"""C0119 R0001 proxy evidence for intraday range ladder failure repair."""

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


CAMPAIGN_ID = "C0119"
RUN_ID = "R0001"
WORK_UNIT_REL = "campaigns/C0119_intraday_range_ladder_failure_repair_discovery"
RUN_REL = f"{WORK_UNIT_REL}/runs/{RUN_ID}"
RUN_DIR = PROJECT_ROOT / RUN_REL
CAMPAIGN_PATH = PROJECT_ROOT / WORK_UNIT_REL / "campaign.yaml"
SELECTED_PATH = PROJECT_ROOT / WORK_UNIT_REL / "selected.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0119_r0001_proxy_trades.csv"
SUMMARY_PATH = RUN_DIR / "artifacts" / "c0119_r0001_range_ladder_failure_repair_summary.json"
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
    "ladder_step_consistency",
    "ladder_slope_pressure",
    "ladder_break_depth",
    "repair_reclaim_strength",
    "counter_ladder_absorption",
    "range_step_compression",
    "volume_repair_confirmation",
    "vwap_repair_alignment",
    "prior_session_ladder_context",
    "session_ladder_position",
    "session_maturity",
    "spread_stress_inverse",
)
MODEL_FAMILY = "fold_local_intraday_range_ladder_failure_repair_rank"
LABEL_SHAPE = "target_first_quality_after_range_ladder_failure_repair"
SELECTION_RULE = "top_fold_local_range_ladder_failure_repair_scores_per_active_day"
LOOKBACK_RANGE_BARS = base.LOOKBACK_RANGE_BARS
SHORT_RANGE_BARS = base.SHORT_RANGE_BARS
LABEL_HORIZON_BARS = base.LABEL_HORIZON_BARS
STOP_RANGE_MULTIPLE = base.STOP_RANGE_MULTIPLE
TARGET_RANGE_MULTIPLE = base.TARGET_RANGE_MULTIPLE
PRICE_DIGITS = base.PRICE_DIGITS
MIN_DAY_BARS = 18
RANGE_LADDER_FAILURE_REPAIR_LOOKBACK_BARS = 54
RANGE_LADDER_FAILURE_REPAIR_RECENT_BARS = 10
RANGE_LADDER_FAILURE_REPAIR_BASE_BARS = 18
MIN_LADDER_STEP_CONSISTENCY = 0.32
MIN_RANGE_LADDER_FAILURE_REPAIR_ACTIVITY = 0.055

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
class LinearRangeLadderFailureRepairModel:
    fold_id: str
    feature_mean: tuple[float, ...]
    feature_std: tuple[float, ...]
    feature_weight: tuple[float, ...]
    train_candidate_count: int
    global_mean: float
    positive_label_rate: float
    range_ladder_failure_repair_failure_rate: float


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
    overnight_high: float | None
    overnight_low: float | None
    overnight_close: float | None
    overnight_range: float | None
    overnight_return: float | None
    overnight_volume_per_bar: float | None
    prior_day_high: float | None
    prior_day_low: float | None
    prior_day_close: float | None
    prior_day_range: float | None
    prior_day_return: float | None
    prior_day_shadow_balance: float | None
    prior_day_volume_per_bar: float | None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rounded(value: float | None) -> float | None:
    return base.rounded(value)


def local_io_path(path: Path) -> str:
    resolved = str(path.resolve())
    if len(resolved) >= 240 and not resolved.startswith("\\\\?\\"):
        return "\\\\?\\" + resolved
    return resolved


def write_ascii_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_io_path(path), "w", encoding="ascii", newline="") as handle:
        handle.write(text)


