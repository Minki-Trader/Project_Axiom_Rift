from __future__ import annotations

from dataclasses import replace
from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.repair_validation import (
    REGISTERED_REPAIR_AUTHORITY_SCHEMA,
)
from axiom_rift.operations.replay_implementation_repair_admission import (
    repair_admission_stream,
    repair_preflight_stream,
)
from axiom_rift.storage.index import IndexRecord
from replay_repair_fixture_factory import _RepairFixture
from replay_repair_fixture_records import (
    JOB_ID,
    MISSION_ID,
    NEW_IMPLEMENTATION,
    REGISTERED,
    REPRODUCTION_HASH,
    SCIENTIFIC_MODES,
    STUDY_ID,
    THIRD_IMPLEMENTATION,
    VERIFICATION_HASH,
    _completion_record,
    _content_record,
    _event_id,
    _judgment_record,
    _repair_attempt_and_close_records,
    _repair_attempt_fingerprint_record,
    _repair_open_record,
    _repair_semantic_validation,
    _request,
    _resume_record,
)

def _rehash_preflight(
    fixture: _RepairFixture,
    payload: dict[str, Any],
) -> None:
    preflight = _content_record(
        kind="job-implementation-preflight",
        prefix="job-implementation-preflight:",
        domain="replay-job-implementation-preflight",
        subject=fixture.preflight.subject,
        status="accepted",
        payload=payload,
        event_stream=fixture.preflight.event_stream,
        event_sequence=fixture.preflight.event_sequence,
        authority_sequence=fixture.preflight.authority_sequence or 24,
    )
    admission_payload = {
        **fixture.admission.payload,
        "recertification_preflight_id": preflight.record_id,
    }
    admission = _content_record(
        kind="replay-implementation-admission",
        prefix="replay-implementation-admission:",
        domain="replay-implementation-admission",
        subject=fixture.admission.subject,
        status="active",
        payload=admission_payload,
        event_stream=fixture.admission.event_stream,
        event_sequence=fixture.admission.event_sequence,
        authority_sequence=fixture.admission.authority_sequence or 24,
    )
    fixture.replace_records(
        ((fixture.preflight, preflight), (fixture.admission, admission))
    )


def _rehash_completion(
    fixture: _RepairFixture,
    scientific: object,
) -> None:
    completion = _completion_record(
        resume_record_id=fixture.resume.record_id,
        scientific=scientific,
    )
    judgment = _judgment_record(completion)
    fixture.replace_records(
        ((fixture.completion, completion), (fixture.judgment, judgment))
    )


def _add_failed_science_memory(fixture: _RepairFixture) -> IndexRecord:
    scientific = dict(fixture.completion.payload["scientific"])
    scientific["verdict"] = "failed"
    completion = _completion_record(
        resume_record_id=fixture.resume.record_id,
        scientific=scientific,
    )
    memory_payload = {
        "evidence_references": [completion.record_id],
        "executed_evidence_modes": list(SCIENTIFIC_MODES),
        "holdout_id": None,
        "mission_id": MISSION_ID,
        "portfolio_axis_id": None,
        "portfolio_axis_identity": None,
        "portfolio_snapshot_id": None,
        "reason": "the repaired production member failed its registered science",
        "reopen_condition": "reopen only with a newly registered causal basis",
        "scope": "repaired replay member",
        "study_id": STUDY_ID,
    }
    memory_id = "negative-memory:" + canonical_digest(
        domain="negative-memory",
        payload={
            "evidence_references": memory_payload["evidence_references"],
            "executable_identity": REGISTERED[0],
            "reason": memory_payload["reason"],
            "reopen_condition": memory_payload["reopen_condition"],
            "scope": memory_payload["scope"],
        },
    )
    memory = IndexRecord(
        kind="negative-memory",
        record_id=memory_id,
        subject=f"Executable:{REGISTERED[0]}",
        status="durable",
        fingerprint=REGISTERED[0],
        payload=memory_payload,
        authority_sequence=23,
        authority_event_id=_event_id(23),
        authority_offset=0,
    )
    judgment = _judgment_record(
        completion,
        authority_sequence=24,
        negative_memory_id=memory.record_id,
    )
    preflight = replace(
        fixture.preflight,
        authority_sequence=25,
        authority_event_id=_event_id(25),
    )
    admission = replace(
        fixture.admission,
        authority_sequence=25,
        authority_event_id=_event_id(25),
    )
    fixture.records.append(memory)
    fixture.replace_records(
        (
            (fixture.completion, completion),
            (fixture.judgment, judgment),
            (fixture.preflight, preflight),
            (fixture.admission, admission),
        )
    )
    return memory


