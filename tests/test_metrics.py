"""Test freshness accounting against hand-computed timelines."""

import unittest

from src.freshlink.metrics import ReceiverMetrics, percentile
from src.freshlink.protocol import Sample


class MetricsTests(unittest.TestCase):
    def test_time_weighted_staleness_and_latency(self) -> None:
        metrics = ReceiverMetrics(0, 100_000_000)
        metrics.accept(Sample(0, 0, 0, 0), 50_000_000)
        metrics.accept(Sample(1, 200_000_000, 3, 4), 250_000_000)
        result = metrics.snapshot(400_000_000, 0, 0)
        self.assertAlmostEqual(result["stale_fraction"], 250 / 350)
        self.assertEqual(result["age_ms"], 200)
        self.assertEqual(result["latency_p99_ms"], 50)
        self.assertEqual(result["position_error"], 5)
        self.assertEqual(result["useful_per_second"], 5)

    def test_no_sample_and_invalid_timestamps(self) -> None:
        metrics = ReceiverMetrics(0, 10)
        self.assertIsNone(metrics.snapshot(5, 0, 0)["age_ms"])
        with self.assertRaises(ValueError):
            metrics.accept(Sample(0, 20, 0, 0), 10)
        with self.assertRaises(ValueError):
            metrics.snapshot(4, 0, 0)

    def test_nearest_rank(self) -> None:
        self.assertEqual(percentile([5, 1, 3, 2, 4], 0.5), 3)
        self.assertEqual(percentile([5, 1, 3, 2, 4], 0.95), 5)
        self.assertIsNone(percentile([], 0.99))

    def test_reset_preserves_age_and_restarts_observation(self) -> None:
        metrics = ReceiverMetrics(0, 100)
        metrics.accept(Sample(0, 0, 0, 0), 50)
        metrics.reset(200)
        result = metrics.snapshot(300, 0, 0)
        self.assertEqual(result["stale_fraction"], 1)
        self.assertIsNone(result["latency_p95_ms"])
        self.assertEqual(result["accepted"], 0)
