"""C0010 R0002 proxy evidence for monthly loss-memory abstention discovery."""

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


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0010_monthly_regime_risk_control_discovery" / "runs" / "R0002"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0010_monthly_regime_risk_control_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0010_r0002_proxy_trades.csv"
REGIME_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0010_r0002_monthly_loss_memory_abstention_summary.json"
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
    "directional_return_3",
    "directional_return_12",
    "directional_return_36",
    "directional_return_96",
    "directional_trend_consistency_36",
    "directional_trend_consistency_96",
    "range_12_over_96",
    "range_36_over_288",
    "range_compression_96_over_288",
    "volatility_acceleration_12_over_96",
    "bar_range_over_average",
    "short_range_over_average",
    "directional_body_fraction",
    "directional_close_location",
    "directional_day_position",
    "directional_day_break_distance",
    "prior_adverse_tail_pressure_36",
    "prior_aligned_close_ratio_36",
    "prior_directional_drawdown_72",
    "prior_directional_drawup_buffer_72",
    "spread_over_range",
    "spread_pressure_96",
    "spread_slope_24",
    "cost_buffer_proxy",
    "month_sin",
    "month_cos",
    "month_progress",
    "month_edge_pressure",
    "weekday_sin",
    "weekday_cos",
    "session_sin",
    "session_cos",
    "minutes_from_core_mid",
)
MODEL_FAMILY = "fold_local_monthly_loss_memory_state_reliability_rank"
LABEL_SHAPE = "target_first_edge_minus_monthly_loss_memory_hazard"
POSITIVE_LABEL_THRESHOLD = 0.08
ADVERSE_LABEL_THRESHOLD = -0.32
FEATURE_WEIGHT_FLOOR = 0.25
FEATURE_WEIGHT_CEILING = 2.50
SELECTION_RULE = "sequential_monthly_loss_memory_abstention_with_train_state_reliability"
MONTH_SOFT_LOSS_LIMIT_POINTS = -80.0
MONTH_HARD_LOSS_LIMIT_POINTS = -160.0
LOSS_STREAK_SOFT_LIMIT = 3
LOSS_STREAK_HARD_LIMIT = 5
SCORE_ABSTENTION_FLOOR = -0.35
MONTH_LOSS_PENALTY_PER_POINT = 0.004
LOSS_STREAK_SCORE_PENALTY = 0.08
TRAIN_DOWNSIDE_PENALTY_SCALE = 0.35


@dataclass(frozen=True)
class LinearEdgeModel:
    fold_id: str
    feature_mean: np.ndarray
    feature_std: np.ndarray
    score_direction: np.ndarray
    feature_weights: np.ndarray
    train_candidate_count: int
    global_mean: float
    positive_label_rate: float
    adverse_label_rate: float
    label_std: float


