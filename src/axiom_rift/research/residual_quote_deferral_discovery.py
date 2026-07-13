"""Discovery surface for one causal residual-continuation entry deferral."""

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
    fit_market_residual,
    market_residual_event_chassis_implementation_sha256,
    project_market_residual_score,
)
from axiom_rift.research.residual_quote_deferral_chassis import (
    SELECTION_TOTAL_EXPOSURES,
    residual_quote_deferral_chassis_implementation_sha256,
    residual_quote_deferral_configurations,
    residual_quote_deferral_executable,
    simulate_residual_quote_deferral,
)
from axiom_rift.research.us500_market_coherence_discovery import (
    _aligned_source_return,
    load_us500_development,
)
from axiom_rift.research.us500_source import us500_source_contract


_THIS_FILE = Path(__file__).resolve()


class ResidualQuoteDeferralBoundaryError(DiscoveryBoundaryError):
    pass


def residual_quote_deferral_discovery_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _target_return(frame: pd.DataFrame, run: np.ndarray) -> np.ndarray:
    close = pd.to_numeric(frame["close"], errors="raise").to_numpy(dtype=float)
    result = np.full(len(frame), np.nan)
    eligible = np.flatnonzero(np.asarray(run) >= 13)
    result[eligible] = np.log(close[eligible]) - np.log(close[eligible - 12])
    return result


def _matched(results: list[Any], profile: str) -> Any:
    matches = [value for value in results if value.configuration.profile == profile]
    if len(matches) != 1:
        raise ResidualQuoteDeferralBoundaryError(
            "residual quote-deferral control is not unique"
        )
    return matches[0]


def _populate_controls(results: list[Any]) -> None:
    control = _matched(results, "immediate_control")
    for subject in results:
        subject.metrics["immediate_control_delta_net_profit_micropoints"] = (
            subject.metrics["net_profit_micropoints"]
            - control.metrics["net_profit_micropoints"]
        )
        subject.metrics["immediate_control_delta_trade_count"] = (
            subject.metrics["trade_count"] - control.metrics["trade_count"]
        )
        subject.metrics["immediate_control_pvalue_upper_ppm"] = (
            1_000_000
            if subject is control
            else _paired_control_pvalue(
                subject,
                control,
                role="exact_stu0098_immediate_continuation_control",
                total_exposures=SELECTION_TOTAL_EXPOSURES,
            )
        )


def _timing_metrics(configuration: Any, simulations: list[Any], result: Any) -> None:
    if configuration.profile == "immediate_control":
        deferred = 0
        immediate = int(result.metrics["trade_count"])
        unknown_reference = 0
    else:
        full_simulations = simulations[0::2]
        statuses = [
            row[-1]
            for simulation in full_simulations
            for row in simulation.intent_rows
        ]
        deferred = statuses.count("executed_deferred")
        immediate = statuses.count("executed_immediate")
        unknown_reference = statuses.count(
            "executed_immediate_reference_unknown"
        )
    executed = deferred + immediate + unknown_reference
    trade_count = int(result.metrics["trade_count"])
    result.metrics.update(
        {
            "deferred_entry_count": deferred,
            "deferred_entry_rate_ppm": (
                0
                if trade_count == 0
                else int(round(1_000_000 * deferred / trade_count))
            ),
            "entry_delay_bars_max": 1 if deferred else 0,
            "execution_timing_accounting_mismatch_count": abs(
                trade_count - executed
            ),
            "immediate_entry_count": immediate + unknown_reference,
            "quote_reference_unknown_immediate_count": unknown_reference,
        }
    )


