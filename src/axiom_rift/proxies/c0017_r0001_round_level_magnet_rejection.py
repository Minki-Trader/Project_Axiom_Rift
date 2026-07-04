"""C0017 R0001 proxy evidence for round-level magnet rejection discovery."""

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


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0017_round_level_magnet_rejection_discovery" / "runs" / "R0001"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0017_round_level_magnet_rejection_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0017_r0001_proxy_trades.csv"
ROUND_LEVEL_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0017_r0001_round_level_magnet_rejection_summary.json"
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
    "anchor_distance_25_over_range",
    "anchor_distance_50_over_range",
    "anchor_distance_100_over_range",
    "opposite_distance_25_over_range",
    "round_proximity_25",
    "round_proximity_50",
    "round_proximity_100",
    "approach_to_anchor_3_over_range",
    "approach_to_anchor_6_over_range",
    "approach_to_anchor_12_over_range",
    "current_anchor_breach_over_range",
    "anchor_reclaim_close_over_range",
    "rejection_wick_fraction",
    "adverse_wick_fraction",
    "directional_body_fraction",
    "directional_close_location",
    "range_expansion_3_over_36",
    "range_compression_12_over_96",
    "day_anchor_position",
    "day_extreme_to_anchor_over_range",
    "level_cross_count_12",
    "time_since_anchor_touch_72",
    "directional_anchor_hold_6",
    "spread_over_range",
    "spread_pressure_48",
    "spread_relief_3_vs_24",
    "minutes_from_core_mid",
    "weekday_sin",
    "weekday_cos",
    "session_sin",
    "session_cos",
)
MODEL_FAMILY = "fold_local_round_level_magnet_rejection_rank"
LABEL_SHAPE = "directional_round_level_rejection_followthrough_quality"
POSITIVE_LABEL_THRESHOLD = 0.18
ADVERSE_LABEL_THRESHOLD = -0.36
FEATURE_WEIGHT_FLOOR = 0.25
FEATURE_WEIGHT_CEILING = 2.50
SELECTION_RULE = "top_fold_local_round_level_magnet_rejection_scores_per_active_day"


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


def run_c0017_r0001_proxy(write: bool = True) -> dict[str, object]:
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
    day_context = build_day_context(bars)
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
            day_context,
            split["train_is"],
            fold_id,
            include_labels=True,
        )
        model = fit_linear_edge_model(train_candidates, fold_id)
        test_candidates = build_candidates(
            bars,
            range_average,
            short_range_average,
            day_context,
            split["test_oos"],
            fold_id,
            include_labels=False,
        )
        scored_candidates = score_candidates(test_candidates, model)
        selected = base.select_daily_candidates(scored_candidates)
        trades.extend(base.simulate_trades(bars, range_average, selected, split["test_oos"]))
        fold_models.append(linear_model_summary(model))
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
    day_context: list[dict[str, float] | None],
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
        288,
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
            features = round_level_magnet_rejection_features(
                bars,
                range_average,
                short_range_average,
                day_context,
                index,
                direction,
            )
            if features is None:
                continue
            label = (
                round_level_magnet_rejection_label(bars, range_average, index, direction)
                if include_labels
                else None
            )
            side = "long" if direction > 0 else "short"
            candidates.append(
                base.Candidate(
                    fold_id=fold_id,
                    index=index,
                    direction=direction,
                    day=bars[index].time.strftime("%Y-%m-%d"),
                    state_key=f"{side}|round_level_magnet_rejection",
                    features=features,
                    label=label,
                )
            )
    return candidates


def build_day_context(bars: list[base.Bar]) -> list[dict[str, float] | None]:
    contexts: list[dict[str, float] | None] = [None] * len(bars)
    current_day: str | None = None
    day_open = 0.0
    day_high = 0.0
    day_low = 0.0
    bars_since_day_open = 0
    for index, bar in enumerate(bars):
        day = bar.time.strftime("%Y-%m-%d")
        if current_day != day:
            current_day = day
            day_open = bar.open
            day_high = bar.high
            day_low = bar.low
            bars_since_day_open = 0
        else:
            day_high = max(day_high, bar.high)
            day_low = min(day_low, bar.low)
            bars_since_day_open += 1
        contexts[index] = {
            "day_open": day_open,
            "day_high": day_high,
            "day_low": day_low,
            "bars_since_day_open": float(bars_since_day_open),
        }
    return contexts


