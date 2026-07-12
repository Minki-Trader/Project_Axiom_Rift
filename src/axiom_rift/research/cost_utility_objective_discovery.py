"""Fold-trained native-utility weighted objective under a fixed label and model."""

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
    DATASET_SHA256, OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256,
    SELECTION_BOOTSTRAP_SAMPLES, SELECTION_SEED, DiscoveryBoundaryError,
    POINT, _claim_limits, _evaluate_configuration, _fold_payloads,
    _paired_control_pvalue, _selection_adjusted_pvalues, _selection_method,
    _time_ns, _validate_engine_environment, _validate_fold_payloads,
    _validate_production_data, causal_effective_spread,
    discovery_implementation_sha256,
)
from axiom_rift.research.event_label_discovery import (
    HORIZON, RIDGE_PENALTY_MILLI, _labels, _raw_features, _score,
    calibrate_selector, event_label_implementation_sha256,
)


SELECTION_TOTAL_EXPOSURES = 524
_PROFILES = ("native_utility_weighted_loss", "unweighted_directional_loss_control")
_THIS_FILE = Path(__file__).resolve()


def cost_utility_objective_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def loader_implementation_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class CostUtilityObjectiveConfiguration:
    profile: str
    signal_sign: int
    holding_bars: int = HORIZON

    def __post_init__(self) -> None:
        if self.profile not in _PROFILES or self.signal_sign not in {-1, 1} or self.holding_bars != HORIZON:
            raise ValueError("cost-utility objective configuration invalid")

    @property
    def configuration_id(self) -> str:
        return f"{self.profile}-{'direct' if self.signal_sign == 1 else 'inverse'}-h{HORIZON}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "holding_bars": HORIZON, "objective_profile": self.profile,
            "ridge_penalty_milli": RIDGE_PENALTY_MILLI,
            "selector_quantile_bp": 8500, "signal_sign": self.signal_sign,
            "utility_weight_floor_milli": 250, "utility_weight_cap_milli": 4250,
        }


def cost_utility_objective_configurations() -> tuple[CostUtilityObjectiveConfiguration, ...]:
    return tuple(CostUtilityObjectiveConfiguration(profile=profile, signal_sign=sign) for profile in _PROFILES for sign in (1, -1))


def _local(name: str) -> str:
    return f"axiom_rift.research.cost_utility_objective_discovery.{name}@sha256:{cost_utility_objective_implementation_sha256()}"


def _label(name: str) -> str:
    return f"axiom_rift.research.event_label_discovery.{name}@sha256:{event_label_implementation_sha256()}"


def _shared(name: str) -> str:
    return f"axiom_rift.research.discovery.{name}@sha256:{discovery_implementation_sha256()}"


def cost_utility_objective_components() -> tuple[ComponentSpec, ...]:
    return (
        ComponentSpec(
            display_name="fixed STU-0065 completed-bar features and first-passage label",
            protocol="label.fixed_first_passage_with_multiscale_features.v1",
            implementation=_label("build_labels"),
            spec={"feature_and_label_fixed": True, "source_study": "STU-0065"},
        ),
        ComponentSpec(
            display_name="native-utility weighted or unweighted squared objective",
            protocol="objective.native_utility_weighted_vs_unweighted.v1",
            implementation=_local("fit_objective_model"),
            spec={
                "future_end_must_be_inside_train": True,
                "native_cost_source": "causal_effective_spread",
                "parameter_fields": ["objective_profile"], "profiles": list(_PROFILES),
                "utility_quantile_cap": "train_95_percent",
                "weight_floor_milli": 250, "weight_cap_milli": 4250,
            },
        ),
        ComponentSpec(
            display_name="fixed fold-trained ridge linear model",
            protocol="model.fixed_ridge_linear_capacity.v1",
            implementation=_local("fit_objective_model"),
            spec={"penalty_milli": RIDGE_PENALTY_MILLI, "same_capacity_across_profiles": True},
        ),
        ComponentSpec(
            display_name="fixed train absolute score selector",
            protocol="selector.fixed_abs_quantile_85.v3",
            implementation=_label("calibrate_selector"),
            spec={"quantile_basis_points": 8500, "same_across_profiles": True},
        ),
        ComponentSpec(
            display_name="completed-bar next-open directional entry",
            protocol="trade.completed_bar_next_open_direction.v7",
            implementation=_shared("simulate_fixed_hold"),
            spec={"entry_time": "next_exact_bar_open", "same_across_profiles": True},
        ),
        ComponentSpec(
            display_name="fixed 48-bar nonoverlap lifecycle",
            protocol="lifecycle.fixed_hold_no_overlap.v7",
            implementation=_shared("simulate_fixed_hold"),
            spec={"holding_bars": HORIZON, "same_across_profiles": True},
        ),
        ComponentSpec(
            display_name="fixed one-lot risk",
            protocol="risk.fixed_one_lot.v5",
            implementation=_shared("simulate_fixed_hold"),
            spec={"lot": 1, "same_across_profiles": True},
        ),
        ComponentSpec(
            display_name="FPMarkets bid-bar spread execution",
            protocol="execution.fpmarkets_bid_bar_spread.v7",
            implementation=_shared("execution_pnl"),
            spec={"point": "0.01", "stress": "half_effective_spread_each_side"},
        ),
    )


