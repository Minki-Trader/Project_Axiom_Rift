from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from axiom_rift.research.post_break_discovery import (
    compute_post_break_score,
    executable_configuration_map,
    post_break_configurations,
)
from axiom_rift.research.post_break_study import build_post_break_validation_plan


class PostBreakDiscoveryTests(unittest.TestCase):
    def test_registered_surface_has_twelve_unique_executables(self) -> None:
        self.assertEqual(len(post_break_configurations()), 12)
        self.assertEqual(len(executable_configuration_map()), 12)

    def test_two_completed_bar_feature_is_prefix_invariant(self) -> None:
        rows = 190
        time = pd.date_range("2025-01-01", periods=rows, freq="5min")
        close = 20_000.0 + np.cumsum(np.sin(np.arange(rows) / 5.0) + 0.15)
        frame = pd.DataFrame(
            {
                "time": time,
                "open": close - 0.2,
                "high": close + 1.2,
                "low": close - 1.2,
                "close": close,
            }
        )

        full = compute_post_break_score(frame, event_state="failure", lookback=24)
        prefix = compute_post_break_score(
            frame.iloc[:150].copy(), event_state="failure", lookback=24
        )

        for full_value, prefix_value in zip(full, prefix, strict=True):
            np.testing.assert_allclose(
                full_value[:150], prefix_value, rtol=0.0, atol=0.0, equal_nan=True
            )

    def test_validation_plan_is_bound_to_study_mission(self) -> None:
        executable_id = next(iter(executable_configuration_map()))
        plan = build_post_break_validation_plan(executable_id)

        self.assertEqual(plan["mission_id"], "MIS-0002")
        self.assertEqual(plan["executable_id"], executable_id)
        self.assertFalse(plan["candidate_eligible_on_pass"])


if __name__ == "__main__":
    unittest.main()
