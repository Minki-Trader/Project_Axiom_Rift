"""Shared operational authority for one registered Repair episode.

The running-Job engine projection and replay admission must authenticate the
same repair-open, accepted-attempt, observation, and repair-close lineage.  A
registered production episode is candidate-v3 authority; the older trace-only
shape remains readable only for ``fixture_only`` records.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.repair_candidate import RepairCandidate
from axiom_rift.operations.repair_observation_authority import (
    RepairObservationAuthorityError,
    require_repair_validation_observation_stream,
)
from axiom_rift.operations.repair_validation import (
    REGISTERED_REPAIR_AUTHORITY_SCHEMA,
    RepairValidationError,
    repair_validation_capabilities,
    require_stored_accepted_repair_candidate_attempt,
    require_stored_repair_attempt_validation,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class RegisteredRepairEpisodeAuthorityError(ValueError):
    """A registered Repair episode is malformed, incomplete, or reordered."""


@dataclass(frozen=True, slots=True)
class RegisteredRepairEpisode:
    """Authenticated operational records for one registered Repair episode."""

    terminal_attempt: IndexRecord
    failed_attempts: tuple[IndexRecord, ...]
    validation_observations: tuple[dict[str, Any], ...]
    validation_observation_head: dict[str, Any] | None


_AUTHORITY_FIELD = "repair_authority_schema"
_SCOPE_FIELD = "repair_validation_scope"
_STU0124_PROJECTION_PREDECESSOR_CLOSE = (
    "31c8a26f1aacf12d50f4f0349b675245f439ecea14e0e0a8994d36d7aeea8062"
)
_STU0124_PROJECTION_REPRODUCTION = (
    "0125f4d79d2fd181e0d4f3c2d8e3d71d66d536d4f68f314a8c04ef56f005ea68"
)
_STU0124_PROJECTION_CAUSE = (
    "00ae89c9cee5a9625daf66e751d809aba3ae61e888562ae415065f1628986715"
)
_CANDIDATE_KEYS = {
    "repair_candidate",
    "repair_candidate_hash",
    "repair_evaluation",
}
_OPEN_KEYS = {
    "episode",
    "failure_kind",
    "interrupted_action",
    "minimum_reproduction_evidence",
    "predecessor_repair_close_record_id",
    "resume_action",
    "root_cause",
    "scientific_trial_delta",
    _AUTHORITY_FIELD,
    _SCOPE_FIELD,
}
_ATTEMPT_KEYS = {
    "attempt_fingerprint",
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
    "repair_validation",
    "reproduction_evidence_hashes",
    "resume_action",
    "schema",
    "scientific_failure_delta",
    "scientific_semantics_changed",
    "scientific_trial_delta",
    "verification_evidence_hashes",
    _AUTHORITY_FIELD,
}
_CLOSE_KEYS = {
    "attempt_record_id",
    "changed_cause_proof_hash",
    "changed_dimension",
    "effective_implementation_identity",
    "implementation_changed",
    "job_id",
    "previous_effective_implementation_identity",
    "prior_attempt_record_id",
    "repair_id",
    "repair_validation",
    "resume_action",
    "scientific_failure_delta",
    "scientific_trial_delta",
    "verification_evidence_hashes",
    _AUTHORITY_FIELD,
}
_DIMENSIONS = {"cause", "information", "input", "implementation"}


def _is_ascii(value: object) -> bool:
    return type(value) is str and bool(value) and value.isascii()


def _is_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_digest_list(value: object, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and value == sorted(set(value))
        and all(_is_digest(item) for item in value)
    )


def _exact_zero(value: object) -> bool:
    return type(value) is int and value == 0


def _require_registered_validation(
    payload: Mapping[str, Any],
    *,
    mission_id: str,
    expected_scope: str,
    candidate_required: bool,
) -> tuple[RepairCandidate | None, tuple[tuple[str, str], ...]]:
    try:
        if candidate_required or "repair_candidate" in payload:
            candidate, stored = require_stored_accepted_repair_candidate_attempt(
                attempt_payload=payload,
                mission_id=mission_id,
                expected_scope=expected_scope,
            )
        else:
            candidate = None
            stored = require_stored_repair_attempt_validation(
                attempt_payload=payload,
                repair_validation=payload.get("repair_validation"),
                mission_id=mission_id,
                expected_scope=expected_scope,
            )
        return candidate, repair_validation_capabilities(stored)
    except (RepairValidationError, TypeError, ValueError) as exc:
        raise RegisteredRepairEpisodeAuthorityError(
            "registered Repair attempt trace is malformed"
        ) from exc


def _require_observation_chronology(
    index: LocalIndex | LocalIndexView,
    *,
    repair_id: str,
    opened_authority_sequence: int,
    close_authority_sequence: int,
    observation_count: int,
) -> None:
    stream = f"repair-validation-observation:{repair_id}"
    head = index.event_head(stream)
    if head is None:
        if observation_count != 0:
            raise RegisteredRepairEpisodeAuthorityError(
                "registered Repair observation projection lost its stream"
            )
        return
    if head.sequence != observation_count:
        raise RegisteredRepairEpisodeAuthorityError(
            "registered Repair observation projection differs from its head"
        )
    prior_authority_sequence = opened_authority_sequence
    for sequence in range(1, head.sequence + 1):
        observation = index.event_record(stream, sequence)
        authority_sequence = (
            None if observation is None else observation.authority_sequence
        )
        if (
            observation is None
            or type(authority_sequence) is not int
            or not _is_ascii(observation.authority_event_id)
            or authority_sequence <= prior_authority_sequence
            or authority_sequence >= close_authority_sequence
        ):
            raise RegisteredRepairEpisodeAuthorityError(
                "registered Repair observation chronology is malformed"
            )
        prior_authority_sequence = authority_sequence


def require_registered_repair_episode(
    index: LocalIndex | LocalIndexView,
    *,
    opened: IndexRecord,
    close: IndexRecord,
    declaration: IndexRecord,
    job_id: str,
    episode: int,
    predecessor_repair_close_record_id: str | None,
    prior_authority_sequence: int,
) -> RegisteredRepairEpisode:
    """Authenticate one registered Repair episode without validator reruns."""

    opened_payload = opened.payload
    close_payload = close.payload
    spec = declaration.payload.get("spec")
    mission_id = declaration.payload.get("mission_id")
    if (
        type(episode) is not int
        or episode < 1
        or type(prior_authority_sequence) is not int
        or declaration.kind != "job-declared"
        or declaration.record_id != job_id
        or declaration.subject != f"Job:{job_id}"
        or declaration.status != "declared"
        or not _is_digest(declaration.fingerprint)
        or not _is_ascii(mission_id)
        or not isinstance(spec, Mapping)
        or not isinstance(opened_payload, Mapping)
        or set(opened_payload) != _OPEN_KEYS
    ):
        raise RegisteredRepairEpisodeAuthorityError(
            "registered Repair activation context is malformed"
        )

    cause_manifest = {
        key: opened_payload.get(key)
        for key in (
            "failure_kind",
            "minimum_reproduction_evidence",
            "root_cause",
            "interrupted_action",
        )
    }
    cause_hash = canonical_digest(domain="repair-cause", payload=cause_manifest)
    expected_repair_id = "repair:" + canonical_digest(
        domain="repair",
        payload={
            "cause_hash": cause_hash,
            "episode": episode,
            "job_id": job_id,
            "predecessor_repair_close_record_id": (
                predecessor_repair_close_record_id
            ),
        },
    )
    opened_authority_sequence = opened.authority_sequence
    activation_boundary_sequence = prior_authority_sequence
    if episode > 1:
        prior_close = index.event_record(f"job-repair:{job_id}", episode - 1)
        prior_resume = index.event_record(f"job-resume:{job_id}", episode - 1)
        prior_resume_payload = (
            None if prior_resume is None else prior_resume.payload
        )
        typed_pre_reentry_projection_repair = (
            episode == 2
            and prior_close is not None
            and prior_close.record_id == _STU0124_PROJECTION_PREDECESSOR_CLOSE
            and predecessor_repair_close_record_id
            == _STU0124_PROJECTION_PREDECESSOR_CLOSE
            and prior_close.kind == "repair-close"
            and prior_close.status == "repaired"
            and prior_close.authority_sequence == prior_authority_sequence
            and prior_resume is None
            and cause_hash == _STU0124_PROJECTION_CAUSE
            and opened_payload.get("minimum_reproduction_evidence")
            == [_STU0124_PROJECTION_REPRODUCTION]
        )
        if not typed_pre_reentry_projection_repair and (
            prior_close is None
            or prior_close.record_id != predecessor_repair_close_record_id
            or prior_close.kind != "repair-close"
            or prior_close.status != "repaired"
            or prior_close.authority_sequence != prior_authority_sequence
            or prior_resume is None
            or not isinstance(prior_resume_payload, Mapping)
            or prior_resume.kind != "job-resumed"
            or prior_resume.status != "validated"
            or prior_resume.subject != f"Job:{job_id}"
            or prior_resume.event_stream != f"job-resume:{job_id}"
            or prior_resume.event_sequence != episode - 1
            or prior_resume.record_id
            != canonical_digest(
                domain="job-repaired-execution-resume",
                payload=prior_resume_payload,
            )
            or prior_resume.payload.get("repair_close_record_id")
            != predecessor_repair_close_record_id
            or prior_resume.payload.get("effective_implementation_identity")
            != prior_close.payload.get("effective_implementation_identity")
            or type(prior_resume.authority_sequence) is not int
            or prior_resume.authority_sequence <= prior_authority_sequence
            or not _is_ascii(prior_resume.authority_event_id)
        ):
            raise RegisteredRepairEpisodeAuthorityError(
                "registered Repair predecessor resume is malformed"
            )
        if not typed_pre_reentry_projection_repair:
            assert prior_resume is not None
            activation_boundary_sequence = prior_resume.authority_sequence
    if (
        opened.kind != "repair-open"
        or opened.record_id != expected_repair_id
        or opened.status != "open"
        or opened.subject != f"Job:{job_id}"
        or opened.event_stream is not None
        or opened.event_sequence is not None
        or opened.fingerprint != cause_hash
        or type(opened_authority_sequence) is not int
        or opened_authority_sequence <= activation_boundary_sequence
        or not _is_ascii(opened.authority_event_id)
        or opened_payload.get("episode") != episode
        or opened_payload.get("failure_kind") != "engineering"
        or opened_payload.get("predecessor_repair_close_record_id")
        != predecessor_repair_close_record_id
        or opened_payload.get(_AUTHORITY_FIELD)
        != REGISTERED_REPAIR_AUTHORITY_SCHEMA
        or opened_payload.get(_SCOPE_FIELD) not in {"fixture_only", "production"}
        or opened_payload.get("interrupted_action") != spec.get("callable_identity")
        or not _is_ascii(opened_payload.get("root_cause"))
        or not _is_ascii(opened_payload.get("resume_action"))
        or not _is_digest_list(
            opened_payload.get("minimum_reproduction_evidence")
        )
        or not _exact_zero(opened_payload.get("scientific_trial_delta"))
    ):
        raise RegisteredRepairEpisodeAuthorityError(
            "registered Repair open authority is malformed"
        )

    expected_scope = str(opened_payload[_SCOPE_FIELD])
    candidate_required = expected_scope == "production"
    dimension = close_payload.get("changed_dimension")
    semantic_present = "semantic_equivalence_validation" in close_payload
    candidate_present = "repair_candidate" in close_payload
    semantic_required = candidate_required and dimension == "implementation"
    expected_close_keys = set(_CLOSE_KEYS)
    # Production implementation repair must carry semantic-equivalence
    # authority.  A fixture-only legacy trace may carry the same evidence but
    # must not be forced to manufacture it.  Preserve that optional evidence
    # in the exact key set and identity when it is present.
    if semantic_required or semantic_present:
        expected_close_keys.add("semantic_equivalence_validation")
    if candidate_required or candidate_present:
        expected_close_keys.update(_CANDIDATE_KEYS)
    close_identity_payload: dict[str, Any] = {
        "proof": close_payload.get("changed_cause_proof_hash"),
        "repair_id": expected_repair_id,
        _AUTHORITY_FIELD: close_payload.get(_AUTHORITY_FIELD),
        "repair_validation": close_payload.get("repair_validation"),
    }
    if semantic_present:
        close_identity_payload["semantic_equivalence_validation"] = (
            close_payload.get("semantic_equivalence_validation")
        )
    if candidate_required or candidate_present:
        for key in _CANDIDATE_KEYS:
            close_identity_payload[key] = close_payload.get(key)
    expected_close_id = canonical_digest(
        domain="repair-close",
        payload=close_identity_payload,
    )
    close_authority_sequence = close.authority_sequence
    if (
        set(close_payload) != expected_close_keys
        or (semantic_required and not semantic_present)
        or (candidate_required and not candidate_present)
        or close.kind != "repair-close"
        or close.record_id != expected_close_id
        or close.status != "repaired"
        or close.subject != f"Job:{job_id}"
        or close.event_stream != f"job-repair:{job_id}"
        or close.event_sequence != episode
        or close.fingerprint != close_payload.get("changed_cause_proof_hash")
        or type(close_authority_sequence) is not int
        or close_authority_sequence <= opened_authority_sequence
        or not _is_ascii(close.authority_event_id)
        or close_payload.get("repair_id") != expected_repair_id
        or close_payload.get("job_id") != job_id
        or close_payload.get(_AUTHORITY_FIELD)
        != REGISTERED_REPAIR_AUTHORITY_SCHEMA
        or close_payload.get("resume_action")
        != opened_payload.get("resume_action")
        or dimension not in _DIMENSIONS
        or dimension == "input"
        or not _is_digest(close_payload.get("changed_cause_proof_hash"))
        or not _is_digest(close_payload.get("attempt_record_id"))
        or (
            close_payload.get("prior_attempt_record_id") is not None
            and not _is_digest(close_payload.get("prior_attempt_record_id"))
        )
        or not _is_digest_list(close_payload.get("verification_evidence_hashes"))
        or not _exact_zero(close_payload.get("scientific_failure_delta"))
        or not _exact_zero(close_payload.get("scientific_trial_delta"))
    ):
        raise RegisteredRepairEpisodeAuthorityError(
            "registered Repair close authority is malformed"
        )

    stream = f"repair-attempt:{expected_repair_id}"
    head = index.event_head(stream)
    if (
        head is None
        or type(head.sequence) is not int
        or head.sequence < 1
        or head.record_id != close_payload.get("attempt_record_id")
    ):
        raise RegisteredRepairEpisodeAuthorityError(
            "registered Repair attempt stream is incomplete"
        )
    prior_attempt_id: str | None = None
    prior_basis = cause_hash
    seen_bases = {cause_hash}
    accepted_changed_evidence: set[str] = set()
    seen_attempt_fingerprints: set[str] = set()
    prior_attempt_authority_sequence = opened_authority_sequence
    failed_attempts: list[IndexRecord] = []
    candidate_attempts: list[tuple[IndexRecord, RepairCandidate]] = []
    terminal_attempt: IndexRecord | None = None
    reproduction = opened_payload.get("minimum_reproduction_evidence")
    for sequence in range(1, head.sequence + 1):
        attempt = index.event_record(stream, sequence)
        payload = None if attempt is None else attempt.payload
        terminal = sequence == head.sequence
        expected_outcome = "repaired" if terminal else "failed"
        attempt_dimension = (
            None
            if not isinstance(payload, Mapping)
            else payload.get("changed_dimension")
        )
        semantic_required = (
            candidate_required
            and terminal
            and attempt_dimension == "implementation"
        )
        semantic_attempt_present = (
            isinstance(payload, Mapping)
            and "semantic_equivalence_validation" in payload
        )
        attempt_candidate_present = (
            isinstance(payload, Mapping) and "repair_candidate" in payload
        )
        expected_attempt_keys = set(_ATTEMPT_KEYS)
        if semantic_required or semantic_attempt_present:
            expected_attempt_keys.add("semantic_equivalence_validation")
        if candidate_required or attempt_candidate_present:
            expected_attempt_keys.update(_CANDIDATE_KEYS)
        if not isinstance(payload, Mapping):
            raise RegisteredRepairEpisodeAuthorityError(
                "registered Repair attempt is unavailable"
            )
        candidate, capabilities = _require_registered_validation(
            payload,
            mission_id=str(mission_id),
            expected_scope=expected_scope,
            candidate_required=candidate_required,
        )
        attempt_fingerprint = canonical_digest(
            domain="repair-attempt-intervention",
            payload={
                "changed_dimension": payload.get("changed_dimension"),
                "implementation_proof_hash": payload.get(
                    "implementation_proof_hash"
                ),
                "new_basis_hash": payload.get("new_basis_hash"),
                "new_evidence_hashes": payload.get("new_evidence_hashes"),
                "outcome": payload.get("outcome"),
                "verification_capabilities": [
                    {"protocol": protocol, "validator_id": validator_id}
                    for protocol, validator_id in capabilities
                ],
            },
        )
        fingerprint_record_id = canonical_digest(
            domain="repair-attempt-fingerprint",
            payload={
                "attempt_fingerprint": attempt_fingerprint,
                "repair_id": expected_repair_id,
            },
        )
        fingerprint_record = index.get(
            "repair-attempt-fingerprint",
            fingerprint_record_id,
        )
        identity_payload = dict(payload)
        identity_payload.pop("scientific_failure_delta", None)
        identity_payload.pop("scientific_trial_delta", None)
        expected_attempt_id = canonical_digest(
            domain="repair-attempt",
            payload=identity_payload,
        )
        new_basis = payload.get("new_basis_hash")
        new_evidence = payload.get("new_evidence_hashes")
        verification = payload.get("verification_evidence_hashes")
        attempt_reproduction = payload.get("reproduction_evidence_hashes")
        implementation_proof = payload.get("implementation_proof_hash")
        reused_basis_without_new_evidence = (
            _is_digest(new_basis)
            and new_basis in seen_bases
            and isinstance(new_evidence, list)
            and not (
                set(new_evidence)
                - accepted_changed_evidence
                - seen_bases
            )
        )
        attempt_authority_sequence = attempt.authority_sequence
        if (
            set(payload) != expected_attempt_keys
            or (semantic_required and not semantic_attempt_present)
            or (candidate_required and not attempt_candidate_present)
            or attempt.kind != "repair-attempt"
            or attempt.status != expected_outcome
            or attempt.subject != f"Repair:{expected_repair_id}"
            or attempt.event_stream != stream
            or attempt.event_sequence != sequence
            or attempt.record_id != expected_attempt_id
            or attempt.fingerprint != payload.get("attempt_proof_hash")
            or payload.get(_AUTHORITY_FIELD)
            != REGISTERED_REPAIR_AUTHORITY_SCHEMA
            or payload.get("repair_id") != expected_repair_id
            or payload.get("job_id") != job_id
            or payload.get("job_hash") != declaration.fingerprint
            or payload.get("cause_hash") != cause_hash
            or payload.get("resume_action") != opened_payload.get("resume_action")
            or payload.get("schema") != "running_job_repair_attempt.v1"
            or payload.get("outcome") != expected_outcome
            or attempt_dimension not in _DIMENSIONS
            or (terminal and attempt_dimension == "input")
            or payload.get("previous_basis_hash") != prior_basis
            or not _is_digest(new_basis)
            or reused_basis_without_new_evidence
            or payload.get("prior_attempt_record_id") != prior_attempt_id
            or not _is_digest(payload.get("attempt_proof_hash"))
            or not _is_ascii(payload.get("explanation"))
            or payload.get("scientific_semantics_changed") is not False
            or not _exact_zero(payload.get("scientific_failure_delta"))
            or not _exact_zero(payload.get("scientific_trial_delta"))
            or attempt_reproduction != reproduction
            or not _is_digest_list(attempt_reproduction)
            or not _is_digest_list(new_evidence)
            or not _is_digest_list(verification)
            or new_basis not in new_evidence
            or bool(set(attempt_reproduction).intersection(new_evidence))
            or bool(set(attempt_reproduction).intersection(verification))
            or bool(set(new_evidence).intersection(verification))
            or (
                attempt_dimension == "implementation"
                and (
                    not _is_digest(implementation_proof)
                    or implementation_proof not in new_evidence
                )
            )
            or (
                attempt_dimension != "implementation"
                and implementation_proof is not None
            )
            or (
                expected_outcome == "failed"
                and not _is_ascii(payload.get("failure_observation"))
            )
            or (
                expected_outcome == "repaired"
                and payload.get("failure_observation") is not None
            )
            or payload.get("attempt_fingerprint") != attempt_fingerprint
            or attempt_fingerprint in seen_attempt_fingerprints
            or fingerprint_record is None
            or fingerprint_record.kind != "repair-attempt-fingerprint"
            or fingerprint_record.status != expected_outcome
            or fingerprint_record.subject != f"Repair:{expected_repair_id}"
            or fingerprint_record.fingerprint != attempt_fingerprint
            or fingerprint_record.payload
            != {
                "attempt_fingerprint": attempt_fingerprint,
                "attempt_record_id": attempt.record_id,
                "repair_id": expected_repair_id,
            }
            or fingerprint_record.event_stream is not None
            or fingerprint_record.event_sequence is not None
            or fingerprint_record.authority_sequence != attempt_authority_sequence
            or fingerprint_record.authority_event_id != attempt.authority_event_id
            or type(attempt_authority_sequence) is not int
            or attempt_authority_sequence <= prior_attempt_authority_sequence
            or not _is_ascii(attempt.authority_event_id)
        ):
            raise RegisteredRepairEpisodeAuthorityError(
                "registered Repair attempt chain is malformed"
            )
        if terminal:
            terminal_attempt = attempt
        else:
            failed_attempts.append(attempt)
        if candidate is not None:
            candidate_attempts.append((attempt, candidate))
        prior_attempt_id = attempt.record_id
        prior_basis = str(new_basis)
        seen_bases.add(prior_basis)
        accepted_changed_evidence.update(new_evidence)
        seen_attempt_fingerprints.add(attempt_fingerprint)
        prior_attempt_authority_sequence = attempt_authority_sequence

    if (
        terminal_attempt is None
        or head.record_kind != terminal_attempt.kind
        or head.record_id != terminal_attempt.record_id
        or head.fingerprint != terminal_attempt.fingerprint
        or terminal_attempt.authority_sequence != close_authority_sequence
        or terminal_attempt.authority_event_id != close.authority_event_id
        or close_payload.get("attempt_record_id") != terminal_attempt.record_id
        or close_payload.get("changed_cause_proof_hash")
        != terminal_attempt.fingerprint
        or close_payload.get("prior_attempt_record_id")
        != terminal_attempt.payload.get("prior_attempt_record_id")
        or close_payload.get("changed_dimension")
        != terminal_attempt.payload.get("changed_dimension")
        or close_payload.get("resume_action")
        != terminal_attempt.payload.get("resume_action")
        or close_payload.get("verification_evidence_hashes")
        != terminal_attempt.payload.get("verification_evidence_hashes")
        or close_payload.get("repair_validation")
        != terminal_attempt.payload.get("repair_validation")
        or close_payload.get(_AUTHORITY_FIELD)
        != terminal_attempt.payload.get(_AUTHORITY_FIELD)
        or close_payload.get("repair_candidate")
        != terminal_attempt.payload.get("repair_candidate")
        or close_payload.get("repair_candidate_hash")
        != terminal_attempt.payload.get("repair_candidate_hash")
        or close_payload.get("repair_evaluation")
        != terminal_attempt.payload.get("repair_evaluation")
        or close_payload.get("semantic_equivalence_validation")
        != terminal_attempt.payload.get("semantic_equivalence_validation")
    ):
        raise RegisteredRepairEpisodeAuthorityError(
            "registered Repair close differs from its terminal attempt"
        )

    try:
        observations, observation_head = (
            require_repair_validation_observation_stream(
                index,
                repair_id=expected_repair_id,
                job_id=job_id,
                job_hash=declaration.fingerprint,
                cause_hash=cause_hash,
                reproduction_evidence_hashes=tuple(
                    opened_payload["minimum_reproduction_evidence"]
                ),
                resume_action=str(opened_payload["resume_action"]),
                mission_id=str(mission_id),
                expected_scope=expected_scope,
                accepted_attempts=tuple(failed_attempts),
            )
        )
    except (RepairObservationAuthorityError, TypeError, ValueError) as exc:
        raise RegisteredRepairEpisodeAuthorityError(
            "registered Repair observation stream is malformed"
        ) from exc
    _require_observation_chronology(
        index,
        repair_id=expected_repair_id,
        opened_authority_sequence=opened_authority_sequence,
        close_authority_sequence=close_authority_sequence,
        observation_count=len(observations),
    )
    observation_stream = f"repair-validation-observation:{expected_repair_id}"
    for attempt, candidate in candidate_attempts:
        bound: list[dict[str, Any]] = []
        prior_head: dict[str, Any] | None = None
        for observation in observations:
            sequence = observation["observation_sequence"]
            record = index.event_record(observation_stream, sequence)
            if (
                record is None
                or type(record.authority_sequence) is not int
                or type(attempt.authority_sequence) is not int
            ):
                raise RegisteredRepairEpisodeAuthorityError(
                    "registered Repair candidate observation binding is malformed"
                )
            if record.authority_sequence >= attempt.authority_sequence:
                break
            bound.append(
                {
                    "new_information_evidence_hashes": list(
                        observation["new_information_evidence_hashes"]
                    ),
                    "observation_record_id": record.record_id,
                }
            )
            prior_head = {
                "fingerprint": record.fingerprint,
                "record_id": record.record_id,
                "sequence": int(record.event_sequence),
            }
        try:
            rebound_candidate, _stored = (
                require_stored_accepted_repair_candidate_attempt(
                    attempt_payload=attempt.payload,
                    mission_id=str(mission_id),
                    expected_scope=expected_scope,
                    expected_prior_validation_observation_head=prior_head,
                    expected_bound_validation_observations=bound,
                )
            )
        except (RepairValidationError, TypeError, ValueError) as exc:
            raise RegisteredRepairEpisodeAuthorityError(
                "registered Repair candidate does not bind its exact prior "
                "observation stream"
            ) from exc
        if rebound_candidate != candidate:
            raise RegisteredRepairEpisodeAuthorityError(
                "registered Repair candidate changed during observation "
                "rebinding"
            )
    return RegisteredRepairEpisode(
        terminal_attempt=terminal_attempt,
        failed_attempts=tuple(failed_attempts),
        validation_observations=observations,
        validation_observation_head=observation_head,
    )


__all__ = [
    "RegisteredRepairEpisode",
    "RegisteredRepairEpisodeAuthorityError",
    "require_registered_repair_episode",
]
