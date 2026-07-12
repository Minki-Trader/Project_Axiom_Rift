"""Controlled sparse-48 versus dense-12 long-sleeve synthesis chassis."""
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
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID,ROLLING_SPLIT_SHA256,SELECTION_BOOTSTRAP_SAMPLES,SELECTION_SEED,SimulationResult,discovery_implementation_sha256,simulate_fixed_hold
from axiom_rift.research.equity_premium_trade_chassis import equity_premium_trade_components,loader_implementation_sha256
from axiom_rift.research.event_label_discovery import RIDGE_PENALTY_MILLI
from axiom_rift.research.volatility_clock_label_chassis import volatility_clock_label_chassis_implementation_sha256

SELECTION_TOTAL_EXPOSURES=542
_PROFILES=("sparse_volatility_clock_48_control","dense_terminal_12_synthesis")
_THIS_FILE=Path(__file__).resolve()
def dense_short_synthesis_chassis_implementation_sha256()->str:return sha256(_THIS_FILE.read_bytes()).hexdigest()
@dataclass(frozen=True,slots=True)
class DenseShortSynthesisConfiguration:
    profile:str
    signal_sign:int=1
    def __post_init__(self)->None:
        if self.profile not in _PROFILES or self.signal_sign!=1:raise ValueError("dense short synthesis configuration invalid")
    @property
    def holding_bars(self)->int:return 48 if self.profile==_PROFILES[0] else 12
    @property
    def selector_quantile_bp(self)->int:return 8_500 if self.profile==_PROFILES[0] else 7_000
    @property
    def label_profile(self)->str:return "volatility_clock_terminal_12_of_48" if self.profile==_PROFILES[0] else "terminal_return_sign_12"
    @property
    def configuration_id(self)->str:return f"{self.profile}-long-h{self.holding_bars}-q{self.selector_quantile_bp}"
    def semantic_parameters(self)->dict[str,Any]:return {"holding_bars":self.holding_bars,"label_profile":self.label_profile,"profile":self.profile,"ridge_penalty_milli":RIDGE_PENALTY_MILLI,"selector_quantile_bp":self.selector_quantile_bp,"signal_sign":self.signal_sign}
def dense_short_synthesis_configurations()->tuple[DenseShortSynthesisConfiguration,...]:return tuple(DenseShortSynthesisConfiguration(v) for v in _PROFILES)
def _local(name:str)->str:return f"axiom_rift.research.dense_short_synthesis_chassis.{name}@sha256:{dense_short_synthesis_chassis_implementation_sha256()}"
def dense_short_synthesis_components()->tuple[ComponentSpec,...]:
    feature,_,model,_,_,_,_,_=equity_premium_trade_components()
    label=ComponentSpec(display_name="volatility-clock 48 control versus terminal-return 12 label",protocol="label.sparse48_vs_dense12_synthesis.v1",implementation=_local("build_synthesis_label"),spec={"parameter_fields":["label_profile"],"profiles":["volatility_clock_terminal_12_of_48","terminal_return_sign_12"],"train_future_must_be_inside_fold":True},semantic_dependencies=(feature.identity,))
    model=ComponentSpec(display_name="fixed fold-trained ridge score",protocol="model.fold_train_ridge_linear.v1",implementation=_local("fit_synthesis_model"),spec={"fit_role":"train_is_only","penalty_milli":RIDGE_PENALTY_MILLI,"standardization":"train_mean_population_std"},semantic_dependencies=(feature.identity,label.identity))
    selector=ComponentSpec(display_name="sparse 85th versus dense 70th train-only selector",protocol="selector.sparse85_vs_dense70_synthesis.v1",implementation=_local("calibrate_synthesis_selector"),spec={"calibration_role":"train_is_only","minimum_train_observations":1000,"parameter_fields":["selector_quantile_bp"],"quantile_method":"higher"},semantic_dependencies=(model.identity,))
    synthesis=ComponentSpec(display_name="sparse-48 versus dense-12 sleeve composition",protocol="synthesis.dense_short_sleeve_profile.v1",implementation=_local("simulate_dense_short_synthesis"),spec={"parameter_fields":["profile"],"profiles":list(_PROFILES)},semantic_dependencies=(label.identity,selector.identity))
    trade=ComponentSpec(display_name="fixed long-only next-open entry",protocol="trade.fixed_long_only_next_open.v1",implementation=_local("simulate_dense_short_synthesis"),spec={"decision_time":"bar_open_plus_5m","direction":"positive_score_only","entry_time":"next_exact_bar_open"},semantic_dependencies=(selector.identity,synthesis.identity))
    lifecycle=ComponentSpec(display_name="sparse 48 versus dense 12 nonoverlap lifecycle",protocol="lifecycle.sparse48_vs_dense12_synthesis.v1",implementation=_local("simulate_dense_short_synthesis"),spec={"entry_overlap":"reject_while_position_slot_is_occupied","gap_action":"exclude_path","parameter_fields":["holding_bars"]},semantic_dependencies=(trade.identity,))
    risk=ComponentSpec(display_name="fixed one-lot no-stop risk",protocol="risk.fixed_one_lot.v2",implementation=_local("simulate_dense_short_synthesis"),spec={"dynamic_sizing":False,"lot":1,"stop":None},semantic_dependencies=(lifecycle.identity,))
    execution=ComponentSpec(display_name="fixed FPMarkets bid-open spread execution",protocol="execution.fpmarkets_bid_open_spread.v1",implementation=_local("simulate_dense_short_synthesis"),spec={"point":"0.01","stress":"half_effective_spread_each_side"},semantic_dependencies=(risk.identity,))
    return feature,label,model,selector,synthesis,trade,lifecycle,risk,execution
