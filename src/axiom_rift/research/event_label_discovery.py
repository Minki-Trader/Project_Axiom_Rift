"""Fold-trained path-event label discovery under a fixed trading chassis."""

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
from axiom_rift.research import data as data_module
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    SELECTION_BOOTSTRAP_SAMPLES,
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


SELECTION_TOTAL_EXPOSURES = 508
SELECTOR_QUANTILE_BP = 8_500
HORIZON = 48
BARRIER_MULTIPLE_MILLI = 750
RIDGE_PENALTY_MILLI = 1_000
_PROFILES = ("first_passage_label_48", "terminal_return_label_control_48")
_THIS_FILE = Path(__file__).resolve()


def event_label_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def loader_implementation_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class EventLabelConfiguration:
    profile: str
    signal_sign: int
    holding_bars: int = HORIZON

    def __post_init__(self) -> None:
        if (
            self.profile not in _PROFILES
            or self.signal_sign not in {-1, 1}
            or self.holding_bars != HORIZON
        ):
            raise ValueError("event-label configuration invalid")

    @property
    def configuration_id(self) -> str:
        direction = "direct" if self.signal_sign == 1 else "inverse"
        return f"{self.profile}-{direction}-h{HORIZON}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "barrier_multiple_milli": BARRIER_MULTIPLE_MILLI,
            "holding_bars": HORIZON,
            "label_profile": self.profile,
            "ridge_penalty_milli": RIDGE_PENALTY_MILLI,
            "selector_quantile_bp": SELECTOR_QUANTILE_BP,
            "signal_sign": self.signal_sign,
        }


def event_label_configurations() -> tuple[EventLabelConfiguration, ...]:
    return tuple(
        EventLabelConfiguration(profile=profile, signal_sign=sign)
        for profile in _PROFILES
        for sign in (1, -1)
    )


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.event_label_discovery.{name}"
        f"@sha256:{event_label_implementation_sha256()}"
    )


def _shared(name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{name}"
        f"@sha256:{discovery_implementation_sha256()}"
    )


def event_label_components() -> tuple[ComponentSpec, ...]:
    return (
        ComponentSpec(
            display_name="completed-bar fixed multiscale predictor inputs",
            protocol="feature.fixed_multiscale_return_path.v1",
            implementation=_local("raw_features"),
            spec={
                "availability": "completed_bar_only",
                "fields": [
                    "normalized_return_12",
                    "normalized_return_48",
                    "normalized_return_192",
                    "path_efficiency_48",
                    "volatility_ratio_48_192",
                ],
                "same_across_label_profiles": True,
            },
        ),
        ComponentSpec(
            display_name="first-passage or terminal-return training label",
            protocol="label.path_event_vs_terminal_return.v1",
            implementation=_local("build_labels"),
            spec={
                "barrier_multiple_milli": BARRIER_MULTIPLE_MILLI,
                "future_end_must_be_inside_train": True,
                "horizon_bars": HORIZON,
                "parameter_fields": ["label_profile"],
                "profiles": list(_PROFILES),
            },
        ),
        ComponentSpec(
            display_name="fold-trained fixed ridge linear score",
            protocol="model.fold_train_ridge_linear.v1",
            implementation=_local("fit_fold_model"),
            spec={
                "fit_role": "train_is_only",
                "penalty_milli": RIDGE_PENALTY_MILLI,
                "same_capacity_across_label_profiles": True,
                "standardization": "train_mean_population_std",
            },
        ),
        ComponentSpec(
            display_name="fold isolated absolute score selector",
            protocol="selector.fold_train_abs_quantile.v3",
            implementation=_local("calibrate_selector"),
            spec={
                "calibration_role": "train_is_only",
                "minimum_train_observations": 1000,
                "quantile_basis_points": SELECTOR_QUANTILE_BP,
                "quantile_method": "higher",
            },
        ),
        ComponentSpec(
            display_name="completed-bar next-open directional entry",
            protocol="trade.completed_bar_next_open_direction.v3",
            implementation=_shared("simulate_fixed_hold"),
            spec={
                "decision_time": "bar_open_plus_5m",
                "direction": "signal_sign_times_score_sign",
                "entry_time": "next_exact_bar_open",
                "parameter_fields": ["signal_sign"],
            },
        ),
        ComponentSpec(
            display_name="fixed 48-bar nonoverlap lifecycle",
            protocol="lifecycle.fixed_hold_no_overlap.v3",
            implementation=_shared("simulate_fixed_hold"),
            spec={
                "entry_overlap": "reject_while_position_slot_is_occupied",
                "exit_surface": "exact_bar_open_after_48_bars",
                "gap_action": "exclude_path",
            },
        ),
        ComponentSpec(
            display_name="FPMarkets bid-bar spread execution",
            protocol="execution.fpmarkets_bid_bar_spread.v3",
            implementation=_shared("execution_pnl"),
            spec={"point": "0.01", "stress": "half_effective_spread_each_side"},
        ),
        ComponentSpec(
            display_name="fixed one-lot risk",
            protocol="risk.fixed_one_lot.v2",
            implementation=_shared("simulate_fixed_hold"),
            spec={"dynamic_sizing": False, "lot": 1, "positions_per_sleeve": 1},
        ),
    )


