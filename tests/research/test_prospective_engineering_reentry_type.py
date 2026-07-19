from __future__ import annotations

from copy import deepcopy
import unittest

from axiom_rift.research.prospective_engineering_reentry import (
    ProspectiveEngineeringReentry,
    ProspectiveEngineeringReentryError,
)
from axiom_rift.research.semantic_question import (
    SemanticQuestionCore,
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)


class ProspectiveEngineeringReentryTypeTests(unittest.TestCase):
    @staticmethod
    def _lineage(
        *,
        relation: SemanticQuestionRelation = (
            SemanticQuestionRelation.ENGINEERING_REENTRY
        ),
    ) -> SemanticQuestionLineageProposal:
        core = SemanticQuestionCore(
            causal_question="Does the corrected protocol resolve the same risk question?",
            changed_variables=("intent_calendar_policy",),
            controlled_variables=("data", "split"),
        )
        return SemanticQuestionLineageProposal(
            predecessor_study_id="STU-0122",
            successor_study_id="STU-0123",
            predecessor_core_id=core.identity,
            successor_core_id=core.identity,
            relation=relation,
            rationale="Reenter the same question under the validated correction.",
            basis_record_ids=(
                "job-completed:" + "1" * 64,
                "study-close:" + "2" * 64,
                "study-diagnosis:diagnosis:" + "3" * 64,
                "study-open:STU-0122",
            ),
        )

    @classmethod
    def _plan(cls) -> ProspectiveEngineeringReentry:
        return ProspectiveEngineeringReentry(
            mission_id="MIS-PROSPECTIVE-REENTRY",
            portfolio_snapshot_id="portfolio:" + "4" * 64,
            target_axis_id="axis-risk-reentry",
            target_axis_identity="axis:" + "5" * 64,
            predecessor_study_id="STU-0122",
            successor_study_id="STU-0123",
            study_diagnosis_id="diagnosis:" + "3" * 64,
            study_close_record_id="2" * 64,
            completion_record_id="1" * 64,
            disposition_record_id="6" * 64,
            disposition_hash="7" * 64,
            successor_artifact_hash="8" * 64,
            successor_baseline_executable_id="executable:" + "9" * 64,
            portfolio_action="deepen",
            semantic_question_lineage=cls._lineage(),
        )

    def test_canonical_payload_round_trips_exactly(self) -> None:
        plan = self._plan()
        rebuilt = ProspectiveEngineeringReentry.from_mapping(
            plan.to_identity_payload()
        )
        self.assertEqual(rebuilt, plan)
        self.assertEqual(rebuilt.identity, plan.identity)

    def test_payload_tampering_fails_closed(self) -> None:
        payload = deepcopy(self._plan().to_identity_payload())
        payload["semantic_question_lineage_id"] = (
            "semantic-question-lineage:" + "a" * 64
        )
        with self.assertRaisesRegex(
            ProspectiveEngineeringReentryError,
            "not canonical",
        ):
            ProspectiveEngineeringReentry.from_mapping(payload)

    def test_non_engineering_lineage_is_rejected(self) -> None:
        plan = self._plan()
        with self.assertRaisesRegex(
            ProspectiveEngineeringReentryError,
            "same-core typed lineage",
        ):
            ProspectiveEngineeringReentry(
                mission_id=plan.mission_id,
                portfolio_snapshot_id=plan.portfolio_snapshot_id,
                target_axis_id=plan.target_axis_id,
                target_axis_identity=plan.target_axis_identity,
                predecessor_study_id=plan.predecessor_study_id,
                successor_study_id=plan.successor_study_id,
                study_diagnosis_id=plan.study_diagnosis_id,
                study_close_record_id=plan.study_close_record_id,
                completion_record_id=plan.completion_record_id,
                disposition_record_id=plan.disposition_record_id,
                disposition_hash=plan.disposition_hash,
                successor_artifact_hash=plan.successor_artifact_hash,
                successor_baseline_executable_id=(
                    plan.successor_baseline_executable_id
                ),
                portfolio_action=plan.portfolio_action,
                semantic_question_lineage=self._lineage(
                    relation=SemanticQuestionRelation.CONTINUATION
                ),
            )


if __name__ == "__main__":
    unittest.main()
