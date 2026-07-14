"""Fixed-lot independent router and target-downside sleeve portfolio."""

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
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    SELECTION_BOOTSTRAP_SAMPLES,
    SELECTION_SEED,
    SimulationResult,
    discovery_implementation_sha256,
    execution_pnl,
)
from axiom_rift.research.regime_direction_router_chassis import (
    loader_implementation_sha256,
    regime_direction_router_components,
)


SELECTION_TOTAL_EXPOSURES = 577
_PROFILES = ("router_control", "target_downside_control", "dual_independent_slots")
_THIS_FILE = Path(__file__).resolve()
_FIVE_MINUTES_NS = 300_000_000_000


def independent_sleeve_portfolio_chassis_implementation_sha256() -> str:
    """Bind prospective chassis identity to the current file bytes."""

    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def independent_sleeve_portfolio_followup_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class IndependentSleevePortfolioConfiguration:
    portfolio_profile: str

    def __post_init__(self) -> None:
        if self.portfolio_profile not in _PROFILES:
            raise ValueError("independent sleeve portfolio profile invalid")

    @property
    def configuration_id(self) -> str:
        return self.portfolio_profile

    @property
    def signal_sign(self) -> int:
        return 1

    @property
    def holding_bars(self) -> int:
        return 12

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "holding_bars": 12,
            "label_profile": "terminal_return_sign_12",
            "portfolio_profile": self.portfolio_profile,
            "profile": "dense_terminal_12_synthesis",
            "ridge_penalty_milli": 1000,
            "route_policy": "high_long_calm_inverse_router",
            "router_holding_bars": 12,
            "router_selector_quantile_bp": 7000,
            "selector_quantile_bp": 7000,
            "signal_sign": 1,
            "target_downside_holding_bars": 3,
            "target_downside_selector_quantile_bp": 9500,
            "sleeve_lot": 1,
        }


def independent_sleeve_portfolio_configurations() -> tuple[IndependentSleevePortfolioConfiguration, ...]:
    return tuple(IndependentSleevePortfolioConfiguration(value) for value in _PROFILES)


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.independent_sleeve_portfolio_chassis.{name}"
        f"@sha256:{independent_sleeve_portfolio_chassis_implementation_sha256()}"
    )


def _followup_local(name: str) -> str:
    return (
        f"axiom_rift.research.independent_sleeve_portfolio_chassis.{name}"
        f"@sha256:{independent_sleeve_portfolio_followup_implementation_sha256()}"
    )


def independent_sleeve_portfolio_components(
    portfolio_profile: str = "router_control",
) -> tuple[ComponentSpec, ...]:
    if portfolio_profile not in _PROFILES:
        raise ValueError("independent sleeve portfolio profile invalid")
    router = regime_direction_router_components()
    router_execution = router[-1]
    target_feature = ComponentSpec(
        display_name="causal US100 downside volatility expansion",
        protocol="feature.target_downside_volatility_expansion.v1",
        implementation=_local("target_downside_score"),
        spec={"lookback_returns": 6, "short_volatility_bars": 12, "long_volatility_bars": 96},
    )
    target_selector = ComponentSpec(
        display_name="train-only target-downside tail selector",
        protocol="selector.train_abs_quantile.v1",
        implementation=_local("normalize_sleeves"),
        spec={"quantile_basis_points": 9500, "quantile_method": "higher"},
        semantic_dependencies=(target_feature.identity,),
    )
    target_trade = ComponentSpec(
        display_name="target-downside next-open short entry",
        protocol="trade.target_downside_next_open_short.v1",
        implementation=_local("simulate_independent_sleeve_portfolio"),
        spec={"decision_time": "bar_open_plus_5m", "entry_time": "next_exact_bar_open"},
        semantic_dependencies=(target_selector.identity,),
    )
    target_lifecycle = ComponentSpec(
        display_name="fixed three-bar target-downside lifecycle",
        protocol="lifecycle.fixed_hold_no_overlap.v10",
        implementation=_local("simulate_independent_sleeve_portfolio"),
        spec={"holding_bars": 3, "slot": "target_downside"},
        semantic_dependencies=(target_trade.identity,),
    )
    target_risk = ComponentSpec(
        display_name="fixed one-lot target-downside risk",
        protocol="risk.fixed_one_lot.v3",
        implementation=_local("simulate_independent_sleeve_portfolio"),
        spec={"dynamic_sizing": False, "lot": 1, "slot": "target_downside"},
        semantic_dependencies=(target_lifecycle.identity,),
    )
    target_execution = ComponentSpec(
        display_name="fixed FPMarkets target-downside spread execution",
        protocol="execution.fpmarkets_bid_open_spread.v2",
        implementation=_local("simulate_independent_sleeve_portfolio"),
        spec={"point": "0.01", "stress": "half_effective_spread_each_side"},
        semantic_dependencies=(target_risk.identity,),
    )
    portfolio_dependencies = (router_execution.identity, target_execution.identity)
    extra_risk: tuple[ComponentSpec, ...] = ()
    if portfolio_profile != "router_control":
        gross_risk = ComponentSpec(
            display_name="fixed gross sleeve-slot exposure",
            protocol="risk.fixed_independent_gross_slots.v1",
            implementation=_followup_local("simulate_independent_sleeve_portfolio"),
            spec={
                "dynamic_sizing": False,
                "max_gross_lots": 2 if portfolio_profile == "dual_independent_slots" else 1,
                "parameter_fields": ["portfolio_profile"],
            },
            semantic_dependencies=(router[-2].identity, target_risk.identity),
        )
        extra_risk = (gross_risk,)
        portfolio_dependencies = (*portfolio_dependencies, gross_risk.identity)
    portfolio = ComponentSpec(
        display_name="independent fixed-lot sleeve portfolio",
        protocol="portfolio.independent_fixed_lot_sleeves.v1",
        implementation=_local("simulate_independent_sleeve_portfolio"),
        spec={
            "parameter_fields": ["portfolio_profile"],
            "profiles": list(_PROFILES),
            "slots": ["regime_router", "target_downside"],
            "per_sleeve_lot": 1,
            "dual_max_gross_lots": 2,
            "dynamic_sizing": False,
        },
        semantic_dependencies=portfolio_dependencies,
    )
    return (*router, target_feature, target_selector, target_trade, target_lifecycle, target_risk, target_execution, *extra_risk, portfolio)


