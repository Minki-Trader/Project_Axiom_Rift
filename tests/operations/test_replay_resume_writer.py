from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.permits import PermitAuthority
from axiom_rift.operations.replay_projection import initial_obligation_record
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.research.historical_adjudication import ReplayPriority
from axiom_rift.research.replay_obligation import (
    ReplayDeferral,
    ReplayDeferralBasis,
    ReplayDeferralBasisKind,
    ReplayDeferralExecutionBinding,
    ReplayResumeCondition,
    ReplayResumeConditionKind,
    ReplayResumeEvidence,
    derive_historical_replay_obligation,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


REPO_ROOT = Path(__file__).resolve().parents[2]
MISSION_ID = "MIS-REPLAY-RESUME-WRITER"
STUDY_ID = "STU-REPLAY-RESUME-WRITER"
PROTOCOL_ID = "python.source.exact_replay.v1"
ORIGINAL_AXIS_ID = "AXS-REPLAY-RESUME-WRITER"
ORIGINAL_AXIS_IDENTITY = "axis:" + "0" * 64
ORIGINAL_EXECUTABLE = {"schema": "original_fixture.v1"}
ORIGINAL_EXECUTABLE_ID = "executable:" + canonical_digest(
    domain="executable",
    payload=ORIGINAL_EXECUTABLE,
)


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


def _repair_work_fingerprint(spec: dict[str, object]) -> str:
    fields = (
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
            "work": {name: spec.get(name) for name in fields},
        },
    )


class ReplayResumeWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.writer = StateWriter(
            Path(self.temporary.name),
            permit_authority=PermitAuthority(b"p" * 32),
            clock=lambda: "2026-07-14T00:00:00Z",
            engineering_fixture=True,
            foundation_root=REPO_ROOT,
        )
        self.writer.initialize_ready()
        self.writer.open_mission(
            mission_id=MISSION_ID,
            goal={
                "objective": "exercise durable replay resume",
                "scope": ["isolated", "engineering_fixture"],
                "terminal_contract": "no_scientific_terminal",
            },
            operation_id="open-replay-resume-mission",
        )

    @staticmethod
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
            "study_id": STUDY_ID,
            "validation_plan_hash": "6" * 64,
        }

    def _seed_pending_obligation(self):
        payload = self._adjudication_payload()
        obligation = derive_historical_replay_obligation(
            governing_mission_id=MISSION_ID,
            historical_adjudication_id="historical-adjudication:" + "7" * 64,
            adjudication_payload=payload,
        )
        original_job_id = "job:" + "8" * 64
        diagnosis_id = "diagnosis:" + "9" * 64
        records = (
            IndexRecord(
                kind="historical-scientific-adjudication",
                record_id=obligation.historical_adjudication_id,
                subject=f"Study:{STUDY_ID}",
                status="replay_required",
                fingerprint="7" * 64,
                payload=payload,
            ),
            initial_obligation_record(obligation),
            IndexRecord(
                kind="study-open",
                record_id=STUDY_ID,
                subject=f"Study:{STUDY_ID}",
                status="open",
                fingerprint="a" * 64,
                payload={
                    "mission_id": MISSION_ID,
                    "portfolio_axis_id": ORIGINAL_AXIS_ID,
                    "portfolio_axis_identity": ORIGINAL_AXIS_IDENTITY,
                },
            ),
            IndexRecord(
                kind="study-close",
                record_id=obligation.original_study_close_record_id,
                subject=f"Study:{STUDY_ID}",
                status="not_evaluable",
                fingerprint="b" * 64,
                payload={"outcome": "not_evaluable"},
            ),
            IndexRecord(
                kind="job-declared",
                record_id=original_job_id,
                subject=f"Job:{original_job_id}",
                status="declared",
                fingerprint="8" * 64,
                payload={
                    "mission_id": MISSION_ID,
                    "study_id": STUDY_ID,
                    "spec": {
                        "evidence_subject": {
                            "kind": "Executable",
                            "id": obligation.original_executable_id,
                        }
                    },
                },
            ),
            IndexRecord(
                kind="job-completed",
                record_id=obligation.original_completion_record_id,
                subject=f"Job:{original_job_id}",
                status="not_evaluable",
                fingerprint="2" * 64,
                payload={
                    "job_id": original_job_id,
                    "scientific": {
                        "executable_id": obligation.original_executable_id
                    },
                },
            ),
            IndexRecord(
                kind="trial",
                record_id=obligation.original_executable_id,
                subject="Batch:BAT-ORIGINAL-WRITER",
                status="evaluated",
                fingerprint=(
                    obligation.original_executable_id.removeprefix(
                        "executable:"
                    )
                ),
                payload={
                    "executable": ORIGINAL_EXECUTABLE,
                    "mission_id": MISSION_ID,
                    "portfolio_axis_id": ORIGINAL_AXIS_ID,
                    "portfolio_axis_identity": ORIGINAL_AXIS_IDENTITY,
                    "study_id": STUDY_ID,
                },
            ),
            IndexRecord(
                kind="study-diagnosis",
                record_id=diagnosis_id,
                subject=f"Study:{STUDY_ID}",
                status="not_identifiable",
                fingerprint="9" * 64,
                payload={
                    "evidence_basis": [
                        {
                            "kind": "job-completed",
                            "record_id": obligation.original_completion_record_id,
                        },
                        {
                            "kind": "study-close",
                            "record_id": obligation.original_study_close_record_id,
                        },
                    ],
                    "mission_id": MISSION_ID,
                    "study_close_record_id": obligation.original_study_close_record_id,
                    "study_id": STUDY_ID,
                },
            ),
        )

        def prepare(current, _index):
            body = self.writer._body(current)
            body["next_action"] = {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": MISSION_ID,
                "pending_replay_obligation_ids": [obligation.identity],
                "required_replay_priority": ReplayPriority.P1.value,
            }
            return body, records, {"seeded": obligation.identity}

        self.writer._commit(
            event_kind="replay_resume_fixture_seeded",
            operation_id="seed-pending-replay-obligation",
            subject=f"Mission:{MISSION_ID}",
            payload={"obligation_id": obligation.identity},
            prepare=prepare,
        )
        return obligation, diagnosis_id

    def _seed_development_trigger(self, material_id: str) -> None:
        authority_id = "0" * 64
        shared = {
            "material_content_sha256": "1" * 64,
            "material_identity": material_id,
            "material_receipt_hash": "2" * 64,
            "mission_id": MISSION_ID,
            "split_identity": "3" * 64,
        }
        records = (
            IndexRecord(
                kind="post-holdout-development",
                record_id=authority_id,
                subject=f"Material:{material_id}",
                status="accepted",
                fingerprint="2" * 64,
                payload=shared,
            ),
            IndexRecord(
                kind="development-material",
                record_id=material_id,
                subject=f"Mission:{MISSION_ID}",
                status="accepted",
                fingerprint="2" * 64,
                payload={**shared, "post_holdout_development_id": authority_id},
            ),
        )

        def prepare(current, _index):
            return self.writer._body(current), records, {"material_id": material_id}

        self.writer._commit(
            event_kind="development_material_fixture_seeded",
            operation_id="seed-new-development-material",
            subject=f"Mission:{MISSION_ID}",
            payload={"material_id": material_id},
            prepare=prepare,
        )

    def _implementation_identity(self, label: str) -> tuple[str, str]:
        source = self.writer.evidence.finalize(
            f"{label} exact replay implementation".encode("ascii")
        )
        manifest = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "artifact_hashes": [source.sha256],
                    "callable_identity": "python:tests.exact_replay_repair",
                    "protocol": PROTOCOL_ID,
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        return manifest.sha256, source.sha256

    def _seed_same_protocol_writer_case(
        self,
        *,
        scientific_invalidity: bool = False,
        forged_changed_cause: bool = False,
    ) -> ReplayResumeEvidence:
        obligation, _ = self._seed_pending_obligation()
        replay_study_id = "STU-REPLAY-REPAIR-WRITER"
        decision_id = "decision:" + "a" * 64
        replay_executable_id = "executable:" + "b" * 64
        replay_close_id = "c" * 64
        replay_diagnosis_id = "diagnosis:" + "d" * 64
        previous_job_id = "job:" + "e" * 64
        previous_completion_id = "f" * 64
        repaired_job_id = "job:" + "0" * 64
        repaired_completion_id = "1" * 64
        failure_signature = "2" * 64
        previous_implementation, _ = self._implementation_identity("previous")
        repaired_implementation, repaired_source = self._implementation_identity(
            "repaired"
        )
        plan = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "criteria": [
                        {"criterion_id": criterion_id}
                        for criterion_id in obligation.criterion_ids
                    ],
                    "executable_id": replay_executable_id,
                    "mission_id": MISSION_ID,
                    "schema": "scientific_validation_plan.v2",
                }
            )
        )
        previous_spec: dict[str, object] = {
            "callable_identity": "python:tests.exact_replay_repair",
            "evidence_subject": {
                "kind": "Executable",
                "id": replay_executable_id,
            },
            "implementation_identity": previous_implementation,
            "input_hashes": ["3" * 64],
            "scientific_binding": {"validation_plan_hash": plan.sha256},
        }
        work_fingerprint = _repair_work_fingerprint(previous_spec)
        stream = f"job-attempt:{work_fingerprint}"
        previous_payload: dict[str, object] = {
            "job_id": previous_job_id,
        }
        if scientific_invalidity:
            previous_payload["scientific"] = {
                "adjudication": {
                    "criteria": [
                        {
                            "comparison_state": "passed",
                            "criterion_id": obligation.criterion_ids[0],
                            "scientific_state": "supported",
                        }
                    ],
                    "state": "not_evaluable",
                }
            }
        else:
            previous_payload["failure"] = {
                "failure_signature": failure_signature,
                "minimum_reproduction_evidence": [],
            }
        records = (
            IndexRecord(
                kind="historical-replay-obligation-progress",
                record_id="historical-replay-progress:" + "4" * 64,
                subject=f"Mission:{MISSION_ID}",
                status="in_progress",
                fingerprint="4" * 64,
                payload={
                    "binding": {
                        "obligation_ids": [obligation.identity],
                        "portfolio_decision_id": decision_id,
                        "replay_executable_id": replay_executable_id,
                        "replay_study_id": replay_study_id,
                        "schema": "replay_execution_binding.v1",
                    },
                    "obligation_id": obligation.identity,
                    "prior_status": "pending",
                },
                event_stream=(
                    f"historical-replay-obligation:{obligation.identity}"
                ),
                event_sequence=2,
            ),
            IndexRecord(
                kind="study-open",
                record_id=replay_study_id,
                subject=f"Mission:{MISSION_ID}",
                status="open",
                fingerprint="5" * 64,
                payload={
                    "mission_id": MISSION_ID,
                    "portfolio_decision_id": decision_id,
                    "replay_obligation_ids": [obligation.identity],
                },
            ),
            IndexRecord(
                kind="trial",
                record_id=replay_executable_id,
                subject="Batch:BAT-REPLAY-REPAIR-WRITER",
                status="evaluated",
                fingerprint="b" * 64,
                payload={
                    "executable": _typed_replay_executable(
                        obligation.original_executable_id
                    ),
                    "replay_obligation_ids": [obligation.identity],
                    "study_id": replay_study_id,
                },
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
                    "work_fingerprint": work_fingerprint,
                },
                event_stream=stream,
                event_sequence=1,
            ),
            IndexRecord(
                kind="job-completed",
                record_id=previous_completion_id,
                subject=f"Job:{previous_job_id}",
                status=("success" if scientific_invalidity else "failed"),
                fingerprint="e" * 64,
                payload=previous_payload,
                event_stream=stream,
                event_sequence=2,
            ),
            IndexRecord(
                kind="study-close",
                record_id=replay_close_id,
                subject=f"Study:{replay_study_id}",
                status="not_evaluable",
                fingerprint="c" * 64,
                payload={"outcome": "not_evaluable"},
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
                    "evidence_state": "not_identifiable",
                    "mission_id": MISSION_ID,
                    "study_close_record_id": replay_close_id,
                    "study_id": replay_study_id,
                },
            ),
        )

        def seed_progress(current, _index):
            return self.writer._body(current), records, {
                "replay_executable_id": replay_executable_id
            }

        self.writer._commit(
            event_kind="replay_repair_progress_fixture_seeded",
            operation_id="seed-replay-repair-progress",
            subject=f"Mission:{MISSION_ID}",
            payload={"replay_executable_id": replay_executable_id},
            prepare=seed_progress,
        )
        condition = ReplayResumeCondition(
            kind=ReplayResumeConditionKind.SAME_PROTOCOL_REPAIR,
            protocol_id=PROTOCOL_ID,
            original_executable_ids=(obligation.original_executable_id,),
            criterion_ids=obligation.criterion_ids,
        )
        deferral = ReplayDeferral(
            obligation_id=obligation.identity,
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
        self.writer.defer_historical_replay_obligations(
            deferrals=(deferral,),
            operation_id="defer-replay-repair",
        )
        if scientific_invalidity:
            changed_manifest = {
                "changed_dimension": "implementation",
                "explanation": "repair exact invalid replay computation",
                "invalid_criterion_ids": [obligation.criterion_ids[1]],
                "new_evidence_hashes": [
                    repaired_implementation,
                    repaired_source,
                ],
                "new_implementation_identity": repaired_implementation,
                "previous_implementation_identity": previous_implementation,
                "prior_completion_record_id": previous_completion_id,
                "schema": "replay_scientific_repair.v1",
                "study_diagnosis_id": replay_diagnosis_id,
                "validation_plan_hash": plan.sha256,
            }
        else:
            changed_manifest = {
                "changed_dimension": "implementation",
                "explanation": "repair exact failed replay implementation",
                "new_evidence_hashes": [
                    repaired_implementation,
                    repaired_source,
                ],
                "new_implementation_identity": repaired_implementation,
                "previous_implementation_identity": previous_implementation,
                "prior_failure_signature": failure_signature,
                "schema": "job_changed_cause.v1",
            }
        changed_proof = self.writer.evidence.finalize(
            canonical_bytes(changed_manifest)
        ).sha256
        repaired_spec = {
            **previous_spec,
            "changed_cause_proof_hash": (
                "a" * 64 if forged_changed_cause else changed_proof
            ),
            "implementation_identity": repaired_implementation,
        }
        repair_declaration = IndexRecord(
            kind="job-declared",
            record_id=repaired_job_id,
            subject=f"Job:{repaired_job_id}",
            status="declared",
            fingerprint="0" * 64,
            payload={
                "mission_id": MISSION_ID,
                "study_id": replay_study_id,
                "spec": repaired_spec,
                "work_fingerprint": work_fingerprint,
            },
            event_stream=stream,
            event_sequence=3,
        )

        def seed_repair_declaration(current, _index):
            return self.writer._body(current), (repair_declaration,), {
                "job_id": repaired_job_id
            }

        self.writer._commit(
            event_kind="replay_repair_declaration_fixture_seeded",
            operation_id="seed-replay-repair-declaration",
            subject=f"Mission:{MISSION_ID}",
            payload={"job_id": repaired_job_id},
            prepare=seed_repair_declaration,
        )
        repair_completion = IndexRecord(
            kind="job-completed",
            record_id=repaired_completion_id,
            subject=f"Job:{repaired_job_id}",
            status="success",
            fingerprint="0" * 64,
            payload={"job_id": repaired_job_id},
            event_stream=stream,
            event_sequence=4,
        )

        def seed_repair_completion(current, _index):
            return self.writer._body(current), (repair_completion,), {
                "completion_record_id": repaired_completion_id
            }

        self.writer._commit(
            event_kind="replay_repair_success_fixture_seeded",
            operation_id="seed-replay-repair-success",
            subject=f"Mission:{MISSION_ID}",
            payload={"completion_record_id": repaired_completion_id},
            prepare=seed_repair_completion,
        )
        return ReplayResumeEvidence(
            obligation_id=obligation.identity,
            deferral_id=deferral.identity,
            resume_condition_id=condition.identity,
            trigger_record_id=repaired_completion_id,
        )

    def test_resume_is_durable_idempotent_and_restores_scheduler(self) -> None:
        obligation, diagnosis_id = self._seed_pending_obligation()
        condition = ReplayResumeCondition(
            kind=ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL,
            protocol_id=PROTOCOL_ID,
            original_executable_ids=(obligation.original_executable_id,),
            criterion_ids=obligation.criterion_ids,
        )
        deferral = ReplayDeferral(
            obligation_id=obligation.identity,
            basis=ReplayDeferralBasis(
                kind=ReplayDeferralBasisKind.STUDY_DIAGNOSIS,
                record_id=diagnosis_id,
                subject_id=STUDY_ID,
            ),
            reason_codes=("not_evaluable",),
            resume_conditions=(condition,),
        )
        self.writer.defer_historical_replay_obligations(
            deferrals=(deferral,),
            operation_id="defer-replay-obligation",
        )
        material_id = "f" * 64
        self._seed_development_trigger(material_id)
        evidence = ReplayResumeEvidence(
            obligation_id=obligation.identity,
            deferral_id=deferral.identity,
            resume_condition_id=condition.identity,
            trigger_record_id=material_id,
        )
        before = self.writer.read_control()
        result = self.writer.resume_historical_replay_obligations(
            resumes=(evidence,),
            operation_id="resume-replay-obligation",
        )
        after = self.writer.read_control()

        self.assertFalse(result.reused)
        self.assertEqual(before["scientific"], after["scientific"])
        self.assertEqual(
            after["next_action"]["pending_replay_obligation_ids"],
            [obligation.identity],
        )
        self.assertEqual(
            after["next_action"]["required_replay_priority"],
            ReplayPriority.P1.value,
        )
        self.assertEqual(result.result["scientific_claim_delta"], 0)
        self.assertEqual(result.result["scientific_trial_delta"], 0)
        with LocalIndex(self.writer.index_path) as index:
            head = index.event_head(
                f"historical-replay-obligation:{obligation.identity}"
            )
            self.assertIsNotNone(head)
            assert head is not None
            self.assertEqual(head.record_kind, "historical-replay-obligation-resume")
            projected = index.get(head.record_kind, head.record_id)
            self.assertIsNotNone(projected)
            assert projected is not None
            self.assertEqual(projected.status, "pending")

        reused = self.writer.resume_historical_replay_obligations(
            resumes=(evidence,),
            operation_id="resume-replay-obligation",
        )
        self.assertTrue(reused.reused)
        with self.assertRaisesRegex(
            TransitionError, "idempotency key reused with different input"
        ):
            self.writer.resume_historical_replay_obligations(
                resumes=(replace(evidence, trigger_record_id="e" * 64),),
                operation_id="resume-replay-obligation",
            )

    def test_exact_failed_same_protocol_repair_resumes(self) -> None:
        evidence = self._seed_same_protocol_writer_case()
        result = self.writer.resume_historical_replay_obligations(
            resumes=(evidence,),
            operation_id="resume-exact-failed-replay-repair",
        )
        self.assertEqual(result.result["scientific_claim_delta"], 0)
        self.assertEqual(result.result["scientific_trial_delta"], 0)

    def test_exact_scientifically_invalid_success_repair_resumes(self) -> None:
        evidence = self._seed_same_protocol_writer_case(
            scientific_invalidity=True
        )
        result = self.writer.resume_historical_replay_obligations(
            resumes=(evidence,),
            operation_id="resume-exact-scientific-replay-repair",
        )
        self.assertEqual(result.result["scientific_claim_delta"], 0)
        self.assertEqual(result.result["scientific_trial_delta"], 0)

    def test_forged_changed_cause_hash_cannot_resume(self) -> None:
        evidence = self._seed_same_protocol_writer_case(
            forged_changed_cause=True
        )
        with self.assertRaisesRegex(
            TransitionError, "changed-cause proof is unavailable"
        ):
            self.writer.resume_historical_replay_obligations(
                resumes=(evidence,),
                operation_id="reject-forged-replay-repair",
            )


if __name__ == "__main__":
    unittest.main()
