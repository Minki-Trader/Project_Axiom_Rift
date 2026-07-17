"""Typed pre-registration authority for prospective replay Job code.

A replay trial is a scientific identity, while its Python closure is an
operational capability.  This module checks the latter before a Batch spends
trial or compute budget.  A rejected result is durable engineering evidence;
it is never a scientific verdict and never grants replay satisfaction.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import InitVar, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.component_surface import (
    ARCHITECTURE_ROLE_DOMAINS,
    ComponentManifestError,
    component_manifest_domain,
    component_manifest_identity,
    validated_component_manifest,
)
from axiom_rift.core.identity import ExecutableSpec, canonical_digest
from axiom_rift.operations.historical_replay_implementation_authority import (
    HistoricalReplayImplementationAuthorityError,
    authenticated_historical_implementation_sources,
)
from axiom_rift.operations.job_implementation_authority import (
    JobImplementationAuthorityError,
    implementation_source_closure_hashes,
    require_job_implementation_evidence,
)
from axiom_rift.research.implementation_closure import (
    ImplementationClosureError,
    require_current_job_source_closure,
    require_job_implementation_closure,
)
from axiom_rift.storage.index import LocalIndex, LocalIndexView


PREFLIGHT_SCHEMA = "replay_job_implementation_preflight.v1"
SCIENTIFIC_SURFACE_SCHEMA = "replay_job_scientific_surface.v2"
SCIENTIFIC_SURFACE_HASH_DOMAIN = "replay-job-scientific-surface"
SCIENTIFIC_EQUIVALENCE_SCHEMA = (
    "replay_job_scientific_equivalence.v1"
)
SCIENTIFIC_EQUIVALENCE_HASH_DOMAIN = (
    "replay-job-scientific-equivalence"
)
SAME_IDENTITY_REPAIR = "same_identity_repair"
REPLACEMENT_REQUIRED = "replacement_required"
_CONTEXT_ONLY_PARAMETER = (
    "historical_context_prior_global_exposure_count"
)
_ORIGINAL_FAMILY_CONTEXT_PARAMETER = (
    "original_family_end_global_exposure_count"
)
_CONTEXT_ONLY_PARAMETERS = frozenset(
    {
        _CONTEXT_ONLY_PARAMETER,
        _ORIGINAL_FAMILY_CONTEXT_PARAMETER,
    }
)
_FIXED_HOLD_RUNTIME_PREFIXES = ("numpy", "pandas", "python", "scipy")
_FIXED_HOLD_ENGINE_SHAPES = {
    "stu0051_volatility_duration_replay_v1": frozenset(
        {
            "adapter",
            "catalog",
            "loader",
            "selection",
            "shared",
            "trace_engine",
        }
    ),
    "volatility_duration_fixed_hold_v1": frozenset(
        {
            "adapter",
            "loader",
            "selection",
            "shared",
            "trace_engine",
        }
    ),
}
_FIXED_HOLD_ENGINE_SEMANTIC_FAMILY = (
    "stu0051_volatility_duration_fixed_hold_replay"
)
_FIXED_HOLD_REPLAY_PROTOCOL_ID = (
    "volatility_duration.concurrent_four_config.replay.v1"
)
_FIXED_HOLD_CONTEXT_OWNER_PROTOCOL = (
    "portfolio.concurrent_fixed_hold_family_inference.v2"
)
_FIXED_HOLD_PRODUCER_ROLE_SHAPES = frozenset(
    {
        frozenset(
            {
                "adapter_sha256",
                "catalog_sha256",
                "discovery_sha256",
                "loader_sha256",
                "trace_engine_sha256",
            }
        ),
        frozenset(
            {
                "adapter_sha256",
                "discovery_sha256",
                "loader_sha256",
                "selection_sha256",
                "trace_engine_sha256",
                "trace_schema_sha256",
            }
        ),
    }
)
_EXECUTABLE_FIELDS = {
    "clock_contract",
    "component_identities",
    "component_manifests",
    "cost_contract",
    "data_contract",
    "engine_contract",
    "parameters",
    "schema",
    "source_contracts",
    "split_contract",
}


class ReplayJobImplementationPreflightError(ValueError):
    """The caller supplied a malformed preflight request."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ReplayJobImplementationPreflightError(
            f"{name} must be non-empty ASCII"
        )
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ReplayJobImplementationPreflightError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


def _prefixed(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    suffix = text.removeprefix(prefix)
    if text == suffix:
        raise ReplayJobImplementationPreflightError(
            f"{name} must use the {prefix} namespace"
        )
    _digest(name, suffix)
    return text


def _canonical_value(name: str, value: object) -> Any:
    try:
        return parse_canonical(canonical_bytes(value))
    except (TypeError, ValueError) as exc:
        raise ReplayJobImplementationPreflightError(
            f"{name} is not canonical"
        ) from exc


def _mapping(name: str, value: object) -> dict[str, Any]:
    copied = _canonical_value(name, value)
    if not isinstance(copied, dict):
        raise ReplayJobImplementationPreflightError(
            f"{name} must be an object"
        )
    return copied


def _strip_context_parameters(
    value: object,
    *,
    names: frozenset[str],
) -> dict[str, Any]:
    """Remove named top-level observations while preserving nested values."""

    copied = _mapping("replay scientific parameter surface", value)
    for parameter in names:
        if parameter not in copied:
            continue
        context = copied.pop(parameter)
        if type(context) is not int or context < 0:
            raise ReplayJobImplementationPreflightError(
                "replay prospective exposure context is invalid"
            )
    return copied


def _strip_prospective_context_parameter(value: object) -> dict[str, Any]:
    return _strip_context_parameters(
        value,
        names=frozenset({_CONTEXT_ONLY_PARAMETER}),
    )


def _strip_equivalence_context_parameters(value: object) -> dict[str, Any]:
    return _strip_context_parameters(
        value,
        names=_CONTEXT_ONLY_PARAMETERS,
    )


def _normalized_component_scientific_spec(
    protocol: str,
    value: object,
) -> dict[str, Any]:
    """Exclude only redundant implementation/binding metadata from science."""

    spec = _mapping("replay Component scientific spec", value)
    catalog_digest = spec.get("catalog_digest")
    if protocol == "synthesis.historical_fixed_hold_member.v2" and (
        catalog_digest is not None
    ):
        _digest("replay historical catalog", catalog_digest)
        spec.pop("catalog_digest")
    parameter_fields = spec.get("parameter_fields")
    if isinstance(parameter_fields, list):
        if any(type(item) is not str for item in parameter_fields):
            raise ReplayJobImplementationPreflightError(
                "replay Component parameter fields are malformed"
            )
        context_fields = set(parameter_fields).intersection(
            _CONTEXT_ONLY_PARAMETERS
        )
        if context_fields and protocol != _FIXED_HOLD_CONTEXT_OWNER_PROTOCOL:
            raise ReplayJobImplementationPreflightError(
                "replay exposure context is declared by an unrelated Component"
            )
        if protocol == _FIXED_HOLD_CONTEXT_OWNER_PROTOCOL:
            if (
                spec.get("historical_context_adjustment_authority")
                != "context_only_never_adjustment_factor"
                or _CONTEXT_ONLY_PARAMETER not in parameter_fields
            ):
                raise ReplayJobImplementationPreflightError(
                    "replay exposure context owner is malformed"
                )
            spec["parameter_fields"] = [
                item
                for item in parameter_fields
                if item != _ORIGINAL_FAMILY_CONTEXT_PARAMETER
            ]
    return spec


def _require_original_family_end_binding(
    manifest: Mapping[str, Any],
    *,
    expected: int,
    name: str,
    strict_owner: bool = False,
) -> bool:
    """Bind a reconstruction-only Executable field to historical authority."""

    if type(expected) is not int or expected < 0:
        raise ReplayJobImplementationPreflightError(
            "replay original family exposure boundary is invalid"
        )
    value = _mapping(name, manifest)
    parameters = _mapping(f"{name} parameters", value.get("parameters"))
    raw_manifests = value.get("component_manifests")
    if not isinstance(raw_manifests, list):
        raise ReplayJobImplementationPreflightError(
            f"{name} Component family is invalid"
        )
    owner_count = 0
    declares_parameter = False
    for raw in raw_manifests:
        try:
            component = validated_component_manifest(raw)
        except ComponentManifestError as exc:
            raise ReplayJobImplementationPreflightError(str(exc)) from exc
        fields = component["spec"].get("parameter_fields")
        if fields is not None and (
            not isinstance(fields, list)
            or any(type(field) is not str for field in fields)
        ):
            raise ReplayJobImplementationPreflightError(
                f"{name} Component parameter fields are malformed"
            )
        fields = [] if fields is None else fields
        context_fields = set(fields).intersection(_CONTEXT_ONLY_PARAMETERS)
        if component["protocol"] == _FIXED_HOLD_CONTEXT_OWNER_PROTOCOL:
            owner_count += 1
            if (
                component["spec"].get(
                    "historical_context_adjustment_authority"
                )
                != "context_only_never_adjustment_factor"
                or _CONTEXT_ONLY_PARAMETER not in fields
            ):
                raise ReplayJobImplementationPreflightError(
                    "replay exposure context owner is malformed"
                )
            declares_parameter = (
                _ORIGINAL_FAMILY_CONTEXT_PARAMETER in fields
            )
        elif strict_owner and context_fields:
            raise ReplayJobImplementationPreflightError(
                "replay exposure context is declared by an unrelated Component"
            )
    if strict_owner and owner_count != 1:
        raise ReplayJobImplementationPreflightError(
            "replay exposure context requires one exact portfolio owner"
        )
    if strict_owner:
        prior = parameters.get(_CONTEXT_ONLY_PARAMETER)
        if type(prior) is not int or prior < 0:
            raise ReplayJobImplementationPreflightError(
                "replay prospective exposure context is invalid"
            )

        def contains_nested_context(value: object) -> bool:
            if isinstance(value, Mapping):
                return any(
                    key in _CONTEXT_ONLY_PARAMETERS
                    or contains_nested_context(item)
                    for key, item in value.items()
                )
            if isinstance(value, list):
                return any(contains_nested_context(item) for item in value)
            return False

        if any(
            contains_nested_context(item)
            for key, item in parameters.items()
            if key not in _CONTEXT_ONLY_PARAMETERS
        ):
            raise ReplayJobImplementationPreflightError(
                "replay exposure context is nested outside its owner"
            )
    actual = parameters.get(_ORIGINAL_FAMILY_CONTEXT_PARAMETER)
    if (
        (
            strict_owner
            and declares_parameter
            != (_ORIGINAL_FAMILY_CONTEXT_PARAMETER in parameters)
        )
        or (
            not strict_owner
            and declares_parameter
            and _ORIGINAL_FAMILY_CONTEXT_PARAMETER not in parameters
        )
        or (
            _ORIGINAL_FAMILY_CONTEXT_PARAMETER in parameters
            and (type(actual) is not int or actual != expected)
        )
    ):
        raise ReplayJobImplementationPreflightError(
            "replay original family exposure boundary drifted"
        )
    return declares_parameter


def _require_controlled_chassis_original_family_end_binding(
    value: object,
    *,
    expected: int,
    strict_owner: bool = False,
) -> None:
    chassis = _mapping("replay controlled chassis", value)
    baseline = chassis.get("baseline_executable")
    if not isinstance(baseline, Mapping):
        raise ReplayJobImplementationPreflightError(
            "replay controlled chassis baseline is absent"
        )
    declares_original = _require_original_family_end_binding(
        baseline,
        expected=expected,
        name="replay controlled chassis baseline",
        strict_owner=strict_owner,
    )
    grouped = _mapping(
        "replay controlled chassis parameter bindings",
        chassis.get("controlled_parameter_bindings"),
    )
    architecture = _mapping(
        "replay controlled chassis architecture",
        chassis.get("architecture"),
    )
    roles = _mapping(
        "replay controlled chassis architecture roles",
        architecture.get("roles"),
    )
    parameter_surfaces = [
        ("controlled", name, parameters)
        for name, parameters in grouped.items()
    ] + [
        (
            "architecture",
            role,
            _mapping(f"replay architecture role {role}", payload).get(
                "parameter_bindings"
            ),
        )
        for role, payload in roles.items()
    ]
    for surface_kind, owner, raw in parameter_surfaces:
        parameters = _mapping("replay controlled parameter binding", raw)
        present = set(parameters).intersection(_CONTEXT_ONLY_PARAMETERS)
        if strict_owner and present and owner != "portfolio":
            raise ReplayJobImplementationPreflightError(
                "replay exposure context escaped its portfolio binding"
            )
        if strict_owner and owner == "portfolio":
            prior = parameters.get(_CONTEXT_ONLY_PARAMETER)
            if type(prior) is not int or prior < 0:
                raise ReplayJobImplementationPreflightError(
                    "replay prospective exposure context is invalid"
                )
            original_present = (
                _ORIGINAL_FAMILY_CONTEXT_PARAMETER in parameters
            )
            if (
                surface_kind == "architecture"
                and original_present != declares_original
            ):
                raise ReplayJobImplementationPreflightError(
                    "replay original family exposure binding drifted"
                )
        if _ORIGINAL_FAMILY_CONTEXT_PARAMETER in parameters and (
            type(parameters[_ORIGINAL_FAMILY_CONTEXT_PARAMETER]) is not int
            or parameters[_ORIGINAL_FAMILY_CONTEXT_PARAMETER] != expected
        ):
            raise ReplayJobImplementationPreflightError(
                "replay original family exposure boundary drifted"
            )


def _engine_scientific_profile(value: object) -> dict[str, Any]:
    """Keep typed runtime semantics while moving byte identities to closure."""

    engine = _ascii("replay Executable engine contract", value)
    parts = engine.split(":")
    runtime: dict[str, str] = {}
    roles: dict[str, str] = {}
    if len(parts) >= 7 and parts[0] == "engine":
        tag = parts[1]
        malformed = False
        for part in parts[2:]:
            matches = tuple(
                prefix
                for prefix in _FIXED_HOLD_RUNTIME_PREFIXES
                if part.startswith(prefix) and len(part) > len(prefix)
            )
            if len(matches) == 1:
                prefix = matches[0]
                if prefix in runtime:
                    malformed = True
                    break
                runtime[prefix] = part.removeprefix(prefix)
                continue
            if "_" not in part:
                malformed = True
                break
            role, digest = part.rsplit("_", 1)
            if (
                not role
                or role in roles
                or len(digest) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in digest
                )
            ):
                malformed = True
                break
            roles[role] = digest
        expected_roles = _FIXED_HOLD_ENGINE_SHAPES.get(tag)
        if (
            not malformed
            and set(runtime) == set(_FIXED_HOLD_RUNTIME_PREFIXES)
            and expected_roles is not None
            and frozenset(roles) == expected_roles
        ):
            return {
                "runtime": dict(sorted(runtime.items())),
                "schema": "replay_engine_scientific_profile.v1",
                "semantic_contract_authority": (
                    "component_data_split_clock_cost_surfaces"
                ),
                "semantic_engine_family": (
                    _FIXED_HOLD_ENGINE_SEMANTIC_FAMILY
                ),
            }
    return {
        "opaque_contract": engine,
        "schema": "replay_engine_scientific_profile.v1",
    }


