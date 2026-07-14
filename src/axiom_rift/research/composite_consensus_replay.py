"""Prospective exact-family replay adapter for historical STU-0017."""

from __future__ import annotations

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.chassis import ControlledStudyChassis
from axiom_rift.research.composite_consensus_discovery import (
    composite_consensus_implementation_sha256,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FixedHoldProtocolDefinition,
)
from axiom_rift.research.historical_family_replay import (
    STU0017_HISTORICAL_FAMILY,
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
    COMPOSITE_CONSENSUS_REPLAY_TRACE_PROTOCOL_ID,
)


COMPOSITE_CONSENSUS_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT = 222
COMPOSITE_CONSENSUS_REPLAY_HISTORICAL_CONTEXT_ID = (
    "historical-replay-obligation:"
    "5d369574dc42c01849cad0c50b2bdec1632f9bb837cc5a07ca19a537b3813b1e"
)
COMPOSITE_CONSENSUS_REPLAY_PROFILES = (
    "full_regime_consensus",
    "volume_primary_all_regimes",
    "middle_consensus_no_high",
)
COMPOSITE_CONSENSUS_REPLAY_HOLDING_BARS = (24, 48)

COMPOSITE_CONSENSUS_REPLAY_DEFINITION = RoutedReplayFamilyDefinition(
    family_name="composite-consensus-replay",
    historical_family=STU0017_HISTORICAL_FAMILY,
    profiles=COMPOSITE_CONSENSUS_REPLAY_PROFILES,
    holding_bars=COMPOSITE_CONSENSUS_REPLAY_HOLDING_BARS,
    selector_quantile_bp=9_750,
    original_family_end_global_exposure_count=(
        COMPOSITE_CONSENSUS_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
    ),
    historical_context_id=COMPOSITE_CONSENSUS_REPLAY_HISTORICAL_CONTEXT_ID,
    trace_protocol_id=COMPOSITE_CONSENSUS_REPLAY_TRACE_PROTOCOL_ID,
    engine_namespace="stu0017_composite_consensus_replay_v1",
    source_module_name="axiom_rift.research.composite_consensus_discovery",
    source_implementation_sha256=composite_consensus_implementation_sha256(),
    calibrator_function_name="calibrate_router",
    router_function_name="route_consensus_score",
    route_mechanism="same_sign_regime_consensus",
)


def composite_consensus_replay_configurations(
) -> tuple[RoutedReplayConfiguration, ...]:
    return routed_replay_configurations(COMPOSITE_CONSENSUS_REPLAY_DEFINITION)


def composite_consensus_replay_components() -> tuple[ComponentSpec, ...]:
    return routed_replay_components(COMPOSITE_CONSENSUS_REPLAY_DEFINITION)


def composite_consensus_replay_executable(
    configuration: RoutedReplayConfiguration,
    *,
    historical_context_prior_global_exposure_count: int,
) -> ExecutableSpec:
    return routed_replay_executable(
        COMPOSITE_CONSENSUS_REPLAY_DEFINITION,
        configuration,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
    )


def composite_consensus_replay_baseline_executable(
    *,
    historical_context_prior_global_exposure_count: int,
) -> ExecutableSpec:
    return routed_replay_baseline_executable(
        COMPOSITE_CONSENSUS_REPLAY_DEFINITION,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
    )


def composite_consensus_replay_controlled_chassis(
    *,
    historical_context_prior_global_exposure_count: int,
) -> ControlledStudyChassis:
    return routed_replay_controlled_chassis(
        COMPOSITE_CONSENSUS_REPLAY_DEFINITION,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
    )


def composite_consensus_replay_executable_map(
    *,
    historical_context_prior_global_exposure_count: int,
) -> dict[str, RoutedReplayConfiguration]:
    return routed_replay_executable_map(
        COMPOSITE_CONSENSUS_REPLAY_DEFINITION,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
    )


def composite_consensus_replay_protocol_definition(
    *,
    historical_context_prior_global_exposure_count: int,
) -> FixedHoldProtocolDefinition:
    return routed_replay_protocol_definition(
        COMPOSITE_CONSENSUS_REPLAY_DEFINITION,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
    )


__all__ = [
    "COMPOSITE_CONSENSUS_REPLAY_DEFINITION",
    "COMPOSITE_CONSENSUS_REPLAY_HISTORICAL_CONTEXT_ID",
    "COMPOSITE_CONSENSUS_REPLAY_HOLDING_BARS",
    "COMPOSITE_CONSENSUS_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT",
    "COMPOSITE_CONSENSUS_REPLAY_PROFILES",
    "composite_consensus_replay_baseline_executable",
    "composite_consensus_replay_components",
    "composite_consensus_replay_configurations",
    "composite_consensus_replay_controlled_chassis",
    "composite_consensus_replay_executable",
    "composite_consensus_replay_executable_map",
    "composite_consensus_replay_protocol_definition",
]
