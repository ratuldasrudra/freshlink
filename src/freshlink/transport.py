"""Blocking socket I/O for a single FreshLink telemetry stream."""

import errno
import logging
import math
import socket
import time
from dataclasses import dataclass

from .protocol import (
    FRAME_LENGTH,
    MAX_PACKET_BYTES,
    MIN_PACKET_BYTES,
    SEQUENCE_HALF_RANGE,
    SEQUENCE_MODULUS,
    ProtocolError,
    Sample,
    decode,
    encode,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_TIMEOUT = 3.0
DEFAULT_RATE = 10.0
MAX_RATE = 100.0
DEFAULT_COUNT = 20
WSAEMSGSIZE = 10040
LOGGER = logging.getLogger(__name__)


def _require_timeout(sock: socket.socket) -> float:
    timeout = sock.gettimeout()
    if timeout is None or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("socket needs a finite positive timeout")
    return timeout


def _read_exact(
    sock: socket.socket, size: int, deadline: float, *, allow_eof: bool = False
) -> bytes | None:
    data = bytearray()
    while len(data) < size:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise TimeoutError("TCP frame deadline expired")
        sock.settimeout(remaining)
        chunk = sock.recv(size - len(data))
        if not chunk:
            if allow_eof and not data:
                return None
            raise ProtocolError("EOF inside TCP frame")
        data.extend(chunk)
    return bytes(data)


def send_tcp(sock: socket.socket, sample: Sample) -> None:
    """Write a complete length-prefixed packet or raise on failure."""
    _require_timeout(sock)
    packet = encode(sample)
    sock.sendall(FRAME_LENGTH.pack(len(packet)) + packet)
    LOGGER.debug("TCP sent seq=%d", sample.sequence)


def read_tcp_frame(sock: socket.socket) -> bytes | None:
    """Read one bounded packet body, or return None at a clean frame boundary.

    A receiver must close the stream after an exception. A partial read cannot
    be resumed by starting another frame.
    """
    timeout = _require_timeout(sock)
    deadline = time.perf_counter() + timeout
    try:
        prefix = _read_exact(sock, FRAME_LENGTH.size, deadline, allow_eof=True)
        if prefix is None:
            return None
        (size,) = FRAME_LENGTH.unpack(prefix)
        if not MIN_PACKET_BYTES <= size <= MAX_PACKET_BYTES:
            raise ProtocolError("invalid TCP frame size")
        return _read_exact(sock, size, deadline)
    except TimeoutError:
        LOGGER.debug("TCP receive timeout")
        raise
    finally:
        sock.settimeout(timeout)


def receive_tcp(sock: socket.socket) -> Sample | None:
    """Read and validate one TCP sample, or return None for clean EOF."""
    packet = read_tcp_frame(sock)
    if packet is None:
        return None
    sample = decode(packet)
    LOGGER.debug("TCP received seq=%d", sample.sequence)
    return sample


def send_udp(sock: socket.socket, target: tuple[str, int], sample: Sample) -> None:
    """Send one sample as a datagram, with no application retry."""
    _require_timeout(sock)
    packet = encode(sample)
    if sock.sendto(packet, target) != len(packet):
        raise OSError("short UDP send")
    LOGGER.debug("UDP sent seq=%d", sample.sequence)


@dataclass(slots=True)
class UdpReceiver:
    """Accept newer snapshots from one sender for the duration of a run."""

    peer: tuple[str, int] | None = None
    latest: Sample | None = None

    def receive(self, sock: socket.socket) -> Sample | None:
        """Consume one receive event. Rejections return None and timeouts raise."""
        _require_timeout(sock)
        try:
            # The extra byte prevents Linux truncation from admitting a valid prefix.
            packet, peer = sock.recvfrom(MAX_PACKET_BYTES + 1)
        except TimeoutError:
            LOGGER.debug("UDP receive timeout")
            raise
        except ConnectionResetError:
            LOGGER.debug("UDP ignored ICMP connection reset")
            return None
        except OSError as error:
            if error.errno not in (errno.EMSGSIZE, WSAEMSGSIZE) and getattr(
                error, "winerror", None
            ) != WSAEMSGSIZE:
                raise
            LOGGER.debug("UDP rejected: oversized datagram")
            return None
        return self.accept_packet(packet, peer)

    def accept_packet(self, packet: bytes, peer: tuple[str, int]) -> Sample | None:
        """Validate a received datagram and accept it only if it advances state."""
        if self.peer is not None and peer != self.peer:
            LOGGER.debug("UDP rejected: unexpected sender")
            return None
        try:
            sample = decode(packet)
        except ProtocolError as error:
            LOGGER.debug("UDP rejected: %s", error)
            return None

        if self.latest is not None:
            # RFC 1982 comparison: equal and half-space values cannot advance state.
            distance = (sample.sequence - self.latest.sequence) % SEQUENCE_MODULUS
            if distance == 0:
                LOGGER.debug("UDP duplicate seq=%d", sample.sequence)
                return None
            if distance >= SEQUENCE_HALF_RANGE:
                LOGGER.debug("UDP stale or ambiguous seq=%d", sample.sequence)
                return None
            if sample.generated_ns < self.latest.generated_ns:
                LOGGER.debug("UDP rejected: source clock moved backwards")
                return None
            if distance > 1:
                LOGGER.debug("UDP gap before seq=%d skipped=%d", sample.sequence, distance - 1)
        self.peer = peer
        self.latest = sample
        LOGGER.debug("UDP accepted seq=%d", sample.sequence)
        return sample
