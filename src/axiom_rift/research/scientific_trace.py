"""Protocol-bound atomic traces and pure scientific recalculation.

The dispatcher is intentionally closed.  A durable calculation artifact names
one registered protocol identifier; it never supplies a formula, import path,
or executable callback.  The validator opens the referenced atomic trace and
invokes the corresponding repository-owned pure recomputer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SCIENTIFIC_EVALUATION_TRACE_SCHEMA = "scientific_evaluation_trace.v1"
SCIENTIFIC_CALCULATION_PROOF_SCHEMA = "scientific_calculation_proof.v1"
ATOMIC_TRACE_PROOF_KIND = "atomic_evaluation_trace.v1"
CALCULATION_PROOF_KIND = "protocol_calculation_proof.v1"
ANALOG_STATE_TRACE_PROTOCOL_ID = "analog_state.concurrent_four_config.v1"
ANALOG_SCOPED_TRACE_PROTOCOL_ID = (
    "analog_state.concurrent_four_config.scoped_query.v2"
)

_TRACE_FIELDS = {
    "adapter_implementation_sha256",
    "attribution",
    "controls",
    "dataset_sha256",
    "eligible_day_observations",
    "family_id",
    "invariance_comparisons",
    "intent_observations",
    "job_hash",
    "job_id",
    "material_identity",
    "mission_id",
    "ordered_family",
    "protocol_id",
    "schema",
    "split_artifact_sha256",
    "subject_executable_id",
    "trade_observations",
    "windows",
}
_CALCULATION_FIELDS = {
    "evidence_modes",
    "executable_id",
    "job_hash",
    "job_id",
    "metrics",
    "mission_id",
    "parameters",
    "protocol_id",
    "schema",
    "statistics",
    "trace",
}


class ScientificTraceError(ValueError):
    """A trace or protocol calculation is absent, forged, or inconsistent."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ScientificTraceError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ScientificTraceError(f"{name} must be a lowercase SHA-256 digest")
    return text


def trace_proof_kinds(
    *, protocol_id: str, evidence_mode: str
) -> dict[str, str]:
    """Return the closed proof pair for one supported protocol and mode."""

    if protocol_id not in {
        ANALOG_STATE_TRACE_PROTOCOL_ID,
        ANALOG_SCOPED_TRACE_PROTOCOL_ID,
    }:
        raise ScientificTraceError("scientific trace protocol is not registered")
    if evidence_mode not in {
        "causal_contrast",
        "cost_and_execution",
        "sensitivity_or_stress",
        "temporal_stability",
    }:
        raise ScientificTraceError(
            "scientific trace protocol cannot demonstrate this evidence mode"
        )
    return {
        ATOMIC_TRACE_PROOF_KIND: SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
        CALCULATION_PROOF_KIND: SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
    }


def _common_identity(
    *,
    value: Mapping[str, Any],
    mission_id: str,
    executable_id: str,
    job_id: str,
    job_hash: str,
) -> None:
    if (
        value.get("mission_id") != mission_id
        or value.get("job_id") != job_id
        or value.get("job_hash") != job_hash
        or value.get("subject_executable_id", value.get("executable_id"))
        != executable_id
    ):
        raise ScientificTraceError(
            "scientific trace calculation belongs to another execution"
        )
    _ascii("trace mission_id", value.get("mission_id"))
    _ascii("trace job_id", value.get("job_id"))
    _digest("trace job_hash", value.get("job_hash"))
    _ascii("trace executable_id", executable_id)


def validate_trace_calculation_pair(
    *,
    trace: Mapping[str, Any],
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
    """Dispatch one atomic trace to its fixed pure recalculation protocol."""

    if (
        set(trace) != _TRACE_FIELDS
        or trace.get("schema") != SCIENTIFIC_EVALUATION_TRACE_SCHEMA
        or set(calculation) != _CALCULATION_FIELDS
        or calculation.get("schema") != SCIENTIFIC_CALCULATION_PROOF_SCHEMA
    ):
        raise ScientificTraceError("scientific trace/calculation schema is invalid")
    protocol_id = _ascii("trace protocol_id", trace.get("protocol_id"))
    if calculation.get("protocol_id") != protocol_id:
        raise ScientificTraceError("trace and calculation protocols differ")
    _common_identity(
        value=trace,
        mission_id=mission_id,
        executable_id=executable_id,
        job_id=job_id,
        job_hash=job_hash,
    )
    _common_identity(
        value=calculation,
        mission_id=mission_id,
        executable_id=executable_id,
        job_id=job_id,
        job_hash=job_hash,
    )
    trace_reference = calculation.get("trace")
    if (
        not isinstance(trace_reference, Mapping)
        or set(trace_reference) != {"output_name", "sha256"}
        or trace_reference.get("output_name") != trace_output_name
        or trace_reference.get("sha256") != _digest("trace hash", trace_hash)
    ):
        raise ScientificTraceError(
            "calculation proof is not bound to the opened atomic trace"
        )
    modes = calculation.get("evidence_modes")
    if (
        not isinstance(modes, list)
        or tuple(modes) != expected_evidence_modes
        or tuple(modes) != tuple(sorted(set(modes)))
    ):
        raise ScientificTraceError(
            "calculation evidence modes differ from preregistration"
        )

    if protocol_id == ANALOG_STATE_TRACE_PROTOCOL_ID:
        from axiom_rift.research.analog_state_trace import (
            validate_analog_trace_calculation,
        )

        derived_metrics = validate_analog_trace_calculation(
            trace=trace,
            calculation=calculation,
        )
    elif protocol_id == ANALOG_SCOPED_TRACE_PROTOCOL_ID:
        from axiom_rift.research.analog_state_scoped_job import (
            validate_analog_scoped_trace_calculation,
        )

        derived_metrics = validate_analog_scoped_trace_calculation(
            trace=trace,
            calculation=calculation,
        )
    else:
        raise ScientificTraceError("scientific trace protocol is not registered")

    for mode in expected_evidence_modes:
        for binding in expected_metric_bindings_by_mode.get(mode, ()):
            claim_id = str(binding["claim_id"])
            metric = str(binding["metric"])
            claim_metrics = derived_metrics.get(claim_id)
            if (
                not isinstance(claim_metrics, Mapping)
                or claim_metrics.get(metric) != binding["value"]
            ):
                raise ScientificTraceError(
                    "measurement metric does not recompute from atomic trace"
                )
    return expected_evidence_modes


__all__ = [
    "ANALOG_STATE_TRACE_PROTOCOL_ID",
    "ANALOG_SCOPED_TRACE_PROTOCOL_ID",
    "ATOMIC_TRACE_PROOF_KIND",
    "CALCULATION_PROOF_KIND",
    "SCIENTIFIC_CALCULATION_PROOF_SCHEMA",
    "SCIENTIFIC_EVALUATION_TRACE_SCHEMA",
    "ScientificTraceError",
    "trace_proof_kinds",
    "validate_trace_calculation_pair",
]
