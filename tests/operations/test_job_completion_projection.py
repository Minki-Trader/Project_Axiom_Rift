from __future__ import annotations

from types import SimpleNamespace
from typing import Any
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.job_completion_projection import (
    JobCompletionProjectionError,
    JobCompletionProjectionIntegrityError,
    project_job_completion,
)
from axiom_rift.storage.index import IndexRecord


JOB_ID = "job:" + "1" * 64
JOB_HASH = "2" * 64
COMPLETION_ID = "3" * 64
SUCCESS_FINGERPRINT = "4" * 64
MISSION_ID = "MIS-PROJECTION"
EXECUTABLE_ID = "executable:" + "5" * 64
SOURCE_ID = "source:" + "6" * 64
HOLDOUT_ID = "holdout:" + "7" * 64
DEPENDENCY_ID = "external-dependency:" + "8" * 64
OUTPUT_NAME = "evidence/job-projection.json"
OUTPUT_HASH = "9" * 64
_MISSING = object()


def _record(**values: Any) -> IndexRecord:
    return IndexRecord(**values)


class _Index:
    def __init__(self, *, dependency_sequence: int | None = None) -> None:
        self.dependency_sequence = dependency_sequence
        self.queries: list[str] = []

    def event_head(self, stream: str):
        self.queries.append(stream)
        if self.dependency_sequence is None:
            return None
        return SimpleNamespace(sequence=self.dependency_sequence)


def _declaration(
    *,
    spec_updates: dict[str, Any] | None = None,
    batch_id: object = _MISSING,
    candidate_context: object = _MISSING,
    return_next_action: object = _MISSING,
    payload_updates: dict[str, Any] | None = None,
) -> IndexRecord:
    spec: dict[str, Any] = {
        "expected_outputs": [OUTPUT_NAME],
        "output_classes": {OUTPUT_NAME: "durable_evidence"},
    }
    if spec_updates:
        spec.update(spec_updates)
    payload: dict[str, Any] = {
        "mission_id": MISSION_ID,
        "spec": spec,
        "success_fingerprint": SUCCESS_FINGERPRINT,
        "work_fingerprint": "a" * 64,
    }
    if batch_id is not _MISSING:
        payload["batch_id"] = batch_id
    if candidate_context is not _MISSING:
        payload["candidate_execution_context"] = candidate_context
    if return_next_action is not _MISSING:
        payload["return_next_action"] = return_next_action
    if payload_updates:
        payload.update(payload_updates)
    return IndexRecord(
        kind="job-declared",
        record_id=JOB_ID,
        subject=f"Job:{JOB_ID}",
        status="declared",
        fingerprint=JOB_HASH,
        payload=payload,
    )


def _completion(
    *,
    status: str = "success",
    scientific: object = None,
    engineering_disposition: object = None,
    failure: object = None,
    external: object = None,
) -> IndexRecord:
    return IndexRecord(
        kind="job-completed",
        record_id=COMPLETION_ID,
        subject=f"Job:{JOB_ID}",
        status=status,
        fingerprint=JOB_HASH,
        payload={
            "candidate_execution_context": None,
            "engineering_disposition": engineering_disposition,
            "external": external,
            "failure": failure,
            "job_id": JOB_ID,
            "output_classes": {OUTPUT_NAME: "durable_evidence"},
            "outputs": {OUTPUT_NAME: OUTPUT_HASH},
            "repair_resume_record_id": None,
            "runtime": None,
            "scientific": scientific,
            "source": None,
            "start_record_id": "b" * 64,
        },
        event_stream="job-attempt:" + "a" * 64,
        event_sequence=3,
    )


def _project(
    *,
    declaration: IndexRecord,
    completion: IndexRecord,
    active_holdout: dict[str, Any] | None = None,
    pre_reveal: bool = False,
    engineering_fixture: bool = False,
    index: _Index | None = None,
):
    return project_job_completion(
        index=_Index() if index is None else index,
        declaration=declaration,
        completion=completion,
        active_holdout=active_holdout,
        pre_reveal_holdout_engineering_gap=pre_reveal,
        engineering_fixture=engineering_fixture,
        record_builder=_record,
    )


