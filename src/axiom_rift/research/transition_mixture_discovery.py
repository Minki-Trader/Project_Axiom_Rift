"""Fold-trained discrete drawdown-volatility transition-mixture discovery."""
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
    _consecutive_run,
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


SELECTION_TOTAL_EXPOSURES = 460
SELECTOR_QUANTILE_BP = 8_500
PEAK_WINDOW = 576
VOLATILITY_WINDOW = 96
HORIZON = 24
_PROFILES = ("joint_drawdown_volatility_transition", "drawdown_transition_control")
_THIS_FILE = Path(__file__).resolve()


def transition_mixture_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def loader_implementation_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class TransitionMixtureConfiguration:
    profile: str
    signal_sign: int
    holding_bars: int = HORIZON

    def __post_init__(self) -> None:
        if (
            self.profile not in _PROFILES
            or self.signal_sign not in {-1, 1}
            or self.holding_bars != HORIZON
        ):
            raise ValueError("transition-mixture configuration invalid")

    @property
    def configuration_id(self) -> str:
        direction = "learned" if self.signal_sign == 1 else "inverse"
        return f"{self.profile}-{direction}-h{HORIZON}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "holding_bars": HORIZON,
            "profile": self.profile,
            "peak_window": PEAK_WINDOW,
            "selector_quantile_bp": SELECTOR_QUANTILE_BP,
            "signal_sign": self.signal_sign,
            "volatility_window": VOLATILITY_WINDOW,
        }


def transition_mixture_configurations() -> tuple[TransitionMixtureConfiguration, ...]:
    return tuple(
        TransitionMixtureConfiguration(profile=profile, signal_sign=sign)
        for profile in _PROFILES
        for sign in (1, -1)
    )


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.transition_mixture_discovery.{name}"
        f"@sha256:{transition_mixture_implementation_sha256()}"
    )


def _shared(name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{name}"
        f"@sha256:{discovery_implementation_sha256()}"
    )


def transition_mixture_components() -> tuple[ComponentSpec, ...]:
    return (
        ComponentSpec(
            display_name="fold-trained discrete transition response table",
            protocol="model.fold_train_discrete_transition_table.v1",
            implementation=_local("fit_fold_transition"),
            spec={
                "availability": "train_is_only",
                "horizon_bars": HORIZON,
                "joint_states": ["drawdown_depth_576", "volatility_level_96"],
                "control_state": "drawdown_depth_576_only",
                "parameter_fields": ["profile"],
                "target_labels_must_end_inside_train": True,
            },
        ),
        ComponentSpec(
            display_name="fold-isolated absolute response selector",
            protocol="selector.fold_train_abs_quantile.v2",
            implementation=_local("calibrate_selector"),
            spec={
                "calibration_role": "train_is_only",
                "minimum_train_observations": 1000,
                "quantile_basis_points": SELECTOR_QUANTILE_BP,
                "quantile_method": "higher",
            },
        ),
        ComponentSpec(
            display_name="completed-bar next-open directional entry",
            protocol="trade.completed_bar_next_open_direction.v2",
            implementation=_shared("simulate_fixed_hold"),
            spec={
                "decision_time": "bar_open_plus_5m",
                "entry_time": "next_exact_bar_open",
                "direction": "signal_sign_times_score_sign",
                "parameter_fields": ["signal_sign"],
            },
        ),
        ComponentSpec(
            display_name="fixed-hold nonoverlap lifecycle",
            protocol="lifecycle.fixed_hold_no_overlap.v2",
            implementation=_shared("simulate_fixed_hold"),
            spec={
                "entry_overlap": "reject_while_position_slot_is_occupied",
                "exit_surface": f"exact_bar_open_after_{HORIZON}_bars",
                "gap_action": "exclude_path",
            },
        ),
        ComponentSpec(
            display_name="FPMarkets bid-bar spread execution",
            protocol="execution.fpmarkets_bid_bar_spread.v2",
            implementation=_shared("execution_pnl"),
            spec={"point": "0.01", "stress": "half_effective_spread_each_side"},
        ),
        ComponentSpec(
            display_name="fixed one-lot risk",
            protocol="risk.fixed_one_lot.v1",
            implementation=_shared("simulate_fixed_hold"),
            spec={"dynamic_sizing": False, "lot": 1, "positions_per_sleeve": 1},
        ),
    )


