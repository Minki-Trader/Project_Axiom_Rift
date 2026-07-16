"""Causal spread-aware entry abstention with a fixed signal chassis."""

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
    SimulationResult,
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
    completed_bar_execution_spreads,
    completed_bar_spread_proxy_indices,
    discovery_implementation_sha256,
    execution_pnl,
)
from axiom_rift.research.event_label_discovery import (
    BARRIER_MULTIPLE_MILLI,
    _fit_model,
    _labels,
    _raw_features,
    _score,
    calibrate_selector,
    event_label_implementation_sha256,
)


SELECTION_TOTAL_EXPOSURES = 530
SELECTOR_QUANTILE_BP = 8_500
HORIZON = 48
SPREAD_REFERENCE_BARS = 288
SPREAD_LIMIT_MILLI = 1_200
_POLICIES = ("unconditional_next_open", "causal_spread_abstention")
_THIS_FILE = Path(__file__).resolve()


def cost_aware_execution_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def loader_implementation_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class CostAwareExecutionConfiguration:
    policy: str
    signal_sign: int
    holding_bars: int = HORIZON

    def __post_init__(self) -> None:
        if (
            self.policy not in _POLICIES
            or self.signal_sign != 1
            or self.holding_bars != HORIZON
        ):
            raise ValueError("cost-aware execution configuration invalid")

    @property
    def configuration_id(self) -> str:
        return f"{self.policy}-direct-h{HORIZON}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "execution_policy": self.policy,
            "holding_bars": self.holding_bars,
            "label_profile": "first_passage_label_48",
            "selector_quantile_bp": SELECTOR_QUANTILE_BP,
            "signal_sign": self.signal_sign,
            "spread_limit_milli": SPREAD_LIMIT_MILLI,
            "spread_reference_bars": SPREAD_REFERENCE_BARS,
        }


def cost_aware_execution_configurations() -> tuple[CostAwareExecutionConfiguration, ...]:
    return tuple(
        CostAwareExecutionConfiguration(policy=policy, signal_sign=1)
        for policy in _POLICIES
    )


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.cost_aware_execution_discovery.{name}"
        f"@sha256:{cost_aware_execution_implementation_sha256()}"
    )


def _event(name: str) -> str:
    return (
        f"axiom_rift.research.event_label_discovery.{name}"
        f"@sha256:{event_label_implementation_sha256()}"
    )


def _shared(name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{name}"
        f"@sha256:{discovery_implementation_sha256()}"
    )


