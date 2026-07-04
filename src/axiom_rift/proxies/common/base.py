"""C0004 R0001 proxy evidence for fold-local state archetype entries."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import yaml

from axiom_rift.paths import DATA_DIR, PROJECT_ROOT


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
RUN_DIR = PROJECT_ROOT / "campaigns" / "C0004_fold_local_state_archetype_discovery" / "runs" / "R0001"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0004_fold_local_state_archetype_discovery" / "campaign.yaml"
BASE_FRAME = DATA_DIR / "processed" / "datasets" / "us100_m5_base_frame.csv"
ROLLING_WINDOWS = DATA_DIR / "processed" / "coverage_audits" / "us100_m5_rolling_windows.csv"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0004_r0001_proxy_trades.csv"
STATE_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0004_r0001_state_archetype_summary.json"
RUN_MANIFEST_PATH = RUN_DIR / "run_manifest.json"
GATE_REPORT_PATH = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE_PATH = RUN_DIR / "artifact_lineage.json"

FEATURE_NAMES = (
    "directional_ret_6_over_range",
    "directional_ret_18_over_range",
    "range_ratio_48",
    "compression_ratio_12_over_48",
    "directional_range_position_36",
    "directional_body_fraction",
)
STATE_DIMENSIONS = (
    "volatility_regime",
    "trend_state",
    "compression_state",
    "range_position_state",
    "body_state",
    "session_phase",
)
MODELING_START = datetime(2022, 5, 2, 1, 0, 0)
LOOKBACK_RANGE_BARS = 48
SHORT_RANGE_BARS = 12
TREND_BARS = 18
MOMENTUM_BARS = 6
POSITION_BARS = 36
LABEL_HORIZON_BARS = 10
MAX_HOLD_BARS = 10
MAX_ENTRIES_PER_ACTIVE_DAY = 8
MIN_SIGNAL_SPACING_BARS = 6
MIN_TRAIN_ARCHETYPE_COUNT = 80
TOP_ARCHETYPES_PER_FOLD = 28
STOP_RANGE_MULTIPLE = 0.80
TARGET_RANGE_MULTIPLE = 1.10
SPREAD_POINT_VALUE = 0.01
STARTING_BALANCE_USD = 500.0
PRICE_DIGITS = 2
CORE_SESSION_START_MINUTE = 6 * 60
CORE_SESSION_END_MINUTE = 21 * 60
MAX_ENTRY_GAP = timedelta(minutes=5)
MAX_EXIT_CLOSE_GAP = timedelta(minutes=5)


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    spread_points: float


@dataclass(frozen=True)
class SplitWindow:
    fold_id: str
    split: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Candidate:
    fold_id: str
    index: int
    direction: int
    day: str
    state_key: str
    features: tuple[float, ...]
    label: float | None
    score: float | None = None


@dataclass(frozen=True)
class ArchetypeStats:
    archetype_id: str
    count: int
    mean_label: float
    positive_rate: float
    score: float


@dataclass(frozen=True)
class ArchetypeModel:
    fold_id: str
    global_mean: float
    global_positive_rate: float | None
    train_candidate_count: int
    eligible_archetypes: dict[str, ArchetypeStats]
    observed_archetype_count: int


@dataclass(frozen=True)
class Trade:
    fold_id: str
    signal_index: int
    entry_time: datetime
    exit_time: datetime
    direction: int
    score: float
    state_key: str
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    pnl_points: float
    bars_held: int
    exit_reason: str
    mfe_points: float
    mae_points: float
    spread_points: float


@dataclass(frozen=True)
class ProxyRunResult:
    trades: list[Trade]
    windows: dict[str, dict[str, SplitWindow]]
    fold_models: list[dict[str, object]]
    state_distributions: dict[str, dict[str, float | int | None]]
    candidates_by_fold: dict[str, dict[str, int]]


def build_proxy_run_result() -> ProxyRunResult:
    bars = load_bars(BASE_FRAME)
    windows = load_windows(ROLLING_WINDOWS)
    ranges = [bar.high - bar.low for bar in bars]
    range_average = previous_rolling_average(ranges, LOOKBACK_RANGE_BARS)
    short_range_average = previous_rolling_average(ranges, SHORT_RANGE_BARS)
    trades: list[Trade] = []
    fold_models: list[dict[str, object]] = []
    state_distributions: dict[str, dict[str, float | int | None]] = {}
    candidates_by_fold: dict[str, dict[str, int]] = {}
    for fold_id in sorted(fold_id for fold_id, split in windows.items() if {"train_is", "test_oos"} <= set(split)):
        split = windows[fold_id]
        train_candidates = build_candidates(
            bars,
            range_average,
            short_range_average,
            split["train_is"],
            fold_id,
            include_labels=True,
        )
        model = fit_archetype_model(train_candidates, fold_id)
        test_candidates = build_candidates(
            bars,
            range_average,
            short_range_average,
            split["test_oos"],
            fold_id,
            include_labels=False,
        )
        scored_candidates = [score_candidate(candidate, model) for candidate in test_candidates]
        selected = select_daily_candidates(scored_candidates)
        trades.extend(simulate_trades(bars, range_average, selected, split["test_oos"]))
        fold_models.append(archetype_model_summary(model))
        state_distributions[fold_id] = state_distribution(scored_candidates, selected, model)
        candidates_by_fold[fold_id] = {
            "train_candidate_count": len(train_candidates),
            "test_candidate_count": len(test_candidates),
            "selected_candidate_count": len(selected),
            "eligible_archetype_count": len(model.eligible_archetypes),
            "observed_archetype_count": model.observed_archetype_count,
        }
    return ProxyRunResult(
        trades=trades,
        windows=windows,
        fold_models=fold_models,
        state_distributions=state_distributions,
        candidates_by_fold=candidates_by_fold,
    )


def load_proxy_trades() -> list[Trade]:
    return build_proxy_run_result().trades


def run_c0004_r0001_proxy(write: bool = True) -> dict[str, object]:
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


def load_bars(path: Path) -> list[Bar]:
    bars: list[Bar] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            timestamp = datetime.strptime(row["time"], TIME_FORMAT)
            if timestamp < MODELING_START:
                continue
            bars.append(
                Bar(
                    time=timestamp,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    spread_points=float(row.get("spread") or 0.0) * SPREAD_POINT_VALUE,
                )
            )
    return bars


def load_windows(path: Path) -> dict[str, dict[str, SplitWindow]]:
    windows: dict[str, dict[str, SplitWindow]] = defaultdict(dict)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            windows[row["fold_id"]][row["split"]] = SplitWindow(
                fold_id=row["fold_id"],
                split=row["split"],
                start=datetime.strptime(row["start"], TIME_FORMAT),
                end=datetime.strptime(row["end"], TIME_FORMAT),
            )
    return dict(windows)


def build_candidates(
    bars: list[Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    window: SplitWindow,
    fold_id: str,
    include_labels: bool,
) -> list[Candidate]:
    start_index = max(
        first_index_at_or_after(bars, window.start),
        LOOKBACK_RANGE_BARS,
        SHORT_RANGE_BARS,
        TREND_BARS,
        POSITION_BARS,
        MOMENTUM_BARS,
    )
    end_index = min(last_index_at_or_before(bars, window.end), len(bars) - LABEL_HORIZON_BARS - 2)
    candidates: list[Candidate] = []
    for index in range(start_index, end_index + 1):
        if not in_core_session(bars[index].time):
            continue
        average_range = range_average[index]
        short_average_range = short_range_average[index]
        if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
            continue
        for direction in (1, -1):
            state_key, features = candidate_state_and_features(
                bars,
                range_average,
                short_range_average,
                index,
                direction,
            )
            if state_key is None or features is None:
                continue
            label = candidate_label(bars, range_average, index, direction) if include_labels else None
            candidates.append(
                Candidate(
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
    bars: list[Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    index: int,
    direction: int,
) -> tuple[str | None, tuple[float, ...] | None]:
    average_range = range_average[index]
    short_average_range = short_range_average[index]
    if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
        return None, None
    bar = bars[index]
    bar_range = max(bar.high - bar.low, 0.0)
    if bar_range <= 0:
        return None, None
    ret_6 = (bar.close - bars[index - MOMENTUM_BARS].close) / average_range
    ret_18 = (bar.close - bars[index - TREND_BARS].close) / average_range
    range_ratio = bar_range / average_range
    compression_ratio = short_average_range / average_range
    range_position = directional_range_position(bars, index, direction)
    if range_position is None:
        return None, None
    body_fraction = direction * (bar.close - bar.open) / bar_range
    directional_ret_6 = direction * ret_6
    directional_ret_18 = direction * ret_18
    features = (
        directional_ret_6,
        directional_ret_18,
        range_ratio,
        compression_ratio,
        range_position,
        body_fraction,
    )
    dimensions = (
        volatility_bucket(range_ratio),
        trend_bucket(directional_ret_18),
        compression_bucket(compression_ratio),
        range_position_bucket(range_position),
        body_bucket(body_fraction),
        session_bucket(bar.time),
    )
    prefix = "long" if direction > 0 else "short"
    return prefix + "|" + "|".join(dimensions), features


def directional_range_position(bars: list[Bar], index: int, direction: int) -> float | None:
    start = max(0, index - POSITION_BARS + 1)
    window = bars[start : index + 1]
    high = max(bar.high for bar in window)
    low = min(bar.low for bar in window)
    width = high - low
    if width <= 0:
        return None
    close = bars[index].close
    long_position = (close - low) / width
    return long_position if direction > 0 else 1.0 - long_position


def volatility_bucket(value: float) -> str:
    if value < 0.70:
        return "vol_low"
    if value < 1.20:
        return "vol_mid"
    return "vol_high"


def trend_bucket(value: float) -> str:
    if value < -0.45:
        return "trend_against"
    if value < 0.45:
        return "trend_flat"
    return "trend_with"


def compression_bucket(value: float) -> str:
    if value < 0.78:
        return "compressed"
    if value < 1.15:
        return "normal"
    return "expanded"


def range_position_bucket(value: float) -> str:
    if value < 0.33:
        return "opposite_edge"
    if value < 0.67:
        return "middle_range"
    return "directional_edge"


def body_bucket(value: float) -> str:
    if value < -0.25:
        return "body_against"
    if value < 0.25:
        return "body_neutral"
    return "body_with"


def session_bucket(timestamp: datetime) -> str:
    minute = minute_of_day(timestamp)
    if minute < 8 * 60:
        return "early_session"
    if minute < 13 * 60:
        return "europe_morning"
    if minute < 17 * 60:
        return "us_overlap"
    return "late_session"


def candidate_label(
    bars: list[Bar],
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
    path = bars[entry_index : exit_index + 1]
    stop_distance = STOP_RANGE_MULTIPLE * average_range
    target_distance = TARGET_RANGE_MULTIPLE * average_range
    stop_price = entry - direction * stop_distance
    target_price = entry + direction * target_distance
    first_hit = 0.0
    if direction > 0:
        mfe = max(bar.high - entry for bar in path)
        mae = max(entry - bar.low for bar in path)
        terminal = path[-1].close - entry
        for bar in path:
            hit_stop = bar.low <= stop_price
            hit_target = bar.high >= target_price
            if hit_stop:
                first_hit = -1.0
                break
            if hit_target:
                first_hit = 1.0
                break
    else:
        mfe = max(entry - bar.low for bar in path)
        mae = max(bar.high - entry for bar in path)
        terminal = entry - path[-1].close
        for bar in path:
            hit_stop = bar.high >= stop_price
            hit_target = bar.low <= target_price
            if hit_stop:
                first_hit = -1.0
                break
            if hit_target:
                first_hit = 1.0
                break
    path_quality = (0.40 * terminal + 0.30 * mfe - 0.55 * mae - bars[entry_index].spread_points) / average_range
    return first_hit + path_quality


def fit_archetype_model(candidates: list[Candidate], fold_id: str) -> ArchetypeModel:
    grouped: dict[str, list[float]] = defaultdict(list)
    labels: list[float] = []
    for candidate in candidates:
        if candidate.label is None:
            continue
        grouped[candidate.state_key].append(candidate.label)
        labels.append(candidate.label)
    if not labels:
        return ArchetypeModel(fold_id, 0.0, None, 0, {}, 0)
    global_mean = mean(labels) or 0.0
    global_positive_rate = sum(1 for label in labels if label > 0.0) / len(labels)
    stats: list[ArchetypeStats] = []
    for archetype_id, bucket in grouped.items():
        if len(bucket) < MIN_TRAIN_ARCHETYPE_COUNT:
            continue
        mean_label = mean(bucket) or 0.0
        positive_rate = sum(1 for label in bucket if label > 0.0) / len(bucket)
        edge_lift = mean_label - global_mean
        positive_lift = positive_rate - global_positive_rate
        activity_weight = math.log(1.0 + len(bucket) / MIN_TRAIN_ARCHETYPE_COUNT)
        score = mean_label + 0.20 * positive_lift + 0.02 * activity_weight
        if edge_lift <= 0.0 or positive_lift < -0.01:
            continue
        stats.append(
            ArchetypeStats(
                archetype_id=archetype_id,
                count=len(bucket),
                mean_label=mean_label,
                positive_rate=positive_rate,
                score=score,
            )
        )
    ordered = sorted(stats, key=lambda row: (row.score, row.count), reverse=True)
    eligible = {row.archetype_id: row for row in ordered[:TOP_ARCHETYPES_PER_FOLD]}
    return ArchetypeModel(
        fold_id=fold_id,
        global_mean=global_mean,
        global_positive_rate=global_positive_rate,
        train_candidate_count=len(labels),
        eligible_archetypes=eligible,
        observed_archetype_count=len(grouped),
    )


def score_candidate(candidate: Candidate, model: ArchetypeModel) -> Candidate:
    stat = model.eligible_archetypes.get(candidate.state_key)
    return Candidate(
        fold_id=candidate.fold_id,
        index=candidate.index,
        direction=candidate.direction,
        day=candidate.day,
        state_key=candidate.state_key,
        features=candidate.features,
        label=candidate.label,
        score=None if stat is None else stat.score,
    )


def select_daily_candidates(candidates: list[Candidate]) -> list[Candidate]:
    best_by_day_index: dict[tuple[str, int], Candidate] = {}
    for candidate in candidates:
        if candidate.score is None:
            continue
        key = (candidate.day, candidate.index)
        existing = best_by_day_index.get(key)
        if existing is None or (candidate.score or 0.0) > (existing.score or 0.0):
            best_by_day_index[key] = candidate
    grouped: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in best_by_day_index.values():
        grouped[candidate.day].append(candidate)
    selected: list[Candidate] = []
    for day_candidates in grouped.values():
        day_selected: list[Candidate] = []
        for candidate in sorted(day_candidates, key=lambda row: row.score or 0.0, reverse=True):
            if any(abs(candidate.index - prior.index) < MIN_SIGNAL_SPACING_BARS for prior in day_selected):
                continue
            day_selected.append(candidate)
            if len(day_selected) >= MAX_ENTRIES_PER_ACTIVE_DAY:
                break
        selected.extend(day_selected)
    return sorted(selected, key=lambda candidate: candidate.index)


def simulate_trades(
    bars: list[Bar],
    range_average: list[float | None],
    selected: list[Candidate],
    window: SplitWindow,
) -> list[Trade]:
    window_end_index = last_index_at_or_before(bars, window.end)
    trades: list[Trade] = []
    next_available_index = 0
    for candidate in selected:
        entry_index = candidate.index + 1
        if entry_index <= next_available_index or entry_index >= window_end_index:
            continue
        if bars[entry_index].time - bars[candidate.index].time > MAX_ENTRY_GAP:
            continue
        average_range = range_average[candidate.index]
        if average_range is None or average_range <= 0:
            continue
        trade = build_trade(bars, candidate, entry_index, average_range, window_end_index)
        if exit_close_gap_exceeds_limit(bars, trade.exit_time):
            continue
        trades.append(trade)
        next_available_index = first_index_at_or_after(bars, trade.exit_time)
    return trades


def exit_close_gap_exceeds_limit(bars: list[Bar], exit_time: datetime) -> bool:
    exit_index = first_index_at_or_after(bars, exit_time)
    if exit_index + 1 >= len(bars):
        return True
    return bars[exit_index + 1].time - bars[exit_index].time > MAX_EXIT_CLOSE_GAP


def build_trade(
    bars: list[Bar],
    candidate: Candidate,
    entry_index: int,
    average_range: float,
    window_end_index: int,
) -> Trade:
    entry_bar = bars[entry_index]
    entry_price = entry_bar.open
    direction = candidate.direction
    stop_price = round(entry_price - direction * STOP_RANGE_MULTIPLE * average_range, PRICE_DIGITS)
    target_price = round(entry_price + direction * TARGET_RANGE_MULTIPLE * average_range, PRICE_DIGITS)
    max_exit_index = min(entry_index + MAX_HOLD_BARS, window_end_index)
    exit_index = max_exit_index
    exit_price = bars[max_exit_index].close
    exit_reason = "max_hold"
    for index in range(entry_index, max_exit_index + 1):
        bar = bars[index]
        if direction > 0:
            hit_stop = bar.low <= stop_price
            hit_target = bar.high >= target_price
        else:
            hit_stop = bar.high >= stop_price
            hit_target = bar.low <= target_price
        if hit_stop:
            exit_index = index
            exit_price = stop_price
            exit_reason = "stop"
            break
        if hit_target:
            exit_index = index
            exit_price = target_price
            exit_reason = "target"
            break
    path = bars[entry_index : exit_index + 1]
    if direction > 0:
        mfe = max(bar.high - entry_price for bar in path)
        mae = max(entry_price - bar.low for bar in path)
    else:
        mfe = max(entry_price - bar.low for bar in path)
        mae = max(bar.high - entry_price for bar in path)
    pnl = direction * (exit_price - entry_price) - entry_bar.spread_points
    return Trade(
        fold_id=candidate.fold_id,
        signal_index=candidate.index,
        entry_time=entry_bar.time,
        exit_time=bars[exit_index].time,
        direction=direction,
        score=candidate.score or 0.0,
        state_key=candidate.state_key,
        entry_price=entry_price,
        exit_price=exit_price,
        stop_price=stop_price,
        target_price=target_price,
        pnl_points=pnl,
        bars_held=exit_index - entry_index + 1,
        exit_reason=exit_reason,
        mfe_points=mfe,
        mae_points=mae,
        spread_points=entry_bar.spread_points,
    )


def build_proxy_payload(
    trades: list[Trade],
    windows: dict[str, dict[str, SplitWindow]],
    fold_models: list[dict[str, object]],
    state_distributions: dict[str, dict[str, float | int | None]],
    candidates_by_fold: dict[str, dict[str, int]],
) -> dict[str, object]:
    fold_ids = sorted(windows)
    required = required_kpis(trades)
    fold_summary = grouped_summary(trades, lambda trade: trade.fold_id)
    month_summary = grouped_summary(trades, lambda trade: trade.entry_time.strftime("%Y-%m"))
    direction = direction_summary(trades)
    active_days = sorted({trade.entry_time.strftime("%Y-%m-%d") for trade in trades})
    entries_per_active_day = len(trades) / len(active_days) if active_days else None
    return {
        "schema": "axiom_rift_proxy_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": "C0004",
        "campaign_id": "C0004",
        "synthesis_id_when_applicable": None,
        "run_id": "R0001",
        "proxy_id": "PX-C0004-R0001",
        "dataset_identity": "data/processed/datasets/us100_m5_base_frame.csv",
        "split_policy": "rolling_window_test_oos_only_with_train_is_state_archetype_fit",
        "fold_ids": fold_ids,
        "proxy_engine": "axiom_rift.proxies.c0004_r0001_fold_local_state_archetype",
        "proxy_config_path": "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0001/run_manifest.json",
        "proxy_code_version_or_commit": "uncommitted_local_worktree_at_proxy_creation",
        "proxy_artifact_paths": [
            "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0001/kpi/proxy.json",
            "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0001/artifacts/c0004_r0001_proxy_trades.csv",
            "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0001/artifacts/c0004_r0001_state_archetype_summary.json",
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
            "starting_balance_usd": STARTING_BALANCE_USD,
            "net_pnl_usd": None,
            "balance_after_proxy_usd": None,
            "money_model_status": "deferred_until_mt5_symbol_spec_and_fixed_lot_size",
            "long_trade_count": direction["long"]["trade_count"],
            "short_trade_count": direction["short"]["trade_count"],
            "target_exit_count": sum(1 for trade in trades if trade.exit_reason == "target"),
            "stop_exit_count": sum(1 for trade in trades if trade.exit_reason == "stop"),
            "max_hold_exit_count": sum(1 for trade in trades if trade.exit_reason == "max_hold"),
            "average_bars_in_trade": rounded(mean([trade.bars_held for trade in trades])),
        },
        "required_kpis": required,
        "conditional_profiles": {
            "state_archetype_profile": {
                "applies": True,
                "fields": {
                    "state_fit_scope": "rolling_train_is_only",
                    "feature_count": len(FEATURE_NAMES),
                    "feature_names": list(FEATURE_NAMES),
                    "state_dimensions": list(STATE_DIMENSIONS),
                    "candidate_direction": "dual_direction_long_and_short_per_closed_bar",
                    "label_horizon_bars": LABEL_HORIZON_BARS,
                    "label_shape": "directional_target_before_stop_plus_forward_path_quality",
                    "entry_count_per_active_day_target": "5_to_10",
                    "entries_per_active_day": rounded(entries_per_active_day),
                    "max_entries_per_active_day": MAX_ENTRIES_PER_ACTIVE_DAY,
                    "min_train_archetype_count": MIN_TRAIN_ARCHETYPE_COUNT,
                    "top_archetypes_per_fold": TOP_ARCHETYPES_PER_FOLD,
                    "selection_rule": "top_fold_local_eligible_state_archetypes_per_active_day",
                    "model_family": "fold_local_state_archetype_membership",
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
                "fields": excursion_summary(trades),
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
                    "spread_point_value": SPREAD_POINT_VALUE,
                    "round_trip_cost_model": "subtract_entry_spread_once",
                    "total_spread_cost_points": rounded(sum(trade.spread_points for trade in trades)),
                    "average_spread_cost_points": rounded(mean([trade.spread_points for trade in trades])),
                    "spread_stress_test_allowed": True,
                    "slippage_stress_test_allowed": True,
                },
            },
        },
        "deferred_with_reason": [
            {
                "field": "proxy_net_pnl, proxy_max_drawdown_percent, proxy_expectancy_per_entry",
                "requirement_class": "deferred_with_reason",
                "reason": "proxy measures raw US100 index points only; USD conversion requires MT5 symbol contract, tick value, and fixed-lot discovery sizing",
                "blocking_condition": "record the matching MT5 symbol specification and fixed-lot sizing for the 500 USD account",
                "revisit_when": "during C0004 R0001 MT5 evidence production",
                "claim_boundary": {"claim_authority": False},
            },
            {
                "field": "proxy_artifact_hashes",
                "requirement_class": "deferred_with_reason",
                "reason": "self-hash is recorded in artifact_lineage after proxy.json is written",
                "blocking_condition": "proxy.json content must be stable before hashing",
                "revisit_when": "before C0004 R0001 closeout",
                "claim_boundary": {"claim_authority": False},
            },
        ],
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


def required_kpis(trades: list[Trade]) -> dict[str, int | float | None]:
    total_pnl = sum(trade.pnl_points for trade in trades)
    wins = [trade for trade in trades if trade.pnl_points > 0]
    return {
        "proxy_trade_count": len(trades),
        "proxy_signal_count": len(trades),
        "proxy_net_pnl": None,
        "proxy_profit_factor": profit_factor(trades),
        "proxy_max_drawdown_percent": None,
        "proxy_expectancy_per_entry": None,
        "proxy_win_rate": rounded(len(wins) / len(trades)) if trades else None,
        "proxy_net_pnl_points": rounded(total_pnl),
        "proxy_max_drawdown_points": max_drawdown_points(trades),
        "proxy_expectancy_points_per_entry": rounded(total_pnl / len(trades)) if trades else None,
    }


def grouped_summary(trades: list[Trade], key_fn: Callable[[Trade], str]) -> list[dict[str, object]]:
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        grouped[key_fn(trade)].append(trade)
    return [
        {
            "bucket": key,
            "trade_count": len(bucket_trades),
            "net_pnl_points": rounded(sum(trade.pnl_points for trade in bucket_trades)),
            "profit_factor": profit_factor(bucket_trades),
            "win_rate": rounded(sum(1 for trade in bucket_trades if trade.pnl_points > 0) / len(bucket_trades)),
            "max_drawdown_points": max_drawdown_points(bucket_trades),
        }
        for key, bucket_trades in sorted(grouped.items())
    ]


def direction_summary(trades: list[Trade]) -> dict[str, dict[str, int | float | None]]:
    return {
        "long": direction_bucket(trades, 1),
        "short": direction_bucket(trades, -1),
    }


def direction_bucket(trades: list[Trade], direction: int) -> dict[str, int | float | None]:
    bucket = [trade for trade in trades if trade.direction == direction]
    return {
        "trade_count": len(bucket),
        "net_pnl_points": rounded(sum(trade.pnl_points for trade in bucket)),
        "profit_factor": profit_factor(bucket),
        "win_rate": rounded(sum(1 for trade in bucket if trade.pnl_points > 0) / len(bucket)) if bucket else None,
        "max_drawdown_points": max_drawdown_points(bucket),
    }


def excursion_summary(trades: list[Trade]) -> dict[str, float | None]:
    return {
        "average_mfe_points": rounded(mean([trade.mfe_points for trade in trades])),
        "average_mae_points": rounded(mean([trade.mae_points for trade in trades])),
        "median_mfe_points": rounded(median([trade.mfe_points for trade in trades])),
        "median_mae_points": rounded(median([trade.mae_points for trade in trades])),
        "average_capture_ratio": rounded(mean(capture_ratios(trades))),
    }


def capture_ratios(trades: list[Trade]) -> list[float]:
    ratios: list[float] = []
    for trade in trades:
        if trade.mfe_points > 0:
            ratios.append(max(trade.pnl_points, 0.0) / trade.mfe_points)
    return ratios


def archetype_model_summary(model: ArchetypeModel) -> dict[str, object]:
    return {
        "fold_id": model.fold_id,
        "feature_names": list(FEATURE_NAMES),
        "state_dimensions": list(STATE_DIMENSIONS),
        "train_candidate_count": model.train_candidate_count,
        "observed_archetype_count": model.observed_archetype_count,
        "eligible_archetype_count": len(model.eligible_archetypes),
        "global_mean": rounded(model.global_mean),
        "global_positive_rate": rounded(model.global_positive_rate),
        "eligible_archetypes": [
            {
                "archetype_id": row.archetype_id,
                "count": row.count,
                "mean_label": rounded(row.mean_label),
                "positive_rate": rounded(row.positive_rate),
                "score": rounded(row.score),
            }
            for row in sorted(model.eligible_archetypes.values(), key=lambda item: item.score, reverse=True)
        ],
    }


def state_distribution(
    scored: list[Candidate],
    selected: list[Candidate],
    model: ArchetypeModel,
) -> dict[str, float | int | None]:
    scores = [candidate.score or 0.0 for candidate in scored if candidate.score is not None]
    selected_scores = [candidate.score or 0.0 for candidate in selected]
    eligible_hits = sum(1 for candidate in scored if candidate.score is not None)
    return {
        "candidate_count": len(scored),
        "eligible_candidate_count": eligible_hits,
        "eligible_candidate_rate": rounded(eligible_hits / len(scored)) if scored else None,
        "selected_count": len(selected),
        "eligible_archetype_count": len(model.eligible_archetypes),
        "score_p10": rounded(percentile(scores, 0.10)),
        "score_p50": rounded(percentile(scores, 0.50)),
        "score_p90": rounded(percentile(scores, 0.90)),
        "selected_score_min": rounded(min(selected_scores)) if selected_scores else None,
        "selected_score_max": rounded(max(selected_scores)) if selected_scores else None,
    }


def proxy_config() -> dict[str, object]:
    return {
        "bar_basis": "closed_m5",
        "entry_basis": "next_bar_open_after_scored_closed_bar",
        "evaluation_splits": "rolling_windows_test_oos",
        "training_splits": "rolling_windows_train_is",
        "candidate_direction": "dual_direction_long_and_short_per_closed_bar",
        "state_model": "fold_local_train_only_state_archetype_membership",
        "lookback_range_bars": LOOKBACK_RANGE_BARS,
        "short_range_bars": SHORT_RANGE_BARS,
        "trend_bars": TREND_BARS,
        "momentum_bars": MOMENTUM_BARS,
        "position_bars": POSITION_BARS,
        "label_horizon_bars": LABEL_HORIZON_BARS,
        "label_shape": "directional_target_before_stop_plus_path_quality",
        "min_train_archetype_count": MIN_TRAIN_ARCHETYPE_COUNT,
        "top_archetypes_per_fold": TOP_ARCHETYPES_PER_FOLD,
        "max_entries_per_active_day": MAX_ENTRIES_PER_ACTIVE_DAY,
        "min_signal_spacing_bars": MIN_SIGNAL_SPACING_BARS,
        "positive_score_gate": False,
        "stop_range_multiple": STOP_RANGE_MULTIPLE,
        "target_range_multiple": TARGET_RANGE_MULTIPLE,
        "max_hold_bars": MAX_HOLD_BARS,
        "core_session_start_minute": CORE_SESSION_START_MINUTE,
        "core_session_end_minute": CORE_SESSION_END_MINUTE,
        "same_bar_stop_target_policy": "stop_first_conservative",
        "gap_carried_entry_policy": "skip_when_next_bar_gap_exceeds_5_minutes",
        "gap_blocked_exit_policy": "skip_when_exit_bar_next_tick_gap_exceeds_5_minutes",
        "price_precision_digits": PRICE_DIGITS,
        "starting_balance_usd": STARTING_BALANCE_USD,
        "sizing_mode": "fixed_lot_discovery",
        "equity_percent_sizing": "deferred_until_candidate_quality",
        "money_conversion_status": "deferred_until_mt5_symbol_spec_and_fixed_lot_size",
    }


def write_proxy_evidence(payload: dict[str, object], trades: list[Trade]) -> None:
    RUN_DIR.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    write_trade_artifact(trades, TRADE_ARTIFACT_PATH)
    write_state_summary_artifact(payload, STATE_SUMMARY_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = sha256_file(TRADE_ARTIFACT_PATH)
    state_summary_hash = sha256_file(STATE_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, state_summary_hash)
    proxy_hash = sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, state_summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()


def write_trade_artifact(trades: list[Trade], path: Path) -> None:
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
                    "entry_time": trade.entry_time.strftime(TIME_FORMAT),
                    "exit_time": trade.exit_time.strftime(TIME_FORMAT),
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


def write_state_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_state_archetype_summary_v1",
        "template": False,
        "work_unit_id": "C0004",
        "run_id": "R0001",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "state_archetype_profile": profiles["state_archetype_profile"]["fields"],  # type: ignore[index]
        "claim_boundary": payload["claim_boundary"],
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_proxy_hashes(trade_hash: str, state_summary_hash: str) -> None:
    data = json.loads(PROXY_PATH.read_text(encoding="ascii"))
    data["proxy_artifact_hashes"] = [trade_hash, state_summary_hash]
    PROXY_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_artifact_lineage(proxy_hash: str, trade_hash: str, state_summary_hash: str) -> None:
    data = json.loads(ARTIFACT_LINEAGE_PATH.read_text(encoding="ascii"))
    records = [
        record
        for record in data.get("artifact_records", [])
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "state_archetype_summary_artifact"}
    ]
    records.extend(
        [
            {
                "artifact_id": "A-C0004-R0001-PROXY-KPI",
                "artifact_role": "proxy_kpi",
                "artifact_type": "json",
                "repo_relative_path": "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0001/kpi/proxy.json",
                "sha256": proxy_hash,
                "produced_by": "axiom_rift.proxies.c0004_r0001_fold_local_state_archetype",
                "source_inputs": [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0001/run_manifest.json",
                ],
                "linked_kpi_family": "proxy",
                "mutable": False,
                "claim_authority": False,
            },
            {
                "artifact_id": "A-C0004-R0001-PROXY-TRADES",
                "artifact_role": "proxy_trade_artifact",
                "artifact_type": "csv",
                "repo_relative_path": "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0001/artifacts/c0004_r0001_proxy_trades.csv",
                "sha256": trade_hash,
                "produced_by": "axiom_rift.proxies.c0004_r0001_fold_local_state_archetype",
                "source_inputs": [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0001/kpi/proxy.json",
                ],
                "linked_kpi_family": "proxy",
                "mutable": False,
                "claim_authority": False,
            },
            {
                "artifact_id": "A-C0004-R0001-STATE-ARCHETYPE-SUMMARY",
                "artifact_role": "state_archetype_summary_artifact",
                "artifact_type": "json",
                "repo_relative_path": "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0001/artifacts/c0004_r0001_state_archetype_summary.json",
                "sha256": state_summary_hash,
                "produced_by": "axiom_rift.proxies.c0004_r0001_fold_local_state_archetype",
                "source_inputs": [
                    "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0001/kpi/proxy.json",
                ],
                "linked_kpi_family": "proxy",
                "mutable": False,
                "claim_authority": False,
            },
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0004_r0001_mt5_logic_parity_evidence",
        }
    ]
    ARTIFACT_LINEAGE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_run_manifest_status() -> None:
    data = json.loads(RUN_MANIFEST_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_ready"
    data["gate_status"] = "proxy_recorded_pending_mt5"
    evidence = data.setdefault("evidence_paths", {})
    evidence["proxy_trade_artifact"] = "artifacts/c0004_r0001_proxy_trades.csv"
    evidence["state_archetype_summary"] = "artifacts/c0004_r0001_state_archetype_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0004_r0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0004_r0001_proxy_trades.csv",
        "artifacts/c0004_r0001_state_archetype_summary.json",
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
            "revisit_when": "after C0004 R0001 MT5 evidence files contain measured results",
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
    closeout["remaining_question"] = "produce_c0004_r0001_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    next_work = data.setdefault("next_work", {})
    completed = list(next_work.get("completed") or [])
    if "produce_c0004_r0001_proxy_evidence" not in completed:
        completed.append("produce_c0004_r0001_proxy_evidence")
    next_action = "produce_c0004_r0001_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def previous_rolling_average(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= window:
        return result
    total = sum(values[:window])
    for index in range(window, len(values)):
        if index > window:
            total += values[index - 1] - values[index - window - 1]
        result[index] = total / window
    return result


def in_core_session(timestamp: datetime) -> bool:
    minute = minute_of_day(timestamp)
    if CORE_SESSION_START_MINUTE < CORE_SESSION_END_MINUTE:
        return CORE_SESSION_START_MINUTE <= minute < CORE_SESSION_END_MINUTE
    return minute >= CORE_SESSION_START_MINUTE or minute < CORE_SESSION_END_MINUTE


def minute_of_day(timestamp: datetime) -> int:
    return timestamp.hour * 60 + timestamp.minute


def first_index_at_or_after(bars: list[Bar], timestamp: datetime) -> int:
    for index, bar in enumerate(bars):
        if bar.time >= timestamp:
            return index
    raise ValueError(f"No bar at or after {timestamp}")


def last_index_at_or_before(bars: list[Bar], timestamp: datetime) -> int:
    for index in range(len(bars) - 1, -1, -1):
        if bars[index].time <= timestamp:
            return index
    raise ValueError(f"No bar at or before {timestamp}")


def profit_factor(trades: list[Trade]) -> float | None:
    gross_profit = sum(trade.pnl_points for trade in trades if trade.pnl_points > 0)
    gross_loss = sum(trade.pnl_points for trade in trades if trade.pnl_points < 0)
    if gross_loss == 0:
        return None if gross_profit == 0 else round(gross_profit, 6)
    return rounded(gross_profit / abs(gross_loss))


def max_drawdown_points(trades: list[Trade]) -> float | None:
    if not trades:
        return None
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for trade in trades:
        equity += trade.pnl_points
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return rounded(max_drawdown)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def mean(values: list[float | int]) -> float | None:
    return None if not values else sum(values) / len(values)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