def run_c0010_r0002_proxy(write: bool = True) -> dict[str, object]:
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
        model = fit_linear_edge_model(train_candidates, fold_id)
        test_candidates = build_candidates(
            bars,
            range_average,
            short_range_average,
            split["test_oos"],
            fold_id,
            include_labels=False,
        )
        scored_candidates = score_candidates(test_candidates, model)
        fold_trades = select_loss_memory_trades(bars, range_average, scored_candidates, split["test_oos"], model)
        trades.extend(fold_trades)
        fold_models.append(linear_model_summary(model))
        state_distributions[fold_id] = loss_memory_distribution(scored_candidates, fold_trades, model)
        candidates_by_fold[fold_id] = {
            "train_candidate_count": len(train_candidates),
            "test_candidate_count": len(test_candidates),
            "selected_candidate_count": len(fold_trades),
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
        72,
        36,
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
            features = monthly_loss_memory_abstention_features(bars, range_average, short_range_average, index, direction)
            if features is None:
                continue
            label = monthly_loss_memory_abstention_label(bars, range_average, index, direction) if include_labels else None
            candidates.append(
                base.Candidate(
                    fold_id=fold_id,
                    index=index,
                    direction=direction,
                    day=bars[index].time.strftime("%Y-%m-%d"),
                    state_key=state_key_for_candidate(bars, range_average, index, direction),
                    features=features,
                    label=label,
                )
            )
    return candidates


def monthly_loss_memory_abstention_features(
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
    day_low, day_high = prior_window_low_high(bars, index, 288)
    directional_steps_36 = [
        direction * (bars[offset].close - bars[offset - 1].close) for offset in range(index - 35, index + 1)
    ]
    directional_steps_96 = [
        direction * (bars[offset].close - bars[offset - 1].close) for offset in range(index - 95, index + 1)
    ]
    trend_consistency_36 = signed_step_average(directional_steps_36)
    trend_consistency_96 = signed_step_average(directional_steps_96)
    ret_3 = direction * (bar.close - bars[index - 3].close) / average_range
    ret_12 = direction * (bar.close - bars[index - 12].close) / average_range
    ret_36 = direction * (bar.close - bars[index - 36].close) / average_range
    ret_96 = direction * (bar.close - bars[index - 96].close) / average_range
    range_12 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 11, index + 1)) / 12.0
    range_36 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 35, index + 1)) / 36.0
    range_96 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 95, index + 1)) / 96.0
    range_288 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 287, index + 1)) / 288.0
    day_range = max(day_high - day_low, 1e-9)
    range_12_over_96 = range_12 / max(range_96, 1e-9)
    range_36_over_288 = range_36 / max(range_288, 1e-9)
    range_compression_96_over_288 = max(1.0 - (range_96 / max(range_288, 1e-9)), 0.0)
    volatility_acceleration = max(range_12_over_96 - 1.0, 0.0)
    bar_range_over_average = bar_range / average_range
    short_range_over_average = short_average_range / average_range
    body_fraction = direction * (bar.close - bar.open) / bar_range
    close_location = (bar.close - bar.low) / bar_range
    directional_close_location = close_location if direction > 0 else 1.0 - close_location
    directional_day_position = directional_position(bar.close, day_low, day_high, direction)
    directional_day_break = directional_break_distance(bar.close, day_low, day_high, average_range, direction)
    prior_bars_36 = bars[index - 35 : index + 1]
    adverse_tail_pressure = 0.0
    aligned_close_count = 0
    for prior in prior_bars_36:
        prior_range = max(prior.high - prior.low, 1e-9)
        prior_upper = prior.high - max(prior.open, prior.close)
        prior_lower = min(prior.open, prior.close) - prior.low
        adverse_tail = prior_upper if direction > 0 else prior_lower
        adverse_tail_pressure += adverse_tail / prior_range
        if (direction > 0 and prior.close >= prior.open) or (direction < 0 and prior.close <= prior.open):
            aligned_close_count += 1
    adverse_tail_pressure /= len(prior_bars_36)
    aligned_close_ratio = aligned_close_count / len(prior_bars_36)
    recent_closes = [bars[offset].close for offset in range(index - 71, index + 1)]
    if direction > 0:
        drawdown_pressure = max(0.0, max(recent_closes) - bar.close) / average_range
        drawup_buffer = max(0.0, bar.close - min(recent_closes)) / average_range
    else:
        drawdown_pressure = max(0.0, bar.close - min(recent_closes)) / average_range
        drawup_buffer = max(0.0, max(recent_closes) - bar.close) / average_range
    spread_96 = sum(bars[offset].spread_points for offset in range(index - 95, index + 1)) / 96.0
    spread_24 = sum(bars[offset].spread_points for offset in range(index - 23, index + 1)) / 24.0
    prev_spread_24 = sum(bars[offset].spread_points for offset in range(index - 47, index - 23)) / 24.0
    spread_over_range = bar.spread_points / average_range
    spread_pressure_96 = bar.spread_points / max(spread_96, 1e-9)
    spread_slope_24 = (spread_24 - prev_spread_24) / max(spread_96, 1e-9)
    cost_buffer_proxy = max(ret_12, ret_36, 0.0) - spread_over_range - 0.18 * max(spread_pressure_96 - 1.0, 0.0)
    month_progress = month_progress_ratio(bar.time)
    month_angle = 2.0 * math.pi * month_progress
    month_sin = math.sin(month_angle)
    month_cos = math.cos(month_angle)
    month_edge_pressure = 1.0 if bar.time.day <= 3 or bar.time.day >= 26 else 0.0
    weekday_fraction = bar.time.weekday() / 5.0
    weekday_sin = math.sin(2.0 * math.pi * weekday_fraction)
    weekday_cos = math.cos(2.0 * math.pi * weekday_fraction)
    candidate_quality = (
        max(ret_12, 0.0)
        + max(trend_consistency_36, 0.0)
        + 0.35 * max(directional_close_location - 0.50, 0.0)
        + 0.18 * max(cost_buffer_proxy, 0.0)
        - 0.28 * drawdown_pressure
        - 0.26 * adverse_tail_pressure
        - 0.30 * max(spread_over_range - 0.22, 0.0)
        - 0.08 * month_edge_pressure
    )
    if spread_over_range > 0.70 or spread_pressure_96 > 1.80:
        return None
    if candidate_quality < -0.35 and cost_buffer_proxy < -0.24:
        return None
    minute_fraction = base.minute_of_day(bar.time) / (24.0 * 60.0)
    session_sin = math.sin(2.0 * math.pi * minute_fraction)
    session_cos = math.cos(2.0 * math.pi * minute_fraction)
    core_mid = (base.CORE_SESSION_START_MINUTE + base.CORE_SESSION_END_MINUTE) / 2.0
    minutes_from_core_mid = (base.minute_of_day(bar.time) - core_mid) / max(
        base.CORE_SESSION_END_MINUTE - base.CORE_SESSION_START_MINUTE,
        1.0,
    )
    return (
        ret_3,
        ret_12,
        ret_36,
        ret_96,
        trend_consistency_36,
        trend_consistency_96,
        range_12_over_96,
        range_36_over_288,
        range_compression_96_over_288,
        volatility_acceleration,
        bar_range_over_average,
        short_range_over_average,
        body_fraction,
        directional_close_location,
        directional_day_position,
        directional_day_break,
        adverse_tail_pressure,
        aligned_close_ratio,
        drawdown_pressure,
        drawup_buffer,
        spread_over_range,
        spread_pressure_96,
        spread_slope_24,
        cost_buffer_proxy,
        month_sin,
        month_cos,
        month_progress,
        month_edge_pressure,
        weekday_sin,
        weekday_cos,
        session_sin,
        session_cos,
        minutes_from_core_mid,
    )


