"""Pure normalization and validation for immutable Job declarations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.external_dependency import (
    ExternalDependencyContractError,
    external_plan_from_binding,
)


class JobContractError(RuntimeError):
    """A Job declaration violates its immutable logical contract."""


EvidenceModesValidator = Callable[[Mapping[str, Any]], tuple[str, ...]]
EvidenceVerifier = Callable[[str], object]
EngineeringCauseBuilder = Callable[
    [Mapping[str, Any]], tuple[Mapping[str, Any], str]
]


@dataclass(frozen=True, slots=True)
class JobIdentityPlan:
    """Pure identities and bound work produced from one validated Job spec."""

    bound_work_basis: Mapping[str, Any]
    job_hash: str
    job_id: str
    success_fingerprint: str
    work_fingerprint: str


_JOB_OUTPUT_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")
_WORKER_CLAIM_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_WINDOWS_RESERVED_OUTPUT_COMPONENTS = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{ordinal}" for ordinal in range(1, 10)),
        *(f"lpt{ordinal}" for ordinal in range(1, 10)),
    }
)
_JOB_OUTPUT_CLASS_ROOTS = {
    "durable_evidence": frozenset({"evidence", "scientific", "source"}),
    "reproducible_cache": frozenset({"local/cache"}),
    "transient": frozenset({"local/jobs"}),
}


def _copy(value: Mapping[str, Any]) -> dict[str, Any]:
    copied = parse_canonical(canonical_bytes(dict(value)))
    assert isinstance(copied, dict)
    return dict(copied)


def _require_ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise JobContractError(f"{name} must be non-empty ASCII")
    return value


def _require_digest(name: str, value: object) -> str:
    result = _require_ascii(name, value)
    if len(result) != 64 or any(
        character not in "0123456789abcdef" for character in result
    ):
        raise JobContractError(f"{name} must be a lowercase SHA-256 digest")
    return result


def canonical_job_output_identity(
    value: object,
    *,
    output_class: object | None = None,
    name: str = "Job output",
) -> str:
    """Validate one cross-platform logical output name and return its alias key."""

    if type(value) is not str or not value or not value.isascii():
        raise JobContractError(f"{name} must be non-empty ASCII")
    if len(value) > 1024 or "\\" in value or ":" in value:
        raise JobContractError(f"{name} must use canonical POSIX spelling")
    parts = value.split("/")
    if (
        (output_class is not None and len(parts) < 2)
        or any(part in {"", ".", ".."} for part in parts)
        or any(len(part) > 255 for part in parts)
    ):
        raise JobContractError(
            f"{name} must be a normalized relative logical path"
        )
    for part in parts:
        if (
            _JOB_OUTPUT_COMPONENT.fullmatch(part) is None
            or part.endswith((".", " "))
            or part.split(".", 1)[0].casefold()
            in _WINDOWS_RESERVED_OUTPUT_COMPONENTS
        ):
            raise JobContractError(
                f"{name} contains a non-portable or reserved path component"
            )
    if output_class is not None:
        roots = _JOB_OUTPUT_CLASS_ROOTS.get(output_class)
        if roots is None:
            raise JobContractError("Job output has an invalid storage class")
        root = "/".join(parts[:2]) if parts[0] == "local" else parts[0]
        if root not in roots:
            raise JobContractError(
                f"{output_class} output is outside its logical namespace"
            )
        if parts[0] == "local" and len(parts) < 3:
            raise JobContractError(
                f"{output_class} output must name a file below its namespace"
            )
    return value.casefold()


def canonical_worker_claim_identity(value: object, *, name: str) -> str:
    """Return one portable case-folded logical worker claim identity."""

    if (
        type(value) is not str
        or not value
        or not value.isascii()
        or len(value) > 255
        or _WORKER_CLAIM_IDENTIFIER.fullmatch(value) is None
    ):
        raise JobContractError(
            f"{name} must be a portable non-empty ASCII logical identifier"
        )
    return value.casefold()


def require_job_output_namespace(
    output_names: Sequence[object],
    *,
    output_classes: Mapping[object, object] | None = None,
    name: str = "Job outputs",
) -> None:
    """Reject spelling aliases and enforce storage-class namespace lanes."""

    identities = [
        canonical_job_output_identity(
            value,
            output_class=(
                None if output_classes is None else output_classes.get(value)
            ),
            name=name,
        )
        for value in output_names
    ]
    if len(identities) != len(set(identities)):
        raise JobContractError(f"{name} contain a case-insensitive path alias")


def normalize_job_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical ordering used by Job identity construction."""

    value = _copy(spec)
    for name in ("input_hashes", "expected_outputs"):
        if isinstance(value.get(name), list):
            value[name] = sorted(value[name])
    claims = value.get("worker_claims")
    if isinstance(claims, list):
        for claim in claims:
            if isinstance(claim, dict):
                for name in ("inputs", "outputs", "resources"):
                    if isinstance(claim.get(name), list):
                        claim[name] = sorted(claim[name])
        value["worker_claims"] = sorted(
            claims,
            key=lambda claim: (
                claim.get("worker_id", "") if isinstance(claim, dict) else ""
            ),
        )
    for binding_name in (
        "component_parity_binding",
        "runtime_binding",
        "scientific_binding",
    ):
        binding = value.get(binding_name)
        if isinstance(binding, dict):
            for name in (
                "evidence_modes",
                "planned_claims",
                "planned_parity_surfaces",
                "planned_materialization_cases",
                "planned_source_lifecycle_coverage_ids",
                "dimensions",
            ):
                if isinstance(binding.get(name), list):
                    binding[name] = sorted(binding[name])
    return value


