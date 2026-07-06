"""C0056 R0001 proxy evidence for intraday volume clock phase."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies.common import base


CAMPAIGN_ID = "C0056"
RUN_ID = "R0001"
WORK_UNIT_REL = "campaigns/C0056_intraday_volume_clock_phase_discovery"
RUN_REL = f"{WORK_UNIT_REL}/runs/{RUN_ID}"
RUN_DIR = PROJECT_ROOT / RUN_REL
CAMPAIGN_PATH = PROJECT_ROOT / WORK_UNIT_REL / "campaign.yaml"
SELECTED_PATH = PROJECT_ROOT / WORK_UNIT_REL / "selected.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0056_r0001_proxy_trades.csv"
SUMMARY_PATH = RUN_DIR / "artifacts" / "c0056_r0001_volume_clock_phase_summary.json"
RUN_MANIFEST_PATH = RUN_DIR / "run_manifest.json"
GATE_REPORT_PATH = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE_PATH = RUN_DIR / "artifact_lineage.json"
REENTRY_PATH = PROJECT_ROOT / "registries" / "reentry.yaml"
CLAIM_STATE_PATH = PROJECT_ROOT / "registries" / "claim_state.yaml"
DECISION_CURSOR_PATH = PROJECT_ROOT / "registries" / "decision_cursor.yaml"
DECISION_REGISTRY_PATH = PROJECT_ROOT / "registries" / "decision_registry.yaml"
BASE_FRAME = base.BASE_FRAME
ROLLING_WINDOWS = base.ROLLING_WINDOWS
SplitWindow = base.SplitWindow
Trade = base.Trade

FEATURE_NAMES = (
    "directional_volume_clock_drift",
    "volume_clock_intensity",
    "volume_clock_acceleration_6",
    "directional_price_per_volume_efficiency_12",
    "volume_climax_recency",
    "post_climax_compression",
    "directional_volume_clock_position",
    "directional_volume_reversal_pressure_6",
    "day_range_completion_ratio",
    "range_compression_12_vs_48",
    "volume_confirmation_on_clock_shift",
    "spread_stress_inverse",
)
MODEL_FAMILY = "fold_local_intraday_volume_clock_phase_rank"
LABEL_SHAPE = "target_first_quality_conditioned_on_volume_clock_phase_state"
SELECTION_RULE = "top_fold_local_volume_clock_phase_scores_per_active_day"
LOOKBACK_RANGE_BARS = base.LOOKBACK_RANGE_BARS
SHORT_RANGE_BARS = base.SHORT_RANGE_BARS
LABEL_HORIZON_BARS = base.LABEL_HORIZON_BARS
STOP_RANGE_MULTIPLE = base.STOP_RANGE_MULTIPLE
TARGET_RANGE_MULTIPLE = base.TARGET_RANGE_MULTIPLE
PRICE_DIGITS = base.PRICE_DIGITS
MIN_DAY_BARS = 36
VOLUME_CLOCK_LOOKBACK_BARS = 12
VOLUME_CLOCK_SHORT_LOOKBACK_BARS = 6
MIN_VOLUME_CLOCK_ACTIVITY = 0.18

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


@dataclass(frozen=True)
class LinearVolumeClockPhaseModel:
    fold_id: str
    feature_mean: tuple[float, ...]
    feature_std: tuple[float, ...]
    feature_weight: tuple[float, ...]
    train_candidate_count: int
    global_mean: float
    positive_label_rate: float
    clock_failure_rate: float


@dataclass(frozen=True)
class DailyContext:
    day_key: str
    day_start_index: int
    bars_so_far: int
    day_open: float
    high_so_far: float
    low_so_far: float
    volume_so_far: float
    opening_high: float
    opening_low: float
    prior_day_range: float | None
    prior_day_return: float | None
    prior_day_volume_per_bar: float | None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rounded(value: float | None) -> float | None:
    return base.rounded(value)


def sha256_file_local(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_c0056_r0001_proxy(write: bool = True) -> dict[str, object]:
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
    volumes = load_tick_volume_series(BASE_FRAME)
    if len(volumes) != len(bars):
        raise RuntimeError(f"tick volume length mismatch: bars={len(bars)} volumes={len(volumes)}")
    daily_contexts = build_daily_contexts(bars, volumes)
    windows = base.load_windows(ROLLING_WINDOWS)
    ranges = [bar.high - bar.low for bar in bars]
    range_average = base.previous_rolling_average(ranges, LOOKBACK_RANGE_BARS)
    short_range_average = base.previous_rolling_average(ranges, SHORT_RANGE_BARS)
    volume_average = base.previous_rolling_average(volumes, SHORT_RANGE_BARS)
    trades: list[base.Trade] = []
    fold_models: list[dict[str, object]] = []
    state_distributions: dict[str, dict[str, float | int | None]] = {}
    candidates_by_fold: dict[str, dict[str, int]] = {}
    for fold_id in sorted(fold_id for fold_id, split in windows.items() if {"train_is", "test_oos"} <= set(split)):
        split = windows[fold_id]
        train_candidates = build_candidates(
            bars,
            volumes,
            daily_contexts,
            range_average,
            short_range_average,
            volume_average,
            split["train_is"],
            fold_id,
            include_labels=True,
        )
        model = fit_linear_volume_clock_phase_model(train_candidates, fold_id)
        test_candidates = build_candidates(
            bars,
            volumes,
            daily_contexts,
            range_average,
            short_range_average,
            volume_average,
            split["test_oos"],
            fold_id,
            include_labels=False,
        )
        scored_candidates = [score_candidate(candidate, model) for candidate in test_candidates]
        selected = base.select_daily_candidates(scored_candidates)
        trades.extend(base.simulate_trades(bars, range_average, selected, split["test_oos"]))
        fold_models.append(linear_volume_clock_phase_model_summary(model))
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


def load_tick_volume_series(path: Path) -> list[float]:
    volumes: list[float] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            timestamp = datetime.strptime(row["time"], base.TIME_FORMAT)
            if timestamp < base.MODELING_START:
                continue
            volumes.append(float(row.get("tick_volume") or 0.0))
    return volumes


def build_daily_contexts(bars: list[base.Bar], volumes: list[float]) -> list[DailyContext]:
    indices_by_day: dict[str, list[int]] = {}
    for index, bar in enumerate(bars):
        indices_by_day.setdefault(bar.time.strftime("%Y-%m-%d"), []).append(index)

    summaries: dict[str, dict[str, float | int]] = {}
    for day_key, indices in indices_by_day.items():
        first = indices[0]
        last = indices[-1]
        opening_indices = indices[:12]
        summaries[day_key] = {
            "open": bars[first].open,
            "close": bars[last].close,
            "high": max(bars[pos].high for pos in indices),
            "low": min(bars[pos].low for pos in indices),
            "volume": sum(volumes[pos] for pos in indices),
            "bar_count": len(indices),
            "opening_high": max(bars[pos].high for pos in opening_indices),
            "opening_low": min(bars[pos].low for pos in opening_indices),
        }

    prior_by_day: dict[str, dict[str, float | int] | None] = {}
    previous: dict[str, float | int] | None = None
    for day_key in sorted(indices_by_day):
        prior_by_day[day_key] = previous
        previous = summaries[day_key]

    contexts: list[DailyContext] = []
    current_day = ""
    day_start_index = 0
    high_so_far = 0.0
    low_so_far = 0.0
    volume_so_far = 0.0
    bars_so_far = 0
    for index, bar in enumerate(bars):
        day_key = bar.time.strftime("%Y-%m-%d")
        if day_key != current_day:
            current_day = day_key
            day_start_index = index
            high_so_far = bar.high
            low_so_far = bar.low
            volume_so_far = 0.0
            bars_so_far = 0
        high_so_far = max(high_so_far, bar.high)
        low_so_far = min(low_so_far, bar.low)
        volume_so_far += volumes[index]
        bars_so_far += 1
        summary = summaries[day_key]
        prior = prior_by_day[day_key]
        if prior is None:
            prior_range = None
            prior_return = None
            prior_volume_per_bar = None
        else:
            prior_range = float(prior["high"]) - float(prior["low"])
            prior_return = float(prior["close"]) - float(prior["open"])
            prior_volume_per_bar = float(prior["volume"]) / max(float(prior["bar_count"]), 1.0)
        contexts.append(
            DailyContext(
                day_key=day_key,
                day_start_index=day_start_index,
                bars_so_far=bars_so_far,
                day_open=float(summary["open"]),
                high_so_far=high_so_far,
                low_so_far=low_so_far,
                volume_so_far=volume_so_far,
                opening_high=float(summary["opening_high"]),
                opening_low=float(summary["opening_low"]),
                prior_day_range=prior_range,
                prior_day_return=prior_return,
                prior_day_volume_per_bar=prior_volume_per_bar,
            )
        )
    return contexts


def build_candidates(
    bars: list[base.Bar],
    volumes: list[float],
    daily_contexts: list[DailyContext],
    range_average: list[float | None],
    short_range_average: list[float | None],
    volume_average: list[float | None],
    window: base.SplitWindow,
    fold_id: str,
    include_labels: bool,
) -> list[base.Candidate]:
    start_index = max(
        base.first_index_at_or_after(bars, window.start),
        LOOKBACK_RANGE_BARS,
        SHORT_RANGE_BARS,
        72,
        LABEL_HORIZON_BARS,
    )
    end_index = min(base.last_index_at_or_before(bars, window.end), len(bars) - LABEL_HORIZON_BARS - 2)
    candidates: list[base.Candidate] = []
    for index in range(start_index, end_index + 1):
        if not base.in_core_session(bars[index].time):
            continue
        average_range = range_average[index]
        short_average_range = short_range_average[index]
        if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
            continue
        for direction in (1, -1):
            state_key, features = candidate_state_and_features(
                bars,
                volumes,
                daily_contexts,
                range_average,
                short_range_average,
                volume_average,
                index,
                direction,
            )
            if state_key is None or features is None:
                continue
            label = candidate_label(bars, range_average, index, direction) if include_labels else None
            candidates.append(
                base.Candidate(
                    fold_id=fold_id,
                    index=index,
                    direction=direction,
                    day=bars[index].time.strftime("%Y-%m-%d"),
                    state_key=state_key,
                    features=features,
                    label=label,
                )
            )
    return candidates


def candidate_state_and_features(
    bars: list[base.Bar],
    volumes: list[float],
    daily_contexts: list[DailyContext],
    range_average: list[float | None],
    short_range_average: list[float | None],
    volume_average: list[float | None],
    index: int,
    direction: int,
) -> tuple[str | None, tuple[float, ...] | None]:
    average_range = range_average[index]
    short_average_range = short_range_average[index]
    if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
        return None, None
    bar = bars[index]
    context = daily_contexts[index]
    if context.bars_so_far < MIN_DAY_BARS:
        return None, None
    clock = volume_clock_phase_metrics(bars, volumes, context, volume_average, index, direction, average_range)
    if clock["clock_event_count"] <= 0:
        return None, None
    compression = short_average_range / average_range
    volume_ratio = volume_stability(volumes, volume_average, index)
    spread_stress = bar.spread_points / average_range
    if volume_ratio is None:
        return None, None
    volume_confirmation = bounded(
        volume_ratio
        * (
            0.45 * clock["directional_volume_clock_drift"]
            + 0.35 * clock["directional_price_per_volume_efficiency_12"]
            + 0.20 * clock["volume_clock_acceleration_6"]
        ),
        -4.0,
        4.0,
    )
    features = (
        clock["directional_volume_clock_drift"],
        clock["volume_clock_intensity"],
        clock["volume_clock_acceleration_6"],
        clock["directional_price_per_volume_efficiency_12"],
        clock["volume_climax_recency"],
        clock["post_climax_compression"],
        clock["directional_volume_clock_position"],
        clock["directional_volume_reversal_pressure_6"],
        clock["day_range_completion_ratio"],
        compression,
        volume_confirmation,
        1.0 / (1.0 + max(spread_stress, 0.0)),
    )
    prefix = "long" if direction > 0 else "short"
    dimensions = (
        clock_drift_bucket(clock["directional_volume_clock_drift"]),
        clock_intensity_bucket(clock["volume_clock_intensity"]),
        clock_acceleration_bucket(clock["volume_clock_acceleration_6"]),
        clock_efficiency_bucket(clock["directional_price_per_volume_efficiency_12"]),
        climax_recency_bucket(clock["volume_climax_recency"]),
        post_climax_bucket(clock["post_climax_compression"]),
        edge_pressure_bucket(clock["directional_volume_clock_position"]),
        reversal_bucket(clock["directional_volume_reversal_pressure_6"]),
        compression_bucket(compression),
        participation_bucket(volume_ratio),
        spread_bucket(spread_stress),
        base.session_bucket(bar.time),
    )
    return prefix + "|" + "|".join(dimensions), features


def volume_clock_phase_metrics(
    bars: list[base.Bar],
    volumes: list[float],
    context: DailyContext,
    volume_average: list[float | None],
    index: int,
    direction: int,
    average_range: float,
) -> dict[str, float]:
    close = bars[index].close
    day_width = context.high_so_far - context.low_so_far
    if day_width <= 0:
        return {"clock_event_count": 0.0}
    prior_volume_per_bar = context.prior_day_volume_per_bar
    if prior_volume_per_bar is None or prior_volume_per_bar <= 0:
        return {"clock_event_count": 0.0}
    cumulative_rate = context.volume_so_far / max(context.bars_so_far, 1)
    volume_intensity = cumulative_rate / prior_volume_per_bar
    recent_volume = sum(volumes[max(0, index - VOLUME_CLOCK_SHORT_LOOKBACK_BARS + 1) : index + 1])
    expected_recent_volume = prior_volume_per_bar * VOLUME_CLOCK_SHORT_LOOKBACK_BARS
    recent_intensity = recent_volume / max(expected_recent_volume, 1e-9)
    clock_acceleration = recent_intensity - volume_intensity
    price_move_12 = direction * (close - bars[index - VOLUME_CLOCK_LOOKBACK_BARS].close) / average_range
    price_per_volume_efficiency = price_move_12 / max(recent_intensity, 0.20)
    day_drift = direction * (close - context.day_open) / average_range
    directional_drift = day_drift * min(volume_intensity, 4.0)
    climax_age, climax_strength = recent_volume_climax(volumes, volume_average, index, VOLUME_CLOCK_LOOKBACK_BARS)
    climax_recency = 0.0 if climax_age is None else (1.0 - min(climax_age / VOLUME_CLOCK_LOOKBACK_BARS, 1.0)) * climax_strength
    post_climax_compression = 1.0 / (1.0 + max(recent_intensity - volume_intensity, 0.0))
    directional_position = directional_session_position(close, context, direction) or 0.5
    range_completion = day_width / average_range
    reversal_pressure = -direction * (close - bars[index - VOLUME_CLOCK_SHORT_LOOKBACK_BARS].close) / average_range
    activity = max(abs(directional_drift), abs(clock_acceleration), climax_recency, abs(price_per_volume_efficiency))
    if activity < MIN_VOLUME_CLOCK_ACTIVITY:
        return {"clock_event_count": 0.0}
    return {
        "directional_volume_clock_drift": bounded(directional_drift, -4.0, 4.0),
        "volume_clock_intensity": bounded(volume_intensity, 0.0, 4.0),
        "volume_clock_acceleration_6": bounded(clock_acceleration, -4.0, 4.0),
        "directional_price_per_volume_efficiency_12": bounded(price_per_volume_efficiency, -4.0, 4.0),
        "volume_climax_recency": bounded(climax_recency, 0.0, 4.0),
        "post_climax_compression": bounded(post_climax_compression, 0.0, 1.0),
        "directional_volume_clock_position": bounded(directional_position, 0.0, 1.0),
        "directional_volume_reversal_pressure_6": bounded(reversal_pressure, -4.0, 4.0),
        "day_range_completion_ratio": bounded(range_completion, 0.0, 8.0),
        "clock_event_count": 1.0,
    }


def recent_volume_climax(
    volumes: list[float],
    volume_average: list[float | None],
    index: int,
    lookback: int,
) -> tuple[int | None, float]:
    start = max(0, index - lookback + 1)
    best_age: int | None = None
    best_strength = 0.0
    for position in range(start, index + 1):
        average_volume = volume_average[position]
        if average_volume is None or average_volume <= 0:
            continue
        strength = max(0.0, volumes[position] / average_volume - 1.0)
        if strength > best_strength:
            best_strength = strength
            best_age = index - position
    return best_age, min(best_strength, 4.0)


def historical_day_width(
    bars: list[base.Bar],
    context: DailyContext,
    index: int,
    lookback: int,
) -> float | None:
    end = index - lookback
    if end < context.day_start_index:
        return None
    window = bars[context.day_start_index : end + 1]
    if not window:
        return None
    return max(bar.high for bar in window) - min(bar.low for bar in window)


def price_sign(value: float) -> float:
    if value > 0:
        return 1.0
    if value < 0:
        return -1.0
    return 0.0


def bounded(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def directional_session_position(close: float, context: DailyContext, direction: int) -> float | None:
    width = context.high_so_far - context.low_so_far
    if width <= 0:
        return None
    long_position = (close - context.low_so_far) / width
    return long_position if direction > 0 else 1.0 - long_position


def bounded_session_progress(timestamp: datetime) -> float:
    span = base.CORE_SESSION_END_MINUTE - base.CORE_SESSION_START_MINUTE
    if span <= 0:
        return 0.0
    value = (base.minute_of_day(timestamp) - base.CORE_SESSION_START_MINUTE) / span
    return max(0.0, min(1.0, value))


def directional_close_location(bar: base.Bar, direction: int) -> float:
    width = max(bar.high - bar.low, 1e-9)
    long_location = (bar.close - bar.low) / width
    return long_location if direction > 0 else 1.0 - long_location


def adverse_wick_absorption(bar: base.Bar, direction: int) -> float:
    width = max(bar.high - bar.low, 1e-9)
    if direction > 0:
        return (min(bar.open, bar.close) - bar.low) / width
    return (bar.high - max(bar.open, bar.close)) / width


def favorable_wick_giveback(bar: base.Bar, direction: int) -> float:
    width = max(bar.high - bar.low, 1e-9)
    if direction > 0:
        return (bar.high - max(bar.open, bar.close)) / width
    return (min(bar.open, bar.close) - bar.low) / width


def directional_range_position(bars: list[base.Bar], index: int, direction: int, lookback: int) -> float | None:
    start = max(0, index - lookback + 1)
    window = bars[start : index + 1]
    high = max(bar.high for bar in window)
    low = min(bar.low for bar in window)
    width = high - low
    if width <= 0:
        return None
    long_position = (bars[index].close - low) / width
    return long_position if direction > 0 else 1.0 - long_position


def directional_path_efficiency(bars: list[base.Bar], index: int, direction: int, lookback: int) -> float | None:
    start = index - lookback
    if start < 0:
        return None
    net = direction * (bars[index].close - bars[start].close)
    travel = sum(abs(bars[pos].close - bars[pos - 1].close) for pos in range(start + 1, index + 1))
    if travel <= 0:
        return 0.0
    return net / travel


def volume_stability(volumes: list[float], volume_average: list[float | None], index: int) -> float | None:
    average_volume = volume_average[index]
    if average_volume is None or average_volume <= 0:
        return None
    current = volumes[index] / average_volume
    previous = volumes[index - 1] / average_volume
    return 1.0 - abs(current - previous)


def compression_bucket(value: float) -> str:
    if value < 0.78:
        return "compressed"
    if value < 1.15:
        return "normal"
    return "expanded"


def prior_range_bucket(value: float) -> str:
    if value < 0.75:
        return "prior_quiet"
    if value < 1.50:
        return "prior_normal"
    return "prior_hot"


def clock_drift_bucket(value: float) -> str:
    if value < -0.40:
        return "clock_drift_against"
    if value < 0.25:
        return "clock_drift_mixed"
    return "clock_drift_with"


def clock_intensity_bucket(value: float) -> str:
    if value < 0.75:
        return "slow_volume_clock"
    if value < 1.35:
        return "normal_volume_clock"
    return "fast_volume_clock"


def clock_acceleration_bucket(value: float) -> str:
    if value < -0.25:
        return "volume_clock_decelerating"
    if value < 0.35:
        return "volume_clock_stable"
    return "volume_clock_accelerating"


def edge_pressure_bucket(value: float) -> str:
    if value < 0.35:
        return "away_from_directional_edge"
    if value < 0.70:
        return "mid_directional_range"
    return "near_directional_edge"


def clock_efficiency_bucket(value: float) -> str:
    if value < -0.35:
        return "price_per_volume_against"
    if value < 0.35:
        return "price_per_volume_neutral"
    return "price_per_volume_with"


def climax_recency_bucket(value: float) -> str:
    if value <= 0.0:
        return "no_recent_volume_climax"
    if value < 0.75:
        return "minor_recent_volume_climax"
    return "strong_recent_volume_climax"


def post_climax_bucket(value: float) -> str:
    if value < 0.45:
        return "post_climax_expanding"
    if value < 0.75:
        return "post_climax_mixed"
    return "post_climax_compressed"


def reversal_bucket(value: float) -> str:
    if value < -0.35:
        return "volume_reversal_against"
    if value < 0.35:
        return "volume_reversal_neutral"
    return "volume_reversal_with"


def impulse_bucket(value: float) -> str:
    if value < -0.35:
        return "impulse_against"
    if value < 0.35:
        return "impulse_neutral"
    return "impulse_with"


def momentum_bucket(value: float) -> str:
    if value < -0.30:
        return "momentum_against"
    if value < 0.30:
        return "momentum_neutral"
    return "momentum_with"


def wick_bucket(value: float) -> str:
    if value < 0.25:
        return "thin_rejection_wick"
    if value < 0.55:
        return "mid_rejection_wick"
    return "strong_rejection_wick"


def participation_bucket(value: float) -> str:
    if value < 0.75:
        return "participation_faded"
    if value < 1.35:
        return "participation_normal"
    return "participation_amplified"


def body_bucket(value: float) -> str:
    if value < -0.25:
        return "body_against"
    if value < 0.25:
        return "body_neutral"
    return "body_with"


def location_bucket(value: float) -> str:
    if value < 0.35:
        return "weak_close"
    if value < 0.65:
        return "mid_close"
    return "strong_close"


def absorption_bucket(value: float) -> str:
    if value < 0.20:
        return "thin_absorption"
    if value < 0.45:
        return "mid_absorption"
    return "strong_absorption"


def spread_bucket(value: float) -> str:
    if value < 0.06:
        return "spread_low"
    if value < 0.12:
        return "spread_mid"
    return "spread_high"


def candidate_label(
    bars: list[base.Bar],
    range_average: list[float | None],
    index: int,
    direction: int,
) -> float | None:
    entry_index = index + 1
    exit_index = min(index + LABEL_HORIZON_BARS, len(bars) - 1)
    average_range = range_average[index]
    if average_range is None or average_range <= 0 or entry_index >= exit_index:
        return None
    entry = bars[entry_index].open
    stop_distance = STOP_RANGE_MULTIPLE * average_range
    target_distance = TARGET_RANGE_MULTIPLE * average_range
    stop_price = entry - direction * stop_distance
    target_price = entry + direction * target_distance
    path = bars[entry_index : exit_index + 1]
    first_hit = 0.0
    same_bar_conflict_count = 0
    for bar in path:
        if direction > 0:
            hit_stop = bar.low <= stop_price
            hit_target = bar.high >= target_price
        else:
            hit_stop = bar.high >= stop_price
            hit_target = bar.low <= target_price
        if hit_stop and hit_target:
            same_bar_conflict_count += 1
        if hit_stop:
            first_hit = -1.0
            break
        if hit_target:
            first_hit = 1.0
            break
    if direction > 0:
        mfe = max(bar.high - entry for bar in path)
        mae = max(entry - bar.low for bar in path)
        terminal = path[-1].close - entry
    else:
        mfe = max(entry - bar.low for bar in path)
        mae = max(bar.high - entry for bar in path)
        terminal = entry - path[-1].close
    recent_response = direction * (bars[index].close - bars[index - 3].close) / average_range
    clock_phase_reward = 0.20 if recent_response > 0.15 and terminal > 0 else 0.0
    failed_clock_shift_penalty = 0.20 if recent_response < -0.15 and mae > mfe else 0.0
    stall_penalty = 0.20 if mfe < 0.45 * average_range and terminal <= 0 else 0.0
    adverse_expansion_penalty = max(0.0, mae - mfe) / average_range * 0.35
    clock_path_quality = (0.35 * terminal + 0.35 * mfe - 0.70 * mae) / average_range
    same_bar_penalty = 0.25 * same_bar_conflict_count
    spread_penalty = bars[entry_index].spread_points / average_range
    return (
        first_hit
        + clock_path_quality
        + clock_phase_reward
        - failed_clock_shift_penalty
        - stall_penalty
        - adverse_expansion_penalty
        - same_bar_penalty
        - spread_penalty
    )


def fit_linear_volume_clock_phase_model(candidates: list[base.Candidate], fold_id: str) -> LinearVolumeClockPhaseModel:
    labeled = [candidate for candidate in candidates if candidate.label is not None]
    if not labeled:
        return LinearVolumeClockPhaseModel(fold_id, tuple(0.0 for _ in FEATURE_NAMES), tuple(1.0 for _ in FEATURE_NAMES), tuple(0.0 for _ in FEATURE_NAMES), 0, 0.0, 0.0, 0.0)
    labels = [float(candidate.label or 0.0) for candidate in labeled]
    global_mean = base.mean(labels) or 0.0
    label_std = stddev(labels, global_mean) or 1.0
    means: list[float] = []
    stds: list[float] = []
    weights: list[float] = []
    for offset in range(len(FEATURE_NAMES)):
        values = [candidate.features[offset] for candidate in labeled]
        mean_value = base.mean(values) or 0.0
        std_value = stddev(values, mean_value) or 1.0
        covariance = sum((value - mean_value) * (label - global_mean) for value, label in zip(values, labels)) / len(labels)
        correlation = covariance / (std_value * label_std)
        means.append(mean_value)
        stds.append(std_value)
        weights.append(max(-2.5, min(2.5, correlation)))
    positive_label_rate = sum(1 for label in labels if label > 0.0) / len(labels)
    clock_failure_rate = sum(1 for label in labels if label < -0.75) / len(labels)
    return LinearVolumeClockPhaseModel(
        fold_id=fold_id,
        feature_mean=tuple(means),
        feature_std=tuple(stds),
        feature_weight=tuple(weights),
        train_candidate_count=len(labeled),
        global_mean=global_mean,
        positive_label_rate=positive_label_rate,
        clock_failure_rate=clock_failure_rate,
    )


def stddev(values: list[float], mean_value: float) -> float | None:
    if not values:
        return None
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def score_candidate(candidate: base.Candidate, model: LinearVolumeClockPhaseModel) -> base.Candidate:
    score = 0.0
    for value, mean_value, std_value, weight in zip(
        candidate.features,
        model.feature_mean,
        model.feature_std,
        model.feature_weight,
    ):
        score += ((value - mean_value) / (std_value or 1.0)) * weight
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
    fold_ids = sorted(windows)
    required = base.required_kpis(trades)
    fold_summary = base.grouped_summary(trades, lambda trade: trade.fold_id)
    month_summary = base.grouped_summary(trades, lambda trade: trade.entry_time.strftime("%Y-%m"))
    direction = base.direction_summary(trades)
    active_days = sorted({trade.entry_time.strftime("%Y-%m-%d") for trade in trades})
    entries_per_active_day = len(trades) / len(active_days) if active_days else None
    return {
        "schema": "axiom_rift_proxy_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "synthesis_id_when_applicable": None,
        "run_id": RUN_ID,
        "proxy_id": "PX-C0056-R0001",
        "dataset_identity": "data/processed/datasets/us100_m5_base_frame.csv",
        "split_policy": "rolling_window_test_oos_only_with_train_is_volume_clock_phase_fit",
        "fold_ids": fold_ids,
        "proxy_engine": "axiom_rift.proxies.c0056_r0001_intraday_volume_clock_phase",
        "proxy_config_path": f"{RUN_REL}/run_manifest.json",
        "proxy_code_version_or_commit": "uncommitted_local_worktree_at_proxy_creation",
        "proxy_artifact_paths": [
            f"{RUN_REL}/kpi/proxy.json",
            f"{RUN_REL}/artifacts/c0056_r0001_proxy_trades.csv",
            f"{RUN_REL}/artifacts/c0056_r0001_volume_clock_phase_summary.json",
        ],
        "proxy_artifact_hashes": [],
        "proxy_config": proxy_config(),
        "proxy_summary": {
            "evaluation_surface": "rolling_window_test_oos_only",
            "trade_count": required["proxy_trade_count"],
            "signal_count": required["proxy_signal_count"],
            "active_day_count": len(active_days),
            "entries_per_active_day": rounded(entries_per_active_day),
            "entry_target_min": 5,
            "entry_target_max": 10,
            "gross_profit_points": rounded(sum(trade.pnl_points for trade in trades if trade.pnl_points > 0)),
            "gross_loss_points": rounded(sum(trade.pnl_points for trade in trades if trade.pnl_points < 0)),
            "net_pnl_points": rounded(sum(trade.pnl_points for trade in trades)),
            "long_trade_count": direction["long"]["trade_count"],
            "short_trade_count": direction["short"]["trade_count"],
            "target_exit_count": sum(1 for trade in trades if trade.exit_reason == "target"),
            "stop_exit_count": sum(1 for trade in trades if trade.exit_reason == "stop"),
            "max_hold_exit_count": sum(1 for trade in trades if trade.exit_reason == "max_hold"),
            "average_bars_in_trade": rounded(base.mean([trade.bars_held for trade in trades])),
        },
        "required_kpis": required,
        "conditional_profiles": {
            "volume_clock_phase_profile": {
                "applies": True,
                "fields": {
                    "model_family": MODEL_FAMILY,
                    "label_shape": LABEL_SHAPE,
                    "selection_rule": SELECTION_RULE,
                    "feature_count": len(FEATURE_NAMES),
                    "feature_names": list(FEATURE_NAMES),
                    "candidate_direction": "dual_direction_long_and_short_per_closed_bar",
                    "label_horizon_bars": LABEL_HORIZON_BARS,
                    "entry_count_per_active_day_target": "5_to_10",
                    "entries_per_active_day": rounded(entries_per_active_day),
                    "max_entries_per_active_day": base.MAX_ENTRIES_PER_ACTIVE_DAY,
                    "fold_models": fold_models,
                    "state_distributions": state_distributions,
                    "candidates_by_fold": candidates_by_fold,
                    "model_selected": False,
                    "feature_set_selected": False,
                    "label_selected": False,
                },
            },
            "trade_excursion_profile": {
                "applies": True,
                "fields": base.excursion_summary(trades),
            },
            "direction_profile": {
                "applies": True,
                "fields": direction,
            },
            "stability_profile": {
                "applies": True,
                "fields": {
                    "fold_summary": fold_summary,
                    "month_summary": month_summary,
                    "losing_month_count": sum(1 for row in month_summary if row["net_pnl_points"] < 0),
                    "worst_month_pnl_points": min((row["net_pnl_points"] for row in month_summary), default=None),
                },
            },
            "cost_execution_profile": {
                "applies": True,
                "fields": {
                    "commission_per_trade": 0,
                    "synthetic_commission_allowed": False,
                    "spread_source": "entry_bar_spread_column",
                    "spread_point_value": base.SPREAD_POINT_VALUE,
                    "round_trip_cost_model": "subtract_entry_spread_once",
                    "total_spread_cost_points": rounded(sum(trade.spread_points for trade in trades)),
                    "average_spread_cost_points": rounded(base.mean([trade.spread_points for trade in trades])),
                    "spread_stress_test_allowed": True,
                    "slippage_stress_test_allowed": True,
                },
            },
        },
        "deferred_with_reason": [
            {
                "field": "mt5_paired_validation",
                "requirement_class": "deferred_with_reason",
                "reason": "proxy evidence is recorded as a reference surface; MT5 logic parity, tick execution, divergence, and fold-isolated evidence remain mandatory",
                "blocking_condition": "produce C0056 R0001 MT5 paired validation evidence",
                "revisit_when": "produce_c0056_r0001_mt5_logic_parity_evidence",
                "claim_boundary": {"claim_authority": False},
            },
            {
                "field": "proxy_artifact_hashes",
                "requirement_class": "deferred_with_reason",
                "reason": "self-hash is recorded in artifact_lineage after proxy.json is written",
                "blocking_condition": "proxy.json content must be stable before hashing",
                "revisit_when": "before C0056 R0001 closeout",
                "claim_boundary": {"claim_authority": False},
            },
        ],
        "claim_boundary": CLAIM_BOUNDARY,
    }


def proxy_config() -> dict[str, object]:
    return {
        "bar_basis": "closed_m5",
        "entry_basis": "next_bar_open_after_scored_closed_bar",
        "evaluation_splits": "rolling_windows_test_oos",
        "training_splits": "rolling_windows_train_is",
        "candidate_direction": "dual_direction_long_and_short_per_closed_bar",
        "model_family": MODEL_FAMILY,
        "label_shape": LABEL_SHAPE,
        "lookback_range_bars": LOOKBACK_RANGE_BARS,
        "short_range_bars": SHORT_RANGE_BARS,
        "label_horizon_bars": LABEL_HORIZON_BARS,
        "stop_range_multiple": STOP_RANGE_MULTIPLE,
        "target_range_multiple": TARGET_RANGE_MULTIPLE,
        "max_hold_bars": base.MAX_HOLD_BARS,
        "max_entries_per_active_day": base.MAX_ENTRIES_PER_ACTIVE_DAY,
        "min_signal_spacing_bars": base.MIN_SIGNAL_SPACING_BARS,
        "same_bar_stop_target_policy": "stop_first_conservative",
        "gap_carried_entry_policy": "skip_when_next_bar_gap_exceeds_5_minutes",
        "gap_blocked_exit_policy": "skip_when_exit_bar_next_tick_gap_exceeds_5_minutes",
        "price_precision_digits": PRICE_DIGITS,
        "sizing_mode": "fixed_lot_discovery",
        "equity_percent_sizing": "deferred_until_candidate_quality",
    }


def linear_volume_clock_phase_model_summary(model: LinearVolumeClockPhaseModel) -> dict[str, object]:
    return {
        "fold_id": model.fold_id,
        "feature_names": list(FEATURE_NAMES),
        "feature_mean": [rounded(value) for value in model.feature_mean],
        "feature_std": [rounded(value) for value in model.feature_std],
        "feature_weight": [rounded(value) for value in model.feature_weight],
        "train_candidate_count": model.train_candidate_count,
        "global_mean": rounded(model.global_mean),
        "positive_label_rate": rounded(model.positive_label_rate),
        "clock_failure_rate": rounded(model.clock_failure_rate),
    }


def score_distribution(
    scored: list[base.Candidate],
    selected: list[base.Candidate],
    model: LinearVolumeClockPhaseModel,
) -> dict[str, float | int | None]:
    scores = [candidate.score or 0.0 for candidate in scored if candidate.score is not None]
    selected_scores = [candidate.score or 0.0 for candidate in selected]
    eligible_hits = sum(1 for candidate in scored if candidate.score is not None)
    return {
        "candidate_count": len(scored),
        "eligible_candidate_count": eligible_hits,
        "eligible_candidate_rate": rounded(eligible_hits / len(scored)) if scored else None,
        "selected_count": len(selected),
        "train_candidate_count": model.train_candidate_count,
        "score_p10": rounded(base.percentile(scores, 0.10)),
        "score_p50": rounded(base.percentile(scores, 0.50)),
        "score_p90": rounded(base.percentile(scores, 0.90)),
        "selected_score_min": rounded(min(selected_scores)) if selected_scores else None,
        "selected_score_max": rounded(max(selected_scores)) if selected_scores else None,
    }


def write_proxy_evidence(payload: dict[str, object], trades: list[base.Trade]) -> None:
    RUN_DIR.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    PROXY_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_trade_artifact(trades, TRADE_ARTIFACT_PATH)
    write_summary_artifact(payload, SUMMARY_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = sha256_file_local(TRADE_ARTIFACT_PATH)
    summary_hash = sha256_file_local(SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_selected_status()
    update_reentry_after_proxy(payload)
    update_claim_state_after_proxy(payload)
    update_decision_cursor_after_proxy(payload)
    append_decision_registry_after_proxy(payload)
    proxy_hash = sha256_file_local(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)


def write_trade_artifact(trades: list[base.Trade], path: Path) -> None:
    fields = [
        "fold_id",
        "signal_index",
        "entry_time",
        "exit_time",
        "direction",
        "score",
        "state_key",
        "entry_price",
        "exit_price",
        "stop_price",
        "target_price",
        "pnl_points",
        "bars_held",
        "exit_reason",
        "mfe_points",
        "mae_points",
        "spread_points",
    ]
    with path.open("w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for trade in trades:
            writer.writerow(
                {
                    "fold_id": trade.fold_id,
                    "signal_index": trade.signal_index,
                    "entry_time": trade.entry_time.strftime(base.TIME_FORMAT),
                    "exit_time": trade.exit_time.strftime(base.TIME_FORMAT),
                    "direction": trade.direction,
                    "score": rounded(trade.score),
                    "state_key": trade.state_key,
                    "entry_price": rounded(trade.entry_price),
                    "exit_price": rounded(trade.exit_price),
                    "stop_price": rounded(trade.stop_price),
                    "target_price": rounded(trade.target_price),
                    "pnl_points": rounded(trade.pnl_points),
                    "bars_held": trade.bars_held,
                    "exit_reason": trade.exit_reason,
                    "mfe_points": rounded(trade.mfe_points),
                    "mae_points": rounded(trade.mae_points),
                    "spread_points": rounded(trade.spread_points),
                }
            )


def write_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_volume_clock_phase_summary_v1",
        "template": False,
        "work_unit_id": CAMPAIGN_ID,
        "run_id": RUN_ID,
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "volume_clock_phase_profile": profiles["volume_clock_phase_profile"]["fields"],  # type: ignore[index]
        "claim_boundary": payload["claim_boundary"],
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_proxy_hashes(trade_hash: str, summary_hash: str) -> None:
    data = json.loads(PROXY_PATH.read_text(encoding="ascii"))
    data["proxy_artifact_hashes"] = [trade_hash, summary_hash]
    PROXY_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_run_manifest_status() -> None:
    data = json.loads(RUN_MANIFEST_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_ready"
    data["gate_status"] = "proxy_recorded_pending_mt5"
    data["mt5_probe_plan"]["next_required_action"] = "produce_c0056_r0001_mt5_logic_parity_evidence"
    evidence = data.setdefault("evidence_paths", {})
    evidence["proxy_trade_artifact"] = "artifacts/c0056_r0001_proxy_trades.csv"
    evidence["volume_clock_phase_summary"] = "artifacts/c0056_r0001_volume_clock_phase_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0056_r0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "run_manifest.json",
        "artifact_lineage.json",
        "artifacts/c0056_r0001_proxy_trades.csv",
        "artifacts/c0056_r0001_volume_clock_phase_summary.json",
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
            "revisit_when": "produce_c0056_r0001_mt5_logic_parity_evidence",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_campaign_status() -> None:
    data = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["direction"] = "active_r0001_mt5_logic_parity"
    next_candidate["reason"] = "R0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0056_r0001_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_selected_status() -> None:
    data = yaml.safe_load(SELECTED_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_not_selected"
    data["selected_reason"] = "C0056 R0001 proxy evidence is recorded as a reference surface only; MT5 paired validation and fold-isolated closeout remain mandatory before judgment."
    data["next_required_action"] = "produce_c0056_r0001_mt5_logic_parity_evidence"
    SELECTED_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_reentry_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(REENTRY_PATH.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = WORK_UNIT_REL
    data["project"]["active_run"] = RUN_REL
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = WORK_UNIT_REL
    completed = next_work.setdefault("completed", [])
    for item in (
        "produce_c0056_r0001_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_work["tasks"] = ["produce_c0056_r0001_mt5_logic_parity_evidence"]
    next_work["active_campaign"] = WORK_UNIT_REL
    next_work["active_run"] = RUN_REL
    next_work["run"] = RUN_REL
    data["active_campaign"] = WORK_UNIT_REL
    data["active_run"] = RUN_REL
    REENTRY_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    data["active_campaign"] = WORK_UNIT_REL
    data["active_synthesis"] = None
    data["active_run"] = RUN_REL
    required = payload["required_kpis"]  # type: ignore[index]
    summary = payload["proxy_summary"]  # type: ignore[index]
    data["latest_operation"] = {
        "id": "produce_c0056_r0001_proxy_evidence",
        "status": "completed",
        "recorded_at_source": f"{RUN_REL}/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "active_campaign": WORK_UNIT_REL,
        "active_synthesis": None,
        "active_run": RUN_REL,
        "negative_memory_recorded": False,
        "candidate_evidence_retained": False,
        "entries_per_active_day": summary.get("entries_per_active_day"),  # type: ignore[union-attr]
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points"),  # type: ignore[union-attr]
        "proxy_profit_factor": required.get("proxy_profit_factor"),  # type: ignore[union-attr]
        "proxy_trade_count": required.get("proxy_trade_count"),  # type: ignore[union-attr]
        "next_required_action": "produce_c0056_r0001_mt5_logic_parity_evidence",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_decision_cursor_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(DECISION_CURSOR_PATH.read_text(encoding="ascii"))
    data["canonical_source"] = f"{RUN_REL}/kpi/proxy.json"
    data["canonical_status"] = "proxy_recorded_pending_mt5"
    data["current_decision"] = "produce_c0056_r0001_mt5_logic_parity_evidence"
    data["active_campaign"] = WORK_UNIT_REL
    data["active_run"] = RUN_REL
    data["active_synthesis"] = None
    data["next_required_action"] = "produce_c0056_r0001_mt5_logic_parity_evidence"
    summary = data.setdefault("current_evidence_summary", {})
    summary.update(
        {
            "active_campaign": WORK_UNIT_REL,
            "active_run": RUN_REL,
            "active_run_status": "proxy_recorded_pending_mt5",
            "evidence_status": "proxy_recorded_pending_mt5",
            "current_task": "produce_c0056_r0001_mt5_logic_parity_evidence",
            "next_required_action": "produce_c0056_r0001_mt5_logic_parity_evidence",
            "proxy_trade_count": payload["required_kpis"]["proxy_trade_count"],  # type: ignore[index]
            "proxy_net_pnl_points": payload["required_kpis"].get("proxy_net_pnl_points"),  # type: ignore[index]
            "proxy_profit_factor": payload["required_kpis"]["proxy_profit_factor"],  # type: ignore[index]
            "entries_per_active_day": payload["proxy_summary"]["entries_per_active_day"],  # type: ignore[index]
            "note": "C0056 R0001 proxy evidence is recorded; MT5 paired validation remains mandatory and no selection or economics claim is created.",
        }
    )
    data["next_decision_basis"] = [
        {
            "path": f"{RUN_REL}/kpi/proxy.json",
            "role": "active_proxy_kpi",
            "summary": "C0056 R0001 proxy evidence recorded as reference surface only; MT5 logic parity is next.",
        },
        {
            "path": f"{RUN_REL}/run_manifest.json",
            "role": "active_run_manifest",
            "summary": "R0001 remains active and cannot close until mandatory MT5 paired and fold-isolated evidence exists.",
        },
    ]
    DECISION_CURSOR_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def append_decision_registry_after_proxy(payload: dict[str, object]) -> None:
    text = DECISION_REGISTRY_PATH.read_text(encoding="ascii")
    required = payload["required_kpis"]  # type: ignore[index]
    summary = payload["proxy_summary"]  # type: ignore[index]
    block = f"""
