from __future__ import annotations

import unittest

from axiom_rift.research.adjudication import (
    AdjudicationProfile,
    CriterionAdjudication,
    MultiplicityAssessment,
    adjudicate_plan_measurement,
    bonferroni_concurrent_family,
    scientific_adjudication_manifest,
)
from axiom_rift.research.scientific_study import (
    PLANNED_CLAIMS,
    adjudicate_discovery,
    discovery_criteria,
    planned_verdict,
)


CONTROL_DELTA = "primary_control_delta_net_profit_micropoints"
CONTROL_PVALUE = "primary_control_pvalue_upper_ppm"


def _criteria() -> tuple[dict[str, object], ...]:
    return discovery_criteria(
        control_delta_metric=CONTROL_DELTA,
        control_pvalue_metric=CONTROL_PVALUE,
        include_opposite_sign=False,
    )


def _plan(
    *,
    evidence_depth: str = "discovery",
    candidate_eligible_on_pass: bool = False,
) -> dict[str, object]:
    return {
        "candidate_eligible_on_pass": candidate_eligible_on_pass,
        "criteria": list(_criteria()),
        "evidence_depth": evidence_depth,
        "planned_claims": list(PLANNED_CLAIMS),
    }


def _frontier_metrics() -> dict[str, dict[str, int | None]]:
    return {
        "activity_and_concentration": {
            "entries_per_day_milli": 5_143,
            "top5_profit_day_share_ppm": 136_720,
            "trade_count": 2_983,
        },
        "after_cost_fixed_lot_economics": {
            "median_fold_profit_factor_milli": 1_194,
            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": 808_232,
            "net_profit_micropoints": 9_738_130_000,
            "stress_net_profit_micropoints": 6_546_545_000,
        },
        "causal_feature_and_execution_validity": {
            "append_invariance_mismatch_count": 0,
            "causality_violation_count": 0,
            "nonfinite_metric_count": 0,
            "prefix_invariance_mismatch_count": 0,
            "unknown_cost_unresolved_signal_count": 0,
        },
        "registered_control_contrast": {
            CONTROL_DELTA: 2_663_240_000,
            CONTROL_PVALUE: 1_000_000,
        },
        "selection_aware_signal_evidence": {
            "selection_aware_pvalue_ppm": 1_000_000,
        },
        "temporal_and_regime_stability": {
            "evaluable_folds": 9,
            "supported_positive_regime_count": 2,
            "winning_fold_count": 6,
        },
    }


def _measurement(
    metrics: dict[str, dict[str, int | None]] | None = None,
) -> dict[str, object]:
    return {"metrics": _frontier_metrics() if metrics is None else metrics}


def _passing_profile() -> AdjudicationProfile:
    return AdjudicationProfile(
        multiplicity=(
            bonferroni_concurrent_family(
                criterion_id="D04-primary-control-uncertainty",
                family_id="family:registered-control",
                family_size=4,
                raw_pvalue_ppm=10_000,
                alpha_ppm=100_000,
            ),
            bonferroni_concurrent_family(
                criterion_id="E01-familywise-selection",
                family_id="family:concurrent-portfolio",
                family_size=4,
                raw_pvalue_ppm=10_000,
                alpha_ppm=100_000,
            ),
        )
    )


