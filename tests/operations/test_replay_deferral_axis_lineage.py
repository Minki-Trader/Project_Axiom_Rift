from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.replay_projection import (
    ReplayTransitionError,
    initial_obligation_record,
    prepare_deferral,
)
from axiom_rift.research.historical_adjudication import ReplayPriority
from axiom_rift.research.replay_obligation import (
    ReplayDeferral,
    ReplayDeferralBasis,
    ReplayDeferralBasisKind,
    ReplayResumeCondition,
    ReplayResumeConditionKind,
    derive_historical_replay_obligation,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


MISSION_ID = "MIS-DEFERRAL-LINEAGE"
REGISTRATION_STUDY = "STU-DEFERRAL-REGISTRATION"
COMPLETION_STUDY = "STU-DEFERRAL-COMPLETION"
THIRD_STUDY = "STU-DEFERRAL-THIRD"
COMPLETION_ID = "1" * 64
CLOSE_ID = "2" * 64
DIAGNOSIS_ID = "diagnosis:" + "3" * 64
JOB_ID = "job:" + "4" * 64
EXECUTABLE = {
    "schema": "replay_deferral_axis_lineage_fixture.v1",
    "source_contracts": [],
}
EXECUTABLE_ID = "executable:" + canonical_digest(
    domain="executable",
    payload=EXECUTABLE,
)


def _authority(record: IndexRecord, sequence: int, offset: int) -> IndexRecord:
    return replace(
        record,
        authority_event_id=f"{sequence:064x}",
        authority_offset=offset,
        authority_sequence=sequence,
    )


class ReplayDeferralAxisLineageTests(unittest.TestCase):
    def _index(self, declaration_study_id: str):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        index = LocalIndex(Path(temporary.name) / "index.sqlite3")
        self.addCleanup(index.close)
        payload = {
            "adjudication": {
                "candidate_eligible": False,
                "claims": [{"claim_id": "claim-deferral-lineage"}],
                "criteria": [{"criterion_id": "criterion-a"}],
            },
            "audit_artifact_hash": "5" * 64,
            "completion_record_id": COMPLETION_ID,
            "disposition": "replay_required",
            "executable_id": EXECUTABLE_ID,
            "measurement_artifact_hash": "6" * 64,
            "reason_codes": ["missing_exact_uncertainty"],
            "replay_priority": ReplayPriority.P1.value,
            "schema": "historical_scientific_adjudication.v2",
            "study_close_record_id": CLOSE_ID,
            "study_id": COMPLETION_STUDY,
            "validation_plan_hash": "7" * 64,
        }
        obligation = derive_historical_replay_obligation(
            governing_mission_id=MISSION_ID,
            historical_adjudication_id=(
                "historical-adjudication:" + "8" * 64
            ),
            adjudication_payload=payload,
        )
        study_records = tuple(
            IndexRecord(
                kind="study-open",
                record_id=study_id,
                subject=f"Study:{study_id}",
                status="closed",
                fingerprint=f"{ordinal}" * 64,
                payload={
                    "mission_id": MISSION_ID,
                    "portfolio_axis_id": f"AXS-DEFERRAL-{ordinal}",
                    "portfolio_axis_identity": "axis:" + f"{ordinal}" * 64,
                },
            )
            for ordinal, study_id in enumerate(
                (REGISTRATION_STUDY, COMPLETION_STUDY, THIRD_STUDY),
                start=1,
            )
        )
        records = (
            IndexRecord(
                kind="historical-scientific-adjudication",
                record_id=obligation.historical_adjudication_id,
                subject=f"Study:{COMPLETION_STUDY}",
                status="replay_required",
                fingerprint="8" * 64,
                payload=payload,
            ),
            initial_obligation_record(obligation),
            *study_records,
            IndexRecord(
                kind="trial",
                record_id=EXECUTABLE_ID,
                subject="Batch:BAT-DEFERRAL-LINEAGE",
                status="evaluated",
                fingerprint=EXECUTABLE_ID.removeprefix("executable:"),
                payload={
                    "executable": EXECUTABLE,
                    "mission_id": MISSION_ID,
                    "portfolio_axis_id": "AXS-DEFERRAL-1",
                    "portfolio_axis_identity": "axis:" + "1" * 64,
                    "study_id": REGISTRATION_STUDY,
                },
            ),
            IndexRecord(
                kind="job-declared",
                record_id=JOB_ID,
                subject=f"Job:{JOB_ID}",
                status="declared",
                fingerprint="4" * 64,
                payload={
                    "mission_id": MISSION_ID,
                    "study_id": declaration_study_id,
                    "spec": {
                        "evidence_subject": {
                            "id": EXECUTABLE_ID,
                            "kind": "Executable",
                        }
                    },
                },
            ),
            IndexRecord(
                kind="job-completed",
                record_id=COMPLETION_ID,
                subject=f"Job:{JOB_ID}",
                status="not_evaluable",
                fingerprint="1" * 64,
                payload={
                    "job_id": JOB_ID,
                    "scientific": {"executable_id": EXECUTABLE_ID},
                },
            ),
            IndexRecord(
                kind="study-close",
                record_id=CLOSE_ID,
                subject=f"Study:{COMPLETION_STUDY}",
                status="not_evaluable",
                fingerprint="2" * 64,
                payload={"outcome": "not_evaluable"},
            ),
            IndexRecord(
                kind="study-diagnosis",
                record_id=DIAGNOSIS_ID,
                subject=f"Study:{COMPLETION_STUDY}",
                status="not_identifiable",
                fingerprint="3" * 64,
                payload={
                    "evidence_basis": [
                        {"kind": "job-completed", "record_id": COMPLETION_ID},
                        {"kind": "study-close", "record_id": CLOSE_ID},
                    ],
                    "mission_id": MISSION_ID,
                    "study_close_record_id": CLOSE_ID,
                    "study_id": COMPLETION_STUDY,
                },
            ),
        )
        index.put_many(
            tuple(
                _authority(record, ordinal + 1, ordinal)
                for ordinal, record in enumerate(records)
            )
        )
        return index, obligation

    @staticmethod
    def _deferral(obligation) -> ReplayDeferral:
        return ReplayDeferral(
            obligation_id=obligation.identity,
            basis=ReplayDeferralBasis(
                kind=ReplayDeferralBasisKind.STUDY_DIAGNOSIS,
                record_id=DIAGNOSIS_ID,
                subject_id=COMPLETION_STUDY,
            ),
            reason_codes=("not_evaluable",),
            resume_conditions=(
                ReplayResumeCondition(
                    kind=(
                        ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL
                    ),
                    protocol_id="python.source.exact_replay.v1",
                    original_executable_ids=(EXECUTABLE_ID,),
                    criterion_ids=obligation.criterion_ids,
                ),
            ),
        )

    def test_deferral_uses_completion_study_not_registration_study(self) -> None:
        index, obligation = self._index(COMPLETION_STUDY)
        records, _constraints, result = prepare_deferral(
            index,
            mission_id=MISSION_ID,
            deferrals=(self._deferral(obligation),),
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(
            result["deferred_replay_obligation_ids"],
            [obligation.identity],
        )

        for wrong_study in (REGISTRATION_STUDY, THIRD_STUDY):
            wrong_index, wrong_obligation = self._index(wrong_study)
            with self.subTest(wrong_study=wrong_study):
                with self.assertRaisesRegex(
                    ReplayTransitionError,
                    "diagnosis basis is not bound",
                ):
                    prepare_deferral(
                        wrong_index,
                        mission_id=MISSION_ID,
                        deferrals=(self._deferral(wrong_obligation),),
                    )


if __name__ == "__main__":
    unittest.main()