def cost_aware_execution_components() -> tuple[ComponentSpec, ...]:
    feature = ComponentSpec(
            display_name="fixed completed-bar multiscale predictor inputs",
            protocol="feature.fixed_multiscale_return_path.v1",
            implementation=_event("raw_features"),
            spec={
                "availability": "completed_bar_only",
                "fields": [
                    "normalized_return_12",
                    "normalized_return_48",
                    "normalized_return_192",
                    "path_efficiency_48",
                    "volatility_ratio_48_192",
                ],
            },
        )
    label = ComponentSpec(
            display_name="fixed first-passage path label",
            protocol="label.first_passage_path_event.v1",
            implementation=_event("build_labels"),
            spec={
                "barrier_multiple_milli": BARRIER_MULTIPLE_MILLI,
                "future_end_must_be_inside_train": True,
                "horizon_bars": HORIZON,
            },
        )
    model = ComponentSpec(
            display_name="fixed fold-trained ridge score",
            protocol="model.fold_train_ridge_linear.v1",
            implementation=_event("fit_fold_model"),
            spec={
                "fit_role": "train_is_only",
                "penalty_milli": 1_000,
                "standardization": "train_mean_population_std",
            },
            semantic_dependencies=(feature.identity, label.identity),
        )
    calibration = ComponentSpec(
            display_name="fixed identity score calibration",
            protocol="calibration.identity_score.v1",
            implementation=_local("identity_score_calibration"),
            spec={"mapping": "identity", "fit_required": False},
            semantic_dependencies=(model.identity,),
        )
    selector = ComponentSpec(
            display_name="fixed train-only absolute score selector",
            protocol="selector.fold_train_abs_quantile.v3",
            implementation=_event("calibrate_selector"),
            spec={
                "calibration_role": "train_is_only",
                "minimum_train_observations": 1000,
                "quantile_basis_points": SELECTOR_QUANTILE_BP,
                "quantile_method": "higher",
            },
            semantic_dependencies=(calibration.identity,),
        )
    trade = ComponentSpec(
            display_name="fixed completed-bar directional intent",
            protocol="trade.completed_bar_next_open_direction.v3",
            implementation=_shared("simulate_fixed_hold"),
            spec={
                "decision_time": "bar_open_plus_5m",
                "direction": "signal_sign_times_score_sign",
                "parameter_fields": ["signal_sign"],
            },
            semantic_dependencies=(selector.identity,),
        )
    lifecycle = ComponentSpec(
            display_name="fixed 48-bar nonoverlap lifecycle",
            protocol="lifecycle.fixed_hold_no_overlap.v3",
            implementation=_shared("simulate_fixed_hold"),
            spec={
                "entry_overlap": "reject_while_position_slot_is_occupied",
                "exit_surface": "exact_bar_open_after_48_bars",
                "gap_action": "exclude_path",
            },
            semantic_dependencies=(trade.identity,),
        )
    risk = ComponentSpec(
            display_name="fixed one-lot risk",
            protocol="risk.fixed_one_lot.v2",
            implementation=_shared("simulate_fixed_hold"),
            spec={"dynamic_sizing": False, "lot": 1, "positions_per_sleeve": 1},
            semantic_dependencies=(lifecycle.identity,),
        )
    execution = ComponentSpec(
            display_name="causal spread-aware next-open execution policy",
            protocol="execution.causal_spread_abstention.v1",
            implementation=_local("simulate_cost_aware_execution"),
            spec={
                "entry_spread_available_at": (
                    "completed_decision_bar_close_before_next_open"
                ),
                "execution_cost_proxies": {
                    "entry": "entry_index_minus_1",
                    "exit": "exit_index_minus_1",
                },
                "parameter_fields": ["execution_policy"],
                "policies": list(_POLICIES),
                "reference": (
                    "gap_reset_strictly_prior_288_completed_bar_median"
                ),
                "spread_limit_milli": SPREAD_LIMIT_MILLI,
                "stress": "half_effective_spread_each_side",
            },
            semantic_dependencies=(risk.identity,),
        )
    return (
        feature,
        label,
        model,
        calibration,
        selector,
        trade,
        lifecycle,
        risk,
        execution,
    )


def cost_aware_execution_baseline() -> ExecutableSpec:
    trial_components = cost_aware_execution_components()
    risk = next(
        component
        for component in trial_components
        if component.protocol.startswith("risk.")
    )
    anchor = ComponentSpec(
        display_name="execution policy comparison anchor",
        protocol="execution.policy_comparison_anchor.v1",
        implementation=_local("execution_policy_comparison_anchor"),
        spec={
            "parameter_fields": ["execution_policy"],
            "role": "non_evaluated_control_anchor",
        },
        semantic_dependencies=(risk.identity,),
    )
    components = tuple(
        anchor if component.protocol.startswith("execution.") else component
        for component in trial_components
    )
    parameters = CostAwareExecutionConfiguration(
        policy="unconditional_next_open", signal_sign=1
    ).semantic_parameters()
    parameters["execution_policy"] = "comparison_anchor"
    return _cost_aware_execution_executable(
        display_name="cost-aware execution controlled baseline",
        components=components,
        parameters=parameters,
    )


