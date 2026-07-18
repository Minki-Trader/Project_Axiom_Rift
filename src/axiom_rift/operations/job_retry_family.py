"""Pure identity and evidence rules for post-completion Job retries.

The exact-work fingerprint remains useful for cache identity, but it cannot be
the only failed-attempt boundary: caller-supplied input hashes are part of that
fingerprint.  This module derives a coarser retry family from Writer-owned work
context and validates the one typed authority that may release a failed family
without changing scientific semantics.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axiom_rift.core.canonical import CanonicalJSONError, canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.validation import (
    EngineeringEvidenceValidationRequest,
    EvidenceValidationError,
    EvidenceValidatorRegistry,
    ValidationArtifact,
)


class JobRetryFamilyError(ValueError):
    """A retry family or its release authority is malformed or stale."""


RETRY_RESUME_AUTHORITY_SCHEMA = "job_retry_resume_authority.v1"
RETRY_RESUME_VERIFICATION_SCHEMA = "job_retry_resume_verification.v1"
RETRY_FAMILY_SCHEMA = "job_retry_family.v1"
RETRY_FAMILY_ATTEMPT_SCHEMA = "job_retry_family_attempt.v1"

_RESUME_CHANGED_DIMENSIONS = frozenset(
    {"cause", "information", "compute_budget"}
)
_RETRY_BASIS_DIMENSIONS = frozenset(
    {*_RESUME_CHANGED_DIMENSIONS, "implementation"}
)
_ENGINEERING_ONLY_DISPOSITIONS = frozenset(
    {
        "repair_exhausted_changed_causes",
        "repair_infeasible",
        "repair_nonpositive_expected_value",
    }
)
EvidenceReader = Callable[[str], bytes]
EvidenceVerifier = Callable[[str], object]
EvidencePathResolver = Callable[[str], Path]


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise JobRetryFamilyError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise JobRetryFamilyError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


def _typed_id(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    if not text.startswith(prefix):
        raise JobRetryFamilyError(f"{name} has an invalid prefix")
    _digest(name, text.removeprefix(prefix))
    return text


def _optional_ascii(name: str, value: object) -> str | None:
    if value is None:
        return None
    return _ascii(name, value)


def _digest_list(
    name: str,
    value: object,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(type(item) is not str for item in value)
        or value != sorted(set(value))
    ):
        raise JobRetryFamilyError(
            f"{name} must be a sorted unique digest list"
        )
    return tuple(_digest(name, item) for item in value)


def _document(content: bytes, *, name: str) -> dict[str, Any]:
    try:
        value = parse_canonical(content)
    except (CanonicalJSONError, TypeError, ValueError) as exc:
        raise JobRetryFamilyError(f"{name} is not canonical evidence") from exc
    if not isinstance(value, dict):
        raise JobRetryFamilyError(f"{name} must be an object")
    return dict(value)


def _plain_canonical(value: object) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _plain_canonical(child) for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain_canonical(child) for child in value]
    return value


def evidence_schema(content: bytes) -> str | None:
    """Return a canonical evidence schema without accepting malformed bytes."""

    return _document(content, name="Job retry evidence").get("schema")


def _binding_target(spec: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    component = spec.get("component_parity_binding")
    if isinstance(component, Mapping):
        return (
            "component_parity",
            {
                "canonical_component_id": component.get(
                    "canonical_component_id"
                ),
                "equivalent_component_id": component.get(
                    "equivalent_component_id"
                ),
                "portfolio_decision_id": component.get(
                    "portfolio_decision_id"
                ),
            },
        )
    external = spec.get("external_dependency_binding")
    if isinstance(external, Mapping):
        return (
            "external_dependency",
            {
                "dependency_id": external.get("dependency_id"),
                "recovery_path_id": external.get("recovery_path_id"),
                "recovery_plan_id": external.get("recovery_plan_id"),
            },
        )
    source = spec.get("source_binding")
    if isinstance(source, Mapping):
        return (
            "source",
            {
                "source_contract_id": source.get("source_contract_id"),
                "transition_evidence": source.get("transition_evidence"),
            },
        )
    runtime = spec.get("runtime_binding")
    if isinstance(runtime, Mapping):
        return (
            "runtime",
            {"evidence_depth": runtime.get("evidence_depth")},
        )
    scientific = spec.get("scientific_binding")
    if isinstance(scientific, Mapping):
        holdout = spec.get("holdout_binding")
        return (
            "scientific",
            {
                "evidence_depth": scientific.get("evidence_depth"),
                "holdout_id": (
                    holdout.get("holdout_id")
                    if isinstance(holdout, Mapping)
                    else None
                ),
            },
        )
    return (
        "generic",
        {"callable_identity": spec.get("callable_identity")},
    )


@dataclass(frozen=True, slots=True)
class JobRetryFamily:
    mission_id: str
    initiative_id: str | None
    study_id: str | None
    batch_id: str | None
    evidence_subject: Mapping[str, str]
    lane: str
    target: Mapping[str, Any]

    def __post_init__(self) -> None:
        _ascii("retry family Mission", self.mission_id)
        for name in (
            "initiative_id",
            "study_id",
            "batch_id",
        ):
            _optional_ascii(f"retry family {name}", getattr(self, name))
        if (
            not isinstance(self.evidence_subject, Mapping)
            or set(self.evidence_subject) != {"kind", "id"}
        ):
            raise JobRetryFamilyError("retry family evidence subject is invalid")
        _ascii("retry family subject kind", self.evidence_subject.get("kind"))
        _ascii("retry family subject id", self.evidence_subject.get("id"))
        if self.lane not in {
            "component_parity",
            "external_dependency",
            "generic",
            "runtime",
            "scientific",
            "source",
        }:
            raise JobRetryFamilyError("retry family lane is invalid")
        canonical_bytes(dict(self.target))

    def payload(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "evidence_subject": dict(self.evidence_subject),
            "initiative_id": self.initiative_id,
            "lane": self.lane,
            "mission_id": self.mission_id,
            "schema": RETRY_FAMILY_SCHEMA,
            "study_id": self.study_id,
            "target": dict(self.target),
        }

    @property
    def fingerprint(self) -> str:
        return canonical_digest(
            domain="job-retry-family",
            payload=self.payload(),
        )

    @property
    def stream(self) -> str:
        return f"job-retry-family:{self.fingerprint}"


def derive_job_retry_family(
    *,
    mission_id: str,
    initiative_id: str | None,
    study_id: str | None,
    batch_id: str | None,
    spec: Mapping[str, Any],
) -> JobRetryFamily:
    """Derive a family without caller-controlled loose input hashes."""

    evidence_subject = spec.get("evidence_subject")
    if not isinstance(evidence_subject, Mapping):
        raise JobRetryFamilyError("Job retry family lacks an evidence subject")
    lane, target = _binding_target(spec)
    return JobRetryFamily(
        mission_id=mission_id,
        initiative_id=initiative_id,
        study_id=study_id,
        batch_id=batch_id,
        evidence_subject=dict(evidence_subject),
        lane=lane,
        target=target,
    )


def retry_family_attempt_payload(
    *,
    family: JobRetryFamily,
    phase: str,
    job_id: str,
    job_hash: str,
    work_fingerprint: str,
    retry_basis_record_ids: Sequence[str] = (),
    completion_record_id: str | None = None,
) -> dict[str, Any]:
    if phase not in {"declared", "success", "failed", "not_evaluable"}:
        raise JobRetryFamilyError("retry family attempt phase is invalid")
    _typed_id("retry family Job", job_id, "job:")
    _digest("retry family Job hash", job_hash)
    _digest("retry family work fingerprint", work_fingerprint)
    basis_ids = tuple(
        _digest("retry basis record", item) for item in retry_basis_record_ids
    )
    if basis_ids != tuple(sorted(set(basis_ids))):
        raise JobRetryFamilyError(
            "retry basis records must be sorted and unique"
        )
    if phase == "declared":
        if completion_record_id is not None:
            raise JobRetryFamilyError(
                "declared retry family attempt cannot name a completion"
            )
    else:
        _digest("retry family completion", completion_record_id)
    return {
        "completion_record_id": completion_record_id,
        "family": family.payload(),
        "job_hash": job_hash,
        "job_id": job_id,
        "phase": phase,
        "retry_family_fingerprint": family.fingerprint,
        "retry_basis_record_ids": list(basis_ids),
        "schema": RETRY_FAMILY_ATTEMPT_SCHEMA,
        "scientific_failure_delta": 0,
        "scientific_trial_delta": 0,
        "work_fingerprint": work_fingerprint,
    }


def retry_family_attempt_identity(payload: Mapping[str, Any]) -> str:
    return canonical_digest(
        domain="job-retry-family-attempt",
        payload=dict(payload),
    )


def require_legacy_implementation_retry_semantics(
    *,
    previous_spec: Mapping[str, Any],
    current_spec: Mapping[str, Any],
) -> None:
    """Allow an implementation proof to change implementation evidence only."""

    previous = dict(previous_spec)
    current = dict(current_spec)
    for spec in (previous, current):
        spec.pop("changed_cause_proof_hash", None)
        spec.pop("implementation_identity", None)
    try:
        same_frozen_contract = canonical_bytes(previous) == canonical_bytes(current)
    except (CanonicalJSONError, TypeError, ValueError) as exc:
        raise JobRetryFamilyError(
            "implementation retry Job specification is not canonical"
        ) from exc
    if not same_frozen_contract:
        raise JobRetryFamilyError(
            "implementation retry changes scientific or semantic Job inputs, "
            "outputs, or operational contract"
        )


def _require_same_implementation_retry_spec(
    *,
    previous_spec: Mapping[str, Any],
    current_spec: Mapping[str, Any],
    changed_dimension: str,
) -> None:
    previous = dict(previous_spec)
    current = dict(current_spec)
    previous.pop("changed_cause_proof_hash", None)
    current.pop("changed_cause_proof_hash", None)
    if previous.get("implementation_identity") != current.get(
        "implementation_identity"
    ):
        raise JobRetryFamilyError(
            "same-implementation retry changes implementation identity"
        )
    if changed_dimension != "compute_budget":
        if previous != current:
            raise JobRetryFamilyError(
                "operational retry changes the frozen Job specification"
            )
        return
    previous_budget = previous.pop("budget", None)
    current_budget = current.pop("budget", None)
    if previous != current:
        raise JobRetryFamilyError(
            "compute retry changes non-budget Job semantics"
        )
    if not isinstance(previous_budget, Mapping) or not isinstance(
        current_budget, Mapping
    ):
        raise JobRetryFamilyError("compute retry budget is malformed")
    if set(previous_budget) != set(current_budget):
        raise JobRetryFamilyError("compute retry changes budget dimensions")
    for name in set(previous_budget) - {"compute_seconds", "wall_seconds"}:
        if previous_budget[name] != current_budget[name]:
            raise JobRetryFamilyError(
                "compute retry changes scientific trial or stop budget"
            )
    if all(
        previous_budget.get(name) == current_budget.get(name)
        for name in ("compute_seconds", "wall_seconds")
    ):
        raise JobRetryFamilyError("compute retry does not reestimate compute budget")


@dataclass(frozen=True, slots=True)
class JobRetryResumeAuthority:
    changed_dimension: str
    new_basis_hash: str
    new_evidence_hashes: tuple[str, ...]
    verification_receipt_hashes: tuple[str, ...]
    validations: tuple[JobRetryValidationAuthority, ...]


@dataclass(frozen=True, slots=True)
class JobRetryValidationAuthority:
    receipt_hash: str
    validator_id: str
    validation_plan_hash: str
    measurement_artifact_hashes: tuple[str, ...]
    artifact_roles: tuple[tuple[str, str], ...]
    facts: Mapping[str, Any]
    declared_artifact_count: int
    opened_artifact_count: int

    def payload(self) -> dict[str, Any]:
        return {
            "artifact_roles": [
                {"artifact_hash": artifact_hash, "role": role}
                for role, artifact_hash in self.artifact_roles
            ],
            "declared_artifact_count": self.declared_artifact_count,
            "facts": _plain_canonical(self.facts),
            "measurement_artifact_hashes": list(
                self.measurement_artifact_hashes
            ),
            "opened_artifact_count": self.opened_artifact_count,
            "receipt_hash": self.receipt_hash,
            "schema": "job_retry_validation_authority.v1",
            "validated_verdict": "passed",
            "validation_plan_hash": self.validation_plan_hash,
            "validator_id": self.validator_id,
        }


class JobRetryValidationDispatchRequired(RuntimeError):
    """A Writer dry pass reached one registered retry-validation boundary."""

    def __init__(self, arguments: Mapping[str, Any]) -> None:
        super().__init__("engineering retry validation must run outside Writer lock")
        self.arguments = _plain_canonical(arguments)


@dataclass(frozen=True, slots=True)
class RuntimeSourceRetryResolution:
    new_basis_hash: str
    source_contract_id: str
    prior_source_state_record_id: str
    current_source_state_record_id: str
    current_source_receipt_id: str

    def payload(self) -> dict[str, Any]:
        return {
            "authority_kind": "runtime_source_state_advance",
            "changed_dimension": "information",
            "current_source_receipt_id": self.current_source_receipt_id,
            "current_source_state_record_id": (
                self.current_source_state_record_id
            ),
            "new_basis_hash": self.new_basis_hash,
            "prior_source_state_record_id": (
                self.prior_source_state_record_id
            ),
            "schema": "runtime_source_retry_resolution.v1",
            "scientific_semantics_changed": False,
            "source_contract_id": self.source_contract_id,
        }


def derive_runtime_source_retry_resolution(
    *,
    failure: Mapping[str, Any] | None,
    previous_candidate_context: Mapping[str, Any] | None,
    current_candidate_context: Mapping[str, Any] | None,
    previous_spec: Mapping[str, Any],
    current_spec: Mapping[str, Any],
) -> RuntimeSourceRetryResolution | None:
    """Recognize an exact fresh source head after runtime-source ineligibility.

    The current candidate context has already been Writer-derived through the
    runtime-source eligibility gate.  No caller receipt or loose Job input can
    manufacture this release.
    """

    if not isinstance(failure, Mapping) or failure.get(
        "failure_kind"
    ) != "runtime_source_ineligibility":
        return None
    if not isinstance(previous_candidate_context, Mapping) or not isinstance(
        current_candidate_context, Mapping
    ):
        raise JobRetryFamilyError(
            "runtime-source retry lost its Writer-derived candidate context"
        )
    _require_same_implementation_retry_spec(
        previous_spec=previous_spec,
        current_spec=current_spec,
        changed_dimension="information",
    )
    source_contract_id = _ascii(
        "runtime-source retry SourceContract",
        failure.get("source_contract_id"),
    )
    prior_state = _digest(
        "runtime-source retry prior state",
        failure.get("source_state_record_id"),
    )
    prior_states = previous_candidate_context.get("source_state_record_ids")
    current_states = current_candidate_context.get("source_state_record_ids")
    current_rows = current_candidate_context.get("source_snapshot_rows")
    if (
        not isinstance(prior_states, list)
        or prior_states != sorted(set(prior_states))
        or not isinstance(current_states, list)
        or current_states != sorted(set(current_states))
        or not isinstance(current_rows, list)
        or prior_state not in prior_states
        or prior_state in current_states
        or prior_states == current_states
    ):
        raise JobRetryFamilyError(
            "runtime-source retry does not advance the failed source state"
        )
    for state_id in (*prior_states, *current_states):
        _digest("runtime-source retry state", state_id)
    matching_rows = [
        row
        for row in current_rows
        if isinstance(row, Mapping)
        and row.get("source_contract_id") == source_contract_id
    ]
    if len(matching_rows) != 1:
        raise JobRetryFamilyError(
            "runtime-source retry current source row is ambiguous"
        )
    row = matching_rows[0]
    current_state = _digest(
        "runtime-source retry current state",
        row.get("source_state_record_id"),
    )
    current_receipt = _ascii(
        "runtime-source retry current receipt",
        row.get("source_receipt_id"),
    )
    if current_state not in current_states or current_state == prior_state:
        raise JobRetryFamilyError(
            "runtime-source retry current state is not the fresh source head"
        )
    basis_payload = {
        "current_candidate_context": dict(current_candidate_context),
        "current_source_receipt_id": current_receipt,
        "current_source_state_record_id": current_state,
        "prior_source_state_record_id": prior_state,
        "schema": "runtime_source_retry_resolution.v1",
        "source_contract_id": source_contract_id,
    }
    return RuntimeSourceRetryResolution(
        new_basis_hash=canonical_digest(
            domain="runtime-source-retry-resolution",
            payload=basis_payload,
        ),
        source_contract_id=source_contract_id,
        prior_source_state_record_id=prior_state,
        current_source_state_record_id=current_state,
        current_source_receipt_id=current_receipt,
    )


def retry_basis_identity(
    *,
    retry_family_fingerprint: str,
    changed_dimension: str,
    new_basis_hash: str,
) -> str:
    _digest("retry family fingerprint", retry_family_fingerprint)
    if changed_dimension not in _RETRY_BASIS_DIMENSIONS:
        raise JobRetryFamilyError("retry changed dimension is invalid")
    _digest("retry new basis", new_basis_hash)
    return canonical_digest(
        domain="job-retry-basis",
        payload={
            "changed_dimension": changed_dimension,
            "new_basis_hash": new_basis_hash,
            "retry_family_fingerprint": retry_family_fingerprint,
            "schema": "job_retry_basis.v1",
        },
    )


def validate_engineering_retry_evidence(
    *,
    receipt_hash: str,
    validator_id: str,
    validation_plan_hash: str,
    result_artifact_hashes: tuple[str, ...],
    mission_id: str,
    retry_family_fingerprint: str,
    prior_completion_record_id: str,
    prior_job_id: str,
    prior_job_hash: str,
    prior_work_fingerprint: str,
    new_work_fingerprint: str,
    changed_dimension: str,
    new_basis_hash: str,
    evidence_subject: Mapping[str, str],
    binding: Mapping[str, Any],
    result_manifest: Mapping[str, Any],
    validation_registry: EvidenceValidatorRegistry,
    evidence_path: EvidencePathResolver,
    engineering_fixture: bool,
    prevalidated_authority: JobRetryValidationAuthority | None = None,
    defer_validation: bool = False,
) -> JobRetryValidationAuthority:
    """Run one immutable engineering validator and bind its exact facts."""

    _digest("engineering validation receipt", receipt_hash)
    plan_hash = _digest(
        "engineering validation plan",
        validation_plan_hash,
    )
    results = tuple(
        _digest("engineering validation result", item)
        for item in result_artifact_hashes
    )
    if (
        not results
        or results != tuple(sorted(set(results)))
        or plan_hash in results
    ):
        raise JobRetryFamilyError(
            "engineering validation artifacts must be distinct and ordered"
        )
    dispatch_arguments = {
        "binding": _plain_canonical(binding),
        "changed_dimension": changed_dimension,
        "engineering_fixture": engineering_fixture,
        "evidence_subject": _plain_canonical(evidence_subject),
        "mission_id": mission_id,
        "new_basis_hash": new_basis_hash,
        "new_work_fingerprint": new_work_fingerprint,
        "prior_completion_record_id": prior_completion_record_id,
        "prior_job_hash": prior_job_hash,
        "prior_job_id": prior_job_id,
        "prior_work_fingerprint": prior_work_fingerprint,
        "receipt_hash": receipt_hash,
        "result_artifact_hashes": list(results),
        "result_manifest": _plain_canonical(result_manifest),
        "retry_family_fingerprint": retry_family_fingerprint,
        "validation_plan_hash": plan_hash,
        "validator_id": validator_id,
    }
    if prevalidated_authority is not None:
        exact_binding = _plain_canonical(binding)
        role_hashes = {
            artifact_hash
            for _role, artifact_hash in prevalidated_authority.artifact_roles
        }
        if (
            prevalidated_authority.receipt_hash != receipt_hash
            or prevalidated_authority.validator_id != validator_id
            or prevalidated_authority.validation_plan_hash != plan_hash
            or prevalidated_authority.measurement_artifact_hashes != results
            or role_hashes != {plan_hash, *results}
            or _plain_canonical(prevalidated_authority.facts).get("binding")
            != exact_binding
            or _plain_canonical(prevalidated_authority.facts).get(
                "cause_resolved"
            )
            is not True
            or _plain_canonical(prevalidated_authority.facts).get(
                "material_change"
            )
            is not True
            or prevalidated_authority.declared_artifact_count
            != len(results) + 1
            or prevalidated_authority.opened_artifact_count
            != len(results) + 1
        ):
            raise JobRetryFamilyError(
                "prevalidated engineering retry authority differs from dispatch"
            )
        return prevalidated_authority
    if defer_validation:
        raise JobRetryValidationDispatchRequired(dispatch_arguments)
    try:
        artifacts = (
            ValidationArtifact(
                output_name="validation_plan",
                sha256=plan_hash,
                _source=evidence_path(plan_hash),
            ),
            *(
                ValidationArtifact(
                    output_name=f"validation_result:{index:04d}",
                    sha256=artifact_hash,
                    _source=evidence_path(artifact_hash),
                )
                for index, artifact_hash in enumerate(results)
            ),
        )
        request = EngineeringEvidenceValidationRequest(
            validator_id=validator_id,
            validation_plan_hash=plan_hash,
            mission_id=mission_id,
            retry_family_fingerprint=retry_family_fingerprint,
            prior_completion_record_id=prior_completion_record_id,
            prior_job_id=prior_job_id,
            prior_job_hash=prior_job_hash,
            prior_work_fingerprint=prior_work_fingerprint,
            new_work_fingerprint=new_work_fingerprint,
            changed_dimension=changed_dimension,
            new_basis_hash=new_basis_hash,
            evidence_subject=evidence_subject,
            binding=binding,
            result_manifest=result_manifest,
            artifacts=artifacts,
            engineering_fixture=engineering_fixture,
        )
        validated, trace = validation_registry.validate(request)
    except (
        EvidenceValidationError,
        FileNotFoundError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        raise JobRetryFamilyError(
            "registered engineering retry validation failed"
        ) from exc
    facts = _plain_canonical(validated.facts)
    exact_binding = _plain_canonical(binding)
    role_hashes = {artifact_hash for _role, artifact_hash in validated.artifact_roles}
    support_hashes = {plan_hash, *results}
    if (
        validated.verdict != "passed"
        or validated.claims
        or validated.scientific_eligible
        or validated.candidate_eligible
        or validated.release_eligible
        or tuple(validated.measurement_artifact_hashes) != results
        or role_hashes != support_hashes
        or not isinstance(facts, dict)
        or facts.get("binding") != exact_binding
        or facts.get("cause_resolved") is not True
        or facts.get("material_change") is not True
        or trace.declared_artifact_count != len(artifacts)
        or trace.opened_artifact_count != len(artifacts)
    ):
        raise JobRetryFamilyError(
            "engineering retry validator did not establish exact passed facts"
        )
    return JobRetryValidationAuthority(
        receipt_hash=receipt_hash,
        validator_id=trace.validator_id,
        validation_plan_hash=plan_hash,
        measurement_artifact_hashes=tuple(
            validated.measurement_artifact_hashes
        ),
        artifact_roles=tuple(validated.artifact_roles),
        facts=facts,
        declared_artifact_count=trace.declared_artifact_count,
        opened_artifact_count=trace.opened_artifact_count,
    )


def parse_job_retry_resume_authority(
    content: bytes,
    *,
    mission_id: str,
    evidence_subject: Mapping[str, str],
    retry_family_fingerprint: str,
    prior_completion_record_id: str,
    prior_job_id: str,
    prior_job_hash: str,
    prior_work_fingerprint: str,
    new_work_fingerprint: str,
    failure: Mapping[str, Any],
    engineering_disposition: Mapping[str, Any],
    previous_spec: Mapping[str, Any],
    current_spec: Mapping[str, Any],
    read_evidence: EvidenceReader,
    verify_evidence: EvidenceVerifier,
    evidence_path: EvidencePathResolver,
    validation_registry: EvidenceValidatorRegistry,
    engineering_fixture: bool,
    prevalidated_authorities: (
        Mapping[str, JobRetryValidationAuthority] | None
    ) = None,
    defer_validation: bool = False,
) -> JobRetryResumeAuthority:
    """Validate one evidence-bound release of a failed retry family."""

    value = _document(content, name="Job retry resume authority")
    required = {
        "changed_dimension",
        "engineering_disposition_hash",
        "failure_signature",
        "new_basis_hash",
        "new_evidence_hashes",
        "new_work_fingerprint",
        "previous_basis_hash",
        "prior_completion_record_id",
        "prior_job_hash",
        "prior_job_id",
        "prior_work_fingerprint",
        "resume_condition",
        "retry_family_fingerprint",
        "schema",
        "scientific_semantics_changed",
        "verification_receipt_hashes",
    }
    if (
        set(value) != required
        or value.get("schema") != RETRY_RESUME_AUTHORITY_SCHEMA
        or value.get("scientific_semantics_changed") is not False
    ):
        raise JobRetryFamilyError("Job retry resume authority schema is invalid")
    changed_dimension = value.get("changed_dimension")
    if changed_dimension not in _RESUME_CHANGED_DIMENSIONS:
        raise JobRetryFamilyError("Job retry changed dimension is invalid")
    family_fingerprint = _digest(
        "retry family fingerprint", value.get("retry_family_fingerprint")
    )
    if family_fingerprint != retry_family_fingerprint:
        raise JobRetryFamilyError("Job retry authority names another family")
    observed_completion = _digest(
        "prior Job completion", value.get("prior_completion_record_id")
    )
    observed_job_id = _typed_id(
        "prior retry Job", value.get("prior_job_id"), "job:"
    )
    observed_job_hash = _digest(
        "prior retry Job hash", value.get("prior_job_hash")
    )
    observed_prior_work = _digest(
        "prior work fingerprint", value.get("prior_work_fingerprint")
    )
    observed_new_work = _digest(
        "new work fingerprint", value.get("new_work_fingerprint")
    )
    if (
        observed_completion != prior_completion_record_id
        or observed_job_id != prior_job_id
        or observed_job_hash != prior_job_hash
        or observed_prior_work != prior_work_fingerprint
        or observed_new_work != new_work_fingerprint
    ):
        raise JobRetryFamilyError("Job retry authority is stale or cross-work")
    if failure.get("failure_kind") != "engineering":
        raise JobRetryFamilyError(
            "same-implementation release requires an engineering failure"
        )
    failure_signature = _digest(
        "prior failure signature", value.get("failure_signature")
    )
    disposition_hash = _digest(
        "engineering disposition hash",
        value.get("engineering_disposition_hash"),
    )
    resume_condition = _ascii(
        "engineering resume condition", value.get("resume_condition")
    )
    disposition = engineering_disposition.get("disposition")
    if disposition not in _ENGINEERING_ONLY_DISPOSITIONS:
        raise JobRetryFamilyError(
            "scientific-change disposition cannot release the same Job family"
        )
    if (
        failure_signature != failure.get("failure_signature")
        or disposition_hash != failure.get("repair_disposition_hash")
        or resume_condition != engineering_disposition.get("resume_condition")
    ):
        raise JobRetryFamilyError(
            "Job retry authority differs from the exact failed disposition"
        )
    previous_basis = _digest(
        "previous retry basis", value.get("previous_basis_hash")
    )
    if previous_basis != engineering_disposition.get("basis_manifest_hash"):
        raise JobRetryFamilyError(
            "Job retry authority changes its disposition basis"
        )
    new_basis = _digest("new retry basis", value.get("new_basis_hash"))
    if new_basis == previous_basis:
        raise JobRetryFamilyError("Job retry authority does not change basis")
    new_evidence = _digest_list(
        "Job retry new evidence",
        value.get("new_evidence_hashes"),
        allow_empty=False,
    )
    receipts = _digest_list(
        "Job retry verification receipts",
        value.get("verification_receipt_hashes"),
        allow_empty=False,
    )
    if new_basis not in new_evidence or set(new_evidence).intersection(receipts):
        raise JobRetryFamilyError(
            "Job retry changed basis and verification evidence are not independent"
        )
    for evidence_hash in new_evidence:
        verify_evidence(evidence_hash)

    receipt_required = {
        "changed_dimension",
        "check_plan_hash",
        "engineering_disposition_hash",
        "failure_signature",
        "new_basis_hash",
        "new_work_fingerprint",
        "prior_completion_record_id",
        "prior_job_hash",
        "prior_job_id",
        "result_artifact_hashes",
        "resume_condition",
        "retry_family_fingerprint",
        "schema",
        "scientific_semantics_changed",
        "validator_id",
        "verdict",
        "verification_method",
    }
    verification_support: set[str] = set()
    validations: list[JobRetryValidationAuthority] = []
    _require_same_implementation_retry_spec(
        previous_spec=previous_spec,
        current_spec=current_spec,
        changed_dimension=str(changed_dimension),
    )
    for receipt_hash in receipts:
        receipt = _document(
            read_evidence(receipt_hash),
            name="Job retry verification receipt",
        )
        if (
            set(receipt) != receipt_required
            or receipt.get("schema") != RETRY_RESUME_VERIFICATION_SCHEMA
            or receipt.get("scientific_semantics_changed") is not False
            or receipt.get("changed_dimension") != changed_dimension
            or receipt.get("engineering_disposition_hash") != disposition_hash
            or receipt.get("failure_signature") != failure_signature
            or receipt.get("new_basis_hash") != new_basis
            or receipt.get("new_work_fingerprint") != observed_new_work
            or receipt.get("prior_completion_record_id") != observed_completion
            or receipt.get("prior_job_hash") != observed_job_hash
            or receipt.get("prior_job_id") != observed_job_id
            or receipt.get("resume_condition") != resume_condition
            or receipt.get("retry_family_fingerprint") != family_fingerprint
        ):
            raise JobRetryFamilyError(
                "Job retry verification differs from its exact authority"
            )
        _ascii(
            "Job retry verification method",
            receipt.get("verification_method"),
        )
        validator_id = _ascii(
            "Job retry verification validator",
            receipt.get("validator_id"),
        )
        check_plan = _digest(
            "Job retry verification plan", receipt.get("check_plan_hash")
        )
        result_hashes = _digest_list(
            "Job retry verification results",
            receipt.get("result_artifact_hashes"),
            allow_empty=False,
        )
        for support_hash in (check_plan, *result_hashes):
            verify_evidence(support_hash)
            verification_support.add(support_hash)
        binding = {
            "authority_kind": "same_implementation_retry",
            "changed_dimension": changed_dimension,
            "engineering_disposition_hash": disposition_hash,
            "failure_signature": failure_signature,
            "new_basis_hash": new_basis,
            "new_work_fingerprint": observed_new_work,
            "previous_basis_hash": previous_basis,
            "prior_completion_record_id": observed_completion,
            "prior_job_hash": observed_job_hash,
            "prior_job_id": observed_job_id,
            "prior_work_fingerprint": observed_prior_work,
            "resume_condition": resume_condition,
            "retry_family_fingerprint": family_fingerprint,
            "schema": "engineering_retry_validation_binding.v1",
            "scientific_semantics_changed": False,
        }
        validation = validate_engineering_retry_evidence(
            receipt_hash=receipt_hash,
            validator_id=validator_id,
            validation_plan_hash=check_plan,
            result_artifact_hashes=result_hashes,
            mission_id=mission_id,
            retry_family_fingerprint=family_fingerprint,
            prior_completion_record_id=observed_completion,
            prior_job_id=observed_job_id,
            prior_job_hash=observed_job_hash,
            prior_work_fingerprint=observed_prior_work,
            new_work_fingerprint=observed_new_work,
            changed_dimension=str(changed_dimension),
            new_basis_hash=new_basis,
            evidence_subject=evidence_subject,
            binding=binding,
            result_manifest=receipt,
            validation_registry=validation_registry,
            evidence_path=evidence_path,
            engineering_fixture=engineering_fixture,
            prevalidated_authority=(
                None
                if prevalidated_authorities is None
                else prevalidated_authorities.get(receipt_hash)
            ),
            defer_validation=defer_validation,
        )
        if receipt.get("verdict") != "passed":
            raise JobRetryFamilyError(
                "Job retry caller verdict differs from validated facts"
            )
        validations.append(validation)
    if prevalidated_authorities is not None and set(
        prevalidated_authorities
    ) != set(receipts):
        raise JobRetryFamilyError(
            "prevalidated retry authority set differs from receipts"
        )
    if set(new_evidence).intersection(verification_support):
        raise JobRetryFamilyError(
            "Job retry verification support reuses changed-basis evidence"
        )
    return JobRetryResumeAuthority(
        changed_dimension=str(changed_dimension),
        new_basis_hash=new_basis,
        new_evidence_hashes=new_evidence,
        verification_receipt_hashes=receipts,
        validations=tuple(validations),
    )


__all__ = [
    "JobRetryFamily",
    "JobRetryFamilyError",
    "JobRetryResumeAuthority",
    "JobRetryValidationDispatchRequired",
    "JobRetryValidationAuthority",
    "RETRY_RESUME_AUTHORITY_SCHEMA",
    "RuntimeSourceRetryResolution",
    "derive_job_retry_family",
    "derive_runtime_source_retry_resolution",
    "evidence_schema",
    "parse_job_retry_resume_authority",
    "require_legacy_implementation_retry_semantics",
    "retry_basis_identity",
    "retry_family_attempt_identity",
    "retry_family_attempt_payload",
    "validate_engineering_retry_evidence",
]
