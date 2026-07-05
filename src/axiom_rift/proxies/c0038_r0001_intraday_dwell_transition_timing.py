"""C0038 R0001 proxy evidence for intraday dwell transition timing discovery."""

from __future__ import annotations

import csv
import hashlib
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


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0038_intraday_dwell_transition_timing_discovery" / "runs" / "R0001"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0038_intraday_dwell_transition_timing_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0038_r0001_proxy_trades.csv"
DWELL_TRANSITION_TIMING_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0038_r0001_dwell_transition_timing_summary.json"
RUN_MANIFEST_PATH = RUN_DIR / "run_manifest.json"
GATE_REPORT_PATH = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE_PATH = RUN_DIR / "artifact_lineage.json"
REENTRY_PATH = PROJECT_ROOT / "registries" / "reentry.yaml"
CLAIM_STATE_PATH = PROJECT_ROOT / "registries" / "claim_state.yaml"
DECISION_CURSOR_PATH = PROJECT_ROOT / "registries" / "decision_cursor.yaml"
BASE_FRAME = base.BASE_FRAME
ROLLING_WINDOWS = base.ROLLING_WINDOWS
SplitWindow = base.SplitWindow
Trade = base.Trade
load_bars = base.load_bars
load_windows = base.load_windows


CLAIM_BOUNDARY = {
    "claim_authority": False,
    "economics_pass": False,
    "feature_set_selected": False,
    "label_selected": False,
    "live_ready": False,
    "materialization_ready": False,
    "model_selected": False,
    "onnx_ready": False,
    "promotion_ready": False,
    "runtime_authority": False,
    "runtime_probe_completed": False,
    "selected": False,
    "trade_logic_selected": False,
}


FEATURE_NAMES = (
    "direction_bias",
    "directional_return_1_atr",
    "directional_return_3_atr",
    "directional_return_6_atr",
    "directional_return_12_atr",
    "dwell_fraction_12",
    "dwell_fraction_24",
    "dwell_fraction_48",
    "range_dwell_fraction_24",
    "range_dwell_fraction_48",
    "dwell_streak_24",
    "dwell_streak_48",
    "touch_recency_48",
    "recross_count_12",
    "recross_count_24",
    "directional_recross_balance_24",
    "opposite_recross_balance_24",
    "dwell_compression_12_vs_48",
    "dwell_expansion_6_vs_24",
    "transition_velocity_3",
    "transition_velocity_6",
    "transition_velocity_12",
    "failed_transition_pressure_12",
    "failed_transition_pressure_24",
    "accepted_transition_pressure_12",
    "accepted_transition_pressure_24",
    "reclaim_delay_directional_24",
    "stall_decay_24",
    "body_transition_alignment_6",
    "body_transition_alignment_12",
    "wick_rejection_timing_6",
    "path_efficiency_12",
    "churn_ratio_12",
    "day_dwell_balance_directional",
    "day_transition_room",
    "day_dwell_fraction_current",
    "session_progress",
    "spread_over_range",
    "spread_dwell_stress_24",
)
MODEL_FAMILY = "fold_local_intraday_dwell_transition_timing_rank"
LABEL_SHAPE = "directional_intraday_dwell_transition_timing_survival_quality"
POSITIVE_LABEL_THRESHOLD = 0.18
ADVERSE_LABEL_THRESHOLD = -0.36
FEATURE_WEIGHT_FLOOR = 0.25
FEATURE_WEIGHT_CEILING = 2.50
SELECTION_RULE = "top_fold_local_intraday_dwell_transition_timing_scores_per_active_day"


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


def local_execution_path(path: Path) -> str:
    resolved = str(path.resolve())
    if len(resolved) >= 240 and not resolved.startswith("\\\\?\\"):
        return "\\\\?\\" + resolved
    return resolved


def write_text_local(path: Path, text: str, encoding: str = "ascii") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_execution_path(path), "w", encoding=encoding, newline="") as handle:
        handle.write(text)


