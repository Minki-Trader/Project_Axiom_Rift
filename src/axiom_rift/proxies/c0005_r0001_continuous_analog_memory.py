"""C0005 R0001 proxy evidence for continuous analog-memory entries."""

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
from sklearn.neighbors import NearestNeighbors

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies.common import base


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0005_continuous_analog_memory_discovery" / "runs" / "R0001"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0005_continuous_analog_memory_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0005_r0001_proxy_trades.csv"
ANALOG_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0005_r0001_analog_memory_summary.json"
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

FEATURE_NAMES = (
    "directional_ret_3_over_range",
    "directional_ret_6_over_range",
    "directional_ret_18_over_range",
    "range_ratio_1",
    "range_ratio_12_over_48",
    "directional_range_position_36",
    "directional_body_fraction",
    "directional_close_location",
    "session_sin",
    "session_cos",
    "spread_over_range",
)
MODEL_FAMILY = "fold_local_continuous_knn_analog_memory"
LABEL_SHAPE = "directional_target_before_stop_plus_forward_path_quality"
ANALOG_NEIGHBOR_COUNT = 45
MAX_ANALOG_DISTANCE = 4.75
MIN_ANALOG_POSITIVE_LIFT = -0.015


@dataclass(frozen=True)
class AnalogModel:
    fold_id: str
    feature_mean: np.ndarray
    feature_std: np.ndarray
    labels: np.ndarray
    neighbors: NearestNeighbors | None
    neighbor_count: int
    train_candidate_count: int
    global_mean: float
    global_positive_rate: float


def run_c0005_r0001_proxy(write: bool = True) -> dict[str, object]:
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
        model = fit_analog_model(train_candidates, fold_id)
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
        fold_models.append(analog_model_summary(model))
        state_distributions[fold_id] = analog_distribution(scored_candidates, selected, model)
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
            features = continuous_features(bars, range_average, short_range_average, index, direction)
            if features is None:
                continue
            label = base.candidate_label(bars, range_average, index, direction) if include_labels else None
            side = "long" if direction > 0 else "short"
            candidates.append(
                base.Candidate(
                    fold_id=fold_id,
                    index=index,
                    direction=direction,
                    day=bars[index].time.strftime("%Y-%m-%d"),
                    state_key=f"{side}|continuous_analog_memory",
                    features=features,
                    label=label,
                )
            )
    return candidates


def continuous_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    index: int,
    direction: int,
) -> tuple[float, ...] | None:
    average_range = range_average[index]
    short_average_range = short_range_average[index]
    if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
        return None
    bar = bars[index]
    bar_range = max(bar.high - bar.low, 0.0)
    if bar_range <= 0:
        return None
    range_position = base.directional_range_position(bars, index, direction)
    if range_position is None:
        return None
    ret_3 = direction * (bar.close - bars[index - 3].close) / average_range
    ret_6 = direction * (bar.close - bars[index - base.MOMENTUM_BARS].close) / average_range
    ret_18 = direction * (bar.close - bars[index - base.TREND_BARS].close) / average_range
    range_ratio_1 = bar_range / average_range
    range_ratio_12 = short_average_range / average_range
    body_fraction = direction * (bar.close - bar.open) / bar_range
    close_location = (bar.close - bar.low) / bar_range
    directional_close_location = close_location if direction > 0 else 1.0 - close_location
    minute_fraction = base.minute_of_day(bar.time) / (24.0 * 60.0)
    session_sin = math.sin(2.0 * math.pi * minute_fraction)
    session_cos = math.cos(2.0 * math.pi * minute_fraction)
    spread_over_range = bar.spread_points / average_range
    return (
        ret_3,
        ret_6,
        ret_18,
        range_ratio_1,
        range_ratio_12,
        range_position,
        body_fraction,
        directional_close_location,
        session_sin,
        session_cos,
        spread_over_range,
    )


