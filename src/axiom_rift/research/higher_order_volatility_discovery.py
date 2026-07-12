"""Causal volatility-of-volatility directional discovery."""
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
SELECTION_TOTAL_EXPOSURES=484;SELECTOR_QUANTILE_BP=8_500;VOL_WINDOW=48;VOV_WINDOW=24;BASELINE_WINDOW=576;HORIZON=24;_PROFILES=("signed_vol_of_vol_24_576","signed_vol_level_control_48_576");_THIS_FILE=Path(__file__).resolve()
def higher_volatility_implementation_sha256()->str:return sha256(_THIS_FILE.read_bytes()).hexdigest()
def loader_implementation_sha256()->str:return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()
@dataclass(frozen=True,slots=True)
class HigherVolatilityConfiguration:
    profile:str;signal_sign:int;holding_bars:int=HORIZON
    def __post_init__(self)->None:
        if self.profile not in _PROFILES or self.signal_sign not in {-1,1} or self.holding_bars!=HORIZON:raise ValueError("higher-volatility configuration invalid")
    @property
    def configuration_id(self)->str:return f"{self.profile}-{'continue' if self.signal_sign==1 else 'reverse'}-h{HORIZON}"
    def semantic_parameters(self)->dict[str,Any]:return {"baseline_window":BASELINE_WINDOW,"holding_bars":HORIZON,"profile":self.profile,"selector_quantile_bp":SELECTOR_QUANTILE_BP,"signal_sign":self.signal_sign,"volatility_window":VOL_WINDOW,"volatility_of_volatility_window":VOV_WINDOW}
def higher_volatility_configurations()->tuple[HigherVolatilityConfiguration,...]:return tuple(HigherVolatilityConfiguration(profile=p,signal_sign=s) for p in _PROFILES for s in (1,-1))
def _local(n:str)->str:return f"axiom_rift.research.higher_order_volatility_discovery.{n}@sha256:{higher_volatility_implementation_sha256()}"
def _shared(n:str)->str:return f"axiom_rift.research.discovery.{n}@sha256:{discovery_implementation_sha256()}"
def higher_volatility_components()->tuple[ComponentSpec,...]:return (ComponentSpec(display_name="causal volatility-of-volatility state",protocol="feature.causal_volatility_of_volatility.v1",implementation=_local("compute_higher_volatility_score"),spec={"availability":"completed_bar_only","baseline_window":BASELINE_WINDOW,"direction_context_bars":12,"profiles":list(_PROFILES),"volatility_window":VOL_WINDOW,"volatility_of_volatility_window":VOV_WINDOW,"parameter_fields":["profile"]}),ComponentSpec(display_name="fold isolated higher-volatility selector",protocol="selector.fold_train_abs_quantile.v2",implementation=_local("calibrate_selector"),spec={"calibration_role":"train_is_only","minimum_train_observations":1000,"quantile_basis_points":SELECTOR_QUANTILE_BP,"quantile_method":"higher"}),ComponentSpec(display_name="completed-bar next-open directional entry",protocol="trade.completed_bar_next_open_direction.v2",implementation=_shared("simulate_fixed_hold"),spec={"decision_time":"bar_open_plus_5m","entry_time":"next_exact_bar_open","direction":"signal_sign_times_score_sign","parameter_fields":["signal_sign"]}),ComponentSpec(display_name="fixed-hold nonoverlap lifecycle",protocol="lifecycle.fixed_hold_no_overlap.v2",implementation=_shared("simulate_fixed_hold"),spec={"entry_overlap":"reject_while_position_slot_is_occupied","exit_surface":"exact_bar_open_after_24_bars","gap_action":"exclude_path"}),ComponentSpec(display_name="FPMarkets bid-bar spread execution",protocol="execution.fpmarkets_bid_bar_spread.v2",implementation=_shared("execution_pnl"),spec={"point":"0.01","stress":"half_effective_spread_each_side"}),ComponentSpec(display_name="fixed one-lot risk",protocol="risk.fixed_one_lot.v1",implementation=_shared("simulate_fixed_hold"),spec={"dynamic_sizing":False,"lot":1,"positions_per_sleeve":1}))
def higher_volatility_executable(c:HigherVolatilityConfiguration)->ExecutableSpec:return ExecutableSpec(display_name=f"higher volatility {c.configuration_id}",components=higher_volatility_components(),parameters=c.semantic_parameters(),data_contract=f"data:{OBSERVED_MATERIAL_ID}",split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v2",cost_contract="cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v2",engine_contract=f"engine:higher_order_volatility_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:implementation_{higher_volatility_implementation_sha256()}:loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}")
def executable_configuration_map()->dict[str,HigherVolatilityConfiguration]:return {higher_volatility_executable(c).identity:c for c in higher_volatility_configurations()}
def compute_higher_volatility_score(frame:pd.DataFrame,profile:str)->tuple[np.ndarray,np.ndarray,np.ndarray]:
    if profile not in _PROFILES:raise ValueError("higher-volatility profile invalid")
    close=frame["close"].to_numpy(float);log=np.log(close);ret=np.full(len(close),np.nan);ret[1:]=np.diff(log);series=pd.Series(ret);vol=series.rolling(VOL_WINDOW,min_periods=VOL_WINDOW).std(ddof=1).to_numpy(float);logvol=np.log(vol);vol_change=np.full(len(close),np.nan);vol_change[1:]=np.diff(logvol);vov=pd.Series(vol_change).rolling(VOV_WINDOW,min_periods=VOV_WINDOW).std(ddof=1).to_numpy(float);baseline_vov=pd.Series(vov).shift(1).rolling(BASELINE_WINDOW,min_periods=BASELINE_WINDOW).median().to_numpy(float);baseline_vol=pd.Series(vol).shift(1).rolling(BASELINE_WINDOW,min_periods=BASELINE_WINDOW).median().to_numpy(float);direction=np.full(len(close),np.nan);direction[12:]=np.sign(log[12:]-log[:-12])
    if profile=="signed_vol_of_vol_24_576":raw=np.divide(vov,baseline_vov,out=np.full(len(close),np.nan),where=np.isfinite(baseline_vov)&(baseline_vov>0))-1.0
    else:raw=np.divide(vol,baseline_vol,out=np.full(len(close),np.nan),where=np.isfinite(baseline_vol)&(baseline_vol>0))-1.0
    score=raw*direction;run=_consecutive_run(_time_ns(frame));score[run<97]=np.nan;return score,vol,run
