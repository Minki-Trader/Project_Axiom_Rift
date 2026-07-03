"""C0008 R0002 proxy evidence for structural trap reversal discovery."""

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
from axiom_rift.proxies import c0004_r0001_fold_local_state_archetype as base


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0008_multi_timeframe_structural_context_discovery" / "runs" / "R0002"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0008_multi_timeframe_structural_context_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0008_r0002_proxy_trades.csv"
TRAP_REVERSAL_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0008_r0002_structural_trap_reversal_summary.json"
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
    "directional_m15_return_3",
    "directional_m15_return_9",
    "directional_h1_return_12",
    "directional_h1_return_24",
    "directional_h1_return_72",
    "directional_h1_trend_consistency_24",
    "directional_position_prior_m15_range",
    "directional_position_prior_h1_range",
    "directional_position_prior_session_range",
    "directional_position_prior_day_range",
    "directional_break_prior_m15_range",
    "directional_break_prior_h1_range",
    "directional_break_prior_session_range",
    "directional_break_prior_day_range",
    "directional_distance_from_session_mid",
    "directional_distance_from_day_mid",
    "range_ratio_m15_over_h1",
    "range_ratio_h1_over_day",
    "range_expansion_3_over_36",
    "range_compression_12_over_96",
    "directional_body_fraction",
    "directional_close_location",
    "directional_adverse_wick_fraction",
    "structural_transition_pressure",
    "session_sin",
    "session_cos",
    "spread_over_range",
    "trap_extension_prior_m15",
    "trap_extension_prior_h1",
    "trap_extension_prior_session",
    "trap_extension_prior_day",
    "reclaim_strength_h1",
    "reclaim_strength_session",
    "reversal_wick_fraction",
    "opposite_trend_pressure",
    "trap_body_reversal",
    "trap_range_expansion",
)
MODEL_FAMILY = "fold_local_structural_trap_reversal_centroid_contrast"
LABEL_SHAPE = "directional_trap_reversal_target_first_reclaim_quality"
POSITIVE_LABEL_THRESHOLD = 0.18
ADVERSE_LABEL_THRESHOLD = -0.30
FEATURE_WEIGHT_FLOOR = 0.35
FEATURE_WEIGHT_CEILING = 3.00
TRAP_SIGNAL_THRESHOLD = 0.16
SELECTION_RULE = "top_fold_local_structural_trap_reversal_centroid_scores_per_active_day"


@dataclass(frozen=True)
class TrapReversalModel:
    fold_id: str
    feature_mean: np.ndarray
    feature_std: np.ndarray
    feature_weights: np.ndarray
    positive_centroid: np.ndarray
    adverse_centroid: np.ndarray
    neutral_centroid: np.ndarray
    train_candidate_count: int
    global_mean: float
    positive_label_rate: float
    adverse_label_rate: float
    label_std: float


def run_c0008_r0002_proxy(write: bool = True) -> dict[str, object]:
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
        model = fit_trap_reversal_model(train_candidates, fold_id)
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
        fold_models.append(trap_model_summary(model))
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
        288,
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
            features = trap_reversal_features(bars, range_average, short_range_average, index, direction)
            if features is None:
                continue
            label = trap_reversal_path_label(bars, range_average, index, direction) if include_labels else None
            side = "long" if direction > 0 else "short"
            candidates.append(
                base.Candidate(
                    fold_id=fold_id,
                    index=index,
                    direction=direction,
                    day=bars[index].time.strftime("%Y-%m-%d"),
                    state_key=f"{side}|structural_trap_reversal",
                    features=features,
                    label=label,
                )
            )
    return candidates


