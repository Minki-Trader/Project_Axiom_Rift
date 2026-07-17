from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from axiom_rift.operations.fixed_hold_replay_profile import (
    require_borrowed_production_profile,
)
from axiom_rift.operations.fixed_hold_replay_workflow import (
    ReplayAxisAdmission,
    ReplayInitiativeLifecycle,
)
from axiom_rift.operations.strict_operation_chain import OperationStep
from axiom_rift.research.portfolio import PortfolioAction
from axiom_rift.research.semantic_question import SemanticQuestionCore


PREFIX = "production-replay-"
QUESTION = {
    "causal_question": "production replay question",
    "changed_variables": ["replay treatment"],
    "controlled_variables": ["replay control"],
    "done_conditions": ["registered family completes"],
    "evidence_modes": ["development"],
}
QUESTION_CORE_ID = SemanticQuestionCore.from_question_manifest(QUESTION).identity


def _design(*, lifecycle=ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE):
    return SimpleNamespace(
        spec=SimpleNamespace(
            initiative_lifecycle=lifecycle,
            axis_admission=ReplayAxisAdmission.ADD_NEW_MECHANISM,
            new_axis_action=PortfolioAction.NEW_MECHANISM,
            resolved_new_axis_action=PortfolioAction.NEW_MECHANISM,
            operation_prefix=PREFIX,
            study_id="STU-9002",
        ),
        semantic_question_lineage=SimpleNamespace(
            successor_study_id="STU-9002",
            successor_core_id=QUESTION_CORE_ID,
        ),
        question=QUESTION,
        batch_spec=SimpleNamespace(study_hash="a" * 64),
        base_snapshot_id="portfolio:" + "a" * 64,
        prior_axes=(SimpleNamespace(axis_id="axis-source"),),
        replay_axis=SimpleNamespace(axis_id="axis-replay"),
        bridge_decision=SimpleNamespace(
            chosen=SimpleNamespace(action=PortfolioAction.NEW_MECHANISM),
            protocol_revision=None,
        ),
        expanded_snapshot=SimpleNamespace(axes=(1, 2)),
        protocol_revision=None,
    )


class FixedHoldReplayProfileTests(unittest.TestCase):
    @patch(
        "axiom_rift.operations.fixed_hold_replay_profile."
        "fixed_hold_replay_study_input_hash",
        return_value="a" * 64,
    )
    @patch("axiom_rift.operations.fixed_hold_replay_profile.operation_steps")
    def test_borrowed_profile_requires_resolution_without_ownership_steps(
        self,
        planned: Mock,
        _study_hash: Mock,
    ) -> None:
        design = _design()
        planned.return_value = (
            OperationStep(PREFIX + "open-study", "study_opened", "study_close"),
            OperationStep(
                PREFIX + "resolve-replay",
                "historical_replay_obligations_resolved",
                "diagnose",
            ),
        )

        self.assertIs(
            require_borrowed_production_profile(Mock(), design),
            design,
        )

        attacks = (
            (
                OperationStep(
                    PREFIX + "open-initiative",
                    "initiative_opened",
                    "study_close",
                ),
                *planned.return_value,
            ),
            (
                OperationStep(
                    PREFIX + "disposition-decision",
                    "portfolio_decision_recorded",
                    "diagnose",
                ),
                *planned.return_value,
            ),
            planned.return_value[:1],
        )
        for steps in attacks:
            with self.subTest(steps=steps):
                planned.return_value = steps
                with self.assertRaisesRegex(RuntimeError, "owns Initiative state"):
                    require_borrowed_production_profile(Mock(), design)

    @patch(
        "axiom_rift.operations.fixed_hold_replay_profile."
        "fixed_hold_replay_study_input_hash",
        return_value="a" * 64,
    )
    @patch("axiom_rift.operations.fixed_hold_replay_profile.operation_steps")
    def test_profile_fails_closed_on_lifecycle_lineage_or_hash_drift(
        self,
        planned: Mock,
        _study_hash: Mock,
    ) -> None:
        planned.return_value = (
            OperationStep(
                PREFIX + "resolve-replay",
                "historical_replay_obligations_resolved",
                "diagnose",
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "must borrow"):
            require_borrowed_production_profile(
                Mock(),
                _design(
                    lifecycle=(
                        ReplayInitiativeLifecycle.OWN_BOUNDED_INITIATIVE
                    )
                ),
            )

        missing_lineage = _design()
        missing_lineage.semantic_question_lineage = None
        with self.assertRaisesRegex(RuntimeError, "semantic lineage"):
            require_borrowed_production_profile(Mock(), missing_lineage)

        mismatched_hash = _design()
        mismatched_hash.batch_spec.study_hash = "b" * 64
        with self.assertRaisesRegex(RuntimeError, "hashes differ"):
            require_borrowed_production_profile(Mock(), mismatched_hash)

        mismatched_core = _design()
        mismatched_core.semantic_question_lineage.successor_core_id = (
            "semantic-question-core:" + "b" * 64
        )
        with self.assertRaisesRegex(RuntimeError, "semantic lineage"):
            require_borrowed_production_profile(Mock(), mismatched_core)


if __name__ == "__main__":
    unittest.main()
