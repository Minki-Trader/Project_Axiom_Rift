"""One fixed US500 sign-coherence routing contrast over a fixed reversal frontier."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.external_observed_development import (
    ExternalObservedDevelopmentError,
    US500_OBSERVED_DEVELOPMENT_SPEC,
    load_external_observed_development,
)
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
    discovery_implementation_sha256,
)
from axiom_rift.research.event_label_discovery import _raw_features
from axiom_rift.research.high_vol_target_reversal_discovery import _matrix, _threshold
from axiom_rift.research.positive_direction_sleeve_discovery import target_direction_score
from axiom_rift.research.us500_market_coherence_chassis import (
    SELECTION_TOTAL_EXPOSURES,
    US500_RAW_SHA256,
    executable_configuration_map,
    simulate_us500_market_coherence,
    us500_market_coherence_chassis_implementation_sha256,
    us500_market_coherence_configurations,
    us500_market_coherence_executable,
)
from axiom_rift.research.us500_source import us500_source_contract
from axiom_rift.research.volatility_clock_label_chassis import fit_label_model
from axiom_rift.research.volatility_clock_label_discovery import deterministic_score


DEVELOPMENT_END = pd.Timestamp("2026-04-30 23:55:00")
_TIME_FORMAT = "%Y.%m.%d %H:%M:%S"
_THIS_FILE = Path(__file__).resolve()


class US500MarketCoherenceBoundaryError(DiscoveryBoundaryError):
    pass


@dataclass(frozen=True, slots=True)
class US500Development:
    frame: pd.DataFrame
    raw_sha256: str
    prefix_sha256: str
    row_count: int


def us500_market_coherence_discovery_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def load_us500_development(repository_root: str | Path) -> US500Development:
    try:
        loaded = load_external_observed_development(repository_root, "US500")
    except ExternalObservedDevelopmentError as exc:
        raise US500MarketCoherenceBoundaryError(
            "US500 observed-development prefix is invalid"
        ) from exc
    return US500Development(
        frame=loaded.frame,
        raw_sha256=US500_OBSERVED_DEVELOPMENT_SPEC.parent_raw_sha256,
        prefix_sha256=US500_OBSERVED_DEVELOPMENT_SPEC.prefix_sha256,
        row_count=US500_OBSERVED_DEVELOPMENT_SPEC.row_count,
    )


def _aligned_source_return(target_frame: pd.DataFrame, source_frame: pd.DataFrame) -> np.ndarray:
    target_time = pd.to_datetime(target_frame["time"], errors="raise")
    source = source_frame.set_index("time")["close"]
    aligned = source.reindex(target_time).to_numpy(dtype=float)
    valid = np.isfinite(aligned) & (aligned > 0)
    target_ns = target_time.to_numpy(dtype="datetime64[ns]").astype("int64")
    run = np.zeros(len(aligned), dtype=np.int32)
    for index in range(len(aligned)):
        if not valid[index]:
            continue
        run[index] = (
            run[index - 1] + 1
            if index > 0 and valid[index - 1] and target_ns[index] - target_ns[index - 1] == 300_000_000_000
            else 1
        )
    result = np.full(len(aligned), np.nan)
    eligible = np.flatnonzero(run >= 13)
    result[eligible] = np.log(aligned[eligible]) - np.log(aligned[eligible - 12])
    return result


def _matched(results: list[Any], profile: str) -> Any:
    found = [value for value in results if value.configuration.profile == profile]
    if len(found) != 1:
        raise US500MarketCoherenceBoundaryError("market coherence control is not unique")
    return found[0]


def _populate(results: list[Any]) -> None:
    control = _matched(results, "fixed_high_reversal_control")
    for subject in results:
        subject.metrics["fixed_high_reversal_delta_net_profit_micropoints"] = (
            subject.metrics["net_profit_micropoints"] - control.metrics["net_profit_micropoints"]
        )
        subject.metrics["fixed_high_reversal_pvalue_upper_ppm"] = (
            1_000_000
            if subject is control
            else _paired_control_pvalue(
                subject,
                control,
                role="fixed_high_reversal_control",
                total_exposures=SELECTION_TOTAL_EXPOSURES,
            )
        )


def compute_registered_us500_market_coherence_surface(
    repository_root: str | Path,
) -> dict[str, Any]:
    _validate_engine_environment()
    root = Path(repository_root).resolve()
    data = load_observed_development(root)
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    source = load_us500_development(root)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = causal_effective_spread(frame["spread"].to_numpy(float), _time_ns(frame))
    features, volatility, run = _raw_features(frame)
    label = terminal_return_sign_12(frame, run)
    target = target_direction_score(frame, run)
    source_return = _aligned_source_return(frame, source.frame)
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
    common: dict[str, tuple[Any, ...]] = {}
    prefix_common: dict[str, tuple[Any, ...]] = {}
    state_counts: list[dict[str, Any]] = []
    for fold in folds:
        fold_id = str(fold["fold_id"])
        start = pd.Timestamp(fold["train_is"]["start"])
        end = pd.Timestamp(fold["train_is"]["end"])
        mask = ((time >= start) & (time <= end)).to_numpy()
        train = mask & (time.shift(-13) <= end).fillna(False).to_numpy()
        model = fit_label_model(features=features, label=label, train_mask=train)
        router_raw = deterministic_score(features, model)
        router_threshold = calibrate_synthesis_selector(router_raw, mask, 7000)
        values = volatility[train & np.isfinite(volatility)]
        cutoffs = (
            float(np.quantile(values, 1 / 3, method="higher")),
            float(np.quantile(values, 2 / 3, method="higher")),
        )
        common[fold_id] = (
            router_raw,
            target,
            volatility,
            run,
            router_threshold,
            cutoffs,
            mask,
            source_return,
        )
        prefix = prefix_frames[fold_id]
        raw = prefix_raw[fold_id]
        prefix_time = pd.to_datetime(prefix["time"], errors="raise")
        prefix_mask = ((prefix_time >= start) & (prefix_time <= end)).to_numpy()
        prefix_router = deterministic_score(raw[0], model)
        prefix_target = target_direction_score(prefix, raw[2])
        prefix_router_threshold = calibrate_synthesis_selector(prefix_router, prefix_mask, 7000)
        if router_threshold != prefix_router_threshold:
            raise US500MarketCoherenceBoundaryError("router threshold drifted")
        prefix_common[fold_id] = (
            prefix_router,
            prefix_target,
            raw[1],
            raw[2],
            prefix_router_threshold,
            prefix_mask,
            source_return[: len(prefix)],
        )
    results: list[Any] = []
    for configuration in us500_market_coherence_configurations():
        fold_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        prefix_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        calibrations: dict[str, tuple[float, tuple[float, float], float]] = {}
        for fold in folds:
            fold_id = str(fold["fold_id"])
            router_raw, target_raw, fold_volatility, fold_run, router_threshold, cutoffs, mask, source_values = common[fold_id]
            target_threshold = _threshold(target_raw, mask, configuration.target_quantile_bp)
            matrix = _matrix(
                router_raw,
                target_raw,
                fold_volatility,
                router_threshold,
                target_threshold,
                cutoffs,
            )
            fold_scores[fold_id] = (
                np.column_stack((matrix, source_values)),
                fold_volatility,
                fold_run,
            )
            prefix_router, prefix_target, prefix_volatility, prefix_run, prefix_router_threshold, prefix_mask, prefix_source = prefix_common[fold_id]
            prefix_target_threshold = _threshold(
                prefix_target, prefix_mask, configuration.target_quantile_bp
            )
            if target_threshold != prefix_target_threshold:
                raise US500MarketCoherenceBoundaryError("target threshold drifted")
            prefix_matrix = _matrix(
                prefix_router,
                prefix_target,
                prefix_volatility,
                prefix_router_threshold,
                prefix_target_threshold,
                cutoffs,
            )
            prefix_scores[fold_id] = (
                np.column_stack((prefix_matrix, prefix_source)),
                prefix_volatility,
                prefix_run,
            )
            calibrations[fold_id] = (1.0, cutoffs, 1.0)
            if configuration.uses_market_coherence:
                test_start = pd.Timestamp(fold["test_oos"]["start"])
                test_end = pd.Timestamp(fold["test_oos"]["end"])
                test = ((time >= test_start) & (time <= test_end)).to_numpy()
                high = np.isfinite(fold_volatility) & (fold_volatility >= cutoffs[1])
                selected = np.isfinite(target_raw) & (np.abs(target_raw) >= target_threshold)
                available = np.isfinite(source_values) & (source_values != 0.0)
                coherent = available & (np.sign(target_raw) == np.sign(source_values))
                state_counts.append(
                    {
                        "fold_id": fold_id,
                        "systemic_selected_high_count": int(np.sum(test & high & selected & coherent)),
                        "idiosyncratic_selected_high_count": int(np.sum(test & high & selected & available & ~coherent)),
                        "missing_selected_high_count": int(np.sum(test & high & selected & ~available)),
                    }
                )
        first = fold_scores[str(folds[0]["fold_id"])]
        results.append(
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
                executable_id=us500_market_coherence_executable(configuration).identity,
                simulation_fn=simulate_us500_market_coherence,
            )
        )
    adjusted = _selection_adjusted_pvalues(results, total_exposures=SELECTION_TOTAL_EXPOSURES)
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = adjusted[result.executable_id]
    _populate(results)
    surface = {
        "schema": "us500_market_coherence_surface.v1",
        "dataset_sha256": DATASET_SHA256,
        "material_identity": OBSERVED_MATERIAL_ID,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "source_contract_id": us500_source_contract().source_contract_id,
        "source_raw_sha256": source.raw_sha256,
        "source_development_prefix_sha256": source.prefix_sha256,
        "source_development_row_count": source.row_count,
        "state_counts": state_counts,
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "selection_method": _selection_method(SELECTION_TOTAL_EXPOSURES),
        "selection_context": [
            {
                "configuration_id": result.configuration.configuration_id,
                "executable_id": result.executable_id,
                "net_profit_micropoints": result.metrics["net_profit_micropoints"],
                "selection_aware_pvalue_ppm": result.metrics["selection_aware_pvalue_ppm"],
            }
            for result in results
        ],
        "claim_limits": _claim_limits()
        + [
            "data_source_regime_and_portfolio_are_the_primary_changed_layers",
            "subject_uses_fixed_nonzero_twelve_bar_sign_coherence_only",
            "systemic_high_target_role_follows_and_idiosyncratic_role_reverses",
            "registered_frontier_underlying_sleeves_features_labels_models_trades_lifecycles_risk_and_execution_are_unchanged",
            "missing_source_fails_only_the_dependent_high_target_sleeve_closed",
            "no_source_lookback_threshold_beta_fit_selector_hour_or_role_grid",
            "one_new_subject_with_exact_registered_fixed_reversal_control",
        ],
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
        "us500_market_coherence_chassis_implementation_sha256": us500_market_coherence_chassis_implementation_sha256(),
        "us500_market_coherence_discovery_implementation_sha256": us500_market_coherence_discovery_implementation_sha256(),
        "shared_discovery_implementation_sha256": discovery_implementation_sha256(),
    }
    canonical_bytes(surface)
    return surface


def project_us500_market_coherence_evaluation(
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
        or value.get("schema") != "us500_market_coherence_surface.v1"
    ):
        raise US500MarketCoherenceBoundaryError("US500 market coherence surface is invalid")
    expected = executable_configuration_map()
    by_executable = {
        item.get("subject_executable_id"): item for item in value["evaluations"]
    }
    if set(by_executable) != set(expected) or subject_executable_id not in expected:
        raise US500MarketCoherenceBoundaryError("US500 market coherence subjects differ")
    payload = {
        name: job_execution[name]
        for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")
    }
    if job_execution.get("identity") != canonical_digest(
        domain="running-job-execution", payload=payload
    ):
        raise US500MarketCoherenceBoundaryError("US500 market coherence Job is invalid")
    result = {
        **dict(by_executable[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "us500_market_coherence_evaluation.v1",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(result)
    return result


__all__ = [
    "compute_registered_us500_market_coherence_surface",
    "load_us500_development",
    "project_us500_market_coherence_evaluation",
    "us500_market_coherence_discovery_implementation_sha256",
]
