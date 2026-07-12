"""Profitable router plus US100 direction fixed-lot sleeve composition."""

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
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256, SELECTION_BOOTSTRAP_SAMPLES, SELECTION_SEED, SimulationResult, discovery_implementation_sha256, simulate_fixed_hold
from axiom_rift.research.regime_direction_router_chassis import loader_implementation_sha256, regime_direction_router_components


SELECTION_TOTAL_EXPOSURES = 579
_PROFILES = ("router_control", "dual_positive_direction_slots")
_THIS_FILE = Path(__file__).resolve()


def positive_direction_sleeve_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class PositiveDirectionSleeveConfiguration:
    portfolio_profile: str

    def __post_init__(self) -> None:
        if self.portfolio_profile not in _PROFILES:
            raise ValueError("positive direction sleeve profile invalid")

    @property
    def configuration_id(self) -> str:
        return self.portfolio_profile

    @property
    def holding_bars(self) -> int:
        return 12

    @property
    def signal_sign(self) -> int:
        return 1

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "holding_bars": 12,
            "label_profile": "terminal_return_sign_12",
            "portfolio_profile": self.portfolio_profile,
            "profile": "dense_terminal_12_synthesis",
            "ridge_penalty_milli": 1000,
            "route_policy": "high_long_calm_inverse_router",
            "selector_quantile_bp": 7000,
            "signal_sign": 1,
            "target_direction_holding_bars": 6,
            "target_direction_lookback_bars": 12,
            "target_direction_selector_quantile_bp": 9750,
            "target_direction_volatility_bars": 48,
        }


def positive_direction_sleeve_configurations() -> tuple[PositiveDirectionSleeveConfiguration, ...]:
    return tuple(PositiveDirectionSleeveConfiguration(value) for value in _PROFILES)


def _local(name: str) -> str:
    return f"axiom_rift.research.positive_direction_sleeve_chassis.{name}@sha256:{positive_direction_sleeve_chassis_implementation_sha256()}"


def positive_direction_sleeve_components() -> tuple[ComponentSpec, ...]:
    router = regime_direction_router_components()
    feature = ComponentSpec(display_name="causal US100 twelve-bar sigma-normalized direction", protocol="feature.us100_direction_12_sigma48.v1", implementation=_local("target_direction_score"), spec={"availability": "completed_bar_only", "lookback_bars": 12, "volatility_bars": 48})
    selector = ComponentSpec(display_name="train-only extreme US100 direction selector", protocol="selector.fold_train_abs_quantile.v3", implementation=_local("normalize_sleeves"), spec={"quantile_basis_points": 9750, "quantile_method": "higher"}, semantic_dependencies=(feature.identity,))
    trade = ComponentSpec(display_name="US100 direction next-open entry", protocol="trade.target_direction_next_open.v1", implementation=_local("simulate_positive_direction_sleeves"), spec={"decision_time": "bar_open_plus_5m", "entry_time": "next_exact_bar_open"}, semantic_dependencies=(selector.identity,))
    lifecycle = ComponentSpec(display_name="fixed six-bar target-direction lifecycle", protocol="lifecycle.fixed_hold_no_overlap.v11", implementation=_local("simulate_positive_direction_sleeves"), spec={"holding_bars": 6, "slot": "target_direction"}, semantic_dependencies=(trade.identity,))
    risk = ComponentSpec(display_name="fixed one-lot target-direction risk", protocol="risk.fixed_one_lot.v4", implementation=_local("simulate_positive_direction_sleeves"), spec={"dynamic_sizing": False, "lot": 1, "slot": "target_direction"}, semantic_dependencies=(lifecycle.identity,))
    execution = ComponentSpec(display_name="fixed FPMarkets target-direction spread execution", protocol="execution.fpmarkets_bid_open_spread.v3", implementation=_local("simulate_positive_direction_sleeves"), spec={"point": "0.01", "stress": "half_effective_spread_each_side"}, semantic_dependencies=(risk.identity,))
    portfolio_risk = ComponentSpec(display_name="fixed gross positive-sleeve exposure", protocol="risk.fixed_positive_sleeve_gross_slots.v1", implementation=_local("simulate_positive_direction_sleeves"), spec={"dynamic_sizing": False, "parameter_fields": ["portfolio_profile"], "profiles": list(_PROFILES), "router_control_max_gross_lots": 1, "dual_max_gross_lots": 2}, semantic_dependencies=(router[-2].identity, risk.identity))
    portfolio = ComponentSpec(display_name="router and positive target-direction sleeve portfolio", protocol="portfolio.positive_direction_fixed_lot_sleeves.v1", implementation=_local("simulate_positive_direction_sleeves"), spec={"parameter_fields": ["portfolio_profile"], "profiles": list(_PROFILES), "per_sleeve_lot": 1}, semantic_dependencies=(router[-1].identity, execution.identity, portfolio_risk.identity))
    return (*router, feature, selector, trade, lifecycle, risk, execution, portfolio_risk, portfolio)


