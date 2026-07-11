"""Causal broker-time discontinuity and gap-recovery discovery."""
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
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import DATASET_SHA256,OBSERVED_MATERIAL_ID,ROLLING_SPLIT_SHA256,SELECTION_BOOTSTRAP_SAMPLES,SELECTION_SEED,DiscoveryBoundaryError,_claim_limits,_consecutive_run,_evaluate_configuration,_fold_payloads,_paired_control_pvalue,_selection_adjusted_pvalues,_selection_method,_time_ns,_validate_engine_environment,_validate_fold_payloads,_validate_production_data,causal_effective_spread,discovery_implementation_sha256
SELECTION_TOTAL_EXPOSURES=432;SELECTOR_QUANTILE_BP=7_000;_PROFILES=("open_gap_30m","first_bar_response_30m");_THIS_FILE=Path(__file__).resolve();_MIN_GAP_MINUTES=30
def gap_implementation_sha256()->str:return sha256(_THIS_FILE.read_bytes()).hexdigest()
def loader_implementation_sha256()->str:return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()
@dataclass(frozen=True,slots=True)
class GapConfiguration:
    profile:str;signal_sign:int;holding_bars:int=12;unknown_entry_action:str="cancel_before_open"
    def __post_init__(self)->None:
        if self.profile not in _PROFILES or self.signal_sign not in {-1,1} or self.holding_bars!=12 or self.unknown_entry_action!="cancel_before_open":raise ValueError("gap configuration invalid")
    @property
    def configuration_id(self)->str:return f"{self.profile}-{'continuation' if self.signal_sign==1 else 'recovery'}-h12"
    def semantic_parameters(self)->dict[str,Any]:return {"holding_bars":12,"minimum_gap_minutes":30,"profile":self.profile,"selector_quantile_bp":SELECTOR_QUANTILE_BP,"signal_sign":self.signal_sign,"unknown_entry_action":self.unknown_entry_action}
def gap_configurations()->tuple[GapConfiguration,...]:return tuple(GapConfiguration(profile=p,signal_sign=s) for p in _PROFILES for s in (1,-1))
def _local(n:str)->str:return f"axiom_rift.research.gap_recovery_discovery.{n}@sha256:{gap_implementation_sha256()}"
def _shared(n:str)->str:return f"axiom_rift.research.discovery.{n}@sha256:{discovery_implementation_sha256()}"
def gap_components()->tuple[ComponentSpec,...]:return (ComponentSpec(display_name="causal broker-time gap event",protocol="feature.causal_gap_recovery.v1",implementation=_local("compute_gap_score"),spec={"availability":"first_completed_bar_after_gap","minimum_gap_minutes":30,"profiles":list(_PROFILES),"non_event_value":"missing","parameter_fields":["profile"]}),ComponentSpec(display_name="fold isolated event selector",protocol="selector.fold_train_abs_quantile.v3",implementation=_local("calibrate_selector"),spec={"calibration_role":"train_is_only","minimum_train_observations":350,"quantile_basis_points":SELECTOR_QUANTILE_BP,"quantile_method":"higher"}),ComponentSpec(display_name="completed-bar next-open directional entry",protocol="trade.completed_bar_next_open_direction.v3",implementation=_shared("simulate_fixed_hold"),spec={"decision_time":"bar_open_plus_5m","entry_time":"next_exact_bar_open","direction":"signal_sign_times_score_sign","parameter_fields":["signal_sign"],"unknown_entry_action":"cancel_before_open"}),ComponentSpec(display_name="fixed-hold nonoverlap lifecycle",protocol="lifecycle.fixed_hold_no_overlap.v3",implementation=_shared("simulate_fixed_hold"),spec={"entry_overlap":"reject_while_position_slot_is_occupied","exit_surface":"exact_bar_open_after_12_bars","gap_action":"exclude_path","unknown_entry_reservation":False}),ComponentSpec(display_name="FPMarkets gap-segment spread execution",protocol="execution.fpmarkets_gap_segment_spread.v1",implementation=_local("causal_gap_effective_spread"),spec={"observed_positive_spread":"use_as_is","point":"0.01","stress":"half_effective_spread_each_side","zero_spread":"lagged_positive_segment_median_min_1_else_unknown"}),ComponentSpec(display_name="fixed one-lot risk",protocol="risk.fixed_one_lot.v1",implementation=_shared("simulate_fixed_hold"),spec={"dynamic_sizing":False,"lot":1,"positions_per_sleeve":1}))
def gap_executable(c:GapConfiguration)->ExecutableSpec:return ExecutableSpec(display_name=f"gap recovery {c.configuration_id}",components=gap_components(),parameters=c.semantic_parameters(),data_contract=f"data:{OBSERVED_MATERIAL_ID}",split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v2",cost_contract="cost:bid_bar_gap_segment_positive_median_min_1_unknown_entry_cancel_half_spread_stress_v1",engine_contract=f"engine:gap_recovery_v3:python{'.'.join(str(v) for v in sys.version_info[:3])}:numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:implementation_{gap_implementation_sha256()}:loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}")
def executable_configuration_map()->dict[str,GapConfiguration]:return {gap_executable(c).identity:c for c in gap_configurations()}
def compute_gap_score(frame:pd.DataFrame,profile:str)->tuple[np.ndarray,np.ndarray,np.ndarray]:
    if profile not in _PROFILES:raise ValueError("profile invalid")
    time_ns=_time_ns(frame);delta=np.full(len(frame),np.nan);delta[1:]=np.diff(time_ns)/60_000_000_000;event=delta>=_MIN_GAP_MINUTES;o=frame["open"].to_numpy(float);c=frame["close"].to_numpy(float);raw=np.full(len(frame),np.nan);raw[event]=(o[event]-np.roll(c,1)[event]) if profile=="open_gap_30m" else (c[event]-o[event]);ret=np.full(len(c),np.nan);ret[1:]=np.diff(np.log(c));vol=pd.Series(ret).rolling(96,min_periods=96).std(ddof=1).to_numpy(float);score=np.divide(raw,c*vol,out=np.full(len(c),np.nan),where=np.isfinite(vol)&(vol>0));run=_consecutive_run(time_ns);return score,vol,run
