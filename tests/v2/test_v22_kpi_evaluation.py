from __future__ import annotations

import math
import unittest

from axiom_rift.v2.research.evaluation import (
    EvaluationProfile,
    FailureEffect,
    MetricObservation,
    MetricRule,
    SensitivityState,
    Stage,
    TuningContext,
    TuningRole,
    VerdictStatus,
    interpret_kpis,
)


def evaluation_profile() -> EvaluationProfile:
    return EvaluationProfile(
        profile_id="V2KPI_TEST_0001",
        rules=(
            MetricRule.equal(
                "causal_checks_all_pass",
                "integrity",
                stages=(Stage.S, Stage.R, Stage.P),
                expected=True,
                failure_effect=FailureEffect.REPAIR,
            ),
            MetricRule.maximum(
                "unknown_cost_trade_count",
                "integrity",
                stages=(Stage.S, Stage.R, Stage.P),
                pass_at=0,
                failure_effect=FailureEffect.REPAIR,
            ),
            MetricRule.range(
                "entries_per_eligible_day",
                "activity",
                stages=(Stage.S, Stage.R, Stage.P),
                pass_min=5.0,
                pass_max=10.0,
                fail_below=2.0,
                fail_above=15.0,
                tuning_role=TuningRole.CALIBRATABLE,
            ),
            MetricRule.minimum(
                "profit_factor",
                "economics",
                stages=(Stage.S, Stage.R, Stage.P),
                pass_at=1.20,
                fail_below=1.00,
                tuning_role=TuningRole.SENSITIVITY_ONLY,
            ),
            MetricRule.maximum(
                "monthly_drawdown_points",
                "risk",
                stages=(Stage.R, Stage.P),
                pass_at=100.0,
                fail_above=150.0,
            ),
            MetricRule.minimum(
                "positive_fold_share",
                "stability",
                stages=(Stage.R, Stage.P),
                pass_at=0.67,
                fail_below=0.50,
            ),
            MetricRule.equal(
                "mt5_decision_parity",
                "execution",
                stages=(Stage.P,),
                expected=True,
            ),
            MetricRule.equal(
                "onnx_ea_parity",
                "execution",
                stages=(Stage.M,),
                expected=True,
            ),
        ),
    )


def scout_metrics(**overrides: object) -> dict[str, object]:
    metrics: dict[str, object] = {
        "causal_checks_all_pass": True,
        "unknown_cost_trade_count": 0,
        "entries_per_eligible_day": 7.0,
        "profit_factor": 1.35,
    }
    metrics.update(overrides)
    return metrics


def confirmation_metrics(**overrides: object) -> dict[str, object]:
    metrics = scout_metrics()
    metrics.update(
        {
            "monthly_drawdown_points": 80.0,
            "positive_fold_share": 0.78,
        }
    )
    metrics.update(overrides)
    return metrics