def compute_registered_residual_quote_deferral_surface(
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
    spread = causal_effective_spread(
        frame["spread"].to_numpy(float),
        _time_ns(frame),
    )
    _, volatility, run = _raw_features(frame)
    target_return = _target_return(frame, run)
    source_return = _aligned_source_return(frame, source.frame)
    prefix_spreads: dict[str, np.ndarray] = {}
    fold_payload: dict[str, dict[str, Any]] = {}
    fit_rows: list[dict[str, Any]] = []
    for fold in folds:
        fold_id = str(fold["fold_id"])
        train_start = pd.Timestamp(fold["train_is"]["start"])
        train_end = pd.Timestamp(fold["train_is"]["end"])
        train = ((time >= train_start) & (time <= train_end)).to_numpy()
        fit = fit_market_residual(target_return, source_return, train)
        train_volatility = volatility[train & np.isfinite(volatility)]
        cutoffs = (
            float(np.quantile(train_volatility, 1 / 3, method="higher")),
            float(np.quantile(train_volatility, 2 / 3, method="higher")),
        )
        prefix_end = int(
            time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]), side="right")
        )
        prefix = frame.iloc[:prefix_end]
        prefix_run = run[:prefix_end]
        prefix_target = _target_return(prefix, prefix_run)
        prefix_source = source_return[:prefix_end]
        prefix_spreads[fold_id] = causal_effective_spread(
            prefix["spread"].to_numpy(float),
            _time_ns(prefix),
        )
        fold_payload[fold_id] = {
            "cutoffs": cutoffs,
            "fit": fit,
            "prefix_end": prefix_end,
            "prefix_source": prefix_source,
            "prefix_target": prefix_target,
            "train": train,
        }
        fit_rows.append(
            {
                "alpha_nano": int(round(fit.alpha * 1_000_000_000)),
                "beta_ppm": int(round(fit.beta * 1_000_000)),
                "fold_id": fold_id,
                "residual_scale_nano": int(
                    round(fit.residual_scale * 1_000_000_000)
                ),
                "target_scale_nano": int(
                    round(fit.target_scale * 1_000_000_000)
                ),
                "train_pair_count": int(
                    np.sum(
                        train
                        & np.isfinite(target_return)
                        & np.isfinite(source_return)
                    )
                ),
            }
        )
    fold_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    calibrations: dict[str, tuple[float, tuple[float, float], float]] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        values = fold_payload[fold_id]
        score = project_market_residual_score(
            target_return,
            source_return,
            values["fit"],
            residual_profile="fold_train_linear_market_residual",
        )
        threshold = _threshold(score, values["train"], 9000)
        prefix_score = project_market_residual_score(
            values["prefix_target"],
            values["prefix_source"],
            values["fit"],
            residual_profile="fold_train_linear_market_residual",
        )
        prefix_end = values["prefix_end"]
        prefix_train = values["train"][:prefix_end]
        prefix_threshold = _threshold(prefix_score, prefix_train, 9000)
        if threshold != prefix_threshold or not np.array_equal(
            score[:prefix_end],
            prefix_score,
            equal_nan=True,
        ):
            raise ResidualQuoteDeferralBoundaryError(
                "residual quote-deferral prefix invariance failed"
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
    results: list[Any] = []
    for configuration in residual_quote_deferral_configurations():
        simulations: list[Any] = []
        if configuration.profile == "immediate_control":
            simulation_fn = simulate_fixed_hold
        else:
            def simulation_fn(**kwargs: Any):
                simulation = simulate_residual_quote_deferral(**kwargs)
                simulations.append(simulation)
                return simulation

        result = _evaluate_configuration(
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
            executable_id=residual_quote_deferral_executable(configuration).identity,
            simulation_fn=simulation_fn,
        )
        _timing_metrics(configuration, simulations, result)
        results.append(result)
    adjusted = _selection_adjusted_pvalues(
        results,
        total_exposures=SELECTION_TOTAL_EXPOSURES,
    )
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = adjusted[
            result.executable_id
        ]
    _populate_controls(results)
    surface = {
        "schema": "residual_quote_deferral_surface.v1",
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
                "net_profit_micropoints": result.metrics[
                    "net_profit_micropoints"
                ],
                "selection_aware_pvalue_ppm": result.metrics[
                    "selection_aware_pvalue_ppm"
                ],
            }
            for result in results
        ],
        "claim_limits": _claim_limits()
        + [
            "exact_stu0098_residual_continuation_control",
            "one_fixed_prior_288_bar_median_quote_reference",
            "one_fixed_above_median_scheduled_quote_condition",
            "one_fixed_five_minute_deferral_then_unconditional_entry",
            "unknown_quote_reference_retains_immediate_entry",
            "same_direction_selector_session_six_bar_hold_and_one_lot",
            "no_spread_threshold_delay_window_direction_hold_or_session_grid",
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
                        "execution_timing_accounting_mismatch_count",
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
        "residual_quote_deferral_chassis_implementation_sha256": (
            residual_quote_deferral_chassis_implementation_sha256()
        ),
        "residual_quote_deferral_discovery_implementation_sha256": (
            residual_quote_deferral_discovery_implementation_sha256()
        ),
        "shared_discovery_implementation_sha256": (
            discovery_implementation_sha256()
        ),
    }
    canonical_bytes(surface)
    return surface


def project_residual_quote_deferral_evaluation(
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
        or value.get("schema") != "residual_quote_deferral_surface.v1"
    ):
        raise ResidualQuoteDeferralBoundaryError(
            "residual quote-deferral surface is invalid"
        )
    expected = {
        residual_quote_deferral_executable(configuration).identity
        for configuration in residual_quote_deferral_configurations()
    }
    by_executable = {
        item.get("subject_executable_id"): item
        for item in value["evaluations"]
    }
    if set(by_executable) != expected or subject_executable_id not in expected:
        raise ResidualQuoteDeferralBoundaryError(
            "residual quote-deferral subjects differ"
        )
    payload = {
        name: job_execution[name]
        for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")
    }
    if job_execution.get("identity") != canonical_digest(
        domain="running-job-execution",
        payload=payload,
    ):
        raise ResidualQuoteDeferralBoundaryError(
            "residual quote-deferral Job is invalid"
        )
    result = {
        **dict(by_executable[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "residual_quote_deferral_evaluation.v1",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(result)
    return result


__all__ = [
    "compute_registered_residual_quote_deferral_surface",
    "project_residual_quote_deferral_evaluation",
    "residual_quote_deferral_discovery_implementation_sha256",
]
