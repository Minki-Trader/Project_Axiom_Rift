"""Registered independent fixed-lot sleeve portfolio surface."""

from __future__ import annotations

from hashlib import sha256
from math import sqrt
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.dense_short_synthesis_chassis import (
    calibrate_synthesis_selector,
    terminal_return_sign_12,
)
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
from axiom_rift.research.event_label_discovery import _raw_features
from axiom_rift.research.independent_sleeve_portfolio_chassis import (
    SELECTION_TOTAL_EXPOSURES,
    executable_configuration_map,
    independent_sleeve_portfolio_chassis_implementation_sha256,
    independent_sleeve_portfolio_configurations,
    independent_sleeve_portfolio_executable,
    loader_implementation_sha256,
    simulate_independent_sleeve_portfolio,
)
from axiom_rift.research.volatility_clock_label_chassis import fit_label_model
from axiom_rift.research.volatility_clock_label_discovery import deterministic_score


_THIS_FILE = Path(__file__).resolve()


def independent_sleeve_portfolio_discovery_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def target_downside_score(frame: pd.DataFrame, run: np.ndarray) -> np.ndarray:
    close = pd.to_numeric(frame["close"], errors="raise").to_numpy(dtype=float)
    log_close = np.log(close)
    one = np.full(len(close), np.nan)
    one[1:] = np.diff(log_close)
    r6 = np.full(len(close), np.nan)
    r6[6:] = log_close[6:] - log_close[:-6]
    rv12 = np.sqrt(pd.Series(one * one).rolling(12, min_periods=12).sum().to_numpy(float))
    rv96 = np.sqrt(pd.Series(one * one).rolling(96, min_periods=96).sum().to_numpy(float))
    zden = rv96 * sqrt(6 / 96)
    z6 = np.divide(r6, zden, out=np.full(len(close), np.nan), where=np.isfinite(zden) & (zden > 0))
    eden = rv96 * sqrt(12 / 96)
    ratio = np.divide(rv12, eden, out=np.full(len(close), np.nan), where=np.isfinite(eden) & (eden > 0))
    score = np.minimum(z6, 0.0) * np.maximum(ratio - 1.0, 0.0)
    score[np.asarray(run) < 97] = np.nan
    return score


def _quantile(values: np.ndarray, mask: np.ndarray, bp: int) -> float:
    selected = np.abs(values[mask & np.isfinite(values)])
    if len(selected) < 1000:
        raise DiscoveryBoundaryError("independent sleeve selector has fewer than 1000 observations")
    return float(np.quantile(selected, bp / 10_000, method="higher"))


def _normalized_scores(
    router_raw: np.ndarray,
    downside_raw: np.ndarray,
    volatility: np.ndarray,
    router_threshold: float,
    downside_threshold: float,
    cutoffs: tuple[float, float],
) -> np.ndarray:
    router = np.zeros(len(router_raw), dtype=float)
    selected = np.isfinite(router_raw) & (router_raw > 0)
    high = np.isfinite(volatility) & (volatility >= cutoffs[1])
    router[selected & high] = np.abs(router_raw[selected & high]) / router_threshold
    router[selected & ~high] = -np.abs(router_raw[selected & ~high]) / router_threshold
    downside = np.divide(downside_raw, downside_threshold, out=np.full(len(downside_raw), np.nan), where=np.isfinite(downside_raw))
    return np.column_stack((router, downside))


def _matched(results: list[Any], profile: str) -> Any:
    found = [value for value in results if value.configuration.portfolio_profile == profile]
    if len(found) != 1:
        raise DiscoveryBoundaryError("independent sleeve control is not unique")
    return found[0]


def _populate_controls(results: list[Any]) -> None:
    router = _matched(results, "router_control")
    downside = _matched(results, "target_downside_control")
    for subject in results:
        subject.metrics["router_control_delta_net_profit_micropoints"] = subject.metrics["net_profit_micropoints"] - router.metrics["net_profit_micropoints"]
        subject.metrics["router_control_pvalue_upper_ppm"] = 1_000_000 if subject is router else _paired_control_pvalue(subject, router, role="router_control", total_exposures=SELECTION_TOTAL_EXPOSURES)
        subject.metrics["downside_control_delta_net_profit_micropoints"] = subject.metrics["net_profit_micropoints"] - downside.metrics["net_profit_micropoints"]
        subject.metrics["downside_control_pvalue_upper_ppm"] = 1_000_000 if subject is downside else _paired_control_pvalue(subject, downside, role="target_downside_control", total_exposures=SELECTION_TOTAL_EXPOSURES)


