"""Registered surface for unconditional versus causal long-trend regime entry."""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any,Mapping
import numpy as np
import pandas as pd
import scipy
from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import DATASET_SHA256,OBSERVED_MATERIAL_ID,ROLLING_SPLIT_SHA256,DiscoveryBoundaryError,_claim_limits,_evaluate_configuration,_fold_payloads,_paired_control_pvalue,_selection_adjusted_pvalues,_selection_method,_time_ns,_validate_engine_environment,_validate_fold_payloads,_validate_production_data,causal_effective_spread
from axiom_rift.research.event_label_discovery import HORIZON,_raw_features,calibrate_selector
from axiom_rift.research.trend_regime_chassis import SELECTION_TOTAL_EXPOSURES,executable_configuration_map,loader_implementation_sha256,simulate_trend_regime,trend_regime_chassis_implementation_sha256,trend_regime_configurations,trend_regime_executable
from axiom_rift.research.volatility_clock_label_chassis import build_labels,fit_label_model
from axiom_rift.research.volatility_clock_label_discovery import deterministic_score

_THIS_FILE=Path(__file__).resolve()
def trend_regime_discovery_implementation_sha256()->str:return sha256(_THIS_FILE.read_bytes()).hexdigest()
def _matched(results:list[Any],policy:str)->Any:
    found=[v for v in results if v.configuration.regime_policy==policy]
    if len(found)!=1:raise DiscoveryBoundaryError("trend regime control is not unique")
    return found[0]
def _populate_controls(results:list[Any])->None:
    control=_matched(results,"unconditional_long_control")
    for subject in results:
        subject.metrics["regime_control_delta_net_profit_micropoints"]=subject.metrics["net_profit_micropoints"]-control.metrics["net_profit_micropoints"]
        subject.metrics["regime_control_pvalue_upper_ppm"]=1_000_000 if subject is control else _paired_control_pvalue(subject,control,role="matched_unconditional_long_control",total_exposures=SELECTION_TOTAL_EXPOSURES)