def causal_gap_effective_spread(spread:np.ndarray,time_ns:np.ndarray)->np.ndarray:
    values=np.asarray(spread,dtype=float);times=np.asarray(time_ns,dtype=np.int64)
    if len(values)!=len(times) or np.any(~np.isfinite(values)) or np.any(values<0):raise ValueError("gap spread invalid")
    segment=np.zeros(len(times),dtype=np.int64)
    if len(times)>1:segment[1:]=np.cumsum(np.diff(times)!=300_000_000_000)
    positive=pd.Series(np.where(values>0,values,np.nan));groups=pd.Series(segment);lagged=positive.groupby(groups,sort=False).transform(lambda part:part.shift(1).rolling(288,min_periods=1).median())
    return np.where(values>0,values,lagged.to_numpy(dtype=float))
def calibrate_selector(score:np.ndarray,mask:np.ndarray)->float:
    v=np.abs(score[mask&np.isfinite(score)])
    if len(v)<350:raise DiscoveryBoundaryError("gap selector too small")
    return float(np.quantile(v,SELECTOR_QUANTILE_BP/10000,method="higher"))
def _matched(results:list[Any],profile:str,sign:int)->Any:
    found=[r for r in results if r.configuration.profile==profile and r.configuration.signal_sign==sign]
    if len(found)!=1:raise DiscoveryBoundaryError("control not unique")
    return found[0]
def _populate(results:list[Any])->None:
    for s in results:
        c=s.configuration;opposite=_matched(results,c.profile,-c.signal_sign);control=_matched(results,next(p for p in _PROFILES if p!=c.profile),c.signal_sign);s.metrics["opposite_sign_worst_delta_net_profit_micropoints"]=s.metrics["net_profit_micropoints"]-opposite.metrics["net_profit_micropoints"];s.metrics["opposite_sign_pvalue_upper_ppm"]=_paired_control_pvalue(s,opposite,role="opposite_sign",total_exposures=SELECTION_TOTAL_EXPOSURES);s.metrics["feature_control_worst_delta_net_profit_micropoints"]=s.metrics["net_profit_micropoints"]-control.metrics["net_profit_micropoints"];s.metrics["feature_control_worst_pvalue_upper_ppm"]=_paired_control_pvalue(s,control,role="gap_profile",total_exposures=SELECTION_TOTAL_EXPOSURES)
