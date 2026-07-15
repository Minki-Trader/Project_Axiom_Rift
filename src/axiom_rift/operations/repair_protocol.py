"""Typed, evidence-bound Repair attempts and unrecovered dispositions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from axiom_rift.core.canonical import CanonicalJSONError, parse_canonical


class RepairProtocolError(ValueError):
    """A Repair proof is malformed or differs from its active Job context."""


_ATTEMPT_SCHEMA = "running_job_repair_attempt.v1"
_VERIFICATION_SCHEMA = "repair_verification_receipt.v1"
_DISPOSITION_SCHEMA = "engineering_failure_disposition.v1"
_DISPOSITION_BASIS_SCHEMA = "engineering_failure_disposition_basis.v1"
_DISPOSITION_OBSERVATION_SCHEMA = (
    "engineering_failure_disposition_observation.v1"
)
_ATTEMPT_OUTCOMES = frozenset({"failed", "repaired"})
_CHANGED_DIMENSIONS = frozenset(
    {"cause", "information", "input", "implementation"}
)
_ENGINEERING_DISPOSITIONS = frozenset(
    {
        "repair_exhausted_changed_causes",
        "repair_infeasible",
        "repair_nonpositive_expected_value",
        "requires_scientific_change",
    }
)
_SUCCESSOR_SCOPES = frozenset({"executable", "study"})
_DISPOSITION_VERIFICATION_RESULTS = {
    "repair_exhausted_changed_causes": "changed_causes_exhausted",
    "repair_infeasible": "repair_infeasible",
    "repair_nonpositive_expected_value": "nonpositive_expected_value",
    "requires_scientific_change": "scientific_change_required",
}


EvidenceVerifier = Callable[[str], object]
EvidenceReader = Callable[[str], bytes]


def _ascii(label: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise RepairProtocolError(f"{label} must be non-empty ASCII")
    return value


def _digest(label: str, value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RepairProtocolError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _typed_id(label: str, value: object, prefix: str) -> str:
    text = _ascii(label, value)
    if not text.startswith(prefix) or len(text) != len(prefix) + 64:
        raise RepairProtocolError(f"{label} is invalid")
    _digest(label, text.removeprefix(prefix))
    return text


def _nullable_typed_id(
    label: str,
    value: object,
    prefix: str,
) -> str | None:
    if value is None:
        return None
    return _typed_id(label, value, prefix)


def _ascii_list(label: str, value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(type(item) is not str for item in value)
        or value != sorted(set(value))
    ):
        raise RepairProtocolError(
            f"{label} must be a sorted unique ASCII list"
        )
    return tuple(_ascii(label, item) for item in value)


def _digest_list(
    label: str,
    value: object,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(type(item) is not str for item in value)
    ):
        raise RepairProtocolError(
            f"{label} must be a sorted unique digest list"
        )
    if value != sorted(set(value)):
        raise RepairProtocolError(
            f"{label} must be a sorted unique digest list"
        )
    result = tuple(_digest(label, item) for item in value)
    return result


def _document(document: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = parse_canonical(document)
    except (CanonicalJSONError, TypeError, ValueError) as exc:
        raise RepairProtocolError(f"{label} is not canonical evidence") from exc
    if not isinstance(value, dict):
        raise RepairProtocolError(f"{label} must be an object")
    return dict(value)


@dataclass(frozen=True, slots=True)
class RepairAttemptProof:
    repair_id: str
    job_id: str
    job_hash: str
    cause_hash: str
    outcome: str
    changed_dimension: str
    previous_basis_hash: str
    new_basis_hash: str
    prior_attempt_record_id: str | None
    reproduction_evidence_hashes: tuple[str, ...]
    new_evidence_hashes: tuple[str, ...]
    verification_evidence_hashes: tuple[str, ...]
    implementation_proof_hash: str | None
    explanation: str
    failure_observation: str | None
    resume_action: str

    def payload(self) -> dict[str, Any]:
        return {
            "cause_hash": self.cause_hash,
            "changed_dimension": self.changed_dimension,
            "explanation": self.explanation,
            "failure_observation": self.failure_observation,
            "implementation_proof_hash": self.implementation_proof_hash,
            "job_hash": self.job_hash,
            "job_id": self.job_id,
            "new_basis_hash": self.new_basis_hash,
            "new_evidence_hashes": list(self.new_evidence_hashes),
            "outcome": self.outcome,
            "previous_basis_hash": self.previous_basis_hash,
            "prior_attempt_record_id": self.prior_attempt_record_id,
            "repair_id": self.repair_id,
            "reproduction_evidence_hashes": list(
                self.reproduction_evidence_hashes
            ),
            "resume_action": self.resume_action,
            "schema": _ATTEMPT_SCHEMA,
            "scientific_semantics_changed": False,
            "verification_evidence_hashes": list(
                self.verification_evidence_hashes
            ),
        }


def parse_repair_attempt_proof(
    document: bytes,
    *,
    expected_outcome: str,
    repair_id: str,
    job_id: str,
    job_hash: str,
    cause_hash: str,
    resume_action: str,
    reproduction_evidence_hashes: Sequence[str],
    prior_attempt_record_id: str | None,
    previous_basis_hash: str,
    read_evidence: EvidenceReader,
    verify_evidence: EvidenceVerifier,
) -> RepairAttemptProof:
    """Validate one changed-basis Repair attempt against exact active state."""

    if expected_outcome not in _ATTEMPT_OUTCOMES:
        raise RepairProtocolError("expected Repair attempt outcome is invalid")
    value = _document(document, label="Repair attempt proof")
    required = {
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
        "scientific_semantics_changed",
        "verification_evidence_hashes",
    }
    if set(value) != required or value.get("schema") != _ATTEMPT_SCHEMA:
        raise RepairProtocolError("Repair attempt proof schema is invalid")
    if value.get("scientific_semantics_changed") is not False:
        raise RepairProtocolError(
            "scientific semantic change must leave Repair and create new work"
        )

    observed_repair_id = _typed_id("repair id", value.get("repair_id"), "repair:")
    observed_job_id = _typed_id("Job id", value.get("job_id"), "job:")
    observed_job_hash = _digest("Job hash", value.get("job_hash"))
    observed_cause_hash = _digest("Repair cause hash", value.get("cause_hash"))
    observed_resume = _ascii("Repair resume action", value.get("resume_action"))
    if (
        observed_repair_id != repair_id
        or observed_job_id != job_id
        or observed_job_hash != job_hash
        or observed_cause_hash != cause_hash
        or observed_resume != resume_action
    ):
        raise RepairProtocolError("Repair attempt differs from active Job context")
    if value.get("outcome") != expected_outcome:
        raise RepairProtocolError("Repair attempt outcome differs")

    changed_dimension = value.get("changed_dimension")
    if changed_dimension not in _CHANGED_DIMENSIONS:
        raise RepairProtocolError("Repair changed dimension is invalid")
    if expected_outcome == "repaired" and changed_dimension == "input":
        raise RepairProtocolError(
            "a changed Job input requires a new Job identity, not in-place Repair"
        )
    observed_previous_basis = _digest(
        "previous Repair basis", value.get("previous_basis_hash")
    )
    observed_new_basis = _digest(
        "new Repair basis", value.get("new_basis_hash")
    )
    if (
        observed_previous_basis != previous_basis_hash
        or observed_new_basis == observed_previous_basis
    ):
        raise RepairProtocolError("Repair attempt does not change its exact basis")

    observed_prior = value.get("prior_attempt_record_id")
    if observed_prior is not None:
        observed_prior = _digest("prior Repair attempt", observed_prior)
    if observed_prior != prior_attempt_record_id:
        raise RepairProtocolError("Repair attempt does not extend the exact prior attempt")

    expected_reproduction = tuple(sorted(set(reproduction_evidence_hashes)))
    if len(expected_reproduction) != len(tuple(reproduction_evidence_hashes)):
        raise RepairProtocolError("active Repair reproduction evidence is ambiguous")
    observed_reproduction = _digest_list(
        "Repair reproduction evidence",
        value.get("reproduction_evidence_hashes"),
        allow_empty=False,
    )
    new_evidence = _digest_list(
        "Repair changed evidence",
        value.get("new_evidence_hashes"),
        allow_empty=False,
    )
    verification_evidence = _digest_list(
        "Repair verification evidence",
        value.get("verification_evidence_hashes"),
        allow_empty=False,
    )
    if observed_reproduction != expected_reproduction:
        raise RepairProtocolError("Repair attempt reproduction binding differs")
    if observed_new_basis not in new_evidence:
        raise RepairProtocolError("new Repair basis is absent from changed evidence")
    if (
        set(observed_reproduction).intersection(new_evidence)
        or set(observed_reproduction).intersection(verification_evidence)
        or set(new_evidence).intersection(verification_evidence)
    ):
        raise RepairProtocolError(
            "Repair reproduction, change, and verification evidence must be distinct"
        )

    implementation_proof = value.get("implementation_proof_hash")
    if changed_dimension == "implementation":
        implementation_proof = _digest(
            "implementation Repair proof", implementation_proof
        )
        if implementation_proof not in new_evidence:
            raise RepairProtocolError(
                "implementation Repair proof is absent from changed evidence"
            )
    elif implementation_proof is not None:
        raise RepairProtocolError(
            "non-implementation Repair cannot carry implementation proof"
        )
    for identity in new_evidence:
        verify_evidence(identity)
    verification_support: set[str] = set()
    for receipt_hash in verification_evidence:
        receipt = _document(
            read_evidence(receipt_hash),
            label="Repair verification receipt",
        )
        receipt_required = {
            "cause_hash",
            "changed_dimension",
            "check_plan_hash",
            "job_hash",
            "job_id",
            "new_basis_hash",
            "outcome",
            "repair_id",
            "result_artifact_hashes",
            "resume_action",
            "schema",
            "scientific_semantics_changed",
            "verdict",
            "verification_method",
        }
        expected_verdict = (
            "passed" if expected_outcome == "repaired" else "failure_reproduced"
        )
        if (
            set(receipt) != receipt_required
            or receipt.get("schema") != _VERIFICATION_SCHEMA
            or receipt.get("repair_id") != observed_repair_id
            or receipt.get("job_id") != observed_job_id
            or receipt.get("job_hash") != observed_job_hash
            or receipt.get("cause_hash") != observed_cause_hash
            or receipt.get("changed_dimension") != changed_dimension
            or receipt.get("new_basis_hash") != observed_new_basis
            or receipt.get("outcome") != expected_outcome
            or receipt.get("resume_action") != observed_resume
            or receipt.get("verdict") != expected_verdict
            or receipt.get("scientific_semantics_changed") is not False
        ):
            raise RepairProtocolError(
                "Repair verification receipt differs from its attempt"
            )
        _ascii(
            "Repair verification method",
            receipt.get("verification_method"),
        )
        check_plan_hash = _digest(
            "Repair verification check plan",
            receipt.get("check_plan_hash"),
        )
        result_hashes = _digest_list(
            "Repair verification result artifacts",
            receipt.get("result_artifact_hashes"),
            allow_empty=False,
        )
        for identity in (check_plan_hash, *result_hashes):
            verify_evidence(identity)
            verification_support.add(identity)
    if (
        set(observed_reproduction).intersection(verification_support)
        or set(new_evidence).intersection(verification_support)
    ):
        raise RepairProtocolError(
            "Repair verification support must be independent evidence"
        )

    explanation = _ascii("Repair attempt explanation", value.get("explanation"))
    failure_observation = value.get("failure_observation")
    if expected_outcome == "failed":
        failure_observation = _ascii(
            "failed Repair observation", failure_observation
        )
    elif failure_observation is not None:
        raise RepairProtocolError(
            "repaired attempt cannot carry a failure observation"
        )
    return RepairAttemptProof(
        repair_id=observed_repair_id,
        job_id=observed_job_id,
        job_hash=observed_job_hash,
        cause_hash=observed_cause_hash,
        outcome=expected_outcome,
        changed_dimension=str(changed_dimension),
        previous_basis_hash=observed_previous_basis,
        new_basis_hash=observed_new_basis,
        prior_attempt_record_id=observed_prior,
        reproduction_evidence_hashes=observed_reproduction,
        new_evidence_hashes=new_evidence,
        verification_evidence_hashes=verification_evidence,
        implementation_proof_hash=implementation_proof,
        explanation=explanation,
        failure_observation=failure_observation,
        resume_action=observed_resume,
    )


@dataclass(frozen=True, slots=True)
class EngineeringFailureDisposition:
    job_id: str
    repair_id: str | None
    cause_hash: str
    disposition: str
    basis_manifest_hash: str
    successor_scope: str | None
    rationale: str
    resume_condition: str
    repair_attempt_record_ids: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "basis_manifest_hash": self.basis_manifest_hash,
            "cause_hash": self.cause_hash,
            "disposition": self.disposition,
            "job_id": self.job_id,
            "rationale": self.rationale,
            "repair_id": self.repair_id,
            "repair_attempt_record_ids": list(self.repair_attempt_record_ids),
            "resume_condition": self.resume_condition,
            "schema": _DISPOSITION_SCHEMA,
            "successor_scope": self.successor_scope,
        }


def _disposition_attempts(
    value: object,
    *,
    label: str,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise RepairProtocolError(f"{label} must be a frozen attempt list")
    normalized: list[dict[str, Any]] = []
    required = {
        "attempt_proof_hash",
        "changed_dimension",
        "new_basis_hash",
        "repair_attempt_record_id",
        "verification_receipt_hashes",
    }
    for item in value:
        if not isinstance(item, Mapping) or set(item) != required:
            raise RepairProtocolError(f"{label} entry schema is invalid")
        changed_dimension = item.get("changed_dimension")
        if changed_dimension not in _CHANGED_DIMENSIONS:
            raise RepairProtocolError(f"{label} changed dimension is invalid")
        normalized.append(
            {
                "attempt_proof_hash": _digest(
                    f"{label} proof",
                    item.get("attempt_proof_hash"),
                ),
                "changed_dimension": str(changed_dimension),
                "new_basis_hash": _digest(
                    f"{label} basis",
                    item.get("new_basis_hash"),
                ),
                "repair_attempt_record_id": _digest(
                    f"{label} record",
                    item.get("repair_attempt_record_id"),
                ),
                "verification_receipt_hashes": list(
                    _digest_list(
                        f"{label} verification receipts",
                        item.get("verification_receipt_hashes"),
                        allow_empty=False,
                    )
                ),
            }
        )
    if normalized != sorted(
        normalized,
        key=lambda item: item["repair_attempt_record_id"],
    ) or len(
        {item["repair_attempt_record_id"] for item in normalized}
    ) != len(normalized):
        raise RepairProtocolError(f"{label} must be sorted and unique")
    return tuple(normalized)


def _validate_failed_attempt_receipts(
    attempts: Sequence[Mapping[str, Any]],
    *,
    job_id: str,
    job_hash: str,
    repair_id: str | None,
    cause_hash: str,
    read_evidence: EvidenceReader,
    verify_evidence: EvidenceVerifier,
) -> set[str]:
    support: set[str] = set()
    if attempts and repair_id is None:
        raise RepairProtocolError(
            "engineering disposition attempts require one exact Repair"
        )
    receipt_required = {
        "cause_hash",
        "changed_dimension",
        "check_plan_hash",
        "job_hash",
        "job_id",
        "new_basis_hash",
        "outcome",
        "repair_id",
        "result_artifact_hashes",
        "resume_action",
        "schema",
        "scientific_semantics_changed",
        "verdict",
        "verification_method",
    }
    for attempt in attempts:
        proof_hash = str(attempt["attempt_proof_hash"])
        verify_evidence(proof_hash)
        for receipt_hash in attempt["verification_receipt_hashes"]:
            receipt = _document(
                read_evidence(receipt_hash),
                label="engineering disposition Repair verification receipt",
            )
            if (
                set(receipt) != receipt_required
                or receipt.get("schema") != _VERIFICATION_SCHEMA
                or receipt.get("repair_id") != repair_id
                or receipt.get("job_id") != job_id
                or receipt.get("job_hash") != job_hash
                or receipt.get("cause_hash") != cause_hash
                or receipt.get("changed_dimension")
                != attempt["changed_dimension"]
                or receipt.get("new_basis_hash")
                != attempt["new_basis_hash"]
                or receipt.get("outcome") != "failed"
                or receipt.get("verdict") != "failure_reproduced"
                or receipt.get("scientific_semantics_changed") is not False
            ):
                raise RepairProtocolError(
                    "engineering disposition Repair verification differs "
                    "from its failed attempt"
                )
            _ascii(
                "engineering disposition Repair verification method",
                receipt.get("verification_method"),
            )
            _ascii(
                "engineering disposition Repair resume action",
                receipt.get("resume_action"),
            )
            check_plan = _digest(
                "engineering disposition Repair check plan",
                receipt.get("check_plan_hash"),
            )
            results = _digest_list(
                "engineering disposition Repair results",
                receipt.get("result_artifact_hashes"),
                allow_empty=False,
            )
            for identity in (check_plan, *results):
                verify_evidence(identity)
                support.add(identity)
    return support


def _validate_disposition_observation(
    document: bytes,
    *,
    job_id: str,
    job_hash: str,
    repair_id: str | None,
    cause_hash: str,
    disposition: str,
    reproduction_evidence_hashes: Sequence[str],
    repair_attempts: Sequence[Mapping[str, Any]],
    read_evidence: EvidenceReader,
    verify_evidence: EvidenceVerifier,
) -> None:
    value = _document(document, label="engineering disposition observation")
    required = {
        "cause_hash",
        "check_plan_hash",
        "disposition",
        "job_hash",
        "job_id",
        "minimum_reproduction_evidence_hashes",
        "repair_attempts",
        "repair_id",
        "result_artifact_hashes",
        "schema",
        "scientific_semantics_changed",
        "verification_method",
        "verification_result",
    }
    if (
        set(value) != required
        or value.get("schema") != _DISPOSITION_OBSERVATION_SCHEMA
        or value.get("scientific_semantics_changed") is not False
        or _typed_id(
            "engineering disposition observation Job",
            value.get("job_id"),
            "job:",
        )
        != job_id
        or _digest(
            "engineering disposition observation Job hash",
            value.get("job_hash"),
        )
        != job_hash
        or _nullable_typed_id(
            "engineering disposition observation Repair",
            value.get("repair_id"),
            "repair:",
        )
        != repair_id
        or _digest(
            "engineering disposition observation cause",
            value.get("cause_hash"),
        )
        != cause_hash
        or value.get("disposition") != disposition
        or value.get("verification_result")
        != _DISPOSITION_VERIFICATION_RESULTS[disposition]
    ):
        raise RepairProtocolError(
            "engineering disposition observation differs from exact context"
        )
    expected_reproduction = tuple(sorted(set(reproduction_evidence_hashes)))
    if (
        not expected_reproduction
        or len(expected_reproduction) != len(tuple(reproduction_evidence_hashes))
    ):
        raise RepairProtocolError(
            "engineering disposition reproduction context is ambiguous"
        )
    observed_reproduction = _digest_list(
        "engineering disposition observation reproduction evidence",
        value.get("minimum_reproduction_evidence_hashes"),
        allow_empty=False,
    )
    if observed_reproduction != expected_reproduction:
        raise RepairProtocolError(
            "engineering disposition observation changes the failure reproduction"
        )
    expected_attempts = _disposition_attempts(
        repair_attempts,
        label="expected engineering disposition attempts",
    )
    observed_attempts = _disposition_attempts(
        value.get("repair_attempts"),
        label="engineering disposition observation attempts",
    )
    if observed_attempts != expected_attempts:
        raise RepairProtocolError(
            "engineering disposition observation changes the Repair attempts"
        )
    attempt_support = _validate_failed_attempt_receipts(
        expected_attempts,
        job_id=job_id,
        job_hash=job_hash,
        repair_id=repair_id,
        cause_hash=cause_hash,
        read_evidence=read_evidence,
        verify_evidence=verify_evidence,
    )
    _ascii(
        "engineering disposition observation verification method",
        value.get("verification_method"),
    )
    check_plan = _digest(
        "engineering disposition observation check plan",
        value.get("check_plan_hash"),
    )
    result_artifacts = _digest_list(
        "engineering disposition observation results",
        value.get("result_artifact_hashes"),
        allow_empty=False,
    )
    observation_support = {check_plan, *result_artifacts}
    if (
        check_plan in result_artifacts
        or observation_support.intersection(observed_reproduction)
        or observation_support.intersection(attempt_support)
    ):
        raise RepairProtocolError(
            "engineering disposition observation requires independent "
            "verification support"
        )
    for identity in observation_support:
        verify_evidence(identity)


def _validate_disposition_basis(
    document: bytes,
    *,
    job_id: str,
    job_hash: str,
    repair_id: str | None,
    cause_hash: str,
    disposition: str,
    reproduction_evidence_hashes: Sequence[str],
    repair_attempts: Sequence[Mapping[str, Any]],
    read_evidence: EvidenceReader,
    verify_evidence: EvidenceVerifier,
) -> None:
    value = _document(document, label="engineering disposition basis")
    required = {
        "cause_hash",
        "disposition",
        "expected_value",
        "job_id",
        "observation_manifest_hash",
        "remaining_changed_causes",
        "repair_id",
        "repairable_without_scientific_change",
        "schema",
        "scientific_semantics_change_required",
    }
    if (
        set(value) != required
        or value.get("schema") != _DISPOSITION_BASIS_SCHEMA
        or _typed_id(
            "engineering disposition basis Job",
            value.get("job_id"),
            "job:",
        )
        != job_id
        or _nullable_typed_id(
            "engineering disposition basis Repair",
            value.get("repair_id"),
            "repair:",
        )
        != repair_id
        or _digest(
            "engineering disposition basis cause",
            value.get("cause_hash"),
        )
        != cause_hash
        or value.get("disposition") != disposition
    ):
        raise RepairProtocolError(
            "engineering failure disposition basis differs from context"
        )
    observation_hash = _digest(
        "engineering disposition observation manifest",
        value.get("observation_manifest_hash"),
    )
    verify_evidence(observation_hash)
    _validate_disposition_observation(
        read_evidence(observation_hash),
        job_id=job_id,
        job_hash=job_hash,
        repair_id=repair_id,
        cause_hash=cause_hash,
        disposition=disposition,
        reproduction_evidence_hashes=reproduction_evidence_hashes,
        repair_attempts=repair_attempts,
        read_evidence=read_evidence,
        verify_evidence=verify_evidence,
    )
    remaining = _ascii_list(
        "remaining changed Repair causes",
        value.get("remaining_changed_causes"),
    )
    repairable = value.get("repairable_without_scientific_change")
    semantic_change = value.get("scientific_semantics_change_required")
    expected_value = value.get("expected_value")
    if type(repairable) is not bool or type(semantic_change) is not bool:
        raise RepairProtocolError(
            "engineering disposition basis booleans are invalid"
        )
    expected = {
        "repair_exhausted_changed_causes": (
            False,
            False,
            "not_applicable",
            False,
        ),
        "repair_infeasible": (False, False, "not_applicable", False),
        "repair_nonpositive_expected_value": (
            True,
            False,
            "nonpositive",
            True,
        ),
        "requires_scientific_change": (
            False,
            True,
            "not_applicable",
            False,
        ),
    }[disposition]
    observed = (
        repairable,
        semantic_change,
        expected_value,
        bool(remaining),
    )
    if observed != expected:
        raise RepairProtocolError(
            "engineering disposition basis does not support its conclusion"
        )


def parse_engineering_failure_disposition(
    document: bytes,
    *,
    job_id: str,
    job_hash: str,
    repair_id: str | None,
    cause_hash: str,
    reproduction_evidence_hashes: Sequence[str],
    repair_attempts: Sequence[Mapping[str, Any]],
    read_evidence: EvidenceReader,
    verify_evidence: EvidenceVerifier,
) -> EngineeringFailureDisposition:
    """Validate why one engineering failure may end instead of being repaired."""

    value = _document(document, label="engineering failure disposition")
    required = {
        "basis_manifest_hash",
        "cause_hash",
        "disposition",
        "job_id",
        "rationale",
        "repair_id",
        "repair_attempt_record_ids",
        "resume_condition",
        "schema",
        "successor_scope",
    }
    if set(value) != required or value.get("schema") != _DISPOSITION_SCHEMA:
        raise RepairProtocolError(
            "engineering failure disposition schema is invalid"
        )
    observed_job = _typed_id("engineering disposition Job", value.get("job_id"), "job:")
    if observed_job != job_id:
        raise RepairProtocolError("engineering disposition names another Job")
    observed_job_hash = _digest("engineering disposition Job hash", job_hash)
    observed_repair = _nullable_typed_id(
        "engineering disposition Repair",
        value.get("repair_id"),
        "repair:",
    )
    observed_cause = _digest(
        "engineering disposition cause",
        value.get("cause_hash"),
    )
    if observed_repair != repair_id or observed_cause != cause_hash:
        raise RepairProtocolError(
            "engineering disposition differs from exact failure context"
        )
    disposition = value.get("disposition")
    if disposition not in _ENGINEERING_DISPOSITIONS:
        raise RepairProtocolError("engineering failure disposition is invalid")
    successor_scope = value.get("successor_scope")
    if disposition == "requires_scientific_change":
        if successor_scope not in _SUCCESSOR_SCOPES:
            raise RepairProtocolError(
                "scientific change disposition requires Executable or Study scope"
            )
    elif successor_scope is not None:
        raise RepairProtocolError(
            "engineering-only disposition cannot name scientific successor scope"
        )
    basis_hash = _digest(
        "engineering disposition basis",
        value.get("basis_manifest_hash"),
    )
    attempt_ids = _digest_list(
        "engineering disposition Repair attempts",
        value.get("repair_attempt_record_ids"),
        allow_empty=True,
    )
    expected_attempts = _disposition_attempts(
        repair_attempts,
        label="expected engineering disposition attempts",
    )
    expected_attempt_ids = tuple(
        item["repair_attempt_record_id"] for item in expected_attempts
    )
    if attempt_ids != expected_attempt_ids:
        raise RepairProtocolError(
            "engineering disposition differs from exact failed Repair attempts"
        )
    _validate_disposition_basis(
        read_evidence(basis_hash),
        job_id=observed_job,
        job_hash=observed_job_hash,
        repair_id=observed_repair,
        cause_hash=observed_cause,
        disposition=str(disposition),
        reproduction_evidence_hashes=reproduction_evidence_hashes,
        repair_attempts=expected_attempts,
        read_evidence=read_evidence,
        verify_evidence=verify_evidence,
    )
    if disposition == "repair_exhausted_changed_causes" and (
        observed_repair is None or not attempt_ids
    ):
        raise RepairProtocolError(
            "exhausted Repair disposition requires failed changed-cause attempts"
        )
    return EngineeringFailureDisposition(
        job_id=observed_job,
        repair_id=observed_repair,
        cause_hash=observed_cause,
        disposition=str(disposition),
        basis_manifest_hash=basis_hash,
        successor_scope=(
            None if successor_scope is None else str(successor_scope)
        ),
        rationale=_ascii(
            "engineering disposition rationale", value.get("rationale")
        ),
        resume_condition=_ascii(
            "engineering disposition resume condition",
            value.get("resume_condition"),
        ),
        repair_attempt_record_ids=attempt_ids,
    )


__all__ = [
    "EngineeringFailureDisposition",
    "RepairAttemptProof",
    "RepairProtocolError",
    "parse_engineering_failure_disposition",
    "parse_repair_attempt_proof",
]