def _engineering_disposition() -> dict[str, Any]:
    return {
        "disposition": "requires_scientific_change",
        "resume_condition": "register an exact changed Executable",
        "successor_scope": {
            "changed_variables": ["implementation semantics"],
        },
    }


def _candidate_context() -> dict[str, Any]:
    return {"executable_id": EXECUTABLE_ID}


def _revealed_holdout() -> dict[str, Any]:
    return {
        "candidate_id": "candidate:" + "c" * 64,
        "executable_id": EXECUTABLE_ID,
        "holdout_id": HOLDOUT_ID,
        "job_id": JOB_ID,
        "status": "revealed_pending_evaluation",
    }


class JobCompletionProjectionTests(unittest.TestCase):
    def test_route_matrix_preserves_exact_precedence_and_actions(self) -> None:
        return_action = {"kind": "freeze_batch", "study_id": "STU-PROJECTION"}
        judgement = {
            "completion_record_id": COMPLETION_ID,
            "job_id": JOB_ID,
            "kind": "judge_job_evidence",
        }
        engineering = _engineering_disposition()
        cases = (
            {
                "name": "batch",
                "declaration": _declaration(batch_id="BAT-PROJECTION"),
                "completion": _completion(),
                "engineering_fixture": False,
                "expected": judgement,
            },
            {
                "name": "component_parity",
                "declaration": _declaration(
                    spec_updates={"component_parity_binding": {"typed": True}}
                ),
                "completion": _completion(),
                "engineering_fixture": False,
                "expected": judgement,
            },
            {
                "name": "candidate_success",
                "declaration": _declaration(
                    candidate_context=_candidate_context(),
                    spec_updates={
                        "runtime_binding": {"evidence_depth": "execution_proof"}
                    },
                ),
                "completion": _completion(),
                "engineering_fixture": False,
                "expected": {
                    "executable_id": EXECUTABLE_ID,
                    "kind": "plan_candidate_bound_evidence",
                },
            },
            {
                "name": "candidate_runtime_gap",
                "declaration": _declaration(
                    candidate_context=_candidate_context(),
                    spec_updates={
                        "runtime_binding": {"evidence_depth": "execution_proof"}
                    },
                ),
                "completion": _completion(
                    status="failed",
                    engineering_disposition=engineering,
                    failure={"repair_disposition_hash": "d" * 64},
                ),
                "engineering_fixture": False,
                "expected": {
                    "completion_record_id": COMPLETION_ID,
                    "disposition": engineering["disposition"],
                    "executable_id": EXECUTABLE_ID,
                    "job_id": JOB_ID,
                    "kind": "resolve_candidate_engineering_gap",
                    "resume_condition": engineering["resume_condition"],
                    "successor_scope": engineering["successor_scope"],
                    "target_id": "execution_proof",
                    "work_context": "runtime",
                },
            },
            {
                "name": "source_success_inside_batch",
                "declaration": _declaration(
                    batch_id="BAT-PROJECTION",
                    spec_updates={
                        "source_binding": {"source_contract_id": SOURCE_ID}
                    },
                ),
                "completion": _completion(),
                "engineering_fixture": False,
                "expected": {
                    "completion_record_id": COMPLETION_ID,
                    "job_id": JOB_ID,
                    "kind": "record_source_eligibility",
                    "resume_next_action": judgement,
                    "source_contract_id": SOURCE_ID,
                },
            },
            {
                "name": "source_success_standalone",
                "declaration": _declaration(
                    return_next_action=return_action,
                    spec_updates={
                        "source_binding": {"source_contract_id": SOURCE_ID}
                    },
                ),
                "completion": _completion(),
                "engineering_fixture": False,
                "expected": {
                    "completion_record_id": COMPLETION_ID,
                    "job_id": JOB_ID,
                    "kind": "record_source_eligibility",
                    "resume_next_action": return_action,
                    "source_contract_id": SOURCE_ID,
                },
            },
            {
                "name": "source_failure_standalone",
                "declaration": _declaration(
                    return_next_action=return_action,
                    spec_updates={
                        "source_binding": {"source_contract_id": SOURCE_ID}
                    },
                ),
                "completion": _completion(
                    status="failed",
                    failure={"failure_kind": "engineering"},
                ),
                "engineering_fixture": False,
                "expected": return_action,
            },
            {
                "name": "source_candidate_gap",
                "declaration": _declaration(
                    candidate_context=_candidate_context(),
                    spec_updates={
                        "source_binding": {"source_contract_id": SOURCE_ID}
                    },
                ),
                "completion": _completion(
                    status="failed",
                    engineering_disposition=engineering,
                    failure={"repair_disposition_hash": "d" * 64},
                ),
                "engineering_fixture": False,
                "expected": {
                    "completion_record_id": COMPLETION_ID,
                    "disposition": engineering["disposition"],
                    "executable_id": EXECUTABLE_ID,
                    "job_id": JOB_ID,
                    "kind": "resolve_candidate_engineering_gap",
                    "resume_condition": engineering["resume_condition"],
                    "successor_scope": engineering["successor_scope"],
                    "target_id": SOURCE_ID,
                    "work_context": "source",
                },
            },
            {
                "name": "external",
                "declaration": _declaration(
                    spec_updates={
                        "external_dependency_binding": {
                            "dependency_id": DEPENDENCY_ID,
                            "recovery_path_id": "path-001",
                        }
                    }
                ),
                "completion": _completion(
                    status="failed",
                    external={"verdict": "failed"},
                ),
                "engineering_fixture": False,
                "expected": {
                    "completion_record_id": COMPLETION_ID,
                    "job_id": JOB_ID,
                    "kind": "judge_external_dependency_evidence",
                },
            },
            {
                "name": "engineering_fixture_return",
                "declaration": _declaration(return_next_action=return_action),
                "completion": _completion(status="failed"),
                "engineering_fixture": True,
                "expected": return_action,
            },
        )
        for case in cases:
            with self.subTest(case["name"]):
                projection = _project(
                    declaration=case["declaration"],
                    completion=case["completion"],
                    engineering_fixture=case["engineering_fixture"],
                )
                self.assertEqual(projection.next_action, case["expected"])

    def test_holdout_matrix_is_first_and_does_not_mutate_input(self) -> None:
        active_holdout = _revealed_holdout()
        original_holdout = canonical_bytes(active_holdout)
        declaration = _declaration(
            batch_id="BAT-PROJECTION",
            candidate_context=_candidate_context(),
            spec_updates={
                "component_parity_binding": {"typed": True},
                "external_dependency_binding": {
                    "dependency_id": DEPENDENCY_ID,
                    "recovery_path_id": "path-001",
                },
                "holdout_binding": {"holdout_id": HOLDOUT_ID},
                "runtime_binding": {"evidence_depth": "confirmation"},
                "source_binding": {"source_contract_id": SOURCE_ID},
            },
        )
        declaration_before = canonical_bytes(declaration.payload)
        completion = _completion(
            scientific={"verdict": "passed"},
            external={"verdict": "passed"},
        )
        completion_before = canonical_bytes(completion.payload)

        projection = _project(
            declaration=declaration,
            completion=completion,
            active_holdout=active_holdout,
        )

        self.assertEqual(
            projection.next_action,
            {
                "completion_record_id": COMPLETION_ID,
                "holdout_id": HOLDOUT_ID,
                "job_id": JOB_ID,
                "kind": "record_holdout_evaluation",
            },
        )
        self.assertEqual(
            projection.active_holdout_evaluation,
            {
                **active_holdout,
                "completion_record_id": COMPLETION_ID,
                "status": "evaluation_completed_pending_disposition",
            },
        )
        self.assertEqual(canonical_bytes(active_holdout), original_holdout)
        self.assertEqual(canonical_bytes(declaration.payload), declaration_before)
        self.assertEqual(canonical_bytes(completion.payload), completion_before)

    def test_holdout_engineering_routes_and_gap_record_are_exact(self) -> None:
        engineering = _engineering_disposition()
        failure = {"repair_disposition_hash": "d" * 64}
        cases = (
            {
                "name": "revealed",
                "active": _revealed_holdout(),
                "pre_reveal": False,
                "expected_kind": "dispose_revealed_holdout_engineering_gap",
                "expected_status": "engineering_gap_pending_disposition",
                "expected_records": (),
            },
            {
                "name": "pre_reveal",
                "active": None,
                "pre_reveal": True,
                "expected_kind": "resolve_candidate_engineering_gap",
                "expected_status": None,
                "expected_records": ("holdout-evaluation-operational-gap",),
            },
        )
        for case in cases:
            with self.subTest(case["name"]):
                declaration = _declaration(
                    candidate_context=_candidate_context(),
                    spec_updates={"holdout_binding": {"holdout_id": HOLDOUT_ID}},
                )
                completion = _completion(
                    status="failed",
                    engineering_disposition=engineering,
                    failure=failure,
                )
                projection = _project(
                    declaration=declaration,
                    completion=completion,
                    active_holdout=case["active"],
                    pre_reveal=case["pre_reveal"],
                )
                self.assertEqual(
                    projection.next_action["kind"], case["expected_kind"]
                )
                self.assertEqual(
                    tuple(item.kind for item in projection.supplemental_records),
                    case["expected_records"],
                )
                if case["expected_status"] is None:
                    self.assertIsNone(projection.active_holdout_evaluation)
                    gap_payload = {
                        "completion_record_id": COMPLETION_ID,
                        "engineering_disposition_hash": "d" * 64,
                        "holdout_id": HOLDOUT_ID,
                        "job_id": JOB_ID,
                        "scientific_failure_delta": 0,
                        "scientific_trial_delta": 0,
                        "sealed_holdout_preserved": True,
                    }
                    self.assertEqual(
                        projection.supplemental_records[0],
                        IndexRecord(
                            kind="holdout-evaluation-operational-gap",
                            record_id=canonical_digest(
                                domain="holdout-evaluation-operational-gap",
                                payload=gap_payload,
                            ),
                            subject=f"Holdout:{HOLDOUT_ID}",
                            status="pre_reveal_engineering_gap",
                            fingerprint=HOLDOUT_ID.removeprefix("holdout:"),
                            payload=gap_payload,
                        ),
                    )
                else:
                    assert projection.active_holdout_evaluation is not None
                    self.assertEqual(
                        projection.active_holdout_evaluation["status"],
                        case["expected_status"],
                    )
                    self.assertEqual(
                        projection.active_holdout_evaluation[
                            "completion_record_id"
                        ],
                        COMPLETION_ID,
                    )

    def test_success_cache_and_external_attempt_identity_payload_and_order(self) -> None:
        binding = {
            "dependency_id": DEPENDENCY_ID,
            "exact_resume_action": "choose_next_initiative_or_terminal",
            "recovery_path_id": "path-001",
        }
        source_authority = {"closure_hash": "e" * 64}
        external_development = {"prefix_hash": "f" * 64}
        observed_development = {"prefix_hash": "0" * 64}
        declaration = _declaration(
            spec_updates={"external_dependency_binding": binding},
            payload_updates={
                "external_observed_development_binding": external_development,
                "observed_development_binding": observed_development,
                "source_closure_authority": source_authority,
            },
        )
        completion = _completion(external={"verdict": "passed"})
        index = _Index(dependency_sequence=7)

        projection = _project(
            declaration=declaration,
            completion=completion,
            index=index,
        )

        self.assertEqual(
            tuple(item.kind for item in projection.supplemental_records),
            ("job-success-cache", "external-dependency-attempt"),
        )
        cache, attempt = projection.supplemental_records
        self.assertEqual(
            cache,
            IndexRecord(
                kind="job-success-cache",
                record_id=SUCCESS_FINGERPRINT,
                subject=f"Mission:{MISSION_ID}",
                status="reusable",
                fingerprint=JOB_HASH,
                payload={
                    "candidate_execution_context": None,
                    "completion_record_id": COMPLETION_ID,
                    "expected_outputs": [OUTPUT_NAME],
                    "external_observed_development_binding": external_development,
                    "implementation_source_authority": {
                        "authority": source_authority,
                        "schema": "job_implementation_source_binding.v1",
                    },
                    "job_id": JOB_ID,
                    "mission_id": MISSION_ID,
                    "observed_development_binding": observed_development,
                    "output_classes": {OUTPUT_NAME: "durable_evidence"},
                },
            ),
        )
        attempt_payload = {
            "completion_record_id": COMPLETION_ID,
            "external": {"verdict": "passed"},
            **binding,
        }
        self.assertEqual(
            attempt,
            IndexRecord(
                kind="external-dependency-attempt",
                record_id=canonical_digest(
                    domain="external-dependency-attempt",
                    payload={
                        "completion_record_id": COMPLETION_ID,
                        "dependency_id": DEPENDENCY_ID,
                        "recovery_path_id": "path-001",
                    },
                ),
                subject=f"Mission:{MISSION_ID}",
                status="available",
                fingerprint=DEPENDENCY_ID,
                payload=attempt_payload,
                event_stream=f"external-dependency:{DEPENDENCY_ID}",
                event_sequence=8,
            ),
        )
        self.assertEqual(index.queries, [f"external-dependency:{DEPENDENCY_ID}"])

    def test_external_attempt_status_matrix(self) -> None:
        binding = {
            "dependency_id": DEPENDENCY_ID,
            "recovery_path_id": "path-001",
        }
        cases = (
            ("success", {"verdict": "passed"}, "available"),
            ("failed", {"verdict": "failed"}, "external_unavailable"),
            (
                "failed",
                {"verdict": "not_evaluable"},
                "external_unresolved",
            ),
            ("failed", None, "local_failure"),
        )
        for outcome, external, expected in cases:
            with self.subTest(outcome=outcome, external=external):
                projection = _project(
                    declaration=_declaration(
                        spec_updates={"external_dependency_binding": binding}
                    ),
                    completion=_completion(
                        status=outcome,
                        external=external,
                    ),
                )
                attempt = next(
                    item
                    for item in projection.supplemental_records
                    if item.kind == "external-dependency-attempt"
                )
                self.assertEqual(attempt.status, expected)

    def test_holdout_gap_precedes_external_attempt(self) -> None:
        declaration = _declaration(
            candidate_context=_candidate_context(),
            spec_updates={
                "external_dependency_binding": {
                    "dependency_id": DEPENDENCY_ID,
                    "recovery_path_id": "path-001",
                },
                "holdout_binding": {"holdout_id": HOLDOUT_ID},
            },
        )
        projection = _project(
            declaration=declaration,
            completion=_completion(
                status="failed",
                engineering_disposition=_engineering_disposition(),
                failure={"repair_disposition_hash": "d" * 64},
            ),
            pre_reveal=True,
        )
        self.assertEqual(
            tuple(item.kind for item in projection.supplemental_records),
            (
                "holdout-evaluation-operational-gap",
                "external-dependency-attempt",
            ),
        )

    def test_error_classification_matrix(self) -> None:
        cases = (
            {
                "name": "no_consumer",
                "declaration": _declaration(),
                "completion": _completion(status="failed"),
                "error": JobCompletionProjectionError,
                "message": "typed operational consumer",
            },
            {
                "name": "source_return_lost",
                "declaration": _declaration(
                    spec_updates={
                        "source_binding": {"source_contract_id": SOURCE_ID}
                    }
                ),
                "completion": _completion(),
                "error": JobCompletionProjectionIntegrityError,
                "message": "source Job lost its exact return action",
            },
            {
                "name": "candidate_context_malformed",
                "declaration": _declaration(
                    candidate_context={"executable_id": None}
                ),
                "completion": _completion(status="failed"),
                "error": JobCompletionProjectionIntegrityError,
                "message": "candidate Job completion context is malformed",
            },
            {
                "name": "candidate_gap_without_runtime",
                "declaration": _declaration(
                    candidate_context=_candidate_context()
                ),
                "completion": _completion(
                    status="failed",
                    engineering_disposition=_engineering_disposition(),
                ),
                "error": JobCompletionProjectionError,
                "message": "no typed work context",
            },
        )
        for case in cases:
            with self.subTest(case["name"]):
                with self.assertRaises(case["error"]) as caught:
                    _project(
                        declaration=case["declaration"],
                        completion=case["completion"],
                    )
                self.assertIs(type(caught.exception), case["error"])
                self.assertIn(case["message"], str(caught.exception))


if __name__ == "__main__":
    unittest.main()
