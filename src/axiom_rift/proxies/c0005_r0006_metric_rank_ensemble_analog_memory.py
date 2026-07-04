"""C0005 R0006 proxy evidence for metric-rank ensemble analog-memory entries."""

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


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0005_continuous_analog_memory_discovery" / "runs" / "R0006"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0005_continuous_analog_memory_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0005_r0006_proxy_trades.csv"
ANALOG_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0005_r0006_analog_memory_summary.json"
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
    "directional_ret_2_over_range",
    "directional_ret_3_over_range",
    "directional_ret_6_over_range",
    "directional_ret_9_over_range",
    "directional_ret_12_over_range",
    "directional_ret_18_over_range",
    "directional_reversal_pressure_6",
    "directional_trend_consistency_18",
    "range_ratio_1",
    "range_ratio_3_over_12",
    "range_ratio_12_over_48",
    "range_ratio_36_over_96",
    "range_acceleration_3_over_12",
    "compression_release_pressure",
    "directional_range_position_36",
    "directional_body_fraction",
    "directional_close_location",
    "favorable_wick_fraction",
    "adverse_wick_fraction",
    "prior_directional_drawdown_6",
    "session_sin",
    "session_cos",
    "spread_over_range",
)
MODEL_FAMILY = "fold_local_supervised_metric_rank_ensemble_analog_memory"
LABEL_SHAPE = "continuous_directional_favorable_path_rank_target"
ANALOG_NEIGHBOR_COUNT = 96
INNER_NEIGHBOR_COUNT = 40
MAX_ANALOG_DISTANCE = 12.0
POSITIVE_LABEL_THRESHOLD = 0.12
ADVERSE_LABEL_THRESHOLD = -0.45
METRIC_WEIGHT_FLOOR = 0.35
METRIC_WEIGHT_CEILING = 2.20
ELIGIBILITY_FILTER = "distance_only_no_rank_gate"
RANK_COMPONENT_NAMES = (
    "weighted_local_edge_rank",
    "positive_minus_adverse_rate_rank",
    "tail_quality_rank",
    "temporal_stability_rank",
    "metric_similarity_rank",
)


@dataclass(frozen=True)
class AnalogModel:
    fold_id: str
    feature_mean: np.ndarray
    feature_std: np.ndarray
    labels: np.ndarray
    binary_labels: np.ndarray
    train_indices: np.ndarray
    feature_weights: np.ndarray
    neighbors: NearestNeighbors | None
    neighbor_count: int
    train_candidate_count: int
    global_mean: float
    global_recent_mean: float
    global_positive_rate: float
    global_adverse_rate: float