def calibrate_selector(score:np.ndarray,mask:np.ndarray)->float:
    v=np.abs(score[mask&np.isfinite(score)])
    if len(v)<1000:raise DiscoveryBoundaryError("higher-volatility selector too small")
    return float(np.quantile(v,SELECTOR_QUANTILE_BP/10000,method="higher"))
def _matched(results:list[Any],profile:str,sign:int)->Any:
    found=[r for r in results if r.configuration.profile==profile and r.configuration.signal_sign==sign]
    if len(found)!=1:raise DiscoveryBoundaryError("higher-volatility control not unique")
    return found[0]
def _populate(results:list[Any])->None:
    for s in results:
        c=s.configuration;o=_matched(results,c.profile,-c.signal_sign);k=_matched(results,next(p for p in _PROFILES if p!=c.profile),c.signal_sign);s.metrics["opposite_sign_worst_delta_net_profit_micropoints"]=s.metrics["net_profit_micropoints"]-o.metrics["net_profit_micropoints"];s.metrics["opposite_sign_pvalue_upper_ppm"]=_paired_control_pvalue(s,o,role="opposite_sign",total_exposures=SELECTION_TOTAL_EXPOSURES);s.metrics["feature_control_worst_delta_net_profit_micropoints"]=s.metrics["net_profit_micropoints"]-k.metrics["net_profit_micropoints"];s.metrics["feature_control_worst_pvalue_upper_ppm"]=_paired_control_pvalue(s,k,role="volatility_level_control",total_exposures=SELECTION_TOTAL_EXPOSURES)
