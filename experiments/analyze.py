"""Summarize and plot the complete run CSV with standard-library tooling."""

import argparse
import csv
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

from .run import CONDITIONS, PATHS, SAMPLE_INTERVAL

BOOTSTRAP_DRAWS = 4000
BOOTSTRAP_SEED = 2587
METRICS = ("latency_median_ms", "latency_p95_ms", "latency_p99_ms", "median_age_ms",
           "stale_fraction", "median_position_error", "useful_per_second", "recovery_ms",
           "source_queue_dropped", "source_queue_delayed", "relay_overflow")


def summarize(values: list[float]) -> dict:
    """Summarize trial-level values and bootstrap a percentile CI for the median."""
    if not values:
        return dict(n=0, median=None, q1=None, q3=None, variance=None, ci_low=None, ci_high=None)
    if len(values) == 1:
        return dict(n=1, median=values[0], q1=None, q3=None, variance=None, ci_low=None, ci_high=None)
    rng = random.Random(BOOTSTRAP_SEED)
    resampled = [statistics.median(rng.choices(values, k=len(values))) for _ in range(BOOTSTRAP_DRAWS)]
    interval = statistics.quantiles(resampled, n=40, method="inclusive")
    lower, _, upper = statistics.quantiles(values, n=4, method="inclusive")
    return dict(n=len(values), median=statistics.median(values), q1=lower, q3=upper,
                variance=statistics.variance(values), ci_low=interval[0], ci_high=interval[-1])


def read_runs(path: Path) -> list[dict]:
    """Load run CSV records, retaining missing values as empty fields."""
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def group_runs(rows: list[dict], expected_repeats: int | None = None) -> dict:
    """Validate that every repeat has exactly one row for each condition and protocol."""
    groups = defaultdict(list)
    seen = set()
    if not rows:
        raise ValueError("run data is empty")
    for row in rows:
        pair = row["condition"], row["protocol"]
        key = (*pair, row["repeat"])
        if key in seen or pair[0] not in CONDITIONS or pair[1] not in PATHS:
            raise ValueError(f"unexpected or duplicate trial row: {key}")
        seen.add(key)
        groups[pair].append(row)
    repeats = {row["repeat"] for row in rows}
    if expected_repeats is not None and repeats != {str(i) for i in range(1, expected_repeats + 1)}:
        raise ValueError(f"expected repeats 1 through {expected_repeats}, got {sorted(repeats)}")
    expected = {(condition, protocol, repeat) for condition in CONDITIONS for protocol in PATHS
                for repeat in repeats}
    if seen != expected:
        raise ValueError(f"incomplete trial rows: {sorted(expected - seen)}")
    return groups


