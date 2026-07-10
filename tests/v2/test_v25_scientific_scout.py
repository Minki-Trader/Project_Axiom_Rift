from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import unittest

import numpy as np

from axiom_rift.v2.data.blackouts import BoundaryGap
from axiom_rift.v2.features import BarArrays
from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.research.evaluation import (
    EvaluationProfile,
    FailureEffect,
    MetricRule,
)
from axiom_rift.v2.research.scientific_scout import (
    ANCHORS,
    BUNDLE_ROLES,
    ScientificFold,
    ScientificScoutSpec,
    SCIENTIFIC_SELECTION_RULE_SHA256,
    evaluate_signal_role,
    run_scientific_scout,
)
from axiom_rift.v2.research.scout import FoldWindow
from axiom_rift.v2.research.specs import IndexBoundary


@dataclass(frozen=True)
class FakeConfiguration:
    role: str

    @property
    def identity_sha256(self) -> str:
        return sha256_payload({"role": self.role, "surface": "fake_release"})


@dataclass(frozen=True)
class FakeEvaluation:
    directions: tuple[int, ...]
    scores: tuple[float, ...]
    valid_mask: tuple[bool, ...]
    configuration_sha256: str = "0" * 64
    executable_sha256: str = "1" * 64


def _bars(start: datetime, size: int = 1500) -> BarArrays:
    times = tuple(start + timedelta(minutes=5 * index) for index in range(size))
    opening = 20000.0 + np.arange(size, dtype=np.float64) * 0.05
    return BarArrays(
        time=times,
        open=opening,
        high=opening + 0.10,
        low=opening - 0.10,
        close=opening + 0.02,
        tick_volume=np.full(size, 100.0),
        spread=np.full(size, 2.0),
    )


def _fold(fold_id: str, start: datetime) -> ScientificFold:
    bars = _bars(start)
    times = bars.time
    return ScientificFold(
        window=FoldWindow(
            development_id=fold_id,
            train_start=times[0],
            train_end=times[149],
            validation_start=times[150],
            validation_end=times[1049],
            development_start=times[1050],
            development_end=times[1449],
        ),
        bars=bars,
    )


def _spec() -> ScientificScoutSpec:
    profile = EvaluationProfile(
        profile_id="V2SAP9001",
        rules=(
            MetricRule.equal(
                "causal_checks_all_pass",
                "integrity",
                stages=("S",),
                expected=True,
                failure_effect=FailureEffect.REPAIR,
            ),
            MetricRule.minimum(
                "evaluable_trade_count",
                "inferential_density",
                stages=("S",),
                pass_at=60,
            ),
            MetricRule.maximum(
                "unknown_cost_observation_count",
                "integrity",
                stages=("S",),
                pass_at=0,
                failure_effect=FailureEffect.EVIDENCE_GAP,
            ),
            MetricRule.minimum(
                "net_broker_points",
                "economics",
                stages=("S",),
                pass_at=0.01,
            ),
            MetricRule.minimum(
                "positive_net_fold_count",
                "stability",
                stages=("S",),
                pass_at=2,
            ),
        ),
    )
    return ScientificScoutSpec(
        goal_id="V2G0002",
        hypothesis_id="V2H0002",
        family_id="compression_release",
        bundle_role_hashes={role: sha256_payload({"bundle_role": role}) for role in BUNDLE_ROLES},
        release_configuration_hashes={
            role: FakeConfiguration(role).identity_sha256 for role in BUNDLE_ROLES
        },
        evaluation_profile=profile,
        runtime_sha256=sha256_payload({"runtime": "fixture"}),
        runtime_executable_sha256=sha256_payload({"executable": "fixture"}),
        selection_rule_sha256=SCIENTIFIC_SELECTION_RULE_SHA256,
    )