def _replace_resume_payload(
    fixture: _RepairFixture,
    payload: dict[str, Any],
) -> None:
    resume = replace(
        fixture.resume,
        record_id=canonical_digest(
            domain="job-repaired-execution-resume",
            payload=payload,
        ),
        payload=payload,
    )
    completion = _completion_record(
        resume_record_id=resume.record_id,
        scientific=fixture.completion.payload["scientific"],
        authority_sequence=fixture.completion.authority_sequence or 22,
    )
    judgment = _judgment_record(
        completion,
        authority_sequence=fixture.judgment.authority_sequence or 23,
    )
    fixture.replace_records(
        (
            (fixture.resume, resume),
            (fixture.completion, completion),
            (fixture.judgment, judgment),
        )
    )


def _replace_attempt_payload(
    fixture: _RepairFixture,
    payload: dict[str, Any],
) -> None:
    identity_payload = dict(payload)
    identity_payload.pop("scientific_failure_delta", None)
    identity_payload.pop("scientific_trial_delta", None)
    attempt = replace(
        fixture.attempt,
        record_id=canonical_digest(
            domain="repair-attempt",
            payload=identity_payload,
        ),
        payload=payload,
    )
    close = replace(
        fixture.repair_close,
        payload={
            **fixture.repair_close.payload,
            "attempt_record_id": attempt.record_id,
        },
    )
    resume_payload = {
        **fixture.resume.payload,
        "repair_attempt_record_id": attempt.record_id,
    }
    resume = replace(
        fixture.resume,
        record_id=canonical_digest(
            domain="job-repaired-execution-resume",
            payload=resume_payload,
        ),
        payload=resume_payload,
    )
    completion = _completion_record(
        resume_record_id=resume.record_id,
        scientific=fixture.completion.payload["scientific"],
        authority_sequence=fixture.completion.authority_sequence or 22,
    )
    judgment = _judgment_record(
        completion,
        authority_sequence=fixture.judgment.authority_sequence or 23,
    )
    fixture.replace_records(
        (
            (fixture.attempt, attempt),
            (fixture.repair_close, close),
            (fixture.resume, resume),
            (fixture.completion, completion),
            (fixture.judgment, judgment),
        )
    )


def _prepend_failed_attempt(fixture: _RepairFixture) -> IndexRecord:
    failed_basis = "13579bdf02468ace" * 4
    changed_evidence = "2468ace013579bdf" * 4
    failed_identity_payload = {
        "attempt_proof_hash": "1" * 64,
        "cause_hash": fixture.repair_open.fingerprint,
        "changed_dimension": "cause",
        "explanation": "first changed-cause attempt did not repair the defect",
        "failure_observation": "the engineering defect reproduced",
        "implementation_proof_hash": None,
        "job_hash": JOB_ID.removeprefix("job:"),
        "job_id": JOB_ID,
        "new_basis_hash": failed_basis,
        "new_evidence_hashes": sorted((changed_evidence, failed_basis)),
        "outcome": "failed",
        "previous_basis_hash": fixture.repair_open.fingerprint,
        "prior_attempt_record_id": None,
        "repair_id": fixture.repair_open.record_id,
        "reproduction_evidence_hashes": [REPRODUCTION_HASH],
        "resume_action": "continue_batch",
        "schema": "running_job_repair_attempt.v1",
        "scientific_semantics_changed": False,
        "verification_evidence_hashes": [VERIFICATION_HASH],
    }
    failed = IndexRecord(
        kind="repair-attempt",
        record_id=canonical_digest(
            domain="repair-attempt",
            payload=failed_identity_payload,
        ),
        subject=f"Repair:{fixture.repair_open.record_id}",
        status="failed",
        fingerprint="1" * 64,
        payload={
            **failed_identity_payload,
            "scientific_failure_delta": 0,
            "scientific_trial_delta": 0,
        },
        event_stream=f"repair-attempt:{fixture.repair_open.record_id}",
        event_sequence=1,
        authority_sequence=19,
        authority_event_id=_event_id(19),
        authority_offset=0,
    )
    terminal_payload = {
        **fixture.attempt.payload,
        "previous_basis_hash": failed_basis,
        "prior_attempt_record_id": failed.record_id,
    }
    terminal_identity = dict(terminal_payload)
    terminal_identity.pop("scientific_failure_delta")
    terminal_identity.pop("scientific_trial_delta")
    terminal = replace(
        fixture.attempt,
        record_id=canonical_digest(
            domain="repair-attempt",
            payload=terminal_identity,
        ),
        payload=terminal_payload,
        event_sequence=2,
    )
    close = replace(
        fixture.repair_close,
        payload={
            **fixture.repair_close.payload,
            "attempt_record_id": terminal.record_id,
            "prior_attempt_record_id": failed.record_id,
        },
    )
    resume_payload = {
        **fixture.resume.payload,
        "repair_attempt_record_id": terminal.record_id,
    }
    resume = replace(
        fixture.resume,
        record_id=canonical_digest(
            domain="job-repaired-execution-resume",
            payload=resume_payload,
        ),
        payload=resume_payload,
    )
    completion = _completion_record(
        resume_record_id=resume.record_id,
        scientific=fixture.completion.payload["scientific"],
        authority_sequence=fixture.completion.authority_sequence or 22,
    )
    judgment = _judgment_record(
        completion,
        authority_sequence=fixture.judgment.authority_sequence or 23,
    )
    fixture.records.append(failed)
    fixture.replace_records(
        (
            (fixture.attempt, terminal),
            (fixture.repair_close, close),
            (fixture.resume, resume),
            (fixture.completion, completion),
            (fixture.judgment, judgment),
        )
    )
    return failed


