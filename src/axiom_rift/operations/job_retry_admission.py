"""State-bound admission and projection records for failed Job retries.

Pure retry-family identity and proof parsing live in ``job_retry_family``.
Legacy lookup lives in ``job_retry_history``.  This module owns the remaining
state-bound admission decision so ``StateWriter`` stays the sole mutator
without also carrying hundreds of lines of retry protocol implementation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.job_implementation_authority import (
    JobImplementationAuthorityError,
    require_job_implementation_evidence,
)
from axiom_rift.operations.job_retry_family import (
    RETRY_RESUME_AUTHORITY_SCHEMA,
    JobRetryFamily,
    JobRetryFamilyError,
    JobRetryValidationAuthority,
    derive_job_retry_family,
    derive_runtime_source_retry_resolution,
    evidence_schema,
    parse_job_retry_resume_authority,
    require_legacy_implementation_retry_semantics,
    retry_basis_identity,
    retry_family_attempt_identity,
    retry_family_attempt_payload,
    validate_engineering_retry_evidence,
)
from axiom_rift.operations.job_retry_history import (
    JobRetryHistoryError,
    resolve_job_retry_history,
)
from axiom_rift.operations.validation import EvidenceValidatorRegistry
from axiom_rift.storage.index import EventHead, IndexRecord, LocalIndex


class JobRetryAdmissionError(RuntimeError):
    """Base class for one retry admission failure."""


class JobRetryAdmissionSpecificationError(JobRetryAdmissionError):
    """The current Job cannot form a valid Writer-owned retry family."""


class JobRetryAdmissionIntegrityError(JobRetryAdmissionError):
    """Authenticated retry history is incomplete or internally inconsistent."""


class JobRetryAdmissionRejected(JobRetryAdmissionError):
    """A prior failed family has no valid materially changed retry basis."""


EvidenceReader = Callable[[str], bytes]
EvidenceVerifier = Callable[[str], object]
EvidencePathResolver = Callable[[str], Path]


@dataclass(frozen=True, slots=True)
class JobRetryAdmission:
    family: JobRetryFamily
    stream_head: EventHead | None
    basis_records: tuple[IndexRecord, ...]


def _record(
    *,
    kind: str,
    record_id: str,
    subject: str,
    status: str,
    fingerprint: str,
    payload: Mapping[str, Any],
    event_stream: str | None = None,
    event_sequence: int | None = None,
) -> IndexRecord:
    return IndexRecord(
        kind=kind,
        record_id=record_id,
        subject=subject,
        status=status,
        fingerprint=fingerprint,
        payload=dict(payload),
        event_stream=event_stream,
        event_sequence=event_sequence,
    )


def _prior_completion(
    *,
    index: LocalIndex,
    family_attempt: IndexRecord,
) -> IndexRecord:
    if family_attempt.kind != "job-retry-family-attempt":
        return family_attempt
    completion_id = family_attempt.payload.get("completion_record_id")
    completion = (
        None
        if not isinstance(completion_id, str)
        else index.get("job-completed", completion_id)
    )
    if (
        completion is None
        or completion.status != family_attempt.status
        or completion.payload.get("job_id")
        != family_attempt.payload.get("job_id")
    ):
        raise JobRetryAdmissionIntegrityError(
            "Job retry family completion is unavailable"
        )
    return completion


def _automatic_runtime_source_basis_record(
    *,
    index: LocalIndex,
    family: JobRetryFamily,
    previous_attempt: IndexRecord,
    previous_declaration: IndexRecord,
    prior_failure: Mapping[str, Any] | None,
    previous_candidate_context: Mapping[str, Any] | None,
    current_candidate_context: Mapping[str, Any] | None,
    current_spec: Mapping[str, Any],
    current_job_id: str,
    current_job_hash: str,
) -> tuple[IndexRecord | None, bool]:
    try:
        resolution = derive_runtime_source_retry_resolution(
            failure=prior_failure,
            previous_candidate_context=previous_candidate_context,
            current_candidate_context=current_candidate_context,
            previous_spec=previous_declaration.payload["spec"],
            current_spec=current_spec,
        )
    except (KeyError, JobRetryFamilyError) as exc:
        raise JobRetryAdmissionRejected(str(exc)) from exc
    if resolution is None:
        return None, False
    basis_id = retry_basis_identity(
        retry_family_fingerprint=family.fingerprint,
        changed_dimension="information",
        new_basis_hash=resolution.new_basis_hash,
    )
    if index.get("job-retry-basis", basis_id) is not None:
        raise JobRetryAdmissionRejected("Job retry basis was already consumed")
    return (
        _record(
            kind="job-retry-basis",
            record_id=basis_id,
            subject=f"JobRetryFamily:{family.fingerprint}",
            status="consumed",
            fingerprint=resolution.new_basis_hash,
            payload={
                **resolution.payload(),
                "consumed_by_job_hash": current_job_hash,
                "consumed_by_job_id": current_job_id,
                "consumption_event_kind": "job_declared",
                "prior_completion_record_id": previous_attempt.record_id,
                "retry_family_fingerprint": family.fingerprint,
                "scientific_failure_delta": 0,
                "scientific_trial_delta": 0,
                "validations": [],
            },
        ),
        True,
    )


def _typed_resume_basis_record(
    *,
    index: LocalIndex,
    family: JobRetryFamily,
    previous_attempt: IndexRecord,
    previous_declaration: IndexRecord,
    prior_failure: Mapping[str, Any] | None,
    engineering_disposition: Mapping[str, Any] | None,
    current_spec: Mapping[str, Any],
    work_fingerprint: str,
    current_job_id: str,
    current_job_hash: str,
    authority_hash: str,
    authority_bytes: bytes,
    read_evidence: EvidenceReader,
    verify_evidence: EvidenceVerifier,
    evidence_path: EvidencePathResolver,
    validation_registry: EvidenceValidatorRegistry,
    engineering_fixture: bool,
    prevalidated_authorities: (
        Mapping[str, JobRetryValidationAuthority] | None
    ),
    defer_validation: bool,
) -> IndexRecord:
    if prior_failure is None or engineering_disposition is None:
        raise JobRetryAdmissionRejected(
            "same-implementation retry lacks an exact engineering disposition"
        )
    try:
        authority = parse_job_retry_resume_authority(
            authority_bytes,
            mission_id=family.mission_id,
            evidence_subject=family.evidence_subject,
            retry_family_fingerprint=family.fingerprint,
            prior_completion_record_id=previous_attempt.record_id,
            prior_job_id=previous_declaration.record_id,
            prior_job_hash=previous_declaration.fingerprint,
            prior_work_fingerprint=previous_declaration.payload[
                "work_fingerprint"
            ],
            new_work_fingerprint=work_fingerprint,
            failure=prior_failure,
            engineering_disposition=engineering_disposition,
            previous_spec=previous_declaration.payload["spec"],
            current_spec=current_spec,
            read_evidence=read_evidence,
            verify_evidence=verify_evidence,
            evidence_path=evidence_path,
            validation_registry=validation_registry,
            engineering_fixture=engineering_fixture,
            prevalidated_authorities=prevalidated_authorities,
            defer_validation=defer_validation,
        )
        basis_id = retry_basis_identity(
            retry_family_fingerprint=family.fingerprint,
            changed_dimension=authority.changed_dimension,
            new_basis_hash=authority.new_basis_hash,
        )
    except (KeyError, JobRetryFamilyError) as exc:
        raise JobRetryAdmissionRejected(str(exc)) from exc
    if index.get("job-retry-basis", basis_id) is not None:
        raise JobRetryAdmissionRejected("Job retry basis was already consumed")
    return _record(
        kind="job-retry-basis",
        record_id=basis_id,
        subject=f"JobRetryFamily:{family.fingerprint}",
        status="consumed",
        fingerprint=authority.new_basis_hash,
        payload={
            "authority_hash": authority_hash,
            "changed_dimension": authority.changed_dimension,
            "consumed_by_job_hash": current_job_hash,
            "consumed_by_job_id": current_job_id,
            "consumption_event_kind": "job_declared",
            "new_basis_hash": authority.new_basis_hash,
            "new_evidence_hashes": list(authority.new_evidence_hashes),
            "prior_completion_record_id": previous_attempt.record_id,
            "retry_family_fingerprint": family.fingerprint,
            "schema": "job_retry_basis.v1",
            "scientific_failure_delta": 0,
            "scientific_trial_delta": 0,
            "verification_receipt_hashes": list(
                authority.verification_receipt_hashes
            ),
            "validations": [
                validation.payload() for validation in authority.validations
            ],
        },
    )


def _require_implementation_retry(
    *,
    index: LocalIndex,
    family: JobRetryFamily,
    previous_attempt: IndexRecord,
    previous_declaration: IndexRecord,
    prior_failure: Mapping[str, Any] | None,
    current_spec: Mapping[str, Any],
    current_implementation_manifest: Mapping[str, Any],
    current_job_id: str,
    current_job_hash: str,
    work_fingerprint: str,
    changed_proof_hash: str,
    changed_bytes: bytes,
    read_evidence: EvidenceReader,
    verify_evidence: EvidenceVerifier,
    evidence_path: EvidencePathResolver,
    validation_registry: EvidenceValidatorRegistry,
    engineering_fixture: bool,
    prevalidated_authorities: (
        Mapping[str, JobRetryValidationAuthority] | None
    ),
    defer_validation: bool,
) -> IndexRecord:
    previous_spec = previous_declaration.payload["spec"]
    if (
        not isinstance(prior_failure, Mapping)
        or prior_failure.get("failure_kind") != "engineering"
    ):
        raise JobRetryAdmissionRejected(
            "implementation retry requires an exact engineering failure"
        )
    try:
        require_legacy_implementation_retry_semantics(
            previous_spec=previous_spec,
            current_spec=current_spec,
        )
        previous_manifest = require_job_implementation_evidence(
            previous_spec,
            artifact_reader=read_evidence,
        )
    except (KeyError, JobImplementationAuthorityError, JobRetryFamilyError) as exc:
        raise JobRetryAdmissionRejected(str(exc)) from exc
    if (
        previous_manifest["artifact_hashes"]
        == current_implementation_manifest["artifact_hashes"]
    ):
        raise JobRetryAdmissionRejected(
            "changed-cause proof does not change implementation artifacts"
        )
    try:
        changed_manifest = parse_canonical(changed_bytes)
    except (TypeError, ValueError) as exc:
        raise JobRetryAdmissionRejected(
            "changed-cause proof is not canonical"
        ) from exc
    if (
        not isinstance(changed_manifest, dict)
        or set(changed_manifest)
        != {
            "changed_dimension",
            "explanation",
            "new_evidence_hashes",
            "new_implementation_identity",
            "prior_failure_signature",
            "previous_implementation_identity",
            "result_artifact_hashes",
            "schema",
            "validation_plan_hash",
            "validator_id",
        }
        or changed_manifest.get("schema") != "job_changed_cause.v1"
        or changed_manifest.get("prior_failure_signature")
        != (
            prior_failure.get("failure_signature")
            if prior_failure is not None
            else None
        )
        or changed_manifest.get("changed_dimension") != "implementation"
        or changed_manifest.get("previous_implementation_identity")
        != previous_spec.get("implementation_identity")
        or changed_manifest.get("new_implementation_identity")
        != current_spec["implementation_identity"]
        or changed_manifest.get("new_implementation_identity")
        == changed_manifest.get("previous_implementation_identity")
        or type(changed_manifest.get("explanation")) is not str
        or not changed_manifest["explanation"]
        or not changed_manifest["explanation"].isascii()
        or not isinstance(changed_manifest.get("new_evidence_hashes"), list)
        or not changed_manifest["new_evidence_hashes"]
        or changed_manifest["new_evidence_hashes"]
        != sorted(set(changed_manifest["new_evidence_hashes"]))
        or not isinstance(changed_manifest.get("result_artifact_hashes"), list)
        or not changed_manifest["result_artifact_hashes"]
        or changed_manifest["result_artifact_hashes"]
        != sorted(set(changed_manifest["result_artifact_hashes"]))
        or type(changed_manifest.get("validation_plan_hash")) is not str
        or type(changed_manifest.get("validator_id")) is not str
    ):
        raise JobRetryAdmissionRejected(
            "changed-cause proof does not bind the prior failure and change"
        )
    prior_reproduction = set(
        prior_failure.get("minimum_reproduction_evidence", [])
        if prior_failure is not None
        else []
    )
    try:
        for evidence_hash in (
            *changed_manifest["new_evidence_hashes"],
            changed_manifest["validation_plan_hash"],
            *changed_manifest["result_artifact_hashes"],
        ):
            verify_evidence(evidence_hash)
            if evidence_hash in prior_reproduction:
                raise JobRetryAdmissionRejected(
                    "changed-cause evidence reuses prior reproduction"
                )
    except JobRetryAdmissionRejected:
        raise
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise JobRetryAdmissionRejected(
            "changed-cause evidence is unavailable"
        ) from exc
    if (
        changed_manifest["new_implementation_identity"]
        not in changed_manifest["new_evidence_hashes"]
    ):
        raise JobRetryAdmissionRejected(
            "changed-cause proof lacks the new implementation bytes"
        )
    for source_hash in current_implementation_manifest["artifact_hashes"]:
        if source_hash not in changed_manifest["new_evidence_hashes"]:
            raise JobRetryAdmissionRejected(
                "changed-cause proof omits implementation artifact bytes"
            )
    validation_support = {
        changed_manifest["validation_plan_hash"],
        *changed_manifest["result_artifact_hashes"],
    }
    if validation_support.intersection(changed_manifest["new_evidence_hashes"]):
        raise JobRetryAdmissionRejected(
            "changed-cause validation reuses implementation evidence"
        )
    previous_work_fingerprint = previous_declaration.payload.get(
        "work_fingerprint"
    )
    if type(previous_work_fingerprint) is not str:
        raise JobRetryAdmissionRejected(
            "prior implementation retry work fingerprint is unavailable"
        )
    basis_material = {
        "authority_kind": "implementation_cause_resolution",
        "changed_dimension": "implementation",
        "failure_signature": changed_manifest["prior_failure_signature"],
        "new_artifact_hashes": list(
            current_implementation_manifest["artifact_hashes"]
        ),
        "new_implementation_identity": changed_manifest[
            "new_implementation_identity"
        ],
        "new_work_fingerprint": work_fingerprint,
        "previous_artifact_hashes": list(previous_manifest["artifact_hashes"]),
        "previous_implementation_identity": changed_manifest[
            "previous_implementation_identity"
        ],
        "prior_completion_record_id": previous_attempt.record_id,
        "prior_job_hash": previous_declaration.fingerprint,
        "prior_job_id": previous_declaration.record_id,
        "prior_work_fingerprint": previous_work_fingerprint,
        "retry_family_fingerprint": family.fingerprint,
        "schema": "engineering_retry_validation_binding.v1",
        "scientific_semantics_changed": False,
    }
    new_basis_hash = canonical_digest(
        domain="job-implementation-retry-basis",
        payload=basis_material,
    )
    validation = validate_engineering_retry_evidence(
        receipt_hash=changed_proof_hash,
        validator_id=changed_manifest["validator_id"],
        validation_plan_hash=changed_manifest["validation_plan_hash"],
        result_artifact_hashes=tuple(
            changed_manifest["result_artifact_hashes"]
        ),
        mission_id=family.mission_id,
        retry_family_fingerprint=family.fingerprint,
        prior_completion_record_id=previous_attempt.record_id,
        prior_job_id=previous_declaration.record_id,
        prior_job_hash=previous_declaration.fingerprint,
        prior_work_fingerprint=previous_work_fingerprint,
        new_work_fingerprint=work_fingerprint,
        changed_dimension="implementation",
        new_basis_hash=new_basis_hash,
        evidence_subject=family.evidence_subject,
        binding=basis_material,
        result_manifest=changed_manifest,
        validation_registry=validation_registry,
        evidence_path=evidence_path,
        engineering_fixture=engineering_fixture,
        prevalidated_authority=(
            None
            if prevalidated_authorities is None
            else prevalidated_authorities.get(changed_proof_hash)
        ),
        defer_validation=defer_validation,
    )
    basis_id = retry_basis_identity(
        retry_family_fingerprint=family.fingerprint,
        changed_dimension="implementation",
        new_basis_hash=new_basis_hash,
    )
    if index.get("job-retry-basis", basis_id) is not None:
        raise JobRetryAdmissionRejected("Job retry basis was already consumed")
    return _record(
        kind="job-retry-basis",
        record_id=basis_id,
        subject=f"JobRetryFamily:{family.fingerprint}",
        status="consumed",
        fingerprint=new_basis_hash,
        payload={
            "authority_hash": changed_proof_hash,
            "changed_dimension": "implementation",
            "consumed_by_job_hash": current_job_hash,
            "consumed_by_job_id": current_job_id,
            "consumption_event_kind": "job_declared",
            "new_basis_hash": new_basis_hash,
            "new_evidence_hashes": list(
                changed_manifest["new_evidence_hashes"]
            ),
            "prior_completion_record_id": previous_attempt.record_id,
            "retry_family_fingerprint": family.fingerprint,
            "schema": "job_retry_basis.v1",
            "scientific_failure_delta": 0,
            "scientific_trial_delta": 0,
            "validations": [validation.payload()],
        },
    )


def prepare_job_retry_admission(
    *,
    index: LocalIndex,
    mission_id: str,
    initiative_id: str | None,
    study_id: str | None,
    batch_id: str | None,
    spec: Mapping[str, Any],
    candidate_execution_context: Mapping[str, Any] | None,
    implementation_manifest: Mapping[str, Any],
    current_job_id: str,
    current_job_hash: str,
    work_fingerprint: str,
    read_evidence: EvidenceReader,
    verify_evidence: EvidenceVerifier,
    evidence_path: EvidencePathResolver,
    validation_registry: EvidenceValidatorRegistry,
    engineering_fixture: bool,
    prevalidated_authorities: (
        Mapping[str, JobRetryValidationAuthority] | None
    ) = None,
    defer_validation: bool = False,
) -> JobRetryAdmission:
    """Derive one family and authorize only a materially changed retry."""

    try:
        family = derive_job_retry_family(
            mission_id=mission_id,
            initiative_id=initiative_id,
            study_id=study_id,
            batch_id=batch_id,
            spec=spec,
        )
    except JobRetryFamilyError as exc:
        raise JobRetryAdmissionSpecificationError(str(exc)) from exc
    try:
        history = resolve_job_retry_history(index=index, family=family)
    except JobRetryHistoryError as exc:
        raise JobRetryAdmissionIntegrityError(str(exc)) from exc
    latest = history.latest_attempt
    if latest is None or latest.status not in {"failed", "not_evaluable"}:
        if prevalidated_authorities:
            raise JobRetryAdmissionIntegrityError(
                "unrelated retry validation authority is present"
            )
        return JobRetryAdmission(
            family=family,
            stream_head=history.stream_head,
            basis_records=(),
        )
    previous_attempt = _prior_completion(index=index, family_attempt=latest)
    previous_job_id = previous_attempt.payload.get("job_id")
    previous_declaration = (
        None
        if not isinstance(previous_job_id, str)
        else index.get("job-declared", previous_job_id)
    )
    if previous_declaration is None:
        raise JobRetryAdmissionIntegrityError(
            "prior failed Job declaration is unavailable"
        )
    previous_spec = previous_declaration.payload.get("spec")
    if not isinstance(previous_spec, Mapping):
        raise JobRetryAdmissionIntegrityError(
            "prior failed Job declaration spec is malformed"
        )
    failure_value = previous_attempt.payload.get("failure")
    prior_failure = (
        dict(failure_value) if isinstance(failure_value, Mapping) else None
    )
    changed_proof = spec.get("changed_cause_proof_hash")
    basis_records: list[IndexRecord] = []
    automatic_resolution = False
    if changed_proof is None:
        basis_record, automatic_resolution = (
            _automatic_runtime_source_basis_record(
                index=index,
                family=family,
                previous_attempt=previous_attempt,
                previous_declaration=previous_declaration,
                prior_failure=prior_failure,
                previous_candidate_context=(
                    previous_declaration.payload.get(
                        "candidate_execution_context"
                    )
                ),
                current_candidate_context=candidate_execution_context,
                current_spec=spec,
                current_job_id=current_job_id,
                current_job_hash=current_job_hash,
            )
        )
        if basis_record is None:
            raise JobRetryAdmissionRejected(
                "failed Job work cannot be retried without changed-cause proof"
            )
        basis_records.append(basis_record)
        changed_bytes = b""
    elif isinstance(changed_proof, str):
        try:
            changed_bytes = read_evidence(changed_proof)
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            raise JobRetryAdmissionRejected(
                "changed-cause proof is unavailable"
            ) from exc
    else:
        raise JobRetryAdmissionRejected(
            "changed-cause proof identity is malformed"
        )
    if (
        not automatic_resolution
        and prior_failure is not None
        and changed_proof
        in prior_failure.get("minimum_reproduction_evidence", [])
    ):
        raise JobRetryAdmissionRejected(
            "changed-cause proof reuses failed reproduction evidence"
        )
    if (
        not automatic_resolution
        and previous_spec.get("changed_cause_proof_hash") == changed_proof
    ):
        raise JobRetryAdmissionRejected(
            "changed-cause proof was already consumed by the prior retry"
        )
    disposition_value = previous_attempt.payload.get(
        "engineering_disposition"
    )
    engineering_disposition = (
        dict(disposition_value)
        if isinstance(disposition_value, Mapping)
        else None
    )
    if (
        engineering_disposition is not None
        and engineering_disposition.get("disposition")
        == "requires_scientific_change"
    ):
        raise JobRetryAdmissionRejected(
            "requires_scientific_change must create distinct scientific work"
        )
    if automatic_resolution:
        if prevalidated_authorities:
            raise JobRetryAdmissionIntegrityError(
                "automatic retry carries unrelated validator authority"
            )
        return JobRetryAdmission(
            family=family,
            stream_head=history.stream_head,
            basis_records=tuple(basis_records),
        )
    try:
        schema = evidence_schema(changed_bytes)
    except JobRetryFamilyError as exc:
        raise JobRetryAdmissionRejected(
            "changed-cause proof is not a canonical manifest"
        ) from exc
    assert isinstance(changed_proof, str)
    if schema == RETRY_RESUME_AUTHORITY_SCHEMA:
        basis_records.append(
            _typed_resume_basis_record(
                index=index,
                family=family,
                previous_attempt=previous_attempt,
                previous_declaration=previous_declaration,
                prior_failure=prior_failure,
                engineering_disposition=engineering_disposition,
                current_spec=spec,
                work_fingerprint=work_fingerprint,
                current_job_id=current_job_id,
                current_job_hash=current_job_hash,
                authority_hash=changed_proof,
                authority_bytes=changed_bytes,
                read_evidence=read_evidence,
                verify_evidence=verify_evidence,
                evidence_path=evidence_path,
                validation_registry=validation_registry,
                engineering_fixture=engineering_fixture,
                prevalidated_authorities=prevalidated_authorities,
                defer_validation=defer_validation,
            )
        )
    else:
        try:
            basis_records.append(
                _require_implementation_retry(
                    index=index,
                    family=family,
                    previous_attempt=previous_attempt,
                    previous_declaration=previous_declaration,
                    prior_failure=prior_failure,
                    current_spec=spec,
                    current_implementation_manifest=implementation_manifest,
                    current_job_id=current_job_id,
                    current_job_hash=current_job_hash,
                    work_fingerprint=work_fingerprint,
                    changed_proof_hash=changed_proof,
                    changed_bytes=changed_bytes,
                    read_evidence=read_evidence,
                    verify_evidence=verify_evidence,
                    evidence_path=evidence_path,
                    validation_registry=validation_registry,
                    engineering_fixture=engineering_fixture,
                    prevalidated_authorities=prevalidated_authorities,
                    defer_validation=defer_validation,
                )
            )
        except JobRetryFamilyError as exc:
            raise JobRetryAdmissionRejected(str(exc)) from exc
    consumed_validation_receipts = {
        validation.get("receipt_hash")
        for record in basis_records
        for validation in record.payload.get("validations", [])
        if isinstance(validation, Mapping)
    }
    if prevalidated_authorities is not None and set(
        prevalidated_authorities
    ) != consumed_validation_receipts:
        raise JobRetryAdmissionIntegrityError(
            "prevalidated retry authority set differs from admission"
        )
    return JobRetryAdmission(
        family=family,
        stream_head=history.stream_head,
        basis_records=tuple(basis_records),
    )


def build_retry_family_declaration_record(
    *,
    admission: JobRetryAdmission,
    job_id: str,
    job_hash: str,
    work_fingerprint: str,
) -> IndexRecord:
    try:
        payload = retry_family_attempt_payload(
            family=admission.family,
            phase="declared",
            job_id=job_id,
            job_hash=job_hash,
            work_fingerprint=work_fingerprint,
            retry_basis_record_ids=tuple(
                sorted(record.record_id for record in admission.basis_records)
            ),
        )
    except JobRetryFamilyError as exc:
        raise JobRetryAdmissionSpecificationError(str(exc)) from exc
    return _record(
        kind="job-retry-family-attempt",
        record_id=retry_family_attempt_identity(payload),
        subject=f"Mission:{admission.family.mission_id}",
        status="declared",
        fingerprint=admission.family.fingerprint,
        payload=payload,
        event_stream=admission.family.stream,
        event_sequence=(
            1
            if admission.stream_head is None
            else admission.stream_head.sequence + 1
        ),
    )


def build_retry_family_completion_record(
    *,
    index: LocalIndex,
    declaration: IndexRecord,
    outcome: str,
    completion_record_id: str,
) -> IndexRecord | None:
    """Validate the exact current family declaration and append its terminal."""

    stored = declaration.payload.get("retry_family")
    stored_fingerprint = declaration.payload.get(
        "retry_family_fingerprint"
    )
    if stored is None and stored_fingerprint is None:
        return None
    if not isinstance(stored, Mapping) or not isinstance(
        stored_fingerprint, str
    ):
        raise JobRetryAdmissionIntegrityError(
            "stored Job retry family projection is incomplete"
        )
    try:
        family = JobRetryFamily(
            mission_id=stored.get("mission_id"),
            initiative_id=stored.get("initiative_id"),
            study_id=stored.get("study_id"),
            batch_id=stored.get("batch_id"),
            evidence_subject=stored.get("evidence_subject"),
            lane=stored.get("lane"),
            target=stored.get("target"),
        )
    except (JobRetryFamilyError, TypeError, ValueError) as exc:
        raise JobRetryAdmissionIntegrityError(
            "stored Job retry family is malformed"
        ) from exc
    if (
        family.payload() != dict(stored)
        or family.fingerprint != stored_fingerprint
        or declaration.payload.get("mission_id") != family.mission_id
    ):
        raise JobRetryAdmissionIntegrityError(
            "stored Job retry family identity drifted"
        )
    work_fingerprint = declaration.payload.get("work_fingerprint")
    retry_basis_record_ids = declaration.payload.get(
        "retry_basis_record_ids",
        [],
    )
    if (
        not isinstance(retry_basis_record_ids, list)
        or any(type(item) is not str for item in retry_basis_record_ids)
    ):
        raise JobRetryAdmissionIntegrityError(
            "stored Job retry basis projection is malformed"
        )
    try:
        declared_payload = retry_family_attempt_payload(
            family=family,
            phase="declared",
            job_id=declaration.record_id,
            job_hash=declaration.fingerprint,
            work_fingerprint=work_fingerprint,
            retry_basis_record_ids=tuple(retry_basis_record_ids),
        )
    except JobRetryFamilyError as exc:
        raise JobRetryAdmissionIntegrityError(
            "stored Job retry family declaration is malformed"
        ) from exc
    head = index.event_head(family.stream)
    current = (
        None if head is None else index.get(head.record_kind, head.record_id)
    )
    if (
        head is None
        or current is None
        or current.kind != "job-retry-family-attempt"
        or current.record_id
        != retry_family_attempt_identity(declared_payload)
        or current.subject != f"Mission:{family.mission_id}"
        or current.status != "declared"
        or current.fingerprint != family.fingerprint
        or current.payload != declared_payload
        or current.event_stream != family.stream
        or current.event_sequence != head.sequence
    ):
        raise JobRetryAdmissionIntegrityError(
            "Job retry family declaration is not current"
        )
    try:
        completion_payload = retry_family_attempt_payload(
            family=family,
            phase=outcome,
            job_id=declaration.record_id,
            job_hash=declaration.fingerprint,
            work_fingerprint=work_fingerprint,
            retry_basis_record_ids=tuple(retry_basis_record_ids),
            completion_record_id=completion_record_id,
        )
    except JobRetryFamilyError as exc:
        raise JobRetryAdmissionIntegrityError(
            "Job retry family completion is malformed"
        ) from exc
    return _record(
        kind="job-retry-family-attempt",
        record_id=retry_family_attempt_identity(completion_payload),
        subject=f"Mission:{family.mission_id}",
        status=outcome,
        fingerprint=family.fingerprint,
        payload=completion_payload,
        event_stream=family.stream,
        event_sequence=head.sequence + 1,
    )


__all__ = [
    "JobRetryAdmission",
    "JobRetryAdmissionError",
    "JobRetryAdmissionIntegrityError",
    "JobRetryAdmissionRejected",
    "JobRetryAdmissionSpecificationError",
    "build_retry_family_completion_record",
    "build_retry_family_declaration_record",
    "prepare_job_retry_admission",
]
