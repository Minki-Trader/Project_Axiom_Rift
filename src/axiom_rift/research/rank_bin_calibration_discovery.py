"""Validation-only monotone rank-bin calibration of a fixed score."""

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
from axiom_rift.research.event_label_discovery import (
    HORIZON,
    _fit_model,
    _labels,
    _raw_features,
    _score,
    calibrate_selector,
    event_label_implementation_sha256,
)


SELECTION_TOTAL_EXPOSURES = 520
BIN_COUNT = 7
_PROFILES = ("validation_isotonic_rank_bin_edge", "raw_score_control")
_THIS_FILE = Path(__file__).resolve()


def rank_bin_calibration_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def loader_implementation_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class RankBinCalibrationConfiguration:
    profile: str
    signal_sign: int
    holding_bars: int = HORIZON

    def __post_init__(self) -> None:
        if (
            self.profile not in _PROFILES
            or self.signal_sign not in {-1, 1}
            or self.holding_bars != HORIZON
        ):
            raise ValueError("rank-bin calibration configuration invalid")

    @property
    def configuration_id(self) -> str:
        direction = "direct" if self.signal_sign == 1 else "inverse"
        return f"{self.profile}-{direction}-h{HORIZON}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "bin_count": BIN_COUNT,
            "calibration_profile": self.profile,
            "holding_bars": HORIZON,
            "selector_quantile_bp": 8500,
            "signal_sign": self.signal_sign,
        }


def rank_bin_calibration_configurations() -> tuple[
    RankBinCalibrationConfiguration, ...
]:
    return tuple(
        RankBinCalibrationConfiguration(profile=profile, signal_sign=sign)
        for profile in _PROFILES
        for sign in (1, -1)
    )


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.rank_bin_calibration_discovery.{name}"
        f"@sha256:{rank_bin_calibration_implementation_sha256()}"
    )


def _label(name: str) -> str:
    return (
        f"axiom_rift.research.event_label_discovery.{name}"
        f"@sha256:{event_label_implementation_sha256()}"
    )


def _shared(name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{name}"
        f"@sha256:{discovery_implementation_sha256()}"
    )


def rank_bin_calibration_components() -> tuple[ComponentSpec, ...]:
    return (
        ComponentSpec(
            display_name="fixed STU-0065 first-passage ridge score",
            protocol="model.fixed_first_passage_ridge_score.v2",
            implementation=_label("fit_fold_model"),
            spec={"feature_label_and_capacity_fixed": True, "source_study": "STU-0065"},
        ),
        ComponentSpec(
            display_name="validation monotone rank-bin probability edge or raw control",
            protocol="calibration.validation_isotonic_rank_bin_vs_raw.v1",
            implementation=_local("fit_rank_bins"),
            spec={
                "bin_count": BIN_COUNT,
                "fit_role": "validation_oos_only",
                "future_label_end_inside_calibration": True,
                "laplace_prior_each_class": 2,
                "monotonicity": "weighted_pava",
                "parameter_fields": ["calibration_profile"],
                "profiles": list(_PROFILES),
            },
        ),
        ComponentSpec(
            display_name="fixed fold isolated absolute score selector",
            protocol="selector.fixed_abs_quantile_85.v2",
            implementation=_label("calibrate_selector"),
            spec={"fit_role": "train_is_only", "quantile_basis_points": 8500},
        ),
        ComponentSpec(
            display_name="completed-bar next-open directional entry",
            protocol="trade.completed_bar_next_open_direction.v6",
            implementation=_shared("simulate_fixed_hold"),
            spec={"entry_time": "next_exact_bar_open", "same_across_profiles": True},
        ),
        ComponentSpec(
            display_name="fixed 48-bar nonoverlap lifecycle",
            protocol="lifecycle.fixed_hold_no_overlap.v6",
            implementation=_shared("simulate_fixed_hold"),
            spec={"holding_bars": HORIZON, "same_across_profiles": True},
        ),
        ComponentSpec(
            display_name="fixed one-lot risk",
            protocol="risk.fixed_one_lot.v4",
            implementation=_shared("simulate_fixed_hold"),
            spec={"lot": 1, "same_across_profiles": True},
        ),
        ComponentSpec(
            display_name="FPMarkets completed-period spread proxy execution",
            protocol="execution.fpmarkets_completed_bar_spread_proxy.v6",
            implementation=_shared("execution_pnl"),
            spec={"point": "0.01", "stress": "half_effective_spread_each_side"},
        ),
    )


