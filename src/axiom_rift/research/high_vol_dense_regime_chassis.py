"""Dense 12-bar sleeve with controlled unconditional versus high-volatility routing."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any
import numpy as np
import pandas as pd
import scipy
from axiom_rift.core.identity import ComponentSpec,ExecutableSpec
from axiom_rift.research.dense_short_synthesis_chassis import dense_short_synthesis_components,loader_implementation_sha256,simulate_dense_short_synthesis,DenseShortSynthesisConfiguration
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID,ROLLING_SPLIT_SHA256,SELECTION_BOOTSTRAP_SAMPLES,SELECTION_SEED,SimulationResult,discovery_implementation_sha256

SELECTION_TOTAL_EXPOSURES=544
_POLICIES=("unconditional_dense_control","train_top_third_volatility_gate")
_THIS_FILE=Path(__file__).resolve()
def high_vol_dense_regime_chassis_implementation_sha256()->str:return sha256(_THIS_FILE.read_bytes()).hexdigest()
@dataclass(frozen=True,slots=True)
class HighVolDenseRegimeConfiguration:
    regime_policy:str
    def __post_init__(self)->None:
        if self.regime_policy not in _POLICIES:raise ValueError("high-vol dense regime configuration invalid")
    @property
    def configuration_id(self)->str:return f"{self.regime_policy}-dense12-long"
    @property
    def holding_bars(self)->int:return 12
    @property
    def label_profile(self)->str:return "terminal_return_sign_12"
    @property
    def selector_quantile_bp(self)->int:return 7000
    def semantic_parameters(self)->dict[str,Any]:return {"holding_bars":12,"label_profile":"terminal_return_sign_12","profile":"dense_terminal_12_synthesis","regime_policy":self.regime_policy,"ridge_penalty_milli":1000,"selector_quantile_bp":7000,"signal_sign":1}
def high_vol_dense_regime_configurations()->tuple[HighVolDenseRegimeConfiguration,...]:return tuple(HighVolDenseRegimeConfiguration(v) for v in _POLICIES)
def _local(name:str)->str:return f"axiom_rift.research.high_vol_dense_regime_chassis.{name}@sha256:{high_vol_dense_regime_chassis_implementation_sha256()}"
def high_vol_dense_regime_components()->tuple[ComponentSpec,...]:
    feature,label,model,selector,synthesis,_,_,_,_=dense_short_synthesis_components()
    regime=ComponentSpec(display_name="unconditional versus train-top-third volatility routing",protocol="regime.train_top_third_completed_bar_volatility.v1",implementation=_local("simulate_high_vol_dense_regime"),spec={"availability":"completed_bar_only","cutoff_source":"train_is_only_upper_tercile","parameter_fields":["regime_policy"],"policies":list(_POLICIES)},semantic_dependencies=(selector.identity,synthesis.identity))
    trade=ComponentSpec(display_name="fixed long-only next-open entry",protocol="trade.fixed_long_only_next_open.v1",implementation=_local("simulate_high_vol_dense_regime"),spec={"decision_time":"bar_open_plus_5m","direction":"positive_score_only","entry_time":"next_exact_bar_open"},semantic_dependencies=(selector.identity,synthesis.identity,regime.identity))
    lifecycle=ComponentSpec(display_name="fixed 12-bar nonoverlap lifecycle",protocol="lifecycle.fixed_hold_no_overlap.v9",implementation=_local("simulate_high_vol_dense_regime"),spec={"entry_overlap":"reject_while_position_slot_is_occupied","exit_surface":"exact_bar_open_after_12_bars","gap_action":"exclude_path"},semantic_dependencies=(trade.identity,))
    risk=ComponentSpec(display_name="fixed one-lot no-stop risk",protocol="risk.fixed_one_lot.v2",implementation=_local("simulate_high_vol_dense_regime"),spec={"dynamic_sizing":False,"lot":1,"stop":None},semantic_dependencies=(lifecycle.identity,))
    execution=ComponentSpec(display_name="fixed FPMarkets bid-open spread execution",protocol="execution.fpmarkets_bid_open_spread.v1",implementation=_local("simulate_high_vol_dense_regime"),spec={"point":"0.01","stress":"half_effective_spread_each_side"},semantic_dependencies=(risk.identity,))
    return feature,label,model,selector,synthesis,regime,trade,lifecycle,risk,execution
def high_vol_dense_regime_executable(configuration:HighVolDenseRegimeConfiguration)->ExecutableSpec:
    return ExecutableSpec(display_name=f"high vol dense regime {configuration.configuration_id}",components=high_vol_dense_regime_components(),parameters=configuration.semantic_parameters(),data_contract=f"data:{OBSERVED_MATERIAL_ID}",split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v3",cost_contract="cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v3",engine_contract=f"engine:high_vol_dense_regime_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:chassis_{high_vol_dense_regime_chassis_implementation_sha256()}:loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}")
def high_vol_dense_regime_baseline()->ExecutableSpec:return high_vol_dense_regime_executable(high_vol_dense_regime_configurations()[0])
def executable_configuration_map()->dict[str,HighVolDenseRegimeConfiguration]:return {high_vol_dense_regime_executable(v).identity:v for v in high_vol_dense_regime_configurations()}
def simulate_high_vol_dense_regime(*,frame:pd.DataFrame,score:np.ndarray,volatility:np.ndarray,run:np.ndarray,threshold:float,configuration:HighVolDenseRegimeConfiguration,test_start:pd.Timestamp,test_end:pd.Timestamp,fold_id:str,regime_cutoffs:tuple[float,float],effective_spread:np.ndarray|None=None)->SimulationResult:
    gated=np.asarray(score,float).copy()
    if configuration.regime_policy=="train_top_third_volatility_gate":gated[~(np.isfinite(volatility)&(volatility>=regime_cutoffs[1]))]=0.0
    return simulate_dense_short_synthesis(frame=frame,score=gated,volatility=volatility,run=run,threshold=threshold,configuration=DenseShortSynthesisConfiguration("dense_terminal_12_synthesis"),test_start=test_start,test_end=test_end,fold_id=fold_id,regime_cutoffs=regime_cutoffs,effective_spread=effective_spread)
__all__=["SELECTION_TOTAL_EXPOSURES","HighVolDenseRegimeConfiguration","executable_configuration_map","high_vol_dense_regime_baseline","high_vol_dense_regime_chassis_implementation_sha256","high_vol_dense_regime_components","high_vol_dense_regime_configurations","high_vol_dense_regime_executable","loader_implementation_sha256","simulate_high_vol_dense_regime"]
