"""Deterministic scheduling and IPv4 loopback tests for the impairment relay."""

import asyncio
import socket
import unittest

from src.freshlink.impairment import LinkQueue, Profile
from src.freshlink.protocol import FRAME_LENGTH, Sample, encode
from src.freshlink.transport import DEFAULT_HOST
from tools.impair_proxy import run_relay

TIMEOUT = 2.0


class LinkQueueTests(unittest.TestCase):
    """Use a supplied clock to separate seeded behavior from OS timing."""

    def test_delay_jitter_and_bandwidth_are_reproducible_and_fifo(self) -> None:
        queue = LinkQueue(Profile(seed=17, delay=2, jitter=1, bytes_per_second=2), ordered=True)
        queue.admit(b"abcd", 10)
        queue.admit(b"ef", 10)
        self.assertIsNone(queue.pop(11))
        first = queue.ready_at
        self.assertIsNotNone(first)
        self.assertGreater(first, 12)
        self.assertLess(first, 13)
        self.assertEqual(queue.pop(first), b"abcd")
        self.assertEqual(queue.ready_at, first + 2)
        self.assertIsNone(queue.pop(first + 1))
        self.assertEqual(queue.pop(first + 2), b"ef")

    def test_fixed_seed_exercises_udp_faults(self) -> None:
        profile = Profile(seed=17, loss=0.25, duplicate=0.3, reorder=0.5,
                          reorder_delay=1, corrupt=0.3)
        with self.assertLogs("src.freshlink.impairment", level="DEBUG") as log:
            queue = LinkQueue(profile, ordered=False)
            for number in range(1, 13):
                queue.admit(bytes((number,)), 0)
            output = []
            while (ready := queue.ready_at) is not None:
                output.append(queue.pop(ready))
        for fault in ("loss", "reorder delay", "duplicate", "corruption"):
            self.assertTrue(any(f"udp {fault} input=" in entry for entry in log.output))
        self.assertEqual(output, self._replay(profile))

    @staticmethod
    def _replay(profile: Profile) -> list[bytes | None]:
        queue = LinkQueue(profile, ordered=False)
        for number in range(1, 13):
            queue.admit(bytes((number,)), 0)
        output = []
        while (ready := queue.ready_at) is not None:
            output.append(queue.pop(ready))
        return output

    def test_full_queues_preserve_admitted_payloads(self) -> None:
        tcp = LinkQueue(Profile(queue_packets=1), ordered=True)
        tcp.admit(b"first", 0)
        self.assertTrue(tcp.full)
        with self.assertRaises(BufferError):
            tcp.admit(b"second", 0)
        self.assertEqual(tcp.pop(0), b"first")

        udp = LinkQueue(Profile(queue_packets=1, duplicate=1), ordered=False)
        with self.assertLogs("src.freshlink.impairment", level="DEBUG") as log:
            udp.admit(b"first", 0)
            udp.admit(b"second", 0)
        self.assertTrue(any("udp overflow input=2" in entry for entry in log.output))
        self.assertEqual(udp.pop(0), b"first")
        self.assertIsNone(udp.pop(0))

    def test_tcp_rejects_datagram_only_faults(self) -> None:
        for profile in (Profile(loss=1), Profile(duplicate=1),
                        Profile(reorder=1, reorder_delay=1), Profile(corrupt=1)):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                LinkQueue(profile, ordered=True)


def tcp_frame(sequence: int) -> bytes:
    """Create a wire frame for a TCP relay integration test."""
    packet = encode(Sample(sequence, sequence, 0, 0, "로버"))
    return FRAME_LENGTH.pack(len(packet)) + packet


class RelayTests(unittest.IsolatedAsyncioTestCase):
    """Verify that the actual socket relay uses the scheduler and shuts down."""

    def endpoint(self, kind: int) -> socket.socket:
        """Bind a nonblocking test socket on an available loopback port."""
        sock = self.enterContext(socket.socket(socket.AF_INET, kind))
        sock.setblocking(False)
        sock.bind((DEFAULT_HOST, 0))
        if kind == socket.SOCK_STREAM:
            sock.listen(1)
        return sock

    async def test_tcp_preserves_bytes_under_seeded_jitter_with_one_slot(self) -> None:
        relay = self.endpoint(socket.SOCK_STREAM)
        target = self.endpoint(socket.SOCK_STREAM)
        client = self.enterContext(socket.socket())
        client.setblocking(False)
        loop = asyncio.get_running_loop()
        profile = Profile(seed=17, delay=0.015, jitter=0.01, bytes_per_second=5000, queue_packets=1)
        wire = b"".join(tcp_frame(sequence) for sequence in range(5))
        async with asyncio.timeout(TIMEOUT), asyncio.TaskGroup() as tasks:
            relay_task = tasks.create_task(run_relay(relay, target.getsockname(), profile, TIMEOUT))
            await loop.sock_connect(client, relay.getsockname())
            downstream, _ = await loop.sock_accept(target)
            with downstream:
                downstream.setblocking(False)
                await loop.sock_sendall(client, wire[:3])
                await loop.sock_sendall(client, wire[3:])
                client.shutdown(socket.SHUT_WR)
                received = bytearray()
                while chunk := await loop.sock_recv(downstream, 4096):
                    received.extend(chunk)
                self.assertEqual(bytes(received), wire)
        self.assertTrue(relay_task.done())

    async def test_udp_forwards_seeded_corrupt_duplicates_and_ends_on_idle(self) -> None:
        relay = self.endpoint(socket.SOCK_DGRAM)
        target = self.endpoint(socket.SOCK_DGRAM)
        client = self.endpoint(socket.SOCK_DGRAM)
        loop = asyncio.get_running_loop()
        # Delay exceeds the idle timeout so the relay must drain after intake stops.
        profile = Profile(seed=17, delay=0.25, corrupt=1, duplicate=1)
        packet = encode(Sample(1, 1, 2, 3))
        async with asyncio.timeout(TIMEOUT), asyncio.TaskGroup() as tasks:
            relay_task = tasks.create_task(run_relay(relay, target.getsockname(), profile, 0.15))
            await loop.sock_sendto(client, packet, relay.getsockname())
            first, first_peer = await loop.sock_recvfrom(target, 1500)
            second, second_peer = await loop.sock_recvfrom(target, 1500)
            self.assertEqual(first, second)
            self.assertEqual(first_peer, relay.getsockname())
            self.assertEqual(second_peer, first_peer)
            self.assertEqual(sum((a ^ b).bit_count() for a, b in zip(packet, first, strict=True)), 1)
        self.assertTrue(relay_task.done())