def _producer_role_scientific_profile(
    protocol_id: object,
    value: object,
) -> dict[str, Any]:
    protocol = _ascii("replay fixed-hold protocol", protocol_id)
    if not isinstance(value, list) or any(
        type(role) is not str or not role or not role.isascii()
        for role in value
    ):
        raise ReplayJobImplementationPreflightError(
            "replay producer implementation roles are malformed"
        )
    roles = tuple(sorted(value))
    if len(roles) != len(set(roles)):
        raise ReplayJobImplementationPreflightError(
            "replay producer implementation roles are duplicated"
        )
    if (
        protocol == _FIXED_HOLD_REPLAY_PROTOCOL_ID
        and frozenset(roles) in _FIXED_HOLD_PRODUCER_ROLE_SHAPES
    ):
        return {
            "schema": "replay_producer_role_scientific_profile.v1",
            "semantic_authority": (
                "authenticated_job_and_component_source_closure"
            ),
            "semantic_family": (
                _FIXED_HOLD_ENGINE_SEMANTIC_FAMILY
            ),
        }
    return {
        "opaque_roles": list(roles),
        "schema": "replay_producer_role_scientific_profile.v1",
    }


def _strip_grouped_context_parameters(value: object) -> dict[str, Any]:
    groups = _mapping("replay grouped parameter surface", value)
    return {
        name: _strip_equivalence_context_parameters(parameters)
        for name, parameters in groups.items()
    }


def _normalized_component_surface(
    manifest: Mapping[str, Any],
    *,
    ordinal_by_identity: Mapping[str, int],
) -> dict[str, Any]:
    try:
        value = validated_component_manifest(manifest)
        identity = component_manifest_identity(value)
    except ComponentManifestError as exc:
        raise ReplayJobImplementationPreflightError(str(exc)) from exc
    dependencies: list[dict[str, Any]] = []
    for dependency in value["semantic_dependencies"]:
        if dependency in ordinal_by_identity:
            normalized = {
                "kind": "family_component",
                "ordinal": ordinal_by_identity[dependency],
            }
        else:
            normalized = {
                "identity": dependency,
                "kind": "external_semantic_authority",
            }
        dependencies.append(normalized)
    dependencies.sort(key=canonical_bytes)
    return {
        "component_ordinal": ordinal_by_identity[identity],
        "protocol": value["protocol"],
        "schema": "replay_component_scientific_surface.v1",
        "semantic_dependencies": dependencies,
        "spec": value["spec"],
    }


def _normalized_executable_surface(
    manifest: Mapping[str, Any],
    *,
    require_historical_reference: bool,
) -> tuple[str | None, dict[str, Any]]:
    value = _mapping("replay Executable manifest", manifest)
    if set(value) != _EXECUTABLE_FIELDS or value.get("schema") != "executable_spec.v1":
        raise ReplayJobImplementationPreflightError(
            "replay Executable manifest schema is invalid"
        )
    raw_manifests = value.get("component_manifests")
    raw_identities = value.get("component_identities")
    if (
        not isinstance(raw_manifests, list)
        or not raw_manifests
        or not isinstance(raw_identities, list)
        or len(raw_manifests) != len(raw_identities)
    ):
        raise ReplayJobImplementationPreflightError(
            "replay Executable component family is invalid"
        )
    try:
        identities = tuple(
            component_manifest_identity(item) for item in raw_manifests
        )
    except ComponentManifestError as exc:
        raise ReplayJobImplementationPreflightError(str(exc)) from exc
    if list(identities) != raw_identities or len(set(identities)) != len(identities):
        raise ReplayJobImplementationPreflightError(
            "replay Executable Component identities drifted"
        )
    ordinal_by_identity = {
        identity: ordinal for ordinal, identity in enumerate(identities, 1)
    }
    components = [
        _normalized_component_surface(
            manifest,
            ordinal_by_identity=ordinal_by_identity,
        )
        for manifest in raw_manifests
    ]
    parameters = _mapping("replay Executable parameters", value.get("parameters"))
    reference = parameters.get("historical_reference_executable_id")
    if require_historical_reference:
        from axiom_rift.research.historical_family_binding import (
            HistoricalFamilyBindingError,
            historical_reference_executable_id_from_manifest,
        )

        try:
            reference = historical_reference_executable_id_from_manifest(value)
        except HistoricalFamilyBindingError as exc:
            raise ReplayJobImplementationPreflightError(str(exc)) from exc
        if reference is None:
            raise ReplayJobImplementationPreflightError(
                "replay Executable lacks one typed historical reference"
            )
    elif reference is not None and (
        type(reference) is not str or not reference.isascii()
    ):
        raise ReplayJobImplementationPreflightError(
            "replay baseline historical reference is invalid"
        )
    for name in (
        "clock_contract",
        "cost_contract",
        "data_contract",
        "engine_contract",
        "split_contract",
    ):
        _ascii(f"replay Executable {name}", value.get(name))
    sources = value.get("source_contracts")
    if (
        not isinstance(sources, list)
        or any(type(item) is not str or not item.isascii() for item in sources)
        or sources != sorted(set(sources))
    ):
        raise ReplayJobImplementationPreflightError(
            "replay Executable source contracts are invalid"
        )
    return (
        reference,
        {
            "clock_contract": value["clock_contract"],
            "components": components,
            "cost_contract": value["cost_contract"],
            "data_contract": value["data_contract"],
            "engine_contract": value["engine_contract"],
            "historical_reference_executable_id": reference,
            "parameters": _strip_prospective_context_parameter(parameters),
            "schema": "replay_executable_scientific_surface.v1",
            "source_contracts": sources,
            "split_contract": value["split_contract"],
        },
    )


