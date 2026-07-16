"""Prospective fixed-hold implementation for a Writer-bound volatility family.

Historical modules reconstruct old authority only.  This module receives the
exact family and exposure context as typed data, constructs new Executables,
and computes current completed-period evidence without reading historical raw
evidence or requiring equality with an old evaluation artifact.
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
from axiom_rift.research.scientific_trace import (
    VOLATILITY_DURATION_REPLAY_TRACE_PROTOCOL_ID,
)
from axiom_rift.research.selection_inference import (
    selection_inference_implementation_sha256,
)


VOLATILITY_DURATION_FIXED_HOLD_ALPHA_PPM = 100_000
VOLATILITY_DURATION_FIXED_HOLD_HOLDING_BARS = 24
VOLATILITY_DURATION_FIXED_HOLD_STATE_WINDOW = 1_152
VOLATILITY_DURATION_FIXED_HOLD_VOLATILITY_WINDOW = 96
VOLATILITY_DURATION_FIXED_HOLD_CONTEXT_PARAMETER = (
    "historical_context_prior_global_exposure_count"
)
VOLATILITY_DURATION_FIXED_HOLD_ORIGINAL_END_PARAMETER = (
    "original_family_end_global_exposure_count"
)
VOLATILITY_DURATION_FIXED_HOLD_PROFILES = (
    "mature_state_age_24_47",
    "persistent_state_age_72_143",
)
VOLATILITY_DURATION_FIXED_HOLD_COMPARISON_ANCHOR_PROFILE = (
    "comparison_anchor_none"
)
VOLATILITY_DURATION_FIXED_HOLD_CLOCK_CONTRACT = (
    "clock:fpmarkets_m5_bar_open_completed_plus_5m_v2"
)
VOLATILITY_DURATION_FIXED_HOLD_COST_CONTRACT = (
    "cost:fpmarkets_completed_bar_spread_proxy_segment_positive_median_min_1_"
    "unknown_entry_cancel_half_spread_stress_v1"
)
_THIS_FILE = Path(__file__).resolve()


def volatility_duration_fixed_hold_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def volatility_duration_fixed_hold_loader_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


def volatility_duration_fixed_hold_producer_implementation_identities(
) -> dict[str, str]:
    return {
        "adapter_sha256": (
            volatility_duration_fixed_hold_implementation_sha256()
        ),
        "discovery_sha256": discovery_implementation_sha256(),
        "loader_sha256": volatility_duration_fixed_hold_loader_sha256(),
        "selection_sha256": selection_inference_implementation_sha256(),
        "trace_engine_sha256": (
            fixed_hold_trace_engine_implementation_sha256()
        ),
        "trace_schema_sha256": fixed_hold_trace_implementation_sha256(),
    }


@dataclass(frozen=True, slots=True)
class VolatilityDurationFixedHoldConfiguration:
    ordinal: int
    configuration_id: str
    historical_reference_executable_id: str
    profile: str
    signal_sign: int
    holding_bars: int = VOLATILITY_DURATION_FIXED_HOLD_HOLDING_BARS
    state_window: int = VOLATILITY_DURATION_FIXED_HOLD_STATE_WINDOW
    volatility_window: int = VOLATILITY_DURATION_FIXED_HOLD_VOLATILITY_WINDOW
    unknown_entry_action: str = "cancel_before_open"

    def __post_init__(self) -> None:
        if (
            type(self.ordinal) is not int
            or self.ordinal < 1
            or type(self.configuration_id) is not str
            or not self.configuration_id
            or not self.configuration_id.isascii()
            or self.profile not in VOLATILITY_DURATION_FIXED_HOLD_PROFILES
            or type(self.signal_sign) is not int
            or self.signal_sign not in {-1, 1}
            or type(self.holding_bars) is not int
            or self.holding_bars
            != VOLATILITY_DURATION_FIXED_HOLD_HOLDING_BARS
            or type(self.state_window) is not int
            or self.state_window != VOLATILITY_DURATION_FIXED_HOLD_STATE_WINDOW
            or type(self.volatility_window) is not int
            or self.volatility_window
            != VOLATILITY_DURATION_FIXED_HOLD_VOLATILITY_WINDOW
            or type(self.unknown_entry_action) is not str
            or self.unknown_entry_action != "cancel_before_open"
            or type(self.historical_reference_executable_id) is not str
            or not self.historical_reference_executable_id.startswith(
                "executable:"
            )
        ):
            raise ValueError("volatility-duration fixed-hold member is invalid")

    def semantic_parameters(self) -> dict[str, object]:
        return {
            "configuration_id": self.configuration_id,
            "historical_reference_executable_id": (
                self.historical_reference_executable_id
            ),
            "holding_bars": self.holding_bars,
            "profile": self.profile,
            "signal_sign": self.signal_sign,
            "state_window": self.state_window,
            "unknown_entry_action": self.unknown_entry_action,
            "volatility_window": self.volatility_window,
        }


def _configuration_from_member(
    member: HistoricalMemberSpec,
) -> VolatilityDurationFixedHoldConfiguration:
    parameters = member.parameter_values()
    expected = {
        "holding_bars",
        "profile",
        "signal_sign",
        "state_window",
        "unknown_entry_action",
        "volatility_window",
    }
    if set(parameters) != expected:
        raise ValueError(
            "volatility-duration historical parameter surface is invalid"
        )
    if (
        type(parameters["profile"]) is not str
        or type(parameters["signal_sign"]) is not int
        or type(parameters["holding_bars"]) is not int
        or type(parameters["state_window"]) is not int
        or type(parameters["unknown_entry_action"]) is not str
        or type(parameters["volatility_window"]) is not int
    ):
        raise ValueError(
            "volatility-duration historical parameter types are invalid"
        )
    return VolatilityDurationFixedHoldConfiguration(
        ordinal=member.ordinal,
        configuration_id=member.configuration_id,
        historical_reference_executable_id=(
            member.historical_reference_executable_id
        ),
        profile=parameters["profile"],
        signal_sign=parameters["signal_sign"],
        holding_bars=parameters["holding_bars"],
        state_window=parameters["state_window"],
        unknown_entry_action=parameters["unknown_entry_action"],
        volatility_window=parameters["volatility_window"],
    )


def volatility_duration_fixed_hold_configurations(
    historical_family: HistoricalFamilySpec,
) -> tuple[VolatilityDurationFixedHoldConfiguration, ...]:
    if not isinstance(historical_family, HistoricalFamilySpec):
        raise TypeError("volatility-duration family is not Writer-bound")
    values = tuple(
        _configuration_from_member(member)
        for member in historical_family.members
    )
    profile_signs = {(value.profile, value.signal_sign) for value in values}
    expected_profile_signs = {
        (profile, signal_sign)
        for profile in VOLATILITY_DURATION_FIXED_HOLD_PROFILES
        for signal_sign in (-1, 1)
    }
    if (
        historical_family.family_size != 4
        or tuple(value.ordinal for value in values) != (1, 2, 3, 4)
        or profile_signs != expected_profile_signs
    ):
        raise ValueError(
            "volatility-duration Writer-bound family is not the exact axis"
        )
    return values


def _local(name: str) -> str:
    return (
        "axiom_rift.research.volatility_duration_fixed_hold."
        f"{name}@sha256:"
        f"{volatility_duration_fixed_hold_implementation_sha256()}"
    )


def _shared(name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{name}@sha256:"
        f"{discovery_implementation_sha256()}"
    )


def volatility_duration_fixed_hold_components(
    historical_family: HistoricalFamilySpec,
) -> tuple[ComponentSpec, ...]:
    volatility_duration_fixed_hold_configurations(historical_family)
    feature = ComponentSpec(
        display_name="causal volatility state-age fixed-hold feature",
        protocol="feature.causal_volatility_state_age.fixed_hold.v1",
        implementation=_local("compute_volatility_duration_fixed_hold_score"),
        spec={
            "age_windows": {"mature": [24, 47], "persistent": [72, 143]},
            "availability": "completed_bar_close",
            "parameter_fields": ["profile", "state_window", "volatility_window"],
            "profiles": list(VOLATILITY_DURATION_FIXED_HOLD_PROFILES),
            "state_reference": (
                "lagged_1152_bar_median_of_96_bar_volatility"
            ),
        },
    )
    label = ComponentSpec(
        display_name="realized fixed-hold after-cost label",
        protocol="label.realized_fixed_hold_native_net_pnl.v2",
        implementation=_shared("_evaluate_configuration"),
        spec={
            "availability": "exit_bar_open_after_registered_holding_interval",
            "cost_basis": "native_entry_and_exit_execution_cost",
            "parameter_fields": ["holding_bars"],
            "target": "native_net_pnl_micropoints",
        },
    )
    model = ComponentSpec(
        display_name="registered volatility-duration outcome hypothesis",
        protocol="model.deterministic_volatility_duration.fixed_hold.v1",
        implementation=_local("compute_volatility_duration_fixed_hold_score"),
        spec={
            "fit": "none",
            "label_role": "scientific_outcome_never_runtime_input",
            "score_role": "causal_completed_bar_state",
        },
        semantic_dependencies=(feature.identity, label.identity),
    )
    selector = ComponentSpec(
        display_name="fold-isolated event-presence selector",
        protocol="selector.fold_train_event_presence.fixed_hold.v1",
        implementation=(
            _local("calibrate_volatility_duration_fixed_hold_selector")
        ),
        spec={
            "calibration_role": "train_is_only",
            "minimum_train_events": 500,
            "threshold": 1,
        },
        semantic_dependencies=(model.identity,),
    )
    trade = ComponentSpec(
        display_name="completed-bar next-open directional entry",
        protocol="trade.completed_bar_next_open_direction.fixed_hold.v3",
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
        protocol="lifecycle.fixed_hold_no_overlap.v3",
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
        implementation=_local("causal_volatility_duration_fixed_hold_spread"),
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
        display_name="Writer-bound volatility-duration family member",
        protocol="synthesis.writer_bound_fixed_hold_member.v3",
        implementation=_local("volatility_duration_fixed_hold_executable"),
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
        display_name="exact concurrent volatility-duration inference",
        protocol="portfolio.concurrent_fixed_hold_family_inference.v3",
        implementation=_local(
            "volatility_duration_fixed_hold_protocol_definition"
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
                VOLATILITY_DURATION_FIXED_HOLD_CONTEXT_PARAMETER,
                VOLATILITY_DURATION_FIXED_HOLD_ORIGINAL_END_PARAMETER,
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
        raise ValueError(
            "volatility-duration historical exposure context is invalid"
        )
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
        "alpha_ppm": VOLATILITY_DURATION_FIXED_HOLD_ALPHA_PPM,
        "base_seed": SELECTION_SEED,
        "block_lengths": list(SELECTION_BLOCK_LENGTHS),
        "bootstrap_samples": SELECTION_BOOTSTRAP_SAMPLES,
        VOLATILITY_DURATION_FIXED_HOLD_CONTEXT_PARAMETER: prior,
        VOLATILITY_DURATION_FIXED_HOLD_ORIGINAL_END_PARAMETER: original_end,
        "monte_carlo_confidence_ppm": (
            SELECTION_MONTE_CARLO_CONFIDENCE_PPM
        ),
    }


def _engine_contract() -> str:
    return (
        "engine:volatility_duration_fixed_hold_v1:"
        f"python{'.'.join(str(value) for value in sys.version_info[:3])}:"
        f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
        f"adapter_{volatility_duration_fixed_hold_implementation_sha256()}:"
        f"trace_engine_{fixed_hold_trace_engine_implementation_sha256()}:"
        f"loader_{volatility_duration_fixed_hold_loader_sha256()}:"
        f"shared_{discovery_implementation_sha256()}:"
        f"selection_{selection_inference_implementation_sha256()}"
    )


def volatility_duration_fixed_hold_executable(
    configuration: VolatilityDurationFixedHoldConfiguration,
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ExecutableSpec:
    if configuration not in volatility_duration_fixed_hold_configurations(
        historical_family
    ):
        raise ValueError("configuration is outside the Writer-bound family")
    return ExecutableSpec(
        display_name=(
            f"{historical_family.original_study_id} prospective fixed-hold "
            f"{configuration.configuration_id}"
        ),
        components=volatility_duration_fixed_hold_components(
            historical_family
        ),
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
        clock_contract=VOLATILITY_DURATION_FIXED_HOLD_CLOCK_CONTRACT,
        cost_contract=VOLATILITY_DURATION_FIXED_HOLD_COST_CONTRACT,
        engine_contract=_engine_contract(),
    )


def volatility_duration_fixed_hold_baseline_executable(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=(
            f"{historical_family.original_study_id} prospective fixed-hold "
            "non-evaluated comparison anchor"
        ),
        components=volatility_duration_fixed_hold_components(
            historical_family
        ),
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
            "holding_bars": VOLATILITY_DURATION_FIXED_HOLD_HOLDING_BARS,
            "profile": (
                VOLATILITY_DURATION_FIXED_HOLD_COMPARISON_ANCHOR_PROFILE
            ),
            "signal_sign": 0,
            "state_window": VOLATILITY_DURATION_FIXED_HOLD_STATE_WINDOW,
            "unknown_entry_action": "cancel_before_open",
            "volatility_window": (
                VOLATILITY_DURATION_FIXED_HOLD_VOLATILITY_WINDOW
            ),
        },
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:"
            "rolling_windows_9_observed_development"
        ),
        clock_contract=VOLATILITY_DURATION_FIXED_HOLD_CLOCK_CONTRACT,
        cost_contract=VOLATILITY_DURATION_FIXED_HOLD_COST_CONTRACT,
        engine_contract=_engine_contract(),
    )


def volatility_duration_fixed_hold_controlled_chassis(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> ControlledStudyChassis:
    baseline = volatility_duration_fixed_hold_baseline_executable(
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
    for configuration in volatility_duration_fixed_hold_configurations(
        historical_family
    ):
        validate_controlled_executable(
            payload,
            volatility_duration_fixed_hold_executable(
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


def volatility_duration_fixed_hold_executable_map(
    *,
    historical_family: HistoricalFamilySpec,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
) -> dict[str, VolatilityDurationFixedHoldConfiguration]:
    return {
        volatility_duration_fixed_hold_executable(
            configuration,
            historical_family=historical_family,
            historical_context_prior_global_exposure_count=(
                historical_context_prior_global_exposure_count
            ),
            original_family_end_global_exposure_count=(
                original_family_end_global_exposure_count
            ),
        ).identity: configuration
        for configuration in volatility_duration_fixed_hold_configurations(
            historical_family
        )
    }


def volatility_duration_fixed_hold_protocol_definition(
    context: HistoricalFamilyReplayContext,
) -> FixedHoldProtocolDefinition:
    if not isinstance(context, HistoricalFamilyReplayContext):
        raise TypeError("volatility-duration replay context is not typed")
    family = context.family
    configurations = volatility_duration_fixed_hold_configurations(family)
    prior, original_end = _validated_exposure_context(
        historical_family=family,
        prior_global_exposure_count=context.prior_global_exposure_count,
        original_family_end_global_exposure_count=(
            context.original_family_end_global_exposure_count
        ),
    )
    executables = tuple(
        volatility_duration_fixed_hold_executable(
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
        raise RuntimeError("volatility-duration execution contracts drifted")
    return FixedHoldProtocolDefinition(
        family=family,
        prospective_executable_ids=tuple(
            executable.identity for executable in executables
        ),
        protocol_id=VOLATILITY_DURATION_REPLAY_TRACE_PROTOCOL_ID,
        fold_ids=EXPECTED_FOLD_IDS,
        invariance_keys=VOLATILITY_DURATION_FIXED_HOLD_PROFILES,
        allowed_regimes=("high", "low", "middle"),
        dataset_sha256=DATASET_SHA256,
        material_identity=OBSERVED_MATERIAL_ID,
        split_artifact_sha256=ROLLING_SPLIT_SHA256,
        clock_contract=next(iter(clocks)),
        cost_contract=next(iter(costs)),
        producer_implementation_identities=tuple(
            sorted(
                volatility_duration_fixed_hold_producer_implementation_identities().items()
            )
        ),
        historical_context_id=context.family_authority_id,
        historical_prior_global_exposure_count=prior,
        original_family_end_global_exposure_count=original_end,
        alpha_ppm=VOLATILITY_DURATION_FIXED_HOLD_ALPHA_PPM,
        bootstrap_samples=SELECTION_BOOTSTRAP_SAMPLES,
        block_lengths=SELECTION_BLOCK_LENGTHS,
        monte_carlo_confidence_ppm=(
            SELECTION_MONTE_CARLO_CONFIDENCE_PPM
        ),
        base_seed=SELECTION_SEED,
    )


def compute_volatility_duration_fixed_hold_score(
    frame: pd.DataFrame,
    profile: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if profile not in VOLATILITY_DURATION_FIXED_HOLD_PROFILES:
        raise ValueError("volatility-duration fixed-hold profile is invalid")
    close = frame["close"].to_numpy(float)
    if np.any(~np.isfinite(close)) or np.any(close <= 0):
        raise ValueError("volatility-duration close is invalid")
    returns = np.full(len(close), np.nan)
    returns[1:] = np.diff(np.log(close))
    volatility = (
        pd.Series(returns)
        .rolling(
            VOLATILITY_DURATION_FIXED_HOLD_VOLATILITY_WINDOW,
            min_periods=VOLATILITY_DURATION_FIXED_HOLD_VOLATILITY_WINDOW,
        )
        .std(ddof=1)
        .to_numpy(float)
    )
    reference = (
        pd.Series(volatility)
        .shift(1)
        .rolling(
            VOLATILITY_DURATION_FIXED_HOLD_STATE_WINDOW,
            min_periods=VOLATILITY_DURATION_FIXED_HOLD_STATE_WINDOW,
        )
        .median()
        .to_numpy(float)
    )
    level = (
        np.divide(
            volatility,
            reference,
            out=np.full(len(close), np.nan),
            where=np.isfinite(reference) & (reference > 0),
        )
        - 1
    )
    score = np.full(len(close), np.nan)
    previous_state = 0
    duration = 0
    bounds = (
        (24, 47)
        if profile == "mature_state_age_24_47"
        else (72, 143)
    )
    for index, value in enumerate(level):
        if not np.isfinite(value):
            previous_state = 0
            duration = 0
            continue
        state = 1 if value >= 0 else -1
        duration = duration + 1 if state == previous_state else 1
        previous_state = state
        if bounds[0] <= duration <= bounds[1]:
            score[index] = state
    return score, volatility, _consecutive_run(_time_ns(frame))


def causal_volatility_duration_fixed_hold_spread(
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
        raise ValueError("volatility-duration spread is invalid")
    segment = np.zeros(len(times), np.int64)
    if len(times) > 1:
        segment[1:] = np.cumsum(np.diff(times) != 300_000_000_000)
    positive = pd.Series(np.where(values > 0, values, np.nan))
    groups = pd.Series(segment)
    lagged = positive.groupby(groups, sort=False).transform(
        lambda part: part.shift(1).rolling(288, min_periods=1).median()
    )
    return np.where(values > 0, values, lagged.to_numpy(float))


def calibrate_volatility_duration_fixed_hold_selector(
    score: np.ndarray,
    mask: np.ndarray,
) -> float:
    values = np.abs(score[mask & np.isfinite(score)])
    if len(values) < 500:
        raise DiscoveryBoundaryError(
            "volatility-duration event set is too small"
        )
    return 1.0


def compute_volatility_duration_fixed_hold_family_trace(
    repository_root: str | Path,
    definition: FixedHoldProtocolDefinition,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    if (
        not isinstance(definition, FixedHoldProtocolDefinition)
        or not isinstance(definition.family, HistoricalFamilySpec)
    ):
        raise TypeError("volatility-duration definition is not Writer-bound")
    return compute_fixed_hold_family_trace(
        repository_root,
        definition=definition,
        configurations=volatility_duration_fixed_hold_configurations(
            definition.family
        ),
        feature_builder=compute_volatility_duration_fixed_hold_score,
        selector_calibrator=calibrate_volatility_duration_fixed_hold_selector,
        spread_builder=causal_volatility_duration_fixed_hold_spread,
    )


__all__ = [
    "VOLATILITY_DURATION_FIXED_HOLD_CONTEXT_PARAMETER",
    "VOLATILITY_DURATION_FIXED_HOLD_ORIGINAL_END_PARAMETER",
    "VOLATILITY_DURATION_FIXED_HOLD_PROFILES",
    "VolatilityDurationFixedHoldConfiguration",
    "calibrate_volatility_duration_fixed_hold_selector",
    "causal_volatility_duration_fixed_hold_spread",
    "compute_volatility_duration_fixed_hold_family_trace",
    "compute_volatility_duration_fixed_hold_score",
    "volatility_duration_fixed_hold_baseline_executable",
    "volatility_duration_fixed_hold_components",
    "volatility_duration_fixed_hold_configurations",
    "volatility_duration_fixed_hold_controlled_chassis",
    "volatility_duration_fixed_hold_executable",
    "volatility_duration_fixed_hold_executable_map",
    "volatility_duration_fixed_hold_implementation_sha256",
    "volatility_duration_fixed_hold_loader_sha256",
    "volatility_duration_fixed_hold_producer_implementation_identities",
    "volatility_duration_fixed_hold_protocol_definition",
]
