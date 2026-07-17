"""Writer-bound prospective fixed-hold research for historical gap families.

The same mechanism supports the two exact historical gap surfaces without
hard-coding a Study identity.  Family members, controls, holding period, and
selector calibration arrive through authenticated historical-family authority.
"""

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
from axiom_rift.research.fixed_hold_family_trace import (
    FixedHoldProtocolDefinition,
    fixed_hold_trace_implementation_sha256,
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
from axiom_rift.research.scientific_trace import GAP_REPLAY_TRACE_PROTOCOL_ID
from axiom_rift.research.selection_inference import (
    selection_inference_implementation_sha256,
)


GAP_FIXED_HOLD_ALPHA_PPM = 100_000
GAP_FIXED_HOLD_MINIMUM_GAP_MINUTES = 30
GAP_FIXED_HOLD_SELECTOR_QUANTILE_BP = 7_000
GAP_FIXED_HOLD_CONTEXT_PARAMETER = (
    "historical_context_prior_global_exposure_count"
)
GAP_FIXED_HOLD_ORIGINAL_END_PARAMETER = (
    "original_family_end_global_exposure_count"
)
GAP_EVENT_FIXED_HOLD_PROFILES = (
    "open_gap_30m",
    "first_bar_response_30m",
)
GAP_PATH_FIXED_HOLD_PROFILES = (
    "residual_gap_after_first_bar",
    "gap_fill_fraction_after_first_bar",
)
GAP_FIXED_HOLD_COMPARISON_ANCHOR_PROFILE = "comparison_anchor_none"
GAP_FIXED_HOLD_CLOCK_CONTRACT = (
    "clock:fpmarkets_m5_bar_open_completed_plus_5m_v2"
)
GAP_FIXED_HOLD_COST_CONTRACT = (
    "cost:fpmarkets_completed_bar_spread_proxy_gap_segment_positive_median_"
    "min_1_unknown_entry_cancel_half_spread_stress_v1"
)
_THIS_FILE = Path(__file__).resolve()


@dataclass(frozen=True, slots=True)
class _GapFamilySettings:
    profiles: tuple[str, str]
    holding_bars: int
    minimum_train_observations: int
    feature_mode: str


_GAP_FAMILY_SETTINGS = (
    _GapFamilySettings(
        profiles=GAP_EVENT_FIXED_HOLD_PROFILES,
        holding_bars=12,
        minimum_train_observations=500,
        feature_mode="gap_event",
    ),
    _GapFamilySettings(
        profiles=GAP_PATH_FIXED_HOLD_PROFILES,
        holding_bars=6,
        minimum_train_observations=350,
        feature_mode="post_gap_path",
    ),
)


def _settings_for_profile(profile: str) -> _GapFamilySettings:
    matches = tuple(
        settings
        for settings in _GAP_FAMILY_SETTINGS
        if profile in settings.profiles
    )
    if len(matches) != 1:
        raise ValueError("gap fixed-hold profile is not registered")
    return matches[0]


def _settings_for_configurations(
    configurations: tuple["GapFixedHoldConfiguration", ...],
) -> _GapFamilySettings:
    matches = tuple(
        settings
        for settings in _GAP_FAMILY_SETTINGS
        if {item.profile for item in configurations} == set(settings.profiles)
    )
    if len(matches) != 1:
        raise ValueError("gap fixed-hold family is not registered")
    return matches[0]


def gap_fixed_hold_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def gap_fixed_hold_loader_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


def gap_fixed_hold_producer_implementation_identities() -> dict[str, str]:
    return {
        "adapter_sha256": gap_fixed_hold_implementation_sha256(),
        "discovery_sha256": discovery_implementation_sha256(),
        "loader_sha256": gap_fixed_hold_loader_sha256(),
        "selection_sha256": selection_inference_implementation_sha256(),
        "trace_engine_sha256": (
            fixed_hold_trace_engine_implementation_sha256()
        ),
        "trace_schema_sha256": fixed_hold_trace_implementation_sha256(),
    }


@dataclass(frozen=True, slots=True)
class GapFixedHoldConfiguration:
    ordinal: int
    configuration_id: str
    historical_reference_executable_id: str
    profile: str
    signal_sign: int
    holding_bars: int
    minimum_gap_minutes: int = GAP_FIXED_HOLD_MINIMUM_GAP_MINUTES
    selector_quantile_bp: int = GAP_FIXED_HOLD_SELECTOR_QUANTILE_BP
    unknown_entry_action: str = "cancel_before_open"

    def __post_init__(self) -> None:
        settings = _settings_for_profile(self.profile)
        if (
            type(self.ordinal) is not int
            or self.ordinal < 1
            or type(self.configuration_id) is not str
            or not self.configuration_id.isascii()
            or type(self.historical_reference_executable_id) is not str
            or not self.historical_reference_executable_id.startswith(
                "executable:"
            )
            or self.signal_sign not in {-1, 1}
            or self.holding_bars != settings.holding_bars
            or self.minimum_gap_minutes != GAP_FIXED_HOLD_MINIMUM_GAP_MINUTES
            or self.selector_quantile_bp != GAP_FIXED_HOLD_SELECTOR_QUANTILE_BP
            or self.unknown_entry_action != "cancel_before_open"
        ):
            raise ValueError("gap fixed-hold configuration is invalid")

    def semantic_parameters(self) -> dict[str, object]:
        return {
            "configuration_id": self.configuration_id,
            "historical_reference_executable_id": (
                self.historical_reference_executable_id
            ),
            "holding_bars": self.holding_bars,
            "minimum_gap_minutes": self.minimum_gap_minutes,
            "profile": self.profile,
            "selector_quantile_bp": self.selector_quantile_bp,
            "signal_sign": self.signal_sign,
            "unknown_entry_action": self.unknown_entry_action,
        }


def _configuration_from_member(
    member: HistoricalMemberSpec,
) -> GapFixedHoldConfiguration:
    parameters = member.parameter_values()
    expected = {
        "holding_bars",
        "minimum_gap_minutes",
        "profile",
        "selector_quantile_bp",
        "signal_sign",
        "unknown_entry_action",
    }
    if set(parameters) != expected or any(
        type(parameters[name]) is not expected_type
        for name, expected_type in (
            ("holding_bars", int),
            ("minimum_gap_minutes", int),
            ("profile", str),
            ("selector_quantile_bp", int),
            ("signal_sign", int),
            ("unknown_entry_action", str),
        )
    ):
        raise ValueError("gap historical parameter surface is invalid")
    return GapFixedHoldConfiguration(
        ordinal=member.ordinal,
        configuration_id=member.configuration_id,
        historical_reference_executable_id=(
            member.historical_reference_executable_id
        ),
        profile=parameters["profile"],
        signal_sign=parameters["signal_sign"],
        holding_bars=parameters["holding_bars"],
        minimum_gap_minutes=parameters["minimum_gap_minutes"],
        selector_quantile_bp=parameters["selector_quantile_bp"],
        unknown_entry_action=parameters["unknown_entry_action"],
    )


def gap_fixed_hold_configurations(
    historical_family: HistoricalFamilySpec,
) -> tuple[GapFixedHoldConfiguration, ...]:
    if not isinstance(historical_family, HistoricalFamilySpec):
        raise TypeError("gap family is not Writer-bound")
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
        len(values) != 4
        or tuple(value.ordinal for value in values) != (1, 2, 3, 4)
        or profile_signs != expected_profile_signs
    ):
        raise ValueError("gap Writer-bound family is not an exact surface")
    return values


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.gap_fixed_hold.{name}@sha256:"
        f"{gap_fixed_hold_implementation_sha256()}"
    )


