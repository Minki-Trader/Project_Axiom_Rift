"""Two-way calm inverse control versus low-abstain three-way regime router."""
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
from axiom_rift.research.dense_short_synthesis_chassis import dense_short_synthesis_components, loader_implementation_sha256
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256, SELECTION_BOOTSTRAP_SAMPLES, SELECTION_SEED, SimulationResult, discovery_implementation_sha256, simulate_fixed_hold

SELECTION_TOTAL_EXPOSURES = 550
_POLICIES = ("two_way_calm_inverse_control", "three_way_low_abstain_middle_inverse")
_THIS_FILE = Path(__file__).resolve()


def three_way_regime_router_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class ThreeWayRegimeRouterConfiguration:
    route_policy: str
    signal_sign: int = 1
    holding_bars: int = 12

    def __post_init__(self) -> None:
        if self.route_policy not in _POLICIES or self.signal_sign != 1 or self.holding_bars != 12:
            raise ValueError("three-way regime router configuration invalid")

    @property
    def label_profile(self) -> str:
        return "terminal_return_sign_12"

    @property
    def selector_quantile_bp(self) -> int:
        return 7000

    @property
    def configuration_id(self) -> str:
        return f"{self.route_policy}-dense12"

    def semantic_parameters(self) -> dict[str, Any]:
        return {"holding_bars": 12, "label_profile": self.label_profile, "profile": "three_way_regime_router", "ridge_penalty_milli": 1000, "route_policy": self.route_policy, "selector_quantile_bp": 7000, "signal_sign": 1}


def three_way_regime_router_configurations() -> tuple[ThreeWayRegimeRouterConfiguration, ...]:
    return tuple(ThreeWayRegimeRouterConfiguration(value) for value in _POLICIES)


def _local(name: str) -> str:
    return f"axiom_rift.research.three_way_regime_router_chassis.{name}@sha256:{three_way_regime_router_chassis_implementation_sha256()}"


def three_way_regime_router_components() -> tuple[ComponentSpec, ...]:
    feature, label, model, selector, _, _, _, _, _ = dense_short_synthesis_components()
    regime = ComponentSpec(display_name="train-tercile three-way volatility route state", protocol="regime.train_tercile_three_way_direction_route.v1", implementation=_local("simulate_three_way_regime_router"), spec={"availability": "completed_bar_only", "cutoff_source": "train_is_only_terciles", "parameter_fields": ["route_policy"], "policies": list(_POLICIES)}, semantic_dependencies=(selector.identity,))
    synthesis = ComponentSpec(display_name="high momentum middle reversal low abstention composition", protocol="synthesis.three_way_regime_direction_router.v1", implementation=_local("simulate_three_way_regime_router"), spec={"parameter_fields": ["route_policy"], "policies": list(_POLICIES)}, semantic_dependencies=(selector.identity, regime.identity))
    trade = ComponentSpec(display_name="three-way regime-routed next-open entry", protocol="trade.three_way_regime_routed_direction.v1", implementation=_local("simulate_three_way_regime_router"), spec={"decision_time": "bar_open_plus_5m", "entry_time": "next_exact_bar_open", "parameter_fields": ["route_policy"]}, semantic_dependencies=(selector.identity, regime.identity, synthesis.identity))
    lifecycle = ComponentSpec(display_name="fixed 12-bar nonoverlap lifecycle", protocol="lifecycle.fixed_hold_no_overlap.v10", implementation=_local("simulate_three_way_regime_router"), spec={"entry_overlap": "reject_while_position_slot_is_occupied", "exit_surface": "exact_bar_open_after_12_bars", "gap_action": "exclude_path"}, semantic_dependencies=(trade.identity,))
    risk = ComponentSpec(display_name="fixed one-lot no-stop risk", protocol="risk.fixed_one_lot.v2", implementation=_local("simulate_three_way_regime_router"), spec={"dynamic_sizing": False, "lot": 1, "stop": None}, semantic_dependencies=(lifecycle.identity,))
    execution = ComponentSpec(display_name="fixed FPMarkets bid-open spread execution", protocol="execution.fpmarkets_bid_open_spread.v1", implementation=_local("simulate_three_way_regime_router"), spec={"point": "0.01", "stress": "half_effective_spread_each_side"}, semantic_dependencies=(risk.identity,))
    return feature, label, model, selector, regime, synthesis, trade, lifecycle, risk, execution


def three_way_regime_router_executable(configuration: ThreeWayRegimeRouterConfiguration) -> ExecutableSpec:
    return ExecutableSpec(display_name=f"three-way regime router {configuration.configuration_id}", components=three_way_regime_router_components(), parameters=configuration.semantic_parameters(), data_contract=f"data:{OBSERVED_MATERIAL_ID}", split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development", clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v3", cost_contract="cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v3", engine_contract=f"engine:three_way_regime_router_v1:python{'.'.join(str(value) for value in sys.version_info[:3])}:numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:chassis_{three_way_regime_router_chassis_implementation_sha256()}:loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}")


def three_way_regime_router_baseline() -> ExecutableSpec:
    return three_way_regime_router_executable(three_way_regime_router_configurations()[0])


def executable_configuration_map() -> dict[str, ThreeWayRegimeRouterConfiguration]:
    return {three_way_regime_router_executable(value).identity: value for value in three_way_regime_router_configurations()}


def simulate_three_way_regime_router(*, frame: pd.DataFrame, score: np.ndarray, volatility: np.ndarray, run: np.ndarray, threshold: float, configuration: ThreeWayRegimeRouterConfiguration, test_start: pd.Timestamp, test_end: pd.Timestamp, fold_id: str, regime_cutoffs: tuple[float, float], effective_spread: np.ndarray | None = None) -> SimulationResult:
    routed = np.zeros(len(score), dtype=float)
    positive = np.isfinite(score) & (score > 0)
    low = np.isfinite(volatility) & (volatility <= regime_cutoffs[0])
    high = np.isfinite(volatility) & (volatility >= regime_cutoffs[1])
    middle = np.isfinite(volatility) & ~low & ~high
    routed[positive & high] = np.abs(score[positive & high])
    routed[positive & middle] = -np.abs(score[positive & middle])
    if configuration.route_policy == "two_way_calm_inverse_control":
        routed[positive & low] = -np.abs(score[positive & low])
    return simulate_fixed_hold(frame=frame, score=routed, volatility=volatility, run=run, threshold=threshold, configuration=configuration, test_start=test_start, test_end=test_end, fold_id=fold_id, regime_cutoffs=regime_cutoffs, effective_spread=effective_spread)


__all__ = ["SELECTION_TOTAL_EXPOSURES", "ThreeWayRegimeRouterConfiguration", "executable_configuration_map", "loader_implementation_sha256", "simulate_three_way_regime_router", "three_way_regime_router_baseline", "three_way_regime_router_chassis_implementation_sha256", "three_way_regime_router_components", "three_way_regime_router_configurations", "three_way_regime_router_executable"]
