"""SC0004 SR0001 proxy for post-SC0003 mixed-evidence synthesis."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies.common import base
from axiom_rift.proxies.common import sc0004_c0010_loss_memory_source as c10_loss
from axiom_rift.proxies.common import sc0004_c0010_monthly_regime_source as c10_regime
from axiom_rift.proxies.common import sc0004_c0011_invalidation_source as c11_invalidation
from axiom_rift.proxies.common import sc0004_c0011_lifecycle_source as c11_lifecycle
from axiom_rift.proxies.common import sc0004_c0012_auction_source as c12_auction


WORK_UNIT_ID = "SC0004"
RUN_ID = "SR0001"
WORK_UNIT_DIR = PROJECT_ROOT / "campaigns" / "SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis"
RUN_DIR = WORK_UNIT_DIR / "runs" / RUN_ID
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "sc0004_sr0001_proxy_trades.csv"
SUMMARY_ARTIFACT_PATH = RUN_DIR / "artifacts" / "sc0004_sr0001_mixed_evidence_synthesis_summary.json"
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

MODEL_FAMILY = "fold_local_post_sc0003_monthly_lifecycle_auction_synthesis"
LABEL_SHAPE = "auction_rotation_followthrough_conditioned_by_monthly_and_lifecycle_memory"
SELECTION_RULE = "top_fold_local_mixed_evidence_auction_candidates_per_active_day"
SOURCE_INGREDIENT_IDS = (
    "c0010_ig001_monthly_regime_risk_control_negative_memory",
    "c0010_ig002_monthly_loss_memory_abstention_negative_memory",
    "c0011_ig001_setup_lifecycle_phase_timing_negative_memory",
    "c0011_ig002_setup_invalidation_reversal_negative_memory",
    "c0012_ig001_session_auction_rotation_fragile_candidate_evidence",
    "c0012_ig002_session_auction_rotation_robustness_fragility_lesson",
    "c0012_ig003_session_auction_robustness_conditioner_negative_memory",
    "c0012_ig004_session_auction_transition_hazard_negative_memory",
)
SCORE_COMPONENT_NAMES = (
    "auction_rotation_base_score",
    "monthly_regime_support",
    "monthly_loss_memory_penalty",
    "setup_lifecycle_support",
    "setup_invalidation_penalty",
    "auction_spread_pressure_penalty",
)
AUCTION_WEIGHT = 0.58
MONTHLY_REGIME_WEIGHT = 0.22
MONTHLY_LOSS_MEMORY_PENALTY_WEIGHT = 0.20
LIFECYCLE_WEIGHT = 0.28
INVALIDATION_PENALTY_WEIGHT = 0.18
SPREAD_PRESSURE_PENALTY_WEIGHT = 0.12
CONTRADICTION_PENALTY = 0.18


def run_sc0004_sr0001_proxy(write: bool = True) -> dict[str, object]:
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
        return c12_auction.read_trade_artifact(TRADE_ARTIFACT_PATH)
    return build_proxy_run_result().trades


def build_proxy_run_result() -> base.ProxyRunResult:
    bars = base.load_bars(BASE_FRAME)
    windows = base.load_windows(ROLLING_WINDOWS)
    ranges = [bar.high - bar.low for bar in bars]
    range_average = base.previous_rolling_average(ranges, base.LOOKBACK_RANGE_BARS)
    short_range_average = base.previous_rolling_average(ranges, base.SHORT_RANGE_BARS)
    auction_context = c12_auction.build_context(bars)
    lifecycle_range_series = c11_lifecycle.build_range_series(bars)
    trades: list[base.Trade] = []
    fold_models: list[dict[str, object]] = []
    state_distributions: dict[str, dict[str, float | int | None]] = {}
    candidates_by_fold: dict[str, dict[str, int]] = {}

    for fold_id in sorted(fold_id for fold_id, split in windows.items() if {"train_is", "test_oos"} <= set(split)):
        split = windows[fold_id]
        auction_train = c12_auction.build_candidates(bars, auction_context, split["train_is"], fold_id, True)
        auction_model = c12_auction.fit_linear_auction_model(auction_train, fold_id)
        auction_test = c12_auction.build_candidates(bars, auction_context, split["test_oos"], fold_id, False)
        auction_scored = c12_auction.score_candidates(auction_test, auction_model)
        auction_selected = base.select_daily_candidates(auction_scored)

        monthly_train = c10_regime.build_candidates(
            bars, range_average, short_range_average, split["train_is"], fold_id, True
        )
        monthly_model = c10_regime.fit_linear_edge_model(monthly_train, fold_id)
        monthly_test = c10_regime.build_candidates(
            bars, range_average, short_range_average, split["test_oos"], fold_id, False
        )
        monthly_scored = c10_regime.score_candidates(monthly_test, monthly_model)

        loss_memory_train = c10_loss.build_candidates(
            bars, range_average, short_range_average, split["train_is"], fold_id, True
        )
        loss_memory_model = c10_loss.fit_linear_edge_model(loss_memory_train, fold_id)
        loss_memory_test = c10_loss.build_candidates(
            bars, range_average, short_range_average, split["test_oos"], fold_id, False
        )
        loss_memory_scored = c10_loss.score_candidates(loss_memory_test, loss_memory_model)

        lifecycle_train = c11_lifecycle.build_candidates(
            bars, lifecycle_range_series, split["train_is"], fold_id, True
        )
        lifecycle_model = c11_lifecycle.fit_linear_edge_model(lifecycle_train, fold_id)
        lifecycle_test = c11_lifecycle.build_candidates(
            bars, lifecycle_range_series, split["test_oos"], fold_id, False
        )
        lifecycle_scored = c11_lifecycle.score_candidates(lifecycle_test, lifecycle_model)

        invalidation_train = c11_invalidation.build_candidates(
            bars, lifecycle_range_series, split["train_is"], fold_id, True
        )
        invalidation_model = c11_invalidation.fit_linear_edge_model(invalidation_train, fold_id)
        invalidation_test = c11_invalidation.build_candidates(
            bars, lifecycle_range_series, split["test_oos"], fold_id, False
        )
        invalidation_scored = c11_invalidation.score_candidates(invalidation_test, invalidation_model)

        synthesis_context = build_synthesis_context(
            auction_scored,
            monthly_scored,
            loss_memory_scored,
            lifecycle_scored,
            invalidation_scored,
        )
        synthesized_candidates = synthesize_candidates(auction_selected, synthesis_context)
        selected = base.select_daily_candidates(synthesized_candidates)
        fold_trades = base.simulate_trades(bars, auction_context["range_48"], selected, split["test_oos"])
        trades.extend(fold_trades)

        fold_models.append(
            {
                "fold_id": fold_id,
                "model_family": MODEL_FAMILY,
                "source_models": {
                    "auction_rotation": c12_auction.linear_model_summary(auction_model),
                    "monthly_regime_memory": c10_regime.linear_model_summary(monthly_model),
                    "monthly_loss_memory": c10_loss.linear_model_summary(loss_memory_model),
                    "setup_lifecycle_memory": c11_lifecycle.linear_model_summary(lifecycle_model),
                    "setup_invalidation_memory": c11_invalidation.linear_model_summary(invalidation_model),
                },
                "score_component_names": list(SCORE_COMPONENT_NAMES),
                "label_shape": LABEL_SHAPE,
                "model_selected": False,
            }
        )
        state_distributions[fold_id] = synthesis_distribution(
            auction_selected,
            synthesized_candidates,
            selected,
            synthesis_context,
        )
        candidates_by_fold[fold_id] = {
            "auction_train_candidate_count": len(auction_train),
            "auction_test_candidate_count": len(auction_test),
            "auction_selected_candidate_count": len(auction_selected),
            "monthly_train_candidate_count": len(monthly_train),
            "monthly_loss_memory_train_candidate_count": len(loss_memory_train),
            "lifecycle_train_candidate_count": len(lifecycle_train),
            "invalidation_train_candidate_count": len(invalidation_train),
            "synthesized_candidate_count": len(synthesized_candidates),
            "synthesized_eligible_candidate_count": sum(
                1 for candidate in synthesized_candidates if candidate.score is not None
            ),
            "selected_candidate_count": len(selected),
            "feature_count_declared_exploratory": (
                len(c12_auction.FEATURE_NAMES)
                + len(c10_regime.FEATURE_NAMES)
                + len(c10_loss.FEATURE_NAMES)
                + len(c11_lifecycle.FEATURE_NAMES)
                + len(c11_invalidation.FEATURE_NAMES)
            ),
        }

    return base.ProxyRunResult(
        trades=sorted(trades, key=lambda trade: (trade.entry_time, trade.fold_id, trade.signal_index)),
        windows=windows,
        fold_models=fold_models,
        state_distributions=state_distributions,
        candidates_by_fold=candidates_by_fold,
    )


def build_synthesis_context(
    auction_scored: list[base.Candidate],
    monthly_scored: list[base.Candidate],
    loss_memory_scored: list[base.Candidate],
    lifecycle_scored: list[base.Candidate],
    invalidation_scored: list[base.Candidate],
) -> dict[str, dict[tuple[int, int], float]]:
    return {
        "auction_z": normalized_score_map(auction_scored),
        "monthly_z": normalized_score_map(monthly_scored),
        "loss_memory_z": normalized_score_map(loss_memory_scored),
        "lifecycle_z": normalized_score_map(lifecycle_scored),
        "invalidation_z": normalized_score_map(invalidation_scored),
        "auction_raw": raw_score_map(auction_scored),
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


def synthesize_candidates(
    candidates: list[base.Candidate],
    context: dict[str, dict[tuple[int, int], float]],
) -> list[base.Candidate]:
    synthesized: list[base.Candidate] = []
    auction_z = context["auction_z"]
    monthly_z = context["monthly_z"]
    loss_memory_z = context["loss_memory_z"]
    lifecycle_z = context["lifecycle_z"]
    invalidation_z = context["invalidation_z"]
    for candidate in candidates:
        key = (candidate.index, candidate.direction)
        auction_score = auction_z.get(key)
        if auction_score is None or candidate.score is None:
            synthesized.append(copy_candidate(candidate, None))
            continue
        monthly_score = monthly_z.get(key, 0.0)
        loss_memory_score = loss_memory_z.get(key, 0.0)
        lifecycle_score = lifecycle_z.get(key, 0.0)
        invalidation_score = invalidation_z.get(key, 0.0)
        features = auction_feature_map(candidate)
        spread_pressure = features["spread_over_range"]
        monthly_loss_penalty = max(loss_memory_score, 0.0)
        invalidation_penalty = max(invalidation_score, 0.0)
        spread_penalty = max(spread_pressure, 0.0)
        contradiction_penalty = (
            CONTRADICTION_PENALTY if monthly_score < -0.60 and lifecycle_score < -0.60 else 0.0
        )
        score = (
            AUCTION_WEIGHT * auction_score
            + MONTHLY_REGIME_WEIGHT * monthly_score
            + LIFECYCLE_WEIGHT * lifecycle_score
            - MONTHLY_LOSS_MEMORY_PENALTY_WEIGHT * monthly_loss_penalty
            - INVALIDATION_PENALTY_WEIGHT * invalidation_penalty
            - SPREAD_PRESSURE_PENALTY_WEIGHT * spread_penalty
            - contradiction_penalty
        )
        synthesized.append(copy_candidate(candidate, float(score)))
    return synthesized


def auction_feature_map(candidate: base.Candidate) -> dict[str, float]:
    return {name: float(candidate.features[index]) for index, name in enumerate(c12_auction.FEATURE_NAMES)}


def copy_candidate(candidate: base.Candidate, score: float | None) -> base.Candidate:
    side = "long" if candidate.direction > 0 else "short"
    return base.Candidate(
        fold_id=candidate.fold_id,
        index=candidate.index,
        direction=candidate.direction,
        day=candidate.day,
        state_key=f"{side}|monthly_lifecycle_auction_synthesis",
        features=candidate.features,
        label=candidate.label,
        score=score,
    )


def synthesis_distribution(
    auction_selected: list[base.Candidate],
    synthesized: list[base.Candidate],
    selected: list[base.Candidate],
    context: dict[str, dict[tuple[int, int], float]],
) -> dict[str, float | int | None]:
    scores = [candidate.score or 0.0 for candidate in synthesized if candidate.score is not None]
    selected_scores = [candidate.score or 0.0 for candidate in selected]
    monthly_values = list(context["monthly_z"].values())
    loss_memory_values = list(context["loss_memory_z"].values())
    lifecycle_values = list(context["lifecycle_z"].values())
    invalidation_values = list(context["invalidation_z"].values())
    return {
        "auction_selected_count": len(auction_selected),
        "synthesized_candidate_count": len(synthesized),
        "eligible_candidate_count": sum(1 for candidate in synthesized if candidate.score is not None),
        "selected_count": len(selected),
        "score_p10": base.rounded(base.percentile(scores, 0.10)),
        "score_p50": base.rounded(base.percentile(scores, 0.50)),
        "score_p90": base.rounded(base.percentile(scores, 0.90)),
        "selected_score_min": base.rounded(min(selected_scores)) if selected_scores else None,
        "selected_score_max": base.rounded(max(selected_scores)) if selected_scores else None,
        "monthly_z_p50": base.rounded(base.percentile(monthly_values, 0.50)),
        "loss_memory_z_p90": base.rounded(base.percentile(loss_memory_values, 0.90)),
        "lifecycle_z_p50": base.rounded(base.percentile(lifecycle_values, 0.50)),
        "invalidation_z_p90": base.rounded(base.percentile(invalidation_values, 0.90)),
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
    payload["proxy_id"] = "PX-SC0004-SR0001"
    payload["proxy_engine"] = "axiom_rift.proxies.sc0004_sr0001_post_sc0003_mixed_evidence_synthesis"
    payload["proxy_config_path"] = "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/runs/SR0001/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_mixed_evidence_synthesis_fit"
    payload["proxy_artifact_paths"] = [
        "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/runs/SR0001/kpi/proxy.json",
        "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/runs/SR0001/artifacts/sc0004_sr0001_proxy_trades.csv",
        "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/runs/SR0001/artifacts/sc0004_sr0001_mixed_evidence_synthesis_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["mixed_evidence_synthesis_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "model_family": MODEL_FAMILY,
            "state_model": MODEL_FAMILY,
            "label_shape": LABEL_SHAPE,
            "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
            "score_component_names": list(SCORE_COMPONENT_NAMES),
            "base_candidate_surface": "c0012_r0001_session_auction_rotation_fragile_candidate_evidence",
            "monthly_regime_role": "fold_local_support_context_from_c0010_r0001_negative_memory",
            "monthly_loss_memory_role": "fold_local_penalty_context_from_c0010_r0002_negative_memory",
            "setup_lifecycle_role": "fold_local_support_context_from_c0011_r0001_negative_memory",
            "setup_invalidation_role": "fold_local_penalty_context_from_c0011_r0002_negative_memory",
            "selection_rule": SELECTION_RULE,
            "auction_weight": AUCTION_WEIGHT,
            "monthly_regime_weight": MONTHLY_REGIME_WEIGHT,
            "monthly_loss_memory_penalty_weight": MONTHLY_LOSS_MEMORY_PENALTY_WEIGHT,
            "lifecycle_weight": LIFECYCLE_WEIGHT,
            "invalidation_penalty_weight": INVALIDATION_PENALTY_WEIGHT,
            "spread_pressure_penalty_weight": SPREAD_PRESSURE_PENALTY_WEIGHT,
            "contradiction_penalty": CONTRADICTION_PENALTY,
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
            "next_action": "produce_sc0004_sr0001_mt5_logic_parity_evidence",
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
            "base_candidate_surface": "c0012_r0001_session_auction_rotation",
            "mixed_evidence_sources": [
                "c0010_monthly_regime_risk_control_negative_memory",
                "c0010_monthly_loss_memory_abstention_negative_memory",
                "c0011_setup_lifecycle_phase_timing_negative_memory",
                "c0011_setup_invalidation_reversal_negative_memory",
                "c0012_session_auction_rotation_fragile_candidate_evidence",
            ],
            "weights": {
                "auction": AUCTION_WEIGHT,
                "monthly_regime": MONTHLY_REGIME_WEIGHT,
                "monthly_loss_memory_penalty": MONTHLY_LOSS_MEMORY_PENALTY_WEIGHT,
                "lifecycle": LIFECYCLE_WEIGHT,
                "invalidation_penalty": INVALIDATION_PENALTY_WEIGHT,
                "spread_pressure_penalty": SPREAD_PRESSURE_PENALTY_WEIGHT,
                "contradiction_penalty": CONTRADICTION_PENALTY,
            },
            "variant_boundary": "post_sc0003_monthly_lifecycle_auction_synthesis_not_c0012_threshold_cost_buffer_fold_month_stop_target_hold_daily_count_or_retry_nudge",
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
        "schema": "axiom_rift_post_sc0003_mixed_evidence_synthesis_summary_v1",
        "template": False,
        "work_unit_id": WORK_UNIT_ID,
        "synthesis_id": WORK_UNIT_ID,
        "run_id": RUN_ID,
        "created_at_utc": payload["created_at_utc"],
        "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
        "proxy_config": payload["proxy_config"],
        "mixed_evidence_synthesis_profile": profiles["mixed_evidence_synthesis_profile"]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "mixed_evidence_synthesis_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-SC0004-SR0001-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/runs/SR0001/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/ingredient_refs.yaml",
                    "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/synthesis_queue.yaml",
                    "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/runs/SR0001/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-SC0004-SR0001-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/runs/SR0001/artifacts/sc0004_sr0001_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/runs/SR0001/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-SC0004-SR0001-MIXED-EVIDENCE-SYNTHESIS-SUMMARY",
                "mixed_evidence_synthesis_summary_artifact",
                "json",
                "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/runs/SR0001/artifacts/sc0004_sr0001_mixed_evidence_synthesis_summary.json",
                summary_hash,
                ["campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/runs/SR0001/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_sc0004_sr0001_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.sc0004_sr0001_post_sc0003_mixed_evidence_synthesis",
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
    evidence["proxy_trade_artifact"] = "artifacts/sc0004_sr0001_proxy_trades.csv"
    evidence["mixed_evidence_synthesis_summary"] = "artifacts/sc0004_sr0001_mixed_evidence_synthesis_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_sc0004_sr0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/sc0004_sr0001_proxy_trades.csv",
        "artifacts/sc0004_sr0001_mixed_evidence_synthesis_summary.json",
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
            "revisit_when": "produce_sc0004_sr0001_mt5_logic_parity_evidence",
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
    next_candidate["direction"] = "active_sc0004_sr0001_mt5_logic_parity"
    next_candidate["reason"] = "SR0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    SYNTHESIS_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_synthesis_queue_after_proxy() -> None:
    data = yaml.safe_load(SYNTHESIS_QUEUE_PATH.read_text(encoding="ascii"))
    for item in data.get("queue", []):
        if item.get("synthesis_run_id") == RUN_ID:
            item["status"] = "proxy_done"
            item["opened_at_utc"] = item.get("opened_at_utc") or utc_now()
            item["last_completed_step"] = "produce_sc0004_sr0001_proxy_evidence"
            item["next_action"] = "produce_sc0004_sr0001_mt5_logic_parity_evidence"
    SYNTHESIS_QUEUE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    data["project"]["active_synthesis"] = "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis"
    next_work = data.setdefault("next_work", {})
    next_work["synthesis"] = "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis"
    completed = list(next_work.get("completed") or [])
    for item in (
        "open_sc0004_sr0001_mixed_evidence_synthesis_run",
        "produce_sc0004_sr0001_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_sc0004_sr0001_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_synthesis"] = "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis"
    data["active_run"] = "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/runs/SR0001"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_synthesis"] = "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis"
    data["active_run"] = "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/runs/SR0001"
    data["latest_operation"] = {
        "id": "produce_sc0004_sr0001_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/runs/SR0001/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "active_synthesis": "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis",
        "active_run": "campaigns/SC0004_post_sc0003_c0010_c0012_mixed_evidence_synthesis/runs/SR0001",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_sc0004_sr0001_mt5_logic_parity_evidence",
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
            "C0004 R0001": "SC0004 SR0001",
            "C0004": "SC0004",
            "R0001": "SR0001",
            "c0004_r0001_fold_local_state_archetype": "sc0004_sr0001_post_sc0003_mixed_evidence_synthesis",
            "c0004_r0001": "sc0004_sr0001",
            "fold_local_state_archetype_discovery": "post_sc0003_c0010_c0012_mixed_evidence_synthesis",
            "fold_local_train_only_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "mixed_evidence_synthesis_summary",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    print(json.dumps(run_sc0004_sr0001_proxy(write=True), indent=2, sort_keys=True))
