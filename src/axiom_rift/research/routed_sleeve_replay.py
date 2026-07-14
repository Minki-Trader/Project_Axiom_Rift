"""Declarative prospective adapters for historical routed-sleeve families."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research import data as data_module
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    EXPECTED_FOLD_IDS,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    SELECTION_BLOCK_LENGTHS,
    SELECTION_BOOTSTRAP_SAMPLES,
    SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
    SELECTION_SEED,
    discovery_implementation_sha256,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FixedHoldProtocolDefinition,
    fixed_hold_trace_implementation_sha256,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.historical_family_replay import (
    HistoricalFamilySpec,
)
from axiom_rift.research.reversion_discovery import (
    reversion_implementation_sha256,
)
from axiom_rift.research.routed_sleeve_trace_engine import (
    routed_sleeve_trace_engine_implementation_sha256,
)
from axiom_rift.research.selection_inference import (
    selection_inference_implementation_sha256,
)
from axiom_rift.research.volatility_discovery import (
    volatility_implementation_sha256,
)
from axiom_rift.research.volume_price_discovery import (
    volume_price_implementation_sha256,
)


ROUTED_REPLAY_ALPHA_PPM = 100_000
ROUTED_REPLAY_CLOCK_CONTRACT = (
    "clock:fpmarkets_m5_bar_open_completed_plus_5m_v2"
)
ROUTED_REPLAY_COST_CONTRACT = (
    "cost:bid_bar_spread_point_0_01_causal_zero_repair_"
    "half_spread_stress_v2"
)
_THIS_FILE = Path(__file__).resolve()


def routed_sleeve_replay_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def routed_sleeve_replay_loader_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class RoutedReplayFamilyDefinition:
    family_name: str
    historical_family: HistoricalFamilySpec
    profiles: tuple[str, ...]
    holding_bars: tuple[int, ...]
    selector_quantile_bp: int
    original_family_end_global_exposure_count: int
    historical_context_id: str
    trace_protocol_id: str
    engine_namespace: str
    source_module_name: str
    source_implementation_sha256: str
    calibrator_function_name: str
    router_function_name: str
    route_mechanism: str

    def __post_init__(self) -> None:
        for name in (
            "family_name",
            "historical_context_id",
            "trace_protocol_id",
            "engine_namespace",
            "source_module_name",
            "calibrator_function_name",
            "router_function_name",
            "route_mechanism",
        ):
            _ascii(name, getattr(self, name))
        _digest(
            "source_implementation_sha256",
            self.source_implementation_sha256,
        )
        if (
            not isinstance(self.historical_family, HistoricalFamilySpec)
            or self.historical_family.family_size != 12
            or type(self.profiles) is not tuple
            or len(self.profiles) != 3
            or len(set(self.profiles)) != 3
            or any(type(value) is not str or not value.isascii() for value in self.profiles)
            or type(self.holding_bars) is not tuple
            or len(self.holding_bars) != 2
            or len(set(self.holding_bars)) != 2
            or any(type(value) is not int or value <= 0 for value in self.holding_bars)
            or type(self.selector_quantile_bp) is not int
            or not 1 <= self.selector_quantile_bp <= 9_999
            or type(self.original_family_end_global_exposure_count) is not int
            or self.original_family_end_global_exposure_count < 12
        ):
            raise ValueError("routed replay family definition is invalid")
        observed = {
            (
                str(parameters["profile"]),
                int(parameters["signal_sign"]),
                int(parameters["holding_bars"]),
                int(parameters["selector_quantile_bp"]),
            )
            for member in self.historical_family.members
            for parameters in (member.parameter_values(),)
        }
        expected = {
            (profile, sign, horizon, self.selector_quantile_bp)
            for profile in self.profiles
            for sign in (-1, 1)
            for horizon in self.holding_bars
        }
        if observed != expected:
            raise ValueError("routed replay family membership drifted")

    def source_implementation(self, function_name: str) -> str:
        return (
            f"{self.source_module_name}.{function_name}@sha256:"
            f"{self.source_implementation_sha256}"
        )

    def producer_implementation_identities(self) -> dict[str, str]:
        return {
            "adapter_sha256": routed_sleeve_replay_implementation_sha256(),
            "discovery_sha256": discovery_implementation_sha256(),
            "family_sha256": self.historical_family.identity.removeprefix(
                "historical-family:"
            ),
            "loader_sha256": routed_sleeve_replay_loader_sha256(),
            "source_sha256": self.source_implementation_sha256,
            "trace_engine_sha256": (
                routed_sleeve_trace_engine_implementation_sha256()
            ),
        }


@dataclass(frozen=True, slots=True)
class RoutedReplayConfiguration:
    ordinal: int
    configuration_id: str
    historical_reference_executable_id: str
    profile: str
    signal_sign: int
    holding_bars: int
    selector_quantile_bp: int

    @property
    def route_sign(self) -> int:
        return self.signal_sign

    def semantic_parameters(self) -> dict[str, object]:
        return {
            "configuration_id": self.configuration_id,
            "historical_reference_executable_id": (
                self.historical_reference_executable_id
            ),
            "holding_bars": self.holding_bars,
            "profile": self.profile,
            "selector_quantile_bp": self.selector_quantile_bp,
            "signal_sign": self.signal_sign,
        }


def routed_replay_configurations(
    definition: RoutedReplayFamilyDefinition,
) -> tuple[RoutedReplayConfiguration, ...]:
    values = tuple(
        RoutedReplayConfiguration(
            ordinal=member.ordinal,
            configuration_id=member.configuration_id,
            historical_reference_executable_id=(
                member.historical_reference_executable_id
            ),
            profile=str(parameters["profile"]),
            signal_sign=int(parameters["signal_sign"]),
            holding_bars=int(parameters["holding_bars"]),
            selector_quantile_bp=int(parameters["selector_quantile_bp"]),
        )
        for member in definition.historical_family.members
        for parameters in (member.parameter_values(),)
    )
    if tuple(value.ordinal for value in values) != tuple(range(1, 13)):
        raise RuntimeError("routed replay family order drifted")
    return values


def _shared_implementation(function_name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{function_name}@sha256:"
        f"{discovery_implementation_sha256()}"
    )


def routed_replay_components(
    definition: RoutedReplayFamilyDefinition,
) -> tuple[ComponentSpec, ...]:
    volume = ComponentSpec(
        display_name="completed-bar volume body-pressure sleeve",
        protocol="feature.completed_bar_volume_body_pressure_12_96.replay.v1",
        implementation=(
            "axiom_rift.research.volume_price_discovery."
            "compute_volume_price_pressure_score@sha256:"
            f"{volume_price_implementation_sha256()}"
        ),
        spec={
            "availability": "completed_bar_only",
            "profile": "body_pressure_12_96",
            "role": "low_realized_volatility_sleeve",
        },
    )
    reversion = ComponentSpec(
        display_name="completed-bar slow96 overextension sleeve",
        protocol="feature.completed_bar_slow96_overextension.replay.v1",
        implementation=(
            "axiom_rift.research.reversion_discovery."
            "compute_overextension_score@sha256:"
            f"{reversion_implementation_sha256()}"
        ),
        spec={
            "availability": "completed_bar_only",
            "lookback_bars": 96,
            "role": "middle_realized_volatility_sleeve",
        },
    )
    volatility = ComponentSpec(
        display_name="completed-bar rv24-120 transition sleeve",
        protocol="feature.completed_bar_rv24_120_transition.replay.v1",
        implementation=(
            "axiom_rift.research.volatility_discovery."
            "compute_volatility_transition_score@sha256:"
            f"{volatility_implementation_sha256()}"
        ),
        spec={
            "availability": "completed_bar_only",
            "profile": "rv_ratio_24_120",
            "role": "high_realized_volatility_sleeve",
        },
    )
    label = ComponentSpec(
        display_name="realized fixed-hold after-cost replay label",
        protocol="label.realized_fixed_hold_native_net_pnl.replay.v1",
        implementation=_shared_implementation("simulate_fixed_hold"),
        spec={
            "availability": "exit_bar_open_after_registered_holding_interval",
            "cost_basis": "native_entry_and_exit_execution_cost",
            "parameter_fields": ["holding_bars"],
            "target": "native_net_pnl_micropoints",
        },
    )
    model = ComponentSpec(
        display_name="deterministic routed-sleeve replay hypothesis",
        protocol="model.deterministic_routed_sleeve.replay.v1",
        implementation=definition.source_implementation(
            definition.router_function_name
        ),
        spec={
            "fit": "none",
            "label_role": "scientific_outcome_never_runtime_input",
            "route_mechanism": definition.route_mechanism,
        },
        semantic_dependencies=(
            volume.identity,
            reversion.identity,
            volatility.identity,
            label.identity,
        ),
    )
    calibration = ComponentSpec(
        display_name="fold-train sleeve and volatility calibration",
        protocol="calibration.fold_train_routed_sleeve.replay.v1",
        implementation=definition.source_implementation(
            definition.calibrator_function_name
        ),
        spec={
            "parameter_fields": ["selector_quantile_bp"],
            "quantile_basis_points": definition.selector_quantile_bp,
            "quantile_method": "higher",
            "regime_cutoffs": "train_realized_volatility_tertiles",
        },
        semantic_dependencies=(model.identity,),
    )
    selector = ComponentSpec(
        display_name="absolute normalized routed-score selector",
        protocol="selector.absolute_normalized_routed_score.replay.v1",
        implementation=definition.source_implementation(
            definition.router_function_name
        ),
        spec={
            "entry_threshold": "absolute_normalized_score_at_least_one",
            "parameter_fields": ["selector_quantile_bp"],
        },
        semantic_dependencies=(calibration.identity,),
    )
    synthesis = ComponentSpec(
        display_name="exact historical routed-family member",
        protocol="synthesis.historical_routed_sleeve_member.replay.v1",
        implementation=definition.source_implementation(
            definition.router_function_name
        ),
        spec={
            "exact_member_count": 12,
            "historical_family_identity": definition.historical_family.identity,
            "parameter_fields": [
                "configuration_id",
                "historical_reference_executable_id",
                "profile",
            ],
            "profiles": list(definition.profiles),
        },
        semantic_dependencies=(selector.identity,),
    )
    trade = ComponentSpec(
        display_name="completed-bar next-open routed direction",
        protocol="trade.completed_bar_next_open_routed_direction.replay.v1",
        implementation=_shared_implementation("simulate_fixed_hold"),
        spec={
            "decision_time": "bar_open_plus_5m",
            "direction": "signal_sign_times_routed_score_sign",
            "entry_time": "next_exact_bar_open",
            "parameter_fields": ["signal_sign"],
        },
        semantic_dependencies=(synthesis.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="fixed-hold nonoverlap routed lifecycle",
        protocol="lifecycle.fixed_hold_no_overlap.replay.v2",
        implementation=_shared_implementation("simulate_fixed_hold"),
        spec={
            "entry_overlap": "reject_while_position_slot_is_occupied",
            "gap_action": "exclude_path",
            "parameter_fields": ["holding_bars"],
        },
        semantic_dependencies=(trade.identity,),
    )
    execution = ComponentSpec(
        display_name="causal lagged-spread routed execution",
        protocol="execution.fpmarkets_lagged_spread.replay.v1",
        implementation=_shared_implementation("causal_effective_spread"),
        spec={
            "point": "0.01",
            "stress": "half_effective_spread_each_side",
            "zero_spread": (
                "gap_reset_lagged_positive_288_bar_median_min_24_else_unknown"
            ),
        },
        semantic_dependencies=(lifecycle.identity,),
    )
    risk = ComponentSpec(
        display_name="fixed one-lot routed replay risk",
        protocol="risk.fixed_one_lot.v1",
        implementation=_shared_implementation("simulate_fixed_hold"),
        spec={"dynamic_sizing": False, "lot": 1, "positions_per_sleeve": 1},
        semantic_dependencies=(execution.identity,),
    )
    portfolio = ComponentSpec(
        display_name="exact concurrent routed-family inference",
        protocol="portfolio.concurrent_fixed_hold_family_inference.v2",
        implementation=(
            "axiom_rift.research.fixed_hold_family_trace."
            "build_fixed_hold_trace_calculation@sha256:"
            f"{fixed_hold_trace_implementation_sha256()}"
        ),
        spec={
            "historical_context_adjustment_authority": (
                "context_only_never_adjustment_factor"
            ),
            "parameter_fields": [
                "alpha_ppm",
                "base_seed",
                "block_lengths",
                "bootstrap_samples",
                "historical_context_prior_global_exposure_count",
                "monte_carlo_confidence_ppm",
            ],
            "selection_family_scope": "exact_registered_concurrent_family",
        },
        semantic_dependencies=(risk.identity,),
    )
    return (
        volume,
        reversion,
        volatility,
        label,
        model,
        calibration,
        selector,
        synthesis,
        trade,
        lifecycle,
        execution,
        risk,
        portfolio,
    )


def _shared_parameters(
    definition: RoutedReplayFamilyDefinition,
    historical_context_prior_global_exposure_count: int,
) -> dict[str, object]:
    if (
        type(historical_context_prior_global_exposure_count) is not int
        or historical_context_prior_global_exposure_count
        < definition.original_family_end_global_exposure_count
    ):
        raise ValueError("historical context precedes the routed family")
    return {
        "alpha_ppm": ROUTED_REPLAY_ALPHA_PPM,
        "base_seed": SELECTION_SEED,
        "block_lengths": list(SELECTION_BLOCK_LENGTHS),
        "bootstrap_samples": SELECTION_BOOTSTRAP_SAMPLES,
        "historical_context_prior_global_exposure_count": (
            historical_context_prior_global_exposure_count
        ),
        "monte_carlo_confidence_ppm": (
            SELECTION_MONTE_CARLO_CONFIDENCE_PPM
        ),
    }


def _engine_contract(definition: RoutedReplayFamilyDefinition) -> str:
    return (
        f"engine:{definition.engine_namespace}:"
        f"python{'.'.join(str(value) for value in sys.version_info[:3])}:"
        f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
        f"adapter_{routed_sleeve_replay_implementation_sha256()}:"
        f"source_{definition.source_implementation_sha256}:"
        "trace_engine_"
        f"{routed_sleeve_trace_engine_implementation_sha256()}:"
        f"loader_{routed_sleeve_replay_loader_sha256()}:"
        f"shared_{discovery_implementation_sha256()}:"
        f"selection_{selection_inference_implementation_sha256()}:"
        "family_"
        f"{definition.historical_family.identity.removeprefix('historical-family:')}"
    )


def routed_replay_executable(
    definition: RoutedReplayFamilyDefinition,
    configuration: RoutedReplayConfiguration,
    *,
    historical_context_prior_global_exposure_count: int,
) -> ExecutableSpec:
    if configuration not in routed_replay_configurations(definition):
        raise ValueError("configuration is outside the exact routed family")
    return ExecutableSpec(
        display_name=(
            f"{definition.historical_family.original_study_id} replay "
            f"{configuration.configuration_id}"
        ),
        components=routed_replay_components(definition),
        parameters={
            **configuration.semantic_parameters(),
            **_shared_parameters(
                definition,
                historical_context_prior_global_exposure_count,
            ),
        },
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:"
            "rolling_windows_9_observed_development"
        ),
        clock_contract=ROUTED_REPLAY_CLOCK_CONTRACT,
        cost_contract=ROUTED_REPLAY_COST_CONTRACT,
        engine_contract=_engine_contract(definition),
    )


def routed_replay_baseline_executable(
    definition: RoutedReplayFamilyDefinition,
    *,
    historical_context_prior_global_exposure_count: int,
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"{definition.family_name} non-evaluated comparison anchor",
        components=routed_replay_components(definition),
        parameters={
            **_shared_parameters(
                definition,
                historical_context_prior_global_exposure_count,
            ),
            "configuration_id": "comparison-anchor",
            "historical_reference_executable_id": "none",
            "holding_bars": 0,
            "profile": "comparison_anchor_none",
            "selector_quantile_bp": definition.selector_quantile_bp,
            "signal_sign": 0,
        },
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:"
            "rolling_windows_9_observed_development"
        ),
        clock_contract=ROUTED_REPLAY_CLOCK_CONTRACT,
        cost_contract=ROUTED_REPLAY_COST_CONTRACT,
        engine_contract=_engine_contract(definition),
    )


def routed_replay_controlled_chassis(
    definition: RoutedReplayFamilyDefinition,
    *,
    historical_context_prior_global_exposure_count: int,
) -> ControlledStudyChassis:
    baseline = routed_replay_baseline_executable(
        definition,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
    )
    chassis = ControlledStudyChassis(
        baseline_executable=baseline,
        changed_domains=(
            ResearchLayer.LABEL,
            ResearchLayer.LIFECYCLE,
            ResearchLayer.SYNTHESIS,
            ResearchLayer.TRADE,
        ),
        controlled_domains=(
            ResearchLayer.CALIBRATION,
            ResearchLayer.EXECUTION,
            ResearchLayer.FEATURE,
            ResearchLayer.MODEL,
            ResearchLayer.PORTFOLIO,
            ResearchLayer.RISK,
            ResearchLayer.SELECTOR,
        ),
        architecture=ArchitectureChassisSpec.from_executable(baseline),
    )
    payload = chassis.to_identity_payload()
    for configuration in routed_replay_configurations(definition):
        validate_controlled_executable(
            payload,
            routed_replay_executable(
                definition,
                configuration,
                historical_context_prior_global_exposure_count=(
                    historical_context_prior_global_exposure_count
                ),
            ),
        )
    return chassis


def routed_replay_executable_map(
    definition: RoutedReplayFamilyDefinition,
    *,
    historical_context_prior_global_exposure_count: int,
) -> dict[str, RoutedReplayConfiguration]:
    return {
        routed_replay_executable(
            definition,
            configuration,
            historical_context_prior_global_exposure_count=(
                historical_context_prior_global_exposure_count
            ),
        ).identity: configuration
        for configuration in routed_replay_configurations(definition)
    }


def routed_replay_protocol_definition(
    definition: RoutedReplayFamilyDefinition,
    *,
    historical_context_prior_global_exposure_count: int,
) -> FixedHoldProtocolDefinition:
    configurations = routed_replay_configurations(definition)
    return FixedHoldProtocolDefinition(
        family=definition.historical_family,
        prospective_executable_ids=tuple(
            routed_replay_executable(
                definition,
                configuration,
                historical_context_prior_global_exposure_count=(
                    historical_context_prior_global_exposure_count
                ),
            ).identity
            for configuration in configurations
        ),
        protocol_id=definition.trace_protocol_id,
        fold_ids=EXPECTED_FOLD_IDS,
        invariance_keys=tuple(sorted(definition.profiles)),
        allowed_regimes=("high", "low", "middle"),
        dataset_sha256=DATASET_SHA256,
        material_identity=OBSERVED_MATERIAL_ID,
        split_artifact_sha256=ROLLING_SPLIT_SHA256,
        clock_contract=ROUTED_REPLAY_CLOCK_CONTRACT,
        cost_contract=ROUTED_REPLAY_COST_CONTRACT,
        producer_implementation_identities=tuple(
            sorted(definition.producer_implementation_identities().items())
        ),
        historical_context_id=definition.historical_context_id,
        historical_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=(
            definition.original_family_end_global_exposure_count
        ),
        alpha_ppm=ROUTED_REPLAY_ALPHA_PPM,
        bootstrap_samples=SELECTION_BOOTSTRAP_SAMPLES,
        block_lengths=SELECTION_BLOCK_LENGTHS,
        monte_carlo_confidence_ppm=SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
        base_seed=SELECTION_SEED,
    )


__all__ = [
    "ROUTED_REPLAY_ALPHA_PPM",
    "ROUTED_REPLAY_CLOCK_CONTRACT",
    "ROUTED_REPLAY_COST_CONTRACT",
    "RoutedReplayConfiguration",
    "RoutedReplayFamilyDefinition",
    "routed_replay_baseline_executable",
    "routed_replay_components",
    "routed_replay_configurations",
    "routed_replay_controlled_chassis",
    "routed_replay_executable",
    "routed_replay_executable_map",
    "routed_replay_protocol_definition",
    "routed_sleeve_replay_implementation_sha256",
    "routed_sleeve_replay_loader_sha256",
]
