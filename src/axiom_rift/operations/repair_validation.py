"""Registered independent validation for Repair attempts and dispositions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.repair_candidate import (
    RepairCandidate,
    RepairCandidateError,
    build_repair_evaluation,
    parse_repair_candidate,
    parse_repair_evaluation,
)
from axiom_rift.operations.repair_disposition_case import (
    REPAIR_DISPOSITION_CASE_SCHEMA,
    RepairDispositionCaseError,
    derive_repair_disposition,
    normalize_repair_disposition_case,
)
from axiom_rift.operations.repair_disposition_inventory import (
    RepairDispositionInventoryError,
    normalize_repair_inventory_facts,
    repair_inventory_information_set_hash,
)
from axiom_rift.operations.repair_protocol import (
    EngineeringFailureDisposition,
)
from axiom_rift.operations.repair_semantic_change_authority import (
    RepairSemanticChangeAuthorityError,
    semantic_change_facts,
)
from axiom_rift.operations.validation import (
    EngineeringRepairValidationRequest,
    EvidenceValidationError,
    EvidenceValidatorRegistry,
    ValidationArtifact,
)
from axiom_rift.storage.evidence import EvidenceStore


class RepairValidationError(ValueError):
    """Repair evidence was not independently validated as claimed."""


class RepairValidationUnavailableError(RepairValidationError):
    """One typed zero-credit reason from a failed registered dispatch."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


PLAN_SCHEMA = "engineering_repair_validation_plan.v1"
BINDING_SCHEMA = "engineering_repair_validation_binding.v1"
TRACE_SCHEMA = "engineering_repair_registered_validation.v2"
ATTEMPT_TRACE_SCHEMA = "engineering_repair_attempt_validations.v2"
DISPOSITION_TRACE_SCHEMA = "engineering_repair_disposition_validation.v3"
DISPOSITION_DERIVATION_SCHEMA = (
    "engineering_repair_disposition_derivation.v1"
)
REGISTERED_REPAIR_AUTHORITY_SCHEMA = "registered_repair_authority.v2"
CANDIDATE_RECEIPT_SCHEMA = "repair_candidate_validation_receipt.v2"
CANDIDATE_TRACE_SCHEMA = "engineering_repair_candidate_validation.v2"
INVENTORY_RECEIPT_SCHEMA = "engineering_repair_inventory_validation_receipt.v1"
INVENTORY_TRACE_SCHEMA = "engineering_repair_inventory_validation.v1"
SEMANTIC_CHANGE_RECEIPT_SCHEMA = (
    "engineering_semantic_change_validation_receipt.v1"
)
SEMANTIC_CHANGE_TRACE_SCHEMA = (
    "engineering_semantic_change_necessity_validation.v2"
)
_OBSERVATION_BINDING_UNBOUND = object()
_CANDIDATE_FLAT_COMPATIBILITY_FIELDS = frozenset(
    {
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
        "repair_id",
        "reproduction_evidence_hashes",
        "resume_action",
        "scientific_semantics_changed",
        "verification_evidence_hashes",
    }
)


