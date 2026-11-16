"""Run a bounded, one-way FreshLink impairment relay on IPv4 loopback."""

import argparse
import asyncio
import errno
import ipaddress
import logging
import math
import socket
import time
from collections.abc import Awaitable, Callable

from src.freshlink.impairment import DEFAULT_QUEUE_PACKETS, MILLISECONDS_PER_SECOND, LinkQueue, Profile
from src.freshlink.protocol import FRAME_LENGTH, MAX_PACKET_BYTES, MIN_PACKET_BYTES, ProtocolError
from src.freshlink.transport import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_TIMEOUT, WSAEMSGSIZE

DEFAULT_RELAY_PORT = 8766
LOGGER = logging.getLogger(__name__)
Address = tuple[str, int]


async def _pump(
    receive: Callable[[], Awaitable[bytes | None]],
    send: Callable[[bytes], Awaitable[None]],
    queue: LinkQueue,
    changed: asyncio.Event | None = None,
) -> None:
    pending = None
    accepting = True
    try:
        while accepting or queue.has_pending:
            now = time.perf_counter()
            payload = queue.pop(now)
            if payload is not None:
                await send(payload)
            if pending is not None and pending.done():
                incoming = pending.result()
                pending = None
                if incoming is None:
                    accepting = False
                else:
                    queue.admit(incoming, time.perf_counter())
            if accepting and pending is None and (not queue.ordered or not queue.full):
                pending = asyncio.ensure_future(receive())
            ready = queue.ready_at
            delay = None if ready is None else max(0.0, ready - time.perf_counter())
            wake = asyncio.create_task(changed.wait()) if changed is not None else None
            waiting = [task for task in (pending, wake) if task is not None]
            try:
                if waiting:
                    await asyncio.wait(waiting, timeout=delay, return_when=asyncio.FIRST_COMPLETED)
                elif delay is not None:
                    await asyncio.sleep(delay)
            finally:
                if wake is not None:
                    if wake.done() and not wake.cancelled() and wake.result():
                        changed.clear()
                    wake.cancel()
                    await asyncio.gather(wake, return_exceptions=True)
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def _read_frame(reader: asyncio.StreamReader, timeout: float) -> bytes | None:
    deadline = asyncio.get_running_loop().time() + timeout
    try:
        async with asyncio.timeout_at(deadline):
            first = await reader.read(1)
    except TimeoutError:
        LOGGER.debug("TCP input idle; draining admitted frames")
        return None
    if not first:
        return None
    async with asyncio.timeout_at(deadline):
        try:
            prefix = first + await reader.readexactly(FRAME_LENGTH.size - len(first))
        except asyncio.IncompleteReadError as error:
            raise ProtocolError("EOF inside TCP prefix") from error
        (length,) = FRAME_LENGTH.unpack(prefix)
        if not MIN_PACKET_BYTES <= length <= MAX_PACKET_BYTES:
            raise ProtocolError("invalid TCP frame size")
        try:
            return prefix + await reader.readexactly(length)
        except asyncio.IncompleteReadError as error:
            raise ProtocolError("EOF inside TCP body") from error


async def _close_writer(writer: asyncio.StreamWriter, timeout: float) -> None:
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), timeout)
    except (TimeoutError, OSError):
        writer.transport.abort()


async def _relay_tcp(listener: socket.socket, target: Address, queue: LinkQueue, timeout: float,
                     changed: asyncio.Event | None = None) -> None:
    loop = asyncio.get_running_loop()
    accepted, _ = await asyncio.wait_for(loop.sock_accept(listener), timeout)
    with accepted, socket.socket() as downstream:
        downstream.setblocking(False)
        await asyncio.wait_for(loop.sock_connect(downstream, target), timeout)
        reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection(sock=accepted, limit=MAX_PACKET_BYTES + FRAME_LENGTH.size), timeout
        )
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(sock=downstream), timeout)
            try:
                async def send(payload: bytes) -> None:
                    writer.write(payload)
                    await asyncio.wait_for(writer.drain(), timeout)

                await _pump(lambda: _read_frame(reader, timeout), send, queue, changed)
            finally:
                await _close_writer(writer, timeout)
        finally:
            await _close_writer(upstream_writer, timeout)