def build_job_identity_plan(
    *,
    spec: Mapping[str, Any],
    work_basis: Mapping[str, Any],
    mission_id: str,
    candidate_execution_context: Mapping[str, Any] | None,
    observed_development_binding: Mapping[str, Any] | None,
    implementation_source_authority: Mapping[str, Any] | None,
    external_observed_development_binding: Mapping[str, Any] | None,
) -> JobIdentityPlan:
    """Bind every current execution authority into Job and cache identity."""

    optional = {
        "candidate_execution_context": candidate_execution_context,
        "observed_development_binding": observed_development_binding,
        "implementation_source_authority": implementation_source_authority,
        "external_observed_development_binding": (
            external_observed_development_binding
        ),
    }
    bound_work_basis = dict(work_basis)
    job_identity_payload: dict[str, Any] = {
        "mission_id": mission_id,
        "spec": dict(spec),
    }
    for name, value in optional.items():
        if value is not None:
            bound_work_basis[name] = value
            job_identity_payload[name] = value
    job_hash = canonical_digest(domain="job", payload=job_identity_payload)
    work_fingerprint = canonical_digest(
        domain="job-work",
        payload={"mission_id": mission_id, "work": bound_work_basis},
    )
    success_payload: dict[str, Any] = {
        "expected_outputs": spec["expected_outputs"],
        "implementation_identity": spec["implementation_identity"],
        "mission_id": mission_id,
        "output_classes": spec["output_classes"],
        "work_fingerprint": work_fingerprint,
        "candidate_execution_context": candidate_execution_context,
        "implementation_source_authority": implementation_source_authority,
        "external_observed_development_binding": (
            external_observed_development_binding
        ),
    }
    if observed_development_binding is not None:
        success_payload["observed_development_binding"] = (
            observed_development_binding
        )
    return JobIdentityPlan(
        bound_work_basis=bound_work_basis,
        job_hash=job_hash,
        job_id=f"job:{job_hash}",
        success_fingerprint=canonical_digest(
            domain="job-success-cache",
            payload=success_payload,
        ),
        work_fingerprint=work_fingerprint,
    )


