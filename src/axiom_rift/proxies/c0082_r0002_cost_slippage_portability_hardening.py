"""C0082 R0002 proxy evidence for cost/slippage portability hardening."""

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


CAMPAIGN_ID = "C0082"
RUN_ID = "R0002"
WORK_UNIT_REL = "campaigns/C0082_intraday_midpoint_rotation_rejection_discovery"
RUN_REL = f"{WORK_UNIT_REL}/runs/{RUN_ID}"
RUN_DIR = PROJECT_ROOT / RUN_REL
CAMPAIGN_PATH = PROJECT_ROOT / WORK_UNIT_REL / "campaign.yaml"
SELECTED_PATH = PROJECT_ROOT / WORK_UNIT_REL / "selected.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0082_r0002_proxy_trades.csv"
SUMMARY_PATH = RUN_DIR / "artifacts" / "c0082_r0002_cost_slippage_portability_summary.json"
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
    "midpoint_distance_pressure",
    "failed_midpoint_cross_depth",
    "rotation_compression_ratio",
    "midpoint_rejection_wick",
    "close_escape_strength",
    "range_balance_skew",
    "volume_reengagement",
    "prior_day_midpoint_context",
    "session_escape_pressure",
    "spread_stress_inverse",
)
MODEL_FAMILY = "fold_local_midpoint_rotation_rejection_cost_slippage_portability_hardened_rank"
LABEL_SHAPE = "target_first_escape_quality_with_cost_slippage_survival_overlay"
SELECTION_RULE = "top_fold_local_cost_slippage_portability_hardened_midpoint_rotation_rejection_scores_per_active_day"
LOOKBACK_RANGE_BARS = base.LOOKBACK_RANGE_BARS
SHORT_RANGE_BARS = base.SHORT_RANGE_BARS
LABEL_HORIZON_BARS = base.LABEL_HORIZON_BARS
STOP_RANGE_MULTIPLE = base.STOP_RANGE_MULTIPLE
TARGET_RANGE_MULTIPLE = base.TARGET_RANGE_MULTIPLE
PRICE_DIGITS = base.PRICE_DIGITS
MIN_DAY_BARS = 30
MIDPOINT_ROTATION_REJECTION_LOOKBACK_BARS = 18
MIDPOINT_ROTATION_REJECTION_SHORT_LOOKBACK_BARS = 6
MIN_MIDPOINT_ROTATION_REJECTION_ACTIVITY = 0.16
HARDENING_RECENT_SPREAD_BARS = 12
HARDENING_PRIOR_SPREAD_BARS = 48
MAX_PORTABILITY_SPREAD_OVER_RANGE = 0.74
COST_STRESS_EXTRA_POINTS_PER_TRADE = (0.25, 0.50, 1.00)
HARDENING_COMPONENT_NAMES = (
    "base_midpoint_rotation_score_z",
    "spread_stress_inverse",
    "recent_spread_relief",
    "spread_acceleration_penalty",
    "thin_range_cost_density_penalty",
    "rotation_compression_survival_penalty",
    "session_escape_pressure",
)

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
class LinearMidpointRotationRejectionModel:
    fold_id: str
    feature_mean: tuple[float, ...]
    feature_std: tuple[float, ...]
    feature_weight: tuple[float, ...]
    train_candidate_count: int
    global_mean: float
    positive_label_rate: float
    midpoint_rotation_rejection_failure_rate: float


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
    prior_day_close: float | None
    prior_day_range: float | None
    prior_day_return: float | None
    prior_day_shadow_balance: float | None
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