def fit_analog_model(candidates: list[base.Candidate], fold_id: str) -> AnalogModel:
    labeled = [candidate for candidate in candidates if candidate.label is not None]
    if not labeled:
        zeros = np.zeros(len(FEATURE_NAMES), dtype=float)
        ones = np.ones(len(FEATURE_NAMES), dtype=float)
        return AnalogModel(fold_id, zeros, ones, np.array([], dtype=float), None, 0, 0, 0.0, 0.0)
    feature_matrix = np.asarray([candidate.features for candidate in labeled], dtype=float)
    labels = np.asarray([candidate.label for candidate in labeled if candidate.label is not None], dtype=float)
    feature_mean = feature_matrix.mean(axis=0)
    feature_std = feature_matrix.std(axis=0)
    feature_std[feature_std < 1e-9] = 1.0
    scaled = (feature_matrix - feature_mean) / feature_std
    neighbor_count = min(ANALOG_NEIGHBOR_COUNT, len(labeled))
    neighbors = NearestNeighbors(n_neighbors=neighbor_count, algorithm="auto", metric="minkowski")
    neighbors.fit(scaled)
    return AnalogModel(
        fold_id=fold_id,
        feature_mean=feature_mean,
        feature_std=feature_std,
        labels=labels,
        neighbors=neighbors,
        neighbor_count=neighbor_count,
        train_candidate_count=len(labeled),
        global_mean=float(labels.mean()),
        global_positive_rate=float(np.mean(labels > 0.0)),
    )


def score_candidates(candidates: list[base.Candidate], model: AnalogModel) -> list[base.Candidate]:
    if model.neighbors is None or not candidates:
        return [copy_with_score(candidate, None) for candidate in candidates]
    features = np.asarray([candidate.features for candidate in candidates], dtype=float)
    scaled = (features - model.feature_mean) / model.feature_std
    distances, indices = model.neighbors.kneighbors(scaled)
    neighbor_labels = model.labels[indices]
    local_mean = neighbor_labels.mean(axis=1)
    local_std = neighbor_labels.std(axis=1)
    local_positive_rate = (neighbor_labels > 0.0).mean(axis=1)
    mean_distance = distances.mean(axis=1)
    scores = (
        local_mean
        + 0.24 * (local_positive_rate - model.global_positive_rate)
        - 0.08 * local_std
        - 0.025 * mean_distance
    )
    scored: list[base.Candidate] = []
    for index, candidate in enumerate(candidates):
        if mean_distance[index] > MAX_ANALOG_DISTANCE:
            score = None
        elif local_mean[index] <= model.global_mean:
            score = None
        elif local_positive_rate[index] - model.global_positive_rate < MIN_ANALOG_POSITIVE_LIFT:
            score = None
        else:
            score = float(scores[index])
        scored.append(copy_with_score(candidate, score))
    return scored


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
    payload = replace_run_markers(base.build_proxy_payload(trades, windows, fold_models, state_distributions, candidates_by_fold))
    payload["campaign_id"] = "C0005"
    payload["work_unit_id"] = "C0005"
    payload["run_id"] = "R0001"
    payload["proxy_id"] = "PX-C0005-R0001"
    payload["proxy_engine"] = "axiom_rift.proxies.c0005_r0001_continuous_analog_memory"
    payload["proxy_config_path"] = "campaigns/C0005_continuous_analog_memory_discovery/runs/R0001/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_continuous_analog_fit"
    payload["proxy_artifact_paths"] = [
        "campaigns/C0005_continuous_analog_memory_discovery/runs/R0001/kpi/proxy.json",
        "campaigns/C0005_continuous_analog_memory_discovery/runs/R0001/artifacts/c0005_r0001_proxy_trades.csv",
        "campaigns/C0005_continuous_analog_memory_discovery/runs/R0001/artifacts/c0005_r0001_analog_memory_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["analog_memory_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "model_family": MODEL_FAMILY,
            "feature_count": len(FEATURE_NAMES),
            "feature_names": list(FEATURE_NAMES),
            "label_shape": LABEL_SHAPE,
            "neighbor_count": ANALOG_NEIGHBOR_COUNT,
            "max_analog_distance": MAX_ANALOG_DISTANCE,
            "min_analog_positive_lift": MIN_ANALOG_POSITIVE_LIFT,
            "fold_models": fold_models,
            "state_distributions": state_distributions,
            "candidates_by_fold": candidates_by_fold,
            "selection_rule": "top_fold_local_continuous_analog_scores_per_active_day",
            "model_selected": False,
            "feature_set_selected": False,
            "label_selected": False,
        },
    }
    return payload


def proxy_config() -> dict[str, object]:
    config = dict(base.proxy_config())
    config.update(
        {
            "state_model": MODEL_FAMILY,
            "label_shape": LABEL_SHAPE,
            "selection_rule": "top_fold_local_continuous_analog_scores_per_active_day",
            "feature_names": list(FEATURE_NAMES),
            "feature_count": len(FEATURE_NAMES),
            "analog_neighbor_count": ANALOG_NEIGHBOR_COUNT,
            "max_analog_distance": MAX_ANALOG_DISTANCE,
            "min_analog_positive_lift": MIN_ANALOG_POSITIVE_LIFT,
            "score_interpretation": "higher_score_means_stronger_local_train_analog_forward_outcome",
            "variant_boundary": "continuous_analog_memory_not_state_archetype_or_threshold_nudge",
        }
    )
    return config


