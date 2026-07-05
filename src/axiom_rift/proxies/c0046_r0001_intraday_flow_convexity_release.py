"""C0046 R0001 proxy evidence for intraday flow convexity release discovery."""

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


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0046_intraday_flow_convexity_release_discovery" / "runs" / "R0001"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0046_intraday_flow_convexity_release_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0046_r0001_proxy_trades.csv"
FLOW_CONVEXITY_RELEASE_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0046_r0001_flow_convexity_release_summary.json"
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
    "directional_return_1",
    "directional_return_3",
    "directional_return_6",
    "directional_return_12",
    "directional_return_24",
    "directional_acceleration_3_12",
    "directional_acceleration_6_24",
    "acceleration_inflection_3",
    "signed_flow_sum_6",
    "signed_flow_sum_12",
    "signed_flow_sum_24",
    "flow_energy_6",
    "flow_energy_12",
    "flow_energy_24",
    "energy_contraction_6_24",
    "energy_expansion_6_24",
    "pressure_build_12",
    "pressure_build_24",
    "opposing_pressure_build_12",
    "release_impulse_1",
    "release_impulse_3",
    "release_impulse_6",
    "body_flow_alignment_6",
    "body_flow_alignment_12",
    "body_close_agreement_12",
    "favorable_wick_acceptance_6",
    "opposing_wick_rejection_6",
    "path_efficiency_12",
    "path_churn_ratio_12",
    "day_directional_return",
    "day_pressure_balance",
    "day_range_position",
    "range_expansion_6_24",
    "session_progress",
    "spread_over_range",
    "spread_flow_stress",
    "pressure_release_alignment",
    "convexity_energy_interaction",
)
MODEL_FAMILY = "fold_local_intraday_flow_convexity_release_rank"
LABEL_SHAPE = "directional_intraday_signed_flow_convexity_release_quality"
POSITIVE_LABEL_THRESHOLD = 0.18
ADVERSE_LABEL_THRESHOLD = -0.36
FEATURE_WEIGHT_FLOOR = 0.25
FEATURE_WEIGHT_CEILING = 2.50
SELECTION_RULE = "top_fold_local_intraday_flow_convexity_release_scores_per_active_day"


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


