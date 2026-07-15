"""Router control versus session-gated dense positive US100 sleeve."""
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
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID,ROLLING_SPLIT_SHA256,SELECTION_BOOTSTRAP_SAMPLES,SELECTION_SEED,SimulationResult,concat_simulation_trades,discovery_implementation_sha256,simulate_fixed_hold
from axiom_rift.research.regime_direction_router_chassis import loader_implementation_sha256,regime_direction_router_components

SELECTION_TOTAL_EXPOSURES=581
_PROFILES=("router_control","session_dense_positive_subject")
_THIS_FILE=Path(__file__).resolve()
def session_dense_positive_sleeve_chassis_implementation_sha256()->str:
    """Bind prospective chassis identity to the current file bytes."""
    return sha256(_THIS_FILE.read_bytes()).hexdigest()
@dataclass(frozen=True,slots=True)
class SessionDensePositiveSleeveConfiguration:
    profile:str
    def __post_init__(self)->None:
        if self.profile not in _PROFILES:raise ValueError("session dense positive profile invalid")
    @property
    def configuration_id(self)->str:return self.profile
    @property
    def holding_bars(self)->int:return 12
    @property
    def signal_sign(self)->int:return 1
    @property
    def target_quantile_bp(self)->int:return 9750 if self.profile=="router_control" else 9000
    @property
    def target_session_policy(self)->str:return "all_broker_hours" if self.profile=="router_control" else "broker_15_22_only"
    def semantic_parameters(self)->dict[str,Any]:return {"holding_bars":12,"label_profile":"terminal_return_sign_12","portfolio_profile":self.profile,"profile":"dense_terminal_12_synthesis","ridge_penalty_milli":1000,"route_policy":"high_long_calm_inverse_router","selector_quantile_bp":7000,"signal_sign":1,"target_direction_holding_bars":6,"target_direction_lookback_bars":12,"target_direction_selector_quantile_bp":self.target_quantile_bp,"target_direction_volatility_bars":48,"target_session_policy":self.target_session_policy}
def session_dense_positive_sleeve_configurations()->tuple[SessionDensePositiveSleeveConfiguration,...]:return tuple(SessionDensePositiveSleeveConfiguration(v) for v in _PROFILES)
def _local(name:str)->str:return f"axiom_rift.research.session_dense_positive_sleeve_chassis.{name}@sha256:{session_dense_positive_sleeve_chassis_implementation_sha256()}"
def session_dense_positive_sleeve_components()->tuple[ComponentSpec,...]:
    router=regime_direction_router_components();feature=ComponentSpec(display_name="causal US100 twelve-bar sigma-normalized direction",protocol="feature.us100_direction_12_sigma48.v2",implementation=_local("target_direction_score"),spec={"availability":"completed_bar_only","lookback_bars":12,"volatility_bars":48});selector=ComponentSpec(display_name="train-only US100 direction density selector",protocol="selector.fold_train_abs_quantile.v4",implementation=_local("normalize_scores"),spec={"parameter_fields":["target_direction_selector_quantile_bp"],"registered_quantiles_bp":[9750,9000],"quantile_method":"higher"},semantic_dependencies=(feature.identity,));regime=ComponentSpec(display_name="completed-bar broker-time target sleeve gate",protocol="regime.broker_clock_target_sleeve_gate.v1",implementation=_local("simulate_session_dense_positive_sleeves"),spec={"availability":"completed_bar_only","parameter_fields":["target_session_policy"],"policies":["all_broker_hours","broker_15_22_only"],"no_cash_session_claim":True},semantic_dependencies=(selector.identity,));trade=ComponentSpec(display_name="session-gated US100 direction next-open entry",protocol="trade.session_gated_target_direction_next_open.v1",implementation=_local("simulate_session_dense_positive_sleeves"),spec={"decision_time":"bar_open_plus_5m","entry_time":"next_exact_bar_open"},semantic_dependencies=(selector.identity,regime.identity));life=ComponentSpec(display_name="fixed six-bar target-direction lifecycle",protocol="lifecycle.fixed_hold_no_overlap.v12",implementation=_local("simulate_session_dense_positive_sleeves"),spec={"holding_bars":6,"slot":"target_direction"},semantic_dependencies=(trade.identity,));risk=ComponentSpec(display_name="fixed one-lot target-direction risk",protocol="risk.fixed_one_lot.v5",implementation=_local("simulate_session_dense_positive_sleeves"),spec={"dynamic_sizing":False,"lot":1},semantic_dependencies=(life.identity,));execution=ComponentSpec(display_name="fixed FPMarkets target-direction spread execution",protocol="execution.fpmarkets_bid_open_spread.v4",implementation=_local("simulate_session_dense_positive_sleeves"),spec={"point":"0.01","stress":"half_effective_spread_each_side"},semantic_dependencies=(risk.identity,));prisk=ComponentSpec(display_name="fixed gross session-sleeve exposure",protocol="risk.fixed_session_sleeve_gross_slots.v1",implementation=_local("simulate_session_dense_positive_sleeves"),spec={"dynamic_sizing":False,"parameter_fields":["portfolio_profile"],"profiles":list(_PROFILES),"router_control_max_gross_lots":1,"subject_max_gross_lots":2},semantic_dependencies=(router[-2].identity,risk.identity));portfolio=ComponentSpec(display_name="router and session-dense positive sleeve portfolio",protocol="portfolio.session_dense_positive_sleeves.v1",implementation=_local("simulate_session_dense_positive_sleeves"),spec={"parameter_fields":["portfolio_profile"],"profiles":list(_PROFILES),"per_sleeve_lot":1},semantic_dependencies=(router[-1].identity,execution.identity,prisk.identity));return (*router,feature,selector,regime,trade,life,risk,execution,prisk,portfolio)