def sha256_file_local(path: Path) -> str:
    digest = hashlib.sha256()
    with open(local_io_path(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_c0119_r0001_proxy(write: bool = True) -> dict[str, object]:
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
        model = fit_linear_range_ladder_failure_repair_model(train_candidates, fold_id)
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
        fold_models.append(linear_range_ladder_failure_repair_model_summary(model))
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

    summaries: dict[str, dict[str, float | int | None]] = {}
    for day_key, indices in indices_by_day.items():
        first = indices[0]
        last = indices[-1]
        opening_indices = indices[:12]
        overnight_indices = [
            pos for pos in indices if base.minute_of_day(bars[pos].time) < base.CORE_SESSION_START_MINUTE
        ]
        if overnight_indices:
            overnight_first = overnight_indices[0]
            overnight_last = overnight_indices[-1]
            overnight_high = max(bars[pos].high for pos in overnight_indices)
            overnight_low = min(bars[pos].low for pos in overnight_indices)
            overnight_close = bars[overnight_last].close
            overnight_range = overnight_high - overnight_low
            overnight_return = overnight_close - bars[overnight_first].open
            overnight_volume_per_bar = sum(volumes[pos] for pos in overnight_indices) / max(
                len(overnight_indices),
                1,
            )
        else:
            overnight_high = None
            overnight_low = None
            overnight_close = None
            overnight_range = None
            overnight_return = None
            overnight_volume_per_bar = None
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
            "overnight_high": overnight_high,
            "overnight_low": overnight_low,
            "overnight_close": overnight_close,
            "overnight_range": overnight_range,
            "overnight_return": overnight_return,
            "overnight_volume_per_bar": overnight_volume_per_bar,
            "upper_shadow_sum": upper_shadow_sum,
            "lower_shadow_sum": lower_shadow_sum,
        }

    prior_by_day: dict[str, dict[str, float | int | None] | None] = {}
    previous: dict[str, float | int | None] | None = None
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
        overnight_high = (
            float(summary["overnight_high"]) if summary.get("overnight_high") is not None else None
        )
        overnight_low = float(summary["overnight_low"]) if summary.get("overnight_low") is not None else None
        overnight_close = (
            float(summary["overnight_close"]) if summary.get("overnight_close") is not None else None
        )
        overnight_range = (
            float(summary["overnight_range"]) if summary.get("overnight_range") is not None else None
        )
        overnight_return = (
            float(summary["overnight_return"]) if summary.get("overnight_return") is not None else None
        )
        overnight_volume_per_bar = (
            float(summary["overnight_volume_per_bar"])
            if summary.get("overnight_volume_per_bar") is not None
            else None
        )
        if prior is None:
            prior_high = None
            prior_low = None
            prior_close = None
            prior_range = None
            prior_return = None
            prior_shadow_balance = None
            prior_volume_per_bar = None
        else:
            prior_high = float(prior["high"])
            prior_low = float(prior["low"])
            prior_close = float(prior["close"])
            prior_range = prior_high - prior_low
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
                overnight_high=overnight_high,
                overnight_low=overnight_low,
                overnight_close=overnight_close,
                overnight_range=overnight_range,
                overnight_return=overnight_return,
                overnight_volume_per_bar=overnight_volume_per_bar,
                prior_day_high=prior_high,
                prior_day_low=prior_low,
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
        RANGE_LADDER_FAILURE_REPAIR_LOOKBACK_BARS,
        RANGE_LADDER_FAILURE_REPAIR_RECENT_BARS + RANGE_LADDER_FAILURE_REPAIR_BASE_BARS,
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
    metrics = range_ladder_failure_repair_metrics(
        bars, volumes, context, volume_average, index, direction, average_range
    )
    if metrics["event_count"] <= 0:
        return None, None
    spread_stress = bar.spread_points / average_range
    features = (
        metrics["ladder_step_consistency"],
        metrics["ladder_slope_pressure"],
        metrics["ladder_break_depth"],
        metrics["repair_reclaim_strength"],
        metrics["counter_ladder_absorption"],
        metrics["range_step_compression"],
        metrics["volume_repair_confirmation"],
        metrics["vwap_repair_alignment"],
        metrics["prior_session_ladder_context"],
        metrics["session_ladder_position"],
        metrics["session_maturity"],
        metrics["spread_stress_inverse"],
    )
    prefix = "long" if direction > 0 else "short"
    dimensions = (
        touch_density_bucket(metrics["ladder_step_consistency"]),
        breakout_pressure_bucket(metrics["ladder_slope_pressure"]),
        breakout_pressure_bucket(metrics["ladder_break_depth"]),
        breakout_pressure_bucket(metrics["repair_reclaim_strength"]),
        absorption_bucket(metrics["counter_ladder_absorption"]),
        compression_bucket(metrics["range_step_compression"]),
        volume_confirmation_bucket(metrics["volume_repair_confirmation"]),
        vwap_alignment_bucket(metrics["vwap_repair_alignment"]),
        prior_day_position_context_bucket(metrics["prior_session_ladder_context"]),
        range_position_pressure_bucket(metrics["session_ladder_position"]),
        session_maturity_bucket(metrics["session_maturity"]),
        spread_bucket(spread_stress),
        base.session_bucket(bar.time),
    )
    return prefix + "|" + "|".join(dimensions), features


def range_ladder_failure_repair_metrics(
    bars: list[base.Bar],
    volumes: list[float],
    context: DailyContext,
    volume_average: list[float | None],
    index: int,
    direction: int,
    average_range: float,
) -> dict[str, float]:
    signal_bar = bars[index]
    recent_start = max(index - RANGE_LADDER_FAILURE_REPAIR_RECENT_BARS + 1, context.day_start_index)
    base_start = max(recent_start - RANGE_LADDER_FAILURE_REPAIR_BASE_BARS, context.day_start_index)
    lookback_start = max(index - RANGE_LADDER_FAILURE_REPAIR_LOOKBACK_BARS + 1, context.day_start_index)
    if base_start < 0 or recent_start < 0 or lookback_start < 0:
        return {"event_count": 0.0}
    base_window = bars[base_start:recent_start]
    recent_window = bars[recent_start : index + 1]
    lookback_window = bars[lookback_start : index + 1]
    day_window = bars[context.day_start_index : index + 1]
    if len(base_window) < 8 or len(recent_window) < 5 or len(lookback_window) < 24 or len(day_window) < MIN_DAY_BARS:
        return {"event_count": 0.0}
    average_volume = volume_average[index]
    if average_volume is None or average_volume <= 0:
        return {"event_count": 0.0}

    recent_ranges = [bar.high - bar.low for bar in recent_window]
    base_ranges = [bar.high - bar.low for bar in base_window]
    lookback_ranges = [bar.high - bar.low for bar in lookback_window]
    recent_range_mean = base.mean(recent_ranges) or average_range
    base_range_mean = base.mean(base_ranges) or average_range
    lookback_range_mean = base.mean(lookback_ranges) or average_range
    base_volume_mean = base.mean(volumes[base_start:recent_start]) or average_volume
    recent_volume_mean = base.mean(volumes[recent_start : index + 1]) or average_volume
    lookback_volume_mean = base.mean(volumes[lookback_start : index + 1]) or average_volume
    if recent_range_mean <= 0 or base_range_mean <= 0 or lookback_range_mean <= 0:
        return {"event_count": 0.0}

    session_phase_maturity = bounded_session_progress(signal_bar.time)
    if session_phase_maturity < 0.12 or session_phase_maturity > 0.88:
        return {"event_count": 0.0}

    def adverse_ladder_step(previous: base.Bar, current: base.Bar) -> bool:
        if direction > 0:
            return (current.high <= previous.high and current.low <= previous.low) or current.close < previous.close
        return (current.high >= previous.high and current.low >= previous.low) or current.close > previous.close

    ladder_steps = [
        adverse_ladder_step(previous, current)
        for previous, current in zip(lookback_window, lookback_window[1:])
    ]
    ladder_step_consistency = sum(1 for flag in ladder_steps if flag) / max(len(ladder_steps), 1)
    if ladder_step_consistency < MIN_LADDER_STEP_CONSISTENCY:
        return {"event_count": 0.0}

    base_width = max(max(bar.high for bar in base_window) - min(bar.low for bar in base_window), 1e-9)
    lookback_width = max(max(bar.high for bar in lookback_window) - min(bar.low for bar in lookback_window), 1e-9)
    range_step_compression = 1.0 - min(1.0, base_width / max(lookback_width, average_range * 1.5))
    ladder_mid = (min(bar.low for bar in lookback_window) + max(bar.high for bar in lookback_window)) / 2.0
    adverse_extreme = min(bar.low for bar in recent_window) if direction > 0 else max(bar.high for bar in recent_window)
    ladder_break_depth = max(0.0, -direction * (adverse_extreme - ladder_mid) / max(average_range, 1e-9))
    ladder_slope_pressure = -direction * (lookback_window[-1].close - lookback_window[0].close)
    ladder_slope_pressure = ladder_slope_pressure / max(lookback_range_mean * math.sqrt(len(lookback_window)), average_range)
    recent_directional_net = direction * (recent_window[-1].close - recent_window[0].close)
    repair_reclaim_strength = direction * (signal_bar.close - ladder_mid) / max(average_range, 1e-9)
    repair_reclaim_strength += recent_directional_net / max(recent_range_mean * len(recent_window), average_range)
    settlement_balance = base.mean([directional_bar_settlement(bar, direction) for bar in recent_window]) or 0.0
    absorbed_count = sum(
        1
        for bar in recent_window
        if direction * (bar.close - ladder_mid) > 0 or directional_bar_settlement(bar, direction) > 0.15
    )
    counter_ladder_absorption = 0.5 * (absorbed_count / max(len(recent_window), 1)) + 0.5 * max(
        settlement_balance, 0.0
    )
    if repair_reclaim_strength < -0.20 and counter_ladder_absorption < 0.25:
        return {"event_count": 0.0}

    volume_repair_confirmation = recent_volume_mean / max(average_volume, 1e-9)
    session_vwap = session_vwap_until(bars, volumes, context.day_start_index, index)
    vwap_repair_alignment = 1.0 - abs(signal_bar.close - session_vwap) / max(average_range * 3.0, 1e-9)
    prior_session_ladder_context = 0.0
    if context.prior_day_return is not None and context.prior_day_range is not None and context.prior_day_range > 0:
        prior_session_ladder_context = direction * context.prior_day_return / max(context.prior_day_range, 1e-9)
    if context.prior_day_shadow_balance is not None:
        prior_session_ladder_context += direction * context.prior_day_shadow_balance * 0.08
    session_ladder_position = directional_session_percentile_position(
        signal_bar.close,
        context.low_so_far,
        context.high_so_far,
        direction,
    )
    spread_stress = signal_bar.spread_points / average_range
    spread_stress_inverse = 1.0 / (1.0 + max(spread_stress, 0.0))
    if spread_stress_inverse < 0.35:
        return {"event_count": 0.0}

    activity = max(
        ladder_step_consistency * 0.34,
        max(ladder_slope_pressure, 0.0) * 0.22,
        max(ladder_break_depth, 0.0) * 0.12,
        max(repair_reclaim_strength, 0.0) * 0.24,
        counter_ladder_absorption * 0.22,
        max(range_step_compression, 0.0) * 0.14,
        max(volume_repair_confirmation - 0.70, 0.0) * 0.08,
        max(vwap_repair_alignment, 0.0) * 0.06,
    )
    if activity < MIN_RANGE_LADDER_FAILURE_REPAIR_ACTIVITY:
        return {"event_count": 0.0}
    return {
        "ladder_step_consistency": bounded(ladder_step_consistency, 0.0, 1.0),
        "ladder_slope_pressure": bounded(ladder_slope_pressure, -4.0, 8.0),
        "ladder_break_depth": bounded(ladder_break_depth, 0.0, 8.0),
        "repair_reclaim_strength": bounded(repair_reclaim_strength, -4.0, 8.0),
        "counter_ladder_absorption": bounded(counter_ladder_absorption, 0.0, 1.0),
        "range_step_compression": bounded(range_step_compression, -1.0, 1.0),
        "volume_repair_confirmation": bounded(volume_repair_confirmation, 0.0, 8.0),
        "vwap_repair_alignment": bounded(vwap_repair_alignment, -4.0, 1.0),
        "prior_session_ladder_context": bounded(prior_session_ladder_context, -3.0, 3.0),
        "session_ladder_position": bounded(session_ladder_position, 0.0, 1.0),
        "session_maturity": bounded(session_phase_maturity, 0.0, 1.0),
        "spread_stress_inverse": bounded(spread_stress_inverse, 0.0, 1.0),
        "recent_range_ratio": bounded(recent_range_mean / max(average_range, 1e-9), 0.0, 6.0),
        "base_range_ratio": bounded(base_range_mean / max(average_range, 1e-9), 0.0, 6.0),
        "lookback_range_ratio": bounded(lookback_range_mean / max(average_range, 1e-9), 0.0, 6.0),
        "recent_volume_ratio": bounded(recent_volume_mean / max(average_volume, 1e-9), 0.0, 8.0),
        "base_volume_ratio": bounded(base_volume_mean / max(average_volume, 1e-9), 0.0, 8.0),
        "lookback_volume_ratio": bounded(lookback_volume_mean / max(average_volume, 1e-9), 0.0, 8.0),
        "ladder_mid": rounded(ladder_mid) or 0.0,
        "ladder_adverse_extreme": rounded(adverse_extreme) or 0.0,
        "range_ladder_failure_repair_pressure": bounded(activity, 0.0, 8.0),
        "event_count": 1.0,
    }


def directional_session_percentile_position(price: float, session_low: float, session_high: float, direction: int) -> float:
    position = (price - session_low) / max(session_high - session_low, 1e-9)
    return bounded(position if direction > 0 else 1.0 - position, 0.0, 1.0)


def session_vwap_until(
    bars: list[base.Bar],
    volumes: list[float],
    start_index: int,
    end_index: int,
) -> float:
    start = max(0, start_index)
    end = max(start, end_index)
    total_volume = 0.0
    weighted_sum = 0.0
    closes: list[float] = []
    for pos in range(start, end + 1):
        typical = (bars[pos].high + bars[pos].low + bars[pos].close) / 3.0
        weight = max(volumes[pos], 0.0)
        total_volume += weight
        weighted_sum += typical * weight
        closes.append(bars[pos].close)
    if total_volume <= 0:
        return base.mean(closes) or bars[end].close
    return weighted_sum / total_volume


def volume_weighted_close(bars: list[base.Bar], volumes: list[float]) -> float:
    total_volume = sum(max(volume, 0.0) for volume in volumes)
    if total_volume <= 0:
        return base.mean([bar.close for bar in bars]) or bars[-1].close
    return sum(bar.close * max(volume, 0.0) for bar, volume in zip(bars, volumes)) / total_volume


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


def body_centroid(bar: base.Bar) -> float:
    return (bar.open + bar.close) / 2.0


def body_fraction(bar: base.Bar) -> float:
    return abs(bar.close - bar.open) / max(bar.high - bar.low, 1e-9)


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


def overnight_position_pressure_bucket(value: float) -> str:
    if value < -0.12:
        return "overnight_position_against"
    if value < 0.32:
        return "overnight_position_near_mid"
    return "overnight_position_unwinding"


def overnight_inventory_skew_bucket(value: float) -> str:
    if value < -0.15:
        return "overnight_inventory_with_trade"
    if value < 0.35:
        return "overnight_inventory_balanced"
    return "overnight_inventory_opposed"


def overnight_extension_pressure_bucket(value: float) -> str:
    if value < 0.10:
        return "overnight_extension_light"
    if value < 0.65:
        return "overnight_extension_defined"
    return "overnight_extension_heavy"


def core_reentry_depth_bucket(value: float) -> str:
    if value < 0.22:
        return "core_reentry_shallow"
    if value < 0.85:
        return "core_reentry_defined"
    return "core_reentry_deep"


def session_unwind_progress_bucket(value: float) -> str:
    if value < -0.10:
        return "session_unwind_counter"
    if value < 0.40:
        return "session_unwind_mixed"
    return "session_unwind_clear"


def range_reversion_efficiency_bucket(value: float) -> str:
    if value < -0.05:
        return "range_reversion_fading"
    if value < 0.35:
        return "range_reversion_mixed"
    return "range_reversion_efficient"


def volume_unwind_ratio_bucket(value: float) -> str:
    if value < 0.78:
        return "volume_unwind_thin"
    if value < 1.55:
        return "volume_unwind_orderly"
    return "volume_unwind_hot"


def vwap_unwind_alignment_bucket(value: float) -> str:
    if value < -0.45:
        return "vwap_unwind_far"
    if value < 0.30:
        return "vwap_unwind_near"
    return "vwap_unwind_tight"


def day_open_tension_bucket(value: float) -> str:
    if value < -0.10:
        return "day_open_tension_against"
    if value < 0.35:
        return "day_open_tension_neutral"
    return "day_open_tension_aligned"


def prior_day_range_context_bucket(value: float) -> str:
    if value < -0.22:
        return "prior_day_range_counter"
    if value < 0.22:
        return "prior_day_range_neutral"
    return "prior_day_range_aligned"


def drift_efficiency_bucket(value: float) -> str:
    if value < 0.18:
        return "drift_efficiency_thin"
    if value < 0.42:
        return "drift_efficiency_orderly"
    return "drift_efficiency_clean"


def range_moderation_bucket(value: float) -> str:
    if value < -0.18:
        return "range_moderation_expanding"
    if value < 0.18:
        return "range_moderation_even"
    return "range_moderation_quiet"


def spread_relief_bucket(value: float) -> str:
    if value < 0.48:
        return "spread_relief_poor"
    if value < 0.72:
        return "spread_relief_tradeable"
    return "spread_relief_clean"


def volume_stability_bucket(value: float) -> str:
    if value < -0.10:
        return "volume_stability_disrupted"
    if value < 0.45:
        return "volume_stability_mixed"
    return "volume_stability_orderly"


def pullback_containment_bucket(value: float) -> str:
    if value < 0.20:
        return "pullback_containment_thin"
    if value < 0.72:
        return "pullback_containment_balanced"
    return "pullback_containment_strong"


def vwap_alignment_bucket(value: float) -> str:
    if value < -0.08:
        return "vwap_alignment_against"
    if value < 0.20:
        return "vwap_alignment_neutral"
    return "vwap_alignment_supportive"


def prior_tailwind_bucket(value: float) -> str:
    if value < -0.16:
        return "prior_tailwind_conflict"
    if value < 0.20:
        return "prior_tailwind_neutral"
    return "prior_tailwind_aligned"


def adverse_wick_control_bucket(value: float) -> str:
    if value < 0.36:
        return "adverse_wick_control_poor"
    if value < 0.66:
        return "adverse_wick_control_mixed"
    return "adverse_wick_control_clean"


def continuation_room_bucket(value: float) -> str:
    if value < 0.18:
        return "continuation_room_thin"
    if value < 0.48:
        return "continuation_room_open"
    return "continuation_room_wide"


def c0119_extreme_retest_bucket(value: float) -> str:
    if value < 0.45:
        return "extreme_retest_light"
    if value < 0.95:
        return "extreme_retest_defined"
    return "extreme_retest_pin"


def c0119_recovery_bucket(value: float) -> str:
    if value < 0.22:
        return "failed_breakout_recovery_thin"
    if value < 0.75:
        return "failed_breakout_recovery_defined"
    return "failed_breakout_recovery_wide"


def c0119_opposite_room_bucket(value: float) -> str:
    if value < 0.25:
        return "opposite_room_thin"
    if value < 0.62:
        return "opposite_room_open"
    return "opposite_room_wide"


def trend_persistence_bucket(value: float) -> str:
    if value < -0.10:
        return "trend_persistence_against"
    if value < 0.35:
        return "trend_persistence_mixed"
    return "trend_persistence_with"


def range_reexpansion_bucket(value: float) -> str:
    if value < -0.15:
        return "range_reexpansion_absent"
    if value < 0.25:
        return "range_reexpansion_mixed"
    return "range_reexpansion_active"


def c0119_volume_exhaustion_bucket(value: float) -> str:
    if value < -0.18:
        return "volume_exhaustion_absent"
    if value < 0.18:
        return "volume_exhaustion_mixed"
    return "volume_exhaustion_defined"


def c0119_opening_reclaim_bucket(value: float) -> str:
    if value < -0.15:
        return "opening_range_reclaim_failed"
    if value < 0.45:
        return "opening_range_reclaim_mixed"
    return "opening_range_reclaim_clear"


def c0119_prior_contrast_bucket(value: float) -> str:
    if value < -0.18:
        return "prior_contrast_against"
    if value < 0.18:
        return "prior_contrast_neutral"
    return "prior_contrast_supportive"


def c0119_gap_size_bucket(value: float) -> str:
    if value < 0.45:
        return "gap_size_modest"
    if value < 1.05:
        return "gap_size_defined"
    return "gap_size_large"


def c0119_gap_residual_bucket(value: float) -> str:
    if value < 0.22:
        return "gap_residual_thin"
    if value < 0.75:
        return "gap_residual_tradeable"
    return "gap_residual_wide"


def c0119_gap_fill_bucket(value: float) -> str:
    if value < 0.05:
        return "gap_fill_not_started"
    if value < 0.45:
        return "gap_fill_partial"
    return "gap_fill_deep"


def c0119_volume_cooling_bucket(value: float) -> str:
    if value < -0.18:
        return "volume_still_expanding"
    if value < 0.18:
        return "volume_neutral"
    return "volume_cooling"


def c0119_prior_close_magnet_bucket(value: float) -> str:
    if value < -0.05:
        return "prior_close_far"
    if value < 0.38:
        return "prior_close_near"
    return "prior_close_magnetic"


def c0119_vwap_magnet_bucket(value: float) -> str:
    if value < -0.08:
        return "vwap_against_reversal"
    if value < 0.18:
        return "vwap_neutral"
    return "vwap_supports_reversal"


def opening_drive_extension_bucket(value: float) -> str:
    if value < 0.35:
        return "drive_extension_light"
    if value < 1.10:
        return "drive_extension_defined"
    return "drive_extension_stretched"


def opening_extreme_position_bucket(value: float) -> str:
    if value < 0.42:
        return "opening_extreme_inside"
    if value < 0.72:
        return "opening_extreme_outer"
    return "opening_extreme_deep"


def counter_body_turn_bucket(value: float) -> str:
    if value < -0.04:
        return "counter_body_absent"
    if value < 0.14:
        return "counter_body_mixed"
    return "counter_body_turning"


def adverse_absorption_bucket(value: float) -> str:
    if value < 0.18:
        return "adverse_absorption_thin"
    if value < 0.42:
        return "adverse_absorption_defined"
    return "adverse_absorption_heavy"


def reclaim_against_drive_bucket(value: float) -> str:
    if value < 0.10:
        return "drive_reclaim_absent"
    if value < 0.55:
        return "drive_reclaim_partial"
    return "drive_reclaim_clear"


def c0119_anchor_probe_bucket(value: float) -> str:
    if value < 0.05:
        return "probe_shallow"
    if value < 0.22:
        return "probe_defined"
    return "probe_deep"


def c0119_recoil_bucket(value: float) -> str:
    if value < 0.35:
        return "recoil_weak"
    if value < 0.68:
        return "recoil_partial"
    return "recoil_full"


def c0119_failed_followthrough_bucket(value: float) -> str:
    if value < -0.08:
        return "followthrough_opposite"
    if value < 0.16:
        return "followthrough_stalled"
    return "followthrough_reversal_started"


def c0119_tail_rejection_bucket(value: float) -> str:
    if value < -0.08:
        return "tail_rejection_failed"
    if value < 0.12:
        return "tail_rejection_mixed"
    return "tail_rejection_strong"


def c0119_reclaim_bucket(value: float) -> str:
    if value < -0.05:
        return "anchor_not_reclaimed"
    if value < 0.16:
        return "anchor_reclaimed_thin"
    return "anchor_reclaimed_clear"


def c0119_volume_exhaustion_bucket(value: float) -> str:
    if value < -0.18:
        return "volume_still_expanding"
    if value < 0.18:
        return "volume_flat"
    return "volume_exhausting"


def c0119_extension_stress_bucket(value: float) -> str:
    if value < 0.16:
        return "extension_minor"
    if value < 0.42:
        return "extension_defined"
    return "extension_stressed"


def c0119_opening_reclaim_bucket(value: float) -> str:
    if value < -0.08:
        return "opening_context_against"
    if value < 0.24:
        return "opening_context_neutral"
    return "opening_context_reclaimed"


def c0119_prior_anchor_bucket(value: float) -> str:
    if value < -0.12:
        return "prior_anchor_against"
    if value < 0.18:
        return "prior_anchor_neutral"
    return "prior_anchor_supportive"


def c0119_time_reversal_bucket(value: float) -> str:
    if value < 0.04:
        return "time_reversal_weak"
    if value < 0.18:
        return "time_reversal_mixed"
    return "time_reversal_aligned"


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


def vwap_dislocation_distance_bucket(value: float) -> str:
    if value < 0.10:
        return "vwap_dislocation_inside"
    if value < 0.85:
        return "vwap_dislocation_defined"
    return "vwap_dislocation_extended"


def vwap_reversion_depth_bucket(value: float) -> str:
    if value < 0.15:
        return "vwap_reversion_shallow"
    if value < 0.95:
        return "vwap_reversion_defined"
    return "vwap_reversion_deep"


def vwap_reclaim_bucket(value: float) -> str:
    if value < -0.04:
        return "vwap_reclaim_failed"
    if value < 0.35:
        return "vwap_reclaim_mixed"
    return "vwap_reclaim_clear"


def vwap_slope_alignment_bucket(value: float) -> str:
    if value < -0.04:
        return "vwap_slope_against"
    if value < 0.08:
        return "vwap_slope_flat"
    return "vwap_slope_aligned"


def vwap_wick_rejection_bucket(value: float) -> str:
    if value < -0.08:
        return "vwap_wick_against"
    if value < 0.12:
        return "vwap_wick_mixed"
    return "vwap_wick_rejecting"


def vwap_close_commitment_bucket(value: float) -> str:
    if value < 0.45:
        return "vwap_close_weak"
    if value < 0.66:
        return "vwap_close_mid"
    return "vwap_close_strong"


def reversion_impulse_bucket(value: float) -> str:
    if value < -0.10:
        return "reversion_impulse_against"
    if value < 0.45:
        return "reversion_impulse_mixed"
    return "reversion_impulse_with"


def dislocation_pressure_bucket(value: float) -> str:
    if value < 0.08:
        return "dislocation_pressure_light"
    if value < 0.65:
        return "dislocation_pressure_defined"
    return "dislocation_pressure_heavy"


def zigzag_density_bucket(value: float) -> str:
    if value < 0.30:
        return "zigzag_density_light"
    if value < 0.58:
        return "zigzag_density_defined"
    return "zigzag_density_dense"


def coil_compression_bucket(value: float) -> str:
    if value < -0.05:
        return "coil_expanding"
    if value < 0.12:
        return "coil_loose"
    return "coil_compressed"


def release_body_bucket(value: float) -> str:
    if value < -0.06:
        return "release_body_against"
    if value < 0.14:
        return "release_body_mixed"
    return "release_body_aligned"


def close_drive_bucket(value: float) -> str:
    if value < 0.44:
        return "close_drive_weak"
    if value < 0.66:
        return "close_drive_mid"
    return "close_drive_strong"


def range_expansion_bucket(value: float) -> str:
    if value < 0.70:
        return "release_range_thin"
    if value < 1.65:
        return "release_range_defined"
    return "release_range_extended"


def path_tortuosity_bucket(value: float) -> str:
    if value < 0.25:
        return "path_tortuosity_low"
    if value < 0.60:
        return "path_tortuosity_mixed"
    return "path_tortuosity_high"


def prior_day_energy_bucket(value: float) -> str:
    if value < 0.45:
        return "prior_energy_quiet"
    if value < 1.65:
        return "prior_energy_balanced"
    return "prior_energy_hot"


def session_release_bucket(value: float) -> str:
    if value < 0.08:
        return "session_release_light"
    if value < 0.65:
        return "session_release_defined"
    return "session_release_heavy"


def displacement_stretch_bucket(value: float) -> str:
    if value < 0.35:
        return "displacement_stretch_light"
    if value < 1.35:
        return "displacement_stretch_defined"
    return "displacement_stretch_extended"


def equilibrium_reclaim_bucket(value: float) -> str:
    if value < -0.04:
        return "equilibrium_reclaim_fading"
    if value < 0.18:
        return "equilibrium_reclaim_mixed"
    return "equilibrium_reclaim_clear"


def failed_extension_decay_bucket(value: float) -> str:
    if value < 0.08:
        return "failed_extension_decay_light"
    if value < 0.85:
        return "failed_extension_decay_defined"
    return "failed_extension_decay_heavy"


def prior_day_contrarian_bucket(value: float) -> str:
    if value < -0.20:
        return "prior_day_contrarian_conflict"
    if value < 0.35:
        return "prior_day_contrarian_neutral"
    return "prior_day_contrarian_supportive"


def session_reversion_bucket(value: float) -> str:
    if value < 0.08:
        return "session_reversion_light"
    if value < 0.65:
        return "session_reversion_defined"
    return "session_reversion_heavy"


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


def anchor_extreme_bucket(value: float) -> str:
    if value < 0.22:
        return "anchor_extreme_light"
    if value < 0.48:
        return "anchor_extreme_defined"
    return "anchor_extreme_deep"


def anchor_wick_bucket(value: float) -> str:
    if value < -0.08:
        return "anchor_wick_against"
    if value < 0.12:
        return "anchor_wick_mixed"
    return "anchor_wick_rejecting"


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


def position_percentile_bucket(value: float) -> str:
    if value < 0.46:
        return "position_lower"
    if value < 0.70:
        return "position_transition"
    return "position_upper"


def percentile_velocity_bucket(value: float) -> str:
    if value < 0.10:
        return "velocity_thin"
    if value < 0.24:
        return "velocity_defined"
    return "velocity_strong"


def percentile_acceleration_bucket(value: float) -> str:
    if value < -0.04:
        return "acceleration_fading"
    if value < 0.10:
        return "acceleration_flat"
    return "acceleration_confirming"


def transition_smoothness_bucket(value: float) -> str:
    if value < 0.08:
        return "transition_choppy"
    if value < 0.38:
        return "transition_mixed"
    return "transition_smooth"


def dwell_balance_bucket(value: float) -> str:
    if value < 0.30:
        return "dwell_low"
    if value < 0.58:
        return "dwell_transition"
    return "dwell_persistent"


def range_growth_efficiency_bucket(value: float) -> str:
    if value < -0.08:
        return "range_growth_negative"
    if value < 0.35:
        return "range_growth_mild"
    return "range_growth_clear"


def volume_confirmation_bucket(value: float) -> str:
    if value < -0.20:
        return "volume_fading"
    if value < 0.20:
        return "volume_neutral"
    return "volume_confirming"


def close_location_confirm_bucket(value: float) -> str:
    if value < 0.44:
        return "close_location_weak"
    if value < 0.68:
        return "close_location_mid"
    return "close_location_strong"


def vwap_side_confirm_bucket(value: float) -> str:
    if value < -0.20:
        return "vwap_side_against"
    if value < 0.20:
        return "vwap_side_mixed"
    return "vwap_side_confirmed"


def prior_day_position_context_bucket(value: float) -> str:
    if value < -0.25:
        return "prior_day_position_conflict"
    if value < 0.35:
        return "prior_day_position_neutral"
    return "prior_day_position_aligned"


def extension_pressure_bucket(value: float) -> str:
    if value < 0.75:
        return "extension_pressure_defined"
    if value < 1.60:
        return "extension_pressure_stretched"
    return "extension_pressure_extreme"


def volume_response_gap_bucket(value: float) -> str:
    if value < -0.08:
        return "volume_still_confirming"
    if value < 0.16:
        return "volume_gap_mixed"
    return "volume_gap_fading"


def body_efficiency_gap_bucket(value: float) -> str:
    if value < -0.08:
        return "body_efficiency_confirming"
    if value < 0.16:
        return "body_efficiency_mixed"
    return "body_efficiency_diverging"


def close_location_decay_bucket(value: float) -> str:
    if value < 0.28:
        return "close_decay_weak"
    if value < 0.52:
        return "close_decay_mixed"
    return "close_decay_clear"


def range_efficiency_decay_bucket(value: float) -> str:
    if value < 0.32:
        return "range_efficiency_hold"
    if value < 0.74:
        return "range_efficiency_mixed"
    return "range_efficiency_decaying"


def micro_slope_deceleration_bucket(value: float) -> str:
    if value < -0.02:
        return "micro_slope_accelerating"
    if value < 0.04:
        return "micro_slope_flat"
    return "micro_slope_decelerating"


def counter_wick_pressure_bucket(value: float) -> str:
    if value < -0.08:
        return "counter_wick_absent"
    if value < 0.12:
        return "counter_wick_mixed"
    return "counter_wick_visible"


def vwap_stretch_pressure_bucket(value: float) -> str:
    if value < 0.18:
        return "vwap_stretch_light"
    if value < 0.90:
        return "vwap_stretch_defined"
    return "vwap_stretch_extended"


def prior_extension_burden_bucket(value: float) -> str:
    if value < -0.15:
        return "prior_extension_against"
    if value < 0.35:
        return "prior_extension_neutral"
    return "prior_extension_loaded"


def divergence_consensus_bucket(value: float) -> str:
    if value < 0.10:
        return "divergence_consensus_thin"
    if value < 0.28:
        return "divergence_consensus_defined"
    return "divergence_consensus_strong"


def session_maturity_bucket(value: float) -> str:
    if value < 0.30:
        return "session_early_transition"
    if value < 0.62:
        return "session_mid_transition"
    return "session_late_transition"


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


def vwap_hold_bucket(value: float) -> str:
    if value < -0.35:
        return "vwap_hold_lost"
    if value < 0.18:
        return "vwap_hold_mixed"
    return "vwap_hold_clear"


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


def session_vwap_maturity_bucket(value: float) -> str:
    if value < 0.75:
        return "session_vwap_young"
    if value < 1.75:
        return "session_vwap_mature"
    return "session_vwap_late"


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


def streak_length_pressure_bucket(value: float) -> str:
    if value < 0.34:
        return "streak_length_short"
    if value < 0.84:
        return "streak_length_defined"
    return "streak_length_extended"


def streak_displacement_stretch_bucket(value: float) -> str:
    if value < 0.35:
        return "streak_stretch_light"
    if value < 1.35:
        return "streak_stretch_defined"
    return "streak_stretch_extended"


def body_effort_decay_streak_bucket(value: float) -> str:
    if value < -0.15:
        return "body_effort_reaccelerating"
    if value < 0.18:
        return "body_effort_flat"
    return "body_effort_decaying"


def close_progression_erosion_bucket(value: float) -> str:
    if value < -0.10:
        return "close_progression_continuing"
    if value < 0.16:
        return "close_progression_mixed"
    return "close_progression_eroding"


def counter_wick_rejection_streak_bucket(value: float) -> str:
    if value < -0.08:
        return "counter_wick_absent"
    if value < 0.18:
        return "counter_wick_mixed"
    return "counter_wick_rejecting"


def participation_fade_streak_bucket(value: float) -> str:
    if value < -0.18:
        return "participation_reloading"
    if value < 0.12:
        return "participation_flat"
    return "participation_fading"


def path_efficiency_loss_streak_bucket(value: float) -> str:
    if value < 0.24:
        return "path_efficiency_intact"
    if value < 0.68:
        return "path_efficiency_fraying"
    return "path_efficiency_lost"


def vwap_extension_pressure_bucket(value: float) -> str:
    if value < 0.10:
        return "vwap_extension_inside"
    if value < 0.95:
        return "vwap_extension_defined"
    return "vwap_extension_stretched"


def reversal_commitment_bucket(value: float) -> str:
    if value < -0.08:
        return "reversal_commitment_against"
    if value < 0.16:
        return "reversal_commitment_mixed"
    return "reversal_commitment_clear"


def pulse_volume_ratio_bucket(value: float) -> str:
    if value < 1.05:
        return "pulse_volume_light"
    if value < 1.55:
        return "pulse_volume_defined"
    return "pulse_volume_heavy"


def participation_acceleration_bucket(value: float) -> str:
    if value < -0.05:
        return "participation_accel_fading"
    if value < 0.18:
        return "participation_accel_mixed"
    return "participation_accel_expanding"


def pulse_body_commitment_bucket(value: float) -> str:
    if value < -0.08:
        return "pulse_body_against"
    if value < 0.30:
        return "pulse_body_mixed"
    return "pulse_body_with"


def pulse_close_commitment_bucket(value: float) -> str:
    if value < 0.45:
        return "pulse_close_weak"
    if value < 0.68:
        return "pulse_close_mid"
    return "pulse_close_strong"


def pulse_range_efficiency_bucket(value: float) -> str:
    if value < -0.05:
        return "pulse_range_inefficient"
    if value < 0.28:
        return "pulse_range_mixed"
    return "pulse_range_efficient"


def wick_containment_bucket(value: float) -> str:
    if value < 0.45:
        return "wick_containment_poor"
    if value < 0.72:
        return "wick_containment_mixed"
    return "wick_containment_clean"


def prior_participation_drought_bucket(value: float) -> str:
    if value < 0.04:
        return "prior_drought_absent"
    if value < 0.18:
        return "prior_drought_defined"
    return "prior_drought_deep"


def session_vwap_impulse_bucket(value: float) -> str:
    if value < -0.25:
        return "vwap_impulse_against"
    if value < 0.28:
        return "vwap_impulse_mixed"
    return "vwap_impulse_with"


def pulse_resolution_pressure_bucket(value: float) -> str:
    if value < 0.10:
        return "pulse_resolution_light"
    if value < 0.55:
        return "pulse_resolution_defined"
    return "pulse_resolution_heavy"


def spread_pressure_ratio_bucket(value: float) -> str:
    if value < 0.92:
        return "spread_pressure_calm"
    if value < 1.18:
        return "spread_pressure_defined"
    return "spread_pressure_heavy"


def spread_relief_intensity_bucket(value: float) -> str:
    if value < -0.08:
        return "spread_relief_absent"
    if value < 0.14:
        return "spread_relief_mixed"
    return "spread_relief_clear"


def cost_absorption_drive_bucket(value: float) -> str:
    if value < -0.08:
        return "cost_drive_against"
    if value < 0.28:
        return "cost_drive_mixed"
    return "cost_drive_with"


def close_after_cost_pressure_bucket(value: float) -> str:
    if value < 0.42:
        return "cost_close_weak"
    if value < 0.66:
        return "cost_close_mid"
    return "cost_close_strong"


def volume_cost_confirmation_bucket(value: float) -> str:
    if value < -0.04:
        return "cost_volume_fading"
    if value < 0.20:
        return "cost_volume_flat"
    return "cost_volume_confirming"


def spread_cluster_pressure_bucket(value: float) -> str:
    if value < 0.18:
        return "spread_cluster_sparse"
    if value < 0.42:
        return "spread_cluster_defined"
    return "spread_cluster_heavy"


def price_efficiency_under_cost_bucket(value: float) -> str:
    if value < -0.05:
        return "cost_efficiency_failed"
    if value < 0.24:
        return "cost_efficiency_mixed"
    return "cost_efficiency_clean"


def prior_cost_context_bucket(value: float) -> str:
    if value < 0.04:
        return "prior_cost_low"
    if value < 0.11:
        return "prior_cost_mid"
    return "prior_cost_high"


def cost_resolution_pressure_bucket(value: float) -> str:
    if value < 0.08:
        return "cost_resolution_light"
    if value < 0.46:
        return "cost_resolution_defined"
    return "cost_resolution_heavy"


def spread_bucket(value: float) -> str:
    if value < 0.06:
        return "spread_low"
    if value < 0.12:
        return "spread_mid"
    return "spread_high"


def break_compression_depth_bucket(value: float) -> str:
    if value < 0.04:
        return "break_compression_absent"
    if value < 0.20:
        return "break_compression_defined"
    return "break_compression_deep"


def volatility_expansion_ratio_bucket(value: float) -> str:
    if value < 0.95:
        return "vol_expansion_muted"
    if value < 1.65:
        return "vol_expansion_defined"
    return "vol_expansion_shock"


def range_break_strength_bucket(value: float) -> str:
    if value < -0.02:
        return "range_break_failed"
    if value < 0.22:
        return "range_break_probe"
    return "range_break_clear"


def directional_body_commitment_bucket(value: float) -> str:
    if value < -0.08:
        return "body_commitment_against"
    if value < 0.34:
        return "body_commitment_mixed"
    return "body_commitment_with"


def close_location_drive_bucket(value: float) -> str:
    if value < 0.45:
        return "close_drive_weak"
    if value < 0.70:
        return "close_drive_mid"
    return "close_drive_strong"


def participation_expansion_bucket(value: float) -> str:
    if value < -0.04:
        return "participation_contracting"
    if value < 0.18:
        return "participation_flat"
    return "participation_expanding"


def prebreak_range_contraction_bucket(value: float) -> str:
    if value < 0.02:
        return "prebreak_not_contracted"
    if value < 0.18:
        return "prebreak_contracted"
    return "prebreak_tightly_contracted"


def path_efficiency_bucket(value: float) -> str:
    if value < -0.05:
        return "path_efficiency_against"
    if value < 0.36:
        return "path_efficiency_mixed"
    return "path_efficiency_with"


def session_phase_maturity_bucket(value: float) -> str:
    if value < 0.33:
        return "session_phase_early"
    if value < 0.72:
        return "session_phase_core"
    return "session_phase_late"


def variance_decoupling_bucket(value: float) -> str:
    if value < 0.14:
        return "variance_decoupling_thin"
    if value < 0.85:
        return "variance_decoupling_defined"
    return "variance_decoupling_extreme"


def adverse_displacement_bucket(value: float) -> str:
    if value < -0.10:
        return "adverse_displacement_absent"
    if value < 0.45:
        return "adverse_displacement_defined"
    return "adverse_displacement_stretched"


def range_energy_excess_bucket(value: float) -> str:
    if value < 0.05:
        return "range_energy_excess_low"
    if value < 0.60:
        return "range_energy_excess_defined"
    return "range_energy_excess_heavy"


def path_churn_bucket(value: float) -> str:
    if value < 1.25:
        return "path_churn_light"
    if value < 3.40:
        return "path_churn_defined"
    return "path_churn_dense"


def recenter_pressure_bucket(value: float) -> str:
    if value < -0.12:
        return "recenter_pressure_against"
    if value < 0.30:
        return "recenter_pressure_mixed"
    return "recenter_pressure_clear"


def counter_wick_confirmation_bucket(value: float) -> str:
    if value < -0.08:
        return "counter_wick_against"
    if value < 0.12:
        return "counter_wick_mixed"
    return "counter_wick_confirming"


def counter_settlement_bucket(value: float) -> str:
    if value < 0.44:
        return "counter_settlement_weak"
    if value < 0.66:
        return "counter_settlement_mixed"
    return "counter_settlement_strong"


def participation_dislocation_bucket(value: float) -> str:
    if value < -0.20:
        return "participation_dislocation_fading"
    if value < 0.25:
        return "participation_dislocation_even"
    return "participation_dislocation_engaged"


def vwap_variance_pressure_bucket(value: float) -> str:
    if value < 0.08:
        return "vwap_variance_pressure_light"
    if value < 0.75:
        return "vwap_variance_pressure_defined"
    return "vwap_variance_pressure_heavy"


def prior_energy_context_bucket(value: float) -> str:
    if value < -0.20:
        return "prior_energy_context_quiet"
    if value < 0.35:
        return "prior_energy_context_normal"
    return "prior_energy_context_hot"


def breakout_pressure_bucket(value: float) -> str:
    if value < 0.08:
        return "breakout_pressure_light"
    if value < 0.55:
        return "breakout_pressure_defined"
    return "breakout_pressure_heavy"


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
    metrics = range_ladder_failure_repair_metrics(
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
    step_reward = 0.10 if metrics["ladder_step_consistency"] > 0.48 and terminal > 0 else 0.0
    slope_reward = 0.09 if metrics["ladder_slope_pressure"] > 0.20 and terminal > 0 else 0.0
    break_reward = 0.08 if metrics["ladder_break_depth"] > 0.25 and terminal > 0 else 0.0
    repair_reward = 0.13 if metrics["repair_reclaim_strength"] > 0.18 and terminal > 0 else 0.0
    absorption_reward = 0.09 if metrics["counter_ladder_absorption"] > 0.42 and terminal > 0 else 0.0
    compression_reward = 0.07 if metrics["range_step_compression"] > 0.10 and terminal > 0 else 0.0
    volume_reward = 0.06 if 0.80 <= metrics["volume_repair_confirmation"] <= 2.20 and terminal > 0 else 0.0
    vwap_reward = 0.06 if metrics["vwap_repair_alignment"] > 0.10 and terminal > 0 else 0.0
    position_reward = 0.05 if metrics["session_ladder_position"] > 0.45 and terminal > 0 else 0.0
    weak_step_penalty = 0.08 if metrics["ladder_step_consistency"] < 0.38 and terminal <= 0 else 0.0
    weak_slope_penalty = 0.07 if metrics["ladder_slope_pressure"] < -0.05 and terminal <= 0 else 0.0
    weak_repair_penalty = 0.10 if metrics["repair_reclaim_strength"] < 0.00 and terminal <= 0 else 0.0
    weak_absorption_penalty = 0.08 if metrics["counter_ladder_absorption"] < 0.24 and terminal <= 0 else 0.0
    overheated_volume_penalty = 0.06 if metrics["volume_repair_confirmation"] > 2.80 and terminal <= 0 else 0.0
    stall_penalty = 0.18 if mfe < 0.55 * average_range and terminal <= 0 else 0.0
    unfavorable_path_penalty = max(0.0, mae - mfe) / average_range * 0.35
    range_ladder_failure_repair_path_quality = (0.62 * terminal + 0.28 * mfe - 0.65 * mae) / average_range
    same_bar_penalty = 0.25 * same_bar_conflict_count
    spread_penalty = bars[entry_index].spread_points / average_range
    return (
        first_hit
        + range_ladder_failure_repair_path_quality
        + step_reward
        + slope_reward
        + break_reward
        + repair_reward
        + absorption_reward
        + compression_reward
        + volume_reward
        + vwap_reward
        + position_reward
        - weak_step_penalty
        - weak_slope_penalty
        - weak_repair_penalty
        - weak_absorption_penalty
        - overheated_volume_penalty
        - stall_penalty
        - unfavorable_path_penalty
        - same_bar_penalty
        - spread_penalty
        - max(0.0, metrics["recent_range_ratio"] - 2.60) * 0.04
        - max(0.0, metrics["recent_volume_ratio"] - 4.20) * 0.015
        - max(0.0, 0.34 - metrics["ladder_step_consistency"]) * 0.12
    )


def fit_linear_range_ladder_failure_repair_model(candidates: list[base.Candidate], fold_id: str) -> LinearRangeLadderFailureRepairModel:
    labeled = [candidate for candidate in candidates if candidate.label is not None]
    if not labeled:
        return LinearRangeLadderFailureRepairModel(
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
    range_ladder_failure_repair_failure_rate = sum(1 for label in labels if label < -0.75) / len(labels)
    return LinearRangeLadderFailureRepairModel(
        fold_id=fold_id,
        feature_mean=tuple(means),
        feature_std=tuple(stds),
        feature_weight=tuple(weights),
        train_candidate_count=len(labeled),
        global_mean=global_mean,
        positive_label_rate=positive_label_rate,
        range_ladder_failure_repair_failure_rate=range_ladder_failure_repair_failure_rate,
    )


def stddev(values: list[float], mean_value: float) -> float | None:
    if not values:
        return None
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def score_candidate(candidate: base.Candidate, model: LinearRangeLadderFailureRepairModel) -> base.Candidate:
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
        "proxy_id": "PX-C0119-R0001",
        "dataset_identity": "data/processed/datasets/us100_m5_base_frame.csv",
        "split_policy": "rolling_window_test_oos_only_with_train_is_range_ladder_failure_repair_fit",
        "fold_ids": fold_ids,
        "proxy_engine": "axiom_rift.proxies.c0119_r0001_intraday_range_ladder_failure_repair",
        "proxy_config_path": f"{RUN_REL}/run_manifest.json",
        "proxy_code_version_or_commit": "uncommitted_local_worktree_at_proxy_creation",
        "proxy_artifact_paths": [
            f"{RUN_REL}/kpi/proxy.json",
            f"{RUN_REL}/artifacts/c0119_r0001_proxy_trades.csv",
            f"{RUN_REL}/artifacts/c0119_r0001_range_ladder_failure_repair_summary.json",
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
            "range_ladder_failure_repair_profile": {
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
                "blocking_condition": "produce C0119 R0001 MT5 paired validation evidence",
                "revisit_when": "produce_c0119_r0001_mt5_logic_parity_evidence",
                "claim_boundary": {"claim_authority": False},
            },
            {
                "field": "proxy_artifact_hashes",
                "requirement_class": "deferred_with_reason",
                "reason": "self-hash is recorded in artifact_lineage after proxy.json is written",
                "blocking_condition": "proxy.json content must be stable before hashing",
                "revisit_when": "before C0119 R0001 closeout",
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
        "range_ladder_failure_repair_lookback_bars": RANGE_LADDER_FAILURE_REPAIR_LOOKBACK_BARS,
        "range_ladder_failure_repair_recent_bars": RANGE_LADDER_FAILURE_REPAIR_RECENT_BARS,
        "range_ladder_failure_repair_base_bars": RANGE_LADDER_FAILURE_REPAIR_BASE_BARS,
        "min_ladder_step_consistency": MIN_LADDER_STEP_CONSISTENCY,
        "min_range_ladder_failure_repair_activity": MIN_RANGE_LADDER_FAILURE_REPAIR_ACTIVITY,
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


def linear_range_ladder_failure_repair_model_summary(model: LinearRangeLadderFailureRepairModel) -> dict[str, object]:
    return {
        "fold_id": model.fold_id,
        "feature_names": list(FEATURE_NAMES),
        "feature_mean": [rounded(value) for value in model.feature_mean],
        "feature_std": [rounded(value) for value in model.feature_std],
        "feature_weight": [rounded(value) for value in model.feature_weight],
        "train_candidate_count": model.train_candidate_count,
        "global_mean": rounded(model.global_mean),
        "positive_label_rate": rounded(model.positive_label_rate),
        "range_ladder_failure_repair_failure_rate": rounded(model.range_ladder_failure_repair_failure_rate),
    }


def score_distribution(
    scored: list[base.Candidate],
    selected: list[base.Candidate],
    model: LinearRangeLadderFailureRepairModel,
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
        "schema": "axiom_rift_range_ladder_failure_repair_summary_v1",
        "template": False,
        "work_unit_id": CAMPAIGN_ID,
        "run_id": RUN_ID,
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "range_ladder_failure_repair_profile": profiles["range_ladder_failure_repair_profile"]["fields"],  # type: ignore[index]
        "claim_boundary": payload["claim_boundary"],
    }
    write_ascii_text(path, json.dumps(summary, indent=2, sort_keys=True) + "\n")


def update_proxy_hashes(trade_hash: str, summary_hash: str) -> None:
    data = json.loads(PROXY_PATH.read_text(encoding="ascii"))
    data["proxy_artifact_hashes"] = [trade_hash, summary_hash]
    PROXY_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_run_manifest_status() -> None:
    data = json.loads(RUN_MANIFEST_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_ready"
    data["gate_status"] = "proxy_recorded_pending_mt5"
    data["mt5_probe_plan"]["next_required_action"] = "produce_c0119_r0001_mt5_logic_parity_evidence"
    evidence = data.setdefault("evidence_paths", {})
    evidence["proxy_kpi"] = "kpi/proxy.json"
    evidence["proxy_trade_artifact"] = "artifacts/c0119_r0001_proxy_trades.csv"
    evidence["range_ladder_failure_repair_summary"] = "artifacts/c0119_r0001_range_ladder_failure_repair_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    if GATE_REPORT_PATH.exists():
        data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    else:
        data = {
            "schema": "axiom_rift_gate_report_v2",
            "template": False,
            "gate_report_id": "G-C0119-R0001",
            "work_unit_id": CAMPAIGN_ID,
            "campaign_id": CAMPAIGN_ID,
            "run_id": RUN_ID,
            "status": "opened_proxy_pending",
            "decision": "defer_with_reason",
            "opened_at_utc": utc_now(),
            "evidence_gate": {
                "status": "opened_proxy_pending",
                "checks": {},
            },
            "parity_gate": {
                "status": "blocked_until_mt5",
            },
            "evidence_paths": ["run_manifest.json"],
            "claim_boundary": CLAIM_BOUNDARY,
        }
    data["status"] = "proxy_recorded_pending_mt5"
    evidence_gate = data.setdefault("evidence_gate", {})
    evidence_gate["status"] = "proxy_recorded_pending_mt5"
    evidence_gate.setdefault("checks", {})["proxy_kpi_path_recorded"] = True
    data.setdefault("parity_gate", {})["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0119_r0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "run_manifest.json",
        "artifact_lineage.json",
        "artifacts/c0119_r0001_proxy_trades.csv",
        "artifacts/c0119_r0001_range_ladder_failure_repair_summary.json",
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
            "revisit_when": "produce_c0119_r0001_mt5_logic_parity_evidence",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_campaign_status() -> None:
    data = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    next_candidate = run_index.get("next_run_candidate")
    if not isinstance(next_candidate, dict):
        next_candidate = {}
        run_index["next_run_candidate"] = next_candidate
    next_candidate["direction"] = "active_r0001_mt5_logic_parity"
    next_candidate["reason"] = "R0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0119_r0001_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_selected_status() -> None:
    data = yaml.safe_load(SELECTED_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_not_selected"
    data["selected_reason"] = "C0119 R0001 proxy evidence is recorded as a reference surface only; MT5 paired validation and fold-isolated closeout remain mandatory before judgment."
    data["next_required_action"] = "produce_c0119_r0001_mt5_logic_parity_evidence"
    SELECTED_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_reentry_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(REENTRY_PATH.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = WORK_UNIT_REL
    data["project"]["active_run"] = RUN_REL
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = WORK_UNIT_REL
    completed = next_work.setdefault("completed", [])
    for item in (
        "produce_c0119_r0001_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_work["tasks"] = ["produce_c0119_r0001_mt5_logic_parity_evidence"]
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
        "id": "produce_c0119_r0001_proxy_evidence",
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
        "next_required_action": "produce_c0119_r0001_mt5_logic_parity_evidence",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_decision_cursor_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(DECISION_CURSOR_PATH.read_text(encoding="ascii"))
    data["canonical_source"] = f"{RUN_REL}/kpi/proxy.json"
    data["canonical_status"] = "proxy_recorded_pending_mt5"
    data["current_decision"] = "produce_c0119_r0001_mt5_logic_parity_evidence"
    data["active_campaign"] = WORK_UNIT_REL
    data["active_run"] = RUN_REL
    data["active_synthesis"] = None
    data["next_required_action"] = "produce_c0119_r0001_mt5_logic_parity_evidence"
    summary = data.setdefault("current_evidence_summary", {})
    summary.update(
        {
            "active_campaign": WORK_UNIT_REL,
            "active_run": RUN_REL,
            "active_run_status": "proxy_recorded_pending_mt5",
            "evidence_status": "proxy_recorded_pending_mt5",
            "current_task": "produce_c0119_r0001_mt5_logic_parity_evidence",
            "next_required_action": "produce_c0119_r0001_mt5_logic_parity_evidence",
            "proxy_trade_count": payload["required_kpis"]["proxy_trade_count"],  # type: ignore[index]
            "proxy_net_pnl_points": payload["required_kpis"].get("proxy_net_pnl_points"),  # type: ignore[index]
            "proxy_profit_factor": payload["required_kpis"]["proxy_profit_factor"],  # type: ignore[index]
            "entries_per_active_day": payload["proxy_summary"]["entries_per_active_day"],  # type: ignore[index]
            "note": "C0119 R0001 proxy evidence is recorded; MT5 paired validation remains mandatory and no selection or economics claim is created.",
        }
    )
    data["next_decision_basis"] = [
        {
            "path": f"{RUN_REL}/kpi/proxy.json",
            "role": "active_proxy_kpi",
            "summary": "C0119 R0001 proxy evidence recorded as reference surface only; MT5 logic parity is next.",
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
- decision_id: dec_20260707_produce_c0119_r0001_proxy_evidence
  created_local_date: '2026-07-07'
  status: active
  decision: produce_c0119_r0001_proxy_evidence
  refines:
  - dec_20260707_open_c0119_r0001_intraday_range_ladder_failure_repair_rank_run
  - dec_20260701_mandatory_mt5_paired_run_validation
  rationale:
  - c0119_r0001_proxy_records_range_ladder_failure_repair_reference_surface
  - proxy_trade_count_{required.get("proxy_trade_count")}
  - entries_per_active_day_{summary.get("entries_per_active_day")}
  - proxy_net_pnl_points_{required.get("proxy_net_pnl_points")}
  - proxy_profit_factor_{required.get("proxy_profit_factor")}
  - proxy_result_cannot_skip_mt5_logic_parity_tick_execution_divergence_or_fold_isolated_closeout_evidence
  - next_work_is_produce_c0119_r0001_mt5_logic_parity_evidence
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
    if "dec_20260707_produce_c0119_r0001_proxy_evidence" not in text:
        DECISION_REGISTRY_PATH.write_text(text.rstrip() + block, encoding="ascii")


def update_artifact_lineage(proxy_hash: str, trade_hash: str, summary_hash: str) -> None:
    run_manifest_hash = sha256_file_local(RUN_MANIFEST_PATH)
    gate_hash = sha256_file_local(GATE_REPORT_PATH)
    data = json.loads(ARTIFACT_LINEAGE_PATH.read_text(encoding="ascii")) if ARTIFACT_LINEAGE_PATH.exists() else {}
    data["schema"] = "axiom_rift_artifact_lineage_v1"
    data["template"] = False
    data["work_unit_id"] = CAMPAIGN_ID
    data["campaign_id"] = CAMPAIGN_ID
    data["run_id"] = RUN_ID
    data["status"] = "proxy_recorded_pending_mt5"
    data["artifact_records"] = [
        {
            "artifact_id": "A-C0119-R0001-RUN-MANIFEST",
            "artifact_role": "run_manifest",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/run_manifest.json",
            "sha256": run_manifest_hash,
            "produced_by": "axiom_rift.proxies.c0119_r0001_intraday_range_ladder_failure_repair",
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
            "artifact_id": "A-C0119-R0001-GATE-REPORT",
            "artifact_role": "gate_report",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/gate_report.json",
            "sha256": gate_hash,
            "produced_by": "axiom_rift.proxies.c0119_r0001_intraday_range_ladder_failure_repair",
            "source_inputs": [
                f"{RUN_REL}/run_manifest.json",
                f"{RUN_REL}/kpi/proxy.json",
            ],
            "linked_kpi_family": None,
            "mutable": True,
            "claim_authority": False,
        },
        {
            "artifact_id": "A-C0119-R0001-PROXY-KPI",
            "artifact_role": "proxy_kpi",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/kpi/proxy.json",
            "sha256": proxy_hash,
            "produced_by": "axiom_rift.proxies.c0119_r0001_intraday_range_ladder_failure_repair",
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
            "artifact_id": "A-C0119-R0001-PROXY-TRADES",
            "artifact_role": "proxy_trade_artifact",
            "artifact_type": "csv",
            "repo_relative_path": f"{RUN_REL}/artifacts/c0119_r0001_proxy_trades.csv",
            "sha256": trade_hash,
            "produced_by": "axiom_rift.proxies.c0119_r0001_intraday_range_ladder_failure_repair",
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
            "artifact_id": "A-C0119-R0001-RANGE-LADDER-FAILURE-REPAIR-SUMMARY",
            "artifact_role": "range_ladder_failure_repair_summary_artifact",
            "artifact_type": "json",
            "repo_relative_path": f"{RUN_REL}/artifacts/c0119_r0001_range_ladder_failure_repair_summary.json",
            "sha256": summary_hash,
            "produced_by": "axiom_rift.proxies.c0119_r0001_intraday_range_ladder_failure_repair",
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
            "next_action": "produce_c0119_r0001_mt5_logic_parity_evidence",
        }
    ]
    ARTIFACT_LINEAGE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")
