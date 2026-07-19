"""Real event-5433 and durable inputs for fixed-hold Repair E2E tests."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.operations.fixed_hold_repair_equivalence import (
    FIXED_HOLD_AUTHORITY_CORRECTION_NEW_IMPLEMENTATION_IDENTITY,
    FIXED_HOLD_AUTHORITY_CORRECTION_OLD_IMPLEMENTATION_IDENTITY,
    _FIXED_HOLD_JOB_SOURCE_PATHS,
)


EVENT_SEQUENCE = 5433
PREFLIGHT_ID = (
    "job-implementation-preflight:"
    "602b03f04306c02523b0f6b4f3376006ff91ba3f001fd9ad8a47d722798b584c"
)
EXECUTABLE_ID = (
    "executable:6732b3db490f9c7aafc3bb907240fc6546f46f086f56591c0532e0c0154e6a0f"
)
CALLABLE_IDENTITY = (
    "axiom_rift.research.volatility_duration_fixed_hold_job."
    "execute_volatility_duration_fixed_hold_job.v1"
)
PROTOCOL_ID = "python.source.volatility_duration_fixed_hold.v1"
COMPONENT_IMPLEMENTATION_HASHES = (
    "98543544864c1cf071ec1891c554303e45ce7c5b7985f5bd1dd065c66f5b3467",
    "de46f60f38193ee81cd427b073871648553afaad144b4154618458b713cc9098",
)

AUTHORITY_AND_FOUNDATION_PATHS = (
    "OPERATING_DIRECTION.md",
    "contracts/operations.yaml",
    "contracts/science.yaml",
    "contracts/evidence.yaml",
    "contracts/runtime.yaml",
    "foundation/market.yaml",
    "foundation/environment.yaml",
    "foundation/data.yaml",
    "foundation/data_exposure.yaml",
    "foundation/prior_scientific_memory.yaml",
    "foundation/origin.yaml",
)


def _event_preflight(repo_root: Path) -> dict[str, Any]:
    journal = repo_root / "records/journal/journal-000002.jsonl"
    with journal.open("r", encoding="ascii") as handle:
        for line in handle:
            if '"sequence":5433' not in line:
                continue
            event = json.loads(line)
            if event.get("sequence") != EVENT_SEQUENCE:
                continue
            if event.get("event_kind") != (
                "replay_implementation_repair_recertified"
            ):
                raise AssertionError("event 5433 kind drifted")
            records = event.get("index_records")
            if not isinstance(records, list):
                raise AssertionError("event 5433 records are absent")
            matches = [
                record
                for record in records
                if record.get("kind") == "job-implementation-preflight"
                and record.get("record_id") == PREFLIGHT_ID
            ]
            if len(matches) != 1:
                raise AssertionError("event 5433 preflight is not exact")
            payload = matches[0].get("payload")
            if not isinstance(payload, dict):
                raise AssertionError("event 5433 preflight payload is absent")
            return payload
    raise AssertionError("event 5433 is absent from committed Journal")


def _evidence_bytes(repo_root: Path, identity: str) -> bytes:
    path = (
        repo_root
        / "local"
        / "evidence"
        / "sha256"
        / identity[:2]
        / identity
    )
    content = path.read_bytes()
    if sha256(content).hexdigest() != identity:
        raise AssertionError("fixed-hold durable evidence identity drifted")
    return content


def _registered_sources(repo_root: Path, identity: str) -> dict[str, bytes]:
    implementation = parse_canonical(_evidence_bytes(repo_root, identity))
    if (
        not isinstance(implementation, dict)
        or implementation.get("schema") != "job_implementation_evidence.v1"
        or implementation.get("callable_identity") != CALLABLE_IDENTITY
        or implementation.get("protocol") != PROTOCOL_ID
        or not isinstance(implementation.get("artifact_hashes"), list)
    ):
        raise AssertionError("fixed-hold implementation evidence drifted")
    opened = {
        artifact_hash: _evidence_bytes(repo_root, artifact_hash)
        for artifact_hash in implementation["artifact_hashes"]
    }
    closures: list[dict[str, Any]] = []
    for content in opened.values():
        try:
            candidate = parse_canonical(content)
        except (TypeError, ValueError):
            continue
        if (
            isinstance(candidate, dict)
            and candidate.get("schema")
            == "job_implementation_source_closure.v1"
        ):
            closures.append(candidate)
    if len(closures) != 1 or not isinstance(
        closures[0].get("dependencies"), list
    ):
        raise AssertionError("fixed-hold source closure is absent")
    sources = {
        dependency["path"]: opened[dependency["sha256"]]
        for dependency in closures[0]["dependencies"]
    }
    if tuple(sources) != _FIXED_HOLD_JOB_SOURCE_PATHS:
        raise AssertionError("fixed-hold source snapshot inventory drifted")
    return sources


def executable_from_manifest(
    manifest: Mapping[str, Any],
    *,
    display_name: str,
) -> ExecutableSpec:
    components: list[ComponentSpec] = []
    component_manifests = manifest.get("component_manifests")
    component_identities = manifest.get("component_identities")
    if not isinstance(component_manifests, list) or not isinstance(
        component_identities, list
    ):
        raise AssertionError("Executable manifest components are absent")
    for ordinal, component_manifest in enumerate(component_manifests, start=1):
        component = ComponentSpec(
            display_name=f"{display_name} component {ordinal}",
            protocol=component_manifest["protocol"],
            implementation=component_manifest["implementation"],
            spec=component_manifest["spec"],
            semantic_dependencies=tuple(
                component_manifest["semantic_dependencies"]
            ),
        )
        if component.identity != component_identities[ordinal - 1]:
            raise AssertionError("Executable component identity drifted")
        if component.to_identity_payload() != component_manifest:
            raise AssertionError("Executable component manifest drifted")
        components.append(component)
    executable = ExecutableSpec(
        display_name=display_name,
        components=tuple(components),
        parameters=manifest["parameters"],
        data_contract=manifest["data_contract"],
        split_contract=manifest["split_contract"],
        clock_contract=manifest["clock_contract"],
        cost_contract=manifest["cost_contract"],
        engine_contract=manifest["engine_contract"],
        source_contracts=tuple(manifest["source_contracts"]),
    )
    if executable.to_identity_payload() != dict(manifest):
        raise AssertionError("Executable manifest did not round-trip")
    return executable


def baseline_from_scientific_surface(
    surface: Mapping[str, Any],
    *,
    implementation_template: ExecutableSpec,
) -> ExecutableSpec:
    raw_components = surface.get("components")
    if not isinstance(raw_components, list):
        raise AssertionError("scientific baseline components are absent")
    if len(raw_components) != len(implementation_template.components):
        raise AssertionError("scientific baseline component count drifted")
    components: list[ComponentSpec] = []
    for expected_ordinal, raw in enumerate(raw_components, start=1):
        if raw.get("component_ordinal") != expected_ordinal:
            raise AssertionError("scientific baseline ordinal drifted")
        dependencies: list[str] = []
        for dependency in raw.get("semantic_dependencies", []):
            if (
                not isinstance(dependency, dict)
                or dependency.get("kind") != "family_component"
                or type(dependency.get("ordinal")) is not int
                or not 1 <= dependency["ordinal"] < expected_ordinal
            ):
                raise AssertionError(
                    "scientific baseline dependency is not reconstructible"
                )
            dependencies.append(components[dependency["ordinal"] - 1].identity)
        template = implementation_template.components[expected_ordinal - 1]
        if template.protocol != raw.get("protocol"):
            raise AssertionError("scientific baseline protocol drifted")
        components.append(
            ComponentSpec(
                display_name=f"event 5433 baseline component {expected_ordinal}",
                protocol=raw["protocol"],
                implementation=template.implementation,
                spec=raw["spec"],
                semantic_dependencies=tuple(dependencies),
            )
        )
    parameters = dict(surface["parameters"])
    template_parameters = implementation_template.parameter_values()
    if not isinstance(template_parameters, dict):
        raise AssertionError("implementation template parameters are absent")
    declared_parameter_fields = {
        field
        for component in components
        for field in component.specification().get("parameter_fields", [])
    }
    missing = declared_parameter_fields.difference(parameters)
    if missing != {"historical_context_prior_global_exposure_count"}:
        raise AssertionError(
            "scientific baseline parameter projection drifted: "
            + ",".join(sorted(missing))
        )
    parameters.update({field: template_parameters[field] for field in missing})
    return ExecutableSpec(
        display_name="event 5433 controlled baseline",
        components=tuple(components),
        parameters=parameters,
        data_contract=surface["data_contract"],
        split_contract=surface["split_contract"],
        clock_contract=surface["clock_contract"],
        cost_contract=surface["cost_contract"],
        engine_contract=surface["engine_contract"],
        source_contracts=tuple(surface["source_contracts"]),
    )


def copy_foundation(repo_root: Path, target: Path) -> Path:
    for relative_path in AUTHORITY_AND_FOUNDATION_PATHS:
        source = repo_root / relative_path
        destination = target / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    return target


def write_source_snapshot(
    source_root: Path,
    sources: Mapping[str, bytes],
) -> None:
    if tuple(sorted(sources)) != tuple(sorted(_FIXED_HOLD_JOB_SOURCE_PATHS)):
        raise AssertionError("fixed-hold source snapshot inventory drifted")
    for relative_path, content in sources.items():
        target = source_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


@dataclass(slots=True)
class Event5433RepairFixture:
    preflight: dict[str, Any]
    scientific_surface: dict[str, Any]
    executables: tuple[ExecutableSpec, ...]
    baseline: ExecutableSpec
    old_sources: dict[str, bytes]
    new_sources: dict[str, bytes]

    @classmethod
    def load(cls, repo_root: Path) -> Event5433RepairFixture:
        preflight = _event_preflight(repo_root)
        manifests = preflight.get("executable_manifests")
        executable_ids = preflight.get("executable_ids")
        if not isinstance(manifests, list) or not isinstance(
            executable_ids, list
        ):
            raise AssertionError("event 5433 Executable family is absent")
        executables = tuple(
            executable_from_manifest(
                manifest,
                display_name=f"event 5433 family member {ordinal}",
            )
            for ordinal, manifest in enumerate(manifests, start=1)
        )
        if [executable.identity for executable in executables] != executable_ids:
            raise AssertionError("event 5433 Executable family identity drifted")
        if executables[0].identity != EXECUTABLE_ID:
            raise AssertionError("event 5433 target Executable drifted")
        if preflight.get("callable_identity") != CALLABLE_IDENTITY:
            raise AssertionError("event 5433 callable identity drifted")
        if preflight.get("protocol_id") != PROTOCOL_ID:
            raise AssertionError("event 5433 implementation protocol drifted")
        observed_component_hashes = tuple(
            sorted(
                {
                    component.implementation.rsplit("@sha256:", 1)[1]
                    for executable in executables
                    for component in executable.components
                }
            )
        )
        if observed_component_hashes != COMPONENT_IMPLEMENTATION_HASHES:
            raise AssertionError("event 5433 component implementation drifted")
        scientific_surface = preflight.get("scientific_surface")
        if not isinstance(scientific_surface, dict):
            raise AssertionError("event 5433 scientific surface is absent")
        baseline_surface = scientific_surface["study"]["controlled_chassis"][
            "baseline_executable"
        ]
        baseline = baseline_from_scientific_surface(
            baseline_surface,
            implementation_template=executables[0],
        )
        old_sources = _registered_sources(
            repo_root,
            FIXED_HOLD_AUTHORITY_CORRECTION_OLD_IMPLEMENTATION_IDENTITY,
        )
        new_sources = _registered_sources(
            repo_root,
            FIXED_HOLD_AUTHORITY_CORRECTION_NEW_IMPLEMENTATION_IDENTITY,
        )
        return cls(
            preflight=preflight,
            scientific_surface=scientific_surface,
            executables=executables,
            baseline=baseline,
            old_sources=old_sources,
            new_sources=new_sources,
        )

    @staticmethod
    def expected_old_implementation_identity() -> str:
        return FIXED_HOLD_AUTHORITY_CORRECTION_OLD_IMPLEMENTATION_IDENTITY

    @staticmethod
    def expected_new_implementation_identity() -> str:
        return FIXED_HOLD_AUTHORITY_CORRECTION_NEW_IMPLEMENTATION_IDENTITY
