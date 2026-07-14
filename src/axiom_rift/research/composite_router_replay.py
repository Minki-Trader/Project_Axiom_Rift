"""Prospective exact-family replay adapter for historical STU-0016."""

from __future__ import annotations

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.chassis import ControlledStudyChassis
from axiom_rift.research.composite_router_discovery import (
    composite_router_implementation_sha256,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FixedHoldProtocolDefinition,
)
from axiom_rift.research.historical_family_replay import (
    STU0016_HISTORICAL_FAMILY,
)
from axiom_rift.research.routed_sleeve_replay import (
    RoutedReplayConfiguration,
    RoutedReplayFamilyDefinition,
    routed_replay_baseline_executable,
    routed_replay_components,
    routed_replay_configurations,
    routed_replay_controlled_chassis,
    routed_replay_executable,
    routed_replay_executable_map,
    routed_replay_protocol_definition,
)
from axiom_rift.research.scientific_trace import (
    COMPOSITE_ROUTER_REPLAY_TRACE_PROTOCOL_ID,
)


COMPOSITE_ROUTER_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT = 210
COMPOSITE_ROUTER_REPLAY_HISTORICAL_CONTEXT_ID = (
    "historical-replay-obligation:"
    "76e0d687a149430422231dd36c1853456dccf34724af77309d218455b94aecfa"
)
COMPOSITE_ROUTER_REPLAY_PROFILES = (
    "three_sleeve_router",
    "volume_reversion_ablation",
    "volume_volatility_ablation",
)
COMPOSITE_ROUTER_REPLAY_HOLDING_BARS = (12, 48)

COMPOSITE_ROUTER_REPLAY_DEFINITION = RoutedReplayFamilyDefinition(
    family_name="composite-router-replay",
    historical_family=STU0016_HISTORICAL_FAMILY,
    profiles=COMPOSITE_ROUTER_REPLAY_PROFILES,
    holding_bars=COMPOSITE_ROUTER_REPLAY_HOLDING_BARS,
    selector_quantile_bp=9_500,
    original_family_end_global_exposure_count=(
        COMPOSITE_ROUTER_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
    ),
    historical_context_id=COMPOSITE_ROUTER_REPLAY_HISTORICAL_CONTEXT_ID,
    trace_protocol_id=COMPOSITE_ROUTER_REPLAY_TRACE_PROTOCOL_ID,
    engine_namespace="stu0016_composite_router_replay_v1",
    source_module_name="axiom_rift.research.composite_router_discovery",
    source_implementation_sha256=composite_router_implementation_sha256(),
    calibrator_function_name="calibrate_router",
    router_function_name="route_composite_score",
    route_mechanism="single_regime_sleeve",
)


def composite_router_replay_configurations(
) -> tuple[RoutedReplayConfiguration, ...]:
    return routed_replay_configurations(COMPOSITE_ROUTER_REPLAY_DEFINITION)


def composite_router_replay_components() -> tuple[ComponentSpec, ...]:
    return routed_replay_components(COMPOSITE_ROUTER_REPLAY_DEFINITION)


def composite_router_replay_executable(
    configuration: RoutedReplayConfiguration,
    *,
    historical_context_prior_global_exposure_count: int,
) -> ExecutableSpec:
    return routed_replay_executable(
        COMPOSITE_ROUTER_REPLAY_DEFINITION,
        configuration,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
    )


def composite_router_replay_baseline_executable(
    *,
    historical_context_prior_global_exposure_count: int,
) -> ExecutableSpec:
    return routed_replay_baseline_executable(
        COMPOSITE_ROUTER_REPLAY_DEFINITION,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
    )


def composite_router_replay_controlled_chassis(
    *,
    historical_context_prior_global_exposure_count: int,
) -> ControlledStudyChassis:
    return routed_replay_controlled_chassis(
        COMPOSITE_ROUTER_REPLAY_DEFINITION,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
    )


def composite_router_replay_executable_map(
    *,
    historical_context_prior_global_exposure_count: int,
) -> dict[str, RoutedReplayConfiguration]:
    return routed_replay_executable_map(
        COMPOSITE_ROUTER_REPLAY_DEFINITION,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
    )


def composite_router_replay_protocol_definition(
    *,
    historical_context_prior_global_exposure_count: int,
) -> FixedHoldProtocolDefinition:
    return routed_replay_protocol_definition(
        COMPOSITE_ROUTER_REPLAY_DEFINITION,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
    )


__all__ = [
    "COMPOSITE_ROUTER_REPLAY_DEFINITION",
    "COMPOSITE_ROUTER_REPLAY_HISTORICAL_CONTEXT_ID",
    "COMPOSITE_ROUTER_REPLAY_HOLDING_BARS",
    "COMPOSITE_ROUTER_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT",
    "COMPOSITE_ROUTER_REPLAY_PROFILES",
    "composite_router_replay_baseline_executable",
    "composite_router_replay_components",
    "composite_router_replay_configurations",
    "composite_router_replay_controlled_chassis",
    "composite_router_replay_executable",
    "composite_router_replay_executable_map",
    "composite_router_replay_protocol_definition",
]