def trap_reversal_features(
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
    m15_low, m15_high = prior_window_low_high(bars, index, 3)
    h1_low, h1_high = prior_window_low_high(bars, index, 12)
    session_low, session_high = prior_window_low_high(bars, index, 72)
    day_low, day_high = prior_window_low_high(bars, index, 288)
    directional_steps = [direction * (bars[offset].close - bars[offset - 1].close) for offset in range(index - 23, index + 1)]
    trend_consistency = sum(1.0 if value > 0 else -1.0 if value < 0 else 0.0 for value in directional_steps) / len(
        directional_steps
    )
    range_3 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 2, index + 1)) / 3.0
    range_12 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 11, index + 1)) / 12.0
    range_36 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 35, index + 1)) / 36.0
    range_96 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 95, index + 1)) / 96.0
    range_ratio_m15_h1 = max(m15_high - m15_low, 0.0) / max(h1_high - h1_low, 1e-9)
    range_ratio_h1_day = max(h1_high - h1_low, 0.0) / max(day_high - day_low, 1e-9)
    range_expansion = range_3 / max(range_36, 1e-9)
    range_compression = range_12 / max(range_96, 1e-9)
    body_fraction = direction * (bar.close - bar.open) / bar_range
    close_location = (bar.close - bar.low) / bar_range
    directional_close_location = close_location if direction > 0 else 1.0 - close_location
    upper_wick = bar.high - max(bar.open, bar.close)
    lower_wick = min(bar.open, bar.close) - bar.low
    adverse_wick = upper_wick if direction > 0 else lower_wick
    pos_m15 = directional_position(bar.close, m15_low, m15_high, direction)
    pos_h1 = directional_position(bar.close, h1_low, h1_high, direction)
    pos_session = directional_position(bar.close, session_low, session_high, direction)
    pos_day = directional_position(bar.close, day_low, day_high, direction)
    break_m15 = directional_break_distance(bar.close, m15_low, m15_high, average_range, direction)
    break_h1 = directional_break_distance(bar.close, h1_low, h1_high, average_range, direction)
    break_session = directional_break_distance(bar.close, session_low, session_high, average_range, direction)
    break_day = directional_break_distance(bar.close, day_low, day_high, average_range, direction)
    if direction > 0:
        trap_extension_m15 = max((m15_low - bar.low) / average_range, 0.0)
        trap_extension_h1 = max((h1_low - bar.low) / average_range, 0.0)
        trap_extension_session = max((session_low - bar.low) / average_range, 0.0)
        trap_extension_day = max((day_low - bar.low) / average_range, 0.0)
        reclaim_strength_h1 = max((bar.close - h1_low) / average_range, 0.0)
        reclaim_strength_session = max((bar.close - session_low) / average_range, 0.0)
        reversal_wick_fraction = lower_wick / bar_range
    else:
        trap_extension_m15 = max((bar.high - m15_high) / average_range, 0.0)
        trap_extension_h1 = max((bar.high - h1_high) / average_range, 0.0)
        trap_extension_session = max((bar.high - session_high) / average_range, 0.0)
        trap_extension_day = max((bar.high - day_high) / average_range, 0.0)
        reclaim_strength_h1 = max((h1_high - bar.close) / average_range, 0.0)
        reclaim_strength_session = max((session_high - bar.close) / average_range, 0.0)
        reversal_wick_fraction = upper_wick / bar_range
    opposite_trend_pressure = max(0.0, -direction * (bar.close - bars[index - 24].close) / average_range)
    trap_body_reversal = max(body_fraction, 0.0)
    trap_range_expansion = max(range_expansion - 1.0, 0.0)
    session_mid = (session_low + session_high) / 2.0
    day_mid = (day_low + day_high) / 2.0
    distance_session_mid = direction * (bar.close - session_mid) / average_range
    distance_day_mid = direction * (bar.close - day_mid) / average_range
    structural_transition_pressure = max(
        abs(pos_h1 - 0.5),
        abs(pos_session - 0.5),
        abs(pos_day - 0.5),
        max(break_h1, break_session, break_day, 0.0),
    )
    if structural_transition_pressure < 0.12 and range_expansion < 1.08 and range_compression > 0.86:
        return None
    trap_signal = (
        max(trap_extension_m15, trap_extension_h1, trap_extension_session, trap_extension_day)
        + 0.36 * reversal_wick_fraction
        + 0.22 * trap_body_reversal
        + 0.16 * opposite_trend_pressure
        + 0.18 * trap_range_expansion
    )
    if trap_signal < TRAP_SIGNAL_THRESHOLD and directional_close_location < 0.52 and structural_transition_pressure < 0.20:
        return None
    minute_fraction = base.minute_of_day(bar.time) / (24.0 * 60.0)
    session_sin = math.sin(2.0 * math.pi * minute_fraction)
    session_cos = math.cos(2.0 * math.pi * minute_fraction)
    spread_over_range = bar.spread_points / average_range
    return (
        direction * (bar.close - bars[index - 3].close) / average_range,
        direction * (bar.close - bars[index - 9].close) / average_range,
        direction * (bar.close - bars[index - 12].close) / average_range,
        direction * (bar.close - bars[index - 24].close) / average_range,
        direction * (bar.close - bars[index - 72].close) / average_range,
        trend_consistency,
        pos_m15,
        pos_h1,
        pos_session,
        pos_day,
        break_m15,
        break_h1,
        break_session,
        break_day,
        distance_session_mid,
        distance_day_mid,
        range_ratio_m15_h1,
        range_ratio_h1_day,
        range_expansion,
        range_compression,
        body_fraction,
        directional_close_location,
        adverse_wick / bar_range,
        structural_transition_pressure,
        session_sin,
        session_cos,
        spread_over_range,
        trap_extension_m15,
        trap_extension_h1,
        trap_extension_session,
        trap_extension_day,
        reclaim_strength_h1,
        reclaim_strength_session,
        reversal_wick_fraction,
        opposite_trend_pressure,
        trap_body_reversal,
        trap_range_expansion,
    )


