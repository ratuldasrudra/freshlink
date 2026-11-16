"""Run one shared source through real TCP and UDP loopback relays."""

import asyncio
import errno
import math
import socket
import threading
import time

from .metrics import ReceiverMetrics
from .protocol import FRAME_LENGTH, MAX_PACKET_BYTES, Sample, decode, encode
from .transport import DEFAULT_HOST, UdpReceiver, WSAEMSGSIZE
from .impairment import Profile
from tools.impair_proxy import run_relay

RATE = 10
THRESHOLD_NS = 500_000_000
IO_TIMEOUT = 5.0
STOP_TIMEOUT = 8.0


def _bind(kind: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, kind)
    try:
        sock.bind((DEFAULT_HOST, 0))
        sock.setblocking(False)
        if kind == socket.SOCK_STREAM:
            sock.listen(1)
        return sock
    except BaseException:
        sock.close()
        raise


class LiveTelemetry:
    """Own relay sockets, a shared source, and synchronized receiver metrics."""

    def __init__(self, tcp_profile: Profile = Profile(), udp_profile: Profile = Profile()) -> None:
        self.tcp_profile = tcp_profile
        self.udp_profile = udp_profile
        self.lock = threading.Lock()
        self.started_ns = time.perf_counter_ns()
        self.metrics = {name: ReceiverMetrics(self.started_ns, THRESHOLD_NS) for name in ("tcp", "udp")}
        self.truth = (0.0, 0.0)
        self.sequence = 0
        self.error: str | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self.ready = threading.Event()
        self.stopping = threading.Event()

    def start(self) -> None:
        """Start the socket workers and wait until initialization finishes."""
        if self.thread is not None:
            raise RuntimeError("telemetry already started")
        self.thread = threading.Thread(target=self._thread_main, name="freshlink-telemetry")
        self.thread.start()
        if not self.ready.wait(IO_TIMEOUT):
            self.stop()
            raise TimeoutError("telemetry startup timed out")
        if self.error:
            self.stop()
            raise RuntimeError(self.error)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as error:
            with self.lock:
                self.error = str(error)
        finally:
            self.ready.set()

    async def _run(self) -> None:
        self.loop = asyncio.get_running_loop()
        sockets = []
        tasks = []
        try:
            tcp_target = _bind(socket.SOCK_STREAM)
            sockets.append(tcp_target)
            udp_target = _bind(socket.SOCK_DGRAM)
            sockets.append(udp_target)
            tcp_relay = _bind(socket.SOCK_STREAM)
            sockets.append(tcp_relay)
            udp_relay = _bind(socket.SOCK_DGRAM)
            sockets.append(udp_relay)
            tcp_sender = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(tcp_sender)
            tcp_sender.setblocking(False)
            udp_sender = _bind(socket.SOCK_DGRAM)
            sockets.append(udp_sender)
            tasks = [
                asyncio.create_task(run_relay(tcp_relay, tcp_target.getsockname(), self.tcp_profile, IO_TIMEOUT)),
                asyncio.create_task(run_relay(udp_relay, udp_target.getsockname(), self.udp_profile, IO_TIMEOUT)),
            ]
            await asyncio.wait_for(self.loop.sock_connect(tcp_sender, tcp_relay.getsockname()), IO_TIMEOUT)
            receiver, _ = await asyncio.wait_for(self.loop.sock_accept(tcp_target), IO_TIMEOUT)
            sockets.append(receiver)
            receiver.setblocking(False)
            tasks.extend([
                asyncio.create_task(self._tcp_receive(receiver)),
                asyncio.create_task(self._udp_receive(udp_target)),
                asyncio.create_task(self._source(tcp_sender, udp_sender, udp_relay.getsockname())),
            ])
            self.ready.set()
            stop_task = asyncio.create_task(self._wait_for_stop())
            tasks.append(stop_task)
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            if stop_task not in done:
                raise RuntimeError("telemetry worker stopped unexpectedly")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for sock in sockets:
                sock.close()
            self.loop = None

    async def _wait_for_stop(self) -> None:
        while not self.stopping.is_set():
            await asyncio.sleep(0.1)

    async def _source(self, tcp: socket.socket, udp: socket.socket, udp_target: tuple[str, int]) -> None:
        loop = asyncio.get_running_loop()
        while True:
            now = time.perf_counter_ns()
            elapsed = (now - self.started_ns) / 1_000_000_000
            x, y = math.cos(elapsed), math.sin(elapsed)
            with self.lock:
                sample = Sample(self.sequence, now, x, y, "rover")
                self.truth = (x, y)
                self.sequence = (self.sequence + 1) % (1 << 32)
            packet = encode(sample)
            await asyncio.wait_for(loop.sock_sendall(tcp, FRAME_LENGTH.pack(len(packet)) + packet), IO_TIMEOUT)
            await asyncio.wait_for(loop.sock_sendto(udp, packet, udp_target), IO_TIMEOUT)
            await asyncio.sleep(1 / RATE)

    async def _tcp_receive(self, sock: socket.socket) -> None:
        reader, writer = await asyncio.open_connection(sock=sock)
        try:
            while True:
                async with asyncio.timeout(IO_TIMEOUT):
                    prefix = await reader.readexactly(FRAME_LENGTH.size)
                    (size,) = FRAME_LENGTH.unpack(prefix)
                    if not 1 <= size <= MAX_PACKET_BYTES:
                        raise ValueError("invalid TCP packet length")
                    sample = decode(await reader.readexactly(size))
                with self.lock:
                    self.metrics["tcp"].accept(sample, time.perf_counter_ns())
        finally:
            writer.close()
            await writer.wait_closed()

    async def _udp_receive(self, sock: socket.socket) -> None:
        receiver = UdpReceiver()
        loop = asyncio.get_running_loop()
        while True:
            try:
                packet, peer = await asyncio.wait_for(loop.sock_recvfrom(sock, MAX_PACKET_BYTES + 1), IO_TIMEOUT)
            except ConnectionResetError:
                continue
            except OSError as error:
                if error.errno not in (errno.EMSGSIZE, WSAEMSGSIZE) and getattr(
                    error, "winerror", None
                ) != WSAEMSGSIZE:
                    raise
                continue
            sample = receiver.accept_packet(packet, peer)
            if sample is not None:
                with self.lock:
                    self.metrics["udp"].accept(sample, time.perf_counter_ns())

    def snapshot(self) -> dict:
        """Return a coherent current view for SSE clients."""
        with self.lock:
            now = time.perf_counter_ns()
            return {
                "truth": {"x": self.truth[0], "y": self.truth[1]},
                "sequence": self.sequence,
                "error": self.error,
                "tcp": self.metrics["tcp"].snapshot(now, *self.truth),
                "udp": self.metrics["udp"].snapshot(now, *self.truth),
            }

    def stop(self) -> None:
        """Stop all workers and wait for their sockets to close."""
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(STOP_TIMEOUT)
            if self.thread.is_alive():
                raise TimeoutError("telemetry shutdown timed out")