def compute_registered_gap_surface(repository_root:str|Path)->dict[str,Any]:
    _validate_engine_environment();data=load_observed_development(Path(repository_root).resolve());_validate_production_data(data);folds=_fold_payloads(data);_validate_fold_payloads(data.frame,folds);frame=data.frame;time=pd.to_datetime(frame["time"],errors="raise");spread=causal_gap_effective_spread(frame["spread"].to_numpy(float),_time_ns(frame));prefix_frames={};prefix_spreads={}
    for f in folds:
        fid=str(f["fold_id"]);end=int(time.searchsorted(pd.Timestamp(f["test_oos"]["end"]),side="right"));prefix_frames[fid]=frame.iloc[:end];prefix_spreads[fid]=causal_gap_effective_spread(prefix_frames[fid]["spread"].to_numpy(float),_time_ns(prefix_frames[fid]))
    features={};prefixes={};calibrations={}
    for profile in _PROFILES:
        value=compute_gap_score(frame,profile);features[profile]=value;prefixes[profile]={};calibrations[profile]={}
        for f in folds:
            fid=str(f["fold_id"]);train=f["train_is"];mask=((time>=pd.Timestamp(train["start"]))&(time<=pd.Timestamp(train["end"]))).to_numpy();threshold=calibrate_selector(value[0],mask);vv=value[1][mask&np.isfinite(value[1])];cutoffs=(float(np.quantile(vv,1/3,method="higher")),float(np.quantile(vv,2/3,method="higher")));pv=compute_gap_score(prefix_frames[fid],profile);prefixes[profile][fid]=pv;pt=pd.to_datetime(prefix_frames[fid]["time"],errors="raise");pm=((pt>=pd.Timestamp(train["start"]))&(pt<=pd.Timestamp(train["end"]))).to_numpy();calibrations[profile][fid]=(threshold,cutoffs,calibrate_selector(pv[0],pm))
    results=[_evaluate_configuration(calibrations=calibrations[c.profile],frame=frame,features=features[c.profile],folds=folds,configuration=c,effective_spread=spread,prefix_features=prefixes[c.profile],prefix_spreads=prefix_spreads,time=time,executable_id=gap_executable(c).identity) for c in gap_configurations()];pv=_selection_adjusted_pvalues(results,total_exposures=SELECTION_TOTAL_EXPOSURES)
    for r in results:r.metrics["selection_aware_pvalue_ppm"]=pv[r.executable_id]
    _populate(results);surface={"claim_limits":_claim_limits()+["gap_events_require_broker_time_discontinuity","four_trial_surface","minimum_fold_calibration_count_350","unknown_entry_cost_cancels_before_open","exit_zero_spread_uses_lagged_positive_gap_segment_median"],"dataset_sha256":DATASET_SHA256,"engine_environment":{"numpy":np.__version__,"pandas":pd.__version__,"python":".".join(str(v) for v in sys.version_info[:3]),"scipy":scipy.__version__},"evaluations":[{"direction_metrics":r.direction_metrics,"evaluable":all(r.metrics[n]==0 for n in ("unknown_cost_unresolved_signal_count","causality_violation_count","nonfinite_metric_count","prefix_invariance_mismatch_count","append_invariance_mismatch_count")),"fold_metrics":r.fold_metrics,"metrics":dict(sorted(r.metrics.items())),"regime_metrics":r.regime_metrics,"session_metrics":r.session_metrics,"subject_configuration_id":r.configuration.configuration_id,"subject_executable_id":r.executable_id} for r in results],"loader_implementation_sha256":loader_implementation_sha256(),"material_identity":OBSERVED_MATERIAL_ID,"schema":"gap_recovery_surface.v3","selection_context":[{"configuration_id":r.configuration.configuration_id,"executable_id":r.executable_id,"net_profit_micropoints":r.metrics["net_profit_micropoints"],"selection_aware_pvalue_ppm":r.metrics["selection_aware_pvalue_ppm"]} for r in results],"selection_method":_selection_method(SELECTION_TOTAL_EXPOSURES),"session_semantics":"broker_clock_fixed_bins_no_dst_or_cash_session_claim","gap_implementation_sha256":gap_implementation_sha256(),"split_artifact_sha256":ROLLING_SPLIT_SHA256};canonical_bytes(surface);return surface
def project_gap_evaluation(surface:Mapping[str,Any],*,job_execution:Mapping[str,str],subject_executable_id:str,surface_artifact_hash:str,surface_manifest_hash:str)->dict[str,Any]:
    value=dict(surface)
    if sha256(canonical_bytes(value)).hexdigest()!=surface_artifact_hash or value.get("schema")!="gap_recovery_surface.v3":raise DiscoveryBoundaryError("surface invalid")
    expected=executable_configuration_map();by={x.get("subject_executable_id"):x for x in value["evaluations"]}
    if set(by)!=set(expected) or subject_executable_id not in expected:raise DiscoveryBoundaryError("subjects differ")
    payload={n:job_execution[n] for n in ("job_hash","job_id","job_permit_id","start_record_id")}
    if job_execution.get("identity")!=canonical_digest(domain="running-job-execution",payload=payload):raise DiscoveryBoundaryError("Job invalid")
    result={**dict(by[subject_executable_id]),"claim_limits":value["claim_limits"],"job_execution":dict(job_execution),"schema":"gap_recovery_evaluation.v3","selection_context":value["selection_context"],"selection_method":value["selection_method"],"session_semantics":value["session_semantics"],"surface_artifact_hash":surface_artifact_hash,"surface_manifest_hash":surface_manifest_hash};canonical_bytes(result);return result
__all__=["causal_gap_effective_spread","compute_gap_score","compute_registered_gap_surface","executable_configuration_map","gap_configurations","gap_executable","gap_implementation_sha256","loader_implementation_sha256","project_gap_evaluation"]
