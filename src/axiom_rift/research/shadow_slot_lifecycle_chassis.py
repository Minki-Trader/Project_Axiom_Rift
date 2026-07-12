"""Volatility-stop signal with controlled post-exit slot reservation semantics."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research import data as data_module
from axiom_rift.research.discovery import (
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    SELECTION_BOOTSTRAP_SAMPLES,
    SELECTION_SEED,
    SimulationResult,
    _time_ns,
    causal_effective_spread,
    discovery_implementation_sha256,
    execution_pnl,
)
from axiom_rift.research.event_label_discovery import (
    HORIZON,
    RIDGE_PENALTY_MILLI,
    event_label_implementation_sha256,
)
from axiom_rift.research.volatility_clock_label_chassis import (
    VOLATILITY_BUDGET_BARS,
    volatility_clock_label_chassis_implementation_sha256,
)


SELECTION_TOTAL_EXPOSURES = 536
SELECTOR_QUANTILE_BP = 8_500
_POLICIES = ("immediate_reuse_control", "shadow_reserve_original_expiry")
_THIS_FILE = Path(__file__).resolve()
_FIVE_MINUTES_NS = 300_000_000_000


def shadow_slot_lifecycle_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def loader_implementation_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class ShadowSlotLifecycleConfiguration:
    lifecycle_policy: str
    signal_sign: int = 1
    holding_bars: int = HORIZON

    def __post_init__(self) -> None:
        if (
            self.lifecycle_policy not in _POLICIES
            or self.signal_sign != 1
            or self.holding_bars != HORIZON
        ):
            raise ValueError("shadow-slot lifecycle configuration invalid")

    @property
    def configuration_id(self) -> str:
        return f"{self.lifecycle_policy}-stop-maxh{HORIZON}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "holding_bars": HORIZON,
            "label_profile": "volatility_clock_terminal_12_of_48",
            "lifecycle_policy": self.lifecycle_policy,
            "ridge_penalty_milli": RIDGE_PENALTY_MILLI,
            "risk_policy": "pre_entry_volatility_loss_stop",
            "selector_quantile_bp": SELECTOR_QUANTILE_BP,
            "signal_sign": self.signal_sign,
            "stop_volatility_budget_bars": VOLATILITY_BUDGET_BARS,
        }


def shadow_slot_lifecycle_configurations(
) -> tuple[ShadowSlotLifecycleConfiguration, ...]:
    return tuple(ShadowSlotLifecycleConfiguration(value) for value in _POLICIES)


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.shadow_slot_lifecycle_chassis.{name}"
        f"@sha256:{shadow_slot_lifecycle_chassis_implementation_sha256()}"
    )


def _event(name: str) -> str:
    return (
        f"axiom_rift.research.event_label_discovery.{name}"
        f"@sha256:{event_label_implementation_sha256()}"
    )


def _volatility_label(name: str) -> str:
    return (
        f"axiom_rift.research.volatility_clock_label_chassis.{name}"
        f"@sha256:{volatility_clock_label_chassis_implementation_sha256()}"
    )


def shadow_slot_lifecycle_components() -> tuple[ComponentSpec, ...]:
    feature = ComponentSpec(
        display_name="fixed completed-bar multiscale predictor inputs",
        protocol="feature.fixed_multiscale_return_path.v1",
        implementation=_event("raw_features"),
        spec={
            "availability": "completed_bar_only",
            "fields": [
                "normalized_return_12", "normalized_return_48",
                "normalized_return_192", "path_efficiency_48",
                "volatility_ratio_48_192",
            ],
        },
    )
    label = ComponentSpec(
        display_name="fixed volatility-clock terminal label",
        protocol="label.volatility_clock_terminal.v1",
        implementation=_volatility_label("build_labels"),
        spec={
            "maximum_horizon_bars": HORIZON,
            "profile": "volatility_clock_terminal_12_of_48",
            "volatility_budget_bars": VOLATILITY_BUDGET_BARS,
        },
    )
    model = ComponentSpec(
        display_name="fixed fold-trained ridge score",
        protocol="model.fold_train_ridge_linear.v1",
        implementation=_event("fit_fold_model"),
        spec={
            "fit_role": "train_is_only", "penalty_milli": RIDGE_PENALTY_MILLI,
            "standardization": "train_mean_population_std",
        },
        semantic_dependencies=(feature.identity, label.identity),
    )
    selector = ComponentSpec(
        display_name="fixed train-only absolute score selector",
        protocol="selector.fold_train_abs_quantile.v3",
        implementation=_event("calibrate_selector"),
        spec={
            "calibration_role": "train_is_only", "minimum_train_observations": 1000,
            "quantile_basis_points": SELECTOR_QUANTILE_BP, "quantile_method": "higher",
        },
        semantic_dependencies=(model.identity,),
    )
    trade = ComponentSpec(
        display_name="fixed completed-bar next-open directional entry",
        protocol="trade.completed_bar_next_open_direction.v3",
        implementation=_local("simulate_shadow_slot_lifecycle"),
        spec={
            "decision_time": "bar_open_plus_5m",
            "direction": "signal_sign_times_score_sign",
            "parameter_fields": ["signal_sign"],
        },
        semantic_dependencies=(selector.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="post-stop immediate reuse versus shadow reservation lifecycle",
        protocol="lifecycle.post_stop_slot_reservation.v1",
        implementation=_local("simulate_shadow_slot_lifecycle"),
        spec={
            "entry_overlap": "reject_while_position_or_shadow_slot_is_occupied",
            "maximum_exit_surface": "exact_bar_open_after_48_bars",
            "parameter_fields": ["lifecycle_policy"],
            "policies": list(_POLICIES),
            "risk_exit": "pre_entry_fixed_loss_distance",
        },
        semantic_dependencies=(trade.identity,),
    )
    risk = ComponentSpec(
        display_name="fixed-lot fixed volatility loss-stop risk",
        protocol="risk.pre_entry_volatility_loss_stop.v2",
        implementation=_local("simulate_shadow_slot_lifecycle"),
        spec={
            "dynamic_sizing": False, "lot": 1,
            "policy": "pre_entry_volatility_loss_stop",
            "stop_volatility_budget_bars": VOLATILITY_BUDGET_BARS,
        },
        semantic_dependencies=(lifecycle.identity,),
    )
    execution = ComponentSpec(
        display_name="fixed FPMarkets bid-open spread execution",
        protocol="execution.fpmarkets_bid_open_spread.v1",
        implementation=_local("simulate_shadow_slot_lifecycle"),
        spec={"point": "0.01", "stress": "half_effective_spread_each_side"},
        semantic_dependencies=(risk.identity,),
    )
    return feature, label, model, selector, trade, lifecycle, risk, execution


def shadow_slot_lifecycle_executable(
    configuration: ShadowSlotLifecycleConfiguration,
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"shadow slot lifecycle {configuration.configuration_id}",
        components=shadow_slot_lifecycle_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v3",
        cost_contract="cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v3",
        engine_contract=(
            f"engine:shadow_slot_lifecycle_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"chassis_{shadow_slot_lifecycle_chassis_implementation_sha256()}:"
            f"label_{volatility_clock_label_chassis_implementation_sha256()}:"
            f"event_{event_label_implementation_sha256()}:loader_{loader_implementation_sha256()}:"
            f"shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:"
            f"blocks_5_10_20:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def shadow_slot_lifecycle_baseline() -> ExecutableSpec:
    return shadow_slot_lifecycle_executable(shadow_slot_lifecycle_configurations()[0])


def executable_configuration_map() -> dict[str, ShadowSlotLifecycleConfiguration]:
    return {
        shadow_slot_lifecycle_executable(value).identity: value
        for value in shadow_slot_lifecycle_configurations()
    }


def simulate_shadow_slot_lifecycle(
    *, frame: pd.DataFrame, score: np.ndarray, volatility: np.ndarray,
    run: np.ndarray, threshold: float,
    configuration: ShadowSlotLifecycleConfiguration,
    test_start: pd.Timestamp, test_end: pd.Timestamp, fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray | None = None,
) -> SimulationResult:
    time = pd.to_datetime(frame["time"], errors="raise")
    time_ns = _time_ns(frame)
    opens = pd.to_numeric(frame["open"], errors="raise").to_numpy(float)
    log_open = np.log(opens)
    spreads = (
        causal_effective_spread(frame["spread"].to_numpy(float), time_ns)
        if effective_spread is None else np.asarray(effective_spread, float)
    )
    candidates = np.flatnonzero(
        ((time >= test_start) & (time <= test_end)).to_numpy() & np.isfinite(score)
    )
    records: list[dict[str, Any]] = []
    intents: list[tuple[Any, ...]] = []
    next_decision_index = -1
    unresolved = gap_excluded = causality_violations = 0
    for decision_index in candidates:
        if decision_index < next_decision_index or abs(score[decision_index]) < threshold:
            continue
        direction = int(np.sign(score[decision_index])) * configuration.signal_sign
        if direction == 0:
            continue
        entry_index = decision_index + 1
        maximum_exit = entry_index + configuration.holding_bars
        if maximum_exit >= len(frame) or time.iloc[maximum_exit] > test_end:
            continue
        decision_time = time.iloc[decision_index] + pd.Timedelta(minutes=5)
        entry_time = time.iloc[entry_index]
        if time_ns[entry_index] - time_ns[decision_index] != _FIVE_MINUTES_NS:
            gap_excluded += 1
            intents.append((decision_time, entry_time, time.iloc[maximum_exit], direction, "gap_excluded"))
            continue
        if decision_time != entry_time:
            causality_violations += 1
            intents.append((decision_time, entry_time, time.iloc[maximum_exit], direction, "causality_violation"))
            continue
        loss_distance = float(volatility[decision_index]) * np.sqrt(VOLATILITY_BUDGET_BARS)
        exit_index = maximum_exit
        for candidate_exit in range(entry_index + 1, maximum_exit + 1):
            signed_return = direction * (log_open[candidate_exit] - log_open[entry_index])
            if signed_return <= -loss_distance:
                exit_index = candidate_exit
                break
        if run[exit_index] < exit_index - entry_index + 2:
            gap_excluded += 1
            intents.append((decision_time, entry_time, time.iloc[exit_index], direction, "gap_excluded"))
            continue
        next_decision_index = (
            exit_index
            if configuration.lifecycle_policy == "immediate_reuse_control"
            else maximum_exit
        )
        if not (np.isfinite(spreads[entry_index]) and np.isfinite(spreads[exit_index])):
            unresolved += 1
            intents.append((decision_time, entry_time, time.iloc[exit_index], direction, "unknown_cost"))
            continue
        native, stress = execution_pnl(
            direction=direction, entry_bid=float(opens[entry_index]),
            exit_bid=float(opens[exit_index]),
            entry_spread_points=float(spreads[entry_index]),
            exit_spread_points=float(spreads[exit_index]),
        )
        entry_volatility = float(volatility[decision_index])
        regime = (
            "low" if entry_volatility <= regime_cutoffs[0]
            else "high" if entry_volatility >= regime_cutoffs[1] else "middle"
        )
        records.append({
            "decision_bar_open_time": time.iloc[decision_index],
            "decision_time": decision_time, "entry_time": entry_time,
            "exit_time": time.iloc[exit_index], "direction": direction,
            "pnl": native, "stress_pnl": stress, "fold_id": fold_id,
            "regime": regime,
        })
        intents.append((decision_time, entry_time, time.iloc[exit_index], direction, "executed"))
    trades = pd.DataFrame.from_records(records)
    if trades.empty:
        trades = pd.DataFrame(columns=(
            "decision_bar_open_time", "decision_time", "entry_time", "exit_time",
            "direction", "pnl", "stress_pnl", "fold_id", "regime",
        ))
    return SimulationResult(
        trades=trades, intent_rows=tuple(intents),
        unresolved_cost_signal_count=unresolved,
        gap_excluded_signal_count=gap_excluded,
        causality_violation_count=causality_violations,
    )


__all__ = [
    "SELECTION_TOTAL_EXPOSURES", "ShadowSlotLifecycleConfiguration",
    "executable_configuration_map", "loader_implementation_sha256",
    "shadow_slot_lifecycle_baseline",
    "shadow_slot_lifecycle_chassis_implementation_sha256",
    "shadow_slot_lifecycle_components", "shadow_slot_lifecycle_configurations",
    "shadow_slot_lifecycle_executable", "simulate_shadow_slot_lifecycle",
]