def _cost_aware_execution_executable(
    *,
    display_name: str,
    components: tuple[ComponentSpec, ...],
    parameters: Mapping[str, Any],
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=display_name,
        components=components,
        parameters=dict(parameters),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development"
        ),
        clock_contract=(
            "clock:fpmarkets_m5_completed_decision_bar_spread_proxy_v1"
        ),
        cost_contract=(
            "cost:fpmarkets_completed_bar_spread_proxy_point_0_01_"
            "causal_zero_repair_decision_bar_gate_half_spread_stress_v1"
        ),
        engine_contract=(
            f"engine:cost_aware_execution_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"implementation_{cost_aware_execution_implementation_sha256()}:"
            f"event_{event_label_implementation_sha256()}:"
            f"loader_{loader_implementation_sha256()}:"
            f"shared_{discovery_implementation_sha256()}:"
            f"bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:"
            f"bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def cost_aware_execution_executable(
    configuration: CostAwareExecutionConfiguration,
) -> ExecutableSpec:
    return _cost_aware_execution_executable(
        display_name=f"cost-aware execution {configuration.configuration_id}",
        components=cost_aware_execution_components(),
        parameters=configuration.semantic_parameters(),
    )


def executable_configuration_map() -> dict[str, CostAwareExecutionConfiguration]:
    return {
        cost_aware_execution_executable(configuration).identity: configuration
        for configuration in cost_aware_execution_configurations()
    }


def _spread_reference(spreads: np.ndarray, time_ns: np.ndarray) -> np.ndarray:
    segment = np.zeros(len(time_ns), dtype=np.int64)
    if len(time_ns) > 1:
        segment[1:] = np.cumsum(np.diff(time_ns) != 300_000_000_000)
    values = pd.Series(spreads)
    groups = pd.Series(segment)
    return values.groupby(groups, sort=False).transform(
        lambda part: part.shift(1).rolling(
            SPREAD_REFERENCE_BARS, min_periods=24
        ).median()
    ).to_numpy(float)


