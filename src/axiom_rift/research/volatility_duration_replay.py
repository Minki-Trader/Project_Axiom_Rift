"""Prospective exact-family replay adapter for historical STU-0051.

The adapter reconstructs the original four volatility-state-age members while
separating raw historical parity from prospective exact-family inference.  It
contains no Mission, Initiative, or successor Study identifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.canonical import parse_canonical
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
from axiom_rift.research.historical_family_replay import (
    P1_HISTORICAL_FAMILY_CATALOG_DIGEST,
    STU0051_HISTORICAL_FAMILY,
    HistoricalMemberSpec,
)
from axiom_rift.research.scientific_trace import (
    VOLATILITY_DURATION_REPLAY_TRACE_PROTOCOL_ID,
)
from axiom_rift.research.selection_inference import (
    selection_inference_implementation_sha256,
)
from axiom_rift.storage.evidence import EvidenceStore


VOLATILITY_DURATION_REPLAY_ALPHA_PPM = 100_000
VOLATILITY_DURATION_REPLAY_HOLDING_BARS = 24
VOLATILITY_DURATION_REPLAY_STATE_WINDOW = 1_152
VOLATILITY_DURATION_REPLAY_VOLATILITY_WINDOW = 96
VOLATILITY_DURATION_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT = 452
VOLATILITY_DURATION_REPLAY_HISTORICAL_CONTEXT_ID = (
    "historical-replay-obligation:"
    "a8da0fda7ff53c1951c59bf2bdc4fb8db722cf21c2090dd2e5220c5d2069a904"
)
VOLATILITY_DURATION_REPLAY_PROFILES = (
    "mature_state_age_24_47",
    "persistent_state_age_72_143",
)
VOLATILITY_DURATION_REPLAY_COMPARISON_ANCHOR_PROFILE = (
    "comparison_anchor_none"
)
VOLATILITY_DURATION_REPLAY_CLOCK_CONTRACT = (
    "clock:fpmarkets_m5_bar_open_completed_plus_5m_v2"
)
VOLATILITY_DURATION_REPLAY_COST_CONTRACT = (
    "cost:fpmarkets_completed_bar_spread_proxy_segment_positive_median_min_1_unknown_entry_cancel_"
    "half_spread_stress_v1"
)
_THIS_FILE = Path(__file__).resolve()

STU0051_HISTORICAL_EVALUATION_HASHES = {
    "mature_state_age_24_47-follow-h24": (
        "8e9a0c5d7f7bb06bc608cffed72885f8f71748ad1a82090ea3c44a8558483919"
    ),
    "mature_state_age_24_47-reverse-h24": (
        "1dd88cc0cde5899af80ad2d8c2648267152a50c7db8557c13cfe50927de90dc2"
    ),
    "persistent_state_age_72_143-follow-h24": (
        "b9da6c1e0704dd31aa2f741de869d1dc3077defa906ec6f821132984f00908bf"
    ),
    "persistent_state_age_72_143-reverse-h24": (
        "a678c8b917641567e72f217b47cdc3994d03e4ec79f2b15ff2688ae231d13840"
    ),
}

_LEGACY_INFERENCE_METRICS = frozenset(
    {
        "feature_control_worst_pvalue_upper_ppm",
        "opposite_sign_pvalue_upper_ppm",
        "selection_aware_pvalue_ppm",
    }
)


def volatility_duration_replay_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def volatility_duration_replay_loader_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


def volatility_duration_replay_producer_implementation_identities(
) -> dict[str, str]:
    return {
        "adapter_sha256": volatility_duration_replay_implementation_sha256(),
        "catalog_sha256": P1_HISTORICAL_FAMILY_CATALOG_DIGEST,
        "discovery_sha256": discovery_implementation_sha256(),
        "loader_sha256": volatility_duration_replay_loader_sha256(),
        "trace_engine_sha256": (
            fixed_hold_trace_engine_implementation_sha256()
        ),
    }


@dataclass(frozen=True, slots=True)
class VolatilityDurationReplayConfiguration:
    ordinal: int
    configuration_id: str
    historical_reference_executable_id: str
    profile: str
    signal_sign: int
    holding_bars: int = VOLATILITY_DURATION_REPLAY_HOLDING_BARS
    state_window: int = VOLATILITY_DURATION_REPLAY_STATE_WINDOW
    volatility_window: int = VOLATILITY_DURATION_REPLAY_VOLATILITY_WINDOW
    unknown_entry_action: str = "cancel_before_open"

    def __post_init__(self) -> None:
        if (
            type(self.ordinal) is not int
            or self.ordinal < 1
            or type(self.configuration_id) is not str
            or not self.configuration_id.isascii()
            or self.profile not in VOLATILITY_DURATION_REPLAY_PROFILES
            or self.signal_sign not in {-1, 1}
            or self.holding_bars != VOLATILITY_DURATION_REPLAY_HOLDING_BARS
            or self.state_window != VOLATILITY_DURATION_REPLAY_STATE_WINDOW
            or self.volatility_window
            != VOLATILITY_DURATION_REPLAY_VOLATILITY_WINDOW
            or self.unknown_entry_action != "cancel_before_open"
            or not self.historical_reference_executable_id.startswith(
                "executable:"
            )
        ):
            raise ValueError("volatility-duration replay configuration invalid")

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
) -> VolatilityDurationReplayConfiguration:
    parameters = member.parameter_values()
    return VolatilityDurationReplayConfiguration(
        ordinal=member.ordinal,
        configuration_id=member.configuration_id,
        historical_reference_executable_id=(
            member.historical_reference_executable_id
        ),
        profile=str(parameters["profile"]),
        signal_sign=int(parameters["signal_sign"]),
        holding_bars=int(parameters["holding_bars"]),
        state_window=int(parameters["state_window"]),
        unknown_entry_action=str(parameters["unknown_entry_action"]),
        volatility_window=int(parameters["volatility_window"]),
    )


def volatility_duration_replay_configurations(
) -> tuple[VolatilityDurationReplayConfiguration, ...]:
    values = tuple(
        _configuration_from_member(member)
        for member in STU0051_HISTORICAL_FAMILY.members
    )
    if tuple(value.ordinal for value in values) != (1, 2, 3, 4):
        raise RuntimeError("STU-0051 volatility-duration family order drifted")
    return values


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.volatility_duration_replay.{name}@sha256:"
        f"{volatility_duration_replay_implementation_sha256()}"
    )


def _shared(name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{name}@sha256:"
        f"{discovery_implementation_sha256()}"
    )


def volatility_duration_replay_components() -> tuple[ComponentSpec, ...]:
    feature = ComponentSpec(
        display_name="causal volatility state-age replay",
        protocol="feature.causal_volatility_state_age.replay.v1",
        implementation=_local("compute_volatility_duration_replay_score"),
        spec={
            "age_windows": {"mature": [24, 47], "persistent": [72, 143]},
            "availability": "completed_bar_close",
            "parameter_fields": [
                "profile",
                "state_window",
                "volatility_window",
            ],
            "profiles": list(VOLATILITY_DURATION_REPLAY_PROFILES),
            "state_reference": (
                "lagged_1152_bar_median_of_96_bar_volatility"
            ),
        },
    )
    label = ComponentSpec(
        display_name="realized fixed-hold after-cost replay label",
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
        display_name="registered volatility-duration outcome hypothesis",
        protocol="model.deterministic_volatility_duration.replay.v1",
        implementation=_local("compute_volatility_duration_replay_score"),
        spec={
            "fit": "none",
            "label_role": "scientific_outcome_never_runtime_input",
            "score_role": "causal_completed_bar_state",
        },
        semantic_dependencies=(feature.identity, label.identity),
    )
    selector = ComponentSpec(
        display_name="fold isolated event-presence replay selector",
        protocol="selector.fold_train_event_presence.replay.v1",
        implementation=_local("calibrate_volatility_duration_replay_selector"),
        spec={
            "calibration_role": "train_is_only",
            "minimum_train_events": 500,
            "threshold": 1,
        },
        semantic_dependencies=(model.identity,),
    )
    trade = ComponentSpec(
        display_name="completed-bar next-open directional replay entry",
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
        display_name="fixed-hold nonoverlap replay lifecycle",
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
        display_name="completed-period spread-proxy replay execution",
        protocol="execution.fpmarkets_completed_period_spread_proxy.v2",
        implementation=_local("causal_volatility_duration_replay_spread"),
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
        display_name="registered STU-0051 replay member",
        protocol="synthesis.historical_fixed_hold_member.v2",
        implementation=_local("volatility_duration_replay_executable"),
        spec={
            "catalog_digest": P1_HISTORICAL_FAMILY_CATALOG_DIGEST,
            "exact_member_count": 4,
            "historical_family_identity": STU0051_HISTORICAL_FAMILY.identity,
            "parameter_fields": [
                "configuration_id",
                "historical_reference_executable_id",
            ],
        },
        semantic_dependencies=(risk.identity,),
    )
    portfolio = ComponentSpec(
        display_name="exact concurrent STU-0051 replay inference",
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


def _shared_parameters(
    historical_context_prior_global_exposure_count: int,
) -> dict[str, object]:
    if (
        type(historical_context_prior_global_exposure_count) is not int
        or historical_context_prior_global_exposure_count
        < VOLATILITY_DURATION_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
    ):
        raise ValueError(
            "historical context cannot precede the original STU-0051 family"
        )
    return {
        "alpha_ppm": VOLATILITY_DURATION_REPLAY_ALPHA_PPM,
        "base_seed": SELECTION_SEED,
        "block_lengths": list(SELECTION_BLOCK_LENGTHS),
        "bootstrap_samples": SELECTION_BOOTSTRAP_SAMPLES,
        "historical_context_prior_global_exposure_count": (
            historical_context_prior_global_exposure_count
        ),
        "monte_carlo_confidence_ppm": SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
    }


def _engine_contract() -> str:
    return (
        "engine:stu0051_volatility_duration_replay_v1:"
        f"python{'.'.join(str(value) for value in sys.version_info[:3])}:"
        f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
        f"adapter_{volatility_duration_replay_implementation_sha256()}:"
        f"trace_engine_{fixed_hold_trace_engine_implementation_sha256()}:"
        f"loader_{volatility_duration_replay_loader_sha256()}:"
        f"shared_{discovery_implementation_sha256()}:"
        f"selection_{selection_inference_implementation_sha256()}:"
        f"catalog_{P1_HISTORICAL_FAMILY_CATALOG_DIGEST}"
    )


def volatility_duration_replay_executable(
    configuration: VolatilityDurationReplayConfiguration,
    *,
    historical_context_prior_global_exposure_count: int,
) -> ExecutableSpec:
    if configuration not in volatility_duration_replay_configurations():
        raise ValueError("configuration is outside the exact STU-0051 family")
    return ExecutableSpec(
        display_name=f"STU-0051 replay {configuration.configuration_id}",
        components=volatility_duration_replay_components(),
        parameters={
            **configuration.semantic_parameters(),
            **_shared_parameters(
                historical_context_prior_global_exposure_count
            ),
        },
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:"
            "rolling_windows_9_observed_development"
        ),
        clock_contract=VOLATILITY_DURATION_REPLAY_CLOCK_CONTRACT,
        cost_contract=VOLATILITY_DURATION_REPLAY_COST_CONTRACT,
        engine_contract=_engine_contract(),
    )


def volatility_duration_replay_baseline_executable(
    *,
    historical_context_prior_global_exposure_count: int,
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name="STU-0051 non-evaluated comparison anchor",
        components=volatility_duration_replay_components(),
        parameters={
            **_shared_parameters(
                historical_context_prior_global_exposure_count
            ),
            "configuration_id": "comparison-anchor",
            "historical_reference_executable_id": "none",
            "holding_bars": VOLATILITY_DURATION_REPLAY_HOLDING_BARS,
            "profile": VOLATILITY_DURATION_REPLAY_COMPARISON_ANCHOR_PROFILE,
            "signal_sign": 0,
            "state_window": VOLATILITY_DURATION_REPLAY_STATE_WINDOW,
            "unknown_entry_action": "cancel_before_open",
            "volatility_window": VOLATILITY_DURATION_REPLAY_VOLATILITY_WINDOW,
        },
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:"
            "rolling_windows_9_observed_development"
        ),
        clock_contract=VOLATILITY_DURATION_REPLAY_CLOCK_CONTRACT,
        cost_contract=VOLATILITY_DURATION_REPLAY_COST_CONTRACT,
        engine_contract=_engine_contract(),
    )


def volatility_duration_replay_controlled_chassis(
    *,
    historical_context_prior_global_exposure_count: int,
) -> ControlledStudyChassis:
    baseline = volatility_duration_replay_baseline_executable(
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        )
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
    for configuration in volatility_duration_replay_configurations():
        validate_controlled_executable(
            payload,
            volatility_duration_replay_executable(
                configuration,
                historical_context_prior_global_exposure_count=(
                    historical_context_prior_global_exposure_count
                ),
            ),
        )
    return chassis


def volatility_duration_replay_executable_map(
    *,
    historical_context_prior_global_exposure_count: int,
) -> dict[str, VolatilityDurationReplayConfiguration]:
    return {
        volatility_duration_replay_executable(
            configuration,
            historical_context_prior_global_exposure_count=(
                historical_context_prior_global_exposure_count
            ),
        ).identity: configuration
        for configuration in volatility_duration_replay_configurations()
    }


def volatility_duration_replay_protocol_definition(
    *,
    historical_context_prior_global_exposure_count: int,
) -> FixedHoldProtocolDefinition:
    configurations = volatility_duration_replay_configurations()
    return FixedHoldProtocolDefinition(
        family=STU0051_HISTORICAL_FAMILY,
        prospective_executable_ids=tuple(
            volatility_duration_replay_executable(
                configuration,
                historical_context_prior_global_exposure_count=(
                    historical_context_prior_global_exposure_count
                ),
            ).identity
            for configuration in configurations
        ),
        protocol_id=VOLATILITY_DURATION_REPLAY_TRACE_PROTOCOL_ID,
        fold_ids=EXPECTED_FOLD_IDS,
        invariance_keys=VOLATILITY_DURATION_REPLAY_PROFILES,
        allowed_regimes=("high", "low", "middle"),
        dataset_sha256=DATASET_SHA256,
        material_identity=OBSERVED_MATERIAL_ID,
        split_artifact_sha256=ROLLING_SPLIT_SHA256,
        clock_contract=VOLATILITY_DURATION_REPLAY_CLOCK_CONTRACT,
        cost_contract=VOLATILITY_DURATION_REPLAY_COST_CONTRACT,
        producer_implementation_identities=tuple(
            sorted(
                volatility_duration_replay_producer_implementation_identities().items()
            )
        ),
        historical_context_id=VOLATILITY_DURATION_REPLAY_HISTORICAL_CONTEXT_ID,
        historical_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=(
            VOLATILITY_DURATION_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        ),
        alpha_ppm=VOLATILITY_DURATION_REPLAY_ALPHA_PPM,
        bootstrap_samples=SELECTION_BOOTSTRAP_SAMPLES,
        block_lengths=SELECTION_BLOCK_LENGTHS,
        monte_carlo_confidence_ppm=SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
        base_seed=SELECTION_SEED,
    )


def compute_volatility_duration_replay_score(
    frame: pd.DataFrame,
    profile: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if profile not in VOLATILITY_DURATION_REPLAY_PROFILES:
        raise ValueError("volatility-duration replay profile is invalid")
    close = frame["close"].to_numpy(float)
    if np.any(~np.isfinite(close)) or np.any(close <= 0):
        raise ValueError("volatility-duration replay close is invalid")
    returns = np.full(len(close), np.nan)
    returns[1:] = np.diff(np.log(close))
    volatility = (
        pd.Series(returns)
        .rolling(
            VOLATILITY_DURATION_REPLAY_VOLATILITY_WINDOW,
            min_periods=VOLATILITY_DURATION_REPLAY_VOLATILITY_WINDOW,
        )
        .std(ddof=1)
        .to_numpy(float)
    )
    reference = (
        pd.Series(volatility)
        .shift(1)
        .rolling(
            VOLATILITY_DURATION_REPLAY_STATE_WINDOW,
            min_periods=VOLATILITY_DURATION_REPLAY_STATE_WINDOW,
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


def causal_volatility_duration_replay_spread(
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
        raise ValueError("volatility-duration replay spread is invalid")
    segment = np.zeros(len(times), np.int64)
    if len(times) > 1:
        segment[1:] = np.cumsum(np.diff(times) != 300_000_000_000)
    positive = pd.Series(np.where(values > 0, values, np.nan))
    groups = pd.Series(segment)
    lagged = positive.groupby(groups, sort=False).transform(
        lambda part: part.shift(1).rolling(288, min_periods=1).median()
    )
    return np.where(values > 0, values, lagged.to_numpy(float))


def calibrate_volatility_duration_replay_selector(
    score: np.ndarray,
    mask: np.ndarray,
) -> float:
    values = np.abs(score[mask & np.isfinite(score)])
    if len(values) < 500:
        raise DiscoveryBoundaryError(
            "volatility-duration replay event set is too small"
        )
    return 1.0


def _load_historical_evaluations(
    repository_root: Path,
) -> dict[str, dict[str, Any]]:
    store = EvidenceStore(repository_root / "local" / "evidence")
    evaluations: dict[str, dict[str, Any]] = {}
    for configuration_id, identity in (
        STU0051_HISTORICAL_EVALUATION_HASHES.items()
    ):
        value = parse_canonical(store.read_verified(identity))
        if (
            not isinstance(value, dict)
            or value.get("schema") != "volatility_duration_evaluation.v2"
            or value.get("subject_configuration_id") != configuration_id
        ):
            raise RuntimeError("historical STU-0051 evaluation binding drifted")
        evaluations[configuration_id] = value
    return evaluations


def assert_volatility_duration_historical_raw_parity(
    repository_root: Path,
    results: Mapping[str, Any],
) -> None:
    historical = _load_historical_evaluations(repository_root)
    configurations = volatility_duration_replay_configurations()
    by_reference = {
        configuration.historical_reference_executable_id: results[
            configuration.configuration_id
        ]
        for configuration in configurations
    }
    for configuration in configurations:
        result = results[configuration.configuration_id]
        control = STU0051_HISTORICAL_FAMILY.control_for_historical_executable(
            configuration.historical_reference_executable_id
        )
        opposite = by_reference[control.opposite_historical_executable_id]
        features = tuple(
            by_reference[value]
            for value in control.feature_historical_executable_ids
        )
        observed_metrics = {
            **{
                name: value
                for name, value in result.metrics.items()
                if name not in _LEGACY_INFERENCE_METRICS
            },
            "feature_control_worst_delta_net_profit_micropoints": min(
                result.metrics["net_profit_micropoints"]
                - value.metrics["net_profit_micropoints"]
                for value in features
            ),
            "opposite_sign_worst_delta_net_profit_micropoints": (
                result.metrics["net_profit_micropoints"]
                - opposite.metrics["net_profit_micropoints"]
            ),
        }
        expected = historical[configuration.configuration_id]
        expected_metrics = {
            name: value
            for name, value in expected["metrics"].items()
            if name not in _LEGACY_INFERENCE_METRICS
        }
        surfaces = {
            "metrics": (observed_metrics, expected_metrics),
            "fold_metrics": (result.fold_metrics, expected["fold_metrics"]),
            "regime_metrics": (
                result.regime_metrics,
                expected["regime_metrics"],
            ),
            "session_metrics": (
                result.session_metrics,
                expected["session_metrics"],
            ),
            "direction_metrics": (
                result.direction_metrics,
                expected["direction_metrics"],
            ),
        }
        mismatches = {
            name: {"expected": expected_value, "observed": observed_value}
            for name, (observed_value, expected_value) in surfaces.items()
            if observed_value != expected_value
        }
        if mismatches:
            raise RuntimeError(
                "prospective STU-0051 raw results differ from historical "
                f"evidence for {configuration.configuration_id}: {mismatches}"
            )


def compute_stu0051_volatility_duration_family_trace(
    repository_root: str | Path,
    *,
    historical_context_prior_global_exposure_count: int,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    definition = volatility_duration_replay_protocol_definition(
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        )
    )
    return compute_fixed_hold_family_trace(
        repository_root,
        definition=definition,
        configurations=volatility_duration_replay_configurations(),
        feature_builder=compute_volatility_duration_replay_score,
        selector_calibrator=calibrate_volatility_duration_replay_selector,
        spread_builder=causal_volatility_duration_replay_spread,
        raw_parity_validator=assert_volatility_duration_historical_raw_parity,
    )


__all__ = [
    "STU0051_HISTORICAL_EVALUATION_HASHES",
    "VOLATILITY_DURATION_REPLAY_HISTORICAL_CONTEXT_ID",
    "VOLATILITY_DURATION_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT",
    "VOLATILITY_DURATION_REPLAY_PROFILES",
    "VolatilityDurationReplayConfiguration",
    "assert_volatility_duration_historical_raw_parity",
    "calibrate_volatility_duration_replay_selector",
    "causal_volatility_duration_replay_spread",
    "compute_stu0051_volatility_duration_family_trace",
    "compute_volatility_duration_replay_score",
    "volatility_duration_replay_configurations",
    "volatility_duration_replay_controlled_chassis",
    "volatility_duration_replay_executable",
    "volatility_duration_replay_executable_map",
    "volatility_duration_replay_implementation_sha256",
    "volatility_duration_replay_loader_sha256",
    "volatility_duration_replay_producer_implementation_identities",
    "volatility_duration_replay_protocol_definition",
]
