"""Fixed three-profile discovery for the causal market-residual event chassis."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

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
    discovery_implementation_sha256,
    simulate_fixed_hold,
)
from axiom_rift.research.event_label_discovery import _raw_features
from axiom_rift.research.high_vol_target_reversal_discovery import _threshold
from axiom_rift.research.market_residual_event_chassis import (
    SELECTION_TOTAL_EXPOSURES,
    fit_market_residual,
    market_residual_event_chassis_implementation_sha256,
    market_residual_event_configurations,
    market_residual_event_executable,
    project_market_residual_score,
)
from axiom_rift.research.us500_market_coherence_discovery import (
    _aligned_source_return,
    load_us500_development,
)
from axiom_rift.research.us500_source import us500_source_contract


_THIS_FILE = Path(__file__).resolve()


class MarketResidualEventBoundaryError(DiscoveryBoundaryError):
    pass


def market_residual_event_discovery_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _target_return(frame: pd.DataFrame, run: np.ndarray) -> np.ndarray:
    close = pd.to_numeric(frame["close"], errors="raise").to_numpy(dtype=float)
    result = np.full(len(frame), np.nan)
    eligible = np.flatnonzero(np.asarray(run) >= 13)
    result[eligible] = np.log(close[eligible]) - np.log(close[eligible - 12])
    return result


def _matched(results: list[Any], profile: str) -> Any:
    values = [value for value in results if value.configuration.profile == profile]
    if len(values) != 1:
        raise MarketResidualEventBoundaryError("residual event control is not unique")
    return values[0]


def _populate(results: list[Any]) -> None:
    control = _matched(results, "target_only_mean_reversion_control")
    for subject in results:
        subject.metrics["target_only_delta_net_profit_micropoints"] = (
            subject.metrics["net_profit_micropoints"]
            - control.metrics["net_profit_micropoints"]
        )
        subject.metrics["target_only_pvalue_upper_ppm"] = (
            1_000_000
            if subject is control
            else _paired_control_pvalue(
                subject,
                control,
                role="target_only_mean_reversion_control",
                total_exposures=SELECTION_TOTAL_EXPOSURES,
            )
        )


def compute_registered_market_residual_event_surface(
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
    _, volatility, run = _raw_features(frame)
    target_return = _target_return(frame, run)
    source_return = _aligned_source_return(frame, source.frame)
    prefix_spreads: dict[str, np.ndarray] = {}
    results: list[Any] = []
    fit_rows: list[dict[str, Any]] = []
    fold_payload: dict[str, dict[str, Any]] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        train_start = pd.Timestamp(fold["train_is"]["start"])
        train_end = pd.Timestamp(fold["train_is"]["end"])
        train = ((time >= train_start) & (time <= train_end)).to_numpy()
        fit = fit_market_residual(target_return, source_return, train)
        values = volatility[train & np.isfinite(volatility)]
        cutoffs = (
            float(np.quantile(values, 1 / 3, method="higher")),
            float(np.quantile(values, 2 / 3, method="higher")),
        )
        prefix_end = int(
            time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]), side="right")
        )
        prefix = frame.iloc[:prefix_end]
        prefix_time = pd.to_datetime(prefix["time"], errors="raise")
        prefix_run = run[:prefix_end]
        prefix_target = _target_return(prefix, prefix_run)
        prefix_source = source_return[:prefix_end]
        prefix_spreads[fold_id] = causal_effective_spread(
            prefix["spread"].to_numpy(float), _time_ns(prefix)
        )
        fold_payload[fold_id] = {
            "cutoffs": cutoffs,
            "fit": fit,
            "prefix_end": prefix_end,
            "prefix_source": prefix_source,
            "prefix_target": prefix_target,
            "prefix_time": prefix_time,
            "train": train,
        }
        fit_rows.append(
            {
                "alpha_nano": int(round(fit.alpha * 1_000_000_000)),
                "beta_ppm": int(round(fit.beta * 1_000_000)),
                "fold_id": fold_id,
                "residual_scale_nano": int(round(fit.residual_scale * 1_000_000_000)),
                "target_scale_nano": int(round(fit.target_scale * 1_000_000_000)),
                "train_pair_count": int(
                    np.sum(train & np.isfinite(target_return) & np.isfinite(source_return))
                ),
            }
        )
    for configuration in market_residual_event_configurations():
        fold_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        prefix_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        calibrations: dict[str, tuple[float, tuple[float, float], float]] = {}
        for fold in folds:
            fold_id = str(fold["fold_id"])
            values = fold_payload[fold_id]
            fit = values["fit"]
            score = project_market_residual_score(
                target_return,
                source_return,
                fit,
                residual_profile=configuration.residual_profile,
            )
            threshold = _threshold(score, values["train"], 9000)
            prefix_end = values["prefix_end"]
            prefix_score = project_market_residual_score(
                values["prefix_target"],
                values["prefix_source"],
                fit,
                residual_profile=configuration.residual_profile,
            )
            prefix_train = values["train"][:prefix_end]
            prefix_threshold = _threshold(prefix_score, prefix_train, 9000)
            if threshold != prefix_threshold or not np.array_equal(
                score[:prefix_end], prefix_score, equal_nan=True
            ):
                raise MarketResidualEventBoundaryError(
                    "residual event prefix invariance failed"
                )
            fold_scores[fold_id] = (score, volatility, run)
            prefix_scores[fold_id] = (
                prefix_score,
                volatility[:prefix_end],
                run[:prefix_end],
            )
            calibrations[fold_id] = (
                threshold,
                values["cutoffs"],
                prefix_threshold,
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
                executable_id=market_residual_event_executable(configuration).identity,
                simulation_fn=simulate_fixed_hold,
            )
        )
    adjusted = _selection_adjusted_pvalues(
        results, total_exposures=SELECTION_TOTAL_EXPOSURES
    )
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = adjusted[result.executable_id]
    _populate(results)
    surface = {
        "schema": "market_residual_event_surface.v1",
        "dataset_sha256": DATASET_SHA256,
        "material_identity": OBSERVED_MATERIAL_ID,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "source_contract_id": us500_source_contract().source_contract_id,
        "source_raw_sha256": source.raw_sha256,
        "source_development_prefix_sha256": source.prefix_sha256,
        "source_development_row_count": source.row_count,
        "fold_fit_rows": fit_rows,
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "selection_method": _selection_method(SELECTION_TOTAL_EXPOSURES),
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
        "claim_limits": _claim_limits()
        + [
            "one_fixed_fold_train_linear_beta_with_intercept",
            "one_fixed_completed_twelve_bar_return_definition",
            "one_fixed_top_decile_absolute_event_selector",
            "one_fixed_six_bar_nonoverlap_lifecycle",
            "target_only_control_is_source_bound_but_value_independent",
            "residual_source_missing_fails_closed",
            "no_beta_lookback_selector_holding_or_direction_grid",
            "activity_is_an_observation_not_a_quota",
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
        "market_residual_event_chassis_implementation_sha256": (
            market_residual_event_chassis_implementation_sha256()
        ),
        "market_residual_event_discovery_implementation_sha256": (
            market_residual_event_discovery_implementation_sha256()
        ),
        "shared_discovery_implementation_sha256": discovery_implementation_sha256(),
    }
    canonical_bytes(surface)
    return surface


def project_market_residual_event_evaluation(
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
        or value.get("schema") != "market_residual_event_surface.v1"
    ):
        raise MarketResidualEventBoundaryError("market residual event surface is invalid")
    expected = {
        market_residual_event_executable(configuration).identity
        for configuration in market_residual_event_configurations()
    }
    by_executable = {
        item.get("subject_executable_id"): item for item in value["evaluations"]
    }
    if set(by_executable) != expected or subject_executable_id not in expected:
        raise MarketResidualEventBoundaryError("market residual event subjects differ")
    payload = {
        name: job_execution[name]
        for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")
    }
    if job_execution.get("identity") != canonical_digest(
        domain="running-job-execution", payload=payload
    ):
        raise MarketResidualEventBoundaryError("market residual event Job is invalid")
    result = {
        **dict(by_executable[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "market_residual_event_evaluation.v1",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(result)
    return result


__all__ = [
    "compute_registered_market_residual_event_surface",
    "market_residual_event_discovery_implementation_sha256",
    "project_market_residual_event_evaluation",
]
