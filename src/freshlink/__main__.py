"""Run a bounded, standalone FreshLink transport demonstration."""

import argparse
import ipaddress
import logging
import math
import socket
import time

from .protocol import SEQUENCE_MODULUS, ProtocolError, Sample
from .transport import (
    DEFAULT_COUNT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_RATE,
    DEFAULT_TIMEOUT,
    MAX_RATE,
    UdpReceiver,
    receive_tcp,
    send_tcp,
    send_udp,
)

LOGGER = logging.getLogger(__name__)


def _send(sock: socket.socket, args: argparse.Namespace) -> None:
    target = (args.host, args.port)
    if args.transport == "tcp":
        sock.connect(target)
    for index in range(args.count):
        start = time.perf_counter_ns()
        sample = Sample(index % SEQUENCE_MODULUS, start, float(index), 0.0, args.label)
        if args.transport == "tcp":
            send_tcp(sock, sample)
        else:
            send_udp(sock, target, sample)
        if index + 1 < args.count:
            elapsed = (time.perf_counter_ns() - start) / 1e9
            time.sleep(max(0.0, 1 / args.rate - elapsed))


def _receive(sock: socket.socket, args: argparse.Namespace) -> None:
    sock.bind((args.host, args.port))
    if args.transport == "tcp":
        sock.listen(1)
    LOGGER.info("%s listening on %s:%d", args.transport.upper(), *sock.getsockname())
    if args.transport == "tcp":
        connection, _ = sock.accept()
        with connection:
            connection.settimeout(args.timeout)
            while (sample := receive_tcp(connection)) is not None:
                LOGGER.info("seq=%d %r at (%.2f, %.2f)", sample.sequence, sample.label, sample.x, sample.y)
    else:
        receiver = UdpReceiver()
        while True:
            sample = receiver.receive(sock)
            if sample is not None:
                LOGGER.info("seq=%d %r at (%.2f, %.2f)", sample.sequence, sample.label, sample.x, sample.y)


def main() -> int:
    """Parse CLI options and run one bounded sender or receiver."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("send", "receive"))
    parser.add_argument("transport", choices=("tcp", "udp"))
    parser.add_argument("--host", default=DEFAULT_HOST, help="IPv4 loopback address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="sender sample count")
    parser.add_argument("--rate", type=float, default=DEFAULT_RATE, help="sender samples per second")
    parser.add_argument("--label", default="rover")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    try:
        address = ipaddress.IPv4Address(args.host)
    except ipaddress.AddressValueError as error:
        parser.error(str(error))
    if not address.is_loopback:
        parser.error("--host must be an IPv4 loopback address")
    if not 0 <= args.port <= 65535 or (args.role == "send" and args.port == 0):
        parser.error("invalid port for this role")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    if not 1 <= args.rate <= MAX_RATE or args.count < 1:
        parser.error(f"--rate must be between 1 and {MAX_RATE:g}; --count must be positive")

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(levelname)s %(message)s")
    kind = socket.SOCK_STREAM if args.transport == "tcp" else socket.SOCK_DGRAM
    try:
        with socket.socket(socket.AF_INET, kind) as sock:
            sock.settimeout(args.timeout)
            if args.role == "send":
                _send(sock, args)
            else:
                _receive(sock, args)
    except KeyboardInterrupt:
        LOGGER.info("stopped by user")
    except TimeoutError:
        LOGGER.info("%s timed out", args.role)
        return int(args.role == "send")
    except (OSError, ProtocolError) as error:
        LOGGER.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