def rank_bin_calibration_executable(
    configuration: RankBinCalibrationConfiguration,
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"rank-bin calibration {configuration.configuration_id}",
        components=rank_bin_calibration_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v6",
        cost_contract="cost:fpmarkets_completed_bar_spread_proxy_point_0_01_causal_zero_repair_half_spread_stress_v6",
        engine_contract=(
            f"engine:rank_bin_calibration_v1:"
            f"python{'.'.join(str(value) for value in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"implementation_{rank_bin_calibration_implementation_sha256()}:"
            f"label_{event_label_implementation_sha256()}:"
            f"loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:"
            f"bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:"
            f"bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def executable_configuration_map() -> dict[str, RankBinCalibrationConfiguration]:
    return {
        rank_bin_calibration_executable(configuration).identity: configuration
        for configuration in rank_bin_calibration_configurations()
    }


def _pava(probabilities: np.ndarray, weights: np.ndarray) -> np.ndarray:
    blocks: list[tuple[int, int, float, float]] = []
    for index, (probability, weight) in enumerate(zip(probabilities, weights, strict=True)):
        blocks.append((index, index + 1, float(probability * weight), float(weight)))
        while len(blocks) >= 2:
            left = blocks[-2]
            right = blocks[-1]
            if left[2] / left[3] <= right[2] / right[3]:
                break
            blocks[-2:] = [(left[0], right[1], left[2] + right[2], left[3] + right[3])]
    result = np.empty(len(probabilities), dtype=float)
    for start, end, total, weight in blocks:
        result[start:end] = total / weight
    return result


def _fit_rank_bins(
    score: np.ndarray,
    label: np.ndarray,
    calibration_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    mask = calibration_mask & np.isfinite(score) & np.isfinite(label) & (label != 0)
    if int(mask.sum()) < 700:
        raise DiscoveryBoundaryError("rank-bin calibration set is too small")
    x = score[mask]
    y = (label[mask] > 0).astype(float)
    edges = np.array(
        [np.quantile(x, index / BIN_COUNT, method="higher") for index in range(1, BIN_COUNT)],
        dtype=float,
    )
    if np.any(~np.isfinite(edges)) or np.any(np.diff(edges) <= 0):
        raise DiscoveryBoundaryError("rank-bin calibration edges are degenerate")
    bins = np.searchsorted(edges, x, side="right")
    counts = np.bincount(bins, minlength=BIN_COUNT).astype(float)
    positives = np.bincount(bins, weights=y, minlength=BIN_COUNT).astype(float)
    probabilities = (positives + 2.0) / (counts + 4.0)
    monotone = _pava(probabilities, counts + 4.0)
    return edges, 2.0 * monotone - 1.0


def _rank_bin_score(
    score: np.ndarray,
    calibration: tuple[np.ndarray, np.ndarray],
    profile: str,
) -> np.ndarray:
    if profile == "raw_score_control":
        return np.array(score, dtype=float, copy=True)
    if profile != "validation_isotonic_rank_bin_edge":
        raise DiscoveryBoundaryError("rank-bin calibration profile is invalid")
    edges, values = calibration
    result = np.full(len(score), np.nan)
    valid = np.isfinite(score)
    result[valid] = values[np.searchsorted(edges, score[valid], side="right")]
    return result


def _matched(results: list[Any], profile: str, signal_sign: int) -> Any:
    found = [
        result
        for result in results
        if result.configuration.profile == profile
        and result.configuration.signal_sign == signal_sign
    ]
    if len(found) != 1:
        raise DiscoveryBoundaryError("rank-bin calibration control is not unique")
    return found[0]


def _populate_controls(results: list[Any]) -> None:
    for subject in results:
        configuration = subject.configuration
        opposite = _matched(results, configuration.profile, -configuration.signal_sign)
        control_profile = next(profile for profile in _PROFILES if profile != configuration.profile)
        calibration_control = _matched(results, control_profile, configuration.signal_sign)
        subject.metrics["opposite_sign_worst_delta_net_profit_micropoints"] = subject.metrics["net_profit_micropoints"] - opposite.metrics["net_profit_micropoints"]
        subject.metrics["opposite_sign_pvalue_upper_ppm"] = _paired_control_pvalue(subject, opposite, role="opposite_sign", total_exposures=SELECTION_TOTAL_EXPOSURES)
        subject.metrics["feature_control_worst_delta_net_profit_micropoints"] = subject.metrics["net_profit_micropoints"] - calibration_control.metrics["net_profit_micropoints"]
        subject.metrics["feature_control_worst_pvalue_upper_ppm"] = _paired_control_pvalue(subject, calibration_control, role="raw_score_calibration_control", total_exposures=SELECTION_TOTAL_EXPOSURES)


def compute_registered_rank_bin_calibration_surface(repository_root: str | Path) -> dict[str, Any]:
    _validate_engine_environment()
    data = load_observed_development(Path(repository_root).resolve())
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = causal_effective_spread(frame["spread"].to_numpy(float), _time_ns(frame))
    full_features, full_volatility, full_run = _raw_features(frame)
    labels = _labels(frame, full_volatility, full_run)["first_passage_label_48"]
    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_raw: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        end = int(time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]), side="right"))
        prefix = frame.iloc[:end]
        prefix_frames[fold_id] = prefix
        prefix_raw[fold_id] = _raw_features(prefix)
        prefix_spreads[fold_id] = causal_effective_spread(prefix["spread"].to_numpy(float), _time_ns(prefix))
    fold_sets = {profile: {} for profile in _PROFILES}
    prefix_sets = {profile: {} for profile in _PROFILES}
    calibrations = {profile: {} for profile in _PROFILES}
    future_time = time.shift(-(HORIZON + 1))
    for fold in folds:
        fold_id = str(fold["fold_id"])
        train = fold["train_is"]
        validation = fold["validation_oos"]
        train_start, train_end = pd.Timestamp(train["start"]), pd.Timestamp(train["end"])
        validation_start, validation_end = pd.Timestamp(validation["start"]), pd.Timestamp(validation["end"])
        selector_mask = ((time >= train_start) & (time <= train_end)).to_numpy()
        model_mask = selector_mask & (future_time <= train_end).fillna(False).to_numpy()
        validation_mask = ((time >= validation_start) & (time <= validation_end) & (future_time <= validation_end).fillna(False)).to_numpy()
        model = _fit_model(features=full_features, label=labels, train_mask=model_mask)
        raw_score = _score(full_features, model)
        rank_bins = _fit_rank_bins(raw_score, labels, validation_mask)
        prefix_score = _score(prefix_raw[fold_id][0], model)
        prefix_time = pd.to_datetime(prefix_frames[fold_id]["time"], errors="raise")
        prefix_selector = ((prefix_time >= train_start) & (prefix_time <= train_end)).to_numpy()
        volatility_values = full_volatility[selector_mask & np.isfinite(full_volatility)]
        cutoffs = (
            float(np.quantile(volatility_values, 1 / 3, method="higher")),
            float(np.quantile(volatility_values, 2 / 3, method="higher")),
        )
        for profile in _PROFILES:
            score = _rank_bin_score(raw_score, rank_bins, profile)
            prefix_value = _rank_bin_score(prefix_score, rank_bins, profile)
            threshold = calibrate_selector(score, selector_mask)
            prefix_threshold = calibrate_selector(prefix_value, prefix_selector)
            if threshold != prefix_threshold:
                raise DiscoveryBoundaryError("rank-bin selector threshold drifted")
            fold_sets[profile][fold_id] = (score, full_volatility, full_run)
            prefix_sets[profile][fold_id] = (prefix_value, prefix_raw[fold_id][1], prefix_raw[fold_id][2])
            calibrations[profile][fold_id] = (threshold, cutoffs, prefix_threshold)
    results = []
    for configuration in rank_bin_calibration_configurations():
        first = fold_sets[configuration.profile][str(folds[0]["fold_id"])]
        results.append(_evaluate_configuration(
            calibrations=calibrations[configuration.profile], frame=frame,
            features=first, fold_features=fold_sets[configuration.profile], folds=folds,
            configuration=configuration, effective_spread=spread,
            prefix_features=prefix_sets[configuration.profile], prefix_spreads=prefix_spreads,
            time=time, executable_id=rank_bin_calibration_executable(configuration).identity,
        ))
    adjusted = _selection_adjusted_pvalues(results, total_exposures=SELECTION_TOTAL_EXPOSURES)
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = adjusted[result.executable_id]
    _populate_controls(results)
    surface = {
        "claim_limits": _claim_limits() + [
            "calibration_is_the_only_primary_changed_research_layer",
            "rank_bins_fit_validation_rows_with_future_end_inside_validation",
            "weighted_pava_is_monotone_and_uses_seven_equal_frequency_bins",
            "first_passage_feature_label_model_selector_trade_and_lifecycle_are_fixed",
            "four_trial_surface",
        ],
        "dataset_sha256": DATASET_SHA256,
        "engine_environment": {"numpy": np.__version__, "pandas": pd.__version__, "python": ".".join(str(value) for value in sys.version_info[:3]), "scipy": scipy.__version__},
        "evaluations": [{
            "direction_metrics": result.direction_metrics,
            "evaluable": all(result.metrics[name] == 0 for name in ("unknown_cost_unresolved_signal_count", "causality_violation_count", "nonfinite_metric_count", "prefix_invariance_mismatch_count", "append_invariance_mismatch_count")),
            "fold_metrics": result.fold_metrics,
            "metrics": dict(sorted(result.metrics.items())),
            "regime_metrics": result.regime_metrics,
            "session_metrics": result.session_metrics,
            "subject_configuration_id": result.configuration.configuration_id,
            "subject_executable_id": result.executable_id,
        } for result in results],
        "event_label_implementation_sha256": event_label_implementation_sha256(),
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "rank_bin_calibration_implementation_sha256": rank_bin_calibration_implementation_sha256(),
        "schema": "rank_bin_calibration_surface.v1",
        "selection_context": [{"configuration_id": result.configuration.configuration_id, "executable_id": result.executable_id, "net_profit_micropoints": result.metrics["net_profit_micropoints"], "selection_aware_pvalue_ppm": result.metrics["selection_aware_pvalue_ppm"]} for result in results],
        "selection_method": _selection_method(SELECTION_TOTAL_EXPOSURES),
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
    }
    canonical_bytes(surface)
    return surface