def round_level_magnet_rejection_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    day_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> tuple[float, ...] | None:
    average_range = range_average[index]
    short_average_range = short_range_average[index]
    if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
        return None
    context = day_context[index]
    if context is None:
        return None
    bar = bars[index]
    bar_range = max(bar.high - bar.low, 0.0)
    if bar_range <= 0:
        return None
    primary = round_context(bar.close, direction, 25.0)
    medium = round_context(bar.close, direction, 50.0)
    major = round_context(bar.close, direction, 100.0)
    anchor = primary["anchor"]
    anchor_distance_25 = primary["anchor_distance"] / average_range
    anchor_distance_50 = medium["anchor_distance"] / average_range
    anchor_distance_100 = major["anchor_distance"] / average_range
    opposite_distance_25 = primary["opposite_distance"] / average_range
    proximity_25 = round_proximity(primary["anchor_distance"], average_range)
    proximity_50 = round_proximity(medium["anchor_distance"], average_range)
    proximity_100 = round_proximity(major["anchor_distance"], average_range)
    approach_3 = approach_to_anchor(bars, index, direction, 3, average_range)
    approach_6 = approach_to_anchor(bars, index, direction, 6, average_range)
    approach_12 = approach_to_anchor(bars, index, direction, 12, average_range)
    day_high = context["day_high"]
    day_low = context["day_low"]
    day_range = max(day_high - day_low, 1e-9)
    range_3 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 2, index + 1)) / 3.0
    range_12 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 11, index + 1)) / 12.0
    range_36 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 35, index + 1)) / 36.0
    range_48 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 47, index + 1)) / 48.0
    range_96 = sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - 95, index + 1)) / 96.0
    range_expansion = range_3 / max(range_36, 1e-9)
    range_compression = range_12 / max(range_96, 1e-9)
    body_fraction = direction * (bar.close - bar.open) / bar_range
    close_location = (bar.close - bar.low) / bar_range
    directional_close_location = close_location if direction > 0 else 1.0 - close_location
    lower_wick = max(min(bar.open, bar.close) - bar.low, 0.0)
    upper_wick = max(bar.high - max(bar.open, bar.close), 0.0)
    rejection_wick_fraction = lower_wick / bar_range if direction > 0 else upper_wick / bar_range
    adverse_tail_fraction = upper_wick / bar_range if direction > 0 else lower_wick / bar_range
    if direction > 0:
        anchor_breach = max(anchor - bar.low, 0.0) / average_range
        anchor_reclaim = (bar.close - anchor) / average_range
        day_anchor_position = (anchor - day_low) / day_range
        day_extreme_to_anchor = (anchor - day_low) / average_range
    else:
        anchor_breach = max(bar.high - anchor, 0.0) / average_range
        anchor_reclaim = (anchor - bar.close) / average_range
        day_anchor_position = (day_high - anchor) / day_range
        day_extreme_to_anchor = (day_high - anchor) / average_range
    level_cross_count = anchor_cross_count(bars, index, anchor, 12)
    time_since_touch = time_since_anchor_touch(bars, index, anchor, 72)
    anchor_hold = directional_anchor_hold(bars, index, direction, anchor, 6)
    spread_over_range = bar.spread_points / average_range
    spread_3 = sum(bars[offset].spread_points for offset in range(index - 2, index + 1)) / 3.0
    spread_24 = sum(bars[offset].spread_points for offset in range(index - 23, index + 1)) / 24.0
    spread_48 = sum(bars[offset].spread_points for offset in range(index - 47, index + 1)) / 48.0
    spread_pressure = bar.spread_points / max(spread_48, 1e-9)
    spread_relief = (spread_24 - spread_3) / max(spread_24, 1e-9)
    minute_fraction = base.minute_of_day(bar.time) / (24.0 * 60.0)
    session_sin = math.sin(2.0 * math.pi * minute_fraction)
    session_cos = math.cos(2.0 * math.pi * minute_fraction)
    minutes_from_core_mid = (base.minute_of_day(bar.time) - (14 * 60 + 30)) / (24.0 * 60.0)
    weekday_fraction = bar.time.weekday() / 5.0
    weekday_sin = math.sin(2.0 * math.pi * weekday_fraction)
    weekday_cos = math.cos(2.0 * math.pi * weekday_fraction)
    if spread_over_range > 0.65 or spread_pressure > 2.20:
        return None
    return (
        anchor_distance_25,
        anchor_distance_50,
        anchor_distance_100,
        opposite_distance_25,
        proximity_25,
        proximity_50,
        proximity_100,
        approach_3,
        approach_6,
        approach_12,
        anchor_breach,
        anchor_reclaim,
        rejection_wick_fraction,
        adverse_tail_fraction,
        body_fraction,
        directional_close_location,
        range_expansion,
        range_compression,
        day_anchor_position,
        day_extreme_to_anchor,
        level_cross_count,
        time_since_touch,
        anchor_hold,
        spread_over_range,
        spread_pressure,
        spread_relief,
        minutes_from_core_mid,
        weekday_sin,
        weekday_cos,
        session_sin,
        session_cos,
    )


