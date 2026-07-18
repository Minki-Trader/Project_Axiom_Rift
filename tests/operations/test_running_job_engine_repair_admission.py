from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.running_job import (
    RunningJobAuthority,
    RunningJobAuthorityIntegrityError,
    RunningJobExecution,
    running_job_authority_dependency_paths,
)
from axiom_rift.operations.repair_validation import (
    ATTEMPT_TRACE_SCHEMA,
    REGISTERED_REPAIR_AUTHORITY_SCHEMA,
    TRACE_SCHEMA,
    build_repair_attempt_validation_context,
    repair_validation_binding,
    require_stored_repair_attempt_validation,
)
from axiom_rift.storage.index import IndexRecord
from replay_repair_fixture_factory import _RepairFixture, _repair_fixture
from replay_repair_fixture_mutations import _add_terminal_cause_repair
from replay_repair_fixture_records import (
    ENGINE_ENTRY_RECORD_ID,
    JOB_ID,
    JOB_PERMIT_ID,
    NEW_IMPLEMENTATION,
    START_RECORD_ID,
)


CALLABLE_IDENTITY = "fixture.replay:run"
AUTHORIZATION_HASH = "0" * 64
CONSUMED_RECORD_ID = "f" * 64


def _upgrade_first_attempt_with_scope_swapped_trace(
    fixture: _RepairFixture,
) -> None:
    attempt_payload = fixture.attempt.payload
    mission_id = fixture.declaration.payload["mission_id"]
    protocol = "fixture.engine.repair.validation.v1"
    result_hash = "6" * 64
    validation_plan_hash = "7" * 64
    validator_id = "validator:" + "8" * 64
    context = build_repair_attempt_validation_context(
        cause_hash=attempt_payload["cause_hash"],
        changed_dimension=attempt_payload["changed_dimension"],
        explanation=attempt_payload["explanation"],
        failure_observation=attempt_payload["failure_observation"],
        implementation_proof_hash=attempt_payload[
            "implementation_proof_hash"
        ],
        job_hash=attempt_payload["job_hash"],
        job_id=attempt_payload["job_id"],
        new_basis_hash=attempt_payload["new_basis_hash"],
        new_evidence_hashes=attempt_payload["new_evidence_hashes"],
        outcome=attempt_payload["outcome"],
        previous_basis_hash=attempt_payload["previous_basis_hash"],
        prior_attempt_record_id=attempt_payload["prior_attempt_record_id"],
        repair_id=attempt_payload["repair_id"],
        reproduction_evidence_hashes=attempt_payload[
            "reproduction_evidence_hashes"
        ],
        resume_action=attempt_payload["resume_action"],
    )
    binding = repair_validation_binding(
        verification_kind="attempt",
        mission_id=mission_id,
        protocol=protocol,
        context=context,
        artifact_roles=(("validation_result", result_hash),),
    )
    registered_trace = {
        "authority_scope": "fixture_only",
        "evidence_subject": {
            "id": attempt_payload["repair_id"],
            "kind": "Repair",
        },
        "facts": {
            "binding": binding,
            "cause_resolved": True,
            "failure_reproduced": False,
            "material_change": True,
        },
        "protocol": protocol,
        "registry_trace": {
            "declared_artifact_count": 2,
            "opened_artifact_count": 2,
            "validator_id": validator_id,
        },
        "result_artifact_hashes": [result_hash],
        "schema": TRACE_SCHEMA,
        "validation_plan_hash": validation_plan_hash,
        "verification_kind": "attempt",
        "verdict": "passed",
    }
    trace_body = {
        "receipts": [
            {
                "receipt_hash": attempt_payload[
                    "verification_evidence_hashes"
                ][0],
                **registered_trace,
            }
        ],
        "schema": ATTEMPT_TRACE_SCHEMA,
        "verification_count": 1,
    }
    repair_validation = {
        **trace_body,
        "trace_sha256": sha256(canonical_bytes(trace_body)).hexdigest(),
    }
    marked_open = replace(
        fixture.repair_open,
        payload={
            **fixture.repair_open.payload,
            "repair_authority_schema": REGISTERED_REPAIR_AUTHORITY_SCHEMA,
            "repair_validation_scope": "production",
        },
    )
    prospective_attempt_payload = {
        **attempt_payload,
        "attempt_fingerprint": canonical_digest(
            domain="repair-attempt-intervention",
            payload={
                "changed_dimension": attempt_payload["changed_dimension"],
                "implementation_proof_hash": attempt_payload[
                    "implementation_proof_hash"
                ],
                "new_basis_hash": attempt_payload["new_basis_hash"],
                "new_evidence_hashes": attempt_payload[
                    "new_evidence_hashes"
                ],
                "outcome": attempt_payload["outcome"],
                "verification_evidence_hashes": attempt_payload[
                    "verification_evidence_hashes"
                ],
            },
        ),
        "repair_authority_schema": REGISTERED_REPAIR_AUTHORITY_SCHEMA,
        "repair_validation": repair_validation,
    }
    require_stored_repair_attempt_validation(
        attempt_payload=prospective_attempt_payload,
        repair_validation=repair_validation,
        mission_id=mission_id,
        expected_scope="fixture_only",
    )
    attempt_identity_payload = {
        key: value
        for key, value in prospective_attempt_payload.items()
        if key not in {"scientific_failure_delta", "scientific_trial_delta"}
    }
    prospective_attempt = replace(
        fixture.attempt,
        record_id=canonical_digest(
            domain="repair-attempt",
            payload=attempt_identity_payload,
        ),
        payload=prospective_attempt_payload,
    )
    prospective_close_payload = {
        **fixture.repair_close.payload,
        "attempt_record_id": prospective_attempt.record_id,
        "repair_authority_schema": REGISTERED_REPAIR_AUTHORITY_SCHEMA,
        "repair_validation": repair_validation,
    }
    close_identity_payload = {
        "proof": prospective_close_payload["changed_cause_proof_hash"],
        "repair_authority_schema": REGISTERED_REPAIR_AUTHORITY_SCHEMA,
        "repair_id": prospective_close_payload["repair_id"],
        "repair_validation": repair_validation,
        "semantic_equivalence_validation": prospective_close_payload[
            "semantic_equivalence_validation"
        ],
    }
    prospective_close = replace(
        fixture.repair_close,
        record_id=canonical_digest(
            domain="repair-close",
            payload=close_identity_payload,
        ),
        payload=prospective_close_payload,
    )
    fixture.replace_records(
        (
            (fixture.repair_open, marked_open),
            (fixture.attempt, prospective_attempt),
            (fixture.repair_close, prospective_close),
        )
    )


