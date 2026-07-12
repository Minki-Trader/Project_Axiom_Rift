from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from axiom_rift.research.chassis import (
    ArchitectureChassisSpec, ControlledStudyChassis, validate_controlled_executable,
)
from axiom_rift.research.equity_premium_trade_chassis import (
    EquityPremiumTradeConfiguration, equity_premium_trade_baseline,
    equity_premium_trade_configurations, equity_premium_trade_executable,
    simulate_equity_premium_trade,
)
from axiom_rift.research.governance import ResearchLayer


class EquityPremiumTradeChassisTests(unittest.TestCase):
    def test_subject_changes_only_the_trade_parameter(self) -> None:
        baseline = equity_premium_trade_baseline()
        subject = equity_premium_trade_executable(next(
            value for value in equity_premium_trade_configurations()
            if value.trade_policy == "long_only_equity_premium"
        ))
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.TRADE,),
            controlled_domains=(
                ResearchLayer.FEATURE, ResearchLayer.LABEL, ResearchLayer.MODEL,
                ResearchLayer.SELECTOR, ResearchLayer.LIFECYCLE, ResearchLayer.RISK,
                ResearchLayer.EXECUTION,
            ),
            architecture=ArchitectureChassisSpec.from_executable(baseline),
        )
        validate_controlled_executable(chassis.to_identity_payload(), subject)

    def test_long_only_policy_rejects_negative_scores(self) -> None:
        times = pd.date_range("2025-01-01", periods=110, freq="5min", tz="UTC")
        frame = pd.DataFrame({
            "time": times, "open": np.linspace(100.0, 110.0, 110),
            "spread": np.ones(110),
        })
        score = np.ones(110)
        score[:55] = -1.0
        kwargs = {
            "frame": frame, "score": score, "volatility": np.ones(110),
            "run": np.arange(1, 111), "threshold": 0.5,
            "test_start": times[0], "test_end": times[-1], "fold_id": "fold-01",
            "regime_cutoffs": (0.5, 1.5), "effective_spread": np.ones(110),
        }
        symmetric = simulate_equity_premium_trade(
            configuration=EquityPremiumTradeConfiguration("symmetric_direction_control"),
            **kwargs,
        )
        long_only = simulate_equity_premium_trade(
            configuration=EquityPremiumTradeConfiguration("long_only_equity_premium"),
            **kwargs,
        )
        self.assertTrue((symmetric.trades["direction"] < 0).any())
        self.assertTrue((long_only.trades["direction"] > 0).all())


if __name__ == "__main__":
    unittest.main()
