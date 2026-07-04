"""C0007 R0003 proxy evidence for nonlinear interaction edge ensemble supervised edge discovery."""

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
from sklearn.ensemble import ExtraTreesClassifier

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies.common import base
from axiom_rift.proxies.common import supervised_edge as linear_base


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0007_fold_local_supervised_edge_discovery" / "runs" / "R0003"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0007_fold_local_supervised_edge_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0007_r0003_proxy_trades.csv"
TREE_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0007_r0003_nonlinear_interaction_edge_ensemble_summary.json"
RUN_MANIFEST_PATH = RUN_DIR / "run_manifest.json"
GATE_REPORT_PATH = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE_PATH = RUN_DIR / "artifact_lineage.json"
CLAIM_STATE_PATH = PROJECT_ROOT / "registries" / "claim_state.yaml"
BASE_FRAME = base.BASE_FRAME
ROLLING_WINDOWS = base.ROLLING_WINDOWS
SplitWindow = base.SplitWindow
Trade = base.Trade
load_bars = base.load_bars
load_windows = base.load_windows

INTERACTION_FEATURE_NAMES = (
    "trend_x_range_position",
    "momentum_x_close_location",
    "reversal_x_adverse_wick",
    "compression_x_body",
    "range_acceleration_x_trend",
    "spread_x_adverse_wick",
    "range_ratio_x_body",
    "drawdown_x_reversal",
    "session_sin_x_momentum",
    "session_cos_x_reversal",
    "positive_body_minus_adverse_wick",
)
FEATURE_NAMES = tuple(linear_base.FEATURE_NAMES) + INTERACTION_FEATURE_NAMES
MODEL_FAMILY = "fold_local_nonlinear_interaction_edge_ensemble"
LABEL_SHAPE = "target_positive_probability_minus_adverse_path_hazard"
POSITIVE_LABEL_THRESHOLD = 0.10
ADVERSE_LABEL_THRESHOLD = -0.45
SELECTION_RULE = "top_fold_local_nonlinear_interaction_edge_scores_per_active_day"
TREE_ESTIMATOR_COUNT = 72
TREE_MAX_DEPTH = 6
TREE_MIN_SAMPLES_LEAF = 96
TREE_MAX_FEATURES = "sqrt"


@dataclass(frozen=True)
class TreeEdgeModel:
    fold_id: str
    feature_mean: np.ndarray
    feature_std: np.ndarray
    positive_classifier: ExtraTreesClassifier | None
    adverse_classifier: ExtraTreesClassifier | None
    train_candidate_count: int
    positive_label_rate: float
    adverse_label_rate: float
    label_mean: float
    label_std: float


def run_c0007_r0003_proxy(write: bool = True) -> dict[str, object]:
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
        train_candidates = build_candidates(
            bars,
            range_average,
            short_range_average,
            split["train_is"],
            fold_id,
            include_labels=True,
        )
        model = fit_tree_edge_model(train_candidates, fold_id)
        test_candidates = build_candidates(
            bars,
            range_average,
            short_range_average,
            split["test_oos"],
            fold_id,
            include_labels=False,
        )
        scored_candidates = score_candidates(test_candidates, model)
        selected = base.select_daily_candidates(scored_candidates)
        trades.extend(base.simulate_trades(bars, range_average, selected, split["test_oos"]))
        fold_models.append(tree_model_summary(model))
        state_distributions[fold_id] = score_distribution(scored_candidates, selected, model)
        candidates_by_fold[fold_id] = {
            "train_candidate_count": len(train_candidates),
            "test_candidate_count": len(test_candidates),
            "selected_candidate_count": len(selected),
            "eligible_candidate_count": sum(1 for candidate in scored_candidates if candidate.score is not None),
            "feature_count": len(FEATURE_NAMES),
        }
    return base.ProxyRunResult(
        trades=trades,
        windows=windows,
        fold_models=fold_models,
        state_distributions=state_distributions,
        candidates_by_fold=candidates_by_fold,
    )


