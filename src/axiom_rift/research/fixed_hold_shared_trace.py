"""Content-addressed fixed-hold family traces with subject-scoped proofs.

The neutral family trace is durable once.  A small calculation artifact binds
that shared content to one Mission, Executable, and Job.  The established
subject-bound trace remains the semantic oracle and is projected only in
memory, preserving historical validation without duplicating durable rows.
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_REPLAY_EVIDENCE_MODES,
    FIXED_HOLD_TRACE_VALIDATOR,
    FixedHoldFamilyTraceSnapshot,
    FixedHoldProtocolDefinition,
    bind_fixed_hold_family_trace_snapshot,
    build_fixed_hold_trace_calculation,
    fixed_hold_protocol_definition_from_manifest,
    validate_fixed_hold_family_trace_snapshot,
    validate_fixed_hold_trace_calculation,
)
from axiom_rift.research.scientific_trace import ScientificTraceError


_THIS_FILE = Path(__file__).resolve()


def fixed_hold_shared_trace_implementation_sha256() -> str:
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
        raise ScientificTraceError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


def build_fixed_hold_shared_trace_calculation(
    *,
    trace: Mapping[str, Any] | FixedHoldFamilyTraceSnapshot,
    definition: FixedHoldProtocolDefinition,
    mission_id: str,
    executable_id: str,
    job_id: str,
    job_hash: str,
    trace_output_name: str,
    trace_hash: str,
) -> dict[str, object]:
    """Build one subject calculation over a shared family trace."""

    family = validate_fixed_hold_family_trace_snapshot(
        trace,
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
    )
    expected_hash = family.sha256
    if _digest("shared fixed-hold trace hash", trace_hash) != expected_hash:
        raise ScientificTraceError(
            "shared fixed-hold trace hash differs from the opened trace"
        )
    subject_trace = bind_fixed_hold_family_trace_snapshot(
        family_trace=family,
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
        mission_id=mission_id,
        executable_id=executable_id,
        job_id=job_id,
        job_hash=job_hash,
    )
    subject_hash = subject_trace.sha256
    legacy = build_fixed_hold_trace_calculation(
        trace=subject_trace,
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
        trace_output_name=trace_output_name,
        trace_hash=subject_hash,
    )
    calculation = {
        **legacy,
        "trace": {
            "output_name": _ascii(
                "shared fixed-hold trace output name",
                trace_output_name,
            ),
            "sha256": expected_hash,
        },
    }
    canonical_bytes(calculation)
    return calculation


def validate_fixed_hold_shared_trace_calculation(
    *,
    trace: Mapping[str, Any] | FixedHoldFamilyTraceSnapshot,
    calculation: Mapping[str, Any],
    definition: FixedHoldProtocolDefinition,
) -> dict[str, dict[str, int]]:
    """Recompute a subject proof from one content-addressed family trace."""

    family = validate_fixed_hold_family_trace_snapshot(
        trace,
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
    )
    trace_reference = calculation.get("trace")
    expected_hash = family.sha256
    if (
        not isinstance(trace_reference, Mapping)
        or set(trace_reference) != {"output_name", "sha256"}
        or trace_reference.get("sha256") != expected_hash
    ):
        raise ScientificTraceError(
            "fixed-hold calculation is not bound to the shared family trace"
        )
    subject_trace = bind_fixed_hold_family_trace_snapshot(
        family_trace=family,
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
        mission_id=calculation.get("mission_id"),
        executable_id=calculation.get("executable_id"),
        job_id=calculation.get("job_id"),
        job_hash=calculation.get("job_hash"),
    )
    projected_calculation = {
        **calculation,
        "trace": {
            "output_name": trace_reference.get("output_name"),
            "sha256": subject_trace.sha256,
        },
    }
    return validate_fixed_hold_trace_calculation(
        trace=subject_trace,
        calculation=projected_calculation,
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
    )


def _protocol_definition(
    calculation: Mapping[str, Any],
) -> FixedHoldProtocolDefinition:
    definition = fixed_hold_protocol_definition_from_manifest(
        calculation.get("protocol_definition")
    )
    if calculation.get("protocol_id") != definition.protocol_id:
        raise ScientificTraceError(
            "shared fixed-hold calculation protocol definition drifted"
        )
    return definition


def validate_fixed_hold_shared_trace_pair(
    *,
    trace: Mapping[str, Any] | FixedHoldFamilyTraceSnapshot,
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
    """Validate one shared family trace through a closed protocol route."""

    definition = _protocol_definition(calculation)
    family = validate_fixed_hold_family_trace_snapshot(
        trace,
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
    )
    try:
        actual_hash = family.sha256
        opened_hash = _digest("shared fixed-hold trace hash", trace_hash)
    except (TypeError, ValueError) as exc:
        raise ScientificTraceError(str(exc)) from exc
    if opened_hash != actual_hash:
        raise ScientificTraceError(
            "shared fixed-hold trace hash differs from the opened trace"
        )
    if (
        calculation.get("mission_id") != mission_id
        or calculation.get("executable_id") != executable_id
        or calculation.get("job_id") != job_id
        or calculation.get("job_hash") != job_hash
    ):
        raise ScientificTraceError(
            "shared fixed-hold calculation belongs to another execution"
        )
    if definition.protocol_id != calculation.get("protocol_id"):
        raise ScientificTraceError(
            "shared fixed-hold trace and calculation protocols differ"
        )
    reference = calculation.get("trace")
    if (
        not isinstance(reference, Mapping)
        or set(reference) != {"output_name", "sha256"}
        or reference.get("output_name") != trace_output_name
        or reference.get("sha256") != actual_hash
    ):
        raise ScientificTraceError(
            "calculation proof is not bound to the opened shared trace"
        )
    modes = calculation.get("evidence_modes")
    if (
        not isinstance(modes, list)
        or tuple(modes) != expected_evidence_modes
        or tuple(modes) != tuple(sorted(set(modes)))
        or tuple(modes) != FIXED_HOLD_REPLAY_EVIDENCE_MODES
    ):
        raise ScientificTraceError(
            "shared fixed-hold evidence modes differ from preregistration"
        )
    derived_metrics = validate_fixed_hold_shared_trace_calculation(
        trace=family,
        calculation=calculation,
        definition=definition,
    )
    for mode in expected_evidence_modes:
        for binding in expected_metric_bindings_by_mode.get(mode, ()):
            claim_metrics = derived_metrics.get(str(binding["claim_id"]))
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
    "build_fixed_hold_shared_trace_calculation",
    "fixed_hold_shared_trace_implementation_sha256",
    "validate_fixed_hold_shared_trace_calculation",
    "validate_fixed_hold_shared_trace_pair",
]