def _engine_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    prospective_trace: str = "historical",
) -> tuple[RunningJobAuthority, RunningJobExecution, _RepairFixture]:
    fixture = _repair_fixture(tmp_path)
    _add_terminal_cause_repair(fixture)
    if prospective_trace not in {
        "historical",
        "missing",
        "scope_swapped",
        "tampered",
    }:
        raise AssertionError(prospective_trace)
    if prospective_trace == "scope_swapped":
        _upgrade_first_attempt_with_scope_swapped_trace(fixture)
    if prospective_trace != "historical":
        replacements = []
        if prospective_trace != "scope_swapped":
            marked_open = replace(
                fixture.repair_open,
                payload={
                    **fixture.repair_open.payload,
                    "repair_authority_schema": (
                        REGISTERED_REPAIR_AUTHORITY_SCHEMA
                    ),
                    "repair_validation_scope": "production",
                },
            )
            replacements.append((fixture.repair_open, marked_open))
        if prospective_trace == "tampered":
            malformed_trace = {
                "receipts": [],
                "schema": ATTEMPT_TRACE_SCHEMA,
                "trace_sha256": "0" * 64,
                "verification_count": 0,
            }
            replacements.extend(
                (
                    (
                        fixture.attempt,
                        replace(
                            fixture.attempt,
                            payload={
                                **fixture.attempt.payload,
                                "repair_authority_schema": (
                                    REGISTERED_REPAIR_AUTHORITY_SCHEMA
                                ),
                                "repair_validation": malformed_trace,
                            },
                        ),
                    ),
                    (
                        fixture.repair_close,
                        replace(
                            fixture.repair_close,
                            payload={
                                **fixture.repair_close.payload,
                                "repair_authority_schema": (
                                    REGISTERED_REPAIR_AUTHORITY_SCHEMA
                                ),
                                "repair_validation": malformed_trace,
                            },
                        ),
                    ),
                )
            )
        if replacements:
            fixture.replace_records(tuple(replacements))
    execution = RunningJobExecution(
        job_id=JOB_ID,
        job_hash=JOB_ID.removeprefix("job:"),
        start_record_id=START_RECORD_ID,
        job_permit_id=JOB_PERMIT_ID,
    )
    permit_payload = {
        "actions": ["start_job"],
        "audit_revision": 10,
        "expires_at_utc": "2027-01-01T00:00:00Z",
        "input_hash": execution.job_hash,
        "issued_at_utc": "2026-01-01T00:00:00Z",
        "kind": "job",
        "one_shot": True,
        "permit_id": execution.job_permit_id,
        "schema": "typed_permit",
        "scope": ["job"],
        "signature": "1" * 64,
        "subject": {
            "authorization_epoch": 1,
            "authorization_hash": AUTHORIZATION_HASH,
            "kind": "Job",
            "subject_id": execution.job_id,
        },
    }
    issued = IndexRecord(
        kind="permit-issued",
        record_id=execution.job_permit_id,
        subject=f"Permit:{execution.job_permit_id}",
        status="issued",
        fingerprint=execution.job_permit_id,
        payload=permit_payload,
        event_stream=f"permit:{execution.job_permit_id}",
        event_sequence=1,
        authority_sequence=11,
        authority_event_id="1" * 64,
        authority_offset=0,
    )
    consumed = IndexRecord(
        kind="permit-consumed",
        record_id=CONSUMED_RECORD_ID,
        subject=f"Permit:{execution.job_permit_id}",
        status="consumed",
        fingerprint=execution.job_permit_id,
        payload={
            "one_shot": True,
            "permit_id": execution.job_permit_id,
        },
        event_stream=f"permit:{execution.job_permit_id}",
        event_sequence=2,
        authority_sequence=12,
        authority_event_id="2" * 64,
        authority_offset=0,
    )
    started = IndexRecord(
        kind="job-started",
        record_id=execution.start_record_id,
        subject=f"Job:{execution.job_id}",
        status="running",
        fingerprint=execution.job_hash,
        payload={
            "job_permit_id": execution.job_permit_id,
            "runtime": None,
        },
        authority_sequence=12,
        authority_event_id=consumed.authority_event_id,
        authority_offset=1,
    )
    engine_entry = IndexRecord(
        kind="job-engine-entry",
        record_id=ENGINE_ENTRY_RECORD_ID,
        subject=f"Job:{execution.job_id}",
        status="validated",
        fingerprint=execution.job_hash,
        payload={
            "execution": execution.payload(),
            "permit_consumption_record_id": consumed.record_id,
        },
        authority_sequence=12,
        authority_event_id=consumed.authority_event_id,
        authority_offset=2,
    )
    fixture.add_records((issued, consumed, started, engine_entry))
    control = {
        "scientific": {
            "active_job": {
                "engine_entry_record_id": engine_entry.record_id,
                "hash": execution.job_hash,
                "id": execution.job_id,
                "last_repair_resume_record_id": fixture.resume.record_id,
                "start_record_id": execution.start_record_id,
                "status": "running",
            }
        }
    }
    authority = RunningJobAuthority(tmp_path, foundation_root=tmp_path)

    @contextmanager
    def existing_lock():
        yield

    @contextmanager
    def open_index():
        yield fixture.index.read_only()

    monkeypatch.setattr(authority, "_existing_writer_lock", existing_lock)
    monkeypatch.setattr(authority, "_open_authoritative_index", open_index)
    monkeypatch.setattr(
        authority,
        "_require_stable_locked",
        lambda _index: control,
    )
    return authority, execution, fixture