def run_c0005_r0006_proxy(write: bool = True) -> dict[str, object]:
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
            features = continuous_features(bars, range_average, short_range_average, index, direction)
            if features is None:
                continue
            label = metric_rank_ensemble_analog_memory_label(bars, range_average, index, direction) if include_labels else None
            side = "long" if direction > 0 else "short"
            candidates.append(
                base.Candidate(
                    fold_id=fold_id,
                    index=index,
                    direction=direction,
                    day=bars[index].time.strftime("%Y-%m-%d"),
                    state_key=f"{side}|metric_rank_ensemble_analog_memory",
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
    ret_2 = direction * (bar.close - bars[index - 2].close) / average_range
    ret_3 = direction * (bar.close - bars[index - 3].close) / average_range
    ret_6_raw = direction * (bar.close - bars[index - base.MOMENTUM_BARS].close) / average_range
    ret_6 = ret_6_raw
    ret_9 = direction * (bar.close - bars[index - 9].close) / average_range
    ret_12 = direction * (bar.close - bars[index - 12].close) / average_range
    ret_18 = direction * (bar.close - bars[index - base.TREND_BARS].close) / average_range
    reversal_pressure = -ret_6_raw * (1.0 - range_position)
    directional_steps = [
        direction * (bars[offset].close - bars[offset - 1].close)
        for offset in range(index - base.TREND_BARS + 1, index + 1)
    ]
    trend_consistency = sum(1.0 if value > 0 else -1.0 if value < 0 else 0.0 for value in directional_steps) / len(directional_steps)
    range_ratio_1 = bar_range / average_range
    range_ratio_12 = short_average_range / average_range
    range_3 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 2, index + 1)) / 3.0
    range_ratio_3 = range_3 / max(short_average_range, 1e-9)
    range_36 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 35, index + 1)) / 36.0
    range_96 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 95, index + 1)) / 96.0
    range_ratio_36 = range_36 / max(range_96, 1e-9)
    range_acceleration = range_3 / max(range_36, 1e-9)
    compression_release_pressure = range_ratio_1 - range_ratio_12
    body_fraction = direction * (bar.close - bar.open) / bar_range
    close_location = (bar.close - bar.low) / bar_range
    directional_close_location = close_location if direction > 0 else 1.0 - close_location
    upper_wick = bar.high - max(bar.open, bar.close)
    lower_wick = min(bar.open, bar.close) - bar.low
    favorable_wick = lower_wick if direction > 0 else upper_wick
    adverse_wick = upper_wick if direction > 0 else lower_wick
    prior_directional_drawdown = max(
        0.0,
        max(direction * (bars[offset].close - bar.close) for offset in range(index - 6, index + 1)),
    ) / average_range
    minute_fraction = base.minute_of_day(bar.time) / (24.0 * 60.0)
    session_sin = math.sin(2.0 * math.pi * minute_fraction)
    session_cos = math.cos(2.0 * math.pi * minute_fraction)
    spread_over_range = bar.spread_points / average_range
    return (
        ret_2,
        ret_3,
        ret_6,
        ret_9,
        ret_12,
        ret_18,
        reversal_pressure,
        trend_consistency,
        range_ratio_1,
        range_ratio_3,
        range_ratio_12,
        range_ratio_36,
        range_acceleration,
        compression_release_pressure,
        range_position,
        body_fraction,
        directional_close_location,
        favorable_wick / bar_range,
        adverse_wick / bar_range,
        prior_directional_drawdown,
        session_sin,
        session_cos,
        spread_over_range,
    )


def metric_rank_ensemble_analog_memory_label(
    bars: list[base.Bar],
    range_average: list[float | None],
    index: int,
    direction: int,
) -> float | None:
    entry_index = index + 1
    exit_index = min(index + base.LABEL_HORIZON_BARS, len(bars) - 1)
    average_range = range_average[index]
    if average_range is None or average_range <= 0 or entry_index >= exit_index:
        return None
    entry = bars[entry_index].open
    path = bars[entry_index : exit_index + 1]
    stop_distance = base.STOP_RANGE_MULTIPLE * average_range
    target_distance = base.TARGET_RANGE_MULTIPLE * average_range
    stop_price = entry - direction * stop_distance
    target_price = entry + direction * target_distance
    first_hit = 0.0
    event_bar = len(path)
    if direction > 0:
        mfe = max(bar.high - entry for bar in path)
        mae = max(entry - bar.low for bar in path)
        terminal = path[-1].close - entry
        aligned_close_count = sum(1 for bar in path if bar.close >= entry)
        for offset, bar in enumerate(path, start=1):
            hit_stop = bar.low <= stop_price
            hit_target = bar.high >= target_price
            if hit_stop:
                first_hit = -1.0
                event_bar = offset
                break
            if hit_target:
                first_hit = 1.0
                event_bar = offset
                break
    else:
        mfe = max(entry - bar.low for bar in path)
        mae = max(bar.high - entry for bar in path)
        terminal = entry - path[-1].close
        aligned_close_count = sum(1 for bar in path if bar.close <= entry)
        for offset, bar in enumerate(path, start=1):
            hit_stop = bar.high >= stop_price
            hit_target = bar.low <= target_price
            if hit_stop:
                first_hit = -1.0
                event_bar = offset
                break
            if hit_target:
                first_hit = 1.0
                event_bar = offset
                break
    favorable = mfe / average_range
    adverse = mae / average_range
    terminal_norm = terminal / average_range
    path_alignment = aligned_close_count / len(path)
    target_speed = (len(path) - event_bar + 1) / len(path) if first_hit > 0.0 else 0.0
    stop_speed = (len(path) - event_bar + 1) / len(path) if first_hit < 0.0 else 0.0
    adverse_tail = max(0.0, (mae / max(stop_distance, 1e-9)) - 0.62)
    giveback = max(0.0, favorable - max(terminal_norm, 0.0))
    path_alignment_edge = path_alignment - 0.5
    spread_norm = bars[entry_index].spread_points / average_range
    return (
        0.95 * first_hit
        + 0.38 * target_speed
        - 0.30 * stop_speed
        + 0.26 * favorable
        - 0.38 * adverse
        - 1.12 * adverse_tail
        - 0.24 * giveback
        + 0.22 * terminal_norm
        + 0.18 * path_alignment_edge
        - spread_norm
    )