def run_c0046_r0001_proxy(write: bool = True) -> dict[str, object]:
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
    price_context = build_flow_convexity_release_context(bars, range_average, short_range_average, day_context)
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
            features = intraday_flow_convexity_release_features(
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
                intraday_flow_convexity_release_label(bars, range_average, price_context, index, direction)
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
                    state_key=f"{side}|intraday_flow_convexity_release",
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


def build_flow_convexity_release_context(
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
        ribbon_6 = close_ribbon_fraction(bars, index, 6, average_range)
        ribbon_12 = close_ribbon_fraction(bars, index, 12, average_range)
        ribbon_24 = close_ribbon_fraction(bars, index, 24, average_range)
        ribbon_48 = close_ribbon_fraction(bars, index, 48, average_range)
        range_ribbon_24 = range_ribbon_fraction(bars, index, 24, average_range)
        range_ribbon_48 = range_ribbon_fraction(bars, index, 48, average_range)
        contexts[index] = {
            "ribbon_fraction_6": ribbon_6,
            "ribbon_fraction_12": ribbon_12,
            "ribbon_fraction_24": ribbon_24,
            "ribbon_fraction_48": ribbon_48,
            "range_ribbon_fraction_24": range_ribbon_24,
            "range_ribbon_fraction_48": range_ribbon_48,
            "ribbon_streak_24": ribbon_streak_norm(bars, index, 24, average_range),
            "ribbon_streak_48": ribbon_streak_norm(bars, index, 48, average_range),
            "touch_recency_48": touch_recency(bars, index, 48, average_range),
            "recross_count_12": recross_count(bars, index, 12, average_range),
            "recross_count_24": recross_count(bars, index, 24, average_range),
            "ribbon_compression_12_vs_48": ribbon_12 / max(ribbon_48, 1e-9),
            "ribbon_expansion_6_vs_24": ribbon_6 / max(ribbon_24, 1e-9),
            "day_ribbon_fraction_current": day_ribbon_fraction_current(bars, day, index, average_range),
            "session_progress": bounded(day["bars_since_day_open"] / 288.0, 0.0, 1.0),
            "spread_over_range": bar.spread_points / average_range,
            "spread_ribbon_stress_24": (bar.spread_points / average_range) * (1.0 + ribbon_24 + range_ribbon_24),
        }
    return contexts


def close_ribbon_fraction(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    if index < lookback:
        return 0.0
    current = bars[index].close
    band = max(0.32 * average_range, 1e-9)
    total = 0.0
    for offset in range(index - lookback, index):
        distance = abs(bars[offset].close - current)
        total += max(0.0, 1.0 - distance / band)
    return total / lookback


def range_ribbon_fraction(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
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


def ribbon_streak_norm(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
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
    ribbon = close_ribbon_fraction(bars, index, lookback, average_range)
    return net / max(1.0, math.sqrt(1.0 + ribbon * lookback))


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
    return context["ribbon_streak_24"] * max(0.0, 1.0 - recent_move)


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


def day_ribbon_fraction_current(
    bars: list[base.Bar],
    day_context: dict[str, float],
    index: int,
    average_range: float,
) -> float:
    lookback = int(min(day_context["bars_since_day_open"], 96.0))
    if lookback <= 0:
        return 0.0
    return close_ribbon_fraction(bars, index, lookback, average_range)


def day_ribbon_balance_directional(
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


def intraday_flow_convexity_release_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    day_context: list[dict[str, float] | None],
    ribbon_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> tuple[float, ...] | None:
    average_range = range_average[index]
    short_average_range = short_range_average[index]
    if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
        return None
    day = day_context[index]
    context = ribbon_context[index]
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
        context["ribbon_fraction_12"],
        context["ribbon_fraction_24"],
        context["ribbon_fraction_48"],
        context["range_ribbon_fraction_24"],
        context["range_ribbon_fraction_48"],
        context["ribbon_streak_24"],
        context["ribbon_streak_48"],
        context["touch_recency_48"],
        context["recross_count_12"],
        context["recross_count_24"],
        directional_recross_balance(bars, index, direction, 24, average_range),
        directional_recross_balance(bars, index, -direction, 24, average_range),
        context["ribbon_compression_12_vs_48"],
        context["ribbon_expansion_6_vs_24"],
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
        day_ribbon_balance_directional(bars, day, index, direction, average_range),
        day_transition_room(bars, day, index, direction, average_range),
        context["day_ribbon_fraction_current"],
        context["session_progress"],
        spread_over_range,
        context["spread_ribbon_stress_24"],
    )
    if len(features) != len(FEATURE_NAMES):
        raise RuntimeError(f"C0046 feature length mismatch: {len(features)} != {len(FEATURE_NAMES)}")
    return tuple(float(value) for value in features)


def intraday_flow_convexity_release_label(
    bars: list[base.Bar],
    range_average: list[float | None],
    ribbon_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> float | None:
    entry_index = index + 1
    exit_index = min(index + base.LABEL_HORIZON_BARS, len(bars) - 1)
    average_range = range_average[index]
    if average_range is None or average_range <= 0 or entry_index >= exit_index:
        return None
    context = ribbon_context[index]
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
    future_release = future_flow_convexity_release_retention(ribbon_context, entry_index, exit_index, direction)
    future_revisit = future_ribbon_revisit(path, entry, average_range)
    future_recross = future_recross_penalty(path, entry, direction, average_range)
    future_adverse_density = future_adverse_side_density(path, entry, direction, average_range)
    future_churn_penalty = future_path_churn(path, entry)
    pre_ribbon = 0.5 * context["ribbon_fraction_48"] + 0.5 * context["ribbon_streak_24"]
    return (
        0.82 * first_hit
        + 0.34 * target_speed
        - 0.46 * stop_speed
        - 0.58 * adverse_first
        + 0.26 * pre_ribbon
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


def future_flow_convexity_release_retention(
    ribbon_context: list[dict[str, float] | None],
    entry_index: int,
    exit_index: int,
    direction: int,
) -> float:
    values: list[float] = []
    for offset in range(entry_index, exit_index + 1):
        context = ribbon_context[offset]
        if context is None:
            continue
        values.append(
            0.32 * (1.0 - context["ribbon_fraction_24"])
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


def future_ribbon_revisit(path: list[base.Bar], entry: float, average_range: float) -> float:
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


def ema_series(values: list[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1.0)
    output: list[float] = []
    current: float | None = None
    for value in values:
        current = value if current is None else alpha * value + (1.0 - alpha) * current
        output.append(current)
    return output


def ribbon_stack_sign(fast: float, mid: float, slow: float) -> int:
    if fast > mid > slow:
        return 1
    if fast < mid < slow:
        return -1
    return 0


def build_flow_convexity_release_context(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    day_context: list[dict[str, float] | None],
) -> list[dict[str, float] | None]:
    closes = [bar.close for bar in bars]
    ema_fast = ema_series(closes, 8)
    ema_mid = ema_series(closes, 21)
    ema_slow = ema_series(closes, 55)
    width_values: list[float | None] = [None] * len(bars)
    for index in range(len(bars)):
        average_range = range_average[index]
        if average_range is None or average_range <= 0:
            continue
        ribbon_high = max(ema_fast[index], ema_mid[index], ema_slow[index])
        ribbon_low = min(ema_fast[index], ema_mid[index], ema_slow[index])
        width_values[index] = (ribbon_high - ribbon_low) / max(average_range, 1e-9)

    contexts: list[dict[str, float] | None] = [None] * len(bars)
    for index, bar in enumerate(bars):
        average_range = range_average[index]
        short_average_range = short_range_average[index]
        day = day_context[index]
        width = width_values[index]
        if (
            index < 120
            or average_range is None
            or average_range <= 0
            or short_average_range is None
            or short_average_range <= 0
            or day is None
            or width is None
        ):
            continue
        fast = ema_fast[index]
        mid = ema_mid[index]
        slow = ema_slow[index]
        ribbon_high = max(fast, mid, slow)
        ribbon_low = min(fast, mid, slow)
        stack = ribbon_stack_sign(fast, mid, slow)
        fast_slope_6 = (fast - ema_fast[index - 6]) / average_range
        fast_slope_12 = (fast - ema_fast[index - 12]) / average_range
        mid_slope_12 = (mid - ema_mid[index - 12]) / average_range
        mid_slope_24 = (mid - ema_mid[index - 24]) / average_range
        slow_slope_24 = (slow - ema_slow[index - 24]) / average_range
        prev_fast_slope_6 = (ema_fast[index - 6] - ema_fast[index - 12]) / average_range
        width_6 = width_values[index - 6] or width
        width_24 = width_values[index - 24] or width
        above_fraction, below_fraction = ribbon_side_fractions(bars, ema_fast, ema_mid, ema_slow, index, 24)
        session_progress = bounded(day["bars_since_day_open"] / 288.0, 0.0, 1.0)
        contexts[index] = {
            "average_range": average_range,
            "ema_fast": fast,
            "ema_mid": mid,
            "ema_slow": slow,
            "ribbon_high": ribbon_high,
            "ribbon_low": ribbon_low,
            "stack_sign": float(stack),
            "ribbon_width_atr": width,
            "ribbon_width_change_6": width / max(width_6, 1e-9) - 1.0,
            "ribbon_width_change_24": width / max(width_24, 1e-9) - 1.0,
            "ribbon_slope_fast_6": fast_slope_6,
            "ribbon_slope_fast_12": fast_slope_12,
            "ribbon_slope_mid_12": mid_slope_12,
            "ribbon_slope_mid_24": mid_slope_24,
            "ribbon_slope_slow_24": slow_slope_24,
            "slope_inflection_12": fast_slope_6 - prev_fast_slope_6,
            "price_above_ribbon_fraction_24": above_fraction,
            "price_below_ribbon_fraction_24": below_fraction,
            "session_progress": session_progress,
            "spread_over_range": bar.spread_points / average_range,
        }
    return contexts


def ribbon_side_fractions(
    bars: list[base.Bar],
    ema_fast: list[float],
    ema_mid: list[float],
    ema_slow: list[float],
    index: int,
    lookback: int,
) -> tuple[float, float]:
    above = 0
    below = 0
    total = 0
    for offset in range(index - lookback + 1, index + 1):
        if offset < 0:
            continue
        ribbon_high = max(ema_fast[offset], ema_mid[offset], ema_slow[offset])
        ribbon_low = min(ema_fast[offset], ema_mid[offset], ema_slow[offset])
        close = bars[offset].close
        above += int(close > ribbon_high)
        below += int(close < ribbon_low)
        total += 1
    return above / max(total, 1), below / max(total, 1)


def intraday_flow_convexity_release_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    day_context: list[dict[str, float] | None],
    ribbon_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> tuple[float, ...] | None:
    average_range = range_average[index]
    short_average_range = short_range_average[index]
    if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
        return None
    day = day_context[index]
    context = ribbon_context[index]
    if day is None or context is None:
        return None
    spread_over_range = bars[index].spread_points / average_range
    if spread_over_range > 0.65:
        return None
    fast = context["ema_fast"]
    mid = context["ema_mid"]
    slow = context["ema_slow"]
    fast_mid = direction * (fast - mid) / average_range
    mid_slow = direction * (mid - slow) / average_range
    stack_alignment = min(fast_mid, mid_slow)
    stack_opposition = max(0.0, -fast_mid) + max(0.0, -mid_slow)
    slope_values = (
        context["ribbon_slope_fast_6"],
        context["ribbon_slope_mid_12"],
        context["ribbon_slope_slow_24"],
    )
    slope_consensus = sum(
        1.0 if direction * value > 0 else -1.0 if direction * value < 0 else 0.0 for value in slope_values
    ) / 3.0
    breach_24 = ribbon_breach_pressure(bars, ribbon_context, index, direction, 24)
    features = (
        float(direction),
        direction * (bars[index].close - bars[index - 1].close) / average_range,
        direction * (bars[index].close - bars[index - 3].close) / average_range,
        direction * (bars[index].close - bars[index - 6].close) / average_range,
        direction * (bars[index].close - bars[index - 12].close) / average_range,
        direction * (bars[index].close - fast) / average_range,
        direction * (bars[index].close - mid) / average_range,
        direction * (bars[index].close - slow) / average_range,
        stack_alignment,
        stack_opposition,
        context["ribbon_width_atr"],
        context["ribbon_width_change_6"],
        context["ribbon_width_change_24"],
        direction * context["ribbon_slope_fast_6"],
        direction * context["ribbon_slope_fast_12"],
        direction * context["ribbon_slope_mid_12"],
        direction * context["ribbon_slope_mid_24"],
        direction * context["ribbon_slope_slow_24"],
        slope_consensus,
        direction * context["slope_inflection_12"],
        context["price_above_ribbon_fraction_24"],
        context["price_below_ribbon_fraction_24"],
        pullback_to_ema_depth(bars, ribbon_context, index, direction, "ema_fast", 12),
        pullback_to_ema_depth(bars, ribbon_context, index, direction, "ema_mid", 24),
        ribbon_retest_recency(bars, ribbon_context, index, 24),
        ribbon_retest_acceptance(bars, ribbon_context, index, direction, 12),
        ribbon_breach_pressure(bars, ribbon_context, index, direction, 12),
        breach_24,
        ribbon_recapture_pressure(bars, ribbon_context, index, direction, 12),
        ribbon_recapture_pressure(bars, ribbon_context, index, direction, 24),
        ribbon_trend_age(bars, ribbon_context, index, direction, 48),
        ribbon_phase_shift(ribbon_context, index, direction, 24),
        max(0.0, -context["ribbon_width_change_24"])
        * max(0.0, direction * (bars[index].close - bars[index - 6].close) / average_range),
        max(0.0, context["ribbon_width_change_24"]) * max(0.0, breach_24),
        body_ribbon_alignment(bars, index, direction, 6, average_range),
        body_ribbon_alignment(bars, index, direction, 12, average_range),
        wick_ribbon_rejection(bars, ribbon_context, index, direction, 6),
        directional_efficiency(bars, index, direction, 12),
        path_churn_ratio(bars, index, 12),
        direction * (bars[index].close - mid) / average_range * (0.5 + context["session_progress"]),
        context["session_progress"],
        spread_over_range,
        spread_over_range * (1.0 + context["ribbon_width_atr"] + breach_24),
    )
    if len(features) != len(FEATURE_NAMES):
        raise RuntimeError(f"C0046 feature length mismatch: {len(features)} != {len(FEATURE_NAMES)}")
    return tuple(float(value) for value in features)


def pullback_to_ema_depth(
    bars: list[base.Bar],
    ribbon_context: list[dict[str, float] | None],
    index: int,
    direction: int,
    ema_key: str,
    lookback: int,
) -> float:
    depth = 0.0
    for offset in range(index - lookback + 1, index + 1):
        context = ribbon_context[offset]
        if context is None:
            continue
        average_range = context["average_range"]
        ema_value = context[ema_key]
        if direction > 0:
            depth = max(depth, (ema_value - bars[offset].low) / max(average_range, 1e-9))
        else:
            depth = max(depth, (bars[offset].high - ema_value) / max(average_range, 1e-9))
    return max(0.0, depth)


def ribbon_retest_recency(
    bars: list[base.Bar],
    ribbon_context: list[dict[str, float] | None],
    index: int,
    lookback: int,
) -> float:
    for age, offset in enumerate(range(index, index - lookback, -1), start=0):
        context = ribbon_context[offset]
        if context is None:
            continue
        band = max(0.10 * context["average_range"], 1e-9)
        if bars[offset].low <= context["ribbon_high"] + band and bars[offset].high >= context["ribbon_low"] - band:
            return 1.0 - age / lookback
    return 0.0


def ribbon_retest_acceptance(
    bars: list[base.Bar],
    ribbon_context: list[dict[str, float] | None],
    index: int,
    direction: int,
    lookback: int,
) -> float:
    score = 0.0
    hits = 0
    for offset in range(index - lookback + 1, index + 1):
        context = ribbon_context[offset]
        if context is None:
            continue
        band = max(0.10 * context["average_range"], 1e-9)
        touched = bars[offset].low <= context["ribbon_high"] + band and bars[offset].high >= context["ribbon_low"] - band
        if not touched:
            continue
        distance = direction * (bars[offset].close - context["ema_mid"]) / max(context["average_range"], 1e-9)
        score += max(-1.0, min(2.0, distance))
        hits += 1
    return score / max(hits, 1)


def ribbon_breach_pressure(
    bars: list[base.Bar],
    ribbon_context: list[dict[str, float] | None],
    index: int,
    direction: int,
    lookback: int,
) -> float:
    pressure = 0.0
    for offset in range(index - lookback + 1, index + 1):
        context = ribbon_context[offset]
        if context is None:
            continue
        if direction > 0:
            breach = context["ribbon_low"] - bars[offset].close
        else:
            breach = bars[offset].close - context["ribbon_high"]
        pressure += max(0.0, breach / max(context["average_range"], 1e-9))
    return pressure / max(lookback, 1)


def ribbon_recapture_pressure(
    bars: list[base.Bar],
    ribbon_context: list[dict[str, float] | None],
    index: int,
    direction: int,
    lookback: int,
) -> float:
    captures = 0.0
    previous_side = 0
    for offset in range(index - lookback + 1, index + 1):
        context = ribbon_context[offset]
        if context is None:
            continue
        side = 1 if direction * (bars[offset].close - context["ema_mid"]) > 0 else -1
        if previous_side < 0 and side > 0:
            captures += min(abs(bars[offset].close - context["ema_mid"]) / max(context["average_range"], 1e-9), 2.0)
        previous_side = side
    return captures / max(lookback, 1)


def ribbon_trend_age(
    bars: list[base.Bar],
    ribbon_context: list[dict[str, float] | None],
    index: int,
    direction: int,
    lookback: int,
) -> float:
    age = 0
    for offset in range(index, index - lookback, -1):
        context = ribbon_context[offset]
        if context is None or direction * context["stack_sign"] <= 0:
            break
        age += 1
    return age / lookback


def ribbon_phase_shift(
    ribbon_context: list[dict[str, float] | None],
    index: int,
    direction: int,
    lookback: int,
) -> float:
    current = ribbon_context[index]
    previous = ribbon_context[index - lookback]
    if current is None or previous is None:
        return 0.0
    return direction * (current["stack_sign"] - previous["stack_sign"]) / 2.0


def body_ribbon_alignment(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    total = 0.0
    for offset in range(index - lookback + 1, index + 1):
        total += direction * (bars[offset].close - bars[offset].open) / max(average_range, 1e-9)
    return total / max(lookback, 1)


def wick_ribbon_rejection(
    bars: list[base.Bar],
    ribbon_context: list[dict[str, float] | None],
    index: int,
    direction: int,
    lookback: int,
) -> float:
    score = 0.0
    for offset in range(index - lookback + 1, index + 1):
        context = ribbon_context[offset]
        if context is None:
            continue
        average_range = max(context["average_range"], 1e-9)
        if direction > 0:
            pierced = max(0.0, context["ema_mid"] - bars[offset].low) / average_range
            accepted = max(0.0, bars[offset].close - context["ema_fast"]) / average_range
        else:
            pierced = max(0.0, bars[offset].high - context["ema_mid"]) / average_range
            accepted = max(0.0, context["ema_fast"] - bars[offset].close) / average_range
        score += min(pierced, 2.0) * min(accepted, 2.0)
    return score / max(lookback, 1)


def intraday_flow_convexity_release_label(
    bars: list[base.Bar],
    range_average: list[float | None],
    ribbon_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> float | None:
    entry_index = index + 1
    exit_index = min(index + base.LABEL_HORIZON_BARS, len(bars) - 1)
    average_range = range_average[index]
    context = ribbon_context[index]
    if average_range is None or average_range <= 0 or context is None or entry_index >= exit_index:
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
    close_path = [entry] + [bar.close for bar in path]
    path_distance = sum(abs(close_path[offset] - close_path[offset - 1]) for offset in range(1, len(close_path)))
    path_efficiency = terminal / max(path_distance, 1e-9)
    path_alignment = aligned_close_count / len(path) - 0.5
    target_speed = (len(path) - event_bar + 1) / len(path) if first_hit > 0.0 else 0.0
    stop_speed = (len(path) - event_bar + 1) / len(path) if first_hit < 0.0 else 0.0
    giveback = max(0.0, favorable - max(terminal_norm, 0.0))
    early_path = path[: min(3, len(path))]
    if direction > 0:
        early_followthrough = max(bar.high - entry for bar in early_path) / average_range
        early_adverse = max(entry - bar.low for bar in early_path) / average_range
    else:
        early_followthrough = max(entry - bar.low for bar in early_path) / average_range
        early_adverse = max(bar.high - entry for bar in early_path) / average_range
    spread_norm = bars[entry_index].spread_points / average_range
    path_spread_peak = max(bar.spread_points for bar in path) / average_range
    future_acceptance = future_ribbon_side_acceptance(bars, ribbon_context, entry_index, exit_index, direction)
    future_breach = future_ribbon_breach_penalty(bars, ribbon_context, entry_index, exit_index, direction)
    future_recapture = future_ribbon_recapture_after_breach(bars, ribbon_context, entry_index, exit_index, direction)
    current_alignment = max(0.0, direction * context["stack_sign"]) + max(0.0, direction * context["ribbon_slope_mid_12"])
    compression_break = max(0.0, -context["ribbon_width_change_24"]) * max(
        0.0,
        direction * (bars[index].close - bars[index - 6].close) / average_range,
    )
    return (
        0.84 * first_hit
        + 0.34 * target_speed
        - 0.46 * stop_speed
        - 0.56 * adverse_first
        + 0.22 * current_alignment
        + 0.30 * compression_break
        + 0.32 * early_followthrough
        - 0.34 * early_adverse
        + 0.28 * favorable
        - 0.62 * adverse
        + 0.38 * terminal_norm
        + 0.32 * path_efficiency
        + 0.24 * path_alignment
        - 0.30 * giveback
        + 0.38 * future_acceptance
        + 0.18 * future_recapture
        - 0.42 * future_breach
        - 0.20 * future_path_churn(path, entry)
        - 1.08 * spread_norm
        - 0.20 * max(0.0, path_spread_peak - spread_norm)
    )


def future_ribbon_side_acceptance(
    bars: list[base.Bar],
    ribbon_context: list[dict[str, float] | None],
    entry_index: int,
    exit_index: int,
    direction: int,
) -> float:
    values: list[float] = []
    for offset in range(entry_index, exit_index + 1):
        context = ribbon_context[offset]
        if context is None:
            continue
        distance = direction * (bars[offset].close - context["ema_mid"]) / max(context["average_range"], 1e-9)
        values.append(max(-1.5, min(2.5, distance)))
    return sum(values) / max(len(values), 1)


def future_ribbon_breach_penalty(
    bars: list[base.Bar],
    ribbon_context: list[dict[str, float] | None],
    entry_index: int,
    exit_index: int,
    direction: int,
) -> float:
    penalty = 0.0
    for offset in range(entry_index, exit_index + 1):
        context = ribbon_context[offset]
        if context is None:
            continue
        if direction > 0:
            breach = context["ribbon_low"] - bars[offset].close
        else:
            breach = bars[offset].close - context["ribbon_high"]
        penalty = max(penalty, breach / max(context["average_range"], 1e-9))
    return max(0.0, penalty)


def future_ribbon_recapture_after_breach(
    bars: list[base.Bar],
    ribbon_context: list[dict[str, float] | None],
    entry_index: int,
    exit_index: int,
    direction: int,
) -> float:
    breached = False
    recapture = 0.0
    for offset in range(entry_index, exit_index + 1):
        context = ribbon_context[offset]
        if context is None:
            continue
        side = direction * (bars[offset].close - context["ema_mid"])
        if side < 0:
            breached = True
        elif breached and side > 0:
            recapture = max(recapture, side / max(context["average_range"], 1e-9))
    return min(recapture, 2.0)


def normalized_close_return(
    bars: list[base.Bar],
    range_average: list[float | None],
    index: int,
) -> float:
    if index <= 0:
        return 0.0
    average_range = range_average[index]
    if average_range is None or average_range <= 0:
        average_range = max(bars[index].high - bars[index].low, 1e-9)
    return (bars[index].close - bars[index - 1].close) / max(average_range, 1e-9)


def rolling_return_values(
    bars: list[base.Bar],
    range_average: list[float | None],
    index: int,
    lookback: int,
) -> list[float]:
    start = max(1, index - lookback + 1)
    return [normalized_close_return(bars, range_average, offset) for offset in range(start, index + 1)]


def close_delta_atr(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    if index < lookback:
        return 0.0
    return (bars[index].close - bars[index - lookback].close) / max(average_range, 1e-9)


def return_distribution_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "mean": 0.0,
            "std": 1.0,
            "skew": 0.0,
            "kurtosis": 0.0,
            "positive_share": 0.0,
            "negative_share": 0.0,
            "tail_mass": 0.0,
            "tail_balance": 0.0,
        }
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / max(len(values), 1)
    std = math.sqrt(max(variance, 1e-12))
    centered = [(value - mean) / std for value in values]
    positive_tail = sum(1 for value in centered if value > 1.25) / len(centered)
    negative_tail = sum(1 for value in centered if value < -1.25) / len(centered)
    return {
        "mean": mean,
        "std": std,
        "skew": bounded(sum(value**3 for value in centered) / len(centered), -6.0, 6.0),
        "kurtosis": bounded(sum(value**4 for value in centered) / len(centered) - 3.0, -3.0, 12.0),
        "positive_share": sum(1 for value in values if value > 0.0) / len(values),
        "negative_share": sum(1 for value in values if value < 0.0) / len(values),
        "tail_mass": positive_tail + negative_tail,
        "tail_balance": positive_tail - negative_tail,
    }


def zscore(value: float, mean: float, std: float) -> float:
    return bounded((value - mean) / max(std, 1e-9), -8.0, 8.0)


def quantile_position(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    return sum(1 for item in values if item <= value) / len(values) - 0.5


def outlier_cluster_count(values: list[float]) -> float:
    if not values:
        return 0.0
    stats = return_distribution_stats(values)
    clusters = 0
    in_cluster = False
    for value in values:
        is_tail = abs(zscore(value, stats["mean"], stats["std"])) > 1.25
        if is_tail and not in_cluster:
            clusters += 1
        in_cluster = is_tail
    return clusters / len(values)


def sign_run_norm(values: list[float]) -> float:
    if not values:
        return 0.0
    last_sign = 1 if values[-1] > 0.0 else -1 if values[-1] < 0.0 else 0
    if last_sign == 0:
        return 0.0
    run = 0
    for value in reversed(values):
        sign = 1 if value > 0.0 else -1 if value < 0.0 else 0
        if sign != last_sign:
            break
        run += 1
    return last_sign * run / len(values)


def tail_decay_signed(values: list[float]) -> float:
    if len(values) < 4:
        return 0.0
    stats = return_distribution_stats(values)
    current_z = zscore(values[-1], stats["mean"], stats["std"])
    prior_tail = max(abs(zscore(value, stats["mean"], stats["std"])) for value in values[:-1])
    decay = max(0.0, prior_tail - abs(current_z))
    return (1.0 if current_z >= 0.0 else -1.0) * bounded(decay, 0.0, 4.0)


def calm_to_tail_transition(values: list[float]) -> float:
    if len(values) < 8:
        return 0.0
    stats = return_distribution_stats(values)
    prior = [abs(zscore(value, stats["mean"], stats["std"])) for value in values[:-3]]
    recent = [abs(zscore(value, stats["mean"], stats["std"])) for value in values[-3:]]
    prior_tail_pressure = sum(prior[-8:]) / max(len(prior[-8:]), 1)
    calm = 1.0 - bounded(prior_tail_pressure, 0.0, 1.0)
    tail = bounded(max(recent) - 1.0, 0.0, 3.0)
    return calm * tail


def tail_to_calm_transition(values: list[float]) -> float:
    if len(values) < 8:
        return 0.0
    stats = return_distribution_stats(values)
    prior_tail = max(abs(zscore(value, stats["mean"], stats["std"])) for value in values[:-3])
    recent_mean = sum(abs(zscore(value, stats["mean"], stats["std"])) for value in values[-3:]) / 3.0
    return max(0.0, prior_tail - max(recent_mean, 1.0))


def mean_abs(values: list[float]) -> float:
    return sum(abs(value) for value in values) / max(len(values), 1)


def body_return_agreement(bars: list[base.Bar], index: int, lookback: int) -> float:
    total = 0.0
    count = 0
    for offset in range(max(1, index - lookback + 1), index + 1):
        close_change = bars[offset].close - bars[offset - 1].close
        body_change = bars[offset].close - bars[offset].open
        close_sign = 1 if close_change > 0.0 else -1 if close_change < 0.0 else 0
        body_sign = 1 if body_change > 0.0 else -1 if body_change < 0.0 else 0
        if close_sign == 0 or body_sign == 0:
            continue
        total += 1.0 if close_sign == body_sign else -1.0
        count += 1
    return total / max(count, 1)


def sign_value(value: float) -> int:
    if value > 0.0:
        return 1
    if value < 0.0:
        return -1
    return 0



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
        "score_interpretation": "higher_score_means_direct_fold_local_intraday_flow_convexity_release_rank",
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
    payload["campaign_id"] = "C0046"
    payload["work_unit_id"] = "C0046"
    payload["run_id"] = "R0001"
    payload["proxy_id"] = "PX-C0046-R0001"
    payload["proxy_engine"] = "axiom_rift.proxies.c0046_r0001_intraday_flow_convexity_release"
    payload["proxy_config_path"] = "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_intraday_flow_convexity_release_rank_fit"
    payload["claim_boundary"] = dict(CLAIM_BOUNDARY)
    payload["proxy_artifact_paths"] = [
        "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/kpi/proxy.json",
        "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/artifacts/c0046_r0001_proxy_trades.csv",
        "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/artifacts/c0046_r0001_flow_convexity_release_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["intraday_flow_convexity_release_profile"] = {  # type: ignore[index]
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
            "next_action": "produce_c0046_r0001_mt5_logic_parity_evidence",
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
            "score_interpretation": "higher_score_means_direct_fold_local_intraday_flow_convexity_release_rank",
            "variant_boundary": (
                "intraday_flow_convexity_release_rank_not_effort_absorption_seasonal_residual_tail_risk_skew_entropy_"
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
    write_flow_convexity_release_summary_artifact(payload, FLOW_CONVEXITY_RELEASE_SUMMARY_PATH)
    write_text_local(PROXY_PATH, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    trade_hash = sha256_file_local(TRADE_ARTIFACT_PATH)
    summary_hash = sha256_file_local(FLOW_CONVEXITY_RELEASE_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = sha256_file_local(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)
    update_decision_cursor_after_proxy(payload)


def write_flow_convexity_release_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_fold_local_intraday_flow_convexity_release_summary_v1",
        "template": False,
        "work_unit_id": "C0046",
        "campaign_id": "C0046",
        "run_id": "R0001",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "intraday_flow_convexity_release_profile": profiles["intraday_flow_convexity_release_profile"]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "intraday_flow_convexity_release_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-C0046-R0001-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-C0046-R0001-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/artifacts/c0046_r0001_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0046-R0001-EXTREME-RECENCY-GRADIENT-SUMMARY",
                "intraday_flow_convexity_release_summary_artifact",
                "json",
                "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/artifacts/c0046_r0001_flow_convexity_release_summary.json",
                summary_hash,
                ["campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0046_r0001_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0046_r0001_intraday_flow_convexity_release",
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
    evidence["proxy_trade_artifact"] = "artifacts/c0046_r0001_proxy_trades.csv"
    evidence["intraday_flow_convexity_release_summary"] = "artifacts/c0046_r0001_flow_convexity_release_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    parity_gate = data.setdefault("parity_gate", {})
    parity_gate.setdefault("mechanical_parity_status", "pending")
    parity_gate.setdefault("intent_parity_status", "pending")
    parity_gate.setdefault("mismatch_count", None)
    parity_gate.setdefault("repair_required", False)
    parity_gate["status"] = "blocked_until_mt5"
    data.setdefault("proxy_gate", {})["status"] = "recorded"
    data.setdefault("mt5_gate", {})["status"] = "pending_logic_parity"
    data.setdefault("rolling_window_closeout_gate", {})["status"] = "pending_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0046_r0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0046_r0001_proxy_trades.csv",
        "artifacts/c0046_r0001_flow_convexity_release_summary.json",
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
            "revisit_when": "after C0046 R0001 MT5 evidence files contain measured results",
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
    next_candidate["direction"] = "active_c0046_r0001_mt5_logic_parity"
    next_candidate["reason"] = "R0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0046_r0001_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    data = yaml.safe_load(REENTRY_PATH.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = "campaigns/C0046_intraday_flow_convexity_release_discovery"
    data["project"]["active_run"] = "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001"
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = "campaigns/C0046_intraday_flow_convexity_release_discovery"
    completed = list(next_work.get("completed") or [])
    for item in (
        "open_c0046_intraday_flow_convexity_release_discovery",
        "open_c0046_r0001_fold_local_intraday_flow_convexity_release_rank_run",
        "produce_c0046_r0001_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_c0046_r0001_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_campaign"] = "campaigns/C0046_intraday_flow_convexity_release_discovery"
    data["active_run"] = "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001"
    REENTRY_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0046_intraday_flow_convexity_release_discovery"
    data["active_run"] = "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001"
    data["latest_operation"] = {
        "id": "produce_c0046_r0001_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0046_r0001_mt5_logic_parity_evidence",
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_decision_cursor_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(DECISION_CURSOR_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["updated_local_date"] = "2026-07-06"
    data["canonical_source"] = "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/kpi/proxy.json"
    data["canonical_status"] = "proxy_recorded_pending_mt5"
    data["current_decision"] = "produce_c0046_r0001_mt5_logic_parity_evidence"
    data["active_campaign"] = "campaigns/C0046_intraday_flow_convexity_release_discovery"
    data["active_run"] = "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001"
    data["next_required_action"] = "produce_c0046_r0001_mt5_logic_parity_evidence"
    data["current_evidence_summary"] = {
        "source_campaign": "campaigns/C0046_intraday_flow_convexity_release_discovery",
        "current_task": "produce_c0046_r0001_mt5_logic_parity_evidence",
        "active_run": "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001",
        "active_run_status": "proxy_recorded_pending_mt5",
        "evidence_status": "proxy_recorded_pending_mt5",
        "campaign_family": "intraday_flow_convexity_release",
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0046_r0001_mt5_logic_parity_evidence",
        "note": "C0046 R0001 proxy evidence recorded; MT5 paired validation remains mandatory regardless of proxy result.",
        "source_campaign_manifest": "campaigns/C0046_intraday_flow_convexity_release_discovery/campaign.yaml",
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
            "C0004": "C0046",
            "c0004_r0001_fold_local_state_archetype": "c0046_r0001_intraday_flow_convexity_release",
            "c0004_r0001": "c0046_r0001",
            "fold_local_state_archetype_discovery": "intraday_flow_convexity_release_discovery",
            "fold_local_train_only_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "intraday_flow_convexity_release_summary",
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


def build_flow_convexity_release_context(
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
        if (
            index < 120
            or average_range is None
            or average_range <= 0
            or short_average_range is None
            or short_average_range <= 0
            or day is None
        ):
            continue
        ret_1 = close_return_atr(bars, index, 1, average_range)
        ret_3 = close_return_atr(bars, index, 3, average_range)
        ret_6 = close_return_atr(bars, index, 6, average_range)
        ret_12 = close_return_atr(bars, index, 12, average_range)
        ret_24 = close_return_atr(bars, index, 24, average_range)
        prev_ret_3 = close_return_atr(bars, index - 3, 3, average_range)
        energy_6 = flow_energy_atr(bars, index, 6, average_range)
        energy_12 = flow_energy_atr(bars, index, 12, average_range)
        energy_24 = flow_energy_atr(bars, index, 24, average_range)
        day_range = max(day["day_high"] - day["day_low"], 1e-9)
        contexts[index] = {
            "ret_1": ret_1,
            "ret_3": ret_3,
            "ret_6": ret_6,
            "ret_12": ret_12,
            "ret_24": ret_24,
            "prev_ret_3": prev_ret_3,
            "energy_6": energy_6,
            "energy_12": energy_12,
            "energy_24": energy_24,
            "range_expansion_6_24": short_average_range / max(average_range, 1e-9) - 1.0,
            "day_open": day["day_open"],
            "day_high": day["day_high"],
            "day_low": day["day_low"],
            "day_mid": day["day_low"] + 0.5 * day_range,
            "day_range": day_range,
            "session_progress": bounded(day["bars_since_day_open"] / 288.0, 0.0, 1.0),
            "spread_over_range": bar.spread_points / average_range,
        }
    return contexts


def intraday_flow_convexity_release_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    day_context: list[dict[str, float] | None],
    flow_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> tuple[float, ...] | None:
    average_range = range_average[index]
    short_average_range = short_range_average[index]
    if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
        return None
    context = flow_context[index]
    if context is None:
        return None
    spread_over_range = context["spread_over_range"]
    if spread_over_range > 0.65:
        return None

    signed_flow_6 = direction * close_flow_sum_atr(bars, index, 6, average_range)
    signed_flow_12 = direction * close_flow_sum_atr(bars, index, 12, average_range)
    signed_flow_24 = direction * close_flow_sum_atr(bars, index, 24, average_range)
    pressure_build_12 = max(0.0, -signed_flow_12)
    pressure_build_24 = max(0.0, -signed_flow_24)
    opposing_pressure_12 = max(0.0, -direction * body_flow_sum_atr(bars, index, 12, average_range))
    release_1 = max(0.0, direction * context["ret_1"])
    release_3 = max(0.0, direction * context["ret_3"])
    release_6 = max(0.0, direction * context["ret_6"])
    acceleration_3_12 = direction * (context["ret_3"] - 0.25 * context["ret_12"])
    acceleration_6_24 = direction * (context["ret_6"] - 0.25 * context["ret_24"])
    acceleration_inflection = direction * (context["ret_3"] - context["prev_ret_3"])
    body_align_6 = direction * body_flow_sum_atr(bars, index, 6, average_range)
    body_align_12 = direction * body_flow_sum_atr(bars, index, 12, average_range)
    day_return = direction * (bars[index].close - context["day_open"]) / average_range
    if direction > 0:
        day_position = (bars[index].close - context["day_low"]) / context["day_range"]
    else:
        day_position = (context["day_high"] - bars[index].close) / context["day_range"]
    day_balance = direction * (bars[index].close - context["day_mid"]) / average_range
    energy_contraction = max(0.0, context["energy_24"] - context["energy_6"])
    energy_expansion = max(0.0, context["energy_6"] - context["energy_24"])
    pressure_release_alignment = (
        0.42 * release_3
        + 0.26 * body_align_6
        + 0.18 * max(0.0, pressure_build_12 - opposing_pressure_12)
        - 0.24 * opposing_pressure_12
    )
    convexity_energy_interaction = acceleration_3_12 * (0.55 + context["energy_6"] + 0.25 * context["energy_12"])
    features = (
        float(direction),
        direction * context["ret_1"],
        direction * context["ret_3"],
        direction * context["ret_6"],
        direction * context["ret_12"],
        direction * context["ret_24"],
        acceleration_3_12,
        acceleration_6_24,
        acceleration_inflection,
        signed_flow_6,
        signed_flow_12,
        signed_flow_24,
        context["energy_6"],
        context["energy_12"],
        context["energy_24"],
        energy_contraction,
        energy_expansion,
        pressure_build_12,
        pressure_build_24,
        opposing_pressure_12,
        release_1,
        release_3,
        release_6,
        body_align_6,
        body_align_12,
        body_close_agreement(bars, index, 12),
        favorable_wick_acceptance(bars, index, direction, 6, average_range),
        opposing_wick_rejection(bars, index, direction, 6, average_range),
        directional_path_efficiency(bars, index, direction, 12),
        flow_path_churn_ratio(bars, index, 12),
        day_return,
        day_balance,
        bounded(day_position, 0.0, 1.0),
        context["range_expansion_6_24"],
        context["session_progress"],
        spread_over_range,
        spread_over_range * (1.0 + context["energy_6"] + pressure_build_12 + release_3),
        pressure_release_alignment,
        convexity_energy_interaction,
    )
    if len(features) != len(FEATURE_NAMES):
        raise RuntimeError(f"C0046 feature length mismatch: {len(features)} != {len(FEATURE_NAMES)}")
    return tuple(float(value) for value in features)


def intraday_flow_convexity_release_label(
    bars: list[base.Bar],
    range_average: list[float | None],
    flow_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> float | None:
    entry_index = index + 1
    exit_index = min(index + base.LABEL_HORIZON_BARS, len(bars) - 1)
    average_range = range_average[index]
    context = flow_context[index]
    if average_range is None or average_range <= 0 or context is None or entry_index >= exit_index:
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
    close_path = [entry] + [bar.close for bar in path]
    path_distance = sum(abs(close_path[offset] - close_path[offset - 1]) for offset in range(1, len(close_path)))
    path_efficiency = terminal / max(path_distance, 1e-9)
    target_speed = (len(path) - event_bar + 1) / len(path) if first_hit > 0.0 else 0.0
    stop_speed = (len(path) - event_bar + 1) / len(path) if first_hit < 0.0 else 0.0
    giveback = max(0.0, favorable - max(terminal_norm, 0.0))
    early_path = path[: min(3, len(path))]
    if direction > 0:
        early_followthrough = max(bar.high - entry for bar in early_path) / average_range
        early_adverse = max(entry - bar.low for bar in early_path) / average_range
    else:
        early_followthrough = max(entry - bar.low for bar in early_path) / average_range
        early_adverse = max(bar.high - entry for bar in early_path) / average_range
    future_acceptance = sum(
        max(-1.5, min(2.5, direction * (bar.close - entry) / average_range)) for bar in path
    ) / len(path)
    favorable_body_share = sum(1 for bar in path if direction * (bar.close - bar.open) > 0.0) / len(path)
    opposing_close_share = sum(1 for bar in path if direction * (bar.close - entry) < -0.22 * average_range) / len(path)
    pre_pressure = max(0.0, -direction * context["ret_12"])
    pre_release = max(0.0, direction * context["ret_3"])
    spread_norm = bars[entry_index].spread_points / average_range
    path_spread_peak = max(bar.spread_points for bar in path) / average_range
    return (
        0.86 * first_hit
        + 0.34 * target_speed
        - 0.48 * stop_speed
        - 0.56 * adverse_first
        + 0.24 * pre_pressure
        + 0.26 * pre_release
        + 0.34 * early_followthrough
        - 0.36 * early_adverse
        + 0.28 * favorable
        - 0.62 * adverse
        + 0.40 * terminal_norm
        + 0.32 * path_efficiency
        - 0.28 * giveback
        + 0.36 * future_acceptance
        + 0.20 * favorable_body_share
        - 0.30 * opposing_close_share
        - 0.22 * future_path_churn(path, entry)
        - 1.08 * spread_norm
        - 0.20 * max(0.0, path_spread_peak - spread_norm)
    )


def close_return_atr(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    if index < lookback:
        return 0.0
    return (bars[index].close - bars[index - lookback].close) / max(average_range, 1e-9)


def close_flow_sum_atr(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    start = max(1, index - lookback + 1)
    return sum((bars[offset].close - bars[offset - 1].close) / max(average_range, 1e-9) for offset in range(start, index + 1))


def body_flow_sum_atr(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    start = max(0, index - lookback + 1)
    return sum((bars[offset].close - bars[offset].open) / max(average_range, 1e-9) for offset in range(start, index + 1))


def flow_energy_atr(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    start = max(1, index - lookback + 1)
    count = max(index - start + 1, 1)
    return sum(abs(bars[offset].close - bars[offset - 1].close) / max(average_range, 1e-9) for offset in range(start, index + 1)) / count


def body_close_agreement(bars: list[base.Bar], index: int, lookback: int) -> float:
    total = 0.0
    count = 0
    for offset in range(max(1, index - lookback + 1), index + 1):
        close_change = bars[offset].close - bars[offset - 1].close
        body_change = bars[offset].close - bars[offset].open
        close_sign = 1 if close_change > 0.0 else -1 if close_change < 0.0 else 0
        body_sign = 1 if body_change > 0.0 else -1 if body_change < 0.0 else 0
        if close_sign == 0 or body_sign == 0:
            continue
        total += 1.0 if close_sign == body_sign else -1.0
        count += 1
    return total / max(count, 1)


def favorable_wick_acceptance(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    total = 0.0
    for offset in range(index - lookback + 1, index + 1):
        bar = bars[offset]
        if direction > 0:
            excursion = max(0.0, bar.high - bar.open)
            acceptance = max(0.0, bar.close - bar.open)
        else:
            excursion = max(0.0, bar.open - bar.low)
            acceptance = max(0.0, bar.open - bar.close)
        total += min(excursion / max(average_range, 1e-9), 2.0) * min(acceptance / max(average_range, 1e-9), 2.0)
    return total / max(lookback, 1)


def opposing_wick_rejection(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    total = 0.0
    for offset in range(index - lookback + 1, index + 1):
        bar = bars[offset]
        if direction > 0:
            adverse_wick = max(0.0, bar.open - bar.low)
            rejection = max(0.0, bar.open - bar.close)
        else:
            adverse_wick = max(0.0, bar.high - bar.open)
            rejection = max(0.0, bar.close - bar.open)
        total += min(adverse_wick / max(average_range, 1e-9), 2.0) * min(rejection / max(average_range, 1e-9), 2.0)
    return total / max(lookback, 1)


def directional_path_efficiency(bars: list[base.Bar], index: int, direction: int, lookback: int) -> float:
    start = max(0, index - lookback)
    net = direction * (bars[index].close - bars[start].close)
    distance = sum(abs(bars[offset].close - bars[offset - 1].close) for offset in range(start + 1, index + 1))
    return net / max(distance, 1e-9)


def flow_path_churn_ratio(bars: list[base.Bar], index: int, lookback: int) -> float:
    start = max(1, index - lookback + 1)
    changes = [abs(bars[offset].close - bars[offset - 1].close) for offset in range(start, index + 1)]
    net = abs(bars[index].close - bars[start - 1].close)
    return sum(changes) / max(net, 1e-9)


def bar_range_value(bar: base.Bar) -> float:
    return max(bar.high - bar.low, 0.0)


def range_window_values(bars: list[base.Bar], index: int, lookback: int) -> list[float]:
    start = max(0, index - lookback + 1)
    return [bar_range_value(bars[offset]) for offset in range(start, index + 1)]


def range_mean_value(bars: list[base.Bar], index: int, lookback: int) -> float:
    values = range_window_values(bars, index, lookback)
    return sum(values) / max(len(values), 1)


def range_std_ratio(bars: list[base.Bar], index: int, lookback: int) -> float:
    values = range_window_values(bars, index, lookback)
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(max(variance, 0.0)) / max(mean, 1e-9)


def extreme_recency_ratio_at(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    baseline = max(range_mean_value(bars, max(0, index - 1), lookback), average_range, 1e-9)
    return bar_range_value(bars[index]) / baseline


def shock_cluster_density_at(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    values = range_window_values(bars, index, lookback)
    if not values:
        return 0.0
    threshold = 1.35 * max(average_range, 1e-9)
    return sum(1 for value in values if value >= threshold) / len(values)


def strongest_extreme_recency_index(
    bars: list[base.Bar],
    range_average: list[float | None],
    index: int,
    lookback: int,
    fallback_average_range: float,
) -> int:
    start = max(1, index - lookback + 1)
    best_index = index
    best_ratio = -1.0
    for offset in range(start, index + 1):
        average = range_average[offset] if range_average[offset] is not None else fallback_average_range
        ratio = bar_range_value(bars[offset]) / max(float(average), 1e-9)
        if ratio > best_ratio:
            best_ratio = ratio
            best_index = offset
    return best_index


def bar_body_direction(bar: base.Bar) -> int:
    body = bar.close - bar.open
    if body != 0.0:
        return 1 if body > 0.0 else -1
    return 1 if bar.close >= bar.open else -1


def range_digest_path_pressures(
    bars: list[base.Bar],
    index: int,
    shock_direction: int,
    lookback: int,
    average_range: float,
) -> tuple[float, float]:
    continuation = 0.0
    reversal = 0.0
    start = max(1, index - lookback + 1)
    for offset in range(start, index + 1):
        move = shock_direction * (bars[offset].close - bars[offset - 1].close)
        if move >= 0.0:
            continuation += move / max(average_range, 1e-9)
        else:
            reversal += abs(move) / max(average_range, 1e-9)
    return continuation, reversal


def post_shock_range_shape(
    bars: list[base.Bar],
    index: int,
    shock_index: int,
    horizon: int,
) -> tuple[float, float]:
    post_start = min(index, shock_index + 1)
    post_values = [bar_range_value(bars[offset]) for offset in range(post_start, index + 1)]
    pre_start = max(0, shock_index - horizon + 1)
    pre_values = [bar_range_value(bars[offset]) for offset in range(pre_start, shock_index + 1)]
    post_mean = sum(post_values) / max(len(post_values), 1)
    pre_mean = sum(pre_values) / max(len(pre_values), 1)
    ratio = post_mean / max(pre_mean, 1e-9)
    return max(0.0, 1.0 - ratio), max(0.0, ratio - 1.0)


def recent_high_low_position(bars: list[base.Bar], index: int, lookback: int) -> float:
    start = max(0, index - lookback + 1)
    high = max(bars[offset].high for offset in range(start, index + 1))
    low = min(bars[offset].low for offset in range(start, index + 1))
    return (bars[index].close - low) / max(high - low, 1e-9)


def close_delta_over(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    anchor = max(0, index - lookback)
    return (bars[index].close - bars[anchor].close) / max(average_range, 1e-9)


def build_flow_convexity_release_context(
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
        current_range = bar_range_value(bar)
        shock_index = strongest_extreme_recency_index(bars, range_average, index, 24, average_range)
        shock_bar = bars[shock_index]
        shock_direction = bar_body_direction(shock_bar)
        age = max(index - shock_index, 0)
        return_from_shock = (bar.close - shock_bar.close) / max(average_range, 1e-9)
        return_3 = close_delta_over(bars, index, min(3, max(age, 1)), average_range)
        return_6 = close_delta_over(bars, index, min(6, max(age, 1)), average_range)
        continuation_6, reversal_6 = range_digest_path_pressures(bars, index, shock_direction, 6, average_range)
        compression_6, expansion_6 = post_shock_range_shape(bars, index, shock_index, 6)
        compression_12, expansion_12 = post_shock_range_shape(bars, index, shock_index, 12)
        day_width = max(day["day_high"] - day["day_low"], 1e-9)
        body = bar.close - bar.open
        body_abs = abs(body)
        upper_wick = max(bar.high - max(bar.open, bar.close), 0.0)
        lower_wick = max(min(bar.open, bar.close) - bar.low, 0.0)
        extreme_recency_12 = extreme_recency_ratio_at(bars, index, 12, average_range)
        contexts[index] = {
            "average_range": average_range,
            "current_range": current_range,
            "shock_index": float(shock_index),
            "shock_age": float(age),
            "shock_direction": float(shock_direction),
            "extreme_recency_6": extreme_recency_ratio_at(bars, index, 6, average_range),
            "extreme_recency_12": extreme_recency_12,
            "extreme_recency_24": extreme_recency_ratio_at(bars, index, 24, average_range),
            "extreme_recency_48": extreme_recency_ratio_at(bars, index, 48, average_range),
            "close_in_shock_efficiency": body_abs / max(current_range, 1e-9),
            "shock_cluster_density_6": shock_cluster_density_at(bars, index, 6, average_range),
            "shock_cluster_density_12": shock_cluster_density_at(bars, index, 12, average_range),
            "shock_cluster_density_24": shock_cluster_density_at(bars, index, 24, average_range),
            "post_shock_compression_6": compression_6,
            "post_shock_compression_12": compression_12,
            "post_shock_expansion_6": expansion_6,
            "post_shock_expansion_12": expansion_12,
            "post_shock_return_3": return_3,
            "post_shock_return_6": return_6,
            "shock_follow_through_3": shock_direction * return_3,
            "shock_follow_through_6": shock_direction * return_6,
            "shock_exhaustion_3": max(0.0, -shock_direction * return_3),
            "shock_exhaustion_6": max(0.0, -shock_direction * return_6),
            "shock_reversal_pressure_6": reversal_6,
            "shock_continuation_pressure_6": continuation_6,
            "shock_range_position": recent_high_low_position(bars, index, 24),
            "day_range_depletion": min(day_width / max(average_range * 24.0, 1e-9), 4.0),
            "day_position": (bar.close - day["day_low"]) / day_width,
            "shock_to_day_range_ratio": current_range / day_width,
            "range_acceleration_3_12": range_mean_value(bars, index, 3) / max(range_mean_value(bars, index, 12), 1e-9) - 1.0,
            "range_acceleration_6_24": range_mean_value(bars, index, 6) / max(range_mean_value(bars, index, 24), 1e-9) - 1.0,
            "body_to_shock_range": body_abs / max(current_range, 1e-9),
            "signed_body_to_shock_range": sign_value(body) * body_abs / max(current_range, 1e-9),
            "upper_wick_shock_pressure": upper_wick / max(current_range, 1e-9),
            "lower_wick_shock_pressure": lower_wick / max(current_range, 1e-9),
            "shock_churn_ratio_6": path_churn_ratio(bars, index, 6),
            "shock_churn_ratio_12": path_churn_ratio(bars, index, 12),
            "range_volatility_of_volatility_12": range_std_ratio(bars, index, 12),
            "range_volatility_of_volatility_24": range_std_ratio(bars, index, 24),
            "session_progress": bounded(day["bars_since_day_open"] / 288.0, 0.0, 1.0),
            "spread_over_range": bar.spread_points / max(average_range, 1e-9),
            "spread_shock_stress_12": (bar.spread_points / max(average_range, 1e-9))
            * (1.0 + extreme_recency_12 + shock_cluster_density_at(bars, index, 12, average_range)),
            "path_efficiency_12": directional_efficiency(bars, index, shock_direction, 12),
            "path_churn_ratio_12": path_churn_ratio(bars, index, 12),
            "normalized_close_return_3": close_delta_over(bars, index, 3, average_range),
            "shock_regime_contrast_12_48": extreme_recency_12
            / max(extreme_recency_ratio_at(bars, index, 48, average_range), 1e-9)
            - 1.0,
            "return_from_shock": return_from_shock,
        }
    return contexts


def intraday_flow_convexity_release_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    day_context: list[dict[str, float] | None],
    extreme_recency_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> list[float] | None:
    average_range = range_average[index]
    day = day_context[index]
    context = extreme_recency_context[index]
    if average_range is None or average_range <= 0 or day is None or context is None or index < 120:
        return None
    shock_direction = int(context["shock_direction"])
    directional_day_depletion = day_range_position_directional(bars, day, index, direction)
    directional_wick_pressure = (
        context["lower_wick_shock_pressure"] - context["upper_wick_shock_pressure"]
        if direction > 0
        else context["upper_wick_shock_pressure"] - context["lower_wick_shock_pressure"]
    )
    features = [
        float(direction),
        directional_close_location(bars[index], direction),
        context["extreme_recency_6"],
        context["extreme_recency_12"],
        context["extreme_recency_24"],
        context["extreme_recency_48"],
        direction * shock_direction * context["close_in_shock_efficiency"],
        context["shock_cluster_density_6"],
        context["shock_cluster_density_12"],
        context["shock_cluster_density_24"],
        context["post_shock_compression_6"],
        context["post_shock_compression_12"],
        context["post_shock_expansion_6"],
        context["post_shock_expansion_12"],
        direction * context["post_shock_return_3"],
        direction * context["post_shock_return_6"],
        direction * shock_direction * context["shock_follow_through_3"],
        direction * shock_direction * context["shock_follow_through_6"],
        context["shock_exhaustion_3"] if direction == shock_direction else -context["shock_exhaustion_3"],
        context["shock_exhaustion_6"] if direction == shock_direction else -context["shock_exhaustion_6"],
        context["shock_reversal_pressure_6"] * (-direction * shock_direction),
        context["shock_continuation_pressure_6"] * (direction * shock_direction),
        context["shock_range_position"] if direction > 0 else 1.0 - context["shock_range_position"],
        directional_day_depletion,
        context["day_range_depletion"],
        context["shock_to_day_range_ratio"],
        context["range_acceleration_3_12"],
        context["range_acceleration_6_24"],
        context["body_to_shock_range"],
        direction * context["signed_body_to_shock_range"],
        context["upper_wick_shock_pressure"],
        context["lower_wick_shock_pressure"],
        directional_wick_pressure,
        context["shock_churn_ratio_6"],
        context["shock_churn_ratio_12"],
        context["range_volatility_of_volatility_12"],
        context["range_volatility_of_volatility_24"],
        context["session_progress"] * max(context["extreme_recency_12"], 0.0),
        context["spread_over_range"],
        context["spread_shock_stress_12"],
        directional_close_streak(bars, index, direction, 12),
        directional_efficiency(bars, index, direction, 12),
        context["path_churn_ratio_12"],
        direction * context["normalized_close_return_3"],
        context["shock_regime_contrast_12_48"],
    ]
    if len(features) != len(FEATURE_NAMES):
        raise RuntimeError(f"C0046 feature length mismatch: {len(features)} != {len(FEATURE_NAMES)}")
    if any(not math.isfinite(float(value)) for value in features):
        return None
    return [bounded(float(value), -8.0, 8.0) for value in features]


def intraday_flow_convexity_release_label(
    bars: list[base.Bar],
    range_average: list[float | None],
    extreme_recency_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> float | None:
    entry_index = index + 1
    exit_index = min(index + base.LABEL_HORIZON_BARS, len(bars) - 1)
    average_range = range_average[index]
    context = extreme_recency_context[index]
    if average_range is None or average_range <= 0 or context is None or entry_index >= exit_index:
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
    close_path = [entry] + [bar.close for bar in path]
    path_distance = sum(abs(close_path[offset] - close_path[offset - 1]) for offset in range(1, len(close_path)))
    path_efficiency = terminal / max(path_distance, 1e-9)
    target_speed = (len(path) - event_bar + 1) / len(path) if first_hit > 0.0 else 0.0
    stop_speed = (len(path) - event_bar + 1) / len(path) if first_hit < 0.0 else 0.0
    giveback = max(0.0, favorable - max(terminal_norm, 0.0))
    early_path = path[: min(3, len(path))]
    if direction > 0:
        early_followthrough = max(bar.high - entry for bar in early_path) / average_range
        early_adverse = max(entry - bar.low for bar in early_path) / average_range
    else:
        early_followthrough = max(entry - bar.low for bar in early_path) / average_range
        early_adverse = max(bar.high - entry for bar in early_path) / average_range
    future_ranges = [bar_range_value(bar) for bar in path]
    future_range_mean = sum(future_ranges) / max(len(future_ranges), 1)
    future_range_expansion = max(0.0, future_range_mean / max(average_range, 1e-9) - 1.0)
    future_range_compression = max(0.0, 1.0 - future_range_mean / max(average_range, 1e-9))
    shock_alignment = direction * int(context["shock_direction"])
    shock_follow_bonus = shock_alignment * max(context["shock_follow_through_6"], 0.0)
    shock_exhaustion_bonus = -shock_alignment * context["shock_exhaustion_6"]
    adverse_continuation_penalty = max(0.0, -shock_alignment * context["shock_continuation_pressure_6"])
    spread_norm = bars[entry_index].spread_points / average_range
    path_spread_peak = max(bar.spread_points for bar in path) / average_range
    return (
        0.86 * first_hit
        + 0.32 * target_speed
        - 0.48 * stop_speed
        - 0.58 * adverse_first
        + 0.30 * shock_follow_bonus
        + 0.24 * shock_exhaustion_bonus
        - 0.30 * adverse_continuation_penalty
        + 0.30 * early_followthrough
        - 0.36 * early_adverse
        + 0.30 * favorable
        - 0.64 * adverse
        + 0.40 * terminal_norm
        + 0.28 * path_efficiency
        + 0.16 * future_range_expansion
        - 0.10 * future_range_compression
        - 0.28 * giveback
        - 0.22 * future_path_churn(path, entry)
        - 1.08 * spread_norm
        - 0.20 * max(0.0, path_spread_peak - spread_norm)
        - 0.18 * max(0.0, context["spread_shock_stress_12"] - context["spread_over_range"])
    )


def safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    if abs(denominator) < 1e-9:
        return default
    return numerator / denominator


def recency_score(age: int, lookback: int) -> float:
    return bounded(1.0 - safe_ratio(float(age), float(max(lookback, 1))), 0.0, 1.0)


def rolling_extreme_stats(
    bars: list[base.Bar],
    index: int,
    lookback: int,
    average_range: float,
) -> dict[str, float | int]:
    start = max(0, index - lookback + 1)
    window = bars[start : index + 1]
    high_value = max(bar.high for bar in window)
    low_value = min(bar.low for bar in window)
    high_index = start + max(offset for offset, bar in enumerate(window) if bar.high >= high_value - 1e-9)
    low_index = start + max(offset for offset, bar in enumerate(window) if bar.low <= low_value + 1e-9)
    high_refresh_count = 0
    low_refresh_count = 0
    failed_high_count = 0
    failed_low_count = 0
    running_high = bars[start].high
    running_low = bars[start].low
    for cursor in range(start + 1, index + 1):
        bar = bars[cursor]
        if bar.high > running_high + 1e-9:
            high_refresh_count += 1
            if bar.close < running_high:
                failed_high_count += 1
            running_high = bar.high
        if bar.low < running_low - 1e-9:
            low_refresh_count += 1
            if bar.close > running_low:
                failed_low_count += 1
            running_low = bar.low
    width = max(high_value - low_value, 1e-9)
    high_age = index - high_index
    low_age = index - low_index
    high_recency = recency_score(high_age, lookback)
    low_recency = recency_score(low_age, lookback)
    denominator = float(max(len(window) - 1, 1))
    return {
        "high": high_value,
        "low": low_value,
        "high_index": high_index,
        "low_index": low_index,
        "high_age": high_age,
        "low_age": low_age,
        "high_recency": high_recency,
        "low_recency": low_recency,
        "high_refresh_density": high_refresh_count / denominator,
        "low_refresh_density": low_refresh_count / denominator,
        "refresh_density": (high_refresh_count + low_refresh_count) / denominator,
        "failed_high_density": failed_high_count / denominator,
        "failed_low_density": failed_low_count / denominator,
        "failed_refresh_density": (failed_high_count + failed_low_count) / denominator,
        "band_position": bounded((bars[index].close - low_value) / width, 0.0, 1.0),
        "channel_width": bounded(width / max(average_range, 1e-9), 0.0, 12.0),
    }


def session_extreme_stats(
    bars: list[base.Bar],
    index: int,
    average_range: float,
) -> dict[str, float | int]:
    day = bars[index].time.strftime("%Y-%m-%d")
    start = index
    while start > 0 and bars[start - 1].time.strftime("%Y-%m-%d") == day:
        start -= 1
    window = bars[start : index + 1]
    high_value = max(bar.high for bar in window)
    low_value = min(bar.low for bar in window)
    high_index = start + max(offset for offset, bar in enumerate(window) if bar.high >= high_value - 1e-9)
    low_index = start + max(offset for offset, bar in enumerate(window) if bar.low <= low_value + 1e-9)
    high_refresh_count = 0
    low_refresh_count = 0
    running_high = bars[start].high
    running_low = bars[start].low
    for cursor in range(start + 1, index + 1):
        bar = bars[cursor]
        if bar.high > running_high + 1e-9:
            high_refresh_count += 1
            running_high = bar.high
        if bar.low < running_low - 1e-9:
            low_refresh_count += 1
            running_low = bar.low
    width = max(high_value - low_value, 1e-9)
    denominator = float(max(len(window) - 1, 1))
    return {
        "high": high_value,
        "low": low_value,
        "high_index": high_index,
        "low_index": low_index,
        "high_recency": recency_score(index - high_index, max(len(window), 1)),
        "low_recency": recency_score(index - low_index, max(len(window), 1)),
        "refresh_density": (high_refresh_count + low_refresh_count) / denominator,
        "range_position": bounded((bars[index].close - low_value) / width, 0.0, 1.0),
        "channel_width": bounded(width / max(average_range, 1e-9), 0.0, 20.0),
    }


def post_extreme_motion(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> dict[str, float]:
    stats = rolling_extreme_stats(bars, index, lookback, average_range)
    extreme_index = int(stats["high_index"] if direction > 0 else stats["low_index"])
    extreme_price = float(stats["high"] if direction > 0 else stats["low"])
    current = bars[index].close
    drift = direction * (current - bars[extreme_index].close) / max(average_range, 1e-9)
    if direction > 0:
        retracement = max(0.0, extreme_price - current) / max(average_range, 1e-9)
    else:
        retracement = max(0.0, current - extreme_price) / max(average_range, 1e-9)
    closes = [bar.close for bar in bars[extreme_index : index + 1]]
    path_distance = sum(abs(closes[offset] - closes[offset - 1]) for offset in range(1, len(closes)))
    net_distance = abs(closes[-1] - closes[0]) if closes else 0.0
    efficiency = safe_ratio(net_distance, path_distance, 0.0)
    stall = (1.0 - bounded(efficiency, 0.0, 1.0)) * recency_score(index - extreme_index, lookback)
    return {
        "drift": bounded(drift, -8.0, 8.0),
        "retracement": bounded(retracement, 0.0, 8.0),
        "stall": bounded(stall, 0.0, 1.0),
        "efficiency": bounded(efficiency, 0.0, 1.0),
    }


def build_flow_convexity_release_context(
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
        if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0 or day is None or index < 120:
            continue
        stats_12 = rolling_extreme_stats(bars, index, 12, average_range)
        stats_24 = rolling_extreme_stats(bars, index, 24, average_range)
        stats_48 = rolling_extreme_stats(bars, index, 48, average_range)
        session_stats = session_extreme_stats(bars, index, average_range)
        width_24 = max(float(stats_24["high"]) - float(stats_24["low"]), 1e-9)
        close_to_high = 1.0 - bounded((float(stats_24["high"]) - bar.close) / width_24, 0.0, 1.0)
        close_to_low = 1.0 - bounded((bar.close - float(stats_24["low"])) / width_24, 0.0, 1.0)
        spread_over_range = bar.spread_points / max(average_range, 1e-9)
        channel_change = safe_ratio(float(stats_24["channel_width"]), float(stats_48["channel_width"]), 1.0) - 1.0
        contexts[index] = {
            "rolling_high_recency_12": float(stats_12["high_recency"]),
            "rolling_low_recency_12": float(stats_12["low_recency"]),
            "high_recency_24": float(stats_24["high_recency"]),
            "low_recency_24": float(stats_24["low_recency"]),
            "high_recency_48": float(stats_48["high_recency"]),
            "low_recency_48": float(stats_48["low_recency"]),
            "extreme_refresh_density_12": float(stats_12["refresh_density"]),
            "extreme_refresh_density_24": float(stats_24["refresh_density"]),
            "high_refresh_density_24": float(stats_24["high_refresh_density"]),
            "low_refresh_density_24": float(stats_24["low_refresh_density"]),
            "high_failed_refresh_12": float(stats_12["failed_high_density"]),
            "low_failed_refresh_12": float(stats_12["failed_low_density"]),
            "failed_extreme_refresh_12": float(stats_12["failed_refresh_density"]),
            "extreme_age_gradient_12_48": (
                (float(stats_12["high_recency"]) + float(stats_12["low_recency"]))
                - (float(stats_48["high_recency"]) + float(stats_48["low_recency"]))
            )
            / 2.0,
            "day_high_recency": float(session_stats["high_recency"]),
            "day_low_recency": float(session_stats["low_recency"]),
            "day_extreme_refresh_density": float(session_stats["refresh_density"]),
            "day_range_position": float(session_stats["range_position"]),
            "distance_to_day_high": (float(session_stats["high"]) - bar.close) / max(average_range, 1e-9),
            "distance_to_day_low": (bar.close - float(session_stats["low"])) / max(average_range, 1e-9),
            "rolling_extreme_band_position_24": float(stats_24["band_position"]),
            "extreme_channel_width_24": float(stats_24["channel_width"]),
            "extreme_channel_width_48": float(stats_48["channel_width"]),
            "channel_width_change_24_48": bounded(channel_change, -8.0, 8.0),
            "close_to_high_pressure": close_to_high * float(stats_24["high_recency"]),
            "close_to_low_pressure": close_to_low * float(stats_24["low_recency"]),
            "extreme_churn_ratio_12": path_churn_ratio(bars, index, 12),
            "extreme_path_efficiency_12": directional_efficiency(bars, index, 1, 12),
            "normalized_close_return_3": close_delta_over(bars, index, 3, average_range),
            "directional_close_streak_long_12": directional_close_streak(bars, index, 1, 12),
            "directional_close_streak_short_12": directional_close_streak(bars, index, -1, 12),
            "session_progress": bounded(day["bars_since_day_open"] / 288.0, 0.0, 1.0),
            "spread_over_range": spread_over_range,
            "spread_extreme_stress_24": spread_over_range
            * (
                1.0
                + max(float(stats_24["high_recency"]), float(stats_24["low_recency"]))
                + float(stats_24["refresh_density"])
                + max(0.0, channel_change)
            ),
            "extreme_regime_contrast_12_48": safe_ratio(float(stats_12["channel_width"]), float(stats_48["channel_width"]), 1.0) - 1.0,
        }
    return contexts


def intraday_flow_convexity_release_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    day_context: list[dict[str, float] | None],
    extreme_recency_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> list[float] | None:
    average_range = range_average[index]
    day = day_context[index]
    context = extreme_recency_context[index]
    if average_range is None or average_range <= 0 or day is None or context is None or index < 120:
        return None
    dir_rec_12 = context["rolling_high_recency_12"] if direction > 0 else context["rolling_low_recency_12"]
    dir_rec_24 = context["high_recency_24"] if direction > 0 else context["low_recency_24"]
    dir_rec_48 = context["high_recency_48"] if direction > 0 else context["low_recency_48"]
    opp_rec_24 = context["low_recency_24"] if direction > 0 else context["high_recency_24"]
    dir_refresh = context["high_refresh_density_24"] if direction > 0 else context["low_refresh_density_24"]
    opp_refresh = context["low_refresh_density_24"] if direction > 0 else context["high_refresh_density_24"]
    post_3 = post_extreme_motion(bars, index, direction, 3, average_range)
    post_6 = post_extreme_motion(bars, index, direction, 6, average_range)
    post_12 = post_extreme_motion(bars, index, direction, 12, average_range)
    day_extreme_recency = context["day_high_recency"] if direction > 0 else context["day_low_recency"]
    day_position = context["day_range_position"]
    directional_day_position = day_position if direction > 0 else 1.0 - day_position
    distance_to_directional_day_extreme = (
        context["distance_to_day_high"] if direction > 0 else context["distance_to_day_low"]
    )
    distance_from_opposite_day_extreme = (
        context["distance_to_day_low"] if direction > 0 else context["distance_to_day_high"]
    )
    band_position = context["rolling_extreme_band_position_24"]
    directional_band_position = band_position if direction > 0 else 1.0 - band_position
    close_to_fresh_extreme_pressure = (
        context["close_to_high_pressure"] if direction > 0 else context["close_to_low_pressure"]
    )
    opposite_extreme_pressure = context["close_to_low_pressure"] if direction > 0 else context["close_to_high_pressure"]
    directional_failed_refresh = context["high_failed_refresh_12"] if direction > 0 else context["low_failed_refresh_12"]
    directional_streak = (
        context["directional_close_streak_long_12"]
        if direction > 0
        else context["directional_close_streak_short_12"]
    )
    features = [
        float(direction),
        directional_close_location(bars[index], direction),
        context["rolling_high_recency_12"],
        context["rolling_low_recency_12"],
        dir_rec_12,
        dir_rec_24,
        dir_rec_48,
        opp_rec_24,
        context["extreme_refresh_density_12"],
        context["extreme_refresh_density_24"],
        dir_refresh,
        opp_refresh,
        post_3["drift"],
        post_6["drift"],
        direction * post_6["drift"],
        post_6["retracement"],
        post_12["retracement"],
        post_6["stall"],
        post_12["stall"],
        context["extreme_age_gradient_12_48"],
        context["day_high_recency"],
        context["day_low_recency"],
        day_extreme_recency,
        context["day_extreme_refresh_density"],
        day_position,
        directional_day_position,
        distance_to_directional_day_extreme,
        distance_from_opposite_day_extreme,
        band_position,
        directional_band_position,
        context["extreme_channel_width_24"],
        context["extreme_channel_width_48"],
        context["channel_width_change_24_48"],
        close_to_fresh_extreme_pressure,
        opposite_extreme_pressure,
        context["failed_extreme_refresh_12"],
        directional_failed_refresh,
        context["extreme_churn_ratio_12"],
        post_12["efficiency"],
        direction * context["normalized_close_return_3"],
        directional_streak,
        context["session_progress"],
        context["spread_over_range"],
        context["spread_extreme_stress_24"],
        context["extreme_regime_contrast_12_48"],
    ]
    if len(features) != len(FEATURE_NAMES):
        raise RuntimeError(f"C0046 feature length mismatch: {len(features)} != {len(FEATURE_NAMES)}")
    if any(not math.isfinite(float(value)) for value in features):
        return None
    return [bounded(float(value), -8.0, 8.0) for value in features]


def intraday_flow_convexity_release_label(
    bars: list[base.Bar],
    range_average: list[float | None],
    extreme_recency_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> float | None:
    entry_index = index + 1
    exit_index = min(index + base.LABEL_HORIZON_BARS, len(bars) - 1)
    average_range = range_average[index]
    context = extreme_recency_context[index]
    if average_range is None or average_range <= 0 or context is None or entry_index >= exit_index:
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
    close_path = [entry] + [bar.close for bar in path]
    path_distance = sum(abs(close_path[offset] - close_path[offset - 1]) for offset in range(1, len(close_path)))
    path_efficiency = terminal / max(path_distance, 1e-9)
    target_speed = (len(path) - event_bar + 1) / len(path) if first_hit > 0.0 else 0.0
    stop_speed = (len(path) - event_bar + 1) / len(path) if first_hit < 0.0 else 0.0
    giveback = max(0.0, favorable - max(terminal_norm, 0.0))
    early_path = path[: min(3, len(path))]
    if direction > 0:
        early_followthrough = max(bar.high - entry for bar in early_path) / average_range
        early_adverse = max(entry - bar.low for bar in early_path) / average_range
    else:
        early_followthrough = max(entry - bar.low for bar in early_path) / average_range
        early_adverse = max(bar.high - entry for bar in early_path) / average_range
    post_6 = post_extreme_motion(bars, index, direction, 6, average_range)
    post_12 = post_extreme_motion(bars, index, direction, 12, average_range)
    dir_recency = context["high_recency_24"] if direction > 0 else context["low_recency_24"]
    opp_pressure = context["close_to_low_pressure"] if direction > 0 else context["close_to_high_pressure"]
    fresh_extreme_continuation = max(0.0, dir_recency * post_6["drift"])
    fresh_extreme_failure = dir_recency * post_6["retracement"]
    spread_norm = bars[entry_index].spread_points / average_range
    path_spread_peak = max(bar.spread_points for bar in path) / average_range
    return (
        0.86 * first_hit
        + 0.32 * target_speed
        - 0.48 * stop_speed
        - 0.58 * adverse_first
        + 0.22 * fresh_extreme_continuation
        + 0.18 * fresh_extreme_failure
        - 0.22 * opp_pressure
        + 0.30 * early_followthrough
        - 0.36 * early_adverse
        + 0.30 * favorable
        - 0.64 * adverse
        + 0.40 * terminal_norm
        + 0.28 * path_efficiency
        + 0.14 * post_12["efficiency"]
        - 0.24 * post_12["stall"]
        - 0.28 * giveback
        - 0.22 * future_path_churn(path, entry)
        - 1.08 * spread_norm
        - 0.20 * max(0.0, path_spread_peak - spread_norm)
        - 0.18 * max(0.0, context["spread_extreme_stress_24"] - context["spread_over_range"])
    )


def _c0046_final_flow_context(
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
        if (
            index < 120
            or average_range is None
            or average_range <= 0
            or short_average_range is None
            or short_average_range <= 0
            or day is None
        ):
            continue
        day_range = max(day["day_high"] - day["day_low"], 1e-9)
        contexts[index] = {
            "ret_1": close_return_atr(bars, index, 1, average_range),
            "ret_3": close_return_atr(bars, index, 3, average_range),
            "ret_6": close_return_atr(bars, index, 6, average_range),
            "ret_12": close_return_atr(bars, index, 12, average_range),
            "ret_24": close_return_atr(bars, index, 24, average_range),
            "prev_ret_3": close_return_atr(bars, index - 3, 3, average_range),
            "energy_6": flow_energy_atr(bars, index, 6, average_range),
            "energy_12": flow_energy_atr(bars, index, 12, average_range),
            "energy_24": flow_energy_atr(bars, index, 24, average_range),
            "range_expansion_6_24": short_average_range / max(average_range, 1e-9) - 1.0,
            "day_open": day["day_open"],
            "day_high": day["day_high"],
            "day_low": day["day_low"],
            "day_mid": day["day_low"] + 0.5 * day_range,
            "day_range": day_range,
            "session_progress": bounded(day["bars_since_day_open"] / 288.0, 0.0, 1.0),
            "spread_over_range": bar.spread_points / average_range,
        }
    return contexts


def _c0046_final_flow_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    day_context: list[dict[str, float] | None],
    flow_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> tuple[float, ...] | None:
    average_range = range_average[index]
    short_average_range = short_range_average[index]
    if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
        return None
    context = flow_context[index]
    if context is None:
        return None
    spread_over_range = context["spread_over_range"]
    if spread_over_range > 0.65:
        return None
    signed_flow_6 = direction * close_flow_sum_atr(bars, index, 6, average_range)
    signed_flow_12 = direction * close_flow_sum_atr(bars, index, 12, average_range)
    signed_flow_24 = direction * close_flow_sum_atr(bars, index, 24, average_range)
    pressure_build_12 = max(0.0, -signed_flow_12)
    pressure_build_24 = max(0.0, -signed_flow_24)
    opposing_pressure_12 = max(0.0, -direction * body_flow_sum_atr(bars, index, 12, average_range))
    release_1 = max(0.0, direction * context["ret_1"])
    release_3 = max(0.0, direction * context["ret_3"])
    release_6 = max(0.0, direction * context["ret_6"])
    acceleration_3_12 = direction * (context["ret_3"] - 0.25 * context["ret_12"])
    acceleration_6_24 = direction * (context["ret_6"] - 0.25 * context["ret_24"])
    acceleration_inflection = direction * (context["ret_3"] - context["prev_ret_3"])
    body_align_6 = direction * body_flow_sum_atr(bars, index, 6, average_range)
    body_align_12 = direction * body_flow_sum_atr(bars, index, 12, average_range)
    day_return = direction * (bars[index].close - context["day_open"]) / average_range
    if direction > 0:
        day_position = (bars[index].close - context["day_low"]) / context["day_range"]
    else:
        day_position = (context["day_high"] - bars[index].close) / context["day_range"]
    day_balance = direction * (bars[index].close - context["day_mid"]) / average_range
    energy_contraction = max(0.0, context["energy_24"] - context["energy_6"])
    energy_expansion = max(0.0, context["energy_6"] - context["energy_24"])
    pressure_release_alignment = (
        0.42 * release_3
        + 0.26 * body_align_6
        + 0.18 * max(0.0, pressure_build_12 - opposing_pressure_12)
        - 0.24 * opposing_pressure_12
    )
    convexity_energy_interaction = acceleration_3_12 * (0.55 + context["energy_6"] + 0.25 * context["energy_12"])
    features = (
        float(direction),
        direction * context["ret_1"],
        direction * context["ret_3"],
        direction * context["ret_6"],
        direction * context["ret_12"],
        direction * context["ret_24"],
        acceleration_3_12,
        acceleration_6_24,
        acceleration_inflection,
        signed_flow_6,
        signed_flow_12,
        signed_flow_24,
        context["energy_6"],
        context["energy_12"],
        context["energy_24"],
        energy_contraction,
        energy_expansion,
        pressure_build_12,
        pressure_build_24,
        opposing_pressure_12,
        release_1,
        release_3,
        release_6,
        body_align_6,
        body_align_12,
        body_close_agreement(bars, index, 12),
        favorable_wick_acceptance(bars, index, direction, 6, average_range),
        opposing_wick_rejection(bars, index, direction, 6, average_range),
        directional_path_efficiency(bars, index, direction, 12),
        flow_path_churn_ratio(bars, index, 12),
        day_return,
        day_balance,
        bounded(day_position, 0.0, 1.0),
        context["range_expansion_6_24"],
        context["session_progress"],
        spread_over_range,
        spread_over_range * (1.0 + context["energy_6"] + pressure_build_12 + release_3),
        pressure_release_alignment,
        convexity_energy_interaction,
    )
    if len(features) != len(FEATURE_NAMES):
        raise RuntimeError(f"C0046 feature length mismatch: {len(features)} != {len(FEATURE_NAMES)}")
    return tuple(float(value) for value in features)


def _c0046_final_flow_label(
    bars: list[base.Bar],
    range_average: list[float | None],
    flow_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> float | None:
    entry_index = index + 1
    exit_index = min(index + base.LABEL_HORIZON_BARS, len(bars) - 1)
    average_range = range_average[index]
    context = flow_context[index]
    if average_range is None or average_range <= 0 or context is None or entry_index >= exit_index:
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
    close_path = [entry] + [bar.close for bar in path]
    path_distance = sum(abs(close_path[offset] - close_path[offset - 1]) for offset in range(1, len(close_path)))
    path_efficiency = terminal / max(path_distance, 1e-9)
    target_speed = (len(path) - event_bar + 1) / len(path) if first_hit > 0.0 else 0.0
    stop_speed = (len(path) - event_bar + 1) / len(path) if first_hit < 0.0 else 0.0
    giveback = max(0.0, favorable - max(terminal_norm, 0.0))
    early_path = path[: min(3, len(path))]
    if direction > 0:
        early_followthrough = max(bar.high - entry for bar in early_path) / average_range
        early_adverse = max(entry - bar.low for bar in early_path) / average_range
    else:
        early_followthrough = max(entry - bar.low for bar in early_path) / average_range
        early_adverse = max(bar.high - entry for bar in early_path) / average_range
    future_acceptance = sum(
        max(-1.5, min(2.5, direction * (bar.close - entry) / average_range)) for bar in path
    ) / len(path)
    favorable_body_share = sum(1 for bar in path if direction * (bar.close - bar.open) > 0.0) / len(path)
    opposing_close_share = sum(1 for bar in path if direction * (bar.close - entry) < -0.22 * average_range) / len(path)
    pre_pressure = max(0.0, -direction * context["ret_12"])
    pre_release = max(0.0, direction * context["ret_3"])
    spread_norm = bars[entry_index].spread_points / average_range
    path_spread_peak = max(bar.spread_points for bar in path) / average_range
    return (
        0.86 * first_hit
        + 0.34 * target_speed
        - 0.48 * stop_speed
        - 0.56 * adverse_first
        + 0.24 * pre_pressure
        + 0.26 * pre_release
        + 0.34 * early_followthrough
        - 0.36 * early_adverse
        + 0.28 * favorable
        - 0.62 * adverse
        + 0.40 * terminal_norm
        + 0.32 * path_efficiency
        - 0.28 * giveback
        + 0.36 * future_acceptance
        + 0.20 * favorable_body_share
        - 0.30 * opposing_close_share
        - 0.22 * future_path_churn(path, entry)
        - 1.08 * spread_norm
        - 0.20 * max(0.0, path_spread_peak - spread_norm)
    )


build_flow_convexity_release_context = _c0046_final_flow_context
intraday_flow_convexity_release_features = _c0046_final_flow_features
intraday_flow_convexity_release_label = _c0046_final_flow_label
