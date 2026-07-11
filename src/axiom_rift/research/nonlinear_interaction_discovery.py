"""Bounded shock and path nonlinear interaction discovery."""
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
from axiom_rift.research.discovery import DATASET_SHA256,OBSERVED_MATERIAL_ID,ROLLING_SPLIT_SHA256,SELECTION_BLOCK_LENGTHS,SELECTION_BOOTSTRAP_SAMPLES,SELECTION_MONTE_CARLO_CONFIDENCE_PPM,SELECTION_SEED,DiscoveryBoundaryError,_claim_limits,_evaluate_configuration,_fold_payloads,_paired_control_pvalue,_selection_adjusted_pvalues,_selection_method,_time_ns,_validate_engine_environment,_validate_fold_payloads,_validate_production_data,causal_effective_spread,discovery_implementation_sha256
from axiom_rift.research.path_efficiency_discovery import compute_path_score
from axiom_rift.research.shock_aftereffect_discovery import compute_shock_score
SELECTION_TOTAL_EXPOSURES=330;SELECTOR_QUANTILE_BP=9_000;_PROFILES=("product","conjunction","additive");_THIS_FILE=Path(__file__).resolve()
def nonlinear_implementation_sha256()->str:return sha256(_THIS_FILE.read_bytes()).hexdigest()
def loader_implementation_sha256()->str:return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()
@dataclass(frozen=True,slots=True)
class NonlinearConfiguration:
    profile:str;signal_sign:int;holding_bars:int
    def __post_init__(self)->None:
        if self.profile not in _PROFILES or self.signal_sign not in {-1,1} or self.holding_bars not in {3,12}:raise ValueError("nonlinear configuration is not registered")
    @property
    def configuration_id(self)->str:return f"{self.profile}-{'continuation' if self.signal_sign==1 else 'reversal'}-h{self.holding_bars}"
    def semantic_parameters(self)->dict[str,Any]:return {"efficiency_lookback":48,"holding_bars":self.holding_bars,"profile":self.profile,"selector_quantile_bp":SELECTOR_QUANTILE_BP,"signal_sign":self.signal_sign,"shock_volatility_window":48}
def nonlinear_configurations()->tuple[NonlinearConfiguration,...]:return tuple(NonlinearConfiguration(profile=p,signal_sign=s,holding_bars=h) for p in _PROFILES for s in (1,-1) for h in (3,12))
def _local(n:str)->str:return f"axiom_rift.research.nonlinear_interaction_discovery.{n}@sha256:{nonlinear_implementation_sha256()}"
def _shared(n:str)->str:return f"axiom_rift.research.discovery.{n}@sha256:{discovery_implementation_sha256()}"
def nonlinear_components()->tuple[ComponentSpec,...]:return (ComponentSpec(display_name="bounded shock path interaction",protocol="feature.shock_path_interaction.v1",implementation=_local("compute_nonlinear_score"),spec={"availability":"completed_bar_only","constituents":["lagged_volatility_shock","signed_efficiency_48"],"profiles":["product","conjunction","additive"],"conjunction_abs_efficiency_floor":"0.5","parameter_fields":["profile"]}),ComponentSpec(display_name="fold isolated interaction selector",protocol="selector.fold_train_abs_quantile.v2",implementation=_local("calibrate_nonlinear_selector"),spec={"calibration_role":"train_is_only","minimum_train_observations":1000,"quantile_basis_points":SELECTOR_QUANTILE_BP,"quantile_method":"higher"}),ComponentSpec(display_name="completed-bar next-open directional entry",protocol="trade.completed_bar_next_open_direction.v2",implementation=_shared("simulate_fixed_hold"),spec={"decision_time":"bar_open_plus_5m","entry_time":"next_exact_bar_open","direction":"signal_sign_times_interaction_sign","parameter_fields":["signal_sign"]}),ComponentSpec(display_name="fixed-hold nonoverlap lifecycle",protocol="lifecycle.fixed_hold_no_overlap.v2",implementation=_shared("simulate_fixed_hold"),spec={"entry_overlap":"reject_while_position_slot_is_occupied","exit_surface":"exact_bar_open_after_holding_bars","gap_action":"exclude_path","parameter_fields":["holding_bars"]}),ComponentSpec(display_name="FPMarkets bid-bar spread execution",protocol="execution.fpmarkets_bid_bar_spread.v2",implementation=_shared("execution_pnl"),spec={"bar_quote_basis":"bid_ohlc_with_spread_points","point":"0.01","stress":"half_effective_spread_each_side","zero_spread_action":"causal_lagged_positive_median"}),ComponentSpec(display_name="fixed one-lot single-sleeve risk",protocol="risk.fixed_one_lot.v1",implementation=_shared("simulate_fixed_hold"),spec={"dynamic_sizing":False,"lot":1,"positions_per_sleeve":1}))
def nonlinear_executable(c:NonlinearConfiguration)->ExecutableSpec:return ExecutableSpec(display_name=f"nonlinear interaction {c.configuration_id}",components=nonlinear_components(),parameters=c.semantic_parameters(),data_contract=f"data:{OBSERVED_MATERIAL_ID}",split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v2",cost_contract="cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v2",engine_contract=f"engine:nonlinear_interaction_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:implementation_{nonlinear_implementation_sha256()}:loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:mc_upper_{SELECTION_MONTE_CARLO_CONFIDENCE_PPM}:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}")
def executable_configuration_map()->dict[str,NonlinearConfiguration]:return {nonlinear_executable(c).identity:c for c in nonlinear_configurations()}
def compute_nonlinear_score(frame:pd.DataFrame,profile:str)->tuple[np.ndarray,np.ndarray,np.ndarray]:
    if profile not in _PROFILES:raise ValueError("nonlinear profile is not registered")
    shock,vol,run=compute_shock_score(frame,"symmetric");eff,_,_=compute_path_score(frame,feature_kind="efficiency",lookback=48)
    if profile=="product":score=shock*np.abs(eff)
    elif profile=="conjunction":score=np.where((np.sign(shock)==np.sign(eff))&(np.abs(eff)>=0.5),shock,0.0)
    else:score=0.5*np.tanh(shock/3.0)+0.5*eff
    score[~np.isfinite(shock)|~np.isfinite(eff)]=np.nan;return score,vol,run
