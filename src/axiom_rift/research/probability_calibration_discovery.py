"""Validation-only probability calibration of a fixed event-label score."""

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


SELECTION_TOTAL_EXPOSURES = 516
_PROFILES = ("validation_platt_probability_edge", "raw_score_control")
_THIS_FILE = Path(__file__).resolve()


def probability_calibration_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def loader_implementation_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class ProbabilityCalibrationConfiguration:
    profile: str
    signal_sign: int
    holding_bars: int = HORIZON

    def __post_init__(self) -> None:
        if (
            self.profile not in _PROFILES
            or self.signal_sign not in {-1, 1}
            or self.holding_bars != HORIZON
        ):
            raise ValueError("probability-calibration configuration invalid")

    @property
    def configuration_id(self) -> str:
        direction = "direct" if self.signal_sign == 1 else "inverse"
        return f"{self.profile}-{direction}-h{HORIZON}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "calibration_profile": self.profile,
            "holding_bars": HORIZON,
            "selector_quantile_bp": 8500,
            "signal_sign": self.signal_sign,
        }


def probability_calibration_configurations() -> tuple[
    ProbabilityCalibrationConfiguration, ...
]:
    return tuple(
        ProbabilityCalibrationConfiguration(profile=profile, signal_sign=sign)
        for profile in _PROFILES
        for sign in (1, -1)
    )


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.probability_calibration_discovery.{name}"
        f"@sha256:{probability_calibration_implementation_sha256()}"
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


def probability_calibration_components() -> tuple[ComponentSpec, ...]:
    return (
        ComponentSpec(
            display_name="fixed STU-0065 first-passage ridge score",
            protocol="model.fixed_first_passage_ridge_score.v1",
            implementation=_label("fit_fold_model"),
            spec={
                "feature_label_and_capacity_fixed": True,
                "source_study": "STU-0065",
            },
        ),
        ComponentSpec(
            display_name="validation-only Platt probability edge or raw control",
            protocol="calibration.validation_platt_vs_raw.v1",
            implementation=_local("fit_platt"),
            spec={
                "fit_role": "validation_oos_only",
                "future_label_end_inside_calibration": True,
                "parameter_fields": ["calibration_profile"],
                "profiles": list(_PROFILES),
                "probability_edge": "two_p_minus_one",
            },
        ),
        ComponentSpec(
            display_name="fixed fold isolated absolute score selector",
            protocol="selector.fixed_abs_quantile_85.v1",
            implementation=_label("calibrate_selector"),
            spec={
                "fit_role": "train_is_only",
                "quantile_basis_points": 8500,
                "same_across_profiles": True,
            },
        ),
        ComponentSpec(
            display_name="completed-bar next-open directional entry",
            protocol="trade.completed_bar_next_open_direction.v5",
            implementation=_shared("simulate_fixed_hold"),
            spec={"entry_time": "next_exact_bar_open", "same_across_profiles": True},
        ),
        ComponentSpec(
            display_name="fixed 48-bar nonoverlap lifecycle",
            protocol="lifecycle.fixed_hold_no_overlap.v5",
            implementation=_shared("simulate_fixed_hold"),
            spec={"holding_bars": HORIZON, "same_across_profiles": True},
        ),
        ComponentSpec(
            display_name="fixed one-lot risk",
            protocol="risk.fixed_one_lot.v3",
            implementation=_shared("simulate_fixed_hold"),
            spec={"lot": 1, "same_across_profiles": True},
        ),
        ComponentSpec(
            display_name="FPMarkets bid-bar spread execution",
            protocol="execution.fpmarkets_bid_bar_spread.v5",
            implementation=_shared("execution_pnl"),
            spec={"point": "0.01", "stress": "half_effective_spread_each_side"},
        ),
    )


def probability_calibration_executable(
    configuration: ProbabilityCalibrationConfiguration,
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"probability calibration {configuration.configuration_id}",
        components=probability_calibration_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development"
        ),
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v5",
        cost_contract=(
            "cost:bid_bar_spread_point_0_01_causal_zero_repair_"
            "half_spread_stress_v5"
        ),
        engine_contract=(
            f"engine:probability_calibration_v1:"
            f"python{'.'.join(str(v) for v in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"implementation_{probability_calibration_implementation_sha256()}:"
            f"label_{event_label_implementation_sha256()}:"
            f"loader_{loader_implementation_sha256()}:"
            f"shared_{discovery_implementation_sha256()}:"
            f"bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:"
            f"bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def executable_configuration_map() -> dict[
    str, ProbabilityCalibrationConfiguration
]:
    return {
        probability_calibration_executable(configuration).identity: configuration
        for configuration in probability_calibration_configurations()
    }


