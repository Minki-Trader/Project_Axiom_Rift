"""Volatility-clock signal with controlled symmetric versus long-only entry policy."""

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
    OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256, SELECTION_BOOTSTRAP_SAMPLES,
    SELECTION_SEED, SimulationResult, _time_ns, causal_effective_spread,
    discovery_implementation_sha256, execution_pnl,
)
from axiom_rift.research.event_label_discovery import (
    HORIZON, RIDGE_PENALTY_MILLI, event_label_implementation_sha256,
)
from axiom_rift.research.volatility_clock_label_chassis import (
    VOLATILITY_BUDGET_BARS, volatility_clock_label_chassis_implementation_sha256,
)


SELECTION_TOTAL_EXPOSURES = 538
SELECTOR_QUANTILE_BP = 8_500
_POLICIES = ("symmetric_direction_control", "long_only_equity_premium")
_THIS_FILE = Path(__file__).resolve()
_FIVE_MINUTES_NS = 300_000_000_000


def equity_premium_trade_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def loader_implementation_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class EquityPremiumTradeConfiguration:
    trade_policy: str
    holding_bars: int = HORIZON

    def __post_init__(self) -> None:
        if self.trade_policy not in _POLICIES or self.holding_bars != HORIZON:
            raise ValueError("equity-premium trade configuration invalid")

    @property
    def configuration_id(self) -> str:
        return f"{self.trade_policy}-fixed-maxh{HORIZON}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "holding_bars": HORIZON,
            "label_profile": "volatility_clock_terminal_12_of_48",
            "ridge_penalty_milli": RIDGE_PENALTY_MILLI,
            "risk_policy": "fixed_one_lot_no_stop",
            "selector_quantile_bp": SELECTOR_QUANTILE_BP,
            "trade_policy": self.trade_policy,
            "volatility_budget_bars": VOLATILITY_BUDGET_BARS,
        }


def equity_premium_trade_configurations(
) -> tuple[EquityPremiumTradeConfiguration, ...]:
    return tuple(EquityPremiumTradeConfiguration(value) for value in _POLICIES)


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.equity_premium_trade_chassis.{name}"
        f"@sha256:{equity_premium_trade_chassis_implementation_sha256()}"
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


def equity_premium_trade_components() -> tuple[ComponentSpec, ...]:
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
        display_name="symmetric versus long-only next-open entry policy",
        protocol="trade.equity_premium_direction_gate.v1",
        implementation=_local("simulate_equity_premium_trade"),
        spec={
            "decision_time": "bar_open_plus_5m",
            "entry_time": "next_exact_bar_open",
            "parameter_fields": ["trade_policy"],
            "policies": list(_POLICIES),
            "signal_direction": "fold_score_sign",
        },
        semantic_dependencies=(selector.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="fixed maximum 48-bar nonoverlap lifecycle",
        protocol="lifecycle.fixed_hold_no_overlap.v8",
        implementation=_local("simulate_equity_premium_trade"),
        spec={
            "entry_overlap": "reject_while_position_slot_is_occupied",
            "exit_surface": "exact_bar_open_after_48_bars",
            "gap_action": "exclude_path",
        },
        semantic_dependencies=(trade.identity,),
    )
    risk = ComponentSpec(
        display_name="fixed one-lot no-stop risk",
        protocol="risk.fixed_one_lot.v2",
        implementation=_local("simulate_equity_premium_trade"),
        spec={"dynamic_sizing": False, "lot": 1, "stop": None},
        semantic_dependencies=(lifecycle.identity,),
    )
    execution = ComponentSpec(
        display_name="fixed FPMarkets bid-open spread execution",
        protocol="execution.fpmarkets_bid_open_spread.v1",
        implementation=_local("simulate_equity_premium_trade"),
        spec={"point": "0.01", "stress": "half_effective_spread_each_side"},
        semantic_dependencies=(risk.identity,),
    )
    return feature, label, model, selector, trade, lifecycle, risk, execution


def equity_premium_trade_executable(
    configuration: EquityPremiumTradeConfiguration,
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"equity premium trade {configuration.configuration_id}",
        components=equity_premium_trade_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v3",
        cost_contract="cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v3",
        engine_contract=(
            f"engine:equity_premium_trade_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"chassis_{equity_premium_trade_chassis_implementation_sha256()}:"
            f"label_{volatility_clock_label_chassis_implementation_sha256()}:"
            f"event_{event_label_implementation_sha256()}:loader_{loader_implementation_sha256()}:"
            f"shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:"
            f"blocks_5_10_20:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def equity_premium_trade_baseline() -> ExecutableSpec:
    return equity_premium_trade_executable(equity_premium_trade_configurations()[0])


def executable_configuration_map() -> dict[str, EquityPremiumTradeConfiguration]:
    return {
        equity_premium_trade_executable(value).identity: value
        for value in equity_premium_trade_configurations()
    }


def simulate_equity_premium_trade(
    *, frame: pd.DataFrame, score: np.ndarray, volatility: np.ndarray,
    run: np.ndarray, threshold: float, configuration: EquityPremiumTradeConfiguration,
    test_start: pd.Timestamp, test_end: pd.Timestamp, fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray | None = None,
) -> SimulationResult:
    time = pd.to_datetime(frame["time"], errors="raise")
    time_ns = _time_ns(frame)
    opens = pd.to_numeric(frame["open"], errors="raise").to_numpy(float)
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
        direction = int(np.sign(score[decision_index]))
        if direction == 0 or (
            configuration.trade_policy == "long_only_equity_premium" and direction < 0
        ):
            continue
        entry_index = decision_index + 1
        exit_index = entry_index + configuration.holding_bars
        if exit_index >= len(frame) or time.iloc[exit_index] > test_end:
            continue
        decision_time = time.iloc[decision_index] + pd.Timedelta(minutes=5)
        entry_time = time.iloc[entry_index]
        if time_ns[entry_index] - time_ns[decision_index] != _FIVE_MINUTES_NS:
            gap_excluded += 1
            intents.append((decision_time, entry_time, time.iloc[exit_index], direction, "gap_excluded"))
            continue
        if decision_time != entry_time:
            causality_violations += 1
            intents.append((decision_time, entry_time, time.iloc[exit_index], direction, "causality_violation"))
            continue
        if run[exit_index] < configuration.holding_bars + 2:
            gap_excluded += 1
            intents.append((decision_time, entry_time, time.iloc[exit_index], direction, "gap_excluded"))
            continue
        next_decision_index = exit_index
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
    "SELECTION_TOTAL_EXPOSURES", "EquityPremiumTradeConfiguration",
    "equity_premium_trade_baseline",
    "equity_premium_trade_chassis_implementation_sha256",
    "equity_premium_trade_components", "equity_premium_trade_configurations",
    "equity_premium_trade_executable", "executable_configuration_map",
    "loader_implementation_sha256", "simulate_equity_premium_trade",
]