def write_summary(groups: dict, path: Path) -> dict:
    """Write trial counts, spread, and confidence intervals for all requested metrics."""
    summaries = {}
    with path.open("w", newline="", encoding="utf-8") as stream:
        fields = ["condition", "protocol", "metric", "n", "missing", "median", "q1", "q3",
                  "variance", "ci_low", "ci_high"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for condition in CONDITIONS:
            for protocol in PATHS:
                rows = groups[condition, protocol]
                for metric in METRICS:
                    if metric == "recovery_ms" and condition != "outage":
                        continue
                    result = summarize([float(row[metric]) for row in rows if row[metric] != ""])
                    summaries[condition, protocol, metric] = result
                    writer.writerow(dict(condition=condition, protocol=protocol, metric=metric,
                                         missing=len(rows) - result["n"], **result))
    return summaries


def validity(rows: list[dict], groups: dict) -> list[tuple[str, bool]]:
    """Evaluate declared healthy parity, loss-rate, pacing, and CPU checks."""
    pairs = [{row["repeat"]: row for row in groups["healthy", protocol]} for protocol in PATHS]
    checks = []
    for metric, limit in (("median_age_ms", 10), ("latency_p95_ms", 10), ("useful_per_second", 0.5)):
        differences = [abs(float(pairs[0][repeat][metric]) - float(pairs[1][repeat][metric]))
                       for repeat in pairs[0]]
        difference = statistics.median(differences)
        checks.append((f"Healthy median absolute paired {metric} gap {difference:.3f} (limit {limit})",
                       difference <= limit))
    for condition, settings in CONDITIONS.items():
        if "loss" not in settings:
            continue
        runs = groups[condition, "udp"]
        total = sum(int(row["relay_received"]) for row in runs)
        drops = sum(int(row["relay_loss"]) for row in runs)
        probability = settings["loss"]
        observed = drops / total if total else 0
        tolerance = max(0.03, 3 * math.sqrt(probability * (1 - probability) / total)) if total else 0
        checks.append((f"{condition} injected UDP drops {drops}/{total} ({observed:.2%}), "
                       f"expected {probability:.0%} ± {tolerance:.2%}",
                       bool(total) and abs(observed - probability) <= tolerance))
    unique = [row for row in rows if row["protocol"] == PATHS[0]]
    cpu = max(float(row["cpu_seconds"]) / float(row["observed_s"]) for row in unique)
    source_rate = min(float(row["generated"]) / float(row["observed_s"]) for row in unique)
    target = float(unique[0]["target_hz"])
    max_gap = max(float(row["poll_gap_max_ms"]) for row in unique)
    gap_limit = 2 * SAMPLE_INTERVAL * 1000
    checks.extend([(f"Maximum process CPU use {cpu:.2%} of one core (limit 50%)", cpu <= 0.5),
                   (f"Minimum achieved source rate {source_rate:.2f} Hz (floor {target * 0.8:.2f} Hz)",
                    source_rate >= target * 0.8),
                   (f"Maximum sampling gap {max_gap:.2f} ms (limit {gap_limit:.0f} ms)", max_gap <= gap_limit)])
    return checks


def plot_metric(summaries: dict, path: Path, metric: str, title: str,
                *, threshold: float | None = None) -> None:
    """Plot trial medians and median CIs as labelled and patterned SVG bars."""
    width, height = 1000, 370
    top, bottom = 45, 285
    maximum = max(1, threshold or 0, *(entry["ci_high"] or entry["median"] or 0
                                       for key, entry in summaries.items() if key[-1] == metric))
    step = 10 ** math.floor(math.log10(maximum)) / 2
    maximum = math.ceil(maximum * 1.1 / step) * step

    def y(value: float) -> float:
        return bottom - value / maximum * (bottom - top)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">',
        f'<title>{escape(title)} and 95% bootstrap intervals by condition</title>',
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<defs><pattern id="stripe" width="7" height="7" patternUnits="userSpaceOnUse">'
        '<rect width="7" height="7" fill="#d9eeec"/><path d="M0 7L7 0" stroke="#146a70"/></pattern></defs>',
        '<g font-family="sans-serif" font-size="13" fill="#182636">',
        f'<text x="85" y="24" font-size="19" font-weight="bold">{escape(title)}</text>',
        '<text x="18" y="170" text-anchor="middle" transform="rotate(-90 18 170)">Milliseconds (ms)</text>',
    ]
    for value in (0, maximum / 2, maximum):
        position = y(value)
        parts.append(f'<path d="M80 {position}H970" stroke="#ddd"/>'
                     f'<text x="70" y="{position + 4}" text-anchor="end">{value:g}</text>')
    for index, condition in enumerate(CONDITIONS):
        center = 140 + index * 123
        labels = {"stationary": "Stationary", "overload": "Overload", "outage": "Outage",
                  "healthy": "Healthy", "loss_10": "UDP loss 10%", "loss_30": "UDP loss 30%",
                  "loss_45": "UDP loss 45%"}
        label = escape(labels[condition])
        parts.append(f'<text x="{center}" y="310" text-anchor="middle">{label}</text>')
        for protocol, offset, fill in (("tcp", -31, "#d28337"), ("udp", 4, "url(#stripe)")):
            entry = summaries[condition, protocol, metric]
            if entry["median"] is None:
                continue
            x = center + offset
            bar_y = y(entry["median"])
            parts.append(f'<rect x="{x}" y="{bar_y}" width="26" height="{bottom - bar_y}" '
                         f'fill="{fill}" stroke="#243343"/>')
            if entry["ci_low"] is not None:
                middle = x + 13
                lower = y(entry["ci_low"])
                upper = y(entry["ci_high"])
                parts.append(f'<path d="M{middle} {lower}V{upper}m-5 0h10M{middle-5} {lower}h10" '
                             'stroke="#182636" fill="none"/>')
    if threshold is not None:
        level = y(threshold)
        parts.append(f'<path d="M80 {level}H970" stroke="#182636" stroke-dasharray="5 4"/>'
                     f'<text x="968" y="{level - 6}" text-anchor="end" stroke="white" stroke-width="4" '
                     f'paint-order="stroke">Stale threshold {threshold:g} ms</text>')
    parts.append('<text x="85" y="345">Solid TCP · Striped UDP · Whiskers show 95% bootstrap CIs</text></g></svg>')
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def main() -> None:
    """Generate the complete summary CSV, validity checks, and age figure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results"))
    parser.add_argument("--quick", action="store_true", help="expect a single smoke-test repeat")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = read_runs(args.runs)
    groups = group_runs(rows, expected_repeats=1 if args.quick else 10)
    summaries = write_summary(groups, args.output / "summary.csv")
    plot_metric(summaries, args.output / "information-age.svg", "median_age_ms",
                "Median information age", threshold=float(rows[0]["threshold_ms"]))
    plot_metric(summaries, args.output / "delivered-latency.svg", "latency_p95_ms",
                "95th percentile delivered-update latency")
    for message, passed in validity(rows, groups):
        print(f'{"PASS" if passed else "FAIL"} {message}')


if __name__ == "__main__":
    main()