def normalize_job_failure_manifest(
    *,
    outcome: str,
    failure: Mapping[str, Any] | None,
    evidence_verifier: EvidenceVerifier,
    engineering_cause_builder: EngineeringCauseBuilder,
) -> dict[str, Any] | None:
    """Validate typed operational failure without creating scientific meaning."""

    if outcome not in {"success", "failed", "not_evaluable"}:
        raise JobContractError("invalid Job outcome")
    if outcome == "success":
        if failure is not None:
            raise JobContractError(
                "a successful Job cannot carry failure evidence"
            )
        return None
    if failure is None:
        raise JobContractError(
            "failed or not-evaluable Job requires failure evidence"
        )
    required = {
        "failure_kind",
        "minimum_reproduction_evidence",
        "root_cause",
        "interrupted_action",
        "resume_action",
    }
    if not isinstance(failure, Mapping):
        raise JobContractError("failure must be a mapping")
    missing = required - set(failure)
    if missing:
        raise JobContractError(
            f"failure is missing fields: {sorted(missing)!r}"
        )
    manifest = _copy(failure)
    for name in ("root_cause", "interrupted_action", "resume_action"):
        _require_ascii(name, manifest[name])
    failure_kind = manifest["failure_kind"]
    if failure_kind not in {
        "engineering",
        "runtime_source_ineligibility",
        "scientific_falsification",
        "not_evaluable",
        "external_dependency",
    }:
        raise JobContractError("Job failure_kind is not typed")
    if failure_kind == "scientific_falsification":
        raise JobContractError(
            "a validator-derived scientific verdict is not a Job execution failure"
        )
    if failure_kind == "not_evaluable":
        raise JobContractError(
            "not_evaluable is a validator verdict, not an untyped Job execution failure"
        )
    allowed_failure_outcomes = {
        "engineering": {"failed"},
        "runtime_source_ineligibility": {"not_evaluable"},
        "external_dependency": {"failed", "not_evaluable"},
    }
    if outcome not in allowed_failure_outcomes[failure_kind]:
        raise JobContractError(
            "Job outcome differs from its exact failure-kind semantics"
        )
    references = manifest["minimum_reproduction_evidence"]
    if (
        not isinstance(references, list)
        or not references
        or references != sorted(set(references))
    ):
        raise JobContractError(
            "failure requires sorted unique minimum reproduction evidence"
        )
    for reference in references:
        evidence_verifier(reference)
    expected_fields = set(required)
    if failure_kind == "engineering":
        expected_fields.add("repair_disposition_hash")
        _require_digest(
            "engineering failure disposition",
            manifest.get("repair_disposition_hash"),
        )
    elif failure_kind == "runtime_source_ineligibility":
        expected_fields.update(
            {"source_contract_id", "source_state_record_id"}
        )
        _require_ascii(
            "runtime-ineligible source contract",
            manifest.get("source_contract_id"),
        )
        _require_digest(
            "runtime-ineligible source state",
            manifest.get("source_state_record_id"),
        )
    else:
        expected_fields.update(
            {"external_dependency_id", "observed_external_state"}
        )
        for name in ("external_dependency_id", "observed_external_state"):
            _require_ascii(name, manifest.get(name))
    if set(manifest) != expected_fields:
        raise JobContractError(
            "Job failure manifest differs from its exact typed schema"
        )
    if failure_kind == "engineering":
        _cause, cause_hash = engineering_cause_builder(
            {
                "failure_kind": "engineering",
                "interrupted_action": manifest["interrupted_action"],
                "minimum_reproduction_evidence": references,
                "root_cause": manifest["root_cause"],
            }
        )
        manifest["engineering_cause_hash"] = cause_hash
    manifest["failure_signature"] = canonical_digest(
        domain="job-failure",
        payload=manifest,
    )
    return manifest