def compute_registered_independent_sleeve_portfolio_surface(repository_root: str | Path) -> dict[str, Any]:
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
    downside = target_downside_score(frame, run)
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
    fold_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    calibrations: dict[str, tuple[float, tuple[float, float], float]] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        start, end = pd.Timestamp(fold["train_is"]["start"]), pd.Timestamp(fold["train_is"]["end"])
        selector_mask = ((time >= start) & (time <= end)).to_numpy()
        future_time = time.shift(-13)
        train_mask = selector_mask & (future_time <= end).fillna(False).to_numpy()
        model = fit_label_model(features=features, label=label, train_mask=train_mask)
        router_raw = deterministic_score(features, model)
        router_threshold = calibrate_synthesis_selector(router_raw, selector_mask, 7000)
        downside_threshold = _quantile(downside, selector_mask, 9500)
        vol_values = volatility[train_mask & np.isfinite(volatility)]
        cutoffs = (float(np.quantile(vol_values, 1 / 3, method="higher")), float(np.quantile(vol_values, 2 / 3, method="higher")))
        normalized = _normalized_scores(router_raw, downside, volatility, router_threshold, downside_threshold, cutoffs)
        fold_scores[fold_id] = (normalized, volatility, run)
        raw = prefix_raw[fold_id]
        prefix_time = pd.to_datetime(prefix_frames[fold_id]["time"], errors="raise")
        prefix_mask = ((prefix_time >= start) & (prefix_time <= end)).to_numpy()
        prefix_router = deterministic_score(raw[0], model)
        prefix_downside = target_downside_score(prefix_frames[fold_id], raw[2])
        prefix_router_threshold = calibrate_synthesis_selector(prefix_router, prefix_mask, 7000)
        prefix_downside_threshold = _quantile(prefix_downside, prefix_mask, 9500)
        if router_threshold != prefix_router_threshold or downside_threshold != prefix_downside_threshold:
            raise DiscoveryBoundaryError("independent sleeve threshold drifted")
        prefix_scores[fold_id] = (_normalized_scores(prefix_router, prefix_downside, raw[1], prefix_router_threshold, prefix_downside_threshold, cutoffs), raw[1], raw[2])
        calibrations[fold_id] = (1.0, cutoffs, 1.0)
    first = fold_scores[str(folds[0]["fold_id"])]
    results = [
        _evaluate_configuration(
            calibrations=calibrations,
            frame=frame,
            features=first,
            fold_features=fold_scores,
            folds=folds,
            configuration=configuration,
            effective_spread=spread,
            prefix_features=prefix_scores,
            prefix_spreads=prefix_spreads,
            time=time,
            executable_id=independent_sleeve_portfolio_executable(configuration).identity,
            simulation_fn=simulate_independent_sleeve_portfolio,
        )
        for configuration in independent_sleeve_portfolio_configurations()
    ]
    adjusted = _selection_adjusted_pvalues(results, total_exposures=SELECTION_TOTAL_EXPOSURES)
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = adjusted[result.executable_id]
    _populate_controls(results)
    surface = {
        "claim_limits": _claim_limits() + [
            "portfolio_is_the_primary_changed_research_layer",
            "router_and_target_downside_sleeves_reuse_fixed_prior_semantics",
            "each_sleeve_uses_one_fixed_lot_without_dynamic_sizing",
            "dual_profile_allows_two_gross_lots_and_is_not_netting_authority",
            "three_trial_surface",
        ],
        "dataset_sha256": DATASET_SHA256,
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
        "independent_sleeve_portfolio_chassis_implementation_sha256": independent_sleeve_portfolio_chassis_implementation_sha256(),
        "independent_sleeve_portfolio_discovery_implementation_sha256": independent_sleeve_portfolio_discovery_implementation_sha256(),
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "schema": "independent_sleeve_portfolio_surface.v1",
        "selection_context": [{"configuration_id": result.configuration.configuration_id, "executable_id": result.executable_id, "net_profit_micropoints": result.metrics["net_profit_micropoints"], "selection_aware_pvalue_ppm": result.metrics["selection_aware_pvalue_ppm"]} for result in results],
        "selection_method": _selection_method(SELECTION_TOTAL_EXPOSURES),
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
    }
    canonical_bytes(surface)
    return surface


def project_independent_sleeve_portfolio_evaluation(surface: Mapping[str, Any], *, job_execution: Mapping[str, str], subject_executable_id: str, surface_artifact_hash: str, surface_manifest_hash: str) -> dict[str, Any]:
    value = dict(surface)
    if sha256(canonical_bytes(value)).hexdigest() != surface_artifact_hash or value.get("schema") != "independent_sleeve_portfolio_surface.v1":
        raise DiscoveryBoundaryError("independent sleeve portfolio surface invalid")
    expected = executable_configuration_map()
    by_subject = {entry.get("subject_executable_id"): entry for entry in value["evaluations"]}
    if set(by_subject) != set(expected) or subject_executable_id not in expected:
        raise DiscoveryBoundaryError("independent sleeve portfolio subjects differ")
    payload = {name: job_execution[name] for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")}
    if job_execution.get("identity") != canonical_digest(domain="running-job-execution", payload=payload):
        raise DiscoveryBoundaryError("independent sleeve portfolio Job invalid")
    result = {**dict(by_subject[subject_executable_id]), "claim_limits": value["claim_limits"], "job_execution": dict(job_execution), "schema": "independent_sleeve_portfolio_evaluation.v1", "selection_context": value["selection_context"], "selection_method": value["selection_method"], "session_semantics": value["session_semantics"], "surface_artifact_hash": surface_artifact_hash, "surface_manifest_hash": surface_manifest_hash}
    canonical_bytes(result)
    return result


__all__ = [
    "compute_registered_independent_sleeve_portfolio_surface",
    "independent_sleeve_portfolio_discovery_implementation_sha256",
    "project_independent_sleeve_portfolio_evaluation",
    "target_downside_score",
]
