"""Typed US30 source-usage contrast on the registered sector-rotation chassis."""

from __future__ import annotations

from typing import Any, Mapping

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.us30_sector_rotation_discovery import (
    US30SectorRotationConfiguration,
    us30_sector_rotation_configurations,
    us30_sector_rotation_executable,
    project_us30_sector_rotation_evaluation,
    us30_source_implementation_sha256,
)
from axiom_rift.research.us30_source import us30_source_contract


def source_usage_component() -> ComponentSpec:
    contract = us30_source_contract()
    return ComponentSpec(
        display_name="eligible FPMarkets US30 source usage profile",
        protocol="external_source.fpmarkets_us30_usage_profile.v1",
        implementation=(
            "axiom_rift.research.us30_source.us30_source_contract@sha256:"
            f"{us30_source_implementation_sha256()}"
        ),
        semantic_dependencies=(contract.source_contract_id,),
        spec={
            "parameter_fields": ["source_usage_profile"],
            "profiles": [
                "relative_strength_12_joint",
                "us30_direction_12_source_only",
                "us100_direction_12_target_only",
            ],
            "source_contract_id": contract.source_contract_id,
        },
    )


def us30_sector_rotation_registered_executable(
    configuration: US30SectorRotationConfiguration,
    raw_sha256: str,
) -> ExecutableSpec:
    current = us30_sector_rotation_executable(configuration, raw_sha256)
    parameters = dict(current.parameter_values())
    parameters["source_usage_profile"] = configuration.profile
    return ExecutableSpec(
        display_name=current.display_name,
        components=(source_usage_component(), *current.components),
        parameters=parameters,
        data_contract=current.data_contract,
        split_contract=current.split_contract,
        clock_contract=current.clock_contract,
        cost_contract=current.cost_contract,
        engine_contract=current.engine_contract,
        source_contracts=current.source_contracts,
    )


def us30_sector_rotation_registered_configuration_map(
    raw_sha256: str,
) -> dict[str, US30SectorRotationConfiguration]:
    return {
        us30_sector_rotation_registered_executable(value, raw_sha256).identity: value
        for value in us30_sector_rotation_configurations()
    }


def us30_sector_rotation_registered_baseline(raw_sha256: str) -> ExecutableSpec:
    configuration = next(
        value
        for value in us30_sector_rotation_configurations()
        if value.profile == "us100_direction_12_target_only"
        and value.route_sign == 1
        and value.holding_bars == 6
    )
    current = us30_sector_rotation_executable(configuration, raw_sha256)
    return ExecutableSpec(
        display_name=current.display_name,
        components=current.components,
        parameters=current.parameter_values(),
        data_contract=current.data_contract,
        split_contract=current.split_contract,
        clock_contract=current.clock_contract,
        cost_contract=current.cost_contract,
        engine_contract=current.engine_contract,
        source_contracts=current.source_contracts,
    )


def us30_sector_rotation_study_executable(
    configuration: US30SectorRotationConfiguration,
    raw_sha256: str,
) -> ExecutableSpec:
    if (
        configuration.profile == "us100_direction_12_target_only"
        and configuration.route_sign == 1
        and configuration.holding_bars == 6
    ):
        return us30_sector_rotation_registered_baseline(raw_sha256)
    return us30_sector_rotation_registered_executable(configuration, raw_sha256)


def us30_sector_rotation_study_configuration_map(
    raw_sha256: str,
) -> dict[str, US30SectorRotationConfiguration]:
    return {
        us30_sector_rotation_study_executable(value, raw_sha256).identity: value
        for value in us30_sector_rotation_configurations()
    }


def project_registered_us30_sector_rotation_evaluation(
    surface: Mapping[str, Any],
    *,
    job_execution: Mapping[str, str],
    subject_executable_id: str,
    surface_artifact_hash: str,
    surface_manifest_hash: str,
) -> dict[str, Any]:
    raw_sha256 = str(surface.get("source_raw_sha256", ""))
    registered = us30_sector_rotation_study_configuration_map(raw_sha256)
    configuration = registered.get(subject_executable_id)
    if configuration is None:
        raise ValueError("registered US30 subject Executable is absent")
    original_id = us30_sector_rotation_executable(configuration, raw_sha256).identity
    evaluation = project_us30_sector_rotation_evaluation(
        surface,
        job_execution=job_execution,
        subject_executable_id=original_id,
        surface_artifact_hash=surface_artifact_hash,
        surface_manifest_hash=surface_manifest_hash,
    )
    evaluation["subject_executable_id"] = subject_executable_id
    original = {
        us30_sector_rotation_executable(value, raw_sha256).identity: value
        for value in us30_sector_rotation_configurations()
    }
    registered_by_configuration = {
        value.configuration_id: executable_id
        for executable_id, value in registered.items()
    }
    evaluation["selection_context"] = [
        {
            **dict(item),
            "executable_id": registered_by_configuration[
                original[item["executable_id"]].configuration_id
            ],
        }
        for item in evaluation["selection_context"]
    ]
    canonical_bytes(evaluation)
    return evaluation


__all__ = [
    "source_usage_component",
    "project_registered_us30_sector_rotation_evaluation",
    "us30_sector_rotation_registered_baseline",
    "us30_sector_rotation_registered_configuration_map",
    "us30_sector_rotation_registered_executable",
    "us30_sector_rotation_study_configuration_map",
    "us30_sector_rotation_study_executable",
]