def _shared(name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{name}@sha256:"
        f"{discovery_implementation_sha256()}"
    )


def gap_fixed_hold_components(
    historical_family: HistoricalFamilySpec,
) -> tuple[ComponentSpec, ...]:
    configurations = gap_fixed_hold_configurations(historical_family)
    settings = _settings_for_configurations(configurations)
    feature = ComponentSpec(
        display_name=(
            "causal completed-bar gap event"
            if settings.feature_mode == "gap_event"
            else "causal completed-bar post-gap path"
        ),
        protocol=(
            "feature.causal_gap_event.replay.v1"
            if settings.feature_mode == "gap_event"
            else "feature.causal_post_gap_path.replay.v1"
        ),
        implementation=_local("compute_gap_fixed_hold_score"),
        spec={
            "availability": "first_completed_bar_after_gap",
            "minimum_gap_minutes": GAP_FIXED_HOLD_MINIMUM_GAP_MINUTES,
            "non_evaluated_anchor_profile": (
                GAP_FIXED_HOLD_COMPARISON_ANCHOR_PROFILE
            ),
            "parameter_fields": ["minimum_gap_minutes", "profile"],
            "profiles": list(settings.profiles),
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
        display_name="registered causal gap outcome hypothesis",
        protocol="model.deterministic_gap_hypothesis.replay.v1",
        implementation=_local("compute_gap_fixed_hold_score"),
        spec={
            "fit": "none",
            "label_role": "scientific_outcome_never_runtime_input",
            "score_role": "causal_completed_bar_gap_state",
        },
        semantic_dependencies=(feature.identity, label.identity),
    )
    selector = ComponentSpec(
        display_name="fold-isolated gap selector",
        protocol="selector.fold_train_abs_quantile.replay.v1",
        implementation=_local("calibrate_gap_fixed_hold_selector"),
        spec={
            "calibration_role": "train_is_only",
            "minimum_train_observations": settings.minimum_train_observations,
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
        display_name="completed-period gap-segment spread-proxy execution",
        protocol="execution.fpmarkets_completed_period_spread_proxy.v2",
        implementation=_local("causal_gap_fixed_hold_spread"),
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
        display_name="Writer-bound gap family member",
        protocol="synthesis.historical_fixed_hold_member.v2",
        implementation=_local("gap_fixed_hold_executable"),
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
        display_name="exact concurrent gap-family inference",
        protocol="portfolio.concurrent_fixed_hold_family_inference.v2",
        implementation=_local("gap_fixed_hold_protocol_definition"),
        spec={
            "historical_context_adjustment_authority": (
                "context_only_never_adjustment_factor"
            ),
            "parameter_fields": [
                "alpha_ppm",
                "base_seed",
                "block_lengths",
                "bootstrap_samples",
                GAP_FIXED_HOLD_CONTEXT_PARAMETER,
                GAP_FIXED_HOLD_ORIGINAL_END_PARAMETER,
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
        raise ValueError("gap historical exposure context is invalid")
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
        "alpha_ppm": GAP_FIXED_HOLD_ALPHA_PPM,
        "base_seed": SELECTION_SEED,
        "block_lengths": list(SELECTION_BLOCK_LENGTHS),
        "bootstrap_samples": SELECTION_BOOTSTRAP_SAMPLES,
        GAP_FIXED_HOLD_CONTEXT_PARAMETER: prior,
        GAP_FIXED_HOLD_ORIGINAL_END_PARAMETER: original_end,
        "monte_carlo_confidence_ppm": SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
    }


def _engine_contract() -> str:
    return (
        "engine:gap_fixed_hold_v1:"
        f"python{'.'.join(str(value) for value in sys.version_info[:3])}:"
        f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
        f"adapter_{gap_fixed_hold_implementation_sha256()}:"
        f"trace_engine_{fixed_hold_trace_engine_implementation_sha256()}:"
        f"loader_{gap_fixed_hold_loader_sha256()}:"
        f"shared_{discovery_implementation_sha256()}:"
        f"selection_{selection_inference_implementation_sha256()}"
    )


def gap_fixed_hold_executable(
    configuration: GapFixedHoldConfiguration,
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ExecutableSpec:
    if configuration not in gap_fixed_hold_configurations(historical_family):
        raise ValueError("configuration is outside the Writer-bound gap family")
    return ExecutableSpec(
        display_name=(
            f"{historical_family.original_study_id} prospective gap "
            f"{configuration.configuration_id}"
        ),
        components=gap_fixed_hold_components(historical_family),
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
        clock_contract=GAP_FIXED_HOLD_CLOCK_CONTRACT,
        cost_contract=GAP_FIXED_HOLD_COST_CONTRACT,
        engine_contract=_engine_contract(),
    )


def gap_fixed_hold_baseline_executable(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ExecutableSpec:
    settings = _settings_for_configurations(
        gap_fixed_hold_configurations(historical_family)
    )
    return ExecutableSpec(
        display_name=(
            f"{historical_family.original_study_id} prospective gap "
            "non-evaluated comparison anchor"
        ),
        components=gap_fixed_hold_components(historical_family),
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
            "minimum_gap_minutes": GAP_FIXED_HOLD_MINIMUM_GAP_MINUTES,
            "profile": GAP_FIXED_HOLD_COMPARISON_ANCHOR_PROFILE,
            "selector_quantile_bp": GAP_FIXED_HOLD_SELECTOR_QUANTILE_BP,
            "signal_sign": 0,
            "unknown_entry_action": "cancel_before_open",
        },
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:"
            "rolling_windows_9_observed_development"
        ),
        clock_contract=GAP_FIXED_HOLD_CLOCK_CONTRACT,
        cost_contract=GAP_FIXED_HOLD_COST_CONTRACT,
        engine_contract=_engine_contract(),
    )


def gap_fixed_hold_controlled_chassis(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ControlledStudyChassis:
    baseline = gap_fixed_hold_baseline_executable(
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
    for configuration in gap_fixed_hold_configurations(historical_family):
        validate_controlled_executable(
            payload,
            gap_fixed_hold_executable(
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


def gap_fixed_hold_executable_map(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> dict[str, GapFixedHoldConfiguration]:
    return {
        gap_fixed_hold_executable(
            configuration,
            historical_family=historical_family,
            historical_context_prior_global_exposure_count=(
                historical_context_prior_global_exposure_count
            ),
            original_family_end_global_exposure_count=(
                original_family_end_global_exposure_count
            ),
        ).identity: configuration
        for configuration in gap_fixed_hold_configurations(historical_family)
    }


def gap_fixed_hold_protocol_definition(
    context: HistoricalFamilyReplayContext,
) -> FixedHoldProtocolDefinition:
    if not isinstance(context, HistoricalFamilyReplayContext):
        raise TypeError("gap replay context is not typed")
    family = context.family
    configurations = gap_fixed_hold_configurations(family)
    settings = _settings_for_configurations(configurations)
    prior, original_end = _validated_exposure_context(
        historical_family=family,
        prior_global_exposure_count=context.prior_global_exposure_count,
        original_family_end_global_exposure_count=(
            context.original_family_end_global_exposure_count
        ),
    )
    executables = tuple(
        gap_fixed_hold_executable(
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
        raise RuntimeError("gap execution contracts drifted")
    return FixedHoldProtocolDefinition(
        family=family,
        prospective_executable_ids=tuple(
            executable.identity for executable in executables
        ),
        protocol_id=GAP_REPLAY_TRACE_PROTOCOL_ID,
        fold_ids=EXPECTED_FOLD_IDS,
        invariance_keys=tuple(sorted(settings.profiles)),
        allowed_regimes=("high", "low", "middle"),
        dataset_sha256=DATASET_SHA256,
        material_identity=OBSERVED_MATERIAL_ID,
        split_artifact_sha256=ROLLING_SPLIT_SHA256,
        clock_contract=next(iter(clocks)),
        cost_contract=next(iter(costs)),
        producer_implementation_identities=tuple(
            sorted(gap_fixed_hold_producer_implementation_identities().items())
        ),
        historical_context_id=context.family_authority_id,
        historical_prior_global_exposure_count=prior,
        original_family_end_global_exposure_count=original_end,
        alpha_ppm=GAP_FIXED_HOLD_ALPHA_PPM,
        bootstrap_samples=SELECTION_BOOTSTRAP_SAMPLES,
        block_lengths=SELECTION_BLOCK_LENGTHS,
        monte_carlo_confidence_ppm=SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
        base_seed=SELECTION_SEED,
    )


def compute_gap_fixed_hold_score(
    frame: pd.DataFrame,
    profile: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    _settings_for_profile(profile)
    time_ns = _time_ns(frame)
    delta_minutes = np.full(len(frame), np.nan)
    delta_minutes[1:] = np.diff(time_ns) / 60_000_000_000
    event = delta_minutes >= GAP_FIXED_HOLD_MINIMUM_GAP_MINUTES
    opening_price = frame["open"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    if (
        np.any(~np.isfinite(opening_price))
        or np.any(~np.isfinite(close))
        or np.any(opening_price <= 0)
        or np.any(close <= 0)
    ):
        raise ValueError("gap fixed-hold price input is invalid")
    previous_close = np.roll(close, 1)
    opening_gap = opening_price - previous_close
    raw = np.full(len(frame), np.nan)
    if profile == "open_gap_30m":
        raw[event] = opening_gap[event]
    elif profile == "first_bar_response_30m":
        raw[event] = close[event] - opening_price[event]
    elif profile == "residual_gap_after_first_bar":
        raw[event] = close[event] - previous_close[event]
    else:
        event_count = int(event.sum())
        raw[event] = np.divide(
            np.sign(opening_gap[event])
            * (close[event] - opening_price[event]),
            np.abs(opening_gap[event]),
            out=np.full(event_count, np.nan),
            where=np.abs(opening_gap[event]) > 0,
        )
    returns = np.full(len(close), np.nan)
    returns[1:] = np.diff(np.log(close))
    volatility = (
        pd.Series(returns)
        .rolling(96, min_periods=96)
        .std(ddof=1)
        .to_numpy(float)
    )
    score = (
        raw
        if profile == "gap_fill_fraction_after_first_bar"
        else np.divide(
            raw,
            close * volatility,
            out=np.full(len(close), np.nan),
            where=np.isfinite(volatility) & (volatility > 0),
        )
    )
    return score, volatility, _consecutive_run(time_ns)


def causal_gap_fixed_hold_spread(
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
        raise ValueError("gap fixed-hold spread is invalid")
    segment = np.zeros(len(times), np.int64)
    if len(times) > 1:
        segment[1:] = np.cumsum(np.diff(times) != 300_000_000_000)
    positive = pd.Series(np.where(values > 0, values, np.nan))
    groups = pd.Series(segment)
    lagged = positive.groupby(groups, sort=False).transform(
        lambda part: part.shift(1).rolling(288, min_periods=1).median()
    )
    return np.where(values > 0, values, lagged.to_numpy(float))


def calibrate_gap_fixed_hold_selector(
    score: np.ndarray,
    mask: np.ndarray,
) -> float:
    return _calibrate_gap_selector(
        score,
        mask,
        settings=_GAP_FAMILY_SETTINGS[0],
    )


def _calibrate_gap_selector(
    score: np.ndarray,
    mask: np.ndarray,
    *,
    settings: _GapFamilySettings,
) -> float:
    values = np.abs(score[mask & np.isfinite(score)])
    if len(values) < settings.minimum_train_observations:
        raise DiscoveryBoundaryError("gap selector event set is too small")
    return float(
        np.quantile(
            values,
            GAP_FIXED_HOLD_SELECTOR_QUANTILE_BP / 10_000,
            method="higher",
        )
    )


def compute_gap_fixed_hold_family_trace(
    repository_root: str | Path,
    definition: FixedHoldProtocolDefinition,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    if (
        not isinstance(definition, FixedHoldProtocolDefinition)
        or not isinstance(definition.family, HistoricalFamilySpec)
    ):
        raise TypeError("gap definition is not Writer-bound")
    configurations = gap_fixed_hold_configurations(definition.family)
    settings = _settings_for_configurations(configurations)

    def calibrate(score: np.ndarray, mask: np.ndarray) -> float:
        return _calibrate_gap_selector(score, mask, settings=settings)

    return compute_fixed_hold_family_trace(
        repository_root,
        definition=definition,
        configurations=configurations,
        feature_builder=compute_gap_fixed_hold_score,
        selector_calibrator=calibrate,
        spread_builder=causal_gap_fixed_hold_spread,
    )


__all__ = [
    "GAP_EVENT_FIXED_HOLD_PROFILES",
    "GAP_FIXED_HOLD_CONTEXT_PARAMETER",
    "GAP_FIXED_HOLD_ORIGINAL_END_PARAMETER",
    "GAP_PATH_FIXED_HOLD_PROFILES",
    "GapFixedHoldConfiguration",
    "calibrate_gap_fixed_hold_selector",
    "causal_gap_fixed_hold_spread",
    "compute_gap_fixed_hold_family_trace",
    "compute_gap_fixed_hold_score",
    "gap_fixed_hold_baseline_executable",
    "gap_fixed_hold_components",
    "gap_fixed_hold_configurations",
    "gap_fixed_hold_controlled_chassis",
    "gap_fixed_hold_executable",
    "gap_fixed_hold_executable_map",
    "gap_fixed_hold_implementation_sha256",
    "gap_fixed_hold_loader_sha256",
    "gap_fixed_hold_producer_implementation_identities",
    "gap_fixed_hold_protocol_definition",
]
