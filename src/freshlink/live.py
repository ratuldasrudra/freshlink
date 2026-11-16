"""Run one shared source through real TCP and UDP loopback relays."""

import asyncio
import errno
import math
import socket
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .metrics import ReceiverMetrics
from .protocol import FRAME_LENGTH, MAX_PACKET_BYTES, Sample, decode, encode
from .transport import DEFAULT_HOST, UdpReceiver, WSAEMSGSIZE
from .impairment import LinkQueue, Profile
from tools.impair_proxy import run_relay

RATE = 10
THRESHOLD_NS = 500_000_000
IO_TIMEOUT = 5.0
STOP_TIMEOUT = 8.0
SENDER_QUEUE_SIZE = 16


@dataclass
class SenderStats:
    """Track application queue effects independently of relay effects."""

    dropped: int = 0
    delayed: int = 0
    busy: bool = False
    queue_wait_ms: float | None = None


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
        self.queues: dict[str, LinkQueue] = {}
        self.changed: dict[str, asyncio.Event] = {}
        self.sender_stats = {name: SenderStats() for name in self.metrics}

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
            self.changed = {"tcp": asyncio.Event(), "udp": asyncio.Event()}
            self.queues = {
                "tcp": LinkQueue(self.tcp_profile, ordered=True),
                "udp": LinkQueue(self.udp_profile, ordered=False),
            }
            tasks = [
                asyncio.create_task(run_relay(tcp_relay, tcp_target.getsockname(), self.tcp_profile, IO_TIMEOUT,
                                              queue=self.queues["tcp"], changed=self.changed["tcp"])),
                asyncio.create_task(run_relay(udp_relay, udp_target.getsockname(), self.udp_profile, IO_TIMEOUT,
                                              queue=self.queues["udp"], changed=self.changed["udp"])),
            ]
            await asyncio.wait_for(self.loop.sock_connect(tcp_sender, tcp_relay.getsockname()), IO_TIMEOUT)
            receiver, _ = await asyncio.wait_for(self.loop.sock_accept(tcp_target), IO_TIMEOUT)
            sockets.append(receiver)
            receiver.setblocking(False)
            outgoing = {name: asyncio.Queue(maxsize=SENDER_QUEUE_SIZE) for name in self.metrics}

            async def send_tcp(packet: bytes) -> None:
                await self._send_tcp(tcp_sender, packet)

            async def send_udp(packet: bytes) -> None:
                await asyncio.wait_for(
                    self.loop.sock_sendto(udp_sender, packet, udp_relay.getsockname()), IO_TIMEOUT
                )

            tasks.extend([
                asyncio.create_task(self._tcp_receive(receiver)),
                asyncio.create_task(self._udp_receive(udp_target)),
                asyncio.create_task(self._source(outgoing)),
                asyncio.create_task(self._sender("tcp", outgoing["tcp"], send_tcp)),
                asyncio.create_task(self._sender("udp", outgoing["udp"], send_udp)),
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

    async def _source(self, outgoing: dict[str, asyncio.Queue[Sample]]) -> None:
        while True:
            now = time.perf_counter_ns()
            elapsed = (now - self.started_ns) / 1_000_000_000
            x, y = math.cos(elapsed), math.sin(elapsed)
            with self.lock:
                sample = Sample(self.sequence, now, x, y, "rover")
                self.truth = (x, y)
                self.sequence = (self.sequence + 1) % (1 << 32)
                for name, queue in outgoing.items():
                    stats = self.sender_stats[name]
                    if queue.full():
                        stats.dropped += 1
                        continue
                    if stats.busy or not queue.empty():
                        stats.delayed += 1
                    queue.put_nowait(sample)
            await asyncio.sleep(1 / RATE)

    async def _sender(self, name: str, queue: asyncio.Queue[Sample],
                      send: Callable[[bytes], Awaitable[None]]) -> None:
        stats = self.sender_stats[name]
        while True:
            try:
                sample = await asyncio.wait_for(queue.get(), IO_TIMEOUT)
            except TimeoutError:
                continue
            with self.lock:
                stats.busy = True
                stats.queue_wait_ms = (time.perf_counter_ns() - sample.generated_ns) / 1_000_000
            try:
                await send(encode(sample))
            finally:
                with self.lock:
                    stats.busy = False

    async def _send_tcp(self, sock: socket.socket, packet: bytes) -> None:
        loop = asyncio.get_running_loop()
        # Keep one in-progress frame intact across backpressure intervals.
        send = asyncio.create_task(loop.sock_sendall(sock, FRAME_LENGTH.pack(len(packet)) + packet))
        try:
            while not send.done():
                await asyncio.wait((send,), timeout=IO_TIMEOUT)
            send.result()
        finally:
            if not send.done():
                send.cancel()
                await asyncio.gather(send, return_exceptions=True)

    async def _tcp_receive(self, sock: socket.socket) -> None:
        reader, writer = await asyncio.open_connection(sock=sock)
        try:
            while True:
                try:
                    first = await asyncio.wait_for(reader.read(1), IO_TIMEOUT)
                except TimeoutError:
                    continue
                if not first:
                    raise EOFError("TCP receiver disconnected")
                async with asyncio.timeout(IO_TIMEOUT):
                    prefix = first + await reader.readexactly(FRAME_LENGTH.size - 1)
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
            except TimeoutError:
                continue
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
                **{name: {
                    **metrics.snapshot(now, *self.truth),
                    "source_queue_dropped": self.sender_stats[name].dropped,
                    "source_queue_delayed": self.sender_stats[name].delayed,
                    "source_queue_wait_ms": self.sender_stats[name].queue_wait_ms,
                } for name, metrics in self.metrics.items()},
            }

    def control(self, settings: dict) -> None:
        """Apply validated settings atomically on the relay event loop."""
        from concurrent.futures import Future

        allowed = {"delay_ms", "jitter_ms", "bytes_per_second", "loss", "duplicate",
                   "reorder", "reorder_ms", "corrupt", "outage"}
        if not isinstance(settings, dict) or set(settings) != allowed:
            raise ValueError("control requires exactly the documented fields")
        if type(settings["outage"]) is not bool:
            raise ValueError("outage must be a boolean")
        for key in allowed - {"outage"}:
            if type(settings[key]) not in (int, float) or not math.isfinite(settings[key]):
                raise ValueError(f"{key} must be a finite number")
        if type(settings["bytes_per_second"]) is not int or not 0 <= settings["bytes_per_second"] <= 1_000_000:
            raise ValueError("bytes_per_second must be an integer from 0 to 1000000")
        if any(not 0 <= settings[key] <= 10000 for key in ("delay_ms", "jitter_ms", "reorder_ms")):
            raise ValueError("delay values must be between 0 and 10000 ms")
        shared = dict(delay=settings["delay_ms"] / 1000, jitter=settings["jitter_ms"] / 1000,
                      bytes_per_second=settings["bytes_per_second"])
        tcp = Profile(seed=self.tcp_profile.seed, queue_packets=self.tcp_profile.queue_packets, **shared)
        udp = Profile(seed=self.udp_profile.seed, queue_packets=self.udp_profile.queue_packets,
                      loss=1.0 if settings["outage"] else settings["loss"],
                      duplicate=settings["duplicate"], reorder=settings["reorder"],
                      reorder_delay=settings["reorder_ms"] / 1000, corrupt=settings["corrupt"], **shared)
        loop = self.loop
        if loop is None or not loop.is_running():
            raise RuntimeError("telemetry is not running")
        result: Future[None] = Future()

        def apply() -> None:
            try:
                self.queues["tcp"].update_profile(tcp)
                self.queues["udp"].update_profile(udp)
                self.queues["tcp"].paused = settings["outage"]
                self.changed["tcp"].set()
                self.changed["udp"].set()
                result.set_result(None)
            except Exception as error:
                result.set_exception(error)

        loop.call_soon_threadsafe(apply)
        result.result(timeout=IO_TIMEOUT)

    def stop(self) -> None:
        """Stop all workers and wait for their sockets to close."""
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(STOP_TIMEOUT)
            if self.thread.is_alive():
                raise TimeoutError("telemetry shutdown timed out")