def prior_window_low_high(bars: list[base.Bar], index: int, lookback: int) -> tuple[float, float]:
    window = bars[index - lookback : index]
    return min(bar.low for bar in window), max(bar.high for bar in window)


def directional_position(close: float, low: float, high: float, direction: int) -> float:
    if high <= low:
        return 0.5
    position = (close - low) / (high - low)
    return position if direction > 0 else 1.0 - position


def directional_break_distance(close: float, low: float, high: float, average_range: float, direction: int) -> float:
    level = high if direction > 0 else low
    return direction * (close - level) / average_range


def trap_reversal_path_label(
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
        1.08 * first_hit
        + 0.52 * target_speed
        - 0.42 * stop_speed
        + 0.18 * favorable
        - 0.48 * adverse
        - 1.28 * adverse_tail
        - 0.34 * giveback
        + 0.32 * terminal_norm
        + 0.30 * path_alignment_edge
        - 1.12 * spread_norm
    )


def fit_trap_reversal_model(candidates: list[base.Candidate], fold_id: str) -> TrapReversalModel:
    labeled = [candidate for candidate in candidates if candidate.label is not None]
    feature_count = len(FEATURE_NAMES)
    if not labeled:
        return TrapReversalModel(
            fold_id=fold_id,
            feature_mean=np.zeros(feature_count, dtype=float),
            feature_std=np.ones(feature_count, dtype=float),
            feature_weights=np.ones(feature_count, dtype=float),
            positive_centroid=np.zeros(feature_count, dtype=float),
            adverse_centroid=np.zeros(feature_count, dtype=float),
            neutral_centroid=np.zeros(feature_count, dtype=float),
            train_candidate_count=0,
            global_mean=0.0,
            positive_label_rate=0.0,
            adverse_label_rate=0.0,
            label_std=0.0,
        )
    feature_matrix = np.asarray([candidate.features for candidate in labeled], dtype=float)
    labels = np.asarray([candidate.label for candidate in labeled if candidate.label is not None], dtype=float)
    feature_mean = feature_matrix.mean(axis=0)
    feature_std = feature_matrix.std(axis=0)
    feature_std[feature_std < 1e-9] = 1.0
    scaled = (feature_matrix - feature_mean) / feature_std
    label_std = float(labels.std())
    positive_mask = labels > POSITIVE_LABEL_THRESHOLD
    adverse_mask = labels < ADVERSE_LABEL_THRESHOLD
    neutral_mask = ~(positive_mask | adverse_mask)
    positive_centroid = scaled[positive_mask].mean(axis=0) if positive_mask.any() else scaled.mean(axis=0)
    adverse_centroid = scaled[adverse_mask].mean(axis=0) if adverse_mask.any() else scaled.mean(axis=0)
    neutral_centroid = scaled[neutral_mask].mean(axis=0) if neutral_mask.any() else scaled.mean(axis=0)
    separation = positive_centroid - adverse_centroid
    if label_std <= 1e-9:
        signed_correlation = np.zeros(feature_count, dtype=float)
    else:
        signed_correlation = (scaled * (labels - labels.mean())[:, None]).mean(axis=0) / label_std
    raw_strength = np.abs(separation) + 0.18 * np.abs(signed_correlation)
    raw_strength[~np.isfinite(raw_strength)] = 0.0
    positive_strength = raw_strength[raw_strength > 0.0]
    if positive_strength.size:
        scale = float(np.median(positive_strength))
        if scale <= 1e-12:
            scale = float(positive_strength.max())
        weights = np.sqrt(np.maximum(raw_strength / max(scale, 1e-12), 0.0))
        weights = np.clip(weights, FEATURE_WEIGHT_FLOOR, FEATURE_WEIGHT_CEILING)
        weights = weights / max(float(weights.mean()), 1e-12)
    else:
        weights = np.ones(feature_count, dtype=float)
    return TrapReversalModel(
        fold_id=fold_id,
        feature_mean=feature_mean,
        feature_std=feature_std,
        feature_weights=weights,
        positive_centroid=positive_centroid,
        adverse_centroid=adverse_centroid,
        neutral_centroid=neutral_centroid,
        train_candidate_count=len(labeled),
        global_mean=float(labels.mean()),
        positive_label_rate=float(np.mean(positive_mask)),
        adverse_label_rate=float(np.mean(adverse_mask)),
        label_std=label_std,
    )


