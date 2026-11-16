"""Time-weighted freshness metrics for one telemetry receiver."""

import math
from collections import deque
from dataclasses import dataclass, field

from .protocol import Sample

MAX_LATENCIES = 4096
NANOSECONDS_PER_SECOND = 1_000_000_000


def percentile(values: list[float], fraction: float) -> float | None:
    """Return the nearest-rank percentile for a nonempty sequence."""
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(fraction * len(ordered)) - 1]


@dataclass(slots=True)
class ReceiverMetrics:
    """Accumulate accepted samples using a shared monotonic clock."""

    started_ns: int
    threshold_ns: int
    latest: Sample | None = None
    accepted: int = 0
    stale_ns: int = 0
    first_received_ns: int | None = None
    last_observed_ns: int = field(init=False)
    latencies_ms: deque[float] = field(default_factory=lambda: deque(maxlen=MAX_LATENCIES))

    def __post_init__(self) -> None:
        if self.started_ns < 0 or self.threshold_ns <= 0:
            raise ValueError("invalid start or staleness threshold")
        self.last_observed_ns = self.started_ns

    def advance(self, now_ns: int) -> None:
        """Integrate time above threshold since the previous observation."""
        if now_ns < self.last_observed_ns:
            raise ValueError("monotonic time moved backwards")
        if self.latest is not None:
            stale_start = self.latest.generated_ns + self.threshold_ns
            self.stale_ns += max(0, now_ns - max(self.last_observed_ns, stale_start))
        self.last_observed_ns = now_ns

    def accept(self, sample: Sample, now_ns: int) -> None:
        """Record an accepted snapshot and its generation-to-receive delay."""
        if sample.generated_ns > now_ns:
            raise ValueError("sample generation is in the future")
        if self.latest is not None and sample.generated_ns < self.latest.generated_ns:
            raise ValueError("sample generation moved backwards")
        self.advance(now_ns)
        if self.first_received_ns is None:
            self.first_received_ns = now_ns
        self.latest = sample
        self.accepted += 1
        self.latencies_ms.append((now_ns - sample.generated_ns) / 1_000_000)

    def snapshot(self, now_ns: int, truth_x: float, truth_y: float) -> dict[str, float | int | None]:
        """Return current age, stale fraction, latency percentiles, and position error."""
        self.advance(now_ns)
        duration = now_ns - self.started_ns
        samples = list(self.latencies_ms)
        if self.latest is None:
            age_ms = None
            error = None
            stale_fraction = None
        else:
            age_ms = (now_ns - self.latest.generated_ns) / 1_000_000
            error = math.hypot(self.latest.x - truth_x, self.latest.y - truth_y)
            known_duration = now_ns - self.first_received_ns
            stale_fraction = self.stale_ns / known_duration if known_duration else 0.0
        return {
            "age_ms": age_ms,
            "stale_fraction": stale_fraction,
            "latency_median_ms": percentile(samples, 0.5),
            "latency_p95_ms": percentile(samples, 0.95),
            "latency_p99_ms": percentile(samples, 0.99),
            "position_error": error,
            "accepted": self.accepted,
            "useful_per_second": self.accepted * NANOSECONDS_PER_SECOND / duration if duration else 0.0,
        }