class ScientificScoutTests(unittest.TestCase):
    def test_validation_only_selection_and_complete_trial_accounting(self) -> None:
        folds = tuple(
            _fold(fold_id, datetime(2020 + index * 2, 1, 1))
            for index, fold_id in enumerate(ANCHORS)
        )
        configurations = tuple(FakeConfiguration(role) for role in BUNDLE_ROLES)
        calls: list[tuple[str, int]] = []

        def evaluator(bars: BarArrays, configuration: FakeConfiguration) -> FakeEvaluation:
            calls.append((configuration.role, len(bars)))
            direction = (
                -1
                if configuration.role
                in {"failed_break_reversal", "compression_ablation"}
                else 1
            )
            return FakeEvaluation(
                directions=(direction,) * len(bars),
                scores=(1.0,) * len(bars),
                valid_mask=(True,) * len(bars),
                configuration_sha256=configuration.identity_sha256,
                executable_sha256=_spec().runtime_executable_sha256,
            )

        first = run_scientific_scout(
            _spec(), folds, configurations=configurations, evaluator=evaluator
        )
        self.assertTrue(first.gate_passed)
        self.assertEqual(
            {row.selected_role for row in first.selections}, {"continuation_base"}
        )
        self.assertEqual(first.trial_accounting["configuration_trials"], 5)
        self.assertEqual(first.trial_accounting["validation_evaluation_cells"], 15)
        self.assertEqual(first.trial_accounting["development_selected_paths"], 3)
        self.assertFalse(first.trial_accounting["development_variant_selection"])
        self.assertEqual(len(first.selected_path_hashes), 3)
        validation_calls = [row for row in calls if row[1] == 1050]
        prefix_check_calls = [row for row in calls if row[1] == 1500]
        development_calls = [row for row in calls if row[1] == 1450]
        self.assertEqual(len(validation_calls), 15)
        self.assertEqual(len(prefix_check_calls), 15)
        self.assertEqual(development_calls, [("continuation_base", 1450)] * 3)
        self.assertTrue(all(
            not row.validation_contrasts["falsifiers_selection_eligible"]
            for row in first.selections
        ))

        calls.clear()
        second = run_scientific_scout(
            _spec(), folds, configurations=configurations, evaluator=evaluator
        )
        self.assertEqual(first.result_sha256, second.result_sha256)
        self.assertEqual(dict(first.selected_path_hashes), dict(second.selected_path_hashes))
        self.assertEqual(first.to_payload(), second.to_payload())
        self.assertEqual(first.claim_ceiling, "diagnostic_observation")
        self.assertFalse(first.mt5_executed)
        self.assertFalse(first.economics_claim_allowed)

    def test_zero_required_spread_routes_to_unknown_cost(self) -> None:
        bars = _bars(datetime(2025, 1, 1), size=90)
        spread = bars.spread.copy()
        spread[11] = 0.0  # long entry spread
        spread[27] = 0.0  # short exit spread
        spread[31] = 0.0  # short entry spread is not the required short cost
        spread[40] = 0.0  # decision spread is unknown, not a free signal
        bars = BarArrays(
            time=bars.time, open=bars.open, high=bars.high, low=bars.low,
            close=bars.close, tick_volume=bars.tick_volume, spread=spread,
        )
        directions = [0] * len(bars)
        directions[10] = 1
        directions[20] = -1
        directions[30] = -1
        directions[40] = 1
        evaluation = FakeEvaluation(
            directions=tuple(directions),
            scores=(1.0,) * len(bars),
            valid_mask=(True,) * len(bars),
        )
        row = evaluate_signal_role(
            fold_id="V2D002",
            bars=bars,
            boundary=IndexBoundary("validation_oos", 5, 70),
            configuration_role="continuation_base",
            configuration_sha256=_spec().bundle_role_hashes["continuation_base"],
            evaluation=evaluation,
            spec=_spec(),
        )
        self.assertEqual(row.metrics["entry_count"], 4)
        self.assertEqual(row.metrics["unknown_cost_observation_count"], 3)
        self.assertEqual(row.metrics["evaluable_trade_count"], 1)
        self.assertIsNone(row.metrics["net_broker_points"])
        self.assertEqual(row.metrics["after_cost_metric_state"], "not_evaluable")
        self.assertFalse(row.metrics["selection_feasible"])
        self.assertEqual(
            [trade.exclusion_reason for trade in row.trades],
            [
                "unknown_required_spread",
                "unknown_required_spread",
                None,
                "unknown_decision_spread",
            ],
        )
        self.assertIsNotNone(row.trades[-1].gross_broker_points)

    def test_validation_unknown_cost_is_an_evidence_gap_not_a_rejection(self) -> None:
        folds = list(
            _fold(fold_id, datetime(2020 + index * 2, 1, 1))
            for index, fold_id in enumerate(ANCHORS)
        )
        first = folds[0]
        spread = first.bars.spread.copy()
        spread[150] = 0.0
        folds[0] = ScientificFold(
            window=first.window,
            bars=BarArrays(
                time=first.bars.time,
                open=first.bars.open,
                high=first.bars.high,
                low=first.bars.low,
                close=first.bars.close,
                tick_volume=first.bars.tick_volume,
                spread=spread,
            ),
        )
        configurations = tuple(FakeConfiguration(role) for role in BUNDLE_ROLES)

        def evaluator(bars: BarArrays, configuration: FakeConfiguration) -> FakeEvaluation:
            direction = (
                -1
                if configuration.role
                in {"failed_break_reversal", "compression_ablation"}
                else 1
            )
            return FakeEvaluation(
                directions=(direction,) * len(bars),
                scores=(1.0,) * len(bars),
                valid_mask=(True,) * len(bars),
                configuration_sha256=configuration.identity_sha256,
                executable_sha256=_spec().runtime_executable_sha256,
            )

        result = run_scientific_scout(
            _spec(), tuple(folds), configurations=configurations, evaluator=evaluator
        )
        self.assertEqual(result.outcome, "evidence_gap")
        self.assertFalse(result.gate_passed)
        self.assertGreater(
            result.metrics["validation_unknown_cost_observation_count"], 0
        )
        self.assertEqual(
            result.metrics["unknown_cost_observation_count"],
            result.metrics["validation_unknown_cost_observation_count"]
            + result.metrics["development_unknown_cost_observation_count"],
        )

    def test_development_prefix_drift_requires_repair(self) -> None:
        folds = tuple(
            _fold(fold_id, datetime(2020 + index * 2, 1, 1))
            for index, fold_id in enumerate(ANCHORS)
        )
        configurations = tuple(FakeConfiguration(role) for role in BUNDLE_ROLES)

        def evaluator(bars: BarArrays, configuration: FakeConfiguration) -> FakeEvaluation:
            direction = (
                -1
                if configuration.role
                in {"failed_break_reversal", "compression_ablation"}
                else 1
            )
            directions = [direction] * len(bars)
            if len(bars) == 1500 and configuration.role == "continuation_base":
                directions[1100] = -1
            return FakeEvaluation(
                directions=tuple(directions),
                scores=(1.0,) * len(bars),
                valid_mask=(True,) * len(bars),
                configuration_sha256=configuration.identity_sha256,
                executable_sha256=_spec().runtime_executable_sha256,
            )

        result = run_scientific_scout(
            _spec(), folds, configurations=configurations, evaluator=evaluator
        )
        self.assertEqual(result.outcome, "repair_required")
        self.assertFalse(result.gate_passed)
        self.assertFalse(result.causal_checks["all_role_checks_passed"])

    def test_valid_low_density_rejection_has_no_development_path(self) -> None:
        folds = tuple(
            _fold(fold_id, datetime(2020 + index * 2, 1, 1))
            for index, fold_id in enumerate(ANCHORS)
        )
        configurations = tuple(FakeConfiguration(role) for role in BUNDLE_ROLES)

        def evaluator(bars: BarArrays, configuration: FakeConfiguration) -> FakeEvaluation:
            return FakeEvaluation(
                directions=(0,) * len(bars),
                scores=(0.0,) * len(bars),
                valid_mask=(True,) * len(bars),
                configuration_sha256=configuration.identity_sha256,
                executable_sha256=_spec().runtime_executable_sha256,
            )

        result = run_scientific_scout(
            _spec(), folds, configurations=configurations, evaluator=evaluator
        )
        self.assertEqual(result.outcome, "scientific_reject")
        self.assertFalse(result.gate_passed)
        self.assertEqual(dict(result.selected_path_hashes), {})
        self.assertEqual(result.trial_accounting["development_selected_paths"], 0)

    def test_reversal_dependency_excludes_t_minus_26_boundary(self) -> None:
        bars = _bars(datetime(2025, 1, 1), size=90)
        directions = [0] * len(bars)
        directions[30] = -1
        evaluation = FakeEvaluation(
            directions=tuple(directions),
            scores=(1.0,) * len(bars),
            valid_mask=(True,) * len(bars),
        )
        kwargs = {
            "fold_id": "V2D002",
            "bars": bars,
            "boundary": IndexBoundary("validation_oos", 30, 70),
            "configuration_role": "failed_break_reversal",
            "configuration_sha256": _spec().bundle_role_hashes[
                "failed_break_reversal"
            ],
            "evaluation": evaluation,
            "spec": _spec(),
        }
        without_gap = evaluate_signal_role(**kwargs)
        with_gap = evaluate_signal_role(
            **kwargs,
            non_allow_gaps=(
                BoundaryGap(
                    start=bars.time[4],
                    end=bars.time[5],
                    missing_bars=1,
                    action="exclude",
                    classification="fixture",
                ),
            ),
        )
        self.assertEqual(without_gap.metrics["entry_count"], 1)
        self.assertEqual(with_gap.metrics["entry_count"], 0)


if __name__ == "__main__":
    unittest.main()
