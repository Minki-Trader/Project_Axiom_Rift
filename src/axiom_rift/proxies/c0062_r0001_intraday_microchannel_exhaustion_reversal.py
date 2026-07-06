"""C0062 R0001 proxy evidence for intraday microchannel exhaustion reversal."""

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


CAMPAIGN_ID = "C0062"
RUN_ID = "R0001"
WORK_UNIT_REL = "campaigns/C0062_intraday_microchannel_exhaustion_reversal_discovery"
RUN_REL = f"{WORK_UNIT_REL}/runs/{RUN_ID}"
RUN_DIR = PROJECT_ROOT / RUN_REL
CAMPAIGN_PATH = PROJECT_ROOT / WORK_UNIT_REL / "campaign.yaml"
SELECTED_PATH = PROJECT_ROOT / WORK_UNIT_REL / "selected.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0062_r0001_proxy_trades.csv"
SUMMARY_PATH = RUN_DIR / "artifacts" / "c0062_r0001_microchannel_summary.json"
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
    "microchannel_length_ratio",
    "channel_efficiency",
    "channel_slope",
    "pullback_compression",
    "exhaustion_wick_pressure",
    "momentum_fatigue",
    "counter_channel_fracture",
    "reversal_close_pressure",
    "day_range_location",
    "participation_fatigue",
    "session_maturity_pressure",
    "spread_stress_inverse",
)
MODEL_FAMILY = "fold_local_intraday_microchannel_exhaustion_reversal_rank"
LABEL_SHAPE = "target_first_quality_conditioned_on_microchannel_exhaustion_reversal_state"
SELECTION_RULE = "top_fold_local_microchannel_exhaustion_reversal_scores_per_active_day"
LOOKBACK_RANGE_BARS = base.LOOKBACK_RANGE_BARS
SHORT_RANGE_BARS = base.SHORT_RANGE_BARS
LABEL_HORIZON_BARS = base.LABEL_HORIZON_BARS
STOP_RANGE_MULTIPLE = base.STOP_RANGE_MULTIPLE
TARGET_RANGE_MULTIPLE = base.TARGET_RANGE_MULTIPLE
PRICE_DIGITS = base.PRICE_DIGITS
MIN_DAY_BARS = 36
MICROCHANNEL_LOOKBACK_BARS = 14
MICROCHANNEL_SHORT_LOOKBACK_BARS = 5
MIN_MICROCHANNEL_ACTIVITY = 0.12

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
class LinearMicrochannelExhaustionReversalModel:
    fold_id: str
    feature_mean: tuple[float, ...]
    feature_std: tuple[float, ...]
    feature_weight: tuple[float, ...]
    train_candidate_count: int
    global_mean: float
    positive_label_rate: float
    exhaustion_reversal_failure_rate: float


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


def run_c0062_r0001_proxy(write: bool = True) -> dict[str, object]:
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
        model = fit_linear_microchannel_exhaustion_reversal_model(train_candidates, fold_id)
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
        fold_models.append(linear_microchannel_exhaustion_reversal_model_summary(model))
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
        MICROCHANNEL_LOOKBACK_BARS,
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
    channel = microchannel_exhaustion_reversal_metrics(
        bars, volumes, context, volume_average, index, direction, average_range
    )
    if channel["event_count"] <= 0:
        return None, None
    volume_ratio = volume_stability(volumes, volume_average, index)
    spread_stress = bar.spread_points / average_range
    if volume_ratio is None:
        return None, None
    features = (
        channel["microchannel_length_ratio"],
        channel["channel_efficiency"],
        channel["channel_slope"],
        channel["pullback_compression"],
        channel["exhaustion_wick_pressure"],
        channel["momentum_fatigue"],
        channel["counter_channel_fracture"],
        channel["reversal_close_pressure"],
        channel["day_range_location"],
        channel["participation_fatigue"],
        channel["session_maturity_pressure"],
        1.0 / (1.0 + max(spread_stress, 0.0)),
    )
    prefix = "long" if direction > 0 else "short"
    dimensions = (
        microchannel_length_bucket(channel["microchannel_length_ratio"]),
        channel_efficiency_bucket(channel["channel_efficiency"]),
        channel_slope_bucket(channel["channel_slope"]),
        pullback_compression_bucket(channel["pullback_compression"]),
        exhaustion_wick_bucket(channel["exhaustion_wick_pressure"]),
        momentum_fatigue_bucket(channel["momentum_fatigue"]),
        counter_fracture_bucket(channel["counter_channel_fracture"]),
        reversal_close_bucket(channel["reversal_close_pressure"]),
        day_range_location_bucket(channel["day_range_location"]),
        participation_fatigue_bucket(channel["participation_fatigue"]),
        session_pressure_bucket(channel["session_maturity_pressure"]),
        spread_bucket(spread_stress),
        base.session_bucket(bar.time),
    )
    return prefix + "|" + "|".join(dimensions), features


