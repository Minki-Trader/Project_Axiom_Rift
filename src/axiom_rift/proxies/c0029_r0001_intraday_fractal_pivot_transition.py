"""C0029 R0001 proxy evidence for intraday fractal pivot transition discovery."""

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


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0029_intraday_fractal_pivot_transition_discovery" / "runs" / "R0001"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0029_intraday_fractal_pivot_transition_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0029_r0001_proxy_trades.csv"
INTRADAY_FRACTAL_PIVOT_TRANSITION_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0029_r0001_intraday_fractal_pivot_transition_summary.json"
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
    "direction_bias",
    "pivot_type_alignment_48",
    "bars_since_last_confirmed_pivot_48",
    "distance_from_last_pivot_atr",
    "last_pivot_age_weighted_distance",
    "last_pivot_retest_distance_atr",
    "confirmed_pivot_high_age_48",
    "confirmed_pivot_low_age_48",
    "distance_to_recent_pivot_high_atr",
    "distance_to_recent_pivot_low_atr",
    "directional_pivot_box_position_48",
    "pivot_midline_pressure_48",
    "pivot_span_atr_48",
    "pivot_alternation_rate_48",
    "pivot_frequency_48",
    "same_side_pivot_cluster_48",
    "pivot_breakout_pressure_12",
    "pivot_reclaim_rate_12",
    "pivot_failed_break_rate_12",
    "directional_escape_from_pivot_6",
    "pivot_retest_rate_12",
    "pivot_rejection_wick_mean_3",
    "pivot_follow_wick_mean_3",
    "pivot_wick_asymmetry_3",
    "directional_close_location_1",
    "directional_close_location_mean_3",
    "body_agreement_1",
    "body_agreement_rate_6",
    "directional_close_streak_6",
    "adverse_close_streak_6",
    "range_tier_1",
    "range_tier_mean_6",
    "range_contraction_near_pivot_3",
    "inside_rate_6",
    "average_overlap_ratio_6",
    "churn_ratio_12",
    "directional_path_efficiency_12",
    "counter_move_pressure_6",
    "directional_range_position_12",
    "day_range_position_directional",
    "cumulative_day_range_pressure",
    "spread_over_range",
    "spread_relief_3_vs_24",
    "session_position",
)
MODEL_FAMILY = "fold_local_intraday_fractal_pivot_transition_rank"
LABEL_SHAPE = "directional_intraday_fractal_pivot_transition_survival_quality"
POSITIVE_LABEL_THRESHOLD = 0.18
ADVERSE_LABEL_THRESHOLD = -0.36
FEATURE_WEIGHT_FLOOR = 0.25
FEATURE_WEIGHT_CEILING = 2.50
SELECTION_RULE = "top_fold_local_intraday_fractal_pivot_transition_scores_per_active_day"


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