def signed_step_average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(1.0 if value > 0 else -1.0 if value < 0 else 0.0 for value in values) / len(values)


def month_progress_ratio(value: datetime) -> float:
    month_days = 31.0
    if value.month in {4, 6, 9, 11}:
        month_days = 30.0
    elif value.month == 2:
        month_days = 29.0 if value.year % 4 == 0 else 28.0
    minute_fraction = base.minute_of_day(value) / (24.0 * 60.0)
    return min(max((value.day - 1 + minute_fraction) / month_days, 0.0), 1.0)


def state_key_for_candidate(
    bars: list[base.Bar],
    range_average: list[float | None],
    index: int,
    direction: int,
) -> str:
    side = "long" if direction > 0 else "short"
    value = bars[index].time
    if value.day <= 7:
        month_phase = "early_month"
    elif value.day >= 24:
        month_phase = "late_month"
    else:
        month_phase = "mid_month"
    average_range = range_average[index] or 1.0
    range_36 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 35, index + 1)) / 36.0
    volatility_ratio = range_36 / max(average_range, 1e-9)
    if volatility_ratio < 0.82:
        volatility_state = "quiet"
    elif volatility_ratio > 1.22:
        volatility_state = "hot"
    else:
        volatility_state = "normal"
    recent_closes = [bars[offset].close for offset in range(index - 71, index + 1)]
    if direction > 0:
        drawdown_pressure = max(0.0, max(recent_closes) - bars[index].close) / max(average_range, 1e-9)
    else:
        drawdown_pressure = max(0.0, bars[index].close - min(recent_closes)) / max(average_range, 1e-9)
    risk_state = "pressed" if drawdown_pressure > 1.10 else "calm"
    return f"{side}|{month_phase}|vol_{volatility_state}|risk_{risk_state}"


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


