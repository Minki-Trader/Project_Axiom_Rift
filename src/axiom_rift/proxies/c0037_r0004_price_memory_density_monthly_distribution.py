"""C0037 R0004 proxy evidence for price memory density monthly distribution."""

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


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0037_intraday_price_memory_density_discovery" / "runs" / "R0004"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0037_intraday_price_memory_density_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0037_r0004_proxy_trades.csv"
PRICE_MEMORY_DENSITY_MONTHLY_DISTRIBUTION_SUMMARY_PATH = (
    RUN_DIR / "artifacts" / "c0037_r0004_price_memory_density_monthly_distribution_summary.json"
)
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


FEATURE_NAMES = (
    "direction_bias",
    "directional_return_1_atr",
    "directional_return_3_atr",
    "directional_return_6_atr",
    "directional_return_12_atr",
    "close_density_24",
    "close_density_48",
    "close_density_96",
    "range_density_24",
    "range_density_48",
    "above_close_density_48",
    "below_close_density_48",
    "directional_density_gradient_48",
    "directional_sparse_lane_24",
    "directional_sparse_lane_48",
    "directional_sparse_lane_96",
    "opposite_sparse_lane_48",
    "density_compression_24_vs_96",
    "density_expansion_12_vs_48",
    "revisit_recency_48",
    "directional_revisit_risk_24",
    "failed_escape_pressure_12",
    "failed_escape_pressure_24",
    "accepted_escape_pressure_12",
    "accepted_escape_pressure_24",
    "close_cluster_width_24",
    "close_cluster_width_48",
    "body_range_alignment_6",
    "body_range_alignment_12",
    "wick_reentry_pressure_6",
    "path_efficiency_12",
    "churn_ratio_12",
    "day_density_balance_directional",
    "day_density_escape_distance",
    "day_close_density_current",
    "session_progress",
    "spread_over_range",
    "spread_density_stress_24",
)
MODEL_FAMILY = "fold_local_price_memory_density_monthly_distribution_stability_conditioner"
LABEL_SHAPE = "directional_price_memory_density_monthly_distribution_stability_quality"
POSITIVE_LABEL_THRESHOLD = 0.18
ADVERSE_LABEL_THRESHOLD = -0.36
FEATURE_WEIGHT_FLOOR = 0.25
FEATURE_WEIGHT_CEILING = 2.50
CONDITIONER_WEIGHT = 0.46
MONTH_PRIOR_WEIGHT = 0.30
PHASE_PRIOR_WEIGHT = 0.14
SELECTION_RULE = "top_fold_local_monthly_distribution_stability_scores_per_active_day"
SOURCE_ROBUSTNESS_AUDIT_PATH = (
    "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0003/kpi/candidate_robustness_audit.json"
)
CONDITIONER_FEATURE_NAMES = (
    "base_price_memory_density_score",
    "adverse_cost_pressure",
    "fragile_tail_pressure",
    "stable_escape_quality",
    "stress_resilience_margin",
    "density_balance_stability",
    "spread_churn_tail_pressure",
    "late_session_tail_pressure",
    "low_efficiency_tail_pressure",
    "cluster_revisit_pressure",
    "month_sin",
    "month_cos",
    "month_start_pressure",
    "month_end_pressure",
    "quarter_turn_pressure",
    "month_middle_stability",
    "monthly_distribution_risk_score",
)


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


@dataclass(frozen=True)
class RobustnessConditioner:
    fold_id: str
    base_model: LinearEdgeModel
    feature_mean: np.ndarray
    feature_std: np.ndarray
    feature_weights: np.ndarray
    robust_centroid: np.ndarray
    fragile_centroid: np.ndarray
    robust_label_threshold: float
    fragile_label_threshold: float
    robust_label_rate: float
    fragile_label_rate: float
    base_score_median: float
    month_quality_by_month: dict[int, float]
    phase_quality_by_phase: dict[str, float]
    month_loss_pressure_by_month: dict[int, float]
    train_candidate_count: int


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


