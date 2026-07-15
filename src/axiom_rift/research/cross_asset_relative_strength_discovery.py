"""Causal US500 relative-strength discovery on Foundation-safe US100 M5 data.

The external source is scientific input only after its durable eligibility
transition.  This module binds the exact SourceContract and immutable raw
snapshot into twelve discovery Executables.  It hashes every source byte but
copies only the observed-development prefix into parser memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import ceil, sqrt
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import scipy
from scipy.stats import beta

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec, canonical_digest
from axiom_rift.research import data as data_module
from axiom_rift.research import us500_source as us500_source_module
from axiom_rift.research.data import ObservedDevelopmentData, load_observed_development
from axiom_rift.research.external_observed_development import (
    ExternalObservedDevelopmentError,
    US500_OBSERVED_DEVELOPMENT_SPEC,
    external_observed_development_loader_implementation_sha256,
    load_external_observed_development,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    DiscoveryBoundaryError,
    _consecutive_run,
    _daily_series,
    _fold_payloads,
    _micropoints,
    _monthly_realized_exit_drawdown,
    _profit_factor,
    _time_ns,
    _validate_engine_environment,
    _validate_fold_payloads,
    _validate_production_data,
    causal_effective_spread,
    discovery_implementation_sha256,
    execution_pnl,
)
from axiom_rift.research.us500_source import (
    us500_source_contract,
)


SELECTOR_QUANTILE_BP = 9_750
SELECTION_BOOTSTRAP_SAMPLES = 41_999
SELECTION_BLOCK_LENGTHS = (5, 10, 20)
SELECTION_TOTAL_EXPOSURES = 234
SELECTION_SEED = 612_337_279
SELECTION_MONTE_CARLO_CONFIDENCE_PPM = 990_000
DEVELOPMENT_END = pd.Timestamp("2026-04-30 23:55:00")
_FIVE_MINUTES_NS = 300_000_000_000
_TIME_FORMAT = "%Y.%m.%d %H:%M:%S"
_PROFILES = (
    "relative_strength_12_joint",
    "us500_direction_12_source_only",
    "us100_direction_12_target_only",
)
_THIS_FILE = Path(__file__).resolve()


class CrossAssetRelativeStrengthBoundaryError(DiscoveryBoundaryError):
    """Raised before unregistered cross-asset semantics enter evaluation."""


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_digest(value: str, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CrossAssetRelativeStrengthBoundaryError(
            f"{name} must be a lowercase SHA256 digest"
        )
    return value


def cross_asset_relative_strength_implementation_sha256() -> str:
    return _file_sha256(_THIS_FILE)


def trend_dependency_sha256() -> str:
    return discovery_implementation_sha256()


def loader_implementation_sha256() -> str:
    return _file_sha256(Path(data_module.__file__).resolve())


def us500_source_implementation_sha256() -> str:
    return _file_sha256(Path(us500_source_module.__file__).resolve())


def us500_raw_sha256(repository_root: str | Path) -> str:
    """Return the immutable acquisition identity without opening raw bytes."""

    Path(repository_root).resolve()
    return US500_OBSERVED_DEVELOPMENT_SPEC.parent_raw_sha256


@dataclass(frozen=True, slots=True)
class US500DevelopmentMetadata:
    raw_sha256: str
    development_prefix_sha256: str
    prefix_byte_count: int
    development_row_count: int
    first_time: pd.Timestamp
    last_time: pd.Timestamp
    source_path: Path


@dataclass(frozen=True, slots=True)
class US500ObservedDevelopment:
    frame: pd.DataFrame
    metadata: US500DevelopmentMetadata


def load_us500_observed_development(
    repository_root: str | Path,
    *,
    expected_raw_sha256: str | None = None,
) -> US500ObservedDevelopment:
    """Load only the registered US500 development-prefix artifact."""

    expected = US500_OBSERVED_DEVELOPMENT_SPEC.parent_raw_sha256
    if expected_raw_sha256 is not None and _require_digest(
        expected_raw_sha256, "expected US500 raw hash"
    ) != expected:
        raise CrossAssetRelativeStrengthBoundaryError(
            "US500 acquisition identity differs"
        )
    try:
        loaded = load_external_observed_development(repository_root, "US500")
    except ExternalObservedDevelopmentError as exc:
        raise CrossAssetRelativeStrengthBoundaryError(
            "US500 observed-development prefix is invalid"
        ) from exc
    frame = loaded.frame
    metadata = loaded.metadata
    return US500ObservedDevelopment(
        frame=frame,
        metadata=US500DevelopmentMetadata(
            raw_sha256=metadata.parent_raw_sha256,
            development_prefix_sha256=metadata.development_prefix_sha256,
            prefix_byte_count=metadata.prefix_byte_count,
            development_row_count=len(frame),
            first_time=metadata.first_time,
            last_time=metadata.last_time,
            source_path=metadata.source_path,
        ),
    )


@dataclass(frozen=True, slots=True)
class CrossAssetRelativeStrengthConfiguration:
    profile: str
    route_sign: int
    holding_bars: int

    def __post_init__(self) -> None:
        if self.profile not in _PROFILES:
            raise ValueError("cross-asset profile is not registered")
        if self.route_sign not in {-1, 1}:
            raise ValueError("route_sign must be -1 or 1")
        if self.holding_bars not in {6, 24}:
            raise ValueError("holding_bars is not registered")

    @property
    def configuration_id(self) -> str:
        route = "inverted" if self.route_sign == -1 else "routed"
        return f"{self.profile}-{route}-h{self.holding_bars}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "holding_bars": self.holding_bars,
            "lookback_bars": 12,
            "route_sign": self.route_sign,
            "score_profile": self.profile,
            "selector_quantile_bp": SELECTOR_QUANTILE_BP,
            "volatility_window_bars": 48,
        }


def cross_asset_relative_strength_configurations() -> tuple[CrossAssetRelativeStrengthConfiguration, ...]:
    return tuple(
        CrossAssetRelativeStrengthConfiguration(profile, route_sign, holding_bars)
        for profile in _PROFILES
        for route_sign in (-1, 1)
        for holding_bars in (6, 24)
    )


def _source_identity_payload() -> dict[str, str]:
    contract = us500_source_contract()
    return {
        "availability_identity": contract.availability_identity,
        "clock_identity": contract.clock_identity,
        "field_identity": contract.field_identity,
        "mapping_identity": contract.mapping_identity,
        "schema_identity": contract.schema_identity,
        "source_contract_id": contract.source_contract_id,
    }


def _local_implementation(function_name: str) -> str:
    return (
        "axiom_rift.research.cross_asset_relative_strength_discovery."
        f"{function_name}@sha256:{cross_asset_relative_strength_implementation_sha256()}"
    )


def _dependency_implementation(function_name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{function_name}@sha256:"
        f"{trend_dependency_sha256()}"
    )


def cross_asset_relative_strength_components(raw_sha256: str) -> tuple[ComponentSpec, ...]:
    raw = _require_digest(raw_sha256, "US500 raw hash")
    source = _source_identity_payload()
    source_id = source["source_contract_id"]
    return (
        ComponentSpec(
            display_name="exact causal US500 and US100 relative strength",
            protocol="feature.cross_asset_relative_strength_12_sigma48.v1",
            implementation=_local_implementation("compute_relative_strength_features"),
            semantic_dependencies=(
                source_id,
                f"external-development-material:{US500_OBSERVED_DEVELOPMENT_SPEC.material_identity}",
            ),
            spec={
                "availability": "both_completed_bars_at_event_time_plus_5m",
                "development_end": str(DEVELOPMENT_END),
                "join": "exact_timestamp_inner_no_fill_no_asof_no_zero",
                "lookback_bars": 12,
                "nonconsecutive_action": "joint_run_reset_and_rewarm_49_bars",
                "profiles": list(_PROFILES),
                "raw_sha256": raw,
                "raw_sha256_role": "acquisition_identity_only",
                "development_prefix_sha256": (
                    US500_OBSERVED_DEVELOPMENT_SPEC.prefix_sha256
                ),
                "development_prefix_byte_count": (
                    US500_OBSERVED_DEVELOPMENT_SPEC.prefix_byte_count
                ),
                "development_prefix_row_count": (
                    US500_OBSERVED_DEVELOPMENT_SPEC.row_count
                ),
                "development_material_identity": (
                    US500_OBSERVED_DEVELOPMENT_SPEC.material_identity
                ),
                "development_source_key": "US500",
                "development_loader_implementation_sha256": (
                    external_observed_development_loader_implementation_sha256()
                ),
                "source_identities": source,
                "volatility": "sample_std_ddof1_last48_one_bar_log_returns",
            },
        ),
        ComponentSpec(
            display_name="fold isolated relative strength selector",
            protocol="selector.fold_train_abs_quantile.v3",
            implementation=_local_implementation("calibrate_selector"),
            spec={
                "calibration_role": "train_is_only",
                "minimum_train_observations": 1000,
                "quantile_basis_points": SELECTOR_QUANTILE_BP,
                "quantile_method": "higher",
            },
        ),
        ComponentSpec(
            display_name="completed-bar cross-asset route",
            protocol="trade.completed_bar_cross_asset_next_open.v1",
            implementation=_local_implementation("simulate_cross_asset_fixed_hold"),
            spec={
                "decision_time": "event_time_plus_5m",
                "direction": "route_sign_times_score_sign",
                "entry_time": "next_exact_US100_bar_open",
                "source_required_after_entry": False,
            },
        ),
        ComponentSpec(
            display_name="US100 timestamp-indexed fixed hold",
            protocol="lifecycle.us100_exact_timestamp_fixed_hold_no_overlap.v1",
            implementation=_local_implementation("simulate_cross_asset_fixed_hold"),
            spec={
                "entry_overlap": "reject_while_position_slot_is_occupied",
                "exit_index": "original_US100_entry_index_plus_holding_bars",
                "gap_action": "exclude_target_path",
                "joined_row_position_used_for_hold": False,
            },
        ),
        ComponentSpec(
            display_name="US100 native bid-bar spread execution",
            protocol="execution.fpmarkets_US100_bid_bar_spread.v2",
            implementation=_dependency_implementation("execution_pnl"),
            spec={
                "point": "0.01",
                "source_spread_used": False,
                "stress": "half_effective_US100_spread_each_side",
                "zero_spread": "lag1_positive_median_window288_min24_target_gap_reset",
            },
        ),
        ComponentSpec(
            display_name="fixed one-lot single-sleeve risk",
            protocol="risk.fixed_one_lot.v1",
            implementation=_local_implementation("simulate_cross_asset_fixed_hold"),
            spec={"dynamic_sizing": False, "lot": 1, "positions_per_sleeve": 1},
        ),
    )


def cross_asset_relative_strength_executable(
    configuration: CrossAssetRelativeStrengthConfiguration,
    raw_sha256: str,
) -> ExecutableSpec:
    if not isinstance(configuration, CrossAssetRelativeStrengthConfiguration):
        raise TypeError("configuration must be CrossAssetRelativeStrengthConfiguration")
    raw = _require_digest(raw_sha256, "US500 raw hash")
    source = _source_identity_payload()
    return ExecutableSpec(
        display_name=f"cross asset relative strength {configuration.configuration_id}",
        components=cross_asset_relative_strength_components(raw),
        parameters={
            **configuration.semantic_parameters(),
            "source_contract_identities": source,
            "source_development_material_identity": (
                US500_OBSERVED_DEVELOPMENT_SPEC.material_identity
            ),
            "source_development_prefix_sha256": (
                US500_OBSERVED_DEVELOPMENT_SPEC.prefix_sha256
            ),
            "source_raw_sha256": raw,
        },
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development"
        ),
        clock_contract=(
            "clock:US100_and_US500_completed_M5_event_time_plus_5m_"
            "exact_timestamp_no_offset_inference_v1"
        ),
        cost_contract=(
            "cost:US100_bid_bar_spread_point_0_01_zero_lag1_positive_median_"
            "window288_min24_target_gap_reset_half_spread_stress_v2"
        ),
        engine_contract=(
            "engine:cross_asset_relative_strength_discovery_v1:python3_13_9:"
            "numpy2_3_4:pandas2_3_3:scipy1_16_3:"
            f"implementation_{cross_asset_relative_strength_implementation_sha256()}:"
            f"trend_{trend_dependency_sha256()}:loader_{loader_implementation_sha256()}:"
            f"external_loader_{external_observed_development_loader_implementation_sha256()}:"
            f"source_module_{us500_source_implementation_sha256()}:raw_{raw}:"
            f"development_material_{US500_OBSERVED_DEVELOPMENT_SPEC.material_identity}:"
            f"development_prefix_{US500_OBSERVED_DEVELOPMENT_SPEC.prefix_sha256}:"
            f"source_{source['source_contract_id']}:mapping_{source['mapping_identity']}:"
            f"schema_{source['schema_identity']}:field_{source['field_identity']}:"
            f"clock_{source['clock_identity']}:availability_{source['availability_identity']}:"
            f"selector_{SELECTOR_QUANTILE_BP}_higher:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:"
            f"blocks_5_10_20:mc_upper_{SELECTION_MONTE_CARLO_CONFIDENCE_PPM}:"
            f"bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
        source_contracts=(source["source_contract_id"],),
    )


def _configuration_map_for_raw(raw_sha256: str) -> dict[str, CrossAssetRelativeStrengthConfiguration]:
    return {
        cross_asset_relative_strength_executable(configuration, raw_sha256).identity: configuration
        for configuration in cross_asset_relative_strength_configurations()
    }


def cross_asset_relative_strength_executable_configuration_map(
    repository_root: str | Path,
) -> dict[str, CrossAssetRelativeStrengthConfiguration]:
    return _configuration_map_for_raw(us500_raw_sha256(repository_root))


def executable_configuration_map(
    repository_root: str | Path,
) -> dict[str, CrossAssetRelativeStrengthConfiguration]:
    return cross_asset_relative_strength_executable_configuration_map(repository_root)


@dataclass(frozen=True, slots=True)
class RelativeStrengthFeatures:
    relative_strength_12_joint: np.ndarray
    us500_direction_12_source_only: np.ndarray
    us100_direction_12_target_only: np.ndarray
    us100_volatility: np.ndarray
    joint_run: np.ndarray

    def score(self, profile: str) -> np.ndarray:
        if profile not in _PROFILES:
            raise ValueError("cross-asset score profile is not registered")
        return np.asarray(getattr(self, profile), dtype=float)


def _join_exact(target_frame: pd.DataFrame, source_frame: pd.DataFrame) -> pd.DataFrame:
    required_target = {"time", "open", "high", "low", "close", "spread"}
    if not required_target.issubset(target_frame.columns) or set(source_frame.columns) != {"time", "close"}:
        raise CrossAssetRelativeStrengthBoundaryError("cross-asset frame schema is invalid")
    target = target_frame.reset_index(drop=True).copy()
    target["target_index"] = np.arange(len(target), dtype=np.int64)
    target = target.rename(columns={"close": "us100_close"})
    source = source_frame.rename(columns={"close": "us500_close"}).copy()
    for frame, name in ((target, "US100"), (source, "US500")):
        frame["time"] = pd.to_datetime(frame["time"], errors="raise")
        if frame["time"].duplicated().any() or not frame["time"].is_monotonic_increasing:
            raise CrossAssetRelativeStrengthBoundaryError(f"{name} timestamps are invalid")
    joined = target.merge(source, on="time", how="inner", sort=True, validate="one_to_one")
    if joined.empty or joined["time"].duplicated().any() or not joined["time"].is_monotonic_increasing:
        raise CrossAssetRelativeStrengthBoundaryError("exact cross-asset join is empty or invalid")
    return joined.reset_index(drop=True)


def compute_relative_strength_features(joined_frame: pd.DataFrame) -> RelativeStrengthFeatures:
    required = {"time", "us100_close", "us500_close", "target_index"}
    if not required.issubset(joined_frame.columns):
        raise ValueError("joined cross-asset frame schema is invalid")
    time_ns = _time_ns(joined_frame)
    run = _consecutive_run(time_ns)
    values: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for name in ("us100", "us500"):
        close = pd.to_numeric(joined_frame[f"{name}_close"], errors="raise").to_numpy(dtype=float)
        if np.any(~np.isfinite(close)) or np.any(close <= 0):
            raise ValueError(f"{name} close must be finite and positive")
        log_close = np.log(close)
        one_bar = np.full(len(close), np.nan)
        one_bar[1:] = np.diff(log_close)
        volatility = pd.Series(one_bar).rolling(48, min_periods=48).std(ddof=1).to_numpy(dtype=float)
        cumulative = np.full(len(close), np.nan)
        cumulative[12:] = log_close[12:] - log_close[:-12]
        zscore = cumulative / (volatility * sqrt(12))
        zscore[run < 49] = np.nan
        volatility[run < 49] = np.nan
        values[name] = (zscore, volatility)
    us100_score, us100_volatility = values["us100"]
    us500_score, _ = values["us500"]
    relative = us500_score - us100_score
    relative[~(np.isfinite(us500_score) & np.isfinite(us100_score))] = np.nan
    return RelativeStrengthFeatures(
        relative_strength_12_joint=relative,
        us500_direction_12_source_only=us500_score,
        us100_direction_12_target_only=us100_score,
        us100_volatility=us100_volatility,
        joint_run=run,
    )


def calibrate_selector(score: np.ndarray, train_mask: np.ndarray) -> float:
    values = np.abs(np.asarray(score, dtype=float)[train_mask & np.isfinite(score)])
    if len(values) < 1000:
        raise CrossAssetRelativeStrengthBoundaryError(
            "selector calibration has fewer than 1000 observations"
        )
    return float(np.quantile(values, SELECTOR_QUANTILE_BP / 10_000, method="higher"))


@dataclass(slots=True)
class CrossAssetSimulationResult:
    trades: pd.DataFrame
    intent_rows: tuple[tuple[Any, ...], ...]
    unresolved_cost_signal_count: int
    gap_excluded_signal_count: int
    causality_violation_count: int


def simulate_cross_asset_fixed_hold(
    *,
    target_frame: pd.DataFrame,
    joined_frame: pd.DataFrame,
    score: np.ndarray,
    us100_volatility: np.ndarray,
    joint_run: np.ndarray,
    threshold: float,
    configuration: CrossAssetRelativeStrengthConfiguration,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray | None = None,
) -> CrossAssetSimulationResult:
    """Trade on the original US100 time index; source is required only at decision."""

    if not isinstance(configuration, CrossAssetRelativeStrengthConfiguration):
        raise TypeError("configuration must be CrossAssetRelativeStrengthConfiguration")
    score_values = np.asarray(score, dtype=float)
    volatility = np.asarray(us100_volatility, dtype=float)
    runs = np.asarray(joint_run, dtype=np.int32)
    if not (len(joined_frame) == len(score_values) == len(volatility) == len(runs)):
        raise ValueError("cross-asset simulation inputs have different lengths")
    target = target_frame.reset_index(drop=True)
    target_time = pd.to_datetime(target["time"], errors="raise")
    target_time_ns = _time_ns(target)
    target_run = _consecutive_run(target_time_ns)
    opens = pd.to_numeric(target["open"], errors="raise").to_numpy(dtype=float)
    spreads = (
        causal_effective_spread(
            pd.to_numeric(target["spread"], errors="raise").to_numpy(dtype=float),
            target_time_ns,
        )
        if effective_spread is None
        else np.asarray(effective_spread, dtype=float)
    )
    if len(spreads) != len(target):
        raise ValueError("effective spread length differs from target frame")
    joined_time = pd.to_datetime(joined_frame["time"], errors="raise")
    target_indices = pd.to_numeric(joined_frame["target_index"], errors="raise").to_numpy(dtype=np.int64)
    candidates = np.flatnonzero(
        ((joined_time >= test_start) & (joined_time <= test_end)).to_numpy()
        & np.isfinite(score_values)
        & (runs >= 49)
    )
    records: list[dict[str, Any]] = []
    intents: list[tuple[Any, ...]] = []
    next_decision_target_index = -1
    unresolved = gap_excluded = causality = 0
    low_cutoff, high_cutoff = regime_cutoffs
    if not (
        np.isfinite(low_cutoff)
        and np.isfinite(high_cutoff)
        and low_cutoff <= high_cutoff
    ):
        raise ValueError("regime cutoffs are invalid")
    for joined_index in candidates:
        decision_index = int(target_indices[joined_index])
        if decision_index < next_decision_target_index:
            continue
        if decision_index < 0 or decision_index >= len(target):
            raise CrossAssetRelativeStrengthBoundaryError(
                "joined target index lies outside US100"
            )
        if target_time.iloc[decision_index] != joined_time.iloc[joined_index]:
            raise CrossAssetRelativeStrengthBoundaryError(
                "joined timestamp does not identify its original US100 row"
            )
        value = float(score_values[joined_index])
        if abs(value) < threshold:
            continue
        direction = int(np.sign(value)) * configuration.route_sign
        if direction == 0:
            continue
        entry_index = decision_index + 1
        exit_index = entry_index + configuration.holding_bars
        if exit_index >= len(target) or target_time.iloc[exit_index] > test_end:
            continue
        decision_bar_open_time = target_time.iloc[decision_index]
        decision_time = decision_bar_open_time + pd.Timedelta(minutes=5)
        entry_time = target_time.iloc[entry_index]
        exit_time = target_time.iloc[exit_index]
        if (
            target_time_ns[entry_index] - target_time_ns[decision_index]
            != _FIVE_MINUTES_NS
            or target_run[exit_index] < configuration.holding_bars + 2
        ):
            gap_excluded += 1
            intents.append((decision_time, entry_time, exit_time, direction, "gap_excluded"))
            continue
        if decision_time != entry_time:
            causality += 1
            intents.append((decision_time, entry_time, exit_time, direction, "causality_violation"))
            continue
        next_decision_target_index = exit_index
        if not (np.isfinite(spreads[entry_index]) and np.isfinite(spreads[exit_index])):
            unresolved += 1
            intents.append((decision_time, entry_time, exit_time, direction, "unknown_cost"))
            continue
        native, stress = execution_pnl(
            direction=direction,
            entry_bid=float(opens[entry_index]),
            exit_bid=float(opens[exit_index]),
            entry_spread_points=float(spreads[entry_index]),
            exit_spread_points=float(spreads[exit_index]),
        )
        entry_volatility = float(volatility[joined_index])
        regime = (
            "low"
            if entry_volatility <= low_cutoff
            else "high"
            if entry_volatility >= high_cutoff
            else "middle"
        )
        records.append(
            {
                "decision_bar_open_time": decision_bar_open_time,
                "decision_time": decision_time,
                "entry_time": entry_time,
                "exit_time": exit_time,
                "direction": direction,
                "pnl": native,
                "stress_pnl": stress,
                "fold_id": fold_id,
                "regime": regime,
            }
        )
        intents.append((decision_time, entry_time, exit_time, direction, "executed"))
    trades = pd.DataFrame.from_records(records)
    if trades.empty:
        trades = pd.DataFrame(
            columns=(
                "decision_bar_open_time",
                "decision_time",
                "entry_time",
                "exit_time",
                "direction",
                "pnl",
                "stress_pnl",
                "fold_id",
                "regime",
            )
        )
    return CrossAssetSimulationResult(
        trades=trades,
        intent_rows=tuple(intents),
        unresolved_cost_signal_count=unresolved,
        gap_excluded_signal_count=gap_excluded,
        causality_violation_count=causality,
    )


@dataclass(frozen=True, slots=True)
class _EvaluationContext:
    target_frame: pd.DataFrame
    joined_frame: pd.DataFrame
    features: RelativeStrengthFeatures
    effective_spread: np.ndarray


@dataclass(slots=True)
class _ConfigurationResult:
    configuration: CrossAssetRelativeStrengthConfiguration
    executable_id: str
    metrics: dict[str, int]
    fold_metrics: list[dict[str, int | str]]
    regime_metrics: list[dict[str, int | str]]
    session_metrics: list[dict[str, int | str]]
    direction_metrics: list[dict[str, int | str]]
    daily_pnl: pd.Series


def _prefix_mismatch_count(
    full: _EvaluationContext,
    prefix: _EvaluationContext,
    *,
    profile: str,
    end: pd.Timestamp,
) -> int:
    full_mask = pd.to_datetime(full.joined_frame["time"], errors="raise") <= end
    target_mask = pd.to_datetime(full.target_frame["time"], errors="raise") <= end
    expected_frame = full.joined_frame.loc[full_mask].reset_index(drop=True)
    if len(expected_frame) != len(prefix.joined_frame):
        return abs(len(expected_frame) - len(prefix.joined_frame)) + 1
    mismatch = int(
        not expected_frame.loc[:, ["time", "target_index"]].equals(
            prefix.joined_frame.loc[:, ["time", "target_index"]].reset_index(drop=True)
        )
    )
    pairs = (
        (full.features.score(profile)[full_mask.to_numpy()], prefix.features.score(profile)),
        (full.features.us100_volatility[full_mask.to_numpy()], prefix.features.us100_volatility),
        (full.features.joint_run[full_mask.to_numpy()], prefix.features.joint_run),
        (full.effective_spread[target_mask.to_numpy()], prefix.effective_spread),
    )
    for left, right in pairs:
        if len(left) != len(right):
            mismatch += abs(len(left) - len(right)) + 1
        else:
            mismatch += int(
                (~np.isclose(left, right, rtol=0.0, atol=0.0, equal_nan=True)).sum()
            )
    return mismatch


def _evaluate_configuration(
    *,
    context: _EvaluationContext,
    prefix_contexts: Mapping[str, _EvaluationContext],
    folds: Sequence[Mapping[str, Any]],
    configuration: CrossAssetRelativeStrengthConfiguration,
    calibrations: Mapping[str, tuple[float, float, tuple[float, float], tuple[float, float]]],
    raw_sha256: str,
) -> _ConfigurationResult:
    simulations: list[CrossAssetSimulationResult] = []
    fold_metrics: list[dict[str, int | str]] = []
    eligible_parts: list[pd.DatetimeIndex] = []
    append_mismatches = prefix_mismatches = source_unavailable = 0
    target_time = pd.to_datetime(context.target_frame["time"], errors="raise")
    joined_time = pd.to_datetime(context.joined_frame["time"], errors="raise")
    full_score = context.features.score(configuration.profile)
    for fold in folds:
        fold_id = str(fold["fold_id"])
        test = fold["test_oos"]
        test_start = pd.Timestamp(test["start"])
        test_end = pd.Timestamp(test["end"])
        threshold, prefix_threshold, cutoffs, prefix_cutoffs = calibrations[fold_id]
        simulation = simulate_cross_asset_fixed_hold(
            target_frame=context.target_frame,
            joined_frame=context.joined_frame,
            score=full_score,
            us100_volatility=context.features.us100_volatility,
            joint_run=context.features.joint_run,
            threshold=threshold,
            configuration=configuration,
            test_start=test_start,
            test_end=test_end,
            fold_id=fold_id,
            regime_cutoffs=cutoffs,
            effective_spread=context.effective_spread,
        )
        simulations.append(simulation)
        pnl = simulation.trades["pnl"].to_numpy(dtype=float)
        fold_metrics.append(
            {
                "fold_id": fold_id,
                "net_profit_micropoints": _micropoints(float(pnl.sum())),
                "profit_factor_milli": _profit_factor(pnl),
                "stress_net_profit_micropoints": _micropoints(
                    float(simulation.trades["stress_pnl"].sum())
                ),
                "trade_count": int(len(simulation.trades)),
                "unresolved_cost_signal_count": simulation.unresolved_cost_signal_count,
            }
        )
        target_test = (target_time >= test_start) & (target_time <= test_end)
        joined_test = (joined_time >= test_start) & (joined_time <= test_end)
        source_unavailable += int(target_test.sum() - joined_test.sum())
        eligible_parts.append(pd.DatetimeIndex(target_time[target_test]).normalize().unique())
        prefix = prefix_contexts[fold_id]
        prefix_mismatches += _prefix_mismatch_count(
            context, prefix, profile=configuration.profile, end=test_end
        )
        if not (
            np.isclose(threshold, prefix_threshold, rtol=0.0, atol=0.0)
            and np.allclose(cutoffs, prefix_cutoffs, rtol=0.0, atol=0.0)
        ):
            prefix_mismatches += 1
        prefix_simulation = simulate_cross_asset_fixed_hold(
            target_frame=prefix.target_frame,
            joined_frame=prefix.joined_frame,
            score=prefix.features.score(configuration.profile),
            us100_volatility=prefix.features.us100_volatility,
            joint_run=prefix.features.joint_run,
            threshold=prefix_threshold,
            configuration=configuration,
            test_start=test_start,
            test_end=test_end,
            fold_id=fold_id,
            regime_cutoffs=prefix_cutoffs,
            effective_spread=prefix.effective_spread,
        )
        left = simulation.intent_rows
        right = prefix_simulation.intent_rows
        append_mismatches += abs(len(left) - len(right)) + sum(
            left_item != right_item
            for left_item, right_item in zip(left, right, strict=False)
        )
    trades = pd.concat([item.trades for item in simulations], ignore_index=True)
    eligible_days = pd.DatetimeIndex(sorted(set().union(*(set(item) for item in eligible_parts))))
    daily_pnl = _daily_series(trades, eligible_days, "pnl")
    daily_entries = (
        pd.Series(0, index=eligible_days, dtype=int)
        if trades.empty
        else trades.assign(day=pd.to_datetime(trades["decision_time"]).dt.normalize())
        .groupby("day", sort=True)
        .size()
        .reindex(eligible_days, fill_value=0)
        .astype(int)
    )
    net = float(trades["pnl"].sum()) if not trades.empty else 0.0
    stress = float(trades["stress_pnl"].sum()) if not trades.empty else 0.0
    drawdown, drawdown_share = _monthly_realized_exit_drawdown(trades)
    positive_daily = daily_pnl[daily_pnl > 0].sort_values(ascending=False)
    gross_positive = float(positive_daily.sum())
    top5_share = (
        0
        if gross_positive <= 0
        else min(1_000_000, int(round(1_000_000 * float(positive_daily.head(5).sum()) / gross_positive)))
    )
    regime_metrics: list[dict[str, int | str]] = []
    for regime in ("low", "middle", "high"):
        selected = trades[trades["regime"] == regime]
        by_fold = selected.groupby("fold_id", sort=True)["pnl"].sum() if not selected.empty else pd.Series(dtype=float)
        regime_metrics.append(
            {
                "evaluable_fold_count": int(len(by_fold)),
                "regime": regime,
                "net_profit_micropoints": _micropoints(float(selected["pnl"].sum())),
                "trade_count": int(len(selected)),
                "winning_fold_count": int((by_fold > 0).sum()),
            }
        )
    hours = pd.to_datetime(trades["entry_time"]).dt.hour if not trades.empty else pd.Series(dtype=int)
    labels = (
        pd.Series(
            np.select(
                [hours.between(1, 7), hours.between(8, 14), hours.between(15, 22)],
                ["broker_01_07", "broker_08_14", "broker_15_22"],
                default="broker_23_00",
            ),
            index=trades.index,
        )
        if not trades.empty
        else pd.Series(dtype=object)
    )
    session_metrics: list[dict[str, int | str]] = []
    for session in ("broker_01_07", "broker_08_14", "broker_15_22", "broker_23_00"):
        selected = trades[labels == session] if not trades.empty else trades
        session_metrics.append(
            {
                "session": session,
                "net_profit_micropoints": _micropoints(float(selected["pnl"].sum())),
                "trade_count": int(len(selected)),
            }
        )
    direction_metrics: list[dict[str, int | str]] = []
    for direction, label in ((1, "long"), (-1, "short")):
        selected = trades[trades["direction"] == direction]
        direction_metrics.append(
            {
                "direction": label,
                "net_profit_micropoints": _micropoints(float(selected["pnl"].sum())),
                "trade_count": int(len(selected)),
            }
        )
    fold_pf = sorted(int(item["profit_factor_milli"]) for item in fold_metrics)
    unresolved = sum(item.unresolved_cost_signal_count for item in simulations)
    metrics = {
        "append_invariance_mismatch_count": append_mismatches,
        "causality_violation_count": sum(item.causality_violation_count for item in simulations),
        "daily_entries_max_milli": 0 if daily_entries.empty else int(daily_entries.max()) * 1000,
        "daily_entries_median_milli": 0 if daily_entries.empty else int(round(1000 * float(daily_entries.median()))),
        "daily_entries_p10_milli": 0 if daily_entries.empty else int(round(1000 * float(np.quantile(daily_entries, 0.10, method="lower")))),
        "daily_entries_p90_milli": 0 if daily_entries.empty else int(round(1000 * float(np.quantile(daily_entries, 0.90, method="higher")))),
        "eligible_day_count": int(len(eligible_days)),
        "entries_per_day_milli": 0 if not len(eligible_days) else int(round(1000 * len(trades) / len(eligible_days))),
        "evaluable_folds": sum(int(item["trade_count"]) > 0 for item in fold_metrics),
        "gap_excluded_signal_count": sum(item.gap_excluded_signal_count for item in simulations),
        "median_fold_profit_factor_milli": fold_pf[len(fold_pf) // 2] if fold_pf else 0,
        "monthly_realized_exit_drawdown_micropoints": _micropoints(drawdown),
        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": drawdown_share,
        "net_profit_micropoints": _micropoints(net),
        "nonfinite_metric_count": 0,
        "positive_regime_count": sum(int(item["net_profit_micropoints"]) > 0 for item in regime_metrics),
        "prefix_invariance_mismatch_count": prefix_mismatches,
        "selection_aware_pvalue_ppm": 1_000_000,
        "source_unavailable_decision_count": source_unavailable,
        "stress_net_profit_micropoints": _micropoints(stress),
        "supported_positive_regime_count": sum(
            int(item["net_profit_micropoints"]) > 0
            and int(item["trade_count"]) >= 30
            and int(item["evaluable_fold_count"]) >= 5
            and int(item["winning_fold_count"]) >= 3
            and 2 * int(item["winning_fold_count"]) > int(item["evaluable_fold_count"])
            for item in regime_metrics
        ),
        "top5_profit_day_share_ppm": top5_share,
        "trade_count": int(len(trades)),
        "unknown_cost_unresolved_signal_count": unresolved,
        "winning_fold_count": sum(int(item["net_profit_micropoints"]) > 0 for item in fold_metrics),
        "zero_entry_day_rate_ppm": 0 if daily_entries.empty else int(round(1_000_000 * int((daily_entries == 0).sum()) / len(daily_entries))),
    }
    executable_id = cross_asset_relative_strength_executable(configuration, raw_sha256).identity
    return _ConfigurationResult(
        configuration=configuration,
        executable_id=executable_id,
        metrics=metrics,
        fold_metrics=fold_metrics,
        regime_metrics=regime_metrics,
        session_metrics=session_metrics,
        direction_metrics=direction_metrics,
        daily_pnl=daily_pnl,
    )


def _overlapping_block_sums(values: np.ndarray, length: int) -> np.ndarray:
    cumulative = np.concatenate(([0.0], np.cumsum(values, dtype=float)))
    return cumulative[length:] - cumulative[:-length]


def _adjusted_bootstrap_upper_pvalue(values: np.ndarray, *, seed_label: str) -> int:
    sample = np.asarray(values, dtype=float)
    if len(sample) < 30 or np.any(~np.isfinite(sample)):
        raise CrossAssetRelativeStrengthBoundaryError(
            "bootstrap series is invalid or too short"
        )
    standard = float(sample.std(ddof=1))
    if standard <= 0 or float(sample.mean()) <= 0:
        return 1_000_000
    observed = float(sample.mean() * sqrt(len(sample)) / standard)
    centered = sample - sample.mean()
    squares = centered * centered
    worst = 0.0
    for length in SELECTION_BLOCK_LENGTHS:
        seed = sha256(f"{SELECTION_SEED}:{seed_label}:{length}".encode("ascii")).digest()
        rng = np.random.default_rng(int.from_bytes(seed[:8], "big"))
        full_count, remainder = divmod(len(centered), length)
        sums = _overlapping_block_sums(centered, length)
        square_sums = _overlapping_block_sums(squares, length)
        partial_sums = None if remainder == 0 else _overlapping_block_sums(centered, remainder)
        partial_squares = None if remainder == 0 else _overlapping_block_sums(squares, remainder)
        exceedances = generated = 0
        while generated < SELECTION_BOOTSTRAP_SAMPLES:
            count = min(256, SELECTION_BOOTSTRAP_SAMPLES - generated)
            starts = rng.integers(0, len(sums), size=(count, full_count))
            draw_sum = sums[starts].sum(axis=1)
            draw_square = square_sums[starts].sum(axis=1)
            if partial_sums is not None and partial_squares is not None:
                partial_starts = rng.integers(0, len(partial_sums), size=count)
                draw_sum += partial_sums[partial_starts]
                draw_square += partial_squares[partial_starts]
            variance = np.maximum(
                0.0,
                (draw_square - draw_sum * draw_sum / len(centered))
                / (len(centered) - 1),
            )
            statistics = np.divide(
                draw_sum / len(centered) * sqrt(len(centered)),
                np.sqrt(variance),
                out=np.zeros(count),
                where=variance > 0,
            )
            exceedances += int((statistics >= observed).sum())
            generated += count
        point = (1 + exceedances) / (SELECTION_BOOTSTRAP_SAMPLES + 1)
        upper = (
            1.0
            if exceedances >= SELECTION_BOOTSTRAP_SAMPLES
            else float(
                beta.ppf(
                    SELECTION_MONTE_CARLO_CONFIDENCE_PPM / 1_000_000,
                    exceedances + 1,
                    SELECTION_BOOTSTRAP_SAMPLES - exceedances,
                )
            )
        )
        worst = max(
            worst,
            min(1.0, max(point, upper) * SELECTION_TOTAL_EXPOSURES),
        )
    return min(1_000_000, int(ceil(1_000_000 * worst)))


def _matched_result(
    results: Sequence[_ConfigurationResult],
    *,
    profile: str,
    route_sign: int,
    holding_bars: int,
) -> _ConfigurationResult:
    matches = [
        item
        for item in results
        if item.configuration.profile == profile
        and item.configuration.route_sign == route_sign
        and item.configuration.holding_bars == holding_bars
    ]
    if len(matches) != 1:
        raise CrossAssetRelativeStrengthBoundaryError(
            "registered cross-asset control match is not unique"
        )
    return matches[0]


def _paired_pvalue(
    subject: _ConfigurationResult,
    control: _ConfigurationResult,
    role: str,
) -> int:
    if not subject.daily_pnl.index.equals(control.daily_pnl.index):
        raise CrossAssetRelativeStrengthBoundaryError(
            "paired controls have different eligible days"
        )
    return _adjusted_bootstrap_upper_pvalue(
        subject.daily_pnl.to_numpy(dtype=float)
        - control.daily_pnl.to_numpy(dtype=float),
        seed_label=(
            f"control:{role}:{subject.executable_id}:{control.executable_id}"
        ),
    )


def _populate_pvalues_and_controls(results: Sequence[_ConfigurationResult]) -> None:
    for subject in results:
        subject.metrics["selection_aware_pvalue_ppm"] = _adjusted_bootstrap_upper_pvalue(
            subject.daily_pnl.to_numpy(dtype=float),
            seed_label=f"selection:{subject.executable_id}",
        )
        opposite = _matched_result(
            results,
            profile=subject.configuration.profile,
            route_sign=-subject.configuration.route_sign,
            holding_bars=subject.configuration.holding_bars,
        )
        controls = [
            _matched_result(
                results,
                profile=profile,
                route_sign=subject.configuration.route_sign,
                holding_bars=subject.configuration.holding_bars,
            )
            for profile in _PROFILES
            if profile != subject.configuration.profile
        ]
        subject.metrics["opposite_sign_worst_delta_net_profit_micropoints"] = (
            subject.metrics["net_profit_micropoints"]
            - opposite.metrics["net_profit_micropoints"]
        )
        subject.metrics["opposite_sign_pvalue_upper_ppm"] = _paired_pvalue(
            subject, opposite, "opposite_sign"
        )
        subject.metrics["feature_control_worst_delta_net_profit_micropoints"] = min(
            subject.metrics["net_profit_micropoints"]
            - control.metrics["net_profit_micropoints"]
            for control in controls
        )
        subject.metrics["feature_control_worst_pvalue_upper_ppm"] = max(
            _paired_pvalue(subject, control, "profile") for control in controls
        )
        if any(type(value) is not int for value in subject.metrics.values()):
            raise CrossAssetRelativeStrengthBoundaryError(
                "cross-asset scientific metrics are not fixed-point integers"
            )


def _context(target_frame: pd.DataFrame, source_frame: pd.DataFrame) -> _EvaluationContext:
    target = target_frame.reset_index(drop=True).copy()
    joined = _join_exact(target, source_frame)
    return _EvaluationContext(
        target_frame=target,
        joined_frame=joined,
        features=compute_relative_strength_features(joined),
        effective_spread=causal_effective_spread(
            pd.to_numeric(target["spread"], errors="raise").to_numpy(dtype=float),
            _time_ns(target),
        ),
    )


def _calibrations(
    *,
    context: _EvaluationContext,
    prefix_contexts: Mapping[str, _EvaluationContext],
    folds: Sequence[Mapping[str, Any]],
    profile: str,
) -> dict[str, tuple[float, float, tuple[float, float], tuple[float, float]]]:
    result: dict[str, tuple[float, float, tuple[float, float], tuple[float, float]]] = {}
    full_time = pd.to_datetime(context.joined_frame["time"], errors="raise")
    for fold in folds:
        fold_id = str(fold["fold_id"])
        train = fold["train_is"]
        start = pd.Timestamp(train["start"])
        end = pd.Timestamp(train["end"])
        train_mask = ((full_time >= start) & (full_time <= end)).to_numpy()
        threshold = calibrate_selector(context.features.score(profile), train_mask)
        full_volatility = context.features.us100_volatility[
            train_mask & np.isfinite(context.features.us100_volatility)
        ]
        if len(full_volatility) < 1000:
            raise CrossAssetRelativeStrengthBoundaryError(
                "cross-asset regime calibration is too small"
            )
        cutoffs = (
            float(np.quantile(full_volatility, 1 / 3, method="higher")),
            float(np.quantile(full_volatility, 2 / 3, method="higher")),
        )
        prefix = prefix_contexts[fold_id]
        prefix_time = pd.to_datetime(prefix.joined_frame["time"], errors="raise")
        prefix_train = ((prefix_time >= start) & (prefix_time <= end)).to_numpy()
        prefix_threshold = calibrate_selector(
            prefix.features.score(profile), prefix_train
        )
        prefix_volatility = prefix.features.us100_volatility[
            prefix_train & np.isfinite(prefix.features.us100_volatility)
        ]
        if len(prefix_volatility) < 1000:
            raise CrossAssetRelativeStrengthBoundaryError(
                "prefix regime calibration is too small"
            )
        prefix_cutoffs = (
            float(np.quantile(prefix_volatility, 1 / 3, method="higher")),
            float(np.quantile(prefix_volatility, 2 / 3, method="higher")),
        )
        result[fold_id] = (
            threshold,
            prefix_threshold,
            cutoffs,
            prefix_cutoffs,
        )
    return result


def _selection_method() -> dict[str, Any]:
    return {
        "bootstrap_samples": SELECTION_BOOTSTRAP_SAMPLES,
        "block_days": list(SELECTION_BLOCK_LENGTHS),
        "method": "centered_non_circular_moving_block_studentized_one_sided_then_bonferroni",
        "monte_carlo_upper_confidence_ppm": SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
        "multiple_block_rule": "maximum_adjusted_pvalue",
        "paired_control_rule": "same_eligible_decision_day_intersection_union_worst_control",
        "seed": SELECTION_SEED,
        "seed_derivation": "sha256_base_seed_label_block_length_first_u64",
        "total_exposures": SELECTION_TOTAL_EXPOSURES,
    }


def _claim_limits() -> list[str]:
    return [
        "discovery_only",
        "candidate_eligible_false_independent_confirmation_required",
        "US500_source_eligibility_is_not_scientific_performance_evidence",
        "US500_spread_is_not_US100_execution_cost",
        "exact_timestamp_inner_join_no_fill_no_asof_no_zero",
        "source_required_at_decision_not_after_entry",
        "holding_bars_index_original_US100_timeline",
        "source_tail_after_2026_04_30_23_55_never_enters_parser",
        "daily_pnl_is_attributed_to_decision_day",
        "monthly_drawdown_is_exit_realized_not_mark_to_market",
        "regime_support_requires_30_trades_5_folds_3_winning_folds",
        "regime_support_requires_strict_majority_winning_evaluable_folds",
        "session_bins_are_descriptive_only",
        "controls_are_registered_executables_in_the_same_batch",
    ]


def _surface_from_frames(
    *,
    target_frame: pd.DataFrame,
    source_frame: pd.DataFrame,
    folds: Sequence[Mapping[str, Any]],
    raw_sha256: str,
    source_prefix_sha256: str,
) -> dict[str, Any]:
    raw = _require_digest(raw_sha256, "US500 raw hash")
    prefix_hash = _require_digest(source_prefix_sha256, "US500 prefix hash")
    context = _context(target_frame, source_frame)
    target_time = pd.to_datetime(context.target_frame["time"], errors="raise")
    source_time = pd.to_datetime(source_frame["time"], errors="raise")
    prefix_contexts: dict[str, _EvaluationContext] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        end = pd.Timestamp(fold["test_oos"]["end"])
        prefix_contexts[fold_id] = _context(
            context.target_frame.loc[target_time <= end].reset_index(drop=True),
            source_frame.loc[source_time <= end].reset_index(drop=True),
        )
    calibration_by_profile = {
        profile: _calibrations(
            context=context,
            prefix_contexts=prefix_contexts,
            folds=folds,
            profile=profile,
        )
        for profile in _PROFILES
    }
    results = [
        _evaluate_configuration(
            context=context,
            prefix_contexts=prefix_contexts,
            folds=folds,
            configuration=configuration,
            calibrations=calibration_by_profile[configuration.profile],
            raw_sha256=raw,
        )
        for configuration in cross_asset_relative_strength_configurations()
    ]
    _populate_pvalues_and_controls(results)
    source = _source_identity_payload()
    surface: dict[str, Any] = {
        "claim_limits": _claim_limits(),
        "dataset_sha256": DATASET_SHA256,
        "discovery_implementation_sha256": cross_asset_relative_strength_implementation_sha256(),
        "engine_environment": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "python": ".".join(str(value) for value in sys.version_info[:3]),
            "scipy": scipy.__version__,
        },
        "evaluations": [
            {
                "direction_metrics": item.direction_metrics,
                "evaluable": all(
                    item.metrics[name] == 0
                    for name in (
                        "unknown_cost_unresolved_signal_count",
                        "causality_violation_count",
                        "nonfinite_metric_count",
                        "prefix_invariance_mismatch_count",
                        "append_invariance_mismatch_count",
                    )
                ),
                "fold_metrics": item.fold_metrics,
                "metrics": dict(sorted(item.metrics.items())),
                "regime_metrics": item.regime_metrics,
                "session_metrics": item.session_metrics,
                "subject_configuration_id": item.configuration.configuration_id,
                "subject_executable_id": item.executable_id,
            }
            for item in results
        ],
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "schema": "cross_asset_relative_strength_surface.v1",
        "selection_context": [
            {
                "configuration_id": item.configuration.configuration_id,
                "executable_id": item.executable_id,
                "net_profit_micropoints": item.metrics["net_profit_micropoints"],
                "selection_aware_pvalue_ppm": item.metrics["selection_aware_pvalue_ppm"],
            }
            for item in results
        ],
        "selection_method": _selection_method(),
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "source_contract_identities": source,
        "source_development_prefix_sha256": prefix_hash,
        "source_implementation_sha256": us500_source_implementation_sha256(),
        "source_raw_sha256": raw,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "trend_dependency_sha256": trend_dependency_sha256(),
    }
    canonical_bytes(surface)
    return surface


def _compute_registered_cross_asset_relative_strength_surface(
    repository_root: str | Path,
) -> dict[str, Any]:
    if not isinstance(repository_root, (str, Path)):
        raise CrossAssetRelativeStrengthBoundaryError(
            "cross-asset surface requires a repository path"
        )
    root = Path(repository_root).resolve()
    _validate_engine_environment()
    target: ObservedDevelopmentData = load_observed_development(root)
    _validate_production_data(target)
    folds = _fold_payloads(target)
    _validate_fold_payloads(target.frame, folds)
    raw = us500_raw_sha256(root)
    source = load_us500_observed_development(root, expected_raw_sha256=raw)
    if target.metadata.last_development_time != DEVELOPMENT_END:
        raise CrossAssetRelativeStrengthBoundaryError(
            "US100 and US500 development boundary differs"
        )
    return _surface_from_frames(
        target_frame=target.frame,
        source_frame=source.frame,
        folds=folds,
        raw_sha256=raw,
        source_prefix_sha256=source.metadata.development_prefix_sha256,
    )


def project_cross_asset_relative_strength_evaluation(
    surface: Mapping[str, Any],
    *,
    job_execution: Mapping[str, str],
    subject_executable_id: str,
    surface_artifact_hash: str,
    surface_manifest_hash: str,
) -> dict[str, Any]:
    for name, digest in (
        ("surface artifact", surface_artifact_hash),
        ("surface manifest", surface_manifest_hash),
    ):
        _require_digest(digest, name)
    if not isinstance(job_execution, Mapping) or set(job_execution) != {
        "identity",
        "job_hash",
        "job_id",
        "job_permit_id",
        "start_record_id",
    }:
        raise CrossAssetRelativeStrengthBoundaryError(
            "Job execution binding is invalid"
        )
    payload = {
        name: job_execution[name]
        for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")
    }
    if job_execution["identity"] != canonical_digest(
        domain="running-job-execution", payload=payload
    ):
        raise CrossAssetRelativeStrengthBoundaryError(
            "Job execution identity is invalid"
        )
    value = dict(surface)
    if sha256(canonical_bytes(value)).hexdigest() != surface_artifact_hash:
        raise CrossAssetRelativeStrengthBoundaryError(
            "surface bytes differ from their artifact hash"
        )
    expected_fields = {
        "claim_limits",
        "dataset_sha256",
        "discovery_implementation_sha256",
        "engine_environment",
        "evaluations",
        "loader_implementation_sha256",
        "material_identity",
        "schema",
        "selection_context",
        "selection_method",
        "session_semantics",
        "source_contract_identities",
        "source_development_prefix_sha256",
        "source_implementation_sha256",
        "source_raw_sha256",
        "split_artifact_sha256",
        "trend_dependency_sha256",
    }
    if set(value) != expected_fields or value.get("schema") != "cross_asset_relative_strength_surface.v1":
        raise CrossAssetRelativeStrengthBoundaryError(
            "cross-asset surface schema is invalid"
        )
    if (
        value["dataset_sha256"] != DATASET_SHA256
        or value["material_identity"] != OBSERVED_MATERIAL_ID
        or value["split_artifact_sha256"] != ROLLING_SPLIT_SHA256
        or value["discovery_implementation_sha256"]
        != cross_asset_relative_strength_implementation_sha256()
        or value["loader_implementation_sha256"] != loader_implementation_sha256()
        or value["source_implementation_sha256"] != us500_source_implementation_sha256()
        or value["trend_dependency_sha256"] != trend_dependency_sha256()
        or value["source_contract_identities"] != _source_identity_payload()
    ):
        raise CrossAssetRelativeStrengthBoundaryError(
            "cross-asset surface dependencies differ"
        )
    raw = _require_digest(value["source_raw_sha256"], "surface US500 raw hash")
    _require_digest(
        value["source_development_prefix_sha256"], "surface US500 prefix hash"
    )
    expected = _configuration_map_for_raw(raw)
    evaluations = value.get("evaluations")
    if not isinstance(evaluations, list) or len(evaluations) != len(expected):
        raise CrossAssetRelativeStrengthBoundaryError(
            "cross-asset surface evaluation count is invalid"
        )
    by_identity = {
        item.get("subject_executable_id"): item
        for item in evaluations
        if isinstance(item, Mapping)
    }
    if (
        len(by_identity) != len(evaluations)
        or set(by_identity) != set(expected)
        or subject_executable_id not in expected
    ):
        raise CrossAssetRelativeStrengthBoundaryError(
            "cross-asset surface subjects differ from registration"
        )
    for identity, configuration in expected.items():
        if by_identity[identity].get("subject_configuration_id") != configuration.configuration_id:
            raise CrossAssetRelativeStrengthBoundaryError(
                "cross-asset surface configuration binding differs"
            )
    evaluation = {
        **dict(by_identity[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "cross_asset_relative_strength_evaluation.v1",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(evaluation)
    return evaluation


__all__ = [
    "DATASET_SHA256",
    "DEVELOPMENT_END",
    "OBSERVED_MATERIAL_ID",
    "ROLLING_SPLIT_SHA256",
    "CrossAssetRelativeStrengthBoundaryError",
    "CrossAssetRelativeStrengthConfiguration",
    "RelativeStrengthFeatures",
    "SELECTOR_QUANTILE_BP",
    "SELECTION_BLOCK_LENGTHS",
    "SELECTION_BOOTSTRAP_SAMPLES",
    "SELECTION_MONTE_CARLO_CONFIDENCE_PPM",
    "SELECTION_SEED",
    "SELECTION_TOTAL_EXPOSURES",
    "US500DevelopmentMetadata",
    "US500ObservedDevelopment",
    "_compute_registered_cross_asset_relative_strength_surface",
    "_surface_from_frames",
    "calibrate_selector",
    "compute_relative_strength_features",
    "cross_asset_relative_strength_components",
    "cross_asset_relative_strength_configurations",
    "cross_asset_relative_strength_executable",
    "cross_asset_relative_strength_executable_configuration_map",
    "cross_asset_relative_strength_implementation_sha256",
    "executable_configuration_map",
    "load_us500_observed_development",
    "loader_implementation_sha256",
    "project_cross_asset_relative_strength_evaluation",
    "simulate_cross_asset_fixed_hold",
    "trend_dependency_sha256",
    "us500_raw_sha256",
    "us500_source_implementation_sha256",
]
