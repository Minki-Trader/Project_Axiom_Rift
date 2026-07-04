"""SC0002 SR0001 proxy for cross-surface veto-inversion synthesis."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies.common import base
from axiom_rift.proxies.common import event_reclaim as event


WORK_UNIT_ID = "SC0002"
RUN_ID = "SR0001"
WORK_UNIT_DIR = PROJECT_ROOT / "campaigns" / "SC0002_accumulated_post_sc0001_negative_memory_synthesis"
RUN_DIR = WORK_UNIT_DIR / "runs" / RUN_ID
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "sc0002_sr0001_proxy_trades.csv"
SUMMARY_ARTIFACT_PATH = RUN_DIR / "artifacts" / "sc0002_sr0001_veto_inversion_summary.json"
RUN_MANIFEST_PATH = RUN_DIR / "run_manifest.json"
GATE_REPORT_PATH = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE_PATH = RUN_DIR / "artifact_lineage.json"
SYNTHESIS_PATH = WORK_UNIT_DIR / "synthesis.yaml"
SYNTHESIS_QUEUE_PATH = WORK_UNIT_DIR / "synthesis_queue.yaml"
CLAIM_STATE_PATH = PROJECT_ROOT / "registries" / "claim_state.yaml"

BASE_FRAME = event.BASE_FRAME
ROLLING_WINDOWS = event.ROLLING_WINDOWS
TIME_FORMAT = base.TIME_FORMAT
SplitWindow = event.SplitWindow
Trade = base.Trade
load_bars = base.load_bars
load_windows = base.load_windows

SOURCE_INGREDIENT_IDS = (
    "c0004_ig001_simple_archetype_negative_memory",
    "c0004_ig002_path_quality_archetype_negative_memory",
    "c0004_ig003_adverse_inversion_negative_memory",
    "c0004_ig004_temporal_stability_archetype_negative_memory",
    "c0005_ig001_mean_analog_negative_memory",
    "c0005_ig002_directional_contrast_negative_memory",
    "c0005_ig003_temporal_stability_negative_memory",
    "c0005_ig004_target_first_tail_hazard_negative_memory",
    "c0005_ig005_calibrated_classifier_negative_memory",
    "c0005_ig006_metric_rank_ensemble_negative_memory",
    "c0006_ig001_immediate_reclaim_negative_memory",
    "c0006_ig002_acceptance_continuation_negative_memory",
    "c0006_ig003_delayed_trap_rejection_negative_memory",
    "c0006_ig004_two_sided_sweep_reversion_negative_memory",
    "c0006_ig005_reclaim_retest_rejection_negative_memory",
)
MODEL_FAMILY = "fold_local_cross_surface_failure_mode_veto_inversion"
LABEL_SHAPE = "target_before_stop_adverse_path_avoidance_fold_local_consistency"
FEATURE_NAMES = event.FEATURE_NAMES
SCORE_COMPONENT_NAMES = (
    "source_event_utility",
    "failed_family_veto_pressure",
    "opposite_rejection_path_quality",
    "analog_dispersion_penalty",
    "execution_pressure_penalty",
)
MIN_INVERSION_QUALITY = 0.04
MAX_SPREAD_OVER_RANGE = 0.42


def run_sc0002_sr0001_proxy(write: bool = True) -> dict[str, object]:
    result = build_proxy_run_result()
    payload = build_proxy_payload(
        result.trades,
        result.windows,
        result.fold_models,
        result.state_distributions,
        result.candidates_by_fold,
    )
    if write:
        write_proxy_evidence(payload, result.trades)
    return payload


def load_proxy_trades() -> list[base.Trade]:
    if TRADE_ARTIFACT_PATH.exists():
        return event.read_trade_artifact(TRADE_ARTIFACT_PATH)
    return build_proxy_run_result().trades


def build_proxy_run_result() -> base.ProxyRunResult:
    bars = base.load_bars(BASE_FRAME)
    windows = base.load_windows(ROLLING_WINDOWS)
    ranges = [bar.high - bar.low for bar in bars]
    range_average = base.previous_rolling_average(ranges, base.LOOKBACK_RANGE_BARS)
    short_range_average = base.previous_rolling_average(ranges, base.SHORT_RANGE_BARS)
    trades: list[base.Trade] = []
    fold_models: list[dict[str, object]] = []
    state_distributions: dict[str, dict[str, float | int | None]] = {}
    candidates_by_fold: dict[str, dict[str, int]] = {}

    for fold_id in sorted(fold_id for fold_id, split in windows.items() if {"train_is", "test_oos"} <= set(split)):
        split = windows[fold_id]
        train_candidates = event.build_candidates(
            bars,
            range_average,
            short_range_average,
            split["train_is"],
            fold_id,
            include_labels=True,
        )
        model = event.fit_event_model(train_candidates, fold_id)
        test_candidates = event.build_candidates(
            bars,
            range_average,
            short_range_average,
            split["test_oos"],
            fold_id,
            include_labels=False,
        )
        scored_candidates = score_cross_surface_candidates(test_candidates, model)
        selected = base.select_daily_candidates(scored_candidates)
        fold_trades = base.simulate_trades(bars, range_average, selected, split["test_oos"])
        trades.extend(fold_trades)
        fold_models.append(cross_surface_model_summary(model))
        state_distributions[fold_id] = cross_surface_distribution(scored_candidates, selected, model)
        candidates_by_fold[fold_id] = {
            "train_candidate_count": len(train_candidates),
            "test_candidate_count": len(test_candidates),
            "selected_candidate_count": len(selected),
            "eligible_candidate_count": sum(1 for candidate in scored_candidates if candidate.score is not None),
            "feature_count": len(FEATURE_NAMES),
        }
    return base.ProxyRunResult(
        trades=sorted(trades, key=lambda trade: (trade.entry_time, trade.fold_id, trade.signal_index)),
        windows=windows,
        fold_models=fold_models,
        state_distributions=state_distributions,
        candidates_by_fold=candidates_by_fold,
    )


def score_cross_surface_candidates(
    candidates: list[base.Candidate],
    model: event.EventUtilityModel,
) -> list[base.Candidate]:
    source_scored = event.score_event_candidates(candidates, model)
    scored: list[base.Candidate] = []
    for candidate in source_scored:
        if candidate.score is None:
            scored.append(copy_candidate(candidate, None))
            continue
        features = feature_map(candidate)
        spread = features["spread_over_range"]
        inversion_quality = (
            0.38 * np.tanh(2.4 * features["retest_rejection_depth_over_range"])
            + 0.26 * features["retest_rejection_wick_fraction"]
            + 0.18 * features["retest_directional_close_location"]
            + 0.12 * max(features["retest_body_fraction"], 0.0)
            - 0.18 * np.tanh(3.0 * features["retest_overshoot_over_range"])
            - 0.14 * np.tanh(3.0 * features["retest_touch_gap_over_range"])
        )
        veto_pressure = (
            0.24 * np.tanh(max(features["prior_push_against_direction_12"], 0.0))
            + 0.18 * np.tanh(max(features["range_expansion_ratio"] - 1.0, 0.0))
            + 0.16 * np.tanh(abs(features["distance_from_range_mid_over_range"]))
            + 0.10 * features["session_scope_flag"]
            + 0.06 * features["wide_scope_flag"]
        )
        analog_dispersion_penalty = 0.11 * abs(features["compression_ratio_12_over_48"] - 1.0)
        execution_pressure_penalty = 0.24 * spread
        if inversion_quality < MIN_INVERSION_QUALITY or spread > MAX_SPREAD_OVER_RANGE:
            scored.append(copy_candidate(candidate, None))
            continue
        score = (
            0.42 * candidate.score
            + veto_pressure
            + inversion_quality
            - analog_dispersion_penalty
            - execution_pressure_penalty
        )
        scored.append(copy_candidate(candidate, float(score)))
    return scored


def feature_map(candidate: base.Candidate) -> dict[str, float]:
    return {name: float(candidate.features[index]) for index, name in enumerate(FEATURE_NAMES)}


def copy_candidate(candidate: base.Candidate, score: float | None) -> base.Candidate:
    side = "long" if candidate.direction > 0 else "short"
    return base.Candidate(
        fold_id=candidate.fold_id,
        index=candidate.index,
        direction=candidate.direction,
        day=candidate.day,
        state_key=f"{side}|cross_surface_veto_inversion",
        features=candidate.features,
        label=candidate.label,
        score=score,
    )


def build_proxy_payload(
    trades: list[base.Trade],
    windows: dict[str, dict[str, base.SplitWindow]],
    fold_models: list[dict[str, object]],
    state_distributions: dict[str, dict[str, float | int | None]],
    candidates_by_fold: dict[str, dict[str, int]],
) -> dict[str, object]:
    payload = replace_sc0002_markers(event.build_proxy_payload(trades, windows, fold_models, state_distributions, candidates_by_fold))
    payload["campaign_id"] = None
    payload["work_unit_id"] = WORK_UNIT_ID
    payload["synthesis_id_when_applicable"] = WORK_UNIT_ID
    payload["run_id"] = RUN_ID
    payload["proxy_id"] = "PX-SC0002-SR0001"
    payload["proxy_engine"] = "axiom_rift.proxies.sc0002_sr0001_cross_surface_veto_inversion"
    payload["proxy_config_path"] = "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_cross_surface_veto_inversion_fit"
    payload["proxy_artifact_paths"] = [
        "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001/kpi/proxy.json",
        "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001/artifacts/sc0002_sr0001_proxy_trades.csv",
        "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001/artifacts/sc0002_sr0001_veto_inversion_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("reclaim_retest_rejection_profile", None)  # type: ignore[union-attr]
    profiles["cross_surface_veto_inversion_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "model_family": MODEL_FAMILY,
            "feature_count": len(FEATURE_NAMES),
            "feature_names": list(FEATURE_NAMES),
            "label_shape": LABEL_SHAPE,
            "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
            "score_component_names": list(SCORE_COMPONENT_NAMES),
            "source_candidate_family": "c0006_reclaim_retest_rejection_liquidity_context",
            "c0004_role": "state_archetype_failures_used_as_veto_pressure_context",
            "c0005_role": "analog_memory_failures_used_as_dispersion_and_instability_context",
            "c0006_role": "liquidity_sweep_failures_used_as_rejection_context_not_selection_claim",
            "sc0001_role": "constraint_replay_failure_blocks_simple_negative_memory_replay",
            "min_inversion_quality": MIN_INVERSION_QUALITY,
            "max_spread_over_range": MAX_SPREAD_OVER_RANGE,
            "selection_rule": "top_fold_local_cross_surface_veto_inversion_scores_per_active_day",
            "fold_models": fold_models,
            "state_distributions": state_distributions,
            "candidates_by_fold": candidates_by_fold,
            "model_selected": False,
            "feature_set_selected": False,
            "label_selected": False,
            "trade_logic_selected": False,
        },
    }
    profiles["mt5_pairing_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "mt5_logic_parity_required_next": True,
            "mt5_tick_required_after_logic_parity": True,
            "fold_isolated_mt5_closeout_required": True,
            "proxy_result_may_close_run": False,
            "proxy_is_screening_gate_for_mt5": False,
            "weak_proxy_may_skip_mt5": False,
            "next_action": "produce_sc0002_sr0001_mt5_logic_parity_evidence",
        },
    }
    return payload


def proxy_config() -> dict[str, object]:
    config = dict(event.proxy_config())
    config.update(
        {
            "event_model": MODEL_FAMILY,
            "label_shape": LABEL_SHAPE,
            "selection_rule": "top_fold_local_cross_surface_veto_inversion_scores_per_active_day",
            "score_component_names": list(SCORE_COMPONENT_NAMES),
            "min_inversion_quality": MIN_INVERSION_QUALITY,
            "max_spread_over_range": MAX_SPREAD_OVER_RANGE,
            "variant_boundary": "cross_surface_failure_mode_veto_inversion_not_constraint_replay_or_parameter_nudge",
            "source_candidate_family": "reclaim_retest_rejection_events_as_liquidity_context",
            "fixed_lot_policy": "early_discovery_fixed_lot_no_equity_percent_sizing_rescue",
        }
    )
    return config


def cross_surface_model_summary(model: event.EventUtilityModel) -> dict[str, object]:
    summary = event.event_model_summary(model)
    summary["model_family"] = MODEL_FAMILY
    summary["score_interpretation"] = (
        "higher_score_means_failed_family_continuation_veto_and_independent_rejection_quality_align"
    )
    summary["score_component_names"] = list(SCORE_COMPONENT_NAMES)
    return summary


def cross_surface_distribution(
    scored: list[base.Candidate],
    selected: list[base.Candidate],
    model: event.EventUtilityModel,
) -> dict[str, float | int | None]:
    distribution = event.event_distribution(scored, selected, model)
    distribution["eligible_after_veto_inversion_filter_count"] = sum(1 for candidate in scored if candidate.score is not None)
    return distribution


def write_proxy_evidence(payload: dict[str, object], trades: list[base.Trade]) -> None:
    RUN_DIR.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    RUN_DIR.joinpath("kpi").mkdir(parents=True, exist_ok=True)
    base.write_trade_artifact(trades, TRADE_ARTIFACT_PATH)
    write_summary_artifact(payload, SUMMARY_ARTIFACT_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = base.sha256_file(TRADE_ARTIFACT_PATH)
    summary_hash = base.sha256_file(SUMMARY_ARTIFACT_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = base.sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_synthesis_status()
    update_synthesis_queue_after_proxy()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)


def write_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_cross_surface_veto_inversion_summary_v1",
        "template": False,
        "work_unit_id": WORK_UNIT_ID,
        "synthesis_id": WORK_UNIT_ID,
        "run_id": RUN_ID,
        "created_at_utc": payload["created_at_utc"],
        "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
        "proxy_config": payload["proxy_config"],
        "cross_surface_veto_inversion_profile": profiles["cross_surface_veto_inversion_profile"]["fields"],  # type: ignore[index]
        "claim_boundary": payload["claim_boundary"],
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_proxy_hashes(trade_hash: str, summary_hash: str) -> None:
    data = json.loads(PROXY_PATH.read_text(encoding="ascii"))
    data["proxy_artifact_hashes"] = [trade_hash, summary_hash]
    PROXY_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_artifact_lineage(proxy_hash: str, trade_hash: str, summary_hash: str) -> None:
    data = json.loads(ARTIFACT_LINEAGE_PATH.read_text(encoding="ascii"))
    records = [
        record
        for record in data.get("artifact_records", [])
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "cross_surface_veto_inversion_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-SC0002-SR0001-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/ingredient_refs.yaml",
                    "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/synthesis_queue.yaml",
                    "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-SC0002-SR0001-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001/artifacts/sc0002_sr0001_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-SC0002-SR0001-CROSS-SURFACE-SUMMARY",
                "cross_surface_veto_inversion_summary_artifact",
                "json",
                "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001/artifacts/sc0002_sr0001_veto_inversion_summary.json",
                summary_hash,
                ["campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_sc0002_sr0001_mt5_logic_parity_evidence",
        }
    ]
    ARTIFACT_LINEAGE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def artifact_record(
    artifact_id: str,
    role: str,
    artifact_type: str,
    path: str,
    digest: str,
    source_inputs: list[str],
) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "artifact_role": role,
        "artifact_type": artifact_type,
        "repo_relative_path": path,
        "sha256": digest,
        "produced_by": "axiom_rift.proxies.sc0002_sr0001_cross_surface_veto_inversion",
        "source_inputs": source_inputs,
        "linked_kpi_family": "proxy",
        "mutable": False,
        "claim_authority": False,
    }


def update_run_manifest_status() -> None:
    data = json.loads(RUN_MANIFEST_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_ready"
    data["gate_status"] = "proxy_recorded_pending_mt5"
    evidence = data.setdefault("evidence_paths", {})
    evidence["proxy_trade_artifact"] = "artifacts/sc0002_sr0001_proxy_trades.csv"
    evidence["cross_surface_veto_inversion_summary"] = "artifacts/sc0002_sr0001_veto_inversion_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_sc0002_sr0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/sc0002_sr0001_proxy_trades.csv",
        "artifacts/sc0002_sr0001_veto_inversion_summary.json",
        "kpi/proxy.json",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["evidence_paths"] = evidence_paths
    data["deferred_with_reason"] = [
        {
            "field": "decision",
            "reason": "proxy evidence is recorded but MT5 and proxy-vs-MT5 evidence are still missing",
            "blocking_condition": "SR0001 cannot close until mandatory MT5 logic parity, MT5 tick, execution divergence, and fold-isolated evidence are recorded",
            "revisit_when": "produce_sc0002_sr0001_mt5_logic_parity_evidence",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_synthesis_status() -> None:
    data = yaml.safe_load(SYNTHESIS_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = "runs/SR0001"
    if "runs/SR0001" not in list(run_index.get("opened_runs") or []):
        run_index["opened_runs"] = list(run_index.get("opened_runs") or []) + ["runs/SR0001"]
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["run_id"] = RUN_ID
    next_candidate["direction"] = "active_sc0002_sr0001_mt5_logic_parity"
    next_candidate["reason"] = "SR0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    SYNTHESIS_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_synthesis_queue_after_proxy() -> None:
    data = yaml.safe_load(SYNTHESIS_QUEUE_PATH.read_text(encoding="ascii"))
    for item in data.get("queue", []):
        if item.get("synthesis_run_id") == RUN_ID:
            item["status"] = "proxy_done"
            item["last_completed_step"] = "produce_sc0002_sr0001_proxy_evidence"
            item["next_action"] = "produce_sc0002_sr0001_mt5_logic_parity_evidence"
    SYNTHESIS_QUEUE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    next_work = data.setdefault("next_work", {})
    completed = list(next_work.get("completed") or [])
    completed_step = "produce_sc0002_sr0001_proxy_evidence"
    if completed_step not in completed:
        completed.append(completed_step)
    next_action = "produce_sc0002_sr0001_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_run"] = "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_synthesis"] = "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis"
    data["active_run"] = "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001"
    data["latest_operation"] = {
        "id": "produce_sc0002_sr0001_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "active_synthesis": "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis",
        "active_run": "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_sc0002_sr0001_mt5_logic_parity_evidence",
        "claim_boundary": {
            "claim_authority": False,
            "selected": False,
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "runtime_probe_completed": False,
            "economics_pass": False,
            "materialization_ready": False,
            "runtime_authority": False,
            "onnx_ready": False,
            "promotion_ready": False,
            "live_ready": False,
        },
    }
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def replace_sc0002_markers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: replace_sc0002_markers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_sc0002_markers(item) for item in value]
    if isinstance(value, str):
        replacements = {
            "campaigns/C0006_liquidity_sweep_reclaim_event_discovery/runs/R0005": (
                "campaigns/SC0002_accumulated_post_sc0001_negative_memory_synthesis/runs/SR0001"
            ),
            "C0006": "SC0002",
            "R0005": "SR0001",
            "c0006_r0005_reclaim_retest_rejection": "sc0002_sr0001_cross_surface_veto_inversion",
            "c0006_r0005": "sc0002_sr0001",
            "liquidity_sweep_reclaim_event_discovery": "accumulated_post_sc0001_negative_memory_synthesis",
            "fold_local_train_only_reclaim_retest_rejection_event_utility": MODEL_FAMILY,
            "reclaim_retest_rejection_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "reclaim_retest_rejection": "cross_surface_veto_inversion",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    print(json.dumps(run_sc0002_sr0001_proxy(write=True), indent=2, sort_keys=True))