def monthly_loss_memory_abstention_label(
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
    path_spread_peak = max(bar.spread_points for bar in path) / average_range
    path_range_peak = max(max(bar.high - bar.low, 0.0) for bar in path) / average_range
    spread_drift = max(0.0, path_spread_peak - spread_norm)
    path_shock = max(0.0, path_range_peak - 1.65)
    cost_buffer = max(0.0, favorable - spread_norm)
    near_stop_pressure = max(0.0, 1.0 - (stop_distance - mae) / max(stop_distance, 1e-9))
    recent_closes = [bars[offset].close for offset in range(index - 71, index + 1)]
    if direction > 0:
        prior_drawdown_pressure = max(0.0, max(recent_closes) - bars[index].close) / average_range
    else:
        prior_drawdown_pressure = max(0.0, bars[index].close - min(recent_closes)) / average_range
    month_edge_pressure = 1.0 if bars[index].time.day <= 3 or bars[index].time.day >= 26 else 0.0
    friday_pressure = 1.0 if bars[index].time.weekday() == 4 else 0.0
    clean_target_edge = 1.12 * first_hit + 0.30 * target_speed - 0.42 * stop_speed
    return (
        clean_target_edge
        + 0.24 * favorable
        - 0.50 * adverse
        - 1.05 * adverse_tail
        - 0.28 * giveback
        - 0.32 * near_stop_pressure
        - 0.24 * prior_drawdown_pressure
        - 0.14 * month_edge_pressure
        - 0.06 * friday_pressure
        + 0.22 * terminal_norm
        + 0.18 * path_alignment_edge
        + 0.14 * cost_buffer
        - 0.88 * spread_norm
        - 0.42 * spread_drift
        - 0.28 * path_shock
    )


def fit_linear_edge_model(candidates: list[base.Candidate], fold_id: str) -> LinearEdgeModel:
    labeled = [candidate for candidate in candidates if candidate.label is not None]
    feature_count = len(FEATURE_NAMES)
    if not labeled:
        return LinearEdgeModel(
            fold_id=fold_id,
            feature_mean=np.zeros(feature_count, dtype=float),
            feature_std=np.ones(feature_count, dtype=float),
            score_direction=np.zeros(feature_count, dtype=float),
            feature_weights=np.ones(feature_count, dtype=float),
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
    centered = labels - labels.mean()
    label_std = float(labels.std())
    if label_std <= 1e-9:
        signed_correlation = np.zeros(feature_count, dtype=float)
    else:
        signed_correlation = (scaled * centered[:, None]).mean(axis=0) / label_std
    positive_mask = labels > POSITIVE_LABEL_THRESHOLD
    adverse_mask = labels < ADVERSE_LABEL_THRESHOLD
    separation = np.zeros(feature_count, dtype=float)
    if positive_mask.any() and adverse_mask.any():
        separation = scaled[positive_mask].mean(axis=0) - scaled[adverse_mask].mean(axis=0)
    raw_strength = np.abs(signed_correlation) + 0.12 * np.abs(separation)
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
    direction = signed_correlation + 0.08 * separation
    direction[~np.isfinite(direction)] = 0.0
    return LinearEdgeModel(
        fold_id=fold_id,
        feature_mean=feature_mean,
        feature_std=feature_std,
        score_direction=direction,
        feature_weights=weights,
        train_candidate_count=len(labeled),
        global_mean=float(labels.mean()),
        positive_label_rate=float(np.mean(positive_mask)),
        adverse_label_rate=float(np.mean(adverse_mask)),
        label_std=label_std,
    )


def score_candidates(candidates: list[base.Candidate], model: LinearEdgeModel) -> list[base.Candidate]:
    if not candidates:
        return []
    features = np.asarray([candidate.features for candidate in candidates], dtype=float)
    scaled = (features - model.feature_mean) / model.feature_std
    score_vector = model.score_direction * model.feature_weights
    denominator = math.sqrt(max(len(score_vector), 1))
    scores = (scaled @ score_vector) / denominator
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


def select_loss_memory_trades(
    bars: list[base.Bar],
    range_average: list[float | None],
    scored: list[base.Candidate],
    window: base.SplitWindow,
    model: LinearEdgeModel,
) -> list[base.Trade]:
    best_by_day_index: dict[tuple[str, int], base.Candidate] = {}
    for candidate in scored:
        if candidate.score is None:
            continue
        key = (candidate.day, candidate.index)
        existing = best_by_day_index.get(key)
        if existing is None or (candidate.score or 0.0) > (existing.score or 0.0):
            best_by_day_index[key] = candidate
    grouped: dict[str, list[base.Candidate]] = {}
    for candidate in best_by_day_index.values():
        grouped.setdefault(candidate.day, []).append(candidate)

    window_end_index = base.last_index_at_or_before(bars, window.end)
    next_available_index = 0
    month_pnl: dict[str, float] = {}
    month_loss_streak: dict[str, int] = {}
    trades: list[base.Trade] = []
    train_penalty = train_state_downside_penalty(model)

    for day in sorted(grouped):
        day_selected_indices: list[int] = []
        for candidate in sorted(grouped[day], key=lambda row: row.index):
            entry_index = candidate.index + 1
            if entry_index <= next_available_index or entry_index >= window_end_index:
                continue
            if bars[entry_index].time - bars[candidate.index].time > base.MAX_ENTRY_GAP:
                continue
            if any(abs(candidate.index - prior_index) < base.MIN_SIGNAL_SPACING_BARS for prior_index in day_selected_indices):
                continue
            month_key = bars[entry_index].time.strftime("%Y-%m")
            month_loss = month_pnl.get(month_key, 0.0)
            loss_streak = month_loss_streak.get(month_key, 0)
            day_budget = loss_memory_day_budget(month_loss, loss_streak)
            if day_budget <= 0 or len(day_selected_indices) >= day_budget:
                break
            adjusted_score = loss_memory_adjusted_score(candidate.score or 0.0, month_loss, loss_streak, train_penalty)
            if adjusted_score < SCORE_ABSTENTION_FLOOR:
                continue
            average_range = range_average[candidate.index]
            if average_range is None or average_range <= 0:
                continue
            trade = base.build_trade(bars, candidate, entry_index, average_range, window_end_index)
            if base.exit_close_gap_exceeds_limit(bars, trade.exit_time):
                continue
            trades.append(trade)
            day_selected_indices.append(candidate.index)
            next_available_index = base.first_index_at_or_after(bars, trade.exit_time)
            month_pnl[month_key] = month_loss + trade.pnl_points
            if trade.pnl_points < 0.0:
                month_loss_streak[month_key] = loss_streak + 1
            else:
                month_loss_streak[month_key] = max(loss_streak - 1, 0)
    return trades


def train_state_downside_penalty(model: LinearEdgeModel) -> float:
    adverse_excess = max(0.0, model.adverse_label_rate - model.positive_label_rate)
    return TRAIN_DOWNSIDE_PENALTY_SCALE * adverse_excess


def loss_memory_day_budget(month_loss: float, loss_streak: int) -> int:
    if month_loss <= MONTH_HARD_LOSS_LIMIT_POINTS or loss_streak >= LOSS_STREAK_HARD_LIMIT:
        return 0
    if month_loss <= MONTH_SOFT_LOSS_LIMIT_POINTS or loss_streak >= LOSS_STREAK_SOFT_LIMIT:
        return 3
    return base.MAX_ENTRIES_PER_ACTIVE_DAY


def loss_memory_adjusted_score(score: float, month_loss: float, loss_streak: int, train_penalty: float) -> float:
    month_penalty = MONTH_LOSS_PENALTY_PER_POINT * max(0.0, -month_loss)
    streak_penalty = LOSS_STREAK_SCORE_PENALTY * max(0, loss_streak)
    return score - month_penalty - streak_penalty - train_penalty


def build_proxy_payload(
    trades: list[base.Trade],
    windows: dict[str, dict[str, base.SplitWindow]],
    fold_models: list[dict[str, object]],
    state_distributions: dict[str, dict[str, float | int | None]],
    candidates_by_fold: dict[str, dict[str, int]],
) -> dict[str, object]:
    payload = replace_run_markers(base.build_proxy_payload(trades, windows, fold_models, state_distributions, candidates_by_fold))
    payload["campaign_id"] = "C0010"
    payload["work_unit_id"] = "C0010"
    payload["run_id"] = "R0002"
    payload["proxy_id"] = "PX-C0010-R0002"
    payload["proxy_engine"] = "axiom_rift.proxies.c0010_r0002_monthly_loss_memory_abstention"
    payload["proxy_config_path"] = "campaigns/C0010_monthly_regime_risk_control_discovery/runs/R0002/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_monthly_loss_memory_abstention_rank_fit"
    payload["proxy_artifact_paths"] = [
        "campaigns/C0010_monthly_regime_risk_control_discovery/runs/R0002/kpi/proxy.json",
        "campaigns/C0010_monthly_regime_risk_control_discovery/runs/R0002/artifacts/c0010_r0002_proxy_trades.csv",
        "campaigns/C0010_monthly_regime_risk_control_discovery/runs/R0002/artifacts/c0010_r0002_monthly_loss_memory_abstention_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["monthly_loss_memory_abstention_profile"] = {  # type: ignore[index]
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
            "month_soft_loss_limit_points": MONTH_SOFT_LOSS_LIMIT_POINTS,
            "month_hard_loss_limit_points": MONTH_HARD_LOSS_LIMIT_POINTS,
            "loss_streak_soft_limit": LOSS_STREAK_SOFT_LIMIT,
            "loss_streak_hard_limit": LOSS_STREAK_HARD_LIMIT,
            "score_abstention_floor": SCORE_ABSTENTION_FLOOR,
            "month_loss_penalty_per_point": MONTH_LOSS_PENALTY_PER_POINT,
            "loss_streak_score_penalty": LOSS_STREAK_SCORE_PENALTY,
            "train_downside_penalty_scale": TRAIN_DOWNSIDE_PENALTY_SCALE,
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
            "next_action": "produce_c0010_r0002_mt5_logic_parity_evidence",
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
            "month_soft_loss_limit_points": MONTH_SOFT_LOSS_LIMIT_POINTS,
            "month_hard_loss_limit_points": MONTH_HARD_LOSS_LIMIT_POINTS,
            "loss_streak_soft_limit": LOSS_STREAK_SOFT_LIMIT,
            "loss_streak_hard_limit": LOSS_STREAK_HARD_LIMIT,
            "score_abstention_floor": SCORE_ABSTENTION_FLOOR,
            "month_loss_penalty_per_point": MONTH_LOSS_PENALTY_PER_POINT,
            "loss_streak_score_penalty": LOSS_STREAK_SCORE_PENALTY,
            "train_downside_penalty_scale": TRAIN_DOWNSIDE_PENALTY_SCALE,
            "score_interpretation": "higher_centered_score_means_fold_local_monthly_loss_memory_abstention_quality",
            "variant_boundary": "sequential_month_to_date_loss_memory_abstention_not_score_floor_quantile_daily_count_stop_target_hold_session_or_retry_nudge",
        }
    )
    return config


def linear_model_summary(model: LinearEdgeModel) -> dict[str, object]:
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
        "score_direction": [base.rounded(float(value)) for value in model.score_direction],
        "feature_mean": [base.rounded(float(value)) for value in model.feature_mean],
        "feature_std": [base.rounded(float(value)) for value in model.feature_std],
        "score_interpretation": "higher_centered_score_means_fold_local_monthly_loss_memory_abstention_quality",
    }