def _ascii(label: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise RepairValidationError(f"{label} must be non-empty ASCII")
    return value


def _digest(label: str, value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RepairValidationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _digest_list(
    label: str,
    value: object,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or (not allow_empty and not value)
        or list(value) != sorted(set(value))
    ):
        raise RepairValidationError(
            f"{label} must be a sorted unique digest list"
        )
    return tuple(_digest(label, item) for item in value)


def _typed_digest(label: str, value: object, prefix: str) -> str:
    text = _ascii(label, value)
    if not text.startswith(prefix):
        raise RepairValidationError(f"{label} has an invalid prefix")
    _digest(label, text.removeprefix(prefix))
    return text


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def _canonical_mapping(label: str, value: object) -> dict[str, Any]:
    try:
        copied = parse_canonical(canonical_bytes(_plain(value)))
    except (TypeError, ValueError) as exc:
        raise RepairValidationError(f"{label} is not canonical") from exc
    if not isinstance(copied, dict):
        raise RepairValidationError(f"{label} must be an object")
    return copied


def _document(content: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = parse_canonical(content)
    except (TypeError, ValueError) as exc:
        raise RepairValidationError(f"{label} is not canonical") from exc
    if not isinstance(value, dict):
        raise RepairValidationError(f"{label} must be an object")
    return value


def _artifact_roles(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise RepairValidationError("Repair validation artifact roles are absent")
    roles: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"output_name", "sha256"}:
            raise RepairValidationError(
                "Repair validation artifact role schema is invalid"
            )
        roles.append(
            (
                _ascii("Repair validation output name", item.get("output_name")),
                _digest("Repair validation artifact", item.get("sha256")),
            )
        )
    if (
        roles != sorted(roles)
        or len({name for name, _identity in roles}) != len(roles)
        or len({identity for _name, identity in roles}) != len(roles)
        or any(name == "validation_plan" for name, _identity in roles)
    ):
        raise RepairValidationError(
            "Repair validation artifact roles must be sorted and unique"
        )
    return tuple(roles)


def repair_validation_binding(
    *,
    verification_kind: str,
    mission_id: str,
    protocol: str,
    context: Mapping[str, Any],
    artifact_roles: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    """Build the exact binding shared by a producer and the Writer."""

    if verification_kind not in {
        "attempt",
        "candidate",
        "disposition",
        "inventory",
        "semantic_change",
    }:
        raise RepairValidationError("Repair verification kind is invalid")
    normalized_roles = tuple(
        (
            _ascii("Repair validation output name", name),
            _digest("Repair validation artifact", identity),
        )
        for name, identity in artifact_roles
    )
    if (
        not normalized_roles
        or normalized_roles != tuple(sorted(normalized_roles))
        or len({name for name, _identity in normalized_roles})
        != len(normalized_roles)
        or len({identity for _name, identity in normalized_roles})
        != len(normalized_roles)
    ):
        raise RepairValidationError(
            "Repair validation artifact roles must be sorted and unique"
        )
    return {
        "artifact_roles": [
            {"output_name": name, "sha256": identity}
            for name, identity in normalized_roles
        ],
        "context": _canonical_mapping("Repair validation context", context),
        "mission_id": _ascii("Repair validation Mission", mission_id),
        "protocol": _ascii("Repair validation protocol", protocol),
        "schema": BINDING_SCHEMA,
        "verification_kind": verification_kind,
    }


def build_repair_validation_plan(
    *,
    validator_id: str,
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the common immutable plan envelope for a registered validator."""

    copied = _canonical_mapping("Repair validation binding", binding)
    if copied.get("schema") != BINDING_SCHEMA:
        raise RepairValidationError("Repair validation binding schema is invalid")
    return {
        "artifact_roles": copied["artifact_roles"],
        "binding_sha256": sha256(canonical_bytes(copied)).hexdigest(),
        "protocol": copied["protocol"],
        "schema": PLAN_SCHEMA,
        "validator_id": _ascii("Repair validator id", validator_id),
        "verification_kind": copied["verification_kind"],
    }


def build_repair_attempt_validation_context(
    *,
    cause_hash: str,
    changed_dimension: str,
    explanation: str,
    failure_observation: str | None,
    implementation_proof_hash: str | None,
    job_hash: str,
    job_id: str,
    new_basis_hash: str,
    new_evidence_hashes: Sequence[str],
    outcome: str,
    previous_basis_hash: str,
    prior_attempt_record_id: str | None,
    repair_id: str,
    reproduction_evidence_hashes: Sequence[str],
    resume_action: str,
) -> dict[str, Any]:
    """Build the exact context shared by a producer and parsed attempt."""

    return _canonical_mapping(
        "Repair attempt validation context",
        {
            "cause_hash": cause_hash,
            "changed_dimension": changed_dimension,
            "explanation": explanation,
            "failure_observation": failure_observation,
            "implementation_proof_hash": implementation_proof_hash,
            "job_hash": job_hash,
            "job_id": job_id,
            "new_basis_hash": new_basis_hash,
            "new_evidence_hashes": list(new_evidence_hashes),
            "outcome": outcome,
            "previous_basis_hash": previous_basis_hash,
            "prior_attempt_record_id": prior_attempt_record_id,
            "repair_id": repair_id,
            "reproduction_evidence_hashes": list(
                reproduction_evidence_hashes
            ),
            "resume_action": resume_action,
            "scientific_semantics_changed": False,
        },
    )


def build_repair_candidate_validation_context(
    *,
    bound_validation_observations: Sequence[Mapping[str, Any]],
    cause_hash: str,
    changed_dimension: str,
    explanation: str,
    implementation_proof_hash: str | None,
    job_hash: str,
    job_id: str,
    new_basis_hash: str,
    new_evidence_hashes: Sequence[str],
    previous_basis_hash: str,
    prior_attempt_record_id: str | None,
    prior_validation_observation_head: Mapping[str, Any] | None,
    repair_axis_id: str,
    repair_id: str,
    reproduction_evidence_hashes: Sequence[str],
    resume_action: str,
) -> dict[str, Any]:
    """Build the exact outcome-free core shared by producer and validator."""

    return _canonical_mapping(
        "Repair candidate validation context",
        {
            "bound_validation_observations": [
                dict(item) for item in bound_validation_observations
            ],
            "cause_hash": cause_hash,
            "changed_dimension": changed_dimension,
            "explanation": explanation,
            "implementation_proof_hash": implementation_proof_hash,
            "job_hash": job_hash,
            "job_id": job_id,
            "new_basis_hash": new_basis_hash,
            "new_evidence_hashes": list(new_evidence_hashes),
            "previous_basis_hash": previous_basis_hash,
            "prior_attempt_record_id": prior_attempt_record_id,
            "prior_validation_observation_head": (
                None
                if prior_validation_observation_head is None
                else dict(prior_validation_observation_head)
            ),
            "repair_axis_id": repair_axis_id,
            "repair_id": repair_id,
            "reproduction_evidence_hashes": list(
                reproduction_evidence_hashes
            ),
            "resume_action": resume_action,
            "schema": "running_job_repair_candidate.v3",
            "scientific_semantics_changed": False,
        },
    )


def repair_candidate_validation_context(
    candidate: RepairCandidate,
) -> dict[str, Any]:
    """Return the outcome-free candidate core that a plan can bind.

    The verification receipt is deliberately omitted.  Including it would
    create a content-addressing cycle because the candidate names the receipt
    while the receipt names the plan that binds this context.
    """

    return build_repair_candidate_validation_context(
        bound_validation_observations=(
            candidate.payload()["bound_validation_observations"]
        ),
        cause_hash=candidate.cause_hash,
        changed_dimension=candidate.changed_dimension,
        explanation=candidate.explanation,
        implementation_proof_hash=candidate.implementation_proof_hash,
        job_hash=candidate.job_hash,
        job_id=candidate.job_id,
        new_basis_hash=candidate.new_basis_hash,
        new_evidence_hashes=candidate.new_evidence_hashes,
        previous_basis_hash=candidate.previous_basis_hash,
        prior_attempt_record_id=candidate.prior_attempt_record_id,
        prior_validation_observation_head=(
            candidate.payload()["prior_validation_observation_head"]
        ),
        repair_axis_id=candidate.repair_axis_id,
        repair_id=candidate.repair_id,
        reproduction_evidence_hashes=candidate.reproduction_evidence_hashes,
        resume_action=candidate.resume_action,
    )


def build_repair_candidate_validation_receipt(
    *,
    validator_id: str,
    validation_plan_hash: str,
    protocol: str,
    result_artifact_hashes: Sequence[str],
) -> dict[str, Any]:
    """Build routing authority for one outcome-free registered dispatch."""

    results = tuple(
        _digest("Repair candidate result artifact", identity)
        for identity in result_artifact_hashes
    )
    if not results or results != tuple(sorted(set(results))):
        raise RepairValidationError(
            "Repair candidate result artifacts must be sorted and unique"
        )
    return {
        "check_plan_hash": _digest(
            "Repair candidate validation plan", validation_plan_hash
        ),
        "protocol": _ascii("Repair candidate validation protocol", protocol),
        "result_artifact_hashes": list(results),
        "schema": CANDIDATE_RECEIPT_SCHEMA,
        "validator_id": _typed_digest(
            "Repair candidate validator", validator_id, "validator:"
        ),
    }


def parse_repair_candidate_validation_receipt(
    content: bytes,
) -> dict[str, Any]:
    receipt = _document(content, label="Repair candidate validation receipt")
    if set(receipt) != {
        "check_plan_hash",
        "protocol",
        "result_artifact_hashes",
        "schema",
        "validator_id",
    } or receipt.get("schema") != CANDIDATE_RECEIPT_SCHEMA:
        raise RepairValidationError(
            "Repair candidate validation receipt schema is invalid"
        )
    return build_repair_candidate_validation_receipt(
        validator_id=receipt.get("validator_id"),
        validation_plan_hash=receipt.get("check_plan_hash"),
        protocol=receipt.get("protocol"),
        result_artifact_hashes=receipt.get("result_artifact_hashes", ()),
    )


def build_semantic_change_validation_receipt(
    *,
    validator_id: str,
    validation_plan_hash: str,
    protocol: str,
    result_artifact_hashes: Sequence[str],
) -> dict[str, Any]:
    """Build a route to an outcome-free semantic-necessity dispatch."""

    receipt = build_repair_candidate_validation_receipt(
        validator_id=validator_id,
        validation_plan_hash=validation_plan_hash,
        protocol=protocol,
        result_artifact_hashes=result_artifact_hashes,
    )
    receipt["schema"] = SEMANTIC_CHANGE_RECEIPT_SCHEMA
    return receipt


def parse_semantic_change_validation_receipt(
    content: bytes,
) -> dict[str, Any]:
    receipt = _document(content, label="semantic-change validation receipt")
    if set(receipt) != {
        "check_plan_hash",
        "protocol",
        "result_artifact_hashes",
        "schema",
        "validator_id",
    } or receipt.get("schema") != SEMANTIC_CHANGE_RECEIPT_SCHEMA:
        raise RepairValidationError(
            "semantic-change validation receipt schema is invalid"
        )
    return build_semantic_change_validation_receipt(
        validator_id=receipt.get("validator_id"),
        validation_plan_hash=receipt.get("check_plan_hash"),
        protocol=receipt.get("protocol"),
        result_artifact_hashes=receipt.get("result_artifact_hashes", ()),
    )


def build_repair_inventory_validation_receipt(
    *,
    validator_id: str,
    validation_plan_hash: str,
    protocol: str,
    result_artifact_hashes: Sequence[str],
) -> dict[str, Any]:
    """Build a route to one registered domain Repair inventory review."""

    receipt = build_repair_candidate_validation_receipt(
        validator_id=validator_id,
        validation_plan_hash=validation_plan_hash,
        protocol=protocol,
        result_artifact_hashes=result_artifact_hashes,
    )
    receipt["schema"] = INVENTORY_RECEIPT_SCHEMA
    return receipt


def parse_repair_inventory_validation_receipt(
    content: bytes,
) -> dict[str, Any]:
    receipt = _document(content, label="Repair inventory validation receipt")
    if set(receipt) != {
        "check_plan_hash",
        "protocol",
        "result_artifact_hashes",
        "schema",
        "validator_id",
    } or receipt.get("schema") != INVENTORY_RECEIPT_SCHEMA:
        raise RepairValidationError(
            "Repair inventory validation receipt schema is invalid"
        )
    return build_repair_inventory_validation_receipt(
        validator_id=receipt.get("validator_id"),
        validation_plan_hash=receipt.get("check_plan_hash"),
        protocol=receipt.get("protocol"),
        result_artifact_hashes=receipt.get("result_artifact_hashes", ()),
    )


def _prepare_registered_dispatch(
    *,
    evidence: EvidenceStore,
    engineering_fixture: bool,
    mission_id: str,
    job_id: str,
    job_hash: str,
    repair_id: str | None,
    verification_kind: str,
    evidence_subject: Mapping[str, str],
    context: Mapping[str, Any],
    validation_plan_hash: str,
    protocol: str,
    result_artifact_hashes: Sequence[str],
) -> tuple[
    dict[str, str],
    str,
    tuple[str, ...],
    dict[str, Any],
    list[ValidationArtifact],
    EngineeringRepairValidationRequest,
]:
    expected_subject = (
        {"kind": "Repair", "id": repair_id}
        if repair_id is not None
        else {"kind": "Job", "id": job_id}
    )
    if dict(evidence_subject) != expected_subject:
        raise RepairValidationError(
            "Repair validation evidence subject differs from its authority"
        )
    plan = _document(
        evidence.read_verified(validation_plan_hash),
        label="Repair validation plan",
    )
    required = {
        "artifact_roles",
        "binding_sha256",
        "protocol",
        "schema",
        "validator_id",
        "verification_kind",
    }
    if (
        set(plan) != required
        or plan.get("schema") != PLAN_SCHEMA
        or plan.get("verification_kind") != verification_kind
        or plan.get("protocol") != protocol
    ):
        raise RepairValidationError(
            "Repair validation plan differs from its verification receipt"
        )
    roles = _artifact_roles(plan.get("artifact_roles"))
    expected_results = tuple(sorted(set(result_artifact_hashes)))
    if (
        len(expected_results) != len(tuple(result_artifact_hashes))
        or tuple(sorted(identity for _name, identity in roles))
        != expected_results
        or validation_plan_hash in expected_results
    ):
        raise RepairValidationError(
            "Repair validation plan differs from its result artifacts"
        )
    binding = repair_validation_binding(
        verification_kind=verification_kind,
        mission_id=mission_id,
        protocol=protocol,
        context=context,
        artifact_roles=roles,
    )
    if plan.get("binding_sha256") != sha256(canonical_bytes(binding)).hexdigest():
        raise RepairValidationError(
            "Repair validation plan does not bind the authoritative context"
        )
    validator_id = _ascii("Repair validator id", plan.get("validator_id"))
    artifacts = [
        ValidationArtifact(
            output_name="validation_plan",
            sha256=validation_plan_hash,
            _source=evidence.verified_path(validation_plan_hash),
        )
    ]
    artifacts.extend(
        ValidationArtifact(
            output_name=name,
            sha256=identity,
            _source=evidence.verified_path(identity),
        )
        for name, identity in roles
    )
    request = EngineeringRepairValidationRequest(
        validator_id=validator_id,
        validation_plan_hash=validation_plan_hash,
        mission_id=mission_id,
        job_id=job_id,
        job_hash=job_hash,
        repair_id=repair_id,
        verification_kind=verification_kind,
        evidence_subject=evidence_subject,
        binding=binding,
        result_manifest={
            "protocol": protocol,
            "result_artifact_hashes": list(expected_results),
            "schema": "engineering_repair_validation_dispatch.v1",
            "verification_kind": verification_kind,
        },
        artifacts=tuple(artifacts),
        engineering_fixture=engineering_fixture,
    )
    return (
        expected_subject,
        validator_id,
        expected_results,
        binding,
        artifacts,
        request,
    )


def _execute_registered_dispatch(
    *,
    registry: EvidenceValidatorRegistry,
    protocol: str,
    validator_id: str,
    expected_results: tuple[str, ...],
    artifacts: Sequence[ValidationArtifact],
    request: EngineeringRepairValidationRequest,
) -> tuple[Any, Any, dict[str, Any]]:
    try:
        registry.require_plannable_protocol(
            validator_id=validator_id,
            domain="engineering",
            protocol=protocol,
        )
    except EvidenceValidationError as exc:
        raise RepairValidationUnavailableError(
            f"registered Repair validation authorization failed: {exc}",
            reason_code=(
                exc.reason_code
                or "validator_protocol_or_identity_mismatch"
            ),
        ) from exc
    try:
        validated, trace = registry.validate(request)
    except EvidenceValidationError as exc:
        raise RepairValidationUnavailableError(
            f"registered Repair validation failed: {exc}",
            reason_code=(exc.reason_code or "validator_execution_failed"),
        ) from exc
    facts = _canonical_mapping("registered Repair validation facts", validated.facts)
    expected_roles = tuple(
        sorted((artifact.output_name, artifact.sha256) for artifact in artifacts)
    )
    if (
        validated.claims
        or validated.measurement_artifact_hashes != expected_results
        or validated.artifact_roles != expected_roles
        or validated.scientific_eligible
        or validated.candidate_eligible
        or validated.release_eligible
        or trace.validator_id != validator_id
        or trace.declared_artifact_count != len(artifacts)
        or trace.opened_artifact_count != len(artifacts)
    ):
        raise RepairValidationUnavailableError(
            "registered Repair validation roles or registry trace is partial",
            reason_code="partial_validator_result",
        )
    return validated, trace, facts


def _dispatch(
    *,
    evidence: EvidenceStore,
    registry: EvidenceValidatorRegistry,
    engineering_fixture: bool,
    mission_id: str,
    job_id: str,
    job_hash: str,
    repair_id: str | None,
    verification_kind: str,
    evidence_subject: Mapping[str, str],
    context: Mapping[str, Any],
    validation_plan_hash: str,
    protocol: str,
    result_artifact_hashes: Sequence[str],
    expected_facts: Mapping[str, Any],
) -> dict[str, Any]:
    (
        expected_subject,
        validator_id,
        expected_results,
        binding,
        artifacts,
        request,
    ) = _prepare_registered_dispatch(
        evidence=evidence,
        engineering_fixture=engineering_fixture,
        mission_id=mission_id,
        job_id=job_id,
        job_hash=job_hash,
        repair_id=repair_id,
        verification_kind=verification_kind,
        evidence_subject=evidence_subject,
        context=context,
        validation_plan_hash=validation_plan_hash,
        protocol=protocol,
        result_artifact_hashes=result_artifact_hashes,
    )
    validated, trace, facts = _execute_registered_dispatch(
        registry=registry,
        protocol=protocol,
        validator_id=validator_id,
        expected_results=expected_results,
        artifacts=artifacts,
        request=request,
    )
    expected = {
        "binding": binding,
        **_canonical_mapping("expected Repair validation facts", expected_facts),
    }
    if validated.verdict != "passed" or facts != expected:
        raise RepairValidationError(
            "registered Repair validation verdict or facts is partial"
        )
    return {
        "authority_scope": (
            "fixture_only" if engineering_fixture else "production"
        ),
        "evidence_subject": expected_subject,
        "facts": facts,
        "protocol": protocol,
        "registry_trace": {
            "declared_artifact_count": trace.declared_artifact_count,
            "opened_artifact_count": trace.opened_artifact_count,
            "validator_id": trace.validator_id,
        },
        "result_artifact_hashes": list(expected_results),
        "schema": TRACE_SCHEMA,
        "validation_plan_hash": validation_plan_hash,
        "verification_kind": verification_kind,
        "verdict": validated.verdict,
    }


def _dispatch_authoritative_facts(
    *,
    evidence: EvidenceStore,
    registry: EvidenceValidatorRegistry,
    engineering_fixture: bool,
    mission_id: str,
    job_id: str,
    job_hash: str,
    repair_id: str | None,
    verification_kind: str,
    evidence_subject: Mapping[str, str],
    context: Mapping[str, Any],
    validation_plan_hash: str,
    protocol: str,
    result_artifact_hashes: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Dispatch a registered validator whose facts are the domain authority."""

    (
        expected_subject,
        validator_id,
        expected_results,
        binding,
        artifacts,
        request,
    ) = _prepare_registered_dispatch(
        evidence=evidence,
        engineering_fixture=engineering_fixture,
        mission_id=mission_id,
        job_id=job_id,
        job_hash=job_hash,
        repair_id=repair_id,
        verification_kind=verification_kind,
        evidence_subject=evidence_subject,
        context=context,
        validation_plan_hash=validation_plan_hash,
        protocol=protocol,
        result_artifact_hashes=result_artifact_hashes,
    )
    validated, registry_trace, facts = _execute_registered_dispatch(
        registry=registry,
        protocol=protocol,
        validator_id=validator_id,
        expected_results=expected_results,
        artifacts=artifacts,
        request=request,
    )
    if validated.verdict != "passed" or facts.get("binding") != binding:
        raise RepairValidationError(
            "registered Repair authority verdict or binding is partial"
        )
    authority_facts = {
        key: value for key, value in facts.items() if key != "binding"
    }
    trace = {
        "authority_scope": (
            "fixture_only" if engineering_fixture else "production"
        ),
        "evidence_subject": expected_subject,
        "facts": facts,
        "protocol": protocol,
        "registry_trace": {
            "declared_artifact_count": registry_trace.declared_artifact_count,
            "opened_artifact_count": registry_trace.opened_artifact_count,
            "validator_id": registry_trace.validator_id,
        },
        "result_artifact_hashes": list(expected_results),
        "schema": TRACE_SCHEMA,
        "validation_plan_hash": validation_plan_hash,
        "verification_kind": verification_kind,
        "verdict": validated.verdict,
    }
    return trace, authority_facts


def validate_repair_candidate(
    *,
    candidate: RepairCandidate,
    mission_id: str,
    evidence: EvidenceStore,
    registry: EvidenceValidatorRegistry,
    engineering_fixture: bool,
) -> dict[str, Any]:
    """Evaluate one outcome-free candidate through one registered dispatch.

    Validator absence and dispatch failure are intentionally raised to the
    Writer.  The Writer owns the stable-head-bound zero-credit observation and
    therefore derives, rather than trusts, the unavailable reason.
    """

    if len(candidate.verification_evidence_hashes) != 1:
        raise RepairValidationUnavailableError(
            "Repair candidate requires one exact validation receipt",
            reason_code="plan_or_context_binding_mismatch",
        )
    receipt_hash = candidate.verification_evidence_hashes[0]
    try:
        receipt_content = evidence.read_verified(receipt_hash)
    except (FileNotFoundError, OSError) as exc:
        raise RepairValidationUnavailableError(
            "Repair candidate validation receipt is absent",
            reason_code="declared_artifact_absent_drifted_or_unopened",
        ) from exc
    try:
        receipt = parse_repair_candidate_validation_receipt(receipt_content)
    except RepairValidationError as exc:
        raise RepairValidationUnavailableError(
            str(exc),
            reason_code="plan_or_context_binding_mismatch",
        ) from exc
    context = repair_candidate_validation_context(candidate)
    try:
        (
            expected_subject,
            validator_id,
            expected_results,
            binding,
            artifacts,
            request,
        ) = _prepare_registered_dispatch(
            evidence=evidence,
            engineering_fixture=engineering_fixture,
            mission_id=mission_id,
            job_id=candidate.job_id,
            job_hash=candidate.job_hash,
            repair_id=candidate.repair_id,
            verification_kind="candidate",
            evidence_subject={"kind": "Repair", "id": candidate.repair_id},
            context=context,
            validation_plan_hash=receipt["check_plan_hash"],
            protocol=receipt["protocol"],
            result_artifact_hashes=receipt["result_artifact_hashes"],
        )
    except EvidenceValidationError as exc:
        raise RepairValidationUnavailableError(
            str(exc),
            reason_code=(
                exc.reason_code
                or "declared_artifact_absent_drifted_or_unopened"
            ),
        ) from exc
    except (FileNotFoundError, OSError) as exc:
        raise RepairValidationUnavailableError(
            str(exc),
            reason_code="declared_artifact_absent_drifted_or_unopened",
        ) from exc
    except RepairValidationUnavailableError:
        raise
    except RepairValidationError as exc:
        raise RepairValidationUnavailableError(
            str(exc),
            reason_code="plan_or_context_binding_mismatch",
        ) from exc
    if validator_id != receipt["validator_id"]:
        raise RepairValidationUnavailableError(
            "Repair candidate receipt and plan validators differ",
            reason_code="validator_protocol_or_identity_mismatch",
        )
    validated, registry_trace, facts = _execute_registered_dispatch(
        registry=registry,
        protocol=receipt["protocol"],
        validator_id=validator_id,
        expected_results=expected_results,
        artifacts=artifacts,
        request=request,
    )
    if facts.get("binding") != binding:
        raise RepairValidationUnavailableError(
            "registered Repair candidate facts lost their exact binding",
            reason_code="plan_or_context_binding_mismatch",
        )
    evaluation_facts = {
        key: value for key, value in facts.items() if key != "binding"
    }
    required_facts = {
        "cause_resolved",
        "failure_reproduced",
        "material_change",
        "mode",
        "new_failure_manifest_hash",
        "reason_code",
    }
    if set(evaluation_facts) != required_facts:
        raise RepairValidationUnavailableError(
            "registered Repair candidate evaluation facts are partial",
            reason_code="partial_validator_result",
        )
    expected_verdict = {
        "failure_reproduced": "passed",
        "invalid_change": "failed",
        "new_failure": "passed",
        "not_evaluable": "not_evaluable",
        "repaired": "passed",
    }.get(evaluation_facts.get("mode"))
    if validated.verdict != expected_verdict:
        raise RepairValidationUnavailableError(
            "registered Repair candidate mode and verdict differ",
            reason_code="facts_roles_or_registry_trace_mismatch",
        )
    registered_trace = {
        "authority_scope": (
            "fixture_only" if engineering_fixture else "production"
        ),
        "evidence_subject": expected_subject,
        "facts": facts,
        "protocol": receipt["protocol"],
        "registry_trace": {
            "declared_artifact_count": registry_trace.declared_artifact_count,
            "opened_artifact_count": registry_trace.opened_artifact_count,
            "validator_id": registry_trace.validator_id,
        },
        "result_artifact_hashes": list(expected_results),
        "schema": TRACE_SCHEMA,
        "validation_plan_hash": receipt["check_plan_hash"],
        "verification_kind": "candidate",
        "verdict": validated.verdict,
    }
    registered_trace_hash = sha256(
        canonical_bytes(registered_trace)
    ).hexdigest()
    try:
        evaluation_payload = build_repair_evaluation(
            candidate_hash=candidate.sha256,
            validator_id=validator_id,
            validation_plan_hash=receipt["check_plan_hash"],
            registry_trace_hash=registered_trace_hash,
            mode=evaluation_facts["mode"],
            cause_resolved=evaluation_facts["cause_resolved"],
            failure_reproduced=evaluation_facts["failure_reproduced"],
            material_change=evaluation_facts["material_change"],
            new_failure_manifest_hash=evaluation_facts[
                "new_failure_manifest_hash"
            ],
            reason_code=evaluation_facts["reason_code"],
            read_evidence=evidence.read_verified,
        )
        parse_repair_evaluation(
            canonical_bytes(evaluation_payload),
            candidate_hash=candidate.sha256,
            validator_id=validator_id,
            validation_plan_hash=receipt["check_plan_hash"],
            registry_trace_hash=registered_trace_hash,
            read_evidence=evidence.read_verified,
        )
    except RepairCandidateError as exc:
        raise RepairValidationUnavailableError(
            str(exc),
            reason_code="facts_roles_or_registry_trace_mismatch",
        ) from exc
    body = {
        "evaluation": evaluation_payload,
        "receipt_hash": receipt_hash,
        "registered_trace": registered_trace,
        "registered_trace_hash": registered_trace_hash,
        "schema": CANDIDATE_TRACE_SCHEMA,
    }
    return {
        **body,
        "trace_sha256": sha256(canonical_bytes(body)).hexdigest(),
    }


def _named_result_document(
    *,
    evidence: EvidenceStore,
    validation_plan_hash: str,
    result_artifact_hashes: Sequence[str],
    output_name: str,
    label: str,
) -> tuple[str, dict[str, Any]]:
    plan = _document(
        evidence.read_verified(validation_plan_hash),
        label=f"{label} validation plan",
    )
    roles = dict(_artifact_roles(plan.get("artifact_roles")))
    identity = roles.get(output_name)
    if (
        identity is None
        or identity not in result_artifact_hashes
        or set(roles.values()) != set(result_artifact_hashes)
    ):
        raise RepairValidationError(
            f"{label} result roles are incomplete or ambiguous"
        )
    return identity, _document(
        evidence.read_verified(identity),
        label=f"{label} {output_name}",
    )


def build_repair_inventory_validation_context(
    *,
    job_id: str,
    job_hash: str,
    repair_id: str,
    cause_hash: str,
    current_basis_hash: str,
    accepted_attempts: Sequence[Mapping[str, Any]],
    repair_validation_observations: Sequence[Mapping[str, Any]],
    repair_validation_observation_head: Mapping[str, Any] | None,
    reproduction_evidence_hashes: Sequence[str],
    authority_head: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the exact head-bound context for a domain inventory validator."""

    normalized_attempts = [
        _canonical_mapping("Repair inventory accepted attempt", item)
        for item in accepted_attempts
    ]
    normalized_observations = [
        _canonical_mapping("Repair inventory validation observation", item)
        for item in repair_validation_observations
    ]
    normalized_head = (
        None
        if repair_validation_observation_head is None
        else _canonical_mapping(
            "Repair inventory validation observation head",
            repair_validation_observation_head,
        )
    )
    normalized_authority_head = _canonical_mapping(
        "Repair inventory authority head", authority_head
    )
    information_set_hash = repair_inventory_information_set_hash(
        cause_hash=cause_hash,
        current_basis_hash=current_basis_hash,
        accepted_attempts=normalized_attempts,
        validation_observations=normalized_observations,
        validation_observation_head=normalized_head,
    )
    return {
        "accepted_attempt_head_record_id": (
            None
            if not normalized_attempts
            else normalized_attempts[-1].get("repair_attempt_record_id")
        ),
        "authority_head": normalized_authority_head,
        "cause_hash": _digest("Repair inventory cause", cause_hash),
        "current_basis_hash": _digest(
            "Repair inventory current basis", current_basis_hash
        ),
        "information_set_hash": information_set_hash,
        "job_hash": _digest("Repair inventory Job hash", job_hash),
        "job_id": _typed_digest("Repair inventory Job", job_id, "job:"),
        "repair_attempts": normalized_attempts,
        "repair_id": _typed_digest(
            "Repair inventory Repair", repair_id, "repair:"
        ),
        "repair_validation_observation_head": normalized_head,
        "repair_validation_observations": normalized_observations,
        "reproduction_evidence_hashes": list(
            _digest_list(
                "Repair inventory reproduction evidence",
                reproduction_evidence_hashes,
                allow_empty=False,
            )
        ),
        "schema": "engineering_repair_inventory_context.v1",
        "scientific_semantics_changed": False,
    }


def build_repair_inventory_authority_head(
    control: Mapping[str, Any],
) -> dict[str, Any]:
    """Project the exact stable control head bound by inventory authority."""

    document = _canonical_mapping("Repair inventory control", control)
    heads = document.get("heads")
    if (
        not isinstance(heads, Mapping)
        or not isinstance(heads.get("journal"), Mapping)
        or not isinstance(heads.get("index"), Mapping)
        or type(document.get("revision")) is not int
        or document["revision"] < 0
    ):
        raise RepairValidationError(
            "Repair inventory requires one authenticated authority head"
        )
    return {
        "control_hash": _digest(
            "Repair inventory control hash", document.get("control_hash")
        ),
        "index": _canonical_mapping(
            "Repair inventory index head", heads["index"]
        ),
        "journal": _canonical_mapping(
            "Repair inventory Journal head", heads["journal"]
        ),
        "revision": document["revision"],
        "schema": "engineering_repair_inventory_authority_head.v1",
    }


def validate_repair_inventory(
    *,
    receipt_hash: str,
    mission_id: str,
    job_id: str,
    job_hash: str,
    repair_id: str,
    cause_hash: str,
    current_basis_hash: str,
    accepted_attempts: Sequence[Mapping[str, Any]],
    repair_validation_observations: Sequence[Mapping[str, Any]],
    repair_validation_observation_head: Mapping[str, Any] | None,
    reproduction_evidence_hashes: Sequence[str],
    authority_head: Mapping[str, Any],
    evidence: EvidenceStore,
    registry: EvidenceValidatorRegistry,
    engineering_fixture: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one registered domain validator for complete Repair inventory facts."""

    receipt = parse_repair_inventory_validation_receipt(
        evidence.read_verified(receipt_hash)
    )
    context = build_repair_inventory_validation_context(
        job_id=job_id,
        job_hash=job_hash,
        repair_id=repair_id,
        cause_hash=cause_hash,
        current_basis_hash=current_basis_hash,
        accepted_attempts=accepted_attempts,
        repair_validation_observations=repair_validation_observations,
        repair_validation_observation_head=(
            repair_validation_observation_head
        ),
        reproduction_evidence_hashes=reproduction_evidence_hashes,
        authority_head=authority_head,
    )
    normalized_attempts = list(context["repair_attempts"])
    information_set_hash = str(context["information_set_hash"])
    trace, authority_facts = _dispatch_authoritative_facts(
        evidence=evidence,
        registry=registry,
        engineering_fixture=engineering_fixture,
        mission_id=mission_id,
        job_id=job_id,
        job_hash=job_hash,
        repair_id=repair_id,
        verification_kind="inventory",
        evidence_subject={"kind": "Repair", "id": repair_id},
        context=context,
        validation_plan_hash=receipt["check_plan_hash"],
        protocol=receipt["protocol"],
        result_artifact_hashes=tuple(receipt["result_artifact_hashes"]),
    )
    try:
        inventory = normalize_repair_inventory_facts(
            authority_facts,
            accepted_attempts=normalized_attempts,
            current_basis_hash=current_basis_hash,
            information_set_hash=information_set_hash,
            opened_result_artifact_hashes=tuple(
                receipt["result_artifact_hashes"]
            ),
        )
    except RepairDispositionInventoryError as exc:
        raise RepairValidationError(str(exc)) from exc
    body = {
        "receipt_hash": _digest(
            "Repair inventory validation receipt", receipt_hash
        ),
        "schema": INVENTORY_TRACE_SCHEMA,
        "validation": trace,
    }
    wrapper = {
        **body,
        "trace_sha256": sha256(canonical_bytes(body)).hexdigest(),
    }
    return wrapper, inventory


def validate_semantic_change_necessity(
    *,
    receipt_hash: str,
    mission_id: str,
    job_id: str,
    job_hash: str,
    repair_id: str | None,
    cause_hash: str,
    current_basis_hash: str,
    accepted_attempt_head_record_id: str | None,
    repair_validation_observation_head: Mapping[str, Any] | None,
    successor_scope: str,
    evidence: EvidenceStore,
    registry: EvidenceValidatorRegistry,
    engineering_fixture: bool,
) -> dict[str, Any]:
    """Dispatch one content-derived protected-semantic surface comparison."""

    receipt = parse_semantic_change_validation_receipt(
        evidence.read_verified(receipt_hash)
    )
    result_hashes = tuple(receipt["result_artifact_hashes"])
    _case_hash, case_document = _named_result_document(
        evidence=evidence,
        validation_plan_hash=receipt["check_plan_hash"],
        result_artifact_hashes=result_hashes,
        output_name="semantic_change_case",
        label="semantic-change necessity",
    )
    plan = _document(
        evidence.read_verified(receipt["check_plan_hash"]),
        label="semantic-change validation plan",
    )
    roles = dict(_artifact_roles(plan.get("artifact_roles")))
    expected_names = {
        "current_executable_manifest",
        "current_implementation_protocol",
        "current_job_spec",
        "semantic_change_case",
        "semantic_change_proposal",
        "semantic_change_successor",
    }
    if (
        set(roles) != expected_names
        or plan.get("validator_id") != receipt["validator_id"]
        or plan.get("protocol") != receipt["protocol"]
        or plan.get("verification_kind") != "semantic_change"
    ):
        raise RepairValidationError(
            "semantic-change validation roles or route differ"
        )
    try:
        current_spec = _document(
            evidence.read_verified(roles["current_job_spec"]),
            label="current semantic-change Job spec",
        )
        current_executable = _document(
            evidence.read_verified(roles["current_executable_manifest"]),
            label="current semantic-change Executable",
        )
        current_protocol = parse_canonical(
            evidence.read_verified(roles["current_implementation_protocol"])
        )
        proposal = _document(
            evidence.read_verified(roles["semantic_change_proposal"]),
            label="semantic-change proposal",
        )
        successor = _document(
            evidence.read_verified(roles["semantic_change_successor"]),
            label="semantic-change successor",
        )
        current_authority = case_document.get("current_authority")
        if not isinstance(current_authority, Mapping):
            raise RepairSemanticChangeAuthorityError(
                "semantic-change current authority is absent"
            )
        facts = semantic_change_facts(
            case_document,
            proposal=proposal,
            mission_id=str(current_authority.get("mission_id")),
            repair_id=str(current_authority.get("repair_id")),
            job_id=str(current_authority.get("job_id")),
            job_hash=str(current_authority.get("job_hash")),
            current_basis_hash=str(
                current_authority.get("current_basis_hash")
            ),
            accepted_attempt_head_record_id=current_authority.get(
                "accepted_attempt_head_record_id"
            ),
            repair_validation_observation_head=current_authority.get(
                "repair_validation_observation_head"
            ),
            current_executable_id=str(
                current_authority.get("executable_id")
            ),
            current_implementation_identity=str(
                current_authority.get("implementation_identity")
            ),
            current_job_spec=current_spec,
            current_executable_manifest=current_executable,
            current_implementation_protocol=str(current_protocol),
            proposed_successor_artifact=successor,
        )
    except (
        RepairSemanticChangeAuthorityError,
        TypeError,
        ValueError,
    ) as exc:
        raise RepairValidationError(str(exc)) from exc
    if (
        current_authority.get("mission_id") != mission_id
        or current_authority.get("repair_id") != repair_id
        or current_authority.get("job_id") != job_id
        or current_authority.get("job_hash") != job_hash
        or current_authority.get("current_basis_hash")
        != current_basis_hash
        or current_authority.get("accepted_attempt_head_record_id")
        != accepted_attempt_head_record_id
        or current_authority.get("repair_validation_observation_head")
        != (
            None
            if repair_validation_observation_head is None
            else dict(repair_validation_observation_head)
        )
        or successor.get("successor_scope") != successor_scope
    ):
        raise RepairValidationError(
            "semantic-change case names another current authority"
        )
    context = {
        "changed_surface_count": len(case_document["changed_surfaces"]),
        "current_authority": dict(current_authority),
        "current_surface_inventory_hash": case_document[
            "current_surface_inventory_hash"
        ],
        "proposal_sha256": roles["semantic_change_proposal"],
        "proposed_successor_artifact_sha256": roles[
            "semantic_change_successor"
        ],
        "proposed_surface_inventory_hash": case_document[
            "proposed_surface_inventory_hash"
        ],
        "schema": "engineering_semantic_change_context.v2",
        "scientific_semantics_changed": False,
        "successor_scope": successor_scope,
    }
    trace = _dispatch(
        evidence=evidence,
        registry=registry,
        engineering_fixture=engineering_fixture,
        mission_id=mission_id,
        job_id=job_id,
        job_hash=job_hash,
        repair_id=repair_id,
        verification_kind="semantic_change",
        evidence_subject={
            "kind": "Repair" if repair_id is not None else "Job",
            "id": repair_id if repair_id is not None else job_id,
        },
        context=context,
        validation_plan_hash=receipt["check_plan_hash"],
        protocol=receipt["protocol"],
        result_artifact_hashes=result_hashes,
        expected_facts=facts,
    )
    body = {
        "receipt_hash": receipt_hash,
        "schema": SEMANTIC_CHANGE_TRACE_SCHEMA,
        "validation": trace,
    }
    return {
        **body,
        "trace_sha256": sha256(canonical_bytes(body)).hexdigest(),
    }


def validate_engineering_disposition(
    *,
    disposition: EngineeringFailureDisposition,
    mission_id: str,
    job_hash: str,
    reproduction_evidence_hashes: Sequence[str],
    repair_attempts: Sequence[Mapping[str, Any]],
    repair_validation_observations: Sequence[Mapping[str, Any]],
    repair_validation_observation_head: Mapping[str, Any] | None,
    authority_head: Mapping[str, Any],
    evidence: EvidenceStore,
    registry: EvidenceValidatorRegistry,
    engineering_fixture: bool,
    prevalidated_inventory: tuple[
        Mapping[str, Any], Mapping[str, Any]
    ]
    | None = None,
    prevalidated_semantic_change: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one terminal derivation with each domain dispatch at most once.

    ``prevalidated_inventory`` and ``prevalidated_semantic_change`` are used by
    the two-phase materializer after it has released the stable-state lock.
    They are durable registered traces, not caller facts.  The fallback path
    performs the same registered dispatches for isolated fixture callers.
    """

    basis = _document(
        evidence.read_verified(disposition.basis_manifest_hash),
        label="engineering disposition basis",
    )
    observation_hash = _digest(
        "engineering disposition observation",
        basis.get("observation_manifest_hash"),
    )
    observation = _document(
        evidence.read_verified(observation_hash),
        label="engineering disposition observation",
    )
    result_hashes = observation.get("result_artifact_hashes")
    if not isinstance(result_hashes, list):
        raise RepairValidationError(
            "engineering disposition result artifact list is invalid"
        )
    normalized_attempts = [
        _canonical_mapping("engineering disposition Repair attempt", attempt)
        for attempt in repair_attempts
    ]
    normalized_observations = [
        _canonical_mapping(
            "engineering disposition Repair validation observation",
            observation,
        )
        for observation in repair_validation_observations
    ]
    normalized_observation_head = (
        None
        if repair_validation_observation_head is None
        else _canonical_mapping(
            "engineering disposition Repair validation observation head",
            repair_validation_observation_head,
        )
    )
    validation_plan_hash = _digest(
        "engineering disposition validation plan",
        observation.get("check_plan_hash"),
    )
    _result_hash, result_document = _named_result_document(
        evidence=evidence,
        validation_plan_hash=validation_plan_hash,
        result_artifact_hashes=tuple(result_hashes),
        output_name="validation_result",
        label="engineering disposition",
    )
    case_value = (
        result_document
        if result_document.get("schema") == REPAIR_DISPOSITION_CASE_SCHEMA
        else result_document.get("disposition_case")
    )
    try:
        disposition_case = normalize_repair_disposition_case(case_value)
    except (KeyError, RepairDispositionCaseError, TypeError) as exc:
        raise RepairValidationError(str(exc)) from exc
    current_basis_hash = (
        disposition.cause_hash
        if not normalized_attempts
        else _digest(
            "engineering disposition current Repair basis",
            normalized_attempts[-1].get("new_basis_hash"),
        )
    )
    accepted_attempt_head_record_id = (
        None
        if not normalized_attempts
        else _digest(
            "engineering disposition accepted attempt head",
            normalized_attempts[-1].get("repair_attempt_record_id"),
        )
    )
    if disposition.repair_id is None:
        raise RepairValidationError(
            "prospective engineering disposition requires an active Repair"
        )
    inventory_context = build_repair_inventory_validation_context(
        job_id=disposition.job_id,
        job_hash=job_hash,
        repair_id=str(disposition.repair_id),
        cause_hash=disposition.cause_hash,
        current_basis_hash=current_basis_hash,
        accepted_attempts=normalized_attempts,
        repair_validation_observations=normalized_observations,
        repair_validation_observation_head=normalized_observation_head,
        reproduction_evidence_hashes=reproduction_evidence_hashes,
        authority_head=authority_head,
    )
    if prevalidated_inventory is None:
        inventory_validation, inventory = validate_repair_inventory(
            receipt_hash=disposition_case[
                "inventory_validation_receipt_hash"
            ],
            mission_id=mission_id,
            job_id=disposition.job_id,
            job_hash=job_hash,
            repair_id=str(disposition.repair_id),
            cause_hash=disposition.cause_hash,
            current_basis_hash=current_basis_hash,
            accepted_attempts=normalized_attempts,
            repair_validation_observations=normalized_observations,
            repair_validation_observation_head=normalized_observation_head,
            reproduction_evidence_hashes=reproduction_evidence_hashes,
            authority_head=authority_head,
            evidence=evidence,
            registry=registry,
            engineering_fixture=engineering_fixture,
        )
    else:
        supplied_wrapper, supplied_inventory = prevalidated_inventory
        inventory_validation, inventory = (
            require_stored_repair_inventory_validation(
                value=supplied_wrapper,
                mission_id=mission_id,
                job_id=disposition.job_id,
                job_hash=job_hash,
                repair_id=str(disposition.repair_id),
                cause_hash=disposition.cause_hash,
                current_basis_hash=current_basis_hash,
                accepted_attempts=normalized_attempts,
                repair_validation_observations=normalized_observations,
                repair_validation_observation_head=(
                    normalized_observation_head
                ),
                reproduction_evidence_hashes=(
                    reproduction_evidence_hashes
                ),
                authority_head=authority_head,
                expected_scope=(
                    "fixture_only" if engineering_fixture else "production"
                ),
            )
        )
        if inventory != _canonical_mapping(
            "prevalidated Repair inventory", supplied_inventory
        ):
            raise RepairValidationError(
                "prevalidated Repair inventory differs from its trace"
            )
    if (
        inventory_validation.get("receipt_hash")
        != disposition_case["inventory_validation_receipt_hash"]
    ):
        raise RepairValidationError(
            "Repair inventory trace names another validation receipt"
        )
    semantic_receipt_hash = disposition_case[
        "semantic_change_receipt_hash"
    ]
    semantic_validation: dict[str, Any] | None = None
    if disposition.disposition == "requires_scientific_change":
        if not isinstance(semantic_receipt_hash, str) or not isinstance(
            disposition.successor_scope, str
        ):
            raise RepairValidationError(
                "scientific-change disposition lacks a separate proof route"
            )
        if prevalidated_semantic_change is None:
            semantic_validation = validate_semantic_change_necessity(
                receipt_hash=semantic_receipt_hash,
                mission_id=mission_id,
                job_id=disposition.job_id,
                job_hash=job_hash,
                repair_id=disposition.repair_id,
                cause_hash=disposition.cause_hash,
                current_basis_hash=current_basis_hash,
                accepted_attempt_head_record_id=(
                    accepted_attempt_head_record_id
                ),
                repair_validation_observation_head=(
                    normalized_observation_head
                ),
                successor_scope=disposition.successor_scope,
                evidence=evidence,
                registry=registry,
                engineering_fixture=engineering_fixture,
            )
        else:
            semantic_validation = _require_stored_semantic_change_validation(
                value=prevalidated_semantic_change,
                mission_id=mission_id,
                job_id=disposition.job_id,
                job_hash=job_hash,
                repair_id=disposition.repair_id,
                cause_hash=disposition.cause_hash,
                current_basis_hash=current_basis_hash,
                accepted_attempt_head_record_id=(
                    accepted_attempt_head_record_id
                ),
                repair_validation_observation_head=(
                    normalized_observation_head
                ),
                successor_scope=disposition.successor_scope,
                evidence=evidence,
                expected_scope=(
                    "fixture_only" if engineering_fixture else "production"
                ),
            )
        if semantic_validation.get("receipt_hash") != semantic_receipt_hash:
            raise RepairValidationError(
                "semantic-change trace names another validation receipt"
            )
    elif (
        semantic_receipt_hash is not None
        or prevalidated_semantic_change is not None
    ):
        raise RepairValidationError(
            "engineering-only disposition cannot carry semantic-change authority"
        )
    try:
        derived_disposition, derived_basis, expected_facts = (
            derive_repair_disposition(
                inventory,
                observation_count=len(normalized_observations),
                scientific_semantics_change_proven=(
                    semantic_validation is not None
                ),
            )
        )
    except RepairDispositionCaseError as exc:
        raise RepairValidationError(str(exc)) from exc
    basis_context = {
        "expected_value": basis.get("expected_value"),
        "remaining_changed_causes": basis.get("remaining_changed_causes"),
        "repairable_without_scientific_change": basis.get(
            "repairable_without_scientific_change"
        ),
        "scientific_semantics_change_required": basis.get(
            "scientific_semantics_change_required"
        ),
    }
    if (
        derived_disposition != disposition.disposition
        or derived_basis != basis_context
    ):
        raise RepairValidationError(
            "engineering disposition differs from its neutral cause inventory"
        )
    expected_facts = {
        **expected_facts,
        "inventory_facts": inventory,
        "inventory_validation_receipt_hash": disposition_case[
            "inventory_validation_receipt_hash"
        ],
    }
    context = {
        "accepted_attempt_head_record_id": accepted_attempt_head_record_id,
        "authority_head": _canonical_mapping(
            "engineering disposition authority head", authority_head
        ),
        "basis": basis_context,
        "cause_hash": disposition.cause_hash,
        "current_basis_hash": current_basis_hash,
        "disposition": disposition.disposition,
        "information_set_hash": inventory_context["information_set_hash"],
        "inventory_facts_artifact_hash": disposition_case[
            "inventory_facts_artifact_hash"
        ],
        "inventory_validation_receipt_hash": disposition_case[
            "inventory_validation_receipt_hash"
        ],
        "job_hash": job_hash,
        "job_id": disposition.job_id,
        "repair_attempts": normalized_attempts,
        "repair_id": disposition.repair_id,
        "repair_validation_observation_head": normalized_observation_head,
        "repair_validation_observations": normalized_observations,
        "reproduction_evidence_hashes": sorted(reproduction_evidence_hashes),
        "semantic_change_receipt_hash": semantic_receipt_hash,
        "scientific_semantics_changed": False,
        "successor_scope": disposition.successor_scope,
    }
    plan = _document(
        evidence.read_verified(validation_plan_hash),
        label="engineering disposition derivation plan",
    )
    plan_roles = _artifact_roles(plan.get("artifact_roles"))
    if (
        plan.get("schema") != PLAN_SCHEMA
        or plan.get("verification_kind") != "disposition"
        or plan.get("protocol") != DISPOSITION_DERIVATION_SCHEMA
        or tuple(sorted(identity for _name, identity in plan_roles))
        != tuple(result_hashes)
        or dict(plan_roles).get("validation_result") != _result_hash
        or observation.get("verification_method")
        != DISPOSITION_DERIVATION_SCHEMA
    ):
        raise RepairValidationError(
            "engineering disposition derivation plan is invalid"
        )
    derivation = {
        "context": context,
        "facts": expected_facts,
        "schema": DISPOSITION_DERIVATION_SCHEMA,
        "validation_plan_hash": validation_plan_hash,
    }
    body = {
        "basis_manifest_hash": disposition.basis_manifest_hash,
        "derivation": derivation,
        "observation_manifest_hash": observation_hash,
        "schema": DISPOSITION_TRACE_SCHEMA,
        "inventory_validation": inventory_validation,
        "semantic_change_validation": semantic_validation,
    }
    return {
        **body,
        "trace_sha256": sha256(canonical_bytes(body)).hexdigest(),
    }


def _trace_body(value: Mapping[str, Any]) -> dict[str, Any]:
    body = {key: _plain(child) for key, child in value.items() if key != "trace_sha256"}
    observed = _digest("Repair validation trace", value.get("trace_sha256"))
    if observed != sha256(canonical_bytes(body)).hexdigest():
        raise RepairValidationError("Repair validation trace digest is invalid")
    return body


def _stored_registered_trace(
    value: object,
    *,
    verification_kind: str,
    mission_id: str,
    protocol_context: Mapping[str, Any],
    evidence_subject: Mapping[str, str],
    expected_facts: Mapping[str, Any],
    expected_scope: str | None,
    expected_verdict: str = "passed",
) -> dict[str, Any]:
    trace = _canonical_mapping("stored registered Repair trace", value)
    required = {
        "authority_scope",
        "evidence_subject",
        "facts",
        "protocol",
        "registry_trace",
        "result_artifact_hashes",
        "schema",
        "validation_plan_hash",
        "verification_kind",
        "verdict",
    }
    if set(trace) != required or trace.get("schema") != TRACE_SCHEMA:
        raise RepairValidationError("stored registered Repair trace schema is invalid")
    scope = trace.get("authority_scope")
    if scope not in {"fixture_only", "production"} or (
        expected_scope is not None and scope != expected_scope
    ):
        raise RepairValidationError("stored Repair validator authority scope differs")
    subject = _canonical_mapping(
        "stored Repair evidence subject", trace.get("evidence_subject")
    )
    if subject != dict(evidence_subject):
        raise RepairValidationError("stored Repair evidence subject differs")
    protocol = _ascii("stored Repair validation protocol", trace.get("protocol"))
    result_hashes = trace.get("result_artifact_hashes")
    if (
        not isinstance(result_hashes, list)
        or not result_hashes
        or result_hashes != sorted(set(result_hashes))
    ):
        raise RepairValidationError("stored Repair result artifacts are invalid")
    normalized_results = tuple(
        _digest("stored Repair result artifact", item) for item in result_hashes
    )
    facts = _canonical_mapping("stored Repair validation facts", trace.get("facts"))
    binding = facts.get("binding")
    if not isinstance(binding, Mapping):
        raise RepairValidationError("stored Repair validation binding is absent")
    roles = _artifact_roles(binding.get("artifact_roles"))
    expected_binding = repair_validation_binding(
        verification_kind=verification_kind,
        mission_id=mission_id,
        protocol=protocol,
        context=protocol_context,
        artifact_roles=roles,
    )
    expected = {
        "binding": expected_binding,
        **_canonical_mapping("stored Repair expected facts", expected_facts),
    }
    registry_trace = trace.get("registry_trace")
    if (
        facts != expected
        or binding != expected_binding
        or tuple(sorted(identity for _name, identity in roles))
        != normalized_results
        or trace.get("verification_kind") != verification_kind
        or trace.get("verdict") != expected_verdict
        or not isinstance(registry_trace, Mapping)
        or set(registry_trace)
        != {
            "declared_artifact_count",
            "opened_artifact_count",
            "validator_id",
        }
        or registry_trace.get("declared_artifact_count") != len(roles) + 1
        or registry_trace.get("opened_artifact_count") != len(roles) + 1
    ):
        raise RepairValidationError("stored registered Repair trace is partial")
    _typed_digest(
        "stored Repair validator",
        registry_trace.get("validator_id"),
        "validator:",
    )
    _digest("stored Repair validation plan", trace.get("validation_plan_hash"))
    return trace


def require_stored_repair_attempt_validation(
    *,
    attempt_payload: Mapping[str, Any],
    repair_validation: object,
    mission_id: str,
    expected_scope: str | None = None,
) -> dict[str, Any]:
    """Purely rebind a durable attempt trace without rerunning its validator."""

    attempt = _canonical_mapping("stored Repair attempt", attempt_payload)
    repair_id = _typed_digest("stored Repair id", attempt.get("repair_id"), "repair:")
    job_id = _typed_digest("stored Repair Job", attempt.get("job_id"), "job:")
    outcome = attempt.get("outcome")
    if outcome not in {"failed", "repaired"}:
        raise RepairValidationError("stored Repair attempt outcome is invalid")
    context = build_repair_attempt_validation_context(
        cause_hash=_digest("stored Repair cause", attempt.get("cause_hash")),
        changed_dimension=_ascii(
            "stored Repair changed dimension", attempt.get("changed_dimension")
        ),
        explanation=_ascii("stored Repair explanation", attempt.get("explanation")),
        failure_observation=attempt.get("failure_observation"),
        implementation_proof_hash=attempt.get("implementation_proof_hash"),
        job_hash=_digest("stored Repair Job hash", attempt.get("job_hash")),
        job_id=job_id,
        new_basis_hash=_digest("stored Repair new basis", attempt.get("new_basis_hash")),
        new_evidence_hashes=tuple(attempt.get("new_evidence_hashes", ())),
        outcome=str(outcome),
        previous_basis_hash=_digest(
            "stored Repair previous basis", attempt.get("previous_basis_hash")
        ),
        prior_attempt_record_id=attempt.get("prior_attempt_record_id"),
        repair_id=repair_id,
        reproduction_evidence_hashes=tuple(
            attempt.get("reproduction_evidence_hashes", ())
        ),
        resume_action=_ascii(
            "stored Repair resume action", attempt.get("resume_action")
        ),
    )
    wrapper = _canonical_mapping("stored Repair attempt validation", repair_validation)
    if set(wrapper) != {
        "receipts",
        "schema",
        "trace_sha256",
        "verification_count",
    } or wrapper.get("schema") != ATTEMPT_TRACE_SCHEMA:
        raise RepairValidationError("stored Repair attempt validation schema is invalid")
    body = _trace_body(wrapper)
    receipts = wrapper.get("receipts")
    expected_receipts = attempt.get("verification_evidence_hashes")
    if (
        not isinstance(receipts, list)
        or not isinstance(expected_receipts, list)
        or expected_receipts != sorted(set(expected_receipts))
        or wrapper.get("verification_count") != len(receipts)
        or len(receipts) != len(expected_receipts)
        or body.get("verification_count") != len(receipts)
    ):
        raise RepairValidationError("stored Repair attempt trace count differs")
    dispatches: set[tuple[object, ...]] = set()
    normalized: list[dict[str, Any]] = []
    for expected_receipt, item in zip(expected_receipts, receipts, strict=True):
        receipt = _canonical_mapping("stored Repair receipt trace", item)
        if set(receipt) != {
            "authority_scope",
            "evidence_subject",
            "facts",
            "protocol",
            "receipt_hash",
            "registry_trace",
            "result_artifact_hashes",
            "schema",
            "validation_plan_hash",
            "verification_kind",
            "verdict",
        } or receipt.get("receipt_hash") != _digest(
            "stored Repair verification receipt", expected_receipt
        ):
            raise RepairValidationError("stored Repair receipt trace is invalid")
        trace = _stored_registered_trace(
            {key: value for key, value in receipt.items() if key != "receipt_hash"},
            verification_kind="attempt",
            mission_id=mission_id,
            protocol_context=context,
            evidence_subject={"kind": "Repair", "id": repair_id},
            expected_facts={
                "cause_resolved": outcome == "repaired",
                "failure_reproduced": outcome == "failed",
                "material_change": True,
            },
            expected_scope=expected_scope,
        )
        registry = trace["registry_trace"]
        dispatch = (
            registry["validator_id"],
            trace["protocol"],
            trace["validation_plan_hash"],
            tuple(trace["result_artifact_hashes"]),
        )
        if dispatch in dispatches:
            raise RepairValidationError("duplicate Repair validator dispatch is forbidden")
        dispatches.add(dispatch)
        normalized.append(receipt)
    if not normalized:
        raise RepairValidationError("stored Repair attempt has no registered validation")
    return wrapper


def require_stored_repair_candidate_validation(
    *,
    candidate: RepairCandidate,
    repair_validation: object,
    mission_id: str,
    evidence: EvidenceStore | None = None,
    expected_scope: str | None = None,
) -> dict[str, Any]:
    """Purely rebind a stored candidate evaluation without redispatch."""

    wrapper = _canonical_mapping(
        "stored Repair candidate validation", repair_validation
    )
    if set(wrapper) != {
        "evaluation",
        "receipt_hash",
        "registered_trace",
        "registered_trace_hash",
        "schema",
        "trace_sha256",
    } or wrapper.get("schema") != CANDIDATE_TRACE_SCHEMA:
        raise RepairValidationError(
            "stored Repair candidate validation schema is invalid"
        )
    _trace_body(wrapper)
    if wrapper.get("receipt_hash") != candidate.verification_evidence_hashes[0]:
        raise RepairValidationError(
            "stored Repair candidate receipt differs"
        )
    registered = _canonical_mapping(
        "stored Repair candidate registered trace",
        wrapper.get("registered_trace"),
    )
    registered_hash = _digest(
        "stored Repair candidate registered trace hash",
        wrapper.get("registered_trace_hash"),
    )
    if sha256(canonical_bytes(registered)).hexdigest() != registered_hash:
        raise RepairValidationError(
            "stored Repair candidate registered trace hash differs"
        )
    registry = registered.get("registry_trace")
    if not isinstance(registry, Mapping):
        raise RepairValidationError(
            "stored Repair candidate registry trace is absent"
        )
    validator_id = _typed_digest(
        "stored Repair candidate validator",
        registry.get("validator_id"),
        "validator:",
    )
    validation_plan_hash = _digest(
        "stored Repair candidate validation plan",
        registered.get("validation_plan_hash"),
    )
    evaluation_value = _canonical_mapping(
        "stored Repair candidate evaluation", wrapper.get("evaluation")
    )
    try:
        evaluation = parse_repair_evaluation(
            canonical_bytes(evaluation_value),
            candidate_hash=candidate.sha256,
            validator_id=validator_id,
            validation_plan_hash=validation_plan_hash,
            registry_trace_hash=registered_hash,
            read_evidence=(
                None if evidence is None else evidence.read_verified
            ),
        )
    except RepairCandidateError as exc:
        raise RepairValidationError(str(exc)) from exc
    expected_verdict = {
        "failure_reproduced": "passed",
        "invalid_change": "failed",
        "new_failure": "passed",
        "not_evaluable": "not_evaluable",
        "repaired": "passed",
    }.get(evaluation.mode)
    trace = _stored_registered_trace(
        registered,
        verification_kind="candidate",
        mission_id=mission_id,
        protocol_context=repair_candidate_validation_context(candidate),
        evidence_subject={"kind": "Repair", "id": candidate.repair_id},
        expected_facts={
            "cause_resolved": evaluation.cause_resolved,
            "failure_reproduced": evaluation.failure_reproduced,
            "material_change": evaluation.material_change,
            "mode": evaluation.mode,
            "new_failure_manifest_hash": (
                evaluation.new_failure_manifest_hash
            ),
            "reason_code": evaluation.reason_code,
        },
        expected_scope=expected_scope,
        expected_verdict=str(expected_verdict),
    )
    if trace != registered:
        raise RepairValidationError(
            "stored Repair candidate trace is not canonical"
        )
    return wrapper


def require_stored_accepted_repair_candidate_attempt(
    *,
    attempt_payload: Mapping[str, Any],
    mission_id: str,
    expected_scope: str | None = None,
    evidence: EvidenceStore | None = None,
    expected_prior_validation_observation_head: (
        Mapping[str, Any] | None | object
    ) = _OBSERVATION_BINDING_UNBOUND,
    expected_bound_validation_observations: (
        Sequence[Mapping[str, Any]] | object
    ) = _OBSERVATION_BINDING_UNBOUND,
) -> tuple[RepairCandidate, dict[str, Any]]:
    """Rebind one Writer-derived accepted candidate attempt and its trace.

    Projection and replay admission share this boundary so neither may invent
    a second interpretation of the flat compatibility fields persisted beside
    the outcome-free candidate.
    """

    attempt = _canonical_mapping("stored Repair candidate attempt", attempt_payload)
    candidate_value = attempt.get("repair_candidate")
    if not isinstance(candidate_value, Mapping):
        raise RepairValidationError("stored Repair candidate payload is absent")
    observation_expectations: dict[str, Any] = {}
    if (
        expected_prior_validation_observation_head
        is not _OBSERVATION_BINDING_UNBOUND
        or expected_bound_validation_observations
        is not _OBSERVATION_BINDING_UNBOUND
    ):
        if (
            expected_prior_validation_observation_head
            is _OBSERVATION_BINDING_UNBOUND
            or expected_bound_validation_observations
            is _OBSERVATION_BINDING_UNBOUND
        ):
            raise RepairValidationError(
                "stored Repair candidate observation head and inventory must "
                "be checked together"
            )
        observation_expectations = {
            "expected_prior_validation_observation_head": (
                expected_prior_validation_observation_head
            ),
            "expected_bound_validation_observations": (
                expected_bound_validation_observations
            ),
        }
    try:
        candidate = parse_repair_candidate(
            canonical_bytes(dict(candidate_value)),
            repair_id=str(attempt.get("repair_id")),
            job_id=str(attempt.get("job_id")),
            job_hash=str(attempt.get("job_hash")),
            cause_hash=str(attempt.get("cause_hash")),
            previous_basis_hash=str(attempt.get("previous_basis_hash")),
            prior_attempt_record_id=attempt.get("prior_attempt_record_id"),
            reproduction_evidence_hashes=attempt.get(
                "reproduction_evidence_hashes", ()
            ),
            resume_action=str(attempt.get("resume_action")),
            **observation_expectations,
        )
    except (RepairCandidateError, TypeError, ValueError) as exc:
        raise RepairValidationError(
            "stored Repair candidate payload is malformed"
        ) from exc
    repair_validation = attempt.get("repair_validation")
    evaluation = attempt.get("repair_evaluation")
    stored_evaluation = (
        None
        if not isinstance(repair_validation, Mapping)
        else repair_validation.get("evaluation")
    )
    expected_outcome = (
        "repaired"
        if isinstance(evaluation, Mapping)
        and evaluation.get("mode") == "repaired"
        else "failed"
    )
    if (
        attempt.get("repair_candidate_hash") != candidate.sha256
        or attempt.get("attempt_proof_hash") != candidate.sha256
        or evaluation != stored_evaluation
        or not isinstance(evaluation, Mapping)
        or evaluation.get("mode") not in {"failure_reproduced", "repaired"}
        or attempt.get("outcome") != expected_outcome
        or attempt.get("failure_observation")
        != (
            None
            if expected_outcome == "repaired"
            else "registered_original_failure_reproduced"
        )
        or any(
            attempt.get(key) != candidate.payload().get(key)
            for key in _CANDIDATE_FLAT_COMPATIBILITY_FIELDS
        )
    ):
        raise RepairValidationError(
            "stored Repair candidate differs from its derived attempt"
        )
    stored = require_stored_repair_candidate_validation(
        candidate=candidate,
        repair_validation=repair_validation,
        mission_id=mission_id,
        evidence=evidence,
        expected_scope=expected_scope,
    )
    return candidate, stored


def repair_validation_capabilities(
    repair_validation: Mapping[str, Any],
) -> tuple[tuple[str, str], ...]:
    """Return the immutable validator capabilities used by one checked trace."""

    wrapper = _canonical_mapping("Repair validation capability trace", repair_validation)
    if wrapper.get("schema") == CANDIDATE_TRACE_SCHEMA:
        registered = wrapper.get("registered_trace")
        registry = (
            None
            if not isinstance(registered, Mapping)
            else registered.get("registry_trace")
        )
        if not isinstance(registered, Mapping) or not isinstance(
            registry, Mapping
        ):
            raise RepairValidationError(
                "Repair candidate validation capability is absent"
            )
        return (
            (
                _ascii(
                    "Repair validation protocol", registered.get("protocol")
                ),
                _typed_digest(
                    "Repair validation validator",
                    registry.get("validator_id"),
                    "validator:",
                ),
            ),
        )
    receipts = wrapper.get("receipts")
    if not isinstance(receipts, list) or not receipts:
        raise RepairValidationError("Repair validation capabilities are absent")
    capabilities: list[tuple[str, str]] = []
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            raise RepairValidationError("Repair validation capability is invalid")
        registry = receipt.get("registry_trace")
        if not isinstance(registry, Mapping):
            raise RepairValidationError("Repair validator registry trace is absent")
        capabilities.append(
            (
                _ascii("Repair validation protocol", receipt.get("protocol")),
                _typed_digest(
                    "Repair validation validator",
                    registry.get("validator_id"),
                    "validator:",
                ),
            )
        )
    normalized = tuple(sorted(set(capabilities)))
    if len(normalized) != len(capabilities):
        raise RepairValidationError("Repair validation capability is duplicated")
    return normalized


def require_stored_repair_inventory_validation(
    *,
    value: object,
    mission_id: str,
    job_id: str,
    job_hash: str,
    repair_id: str,
    cause_hash: str,
    current_basis_hash: str,
    accepted_attempts: Sequence[Mapping[str, Any]],
    repair_validation_observations: Sequence[Mapping[str, Any]],
    repair_validation_observation_head: Mapping[str, Any] | None,
    reproduction_evidence_hashes: Sequence[str],
    authority_head: Mapping[str, Any],
    expected_scope: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebind one stored domain inventory trace without validator execution."""

    expected_context = build_repair_inventory_validation_context(
        job_id=job_id,
        job_hash=job_hash,
        repair_id=repair_id,
        cause_hash=cause_hash,
        current_basis_hash=current_basis_hash,
        accepted_attempts=accepted_attempts,
        repair_validation_observations=repair_validation_observations,
        repair_validation_observation_head=(
            repair_validation_observation_head
        ),
        reproduction_evidence_hashes=reproduction_evidence_hashes,
        authority_head=authority_head,
    )
    normalized_attempts = list(expected_context["repair_attempts"])
    information_set_hash = str(expected_context["information_set_hash"])
    wrapper = _canonical_mapping("stored Repair inventory validation", value)
    if set(wrapper) != {
        "receipt_hash",
        "schema",
        "trace_sha256",
        "validation",
    } or wrapper.get("schema") != INVENTORY_TRACE_SCHEMA:
        raise RepairValidationError(
            "stored Repair inventory validation schema is invalid"
        )
    _trace_body(wrapper)
    _digest("stored Repair inventory receipt", wrapper.get("receipt_hash"))
    trace_value = wrapper.get("validation")
    if not isinstance(trace_value, Mapping):
        raise RepairValidationError("stored Repair inventory trace is absent")
    facts = trace_value.get("facts")
    binding = None if not isinstance(facts, Mapping) else facts.get("binding")
    context = None if not isinstance(binding, Mapping) else binding.get("context")
    if not isinstance(context, Mapping):
        raise RepairValidationError("stored Repair inventory context is absent")
    if dict(context) != expected_context:
        raise RepairValidationError(
            "stored Repair inventory validation names another authority head"
        )
    authority_facts = {
        key: child for key, child in facts.items() if key != "binding"
    }
    result_hashes = trace_value.get("result_artifact_hashes")
    if not isinstance(result_hashes, list):
        raise RepairValidationError(
            "stored Repair inventory result identities are absent"
        )
    try:
        inventory = normalize_repair_inventory_facts(
            authority_facts,
            accepted_attempts=normalized_attempts,
            current_basis_hash=current_basis_hash,
            information_set_hash=information_set_hash,
            opened_result_artifact_hashes=result_hashes,
        )
    except RepairDispositionInventoryError as exc:
        raise RepairValidationError(str(exc)) from exc
    trace = _stored_registered_trace(
        trace_value,
        verification_kind="inventory",
        mission_id=mission_id,
        protocol_context=expected_context,
        evidence_subject={"kind": "Repair", "id": repair_id},
        expected_facts=inventory,
        expected_scope=expected_scope,
    )
    if trace != trace_value:
        raise RepairValidationError(
            "stored Repair inventory trace is not canonical"
        )
    return wrapper, inventory


def _require_stored_semantic_change_validation(
    *,
    value: object,
    mission_id: str,
    job_id: str,
    job_hash: str,
    repair_id: str | None,
    cause_hash: str,
    current_basis_hash: str,
    accepted_attempt_head_record_id: str | None,
    repair_validation_observation_head: Mapping[str, Any] | None,
    successor_scope: str,
    evidence: EvidenceStore,
    expected_scope: str | None,
) -> dict[str, Any]:
    wrapper = _canonical_mapping(
        "stored semantic-change validation", value
    )
    if set(wrapper) != {
        "receipt_hash",
        "schema",
        "trace_sha256",
        "validation",
    } or wrapper.get("schema") != SEMANTIC_CHANGE_TRACE_SCHEMA:
        raise RepairValidationError(
            "stored semantic-change validation schema is invalid"
        )
    _trace_body(wrapper)
    receipt_hash = _digest(
        "stored semantic-change receipt", wrapper.get("receipt_hash")
    )
    receipt = parse_semantic_change_validation_receipt(
        evidence.read_verified(receipt_hash)
    )
    plan = _document(
        evidence.read_verified(receipt["check_plan_hash"]),
        label="stored semantic-change validation plan",
    )
    roles = dict(_artifact_roles(plan.get("artifact_roles")))
    if (
        set(roles)
        != {
            "current_executable_manifest",
            "current_implementation_protocol",
            "current_job_spec",
            "semantic_change_case",
            "semantic_change_proposal",
            "semantic_change_successor",
        }
        or set(roles.values()) != set(receipt["result_artifact_hashes"])
    ):
        raise RepairValidationError(
            "stored semantic-change artifact roles are incomplete"
        )
    trace_value = wrapper.get("validation")
    facts = None if not isinstance(trace_value, Mapping) else trace_value.get(
        "facts"
    )
    binding = None if not isinstance(facts, Mapping) else facts.get("binding")
    context = None if not isinstance(binding, Mapping) else binding.get(
        "context"
    )
    if not isinstance(context, Mapping):
        raise RepairValidationError(
            "stored semantic-change context is absent"
        )
    try:
        current_spec = _document(
            evidence.read_verified(roles["current_job_spec"]),
            label="stored current semantic-change Job spec",
        )
        current_executable = _document(
            evidence.read_verified(roles["current_executable_manifest"]),
            label="stored current semantic-change Executable",
        )
        current_protocol = parse_canonical(
            evidence.read_verified(roles["current_implementation_protocol"])
        )
        proposal = _document(
            evidence.read_verified(roles["semantic_change_proposal"]),
            label="stored semantic-change proposal",
        )
        semantic_case = _document(
            evidence.read_verified(roles["semantic_change_case"]),
            label="stored semantic-change case",
        )
        successor = _document(
            evidence.read_verified(roles["semantic_change_successor"]),
            label="stored semantic-change successor",
        )
        current_authority = semantic_case.get("current_authority")
        if not isinstance(current_authority, Mapping):
            raise RepairSemanticChangeAuthorityError(
                "stored semantic-change current authority is absent"
            )
        expected_facts = semantic_change_facts(
            semantic_case,
            proposal=proposal,
            mission_id=str(current_authority.get("mission_id")),
            repair_id=str(current_authority.get("repair_id")),
            job_id=str(current_authority.get("job_id")),
            job_hash=str(current_authority.get("job_hash")),
            current_basis_hash=str(
                current_authority.get("current_basis_hash")
            ),
            accepted_attempt_head_record_id=current_authority.get(
                "accepted_attempt_head_record_id"
            ),
            repair_validation_observation_head=current_authority.get(
                "repair_validation_observation_head"
            ),
            current_executable_id=str(
                current_authority.get("executable_id")
            ),
            current_implementation_identity=str(
                current_authority.get("implementation_identity")
            ),
            current_job_spec=current_spec,
            current_executable_manifest=current_executable,
            current_implementation_protocol=str(current_protocol),
            proposed_successor_artifact=successor,
        )
    except (
        RepairSemanticChangeAuthorityError,
        TypeError,
        ValueError,
    ) as exc:
        raise RepairValidationError(str(exc)) from exc
    expected_context = {
        "changed_surface_count": len(semantic_case["changed_surfaces"]),
        "current_authority": dict(current_authority),
        "current_surface_inventory_hash": semantic_case[
            "current_surface_inventory_hash"
        ],
        "proposal_sha256": roles["semantic_change_proposal"],
        "proposed_successor_artifact_sha256": roles[
            "semantic_change_successor"
        ],
        "proposed_surface_inventory_hash": semantic_case[
            "proposed_surface_inventory_hash"
        ],
        "schema": "engineering_semantic_change_context.v2",
        "scientific_semantics_changed": False,
        "successor_scope": successor_scope,
    }
    if (
        repair_id is None
        or current_authority.get("mission_id") != mission_id
        or current_authority.get("repair_id") != repair_id
        or current_authority.get("job_id") != job_id
        or current_authority.get("job_hash") != job_hash
        or current_authority.get("current_basis_hash")
        != current_basis_hash
        or current_authority.get("accepted_attempt_head_record_id")
        != accepted_attempt_head_record_id
        or current_authority.get("repair_validation_observation_head")
        != (
            None
            if repair_validation_observation_head is None
            else dict(repair_validation_observation_head)
        )
        or successor.get("successor_scope") != successor_scope
        or dict(context) != expected_context
    ):
        raise RepairValidationError(
            "stored semantic-change validation names another authority head"
        )
    trace = _stored_registered_trace(
        trace_value,
        verification_kind="semantic_change",
        mission_id=mission_id,
        protocol_context=expected_context,
        evidence_subject={
            "kind": "Repair" if repair_id is not None else "Job",
            "id": repair_id if repair_id is not None else job_id,
        },
        expected_facts=expected_facts,
        expected_scope=expected_scope,
    )
    if trace != trace_value:
        raise RepairValidationError(
            "stored semantic-change trace is not canonical"
        )
    return wrapper


def require_stored_engineering_disposition_validation(
    *,
    disposition_payload: Mapping[str, Any],
    disposition_validation: object,
    mission_id: str,
    job_hash: str,
    reproduction_evidence_hashes: Sequence[str],
    repair_attempts: Sequence[Mapping[str, Any]],
    repair_validation_observations: Sequence[Mapping[str, Any]],
    repair_validation_observation_head: Mapping[str, Any] | None,
    evidence: EvidenceStore,
    expected_scope: str | None = None,
) -> dict[str, Any]:
    """Purely rebind a durable disposition trace without validator dispatch."""

    disposition = _canonical_mapping("stored engineering disposition", disposition_payload)
    job_id = _typed_digest("stored disposition Job", disposition.get("job_id"), "job:")
    repair_id_value = disposition.get("repair_id")
    repair_id = (
        None
        if repair_id_value is None
        else _typed_digest("stored disposition Repair", repair_id_value, "repair:")
    )
    normalized_attempts = [
        _canonical_mapping("stored disposition Repair attempt", item)
        for item in repair_attempts
    ]
    normalized_observations = [
        _canonical_mapping(
            "stored disposition Repair validation observation", item
        )
        for item in repair_validation_observations
    ]
    normalized_observation_head = (
        None
        if repair_validation_observation_head is None
        else _canonical_mapping(
            "stored disposition Repair validation observation head",
            repair_validation_observation_head,
        )
    )
    wrapper = _canonical_mapping(
        "stored engineering disposition validation", disposition_validation
    )
    if set(wrapper) != {
        "basis_manifest_hash",
        "derivation",
        "inventory_validation",
        "observation_manifest_hash",
        "schema",
        "semantic_change_validation",
        "trace_sha256",
    } or wrapper.get("schema") != DISPOSITION_TRACE_SCHEMA:
        raise RepairValidationError("stored disposition validation schema is invalid")
    _trace_body(wrapper)
    basis_hash = _digest(
        "stored disposition basis", disposition.get("basis_manifest_hash")
    )
    if wrapper.get("basis_manifest_hash") != basis_hash:
        raise RepairValidationError("stored disposition basis differs")
    derivation = wrapper.get("derivation")
    if (
        not isinstance(derivation, Mapping)
        or set(derivation)
        != {"context", "facts", "schema", "validation_plan_hash"}
        or derivation.get("schema") != DISPOSITION_DERIVATION_SCHEMA
    ):
        raise RepairValidationError("stored disposition derivation is absent")
    context = derivation.get("context")
    basis_context = None if not isinstance(context, Mapping) else context.get("basis")
    if not isinstance(basis_context, Mapping):
        raise RepairValidationError("stored disposition basis context is absent")
    assert isinstance(context, Mapping)
    stored_authority_head = context.get("authority_head")
    if not isinstance(stored_authority_head, Mapping):
        raise RepairValidationError(
            "stored disposition authority head is absent"
        )
    current_basis_hash = (
        _digest("stored disposition cause", disposition.get("cause_hash"))
        if not normalized_attempts
        else _digest(
            "stored disposition current basis",
            normalized_attempts[-1].get("new_basis_hash"),
        )
    )
    accepted_attempt_head_record_id = (
        None
        if not normalized_attempts
        else _digest(
            "stored disposition accepted attempt head",
            normalized_attempts[-1].get("repair_attempt_record_id"),
        )
    )
    if repair_id is None:
        raise RepairValidationError(
            "stored prospective disposition lacks active Repair authority"
        )
    inventory_context = build_repair_inventory_validation_context(
        job_id=job_id,
        job_hash=job_hash,
        repair_id=repair_id,
        cause_hash=_digest(
            "stored disposition cause", disposition.get("cause_hash")
        ),
        current_basis_hash=current_basis_hash,
        accepted_attempts=normalized_attempts,
        repair_validation_observations=normalized_observations,
        repair_validation_observation_head=normalized_observation_head,
        reproduction_evidence_hashes=reproduction_evidence_hashes,
        authority_head=stored_authority_head,
    )
    semantic_receipt_hash = context.get("semantic_change_receipt_hash")
    try:
        disposition_case = normalize_repair_disposition_case(
            {
                "inventory_facts_artifact_hash": context.get(
                    "inventory_facts_artifact_hash"
                ),
                "inventory_validation_receipt_hash": context.get(
                    "inventory_validation_receipt_hash"
                ),
                "schema": REPAIR_DISPOSITION_CASE_SCHEMA,
                "semantic_change_receipt_hash": semantic_receipt_hash,
            }
        )
    except (KeyError, RepairDispositionCaseError, TypeError) as exc:
        raise RepairValidationError(str(exc)) from exc
    inventory_wrapper, inventory = require_stored_repair_inventory_validation(
        value=wrapper.get("inventory_validation"),
        mission_id=mission_id,
        job_id=job_id,
        job_hash=job_hash,
        repair_id=repair_id,
        cause_hash=_digest(
            "stored disposition cause", disposition.get("cause_hash")
        ),
        current_basis_hash=current_basis_hash,
        accepted_attempts=normalized_attempts,
        repair_validation_observations=normalized_observations,
        repair_validation_observation_head=normalized_observation_head,
        reproduction_evidence_hashes=reproduction_evidence_hashes,
        authority_head=stored_authority_head,
        expected_scope=expected_scope,
    )
    semantic_value = wrapper.get("semantic_change_validation")
    semantic_validation: dict[str, Any] | None = None
    if disposition.get("disposition") == "requires_scientific_change":
        if (
            not isinstance(semantic_receipt_hash, str)
            or not isinstance(disposition.get("successor_scope"), str)
        ):
            raise RepairValidationError(
                "stored scientific-change disposition lacks proof authority"
            )
        semantic_validation = _require_stored_semantic_change_validation(
            value=semantic_value,
            mission_id=mission_id,
            job_id=job_id,
            job_hash=job_hash,
            repair_id=repair_id,
            cause_hash=_digest(
                "stored disposition cause", disposition.get("cause_hash")
            ),
            current_basis_hash=current_basis_hash,
            accepted_attempt_head_record_id=accepted_attempt_head_record_id,
            repair_validation_observation_head=normalized_observation_head,
            successor_scope=str(disposition["successor_scope"]),
            evidence=evidence,
            expected_scope=expected_scope,
        )
    elif semantic_value is not None or semantic_receipt_hash is not None:
        raise RepairValidationError(
            "stored engineering-only disposition carries semantic authority"
        )
    try:
        derived_disposition, derived_basis, expected_facts = (
            derive_repair_disposition(
                inventory,
                observation_count=len(normalized_observations),
                scientific_semantics_change_proven=(
                    semantic_validation is not None
                ),
            )
        )
    except RepairDispositionCaseError as exc:
        raise RepairValidationError(str(exc)) from exc
    if (
        derived_disposition != disposition.get("disposition")
        or derived_basis != dict(basis_context)
    ):
        raise RepairValidationError(
            "stored disposition differs from its neutral cause inventory"
        )
    expected_facts = {
        **expected_facts,
        "inventory_facts": inventory,
        "inventory_validation_receipt_hash": disposition_case[
            "inventory_validation_receipt_hash"
        ],
    }
    expected_context = {
        "accepted_attempt_head_record_id": accepted_attempt_head_record_id,
        "authority_head": _canonical_mapping(
            "stored disposition authority head", stored_authority_head
        ),
        "basis": dict(basis_context),
        "cause_hash": disposition.get("cause_hash"),
        "current_basis_hash": current_basis_hash,
        "disposition": disposition.get("disposition"),
        "information_set_hash": inventory_context["information_set_hash"],
        "inventory_facts_artifact_hash": disposition_case[
            "inventory_facts_artifact_hash"
        ],
        "inventory_validation_receipt_hash": disposition_case[
            "inventory_validation_receipt_hash"
        ],
        "job_hash": job_hash,
        "job_id": job_id,
        "repair_attempts": normalized_attempts,
        "repair_id": repair_id,
        "repair_validation_observation_head": normalized_observation_head,
        "repair_validation_observations": normalized_observations,
        "reproduction_evidence_hashes": sorted(reproduction_evidence_hashes),
        "semantic_change_receipt_hash": semantic_receipt_hash,
        "scientific_semantics_changed": False,
        "successor_scope": disposition.get("successor_scope"),
    }
    if (
        dict(context) != expected_context
        or derivation.get("facts") != expected_facts
    ):
        raise RepairValidationError(
            "stored disposition derivation differs from registered facts"
        )
    validation_plan_hash = _digest(
        "stored disposition derivation plan",
        derivation.get("validation_plan_hash"),
    )
    basis_document = _document(
        evidence.read_verified(basis_hash),
        label="stored engineering disposition basis",
    )
    observation_hash = _digest(
        "stored disposition observation",
        basis_document.get("observation_manifest_hash"),
    )
    if wrapper.get("observation_manifest_hash") != observation_hash:
        raise RepairValidationError(
            "stored disposition observation differs from its basis"
        )
    observation = _document(
        evidence.read_verified(observation_hash),
        label="stored engineering disposition observation",
    )
    result_hashes = observation.get("result_artifact_hashes")
    plan = _document(
        evidence.read_verified(validation_plan_hash),
        label="stored engineering disposition derivation plan",
    )
    plan_roles = _artifact_roles(plan.get("artifact_roles"))
    roles = dict(plan_roles)
    if (
        not isinstance(result_hashes, list)
        or result_hashes != sorted(set(result_hashes))
        or plan.get("schema") != PLAN_SCHEMA
        or plan.get("verification_kind") != "disposition"
        or plan.get("protocol") != DISPOSITION_DERIVATION_SCHEMA
        or tuple(sorted(identity for _name, identity in plan_roles))
        != tuple(result_hashes)
        or observation.get("check_plan_hash") != validation_plan_hash
        or observation.get("verification_method")
        != DISPOSITION_DERIVATION_SCHEMA
        or roles.get("inventory_facts")
        != disposition_case["inventory_facts_artifact_hash"]
        or roles.get("inventory_validation_receipt")
        != disposition_case["inventory_validation_receipt_hash"]
    ):
        raise RepairValidationError(
            "stored disposition derivation evidence is invalid"
        )
    result_hash = roles.get("validation_result")
    if type(result_hash) is not str:
        raise RepairValidationError(
            "stored disposition case artifact is absent"
        )
    stored_case = normalize_repair_disposition_case(
        _document(
            evidence.read_verified(result_hash),
            label="stored engineering disposition case",
        )
    )
    stored_inventory = _document(
        evidence.read_verified(
            disposition_case["inventory_facts_artifact_hash"]
        ),
        label="stored engineering disposition inventory facts",
    )
    if stored_case != disposition_case or stored_inventory != inventory:
        raise RepairValidationError(
            "stored disposition artifacts differ from registered facts"
        )
    if inventory_wrapper != wrapper.get("inventory_validation"):
        raise RepairValidationError(
            "stored disposition inventory trace is not canonical"
        )
    return wrapper


__all__ = [
    "ATTEMPT_TRACE_SCHEMA",
    "BINDING_SCHEMA",
    "CANDIDATE_RECEIPT_SCHEMA",
    "CANDIDATE_TRACE_SCHEMA",
    "DISPOSITION_DERIVATION_SCHEMA",
    "DISPOSITION_TRACE_SCHEMA",
    "INVENTORY_RECEIPT_SCHEMA",
    "INVENTORY_TRACE_SCHEMA",
    "PLAN_SCHEMA",
    "REGISTERED_REPAIR_AUTHORITY_SCHEMA",
    "SEMANTIC_CHANGE_RECEIPT_SCHEMA",
    "SEMANTIC_CHANGE_TRACE_SCHEMA",
    "RepairValidationError",
    "RepairValidationUnavailableError",
    "build_repair_validation_plan",
    "build_repair_attempt_validation_context",
    "build_repair_candidate_validation_context",
    "build_repair_candidate_validation_receipt",
    "build_repair_inventory_authority_head",
    "build_repair_inventory_validation_context",
    "build_repair_inventory_validation_receipt",
    "build_semantic_change_validation_receipt",
    "repair_candidate_validation_context",
    "parse_repair_candidate_validation_receipt",
    "parse_repair_inventory_validation_receipt",
    "parse_semantic_change_validation_receipt",
    "repair_validation_binding",
    "repair_validation_capabilities",
    "require_stored_accepted_repair_candidate_attempt",
    "require_stored_engineering_disposition_validation",
    "require_stored_repair_inventory_validation",
    "require_stored_repair_candidate_validation",
    "require_stored_repair_attempt_validation",
    "validate_engineering_disposition",
    "validate_repair_inventory",
    "validate_repair_candidate",
    "validate_semantic_change_necessity",
]
