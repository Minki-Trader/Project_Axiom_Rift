from __future__ import annotations

from pathlib import Path
import unittest

from axiom_rift.operations.architecture_review_direction import (
    ArchitectureReviewDirectionError,
    constraint_from_action,
    constraint_from_direction,
    direction_from_identity_payload,
    eligible_new_mechanism_axes,
    require_decision_direction,
    require_existing_axis_binding,
    require_review_binding,
    required_quant_team_basis,
)
from axiom_rift.research.governance import (
    ArchitectureContinuationDirection,
    ArchitectureContinuationMode,
    ArchitectureReview,
    ArchitectureReviewConclusion,
    ResearchGovernanceError,
    ResearchLayer,
)


D0 = "0" * 64
D1 = "1" * 64
D2 = "2" * 64
FAMILY = "architecture-family:" + D0
REVIEW_ID = "architecture-review:" + D1
AXIS_IDENTITY = "axis:" + D2
DIAGNOSES = ("diagnosis:" + D0, "diagnosis:" + D1)


def existing_direction() -> ArchitectureContinuationDirection:
    return ArchitectureContinuationDirection(
        mode=ArchitectureContinuationMode.EXISTING_AXIS,
        reviewed_architecture_family=FAMILY,
        trigger_record_id=D2,
        covered_diagnosis_ids=DIAGNOSES,
        target_axis_id="axis-covered",
        target_axis_identity=AXIS_IDENTITY,
    )


def new_direction() -> ArchitectureContinuationDirection:
    return ArchitectureContinuationDirection(
        mode=ArchitectureContinuationMode.NEW_MECHANISM,
        reviewed_architecture_family=FAMILY,
        trigger_record_id=D2,
        covered_diagnosis_ids=DIAGNOSES,
        required_research_layer=ResearchLayer.MODEL,
    )


def review_payload(
    direction: ArchitectureContinuationDirection,
) -> dict[str, object]:
    review = ArchitectureReview(
        mission_id="MIS-TEST",
        trigger_record_id=D2,
        system_architecture_family=FAMILY,
        conclusion=ArchitectureReviewConclusion.BOUNDED_SAME_ARCHITECTURE,
        rationale="bounded expert allocation preserves a testable forest branch",
        stop_or_reopen_condition="stop unless the exact bound yields information",
        continuation_direction=direction,
    )
    return {
        **review.to_identity_payload(),
        "covered_diagnosis_ids": list(DIAGNOSES),
    }


def trigger_payload() -> dict[str, object]:
    return {
        "schema": "architecture_review_trigger.v1",
        "diagnosis_ids": list(DIAGNOSES),
        "system_architecture_family": FAMILY,
    }