def round_context(price: float, direction: int, interval: float) -> dict[str, float]:
    lower = math.floor(price / interval) * interval
    upper = math.ceil(price / interval) * interval
    if upper <= lower:
        upper = lower + interval
    if direction > 0:
        anchor = lower
        opposite = upper
        anchor_distance = max(price - anchor, 0.0)
        opposite_distance = max(opposite - price, 0.0)
    else:
        anchor = upper
        opposite = lower
        anchor_distance = max(anchor - price, 0.0)
        opposite_distance = max(price - opposite, 0.0)
    return {
        "anchor": anchor,
        "opposite": opposite,
        "anchor_distance": anchor_distance,
        "opposite_distance": opposite_distance,
    }


def round_proximity(distance: float, average_range: float) -> float:
    return max(0.0, 1.0 - distance / max(average_range, 1e-9))


def approach_to_anchor(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    return -direction * (bars[index].close - bars[index - lookback].close) / average_range


def anchor_cross_count(bars: list[base.Bar], index: int, anchor: float, lookback: int) -> float:
    closes = [bars[offset].close for offset in range(index - lookback + 1, index + 1)]
    signs = [1 if close >= anchor else -1 for close in closes]
    crosses = sum(1 for left, right in zip(signs, signs[1:]) if left != right)
    return crosses / max(lookback - 1, 1)


def time_since_anchor_touch(bars: list[base.Bar], index: int, anchor: float, lookback: int) -> float:
    for offset in range(index, index - lookback, -1):
        if bars[offset].low <= anchor <= bars[offset].high:
            return (index - offset) / lookback
    return 1.0


def directional_anchor_hold(
    bars: list[base.Bar],
    index: int,
    direction: int,
    anchor: float,
    lookback: int,
) -> float:
    if direction > 0:
        held = sum(1 for offset in range(index - lookback + 1, index + 1) if bars[offset].close >= anchor)
    else:
        held = sum(1 for offset in range(index - lookback + 1, index + 1) if bars[offset].close <= anchor)
    return held / lookback


def round_level_magnet_rejection_label(
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
    anchor = round_context(bars[index].close, direction, 25.0)["anchor"]
    stop_distance = base.STOP_RANGE_MULTIPLE * average_range
    target_distance = base.TARGET_RANGE_MULTIPLE * average_range
    stop_price = entry - direction * stop_distance
    target_price = entry + direction * target_distance
    first_hit = 0.0
    event_bar = len(path)
    adverse_first = 0.0
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
                adverse_first = 1.0
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
                adverse_first = 1.0
                break
            if hit_target:
                first_hit = 1.0
                event_bar = offset
                break
    favorable = mfe / average_range
    adverse = mae / average_range
    terminal_norm = terminal / average_range
    path_alignment = aligned_close_count / len(path)
    close_path = [entry] + [bar.close for bar in path]
    path_distance = sum(abs(close_path[offset] - close_path[offset - 1]) for offset in range(1, len(close_path)))
    path_efficiency = terminal / max(path_distance, 1e-9)
    adverse_close_flips = sum(
        1
        for offset in range(1, len(close_path))
        if direction * (close_path[offset] - close_path[offset - 1]) < 0
    ) / max(len(close_path) - 1, 1)
    target_speed = (len(path) - event_bar + 1) / len(path) if first_hit > 0.0 else 0.0
    stop_speed = (len(path) - event_bar + 1) / len(path) if first_hit < 0.0 else 0.0
    giveback = max(0.0, favorable - max(terminal_norm, 0.0))
    path_alignment_edge = path_alignment - 0.5
    early_path = path[: min(3, len(path))]
    if direction > 0:
        early_followthrough = max(bar.high - entry for bar in early_path) / average_range
        early_adverse = max(entry - bar.low for bar in early_path) / average_range
        close_through = (early_path[-1].close - entry) / average_range
    else:
        early_followthrough = max(entry - bar.low for bar in early_path) / average_range
        early_adverse = max(bar.high - entry for bar in early_path) / average_range
        close_through = (entry - early_path[-1].close) / average_range
    spread_norm = bars[entry_index].spread_points / average_range
    path_spread_peak = max(bar.spread_points for bar in path) / average_range
    spread_drift = max(0.0, path_spread_peak - spread_norm)
    if direction > 0:
        anchor_hold = sum(1 for bar in path if bar.close >= anchor) / len(path)
        anchor_failure_depth = max(anchor - bar.low for bar in path) / average_range
        anchor_recross_count = sum(1 for bar in path if bar.close < anchor) / len(path)
    else:
        anchor_hold = sum(1 for bar in path if bar.close <= anchor) / len(path)
        anchor_failure_depth = max(bar.high - anchor for bar in path) / average_range
        anchor_recross_count = sum(1 for bar in path if bar.close > anchor) / len(path)
    return (
        0.82 * first_hit
        + 0.34 * target_speed
        - 0.46 * stop_speed
        - 0.58 * adverse_first
        + 0.30 * early_followthrough
        - 0.34 * early_adverse
        + 0.28 * close_through
        + 0.36 * (anchor_hold - 0.5)
        - 0.42 * max(anchor_failure_depth, 0.0)
        - 0.24 * anchor_recross_count
        + 0.28 * favorable
        - 0.62 * adverse
        + 0.38 * terminal_norm
        + 0.34 * path_efficiency
        - 0.30 * giveback
        + 0.22 * path_alignment_edge
        - 0.26 * adverse_close_flips
        - 1.08 * spread_norm
        - 0.20 * spread_drift
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
    scores = model.global_mean + (scaled @ score_vector) / denominator
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
    payload["campaign_id"] = "C0017"
    payload["work_unit_id"] = "C0017"
    payload["run_id"] = "R0001"
    payload["proxy_id"] = "PX-C0017-R0001"
    payload["proxy_engine"] = "axiom_rift.proxies.c0017_r0001_round_level_magnet_rejection"
    payload["proxy_config_path"] = "campaigns/C0017_round_level_magnet_rejection_discovery/runs/R0001/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_round_level_magnet_rejection_rank_fit"
    payload["proxy_artifact_paths"] = [
        "campaigns/C0017_round_level_magnet_rejection_discovery/runs/R0001/kpi/proxy.json",
        "campaigns/C0017_round_level_magnet_rejection_discovery/runs/R0001/artifacts/c0017_r0001_proxy_trades.csv",
        "campaigns/C0017_round_level_magnet_rejection_discovery/runs/R0001/artifacts/c0017_r0001_round_level_magnet_rejection_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["round_level_magnet_rejection_profile"] = {  # type: ignore[index]
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
            "next_action": "produce_c0017_r0001_mt5_logic_parity_evidence",
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
            "score_interpretation": "higher_score_means_direct_fold_local_round_level_magnet_rejection_rank",
            "variant_boundary": "round_level_magnet_rejection_rank_not_auction_threshold_monthly_memory_lifecycle_structural_trap_score_floor_stop_target_hold_or_retry_nudge",
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
        "score_interpretation": "higher_score_means_direct_fold_local_round_level_magnet_rejection_rank",
    }


def score_distribution(
    scored: list[base.Candidate],
    selected: list[base.Candidate],
    model: LinearEdgeModel,
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
    write_round_level_magnet_rejection_summary_artifact(payload, ROUND_LEVEL_SUMMARY_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = base.sha256_file(TRADE_ARTIFACT_PATH)
    summary_hash = base.sha256_file(ROUND_LEVEL_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = base.sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)


def write_round_level_magnet_rejection_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_fold_local_round_level_magnet_rejection_summary_v1",
        "template": False,
        "work_unit_id": "C0017",
        "campaign_id": "C0017",
        "run_id": "R0001",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "round_level_magnet_rejection_profile": profiles["round_level_magnet_rejection_profile"]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "round_level_magnet_rejection_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-C0017-R0001-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0017_round_level_magnet_rejection_discovery/runs/R0001/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0017_round_level_magnet_rejection_discovery/runs/R0001/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-C0017-R0001-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0017_round_level_magnet_rejection_discovery/runs/R0001/artifacts/c0017_r0001_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0017_round_level_magnet_rejection_discovery/runs/R0001/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0017-R0001-ROUND-LEVEL-MAGNET-REJECTION-SUMMARY",
                "round_level_magnet_rejection_summary_artifact",
                "json",
                "campaigns/C0017_round_level_magnet_rejection_discovery/runs/R0001/artifacts/c0017_r0001_round_level_magnet_rejection_summary.json",
                summary_hash,
                ["campaigns/C0017_round_level_magnet_rejection_discovery/runs/R0001/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0017_r0001_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0017_r0001_round_level_magnet_rejection",
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
    evidence["proxy_trade_artifact"] = "artifacts/c0017_r0001_proxy_trades.csv"
    evidence["round_level_magnet_rejection_summary"] = "artifacts/c0017_r0001_round_level_magnet_rejection_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0017_r0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0017_r0001_proxy_trades.csv",
        "artifacts/c0017_r0001_round_level_magnet_rejection_summary.json",
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
            "revisit_when": "after C0017 R0001 MT5 evidence files contain measured results",
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
    next_candidate["direction"] = "active_c0017_r0001_mt5_logic_parity"
    next_candidate["reason"] = "R0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0017_r0001_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = "campaigns/C0017_round_level_magnet_rejection_discovery"
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = "campaigns/C0017_round_level_magnet_rejection_discovery"
    completed = list(next_work.get("completed") or [])
    for item in (
        "open_c0017_round_level_magnet_rejection_discovery",
        "open_c0017_r0001_fold_local_round_level_magnet_rejection_rank_run",
        "produce_c0017_r0001_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_c0017_r0001_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_run"] = "campaigns/C0017_round_level_magnet_rejection_discovery/runs/R0001"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0017_round_level_magnet_rejection_discovery"
    data["active_run"] = "campaigns/C0017_round_level_magnet_rejection_discovery/runs/R0001"
    data["latest_operation"] = {
        "id": "produce_c0017_r0001_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0017_round_level_magnet_rejection_discovery/runs/R0001/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0017_r0001_mt5_logic_parity_evidence",
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
            "C0004": "C0017",
            "c0004_r0001_fold_local_state_archetype": "c0017_r0001_round_level_magnet_rejection",
            "c0004_r0001": "c0017_r0001",
            "fold_local_state_archetype_discovery": "round_level_magnet_rejection_discovery",
            "fold_local_train_only_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "round_level_magnet_rejection_summary",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

