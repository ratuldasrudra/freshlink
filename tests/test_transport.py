"""Exercise FreshLink framing and datagrams without external network access."""

import random
import socket
import unittest
import zlib
from contextlib import contextmanager
from collections.abc import Iterator

from src.freshlink.protocol import (
    FRAME_LENGTH,
    MAX_LABEL_BYTES,
    MAX_PACKET_BYTES,
    SEQUENCE_HALF_RANGE,
    SEQUENCE_MODULUS,
    ProtocolError,
    Sample,
    decode,
    encode,
)
from src.freshlink.transport import (
    DEFAULT_HOST,
    LOGGER,
    UdpReceiver,
    receive_tcp,
    send_tcp,
    send_udp,
)

TIMEOUT = 2.0
SAMPLE = Sample(17, 200, 1.25, -2.5, "rø버")


@contextmanager
def tcp_pair() -> Iterator[tuple[socket.socket, socket.socket]]:
    """Create two connected TCP sockets using an ephemeral IPv4 loopback port."""
    with socket.socket() as listener, socket.socket() as sender:
        listener.settimeout(TIMEOUT)
        sender.settimeout(TIMEOUT)
        listener.bind((DEFAULT_HOST, 0))
        listener.listen(1)
        sender.connect(listener.getsockname())
        receiver, _ = listener.accept()
        with receiver:
            receiver.settimeout(TIMEOUT)
            yield sender, receiver


class OneByteSocket(socket.socket):
    """Force partial reads even when the kernel buffered the entire stream."""

    def recv(self, bufsize: int, flags: int = 0) -> bytes:
        return super().recv(min(bufsize, 1), flags)


def sample_at(sequence: int, generation: int) -> Sample:
    """Generate a complete test snapshot for one serial number."""
    return Sample(sequence, generation, float(generation), 0.0)


