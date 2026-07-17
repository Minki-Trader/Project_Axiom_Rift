"""Authenticated family-wide replay admission after an in-place Job Repair.

A running Job Repair is deliberately local to that immutable Job.  When the
same implementation is shared by the remaining members of a preregistered
replay family, the Repair must not silently rewrite the Study admission.  This
module projects the exact additive bridge: the completed Job, its ordered
Repair chain, the accepted full-family preflight, and the predecessor admission
are all immutable inputs to one successor admission.

The state writer remains the only mutation boundary.  Functions here only
inspect an authenticated index or validate records that the writer is about to
commit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.replay_repair_operational_authority import (
    ReplayRepairOperationalAuthorityError,
    require_repair_chain,
)
from axiom_rift.operations.replay_repair_scientific_authority import (
    ReplayRepairScientificAuthorityError,
    request_executable_ids,
    request_member_binding,
    request_validation_plan_hashes,
    require_scientific_completion,
)
from axiom_rift.operations.replay_study_admission import (
    ReplayStudyAdmissionError,
    ReplayStudyRegistrationInspection,
    inspect_replay_study_registration,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


REPAIR_RECERTIFICATION_ADMISSION_SCHEMA = "replay_implementation_admission.v3"
REPAIR_RECERTIFICATION_ADMISSION_STREAM_PREFIX = (
    "replay-implementation-admission-repair-study:"
)
REPAIR_RECERTIFICATION_PREFLIGHT_STREAM_PREFIX = (
    "replay-job-implementation-preflight-repair:"
)

class ReplayImplementationRepairAdmissionError(RuntimeError):
    """A requested post-Repair family admission is not currently admissible."""


class ReplayImplementationRepairAdmissionIntegrityError(
    ReplayImplementationRepairAdmissionError
):
    """Durable post-Repair family-admission authority is malformed."""


@dataclass(frozen=True, slots=True)
class ReplayImplementationRepairBoundary:
    """Writer-derived inputs for one additive family recertification."""

    predecessor_admission_id: str
    repair_close_record_ids: tuple[str, ...]
    repair_job_id: str
    repair_executable_id: str
    registered_executable_ids: tuple[str, ...]
    trigger_repair_close_record_id: str
    admission_event_sequence: int


def repair_admission_stream(study_id: str) -> str:
    return REPAIR_RECERTIFICATION_ADMISSION_STREAM_PREFIX + study_id


def repair_preflight_stream(repair_close_record_id: str) -> str:
    return (
        REPAIR_RECERTIFICATION_PREFLIGHT_STREAM_PREFIX
        + repair_close_record_id
    )


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplayImplementationRepairAdmissionIntegrityError(
            f"{name} is not a mapping"
        )
    return value


def _request_without_implementation(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    reduced = dict(request)
    reduced.pop("implementation_identity", None)
    return reduced


def _records_by_payload(
    index: LocalIndex | LocalIndexView,
    kind: str,
    key: str,
    value: str,
) -> tuple[IndexRecord, ...]:
    return tuple(index.records_by_payload_text(kind, key, value))


def _require_content_addressed_admission(
    admission: IndexRecord,
    *,
    study_id: str,
) -> None:
    fingerprint = canonical_digest(
        domain="replay-implementation-admission",
        payload=admission.payload,
    )
    if (
        admission.kind != "replay-implementation-admission"
        or admission.status != "active"
        or admission.subject != f"Study:{study_id}"
        or admission.fingerprint != fingerprint
        or admission.record_id
        != f"replay-implementation-admission:{fingerprint}"
    ):
        raise ReplayImplementationRepairAdmissionIntegrityError(
            "replay implementation admission content identity is malformed"
        )


def _require_completed_repair_job(
    index: LocalIndex | LocalIndexView,
    *,
    job_id: str,
    trigger_close: IndexRecord,
    declaration: IndexRecord,
    request: Mapping[str, Any],
    executable_id: str,
    batch_record: IndexRecord,
) -> tuple[IndexRecord, IndexRecord]:
    completions = tuple(
        record
        for record in index.records_by_subject_status(
            f"Job:{job_id}",
            "success",
        )
        if record.kind == "job-completed"
        and record.payload.get("job_id") == job_id
    )
    if len(completions) != 1:
        raise ReplayImplementationRepairAdmissionIntegrityError(
            "repaired replay Job lacks one exact completion"
        )
    completion = completions[0]
    resume_id = completion.payload.get("repair_resume_record_id")
    resume = (
        None
        if type(resume_id) is not str
        else index.get("job-resumed", resume_id)
    )
    resume_head = index.event_head(f"job-resume:{job_id}")
    judgments = _records_by_payload(
        index,
        "job-evidence-decision",
        "completion_record_id",
        completion.record_id,
    )
    judgment = judgments[0] if len(judgments) == 1 else None
    judgment_payload = {
        "completion_record_id": completion.record_id,
        "disposition": "continue_batch",
        "negative_memory_id": (
            None if judgment is None else judgment.payload.get("negative_memory_id")
        ),
    }
    expected_judgment_id = canonical_digest(
        domain="job-evidence-decision",
        payload=judgment_payload,
    )
    if (
        completion.status != "success"
        or completion.subject != f"Job:{job_id}"
        or resume is None
        or resume.status != "validated"
        or resume.subject != f"Job:{job_id}"
        or resume.event_stream != f"job-resume:{job_id}"
        or resume_head is None
        or resume_head.record_id != resume.record_id
        or resume.payload.get("repair_close_record_id")
        != trigger_close.record_id
        or resume.payload.get("effective_implementation_identity")
        != trigger_close.payload.get("effective_implementation_identity")
        or resume.payload.get("execution", {}).get("job_id") != job_id
        or judgment is None
        or judgment.status != "continue_batch"
        or judgment.subject != f"Job:{job_id}"
        or set(judgment.payload)
        != {"completion_record_id", "negative_memory_id"}
        or judgment.payload.get("completion_record_id") != completion.record_id
        or judgment.fingerprint != declaration.fingerprint
        or judgment.record_id != expected_judgment_id
        or declaration.record_id != job_id
        or declaration.fingerprint != job_id.removeprefix("job:")
        or completion.fingerprint != declaration.fingerprint
        or type(declaration.authority_sequence) is not int
        or type(trigger_close.authority_sequence) is not int
        or type(resume.authority_sequence) is not int
        or type(completion.authority_sequence) is not int
        or type(judgment.authority_sequence) is not int
        or not (
            declaration.authority_sequence
            < trigger_close.authority_sequence
            < resume.authority_sequence
            < completion.authority_sequence
            < judgment.authority_sequence
        )
    ):
        raise ReplayImplementationRepairAdmissionIntegrityError(
            "repaired replay Job completion or judgement is malformed"
        )
    try:
        require_scientific_completion(
            completion=completion,
            declaration=declaration,
            request=request,
            executable_id=executable_id,
            batch_record=batch_record,
        )
    except ReplayRepairScientificAuthorityError as exc:
        raise ReplayImplementationRepairAdmissionIntegrityError(str(exc)) from exc
    scientific = completion.payload["scientific"]
    negative_memory_id = judgment.payload.get("negative_memory_id")
    needs_negative_memory = (
        scientific.get("verdict") == "failed"
        and scientific.get("scientific_eligible") is True
    )
    memory = (
        None
        if type(negative_memory_id) is not str
        else index.get("negative-memory", negative_memory_id)
    )
    memory_payload = None if memory is None else memory.payload
    memory_references = (
        None
        if not isinstance(memory_payload, Mapping)
        else memory_payload.get("evidence_references")
    )
    expected_memory_id = (
        None
        if not isinstance(memory_payload, Mapping)
        else "negative-memory:"
        + canonical_digest(
            domain="negative-memory",
            payload={
                "evidence_references": memory_references,
                "executable_identity": executable_id,
                "reason": memory_payload.get("reason"),
                "reopen_condition": memory_payload.get("reopen_condition"),
                "scope": memory_payload.get("scope"),
            },
        )
    )
    if needs_negative_memory:
        if (
            memory is None
            or not negative_memory_id.startswith("negative-memory:")
            or memory.status != "durable"
            or memory.subject != f"Executable:{executable_id}"
            or memory.fingerprint != executable_id
            or set(memory_payload)
            != {
                "evidence_references",
                "executed_evidence_modes",
                "holdout_id",
                "mission_id",
                "portfolio_axis_id",
                "portfolio_axis_identity",
                "portfolio_snapshot_id",
                "reason",
                "reopen_condition",
                "scope",
                "study_id",
            }
            or not isinstance(memory_references, list)
            or memory_references != sorted(set(memory_references))
            or completion.record_id not in memory_references
            or memory.payload.get("mission_id") != request.get("mission_id")
            or memory.payload.get("study_id")
            != declaration.payload.get("study_id")
            or memory.record_id != expected_memory_id
            or type(memory.authority_sequence) is not int
            or not (
                completion.authority_sequence
                < memory.authority_sequence
                < judgment.authority_sequence
            )
        ):
            raise ReplayImplementationRepairAdmissionIntegrityError(
                "failed repaired replay science lacks its exact negative memory"
            )
    elif negative_memory_id is not None:
        raise ReplayImplementationRepairAdmissionIntegrityError(
            "repaired replay judgment carries unrelated negative memory"
        )
    return completion, judgment


def inspect_replay_implementation_repair_boundary(
    index: LocalIndex | LocalIndexView,
    *,
    predecessor_admission: IndexRecord,
    study_record: IndexRecord,
    batch_record: IndexRecord,
    request: Mapping[str, Any],
    registration_inspection: ReplayStudyRegistrationInspection,
    trigger_repair_close_record_id: str,
) -> ReplayImplementationRepairBoundary:
    """Re-derive the only Repair edge allowed to update a family admission."""

    predecessor_request = _mapping(
        predecessor_admission.payload.get("request"),
        "predecessor replay implementation request",
    )
    predecessor_identity = predecessor_request.get("implementation_identity")
    next_identity = request.get("implementation_identity")
    expected_family = tuple(request.get("executable_manifests", ()))
    expected_executable_ids = request_executable_ids(request)
    try:
        registration = registration_inspection.require_usable()
    except ReplayStudyAdmissionError as exc:
        raise ReplayImplementationRepairAdmissionIntegrityError(str(exc)) from exc
    registered = registration.registered_executable_ids
    if (
        predecessor_admission.kind != "replay-implementation-admission"
        or predecessor_admission.status != "active"
        or predecessor_admission.subject != f"Study:{study_record.record_id}"
        or _request_without_implementation(predecessor_request)
        != _request_without_implementation(request)
        or type(predecessor_identity) is not str
        or type(next_identity) is not str
        or predecessor_identity == next_identity
        or expected_executable_ids != registered
        or not registered
        or len(expected_family) != len(registered)
        or registration.study_id != study_record.record_id
        or registration.batch_id != batch_record.record_id
        or registration.expected_executable_ids != expected_executable_ids
        or study_record.payload.get("mission_id") != request.get("mission_id")
        or study_record.payload.get("replay_obligation_ids")
        != request.get("replay_obligation_ids")
    ):
        raise ReplayImplementationRepairAdmissionError(
            "post-Repair preflight differs from the admitted replay family"
        )
    trigger = index.get("repair-close", trigger_repair_close_record_id)
    job_id = None if trigger is None else trigger.payload.get("job_id")
    declaration = (
        None
        if type(job_id) is not str
        else index.get("job-declared", job_id)
    )
    spec = None if declaration is None else declaration.payload.get("spec")
    subject = None if not isinstance(spec, Mapping) else spec.get("evidence_subject")
    executable_id = (
        None
        if not isinstance(subject, Mapping)
        else subject.get("id")
    )
    if (
        trigger is None
        or type(job_id) is not str
        or declaration is None
        or declaration.status != "declared"
        or declaration.payload.get("mission_id") != request.get("mission_id")
        or declaration.payload.get("study_id") != study_record.record_id
        or declaration.payload.get("batch_id") != batch_record.record_id
        or not isinstance(spec, Mapping)
        or spec.get("callable_identity") != request.get("callable_identity")
        or spec.get("implementation_identity") != predecessor_identity
        or not isinstance(subject, Mapping)
        or subject.get("kind") != "Executable"
        or type(executable_id) is not str
        or executable_id not in registered
        or type(predecessor_admission.authority_sequence) is not int
        or type(declaration.authority_sequence) is not int
        or predecessor_admission.authority_sequence
        >= declaration.authority_sequence
    ):
        raise ReplayImplementationRepairAdmissionError(
            "post-Repair admission lacks its exact replay Job declaration"
        )
    declarations = tuple(
        sorted(
            _records_by_payload(
                index,
                "job-declared",
                "batch_id",
                batch_record.record_id,
            ),
            key=lambda record: record.authority_sequence,
        )
    )
    declaration_executable_ids = tuple(
        record.payload.get("spec", {}).get("evidence_subject", {}).get("id")
        for record in declarations
    )
    if (
        not declarations
        or declarations[-1].record_id != declaration.record_id
        or declaration_executable_ids != registered[: len(declarations)]
    ):
        raise ReplayImplementationRepairAdmissionError(
            "post-Repair admission is outside the exact declared family prefix"
        )
    try:
        closes = require_repair_chain(
            index,
            job_id=job_id,
            declared_implementation_identity=predecessor_identity,
            expected_implementation_identity=next_identity,
            trigger_repair_close_record_id=trigger_repair_close_record_id,
            declaration=declaration,
            executable_id=executable_id,
        )
    except ReplayRepairOperationalAuthorityError as exc:
        raise ReplayImplementationRepairAdmissionIntegrityError(str(exc)) from exc
    _require_completed_repair_job(
        index,
        job_id=job_id,
        trigger_close=closes[-1],
        declaration=declaration,
        request=predecessor_request,
        executable_id=executable_id,
        batch_record=batch_record,
    )
    admission_stream = repair_admission_stream(study_record.record_id)
    admission_head = index.event_head(admission_stream)
    if admission_head is not None and admission_head.record_id != (
        predecessor_admission.record_id
    ):
        raise ReplayImplementationRepairAdmissionIntegrityError(
            "post-Repair admission predecessor is not the current stream head"
        )
    return ReplayImplementationRepairBoundary(
        predecessor_admission_id=predecessor_admission.record_id,
        repair_close_record_ids=tuple(close.record_id for close in closes),
        repair_job_id=job_id,
        repair_executable_id=executable_id,
        registered_executable_ids=registered,
        trigger_repair_close_record_id=trigger_repair_close_record_id,
        admission_event_sequence=(
            1 if admission_head is None else admission_head.sequence + 1
        ),
    )


def require_replay_implementation_repair_link(
    index: LocalIndex | LocalIndexView,
    *,
    predecessor_admission: IndexRecord,
    admission: IndexRecord,
    study_id: str,
) -> None:
    """Authenticate one already-recorded v3 admission link from first principles."""

    _require_content_addressed_admission(
        predecessor_admission,
        study_id=study_id,
    )
    payload = admission.payload
    expected_payload_keys = {
        "accepted_replacement_preflight_id",
        "authority_manifest_digest",
        "batch_id",
        "predecessor_admission_id",
        "recertification_preflight_id",
        "registered_prefix_executable_ids",
        "repair_close_record_ids",
        "repair_executable_id",
        "repair_job_id",
        "request",
        "research_protocol_activation_id",
        "schema",
        "scientific_surface",
        "scientific_surface_hash",
        "source_closure_authority",
        "study_id",
        "trigger_repair_close_record_id",
    }
    request = _mapping(payload.get("request"), "repaired replay request")
    predecessor_payload = predecessor_admission.payload
    predecessor_request = _mapping(
        predecessor_admission.payload.get("request"),
        "predecessor replay request",
    )
    close_ids = payload.get("repair_close_record_ids")
    trigger_id = payload.get("trigger_repair_close_record_id")
    job_id = payload.get("repair_job_id")
    executable_id = payload.get("repair_executable_id")
    registered = payload.get("registered_prefix_executable_ids")
    preflight_id = payload.get("recertification_preflight_id")
    preflight = (
        None
        if type(preflight_id) is not str
        else index.get("job-implementation-preflight", preflight_id)
    )
    stream_head = index.event_head(repair_preflight_stream(str(trigger_id)))
    expected_preflight_keys = {
        "artifact_hashes",
        "batch_id",
        "callable_identity",
        "component_implementation_hashes",
        "executable_ids",
        "executable_manifests",
        "failure_detail",
        "failure_fingerprint",
        "implementation_identity",
        "mission_id",
        "outcome",
        "protocol_id",
        "reason_code",
        "remediation_kind",
        "repair_close_record_id",
        "replacement_for_preflight_id",
        "replay_obligation_ids",
        "request_identity",
        "schema",
        "scientific_surface",
        "scientific_surface_hash",
        "source_closure_authority",
        "study_id",
        "validation_plan_hashes",
    }
    declaration = (
        None if type(job_id) is not str else index.get("job-declared", job_id)
    )
    spec = None if declaration is None else declaration.payload.get("spec")
    trigger = (
        None
        if type(trigger_id) is not str
        else index.get("repair-close", trigger_id)
    )
    predecessor_identity = predecessor_request.get("implementation_identity")
    repaired_identity = request.get("implementation_identity")
    batch_id = payload.get("batch_id")
    study = index.get("study-open", study_id)
    batch = (
        None
        if type(batch_id) is not str
        else index.get("batch-open", batch_id)
    )
    registration = None
    if study is not None and batch is not None:
        try:
            registration = inspect_replay_study_registration(
                index,
                study_record=study,
                batch_record=batch,
            ).require_usable()
        except ReplayStudyAdmissionError as exc:
            raise ReplayImplementationRepairAdmissionIntegrityError(
                str(exc)
            ) from exc
    try:
        binding = (
            None
            if type(executable_id) is not str
            else request_member_binding(request, executable_id)
        )
        expected_validation_plan_hashes = request_validation_plan_hashes(
            request
        )
    except ReplayRepairScientificAuthorityError as exc:
        raise ReplayImplementationRepairAdmissionIntegrityError(str(exc)) from exc
    admission_fingerprint = canonical_digest(
        domain="replay-implementation-admission",
        payload=payload,
    )
    if (
        admission.kind != "replay-implementation-admission"
        or admission.status != "active"
        or admission.subject != f"Study:{study_id}"
        or admission.event_stream != repair_admission_stream(study_id)
        or type(admission.event_sequence) is not int
        or admission.event_sequence < 1
        or set(payload) != expected_payload_keys
        or payload.get("schema") != REPAIR_RECERTIFICATION_ADMISSION_SCHEMA
        or payload.get("study_id") != study_id
        or payload.get("predecessor_admission_id")
        != predecessor_admission.record_id
        or payload.get("accepted_replacement_preflight_id")
        != predecessor_payload.get("accepted_replacement_preflight_id")
        or payload.get("authority_manifest_digest")
        != predecessor_payload.get("authority_manifest_digest")
        or payload.get("batch_id") != predecessor_payload.get("batch_id")
        or payload.get("research_protocol_activation_id")
        != predecessor_payload.get("research_protocol_activation_id")
        or payload.get("scientific_surface")
        != predecessor_payload.get("scientific_surface")
        or payload.get("scientific_surface_hash")
        != predecessor_payload.get("scientific_surface_hash")
        or _request_without_implementation(predecessor_request)
        != _request_without_implementation(request)
        or request.get("schema")
        != "replay_job_implementation_preflight_request.v1"
        or not isinstance(close_ids, list)
        or not close_ids
        or any(type(item) is not str for item in close_ids)
        or close_ids[-1] != trigger_id
        or trigger is None
        or type(job_id) is not str
        or type(executable_id) is not str
        or declaration is None
        or not isinstance(spec, Mapping)
        or declaration.status != "declared"
        or declaration.subject != f"Job:{job_id}"
        or declaration.payload.get("mission_id") != request.get("mission_id")
        or declaration.payload.get("study_id") != study_id
        or declaration.payload.get("batch_id") != batch_id
        or spec.get("callable_identity") != request.get("callable_identity")
        or spec.get("implementation_identity") != predecessor_identity
        or spec.get("scientific_binding") != binding
        or spec.get("evidence_subject")
        != {"kind": "Executable", "id": executable_id}
        or not isinstance(registered, list)
        or tuple(registered) != request_executable_ids(request)
        or study is None
        or batch is None
        or registration is None
        or registration.study_id != study_id
        or registration.batch_id != batch_id
        or registration.expected_executable_ids
        != request_executable_ids(request)
        or registration.registered_executable_ids != tuple(registered)
        or type(predecessor_identity) is not str
        or type(repaired_identity) is not str
        or predecessor_identity == repaired_identity
        or preflight is None
        or preflight.kind != "job-implementation-preflight"
        or preflight.status != "accepted"
        or preflight.subject != f"Batch:{payload.get('batch_id')}"
        or set(preflight.payload) != expected_preflight_keys
        or preflight.payload.get("schema")
        != "replay_job_implementation_preflight.v1"
        or preflight.payload.get("outcome") != "accepted"
        or any(
            preflight.payload.get(field) is not None
            for field in (
                "failure_detail",
                "failure_fingerprint",
                "reason_code",
                "remediation_kind",
            )
        )
        or preflight.payload.get("repair_close_record_id") != trigger_id
        or preflight.payload.get("batch_id") != payload.get("batch_id")
        or preflight.payload.get("study_id") != study_id
        or preflight.payload.get("callable_identity")
        != request.get("callable_identity")
        or preflight.payload.get("mission_id") != request.get("mission_id")
        or preflight.payload.get("protocol_id") != request.get("protocol_id")
        or preflight.payload.get("replacement_for_preflight_id")
        != request.get("replacement_for_preflight_id")
        or preflight.payload.get("replay_obligation_ids")
        != request.get("replay_obligation_ids")
        or preflight.payload.get("executable_manifests")
        != request.get("executable_manifests")
        or tuple(preflight.payload.get("executable_ids", ()))
        != tuple(registered)
        or tuple(preflight.payload.get("validation_plan_hashes", ()))
        != expected_validation_plan_hashes
        or preflight.payload.get("implementation_identity")
        != repaired_identity
        or preflight.payload.get("scientific_surface")
        != payload.get("scientific_surface")
        or preflight.payload.get("scientific_surface_hash")
        != payload.get("scientific_surface_hash")
        or preflight.payload.get("source_closure_authority")
        != payload.get("source_closure_authority")
        or preflight.payload.get("request_identity")
        != (
            "replay-job-implementation-preflight-request:"
            + canonical_digest(
                domain="replay-job-implementation-preflight-request",
                payload=request,
            )
        )
        or preflight.event_stream != repair_preflight_stream(trigger_id)
        or preflight.event_sequence != 1
        or stream_head is None
        or stream_head.sequence != 1
        or stream_head.record_id != preflight.record_id
        or preflight.fingerprint
        != canonical_digest(
            domain="replay-job-implementation-preflight",
            payload=preflight.payload,
        )
        or preflight.record_id
        != f"job-implementation-preflight:{preflight.fingerprint}"
        or admission.authority_sequence != preflight.authority_sequence
        or admission.authority_event_id != preflight.authority_event_id
        or type(predecessor_admission.authority_sequence) is not int
        or predecessor_admission.authority_sequence
        >= admission.authority_sequence
        or type(declaration.authority_sequence) is not int
        or predecessor_admission.authority_sequence
        >= declaration.authority_sequence
        or type(trigger.authority_sequence) is not int
        or type(admission.authority_sequence) is not int
        or trigger.authority_sequence >= admission.authority_sequence
        or admission.fingerprint != admission_fingerprint
        or admission.record_id
        != f"replay-implementation-admission:{admission_fingerprint}"
    ):
        raise ReplayImplementationRepairAdmissionIntegrityError(
            "post-Repair replay implementation admission link is malformed"
        )
    try:
        closes = require_repair_chain(
            index,
            job_id=job_id,
            declared_implementation_identity=predecessor_identity,
            expected_implementation_identity=repaired_identity,
            trigger_repair_close_record_id=trigger_id,
            declaration=declaration,
            executable_id=executable_id,
        )
    except ReplayRepairOperationalAuthorityError as exc:
        raise ReplayImplementationRepairAdmissionIntegrityError(str(exc)) from exc
    if tuple(close.record_id for close in closes) != tuple(close_ids):
        raise ReplayImplementationRepairAdmissionIntegrityError(
            "post-Repair admission names another Repair chain"
        )
    _completion, judgment = _require_completed_repair_job(
        index,
        job_id=job_id,
        trigger_close=closes[-1],
        declaration=declaration,
        request=predecessor_request,
        executable_id=executable_id,
        batch_record=batch,
    )
    if (
        type(judgment.authority_sequence) is not int
        or type(preflight.authority_sequence) is not int
        or judgment.authority_sequence >= preflight.authority_sequence
    ):
        raise ReplayImplementationRepairAdmissionIntegrityError(
            "post-Repair admission precedes its completed scientific Job"
        )


def current_replay_implementation_repair_admission(
    index: LocalIndex | LocalIndexView,
    *,
    study_id: str,
    base_admission: IndexRecord,
) -> IndexRecord:
    """Return the authenticated terminal admission in the additive Repair chain."""

    _require_content_addressed_admission(base_admission, study_id=study_id)
    stream = repair_admission_stream(study_id)
    head = index.event_head(stream)
    if head is None:
        return base_admission
    predecessor = base_admission
    for sequence in range(1, head.sequence + 1):
        admission = index.event_record(stream, sequence)
        if (
            admission is None
            or admission.event_sequence != sequence
            or admission.event_stream != stream
        ):
            raise ReplayImplementationRepairAdmissionIntegrityError(
                "post-Repair admission stream is incomplete"
            )
        require_replay_implementation_repair_link(
            index,
            predecessor_admission=predecessor,
            admission=admission,
            study_id=study_id,
        )
        predecessor = admission
    if predecessor.record_id != head.record_id:
        raise ReplayImplementationRepairAdmissionIntegrityError(
            "post-Repair admission head differs from its authenticated chain"
        )
    return predecessor


__all__ = [
    "REPAIR_RECERTIFICATION_ADMISSION_SCHEMA",
    "ReplayImplementationRepairAdmissionError",
    "ReplayImplementationRepairAdmissionIntegrityError",
    "ReplayImplementationRepairBoundary",
    "current_replay_implementation_repair_admission",
    "inspect_replay_implementation_repair_boundary",
    "repair_admission_stream",
    "repair_preflight_stream",
    "require_replay_implementation_repair_link",
]
