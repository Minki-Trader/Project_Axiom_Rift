"""SC0001 SR0001 proxy evidence for negative-memory synthesis constraints."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import yaml

from axiom_rift.paths import DATA_DIR, PROJECT_ROOT


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
WORK_UNIT_DIR = PROJECT_ROOT / "campaigns" / "SC0001_accumulated_negative_memory_synthesis"
RUN_DIR = WORK_UNIT_DIR / "runs" / "SR0001"
BASE_FRAME = DATA_DIR / "processed" / "datasets" / "us100_m5_base_frame.csv"
ROLLING_WINDOWS = DATA_DIR / "processed" / "coverage_audits" / "us100_m5_rolling_windows.csv"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
RUN_MANIFEST_PATH = RUN_DIR / "run_manifest.json"
GATE_REPORT_PATH = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE_PATH = RUN_DIR / "artifact_lineage.json"
SYNTHESIS_QUEUE_PATH = WORK_UNIT_DIR / "synthesis_queue.yaml"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "sc0001_sr0001_proxy_trades.csv"
CONSTRAINT_ARTIFACT_PATH = RUN_DIR / "artifacts" / "sc0001_sr0001_constraint_summary.json"

SOURCE_INGREDIENT_IDS = (
    "c0001_ig004_execution_and_parity_lesson",
    "c0002_ig004_score_conditioned_execution_and_parity_lesson",
    "c0003_ig004_path_conditioned_execution_divergence_lesson",
    "c0003_ig005_target_frequency_is_not_edge_negative_memory",
)
FEATURE_NAMES = (
    "compression_ratio_12_over_48",
    "prior_adverse_impulse_6_over_range",
    "failure_reclaim_score",
    "spread_ratio_over_range",
    "session_position",
)
MODELING_START = datetime(2022, 5, 2, 1, 0, 0)
LOOKBACK_RANGE_BARS = 48
SQUEEZE_RANGE_BARS = 12
IMPULSE_BARS = 6
LABEL_HORIZON_BARS = 10
CANDIDATE_STRIDE_BARS = 3
MAX_ENTRIES_PER_ACTIVE_DAY = 8
MIN_ENTRY_SPACING_BARS = 3
MAX_HOLD_BARS = 7
STOP_RANGE_MULTIPLE = 0.62
TARGET_RANGE_MULTIPLE = 0.88
EARLY_GIVEBACK_BARS = 3
EARLY_GIVEBACK_RANGE_MULTIPLE = 0.15
SPREAD_POINT_VALUE = 0.01
PRICE_DIGITS = 2
CORE_SESSION_START_MINUTE = 6 * 60
CORE_SESSION_END_MINUTE = 21 * 60
MAX_ENTRY_GAP = timedelta(minutes=5)
MAX_HOLDING_GAP = timedelta(minutes=5)


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
    compression_ratio: float
    prior_adverse_impulse: float
    failure_reclaim_score: float
    spread_ratio: float
    session_position: float
    label: float | None
    score: float | None = None


@dataclass(frozen=True)
class ConstraintModel:
    fold_id: str
    compression_max: float
    prior_adverse_min: float
    reclaim_min: float
    spread_ratio_max: float
    score_min: float
    train_candidate_count: int
    train_positive_label_rate: float | None


@dataclass(frozen=True)
class Trade:
    fold_id: str
    signal_index: int
    exit_index: int
    entry_time: datetime
    exit_time: datetime
    direction: int
    score: float
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
    models: list[ConstraintModel]
    candidates_by_fold: dict[str, dict[str, int]]
    score_distributions: dict[str, dict[str, float | int | None]]


def run_sc0001_sr0001_proxy(write: bool = True) -> dict[str, object]:
    result = build_proxy_run_result()
    payload = build_proxy_payload(
        result.trades,
        result.windows,
        result.models,
        result.candidates_by_fold,
        result.score_distributions,
    )
    if write:
        write_proxy_evidence(payload, result.trades)
    return payload


def build_proxy_run_result() -> ProxyRunResult:
    bars = load_bars(BASE_FRAME)
    windows = load_windows(ROLLING_WINDOWS)
    bar_ranges = [bar.high - bar.low for bar in bars]
    average_range_48 = previous_rolling_average(bar_ranges, LOOKBACK_RANGE_BARS)
    average_range_12 = previous_rolling_average(bar_ranges, SQUEEZE_RANGE_BARS)
    trades: list[Trade] = []
    models: list[ConstraintModel] = []
    candidates_by_fold: dict[str, dict[str, int]] = {}
    score_distributions: dict[str, dict[str, float | int | None]] = {}

    for fold_id in sorted(fold for fold, splits in windows.items() if {"train_is", "test_oos"} <= set(splits)):
        split = windows[fold_id]
        train_candidates = build_candidates(
            bars,
            average_range_12,
            average_range_48,
            split["train_is"],
            fold_id,
            include_labels=True,
        )
        model = fit_constraint_model(train_candidates, fold_id)
        test_candidates = build_candidates(
            bars,
            average_range_12,
            average_range_48,
            split["test_oos"],
            fold_id,
            include_labels=False,
        )
        scored_test = [score_candidate(candidate, model) for candidate in test_candidates]
        selected = select_daily_candidates(scored_test, model)
        fold_trades = simulate_trades(bars, average_range_48, selected)
        trades.extend(fold_trades)
        models.append(model)
        candidates_by_fold[fold_id] = {
            "train_candidate_count": len(train_candidates),
            "test_candidate_count": len(test_candidates),
            "selected_signal_count": len(selected),
            "executed_trade_count": len(fold_trades),
        }
        score_distributions[fold_id] = score_distribution(scored_test, selected)

    trades.sort(key=lambda trade: (trade.entry_time, trade.fold_id, trade.signal_index))
    return ProxyRunResult(
        trades=trades,
        windows=windows,
        models=models,
        candidates_by_fold=candidates_by_fold,
        score_distributions=score_distributions,
    )


def load_proxy_trades() -> list[Trade]:
    return build_proxy_run_result().trades


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
    average_range_12: list[float | None],
    average_range_48: list[float | None],
    window: SplitWindow,
    fold_id: str,
    include_labels: bool,
) -> list[Candidate]:
    start = max(first_index_at_or_after(bars, window.start), LOOKBACK_RANGE_BARS + IMPULSE_BARS)
    end = min(last_index_at_or_before(bars, window.end), len(bars) - LABEL_HORIZON_BARS - 2)
    candidates: list[Candidate] = []
    for index in range(start, end + 1, CANDIDATE_STRIDE_BARS):
        bar = bars[index]
        if not in_core_session(bar.time):
            continue
        if bars[index + 1].time - bar.time > MAX_ENTRY_GAP:
            continue
        range_48 = average_range_48[index]
        range_12 = average_range_12[index]
        if range_48 is None or range_12 is None or range_48 <= 0:
            continue
        spread_ratio = bars[index + 1].spread_points / range_48
        session_position = session_fraction(bar.time)
        for direction in (1, -1):
            candidate = build_candidate(
                bars,
                index,
                direction,
                fold_id,
                range_12,
                range_48,
                spread_ratio,
                session_position,
                include_labels,
            )
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def build_candidate(
    bars: list[Bar],
    index: int,
    direction: int,
    fold_id: str,
    range_12: float,
    range_48: float,
    spread_ratio: float,
    session_position: float,
    include_labels: bool,
) -> Candidate | None:
    bar = bars[index]
    bar_range = max(bar.high - bar.low, 0.01)
    prior_return = bars[index - 1].close - bars[index - IMPULSE_BARS - 1].close
    prior_adverse_impulse = (-direction * prior_return) / range_48
    directional_body = direction * (bar.close - bar.open) / bar_range
    if direction == 1:
        directional_close_position = (bar.close - bar.low) / bar_range
    else:
        directional_close_position = (bar.high - bar.close) / bar_range
    directional_reclaim_return = direction * (bar.close - bars[index - 1].close) / range_48
    failure_reclaim_score = (
        0.45 * directional_body
        + 0.35 * directional_close_position
        + 0.20 * directional_reclaim_return
    )
    compression_ratio = range_12 / range_48
    if prior_adverse_impulse <= 0.05 or failure_reclaim_score <= 0.05 or spread_ratio >= 0.25:
        return None
    label = label_path_quality(bars, index + 1, direction) if include_labels else None
    return Candidate(
        fold_id=fold_id,
        index=index,
        direction=direction,
        day=bar.time.strftime("%Y-%m-%d"),
        compression_ratio=compression_ratio,
        prior_adverse_impulse=prior_adverse_impulse,
        failure_reclaim_score=failure_reclaim_score,
        spread_ratio=spread_ratio,
        session_position=session_position,
        label=label,
    )


def label_path_quality(bars: list[Bar], entry_index: int, direction: int) -> float:
    entry_price = bars[entry_index].open
    mfe = 0.0
    mae = 0.0
    for offset in range(0, LABEL_HORIZON_BARS + 1):
        bar = bars[entry_index + offset]
        if direction == 1:
            mfe = max(mfe, bar.high - entry_price)
            mae = max(mae, entry_price - bar.low)
        else:
            mfe = max(mfe, entry_price - bar.low)
            mae = max(mae, bar.high - entry_price)
    return mfe - (1.20 * mae) - bars[entry_index].spread_points


def fit_constraint_model(candidates: list[Candidate], fold_id: str) -> ConstraintModel:
    if not candidates:
        return ConstraintModel(
            fold_id=fold_id,
            compression_max=1.0,
            prior_adverse_min=0.20,
            reclaim_min=0.20,
            spread_ratio_max=0.10,
            score_min=1.0,
            train_candidate_count=0,
            train_positive_label_rate=None,
        )
    labels = [candidate.label or 0.0 for candidate in candidates]
    positive = [candidate for candidate in candidates if (candidate.label or 0.0) > 0.0]
    reference = positive if len(positive) >= 100 else candidates
    compression_max = min(
        percentile([candidate.compression_ratio for candidate in candidates], 0.55) or 1.25,
        percentile([candidate.compression_ratio for candidate in reference], 0.75) or 1.25,
    )
    prior_adverse_min = max(0.12, percentile([candidate.prior_adverse_impulse for candidate in reference], 0.30) or 0.12)
    reclaim_min = max(0.18, percentile([candidate.failure_reclaim_score for candidate in reference], 0.30) or 0.18)
    spread_ratio_max = min(0.20, percentile([candidate.spread_ratio for candidate in candidates], 0.90) or 0.20)
    provisional = ConstraintModel(
        fold_id=fold_id,
        compression_max=compression_max,
        prior_adverse_min=prior_adverse_min,
        reclaim_min=reclaim_min,
        spread_ratio_max=spread_ratio_max,
        score_min=0.0,
        train_candidate_count=len(candidates),
        train_positive_label_rate=len(positive) / len(candidates),
    )
    scored = [score_value(candidate, provisional) for candidate in candidates if passes_hard_constraints(candidate, provisional)]
    score_min = percentile(scored, 0.62) if scored else 0.0
    return ConstraintModel(
        fold_id=fold_id,
        compression_max=compression_max,
        prior_adverse_min=prior_adverse_min,
        reclaim_min=reclaim_min,
        spread_ratio_max=spread_ratio_max,
        score_min=score_min or 0.0,
        train_candidate_count=len(candidates),
        train_positive_label_rate=len(positive) / len(candidates),
    )


def score_candidate(candidate: Candidate, model: ConstraintModel) -> Candidate:
    return Candidate(
        fold_id=candidate.fold_id,
        index=candidate.index,
        direction=candidate.direction,
        day=candidate.day,
        compression_ratio=candidate.compression_ratio,
        prior_adverse_impulse=candidate.prior_adverse_impulse,
        failure_reclaim_score=candidate.failure_reclaim_score,
        spread_ratio=candidate.spread_ratio,
        session_position=candidate.session_position,
        label=candidate.label,
        score=score_value(candidate, model),
    )


def score_value(candidate: Candidate, model: ConstraintModel) -> float:
    compression_score = max(0.0, (model.compression_max - candidate.compression_ratio) / max(model.compression_max, 0.01))
    prior_score = candidate.prior_adverse_impulse / max(model.prior_adverse_min, 0.01)
    reclaim_score = candidate.failure_reclaim_score / max(model.reclaim_min, 0.01)
    spread_score = max(0.0, 1.0 - (candidate.spread_ratio / max(model.spread_ratio_max, 0.0001)))
    session_score = 1.0 - abs(candidate.session_position - 0.50)
    return (
        0.26 * compression_score
        + 0.29 * min(prior_score, 3.0)
        + 0.27 * min(reclaim_score, 3.0)
        + 0.10 * spread_score
        + 0.08 * session_score
    )


def passes_hard_constraints(candidate: Candidate, model: ConstraintModel) -> bool:
    return (
        candidate.compression_ratio <= model.compression_max
        and candidate.prior_adverse_impulse >= model.prior_adverse_min
        and candidate.failure_reclaim_score >= model.reclaim_min
        and candidate.spread_ratio <= model.spread_ratio_max
    )


def select_daily_candidates(candidates: list[Candidate], model: ConstraintModel) -> list[Candidate]:
    by_day: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        if candidate.score is None:
            continue
        if candidate.score < model.score_min or not passes_hard_constraints(candidate, model):
            continue
        by_day[candidate.day].append(candidate)

    selected: list[Candidate] = []
    for day, bucket in sorted(by_day.items()):
        del day
        used_indices: set[int] = set()
        chosen: list[Candidate] = []
        for candidate in sorted(bucket, key=lambda item: (item.score or 0.0), reverse=True):
            if len(chosen) >= MAX_ENTRIES_PER_ACTIVE_DAY:
                break
            if any(abs(candidate.index - used) < MIN_ENTRY_SPACING_BARS for used in used_indices):
                continue
            used_indices.add(candidate.index)
            chosen.append(candidate)
        selected.extend(sorted(chosen, key=lambda item: item.index))
    selected.sort(key=lambda item: (item.index, item.direction))
    return selected


def simulate_trades(
    bars: list[Bar],
    average_range_48: list[float | None],
    candidates: list[Candidate],
) -> list[Trade]:
    trades: list[Trade] = []
    last_exit_index = -1
    for candidate in sorted(candidates, key=lambda item: (item.index, -(item.score or 0.0))):
        entry_index = candidate.index + 1
        if entry_index <= last_exit_index:
            continue
        if bars[entry_index].time - bars[candidate.index].time > MAX_ENTRY_GAP:
            continue
        range_48 = average_range_48[candidate.index]
        if range_48 is None or range_48 <= 0:
            continue
        trade = simulate_trade(bars, candidate, range_48)
        trades.append(trade)
        last_exit_index = trade.exit_index
    return trades


def simulate_trade(bars: list[Bar], candidate: Candidate, range_48: float) -> Trade:
    entry_index = candidate.index + 1
    entry_bar = bars[entry_index]
    direction = candidate.direction
    entry_price = entry_bar.open
    stop_distance = STOP_RANGE_MULTIPLE * range_48
    target_distance = TARGET_RANGE_MULTIPLE * range_48
    stop_price = entry_price - direction * stop_distance
    target_price = entry_price + direction * target_distance
    mfe = 0.0
    mae = 0.0
    best_favorable = 0.0
    exit_index = min(entry_index + MAX_HOLD_BARS, len(bars) - 1)
    exit_price = bars[exit_index].close
    exit_reason = "max_hold"

    for index in range(entry_index, min(entry_index + MAX_HOLD_BARS, len(bars) - 1) + 1):
        bar = bars[index]
        if index > entry_index and bar.time - bars[index - 1].time > MAX_HOLDING_GAP:
            exit_index = index
            exit_price = bar.open
            exit_reason = "session_gap_guard_exit"
            break
        if direction == 1:
            favorable = bar.high - entry_price
            adverse = entry_price - bar.low
            stop_hit = bar.low <= stop_price
            target_hit = bar.high >= target_price
        else:
            favorable = entry_price - bar.low
            adverse = bar.high - entry_price
            stop_hit = bar.high >= stop_price
            target_hit = bar.low <= target_price
        mfe = max(mfe, favorable)
        mae = max(mae, adverse)
        best_favorable = max(best_favorable, favorable)
        if stop_hit:
            exit_index = index
            exit_price = stop_price
            exit_reason = "stop"
            break
        if target_hit:
            exit_index = index
            exit_price = target_price
            exit_reason = "target"
            break
        if index - entry_index >= EARLY_GIVEBACK_BARS and best_favorable >= target_distance * 0.45:
            current_favorable = direction * (bar.close - entry_price)
            giveback = best_favorable - current_favorable
            if giveback >= EARLY_GIVEBACK_RANGE_MULTIPLE * range_48:
                exit_index = index
                exit_price = bar.close
                exit_reason = "early_giveback"
                break

    pnl_points = direction * (exit_price - entry_price) - entry_bar.spread_points
    return Trade(
        fold_id=candidate.fold_id,
        signal_index=candidate.index,
        exit_index=exit_index,
        entry_time=entry_bar.time,
        exit_time=bars[exit_index].time,
        direction=direction,
        score=candidate.score or 0.0,
        entry_price=entry_price,
        exit_price=exit_price,
        stop_price=stop_price,
        target_price=target_price,
        pnl_points=pnl_points,
        bars_held=exit_index - entry_index + 1,
        exit_reason=exit_reason,
        mfe_points=mfe,
        mae_points=mae,
        spread_points=entry_bar.spread_points,
    )


def build_proxy_payload(
    trades: list[Trade],
    windows: dict[str, dict[str, SplitWindow]],
    models: list[ConstraintModel],
    candidates_by_fold: dict[str, dict[str, int]],
    score_distributions: dict[str, dict[str, float | int | None]],
) -> dict[str, object]:
    fold_ids = sorted(windows)
    required = required_kpis(trades)
    active_days = sorted({trade.entry_time.strftime("%Y-%m-%d") for trade in trades})
    entries_per_active_day = len(trades) / len(active_days) if active_days else None
    fold_summary = grouped_summary(trades, lambda trade: trade.fold_id)
    month_summary = grouped_summary(trades, lambda trade: trade.entry_time.strftime("%Y-%m"))
    direction = direction_summary(trades)
    return {
        "schema": "axiom_rift_proxy_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": "SC0001",
        "campaign_id": None,
        "synthesis_id_when_applicable": "SC0001",
        "run_id": "SR0001",
        "proxy_id": "PX-SC0001-SR0001",
        "dataset_identity": "data/processed/datasets/us100_m5_base_frame.csv",
        "split_policy": "rolling_window_test_oos_only_with_train_is_constraint_fit",
        "fold_ids": fold_ids,
        "proxy_engine": "axiom_rift.proxies.sc0001_sr0001_synthesis_constraints",
        "proxy_config_path": "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/run_manifest.json",
        "proxy_code_version_or_commit": "uncommitted_local_worktree_at_proxy_creation",
        "proxy_artifact_paths": [
            "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/kpi/proxy.json",
            "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/artifacts/sc0001_sr0001_proxy_trades.csv",
            "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/artifacts/sc0001_sr0001_constraint_summary.json",
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
            "early_giveback_exit_count": sum(1 for trade in trades if trade.exit_reason == "early_giveback"),
            "session_gap_guard_exit_count": sum(1 for trade in trades if trade.exit_reason == "session_gap_guard_exit"),
            "max_hold_exit_count": sum(1 for trade in trades if trade.exit_reason == "max_hold"),
            "average_bars_in_trade": rounded(mean([trade.bars_held for trade in trades])),
            "money_model_status": "deferred_until_mt5_symbol_spec_and_fixed_lot_size",
            "proxy_is_screening_gate_for_mt5": False,
        },
        "required_kpis": required,
        "conditional_profiles": {
            "synthesis_constraint_profile": {
                "applies": True,
                "fields": {
                    "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
                    "constraint_summary_artifact": "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/artifacts/sc0001_sr0001_constraint_summary.json",
                    "derived_constraints": [
                        "do_not_use_daily_entry_quota_without_train_fit_path_constraint",
                        "fit_constraints_on_train_is_only_and_score_test_oos_only",
                        "prefer_failure_reclaim_after_prior_adverse_impulse_not_continuation_or_exit_parameter_retry",
                        "block_wide_spread_and_session_gap_paths_before MT5 paired validation",
                        "treat_proxy_as_reference_surface_not_mt5_skip_gate",
                    ],
                    "adjacent_retry_disallowed": True,
                    "proxy_is_screening_gate_for_mt5": False,
                    "weak_proxy_may_skip_mt5": False,
                    "model_selected": False,
                    "feature_set_selected": False,
                    "trade_logic_selected": False,
                },
            },
            "score_surface_profile": {
                "applies": True,
                "fields": {
                    "score_type": "train_only_negative_memory_constraint_score",
                    "training_scope": "rolling_train_is_only",
                    "feature_count": len(FEATURE_NAMES),
                    "feature_names": list(FEATURE_NAMES),
                    "label_shape": "forward_path_quality_mfe_minus_adverse_and_spread",
                    "label_horizon_bars": LABEL_HORIZON_BARS,
                    "candidate_stride_bars": CANDIDATE_STRIDE_BARS,
                    "max_entries_per_active_day": MAX_ENTRIES_PER_ACTIVE_DAY,
                    "fold_models": [model_summary(model) for model in models],
                    "score_distributions": score_distributions,
                    "candidates_by_fold": candidates_by_fold,
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
            "mt5_pairing_profile": {
                "applies": True,
                "fields": {
                    "mt5_logic_parity_required_next": True,
                    "mt5_tick_required_after_logic_parity": True,
                    "fold_isolated_mt5_closeout_required": True,
                    "proxy_result_may_close_run": False,
                    "next_action": "produce_sc0001_sr0001_mt5_logic_parity_evidence",
                },
            },
        },
        "deferred_with_reason": [
            {
                "field": "proxy_net_pnl, proxy_max_drawdown_percent, proxy_expectancy_per_entry",
                "requirement_class": "deferred_with_reason",
                "reason": "proxy measures raw US100 index points only; USD conversion requires MT5 symbol contract, tick value, and fixed-lot discovery sizing",
                "blocking_condition": "record the matching MT5 symbol specification and fixed-lot sizing for the 500 USD account",
                "revisit_when": "during SC0001 SR0001 MT5 evidence production",
                "claim_boundary": {"claim_authority": False},
            },
            {
                "field": "proxy_artifact_hashes",
                "requirement_class": "deferred_with_reason",
                "reason": "self-hash is recorded in artifact_lineage after proxy.json is written",
                "blocking_condition": "proxy.json content must be stable before hashing",
                "revisit_when": "before SC0001 SR0001 closeout",
                "claim_boundary": {"claim_authority": False},
            },
        ],
        "claim_boundary": {
            "claim_authority": False,
            "selected": False,
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "runtime_probe_completed": False,
            "economics_pass": False,
            "materialization_ready": False,
            "runtime_authority": False,
            "onnx_ready": False,
            "promotion_ready": False,
            "live_ready": False,
        },
    }


def proxy_config() -> dict[str, object]:
    return {
        "bar_basis": "closed_m5",
        "entry_basis": "next_bar_open_after_scored_closed_bar",
        "evaluation_splits": "rolling_windows_test_oos",
        "training_splits": "rolling_windows_train_is",
        "candidate_direction": "dual_direction_prior_adverse_impulse_reclaim",
        "candidate_stride_bars": CANDIDATE_STRIDE_BARS,
        "lookback_range_bars": LOOKBACK_RANGE_BARS,
        "squeeze_range_bars": SQUEEZE_RANGE_BARS,
        "impulse_bars": IMPULSE_BARS,
        "label_horizon_bars": LABEL_HORIZON_BARS,
        "max_entries_per_active_day": MAX_ENTRIES_PER_ACTIVE_DAY,
        "min_entry_spacing_bars": MIN_ENTRY_SPACING_BARS,
        "max_hold_bars": MAX_HOLD_BARS,
        "stop_range_multiple": STOP_RANGE_MULTIPLE,
        "target_range_multiple": TARGET_RANGE_MULTIPLE,
        "early_giveback_bars": EARLY_GIVEBACK_BARS,
        "early_giveback_range_multiple": EARLY_GIVEBACK_RANGE_MULTIPLE,
        "core_session_start_minute": CORE_SESSION_START_MINUTE,
        "core_session_end_minute": CORE_SESSION_END_MINUTE,
        "gap_guard_policy": "skip_entry_or_exit_on_gap_greater_than_5_minutes",
        "same_bar_stop_target_policy": "stop_first_conservative",
        "price_precision_digits": PRICE_DIGITS,
        "sizing_mode": "fixed_lot_discovery",
        "equity_percent_sizing": "deferred_until_candidate_quality",
        "money_conversion_status": "deferred_until_mt5_symbol_spec_and_fixed_lot_size",
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


def model_summary(model: ConstraintModel) -> dict[str, int | float | None | str]:
    return {
        "fold_id": model.fold_id,
        "compression_max": rounded(model.compression_max),
        "prior_adverse_min": rounded(model.prior_adverse_min),
        "reclaim_min": rounded(model.reclaim_min),
        "spread_ratio_max": rounded(model.spread_ratio_max),
        "score_min": rounded(model.score_min),
        "train_candidate_count": model.train_candidate_count,
        "train_positive_label_rate": rounded(model.train_positive_label_rate),
    }


def score_distribution(scored: list[Candidate], selected: list[Candidate]) -> dict[str, float | int | None]:
    scores = [candidate.score or 0.0 for candidate in scored]
    selected_scores = [candidate.score or 0.0 for candidate in selected]
    return {
        "candidate_count": len(scored),
        "selected_count": len(selected),
        "score_p10": rounded(percentile(scores, 0.10)),
        "score_p50": rounded(percentile(scores, 0.50)),
        "score_p75": rounded(percentile(scores, 0.75)),
        "score_p90": rounded(percentile(scores, 0.90)),
        "selected_score_min": rounded(min(selected_scores)) if selected_scores else None,
        "selected_score_max": rounded(max(selected_scores)) if selected_scores else None,
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


def write_proxy_evidence(payload: dict[str, object], trades: list[Trade]) -> None:
    RUN_DIR.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    write_trade_artifact(trades, TRADE_ARTIFACT_PATH)
    write_constraint_artifact(payload, CONSTRAINT_ARTIFACT_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = sha256_file(TRADE_ARTIFACT_PATH)
    constraint_hash = sha256_file(CONSTRAINT_ARTIFACT_PATH)
    update_proxy_hashes(trade_hash, constraint_hash)
    proxy_hash = sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, constraint_hash)
    update_run_manifest_status()
    update_gate_report()
    update_synthesis_queue_after_proxy()
    update_reentry_after_proxy()


def write_trade_artifact(trades: list[Trade], path: Path) -> None:
    fields = [
        "fold_id",
        "signal_index",
        "entry_time",
        "exit_time",
        "direction",
        "score",
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


def write_constraint_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_synthesis_constraint_summary_v1",
        "template": False,
        "work_unit_id": "SC0001",
        "run_id": "SR0001",
        "created_at_utc": payload["created_at_utc"],
        "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
        "proxy_config": payload["proxy_config"],
        "synthesis_constraint_profile": profiles["synthesis_constraint_profile"]["fields"],  # type: ignore[index]
        "score_surface_profile": profiles["score_surface_profile"]["fields"],  # type: ignore[index]
        "claim_boundary": payload["claim_boundary"],
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_proxy_hashes(trade_hash: str, constraint_hash: str) -> None:
    data = json.loads(PROXY_PATH.read_text(encoding="ascii"))
    data["proxy_artifact_hashes"] = [trade_hash, constraint_hash]
    PROXY_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_artifact_lineage(proxy_hash: str, trade_hash: str, constraint_hash: str) -> None:
    data = json.loads(ARTIFACT_LINEAGE_PATH.read_text(encoding="ascii"))
    records = [
        record
        for record in data.get("artifact_records", [])
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "constraint_summary_artifact"}
    ]
    records.extend(
        [
            {
                "artifact_id": "A-SC0001-SR0001-PROXY-KPI",
                "artifact_role": "proxy_kpi",
                "artifact_type": "json",
                "repo_relative_path": "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/kpi/proxy.json",
                "sha256": proxy_hash,
                "produced_by": "axiom_rift.proxies.sc0001_sr0001_synthesis_constraints",
                "source_inputs": [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/SC0001_accumulated_negative_memory_synthesis/ingredient_refs.yaml",
                    "campaigns/SC0001_accumulated_negative_memory_synthesis/synthesis_queue.yaml",
                    "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/run_manifest.json",
                ],
                "linked_kpi_family": "proxy",
                "mutable": False,
                "claim_authority": False,
            },
            {
                "artifact_id": "A-SC0001-SR0001-PROXY-TRADES",
                "artifact_role": "proxy_trade_artifact",
                "artifact_type": "csv",
                "repo_relative_path": "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/artifacts/sc0001_sr0001_proxy_trades.csv",
                "sha256": trade_hash,
                "produced_by": "axiom_rift.proxies.sc0001_sr0001_synthesis_constraints",
                "source_inputs": [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/kpi/proxy.json",
                ],
                "linked_kpi_family": "proxy",
                "mutable": False,
                "claim_authority": False,
            },
            {
                "artifact_id": "A-SC0001-SR0001-CONSTRAINT-SUMMARY",
                "artifact_role": "constraint_summary_artifact",
                "artifact_type": "json",
                "repo_relative_path": "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/artifacts/sc0001_sr0001_constraint_summary.json",
                "sha256": constraint_hash,
                "produced_by": "axiom_rift.proxies.sc0001_sr0001_synthesis_constraints",
                "source_inputs": [
                    "campaigns/SC0001_accumulated_negative_memory_synthesis/ingredient_refs.yaml",
                    "campaigns/SC0001_accumulated_negative_memory_synthesis/synthesis_queue.yaml",
                    "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/kpi/proxy.json",
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
            "next_action": "produce_sc0001_sr0001_mt5_logic_parity_evidence",
        }
    ]
    ARTIFACT_LINEAGE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_run_manifest_status() -> None:
    data = json.loads(RUN_MANIFEST_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_ready"
    data["gate_status"] = "proxy_recorded_pending_mt5"
    evidence = data.setdefault("evidence_paths", {})
    evidence["proxy_trade_artifact"] = "artifacts/sc0001_sr0001_proxy_trades.csv"
    evidence["proxy_constraint_summary"] = "artifacts/sc0001_sr0001_constraint_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_sc0001_sr0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/sc0001_sr0001_proxy_trades.csv",
        "artifacts/sc0001_sr0001_constraint_summary.json",
        "kpi/proxy.json",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["evidence_paths"] = evidence_paths
    data["deferred_with_reason"] = [
        {
            "field": "decision",
            "reason": "proxy evidence is recorded but MT5 and proxy-vs-MT5 evidence are still missing",
            "blocking_condition": "SR0001 cannot close until mandatory MT5 logic parity, MT5 tick, execution divergence, and fold-isolated evidence are recorded",
            "revisit_when": "after SC0001 SR0001 MT5 evidence files contain measured results",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_synthesis_queue_after_proxy() -> None:
    data = yaml.safe_load(SYNTHESIS_QUEUE_PATH.read_text(encoding="ascii"))
    for item in data.get("queue", []):
        if item.get("synthesis_run_id") == "SR0001":
            item["status"] = "proxy_done"
            item["last_completed_step"] = "produce_sc0001_sr0001_proxy_evidence"
            item["next_action"] = "produce_sc0001_sr0001_mt5_logic_parity_evidence"
    SYNTHESIS_QUEUE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    next_work = data.setdefault("next_work", {})
    completed = list(next_work.get("completed") or [])
    completed_step = "produce_sc0001_sr0001_proxy_evidence"
    if completed_step not in completed:
        completed.append(completed_step)
    next_action = "produce_sc0001_sr0001_mt5_logic_parity_evidence"
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


def session_fraction(timestamp: datetime) -> float:
    minute = minute_of_day(timestamp)
    return (minute - CORE_SESSION_START_MINUTE) / max(CORE_SESSION_END_MINUTE - CORE_SESSION_START_MINUTE, 1)


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
    for trade in sorted(trades, key=lambda item: item.entry_time):
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


if __name__ == "__main__":
    proxy_payload = run_sc0001_sr0001_proxy(write=True)
    print(json.dumps(proxy_payload["proxy_summary"], indent=2, sort_keys=True))
