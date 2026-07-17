"""Prospective STU-0046 gap-event protocol with a feasible train floor.

The prior v2 implementation is intentionally left byte-stable because its
source hash is part of already registered Executable identities.  This module
creates a distinct scientific surface for the diagnosed successor Study while
reusing only the unchanged feature, label, cost, and inference machinery.
"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import numpy as np

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research import gap_fixed_hold as legacy
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.discovery import DiscoveryBoundaryError
from axiom_rift.research.fixed_hold_family_trace import FixedHoldProtocolDefinition
from axiom_rift.research.fixed_hold_trace_engine import (
    compute_fixed_hold_family_trace,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
    HistoricalFamilySpec,
)


GAP_EVENT_V3_MINIMUM_TRAIN_OBSERVATIONS = 350
GAP_EVENT_V3_OBSERVED_TRAIN_EVENT_RANGE = (386, 392)
GAP_EVENT_V3_DIAGNOSIS_ID = (
    "diagnosis:81d551801014e8b3a3278cefb9bab929195e61c687d20b85a4a87c9d9e3f53e6"
)
_THIS_FILE = Path(__file__).resolve()


def gap_event_fixed_hold_v3_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.gap_event_fixed_hold_v3.{name}@sha256:"
        f"{gap_event_fixed_hold_v3_implementation_sha256()}"
    )


def _configurations(historical_family: HistoricalFamilySpec):
    configurations = legacy.gap_fixed_hold_configurations(historical_family)
    if (
        historical_family.original_study_id != "STU-0046"
        or {item.profile for item in configurations}
        != set(legacy.GAP_EVENT_FIXED_HOLD_PROFILES)
    ):
        raise ValueError("gap-event v3 requires the exact STU-0046 family")
    return configurations


def _with_dependency(component: ComponentSpec, dependency: str) -> ComponentSpec:
    return ComponentSpec(
        display_name=component.display_name,
        protocol=component.protocol,
        implementation=component.implementation,
        spec=component.specification(),
        semantic_dependencies=(dependency,),
    )


def gap_event_fixed_hold_v3_components(
    historical_family: HistoricalFamilySpec,
) -> tuple[ComponentSpec, ...]:
    _configurations(historical_family)
    prior = legacy.gap_fixed_hold_components(historical_family)
    feature, label, model = prior[:3]
    selector = ComponentSpec(
        display_name="fold-isolated feasible gap-event selector",
        protocol="selector.fold_train_abs_quantile.replay.v2",
        implementation=_local("calibrate_gap_event_fixed_hold_v3_selector"),
        spec={
            "calibration_role": "train_is_only",
            "feasibility_basis": "observed_development_train_event_counts_only",
            "minimum_train_observations": (
                GAP_EVENT_V3_MINIMUM_TRAIN_OBSERVATIONS
            ),
            "observed_train_event_count_range": list(
                GAP_EVENT_V3_OBSERVED_TRAIN_EVENT_RANGE
            ),
            "outcome_values_used_for_floor": False,
            "parameter_fields": ["selector_quantile_bp"],
            "quantile_method": "higher",
            "source_study_diagnosis_id": GAP_EVENT_V3_DIAGNOSIS_ID,
        },
        semantic_dependencies=(model.identity,),
    )
    trade = _with_dependency(prior[4], selector.identity)
    lifecycle = _with_dependency(prior[5], trade.identity)
    execution = _with_dependency(prior[6], lifecycle.identity)
    risk = _with_dependency(prior[7], execution.identity)
    synthesis_spec = prior[8].specification()
    assert isinstance(synthesis_spec, dict)
    synthesis = ComponentSpec(
        display_name="Writer-bound gap-event v3 family member",
        protocol="synthesis.historical_fixed_hold_member.v3",
        implementation=_local("gap_event_fixed_hold_v3_executable"),
        spec={
            **synthesis_spec,
            "scientific_change_basis": GAP_EVENT_V3_DIAGNOSIS_ID,
        },
        semantic_dependencies=(risk.identity,),
    )
    portfolio_spec = prior[9].specification()
    assert isinstance(portfolio_spec, dict)
    portfolio = ComponentSpec(
        display_name="exact concurrent feasible gap-event family inference",
        protocol="portfolio.concurrent_fixed_hold_family_inference.v3",
        implementation=_local("gap_event_fixed_hold_v3_protocol_definition"),
        spec={
            **portfolio_spec,
            "selector_floor_policy": "registered_feasible_train_event_floor_v1",
        },
        semantic_dependencies=(synthesis.identity,),
    )
    return (
        feature,
        label,
        model,
        selector,
        trade,
        lifecycle,
        execution,
        risk,
        synthesis,
        portfolio,
    )


def _revised_executable(
    base: ExecutableSpec,
    *,
    historical_family: HistoricalFamilySpec,
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=base.display_name + " v3",
        components=gap_event_fixed_hold_v3_components(historical_family),
        parameters=base.parameter_values(),
        data_contract=base.data_contract,
        split_contract=base.split_contract,
        clock_contract=base.clock_contract,
        cost_contract=base.cost_contract,
        engine_contract=(
            base.engine_contract
            + ":scientific_revision_"
            + gap_event_fixed_hold_v3_implementation_sha256()
        ),
        source_contracts=base.source_contracts,
    )


def gap_event_fixed_hold_v3_executable(
    configuration: legacy.GapFixedHoldConfiguration,
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ExecutableSpec:
    if configuration not in _configurations(historical_family):
        raise ValueError("configuration is outside the STU-0046 v3 family")
    base = legacy.gap_fixed_hold_executable(
        configuration,
        historical_family=historical_family,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=(
            original_family_end_global_exposure_count
        ),
    )
    return _revised_executable(base, historical_family=historical_family)


def gap_event_fixed_hold_v3_baseline_executable(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ExecutableSpec:
    _configurations(historical_family)
    base = legacy.gap_fixed_hold_baseline_executable(
        historical_family=historical_family,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=(
            original_family_end_global_exposure_count
        ),
    )
    return _revised_executable(base, historical_family=historical_family)


def gap_event_fixed_hold_v3_controlled_chassis(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ControlledStudyChassis:
    baseline = gap_event_fixed_hold_v3_baseline_executable(
        historical_family=historical_family,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=(
            original_family_end_global_exposure_count
        ),
    )
    chassis = ControlledStudyChassis(
        baseline_executable=baseline,
        changed_domains=(
            ResearchLayer.FEATURE,
            ResearchLayer.SYNTHESIS,
            ResearchLayer.TRADE,
        ),
        controlled_domains=(
            ResearchLayer.EXECUTION,
            ResearchLayer.LABEL,
            ResearchLayer.LIFECYCLE,
            ResearchLayer.MODEL,
            ResearchLayer.PORTFOLIO,
            ResearchLayer.RISK,
            ResearchLayer.SELECTOR,
        ),
        architecture=ArchitectureChassisSpec.from_executable(baseline),
    )
    payload = chassis.to_identity_payload()
    for configuration in _configurations(historical_family):
        validate_controlled_executable(
            payload,
            gap_event_fixed_hold_v3_executable(
                configuration,
                historical_family=historical_family,
                historical_context_prior_global_exposure_count=(
                    historical_context_prior_global_exposure_count
                ),
                original_family_end_global_exposure_count=(
                    original_family_end_global_exposure_count
                ),
            ),
        )
    return chassis


def gap_event_fixed_hold_v3_producer_implementation_identities(
) -> dict[str, str]:
    return {
        **legacy.gap_fixed_hold_producer_implementation_identities(),
        "scientific_revision_sha256": (
            gap_event_fixed_hold_v3_implementation_sha256()
        ),
    }


def gap_event_fixed_hold_v3_protocol_definition(
    context: HistoricalFamilyReplayContext,
) -> FixedHoldProtocolDefinition:
    base = legacy.gap_fixed_hold_protocol_definition(context)
    configurations = _configurations(context.family)
    executables = tuple(
        gap_event_fixed_hold_v3_executable(
            configuration,
            historical_family=context.family,
            historical_context_prior_global_exposure_count=(
                context.prior_global_exposure_count
            ),
            original_family_end_global_exposure_count=(
                context.original_family_end_global_exposure_count
            ),
        )
        for configuration in configurations
    )
    return replace(
        base,
        prospective_executable_ids=tuple(
            executable.identity for executable in executables
        ),
        producer_implementation_identities=tuple(
            sorted(gap_event_fixed_hold_v3_producer_implementation_identities().items())
        ),
    )


def calibrate_gap_event_fixed_hold_v3_selector(
    score: np.ndarray,
    mask: np.ndarray,
) -> float:
    values = np.abs(score[mask & np.isfinite(score)])
    if len(values) < GAP_EVENT_V3_MINIMUM_TRAIN_OBSERVATIONS:
        raise DiscoveryBoundaryError("gap-event v3 selector event set is too small")
    return float(
        np.quantile(
            values,
            legacy.GAP_FIXED_HOLD_SELECTOR_QUANTILE_BP / 10_000,
            method="higher",
        )
    )


def compute_gap_event_fixed_hold_v3_family_trace(
    repository_root: str | Path,
    definition: FixedHoldProtocolDefinition,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    if not isinstance(definition.family, HistoricalFamilySpec):
        raise TypeError("gap-event v3 definition is not Writer-bound")
    configurations = _configurations(definition.family)
    expected_ids = tuple(
        gap_event_fixed_hold_v3_executable(
            configuration,
            historical_family=definition.family,
            historical_context_prior_global_exposure_count=(
                definition.historical_prior_global_exposure_count
            ),
            original_family_end_global_exposure_count=(
                definition.original_family_end_global_exposure_count
            ),
        ).identity
        for configuration in configurations
    )
    if (
        definition.prospective_executable_ids != expected_ids
        or definition.producer_implementation_identities
        != tuple(
            sorted(gap_event_fixed_hold_v3_producer_implementation_identities().items())
        )
    ):
        raise ValueError("gap-event v3 definition drifted from its scientific surface")
    return compute_fixed_hold_family_trace(
        repository_root,
        definition=definition,
        configurations=configurations,
        feature_builder=legacy.compute_gap_fixed_hold_score,
        selector_calibrator=calibrate_gap_event_fixed_hold_v3_selector,
        spread_builder=legacy.causal_gap_fixed_hold_spread,
    )


__all__ = [
    "GAP_EVENT_V3_DIAGNOSIS_ID",
    "GAP_EVENT_V3_MINIMUM_TRAIN_OBSERVATIONS",
    "GAP_EVENT_V3_OBSERVED_TRAIN_EVENT_RANGE",
    "calibrate_gap_event_fixed_hold_v3_selector",
    "compute_gap_event_fixed_hold_v3_family_trace",
    "gap_event_fixed_hold_v3_baseline_executable",
    "gap_event_fixed_hold_v3_components",
    "gap_event_fixed_hold_v3_controlled_chassis",
    "gap_event_fixed_hold_v3_executable",
    "gap_event_fixed_hold_v3_implementation_sha256",
    "gap_event_fixed_hold_v3_producer_implementation_identities",
    "gap_event_fixed_hold_v3_protocol_definition",
]
