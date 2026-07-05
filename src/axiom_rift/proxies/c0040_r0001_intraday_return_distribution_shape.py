"""C0040 R0001 proxy evidence for intraday return distribution shape discovery."""

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


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0040_intraday_return_distribution_shape_discovery" / "runs" / "R0001"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0040_intraday_return_distribution_shape_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0040_r0001_proxy_trades.csv"
RETURN_DISTRIBUTION_SHAPE_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0040_r0001_return_distribution_shape_summary.json"
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
    "return_z_1_24",
    "return_z_3_24",
    "return_z_6_48",
    "signed_return_quantile_24",
    "signed_return_quantile_48",
    "positive_return_share_12",
    "positive_return_share_24",
    "positive_return_share_48",
    "negative_return_share_12",
    "negative_return_share_24",
    "negative_return_share_48",
    "directional_positive_minus_negative_24",
    "return_skew_12",
    "return_skew_24",
    "return_skew_48",
    "return_kurtosis_24",
    "tail_mass_24",
    "tail_mass_48",
    "two_sided_tail_balance_24",
    "direction_tail_alignment_24",
    "direction_tail_alignment_48",
    "outlier_cluster_count_24",
    "outlier_cluster_count_48",
    "sign_run_length_24",
    "directional_sign_run_pressure_24",
    "mean_reversion_pressure_12",
    "mean_reversion_pressure_24",
    "tail_decay_pressure_12",
    "tail_decay_pressure_24",
    "calm_to_tail_transition_24",
    "tail_to_calm_transition_24",
    "range_adjusted_return_rank_24",
    "body_return_agreement_12",
    "body_return_agreement_24",
    "path_efficiency_12",
    "churn_ratio_12",
    "day_return_distribution_position",
    "session_progress",
    "spread_over_range",
    "spread_tail_stress_24",
)
MODEL_FAMILY = "fold_local_intraday_return_distribution_shape_rank"
LABEL_SHAPE = "directional_intraday_return_distribution_shape_survival_quality"
POSITIVE_LABEL_THRESHOLD = 0.18
ADVERSE_LABEL_THRESHOLD = -0.36
FEATURE_WEIGHT_FLOOR = 0.25
FEATURE_WEIGHT_CEILING = 2.50
SELECTION_RULE = "top_fold_local_intraday_return_distribution_shape_scores_per_active_day"


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


