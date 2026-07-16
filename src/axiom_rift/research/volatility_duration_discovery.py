"""Causal volatility level and state-duration discovery."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any,Mapping
import numpy as np
import pandas as pd
import scipy
from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ComponentSpec,ExecutableSpec,canonical_digest
from axiom_rift.research import data as data_module
from axiom_rift.research.completed_period_atomic_trace import completed_period_proxy_execution_spec
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import DATASET_SHA256,OBSERVED_MATERIAL_ID,ROLLING_SPLIT_SHA256,SELECTION_BOOTSTRAP_SAMPLES,SELECTION_SEED,DiscoveryBoundaryError,_claim_limits,_consecutive_run,_evaluate_configuration,_fold_payloads,_paired_control_pvalue,_selection_adjusted_pvalues,_selection_method,_time_ns,_validate_engine_environment,_validate_fold_payloads,_validate_production_data,discovery_implementation_sha256
SELECTION_TOTAL_EXPOSURES=452;SELECTOR_QUANTILE_BP=10_000;VOLATILITY_WINDOW=96;STATE_WINDOW=1152;_PROFILES=("mature_state_age_24_47","persistent_state_age_72_143");_THIS_FILE=Path(__file__).resolve()
def volatility_duration_implementation_sha256()->str:return sha256(_THIS_FILE.read_bytes()).hexdigest()
def loader_implementation_sha256()->str:return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()
@dataclass(frozen=True,slots=True)
class VolatilityDurationConfiguration:
    profile:str;signal_sign:int;holding_bars:int=24;unknown_entry_action:str="cancel_before_open"
    def __post_init__(self)->None:
        if self.profile not in _PROFILES or self.signal_sign not in {-1,1} or self.holding_bars!=24 or self.unknown_entry_action!="cancel_before_open":raise ValueError("volatility-duration configuration invalid")
    @property
    def configuration_id(self)->str:return f"{self.profile}-{'follow' if self.signal_sign==1 else 'reverse'}-h24"
    def semantic_parameters(self)->dict[str,Any]:return {"holding_bars":24,"profile":self.profile,"signal_sign":self.signal_sign,"state_window":STATE_WINDOW,"unknown_entry_action":self.unknown_entry_action,"volatility_window":VOLATILITY_WINDOW}
def volatility_duration_configurations()->tuple[VolatilityDurationConfiguration,...]:return tuple(VolatilityDurationConfiguration(profile=p,signal_sign=s) for p in _PROFILES for s in (1,-1))
def _local(n:str)->str:return f"axiom_rift.research.volatility_duration_discovery.{n}@sha256:{volatility_duration_implementation_sha256()}"
def _shared(n:str)->str:return f"axiom_rift.research.discovery.{n}@sha256:{discovery_implementation_sha256()}"
def volatility_duration_components()->tuple[ComponentSpec,...]:
    execution_spec=completed_period_proxy_execution_spec(
        repair_policy="same_contiguous_segment_strict_prior_positive_288_bar_median_min_1_else_unknown"
    )
    return (
        ComponentSpec(display_name="causal volatility state-age hazard",protocol="feature.causal_volatility_age_hazard.v1",implementation=_local("compute_volatility_duration_score"),spec={"age_windows":{"mature":[24,47],"persistent":[72,143]},"availability":"completed_bar_close","profiles":list(_PROFILES),"state_reference":"lagged_1152_bar_median_of_96_bar_volatility","parameter_fields":["profile"]}),
        ComponentSpec(display_name="fold isolated event presence selector",protocol="selector.fold_train_event_presence.v1",implementation=_local("calibrate_selector"),spec={"calibration_role":"train_is_only","minimum_train_events":500,"threshold":1}),
        ComponentSpec(display_name="completed-bar next-open directional entry",protocol="trade.completed_bar_next_open_direction.v3",implementation=_shared("simulate_fixed_hold"),spec={"decision_time":"bar_open_plus_5m","entry_time":"next_exact_bar_open","direction":"signal_sign_times_score_sign","unknown_entry_action":"cancel_before_open"}),
        ComponentSpec(display_name="fixed-hold nonoverlap lifecycle",protocol="lifecycle.fixed_hold_no_overlap.v7",implementation=_shared("simulate_fixed_hold"),spec={"entry_overlap":"reject_while_position_slot_is_occupied","exit_surface":"exact_bar_open_after_24_bars","gap_action":"exclude_path","unknown_entry_reservation":False}),
        ComponentSpec(display_name="completed-period spread-proxy execution",protocol="execution.fpmarkets_completed_period_spread_proxy.v2",implementation=_local("causal_state_effective_spread"),spec=execution_spec),
        ComponentSpec(display_name="fixed one-lot risk",protocol="risk.fixed_one_lot.v1",implementation=_shared("simulate_fixed_hold"),spec={"dynamic_sizing":False,"lot":1,"positions_per_sleeve":1}),
    )
def volatility_duration_executable(c:VolatilityDurationConfiguration)->ExecutableSpec:return ExecutableSpec(display_name=f"volatility age hazard {c.configuration_id}",components=volatility_duration_components(),parameters=c.semantic_parameters(),data_contract=f"data:{OBSERVED_MATERIAL_ID}",split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v2",cost_contract="cost:fpmarkets_completed_bar_spread_proxy_segment_positive_median_min_1_unknown_entry_cancel_half_spread_stress_v1",engine_contract=f"engine:volatility_duration_v2:python{'.'.join(str(v) for v in sys.version_info[:3])}:numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:implementation_{volatility_duration_implementation_sha256()}:loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}")
def executable_configuration_map()->dict[str,VolatilityDurationConfiguration]:return {volatility_duration_executable(c).identity:c for c in volatility_duration_configurations()}
def compute_volatility_duration_score(frame:pd.DataFrame,profile:str)->tuple[np.ndarray,np.ndarray,np.ndarray]:
    if profile not in _PROFILES:raise ValueError("volatility-duration profile invalid")
    c=frame["close"].to_numpy(float);ret=np.full(len(c),np.nan);ret[1:]=np.diff(np.log(c));vol=pd.Series(ret).rolling(VOLATILITY_WINDOW,min_periods=VOLATILITY_WINDOW).std(ddof=1).to_numpy(float);reference=pd.Series(vol).shift(1).rolling(STATE_WINDOW,min_periods=STATE_WINDOW).median().to_numpy(float);level=np.divide(vol,reference,out=np.full(len(c),np.nan),where=np.isfinite(reference)&(reference>0))-1
    score=np.full(len(c),np.nan);previous=0;duration=0;bounds=(24,47) if profile=="mature_state_age_24_47" else (72,143)
    for i,value in enumerate(level):
        if not np.isfinite(value):previous=0;duration=0;continue
        state=1 if value>=0 else -1;duration=duration+1 if state==previous else 1;previous=state
        if bounds[0]<=duration<=bounds[1]:score[i]=state
    return score,vol,_consecutive_run(_time_ns(frame))
def causal_state_effective_spread(spread:np.ndarray,time_ns:np.ndarray)->np.ndarray:
    values=np.asarray(spread,float);times=np.asarray(time_ns,np.int64)
    if len(values)!=len(times) or np.any(~np.isfinite(values)) or np.any(values<0):raise ValueError("state spread invalid")
    segment=np.zeros(len(times),np.int64)
    if len(times)>1:segment[1:]=np.cumsum(np.diff(times)!=300_000_000_000)
    positive=pd.Series(np.where(values>0,values,np.nan));groups=pd.Series(segment);lagged=positive.groupby(groups,sort=False).transform(lambda x:x.shift(1).rolling(288,min_periods=1).median());return np.where(values>0,values,lagged.to_numpy(float))
def calibrate_selector(score:np.ndarray,mask:np.ndarray)->float:
    v=np.abs(score[mask&np.isfinite(score)])
    if len(v)<500:raise DiscoveryBoundaryError("volatility-duration event set too small")
    return 1.0
def _matched(results:list[Any],profile:str,sign:int)->Any:
    x=[r for r in results if r.configuration.profile==profile and r.configuration.signal_sign==sign]
    if len(x)!=1:raise DiscoveryBoundaryError("volatility-duration control not unique")
    return x[0]
def _populate(results:list[Any])->None:
    for s in results:
        c=s.configuration;o=_matched(results,c.profile,-c.signal_sign);k=_matched(results,next(p for p in _PROFILES if p!=c.profile),c.signal_sign);s.metrics["opposite_sign_worst_delta_net_profit_micropoints"]=s.metrics["net_profit_micropoints"]-o.metrics["net_profit_micropoints"];s.metrics["opposite_sign_pvalue_upper_ppm"]=_paired_control_pvalue(s,o,role="opposite_sign",total_exposures=SELECTION_TOTAL_EXPOSURES);s.metrics["feature_control_worst_delta_net_profit_micropoints"]=s.metrics["net_profit_micropoints"]-k.metrics["net_profit_micropoints"];s.metrics["feature_control_worst_pvalue_upper_ppm"]=_paired_control_pvalue(s,k,role="volatility_level_control",total_exposures=SELECTION_TOTAL_EXPOSURES)
def compute_registered_volatility_duration_surface(repository_root:str|Path)->dict[str,Any]:
    _validate_engine_environment();data=load_observed_development(Path(repository_root).resolve());_validate_production_data(data);folds=_fold_payloads(data);_validate_fold_payloads(data.frame,folds);frame=data.frame;time=pd.to_datetime(frame["time"],errors="raise");spread=causal_state_effective_spread(frame["spread"].to_numpy(float),_time_ns(frame));prefix_frames={};prefix_spreads={}
    for f in folds:
        fid=str(f["fold_id"]);end=int(time.searchsorted(pd.Timestamp(f["test_oos"]["end"]),side="right"));prefix_frames[fid]=frame.iloc[:end];prefix_spreads[fid]=causal_state_effective_spread(prefix_frames[fid]["spread"].to_numpy(float),_time_ns(prefix_frames[fid]))
    features={};prefixes={};calibrations={}
    for profile in _PROFILES:
        value=compute_volatility_duration_score(frame,profile);features[profile]=value;prefixes[profile]={};calibrations[profile]={}
        for f in folds:
            fid=str(f["fold_id"]);train=f["train_is"];mask=((time>=pd.Timestamp(train["start"]))&(time<=pd.Timestamp(train["end"]))).to_numpy();threshold=calibrate_selector(value[0],mask);vv=value[1][mask&np.isfinite(value[1])];cutoffs=(float(np.quantile(vv,1/3,method="higher")),float(np.quantile(vv,2/3,method="higher")));pv=compute_volatility_duration_score(prefix_frames[fid],profile);prefixes[profile][fid]=pv;pt=pd.to_datetime(prefix_frames[fid]["time"],errors="raise");pm=((pt>=pd.Timestamp(train["start"]))&(pt<=pd.Timestamp(train["end"]))).to_numpy();calibrations[profile][fid]=(threshold,cutoffs,calibrate_selector(pv[0],pm))
    results=[_evaluate_configuration(calibrations=calibrations[c.profile],frame=frame,features=features[c.profile],folds=folds,configuration=c,effective_spread=spread,prefix_features=prefixes[c.profile],prefix_spreads=prefix_spreads,time=time,executable_id=volatility_duration_executable(c).identity) for c in volatility_duration_configurations()];pv=_selection_adjusted_pvalues(results,total_exposures=SELECTION_TOTAL_EXPOSURES)
    for r in results:r.metrics["selection_aware_pvalue_ppm"]=pv[r.executable_id]
    _populate(results);surface={"claim_limits":_claim_limits()+["state_age_windows_are_preregistered","mature_and_persistent_hazard_only","four_trial_surface"],"dataset_sha256":DATASET_SHA256,"engine_environment":{"numpy":np.__version__,"pandas":pd.__version__,"python":".".join(str(v) for v in sys.version_info[:3]),"scipy":scipy.__version__},"evaluations":[{"direction_metrics":r.direction_metrics,"evaluable":all(r.metrics[n]==0 for n in ("unknown_cost_unresolved_signal_count","causality_violation_count","nonfinite_metric_count","prefix_invariance_mismatch_count","append_invariance_mismatch_count")),"fold_metrics":r.fold_metrics,"metrics":dict(sorted(r.metrics.items())),"regime_metrics":r.regime_metrics,"session_metrics":r.session_metrics,"subject_configuration_id":r.configuration.configuration_id,"subject_executable_id":r.executable_id} for r in results],"loader_implementation_sha256":loader_implementation_sha256(),"material_identity":OBSERVED_MATERIAL_ID,"schema":"volatility_duration_surface.v2","selection_context":[{"configuration_id":r.configuration.configuration_id,"executable_id":r.executable_id,"net_profit_micropoints":r.metrics["net_profit_micropoints"],"selection_aware_pvalue_ppm":r.metrics["selection_aware_pvalue_ppm"]} for r in results],"selection_method":_selection_method(SELECTION_TOTAL_EXPOSURES),"session_semantics":"broker_clock_fixed_bins_no_dst_or_cash_session_claim","volatility_duration_implementation_sha256":volatility_duration_implementation_sha256(),"split_artifact_sha256":ROLLING_SPLIT_SHA256};canonical_bytes(surface);return surface
def project_volatility_duration_evaluation(surface:Mapping[str,Any],*,job_execution:Mapping[str,str],subject_executable_id:str,surface_artifact_hash:str,surface_manifest_hash:str)->dict[str,Any]:
    value=dict(surface)
    if sha256(canonical_bytes(value)).hexdigest()!=surface_artifact_hash or value.get("schema")!="volatility_duration_surface.v2":raise DiscoveryBoundaryError("volatility-duration surface invalid")
    expected=executable_configuration_map();by={x.get("subject_executable_id"):x for x in value["evaluations"]}
    if set(by)!=set(expected) or subject_executable_id not in expected:raise DiscoveryBoundaryError("volatility-duration subjects differ")
    payload={n:job_execution[n] for n in ("job_hash","job_id","job_permit_id","start_record_id")}
    if job_execution.get("identity")!=canonical_digest(domain="running-job-execution",payload=payload):raise DiscoveryBoundaryError("Job invalid")
    result={**dict(by[subject_executable_id]),"claim_limits":value["claim_limits"],"job_execution":dict(job_execution),"schema":"volatility_duration_evaluation.v2","selection_context":value["selection_context"],"selection_method":value["selection_method"],"session_semantics":value["session_semantics"],"surface_artifact_hash":surface_artifact_hash,"surface_manifest_hash":surface_manifest_hash};canonical_bytes(result);return result
__all__=["compute_registered_volatility_duration_surface","compute_volatility_duration_score","executable_configuration_map","loader_implementation_sha256","project_volatility_duration_evaluation","volatility_duration_configurations","volatility_duration_executable","volatility_duration_implementation_sha256"]