def analog_model_summary(model: AnalogModel) -> dict[str, object]:
    return {
        "fold_id": model.fold_id,
        "model_family": MODEL_FAMILY,
        "feature_names": list(FEATURE_NAMES),
        "feature_count": len(FEATURE_NAMES),
        "train_candidate_count": model.train_candidate_count,
        "neighbor_count": model.neighbor_count,
        "global_mean": base.rounded(model.global_mean),
        "global_positive_rate": base.rounded(model.global_positive_rate),
        "feature_mean": [base.rounded(float(value)) for value in model.feature_mean],
        "feature_std": [base.rounded(float(value)) for value in model.feature_std],
        "score_interpretation": "higher_score_means_stronger_local_train_analog_forward_outcome",
    }


def analog_distribution(
    scored: list[base.Candidate],
    selected: list[base.Candidate],
    model: AnalogModel,
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
    write_analog_summary_artifact(payload, ANALOG_SUMMARY_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = base.sha256_file(TRADE_ARTIFACT_PATH)
    summary_hash = base.sha256_file(ANALOG_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = base.sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)


def write_analog_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_continuous_analog_memory_summary_v1",
        "template": False,
        "work_unit_id": "C0005",
        "campaign_id": "C0005",
        "run_id": "R0001",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "analog_memory_profile": profiles["analog_memory_profile"]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "analog_memory_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-C0005-R0001-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0005_continuous_analog_memory_discovery/runs/R0001/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0005_continuous_analog_memory_discovery/runs/R0001/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-C0005-R0001-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0005_continuous_analog_memory_discovery/runs/R0001/artifacts/c0005_r0001_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0005_continuous_analog_memory_discovery/runs/R0001/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0005-R0001-ANALOG-MEMORY-SUMMARY",
                "analog_memory_summary_artifact",
                "json",
                "campaigns/C0005_continuous_analog_memory_discovery/runs/R0001/artifacts/c0005_r0001_analog_memory_summary.json",
                summary_hash,
                ["campaigns/C0005_continuous_analog_memory_discovery/runs/R0001/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0005_r0001_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0005_r0001_continuous_analog_memory",
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
    evidence["proxy_trade_artifact"] = "artifacts/c0005_r0001_proxy_trades.csv"
    evidence["analog_memory_summary"] = "artifacts/c0005_r0001_analog_memory_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0005_r0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0005_r0001_proxy_trades.csv",
        "artifacts/c0005_r0001_analog_memory_summary.json",
        "kpi/proxy.json",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["evidence_paths"] = evidence_paths
    data["deferred_with_reason"] = [
        {
            "field": "decision",
            "reason": "proxy evidence is recorded but MT5 and proxy-vs-MT5 evidence are still missing",
            "blocking_condition": "R0001 cannot close until mandatory MT5 logic parity, MT5 tick, execution divergence, and fold-isolated evidence are recorded",
            "revisit_when": "after C0005 R0001 MT5 evidence files contain measured results",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_campaign_status() -> None:
    data = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = "runs/R0001"
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["run_id"] = "R0001"
    next_candidate["direction"] = "active_r0001_mt5_logic_parity"
    next_candidate["reason"] = "R0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0005_r0001_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = "campaigns/C0005_continuous_analog_memory_discovery"
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = "campaigns/C0005_continuous_analog_memory_discovery"
    completed = list(next_work.get("completed") or [])
    if "produce_c0005_r0001_proxy_evidence" not in completed:
        completed.append("produce_c0005_r0001_proxy_evidence")
    next_action = "produce_c0005_r0001_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_run"] = "campaigns/C0005_continuous_analog_memory_discovery/runs/R0001"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0005_continuous_analog_memory_discovery"
    data["active_run"] = "campaigns/C0005_continuous_analog_memory_discovery/runs/R0001"
    data["latest_operation"] = {
        "id": "produce_c0005_r0001_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0005_continuous_analog_memory_discovery/runs/R0001/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0005_r0001_mt5_logic_parity_evidence",
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
            "C0004": "C0005",
            "R0004": "R0001",
            "c0004_r0001_fold_local_state_archetype": "c0005_r0001_continuous_analog_memory",
            "c0004_r0001": "c0005_r0001",
            "fold_local_state_archetype_discovery": "continuous_analog_memory_discovery",
            "fold_local_train_only_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
