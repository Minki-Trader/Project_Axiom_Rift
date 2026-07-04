"""SC0003 SR0001 proxy for cross-family fragile-candidate hardening."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies.common import sc0003_c0007_supervised_edge_source as c7
from axiom_rift.proxies.common import sc0003_c0008_structural_trap_source as c8
from axiom_rift.proxies.common import sc0003_c0009_intrabar_ambiguity_source as c9
from axiom_rift.proxies.common import base


WORK_UNIT_ID = "SC0003"
RUN_ID = "SR0001"
WORK_UNIT_DIR = PROJECT_ROOT / "campaigns" / "SC0003_post_sc0002_mixed_evidence_synthesis"
RUN_DIR = WORK_UNIT_DIR / "runs" / RUN_ID
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "sc0003_sr0001_proxy_trades.csv"
SUMMARY_ARTIFACT_PATH = RUN_DIR / "artifacts" / "sc0003_sr0001_cross_family_hardening_summary.json"
RUN_MANIFEST_PATH = RUN_DIR / "run_manifest.json"
GATE_REPORT_PATH = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE_PATH = RUN_DIR / "artifact_lineage.json"
SYNTHESIS_PATH = WORK_UNIT_DIR / "synthesis.yaml"
SYNTHESIS_QUEUE_PATH = WORK_UNIT_DIR / "synthesis_queue.yaml"
CLAIM_STATE_PATH = PROJECT_ROOT / "registries" / "claim_state.yaml"

BASE_FRAME = base.BASE_FRAME
ROLLING_WINDOWS = base.ROLLING_WINDOWS
TIME_FORMAT = base.TIME_FORMAT
SplitWindow = base.SplitWindow
Trade = base.Trade
load_bars = base.load_bars
load_windows = base.load_windows

MODEL_FAMILY = "fold_local_cross_family_fragile_candidate_hardening"
LABEL_SHAPE = "structural_trap_reversal_hardened_by_supervised_failure_and_execution_friction_vetoes"
SELECTION_RULE = "top_fold_local_hardened_structural_trap_candidates_per_active_day"
SOURCE_INGREDIENT_IDS = (
    "c0007_ig001_fold_local_linear_rank_negative_memory",
    "c0007_ig002_dual_hazard_logistic_negative_memory",
    "c0007_ig003_nonlinear_interaction_negative_memory",
    "c0008_ig001_direct_structural_context_rank_negative_memory",
    "c0008_ig002_structural_trap_reversal_fragile_candidate_evidence",
    "c0008_ig003_structural_trap_robustness_conditioner_negative_memory",
    "c0008_ig004_structural_acceptance_continuation_negative_memory",
    "c0009_ig001_execution_friction_regime_negative_memory",
    "c0009_ig002_execution_degradation_abstention_negative_memory",
    "c0009_ig003_intrabar_ambiguity_avoidance_negative_memory",
    "c0008_ig005_r0002_robustness_fragility_lesson",
)
SCORE_COMPONENT_NAMES = (
    "structural_trap_reversal_base_score",
    "supervised_edge_failure_veto_pressure",
    "execution_friction_survival_score",
    "intrabar_ambiguity_penalty",
    "spread_pressure_penalty",
)
MAX_SPREAD_OVER_RANGE = 0.58
MIN_EXECUTION_FRICTION_Z = -1.35
MAX_SUPERVISED_ONLY_PRESSURE = 1.70


def run_sc0003_sr0001_proxy(write: bool = True) -> dict[str, object]:
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
        return c8.read_trade_artifact(TRADE_ARTIFACT_PATH)
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
        c8_train = c8.build_candidates(bars, range_average, short_range_average, split["train_is"], fold_id, True)
        c8_model = c8.fit_trap_reversal_model(c8_train, fold_id)
        c8_test = c8.build_candidates(bars, range_average, short_range_average, split["test_oos"], fold_id, False)
        c8_scored = c8.score_candidates(c8_test, c8_model)
        structural_selected = base.select_daily_candidates(c8_scored)

        c7_train = c7.build_candidates(bars, range_average, short_range_average, split["train_is"], fold_id, True)
        c7_model = c7.fit_linear_edge_model(c7_train, fold_id)
        c7_test = c7.build_candidates(bars, range_average, short_range_average, split["test_oos"], fold_id, False)
        c7_scored = c7.score_candidates(c7_test, c7_model)

        c9_train = c9.build_candidates(bars, range_average, short_range_average, split["train_is"], fold_id, True)
        c9_model = c9.fit_linear_edge_model(c9_train, fold_id)
        c9_test = c9.build_candidates(bars, range_average, short_range_average, split["test_oos"], fold_id, False)
        c9_scored = c9.score_candidates(c9_test, c9_model)

        hardening_context = build_hardening_context(c8_scored, c7_scored, c9_scored)
        hardened_candidates = harden_candidates(structural_selected, hardening_context)
        selected = base.select_daily_candidates(hardened_candidates)
        fold_trades = base.simulate_trades(bars, range_average, selected, split["test_oos"])
        trades.extend(fold_trades)

        fold_models.append(
            {
                "fold_id": fold_id,
                "model_family": MODEL_FAMILY,
                "source_models": {
                    "structural_trap_reversal": c8.trap_model_summary(c8_model),
                    "supervised_edge_failure_memory": c7.linear_model_summary(c7_model),
                    "execution_friction_memory": c9.linear_model_summary(c9_model),
                },
                "score_component_names": list(SCORE_COMPONENT_NAMES),
                "label_shape": LABEL_SHAPE,
                "model_selected": False,
            }
        )
        state_distributions[fold_id] = hardening_distribution(
            structural_selected,
            hardened_candidates,
            selected,
            hardening_context,
        )
        candidates_by_fold[fold_id] = {
            "structural_train_candidate_count": len(c8_train),
            "structural_test_candidate_count": len(c8_test),
            "structural_selected_candidate_count": len(structural_selected),
            "supervised_train_candidate_count": len(c7_train),
            "execution_friction_train_candidate_count": len(c9_train),
            "hardened_candidate_count": len(hardened_candidates),
            "hardened_eligible_candidate_count": sum(1 for candidate in hardened_candidates if candidate.score is not None),
            "selected_candidate_count": len(selected),
            "feature_count_declared_exploratory": len(c8.FEATURE_NAMES) + len(c7.FEATURE_NAMES) + len(c9.FEATURE_NAMES),
        }

    return base.ProxyRunResult(
        trades=sorted(trades, key=lambda trade: (trade.entry_time, trade.fold_id, trade.signal_index)),
        windows=windows,
        fold_models=fold_models,
        state_distributions=state_distributions,
        candidates_by_fold=candidates_by_fold,
    )


def build_hardening_context(
    structural_scored: list[base.Candidate],
    supervised_scored: list[base.Candidate],
    friction_scored: list[base.Candidate],
) -> dict[str, dict[tuple[int, int], float]]:
    return {
        "structural_z": normalized_score_map(structural_scored),
        "supervised_z": normalized_score_map(supervised_scored),
        "friction_z": normalized_score_map(friction_scored),
        "friction_raw": raw_score_map(friction_scored),
    }


def raw_score_map(candidates: list[base.Candidate]) -> dict[tuple[int, int], float]:
    return {
        (candidate.index, candidate.direction): float(candidate.score)
        for candidate in candidates
        if candidate.score is not None
    }


def normalized_score_map(candidates: list[base.Candidate]) -> dict[tuple[int, int], float]:
    scores = [float(candidate.score) for candidate in candidates if candidate.score is not None]
    if not scores:
        return {}
    mean = float(np.mean(scores))
    std = float(np.std(scores))
    if std <= 1e-12:
        std = 1.0
    return {
        (candidate.index, candidate.direction): float((float(candidate.score) - mean) / std)
        for candidate in candidates
        if candidate.score is not None
    }


def harden_candidates(
    candidates: list[base.Candidate],
    context: dict[str, dict[tuple[int, int], float]],
) -> list[base.Candidate]:
    hardened: list[base.Candidate] = []
    structural_z = context["structural_z"]
    supervised_z = context["supervised_z"]
    friction_z = context["friction_z"]
    for candidate in candidates:
        key = (candidate.index, candidate.direction)
        structural_score = structural_z.get(key)
        if structural_score is None or candidate.score is None:
            hardened.append(copy_candidate(candidate, None))
            continue
        supervised_score = supervised_z.get(key, 0.0)
        friction_score = friction_z.get(key, -0.85)
        features = c8_feature_map(candidate)
        spread_pressure = features["spread_over_range"]
        supervised_only_pressure = max(supervised_score - structural_score, 0.0)
        intrabar_penalty = max(-friction_score, 0.0)
        if spread_pressure > MAX_SPREAD_OVER_RANGE:
            hardened.append(copy_candidate(candidate, None))
            continue
        if friction_score < MIN_EXECUTION_FRICTION_Z:
            hardened.append(copy_candidate(candidate, None))
            continue
        if supervised_only_pressure > MAX_SUPERVISED_ONLY_PRESSURE and structural_score < 0.35:
            hardened.append(copy_candidate(candidate, None))
            continue
        score = (
            0.62 * structural_score
            + 0.24 * friction_score
            - 0.18 * supervised_only_pressure
            - 0.14 * intrabar_penalty
            - 0.16 * spread_pressure
            + 0.07 * max(features["reclaim_strength_h1"], 0.0)
            + 0.05 * max(features["reversal_wick_fraction"], 0.0)
        )
        hardened.append(copy_candidate(candidate, float(score)))
    return hardened


def c8_feature_map(candidate: base.Candidate) -> dict[str, float]:
    return {name: float(candidate.features[index]) for index, name in enumerate(c8.FEATURE_NAMES)}


def copy_candidate(candidate: base.Candidate, score: float | None) -> base.Candidate:
    side = "long" if candidate.direction > 0 else "short"
    return base.Candidate(
        fold_id=candidate.fold_id,
        index=candidate.index,
        direction=candidate.direction,
        day=candidate.day,
        state_key=f"{side}|cross_family_fragile_candidate_hardening",
        features=candidate.features,
        label=candidate.label,
        score=score,
    )


def hardening_distribution(
    structural_selected: list[base.Candidate],
    hardened: list[base.Candidate],
    selected: list[base.Candidate],
    context: dict[str, dict[tuple[int, int], float]],
) -> dict[str, float | int | None]:
    scores = [candidate.score or 0.0 for candidate in hardened if candidate.score is not None]
    selected_scores = [candidate.score or 0.0 for candidate in selected]
    friction_values = list(context["friction_z"].values())
    supervised_values = list(context["supervised_z"].values())
    return {
        "structural_selected_count": len(structural_selected),
        "hardened_candidate_count": len(hardened),
        "eligible_candidate_count": sum(1 for candidate in hardened if candidate.score is not None),
        "selected_count": len(selected),
        "score_p10": base.rounded(base.percentile(scores, 0.10)),
        "score_p50": base.rounded(base.percentile(scores, 0.50)),
        "score_p90": base.rounded(base.percentile(scores, 0.90)),
        "selected_score_min": base.rounded(min(selected_scores)) if selected_scores else None,
        "selected_score_max": base.rounded(max(selected_scores)) if selected_scores else None,
        "friction_z_p10": base.rounded(base.percentile(friction_values, 0.10)),
        "friction_z_p50": base.rounded(base.percentile(friction_values, 0.50)),
        "supervised_z_p90": base.rounded(base.percentile(supervised_values, 0.90)),
    }


def build_proxy_payload(
    trades: list[base.Trade],
    windows: dict[str, dict[str, base.SplitWindow]],
    fold_models: list[dict[str, object]],
    state_distributions: dict[str, dict[str, float | int | None]],
    candidates_by_fold: dict[str, dict[str, int]],
) -> dict[str, object]:
    payload = replace_base_markers(base.build_proxy_payload(trades, windows, fold_models, state_distributions, candidates_by_fold))
    payload["campaign_id"] = None
    payload["work_unit_id"] = WORK_UNIT_ID
    payload["synthesis_id_when_applicable"] = WORK_UNIT_ID
    payload["run_id"] = RUN_ID
    payload["proxy_id"] = "PX-SC0003-SR0001"
    payload["proxy_engine"] = "axiom_rift.proxies.sc0003_sr0001_cross_family_fragile_candidate_hardening"
    payload["proxy_config_path"] = "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/runs/SR0001/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_cross_family_hardening_fit"
    payload["proxy_artifact_paths"] = [
        "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/runs/SR0001/kpi/proxy.json",
        "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/runs/SR0001/artifacts/sc0003_sr0001_proxy_trades.csv",
        "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/runs/SR0001/artifacts/sc0003_sr0001_cross_family_hardening_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["cross_family_hardening_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "model_family": MODEL_FAMILY,
            "state_model": MODEL_FAMILY,
            "label_shape": LABEL_SHAPE,
            "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
            "score_component_names": list(SCORE_COMPONENT_NAMES),
            "base_candidate_surface": "c0008_r0002_structural_trap_reversal_fragile_candidate_evidence",
            "supervised_edge_role": "failure_memory_veto_pressure_not_primary_generator",
            "execution_friction_role": "survival_veto_context_not_primary_generator",
            "selection_rule": SELECTION_RULE,
            "max_spread_over_range": MAX_SPREAD_OVER_RANGE,
            "min_execution_friction_z": MIN_EXECUTION_FRICTION_Z,
            "max_supervised_only_pressure": MAX_SUPERVISED_ONLY_PRESSURE,
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
            "next_action": "produce_sc0003_sr0001_mt5_logic_parity_evidence",
        },
    }
    return payload


def proxy_config() -> dict[str, object]:
    config = dict(base.proxy_config())
    config.update(
        {
            "model_family": MODEL_FAMILY,
            "label_shape": LABEL_SHAPE,
            "selection_rule": SELECTION_RULE,
            "score_component_names": list(SCORE_COMPONENT_NAMES),
            "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
            "base_candidate_surface": "c0008_r0002_structural_trap_reversal",
            "cross_family_sources": [
                "c0007_fold_local_supervised_edge_negative_memory",
                "c0009_intrabar_ambiguity_and_execution_friction_negative_memory",
            ],
            "max_spread_over_range": MAX_SPREAD_OVER_RANGE,
            "min_execution_friction_z": MIN_EXECUTION_FRICTION_Z,
            "max_supervised_only_pressure": MAX_SUPERVISED_ONLY_PRESSURE,
            "variant_boundary": "cross_family_fragile_candidate_hardening_not_structural_filter_score_floor_session_stop_target_hold_daily_count_or_retry_nudge",
            "fixed_lot_policy": "early_discovery_fixed_lot_no_equity_percent_sizing_rescue",
        }
    )
    return config


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
        "schema": "axiom_rift_cross_family_fragile_candidate_hardening_summary_v1",
        "template": False,
        "work_unit_id": WORK_UNIT_ID,
        "synthesis_id": WORK_UNIT_ID,
        "run_id": RUN_ID,
        "created_at_utc": payload["created_at_utc"],
        "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
        "proxy_config": payload["proxy_config"],
        "cross_family_hardening_profile": profiles["cross_family_hardening_profile"]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "cross_family_hardening_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-SC0003-SR0001-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/runs/SR0001/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/ingredient_refs.yaml",
                    "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/synthesis_queue.yaml",
                    "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/runs/SR0001/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-SC0003-SR0001-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/runs/SR0001/artifacts/sc0003_sr0001_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/runs/SR0001/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-SC0003-SR0001-CROSS-FAMILY-HARDENING-SUMMARY",
                "cross_family_hardening_summary_artifact",
                "json",
                "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/runs/SR0001/artifacts/sc0003_sr0001_cross_family_hardening_summary.json",
                summary_hash,
                ["campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/runs/SR0001/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_sc0003_sr0001_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.sc0003_sr0001_cross_family_fragile_candidate_hardening",
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
    evidence["proxy_trade_artifact"] = "artifacts/sc0003_sr0001_proxy_trades.csv"
    evidence["cross_family_hardening_summary"] = "artifacts/sc0003_sr0001_cross_family_hardening_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_sc0003_sr0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/sc0003_sr0001_proxy_trades.csv",
        "artifacts/sc0003_sr0001_cross_family_hardening_summary.json",
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
            "revisit_when": "produce_sc0003_sr0001_mt5_logic_parity_evidence",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_synthesis_status() -> None:
    data = yaml.safe_load(SYNTHESIS_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = "runs/SR0001"
    opened = list(run_index.get("opened_runs") or [])
    if "runs/SR0001" not in opened:
        opened.append("runs/SR0001")
    run_index["opened_runs"] = opened
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["run_id"] = RUN_ID
    next_candidate["direction"] = "active_sc0003_sr0001_mt5_logic_parity"
    next_candidate["reason"] = "SR0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    SYNTHESIS_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_synthesis_queue_after_proxy() -> None:
    data = yaml.safe_load(SYNTHESIS_QUEUE_PATH.read_text(encoding="ascii"))
    for item in data.get("queue", []):
        if item.get("synthesis_run_id") == RUN_ID:
            item["status"] = "proxy_done"
            item["opened_at_utc"] = item.get("opened_at_utc") or utc_now()
            item["last_completed_step"] = "produce_sc0003_sr0001_proxy_evidence"
            item["next_action"] = "produce_sc0003_sr0001_mt5_logic_parity_evidence"
    SYNTHESIS_QUEUE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    data["project"]["active_synthesis"] = "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis"
    next_work = data.setdefault("next_work", {})
    next_work["synthesis"] = "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis"
    completed = list(next_work.get("completed") or [])
    for item in (
        "open_sc0003_sr0001_mixed_evidence_synthesis_run",
        "produce_sc0003_sr0001_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_sc0003_sr0001_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_synthesis"] = "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis"
    data["active_run"] = "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/runs/SR0001"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_synthesis"] = "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis"
    data["active_run"] = "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/runs/SR0001"
    data["latest_operation"] = {
        "id": "produce_sc0003_sr0001_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/runs/SR0001/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "active_synthesis": "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis",
        "active_run": "campaigns/SC0003_post_sc0002_mixed_evidence_synthesis/runs/SR0001",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_sc0003_sr0001_mt5_logic_parity_evidence",
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


def replace_base_markers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: replace_base_markers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_base_markers(item) for item in value]
    if isinstance(value, str):
        replacements = {
            "C0004 R0001": "SC0003 SR0001",
            "C0004": "SC0003",
            "R0001": "SR0001",
            "c0004_r0001_fold_local_state_archetype": "sc0003_sr0001_cross_family_fragile_candidate_hardening",
            "c0004_r0001": "sc0003_sr0001",
            "fold_local_state_archetype_discovery": "post_sc0002_mixed_evidence_synthesis",
            "fold_local_train_only_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "cross_family_hardening_summary",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    print(json.dumps(run_sc0003_sr0001_proxy(write=True), indent=2, sort_keys=True))