def compute_registered_higher_volatility_surface(repository_root:str|Path)->dict[str,Any]:
    _validate_engine_environment();data=load_observed_development(Path(repository_root).resolve());_validate_production_data(data);folds=_fold_payloads(data);_validate_fold_payloads(data.frame,folds);frame=data.frame;time=pd.to_datetime(frame["time"],errors="raise");spread=causal_effective_spread(frame["spread"].to_numpy(float),_time_ns(frame));prefix_frames={};prefix_spreads={}
    for f in folds:
        fid=str(f["fold_id"]);end=int(time.searchsorted(pd.Timestamp(f["test_oos"]["end"]),side="right"));prefix_frames[fid]=frame.iloc[:end];prefix_spreads[fid]=causal_effective_spread(prefix_frames[fid]["spread"].to_numpy(float),_time_ns(prefix_frames[fid]))
    features={};prefixes={};calibrations={}
    for profile in _PROFILES:
        value=compute_higher_volatility_score(frame,profile);features[profile]=value;prefixes[profile]={};calibrations[profile]={}
        for f in folds:
            fid=str(f["fold_id"]);train=f["train_is"];mask=((time>=pd.Timestamp(train["start"]))&(time<=pd.Timestamp(train["end"]))).to_numpy();threshold=calibrate_selector(value[0],mask);vv=value[1][mask&np.isfinite(value[1])];cutoffs=(float(np.quantile(vv,1/3,method="higher")),float(np.quantile(vv,2/3,method="higher")));pv=compute_higher_volatility_score(prefix_frames[fid],profile);prefixes[profile][fid]=pv;pt=pd.to_datetime(prefix_frames[fid]["time"],errors="raise");pm=((pt>=pd.Timestamp(train["start"]))&(pt<=pd.Timestamp(train["end"]))).to_numpy();calibrations[profile][fid]=(threshold,cutoffs,calibrate_selector(pv[0],pm))
    results=[_evaluate_configuration(calibrations=calibrations[c.profile],frame=frame,features=features[c.profile],folds=folds,configuration=c,effective_spread=spread,prefix_features=prefixes[c.profile],prefix_spreads=prefix_spreads,time=time,executable_id=higher_volatility_executable(c).identity) for c in higher_volatility_configurations()];adjusted=_selection_adjusted_pvalues(results,total_exposures=SELECTION_TOTAL_EXPOSURES)
    for r in results:r.metrics["selection_aware_pvalue_ppm"]=adjusted[r.executable_id]
    _populate(results);surface={"claim_limits":_claim_limits()+["volatility_of_volatility_is_completed_bar_only","direction_is_prior_twelve_bar_return","four_trial_surface"],"dataset_sha256":DATASET_SHA256,"engine_environment":{"numpy":np.__version__,"pandas":pd.__version__,"python":".".join(str(v) for v in sys.version_info[:3]),"scipy":scipy.__version__},"evaluations":[{"direction_metrics":r.direction_metrics,"evaluable":all(r.metrics[n]==0 for n in ("unknown_cost_unresolved_signal_count","causality_violation_count","nonfinite_metric_count","prefix_invariance_mismatch_count","append_invariance_mismatch_count")),"fold_metrics":r.fold_metrics,"metrics":dict(sorted(r.metrics.items())),"regime_metrics":r.regime_metrics,"session_metrics":r.session_metrics,"subject_configuration_id":r.configuration.configuration_id,"subject_executable_id":r.executable_id} for r in results],"higher_volatility_implementation_sha256":higher_volatility_implementation_sha256(),"loader_implementation_sha256":loader_implementation_sha256(),"material_identity":OBSERVED_MATERIAL_ID,"schema":"higher_order_volatility_surface.v1","selection_context":[{"configuration_id":r.configuration.configuration_id,"executable_id":r.executable_id,"net_profit_micropoints":r.metrics["net_profit_micropoints"],"selection_aware_pvalue_ppm":r.metrics["selection_aware_pvalue_ppm"]} for r in results],"selection_method":_selection_method(SELECTION_TOTAL_EXPOSURES),"session_semantics":"broker_clock_fixed_bins_no_dst_or_cash_session_claim","split_artifact_sha256":ROLLING_SPLIT_SHA256};canonical_bytes(surface);return surface
def project_higher_volatility_evaluation(surface:Mapping[str,Any],*,job_execution:Mapping[str,str],subject_executable_id:str,surface_artifact_hash:str,surface_manifest_hash:str)->dict[str,Any]:
    value=dict(surface)
    if sha256(canonical_bytes(value)).hexdigest()!=surface_artifact_hash or value.get("schema")!="higher_order_volatility_surface.v1":raise DiscoveryBoundaryError("higher-volatility surface invalid")
    expected=executable_configuration_map();by={x.get("subject_executable_id"):x for x in value["evaluations"]}
    if set(by)!=set(expected) or subject_executable_id not in expected:raise DiscoveryBoundaryError("higher-volatility subjects differ")
    payload={n:job_execution[n] for n in ("job_hash","job_id","job_permit_id","start_record_id")}
    if job_execution.get("identity")!=canonical_digest(domain="running-job-execution",payload=payload):raise DiscoveryBoundaryError("Job invalid")
    result={**dict(by[subject_executable_id]),"claim_limits":value["claim_limits"],"job_execution":dict(job_execution),"schema":"higher_order_volatility_evaluation.v1","selection_context":value["selection_context"],"selection_method":value["selection_method"],"session_semantics":value["session_semantics"],"surface_artifact_hash":surface_artifact_hash,"surface_manifest_hash":surface_manifest_hash};canonical_bytes(result);return result
__all__=["compute_higher_volatility_score","compute_registered_higher_volatility_surface","executable_configuration_map","higher_volatility_configurations","higher_volatility_executable","higher_volatility_implementation_sha256","loader_implementation_sha256","project_higher_volatility_evaluation"]
