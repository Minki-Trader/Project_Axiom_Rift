"""Causal post-break acceptance and failure discovery for US100 M5."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec, canonical_digest
from axiom_rift.research.data import load_observed_development
from axiom_rift.research import data as data_module
from axiom_rift.research.discovery import (
    DATASET_SHA256, OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256,
    SELECTION_BLOCK_LENGTHS, SELECTION_BOOTSTRAP_SAMPLES,
    SELECTION_MONTE_CARLO_CONFIDENCE_PPM, SELECTION_SEED,
    DiscoveryBoundaryError, _claim_limits, _consecutive_run,
    _evaluate_configuration, _fold_payloads, _paired_control_pvalue,
    _selection_adjusted_pvalues, _selection_method, _time_ns,
    _validate_engine_environment, _validate_fold_payloads,
    _validate_production_data, causal_effective_spread,
    discovery_implementation_sha256,
)


SELECTION_TOTAL_EXPOSURES = 270
SELECTOR_QUANTILE_BP = 5_000
_PROFILES = {
    "failure_24": ("failure", 24),
    "failure_48": ("failure", 48),
    "acceptance_48": ("acceptance", 48),
}
_THIS_FILE = Path(__file__).resolve()


def post_break_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def loader_implementation_sha256() -> str:
    return sha256(Path(data_module.__file__).resolve().read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class PostBreakConfiguration:
    profile: str
    signal_sign: int
    holding_bars: int

    def __post_init__(self) -> None:
        if self.profile not in _PROFILES or self.signal_sign not in {-1, 1} or self.holding_bars not in {3, 12}:
            raise ValueError("post-break configuration is not registered")

    @property
    def event_state(self) -> str:
        return _PROFILES[self.profile][0]

    @property
    def lookback(self) -> int:
        return _PROFILES[self.profile][1]

    @property
    def configuration_id(self) -> str:
        sign = "original_direction" if self.signal_sign == 1 else "opposite_direction"
        return f"{self.profile}-{sign}-h{self.holding_bars}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {"event_state": self.event_state, "holding_bars": self.holding_bars, "level_lookback_bars": self.lookback, "selector_nonzero_quantile_bp": SELECTOR_QUANTILE_BP, "signal_sign": self.signal_sign}


def post_break_configurations() -> tuple[PostBreakConfiguration, ...]:
    return tuple(PostBreakConfiguration(profile=profile, signal_sign=sign, holding_bars=holding) for profile in _PROFILES for sign in (1, -1) for holding in (3, 12))


def _local(name: str) -> str:
    return f"axiom_rift.research.post_break_discovery.{name}@sha256:{post_break_implementation_sha256()}"


def _shared(name: str) -> str:
    return f"axiom_rift.research.discovery.{name}@sha256:{discovery_implementation_sha256()}"


def post_break_components() -> tuple[ComponentSpec, ...]:
    return (
        ComponentSpec(display_name="causal post-break state score", protocol="feature.post_break_acceptance_failure.v1", implementation=_local("compute_post_break_score"), spec={"availability":"two_completed_bars_only","break_level":"prior_rolling_high_or_low_excluding_break_bar","event_states":["acceptance","failure"],"parameter_fields":["event_state","level_lookback_bars"]}),
        ComponentSpec(display_name="fold isolated post-break selector", protocol="selector.fold_train_post_break_quantile.v1", implementation=_local("calibrate_post_break_selector"), spec={"calibration_role":"train_is_only","minimum_nonzero_observations":500,"quantile_basis_points":SELECTOR_QUANTILE_BP,"quantile_method":"higher"}),
        ComponentSpec(display_name="completed-bar next-open directional entry", protocol="trade.completed_bar_next_open_direction.v2", implementation=_shared("simulate_fixed_hold"), spec={"decision_time":"bar_open_plus_5m","entry_time":"next_exact_bar_open","direction":"signal_sign_times_original_break_sign","parameter_fields":["signal_sign"]}),
        ComponentSpec(display_name="fixed-hold nonoverlap lifecycle", protocol="lifecycle.fixed_hold_no_overlap.v2", implementation=_shared("simulate_fixed_hold"), spec={"entry_overlap":"reject_while_position_slot_is_occupied","exit_surface":"exact_bar_open_after_holding_bars","gap_action":"exclude_path","parameter_fields":["holding_bars"]}),
        ComponentSpec(display_name="FPMarkets bid-bar spread execution", protocol="execution.fpmarkets_bid_bar_spread.v2", implementation=_shared("execution_pnl"), spec={"bar_quote_basis":"bid_ohlc_with_spread_points","point":"0.01","stress":"half_effective_spread_each_side","zero_spread_action":"causal_lagged_positive_median"}),
        ComponentSpec(display_name="fixed one-lot single-sleeve risk", protocol="risk.fixed_one_lot.v1", implementation=_shared("simulate_fixed_hold"), spec={"dynamic_sizing":False,"lot":1,"positions_per_sleeve":1}),
    )


def post_break_executable(configuration: PostBreakConfiguration) -> ExecutableSpec:
    return ExecutableSpec(display_name=f"post break {configuration.configuration_id}", components=post_break_components(), parameters=configuration.semantic_parameters(), data_contract=f"data:{OBSERVED_MATERIAL_ID}", split_contract=f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development", clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v2", cost_contract="cost:bid_bar_spread_point_0_01_causal_zero_repair_half_spread_stress_v2", engine_contract=f"engine:post_break_discovery_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:implementation_{post_break_implementation_sha256()}:loader_{loader_implementation_sha256()}:shared_{discovery_implementation_sha256()}:bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:mc_upper_{SELECTION_MONTE_CARLO_CONFIDENCE_PPM}:bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}")


def executable_configuration_map() -> dict[str, PostBreakConfiguration]:
    return {post_break_executable(item).identity:item for item in post_break_configurations()}


def compute_post_break_score(frame: pd.DataFrame, *, event_state: str, lookback: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if event_state not in {"acceptance","failure"} or lookback not in {24,48}:
        raise ValueError("post-break feature parameters are not registered")
    high=frame["high"].to_numpy(dtype=float); low=frame["low"].to_numpy(dtype=float); close=frame["close"].to_numpy(dtype=float)
    prior_high=pd.Series(high).shift(1).rolling(lookback,min_periods=lookback).max().to_numpy(dtype=float); prior_low=pd.Series(low).shift(1).rolling(lookback,min_periods=lookback).min().to_numpy(dtype=float)
    previous_close=np.roll(close,1); previous_close[0]=close[0]; tr=np.maximum.reduce((high-low,np.abs(high-previous_close),np.abs(low-previous_close))); scale=pd.Series(tr).rolling(48,min_periods=48).median().to_numpy(dtype=float)
    break_up=np.zeros(len(frame),dtype=bool); break_down=np.zeros(len(frame),dtype=bool); break_up[1:]=close[:-1]>prior_high[:-1]; break_down[1:]=close[:-1]<prior_low[:-1]
    reference_high=np.roll(prior_high,1); reference_low=np.roll(prior_low,1); strength_up=np.zeros(len(frame)); strength_down=np.zeros(len(frame)); valid=np.isfinite(scale)&(scale>0)&np.isfinite(reference_high)&np.isfinite(reference_low)
    strength_up[valid]=(previous_close[valid]-reference_high[valid])/scale[valid]; strength_down[valid]=(previous_close[valid]-reference_low[valid])/scale[valid]
    if event_state=="failure": up_event=break_up&(close<=reference_high); down_event=break_down&(close>=reference_low)
    else: up_event=break_up&(close>reference_high); down_event=break_down&(close<reference_low)
    score=np.zeros(len(frame)); score[up_event&valid]=np.maximum(strength_up[up_event&valid],0); score[down_event&valid]=np.minimum(strength_down[down_event&valid],0)
    run=_consecutive_run(_time_ns(frame)); score[(run<max(50,lookback+2))|~np.isfinite(score)]=np.nan; volatility=pd.Series(np.log(close)).diff().rolling(48,min_periods=48).std(ddof=1).to_numpy(dtype=float)
    return score,volatility,run


def calibrate_post_break_selector(score: np.ndarray, train_mask: np.ndarray) -> float:
    values=np.abs(score[train_mask&np.isfinite(score)&(score!=0)])
    if len(values)<500: raise DiscoveryBoundaryError("post-break selector has fewer than 500 events")
    return float(np.quantile(values,SELECTOR_QUANTILE_BP/10000,method="higher"))


def _matched(results:list[Any],profile:str,sign:int,holding:int)->Any:
    matches=[r for r in results if r.configuration.profile==profile and r.configuration.signal_sign==sign and r.configuration.holding_bars==holding]
    if len(matches)!=1: raise DiscoveryBoundaryError("post-break control match is not unique")
    return matches[0]


def _populate_controls(results:list[Any])->None:
    for subject in results:
        opposite=_matched(results,subject.configuration.profile,-subject.configuration.signal_sign,subject.configuration.holding_bars); controls=[_matched(results,p,subject.configuration.signal_sign,subject.configuration.holding_bars) for p in _PROFILES if p!=subject.configuration.profile]
        subject.metrics["opposite_sign_worst_delta_net_profit_micropoints"]=subject.metrics["net_profit_micropoints"]-opposite.metrics["net_profit_micropoints"]; subject.metrics["opposite_sign_pvalue_upper_ppm"]=_paired_control_pvalue(subject,opposite,role="opposite_sign",total_exposures=SELECTION_TOTAL_EXPOSURES); subject.metrics["feature_control_worst_delta_net_profit_micropoints"]=min(subject.metrics["net_profit_micropoints"]-c.metrics["net_profit_micropoints"] for c in controls); subject.metrics["feature_control_worst_pvalue_upper_ppm"]=max(_paired_control_pvalue(subject,c,role="event_state",total_exposures=SELECTION_TOTAL_EXPOSURES) for c in controls)


def compute_registered_post_break_surface(repository_root:str|Path)->dict[str,Any]:
    _validate_engine_environment(); data=load_observed_development(Path(repository_root).resolve()); _validate_production_data(data); folds=_fold_payloads(data); _validate_fold_payloads(data.frame,folds); frame=data.frame; time=pd.to_datetime(frame["time"],errors="raise"); spread=causal_effective_spread(frame["spread"].to_numpy(dtype=float),_time_ns(frame)); prefix_frames={}; prefix_spreads={}
    for fold in folds:
        fid=str(fold["fold_id"]); end=int(time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]),side="right")); prefix_frames[fid]=frame.iloc[:end]; prefix_spreads[fid]=causal_effective_spread(prefix_frames[fid]["spread"].to_numpy(dtype=float),_time_ns(prefix_frames[fid]))
    features={}; prefixes={}; calibrations={}
    for profile,(state,lookback) in _PROFILES.items():
        value=compute_post_break_score(frame,event_state=state,lookback=lookback); features[profile]=value; prefixes[profile]={}; calibrations[profile]={}
        for fold in folds:
            fid=str(fold["fold_id"]); train=fold["train_is"]; mask=((time>=pd.Timestamp(train["start"]))&(time<=pd.Timestamp(train["end"]))).to_numpy(); threshold=calibrate_post_break_selector(value[0],mask); vol=value[1][mask&np.isfinite(value[1])]; cutoffs=(float(np.quantile(vol,1/3,method="higher")),float(np.quantile(vol,2/3,method="higher"))); pv=compute_post_break_score(prefix_frames[fid],event_state=state,lookback=lookback); prefixes[profile][fid]=pv; pt=pd.to_datetime(prefix_frames[fid]["time"],errors="raise"); pm=((pt>=pd.Timestamp(train["start"]))&(pt<=pd.Timestamp(train["end"]))).to_numpy(); calibrations[profile][fid]=(threshold,cutoffs,calibrate_post_break_selector(pv[0],pm))
    results=[]
    for config in post_break_configurations():
        eid=post_break_executable(config).identity; results.append(_evaluate_configuration(calibrations=calibrations[config.profile],frame=frame,features=features[config.profile],folds=folds,configuration=config,effective_spread=spread,prefix_features=prefixes[config.profile],prefix_spreads=prefix_spreads,time=time,executable_id=eid))
    pvalues=_selection_adjusted_pvalues(results,total_exposures=SELECTION_TOTAL_EXPOSURES)
    for result in results: result.metrics["selection_aware_pvalue_ppm"]=pvalues[result.executable_id]
    _populate_controls(results)
    surface={"claim_limits":_claim_limits()+["post_break_state_uses_two_completed_bars","break_reference_excludes_break_bar"],"dataset_sha256":DATASET_SHA256,"engine_environment":{"numpy":np.__version__,"pandas":pd.__version__,"python":".".join(str(v) for v in sys.version_info[:3]),"scipy":scipy.__version__},"evaluations":[{"direction_metrics":r.direction_metrics,"evaluable":all(r.metrics[n]==0 for n in ("unknown_cost_unresolved_signal_count","causality_violation_count","nonfinite_metric_count","prefix_invariance_mismatch_count","append_invariance_mismatch_count")),"fold_metrics":r.fold_metrics,"metrics":dict(sorted(r.metrics.items())),"regime_metrics":r.regime_metrics,"session_metrics":r.session_metrics,"subject_configuration_id":r.configuration.configuration_id,"subject_executable_id":r.executable_id} for r in results],"loader_implementation_sha256":loader_implementation_sha256(),"material_identity":OBSERVED_MATERIAL_ID,"post_break_implementation_sha256":post_break_implementation_sha256(),"schema":"post_break_discovery_surface.v1","selection_context":[{"configuration_id":r.configuration.configuration_id,"executable_id":r.executable_id,"net_profit_micropoints":r.metrics["net_profit_micropoints"],"selection_aware_pvalue_ppm":r.metrics["selection_aware_pvalue_ppm"]} for r in results],"selection_method":_selection_method(SELECTION_TOTAL_EXPOSURES),"session_semantics":"broker_clock_fixed_bins_no_dst_or_cash_session_claim","split_artifact_sha256":ROLLING_SPLIT_SHA256}; canonical_bytes(surface); return surface


def project_post_break_evaluation(surface:Mapping[str,Any],*,job_execution:Mapping[str,str],subject_executable_id:str,surface_artifact_hash:str,surface_manifest_hash:str)->dict[str,Any]:
    value=dict(surface)
    if sha256(canonical_bytes(value)).hexdigest()!=surface_artifact_hash or value.get("schema")!="post_break_discovery_surface.v1": raise DiscoveryBoundaryError("post-break surface identity is invalid")
    expected=executable_configuration_map(); evaluations=value.get("evaluations"); by={item.get("subject_executable_id"):item for item in evaluations if isinstance(item,Mapping)} if isinstance(evaluations,list) else {}
    if set(by)!=set(expected) or subject_executable_id not in expected: raise DiscoveryBoundaryError("post-break subjects differ from registration")
    payload={n:job_execution[n] for n in ("job_hash","job_id","job_permit_id","start_record_id")}
    if job_execution.get("identity")!=canonical_digest(domain="running-job-execution",payload=payload): raise DiscoveryBoundaryError("post-break Job identity is invalid")
    result={**dict(by[subject_executable_id]),"claim_limits":value["claim_limits"],"job_execution":dict(job_execution),"schema":"post_break_interaction_evaluation.v1","selection_context":value["selection_context"],"selection_method":value["selection_method"],"session_semantics":value["session_semantics"],"surface_artifact_hash":surface_artifact_hash,"surface_manifest_hash":surface_manifest_hash}; canonical_bytes(result); return result


__all__=["PostBreakConfiguration","SELECTION_TOTAL_EXPOSURES","compute_post_break_score","compute_registered_post_break_surface","executable_configuration_map","loader_implementation_sha256","post_break_configurations","post_break_executable","post_break_implementation_sha256","project_post_break_evaluation"]
