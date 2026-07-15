from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from axiom_rift.research.chassis import ArchitectureChassisSpec, ControlledStudyChassis, validate_controlled_executable
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.session_dense_positive_sleeve_chassis import session_dense_positive_sleeve_baseline, session_dense_positive_sleeve_configurations, session_dense_positive_sleeve_executable, simulate_session_dense_positive_sleeves


class SessionDensePositiveSleeveTests(unittest.TestCase):
    def test_subject_changes_only_registered_portfolio_surface(self) -> None:
        baseline = session_dense_positive_sleeve_baseline()
        architecture = ArchitectureChassisSpec.from_executable(baseline)
        control = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.PORTFOLIO, ResearchLayer.REGIME, ResearchLayer.RISK, ResearchLayer.SELECTOR),
            controlled_domains=(ResearchLayer.CALIBRATION, ResearchLayer.EXECUTION, ResearchLayer.FEATURE, ResearchLayer.LABEL, ResearchLayer.LIFECYCLE, ResearchLayer.MODEL, ResearchLayer.SYNTHESIS, ResearchLayer.TRADE),
            architecture=architecture,
        )
        subject = session_dense_positive_sleeve_executable(session_dense_positive_sleeve_configurations()[1])
        validate_controlled_executable(control.to_identity_payload(), subject)
        self.assertNotEqual(baseline.identity, subject.identity)

    def test_exact_structural_extreme_is_frozen(self) -> None:
        control, subject = session_dense_positive_sleeve_configurations()
        self.assertEqual((control.target_quantile_bp, control.target_session_policy), (9750, "all_broker_hours"))
        self.assertEqual((subject.target_quantile_bp, subject.target_session_policy), (9000, "broker_15_22_only"))

    def test_session_gate_uses_scheduled_entry_clock_not_future_row(self) -> None:
        time = pd.date_range("2026-01-05 14:50:00", periods=12, freq="5min")
        time = pd.Series(time)
        time.iloc[1:] += pd.Timedelta(minutes=5)
        frame = pd.DataFrame(
            {
                "time": time,
                "open": np.linspace(100.0, 101.1, len(time)),
                "high": np.linspace(100.1, 101.2, len(time)),
                "low": np.linspace(99.9, 101.0, len(time)),
                "close": np.linspace(100.05, 101.15, len(time)),
                "tick_volume": np.full(len(time), 10),
                "spread": np.ones(len(time)),
            }
        )
        score = np.full((len(frame), 2), np.nan)
        score[0, 1] = 2.0
        result = simulate_session_dense_positive_sleeves(
            frame=frame,
            score=score,
            volatility=np.ones(len(frame)),
            run=np.arange(1, len(frame) + 1, dtype=np.int32),
            threshold=1.0,
            configuration=session_dense_positive_sleeve_configurations()[1],
            test_start=time.iloc[0],
            test_end=time.iloc[-1],
            fold_id="rw_fixture",
            regime_cutoffs=(0.5, 1.5),
            effective_spread=np.ones(len(frame)),
        )
        self.assertFalse(
            any(row[0] == "target_direction" for row in result.intent_rows)
        )


if __name__ == "__main__":
    unittest.main()
