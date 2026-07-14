

"""Registered router versus broker-high volatility target reversal surface."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.dense_short_synthesis_chassis import calibrate_synthesis_selector, terminal_return_sign_12
from axiom_rift.research.discovery import DATASET_SHA256, OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256, DiscoveryBoundaryError, _claim_limits, _evaluate_configuration, _fold_payloads, _paired_control_pvalue, _selection_adjusted_pvalues, _selection_method, _time_ns, _validate_engine_environment, _validate_fold_payloads, _validate_production_data, causal_effective_spread
from axiom_rift.research.event_label_discovery import _raw_features
from axiom_rift.research.positive_direction_sleeve_discovery import target_direction_score
from axiom_rift.research.high_vol_target_reversal_chassis import SELECTION_TOTAL_EXPOSURES, executable_configuration_map, loader_implementation_sha256, high_vol_target_reversal_chassis_implementation_sha256, high_vol_target_reversal_configurations, high_vol_target_reversal_executable, simulate_high_vol_target_reversal
from axiom_rift.research.volatility_clock_label_chassis import fit_label_model
from axiom_rift.research.volatility_clock_label_discovery import deterministic_score


_THIS_FILE = Path(__file__).resolve()


def high_vol_target_reversal_discovery_implementation_sha256() -> str:
    """Bind prospective work to the current implementation bytes."""

    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _threshold(score: np.ndarray, mask: np.ndarray, quantile_bp: int) -> float:
    values = np.abs(score[mask & np.isfinite(score)])
    if len(values) < 1000:
        raise DiscoveryBoundaryError("high volatility target reversal selector is too small")
    return float(np.quantile(values, quantile_bp / 10000.0, method="higher"))


def _matrix(router_raw: np.ndarray, target_raw: np.ndarray, volatility: np.ndarray, router_threshold: float, target_threshold: float, cutoffs: tuple[float, float]) -> np.ndarray:
    router = np.zeros(len(router_raw))
    selected = np.isfinite(router_raw) & (router_raw > 0)
    high = np.isfinite(volatility) & (volatility >= cutoffs[1])
    router[selected & high] = np.abs(router_raw[selected & high]) / router_threshold
    router[selected & ~high] = -np.abs(router_raw[selected & ~high]) / router_threshold
    target = np.divide(target_raw, target_threshold, out=np.full(len(target_raw), np.nan), where=np.isfinite(target_raw))
    return np.column_stack((router, target))


def _matched(results: list[Any], profile: str) -> Any:
    found = [value for value in results if value.configuration.profile == profile]
    if len(found) != 1:
        raise DiscoveryBoundaryError("high volatility target reversal control is not unique")
    return found[0]


def _populate(results: list[Any]) -> None:
    control = _matched(results, "session_dense_control")
    for subject in results:
        subject.metrics["session_dense_control_delta_net_profit_micropoints"] = subject.metrics["net_profit_micropoints"] - control.metrics["net_profit_micropoints"]
        subject.metrics["session_dense_control_pvalue_upper_ppm"] = 1_000_000 if subject is control else _paired_control_pvalue(subject, control, role="session_dense_control", total_exposures=SELECTION_TOTAL_EXPOSURES)


def compute_registered_high_vol_target_reversal_surface(repository_root: str | Path) -> dict[str, Any]:
    _validate_engine_environment()
    data = load_observed_development(Path(repository_root).resolve())
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = causal_effective_spread(frame["spread"].to_numpy(float), _time_ns(frame))
    features, volatility, run = _raw_features(frame)
    label = terminal_return_sign_12(frame, run)
    target = target_direction_score(frame, run)
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
    common: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float, tuple[float, float], np.ndarray]] = {}
    prefix_common: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float, np.ndarray]] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        start, end = pd.Timestamp(fold["train_is"]["start"]), pd.Timestamp(fold["train_is"]["end"])
        mask = ((time >= start) & (time <= end)).to_numpy()
        train = mask & (time.shift(-13) <= end).fillna(False).to_numpy()
        model = fit_label_model(features=features, label=label, train_mask=train)
        router_raw = deterministic_score(features, model)
        router_threshold = calibrate_synthesis_selector(router_raw, mask, 7000)
        values = volatility[train & np.isfinite(volatility)]
        cutoffs = (float(np.quantile(values, 1 / 3, method="higher")), float(np.quantile(values, 2 / 3, method="higher")))
        common[fold_id] = (router_raw, target, volatility, run, router_threshold, cutoffs, mask)
        prefix = prefix_frames[fold_id]
        raw = prefix_raw[fold_id]
        prefix_time = pd.to_datetime(prefix["time"], errors="raise")
        prefix_mask = ((prefix_time >= start) & (prefix_time <= end)).to_numpy()
        prefix_router = deterministic_score(raw[0], model)
        prefix_target = target_direction_score(prefix, raw[2])
        prefix_router_threshold = calibrate_synthesis_selector(prefix_router, prefix_mask, 7000)
        if router_threshold != prefix_router_threshold:
            raise DiscoveryBoundaryError("session dense router threshold drifted")
        prefix_common[fold_id] = (prefix_router, prefix_target, raw[1], raw[2], prefix_router_threshold, prefix_mask)
    results: list[Any] = []
    for configuration in high_vol_target_reversal_configurations():
        fold_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        prefix_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        calibrations: dict[str, tuple[float, tuple[float, float], float]] = {}
        for fold in folds:
            fold_id = str(fold["fold_id"])
            router_raw, target_raw, fold_volatility, fold_run, router_threshold, cutoffs, mask = common[fold_id]
            target_threshold = _threshold(target_raw, mask, configuration.target_quantile_bp)
            fold_scores[fold_id] = (_matrix(router_raw, target_raw, fold_volatility, router_threshold, target_threshold, cutoffs), fold_volatility, fold_run)
            prefix_router, prefix_target, prefix_volatility, prefix_run, prefix_router_threshold, prefix_mask = prefix_common[fold_id]
            prefix_target_threshold = _threshold(prefix_target, prefix_mask, configuration.target_quantile_bp)
            if target_threshold != prefix_target_threshold:
                raise DiscoveryBoundaryError("session dense target threshold drifted")
            prefix_scores[fold_id] = (_matrix(prefix_router, prefix_target, prefix_volatility, prefix_router_threshold, prefix_target_threshold, cutoffs), prefix_volatility, prefix_run)
            calibrations[fold_id] = (1.0, cutoffs, 1.0)
        first = fold_scores[str(folds[0]["fold_id"])]
        results.append(_evaluate_configuration(calibrations=calibrations, frame=frame, features=first, fold_features=fold_scores, folds=folds, configuration=configuration, effective_spread=spread, prefix_features=prefix_scores, prefix_spreads=prefix_spreads, time=time, executable_id=high_vol_target_reversal_executable(configuration).identity, simulation_fn=simulate_high_vol_target_reversal))
    adjusted = _selection_adjusted_pvalues(results, total_exposures=SELECTION_TOTAL_EXPOSURES)
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = adjusted[result.executable_id]
    _populate(results)
    surface = {
        "claim_limits": _claim_limits() + ["portfolio_and_risk_are_the_primary_changed_layers", "subject_reverses_only_the_fold_train_high_volatility_target_sleeve_role", "low_and_middle_target_roles_are_unchanged", "regime_router_is_unchanged", "both_sleeves_are_US100_completed_bar_only", "each_sleeve_uses_one_fixed_lot", "no_cutoff_selector_hour_or_other_role_tuning", "control_reuses_the_exact_STU_0090_executable", "two_executable_surface_one_new_trial"],
        "dataset_sha256": DATASET_SHA256,
        "evaluations": [{"direction_metrics": result.direction_metrics, "evaluable": all(result.metrics[name] == 0 for name in ("unknown_cost_unresolved_signal_count", "causality_violation_count", "nonfinite_metric_count", "prefix_invariance_mismatch_count", "append_invariance_mismatch_count")), "fold_metrics": result.fold_metrics, "metrics": dict(sorted(result.metrics.items())), "regime_metrics": result.regime_metrics, "session_metrics": result.session_metrics, "subject_configuration_id": result.configuration.configuration_id, "subject_executable_id": result.executable_id} for result in results],
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "schema": "high_vol_target_reversal_surface.v1",
        "selection_context": [{"configuration_id": result.configuration.configuration_id, "executable_id": result.executable_id, "net_profit_micropoints": result.metrics["net_profit_micropoints"], "selection_aware_pvalue_ppm": result.metrics["selection_aware_pvalue_ppm"]} for result in results],
        "selection_method": _selection_method(SELECTION_TOTAL_EXPOSURES),
        "high_vol_target_reversal_chassis_implementation_sha256": high_vol_target_reversal_chassis_implementation_sha256(),
        "high_vol_target_reversal_discovery_implementation_sha256": high_vol_target_reversal_discovery_implementation_sha256(),
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
    }
    canonical_bytes(surface)
    return surface


def project_high_vol_target_reversal_evaluation(surface: Mapping[str, Any], *, job_execution: Mapping[str, str], subject_executable_id: str, surface_artifact_hash: str, surface_manifest_hash: str) -> dict[str, Any]:
    value = dict(surface)
    if sha256(canonical_bytes(value)).hexdigest() != surface_artifact_hash or value.get("schema") != "high_vol_target_reversal_surface.v1":
        raise DiscoveryBoundaryError("high volatility target reversal surface invalid")
    expected = executable_configuration_map()
    by_executable = {item.get("subject_executable_id"): item for item in value["evaluations"]}
    if set(by_executable) != set(expected) or subject_executable_id not in expected:
        raise DiscoveryBoundaryError("high volatility target reversal subjects differ")
    payload = {name: job_execution[name] for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")}
    if job_execution.get("identity") != canonical_digest(domain="running-job-execution", payload=payload):
        raise DiscoveryBoundaryError("high volatility target reversal Job invalid")
    result = {**dict(by_executable[subject_executable_id]), "claim_limits": value["claim_limits"], "job_execution": dict(job_execution), "schema": "high_vol_target_reversal_evaluation.v1", "selection_context": value["selection_context"], "selection_method": value["selection_method"], "session_semantics": value["session_semantics"], "surface_artifact_hash": surface_artifact_hash, "surface_manifest_hash": surface_manifest_hash}
    canonical_bytes(result)
    return result


__all__ = ["compute_registered_high_vol_target_reversal_surface", "project_high_vol_target_reversal_evaluation", "high_vol_target_reversal_discovery_implementation_sha256"]

