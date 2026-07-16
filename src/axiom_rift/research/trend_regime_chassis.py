"""Long-only volatility-clock signal with a causal long-trend regime gate."""

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
from axiom_rift.research.discovery import (
    OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256, SELECTION_BOOTSTRAP_SAMPLES,
    SELECTION_SEED, SimulationResult, discovery_implementation_sha256,
)
from axiom_rift.research.equity_premium_trade_chassis import (
    EquityPremiumTradeConfiguration, equity_premium_trade_components,
    loader_implementation_sha256, simulate_equity_premium_trade,
)
from axiom_rift.research.event_label_discovery import HORIZON
from axiom_rift.research.volatility_clock_label_chassis import (
    VOLATILITY_BUDGET_BARS, volatility_clock_label_chassis_implementation_sha256,
)


SELECTION_TOTAL_EXPOSURES = 540
TREND_WINDOW = 192
_POLICIES = ("unconditional_long_control", "positive_192bar_trend_gate")
_THIS_FILE = Path(__file__).resolve()


def trend_regime_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class TrendRegimeConfiguration:
    regime_policy: str

    def __post_init__(self) -> None:
        if self.regime_policy not in _POLICIES:
            raise ValueError("trend regime configuration invalid")

    @property
    def configuration_id(self) -> str:
        return f"{self.regime_policy}-long-maxh{HORIZON}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "holding_bars": HORIZON,
            "label_profile": "volatility_clock_terminal_12_of_48",
            "regime_policy": self.regime_policy,
            "risk_policy": "fixed_one_lot_no_stop",
            "trade_policy": "long_only_equity_premium",
            "trend_window_bars": TREND_WINDOW,
            "volatility_budget_bars": VOLATILITY_BUDGET_BARS,
        }


def trend_regime_configurations() -> tuple[TrendRegimeConfiguration, ...]:
    return tuple(TrendRegimeConfiguration(value) for value in _POLICIES)


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.trend_regime_chassis.{name}"
        f"@sha256:{trend_regime_chassis_implementation_sha256()}"
    )


def trend_regime_components() -> tuple[ComponentSpec, ...]:
    feature, label, model, selector, *_ = equity_premium_trade_components()
    regime = ComponentSpec(
        display_name="causal completed-bar 192-bar long-trend state",
        protocol="regime.completed_close_above_rolling_mean.v1",
        implementation=_local("simulate_trend_regime"),
        spec={
            "availability": "completed_bar_close", "parameter_fields": ["regime_policy"],
            "policies": list(_POLICIES), "trend_window_bars": TREND_WINDOW,
        },
        semantic_dependencies=(selector.identity,),
    )
    trade = ComponentSpec(
        display_name="fixed long-only next-open entry",
        protocol="trade.fixed_long_only_next_open.v1",
        implementation=_local("simulate_trend_regime"),
        spec={
            "decision_time": "bar_open_plus_5m", "direction": "positive_score_only",
            "entry_time": "next_exact_bar_open",
        },
        semantic_dependencies=(selector.identity, regime.identity),
    )
    lifecycle = ComponentSpec(
        display_name="fixed maximum 48-bar nonoverlap lifecycle",
        protocol="lifecycle.fixed_hold_no_overlap.v8",
        implementation=_local("simulate_trend_regime"),
        spec={
            "entry_overlap": "reject_while_position_slot_is_occupied",
            "exit_surface": "exact_bar_open_after_48_bars", "gap_action": "exclude_path",
        },
        semantic_dependencies=(trade.identity,),
    )
    risk = ComponentSpec(
        display_name="fixed one-lot no-stop risk",
        protocol="risk.fixed_one_lot.v2",
        implementation=_local("simulate_trend_regime"),
        spec={"dynamic_sizing": False, "lot": 1, "stop": None},
        semantic_dependencies=(lifecycle.identity,),
    )
    execution = ComponentSpec(
        display_name="fixed FPMarkets completed-period spread proxy execution",
        protocol="execution.fpmarkets_completed_bar_spread_proxy.v1",
        implementation=_local("simulate_trend_regime"),
        spec={
            "entry_proxy": "entry_index_minus_1",
            "exit_proxy": "exit_index_minus_1",
            "point": "0.01",
            "stress": "half_effective_spread_each_side",
        },
        semantic_dependencies=(risk.identity,),
    )
    return feature, label, model, selector, regime, trade, lifecycle, risk, execution


def trend_regime_executable(configuration: TrendRegimeConfiguration) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"trend regime {configuration.configuration_id}",
        components=trend_regime_components(), parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v3",
        cost_contract=(
            "cost:fpmarkets_completed_bar_spread_proxy_point_0_01_"
            "causal_zero_repair_half_spread_stress_v1"
        ),
        engine_contract=(
            f"engine:trend_regime_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"chassis_{trend_regime_chassis_implementation_sha256()}:"
            f"label_{volatility_clock_label_chassis_implementation_sha256()}:"
            f"loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:"
            f"bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:"
            f"bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def trend_regime_baseline() -> ExecutableSpec:
    return trend_regime_executable(trend_regime_configurations()[0])


def executable_configuration_map() -> dict[str, TrendRegimeConfiguration]:
    return {trend_regime_executable(value).identity: value for value in trend_regime_configurations()}


def simulate_trend_regime(
    *, frame: pd.DataFrame, score: np.ndarray, volatility: np.ndarray,
    run: np.ndarray, threshold: float, configuration: TrendRegimeConfiguration,
    test_start: pd.Timestamp, test_end: pd.Timestamp, fold_id: str,
    regime_cutoffs: tuple[float, float], effective_spread: np.ndarray | None = None,
) -> SimulationResult:
    gated_score = np.asarray(score, float).copy()
    if configuration.regime_policy == "positive_192bar_trend_gate":
        close = pd.to_numeric(frame["close"], errors="raise")
        trend_mean = close.rolling(TREND_WINDOW, min_periods=TREND_WINDOW).mean().to_numpy(float)
        allowed = close.to_numpy(float) > trend_mean
        gated_score[~allowed] = 0.0
    return simulate_equity_premium_trade(
        frame=frame, score=gated_score, volatility=volatility, run=run,
        threshold=threshold,
        configuration=EquityPremiumTradeConfiguration("long_only_equity_premium"),
        test_start=test_start, test_end=test_end, fold_id=fold_id,
        regime_cutoffs=regime_cutoffs, effective_spread=effective_spread,
    )


__all__ = [
    "SELECTION_TOTAL_EXPOSURES", "TREND_WINDOW", "TrendRegimeConfiguration",
    "executable_configuration_map", "loader_implementation_sha256",
    "simulate_trend_regime", "trend_regime_baseline",
    "trend_regime_chassis_implementation_sha256", "trend_regime_components",
    "trend_regime_configurations", "trend_regime_executable",
]
