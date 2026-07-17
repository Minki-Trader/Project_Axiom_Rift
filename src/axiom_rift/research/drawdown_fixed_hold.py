"""Writer-bound prospective drawdown depth-duration fixed-hold research.

Historical family identity is runtime data supplied by an authenticated replay
authority.  This reusable mechanism contains no Mission or Study identifier and
never imports a frozen historical family catalog.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any

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
from axiom_rift.research.completed_period_atomic_trace import (
    completed_period_proxy_execution_spec,
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
    DiscoveryBoundaryError,
    _consecutive_run,
    _time_ns,
    discovery_implementation_sha256,
)
from axiom_rift.research.evidence_inputs import (
    VerifiedEvidenceReader,
    read_bound_evidence_inputs,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FixedHoldProtocolDefinition,
    expected_fixed_hold_control_inventory,
    expected_fixed_hold_family_inventory,
)
from axiom_rift.research.fixed_hold_historical_projection import (
    HISTORICAL_DRAWDOWN_EVALUATION_SCHEMA,
    derive_fixed_hold_semantic_surfaces,
)
from axiom_rift.research.fixed_hold_trace_engine import (
    compute_fixed_hold_family_trace,
    fixed_hold_trace_engine_implementation_sha256,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
)
from axiom_rift.research.historical_semantic_transition import (
    HISTORICAL_COST_TIMING_TRANSITION_POLICY,
    NO_SEMANTIC_TRANSITION_POLICY,
    build_historical_cost_timing_transition,
)
from axiom_rift.research.scientific_trace import (
    DRAWDOWN_REPLAY_TRACE_PROTOCOL_ID,
)
from axiom_rift.research.selection_inference import (
    selection_inference_implementation_sha256,
)


DRAWDOWN_FIXED_HOLD_ALPHA_PPM = 100_000
DRAWDOWN_FIXED_HOLD_LOOKBACK_BARS = 288
DRAWDOWN_FIXED_HOLD_SELECTOR_QUANTILE_BP = 7_000
DRAWDOWN_FIXED_HOLD_HOLDING_BARS = 24
DRAWDOWN_FIXED_HOLD_CONTEXT_PARAMETER = (
    "historical_context_prior_global_exposure_count"
)
DRAWDOWN_FIXED_HOLD_ORIGINAL_END_PARAMETER = (
    "original_family_end_global_exposure_count"
)
DRAWDOWN_FIXED_HOLD_PROFILES = (
    "drawdown_depth_288",
    "drawdown_duration_288",
)
DRAWDOWN_PHASE_FIXED_HOLD_PROFILES = (
    "depth_duration_interaction_576",
    "drawdown_recovery_velocity_12",
)
DRAWDOWN_FIXED_HOLD_COMPARISON_ANCHOR_PROFILE = "comparison_anchor_none"
DRAWDOWN_FIXED_HOLD_CLOCK_CONTRACT = (
    "clock:fpmarkets_m5_bar_open_completed_plus_5m_v2"
)
DRAWDOWN_FIXED_HOLD_COST_CONTRACT = (
    "cost:fpmarkets_completed_bar_spread_proxy_segment_positive_median_min_1_unknown_entry_cancel_"
    "half_spread_stress_v1"
)
DRAWDOWN_FIXED_HOLD_HISTORICAL_EVALUATION_HASHES = {
    "drawdown_depth_288-deterioration-h24": (
        "e08c4e8a131160a35f86c166f55a79f2d93cfa36fd613a4f9e0afc846980c1fc"
    ),
    "drawdown_depth_288-recovery-h24": (
        "13bd4f0940566038250db1eabcdd1466252761227e463ad2cff1e78b523e4c19"
    ),
    "drawdown_duration_288-deterioration-h24": (
        "e00a596d85c6639bf02e095cdedb0d7caac0e5def7239d35c4e1bbdf3d390dbd"
    ),
    "drawdown_duration_288-recovery-h24": (
        "bda62dbf52f937dc7723199d10adaefd52994a241056d6542cd56883b2fbe02d"
    ),
}
_EXPECTED_CONFIGURATION_IDS = tuple(
    DRAWDOWN_FIXED_HOLD_HISTORICAL_EVALUATION_HASHES
)
_THIS_FILE = Path(__file__).resolve()


@dataclass(frozen=True, slots=True)
class _DrawdownFamilySettings:
    profiles: tuple[str, str]
    holding_bars: int
    lookback_bars: int
    selector_quantile_bp: int
    score_mode: str
    historical_transition_required: bool


_DRAWDOWN_FAMILY_SETTINGS = (
    _DrawdownFamilySettings(
        profiles=DRAWDOWN_FIXED_HOLD_PROFILES,
        holding_bars=DRAWDOWN_FIXED_HOLD_HOLDING_BARS,
        lookback_bars=DRAWDOWN_FIXED_HOLD_LOOKBACK_BARS,
        selector_quantile_bp=DRAWDOWN_FIXED_HOLD_SELECTOR_QUANTILE_BP,
        score_mode="depth_and_duration",
        historical_transition_required=True,
    ),
    _DrawdownFamilySettings(
        profiles=DRAWDOWN_PHASE_FIXED_HOLD_PROFILES,
        holding_bars=12,
        lookback_bars=576,
        selector_quantile_bp=8_500,
        score_mode="phase_interaction_and_recovery_velocity",
        historical_transition_required=False,
    ),
)


def _settings_for_profile(profile: str) -> _DrawdownFamilySettings:
    matches = tuple(
        settings
        for settings in _DRAWDOWN_FAMILY_SETTINGS
        if profile in settings.profiles
    )
    if len(matches) != 1:
        raise ValueError("drawdown fixed-hold profile is not registered")
    return matches[0]


def _settings_for_configurations(
    configurations: tuple["DrawdownFixedHoldConfiguration", ...],
) -> _DrawdownFamilySettings:
    matches = tuple(
        settings
        for settings in _DRAWDOWN_FAMILY_SETTINGS
        if {item.profile for item in configurations} == set(settings.profiles)
    )
    if len(matches) != 1:
        raise ValueError("drawdown fixed-hold family is not registered")
    return matches[0]


def drawdown_fixed_hold_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def drawdown_fixed_hold_loader_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


def drawdown_fixed_hold_producer_implementation_identities() -> dict[str, str]:
    return {
        "discovery_sha256": discovery_implementation_sha256(),
        "drawdown_fixed_hold_sha256": (
            drawdown_fixed_hold_implementation_sha256()
        ),
        "loader_sha256": drawdown_fixed_hold_loader_sha256(),
        "trace_engine_sha256": fixed_hold_trace_engine_implementation_sha256(),
    }


@dataclass(frozen=True, slots=True)
class DrawdownFixedHoldConfiguration:
    ordinal: int
    configuration_id: str
    historical_reference_executable_id: str
    profile: str
    signal_sign: int
    holding_bars: int = DRAWDOWN_FIXED_HOLD_HOLDING_BARS
    lookback_bars: int = DRAWDOWN_FIXED_HOLD_LOOKBACK_BARS
    selector_quantile_bp: int = DRAWDOWN_FIXED_HOLD_SELECTOR_QUANTILE_BP
    unknown_entry_action: str = "cancel_before_open"

    def __post_init__(self) -> None:
        settings = _settings_for_profile(self.profile)
        if (
            type(self.ordinal) is not int
            or self.ordinal < 1
            or type(self.configuration_id) is not str
            or not self.configuration_id.isascii()
            or self.signal_sign not in {-1, 1}
            or self.holding_bars != settings.holding_bars
            or self.lookback_bars != settings.lookback_bars
            or self.selector_quantile_bp != settings.selector_quantile_bp
            or self.unknown_entry_action != "cancel_before_open"
            or not self.historical_reference_executable_id.startswith(
                "executable:"
            )
        ):
            raise ValueError("drawdown fixed-hold configuration is invalid")

    def semantic_parameters(self) -> dict[str, object]:
        return {
            "configuration_id": self.configuration_id,
            "historical_reference_executable_id": (
                self.historical_reference_executable_id
            ),
            "holding_bars": self.holding_bars,
            "lookback_bars": self.lookback_bars,
            "profile": self.profile,
            "selector_quantile_bp": self.selector_quantile_bp,
            "signal_sign": self.signal_sign,
            "unknown_entry_action": self.unknown_entry_action,
        }


def _configuration_from_member(
    member: HistoricalMemberSpec,
) -> DrawdownFixedHoldConfiguration:
    parameters = member.parameter_values()
    return DrawdownFixedHoldConfiguration(
        ordinal=member.ordinal,
        configuration_id=member.configuration_id,
        historical_reference_executable_id=(
            member.historical_reference_executable_id
        ),
        profile=str(parameters["profile"]),
        signal_sign=int(parameters["signal_sign"]),
        holding_bars=int(parameters["holding_bars"]),
        lookback_bars=int(parameters["lookback_bars"]),
        selector_quantile_bp=int(parameters["selector_quantile_bp"]),
        unknown_entry_action=str(parameters["unknown_entry_action"]),
    )


def drawdown_fixed_hold_configurations(
    historical_family: HistoricalFamilySpec,
) -> tuple[DrawdownFixedHoldConfiguration, ...]:
    if not isinstance(historical_family, HistoricalFamilySpec):
        raise TypeError("drawdown family is not Writer-bound")
    values = tuple(
        _configuration_from_member(member)
        for member in historical_family.members
    )
    settings = _settings_for_configurations(values)
    profile_signs = {(value.profile, value.signal_sign) for value in values}
    expected_profile_signs = {
        (profile, signal_sign)
        for profile in settings.profiles
        for signal_sign in (-1, 1)
    }
    if (
        tuple(value.ordinal for value in values)
        != tuple(range(1, len(values) + 1))
        or len(values) != 4
        or profile_signs != expected_profile_signs
    ):
        raise ValueError("drawdown fixed-hold family membership drifted")
    return values


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.drawdown_fixed_hold.{name}@sha256:"
        f"{drawdown_fixed_hold_implementation_sha256()}"
    )


def _shared(name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{name}@sha256:"
        f"{discovery_implementation_sha256()}"
    )


def drawdown_fixed_hold_components(
    historical_family: HistoricalFamilySpec,
) -> tuple[ComponentSpec, ...]:
    configurations = drawdown_fixed_hold_configurations(historical_family)
    settings = _settings_for_configurations(configurations)
    feature = ComponentSpec(
        display_name=(
            "causal completed-bar drawdown state"
            if settings.score_mode == "depth_and_duration"
            else "causal completed-bar drawdown phase interaction"
        ),
        protocol=(
            "feature.causal_drawdown_state.replay.v3"
            if settings.score_mode == "depth_and_duration"
            else "feature.causal_drawdown_phase.replay.v1"
        ),
        implementation=_local("compute_drawdown_fixed_hold_score"),
        spec={
            "availability": "completed_bar_close",
            "lookback_bars": settings.lookback_bars,
            "non_evaluated_anchor_profile": (
                DRAWDOWN_FIXED_HOLD_COMPARISON_ANCHOR_PROFILE
            ),
            "parameter_fields": ["lookback_bars", "profile"],
            "profiles": list(settings.profiles),
            **(
                {}
                if settings.score_mode == "depth_and_duration"
                else {"recovery_velocity_bars": 12}
            ),
        },
    )
    label = ComponentSpec(
        display_name="realized fixed-hold after-cost label",
        protocol="label.realized_fixed_hold_native_net_pnl.replay.v1",
        implementation=_shared("_evaluate_configuration"),
        spec={
            "availability": "exit_bar_open_after_registered_holding_interval",
            "cost_basis": "native_entry_and_exit_execution_cost",
            "parameter_fields": ["holding_bars"],
            "target": "native_net_pnl_micropoints",
        },
    )
    model = ComponentSpec(
        display_name="registered drawdown-state outcome hypothesis",
        protocol="model.deterministic_drawdown_state_hypothesis.replay.v2",
        implementation=_local("compute_drawdown_fixed_hold_score"),
        spec={
            "fit": "none",
            "label_role": "scientific_outcome_never_runtime_input",
            "score_role": "causal_completed_bar_state",
        },
        semantic_dependencies=(feature.identity, label.identity),
    )
    selector = ComponentSpec(
        display_name="fold-isolated drawdown selector",
        protocol="selector.fold_train_abs_quantile.replay.v3",
        implementation=_local("calibrate_drawdown_fixed_hold_selector"),
        spec={
            "calibration_role": "train_is_only",
            "minimum_train_observations": 1000,
            "parameter_fields": ["selector_quantile_bp"],
            "quantile_method": "higher",
        },
        semantic_dependencies=(model.identity,),
    )
    trade = ComponentSpec(
        display_name="completed-bar next-open directional entry",
        protocol="trade.completed_bar_next_open_direction.replay.v2",
        implementation=_shared("simulate_fixed_hold"),
        spec={
            "decision_time": "bar_open_plus_5m",
            "direction": "signal_sign_times_score_sign",
            "entry_time": "next_exact_bar_open",
            "parameter_fields": ["signal_sign"],
        },
        semantic_dependencies=(selector.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="fixed-hold nonoverlap lifecycle",
        protocol="lifecycle.fixed_hold_no_overlap.replay.v2",
        implementation=_shared("simulate_fixed_hold"),
        spec={
            "entry_overlap": "reject_while_position_slot_is_occupied",
            "gap_action": "exclude_path",
            "parameter_fields": ["holding_bars", "unknown_entry_action"],
        },
        semantic_dependencies=(trade.identity,),
    )
    execution = ComponentSpec(
        display_name="completed-period spread-proxy execution",
        protocol="execution.fpmarkets_completed_period_spread_proxy.v2",
        implementation=_local("causal_drawdown_fixed_hold_spread"),
        spec=completed_period_proxy_execution_spec(
            repair_policy=(
                "same_contiguous_segment_strict_prior_positive_288_bar_"
                "median_min_1_else_unknown"
            )
        ),
        semantic_dependencies=(lifecycle.identity,),
    )
    risk = ComponentSpec(
        display_name="fixed one-lot replay risk",
        protocol="risk.fixed_one_lot.v1",
        implementation=_shared("simulate_fixed_hold"),
        spec={"dynamic_sizing": False, "lot": 1, "positions_per_sleeve": 1},
        semantic_dependencies=(execution.identity,),
    )
    synthesis = ComponentSpec(
        display_name="Writer-bound drawdown family member",
        protocol="synthesis.historical_fixed_hold_member.v2",
        implementation=_local("drawdown_fixed_hold_executable"),
        spec={
            "exact_member_count": historical_family.family_size,
            "historical_family_identity": historical_family.identity,
            "parameter_fields": [
                "configuration_id",
                "historical_reference_executable_id",
            ],
        },
        semantic_dependencies=(risk.identity,),
    )
    portfolio = ComponentSpec(
        display_name="exact concurrent drawdown family inference",
        protocol="portfolio.concurrent_fixed_hold_family_inference.v3",
        implementation=_local("drawdown_fixed_hold_protocol_definition"),
        spec={
            "historical_context_adjustment_authority": (
                "context_only_never_adjustment_factor"
            ),
            "parameter_fields": [
                "alpha_ppm",
                "base_seed",
                "block_lengths",
                "bootstrap_samples",
                DRAWDOWN_FIXED_HOLD_CONTEXT_PARAMETER,
                DRAWDOWN_FIXED_HOLD_ORIGINAL_END_PARAMETER,
                "monte_carlo_confidence_ppm",
            ],
            "selection_family_scope": "exact_registered_concurrent_family",
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


def _validated_exposure_context(
    *,
    historical_family: HistoricalFamilySpec,
    prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> tuple[int, int]:
    if (
        type(prior_global_exposure_count) is not int
        or type(original_family_end_global_exposure_count) is not int
        or original_family_end_global_exposure_count
        < historical_family.family_size
        or prior_global_exposure_count
        < original_family_end_global_exposure_count
    ):
        raise ValueError("drawdown historical exposure context is invalid")
    return prior_global_exposure_count, original_family_end_global_exposure_count


def _shared_parameters(
    *,
    historical_family: HistoricalFamilySpec,
    prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> dict[str, object]:
    prior, original_end = _validated_exposure_context(
        historical_family=historical_family,
        prior_global_exposure_count=prior_global_exposure_count,
        original_family_end_global_exposure_count=(
            original_family_end_global_exposure_count
        ),
    )
    return {
        "alpha_ppm": DRAWDOWN_FIXED_HOLD_ALPHA_PPM,
        "base_seed": SELECTION_SEED,
        "block_lengths": list(SELECTION_BLOCK_LENGTHS),
        "bootstrap_samples": SELECTION_BOOTSTRAP_SAMPLES,
        DRAWDOWN_FIXED_HOLD_CONTEXT_PARAMETER: prior,
        DRAWDOWN_FIXED_HOLD_ORIGINAL_END_PARAMETER: original_end,
        "monte_carlo_confidence_ppm": SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
    }


def _engine_contract() -> str:
    return (
        "engine:drawdown_fixed_hold_v1:"
        f"python{'.'.join(str(value) for value in sys.version_info[:3])}:"
        f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
        f"adapter_{drawdown_fixed_hold_implementation_sha256()}:"
        f"trace_engine_{fixed_hold_trace_engine_implementation_sha256()}:"
        f"loader_{drawdown_fixed_hold_loader_sha256()}:"
        f"shared_{discovery_implementation_sha256()}:"
        f"selection_{selection_inference_implementation_sha256()}"
    )


def drawdown_fixed_hold_executable(
    configuration: DrawdownFixedHoldConfiguration,
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ExecutableSpec:
    if configuration not in drawdown_fixed_hold_configurations(
        historical_family
    ):
        raise ValueError("configuration is outside the Writer-bound family")
    return ExecutableSpec(
        display_name=(
            f"{historical_family.original_study_id} prospective drawdown "
            f"{configuration.configuration_id}"
        ),
        components=drawdown_fixed_hold_components(historical_family),
        parameters={
            **configuration.semantic_parameters(),
            **_shared_parameters(
                historical_family=historical_family,
                prior_global_exposure_count=(
                    historical_context_prior_global_exposure_count
                ),
                original_family_end_global_exposure_count=(
                    original_family_end_global_exposure_count
                ),
            ),
        },
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:"
            "rolling_windows_9_observed_development"
        ),
        clock_contract=DRAWDOWN_FIXED_HOLD_CLOCK_CONTRACT,
        cost_contract=DRAWDOWN_FIXED_HOLD_COST_CONTRACT,
        engine_contract=_engine_contract(),
    )


def drawdown_fixed_hold_baseline_executable(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ExecutableSpec:
    settings = _settings_for_configurations(
        drawdown_fixed_hold_configurations(historical_family)
    )
    return ExecutableSpec(
        display_name=(
            f"{historical_family.original_study_id} prospective drawdown "
            "non-evaluated comparison anchor"
        ),
        components=drawdown_fixed_hold_components(historical_family),
        parameters={
            **_shared_parameters(
                historical_family=historical_family,
                prior_global_exposure_count=(
                    historical_context_prior_global_exposure_count
                ),
                original_family_end_global_exposure_count=(
                    original_family_end_global_exposure_count
                ),
            ),
            "configuration_id": "comparison-anchor",
            "historical_reference_executable_id": "none",
            "holding_bars": settings.holding_bars,
            "lookback_bars": settings.lookback_bars,
            "profile": DRAWDOWN_FIXED_HOLD_COMPARISON_ANCHOR_PROFILE,
            "selector_quantile_bp": settings.selector_quantile_bp,
            "signal_sign": 0,
            "unknown_entry_action": "cancel_before_open",
        },
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:"
            "rolling_windows_9_observed_development"
        ),
        clock_contract=DRAWDOWN_FIXED_HOLD_CLOCK_CONTRACT,
        cost_contract=DRAWDOWN_FIXED_HOLD_COST_CONTRACT,
        engine_contract=_engine_contract(),
    )


def drawdown_fixed_hold_controlled_chassis(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ControlledStudyChassis:
    baseline = drawdown_fixed_hold_baseline_executable(
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
    for configuration in drawdown_fixed_hold_configurations(historical_family):
        validate_controlled_executable(
            payload,
            drawdown_fixed_hold_executable(
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


def drawdown_fixed_hold_executable_map(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> dict[str, DrawdownFixedHoldConfiguration]:
    return {
        drawdown_fixed_hold_executable(
            configuration,
            historical_family=historical_family,
            historical_context_prior_global_exposure_count=(
                historical_context_prior_global_exposure_count
            ),
            original_family_end_global_exposure_count=(
                original_family_end_global_exposure_count
            ),
        ).identity: configuration
        for configuration in drawdown_fixed_hold_configurations(
            historical_family
        )
    }


def drawdown_fixed_hold_protocol_definition(
    context: HistoricalFamilyReplayContext,
) -> FixedHoldProtocolDefinition:
    if not isinstance(context, HistoricalFamilyReplayContext):
        raise TypeError("drawdown replay context is not typed")
    family = context.family
    configurations = drawdown_fixed_hold_configurations(family)
    settings = _settings_for_configurations(configurations)
    prior, original_end = _validated_exposure_context(
        historical_family=family,
        prior_global_exposure_count=context.prior_global_exposure_count,
        original_family_end_global_exposure_count=(
            context.original_family_end_global_exposure_count
        ),
    )
    executables = tuple(
        drawdown_fixed_hold_executable(
            configuration,
            historical_family=family,
            historical_context_prior_global_exposure_count=prior,
            original_family_end_global_exposure_count=original_end,
        )
        for configuration in configurations
    )
    clocks = {executable.clock_contract for executable in executables}
    costs = {executable.cost_contract for executable in executables}
    if len(clocks) != 1 or len(costs) != 1:
        raise RuntimeError("drawdown execution contracts drifted")
    return FixedHoldProtocolDefinition(
        family=family,
        prospective_executable_ids=tuple(
            executable.identity for executable in executables
        ),
        protocol_id=DRAWDOWN_REPLAY_TRACE_PROTOCOL_ID,
        fold_ids=EXPECTED_FOLD_IDS,
        invariance_keys=tuple(sorted(settings.profiles)),
        allowed_regimes=("high", "low", "middle"),
        dataset_sha256=DATASET_SHA256,
        material_identity=OBSERVED_MATERIAL_ID,
        split_artifact_sha256=ROLLING_SPLIT_SHA256,
        clock_contract=next(iter(clocks)),
        cost_contract=next(iter(costs)),
        producer_implementation_identities=tuple(
            sorted(
                drawdown_fixed_hold_producer_implementation_identities().items()
            )
        ),
        historical_context_id=context.family_authority_id,
        historical_prior_global_exposure_count=prior,
        original_family_end_global_exposure_count=original_end,
        alpha_ppm=DRAWDOWN_FIXED_HOLD_ALPHA_PPM,
        bootstrap_samples=SELECTION_BOOTSTRAP_SAMPLES,
        block_lengths=SELECTION_BLOCK_LENGTHS,
        monte_carlo_confidence_ppm=SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
        base_seed=SELECTION_SEED,
        historical_evaluation_artifacts=(
            tuple(
                (
                    configuration_id,
                    artifact_sha256,
                    HISTORICAL_DRAWDOWN_EVALUATION_SCHEMA,
                )
                for configuration_id, artifact_sha256 in sorted(
                    DRAWDOWN_FIXED_HOLD_HISTORICAL_EVALUATION_HASHES.items()
                )
            )
            if settings.historical_transition_required
            else ()
        ),
        semantic_transition_policy=(
            HISTORICAL_COST_TIMING_TRANSITION_POLICY
            if settings.historical_transition_required
            else NO_SEMANTIC_TRANSITION_POLICY
        ),
    )


def _rolling_peak_age(
    close: np.ndarray,
    lookback_bars: int = DRAWDOWN_FIXED_HOLD_LOOKBACK_BARS,
) -> tuple[np.ndarray, np.ndarray]:
    peak = np.full(len(close), np.nan)
    age = np.full(len(close), np.nan)
    queue: deque[int] = deque()
    for index, value in enumerate(close):
        while queue and close[queue[-1]] <= value:
            queue.pop()
        queue.append(index)
        while queue and queue[0] <= index - lookback_bars:
            queue.popleft()
        if index >= lookback_bars - 1:
            peak[index] = close[queue[0]]
            age[index] = index - queue[0]
    return peak, age


def compute_drawdown_fixed_hold_score(
    frame: pd.DataFrame,
    profile: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    settings = _settings_for_profile(profile)
    close = frame["close"].to_numpy(float)
    if np.any(~np.isfinite(close)) or np.any(close <= 0):
        raise ValueError("drawdown fixed-hold close is invalid")
    peak, age = _rolling_peak_age(close, settings.lookback_bars)
    depth = (
        np.divide(
            close,
            peak,
            out=np.full(len(close), np.nan),
            where=np.isfinite(peak) & (peak > 0),
        )
        - 1
    )
    if profile == "drawdown_depth_288":
        score = depth
    elif profile == "drawdown_duration_288":
        score = -age
    elif profile == "depth_duration_interaction_576":
        score = depth * np.log1p(age)
    else:
        score = np.full(len(close), np.nan)
        score[12:] = depth[12:] - depth[:-12]
    returns = np.full(len(close), np.nan)
    returns[1:] = np.diff(np.log(close))
    volatility = (
        pd.Series(returns)
        .rolling(96, min_periods=96)
        .std(ddof=1)
        .to_numpy(float)
    )
    return score, volatility, _consecutive_run(_time_ns(frame))


def causal_drawdown_fixed_hold_spread(
    spread: np.ndarray,
    time_ns: np.ndarray,
) -> np.ndarray:
    values = np.asarray(spread, float)
    times = np.asarray(time_ns, np.int64)
    if (
        len(values) != len(times)
        or np.any(~np.isfinite(values))
        or np.any(values < 0)
    ):
        raise ValueError("drawdown fixed-hold spread is invalid")
    segment = np.zeros(len(times), np.int64)
    if len(times) > 1:
        segment[1:] = np.cumsum(np.diff(times) != 300_000_000_000)
    positive = pd.Series(np.where(values > 0, values, np.nan))
    groups = pd.Series(segment)
    lagged = positive.groupby(groups, sort=False).transform(
        lambda part: part.shift(1).rolling(288, min_periods=1).median()
    )
    return np.where(values > 0, values, lagged.to_numpy(float))


def calibrate_drawdown_fixed_hold_selector(
    score: np.ndarray,
    mask: np.ndarray,
) -> float:
    return _calibrate_drawdown_selector(
        score,
        mask,
        settings=_DRAWDOWN_FAMILY_SETTINGS[0],
    )


def _calibrate_drawdown_selector(
    score: np.ndarray,
    mask: np.ndarray,
    *,
    settings: _DrawdownFamilySettings,
) -> float:
    values = np.abs(score[mask & np.isfinite(score)])
    if len(values) < 1000:
        raise DiscoveryBoundaryError("drawdown selector is too small")
    return float(
        np.quantile(
            values,
            settings.selector_quantile_bp / 10_000,
            method="higher",
        )
    )


def _load_historical_evaluations(
    definition: FixedHoldProtocolDefinition,
    evidence_reader: VerifiedEvidenceReader,
    evidence_input_hashes: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    evaluations: dict[str, dict[str, Any]] = {}
    artifacts = definition.historical_artifacts_by_configuration()
    if tuple(sorted(artifacts)) != tuple(sorted(_EXPECTED_CONFIGURATION_IDS)):
        raise RuntimeError("drawdown historical artifact inventory drifted")
    inputs = read_bound_evidence_inputs(
        evidence_reader,
        evidence_input_hashes,
        expected_bindings=tuple(
            (
                str(artifact["artifact_sha256"]),
                str(artifact["schema"]),
            )
            for _, artifact in sorted(artifacts.items())
        ),
    )
    for configuration_id, artifact in sorted(artifacts.items()):
        identity = str(artifact["artifact_sha256"])
        value = inputs.require_identity(identity).value
        if (
            value.get("schema") != artifact["schema"]
            or value.get("schema") != HISTORICAL_DRAWDOWN_EVALUATION_SCHEMA
            or value.get("subject_configuration_id") != configuration_id
        ):
            raise RuntimeError("drawdown historical evaluation binding drifted")
        evaluations[configuration_id] = value
    return evaluations


def build_drawdown_historical_semantic_transitions(
    definition: FixedHoldProtocolDefinition,
    windows: tuple[dict[str, object], ...],
    trade_observations: tuple[dict[str, object], ...],
    intent_observations: tuple[dict[str, object], ...],
    historical_evaluations: dict[str, dict[str, Any]],
) -> tuple[dict[str, object], ...]:
    inventory = expected_fixed_hold_family_inventory(definition)
    controls = expected_fixed_hold_control_inventory(definition)
    corrected = derive_fixed_hold_semantic_surfaces(
        ordered_family=inventory,
        control_bindings=controls,
        windows=windows,
        trades=trade_observations,
        intents=intent_observations,
        prefix_invariance_mismatch_count=0,
    )
    artifacts = definition.historical_artifacts_by_configuration()
    transitions: list[dict[str, object]] = []
    for member in inventory:
        configuration_id = str(member["configuration_id"])
        artifact = artifacts[configuration_id]
        projection = corrected[configuration_id]
        transitions.append(
            build_historical_cost_timing_transition(
                configuration_id=configuration_id,
                corrected_executable_id=str(member["executable_id"]),
                historical_reference_executable_id=(
                    str(member["historical_reference_executable_id"])
                ),
                historical_artifact_sha256=artifact["artifact_sha256"],
                historical_artifact_schema=artifact["schema"],
                historical_evaluation_artifact=(
                    historical_evaluations[configuration_id]
                ),
                corrected_structural_surfaces=projection["structural"],
                corrected_economic_surfaces=projection["economic"],
            )
        )
    return tuple(transitions)


def compute_drawdown_fixed_hold_family_trace(
    repository_root: str | Path,
    definition: FixedHoldProtocolDefinition,
    evidence_reader: VerifiedEvidenceReader,
    evidence_input_hashes: tuple[str, ...],
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    if (
        not isinstance(definition, FixedHoldProtocolDefinition)
        or not isinstance(definition.family, HistoricalFamilySpec)
    ):
        raise TypeError("drawdown definition is not Writer-bound")
    configurations = drawdown_fixed_hold_configurations(definition.family)
    settings = _settings_for_configurations(configurations)
    semantic_transition_builder = None
    if settings.historical_transition_required:
        historical_evaluations = _load_historical_evaluations(
            definition,
            evidence_reader,
            evidence_input_hashes,
        )

        def semantic_transitions(
            _repository_root: Path,
            scoped_definition: FixedHoldProtocolDefinition,
            windows: tuple[dict[str, object], ...],
            trade_observations: tuple[dict[str, object], ...],
            intent_observations: tuple[dict[str, object], ...],
        ) -> tuple[dict[str, object], ...]:
            return build_drawdown_historical_semantic_transitions(
                scoped_definition,
                windows,
                trade_observations,
                intent_observations,
                historical_evaluations,
            )

        semantic_transition_builder = semantic_transitions

    def calibrate(score: np.ndarray, mask: np.ndarray) -> float:
        return _calibrate_drawdown_selector(
            score,
            mask,
            settings=settings,
        )

    return compute_fixed_hold_family_trace(
        repository_root,
        definition=definition,
        configurations=configurations,
        feature_builder=compute_drawdown_fixed_hold_score,
        selector_calibrator=calibrate,
        spread_builder=causal_drawdown_fixed_hold_spread,
        semantic_transition_builder=semantic_transition_builder,
    )


__all__ = [
    "DRAWDOWN_FIXED_HOLD_CONTEXT_PARAMETER",
    "DRAWDOWN_FIXED_HOLD_HISTORICAL_EVALUATION_HASHES",
    "DRAWDOWN_FIXED_HOLD_ORIGINAL_END_PARAMETER",
    "DRAWDOWN_FIXED_HOLD_PROFILES",
    "DRAWDOWN_PHASE_FIXED_HOLD_PROFILES",
    "DrawdownFixedHoldConfiguration",
    "build_drawdown_historical_semantic_transitions",
    "calibrate_drawdown_fixed_hold_selector",
    "causal_drawdown_fixed_hold_spread",
    "compute_drawdown_fixed_hold_family_trace",
    "compute_drawdown_fixed_hold_score",
    "drawdown_fixed_hold_baseline_executable",
    "drawdown_fixed_hold_components",
    "drawdown_fixed_hold_configurations",
    "drawdown_fixed_hold_controlled_chassis",
    "drawdown_fixed_hold_executable",
    "drawdown_fixed_hold_executable_map",
    "drawdown_fixed_hold_implementation_sha256",
    "drawdown_fixed_hold_loader_sha256",
    "drawdown_fixed_hold_producer_implementation_identities",
    "drawdown_fixed_hold_protocol_definition",
]