def _validate_worker_claims(claims: object) -> None:
    if not isinstance(claims, list):
        raise JobContractError("worker_claims must be a list")
    seen_by_kind: dict[str, set[str]] = {
        "inputs": set(),
        "outputs": set(),
        "resources": set(),
    }
    worker_ids: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            raise JobContractError("worker claim must be an object")
        worker_id = canonical_worker_claim_identity(
            claim.get("worker_id"),
            name="worker_id",
        )
        if worker_id in worker_ids:
            raise JobContractError("worker_id values must be unique")
        worker_ids.add(worker_id)
        for key, seen in seen_by_kind.items():
            values = claim.get(key, [])
            if not isinstance(values, list) or any(
                not isinstance(item, str) for item in values
            ):
                raise JobContractError(f"worker {key} must be a string list")
            normalized_values = (
                [
                    canonical_job_output_identity(
                        item,
                        name="worker output claim",
                    )
                    for item in values
                ]
                if key == "outputs"
                else [
                    canonical_worker_claim_identity(
                        item,
                        name=f"worker {key} claim",
                    )
                    for item in values
                ]
            )
            if len(set(normalized_values)) != len(normalized_values):
                raise JobContractError(f"worker {key} has duplicate claims")
            overlap = seen.intersection(normalized_values)
            if overlap:
                raise JobContractError(
                    f"worker {key} overlap: {sorted(overlap)!r}"
                )
            seen.update(normalized_values)


def _validate_job_core(
    spec: Mapping[str, Any],
) -> tuple[list[str], dict[str, str], dict[str, str]]:
    required = {
        "callable_identity",
        "implementation_identity",
        "input_hashes",
        "budget",
        "expected_outputs",
        "output_classes",
        "log_path",
        "timeout_or_stop_rule",
        "resume_action",
        "worker_claims",
        "evidence_subject",
    }
    missing = required - set(spec)
    if missing:
        raise JobContractError(f"Job spec missing fields: {sorted(missing)!r}")
    unexpected = set(spec) - required - {
        "changed_cause_proof_hash",
        "external_dependency_binding",
        "holdout_binding",
        "runtime_binding",
        "scientific_binding",
        "source_binding",
        "component_parity_binding",
    }
    if unexpected:
        raise JobContractError(
            f"Job spec has unknown fields: {sorted(unexpected)!r}"
        )
    changed_proof = spec.get("changed_cause_proof_hash")
    if changed_proof is not None:
        _require_digest("changed_cause_proof_hash", changed_proof)
    _require_digest("implementation_identity", spec["implementation_identity"])
    for name in (
        "callable_identity",
        "log_path",
        "timeout_or_stop_rule",
        "resume_action",
    ):
        _require_ascii(name, spec[name])
    canonical_job_output_identity(
        spec["log_path"],
        output_class="transient",
        name="Job log path",
    )

    input_hashes = spec["input_hashes"]
    if (
        not isinstance(input_hashes, list)
        or not input_hashes
        or input_hashes != sorted(set(input_hashes))
    ):
        raise JobContractError(
            "input_hashes must be a sorted unique non-empty list"
        )
    for input_hash in input_hashes:
        _require_digest("input hash", input_hash)

    expected_outputs = spec["expected_outputs"]
    output_classes = spec["output_classes"]
    if (
        not isinstance(expected_outputs, list)
        or not expected_outputs
        or any(not isinstance(item, str) for item in expected_outputs)
        or len(set(expected_outputs)) != len(expected_outputs)
    ):
        raise JobContractError(
            "expected_outputs must be a unique non-empty string list"
        )
    if (
        not isinstance(output_classes, dict)
        or set(output_classes) != set(expected_outputs)
    ):
        raise JobContractError(
            "output_classes must classify every expected output exactly"
        )
    allowed_classes = {"durable_evidence", "reproducible_cache", "transient"}
    if any(value not in allowed_classes for value in output_classes.values()):
        raise JobContractError("Job output has an invalid storage class")
    require_job_output_namespace(
        expected_outputs,
        output_classes=output_classes,
    )

    budget = spec["budget"]
    if (
        not isinstance(budget, dict)
        or not budget
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in budget.values()
        )
    ):
        raise JobContractError(
            "Job budget must contain positive integer bounds"
        )
    if not {"compute_seconds", "wall_seconds"}.issubset(budget):
        raise JobContractError(
            "Job budget must bind compute_seconds and wall_seconds"
        )

    evidence_subject = spec["evidence_subject"]
    if (
        not isinstance(evidence_subject, dict)
        or set(evidence_subject) != {"kind", "id"}
        or evidence_subject["kind"]
        not in {"Mission", "Initiative", "Study", "Executable", "Release"}
    ):
        raise JobContractError("Job evidence_subject is invalid")
    _require_ascii("evidence subject id", evidence_subject["id"])
    _validate_worker_claims(spec["worker_claims"])
    return input_hashes, output_classes, evidence_subject