def build_candidates(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    window: base.SplitWindow,
    fold_id: str,
    include_labels: bool,
) -> list[base.Candidate]:
    start_index = max(
        base.first_index_at_or_after(bars, window.start),
        base.LOOKBACK_RANGE_BARS,
        base.SHORT_RANGE_BARS,
        base.TREND_BARS,
        base.POSITION_BARS,
        base.MOMENTUM_BARS,
        96,
        3,
    )
    end_index = min(base.last_index_at_or_before(bars, window.end), len(bars) - base.LABEL_HORIZON_BARS - 2)
    candidates: list[base.Candidate] = []
    for index in range(start_index, end_index + 1):
        if not base.in_core_session(bars[index].time):
            continue
        average_range = range_average[index]
        short_average_range = short_range_average[index]
        if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
            continue
        for direction in (1, -1):
            features = nonlinear_interaction_features(bars, range_average, short_range_average, index, direction)
            if features is None:
                continue
            label = linear_base.supervised_path_label(bars, range_average, index, direction) if include_labels else None
            side = "long" if direction > 0 else "short"
            candidates.append(
                base.Candidate(
                    fold_id=fold_id,
                    index=index,
                    direction=direction,
                    day=bars[index].time.strftime("%Y-%m-%d"),
                    state_key=f"{side}|nonlinear_interaction_edge_ensemble",
                    features=features,
                    label=label,
                )
            )
    return candidates


def nonlinear_interaction_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    index: int,
    direction: int,
) -> tuple[float, ...] | None:
    base_features = linear_base.supervised_features(bars, range_average, short_range_average, index, direction)
    if base_features is None:
        return None
    values = dict(zip(linear_base.FEATURE_NAMES, base_features, strict=True))
    interactions = (
        values["directional_trend_consistency_18"] * values["directional_range_position_36"],
        values["directional_ret_6_over_range"] * values["directional_close_location"],
        values["directional_reversal_pressure_6"] * values["adverse_wick_fraction"],
        values["compression_release_pressure"] * values["directional_body_fraction"],
        values["range_acceleration_3_over_36"] * values["directional_trend_consistency_18"],
        values["spread_over_range"] * values["adverse_wick_fraction"],
        values["range_ratio_1"] * values["directional_body_fraction"],
        values["prior_directional_drawdown_6"] * values["directional_reversal_pressure_6"],
        values["session_sin"] * values["directional_ret_6_over_range"],
        values["session_cos"] * values["directional_reversal_pressure_6"],
        values["directional_body_fraction"] - values["adverse_wick_fraction"],
    )
    return tuple(base_features) + interactions


def fit_tree_edge_model(candidates: list[base.Candidate], fold_id: str) -> TreeEdgeModel:
    labeled = [candidate for candidate in candidates if candidate.label is not None]
    feature_count = len(FEATURE_NAMES)
    if not labeled:
        return TreeEdgeModel(
            fold_id=fold_id,
            feature_mean=np.zeros(feature_count, dtype=float),
            feature_std=np.ones(feature_count, dtype=float),
            positive_classifier=None,
            adverse_classifier=None,
            train_candidate_count=0,
            positive_label_rate=0.0,
            adverse_label_rate=0.0,
            label_mean=0.0,
            label_std=0.0,
        )
    feature_matrix = np.asarray([candidate.features for candidate in labeled], dtype=float)
    labels = np.asarray([candidate.label for candidate in labeled if candidate.label is not None], dtype=float)
    feature_mean = feature_matrix.mean(axis=0)
    feature_std = feature_matrix.std(axis=0)
    feature_std[feature_std < 1e-9] = 1.0
    scaled = (feature_matrix - feature_mean) / feature_std
    positive_target = (labels > POSITIVE_LABEL_THRESHOLD).astype(int)
    adverse_target = (labels < ADVERSE_LABEL_THRESHOLD).astype(int)
    return TreeEdgeModel(
        fold_id=fold_id,
        feature_mean=feature_mean,
        feature_std=feature_std,
        positive_classifier=fit_binary_classifier(scaled, positive_target),
        adverse_classifier=fit_binary_classifier(scaled, adverse_target),
        train_candidate_count=len(labeled),
        positive_label_rate=float(np.mean(positive_target)),
        adverse_label_rate=float(np.mean(adverse_target)),
        label_mean=float(labels.mean()),
        label_std=float(labels.std()),
    )


