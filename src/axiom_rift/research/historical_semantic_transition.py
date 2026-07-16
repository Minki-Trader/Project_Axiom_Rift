"""Authenticated evidence for one historical fixed-hold semantic transition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.fixed_hold_historical_projection import (
    project_historical_drawdown_evaluation,
)
from axiom_rift.research.scientific_trace import ScientificTraceError


NO_SEMANTIC_TRANSITION_POLICY = "none"
HISTORICAL_COST_TIMING_TRANSITION_POLICY = (
    "historical_cost_timing_semantic_transition.v3"
)
HISTORICAL_COST_TIMING_TRANSITION_REASON = (
    "decision_input_point_in_time_unproven_and_completed_period_cost_"
    "sources_rebound"
)
HISTORICAL_SEMANTIC_TRANSITION_SCHEMA = (
    "historical_raw_semantic_transition.v3"
)
_THIS_FILE = Path(__file__).resolve()
_TRANSITION_FIELDS = {
    "changed_economic_surfaces",
    "configuration_id",
    "corrected_economic_digest",
    "corrected_economic_surfaces",
    "corrected_executable_id",
    "corrected_structural_surfaces",
    "historical_artifact_schema",
    "historical_artifact_sha256",
    "historical_economic_digest",
    "historical_evaluation_artifact",
    "historical_reference_executable_id",
    "reason",
    "schema",
    "structural_digest",
    "unchanged_economic_surfaces",
    "unchanged_numeric_relation",
}


def historical_semantic_transition_implementation_sha256() -> str:
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
        raise ScientificTraceError(f"{name} must be lowercase sha256")
    return text


def _identity(name: str, value: object, *, prefix: str) -> str:
    text = _ascii(name, value)
    expected_prefix = prefix + ":"
    digest = text[len(expected_prefix) :] if text.startswith(expected_prefix) else ""
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ScientificTraceError(f"{name} must be a {prefix} identity")
    return text


def _normalized_mapping(name: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ScientificTraceError(f"{name} must be a mapping")
    try:
        normalized = parse_canonical(canonical_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise ScientificTraceError(f"{name} is not canonical") from exc
    if type(normalized) is not dict or not normalized:
        raise ScientificTraceError(f"{name} must be a non-empty object")
    for key in normalized:
        _ascii(f"{name} surface", key)
    return normalized


def _validated_historical_artifact(
    value: object,
    *,
    expected_artifact_sha256: str,
    expected_artifact_schema: str,
    expected_configuration_id: str,
    expected_historical_reference_executable_id: str,
) -> tuple[dict[str, Any], dict[str, dict[str, object]]]:
    artifact = _normalized_mapping("historical evaluation artifact", value)
    if sha256(canonical_bytes(artifact)).hexdigest() != _digest(
        "expected historical artifact sha256", expected_artifact_sha256
    ):
        raise ScientificTraceError(
            "historical evaluation artifact content address drifted"
        )
    projection = project_historical_drawdown_evaluation(
        artifact,
        expected_configuration_id=expected_configuration_id,
        expected_historical_executable_id=(
            expected_historical_reference_executable_id
        ),
        expected_schema=_ascii(
            "expected historical artifact schema", expected_artifact_schema
        ),
    )
    return artifact, projection


def _relation_fields(
    *,
    historical_economic: Mapping[str, object],
    corrected_economic: Mapping[str, object],
) -> tuple[list[str], list[str]]:
    surface_names = tuple(sorted(historical_economic))
    if tuple(sorted(corrected_economic)) != surface_names:
        raise ScientificTraceError(
            "historical semantic transition surface inventory drifted"
        )
    changed = [
        name
        for name in surface_names
        if historical_economic[name] != corrected_economic[name]
    ]
    return changed, [name for name in surface_names if name not in changed]


def build_historical_cost_timing_transition(
    *,
    configuration_id: str,
    corrected_executable_id: str,
    historical_reference_executable_id: str,
    historical_artifact_sha256: str,
    historical_artifact_schema: str,
    historical_evaluation_artifact: Mapping[str, object],
    corrected_structural_surfaces: Mapping[str, object],
    corrected_economic_surfaces: Mapping[str, object],
) -> dict[str, object]:
    """Build a transition whose two sides have independent authority."""

    historical_artifact, historical_projection = _validated_historical_artifact(
        historical_evaluation_artifact,
        expected_artifact_sha256=historical_artifact_sha256,
        expected_artifact_schema=historical_artifact_schema,
        expected_configuration_id=configuration_id,
        expected_historical_reference_executable_id=(
            historical_reference_executable_id
        ),
    )
    corrected_structural = _normalized_mapping(
        "corrected structural surfaces", corrected_structural_surfaces
    )
    corrected_economic = _normalized_mapping(
        "corrected economic surfaces", corrected_economic_surfaces
    )
    historical_structural = historical_projection["structural"]
    historical_economic = historical_projection["economic"]
    if historical_structural != corrected_structural:
        raise ScientificTraceError(
            "historical semantic transition structural continuity failed"
        )
    changed, unchanged = _relation_fields(
        historical_economic=historical_economic,
        corrected_economic=corrected_economic,
    )
    value: dict[str, object] = {
        "changed_economic_surfaces": changed,
        "configuration_id": _ascii("configuration_id", configuration_id),
        "corrected_economic_digest": canonical_digest(
            domain="stu0048-corrected-economic-surfaces",
            payload=corrected_economic,
        ),
        "corrected_economic_surfaces": corrected_economic,
        "corrected_executable_id": _identity(
            "corrected_executable_id",
            corrected_executable_id,
            prefix="executable",
        ),
        "corrected_structural_surfaces": corrected_structural,
        "historical_artifact_schema": _ascii(
            "historical_artifact_schema", historical_artifact_schema
        ),
        "historical_artifact_sha256": _digest(
            "historical_artifact_sha256", historical_artifact_sha256
        ),
        "historical_economic_digest": canonical_digest(
            domain="stu0048-historical-economic-surfaces",
            payload=historical_economic,
        ),
        "historical_evaluation_artifact": historical_artifact,
        "historical_reference_executable_id": _identity(
            "historical_reference_executable_id",
            historical_reference_executable_id,
            prefix="executable",
        ),
        "reason": HISTORICAL_COST_TIMING_TRANSITION_REASON,
        "schema": HISTORICAL_SEMANTIC_TRANSITION_SCHEMA,
        "structural_digest": canonical_digest(
            domain="stu0048-structural-continuity",
            payload=corrected_structural,
        ),
        "unchanged_economic_surfaces": unchanged,
        "unchanged_numeric_relation": not changed,
    }
    return validate_historical_cost_timing_transition(
        value,
        expected_configuration_id=configuration_id,
        expected_corrected_executable_id=corrected_executable_id,
        expected_historical_reference_executable_id=(
            historical_reference_executable_id
        ),
        expected_historical_artifact_sha256=historical_artifact_sha256,
        expected_historical_artifact_schema=historical_artifact_schema,
        expected_corrected_structural_surfaces=corrected_structural,
        expected_corrected_economic_surfaces=corrected_economic,
    )


def validate_historical_cost_timing_transition(
    value: object,
    *,
    expected_configuration_id: str,
    expected_corrected_executable_id: str,
    expected_historical_reference_executable_id: str,
    expected_historical_artifact_sha256: str,
    expected_historical_artifact_schema: str,
    expected_corrected_structural_surfaces: Mapping[str, object],
    expected_corrected_economic_surfaces: Mapping[str, object],
) -> dict[str, object]:
    """Verify old artifact bytes and corrected atomic-row projection."""

    if not isinstance(value, Mapping) or set(value) != _TRANSITION_FIELDS:
        raise ScientificTraceError(
            "historical semantic transition schema is invalid"
        )
    try:
        normalized = parse_canonical(canonical_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise ScientificTraceError(
            "historical semantic transition is not canonical"
        ) from exc
    if type(normalized) is not dict:
        raise ScientificTraceError(
            "historical semantic transition must be an object"
        )
    if (
        normalized.get("schema") != HISTORICAL_SEMANTIC_TRANSITION_SCHEMA
        or normalized.get("configuration_id")
        != _ascii("expected configuration_id", expected_configuration_id)
        or normalized.get("corrected_executable_id")
        != _identity(
            "expected corrected_executable_id",
            expected_corrected_executable_id,
            prefix="executable",
        )
        or normalized.get("historical_reference_executable_id")
        != _identity(
            "expected historical_reference_executable_id",
            expected_historical_reference_executable_id,
            prefix="executable",
        )
        or normalized.get("reason") != HISTORICAL_COST_TIMING_TRANSITION_REASON
        or normalized.get("historical_artifact_sha256")
        != _digest(
            "expected historical artifact sha256",
            expected_historical_artifact_sha256,
        )
        or normalized.get("historical_artifact_schema")
        != _ascii(
            "expected historical artifact schema",
            expected_historical_artifact_schema,
        )
    ):
        raise ScientificTraceError(
            "historical semantic transition authority binding drifted"
        )
    _, historical_projection = _validated_historical_artifact(
        normalized.get("historical_evaluation_artifact"),
        expected_artifact_sha256=expected_historical_artifact_sha256,
        expected_artifact_schema=expected_historical_artifact_schema,
        expected_configuration_id=expected_configuration_id,
        expected_historical_reference_executable_id=(
            expected_historical_reference_executable_id
        ),
    )
    corrected_structural = _normalized_mapping(
        "corrected structural surfaces",
        normalized.get("corrected_structural_surfaces"),
    )
    corrected_economic = _normalized_mapping(
        "corrected economic surfaces",
        normalized.get("corrected_economic_surfaces"),
    )
    expected_structural = _normalized_mapping(
        "expected corrected structural surfaces",
        expected_corrected_structural_surfaces,
    )
    expected_economic = _normalized_mapping(
        "expected corrected economic surfaces",
        expected_corrected_economic_surfaces,
    )
    historical_structural = historical_projection["structural"]
    historical_economic = historical_projection["economic"]
    if (
        corrected_structural != expected_structural
        or corrected_economic != expected_economic
    ):
        raise ScientificTraceError(
            "historical semantic transition differs from atomic-row projection"
        )
    if historical_structural != corrected_structural:
        raise ScientificTraceError(
            "historical semantic transition structural continuity failed"
        )
    changed, unchanged = _relation_fields(
        historical_economic=historical_economic,
        corrected_economic=corrected_economic,
    )
    if (
        normalized.get("changed_economic_surfaces") != changed
        or normalized.get("unchanged_economic_surfaces") != unchanged
        or normalized.get("unchanged_numeric_relation") is not (not changed)
        or normalized.get("structural_digest")
        != canonical_digest(
            domain="stu0048-structural-continuity",
            payload=corrected_structural,
        )
        or normalized.get("historical_economic_digest")
        != canonical_digest(
            domain="stu0048-historical-economic-surfaces",
            payload=historical_economic,
        )
        or normalized.get("corrected_economic_digest")
        != canonical_digest(
            domain="stu0048-corrected-economic-surfaces",
            payload=corrected_economic,
        )
    ):
        raise ScientificTraceError(
            "historical semantic transition relation or digest drifted"
        )
    return normalized


def validate_historical_semantic_transition_inventory(
    value: object,
    *,
    policy: str,
    ordered_family: Sequence[Mapping[str, Any]],
    historical_artifacts_by_configuration: Mapping[str, Mapping[str, str]],
    corrected_surfaces_by_configuration: Mapping[
        str, Mapping[str, Mapping[str, object]]
    ],
) -> tuple[dict[str, object], ...]:
    """Validate the policy-bound exact member transition inventory."""

    if type(value) is not list:
        raise ScientificTraceError(
            "historical semantic transition inventory must be a list"
        )
    if policy == NO_SEMANTIC_TRANSITION_POLICY:
        if value:
            raise ScientificTraceError(
                "semantic transition evidence is forbidden by policy"
            )
        if historical_artifacts_by_configuration or corrected_surfaces_by_configuration:
            raise ScientificTraceError(
                "semantic transition projections are forbidden by policy"
            )
        return ()
    if policy != HISTORICAL_COST_TIMING_TRANSITION_POLICY:
        raise ScientificTraceError("semantic transition policy is invalid")
    family = tuple(ordered_family)
    configurations = tuple(str(item["configuration_id"]) for item in family)
    if (
        len(value) != len(family)
        or set(historical_artifacts_by_configuration) != set(configurations)
        or set(corrected_surfaces_by_configuration) != set(configurations)
    ):
        raise ScientificTraceError(
            "semantic transition evidence does not cover the exact family"
        )
    result: list[dict[str, object]] = []
    for transition, member in zip(value, family, strict=True):
        configuration_id = str(member["configuration_id"])
        artifact = historical_artifacts_by_configuration[configuration_id]
        corrected = corrected_surfaces_by_configuration[configuration_id]
        if set(artifact) != {"artifact_sha256", "schema"} or set(corrected) != {
            "economic",
            "structural",
        }:
            raise ScientificTraceError(
                "semantic transition projection binding is invalid"
            )
        result.append(
            validate_historical_cost_timing_transition(
                transition,
                expected_configuration_id=configuration_id,
                expected_corrected_executable_id=str(member["executable_id"]),
                expected_historical_reference_executable_id=str(
                    member["historical_reference_executable_id"]
                ),
                expected_historical_artifact_sha256=artifact["artifact_sha256"],
                expected_historical_artifact_schema=artifact["schema"],
                expected_corrected_structural_surfaces=corrected["structural"],
                expected_corrected_economic_surfaces=corrected["economic"],
            )
        )
    if tuple(item["configuration_id"] for item in result) != configurations:
        raise ScientificTraceError(
            "semantic transition evidence order drifted"
        )
    return tuple(result)


__all__ = [
    "HISTORICAL_COST_TIMING_TRANSITION_POLICY",
    "HISTORICAL_COST_TIMING_TRANSITION_REASON",
    "HISTORICAL_SEMANTIC_TRANSITION_SCHEMA",
    "NO_SEMANTIC_TRANSITION_POLICY",
    "build_historical_cost_timing_transition",
    "historical_semantic_transition_implementation_sha256",
    "validate_historical_cost_timing_transition",
    "validate_historical_semantic_transition_inventory",
]