def _validate_validator_binding(
    binding: Mapping[str, Any],
    *,
    input_hashes: Sequence[str],
) -> None:
    validator_id = binding.get("validator_id")
    validator_digest = (
        validator_id.removeprefix("validator:")
        if isinstance(validator_id, str)
        else ""
    )
    _require_digest("validator identity", validator_digest)
    plan_hash = binding.get("validation_plan_hash")
    _require_digest("validation_plan_hash", plan_hash)
    if plan_hash not in input_hashes:
        raise JobContractError(
            "validation plan must be a content-bound Job input"
        )


def _durable_output_count(output_classes: Mapping[str, str]) -> int:
    return sum(
        value == "durable_evidence" for value in output_classes.values()
    )


def _validate_holdout_binding(
    binding: object,
    *,
    scientific_binding: object,
    evidence_subject: Mapping[str, str],
    input_hashes: Sequence[str],
) -> None:
    if binding is None:
        return
    if (
        not isinstance(binding, dict)
        or set(binding) != {"holdout_id"}
        or not isinstance(scientific_binding, Mapping)
        or scientific_binding.get("evidence_depth") != "confirmation"
        or evidence_subject["kind"] != "Executable"
    ):
        raise JobContractError(
            "holdout Job requires confirmation scientific binding"
        )
    holdout_id = binding["holdout_id"]
    if (
        type(holdout_id) is not str
        or not holdout_id.startswith("holdout:")
        or len(holdout_id) != 72
    ):
        raise JobContractError("holdout_binding identity is invalid")
    if holdout_id.removeprefix("holdout:") not in input_hashes:
        raise JobContractError("holdout identity must be a bound Job input")


def _validate_external_binding(
    binding: object,
    *,
    evidence_subject: Mapping[str, str],
    input_hashes: Sequence[str],
    output_classes: Mapping[str, str],
) -> None:
    if binding is None:
        return
    try:
        external_plan_from_binding(binding)
    except ExternalDependencyContractError as exc:
        raise JobContractError(str(exc)) from exc
    if evidence_subject["kind"] != "Mission":
        raise JobContractError(
            "external dependency Job must bind the Mission"
        )
    assert isinstance(binding, Mapping)
    _validate_validator_binding(binding, input_hashes=input_hashes)
    result_output = binding["result_manifest_output"]
    if output_classes.get(result_output) != "durable_evidence":
        raise JobContractError(
            "external dependency result manifest must be durable"
        )
    if _durable_output_count(output_classes) < 2:
        raise JobContractError(
            "external dependency Job requires result and measurement artifacts"
        )


def _validate_source_binding(
    binding: object,
    *,
    input_hashes: Sequence[str],
    output_classes: Mapping[str, str],
) -> None:
    if binding is None:
        return
    if not isinstance(binding, dict) or set(binding) != {
        "result_manifest_output",
        "source_contract_id",
        "transition_evidence",
        "validation_plan_hash",
        "validator_id",
    }:
        raise JobContractError("source_binding has an invalid schema")
    _validate_validator_binding(binding, input_hashes=input_hashes)
    source_id = binding["source_contract_id"]
    if (
        type(source_id) is not str
        or not source_id.startswith("source:")
        or len(source_id) != 71
    ):
        raise JobContractError(
            "source Job requires a SourceContract identity"
        )
    if binding["transition_evidence"] not in {
        "historical_audit",
        "runtime_availability_proof",
        "drift",
        "same_semantics_recertification",
    }:
        raise JobContractError(
            "source Job transition evidence is not typed"
        )
    result_output = binding["result_manifest_output"]
    if output_classes.get(result_output) != "durable_evidence":
        raise JobContractError(
            "source result manifest must be durable output"
        )
    if _durable_output_count(output_classes) < 2:
        raise JobContractError(
            "source Job requires result and measurement artifacts"
        )