def fit_analog_model(candidates: list[base.Candidate], fold_id: str) -> AnalogModel:
    labeled = [candidate for candidate in candidates if candidate.label is not None]
    if not labeled:
        zeros = np.zeros(len(FEATURE_NAMES), dtype=float)
        ones = np.ones(len(FEATURE_NAMES), dtype=float)
        return AnalogModel(
            fold_id=fold_id,
            feature_mean=zeros,
            feature_std=ones,
            labels=np.array([], dtype=float),
            binary_labels=np.array([], dtype=int),
            train_indices=np.array([], dtype=float),
            feature_weights=ones,
            neighbors=None,
            neighbor_count=0,
            train_candidate_count=0,
            global_mean=0.0,
            global_recent_mean=0.0,
            global_positive_rate=0.0,
            global_adverse_rate=0.0,
        )
    feature_matrix = np.asarray([candidate.features for candidate in labeled], dtype=float)
    labels = np.asarray([candidate.label for candidate in labeled if candidate.label is not None], dtype=float)
    binary_labels = (labels > POSITIVE_LABEL_THRESHOLD).astype(int)
    train_indices = np.asarray([candidate.index for candidate in labeled], dtype=float)
    feature_mean = feature_matrix.mean(axis=0)
    feature_std = feature_matrix.std(axis=0)
    feature_std[feature_std < 1e-9] = 1.0
    scaled = (feature_matrix - feature_mean) / feature_std
    feature_weights = supervised_metric_weights(scaled, labels)
    weighted_scaled = scaled * feature_weights
    neighbor_count = min(ANALOG_NEIGHBOR_COUNT, len(labeled))
    fit_neighbor_count = min(ANALOG_NEIGHBOR_COUNT + 1, len(labeled))
    neighbors = NearestNeighbors(n_neighbors=fit_neighbor_count, algorithm="auto", metric="minkowski")
    neighbors.fit(weighted_scaled)
    train_distances, train_neighbor_indices = neighbors.kneighbors(weighted_scaled)
    if fit_neighbor_count > 1:
        train_distances = train_distances[:, 1:]
        train_neighbor_indices = train_neighbor_indices[:, 1:]
    return AnalogModel(
        fold_id=fold_id,
        feature_mean=feature_mean,
        feature_std=feature_std,
        labels=labels,
        binary_labels=binary_labels,
        train_indices=train_indices,
        feature_weights=feature_weights,
        neighbors=neighbors,
        neighbor_count=neighbor_count,
        train_candidate_count=len(labeled),
        global_mean=float(labels.mean()),
        global_recent_mean=float(np.average(labels, weights=recency_weights(train_indices))),
        global_positive_rate=float(np.mean(binary_labels > 0)),
        global_adverse_rate=float(np.mean(labels < ADVERSE_LABEL_THRESHOLD)),
    )


def supervised_metric_weights(scaled_features: np.ndarray, labels: np.ndarray) -> np.ndarray:
    if scaled_features.size == 0 or labels.size == 0:
        return np.ones(scaled_features.shape[1] if scaled_features.ndim == 2 else len(FEATURE_NAMES), dtype=float)
    label_centered = labels - labels.mean()
    label_std = float(labels.std())
    if label_std <= 1e-9:
        return np.ones(scaled_features.shape[1], dtype=float)
    correlations = np.abs((scaled_features * label_centered[:, None]).mean(axis=0) / label_std)
    positive_mask = labels > POSITIVE_LABEL_THRESHOLD
    adverse_mask = labels < ADVERSE_LABEL_THRESHOLD
    separation = np.zeros(scaled_features.shape[1], dtype=float)
    if positive_mask.any() and adverse_mask.any():
        separation = np.abs(scaled_features[positive_mask].mean(axis=0) - scaled_features[adverse_mask].mean(axis=0))
    raw = correlations + 0.18 * separation
    raw[~np.isfinite(raw)] = 0.0
    if float(raw.max()) <= 1e-12:
        return np.ones(scaled_features.shape[1], dtype=float)
    positive_raw = raw[raw > 0.0]
    scale = float(np.median(positive_raw)) if positive_raw.size else float(raw.max())
    if scale <= 1e-12:
        scale = float(raw.max())
    weights = np.sqrt(np.maximum(raw / scale, 0.0))
    weights = np.clip(weights, METRIC_WEIGHT_FLOOR, METRIC_WEIGHT_CEILING)
    mean_weight = float(weights.mean())
    if mean_weight > 1e-12:
        weights = weights / mean_weight
    return weights