def compute_registered_trend_regime_surface(repository_root:str|Path)->dict[str,Any]:
    _validate_engine_environment();data=load_observed_development(Path(repository_root).resolve());_validate_production_data(data)
    folds=_fold_payloads(data);_validate_fold_payloads(data.frame,folds);frame=data.frame;time=pd.to_datetime(frame["time"],errors="raise")
    spread=causal_effective_spread(frame["spread"].to_numpy(float),_time_ns(frame));full_features,full_volatility,full_run=_raw_features(frame)
    label=build_labels(frame,full_volatility,full_run)["volatility_clock_terminal_12_of_48"]
    prefix_frames={};prefix_raw={};prefix_spreads={}
    for fold in folds:
        fid=str(fold["fold_id"]);end=int(time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]),side="right"));prefix=frame.iloc[:end]
        prefix_frames[fid]=prefix;prefix_raw[fid]=_raw_features(prefix);prefix_spreads[fid]=causal_effective_spread(prefix["spread"].to_numpy(float),_time_ns(prefix))
    fold_scores={};prefix_scores={};calibrations={}
    for fold in folds:
        fid=str(fold["fold_id"]);train=fold["train_is"];start,end=pd.Timestamp(train["start"]),pd.Timestamp(train["end"])
        selector_mask=((time>=start)&(time<=end)).to_numpy();future_time=time.shift(-(HORIZON+1));train_mask=selector_mask&(future_time<=end).fillna(False).to_numpy()
        model=fit_label_model(features=full_features,label=label,train_mask=train_mask);score=deterministic_score(full_features,model);fold_scores[fid]=(score,full_volatility,full_run)
        raw=prefix_raw[fid];prefix_score=deterministic_score(raw[0],model);prefix_scores[fid]=(prefix_score,raw[1],raw[2]);prefix_time=pd.to_datetime(prefix_frames[fid]["time"],errors="raise");prefix_train=((prefix_time>=start)&(prefix_time<=end)).to_numpy()
        values=full_volatility[train_mask&np.isfinite(full_volatility)];cutoffs=(float(np.quantile(values,1/3,method="higher")),float(np.quantile(values,2/3,method="higher")))
        calibrations[fid]=(calibrate_selector(score,selector_mask),cutoffs,calibrate_selector(prefix_score,prefix_train))
    first=fold_scores[str(folds[0]["fold_id"])]
    results=[_evaluate_configuration(calibrations=calibrations,frame=frame,features=first,fold_features=fold_scores,folds=folds,configuration=c,effective_spread=spread,prefix_features=prefix_scores,prefix_spreads=prefix_spreads,time=time,executable_id=trend_regime_executable(c).identity,simulation_fn=simulate_trend_regime) for c in trend_regime_configurations()]
    adjusted=_selection_adjusted_pvalues(results,total_exposures=SELECTION_TOTAL_EXPOSURES)
    for result in results:result.metrics["selection_aware_pvalue_ppm"]=adjusted[result.executable_id]
    _populate_controls(results)
    surface={"claim_limits":_claim_limits()+["regime_is_the_only_primary_changed_research_layer","long_only_signal_model_label_lifecycle_risk_and_execution_are_fixed","trend_gate_is_completed_bar_point_in_time","two_trial_surface"],"dataset_sha256":DATASET_SHA256,"engine_environment":{"numpy":np.__version__,"pandas":pd.__version__,"python":".".join(str(v) for v in sys.version_info[:3]),"scipy":scipy.__version__},"evaluations":[{"direction_metrics":r.direction_metrics,"evaluable":all(r.metrics[n]==0 for n in ("unknown_cost_unresolved_signal_count","causality_violation_count","nonfinite_metric_count","prefix_invariance_mismatch_count","append_invariance_mismatch_count")),"fold_metrics":r.fold_metrics,"metrics":dict(sorted(r.metrics.items())),"regime_metrics":r.regime_metrics,"session_metrics":r.session_metrics,"subject_configuration_id":r.configuration.configuration_id,"subject_executable_id":r.executable_id} for r in results],"loader_implementation_sha256":loader_implementation_sha256(),"material_identity":OBSERVED_MATERIAL_ID,"schema":"trend_regime_evaluation_surface.v1","selection_context":[{"configuration_id":r.configuration.configuration_id,"executable_id":r.executable_id,"net_profit_micropoints":r.metrics["net_profit_micropoints"],"selection_aware_pvalue_ppm":r.metrics["selection_aware_pvalue_ppm"]} for r in results],"selection_method":_selection_method(SELECTION_TOTAL_EXPOSURES),"session_semantics":"broker_clock_fixed_bins_no_dst_or_cash_session_claim","split_artifact_sha256":ROLLING_SPLIT_SHA256,"trend_regime_chassis_implementation_sha256":trend_regime_chassis_implementation_sha256(),"trend_regime_discovery_implementation_sha256":trend_regime_discovery_implementation_sha256()}
    canonical_bytes(surface);return surface
def project_trend_regime_evaluation(surface:Mapping[str,Any],*,job_execution:Mapping[str,str],subject_executable_id:str,surface_artifact_hash:str,surface_manifest_hash:str)->dict[str,Any]:
    value=dict(surface)
    if sha256(canonical_bytes(value)).hexdigest()!=surface_artifact_hash or value.get("schema")!="trend_regime_evaluation_surface.v1":raise DiscoveryBoundaryError("trend regime surface invalid")
    expected=executable_configuration_map();by={v.get("subject_executable_id"):v for v in value["evaluations"]}
    if set(by)!=set(expected) or subject_executable_id not in expected:raise DiscoveryBoundaryError("trend regime subjects differ")
    payload={n:job_execution[n] for n in ("job_hash","job_id","job_permit_id","start_record_id")}
    if job_execution.get("identity")!=canonical_digest(domain="running-job-execution",payload=payload):raise DiscoveryBoundaryError("trend regime Job invalid")
    result={**dict(by[subject_executable_id]),"claim_limits":value["claim_limits"],"job_execution":dict(job_execution),"schema":"trend_regime_evaluation.v1","selection_context":value["selection_context"],"selection_method":value["selection_method"],"session_semantics":value["session_semantics"],"surface_artifact_hash":surface_artifact_hash,"surface_manifest_hash":surface_manifest_hash};canonical_bytes(result);return result
__all__=["compute_registered_trend_regime_surface","project_trend_regime_evaluation","trend_regime_discovery_implementation_sha256"]