class V22KpiEvaluationTests(unittest.TestCase):
    def test_h_stage_has_no_post_run_kpis_and_routes_to_hypothesis_ready(self) -> None:
        result = interpret_kpis(Stage.H, {}, evaluation_profile())

        self.assertEqual(result.route, "hypothesis_ready")
        self.assertTrue(
            all(row.status is VerdictStatus.NOT_SCHEDULED for row in result.metric_verdicts)
        )

    def test_stage_scope_distinguishes_missing_from_not_required(self) -> None:
        profile = evaluation_profile()
        scout = interpret_kpis(Stage.S, scout_metrics(), profile)

        self.assertEqual(scout.metric("monthly_drawdown_points").status, VerdictStatus.NOT_SCHEDULED)
        self.assertEqual(scout.dimension("risk").status, VerdictStatus.NOT_SCHEDULED)

        confirmation = confirmation_metrics()
        confirmation.pop("monthly_drawdown_points")
        result = interpret_kpis(Stage.R, confirmation, profile)

        self.assertEqual(result.metric("monthly_drawdown_points").status, VerdictStatus.MISSING)
        self.assertEqual(result.route, "repair_required")

    def test_explicit_not_required_cannot_hide_a_required_metric(self) -> None:
        metrics = scout_metrics(profit_factor=MetricObservation.not_required())
        result = interpret_kpis(Stage.S, metrics, evaluation_profile())

        self.assertEqual(result.metric("profit_factor").status, VerdictStatus.INVALID)
        self.assertEqual(result.route, "repair_required")

    def test_none_nan_and_wrong_numeric_type_are_invalid_evidence(self) -> None:
        for invalid_value in (None, math.nan, "1.35", True):
            with self.subTest(invalid_value=invalid_value):
                result = interpret_kpis(
                    Stage.S,
                    scout_metrics(profit_factor=invalid_value),
                    evaluation_profile(),
                )
                self.assertEqual(result.metric("profit_factor").status, VerdictStatus.INVALID)
                self.assertEqual(result.route, "repair_required")

    def test_integrity_failure_routes_to_repair_not_hypothesis_rejection(self) -> None:
        result = interpret_kpis(
            Stage.S,
            scout_metrics(causal_checks_all_pass=False),
            evaluation_profile(),
        )

        self.assertEqual(result.dimension("integrity").status, VerdictStatus.FAIL)
        self.assertEqual(result.route, "repair_required")

    def test_scout_passes_by_non_compensatory_dimensions_without_magic_score(self) -> None:
        result = interpret_kpis(Stage.S, scout_metrics(), evaluation_profile())
        payload = result.to_payload()

        self.assertEqual(result.route, "route_to_R")
        self.assertEqual(result.dimension("activity").status, VerdictStatus.PASS)
        self.assertEqual(result.dimension("economics").status, VerdictStatus.PASS)
        self.assertEqual(payload["aggregation"], "non_compensatory_precedence")
        self.assertNotIn("score", payload)
        self.assertNotIn("weighted_score", payload)

    def test_non_tunable_scout_failure_is_rejected_even_if_other_kpis_are_strong(self) -> None:
        profile = EvaluationProfile(
            profile_id="V2KPI_NON_TUNABLE",
            rules=(
                MetricRule.minimum(
                    "net_points",
                    "economics",
                    stages=(Stage.S,),
                    pass_at=1.0,
                ),
                MetricRule.maximum(
                    "drawdown",
                    "risk",
                    stages=(Stage.S,),
                    pass_at=100.0,
                ),
            ),
        )
        result = interpret_kpis(
            Stage.S,
            {"net_points": -1.0, "drawdown": 1.0},
            profile,
        )

        self.assertEqual(result.route, "scout_rejected")
        self.assertEqual(result.dimension("economics").status, VerdictStatus.FAIL)

    def test_tunable_weakness_gets_one_bounded_sensitivity_review(self) -> None:
        result = interpret_kpis(
            Stage.S,
            scout_metrics(entries_per_eligible_day=3.0),
            evaluation_profile(),
            tuning=TuningContext(
                sensitivity_state=SensitivityState.NOT_ASSESSED,
                sensitivity_budget_remaining=1,
            ),
        )

        self.assertEqual(result.metric("entries_per_eligible_day").status, VerdictStatus.WARN)
        self.assertEqual(result.route, "sensitivity_review")

    def test_extreme_tunable_failure_may_be_shaken_but_not_declared_passing(self) -> None:
        result = interpret_kpis(
            Stage.S,
            scout_metrics(entries_per_eligible_day=1.0),
            evaluation_profile(),
            tuning=TuningContext(
                sensitivity_state=SensitivityState.NOT_ASSESSED,
                sensitivity_budget_remaining=1,
            ),
        )

        self.assertEqual(result.metric("entries_per_eligible_day").status, VerdictStatus.FAIL)
        self.assertEqual(result.route, "sensitivity_review")

    def test_coherent_sensitivity_can_authorize_one_local_calibration(self) -> None:
        result = interpret_kpis(
            Stage.S,
            scout_metrics(entries_per_eligible_day=3.0),
            evaluation_profile(),
            tuning=TuningContext(
                sensitivity_state=SensitivityState.PLATEAU,
                calibration_budget_remaining=1,
            ),
        )

        self.assertEqual(result.route, "local_calibration_eligible")

    def test_needle_or_edge_hit_cannot_be_called_local_calibration(self) -> None:
        for state in (SensitivityState.NEEDLE, SensitivityState.EDGE_HIT):
            with self.subTest(state=state):
                result = interpret_kpis(
                    Stage.S,
                    scout_metrics(entries_per_eligible_day=3.0),
                    evaluation_profile(),
                    tuning=TuningContext(
                        sensitivity_state=state,
                        calibration_budget_remaining=1,
                    ),
                )
                self.assertEqual(result.route, "scout_rejected")

    def test_candidate_freeze_disables_tuning_routes(self) -> None:
        result = interpret_kpis(
            Stage.R,
            confirmation_metrics(entries_per_eligible_day=3.0),
            evaluation_profile(),
            tuning=TuningContext(
                sensitivity_state=SensitivityState.PLATEAU,
                calibration_budget_remaining=1,
                candidate_frozen=True,
            ),
        )

        self.assertEqual(result.route, "route_to_P")
        self.assertEqual(result.dimension("activity").status, VerdictStatus.WARN)

    def test_confirmation_routes_are_stage_specific(self) -> None:
        passed = interpret_kpis(Stage.R, confirmation_metrics(), evaluation_profile())
        failed = interpret_kpis(
            Stage.R,
            confirmation_metrics(monthly_drawdown_points=175.0),
            evaluation_profile(),
        )

        self.assertEqual(passed.route, "route_to_P")
        self.assertEqual(failed.route, "confirmation_rejected")

    def test_promotion_and_materialization_have_distinct_requirements_and_routes(self) -> None:
        promotion = confirmation_metrics(mt5_decision_parity=True)
        promoted = interpret_kpis(Stage.P, promotion, evaluation_profile())
        materialized = interpret_kpis(
            Stage.M,
            {"onnx_ea_parity": True},
            evaluation_profile(),
        )

        self.assertEqual(promoted.route, "route_to_M")
        self.assertEqual(materialized.route, "materialization_complete")
        self.assertEqual(
            materialized.metric("profit_factor").status,
            VerdictStatus.NOT_SCHEDULED,
        )

    def test_censored_and_not_evaluable_are_scientific_nonpasses_not_repairs(self) -> None:
        for observation, expected in (
            (MetricObservation.censored("no_observed_loss"), VerdictStatus.CENSORED),
            (MetricObservation.not_evaluable("no_trades"), VerdictStatus.NOT_EVALUABLE),
        ):
            with self.subTest(expected=expected):
                result = interpret_kpis(
                    Stage.S,
                    scout_metrics(profit_factor=observation),
                    evaluation_profile(),
                )
                self.assertEqual(result.metric("profit_factor").status, expected)
                self.assertEqual(result.route, "scout_rejected")

    def test_diagnostic_metric_failure_remains_visible_without_blocking(self) -> None:
        profile = EvaluationProfile(
            profile_id="V2KPI_DIAGNOSTIC",
            rules=(
                MetricRule.range(
                    "entries_per_eligible_day",
                    "activity",
                    stages=(Stage.S,),
                    pass_min=5.0,
                    pass_max=10.0,
                    failure_effect=FailureEffect.DIAGNOSTIC,
                ),
            ),
        )
        result = interpret_kpis(
            Stage.S,
            {"entries_per_eligible_day": 1.0},
            profile,
        )

        self.assertEqual(result.dimension("activity").status, VerdictStatus.FAIL)
        self.assertEqual(result.route, "route_to_R")

    def test_unknown_cost_can_route_to_evidence_gap_without_falsifying_hypothesis(self) -> None:
        profile = EvaluationProfile(
            profile_id="V2KPI_EVIDENCE_GAP",
            rules=(
                MetricRule.maximum(
                    "unknown_cost_trade_count",
                    "integrity",
                    stages=(Stage.S,),
                    pass_at=0,
                    failure_effect=FailureEffect.EVIDENCE_GAP,
                ),
            ),
        )
        result = interpret_kpis(
            Stage.S,
            {"unknown_cost_trade_count": 3},
            profile,
        )

        self.assertEqual(result.route, "evidence_gap")
        self.assertIn("required_evidence_is_not_identified", result.reason_codes)

    def test_bad_sensitivity_shape_blocks_even_passing_development_kpis(self) -> None:
        result = interpret_kpis(
            Stage.S,
            scout_metrics(),
            evaluation_profile(),
            tuning=TuningContext(sensitivity_state=SensitivityState.BOUNDARY_TREND),
        )

        self.assertEqual(result.route, "scout_rejected")
        self.assertIn("sensitivity_shape_not_robust", result.reason_codes)

    def test_unregistered_metrics_are_exposed_but_do_not_change_registered_gates(self) -> None:
        result = interpret_kpis(
            Stage.S,
            scout_metrics(unregistered_diagnostic=999999.0),
            evaluation_profile(),
        )

        self.assertEqual(result.route, "route_to_R")
        self.assertEqual(result.unregistered_metric_names, ("unregistered_diagnostic",))


if __name__ == "__main__":
    unittest.main()