def transition_mixture_executable(
    configuration: TransitionMixtureConfiguration,
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"transition mixture {configuration.configuration_id}",
        components=transition_mixture_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development"
        ),
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v2",
        cost_contract=(
            "cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v2"
        ),
        engine_contract=(
            f"engine:transition_mixture_v2:python"
            f"{'.'.join(str(v) for v in sys.version_info[:3])}:numpy{np.__version__}:"
            f"pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"implementation_{transition_mixture_implementation_sha256()}:"
            f"loader_{loader_implementation_sha256()}:"
            f"shared_{discovery_implementation_sha256()}:"
            f"bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:"
            f"bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def executable_configuration_map() -> dict[str, TransitionMixtureConfiguration]:
    return {
        transition_mixture_executable(configuration).identity: configuration
        for configuration in transition_mixture_configurations()
    }


def _raw_states(
    frame: pd.DataFrame,
    profile: str,
    volatility_threshold: float,
    drawdown_threshold: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if profile not in _PROFILES:
        raise ValueError("transition-mixture profile invalid")
    close = frame["close"].to_numpy(float)
    log_close = np.log(close)
    peak = (
        pd.Series(close)
        .rolling(PEAK_WINDOW, min_periods=PEAK_WINDOW)
        .max()
        .to_numpy(float)
    )
    drawdown = np.divide(
        close,
        peak,
        out=np.full(len(close), np.nan),
        where=np.isfinite(peak) & (peak > 0),
    ) - 1
    one_bar = np.full(len(close), np.nan)
    one_bar[1:] = np.diff(log_close)
    volatility = (
        pd.Series(one_bar)
        .rolling(VOLATILITY_WINDOW, min_periods=VOLATILITY_WINDOW)
        .std(ddof=1)
        .to_numpy(float)
    )
    drawdown_state = np.where(drawdown >= drawdown_threshold, 1, 0).astype(
        np.int64
    )
    if profile == "joint_drawdown_volatility_transition":
        volatility_state = np.where(volatility >= volatility_threshold, 1, 0)
        state = drawdown_state * 2 + volatility_state
        state_count = 4
    else:
        state = drawdown_state
        state_count = 2
    valid = np.isfinite(drawdown) & np.isfinite(volatility)
    state = np.where(valid, state, -1)
    transition = np.full(len(close), -1, dtype=np.int64)
    transition[1:] = np.where(
        valid[1:] & valid[:-1],
        state[:-1] * state_count + state[1:],
        -1,
    )
    return transition, volatility, _consecutive_run(_time_ns(frame))


def fit_fold_transition(
    frame: pd.DataFrame,
    profile: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    time = pd.to_datetime(frame["time"], errors="raise")
    close = np.log(frame["close"].to_numpy(float))
    one_bar = np.full(len(close), np.nan)
    one_bar[1:] = np.diff(close)
    volatility = (
        pd.Series(one_bar)
        .rolling(VOLATILITY_WINDOW, min_periods=VOLATILITY_WINDOW)
        .std(ddof=1)
        .to_numpy(float)
    )
    train_mask = ((time >= train_start) & (time <= train_end)).to_numpy()
    train_volatility = volatility[train_mask & np.isfinite(volatility)]
    if len(train_volatility) < 1000:
        raise DiscoveryBoundaryError("transition volatility train too small")
    volatility_threshold = float(
        np.quantile(train_volatility, 0.5, method="higher")
    )
    peak = (
        pd.Series(np.exp(close))
        .rolling(PEAK_WINDOW, min_periods=PEAK_WINDOW)
        .max()
        .to_numpy(float)
    )
    drawdown = np.divide(
        np.exp(close),
        peak,
        out=np.full(len(close), np.nan),
        where=np.isfinite(peak) & (peak > 0),
    ) - 1
    train_drawdown = drawdown[train_mask & np.isfinite(drawdown)]
    if len(train_drawdown) < 1000:
        raise DiscoveryBoundaryError("transition drawdown train too small")
    drawdown_threshold = float(
        np.quantile(train_drawdown, 0.5, method="higher")
    )
    transition, volatility, run = _raw_states(
        frame, profile, volatility_threshold, drawdown_threshold
    )
    target = np.full(len(close), np.nan)
    target[:-HORIZON] = close[HORIZON:] - close[:-HORIZON]
    future_time = time.shift(-HORIZON)
    fit_mask = (
        train_mask
        & (transition >= 0)
        & np.isfinite(target)
        & (future_time <= train_end).to_numpy()
    )
    if int(fit_mask.sum()) < 1000:
        raise DiscoveryBoundaryError("transition response train too small")
    table: dict[int, float] = {}
    for key in np.unique(transition[fit_mask]):
        values = target[fit_mask & (transition == key)]
        if len(values) >= 25:
            table[int(key)] = float(values.mean())
    score = np.full(len(close), np.nan)
    for key, value in table.items():
        score[transition == key] = value
    score[run < max(PEAK_WINDOW, VOLATILITY_WINDOW) + 1] = np.nan
    return score, volatility, run


def calibrate_selector(score: np.ndarray, mask: np.ndarray) -> float:
    values = np.abs(score[mask & np.isfinite(score)])
    if len(values) < 1000:
        raise DiscoveryBoundaryError("transition selector too small")
    return float(
        np.quantile(values, SELECTOR_QUANTILE_BP / 10000, method="higher")
    )


def _matched(results: list[Any], profile: str, sign: int) -> Any:
    found = [
        result
        for result in results
        if result.configuration.profile == profile
        and result.configuration.signal_sign == sign
    ]
    if len(found) != 1:
        raise DiscoveryBoundaryError("transition control not unique")
    return found[0]


def _populate_controls(results: list[Any]) -> None:
    for subject in results:
        configuration = subject.configuration
        opposite = _matched(
            results, configuration.profile, -configuration.signal_sign
        )
        control_profile = next(
            profile for profile in _PROFILES if profile != configuration.profile
        )
        control = _matched(results, control_profile, configuration.signal_sign)
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
            - control.metrics["net_profit_micropoints"]
        )
        subject.metrics["feature_control_worst_pvalue_upper_ppm"] = (
            _paired_control_pvalue(
                subject,
                control,
                role="standalone_transition_control",
                total_exposures=SELECTION_TOTAL_EXPOSURES,
            )
        )


def compute_registered_transition_mixture_surface(
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
    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        prefix_end = int(
            time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]), side="right")
        )
        prefix_frames[fold_id] = frame.iloc[:prefix_end]
        prefix_spreads[fold_id] = causal_effective_spread(
            prefix_frames[fold_id]["spread"].to_numpy(float),
            _time_ns(prefix_frames[fold_id]),
        )
    results = []
    for configuration in transition_mixture_configurations():
        fold_features = {}
        prefix_features = {}
        calibrations = {}
        for fold in folds:
            fold_id = str(fold["fold_id"])
            train = fold["train_is"]
            start = pd.Timestamp(train["start"])
            end = pd.Timestamp(train["end"])
            value = fit_fold_transition(frame, configuration.profile, start, end)
            prefix = fit_fold_transition(
                prefix_frames[fold_id], configuration.profile, start, end
            )
            fold_features[fold_id] = value
            prefix_features[fold_id] = prefix
            mask = ((time >= start) & (time <= end)).to_numpy()
            prefix_time = pd.to_datetime(
                prefix_frames[fold_id]["time"], errors="raise"
            )
            prefix_mask = ((prefix_time >= start) & (prefix_time <= end)).to_numpy()
            train_volatility = value[1][mask & np.isfinite(value[1])]
            cutoffs = (
                float(np.quantile(train_volatility, 1 / 3, method="higher")),
                float(np.quantile(train_volatility, 2 / 3, method="higher")),
            )
            calibrations[fold_id] = (
                calibrate_selector(value[0], mask),
                cutoffs,
                calibrate_selector(prefix[0], prefix_mask),
            )
        first = fold_features[str(folds[0]["fold_id"])]
        results.append(
            _evaluate_configuration(
                calibrations=calibrations,
                frame=frame,
                features=first,
                fold_features=fold_features,
                folds=folds,
                configuration=configuration,
                effective_spread=spread,
                prefix_features=prefix_features,
                prefix_spreads=prefix_spreads,
                time=time,
                executable_id=transition_mixture_executable(configuration).identity,
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
            "transition_tables_are_fold_train_only",
            "drawdown_volatility_joint_state_only",
            "four_trial_surface",
        ],
        "dataset_sha256": DATASET_SHA256,
        "engine_environment": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "python": ".".join(str(v) for v in sys.version_info[:3]),
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
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "schema": "transition_mixture_surface.v2",
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
        "transition_mixture_implementation_sha256": (
            transition_mixture_implementation_sha256()
        ),
    }
    canonical_bytes(surface)
    return surface


def project_transition_mixture_evaluation(
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
        or value.get("schema") != "transition_mixture_surface.v2"
    ):
        raise DiscoveryBoundaryError("transition-mixture surface invalid")
    expected = executable_configuration_map()
    by_identity = {
        item.get("subject_executable_id"): item for item in value["evaluations"]
    }
    if set(by_identity) != set(expected) or subject_executable_id not in expected:
        raise DiscoveryBoundaryError("transition-mixture subjects differ")
    payload = {
        name: job_execution[name]
        for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")
    }
    if job_execution.get("identity") != canonical_digest(
        domain="running-job-execution", payload=payload
    ):
        raise DiscoveryBoundaryError("Job invalid")
    result = {
        **dict(by_identity[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "transition_mixture_evaluation.v2",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(result)
    return result


__all__ = [
    "compute_registered_transition_mixture_surface",
    "executable_configuration_map",
    "fit_fold_transition",
    "loader_implementation_sha256",
    "project_transition_mixture_evaluation",
    "transition_mixture_configurations",
    "transition_mixture_executable",
    "transition_mixture_implementation_sha256",
]