def simulate_cost_aware_execution(
    *,
    frame: pd.DataFrame,
    score: np.ndarray,
    volatility: np.ndarray,
    run: np.ndarray,
    threshold: float,
    configuration: CostAwareExecutionConfiguration,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray | None = None,
) -> SimulationResult:
    time = pd.to_datetime(frame["time"], errors="raise")
    time_ns = _time_ns(frame)
    opens = pd.to_numeric(frame["open"], errors="raise").to_numpy(float)
    spreads = (
        causal_effective_spread(
            pd.to_numeric(frame["spread"], errors="raise").to_numpy(float),
            time_ns,
        )
        if effective_spread is None
        else np.asarray(effective_spread, dtype=float)
    )
    reference = _spread_reference(spreads, time_ns)
    candidates = np.flatnonzero(
        ((time >= test_start) & (time <= test_end)).to_numpy()
        & np.isfinite(score)
    )
    records: list[dict[str, Any]] = []
    intents: list[tuple[Any, ...]] = []
    next_decision_index = -1
    unresolved = 0
    gap_excluded = 0
    causality_violations = 0
    for decision_index in candidates:
        if decision_index < next_decision_index or abs(score[decision_index]) < threshold:
            continue
        direction = int(np.sign(score[decision_index])) * configuration.signal_sign
        if direction == 0:
            continue
        entry_index = decision_index + 1
        exit_index = entry_index + configuration.holding_bars
        if exit_index >= len(frame) or time.iloc[exit_index] > test_end:
            continue
        decision_time = time.iloc[decision_index] + pd.Timedelta(minutes=5)
        entry_time = time.iloc[entry_index]
        exit_time = time.iloc[exit_index]
        if (
            time_ns[entry_index] - time_ns[decision_index] != 300_000_000_000
            or run[exit_index] < configuration.holding_bars + 2
        ):
            gap_excluded += 1
            intents.append((decision_time, entry_time, exit_time, direction, "gap_excluded"))
            continue
        if decision_time != entry_time:
            causality_violations += 1
            intents.append((decision_time, entry_time, exit_time, direction, "causality_violation"))
            continue
        entry_proxy_index = completed_bar_spread_proxy_indices(
            int(entry_index),
            spread_count=len(spreads),
        )
        assert isinstance(entry_proxy_index, int)
        entry_cost_known = np.isfinite(spreads[entry_proxy_index])
        if configuration.policy == "causal_spread_abstention":
            gate_spread = spreads[decision_index]
            gate_reference = reference[decision_index]
            reference_known = np.isfinite(gate_reference)
            if not (entry_cost_known and reference_known):
                intents.append((decision_time, entry_time, exit_time, direction, "entry_cancelled_unknown_gate"))
                continue
            if gate_spread * 1000 > gate_reference * SPREAD_LIMIT_MILLI:
                intents.append((decision_time, entry_time, exit_time, direction, "spread_abstained"))
                continue
        next_decision_index = exit_index
        execution_spreads = completed_bar_execution_spreads(
            spreads,
            entry_index=entry_index,
            exit_index=exit_index,
        )
        if not execution_spreads.costs_known:
            unresolved += 1
            intents.append((decision_time, entry_time, exit_time, direction, "unknown_cost"))
            continue
        native, stress = execution_pnl(
            direction=direction,
            entry_bid=float(opens[entry_index]),
            exit_bid=float(opens[exit_index]),
            entry_spread_points=execution_spreads.entry_spread_points,
            exit_spread_points=execution_spreads.exit_spread_points,
        )
        entry_volatility = float(volatility[decision_index])
        regime = (
            "low"
            if entry_volatility <= regime_cutoffs[0]
            else "high"
            if entry_volatility >= regime_cutoffs[1]
            else "middle"
        )
        records.append(
            {
                "decision_bar_open_time": time.iloc[decision_index],
                "decision_time": decision_time,
                "entry_time": entry_time,
                "exit_time": exit_time,
                "direction": direction,
                "pnl": native,
                "stress_pnl": stress,
                "fold_id": fold_id,
                "regime": regime,
            }
        )
        intents.append((decision_time, entry_time, exit_time, direction, "executed"))
    trades = pd.DataFrame.from_records(records)
    if trades.empty:
        trades = pd.DataFrame(
            columns=(
                "decision_bar_open_time",
                "decision_time",
                "entry_time",
                "exit_time",
                "direction",
                "pnl",
                "stress_pnl",
                "fold_id",
                "regime",
            )
        )
    return SimulationResult(
        trades=trades,
        intent_rows=tuple(intents),
        unresolved_cost_signal_count=unresolved,
        gap_excluded_signal_count=gap_excluded,
        causality_violation_count=causality_violations,
    )


def _matched(results: list[Any], policy: str) -> Any:
    matches = [
        item
        for item in results
        if item.configuration.policy == policy
    ]
    if len(matches) != 1:
        raise DiscoveryBoundaryError("execution control is not unique")
    return matches[0]


def _populate_controls(results: list[Any]) -> None:
    for subject in results:
        configuration = subject.configuration
        execution_control = _matched(results, "unconditional_next_open")
        subject.metrics["execution_control_delta_net_profit_micropoints"] = (
            subject.metrics["net_profit_micropoints"]
            - execution_control.metrics["net_profit_micropoints"]
        )
        subject.metrics["execution_control_pvalue_upper_ppm"] = (
            1_000_000
            if configuration.policy == "unconditional_next_open"
            else _paired_control_pvalue(
                subject,
                execution_control,
                role="unconditional_next_open_control",
                total_exposures=SELECTION_TOTAL_EXPOSURES,
            )
        )


