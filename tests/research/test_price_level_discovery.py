from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from axiom_rift.research.price_level_discovery import (
    compute_price_level_score,
    executable_configuration_map,
    price_level_configurations,
)
from axiom_rift.research.price_level_study import build_price_level_validation_plan


class PriceLevelDiscoveryTests(unittest.TestCase):
    def test_registered_surface_has_twelve_unique_executables(self) -> None:
        configurations = price_level_configurations()
        identities = executable_configuration_map()

        self.assertEqual(len(configurations), 12)
        self.assertEqual(len(identities), 12)
        self.assertEqual(
            {item.configuration_id for item in configurations},
            {item.configuration_id for item in identities.values()},
        )

    def test_price_level_feature_is_prefix_invariant(self) -> None:
        rows = 180
        time = pd.date_range("2025-01-01", periods=rows, freq="5min")
        close = 20_000.0 + np.cumsum(np.sin(np.arange(rows) / 7.0) + 0.2)
        frame = pd.DataFrame(
            {
                "time": time,
                "open": close - 0.1,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
            }
        )

        full = compute_price_level_score(frame, 24)
        prefix = compute_price_level_score(frame.iloc[:140].copy(), 24)

        for full_value, prefix_value in zip(full, prefix, strict=True):
            np.testing.assert_allclose(
                full_value[:140],
                prefix_value,
                rtol=0.0,
                atol=0.0,
                equal_nan=True,
            )

    def test_validation_plan_is_successor_mission_bound(self) -> None:
        executable_id = next(iter(executable_configuration_map()))
        plan = build_price_level_validation_plan(executable_id)

        self.assertEqual(plan["mission_id"], "MIS-0002")
        self.assertEqual(plan["executable_id"], executable_id)
        self.assertFalse(plan["candidate_eligible_on_pass"])


if __name__ == "__main__":
    unittest.main()