def event_label_executable(configuration: EventLabelConfiguration) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"event label {configuration.configuration_id}",
        components=event_label_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development"
        ),
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v3",
        cost_contract=(
            "cost:bid_bar_spread_point_0_01_causal_zero_repair_"
            "half_spread_stress_v3"
        ),
        engine_contract=(
            f"engine:event_label_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"implementation_{event_label_implementation_sha256()}:"
            f"loader_{loader_implementation_sha256()}:"
            f"shared_{discovery_implementation_sha256()}:"
            f"bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:"
            f"bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def executable_configuration_map() -> dict[str, EventLabelConfiguration]:
    return {
        event_label_executable(configuration).identity: configuration
        for configuration in event_label_configurations()
    }


def _raw_features(
    frame: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    close = frame["close"].to_numpy(float)
    log_close = np.log(close)
    returns = np.full(len(frame), np.nan)
    returns[1:] = np.diff(log_close)
    series = pd.Series(returns)
    vol192 = series.rolling(192, min_periods=192).std(ddof=1).to_numpy(float)
    vol48 = series.rolling(48, min_periods=48).std(ddof=1).to_numpy(float)
    columns: list[np.ndarray] = []
    for period in (12, 48, 192):
        change = np.full(len(frame), np.nan)
        change[period:] = log_close[period:] - log_close[:-period]
        columns.append(
            np.divide(
                change,
                vol192 * np.sqrt(period),
                out=np.full(len(frame), np.nan),
                where=np.isfinite(vol192) & (vol192 > 0),
            )
        )
    endpoint = np.full(len(frame), np.nan)
    endpoint[48:] = log_close[48:] - log_close[:-48]
    path = series.abs().rolling(48, min_periods=48).sum().to_numpy(float)
    columns.append(
        np.divide(
            endpoint,
            path,
            out=np.full(len(frame), np.nan),
            where=np.isfinite(path) & (path > 0),
        )
    )
    columns.append(
        np.divide(
            vol48,
            vol192,
            out=np.full(len(frame), np.nan),
            where=np.isfinite(vol192) & (vol192 > 0),
        )
        - 1.0
    )
    run = _consecutive_run(_time_ns(frame))
    values = np.column_stack(columns)
    values[run < 193] = np.nan
    return values, vol192, run


def _labels(
    frame: pd.DataFrame,
    volatility: np.ndarray,
    run: np.ndarray,
) -> dict[str, np.ndarray]:
    count = len(frame)
    log_open = np.log(frame["open"].to_numpy(float))
    terminal = np.full(count, np.nan)
    first_passage = np.full(count, np.nan)
    last = count - HORIZON - 1
    if last <= 0:
        return {
            "first_passage_label_48": first_passage,
            "terminal_return_label_control_48": terminal,
        }
    indices = np.arange(last)
    continuous = run[indices + HORIZON + 1] >= HORIZON + 2
    finite = continuous & np.isfinite(volatility[indices]) & (volatility[indices] > 0)
    entry = log_open[indices + 1]
    terminal_return = log_open[indices + HORIZON + 1] - entry
    terminal_values = np.sign(terminal_return)
    terminal[indices[finite]] = terminal_values[finite]
    barrier = (
        volatility[indices]
        * np.sqrt(HORIZON)
        * BARRIER_MULTIPLE_MILLI
        / 1000.0
    )
    decided = np.zeros(last, dtype=bool)
    event_values = np.zeros(last, dtype=float)
    for step in range(2, HORIZON + 2):
        path_return = log_open[indices + step] - entry
        upper = (~decided) & (path_return >= barrier)
        lower = (~decided) & (path_return <= -barrier)
        event_values[upper] = 1.0
        event_values[lower] = -1.0
        decided |= upper | lower
    first_passage[indices[finite]] = event_values[finite]
    return {
        "first_passage_label_48": first_passage,
        "terminal_return_label_control_48": terminal,
    }


def _fit_model(
    *,
    features: np.ndarray,
    label: np.ndarray,
    train_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    mask = train_mask & np.isfinite(label) & np.isfinite(features).all(axis=1)
    if int(mask.sum()) < 1000:
        raise DiscoveryBoundaryError("event-label model training set too small")
    x = features[mask]
    y = label[mask]
    mean = x.mean(axis=0)
    std = x.std(axis=0, ddof=0)
    std = np.where(std > 0, std, 1.0)
    z = (x - mean) / std
    y_mean = float(y.mean())
    penalty = RIDGE_PENALTY_MILLI / 1000.0
    beta = np.linalg.solve(
        z.T @ z + penalty * np.eye(z.shape[1]),
        z.T @ (y - y_mean),
    )
    return mean, std, beta, y_mean


def _score(
    features: np.ndarray,
    model: tuple[np.ndarray, np.ndarray, np.ndarray, float],
) -> np.ndarray:
    mean, std, beta, intercept = model
    result = np.full(len(features), np.nan)
    valid = np.isfinite(features).all(axis=1)
    result[valid] = ((features[valid] - mean) / std) @ beta + intercept
    return result


def calibrate_selector(score: np.ndarray, mask: np.ndarray) -> float:
    values = np.abs(score[mask & np.isfinite(score)])
    if len(values) < 1000:
        raise DiscoveryBoundaryError("event-label selector set too small")
    return float(
        np.quantile(values, SELECTOR_QUANTILE_BP / 10000, method="higher")
    )


def _matched(
    results: list[Any], profile: str, signal_sign: int
) -> Any:
    found = [
        result
        for result in results
        if result.configuration.profile == profile
        and result.configuration.signal_sign == signal_sign
    ]
    if len(found) != 1:
        raise DiscoveryBoundaryError("event-label control is not unique")
    return found[0]


def _populate_controls(results: list[Any]) -> None:
    for subject in results:
        configuration = subject.configuration
        opposite = _matched(results, configuration.profile, -configuration.signal_sign)
        control_profile = next(
            profile for profile in _PROFILES if profile != configuration.profile
        )
        label_control = _matched(results, control_profile, configuration.signal_sign)
        subject.metrics["opposite_sign_worst_delta_net_profit_micropoints"] = (
            subject.metrics["net_profit_micropoints"]
            - opposite.metrics["net_profit_micropoints"]
        )
        subject.metrics["opposite_sign_pvalue_upper_ppm"] = _paired_control_pvalue(
            subject,
            opposite,
            role="opposite_sign",
            total_exposures=SELECTION_TOTAL_EXPOSURES,
        )
        subject.metrics["feature_control_worst_delta_net_profit_micropoints"] = (
            subject.metrics["net_profit_micropoints"]
            - label_control.metrics["net_profit_micropoints"]
        )
        subject.metrics["feature_control_worst_pvalue_upper_ppm"] = (
            _paired_control_pvalue(
                subject,
                label_control,
                role="terminal_return_label_control",
                total_exposures=SELECTION_TOTAL_EXPOSURES,
            )
        )


def compute_registered_event_label_surface(
    repository_root: str | Path,
) -> dict[str, Any]:
    _validate_engine_environment()
    data = load_observed_development(Path(repository_root).resolve())
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = causal_effective_spread(
        frame["spread"].to_numpy(float), _time_ns(frame)
    )
    full_features, full_volatility, full_run = _raw_features(frame)
    labels = _labels(frame, full_volatility, full_run)
    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_features_raw: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        end = int(
            time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]), side="right")
        )
        prefix = frame.iloc[:end]
        prefix_frames[fold_id] = prefix
        prefix_features_raw[fold_id] = _raw_features(prefix)
        prefix_spreads[fold_id] = causal_effective_spread(
            prefix["spread"].to_numpy(float), _time_ns(prefix)
        )
    fold_scores: dict[str, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]] = {
        profile: {} for profile in _PROFILES
    }
    prefix_scores: dict[str, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]] = {
        profile: {} for profile in _PROFILES
    }
    calibrations: dict[
        str, dict[str, tuple[float, tuple[float, float], float]]
    ] = {profile: {} for profile in _PROFILES}
    for profile in _PROFILES:
        for fold in folds:
            fold_id = str(fold["fold_id"])
            train = fold["train_is"]
            start = pd.Timestamp(train["start"])
            end = pd.Timestamp(train["end"])
            selector_mask = ((time >= start) & (time <= end)).to_numpy()
            train_mask = selector_mask.copy()
            future_time = time.shift(-(HORIZON + 1))
            train_mask &= (future_time <= end).fillna(False).to_numpy()
            model = _fit_model(
                features=full_features,
                label=labels[profile],
                train_mask=train_mask,
            )
            score = _score(full_features, model)
            fold_value = (score, full_volatility, full_run)
            fold_scores[profile][fold_id] = fold_value
            prefix_raw = prefix_features_raw[fold_id]
            prefix_score = _score(prefix_raw[0], model)
            prefix_value = (prefix_score, prefix_raw[1], prefix_raw[2])
            prefix_scores[profile][fold_id] = prefix_value
            prefix_time = pd.to_datetime(prefix_frames[fold_id]["time"], errors="raise")
            prefix_train = ((prefix_time >= start) & (prefix_time <= end)).to_numpy()
            volatility_values = full_volatility[
                train_mask & np.isfinite(full_volatility)
            ]
            cutoffs = (
                float(np.quantile(volatility_values, 1 / 3, method="higher")),
                float(np.quantile(volatility_values, 2 / 3, method="higher")),
            )
            calibrations[profile][fold_id] = (
                calibrate_selector(score, selector_mask),
                cutoffs,
                calibrate_selector(prefix_score, prefix_train),
            )
    results = []
    for configuration in event_label_configurations():
        first = fold_scores[configuration.profile][str(folds[0]["fold_id"])]
        results.append(
            _evaluate_configuration(
                calibrations=calibrations[configuration.profile],
                frame=frame,
                features=first,
                fold_features=fold_scores[configuration.profile],
                folds=folds,
                configuration=configuration,
                effective_spread=spread,
                prefix_features=prefix_scores[configuration.profile],
                prefix_spreads=prefix_spreads,
                time=time,
                executable_id=event_label_executable(configuration).identity,
            )
        )
    adjusted = _selection_adjusted_pvalues(
        results, total_exposures=SELECTION_TOTAL_EXPOSURES
    )
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = adjusted[result.executable_id]
    _populate_controls(results)
    surface = {
        "claim_limits": _claim_limits()
        + [
            "label_is_the_only_primary_changed_research_layer",
            "future_label_end_is_inside_each_fold_train_window",
            "first_passage_and_terminal_return_labels_only",
            "fixed_linear_model_selector_entry_lifecycle_risk_and_execution",
            "four_trial_surface",
        ],
        "dataset_sha256": DATASET_SHA256,
        "engine_environment": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "python": ".".join(str(value) for value in sys.version_info[:3]),
            "scipy": scipy.__version__,
        },
        "evaluations": [
            {
                "direction_metrics": result.direction_metrics,
                "evaluable": all(
                    result.metrics[name] == 0
                    for name in (
                        "unknown_cost_unresolved_signal_count",
                        "causality_violation_count",
                        "nonfinite_metric_count",
                        "prefix_invariance_mismatch_count",
                        "append_invariance_mismatch_count",
                    )
                ),
                "fold_metrics": result.fold_metrics,
                "metrics": dict(sorted(result.metrics.items())),
                "regime_metrics": result.regime_metrics,
                "session_metrics": result.session_metrics,
                "subject_configuration_id": result.configuration.configuration_id,
                "subject_executable_id": result.executable_id,
            }
            for result in results
        ],
        "event_label_implementation_sha256": event_label_implementation_sha256(),
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "schema": "event_label_surface.v1",
        "selection_context": [
            {
                "configuration_id": result.configuration.configuration_id,
                "executable_id": result.executable_id,
                "net_profit_micropoints": result.metrics["net_profit_micropoints"],
                "selection_aware_pvalue_ppm": result.metrics[
                    "selection_aware_pvalue_ppm"
                ],
            }
            for result in results
        ],
        "selection_method": _selection_method(SELECTION_TOTAL_EXPOSURES),
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
    }
    canonical_bytes(surface)
    return surface


