"""C0008 R0003 proxy evidence for structural trap robustness conditioning."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies.common import base
from axiom_rift.proxies.common import structural_trap as r0002


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0008_multi_timeframe_structural_context_discovery" / "runs" / "R0003"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0008_multi_timeframe_structural_context_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0008_r0003_proxy_trades.csv"
ROBUSTNESS_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0008_r0003_structural_trap_robustness_summary.json"
RUN_MANIFEST_PATH = RUN_DIR / "run_manifest.json"
GATE_REPORT_PATH = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE_PATH = RUN_DIR / "artifact_lineage.json"
CLAIM_STATE_PATH = PROJECT_ROOT / "registries" / "claim_state.yaml"
REENTRY_PATH = PROJECT_ROOT / "registries" / "reentry.yaml"

BASE_FRAME = r0002.BASE_FRAME
ROLLING_WINDOWS = r0002.ROLLING_WINDOWS
SplitWindow = r0002.SplitWindow
Trade = r0002.Trade
load_bars = r0002.load_bars
load_windows = r0002.load_windows

MODEL_FAMILY = "fold_local_structural_trap_reversal_robustness_conditioner"
LABEL_SHAPE = "fold_local_robust_positive_minus_fragile_adverse_trap_reversal_quality"
SELECTION_RULE = "top_fold_local_conditioned_robust_trap_reversal_scores_per_active_day"
CONDITIONER_WEIGHT = 0.72
COST_PRESSURE_WEIGHT = 0.45
RANGE_SHOCK_WEIGHT = 0.18

SPREAD_INDEX = r0002.FEATURE_NAMES.index("spread_over_range")
RANGE_EXPANSION_INDEX = r0002.FEATURE_NAMES.index("range_expansion_3_over_36")
OPPOSITE_TREND_INDEX = r0002.FEATURE_NAMES.index("opposite_trend_pressure")
TRAP_RANGE_EXPANSION_INDEX = r0002.FEATURE_NAMES.index("trap_range_expansion")
TRAP_BODY_INDEX = r0002.FEATURE_NAMES.index("trap_body_reversal")
RECLAIM_H1_INDEX = r0002.FEATURE_NAMES.index("reclaim_strength_h1")
RECLAIM_SESSION_INDEX = r0002.FEATURE_NAMES.index("reclaim_strength_session")
TRAP_EXTENSION_INDEXES = tuple(
    r0002.FEATURE_NAMES.index(name)
    for name in (
        "trap_extension_prior_m15",
        "trap_extension_prior_h1",
        "trap_extension_prior_session",
        "trap_extension_prior_day",
    )
)

CONDITIONER_FEATURE_NAMES = tuple(r0002.FEATURE_NAMES) + (
    "base_trap_score",
    "cost_pressure",
    "trap_depth",
    "reclaim_strength",
    "trend_conflict",
    "range_shock",
)


@dataclass(frozen=True)
class RobustnessConditioner:
    fold_id: str
    base_model: r0002.TrapReversalModel
    feature_mean: np.ndarray
    feature_std: np.ndarray
    robust_centroid: np.ndarray
    fragile_centroid: np.ndarray
    feature_weights: np.ndarray
    robust_label_threshold: float
    fragile_label_threshold: float
    robust_label_rate: float
    fragile_label_rate: float
    train_candidate_count: int
    base_score_median: float


def run_c0008_r0003_proxy(write: bool = True) -> dict[str, object]:
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
        return read_trade_artifact(TRADE_ARTIFACT_PATH)
    return build_proxy_run_result().trades


def read_trade_artifact(path: Path) -> list[base.Trade]:
    trades: list[base.Trade] = []
    with path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            trades.append(
                base.Trade(
                    fold_id=row["fold_id"],
                    signal_index=int(row["signal_index"]),
                    entry_time=datetime.strptime(row["entry_time"], base.TIME_FORMAT),
                    exit_time=datetime.strptime(row["exit_time"], base.TIME_FORMAT),
                    direction=int(row["direction"]),
                    score=float(row["score"]),
                    state_key=row["state_key"],
                    entry_price=float(row["entry_price"]),
                    exit_price=float(row["exit_price"]),
                    stop_price=float(row["stop_price"]),
                    target_price=float(row["target_price"]),
                    pnl_points=float(row["pnl_points"]),
                    bars_held=int(row["bars_held"]),
                    exit_reason=row["exit_reason"],
                    mfe_points=float(row["mfe_points"]),
                    mae_points=float(row["mae_points"]),
                    spread_points=float(row["spread_points"]),
                )
            )
    return trades


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
        train_candidates = r0002.build_candidates(
            bars,
            range_average,
            short_range_average,
            split["train_is"],
            fold_id,
            include_labels=True,
        )
        conditioner = fit_robustness_conditioner(train_candidates, fold_id)
        test_candidates = r0002.build_candidates(
            bars,
            range_average,
            short_range_average,
            split["test_oos"],
            fold_id,
            include_labels=False,
        )
        scored_candidates = score_candidates(test_candidates, conditioner)
        selected = base.select_daily_candidates(scored_candidates)
        trades.extend(base.simulate_trades(bars, range_average, selected, split["test_oos"]))
        fold_models.append(conditioner_summary(conditioner))
        state_distributions[fold_id] = score_distribution(scored_candidates, selected, conditioner)
        candidates_by_fold[fold_id] = {
            "train_candidate_count": len(train_candidates),
            "test_candidate_count": len(test_candidates),
            "selected_candidate_count": len(selected),
            "eligible_candidate_count": sum(1 for candidate in scored_candidates if candidate.score is not None),
            "feature_count": len(CONDITIONER_FEATURE_NAMES),
        }
    return base.ProxyRunResult(
        trades=trades,
        windows=windows,
        fold_models=fold_models,
        state_distributions=state_distributions,
        candidates_by_fold=candidates_by_fold,
    )


def fit_robustness_conditioner(candidates: list[base.Candidate], fold_id: str) -> RobustnessConditioner:
    base_model = r0002.fit_trap_reversal_model(candidates, fold_id)
    scored_train = r0002.score_candidates(candidates, base_model)
    labeled = [candidate for candidate in scored_train if candidate.label is not None and candidate.score is not None]
    feature_count = len(CONDITIONER_FEATURE_NAMES)
    if not labeled:
        return RobustnessConditioner(
            fold_id=fold_id,
            base_model=base_model,
            feature_mean=np.zeros(feature_count, dtype=float),
            feature_std=np.ones(feature_count, dtype=float),
            robust_centroid=np.zeros(feature_count, dtype=float),
            fragile_centroid=np.zeros(feature_count, dtype=float),
            feature_weights=np.ones(feature_count, dtype=float),
            robust_label_threshold=0.0,
            fragile_label_threshold=0.0,
            robust_label_rate=0.0,
            fragile_label_rate=0.0,
            train_candidate_count=0,
            base_score_median=0.0,
        )
    matrix = np.asarray([conditioner_features(candidate) for candidate in labeled], dtype=float)
    labels = np.asarray([candidate.label for candidate in labeled if candidate.label is not None], dtype=float)
    adjusted_labels = np.asarray([robustness_adjusted_label(candidate) for candidate in labeled], dtype=float)
    base_scores = np.asarray([candidate.score for candidate in labeled if candidate.score is not None], dtype=float)
    robust_threshold = float(np.quantile(adjusted_labels, 0.72))
    fragile_threshold = float(np.quantile(adjusted_labels, 0.34))
    base_score_median = float(np.median(base_scores))
    robust_mask = (adjusted_labels >= robust_threshold) & (base_scores >= base_score_median)
    fragile_mask = (adjusted_labels <= fragile_threshold) | (labels < r0002.ADVERSE_LABEL_THRESHOLD)
    if not robust_mask.any():
        robust_mask = adjusted_labels >= robust_threshold
    if not fragile_mask.any():
        fragile_mask = adjusted_labels <= fragile_threshold
    feature_mean = matrix.mean(axis=0)
    feature_std = matrix.std(axis=0)
    feature_std[feature_std < 1e-9] = 1.0
    scaled = (matrix - feature_mean) / feature_std
    robust_centroid = scaled[robust_mask].mean(axis=0) if robust_mask.any() else scaled.mean(axis=0)
    fragile_centroid = scaled[fragile_mask].mean(axis=0) if fragile_mask.any() else scaled.mean(axis=0)
    separation = np.abs(robust_centroid - fragile_centroid)
    positive_strength = separation[separation > 0.0]
    if positive_strength.size:
        scale = float(np.median(positive_strength))
        weights = np.sqrt(np.maximum(separation / max(scale, 1e-12), 0.0))
        weights = np.clip(weights, 0.35, 3.0)
        weights = weights / max(float(weights.mean()), 1e-12)
    else:
        weights = np.ones(feature_count, dtype=float)
    return RobustnessConditioner(
        fold_id=fold_id,
        base_model=base_model,
        feature_mean=feature_mean,
        feature_std=feature_std,
        robust_centroid=robust_centroid,
        fragile_centroid=fragile_centroid,
        feature_weights=weights,
        robust_label_threshold=robust_threshold,
        fragile_label_threshold=fragile_threshold,
        robust_label_rate=float(np.mean(robust_mask)),
        fragile_label_rate=float(np.mean(fragile_mask)),
        train_candidate_count=len(labeled),
        base_score_median=base_score_median,
    )


def robustness_adjusted_label(candidate: base.Candidate) -> float:
    if candidate.label is None:
        return 0.0
    features = candidate.features
    cost_pressure = max(float(features[SPREAD_INDEX]), 0.0)
    range_shock = max(float(features[RANGE_EXPANSION_INDEX]) - 1.0, 0.0)
    trend_conflict = max(float(features[OPPOSITE_TREND_INDEX]), 0.0)
    return float(candidate.label) - (1.35 * cost_pressure) - (0.24 * range_shock) - (0.16 * trend_conflict)


def conditioner_features(candidate: base.Candidate) -> tuple[float, ...]:
    features = tuple(float(value) for value in candidate.features)
    base_score = float(candidate.score or 0.0)
    cost_pressure = max(features[SPREAD_INDEX], 0.0)
    trap_depth = max(features[index] for index in TRAP_EXTENSION_INDEXES)
    reclaim_strength = 0.5 * (max(features[RECLAIM_H1_INDEX], 0.0) + max(features[RECLAIM_SESSION_INDEX], 0.0))
    trend_conflict = max(features[OPPOSITE_TREND_INDEX], 0.0)
    range_shock = max(features[RANGE_EXPANSION_INDEX] - 1.0, 0.0) + 0.5 * max(features[TRAP_RANGE_EXPANSION_INDEX], 0.0)
    trap_reversal_body = max(features[TRAP_BODY_INDEX], 0.0)
    return features + (
        base_score,
        cost_pressure,
        trap_depth + 0.25 * trap_reversal_body,
        reclaim_strength,
        trend_conflict,
        range_shock,
    )


def score_candidates(candidates: list[base.Candidate], conditioner: RobustnessConditioner) -> list[base.Candidate]:
    base_scored = r0002.score_candidates(candidates, conditioner.base_model)
    if not base_scored:
        return []
    matrix = np.asarray([conditioner_features(candidate) for candidate in base_scored], dtype=float)
    scaled = (matrix - conditioner.feature_mean) / conditioner.feature_std
    weighted = scaled * conditioner.feature_weights
    robust = conditioner.robust_centroid * conditioner.feature_weights
    fragile = conditioner.fragile_centroid * conditioner.feature_weights
    dist_robust = np.sqrt(((weighted - robust) ** 2).mean(axis=1))
    dist_fragile = np.sqrt(((weighted - fragile) ** 2).mean(axis=1))
    conditioned_scores: list[base.Candidate] = []
    for index, candidate in enumerate(base_scored):
        features = candidate.features
        base_score = float(candidate.score or 0.0)
        cost_pressure = max(float(features[SPREAD_INDEX]), 0.0)
        range_shock = max(float(features[RANGE_EXPANSION_INDEX]) - 1.0, 0.0)
        score = (
            0.58 * base_score
            + CONDITIONER_WEIGHT * float(dist_fragile[index] - dist_robust[index])
            + 0.18 * (conditioner.robust_label_rate - conditioner.fragile_label_rate)
            - COST_PRESSURE_WEIGHT * cost_pressure
            - RANGE_SHOCK_WEIGHT * range_shock
        )
        if not math.isfinite(score):
            score = None  # type: ignore[assignment]
        conditioned_scores.append(r0002.copy_with_score(candidate, score))
    return conditioned_scores


def build_proxy_payload(
    trades: list[base.Trade],
    windows: dict[str, dict[str, base.SplitWindow]],
    fold_models: list[dict[str, object]],
    state_distributions: dict[str, dict[str, float | int | None]],
    candidates_by_fold: dict[str, dict[str, int]],
) -> dict[str, object]:
    payload = replace_run_markers(base.build_proxy_payload(trades, windows, fold_models, state_distributions, candidates_by_fold))
    payload["campaign_id"] = "C0008"
    payload["work_unit_id"] = "C0008"
    payload["run_id"] = "R0003"
    payload["proxy_id"] = "PX-C0008-R0003"
    payload["proxy_engine"] = "axiom_rift.proxies.c0008_r0003_structural_trap_robustness"
    payload["proxy_config_path"] = "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0003/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_structural_trap_robustness_conditioner_fit"
    payload["proxy_artifact_paths"] = [
        "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0003/kpi/proxy.json",
        "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0003/artifacts/c0008_r0003_proxy_trades.csv",
        "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0003/artifacts/c0008_r0003_structural_trap_robustness_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["structural_trap_reversal_robustness_conditioner_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "model_family": MODEL_FAMILY,
            "label_shape": LABEL_SHAPE,
            "feature_count": len(CONDITIONER_FEATURE_NAMES),
            "feature_names": list(CONDITIONER_FEATURE_NAMES),
            "selection_rule": SELECTION_RULE,
            "conditioner_weight": CONDITIONER_WEIGHT,
            "cost_pressure_weight": COST_PRESSURE_WEIGHT,
            "range_shock_weight": RANGE_SHOCK_WEIGHT,
            "fold_models": fold_models,
            "state_distributions": state_distributions,
            "candidates_by_fold": candidates_by_fold,
            "candidate_direction": "dual_direction_structural_trap_reversal_with_robustness_conditioning",
            "model_selected": False,
            "feature_set_selected": False,
            "label_selected": False,
        },
    }
    profiles["mt5_pairing_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "fold_isolated_mt5_closeout_required": True,
            "mt5_logic_parity_required_next": True,
            "mt5_tick_required_after_logic_parity": True,
            "proxy_is_screening_gate_for_mt5": False,
            "weak_proxy_may_skip_mt5": False,
            "proxy_result_may_close_run": False,
            "next_action": "produce_c0008_r0003_mt5_logic_parity_evidence",
        },
    }
    return payload


def proxy_config() -> dict[str, object]:
    config = dict(r0002.proxy_config())
    config.update(
        {
            "state_model": MODEL_FAMILY,
            "label_shape": LABEL_SHAPE,
            "selection_rule": SELECTION_RULE,
            "feature_names": list(CONDITIONER_FEATURE_NAMES),
            "feature_count": len(CONDITIONER_FEATURE_NAMES),
            "conditioner_weight": CONDITIONER_WEIGHT,
            "cost_pressure_weight": COST_PRESSURE_WEIGHT,
            "range_shock_weight": RANGE_SHOCK_WEIGHT,
            "score_interpretation": "higher_score_means_closer_to_fold_local_robust_trap_reversal_and_farther_from_fragile_adverse_conditioner",
            "variant_boundary": "structural_trap_reversal_robustness_conditioner_not_r0002_centroid_threshold_stop_target_hold_session_or_retry_nudge",
        }
    )
    return config


def conditioner_summary(conditioner: RobustnessConditioner) -> dict[str, object]:
    return {
        "fold_id": conditioner.fold_id,
        "model_family": MODEL_FAMILY,
        "feature_names": list(CONDITIONER_FEATURE_NAMES),
        "feature_count": len(CONDITIONER_FEATURE_NAMES),
        "train_candidate_count": conditioner.train_candidate_count,
        "base_score_median": base.rounded(conditioner.base_score_median),
        "robust_label_threshold": base.rounded(conditioner.robust_label_threshold),
        "fragile_label_threshold": base.rounded(conditioner.fragile_label_threshold),
        "robust_label_rate": base.rounded(conditioner.robust_label_rate),
        "fragile_label_rate": base.rounded(conditioner.fragile_label_rate),
        "feature_weights": [base.rounded(float(value)) for value in conditioner.feature_weights],
        "robust_centroid": [base.rounded(float(value)) for value in conditioner.robust_centroid],
        "fragile_centroid": [base.rounded(float(value)) for value in conditioner.fragile_centroid],
        "feature_mean": [base.rounded(float(value)) for value in conditioner.feature_mean],
        "feature_std": [base.rounded(float(value)) for value in conditioner.feature_std],
        "base_trap_model": r0002.trap_model_summary(conditioner.base_model),
        "score_interpretation": "higher_score_means_closer_to_robust_positive_and_farther_from_fragile_adverse_conditioner",
    }


def score_distribution(
    scored: list[base.Candidate],
    selected: list[base.Candidate],
    conditioner: RobustnessConditioner,
) -> dict[str, float | int | None]:
    scores = [candidate.score or 0.0 for candidate in scored if candidate.score is not None]
    selected_scores = [candidate.score or 0.0 for candidate in selected]
    eligible_hits = sum(1 for candidate in scored if candidate.score is not None)
    return {
        "candidate_count": len(scored),
        "eligible_candidate_count": eligible_hits,
        "eligible_candidate_rate": base.rounded(eligible_hits / len(scored)) if scored else None,
        "selected_count": len(selected),
        "train_candidate_count": conditioner.train_candidate_count,
        "score_p10": base.rounded(base.percentile(scores, 0.10)),
        "score_p50": base.rounded(base.percentile(scores, 0.50)),
        "score_p90": base.rounded(base.percentile(scores, 0.90)),
        "selected_score_min": base.rounded(min(selected_scores)) if selected_scores else None,
        "selected_score_max": base.rounded(max(selected_scores)) if selected_scores else None,
        "robust_label_rate": base.rounded(conditioner.robust_label_rate),
        "fragile_label_rate": base.rounded(conditioner.fragile_label_rate),
    }


def write_proxy_evidence(payload: dict[str, object], trades: list[base.Trade]) -> None:
    RUN_DIR.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    RUN_DIR.joinpath("kpi").mkdir(parents=True, exist_ok=True)
    base.write_trade_artifact(trades, TRADE_ARTIFACT_PATH)
    write_summary_artifact(payload, ROBUSTNESS_SUMMARY_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = base.sha256_file(TRADE_ARTIFACT_PATH)
    summary_hash = base.sha256_file(ROBUSTNESS_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = base.sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)


def write_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_structural_trap_robustness_conditioner_summary_v1",
        "template": False,
        "work_unit_id": "C0008",
        "campaign_id": "C0008",
        "run_id": "R0003",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "structural_trap_reversal_robustness_conditioner_profile": profiles[
            "structural_trap_reversal_robustness_conditioner_profile"
        ]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "structural_trap_robustness_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-C0008-R0003-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0003/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0003/run_manifest.json",
                    "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0002/kpi/candidate_robustness_audit.json",
                ],
            ),
            artifact_record(
                "A-C0008-R0003-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0003/artifacts/c0008_r0003_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0003/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0008-R0003-STRUCTURAL-TRAP-ROBUSTNESS-SUMMARY",
                "structural_trap_robustness_summary_artifact",
                "json",
                "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0003/artifacts/c0008_r0003_structural_trap_robustness_summary.json",
                summary_hash,
                ["campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0003/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0008_r0003_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0008_r0003_structural_trap_robustness",
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
    evidence["proxy_kpi"] = "kpi/proxy.json"
    evidence["proxy_trade_artifact"] = "artifacts/c0008_r0003_proxy_trades.csv"
    evidence["structural_trap_robustness_summary"] = "artifacts/c0008_r0003_structural_trap_robustness_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0008_r0003_mt5_logic_parity_evidence"
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "kpi/proxy.json",
        "artifacts/c0008_r0003_proxy_trades.csv",
        "artifacts/c0008_r0003_structural_trap_robustness_summary.json",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["evidence_paths"] = evidence_paths
    data["deferred_with_reason"] = [
        {
            "field": "run_closeout",
            "reason": "proxy evidence is recorded but mandatory MT5 logic parity, tick execution, execution divergence, and fold-isolated evidence are still missing",
            "blocking_condition": "produce_c0008_r0003_mt5_logic_parity_evidence",
            "revisit_when": "after C0008 R0003 MT5 evidence files contain measured results",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_campaign_status() -> None:
    data = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = "runs/R0003"
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["run_id"] = "R0003"
    next_candidate["direction"] = "active_c0008_r0003_mt5_logic_parity"
    next_candidate["reason"] = "R0003 robustness-conditioned proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0008_r0003_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    data = yaml.safe_load(REENTRY_PATH.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = "campaigns/C0008_multi_timeframe_structural_context_discovery"
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = "campaigns/C0008_multi_timeframe_structural_context_discovery"
    completed = list(next_work.get("completed") or [])
    for item in (
        "design_c0008_r0003_structural_trap_reversal_robustness_conditioner_run",
        "open_c0008_r0003_structural_trap_reversal_robustness_conditioner_run",
        "produce_c0008_r0003_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_c0008_r0003_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_run"] = "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0003"
    REENTRY_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0008_multi_timeframe_structural_context_discovery"
    data["active_run"] = "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0003"
    data["latest_operation"] = {
        "id": "produce_c0008_r0003_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0003/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "campaign_status": "active_run_open",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0008_r0003_mt5_logic_parity_evidence",
        "claim_boundary": {
            "claim_authority": False,
            "selected": False,
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "runtime_authority": False,
            "economics_pass": False,
            "onnx_ready": False,
            "promotion_ready": False,
            "live_ready": False,
        },
    }
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def replace_run_markers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: replace_run_markers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_run_markers(item) for item in value]
    if isinstance(value, str):
        replacements = {
            "C0004": "C0008",
            "R0001": "R0003",
            "c0004_r0001_fold_local_state_archetype": "c0008_r0003_structural_trap_robustness",
            "c0004_r0001": "c0008_r0003",
            "fold_local_state_archetype_discovery": "multi_timeframe_structural_context_discovery",
            "fold_local_train_only_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "structural_trap_robustness_summary",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