def _add_second_implementation_repair(
    fixture: _RepairFixture,
    *,
    continuous: bool,
) -> None:
    opened = _repair_open_record(
        episode=2,
        predecessor_close_id=fixture.repair_close.record_id,
        authority_sequence=22,
        root_cause="second fixture implementation defect",
        registered_authority=(
            fixture.repair_open.payload.get("repair_authority_schema")
            == REGISTERED_REPAIR_AUTHORITY_SCHEMA
        ),
    )
    semantic_validation = _repair_semantic_validation(
        REGISTERED[0],
        repair_id=opened.record_id,
        old_implementation=NEW_IMPLEMENTATION,
        new_implementation=THIRD_IMPLEMENTATION,
        old_closure=("9" * 64 if continuous else "4" * 64),
        new_closure="7" * 64,
        old_source=("b" * 64 if continuous else "5" * 64),
        new_source="6" * 64,
    )
    attempt, close = _repair_attempt_and_close_records(
        opened=opened,
        previous_implementation=NEW_IMPLEMENTATION,
        next_implementation=THIRD_IMPLEMENTATION,
        semantic_validation=semantic_validation,
        event_sequence=2,
        authority_sequence=23,
        attempt_proof_hash="0" * 64,
    )
    attempt_fingerprint_record = _repair_attempt_fingerprint_record(attempt)
    resume = _resume_record(
        close,
        event_sequence=2,
        authority_sequence=24,
    )
    completion = _completion_record(
        resume_record_id=resume.record_id,
        scientific=fixture.completion.payload["scientific"],
        authority_sequence=25,
    )
    judgment = _judgment_record(completion, authority_sequence=26)
    request = _request(THIRD_IMPLEMENTATION)
    preflight_payload = {
        **fixture.preflight.payload,
        "artifact_hashes": [THIRD_IMPLEMENTATION],
        "implementation_identity": THIRD_IMPLEMENTATION,
        "repair_close_record_id": close.record_id,
        "request_identity": (
            "replay-job-implementation-preflight-request:"
            + canonical_digest(
                domain="replay-job-implementation-preflight-request",
                payload=request,
            )
        ),
    }
    preflight = _content_record(
        kind="job-implementation-preflight",
        prefix="job-implementation-preflight:",
        domain="replay-job-implementation-preflight",
        subject=fixture.preflight.subject,
        status="accepted",
        payload=preflight_payload,
        event_stream=repair_preflight_stream(close.record_id),
        event_sequence=1,
        authority_sequence=27,
    )
    admission_payload = {
        **fixture.admission.payload,
        "recertification_preflight_id": preflight.record_id,
        "repair_close_record_ids": [
            fixture.repair_close.record_id,
            close.record_id,
        ],
        "request": request,
        "trigger_repair_close_record_id": close.record_id,
    }
    admission = _content_record(
        kind="replay-implementation-admission",
        prefix="replay-implementation-admission:",
        domain="replay-implementation-admission",
        subject=fixture.admission.subject,
        status="active",
        payload=admission_payload,
        event_stream=fixture.admission.event_stream,
        event_sequence=fixture.admission.event_sequence,
        authority_sequence=27,
    )
    fixture.records.extend(
        (
            opened,
            *((attempt_fingerprint_record,) if attempt_fingerprint_record else ()),
            attempt,
            close,
            resume,
        )
    )
    fixture.replace_records(
        (
            (fixture.completion, completion),
            (fixture.judgment, judgment),
            (fixture.preflight, preflight),
            (fixture.admission, admission),
        )
    )
    fixture.resume = resume


