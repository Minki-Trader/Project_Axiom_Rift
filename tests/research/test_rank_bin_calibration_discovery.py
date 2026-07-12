from __future__ import annotations

import unittest

import numpy as np

from axiom_rift.research.rank_bin_calibration_discovery import (
    BIN_COUNT,
    _fit_rank_bins,
    _rank_bin_score,
    rank_bin_calibration_configurations,
    rank_bin_calibration_executable,
)


class RankBinCalibrationDiscoveryTests(unittest.TestCase):
    def test_four_calibration_and_direction_executables_are_unique(self) -> None:
        configurations = rank_bin_calibration_configurations()
        identities = {rank_bin_calibration_executable(value).identity for value in configurations}
        self.assertEqual(len(configurations), 4)
        self.assertEqual(len(identities), 4)
        self.assertEqual(BIN_COUNT, 7)

    def test_rank_bin_edges_are_monotone_probability_edges(self) -> None:
        score = np.linspace(-3.0, 3.0, 1400)
        label = np.where(score + 0.2 * np.sin(score * 3) > 0, 1.0, -1.0)
        edges, values = _fit_rank_bins(score, label, np.ones(len(score), dtype=bool))
        self.assertEqual(len(edges), 6)
        self.assertEqual(len(values), 7)
        self.assertTrue(np.all(np.diff(edges) > 0))
        self.assertTrue(np.all(np.diff(values) >= 0))
        mapped = _rank_bin_score(np.array([-2.0, 0.0, 2.0]), (edges, values), "validation_isotonic_rank_bin_edge")
        self.assertLessEqual(mapped[0], mapped[1])
        self.assertLessEqual(mapped[1], mapped[2])

    def test_raw_control_preserves_score(self) -> None:
        score = np.array([-1.0, np.nan, 2.0])
        observed = _rank_bin_score(score, (np.arange(6.0), np.arange(7.0)), "raw_score_control")
        np.testing.assert_equal(observed, score)


if __name__ == "__main__":
    unittest.main()
