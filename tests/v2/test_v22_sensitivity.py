from __future__ import annotations

import unittest
from dataclasses import replace

from axiom_rift.v2.research.sensitivity import (
    ALLOWED_TARGETS,
    SensitivityError,
    SurfaceRule,
    VariantEvidence,
    assess_sensitivity,
    build_oat_plan,
    finalize_sensitivity_choice,
    propose_local_midpoint,
)


def baseline_parameters() -> dict[str, object]:
    return {
        "model": {"alpha": 1.0, "family": "ridge"},
        "calibration": {"quantile": 0.80},
        "selector": {"cost_multiplier": 1.0},
        "trade": {"hold_bars": 12, "stop_loss": 100.0, "take_profit": 150.0},
    }


def two_knob_policy(reverse: bool = False) -> dict[str, object]:
    model = {
        "alpha": {"type": "float", "low": 0.10, "baseline": 1.0, "high": 10.0}
    }
    calibration = {
        "quantile": {"type": "float", "low": 0.60, "baseline": 0.80, "high": 0.95}
    }
    if reverse:
        return {"calibration": calibration, "model": model}
    return {"model": model, "calibration": calibration}


def alpha_policy() -> dict[str, object]:
    return {
        "model": {
            "alpha": {"type": "float", "low": 0.10, "baseline": 1.0, "high": 10.0}
        }
    }


def make_plan(policy: dict[str, object] | None = None):
    return build_oat_plan(
        hypothesis_id="V2H0042",
        stage="S",
        baseline_parameters=baseline_parameters(),
        nested_policy=policy or alpha_policy(),
    )


def evidence_for(plan, aggregates, folds=None):
    folds = folds or {}
    rows = []
    for variant in plan.variants:
        key = (variant.role, variant.knob_path)
        aggregate = aggregates[key]
        fold_values = folds.get(key, {"V2D001": aggregate, "V2D002": aggregate})
        rows.append(
            VariantEvidence.from_mapping(
                variant.variant_id,
                aggregate,
                fold_values,
                feasible_folds(fold_values),
            )
        )
    return tuple(rows)


def feasible_folds(fold_values):
    return {
        fold_id: {
            "feasible": True,
            "causal_checks_passed": True,
            "unknown_cost_observation_count": 0,
            "evaluable_trade_count": 10,
            "reason_codes": [],
        }
        for fold_id in fold_values
    }


RULE = SurfaceRule(
    metric_name="profit_factor",
    higher_is_better=True,
    pass_threshold=1.10,
    plateau_tolerance=0.10,
    fold_consistency_min=0.50,
    viability_threshold=1.00,
)


