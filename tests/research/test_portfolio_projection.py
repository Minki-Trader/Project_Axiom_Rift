from __future__ import annotations

import unittest

from axiom_rift.research.chassis import ArchitectureChassisSpec
from axiom_rift.research.axis_protocol_revision import (
    AxisProtocolRevisionProposal,
    AxisProtocolRevisionReason,
)
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
    PortfolioDecisionError,
    QuantTeamDecisionReview,
)
from axiom_rift.research.portfolio_projection import (
    PortfolioProjectionError,
    architecture_chassis_from_identity_payload,
    component_surface_registry,
    portfolio_axis_from_projection,
    portfolio_decision_from_projection,
)
from axiom_rift.research.selection_inference import HistoricalSearchContext
from axiom_rift.research.semantic_question import (
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)


class PortfolioProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = build_p0_composite_validation_plan(
            mission_id="MIS-PORTFOLIO-PROJECTION",
            historical_context=HistoricalSearchContext(
                context_id="history:portfolio-projection-test",
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
        cls.axis = PortfolioAxis(
            axis_id="axis-p0-composite-audit-reanalysis",
            causal_question=(
                "Does an exact composite replay preserve the six selected legacy "
                "surfaces without granting post-selection candidate authority?"
            ),
            mechanism_family="historical_post_selection_composite_audit",
            primary_research_layer=ResearchLayer.SYNTHESIS,
            system_architecture_family=cls.architecture.identity,
            changed_domains=(ResearchLayer.SYNTHESIS,),
            controlled_domains=cls.plan.controlled_chassis().controlled_domains,
            why_now="The exhaustive audit found erased claim structure.",
            stop_or_reopen_condition=(
                "Stop after one exact six-member composite replay and reopen only "
                "with a changed immutable legacy artifact."
            ),
            architecture_chassis=cls.architecture,
        )

    def test_component_and_architecture_payloads_round_trip_exactly(self) -> None:
        rebuilt = architecture_chassis_from_identity_payload(
            self.architecture.to_identity_payload(),
            self.registry,
        )
        self.assertEqual(rebuilt.identity, self.architecture.identity)
        self.assertEqual(
            rebuilt.to_identity_payload(), self.architecture.to_identity_payload()
        )

    def test_portfolio_axis_projection_round_trips_exact_identity(self) -> None:
        payload = {
            "architecture_chassis": self.architecture.to_identity_payload(),
            "architecture_chassis_identity": self.architecture.identity,
            "axis_id": self.axis.axis_id,
            "axis_identity": self.axis.identity,
            "causal_question": self.axis.causal_question,
            "changed_domains": [value.value for value in self.axis.changed_domains],
            "controlled_domains": [
                value.value for value in self.axis.controlled_domains
            ],
            "mechanism_family": self.axis.mechanism_family,
            "primary_research_layer": self.axis.primary_research_layer.value,
            "status": self.axis.status,
            "stop_or_reopen_condition": self.axis.stop_or_reopen_condition,
            "system_architecture_family": self.axis.system_architecture_family,
            "why_now": self.axis.why_now,
        }
        rebuilt = portfolio_axis_from_projection(payload, self.registry)
        self.assertEqual(rebuilt.identity, self.axis.identity)
        self.assertEqual(
            rebuilt.architecture_chassis.to_identity_payload(),
            self.architecture.to_identity_payload(),
        )

    def test_missing_semantic_surface_fails_closed(self) -> None:
        incomplete = dict(self.registry)
        used_surface = next(
            surface
            for role in self.architecture.to_identity_payload()["roles"].values()
            for surface in role["component_semantic_surfaces"]
        )
        incomplete.pop(used_surface)
        with self.assertRaisesRegex(
            PortfolioProjectionError,
            "surface is absent",
        ):
            architecture_chassis_from_identity_payload(
                self.architecture.to_identity_payload(),
                incomplete,
            )

    def test_empty_replay_binding_preserves_legacy_decision_identity(self) -> None:
        options = (
            DecisionOption(
                option_id="deepen-replay",
                action=PortfolioAction.DEEPEN,
                target_id=self.axis.axis_id,
                expected_information_value="positive",
                opportunity_cost="one bounded Batch",
            ),
            DecisionOption(
                option_id="new-mechanism",
                action=PortfolioAction.NEW_MECHANISM,
                target_id="axis-independent-control",
                expected_information_value="independent",
                opportunity_cost="one alternative Batch",
                omission_reason="the bounded replay is selected first",
            ),
        )
        legacy = PortfolioDecision(
            decision_id="DEC-LEGACY-IDENTITY",
            chosen_option_id="deepen-replay",
            options=options,
            rationale="preserve the exact historical Decision byte surface",
            commitment_batches=1,
            baseline_executable=self.plan.baseline_executable,
        )
        explicit_empty = PortfolioDecision(
            decision_id="DEC-LEGACY-IDENTITY",
            chosen_option_id="deepen-replay",
            options=options,
            rationale="preserve the exact historical Decision byte surface",
            commitment_batches=1,
            baseline_executable=self.plan.baseline_executable,
            replay_obligation_ids=(),
        )
        self.assertEqual(explicit_empty.identity, legacy.identity)
        self.assertEqual(
            explicit_empty.to_identity_payload(), legacy.to_identity_payload()
        )
        self.assertNotIn("replay_obligation_ids", legacy.to_identity_payload())
        rebuilt = portfolio_decision_from_projection(legacy.to_identity_payload())
        self.assertEqual(rebuilt.identity, legacy.identity)
        self.assertEqual(rebuilt.to_identity_payload(), legacy.to_identity_payload())
        finite_multi_batch = legacy.to_identity_payload()
        finite_multi_batch["commitment_batches"] = 2
        rebuilt_multi_batch = portfolio_decision_from_projection(
            finite_multi_batch
        )
        self.assertEqual(rebuilt_multi_batch.commitment_batches, 2)
        self.assertNotEqual(rebuilt_multi_batch.identity, legacy.identity)

        bound = PortfolioDecision(
            decision_id="DEC-LEGACY-IDENTITY",
            chosen_option_id="deepen-replay",
            options=options,
            rationale="preserve the exact historical Decision byte surface",
            commitment_batches=1,
            baseline_executable=self.plan.baseline_executable,
            replay_obligation_ids=(
                "historical-replay-obligation:" + "2" * 64,
                "historical-replay-obligation:" + "1" * 64,
            ),
        )
        self.assertNotEqual(bound.identity, legacy.identity)
        self.assertEqual(
            bound.to_identity_payload()["replay_obligation_ids"],
            [
                "historical-replay-obligation:" + "1" * 64,
                "historical-replay-obligation:" + "2" * 64,
            ],
        )
        self.assertEqual(
            portfolio_decision_from_projection(bound.to_identity_payload()).identity,
            bound.identity,
        )

    def test_plural_quant_team_review_round_trips_without_scalar_scoring(self) -> None:
        snapshot_basis = DecisionBasisRecord(
            kind="portfolio-snapshot",
            record_id="portfolio:" + "a" * 64,
        )
        options = (
            DecisionOption(
                option_id="deepen-replay",
                action=PortfolioAction.DEEPEN,
                target_id=self.axis.axis_id,
                expected_information_value="resolve one exact causal uncertainty",
                opportunity_cost="one bounded Batch",
            ),
            DecisionOption(
                option_id="rotate-control",
                action=PortfolioAction.ROTATE,
                target_id=self.axis.axis_id,
                expected_information_value="test an independent architecture",
                opportunity_cost="leave the replay pending",
                omission_reason="the exact replay is currently executable",
            ),
        )
        review = QuantTeamDecisionReview(
            assessments=(
                DecisionLensAssessment(
                    lens=DecisionLens.CAUSALITY,
                    position=DecisionLensPosition.SUPPORT,
                    option_ids=("deepen-replay", "rotate-control"),
                    basis_records=(snapshot_basis,),
                    finding="the replay isolates the currently unresolved cause",
                ),
                DecisionLensAssessment(
                    lens=DecisionLens.RISK,
                    position=DecisionLensPosition.UNCERTAIN,
                    option_ids=("deepen-replay",),
                    basis_records=(snapshot_basis,),
                    finding="one Batch delays an independent risk architecture",
                ),
            ),
            claim_boundary="allocation only; no scientific or candidate claim",
            resolution_basis=(
                "resolve the exact bounded uncertainty before paying rotation cost"
            ),
            disagreement_resolution=(
                "retain the risk rotation as an independently selectable option"
            ),
        )
        decision = PortfolioDecision(
            decision_id="DEC-QUANT-TEAM-REVIEW",
            chosen_option_id="deepen-replay",
            options=options,
            rationale="make one evidence-bound non-scalar allocation",
            commitment_batches=1,
            quant_team_review=review,
            baseline_executable=self.plan.baseline_executable,
        )
        payload = decision.to_identity_payload()
        self.assertEqual(payload["schema"], "portfolio_decision.v3")
        self.assertNotIn("score", payload["quant_team_review"])
        rebuilt = portfolio_decision_from_projection(payload)
        self.assertEqual(rebuilt.identity, decision.identity)
        self.assertEqual(rebuilt.to_identity_payload(), payload)

        with self.assertRaisesRegex(
            PortfolioDecisionError,
            "at least two material lenses",
        ):
            QuantTeamDecisionReview(
                assessments=(review.assessments[0],),
                claim_boundary="allocation only",
                resolution_basis="one opinion is not a team review",
            )

    def test_protocol_revision_decision_round_trips_typed_authority(self) -> None:
        obligation_id = "historical-replay-obligation:" + "1" * 64
        lineage = SemanticQuestionLineageProposal(
            predecessor_study_id="STU-PROJECTION-PREDECESSOR",
            successor_study_id="STU-PROJECTION-SUCCESSOR",
            predecessor_core_id="semantic-question-core:" + "2" * 64,
            successor_core_id="semantic-question-core:" + "2" * 64,
            relation=SemanticQuestionRelation.CONTINUATION,
            rationale="retain the exact question under one corrected protocol",
            basis_record_ids=("study-open:STU-PROJECTION-PREDECESSOR",),
        )
        revision = AxisProtocolRevisionProposal(
            mission_id="MIS-PORTFOLIO-PROJECTION",
            axis_id=self.axis.axis_id,
            predecessor_axis_identity=self.axis.identity,
            successor_axis_identity="axis:" + "3" * 64,
            mechanism_family=self.axis.mechanism_family,
            predecessor_architecture_family=self.architecture.identity,
            successor_architecture_family="architecture-family:" + "4" * 64,
            replay_obligation_id=obligation_id,
            satisfaction_invalidation_record_id=(
                "historical-replay-satisfaction-invalidation:" + "5" * 64
            ),
            semantic_question_lineage=lineage,
            reason_code=(
                AxisProtocolRevisionReason.COMPLETION_VALIDITY_INVALIDATED
            ),
            reason="the accepted completion protocol is invalidated",
        )
        decision = PortfolioDecision(
            decision_id="DEC-PROTOCOL-REVISION-PROJECTION",
            chosen_option_id="revise-protocol",
            options=(
                DecisionOption(
                    option_id="revise-protocol",
                    action=PortfolioAction.REVISE_PROTOCOL,
                    target_id=self.axis.axis_id,
                    expected_information_value="recover exact causal evidence",
                    opportunity_cost="one structural snapshot",
                ),
                DecisionOption(
                    option_id="new-mechanism",
                    action=PortfolioAction.NEW_MECHANISM,
                    target_id=self.axis.axis_id,
                    expected_information_value="independent search value",
                    opportunity_cost="leave the invalidated protocol unresolved",
                    omission_reason="the exact correction is currently bounded",
                ),
            ),
            rationale="revise one protocol without manufacturing a mechanism",
            commitment_batches=1,
            replay_obligation_ids=(obligation_id,),
            protocol_revision=revision,
        )
        payload = decision.to_identity_payload()
        self.assertEqual(payload["schema"], "portfolio_decision.v4")
        rebuilt = portfolio_decision_from_projection(payload)
        self.assertEqual(rebuilt.identity, decision.identity)
        self.assertEqual(rebuilt.protocol_revision, revision)
        self.assertEqual(rebuilt.to_identity_payload(), payload)


if __name__ == "__main__":
    unittest.main()