def test_engine_admission_consumes_the_terminal_whole_repair_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, execution, fixture = _engine_authority(tmp_path, monkeypatch)

    binding = authority.verify_running_job_execution(
        execution,
        expected_callable_identity=CALLABLE_IDENTITY,
    )

    assert binding["effective_implementation_identity"] == NEW_IMPLEMENTATION
    assert binding["implementation_repair_record_id"] == (
        fixture.resume.payload["repair_close_record_id"]
    )
    assert binding["repair_resume_record_id"] == fixture.resume.record_id


@pytest.mark.parametrize(
    "prospective_trace",
    ("missing", "scope_swapped", "tampered"),
)
def test_engine_admission_rejects_unproven_prospective_repair_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prospective_trace: str,
) -> None:
    authority, execution, _fixture = _engine_authority(
        tmp_path,
        monkeypatch,
        prospective_trace=prospective_trace,
    )

    with pytest.raises(RunningJobAuthorityIntegrityError):
        authority.verify_running_job_execution(
            execution,
            expected_callable_identity=CALLABLE_IDENTITY,
        )


def test_engine_authority_identity_binds_the_whole_repair_projection() -> None:
    projection_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "axiom_rift"
        / "operations"
        / "running_job_repair_projection.py"
    ).resolve()

    assert projection_path in running_job_authority_dependency_paths()
