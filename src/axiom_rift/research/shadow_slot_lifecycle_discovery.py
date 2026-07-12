"""Registered discovery surface for post-stop slot reservation semantics."""

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
    DATASET_SHA256, OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256,
    DiscoveryBoundaryError, _claim_limits, _evaluate_configuration, _fold_payloads,
    _paired_control_pvalue, _selection_adjusted_pvalues, _selection_method, _time_ns,
    _validate_engine_environment, _validate_fold_payloads, _validate_production_data,
    causal_effective_spread,
)
from axiom_rift.research.event_label_discovery import HORIZON, _raw_features, calibrate_selector
from axiom_rift.research.shadow_slot_lifecycle_chassis import (
    SELECTION_TOTAL_EXPOSURES, executable_configuration_map,
    loader_implementation_sha256, shadow_slot_lifecycle_chassis_implementation_sha256,
    shadow_slot_lifecycle_configurations, shadow_slot_lifecycle_executable,
    simulate_shadow_slot_lifecycle,
)
from axiom_rift.research.volatility_clock_label_chassis import build_labels, fit_label_model
from axiom_rift.research.volatility_clock_label_discovery import deterministic_score


_THIS_FILE = Path(__file__).resolve()


def shadow_slot_lifecycle_discovery_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _matched(results: list[Any], policy: str) -> Any:
    found = [value for value in results if value.configuration.lifecycle_policy == policy]
    if len(found) != 1:
        raise DiscoveryBoundaryError("shadow-slot lifecycle control is not unique")
    return found[0]


def _populate_controls(results: list[Any]) -> None:
    control = _matched(results, "immediate_reuse_control")
    for subject in results:
        subject.metrics["lifecycle_control_delta_net_profit_micropoints"] = (
            subject.metrics["net_profit_micropoints"]
            - control.metrics["net_profit_micropoints"]
        )
        subject.metrics["lifecycle_control_pvalue_upper_ppm"] = (
            1_000_000 if subject is control else _paired_control_pvalue(
                subject, control, role="matched_immediate_reuse_control",
                total_exposures=SELECTION_TOTAL_EXPOSURES,
            )
        )


