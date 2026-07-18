"""Durable authority for zero-credit prospective Repair observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.repair_candidate import (
    RepairCandidateError,
    is_zero_credit_repair_observation_mode,
    parse_repair_candidate,
    parse_repair_evaluation,
)
from axiom_rift.operations.repair_validation import (
    REGISTERED_REPAIR_AUTHORITY_SCHEMA,
    RepairValidationError,
    require_stored_repair_candidate_validation,
)
from axiom_rift.storage.evidence import EvidenceStore
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class RepairObservationAuthorityError(ValueError):
    """A zero-credit Repair observation stream is malformed or incomplete."""


REPAIR_VALIDATION_OBSERVATION_SCHEMA = (
    "engineering_repair_validation_observation.v1"
)

_OBSERVATION_KEYS = {
    "basis_advance",
    "candidate",
    "candidate_delta",
    "candidate_hash",
    "evaluation",
    "holdout_reveal_delta",
    "registered_candidate_validation",
    "release_delta",
    "repair_attempt_delta",
    "repair_authority_schema",
    "repair_id",
    "schema",
    "scientific_failure_delta",
    "scientific_trial_delta",
}


def _digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _exact_zero(value: object) -> bool:
    return type(value) is int and value == 0


def _accepted_context_before(
    attempts: Sequence[IndexRecord],
    *,
    observation_authority_sequence: int,
    cause_hash: str,
) -> tuple[str | None, str, frozenset[str]]:
    prior_record_id: str | None = None
    previous_basis = cause_hash
    used_bases = {cause_hash}
    prior_authority_sequence: int | None = None
    for attempt in attempts:
        authority_sequence = attempt.authority_sequence
        new_basis = attempt.payload.get("new_basis_hash")
        if (
            type(authority_sequence) is not int
            or not _digest(new_basis)
            or (
                prior_authority_sequence is not None
                and authority_sequence <= prior_authority_sequence
            )
        ):
            raise RepairObservationAuthorityError(
                "accepted Repair attempt chronology is malformed"
            )
        prior_authority_sequence = authority_sequence
        if authority_sequence >= observation_authority_sequence:
            break
        prior_record_id = attempt.record_id
        previous_basis = str(new_basis)
        used_bases.add(previous_basis)
    return prior_record_id, previous_basis, frozenset(used_bases)


def require_repair_validation_observation_stream(
    index: LocalIndex | LocalIndexView,
    *,
    repair_id: str,
    job_id: str,
    job_hash: str,
    cause_hash: str,
    reproduction_evidence_hashes: Sequence[str],
    resume_action: str,
    mission_id: str,
    expected_scope: str,
    accepted_attempts: Sequence[IndexRecord] = (),
    evidence: EvidenceStore | None = None,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any] | None]:
    """Authenticate and normalize the exact zero-credit observation stream."""

    stream = f"repair-validation-observation:{repair_id}"
    prior_attempt_authority: int | None = None
    for sequence, attempt in enumerate(accepted_attempts, start=1):
        authority_sequence = attempt.authority_sequence
        if (
            attempt.kind != "repair-attempt"
            or attempt.status != "failed"
            or attempt.subject != f"Repair:{repair_id}"
            or attempt.event_stream != f"repair-attempt:{repair_id}"
            or attempt.event_sequence != sequence
            or attempt.payload.get("repair_id") != repair_id
            or attempt.payload.get("job_id") != job_id
            or attempt.payload.get("job_hash") != job_hash
            or attempt.payload.get("cause_hash") != cause_hash
            or type(attempt.event_sequence) is not int
            or attempt.event_sequence != sequence
            or type(authority_sequence) is not int
            or (
                prior_attempt_authority is not None
                and authority_sequence <= prior_attempt_authority
            )
        ):
            raise RepairObservationAuthorityError(
                "accepted Repair attempt stream is malformed"
            )
        prior_attempt_authority = authority_sequence
    head = index.event_head(stream)
    if head is None:
        return (), None
    if type(head.sequence) is not int or head.sequence < 1:
        raise RepairObservationAuthorityError(
            "Repair validation observation head is malformed"
        )
    normalized: list[dict[str, Any]] = []
    prior_bound_observations: list[dict[str, Any]] = []
    prior_observation_head: dict[str, Any] | None = None
    prior_authority_sequence: int | None = None
    terminal: IndexRecord | None = None
    for sequence in range(1, head.sequence + 1):
        record = index.event_record(stream, sequence)
        payload = None if record is None else record.payload
        if not isinstance(payload, Mapping):
            raise RepairObservationAuthorityError(
                "Repair validation observation is unavailable"
            )
        candidate_value = payload.get("candidate")
        evaluation_value = payload.get("evaluation")
        authority_sequence = record.authority_sequence
        if (
            not isinstance(candidate_value, Mapping)
            or not isinstance(evaluation_value, Mapping)
            or type(authority_sequence) is not int
        ):
            raise RepairObservationAuthorityError(
                "Repair validation observation content is malformed"
            )
        (
            expected_prior_id,
            expected_previous_basis,
            used_bases,
        ) = _accepted_context_before(
            accepted_attempts,
            observation_authority_sequence=authority_sequence,
            cause_hash=cause_hash,
        )
        try:
            candidate = parse_repair_candidate(
                canonical_bytes(dict(candidate_value)),
                repair_id=repair_id,
                job_id=job_id,
                job_hash=job_hash,
                cause_hash=cause_hash,
                previous_basis_hash=expected_previous_basis,
                prior_attempt_record_id=expected_prior_id,
                reproduction_evidence_hashes=reproduction_evidence_hashes,
                resume_action=resume_action,
                expected_prior_validation_observation_head=(
                    prior_observation_head
                ),
                expected_bound_validation_observations=(
                    prior_bound_observations
                ),
            )
        except (RepairCandidateError, TypeError, ValueError) as exc:
            raise RepairObservationAuthorityError(
                "Repair validation observation candidate is malformed"
            ) from exc
        if candidate.new_basis_hash in used_bases:
            raise RepairObservationAuthorityError(
                "Repair validation observation reuses an accepted basis"
            )
        registered = payload.get("registered_candidate_validation")
        if registered is None:
            try:
                evaluation = parse_repair_evaluation(
                    canonical_bytes(dict(evaluation_value)),
                    candidate_hash=candidate.sha256,
                    validator_id=str(evaluation_value.get("validator_id")),
                    validation_plan_hash=str(
                        evaluation_value.get("validation_plan_hash")
                    ),
                    registry_trace_hash=None,
                )
            except (RepairCandidateError, TypeError, ValueError) as exc:
                raise RepairObservationAuthorityError(
                    "unregistered Repair observation evaluation is malformed"
                ) from exc
            if evaluation.mode != "validation_unavailable":
                raise RepairObservationAuthorityError(
                    "only validation_unavailable may omit a registered trace"
                )
            if evaluation.payload() != dict(evaluation_value):
                raise RepairObservationAuthorityError(
                    "unregistered Repair observation evaluation is not canonical"
                )
            trace_sha256 = None
        else:
            if not isinstance(registered, Mapping):
                raise RepairObservationAuthorityError(
                    "Repair observation registered trace is malformed"
                )
            try:
                stored = require_stored_repair_candidate_validation(
                    candidate=candidate,
                    repair_validation=registered,
                    mission_id=mission_id,
                    evidence=evidence,
                    expected_scope=expected_scope,
                )
            except (RepairValidationError, TypeError, ValueError) as exc:
                raise RepairObservationAuthorityError(
                    "Repair observation registered trace is invalid"
                ) from exc
            if stored.get("evaluation") != dict(evaluation_value):
                raise RepairObservationAuthorityError(
                    "Repair observation differs from its registered evaluation"
                )
            mode = evaluation_value.get("mode")
            if not is_zero_credit_repair_observation_mode(mode):
                raise RepairObservationAuthorityError(
                    "accepted Repair evaluation entered the observation stream"
                )
            trace_sha256 = stored.get("trace_sha256")
            if not _digest(trace_sha256):
                raise RepairObservationAuthorityError(
                    "Repair observation trace identity is malformed"
                )
            evaluation = None
        information_hashes = sorted(
            {
                candidate.sha256,
                str(evaluation_value.get("validation_plan_hash")),
                *(
                    ()
                    if evaluation_value.get("new_failure_manifest_hash") is None
                    else (
                        str(
                            evaluation_value.get(
                                "new_failure_manifest_hash"
                            )
                        ),
                    )
                ),
            }
        )
        if not all(_digest(identity) for identity in information_hashes):
            raise RepairObservationAuthorityError(
                "Repair observation new-information identity is malformed"
            )
        identity_payload = {
            "candidate_hash": candidate.sha256,
            "evaluation": dict(evaluation_value),
            "registered_candidate_validation": (
                None if registered is None else dict(registered)
            ),
            "repair_id": repair_id,
            "schema": REPAIR_VALIDATION_OBSERVATION_SCHEMA,
        }
        expected_record_id = canonical_digest(
            domain="repair-validation-observation",
            payload=identity_payload,
        )
        mode = evaluation_value.get("mode")
        if (
            set(payload) != _OBSERVATION_KEYS
            or payload.get("schema") != REPAIR_VALIDATION_OBSERVATION_SCHEMA
            or payload.get("repair_authority_schema")
            != REGISTERED_REPAIR_AUTHORITY_SCHEMA
            or payload.get("repair_id") != repair_id
            or payload.get("candidate_hash") != candidate.sha256
            or payload.get("candidate") != candidate.payload()
            or not is_zero_credit_repair_observation_mode(mode)
            or record.kind != "repair-validation-observation"
            or record.record_id != expected_record_id
            or record.subject != f"Repair:{repair_id}"
            or record.status != mode
            or record.fingerprint != candidate.sha256
            or record.event_stream != stream
            or type(record.event_sequence) is not int
            or record.event_sequence != sequence
            or payload.get("basis_advance") is not False
            or not _exact_zero(payload.get("candidate_delta"))
            or not _exact_zero(payload.get("holdout_reveal_delta"))
            or not _exact_zero(payload.get("release_delta"))
            or not _exact_zero(payload.get("repair_attempt_delta"))
            or not _exact_zero(payload.get("scientific_failure_delta"))
            or not _exact_zero(payload.get("scientific_trial_delta"))
            or (
                prior_authority_sequence is not None
                and authority_sequence <= prior_authority_sequence
            )
        ):
            raise RepairObservationAuthorityError(
                "Repair validation observation stream is malformed"
            )
        normalized.append(
            {
                "candidate_hash": candidate.sha256,
                "evaluation": dict(evaluation_value),
                "new_information_evidence_hashes": information_hashes,
                "observation_record_id": record.record_id,
                "observation_sequence": sequence,
                "registered_validation_trace_sha256": trace_sha256,
            }
        )
        prior_authority_sequence = authority_sequence
        terminal = record
        prior_bound_observations.append(
            {
                "new_information_evidence_hashes": information_hashes,
                "observation_record_id": record.record_id,
            }
        )
        prior_observation_head = {
            "fingerprint": record.fingerprint,
            "record_id": record.record_id,
            "sequence": sequence,
        }
    if (
        terminal is None
        or head.record_kind != terminal.kind
        or head.record_id != terminal.record_id
        or head.fingerprint != terminal.fingerprint
    ):
        raise RepairObservationAuthorityError(
            "Repair validation observation head differs from its stream"
        )
    return tuple(normalized), {
        "fingerprint": head.fingerprint,
        "record_id": head.record_id,
        "sequence": head.sequence,
    }


__all__ = [
    "REPAIR_VALIDATION_OBSERVATION_SCHEMA",
    "RepairObservationAuthorityError",
    "require_repair_validation_observation_stream",
]