def score_candidates(candidates: list[base.Candidate], model: TrapReversalModel) -> list[base.Candidate]:
    if not candidates:
        return []
    features = np.asarray([candidate.features for candidate in candidates], dtype=float)
    scaled = (features - model.feature_mean) / model.feature_std
    weighted = scaled * model.feature_weights
    positive = model.positive_centroid * model.feature_weights
    adverse = model.adverse_centroid * model.feature_weights
    neutral = model.neutral_centroid * model.feature_weights
    dist_positive = np.sqrt(((weighted - positive) ** 2).mean(axis=1))
    dist_adverse = np.sqrt(((weighted - adverse) ** 2).mean(axis=1))
    dist_neutral = np.sqrt(((weighted - neutral) ** 2).mean(axis=1))
    scores = (
        dist_adverse
        - dist_positive
        - 0.18 * dist_neutral
        + model.global_mean
        + 0.24 * (model.positive_label_rate - model.adverse_label_rate)
    )
    scored: list[base.Candidate] = []
    for index, candidate in enumerate(candidates):
        score = float(scores[index])
        if not math.isfinite(score):
            score = None  # type: ignore[assignment]
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
    payload["campaign_id"] = "C0008"
    payload["work_unit_id"] = "C0008"
    payload["run_id"] = "R0002"
    payload["proxy_id"] = "PX-C0008-R0002"
    payload["proxy_engine"] = "axiom_rift.proxies.c0008_r0002_structural_trap_reversal"
    payload["proxy_config_path"] = "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0002/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_structural_trap_reversal_centroid_fit"
    payload["proxy_artifact_paths"] = [
        "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0002/kpi/proxy.json",
        "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0002/artifacts/c0008_r0002_proxy_trades.csv",
        "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0002/artifacts/c0008_r0002_structural_trap_reversal_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["structural_trap_reversal_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "model_family": MODEL_FAMILY,
            "feature_count": len(FEATURE_NAMES),
            "feature_names": list(FEATURE_NAMES),
            "label_shape": LABEL_SHAPE,
            "positive_label_threshold": POSITIVE_LABEL_THRESHOLD,
            "adverse_label_threshold": ADVERSE_LABEL_THRESHOLD,
            "feature_weight_floor": FEATURE_WEIGHT_FLOOR,
            "feature_weight_ceiling": FEATURE_WEIGHT_CEILING,
            "trap_signal_threshold": TRAP_SIGNAL_THRESHOLD,
            "fold_models": fold_models,
            "state_distributions": state_distributions,
            "candidates_by_fold": candidates_by_fold,
            "selection_rule": SELECTION_RULE,
            "candidate_direction": "dual_direction_structural_trap_reversal",
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
            "next_action": "produce_c0008_r0002_mt5_logic_parity_evidence",
        },
    }
    return payload


def proxy_config() -> dict[str, object]:
    config = dict(base.proxy_config())
    config.update(
        {
            "state_model": MODEL_FAMILY,
            "label_shape": LABEL_SHAPE,
            "selection_rule": SELECTION_RULE,
            "feature_names": list(FEATURE_NAMES),
            "feature_count": len(FEATURE_NAMES),
            "positive_label_threshold": POSITIVE_LABEL_THRESHOLD,
            "adverse_label_threshold": ADVERSE_LABEL_THRESHOLD,
            "feature_weight_floor": FEATURE_WEIGHT_FLOOR,
            "feature_weight_ceiling": FEATURE_WEIGHT_CEILING,
            "trap_signal_threshold": TRAP_SIGNAL_THRESHOLD,
            "score_interpretation": "higher_score_means_closer_to_positive_trap_reversal_centroid_and_farther_from_adverse_centroid",
            "variant_boundary": "structural_trap_reversal_centroid_contrast_not_r0001_direct_rank_threshold_daily_count_stop_target_hold_session_or_retry_nudge",
        }
    )
    return config