def compute_registered_shadow_slot_lifecycle_surface(
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
    full_features, full_volatility, full_run = _raw_features(frame)
    label = build_labels(frame, full_volatility, full_run)[
        "volatility_clock_terminal_12_of_48"
    ]
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
    fold_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    calibrations: dict[str, tuple[float, tuple[float, float], float]] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        train = fold["train_is"]
        start, end = pd.Timestamp(train["start"]), pd.Timestamp(train["end"])
        selector_mask = ((time >= start) & (time <= end)).to_numpy()
        future_time = time.shift(-(HORIZON + 1))
        train_mask = selector_mask & (future_time <= end).fillna(False).to_numpy()
        model = fit_label_model(features=full_features, label=label, train_mask=train_mask)
        score = deterministic_score(full_features, model)
        fold_scores[fold_id] = (score, full_volatility, full_run)
        raw = prefix_raw[fold_id]
        prefix_score = deterministic_score(raw[0], model)
        prefix_scores[fold_id] = (prefix_score, raw[1], raw[2])
        prefix_time = pd.to_datetime(prefix_frames[fold_id]["time"], errors="raise")
        prefix_train = ((prefix_time >= start) & (prefix_time <= end)).to_numpy()
        values = full_volatility[train_mask & np.isfinite(full_volatility)]
        cutoffs = (
            float(np.quantile(values, 1 / 3, method="higher")),
            float(np.quantile(values, 2 / 3, method="higher")),
        )
        calibrations[fold_id] = (
            calibrate_selector(score, selector_mask), cutoffs,
            calibrate_selector(prefix_score, prefix_train),
        )
    first = fold_scores[str(folds[0]["fold_id"])]
    results = [
        _evaluate_configuration(
            calibrations=calibrations, frame=frame, features=first,
            fold_features=fold_scores, folds=folds, configuration=configuration,
            effective_spread=spread, prefix_features=prefix_scores,
            prefix_spreads=prefix_spreads, time=time,
            executable_id=shadow_slot_lifecycle_executable(configuration).identity,
            simulation_fn=simulate_shadow_slot_lifecycle,
        )
        for configuration in shadow_slot_lifecycle_configurations()
    ]
    adjusted = _selection_adjusted_pvalues(
        results, total_exposures=SELECTION_TOTAL_EXPOSURES
    )
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = adjusted[result.executable_id]
    _populate_controls(results)
    surface = {
        "claim_limits": _claim_limits() + [
            "lifecycle_is_the_only_primary_changed_research_layer",
            "risk_stop_distance_signal_direction_lot_and_maximum_hold_are_fixed",
            "shadow_reservation_changes_slot_reuse_not_trade_exit",
            "two_trial_surface",
        ],
        "dataset_sha256": DATASET_SHA256,
        "engine_environment": {
            "numpy": np.__version__, "pandas": pd.__version__,
            "python": ".".join(str(value) for value in sys.version_info[:3]),
            "scipy": scipy.__version__,
        },
        "evaluations": [{
            "direction_metrics": result.direction_metrics,
            "evaluable": all(result.metrics[name] == 0 for name in (
                "unknown_cost_unresolved_signal_count", "causality_violation_count",
                "nonfinite_metric_count", "prefix_invariance_mismatch_count",
                "append_invariance_mismatch_count",
            )),
            "fold_metrics": result.fold_metrics,
            "metrics": dict(sorted(result.metrics.items())),
            "regime_metrics": result.regime_metrics,
            "session_metrics": result.session_metrics,
            "subject_configuration_id": result.configuration.configuration_id,
            "subject_executable_id": result.executable_id,
        } for result in results],
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "schema": "shadow_slot_lifecycle_surface.v1",
        "selection_context": [{
            "configuration_id": result.configuration.configuration_id,
            "executable_id": result.executable_id,
            "net_profit_micropoints": result.metrics["net_profit_micropoints"],
            "selection_aware_pvalue_ppm": result.metrics["selection_aware_pvalue_ppm"],
        } for result in results],
        "selection_method": _selection_method(SELECTION_TOTAL_EXPOSURES),
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "shadow_slot_lifecycle_chassis_implementation_sha256": (
            shadow_slot_lifecycle_chassis_implementation_sha256()
        ),
        "shadow_slot_lifecycle_discovery_implementation_sha256": (
            shadow_slot_lifecycle_discovery_implementation_sha256()
        ),
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
    }
    canonical_bytes(surface)
    return surface


def project_shadow_slot_lifecycle_evaluation(
    surface: Mapping[str, Any], *, job_execution: Mapping[str, str],
    subject_executable_id: str, surface_artifact_hash: str,
    surface_manifest_hash: str,
) -> dict[str, Any]:
    value = dict(surface)
    if (
        sha256(canonical_bytes(value)).hexdigest() != surface_artifact_hash
        or value.get("schema") != "shadow_slot_lifecycle_surface.v1"
    ):
        raise DiscoveryBoundaryError("shadow-slot lifecycle surface invalid")
    expected = executable_configuration_map()
    by_id = {item.get("subject_executable_id"): item for item in value["evaluations"]}
    if set(by_id) != set(expected) or subject_executable_id not in expected:
        raise DiscoveryBoundaryError("shadow-slot lifecycle subjects differ")
    payload = {
        name: job_execution[name]
        for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")
    }
    if job_execution.get("identity") != canonical_digest(
        domain="running-job-execution", payload=payload
    ):
        raise DiscoveryBoundaryError("shadow-slot lifecycle Job invalid")
    result = {
        **dict(by_id[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "shadow_slot_lifecycle_evaluation.v1",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(result)
    return result


__all__ = [
    "compute_registered_shadow_slot_lifecycle_surface",
    "project_shadow_slot_lifecycle_evaluation",
    "shadow_slot_lifecycle_discovery_implementation_sha256",
]