def recency_weights(indices: np.ndarray) -> np.ndarray:
    if indices.size == 0:
        return np.array([], dtype=float)
    span = float(indices.max() - indices.min())
    if span <= 0.0:
        return np.ones_like(indices, dtype=float)
    normalized = (indices - indices.min()) / span
    return 0.60 + 0.40 * normalized


def analog_diagnostics(
    distances: np.ndarray,
    neighbor_labels: np.ndarray,
    neighbor_indices: np.ndarray,
    all_labels: np.ndarray,
    all_indices: np.ndarray,
) -> np.ndarray:
    if neighbor_labels.size == 0:
        return np.zeros((0, 10), dtype=float)
    weights = recency_weights(neighbor_indices)
    weighted_mean = (neighbor_labels * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-9)
    local_mean = neighbor_labels.mean(axis=1)
    local_std = neighbor_labels.std(axis=1)
    local_positive_rate = (neighbor_labels > POSITIVE_LABEL_THRESHOLD).mean(axis=1)
    local_adverse_rate = (neighbor_labels < ADVERSE_LABEL_THRESHOLD).mean(axis=1)
    local_upper_tail = np.maximum(neighbor_labels, 0.0).mean(axis=1)
    local_lower_tail = np.minimum(neighbor_labels, 0.0).mean(axis=1)
    inner_count = min(INNER_NEIGHBOR_COUNT, neighbor_labels.shape[1])
    inner_mean = neighbor_labels[:, :inner_count].mean(axis=1)
    outer_labels = neighbor_labels[:, inner_count:] if inner_count < neighbor_labels.shape[1] else neighbor_labels[:, :inner_count]
    outer_mean = outer_labels.mean(axis=1)
    recent_order = np.argsort(neighbor_indices, axis=1)
    recent_indices = recent_order[:, -inner_count:]
    recent_labels = np.take_along_axis(neighbor_labels, recent_indices, axis=1)
    recent_mean = recent_labels.mean(axis=1)
    global_mean = float(all_labels.mean()) if all_labels.size else 0.0
    global_recent_mean = float(np.average(all_labels, weights=recency_weights(all_indices))) if all_labels.size else 0.0
    return np.column_stack(
        [
            weighted_mean - global_mean,
            local_mean - global_mean,
            local_std,
            local_positive_rate,
            local_adverse_rate,
            local_upper_tail,
            local_lower_tail,
            np.abs(inner_mean - outer_mean),
            recent_mean - global_recent_mean,
            distances.mean(axis=1),
        ]
    )


