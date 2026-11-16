"""Version 1 telemetry format shared by TCP and UDP."""

import math
import struct
import zlib
from dataclasses import dataclass

VERSION = 1
TELEMETRY = 1
RESERVED_ACK = 0
SEQUENCE_MODULUS = 1 << 32
SEQUENCE_HALF_RANGE = SEQUENCE_MODULUS // 2
MAX_PACKET_BYTES = 1200
FRAME_LENGTH = struct.Struct("!I")
_HEADER = struct.Struct("!BBIIH")
_CHECKSUM = struct.Struct("!I")
_POSITION = struct.Struct("!Qdd")
MIN_PACKET_BYTES = _HEADER.size + _CHECKSUM.size + _POSITION.size
MAX_LABEL_BYTES = MAX_PACKET_BYTES - MIN_PACKET_BYTES


class ProtocolError(ValueError):
    """A message violates FreshLink framing or packet rules."""


@dataclass(frozen=True, slots=True)
class Sample:
    """One complete rover state generated on the local monotonic clock."""

    sequence: int
    generated_ns: int
    x: float
    y: float
    label: str = ""


def encode(sample: Sample) -> bytes:
    """Serialize a sample and cover its header and body with CRC-32."""
    if not (0 <= sample.sequence < SEQUENCE_MODULUS and 0 <= sample.generated_ns < 1 << 64):
        raise ProtocolError("sequence or timestamp outside wire range")
    if not (math.isfinite(sample.x) and math.isfinite(sample.y)):
        raise ProtocolError("non-finite coordinate")
    if len(sample.label) > MAX_LABEL_BYTES:
        raise ProtocolError("label too long")
    try:
        label = sample.label.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ProtocolError("invalid UTF-8 label") from error
    if len(label) > MAX_LABEL_BYTES:
        raise ProtocolError("label too long")
    body = _POSITION.pack(sample.generated_ns, sample.x, sample.y) + label
    header = _HEADER.pack(VERSION, TELEMETRY, sample.sequence, RESERVED_ACK, len(body))
    return header + _CHECKSUM.pack(zlib.crc32(header + body)) + body


def decode(packet: bytes) -> Sample:
    """Validate an entire packet before reading coordinates or UTF-8."""
    if not MIN_PACKET_BYTES <= len(packet) <= MAX_PACKET_BYTES:
        raise ProtocolError("invalid packet size")
    version, kind, sequence, ack, size = _HEADER.unpack_from(packet)
    if (version, kind, ack) != (VERSION, TELEMETRY, RESERVED_ACK):
        raise ProtocolError("unsupported header")
    start = _HEADER.size + _CHECKSUM.size
    body = packet[start:]
    if size != len(body):
        raise ProtocolError("body length mismatch")
    (checksum,) = _CHECKSUM.unpack_from(packet, _HEADER.size)
    if zlib.crc32(packet[:_HEADER.size] + body) != checksum:
        raise ProtocolError("checksum mismatch")
    generated_ns, x, y = _POSITION.unpack_from(body)
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ProtocolError("non-finite coordinate")
    try:
        label = body[_POSITION.size:].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProtocolError("invalid UTF-8 label") from error
    return Sample(sequence, generated_ns, x, y, label)
