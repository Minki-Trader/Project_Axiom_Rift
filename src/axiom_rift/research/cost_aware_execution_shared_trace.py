"""Subject calculations over one content-addressed cost-aware pair trace.

The 84 MB neutral family trace is durable once.  Each Job keeps its own small
calculation, measurement, result, and completion, so sharing bytes never turns
family evidence into sibling scientific authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES,
    CostAwareExecutionProtocolDefinition,
    cost_aware_execution_protocol_definition_from_manifest,
)
from axiom_rift.research.cost_aware_execution_family_inference import (
    CostAwareExecutionFamilyInferenceSnapshot,
    build_cost_aware_execution_family_inference_snapshot,
)
from axiom_rift.research.cost_aware_execution_trace import (
    cost_aware_execution_calculation_parameters,
    validate_cost_aware_execution_pair_trace_snapshot,
)
from axiom_rift.research.cost_aware_execution_trace_snapshot import (
    CostAwareExecutionPairTraceSnapshot,
)
from axiom_rift.research.scientific_trace import (
    SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
    ScientificTraceError,
)


_THIS_FILE = Path(__file__).resolve()
_CALCULATION_FIELDS = {
    "evidence_modes",
    "executable_id",
    "job_hash",
    "job_id",
    "metrics",
    "mission_id",
    "parameters",
    "protocol_definition",
    "protocol_id",
    "schema",
    "statistics",
    "trace",
}


def cost_aware_execution_shared_trace_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ScientificTraceError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ScientificTraceError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _inference(
    *,
    pair: CostAwareExecutionPairTraceSnapshot,
    definition: CostAwareExecutionProtocolDefinition,
    parameters: Mapping[str, Any],
    inference: CostAwareExecutionFamilyInferenceSnapshot | None,
) -> CostAwareExecutionFamilyInferenceSnapshot:
    if inference is None:
        return build_cost_aware_execution_family_inference_snapshot(
            pair_trace=pair,
            definition=definition,
            parameters=parameters,
        )
    return inference.require(
        pair=pair,
        definition=definition,
        parameters=parameters,
    )


def build_cost_aware_execution_shared_trace_calculation(
    *,
    trace: Mapping[str, Any] | CostAwareExecutionPairTraceSnapshot,
    definition: CostAwareExecutionProtocolDefinition,
    mission_id: str,
    executable_id: str,
    job_id: str,
    job_hash: str,
    trace_output_name: str,
    trace_hash: str,
    inference: CostAwareExecutionFamilyInferenceSnapshot | None = None,
) -> dict[str, object]:
    """Build one subject proof without materializing a subject trace copy."""

    pair = validate_cost_aware_execution_pair_trace_snapshot(
        trace,
        definition=definition,
    )
    if _digest("shared cost-aware trace hash", trace_hash) != pair.sha256:
        raise ScientificTraceError(
            "shared cost-aware trace hash differs from the opened trace"
        )
    subject = _ascii("cost-aware executable_id", executable_id)
    if subject not in definition.prospective_executable_ids:
        raise ScientificTraceError("cost-aware subject is outside the exact pair")
    parameters = cost_aware_execution_calculation_parameters(definition)
    family = _inference(
        pair=pair,
        definition=definition,
        parameters=parameters,
        inference=inference,
    )
    metrics, statistics = family.subject(subject)
    value = {
        "evidence_modes": list(COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES),
        "executable_id": subject,
        "job_hash": _digest("cost-aware job_hash", job_hash),
        "job_id": _ascii("cost-aware job_id", job_id),
        "metrics": metrics,
        "mission_id": _ascii("cost-aware mission_id", mission_id),
        "parameters": parameters,
        "protocol_definition": definition.manifest(),
        "protocol_id": definition.protocol_id,
        "schema": SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
        "statistics": statistics,
        "trace": {
            "output_name": _ascii(
                "shared cost-aware trace output_name",
                trace_output_name,
            ),
            "sha256": pair.sha256,
        },
    }
    canonical_bytes(value)
    return value


def validate_cost_aware_execution_shared_trace_calculation(
    *,
    trace: Mapping[str, Any] | CostAwareExecutionPairTraceSnapshot,
    calculation: Mapping[str, Any],
    definition: CostAwareExecutionProtocolDefinition,
    inference: CostAwareExecutionFamilyInferenceSnapshot | None = None,
) -> dict[str, dict[str, int | None]]:
    """Recompute one subject from independently opened family bytes."""

    if not isinstance(calculation, Mapping) or set(calculation) != _CALCULATION_FIELDS:
        raise ScientificTraceError("cost-aware calculation proof schema is invalid")
    if (
        calculation.get("schema") != SCIENTIFIC_CALCULATION_PROOF_SCHEMA
        or calculation.get("protocol_id") != definition.protocol_id
    ):
        raise ScientificTraceError("cost-aware calculation protocol drifted")
    parsed_definition = cost_aware_execution_protocol_definition_from_manifest(
        calculation.get("protocol_definition")
    )
    if parsed_definition.manifest() != definition.manifest():
        raise ScientificTraceError("cost-aware calculation definition drifted")
    pair = validate_cost_aware_execution_pair_trace_snapshot(
        trace,
        definition=definition,
    )
    subject = _ascii(
        "cost-aware calculation executable_id",
        calculation.get("executable_id"),
    )
    if subject not in definition.prospective_executable_ids:
        raise ScientificTraceError("cost-aware calculation subject is outside its pair")
    _ascii("cost-aware calculation mission_id", calculation.get("mission_id"))
    _ascii("cost-aware calculation job_id", calculation.get("job_id"))
    _digest("cost-aware calculation job_hash", calculation.get("job_hash"))
    if tuple(calculation.get("evidence_modes", ())) != (
        COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES
    ):
        raise ScientificTraceError("cost-aware calculation evidence modes drifted")
    reference = calculation.get("trace")
    if (
        not isinstance(reference, Mapping)
        or set(reference) != {"output_name", "sha256"}
        or reference.get("sha256") != pair.sha256
    ):
        raise ScientificTraceError(
            "cost-aware calculation is not bound to the shared pair trace"
        )
    _ascii("cost-aware trace output_name", reference.get("output_name"))
    parameters = cost_aware_execution_calculation_parameters(definition)
    if calculation.get("parameters") != parameters:
        raise ScientificTraceError("cost-aware calculation parameters drifted")
    family = _inference(
        pair=pair,
        definition=definition,
        parameters=parameters,
        inference=inference,
    )
    metrics, statistics = family.subject(subject)
    if calculation.get("metrics") != metrics:
        raise ScientificTraceError("cost-aware metrics drifted from atomic rows")
    if calculation.get("statistics") != statistics:
        raise ScientificTraceError(
            "cost-aware deterministic inference proof drifted"
        )
    return metrics


def validate_cost_aware_execution_shared_trace_pair(
    *,
    trace: Mapping[str, Any] | CostAwareExecutionPairTraceSnapshot,
    trace_output_name: str,
    trace_hash: str,
    calculation: Mapping[str, Any],
    expected_evidence_modes: tuple[str, ...],
    expected_metric_bindings_by_mode: Mapping[
        str, tuple[dict[str, object], ...]
    ],
    mission_id: str,
    executable_id: str,
    job_id: str,
    job_hash: str,
) -> tuple[str, ...]:
    """Validate one subject while scanning and inferring its family once."""

    definition = cost_aware_execution_protocol_definition_from_manifest(
        calculation.get("protocol_definition")
    )
    pair = validate_cost_aware_execution_pair_trace_snapshot(
        trace,
        definition=definition,
    )
    if _digest("shared cost-aware trace hash", trace_hash) != pair.sha256:
        raise ScientificTraceError(
            "shared cost-aware trace hash differs from the opened trace"
        )
    authority = pair.registered_inputs(definition=definition)
    if (
        authority.get("protocol_id") != definition.protocol_id
        or authority.get("protocol_definition") != definition.manifest()
    ):
        raise ScientificTraceError(
            "shared cost-aware trace protocol authority drifted"
        )
    if (
        calculation.get("mission_id") != mission_id
        or calculation.get("executable_id") != executable_id
        or calculation.get("job_id") != job_id
        or calculation.get("job_hash") != job_hash
    ):
        raise ScientificTraceError(
            "shared cost-aware calculation belongs to another execution"
        )
    reference = calculation.get("trace")
    if (
        not isinstance(reference, Mapping)
        or set(reference) != {"output_name", "sha256"}
        or reference.get("output_name") != trace_output_name
        or reference.get("sha256") != pair.sha256
    ):
        raise ScientificTraceError(
            "calculation proof is not bound to the opened shared trace"
        )
    modes = calculation.get("evidence_modes")
    if (
        not isinstance(modes, list)
        or tuple(modes) != expected_evidence_modes
        or tuple(modes) != COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES
        or tuple(modes) != tuple(sorted(set(modes)))
    ):
        raise ScientificTraceError(
            "shared cost-aware evidence modes differ from preregistration"
        )
    parameters = cost_aware_execution_calculation_parameters(definition)
    inference = build_cost_aware_execution_family_inference_snapshot(
        pair_trace=pair,
        definition=definition,
        parameters=parameters,
    )
    derived = validate_cost_aware_execution_shared_trace_calculation(
        trace=pair,
        calculation=calculation,
        definition=definition,
        inference=inference,
    )
    for mode in expected_evidence_modes:
        for binding in expected_metric_bindings_by_mode.get(mode, ()):
            claim_metrics = derived.get(str(binding["claim_id"]))
            if (
                not isinstance(claim_metrics, Mapping)
                or claim_metrics.get(str(binding["metric"]))
                != binding["value"]
            ):
                raise ScientificTraceError(
                    "measurement metric does not recompute from shared trace"
                )
    return expected_evidence_modes


__all__ = [
    "build_cost_aware_execution_shared_trace_calculation",
    "cost_aware_execution_shared_trace_implementation_sha256",
    "validate_cost_aware_execution_shared_trace_calculation",
    "validate_cost_aware_execution_shared_trace_pair",
]
