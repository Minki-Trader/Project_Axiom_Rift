"""Registered positive US100 direction sleeve portfolio surface."""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
from typing import Any,Mapping
import numpy as np
import pandas as pd
from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.dense_short_synthesis_chassis import calibrate_synthesis_selector,terminal_return_sign_12
from axiom_rift.research.discovery import DATASET_SHA256,OBSERVED_MATERIAL_ID,ROLLING_SPLIT_SHA256,DiscoveryBoundaryError,_claim_limits,_evaluate_configuration,_fold_payloads,_paired_control_pvalue,_selection_adjusted_pvalues,_selection_method,_time_ns,_validate_engine_environment,_validate_fold_payloads,_validate_production_data,causal_effective_spread
from axiom_rift.research.event_label_discovery import _raw_features
from axiom_rift.research.positive_direction_sleeve_chassis import SELECTION_TOTAL_EXPOSURES,executable_configuration_map,loader_implementation_sha256,positive_direction_sleeve_chassis_implementation_sha256,positive_direction_sleeve_configurations,positive_direction_sleeve_executable,simulate_positive_direction_sleeves
from axiom_rift.research.volatility_clock_label_chassis import fit_label_model
from axiom_rift.research.volatility_clock_label_discovery import deterministic_score

_THIS_FILE=Path(__file__).resolve()
def positive_direction_sleeve_discovery_implementation_sha256()->str:return sha256(_THIS_FILE.read_bytes()).hexdigest()
def target_direction_score(frame:pd.DataFrame,run:np.ndarray)->np.ndarray:
    close=frame["close"].to_numpy(float);log=np.log(close);one=np.full(len(close),np.nan);one[1:]=np.diff(log);rv=pd.Series(one).rolling(48,min_periods=48).std(ddof=1).to_numpy(float);score=np.full(len(close),np.nan);score[12:]=(log[12:]-log[:-12])/(rv[12:]*np.sqrt(12));score[np.asarray(run)<49]=np.nan;return score
def _threshold(score:np.ndarray,mask:np.ndarray)->float:
    values=np.abs(score[mask&np.isfinite(score)])
    if len(values)<1000:raise DiscoveryBoundaryError("positive direction selector is too small")
    return float(np.quantile(values,.975,method="higher"))
def _matrix(router_raw:np.ndarray,target_raw:np.ndarray,vol:np.ndarray,router_threshold:float,target_threshold:float,cuts:tuple[float,float])->np.ndarray:
    router=np.zeros(len(router_raw));selected=np.isfinite(router_raw)&(router_raw>0);high=np.isfinite(vol)&(vol>=cuts[1]);router[selected&high]=np.abs(router_raw[selected&high])/router_threshold;router[selected&~high]=-np.abs(router_raw[selected&~high])/router_threshold
    target=np.divide(target_raw,target_threshold,out=np.full(len(target_raw),np.nan),where=np.isfinite(target_raw));return np.column_stack((router,target))
def _matched(results:list[Any],profile:str)->Any:
    found=[v for v in results if v.configuration.portfolio_profile==profile]
    if len(found)!=1:raise DiscoveryBoundaryError("positive direction control is not unique")
    return found[0]
def _populate(results:list[Any])->None:
    control=_matched(results,"router_control")
    for subject in results:
        subject.metrics["router_control_delta_net_profit_micropoints"]=subject.metrics["net_profit_micropoints"]-control.metrics["net_profit_micropoints"]
        subject.metrics["router_control_pvalue_upper_ppm"]=1_000_000 if subject is control else _paired_control_pvalue(subject,control,role="router_control",total_exposures=SELECTION_TOTAL_EXPOSURES)
