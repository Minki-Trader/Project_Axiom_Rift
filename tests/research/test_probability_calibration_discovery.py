from __future__ import annotations

import unittest

import numpy as np

from axiom_rift.research.probability_calibration_discovery import (
    _calibrated_score,
    _fit_platt,
    probability_calibration_configurations,
    probability_calibration_executable,
)


class ProbabilityCalibrationDiscoveryTests(unittest.TestCase):
    def test_four_calibration_and_direction_executables_are_unique(self) -> None:
        configurations = probability_calibration_configurations()
        identities = {
            probability_calibration_executable(value).identity
            for value in configurations
        }
        self.assertEqual(len(configurations), 4)
        self.assertEqual(len(identities), 4)

    def test_platt_edge_is_validation_fitted_and_ordered(self) -> None:
        score = np.linspace(-3.0, 3.0, 1200)
        label = np.where(score > 0.25, 1.0, -1.0)
        mask = np.ones(len(score), dtype=bool)
        calibration = _fit_platt(score, label, mask)
        edge = _calibrated_score(
            np.array([-2.0, 0.0, 2.0]),
            calibration,
            "validation_platt_probability_edge",
        )
        self.assertLess(edge[0], edge[1])
        self.assertLess(edge[1], edge[2])
        self.assertLess(edge[0], 0)
        self.assertGreater(edge[2], 0)

    def test_raw_control_preserves_exact_score(self) -> None:
        score = np.array([-1.0, np.nan, 2.0])
        observed = _calibrated_score(
            score,
            (0.0, 1.0, 0.0, 1.0),
            "raw_score_control",
        )
        np.testing.assert_equal(observed, score)


if __name__ == "__main__":
    unittest.main()
