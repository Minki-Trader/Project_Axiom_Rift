from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.replay_projection import (
    ReplayTransitionError,
    initial_obligation_record,
    prepare_deferral,
    prepare_resume,
    replay_obligation_capability_id,
)
from axiom_rift.research.historical_adjudication import ReplayPriority
from axiom_rift.research.replay_obligation import (
    ReplayDeferral,
    ReplayDeferralBasis,
    ReplayDeferralBasisKind,
    ReplayDeferralExecutionBinding,
    ReplayRepairBasisKind,
    ReplayRepairProvenance,
    ReplayResumeCondition,
    ReplayResumeConditionKind,
    ReplayResumeEvidence,
    derive_historical_replay_obligation,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


MISSION_ID = "MIS-REPLAY-RESUME"
ORIGINAL_STUDY_ID = "STU-ORIGINAL-REPLAY"
PROTOCOL_ID = "python.source.exact_replay.v1"
ORIGINAL_AXIS_ID = "AXS-ORIGINAL-REPLAY"
ORIGINAL_AXIS_IDENTITY = "axis:" + "0" * 64
ORIGINAL_SOURCE_ID = "source:" + "a" * 64
ORIGINAL_EXECUTABLE = {
    "schema": "original_fixture.v1",
    "source_contracts": [ORIGINAL_SOURCE_ID],
}
ORIGINAL_EXECUTABLE_ID = "executable:" + canonical_digest(
    domain="executable",
    payload=ORIGINAL_EXECUTABLE,
)


def _adjudication_payload() -> dict[str, object]:
    return {
        "adjudication": {
            "candidate_eligible": False,
            "claims": [{"claim_id": "claim-original"}],
            "criteria": [
                {"criterion_id": "criterion-a"},
                {"criterion_id": "criterion-b"},
            ],
        },
        "audit_artifact_hash": "1" * 64,
        "completion_record_id": "2" * 64,
        "disposition": "replay_required",
        "executable_id": ORIGINAL_EXECUTABLE_ID,
        "measurement_artifact_hash": "4" * 64,
        "reason_codes": ["missing_exact_uncertainty"],
        "replay_priority": ReplayPriority.P1.value,
        "schema": "historical_scientific_adjudication.v2",
        "study_close_record_id": "5" * 64,
        "study_id": ORIGINAL_STUDY_ID,
        "validation_plan_hash": "6" * 64,
    }


def _typed_replay_executable(original_executable_id: str) -> dict[str, object]:
    return {
        "component_manifests": [
            {
                "spec": {
                    "parameter_fields": [
                        "historical_reference_executable_id"
                    ]
                }
            }
        ],
        "parameters": {
            "historical_reference_executable_id": original_executable_id
        },
        "schema": "replay_fixture.v1",
    }


def _repair_spec(
    replay_executable_id: str,
    implementation_identity: str,
    *,
    validation_plan_hash: str,
    changed_cause_proof_hash: str | None = None,
) -> dict[str, object]:
    spec: dict[str, object] = {
        "callable_identity": "python:tests.exact_replay_repair",
        "evidence_subject": {
            "kind": "Executable",
            "id": replay_executable_id,
        },
        "implementation_identity": implementation_identity,
        "input_hashes": ["1" * 64],
        "scientific_binding": {
            "validation_plan_hash": validation_plan_hash,
        },
    }
    if changed_cause_proof_hash is not None:
        spec["changed_cause_proof_hash"] = changed_cause_proof_hash
    return spec


def _work_fingerprint(spec: dict[str, object]) -> str:
    work_fields = (
        "callable_identity",
        "component_parity_binding",
        "evidence_subject",
        "external_dependency_binding",
        "holdout_binding",
        "input_hashes",
        "runtime_binding",
        "scientific_binding",
        "source_binding",
    )
    return canonical_digest(
        domain="job-work",
        payload={
            "mission_id": MISSION_ID,
            "work": {name: spec.get(name) for name in work_fields},
        },
    )


class ReplayResumeProjectionTests(unittest.TestCase):
    def _put_many(self, records: tuple[IndexRecord, ...]) -> None:
        normalized = []
        for offset, record in enumerate(records):
            if record.authority_sequence is not None:
                record = replace(
                    record,
                    authority_event_id=(
                        record.authority_event_id
                        or f"{record.authority_sequence:064x}"
                    ),
                    authority_offset=(
                        record.authority_offset
                        if record.authority_offset is not None
                        else offset
                    ),
                )
            normalized.append(record)
        self.index.put_many(tuple(normalized))

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.index = LocalIndex(Path(self.temporary.name) / "index.sqlite3")
        self.addCleanup(self.index.close)
        payload = _adjudication_payload()
        self.obligation = derive_historical_replay_obligation(
            governing_mission_id=MISSION_ID,
            historical_adjudication_id="historical-adjudication:" + "7" * 64,
            adjudication_payload=payload,
        )
        self.original_job_id = "job:" + "8" * 64
        self.original_diagnosis_id = "diagnosis:" + "9" * 64
        self.source_id = ORIGINAL_SOURCE_ID
        self._put_many(
            (
                IndexRecord(
                    kind="historical-scientific-adjudication",
                    record_id=self.obligation.historical_adjudication_id,
                    subject=f"Study:{ORIGINAL_STUDY_ID}",
                    status="replay_required",
                    fingerprint="7" * 64,
                    payload=payload,
                    authority_sequence=2,
                    authority_event_id=f"{2:064x}",
                ),
                replace(
                    initial_obligation_record(self.obligation),
                    authority_sequence=3,
                    authority_event_id=f"{3:064x}",
                ),
                IndexRecord(
                    kind="study-open",
                    record_id=ORIGINAL_STUDY_ID,
                    subject=f"Study:{ORIGINAL_STUDY_ID}",
                    status="open",
                    fingerprint="b" * 64,
                    payload={
                        "mission_id": MISSION_ID,
                        "portfolio_axis_id": ORIGINAL_AXIS_ID,
                        "portfolio_axis_identity": ORIGINAL_AXIS_IDENTITY,
                    },
                    authority_sequence=1,
                    authority_event_id=f"{1:064x}",
                ),
                IndexRecord(
                    kind="study-close",
                    record_id=self.obligation.original_study_close_record_id,
                    subject=f"Study:{ORIGINAL_STUDY_ID}",
                    status="not_evaluable",
                    fingerprint="c" * 64,
                    payload={"outcome": "not_evaluable"},
                    authority_sequence=1,
                    authority_event_id=f"{1:064x}",
                ),
                IndexRecord(
                    kind="job-declared",
                    record_id=self.original_job_id,
                    subject=f"Job:{self.original_job_id}",
                    status="declared",
                    fingerprint="8" * 64,
                    payload={
                        "mission_id": MISSION_ID,
                        "study_id": ORIGINAL_STUDY_ID,
                        "spec": {
                            "evidence_subject": {
                                "kind": "Executable",
                                "id": self.obligation.original_executable_id,
                            }
                        },
                    },
                    authority_sequence=1,
                    authority_event_id=f"{1:064x}",
                ),
                IndexRecord(
                    kind="job-completed",
                    record_id=self.obligation.original_completion_record_id,
                    subject=f"Job:{self.original_job_id}",
                    status="not_evaluable",
                    fingerprint="2" * 64,
                    payload={
                        "job_id": self.original_job_id,
                        "scientific": {
                            "executable_id": (
                                self.obligation.original_executable_id
                            )
                        },
                    },
                    authority_sequence=1,
                    authority_event_id=f"{1:064x}",
                ),
                IndexRecord(
                    kind="trial",
                    record_id=self.obligation.original_executable_id,
                    subject="Batch:BAT-ORIGINAL",
                    status="evaluated",
                    fingerprint=(
                        self.obligation.original_executable_id.removeprefix(
                            "executable:"
                        )
                    ),
                    payload={
                        "executable": ORIGINAL_EXECUTABLE,
                        "mission_id": MISSION_ID,
                        "portfolio_axis_id": ORIGINAL_AXIS_ID,
                        "portfolio_axis_identity": ORIGINAL_AXIS_IDENTITY,
                        "study_id": ORIGINAL_STUDY_ID,
                    },
                    authority_sequence=1,
                    authority_event_id=f"{1:064x}",
                ),
                IndexRecord(
                    kind="study-diagnosis",
                    record_id=self.original_diagnosis_id,
                    subject=f"Study:{ORIGINAL_STUDY_ID}",
                    status="not_identifiable",
                    fingerprint="9" * 64,
                    payload={
                        "evidence_basis": [
                            {
                                "kind": "job-completed",
                                "record_id": (
                                    self.obligation.original_completion_record_id
                                ),
                            },
                            {
                                "kind": "study-close",
                                "record_id": (
                                    self.obligation.original_study_close_record_id
                                ),
                            },
                        ],
                        "mission_id": MISSION_ID,
                        "study_close_record_id": (
                            self.obligation.original_study_close_record_id
                        ),
                        "study_id": ORIGINAL_STUDY_ID,
                    },
                    authority_sequence=4,
                    authority_event_id=f"{4:064x}",
                ),
            )
        )

    def _condition(
        self,
        kind: ReplayResumeConditionKind,
        *,
        subject_id: str | None = None,
    ) -> ReplayResumeCondition:
        return ReplayResumeCondition(
            kind=kind,
            protocol_id=PROTOCOL_ID,
            original_executable_ids=(self.obligation.original_executable_id,),
            criterion_ids=self.obligation.criterion_ids,
            subject_id=subject_id,
        )

    def _pending_diagnosis_deferral(
        self,
        *conditions: ReplayResumeCondition,
    ) -> ReplayDeferral:
        return ReplayDeferral(
            obligation_id=self.obligation.identity,
            basis=ReplayDeferralBasis(
                kind=ReplayDeferralBasisKind.STUDY_DIAGNOSIS,
                record_id=self.original_diagnosis_id,
                subject_id=ORIGINAL_STUDY_ID,
            ),
            reason_codes=("not_evaluable",),
            resume_conditions=tuple(conditions),
        )

    def _store_deferral(self, deferral: ReplayDeferral) -> IndexRecord:
        records, constraints, _ = prepare_deferral(
            self.index,
            mission_id=MISSION_ID,
            deferrals=(deferral,),
        )
        self.assertIsNone(constraints)
        record = replace(
            records[0],
            authority_sequence=10,
            authority_event_id=f"{10:064x}",
        )
        self._put_many((record,))
        return record

    def test_pending_bases_require_exact_obligation_provenance(self) -> None:
        ordinary = self._condition(
            ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL
        )
        prepare_deferral(
            self.index,
            mission_id=MISSION_ID,
            deferrals=(self._pending_diagnosis_deferral(ordinary),),
        )

        source_invalidation_id = "source-authority-invalidation:" + "b" * 64
        source_record = IndexRecord(
            kind="source-authority-invalidation",
            record_id=source_invalidation_id,
            subject=f"Source:{self.source_id}",
            status="confirmed_and_suspended",
            fingerprint="b" * 64,
            payload={
                "invalidation": {"source_contract_id": self.source_id}
            },
            event_stream=f"source-authority:{self.source_id}",
            event_sequence=1,
            authority_sequence=5,
            authority_event_id=f"{5:064x}",
        )
        architecture_id = "architecture-review:" + "c" * 64
        architecture_family = "architecture-family:" + "d" * 64
        dependency_id = "dependency.replay.fixture"
        blocker_id = "e" * 64
        self._put_many(
            (
                source_record,
                IndexRecord(
                    kind="architecture-review",
                    record_id=architecture_id,
                    subject=f"Mission:{MISSION_ID}",
                    status="rotate_architecture",
                    fingerprint="c" * 64,
                    payload={
                        "covered_diagnosis_ids": [self.original_diagnosis_id],
                        "mission_id": MISSION_ID,
                        "system_architecture_family": architecture_family,
                    },
                    authority_sequence=6,
                    authority_event_id=f"{6:064x}",
                ),
                IndexRecord(
                    kind="external-blocker",
                    record_id=blocker_id,
                    subject=f"Mission:{MISSION_ID}",
                    status="complete",
                    fingerprint=blocker_id,
                    payload={
                        "cause": {
                            "blocked_mission_capability": (
                                replay_obligation_capability_id(
                                    self.obligation.identity
                                )
                            ),
                            "dependency_id": dependency_id,
                        }
                    },
                    authority_sequence=7,
                    authority_event_id=f"{7:064x}",
                ),
            )
        )
        exact_requests = (
            ReplayDeferral(
                obligation_id=self.obligation.identity,
                basis=ReplayDeferralBasis(
                    kind=(
                        ReplayDeferralBasisKind.SOURCE_AUTHORITY_INVALIDATION
                    ),
                    record_id=source_invalidation_id,
                    subject_id=self.source_id,
                ),
                reason_codes=("source_invalid",),
                resume_conditions=(
                    self._condition(
                        ReplayResumeConditionKind.REPLACEMENT_SOURCE_CONTRACT,
                        subject_id=self.source_id,
                    ),
                ),
            ),
            ReplayDeferral(
                obligation_id=self.obligation.identity,
                basis=ReplayDeferralBasis(
                    kind=ReplayDeferralBasisKind.ARCHITECTURE_REVIEW,
                    record_id=architecture_id,
                    subject_id=architecture_family,
                ),
                reason_codes=("architecture_not_identifiable",),
                resume_conditions=(ordinary,),
            ),
            ReplayDeferral(
                obligation_id=self.obligation.identity,
                basis=ReplayDeferralBasis(
                    kind=ReplayDeferralBasisKind.EXTERNAL_BLOCKER,
                    record_id=blocker_id,
                    subject_id=dependency_id,
                ),
                reason_codes=("external_unavailable",),
                resume_conditions=(
                    self._condition(
                        ReplayResumeConditionKind.EXTERNAL_DEPENDENCY_AVAILABLE,
                        subject_id=dependency_id,
                    ),
                ),
            ),
        )
        for request in exact_requests:
            with self.subTest(kind=request.basis.kind.value):
                prepared, _, _ = prepare_deferral(
                    self.index,
                    mission_id=MISSION_ID,
                    deferrals=(request,),
                )
                self.assertEqual(prepared[0].status, "deferred")

        unrelated = replace(
            exact_requests[2],
            basis=ReplayDeferralBasis(
                kind=ReplayDeferralBasisKind.EXTERNAL_BLOCKER,
                record_id=blocker_id,
                subject_id="dependency.unrelated",
            ),
            resume_conditions=(
                self._condition(
                    ReplayResumeConditionKind.EXTERNAL_DEPENDENCY_AVAILABLE,
                    subject_id="dependency.unrelated",
                ),
            ),
        )
        with self.assertRaisesRegex(
            ReplayTransitionError, "exact capability"
        ):
            prepare_deferral(
                self.index,
                mission_id=MISSION_ID,
                deferrals=(unrelated,),
            )

    def test_development_material_resume_is_later_and_zero_credit(self) -> None:
        condition = self._condition(
            ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL
        )
        deferral = self._pending_diagnosis_deferral(condition)
        self._store_deferral(deferral)
        material_id = "f" * 64
        authority_id = "0" * 64
        shared = {
            "material_content_sha256": "1" * 64,
            "material_identity": material_id,
            "material_receipt_hash": "2" * 64,
            "mission_id": MISSION_ID,
            "split_identity": "3" * 64,
        }
        self._put_many(
            (
                IndexRecord(
                    kind="post-holdout-development",
                    record_id=authority_id,
                    subject=f"Material:{material_id}",
                    status="accepted",
                    fingerprint="2" * 64,
                    payload=shared,
                    authority_sequence=11,
                    authority_event_id=f"{11:064x}",
                ),
                IndexRecord(
                    kind="development-material",
                    record_id=material_id,
                    subject=f"Mission:{MISSION_ID}",
                    status="accepted",
                    fingerprint="2" * 64,
                    payload={
                        **shared,
                        "post_holdout_development_id": authority_id,
                    },
                    authority_sequence=11,
                    authority_event_id=f"{11:064x}",
                ),
            )
        )
        evidence = ReplayResumeEvidence(
            obligation_id=self.obligation.identity,
            deferral_id=deferral.identity,
            resume_condition_id=condition.identity,
            trigger_record_id=material_id,
        )
        records, constraints, result = prepare_resume(
            self.index,
            mission_id=MISSION_ID,
            resumes=(evidence,),
        )
        self.assertEqual(records[0].status, "pending")
        self.assertEqual(records[0].payload["scientific_satisfaction_delta"], 0)
        assert constraints is not None
        self.assertEqual(
            constraints["pending_replay_obligation_ids"],
            [self.obligation.identity],
        )
        self.assertEqual(result["scientific_claim_delta"], 0)
        self.assertEqual(result["scientific_trial_delta"], 0)

        stale_authority_id = "5" * 64
        stale = replace(
            self.index.get("development-material", material_id),
            record_id="4" * 64,
            payload={**shared, "material_identity": "4" * 64,
                     "post_holdout_development_id": stale_authority_id},
            authority_sequence=9,
            authority_event_id=f"{9:064x}",
        )
        stale_authority = replace(
            self.index.get("post-holdout-development", authority_id),
            record_id=stale_authority_id,
            subject=f"Material:{stale.record_id}",
            payload={**shared, "material_identity": stale.record_id},
            authority_sequence=9,
            authority_event_id=f"{9:064x}",
        )
        self._put_many((stale_authority, stale))
        with self.assertRaisesRegex(ReplayTransitionError, "later than"):
            prepare_resume(
                self.index,
                mission_id=MISSION_ID,
                resumes=(replace(evidence, trigger_record_id=stale.record_id),),
            )

    def _seed_same_protocol_repair(
        self,
        *,
        sibling_job: bool = False,
        scientific_invalidity: bool = False,
        repaired_study_id: str | None = None,
        repaired_executable_id: str | None = None,
        repaired_validation_plan_hash: str | None = None,
    ) -> tuple[
        ReplayResumeEvidence,
        Callable[..., ReplayRepairProvenance],
    ]:
        replay_study_id = "STU-REPLAY-REPAIR"
        decision_id = "decision:" + "a" * 64
        replay_executable_id = "executable:" + "b" * 64
        replay_close_id = "c" * 64
        replay_diagnosis_id = "diagnosis:" + "d" * 64
        previous_job_id = "job:" + "e" * 64
        previous_completion_id = "f" * 64
        previous_implementation = "6" * 64
        repaired_implementation = "7" * 64
        changed_cause = "8" * 64
        failure_signature = "9" * 64
        validation_plan_hash = "0" * 64
        previous_spec = _repair_spec(
            replay_executable_id,
            previous_implementation,
            validation_plan_hash=validation_plan_hash,
        )
        exact_work_fingerprint = _work_fingerprint(previous_spec)
        exact_stream = f"job-attempt:{exact_work_fingerprint}"
        progress = IndexRecord(
            kind="historical-replay-obligation-progress",
            record_id="historical-replay-progress:" + "1" * 64,
            subject=f"Mission:{MISSION_ID}",
            status="in_progress",
            fingerprint="1" * 64,
            payload={
                "binding": {
                    "obligation_ids": [self.obligation.identity],
                    "portfolio_decision_id": decision_id,
                    "replay_executable_id": replay_executable_id,
                    "replay_study_id": replay_study_id,
                    "schema": "replay_execution_binding.v1",
                },
                "obligation_id": self.obligation.identity,
                "prior_status": "pending",
            },
            event_stream=(
                f"historical-replay-obligation:{self.obligation.identity}"
            ),
            event_sequence=2,
            authority_sequence=5,
            authority_event_id=f"{5:064x}",
        )
        base_records = [
            progress,
            IndexRecord(
                kind="study-open",
                record_id=replay_study_id,
                subject=f"Mission:{MISSION_ID}",
                status="open",
                fingerprint="2" * 64,
                payload={
                    "mission_id": MISSION_ID,
                    "portfolio_decision_id": decision_id,
                    "replay_obligation_ids": [self.obligation.identity],
                },
                authority_sequence=5,
                authority_event_id=f"{5:064x}",
            ),
            IndexRecord(
                kind="trial",
                record_id=replay_executable_id,
                subject="Batch:BAT-REPLAY-REPAIR",
                status="evaluated",
                fingerprint="b" * 64,
                payload={
                    "executable": _typed_replay_executable(
                        self.obligation.original_executable_id
                    ),
                    "replay_obligation_ids": [self.obligation.identity],
                    "study_id": replay_study_id,
                },
                authority_sequence=5,
                authority_event_id=f"{5:064x}",
            ),
            IndexRecord(
                kind="job-declared",
                record_id=previous_job_id,
                subject=f"Job:{previous_job_id}",
                status="declared",
                fingerprint="e" * 64,
                payload={
                    "mission_id": MISSION_ID,
                    "study_id": replay_study_id,
                    "spec": previous_spec,
                    "work_fingerprint": exact_work_fingerprint,
                },
                event_stream=exact_stream,
                event_sequence=1,
                authority_sequence=5,
                authority_event_id=f"{5:064x}",
            ),
            IndexRecord(
                kind="job-completed",
                record_id=previous_completion_id,
                subject=f"Job:{previous_job_id}",
                status=("success" if scientific_invalidity else "failed"),
                fingerprint="e" * 64,
                payload=(
                    {
                        "job_id": previous_job_id,
                        "scientific": {
                            "adjudication": {
                                "criteria": [
                                    {
                                        "comparison_state": "passed",
                                        "criterion_id": self.obligation.criterion_ids[0],
                                        "scientific_state": "supported",
                                    }
                                ],
                                "state": "not_evaluable",
                            }
                        },
                    }
                    if scientific_invalidity
                    else {
                        "failure": {
                            "failure_signature": failure_signature,
                            "minimum_reproduction_evidence": [],
                        },
                        "job_id": previous_job_id,
                    }
                ),
                event_stream=exact_stream,
                event_sequence=2,
                authority_sequence=6,
                authority_event_id=f"{6:064x}",
            ),
            IndexRecord(
                kind="study-close",
                record_id=replay_close_id,
                subject=f"Study:{replay_study_id}",
                status="not_evaluable",
                fingerprint="c" * 64,
                payload={"outcome": "not_evaluable"},
                authority_sequence=7,
                authority_event_id=f"{7:064x}",
            ),
            IndexRecord(
                kind="study-diagnosis",
                record_id=replay_diagnosis_id,
                subject=f"Study:{replay_study_id}",
                status="not_identifiable",
                fingerprint="d" * 64,
                payload={
                    "evidence_basis": [
                        {
                            "kind": "job-completed",
                            "record_id": previous_completion_id,
                        },
                        {"kind": "study-close", "record_id": replay_close_id},
                    ],
                    "mission_id": MISSION_ID,
                    "study_close_record_id": replay_close_id,
                    "study_id": replay_study_id,
                },
                authority_sequence=8,
                authority_event_id=f"{8:064x}",
            ),
        ]
        repair_previous_job_id = previous_job_id
        repair_previous_completion_id = previous_completion_id
        repair_stream = exact_stream
        repair_input_hash = "1" * 64
        if sibling_job:
            repair_previous_job_id = "job:" + "4" * 64
            repair_previous_completion_id = "5" * 64
            sibling_spec = _repair_spec(
                replay_executable_id,
                previous_implementation,
                validation_plan_hash=validation_plan_hash,
            )
            repair_input_hash = "2" * 64
            sibling_spec["input_hashes"] = [repair_input_hash]
            sibling_fingerprint = _work_fingerprint(sibling_spec)
            repair_stream = f"job-attempt:{sibling_fingerprint}"
            base_records.extend(
                (
                    IndexRecord(
                        kind="job-declared",
                        record_id=repair_previous_job_id,
                        subject=f"Job:{repair_previous_job_id}",
                        status="declared",
                        fingerprint="4" * 64,
                        payload={
                            "mission_id": MISSION_ID,
                            "study_id": replay_study_id,
                            "spec": sibling_spec,
                            "work_fingerprint": sibling_fingerprint,
                        },
                        event_stream=repair_stream,
                        event_sequence=1,
                        authority_sequence=5,
                        authority_event_id=f"{5:064x}",
                    ),
                    IndexRecord(
                        kind="job-completed",
                        record_id=repair_previous_completion_id,
                        subject=f"Job:{repair_previous_job_id}",
                        status="failed",
                        fingerprint="4" * 64,
                        payload={
                            "failure": {
                                "failure_signature": "3" * 64,
                                "minimum_reproduction_evidence": [],
                            },
                            "job_id": repair_previous_job_id,
                        },
                        event_stream=repair_stream,
                        event_sequence=2,
                        authority_sequence=6,
                        authority_event_id=f"{6:064x}",
                    ),
                )
            )
        self._put_many(tuple(base_records))
        condition = self._condition(ReplayResumeConditionKind.SAME_PROTOCOL_REPAIR)
        deferral = ReplayDeferral(
            obligation_id=self.obligation.identity,
            basis=ReplayDeferralBasis(
                kind=ReplayDeferralBasisKind.STUDY_DIAGNOSIS,
                record_id=replay_diagnosis_id,
                subject_id=replay_study_id,
            ),
            reason_codes=("not_evaluable",),
            resume_conditions=(condition,),
            execution_binding=ReplayDeferralExecutionBinding(
                portfolio_decision_id=decision_id,
                replay_study_id=replay_study_id,
                replay_executable_id=replay_executable_id,
                replay_study_close_record_id=replay_close_id,
                study_diagnosis_id=replay_diagnosis_id,
            ),
        )
        self._store_deferral(deferral)
        repaired_job_id = "job:" + "a" * 64
        repaired_completion_id = "b" * 64
        repaired_spec = _repair_spec(
            repaired_executable_id or replay_executable_id,
            repaired_implementation,
            validation_plan_hash=(
                repaired_validation_plan_hash or validation_plan_hash
            ),
            changed_cause_proof_hash=changed_cause,
        )
        repaired_spec["input_hashes"] = [repair_input_hash]
        self._put_many(
            (
                IndexRecord(
                    kind="job-declared",
                    record_id=repaired_job_id,
                    subject=f"Job:{repaired_job_id}",
                    status="declared",
                    fingerprint="a" * 64,
                    payload={
                        "mission_id": MISSION_ID,
                        "study_id": repaired_study_id or replay_study_id,
                        "spec": repaired_spec,
                        "work_fingerprint": (
                            exact_work_fingerprint
                            if not sibling_job
                            else repair_stream.removeprefix("job-attempt:")
                        ),
                    },
                    event_stream=repair_stream,
                    event_sequence=3,
                    authority_sequence=11,
                    authority_event_id=f"{11:064x}",
                ),
                IndexRecord(
                    kind="job-completed",
                    record_id=repaired_completion_id,
                    subject=f"Job:{repaired_job_id}",
                    status="success",
                    fingerprint="a" * 64,
                    payload={"job_id": repaired_job_id},
                    event_stream=repair_stream,
                    event_sequence=4,
                    authority_sequence=12,
                    authority_event_id=f"{12:064x}",
                ),
            )
        )
        evidence = ReplayResumeEvidence(
            obligation_id=self.obligation.identity,
            deferral_id=deferral.identity,
            resume_condition_id=condition.identity,
            trigger_record_id=repaired_completion_id,
        )

        def provenance(*_records: IndexRecord) -> ReplayRepairProvenance:
            return ReplayRepairProvenance(
                basis_kind=(
                    ReplayRepairBasisKind.SCIENTIFIC_INVALIDITY
                    if scientific_invalidity
                    else ReplayRepairBasisKind.OPERATIONAL_FAILURE
                ),
                prior_completion_record_id=previous_completion_id,
                study_diagnosis_id=replay_diagnosis_id,
                protocol_id=PROTOCOL_ID,
                validation_plan_hash=validation_plan_hash,
                criterion_ids=condition.criterion_ids,
                previous_implementation_identity=previous_implementation,
                repaired_implementation_identity=repaired_implementation,
                changed_cause_proof_hash=changed_cause,
                prior_failure_signature=(
                    None if scientific_invalidity else failure_signature
                ),
                invalid_criterion_ids=(
                    (self.obligation.criterion_ids[1],)
                    if scientific_invalidity
                    else ()
                ),
                new_evidence_hashes=(repaired_implementation,),
            )

        return evidence, provenance

    def test_same_protocol_repair_accepts_exact_diagnosed_lineage(self) -> None:
        evidence, provenance = self._seed_same_protocol_repair()
        records, _, _ = prepare_resume(
            self.index,
            mission_id=MISSION_ID,
            resumes=(evidence,),
            repair_provenance=provenance,
        )
        self.assertEqual(records[0].status, "pending")

    def test_same_protocol_repair_accepts_exact_scientific_invalidity(self) -> None:
        evidence, provenance = self._seed_same_protocol_repair(
            scientific_invalidity=True
        )
        records, _, _ = prepare_resume(
            self.index,
            mission_id=MISSION_ID,
            resumes=(evidence,),
            repair_provenance=provenance,
        )
        self.assertEqual(records[0].status, "pending")

    def test_same_protocol_repair_rejects_unrelated_sibling_job_pair(self) -> None:
        evidence, provenance = self._seed_same_protocol_repair(sibling_job=True)
        with self.assertRaisesRegex(ReplayTransitionError, "exact diagnosed"):
            prepare_resume(
                self.index,
                mission_id=MISSION_ID,
                resumes=(evidence,),
                repair_provenance=provenance,
            )

    def test_same_protocol_repair_rejects_other_executable_or_study(self) -> None:
        evidence, provenance = self._seed_same_protocol_repair(
            repaired_executable_id="executable:" + "2" * 64,
            repaired_study_id="STU-UNRELATED-REPAIR",
        )
        with self.assertRaisesRegex(ReplayTransitionError, "exact diagnosed"):
            prepare_resume(
                self.index,
                mission_id=MISSION_ID,
                resumes=(evidence,),
                repair_provenance=provenance,
            )

    def test_same_protocol_repair_rejects_different_mechanism_family(self) -> None:
        evidence, provenance = self._seed_same_protocol_repair(
            repaired_validation_plan_hash="2" * 64,
        )
        with self.assertRaisesRegex(ReplayTransitionError, "exact diagnosed"):
            prepare_resume(
                self.index,
                mission_id=MISSION_ID,
                resumes=(evidence,),
                repair_provenance=provenance,
            )

    def test_in_progress_deferral_requires_exact_close_and_diagnosis(self) -> None:
        replay_study_id = "STU-REPLAY-RUN"
        decision_id = "decision:" + "a" * 64
        replay_executable_id = "executable:" + "b" * 64
        replay_close_id = "c" * 64
        replay_diagnosis_id = "diagnosis:" + "d" * 64
        replay_job_id = "job:" + "e" * 64
        replay_completion_id = "f" * 64
        progress = IndexRecord(
            kind="historical-replay-obligation-progress",
            record_id="historical-replay-progress:" + "0" * 64,
            subject=f"Mission:{MISSION_ID}",
            status="in_progress",
            fingerprint="0" * 64,
            payload={
                "binding": {
                    "obligation_ids": [self.obligation.identity],
                    "portfolio_decision_id": decision_id,
                    "replay_executable_id": replay_executable_id,
                    "replay_study_id": replay_study_id,
                    "schema": "replay_execution_binding.v1",
                },
                "obligation_id": self.obligation.identity,
                "prior_status": "pending",
            },
            event_stream=(
                f"historical-replay-obligation:{self.obligation.identity}"
            ),
            event_sequence=2,
            authority_sequence=20,
            authority_event_id=f"{20:064x}",
        )
        self._put_many(
            (
                progress,
                IndexRecord(
                    kind="study-open",
                    record_id=replay_study_id,
                    subject=f"Mission:{MISSION_ID}",
                    status="open",
                    fingerprint="1" * 64,
                    payload={
                        "mission_id": MISSION_ID,
                        "portfolio_decision_id": decision_id,
                        "replay_obligation_ids": [self.obligation.identity],
                    },
                    authority_sequence=20,
                    authority_event_id=f"{20:064x}",
                ),
                IndexRecord(
                    kind="trial",
                    record_id=replay_executable_id,
                    subject="Batch:BAT-REPLAY-RUN",
                    status="evaluated",
                    fingerprint="b" * 64,
                    payload={
                        "executable": _typed_replay_executable(
                            self.obligation.original_executable_id
                        ),
                        "replay_obligation_ids": [self.obligation.identity],
                        "study_id": replay_study_id,
                    },
                    authority_sequence=20,
                    authority_event_id=f"{20:064x}",
                ),
                IndexRecord(
                    kind="study-close",
                    record_id=replay_close_id,
                    subject=f"Study:{replay_study_id}",
                    status="not_evaluable",
                    fingerprint="c" * 64,
                    payload={"outcome": "not_evaluable"},
                    authority_sequence=21,
                    authority_event_id=f"{21:064x}",
                ),
                IndexRecord(
                    kind="job-declared",
                    record_id=replay_job_id,
                    subject=f"Job:{replay_job_id}",
                    status="declared",
                    fingerprint="e" * 64,
                    payload={
                        "mission_id": MISSION_ID,
                        "study_id": replay_study_id,
                        "spec": {
                            "evidence_subject": {
                                "kind": "Executable",
                                "id": replay_executable_id,
                            }
                        },
                    },
                    authority_sequence=20,
                    authority_event_id=f"{20:064x}",
                ),
                IndexRecord(
                    kind="job-completed",
                    record_id=replay_completion_id,
                    subject=f"Job:{replay_job_id}",
                    status="success",
                    fingerprint="e" * 64,
                    payload={"job_id": replay_job_id},
                    authority_sequence=21,
                    authority_event_id=f"{21:064x}",
                ),
                IndexRecord(
                    kind="study-diagnosis",
                    record_id=replay_diagnosis_id,
                    subject=f"Study:{replay_study_id}",
                    status="not_identifiable",
                    fingerprint="d" * 64,
                    payload={
                        "evidence_basis": [
                            {
                                "kind": "job-completed",
                                "record_id": replay_completion_id,
                            },
                            {
                                "kind": "study-close",
                                "record_id": replay_close_id,
                            },
                        ],
                        "mission_id": MISSION_ID,
                        "study_close_record_id": replay_close_id,
                        "study_id": replay_study_id,
                    },
                    authority_sequence=22,
                    authority_event_id=f"{22:064x}",
                ),
            )
        )
        condition = self._condition(
            ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL
        )
        exact = ReplayDeferral(
            obligation_id=self.obligation.identity,
            basis=ReplayDeferralBasis(
                kind=ReplayDeferralBasisKind.STUDY_DIAGNOSIS,
                record_id=replay_diagnosis_id,
                subject_id=replay_study_id,
            ),
            reason_codes=("not_evaluable",),
            resume_conditions=(condition,),
            execution_binding=ReplayDeferralExecutionBinding(
                portfolio_decision_id=decision_id,
                replay_study_id=replay_study_id,
                replay_executable_id=replay_executable_id,
                replay_study_close_record_id=replay_close_id,
                study_diagnosis_id=replay_diagnosis_id,
            ),
        )
        records, _, _ = prepare_deferral(
            self.index,
            mission_id=MISSION_ID,
            deferrals=(exact,),
        )
        self.assertEqual(records[0].status, "deferred")
        wrong_close = replace(
            exact,
            execution_binding=replace(
                exact.execution_binding,
                replay_study_close_record_id="1" * 64,
            ),
        )
        with self.assertRaisesRegex(
            ReplayTransitionError, "trial, close, and diagnosis"
        ):
            prepare_deferral(
                self.index,
                mission_id=MISSION_ID,
                deferrals=(wrong_close,),
            )


if __name__ == "__main__":
    unittest.main()