def microchannel_exhaustion_reversal_metrics(
    bars: list[base.Bar],
    volumes: list[float],
    context: DailyContext,
    volume_average: list[float | None],
    index: int,
    direction: int,
    average_range: float,
) -> dict[str, float]:
    signal_bar = bars[index]
    close = signal_bar.close
    day_width = context.high_so_far - context.low_so_far
    if day_width <= 0:
        return {"event_count": 0.0}
    prior_volume_per_bar = context.prior_day_volume_per_bar
    if prior_volume_per_bar is None or prior_volume_per_bar <= 0:
        return {"event_count": 0.0}
    window_start = index - MICROCHANNEL_LOOKBACK_BARS + 1
    short_start = index - MICROCHANNEL_SHORT_LOOKBACK_BARS + 1
    if window_start < 0 or short_start < 0:
        return {"event_count": 0.0}
    window = bars[window_start : index + 1]
    short_window = bars[short_start : index + 1]
    prior_channel_direction = -direction
    prior_window = window[:-1]
    if len(prior_window) < 4:
        return {"event_count": 0.0}
    channel_body_count = sum(1 for item in prior_window if prior_channel_direction * (item.close - item.open) > 0)
    microchannel_length_ratio = channel_body_count / len(prior_window)
    channel_net = prior_channel_direction * (prior_window[-1].close - prior_window[0].open)
    travel = sum(abs(prior_window[pos].close - prior_window[pos - 1].close) for pos in range(1, len(prior_window)))
    channel_efficiency = channel_net / max(travel, average_range)
    channel_slope = channel_net / max(average_range * len(prior_window), 1e-9)
    if microchannel_length_ratio < 0.42 and channel_slope < 0.04:
        return {"event_count": 0.0}
    short_ranges = [item.high - item.low for item in short_window]
    short_average = base.mean(short_ranges) or average_range
    pullback_compression = 1.0 / (1.0 + max(short_average / average_range, 0.0))
    exhaustion_wick_pressure = directional_wick_rejection(signal_bar, direction)
    earlier = prior_window[: max(2, len(prior_window) // 2)]
    later = prior_window[max(1, len(prior_window) // 2) :]
    early_momentum = prior_channel_direction * (earlier[-1].close - earlier[0].open) / max(
        average_range * len(earlier),
        1e-9,
    )
    late_momentum = prior_channel_direction * (later[-1].close - later[0].open) / max(
        average_range * len(later),
        1e-9,
    )
    momentum_fatigue = early_momentum - late_momentum
    counter_channel_fracture = direction * (close - prior_window[-1].close) / average_range
    reversal_close_pressure = directional_bar_settlement(signal_bar, direction)
    day_range_location = directional_session_position(close, context, direction)
    if day_range_location is None:
        return {"event_count": 0.0}
    range_completion = day_width / max(average_range, 1e-9)
    recent_volume = sum(volumes[max(0, index - MICROCHANNEL_SHORT_LOOKBACK_BARS + 1) : index + 1])
    expected_recent_volume = prior_volume_per_bar * MICROCHANNEL_SHORT_LOOKBACK_BARS
    recent_intensity = recent_volume / max(expected_recent_volume, 1e-9)
    participation_fatigue = 1.0 / (1.0 + max(recent_intensity, 0.0))
    session_maturity_pressure = bounded_session_progress(signal_bar.time) * max(
        microchannel_length_ratio,
        max(channel_slope, 0.0),
        max(exhaustion_wick_pressure, 0.0),
        max(momentum_fatigue, 0.0),
        max(counter_channel_fracture, 0.0),
    )
    activity = max(
        microchannel_length_ratio,
        abs(channel_efficiency),
        abs(channel_slope),
        pullback_compression,
        abs(exhaustion_wick_pressure),
        abs(momentum_fatigue),
        abs(counter_channel_fracture),
        reversal_close_pressure,
        day_range_location,
        participation_fatigue,
        session_maturity_pressure,
    )
    if activity < MIN_MICROCHANNEL_ACTIVITY:
        return {"event_count": 0.0}
    return {
        "microchannel_length_ratio": bounded(microchannel_length_ratio, 0.0, 1.0),
        "channel_efficiency": bounded(channel_efficiency, -1.0, 1.0),
        "channel_slope": bounded(channel_slope, -1.0, 1.0),
        "pullback_compression": bounded(pullback_compression, 0.0, 1.0),
        "exhaustion_wick_pressure": bounded(exhaustion_wick_pressure, -1.0, 1.0),
        "momentum_fatigue": bounded(momentum_fatigue, -2.0, 2.0),
        "counter_channel_fracture": bounded(counter_channel_fracture, -3.0, 3.0),
        "reversal_close_pressure": bounded(reversal_close_pressure, 0.0, 1.0),
        "day_range_location": bounded(day_range_location, 0.0, 1.0),
        "participation_fatigue": bounded(participation_fatigue, 0.0, 1.0),
        "day_range_completion_ratio": bounded(range_completion, 0.0, 8.0),
        "session_maturity_pressure": bounded(session_maturity_pressure, 0.0, 4.0),
        "event_count": 1.0,
    }


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


def directional_wick_rejection(bar: base.Bar, direction: int) -> float:
    high_body = max(bar.open, bar.close)
    low_body = min(bar.open, bar.close)
    upper_wick = max(0.0, bar.high - high_body)
    lower_wick = max(0.0, low_body - bar.low)
    total_range = max(bar.high - bar.low, 1e-9)
    if direction > 0:
        return (lower_wick - upper_wick) / total_range
    return (upper_wick - lower_wick) / total_range


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


def directional_bar_settlement(bar: base.Bar, direction: int) -> float:
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


def microchannel_length_bucket(value: float) -> str:
    if value < 0.50:
        return "microchannel_short"
    if value < 0.72:
        return "microchannel_mature"
    return "microchannel_extended"


def channel_efficiency_bucket(value: float) -> str:
    if value < 0.25:
        return "channel_inefficient"
    if value < 0.60:
        return "channel_orderly"
    return "channel_one_way"


def channel_slope_bucket(value: float) -> str:
    if value < 0.05:
        return "channel_slope_flat"
    if value < 0.18:
        return "channel_slope_active"
    return "channel_slope_hot"


def pullback_compression_bucket(value: float) -> str:
    if value < 0.42:
        return "pullback_expanded"
    if value < 0.58:
        return "pullback_normal"
    return "pullback_compressed"


def exhaustion_wick_bucket(value: float) -> str:
    if value < -0.12:
        return "exhaustion_wick_absent"
    if value < 0.22:
        return "exhaustion_wick_mixed"
    return "exhaustion_wick_present"


def momentum_fatigue_bucket(value: float) -> str:
    if value < -0.06:
        return "momentum_reaccelerating"
    if value < 0.10:
        return "momentum_flat"
    return "momentum_fatigued"


def counter_fracture_bucket(value: float) -> str:
    if value < -0.12:
        return "counter_fracture_failed"
    if value < 0.18:
        return "counter_fracture_tentative"
    return "counter_fracture_active"


def reversal_close_bucket(value: float) -> str:
    if value < 0.38:
        return "reversal_close_weak"
    if value < 0.67:
        return "reversal_close_mid"
    return "reversal_close_strong"


def day_range_location_bucket(value: float) -> str:
    if value < 0.35:
        return "day_location_deep_extreme"
    if value < 0.70:
        return "day_location_mid"
    return "day_location_reclaimed"


def participation_fatigue_bucket(value: float) -> str:
    if value < 0.32:
        return "participation_hot"
    if value < 0.55:
        return "participation_normal"
    return "participation_fatigued"


def session_pressure_bucket(value: float) -> str:
    if value < 0.25:
        return "session_pressure_low"
    if value < 0.90:
        return "session_pressure_mid"
    return "session_pressure_high"


def reversal_bucket(value: float) -> str:
    if value < -0.35:
        return "volume_reversal_against"
    if value < 0.35:
        return "volume_reversal_neutral"
    return "volume_reversal_with"


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
    history_start = index - MICROCHANNEL_LOOKBACK_BARS + 1
    if history_start < 0:
        return None
    history = bars[history_start : index + 1]
    prior_window = history[:-1]
    if len(prior_window) < 4:
        return None
    signal_close = bars[index].close
    prior_channel_direction = -direction
    channel_body_count = sum(1 for item in prior_window if prior_channel_direction * (item.close - item.open) > 0)
    microchannel_length_ratio = channel_body_count / len(prior_window)
    channel_net = prior_channel_direction * (prior_window[-1].close - prior_window[0].open)
    channel_slope = channel_net / max(average_range * len(prior_window), 1e-9)
    signal_fracture = direction * (signal_close - prior_window[-1].close) / average_range
    exhaustion_wick = directional_wick_rejection(bars[index], direction)
    earlier = prior_window[: max(2, len(prior_window) // 2)]
    later = prior_window[max(1, len(prior_window) // 2) :]
    early_momentum = prior_channel_direction * (earlier[-1].close - earlier[0].open) / max(
        average_range * len(earlier),
        1e-9,
    )
    late_momentum = prior_channel_direction * (later[-1].close - later[0].open) / max(
        average_range * len(later),
        1e-9,
    )
    momentum_fatigue = early_momentum - late_momentum
    reversal_close_pressure = directional_bar_settlement(bars[index], direction)
    channel_maturity_reward = 0.24 if microchannel_length_ratio >= 0.58 and channel_slope > 0.04 and terminal > 0 else 0.0
    fracture_reward = 0.20 if signal_fracture > 0.12 and terminal > 0 else 0.0
    wick_reward = 0.14 if exhaustion_wick > 0.18 and terminal > 0 else 0.0
    fatigue_reward = 0.12 if momentum_fatigue > 0.04 and terminal > 0 else 0.0
    close_reward = 0.10 if reversal_close_pressure > 0.62 and terminal > 0 else 0.0
    failed_fracture_penalty = 0.28 if signal_fracture <= 0.0 and terminal <= 0 else 0.0
    channel_overpower_penalty = 0.22 if channel_slope > 0.18 and terminal <= 0 and mae >= mfe else 0.0
    weak_maturity_penalty = 0.14 if microchannel_length_ratio < 0.45 and terminal <= 0 else 0.0
    stall_penalty = 0.20 if mfe < 0.45 * average_range and terminal <= 0 else 0.0
    unfavorable_expansion_penalty = max(0.0, mae - mfe) / average_range * 0.35
    reversal_path_quality = (0.45 * terminal + 0.35 * mfe - 0.75 * mae) / average_range
    same_bar_penalty = 0.25 * same_bar_conflict_count
    spread_penalty = bars[entry_index].spread_points / average_range
    return (
        first_hit
        + reversal_path_quality
        + channel_maturity_reward
        + fracture_reward
        + wick_reward
        + fatigue_reward
        + close_reward
        - failed_fracture_penalty
        - channel_overpower_penalty
        - weak_maturity_penalty
        - stall_penalty
        - unfavorable_expansion_penalty
        - same_bar_penalty
        - spread_penalty
    )


def fit_linear_microchannel_exhaustion_reversal_model(candidates: list[base.Candidate], fold_id: str) -> LinearMicrochannelExhaustionReversalModel:
    labeled = [candidate for candidate in candidates if candidate.label is not None]
    if not labeled:
        return LinearMicrochannelExhaustionReversalModel(
            fold_id,
            tuple(0.0 for _ in FEATURE_NAMES),
            tuple(1.0 for _ in FEATURE_NAMES),
            tuple(0.0 for _ in FEATURE_NAMES),
            0,
            0.0,
            0.0,
            0.0,
        )
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
    exhaustion_reversal_failure_rate = sum(1 for label in labels if label < -0.75) / len(labels)
    return LinearMicrochannelExhaustionReversalModel(
        fold_id=fold_id,
        feature_mean=tuple(means),
        feature_std=tuple(stds),
        feature_weight=tuple(weights),
        train_candidate_count=len(labeled),
        global_mean=global_mean,
        positive_label_rate=positive_label_rate,
        exhaustion_reversal_failure_rate=exhaustion_reversal_failure_rate,
    )


def stddev(values: list[float], mean_value: float) -> float | None:
    if not values:
        return None
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def score_candidate(candidate: base.Candidate, model: LinearMicrochannelExhaustionReversalModel) -> base.Candidate:
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
        "proxy_id": "PX-C0062-R0001",
        "dataset_identity": "data/processed/datasets/us100_m5_base_frame.csv",
        "split_policy": "rolling_window_test_oos_only_with_train_is_microchannel_exhaustion_reversal_fit",
        "fold_ids": fold_ids,
        "proxy_engine": "axiom_rift.proxies.c0062_r0001_intraday_microchannel_exhaustion_reversal",
        "proxy_config_path": f"{RUN_REL}/run_manifest.json",
        "proxy_code_version_or_commit": "uncommitted_local_worktree_at_proxy_creation",
        "proxy_artifact_paths": [
            f"{RUN_REL}/kpi/proxy.json",
            f"{RUN_REL}/artifacts/c0062_r0001_proxy_trades.csv",
            f"{RUN_REL}/artifacts/c0062_r0001_microchannel_summary.json",
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
            "microchannel_exhaustion_reversal_profile": {
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
                "blocking_condition": "produce C0062 R0001 MT5 paired validation evidence",
                "revisit_when": "produce_c0062_r0001_mt5_logic_parity_evidence",
                "claim_boundary": {"claim_authority": False},
            },
            {
                "field": "proxy_artifact_hashes",
                "requirement_class": "deferred_with_reason",
                "reason": "self-hash is recorded in artifact_lineage after proxy.json is written",
                "blocking_condition": "proxy.json content must be stable before hashing",
                "revisit_when": "before C0062 R0001 closeout",
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
        "microchannel_exhaustion_reversal_lookback_bars": MICROCHANNEL_LOOKBACK_BARS,
        "microchannel_exhaustion_reversal_short_lookback_bars": MICROCHANNEL_SHORT_LOOKBACK_BARS,
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


def linear_microchannel_exhaustion_reversal_model_summary(model: LinearMicrochannelExhaustionReversalModel) -> dict[str, object]:
    return {
        "fold_id": model.fold_id,
        "feature_names": list(FEATURE_NAMES),
        "feature_mean": [rounded(value) for value in model.feature_mean],
        "feature_std": [rounded(value) for value in model.feature_std],
        "feature_weight": [rounded(value) for value in model.feature_weight],
        "train_candidate_count": model.train_candidate_count,
        "global_mean": rounded(model.global_mean),
        "positive_label_rate": rounded(model.positive_label_rate),
        "exhaustion_reversal_failure_rate": rounded(model.exhaustion_reversal_failure_rate),
    }


def score_distribution(
    scored: list[base.Candidate],
    selected: list[base.Candidate],
    model: LinearMicrochannelExhaustionReversalModel,
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
        "schema": "axiom_rift_microchannel_exhaustion_reversal_summary_v1",
        "template": False,
        "work_unit_id": CAMPAIGN_ID,
        "run_id": RUN_ID,
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "microchannel_exhaustion_reversal_profile": profiles["microchannel_exhaustion_reversal_profile"]["fields"],  # type: ignore[index]
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
    data["mt5_probe_plan"]["next_required_action"] = "produce_c0062_r0001_mt5_logic_parity_evidence"
    evidence = data.setdefault("evidence_paths", {})
    evidence["proxy_kpi"] = "kpi/proxy.json"
    evidence["proxy_trade_artifact"] = "artifacts/c0062_r0001_proxy_trades.csv"
    evidence["microchannel_exhaustion_reversal_summary"] = "artifacts/c0062_r0001_microchannel_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    evidence_gate = data.setdefault("evidence_gate", {})
    evidence_gate["status"] = "proxy_recorded_pending_mt5"
    evidence_gate.setdefault("checks", {})["proxy_kpi_path_recorded"] = True
    data.setdefault("parity_gate", {})["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0062_r0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "run_manifest.json",
        "artifact_lineage.json",
        "artifacts/c0062_r0001_proxy_trades.csv",
        "artifacts/c0062_r0001_microchannel_summary.json",
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
            "revisit_when": "produce_c0062_r0001_mt5_logic_parity_evidence",
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
    closeout["remaining_question"] = "produce_c0062_r0001_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_selected_status() -> None:
    data = yaml.safe_load(SELECTED_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_not_selected"
    data["selected_reason"] = "C0062 R0001 proxy evidence is recorded as a reference surface only; MT5 paired validation and fold-isolated closeout remain mandatory before judgment."
    data["next_required_action"] = "produce_c0062_r0001_mt5_logic_parity_evidence"
    SELECTED_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_reentry_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(REENTRY_PATH.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = WORK_UNIT_REL
    data["project"]["active_run"] = RUN_REL
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = WORK_UNIT_REL
    completed = next_work.setdefault("completed", [])
    for item in (
        "produce_c0062_r0001_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_work["tasks"] = ["produce_c0062_r0001_mt5_logic_parity_evidence"]
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
        "id": "produce_c0062_r0001_proxy_evidence",
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
        "next_required_action": "produce_c0062_r0001_mt5_logic_parity_evidence",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_decision_cursor_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(DECISION_CURSOR_PATH.read_text(encoding="ascii"))
    data["canonical_source"] = f"{RUN_REL}/kpi/proxy.json"
    data["canonical_status"] = "proxy_recorded_pending_mt5"
    data["current_decision"] = "produce_c0062_r0001_mt5_logic_parity_evidence"
    data["active_campaign"] = WORK_UNIT_REL
    data["active_run"] = RUN_REL
    data["active_synthesis"] = None
    data["next_required_action"] = "produce_c0062_r0001_mt5_logic_parity_evidence"
    summary = data.setdefault("current_evidence_summary", {})
    summary.update(
        {
            "active_campaign": WORK_UNIT_REL,
            "active_run": RUN_REL,
            "active_run_status": "proxy_recorded_pending_mt5",
            "evidence_status": "proxy_recorded_pending_mt5",
            "current_task": "produce_c0062_r0001_mt5_logic_parity_evidence",
            "next_required_action": "produce_c0062_r0001_mt5_logic_parity_evidence",
            "proxy_trade_count": payload["required_kpis"]["proxy_trade_count"],  # type: ignore[index]
            "proxy_net_pnl_points": payload["required_kpis"].get("proxy_net_pnl_points"),  # type: ignore[index]
            "proxy_profit_factor": payload["required_kpis"]["proxy_profit_factor"],  # type: ignore[index]
            "entries_per_active_day": payload["proxy_summary"]["entries_per_active_day"],  # type: ignore[index]
            "note": "C0062 R0001 proxy evidence is recorded; MT5 paired validation remains mandatory and no selection or economics claim is created.",
        }
    )
    data["next_decision_basis"] = [
        {
            "path": f"{RUN_REL}/kpi/proxy.json",
            "role": "active_proxy_kpi",
            "summary": "C0062 R0001 proxy evidence recorded as reference surface only; MT5 logic parity is next.",
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
- decision_id: dec_20260706_produce_c0062_r0001_proxy_evidence
  created_local_date: '2026-07-06'
  status: active
  decision: produce_c0062_r0001_proxy_evidence
  refines:
  - dec_20260706_open_c0062_r0001_intraday_microchannel_exhaustion_reversal_rank_run
  - dec_20260701_mandatory_mt5_paired_run_validation
  rationale:
  - c0062_r0001_proxy_records_microchannel_exhaustion_reversal_reference_surface
  - proxy_trade_count_{required.get("proxy_trade_count")}
  - entries_per_active_day_{summary.get("entries_per_active_day")}
  - proxy_net_pnl_points_{required.get("proxy_net_pnl_points")}
  - proxy_profit_factor_{required.get("proxy_profit_factor")}
  - proxy_result_cannot_skip_mt5_logic_parity_tick_execution_divergence_or_fold_isolated_closeout_evidence
  - next_work_is_produce_c0062_r0001_mt5_logic_parity_evidence
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
    if "dec_20260706_produce_c0062_r0001_proxy_evidence" not in text:
        DECISION_REGISTRY_PATH.write_text(text.rstrip() + block, encoding="ascii")


def update_artifact_lineage(proxy_hash: str, trade_hash: str, summary_hash: str) -> None:
    run_manifest_hash = sha256_file_local(RUN_MANIFEST_PATH)
    gate_hash = sha256_file_local(GATE_REPORT_PATH)
    data = json.loads(ARTIFACT_LINEAGE_PATH.read_text(encoding="ascii"))
    data["artifact_records"] = [
        {
            "artifact_id": "A-C0062-R0001-RUN-MANIFEST",
            "artifact_role": "run_manifest",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/run_manifest.json",
            "sha256": run_manifest_hash,
            "produced_by": "axiom_rift.proxies.c0062_r0001_intraday_microchannel_exhaustion_reversal",
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
            "artifact_id": "A-C0062-R0001-GATE-REPORT",
            "artifact_role": "gate_report",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/gate_report.json",
            "sha256": gate_hash,
            "produced_by": "axiom_rift.proxies.c0062_r0001_intraday_microchannel_exhaustion_reversal",
            "source_inputs": [
                f"{RUN_REL}/run_manifest.json",
                f"{RUN_REL}/kpi/proxy.json",
            ],
            "linked_kpi_family": None,
            "mutable": True,
            "claim_authority": False,
        },
        {
            "artifact_id": "A-C0062-R0001-PROXY-KPI",
            "artifact_role": "proxy_kpi",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/kpi/proxy.json",
            "sha256": proxy_hash,
            "produced_by": "axiom_rift.proxies.c0062_r0001_intraday_microchannel_exhaustion_reversal",
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
            "artifact_id": "A-C0062-R0001-PROXY-TRADES",
            "artifact_role": "proxy_trade_artifact",
            "artifact_type": "csv",
            "repo_relative_path": f"{RUN_REL}/artifacts/c0062_r0001_proxy_trades.csv",
            "sha256": trade_hash,
            "produced_by": "axiom_rift.proxies.c0062_r0001_intraday_microchannel_exhaustion_reversal",
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
            "artifact_id": "A-C0062-R0001-microchannel-exhaustion-reversal-SUMMARY",
            "artifact_role": "microchannel_exhaustion_reversal_summary_artifact",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/artifacts/c0062_r0001_microchannel_summary.json",
            "sha256": summary_hash,
            "produced_by": "axiom_rift.proxies.c0062_r0001_intraday_microchannel_exhaustion_reversal",
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
            "next_action": "produce_c0062_r0001_mt5_logic_parity_evidence",
        }
    ]
    ARTIFACT_LINEAGE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")