def _validate_scientific_binding(
    binding: object,
    *,
    evidence_subject: Mapping[str, str],
    input_hashes: Sequence[str],
    output_classes: Mapping[str, str],
    evidence_modes_validator: EvidenceModesValidator,
) -> None:
    if binding is None:
        return
    required_fields = {
        "evidence_depth",
        "evidence_modes",
        "planned_claims",
        "result_manifest_output",
        "validation_plan_hash",
        "validator_id",
    }
    allowed_fields = required_fields | {"evaluation_schema"}
    if (
        not isinstance(binding, dict)
        or not required_fields.issubset(binding)
        or not set(binding).issubset(allowed_fields)
    ):
        raise JobContractError(
            "scientific_binding has an invalid schema"
        )
    _validate_validator_binding(binding, input_hashes=input_hashes)
    if "evaluation_schema" in binding:
        _require_ascii(
            "scientific evaluation schema",
            binding["evaluation_schema"],
        )
    if binding["evidence_depth"] not in {"discovery", "confirmation"}:
        raise JobContractError(
            "scientific Job evidence depth is invalid"
        )
    executed_modes = evidence_modes_validator(binding)
    if list(executed_modes) != binding["evidence_modes"]:
        raise JobContractError(
            "scientific Job evidence modes are not canonical"
        )
    planned_claims = binding["planned_claims"]
    if (
        not isinstance(planned_claims, list)
        or not planned_claims
        or len(set(planned_claims)) != len(planned_claims)
    ):
        raise JobContractError(
            "scientific Job claims must be preregistered"
        )
    for claim in planned_claims:
        _require_ascii("scientific claim", claim)
    result_output = binding["result_manifest_output"]
    if output_classes.get(result_output) != "durable_evidence":
        raise JobContractError("scientific result manifest must be durable")
    if _durable_output_count(output_classes) < 2:
        raise JobContractError(
            "scientific Job requires result and measurement artifacts"
        )
    if evidence_subject["kind"] != "Executable":
        raise JobContractError(
            "scientific Job must bind an Executable"
        )


def _validate_component_parity_binding(
    binding: object,
    *,
    evidence_subject: Mapping[str, str],
    input_hashes: Sequence[str],
    output_classes: Mapping[str, str],
) -> None:
    if binding is None:
        return
    required_fields = {
        "architecture_chassis_identity",
        "canonical_component_id",
        "canonical_component_manifest",
        "dimensions",
        "equivalent_component_id",
        "equivalent_component_manifest",
        "portfolio_axis_identity",
        "portfolio_decision_id",
        "portfolio_snapshot_id",
        "result_manifest_output",
        "validation_plan_hash",
        "validator_id",
    }
    if not isinstance(binding, dict) or set(binding) != required_fields:
        raise JobContractError(
            "component parity binding schema is invalid"
        )
    _validate_validator_binding(binding, input_hashes=input_hashes)
    from axiom_rift.research.chassis import (
        ComponentParityDimension,
        component_semantic_surface_identity,
    )

    expected_dimensions = sorted(
        value.value for value in ComponentParityDimension
    )
    if binding["dimensions"] != expected_dimensions:
        raise JobContractError(
            "component parity must preregister every typed dimension"
        )
    manifests: list[dict[str, Any]] = []
    component_ids: list[str] = []
    for prefix in ("canonical", "equivalent"):
        component_id = binding[f"{prefix}_component_id"]
        manifest = binding[f"{prefix}_component_manifest"]
        if not isinstance(manifest, dict):
            raise JobContractError(
                "component parity manifest is malformed"
            )
        expected_id = "component:" + canonical_digest(
            domain="component",
            payload=manifest,
        )
        if component_id != expected_id:
            raise JobContractError(
                "component parity endpoint differs from its exact manifest"
            )
        component_ids.append(component_id)
        manifests.append(manifest)
    if component_ids[0] == component_ids[1]:
        raise JobContractError(
            "component parity endpoints must be distinct"
        )
    protocols = [manifest.get("protocol") for manifest in manifests]
    if any(not isinstance(value, str) for value in protocols) or (
        protocols[0].split(".", 1)[0]
        != protocols[1].split(".", 1)[0]
    ):
        raise JobContractError(
            "component parity cannot cross protocol domains"
        )
    if (
        protocols[0] != protocols[1]
        and component_semantic_surface_identity(manifests[0])
        == component_semantic_surface_identity(manifests[1])
    ):
        raise JobContractError(
            "protocol-only component identity bumps cannot receive parity"
        )
    for component_id in component_ids:
        component_digest = component_id.removeprefix("component:")
        _require_digest("component parity input", component_digest)
        if component_digest not in input_hashes:
            raise JobContractError(
                "component parity endpoints must be content-bound Job inputs"
            )
    for name in (
        "architecture_chassis_identity",
        "portfolio_axis_identity",
        "portfolio_decision_id",
        "portfolio_snapshot_id",
    ):
        _require_ascii(name, binding[name])
    result_output = binding["result_manifest_output"]
    if output_classes.get(result_output) != "durable_evidence":
        raise JobContractError(
            "component parity result manifest must be durable"
        )
    if _durable_output_count(output_classes) < 2:
        raise JobContractError(
            "component parity requires result and measurement artifacts"
        )
    if evidence_subject["kind"] != "Mission":
        raise JobContractError(
            "component parity Job must bind the Mission"
        )