def _normalized_protocol_definition(
    value: object,
    *,
    executable_ids: tuple[str, ...],
    references_by_executable: Mapping[str, str],
) -> dict[str, Any]:
    from axiom_rift.research.fixed_hold_family_trace import (
        ScientificTraceError,
        fixed_hold_protocol_definition_from_manifest,
    )

    try:
        definition = fixed_hold_protocol_definition_from_manifest(value)
    except (ScientificTraceError, TypeError, ValueError) as exc:
        raise ReplayJobImplementationPreflightError(
            "fixed-hold protocol definition is invalid"
        ) from exc
    if definition.prospective_executable_ids != executable_ids:
        raise ReplayJobImplementationPreflightError(
            "fixed-hold definition differs from the preflight family"
        )
    ordered_references = tuple(
        references_by_executable[executable_id]
        for executable_id in executable_ids
    )
    historical_references = tuple(
        member.historical_reference_executable_id
        for member in definition.family.members
    )
    if ordered_references != historical_references:
        raise ReplayJobImplementationPreflightError(
            "fixed-hold definition historical family order drifted"
        )
    manifest = definition.manifest()
    return {
        "allowed_regimes": manifest["allowed_regimes"],
        "clock_contract": manifest["clock_contract"],
        "cost_contract": manifest["cost_contract"],
        "dataset_sha256": manifest["dataset_sha256"],
        "fold_ids": manifest["fold_ids"],
        "historical_context_id": manifest["historical_context_id"],
        "historical_evaluation_artifacts": manifest[
            "historical_evaluation_artifacts"
        ],
        "historical_family": manifest["historical_family"],
        "inference": manifest["inference"],
        "invariance_keys": manifest["invariance_keys"],
        "material_identity": manifest["material_identity"],
        "original_family_end_global_exposure_count": manifest[
            "original_family_end_global_exposure_count"
        ],
        "producer_implementation_roles": sorted(
            manifest["producer_implementation_identities"]
        ),
        "prospective_historical_references": list(ordered_references),
        "protocol_id": manifest["protocol_id"],
        "schema": "fixed_hold_protocol_scientific_surface.v1",
        "semantic_transition_policy": manifest[
            "semantic_transition_policy"
        ],
        "split_artifact_sha256": manifest["split_artifact_sha256"],
    }