def _add_terminal_cause_repair(fixture: _RepairFixture) -> None:
    opened = _repair_open_record(
        episode=2,
        predecessor_close_id=fixture.repair_close.record_id,
        authority_sequence=22,
        root_cause="post-implementation operational defect",
    )
    new_basis = "89abcdef01234567" * 4
    attempt_identity_payload = {
        "attempt_proof_hash": "9" * 64,
        "cause_hash": opened.fingerprint,
        "changed_dimension": "cause",
        "explanation": "repair the later operational cause without changing code",
        "failure_observation": None,
        "implementation_proof_hash": None,
        "job_hash": JOB_ID.removeprefix("job:"),
        "job_id": JOB_ID,
        "new_basis_hash": new_basis,
        "new_evidence_hashes": [new_basis],
        "outcome": "repaired",
        "previous_basis_hash": opened.fingerprint,
        "prior_attempt_record_id": None,
        "repair_id": opened.record_id,
        "reproduction_evidence_hashes": [REPRODUCTION_HASH],
        "resume_action": "continue_batch",
        "schema": "running_job_repair_attempt.v1",
        "scientific_semantics_changed": False,
        "verification_evidence_hashes": [VERIFICATION_HASH],
    }
    attempt = IndexRecord(
        kind="repair-attempt",
        record_id=canonical_digest(
            domain="repair-attempt",
            payload=attempt_identity_payload,
        ),
        subject=f"Repair:{opened.record_id}",
        status="repaired",
        fingerprint="9" * 64,
        payload={
            **attempt_identity_payload,
            "scientific_failure_delta": 0,
            "scientific_trial_delta": 0,
        },
        event_stream=f"repair-attempt:{opened.record_id}",
        event_sequence=1,
        authority_sequence=23,
        authority_event_id=_event_id(23),
        authority_offset=0,
    )
    close_id = canonical_digest(
        domain="repair-close",
        payload={"proof": "9" * 64, "repair_id": opened.record_id},
    )
    close = IndexRecord(
        kind="repair-close",
        record_id=close_id,
        subject=f"Job:{JOB_ID}",
        status="repaired",
        fingerprint="9" * 64,
        payload={
            "attempt_record_id": attempt.record_id,
            "changed_cause_proof_hash": "9" * 64,
            "changed_dimension": "cause",
            "effective_implementation_identity": NEW_IMPLEMENTATION,
            "implementation_changed": False,
            "job_id": JOB_ID,
            "previous_effective_implementation_identity": NEW_IMPLEMENTATION,
            "prior_attempt_record_id": None,
            "repair_id": opened.record_id,
            "resume_action": "continue_batch",
            "scientific_failure_delta": 0,
            "scientific_trial_delta": 0,
            "verification_evidence_hashes": [VERIFICATION_HASH],
        },
        event_stream=f"job-repair:{JOB_ID}",
        event_sequence=2,
        authority_sequence=23,
        authority_event_id=_event_id(23),
        authority_offset=1,
    )
    resume = _resume_record(
        close,
        event_sequence=2,
        authority_sequence=24,
    )
    completion = _completion_record(
        resume_record_id=resume.record_id,
        scientific=fixture.completion.payload["scientific"],
        authority_sequence=25,
    )
    judgment = _judgment_record(completion, authority_sequence=26)
    request = _request(NEW_IMPLEMENTATION)
    preflight_payload = {
        **fixture.preflight.payload,
        "repair_close_record_id": close.record_id,
    }
    preflight = _content_record(
        kind="job-implementation-preflight",
        prefix="job-implementation-preflight:",
        domain="replay-job-implementation-preflight",
        subject=fixture.preflight.subject,
        status="accepted",
        payload=preflight_payload,
        event_stream=repair_preflight_stream(close.record_id),
        event_sequence=1,
        authority_sequence=27,
    )
    admission_payload = {
        **fixture.admission.payload,
        "recertification_preflight_id": preflight.record_id,
        "repair_close_record_ids": [
            fixture.repair_close.record_id,
            close.record_id,
        ],
        "request": request,
        "trigger_repair_close_record_id": close.record_id,
    }
    admission = _content_record(
        kind="replay-implementation-admission",
        prefix="replay-implementation-admission:",
        domain="replay-implementation-admission",
        subject=fixture.admission.subject,
        status="active",
        payload=admission_payload,
        event_stream=fixture.admission.event_stream,
        event_sequence=fixture.admission.event_sequence,
        authority_sequence=27,
    )
    fixture.records.extend((opened, attempt, close, resume))
    fixture.replace_records(
        (
            (fixture.completion, completion),
            (fixture.judgment, judgment),
            (fixture.preflight, preflight),
            (fixture.admission, admission),
        )
    )
    fixture.resume = resume