def calibrate_nonlinear_selector(score:np.ndarray,mask:np.ndarray)->float:
    v=np.abs(score[mask&np.isfinite(score)])
    if len(v)<1000:raise DiscoveryBoundaryError("nonlinear selector is too small")
    return float(np.quantile(v,SELECTOR_QUANTILE_BP/10000,method="higher"))
def _matched(results:list[Any],profile:str,sign:int,holding:int)->Any:
    found=[r for r in results if r.configuration.profile==profile and r.configuration.signal_sign==sign and r.configuration.holding_bars==holding]
    if len(found)!=1:raise DiscoveryBoundaryError("nonlinear control is not unique")
    return found[0]
def _populate_controls(results:list[Any])->None:
    for subject in results:
        opposite=_matched(results,subject.configuration.profile,-subject.configuration.signal_sign,subject.configuration.holding_bars);controls=[_matched(results,p,subject.configuration.signal_sign,subject.configuration.holding_bars) for p in _PROFILES if p!=subject.configuration.profile];subject.metrics["opposite_sign_worst_delta_net_profit_micropoints"]=subject.metrics["net_profit_micropoints"]-opposite.metrics["net_profit_micropoints"];subject.metrics["opposite_sign_pvalue_upper_ppm"]=_paired_control_pvalue(subject,opposite,role="opposite_sign",total_exposures=SELECTION_TOTAL_EXPOSURES);subject.metrics["feature_control_worst_delta_net_profit_micropoints"]=min(subject.metrics["net_profit_micropoints"]-c.metrics["net_profit_micropoints"] for c in controls);subject.metrics["feature_control_worst_pvalue_upper_ppm"]=max(_paired_control_pvalue(subject,c,role="interaction_profile",total_exposures=SELECTION_TOTAL_EXPOSURES) for c in controls)
