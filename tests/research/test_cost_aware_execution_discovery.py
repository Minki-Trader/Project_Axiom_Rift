from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from axiom_rift.research.chassis import ArchitectureChassisSpec
from axiom_rift.research.cost_aware_execution_discovery import (
    CostAwareExecutionConfiguration,
    cost_aware_execution_executable,
    simulate_cost_aware_execution,
)


class CostAwareExecutionDiscoveryTests(unittest.TestCase):
    def test_policy_changes_executable_and_execution_chassis(self) -> None:
        control = cost_aware_execution_executable(
            CostAwareExecutionConfiguration(
                policy="unconditional_next_open", signal_sign=1
            )
        )
        abstention = cost_aware_execution_executable(
            CostAwareExecutionConfiguration(
                policy="causal_spread_abstention", signal_sign=1
            )
        )
        self.assertNotEqual(control.identity, abstention.identity)
        self.assertNotEqual(
            ArchitectureChassisSpec.from_executable(control).identity,
            ArchitectureChassisSpec.from_executable(abstention).identity,
        )

    def test_abstention_uses_entry_spread_against_prior_reference(self) -> None:
        count = 100
        time = pd.date_range("2024-01-02 10:00", periods=count, freq="5min")
        frame = pd.DataFrame(
            {
                "time": time,
                "open": np.linspace(100.0, 110.0, count),
                "spread": np.full(count, 10.0),
            }
        )
        frame.loc[31, "spread"] = 20.0
        score = np.full(count, np.nan)
        score[30] = 1.0
        volatility = np.full(count, 0.01)
        run = np.arange(1, count + 1)
        common = {
            "frame": frame,
            "score": score,
            "volatility": volatility,
            "run": run,
            "threshold": 0.5,
            "test_start": time[25],
            "test_end": time[90],
            "fold_id": "fold-one",
            "regime_cutoffs": (0.005, 0.02),
            "effective_spread": frame["spread"].to_numpy(float),
        }
        control = simulate_cost_aware_execution(
            **common,
            configuration=CostAwareExecutionConfiguration(
                policy="unconditional_next_open", signal_sign=1
            ),
        )
        abstention = simulate_cost_aware_execution(
            **common,
            configuration=CostAwareExecutionConfiguration(
                policy="causal_spread_abstention", signal_sign=1
            ),
        )
        self.assertEqual(len(control.trades), 1)
        self.assertEqual(len(abstention.trades), 0)
        self.assertEqual(abstention.intent_rows[0][-1], "spread_abstained")


if __name__ == "__main__":
    unittest.main()
