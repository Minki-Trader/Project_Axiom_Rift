"""Causal monthly realized-loss entry lock on the dense regime router."""
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
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256, SELECTION_BOOTSTRAP_SAMPLES, SELECTION_SEED, SimulationResult, _time_ns, causal_effective_spread, completed_bar_execution_spreads, discovery_implementation_sha256, execution_pnl
from axiom_rift.research.regime_direction_router_chassis import loader_implementation_sha256, regime_direction_router_components

SELECTION_TOTAL_EXPOSURES = 548
_POLICIES = ("unrestricted_router_control", "monthly_break_even_entry_lock")
_FIVE_MINUTES_NS = 300_000_000_000
_THIS_FILE = Path(__file__).resolve()


def monthly_loss_lock_risk_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class MonthlyLossLockRiskConfiguration:
    risk_policy: str
    signal_sign: int = 1
    holding_bars: int = 12

    def __post_init__(self) -> None:
        if self.risk_policy not in _POLICIES or self.signal_sign != 1 or self.holding_bars != 12:
            raise ValueError("monthly loss lock risk configuration invalid")

    @property
    def label_profile(self) -> str:
        return "terminal_return_sign_12"

    @property
    def selector_quantile_bp(self) -> int:
        return 7000

    @property
    def route_policy(self) -> str:
        return "high_long_calm_inverse_router"

    @property
    def configuration_id(self) -> str:
        return f"{self.risk_policy}-dense12"

    def semantic_parameters(self) -> dict[str, Any]:
        return {"holding_bars": 12, "label_profile": self.label_profile, "profile": "dense_regime_direction_router", "ridge_penalty_milli": 1000, "risk_policy": self.risk_policy, "route_policy": self.route_policy, "selector_quantile_bp": 7000, "signal_sign": 1}


def monthly_loss_lock_risk_configurations() -> tuple[MonthlyLossLockRiskConfiguration, ...]:
    return tuple(MonthlyLossLockRiskConfiguration(value) for value in _POLICIES)


def _local(name: str) -> str:
    return f"axiom_rift.research.monthly_loss_lock_risk_chassis.{name}@sha256:{monthly_loss_lock_risk_chassis_implementation_sha256()}"


def monthly_loss_lock_risk_components() -> tuple[ComponentSpec, ...]:
    feature, label, model, selector, regime, synthesis, trade, lifecycle, _, _ = regime_direction_router_components()
    risk = ComponentSpec(display_name="fixed one-lot causal monthly realized-loss entry lock", protocol="risk.monthly_realized_break_even_entry_lock.v1", implementation=_local("simulate_monthly_loss_lock_risk"), spec={"dynamic_sizing": False, "lock_rule": "after_exit_realized_month_pnl_below_zero_block_new_entries_until_next_broker_month", "lot": 1, "parameter_fields": ["risk_policy"], "policies": list(_POLICIES), "threshold": "economic_break_even_zero_no_fitted_parameter"}, semantic_dependencies=(lifecycle.identity,))
    execution = ComponentSpec(display_name="fixed FPMarkets completed-period spread proxy execution", protocol="execution.fpmarkets_completed_bar_spread_proxy.v1", implementation=_local("simulate_monthly_loss_lock_risk"), spec={"entry_proxy": "entry_index_minus_1", "exit_proxy": "exit_index_minus_1", "point": "0.01", "stress": "half_effective_spread_each_side"}, semantic_dependencies=(risk.identity,))
    return feature, label, model, selector, regime, synthesis, trade, lifecycle, risk, execution


def monthly_loss_lock_risk_executable(configuration: MonthlyLossLockRiskConfiguration) -> ExecutableSpec:
    return ExecutableSpec(display_name=f"monthly loss lock risk {configuration.configuration_id}", components=monthly_loss_lock_risk_components(), parameters=configuration.semantic_parameters(), data_contract=f"data:{OBSERVED_MATERIAL_ID}", split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development", clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v3", cost_contract="cost:fpmarkets_completed_bar_spread_proxy_point_0_01_causal_zero_repair_half_spread_stress_v1", engine_contract=f"engine:monthly_loss_lock_risk_v1:python{'.'.join(str(value) for value in sys.version_info[:3])}:numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:chassis_{monthly_loss_lock_risk_chassis_implementation_sha256()}:loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}")


def monthly_loss_lock_risk_baseline() -> ExecutableSpec:
    return monthly_loss_lock_risk_executable(monthly_loss_lock_risk_configurations()[0])


def executable_configuration_map() -> dict[str, MonthlyLossLockRiskConfiguration]:
    return {monthly_loss_lock_risk_executable(value).identity: value for value in monthly_loss_lock_risk_configurations()}