def compute_registered_nonlinear_surface(repository_root:str|Path)->dict[str,Any]:
    _validate_engine_environment();data=load_observed_development(Path(repository_root).resolve());_validate_production_data(data);folds=_fold_payloads(data);_validate_fold_payloads(data.frame,folds);frame=data.frame;time=pd.to_datetime(frame["time"],errors="raise");spread=causal_effective_spread(frame["spread"].to_numpy(dtype=float),_time_ns(frame));prefix_frames={};prefix_spreads={}
    for fold in folds:
        fid=str(fold["fold_id"]);end=int(time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]),side="right"));prefix_frames[fid]=frame.iloc[:end];prefix_spreads[fid]=causal_effective_spread(prefix_frames[fid]["spread"].to_numpy(dtype=float),_time_ns(prefix_frames[fid]))
    features={};prefixes={};calibrations={}
    for profile in _PROFILES:
        value=compute_nonlinear_score(frame,profile);features[profile]=value;prefixes[profile]={};calibrations[profile]={}
        for fold in folds:
            fid=str(fold["fold_id"]);train=fold["train_is"];mask=((time>=pd.Timestamp(train["start"]))&(time<=pd.Timestamp(train["end"]))).to_numpy();threshold=calibrate_nonlinear_selector(value[0],mask);vv=value[1][mask&np.isfinite(value[1])];cutoffs=(float(np.quantile(vv,1/3,method="higher")),float(np.quantile(vv,2/3,method="higher")));pv=compute_nonlinear_score(prefix_frames[fid],profile);prefixes[profile][fid]=pv;pt=pd.to_datetime(prefix_frames[fid]["time"],errors="raise");pm=((pt>=pd.Timestamp(train["start"]))&(pt<=pd.Timestamp(train["end"]))).to_numpy();calibrations[profile][fid]=(threshold,cutoffs,calibrate_nonlinear_selector(pv[0],pm))
    results=[_evaluate_configuration(calibrations=calibrations[c.profile],frame=frame,features=features[c.profile],folds=folds,configuration=c,effective_spread=spread,prefix_features=prefixes[c.profile],prefix_spreads=prefix_spreads,time=time,executable_id=nonlinear_executable(c).identity) for c in nonlinear_configurations()];pvalues=_selection_adjusted_pvalues(results,total_exposures=SELECTION_TOTAL_EXPOSURES)
    for r in results:r.metrics["selection_aware_pvalue_ppm"]=pvalues[r.executable_id]
    _populate_controls(results);surface={"claim_limits":_claim_limits()+["interaction_is_bounded_and_preregistered","additive_control_is_in_same_batch"],"dataset_sha256":DATASET_SHA256,"engine_environment":{"numpy":np.__version__,"pandas":pd.__version__,"python":".".join(str(v) for v in sys.version_info[:3]),"scipy":scipy.__version__},"evaluations":[{"direction_metrics":r.direction_metrics,"evaluable":all(r.metrics[n]==0 for n in ("unknown_cost_unresolved_signal_count","causality_violation_count","nonfinite_metric_count","prefix_invariance_mismatch_count","append_invariance_mismatch_count")),"fold_metrics":r.fold_metrics,"metrics":dict(sorted(r.metrics.items())),"regime_metrics":r.regime_metrics,"session_metrics":r.session_metrics,"subject_configuration_id":r.configuration.configuration_id,"subject_executable_id":r.executable_id} for r in results],"loader_implementation_sha256":loader_implementation_sha256(),"material_identity":OBSERVED_MATERIAL_ID,"nonlinear_implementation_sha256":nonlinear_implementation_sha256(),"schema":"nonlinear_interaction_surface.v1","selection_context":[{"configuration_id":r.configuration.configuration_id,"executable_id":r.executable_id,"net_profit_micropoints":r.metrics["net_profit_micropoints"],"selection_aware_pvalue_ppm":r.metrics["selection_aware_pvalue_ppm"]} for r in results],"selection_method":_selection_method(SELECTION_TOTAL_EXPOSURES),"session_semantics":"broker_clock_fixed_bins_no_dst_or_cash_session_claim","split_artifact_sha256":ROLLING_SPLIT_SHA256};canonical_bytes(surface);return surface
def project_nonlinear_evaluation(surface:Mapping[str,Any],*,job_execution:Mapping[str,str],subject_executable_id:str,surface_artifact_hash:str,surface_manifest_hash:str)->dict[str,Any]:
    value=dict(surface)
    if sha256(canonical_bytes(value)).hexdigest()!=surface_artifact_hash or value.get("schema")!="nonlinear_interaction_surface.v1":raise DiscoveryBoundaryError("nonlinear surface is invalid")
    expected=executable_configuration_map();evaluations=value.get("evaluations");by={item.get("subject_executable_id"):item for item in evaluations if isinstance(item,Mapping)} if isinstance(evaluations,list) else {}
    if set(by)!=set(expected) or subject_executable_id not in expected:raise DiscoveryBoundaryError("nonlinear subjects differ")
    payload={n:job_execution[n] for n in ("job_hash","job_id","job_permit_id","start_record_id")}
    if job_execution.get("identity")!=canonical_digest(domain="running-job-execution",payload=payload):raise DiscoveryBoundaryError("nonlinear Job identity is invalid")
    result={**dict(by[subject_executable_id]),"claim_limits":value["claim_limits"],"job_execution":dict(job_execution),"schema":"nonlinear_interaction_evaluation.v1","selection_context":value["selection_context"],"selection_method":value["selection_method"],"session_semantics":value["session_semantics"],"surface_artifact_hash":surface_artifact_hash,"surface_manifest_hash":surface_manifest_hash};canonical_bytes(result);return result
__all__=["compute_nonlinear_score","compute_registered_nonlinear_surface","executable_configuration_map","loader_implementation_sha256","nonlinear_configurations","nonlinear_executable","nonlinear_implementation_sha256","project_nonlinear_evaluation"]