def compute_registered_cost_aware_execution_surface(
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
    features, volatility, run = _raw_features(frame)
    label = _labels(frame, volatility, run)["first_passage_label_48"]
    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_raw: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    fold_features: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_features: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    calibrations: dict[str, tuple[float, tuple[float, float], float]] = {}
    future_time = time.shift(-(HORIZON + 1))
    for fold in folds:
        fold_id = str(fold["fold_id"])
        test_end = int(time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]), side="right"))
        prefix = frame.iloc[:test_end]
        prefix_frames[fold_id] = prefix
        prefix_raw[fold_id] = _raw_features(prefix)
        prefix_spreads[fold_id] = causal_effective_spread(
            prefix["spread"].to_numpy(float), _time_ns(prefix)
        )
        train = fold["train_is"]
        start = pd.Timestamp(train["start"])
        end = pd.Timestamp(train["end"])
        selector_mask = ((time >= start) & (time <= end)).to_numpy()
        train_mask = selector_mask & (future_time <= end).fillna(False).to_numpy()
        model = _fit_model(features=features, label=label, train_mask=train_mask)
        score = _score(features, model)
        fold_features[fold_id] = (score, volatility, run)
        prefix_score = _score(prefix_raw[fold_id][0], model)
        prefix_features[fold_id] = (
            prefix_score,
            prefix_raw[fold_id][1],
            prefix_raw[fold_id][2],
        )
        prefix_time = pd.to_datetime(prefix_frames[fold_id]["time"], errors="raise")
        prefix_train = ((prefix_time >= start) & (prefix_time <= end)).to_numpy()
        volatility_values = volatility[train_mask & np.isfinite(volatility)]
        cutoffs = (
            float(np.quantile(volatility_values, 1 / 3, method="higher")),
            float(np.quantile(volatility_values, 2 / 3, method="higher")),
        )
        calibrations[fold_id] = (
            calibrate_selector(score, selector_mask),
            cutoffs,
            calibrate_selector(prefix_score, prefix_train),
        )
    results = []
    first = fold_features[str(folds[0]["fold_id"])]
    for configuration in cost_aware_execution_configurations():
        results.append(
            _evaluate_configuration(
                frame=frame,
                folds=folds,
                configuration=configuration,
                effective_spread=spread,
                features=first,
                fold_features=fold_features,
                prefix_features=prefix_features,
                prefix_spreads=prefix_spreads,
                calibrations=calibrations,
                time=time,
                executable_id=cost_aware_execution_executable(configuration).identity,
                simulation_fn=simulate_cost_aware_execution,
            )
        )
    adjusted = _selection_adjusted_pvalues(results, total_exposures=SELECTION_TOTAL_EXPOSURES)
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = adjusted[result.executable_id]
    _populate_controls(results)
    surface = {
        "claim_limits": _claim_limits()
        + [
            "execution_is_the_only_primary_changed_research_layer",
            "entry_spread_gate_uses_completed_decision_bar_proxy",
            "fixed_first_passage_signal_selector_direction_lifecycle_and_risk",
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
        "execution_implementation_sha256": cost_aware_execution_implementation_sha256(),
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "schema": "cost_aware_execution_surface.v1",
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


def project_cost_aware_execution_evaluation(
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
        or value.get("schema") != "cost_aware_execution_surface.v1"
    ):
        raise DiscoveryBoundaryError("cost-aware execution surface invalid")
    expected = executable_configuration_map()
    by_executable = {
        item.get("subject_executable_id"): item for item in value["evaluations"]
    }
    if set(by_executable) != set(expected) or subject_executable_id not in expected:
        raise DiscoveryBoundaryError("cost-aware execution subjects differ")
    payload = {
        name: job_execution[name]
        for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")
    }
    if job_execution.get("identity") != canonical_digest(
        domain="running-job-execution", payload=payload
    ):
        raise DiscoveryBoundaryError("cost-aware execution Job invalid")
    result = {
        **dict(by_executable[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "cost_aware_execution_evaluation.v1",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(result)
    return result


__all__ = [
    "CostAwareExecutionConfiguration",
    "cost_aware_execution_components",
    "cost_aware_execution_baseline",
    "cost_aware_execution_configurations",
    "cost_aware_execution_executable",
    "cost_aware_execution_implementation_sha256",
    "compute_registered_cost_aware_execution_surface",
    "executable_configuration_map",
    "loader_implementation_sha256",
    "project_cost_aware_execution_evaluation",
    "simulate_cost_aware_execution",
]
