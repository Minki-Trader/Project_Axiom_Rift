"""C0012 R0001 proxy evidence for session auction rotation discovery."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies.common import base


CAMPAIGN_ID = "C0012"
RUN_ID = "R0001"
CAMPAIGN_ROOT = PROJECT_ROOT / "campaigns" / "C0012_session_auction_rotation_discovery"
RUN_DIR = CAMPAIGN_ROOT / "runs" / RUN_ID
CAMPAIGN_PATH = CAMPAIGN_ROOT / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0012_r0001_proxy_trades.csv"
SUMMARY_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0012_r0001_session_auction_rotation_summary.json"
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

FEATURE_NAMES = (
    "directional_value_location",
    "edge_rejection_strength",
    "edge_acceptance_strength",
    "failed_value_return_pressure",
    "rotation_count_norm",
    "balance_width_over_range",
    "balance_expansion",
    "inventory_pressure",
    "volatility_transition",
    "spread_over_range",
    "session_progress",
    "directional_body_fraction",
)
MODEL_FAMILY = "fold_local_session_auction_rotation_rank"
LABEL_SHAPE = "target_first_value_rotation_followthrough_penalized_by_adverse_first_path"
MIN_SESSION_BARS = 12
OPENING_RANGE_BARS = 6
VALUE_LOOKBACK_BARS = 24
RANGE_CONTEXT_BARS = 288
SHORT_RANGE_BARS = 48
LABEL_HORIZON_BARS = base.LABEL_HORIZON_BARS


@dataclass(frozen=True)
class LinearAuctionModel:
    fold_id: str
    feature_mean: np.ndarray
    feature_std: np.ndarray
    score_direction: np.ndarray
    feature_weights: np.ndarray
    train_candidate_count: int
    global_mean: float
    positive_label_rate: float
    label_std: float


@dataclass(frozen=True)
class SessionSnapshot:
    features: tuple[float, ...]
    state_key: str
    auction_event: str
    value_location: float
    rotation_count: int
    balance_width: float


def run_c0012_r0001_proxy(write: bool = True) -> dict[str, object]:
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


def load_proxy_trades() -> list[Trade]:
    if TRADE_ARTIFACT_PATH.exists():
        return read_trade_artifact(TRADE_ARTIFACT_PATH)
    return build_proxy_run_result().trades


def read_trade_artifact(path: Path) -> list[Trade]:
    trades: list[Trade] = []
    with path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            trades.append(
                Trade(
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
    context = build_context(bars)
    trades: list[Trade] = []
    fold_models: list[dict[str, object]] = []
    state_distributions: dict[str, dict[str, float | int | None]] = {}
    candidates_by_fold: dict[str, dict[str, int]] = {}
    for fold_id in sorted(fold_id for fold_id, split in windows.items() if {"train_is", "test_oos"} <= set(split)):
        split = windows[fold_id]
        train_candidates = build_candidates(bars, context, split["train_is"], fold_id, include_labels=True)
        model = fit_linear_auction_model(train_candidates, fold_id)
        test_candidates = build_candidates(bars, context, split["test_oos"], fold_id, include_labels=False)
        scored_candidates = score_candidates(test_candidates, model)
        selected = base.select_daily_candidates(scored_candidates)
        fold_trades = base.simulate_trades(bars, context["range_48"], selected, split["test_oos"])
        trades.extend(fold_trades)
        fold_models.append(linear_model_summary(model))
        state_distributions[fold_id] = auction_distribution(scored_candidates, selected, fold_trades, model)
        candidates_by_fold[fold_id] = {
            "train_candidate_count": len(train_candidates),
            "test_candidate_count": len(test_candidates),
            "eligible_candidate_count": sum(1 for candidate in scored_candidates if candidate.score is not None),
            "selected_candidate_count": len(selected),
            "proxy_trade_count": len(fold_trades),
            "feature_count": len(FEATURE_NAMES),
        }
    return base.ProxyRunResult(
        trades=trades,
        windows=windows,
        fold_models=fold_models,
        state_distributions=state_distributions,
        candidates_by_fold=candidates_by_fold,
    )


def build_context(bars: list[base.Bar]) -> dict[str, list[Any]]:
    ranges = [max(bar.high - bar.low, 0.0) for bar in bars]
    spreads = [bar.spread_points for bar in bars]
    range_48 = base.previous_rolling_average(ranges, SHORT_RANGE_BARS)
    range_288 = base.previous_rolling_average(ranges, RANGE_CONTEXT_BARS)
    spread_48 = base.previous_rolling_average(spreads, SHORT_RANGE_BARS)
    session_bars: list[int] = [0] * len(bars)
    session_open: list[float | None] = [None] * len(bars)
    opening_high: list[float | None] = [None] * len(bars)
    opening_low: list[float | None] = [None] * len(bars)
    session_high: list[float | None] = [None] * len(bars)
    session_low: list[float | None] = [None] * len(bars)
    value_mid: list[float | None] = [None] * len(bars)
    value_width: list[float | None] = [None] * len(bars)
    rotation_count: list[int] = [0] * len(bars)
    last_day = ""
    day_open = 0.0
    day_high = 0.0
    day_low = 0.0
    open_high = 0.0
    open_low = 0.0
    closes: list[float] = []
    rotations = 0
    last_side = 0
    count = 0
    for index, bar in enumerate(bars):
        day = bar.time.strftime("%Y-%m-%d")
        if day != last_day:
            last_day = day
            day_open = bar.open
            day_high = bar.high
            day_low = bar.low
            open_high = bar.high
            open_low = bar.low
            closes = []
            rotations = 0
            last_side = 0
            count = 0
        count += 1
        if count <= OPENING_RANGE_BARS:
            open_high = max(open_high, bar.high)
            open_low = min(open_low, bar.low)
        prior_closes = closes[-VALUE_LOOKBACK_BARS:] or [bar.close]
        mid = sum(prior_closes) / len(prior_closes)
        width = max(day_high - day_low, open_high - open_low, 1e-9)
        side = 1 if bar.close > mid else -1 if bar.close < mid else last_side
        if last_side and side and side != last_side:
            rotations += 1
        session_bars[index] = count
        session_open[index] = day_open
        opening_high[index] = open_high
        opening_low[index] = open_low
        session_high[index] = day_high
        session_low[index] = day_low
        value_mid[index] = mid
        value_width[index] = width
        rotation_count[index] = rotations
        closes.append(bar.close)
        day_high = max(day_high, bar.high)
        day_low = min(day_low, bar.low)
        last_side = side
    return {
        "range_48": range_48,
        "range_288": range_288,
        "spread_48": spread_48,
        "session_bars": session_bars,
        "session_open": session_open,
        "opening_high": opening_high,
        "opening_low": opening_low,
        "session_high": session_high,
        "session_low": session_low,
        "value_mid": value_mid,
        "value_width": value_width,
        "rotation_count": rotation_count,
    }


def build_candidates(
    bars: list[base.Bar],
    context: dict[str, list[Any]],
    window: SplitWindow,
    fold_id: str,
    include_labels: bool,
) -> list[base.Candidate]:
    start_index = max(
        base.first_index_at_or_after(bars, window.start),
        RANGE_CONTEXT_BARS,
        VALUE_LOOKBACK_BARS,
        LABEL_HORIZON_BARS,
    )
    end_index = min(base.last_index_at_or_before(bars, window.end), len(bars) - LABEL_HORIZON_BARS - 2)
    candidates: list[base.Candidate] = []
    for index in range(start_index, end_index + 1):
        if not base.in_core_session(bars[index].time):
            continue
        if int(context["session_bars"][index]) < MIN_SESSION_BARS:
            continue
        for direction in (1, -1):
            snapshot = session_auction_snapshot(bars, context, index, direction)
            if snapshot is None:
                continue
            label = auction_label(bars, context, index, direction, snapshot) if include_labels else None
            candidates.append(
                base.Candidate(
                    fold_id=fold_id,
                    index=index,
                    direction=direction,
                    day=bars[index].time.strftime("%Y-%m-%d"),
                    state_key=snapshot.state_key,
                    features=snapshot.features,
                    label=label,
                )
            )
    return candidates


def session_auction_snapshot(
    bars: list[base.Bar],
    context: dict[str, list[Any]],
    index: int,
    direction: int,
) -> SessionSnapshot | None:
    range_48 = context["range_48"][index]
    range_288 = context["range_288"][index]
    spread_48 = context["spread_48"][index]
    value_mid = context["value_mid"][index]
    value_width = context["value_width"][index]
    session_open = context["session_open"][index]
    session_high = context["session_high"][index]
    session_low = context["session_low"][index]
    if (
        range_48 is None
        or range_288 is None
        or spread_48 is None
        or value_mid is None
        or value_width is None
        or session_open is None
        or session_high is None
        or session_low is None
        or min(float(range_48), float(range_288), float(value_width)) <= 0.0
    ):
        return None
    bar = bars[index]
    previous = bars[index - 1]
    edge_distance = 0.50 * float(value_width)
    upper_edge = float(value_mid) + edge_distance
    lower_edge = float(value_mid) - edge_distance
    edge = upper_edge if direction > 0 else lower_edge
    opposite_edge = lower_edge if direction > 0 else upper_edge
    value_location_long = (bar.close - lower_edge) / max(float(value_width), 1e-9)
    directional_value_location = value_location_long if direction > 0 else 1.0 - value_location_long
    edge_rejection = edge_rejection_strength(bar, lower_edge, upper_edge, direction, float(range_48))
    edge_acceptance = direction * (bar.close - edge) / float(range_48)
    previous_acceptance = direction * (previous.close - edge) / float(range_48)
    failed_return = max(0.0, direction * (opposite_edge - bar.close) / float(range_48))
    rotation_norm = min(float(context["rotation_count"][index]) / 8.0, 2.0)
    session_width = max(float(session_high) - float(session_low), float(value_width))
    balance_width_over_range = session_width / float(range_48)
    opening_width = max(float(context["opening_high"][index]) - float(context["opening_low"][index]), 1e-9)
    balance_expansion = session_width / max(opening_width, 1e-9)
    inventory_pressure = direction * (bar.close - float(session_open)) / float(range_48)
    volatility_transition = (float(range_48) / max(float(range_288), 1e-9)) - 1.0
    spread_over_range = bar.spread_points / float(range_48)
    session_progress = core_session_progress(bar.time)
    body_fraction = direction * (bar.close - bar.open) / max(bar.high - bar.low, 1e-9)
    event = auction_event(
        edge_rejection,
        edge_acceptance,
        previous_acceptance,
        failed_return,
        directional_value_location,
        rotation_norm,
        inventory_pressure,
    )
    if event == "none":
        return None
    if spread_over_range > 1.50 or balance_width_over_range > 20.0:
        return None
    features = (
        clamp(directional_value_location, -2.0, 3.0),
        edge_rejection,
        edge_acceptance,
        failed_return,
        rotation_norm,
        balance_width_over_range,
        balance_expansion,
        inventory_pressure,
        volatility_transition,
        spread_over_range,
        session_progress,
        body_fraction,
    )
    return SessionSnapshot(
        features=features,
        state_key=auction_state_key(direction, event, directional_value_location, rotation_norm, balance_expansion, session_progress),
        auction_event=event,
        value_location=directional_value_location,
        rotation_count=int(context["rotation_count"][index]),
        balance_width=session_width,
    )


def edge_rejection_strength(bar: base.Bar, lower_edge: float, upper_edge: float, direction: int, average_range: float) -> float:
    if direction > 0:
        touch = max(0.0, lower_edge - bar.low) / average_range
        close_back = max(0.0, bar.close - lower_edge) / average_range
    else:
        touch = max(0.0, bar.high - upper_edge) / average_range
        close_back = max(0.0, upper_edge - bar.close) / average_range
    return min(touch + 0.65 * close_back, 3.0)


def auction_event(
    edge_rejection: float,
    edge_acceptance: float,
    previous_acceptance: float,
    failed_return: float,
    directional_value_location: float,
    rotation_norm: float,
    inventory_pressure: float,
) -> str:
    if edge_rejection >= 0.08 and directional_value_location < 0.55:
        return "edge_rejection"
    if edge_acceptance >= 0.16 and previous_acceptance > -0.08:
        return "edge_acceptance"
    if failed_return >= 0.22 and directional_value_location < 0.20:
        return "failed_value_return"
    if abs(inventory_pressure) >= 0.20 and 0.10 <= directional_value_location <= 1.60:
        return "inventory_pressure"
    return "value_rotation"


def auction_label(
    bars: list[base.Bar],
    context: dict[str, list[Any]],
    index: int,
    direction: int,
    snapshot: SessionSnapshot,
) -> float | None:
    entry_index = index + 1
    exit_index = min(index + LABEL_HORIZON_BARS, len(bars) - 1)
    average_range = context["range_48"][index]
    if average_range is None or average_range <= 0.0 or entry_index >= exit_index:
        return None
    entry = bars[entry_index].open
    path = bars[entry_index : exit_index + 1]
    stop_distance = base.STOP_RANGE_MULTIPLE * average_range
    target_distance = base.TARGET_RANGE_MULTIPLE * average_range
    stop_price = entry - direction * stop_distance
    target_price = entry + direction * target_distance
    first_hit = 0.0
    event_bar = len(path)
    first_favorable_bar = len(path)
    first_adverse_bar = len(path)
    if direction > 0:
        mfe = max(bar.high - entry for bar in path)
        mae = max(entry - bar.low for bar in path)
        terminal = path[-1].close - entry
        aligned_close_count = sum(1 for bar in path if bar.close >= entry)
        for offset, bar in enumerate(path, start=1):
            if first_favorable_bar == len(path) and bar.high - entry >= 0.35 * average_range:
                first_favorable_bar = offset
            if first_adverse_bar == len(path) and entry - bar.low >= 0.30 * average_range:
                first_adverse_bar = offset
            if bar.low <= stop_price:
                first_hit = -1.0
                event_bar = offset
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
            if first_favorable_bar == len(path) and entry - bar.low >= 0.35 * average_range:
                first_favorable_bar = offset
            if first_adverse_bar == len(path) and bar.high - entry >= 0.30 * average_range:
                first_adverse_bar = offset
            if bar.high >= stop_price:
                first_hit = -1.0
                event_bar = offset
                break
            if bar.low <= target_price:
                first_hit = 1.0
                event_bar = offset
                break
    favorable = mfe / average_range
    adverse = mae / average_range
    terminal_norm = terminal / average_range
    target_speed = (len(path) - event_bar + 1) / len(path) if first_hit > 0.0 else 0.0
    stop_speed = (len(path) - event_bar + 1) / len(path) if first_hit < 0.0 else 0.0
    favorable_delay = first_favorable_bar / len(path)
    adverse_first_penalty = 1.0 if first_adverse_bar < first_favorable_bar else 0.0
    path_alignment = aligned_close_count / len(path)
    spread_norm = bars[entry_index].spread_points / average_range
    rotation_bonus = min(snapshot.rotation_count / 8.0, 1.0)
    event_bonus = {"edge_rejection": 0.14, "edge_acceptance": 0.08, "failed_value_return": -0.02}.get(snapshot.auction_event, 0.0)
    return (
        1.08 * first_hit
        + 0.34 * target_speed
        - 0.46 * stop_speed
        + 0.28 * favorable
        + 0.20 * terminal_norm
        + 0.16 * (path_alignment - 0.5)
        + 0.10 * rotation_bonus
        + event_bonus
        - 0.55 * adverse
        - 0.36 * favorable_delay
        - 0.42 * adverse_first_penalty
        - 0.62 * spread_norm
    )


def fit_linear_auction_model(candidates: list[base.Candidate], fold_id: str) -> LinearAuctionModel:
    labeled = [candidate for candidate in candidates if candidate.label is not None]
    feature_count = len(FEATURE_NAMES)
    if not labeled:
        return LinearAuctionModel(
            fold_id=fold_id,
            feature_mean=np.zeros(feature_count, dtype=float),
            feature_std=np.ones(feature_count, dtype=float),
            score_direction=np.zeros(feature_count, dtype=float),
            feature_weights=np.ones(feature_count, dtype=float),
            train_candidate_count=0,
            global_mean=0.0,
            positive_label_rate=0.0,
            label_std=0.0,
        )
    matrix = np.array([candidate.features for candidate in labeled], dtype=float)
    labels = np.array([float(candidate.label or 0.0) for candidate in labeled], dtype=float)
    feature_mean = matrix.mean(axis=0)
    feature_std = matrix.std(axis=0)
    feature_std = np.where(feature_std < 1e-9, 1.0, feature_std)
    standardized = (matrix - feature_mean) / feature_std
    centered_labels = labels - labels.mean()
    label_std = float(labels.std())
    if label_std < 1e-9:
        score_direction = np.zeros(feature_count, dtype=float)
    else:
        score_direction = (standardized * centered_labels[:, None]).mean(axis=0) / label_std
    strength = np.abs(score_direction)
    feature_weights = np.clip(strength / max(float(strength.mean()), 1e-9), 0.25, 2.5)
    return LinearAuctionModel(
        fold_id=fold_id,
        feature_mean=feature_mean,
        feature_std=feature_std,
        score_direction=score_direction,
        feature_weights=feature_weights,
        train_candidate_count=len(labeled),
        global_mean=float(labels.mean()),
        positive_label_rate=float(np.mean(labels > 0.0)),
        label_std=label_std,
    )


def score_candidates(candidates: list[base.Candidate], model: LinearAuctionModel) -> list[base.Candidate]:
    scored: list[base.Candidate] = []
    for candidate in candidates:
        vector = np.array(candidate.features, dtype=float)
        standardized = (vector - model.feature_mean) / model.feature_std
        score = float(model.global_mean + np.dot(standardized, model.score_direction * model.feature_weights))
        scored.append(
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
    return scored


def build_proxy_payload(
    trades: list[Trade],
    windows: dict[str, dict[str, SplitWindow]],
    fold_models: list[dict[str, object]],
    state_distributions: dict[str, dict[str, float | int | None]],
    candidates_by_fold: dict[str, dict[str, int]],
) -> dict[str, object]:
    fold_ids = sorted(fold_id for fold_id in windows if fold_id != "tail")
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
        "proxy_id": "PX-C0012-R0001",
        "dataset_identity": "us100_m5_base_frame_sha256_80938f8f37fa0ef4fff7c2b5adfe45186153bc0bbc54d7544fec3d44e2c34ee3",
        "split_policy": "rolling_window_test_oos_only_with_train_is_session_auction_fit",
        "fold_ids": fold_ids,
        "proxy_engine": "axiom_rift.proxies.c0012_r0001_session_auction_rotation",
        "proxy_config_path": "campaigns/C0012_session_auction_rotation_discovery/runs/R0001/run_manifest.json",
        "proxy_code_version_or_commit": "uncommitted_local_worktree_at_proxy_creation",
        "proxy_artifact_paths": [
            "campaigns/C0012_session_auction_rotation_discovery/runs/R0001/kpi/proxy.json",
            "campaigns/C0012_session_auction_rotation_discovery/runs/R0001/artifacts/c0012_r0001_proxy_trades.csv",
            "campaigns/C0012_session_auction_rotation_discovery/runs/R0001/artifacts/c0012_r0001_session_auction_rotation_summary.json"
        ],
        "proxy_artifact_hashes": [],
        "proxy_config": proxy_config(),
        "proxy_summary": {
            "evaluation_surface": "rolling_window_test_oos_only",
            "trade_count": required["proxy_trade_count"],
            "signal_count": required["proxy_signal_count"],
            "active_day_count": len(active_days),
            "entries_per_active_day": base.rounded(entries_per_active_day),
            "entry_target_min": 5,
            "entry_target_max": 10,
            "gross_profit_points": base.rounded(sum(trade.pnl_points for trade in trades if trade.pnl_points > 0)),
            "gross_loss_points": base.rounded(sum(trade.pnl_points for trade in trades if trade.pnl_points < 0)),
            "net_pnl_points": base.rounded(sum(trade.pnl_points for trade in trades)),
            "starting_balance_usd": base.STARTING_BALANCE_USD,
            "net_pnl_usd": None,
            "balance_after_proxy_usd": None,
            "money_model_status": "deferred_until_mt5_symbol_spec_and_fixed_lot_size",
            "long_trade_count": direction["long"]["trade_count"],
            "short_trade_count": direction["short"]["trade_count"],
            "target_exit_count": sum(1 for trade in trades if trade.exit_reason == "target"),
            "stop_exit_count": sum(1 for trade in trades if trade.exit_reason == "stop"),
            "max_hold_exit_count": sum(1 for trade in trades if trade.exit_reason == "max_hold"),
            "average_bars_in_trade": base.rounded(base.mean([trade.bars_held for trade in trades])),
        },
        "required_kpis": required,
        "conditional_profiles": {
            "session_auction_rotation_profile": {
                "applies": True,
                "fields": {
                    "state_fit_scope": "rolling_train_is_only",
                    "feature_count": len(FEATURE_NAMES),
                    "feature_names": list(FEATURE_NAMES),
                    "candidate_direction": "dual_direction_long_and_short_session_auction_events",
                    "label_horizon_bars": LABEL_HORIZON_BARS,
                    "label_shape": LABEL_SHAPE,
                    "entry_count_per_active_day_target": "5_to_10",
                    "entries_per_active_day": base.rounded(entries_per_active_day),
                    "max_entries_per_active_day": base.MAX_ENTRIES_PER_ACTIVE_DAY,
                    "selection_rule": "top_fold_local_session_auction_rotation_scores_per_active_day",
                    "model_family": MODEL_FAMILY,
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
                    "total_spread_cost_points": base.rounded(sum(trade.spread_points for trade in trades)),
                    "average_spread_cost_points": base.rounded(base.mean([trade.spread_points for trade in trades])),
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
                "revisit_when": "during C0012 R0001 MT5 evidence production",
                "claim_boundary": {"claim_authority": False},
            }
        ],
        "claim_boundary": {
            "claim_authority": False,
            "selected": False,
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "trade_logic_selected": False,
            "runtime_authority": False,
            "onnx_ready": False,
            "promotion_ready": False,
            "live_ready": False,
        },
    }


def write_proxy_evidence(payload: dict[str, object], trades: list[Trade]) -> None:
    RUN_DIR.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    RUN_DIR.joinpath("kpi").mkdir(parents=True, exist_ok=True)
    base.write_trade_artifact(trades, TRADE_ARTIFACT_PATH)
    write_summary_artifact(payload, SUMMARY_ARTIFACT_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = base.sha256_file(TRADE_ARTIFACT_PATH)
    summary_hash = base.sha256_file(SUMMARY_ARTIFACT_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = base.sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_after_proxy()
    update_gate_report_after_proxy()
    update_campaign_after_proxy()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)
    update_decision_cursor_after_proxy()


def write_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_session_auction_rotation_summary_v1",
        "template": False,
        "work_unit_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "run_id": RUN_ID,
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "session_auction_rotation_profile": profiles["session_auction_rotation_profile"]["fields"],  # type: ignore[index]
        "claim_boundary": payload["claim_boundary"],
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_proxy_hashes(trade_hash: str, summary_hash: str) -> None:
    data = json.loads(PROXY_PATH.read_text(encoding="ascii"))
    data["proxy_artifact_hashes"] = [trade_hash, summary_hash]
    PROXY_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_artifact_lineage(proxy_hash: str, trade_hash: str, summary_hash: str) -> None:
    data = json.loads(ARTIFACT_LINEAGE_PATH.read_text(encoding="ascii"))
    records = [
        record
        for record in data.get("artifact_records", [])
        if record.get("artifact_role")
        not in {"proxy_kpi", "proxy_trade_artifact", "session_auction_rotation_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-C0012-R0001-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0012_session_auction_rotation_discovery/runs/R0001/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0012_session_auction_rotation_discovery/runs/R0001/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-C0012-R0001-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0012_session_auction_rotation_discovery/runs/R0001/artifacts/c0012_r0001_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0012_session_auction_rotation_discovery/runs/R0001/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0012-R0001-SESSION-AUCTION-ROTATION-SUMMARY",
                "session_auction_rotation_summary_artifact",
                "json",
                "campaigns/C0012_session_auction_rotation_discovery/runs/R0001/artifacts/c0012_r0001_session_auction_rotation_summary.json",
                summary_hash,
                ["campaigns/C0012_session_auction_rotation_discovery/runs/R0001/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0012_r0001_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0012_r0001_session_auction_rotation",
        "source_inputs": source_inputs,
        "linked_kpi_family": "proxy",
        "mutable": False,
        "claim_authority": False,
    }


def update_run_manifest_after_proxy() -> None:
    data = json.loads(RUN_MANIFEST_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_ready"
    data["gate_status"] = "proxy_recorded_pending_mt5"
    evidence = data.setdefault("evidence_paths", {})
    evidence["proxy_trade_artifact"] = "artifacts/c0012_r0001_proxy_trades.csv"
    evidence["session_auction_rotation_summary"] = "artifacts/c0012_r0001_session_auction_rotation_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report_after_proxy() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0012_r0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0012_r0001_proxy_trades.csv",
        "artifacts/c0012_r0001_session_auction_rotation_summary.json",
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
            "revisit_when": "after C0012 R0001 MT5 evidence files contain measured results",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_campaign_after_proxy() -> None:
    data = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = "runs/R0001"
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["run_id"] = RUN_ID
    next_candidate["direction"] = "produce_c0012_r0001_mt5_logic_parity_evidence"
    next_candidate["reason"] = "R0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0012_r0001_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    data = yaml.safe_load(REENTRY_PATH.read_text(encoding="ascii"))
    next_work = data.setdefault("next_work", {})
    completed = list(next_work.get("completed") or [])
    for item in (
        "design_c0012_r0001_session_auction_rotation_run",
        "open_c0012_r0001_session_auction_rotation_run",
        "produce_c0012_r0001_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_c0012_r0001_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_run"] = "campaigns/C0012_session_auction_rotation_discovery/runs/R0001"
    REENTRY_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0012_session_auction_rotation_discovery"
    data["active_run"] = "campaigns/C0012_session_auction_rotation_discovery/runs/R0001"
    data["latest_operation"] = {
        "id": "produce_c0012_r0001_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0012_session_auction_rotation_discovery/runs/R0001/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0012_r0001_mt5_logic_parity_evidence",
        "claim_boundary": {
            "claim_authority": False,
            "selected": False,
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "trade_logic_selected": False,
            "runtime_probe_completed": False,
            "economics_pass": False,
            "materialization_ready": False,
            "runtime_authority": False,
            "onnx_ready": False,
            "promotion_ready": False,
            "live_ready": False,
        },
    }
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_decision_cursor_after_proxy() -> None:
    data = yaml.safe_load(DECISION_CURSOR_PATH.read_text(encoding="ascii"))
    data["canonical_source"] = "campaigns/C0012_session_auction_rotation_discovery/runs/R0001/kpi/proxy.json"
    data["canonical_status"] = "proxy_recorded_pending_mt5"
    data["current_decision"] = "produce_c0012_r0001_mt5_logic_parity_evidence"
    data["active_run"] = "campaigns/C0012_session_auction_rotation_discovery/runs/R0001"
    data["next_required_action"] = "produce_c0012_r0001_mt5_logic_parity_evidence"
    current = data.setdefault("current_evidence_summary", {})
    current["source_run"] = "campaigns/C0012_session_auction_rotation_discovery/runs/R0001"
    current["current_task"] = "produce_c0012_r0001_mt5_logic_parity_evidence"
    current["run_terminal_receipt_available"] = False
    current["note"] = "proxy_recorded_and_mandatory_mt5_paired_validation_next"
    DECISION_CURSOR_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def linear_model_summary(model: LinearAuctionModel) -> dict[str, object]:
    return {
        "fold_id": model.fold_id,
        "model_family": MODEL_FAMILY,
        "feature_names": list(FEATURE_NAMES),
        "train_candidate_count": model.train_candidate_count,
        "global_mean": base.rounded(model.global_mean),
        "positive_label_rate": base.rounded(model.positive_label_rate),
        "label_std": base.rounded(model.label_std),
        "feature_weights": [base.rounded(float(value)) for value in model.feature_weights],
        "score_direction": [base.rounded(float(value)) for value in model.score_direction],
        "feature_mean": [base.rounded(float(value)) for value in model.feature_mean],
        "feature_std": [base.rounded(float(value)) for value in model.feature_std],
        "score_interpretation": "higher_score_means_fold_local_session_auction_rotation_quality",
    }


def auction_distribution(
    scored: list[base.Candidate],
    selected: list[base.Candidate],
    trades: list[Trade],
    model: LinearAuctionModel,
) -> dict[str, float | int | None]:
    scores = [candidate.score or 0.0 for candidate in scored if candidate.score is not None]
    selected_scores = [candidate.score or 0.0 for candidate in selected]
    event_counts: dict[str, int] = {}
    selected_event_counts: dict[str, int] = {}
    for candidate in scored:
        event = parse_auction_event(candidate.state_key)
        event_counts[event] = event_counts.get(event, 0) + 1
    for candidate in selected:
        event = parse_auction_event(candidate.state_key)
        selected_event_counts[event] = selected_event_counts.get(event, 0) + 1
    eligible_hits = sum(1 for candidate in scored if candidate.score is not None)
    return {
        "candidate_count": len(scored),
        "eligible_candidate_count": eligible_hits,
        "eligible_candidate_rate": base.rounded(eligible_hits / len(scored)) if scored else None,
        "selected_count": len(selected),
        "proxy_trade_count": len(trades),
        "train_candidate_count": model.train_candidate_count,
        "score_p10": base.rounded(base.percentile(scores, 0.10)),
        "score_p50": base.rounded(base.percentile(scores, 0.50)),
        "score_p90": base.rounded(base.percentile(scores, 0.90)),
        "selected_score_min": base.rounded(min(selected_scores)) if selected_scores else None,
        "selected_score_max": base.rounded(max(selected_scores)) if selected_scores else None,
        "edge_rejection_candidate_count": event_counts.get("edge_rejection", 0),
        "edge_acceptance_candidate_count": event_counts.get("edge_acceptance", 0),
        "failed_value_return_candidate_count": event_counts.get("failed_value_return", 0),
        "value_rotation_candidate_count": event_counts.get("value_rotation", 0),
        "inventory_pressure_candidate_count": event_counts.get("inventory_pressure", 0),
        "selected_edge_rejection_count": selected_event_counts.get("edge_rejection", 0),
        "selected_edge_acceptance_count": selected_event_counts.get("edge_acceptance", 0),
        "selected_failed_value_return_count": selected_event_counts.get("failed_value_return", 0),
        "selected_value_rotation_count": selected_event_counts.get("value_rotation", 0),
        "selected_inventory_pressure_count": selected_event_counts.get("inventory_pressure", 0),
    }


def proxy_config() -> dict[str, object]:
    return {
        "bar_basis": "closed_m5",
        "entry_basis": "next_bar_open_after_scored_closed_bar",
        "evaluation_splits": "rolling_windows_test_oos",
        "training_splits": "rolling_windows_train_is",
        "candidate_direction": "dual_direction_session_auction_events",
        "model_family": MODEL_FAMILY,
        "feature_names": list(FEATURE_NAMES),
        "label_shape": LABEL_SHAPE,
        "min_session_bars": MIN_SESSION_BARS,
        "opening_range_bars": OPENING_RANGE_BARS,
        "value_lookback_bars": VALUE_LOOKBACK_BARS,
        "range_context_bars": RANGE_CONTEXT_BARS,
        "label_horizon_bars": LABEL_HORIZON_BARS,
        "max_entries_per_active_day": base.MAX_ENTRIES_PER_ACTIVE_DAY,
        "min_signal_spacing_bars": base.MIN_SIGNAL_SPACING_BARS,
        "stop_range_multiple": base.STOP_RANGE_MULTIPLE,
        "target_range_multiple": base.TARGET_RANGE_MULTIPLE,
        "max_hold_bars": base.MAX_HOLD_BARS,
        "core_session_start_minute": base.CORE_SESSION_START_MINUTE,
        "core_session_end_minute": base.CORE_SESSION_END_MINUTE,
        "same_bar_stop_target_policy": "stop_first_conservative",
        "gap_carried_entry_policy": "skip_when_next_bar_gap_exceeds_5_minutes",
        "gap_blocked_exit_policy": "skip_when_exit_bar_next_tick_gap_exceeds_5_minutes",
        "price_precision_digits": base.PRICE_DIGITS,
        "starting_balance_usd": base.STARTING_BALANCE_USD,
        "sizing_mode": "fixed_lot_discovery",
        "equity_percent_sizing": "deferred_until_candidate_quality",
        "money_conversion_status": "deferred_until_mt5_symbol_spec_and_fixed_lot_size",
    }


def auction_state_key(
    direction: int,
    event: str,
    directional_value_location: float,
    rotation_norm: float,
    balance_expansion: float,
    session_progress: float,
) -> str:
    side = "long" if direction > 0 else "short"
    value = bucket(directional_value_location, 0.35, 0.95, "opposite_value", "inside_value", "beyond_edge")
    rotation = bucket(rotation_norm, 0.30, 0.85, "low_rotation", "mid_rotation", "high_rotation")
    expansion = bucket(balance_expansion, 1.35, 2.30, "balanced", "expanding", "wide_balance")
    session = bucket(session_progress, 0.25, 0.70, "early_session", "middle_session", "late_session")
    return f"{side}|event_{event}|{value}|{rotation}|{expansion}|{session}"


def parse_auction_event(state_key: str) -> str:
    for part in state_key.split("|"):
        if part.startswith("event_"):
            return part.replace("event_", "", 1)
    return "unknown"


def bucket(value: float, low: float, high: float, low_name: str, mid_name: str, high_name: str) -> str:
    if value < low:
        return low_name
    if value < high:
        return mid_name
    return high_name


def core_session_progress(timestamp: datetime) -> float:
    minute = base.minute_of_day(timestamp)
    span = max(base.CORE_SESSION_END_MINUTE - base.CORE_SESSION_START_MINUTE, 1)
    return clamp((minute - base.CORE_SESSION_START_MINUTE) / span, 0.0, 1.0)


def clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
