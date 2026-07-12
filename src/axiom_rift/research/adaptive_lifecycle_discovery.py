"""Entry-invariant adaptive trade-lifecycle discovery."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from math import sqrt
import sys
from typing import Any,Mapping
import numpy as np
import pandas as pd
import scipy
from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ComponentSpec,ExecutableSpec,canonical_digest
from axiom_rift.research import data as data_module
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import DATASET_SHA256,OBSERVED_MATERIAL_ID,ROLLING_SPLIT_SHA256,SELECTION_BOOTSTRAP_SAMPLES,SELECTION_SEED,DiscoveryBoundaryError,SimulationResult,_claim_limits,_consecutive_run,_evaluate_configuration,_fold_payloads,_paired_control_pvalue,_selection_adjusted_pvalues,_selection_method,_time_ns,_validate_engine_environment,_validate_fold_payloads,_validate_production_data,causal_effective_spread,discovery_implementation_sha256,execution_pnl
SELECTION_TOTAL_EXPOSURES=504;SELECTOR_QUANTILE_BP=8_500;ENTRY_WINDOW=96;MAX_HOLD=96;MIN_STATE_HOLD=12;STOP_MULTIPLE_MILLI=0;TAKE_MULTIPLE_MILLI=0;_PROFILES=("opposite_state_exit_96","fixed_hold_control_96");_THIS_FILE=Path(__file__).resolve();_FIVE_MINUTES_NS=300_000_000_000
def adaptive_lifecycle_implementation_sha256()->str:return sha256(_THIS_FILE.read_bytes()).hexdigest()
def loader_implementation_sha256()->str:return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()
@dataclass(frozen=True,slots=True)
class AdaptiveLifecycleConfiguration:
    profile:str;signal_sign:int;holding_bars:int=MAX_HOLD
    def __post_init__(self)->None:
        if self.profile not in _PROFILES or self.signal_sign not in {-1,1} or self.holding_bars!=MAX_HOLD:raise ValueError("adaptive-lifecycle configuration invalid")
    @property
    def configuration_id(self)->str:return f"{self.profile}-{'continue' if self.signal_sign==1 else 'reverse'}-max{MAX_HOLD}"
    def semantic_parameters(self)->dict[str,Any]:return {"entry_window":ENTRY_WINDOW,"holding_bars":MAX_HOLD,"minimum_state_hold":MIN_STATE_HOLD,"profile":self.profile,"selector_quantile_bp":SELECTOR_QUANTILE_BP,"signal_sign":self.signal_sign}
def adaptive_lifecycle_configurations()->tuple[AdaptiveLifecycleConfiguration,...]:return tuple(AdaptiveLifecycleConfiguration(profile=p,signal_sign=s) for p in _PROFILES for s in (1,-1))
def _local(n:str)->str:return f"axiom_rift.research.adaptive_lifecycle_discovery.{n}@sha256:{adaptive_lifecycle_implementation_sha256()}"
def _shared(n:str)->str:return f"axiom_rift.research.discovery.{n}@sha256:{discovery_implementation_sha256()}"
def adaptive_lifecycle_components()->tuple[ComponentSpec,...]:return (ComponentSpec(display_name="shared causal normalized 96-bar entry",protocol="feature.shared_normalized_return_entry.v2",implementation=_local("compute_entry_score"),spec={"availability":"completed_bar_only","entry_window":ENTRY_WINDOW,"same_entry_across_profiles":True}),ComponentSpec(display_name="fold isolated shared entry selector",protocol="selector.fold_train_abs_quantile.v2",implementation=_local("calibrate_selector"),spec={"calibration_role":"train_is_only","minimum_train_observations":1000,"quantile_basis_points":SELECTOR_QUANTILE_BP,"quantile_method":"higher"}),ComponentSpec(display_name="completed-bar next-open directional entry",protocol="trade.completed_bar_next_open_direction.v2",implementation=_local("simulate_adaptive_lifecycle"),spec={"decision_time":"bar_open_plus_5m","entry_time":"next_exact_bar_open","direction":"signal_sign_times_score_sign","same_entry_across_profiles":True}),ComponentSpec(display_name="opposite-state or fixed-hold lifecycle",protocol="lifecycle.opposite_state_vs_fixed_hold.v1",implementation=_local("simulate_adaptive_lifecycle"),spec={"entry_overlap":"reject_while_position_slot_is_occupied","exit_on_opposite_state":"next_open_after_completed_state_bar","fixed_control_bars":MAX_HOLD,"maximum_holding_bars":MAX_HOLD,"minimum_state_hold":MIN_STATE_HOLD,"profiles":list(_PROFILES),"parameter_fields":["profile"]}),ComponentSpec(display_name="FPMarkets bid-bar spread execution",protocol="execution.fpmarkets_bid_bar_spread.v2",implementation=_shared("execution_pnl"),spec={"point":"0.01","stress":"half_effective_spread_each_side"}),ComponentSpec(display_name="fixed one-lot risk",protocol="risk.fixed_one_lot.v1",implementation=_local("simulate_adaptive_lifecycle"),spec={"dynamic_sizing":False,"lot":1,"positions_per_sleeve":1}))
def adaptive_lifecycle_executable(c:AdaptiveLifecycleConfiguration)->ExecutableSpec:return ExecutableSpec(display_name=f"adaptive lifecycle {c.configuration_id}",components=adaptive_lifecycle_components(),parameters=c.semantic_parameters(),data_contract=f"data:{OBSERVED_MATERIAL_ID}",split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v2",cost_contract="cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v2",engine_contract=f"engine:adaptive_lifecycle_v2:python{'.'.join(str(v) for v in sys.version_info[:3])}:numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:implementation_{adaptive_lifecycle_implementation_sha256()}:loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}")
def executable_configuration_map()->dict[str,AdaptiveLifecycleConfiguration]:return {adaptive_lifecycle_executable(c).identity:c for c in adaptive_lifecycle_configurations()}
def compute_entry_score(frame:pd.DataFrame,profile:str)->tuple[np.ndarray,np.ndarray,np.ndarray]:
    if profile not in _PROFILES:raise ValueError("adaptive-lifecycle profile invalid")
    close=frame["close"].to_numpy(float);log=np.log(close);ret=np.full(len(close),np.nan);ret[1:]=np.diff(log);vol=pd.Series(ret).rolling(96,min_periods=96).std(ddof=1).to_numpy(float);change=np.full(len(close),np.nan);change[ENTRY_WINDOW:]=log[ENTRY_WINDOW:]-log[:-ENTRY_WINDOW];score=np.divide(change,vol*np.sqrt(ENTRY_WINDOW),out=np.full(len(close),np.nan),where=np.isfinite(vol)&(vol>0));run=_consecutive_run(_time_ns(frame));score[run<97]=np.nan;return score,vol,run
def calibrate_selector(score:np.ndarray,mask:np.ndarray)->float:
    v=np.abs(score[mask&np.isfinite(score)])
    if len(v)<1000:raise DiscoveryBoundaryError("adaptive-lifecycle selector too small")
    return float(np.quantile(v,SELECTOR_QUANTILE_BP/10000,method="higher"))
def simulate_adaptive_lifecycle(*,frame:pd.DataFrame,score:np.ndarray,volatility:np.ndarray,run:np.ndarray,threshold:float,configuration:AdaptiveLifecycleConfiguration,test_start:pd.Timestamp,test_end:pd.Timestamp,fold_id:str,regime_cutoffs:tuple[float,float],effective_spread:np.ndarray|None=None)->SimulationResult:
    time=pd.to_datetime(frame["time"],errors="raise");time_ns=_time_ns(frame);opens=frame["open"].to_numpy(float);spreads=causal_effective_spread(frame["spread"].to_numpy(float),time_ns) if effective_spread is None else np.asarray(effective_spread,float);candidates=np.flatnonzero(((time>=test_start)&(time<=test_end)).to_numpy()&np.isfinite(score));records=[];intents=[];next_decision=-1;unresolved=0;gap_excluded=0;causality=0
    for decision_index in candidates:
        if decision_index<next_decision or abs(score[decision_index])<threshold:continue
        direction=int(np.sign(score[decision_index]))*configuration.signal_sign
        if direction==0:continue
        entry=decision_index+1;maximum=entry+MAX_HOLD
        if maximum>=len(frame) or time.iloc[maximum]>test_end:continue
        decision_time=time.iloc[decision_index]+pd.Timedelta(minutes=5);entry_time=time.iloc[entry]
        if time_ns[entry]-time_ns[decision_index]!=_FIVE_MINUTES_NS:gap_excluded+=1;intents.append((decision_time,entry_time,time.iloc[maximum],direction,"gap_excluded"));continue
        if decision_time!=entry_time:causality+=1;intents.append((decision_time,entry_time,time.iloc[maximum],direction,"causality_violation"));continue
        exit_index=maximum;gap=False
        if configuration.profile=="opposite_state_exit_96":
            for state_decision in range(entry+MIN_STATE_HOLD-1,maximum):
                candidate=state_decision+1
                if time_ns[candidate]-time_ns[candidate-1]!=_FIVE_MINUTES_NS:gap=True;break
                state_direction=0 if not np.isfinite(score[state_decision]) or abs(score[state_decision])<threshold else int(np.sign(score[state_decision]))*configuration.signal_sign
                if state_direction==-direction:exit_index=candidate;break
        elif run[maximum]<MAX_HOLD+2:gap=True
        if run[exit_index]<exit_index-decision_index+1:gap=True
        if gap:gap_excluded+=1;intents.append((decision_time,entry_time,time.iloc[exit_index],direction,"gap_excluded"));continue
        next_decision=exit_index
        if not (np.isfinite(spreads[entry]) and np.isfinite(spreads[exit_index])):unresolved+=1;intents.append((decision_time,entry_time,time.iloc[exit_index],direction,"unknown_cost"));continue
        native,stress=execution_pnl(direction=direction,entry_bid=float(opens[entry]),exit_bid=float(opens[exit_index]),entry_spread_points=float(spreads[entry]),exit_spread_points=float(spreads[exit_index]));entry_vol=float(volatility[decision_index]);regime="low" if entry_vol<=regime_cutoffs[0] else "high" if entry_vol>=regime_cutoffs[1] else "middle";records.append({"decision_bar_open_time":time.iloc[decision_index],"decision_time":decision_time,"entry_time":entry_time,"exit_time":time.iloc[exit_index],"direction":direction,"pnl":native,"stress_pnl":stress,"fold_id":fold_id,"regime":regime});intents.append((decision_time,entry_time,time.iloc[exit_index],direction,"executed"))
    trades=pd.DataFrame.from_records(records)
    if trades.empty:trades=pd.DataFrame(columns=("decision_bar_open_time","decision_time","entry_time","exit_time","direction","pnl","stress_pnl","fold_id","regime"))
    return SimulationResult(trades=trades,intent_rows=tuple(intents),unresolved_cost_signal_count=unresolved,gap_excluded_signal_count=gap_excluded,causality_violation_count=causality)
def _matched(results:list[Any],profile:str,sign:int)->Any:
    found=[r for r in results if r.configuration.profile==profile and r.configuration.signal_sign==sign]
    if len(found)!=1:raise DiscoveryBoundaryError("adaptive-lifecycle control not unique")
    return found[0]
def _populate(results:list[Any])->None:
    for s in results:
        c=s.configuration;o=_matched(results,c.profile,-c.signal_sign);k=_matched(results,next(p for p in _PROFILES if p!=c.profile),c.signal_sign);s.metrics["opposite_sign_worst_delta_net_profit_micropoints"]=s.metrics["net_profit_micropoints"]-o.metrics["net_profit_micropoints"];s.metrics["opposite_sign_pvalue_upper_ppm"]=_paired_control_pvalue(s,o,role="opposite_sign",total_exposures=SELECTION_TOTAL_EXPOSURES);s.metrics["feature_control_worst_delta_net_profit_micropoints"]=s.metrics["net_profit_micropoints"]-k.metrics["net_profit_micropoints"];s.metrics["feature_control_worst_pvalue_upper_ppm"]=_paired_control_pvalue(s,k,role="fixed_hold_96_lifecycle_control",total_exposures=SELECTION_TOTAL_EXPOSURES)
def compute_registered_adaptive_lifecycle_surface(repository_root:str|Path)->dict[str,Any]:
    _validate_engine_environment();data=load_observed_development(Path(repository_root).resolve());_validate_production_data(data);folds=_fold_payloads(data);_validate_fold_payloads(data.frame,folds);frame=data.frame;time=pd.to_datetime(frame["time"],errors="raise");spread=causal_effective_spread(frame["spread"].to_numpy(float),_time_ns(frame));prefix_frames={};prefix_spreads={}
    for f in folds:
        fid=str(f["fold_id"]);end=int(time.searchsorted(pd.Timestamp(f["test_oos"]["end"]),side="right"));prefix_frames[fid]=frame.iloc[:end];prefix_spreads[fid]=causal_effective_spread(prefix_frames[fid]["spread"].to_numpy(float),_time_ns(prefix_frames[fid]))
    value=compute_entry_score(frame,_PROFILES[0]);prefixes={};calibrations={}
    for f in folds:
        fid=str(f["fold_id"]);train=f["train_is"];mask=((time>=pd.Timestamp(train["start"]))&(time<=pd.Timestamp(train["end"]))).to_numpy();pv=compute_entry_score(prefix_frames[fid],_PROFILES[0]);prefixes[fid]=pv;pt=pd.to_datetime(prefix_frames[fid]["time"],errors="raise");pm=((pt>=pd.Timestamp(train["start"]))&(pt<=pd.Timestamp(train["end"]))).to_numpy();vv=value[1][mask&np.isfinite(value[1])];cutoffs=(float(np.quantile(vv,1/3,method="higher")),float(np.quantile(vv,2/3,method="higher")));calibrations[fid]=(calibrate_selector(value[0],mask),cutoffs,calibrate_selector(pv[0],pm))
    results=[_evaluate_configuration(calibrations=calibrations,frame=frame,features=value,folds=folds,configuration=c,effective_spread=spread,prefix_features=prefixes,prefix_spreads=prefix_spreads,time=time,executable_id=adaptive_lifecycle_executable(c).identity,simulation_fn=simulate_adaptive_lifecycle) for c in adaptive_lifecycle_configurations()];adjusted=_selection_adjusted_pvalues(results,total_exposures=SELECTION_TOTAL_EXPOSURES)
    for r in results:r.metrics["selection_aware_pvalue_ppm"]=adjusted[r.executable_id]
    _populate(results);surface={"adaptive_lifecycle_implementation_sha256":adaptive_lifecycle_implementation_sha256(),"claim_limits":_claim_limits()+["entry_signal_and_selector_are_identical_across_lifecycles","opposite_state_exit_occurs_at_next_open_after_completed_state_bar","four_trial_surface"],"dataset_sha256":DATASET_SHA256,"engine_environment":{"numpy":np.__version__,"pandas":pd.__version__,"python":".".join(str(v) for v in sys.version_info[:3]),"scipy":scipy.__version__},"evaluations":[{"direction_metrics":r.direction_metrics,"evaluable":all(r.metrics[n]==0 for n in ("unknown_cost_unresolved_signal_count","causality_violation_count","nonfinite_metric_count","prefix_invariance_mismatch_count","append_invariance_mismatch_count")),"fold_metrics":r.fold_metrics,"metrics":dict(sorted(r.metrics.items())),"regime_metrics":r.regime_metrics,"session_metrics":r.session_metrics,"subject_configuration_id":r.configuration.configuration_id,"subject_executable_id":r.executable_id} for r in results],"loader_implementation_sha256":loader_implementation_sha256(),"material_identity":OBSERVED_MATERIAL_ID,"schema":"adaptive_lifecycle_surface.v2","selection_context":[{"configuration_id":r.configuration.configuration_id,"executable_id":r.executable_id,"net_profit_micropoints":r.metrics["net_profit_micropoints"],"selection_aware_pvalue_ppm":r.metrics["selection_aware_pvalue_ppm"]} for r in results],"selection_method":_selection_method(SELECTION_TOTAL_EXPOSURES),"session_semantics":"broker_clock_fixed_bins_no_dst_or_cash_session_claim","split_artifact_sha256":ROLLING_SPLIT_SHA256};canonical_bytes(surface);return surface
def project_adaptive_lifecycle_evaluation(surface:Mapping[str,Any],*,job_execution:Mapping[str,str],subject_executable_id:str,surface_artifact_hash:str,surface_manifest_hash:str)->dict[str,Any]:
    value=dict(surface)
    if sha256(canonical_bytes(value)).hexdigest()!=surface_artifact_hash or value.get("schema")!="adaptive_lifecycle_surface.v2":raise DiscoveryBoundaryError("adaptive-lifecycle surface invalid")
    expected=executable_configuration_map();by={x.get("subject_executable_id"):x for x in value["evaluations"]}
    if set(by)!=set(expected) or subject_executable_id not in expected:raise DiscoveryBoundaryError("adaptive-lifecycle subjects differ")
    payload={n:job_execution[n] for n in ("job_hash","job_id","job_permit_id","start_record_id")}
    if job_execution.get("identity")!=canonical_digest(domain="running-job-execution",payload=payload):raise DiscoveryBoundaryError("Job invalid")
    result={**dict(by[subject_executable_id]),"claim_limits":value["claim_limits"],"job_execution":dict(job_execution),"schema":"adaptive_lifecycle_evaluation.v2","selection_context":value["selection_context"],"selection_method":value["selection_method"],"session_semantics":value["session_semantics"],"surface_artifact_hash":surface_artifact_hash,"surface_manifest_hash":surface_manifest_hash};canonical_bytes(result);return result
__all__=["adaptive_lifecycle_configurations","adaptive_lifecycle_executable","adaptive_lifecycle_implementation_sha256","compute_entry_score","compute_registered_adaptive_lifecycle_surface","executable_configuration_map","loader_implementation_sha256","project_adaptive_lifecycle_evaluation","simulate_adaptive_lifecycle"]
