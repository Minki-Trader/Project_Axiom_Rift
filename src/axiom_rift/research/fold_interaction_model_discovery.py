"""Fold-trained pairwise-interaction ridge model discovery surface."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
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
)
from axiom_rift.research.event_label_discovery import (
    HORIZON,
    _labels,
    _raw_features,
    calibrate_selector,
)
from axiom_rift.research.fold_interaction_model_chassis import (
    SELECTION_TOTAL_EXPOSURES,
    executable_configuration_map,
    fit_model_profile,
    fold_interaction_model_chassis_implementation_sha256,
    fold_interaction_model_configurations,
    fold_interaction_model_executable,
    loader_implementation_sha256,
    model_design,
)


_THIS_FILE = Path(__file__).resolve()


def fold_interaction_model_discovery_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def deterministic_score(
    features: np.ndarray,
    model: tuple[np.ndarray, np.ndarray, np.ndarray, float],
) -> np.ndarray:
    """Project every row with one stable reduction order.

    Matrix multiplication may select a different floating reduction kernel when
    only the number of rows changes.  A row-wise multiply and sum keeps full and
    prefix projections bit-identical without changing the fitted model.
    """

    mean, std, beta, intercept = model
    result = np.full(len(features), np.nan)
    valid = np.isfinite(features).all(axis=1)
    standardized = (features[valid] - mean) / std
    result[valid] = np.sum(
        standardized * beta.reshape(1, -1),
        axis=1,
        dtype=np.float64,
    ) + intercept
    return result


def _matched(results: list[Any], profile: str) -> Any:
    found = [value for value in results if value.configuration.profile == profile]
    if len(found) != 1:
        raise DiscoveryBoundaryError("fold-interaction model control is not unique")
    return found[0]


def _populate_controls(results: list[Any]) -> None:
    for subject in results:
        control_profile = next(
            value
            for value in ("linear_ridge_control", "pairwise_interaction_ridge")
            if value != subject.configuration.profile
        )
        control = _matched(results, control_profile)
        subject.metrics["model_control_delta_net_profit_micropoints"] = (
            subject.metrics["net_profit_micropoints"]
            - control.metrics["net_profit_micropoints"]
        )
        subject.metrics["model_control_pvalue_upper_ppm"] = _paired_control_pvalue(
            subject,
            control,
            role="matched_linear_model_control",
            total_exposures=SELECTION_TOTAL_EXPOSURES,
        )


def compute_registered_fold_interaction_model_surface(
    repository_root: str | Path,
) -> dict[str, Any]:
    _validate_engine_environment()
    data = load_observed_development(Path(repository_root).resolve())
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = causal_effective_spread(frame["spread"].to_numpy(float), _time_ns(frame))
    raw_features, full_volatility, full_run = _raw_features(frame)
    label = _labels(frame, full_volatility, full_run)["first_passage_label_48"]
    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_raw: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        end = int(time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]), side="right"))
        prefix = frame.iloc[:end]
        prefix_frames[fold_id] = prefix
        prefix_raw[fold_id] = _raw_features(prefix)
        prefix_spreads[fold_id] = causal_effective_spread(
            prefix["spread"].to_numpy(float), _time_ns(prefix)
        )
    profiles = tuple(value.profile for value in fold_interaction_model_configurations())
    fold_scores: dict[str, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]] = {
        profile: {} for profile in profiles
    }
    prefix_scores: dict[str, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]] = {
        profile: {} for profile in profiles
    }
    calibrations: dict[str, dict[str, tuple[float, tuple[float, float], float]]] = {
        profile: {} for profile in profiles
    }
    for profile in profiles:
        full_design = model_design(raw_features, profile)
        for fold in folds:
            fold_id = str(fold["fold_id"])
            train = fold["train_is"]
            start = pd.Timestamp(train["start"])
            end = pd.Timestamp(train["end"])
            selector_mask = ((time >= start) & (time <= end)).to_numpy()
            future_time = time.shift(-(HORIZON + 1))
            train_mask = selector_mask & (future_time <= end).fillna(False).to_numpy()
            model = fit_model_profile(
                features=raw_features,
                label=label,
                train_mask=train_mask,
                profile=profile,
            )
            score = deterministic_score(full_design, model)
            fold_scores[profile][fold_id] = (score, full_volatility, full_run)
            raw = prefix_raw[fold_id]
            prefix_design = model_design(raw[0], profile)
            prefix_score = deterministic_score(prefix_design, model)
            prefix_scores[profile][fold_id] = (prefix_score, raw[1], raw[2])
            prefix_time = pd.to_datetime(prefix_frames[fold_id]["time"], errors="raise")
            prefix_train = ((prefix_time >= start) & (prefix_time <= end)).to_numpy()
            volatility_values = full_volatility[train_mask & np.isfinite(full_volatility)]
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
    for configuration in fold_interaction_model_configurations():
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
                executable_id=fold_interaction_model_executable(configuration).identity,
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
            "model_is_the_only_primary_changed_research_layer",
            "first_passage_label_and_48_bar_trade_chassis_are_fixed",
            "pairwise_profile_adds_ten_products_without_squares",
            "two_trial_surface",
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
        "fold_interaction_model_chassis_implementation_sha256": fold_interaction_model_chassis_implementation_sha256(),
        "fold_interaction_model_discovery_implementation_sha256": fold_interaction_model_discovery_implementation_sha256(),
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "schema": "fold_interaction_model_surface.v1",
        "selection_context": [
            {
                "configuration_id": result.configuration.configuration_id,
                "executable_id": result.executable_id,
                "net_profit_micropoints": result.metrics["net_profit_micropoints"],
                "selection_aware_pvalue_ppm": result.metrics["selection_aware_pvalue_ppm"],
            }
            for result in results
        ],
        "selection_method": _selection_method(SELECTION_TOTAL_EXPOSURES),
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
    }
    canonical_bytes(surface)
    return surface


def project_fold_interaction_model_evaluation(
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
        or value.get("schema") != "fold_interaction_model_surface.v1"
    ):
        raise DiscoveryBoundaryError("fold-interaction model surface invalid")
    expected = executable_configuration_map()
    by_executable = {
        item.get("subject_executable_id"): item for item in value["evaluations"]
    }
    if set(by_executable) != set(expected) or subject_executable_id not in expected:
        raise DiscoveryBoundaryError("fold-interaction model subjects differ")
    payload = {
        name: job_execution[name]
        for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")
    }
    if job_execution.get("identity") != canonical_digest(
        domain="running-job-execution", payload=payload
    ):
        raise DiscoveryBoundaryError("fold-interaction model Job invalid")
    result = {
        **dict(by_executable[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "fold_interaction_model_evaluation.v1",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(result)
    return result


__all__ = [
    "compute_registered_fold_interaction_model_surface",
    "deterministic_score",
    "fold_interaction_model_discovery_implementation_sha256",
    "project_fold_interaction_model_evaluation",
]
