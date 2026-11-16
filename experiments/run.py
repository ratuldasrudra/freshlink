"""Collect paired TCP and UDP measurements through the live loopback relay."""

import argparse
import csv
import json
import platform
import random
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from src.freshlink.impairment import Profile
from src.freshlink.live import LiveTelemetry, RATE

SEED = 1729
PATHS = ("tcp", "udp")
HEALTHY = dict(delay_ms=0, jitter_ms=0, bytes_per_second=0, loss=0,
               duplicate=0, reorder=0, reorder_ms=0, corrupt=0, outage=False)
CONDITIONS = {
    "healthy": {},
    "stationary": {},
    "overload": dict(delay_ms=70, jitter_ms=25, bytes_per_second=180),
    "loss_10": dict(loss=0.10, delay_ms=30),
    "loss_30": dict(loss=0.30, delay_ms=30),
    "loss_45": dict(loss=0.45, delay_ms=30),
    "outage": {},
}
SAMPLE_INTERVAL = 0.05
METRICS = ("latency_median_ms", "latency_p95_ms", "latency_p99_ms", "stale_fraction",
           "useful_per_second", "accepted", "source_queue_dropped", "source_queue_delayed",
           "relay_received", "relay_loss", "relay_overflow")


def measure_timer() -> dict:
    """Measure the real wait duration at the harness polling interval."""
    waits = []
    for _ in range(12):
        start = time.perf_counter()
        time.sleep(SAMPLE_INTERVAL)
        waits.append(time.perf_counter() - start)
    return {"clock_resolution_us": time.get_clock_info("perf_counter").resolution * 1e6,
            "poll_sleep_median_ms": statistics.median(waits) * 1000,
            "poll_sleep_max_ms": max(waits) * 1000}


def measure_run(condition: str, seed: int, order: int, repeat: int,
                *, warmup: float, duration: float, timer: dict) -> list[dict]:
    """Return one CSV record per protocol from a fresh telemetry instance."""
    settings = HEALTHY | CONDITIONS[condition]
    timestamp = datetime.now(timezone.utc).isoformat()
    live = LiveTelemetry(Profile(seed=seed), Profile(seed=seed), stationary=condition == "stationary")
    ages = {path: [] for path in PATHS}
    errors = {path: [] for path in PATHS}
    recovery = dict.fromkeys(PATHS)
    outage_start_s = 0.2 * duration if condition == "outage" else None
    outage_end_s = 0.55 * duration if condition == "outage" else None
    resume_ns = None
    outage_applied = False
    gaps_ms = []
    previous_ns = None
    live.start()
    try:
        live.control(settings)
        time.sleep(warmup)
        live.reset()
        start = time.perf_counter()
        start_cpu = time.process_time()
        tick = 0
        while True:
            elapsed = time.perf_counter() - start
            if condition == "outage":
                if not outage_applied and elapsed >= outage_start_s:
                    live.control(settings | {"outage": True}, reset_counters=False)
                    outage_applied = True
                if resume_ns is None and elapsed >= outage_end_s:
                    live.control(settings, reset_counters=False)
                    resume_ns = time.perf_counter_ns()
            state = live.snapshot()
            now_ns = time.perf_counter_ns()
            if state["error"]:
                raise RuntimeError(state["error"])
            if previous_ns is not None:
                gaps_ms.append((now_ns - previous_ns) / 1e6)
            previous_ns = now_ns
            for path in PATHS:
                entry = state[path]
                if entry["age_ms"] is not None:
                    ages[path].append(entry["age_ms"])
                    errors[path].append(entry["position_error"])
                    if (resume_ns is not None and recovery[path] is None
                            and entry["sample_generated_ns"] >= resume_ns
                            and entry["age_ms"] <= state["threshold_ms"]):
                        recovery[path] = (now_ns - resume_ns) / 1e6
            if elapsed >= duration:
                break
            tick += 1
            time.sleep(max(0, start + min(tick * SAMPLE_INTERVAL, duration) - time.perf_counter()))
        cpu_s = time.process_time() - start_cpu
    finally:
        live.stop()
    common = dict(condition=condition, seed=seed, order=order, repeat=repeat, utc=timestamp,
                  python=platform.python_version(), os=platform.platform(),
                  config=json.dumps(settings | {"outage_start_s": outage_start_s,
                                                "outage_end_s": outage_end_s}, sort_keys=True),
                  warmup_s=warmup, target_duration_s=duration, observed_s=state["counter_window_seconds"],
                  generated=state["generated_in_window"], target_hz=RATE,
                  threshold_ms=state["threshold_ms"], cpu_seconds=cpu_s,
                  poll_gap_median_ms=statistics.median(gaps_ms), poll_gap_max_ms=max(gaps_ms), **timer)
    return [
        common | dict(protocol=path, age_observations=len(ages[path]),
                      median_age_ms=statistics.median(ages[path]) if ages[path] else None,
                      median_position_error=statistics.median(errors[path]) if errors[path] else None,
                      recovery_ms=recovery[path], recovery_censored=int(condition == "outage" and recovery[path] is None),
                      recovery_followup_ms=(now_ns - resume_ns) / 1e6 if resume_ns is not None else None)
        | {key: state[path][key] for key in METRICS}
        for path in PATHS
    ]


def main() -> None:
    """Write each completed trial immediately in reproducible blocked order."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="run one short repeat for CI")
    parser.add_argument("--output", type=Path, default=Path("results/raw/runs.csv"))
    args = parser.parse_args()
    repeats, warmup, duration = (1, 0.3, 1.0) if args.quick else (10, 1.5, 6.0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    timer = measure_timer()
    rng = random.Random(SEED)
    with args.output.open("x", encoding="utf-8", newline="") as stream:
        writer = None
        for repeat in range(1, repeats + 1):
            order = list(CONDITIONS)
            rng.shuffle(order)
            for index, condition in enumerate(order, 1):
                rows = measure_run(condition, SEED + repeat, index, repeat,
                                   warmup=warmup, duration=duration, timer=timer)
                if writer is None:
                    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                    writer.writeheader()
                writer.writerows(rows)
                stream.flush()
                print(f"Repeat {repeat}/{repeats} · {condition}", flush=True)


if __name__ == "__main__":
    main()