class ArchitectureReviewDirectionTests(unittest.TestCase):
    def test_required_research_direction_reference_covers_all_typed_routes(
        self,
    ) -> None:
        reference = (
            Path(__file__).resolve().parents[2]
            / ".agents"
            / "skills"
            / "run-research-portfolio"
            / "references"
            / "research-direction.md"
        ).read_text(encoding="ascii")
        for token in (
            "`bounded_same_architecture`",
            "`existing_axis`",
            "`new_mechanism`",
            "`change_research_layer`",
            "`rotate_architecture`",
        ):
            with self.subTest(token=token):
                self.assertIn(token, reference)

    def test_legacy_architecture_review_identity_is_unchanged(self) -> None:
        review = ArchitectureReview(
            mission_id="MIS-LEGACY",
            trigger_record_id=D1,
            system_architecture_family="architecture-family:" + D2,
            conclusion=ArchitectureReviewConclusion.ROTATE_ARCHITECTURE,
            rationale="legacy review rationale",
            stop_or_reopen_condition="legacy stop or reopen",
        )
        self.assertEqual(
            review.identity,
            "architecture-review:"
            "7c27ed44c3323e264b9f460331e679979e82a0bf32cb8a633480befdd165a148",
        )
        self.assertEqual(review.to_identity_payload()["schema"], "architecture_review.v1")
        with self.assertRaises(ResearchGovernanceError):
            ArchitectureReview(
                mission_id="MIS-LEGACY",
                trigger_record_id=D1,
                system_architecture_family="architecture-family:" + D2,
                conclusion=ArchitectureReviewConclusion.ROTATE_ARCHITECTURE,
                rationale="legacy review rationale",
                stop_or_reopen_condition="legacy stop or reopen",
                continuation_direction=existing_direction(),
            )

    def test_v2_direction_and_action_shapes_are_closed(self) -> None:
        direction = existing_direction()
        payload = direction.to_identity_payload()
        self.assertEqual(direction_from_identity_payload(payload), direction)
        malformed = {**payload, "free_form_override": "bypass"}
        with self.assertRaisesRegex(
            ArchitectureReviewDirectionError,
            "schema is not exact",
        ):
            direction_from_identity_payload(malformed)

        constraint = constraint_from_direction(
            architecture_review_id=REVIEW_ID,
            direction=direction,
        )
        action = constraint.to_action_fields()
        self.assertEqual(constraint_from_action(action), constraint)
        partial = dict(action)
        partial.pop("covered_diagnosis_ids")
        with self.assertRaisesRegex(
            ArchitectureReviewDirectionError,
            "incomplete",
        ):
            constraint_from_action(partial)

    def test_review_binding_recomputes_trigger_family_and_diagnoses(self) -> None:
        direction = new_direction()
        constraint = constraint_from_direction(
            architecture_review_id=REVIEW_ID,
            direction=direction,
        )
        self.assertEqual(
            require_review_binding(
                constraint,
                review_record_id=REVIEW_ID,
                review_payload=review_payload(direction),
                trigger_payload=trigger_payload(),
            ),
            direction,
        )
        tampered = trigger_payload()
        tampered["diagnosis_ids"] = [DIAGNOSES[0]]
        with self.assertRaisesRegex(
            ArchitectureReviewDirectionError,
            "exact trigger",
        ):
            require_review_binding(
                constraint,
                review_record_id=REVIEW_ID,
                review_payload=review_payload(direction),
                trigger_payload=tampered,
            )

    def test_existing_axis_is_exact_selectable_and_same_family(self) -> None:
        constraint = constraint_from_direction(
            architecture_review_id=REVIEW_ID,
            direction=existing_direction(),
        )
        axes = {
            "axis-covered": {
                "axis_id": "axis-covered",
                "axis_identity": AXIS_IDENTITY,
            }
        }
        require_existing_axis_binding(
            constraint,
            axes_by_id=axes,
            selectable_axis_ids=frozenset({"axis-covered"}),
            resolved_architecture_families={"axis-covered": FAMILY},
        )
        require_decision_direction(
            constraint,
            action="deepen",
            target_axis_id="axis-covered",
            target_axis_identity=AXIS_IDENTITY,
            target_architecture_family=FAMILY,
        )
        for selectable, identity, family in (
            (frozenset(), AXIS_IDENTITY, FAMILY),
            (frozenset({"axis-covered"}), "axis:" + D1, FAMILY),
            (
                frozenset({"axis-covered"}),
                AXIS_IDENTITY,
                "architecture-family:" + D1,
            ),
        ):
            with self.subTest(selectable=selectable, identity=identity, family=family):
                forged_axes = {
                    "axis-covered": {
                        "axis_id": "axis-covered",
                        "axis_identity": identity,
                    }
                }
                with self.assertRaises(ArchitectureReviewDirectionError):
                    require_existing_axis_binding(
                        constraint,
                        axes_by_id=forged_axes,
                        selectable_axis_ids=selectable,
                        resolved_architecture_families={"axis-covered": family},
                    )
        with self.assertRaises(ArchitectureReviewDirectionError):
            require_decision_direction(
                constraint,
                action="deepen",
                target_axis_id="axis-other",
                target_axis_identity=AXIS_IDENTITY,
                target_architecture_family=FAMILY,
            )

    def test_new_mechanism_requires_expert_layer_and_reviewed_family(self) -> None:
        constraint = constraint_from_direction(
            architecture_review_id=REVIEW_ID,
            direction=new_direction(),
        )
        require_decision_direction(
            constraint,
            action="new_mechanism",
            target_axis_id="axis-anchor",
            target_axis_identity=AXIS_IDENTITY,
            target_architecture_family=FAMILY,
        )
        added = {
            "axis-good": {"primary_research_layer": "model"},
            "axis-wrong-layer": {"primary_research_layer": "label"},
            "axis-wrong-family": {"primary_research_layer": "model"},
        }
        eligible = eligible_new_mechanism_axes(
            constraint,
            added_axes=added,
            resolved_architecture_families={
                "axis-good": FAMILY,
                "axis-wrong-layer": FAMILY,
                "axis-wrong-family": "architecture-family:" + D1,
            },
        )
        self.assertEqual(eligible, ("axis-good",))
        materialized = constraint.with_materialized_targets(eligible)
        require_decision_direction(
            materialized,
            action="contrast",
            target_axis_id="axis-good",
            target_axis_identity=AXIS_IDENTITY,
            target_architecture_family=FAMILY,
        )
        with self.assertRaises(ArchitectureReviewDirectionError):
            require_decision_direction(
                constraint,
                action="deepen",
                target_axis_id="axis-anchor",
                target_axis_identity=AXIS_IDENTITY,
                target_architecture_family=FAMILY,
            )

    def test_quant_team_basis_includes_review_trigger_and_every_diagnosis(self) -> None:
        constraint = constraint_from_direction(
            architecture_review_id=REVIEW_ID,
            direction=existing_direction(),
        )
        self.assertEqual(
            required_quant_team_basis(constraint),
            frozenset(
                {
                    ("architecture-review", REVIEW_ID),
                    ("architecture-review-trigger", D2),
                    *( ("study-diagnosis", item) for item in DIAGNOSES ),
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
