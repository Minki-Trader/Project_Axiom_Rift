from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.market_residual_event_chassis import (
    market_residual_event_configurations,
    market_residual_event_executable,
)
from axiom_rift.research.residual_quote_deferral_chassis import (
    SELECTION_TOTAL_EXPOSURES,
    residual_quote_deferral_baseline,
    residual_quote_deferral_configurations,
    residual_quote_deferral_executable,
    simulate_residual_quote_deferral,
)
from axiom_rift.research.residual_quote_deferral_study import (
    build_residual_quote_deferral_validation_plan,
)
from axiom_rift.research.validation import require_supported_evaluation_schema


class ResidualQuoteDeferralChassisTests(unittest.TestCase):
    def test_control_reuses_exact_stu0098_continuation(self) -> None:
        continuation = next(
            configuration
            for configuration in market_residual_event_configurations()
            if configuration.profile == "market_residual_continuation"
        )
        self.assertEqual(
            residual_quote_deferral_baseline().identity,
            market_residual_event_executable(continuation).identity,
        )
        self.assertEqual(SELECTION_TOTAL_EXPOSURES, 594)

    def test_subject_changes_only_execution_layer(self) -> None:
        baseline = residual_quote_deferral_baseline()
        controlled = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.EXECUTION,),
            controlled_domains=(
                ResearchLayer.CALIBRATION,
                ResearchLayer.DATA_SOURCE,
                ResearchLayer.FEATURE,
                ResearchLayer.LABEL,
                ResearchLayer.LIFECYCLE,
                ResearchLayer.MODEL,
                ResearchLayer.OBJECTIVE,
                ResearchLayer.PORTFOLIO,
                ResearchLayer.REGIME,
                ResearchLayer.RISK,
                ResearchLayer.SELECTOR,
                ResearchLayer.SYNTHESIS,
                ResearchLayer.TRADE,
            ),
            architecture=ArchitectureChassisSpec.from_executable(baseline),
        )
        subject = residual_quote_deferral_executable(
            residual_quote_deferral_configurations()[1]
        )
        validate_controlled_executable(controlled.to_identity_payload(), subject)
        self.assertNotEqual(baseline.identity, subject.identity)

    @staticmethod
    def _frame(rows: int = 48) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "time": pd.date_range(
                    "2024-01-01 00:00:00",
                    periods=rows,
                    freq="5min",
                ),
                "open": 100.0 + np.arange(rows) * 0.01,
                "spread": np.ones(rows),
            }
        )

    def test_above_median_quote_defers_exactly_one_bar(self) -> None:
        frame = self._frame()
        score = np.full(len(frame), np.nan)
        decision_index = 30
        score[decision_index] = 1.0
        spreads = np.ones(len(frame))
        spreads[decision_index] = 2.0
        result = simulate_residual_quote_deferral(
            frame=frame,
            score=score,
            volatility=np.ones(len(frame)),
            run=np.arange(1, len(frame) + 1),
            threshold=0.5,
            configuration=residual_quote_deferral_configurations()[1],
            test_start=frame.loc[decision_index, "time"],
            test_end=frame.loc[len(frame) - 1, "time"],
            fold_id="fold-01",
            regime_cutoffs=(0.5, 1.5),
            effective_spread=spreads,
        )
        self.assertEqual(len(result.trades), 1)
        trade = result.trades.iloc[0]
        self.assertEqual(int(trade["entry_delay_bars"]), 1)
        self.assertEqual(
            trade["entry_time"],
            frame.loc[decision_index + 2, "time"],
        )
        self.assertEqual(result.intent_rows[0][-1], "executed_deferred")

    def test_entry_bar_spreads_never_change_deferral_or_trade_sample(self) -> None:
        frame = self._frame(64)
        score = np.full(len(frame), np.nan)
        decision_index = 30
        score[decision_index] = 1.0
        base_spreads = np.ones(len(frame))
        base_spreads[decision_index] = 2.0

        def simulate(spreads: np.ndarray):
            return simulate_residual_quote_deferral(
                frame=frame,
                score=score,
                volatility=np.ones(len(frame)),
                run=np.arange(1, len(frame) + 1),
                threshold=0.5,
                configuration=residual_quote_deferral_configurations()[1],
                test_start=frame.loc[decision_index, "time"],
                test_end=frame.loc[len(frame) - 1, "time"],
                fold_id="fold-01",
                regime_cutoffs=(0.5, 1.5),
                effective_spread=spreads,
            )

        baseline = simulate(base_spreads)
        scheduled_entry_bar = base_spreads.copy()
        scheduled_entry_bar[decision_index + 1] = 50.0
        scheduled_perturbed = simulate(scheduled_entry_bar)
        actual_entry_bar = base_spreads.copy()
        actual_entry_bar[decision_index + 2] = 500.0
        actual_perturbed = simulate(actual_entry_bar)

        self.assertEqual(baseline.intent_rows, scheduled_perturbed.intent_rows)
        self.assertEqual(baseline.intent_rows, actual_perturbed.intent_rows)
        self.assertEqual(len(baseline.trades), len(scheduled_perturbed.trades))
        self.assertEqual(len(baseline.trades), len(actual_perturbed.trades))
        self.assertNotEqual(
            float(baseline.trades.iloc[0]["pnl"]),
            float(scheduled_perturbed.trades.iloc[0]["pnl"]),
        )
        pd.testing.assert_frame_equal(
            baseline.trades,
            actual_perturbed.trades,
        )

    def test_gap_intent_decision_time_is_derived_without_future_row(self) -> None:
        frame = self._frame(64)
        decision_index = 30
        frame.loc[decision_index + 1 :, "time"] += pd.Timedelta(minutes=5)
        score = np.full(len(frame), np.nan)
        score[decision_index] = 1.0
        result = simulate_residual_quote_deferral(
            frame=frame,
            score=score,
            volatility=np.ones(len(frame)),
            run=np.arange(1, len(frame) + 1),
            threshold=0.5,
            configuration=residual_quote_deferral_configurations()[1],
            test_start=frame.loc[decision_index, "time"],
            test_end=frame.loc[len(frame) - 1, "time"],
            fold_id="fold-01",
            regime_cutoffs=(0.5, 1.5),
            effective_spread=np.ones(len(frame)),
        )
        self.assertEqual(len(result.trades), 0)
        self.assertEqual(result.intent_rows[0][-1], "gap_excluded")
        self.assertEqual(
            result.intent_rows[0][0],
            frame.loc[decision_index, "time"] + pd.Timedelta(minutes=5),
        )
        self.assertNotEqual(
            result.intent_rows[0][0],
            frame.loc[decision_index + 1, "time"],
        )

    def test_unknown_reference_retains_immediate_entry(self) -> None:
        frame = self._frame()
        score = np.full(len(frame), np.nan)
        decision_index = 5
        score[decision_index] = 1.0
        result = simulate_residual_quote_deferral(
            frame=frame,
            score=score,
            volatility=np.ones(len(frame)),
            run=np.arange(1, len(frame) + 1),
            threshold=0.5,
            configuration=residual_quote_deferral_configurations()[1],
            test_start=frame.loc[decision_index, "time"],
            test_end=frame.loc[len(frame) - 1, "time"],
            fold_id="fold-01",
            regime_cutoffs=(0.5, 1.5),
            effective_spread=np.ones(len(frame)),
        )
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(int(result.trades.iloc[0]["entry_delay_bars"]), 0)
        self.assertEqual(
            result.intent_rows[0][-1],
            "executed_immediate_reference_unknown",
        )

    def test_validator_profile_and_final_activity_bounds_are_registered(self) -> None:
        self.assertEqual(
            require_supported_evaluation_schema(
                "residual_quote_deferral_evaluation.v1"
            ),
            "residual_quote_deferral_evaluation.v1",
        )
        subject = residual_quote_deferral_executable(
            residual_quote_deferral_configurations()[1]
        )
        plan = build_residual_quote_deferral_validation_plan(
            subject.identity,
            mission_id="MIS-0006",
        )
        criteria = {item["criterion_id"] for item in plan["criteria"]}
        self.assertIn("A04-target-minimum-density", criteria)
        self.assertIn("A05-target-maximum-density", criteria)
        self.assertIn("C06-execution-timing-accounting", criteria)


if __name__ == "__main__":
    unittest.main()