def compute_registered_positive_direction_sleeve_surface(repository_root:str|Path)->dict[str,Any]:
    _validate_engine_environment();data=load_observed_development(Path(repository_root).resolve());_validate_production_data(data);folds=_fold_payloads(data);_validate_fold_payloads(data.frame,folds);frame=data.frame;time=pd.to_datetime(frame["time"],errors="raise");spread=causal_effective_spread(frame["spread"].to_numpy(float),_time_ns(frame));features,vol,run=_raw_features(frame);label=terminal_return_sign_12(frame,run);target=target_direction_score(frame,run)
    prefix_frames={};prefix_raw={};prefix_spreads={}
    for fold in folds:
        fid=str(fold["fold_id"]);end=int(time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]),side="right"));pf=frame.iloc[:end];prefix_frames[fid]=pf;prefix_raw[fid]=_raw_features(pf);prefix_spreads[fid]=causal_effective_spread(pf["spread"].to_numpy(float),_time_ns(pf))
    fold_scores={};prefix_scores={};calibrations={}
    for fold in folds:
        fid=str(fold["fold_id"]);start,end=pd.Timestamp(fold["train_is"]["start"]),pd.Timestamp(fold["train_is"]["end"]);mask=((time>=start)&(time<=end)).to_numpy();train=mask&(time.shift(-13)<=end).fillna(False).to_numpy();model=fit_label_model(features=features,label=label,train_mask=train);router_raw=deterministic_score(features,model);rt=calibrate_synthesis_selector(router_raw,mask,7000);tt=_threshold(target,mask);values=vol[train&np.isfinite(vol)];cuts=(float(np.quantile(values,1/3,method="higher")),float(np.quantile(values,2/3,method="higher")));fold_scores[fid]=(_matrix(router_raw,target,vol,rt,tt,cuts),vol,run)
        pf=prefix_frames[fid];pr=prefix_raw[fid];ptime=pd.to_datetime(pf["time"],errors="raise");pmask=((ptime>=start)&(ptime<=end)).to_numpy();prouter=deterministic_score(pr[0],model);ptarget=target_direction_score(pf,pr[2]);prt=calibrate_synthesis_selector(prouter,pmask,7000);ptt=_threshold(ptarget,pmask)
        if rt!=prt or tt!=ptt:raise DiscoveryBoundaryError("positive direction threshold drifted")
        prefix_scores[fid]=(_matrix(prouter,ptarget,pr[1],prt,ptt,cuts),pr[1],pr[2]);calibrations[fid]=(1.0,cuts,1.0)
    first=fold_scores[str(folds[0]["fold_id"])]
    results=[_evaluate_configuration(calibrations=calibrations,frame=frame,features=first,fold_features=fold_scores,folds=folds,configuration=c,effective_spread=spread,prefix_features=prefix_scores,prefix_spreads=prefix_spreads,time=time,executable_id=positive_direction_sleeve_executable(c).identity,simulation_fn=simulate_positive_direction_sleeves) for c in positive_direction_sleeve_configurations()]
    adjusted=_selection_adjusted_pvalues(results,total_exposures=SELECTION_TOTAL_EXPOSURES)
    for result in results:result.metrics["selection_aware_pvalue_ppm"]=adjusted[result.executable_id]
    _populate(results)
    surface={"claim_limits":_claim_limits()+["portfolio_and_risk_are_the_primary_changed_layers","both_sleeves_are_US100_completed_bar_only","each_sleeve_uses_one_fixed_lot","two_trial_surface"],"dataset_sha256":DATASET_SHA256,"evaluations":[{"direction_metrics":r.direction_metrics,"evaluable":all(r.metrics[n]==0 for n in ("unknown_cost_unresolved_signal_count","causality_violation_count","nonfinite_metric_count","prefix_invariance_mismatch_count","append_invariance_mismatch_count")),"fold_metrics":r.fold_metrics,"metrics":dict(sorted(r.metrics.items())),"regime_metrics":r.regime_metrics,"session_metrics":r.session_metrics,"subject_configuration_id":r.configuration.configuration_id,"subject_executable_id":r.executable_id} for r in results],"loader_implementation_sha256":loader_implementation_sha256(),"material_identity":OBSERVED_MATERIAL_ID,"positive_direction_sleeve_chassis_implementation_sha256":positive_direction_sleeve_chassis_implementation_sha256(),"positive_direction_sleeve_discovery_implementation_sha256":positive_direction_sleeve_discovery_implementation_sha256(),"schema":"positive_direction_sleeve_surface.v1","selection_context":[{"configuration_id":r.configuration.configuration_id,"executable_id":r.executable_id,"net_profit_micropoints":r.metrics["net_profit_micropoints"],"selection_aware_pvalue_ppm":r.metrics["selection_aware_pvalue_ppm"]} for r in results],"selection_method":_selection_method(SELECTION_TOTAL_EXPOSURES),"session_semantics":"broker_clock_fixed_bins_no_dst_or_cash_session_claim","split_artifact_sha256":ROLLING_SPLIT_SHA256};canonical_bytes(surface);return surface
def project_positive_direction_sleeve_evaluation(surface:Mapping[str,Any],*,job_execution:Mapping[str,str],subject_executable_id:str,surface_artifact_hash:str,surface_manifest_hash:str)->dict[str,Any]:
    value=dict(surface)
    if sha256(canonical_bytes(value)).hexdigest()!=surface_artifact_hash or value.get("schema")!="positive_direction_sleeve_surface.v1":raise DiscoveryBoundaryError("positive direction sleeve surface invalid")
    expected=executable_configuration_map();by={v.get("subject_executable_id"):v for v in value["evaluations"]}
    if set(by)!=set(expected) or subject_executable_id not in expected:raise DiscoveryBoundaryError("positive direction sleeve subjects differ")
    payload={n:job_execution[n] for n in ("job_hash","job_id","job_permit_id","start_record_id")}
    if job_execution.get("identity")!=canonical_digest(domain="running-job-execution",payload=payload):raise DiscoveryBoundaryError("positive direction sleeve Job invalid")
    result={**dict(by[subject_executable_id]),"claim_limits":value["claim_limits"],"job_execution":dict(job_execution),"schema":"positive_direction_sleeve_evaluation.v1","selection_context":value["selection_context"],"selection_method":value["selection_method"],"session_semantics":value["session_semantics"],"surface_artifact_hash":surface_artifact_hash,"surface_manifest_hash":surface_manifest_hash};canonical_bytes(result);return result
__all__=["compute_registered_positive_direction_sleeve_surface","positive_direction_sleeve_discovery_implementation_sha256","project_positive_direction_sleeve_evaluation","target_direction_score"]
