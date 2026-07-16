"""Causal rolling price-level interaction discovery for US100 M5."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec, canonical_digest
from axiom_rift.research.data import load_observed_development
from axiom_rift.research import data as data_module
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    SELECTION_BLOCK_LENGTHS,
    SELECTION_BOOTSTRAP_SAMPLES,
    SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
    SELECTION_SEED,
    DiscoveryBoundaryError,
    _claim_limits,
    _consecutive_run,
    _evaluate_configuration,
    _fold_payloads,
    _paired_control_pvalue,
    _selection_adjusted_pvalues,
    _selection_method,
    _time_ns,
    _validate_engine_environment,
    _validate_fold_payloads,
    _validate_production_data,
    causal_effective_spread,
    discovery_implementation_sha256,
)


SELECTION_TOTAL_EXPOSURES = 258
SELECTOR_QUANTILE_BP = 5_000
_LOOKBACKS = {"level_12": 12, "level_24": 24, "level_48": 48}
_THIS_FILE = Path(__file__).resolve()


def price_level_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def loader_implementation_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class PriceLevelConfiguration:
    profile: str
    signal_sign: int
    holding_bars: int

    def __post_init__(self) -> None:
        if self.profile not in _LOOKBACKS:
            raise ValueError("price-level profile is not registered")
        if self.signal_sign not in {-1, 1}:
            raise ValueError("signal_sign must be -1 or 1")
        if self.holding_bars not in {3, 12}:
            raise ValueError("holding_bars is not registered")

    @property
    def lookback(self) -> int:
        return _LOOKBACKS[self.profile]

    @property
    def configuration_id(self) -> str:
        sign = "continuation" if self.signal_sign == 1 else "reversal"
        return f"{self.profile}-{sign}-h{self.holding_bars}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "holding_bars": self.holding_bars,
            "level_lookback_bars": self.lookback,
            "selector_nonzero_quantile_bp": SELECTOR_QUANTILE_BP,
            "signal_sign": self.signal_sign,
        }


def price_level_configurations() -> tuple[PriceLevelConfiguration, ...]:
    return tuple(
        PriceLevelConfiguration(profile=profile, signal_sign=signal_sign, holding_bars=holding)
        for profile in ("level_12", "level_24", "level_48")
        for signal_sign in (1, -1)
        for holding in (3, 12)
    )


def _local_implementation(function_name: str) -> str:
    return (
        f"axiom_rift.research.price_level_discovery.{function_name}@sha256:"
        f"{price_level_implementation_sha256()}"
    )


def _shared_implementation(function_name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{function_name}@sha256:"
        f"{discovery_implementation_sha256()}"
    )


def price_level_components() -> tuple[ComponentSpec, ...]:
    return (
        ComponentSpec(
            display_name="causal rolling high-low penetration score",
            protocol="feature.rolling_price_level_penetration.v1",
            implementation=_local_implementation("compute_price_level_score"),
            spec={
                "availability": "completed_bar_only",
                "formula": "signed close penetration beyond prior rolling high or low divided by trailing median true range",
                "prior_level_excludes_current_bar": True,
                "range_window_bars": 48,
                "parameter_fields": ["level_lookback_bars"],
            },
        ),
        ComponentSpec(
            display_name="fold isolated nonzero penetration selector",
            protocol="selector.fold_train_nonzero_abs_quantile.v1",
            implementation=_local_implementation("calibrate_price_level_selector"),
            spec={
                "calibration_role": "train_is_only",
                "minimum_nonzero_observations": 1000,
                "quantile_basis_points": SELECTOR_QUANTILE_BP,
                "quantile_method": "higher",
            },
        ),
        ComponentSpec(
            display_name="completed-bar next-open directional entry",
            protocol="trade.completed_bar_next_open_direction.v2",
            implementation=_shared_implementation("simulate_fixed_hold"),
            spec={
                "decision_time": "bar_open_plus_5m",
                "entry_time": "next_exact_bar_open",
                "direction": "signal_sign_times_penetration_sign",
                "parameter_fields": ["signal_sign"],
            },
        ),
        ComponentSpec(
            display_name="fixed-hold nonoverlap lifecycle",
            protocol="lifecycle.fixed_hold_no_overlap.v2",
            implementation=_shared_implementation("simulate_fixed_hold"),
            spec={
                "entry_overlap": "reject_while_position_slot_is_occupied",
                "exit_surface": "exact_bar_open_after_holding_bars",
                "gap_action": "exclude_path",
                "parameter_fields": ["holding_bars"],
            },
        ),
        ComponentSpec(
            display_name="FPMarkets completed-period spread proxy execution",
            protocol="execution.fpmarkets_completed_bar_spread_proxy.v2",
            implementation=_shared_implementation("execution_pnl"),
            spec={
                "bar_quote_basis": "bid_ohlc_with_spread_points",
                "point": "0.01",
                "stress": "half_effective_spread_each_side",
                "zero_spread_action": "causal_lagged_positive_median",
            },
        ),
        ComponentSpec(
            display_name="fixed one-lot single-sleeve risk",
            protocol="risk.fixed_one_lot.v1",
            implementation=_shared_implementation("simulate_fixed_hold"),
            spec={"dynamic_sizing": False, "lot": 1, "positions_per_sleeve": 1},
        ),
    )


def price_level_executable(configuration: PriceLevelConfiguration) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"price level interaction {configuration.configuration_id}",
        components=price_level_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v2",
        cost_contract="cost:fpmarkets_completed_bar_spread_proxy_point_0_01_causal_zero_repair_half_spread_stress_v2",
        engine_contract=(
            "engine:price_level_discovery_v1:python3_13_9:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"implementation_{price_level_implementation_sha256()}:"
            f"loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:"
            f"bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:"
            f"mc_upper_{SELECTION_MONTE_CARLO_CONFIDENCE_PPM}:"
            f"bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def executable_configuration_map() -> dict[str, PriceLevelConfiguration]:
    return {
        price_level_executable(configuration).identity: configuration
        for configuration in price_level_configurations()
    }


def compute_price_level_score(
    frame: pd.DataFrame, lookback: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if lookback not in set(_LOOKBACKS.values()):
        raise ValueError("lookback is not registered")
    high = pd.to_numeric(frame["high"], errors="raise").to_numpy(dtype=float)
    low = pd.to_numeric(frame["low"], errors="raise").to_numpy(dtype=float)
    close = pd.to_numeric(frame["close"], errors="raise").to_numpy(dtype=float)
    if np.any(~np.isfinite(np.column_stack((high, low, close)))):
        raise ValueError("price fields must be finite")
    prior_high = pd.Series(high).shift(1).rolling(lookback, min_periods=lookback).max().to_numpy()
    prior_low = pd.Series(low).shift(1).rolling(lookback, min_periods=lookback).min().to_numpy()
    previous_close = np.roll(close, 1)
    previous_close[0] = close[0]
    true_range = np.maximum.reduce((high - low, np.abs(high - previous_close), np.abs(low - previous_close)))
    scale = pd.Series(true_range).rolling(48, min_periods=48).median().to_numpy(dtype=float)
    score = np.zeros(len(frame), dtype=float)
    upper = close > prior_high
    lower = close < prior_low
    valid_scale = np.isfinite(scale) & (scale > 0)
    score[upper & valid_scale] = (close[upper & valid_scale] - prior_high[upper & valid_scale]) / scale[upper & valid_scale]
    score[lower & valid_scale] = (close[lower & valid_scale] - prior_low[lower & valid_scale]) / scale[lower & valid_scale]
    run = _consecutive_run(_time_ns(frame))
    score[(run < max(49, lookback + 1)) | ~np.isfinite(score)] = np.nan
    volatility = pd.Series(np.log(close)).diff().rolling(48, min_periods=48).std(ddof=1).to_numpy(dtype=float)
    return score, volatility, run


def calibrate_price_level_selector(score: np.ndarray, train_mask: np.ndarray) -> float:
    values = np.abs(score[train_mask & np.isfinite(score) & (score != 0)])
    if len(values) < 1000:
        raise DiscoveryBoundaryError("price-level selector has fewer than 1000 nonzero observations")
    return float(np.quantile(values, SELECTOR_QUANTILE_BP / 10_000, method="higher"))


def _matched(results: list[Any], profile: str, signal_sign: int, holding_bars: int) -> Any:
    matches = [
        result for result in results
        if result.configuration.profile == profile
        and result.configuration.signal_sign == signal_sign
        and result.configuration.holding_bars == holding_bars
    ]
    if len(matches) != 1:
        raise DiscoveryBoundaryError("price-level control match is not unique")
    return matches[0]


def _populate_controls(results: list[Any]) -> None:
    for subject in results:
        opposite = _matched(results, subject.configuration.profile, -subject.configuration.signal_sign, subject.configuration.holding_bars)
        controls = [
            _matched(results, profile, subject.configuration.signal_sign, subject.configuration.holding_bars)
            for profile in _LOOKBACKS
            if profile != subject.configuration.profile
        ]
        subject.metrics["opposite_sign_worst_delta_net_profit_micropoints"] = subject.metrics["net_profit_micropoints"] - opposite.metrics["net_profit_micropoints"]
        subject.metrics["opposite_sign_pvalue_upper_ppm"] = _paired_control_pvalue(subject, opposite, role="opposite_sign", total_exposures=SELECTION_TOTAL_EXPOSURES)
        subject.metrics["feature_control_worst_delta_net_profit_micropoints"] = min(subject.metrics["net_profit_micropoints"] - control.metrics["net_profit_micropoints"] for control in controls)
        subject.metrics["feature_control_worst_pvalue_upper_ppm"] = max(_paired_control_pvalue(subject, control, role="lookback", total_exposures=SELECTION_TOTAL_EXPOSURES) for control in controls)


def compute_registered_price_level_surface(repository_root: str | Path) -> dict[str, Any]:
    _validate_engine_environment()
    data = load_observed_development(Path(repository_root).resolve())
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    effective_spread = causal_effective_spread(frame["spread"].to_numpy(dtype=float), _time_ns(frame))
    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        end = int(time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]), side="right"))
        prefix_frames[fold_id] = frame.iloc[:end]
        prefix_spreads[fold_id] = causal_effective_spread(prefix_frames[fold_id]["spread"].to_numpy(dtype=float), _time_ns(prefix_frames[fold_id]))
    feature_cache: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_cache: dict[str, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]] = {}
    calibration_cache: dict[str, dict[str, tuple[float, tuple[float, float], float]]] = {}
    for profile, lookback in _LOOKBACKS.items():
        features = compute_price_level_score(frame, lookback)
        feature_cache[profile] = features
        prefix_cache[profile] = {}
        calibration_cache[profile] = {}
        for fold in folds:
            fold_id = str(fold["fold_id"])
            train = fold["train_is"]
            train_mask = ((time >= pd.Timestamp(train["start"])) & (time <= pd.Timestamp(train["end"]))).to_numpy()
            threshold = calibrate_price_level_selector(features[0], train_mask)
            train_volatility = features[1][train_mask & np.isfinite(features[1])]
            cutoffs = (
                float(np.quantile(train_volatility, 1 / 3, method="higher")),
                float(np.quantile(train_volatility, 2 / 3, method="higher")),
            )
            prefix_features = compute_price_level_score(prefix_frames[fold_id], lookback)
            prefix_cache[profile][fold_id] = prefix_features
            prefix_time = pd.to_datetime(prefix_frames[fold_id]["time"], errors="raise")
            prefix_train = ((prefix_time >= pd.Timestamp(train["start"])) & (prefix_time <= pd.Timestamp(train["end"]))).to_numpy()
            prefix_threshold = calibrate_price_level_selector(prefix_features[0], prefix_train)
            calibration_cache[profile][fold_id] = (threshold, cutoffs, prefix_threshold)
    results = []
    for configuration in price_level_configurations():
        executable_id = price_level_executable(configuration).identity
        results.append(
            _evaluate_configuration(
                calibrations=calibration_cache[configuration.profile],
                frame=frame,
                features=feature_cache[configuration.profile],
                folds=folds,
                configuration=configuration,
                effective_spread=effective_spread,
                prefix_features=prefix_cache[configuration.profile],
                prefix_spreads=prefix_spreads,
                time=time,
                executable_id=executable_id,
            )
        )
    pvalues = _selection_adjusted_pvalues(results, total_exposures=SELECTION_TOTAL_EXPOSURES)
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = pvalues[result.executable_id]
    _populate_controls(results)
    surface = {
        "claim_limits": _claim_limits() + ["price_levels_exclude_the_current_bar", "selector_uses_train_only_nonzero_penetrations"],
        "dataset_sha256": DATASET_SHA256,
        "engine_environment": {"numpy": np.__version__, "pandas": pd.__version__, "python": ".".join(str(value) for value in sys.version_info[:3]), "scipy": scipy.__version__},
        "evaluations": [
            {
                "direction_metrics": result.direction_metrics,
                "evaluable": all(result.metrics[name] == 0 for name in ("unknown_cost_unresolved_signal_count", "causality_violation_count", "nonfinite_metric_count", "prefix_invariance_mismatch_count", "append_invariance_mismatch_count")),
                "fold_metrics": result.fold_metrics,
                "metrics": dict(sorted(result.metrics.items())),
                "regime_metrics": result.regime_metrics,
                "session_metrics": result.session_metrics,
                "subject_configuration_id": result.configuration.configuration_id,
                "subject_executable_id": result.executable_id,
            }
            for result in results
        ],
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "price_level_implementation_sha256": price_level_implementation_sha256(),
        "schema": "price_level_discovery_surface.v1",
        "selection_context": [
            {"configuration_id": result.configuration.configuration_id, "executable_id": result.executable_id, "net_profit_micropoints": result.metrics["net_profit_micropoints"], "selection_aware_pvalue_ppm": result.metrics["selection_aware_pvalue_ppm"]}
            for result in results
        ],
        "selection_method": _selection_method(SELECTION_TOTAL_EXPOSURES),
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
    }
    canonical_bytes(surface)
    return surface


def project_price_level_evaluation(
    surface: Mapping[str, Any], *, job_execution: Mapping[str, str], subject_executable_id: str, surface_artifact_hash: str, surface_manifest_hash: str
) -> dict[str, Any]:
    value = dict(surface)
    if sha256(canonical_bytes(value)).hexdigest() != surface_artifact_hash:
        raise DiscoveryBoundaryError("price-level surface bytes differ from artifact hash")
    if value.get("schema") != "price_level_discovery_surface.v1":
        raise DiscoveryBoundaryError("price-level surface schema is invalid")
    expected = executable_configuration_map()
    evaluations = value.get("evaluations")
    if not isinstance(evaluations, list) or len(evaluations) != len(expected):
        raise DiscoveryBoundaryError("price-level surface evaluation count is invalid")
    by_identity = {item.get("subject_executable_id"): item for item in evaluations if isinstance(item, Mapping)}
    if set(by_identity) != set(expected) or subject_executable_id not in expected:
        raise DiscoveryBoundaryError("price-level surface subjects differ from registration")
    execution_payload = {name: job_execution[name] for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")}
    if job_execution.get("identity") != canonical_digest(domain="running-job-execution", payload=execution_payload):
        raise DiscoveryBoundaryError("price-level Job execution identity is invalid")
    evaluation = {
        **dict(by_identity[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "price_level_interaction_evaluation.v1",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(evaluation)
    return evaluation


__all__ = [
    "PriceLevelConfiguration",
    "SELECTION_TOTAL_EXPOSURES",
    "compute_price_level_score",
    "compute_registered_price_level_surface",
    "executable_configuration_map",
    "price_level_components",
    "price_level_configurations",
    "price_level_executable",
    "price_level_implementation_sha256",
    "project_price_level_evaluation",
]
