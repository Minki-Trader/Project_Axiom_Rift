from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.operations.completion_validity_projection import (
    CompletionValidityProjectionError,
    completion_validity_invalidation_record,
    completion_validity_stream,
    current_completion_validity_invalidation,
    validate_completion_validity_invalidation_binding,
)
from axiom_rift.operations.evidence_scope_projection import (
    effective_completion_evidence_scope,
)
from axiom_rift.research.historical_scientific_validity import (
    AUTHORITY_DELTA_ZERO,
    DecisionPredicateActivationState,
    HistoricalScientificValidityInvalidation,
    JobBindingKind,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


MISSION_ID = "MIS-VALIDITY"
STUDY_ID = "STU-REUSED-EXECUTABLE"
ORIGINAL_STUDY_ID = "STU-ORIGINAL-REGISTRATION"
COMPLETION_ID = "1" * 64
JOB_ID = "job:" + "2" * 64
EXECUTABLE_ID = "executable:" + "3" * 64
CLOSE_ID = "4" * 64
PLAN_HASH = "5" * 64
MEASUREMENT_HASH = "6" * 64
RESULT_HASH = "7" * 64
IMPLEMENTATION_HASHES = ("8" * 64, "9" * 64)
AUTHORITY_EVENT_ID = "a" * 64
AUTHORITY_SEQUENCE = 41
AUTHORITY_OFFSET = 700


def _invalidation(
    *,
    job_id: str = JOB_ID,
    executable_id: str = EXECUTABLE_ID,
) -> HistoricalScientificValidityInvalidation:
    return HistoricalScientificValidityInvalidation(
        study_id=STUDY_ID,
        study_close_record_id=CLOSE_ID,
        job_id=job_id,
        job_binding_kind=JobBindingKind.DECLARATION,
        job_binding_record_id=job_id,
        completion_record_id=COMPLETION_ID,
        executable_id=executable_id,
        validation_plan_hash=PLAN_HASH,
        measurement_artifact_hash=MEASUREMENT_HASH,
        result_manifest_hash=RESULT_HASH,
        component_implementation_hashes=IMPLEMENTATION_HASHES,
        clock_contract="clock:completed_m5_v1",
        cost_contract="cost:bar_spread_proxy_v1",
        predicate_evaluated=True,
        activation_state=(
            DecisionPredicateActivationState.EVALUATED_NOT_ACTIVATED
        ),
        predicate_activation_count=0,
        affected_claim_ids=(
            "after_cost_fixed_lot_economics",
            "causal_feature_and_execution_validity",
        ),
        affected_evidence_modes=("cost_and_execution",),
        affected_criterion_ids=(
            "B01-positive-native-cost",
            "C03-decision-time-causality",
        ),
        audit_finding_id="AX-SPREAD-TIME-001",
        audit_artifact_hash="b" * 64,
    )


def _base_records() -> tuple[IndexRecord, ...]:
    scientific = {
        "adjudication": {
            "claims": [
                {"claim_id": "after_cost_fixed_lot_economics"},
                {"claim_id": "causal_feature_and_execution_validity"},
            ],
            "criteria": [
                {"criterion_id": "B01-positive-native-cost"},
                {"criterion_id": "C03-decision-time-causality"},
            ],
        },
        "candidate_eligible": False,
        "claims": [
            "after_cost_fixed_lot_economics",
            "causal_feature_and_execution_validity",
        ],
        "executed_evidence_modes": [
            "causal_contrast",
            "cost_and_execution",
        ],
        "executable_id": EXECUTABLE_ID,
        "measurement_artifact_hashes": [MEASUREMENT_HASH],
        "result_manifest_hash": RESULT_HASH,
        "scientific_eligible": True,
        "validation_plan_hash": PLAN_HASH,
    }
    completion = IndexRecord(
        kind="job-completed",
        record_id=COMPLETION_ID,
        subject=f"Job:{JOB_ID}",
        status="success",
        fingerprint="c" * 64,
        payload={
            "job_id": JOB_ID,
            "outputs": {
                "scientific/plan.json": PLAN_HASH,
                "scientific/measurement.json": MEASUREMENT_HASH,
                "scientific/result.json": RESULT_HASH,
            },
            "scientific": scientific,
        },
    )
    return (
        IndexRecord(
            kind="study-open",
            record_id=STUDY_ID,
            subject=f"Study:{STUDY_ID}",
            status="open",
            fingerprint="d" * 64,
            payload={"mission_id": MISSION_ID},
        ),
        IndexRecord(
            kind="study-close",
            record_id=CLOSE_ID,
            subject=f"Study:{STUDY_ID}",
            status="preserved",
            fingerprint="e" * 64,
            payload={"outcome": "preserved"},
        ),
        IndexRecord(
            kind="trial",
            record_id=EXECUTABLE_ID,
            subject="Batch:BAT-ORIGINAL",
            status="evaluated",
            fingerprint=EXECUTABLE_ID.removeprefix("executable:"),
            payload={
                "mission_id": MISSION_ID,
                # Reuse is legitimate: registration occurred in another Study.
                "study_id": ORIGINAL_STUDY_ID,
                "executable": {
                    "clock_contract": "clock:completed_m5_v1",
                    "component_manifests": [
                        {
                            "implementation": (
                                "axiom_rift.research.example.one@sha256:"
                                + IMPLEMENTATION_HASHES[0]
                            )
                        },
                        {
                            "implementation": (
                                "axiom_rift.research.example.two@sha256:"
                                + IMPLEMENTATION_HASHES[1]
                            )
                        },
                    ],
                    "cost_contract": "cost:bar_spread_proxy_v1",
                },
            },
        ),
        IndexRecord(
            kind="job-declared",
            record_id=JOB_ID,
            subject=f"Job:{JOB_ID}",
            status="declared",
            fingerprint="f" * 64,
            payload={
                "mission_id": MISSION_ID,
                "study_id": STUDY_ID,
                "spec": {
                    "evidence_subject": {
                        "id": EXECUTABLE_ID,
                        "kind": "Executable",
                    }
                },
            },
        ),
        completion,
    )


def _authority_records(
    invalidation: HistoricalScientificValidityInvalidation,
) -> tuple[IndexRecord, IndexRecord, IndexRecord]:
    raw = completion_validity_invalidation_record(invalidation, sequence=1)
    validity = replace(
        raw,
        authority_sequence=AUTHORITY_SEQUENCE,
        authority_event_id=AUTHORITY_EVENT_ID,
        authority_offset=AUTHORITY_OFFSET,
    )
    operation_id = "record-completion-validity-test"
    result = {
        "authority_delta": dict(AUTHORITY_DELTA_ZERO),
        "invalidations": [
            {
                "completion_record_id": invalidation.completion_record_id,
                "invalidation_record_id": invalidation.identity,
            }
        ],
    }
    operation = IndexRecord(
        kind="operation",
        record_id=operation_id,
        subject="Mission:" + MISSION_ID,
        status="success",
        fingerprint="0" * 64,
        payload={
            "event_kind": (
                "historical_scientific_validity_invalidations_recorded"
            ),
            "result": result,
        },
        authority_sequence=AUTHORITY_SEQUENCE,
        authority_event_id=AUTHORITY_EVENT_ID,
        authority_offset=AUTHORITY_OFFSET,
    )
    journal = IndexRecord(
        kind="journal-event",
        record_id=AUTHORITY_EVENT_ID,
        subject="Mission:" + MISSION_ID,
        status="historical_scientific_validity_invalidations_recorded",
        fingerprint=AUTHORITY_EVENT_ID,
        payload={"operation_id": operation_id},
        event_stream="control",
        event_sequence=AUTHORITY_SEQUENCE,
        authority_sequence=AUTHORITY_SEQUENCE,
        authority_event_id=AUTHORITY_EVENT_ID,
        authority_offset=AUTHORITY_OFFSET,
    )
    return operation, journal, validity


class CompletionValidityProjectionTests(unittest.TestCase):
    def test_cross_study_reuse_is_valid_and_current_head_removes_all_credit(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                index.put_many(_base_records())
                invalidation = _invalidation()
                # The Trial belongs to ORIGINAL_STUDY_ID, while the exact Job
                # declaration and completion bind the reused Executable here.
                validate_completion_validity_invalidation_binding(
                    index,
                    invalidation,
                )
                index.put_many(_authority_records(invalidation))
                head = current_completion_validity_invalidation(
                    index,
                    COMPLETION_ID,
                )
                assert head is not None
                self.assertEqual(head.invalidation_record_id, invalidation.identity)
                self.assertEqual(head.validity_stream_sequence, 1)
                self.assertEqual(head.authority_event_id, AUTHORITY_EVENT_ID)
                self.assertEqual(head.authority_sequence, AUTHORITY_SEQUENCE)
                self.assertEqual(head.completion_record_id, COMPLETION_ID)
                self.assertEqual(head.executable_id, EXECUTABLE_ID)
                self.assertEqual(
                    head.reason,
                    "decision_input_point_in_time_unproven",
                )
                completion = index.get("job-completed", COMPLETION_ID)
                assert completion is not None
                effective = effective_completion_evidence_scope(index, completion)
                self.assertEqual(effective.evidence_modes, ("audit_integrity",))
                self.assertEqual(effective.scientific_credit, 0)
                self.assertEqual(effective.economic_credit, 0)
                self.assertEqual(effective.candidate_credit, 0)
                self.assertEqual(effective.terminal_credit, 0)
                self.assertFalse(effective.scientific_eligible)
                self.assertFalse(effective.candidate_eligible)
                self.assertFalse(effective.negative_memory_authoritative)
                self.assertEqual(
                    effective.negative_memory_role,
                    "diagnostic_only",
                )
                self.assertIsNone(effective.overlay_record_id)
                self.assertEqual(
                    effective.invalidation_record_id,
                    invalidation.identity,
                )

    def test_unrelated_job_and_executable_mismatches_fail_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                unrelated_job_id = "job:" + "d" * 64
                index.put_many(
                    (
                        *_base_records(),
                        IndexRecord(
                            kind="job-declared",
                            record_id=unrelated_job_id,
                            subject=f"Job:{unrelated_job_id}",
                            status="declared",
                            fingerprint="d" * 64,
                            payload={
                                "mission_id": MISSION_ID,
                                "study_id": STUDY_ID,
                                "spec": {
                                    "evidence_subject": {
                                        "id": EXECUTABLE_ID,
                                        "kind": "Executable",
                                    }
                                },
                            },
                        ),
                    )
                )
                with self.assertRaisesRegex(
                    CompletionValidityProjectionError,
                    "another Job",
                ):
                    validate_completion_validity_invalidation_binding(
                        index,
                        _invalidation(job_id=unrelated_job_id),
                    )
                with self.assertRaisesRegex(
                    CompletionValidityProjectionError,
                    "artifact binding is not exact",
                ):
                    validate_completion_validity_invalidation_binding(
                        index,
                        _invalidation(executable_id="executable:" + "e" * 64),
                    )

    def test_caller_created_head_without_writer_event_is_not_authority(self) -> None:
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                invalidation = _invalidation()
                fake = replace(
                    completion_validity_invalidation_record(
                        invalidation,
                        sequence=1,
                    ),
                    authority_sequence=AUTHORITY_SEQUENCE,
                    authority_event_id=AUTHORITY_EVENT_ID,
                    authority_offset=AUTHORITY_OFFSET,
                )
                index.put_many((*_base_records(), fake))
                with self.assertRaisesRegex(
                    CompletionValidityProjectionError,
                    "same-event Writer authority",
                ):
                    current_completion_validity_invalidation(
                        index,
                        COMPLETION_ID,
                    )

    def test_same_event_writer_result_cannot_grant_nonzero_authority(self) -> None:
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                invalidation = _invalidation()
                operation, journal, validity = _authority_records(invalidation)
                bad_delta = dict(AUTHORITY_DELTA_ZERO)
                bad_delta["scientific"] = 1
                operation = replace(
                    operation,
                    payload={
                        "event_kind": (
                            "historical_scientific_validity_invalidations_recorded"
                        ),
                        "result": {
                            "authority_delta": bad_delta,
                            "invalidations": [
                                {
                                    "completion_record_id": COMPLETION_ID,
                                    "invalidation_record_id": invalidation.identity,
                                }
                            ],
                        },
                    },
                )
                index.put_many((*_base_records(), operation, journal, validity))
                with self.assertRaisesRegex(
                    CompletionValidityProjectionError,
                    "Writer result is malformed",
                ):
                    current_completion_validity_invalidation(
                        index,
                        COMPLETION_ID,
                    )

    def test_stream_key_rejects_non_digest_completion(self) -> None:
        with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
            completion_validity_stream("not-a-completion")


if __name__ == "__main__":
    unittest.main()
