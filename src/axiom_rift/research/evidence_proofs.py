"""Typed routing for durable scientific evidence proofs.

This module owns only common proof requirements, measurement references, and
protocol dispatch.  Domain recomputation lives behind cohesive validators:
P0 selected-set audit logic in :mod:`audit_integrity_proof` and atomic trace
calculation in :mod:`scientific_trace`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.audit_integrity_proof import (
    AUDIT_INTEGRITY_MODE,
    AUDIT_STATISTICAL_PROOF_KIND,
    AUDIT_SUPPORT_PROOF_KIND,
    P0_FOREST_SUPPORT_SCHEMA,
    SELECTION_STATISTICAL_SCHEMA,
    AuditIntegrityProofError,
    validate_p0_audit_pair,
    validate_statistical_manifest,
)
from axiom_rift.research.scientific_trace import (
    ANALOG_STATE_TRACE_PROTOCOL_ID,
    ATOMIC_TRACE_PROOF_KIND,
    CALCULATION_PROOF_KIND,
    SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
    ScientificTraceError,
    trace_proof_kinds,
    validate_trace_calculation_pair,
)


TERMINAL_EVIDENCE_MODES = frozenset(
    {
        "causal_contrast",
        "cost_and_execution",
        "sensitivity_or_stress",
        "temporal_stability",
    }
)
NON_TERMINAL_EVIDENCE_MODES = frozenset({AUDIT_INTEGRITY_MODE})

SCIENTIFIC_MODE_PROOF_SCHEMA = "scientific_evidence_mode_proof.v1"
FIXED_HOLD_FAMILY_TRACE_SCHEMA = "fixed_hold_family_trace.v4"
FIXED_HOLD_FAMILY_TRACE_PROOF_KIND = "atomic_fixed_hold_family_trace.v1"
PAIRED_CONTROL_PROOF_KIND = "paired_control_contrast.v1"
COST_EXECUTION_PROOF_KIND = "cost_execution_observation.v1"
SENSITIVITY_STRESS_PROOF_KIND = "sensitivity_stress_observation.v1"
TEMPORAL_STABILITY_PROOF_KIND = "temporal_stability_observation.v1"

_REQUIREMENT_FIELDS = {
    "artifact_schema",
    "evidence_mode",
    "output_name",
    "proof_kind",
}
_REFERENCE_FIELDS = _REQUIREMENT_FIELDS | {"sha256"}
_MODE_PROOF_FIELDS = {
    "evidence_mode",
    "executable_id",
    "job_hash",
    "job_id",
    "mission_id",
    "proof",
    "proof_kind",
    "schema",
}
_METRIC_BINDING_FIELDS = {"claim_id", "metric", "value"}
_PROOF_KINDS_BY_MODE = {
    AUDIT_INTEGRITY_MODE: {
        AUDIT_SUPPORT_PROOF_KIND: P0_FOREST_SUPPORT_SCHEMA,
        AUDIT_STATISTICAL_PROOF_KIND: SELECTION_STATISTICAL_SCHEMA,
    },
    "causal_contrast": {
        PAIRED_CONTROL_PROOF_KIND: SCIENTIFIC_MODE_PROOF_SCHEMA,
    },
    "cost_and_execution": {
        COST_EXECUTION_PROOF_KIND: SCIENTIFIC_MODE_PROOF_SCHEMA,
    },
    "sensitivity_or_stress": {
        SENSITIVITY_STRESS_PROOF_KIND: SCIENTIFIC_MODE_PROOF_SCHEMA,
    },
    "temporal_stability": {
        TEMPORAL_STABILITY_PROOF_KIND: SCIENTIFIC_MODE_PROOF_SCHEMA,
    },
}
_ATOMIC_TRACE_PROOF_KINDS = frozenset(
    {ATOMIC_TRACE_PROOF_KIND, FIXED_HOLD_FAMILY_TRACE_PROOF_KIND}
)


class ScientificEvidenceProofError(ValueError):
    """A scientific proof is absent, forged, incomplete, or misrouted."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ScientificEvidenceProofError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise ScientificEvidenceProofError(f"{name} must be a SHA-256 digest")
    return text


def _identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    head, separator, digest = text.partition(":")
    if not separator or head != prefix:
        raise ScientificEvidenceProofError(f"{name} has the wrong identity domain")
    _digest(f"{name} digest", digest)
    return text