def _sigmoid(value: np.ndarray) -> np.ndarray:
    clipped = np.clip(value, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _fit_platt(
    score: np.ndarray,
    label: np.ndarray,
    calibration_mask: np.ndarray,
) -> tuple[float, float, float, float]:
    mask = (
        calibration_mask
        & np.isfinite(score)
        & np.isfinite(label)
        & (label != 0)
    )
    if int(mask.sum()) < 500:
        raise DiscoveryBoundaryError("Platt calibration set is too small")
    x = score[mask]
    y = (label[mask] > 0).astype(float)
    mean = float(x.mean())
    std = float(x.std(ddof=0))
    if not np.isfinite(std) or std <= 0:
        raise DiscoveryBoundaryError("Platt calibration score is degenerate")
    z = (x - mean) / std
    design = np.column_stack((np.ones(len(z)), z))
    beta = np.zeros(2, dtype=float)
    penalty = np.diag([0.0, 1e-3])
    for _ in range(50):
        probability = _sigmoid(design @ beta)
        gradient = design.T @ (probability - y) + penalty @ beta
        weight = np.maximum(probability * (1.0 - probability), 1e-8)
        hessian = design.T @ (design * weight[:, None]) + penalty
        step = np.linalg.solve(hessian, gradient)
        beta -= step
        if float(np.max(np.abs(step))) < 1e-10:
            break
    if not np.isfinite(beta).all():
        raise DiscoveryBoundaryError("Platt calibration is nonfinite")
    return mean, std, float(beta[0]), float(beta[1])


def _calibrated_score(
    score: np.ndarray,
    calibration: tuple[float, float, float, float],
    profile: str,
) -> np.ndarray:
    if profile == "raw_score_control":
        return np.array(score, dtype=float, copy=True)
    if profile != "validation_platt_probability_edge":
        raise DiscoveryBoundaryError("probability-calibration profile is invalid")
    mean, std, intercept, slope = calibration
    result = np.full(len(score), np.nan)
    valid = np.isfinite(score)
    probability = _sigmoid(intercept + slope * ((score[valid] - mean) / std))
    result[valid] = 2.0 * probability - 1.0
    return result


def _matched(results: list[Any], profile: str, signal_sign: int) -> Any:
    found = [
        result
        for result in results
        if result.configuration.profile == profile
        and result.configuration.signal_sign == signal_sign
    ]
    if len(found) != 1:
        raise DiscoveryBoundaryError("probability-calibration control is not unique")
    return found[0]


def _populate_controls(results: list[Any]) -> None:
    for subject in results:
        configuration = subject.configuration
        opposite = _matched(results, configuration.profile, -configuration.signal_sign)
        control_profile = next(
            profile for profile in _PROFILES if profile != configuration.profile
        )
        calibration_control = _matched(
            results, control_profile, configuration.signal_sign
        )
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
            - calibration_control.metrics["net_profit_micropoints"]
        )
        subject.metrics["feature_control_worst_pvalue_upper_ppm"] = (
            _paired_control_pvalue(
                subject,
                calibration_control,
                role="raw_score_calibration_control",
                total_exposures=SELECTION_TOTAL_EXPOSURES,
            )
        )