def _normalized_validation_plan_surface(
    *,
    request: "ReplayJobImplementationPreflightRequest",
    executable: ExecutableSpec,
    binding: Mapping[str, Any],
    references_by_executable: Mapping[str, str],
    artifact_reader: Callable[[str], bytes],
) -> dict[str, Any]:
    from axiom_rift.research.evidence_proofs import (
        CALCULATION_PROOF_KIND,
        FIXED_HOLD_FAMILY_TRACE_PROOF_KIND,
    )
    from axiom_rift.research.fixed_hold_family_job import (
        build_fixed_hold_validation_plan,
    )
    from axiom_rift.research.validation_v2 import (
        SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    )

    plan_hash = binding.get("validation_plan_hash")
    _digest("replay validation plan", plan_hash)
    try:
        plan_bytes = artifact_reader(plan_hash)
        if sha256(plan_bytes).hexdigest() != plan_hash:
            raise ReplayJobImplementationPreflightError(
                "replay validation plan artifact hash drifted"
            )
        plan = parse_canonical(plan_bytes)
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ReplayJobImplementationPreflightError(
            "replay validation plan artifact is unavailable"
        ) from exc
    if not isinstance(plan, dict):
        raise ReplayJobImplementationPreflightError(
            "replay validation plan must be an object"
        )
    if plan.get("mission_id") != request.mission_id or plan.get(
        "executable_id"
    ) != executable.identity:
        raise ReplayJobImplementationPreflightError(
            "replay validation plan subject drifted"
        )
    requirements = plan.get("proof_requirements")
    if not isinstance(requirements, list):
        raise ReplayJobImplementationPreflightError(
            "replay validation proof requirements are invalid"
        )
    names_by_kind: dict[str, set[str]] = {}
    for requirement in requirements:
        if not isinstance(requirement, dict):
            raise ReplayJobImplementationPreflightError(
                "replay validation proof requirement is malformed"
            )
        proof_kind = requirement.get("proof_kind")
        output_name = requirement.get("output_name")
        if type(proof_kind) is not str or type(output_name) is not str:
            raise ReplayJobImplementationPreflightError(
                "replay validation proof output is invalid"
            )
        names_by_kind.setdefault(proof_kind, set()).add(output_name)
    if set(names_by_kind) != {
        CALCULATION_PROOF_KIND,
        FIXED_HOLD_FAMILY_TRACE_PROOF_KIND,
    } or any(len(values) != 1 for values in names_by_kind.values()):
        raise ReplayJobImplementationPreflightError(
            "replay validation proof outputs are ambiguous"
        )
    output_names = {
        "calculation": next(iter(names_by_kind[CALCULATION_PROOF_KIND])),
        "trace": next(iter(names_by_kind[FIXED_HOLD_FAMILY_TRACE_PROOF_KIND])),
    }
    definition = _normalized_protocol_definition(
        plan.get("protocol_definition"),
        executable_ids=request.executable_ids,
        references_by_executable=references_by_executable,
    )
    from axiom_rift.research.fixed_hold_family_trace import (
        fixed_hold_protocol_definition_from_manifest,
    )

    typed_definition = fixed_hold_protocol_definition_from_manifest(
        plan["protocol_definition"]
    )
    expected_plan = build_fixed_hold_validation_plan(
        definition=typed_definition,
        mission_id=request.mission_id,
        executable_id=executable.identity,
        output_names=output_names,
    )
    if expected_plan != plan:
        raise ReplayJobImplementationPreflightError(
            "replay validation plan differs from the fixed-hold protocol"
        )
    expected_binding = {
        "evidence_depth": plan["evidence_depth"],
        "evidence_modes": plan["evidence_modes"],
        "planned_claims": plan["planned_claims"],
        "result_manifest_output": binding.get("result_manifest_output"),
        "validation_plan_hash": plan_hash,
        "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    }
    if dict(binding) != expected_binding:
        raise ReplayJobImplementationPreflightError(
            "replay scientific binding differs from its validation plan"
        )
    result_output = binding.get("result_manifest_output")
    prefixes: set[str] = set()
    for output_name, suffix in (
        (output_names["calculation"], "/calculation-proof.json"),
        (output_names["trace"], "/evaluation-trace.json"),
        (result_output, "/result.json"),
    ):
        if (
            type(output_name) is not str
            or not output_name.isascii()
            or not output_name.startswith("scientific/")
            or not output_name.endswith(suffix)
        ):
            raise ReplayJobImplementationPreflightError(
                "replay scientific output namespace is invalid"
            )
        prefixes.add(output_name[: -len(suffix)])
    if len(prefixes) != 1:
        raise ReplayJobImplementationPreflightError(
            "replay scientific outputs do not share one Job namespace"
        )
    profile = plan["adjudication_profile"]
    multiplicity = profile["multiplicity"]
    normalized_multiplicity = []

    def normalize_member_id(value: object) -> str:
        if type(value) is not str:
            raise ReplayJobImplementationPreflightError(
                "replay multiplicity member is invalid"
            )
        direct = references_by_executable.get(value)
        if direct is not None:
            return direct
        for role in ("feature", "opposite"):
            prefix = f"paired-control:{role}:"
            executable_id = value.removeprefix(prefix)
            if executable_id != value and executable_id in references_by_executable:
                return f"paired-control:{role}:" + references_by_executable[
                    executable_id
                ]
        raise ReplayJobImplementationPreflightError(
            "replay multiplicity family contains another Executable"
        )

    for item in multiplicity:
        member_id = item["member_id"]
        ordered_ids = item["ordered_member_ids"]
        member_reference = normalize_member_id(member_id)
        ordered_references = sorted(
            normalize_member_id(value) for value in ordered_ids
        )
        normalized_multiplicity.append(
            {
                "alpha_ppm": item["alpha_ppm"],
                "criterion_id": item["criterion_id"],
                "family_size": item["family_size"],
                "member_historical_reference": member_reference,
                "method": item["method"],
                "ordered_historical_references": ordered_references,
            }
        )
    normalized_multiplicity.sort(key=lambda item: item["criterion_id"])
    return {
        "adjudication_profile": {
            "decisive_risk_criterion_ids": profile[
                "decisive_risk_criterion_ids"
            ],
            "multiplicity": normalized_multiplicity,
            "promotion_criterion_ids": profile["promotion_criterion_ids"],
            "schema": profile["schema"],
        },
        "candidate_eligible_on_pass": plan["candidate_eligible_on_pass"],
        "criteria": plan["criteria"],
        "evidence_depth": plan["evidence_depth"],
        "evidence_modes": plan["evidence_modes"],
        "historical_reference_executable_id": references_by_executable[
            executable.identity
        ],
        "planned_claims": plan["planned_claims"],
        "proof_requirements": sorted(
            (
                {
                    "artifact_schema": item["artifact_schema"],
                    "evidence_mode": item["evidence_mode"],
                    "proof_kind": item["proof_kind"],
                }
                for item in requirements
            ),
            key=canonical_bytes,
        ),
        "protocol_definition": definition,
        "schema": "replay_validation_plan_scientific_surface.v1",
        "validator_id": binding["validator_id"],
    }


def _normalized_controlled_chassis(value: object) -> dict[str, Any]:
    chassis = _mapping("replay controlled chassis", value)
    baseline = chassis.get("baseline_executable")
    if not isinstance(baseline, dict):
        raise ReplayJobImplementationPreflightError(
            "replay controlled chassis baseline is absent"
        )
    _reference, baseline_surface = _normalized_executable_surface(
        baseline,
        require_historical_reference=False,
    )
    raw_manifests = baseline["component_manifests"]
    role_components: dict[str, list[int]] = {
        role: [] for role in ARCHITECTURE_ROLE_DOMAINS
    }
    for ordinal, manifest in enumerate(raw_manifests, 1):
        try:
            domain = component_manifest_domain(manifest)
        except ComponentManifestError as exc:
            raise ReplayJobImplementationPreflightError(str(exc)) from exc
        matches = tuple(
            role
            for role, domains in ARCHITECTURE_ROLE_DOMAINS.items()
            if domain in domains
        )
        if len(matches) > 1:
            raise ReplayJobImplementationPreflightError(
                "replay architecture role is ambiguous"
            )
        if matches:
            role_components[matches[0]].append(ordinal)
    architecture = _mapping(
        "replay controlled architecture", chassis.get("architecture")
    )
    roles = architecture.get("roles")
    if not isinstance(roles, dict) or set(roles) != set(role_components):
        raise ReplayJobImplementationPreflightError(
            "replay controlled architecture roles are invalid"
        )
    normalized_roles: dict[str, Any] = {}
    for role, ordinals in role_components.items():
        payload = _mapping(f"replay architecture role {role}", roles[role])
        surfaces = payload.get("component_semantic_surfaces")
        if not isinstance(surfaces, list) or len(surfaces) != len(ordinals):
            raise ReplayJobImplementationPreflightError(
                "replay architecture role composition drifted"
            )
        boundaries = _mapping(
            f"replay architecture role {role} boundaries",
            payload.get("boundary_bindings"),
        )
        engine_contract = boundaries.get("engine_contract")
        if engine_contract is not None:
            _ascii("replay architecture engine contract", engine_contract)
        normalized_roles[role] = {
            "absence": payload.get("absence"),
            "boundary_bindings": boundaries,
            "component_ordinals": ordinals,
            "parameter_bindings": _strip_prospective_context_parameter(
                payload.get("parameter_bindings")
            ),
            "role": payload.get("role"),
            "schema": payload.get("schema"),
        }
    equivalences = chassis.get("equivalences")
    if not isinstance(equivalences, list):
        raise ReplayJobImplementationPreflightError(
            "replay chassis equivalences are invalid"
        )
    normalized_equivalences: list[dict[str, Any]] = []
    for raw in equivalences:
        item = _mapping("replay chassis equivalence", raw)
        endpoints = []
        for name in (
            "canonical_component_manifest",
            "equivalent_component_manifest",
        ):
            try:
                endpoint = validated_component_manifest(item.get(name))
            except ComponentManifestError as exc:
                raise ReplayJobImplementationPreflightError(str(exc)) from exc
            endpoints.append(
                {
                    "protocol": endpoint["protocol"],
                    "spec": endpoint["spec"],
                }
            )
        normalized_equivalences.append(
            {
                "canonical_component": endpoints[0],
                "dimensions": item.get("dimensions"),
                "equivalent_component": endpoints[1],
                "schema": item.get("schema"),
            }
        )
    normalized_equivalences.sort(key=canonical_bytes)
    return {
        "architecture": {
            "roles": normalized_roles,
            "schema": architecture.get("schema"),
        },
        "baseline_executable": baseline_surface,
        "changed_domains": chassis.get("changed_domains"),
        "controlled_domains": chassis.get("controlled_domains"),
        "controlled_parameter_bindings": {
            name: _strip_prospective_context_parameter(parameters)
            for name, parameters in _mapping(
                "replay grouped parameter surface",
                chassis.get("controlled_parameter_bindings"),
            ).items()
        },
        "embedded_controlled_domains": chassis.get(
            "embedded_controlled_domains"
        ),
        "equivalences": normalized_equivalences,
        "schema": "replay_controlled_chassis_scientific_surface.v1",
    }


def _normalized_study_surface(value: object) -> dict[str, Any]:
    study = _mapping("replay Study payload", value)
    return {
        "changed_domains": study.get("changed_domains"),
        "controlled_chassis": _normalized_controlled_chassis(
            study.get("controlled_chassis")
        ),
        "controlled_domains": study.get("controlled_domains"),
        "material_identity": study.get("material_identity"),
        "mechanism_family": study.get("mechanism_family"),
        "portfolio_action": study.get("portfolio_action"),
        "primary_research_layer": study.get("primary_research_layer"),
        "question": study.get("question"),
        "semantic_proposal": study.get("semantic_proposal"),
        "semantic_question_core_id": study.get(
            "semantic_question_core_id"
        ),
    }


def derive_replay_job_scientific_surface(
    request: "ReplayJobImplementationPreflightRequest",
    *,
    study_payload: Mapping[str, Any],
    batch_payload: Mapping[str, Any],
    artifact_reader: Callable[[str], bytes],
    registered_batch_executable_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Derive the immutable science while excluding implementation identity."""

    if not isinstance(request, ReplayJobImplementationPreflightRequest):
        raise ReplayJobImplementationPreflightError(
            "replay scientific surface request is not typed"
        )
    study = _mapping("replay Study payload", study_payload)
    batch = _mapping("replay Batch payload", batch_payload)
    if study.get("mission_id") != request.mission_id or study.get(
        "replay_obligation_ids"
    ) != list(request.replay_obligation_ids):
        raise ReplayJobImplementationPreflightError(
            "replay Study differs from the preflight obligations"
        )
    executable_surfaces: list[dict[str, Any]] = []
    references_by_executable: dict[str, str] = {}
    for executable in request.executables:
        reference, surface = _normalized_executable_surface(
            executable.to_identity_payload(),
            require_historical_reference=True,
        )
        assert isinstance(reference, str)
        if reference in references_by_executable.values():
            raise ReplayJobImplementationPreflightError(
                "replay scientific family duplicates a historical reference"
            )
        references_by_executable[executable.identity] = reference
        executable_surfaces.append(surface)
    plan_surfaces = [
        _normalized_validation_plan_surface(
            request=request,
            executable=executable,
            binding=binding,
            references_by_executable=references_by_executable,
            artifact_reader=artifact_reader,
        )
        for executable, binding in zip(
            request.executables,
            request.scientific_binding_values(),
            strict=True,
        )
    ]
    original_family_ends = {
        plan["protocol_definition"][
            "original_family_end_global_exposure_count"
        ]
        for plan in plan_surfaces
    }
    if (
        len(original_family_ends) != 1
        or type(next(iter(original_family_ends), None)) is not int
    ):
        raise ReplayJobImplementationPreflightError(
            "replay original family exposure boundary is inconsistent"
        )
    original_family_end = next(iter(original_family_ends))
    protocol_ids = {
        plan["protocol_definition"]["protocol_id"]
        for plan in plan_surfaces
    }
    if len(protocol_ids) != 1:
        raise ReplayJobImplementationPreflightError(
            "replay family mixes protocol definitions"
        )
    strict_context_owner = (
        next(iter(protocol_ids)) == _FIXED_HOLD_REPLAY_PROTOCOL_ID
    )
    for executable in request.executables:
        _require_original_family_end_binding(
            executable.to_identity_payload(),
            expected=original_family_end,
            name="replay member Executable",
            strict_owner=strict_context_owner,
        )
    _require_controlled_chassis_original_family_end_binding(
        study.get("controlled_chassis"),
        expected=original_family_end,
        strict_owner=strict_context_owner,
    )
    by_reference = {
        surface["historical_reference_executable_id"]: surface
        for surface in executable_surfaces
    }
    plans_by_reference = {
        surface["historical_reference_executable_id"]: surface
        for surface in plan_surfaces
    }
    if set(by_reference) != set(plans_by_reference):
        raise ReplayJobImplementationPreflightError(
            "replay Executable and validation-plan families differ"
        )
    batch_spec = _mapping("replay Batch spec", batch.get("spec"))
    acceptance = _mapping(
        "replay Batch acceptance profile",
        batch_spec.get("acceptance_profile"),
    )
    concurrent = _mapping(
        "replay Batch concurrent family",
        acceptance.get("concurrent_family"),
    )
    family_ids = concurrent.get("executable_ids")
    registered_ids = (
        request.executable_ids
        if registered_batch_executable_ids is None
        else registered_batch_executable_ids
    )
    if (
        type(registered_ids) is not tuple
        or not registered_ids
        or any(type(value) is not str for value in registered_ids)
        or len(set(registered_ids)) != len(registered_ids)
        or not isinstance(family_ids, list)
        or sorted(family_ids) != sorted(registered_ids)
        or concurrent.get("family_size") != len(request.executables)
        or batch_spec.get("max_trials") != len(request.executables)
    ):
        raise ReplayJobImplementationPreflightError(
            "replay Batch differs from the exact preflight family"
        )
    normalized_acceptance = dict(acceptance)
    normalized_acceptance["concurrent_family"] = {
        "evaluation_mode": concurrent.get("evaluation_mode"),
        "family_size": concurrent.get("family_size"),
        "historical_references": sorted(references_by_executable.values()),
        "schema": concurrent.get("schema"),
    }
    members = [
        {
            "executable": by_reference[reference],
            "historical_reference_executable_id": reference,
            "validation_plan": plans_by_reference[reference],
        }
        for reference in sorted(by_reference)
    ]
    surface = {
        "batch": {
            "acceptance_profile": normalized_acceptance,
            "max_trials": batch_spec.get("max_trials"),
            "schema": batch_spec.get("schema"),
            "source_contract_ids": batch_spec.get("source_contract_ids"),
            "stop_rule": batch_spec.get("stop_rule"),
        },
        "callable_identity": request.callable_identity,
        "context_exclusion": {
            "parameter": _CONTEXT_ONLY_PARAMETER,
            "role": "writer_derived_prospective_exposure_observation",
        },
        "members": members,
        "mission_id": request.mission_id,
        "protocol_id": request.protocol_id,
        "replay_obligation_ids": list(request.replay_obligation_ids),
        "schema": SCIENTIFIC_SURFACE_SCHEMA,
        "study": _normalized_study_surface(study),
    }
    return _mapping("replay scientific surface", surface)


def replay_job_scientific_surface_hash(surface: Mapping[str, Any]) -> str:
    value = validated_replay_job_scientific_surface(surface)
    return canonical_digest(
        domain=SCIENTIFIC_SURFACE_HASH_DOMAIN,
        payload=value,
    )


def _exact_surface_keys(
    name: str,
    value: object,
    keys: set[str] | frozenset[str],
) -> dict[str, Any]:
    mapped = _mapping(name, value)
    if set(mapped) != set(keys):
        raise ReplayJobImplementationPreflightError(
            f"{name} schema is not exact"
        )
    return mapped


def _validated_component_scientific_surface(value: object) -> dict[str, Any]:
    component = _exact_surface_keys(
        "replay Component scientific surface",
        value,
        {
            "component_ordinal",
            "protocol",
            "schema",
            "semantic_dependencies",
            "spec",
        },
    )
    if (
        component.get("schema")
        != "replay_component_scientific_surface.v1"
        or type(component.get("component_ordinal")) is not int
        or component["component_ordinal"] < 1
    ):
        raise ReplayJobImplementationPreflightError(
            "replay Component scientific surface is malformed"
        )
    _ascii("replay Component protocol", component.get("protocol"))
    _mapping("replay Component spec", component.get("spec"))
    dependencies = component.get("semantic_dependencies")
    if not isinstance(dependencies, list):
        raise ReplayJobImplementationPreflightError(
            "replay Component semantic dependencies are malformed"
        )
    for dependency in dependencies:
        mapped = _mapping("replay Component semantic dependency", dependency)
        if set(mapped) == {"kind", "ordinal"}:
            valid = (
                mapped.get("kind") == "family_component"
                and type(mapped.get("ordinal")) is int
                and mapped["ordinal"] > 0
            )
        elif set(mapped) == {"identity", "kind"}:
            valid = mapped.get("kind") == "external_semantic_authority"
            if valid:
                _ascii(
                    "replay external semantic authority",
                    mapped.get("identity"),
                )
        else:
            valid = False
        if not valid:
            raise ReplayJobImplementationPreflightError(
                "replay Component semantic dependency is malformed"
            )
    return component


def _validated_executable_scientific_surface(value: object) -> dict[str, Any]:
    executable = _exact_surface_keys(
        "replay Executable scientific surface",
        value,
        {
            "clock_contract",
            "components",
            "cost_contract",
            "data_contract",
            "engine_contract",
            "historical_reference_executable_id",
            "parameters",
            "schema",
            "source_contracts",
            "split_contract",
        },
    )
    if executable.get("schema") != "replay_executable_scientific_surface.v1":
        raise ReplayJobImplementationPreflightError(
            "replay Executable scientific surface schema is invalid"
        )
    for name in (
        "clock_contract",
        "cost_contract",
        "data_contract",
        "engine_contract",
        "historical_reference_executable_id",
        "split_contract",
    ):
        _ascii(f"replay Executable {name}", executable.get(name))
    _mapping("replay Executable parameters", executable.get("parameters"))
    components = executable.get("components")
    if not isinstance(components, list) or not components:
        raise ReplayJobImplementationPreflightError(
            "replay Executable Component surface is empty"
        )
    normalized = [
        _validated_component_scientific_surface(item) for item in components
    ]
    if [item["component_ordinal"] for item in normalized] != list(
        range(1, len(normalized) + 1)
    ):
        raise ReplayJobImplementationPreflightError(
            "replay Executable Component ordinals are not exact"
        )
    sources = executable.get("source_contracts")
    if not isinstance(sources, list) or any(
        type(item) is not str or not item.isascii() for item in sources
    ):
        raise ReplayJobImplementationPreflightError(
            "replay Executable source contracts are malformed"
        )
    return executable


def validated_replay_job_scientific_surface(
    surface: Mapping[str, Any],
) -> dict[str, Any]:
    """Authenticate the exact v2 science skeleton before hashing or reuse."""

    value = _exact_surface_keys(
        "replay scientific surface",
        surface,
        {
            "batch",
            "callable_identity",
            "context_exclusion",
            "members",
            "mission_id",
            "protocol_id",
            "replay_obligation_ids",
            "schema",
            "study",
        },
    )
    if value.get("schema") != SCIENTIFIC_SURFACE_SCHEMA:
        raise ReplayJobImplementationPreflightError(
            "replay scientific surface schema is invalid"
        )
    for name in ("callable_identity", "mission_id", "protocol_id"):
        _ascii(f"replay scientific surface {name}", value.get(name))
    obligations = value.get("replay_obligation_ids")
    if (
        not isinstance(obligations, list)
        or not obligations
        or obligations != sorted(set(obligations))
    ):
        raise ReplayJobImplementationPreflightError(
            "replay scientific surface obligations are malformed"
        )
    for obligation_id in obligations:
        _prefixed(
            "replay scientific surface obligation",
            obligation_id,
            "historical-replay-obligation:",
        )
    exclusion = _exact_surface_keys(
        "replay scientific context exclusion",
        value.get("context_exclusion"),
        {"parameter", "role"},
    )
    if exclusion != {
        "parameter": _CONTEXT_ONLY_PARAMETER,
        "role": "writer_derived_prospective_exposure_observation",
    }:
        raise ReplayJobImplementationPreflightError(
            "replay scientific context exclusion is invalid"
        )
    batch = _exact_surface_keys(
        "replay scientific Batch surface",
        value.get("batch"),
        {
            "acceptance_profile",
            "max_trials",
            "schema",
            "source_contract_ids",
            "stop_rule",
        },
    )
    raw_acceptance = _mapping(
        "replay scientific acceptance profile",
        batch.get("acceptance_profile"),
    )
    acceptance_fields = {
        "candidate_authority",
        "concurrent_family",
        "exact_original_criteria",
        "historical_family_authority_id",
        "historical_family_identity",
        "replay_obligation_id",
    }
    if "replay_member_assignment_set_id" in raw_acceptance:
        acceptance_fields.add("replay_member_assignment_set_id")
    acceptance = _exact_surface_keys(
        "replay scientific acceptance profile",
        raw_acceptance,
        acceptance_fields,
    )
    concurrent = _exact_surface_keys(
        "replay scientific concurrent family",
        acceptance.get("concurrent_family"),
        {
            "evaluation_mode",
            "family_size",
            "historical_references",
            "schema",
        },
    )
    _prefixed(
        "replay historical family authority",
        acceptance.get("historical_family_authority_id"),
        "historical-family-authority:",
    )
    _prefixed(
        "replay historical family identity",
        acceptance.get("historical_family_identity"),
        "historical-family:",
    )
    assignment_set_id = acceptance.get(
        "replay_member_assignment_set_id"
    )
    if assignment_set_id is not None:
        _prefixed(
            "replay member assignment set",
            assignment_set_id,
            "replay-member-assignment-set:",
        )
    members = value.get("members")
    if not isinstance(members, list) or not members:
        raise ReplayJobImplementationPreflightError(
            "replay scientific member family is empty"
        )
    references: list[str] = []
    for raw_member in members:
        member = _exact_surface_keys(
            "replay scientific member",
            raw_member,
            {
                "executable",
                "historical_reference_executable_id",
                "validation_plan",
            },
        )
        reference = _ascii(
            "replay scientific historical reference",
            member.get("historical_reference_executable_id"),
        )
        executable = _validated_executable_scientific_surface(
            member.get("executable")
        )
        plan = _exact_surface_keys(
            "replay scientific validation plan",
            member.get("validation_plan"),
            {
                "adjudication_profile",
                "candidate_eligible_on_pass",
                "criteria",
                "evidence_depth",
                "evidence_modes",
                "historical_reference_executable_id",
                "planned_claims",
                "proof_requirements",
                "protocol_definition",
                "schema",
                "validator_id",
            },
        )
        protocol = _exact_surface_keys(
            "replay scientific protocol definition",
            plan.get("protocol_definition"),
            {
                "allowed_regimes",
                "clock_contract",
                "cost_contract",
                "dataset_sha256",
                "fold_ids",
                "historical_context_id",
                "historical_evaluation_artifacts",
                "historical_family",
                "inference",
                "invariance_keys",
                "material_identity",
                "original_family_end_global_exposure_count",
                "producer_implementation_roles",
                "prospective_historical_references",
                "protocol_id",
                "schema",
                "semantic_transition_policy",
                "split_artifact_sha256",
            },
        )
        if (
            plan.get("schema")
            != "replay_validation_plan_scientific_surface.v1"
            or executable.get("historical_reference_executable_id")
            != reference
            or plan.get("historical_reference_executable_id") != reference
        ):
            raise ReplayJobImplementationPreflightError(
                "replay scientific member reference or protocol drifted"
            )
        _ascii(
            "replay scientific protocol definition identity",
            protocol.get("protocol_id"),
        )
        references.append(reference)
    if (
        references != sorted(set(references))
        or concurrent.get("historical_references") != references
        or concurrent.get("family_size") != len(members)
        or batch.get("max_trials") != len(members)
        or acceptance.get("replay_obligation_id") not in obligations
    ):
        raise ReplayJobImplementationPreflightError(
            "replay scientific concurrent family is inconsistent"
        )
    study = _exact_surface_keys(
        "replay scientific Study surface",
        value.get("study"),
        {
            "changed_domains",
            "controlled_chassis",
            "controlled_domains",
            "material_identity",
            "mechanism_family",
            "portfolio_action",
            "primary_research_layer",
            "question",
            "semantic_proposal",
            "semantic_question_core_id",
        },
    )
    chassis = _exact_surface_keys(
        "replay scientific controlled chassis",
        study.get("controlled_chassis"),
        {
            "architecture",
            "baseline_executable",
            "changed_domains",
            "controlled_domains",
            "controlled_parameter_bindings",
            "embedded_controlled_domains",
            "equivalences",
            "schema",
        },
    )
    _validated_executable_scientific_surface(
        chassis.get("baseline_executable")
    )
    architecture = _exact_surface_keys(
        "replay scientific architecture",
        chassis.get("architecture"),
        {"roles", "schema"},
    )
    roles = _exact_surface_keys(
        "replay scientific architecture roles",
        architecture.get("roles"),
        set(ARCHITECTURE_ROLE_DOMAINS),
    )
    for role, raw_role in roles.items():
        role_surface = _exact_surface_keys(
            f"replay scientific architecture role {role}",
            raw_role,
            {
                "absence",
                "boundary_bindings",
                "component_ordinals",
                "parameter_bindings",
                "role",
                "schema",
            },
        )
        boundaries = _mapping(
            f"replay scientific architecture role {role} boundaries",
            role_surface.get("boundary_bindings"),
        )
        if role == "execution" and boundaries.get("engine_contract") != (
            chassis["baseline_executable"]["engine_contract"]
        ):
            raise ReplayJobImplementationPreflightError(
                "replay execution architecture omits its engine contract"
            )
    return value


def _executable_scientific_equivalence_surface(
    value: object,
    *,
    expected_original_family_end: int | None = None,
    strict_context_owner: bool = False,
) -> dict[str, Any]:
    executable = _validated_executable_scientific_surface(value)
    if expected_original_family_end is not None:
        _require_scientific_surface_context_binding(
            executable,
            expected=expected_original_family_end,
            strict_owner=strict_context_owner,
        )
    executable["engine_scientific_profile"] = _engine_scientific_profile(
        executable.pop("engine_contract")
    )
    executable["parameters"] = _strip_equivalence_context_parameters(
        executable["parameters"]
    )
    for component in executable["components"]:
        component["spec"] = _normalized_component_scientific_spec(
            component["protocol"],
            component["spec"],
        )
    return executable


def _require_scientific_surface_context_binding(
    executable: Mapping[str, Any],
    *,
    expected: int,
    strict_owner: bool,
) -> bool:
    components = executable.get("components")
    parameters = _mapping(
        "replay scientific Executable parameters",
        executable.get("parameters"),
    )
    if not isinstance(components, list):
        raise ReplayJobImplementationPreflightError(
            "replay scientific Executable Components are malformed"
        )
    owner_count = 0
    declares_original = False
    for raw in components:
        component = _mapping("replay scientific Component", raw)
        protocol = component.get("protocol")
        spec = _mapping(
            "replay scientific Component spec",
            component.get("spec"),
        )
        fields = spec.get("parameter_fields")
        if fields is not None and (
            not isinstance(fields, list)
            or any(type(field) is not str for field in fields)
        ):
            raise ReplayJobImplementationPreflightError(
                "replay scientific Component parameter fields are malformed"
            )
        fields = [] if fields is None else fields
        context_fields = set(fields).intersection(_CONTEXT_ONLY_PARAMETERS)
        if protocol == _FIXED_HOLD_CONTEXT_OWNER_PROTOCOL:
            owner_count += 1
            if (
                spec.get("historical_context_adjustment_authority")
                != "context_only_never_adjustment_factor"
                or _CONTEXT_ONLY_PARAMETER not in fields
            ):
                raise ReplayJobImplementationPreflightError(
                    "replay exposure context owner is malformed"
                )
            declares_original = (
                _ORIGINAL_FAMILY_CONTEXT_PARAMETER in fields
            )
        elif strict_owner and context_fields:
            raise ReplayJobImplementationPreflightError(
                "replay exposure context is declared by an unrelated Component"
            )
    if strict_owner and owner_count != 1:
        raise ReplayJobImplementationPreflightError(
            "replay exposure context requires one exact portfolio owner"
        )
    original_present = _ORIGINAL_FAMILY_CONTEXT_PARAMETER in parameters
    if strict_owner and original_present != declares_original:
        raise ReplayJobImplementationPreflightError(
            "replay original family exposure binding drifted"
        )
    if original_present and (
        type(parameters[_ORIGINAL_FAMILY_CONTEXT_PARAMETER]) is not int
        or parameters[_ORIGINAL_FAMILY_CONTEXT_PARAMETER] != expected
    ):
        raise ReplayJobImplementationPreflightError(
            "replay original family exposure boundary drifted"
        )
    return declares_original


def replay_job_scientific_equivalence_surface(
    surface: Mapping[str, Any],
) -> dict[str, Any]:
    """Project exact research semantics without implementation authority.

    The full surface remains the admission identity for one implementation.
    This narrower projection is used only to decide whether a replacement
    implementation reruns the same scientific question.  It deliberately
    retains data, split, clock, cost, component protocols and specifications,
    family membership, inference, criteria, and Study semantics.
    """

    value = validated_replay_job_scientific_surface(surface)
    value.pop("callable_identity")
    value.pop("protocol_id")
    value["schema"] = SCIENTIFIC_EQUIVALENCE_SCHEMA
    acceptance = value["batch"]["acceptance_profile"]
    family_authority_id = _prefixed(
        "replay historical family authority",
        acceptance.get("historical_family_authority_id"),
        "historical-family-authority:",
    )
    replay_obligation_id = _prefixed(
        "replay historical obligation",
        acceptance.get("replay_obligation_id"),
        "historical-replay-obligation:",
    )
    family_identity = _prefixed(
        "replay historical family identity",
        acceptance.get("historical_family_identity"),
        "historical-family:",
    )
    if replay_obligation_id not in value["replay_obligation_ids"]:
        raise ReplayJobImplementationPreflightError(
            "replay historical context subject differs from its obligation"
        )
    context_subject = {
        "historical_family_authority_id": family_authority_id,
        "historical_family_identity": family_identity,
        "replay_obligation_id": replay_obligation_id,
        "schema": "replay_historical_context_subject.v1",
    }
    original_family_ends = {
        member["validation_plan"]["protocol_definition"][
            "original_family_end_global_exposure_count"
        ]
        for member in value["members"]
    }
    protocol_ids = {
        member["validation_plan"]["protocol_definition"]["protocol_id"]
        for member in value["members"]
    }
    if (
        len(original_family_ends) != 1
        or type(next(iter(original_family_ends), None)) is not int
        or len(protocol_ids) != 1
    ):
        raise ReplayJobImplementationPreflightError(
            "replay replacement protocol context is inconsistent"
        )
    original_family_end = next(iter(original_family_ends))
    strict_context_owner = (
        next(iter(protocol_ids)) == _FIXED_HOLD_REPLAY_PROTOCOL_ID
    )

    def normalize_plan(plan: dict[str, Any]) -> None:
        definition = plan["protocol_definition"]
        raw_context_id = _ascii(
            "replay protocol historical context",
            definition.pop("historical_context_id"),
        )
        if raw_context_id not in {
            family_authority_id,
            replay_obligation_id,
        }:
            raise ReplayJobImplementationPreflightError(
                "replay historical context subject is unrelated"
            )
        historical_family = _mapping(
            "replay protocol historical family",
            definition.get("historical_family"),
        )
        derived_family_identity = "historical-family:" + canonical_digest(
            domain="historical-family-spec",
            payload=historical_family,
        )
        if derived_family_identity != family_identity:
            raise ReplayJobImplementationPreflightError(
                "replay historical context family identity drifted"
            )
        definition["historical_context_subject"] = context_subject
        definition["producer_implementation_profile"] = (
            _producer_role_scientific_profile(
                definition.get("protocol_id"),
                definition.pop("producer_implementation_roles"),
            )
        )

    for member in value["members"]:
        member["executable"] = (
            _executable_scientific_equivalence_surface(
                member["executable"],
                expected_original_family_end=original_family_end,
                strict_context_owner=strict_context_owner,
            )
        )
        normalize_plan(member["validation_plan"])

    chassis = value["study"]["controlled_chassis"]
    baseline_declares_original = (
        _require_scientific_surface_context_binding(
            chassis["baseline_executable"],
            expected=original_family_end,
            strict_owner=strict_context_owner,
        )
    )
    chassis["baseline_executable"] = (
        _executable_scientific_equivalence_surface(
            chassis["baseline_executable"],
            expected_original_family_end=original_family_end,
            strict_context_owner=strict_context_owner,
        )
    )
    if strict_context_owner:
        for surface_kind, bindings in (
            (
                "controlled",
                chassis["controlled_parameter_bindings"],
            ),
            ("architecture", chassis["architecture"]["roles"]),
        ):
            for owner, raw in bindings.items():
                parameters = (
                    _mapping("replay architecture role", raw).get(
                        "parameter_bindings"
                    )
                    if surface_kind == "architecture"
                    else raw
                )
                parameter_map = _mapping(
                    "replay scientific chassis parameter binding",
                    parameters,
                )
                present = set(parameter_map).intersection(
                    _CONTEXT_ONLY_PARAMETERS
                )
                if present and owner != "portfolio":
                    raise ReplayJobImplementationPreflightError(
                        "replay exposure context escaped its portfolio binding"
                    )
                if _ORIGINAL_FAMILY_CONTEXT_PARAMETER in parameter_map and (
                    type(
                        parameter_map[_ORIGINAL_FAMILY_CONTEXT_PARAMETER]
                    )
                    is not int
                    or parameter_map[_ORIGINAL_FAMILY_CONTEXT_PARAMETER]
                    != original_family_end
                ):
                    raise ReplayJobImplementationPreflightError(
                        "replay original family exposure boundary drifted"
                    )
                if (
                    owner == "portfolio"
                    and surface_kind == "architecture"
                    and (
                        _ORIGINAL_FAMILY_CONTEXT_PARAMETER in parameter_map
                    )
                    != baseline_declares_original
                ):
                    raise ReplayJobImplementationPreflightError(
                        "replay original family exposure binding drifted"
                    )
    chassis["controlled_parameter_bindings"] = (
        _strip_grouped_context_parameters(
            chassis["controlled_parameter_bindings"]
        )
    )
    for role in chassis["architecture"]["roles"].values():
        boundaries = role["boundary_bindings"]
        if "engine_contract" in boundaries:
            boundaries["engine_scientific_profile"] = (
                _engine_scientific_profile(
                    boundaries.pop("engine_contract")
                )
            )
        role["parameter_bindings"] = _strip_equivalence_context_parameters(
            role["parameter_bindings"]
        )
    return _mapping("replay scientific equivalence surface", value)


def replay_job_scientific_equivalence_hash(
    surface: Mapping[str, Any],
) -> str:
    return canonical_digest(
        domain=SCIENTIFIC_EQUIVALENCE_HASH_DOMAIN,
        payload=replay_job_scientific_equivalence_surface(surface),
    )


def _accepted_replacement_scientific_surface(
    accepted_payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    accepted = _mapping(
        "accepted replacement replay preflight payload",
        accepted_payload,
    )
    surface = accepted.get("scientific_surface")
    surface_hash = (
        replay_job_scientific_surface_hash(surface)
        if isinstance(surface, Mapping)
        else None
    )
    manifests = accepted.get("executable_manifests")
    references = replay_executable_reference_map(manifests)
    executable_ids = accepted.get("executable_ids")
    replacement_for = accepted.get("replacement_for_preflight_id")
    if (
        accepted.get("schema") != PREFLIGHT_SCHEMA
        or accepted.get("outcome") != "accepted"
        or not isinstance(accepted.get("source_closure_authority"), Mapping)
        or accepted.get("failure_detail") is not None
        or accepted.get("failure_fingerprint") is not None
        or accepted.get("reason_code") is not None
        or accepted.get("remediation_kind") is not None
        or not isinstance(replacement_for, str)
        or not replacement_for.startswith("job-implementation-preflight:")
        or not isinstance(surface, Mapping)
        or surface_hash != accepted.get("scientific_surface_hash")
        or surface.get("mission_id") != accepted.get("mission_id")
        or surface.get("protocol_id") != accepted.get("protocol_id")
        or surface.get("callable_identity")
        != accepted.get("callable_identity")
        or surface.get("replay_obligation_ids")
        != accepted.get("replay_obligation_ids")
        or not isinstance(executable_ids, list)
        or any(type(value) is not str for value in executable_ids)
        or len(executable_ids) != len(set(executable_ids))
        or set(executable_ids) != set(references.values())
    ):
        raise ReplayJobImplementationPreflightError(
            "accepted replacement replay preflight is malformed"
        )
    return accepted, validated_replay_job_scientific_surface(surface)


def require_replacement_replay_baseline_semantics(
    *,
    accepted_payload: Mapping[str, Any],
    baseline_executable_manifest: Mapping[str, Any],
) -> str:
    """Allow a new byte identity only when its baseline science is unchanged."""

    _accepted, surface = _accepted_replacement_scientific_surface(
        accepted_payload
    )
    original_family_ends = {
        member["validation_plan"]["protocol_definition"][
            "original_family_end_global_exposure_count"
        ]
        for member in surface["members"]
    }
    if (
        len(original_family_ends) != 1
        or type(next(iter(original_family_ends), None)) is not int
    ):
        raise ReplayJobImplementationPreflightError(
            "accepted replay original family boundary is inconsistent"
        )
    protocol_ids = {
        member["validation_plan"]["protocol_definition"]["protocol_id"]
        for member in surface["members"]
    }
    _require_original_family_end_binding(
        baseline_executable_manifest,
        expected=next(iter(original_family_ends)),
        name="replacement replay baseline Executable",
        strict_owner=(
            protocol_ids == {_FIXED_HOLD_REPLAY_PROTOCOL_ID}
        ),
    )
    _reference, replacement_baseline = _normalized_executable_surface(
        baseline_executable_manifest,
        require_historical_reference=False,
    )
    accepted_baseline = surface["study"]["controlled_chassis"][
        "baseline_executable"
    ]
    if _executable_scientific_equivalence_surface(
        replacement_baseline
    ) != _executable_scientific_equivalence_surface(accepted_baseline):
        raise ReplayJobImplementationPreflightError(
            "replacement replay baseline changed its scientific semantics"
        )
    return replay_job_scientific_equivalence_hash(surface)


def require_replacement_replay_study_semantics(
    *,
    accepted_payload: Mapping[str, Any],
    study_payload: Mapping[str, Any],
) -> str:
    """Bind one prospective successor Study to accepted replacement science."""

    accepted, surface = _accepted_replacement_scientific_surface(
        accepted_payload
    )
    proposed = _mapping("replacement replay prospective Study", study_payload)
    if (
        set(proposed)
        != {
            "changed_domains",
            "controlled_chassis",
            "controlled_domains",
            "material_identity",
            "mechanism_family",
            "mission_id",
            "portfolio_action",
            "primary_research_layer",
            "question",
            "replay_obligation_ids",
            "semantic_proposal",
            "semantic_question_core_id",
        }
        or proposed.get("mission_id") != accepted.get("mission_id")
        or proposed.get("replay_obligation_ids")
        != accepted.get("replay_obligation_ids")
    ):
        raise ReplayJobImplementationPreflightError(
            "replacement replay Study differs from its accepted authority"
        )
    original_family_ends = {
        member["validation_plan"]["protocol_definition"][
            "original_family_end_global_exposure_count"
        ]
        for member in surface["members"]
    }
    if (
        len(original_family_ends) != 1
        or type(next(iter(original_family_ends), None)) is not int
    ):
        raise ReplayJobImplementationPreflightError(
            "accepted replay original family boundary is inconsistent"
        )
    protocol_ids = {
        member["validation_plan"]["protocol_definition"]["protocol_id"]
        for member in surface["members"]
    }
    _require_controlled_chassis_original_family_end_binding(
        proposed.get("controlled_chassis"),
        expected=next(iter(original_family_ends)),
        strict_owner=(
            protocol_ids == {_FIXED_HOLD_REPLAY_PROTOCOL_ID}
        ),
    )
    prospective_surface = _mapping(
        "replacement replay prospective scientific surface",
        surface,
    )
    prospective_surface["study"] = _normalized_study_surface(proposed)
    if replay_job_scientific_equivalence_surface(
        prospective_surface
    ) != replay_job_scientific_equivalence_surface(surface):
        raise ReplayJobImplementationPreflightError(
            "replacement replay Study changed its scientific semantics"
        )
    return replay_job_scientific_equivalence_hash(surface)


def replay_executable_reference_map(
    executable_manifests: object,
) -> dict[str, str]:
    """Return historical-reference -> Executable for one exact family."""

    if not isinstance(executable_manifests, (list, tuple)):
        raise ReplayJobImplementationPreflightError(
            "replay Executable manifest family is invalid"
        )
    result: dict[str, str] = {}
    for raw in executable_manifests:
        if isinstance(raw, ExecutableSpec):
            manifest = raw.to_identity_payload()
            executable_id = raw.identity
        elif isinstance(raw, Mapping):
            manifest = _mapping("replay Executable manifest", raw)
            executable_id = "executable:" + canonical_digest(
                domain="executable",
                payload=manifest,
            )
        else:
            raise ReplayJobImplementationPreflightError(
                "replay Executable manifest family is malformed"
            )
        reference, _surface = _normalized_executable_surface(
            manifest,
            require_historical_reference=True,
        )
        assert isinstance(reference, str)
        if reference in result:
            raise ReplayJobImplementationPreflightError(
                "replay Executable family duplicates a historical reference"
            )
        result[reference] = executable_id
    if not result:
        raise ReplayJobImplementationPreflightError(
            "replay Executable family is empty"
        )
    return result


def require_replacement_replay_job_scientific_surface(
    *,
    prior_preflight_id: str,
    prior_payload: Mapping[str, Any],
    replacement_payload: Mapping[str, Any],
) -> None:
    """Require exact old science and a genuinely new implementation family."""

    _prefixed(
        "prior replay implementation preflight",
        prior_preflight_id,
        "job-implementation-preflight:",
    )
    prior = _mapping("prior replay preflight payload", prior_payload)
    replacement = _mapping(
        "replacement replay preflight payload",
        replacement_payload,
    )
    prior_surface = prior.get("scientific_surface")
    replacement_surface = replacement.get("scientific_surface")
    prior_hash = (
        replay_job_scientific_surface_hash(prior_surface)
        if isinstance(prior_surface, Mapping)
        else None
    )
    replacement_hash = (
        replay_job_scientific_surface_hash(replacement_surface)
        if isinstance(replacement_surface, Mapping)
        else None
    )
    prior_equivalence = (
        replay_job_scientific_equivalence_surface(prior_surface)
        if isinstance(prior_surface, Mapping)
        else None
    )
    replacement_equivalence = (
        replay_job_scientific_equivalence_surface(replacement_surface)
        if isinstance(replacement_surface, Mapping)
        else None
    )
    prior_references = replay_executable_reference_map(
        prior.get("executable_manifests")
    )
    replacement_references = replay_executable_reference_map(
        replacement.get("executable_manifests")
    )
    prior_ids = prior.get("executable_ids")
    replacement_ids = replacement.get("executable_ids")
    if (
        not isinstance(prior_ids, list)
        or any(type(value) is not str for value in prior_ids)
        or not isinstance(replacement_ids, list)
        or any(type(value) is not str for value in replacement_ids)
    ):
        raise ReplayJobImplementationPreflightError(
            "replacement replay implementation changed its scientific surface"
        )
    common_invalid = (
        prior.get("schema") != PREFLIGHT_SCHEMA
        or prior.get("outcome") != "rejected"
        or prior.get("remediation_kind") != REPLACEMENT_REQUIRED
        or replacement.get("schema") != PREFLIGHT_SCHEMA
        or replacement.get("replacement_for_preflight_id")
        != prior_preflight_id
        or replacement.get("mission_id") != prior.get("mission_id")
        or replacement.get("replay_obligation_ids")
        != prior.get("replay_obligation_ids")
        or prior.get("scientific_surface_hash") != prior_hash
        or replacement.get("scientific_surface_hash") != replacement_hash
        or not isinstance(prior_surface, Mapping)
        or not isinstance(replacement_surface, Mapping)
        or prior_surface.get("callable_identity")
        != prior.get("callable_identity")
        or replacement_surface.get("callable_identity")
        != replacement.get("callable_identity")
        or prior_surface.get("protocol_id") != prior.get("protocol_id")
        or replacement_surface.get("protocol_id")
        != replacement.get("protocol_id")
        or replacement_equivalence != prior_equivalence
        or set(prior_references) != set(replacement_references)
        or set(prior_ids) != set(prior_references.values())
        or set(replacement_ids) != set(replacement_references.values())
    )
    if common_invalid:
        raise ReplayJobImplementationPreflightError(
            "replacement replay implementation changed its scientific surface"
        )
    if (
        replacement.get("implementation_identity")
        == prior.get("implementation_identity")
        or replacement_ids == prior_ids
        or replacement.get("executable_manifests")
        == prior.get("executable_manifests")
        or set(prior_references.values()).intersection(
            replacement_references.values()
        )
        or any(
            prior_references[reference]
            == replacement_references[reference]
            for reference in prior_references
        )
    ):
        raise ReplayJobImplementationPreflightError(
            "replacement replay implementation reused an old Executable"
        )


def require_active_replay_job_replacement_binding(
    *,
    accepted_payload: Mapping[str, Any],
    active_payload: Mapping[str, Any],
) -> None:
    """Bind the successor active family to its accepted replacement probe."""

    accepted, accepted_surface = _accepted_replacement_scientific_surface(
        accepted_payload,
    )
    active = _mapping("active replacement replay preflight payload", active_payload)
    active_surface = active.get("scientific_surface")
    accepted_hash = (
        replay_job_scientific_surface_hash(accepted_surface)
        if isinstance(accepted_surface, Mapping)
        else None
    )
    active_hash = (
        replay_job_scientific_surface_hash(active_surface)
        if isinstance(active_surface, Mapping)
        else None
    )
    accepted_equivalence = (
        replay_job_scientific_equivalence_surface(accepted_surface)
        if isinstance(accepted_surface, Mapping)
        else None
    )
    active_equivalence = (
        replay_job_scientific_equivalence_surface(active_surface)
        if isinstance(active_surface, Mapping)
        else None
    )
    if (
        accepted.get("schema") != PREFLIGHT_SCHEMA
        or accepted.get("outcome") != "accepted"
        or not isinstance(accepted.get("source_closure_authority"), Mapping)
        or accepted.get("failure_fingerprint") is not None
        or accepted.get("reason_code") is not None
        or accepted_hash != accepted.get("scientific_surface_hash")
        or active_hash != active.get("scientific_surface_hash")
        or not isinstance(accepted_surface, Mapping)
        or not isinstance(active_surface, Mapping)
        or accepted_surface.get("callable_identity")
        != accepted.get("callable_identity")
        or active_surface.get("callable_identity")
        != active.get("callable_identity")
        or accepted_surface.get("protocol_id")
        != accepted.get("protocol_id")
        or active_surface.get("protocol_id") != active.get("protocol_id")
        or active_equivalence != accepted_equivalence
        or active.get("mission_id") != accepted.get("mission_id")
        or active.get("protocol_id") != accepted.get("protocol_id")
        or active.get("callable_identity") != accepted.get("callable_identity")
        or active.get("implementation_identity")
        != accepted.get("implementation_identity")
        or active.get("replay_obligation_ids")
        != accepted.get("replay_obligation_ids")
        or active.get("replacement_for_preflight_id") is not None
        or active.get("executable_ids") != accepted.get("executable_ids")
        or active.get("executable_manifests")
        != accepted.get("executable_manifests")
    ):
        raise ReplayJobImplementationPreflightError(
            "active replay family differs from its accepted replacement"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayJobImplementationPreflightRequest:
    """One exact concurrent replay family and its prospective Job closure."""

    mission_id: str
    protocol_id: str
    callable_identity: str
    implementation_identity: str
    executables: tuple[ExecutableSpec, ...]
    scientific_bindings: InitVar[tuple[Mapping[str, Any], ...]]
    replay_obligation_ids: tuple[str, ...]
    replacement_for_preflight_id: str | None = None
    _scientific_binding_bytes: tuple[bytes, ...] = field(
        init=False,
        repr=False,
        compare=False,
    )
    identity: str = field(init=False)

    def __post_init__(
        self,
        scientific_bindings: tuple[Mapping[str, Any], ...],
    ) -> None:
        _ascii("preflight Mission id", self.mission_id)
        _ascii("preflight protocol id", self.protocol_id)
        _ascii("preflight callable identity", self.callable_identity)
        _digest("preflight implementation identity", self.implementation_identity)
        if (
            type(self.executables) is not tuple
            or not self.executables
            or any(not isinstance(item, ExecutableSpec) for item in self.executables)
            or len({item.identity for item in self.executables})
            != len(self.executables)
        ):
            raise ReplayJobImplementationPreflightError(
                "preflight Executables must be a non-empty unique tuple"
            )
        if (
            type(scientific_bindings) is not tuple
            or len(scientific_bindings) != len(self.executables)
            or any(not isinstance(item, Mapping) for item in scientific_bindings)
        ):
            raise ReplayJobImplementationPreflightError(
                "preflight scientific bindings must match the Executable family"
            )
        binding_bytes = tuple(canonical_bytes(dict(item)) for item in scientific_bindings)
        bindings = tuple(parse_canonical(value) for value in binding_bytes)
        for binding in bindings:
            if (
                not isinstance(binding, dict)
                or type(binding.get("validation_plan_hash")) is not str
            ):
                raise ReplayJobImplementationPreflightError(
                    "preflight scientific binding lacks a validation plan"
                )
            _digest(
                "preflight validation plan",
                binding["validation_plan_hash"],
            )
        obligations = tuple(sorted(self.replay_obligation_ids))
        if (
            type(self.replay_obligation_ids) is not tuple
            or not obligations
            or len(obligations) != len(set(obligations))
        ):
            raise ReplayJobImplementationPreflightError(
                "preflight replay obligations must be unique and non-empty"
            )
        for obligation_id in obligations:
            _prefixed(
                "preflight replay obligation",
                obligation_id,
                "historical-replay-obligation:",
            )
        if self.replacement_for_preflight_id is not None:
            _prefixed(
                "replaced replay preflight",
                self.replacement_for_preflight_id,
                "job-implementation-preflight:",
            )
        object.__setattr__(self, "replay_obligation_ids", obligations)
        object.__setattr__(self, "_scientific_binding_bytes", binding_bytes)
        object.__setattr__(
            self,
            "identity",
            "replay-job-implementation-preflight-request:"
            + canonical_digest(
                domain="replay-job-implementation-preflight-request",
                payload=self.to_identity_payload(),
            ),
        )

    @property
    def executable_ids(self) -> tuple[str, ...]:
        return tuple(item.identity for item in self.executables)

    def scientific_binding_values(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            parse_canonical(value) for value in self._scientific_binding_bytes
        )

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "callable_identity": self.callable_identity,
            "executable_manifests": [
                item.to_identity_payload() for item in self.executables
            ],
            "implementation_identity": self.implementation_identity,
            "mission_id": self.mission_id,
            "protocol_id": self.protocol_id,
            "replacement_for_preflight_id": self.replacement_for_preflight_id,
            "replay_obligation_ids": list(self.replay_obligation_ids),
            "schema": "replay_job_implementation_preflight_request.v1",
            "scientific_bindings": list(self.scientific_binding_values()),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayJobImplementationPreflightResult:
    """A deterministic accepted or rejected implementation inspection."""

    request: ReplayJobImplementationPreflightRequest
    accepted: bool
    artifact_hashes: tuple[str, ...] = ()
    component_implementation_hashes: tuple[str, ...] = ()
    source_closure_authority: Mapping[str, Any] | None = None
    reason_code: str | None = None
    failure_detail: str | None = None
    failure_fingerprint: str | None = None
    remediation_kind: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, ReplayJobImplementationPreflightRequest):
            raise ReplayJobImplementationPreflightError(
                "preflight result request is not typed"
            )
        for label, values in (
            ("preflight artifact", self.artifact_hashes),
            ("preflight Component implementation", self.component_implementation_hashes),
        ):
            if type(values) is not tuple or values != tuple(sorted(set(values))):
                raise ReplayJobImplementationPreflightError(
                    f"{label} hashes must be sorted and unique"
                )
            for value in values:
                _digest(label, value)
        if self.accepted:
            if (
                not self.artifact_hashes
                or not isinstance(self.source_closure_authority, Mapping)
                or any(
                    value is not None
                    for value in (
                        self.reason_code,
                        self.failure_detail,
                        self.failure_fingerprint,
                        self.remediation_kind,
                    )
                )
            ):
                raise ReplayJobImplementationPreflightError(
                    "accepted preflight lacks exact source authority"
                )
        else:
            _ascii("preflight rejection reason", self.reason_code)
            _ascii("preflight rejection detail", self.failure_detail)
            _digest("preflight failure fingerprint", self.failure_fingerprint)
            if self.remediation_kind not in {
                SAME_IDENTITY_REPAIR,
                REPLACEMENT_REQUIRED,
            }:
                raise ReplayJobImplementationPreflightError(
                    "rejected preflight lacks a typed remediation boundary"
                )
            if self.source_closure_authority is not None:
                raise ReplayJobImplementationPreflightError(
                    "rejected preflight cannot grant source authority"
                )

    @property
    def status(self) -> str:
        return "accepted" if self.accepted else "rejected"

    def to_record_payload(self) -> dict[str, Any]:
        return {
            "artifact_hashes": list(self.artifact_hashes),
            "callable_identity": self.request.callable_identity,
            "component_implementation_hashes": list(
                self.component_implementation_hashes
            ),
            "executable_ids": list(self.request.executable_ids),
            "executable_manifests": [
                executable.to_identity_payload()
                for executable in self.request.executables
            ],
            "failure_detail": self.failure_detail,
            "failure_fingerprint": self.failure_fingerprint,
            "implementation_identity": self.request.implementation_identity,
            "mission_id": self.request.mission_id,
            "outcome": self.status,
            "protocol_id": self.request.protocol_id,
            "reason_code": self.reason_code,
            "remediation_kind": self.remediation_kind,
            "replacement_for_preflight_id": (
                self.request.replacement_for_preflight_id
            ),
            "replay_obligation_ids": list(
                self.request.replay_obligation_ids
            ),
            "request_identity": self.request.identity,
            "schema": PREFLIGHT_SCHEMA,
            "source_closure_authority": (
                None
                if self.source_closure_authority is None
                else dict(self.source_closure_authority)
            ),
            "validation_plan_hashes": sorted(
                binding["validation_plan_hash"]
                for binding in self.request.scientific_binding_values()
            ),
        }


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, HistoricalReplayImplementationAuthorityError):
        return "historical_replay_lineage_invalid"
    if isinstance(exc, JobImplementationAuthorityError):
        return "implementation_manifest_invalid"
    return "source_closure_invalid"


def replay_job_implementation_remediation(exc: Exception) -> str:
    """Classify whether exact bytes can be restored or identity must change."""

    if (
        isinstance(exc, ImplementationClosureError)
        and exc.same_identity_repairable
    ):
        return SAME_IDENTITY_REPAIR
    return REPLACEMENT_REQUIRED


def require_durable_replay_job_implementation_preflight(
    result: ReplayJobImplementationPreflightResult,
) -> None:
    """Keep same-identity restoration outside the durable science journal."""

    if not isinstance(result, ReplayJobImplementationPreflightResult):
        raise ReplayJobImplementationPreflightError(
            "durable replay implementation result is not typed"
        )
    if (
        not result.accepted
        and result.remediation_kind == SAME_IDENTITY_REPAIR
    ):
        raise ReplayJobImplementationPreflightError(
            "same-identity source repair is required before a durable replay "
            "implementation decision"
        )


def evaluate_replay_job_implementation_preflight(
    request: ReplayJobImplementationPreflightRequest,
    *,
    index: LocalIndex | LocalIndexView,
    artifact_reader: Callable[[str], bytes],
    source_root: Path,
) -> ReplayJobImplementationPreflightResult:
    """Inspect current bytes without registering a trial or reserving budget."""

    if not isinstance(request, ReplayJobImplementationPreflightRequest):
        raise ReplayJobImplementationPreflightError(
            "replay implementation preflight request is not typed"
        )
    if not isinstance(source_root, Path):
        raise ReplayJobImplementationPreflightError(
            "replay implementation source root must be a Path"
        )
    try:
        artifact_hashes: tuple[str, ...] | None = None
        component_hashes: set[str] = set()
        for executable, binding in zip(
            request.executables,
            request.scientific_binding_values(),
            strict=True,
        ):
            spec = {
                "callable_identity": request.callable_identity,
                "evidence_subject": {
                    "kind": "Executable",
                    "id": executable.identity,
                },
                "implementation_identity": request.implementation_identity,
                "scientific_binding": binding,
            }
            historical_sources = authenticated_historical_implementation_sources(
                spec,
                index=index,
                artifact_reader=artifact_reader,
            )
            manifest = require_job_implementation_evidence(
                spec,
                artifact_reader=artifact_reader,
                historical_source_authorities=historical_sources,
            )
            if manifest.get("protocol") != request.protocol_id:
                raise JobImplementationAuthorityError(
                    "Job implementation protocol differs from replay preflight"
                )
            current_artifacts = tuple(manifest["artifact_hashes"])
            if artifact_hashes is None:
                artifact_hashes = current_artifacts
            elif artifact_hashes != current_artifacts:
                raise JobImplementationAuthorityError(
                    "replay family implementation manifests disagree"
                )
            component_hashes.update(
                require_job_implementation_closure(
                    executable_manifest=executable.to_identity_payload(),
                    job_artifact_hashes=current_artifacts,
                    artifact_reader=artifact_reader,
                )
            )
        if artifact_hashes is None:
            raise JobImplementationAuthorityError(
                "replay family implementation manifest is absent"
            )
        closure_hashes = implementation_source_closure_hashes(
            implementation_manifest={"artifact_hashes": list(artifact_hashes)},
            artifact_reader=artifact_reader,
        )
        if not closure_hashes:
            raise ImplementationClosureError(
                "prospective replay Job requires one current source closure"
            )
        source_authority = require_current_job_source_closure(
            callable_identity=request.callable_identity,
            job_artifact_hashes=artifact_hashes,
            artifact_reader=artifact_reader,
            source_root=source_root,
            verified_non_source_artifact_hashes=tuple(sorted(component_hashes)),
        )
        return ReplayJobImplementationPreflightResult(
            request=request,
            accepted=True,
            artifact_hashes=artifact_hashes,
            component_implementation_hashes=tuple(sorted(component_hashes)),
            source_closure_authority=source_authority,
        )
    except (
        HistoricalReplayImplementationAuthorityError,
        ImplementationClosureError,
        JobImplementationAuthorityError,
    ) as exc:
        detail = str(exc)
        if not detail or not detail.isascii():
            detail = type(exc).__name__
        return ReplayJobImplementationPreflightResult(
            request=request,
            accepted=False,
            reason_code=_failure_code(exc),
            failure_detail=detail,
            failure_fingerprint=canonical_digest(
                domain="replay-job-implementation-preflight-failure",
                payload={
                    "detail": detail,
                    "exception": type(exc).__name__,
                    "request_identity": request.identity,
                    "remediation_kind": replay_job_implementation_remediation(
                        exc
                    ),
                },
            ),
            remediation_kind=replay_job_implementation_remediation(exc),
        )


__all__ = [
    "PREFLIGHT_SCHEMA",
    "REPLACEMENT_REQUIRED",
    "SAME_IDENTITY_REPAIR",
    "SCIENTIFIC_SURFACE_HASH_DOMAIN",
    "SCIENTIFIC_SURFACE_SCHEMA",
    "ReplayJobImplementationPreflightError",
    "ReplayJobImplementationPreflightRequest",
    "ReplayJobImplementationPreflightResult",
    "derive_replay_job_scientific_surface",
    "evaluate_replay_job_implementation_preflight",
    "replay_executable_reference_map",
    "replay_job_scientific_surface_hash",
    "replay_job_implementation_remediation",
    "validated_replay_job_scientific_surface",
    "require_active_replay_job_replacement_binding",
    "require_durable_replay_job_implementation_preflight",
    "require_replacement_replay_job_scientific_surface",
]