def project_event_label_evaluation(
    surface: Mapping[str, Any],
    *,
    job_execution: Mapping[str, str],
    subject_executable_id: str,
    surface_artifact_hash: str,
    surface_manifest_hash: str,
) -> dict[str, Any]:
    value = dict(surface)
    if (
        sha256(canonical_bytes(value)).hexdigest() != surface_artifact_hash
        or value.get("schema") != "event_label_surface.v1"
    ):
        raise DiscoveryBoundaryError("event-label surface invalid")
    expected = executable_configuration_map()
    by_executable = {
        item.get("subject_executable_id"): item for item in value["evaluations"]
    }
    if set(by_executable) != set(expected) or subject_executable_id not in expected:
        raise DiscoveryBoundaryError("event-label subjects differ")
    payload = {
        name: job_execution[name]
        for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")
    }
    if job_execution.get("identity") != canonical_digest(
        domain="running-job-execution", payload=payload
    ):
        raise DiscoveryBoundaryError("event-label Job invalid")
    result = {
        **dict(by_executable[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "event_label_evaluation.v1",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(result)
    return result


__all__ = [
    "BARRIER_MULTIPLE_MILLI",
    "EventLabelConfiguration",
    "event_label_configurations",
    "event_label_executable",
    "event_label_implementation_sha256",
    "compute_registered_event_label_surface",
    "executable_configuration_map",
    "loader_implementation_sha256",
    "project_event_label_evaluation",
]