- decision_id: dec_20260706_produce_c0056_r0001_proxy_evidence
  created_local_date: '2026-07-06'
  status: active
  decision: produce_c0056_r0001_proxy_evidence
  refines:
  - dec_20260706_open_c0056_r0001_intraday_volume_clock_phase_rank_run
  - dec_20260701_mandatory_mt5_paired_run_validation
  rationale:
  - c0056_r0001_proxy_records_volume_clock_phase_reference_surface
  - proxy_trade_count_{required.get("proxy_trade_count")}
  - entries_per_active_day_{summary.get("entries_per_active_day")}
  - proxy_net_pnl_points_{required.get("proxy_net_pnl_points")}
  - proxy_profit_factor_{required.get("proxy_profit_factor")}
  - proxy_result_cannot_skip_mt5_logic_parity_tick_execution_divergence_or_fold_isolated_closeout_evidence
  - next_work_is_produce_c0056_r0001_mt5_logic_parity_evidence
  - no_selected_economics_runtime_materialization_onnx_promotion_or_live_claim_is_created
  claim_boundary:
    claim_authority: false
    selected: false
    label_selected: false
    feature_set_selected: false
    model_selected: false
    trade_logic_selected: false
    runtime_probe_completed: false
    economics_pass: false
    materialization_ready: false
    runtime_authority: false
    onnx_ready: false
    promotion_ready: false
    live_ready: false