def project_rank_bin_calibration_evaluation(
    surface: Mapping[str, Any], *, job_execution: Mapping[str, str],
    subject_executable_id: str, surface_artifact_hash: str, surface_manifest_hash: str,
) -> dict[str, Any]:
    value = dict(surface)
    if sha256(canonical_bytes(value)).hexdigest() != surface_artifact_hash or value.get("schema") != "rank_bin_calibration_surface.v1":
        raise DiscoveryBoundaryError("rank-bin calibration surface invalid")
    expected = executable_configuration_map()
    by_executable = {item.get("subject_executable_id"): item for item in value["evaluations"]}
    if set(by_executable) != set(expected) or subject_executable_id not in expected:
        raise DiscoveryBoundaryError("rank-bin calibration subjects differ")
    payload = {name: job_execution[name] for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")}
    if job_execution.get("identity") != canonical_digest(domain="running-job-execution", payload=payload):
        raise DiscoveryBoundaryError("rank-bin calibration Job invalid")
    result = {
        **dict(by_executable[subject_executable_id]),
        "claim_limits": value["claim_limits"], "job_execution": dict(job_execution),
        "schema": "rank_bin_calibration_evaluation.v1",
        "selection_context": value["selection_context"], "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"], "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(result)
    return result


__all__ = [
    "BIN_COUNT", "RankBinCalibrationConfiguration", "compute_registered_rank_bin_calibration_surface",
    "executable_configuration_map", "loader_implementation_sha256",
    "project_rank_bin_calibration_evaluation", "rank_bin_calibration_configurations",
    "rank_bin_calibration_executable", "rank_bin_calibration_implementation_sha256",
]