def _mapping(name: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ScientificEvidenceProofError(f"{name} must be a mapping")
    return value


def _sequence(
    name: str,
    value: object,
    *,
    allow_empty: bool = False,
) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)) or (not value and not allow_empty):
        raise ScientificEvidenceProofError(f"{name} must be a sequence")
    return value


def _positive_int(name: str, value: object, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise ScientificEvidenceProofError(
            f"{name} must be at least {minimum}"
        )
    return value


@dataclass(frozen=True, slots=True)
class ProofRequirement:
    artifact_schema: str
    evidence_mode: str
    output_name: str
    proof_kind: str

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return self.evidence_mode, self.proof_kind, self.output_name

    def manifest(self) -> dict[str, str]:
        return {
            "artifact_schema": self.artifact_schema,
            "evidence_mode": self.evidence_mode,
            "output_name": self.output_name,
            "proof_kind": self.proof_kind,
        }


@dataclass(frozen=True, slots=True)
class ProofReference:
    artifact_schema: str
    evidence_mode: str
    output_name: str
    proof_kind: str
    sha256: str

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return self.evidence_mode, self.proof_kind, self.output_name

    def manifest(self) -> dict[str, str]:
        return {
            "artifact_schema": self.artifact_schema,
            "evidence_mode": self.evidence_mode,
            "output_name": self.output_name,
            "proof_kind": self.proof_kind,
            "sha256": self.sha256,
        }


def _trace_kinds(evidence_mode: str) -> dict[str, str]:
    try:
        return trace_proof_kinds(
            protocol_id=ANALOG_STATE_TRACE_PROTOCOL_ID,
            evidence_mode=evidence_mode,
        )
    except ScientificTraceError as exc:
        raise ScientificEvidenceProofError(
            "scientific trace proof protocol is invalid"
        ) from exc


def _trace_kind_alternatives(
    evidence_mode: str,
) -> tuple[dict[str, str], ...]:
    """Return legacy subject-bound and shared fixed-hold proof pairs."""

    return (
        _trace_kinds(evidence_mode),
        {
            FIXED_HOLD_FAMILY_TRACE_PROOF_KIND: (
                FIXED_HOLD_FAMILY_TRACE_SCHEMA
            ),
            CALCULATION_PROOF_KIND: SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
        },
    )


def proof_requirements_for_modes(
    *,
    evidence_modes: tuple[str, ...],
    output_names: Mapping[str, str],
    proof_protocol_id: str | None = None,
) -> tuple[dict[str, str], ...]:
    """Build exact proof requirements for one selected protocol."""

    requirements: list[ProofRequirement] = []
    for mode in evidence_modes:
        if proof_protocol_id is None and mode in TERMINAL_EVIDENCE_MODES:
            raise ScientificEvidenceProofError(
                "terminal scientific evidence requires a registered atomic "
                "trace protocol"
            )
        if proof_protocol_id is None:
            kinds = _PROOF_KINDS_BY_MODE.get(mode)
        else:
            try:
                kinds = trace_proof_kinds(
                    protocol_id=proof_protocol_id,
                    evidence_mode=mode,
                )
            except ScientificTraceError as exc:
                raise ScientificEvidenceProofError(
                    "scientific trace proof protocol is invalid"
                ) from exc
        if kinds is None:
            raise ScientificEvidenceProofError(
                "scientific evidence mode has no typed proof boundary"
            )
        for proof_kind, artifact_schema in kinds.items():
            output_name = output_names.get(proof_kind)
            if output_name is None:
                raise ScientificEvidenceProofError(
                    "scientific proof output is not preregistered"
                )
            requirements.append(
                ProofRequirement(
                    artifact_schema=artifact_schema,
                    evidence_mode=mode,
                    output_name=_ascii("proof output_name", output_name),
                    proof_kind=proof_kind,
                )
            )
    return tuple(
        item.manifest()
        for item in sorted(requirements, key=lambda item: item.sort_key)
    )


def parse_proof_requirements(
    value: object,
    *,
    evidence_modes: tuple[str, ...],
) -> tuple[ProofRequirement, ...]:
    requirements: list[ProofRequirement] = []
    for raw in _sequence("scientific proof requirements", value):
        item = _mapping("scientific proof requirement", raw)
        if set(item) != _REQUIREMENT_FIELDS:
            raise ScientificEvidenceProofError("proof requirement schema is invalid")
        requirement = ProofRequirement(
            artifact_schema=_ascii("proof artifact_schema", item["artifact_schema"]),
            evidence_mode=_ascii("proof evidence_mode", item["evidence_mode"]),
            output_name=_ascii("proof output_name", item["output_name"]),
            proof_kind=_ascii("proof kind", item["proof_kind"]),
        )
        if requirement.evidence_mode in TERMINAL_EVIDENCE_MODES:
            known: dict[str, str] = {}
            for alternative in _trace_kind_alternatives(
                requirement.evidence_mode
            ):
                known.update(alternative)
        else:
            known = dict(
                _PROOF_KINDS_BY_MODE.get(requirement.evidence_mode, {})
            )
        if known.get(requirement.proof_kind) != requirement.artifact_schema:
            raise ScientificEvidenceProofError(
                "proof kind is invalid for its evidence mode"
            )
        requirements.append(requirement)
    normalized = tuple(requirements)
    if tuple(item.sort_key for item in normalized) != tuple(
        sorted(item.sort_key for item in normalized)
    ):
        raise ScientificEvidenceProofError("proof requirements are not canonical")
    output_kinds: dict[str, set[tuple[str, str]]] = {}
    grouped: dict[str, set[tuple[str, str]]] = {}
    for item in normalized:
        output_kinds.setdefault(item.output_name, set()).add(
            (item.proof_kind, item.artifact_schema)
        )
        grouped.setdefault(item.evidence_mode, set()).add(
            (item.proof_kind, item.artifact_schema)
        )
    if any(len(values) != 1 for values in output_kinds.values()):
        raise ScientificEvidenceProofError(
            "one output cannot impersonate different proof kinds"
        )
    if set(grouped) != set(evidence_modes):
        raise ScientificEvidenceProofError(
            "proof requirements do not exactly cover evidence modes"
        )
    for mode in evidence_modes:
        if mode in TERMINAL_EVIDENCE_MODES:
            alternatives = [
                set(value.items())
                for value in _trace_kind_alternatives(mode)
            ]
        else:
            alternatives = [set(_PROOF_KINDS_BY_MODE.get(mode, {}).items())]
        if grouped[mode] not in alternatives:
            raise ScientificEvidenceProofError(
                "proof requirements mix incompatible protocols"
            )
    return normalized


def build_proof_references(
    *,
    requirements: tuple[ProofRequirement, ...],
    artifact_hashes: Mapping[str, str],
) -> tuple[dict[str, str], ...]:
    return tuple(
        ProofReference(
            **requirement.manifest(),
            sha256=_digest(
                "proof artifact hash", artifact_hashes.get(requirement.output_name)
            ),
        ).manifest()
        for requirement in requirements
    )


def parse_proof_references(
    value: object,
    *,
    requirements: tuple[ProofRequirement, ...],
) -> tuple[ProofReference, ...]:
    references: list[ProofReference] = []
    for raw in _sequence("scientific proof references", value):
        item = _mapping("scientific proof reference", raw)
        if set(item) != _REFERENCE_FIELDS:
            raise ScientificEvidenceProofError("proof reference schema is invalid")
        references.append(
            ProofReference(
                artifact_schema=_ascii(
                    "proof artifact_schema", item["artifact_schema"]
                ),
                evidence_mode=_ascii("proof evidence_mode", item["evidence_mode"]),
                output_name=_ascii("proof output_name", item["output_name"]),
                proof_kind=_ascii("proof kind", item["proof_kind"]),
                sha256=_digest("proof artifact hash", item["sha256"]),
            )
        )
    if len(references) != len(requirements):
        raise ScientificEvidenceProofError(
            "proof references differ from preregistration"
        )
    for reference, requirement in zip(references, requirements, strict=True):
        if (
            reference.sort_key != requirement.sort_key
            or reference.artifact_schema != requirement.artifact_schema
        ):
            raise ScientificEvidenceProofError("proof reference metadata drifted")
    return tuple(references)


def _normalized_metric_bindings(
    value: object,
) -> tuple[dict[str, object], ...]:
    bindings: list[dict[str, object]] = []
    for raw in _sequence("proof metric_bindings", value, allow_empty=True):
        item = _mapping("proof metric binding", raw)
        if set(item) != _METRIC_BINDING_FIELDS:
            raise ScientificEvidenceProofError(
                "proof metric binding schema is invalid"
            )
        metric_value = item["value"]
        if metric_value is not None and type(metric_value) is not int:
            raise ScientificEvidenceProofError(
                "proof metric value must be integer or null"
            )
        bindings.append(
            {
                "claim_id": _ascii("proof claim_id", item["claim_id"]),
                "metric": _ascii("proof metric", item["metric"]),
                "value": metric_value,
            }
        )
    keys = tuple((item["claim_id"], item["metric"]) for item in bindings)
    if keys != tuple(sorted(set(keys))):
        raise ScientificEvidenceProofError(
            "proof metric bindings must be sorted and unique"
        )
    return tuple(bindings)


def build_mode_proof(
    *,
    evidence_mode: str,
    proof_kind: str,
    mission_id: str,
    executable_id: str,
    job_id: str,
    job_hash: str,
    proof: Mapping[str, object],
) -> dict[str, object]:
    value = {
        "evidence_mode": evidence_mode,
        "executable_id": executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "mission_id": mission_id,
        "proof": dict(proof),
        "proof_kind": proof_kind,
        "schema": SCIENTIFIC_MODE_PROOF_SCHEMA,
    }
    _validate_mode_proof_envelope(
        value,
        evidence_mode=evidence_mode,
        proof_kind=proof_kind,
        mission_id=mission_id,
        executable_id=executable_id,
        job_id=job_id,
        job_hash=job_hash,
        expected_metric_bindings=_normalized_metric_bindings(
            proof.get("metric_bindings", [])
        ),
    )
    canonical_bytes(value)
    return value


def _validate_mode_proof_envelope(
    value: object,
    *,
    evidence_mode: str,
    proof_kind: str,
    mission_id: str,
    executable_id: str,
    job_id: str,
    job_hash: str,
    expected_metric_bindings: tuple[dict[str, object], ...],
) -> None:
    item = _mapping("scientific mode proof", value)
    if set(item) != _MODE_PROOF_FIELDS or item.get("schema") != SCIENTIFIC_MODE_PROOF_SCHEMA:
        raise ScientificEvidenceProofError("mode proof schema is invalid")
    observed = (
        _ascii("mode", item["evidence_mode"]),
        _ascii("proof kind", item["proof_kind"]),
        _ascii("mission", item["mission_id"]),
        _ascii("executable", item["executable_id"]),
        _ascii("job", item["job_id"]),
        _digest("job hash", item["job_hash"]),
    )
    if observed != (
        evidence_mode,
        proof_kind,
        mission_id,
        executable_id,
        job_id,
        job_hash,
    ):
        raise ScientificEvidenceProofError("mode proof belongs to another execution")
    proof = _mapping("mode proof payload", item["proof"])
    if _normalized_metric_bindings(proof.get("metric_bindings")) != expected_metric_bindings:
        raise ScientificEvidenceProofError("mode proof metrics differ from measurement")
    if proof_kind == PAIRED_CONTROL_PROOF_KIND:
        if set(proof) != {
            "calendar_identity",
            "control_executable_id",
            "delta_metric",
            "metric_bindings",
            "paired_observation_count",
            "subject_executable_id",
            "uncertainty_metric",
        }:
            raise ScientificEvidenceProofError("paired control proof is incomplete")
        if proof["subject_executable_id"] != executable_id or proof["control_executable_id"] == executable_id:
            raise ScientificEvidenceProofError("paired subject or control is invalid")
        _identity("paired calendar", proof["calendar_identity"], "calendar")
        _positive_int("paired observations", proof["paired_observation_count"], minimum=2)
        _ascii("paired delta metric", proof["delta_metric"])
        _ascii("paired uncertainty metric", proof["uncertainty_metric"])
    elif proof_kind == COST_EXECUTION_PROOF_KIND:
        if set(proof) != {
            "cost_contract",
            "metric_bindings",
            "native_cost_observation_count",
            "stress_cost_observation_count",
            "unresolved_cost_observation_count",
        }:
            raise ScientificEvidenceProofError("cost proof is incomplete")
        _ascii("cost contract", proof["cost_contract"])
        _positive_int("native observations", proof["native_cost_observation_count"])
        _positive_int("stress observations", proof["stress_cost_observation_count"])
        if proof["unresolved_cost_observation_count"] != 0:
            raise ScientificEvidenceProofError("cost proof retains unresolved costs")
    elif proof_kind == SENSITIVITY_STRESS_PROOF_KIND:
        if set(proof) != {"metric_bindings", "scenario_count", "stress_dimensions"}:
            raise ScientificEvidenceProofError("sensitivity proof is incomplete")
        _positive_int("stress scenarios", proof["scenario_count"], minimum=2)
        dimensions = tuple(
            _ascii("stress dimension", dimension)
            for dimension in _sequence("stress dimensions", proof["stress_dimensions"])
        )
        if dimensions != tuple(sorted(set(dimensions))):
            raise ScientificEvidenceProofError("stress dimensions are not canonical")
    elif proof_kind == TEMPORAL_STABILITY_PROOF_KIND:
        if set(proof) != {
            "calendar_identity",
            "metric_bindings",
            "observation_count",
            "window_count",
        }:
            raise ScientificEvidenceProofError("temporal proof is incomplete")
        _identity("temporal calendar", proof["calendar_identity"], "calendar")
        _positive_int("temporal observations", proof["observation_count"], minimum=2)
        _positive_int("temporal windows", proof["window_count"], minimum=2)
    else:
        raise ScientificEvidenceProofError("mode proof kind is unknown")


def _validate_statistical_manifest(
    statistical: Mapping[str, Any],
) -> dict[str, Any]:
    """Backward-compatible facade for the audit-specific recomputer."""

    try:
        return validate_statistical_manifest(statistical)
    except AuditIntegrityProofError as exc:
        raise ScientificEvidenceProofError(str(exc)) from exc


def validate_proof_artifacts(
    *,
    requirements: tuple[ProofRequirement, ...],
    references: tuple[ProofReference, ...],
    artifacts: Mapping[str, Mapping[str, Any]],
    artifact_hashes: Mapping[str, str],
    expected_metric_bindings_by_mode: Mapping[
        str, tuple[dict[str, object], ...]
    ],
    mission_id: str,
    executable_id: str,
    job_id: str,
    job_hash: str,
) -> tuple[str, ...]:
    """Open exact proof inventory and dispatch each selected protocol."""

    if any(
        item.evidence_mode in TERMINAL_EVIDENCE_MODES
        and item.proof_kind
        not in (_ATOMIC_TRACE_PROOF_KINDS | {CALCULATION_PROOF_KIND})
        for item in requirements
    ):
        raise ScientificEvidenceProofError(
            "terminal scientific evidence requires an atomic trace and "
            "calculation proof"
        )
    expected_outputs = {item.output_name for item in requirements}
    if set(artifacts) != expected_outputs or set(artifact_hashes) != expected_outputs:
        raise ScientificEvidenceProofError("proof artifact inventory drifted")
    reference_by_key = {item.sort_key: item for item in references}
    if len(reference_by_key) != len(references):
        raise ScientificEvidenceProofError("proof references are not unique")
    for requirement in requirements:
        reference = reference_by_key.get(requirement.sort_key)
        if reference is None:
            raise ScientificEvidenceProofError("proof reference is absent")
        if _digest(
            "opened proof hash", artifact_hashes[requirement.output_name]
        ) != reference.sha256:
            raise ScientificEvidenceProofError(
                "opened proof differs from measurement reference"
            )
        if artifacts[requirement.output_name].get("schema") != requirement.artifact_schema:
            raise ScientificEvidenceProofError("opened proof schema drifted")
    demonstrated: set[str] = set()
    trace_requirements = tuple(
        item
        for item in requirements
        if item.proof_kind in (
            _ATOMIC_TRACE_PROOF_KINDS | {CALCULATION_PROOF_KIND}
        )
    )
    if trace_requirements:
        modes = tuple(sorted({item.evidence_mode for item in trace_requirements}))
        if len(trace_requirements) != 2 * len(modes):
            raise ScientificEvidenceProofError("atomic trace pair is incomplete")
        trace_outputs = {
            item.output_name
            for item in trace_requirements
            if item.proof_kind in _ATOMIC_TRACE_PROOF_KINDS
        }
        calculation_outputs = {
            item.output_name
            for item in trace_requirements
            if item.proof_kind == CALCULATION_PROOF_KIND
        }
        if len(trace_outputs) != 1 or len(calculation_outputs) != 1:
            raise ScientificEvidenceProofError(
                "atomic protocol requires one shared trace/calculation pair"
            )
        trace_output = next(iter(trace_outputs))
        calculation_output = next(iter(calculation_outputs))
        try:
            trace_kinds = {
                item.proof_kind
                for item in trace_requirements
                if item.proof_kind in _ATOMIC_TRACE_PROOF_KINDS
            }
            if len(trace_kinds) != 1:
                raise ScientificTraceError(
                    "atomic trace proof kinds are mixed"
                )
            arguments = {
                "trace": artifacts[trace_output],
                "trace_output_name": trace_output,
                "trace_hash": artifact_hashes[trace_output],
                "calculation": artifacts[calculation_output],
                "expected_evidence_modes": modes,
                "expected_metric_bindings_by_mode": {
                    mode: expected_metric_bindings_by_mode.get(mode, ())
                    for mode in modes
                },
                "mission_id": mission_id,
                "executable_id": executable_id,
                "job_id": job_id,
                "job_hash": job_hash,
            }
            if trace_kinds == {FIXED_HOLD_FAMILY_TRACE_PROOF_KIND}:
                from axiom_rift.research.fixed_hold_shared_trace import (
                    validate_fixed_hold_shared_trace_pair,
                )

                validated_modes = validate_fixed_hold_shared_trace_pair(
                    **arguments
                )
            else:
                validated_modes = validate_trace_calculation_pair(
                    **arguments
                )
            demonstrated.update(validated_modes)
        except ScientificTraceError as exc:
            raise ScientificEvidenceProofError(
                "atomic scientific trace calculation is invalid"
            ) from exc
    audit = tuple(
        item for item in requirements if item.evidence_mode == AUDIT_INTEGRITY_MODE
    )
    if audit:
        by_kind = {item.proof_kind: item for item in audit}
        if set(by_kind) != {
            AUDIT_SUPPORT_PROOF_KIND,
            AUDIT_STATISTICAL_PROOF_KIND,
        }:
            raise ScientificEvidenceProofError("audit proof pair is incomplete")
        support = by_kind[AUDIT_SUPPORT_PROOF_KIND]
        statistical = by_kind[AUDIT_STATISTICAL_PROOF_KIND]
        try:
            derived = validate_p0_audit_pair(
                support=artifacts[support.output_name],
                support_hash=artifact_hashes[support.output_name],
                statistical=artifacts[statistical.output_name],
                statistical_hash=artifact_hashes[statistical.output_name],
                mission_id=mission_id,
                executable_id=executable_id,
                job_id=job_id,
                job_hash=job_hash,
            )
        except AuditIntegrityProofError as exc:
            raise ScientificEvidenceProofError(str(exc)) from exc
        for binding in expected_metric_bindings_by_mode.get(AUDIT_INTEGRITY_MODE, ()):
            if derived.get(str(binding["metric"])) != binding["value"]:
                raise ScientificEvidenceProofError(
                    "audit measurement is not derived from durable proofs"
                )
        demonstrated.add(AUDIT_INTEGRITY_MODE)
    for requirement in requirements:
        if requirement.evidence_mode == AUDIT_INTEGRITY_MODE or requirement.proof_kind in {
            CALCULATION_PROOF_KIND,
        } | _ATOMIC_TRACE_PROOF_KINDS:
            continue
        _validate_mode_proof_envelope(
            artifacts[requirement.output_name],
            evidence_mode=requirement.evidence_mode,
            proof_kind=requirement.proof_kind,
            mission_id=mission_id,
            executable_id=executable_id,
            job_id=job_id,
            job_hash=job_hash,
            expected_metric_bindings=expected_metric_bindings_by_mode.get(
                requirement.evidence_mode, ()
            ),
        )
        demonstrated.add(requirement.evidence_mode)
    return tuple(sorted(demonstrated))


__all__ = [
    "AUDIT_INTEGRITY_MODE",
    "AUDIT_STATISTICAL_PROOF_KIND",
    "AUDIT_SUPPORT_PROOF_KIND",
    "ATOMIC_TRACE_PROOF_KIND",
    "CALCULATION_PROOF_KIND",
    "COST_EXECUTION_PROOF_KIND",
    "FIXED_HOLD_FAMILY_TRACE_PROOF_KIND",
    "FIXED_HOLD_FAMILY_TRACE_SCHEMA",
    "NON_TERMINAL_EVIDENCE_MODES",
    "P0_FOREST_SUPPORT_SCHEMA",
    "PAIRED_CONTROL_PROOF_KIND",
    "ProofReference",
    "ProofRequirement",
    "SCIENTIFIC_MODE_PROOF_SCHEMA",
    "SELECTION_STATISTICAL_SCHEMA",
    "SENSITIVITY_STRESS_PROOF_KIND",
    "ScientificEvidenceProofError",
    "TEMPORAL_STABILITY_PROOF_KIND",
    "TERMINAL_EVIDENCE_MODES",
    "_validate_statistical_manifest",
    "build_mode_proof",
    "build_proof_references",
    "parse_proof_references",
    "parse_proof_requirements",
    "proof_requirements_for_modes",
    "validate_proof_artifacts",
]
