"""Operational authority behind a repaired replay-family admission.

Family admission must not infer a usable implementation from one Repair close
row.  It reconstructs the cause episode, every changed-basis attempt, the
content-addressed close, and the engine re-entry for each Repair on the Job.
Scientific meaning remains in ``replay_repair_scientific_authority``; this
module owns only the ordered operational lineage that delivers that meaning.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.replay_repair_scientific_authority import (
    ReplayRepairScientificAuthorityError,
    require_implementation_repair_semantics,
    require_implementation_semantic_successor,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class ReplayRepairOperationalAuthorityError(RuntimeError):
    """Durable Repair execution does not form one exact usable lineage."""


_REPAIR_OPEN_KEYS = {
    "episode",
    "failure_kind",
    "interrupted_action",
    "minimum_reproduction_evidence",
    "predecessor_repair_close_record_id",
    "resume_action",
    "root_cause",
    "scientific_trial_delta",
}
_REPAIR_ATTEMPT_KEYS = {
    "attempt_proof_hash",
    "cause_hash",
    "changed_dimension",
    "explanation",
    "failure_observation",
    "implementation_proof_hash",
    "job_hash",
    "job_id",
    "new_basis_hash",
    "new_evidence_hashes",
    "outcome",
    "previous_basis_hash",
    "prior_attempt_record_id",
    "repair_id",
    "reproduction_evidence_hashes",
    "resume_action",
    "schema",
    "scientific_failure_delta",
    "scientific_semantics_changed",
    "scientific_trial_delta",
    "verification_evidence_hashes",
}
_REPAIR_CLOSE_KEYS = {
    "attempt_record_id",
    "changed_cause_proof_hash",
    "changed_dimension",
    "effective_implementation_identity",
    "implementation_changed",
    "job_id",
    "previous_effective_implementation_identity",
    "prior_attempt_record_id",
    "repair_id",
    "resume_action",
    "scientific_failure_delta",
    "scientific_trial_delta",
    "verification_evidence_hashes",
}
_REPAIR_RESUME_KEYS = {
    "callable_identity",
    "effective_implementation_identity",
    "engine_entry_record_id",
    "execution",
    "repair_attempt_record_id",
    "repair_close_record_id",
    "repair_id",
    "runtime_entry_record_id",
}
_REPAIR_CHANGED_DIMENSIONS = {"cause", "information", "input", "implementation"}


def _is_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_ascii(value: object) -> bool:
    return type(value) is str and bool(value) and value.isascii()


def _is_digest_list(value: object, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_is_digest(item) for item in value)
        and value == sorted(set(value))
    )


def _require_repair_attempt_chain(
    index: LocalIndex | LocalIndexView,
    *,
    opened: IndexRecord,
    close: IndexRecord,
    declaration: IndexRecord,
    job_id: str,
    repair_id: str,
) -> IndexRecord:
    """Authenticate every failed basis and the terminal repaired attempt."""

    stream = f"repair-attempt:{repair_id}"
    head = index.event_head(stream)
    close_payload = close.payload
    terminal_attempt_id = close_payload.get("attempt_record_id")
    if (
        head is None
        or type(head.sequence) is not int
        or head.sequence < 1
        or head.record_id != terminal_attempt_id
    ):
        raise ReplayRepairOperationalAuthorityError(
            "implementation Repair attempt stream is incomplete"
        )
    prior_attempt_id: str | None = None
    prior_basis = opened.fingerprint
    prior_authority_sequence = opened.authority_sequence
    terminal: IndexRecord | None = None
    reproduction = opened.payload.get("minimum_reproduction_evidence")
    for sequence in range(1, head.sequence + 1):
        attempt = index.event_record(stream, sequence)
        payload = None if attempt is None else attempt.payload
        terminal_attempt = sequence == head.sequence
        expected_outcome = "repaired" if terminal_attempt else "failed"
        dimension = (
            None
            if not isinstance(payload, Mapping)
            else payload.get("changed_dimension")
        )
        semantic_present = (
            isinstance(payload, Mapping)
            and "semantic_equivalence_validation" in payload
        )
        semantic_required = terminal_attempt and dimension == "implementation"
        expected_keys = set(_REPAIR_ATTEMPT_KEYS)
        if semantic_required:
            expected_keys.add("semantic_equivalence_validation")
        new_evidence = (
            None
            if not isinstance(payload, Mapping)
            else payload.get("new_evidence_hashes")
        )
        verification = (
            None
            if not isinstance(payload, Mapping)
            else payload.get("verification_evidence_hashes")
        )
        attempt_reproduction = (
            None
            if not isinstance(payload, Mapping)
            else payload.get("reproduction_evidence_hashes")
        )
        proof_hash = (
            None
            if not isinstance(payload, Mapping)
            else payload.get("attempt_proof_hash")
        )
        new_basis = (
            None
            if not isinstance(payload, Mapping)
            else payload.get("new_basis_hash")
        )
        implementation_proof = (
            None
            if not isinstance(payload, Mapping)
            else payload.get("implementation_proof_hash")
        )
        expected_record_id = None
        if isinstance(payload, Mapping):
            identity_payload = dict(payload)
            identity_payload.pop("scientific_failure_delta", None)
            identity_payload.pop("scientific_trial_delta", None)
            expected_record_id = canonical_digest(
                domain="repair-attempt",
                payload=identity_payload,
            )
        if (
            attempt is None
            or not isinstance(payload, Mapping)
            or set(payload) != expected_keys
            or semantic_present is not semantic_required
            or attempt.kind != "repair-attempt"
            or attempt.status != expected_outcome
            or attempt.subject != f"Repair:{repair_id}"
            or attempt.event_stream != stream
            or attempt.event_sequence != sequence
            or attempt.record_id != expected_record_id
            or attempt.fingerprint != proof_hash
            or (terminal_attempt and head.fingerprint != attempt.fingerprint)
            or payload.get("schema") != "running_job_repair_attempt.v1"
            or payload.get("repair_id") != repair_id
            or payload.get("job_id") != job_id
            or payload.get("job_hash") != declaration.fingerprint
            or payload.get("cause_hash") != opened.fingerprint
            or payload.get("resume_action")
            != opened.payload.get("resume_action")
            or payload.get("outcome") != expected_outcome
            or dimension not in _REPAIR_CHANGED_DIMENSIONS
            or (terminal_attempt and dimension == "input")
            or payload.get("previous_basis_hash") != prior_basis
            or not _is_digest(new_basis)
            or new_basis == prior_basis
            or payload.get("prior_attempt_record_id") != prior_attempt_id
            or not _is_digest(proof_hash)
            or not _is_ascii(payload.get("explanation"))
            or payload.get("scientific_semantics_changed") is not False
            or payload.get("scientific_failure_delta") != 0
            or payload.get("scientific_trial_delta") != 0
            or attempt_reproduction != reproduction
            or not _is_digest_list(attempt_reproduction)
            or not _is_digest_list(new_evidence)
            or not _is_digest_list(verification)
            or new_basis not in new_evidence
            or bool(set(attempt_reproduction).intersection(new_evidence))
            or bool(set(attempt_reproduction).intersection(verification))
            or bool(set(new_evidence).intersection(verification))
            or (
                dimension == "implementation"
                and (
                    not _is_digest(implementation_proof)
                    or implementation_proof not in new_evidence
                )
            )
            or (dimension != "implementation" and implementation_proof is not None)
            or (
                expected_outcome == "failed"
                and not _is_ascii(payload.get("failure_observation"))
            )
            or (
                expected_outcome == "repaired"
                and payload.get("failure_observation") is not None
            )
            or type(prior_authority_sequence) is not int
            or type(attempt.authority_sequence) is not int
            or attempt.authority_sequence <= prior_authority_sequence
        ):
            raise ReplayRepairOperationalAuthorityError(
                "implementation Repair attempt chain is malformed"
            )
        prior_attempt_id = attempt.record_id
        prior_basis = str(new_basis)
        prior_authority_sequence = attempt.authority_sequence
        terminal = attempt
    if (
        terminal is None
        or terminal.record_id != terminal_attempt_id
        or terminal.authority_sequence != close.authority_sequence
        or terminal.authority_event_id != close.authority_event_id
        or terminal.payload.get("prior_attempt_record_id")
        != close_payload.get("prior_attempt_record_id")
        or terminal.payload.get("verification_evidence_hashes")
        != close_payload.get("verification_evidence_hashes")
        or terminal.payload.get("semantic_equivalence_validation")
        != close_payload.get("semantic_equivalence_validation")
    ):
        raise ReplayRepairOperationalAuthorityError(
            "implementation Repair terminal attempt differs from its close"
        )
    return terminal


def _require_repair_resume(
    index: LocalIndex | LocalIndexView,
    *,
    close: IndexRecord,
    declaration: IndexRecord,
    sequence: int,
) -> IndexRecord:
    job_id = declaration.record_id
    stream = f"job-resume:{job_id}"
    resume = index.event_record(stream, sequence)
    payload = None if resume is None else resume.payload
    execution = (
        None
        if not isinstance(payload, Mapping)
        else payload.get("execution")
    )
    spec = declaration.payload.get("spec")
    expected_record_id = (
        None
        if not isinstance(payload, Mapping)
        else canonical_digest(
            domain="job-repaired-execution-resume",
            payload=payload,
        )
    )
    if (
        resume is None
        or not isinstance(payload, Mapping)
        or set(payload) != _REPAIR_RESUME_KEYS
        or not isinstance(execution, Mapping)
        or set(execution)
        != {"job_hash", "job_id", "job_permit_id", "start_record_id"}
        or not isinstance(spec, Mapping)
        or resume.kind != "job-resumed"
        or resume.status != "validated"
        or resume.subject != f"Job:{job_id}"
        or resume.fingerprint != declaration.fingerprint
        or resume.event_stream != stream
        or resume.event_sequence != sequence
        or resume.record_id != expected_record_id
        or payload.get("callable_identity") != spec.get("callable_identity")
        or payload.get("effective_implementation_identity")
        != close.payload.get("effective_implementation_identity")
        or payload.get("repair_attempt_record_id")
        != close.payload.get("attempt_record_id")
        or payload.get("repair_close_record_id") != close.record_id
        or payload.get("repair_id") != close.payload.get("repair_id")
        or execution.get("job_id") != job_id
        or execution.get("job_hash") != declaration.fingerprint
        or not _is_digest(execution.get("job_permit_id"))
        or not _is_digest(execution.get("start_record_id"))
        or (
            payload.get("engine_entry_record_id") is not None
            and not _is_digest(payload.get("engine_entry_record_id"))
        )
        or (
            payload.get("runtime_entry_record_id") is not None
            and not _is_digest(payload.get("runtime_entry_record_id"))
        )
        or type(close.authority_sequence) is not int
        or type(resume.authority_sequence) is not int
        or resume.authority_sequence <= close.authority_sequence
    ):
        raise ReplayRepairOperationalAuthorityError(
            "repaired Job engine re-entry is malformed"
        )
    return resume


def require_repair_chain(
    index: LocalIndex | LocalIndexView,
    *,
    job_id: str,
    declared_implementation_identity: str,
    expected_implementation_identity: str,
    trigger_repair_close_record_id: str,
    declaration: IndexRecord,
    executable_id: str,
) -> tuple[IndexRecord, ...]:
    """Reconstruct every Repair episode and its engine re-entry in order."""

    stream = f"job-repair:{job_id}"
    head = index.event_head(stream)
    if (
        head is None
        or type(head.sequence) is not int
        or head.sequence < 1
        or head.record_id != trigger_repair_close_record_id
    ):
        raise ReplayRepairOperationalAuthorityError(
            "post-Repair admission does not name the current Job Repair head"
        )
    closes: list[IndexRecord] = []
    opens: list[IndexRecord] = []
    effective = declared_implementation_identity
    prior_authority_sequence = declaration.authority_sequence
    implementation_changed = False
    prior_implementation_close: IndexRecord | None = None
    for sequence in range(1, head.sequence + 1):
        close = index.event_record(stream, sequence)
        payload = None if close is None else close.payload
        predecessor_close_id = None if not closes else closes[-1].record_id
        previous = (
            None
            if not isinstance(payload, Mapping)
            else payload.get("previous_effective_implementation_identity")
        )
        next_identity = (
            None
            if not isinstance(payload, Mapping)
            else payload.get("effective_implementation_identity")
        )
        changed = (
            False
            if not isinstance(payload, Mapping)
            else payload.get("implementation_changed")
        )
        attempt_id = (
            None
            if not isinstance(payload, Mapping)
            else payload.get("attempt_record_id")
        )
        attempt = (
            None
            if type(attempt_id) is not str
            else index.get("repair-attempt", attempt_id)
        )
        repair_id = (
            None
            if not isinstance(payload, Mapping)
            else payload.get("repair_id")
        )
        opened = (
            None
            if type(repair_id) is not str
            else index.get("repair-open", repair_id)
        )
        opened_payload = None if opened is None else opened.payload
        cause_manifest = (
            None
            if not isinstance(opened_payload, Mapping)
            else {
                key: opened_payload.get(key)
                for key in (
                    "failure_kind",
                    "minimum_reproduction_evidence",
                    "root_cause",
                    "interrupted_action",
                )
            }
        )
        cause_hash = (
            None
            if cause_manifest is None
            else canonical_digest(domain="repair-cause", payload=cause_manifest)
        )
        expected_repair_id = (
            None
            if cause_hash is None
            else "repair:"
            + canonical_digest(
                domain="repair",
                payload={
                    "cause_hash": cause_hash,
                    "episode": sequence,
                    "job_id": job_id,
                    "predecessor_repair_close_record_id": predecessor_close_id,
                },
            )
        )
        dimension = (
            None
            if not isinstance(payload, Mapping)
            else payload.get("changed_dimension")
        )
        semantic_present = (
            isinstance(payload, Mapping)
            and "semantic_equivalence_validation" in payload
        )
        expected_close_keys = set(_REPAIR_CLOSE_KEYS)
        if dimension == "implementation":
            expected_close_keys.add("semantic_equivalence_validation")
        expected_close_id = None
        if isinstance(payload, Mapping) and type(repair_id) is str:
            close_identity_payload: dict[str, Any] = {
                "repair_id": repair_id,
                "proof": payload.get("changed_cause_proof_hash"),
            }
            if semantic_present:
                close_identity_payload["semantic_equivalence_validation"] = (
                    payload.get("semantic_equivalence_validation")
                )
            expected_close_id = canonical_digest(
                domain="repair-close",
                payload=close_identity_payload,
            )
        spec = declaration.payload.get("spec")
        if (
            close is None
            or not isinstance(payload, Mapping)
            or set(payload) != expected_close_keys
            or semantic_present is not (dimension == "implementation")
            or close.kind != "repair-close"
            or close.status != "repaired"
            or close.subject != f"Job:{job_id}"
            or close.event_stream != stream
            or close.event_sequence != sequence
            or close.record_id != expected_close_id
            or (sequence == head.sequence and head.fingerprint != close.fingerprint)
            or payload.get("job_id") != job_id
            or type(repair_id) is not str
            or repair_id != expected_repair_id
            or opened is None
            or not isinstance(opened_payload, Mapping)
            or set(opened_payload) != _REPAIR_OPEN_KEYS
            or opened.kind != "repair-open"
            or opened.record_id != repair_id
            or opened.status != "open"
            or opened.subject != f"Job:{job_id}"
            or opened.event_stream is not None
            or opened.event_sequence is not None
            or opened.fingerprint != cause_hash
            or opened_payload.get("episode") != sequence
            or opened_payload.get("failure_kind") != "engineering"
            or opened_payload.get("predecessor_repair_close_record_id")
            != predecessor_close_id
            or opened_payload.get("scientific_trial_delta") != 0
            or not isinstance(spec, Mapping)
            or opened_payload.get("interrupted_action")
            != spec.get("callable_identity")
            or not _is_ascii(opened_payload.get("root_cause"))
            or not _is_ascii(opened_payload.get("resume_action"))
            or not _is_digest_list(
                opened_payload.get("minimum_reproduction_evidence")
            )
            or not _is_digest(payload.get("changed_cause_proof_hash"))
            or close.fingerprint != payload.get("changed_cause_proof_hash")
            or type(prior_authority_sequence) is not int
            or type(opened.authority_sequence) is not int
            or type(close.authority_sequence) is not int
            or opened.authority_sequence <= prior_authority_sequence
            or close.authority_sequence <= opened.authority_sequence
            or previous != effective
            or not _is_digest(next_identity)
            or dimension not in _REPAIR_CHANGED_DIMENSIONS
            or dimension == "input"
            or payload.get("resume_action")
            != opened_payload.get("resume_action")
            or payload.get("prior_attempt_record_id")
            != (
                None
                if attempt is None
                else attempt.payload.get("prior_attempt_record_id")
            )
            or not _is_digest_list(payload.get("verification_evidence_hashes"))
            or payload.get("scientific_failure_delta") != 0
            or payload.get("scientific_trial_delta") != 0
        ):
            raise ReplayRepairOperationalAuthorityError(
                "post-Repair admission has an invalid implementation Repair chain"
            )
        attempt = _require_repair_attempt_chain(
            index,
            opened=opened,
            close=close,
            declaration=declaration,
            job_id=job_id,
            repair_id=repair_id,
        )
        if (
            attempt.payload.get("changed_dimension") != dimension
            or attempt.payload.get("attempt_proof_hash")
            != payload.get("changed_cause_proof_hash")
            or attempt.payload.get("resume_action")
            != payload.get("resume_action")
            or attempt.fingerprint != close.fingerprint
        ):
            raise ReplayRepairOperationalAuthorityError(
                "post-Repair close differs from its terminal attempt"
            )
        if dimension == "implementation":
            if (
                changed is not True
                or next_identity == effective
                or attempt.payload.get("new_basis_hash") != next_identity
                or attempt.payload.get("semantic_equivalence_validation")
                != payload.get("semantic_equivalence_validation")
            ):
                raise ReplayRepairOperationalAuthorityError(
                    "post-Repair admission has an invalid implementation change"
                )
            try:
                require_implementation_repair_semantics(
                    index,
                    close=close,
                    executable_id=executable_id,
                )
            except ReplayRepairScientificAuthorityError as exc:
                raise ReplayRepairOperationalAuthorityError(str(exc)) from exc
            if prior_implementation_close is not None:
                try:
                    require_implementation_semantic_successor(
                        predecessor_close=prior_implementation_close,
                        successor_close=close,
                    )
                except ReplayRepairScientificAuthorityError as exc:
                    raise ReplayRepairOperationalAuthorityError(str(exc)) from exc
            prior_implementation_close = close
            implementation_changed = True
        elif changed is not False or next_identity != effective:
            raise ReplayRepairOperationalAuthorityError(
                "non-implementation Repair changed implementation authority"
            )
        effective = next_identity
        opens.append(opened)
        closes.append(close)
        prior_authority_sequence = close.authority_sequence
    resume_stream = f"job-resume:{job_id}"
    resume_head = index.event_head(resume_stream)
    if (
        resume_head is None
        or resume_head.sequence != len(closes)
        or not closes
    ):
        raise ReplayRepairOperationalAuthorityError(
            "post-Repair admission lacks the exact engine re-entry chain"
        )
    resumes = tuple(
        _require_repair_resume(
            index,
            close=close,
            declaration=declaration,
            sequence=sequence,
        )
        for sequence, close in enumerate(closes, start=1)
    )
    if (
        resumes[-1].record_id != resume_head.record_id
        or resume_head.fingerprint != resumes[-1].fingerprint
        or any(
            type(resume.authority_sequence) is not int
            or type(opens[offset + 1].authority_sequence) is not int
            or resume.authority_sequence >= opens[offset + 1].authority_sequence
            for offset, resume in enumerate(resumes[:-1])
        )
    ):
        raise ReplayRepairOperationalAuthorityError(
            "post-Repair engine re-entry order is malformed"
        )
    if (
        not closes
        or closes[-1].record_id != trigger_repair_close_record_id
        or not implementation_changed
        or prior_implementation_close is None
        or effective != expected_implementation_identity
    ):
        raise ReplayRepairOperationalAuthorityError(
            "post-Repair admission implementation lineage is not exact"
        )
    return tuple(closes)


__all__ = [
    "ReplayRepairOperationalAuthorityError",
    "require_repair_chain",
]