def run_c0082_r0002_proxy(write: bool = True) -> dict[str, object]:
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
        model = fit_linear_midpoint_rotation_rejection_model(train_candidates, fold_id)
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
        hardened_candidates = harden_scored_candidates(
            scored_candidates,
            bars,
            range_average,
            short_range_average,
        )
        selected = base.select_daily_candidates(hardened_candidates)
        trades.extend(base.simulate_trades(bars, range_average, selected, split["test_oos"]))
        fold_model = linear_midpoint_rotation_rejection_model_summary(model)
        fold_model["hardening_overlay"] = {
            "component_names": list(HARDENING_COMPONENT_NAMES),
            "recent_spread_bars": HARDENING_RECENT_SPREAD_BARS,
            "prior_spread_bars": HARDENING_PRIOR_SPREAD_BARS,
            "max_portability_spread_over_range": MAX_PORTABILITY_SPREAD_OVER_RANGE,
            "uses_future_price_path": False,
            "model_selected": False,
        }
        fold_models.append(fold_model)
        state_distributions[fold_id] = score_distribution(hardened_candidates, selected, model)
        candidates_by_fold[fold_id] = {
            "train_candidate_count": len(train_candidates),
            "test_candidate_count": len(test_candidates),
            "pre_hardening_eligible_candidate_count": sum(
                1 for candidate in scored_candidates if candidate.score is not None
            ),
            "hardened_candidate_count": len(hardened_candidates),
            "hardened_eligible_candidate_count": sum(
                1 for candidate in hardened_candidates if candidate.score is not None
            ),
            "selected_candidate_count": len(selected),
            "feature_count": len(FEATURE_NAMES),
            "hardening_component_count": len(HARDENING_COMPONENT_NAMES),
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
        upper_shadow_sum = 0.0
        lower_shadow_sum = 0.0
        for pos in indices:
            upper_shadow, lower_shadow = wick_lengths(bars[pos])
            upper_shadow_sum += upper_shadow
            lower_shadow_sum += lower_shadow
        summaries[day_key] = {
            "open": bars[first].open,
            "close": bars[last].close,
            "high": max(bars[pos].high for pos in indices),
            "low": min(bars[pos].low for pos in indices),
            "volume": sum(volumes[pos] for pos in indices),
            "bar_count": len(indices),
            "opening_high": max(bars[pos].high for pos in opening_indices),
            "opening_low": min(bars[pos].low for pos in opening_indices),
            "upper_shadow_sum": upper_shadow_sum,
            "lower_shadow_sum": lower_shadow_sum,
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
            prior_close = None
            prior_range = None
            prior_return = None
            prior_shadow_balance = None
            prior_volume_per_bar = None
        else:
            prior_close = float(prior["close"])
            prior_range = float(prior["high"]) - float(prior["low"])
            prior_return = float(prior["close"]) - float(prior["open"])
            prior_shadow_balance = (float(prior["lower_shadow_sum"]) - float(prior["upper_shadow_sum"])) / max(
                prior_range,
                1e-9,
            )
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
                prior_day_close=prior_close,
                prior_day_range=prior_range,
                prior_day_return=prior_return,
                prior_day_shadow_balance=prior_shadow_balance,
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
        MIDPOINT_ROTATION_REJECTION_LOOKBACK_BARS,
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
            label = (
                candidate_label(bars, volumes, daily_contexts, range_average, volume_average, index, direction)
                if include_labels
                else None
            )
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
    release = midpoint_rotation_rejection_metrics(
        bars, volumes, context, volume_average, index, direction, average_range
    )
    if release["event_count"] <= 0:
        return None, None
    volume_ratio = volume_stability(volumes, volume_average, index)
    spread_stress = bar.spread_points / average_range
    if volume_ratio is None:
        return None, None
    features = (
        release["midpoint_distance_pressure"],
        release["failed_midpoint_cross_depth"],
        release["rotation_compression_ratio"],
        release["midpoint_rejection_wick"],
        release["close_escape_strength"],
        release["range_balance_skew"],
        release["volume_reengagement"],
        release["prior_day_midpoint_context"],
        release["session_escape_pressure"],
        1.0 / (1.0 + max(spread_stress, 0.0)),
    )
    prefix = "long" if direction > 0 else "short"
    dimensions = (
        midpoint_distance_bucket(release["midpoint_distance_pressure"]),
        failed_cross_bucket(release["failed_midpoint_cross_depth"]),
        rotation_compression_bucket(release["rotation_compression_ratio"]),
        midpoint_rejection_wick_bucket(release["midpoint_rejection_wick"]),
        close_escape_bucket(release["close_escape_strength"]),
        range_balance_bucket(release["range_balance_skew"]),
        volume_reengagement_bucket(release["volume_reengagement"]),
        prior_midpoint_context_bucket(release["prior_day_midpoint_context"]),
        session_escape_bucket(release["session_escape_pressure"]),
        spread_bucket(spread_stress),
        base.session_bucket(bar.time),
    )
    return prefix + "|" + "|".join(dimensions), features


def midpoint_rotation_rejection_metrics(
    bars: list[base.Bar],
    volumes: list[float],
    context: DailyContext,
    volume_average: list[float | None],
    index: int,
    direction: int,
    average_range: float,
) -> dict[str, float]:
    signal_bar = bars[index]
    day_width = context.high_so_far - context.low_so_far
    prior_day_range = context.prior_day_range
    prior_day_return = context.prior_day_return
    if day_width <= 0 or prior_day_range is None or prior_day_range <= 0 or prior_day_return is None:
        return {"event_count": 0.0}
    midpoint = (context.high_so_far + context.low_so_far) / 2.0
    short_start = index - MIDPOINT_ROTATION_REJECTION_SHORT_LOOKBACK_BARS + 1
    prior_start = index - MIDPOINT_ROTATION_REJECTION_LOOKBACK_BARS + 1
    if short_start < 0 or prior_start < 0:
        return {"event_count": 0.0}
    short_window = bars[short_start : index + 1]
    prior_window = bars[prior_start : index + 1]
    if len(short_window) < 3 or len(prior_window) < 8:
        return {"event_count": 0.0}
    average_volume = volume_average[index]
    if average_volume is None or average_volume <= 0:
        return {"event_count": 0.0}

    prior_high = max(bar.high for bar in prior_window)
    prior_low = min(bar.low for bar in prior_window)
    short_high = max(bar.high for bar in short_window)
    short_low = min(bar.low for bar in short_window)
    prior_width = max(prior_high - prior_low, 1e-9)
    short_width = max(short_high - short_low, 1e-9)
    midpoint_distance_pressure = direction * (signal_bar.close - midpoint) / average_range
    if direction > 0:
        failed_midpoint_cross_depth = (midpoint - short_low) / average_range
    else:
        failed_midpoint_cross_depth = (short_high - midpoint) / average_range
    rotation_compression_ratio = max(0.0, 1.0 - short_width / prior_width)
    midpoint_rejection_wick = directional_wick_rejection(signal_bar, direction)
    close_escape_strength = directional_bar_settlement(signal_bar, direction)
    range_balance_skew = directional_session_position(signal_bar.close, context, direction)
    if range_balance_skew is None:
        return {"event_count": 0.0}
    early_short_volume = base.mean(volumes[short_start:index]) or average_volume
    current_volume_ratio = volumes[index] / max(average_volume, 1e-9)
    early_volume_ratio = early_short_volume / max(average_volume, 1e-9)
    volume_reengagement = max(current_volume_ratio - early_volume_ratio, 0.0) * max(
        close_escape_strength + max(midpoint_rejection_wick, 0.0),
        0.0,
    )
    prior_day_midpoint_context = direction * prior_day_return / max(prior_day_range, 1e-9)
    escape_pressure = max(
        max(midpoint_distance_pressure, 0.0) / 2.0,
        max(failed_midpoint_cross_depth, 0.0),
        max(rotation_compression_ratio, 0.0),
        max(midpoint_rejection_wick, 0.0),
        max(close_escape_strength - 0.40, 0.0),
        max(range_balance_skew - 0.45, 0.0),
        min(max(volume_reengagement, 0.0) / 2.0, 1.0),
    )
    session_escape_pressure = bounded_session_progress(signal_bar.time) * escape_pressure
    activity = max(escape_pressure, session_escape_pressure)
    if activity < MIN_MIDPOINT_ROTATION_REJECTION_ACTIVITY:
        return {"event_count": 0.0}
    if midpoint_distance_pressure < 0.04 or failed_midpoint_cross_depth < 0.02:
        return {"event_count": 0.0}
    if close_escape_strength < 0.22 and range_balance_skew < 0.45:
        return {"event_count": 0.0}
    if rotation_compression_ratio < 0.03 and midpoint_rejection_wick < -0.04:
        return {"event_count": 0.0}
    return {
        "midpoint_distance_pressure": bounded(midpoint_distance_pressure, -3.0, 8.0),
        "failed_midpoint_cross_depth": bounded(failed_midpoint_cross_depth, -2.0, 6.0),
        "rotation_compression_ratio": bounded(rotation_compression_ratio, 0.0, 1.0),
        "midpoint_rejection_wick": bounded(midpoint_rejection_wick, -1.0, 1.0),
        "close_escape_strength": bounded(close_escape_strength, 0.0, 1.0),
        "range_balance_skew": bounded(range_balance_skew, 0.0, 1.0),
        "volume_reengagement": bounded(volume_reengagement, 0.0, 6.0),
        "prior_day_midpoint_context": bounded(prior_day_midpoint_context, -2.0, 2.0),
        "session_escape_pressure": bounded(session_escape_pressure, 0.0, 4.0),
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


def wick_lengths(bar: base.Bar) -> tuple[float, float]:
    high_body = max(bar.open, bar.close)
    low_body = min(bar.open, bar.close)
    upper = max(0.0, bar.high - high_body)
    lower = max(0.0, low_body - bar.low)
    return upper, lower


def directional_wick_rejection(bar: base.Bar, direction: int) -> float:
    upper_wick, lower_wick = wick_lengths(bar)
    total_range = max(bar.high - bar.low, 1e-9)
    if direction > 0:
        return (lower_wick - upper_wick) / total_range
    return (upper_wick - lower_wick) / total_range


def directional_body_score(bar: base.Bar, direction: int) -> float:
    total_range = max(bar.high - bar.low, 1e-9)
    return direction * (bar.close - bar.open) / total_range


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


def opposing_run_bucket(value: float) -> str:
    if value < 0.55:
        return "opposing_run_thin"
    if value < 1.75:
        return "opposing_run_defined"
    return "opposing_run_stretched"


def body_decay_bucket(value: float) -> str:
    if value < 0.85:
        return "body_decay_absent"
    if value < 1.45:
        return "body_decay_moderate"
    return "body_decay_strong"


def close_erosion_bucket(value: float) -> str:
    if value < -0.05:
        return "close_erosion_continuation"
    if value < 0.12:
        return "close_erosion_mixed"
    return "close_erosion_clear"


def counter_wick_decay_bucket(value: float) -> str:
    if value < 0.14:
        return "counter_wick_low"
    if value < 0.32:
        return "counter_wick_mid"
    return "counter_wick_high"


def participation_decay_bucket(value: float) -> str:
    if value < -0.08:
        return "participation_expanding"
    if value < 0.10:
        return "participation_flat"
    return "participation_fading"


def path_efficiency_loss_bucket(value: float) -> str:
    if value < 0.20:
        return "path_loss_low"
    if value < 0.85:
        return "path_loss_mid"
    return "path_loss_high"


def conviction_range_extension_bucket(value: float) -> str:
    if value < 0.75:
        return "range_extension_underbuilt"
    if value < 1.85:
        return "range_extension_mature"
    return "range_extension_stretched"


def failed_followthrough_bucket(value: float) -> str:
    if value < 0.45:
        return "followthrough_decay_light"
    if value < 1.60:
        return "followthrough_decay_mid"
    return "followthrough_decay_heavy"


def prior_direction_context_bucket(value: float) -> str:
    if value < -0.20:
        return "prior_direction_conflict"
    if value < 0.35:
        return "prior_direction_neutral"
    return "prior_direction_aligned"


def boundary_extreme_bucket(value: float) -> str:
    if value < 0.22:
        return "boundary_extreme_light"
    if value < 0.48:
        return "boundary_extreme_defined"
    return "boundary_extreme_deep"


def boundary_wick_bucket(value: float) -> str:
    if value < -0.08:
        return "boundary_wick_against"
    if value < 0.12:
        return "boundary_wick_mixed"
    return "boundary_wick_rejecting"


def close_reclaim_bucket(value: float) -> str:
    if value < 0.30:
        return "close_reclaim_weak"
    if value < 0.58:
        return "close_reclaim_mixed"
    return "close_reclaim_strong"


def stretch_bucket(value: float) -> str:
    if value < 0.35:
        return "stretch_light"
    if value < 1.45:
        return "stretch_defined"
    return "stretch_extended"


def opening_dislocation_bucket(value: float) -> str:
    if value < 0.05:
        return "opening_dislocation_inside"
    if value < 0.85:
        return "opening_dislocation_edge"
    return "opening_dislocation_outside"


def volume_climax_fade_bucket(value: float) -> str:
    if value < 0.10:
        return "volume_climax_absent"
    if value < 0.65:
        return "volume_climax_moderate"
    return "volume_climax_heavy"


def counterpressure_bucket(value: float) -> str:
    if value < -0.08:
        return "counterpressure_absent"
    if value < 0.10:
        return "counterpressure_mixed"
    return "counterpressure_present"


def prior_extension_context_bucket(value: float) -> str:
    if value < -0.20:
        return "prior_extension_conflict"
    if value < 0.35:
        return "prior_extension_neutral"
    return "prior_extension_supportive"


def body_skew_bucket(value: float, prefix: str) -> str:
    if value < -0.08:
        return f"{prefix}_against"
    if value < 0.10:
        return f"{prefix}_mixed"
    return f"{prefix}_aligned"


def skew_delta_bucket(value: float) -> str:
    if value < -0.08:
        return "skew_delta_fading"
    if value < 0.08:
        return "skew_delta_flat"
    return "skew_delta_inflecting"


def wick_flip_bucket(value: float) -> str:
    if value < -0.08:
        return "wick_rejection_worsening"
    if value < 0.08:
        return "wick_rejection_flat"
    return "wick_rejection_flipping"


def close_shift_bucket(value: float) -> str:
    if value < -0.06:
        return "close_shift_against"
    if value < 0.08:
        return "close_shift_mixed"
    return "close_shift_supportive"


def range_confirmation_bucket(value: float) -> str:
    if value < 0.82:
        return "range_confirmation_contracting"
    if value < 1.30:
        return "range_confirmation_balanced"
    return "range_confirmation_expanding"


def participation_followthrough_bucket(value: float) -> str:
    if value < -0.15:
        return "participation_fading"
    if value < 0.18:
        return "participation_even"
    return "participation_following"


def adverse_tail_bucket(value: float) -> str:
    if value < 0.44:
        return "adverse_tail_heavy"
    if value < 0.70:
        return "adverse_tail_moderate"
    return "adverse_tail_light"


def prior_skew_context_bucket(value: float) -> str:
    if value < -0.20:
        return "prior_skew_conflict"
    if value < 0.35:
        return "prior_skew_neutral"
    return "prior_skew_aligned"


def impulse_range_bucket(value: float) -> str:
    if value < 0.85:
        return "impulse_range_thin"
    if value < 2.10:
        return "impulse_range_defined"
    return "impulse_range_extended"


def acceleration_pressure_bucket(value: float) -> str:
    if value < 0.55:
        return "acceleration_pressure_thin"
    if value < 1.65:
        return "acceleration_pressure_defined"
    return "acceleration_pressure_extended"


def followthrough_decay_bucket(value: float) -> str:
    if value < 0.12:
        return "followthrough_decay_weak"
    if value < 0.34:
        return "followthrough_decay_mixed"
    return "followthrough_decay_strong"


def saturation_bucket(value: float) -> str:
    if value < 0.34:
        return "extension_saturation_low"
    if value < 0.68:
        return "extension_saturation_mid"
    return "extension_saturation_high"


def impulse_efficiency_bucket(value: float) -> str:
    if value < 0.38:
        return "impulse_efficiency_choppy"
    if value < 0.68:
        return "impulse_efficiency_mixed"
    return "impulse_efficiency_clean"


def digestion_compression_bucket(value: float) -> str:
    if value < 0.38:
        return "digestion_expanded"
    if value < 0.62:
        return "digestion_moderate"
    return "digestion_compressed"


def retention_bucket(value: float) -> str:
    if value < 0.42:
        return "retention_weak"
    if value < 0.76:
        return "retention_mixed"
    return "retention_strong"


def adverse_overlap_bucket(value: float) -> str:
    if value < 0.42:
        return "adverse_overlap_deep"
    if value < 0.70:
        return "adverse_overlap_moderate"
    return "adverse_overlap_shallow"


def volume_cooldown_bucket(value: float) -> str:
    if value < -0.05:
        return "digestion_volume_rising"
    if value < 0.12:
        return "digestion_volume_flat"
    return "digestion_volume_cooling"


def absorption_balance_bucket(value: float) -> str:
    if value < -0.08:
        return "absorption_against"
    if value < 0.12:
        return "absorption_mixed"
    return "absorption_supportive"


def close_hold_bucket(value: float) -> str:
    if value < 0.46:
        return "close_hold_weak"
    if value < 0.66:
        return "close_hold_mixed"
    return "close_hold_strong"


def prior_impulse_context_bucket(value: float) -> str:
    if value < -0.20:
        return "prior_impulse_conflict"
    if value < 0.35:
        return "prior_impulse_neutral"
    return "prior_impulse_aligned"


def dwell_ratio_bucket(value: float) -> str:
    if value < 0.22:
        return "dwell_thin"
    if value < 0.48:
        return "dwell_defined"
    return "dwell_persistent"


def touch_density_bucket(value: float) -> str:
    if value < 0.14:
        return "touch_sparse"
    if value < 0.34:
        return "touch_repeated"
    return "touch_dense"


def shallow_pullback_bucket(value: float) -> str:
    if value < 0.34:
        return "pullback_deep"
    if value < 0.64:
        return "pullback_mid"
    return "pullback_shallow"


def rejection_decay_bucket(value: float) -> str:
    if value < -0.08:
        return "rejection_rising"
    if value < 0.10:
        return "rejection_flat"
    return "rejection_decaying"


def close_commitment_bucket(value: float) -> str:
    if value < 0.58:
        return "close_commitment_weak"
    if value < 0.78:
        return "close_commitment_mid"
    return "close_commitment_strong"


def extreme_volume_bucket(value: float) -> str:
    if value < 0.82:
        return "extreme_volume_light"
    if value < 1.35:
        return "extreme_volume_normal"
    return "extreme_volume_heavy"


def range_position_pressure_bucket(value: float) -> str:
    if value < 0.90:
        return "range_position_low"
    if value < 2.20:
        return "range_position_mid"
    return "range_position_high"


def day_extension_pressure_bucket(value: float) -> str:
    if value < 0.75:
        return "day_extension_underbuilt"
    if value < 1.75:
        return "day_extension_mature"
    return "day_extension_stretched"


def prior_extension_context_bucket(value: float) -> str:
    if value < -0.20:
        return "prior_extension_conflict"
    if value < 0.35:
        return "prior_extension_neutral"
    return "prior_extension_aligned"


def adverse_excursion_bucket(value: float) -> str:
    if value < 0.65:
        return "adverse_excursion_thin"
    if value < 1.80:
        return "adverse_excursion_mid"
    return "adverse_excursion_deep"


def anchor_reset_bucket(value: float) -> str:
    if value < 0.35:
        return "anchor_reset_far"
    if value < 0.68:
        return "anchor_reset_near"
    return "anchor_reset_tight"


def opening_reclaim_bucket(value: float) -> str:
    if value < -0.20:
        return "opening_reclaim_failed"
    if value < 0.20:
        return "opening_reclaim_mixed"
    return "opening_reclaim_cleared"


def day_range_progress_bucket(value: float) -> str:
    if value < 0.70:
        return "day_range_underbuilt"
    if value < 1.75:
        return "day_range_mature"
    return "day_range_extended"


def short_recovery_bucket(value: float) -> str:
    if value < 0.25:
        return "short_recovery_stalled"
    if value < 1.05:
        return "short_recovery_active"
    return "short_recovery_fast"


def reset_settlement_bucket(value: float) -> str:
    if value < 0.42:
        return "reset_settlement_weak"
    if value < 0.65:
        return "reset_settlement_mixed"
    return "reset_settlement_strong"


def range_compression_bucket(value: float) -> str:
    if value < 0.82:
        return "range_reset_expanding"
    if value < 1.25:
        return "range_reset_even"
    return "range_reset_compressing"


def reset_volume_bucket(value: float) -> str:
    if value < -0.08:
        return "reset_volume_fading"
    if value < 0.10:
        return "reset_volume_flat"
    return "reset_volume_confirmed"


def prior_day_range_context_bucket(value: float) -> str:
    if value < 0.85:
        return "prior_day_range_quiet"
    if value < 1.75:
        return "prior_day_range_normal"
    return "prior_day_range_hot"


def shadow_pressure_bucket(value: float, prefix: str) -> str:
    if value < 0.18:
        return f"{prefix}_shadow_low"
    if value < 0.34:
        return f"{prefix}_shadow_mid"
    return f"{prefix}_shadow_high"


def shadow_imbalance_bucket(value: float) -> str:
    if value < -0.12:
        return "shadow_imbalance_adverse"
    if value < 0.12:
        return "shadow_imbalance_mixed"
    return "shadow_imbalance_favorable"


def shadow_cluster_bucket(value: float) -> str:
    if value < 0.16:
        return "shadow_cluster_sparse"
    if value < 0.34:
        return "shadow_cluster_present"
    return "shadow_cluster_dense"


def shadow_rejection_bucket(value: float) -> str:
    if value < -0.12:
        return "current_shadow_adverse"
    if value < 0.18:
        return "current_shadow_mixed"
    return "current_shadow_favorable"


def body_follow_bucket(value: float) -> str:
    if value < -0.25:
        return "body_follow_against"
    if value < 0.25:
        return "body_follow_flat"
    return "body_follow_with"


def shadow_settlement_bucket(value: float) -> str:
    if value < 0.45:
        return "shadow_settlement_weak"
    if value < 0.68:
        return "shadow_settlement_mid"
    return "shadow_settlement_strong"


def range_extreme_release_bucket(value: float) -> str:
    if value < 0.35:
        return "range_release_weak"
    if value < 0.68:
        return "range_release_mid"
    return "range_release_strong"


def participation_fade_bucket(value: float) -> str:
    if value < 0.32:
        return "participation_forced"
    if value < 0.55:
        return "participation_normal"
    return "participation_fading"


def range_extension_bucket(value: float) -> str:
    if value < 0.80:
        return "range_extension_low"
    if value < 1.80:
        return "range_extension_mid"
    return "range_extension_high"


def compression_release_bucket(value: float) -> str:
    if value < 0.72:
        return "compression_tight"
    if value < 1.20:
        return "compression_normal"
    return "compression_releasing"


def prior_shadow_contrast_bucket(value: float) -> str:
    if value < -0.18:
        return "prior_shadow_against_trade"
    if value < 0.18:
        return "prior_shadow_neutral"
    return "prior_shadow_with_trade"


def volume_confirmation_bucket(value: float) -> str:
    if value < -0.20:
        return "volume_confirmation_against"
    if value < 0.25:
        return "volume_confirmation_mixed"
    return "volume_confirmation_with"


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


def midpoint_distance_bucket(value: float) -> str:
    if value < 0.12:
        return "midpoint_escape_thin"
    if value < 0.45:
        return "midpoint_escape_defined"
    return "midpoint_escape_extended"


def failed_cross_bucket(value: float) -> str:
    if value < 0.08:
        return "midpoint_cross_shallow"
    if value < 0.35:
        return "midpoint_cross_defined"
    return "midpoint_cross_deep"


def rotation_compression_bucket(value: float) -> str:
    if value < 0.08:
        return "rotation_uncompressed"
    if value < 0.35:
        return "rotation_compressed"
    return "rotation_tight"


def midpoint_rejection_wick_bucket(value: float) -> str:
    if value < -0.08:
        return "midpoint_wick_against_escape"
    if value < 0.12:
        return "midpoint_wick_mixed"
    return "midpoint_wick_rejecting"


def close_escape_bucket(value: float) -> str:
    if value < 0.32:
        return "close_escape_weak"
    if value < 0.62:
        return "close_escape_moderate"
    return "close_escape_strong"


def range_balance_bucket(value: float) -> str:
    if value < 0.35:
        return "range_balance_weak"
    if value < 0.65:
        return "range_balance_mid"
    return "range_balance_escape_side"


def volume_reengagement_bucket(value: float) -> str:
    if value < 0.05:
        return "volume_reengagement_absent"
    if value < 0.35:
        return "volume_reengagement_defined"
    return "volume_reengagement_strong"


def prior_midpoint_context_bucket(value: float) -> str:
    if value < -0.20:
        return "prior_midpoint_against"
    if value < 0.20:
        return "prior_midpoint_neutral"
    return "prior_midpoint_with"


def session_escape_bucket(value: float) -> str:
    if value < 0.08:
        return "session_escape_thin"
    if value < 0.35:
        return "session_escape_defined"
    return "session_escape_late_strong"


def spread_bucket(value: float) -> str:
    if value < 0.06:
        return "spread_low"
    if value < 0.12:
        return "spread_mid"
    return "spread_high"


def candidate_label(
    bars: list[base.Bar],
    volumes: list[float],
    daily_contexts: list[DailyContext],
    range_average: list[float | None],
    volume_average: list[float | None],
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
    metrics = midpoint_rotation_rejection_metrics(
        bars,
        volumes,
        daily_contexts[index],
        volume_average,
        index,
        direction,
        average_range,
    )
    if metrics["event_count"] <= 0:
        return None
    midpoint_distance_reward = 0.15 if metrics["midpoint_distance_pressure"] > 0.35 and terminal > 0 else 0.0
    failed_cross_reward = 0.13 if metrics["failed_midpoint_cross_depth"] > 0.10 and terminal > 0 else 0.0
    compression_reward = 0.12 if metrics["rotation_compression_ratio"] > 0.12 and terminal > 0 else 0.0
    wick_reward = 0.12 if metrics["midpoint_rejection_wick"] > 0.08 and terminal > 0 else 0.0
    close_escape_reward = 0.13 if metrics["close_escape_strength"] > 0.52 and terminal > 0 else 0.0
    balance_reward = 0.10 if metrics["range_balance_skew"] > 0.58 and terminal > 0 else 0.0
    volume_reward = 0.08 if metrics["volume_reengagement"] > 0.06 and terminal > 0 else 0.0
    prior_context_reward = 0.06 if metrics["prior_day_midpoint_context"] > -0.20 and terminal > 0 else 0.0
    weak_midpoint_distance_penalty = 0.12 if metrics["midpoint_distance_pressure"] < 0.12 and terminal <= 0 else 0.0
    shallow_failed_cross_penalty = 0.12 if metrics["failed_midpoint_cross_depth"] < 0.05 and terminal <= 0 else 0.0
    no_compression_penalty = 0.10 if metrics["rotation_compression_ratio"] < 0.04 and terminal <= 0 else 0.0
    wick_against_penalty = 0.12 if metrics["midpoint_rejection_wick"] < -0.08 and terminal <= 0 else 0.0
    weak_close_escape_penalty = 0.12 if metrics["close_escape_strength"] < 0.30 and terminal <= 0 else 0.0
    weak_balance_penalty = 0.10 if metrics["range_balance_skew"] < 0.42 and terminal <= 0 else 0.0
    no_volume_reengagement_penalty = 0.08 if metrics["volume_reengagement"] < 0.02 and terminal <= 0 else 0.0
    stall_penalty = 0.20 if mfe < 0.45 * average_range and terminal <= 0 else 0.0
    unfavorable_path_penalty = max(0.0, mae - mfe) / average_range * 0.35
    midpoint_rotation_rejection_path_quality = (0.46 * terminal + 0.34 * mfe - 0.74 * mae) / average_range
    same_bar_penalty = 0.25 * same_bar_conflict_count
    spread_penalty = bars[entry_index].spread_points / average_range
    return (
        first_hit
        + midpoint_rotation_rejection_path_quality
        + midpoint_distance_reward
        + failed_cross_reward
        + compression_reward
        + wick_reward
        + close_escape_reward
        + balance_reward
        + volume_reward
        + prior_context_reward
        - weak_midpoint_distance_penalty
        - shallow_failed_cross_penalty
        - no_compression_penalty
        - wick_against_penalty
        - weak_close_escape_penalty
        - weak_balance_penalty
        - no_volume_reengagement_penalty
        - stall_penalty
        - unfavorable_path_penalty
        - same_bar_penalty
        - spread_penalty
        - max(0.0, metrics["midpoint_distance_pressure"] - 3.20) * 0.04
    )


def fit_linear_midpoint_rotation_rejection_model(candidates: list[base.Candidate], fold_id: str) -> LinearMidpointRotationRejectionModel:
    labeled = [candidate for candidate in candidates if candidate.label is not None]
    if not labeled:
        return LinearMidpointRotationRejectionModel(
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
    midpoint_rotation_rejection_failure_rate = sum(1 for label in labels if label < -0.75) / len(labels)
    return LinearMidpointRotationRejectionModel(
        fold_id=fold_id,
        feature_mean=tuple(means),
        feature_std=tuple(stds),
        feature_weight=tuple(weights),
        train_candidate_count=len(labeled),
        global_mean=global_mean,
        positive_label_rate=positive_label_rate,
        midpoint_rotation_rejection_failure_rate=midpoint_rotation_rejection_failure_rate,
    )


def stddev(values: list[float], mean_value: float) -> float | None:
    if not values:
        return None
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def score_candidate(candidate: base.Candidate, model: LinearMidpointRotationRejectionModel) -> base.Candidate:
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


def harden_scored_candidates(
    candidates: list[base.Candidate],
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
) -> list[base.Candidate]:
    raw_scores = [float(candidate.score) for candidate in candidates if candidate.score is not None]
    if not raw_scores:
        return [copy_candidate(candidate, None, "cost_portability_no_base_score") for candidate in candidates]
    mean_score = base.mean(raw_scores) or 0.0
    std_score = math.sqrt(base.mean([(score - mean_score) ** 2 for score in raw_scores]) or 0.0)
    if std_score <= 1e-12:
        std_score = 1.0
    hardened: list[base.Candidate] = []
    for candidate in candidates:
        if candidate.score is None:
            hardened.append(copy_candidate(candidate, None, "cost_portability_no_base_score"))
            continue
        metrics = cost_slippage_portability_metrics(candidate, bars, range_average, short_range_average)
        if metrics is None:
            hardened.append(copy_candidate(candidate, None, "cost_portability_missing_context"))
            continue
        if metrics["recent_spread_over_range"] > MAX_PORTABILITY_SPREAD_OVER_RANGE:
            hardened.append(copy_candidate(candidate, None, "cost_portability_spread_veto"))
            continue
        base_score_z = (float(candidate.score) - mean_score) / std_score
        adjusted_score = (
            0.68 * base_score_z
            + 0.22 * metrics["spread_stress_inverse"]
            + 0.18 * metrics["recent_spread_relief"]
            + 0.10 * metrics["session_escape_pressure"]
            - 0.24 * metrics["spread_acceleration_penalty"]
            - 0.20 * metrics["thin_range_cost_density_penalty"]
            - 0.12 * metrics["rotation_compression_survival_penalty"]
        )
        hardened.append(copy_candidate(candidate, adjusted_score, portability_state(metrics)))
    return hardened


def copy_candidate(candidate: base.Candidate, score: float | None, state_suffix: str) -> base.Candidate:
    side = "long" if candidate.direction > 0 else "short"
    return base.Candidate(
        fold_id=candidate.fold_id,
        index=candidate.index,
        direction=candidate.direction,
        day=candidate.day,
        state_key=f"{side}|cost_slippage_portability_hardening|{state_suffix}",
        features=candidate.features,
        label=candidate.label,
        score=score,
    )


def cost_slippage_portability_metrics(
    candidate: base.Candidate,
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
) -> dict[str, float] | None:
    index = candidate.index
    average_range = range_average[index]
    short_average_range = short_range_average[index]
    if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
        return None
    recent_start = max(0, index - HARDENING_RECENT_SPREAD_BARS + 1)
    prior_start = max(0, index - HARDENING_PRIOR_SPREAD_BARS + 1)
    recent_spreads = [bars[pos].spread_points for pos in range(recent_start, index + 1)]
    prior_spreads = [bars[pos].spread_points for pos in range(prior_start, index + 1)]
    if not recent_spreads or not prior_spreads:
        return None
    recent_spread = base.mean(recent_spreads) or 0.0
    prior_spread = base.mean(prior_spreads) or recent_spread
    recent_spread_over_range = recent_spread / average_range
    prior_spread_over_range = prior_spread / average_range
    spread_acceleration = max(0.0, (recent_spread - prior_spread) / max(prior_spread, 1e-9))
    recent_spread_relief = max(-1.0, min(1.0, (prior_spread - recent_spread) / max(prior_spread, 1e-9)))
    thin_range_cost_density = recent_spread_over_range / max(short_average_range / average_range, 0.12)
    features = {name: float(candidate.features[pos]) for pos, name in enumerate(FEATURE_NAMES)}
    compression_penalty = max(0.0, features["rotation_compression_ratio"] - 0.72) * recent_spread_over_range
    return {
        "recent_spread_over_range": recent_spread_over_range,
        "prior_spread_over_range": prior_spread_over_range,
        "spread_stress_inverse": features["spread_stress_inverse"],
        "recent_spread_relief": recent_spread_relief,
        "spread_acceleration_penalty": spread_acceleration,
        "thin_range_cost_density_penalty": thin_range_cost_density,
        "rotation_compression_survival_penalty": compression_penalty,
        "session_escape_pressure": max(-1.0, min(1.0, features["session_escape_pressure"])),
    }


def portability_state(metrics: dict[str, float]) -> str:
    spread = metrics["recent_spread_over_range"]
    acceleration = metrics["spread_acceleration_penalty"]
    if spread < 0.18 and acceleration < 0.10:
        return "low_cost_stable"
    if spread < 0.34 and acceleration < 0.28:
        return "moderate_cost_stable"
    if acceleration >= 0.28:
        return "spread_acceleration_stress"
    return "high_cost_survivor"


def cost_slippage_stress_summary(trades: list[base.Trade]) -> dict[str, object]:
    if not trades:
        return {
            "trade_count": 0,
            "aggregate_extra_cost_per_trade_to_zero": None,
            "stress_rows": [],
        }
    net = sum(trade.pnl_points for trade in trades)
    stress_rows = []
    for extra_cost in COST_STRESS_EXTRA_POINTS_PER_TRADE:
        stressed_points = [trade.pnl_points - extra_cost for trade in trades]
        stress_rows.append(
            {
                "extra_cost_points_per_trade": extra_cost,
                "net_pnl_points": rounded(sum(stressed_points)),
                "profit_factor": profit_factor_points(stressed_points),
                "win_rate": rounded(sum(1 for value in stressed_points if value > 0) / len(stressed_points)),
            }
        )
    return {
        "trade_count": len(trades),
        "aggregate_extra_cost_per_trade_to_zero": rounded(net / len(trades)),
        "stress_rows": stress_rows,
    }


def profit_factor_points(points: list[float]) -> float | None:
    gross_profit = sum(value for value in points if value > 0)
    gross_loss = sum(value for value in points if value < 0)
    if gross_loss == 0:
        return None if gross_profit == 0 else rounded(gross_profit)
    return rounded(gross_profit / abs(gross_loss))


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
    cost_stress = cost_slippage_stress_summary(trades)
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
        "proxy_id": "PX-C0082-R0002",
        "dataset_identity": "data/processed/datasets/us100_m5_base_frame.csv",
        "split_policy": "rolling_window_test_oos_only_with_train_is_midpoint_rotation_rejection_fit_and_cost_portability_overlay",
        "fold_ids": fold_ids,
        "proxy_engine": "axiom_rift.proxies.c0082_r0002_cost_slippage_portability_hardening",
        "proxy_config_path": f"{RUN_REL}/run_manifest.json",
        "proxy_code_version_or_commit": "uncommitted_local_worktree_at_proxy_creation",
        "proxy_artifact_paths": [
            f"{RUN_REL}/kpi/proxy.json",
            f"{RUN_REL}/artifacts/c0082_r0002_proxy_trades.csv",
            f"{RUN_REL}/artifacts/c0082_r0002_cost_slippage_portability_summary.json",
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
            "midpoint_rotation_rejection_profile": {
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
                    "hardening_component_names": list(HARDENING_COMPONENT_NAMES),
                    "hardening_uses_future_price_path": False,
                    "model_selected": False,
                    "feature_set_selected": False,
                    "label_selected": False,
                },
            },
            "cost_slippage_portability_hardening_profile": {
                "applies": True,
                "fields": {
                    "base_candidate_source": "C0082_R0001_midpoint_rotation_rejection_surface",
                    "hardening_question": "does the retained midpoint-rotation evidence survive cost and slippage pressure without selection claims",
                    "recent_spread_bars": HARDENING_RECENT_SPREAD_BARS,
                    "prior_spread_bars": HARDENING_PRIOR_SPREAD_BARS,
                    "max_portability_spread_over_range": MAX_PORTABILITY_SPREAD_OVER_RANGE,
                    "extra_cost_points_per_trade_stress_levels": list(COST_STRESS_EXTRA_POINTS_PER_TRADE),
                    "proxy_cost_stress_summary": cost_stress,
                    "runtime_portability_claim": False,
                    "economics_pass": False,
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
                    "aggregate_extra_cost_per_trade_to_zero": cost_stress["aggregate_extra_cost_per_trade_to_zero"],
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
                "blocking_condition": "produce C0082 R0002 MT5 paired validation evidence",
                "revisit_when": "produce_c0082_r0002_mt5_logic_parity_evidence",
                "claim_boundary": {"claim_authority": False},
            },
            {
                "field": "proxy_artifact_hashes",
                "requirement_class": "deferred_with_reason",
                "reason": "self-hash is recorded in artifact_lineage after proxy.json is written",
                "blocking_condition": "proxy.json content must be stable before hashing",
                "revisit_when": "before C0082 R0002 closeout",
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
        "selection_rule": SELECTION_RULE,
        "lookback_range_bars": LOOKBACK_RANGE_BARS,
        "short_range_bars": SHORT_RANGE_BARS,
        "midpoint_rotation_rejection_lookback_bars": MIDPOINT_ROTATION_REJECTION_LOOKBACK_BARS,
        "midpoint_rotation_rejection_short_lookback_bars": MIDPOINT_ROTATION_REJECTION_SHORT_LOOKBACK_BARS,
        "min_midpoint_rotation_rejection_activity": MIN_MIDPOINT_ROTATION_REJECTION_ACTIVITY,
        "hardening_recent_spread_bars": HARDENING_RECENT_SPREAD_BARS,
        "hardening_prior_spread_bars": HARDENING_PRIOR_SPREAD_BARS,
        "max_portability_spread_over_range": MAX_PORTABILITY_SPREAD_OVER_RANGE,
        "hardening_component_names": list(HARDENING_COMPONENT_NAMES),
        "cost_stress_extra_points_per_trade": list(COST_STRESS_EXTRA_POINTS_PER_TRADE),
        "hardening_uses_future_price_path": False,
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


def linear_midpoint_rotation_rejection_model_summary(model: LinearMidpointRotationRejectionModel) -> dict[str, object]:
    return {
        "fold_id": model.fold_id,
        "feature_names": list(FEATURE_NAMES),
        "feature_mean": [rounded(value) for value in model.feature_mean],
        "feature_std": [rounded(value) for value in model.feature_std],
        "feature_weight": [rounded(value) for value in model.feature_weight],
        "train_candidate_count": model.train_candidate_count,
        "global_mean": rounded(model.global_mean),
        "positive_label_rate": rounded(model.positive_label_rate),
        "midpoint_rotation_rejection_failure_rate": rounded(model.midpoint_rotation_rejection_failure_rate),
    }


def score_distribution(
    scored: list[base.Candidate],
    selected: list[base.Candidate],
    model: LinearMidpointRotationRejectionModel,
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
        "schema": "axiom_rift_cost_slippage_portability_summary_v1",
        "template": False,
        "work_unit_id": CAMPAIGN_ID,
        "run_id": RUN_ID,
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "midpoint_rotation_rejection_profile": profiles["midpoint_rotation_rejection_profile"]["fields"],  # type: ignore[index]
        "cost_slippage_portability_hardening_profile": profiles[
            "cost_slippage_portability_hardening_profile"
        ]["fields"],  # type: ignore[index]
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
    data["mt5_probe_plan"]["next_required_action"] = "produce_c0082_r0002_mt5_logic_parity_evidence"
    evidence = data.setdefault("evidence_paths", {})
    evidence["proxy_kpi"] = "kpi/proxy.json"
    evidence["proxy_trade_artifact"] = "artifacts/c0082_r0002_proxy_trades.csv"
    evidence["cost_slippage_portability_summary"] = "artifacts/c0082_r0002_cost_slippage_portability_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    evidence_gate = data.setdefault("evidence_gate", {})
    evidence_gate["status"] = "proxy_recorded_pending_mt5"
    evidence_gate.setdefault("checks", {})["proxy_kpi_path_recorded"] = True
    data.setdefault("parity_gate", {})["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0082_r0002_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "run_manifest.json",
        "artifact_lineage.json",
        "artifacts/c0082_r0002_proxy_trades.csv",
        "artifacts/c0082_r0002_cost_slippage_portability_summary.json",
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
            "revisit_when": "produce_c0082_r0002_mt5_logic_parity_evidence",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_campaign_status() -> None:
    data = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = "runs/R0002"
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["direction"] = "active_r0002_mt5_logic_parity"
    next_candidate["reason"] = "R0002 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0082_r0002_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_selected_status() -> None:
    data = yaml.safe_load(SELECTED_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_not_selected"
    data["selected_reason"] = "C0082 R0002 proxy evidence is recorded as a reference surface only; MT5 paired validation and fold-isolated closeout remain mandatory before judgment."
    data["next_required_action"] = "produce_c0082_r0002_mt5_logic_parity_evidence"
    SELECTED_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_reentry_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(REENTRY_PATH.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = WORK_UNIT_REL
    data["project"]["active_run"] = RUN_REL
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = WORK_UNIT_REL
    completed = next_work.setdefault("completed", [])
    for item in (
        "produce_c0082_r0002_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_work["tasks"] = ["produce_c0082_r0002_mt5_logic_parity_evidence"]
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
        "id": "produce_c0082_r0002_proxy_evidence",
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
        "next_required_action": "produce_c0082_r0002_mt5_logic_parity_evidence",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_decision_cursor_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(DECISION_CURSOR_PATH.read_text(encoding="ascii"))
    data["canonical_source"] = f"{RUN_REL}/kpi/proxy.json"
    data["canonical_status"] = "proxy_recorded_pending_mt5"
    data["current_decision"] = "produce_c0082_r0002_mt5_logic_parity_evidence"
    data["active_campaign"] = WORK_UNIT_REL
    data["active_run"] = RUN_REL
    data["active_synthesis"] = None
    data["next_required_action"] = "produce_c0082_r0002_mt5_logic_parity_evidence"
    summary = data.setdefault("current_evidence_summary", {})
    summary.update(
        {
            "active_campaign": WORK_UNIT_REL,
            "active_run": RUN_REL,
            "active_run_status": "proxy_recorded_pending_mt5",
            "evidence_status": "proxy_recorded_pending_mt5",
            "current_task": "produce_c0082_r0002_mt5_logic_parity_evidence",
            "next_required_action": "produce_c0082_r0002_mt5_logic_parity_evidence",
            "proxy_trade_count": payload["required_kpis"]["proxy_trade_count"],  # type: ignore[index]
            "proxy_net_pnl_points": payload["required_kpis"].get("proxy_net_pnl_points"),  # type: ignore[index]
            "proxy_profit_factor": payload["required_kpis"]["proxy_profit_factor"],  # type: ignore[index]
            "entries_per_active_day": payload["proxy_summary"]["entries_per_active_day"],  # type: ignore[index]
            "note": "C0082 R0002 proxy evidence is recorded; MT5 paired validation remains mandatory and no selection or economics claim is created.",
        }
    )
    data["next_decision_basis"] = [
        {
            "path": f"{RUN_REL}/kpi/proxy.json",
            "role": "active_proxy_kpi",
            "summary": "C0082 R0002 proxy evidence recorded as reference surface only; MT5 logic parity is next.",
        },
        {
            "path": f"{RUN_REL}/run_manifest.json",
            "role": "active_run_manifest",
            "summary": "R0002 remains active and cannot close until mandatory MT5 paired and fold-isolated evidence exists.",
        },
    ]
    DECISION_CURSOR_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def append_decision_registry_after_proxy(payload: dict[str, object]) -> None:
    text = DECISION_REGISTRY_PATH.read_text(encoding="ascii")
    required = payload["required_kpis"]  # type: ignore[index]
    summary = payload["proxy_summary"]  # type: ignore[index]
    block = f"""
- decision_id: dec_20260707_produce_c0082_r0002_proxy_evidence
  created_local_date: '2026-07-06'
  status: active
  decision: produce_c0082_r0002_proxy_evidence
  refines:
  - dec_20260707_open_c0082_r0002_cost_slippage_portability_hardening_rank_run
  - dec_20260701_mandatory_mt5_paired_run_validation
  rationale:
  - c0082_r0002_proxy_records_midpoint_rotation_rejection_reference_surface
  - proxy_trade_count_{required.get("proxy_trade_count")}
  - entries_per_active_day_{summary.get("entries_per_active_day")}
  - proxy_net_pnl_points_{required.get("proxy_net_pnl_points")}
  - proxy_profit_factor_{required.get("proxy_profit_factor")}
  - proxy_result_cannot_skip_mt5_logic_parity_tick_execution_divergence_or_fold_isolated_closeout_evidence
  - next_work_is_produce_c0082_r0002_mt5_logic_parity_evidence
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
    if "dec_20260707_produce_c0082_r0002_proxy_evidence" not in text:
        DECISION_REGISTRY_PATH.write_text(text.rstrip() + block, encoding="ascii")


def update_artifact_lineage(proxy_hash: str, trade_hash: str, summary_hash: str) -> None:
    run_manifest_hash = sha256_file_local(RUN_MANIFEST_PATH)
    gate_hash = sha256_file_local(GATE_REPORT_PATH)
    data = json.loads(ARTIFACT_LINEAGE_PATH.read_text(encoding="ascii"))
    data["artifact_records"] = [
        {
            "artifact_id": "A-C0082-R0002-RUN-MANIFEST",
            "artifact_role": "run_manifest",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/run_manifest.json",
            "sha256": run_manifest_hash,
            "produced_by": "axiom_rift.proxies.c0082_r0002_cost_slippage_portability_hardening",
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
            "artifact_id": "A-C0082-R0002-GATE-REPORT",
            "artifact_role": "gate_report",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/gate_report.json",
            "sha256": gate_hash,
            "produced_by": "axiom_rift.proxies.c0082_r0002_cost_slippage_portability_hardening",
            "source_inputs": [
                f"{RUN_REL}/run_manifest.json",
                f"{RUN_REL}/kpi/proxy.json",
            ],
            "linked_kpi_family": None,
            "mutable": True,
            "claim_authority": False,
        },
        {
            "artifact_id": "A-C0082-R0002-PROXY-KPI",
            "artifact_role": "proxy_kpi",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/kpi/proxy.json",
            "sha256": proxy_hash,
            "produced_by": "axiom_rift.proxies.c0082_r0002_cost_slippage_portability_hardening",
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
            "artifact_id": "A-C0082-R0002-PROXY-TRADES",
            "artifact_role": "proxy_trade_artifact",
            "artifact_type": "csv",
            "repo_relative_path": f"{RUN_REL}/artifacts/c0082_r0002_proxy_trades.csv",
            "sha256": trade_hash,
            "produced_by": "axiom_rift.proxies.c0082_r0002_cost_slippage_portability_hardening",
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
            "artifact_id": "A-C0082-R0002-COST-SLIPPAGE-PORTABILITY-SUMMARY",
            "artifact_role": "cost_slippage_portability_summary_artifact",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/artifacts/c0082_r0002_cost_slippage_portability_summary.json",
            "sha256": summary_hash,
            "produced_by": "axiom_rift.proxies.c0082_r0002_cost_slippage_portability_hardening",
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
            "next_action": "produce_c0082_r0002_mt5_logic_parity_evidence",
        }
    ]
    ARTIFACT_LINEAGE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")
