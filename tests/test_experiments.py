"""Check analysis statistics and complete-trial validation."""

import unittest

from experiments.analyze import group_runs, summarize
from experiments.run import CONDITIONS, PATHS


class AnalysisTests(unittest.TestCase):
    def test_bootstrap_interval_and_spread(self) -> None:
        result = summarize([1, 2, 3, 4, 5])
        self.assertEqual(result["median"], 3)
        self.assertEqual((result["q1"], result["q3"]), (2, 4))
        self.assertEqual(result["variance"], 2.5)
        self.assertLessEqual(1, result["ci_low"])
        self.assertLess(result["ci_low"], 3)
        self.assertGreater(result["ci_high"], 3)
        self.assertLessEqual(result["ci_high"], 5)
        self.assertEqual(summarize([8] * 10)["ci_low"], 8)
        self.assertIsNone(summarize([8])["ci_high"])
        self.assertEqual(summarize([])["n"], 0)

    def test_missing_or_duplicate_condition_is_rejected(self) -> None:
        rows = [dict(condition=condition, protocol=protocol, repeat="1")
                for condition in CONDITIONS for protocol in PATHS]
        self.assertEqual(len(group_runs(rows)), len(rows))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            group_runs(rows[:-1])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            group_runs(rows + rows[:1])
        with self.assertRaisesRegex(ValueError, "expected repeats"):
            group_runs(rows, expected_repeats=10)