def session_dense_positive_sleeve_executable(c:SessionDensePositiveSleeveConfiguration)->ExecutableSpec:return ExecutableSpec(display_name=f"session dense positive sleeves {c.configuration_id}",components=session_dense_positive_sleeve_components(),parameters=c.semantic_parameters(),data_contract=f"data:{OBSERVED_MATERIAL_ID}",split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v6",cost_contract="cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v6",engine_contract=f"engine:session_dense_positive_sleeves_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:chassis_{session_dense_positive_sleeve_chassis_implementation_sha256()}:loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}")
def session_dense_positive_sleeve_baseline()->ExecutableSpec:return session_dense_positive_sleeve_executable(session_dense_positive_sleeve_configurations()[0])
def executable_configuration_map()->dict[str,SessionDensePositiveSleeveConfiguration]:return {session_dense_positive_sleeve_executable(v).identity:v for v in session_dense_positive_sleeve_configurations()}
@dataclass(frozen=True,slots=True)
class _Slot:holding_bars:int;signal_sign:int=1
def _slot(*,frame,score,volatility,run,hold,test_start,test_end,fold_id,regime_cutoffs,effective_spread,name):
    x=simulate_fixed_hold(frame=frame,score=score,volatility=volatility,run=run,threshold=1.0,configuration=_Slot(hold),test_start=test_start,test_end=test_end,fold_id=fold_id,regime_cutoffs=regime_cutoffs,effective_spread=effective_spread)
    x.trades=x.trades.assign(slot=pd.Series(name,index=x.trades.index,dtype="object"))
    x.intent_rows=tuple((name,*r) for r in x.intent_rows);return x
def simulate_session_dense_positive_sleeves(*,frame:pd.DataFrame,score:np.ndarray,volatility:np.ndarray,run:np.ndarray,threshold:float,configuration:SessionDensePositiveSleeveConfiguration,test_start:pd.Timestamp,test_end:pd.Timestamp,fold_id:str,regime_cutoffs:tuple[float,float],effective_spread:np.ndarray|None=None)->SimulationResult:
    del threshold;v=np.asarray(score,float)
    if v.ndim!=2 or v.shape!=(len(frame),2):raise ValueError("session dense positive sleeve score matrix invalid")
    sp=np.asarray(effective_spread,float);slots=[_slot(frame=frame,score=v[:,0],volatility=volatility,run=run,hold=12,test_start=test_start,test_end=test_end,fold_id=fold_id,regime_cutoffs=regime_cutoffs,effective_spread=sp,name="regime_router")]
    if configuration.profile=="session_dense_positive_subject":
        target=v[:,1].copy();entry_hours=(pd.to_datetime(frame["time"],errors="raise")+pd.Timedelta(minutes=5)).dt.hour.to_numpy();target[~np.isin(entry_hours,np.arange(15,23))]=np.nan
        slots.append(_slot(frame=frame,score=target,volatility=volatility,run=run,hold=6,test_start=test_start,test_end=test_end,fold_id=fold_id,regime_cutoffs=regime_cutoffs,effective_spread=sp,name="target_direction"))
    trades=concat_simulation_trades([x.trades for x in slots],extra_columns=("slot",))
    trades=trades.sort_values(["decision_time","slot"],kind="stable").reset_index(drop=True);return SimulationResult(trades,tuple(r for x in slots for r in x.intent_rows),sum(x.unresolved_cost_signal_count for x in slots),sum(x.gap_excluded_signal_count for x in slots),sum(x.causality_violation_count for x in slots))
__all__=["SELECTION_TOTAL_EXPOSURES","SessionDensePositiveSleeveConfiguration","executable_configuration_map","loader_implementation_sha256","session_dense_positive_sleeve_baseline","session_dense_positive_sleeve_chassis_implementation_sha256","session_dense_positive_sleeve_components","session_dense_positive_sleeve_configurations","session_dense_positive_sleeve_executable","simulate_session_dense_positive_sleeves"]