def score_candidates(candidates: list[base.Candidate], model: AnalogModel) -> list[base.Candidate]:
    if model.neighbors is None or not candidates:
        return [copy_with_score(candidate, None) for candidate in candidates]
    features = np.asarray([candidate.features for candidate in candidates], dtype=float)
    scaled = (features - model.feature_mean) / model.feature_std
    weighted_scaled = scaled * model.feature_weights
    distances, indices = model.neighbors.kneighbors(weighted_scaled)
    if distances.shape[1] > model.neighbor_count:
        distances = distances[:, : model.neighbor_count]
        indices = indices[:, : model.neighbor_count]
    neighbor_labels = model.labels[indices]
    neighbor_train_indices = model.train_indices[indices]
    diagnostics = analog_diagnostics(distances, neighbor_labels, neighbor_train_indices, model.labels, model.train_indices)
    mean_distance = distances.mean(axis=1)
    local_edge = diagnostics[:, 0]
    positive_minus_adverse = (diagnostics[:, 3] - model.global_positive_rate) - (diagnostics[:, 4] - model.global_adverse_rate)
    tail_quality = diagnostics[:, 5] + diagnostics[:, 6]
    temporal_stability = diagnostics[:, 8] - 0.35 * diagnostics[:, 2] - 0.16 * diagnostics[:, 7]
    metric_similarity = -mean_distance
    rank_components = np.column_stack(
        [
            rank01(local_edge),
            rank01(positive_minus_adverse),
            rank01(tail_quality),
            rank01(temporal_stability),
            rank01(metric_similarity),
        ]
    )
    scores = (
        0.34 * (rank_components[:, 0] - 0.5)
        + 0.25 * (rank_components[:, 1] - 0.5)
        + 0.18 * (rank_components[:, 2] - 0.5)
        + 0.15 * (rank_components[:, 3] - 0.5)
        + 0.08 * (rank_components[:, 4] - 0.5)
        + 0.07 * local_edge
        + 0.05 * positive_minus_adverse
    )
    scored: list[base.Candidate] = []
    for index, candidate in enumerate(candidates):
        if mean_distance[index] > MAX_ANALOG_DISTANCE:
            score = None
        else:
            score = float(scores[index])
        scored.append(copy_with_score(candidate, score))
    return scored