class ScientificAdjudicationTests(unittest.TestCase):
    def test_concurrent_family_is_invariant_to_unrelated_history(self) -> None:
        subject_before = bonferroni_concurrent_family(
            criterion_id="E01-familywise-selection",
            family_id="family:subject",
            family_size=3,
            raw_pvalue_ppm=20_000,
            alpha_ppm=100_000,
        )
        unrelated = bonferroni_concurrent_family(
            criterion_id="D04-primary-control-uncertainty",
            family_id="family:unrelated",
            family_size=999,
            raw_pvalue_ppm=20_000,
            alpha_ppm=100_000,
        )
        subject_after = bonferroni_concurrent_family(
            criterion_id="E01-familywise-selection",
            family_id="family:subject",
            family_size=3,
            raw_pvalue_ppm=20_000,
            alpha_ppm=100_000,
        )

        self.assertEqual(subject_before, subject_after)
        self.assertEqual(subject_after.adjusted_pvalue_ppm, 60_000)
        self.assertTrue(subject_after.passed)
        self.assertEqual(unrelated.adjusted_pvalue_ppm, 1_000_000)

    def test_multiplicity_manifest_is_explicit_and_validated(self) -> None:
        assessment = MultiplicityAssessment(
            adjusted_pvalue_ppm=80_000,
            alpha_ppm=100_000,
            criterion_id="E01-familywise-selection",
            family_id="family:four-concurrent-hypotheses",
            family_size=4,
            method="max_t_concurrent_family.v1",
            raw_pvalue_ppm=25_000,
        )

        self.assertEqual(
            set(assessment.manifest()),
            {
                "adjusted_pvalue_ppm",
                "alpha_ppm",
                "criterion_id",
                "family_id",
                "family_size",
                "method",
                "raw_pvalue_ppm",
            },
        )
        with self.assertRaises(ValueError):
            MultiplicityAssessment(
                adjusted_pvalue_ppm=10_000,
                alpha_ppm=100_000,
                criterion_id="E01-familywise-selection",
                family_id="family:invalid",
                family_size=4,
                method="invalid.v1",
                raw_pvalue_ppm=20_000,
            )

    def test_stu0092_like_discovery_is_frontier_with_drawdown_diagnostic(self) -> None:
        adjudication = adjudicate_discovery(
            _plan(), _measurement(), profile=_passing_profile()
        )

        self.assertEqual(adjudication.state, "frontier")
        self.assertTrue(adjudication.evaluable)
        self.assertFalse(adjudication.candidate_eligible)
        self.assertEqual(len(adjudication.risk_diagnostics), 1)
        self.assertEqual(adjudication.risk_diagnostics[0].state, "failed")
        self.assertEqual(
            adjudication.risk_diagnostics[0].comparison_state, "failed"
        )
        self.assertEqual(
            adjudication.risk_diagnostics[0].scientific_state, "diagnostic"
        )
        self.assertEqual(
            adjudication.risk_diagnostics[0].criterion_id,
            "B04-monthly-realized-drawdown-share",
        )
        self.assertEqual(adjudication.legacy_verdict, "failed")
        self.assertEqual(planned_verdict(_plan(), _measurement()), "failed")

    def test_drawdown_is_decisive_only_when_profile_applies_it(self) -> None:
        profile = AdjudicationProfile(
            decisive_risk_criterion_ids=frozenset(
                {"B04-monthly-realized-drawdown-share"}
            ),
            multiplicity=_passing_profile().multiplicity,
        )

        adjudication = adjudicate_discovery(
            _plan(), _measurement(), profile=profile
        )

        self.assertEqual(adjudication.state, "partial_positive")
        self.assertEqual(adjudication.risk_diagnostics, ())
        economics = next(
            item
            for item in adjudication.claims
            if item.claim_id == "after_cost_fixed_lot_economics"
        )
        self.assertEqual(economics.state, "contradicted")

    def test_validity_failures_are_not_evaluable(self) -> None:
        for metric in (
            "causality_violation_count",
            "nonfinite_metric_count",
            "unknown_cost_unresolved_signal_count",
        ):
            with self.subTest(metric=metric):
                metrics = _frontier_metrics()
                metrics["causal_feature_and_execution_validity"][metric] = 1

                adjudication = adjudicate_discovery(
                    _plan(), _measurement(metrics), profile=_passing_profile()
                )

                self.assertEqual(adjudication.state, "not_evaluable")
                self.assertFalse(adjudication.evaluable)
                self.assertIn(metric, adjudication.invalid_metrics)
                self.assertFalse(adjudication.candidate_eligible)
                criterion = next(
                    item for item in adjudication.criteria if item.metric == metric
                )
                self.assertEqual(criterion.state, "failed")
                self.assertEqual(criterion.comparison_state, "failed")
                self.assertEqual(criterion.scientific_state, "invalid")

    def test_missing_or_null_validity_is_not_evaluable(self) -> None:
        for missing in (False, True):
            with self.subTest(missing=missing):
                metrics = _frontier_metrics()
                validity = metrics["causal_feature_and_execution_validity"]
                if missing:
                    del validity["causality_violation_count"]
                else:
                    validity["causality_violation_count"] = None

                adjudication = adjudicate_discovery(
                    _plan(), _measurement(metrics), profile=_passing_profile()
                )

                self.assertEqual(adjudication.state, "not_evaluable")
                self.assertFalse(adjudication.evaluable)
                self.assertIn(
                    "causality_violation_count", adjudication.invalid_metrics
                )
                criterion = next(
                    item
                    for item in adjudication.criteria
                    if item.metric == "causality_violation_count"
                )
                self.assertEqual(criterion.state, "unavailable")
                self.assertEqual(criterion.comparison_state, "unavailable")
                self.assertEqual(criterion.scientific_state, "invalid")

    def test_stu0061_like_zero_trade_surface_is_exactly_contradicted(self) -> None:
        metrics = _frontier_metrics()
        metrics["activity_and_concentration"].update(
            entries_per_day_milli=0,
            trade_count=0,
        )
        metrics["after_cost_fixed_lot_economics"].update(
            median_fold_profit_factor_milli=0,
            net_profit_micropoints=0,
            stress_net_profit_micropoints=0,
        )
        metrics["registered_control_contrast"][CONTROL_DELTA] = 0
        metrics["temporal_and_regime_stability"].update(
            evaluable_folds=0,
            supported_positive_regime_count=0,
            winning_fold_count=0,
        )
        failing_profile = AdjudicationProfile(
            multiplicity=(
                bonferroni_concurrent_family(
                    criterion_id="D04-primary-control-uncertainty",
                    family_id="family:control",
                    family_size=2,
                    raw_pvalue_ppm=100_000,
                    alpha_ppm=100_000,
                ),
                bonferroni_concurrent_family(
                    criterion_id="E01-familywise-selection",
                    family_id="family:selection",
                    family_size=2,
                    raw_pvalue_ppm=100_000,
                    alpha_ppm=100_000,
                ),
            )
        )

        adjudication = adjudicate_discovery(
            _plan(), _measurement(metrics), profile=failing_profile
        )

        self.assertEqual(adjudication.state, "contradicted")
        self.assertNotEqual(adjudication.state, "partial_positive")

    def test_supported_components_and_failed_family_are_partial_positive(self) -> None:
        profile = AdjudicationProfile(
            multiplicity=(
                *_passing_profile().multiplicity[:1],
                bonferroni_concurrent_family(
                    criterion_id="E01-familywise-selection",
                    family_id="family:selection",
                    family_size=4,
                    raw_pvalue_ppm=40_000,
                    alpha_ppm=100_000,
                ),
            )
        )

        adjudication = adjudicate_discovery(
            _plan(), _measurement(), profile=profile
        )

        self.assertEqual(adjudication.state, "partial_positive")
        self.assertTrue(
            any(item.state == "supported" for item in adjudication.claims)
        )
        self.assertTrue(
            any(item.state == "contradicted" for item in adjudication.claims)
        )

    def test_missing_concurrent_family_is_unresolved_not_legacy_adjusted(self) -> None:
        metrics = _frontier_metrics()
        metrics["activity_and_concentration"].update(
            entries_per_day_milli=0,
            trade_count=0,
        )
        metrics["after_cost_fixed_lot_economics"].update(
            median_fold_profit_factor_milli=0,
            net_profit_micropoints=0,
            stress_net_profit_micropoints=-1,
        )
        metrics["registered_control_contrast"][CONTROL_DELTA] = 0
        metrics["temporal_and_regime_stability"].update(
            evaluable_folds=0,
            supported_positive_regime_count=0,
            winning_fold_count=0,
        )

        adjudication = adjudicate_plan_measurement(
            _plan(), _measurement(metrics)
        )

        self.assertEqual(adjudication.state, "unresolved")
        self.assertTrue(adjudication.evaluable)
        selection = next(
            item
            for item in adjudication.criteria
            if item.criterion_id == "E01-familywise-selection"
        )
        self.assertIsNone(selection.value)
        self.assertEqual(selection.state, "unavailable")
        self.assertEqual(selection.comparison_state, "unavailable")
        self.assertEqual(selection.scientific_state, "unresolved")

    def test_diagnostic_semantics_do_not_change_with_comparison_result(self) -> None:
        for value, expected_comparison in (
            (400_000, "passed"),
            (808_232, "failed"),
            (None, "unavailable"),
        ):
            with self.subTest(value=value):
                metrics = _frontier_metrics()
                metrics["after_cost_fixed_lot_economics"][
                    "monthly_realized_exit_drawdown_share_of_gross_profit_ppm"
                ] = value

                adjudication = adjudicate_discovery(
                    _plan(), _measurement(metrics), profile=_passing_profile()
                )
                diagnostic = adjudication.risk_diagnostics[0]

                self.assertEqual(diagnostic.state, expected_comparison)
                self.assertEqual(
                    diagnostic.comparison_state, expected_comparison
                )
                self.assertEqual(diagnostic.scientific_state, "diagnostic")
                self.assertEqual(adjudication.state, "frontier")

    def test_missing_registered_risk_gate_is_unresolved_not_diagnostic(self) -> None:
        metrics = _frontier_metrics()
        del metrics["after_cost_fixed_lot_economics"][
            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm"
        ]
        profile = AdjudicationProfile(
            decisive_risk_criterion_ids=frozenset(
                {"B04-monthly-realized-drawdown-share"}
            ),
            multiplicity=_passing_profile().multiplicity,
        )

        adjudication = adjudicate_discovery(
            _plan(), _measurement(metrics), profile=profile
        )
        risk_gate = next(
            item
            for item in adjudication.criteria
            if item.criterion_id == "B04-monthly-realized-drawdown-share"
        )
        economics = next(
            item
            for item in adjudication.claims
            if item.claim_id == "after_cost_fixed_lot_economics"
        )

        self.assertEqual(risk_gate.decision_role, "risk_gate")
        self.assertEqual(risk_gate.state, "unavailable")
        self.assertEqual(risk_gate.comparison_state, "unavailable")
        self.assertEqual(risk_gate.scientific_state, "unresolved")
        self.assertEqual(economics.state, "unresolved")
        self.assertEqual(adjudication.state, "partial_positive")

    def test_manifest_keeps_legacy_state_and_adds_explicit_states(self) -> None:
        adjudication = adjudicate_discovery(
            _plan(), _measurement(), profile=_passing_profile()
        )

        manifest = scientific_adjudication_manifest(adjudication)
        diagnostic = next(
            item
            for item in manifest["criteria"]
            if item["criterion_id"] == "B04-monthly-realized-drawdown-share"
        )

        self.assertEqual(manifest["schema"], "scientific_adjudication.v1")
        self.assertEqual(diagnostic["state"], "failed")
        self.assertEqual(diagnostic["comparison_state"], "failed")
        self.assertEqual(diagnostic["scientific_state"], "diagnostic")

    def test_legacy_state_constructor_cannot_forge_semantic_state(self) -> None:
        diagnostic = CriterionAdjudication(
            claim_id="claim:risk",
            criterion_id="criterion:risk-diagnostic",
            decision_role="risk_diagnostic",
            metric="drawdown_share_ppm",
            operator="le",
            state="failed",
            threshold=500_000,
            value=800_000,
        )

        self.assertEqual(diagnostic.state, "failed")
        self.assertEqual(diagnostic.comparison_state, "failed")
        self.assertEqual(diagnostic.scientific_state, "diagnostic")
        with self.assertRaises(ValueError):
            CriterionAdjudication(
                claim_id="claim:invalid",
                criterion_id="criterion:invalid",
                decision_role="component",
                metric="metric",
                operator="eq",
                state="contradicted",  # type: ignore[arg-type]
                threshold=0,
                value=1,
            )

    def test_candidate_authority_requires_passing_confirmation(self) -> None:
        discovery_plan = _plan(candidate_eligible_on_pass=True)
        discovery = adjudicate_discovery(
            discovery_plan, _measurement(), profile=_passing_profile()
        )
        confirmation = adjudicate_discovery(
            _plan(
                evidence_depth="confirmation",
                candidate_eligible_on_pass=True,
            ),
            _measurement(),
            profile=_passing_profile(),
        )

        self.assertEqual(discovery.state, "frontier")
        self.assertFalse(discovery.candidate_eligible)
        self.assertEqual(confirmation.state, "confirmed")
        self.assertTrue(confirmation.candidate_eligible)


if __name__ == "__main__":
    unittest.main()
