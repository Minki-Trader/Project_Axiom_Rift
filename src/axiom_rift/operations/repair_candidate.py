"""Pure prospective Repair candidate and evaluation boundaries.

This module deliberately grants no Writer authority.  It separates an exact
caller-proposed candidate from the independently derived evaluation that a
registered production boundary may later persist as either an accepted Repair
attempt or a zero-credit validation observation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from axiom_rift.core.canonical import (
    CanonicalJSONError,
    canonical_bytes,
    parse_canonical,
)


class RepairCandidateError(ValueError):
    """A prospective Repair candidate or evaluation is malformed or unbound."""


REPAIR_CANDIDATE_SCHEMA = "running_job_repair_candidate.v3"
REPAIR_EVALUATION_SCHEMA = "engineering_repair_evaluation.v2"
REPAIR_NEW_FAILURE_SCHEMA = "repair_new_failure.v1"

ACCEPTED_REPAIR_ATTEMPT_MODES = frozenset(
    {"failure_reproduced", "repaired"}
)
ZERO_CREDIT_REPAIR_OBSERVATION_MODES = frozenset(
    {
        "invalid_change",
        "new_failure",
        "not_evaluable",
        "validation_unavailable",
    }
)
REPAIR_EVALUATION_MODES = frozenset(
    ACCEPTED_REPAIR_ATTEMPT_MODES | ZERO_CREDIT_REPAIR_OBSERVATION_MODES
)

# A partial validator result did not establish an evaluation mode of its own.
# It is one typed reason why the validation boundary was unavailable.
VALIDATION_UNAVAILABLE_REASON_CODES = frozenset(
    {
        "declared_artifact_absent_drifted_or_unopened",
        "facts_roles_or_registry_trace_mismatch",
        "partial_validator_result",
        "plan_or_context_binding_mismatch",
        "validator_absent_or_unregistered",
        "validator_execution_failed",
        "validator_protocol_or_identity_mismatch",
    }
)

_CHANGED_DIMENSIONS = frozenset(
    {"cause", "information", "input", "implementation"}
)
_CANDIDATE_FIELDS = {
    "bound_validation_observations",
    "cause_hash",
    "changed_dimension",
    "explanation",
    "implementation_proof_hash",
    "job_hash",
    "job_id",
    "new_basis_hash",
    "new_evidence_hashes",
    "previous_basis_hash",
    "prior_attempt_record_id",
    "prior_validation_observation_head",
    "repair_axis_id",
    "repair_id",
    "reproduction_evidence_hashes",
    "resume_action",
    "schema",
    "scientific_semantics_changed",
    "verification_evidence_hashes",
}
_OBSERVATION_HEAD_FIELDS = {"fingerprint", "record_id", "sequence"}
_BOUND_OBSERVATION_FIELDS = {
    "new_information_evidence_hashes",
    "observation_record_id",
}
_UNBOUND = object()
_EVALUATION_FIELDS = {
    "candidate_hash",
    "cause_resolved",
    "failure_reproduced",
    "material_change",
    "mode",
    "new_failure_manifest_hash",
    "reason_code",
    "registry_trace_hash",
    "schema",
    "scientific_semantics_changed",
    "validation_plan_hash",
    "validator_id",
}
_NEW_FAILURE_FIELDS = {
    "candidate_hash",
    "failure_kind",
    "interrupted_action",
    "job_hash",
    "job_id",
    "minimum_reproduction_evidence_hashes",
    "repair_id",
    "root_cause",
    "schema",
    "scientific_semantics_changed",
}

EvidenceReader = Callable[[str], bytes]
EvidenceVerifier = Callable[[str], object]


def _ascii(label: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise RepairCandidateError(f"{label} must be non-empty ASCII")
    return value


def _token(label: str, value: object) -> str:
    text = _ascii(label, value)
    if any(
        not (character.isalnum() or character in "-_.:")
        for character in text
    ):
        raise RepairCandidateError(
            f"{label} must contain only ASCII token characters"
        )
    return text


def _digest(label: str, value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RepairCandidateError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _typed_id(label: str, value: object, prefix: str) -> str:
    text = _ascii(label, value)
    if not text.startswith(prefix):
        raise RepairCandidateError(f"{label} has an invalid prefix")
    _digest(label, text.removeprefix(prefix))
    return text


def _optional_digest(label: str, value: object) -> str | None:
    return None if value is None else _digest(label, value)


def _digest_list(
    label: str,
    value: object,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or (not allow_empty and not value)
        or any(type(item) is not str for item in value)
        or list(value) != sorted(set(value))
    ):
        raise RepairCandidateError(
            f"{label} must be a sorted unique digest list"
        )
    return tuple(_digest(label, item) for item in value)


def _document(document: bytes | str, *, label: str) -> dict[str, Any]:
    try:
        value = parse_canonical(document)
    except (CanonicalJSONError, TypeError, ValueError) as exc:
        raise RepairCandidateError(f"{label} is not canonical") from exc
    if not isinstance(value, dict):
        raise RepairCandidateError(f"{label} must be an object")
    return dict(value)


def _optional_reason(label: str, value: object) -> str | None:
    return None if value is None else _ascii(label, value)


def _observation_binding(
    *,
    head_value: object,
    observations_value: object,
) -> tuple[
    tuple[str, int, str] | None,
    tuple[tuple[str, tuple[str, ...]], ...],
]:
    if not isinstance(observations_value, (list, tuple)):
        raise RepairCandidateError(
            "Repair candidate bound observations must be a list"
        )
    observations: list[tuple[str, tuple[str, ...]]] = []
    seen: set[str] = set()
    for item in observations_value:
        if not isinstance(item, Mapping) or set(item) != _BOUND_OBSERVATION_FIELDS:
            raise RepairCandidateError(
                "Repair candidate bound observation schema is invalid"
            )
        record_id = _digest(
            "Repair candidate observation record",
            item.get("observation_record_id"),
        )
        if record_id in seen:
            raise RepairCandidateError(
                "Repair candidate bound observations must be unique"
            )
        seen.add(record_id)
        information = _digest_list(
            "Repair candidate observation information",
            item.get("new_information_evidence_hashes"),
            allow_empty=False,
        )
        observations.append((record_id, information))
    if head_value is None:
        head = None
    else:
        if not isinstance(head_value, Mapping) or set(head_value) != (
            _OBSERVATION_HEAD_FIELDS
        ):
            raise RepairCandidateError(
                "Repair candidate observation head schema is invalid"
            )
        sequence = head_value.get("sequence")
        if type(sequence) is not int or sequence < 1:
            raise RepairCandidateError(
                "Repair candidate observation head sequence is invalid"
            )
        head = (
            _digest(
                "Repair candidate observation head record",
                head_value.get("record_id"),
            ),
            sequence,
            _digest(
                "Repair candidate observation head fingerprint",
                head_value.get("fingerprint"),
            ),
        )
    if (head is None) != (not observations):
        raise RepairCandidateError(
            "Repair candidate observation head and inventory diverge"
        )
    if head is not None and (
        head[1] != len(observations) or head[0] != observations[-1][0]
    ):
        raise RepairCandidateError(
            "Repair candidate observation head differs from its inventory"
        )
    return head, tuple(observations)


def _observation_head_payload(
    head: tuple[str, int, str] | None,
) -> dict[str, Any] | None:
    if head is None:
        return None
    return {"fingerprint": head[2], "record_id": head[0], "sequence": head[1]}


def _bound_observation_payloads(
    observations: Sequence[tuple[str, tuple[str, ...]]],
) -> list[dict[str, Any]]:
    return [
        {
            "new_information_evidence_hashes": list(information),
            "observation_record_id": record_id,
        }
        for record_id, information in observations
    ]


@dataclass(frozen=True, slots=True)
class RepairCandidate:
    repair_id: str
    job_id: str
    job_hash: str
    cause_hash: str
    repair_axis_id: str
    changed_dimension: str
    previous_basis_hash: str
    new_basis_hash: str
    prior_attempt_record_id: str | None
    prior_validation_observation_head: tuple[str, int, str] | None
    bound_validation_observations: tuple[
        tuple[str, tuple[str, ...]], ...
    ]
    reproduction_evidence_hashes: tuple[str, ...]
    new_evidence_hashes: tuple[str, ...]
    verification_evidence_hashes: tuple[str, ...]
    implementation_proof_hash: str | None
    explanation: str
    resume_action: str

    def payload(self) -> dict[str, Any]:
        return {
            "bound_validation_observations": _bound_observation_payloads(
                self.bound_validation_observations
            ),
            "cause_hash": self.cause_hash,
            "changed_dimension": self.changed_dimension,
            "explanation": self.explanation,
            "implementation_proof_hash": self.implementation_proof_hash,
            "job_hash": self.job_hash,
            "job_id": self.job_id,
            "new_basis_hash": self.new_basis_hash,
            "new_evidence_hashes": list(self.new_evidence_hashes),
            "previous_basis_hash": self.previous_basis_hash,
            "prior_attempt_record_id": self.prior_attempt_record_id,
            "prior_validation_observation_head": _observation_head_payload(
                self.prior_validation_observation_head
            ),
            "repair_axis_id": self.repair_axis_id,
            "repair_id": self.repair_id,
            "reproduction_evidence_hashes": list(
                self.reproduction_evidence_hashes
            ),
            "resume_action": self.resume_action,
            "schema": REPAIR_CANDIDATE_SCHEMA,
            "scientific_semantics_changed": False,
            "verification_evidence_hashes": list(
                self.verification_evidence_hashes
            ),
        }

    @property
    def sha256(self) -> str:
        return sha256(canonical_bytes(self.payload())).hexdigest()


@dataclass(frozen=True, slots=True)
class RepairNewFailure:
    candidate_hash: str
    repair_id: str
    job_id: str
    job_hash: str
    interrupted_action: str
    root_cause: str
    minimum_reproduction_evidence_hashes: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "candidate_hash": self.candidate_hash,
            "failure_kind": "engineering",
            "interrupted_action": self.interrupted_action,
            "job_hash": self.job_hash,
            "job_id": self.job_id,
            "minimum_reproduction_evidence_hashes": list(
                self.minimum_reproduction_evidence_hashes
            ),
            "repair_id": self.repair_id,
            "root_cause": self.root_cause,
            "schema": REPAIR_NEW_FAILURE_SCHEMA,
            "scientific_semantics_changed": False,
        }

    @property
    def sha256(self) -> str:
        return sha256(canonical_bytes(self.payload())).hexdigest()


@dataclass(frozen=True, slots=True)
class RepairEvaluation:
    candidate_hash: str
    validator_id: str
    validation_plan_hash: str
    registry_trace_hash: str | None
    mode: str
    cause_resolved: bool | None
    failure_reproduced: bool | None
    material_change: bool | None
    new_failure_manifest_hash: str | None
    reason_code: str | None

    def payload(self) -> dict[str, Any]:
        return {
            "candidate_hash": self.candidate_hash,
            "cause_resolved": self.cause_resolved,
            "failure_reproduced": self.failure_reproduced,
            "material_change": self.material_change,
            "mode": self.mode,
            "new_failure_manifest_hash": self.new_failure_manifest_hash,
            "reason_code": self.reason_code,
            "registry_trace_hash": self.registry_trace_hash,
            "schema": REPAIR_EVALUATION_SCHEMA,
            "scientific_semantics_changed": False,
            "validation_plan_hash": self.validation_plan_hash,
            "validator_id": self.validator_id,
        }

    @property
    def accepted_attempt(self) -> bool:
        return is_accepted_repair_attempt_mode(self.mode)

    @property
    def zero_credit_observation(self) -> bool:
        return is_zero_credit_repair_observation_mode(self.mode)


def _candidate(
    *,
    repair_id: object,
    job_id: object,
    job_hash: object,
    cause_hash: object,
    repair_axis_id: object,
    changed_dimension: object,
    previous_basis_hash: object,
    new_basis_hash: object,
    prior_attempt_record_id: object,
    prior_validation_observation_head: object,
    bound_validation_observations: object,
    reproduction_evidence_hashes: object,
    new_evidence_hashes: object,
    verification_evidence_hashes: object,
    implementation_proof_hash: object,
    explanation: object,
    resume_action: object,
) -> RepairCandidate:
    observed_repair = _typed_id("Repair candidate Repair", repair_id, "repair:")
    observed_job = _typed_id("Repair candidate Job", job_id, "job:")
    observed_job_hash = _digest("Repair candidate Job hash", job_hash)
    observed_cause = _digest("Repair candidate cause", cause_hash)
    axis_id = _token("Repair candidate axis", repair_axis_id)
    dimension = _ascii("Repair candidate changed dimension", changed_dimension)
    if dimension not in _CHANGED_DIMENSIONS:
        raise RepairCandidateError("Repair candidate changed dimension is invalid")
    previous_basis = _digest(
        "Repair candidate previous basis", previous_basis_hash
    )
    new_basis = _digest("Repair candidate new basis", new_basis_hash)
    prior_attempt = _optional_digest(
        "Repair candidate prior attempt", prior_attempt_record_id
    )
    observation_head, bound_observations = _observation_binding(
        head_value=prior_validation_observation_head,
        observations_value=bound_validation_observations,
    )
    reproduction = _digest_list(
        "Repair candidate reproduction evidence",
        reproduction_evidence_hashes,
        allow_empty=False,
    )
    new_evidence = _digest_list(
        "Repair candidate changed evidence",
        new_evidence_hashes,
        allow_empty=False,
    )
    verification = _digest_list(
        "Repair candidate verification receipts",
        verification_evidence_hashes,
        allow_empty=False,
    )
    if new_basis not in new_evidence:
        raise RepairCandidateError(
            "Repair candidate new basis is absent from changed evidence"
        )
    observation_information = {
        identity
        for _record_id, identities in bound_observations
        for identity in identities
    }
    if not observation_information.issubset(new_evidence):
        raise RepairCandidateError(
            "Repair candidate observation information is absent from changed "
            "evidence"
        )
    if (
        set(reproduction).intersection(new_evidence)
        or set(reproduction).intersection(verification)
        or set(new_evidence).intersection(verification)
    ):
        raise RepairCandidateError(
            "Repair candidate reproduction, change, and verification surfaces "
            "must be distinct"
        )
    implementation_proof = implementation_proof_hash
    if dimension == "implementation":
        implementation_proof = _digest(
            "Repair candidate implementation proof", implementation_proof
        )
        if implementation_proof not in new_evidence:
            raise RepairCandidateError(
                "Repair candidate implementation proof is absent from changed "
                "evidence"
            )
    elif implementation_proof is not None:
        raise RepairCandidateError(
            "non-implementation Repair candidate cannot carry implementation proof"
        )
    return RepairCandidate(
        repair_id=observed_repair,
        job_id=observed_job,
        job_hash=observed_job_hash,
        cause_hash=observed_cause,
        repair_axis_id=axis_id,
        changed_dimension=dimension,
        previous_basis_hash=previous_basis,
        new_basis_hash=new_basis,
        prior_attempt_record_id=prior_attempt,
        prior_validation_observation_head=observation_head,
        bound_validation_observations=bound_observations,
        reproduction_evidence_hashes=reproduction,
        new_evidence_hashes=new_evidence,
        verification_evidence_hashes=verification,
        implementation_proof_hash=(
            None if implementation_proof is None else str(implementation_proof)
        ),
        explanation=_ascii("Repair candidate explanation", explanation),
        resume_action=_ascii("Repair candidate resume action", resume_action),
    )


def build_repair_candidate(
    *,
    repair_id: str,
    job_id: str,
    job_hash: str,
    cause_hash: str,
    repair_axis_id: str,
    changed_dimension: str,
    previous_basis_hash: str,
    new_basis_hash: str,
    prior_attempt_record_id: str | None,
    prior_validation_observation_head: Mapping[str, Any] | None,
    bound_validation_observations: Sequence[Mapping[str, Any]],
    reproduction_evidence_hashes: Sequence[str],
    new_evidence_hashes: Sequence[str],
    verification_evidence_hashes: Sequence[str],
    implementation_proof_hash: str | None,
    explanation: str,
    resume_action: str,
) -> dict[str, Any]:
    """Build one canonical-ready candidate with no caller-authored outcome."""

    return _candidate(
        repair_id=repair_id,
        job_id=job_id,
        job_hash=job_hash,
        cause_hash=cause_hash,
        repair_axis_id=repair_axis_id,
        changed_dimension=changed_dimension,
        previous_basis_hash=previous_basis_hash,
        new_basis_hash=new_basis_hash,
        prior_attempt_record_id=prior_attempt_record_id,
        prior_validation_observation_head=(
            prior_validation_observation_head
        ),
        bound_validation_observations=bound_validation_observations,
        reproduction_evidence_hashes=reproduction_evidence_hashes,
        new_evidence_hashes=new_evidence_hashes,
        verification_evidence_hashes=verification_evidence_hashes,
        implementation_proof_hash=implementation_proof_hash,
        explanation=explanation,
        resume_action=resume_action,
    ).payload()


def parse_repair_candidate(
    document: bytes | str,
    *,
    repair_id: str,
    job_id: str,
    job_hash: str,
    cause_hash: str,
    previous_basis_hash: str,
    prior_attempt_record_id: str | None,
    reproduction_evidence_hashes: Sequence[str],
    resume_action: str,
    expected_prior_validation_observation_head: (
        Mapping[str, Any] | None | object
    ) = _UNBOUND,
    expected_bound_validation_observations: (
        Sequence[Mapping[str, Any]] | object
    ) = _UNBOUND,
    verify_evidence: EvidenceVerifier | None = None,
) -> RepairCandidate:
    """Parse a candidate only against the exact active Repair and Job state."""

    value = _document(document, label="Repair candidate")
    if (
        set(value) != _CANDIDATE_FIELDS
        or value.get("schema") != REPAIR_CANDIDATE_SCHEMA
    ):
        raise RepairCandidateError("Repair candidate schema is invalid")
    if value.get("scientific_semantics_changed") is not False:
        raise RepairCandidateError(
            "scientific semantic change cannot be a Repair candidate"
        )
    candidate = _candidate(
        repair_id=value.get("repair_id"),
        job_id=value.get("job_id"),
        job_hash=value.get("job_hash"),
        cause_hash=value.get("cause_hash"),
        repair_axis_id=value.get("repair_axis_id"),
        changed_dimension=value.get("changed_dimension"),
        previous_basis_hash=value.get("previous_basis_hash"),
        new_basis_hash=value.get("new_basis_hash"),
        prior_attempt_record_id=value.get("prior_attempt_record_id"),
        prior_validation_observation_head=value.get(
            "prior_validation_observation_head"
        ),
        bound_validation_observations=value.get(
            "bound_validation_observations"
        ),
        reproduction_evidence_hashes=value.get("reproduction_evidence_hashes"),
        new_evidence_hashes=value.get("new_evidence_hashes"),
        verification_evidence_hashes=value.get("verification_evidence_hashes"),
        implementation_proof_hash=value.get("implementation_proof_hash"),
        explanation=value.get("explanation"),
        resume_action=value.get("resume_action"),
    )
    expected_reproduction = _digest_list(
        "active Repair reproduction evidence",
        reproduction_evidence_hashes,
        allow_empty=False,
    )
    expected_observation_binding = None
    if (
        expected_prior_validation_observation_head is not _UNBOUND
        or expected_bound_validation_observations is not _UNBOUND
    ):
        if (
            expected_prior_validation_observation_head is _UNBOUND
            or expected_bound_validation_observations is _UNBOUND
        ):
            raise RepairCandidateError(
                "active Repair observation head and inventory must be checked "
                "together"
            )
        expected_observation_binding = _observation_binding(
            head_value=expected_prior_validation_observation_head,
            observations_value=expected_bound_validation_observations,
        )
    if (
        candidate.repair_id
        != _typed_id("active Repair", repair_id, "repair:")
        or candidate.job_id != _typed_id("active Repair Job", job_id, "job:")
        or candidate.job_hash != _digest("active Repair Job hash", job_hash)
        or candidate.cause_hash != _digest("active Repair cause", cause_hash)
        or candidate.previous_basis_hash
        != _digest("active Repair basis", previous_basis_hash)
        or candidate.prior_attempt_record_id
        != _optional_digest("active Repair prior attempt", prior_attempt_record_id)
        or candidate.reproduction_evidence_hashes != expected_reproduction
        or candidate.resume_action
        != _ascii("active Repair resume action", resume_action)
        or (
            expected_observation_binding is not None
            and (
                candidate.prior_validation_observation_head,
                candidate.bound_validation_observations,
            )
            != expected_observation_binding
        )
    ):
        raise RepairCandidateError(
            "Repair candidate differs from the exact active Repair context"
        )
    if verify_evidence is not None:
        for identity in (
            *candidate.reproduction_evidence_hashes,
            *candidate.new_evidence_hashes,
            *candidate.verification_evidence_hashes,
        ):
            verify_evidence(identity)
    return candidate


def _new_failure(
    *,
    candidate_hash: object,
    repair_id: object,
    job_id: object,
    job_hash: object,
    interrupted_action: object,
    root_cause: object,
    minimum_reproduction_evidence_hashes: object,
) -> RepairNewFailure:
    return RepairNewFailure(
        candidate_hash=_digest("new Repair failure candidate", candidate_hash),
        repair_id=_typed_id("new Repair failure Repair", repair_id, "repair:"),
        job_id=_typed_id("new Repair failure Job", job_id, "job:"),
        job_hash=_digest("new Repair failure Job hash", job_hash),
        interrupted_action=_ascii(
            "new Repair failure interrupted action", interrupted_action
        ),
        root_cause=_ascii("new Repair failure root cause", root_cause),
        minimum_reproduction_evidence_hashes=_digest_list(
            "new Repair failure reproduction evidence",
            minimum_reproduction_evidence_hashes,
            allow_empty=False,
        ),
    )


def build_repair_new_failure_manifest(
    *,
    candidate_hash: str,
    repair_id: str,
    job_id: str,
    job_hash: str,
    interrupted_action: str,
    root_cause: str,
    minimum_reproduction_evidence_hashes: Sequence[str],
) -> dict[str, Any]:
    """Build the typed evidence required by a ``new_failure`` evaluation."""

    return _new_failure(
        candidate_hash=candidate_hash,
        repair_id=repair_id,
        job_id=job_id,
        job_hash=job_hash,
        interrupted_action=interrupted_action,
        root_cause=root_cause,
        minimum_reproduction_evidence_hashes=(
            minimum_reproduction_evidence_hashes
        ),
    ).payload()


def parse_repair_new_failure_manifest(
    document: bytes | str,
    *,
    candidate_hash: str,
    forbidden_evidence_hashes: Sequence[str] = (),
    verify_evidence: EvidenceVerifier | None = None,
) -> RepairNewFailure:
    """Parse a new engineering failure bound to one evaluated candidate."""

    value = _document(document, label="new Repair failure manifest")
    if (
        set(value) != _NEW_FAILURE_FIELDS
        or value.get("schema") != REPAIR_NEW_FAILURE_SCHEMA
    ):
        raise RepairCandidateError("new Repair failure manifest schema is invalid")
    if (
        value.get("failure_kind") != "engineering"
        or value.get("scientific_semantics_changed") is not False
    ):
        raise RepairCandidateError(
            "new Repair failure manifest is not engineering-only"
        )
    manifest = _new_failure(
        candidate_hash=value.get("candidate_hash"),
        repair_id=value.get("repair_id"),
        job_id=value.get("job_id"),
        job_hash=value.get("job_hash"),
        interrupted_action=value.get("interrupted_action"),
        root_cause=value.get("root_cause"),
        minimum_reproduction_evidence_hashes=value.get(
            "minimum_reproduction_evidence_hashes"
        ),
    )
    expected_candidate = _digest("evaluated Repair candidate", candidate_hash)
    forbidden = tuple(
        _digest("new Repair failure forbidden evidence", identity)
        for identity in forbidden_evidence_hashes
    )
    if manifest.candidate_hash != expected_candidate:
        raise RepairCandidateError("new Repair failure names another candidate")
    if set(manifest.minimum_reproduction_evidence_hashes).intersection(forbidden):
        raise RepairCandidateError(
            "new Repair failure reproduction and evaluation surfaces must be distinct"
        )
    if verify_evidence is not None:
        for identity in manifest.minimum_reproduction_evidence_hashes:
            verify_evidence(identity)
    return manifest


def _evaluation(
    *,
    candidate_hash: object,
    validator_id: object,
    validation_plan_hash: object,
    registry_trace_hash: object,
    mode: object,
    cause_resolved: object,
    failure_reproduced: object,
    material_change: object,
    new_failure_manifest_hash: object,
    reason_code: object,
    read_evidence: EvidenceReader | None,
) -> RepairEvaluation:
    candidate = _digest("Repair evaluation candidate", candidate_hash)
    validator = _typed_id("Repair evaluation validator", validator_id, "validator:")
    plan = _digest("Repair evaluation plan", validation_plan_hash)
    trace = _optional_digest("Repair evaluation registry trace", registry_trace_hash)
    observed_mode = _ascii("Repair evaluation mode", mode)
    if observed_mode not in REPAIR_EVALUATION_MODES:
        raise RepairCandidateError("Repair evaluation mode is invalid")
    if cause_resolved is not None and type(cause_resolved) is not bool:
        raise RepairCandidateError(
            "Repair evaluation cause_resolved is not nullable bool"
        )
    if failure_reproduced is not None and type(failure_reproduced) is not bool:
        raise RepairCandidateError(
            "Repair evaluation failure_reproduced is not nullable bool"
        )
    if material_change is not None and type(material_change) is not bool:
        raise RepairCandidateError(
            "Repair evaluation material_change is not nullable bool"
        )
    new_failure_hash = _optional_digest(
        "Repair evaluation new failure", new_failure_manifest_hash
    )
    reason = _optional_reason("Repair evaluation reason", reason_code)

    expected_facts: dict[str, tuple[bool | None, bool | None, bool | None]] = {
        "repaired": (True, False, True),
        "failure_reproduced": (False, True, True),
        "new_failure": (None, None, True),
        "invalid_change": (None, None, False),
        "not_evaluable": (None, None, None),
        "validation_unavailable": (None, None, None),
    }
    if (cause_resolved, failure_reproduced, material_change) != expected_facts[
        observed_mode
    ]:
        raise RepairCandidateError(
            "Repair evaluation facts violate the mode matrix"
        )
    if observed_mode == "new_failure":
        if new_failure_hash is None or trace is None or reason is not None:
            raise RepairCandidateError(
                "new_failure requires a registered trace and typed failure manifest"
            )
        if read_evidence is None:
            raise RepairCandidateError(
                "new_failure requires a reader for its typed failure manifest"
            )
        try:
            content = read_evidence(new_failure_hash)
        except (FileNotFoundError, KeyError, OSError, RuntimeError) as exc:
            raise RepairCandidateError(
                "new Repair failure manifest is unavailable"
            ) from exc
        if sha256(content).hexdigest() != new_failure_hash:
            raise RepairCandidateError("new Repair failure manifest hash differs")
        parse_repair_new_failure_manifest(
            content,
            candidate_hash=candidate,
            forbidden_evidence_hashes=(candidate, plan, trace),
        )
    elif new_failure_hash is not None:
        raise RepairCandidateError(
            "only new_failure may carry a new failure manifest"
        )

    if observed_mode == "validation_unavailable":
        if trace is not None or reason not in VALIDATION_UNAVAILABLE_REASON_CODES:
            raise RepairCandidateError(
                "validation_unavailable requires one typed reason and no registry trace"
            )
    elif trace is None:
        raise RepairCandidateError(
            "completed Repair evaluation requires a registered trace"
        )
    if observed_mode in {"invalid_change", "not_evaluable"}:
        if reason is None:
            raise RepairCandidateError(
                f"{observed_mode} requires one typed ASCII reason"
            )
    elif observed_mode != "validation_unavailable" and reason is not None:
        raise RepairCandidateError(
            "accepted or new-failure evaluation cannot carry a reason code"
        )

    surfaces = [candidate, plan]
    if trace is not None:
        surfaces.append(trace)
    if new_failure_hash is not None:
        surfaces.append(new_failure_hash)
    if len(set(surfaces)) != len(surfaces):
        raise RepairCandidateError(
            "Repair candidate, plan, trace, and failure surfaces must be distinct"
        )
    return RepairEvaluation(
        candidate_hash=candidate,
        validator_id=validator,
        validation_plan_hash=plan,
        registry_trace_hash=trace,
        mode=observed_mode,
        cause_resolved=(
            None if cause_resolved is None else bool(cause_resolved)
        ),
        failure_reproduced=(
            None if failure_reproduced is None else bool(failure_reproduced)
        ),
        material_change=(
            None if material_change is None else bool(material_change)
        ),
        new_failure_manifest_hash=new_failure_hash,
        reason_code=reason,
    )


def build_repair_evaluation(
    *,
    candidate_hash: str,
    validator_id: str,
    validation_plan_hash: str,
    registry_trace_hash: str | None,
    mode: str,
    cause_resolved: bool | None,
    failure_reproduced: bool | None,
    material_change: bool | None,
    new_failure_manifest_hash: str | None,
    reason_code: str | None,
    read_evidence: EvidenceReader | None = None,
) -> dict[str, Any]:
    """Build a strict evaluation; this function itself grants no authority."""

    return _evaluation(
        candidate_hash=candidate_hash,
        validator_id=validator_id,
        validation_plan_hash=validation_plan_hash,
        registry_trace_hash=registry_trace_hash,
        mode=mode,
        cause_resolved=cause_resolved,
        failure_reproduced=failure_reproduced,
        material_change=material_change,
        new_failure_manifest_hash=new_failure_manifest_hash,
        reason_code=reason_code,
        read_evidence=read_evidence,
    ).payload()


def parse_repair_evaluation(
    document: bytes | str,
    *,
    candidate_hash: str,
    validator_id: str,
    validation_plan_hash: str,
    registry_trace_hash: str | None,
    read_evidence: EvidenceReader | None = None,
) -> RepairEvaluation:
    """Parse an evaluation against Writer-derived validator and trace bindings."""

    value = _document(document, label="Repair evaluation")
    if (
        set(value) != _EVALUATION_FIELDS
        or value.get("schema") != REPAIR_EVALUATION_SCHEMA
    ):
        raise RepairCandidateError("Repair evaluation schema is invalid")
    if value.get("scientific_semantics_changed") is not False:
        raise RepairCandidateError(
            "Repair evaluation cannot change scientific semantics"
        )
    evaluation = _evaluation(
        candidate_hash=value.get("candidate_hash"),
        validator_id=value.get("validator_id"),
        validation_plan_hash=value.get("validation_plan_hash"),
        registry_trace_hash=value.get("registry_trace_hash"),
        mode=value.get("mode"),
        cause_resolved=value.get("cause_resolved"),
        failure_reproduced=value.get("failure_reproduced"),
        material_change=value.get("material_change"),
        new_failure_manifest_hash=value.get("new_failure_manifest_hash"),
        reason_code=value.get("reason_code"),
        read_evidence=read_evidence,
    )
    if (
        evaluation.candidate_hash
        != _digest("expected Repair candidate", candidate_hash)
        or evaluation.validator_id
        != _typed_id("expected Repair validator", validator_id, "validator:")
        or evaluation.validation_plan_hash
        != _digest("expected Repair validation plan", validation_plan_hash)
        or evaluation.registry_trace_hash
        != _optional_digest(
            "expected Repair registry trace", registry_trace_hash
        )
    ):
        raise RepairCandidateError(
            "Repair evaluation differs from its authoritative dispatch"
        )
    return evaluation


def is_accepted_repair_attempt_mode(mode: object) -> bool:
    """Return whether a complete evaluation may enter the accepted stream."""

    return type(mode) is str and mode in ACCEPTED_REPAIR_ATTEMPT_MODES


def is_zero_credit_repair_observation_mode(mode: object) -> bool:
    """Return whether an evaluation belongs only to the observation stream."""

    return (
        type(mode) is str
        and mode in ZERO_CREDIT_REPAIR_OBSERVATION_MODES
    )


def repair_evaluation_authority_class(mode: object) -> str:
    """Classify a typed evaluation without treating an unknown mode as evidence."""

    if is_accepted_repair_attempt_mode(mode):
        return "accepted_attempt"
    if is_zero_credit_repair_observation_mode(mode):
        return "zero_credit_observation"
    raise RepairCandidateError("Repair evaluation mode is invalid")


__all__ = [
    "ACCEPTED_REPAIR_ATTEMPT_MODES",
    "REPAIR_CANDIDATE_SCHEMA",
    "REPAIR_EVALUATION_MODES",
    "REPAIR_EVALUATION_SCHEMA",
    "REPAIR_NEW_FAILURE_SCHEMA",
    "VALIDATION_UNAVAILABLE_REASON_CODES",
    "ZERO_CREDIT_REPAIR_OBSERVATION_MODES",
    "RepairCandidate",
    "RepairCandidateError",
    "RepairEvaluation",
    "RepairNewFailure",
    "build_repair_candidate",
    "build_repair_evaluation",
    "build_repair_new_failure_manifest",
    "is_accepted_repair_attempt_mode",
    "is_zero_credit_repair_observation_mode",
    "parse_repair_candidate",
    "parse_repair_evaluation",
    "parse_repair_new_failure_manifest",
    "repair_evaluation_authority_class",
]