def rank01(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=float)
    ranks[order] = np.arange(values.size, dtype=float)
    if values.size == 1:
        return np.ones(values.size, dtype=float)
    return ranks / float(values.size - 1)


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
    payload["run_id"] = "R0006"
    payload["proxy_id"] = "PX-C0005-R0006"
    payload["proxy_engine"] = "axiom_rift.proxies.c0005_r0006_metric_rank_ensemble_analog_memory"
    payload["proxy_config_path"] = "campaigns/C0005_continuous_analog_memory_discovery/runs/R0006/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_metric_rank_ensemble_analog_memory_analog_fit"
    payload["proxy_artifact_paths"] = [
        "campaigns/C0005_continuous_analog_memory_discovery/runs/R0006/kpi/proxy.json",
        "campaigns/C0005_continuous_analog_memory_discovery/runs/R0006/artifacts/c0005_r0006_proxy_trades.csv",
        "campaigns/C0005_continuous_analog_memory_discovery/runs/R0006/artifacts/c0005_r0006_analog_memory_summary.json",
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
            "inner_neighbor_count": INNER_NEIGHBOR_COUNT,
            "positive_label_threshold": POSITIVE_LABEL_THRESHOLD,
            "adverse_label_threshold": ADVERSE_LABEL_THRESHOLD,
            "metric_weight_floor": METRIC_WEIGHT_FLOOR,
            "metric_weight_ceiling": METRIC_WEIGHT_CEILING,
            "rank_component_names": list(RANK_COMPONENT_NAMES),
            "eligibility_filter": ELIGIBILITY_FILTER,
            "fold_models": fold_models,
            "state_distributions": state_distributions,
            "candidates_by_fold": candidates_by_fold,
            "selection_rule": "top_fold_local_metric_rank_ensemble_analog_memory_scores_per_active_day",
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
            "selection_rule": "top_fold_local_metric_rank_ensemble_analog_memory_scores_per_active_day",
            "feature_names": list(FEATURE_NAMES),
            "feature_count": len(FEATURE_NAMES),
            "analog_neighbor_count": ANALOG_NEIGHBOR_COUNT,
            "inner_neighbor_count": INNER_NEIGHBOR_COUNT,
            "max_analog_distance": MAX_ANALOG_DISTANCE,
            "positive_label_threshold": POSITIVE_LABEL_THRESHOLD,
            "adverse_label_threshold": ADVERSE_LABEL_THRESHOLD,
            "metric_weight_floor": METRIC_WEIGHT_FLOOR,
            "metric_weight_ceiling": METRIC_WEIGHT_CEILING,
            "rank_component_names": list(RANK_COMPONENT_NAMES),
            "eligibility_filter": ELIGIBILITY_FILTER,
            "score_interpretation": "higher_score_means_supervised_metric_local_similarity_rank_ensemble_edge",
            "variant_boundary": "supervised_metric_rank_ensemble_not_r0001_r0002_r0003_r0004_r0005_parameter_nudge_or_retry",
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
        "metric_weight_floor": METRIC_WEIGHT_FLOOR,
        "metric_weight_ceiling": METRIC_WEIGHT_CEILING,
        "feature_weights": [base.rounded(float(value)) for value in model.feature_weights],
        "rank_component_names": list(RANK_COMPONENT_NAMES),
        "positive_label_threshold": POSITIVE_LABEL_THRESHOLD,
        "adverse_label_threshold": ADVERSE_LABEL_THRESHOLD,
        "global_mean": base.rounded(model.global_mean),
        "global_recent_mean": base.rounded(model.global_recent_mean),
        "global_positive_label_rate": base.rounded(model.global_positive_rate),
        "global_adverse_label_rate": base.rounded(model.global_adverse_rate),
        "feature_mean": [base.rounded(float(value)) for value in model.feature_mean],
        "feature_std": [base.rounded(float(value)) for value in model.feature_std],
        "score_interpretation": "higher_score_means_supervised_metric_local_similarity_rank_ensemble_edge",
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
        "schema": "axiom_rift_metric_rank_ensemble_analog_memory_summary_v1",
        "template": False,
        "work_unit_id": "C0005",
        "campaign_id": "C0005",
        "run_id": "R0006",
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
                "A-C0005-R0006-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0005_continuous_analog_memory_discovery/runs/R0006/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0005_continuous_analog_memory_discovery/runs/R0006/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-C0005-R0006-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0005_continuous_analog_memory_discovery/runs/R0006/artifacts/c0005_r0006_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0005_continuous_analog_memory_discovery/runs/R0006/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0005-R0006-ANALOG-MEMORY-SUMMARY",
                "analog_memory_summary_artifact",
                "json",
                "campaigns/C0005_continuous_analog_memory_discovery/runs/R0006/artifacts/c0005_r0006_analog_memory_summary.json",
                summary_hash,
                ["campaigns/C0005_continuous_analog_memory_discovery/runs/R0006/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0005_r0006_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0005_r0006_metric_rank_ensemble_analog_memory",
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
    evidence["proxy_trade_artifact"] = "artifacts/c0005_r0006_proxy_trades.csv"
    evidence["analog_memory_summary"] = "artifacts/c0005_r0006_analog_memory_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0005_r0006_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0005_r0006_proxy_trades.csv",
        "artifacts/c0005_r0006_analog_memory_summary.json",
        "kpi/proxy.json",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["evidence_paths"] = evidence_paths
    data["deferred_with_reason"] = [
        {
            "field": "decision",
            "reason": "proxy evidence is recorded but MT5 and proxy-vs-MT5 evidence are still missing",
            "blocking_condition": "R0006 cannot close until mandatory MT5 logic parity, MT5 tick, execution divergence, and fold-isolated evidence are recorded",
            "revisit_when": "after C0005 R0006 MT5 evidence files contain measured results",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_campaign_status() -> None:
    data = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = "runs/R0006"
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["run_id"] = "R0006"
    next_candidate["direction"] = "active_c0005_r0006_mt5_logic_parity"
    next_candidate["reason"] = "R0006 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0005_r0006_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = "campaigns/C0005_continuous_analog_memory_discovery"
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = "campaigns/C0005_continuous_analog_memory_discovery"
    completed = list(next_work.get("completed") or [])
    if "produce_c0005_r0006_proxy_evidence" not in completed:
        completed.append("produce_c0005_r0006_proxy_evidence")
    next_action = "produce_c0005_r0006_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_run"] = "campaigns/C0005_continuous_analog_memory_discovery/runs/R0006"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0005_continuous_analog_memory_discovery"
    data["active_run"] = "campaigns/C0005_continuous_analog_memory_discovery/runs/R0006"
    data["latest_operation"] = {
        "id": "produce_c0005_r0006_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0005_continuous_analog_memory_discovery/runs/R0006/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0005_r0006_mt5_logic_parity_evidence",
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
            "R0006": "R0006",
            "R0001": "R0006",
            "c0004_r0001_fold_local_state_archetype": "c0005_r0006_metric_rank_ensemble_analog_memory",
            "c0004_r0001": "c0005_r0006",
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
