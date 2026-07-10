from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
import tempfile
import unittest

import numpy as np

from axiom_rift.v2.data.blackouts import BoundaryGap
from axiom_rift.v2.features import BarArrays
from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.jobs.scout import _write_json
from axiom_rift.v2.research.evaluation import (
    EvaluationProfile,
    FailureEffect,
    MetricRule,
)
from axiom_rift.v2.research.scientific_scout import (
    ANCHORS,
    BUNDLE_ROLES,
    CAUSAL_SPREAD_FLOOR_IMPLEMENTATION_KEY,
    DIRECTIONAL_BUNDLE_ROLES,
    DIRECTIONAL_SELECTION_RULE_SHA256,
    RoleEvaluation,
    ScientificFold,
    ScientificScoutError,
    ScientificScoutSpec,
    SCIENTIFIC_SELECTION_RULE_SHA256,
    SESSION_GAP_BUNDLE_ROLES,
    SESSION_GAP_SELECTION_RULE_SHA256,
    evaluate_signal_role,
    resolve_scientific_scout_outcome,
    run_scientific_scout,
    select_continuation_path,
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


def _directional_spec() -> ScientificScoutSpec:
    base = _spec()
    return replace(
        base,
        hypothesis_id="V2H0004",
        bundle_role_hashes={
            role: sha256_payload({"directional_bundle_role": role})
            for role in DIRECTIONAL_BUNDLE_ROLES
        },
        release_configuration_hashes={
            role: sha256_payload({"directional_configuration": role})
            for role in DIRECTIONAL_BUNDLE_ROLES
        },
        selection_rule_sha256=DIRECTIONAL_SELECTION_RULE_SHA256,
        trade_implementation_key=CAUSAL_SPREAD_FLOOR_IMPLEMENTATION_KEY,
    )


def _session_spec() -> ScientificScoutSpec:
    base = _spec()
    return replace(
        base,
        hypothesis_id="V2H0005",
        family_id="cash_open_gap_failure_v1",
        bundle_role_hashes={
            role: sha256_payload({"session_bundle_role": role})
            for role in SESSION_GAP_BUNDLE_ROLES
        },
        release_configuration_hashes={
            role: sha256_payload({"session_configuration": role})
            for role in SESSION_GAP_BUNDLE_ROLES
        },
        selection_rule_sha256=SESSION_GAP_SELECTION_RULE_SHA256,
        trade_implementation_key=CAUSAL_SPREAD_FLOOR_IMPLEMENTATION_KEY,
        plateau_tolerance_broker_points=0.0,
    )


class ScientificScoutTests(unittest.TestCase):
    def test_identified_falsifier_precedes_induced_evidence_gap(self) -> None:
        self.assertEqual(
            resolve_scientific_scout_outcome(
                kpi_route="evidence_gap",
                gate_passed=False,
                identified_falsifier=True,
            ),
            "scientific_reject",
        )
        self.assertEqual(
            resolve_scientific_scout_outcome(
                kpi_route="repair_required",
                gate_passed=False,
                identified_falsifier=True,
            ),
            "repair_required",
        )
        self.assertEqual(
            resolve_scientific_scout_outcome(
                kpi_route="evidence_gap",
                gate_passed=False,
                identified_falsifier=False,
            ),
            "evidence_gap",
        )

    def test_directional_selection_uses_shadow_and_never_selects_controls(self) -> None:
        spec = _directional_spec()

        def row(role: str, value: float, *, feasible: bool = True) -> RoleEvaluation:
            metrics = MappingProxyType(
                {
                    "selection_feasible": feasible,
                    "net_broker_points": value + 5000.0,
                    "shadow_net_broker_points": value,
                }
            )
            return RoleEvaluation(
                fold_id="V2D002",
                data_role="validation_oos",
                configuration_role=role,
                configuration_sha256=spec.bundle_role_hashes[role],
                metrics=metrics,
                causal_checks=MappingProxyType({"prefix_invariance": True}),
                trades=(),
                evaluation_sha256=sha256_payload(
                    {"role": role, "shadow": value, "feasible": feasible}
                ),
            )

        evaluations = {
            "short_reversal_low": row(
                "short_reversal_low", 50000.0, feasible=False
            ),
            "short_reversal_base": row("short_reversal_base", 1000.0),
            "short_reversal_high": row("short_reversal_high", 900.0),
            "long_reversal_control": row("long_reversal_control", 0.0),
            "short_continuation_control": row(
                "short_continuation_control", 100.0
            ),
        }
        selected = select_continuation_path("V2D002", evaluations, spec)
        self.assertEqual(selected.selected_role, "short_reversal_base")
        self.assertFalse(selected.falsifier_triggered)
        self.assertEqual(
            selected.plateau_roles,
            ("short_reversal_base", "short_reversal_high"),
        )
        self.assertIn(
            "short_reversal_low",
            selected.validation_contrasts["unevaluable_roles"],
        )

        evaluations["long_reversal_control"] = row(
            "long_reversal_control", 950.0
        )
        falsified = select_continuation_path("V2D002", evaluations, spec)
        self.assertEqual(falsified.selected_role, "short_reversal_base")
        self.assertTrue(falsified.falsifier_triggered)
        self.assertTrue(
            falsified.validation_contrasts[
                "long_reversal_control_falsifies"
            ]
        )

    def test_session_selection_freezes_primary_and_controls_falsify_at_zero_tolerance(
        self,
    ) -> None:
        spec = _session_spec()

        def row(role: str, value: float, *, feasible: bool = True) -> RoleEvaluation:
            return RoleEvaluation(
                fold_id="V2D002",
                data_role="validation_oos",
                configuration_role=role,
                configuration_sha256=spec.bundle_role_hashes[role],
                metrics=MappingProxyType(
                    {
                        "selection_feasible": feasible,
                        "net_broker_points": value,
                        "shadow_net_broker_points": value,
                    }
                ),
                causal_checks=MappingProxyType({"prefix_invariance": True}),
                trades=(),
                evaluation_sha256=sha256_payload(
                    {"role": role, "shadow": value, "feasible": feasible}
                ),
            )

        evaluations = {
            SESSION_GAP_BUNDLE_ROLES[0]: row(
                SESSION_GAP_BUNDLE_ROLES[0], 100.0
            ),
            SESSION_GAP_BUNDLE_ROLES[1]: row(
                SESSION_GAP_BUNDLE_ROLES[1], 99.0
            ),
            SESSION_GAP_BUNDLE_ROLES[2]: row(
                SESSION_GAP_BUNDLE_ROLES[2], 98.0
            ),
        }
        selected = select_continuation_path("V2D002", evaluations, spec)
        self.assertEqual(SESSION_GAP_BUNDLE_ROLES[0], selected.selected_role)
        self.assertFalse(selected.falsifier_triggered)

        evaluations[SESSION_GAP_BUNDLE_ROLES[2]] = row(
            SESSION_GAP_BUNDLE_ROLES[2], 100.0
        )
        falsified = select_continuation_path("V2D002", evaluations, spec)
        self.assertTrue(falsified.falsifier_triggered)
        self.assertTrue(
            falsified.validation_contrasts["plus_60m_control_falsifies"]
        )

        evaluations[SESSION_GAP_BUNDLE_ROLES[1]] = row(
            SESSION_GAP_BUNDLE_ROLES[1], 0.0, feasible=False
        )
        insufficient = select_continuation_path("V2D002", evaluations, spec)
        self.assertIsNone(insufficient.selected_role)
        self.assertFalse(insufficient.falsifier_triggered)

    def test_session_dependency_is_checked_before_zero_spread_rejection(self) -> None:
        bars = _bars(datetime(2025, 1, 1), size=90)
        spread = bars.spread.copy()
        spread[10] = 0.0
        bars = BarArrays(
            time=bars.time,
            open=bars.open,
            high=bars.high,
            low=bars.low,
            close=bars.close,
            tick_volume=bars.tick_volume,
            spread=spread,
        )
        directions = [0] * len(bars)
        directions[10] = 1
        evaluation = SimpleNamespace(
            directions=tuple(directions),
            scores=(1.0,) * len(bars),
            valid_mask=(True,) * len(bars),
            features=tuple(
                SimpleNamespace(atr_24=1.0, dependency_start_index=None)
                for _ in range(len(bars))
            ),
            clock_rule_id="fpmarkets_ny_close_plus_7_v1",
            clock_authority_claim=False,
        )
        with self.assertRaisesRegex(
            ScientificScoutError,
            "exact causal dependency start",
        ):
            evaluate_signal_role(
                fold_id="V2D002",
                bars=bars,
                boundary=IndexBoundary("validation_oos", 5, 70),
                configuration_role=SESSION_GAP_BUNDLE_ROLES[0],
                configuration_sha256=_session_spec().bundle_role_hashes[
                    SESSION_GAP_BUNDLE_ROLES[0]
                ],
                evaluation=evaluation,
                spec=_session_spec(),
            )

    def test_artifact_writer_serializes_nested_immutable_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            _write_json(
                path,
                {
                    "programs": MappingProxyType(
                        {
                            "role": MappingProxyType(
                                {"trade": MappingProxyType({"id": "V2TP1001"})}
                            )
                        }
                    )
                },
            )
            self.assertEqual(
                {"programs": {"role": {"trade": {"id": "V2TP1001"}}}},
                json.loads(path.read_text(encoding="ascii")),
            )
            self.assertNotIn(b"\r", path.read_bytes())

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

    def test_causal_spread_floor_rejects_zero_decision_and_records_cost_source(self) -> None:
        bars = _bars(datetime(2025, 1, 1), size=90)
        spread = bars.spread.copy()
        spread[11] = 0.0  # long execution fallback
        spread[12] = 0.0  # rejected even while the prior trade is occupied
        spread[27] = 0.0  # short execution fallback
        spread[37] = 1.0  # short execution below the decision floor
        spread[40] = 0.0  # rejected before occupancy
        spread[51] = 5.0  # long execution above the decision spread
        bars = BarArrays(
            time=bars.time,
            open=bars.open,
            high=bars.high,
            low=bars.low,
            close=bars.close,
            tick_volume=bars.tick_volume,
            spread=spread,
        )
        directions = [0] * len(bars)
        for index, direction in (
            (10, 1),
            (12, 1),
            (20, -1),
            (30, -1),
            (40, 1),
            (41, 1),
            (50, 1),
        ):
            directions[index] = direction
        evaluation = FakeEvaluation(
            directions=tuple(directions),
            scores=(1.0,) * len(bars),
            valid_mask=(True,) * len(bars),
        )
        spec = replace(
            _spec(),
            trade_implementation_key="fixed_6bar_causal_spread_floor_v1",
        )
        row = evaluate_signal_role(
            fold_id="V2D002",
            bars=bars,
            boundary=IndexBoundary("validation_oos", 5, 70),
            configuration_role="continuation_base",
            configuration_sha256=spec.bundle_role_hashes["continuation_base"],
            evaluation=evaluation,
            spec=spec,
        )
        self.assertEqual(5, row.metrics["entry_count"])
        self.assertEqual(5, row.metrics["evaluable_trade_count"])
        self.assertEqual(0, row.metrics["unknown_cost_observation_count"])
        self.assertEqual(
            2, row.metrics["zero_decision_spread_rejection_count"]
        )
        self.assertEqual(2, row.metrics["execution_spread_fallback_count"])
        self.assertEqual(3, row.metrics["observed_execution_cost_trade_count"])
        self.assertEqual(3, row.metrics["shadow_evaluable_trade_count"])
        self.assertEqual(
            [2.0, 2.0, 2.0, 2.0, 5.0],
            [trade.spread_cost_broker_points for trade in row.trades],
        )
        self.assertEqual(
            [0.0, 0.0, 1.0, 2.0, 5.0],
            [
                trade.applicable_execution_spread_broker_points
                for trade in row.trades
            ],
        )
        self.assertEqual(
            [True, True, False, False, False],
            [trade.execution_spread_fallback_used for trade in row.trades],
        )
        self.assertTrue(
            row.causal_checks["zero_decision_rejected_before_admission"]
        )
        self.assertTrue(
            row.causal_checks["observed_execution_cost_not_undercharged"]
        )
        self.assertEqual(
            "causal_policy_evaluable",
            row.metrics["after_cost_metric_state"],
        )
        self.assertFalse(row.metrics["selection_feasible"])

    def test_causal_spread_floor_rejects_negative_or_nonfinite_input(self) -> None:
        base = _bars(datetime(2025, 1, 1), size=90)
        directions = [0] * len(base)
        directions[10] = 1
        evaluation = FakeEvaluation(
            directions=tuple(directions),
            scores=(1.0,) * len(base),
            valid_mask=(True,) * len(base),
        )
        spec = replace(
            _spec(),
            trade_implementation_key="fixed_6bar_causal_spread_floor_v1",
        )
        for invalid in (-1.0, float("nan")):
            spread = base.spread.copy()
            spread[11] = invalid
            bars = BarArrays(
                time=base.time,
                open=base.open,
                high=base.high,
                low=base.low,
                close=base.close,
                tick_volume=base.tick_volume,
                spread=spread,
            )
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ScientificScoutError,
                "finite and nonnegative",
            ):
                evaluate_signal_role(
                    fold_id="V2D002",
                    bars=bars,
                    boundary=IndexBoundary("validation_oos", 5, 70),
                    configuration_role="continuation_base",
                    configuration_sha256=spec.bundle_role_hashes[
                        "continuation_base"
                    ],
                    evaluation=evaluation,
                    spec=spec,
                )

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