def dense_short_synthesis_executable(configuration:DenseShortSynthesisConfiguration)->ExecutableSpec:
    return ExecutableSpec(display_name=f"dense short synthesis {configuration.configuration_id}",components=dense_short_synthesis_components(),parameters=configuration.semantic_parameters(),data_contract=f"data:{OBSERVED_MATERIAL_ID}",split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v3",cost_contract="cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v3",engine_contract=f"engine:dense_short_synthesis_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:chassis_{dense_short_synthesis_chassis_implementation_sha256()}:volatility_{volatility_clock_label_chassis_implementation_sha256()}:loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}")
def dense_short_synthesis_baseline()->ExecutableSpec:return dense_short_synthesis_executable(dense_short_synthesis_configurations()[0])
def executable_configuration_map()->dict[str,DenseShortSynthesisConfiguration]:return {dense_short_synthesis_executable(v).identity:v for v in dense_short_synthesis_configurations()}
def terminal_return_sign_12(frame:pd.DataFrame,run:np.ndarray)->np.ndarray:
    count=len(frame);result=np.full(count,np.nan);last=count-13
    if last<=0:return result
    indices=np.arange(last);valid=run[indices+13]>=14;log_open=np.log(frame["open"].to_numpy(float));terminal=log_open[indices+13]-log_open[indices+1];result[indices[valid]]=np.sign(terminal[valid]);return result
def calibrate_synthesis_selector(score:np.ndarray,mask:np.ndarray,quantile_bp:int)->float:
    values=np.abs(score[mask&np.isfinite(score)])
    if len(values)<1000:raise ValueError("dense synthesis selector set too small")
    return float(np.quantile(values,quantile_bp/10000,method="higher"))
def simulate_dense_short_synthesis(*,frame:pd.DataFrame,score:np.ndarray,volatility:np.ndarray,run:np.ndarray,threshold:float,configuration:DenseShortSynthesisConfiguration,test_start:pd.Timestamp,test_end:pd.Timestamp,fold_id:str,regime_cutoffs:tuple[float,float],effective_spread:np.ndarray|None=None)->SimulationResult:
    gated=np.asarray(score,float).copy();gated[gated<0]=0.0
    return simulate_fixed_hold(frame=frame,score=gated,volatility=volatility,run=run,threshold=threshold,configuration=configuration,test_start=test_start,test_end=test_end,fold_id=fold_id,regime_cutoffs=regime_cutoffs,effective_spread=effective_spread)
__all__=["SELECTION_TOTAL_EXPOSURES","DenseShortSynthesisConfiguration","calibrate_synthesis_selector","dense_short_synthesis_baseline","dense_short_synthesis_chassis_implementation_sha256","dense_short_synthesis_components","dense_short_synthesis_configurations","dense_short_synthesis_executable","executable_configuration_map","loader_implementation_sha256","simulate_dense_short_synthesis","terminal_return_sign_12"]