def sha256_file_local(path: Path) -> str:
    digest = hashlib.sha256()
    with open(local_execution_path(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_c0038_r0001_proxy(write: bool = True) -> dict[str, object]:
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
    price_context = build_dwell_transition_timing_context(bars, range_average, short_range_average, day_context)
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
            price_context,
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
            price_context,
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
    price_context: list[dict[str, float] | None],
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
        120,
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
            features = intraday_dwell_transition_timing_features(
                bars,
                range_average,
                short_range_average,
                day_context,
                price_context,
                index,
                direction,
            )
            if features is None:
                continue
            label = (
                intraday_dwell_transition_timing_label(bars, range_average, price_context, index, direction)
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
                    state_key=f"{side}|intraday_dwell_transition_timing",
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


def build_dwell_transition_timing_context(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    day_context: list[dict[str, float] | None],
) -> list[dict[str, float] | None]:
    contexts: list[dict[str, float] | None] = [None] * len(bars)
    for index, bar in enumerate(bars):
        average_range = range_average[index]
        short_average_range = short_range_average[index]
        day = day_context[index]
        if index < 120 or average_range is None or average_range <= 0 or short_average_range is None or day is None:
            continue
        dwell_6 = close_dwell_fraction(bars, index, 6, average_range)
        dwell_12 = close_dwell_fraction(bars, index, 12, average_range)
        dwell_24 = close_dwell_fraction(bars, index, 24, average_range)
        dwell_48 = close_dwell_fraction(bars, index, 48, average_range)
        range_dwell_24 = range_dwell_fraction(bars, index, 24, average_range)
        range_dwell_48 = range_dwell_fraction(bars, index, 48, average_range)
        contexts[index] = {
            "dwell_fraction_6": dwell_6,
            "dwell_fraction_12": dwell_12,
            "dwell_fraction_24": dwell_24,
            "dwell_fraction_48": dwell_48,
            "range_dwell_fraction_24": range_dwell_24,
            "range_dwell_fraction_48": range_dwell_48,
            "dwell_streak_24": dwell_streak_norm(bars, index, 24, average_range),
            "dwell_streak_48": dwell_streak_norm(bars, index, 48, average_range),
            "touch_recency_48": touch_recency(bars, index, 48, average_range),
            "recross_count_12": recross_count(bars, index, 12, average_range),
            "recross_count_24": recross_count(bars, index, 24, average_range),
            "dwell_compression_12_vs_48": dwell_12 / max(dwell_48, 1e-9),
            "dwell_expansion_6_vs_24": dwell_6 / max(dwell_24, 1e-9),
            "day_dwell_fraction_current": day_dwell_fraction_current(bars, day, index, average_range),
            "session_progress": bounded(day["bars_since_day_open"] / 288.0, 0.0, 1.0),
            "spread_over_range": bar.spread_points / average_range,
            "spread_dwell_stress_24": (bar.spread_points / average_range) * (1.0 + dwell_24 + range_dwell_24),
        }
    return contexts


def close_dwell_fraction(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    if index < lookback:
        return 0.0
    current = bars[index].close
    band = max(0.32 * average_range, 1e-9)
    total = 0.0
    for offset in range(index - lookback, index):
        distance = abs(bars[offset].close - current)
        total += max(0.0, 1.0 - distance / band)
    return total / lookback


def range_dwell_fraction(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    if index < lookback:
        return 0.0
    current = bars[index].close
    band = max(0.22 * average_range, 1e-9)
    total = 0.0
    for offset in range(index - lookback, index):
        bar = bars[offset]
        if bar.low - band <= current <= bar.high + band:
            distance = 0.0 if bar.low <= current <= bar.high else min(abs(current - bar.low), abs(current - bar.high))
            total += max(0.0, 1.0 - distance / band)
    return total / lookback


def dwell_streak_norm(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    if index < lookback:
        return 0.0
    current = bars[index].close
    band = max(0.30 * average_range, 1e-9)
    streak = 0
    for offset in range(index - 1, index - lookback - 1, -1):
        bar = bars[offset]
        if abs(bar.close - current) <= band or bar.low - band <= current <= bar.high + band:
            streak += 1
            continue
        break
    return streak / lookback


def touch_recency(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    current = bars[index].close
    band = max(0.25 * average_range, 1e-9)
    for age, offset in enumerate(range(index - 1, index - lookback - 1, -1), start=1):
        if offset < 0:
            break
        bar = bars[offset]
        if abs(bar.close - current) <= band or bar.low - band <= current <= bar.high + band:
            return 1.0 - (age - 1) / lookback
    return 0.0


def recross_count(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    if index < lookback:
        return 0.0
    anchor = bars[index].close
    band = max(0.12 * average_range, 1e-9)
    previous_side = 0
    crosses = 0
    for offset in range(index - lookback, index + 1):
        distance = bars[offset].close - anchor
        side = 1 if distance > band else -1 if distance < -band else 0
        if side == 0:
            continue
        if previous_side != 0 and side != previous_side:
            crosses += 1
        previous_side = side
    return crosses / lookback


def directional_recross_balance(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    if index < lookback:
        return 0.0
    anchor = bars[index].close
    band = max(0.12 * average_range, 1e-9)
    favorable = 0
    adverse = 0
    prev_side = directional_side(bars[index - lookback].close, anchor, direction, band)
    for offset in range(index - lookback + 1, index + 1):
        side = directional_side(bars[offset].close, anchor, direction, band)
        if prev_side <= 0 and side > 0:
            favorable += 1
        if prev_side >= 0 and side < 0:
            adverse += 1
        if side != 0:
            prev_side = side
    return (favorable - adverse) / lookback


def directional_side(price: float, anchor: float, direction: int, band: float) -> int:
    distance = direction * (price - anchor)
    return 1 if distance > band else -1 if distance < -band else 0


def transition_velocity(bars: list[base.Bar], index: int, direction: int, lookback: int, average_range: float) -> float:
    if index < lookback:
        return 0.0
    net = direction * (bars[index].close - bars[index - lookback].close) / max(average_range, 1e-9)
    dwell = close_dwell_fraction(bars, index, lookback, average_range)
    return net / max(1.0, math.sqrt(1.0 + dwell * lookback))


def failed_transition_pressure(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    current = bars[index].close
    band = 0.30 * average_range
    total = 0.0
    for offset in range(index - lookback, index):
        bar = bars[offset]
        if direction > 0:
            excursion = bar.high - current
            failed = bar.close <= current + band
        else:
            excursion = current - bar.low
            failed = bar.close >= current - band
        if excursion > 0.45 * average_range and failed:
            total += min(excursion / max(average_range, 1e-9), 2.0)
    return total / max(lookback, 1)


def accepted_transition_pressure(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    current = bars[index].close
    threshold = 0.35 * average_range
    total = 0.0
    for offset in range(index - lookback, index):
        close_escape = direction * (bars[offset].close - current)
        if close_escape > threshold:
            total += min(close_escape / max(average_range, 1e-9), 2.0)
    return total / max(lookback, 1)


def reclaim_delay_directional(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    current = bars[index].close
    threshold = 0.35 * average_range
    for age, offset in enumerate(range(index - 1, index - lookback - 1, -1), start=1):
        if direction * (bars[offset].close - current) < -threshold:
            return age / lookback
    return 0.0


def stall_decay(context: dict[str, float], bars: list[base.Bar], index: int, direction: int, average_range: float) -> float:
    recent_move = abs(direction * (bars[index].close - bars[index - 6].close)) / max(average_range, 1e-9)
    return context["dwell_streak_24"] * max(0.0, 1.0 - recent_move)


def wick_rejection_timing(bars: list[base.Bar], index: int, direction: int, lookback: int, average_range: float) -> float:
    current = bars[index].close
    total = 0.0
    for offset in range(index - lookback + 1, index + 1):
        bar = bars[offset]
        if direction > 0:
            lane_wick = max(0.0, bar.high - current)
            reentry = max(0.0, current - bar.close)
        else:
            lane_wick = max(0.0, current - bar.low)
            reentry = max(0.0, bar.close - current)
        total += min(lane_wick / max(average_range, 1e-9), 2.0) * min(reentry / max(average_range, 1e-9), 2.0)
    return total / lookback


def body_transition_alignment(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    return sum(
        direction * (bars[offset].close - bars[offset].open) / max(average_range, 1e-9)
        for offset in range(index - lookback + 1, index + 1)
    ) / lookback


def day_dwell_fraction_current(
    bars: list[base.Bar],
    day_context: dict[str, float],
    index: int,
    average_range: float,
) -> float:
    lookback = int(min(day_context["bars_since_day_open"], 96.0))
    if lookback <= 0:
        return 0.0
    return close_dwell_fraction(bars, index, lookback, average_range)


def day_dwell_balance_directional(
    bars: list[base.Bar],
    day_context: dict[str, float],
    index: int,
    direction: int,
    average_range: float,
) -> float:
    lookback = int(min(day_context["bars_since_day_open"], 96.0))
    if lookback <= 0:
        return 0.0
    anchor = bars[index].close
    band = max(0.50 * average_range, 1e-9)
    favorable = 0.0
    adverse = 0.0
    for offset in range(index - lookback, index):
        distance = direction * (bars[offset].close - anchor)
        weight = max(0.0, 1.0 - abs(distance) / band)
        if distance >= 0:
            favorable += weight
        else:
            adverse += weight
    return (favorable - adverse) / max(lookback, 1)


def day_transition_room(
    bars: list[base.Bar],
    day_context: dict[str, float],
    index: int,
    direction: int,
    average_range: float,
) -> float:
    if direction > 0:
        distance = day_context["day_high"] - bars[index].close
    else:
        distance = bars[index].close - day_context["day_low"]
    return distance / max(average_range, 1e-9)


def intraday_dwell_transition_timing_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    day_context: list[dict[str, float] | None],
    dwell_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> tuple[float, ...] | None:
    average_range = range_average[index]
    short_average_range = short_range_average[index]
    if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
        return None
    day = day_context[index]
    context = dwell_context[index]
    if day is None or context is None:
        return None
    spread_over_range = bars[index].spread_points / average_range
    if spread_over_range > 0.65:
        return None
    features = (
        float(direction),
        direction * (bars[index].close - bars[index - 1].close) / average_range,
        direction * (bars[index].close - bars[index - 3].close) / average_range,
        direction * (bars[index].close - bars[index - 6].close) / average_range,
        direction * (bars[index].close - bars[index - 12].close) / average_range,
        context["dwell_fraction_12"],
        context["dwell_fraction_24"],
        context["dwell_fraction_48"],
        context["range_dwell_fraction_24"],
        context["range_dwell_fraction_48"],
        context["dwell_streak_24"],
        context["dwell_streak_48"],
        context["touch_recency_48"],
        context["recross_count_12"],
        context["recross_count_24"],
        directional_recross_balance(bars, index, direction, 24, average_range),
        directional_recross_balance(bars, index, -direction, 24, average_range),
        context["dwell_compression_12_vs_48"],
        context["dwell_expansion_6_vs_24"],
        transition_velocity(bars, index, direction, 3, average_range),
        transition_velocity(bars, index, direction, 6, average_range),
        transition_velocity(bars, index, direction, 12, average_range),
        failed_transition_pressure(bars, index, direction, 12, average_range),
        failed_transition_pressure(bars, index, direction, 24, average_range),
        accepted_transition_pressure(bars, index, direction, 12, average_range),
        accepted_transition_pressure(bars, index, direction, 24, average_range),
        reclaim_delay_directional(bars, index, direction, 24, average_range),
        stall_decay(context, bars, index, direction, average_range),
        body_transition_alignment(bars, index, direction, 6, average_range),
        body_transition_alignment(bars, index, direction, 12, average_range),
        wick_rejection_timing(bars, index, direction, 6, average_range),
        directional_efficiency(bars, index, direction, 12),
        path_churn_ratio(bars, index, 12),
        day_dwell_balance_directional(bars, day, index, direction, average_range),
        day_transition_room(bars, day, index, direction, average_range),
        context["day_dwell_fraction_current"],
        context["session_progress"],
        spread_over_range,
        context["spread_dwell_stress_24"],
    )
    if len(features) != len(FEATURE_NAMES):
        raise RuntimeError(f"C0038 feature length mismatch: {len(features)} != {len(FEATURE_NAMES)}")
    return tuple(float(value) for value in features)


def intraday_dwell_transition_timing_label(
    bars: list[base.Bar],
    range_average: list[float | None],
    dwell_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> float | None:
    entry_index = index + 1
    exit_index = min(index + base.LABEL_HORIZON_BARS, len(bars) - 1)
    average_range = range_average[index]
    if average_range is None or average_range <= 0 or entry_index >= exit_index:
        return None
    context = dwell_context[index]
    if context is None:
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
            if bar.low <= stop_price:
                first_hit = -1.0
                event_bar = offset
                adverse_first = 1.0
                break
            if bar.high >= target_price:
                first_hit = 1.0
                event_bar = offset
                break
    else:
        mfe = max(entry - bar.low for bar in path)
        mae = max(bar.high - entry for bar in path)
        terminal = entry - path[-1].close
        aligned_close_count = sum(1 for bar in path if bar.close <= entry)
        for offset, bar in enumerate(path, start=1):
            if bar.high >= stop_price:
                first_hit = -1.0
                event_bar = offset
                adverse_first = 1.0
                break
            if bar.low <= target_price:
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
    future_acceptance = future_transition_acceptance(path, entry, direction, average_range)
    future_release = future_dwell_transition_timing_retention(dwell_context, entry_index, exit_index, direction)
    future_revisit = future_dwell_revisit(path, entry, average_range)
    future_recross = future_recross_penalty(path, entry, direction, average_range)
    future_adverse_density = future_adverse_side_density(path, entry, direction, average_range)
    future_churn_penalty = future_path_churn(path, entry)
    pre_dwell = 0.5 * context["dwell_fraction_48"] + 0.5 * context["dwell_streak_24"]
    return (
        0.82 * first_hit
        + 0.34 * target_speed
        - 0.46 * stop_speed
        - 0.58 * adverse_first
        + 0.26 * pre_dwell
        + 0.32 * early_followthrough
        - 0.34 * early_adverse
        + 0.28 * close_through
        + 0.28 * favorable
        - 0.62 * adverse
        + 0.38 * terminal_norm
        + 0.34 * path_efficiency
        - 0.30 * giveback
        + 0.22 * path_alignment_edge
        - 0.26 * adverse_close_flips
        + 0.34 * future_acceptance
        + 0.22 * future_release
        - 0.32 * future_revisit
        - 0.26 * future_recross
        - 0.24 * future_adverse_density
        - 0.22 * future_churn_penalty
        - 1.08 * spread_norm
        - 0.20 * spread_drift
    )


def future_dwell_transition_timing_retention(
    dwell_context: list[dict[str, float] | None],
    entry_index: int,
    exit_index: int,
    direction: int,
) -> float:
    values: list[float] = []
    for offset in range(entry_index, exit_index + 1):
        context = dwell_context[offset]
        if context is None:
            continue
        values.append(
            0.32 * (1.0 - context["dwell_fraction_24"])
            + 0.24 * (1.0 - context["recross_count_12"])
            - 0.18 * context["touch_recency_48"]
            - 0.12 * context["spread_over_range"]
        )
    return sum(values) / max(len(values), 1)


def future_transition_acceptance(
    path: list[base.Bar],
    entry: float,
    direction: int,
    average_range: float,
) -> float:
    if not path:
        return 0.0
    closes = [bar.close for bar in path]
    directional_closes = [direction * (close - entry) / max(average_range, 1e-9) for close in closes]
    accepted_share = sum(1 for value in directional_closes if value > 0.35) / len(directional_closes)
    if direction > 0:
        favorable_extreme = max(bar.high - entry for bar in path) / max(average_range, 1e-9)
    else:
        favorable_extreme = max(entry - bar.low for bar in path) / max(average_range, 1e-9)
    terminal = directional_closes[-1]
    return 0.40 * accepted_share + 0.35 * favorable_extreme + 0.25 * terminal


def future_dwell_revisit(path: list[base.Bar], entry: float, average_range: float) -> float:
    if not path:
        return 0.0
    band = max(0.35 * average_range, 1e-9)
    return sum(1 for bar in path if abs(bar.close - entry) <= band) / len(path)


def future_recross_penalty(path: list[base.Bar], entry: float, direction: int, average_range: float) -> float:
    if not path:
        return 0.0
    band = max(0.12 * average_range, 1e-9)
    previous_side = 0
    crosses = 0
    for bar in path:
        side = directional_side(bar.close, entry, direction, band)
        if side == 0:
            continue
        if previous_side != 0 and side != previous_side:
            crosses += 1
        previous_side = side
    return crosses / len(path)


def future_adverse_side_density(path: list[base.Bar], entry: float, direction: int, average_range: float) -> float:
    if not path:
        return 0.0
    threshold = 0.30 * average_range
    return sum(1 for bar in path if direction * (bar.close - entry) < -threshold) / len(path)


def fit_linear_edge_model(candidates: list[base.Candidate], fold_id: str) -> LinearEdgeModel:
    rows = [candidate for candidate in candidates if candidate.label is not None]
    if not rows:
        feature_count = len(FEATURE_NAMES)
        return LinearEdgeModel(
            fold_id=fold_id,
            feature_mean=np.zeros(feature_count),
            feature_std=np.ones(feature_count),
            score_direction=np.ones(feature_count),
            feature_weights=np.ones(feature_count),
            train_candidate_count=0,
            global_mean=0.0,
            positive_label_rate=0.0,
            adverse_label_rate=0.0,
            label_std=0.0,
        )
    matrix = np.array([candidate.features for candidate in rows], dtype=float)
    labels = np.array([float(candidate.label) for candidate in rows], dtype=float)
    feature_mean = matrix.mean(axis=0)
    feature_std = matrix.std(axis=0)
    feature_std = np.where(feature_std < 1e-9, 1.0, feature_std)
    label_mean = float(labels.mean())
    label_std = float(labels.std())
    normalized = (matrix - feature_mean) / feature_std
    centered_labels = labels - label_mean
    covariance = (normalized * centered_labels[:, None]).mean(axis=0)
    score_direction = np.where(covariance >= 0.0, 1.0, -1.0)
    raw_weights = np.abs(covariance) / max(label_std, 1e-9)
    feature_weights = np.clip(raw_weights, FEATURE_WEIGHT_FLOOR, FEATURE_WEIGHT_CEILING)
    return LinearEdgeModel(
        fold_id=fold_id,
        feature_mean=feature_mean,
        feature_std=feature_std,
        score_direction=score_direction,
        feature_weights=feature_weights,
        train_candidate_count=len(rows),
        global_mean=label_mean,
        positive_label_rate=float((labels > POSITIVE_LABEL_THRESHOLD).mean()),
        adverse_label_rate=float((labels < ADVERSE_LABEL_THRESHOLD).mean()),
        label_std=label_std,
    )


def score_candidates(candidates: list[base.Candidate], model: LinearEdgeModel) -> list[base.Candidate]:
    return [score_candidate(candidate, model) for candidate in candidates]


def score_candidate(candidate: base.Candidate, model: LinearEdgeModel) -> base.Candidate:
    features = np.array(candidate.features, dtype=float)
    normalized = (features - model.feature_mean) / model.feature_std
    score = float(np.dot(normalized * model.score_direction, model.feature_weights) / max(model.feature_weights.sum(), 1e-9))
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
        "score_interpretation": "higher_score_means_direct_fold_local_intraday_dwell_transition_timing_rank",
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


def build_proxy_payload(
    trades: list[base.Trade],
    windows: dict[str, dict[str, base.SplitWindow]],
    fold_models: list[dict[str, object]],
    state_distributions: dict[str, dict[str, float | int | None]],
    candidates_by_fold: dict[str, dict[str, int]],
) -> dict[str, object]:
    payload = replace_run_markers(base.build_proxy_payload(trades, windows, fold_models, state_distributions, candidates_by_fold))
    payload["campaign_id"] = "C0038"
    payload["work_unit_id"] = "C0038"
    payload["run_id"] = "R0001"
    payload["proxy_id"] = "PX-C0038-R0001"
    payload["proxy_engine"] = "axiom_rift.proxies.c0038_r0001_intraday_dwell_transition_timing"
    payload["proxy_config_path"] = "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_intraday_dwell_transition_timing_rank_fit"
    payload["claim_boundary"] = dict(CLAIM_BOUNDARY)
    payload["proxy_artifact_paths"] = [
        "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001/kpi/proxy.json",
        "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001/artifacts/c0038_r0001_proxy_trades.csv",
        "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001/artifacts/c0038_r0001_dwell_transition_timing_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["intraday_dwell_transition_timing_profile"] = {  # type: ignore[index]
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
            "next_action": "produce_c0038_r0001_mt5_logic_parity_evidence",
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
            "score_interpretation": "higher_score_means_direct_fold_local_intraday_dwell_transition_timing_rank",
            "variant_boundary": (
                "intraday_dwell_transition_timing_rank_not_effort_absorption_seasonal_residual_tail_risk_skew_entropy_"
                "vwap_fractal_pivot_swing_maturity_calendar_rhythm_threshold_score_stop_target_hold_session_activity_"
                "spread_capital_or_retry_nudge"
            ),
        }
    )
    return config


def write_proxy_evidence(payload: dict[str, object], trades: list[base.Trade]) -> None:
    RUN_DIR.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    RUN_DIR.joinpath("kpi").mkdir(parents=True, exist_ok=True)
    base.write_trade_artifact(trades, TRADE_ARTIFACT_PATH)
    write_dwell_transition_timing_summary_artifact(payload, DWELL_TRANSITION_TIMING_SUMMARY_PATH)
    write_text_local(PROXY_PATH, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    trade_hash = sha256_file_local(TRADE_ARTIFACT_PATH)
    summary_hash = sha256_file_local(DWELL_TRANSITION_TIMING_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = sha256_file_local(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)
    update_decision_cursor_after_proxy(payload)


def write_dwell_transition_timing_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_fold_local_intraday_dwell_transition_timing_summary_v1",
        "template": False,
        "work_unit_id": "C0038",
        "campaign_id": "C0038",
        "run_id": "R0001",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "intraday_dwell_transition_timing_profile": profiles["intraday_dwell_transition_timing_profile"]["fields"],  # type: ignore[index]
        "claim_boundary": payload["claim_boundary"],
    }
    write_text_local(path, json.dumps(summary, indent=2, sort_keys=True) + "\n")


def update_proxy_hashes(trade_hash: str, summary_hash: str) -> None:
    data = json.loads(PROXY_PATH.read_text(encoding="ascii"))
    data["proxy_artifact_hashes"] = [trade_hash, summary_hash]
    PROXY_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_artifact_lineage(proxy_hash: str, trade_hash: str, summary_hash: str) -> None:
    data = json.loads(ARTIFACT_LINEAGE_PATH.read_text(encoding="ascii"))
    records = [
        record
        for record in data.get("artifact_records", [])
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "intraday_dwell_transition_timing_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-C0038-R0001-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-C0038-R0001-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001/artifacts/c0038_r0001_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0038-R0001-DWELL-TRANSITION-TIMING-SUMMARY",
                "intraday_dwell_transition_timing_summary_artifact",
                "json",
                "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001/artifacts/c0038_r0001_dwell_transition_timing_summary.json",
                summary_hash,
                ["campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0038_r0001_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0038_r0001_intraday_dwell_transition_timing",
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
    evidence["proxy_trade_artifact"] = "artifacts/c0038_r0001_proxy_trades.csv"
    evidence["intraday_dwell_transition_timing_summary"] = "artifacts/c0038_r0001_dwell_transition_timing_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0038_r0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0038_r0001_proxy_trades.csv",
        "artifacts/c0038_r0001_dwell_transition_timing_summary.json",
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
            "revisit_when": "after C0038 R0001 MT5 evidence files contain measured results",
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
    next_candidate["direction"] = "active_c0038_r0001_mt5_logic_parity"
    next_candidate["reason"] = "R0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0038_r0001_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    data = yaml.safe_load(REENTRY_PATH.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = "campaigns/C0038_intraday_dwell_transition_timing_discovery"
    data["project"]["active_run"] = "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001"
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = "campaigns/C0038_intraday_dwell_transition_timing_discovery"
    completed = list(next_work.get("completed") or [])
    for item in (
        "open_c0038_intraday_dwell_transition_timing_discovery",
        "open_c0038_r0001_fold_local_intraday_dwell_transition_timing_rank_run",
        "produce_c0038_r0001_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_c0038_r0001_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_campaign"] = "campaigns/C0038_intraday_dwell_transition_timing_discovery"
    data["active_run"] = "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001"
    REENTRY_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0038_intraday_dwell_transition_timing_discovery"
    data["active_run"] = "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001"
    data["latest_operation"] = {
        "id": "produce_c0038_r0001_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0038_r0001_mt5_logic_parity_evidence",
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_decision_cursor_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(DECISION_CURSOR_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["updated_local_date"] = "2026-07-06"
    data["canonical_source"] = "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001/kpi/proxy.json"
    data["canonical_status"] = "proxy_recorded_pending_mt5"
    data["current_decision"] = "produce_c0038_r0001_mt5_logic_parity_evidence"
    data["active_campaign"] = "campaigns/C0038_intraday_dwell_transition_timing_discovery"
    data["active_run"] = "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001"
    data["next_required_action"] = "produce_c0038_r0001_mt5_logic_parity_evidence"
    data["current_evidence_summary"] = {
        "source_campaign": "campaigns/C0038_intraday_dwell_transition_timing_discovery",
        "current_task": "produce_c0038_r0001_mt5_logic_parity_evidence",
        "active_run": "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001",
        "active_run_status": "proxy_recorded_pending_mt5",
        "evidence_status": "proxy_recorded_pending_mt5",
        "campaign_family": "intraday_dwell_transition_timing",
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0038_r0001_mt5_logic_parity_evidence",
        "note": "C0038 R0001 proxy evidence recorded; MT5 paired validation remains mandatory regardless of proxy result.",
        "source_campaign_manifest": "campaigns/C0038_intraday_dwell_transition_timing_discovery/campaign.yaml",
    }
    data["claim_boundary_snapshot"] = dict(CLAIM_BOUNDARY)
    DECISION_CURSOR_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def replace_run_markers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: replace_run_markers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_run_markers(item) for item in value]
    if isinstance(value, str):
        replacements = {
            "C0004": "C0038",
            "c0004_r0001_fold_local_state_archetype": "c0038_r0001_intraday_dwell_transition_timing",
            "c0004_r0001": "c0038_r0001",
            "fold_local_state_archetype_discovery": "intraday_dwell_transition_timing_discovery",
            "fold_local_train_only_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "intraday_dwell_transition_timing_summary",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def mean_bar_range(bars: list[base.Bar], index: int, lookback: int) -> float:
    return sum(max(bars[offset].high - bars[offset].low, 0.0) for offset in range(index - lookback + 1, index + 1)) / lookback


def close_change_sign(bars: list[base.Bar], index: int) -> int:
    change = bars[index].close - bars[index - 1].close
    return 1 if change > 0.0 else -1 if change < 0.0 else 0


def directional_close_location(bar: base.Bar, direction: int) -> float:
    bar_range = max(bar.high - bar.low, 1e-9)
    long_location = (bar.close - bar.low) / bar_range
    return long_location if direction > 0 else 1.0 - long_location


def directional_close_location_mean(bars: list[base.Bar], index: int, direction: int, lookback: int) -> float:
    return sum(directional_close_location(bars[offset], direction) for offset in range(index - lookback + 1, index + 1)) / lookback


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


def body_direction_sum(bars: list[base.Bar], index: int, lookback: int) -> float:
    total = 0.0
    for offset in range(index - lookback + 1, index + 1):
        body = bars[offset].close - bars[offset].open
        total += 1.0 if body > 0.0 else -1.0 if body < 0.0 else 0.0
    return total


def counter_move_pressure(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    pressure = 0.0
    for offset in range(index - lookback + 1, index + 1):
        move = direction * (bars[offset].close - bars[offset - 1].close)
        if move < 0.0:
            pressure += abs(move)
    return pressure / max(average_range, 1e-9)


def directional_efficiency(bars: list[base.Bar], index: int, direction: int, lookback: int) -> float:
    net = direction * (bars[index].close - bars[index - lookback].close)
    path = sum(abs(bars[offset].close - bars[offset - 1].close) for offset in range(index - lookback + 1, index + 1))
    return net / max(path, 1e-9)


def path_churn_ratio(bars: list[base.Bar], index: int, lookback: int) -> float:
    path = sum(abs(bars[offset].close - bars[offset - 1].close) for offset in range(index - lookback + 1, index + 1))
    high = max(bars[offset].high for offset in range(index - lookback + 1, index + 1))
    low = min(bars[offset].low for offset in range(index - lookback + 1, index + 1))
    return path / max(high - low, 1e-9)


def day_range_position_directional(
    bars: list[base.Bar],
    day_context: dict[str, float],
    index: int,
    direction: int,
) -> float:
    width = max(day_context["day_high"] - day_context["day_low"], 1e-9)
    long_position = (bars[index].close - day_context["day_low"]) / width
    return long_position if direction > 0 else 1.0 - long_position


def future_path_churn(path: list[base.Bar], entry: float) -> float:
    if not path:
        return 0.0
    closes = [entry] + [bar.close for bar in path]
    distance = sum(abs(closes[index] - closes[index - 1]) for index in range(1, len(closes)))
    span = max(max(bar.high for bar in path) - min(bar.low for bar in path), 1e-9)
    return distance / span


def bounded(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