def loss_memory_distribution(
    scored: list[base.Candidate],
    trades: list[base.Trade],
    model: LinearEdgeModel,
) -> dict[str, float | int | None]:
    scores = [candidate.score or 0.0 for candidate in scored if candidate.score is not None]
    selected_scores = [trade.score for trade in trades]
    eligible_hits = sum(1 for candidate in scored if candidate.score is not None)
    return {
        "candidate_count": len(scored),
        "eligible_candidate_count": eligible_hits,
        "eligible_candidate_rate": base.rounded(eligible_hits / len(scored)) if scored else None,
        "selected_count": len(trades),
        "train_candidate_count": model.train_candidate_count,
        "train_downside_penalty": base.rounded(train_state_downside_penalty(model)),
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
    write_regime_summary_artifact(payload, REGIME_SUMMARY_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = base.sha256_file(TRADE_ARTIFACT_PATH)
    summary_hash = base.sha256_file(REGIME_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = base.sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)


def write_regime_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_fold_local_monthly_loss_memory_abstention_summary_v1",
        "template": False,
        "work_unit_id": "C0010",
        "campaign_id": "C0010",
        "run_id": "R0002",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "monthly_loss_memory_abstention_profile": profiles["monthly_loss_memory_abstention_profile"]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "monthly_loss_memory_abstention_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-C0010-R0002-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0010_monthly_regime_risk_control_discovery/runs/R0002/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0010_monthly_regime_risk_control_discovery/runs/R0002/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-C0010-R0002-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0010_monthly_regime_risk_control_discovery/runs/R0002/artifacts/c0010_r0002_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0010_monthly_regime_risk_control_discovery/runs/R0002/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0010-R0002-MONTHLY-LOSS-MEMORY-ABSTENTION-SUMMARY",
                "monthly_loss_memory_abstention_summary_artifact",
                "json",
                "campaigns/C0010_monthly_regime_risk_control_discovery/runs/R0002/artifacts/c0010_r0002_monthly_loss_memory_abstention_summary.json",
                summary_hash,
                ["campaigns/C0010_monthly_regime_risk_control_discovery/runs/R0002/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0010_r0002_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0010_r0002_monthly_loss_memory_abstention",
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
    evidence["proxy_trade_artifact"] = "artifacts/c0010_r0002_proxy_trades.csv"
    evidence["monthly_loss_memory_abstention_summary"] = "artifacts/c0010_r0002_monthly_loss_memory_abstention_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0010_r0002_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0010_r0002_proxy_trades.csv",
        "artifacts/c0010_r0002_monthly_loss_memory_abstention_summary.json",
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
            "revisit_when": "after C0010 R0002 MT5 evidence files contain measured results",
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
    next_candidate["direction"] = "active_c0010_r0002_mt5_logic_parity"
    next_candidate["reason"] = "R0002 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0010_r0002_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = "campaigns/C0010_monthly_regime_risk_control_discovery"
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = "campaigns/C0010_monthly_regime_risk_control_discovery"
    completed = list(next_work.get("completed") or [])
    for item in (
        "open_c0010_r0002_monthly_loss_memory_abstention_run",
        "produce_c0010_r0002_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_c0010_r0002_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_run"] = "campaigns/C0010_monthly_regime_risk_control_discovery/runs/R0002"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0010_monthly_regime_risk_control_discovery"
    data["active_run"] = "campaigns/C0010_monthly_regime_risk_control_discovery/runs/R0002"
    data["latest_operation"] = {
        "id": "produce_c0010_r0002_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0010_monthly_regime_risk_control_discovery/runs/R0002/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0010_r0002_mt5_logic_parity_evidence",
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
            "C0004": "C0010",
            "c0004_r0004_fold_local_state_archetype": "c0010_r0002_monthly_loss_memory_abstention",
            "c0004_r0004": "c0010_r0002",
            "fold_local_state_archetype_discovery": "monthly_regime_risk_control_discovery",
            "fold_local_train_only_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "monthly_loss_memory_abstention_summary",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