def simulate_monthly_loss_lock_risk(*, frame: pd.DataFrame, score: np.ndarray, volatility: np.ndarray, run: np.ndarray, threshold: float, configuration: MonthlyLossLockRiskConfiguration, test_start: pd.Timestamp, test_end: pd.Timestamp, fold_id: str, regime_cutoffs: tuple[float, float], effective_spread: np.ndarray | None = None) -> SimulationResult:
    routed = np.zeros(len(score), dtype=float)
    positive = np.isfinite(score) & (score > 0)
    high = np.isfinite(volatility) & (volatility >= regime_cutoffs[1])
    routed[positive & high] = np.abs(score[positive & high])
    routed[positive & ~high] = -np.abs(score[positive & ~high])
    time = pd.to_datetime(frame["time"], errors="raise")
    time_ns = _time_ns(frame)
    opens = pd.to_numeric(frame["open"], errors="raise").to_numpy(dtype=float)
    spreads = causal_effective_spread(pd.to_numeric(frame["spread"], errors="raise").to_numpy(dtype=float), time_ns) if effective_spread is None else np.asarray(effective_spread, dtype=float)
    if len(spreads) != len(frame):
        raise ValueError("effective spread length differs from frame")
    candidates = np.flatnonzero(((time >= test_start) & (time <= test_end)).to_numpy() & np.isfinite(routed))
    records: list[dict[str, Any]] = []
    intents: list[tuple[Any, ...]] = []
    month_realized: dict[str, float] = {}
    next_decision_index = -1
    unresolved = 0
    gap_excluded = 0
    causality_violations = 0
    for decision_index in candidates:
        if decision_index < next_decision_index or abs(routed[decision_index]) < threshold:
            continue
        direction = int(np.sign(routed[decision_index]))
        if direction == 0:
            continue
        decision_bar_open_time = time.iloc[decision_index]
        decision_month = decision_bar_open_time.strftime("%Y-%m")
        if configuration.risk_policy == "monthly_break_even_entry_lock" and month_realized.get(decision_month, 0.0) < 0.0:
            intents.append((decision_bar_open_time + pd.Timedelta(minutes=5), None, None, direction, "monthly_loss_locked"))
            continue
        entry_index = decision_index + 1
        exit_index = entry_index + configuration.holding_bars
        if exit_index >= len(frame) or time.iloc[exit_index] > test_end:
            continue
        decision_time = decision_bar_open_time + pd.Timedelta(minutes=5)
        entry_time = time.iloc[entry_index]
        exit_time = time.iloc[exit_index]
        if time_ns[entry_index] - time_ns[decision_index] != _FIVE_MINUTES_NS or run[exit_index] < configuration.holding_bars + 2:
            gap_excluded += 1
            intents.append((decision_time, entry_time, exit_time, direction, "gap_excluded"))
            continue
        if decision_time != entry_time:
            causality_violations += 1
            intents.append((decision_time, entry_time, exit_time, direction, "causality_violation"))
            continue
        next_decision_index = exit_index
        execution_spreads = completed_bar_execution_spreads(spreads, entry_index=entry_index, exit_index=exit_index)
        if not execution_spreads.costs_known:
            unresolved += 1
            intents.append((decision_time, entry_time, exit_time, direction, "unknown_cost"))
            continue
        native, stress = execution_pnl(direction=direction, entry_bid=float(opens[entry_index]), exit_bid=float(opens[exit_index]), entry_spread_points=execution_spreads.entry_spread_points, exit_spread_points=execution_spreads.exit_spread_points)
        exit_month = exit_time.strftime("%Y-%m")
        month_realized[exit_month] = month_realized.get(exit_month, 0.0) + native
        entry_volatility = float(volatility[decision_index])
        regime = "low" if entry_volatility <= regime_cutoffs[0] else "high" if entry_volatility >= regime_cutoffs[1] else "middle"
        records.append({"decision_bar_open_time": decision_bar_open_time, "decision_time": decision_time, "entry_time": entry_time, "exit_time": exit_time, "direction": direction, "pnl": native, "stress_pnl": stress, "fold_id": fold_id, "regime": regime})
        intents.append((decision_time, entry_time, exit_time, direction, "executed"))
    trades = pd.DataFrame.from_records(records)
    if trades.empty:
        trades = pd.DataFrame(columns=("decision_bar_open_time", "decision_time", "entry_time", "exit_time", "direction", "pnl", "stress_pnl", "fold_id", "regime"))
    return SimulationResult(trades=trades, intent_rows=tuple(intents), unresolved_cost_signal_count=unresolved, gap_excluded_signal_count=gap_excluded, causality_violation_count=causality_violations)


__all__ = ["SELECTION_TOTAL_EXPOSURES", "MonthlyLossLockRiskConfiguration", "executable_configuration_map", "loader_implementation_sha256", "monthly_loss_lock_risk_baseline", "monthly_loss_lock_risk_chassis_implementation_sha256", "monthly_loss_lock_risk_components", "monthly_loss_lock_risk_configurations", "monthly_loss_lock_risk_executable", "simulate_monthly_loss_lock_risk"]
