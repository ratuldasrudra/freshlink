"""Seeded, bounded scheduling of FreshLink relay traffic."""

import heapq
import logging
import math
import random
from dataclasses import dataclass

LOGGER = logging.getLogger(__name__)
DEFAULT_QUEUE_PACKETS = 64
MAX_QUEUE_PACKETS = 4096
MILLISECONDS_PER_SECOND = 1000


@dataclass(frozen=True, slots=True)
class Profile:
    """Delay in seconds, probabilities in [0, 1], and an optional byte rate."""

    seed: int = 0
    delay: float = 0.0
    jitter: float = 0.0
    bytes_per_second: int = 0
    queue_packets: int = DEFAULT_QUEUE_PACKETS
    loss: float = 0.0
    duplicate: float = 0.0
    reorder: float = 0.0
    reorder_delay: float = 0.0
    corrupt: float = 0.0

    def __post_init__(self) -> None:
        for duration in (self.delay, self.jitter, self.reorder_delay):
            if not math.isfinite(duration) or duration < 0:
                raise ValueError("delays and jitter must be finite and nonnegative")
        if not math.isfinite(self.delay + self.jitter + self.reorder_delay):
            raise ValueError("combined delay is too large")
        for probability in (self.loss, self.duplicate, self.reorder, self.corrupt):
            if not 0 <= probability <= 1:
                raise ValueError("fault probabilities must be between zero and one")
        if self.reorder > 0 and self.reorder_delay == 0:
            raise ValueError("reordering requires a positive extra delay")
        if self.bytes_per_second < 0 or not 1 <= self.queue_packets <= MAX_QUEUE_PACKETS:
            raise ValueError(f"require nonnegative byte rate and 1–{MAX_QUEUE_PACKETS} queue slots")


class LinkQueue:
    """Schedule one direction of one stream using caller-supplied monotonic times."""

    def __init__(self, profile: Profile, *, ordered: bool) -> None:
        if ordered and (profile.loss or profile.duplicate or profile.reorder or profile.corrupt):
            raise ValueError("TCP supports only delay, jitter, and bandwidth limiting")
        self.profile = profile
        self.ordered = ordered
        self._random = random.Random(profile.seed)
        self._pending: list[tuple[float, int, int, bytes]] = []
        self._ordinal = 0
        self._input = 0
        self._last_eligible = 0.0
        self._next_send = 0.0
        self.paused = False
        self.released = 0
        self.lost = 0
        self.overflow = 0

    @property
    def full(self) -> bool:
        """Report whether all queue slots are occupied."""
        return len(self._pending) >= self.profile.queue_packets

    @property
    def has_pending(self) -> bool:
        """Report queued traffic even when releases are paused."""
        return bool(self._pending)

    def admit(self, payload: bytes, now: float) -> None:
        """Queue a TCP frame unchanged or apply seeded faults to one UDP datagram."""
        self._input += 1
        number = self._input
        profile = self.profile
        if self.ordered and self.full:
            raise BufferError("TCP input must wait for a free relay slot")
        if not self.ordered and self._random.random() < profile.loss:
            self.lost += 1
            LOGGER.debug("udp loss input=%d", number)
            return
        eligible = now + max(0.0, profile.delay + self._random.uniform(-profile.jitter, profile.jitter))
        copies = 1
        if self.ordered:
            eligible = max(eligible, self._last_eligible)
            self._last_eligible = eligible
        else:
            if self._random.random() < profile.reorder:
                eligible += profile.reorder_delay
                LOGGER.debug("udp reorder delay input=%d", number)
            if self._random.random() < profile.corrupt and payload:
                changed = bytearray(payload)
                changed[self._random.randrange(len(changed))] ^= 1 << self._random.randrange(8)
                payload = bytes(changed)
                LOGGER.debug("udp corruption input=%d", number)
            if self._random.random() < profile.duplicate:
                copies = 2
                LOGGER.debug("udp duplicate input=%d", number)

        for index in range(copies):
            if self.full:
                self.overflow += copies - index
                LOGGER.debug("udp overflow input=%d", number)
                break
            self._ordinal += 1
            heapq.heappush(self._pending, (eligible, self._ordinal, number, payload))
            LOGGER.debug("queued input=%d depth=%d", number, len(self._pending))

    @property
    def ready_at(self) -> float | None:
        """Return the next eligibility time including bandwidth pacing."""
        if not self._pending or self.paused:
            return None
        return max(self._pending[0][0], self._next_send)

    def update_profile(self, profile: Profile) -> None:
        """Apply new fault probabilities to future inputs and preserve queued items."""
        if self.ordered and (profile.loss or profile.duplicate or profile.reorder or profile.corrupt):
            raise ValueError("TCP supports only delay, jitter, and bandwidth limiting")
        if profile.seed != self.profile.seed or profile.queue_packets != self.profile.queue_packets:
            raise ValueError("seed and queue capacity cannot change during a run")
        self.profile = profile

    def pop(self, now: float) -> bytes | None:
        """Release the next eligible payload and schedule its serialization gap."""
        ready = self.ready_at
        if ready is None or now < ready:
            return None
        _, _, number, payload = heapq.heappop(self._pending)
        self.released += 1
        if self.profile.bytes_per_second:
            self._next_send = now + len(payload) / self.profile.bytes_per_second
        LOGGER.debug("released input=%d depth=%d", number, len(self._pending))
        return payload