class V22SensitivityTests(unittest.TestCase):
    def test_viability_threshold_defaults_to_pass_threshold(self) -> None:
        rule = SurfaceRule(
            metric_name="profit_factor",
            higher_is_better=True,
            pass_threshold=1.10,
            plateau_tolerance=0.10,
        )

        self.assertEqual(rule.effective_viability_threshold, 1.10)

    def test_empty_policy_builds_validation_oos_baseline_only_plan(self) -> None:
        plan = build_oat_plan(
            hypothesis_id="V2H0042",
            stage="S",
            baseline_parameters=baseline_parameters(),
            nested_policy={},
            disabled_reason="no_safe_registered_numeric_knob",
        )

        self.assertEqual(plan.data_role, "validation_oos")
        self.assertEqual(plan.knobs, ())
        self.assertEqual(len(plan.variants), 1)
        self.assertEqual(plan.variants[0].role, "baseline")
        self.assertFalse(plan.to_payload()["sensitivity_enabled"])
        self.assertEqual(
            plan.disabled_reason,
            "no_safe_registered_numeric_knob",
        )

    def test_nested_oat_policy_is_deterministic_and_capped_at_two_knobs_five_variants(self) -> None:
        first = make_plan(two_knob_policy())
        second = make_plan(two_knob_policy(reverse=True))

        self.assertEqual(ALLOWED_TARGETS, ("model.alpha", "calibration.quantile"))
        self.assertEqual(first.plan_id, second.plan_id)
        self.assertEqual(first.plan_sha256, second.plan_sha256)
        self.assertEqual(
            [(row.variant_id, row.variant_sha256) for row in first.variants],
            [(row.variant_id, row.variant_sha256) for row in second.variants],
        )
        self.assertEqual(len(first.knobs), 2)
        self.assertEqual(len(first.variants), 5)
        self.assertEqual(first.data_role, "validation_oos")
        self.assertEqual(first.to_payload()["policy"], second.to_payload()["policy"])

    def test_oat_extremes_change_exactly_one_target_and_are_diagnostic_only(self) -> None:
        plan = make_plan(two_knob_policy())
        baseline = plan.variant("baseline").parameters

        for variant in plan.variants[1:]:
            changed = []
            for path in ALLOWED_TARGETS:
                parent, name = path.split(".")
                if variant.parameters[parent][name] != baseline[parent][name]:
                    changed.append(path)
            self.assertEqual(changed, [variant.knob_path])
            self.assertTrue(variant.diagnostic_only)
            self.assertFalse(variant.development_selection_allowed)
        self.assertFalse(plan.development_variant_selection_allowed)

    def test_only_registered_non_structural_targets_are_allowed(self) -> None:
        forbidden = (
            ("selector", "cost_multiplier"),
            ("trade", "hold_bars"),
            ("trade", "stop_loss"),
            ("trade", "take_profit"),
        )
        for parent, name in forbidden:
            with self.subTest(path=f"{parent}.{name}"):
                policy = {
                    parent: {
                        name: {
                            "type": "float",
                            "low": 0.5,
                            "baseline": 1.0,
                            "high": 1.5,
                        }
                    }
                }
                with self.assertRaisesRegex(SensitivityError, "not calibratable"):
                    make_plan(policy)

    def test_target_types_ranges_and_executable_baseline_are_enforced(self) -> None:
        invalid_policies = (
            {"model": {"alpha": {"type": "int", "low": 1, "baseline": 2, "high": 3}}},
            {"model": {"alpha": {"type": "float", "low": True, "baseline": 1.0, "high": 2.0}}},
            {"calibration": {"quantile": {"type": "float", "low": 0.0, "baseline": 0.8, "high": 0.9}}},
            {"model": {"alpha": {"type": "float", "low": 0.1, "baseline": 2.0, "high": 3.0}}},
        )
        for policy in invalid_policies:
            with self.subTest(policy=policy):
                with self.assertRaises(SensitivityError):
                    make_plan(policy)

    def test_holdout_freeze_non_development_and_late_stages_forbid_retuning(self) -> None:
        common = {
            "hypothesis_id": "V2H0042",
            "baseline_parameters": baseline_parameters(),
            "nested_policy": alpha_policy(),
        }
        forbidden = (
            {"stage": "P"},
            {"stage": "S", "holdout_revealed": True},
            {"stage": "R", "candidate_frozen": True},
            {"stage": "S", "data_role": "development"},
            {"stage": "S", "data_role": "holdout"},
        )
        for changes in forbidden:
            with self.subTest(changes=changes):
                with self.assertRaises(SensitivityError):
                    build_oat_plan(**common, **changes)

    def test_variant_evidence_rejects_non_validation_oos_role(self) -> None:
        with self.assertRaisesRegex(SensitivityError, "validation_oos"):
            VariantEvidence.from_mapping(
                "V2SVINVALID",
                1.2,
                {"V2D001": 1.2},
                feasible_folds({"V2D001": 1.2}),
                data_role="development",
            )

    def test_surface_classifies_two_sided_plateau(self) -> None:
        plan = make_plan()
        assessment = assess_sensitivity(
            plan,
            evidence_for(
                plan,
                {
                    ("baseline", None): 1.30,
                    ("extreme_low", "model.alpha"): 1.25,
                    ("extreme_high", "model.alpha"): 1.35,
                },
            ),
            RULE,
        )

        surface = assessment.surface("model.alpha")
        self.assertEqual(surface.shape, "plateau")
        self.assertEqual(surface.plateau_side, "both")
        self.assertFalse(surface.local_midpoint_eligible)

    def test_surface_classifies_needle_boundary_trend_weak_and_unstable(self) -> None:
        cases = (
            ((0.80, 1.40, 0.90), "needle"),
            ((0.90, 1.20, 1.50), "boundary_trend"),
            ((0.70, 0.80, 0.90), "weak"),
            ((1.30, 1.15, 1.35), "unstable"),
        )
        for (low, baseline, high), expected in cases:
            with self.subTest(expected=expected):
                plan = make_plan()
                assessment = assess_sensitivity(
                    plan,
                    evidence_for(
                        plan,
                        {
                            ("baseline", None): baseline,
                            ("extreme_low", "model.alpha"): low,
                            ("extreme_high", "model.alpha"): high,
                        },
                    ),
                    RULE,
                )
                self.assertEqual(assessment.surface("model.alpha").shape, expected)

    def test_fold_relation_disagreement_overrides_aggregate_shape_as_unstable(self) -> None:
        plan = make_plan()
        aggregates = {
            ("baseline", None): 1.30,
            ("extreme_low", "model.alpha"): 1.25,
            ("extreme_high", "model.alpha"): 1.35,
        }
        folds = {
            ("baseline", None): {"V2D001": 1.30, "V2D002": 1.30},
            ("extreme_low", "model.alpha"): {"V2D001": 0.80, "V2D002": 0.80},
            ("extreme_high", "model.alpha"): {"V2D001": 1.80, "V2D002": 1.80},
        }
        assessment = assess_sensitivity(plan, evidence_for(plan, aggregates, folds), RULE)

        self.assertEqual(assessment.surface("model.alpha").shape, "unstable")

    def test_one_sided_plateau_allows_one_inward_midpoint_and_counts_all_trials(self) -> None:
        plan = make_plan()
        assessment = assess_sensitivity(
            plan,
            evidence_for(
                plan,
                {
                    ("baseline", None): 1.05,
                    ("extreme_low", "model.alpha"): 0.80,
                    ("extreme_high", "model.alpha"): 1.12,
                },
            ),
            RULE,
        )
        proposal = propose_local_midpoint(plan, assessment)

        self.assertEqual(assessment.surface("model.alpha").plateau_side, "high")
        self.assertEqual(proposal.variant.knob_value, 5.5)
        self.assertTrue(proposal.variant.diagnostic_only)
        self.assertTrue(proposal.no_edge_chase)
        self.assertFalse(proposal.development_variant_selected)
        self.assertEqual(assessment.trial_counts.distinct_variant_count, 3)
        self.assertEqual(assessment.trial_counts.fold_evaluation_count, 6)
        self.assertEqual(assessment.trial_counts.selection_count, 0)
        self.assertEqual(proposal.trial_counts_after_registration.distinct_variant_count, 4)
        self.assertEqual(proposal.trial_counts_after_registration.fold_evaluation_count, 6)
        self.assertEqual(proposal.trial_counts_after_registration.selection_count, 1)
        with self.assertRaisesRegex(SensitivityError, "budget is exhausted"):
            propose_local_midpoint(
                plan,
                assessment,
                calibration_new_evaluations_used_for_outer_fold=1,
            )

    def test_boundary_trend_cannot_chase_the_edge(self) -> None:
        plan = make_plan()
        assessment = assess_sensitivity(
            plan,
            evidence_for(
                plan,
                {
                    ("baseline", None): 1.20,
                    ("extreme_low", "model.alpha"): 0.90,
                    ("extreme_high", "model.alpha"): 1.50,
                },
            ),
            RULE,
        )

        self.assertEqual(assessment.surface("model.alpha").shape, "boundary_trend")
        with self.assertRaisesRegex(SensitivityError, "one-sided plateau"):
            propose_local_midpoint(plan, assessment)

    def test_two_one_sided_plateaus_do_not_trigger_development_selection(self) -> None:
        plan = make_plan(two_knob_policy())
        assessment = assess_sensitivity(
            plan,
            evidence_for(
                plan,
                {
                    ("baseline", None): 1.05,
                    ("extreme_low", "model.alpha"): 0.80,
                    ("extreme_high", "model.alpha"): 1.12,
                    ("extreme_low", "calibration.quantile"): 0.90,
                    ("extreme_high", "calibration.quantile"): 1.11,
                },
            ),
            RULE,
        )

        self.assertFalse(assessment.development_variant_selected)
        with self.assertRaisesRegex(SensitivityError, "exactly one"):
            propose_local_midpoint(plan, assessment)

    def test_one_sided_plateau_with_other_passing_baseline_plateau_allows_midpoint(self) -> None:
        plan = make_plan(two_knob_policy())
        assessed = assess_sensitivity(
            plan,
            evidence_for(
                plan,
                {
                    ("baseline", None): 1.30,
                    ("extreme_low", "model.alpha"): 1.25,
                    ("extreme_high", "model.alpha"): 1.35,
                    ("extreme_low", "calibration.quantile"): 1.25,
                    ("extreme_high", "calibration.quantile"): 1.35,
                },
            ),
            RULE,
        )
        mixed = replace(
            assessed,
            surfaces=(
                replace(
                    assessed.surface("model.alpha"),
                    plateau_side="high",
                    local_midpoint_eligible=True,
                ),
                replace(
                    assessed.surface("calibration.quantile"),
                    plateau_side="baseline",
                    local_midpoint_eligible=False,
                ),
            ),
        )

        proposal = propose_local_midpoint(plan, mixed)

        self.assertEqual(proposal.variant.knob_path, "model.alpha")
        self.assertEqual(proposal.variant.knob_value, 5.5)

    def test_two_sided_plateau_freezes_baseline_without_development_selection(self) -> None:
        plan = make_plan()
        assessment = assess_sensitivity(
            plan,
            evidence_for(
                plan,
                {
                    ("baseline", None): 1.30,
                    ("extreme_low", "model.alpha"): 1.25,
                    ("extreme_high", "model.alpha"): 1.35,
                },
            ),
            RULE,
        )
        finalized = finalize_sensitivity_choice(plan, assessment, RULE)

        self.assertEqual(finalized.selected_variant_id, plan.variant("baseline").variant_id)
        self.assertEqual(finalized.selection_basis, "baseline_frozen_two_sided_plateau")
        self.assertFalse(finalized.promotion_blocked)
        self.assertFalse(finalized.development_metrics_inspected)
        self.assertTrue(finalized.development_cv_parameters_frozen)
        self.assertFalse(finalized.development_cv_selection_allowed)
        self.assertEqual(finalized.source_data_role, "validation_oos")
        self.assertEqual(finalized.freeze_target_role, "development_cv")
        self.assertEqual(finalized.trial_counts.selection_count, 1)

    def test_passing_baseline_is_frozen_without_local_calibration(self) -> None:
        plan = make_plan()
        assessment = assess_sensitivity(
            plan,
            evidence_for(
                plan,
                {
                    ("baseline", None): 1.30,
                    ("extreme_low", "model.alpha"): 0.80,
                    ("extreme_high", "model.alpha"): 1.35,
                },
            ),
            RULE,
        )
        surface = assessment.surface("model.alpha")
        finalized = finalize_sensitivity_choice(plan, assessment, RULE)

        self.assertEqual(surface.shape, "plateau")
        self.assertEqual(surface.plateau_side, "baseline")
        self.assertFalse(surface.local_midpoint_eligible)
        with self.assertRaisesRegex(SensitivityError, "one-sided plateau"):
            propose_local_midpoint(plan, assessment)
        self.assertEqual(finalized.selected_variant_id, plan.variant("baseline").variant_id)
        self.assertEqual(finalized.selection_basis, "baseline_frozen_already_passing")
        self.assertFalse(finalized.promotion_blocked)

    def test_bad_surface_falls_back_to_baseline_and_keeps_promotion_block(self) -> None:
        cases = (
            ((0.70, 0.80, 0.90), "weak"),
            ((0.80, 1.40, 0.90), "needle"),
            ((0.90, 1.20, 1.50), "boundary_trend"),
            ((1.30, 1.15, 1.35), "unstable"),
        )
        for (low, baseline, high), shape in cases:
            with self.subTest(shape=shape):
                plan = make_plan()
                assessment = assess_sensitivity(
                    plan,
                    evidence_for(
                        plan,
                        {
                            ("baseline", None): baseline,
                            ("extreme_low", "model.alpha"): low,
                            ("extreme_high", "model.alpha"): high,
                        },
                    ),
                    RULE,
                )
                finalized = finalize_sensitivity_choice(plan, assessment, RULE)

                self.assertEqual(
                    finalized.selected_variant_id,
                    plan.variant("baseline").variant_id,
                )
                self.assertEqual(
                    finalized.selection_basis,
                    "baseline_fallback_bad_surface",
                )
                self.assertTrue(finalized.promotion_blocked)
                self.assertIn(
                    f"model.alpha:{shape}",
                    finalized.promotion_block_reasons,
                )

    def test_validated_midpoint_is_frozen_without_outer_development_metrics(self) -> None:
        plan = make_plan()
        assessment = assess_sensitivity(
            plan,
            evidence_for(
                plan,
                {
                    ("baseline", None): 1.05,
                    ("extreme_low", "model.alpha"): 0.80,
                    ("extreme_high", "model.alpha"): 1.12,
                },
            ),
            RULE,
        )
        proposal = propose_local_midpoint(plan, assessment)
        midpoint = VariantEvidence.from_mapping(
            proposal.variant.variant_id,
            1.11,
            {"V2D001": 1.10, "V2D002": 1.12},
            feasible_folds({"V2D001": 1.10, "V2D002": 1.12}),
        )
        first = finalize_sensitivity_choice(
            plan,
            assessment,
            RULE,
            proposal=proposal,
            midpoint_evidence=midpoint,
        )
        second = finalize_sensitivity_choice(
            plan,
            assessment,
            RULE,
            proposal=proposal,
            midpoint_evidence=midpoint,
        )

        self.assertEqual(first.finalization_id, second.finalization_id)
        self.assertEqual(first.finalization_sha256, second.finalization_sha256)
        self.assertEqual(first.selected_variant_id, proposal.variant.variant_id)
        self.assertEqual(first.selected_variant_sha256, proposal.variant.variant_sha256)
        self.assertEqual(first.selected_parameters_sha256, proposal.variant.parameters_sha256)
        self.assertIsNotNone(first.midpoint_evidence_sha256)
        self.assertEqual(first.selection_basis, "midpoint_frozen_after_validation_oos")
        self.assertFalse(first.promotion_blocked)
        self.assertFalse(first.development_metrics_inspected)
        self.assertEqual(first.trial_counts.distinct_variant_count, 4)
        self.assertEqual(first.trial_counts.fold_evaluation_count, 8)
        self.assertEqual(first.trial_counts.selection_count, 2)

    def test_failed_midpoint_validation_freezes_baseline_and_blocks_promotion(self) -> None:
        plan = make_plan()
        assessment = assess_sensitivity(
            plan,
            evidence_for(
                plan,
                {
                    ("baseline", None): 1.05,
                    ("extreme_low", "model.alpha"): 0.80,
                    ("extreme_high", "model.alpha"): 1.12,
                },
            ),
            RULE,
        )
        proposal = propose_local_midpoint(plan, assessment)
        midpoint = VariantEvidence.from_mapping(
            proposal.variant.variant_id,
            0.90,
            {"V2D001": 0.85, "V2D002": 0.95},
            feasible_folds({"V2D001": 0.85, "V2D002": 0.95}),
        )
        finalized = finalize_sensitivity_choice(
            plan,
            assessment,
            RULE,
            proposal=proposal,
            midpoint_evidence=midpoint,
        )

        self.assertEqual(finalized.selected_variant_id, plan.variant("baseline").variant_id)
        self.assertEqual(
            finalized.selection_basis,
            "baseline_fallback_midpoint_validation_failed",
        )
        self.assertTrue(finalized.promotion_blocked)
        self.assertIn("midpoint_validation_failed", finalized.promotion_block_reasons)

    def test_infeasible_initial_evidence_blocks_calibration_and_promotion(self) -> None:
        plan = make_plan()
        evidence = list(
            evidence_for(
                plan,
                {
                    ("baseline", None): 1.05,
                    ("extreme_low", "model.alpha"): 0.80,
                    ("extreme_high", "model.alpha"): 1.12,
                },
            )
        )
        fold_values = {"V2D001": 1.12, "V2D002": 1.12}
        feasibility = feasible_folds(fold_values)
        feasibility["V2D002"] = {
            "feasible": False,
            "causal_checks_passed": True,
            "unknown_cost_observation_count": 1,
            "evaluable_trade_count": 10,
            "reason_codes": ["unknown_cost_observation_count"],
        }
        evidence[-1] = VariantEvidence.from_mapping(
            evidence[-1].variant_id,
            1.12,
            fold_values,
            feasibility,
        )
        assessment = assess_sensitivity(plan, tuple(evidence), RULE)

        with self.assertRaisesRegex(SensitivityError, "feasibility"):
            propose_local_midpoint(plan, assessment)
        finalized = finalize_sensitivity_choice(plan, assessment, RULE)
        self.assertTrue(finalized.promotion_blocked)
        self.assertEqual(
            finalized.selection_basis,
            "baseline_fallback_selection_feasibility_failed",
        )

    def test_infeasible_midpoint_falls_back_and_blocks_promotion(self) -> None:
        plan = make_plan()
        assessment = assess_sensitivity(
            plan,
            evidence_for(
                plan,
                {
                    ("baseline", None): 1.05,
                    ("extreme_low", "model.alpha"): 0.80,
                    ("extreme_high", "model.alpha"): 1.12,
                },
            ),
            RULE,
        )
        proposal = propose_local_midpoint(plan, assessment)
        fold_values = {"V2D001": 1.11, "V2D002": 1.12}
        feasibility = feasible_folds(fold_values)
        feasibility["V2D002"] = {
            "feasible": False,
            "causal_checks_passed": False,
            "unknown_cost_observation_count": 0,
            "evaluable_trade_count": 10,
            "reason_codes": ["causal_checks_required"],
        }
        midpoint = VariantEvidence.from_mapping(
            proposal.variant.variant_id,
            1.115,
            fold_values,
            feasibility,
        )

        finalized = finalize_sensitivity_choice(
            plan,
            assessment,
            RULE,
            proposal=proposal,
            midpoint_evidence=midpoint,
        )

        self.assertEqual(finalized.selected_variant_id, plan.variant("baseline").variant_id)
        self.assertTrue(finalized.promotion_blocked)
        self.assertIn(
            "midpoint_selection_feasibility_failed",
            finalized.promotion_block_reasons,
        )


if __name__ == "__main__":
    unittest.main()
