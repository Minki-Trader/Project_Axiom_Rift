from __future__ import annotations

import unittest

from axiom_rift.research.chassis import ArchitectureChassisSpec
from axiom_rift.research.forest_replay import build_p0_composite_validation_plan
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.portfolio import (
    DecisionBasisRecord,
    DecisionLens,
    DecisionLensAssessment,
    DecisionLensPosition,
    DecisionOption,
    PortfolioAction,
    PortfolioAxis,
    PortfolioDecision,
    QuantTeamDecisionReview,
)
from axiom_rift.research.portfolio_projection import (
    PortfolioProjectionError,
    component_surface_registry,
    portfolio_decision_from_projection,
)
from axiom_rift.research.selection_inference import HistoricalSearchContext


class StructuralPortfolioProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = build_p0_composite_validation_plan(
            mission_id="MIS-PORTFOLIO-STRUCTURAL-PROJECTION",
            historical_context=HistoricalSearchContext(
                context_id="history:portfolio-structural-projection-test",
                prior_global_exposure_count=470,
            ),
            bootstrap_samples=199,
            block_lengths=(2, 5),
            base_seed=991,
        )
        cls.registry = component_surface_registry(
            (
                cls.plan.baseline_executable.to_identity_payload(),
                cls.plan.executable.to_identity_payload(),
            )
        )
        cls.architecture = ArchitectureChassisSpec.from_executable(
            cls.plan.baseline_executable
        )
        cls.source_axis = PortfolioAxis(
            axis_id="axis-p0-structural-projection-source",
            causal_question="Does the source architecture remain available?",
            mechanism_family="structural_projection_source",
            primary_research_layer=ResearchLayer.SYNTHESIS,
            system_architecture_family=cls.architecture.identity,
            changed_domains=(ResearchLayer.SYNTHESIS,),
            controlled_domains=cls.plan.controlled_chassis().controlled_domains,
            why_now="The reader must preserve exact forest optionality.",
            stop_or_reopen_condition="Reopen only on changed evidence.",
            architecture_chassis=cls.architecture,
        )

    def test_structural_new_axis_decision_round_trips_exact_v5(self) -> None:
        proposed_axis = PortfolioAxis(
            axis_id="axis-independent-feature-projection",
            causal_question="Does an independent feature add information?",
            mechanism_family="independent_feature_projection",
            primary_research_layer=ResearchLayer.FEATURE,
            system_architecture_family=self.source_axis.system_architecture_family,
            changed_domains=(ResearchLayer.FEATURE,),
            controlled_domains=(ResearchLayer.MODEL,),
            why_now="Compare an independent option without erasing the source.",
            stop_or_reopen_condition="Stop after one bounded comparison.",
        )
        basis = DecisionBasisRecord(
            kind="portfolio-snapshot",
            record_id="portfolio:" + "b" * 64,
        )
        review = QuantTeamDecisionReview(
            assessments=(
                DecisionLensAssessment(
                    lens=DecisionLens.ARCHITECTURE,
                    position=DecisionLensPosition.SUPPORT,
                    option_ids=("new-feature", "preserve-source"),
                    basis_records=(basis,),
                    finding="the proposal is distinct without erasing the source axis",
                ),
                DecisionLensAssessment(
                    lens=DecisionLens.ECONOMICS,
                    position=DecisionLensPosition.UNCERTAIN,
                    option_ids=("new-feature",),
                    basis_records=(basis,),
                    finding="one bounded Batch has unresolved implementation cost",
                ),
            ),
            claim_boundary="allocation only; no scientific credit or candidate claim",
            resolution_basis="retain both options and bind the selected proposal",
            disagreement_resolution="bind one Batch and preserve the source axis",
        )
        decision = self._decision(proposed_axis, quant_team_review=review)
        payload = decision.to_identity_payload()

        self.assertEqual(payload["schema"], "portfolio_decision.v5")
        rebuilt = portfolio_decision_from_projection(payload)
        self.assertEqual(rebuilt.identity, decision.identity)
        self.assertEqual(rebuilt.proposed_axis, proposed_axis)
        self.assertEqual(rebuilt.to_identity_payload(), payload)

    def test_structural_axis_requires_exact_architecture_surface(self) -> None:
        proposed_axis = PortfolioAxis(
            axis_id="axis-independent-synthesis-projection",
            causal_question="Does an independent synthesis add complementary evidence?",
            mechanism_family="independent_synthesis_projection",
            primary_research_layer=ResearchLayer.SYNTHESIS,
            system_architecture_family=self.architecture.identity,
            changed_domains=(ResearchLayer.SYNTHESIS,),
            controlled_domains=self.plan.controlled_chassis().controlled_domains,
            why_now="The proposal must retain its exact architecture surface.",
            stop_or_reopen_condition="Stop after one exact comparison.",
            architecture_chassis=self.architecture,
        )
        decision = self._decision(proposed_axis)
        payload = decision.to_identity_payload()

        with self.assertRaises(PortfolioProjectionError):
            portfolio_decision_from_projection(payload)
        rebuilt = portfolio_decision_from_projection(
            payload,
            components_by_surface=self.registry,
        )
        self.assertEqual(rebuilt.identity, decision.identity)
        self.assertEqual(rebuilt.proposed_axis, proposed_axis)

        forged = dict(payload)
        forged["proposed_axis_identity"] = "axis:" + "f" * 64
        with self.assertRaises(PortfolioProjectionError):
            portfolio_decision_from_projection(
                forged,
                components_by_surface=self.registry,
            )

    def _decision(
        self,
        proposed_axis: PortfolioAxis,
        *,
        quant_team_review: QuantTeamDecisionReview | None = None,
    ) -> PortfolioDecision:
        return PortfolioDecision(
            decision_id="DEC-STRUCTURAL-PROJECTION-V5",
            chosen_option_id="new-mechanism",
            options=(
                DecisionOption(
                    option_id="new-mechanism",
                    action=PortfolioAction.NEW_MECHANISM,
                    target_id=self.source_axis.axis_id,
                    expected_information_value="independent structural evidence",
                    opportunity_cost="one bounded Batch",
                ),
                DecisionOption(
                    option_id="preserve-source",
                    action=PortfolioAction.PRESERVE,
                    target_id=self.source_axis.axis_id,
                    expected_information_value="retain exact reopen optionality",
                    opportunity_cost="defer the independent comparison",
                    omission_reason="the independent comparison is bounded now",
                ),
            ),
            rationale="bind the exact structural proposal without scalar scoring",
            commitment_batches=1,
            quant_team_review=quant_team_review,
            proposed_axis=proposed_axis,
        )


if __name__ == "__main__":
    unittest.main()
