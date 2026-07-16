"""Fold-trained regularized multivariate state discovery."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any,Mapping,Sequence
import numpy as np
import pandas as pd
import scipy
from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ComponentSpec,ExecutableSpec,canonical_digest
from axiom_rift.research import data as data_module
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import DATASET_SHA256,OBSERVED_MATERIAL_ID,ROLLING_SPLIT_SHA256,SELECTION_BOOTSTRAP_SAMPLES,SELECTION_SEED,DiscoveryBoundaryError,_claim_limits,_consecutive_run,_evaluate_configuration,_fold_payloads,_paired_control_pvalue,_selection_adjusted_pvalues,_selection_method,_time_ns,_validate_engine_environment,_validate_fold_payloads,_validate_production_data,causal_effective_spread,discovery_implementation_sha256
SELECTION_TOTAL_EXPOSURES=408;SELECTOR_QUANTILE_BP=8_500;_PROFILES=("ridge_interaction","ridge_price_control");_THIS_FILE=Path(__file__).resolve();_RIDGE=100.0;_HORIZON=96
def learned_implementation_sha256()->str:return sha256(_THIS_FILE.read_bytes()).hexdigest()
def loader_implementation_sha256()->str:return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()
@dataclass(frozen=True,slots=True)
class LearnedConfiguration:
    profile:str;signal_sign:int;holding_bars:int=96
    def __post_init__(self)->None:
        if self.profile not in _PROFILES or self.signal_sign not in {-1,1} or self.holding_bars!=96:raise ValueError("learned configuration invalid")
    @property
    def configuration_id(self)->str:return f"{self.profile}-{'model' if self.signal_sign==1 else 'inverse'}-h96"
    def semantic_parameters(self)->dict[str,Any]:return {"holding_bars":96,"profile":self.profile,"ridge_lambda":100,"selector_quantile_bp":SELECTOR_QUANTILE_BP,"signal_sign":self.signal_sign}
def learned_configurations()->tuple[LearnedConfiguration,...]:return tuple(LearnedConfiguration(profile=p,signal_sign=s) for p in _PROFILES for s in (1,-1))
def _local(n:str)->str:return f"axiom_rift.research.learned_state_discovery.{n}@sha256:{learned_implementation_sha256()}"
def _shared(n:str)->str:return f"axiom_rift.research.discovery.{n}@sha256:{discovery_implementation_sha256()}"
def learned_components()->tuple[ComponentSpec,...]:return (ComponentSpec(display_name="fold-trained ridge interaction predictor",protocol="model.fold_train_ridge_state.v2",implementation=_local("fit_fold_model"),spec={"availability":"train_is_only","horizon_bars":96,"lambda":100,"profiles":list(_PROFILES),"standardization":"train_mean_population_std","interaction_scope":"first_three_price_states_with_nonprice_states","parameter_fields":["profile"]}),ComponentSpec(display_name="fold isolated prediction selector",protocol="selector.fold_train_abs_quantile.v2",implementation=_local("calibrate_selector"),spec={"calibration_role":"train_is_only","minimum_train_observations":1000,"quantile_basis_points":SELECTOR_QUANTILE_BP,"quantile_method":"higher"}),ComponentSpec(display_name="completed-bar next-open directional entry",protocol="trade.completed_bar_next_open_direction.v2",implementation=_shared("simulate_fixed_hold"),spec={"decision_time":"bar_open_plus_5m","entry_time":"next_exact_bar_open","direction":"signal_sign_times_score_sign","parameter_fields":["signal_sign"]}),ComponentSpec(display_name="fixed-hold nonoverlap lifecycle",protocol="lifecycle.fixed_hold_no_overlap.v2",implementation=_shared("simulate_fixed_hold"),spec={"entry_overlap":"reject_while_position_slot_is_occupied","exit_surface":"exact_bar_open_after_96_bars","gap_action":"exclude_path"}),ComponentSpec(display_name="FPMarkets completed-period spread proxy execution",protocol="execution.fpmarkets_completed_bar_spread_proxy.v2",implementation=_shared("execution_pnl"),spec={"point":"0.01","stress":"half_effective_spread_each_side"}),ComponentSpec(display_name="fixed one-lot risk",protocol="risk.fixed_one_lot.v1",implementation=_shared("simulate_fixed_hold"),spec={"dynamic_sizing":False,"lot":1,"positions_per_sleeve":1}))
def learned_executable(c:LearnedConfiguration)->ExecutableSpec:return ExecutableSpec(display_name=f"learned state {c.configuration_id}",components=learned_components(),parameters=c.semantic_parameters(),data_contract=f"data:{OBSERVED_MATERIAL_ID}",split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development",clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v2",cost_contract="cost:fpmarkets_completed_bar_spread_proxy_point_0_01_causal_zero_repair_half_spread_stress_v2",engine_contract=f"engine:learned_state_v2:python{'.'.join(str(v) for v in sys.version_info[:3])}:numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:implementation_{learned_implementation_sha256()}:loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}")
def executable_configuration_map()->dict[str,LearnedConfiguration]:return {learned_executable(c).identity:c for c in learned_configurations()}
def _raw_features(frame:pd.DataFrame,profile:str)->tuple[np.ndarray,np.ndarray,np.ndarray]:
    if profile not in _PROFILES:raise ValueError("profile invalid")
    close=frame["close"].to_numpy(float);log=np.log(close);ret=np.full(len(close),np.nan);ret[1:]=np.diff(log);series=pd.Series(ret);vol=series.rolling(192,min_periods=192).std(ddof=1).to_numpy(float);columns=[]
    for period in (12,48,192):
        value=np.full(len(close),np.nan);value[period:]=log[period:]-log[:-period];columns.append(np.divide(value,vol*np.sqrt(period),out=np.full(len(close),np.nan),where=np.isfinite(vol)&(vol>0)))
    if profile=="ridge_interaction":
        o=frame["open"].to_numpy(float);h=frame["high"].to_numpy(float);l=frame["low"].to_numpy(float);span=h-l;body=np.divide(close-o,span,out=np.full(len(close),np.nan),where=span>0);columns.append(pd.Series(body).rolling(24,min_periods=24).mean().to_numpy(float));spread=causal_effective_spread(frame["spread"].to_numpy(float),_time_ns(frame));ss=pd.Series(spread);sm=ss.rolling(96,min_periods=96).mean();sd=ss.rolling(96,min_periods=96).std(ddof=1);columns.append(((ss-sm)/sd.where(sd>0)).to_numpy(float));columns.append(series.rolling(96,min_periods=96).skew().to_numpy(float));base=list(columns);columns.extend(base[i]*base[j] for i in range(3) for j in range(3,len(base)))
    run=_consecutive_run(_time_ns(frame));return np.column_stack(columns),vol,run
def fit_fold_model(frame:pd.DataFrame,profile:str,train_start:pd.Timestamp,train_end:pd.Timestamp)->tuple[np.ndarray,np.ndarray,np.ndarray]:
    x,vol,run=_raw_features(frame,profile);time=pd.to_datetime(frame["time"],errors="raise");close=np.log(frame["close"].to_numpy(float));target=np.full(len(close),np.nan);target[:-_HORIZON]=close[_HORIZON:]-close[:-_HORIZON];mask=((time>=train_start)&(time<=train_end)).to_numpy()&np.isfinite(target)&np.isfinite(x).all(axis=1);future_time=time.shift(-_HORIZON);mask&=(future_time<=train_end).to_numpy();xt=x[mask];yt=target[mask]
    if len(yt)<1000:raise DiscoveryBoundaryError("model train too small")
    mean=xt.mean(axis=0);std=xt.std(axis=0,ddof=0);std=np.where(std>0,std,1.0);z=(xt-mean)/std;coef=np.linalg.solve(z.T@z+_RIDGE*np.eye(z.shape[1]),z.T@yt);allz=(x-mean)/std;score=allz@coef;score[~np.isfinite(x).all(axis=1)]=np.nan;score[run<193]=np.nan;return score,vol,run
def calibrate_selector(score:np.ndarray,mask:np.ndarray)->float:
    v=np.abs(score[mask&np.isfinite(score)])
    if len(v)<1000:raise DiscoveryBoundaryError("selector too small")
    return float(np.quantile(v,SELECTOR_QUANTILE_BP/10000,method="higher"))
def _matched(results:list[Any],profile:str,sign:int)->Any:
    found=[r for r in results if r.configuration.profile==profile and r.configuration.signal_sign==sign]
    if len(found)!=1:raise DiscoveryBoundaryError("control not unique")
    return found[0]
def _populate(results:list[Any])->None:
    for s in results:
        c=s.configuration;opposite=_matched(results,c.profile,-c.signal_sign);control=_matched(results,next(p for p in _PROFILES if p!=c.profile),c.signal_sign);s.metrics["opposite_sign_worst_delta_net_profit_micropoints"]=s.metrics["net_profit_micropoints"]-opposite.metrics["net_profit_micropoints"];s.metrics["opposite_sign_pvalue_upper_ppm"]=_paired_control_pvalue(s,opposite,role="opposite_sign",total_exposures=SELECTION_TOTAL_EXPOSURES);s.metrics["feature_control_worst_delta_net_profit_micropoints"]=s.metrics["net_profit_micropoints"]-control.metrics["net_profit_micropoints"];s.metrics["feature_control_worst_pvalue_upper_ppm"]=_paired_control_pvalue(s,control,role="learned_profile",total_exposures=SELECTION_TOTAL_EXPOSURES)
def compute_registered_learned_surface(repository_root:str|Path)->dict[str,Any]:
    _validate_engine_environment();data=load_observed_development(Path(repository_root).resolve());_validate_production_data(data);folds=_fold_payloads(data);_validate_fold_payloads(data.frame,folds);frame=data.frame;time=pd.to_datetime(frame["time"],errors="raise");spread=causal_effective_spread(frame["spread"].to_numpy(float),_time_ns(frame));prefix_frames={};prefix_spreads={}
    for f in folds:
        fid=str(f["fold_id"]);end=int(time.searchsorted(pd.Timestamp(f["test_oos"]["end"]),side="right"));prefix_frames[fid]=frame.iloc[:end];prefix_spreads[fid]=causal_effective_spread(prefix_frames[fid]["spread"].to_numpy(float),_time_ns(prefix_frames[fid]))
    results=[]
    for c in learned_configurations():
        fold_features={};prefix_features={};calibrations={}
        for f in folds:
            fid=str(f["fold_id"]);train=f["train_is"];start=pd.Timestamp(train["start"]);end=pd.Timestamp(train["end"]);value=fit_fold_model(frame,c.profile,start,end);prefix=fit_fold_model(prefix_frames[fid],c.profile,start,end);fold_features[fid]=value;prefix_features[fid]=prefix;mask=((time>=start)&(time<=end)).to_numpy();pt=pd.to_datetime(prefix_frames[fid]["time"],errors="raise");pm=((pt>=start)&(pt<=end)).to_numpy();vv=value[1][mask&np.isfinite(value[1])];cutoffs=(float(np.quantile(vv,1/3,method="higher")),float(np.quantile(vv,2/3,method="higher")));calibrations[fid]=(calibrate_selector(value[0],mask),cutoffs,calibrate_selector(prefix[0],pm))
        first=fold_features[str(folds[0]["fold_id"])];results.append(_evaluate_configuration(calibrations=calibrations,frame=frame,features=first,fold_features=fold_features,folds=folds,configuration=c,effective_spread=spread,prefix_features=prefix_features,prefix_spreads=prefix_spreads,time=time,executable_id=learned_executable(c).identity))
    pv=_selection_adjusted_pvalues(results,total_exposures=SELECTION_TOTAL_EXPOSURES)
    for r in results:r.metrics["selection_aware_pvalue_ppm"]=pv[r.executable_id]
    _populate(results);surface={"claim_limits":_claim_limits()+["models_are_fold_train_only","bounded_interactions_only","four_trial_surface"],"dataset_sha256":DATASET_SHA256,"engine_environment":{"numpy":np.__version__,"pandas":pd.__version__,"python":".".join(str(v) for v in sys.version_info[:3]),"scipy":scipy.__version__},"evaluations":[{"direction_metrics":r.direction_metrics,"evaluable":all(r.metrics[n]==0 for n in ("unknown_cost_unresolved_signal_count","causality_violation_count","nonfinite_metric_count","prefix_invariance_mismatch_count","append_invariance_mismatch_count")),"fold_metrics":r.fold_metrics,"metrics":dict(sorted(r.metrics.items())),"regime_metrics":r.regime_metrics,"session_metrics":r.session_metrics,"subject_configuration_id":r.configuration.configuration_id,"subject_executable_id":r.executable_id} for r in results],"loader_implementation_sha256":loader_implementation_sha256(),"material_identity":OBSERVED_MATERIAL_ID,"schema":"learned_state_surface.v2","selection_context":[{"configuration_id":r.configuration.configuration_id,"executable_id":r.executable_id,"net_profit_micropoints":r.metrics["net_profit_micropoints"],"selection_aware_pvalue_ppm":r.metrics["selection_aware_pvalue_ppm"]} for r in results],"selection_method":_selection_method(SELECTION_TOTAL_EXPOSURES),"session_semantics":"broker_clock_fixed_bins_no_dst_or_cash_session_claim","learned_implementation_sha256":learned_implementation_sha256(),"split_artifact_sha256":ROLLING_SPLIT_SHA256};canonical_bytes(surface);return surface
def project_learned_evaluation(surface:Mapping[str,Any],*,job_execution:Mapping[str,str],subject_executable_id:str,surface_artifact_hash:str,surface_manifest_hash:str)->dict[str,Any]:
    value=dict(surface)
    if sha256(canonical_bytes(value)).hexdigest()!=surface_artifact_hash or value.get("schema")!="learned_state_surface.v2":raise DiscoveryBoundaryError("surface invalid")
    expected=executable_configuration_map();by={x.get("subject_executable_id"):x for x in value["evaluations"]}
    if set(by)!=set(expected) or subject_executable_id not in expected:raise DiscoveryBoundaryError("subjects differ")
    payload={n:job_execution[n] for n in ("job_hash","job_id","job_permit_id","start_record_id")}
    if job_execution.get("identity")!=canonical_digest(domain="running-job-execution",payload=payload):raise DiscoveryBoundaryError("Job invalid")
    result={**dict(by[subject_executable_id]),"claim_limits":value["claim_limits"],"job_execution":dict(job_execution),"schema":"learned_state_evaluation.v2","selection_context":value["selection_context"],"selection_method":value["selection_method"],"session_semantics":value["session_semantics"],"surface_artifact_hash":surface_artifact_hash,"surface_manifest_hash":surface_manifest_hash};canonical_bytes(result);return result
__all__=["compute_registered_learned_surface","executable_configuration_map","fit_fold_model","learned_configurations","learned_executable","learned_implementation_sha256","loader_implementation_sha256","project_learned_evaluation"]