def _validate_runtime_binding(
    binding: object,
    *,
    evidence_subject: Mapping[str, str],
    input_hashes: Sequence[str],
    output_classes: Mapping[str, str],
) -> None:
    if binding is None:
        return
    from axiom_rift.runtime.guards import (
        EvidenceDepth,
        REQUIRED_CASES,
        REQUIRED_PARITY,
        REQUIRED_RELEASE_ARTIFACT_ROLES,
    )

    if not isinstance(binding, dict) or set(binding) != {
        "action",
        "evidence_depth",
        "planned_materialization_cases",
        "planned_parity_surfaces",
        "planned_source_lifecycle_coverage_ids",
        "result_manifest_output",
        "artifact_roles",
        "numeric_tolerances",
        "validation_plan_hash",
        "validator_id",
    }:
        raise JobContractError("runtime_binding has an invalid schema")
    _validate_validator_binding(binding, input_hashes=input_hashes)
    action = binding["action"]
    depth = binding["evidence_depth"]
    expected_action = {
        EvidenceDepth.EXECUTION_PROOF.value: "run_execution_proof",
        EvidenceDepth.MATERIALIZATION.value: "materialize",
    }.get(depth)
    if action != expected_action:
        raise JobContractError(
            "runtime Job action and evidence depth conflict"
        )
    parity = binding["planned_parity_surfaces"]
    cases = binding["planned_materialization_cases"]
    lifecycle_coverage_ids = binding[
        "planned_source_lifecycle_coverage_ids"
    ]
    if (
        not isinstance(parity, list)
        or any(type(item) is not str for item in parity)
        or len(set(parity)) != len(parity)
        or not set(parity).issubset(REQUIRED_PARITY)
        or not isinstance(cases, list)
        or any(type(item) is not str for item in cases)
        or len(set(cases)) != len(cases)
        or not set(cases).issubset(REQUIRED_CASES)
        or not isinstance(lifecycle_coverage_ids, list)
        or lifecycle_coverage_ids != sorted(set(lifecycle_coverage_ids))
        or any(
            type(item) is not str
            or not item.startswith("source-lifecycle-coverage:")
            or len(item) != 90
            for item in lifecycle_coverage_ids
        )
    ):
        raise JobContractError("runtime Job planned claims are invalid")
    if depth == EvidenceDepth.EXECUTION_PROOF.value and (
        not parity or cases
    ):
        raise JobContractError(
            "execution proof must preregister parity only"
        )
    if depth == EvidenceDepth.MATERIALIZATION.value and (
        not cases or parity
    ):
        raise JobContractError(
            "materialization must preregister cases only"
        )
    if evidence_subject["kind"] != "Executable":
        raise JobContractError("runtime Job must bind an Executable")
    if _durable_output_count(output_classes) < 1:
        raise JobContractError(
            "runtime Job requires durable evidence output"
        )
    result_output = binding["result_manifest_output"]
    if (
        type(result_output) is not str
        or output_classes.get(result_output) != "durable_evidence"
    ):
        raise JobContractError(
            "runtime Job result manifest must be a declared durable output"
        )
    if _durable_output_count(output_classes) < 2:
        raise JobContractError(
            "runtime Job requires a result manifest and measurement artifact"
        )
    tolerances = binding["numeric_tolerances"]
    if not isinstance(tolerances, dict):
        raise JobContractError(
            "runtime numeric tolerances must be preregistered"
        )
    canonical_bytes(tolerances)
    artifact_roles = binding["artifact_roles"]
    if (
        not isinstance(artifact_roles, dict)
        or not artifact_roles
        or not set(artifact_roles).issubset(REQUIRED_RELEASE_ARTIFACT_ROLES)
        or len(set(artifact_roles.values())) != len(artifact_roles)
    ):
        raise JobContractError("runtime artifact roles are invalid")
    for role, output_name in artifact_roles.items():
        _require_ascii("runtime artifact role", role)
        _require_ascii("runtime artifact output", output_name)
        if (
            output_name == result_output
            or output_classes.get(output_name) != "durable_evidence"
        ):
            raise JobContractError(
                "runtime artifact roles require distinct durable outputs"
            )