def run_c0037_r0004_proxy(write: bool = True) -> dict[str, object]:
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
    price_context = build_price_memory_density_context(bars, range_average, short_range_average, day_context)
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
        base_model = fit_linear_edge_model(train_candidates, fold_id)
        conditioner = fit_robustness_conditioner(train_candidates, base_model, fold_id)
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
        scored_candidates = score_candidates(test_candidates, conditioner)
        selected = base.select_daily_candidates(scored_candidates)
        trades.extend(base.simulate_trades(bars, range_average, selected, split["test_oos"]))
        fold_models.append(conditioner_summary(conditioner))
        state_distributions[fold_id] = score_distribution(scored_candidates, selected, conditioner)
        candidates_by_fold[fold_id] = {
            "train_candidate_count": len(train_candidates),
            "test_candidate_count": len(test_candidates),
            "selected_candidate_count": len(selected),
            "eligible_candidate_count": sum(1 for candidate in scored_candidates if candidate.score is not None),
            "base_feature_count": len(FEATURE_NAMES),
            "conditioner_feature_count": len(CONDITIONER_FEATURE_NAMES),
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
            features = intraday_price_memory_density_features(
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
                intraday_price_memory_density_label(bars, range_average, price_context, index, direction)
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
                    state_key=f"{side}|intraday_price_memory_density_monthly_distribution",
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


def build_price_memory_density_context(
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
        close_density_12 = price_close_density(bars, index, 12, average_range)
        close_density_24 = price_close_density(bars, index, 24, average_range)
        close_density_48 = price_close_density(bars, index, 48, average_range)
        close_density_96 = price_close_density(bars, index, 96, average_range)
        range_density_24 = price_range_density(bars, index, 24, average_range)
        range_density_48 = price_range_density(bars, index, 48, average_range)
        up_lane_24 = directional_lane_density(bars, index, 1, 24, average_range)
        up_lane_48 = directional_lane_density(bars, index, 1, 48, average_range)
        up_lane_96 = directional_lane_density(bars, index, 1, 96, average_range)
        down_lane_24 = directional_lane_density(bars, index, -1, 24, average_range)
        down_lane_48 = directional_lane_density(bars, index, -1, 48, average_range)
        down_lane_96 = directional_lane_density(bars, index, -1, 96, average_range)
        contexts[index] = {
            "close_density_12": close_density_12,
            "close_density_24": close_density_24,
            "close_density_48": close_density_48,
            "close_density_96": close_density_96,
            "range_density_24": range_density_24,
            "range_density_48": range_density_48,
            "above_close_density_48": side_close_density(bars, index, 1, 48, average_range),
            "below_close_density_48": side_close_density(bars, index, -1, 48, average_range),
            "up_lane_density_24": up_lane_24,
            "up_lane_density_48": up_lane_48,
            "up_lane_density_96": up_lane_96,
            "down_lane_density_24": down_lane_24,
            "down_lane_density_48": down_lane_48,
            "down_lane_density_96": down_lane_96,
            "up_sparse_lane_24": sparse_lane_score(up_lane_24),
            "up_sparse_lane_48": sparse_lane_score(up_lane_48),
            "up_sparse_lane_96": sparse_lane_score(up_lane_96),
            "down_sparse_lane_24": sparse_lane_score(down_lane_24),
            "down_sparse_lane_48": sparse_lane_score(down_lane_48),
            "down_sparse_lane_96": sparse_lane_score(down_lane_96),
            "density_compression_24_vs_96": close_density_24 / max(close_density_96, 1e-9),
            "density_expansion_12_vs_48": close_density_12 / max(close_density_48, 1e-9),
            "revisit_recency_48": price_revisit_recency(bars, index, 48, average_range),
            "day_close_density_current": day_close_density_current(bars, day, index, average_range),
            "session_progress": bounded(day["bars_since_day_open"] / 288.0, 0.0, 1.0),
            "spread_over_range": bar.spread_points / average_range,
            "spread_density_stress_24": (bar.spread_points / average_range) * (1.0 + close_density_24 + range_density_24),
        }
    return contexts


def price_close_density(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    if index < lookback:
        return 0.0
    current = bars[index].close
    band = max(0.75 * average_range, 1e-9)
    total = 0.0
    for offset in range(index - lookback, index):
        distance = abs(bars[offset].close - current)
        total += max(0.0, 1.0 - distance / band)
    return total / lookback


def price_range_density(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    if index < lookback:
        return 0.0
    current = bars[index].close
    band = max(0.35 * average_range, 1e-9)
    total = 0.0
    for offset in range(index - lookback, index):
        bar = bars[offset]
        if bar.low - band <= current <= bar.high + band:
            distance = 0.0 if bar.low <= current <= bar.high else min(abs(current - bar.low), abs(current - bar.high))
            total += max(0.0, 1.0 - distance / band)
    return total / lookback


def side_close_density(bars: list[base.Bar], index: int, side: int, lookback: int, average_range: float) -> float:
    if index < lookback:
        return 0.0
    current = bars[index].close
    band = max(1.50 * average_range, 1e-9)
    total = 0.0
    for offset in range(index - lookback, index):
        distance = side * (bars[offset].close - current)
        if distance > 0.0:
            total += max(0.0, 1.0 - distance / band)
    return total / lookback


def directional_lane_density(
    bars: list[base.Bar],
    index: int,
    direction: int,
    lookback: int,
    average_range: float,
) -> float:
    if index < lookback:
        return 0.0
    current = bars[index].close
    span = max(base.TARGET_RANGE_MULTIPLE * average_range, 1e-9)
    lane_low = min(current, current + direction * span)
    lane_high = max(current, current + direction * span)
    midpoint = (lane_low + lane_high) * 0.5
    total = 0.0
    for offset in range(index - lookback, index):
        bar = bars[offset]
        overlap = max(0.0, min(bar.high, lane_high) - max(bar.low, lane_low)) / span
        close_weight = max(0.0, 1.0 - abs(bar.close - midpoint) / max(0.5 * span, 1e-9))
        total += 0.70 * bounded(overlap, 0.0, 1.0) + 0.30 * close_weight
    return total / lookback


def sparse_lane_score(lane_density: float) -> float:
    return 1.0 / (1.0 + 2.5 * max(0.0, lane_density))


def directional_sparse_from_context(context: dict[str, float], direction: int, lookback: int) -> float:
    prefix = "up" if direction > 0 else "down"
    return context[f"{prefix}_sparse_lane_{lookback}"]


def price_revisit_recency(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    current = bars[index].close
    band = max(0.35 * average_range, 1e-9)
    for age, offset in enumerate(range(index - 1, index - lookback - 1, -1), start=1):
        if offset < 0:
            break
        if abs(bars[offset].close - current) <= band:
            return 1.0 - (age - 1) / lookback
    return 0.0


def close_cluster_width(bars: list[base.Bar], index: int, lookback: int, average_range: float) -> float:
    if index < lookback:
        return 0.0
    closes = [bars[offset].close for offset in range(index - lookback, index)]
    center = sum(closes) / lookback
    variance = sum((value - center) ** 2 for value in closes) / lookback
    return math.sqrt(variance) / max(average_range, 1e-9)


def directional_revisit_risk(bars: list[base.Bar], index: int, direction: int, lookback: int, average_range: float) -> float:
    return price_revisit_recency(bars, index, lookback, average_range) * directional_lane_density(
        bars, index, direction, lookback, average_range
    )


def failed_escape_pressure(
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


def accepted_escape_pressure(
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


def wick_reentry_pressure(bars: list[base.Bar], index: int, direction: int, lookback: int, average_range: float) -> float:
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


def body_range_alignment(
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


def day_close_density_current(
    bars: list[base.Bar],
    day_context: dict[str, float],
    index: int,
    average_range: float,
) -> float:
    lookback = int(min(day_context["bars_since_day_open"], 96.0))
    if lookback <= 0:
        return 0.0
    return price_close_density(bars, index, lookback, average_range)


def day_density_balance_directional(
    bars: list[base.Bar],
    day_context: dict[str, float],
    index: int,
    direction: int,
    average_range: float,
) -> float:
    lookback = int(min(day_context["bars_since_day_open"], 96.0))
    if lookback <= 0:
        return 0.0
    above = side_close_density(bars, index, 1, lookback, average_range)
    below = side_close_density(bars, index, -1, lookback, average_range)
    return direction * (below - above)


def day_density_escape_distance(
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


def intraday_price_memory_density_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    day_context: list[dict[str, float] | None],
    price_context: list[dict[str, float] | None],
    index: int,
    direction: int,
) -> tuple[float, ...] | None:
    average_range = range_average[index]
    short_average_range = short_range_average[index]
    if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
        return None
    day = day_context[index]
    context = price_context[index]
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
        context["close_density_24"],
        context["close_density_48"],
        context["close_density_96"],
        context["range_density_24"],
        context["range_density_48"],
        context["above_close_density_48"],
        context["below_close_density_48"],
        direction * (context["below_close_density_48"] - context["above_close_density_48"]),
        directional_sparse_from_context(context, direction, 24),
        directional_sparse_from_context(context, direction, 48),
        directional_sparse_from_context(context, direction, 96),
        directional_sparse_from_context(context, -direction, 48),
        context["density_compression_24_vs_96"],
        context["density_expansion_12_vs_48"],
        context["revisit_recency_48"],
        directional_revisit_risk(bars, index, direction, 24, average_range),
        failed_escape_pressure(bars, index, direction, 12, average_range),
        failed_escape_pressure(bars, index, direction, 24, average_range),
        accepted_escape_pressure(bars, index, direction, 12, average_range),
        accepted_escape_pressure(bars, index, direction, 24, average_range),
        close_cluster_width(bars, index, 24, average_range),
        close_cluster_width(bars, index, 48, average_range),
        body_range_alignment(bars, index, direction, 6, average_range),
        body_range_alignment(bars, index, direction, 12, average_range),
        wick_reentry_pressure(bars, index, direction, 6, average_range),
        directional_efficiency(bars, index, direction, 12),
        path_churn_ratio(bars, index, 12),
        day_density_balance_directional(bars, day, index, direction, average_range),
        day_density_escape_distance(bars, day, index, direction, average_range),
        context["day_close_density_current"],
        context["session_progress"],
        spread_over_range,
        context["spread_density_stress_24"],
    )
    if len(features) != len(FEATURE_NAMES):
        raise RuntimeError(f"C0037 feature length mismatch: {len(features)} != {len(FEATURE_NAMES)}")
    return tuple(float(value) for value in features)


def intraday_price_memory_density_label(
    bars: list[base.Bar],
    range_average: list[float | None],
    price_context: list[dict[str, float] | None],
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
    future_sparse_escape = future_sparse_escape_acceptance(path, entry, direction, average_range)
    future_density_retention = future_price_memory_density_retention(price_context, entry_index, exit_index, direction)
    future_dense_revisit = future_dense_core_revisit(path, entry, average_range)
    future_adverse_density = future_adverse_side_density(path, entry, direction, average_range)
    future_churn_penalty = future_path_churn(path, entry)
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
        + 0.32 * future_sparse_escape
        + 0.22 * future_density_retention
        - 0.30 * future_dense_revisit
        - 0.24 * future_adverse_density
        - 0.22 * future_churn_penalty
        - 1.08 * spread_norm
        - 0.20 * spread_drift
    )


def future_price_memory_density_retention(
    price_context: list[dict[str, float] | None],
    entry_index: int,
    exit_index: int,
    direction: int,
) -> float:
    values: list[float] = []
    for offset in range(entry_index, exit_index + 1):
        context = price_context[offset]
        if context is None:
            continue
        sparse = directional_sparse_from_context(context, direction, 48)
        opposite_sparse = directional_sparse_from_context(context, -direction, 48)
        gradient = direction * (context["below_close_density_48"] - context["above_close_density_48"])
        values.append(
            0.34 * sparse
            - 0.20 * opposite_sparse
            + 0.24 * gradient
            - 0.18 * context["revisit_recency_48"]
            - 0.12 * context["spread_over_range"]
        )
    return sum(values) / max(len(values), 1)


def future_sparse_escape_acceptance(
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


def future_dense_core_revisit(path: list[base.Bar], entry: float, average_range: float) -> float:
    if not path:
        return 0.0
    band = max(0.35 * average_range, 1e-9)
    return sum(1 for bar in path if abs(bar.close - entry) <= band) / len(path)


def future_adverse_side_density(path: list[base.Bar], entry: float, direction: int, average_range: float) -> float:
    if not path:
        return 0.0
    threshold = 0.30 * average_range
    return sum(1 for bar in path if direction * (bar.close - entry) < -threshold) / len(path)


def close_location_signed(bar: base.Bar) -> float:
    bar_range = max(bar.high - bar.low, 1e-9)
    return 2.0 * ((bar.close - bar.low) / bar_range) - 1.0


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


def fit_robustness_conditioner(
    candidates: list[base.Candidate],
    base_model: LinearEdgeModel,
    fold_id: str,
) -> RobustnessConditioner:
    base_scored = score_linear_candidates(candidates, base_model)
    labeled = [candidate for candidate in base_scored if candidate.label is not None and candidate.score is not None]
    feature_count = len(CONDITIONER_FEATURE_NAMES)
    if not labeled:
        return RobustnessConditioner(
            fold_id=fold_id,
            base_model=base_model,
            feature_mean=np.zeros(feature_count),
            feature_std=np.ones(feature_count),
            feature_weights=np.ones(feature_count),
            robust_centroid=np.zeros(feature_count),
            fragile_centroid=np.zeros(feature_count),
            robust_label_threshold=0.0,
            fragile_label_threshold=0.0,
            robust_label_rate=0.0,
            fragile_label_rate=0.0,
            base_score_median=0.0,
            month_quality_by_month={month: 0.0 for month in range(1, 13)},
            phase_quality_by_phase={"early": 0.0, "middle": 0.0, "late": 0.0},
            month_loss_pressure_by_month={month: 0.0 for month in range(1, 13)},
            train_candidate_count=0,
        )

    matrix = np.array([conditioner_features(candidate) for candidate in labeled], dtype=float)
    labels = np.array([robustness_adjusted_label(candidate) for candidate in labeled], dtype=float)
    base_scores = np.array([float(candidate.score or 0.0) for candidate in labeled], dtype=float)
    feature_mean = matrix.mean(axis=0)
    feature_std = matrix.std(axis=0)
    feature_std = np.where(feature_std < 1e-9, 1.0, feature_std)
    scaled = (matrix - feature_mean) / feature_std
    robust_threshold = max(POSITIVE_LABEL_THRESHOLD, float(np.quantile(labels, 0.72)))
    fragile_threshold = min(ADVERSE_LABEL_THRESHOLD, float(np.quantile(labels, 0.28)))
    base_score_median = float(np.median(base_scores))
    robust_mask = (labels >= robust_threshold) & (base_scores >= base_score_median)
    fragile_mask = (labels <= fragile_threshold) & (base_scores < base_score_median)
    if not robust_mask.any():
        robust_mask = labels >= robust_threshold
    if not fragile_mask.any():
        fragile_mask = labels <= fragile_threshold
    if not robust_mask.any():
        robust_mask = labels >= float(np.quantile(labels, 0.80))
    if not fragile_mask.any():
        fragile_mask = labels <= float(np.quantile(labels, 0.20))
    robust_centroid = scaled[robust_mask].mean(axis=0) if robust_mask.any() else scaled.mean(axis=0)
    fragile_centroid = scaled[fragile_mask].mean(axis=0) if fragile_mask.any() else scaled.mean(axis=0)
    separation = np.abs(robust_centroid - fragile_centroid)
    feature_weights = np.clip(separation / max(float(separation.mean()), 1e-9), FEATURE_WEIGHT_FLOOR, 2.80)
    month_quality, phase_quality, month_loss_pressure = build_month_distribution_priors(labeled, labels)
    return RobustnessConditioner(
        fold_id=fold_id,
        base_model=base_model,
        feature_mean=feature_mean,
        feature_std=feature_std,
        feature_weights=feature_weights,
        robust_centroid=robust_centroid,
        fragile_centroid=fragile_centroid,
        robust_label_threshold=robust_threshold,
        fragile_label_threshold=fragile_threshold,
        robust_label_rate=float(robust_mask.mean()),
        fragile_label_rate=float(fragile_mask.mean()),
        base_score_median=base_score_median,
        month_quality_by_month=month_quality,
        phase_quality_by_phase=phase_quality,
        month_loss_pressure_by_month=month_loss_pressure,
        train_candidate_count=len(labeled),
    )


def robustness_adjusted_label(candidate: base.Candidate) -> float:
    label = float(candidate.label or 0.0)
    base_score = float(candidate.score or 0.0)
    values = monthly_distribution_values(candidate)
    return (
        label
        + 0.16 * base_score
        + 0.24 * values["stable_escape_quality"]
        + 0.14 * values["stress_resilience_margin"]
        + 0.12 * values["month_middle_stability"]
        + 0.07 * values["density_balance_stability"]
        - 0.62 * values["monthly_distribution_risk_score"]
        - 0.18 * values["adverse_cost_pressure"]
        - 0.14 * values["month_start_pressure"]
        - 0.16 * values["month_end_pressure"]
        - 0.10 * values["quarter_turn_pressure"]
    )


def conditioner_features(candidate: base.Candidate) -> tuple[float, ...]:
    values = monthly_distribution_values(candidate)
    return (
        values["base_score"],
        values["adverse_cost_pressure"],
        values["fragile_tail_pressure"],
        values["stable_escape_quality"],
        values["stress_resilience_margin"],
        values["density_balance_stability"],
        values["spread_churn_tail_pressure"],
        values["late_session_tail_pressure"],
        values["low_efficiency_tail_pressure"],
        values["cluster_revisit_pressure"],
        values["month_sin"],
        values["month_cos"],
        values["month_start_pressure"],
        values["month_end_pressure"],
        values["quarter_turn_pressure"],
        values["month_middle_stability"],
        values["monthly_distribution_risk_score"],
    )


def monthly_distribution_values(candidate: base.Candidate) -> dict[str, float]:
    base_score = float(candidate.score or 0.0)
    adverse_cost_pressure = feature_value(candidate, "spread_over_range") + feature_value(candidate, "spread_density_stress_24")
    fragile_revisit_pressure = (
        feature_value(candidate, "directional_revisit_risk_24")
        + feature_value(candidate, "failed_escape_pressure_24")
        + feature_value(candidate, "churn_ratio_12")
        + max(0.0, feature_value(candidate, "wick_reentry_pressure_6"))
    )
    sparse_lane_quality = (
        feature_value(candidate, "directional_sparse_lane_48")
        + 0.70 * feature_value(candidate, "directional_sparse_lane_96")
        - 0.40 * feature_value(candidate, "opposite_sparse_lane_48")
    )
    escape_acceptance_balance = (
        feature_value(candidate, "accepted_escape_pressure_24")
        - feature_value(candidate, "failed_escape_pressure_24")
        + 0.50
        * (feature_value(candidate, "accepted_escape_pressure_12") - feature_value(candidate, "failed_escape_pressure_12"))
    )
    spread_churn_stress = feature_value(candidate, "spread_density_stress_24") * (
        1.0 + feature_value(candidate, "churn_ratio_12")
    )
    density_balance_abs = abs(feature_value(candidate, "day_density_balance_directional"))
    cluster_revisit_pressure = feature_value(candidate, "close_cluster_width_48") + feature_value(candidate, "revisit_recency_48")
    low_efficiency_tail_pressure = max(0.0, -feature_value(candidate, "path_efficiency_12")) + 0.35 * feature_value(
        candidate, "churn_ratio_12"
    )
    late_session_tail_pressure = max(0.0, feature_value(candidate, "session_progress") - 0.72)
    month, day = month_day(candidate)
    month_angle = 2.0 * math.pi * (month - 1) / 12.0
    month_sin = math.sin(month_angle)
    month_cos = math.cos(month_angle)
    month_start_pressure = max(0.0, (6.0 - min(float(day), 6.0)) / 5.0) if day <= 6 else 0.0
    month_end_pressure = max(0.0, (float(day) - 24.0) / 7.0) if day >= 25 else 0.0
    month_middle_stability = 1.0 - max(month_start_pressure, month_end_pressure)
    quarter_turn_pressure = 1.0 if (month in {3, 6, 9, 12} and day >= 24) or (month in {1, 4, 7, 10} and day <= 6) else 0.0
    stable_escape_quality = (
        0.42 * sparse_lane_quality
        + 0.36 * escape_acceptance_balance
        + 0.14 * feature_value(candidate, "path_efficiency_12")
        + 0.08 * feature_value(candidate, "body_range_alignment_12")
    )
    fragile_tail_pressure = (
        0.36 * fragile_revisit_pressure
        + 0.22 * cluster_revisit_pressure
        + 0.18 * low_efficiency_tail_pressure
        + 0.14 * density_balance_abs
        + 0.10 * late_session_tail_pressure
    )
    spread_churn_tail_pressure = spread_churn_stress + 0.45 * adverse_cost_pressure
    tail_risk_score = (
        0.30 * adverse_cost_pressure
        + 0.26 * fragile_tail_pressure
        + 0.18 * spread_churn_tail_pressure
        + 0.14 * cluster_revisit_pressure
        + 0.08 * max(month_start_pressure, month_end_pressure)
        + 0.04 * late_session_tail_pressure
    )
    monthly_distribution_risk_score = (
        0.36 * tail_risk_score
        + 0.19 * month_start_pressure
        + 0.21 * month_end_pressure
        + 0.12 * quarter_turn_pressure
        + 0.08 * late_session_tail_pressure
        + 0.04 * low_efficiency_tail_pressure
    )
    stress_resilience_margin = stable_escape_quality - tail_risk_score
    density_balance_stability = 1.0 / (1.0 + density_balance_abs + feature_value(candidate, "close_cluster_width_48"))
    return {
        "base_score": base_score,
        "adverse_cost_pressure": adverse_cost_pressure,
        "fragile_tail_pressure": fragile_tail_pressure,
        "stable_escape_quality": stable_escape_quality,
        "stress_resilience_margin": stress_resilience_margin,
        "density_balance_stability": density_balance_stability,
        "spread_churn_tail_pressure": spread_churn_tail_pressure,
        "late_session_tail_pressure": late_session_tail_pressure,
        "low_efficiency_tail_pressure": low_efficiency_tail_pressure,
        "cluster_revisit_pressure": cluster_revisit_pressure,
        "month_sin": month_sin,
        "month_cos": month_cos,
        "month_start_pressure": month_start_pressure,
        "month_end_pressure": month_end_pressure,
        "quarter_turn_pressure": quarter_turn_pressure,
        "month_middle_stability": month_middle_stability,
        "monthly_distribution_risk_score": monthly_distribution_risk_score,
    }


def month_day(candidate: base.Candidate) -> tuple[int, int]:
    try:
        _, month_text, day_text = candidate.day.split("-")
        return int(month_text), int(day_text)
    except ValueError:
        return 1, 1


def month_phase(candidate: base.Candidate) -> str:
    _, day = month_day(candidate)
    if day <= 10:
        return "early"
    if day >= 21:
        return "late"
    return "middle"


def build_month_distribution_priors(
    candidates: list[base.Candidate],
    labels: np.ndarray,
) -> tuple[dict[int, float], dict[str, float], dict[int, float]]:
    global_mean = float(labels.mean()) if len(labels) else 0.0
    global_std = float(labels.std()) if len(labels) else 1.0
    global_std = max(global_std, 1e-9)
    month_values: dict[int, list[float]] = {month: [] for month in range(1, 13)}
    phase_values: dict[str, list[float]] = {"early": [], "middle": [], "late": []}
    for candidate, label in zip(candidates, labels):
        month, _ = month_day(candidate)
        phase = month_phase(candidate)
        month_values.setdefault(month, []).append(float(label))
        phase_values.setdefault(phase, []).append(float(label))

    month_quality: dict[int, float] = {}
    month_loss_pressure: dict[int, float] = {}
    for month in range(1, 13):
        values = month_values.get(month, [])
        month_quality[month] = shrunk_distribution_quality(values, global_mean, global_std)
        if values:
            loss_rate = sum(1 for value in values if value < 0.0) / len(values)
            month_loss_pressure[month] = base.rounded(min(1.0, max(0.0, loss_rate + max(0.0, -month_quality[month]) * 0.25)))
        else:
            month_loss_pressure[month] = 0.0

    phase_quality = {
        phase: shrunk_distribution_quality(values, global_mean, global_std)
        for phase, values in phase_values.items()
    }
    return month_quality, phase_quality, month_loss_pressure


def shrunk_distribution_quality(values: list[float], global_mean: float, global_std: float) -> float:
    if not values:
        return 0.0
    count = len(values)
    mean = sum(values) / count
    variance = sum((value - mean) ** 2 for value in values) / count
    std = math.sqrt(max(variance, 0.0))
    loss_rate = sum(1 for value in values if value < 0.0) / count
    raw = ((mean - global_mean) / global_std) - 0.25 * (std / global_std) - 0.18 * loss_rate
    shrink = count / (count + 220.0)
    return base.rounded(max(-1.25, min(1.25, raw * shrink)))


def feature_value(candidate: base.Candidate, name: str) -> float:
    return float(candidate.features[FEATURE_NAMES.index(name)])


def score_linear_candidates(candidates: list[base.Candidate], model: LinearEdgeModel) -> list[base.Candidate]:
    return [score_candidate(candidate, model) for candidate in candidates]


def score_candidates(candidates: list[base.Candidate], conditioner: RobustnessConditioner) -> list[base.Candidate]:
    base_scored = score_linear_candidates(candidates, conditioner.base_model)
    if not base_scored:
        return []
    matrix = np.array([conditioner_features(candidate) for candidate in base_scored], dtype=float)
    scaled = (matrix - conditioner.feature_mean) / conditioner.feature_std
    weighted = scaled * conditioner.feature_weights
    robust = conditioner.robust_centroid * conditioner.feature_weights
    fragile = conditioner.fragile_centroid * conditioner.feature_weights
    dist_robust = np.sqrt(((weighted - robust) ** 2).mean(axis=1))
    dist_fragile = np.sqrt(((weighted - fragile) ** 2).mean(axis=1))
    conditioned: list[base.Candidate] = []
    for index, candidate in enumerate(base_scored):
        values = monthly_distribution_values(candidate)
        base_score = float(candidate.score or 0.0)
        robustness_margin = float(dist_fragile[index] - dist_robust[index])
        month, _ = month_day(candidate)
        phase = month_phase(candidate)
        month_quality = conditioner.month_quality_by_month.get(month, 0.0)
        phase_quality = conditioner.phase_quality_by_phase.get(phase, 0.0)
        month_loss_pressure = conditioner.month_loss_pressure_by_month.get(month, 0.0)
        score = (
            0.42 * base_score
            + CONDITIONER_WEIGHT * robustness_margin
            + MONTH_PRIOR_WEIGHT * month_quality
            + PHASE_PRIOR_WEIGHT * phase_quality
            - 0.09 * values["adverse_cost_pressure"]
            - 0.10 * values["monthly_distribution_risk_score"]
            - 0.08 * month_loss_pressure
            + 0.06 * values["stress_resilience_margin"]
            + 0.06 * values["month_middle_stability"]
            + 0.06 * (conditioner.robust_label_rate - conditioner.fragile_label_rate)
        )
        if not math.isfinite(score):
            score = None  # type: ignore[assignment]
        conditioned.append(
            base.Candidate(
                fold_id=candidate.fold_id,
                index=candidate.index,
                direction=candidate.direction,
                day=candidate.day,
                state_key=candidate.state_key,
                features=candidate.features,
                label=candidate.label,
                score=score,
            )
        )
    return conditioned


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
        "model_family": "fold_local_intraday_price_memory_density_base_rank",
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
        "score_interpretation": "higher_score_means_base_fold_local_intraday_price_memory_density_rank",
    }


def conditioner_summary(conditioner: RobustnessConditioner) -> dict[str, object]:
    return {
        "fold_id": conditioner.fold_id,
        "model_family": MODEL_FAMILY,
        "base_model": linear_model_summary(conditioner.base_model),
        "base_feature_names": list(FEATURE_NAMES),
        "base_feature_count": len(FEATURE_NAMES),
        "conditioner_feature_names": list(CONDITIONER_FEATURE_NAMES),
        "conditioner_feature_count": len(CONDITIONER_FEATURE_NAMES),
        "conditioner_weight": CONDITIONER_WEIGHT,
        "train_candidate_count": conditioner.train_candidate_count,
        "robust_label_threshold": base.rounded(conditioner.robust_label_threshold),
        "fragile_label_threshold": base.rounded(conditioner.fragile_label_threshold),
        "robust_label_rate": base.rounded(conditioner.robust_label_rate),
        "fragile_label_rate": base.rounded(conditioner.fragile_label_rate),
        "base_score_median": base.rounded(conditioner.base_score_median),
        "month_prior_weight": MONTH_PRIOR_WEIGHT,
        "phase_prior_weight": PHASE_PRIOR_WEIGHT,
        "month_quality_by_month": {
            f"{month:02d}": base.rounded(value)
            for month, value in sorted(conditioner.month_quality_by_month.items())
        },
        "phase_quality_by_phase": {
            phase: base.rounded(value)
            for phase, value in sorted(conditioner.phase_quality_by_phase.items())
        },
        "month_loss_pressure_by_month": {
            f"{month:02d}": base.rounded(value)
            for month, value in sorted(conditioner.month_loss_pressure_by_month.items())
        },
        "feature_weights": [base.rounded(float(value)) for value in conditioner.feature_weights],
        "feature_mean": [base.rounded(float(value)) for value in conditioner.feature_mean],
        "feature_std": [base.rounded(float(value)) for value in conditioner.feature_std],
        "robust_centroid": [base.rounded(float(value)) for value in conditioner.robust_centroid],
        "fragile_centroid": [base.rounded(float(value)) for value in conditioner.fragile_centroid],
        "source_candidate_audit": SOURCE_ROBUSTNESS_AUDIT_PATH,
        "score_interpretation": "higher_score_means_closer_to_train_monthly_distribution_stable_state",
    }


def score_distribution(
    scored: list[base.Candidate],
    selected: list[base.Candidate],
    conditioner: RobustnessConditioner,
) -> dict[str, float | int | None]:
    scores = [candidate.score or 0.0 for candidate in scored if candidate.score is not None]
    selected_scores = [candidate.score or 0.0 for candidate in selected]
    eligible_hits = sum(1 for candidate in scored if candidate.score is not None)
    return {
        "candidate_count": len(scored),
        "eligible_candidate_count": eligible_hits,
        "eligible_candidate_rate": base.rounded(eligible_hits / len(scored)) if scored else None,
        "selected_count": len(selected),
        "train_candidate_count": conditioner.train_candidate_count,
        "robust_label_rate": base.rounded(conditioner.robust_label_rate),
        "fragile_label_rate": base.rounded(conditioner.fragile_label_rate),
        "base_score_median": base.rounded(conditioner.base_score_median),
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
    payload["campaign_id"] = "C0037"
    payload["work_unit_id"] = "C0037"
    payload["run_id"] = "R0004"
    payload["proxy_id"] = "PX-C0037-R0004"
    payload["proxy_engine"] = "axiom_rift.proxies.c0037_r0004_price_memory_density_monthly_distribution"
    payload["proxy_config_path"] = "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004/run_manifest.json"
    payload["split_policy"] = (
        "rolling_window_test_oos_only_with_train_is_price_memory_density_monthly_distribution_stability_conditioner_fit"
    )
    payload["proxy_artifact_paths"] = [
        "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004/kpi/proxy.json",
        "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004/artifacts/c0037_r0004_proxy_trades.csv",
        "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004/artifacts/c0037_r0004_price_memory_density_monthly_distribution_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["price_memory_density_monthly_distribution_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "model_family": MODEL_FAMILY,
            "base_feature_count": len(FEATURE_NAMES),
            "base_feature_names": list(FEATURE_NAMES),
            "conditioner_feature_count": len(CONDITIONER_FEATURE_NAMES),
            "conditioner_feature_names": list(CONDITIONER_FEATURE_NAMES),
            "conditioner_weight": CONDITIONER_WEIGHT,
            "month_prior_weight": MONTH_PRIOR_WEIGHT,
            "phase_prior_weight": PHASE_PRIOR_WEIGHT,
            "label_shape": LABEL_SHAPE,
            "positive_label_threshold": POSITIVE_LABEL_THRESHOLD,
            "adverse_label_threshold": ADVERSE_LABEL_THRESHOLD,
            "feature_weight_floor": FEATURE_WEIGHT_FLOOR,
            "feature_weight_ceiling": FEATURE_WEIGHT_CEILING,
            "source_candidate_audit": SOURCE_ROBUSTNESS_AUDIT_PATH,
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
            "next_action": "produce_c0037_r0004_mt5_logic_parity_evidence",
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
            "conditioner_feature_names": list(CONDITIONER_FEATURE_NAMES),
            "conditioner_feature_count": len(CONDITIONER_FEATURE_NAMES),
            "conditioner_weight": CONDITIONER_WEIGHT,
            "month_prior_weight": MONTH_PRIOR_WEIGHT,
            "phase_prior_weight": PHASE_PRIOR_WEIGHT,
            "source_candidate_audit": SOURCE_ROBUSTNESS_AUDIT_PATH,
            "positive_label_threshold": POSITIVE_LABEL_THRESHOLD,
            "adverse_label_threshold": ADVERSE_LABEL_THRESHOLD,
            "feature_weight_floor": FEATURE_WEIGHT_FLOOR,
            "feature_weight_ceiling": FEATURE_WEIGHT_CEILING,
            "score_interpretation": "higher_score_means_train_only_monthly_distribution_stability_conditioned_rank",
            "variant_boundary": (
                "train_only_price_memory_density_monthly_distribution_stability_conditioner_informed_by_"
                "c0037_r0003_monthly_loss_streak_aggregate_profitability_and_adverse_cost_audit_not_threshold_"
                "window_stop_target_hold_session_activity_spread_capital_monthly_filter_or_retry_nudge"
            ),
        }
    )
    return config


def write_proxy_evidence(payload: dict[str, object], trades: list[base.Trade]) -> None:
    RUN_DIR.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    RUN_DIR.joinpath("kpi").mkdir(parents=True, exist_ok=True)
    base.write_trade_artifact(trades, TRADE_ARTIFACT_PATH)
    write_price_memory_density_summary_artifact(payload, PRICE_MEMORY_DENSITY_MONTHLY_DISTRIBUTION_SUMMARY_PATH)
    write_text_local(PROXY_PATH, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    trade_hash = sha256_file_local(TRADE_ARTIFACT_PATH)
    summary_hash = sha256_file_local(PRICE_MEMORY_DENSITY_MONTHLY_DISTRIBUTION_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = sha256_file_local(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)
    update_decision_cursor_after_proxy(payload)


def write_price_memory_density_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_fold_local_price_memory_density_monthly_distribution_summary_v1",
        "template": False,
        "work_unit_id": "C0037",
        "campaign_id": "C0037",
        "run_id": "R0004",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "price_memory_density_monthly_distribution_profile": profiles["price_memory_density_monthly_distribution_profile"]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "price_memory_density_monthly_distribution_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-C0037-R0004-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-C0037-R0004-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004/artifacts/c0037_r0004_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0037-R0004-PRICE-MEMORY-DENSITY-SUMMARY",
                "price_memory_density_monthly_distribution_summary_artifact",
                "json",
                "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004/artifacts/c0037_r0004_price_memory_density_monthly_distribution_summary.json",
                summary_hash,
                ["campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0037_r0004_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0037_r0004_price_memory_density_monthly_distribution",
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
    evidence["proxy_trade_artifact"] = "artifacts/c0037_r0004_proxy_trades.csv"
    evidence["price_memory_density_monthly_distribution_summary"] = "artifacts/c0037_r0004_price_memory_density_monthly_distribution_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0037_r0004_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0037_r0004_proxy_trades.csv",
        "artifacts/c0037_r0004_price_memory_density_monthly_distribution_summary.json",
        "kpi/proxy.json",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["evidence_paths"] = evidence_paths
    data["deferred_with_reason"] = [
        {
            "field": "decision",
            "reason": "proxy evidence is recorded but MT5 and proxy-vs-MT5 evidence are still missing",
            "blocking_condition": "R0004 cannot close until mandatory MT5 logic parity, MT5 tick, execution divergence, and fold-isolated evidence are recorded",
            "revisit_when": "after C0037 R0004 MT5 evidence files contain measured results",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_campaign_status() -> None:
    data = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = "runs/R0004"
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["run_id"] = "R0004"
    next_candidate["direction"] = "active_c0037_r0004_mt5_logic_parity"
    next_candidate["reason"] = "R0004 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0037_r0004_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    data = yaml.safe_load(REENTRY_PATH.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = "campaigns/C0037_intraday_price_memory_density_discovery"
    data["project"]["active_run"] = "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004"
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = "campaigns/C0037_intraday_price_memory_density_discovery"
    completed = list(next_work.get("completed") or [])
    for item in (
        "open_c0037_intraday_price_memory_density_discovery",
        "open_c0037_r0004_price_memory_density_monthly_distribution_stability_run",
        "produce_c0037_r0004_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_c0037_r0004_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_campaign"] = "campaigns/C0037_intraday_price_memory_density_discovery"
    data["active_run"] = "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004"
    REENTRY_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0037_intraday_price_memory_density_discovery"
    data["active_run"] = "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004"
    data["latest_operation"] = {
        "id": "produce_c0037_r0004_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0037_r0004_mt5_logic_parity_evidence",
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


def update_decision_cursor_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(DECISION_CURSOR_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["updated_local_date"] = "2026-07-05"
    data["canonical_source"] = "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004/kpi/proxy.json"
    data["canonical_status"] = "proxy_recorded_pending_mt5"
    data["current_decision"] = "produce_c0037_r0004_mt5_logic_parity_evidence"
    data["active_campaign"] = "campaigns/C0037_intraday_price_memory_density_discovery"
    data["active_run"] = "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004"
    data["next_required_action"] = "produce_c0037_r0004_mt5_logic_parity_evidence"
    data["current_evidence_summary"] = {
        "source_campaign": "campaigns/C0037_intraday_price_memory_density_discovery",
        "current_task": "produce_c0037_r0004_mt5_logic_parity_evidence",
        "active_run": "campaigns/C0037_intraday_price_memory_density_discovery/runs/R0004",
        "active_run_status": "proxy_recorded_pending_mt5",
        "evidence_status": "proxy_recorded_pending_mt5",
        "campaign_family": "intraday_price_memory_density",
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0037_r0004_mt5_logic_parity_evidence",
        "note": "C0037 R0004 proxy evidence recorded; MT5 paired validation remains mandatory regardless of proxy result.",
        "source_campaign_manifest": "campaigns/C0037_intraday_price_memory_density_discovery/campaign.yaml",
    }
    data["claim_boundary_snapshot"] = {
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
    DECISION_CURSOR_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def replace_run_markers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: replace_run_markers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_run_markers(item) for item in value]
    if isinstance(value, str):
        replacements = {
            "C0004": "C0037",
            "c0004_R0004_fold_local_state_archetype": "c0037_r0004_price_memory_density_monthly_distribution",
            "c0004_R0004": "c0037_r0004",
            "fold_local_state_archetype_discovery": "intraday_price_memory_density_discovery",
            "fold_local_train_only_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "price_memory_density_monthly_distribution_summary",
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