def compute_registered_probability_calibration_surface(
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
    labels = _labels(frame, full_volatility, full_run)["first_passage_label_48"]
    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_raw: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        end = int(
            time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]), side="right")
        )
        prefix = frame.iloc[:end]
        prefix_frames[fold_id] = prefix
        prefix_raw[fold_id] = _raw_features(prefix)
        prefix_spreads[fold_id] = causal_effective_spread(
            prefix["spread"].to_numpy(float), _time_ns(prefix)
        )
    fold_sets: dict[
        str, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]
    ] = {profile: {} for profile in _PROFILES}
    prefix_sets: dict[
        str, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]
    ] = {profile: {} for profile in _PROFILES}
    calibrations: dict[
        str, dict[str, tuple[float, tuple[float, float], float]]
    ] = {profile: {} for profile in _PROFILES}
    future_time = time.shift(-(HORIZON + 1))
    for fold in folds:
        fold_id = str(fold["fold_id"])
        train = fold["train_is"]
        validation = fold["validation_oos"]
        train_start = pd.Timestamp(train["start"])
        train_end = pd.Timestamp(train["end"])
        validation_start = pd.Timestamp(validation["start"])
        validation_end = pd.Timestamp(validation["end"])
        selector_mask = ((time >= train_start) & (time <= train_end)).to_numpy()
        model_mask = selector_mask.copy()
        model_mask &= (future_time <= train_end).fillna(False).to_numpy()
        validation_mask = (
            (time >= validation_start)
            & (time <= validation_end)
            & (future_time <= validation_end).fillna(False)
        ).to_numpy()
        model = _fit_model(
            features=full_features,
            label=labels,
            train_mask=model_mask,
        )
        raw_score = _score(full_features, model)
        platt = _fit_platt(raw_score, labels, validation_mask)
        prefix_score = _score(prefix_raw[fold_id][0], model)
        prefix_time = pd.to_datetime(prefix_frames[fold_id]["time"], errors="raise")
        prefix_selector = (
            (prefix_time >= train_start) & (prefix_time <= train_end)
        ).to_numpy()
        volatility_values = full_volatility[
            selector_mask & np.isfinite(full_volatility)
        ]
        cutoffs = (
            float(np.quantile(volatility_values, 1 / 3, method="higher")),
            float(np.quantile(volatility_values, 2 / 3, method="higher")),
        )
        for profile in _PROFILES:
            score = _calibrated_score(raw_score, platt, profile)
            prefix_value = _calibrated_score(prefix_score, platt, profile)
            threshold = calibrate_selector(score, selector_mask)
            prefix_threshold = calibrate_selector(prefix_value, prefix_selector)
            if threshold != prefix_threshold:
                raise DiscoveryBoundaryError("calibration selector threshold drifted")
            fold_sets[profile][fold_id] = (score, full_volatility, full_run)
            prefix_sets[profile][fold_id] = (
                prefix_value,
                prefix_raw[fold_id][1],
                prefix_raw[fold_id][2],
            )
            calibrations[profile][fold_id] = (
                threshold,
                cutoffs,
                prefix_threshold,
            )
    results = []
    for configuration in probability_calibration_configurations():
        first = fold_sets[configuration.profile][str(folds[0]["fold_id"])]
        results.append(
            _evaluate_configuration(
                calibrations=calibrations[configuration.profile],
                frame=frame,
                features=first,
                fold_features=fold_sets[configuration.profile],
                folds=folds,
                configuration=configuration,
                effective_spread=spread,
                prefix_features=prefix_sets[configuration.profile],
                prefix_spreads=prefix_spreads,
                time=time,
                executable_id=probability_calibration_executable(
                    configuration
                ).identity,
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
            "calibration_is_the_only_primary_changed_research_layer",
            "Platt_fit_uses_validation_rows_with_future_end_inside_validation",
            "first_passage_feature_label_model_selector_trade_and_lifecycle_are_fixed",
            "validation_Platt_probability_edge_and_raw_score_only",
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
        "probability_calibration_implementation_sha256": (
            probability_calibration_implementation_sha256()
        ),
        "schema": "probability_calibration_surface.v1",
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


def project_probability_calibration_evaluation(
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
        or value.get("schema") != "probability_calibration_surface.v1"
    ):
        raise DiscoveryBoundaryError("probability-calibration surface invalid")
    expected = executable_configuration_map()
    by_executable = {
        item.get("subject_executable_id"): item for item in value["evaluations"]
    }
    if set(by_executable) != set(expected) or subject_executable_id not in expected:
        raise DiscoveryBoundaryError("probability-calibration subjects differ")
    payload = {
        name: job_execution[name]
        for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")
    }
    if job_execution.get("identity") != canonical_digest(
        domain="running-job-execution", payload=payload
    ):
        raise DiscoveryBoundaryError("probability-calibration Job invalid")
    result = {
        **dict(by_executable[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "probability_calibration_evaluation.v1",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(result)
    return result


__all__ = [
    "ProbabilityCalibrationConfiguration",
    "compute_registered_probability_calibration_surface",
    "executable_configuration_map",
    "loader_implementation_sha256",
    "probability_calibration_configurations",
    "probability_calibration_executable",
    "probability_calibration_implementation_sha256",
    "project_probability_calibration_evaluation",
]