def independent_sleeve_portfolio_executable(configuration: IndependentSleevePortfolioConfiguration) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"independent sleeve portfolio {configuration.configuration_id}",
        components=independent_sleeve_portfolio_components(configuration.portfolio_profile),
        parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v4",
        cost_contract="cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v4",
        engine_contract=(
            f"engine:independent_sleeve_portfolio_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"chassis_{independent_sleeve_portfolio_chassis_implementation_sha256()}:"
            f"loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:"
            f"bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:"
            f"bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def independent_sleeve_portfolio_baseline() -> ExecutableSpec:
    return independent_sleeve_portfolio_executable(independent_sleeve_portfolio_configurations()[0])


def executable_configuration_map() -> dict[str, IndependentSleevePortfolioConfiguration]:
    return {independent_sleeve_portfolio_executable(value).identity: value for value in independent_sleeve_portfolio_configurations()}


@dataclass(frozen=True, slots=True)
class _SlotConfiguration:
    holding_bars: int
    signal_sign: int = 1


def _simulate_slot(
    *,
    frame: pd.DataFrame,
    score: np.ndarray,
    volatility: np.ndarray,
    run: np.ndarray,
    holding_bars: int,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray,
    slot: str,
) -> SimulationResult:
    from axiom_rift.research.discovery import simulate_fixed_hold

    result = simulate_fixed_hold(
        frame=frame,
        score=score,
        volatility=volatility,
        run=run,
        threshold=1.0,
        configuration=_SlotConfiguration(holding_bars),
        test_start=test_start,
        test_end=test_end,
        fold_id=fold_id,
        regime_cutoffs=regime_cutoffs,
        effective_spread=effective_spread,
    )
    if not result.trades.empty:
        result.trades = result.trades.assign(slot=slot)
    result.intent_rows = tuple((slot, *row) for row in result.intent_rows)
    return result


def simulate_independent_sleeve_portfolio(
    *,
    frame: pd.DataFrame,
    score: np.ndarray,
    volatility: np.ndarray,
    run: np.ndarray,
    threshold: float,
    configuration: IndependentSleevePortfolioConfiguration,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray | None = None,
) -> SimulationResult:
    del threshold
    values = np.asarray(score, dtype=float)
    if values.ndim != 2 or values.shape[1] != 2 or len(values) != len(frame):
        raise ValueError("independent sleeve score matrix invalid")
    spreads = np.asarray(effective_spread, dtype=float)
    profile = configuration.portfolio_profile
    slots: list[SimulationResult] = []
    if profile in {"router_control", "dual_independent_slots"}:
        slots.append(_simulate_slot(frame=frame, score=values[:, 0], volatility=volatility, run=run, holding_bars=12, test_start=test_start, test_end=test_end, fold_id=fold_id, regime_cutoffs=regime_cutoffs, effective_spread=spreads, slot="regime_router"))
    if profile in {"target_downside_control", "dual_independent_slots"}:
        slots.append(_simulate_slot(frame=frame, score=values[:, 1], volatility=volatility, run=run, holding_bars=3, test_start=test_start, test_end=test_end, fold_id=fold_id, regime_cutoffs=regime_cutoffs, effective_spread=spreads, slot="target_downside"))
    trades = pd.concat([value.trades for value in slots], ignore_index=True).sort_values(["decision_time", "slot"], kind="stable").reset_index(drop=True)
    return SimulationResult(
        trades=trades,
        intent_rows=tuple(row for value in slots for row in value.intent_rows),
        unresolved_cost_signal_count=sum(value.unresolved_cost_signal_count for value in slots),
        gap_excluded_signal_count=sum(value.gap_excluded_signal_count for value in slots),
        causality_violation_count=sum(value.causality_violation_count for value in slots),
    )


__all__ = [
    "SELECTION_TOTAL_EXPOSURES",
    "IndependentSleevePortfolioConfiguration",
    "executable_configuration_map",
    "independent_sleeve_portfolio_baseline",
    "independent_sleeve_portfolio_chassis_implementation_sha256",
    "independent_sleeve_portfolio_components",
    "independent_sleeve_portfolio_configurations",
    "independent_sleeve_portfolio_executable",
    "independent_sleeve_portfolio_followup_implementation_sha256",
    "loader_implementation_sha256",
    "simulate_independent_sleeve_portfolio",
]