def cost_utility_objective_executable(configuration: CostUtilityObjectiveConfiguration) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"cost utility objective {configuration.configuration_id}",
        components=cost_utility_objective_components(), parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v7",
        cost_contract="cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v7",
        engine_contract=(
            f"engine:cost_utility_objective_v1:python{'.'.join(str(value) for value in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"implementation_{cost_utility_objective_implementation_sha256()}:"
            f"label_{event_label_implementation_sha256()}:loader_{loader_implementation_sha256()}:"
            f"shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:"
            f"blocks_5_10_20:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def executable_configuration_map() -> dict[str, CostUtilityObjectiveConfiguration]:
    return {cost_utility_objective_executable(configuration).identity: configuration for configuration in cost_utility_objective_configurations()}


def _future_native_utility(
    frame: pd.DataFrame, label: np.ndarray, effective_spread: np.ndarray, run: np.ndarray,
) -> np.ndarray:
    count = len(frame)
    result = np.full(count, np.nan)
    last = count - HORIZON - 1
    if last <= 0:
        return result
    indices = np.arange(last)
    entry_index = indices + 1
    exit_index = indices + HORIZON + 1
    opens = frame["open"].to_numpy(float)
    direction = label[indices]
    continuous = run[exit_index] >= HORIZON + 2
    valid = (
        continuous & np.isfinite(direction) & np.isfinite(effective_spread[entry_index])
        & np.isfinite(effective_spread[exit_index])
    )
    native = np.zeros(last, dtype=float)
    long_mask = direction == 1
    short_mask = direction == -1
    native[long_mask] = opens[exit_index[long_mask]] - (
        opens[entry_index[long_mask]] + effective_spread[entry_index[long_mask]] * POINT
    )
    native[short_mask] = opens[entry_index[short_mask]] - (
        opens[exit_index[short_mask]] + effective_spread[exit_index[short_mask]] * POINT
    )
    utility = np.where(direction == 0, 0.0, np.maximum(native, 0.0))
    result[indices[valid]] = utility[valid]
    return result


def _fit_objective_model(
    *, features: np.ndarray, label: np.ndarray, utility: np.ndarray,
    train_mask: np.ndarray, profile: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    mask = train_mask & np.isfinite(label) & np.isfinite(utility) & np.isfinite(features).all(axis=1)
    if int(mask.sum()) < 1000:
        raise DiscoveryBoundaryError("cost-utility objective training set too small")
    x, y, u = features[mask], label[mask], utility[mask]
    mean = x.mean(axis=0)
    std = x.std(axis=0, ddof=0)
    std = np.where(std > 0, std, 1.0)
    z = (x - mean) / std
    if profile == "unweighted_directional_loss_control":
        weights = np.ones(len(y), dtype=float)
    elif profile == "native_utility_weighted_loss":
        positive = u[u > 0]
        if len(positive) < 100:
            raise DiscoveryBoundaryError("positive native utility training set too small")
        scale = float(np.quantile(positive, 0.95, method="higher"))
        if not np.isfinite(scale) or scale <= 0:
            raise DiscoveryBoundaryError("native utility weight scale is invalid")
        weights = 0.25 + np.minimum(u / scale, 4.0)
    else:
        raise DiscoveryBoundaryError("cost-utility objective profile is invalid")
    weight_sum = float(weights.sum())
    y_mean = float(np.dot(weights, y) / weight_sum)
    weighted_z = z * weights[:, None]
    penalty = RIDGE_PENALTY_MILLI / 1000.0
    beta = np.linalg.solve(
        z.T @ weighted_z + penalty * np.eye(z.shape[1]),
        z.T @ (weights * (y - y_mean)),
    )
    if not np.isfinite(beta).all():
        raise DiscoveryBoundaryError("cost-utility objective model is nonfinite")
    return mean, std, beta, y_mean


def _matched(results: list[Any], profile: str, signal_sign: int) -> Any:
    found = [result for result in results if result.configuration.profile == profile and result.configuration.signal_sign == signal_sign]
    if len(found) != 1:
        raise DiscoveryBoundaryError("cost-utility objective control is not unique")
    return found[0]


def _populate_controls(results: list[Any]) -> None:
    for subject in results:
        configuration = subject.configuration
        opposite = _matched(results, configuration.profile, -configuration.signal_sign)
        control_profile = next(profile for profile in _PROFILES if profile != configuration.profile)
        objective_control = _matched(results, control_profile, configuration.signal_sign)
        subject.metrics["opposite_sign_worst_delta_net_profit_micropoints"] = subject.metrics["net_profit_micropoints"] - opposite.metrics["net_profit_micropoints"]
        subject.metrics["opposite_sign_pvalue_upper_ppm"] = _paired_control_pvalue(subject, opposite, role="opposite_sign", total_exposures=SELECTION_TOTAL_EXPOSURES)
        subject.metrics["feature_control_worst_delta_net_profit_micropoints"] = subject.metrics["net_profit_micropoints"] - objective_control.metrics["net_profit_micropoints"]
        subject.metrics["feature_control_worst_pvalue_upper_ppm"] = _paired_control_pvalue(subject, objective_control, role="unweighted_objective_control", total_exposures=SELECTION_TOTAL_EXPOSURES)


def compute_registered_cost_utility_objective_surface(repository_root: str | Path) -> dict[str, Any]:
    _validate_engine_environment()
    data = load_observed_development(Path(repository_root).resolve())
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = causal_effective_spread(frame["spread"].to_numpy(float), _time_ns(frame))
    full_features, full_volatility, full_run = _raw_features(frame)
    label = _labels(frame, full_volatility, full_run)["first_passage_label_48"]
    utility = _future_native_utility(frame, label, spread, full_run)
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
        start, end = pd.Timestamp(train["start"]), pd.Timestamp(train["end"])
        selector_mask = ((time >= start) & (time <= end)).to_numpy()
        model_mask = selector_mask & (future_time <= end).fillna(False).to_numpy()
        prefix_time = pd.to_datetime(prefix_frames[fold_id]["time"], errors="raise")
        prefix_selector = ((prefix_time >= start) & (prefix_time <= end)).to_numpy()
        volatility_values = full_volatility[selector_mask & np.isfinite(full_volatility)]
        cutoffs = (float(np.quantile(volatility_values, 1 / 3, method="higher")), float(np.quantile(volatility_values, 2 / 3, method="higher")))
        for profile in _PROFILES:
            model = _fit_objective_model(features=full_features, label=label, utility=utility, train_mask=model_mask, profile=profile)
            score = _score(full_features, model)
            prefix_score = _score(prefix_raw[fold_id][0], model)
            threshold = calibrate_selector(score, selector_mask)
            prefix_threshold = calibrate_selector(prefix_score, prefix_selector)
            if threshold != prefix_threshold:
                raise DiscoveryBoundaryError("objective selector threshold drifted")
            fold_sets[profile][fold_id] = (score, full_volatility, full_run)
            prefix_sets[profile][fold_id] = (prefix_score, prefix_raw[fold_id][1], prefix_raw[fold_id][2])
            calibrations[profile][fold_id] = (threshold, cutoffs, prefix_threshold)
    results = []
    for configuration in cost_utility_objective_configurations():
        first = fold_sets[configuration.profile][str(folds[0]["fold_id"])]
        results.append(_evaluate_configuration(
            calibrations=calibrations[configuration.profile], frame=frame, features=first,
            fold_features=fold_sets[configuration.profile], folds=folds, configuration=configuration,
            effective_spread=spread, prefix_features=prefix_sets[configuration.profile],
            prefix_spreads=prefix_spreads, time=time,
            executable_id=cost_utility_objective_executable(configuration).identity,
        ))
    adjusted = _selection_adjusted_pvalues(results, total_exposures=SELECTION_TOTAL_EXPOSURES)
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = adjusted[result.executable_id]
    _populate_controls(results)
    surface = {
        "claim_limits": _claim_limits() + [
            "objective_is_the_only_primary_changed_research_layer",
            "first_passage_label_and_ridge_capacity_are_fixed",
            "native_utility_weights_use_train_contained_future_paths_and_causal_spread",
            "utility_weight_floor_and_cap_are_preregistered", "four_trial_surface",
        ],
        "cost_utility_objective_implementation_sha256": cost_utility_objective_implementation_sha256(),
        "dataset_sha256": DATASET_SHA256,
        "engine_environment": {"numpy": np.__version__, "pandas": pd.__version__, "python": ".".join(str(value) for value in sys.version_info[:3]), "scipy": scipy.__version__},
        "evaluations": [{
            "direction_metrics": result.direction_metrics,
            "evaluable": all(result.metrics[name] == 0 for name in ("unknown_cost_unresolved_signal_count", "causality_violation_count", "nonfinite_metric_count", "prefix_invariance_mismatch_count", "append_invariance_mismatch_count")),
            "fold_metrics": result.fold_metrics, "metrics": dict(sorted(result.metrics.items())),
            "regime_metrics": result.regime_metrics, "session_metrics": result.session_metrics,
            "subject_configuration_id": result.configuration.configuration_id,
            "subject_executable_id": result.executable_id,
        } for result in results],
        "event_label_implementation_sha256": event_label_implementation_sha256(),
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID, "schema": "cost_utility_objective_surface.v1",
        "selection_context": [{"configuration_id": result.configuration.configuration_id, "executable_id": result.executable_id, "net_profit_micropoints": result.metrics["net_profit_micropoints"], "selection_aware_pvalue_ppm": result.metrics["selection_aware_pvalue_ppm"]} for result in results],
        "selection_method": _selection_method(SELECTION_TOTAL_EXPOSURES),
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
    }
    canonical_bytes(surface)
    return surface


def project_cost_utility_objective_evaluation(
    surface: Mapping[str, Any], *, job_execution: Mapping[str, str], subject_executable_id: str,
    surface_artifact_hash: str, surface_manifest_hash: str,
) -> dict[str, Any]:
    value = dict(surface)
    if sha256(canonical_bytes(value)).hexdigest() != surface_artifact_hash or value.get("schema") != "cost_utility_objective_surface.v1":
        raise DiscoveryBoundaryError("cost-utility objective surface invalid")
    expected = executable_configuration_map()
    by_executable = {item.get("subject_executable_id"): item for item in value["evaluations"]}
    if set(by_executable) != set(expected) or subject_executable_id not in expected:
        raise DiscoveryBoundaryError("cost-utility objective subjects differ")
    payload = {name: job_execution[name] for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")}
    if job_execution.get("identity") != canonical_digest(domain="running-job-execution", payload=payload):
        raise DiscoveryBoundaryError("cost-utility objective Job invalid")
    result = {
        **dict(by_executable[subject_executable_id]), "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution), "schema": "cost_utility_objective_evaluation.v1",
        "selection_context": value["selection_context"], "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"], "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(result)
    return result


__all__ = [
    "CostUtilityObjectiveConfiguration", "compute_registered_cost_utility_objective_surface",
    "cost_utility_objective_configurations", "cost_utility_objective_executable",
    "cost_utility_objective_implementation_sha256", "executable_configuration_map",
    "loader_implementation_sha256", "project_cost_utility_objective_evaluation",
]