async def _relay_udp(listener: socket.socket, target: Address, queue: LinkQueue, timeout: float,
                     changed: asyncio.Event | None = None) -> None:
    loop = asyncio.get_running_loop()

    async def receive() -> bytes | None:
        deadline = time.perf_counter() + timeout
        try:
            async with asyncio.timeout(timeout):
                while True:
                    try:
                        packet, _ = await loop.sock_recvfrom(listener, MAX_PACKET_BYTES + 1)
                    except ConnectionResetError:
                        LOGGER.debug("ignored UDP ICMP connection reset")
                    except OSError as error:
                        if error.errno not in (errno.EMSGSIZE, WSAEMSGSIZE) and getattr(
                            error, "winerror", None
                        ) != WSAEMSGSIZE:
                            raise
                        LOGGER.debug("rejected oversized UDP datagram")
                    else:
                        if len(packet) <= MAX_PACKET_BYTES:
                            return packet
                        LOGGER.debug("rejected oversized UDP datagram")
                    if time.perf_counter() >= deadline:
                        return None
                    await asyncio.sleep(0)
        except TimeoutError:
            return None

    async def send(payload: bytes) -> None:
        size = await asyncio.wait_for(loop.sock_sendto(listener, payload, target), timeout)
        if size != len(payload):
            raise OSError("short UDP relay send")

    await _pump(receive, send, queue, changed)


async def run_relay(listener: socket.socket, target: Address, profile: Profile, timeout: float,
                    *, queue: LinkQueue | None = None, changed: asyncio.Event | None = None) -> None:
    """Relay from a bound IPv4 loopback socket until EOF, UDP idle, or cancellation."""
    if listener.family != socket.AF_INET or listener.type not in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
        raise ValueError("the relay requires an IPv4 TCP or UDP socket")
    source_host, source_port = listener.getsockname()
    if not all(
        ipaddress.IPv4Address(host).is_loopback for host in (source_host, target[0])
    ):
        raise ValueError("the relay requires IPv4 loopback addresses")
    if not source_port or not 1 <= target[1] <= 65535 or (source_host, source_port) == target:
        raise ValueError("the relay and target require distinct endpoints with nonzero ports")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    ordered = listener.type == socket.SOCK_STREAM
    if queue is None:
        queue = LinkQueue(profile, ordered=ordered)
    elif queue.ordered != ordered or queue.profile != profile:
        raise ValueError("queue must match relay transport and initial profile")
    listener.setblocking(False)
    if ordered:
        await _relay_tcp(listener, target, queue, timeout, changed)
    else:
        await _relay_udp(listener, target, queue, timeout, changed)


def main() -> int:
    """Parse CLI options and manage the relay socket and event loop."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transport", choices=("tcp", "udp"))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_RELAY_PORT)
    parser.add_argument("--target-host", default=DEFAULT_HOST)
    parser.add_argument("--target-port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--delay-ms", type=float, default=0)
    parser.add_argument("--jitter-ms", type=float, default=0)
    parser.add_argument("--bytes-per-second", type=int, default=0)
    parser.add_argument("--queue-packets", type=int, default=DEFAULT_QUEUE_PACKETS)
    parser.add_argument("--loss", type=float, default=0)
    parser.add_argument("--duplicate", type=float, default=0)
    parser.add_argument("--reorder", type=float, default=0)
    parser.add_argument("--reorder-ms", type=float, default=0)
    parser.add_argument("--corrupt", type=float, default=0)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(levelname)s %(message)s")
    try:
        profile = Profile(
            seed=args.seed, delay=args.delay_ms / MILLISECONDS_PER_SECOND,
            jitter=args.jitter_ms / MILLISECONDS_PER_SECOND, bytes_per_second=args.bytes_per_second,
            queue_packets=args.queue_packets, loss=args.loss, duplicate=args.duplicate,
            reorder=args.reorder, reorder_delay=args.reorder_ms / MILLISECONDS_PER_SECOND,
            corrupt=args.corrupt,
        )
        if not ipaddress.IPv4Address(args.host).is_loopback:
            raise ValueError("--host must be an IPv4 loopback address")
        kind = socket.SOCK_STREAM if args.transport == "tcp" else socket.SOCK_DGRAM
        with socket.socket(socket.AF_INET, kind) as listener:
            listener.bind((args.host, args.port))
            if kind == socket.SOCK_STREAM:
                listener.listen(1)
            LOGGER.info("%s relay listening on %s:%d (seed=%d)", args.transport.upper(),
                        *listener.getsockname(), profile.seed)
            asyncio.run(run_relay(listener, (args.target_host, args.target_port), profile, args.timeout))
    except KeyboardInterrupt:
        LOGGER.info("relay stopped by user")
    except TimeoutError:
        LOGGER.error("relay TCP operation or UDP send timed out")
        return 1
    except (OSError, ValueError, OverflowError) as error:
        LOGGER.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