def trap_model_summary(model: TrapReversalModel) -> dict[str, object]:
    return {
        "fold_id": model.fold_id,
        "model_family": MODEL_FAMILY,
        "feature_names": list(FEATURE_NAMES),
        "feature_count": len(FEATURE_NAMES),
        "train_candidate_count": model.train_candidate_count,
        "global_mean": base.rounded(model.global_mean),
        "label_std": base.rounded(model.label_std),
        "positive_label_rate": base.rounded(model.positive_label_rate),
        "adverse_label_rate": base.rounded(model.adverse_label_rate),
        "feature_weights": [base.rounded(float(value)) for value in model.feature_weights],
        "positive_centroid": [base.rounded(float(value)) for value in model.positive_centroid],
        "adverse_centroid": [base.rounded(float(value)) for value in model.adverse_centroid],
        "neutral_centroid": [base.rounded(float(value)) for value in model.neutral_centroid],
        "feature_mean": [base.rounded(float(value)) for value in model.feature_mean],
        "feature_std": [base.rounded(float(value)) for value in model.feature_std],
        "score_interpretation": "higher_score_means_closer_to_positive_trap_reversal_centroid_and_farther_from_adverse_centroid",
    }


def score_distribution(
    scored: list[base.Candidate],
    selected: list[base.Candidate],
    model: TrapReversalModel,
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
    write_structural_summary_artifact(payload, TRAP_REVERSAL_SUMMARY_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = base.sha256_file(TRADE_ARTIFACT_PATH)
    summary_hash = base.sha256_file(TRAP_REVERSAL_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = base.sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)


def write_structural_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_fold_local_structural_trap_reversal_summary_v1",
        "template": False,
        "work_unit_id": "C0008",
        "campaign_id": "C0008",
        "run_id": "R0002",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "structural_trap_reversal_profile": profiles["structural_trap_reversal_profile"]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "structural_trap_reversal_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-C0008-R0002-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0002/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0002/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-C0008-R0002-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0002/artifacts/c0008_r0002_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0002/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0008-R0002-STRUCTURAL-TRAP-REVERSAL-SUMMARY",
                "structural_trap_reversal_summary_artifact",
                "json",
                "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0002/artifacts/c0008_r0002_structural_trap_reversal_summary.json",
                summary_hash,
                ["campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0002/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0008_r0002_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0008_r0002_structural_trap_reversal",
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
    evidence["proxy_trade_artifact"] = "artifacts/c0008_r0002_proxy_trades.csv"
    evidence["structural_trap_reversal_summary"] = "artifacts/c0008_r0002_structural_trap_reversal_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0008_r0002_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0008_r0002_proxy_trades.csv",
        "artifacts/c0008_r0002_structural_trap_reversal_summary.json",
        "kpi/proxy.json",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["evidence_paths"] = evidence_paths
    data["deferred_with_reason"] = [
        {
            "field": "decision",
            "reason": "proxy evidence is recorded but MT5 and proxy-vs-MT5 evidence are still missing",
            "blocking_condition": "R0002 cannot close until mandatory MT5 logic parity, MT5 tick, execution divergence, and fold-isolated evidence are recorded",
            "revisit_when": "after C0008 R0002 MT5 evidence files contain measured results",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_campaign_status() -> None:
    data = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = "runs/R0002"
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["run_id"] = "R0002"
    next_candidate["direction"] = "active_c0008_r0002_mt5_logic_parity"
    next_candidate["reason"] = "R0002 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0008_r0002_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = "campaigns/C0008_multi_timeframe_structural_context_discovery"
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = "campaigns/C0008_multi_timeframe_structural_context_discovery"
    completed = list(next_work.get("completed") or [])
    for item in (
        "open_c0008_multi_timeframe_structural_context_discovery",
        "open_c0008_r0002_structural_trap_reversal_centroid_run",
        "produce_c0008_r0002_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_c0008_r0002_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_run"] = "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0002"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0008_multi_timeframe_structural_context_discovery"
    data["active_run"] = "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0002"
    data["latest_operation"] = {
        "id": "produce_c0008_r0002_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0008_multi_timeframe_structural_context_discovery/runs/R0002/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0008_r0002_mt5_logic_parity_evidence",
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
            "C0004": "C0008",
            "R0001": "R0002",
            "c0004_r0001_fold_local_state_archetype": "c0008_r0002_structural_trap_reversal",
            "c0004_r0001": "c0008_r0002",
            "fold_local_state_archetype_discovery": "multi_timeframe_structural_context_discovery",
            "fold_local_train_only_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "structural_trap_reversal_summary",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