def fit_binary_classifier(features: np.ndarray, target: np.ndarray) -> ExtraTreesClassifier | None:
    if features.size == 0 or target.size == 0 or len(set(target.tolist())) < 2:
        return None
    classifier = ExtraTreesClassifier(
        n_estimators=TREE_ESTIMATOR_COUNT,
        max_depth=TREE_MAX_DEPTH,
        min_samples_leaf=TREE_MIN_SAMPLES_LEAF,
        max_features=TREE_MAX_FEATURES,
        class_weight="balanced",
        random_state=7003,
        n_jobs=1,
    )
    classifier.fit(features, target)
    return classifier


def score_candidates(candidates: list[base.Candidate], model: TreeEdgeModel) -> list[base.Candidate]:
    if not candidates:
        return []
    features = np.asarray([candidate.features for candidate in candidates], dtype=float)
    scaled = (features - model.feature_mean) / model.feature_std
    positive_probability = class_probability(model.positive_classifier, scaled, model.positive_label_rate)
    adverse_probability = class_probability(model.adverse_classifier, scaled, model.adverse_label_rate)
    positive_lift = positive_probability - model.positive_label_rate
    adverse_lift = adverse_probability - model.adverse_label_rate
    scores = positive_probability - 0.95 * adverse_probability + 0.08 * positive_lift - 0.05 * adverse_lift
    scored: list[base.Candidate] = []
    for index, candidate in enumerate(candidates):
        score = float(scores[index])
        if not math.isfinite(score):
            score = None  # type: ignore[assignment]
        scored.append(copy_with_score(candidate, score))
    return scored


def class_probability(classifier: ExtraTreesClassifier | None, features: np.ndarray, fallback: float) -> np.ndarray:
    if classifier is None:
        return np.full(features.shape[0], fallback, dtype=float)
    return classifier.predict_proba(features)[:, 1]