def run_c0029_r0001_proxy(write: bool = True) -> dict[str, object]:
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
    pivot_context = build_pivot_context(bars, 48)
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
            pivot_context,
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
            pivot_context,
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
    pivot_context: list[dict[str, object]],
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
            features = intraday_fractal_pivot_transition_features(
                bars,
                range_average,
                short_range_average,
                day_context,
                pivot_context,
                index,
                direction,
            )
            if features is None:
                continue
            label = (
                intraday_fractal_pivot_transition_label(bars, range_average, pivot_context, index, direction)
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
                    state_key=f"{side}|intraday_fractal_pivot_transition",
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
    cumulative_range = 0.0
    for index, bar in enumerate(bars):
        day = bar.time.strftime("%Y-%m-%d")
        bar_range = max(bar.high - bar.low, 0.0)
        if current_day != day:
            current_day = day
            day_open = bar.open
            day_high = bar.high
            day_low = bar.low
            bars_since_day_open = 0
            cumulative_range = bar_range
        else:
            day_high = max(day_high, bar.high)
            day_low = min(day_low, bar.low)
            bars_since_day_open += 1
            cumulative_range += bar_range
        contexts[index] = {
            "day_open": day_open,
            "day_high": day_high,
            "day_low": day_low,
            "bars_since_day_open": float(bars_since_day_open),
            "cumulative_range": cumulative_range,
        }
    return contexts


def build_pivot_context(bars: list[base.Bar], lookback: int) -> list[dict[str, object]]:
    contexts: list[dict[str, object]] = []
    for index in range(len(bars)):
        pivots = confirmed_fractal_pivots(bars, index, lookback)
        high = next((price for _, pivot_type, price in reversed(pivots) if pivot_type < 0), None)
        low = next((price for _, pivot_type, price in reversed(pivots) if pivot_type > 0), None)
        contexts.append({"pivots": pivots, "high": high, "low": low})
    return contexts


def intraday_fractal_pivot_transition_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    day_context: list[dict[str, float] | None],
    pivot_context: list[dict[str, object]],
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
    spread_over_range = bar.spread_points / average_range
    spread_3 = sum(bars[offset].spread_points for offset in range(index - 2, index + 1)) / 3.0
    spread_24 = sum(bars[offset].spread_points for offset in range(index - 23, index + 1)) / 24.0
    spread_relief = (spread_24 - spread_3) / max(spread_24, 1e-9)
    if spread_over_range > 0.65:
        return None
    pivot = fractal_pivot_transition_state(bars, pivot_context, index, direction, 48, average_range)
    if pivot is None:
        return None
    close_streak = directional_close_streak(bars, index, direction, 6)
    rejection_3 = directional_rejection_wick(bars, index, direction, 3)
    follow_3 = directional_follow_wick(bars, index, direction, 3)
    return (
        float(direction),
        pivot["pivot_type_alignment"],
        pivot["bars_since_last_pivot"],
        pivot["distance_from_last_pivot_atr"],
        pivot["last_pivot_age_weighted_distance"],
        pivot["last_pivot_retest_distance_atr"],
        pivot["confirmed_pivot_high_age"],
        pivot["confirmed_pivot_low_age"],
        pivot["distance_to_recent_pivot_high_atr"],
        pivot["distance_to_recent_pivot_low_atr"],
        pivot["directional_pivot_box_position"],
        pivot["pivot_midline_pressure"],
        pivot["pivot_span_atr"],
        pivot["pivot_alternation_rate"],
        pivot["pivot_frequency"],
        pivot["same_side_pivot_cluster"],
        pivot_breakout_rate(bars, pivot_context, index, direction, 12),
        pivot_reclaim_rate(bars, pivot_context, index, direction, 12),
        pivot_failed_break_rate(bars, pivot_context, index, direction, 12),
        direction * (bars[index].close - bars[index - 6].close) / average_range,
        pivot_retest_rate(bars, pivot_context, index, direction, 12, average_range),
        rejection_3,
        follow_3,
        rejection_3 - follow_3,
        directional_close_location(bar, direction),
        directional_close_location_mean(bars, index, direction, 3),
        direction * body_direction(bar),
        direction * body_direction_sum(bars, index, 6) / 6.0,
        close_streak,
        max(0.0, -close_streak),
        range_tier_at(bars, range_average, index),
        range_tier_mean(bars, range_average, index, 6),
        range_contraction_near_pivot(bars, index, average_range),
        inside_bar_count(bars, index, 6),
        average_overlap_ratio(bars, index, 6),
        path_churn_ratio(bars, index, 12),
        directional_efficiency(bars, index, direction, 12),
        counter_move_pressure(bars, index, direction, 6, average_range),
        directional_range_position(bars, index, direction, 12),
        day_range_position_directional(bars, context, index, direction),
        cumulative_day_range_pressure(bars, context, index, direction, average_range),
        spread_over_range,
        spread_relief,
        session_position(context),
    )


def fractal_pivot_transition_state(
    bars: list[base.Bar],
    pivot_context: list[dict[str, object]],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> dict[str, float] | None:
    pivots = pivot_context[index].get("pivots", [])
    if average_range <= 0 or not pivots:
        return None
    last_index, last_type, last_price = pivots[-1]
    high_pivot = next((pivot for pivot in reversed(pivots) if pivot[1] < 0), None)
    low_pivot = next((pivot for pivot in reversed(pivots) if pivot[1] > 0), None)
    if high_pivot is None or low_pivot is None:
        return None
    high_index, _, high_price = high_pivot
    low_index, _, low_price = low_pivot
    pivot_span = max(high_price - low_price, 1e-9)
    box_position = bounded((bars[index].close - low_price) / pivot_span, -0.5, 1.5)
    directional_position = box_position if direction > 0 else 1.0 - box_position
    same_side_count = sum(1 for _, pivot_type, _ in pivots if pivot_type == last_type)
    changes = sum(1 for left, right in zip(pivots, pivots[1:]) if left[1] != right[1])
    distance_from_last = direction * (bars[index].close - last_price) / average_range
    high_distance = (high_price - bars[index].close) / average_range
    low_distance = (bars[index].close - low_price) / average_range
    if direction < 0:
        high_distance = -high_distance
        low_distance = -low_distance
    return {
        "pivot_type_alignment": float(direction * last_type),
        "bars_since_last_pivot": bounded((index - last_index) / lookback, 0.0, 1.5),
        "distance_from_last_pivot_atr": distance_from_last,
        "last_pivot_age_weighted_distance": distance_from_last / max(index - last_index + 1, 1),
        "last_pivot_retest_distance_atr": abs(bars[index].close - last_price) / average_range,
        "confirmed_pivot_high_age": bounded((index - high_index) / lookback, 0.0, 1.5),
        "confirmed_pivot_low_age": bounded((index - low_index) / lookback, 0.0, 1.5),
        "distance_to_recent_pivot_high_atr": high_distance,
        "distance_to_recent_pivot_low_atr": low_distance,
        "directional_pivot_box_position": directional_position,
        "pivot_midline_pressure": direction * (bars[index].close - ((high_price + low_price) / 2.0)) / average_range,
        "pivot_span_atr": pivot_span / average_range,
        "pivot_alternation_rate": changes / max(len(pivots) - 1, 1),
        "pivot_frequency": len(pivots) / lookback,
        "same_side_pivot_cluster": same_side_count / len(pivots),
    }


def confirmed_fractal_pivots(
    bars: list[base.Bar],
    index: int,
    lookback: int,
) -> list[tuple[int, int, float]]:
    start = max(2, index - lookback + 1)
    end = index - 2
    pivots: list[tuple[int, int, float]] = []
    if end < start:
        return pivots
    for center in range(start, end + 1):
        window = bars[center - 2 : center + 3]
        center_high = bars[center].high
        center_low = bars[center].low
        if center_high >= max(bar.high for bar in window):
            pivots.append((center, -1, center_high))
        if center_low <= min(bar.low for bar in window):
            pivots.append((center, 1, center_low))
    pivots.sort(key=lambda item: (item[0], item[1]))
    return pivots


def latest_pivot_levels(
    pivot_context: list[dict[str, object]],
    index: int,
) -> tuple[float | None, float | None]:
    context = pivot_context[index]
    high = context.get("high")
    low = context.get("low")
    return high if isinstance(high, float) else None, low if isinstance(low, float) else None


def pivot_breakout_rate(
    bars: list[base.Bar],
    pivot_context: list[dict[str, object]],
    index: int,
    direction: int,
    lookback: int,
) -> float:
    count = 0
    total = 0
    for offset in range(index - lookback + 1, index + 1):
        high, low = latest_pivot_levels(pivot_context, offset)
        total += 1
        if direction > 0 and high is not None and bars[offset].close > high:
            count += 1
        if direction < 0 and low is not None and bars[offset].close < low:
            count += 1
    return count / max(total, 1)


def pivot_reclaim_rate(
    bars: list[base.Bar],
    pivot_context: list[dict[str, object]],
    index: int,
    direction: int,
    lookback: int,
) -> float:
    count = 0
    total = 0
    for offset in range(index - lookback + 1, index + 1):
        high, low = latest_pivot_levels(pivot_context, offset)
        total += 1
        if direction > 0 and low is not None and bars[offset].low <= low and bars[offset].close > low:
            count += 1
        if direction < 0 and high is not None and bars[offset].high >= high and bars[offset].close < high:
            count += 1
    return count / max(total, 1)


def pivot_failed_break_rate(
    bars: list[base.Bar],
    pivot_context: list[dict[str, object]],
    index: int,
    direction: int,
    lookback: int,
) -> float:
    count = 0
    total = 0
    for offset in range(index - lookback + 1, index + 1):
        high, low = latest_pivot_levels(pivot_context, offset)
        total += 1
        if direction > 0 and high is not None and bars[offset].high > high and bars[offset].close <= high:
            count += 1
        if direction < 0 and low is not None and bars[offset].low < low and bars[offset].close >= low:
            count += 1
    return count / max(total, 1)


def pivot_retest_rate(
    bars: list[base.Bar],
    pivot_context: list[dict[str, object]],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    count = 0
    total = 0
    tolerance = 0.18 * average_range
    for offset in range(index - lookback + 1, index + 1):
        high, low = latest_pivot_levels(pivot_context, offset)
        total += 1
        if direction > 0 and low is not None and abs(bars[offset].low - low) <= tolerance:
            count += 1
        if direction < 0 and high is not None and abs(bars[offset].high - high) <= tolerance:
            count += 1
    return count / max(total, 1)


def directional_close_location_mean(bars: list[base.Bar], index: int, direction: int, lookback: int) -> float:
    values = [directional_close_location(bars[offset], direction) for offset in range(index - lookback + 1, index + 1)]
    return sum(values) / lookback


def directional_pullback_bars(bars: list[base.Bar], index: int, direction: int, lookback: int) -> float:
    count = 0
    for offset in range(index - lookback + 1, index + 1):
        if direction * (bars[offset].close - bars[offset - 1].close) < 0:
            count += 1
    return count / lookback


def directional_new_extreme_rate(bars: list[base.Bar], index: int, direction: int, lookback: int) -> float:
    count = 0
    for offset in range(index - lookback + 1, index + 1):
        prior_start = max(0, offset - 6)
        if direction > 0:
            prior_extreme = max(bars[prior].high for prior in range(prior_start, offset))
            if bars[offset].high > prior_extreme:
                count += 1
        else:
            prior_extreme = min(bars[prior].low for prior in range(prior_start, offset))
            if bars[offset].low < prior_extreme:
                count += 1
    return count / lookback


def directional_failed_extension_rate(bars: list[base.Bar], index: int, direction: int, lookback: int) -> float:
    count = 0
    for offset in range(index - lookback + 1, index + 1):
        prior_start = max(0, offset - 6)
        if direction > 0:
            prior_extreme = max(bars[prior].high for prior in range(prior_start, offset))
            if bars[offset].high > prior_extreme and bars[offset].close <= prior_extreme:
                count += 1
        else:
            prior_extreme = min(bars[prior].low for prior in range(prior_start, offset))
            if bars[offset].low < prior_extreme and bars[offset].close >= prior_extreme:
                count += 1
    return count / lookback


def range_contraction_after_leg(bars: list[base.Bar], index: int, average_range: float) -> float:
    recent = average_bar_range(bars, index, 3)
    baseline = average_bar_range(bars, index - 3, 12)
    return (baseline - recent) / max(average_range, 1e-9)


def range_contraction_near_pivot(bars: list[base.Bar], index: int, average_range: float) -> float:
    recent = average_bar_range(bars, index, 3)
    baseline = average_bar_range(bars, index - 6, 12)
    return (baseline - recent) / max(average_range, 1e-9)


def counter_move_pressure(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    adverse = 0.0
    for offset in range(index - lookback + 1, index + 1):
        move = direction * (bars[offset].close - bars[offset - 1].close)
        adverse += max(0.0, -move)
    return adverse / max(average_range, 1e-9)


def directional_failed_break_pressure(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
) -> float:
    return directional_failed_extension_rate(bars, index, direction, lookback)


def day_range_position_directional(
    bars: list[base.Bar],
    context: dict[str, float],
    index: int,
    direction: int,
) -> float:
    span = max(context["day_high"] - context["day_low"], 1e-9)
    position = (bars[index].close - context["day_low"]) / span
    return position if direction > 0 else 1.0 - position


def cumulative_day_range_pressure(
    bars: list[base.Bar],
    context: dict[str, float],
    index: int,
    direction: int,
    average_range: float,
) -> float:
    directional_day_move = direction * (bars[index].close - context["day_open"])
    churn = max(context["cumulative_range"], average_range)
    return directional_day_move / churn


def bar_range(bar: base.Bar) -> float:
    return max(bar.high - bar.low, 0.0)


def body_direction(bar: base.Bar) -> int:
    if bar.close > bar.open:
        return 1
    if bar.close < bar.open:
        return -1
    return 0


def body_direction_at(bars: list[base.Bar], index: int) -> int:
    return body_direction(bars[index])


def body_direction_sum(bars: list[base.Bar], index: int, lookback: int) -> float:
    return float(sum(body_direction_at(bars, offset) for offset in range(index - lookback + 1, index + 1)))


def body_flip_rate(bars: list[base.Bar], index: int, lookback: int) -> float:
    signs = [body_direction_at(bars, offset) for offset in range(index - lookback + 1, index + 1)]
    pairs = [(left, right) for left, right in zip(signs, signs[1:]) if left != 0 and right != 0]
    if not pairs:
        return 0.0
    return sum(1 for left, right in pairs if left != right) / len(pairs)


def body_run_length(bars: list[base.Bar], index: int, cap: int) -> float:
    current = body_direction_at(bars, index)
    if current == 0:
        return 0.0
    run = 0
    for offset in range(index, index - cap, -1):
        if body_direction_at(bars, offset) != current:
            break
        run += 1
    return current * run / cap


def upper_wick_ratio(bar: base.Bar) -> float:
    return max(bar.high - max(bar.open, bar.close), 0.0) / max(bar_range(bar), 1e-9)


def lower_wick_ratio(bar: base.Bar) -> float:
    return max(min(bar.open, bar.close) - bar.low, 0.0) / max(bar_range(bar), 1e-9)


def directional_rejection_wick(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
) -> float:
    values = []
    for offset in range(index - lookback + 1, index + 1):
        values.append(lower_wick_ratio(bars[offset]) if direction > 0 else upper_wick_ratio(bars[offset]))
    return sum(values) / lookback


def directional_follow_wick(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
) -> float:
    values = []
    for offset in range(index - lookback + 1, index + 1):
        values.append(upper_wick_ratio(bars[offset]) if direction > 0 else lower_wick_ratio(bars[offset]))
    return sum(values) / lookback


def close_location(bar: base.Bar) -> float:
    return bounded((bar.close - bar.low) / max(bar_range(bar), 1e-9), 0.0, 1.0)


def directional_close_location(bar: base.Bar, direction: int) -> float:
    location = close_location(bar)
    return location if direction > 0 else 1.0 - location


def close_location_mean(bars: list[base.Bar], index: int, lookback: int) -> float:
    return sum(close_location(bars[offset]) for offset in range(index - lookback + 1, index + 1)) / lookback


def range_tier_at(bars: list[base.Bar], range_average: list[float | None], index: int) -> float:
    average = range_average[index]
    if average is None or average <= 0:
        return 1.0
    return bar_range(bars[index]) / average


def range_tier_mean(bars: list[base.Bar], range_average: list[float | None], index: int, lookback: int) -> float:
    return sum(range_tier_at(bars, range_average, offset) for offset in range(index - lookback + 1, index + 1)) / lookback


def narrow_wide_transition(bars: list[base.Bar], range_average: list[float | None], index: int, lookback: int) -> float:
    current = range_tier_at(bars, range_average, index)
    prior_mean = range_tier_mean(bars, range_average, index - 1, lookback - 1)
    return current - prior_mean


def containment_break_rate(bars: list[base.Bar], index: int, lookback: int) -> float:
    count = 0
    for offset in range(index - lookback + 1, index + 1):
        prior_high = max(bars[prior].high for prior in range(offset - 3, offset))
        prior_low = min(bars[prior].low for prior in range(offset - 3, offset))
        broke_prior_box = bars[offset].high > prior_high or bars[offset].low < prior_low
        closed_inside = prior_low <= bars[offset].close <= prior_high
        if broke_prior_box and closed_inside:
            count += 1
    return count / lookback


def directional_breakout_token(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
) -> float:
    count = 0
    for offset in range(index - lookback + 1, index + 1):
        prior_high = max(bars[prior].high for prior in range(offset - 3, offset))
        prior_low = min(bars[prior].low for prior in range(offset - 3, offset))
        if direction > 0 and bars[offset].close > prior_high:
            count += 1
        if direction < 0 and bars[offset].close < prior_low:
            count += 1
    return count / lookback


def directional_failed_break_token(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
) -> float:
    count = 0
    for offset in range(index - lookback + 1, index + 1):
        prior_high = max(bars[prior].high for prior in range(offset - 3, offset))
        prior_low = min(bars[prior].low for prior in range(offset - 3, offset))
        if direction > 0 and bars[offset].high > prior_high and bars[offset].close <= prior_high:
            count += 1
        if direction < 0 and bars[offset].low < prior_low and bars[offset].close >= prior_low:
            count += 1
    return count / lookback


def motif_trend_score(bars: list[base.Bar], index: int, direction: int) -> float:
    return direction * body_direction_sum(bars, index, 3) / 3.0


def motif_reversal_score(bars: list[base.Bar], index: int, direction: int) -> float:
    recent = direction * body_direction_sum(bars, index, 3) / 3.0
    prior = direction * body_direction_sum(bars, index - 3, 3) / 3.0
    return recent - prior


def motif_compression_score(bars: list[base.Bar], range_average: list[float | None], index: int) -> float:
    compression = inside_bar_count(bars, index, 3) + contained_range_count(bars, index, 3)
    range_penalty = range_tier_mean(bars, range_average, index, 3)
    return compression - range_penalty


def motif_expansion_score(bars: list[base.Bar], range_average: list[float | None], index: int) -> float:
    range_pop = max(0.0, range_tier_at(bars, range_average, index) - range_tier_mean(bars, range_average, index - 1, 3))
    return outside_bar_count(bars, index, 3) + range_pop


def grammar_token(bars: list[base.Bar], range_average: list[float | None], index: int) -> str:
    sign = body_direction_at(bars, index)
    sign_key = "u" if sign > 0 else "d" if sign < 0 else "f"
    tier = range_tier_at(bars, range_average, index)
    tier_key = "n" if tier < 0.70 else "w" if tier > 1.30 else "m"
    location = close_location(bars[index])
    location_key = "h" if location >= 0.67 else "l" if location <= 0.33 else "c"
    wick_delta = upper_wick_ratio(bars[index]) - lower_wick_ratio(bars[index])
    wick_key = "u" if wick_delta > 0.20 else "l" if wick_delta < -0.20 else "b"
    return f"{sign_key}{tier_key}{location_key}{wick_key}"


def grammar_entropy(bars: list[base.Bar], range_average: list[float | None], index: int, lookback: int) -> float:
    tokens = [grammar_token(bars, range_average, offset) for offset in range(index - lookback + 1, index + 1)]
    counts = {token: tokens.count(token) for token in set(tokens)}
    entropy = 0.0
    for count in counts.values():
        probability = count / lookback
        entropy -= probability * math.log(max(probability, 1e-12))
    return entropy / max(math.log(lookback), 1e-9)


def grammar_repeat_rate(bars: list[base.Bar], range_average: list[float | None], index: int, lookback: int) -> float:
    tokens = [grammar_token(bars, range_average, offset) for offset in range(index - lookback + 1, index + 1)]
    if len(tokens) <= 1:
        return 0.0
    return sum(1 for left, right in zip(tokens, tokens[1:]) if left == right) / (len(tokens) - 1)


def session_position(context: dict[str, float]) -> float:
    return bounded(context["bars_since_day_open"] / 288.0, 0.0, 1.0)


def bounded(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def bar_overlap_ratio(bars: list[base.Bar], index: int, other_index: int) -> float:
    intersection = max(0.0, min(bars[index].high, bars[other_index].high) - max(bars[index].low, bars[other_index].low))
    return intersection / max(bars[index].high - bars[index].low, 1e-9)


def average_overlap_ratio(bars: list[base.Bar], index: int, lookback: int) -> float:
    ratios = [bar_overlap_ratio(bars, offset, offset - 1) for offset in range(index - lookback + 1, index + 1)]
    return sum(ratios) / lookback


def is_inside_bar(bars: list[base.Bar], index: int, other_index: int) -> bool:
    return bars[index].high <= bars[other_index].high and bars[index].low >= bars[other_index].low


def is_outside_bar(bars: list[base.Bar], index: int, other_index: int) -> bool:
    return bars[index].high >= bars[other_index].high and bars[index].low <= bars[other_index].low


def inside_bar_count(bars: list[base.Bar], index: int, lookback: int) -> float:
    count = sum(1 for offset in range(index - lookback + 1, index + 1) if is_inside_bar(bars, offset, offset - 1))
    return count / lookback


def outside_bar_count(bars: list[base.Bar], index: int, lookback: int) -> float:
    count = sum(1 for offset in range(index - lookback + 1, index + 1) if is_outside_bar(bars, offset, offset - 1))
    return count / lookback


def contained_range_count(bars: list[base.Bar], index: int, lookback: int) -> float:
    count = 0
    for offset in range(index - lookback + 1, index + 1):
        prior_start = offset - 3
        prior_high = max(bars[prior].high for prior in range(prior_start, offset))
        prior_low = min(bars[prior].low for prior in range(prior_start, offset))
        if bars[offset].high <= prior_high and bars[offset].low >= prior_low:
            count += 1
    return count / lookback


def range_center_shift(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    current_center = (bars[index].high + bars[index].low) / 2.0
    prior_center = (bars[index - lookback].high + bars[index - lookback].low) / 2.0
    return direction * (current_center - prior_center) / max(average_range, 1e-9)


def box_position(bars: list[base.Bar], index: int, lookback: int) -> float:
    start = index - lookback
    prior_high = max(bars[offset].high for offset in range(start, index))
    prior_low = min(bars[offset].low for offset in range(start, index))
    return bounded((bars[index].close - prior_low) / max(prior_high - prior_low, 1e-9), -0.5, 1.5)


def directional_box_position(bars: list[base.Bar], index: int, direction: int, lookback: int) -> float:
    position = box_position(bars, index, lookback)
    return position if direction > 0 else 1.0 - position


def directional_escape_pressure(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    start = index - lookback
    if direction > 0:
        prior_extreme = max(bars[offset].high for offset in range(start, index))
        return (bars[index].close - prior_extreme) / max(average_range, 1e-9)
    prior_extreme = min(bars[offset].low for offset in range(start, index))
    return (prior_extreme - bars[index].close) / max(average_range, 1e-9)


def close_inside_prior_range(bars: list[base.Bar], index: int, lookback: int) -> float:
    start = index - lookback
    prior_high = max(bars[offset].high for offset in range(start, index))
    prior_low = min(bars[offset].low for offset in range(start, index))
    return 1.0 if prior_low <= bars[index].close <= prior_high else 0.0


def directional_return_to_prior_range(bars: list[base.Bar], index: int, direction: int, lookback: int) -> float:
    start = index - lookback
    prior_high = max(bars[offset].high for offset in range(start, index))
    prior_low = min(bars[offset].low for offset in range(start, index))
    close_inside = prior_low <= bars[index].close <= prior_high
    if direction > 0:
        return 1.0 if bars[index].high > prior_high and close_inside else 0.0
    return 1.0 if bars[index].low < prior_low and close_inside else 0.0


def average_bar_range(bars: list[base.Bar], index: int, lookback: int) -> float:
    return sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - lookback + 1, index + 1)) / lookback


def range_std(bars: list[base.Bar], index: int, lookback: int) -> float:
    ranges = [max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - lookback + 1, index + 1)]
    return float(np.std(np.asarray(ranges, dtype=float)))


def range_std_ratio(bars: list[base.Bar], index: int, lookback: int) -> float:
    mean_range = average_bar_range(bars, index, lookback)
    return range_std(bars, index, lookback) / max(mean_range, 1e-9)


def directional_range_position(bars: list[base.Bar], index: int, direction: int, lookback: int) -> float:
    start = index - lookback + 1
    window_high = max(bars[offset].high for offset in range(start, index + 1))
    window_low = min(bars[offset].low for offset in range(start, index + 1))
    span = max(window_high - window_low, 1e-9)
    position = (bars[index].close - window_low) / span
    return position if direction > 0 else 1.0 - position


def directional_breakout_pressure(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    start = index - lookback
    if direction > 0:
        prior_extreme = max(bars[offset].high for offset in range(start, index))
        return (bars[index].close - prior_extreme) / max(average_range, 1e-9)
    prior_extreme = min(bars[offset].low for offset in range(start, index))
    return (prior_extreme - bars[index].close) / max(average_range, 1e-9)


def directional_efficiency(bars: list[base.Bar], index: int, direction: int, lookback: int) -> float:
    denominator = sum(abs(bars[offset].close - bars[offset - 1].close) for offset in range(index - lookback + 1, index + 1))
    if denominator <= 0:
        return 0.0
    return direction * (bars[index].close - bars[index - lookback].close) / denominator


def recent_range_sum(bars: list[base.Bar], index: int, lookback: int) -> float:
    return sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - lookback + 1, index + 1))


def path_churn_ratio(bars: list[base.Bar], index: int, lookback: int) -> float:
    path = sum(abs(bars[offset].close - bars[offset - 1].close) for offset in range(index - lookback + 1, index + 1))
    span = max(
        max(bars[offset].high for offset in range(index - lookback + 1, index + 1))
        - min(bars[offset].low for offset in range(index - lookback + 1, index + 1)),
        1e-9,
    )
    return path / span


def close_sign_stats(bars: list[base.Bar], index: int, direction: int, lookback: int) -> dict[str, float]:
    signs: list[int] = []
    for offset in range(index - lookback + 1, index + 1):
        move = direction * (bars[offset].close - bars[offset - 1].close)
        if move > 0:
            signs.append(1)
        elif move < 0:
            signs.append(-1)
        else:
            signs.append(0)
    same = sum(1 for sign in signs if sign > 0)
    opposite = sum(1 for sign in signs if sign < 0)
    nonzero_pairs = [(left, right) for left, right in zip(signs, signs[1:]) if left != 0 and right != 0]
    flips = sum(1 for left, right in nonzero_pairs if left != right)
    return {
        "imbalance": (same - opposite) / lookback,
        "same_count": same / lookback,
        "opposite_count": opposite / lookback,
        "alternating_churn": flips / max(len(nonzero_pairs), 1),
    }


def directional_close_streak(bars: list[base.Bar], index: int, direction: int, cap: int) -> float:
    streak = 0
    streak_sign = 0
    for offset in range(index, index - cap, -1):
        move = direction * (bars[offset].close - bars[offset - 1].close)
        sign = 1 if move > 0 else -1 if move < 0 else 0
        if sign == 0:
            break
        if streak_sign == 0:
            streak_sign = sign
        if sign != streak_sign:
            break
        streak += 1
    return streak_sign * streak / cap


def intraday_fractal_pivot_transition_label(
    bars: list[base.Bar],
    range_average: list[float | None],
    pivot_context: list[dict[str, object]],
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
    future_body_agreement = future_body_alignment(path, direction)
    future_close_agreement = future_directional_close_agreement(path, direction) - 0.5
    future_pivot_escape_quality = future_directional_pivot_escape_quality(path, entry, direction, average_range)
    future_pivot_reclaim_quality = future_directional_pivot_reclaim_quality(
        bars,
        pivot_context,
        entry_index,
        exit_index,
        direction,
    )
    future_pivot_retention = future_directional_pivot_retention(path, entry, direction)
    future_failed_pivot_penalty = future_directional_failed_pivot_break_penalty(
        bars,
        pivot_context,
        entry_index,
        exit_index,
        direction,
    )
    return (
        0.82 * first_hit
        + 0.34 * target_speed
        - 0.46 * stop_speed
        - 0.58 * adverse_first
        + 0.30 * early_followthrough
        - 0.34 * early_adverse
        + 0.28 * close_through
        + 0.28 * favorable
        - 0.62 * adverse
        + 0.38 * terminal_norm
        + 0.34 * path_efficiency
        - 0.30 * giveback
        + 0.22 * path_alignment_edge
        - 0.26 * adverse_close_flips
        + 0.22 * future_body_agreement
        + 0.18 * future_close_agreement
        + 0.26 * future_pivot_escape_quality
        + 0.18 * future_pivot_reclaim_quality
        + 0.24 * future_pivot_retention
        - 0.34 * future_failed_pivot_penalty
        - 1.08 * spread_norm
        - 0.20 * spread_drift
    )


def future_directional_pivot_escape_quality(
    path: list[base.Bar],
    entry: float,
    direction: int,
    average_range: float,
) -> float:
    if direction > 0:
        return max(bar.high - entry for bar in path) / average_range
    return max(entry - bar.low for bar in path) / average_range


def future_directional_pivot_retention(path: list[base.Bar], entry: float, direction: int) -> float:
    favorable_closes = [direction * (bar.close - entry) for bar in path]
    peak = max(favorable_closes)
    terminal = favorable_closes[-1]
    if peak <= 0:
        return -max(0.0, -terminal)
    return terminal / peak


def future_body_alignment(path: list[base.Bar], direction: int) -> float:
    if not path:
        return 0.0
    aligned = sum(direction * body_direction(bar) for bar in path)
    return aligned / len(path)


def future_directional_close_agreement(path: list[base.Bar], direction: int) -> float:
    if not path:
        return 0.0
    return sum(directional_close_location(bar, direction) for bar in path) / len(path)


def future_directional_pivot_reclaim_quality(
    bars: list[base.Bar],
    pivot_context: list[dict[str, object]],
    start_index: int,
    exit_index: int,
    direction: int,
) -> float:
    count = 0
    total = 0
    for offset in range(start_index, exit_index + 1):
        high, low = latest_pivot_levels(pivot_context, offset)
        total += 1
        if direction > 0 and low is not None and bars[offset].low <= low and bars[offset].close > low:
            count += 1
        if direction < 0 and high is not None and bars[offset].high >= high and bars[offset].close < high:
            count += 1
    return count / max(total, 1)


def future_directional_wick_support(path: list[base.Bar], direction: int) -> float:
    if not path:
        return 0.0
    values = [lower_wick_ratio(bar) if direction > 0 else upper_wick_ratio(bar) for bar in path]
    return sum(values) / len(values)


def future_directional_follow_wick(path: list[base.Bar], direction: int) -> float:
    if not path:
        return 0.0
    values = [upper_wick_ratio(bar) if direction > 0 else lower_wick_ratio(bar) for bar in path]
    return sum(values) / len(values)


def future_directional_breakout_support(
    bars: list[base.Bar],
    start_index: int,
    exit_index: int,
    direction: int,
) -> float:
    count = 0
    total = 0
    for offset in range(start_index, exit_index + 1):
        prior_high = max(bars[prior].high for prior in range(offset - 3, offset))
        prior_low = min(bars[prior].low for prior in range(offset - 3, offset))
        total += 1
        if direction > 0 and bars[offset].close > prior_high:
            count += 1
        if direction < 0 and bars[offset].close < prior_low:
            count += 1
    return count / max(total, 1)


def future_directional_failed_pivot_break_penalty(
    bars: list[base.Bar],
    pivot_context: list[dict[str, object]],
    start_index: int,
    exit_index: int,
    direction: int,
) -> float:
    count = 0
    total = 0
    for offset in range(start_index, exit_index + 1):
        prior_high, prior_low = latest_pivot_levels(pivot_context, offset)
        total += 1
        if direction > 0 and prior_high is not None and bars[offset].high > prior_high and bars[offset].close <= prior_high:
            count += 1
        if direction < 0 and prior_low is not None and bars[offset].low < prior_low and bars[offset].close >= prior_low:
            count += 1
    return count / max(total, 1)


def future_directional_motif_persistence(path: list[base.Bar], direction: int) -> float:
    if not path:
        return 0.0
    first_sign = direction * body_direction(path[0])
    if first_sign == 0:
        return 0.0
    aligned = sum(1 for bar in path if direction * body_direction(bar) == first_sign)
    return aligned / len(path)


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
    payload["campaign_id"] = "C0029"
    payload["work_unit_id"] = "C0029"
    payload["run_id"] = "R0001"
    payload["proxy_id"] = "PX-C0029-R0001"
    payload["proxy_engine"] = "axiom_rift.proxies.c0029_r0001_intraday_fractal_pivot_transition"
    payload["proxy_config_path"] = "campaigns/C0029_intraday_fractal_pivot_transition_discovery/runs/R0001/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_intraday_fractal_pivot_transition_rank_fit"
    payload["proxy_artifact_paths"] = [
        "campaigns/C0029_intraday_fractal_pivot_transition_discovery/runs/R0001/kpi/proxy.json",
        "campaigns/C0029_intraday_fractal_pivot_transition_discovery/runs/R0001/artifacts/c0029_r0001_proxy_trades.csv",
        "campaigns/C0029_intraday_fractal_pivot_transition_discovery/runs/R0001/artifacts/c0029_r0001_intraday_fractal_pivot_transition_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["intraday_fractal_pivot_transition_profile"] = {  # type: ignore[index]
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
            "next_action": "produce_c0029_r0001_mt5_logic_parity_evidence",
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
            "score_interpretation": "higher_score_means_direct_fold_local_intraday_fractal_pivot_transition_rank",
            "variant_boundary": (
                "intraday_fractal_pivot_transition_rank_not_range_overlap_calendar_phase_tick_participation_"
                "volatility_term_daily_profile_excursion_bar_quality_micro_gap_round_level_liquidity_vacuum_"
                "threshold_stop_target_hold_activity_capital_or_retry_nudge"
            ),
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
        "score_interpretation": "higher_score_means_direct_fold_local_intraday_fractal_pivot_transition_rank",
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
    write_intraday_fractal_pivot_transition_summary_artifact(payload, INTRADAY_FRACTAL_PIVOT_TRANSITION_SUMMARY_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = base.sha256_file(TRADE_ARTIFACT_PATH)
    summary_hash = base.sha256_file(INTRADAY_FRACTAL_PIVOT_TRANSITION_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = base.sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)


def write_intraday_fractal_pivot_transition_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_fold_local_intraday_fractal_pivot_transition_summary_v1",
        "template": False,
        "work_unit_id": "C0029",
        "campaign_id": "C0029",
        "run_id": "R0001",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "intraday_fractal_pivot_transition_profile": profiles["intraday_fractal_pivot_transition_profile"]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "intraday_fractal_pivot_transition_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-C0029-R0001-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0029_intraday_fractal_pivot_transition_discovery/runs/R0001/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0029_intraday_fractal_pivot_transition_discovery/runs/R0001/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-C0029-R0001-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0029_intraday_fractal_pivot_transition_discovery/runs/R0001/artifacts/c0029_r0001_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0029_intraday_fractal_pivot_transition_discovery/runs/R0001/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0029-R0001-INTRADAY-FRACTAL-PIVOT-TRANSITION-SUMMARY",
                "intraday_fractal_pivot_transition_summary_artifact",
                "json",
                "campaigns/C0029_intraday_fractal_pivot_transition_discovery/runs/R0001/artifacts/c0029_r0001_intraday_fractal_pivot_transition_summary.json",
                summary_hash,
                ["campaigns/C0029_intraday_fractal_pivot_transition_discovery/runs/R0001/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0029_r0001_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0029_r0001_intraday_fractal_pivot_transition",
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
    evidence["proxy_trade_artifact"] = "artifacts/c0029_r0001_proxy_trades.csv"
    evidence["intraday_fractal_pivot_transition_summary"] = "artifacts/c0029_r0001_intraday_fractal_pivot_transition_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0029_r0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0029_r0001_proxy_trades.csv",
        "artifacts/c0029_r0001_intraday_fractal_pivot_transition_summary.json",
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
            "revisit_when": "after C0029 R0001 MT5 evidence files contain measured results",
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
    next_candidate["direction"] = "active_c0029_r0001_mt5_logic_parity"
    next_candidate["reason"] = "R0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0029_r0001_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = "campaigns/C0029_intraday_fractal_pivot_transition_discovery"
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = "campaigns/C0029_intraday_fractal_pivot_transition_discovery"
    completed = list(next_work.get("completed") or [])
    for item in (
        "open_c0029_intraday_fractal_pivot_transition_discovery",
        "open_c0029_r0001_fold_local_intraday_fractal_pivot_transition_rank_run",
        "produce_c0029_r0001_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_c0029_r0001_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_run"] = "campaigns/C0029_intraday_fractal_pivot_transition_discovery/runs/R0001"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0029_intraday_fractal_pivot_transition_discovery"
    data["active_run"] = "campaigns/C0029_intraday_fractal_pivot_transition_discovery/runs/R0001"
    data["latest_operation"] = {
        "id": "produce_c0029_r0001_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0029_intraday_fractal_pivot_transition_discovery/runs/R0001/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0029_r0001_mt5_logic_parity_evidence",
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
            "C0004": "C0029",
            "c0004_r0001_fold_local_state_archetype": "c0029_r0001_intraday_fractal_pivot_transition",
            "c0004_r0001": "c0029_r0001",
            "fold_local_state_archetype_discovery": "intraday_fractal_pivot_transition_discovery",
            "fold_local_train_only_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "intraday_fractal_pivot_transition_summary",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