class ProtocolTests(unittest.TestCase):
    """Validate round trips, checksums, and bounds."""

    def test_round_trip_and_maximum_utf8_label(self) -> None:
        self.assertEqual(decode(encode(SAMPLE)), SAMPLE)
        largest = Sample(0, 0, 0.0, 0.0, "é" * (MAX_LABEL_BYTES // 2))
        self.assertEqual(len(encode(largest)), MAX_PACKET_BYTES)
        self.assertEqual(decode(encode(largest)), largest)
        with self.assertRaises(ProtocolError):
            encode(Sample(0, 0, 0, 0, largest.label + "é"))

    def test_malformed_packets(self) -> None:
        packet = encode(SAMPLE)
        malformed = [
            packet[:-1],
            b"\x00" + packet[1:],
            packet[:1] + b"\xff" + packet[2:],
            packet[:9] + b"\x01" + packet[10:],
            packet[:-1] + bytes([packet[-1] ^ 1]),
            b"",
            packet + b"\x00",
        ]
        # Recompute the checksum to exercise the UTF-8 validator itself.
        header, body = packet[:12], packet[16:-1] + b"\xff"
        malformed.append(header + zlib.crc32(header + body).to_bytes(4, "big") + body)
        for invalid in malformed:
            with self.subTest(invalid=invalid), self.assertRaises(ProtocolError):
                decode(invalid)
        for sample in (sample_at(SEQUENCE_MODULUS, 0), Sample(0, 0, float("nan"), 0)):
            with self.subTest(sample=sample), self.assertRaises(ProtocolError):
                encode(sample)


class TcpTests(unittest.TestCase):
    """Verify framing across arbitrary TCP read boundaries."""

    def test_partial_utf8_multiple_frames_and_clean_eof(self) -> None:
        with tcp_pair() as (sender, receiver):
            with OneByteSocket(fileno=receiver.detach()) as byte_reader:
                byte_reader.settimeout(TIMEOUT)
                send_tcp(sender, SAMPLE)
                send_tcp(sender, sample_at(18, 201))
                sender.shutdown(socket.SHUT_WR)
                self.assertEqual(receive_tcp(byte_reader), SAMPLE)
                self.assertEqual(receive_tcp(byte_reader), sample_at(18, 201))
                self.assertIsNone(receive_tcp(byte_reader))
                self.assertEqual(byte_reader.gettimeout(), TIMEOUT)
            self.assertEqual(byte_reader.fileno(), -1)
        self.assertEqual(sender.fileno(), -1)

    def test_rejects_oversize_prefix_before_reading_body(self) -> None:
        with tcp_pair() as (sender, receiver):
            sender.sendall(FRAME_LENGTH.pack(MAX_PACKET_BYTES + 1))
            with self.assertRaisesRegex(ProtocolError, "frame size"):
                receive_tcp(receiver)

    def test_truncated_prefix_and_body_are_not_clean_eof(self) -> None:
        for partial in (b"\x00", FRAME_LENGTH.pack(len(encode(SAMPLE))) + b"\x01"):
            with self.subTest(partial=partial), tcp_pair() as (sender, receiver):
                sender.sendall(partial)
                sender.shutdown(socket.SHUT_WR)
                with self.assertRaisesRegex(ProtocolError, "EOF inside"):
                    receive_tcp(receiver)

    def test_partial_frame_times_out(self) -> None:
        with tcp_pair() as (sender, receiver):
            sender.sendall(FRAME_LENGTH.pack(len(encode(SAMPLE))) + b"\x01")
            receiver.settimeout(0.05)
            with self.assertRaises(TimeoutError):
                receive_tcp(receiver)
            self.assertEqual(receiver.gettimeout(), 0.05)


class UdpTests(unittest.TestCase):
    """Verify snapshot acceptance and rejection over real UDP sockets."""

    def setUp(self) -> None:
        self.sender = self.enterContext(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        self.receiver = self.enterContext(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        self.sender.settimeout(TIMEOUT)
        self.receiver.settimeout(TIMEOUT)
        self.receiver.bind((DEFAULT_HOST, 0))
        self.target = self.receiver.getsockname()
        self.state = UdpReceiver()

    def exchange(self, sample: Sample) -> Sample | None:
        """Send one datagram and consume it before injecting the next event."""
        send_udp(self.sender, self.target, sample)
        return self.state.receive(self.receiver)

    def test_seeded_loss_duplication_reordering_and_corruption(self) -> None:
        seed = 17
        randomizer = random.Random(seed)
        loss = randomizer.choice((2, 3))
        delayed = 5
        accepted = [0, 1, *(i for i in range(2, 8) if i not in (loss, delayed))]
        with self.assertLogs(LOGGER, level="DEBUG") as trace:
            for sequence in range(8):
                if sequence == loss:
                    LOGGER.debug("fixture seed=%d dropped seq=%d before send", seed, sequence)
                    continue
                if sequence == delayed:
                    LOGGER.debug("fixture held seq=%d until after seq=7", delayed)
                    continue
                self.assertEqual(self.exchange(sample_at(sequence, sequence)), sample_at(sequence, sequence))
            self.assertIsNone(self.exchange(sample_at(7, 7)))
            self.assertIsNone(self.exchange(sample_at(delayed, delayed)))
            corrupt = bytearray(encode(sample_at(8, 8)))
            corrupt[-1] ^= 1
            LOGGER.debug("fixture injected corrupt seq=8")
            self.sender.sendto(corrupt, self.target)
            self.assertIsNone(self.state.receive(self.receiver))
        observed = [
            int(log.rsplit("=", 1)[1]) for log in trace.output if "UDP accepted seq=" in log
        ]
        self.assertEqual(observed, accepted)
        self.assertEqual(self.state.latest, sample_at(7, 7))

    def test_wraparound_and_stale_or_ambiguous_serials(self) -> None:
        for sequence, generation in ((SEQUENCE_MODULUS - 2, 1), (SEQUENCE_MODULUS - 1, 2), (0, 3)):
            sample = sample_at(sequence, generation)
            self.assertEqual(self.exchange(sample), sample)
        self.assertIsNone(self.exchange(sample_at(SEQUENCE_MODULUS - 1, 2)))
        self.assertIsNone(self.exchange(sample_at(SEQUENCE_HALF_RANGE, 4)))
        self.assertIsNone(self.exchange(sample_at(1, 1)))
        self.assertEqual(self.exchange(sample_at(1, 4)), sample_at(1, 4))

    def test_truncation_and_oversized_valid_prefix(self) -> None:
        packet = encode(Sample(7, 7, 0, 0, "x" * MAX_LABEL_BYTES))
        for invalid in (packet[:-1], packet + b"\x00" * 64, b""):
            with self.subTest(size=len(invalid)):
                self.sender.sendto(invalid, self.target)
                self.assertIsNone(self.state.receive(self.receiver))
        self.assertIsNone(self.state.latest)
        self.sender.sendto(packet, self.target)
        self.assertEqual(self.state.receive(self.receiver), decode(packet))

    def test_timeout_and_context_closure(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as idle:
            idle.settimeout(0.05)
            idle.bind((DEFAULT_HOST, 0))
            with self.assertRaises(TimeoutError):
                self.state.receive(idle)
        self.assertEqual(idle.fileno(), -1)