def positive_direction_sleeve_executable(configuration: PositiveDirectionSleeveConfiguration) -> ExecutableSpec:
    return ExecutableSpec(display_name=f"positive direction sleeves {configuration.configuration_id}", components=positive_direction_sleeve_components(), parameters=configuration.semantic_parameters(), data_contract=f"data:{OBSERVED_MATERIAL_ID}", split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development", clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v5", cost_contract="cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v5", engine_contract=f"engine:positive_direction_sleeves_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:chassis_{positive_direction_sleeve_chassis_implementation_sha256()}:loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}")


def positive_direction_sleeve_baseline() -> ExecutableSpec:
    return positive_direction_sleeve_executable(positive_direction_sleeve_configurations()[0])


def executable_configuration_map() -> dict[str, PositiveDirectionSleeveConfiguration]:
    return {positive_direction_sleeve_executable(value).identity: value for value in positive_direction_sleeve_configurations()}


@dataclass(frozen=True, slots=True)
class _Slot:
    holding_bars: int
    signal_sign: int = 1


def _slot(*, frame: pd.DataFrame, score: np.ndarray, volatility: np.ndarray, run: np.ndarray, holding_bars: int, test_start: pd.Timestamp, test_end: pd.Timestamp, fold_id: str, regime_cutoffs: tuple[float, float], effective_spread: np.ndarray, slot: str) -> SimulationResult:
    result = simulate_fixed_hold(frame=frame, score=score, volatility=volatility, run=run, threshold=1.0, configuration=_Slot(holding_bars), test_start=test_start, test_end=test_end, fold_id=fold_id, regime_cutoffs=regime_cutoffs, effective_spread=effective_spread)
    if not result.trades.empty:
        result.trades = result.trades.assign(slot=slot)
    result.intent_rows = tuple((slot, *row) for row in result.intent_rows)
    return result


def simulate_positive_direction_sleeves(*, frame: pd.DataFrame, score: np.ndarray, volatility: np.ndarray, run: np.ndarray, threshold: float, configuration: PositiveDirectionSleeveConfiguration, test_start: pd.Timestamp, test_end: pd.Timestamp, fold_id: str, regime_cutoffs: tuple[float, float], effective_spread: np.ndarray | None = None) -> SimulationResult:
    del threshold
    values = np.asarray(score, float)
    if values.ndim != 2 or values.shape != (len(frame), 2):
        raise ValueError("positive direction sleeve score matrix invalid")
    spreads = np.asarray(effective_spread, float)
    slots = [_slot(frame=frame, score=values[:, 0], volatility=volatility, run=run, holding_bars=12, test_start=test_start, test_end=test_end, fold_id=fold_id, regime_cutoffs=regime_cutoffs, effective_spread=spreads, slot="regime_router")]
    if configuration.portfolio_profile == "dual_positive_direction_slots":
        slots.append(_slot(frame=frame, score=values[:, 1], volatility=volatility, run=run, holding_bars=6, test_start=test_start, test_end=test_end, fold_id=fold_id, regime_cutoffs=regime_cutoffs, effective_spread=spreads, slot="target_direction"))
    trades = pd.concat([value.trades for value in slots], ignore_index=True).sort_values(["decision_time", "slot"], kind="stable").reset_index(drop=True)
    return SimulationResult(trades=trades, intent_rows=tuple(row for value in slots for row in value.intent_rows), unresolved_cost_signal_count=sum(value.unresolved_cost_signal_count for value in slots), gap_excluded_signal_count=sum(value.gap_excluded_signal_count for value in slots), causality_violation_count=sum(value.causality_violation_count for value in slots))


__all__ = ["SELECTION_TOTAL_EXPOSURES", "PositiveDirectionSleeveConfiguration", "executable_configuration_map", "loader_implementation_sha256", "positive_direction_sleeve_baseline", "positive_direction_sleeve_chassis_implementation_sha256", "positive_direction_sleeve_components", "positive_direction_sleeve_configurations", "positive_direction_sleeve_executable", "simulate_positive_direction_sleeves"]
