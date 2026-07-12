from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from axiom_rift.research.data import load_observed_development
from axiom_rift.research.transition_mixture_discovery import (
    executable_configuration_map,
    fit_fold_transition,
    transition_mixture_configurations,
)
from axiom_rift.research.transition_mixture_study import (
    build_transition_mixture_validation_plan,
)


class TransitionMixtureTests(unittest.TestCase):
    def test_surface_has_four_unique_executables(self) -> None:
        self.assertEqual(len(transition_mixture_configurations()), 4)
        self.assertEqual(len(executable_configuration_map()), 4)

    def test_fold_transition_is_prefix_invariant(self) -> None:
        frame = load_observed_development(Path(__file__).resolve().parents[2]).frame
        time = pd.to_datetime(frame["time"])
        start = time.iloc[500]
        end = time.iloc[5000]
        full = fit_fold_transition(
            frame.iloc[:8000].copy(),
            "joint_drawdown_volatility_transition",
            start,
            end,
        )
        prefix = fit_fold_transition(
            frame.iloc[:7000].copy(),
            "joint_drawdown_volatility_transition",
            start,
            end,
        )
        for left, right in zip(full, prefix, strict=True):
            np.testing.assert_allclose(
                left[:7000], right, rtol=0, atol=0, equal_nan=True
            )
        train_mask = ((time.iloc[:8000] >= start) & (time.iloc[:8000] <= end)).to_numpy()
        self.assertGreater(int((train_mask & np.isfinite(full[0])).sum()), 1000)

    def test_plan_is_fourth_mission_bound(self) -> None:
        executable_id = next(iter(executable_configuration_map()))
        self.assertEqual(
            build_transition_mixture_validation_plan(executable_id)["mission_id"],
            "MIS-0004",
        )


if __name__ == "__main__":
    unittest.main()