def run_c0040_r0001_proxy(write: bool = True) -> dict[str, object]:
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
    price_context = build_return_distribution_shape_context(bars, range_average, short_range_average, day_context)
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
            features = intraday_return_distribution_shape_features(
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
                intraday_return_distribution_shape_label(bars, range_average, price_context, index, direction)
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
                    state_key=f"{side}|intraday_return_distribution_shape",
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


def build_return_distribution_shape_context(
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


def intraday_return_distribution_shape_features(
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
        raise RuntimeError(f"C0040 feature length mismatch: {len(features)} != {len(FEATURE_NAMES)}")
    return tuple(float(value) for value in features)


def intraday_return_distribution_shape_label(
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
    future_release = future_return_distribution_shape_retention(ribbon_context, entry_index, exit_index, direction)
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


def future_return_distribution_shape_retention(
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


def build_return_distribution_shape_context(
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


def intraday_return_distribution_shape_features(
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
        raise RuntimeError(f"C0040 feature length mismatch: {len(features)} != {len(FEATURE_NAMES)}")
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


def intraday_return_distribution_shape_label(
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


def build_return_distribution_shape_context(
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
        returns_12 = rolling_return_values(bars, range_average, index, 12)
        returns_24 = rolling_return_values(bars, range_average, index, 24)
        returns_48 = rolling_return_values(bars, range_average, index, 48)
        stats_12 = return_distribution_stats(returns_12)
        stats_24 = return_distribution_stats(returns_24)
        stats_48 = return_distribution_stats(returns_48)
        current_return = normalized_close_return(bars, range_average, index)
        return_3 = close_delta_atr(bars, index, 3, average_range)
        return_6 = close_delta_atr(bars, index, 6, average_range)
        spread_over_range = bar.spread_points / average_range
        session_progress = bounded(day["bars_since_day_open"] / 288.0, 0.0, 1.0)
        contexts[index] = {
            "average_range": average_range,
            "return_1": current_return,
            "return_3": return_3,
            "return_6": return_6,
            "return_12": close_delta_atr(bars, index, 12, average_range),
            "return_z_1_24": zscore(current_return, stats_24["mean"], stats_24["std"]),
            "return_z_3_24": zscore(return_3, stats_24["mean"] * 3.0, stats_24["std"] * math.sqrt(3.0)),
            "return_z_6_48": zscore(return_6, stats_48["mean"] * 6.0, stats_48["std"] * math.sqrt(6.0)),
            "quantile_24": quantile_position(returns_24, current_return),
            "quantile_48": quantile_position(returns_48, current_return),
            "positive_share_12": stats_12["positive_share"],
            "positive_share_24": stats_24["positive_share"],
            "positive_share_48": stats_48["positive_share"],
            "negative_share_12": stats_12["negative_share"],
            "negative_share_24": stats_24["negative_share"],
            "negative_share_48": stats_48["negative_share"],
            "skew_12": stats_12["skew"],
            "skew_24": stats_24["skew"],
            "skew_48": stats_48["skew"],
            "kurtosis_24": stats_24["kurtosis"],
            "tail_mass_24": stats_24["tail_mass"],
            "tail_mass_48": stats_48["tail_mass"],
            "tail_balance_24": stats_24["tail_balance"],
            "tail_balance_48": stats_48["tail_balance"],
            "outlier_cluster_24": outlier_cluster_count(returns_24),
            "outlier_cluster_48": outlier_cluster_count(returns_48),
            "sign_run_norm_24": sign_run_norm(returns_24),
            "tail_decay_12": tail_decay_signed(returns_12),
            "tail_decay_24": tail_decay_signed(returns_24),
            "calm_to_tail_24": calm_to_tail_transition(returns_24),
            "tail_to_calm_24": tail_to_calm_transition(returns_24),
            "range_adjusted_rank_24": abs(current_return) / max(mean_abs(returns_24), 1e-9),
            "day_return_position": (bar.close - day["day_open"]) / max(average_range, 1e-9),
            "session_progress": session_progress,
            "spread_over_range": spread_over_range,
            "spread_tail_stress_24": spread_over_range * (1.0 + stats_24["tail_mass"] + outlier_cluster_count(returns_24)),
        }
    return contexts


def intraday_return_distribution_shape_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    day_context: list[dict[str, float] | None],
    distribution_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> tuple[float, ...] | None:
    average_range = range_average[index]
    short_average_range = short_range_average[index]
    if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
        return None
    day = day_context[index]
    context = distribution_context[index]
    if day is None or context is None:
        return None
    spread_over_range = bars[index].spread_points / average_range
    if spread_over_range > 0.65:
        return None
    features = (
        float(direction),
        direction * context["return_1"],
        direction * context["return_3"],
        direction * context["return_6"],
        direction * context["return_12"],
        direction * context["return_z_1_24"],
        direction * context["return_z_3_24"],
        direction * context["return_z_6_48"],
        direction * context["quantile_24"],
        direction * context["quantile_48"],
        context["positive_share_12"],
        context["positive_share_24"],
        context["positive_share_48"],
        context["negative_share_12"],
        context["negative_share_24"],
        context["negative_share_48"],
        direction * (context["positive_share_24"] - context["negative_share_24"]),
        direction * context["skew_12"],
        direction * context["skew_24"],
        direction * context["skew_48"],
        context["kurtosis_24"],
        context["tail_mass_24"],
        context["tail_mass_48"],
        context["tail_balance_24"],
        direction * context["tail_balance_24"],
        direction * context["tail_balance_48"],
        context["outlier_cluster_24"],
        context["outlier_cluster_48"],
        context["sign_run_norm_24"],
        direction * context["sign_run_norm_24"],
        max(0.0, -direction * context["return_z_1_24"]),
        max(0.0, -direction * context["return_z_3_24"]),
        direction * context["tail_decay_12"],
        direction * context["tail_decay_24"],
        context["calm_to_tail_24"],
        context["tail_to_calm_24"],
        context["range_adjusted_rank_24"],
        body_return_agreement(bars, index, 12),
        body_return_agreement(bars, index, 24),
        directional_efficiency(bars, index, direction, 12),
        path_churn_ratio(bars, index, 12),
        direction * context["day_return_position"],
        context["session_progress"],
        spread_over_range,
        context["spread_tail_stress_24"],
    )
    if len(features) != len(FEATURE_NAMES):
        raise RuntimeError(f"C0040 feature length mismatch: {len(features)} != {len(FEATURE_NAMES)}")
    return tuple(float(value) for value in features)


def future_directional_return_share(
    path: list[base.Bar],
    entry: float,
    direction: int,
    average_range: float,
) -> float:
    closes = [entry] + [bar.close for bar in path]
    moves = [direction * (closes[offset] - closes[offset - 1]) / max(average_range, 1e-9) for offset in range(1, len(closes))]
    return sum(1 for move in moves if move > 0.12) / max(len(moves), 1)


def future_directional_tail_share(
    path: list[base.Bar],
    entry: float,
    direction: int,
    average_range: float,
) -> float:
    closes = [entry] + [bar.close for bar in path]
    moves = [direction * (closes[offset] - closes[offset - 1]) / max(average_range, 1e-9) for offset in range(1, len(closes))]
    return sum(1 for move in moves if move > 0.45) / max(len(moves), 1)


def intraday_return_distribution_shape_label(
    bars: list[base.Bar],
    range_average: list[float | None],
    distribution_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> float | None:
    entry_index = index + 1
    exit_index = min(index + base.LABEL_HORIZON_BARS, len(bars) - 1)
    average_range = range_average[index]
    context = distribution_context[index]
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
    future_followthrough = future_directional_return_share(path, entry, direction, average_range)
    future_tail_followthrough = future_directional_tail_share(path, entry, direction, average_range)
    future_adverse_tail = future_directional_tail_share(path, entry, -direction, average_range)
    current_alignment = (
        0.30 * direction * context["skew_24"]
        + 0.26 * direction * context["tail_balance_24"]
        + 0.18 * direction * context["sign_run_norm_24"]
    )
    shape_transition = 0.18 * context["calm_to_tail_24"] + 0.12 * context["tail_to_calm_24"]
    return (
        0.84 * first_hit
        + 0.34 * target_speed
        - 0.46 * stop_speed
        - 0.56 * adverse_first
        + current_alignment
        + shape_transition
        + 0.32 * early_followthrough
        - 0.34 * early_adverse
        + 0.28 * favorable
        - 0.62 * adverse
        + 0.38 * terminal_norm
        + 0.32 * path_efficiency
        + 0.24 * path_alignment
        - 0.30 * giveback
        + 0.34 * future_followthrough
        + 0.24 * future_tail_followthrough
        - 0.42 * future_adverse_tail
        - 0.20 * future_path_churn(path, entry)
        - 1.08 * spread_norm
        - 0.20 * max(0.0, path_spread_peak - spread_norm)
    )


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
        "score_interpretation": "higher_score_means_direct_fold_local_intraday_return_distribution_shape_rank",
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
    payload["campaign_id"] = "C0040"
    payload["work_unit_id"] = "C0040"
    payload["run_id"] = "R0001"
    payload["proxy_id"] = "PX-C0040-R0001"
    payload["proxy_engine"] = "axiom_rift.proxies.c0040_r0001_intraday_return_distribution_shape"
    payload["proxy_config_path"] = "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_intraday_return_distribution_shape_rank_fit"
    payload["claim_boundary"] = dict(CLAIM_BOUNDARY)
    payload["proxy_artifact_paths"] = [
        "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001/kpi/proxy.json",
        "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001/artifacts/c0040_r0001_proxy_trades.csv",
        "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001/artifacts/c0040_r0001_return_distribution_shape_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["intraday_return_distribution_shape_profile"] = {  # type: ignore[index]
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
            "next_action": "produce_c0040_r0001_mt5_logic_parity_evidence",
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
            "score_interpretation": "higher_score_means_direct_fold_local_intraday_return_distribution_shape_rank",
            "variant_boundary": (
                "intraday_return_distribution_shape_rank_not_effort_absorption_seasonal_residual_tail_risk_skew_entropy_"
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
    write_return_distribution_shape_summary_artifact(payload, RETURN_DISTRIBUTION_SHAPE_SUMMARY_PATH)
    write_text_local(PROXY_PATH, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    trade_hash = sha256_file_local(TRADE_ARTIFACT_PATH)
    summary_hash = sha256_file_local(RETURN_DISTRIBUTION_SHAPE_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = sha256_file_local(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)
    update_decision_cursor_after_proxy(payload)


def write_return_distribution_shape_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_fold_local_intraday_return_distribution_shape_summary_v1",
        "template": False,
        "work_unit_id": "C0040",
        "campaign_id": "C0040",
        "run_id": "R0001",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "intraday_return_distribution_shape_profile": profiles["intraday_return_distribution_shape_profile"]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "intraday_return_distribution_shape_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-C0040-R0001-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-C0040-R0001-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001/artifacts/c0040_r0001_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0040-R0001-RETURN-DISTRIBUTION-SHAPE-SUMMARY",
                "intraday_return_distribution_shape_summary_artifact",
                "json",
                "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001/artifacts/c0040_r0001_return_distribution_shape_summary.json",
                summary_hash,
                ["campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0040_r0001_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0040_r0001_intraday_return_distribution_shape",
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
    evidence["proxy_trade_artifact"] = "artifacts/c0040_r0001_proxy_trades.csv"
    evidence["intraday_return_distribution_shape_summary"] = "artifacts/c0040_r0001_return_distribution_shape_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0040_r0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0040_r0001_proxy_trades.csv",
        "artifacts/c0040_r0001_return_distribution_shape_summary.json",
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
            "revisit_when": "after C0040 R0001 MT5 evidence files contain measured results",
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
    next_candidate["direction"] = "active_c0040_r0001_mt5_logic_parity"
    next_candidate["reason"] = "R0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0040_r0001_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    data = yaml.safe_load(REENTRY_PATH.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = "campaigns/C0040_intraday_return_distribution_shape_discovery"
    data["project"]["active_run"] = "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001"
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = "campaigns/C0040_intraday_return_distribution_shape_discovery"
    completed = list(next_work.get("completed") or [])
    for item in (
        "open_c0040_intraday_return_distribution_shape_discovery",
        "open_c0040_r0001_fold_local_intraday_return_distribution_shape_rank_run",
        "produce_c0040_r0001_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_c0040_r0001_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_campaign"] = "campaigns/C0040_intraday_return_distribution_shape_discovery"
    data["active_run"] = "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001"
    REENTRY_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0040_intraday_return_distribution_shape_discovery"
    data["active_run"] = "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001"
    data["latest_operation"] = {
        "id": "produce_c0040_r0001_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0040_r0001_mt5_logic_parity_evidence",
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_decision_cursor_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(DECISION_CURSOR_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["updated_local_date"] = "2026-07-06"
    data["canonical_source"] = "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001/kpi/proxy.json"
    data["canonical_status"] = "proxy_recorded_pending_mt5"
    data["current_decision"] = "produce_c0040_r0001_mt5_logic_parity_evidence"
    data["active_campaign"] = "campaigns/C0040_intraday_return_distribution_shape_discovery"
    data["active_run"] = "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001"
    data["next_required_action"] = "produce_c0040_r0001_mt5_logic_parity_evidence"
    data["current_evidence_summary"] = {
        "source_campaign": "campaigns/C0040_intraday_return_distribution_shape_discovery",
        "current_task": "produce_c0040_r0001_mt5_logic_parity_evidence",
        "active_run": "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001",
        "active_run_status": "proxy_recorded_pending_mt5",
        "evidence_status": "proxy_recorded_pending_mt5",
        "campaign_family": "intraday_return_distribution_shape",
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0040_r0001_mt5_logic_parity_evidence",
        "note": "C0040 R0001 proxy evidence recorded; MT5 paired validation remains mandatory regardless of proxy result.",
        "source_campaign_manifest": "campaigns/C0040_intraday_return_distribution_shape_discovery/campaign.yaml",
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
            "C0004": "C0040",
            "c0004_r0001_fold_local_state_archetype": "c0040_r0001_intraday_return_distribution_shape",
            "c0004_r0001": "c0040_r0001",
            "fold_local_state_archetype_discovery": "intraday_return_distribution_shape_discovery",
            "fold_local_train_only_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "intraday_return_distribution_shape_summary",
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