def copy_with_score(candidate: base.Candidate, score: float | None) -> base.Candidate:
    return base.Candidate(
        fold_id=candidate.fold_id,
        index=candidate.index,
        direction=candidate.direction,
        day=candidate.day,
        state_key=candidate.state_key,
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
    payload = replace_run_markers(linear_base.build_proxy_payload(trades, windows, fold_models, state_distributions, candidates_by_fold))
    payload["campaign_id"] = "C0007"
    payload["work_unit_id"] = "C0007"
    payload["run_id"] = "R0003"
    payload["proxy_id"] = "PX-C0007-R0003"
    payload["proxy_engine"] = "axiom_rift.proxies.c0007_r0003_nonlinear_interaction_edge_ensemble"
    payload["proxy_config_path"] = "campaigns/C0007_fold_local_supervised_edge_discovery/runs/R0003/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_nonlinear_interaction_edge_ensemble_fit"
    payload["proxy_artifact_paths"] = [
        "campaigns/C0007_fold_local_supervised_edge_discovery/runs/R0003/kpi/proxy.json",
        "campaigns/C0007_fold_local_supervised_edge_discovery/runs/R0003/artifacts/c0007_r0003_proxy_trades.csv",
        "campaigns/C0007_fold_local_supervised_edge_discovery/runs/R0003/artifacts/c0007_r0003_nonlinear_interaction_edge_ensemble_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("supervised_edge_profile", None)  # type: ignore[union-attr]
    profiles["nonlinear_interaction_edge_ensemble_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "model_family": MODEL_FAMILY,
            "feature_count": len(FEATURE_NAMES),
            "feature_names": list(FEATURE_NAMES),
            "base_feature_count": len(linear_base.FEATURE_NAMES),
            "interaction_feature_names": list(INTERACTION_FEATURE_NAMES),
            "label_shape": LABEL_SHAPE,
            "positive_label_threshold": POSITIVE_LABEL_THRESHOLD,
            "adverse_label_threshold": ADVERSE_LABEL_THRESHOLD,
            "fold_models": fold_models,
            "state_distributions": state_distributions,
            "candidates_by_fold": candidates_by_fold,
            "selection_rule": SELECTION_RULE,
            "candidate_direction": "dual_direction_long_and_short_per_closed_bar",
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
            "next_action": "produce_c0007_r0003_mt5_logic_parity_evidence",
        },
    }
    return payload


def proxy_config() -> dict[str, object]:
    config = dict(linear_base.proxy_config())
    config.update(
        {
            "state_model": MODEL_FAMILY,
            "label_shape": LABEL_SHAPE,
            "selection_rule": SELECTION_RULE,
            "feature_names": list(FEATURE_NAMES),
            "feature_count": len(FEATURE_NAMES),
            "base_feature_count": len(linear_base.FEATURE_NAMES),
            "interaction_feature_names": list(INTERACTION_FEATURE_NAMES),
            "positive_label_threshold": POSITIVE_LABEL_THRESHOLD,
            "adverse_label_threshold": ADVERSE_LABEL_THRESHOLD,
            "tree_estimator_count": TREE_ESTIMATOR_COUNT,
            "tree_max_depth": TREE_MAX_DEPTH,
            "tree_min_samples_leaf": TREE_MIN_SAMPLES_LEAF,
            "tree_max_features": TREE_MAX_FEATURES,
            "tree_class_weight": "balanced",
            "score_interpretation": "higher_score_means_positive_target_probability_minus_adverse_path_hazard",
            "variant_boundary": "nonlinear_interaction_edge_ensemble_not_r0001_linear_rank_r0002_logistic_or_parameter_retry",
        }
    )
    return config


def tree_model_summary(model: TreeEdgeModel) -> dict[str, object]:
    return {
        "fold_id": model.fold_id,
        "model_family": MODEL_FAMILY,
        "feature_names": list(FEATURE_NAMES),
        "feature_count": len(FEATURE_NAMES),
        "train_candidate_count": model.train_candidate_count,
        "positive_label_rate": base.rounded(model.positive_label_rate),
        "adverse_label_rate": base.rounded(model.adverse_label_rate),
        "label_mean": base.rounded(model.label_mean),
        "label_std": base.rounded(model.label_std),
        "positive_classifier_present": model.positive_classifier is not None,
        "adverse_classifier_present": model.adverse_classifier is not None,
        "tree_estimator_count": TREE_ESTIMATOR_COUNT,
        "tree_max_depth": TREE_MAX_DEPTH,
        "tree_min_samples_leaf": TREE_MIN_SAMPLES_LEAF,
        "tree_max_features": TREE_MAX_FEATURES,
        "positive_top_feature_importances": top_feature_importances(model.positive_classifier),
        "adverse_top_feature_importances": top_feature_importances(model.adverse_classifier),
        "score_interpretation": "higher_score_means_positive_target_probability_minus_adverse_path_hazard",
    }


def top_feature_importances(classifier: ExtraTreesClassifier | None) -> list[dict[str, object]]:
    if classifier is None:
        return []
    importances = classifier.feature_importances_
    ranked = sorted(enumerate(importances), key=lambda item: float(item[1]), reverse=True)
    return [
        {"feature": FEATURE_NAMES[index], "importance": base.rounded(float(value))}
        for index, value in ranked[:15]
    ]


def score_distribution(
    scored: list[base.Candidate],
    selected: list[base.Candidate],
    model: TreeEdgeModel,
) -> dict[str, float | int | None]:
    scores = [candidate.score or 0.0 for candidate in scored if candidate.score is not None]
    selected_scores = [candidate.score or 0.0 for candidate in selected]
    eligible_hits = sum(1 for candidate in scored if candidate.score is not None)
    return {
        "candidate_count": len(scored),
        "eligible_candidate_count": eligible_hits,
        "eligible_candidate_rate": base.rounded(eligible_hits / len(scored)) if scored else None,
        "selected_count": len(selected),
        "train_candidate_count": model.train_candidate_count,
        "positive_label_rate": base.rounded(model.positive_label_rate),
        "adverse_label_rate": base.rounded(model.adverse_label_rate),
        "score_p10": base.rounded(base.percentile(scores, 0.10)),
        "score_p50": base.rounded(base.percentile(scores, 0.50)),
        "score_p90": base.rounded(base.percentile(scores, 0.90)),
        "selected_score_min": base.rounded(min(selected_scores)) if selected_scores else None,
        "selected_score_max": base.rounded(max(selected_scores)) if selected_scores else None,
    }


def write_proxy_evidence(payload: dict[str, object], trades: list[base.Trade]) -> None:
    RUN_DIR.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    RUN_DIR.joinpath("kpi").mkdir(parents=True, exist_ok=True)
    base.write_trade_artifact(trades, TRADE_ARTIFACT_PATH)
    write_tree_summary_artifact(payload, TREE_SUMMARY_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = base.sha256_file(TRADE_ARTIFACT_PATH)
    summary_hash = base.sha256_file(TREE_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = base.sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)


def write_tree_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_nonlinear_interaction_edge_ensemble_summary_v1",
        "template": False,
        "work_unit_id": "C0007",
        "campaign_id": "C0007",
        "run_id": "R0003",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "nonlinear_interaction_edge_ensemble_profile": profiles["nonlinear_interaction_edge_ensemble_profile"]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "nonlinear_interaction_edge_ensemble_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-C0007-R0003-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0007_fold_local_supervised_edge_discovery/runs/R0003/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0007_fold_local_supervised_edge_discovery/runs/R0003/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-C0007-R0003-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0007_fold_local_supervised_edge_discovery/runs/R0003/artifacts/c0007_r0003_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0007_fold_local_supervised_edge_discovery/runs/R0003/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0007-R0003-NONLINEAR-INTERACTION-EDGE-ENSEMBLE-SUMMARY",
                "nonlinear_interaction_edge_ensemble_summary_artifact",
                "json",
                "campaigns/C0007_fold_local_supervised_edge_discovery/runs/R0003/artifacts/c0007_r0003_nonlinear_interaction_edge_ensemble_summary.json",
                summary_hash,
                ["campaigns/C0007_fold_local_supervised_edge_discovery/runs/R0003/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0007_r0003_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0007_r0003_nonlinear_interaction_edge_ensemble",
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
    evidence["proxy_trade_artifact"] = "artifacts/c0007_r0003_proxy_trades.csv"
    evidence["nonlinear_interaction_edge_ensemble_summary"] = "artifacts/c0007_r0003_nonlinear_interaction_edge_ensemble_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0007_r0003_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0007_r0003_proxy_trades.csv",
        "artifacts/c0007_r0003_nonlinear_interaction_edge_ensemble_summary.json",
        "kpi/proxy.json",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["evidence_paths"] = evidence_paths
    data["deferred_with_reason"] = [
        {
            "field": "decision",
            "reason": "proxy evidence is recorded but MT5 and proxy-vs-MT5 evidence are still missing",
            "blocking_condition": "R0003 cannot close until mandatory MT5 logic parity, MT5 tick, execution divergence, and fold-isolated evidence are recorded",
            "revisit_when": "after C0007 R0003 MT5 evidence files contain measured results",
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
    next_candidate["direction"] = "active_c0007_r0003_mt5_logic_parity"
    next_candidate["reason"] = "R0003 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0007_r0003_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = "campaigns/C0007_fold_local_supervised_edge_discovery"
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = "campaigns/C0007_fold_local_supervised_edge_discovery"
    completed = list(next_work.get("completed") or [])
    for item in (
        "open_c0007_r0003_nonlinear_interaction_edge_ensemble_run",
        "produce_c0007_r0003_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_c0007_r0003_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_run"] = "campaigns/C0007_fold_local_supervised_edge_discovery/runs/R0003"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0007_fold_local_supervised_edge_discovery"
    data["active_run"] = "campaigns/C0007_fold_local_supervised_edge_discovery/runs/R0003"
    data["latest_operation"] = {
        "id": "produce_c0007_r0003_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0007_fold_local_supervised_edge_discovery/runs/R0003/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0007_r0003_mt5_logic_parity_evidence",
        "claim_boundary": {
            "claim_authority": False,
            "selected": False,
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "runtime_authority": False,
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
            "R0001": "R0003",
            "r0001": "r0003",
            "PX-C0007-R0001": "PX-C0007-R0003",
            "c0007_r0001_fold_local_supervised_edge": "c0007_r0003_nonlinear_interaction_edge_ensemble",
            "c0007_r0001": "c0007_r0003",
            "fold_local_direct_supervised_linear_rank_edge": MODEL_FAMILY,
            "directional_target_before_stop_path_quality_cost_adjusted": LABEL_SHAPE,
            "supervised_edge_summary": "nonlinear_interaction_edge_ensemble_summary",
            "direct_fold_local_supervised_edge_rank": "positive_target_probability_minus_adverse_path_hazard",
            "supervised_linear_rank": "nonlinear_interaction_edge_ensemble",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