def validate_job_spec(
    spec: Mapping[str, Any],
    *,
    evidence_modes_validator: EvidenceModesValidator,
) -> None:
    """Validate a normalized Job spec without reading or mutating state."""

    input_hashes, output_classes, evidence_subject = _validate_job_core(spec)
    bindings = (
        spec.get("component_parity_binding"),
        spec.get("runtime_binding"),
        spec.get("scientific_binding"),
        spec.get("source_binding"),
        spec.get("external_dependency_binding"),
    )
    if sum(binding is not None for binding in bindings) > 1:
        raise JobContractError("Job cannot mix evidence-domain bindings")
    scientific_binding = spec.get("scientific_binding")
    _validate_holdout_binding(
        spec.get("holdout_binding"),
        scientific_binding=scientific_binding,
        evidence_subject=evidence_subject,
        input_hashes=input_hashes,
    )
    _validate_external_binding(
        spec.get("external_dependency_binding"),
        evidence_subject=evidence_subject,
        input_hashes=input_hashes,
        output_classes=output_classes,
    )
    _validate_source_binding(
        spec.get("source_binding"),
        input_hashes=input_hashes,
        output_classes=output_classes,
    )
    _validate_scientific_binding(
        scientific_binding,
        evidence_subject=evidence_subject,
        input_hashes=input_hashes,
        output_classes=output_classes,
        evidence_modes_validator=evidence_modes_validator,
    )
    _validate_component_parity_binding(
        spec.get("component_parity_binding"),
        evidence_subject=evidence_subject,
        input_hashes=input_hashes,
        output_classes=output_classes,
    )
    _validate_runtime_binding(
        spec.get("runtime_binding"),
        evidence_subject=evidence_subject,
        input_hashes=input_hashes,
        output_classes=output_classes,
    )


__all__ = [
    "EngineeringCauseBuilder",
    "EvidenceVerifier",
    "EvidenceModesValidator",
    "JobContractError",
    "JobIdentityPlan",
    "build_job_identity_plan",
    "canonical_job_output_identity",
    "canonical_worker_claim_identity",
    "normalize_job_spec",
    "normalize_job_failure_manifest",
    "require_job_output_namespace",
    "validate_job_spec",
]