"""
    if "dec_20260706_produce_c0056_r0001_proxy_evidence" not in text:
        DECISION_REGISTRY_PATH.write_text(text.rstrip() + block, encoding="ascii")


def update_artifact_lineage(proxy_hash: str, trade_hash: str, summary_hash: str) -> None:
    run_manifest_hash = sha256_file_local(RUN_MANIFEST_PATH)
    gate_hash = sha256_file_local(GATE_REPORT_PATH)
    data = json.loads(ARTIFACT_LINEAGE_PATH.read_text(encoding="ascii"))
    data["artifact_records"] = [
        {
            "artifact_id": "A-C0056-R0001-RUN-MANIFEST",
            "artifact_role": "run_manifest",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/run_manifest.json",
            "sha256": run_manifest_hash,
            "produced_by": "axiom_rift.proxies.c0056_r0001_intraday_volume_clock_phase",
            "source_inputs": [
                "registries/decision_cursor.yaml",
                "registries/claim_state.yaml",
                "contracts/goal_operation_policy.yaml",
            ],
            "linked_kpi_family": None,
            "mutable": True,
            "claim_authority": False,
        },
        {
            "artifact_id": "A-C0056-R0001-GATE-REPORT",
            "artifact_role": "gate_report",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/gate_report.json",
            "sha256": gate_hash,
            "produced_by": "axiom_rift.proxies.c0056_r0001_intraday_volume_clock_phase",
            "source_inputs": [
                f"{RUN_REL}/run_manifest.json",
                f"{RUN_REL}/kpi/proxy.json",
            ],
            "linked_kpi_family": None,
            "mutable": True,
            "claim_authority": False,
        },
        {
            "artifact_id": "A-C0056-R0001-PROXY-KPI",
            "artifact_role": "proxy_kpi",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/kpi/proxy.json",
            "sha256": proxy_hash,
            "produced_by": "axiom_rift.proxies.c0056_r0001_intraday_volume_clock_phase",
            "source_inputs": [
                "data/processed/datasets/us100_m5_base_frame.csv",
                "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                f"{RUN_REL}/run_manifest.json",
            ],
            "linked_kpi_family": "proxy",
            "mutable": False,
            "claim_authority": False,
        },
        {
            "artifact_id": "A-C0056-R0001-PROXY-TRADES",
            "artifact_role": "proxy_trade_artifact",
            "artifact_type": "csv",
            "repo_relative_path": f"{RUN_REL}/artifacts/c0056_r0001_proxy_trades.csv",
            "sha256": trade_hash,
            "produced_by": "axiom_rift.proxies.c0056_r0001_intraday_volume_clock_phase",
            "source_inputs": [
                "data/processed/datasets/us100_m5_base_frame.csv",
                "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                f"{RUN_REL}/kpi/proxy.json",
            ],
            "linked_kpi_family": "proxy",
            "mutable": False,
            "claim_authority": False,
        },
        {
            "artifact_id": "A-C0056-R0001-volume-clock-phase-SUMMARY",
            "artifact_role": "volume_clock_phase_summary_artifact",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/artifacts/c0056_r0001_volume_clock_phase_summary.json",
            "sha256": summary_hash,
            "produced_by": "axiom_rift.proxies.c0056_r0001_intraday_volume_clock_phase",
            "source_inputs": [
                f"{RUN_REL}/kpi/proxy.json",
            ],
            "linked_kpi_family": "proxy",
            "mutable": False,
            "claim_authority": False,
        },
    ]
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0056_r0001_mt5_logic_parity_evidence",
        }
    ]
    ARTIFACT_LINEAGE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")
