"""C0006 R0005 proxy evidence for reclaim retest rejection events."""

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


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0006_liquidity_sweep_reclaim_event_discovery" / "runs" / "R0005"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0006_liquidity_sweep_reclaim_event_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0006_r0005_proxy_trades.csv"
EVENT_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0006_r0005_reclaim_retest_rejection_summary.json"
RUN_MANIFEST_PATH = RUN_DIR / "run_manifest.json"
GATE_REPORT_PATH = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE_PATH = RUN_DIR / "artifact_lineage.json"
CLAIM_STATE_PATH = PROJECT_ROOT / "registries" / "claim_state.yaml"
BASE_FRAME = base.BASE_FRAME
ROLLING_WINDOWS = base.ROLLING_WINDOWS
SplitWindow = base.SplitWindow
Trade = base.Trade
load_bars = base.load_bars
load_windows = base.load_windows

FEATURE_NAMES = (
    "sweep_depth_over_range",
    "reclaim_close_depth_over_range",
    "retest_delay_bars",
    "retest_touch_gap_over_range",
    "retest_overshoot_over_range",
    "retest_rejection_depth_over_range",
    "retest_rejection_wick_fraction",
    "retest_body_fraction",
    "retest_directional_close_location",
    "reclaim_body_fraction",
    "reclaim_directional_close_location",
    "local_range_width_over_avg",
    "wide_range_width_over_avg",
    "compression_ratio_12_over_48",
    "range_expansion_ratio",
    "prior_push_against_direction_12",
    "distance_from_range_mid_over_range",
    "session_scope_flag",
    "wide_scope_flag",
    "spread_over_range",
)
MODEL_FAMILY = "fold_local_train_only_reclaim_retest_rejection_event_utility"
LABEL_SHAPE = "reclaim_retest_rejection_target_before_stop_plus_path_quality"
POSITIVE_LABEL_THRESHOLD = 0.12
ADVERSE_LABEL_THRESHOLD = -0.45
WEIGHT_FLOOR = 0.25
WEIGHT_CEILING = 2.50
EVENT_LOOKBACK_LOCAL = 36
EVENT_LOOKBACK_WIDE = 96
MIN_SWEEP_DEPTH_OVER_RANGE = 0.015
MIN_RECLAIM_CLOSE_OVER_BAR_RANGE = 0.020
RETEST_MIN_DELAY_BARS = 2
RETEST_MAX_DELAY_BARS = 8
MAX_RETEST_TOUCH_GAP_OVER_RANGE = 0.180
MAX_RETEST_OVERSHOOT_OVER_RANGE = 0.240
MIN_RETEST_REJECTION_OVER_BAR_RANGE = 0.020
SCORE_COMPONENT_NAMES = (
    "signed_feature_utility",
    "retest_rejection_bonus",
    "scope_bonus",
    "spread_penalty",
)


@dataclass(frozen=True)
class EventUtilityModel:
    fold_id: str
    feature_mean: np.ndarray
    feature_std: np.ndarray
    feature_weights: np.ndarray
    feature_directions: np.ndarray
    train_candidate_count: int
    global_mean: float
    global_positive_rate: float
    global_adverse_rate: float


def run_c0006_r0005_proxy(write: bool = True) -> dict[str, object]:
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
            split["train_is"],
            fold_id,
            include_labels=True,
        )
        model = fit_event_model(train_candidates, fold_id)
        test_candidates = build_candidates(
            bars,
            range_average,
            short_range_average,
            split["test_oos"],
            fold_id,
            include_labels=False,
        )
        scored_candidates = score_event_candidates(test_candidates, model)
        selected = base.select_daily_candidates(scored_candidates)
        trades.extend(base.simulate_trades(bars, range_average, selected, split["test_oos"]))
        fold_models.append(event_model_summary(model))
        state_distributions[fold_id] = event_distribution(scored_candidates, selected, model)
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
        96,
        3,
    )
    end_index = min(
        base.last_index_at_or_before(bars, window.end),
        len(bars) - base.LABEL_HORIZON_BARS - RETEST_MAX_DELAY_BARS - 2,
    )
    candidates: list[base.Candidate] = []
    for index in range(start_index, end_index + 1):
        if not base.in_core_session(bars[index].time):
            continue
        average_range = range_average[index]
        short_average_range = short_range_average[index]
        if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
            continue
        for direction in (1, -1):
            event = reclaim_retest_rejection_features(bars, range_average, short_range_average, index, direction)
            if event is None:
                continue
            retest_index, scope, features = event
            if bars[retest_index].time > window.end:
                continue
            label = (
                reclaim_retest_rejection_label(bars, range_average, retest_index, direction)
                if include_labels
                else None
            )
            side = "long" if direction > 0 else "short"
            candidates.append(
                base.Candidate(
                    fold_id=fold_id,
                    index=retest_index,
                    direction=direction,
                    day=bars[retest_index].time.strftime("%Y-%m-%d"),
                    state_key=f"{side}|{scope}|reclaim_retest_rejection",
                    features=features,
                    label=label,
                )
            )
    return candidates


def reclaim_retest_rejection_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    index: int,
    direction: int,
) -> tuple[int, str, tuple[float, ...]] | None:
    average_range = range_average[index]
    short_average_range = short_range_average[index]
    if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
        return None
    bar = bars[index]
    bar_range = max(bar.high - bar.low, 0.0)
    if bar_range <= 0:
        return None

    local_high, local_low = prior_range(bars, index, EVENT_LOOKBACK_LOCAL)
    wide_high, wide_low = prior_range(bars, index, EVENT_LOOKBACK_WIDE)
    session_extreme = prior_session_extreme(bars, index, direction)
    if session_extreme is None:
        return None

    candidates: list[tuple[str, float, float, float]] = []
    if direction > 0:
        candidates.extend(
            [
                ("local", local_low, max(local_low - bar.low, 0.0), local_high - local_low),
                ("wide", wide_low, max(wide_low - bar.low, 0.0), wide_high - wide_low),
                ("session", session_extreme, max(session_extreme - bar.low, 0.0), wide_high - wide_low),
            ]
        )
    else:
        candidates.extend(
            [
                ("local", local_high, max(bar.high - local_high, 0.0), local_high - local_low),
                ("wide", wide_high, max(bar.high - wide_high, 0.0), wide_high - wide_low),
                ("session", session_extreme, max(bar.high - session_extreme, 0.0), wide_high - wide_low),
            ]
        )
    valid = [row for row in candidates if row[2] / average_range >= MIN_SWEEP_DEPTH_OVER_RANGE]
    if not valid:
        return None
    scope, level, sweep_depth, event_range_width = max(
        valid,
        key=lambda row: ({"session": 3, "wide": 2, "local": 1}[row[0]], row[2]),
    )

    reclaim_depth = max(bar.close - level, 0.0) if direction > 0 else max(level - bar.close, 0.0)
    if reclaim_depth / bar_range < MIN_RECLAIM_CLOSE_OVER_BAR_RANGE:
        return None

    retest_index: int | None = None
    retest_touch_gap = 0.0
    retest_overshoot = 0.0
    retest_rejection_depth = 0.0
    retest_bar_range = 0.0
    for candidate_index in range(index + RETEST_MIN_DELAY_BARS, index + RETEST_MAX_DELAY_BARS + 1):
        retest = bars[candidate_index]
        if retest.time.date() != bar.time.date():
            break
        candidate_range = max(retest.high - retest.low, 0.0)
        if candidate_range <= 0:
            continue
        if direction > 0:
            touch_gap = max(retest.low - level, 0.0)
            overshoot = max(level - retest.low, 0.0)
            rejection_depth = max(retest.close - level, 0.0)
            closes_reclaimed = retest.close > level
        else:
            touch_gap = max(level - retest.high, 0.0)
            overshoot = max(retest.high - level, 0.0)
            rejection_depth = max(level - retest.close, 0.0)
            closes_reclaimed = retest.close < level
        if not closes_reclaimed:
            continue
        if touch_gap / average_range > MAX_RETEST_TOUCH_GAP_OVER_RANGE:
            continue
        if overshoot / average_range > MAX_RETEST_OVERSHOOT_OVER_RANGE:
            continue
        if rejection_depth / candidate_range < MIN_RETEST_REJECTION_OVER_BAR_RANGE:
            continue
        retest_index = candidate_index
        retest_touch_gap = touch_gap
        retest_overshoot = overshoot
        retest_rejection_depth = rejection_depth
        retest_bar_range = candidate_range
        break
    if retest_index is None or retest_bar_range <= 0:
        return None
    retest = bars[retest_index]
    delay_bars = retest_index - index

    compression_ratio = short_average_range / average_range
    range_expansion_ratio = bar_range / average_range
    prior_push_12 = -direction * (bars[index - 1].close - bars[index - 12].close) / average_range
    reclaim_body_fraction = direction * (bar.close - bar.open) / bar_range
    reclaim_close_location = (bar.close - bar.low) / bar_range
    reclaim_directional_close_location = reclaim_close_location if direction > 0 else 1.0 - reclaim_close_location
    retest_body_fraction = direction * (retest.close - retest.open) / retest_bar_range
    close_location = (retest.close - retest.low) / retest_bar_range
    retest_directional_close_location = close_location if direction > 0 else 1.0 - close_location
    upper_wick = retest.high - max(retest.open, retest.close)
    lower_wick = min(retest.open, retest.close) - retest.low
    rejection_wick = lower_wick if direction > 0 else upper_wick
    mid = (local_high + local_low) / 2.0
    distance_from_mid = direction * (retest.close - mid) / max(local_high - local_low, 1e-9)
    spread_over_range = retest.spread_points / average_range
    return retest_index, scope, (
        sweep_depth / average_range,
        reclaim_depth / average_range,
        float(delay_bars),
        retest_touch_gap / average_range,
        retest_overshoot / average_range,
        retest_rejection_depth / average_range,
        rejection_wick / retest_bar_range,
        retest_body_fraction,
        retest_directional_close_location,
        reclaim_body_fraction,
        reclaim_directional_close_location,
        (local_high - local_low) / average_range,
        (wide_high - wide_low) / average_range,
        compression_ratio,
        range_expansion_ratio,
        prior_push_12,
        distance_from_mid,
        1.0 if scope == "session" else 0.0,
        1.0 if scope == "wide" else 0.0,
        spread_over_range,
    )


def prior_range(bars: list[base.Bar], index: int, lookback: int) -> tuple[float, float]:
    window = bars[index - lookback : index]
    return max(bar.high for bar in window), min(bar.low for bar in window)


def prior_session_extreme(bars: list[base.Bar], index: int, direction: int) -> float | None:
    timestamp = bars[index].time
    start = index
    while start > 0 and bars[start - 1].time.date() == timestamp.date():
        start -= 1
    session_bars = [
        bar
        for bar in bars[start:index]
        if base.CORE_SESSION_START_MINUTE <= base.minute_of_day(bar.time) <= base.CORE_SESSION_END_MINUTE
    ]
    if len(session_bars) < 6:
        return None
    return min(bar.low for bar in session_bars) if direction > 0 else max(bar.high for bar in session_bars)


def reclaim_retest_rejection_label(
    bars: list[base.Bar],
    range_average: list[float | None],
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
    if direction > 0:
        mfe = max(bar.high - entry for bar in path)
        mae = max(entry - bar.low for bar in path)
        terminal = path[-1].close - entry
        aligned_close_count = sum(1 for bar in path if bar.close >= entry)
        for offset, bar in enumerate(path, start=1):
            hit_stop = bar.low <= stop_price
            hit_target = bar.high >= target_price
            if hit_stop:
                first_hit = -1.0
                event_bar = offset
                break
            if hit_target:
                first_hit = 1.0
                event_bar = offset
                break
    else:
        mfe = max(entry - bar.low for bar in path)
        mae = max(bar.high - entry for bar in path)
        terminal = entry - path[-1].close
        aligned_close_count = sum(1 for bar in path if bar.close <= entry)
        for offset, bar in enumerate(path, start=1):
            hit_stop = bar.high >= stop_price
            hit_target = bar.low <= target_price
            if hit_stop:
                first_hit = -1.0
                event_bar = offset
                break
            if hit_target:
                first_hit = 1.0
                event_bar = offset
                break
    favorable = mfe / average_range
    adverse = mae / average_range
    terminal_norm = terminal / average_range
    path_alignment = aligned_close_count / len(path)
    target_speed = (len(path) - event_bar + 1) / len(path) if first_hit > 0.0 else 0.0
    stop_speed = (len(path) - event_bar + 1) / len(path) if first_hit < 0.0 else 0.0
    adverse_tail = max(0.0, (mae / max(stop_distance, 1e-9)) - 0.62)
    giveback = max(0.0, favorable - max(terminal_norm, 0.0))
    path_alignment_edge = path_alignment - 0.5
    spread_norm = bars[entry_index].spread_points / average_range
    return (
        0.95 * first_hit
        + 0.38 * target_speed
        - 0.30 * stop_speed
        + 0.26 * favorable
        - 0.38 * adverse
        - 1.12 * adverse_tail
        - 0.24 * giveback
        + 0.22 * terminal_norm
        + 0.18 * path_alignment_edge
        - spread_norm
    )


def fit_event_model(candidates: list[base.Candidate], fold_id: str) -> EventUtilityModel:
    labeled = [candidate for candidate in candidates if candidate.label is not None]
    if not labeled:
        zeros = np.zeros(len(FEATURE_NAMES), dtype=float)
        ones = np.ones(len(FEATURE_NAMES), dtype=float)
        return EventUtilityModel(
            fold_id=fold_id,
            feature_mean=zeros,
            feature_std=ones,
            feature_weights=ones,
            feature_directions=zeros,
            train_candidate_count=0,
            global_mean=0.0,
            global_positive_rate=0.0,
            global_adverse_rate=0.0,
        )
    feature_matrix = np.asarray([candidate.features for candidate in labeled], dtype=float)
    labels = np.asarray([candidate.label for candidate in labeled if candidate.label is not None], dtype=float)
    feature_mean = feature_matrix.mean(axis=0)
    feature_std = feature_matrix.std(axis=0)
    feature_std[feature_std < 1e-9] = 1.0
    scaled = (feature_matrix - feature_mean) / feature_std
    feature_weights, feature_directions = supervised_event_weights(scaled, labels)
    return EventUtilityModel(
        fold_id=fold_id,
        feature_mean=feature_mean,
        feature_std=feature_std,
        feature_weights=feature_weights,
        feature_directions=feature_directions,
        train_candidate_count=len(labeled),
        global_mean=float(labels.mean()),
        global_positive_rate=float(np.mean(labels > POSITIVE_LABEL_THRESHOLD)),
        global_adverse_rate=float(np.mean(labels < ADVERSE_LABEL_THRESHOLD)),
    )


def supervised_event_weights(scaled_features: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if scaled_features.size == 0 or labels.size == 0:
        width = scaled_features.shape[1] if scaled_features.ndim == 2 else len(FEATURE_NAMES)
        return np.ones(width, dtype=float), np.zeros(width, dtype=float)
    label_centered = labels - labels.mean()
    label_std = float(labels.std())
    if label_std <= 1e-9:
        return np.ones(scaled_features.shape[1], dtype=float), np.zeros(scaled_features.shape[1], dtype=float)
    signed = (scaled_features * label_centered[:, None]).mean(axis=0) / label_std
    positive_mask = labels > POSITIVE_LABEL_THRESHOLD
    adverse_mask = labels < ADVERSE_LABEL_THRESHOLD
    separation = np.zeros(scaled_features.shape[1], dtype=float)
    if positive_mask.any() and adverse_mask.any():
        separation = scaled_features[positive_mask].mean(axis=0) - scaled_features[adverse_mask].mean(axis=0)
    raw = np.abs(signed) + 0.22 * np.abs(separation)
    raw[~np.isfinite(raw)] = 0.0
    if float(raw.max()) <= 1e-12:
        return np.ones(scaled_features.shape[1], dtype=float), np.zeros(scaled_features.shape[1], dtype=float)
    positive_raw = raw[raw > 0.0]
    scale = float(np.median(positive_raw)) if positive_raw.size else float(raw.max())
    if scale <= 1e-12:
        scale = float(raw.max())
    weights = np.sqrt(np.maximum(raw / scale, 0.0))
    weights = np.clip(weights, WEIGHT_FLOOR, WEIGHT_CEILING)
    mean_weight = float(weights.mean())
    if mean_weight > 1e-12:
        weights = weights / mean_weight
    directions = np.sign(signed + 0.22 * separation)
    directions[~np.isfinite(directions)] = 0.0
    return weights, directions


def score_event_candidates(candidates: list[base.Candidate], model: EventUtilityModel) -> list[base.Candidate]:
    if model.train_candidate_count <= 0 or not candidates:
        return [copy_with_score(candidate, None) for candidate in candidates]
    features = np.asarray([candidate.features for candidate in candidates], dtype=float)
    scaled = (features - model.feature_mean) / model.feature_std
    signed_utility = ((scaled * model.feature_weights) * model.feature_directions).sum(axis=1) / max(len(FEATURE_NAMES), 1)
    sweep_depth = features[:, FEATURE_NAMES.index("sweep_depth_over_range")]
    reclaim_depth = features[:, FEATURE_NAMES.index("reclaim_close_depth_over_range")]
    retest_rejection_depth = features[:, FEATURE_NAMES.index("retest_rejection_depth_over_range")]
    retest_overshoot = features[:, FEATURE_NAMES.index("retest_overshoot_over_range")]
    rejection_wick = features[:, FEATURE_NAMES.index("retest_rejection_wick_fraction")]
    retest_body = features[:, FEATURE_NAMES.index("retest_body_fraction")]
    retest_close_location = features[:, FEATURE_NAMES.index("retest_directional_close_location")]
    session_scope = features[:, FEATURE_NAMES.index("session_scope_flag")]
    wide_scope = features[:, FEATURE_NAMES.index("wide_scope_flag")]
    spread_penalty = features[:, FEATURE_NAMES.index("spread_over_range")]
    scores = (
        0.62 * signed_utility
        + 0.18 * np.tanh(2.1 * reclaim_depth)
        + 0.22 * np.tanh(2.4 * retest_rejection_depth)
        + 0.18 * np.tanh(1.6 * sweep_depth)
        + 0.13 * rejection_wick
        + 0.09 * retest_body
        + 0.06 * retest_close_location
        - 0.08 * np.tanh(2.0 * retest_overshoot)
        + 0.05 * session_scope
        + 0.03 * wide_scope
        - 0.18 * spread_penalty
    )
    scored: list[base.Candidate] = []
    for index, candidate in enumerate(candidates):
        scored.append(copy_with_score(candidate, float(scores[index])))
    return scored


def copy_with_score(candidate: base.Candidate, score: float | None) -> base.Candidate:
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
    payload = replace_run_markers(base.build_proxy_payload(trades, windows, fold_models, state_distributions, candidates_by_fold))
    payload["campaign_id"] = "C0006"
    payload["work_unit_id"] = "C0006"
    payload["run_id"] = "R0005"
    payload["proxy_id"] = "PX-C0006-R0005"
    payload["proxy_engine"] = "axiom_rift.proxies.c0006_r0005_reclaim_retest_rejection"
    payload["proxy_config_path"] = "campaigns/C0006_liquidity_sweep_reclaim_event_discovery/runs/R0005/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_reclaim_retest_rejection_event_fit"
    payload["proxy_artifact_paths"] = [
        "campaigns/C0006_liquidity_sweep_reclaim_event_discovery/runs/R0005/kpi/proxy.json",
        "campaigns/C0006_liquidity_sweep_reclaim_event_discovery/runs/R0005/artifacts/c0006_r0005_proxy_trades.csv",
        "campaigns/C0006_liquidity_sweep_reclaim_event_discovery/runs/R0005/artifacts/c0006_r0005_reclaim_retest_rejection_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["reclaim_retest_rejection_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "model_family": MODEL_FAMILY,
            "feature_count": len(FEATURE_NAMES),
            "feature_names": list(FEATURE_NAMES),
            "label_shape": LABEL_SHAPE,
            "positive_label_threshold": POSITIVE_LABEL_THRESHOLD,
            "adverse_label_threshold": ADVERSE_LABEL_THRESHOLD,
            "weight_floor": WEIGHT_FLOOR,
            "weight_ceiling": WEIGHT_CEILING,
            "event_lookback_local": EVENT_LOOKBACK_LOCAL,
            "event_lookback_wide": EVENT_LOOKBACK_WIDE,
            "min_sweep_depth_over_range": MIN_SWEEP_DEPTH_OVER_RANGE,
            "min_reclaim_close_over_bar_range": MIN_RECLAIM_CLOSE_OVER_BAR_RANGE,
            "retest_min_delay_bars": RETEST_MIN_DELAY_BARS,
            "retest_max_delay_bars": RETEST_MAX_DELAY_BARS,
            "max_retest_touch_gap_over_range": MAX_RETEST_TOUCH_GAP_OVER_RANGE,
            "max_retest_overshoot_over_range": MAX_RETEST_OVERSHOOT_OVER_RANGE,
            "min_retest_rejection_over_bar_range": MIN_RETEST_REJECTION_OVER_BAR_RANGE,
            "score_component_names": list(SCORE_COMPONENT_NAMES),
            "fold_models": fold_models,
            "state_distributions": state_distributions,
            "candidates_by_fold": candidates_by_fold,
            "selection_rule": "top_fold_local_reclaim_retest_rejection_scores_per_active_day",
            "model_selected": False,
            "feature_set_selected": False,
            "label_selected": False,
        },
    }
    return payload


def proxy_config() -> dict[str, object]:
    config = dict(base.proxy_config())
    config.pop("state_model", None)
    config.update(
        {
            "event_model": MODEL_FAMILY,
            "label_shape": LABEL_SHAPE,
            "selection_rule": "top_fold_local_reclaim_retest_rejection_scores_per_active_day",
            "feature_names": list(FEATURE_NAMES),
            "feature_count": len(FEATURE_NAMES),
            "positive_label_threshold": POSITIVE_LABEL_THRESHOLD,
            "adverse_label_threshold": ADVERSE_LABEL_THRESHOLD,
            "weight_floor": WEIGHT_FLOOR,
            "weight_ceiling": WEIGHT_CEILING,
            "event_lookback_local": EVENT_LOOKBACK_LOCAL,
            "event_lookback_wide": EVENT_LOOKBACK_WIDE,
            "min_sweep_depth_over_range": MIN_SWEEP_DEPTH_OVER_RANGE,
            "min_reclaim_close_over_bar_range": MIN_RECLAIM_CLOSE_OVER_BAR_RANGE,
            "retest_min_delay_bars": RETEST_MIN_DELAY_BARS,
            "retest_max_delay_bars": RETEST_MAX_DELAY_BARS,
            "max_retest_touch_gap_over_range": MAX_RETEST_TOUCH_GAP_OVER_RANGE,
            "max_retest_overshoot_over_range": MAX_RETEST_OVERSHOOT_OVER_RANGE,
            "min_retest_rejection_over_bar_range": MIN_RETEST_REJECTION_OVER_BAR_RANGE,
            "score_component_names": list(SCORE_COMPONENT_NAMES),
            "score_interpretation": "higher_score_means_train_fold_event_utility_supports_reclaim_retest_rejection_follow_through",
            "variant_boundary": "new_reclaim_retest_rejection_event_grammar_not_analog_memory_state_bucket_score_cell_exit_shape_or_parameter_nudge",
        }
    )
    return config


def event_model_summary(model: EventUtilityModel) -> dict[str, object]:
    return {
        "fold_id": model.fold_id,
        "model_family": MODEL_FAMILY,
        "feature_names": list(FEATURE_NAMES),
        "feature_count": len(FEATURE_NAMES),
        "train_candidate_count": model.train_candidate_count,
        "weight_floor": WEIGHT_FLOOR,
        "weight_ceiling": WEIGHT_CEILING,
        "feature_weights": [base.rounded(float(value)) for value in model.feature_weights],
        "feature_directions": [base.rounded(float(value)) for value in model.feature_directions],
        "score_component_names": list(SCORE_COMPONENT_NAMES),
        "positive_label_threshold": POSITIVE_LABEL_THRESHOLD,
        "adverse_label_threshold": ADVERSE_LABEL_THRESHOLD,
        "global_mean": base.rounded(model.global_mean),
        "global_positive_label_rate": base.rounded(model.global_positive_rate),
        "global_adverse_label_rate": base.rounded(model.global_adverse_rate),
        "feature_mean": [base.rounded(float(value)) for value in model.feature_mean],
        "feature_std": [base.rounded(float(value)) for value in model.feature_std],
        "score_interpretation": "higher_score_means_train_fold_event_utility_supports_reclaim_retest_rejection_follow_through",
    }


def event_distribution(
    scored: list[base.Candidate],
    selected: list[base.Candidate],
    model: EventUtilityModel,
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


def write_proxy_evidence(payload: dict[str, object], trades: list[base.Trade]) -> None:
    RUN_DIR.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    RUN_DIR.joinpath("kpi").mkdir(parents=True, exist_ok=True)
    base.write_trade_artifact(trades, TRADE_ARTIFACT_PATH)
    write_event_summary_artifact(payload, EVENT_SUMMARY_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = base.sha256_file(TRADE_ARTIFACT_PATH)
    summary_hash = base.sha256_file(EVENT_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = base.sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)


def write_event_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_reclaim_retest_rejection_summary_v1",
        "template": False,
        "work_unit_id": "C0006",
        "campaign_id": "C0006",
        "run_id": "R0005",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "reclaim_retest_rejection_profile": profiles["reclaim_retest_rejection_profile"]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "reclaim_retest_rejection_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-C0006-R0005-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0006_liquidity_sweep_reclaim_event_discovery/runs/R0005/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0006_liquidity_sweep_reclaim_event_discovery/runs/R0005/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-C0006-R0005-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0006_liquidity_sweep_reclaim_event_discovery/runs/R0005/artifacts/c0006_r0005_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0006_liquidity_sweep_reclaim_event_discovery/runs/R0005/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0006-R0005-EVENT-UTILITY-SUMMARY",
                "reclaim_retest_rejection_summary_artifact",
                "json",
                "campaigns/C0006_liquidity_sweep_reclaim_event_discovery/runs/R0005/artifacts/c0006_r0005_reclaim_retest_rejection_summary.json",
                summary_hash,
                ["campaigns/C0006_liquidity_sweep_reclaim_event_discovery/runs/R0005/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0006_r0005_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0006_r0005_reclaim_retest_rejection",
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
    evidence["proxy_trade_artifact"] = "artifacts/c0006_r0005_proxy_trades.csv"
    evidence["reclaim_retest_rejection_summary"] = "artifacts/c0006_r0005_reclaim_retest_rejection_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0006_r0005_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0006_r0005_proxy_trades.csv",
        "artifacts/c0006_r0005_reclaim_retest_rejection_summary.json",
        "kpi/proxy.json",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["evidence_paths"] = evidence_paths
    data["deferred_with_reason"] = [
        {
            "field": "decision",
            "reason": "proxy evidence is recorded but MT5 and proxy-vs-MT5 evidence are still missing",
            "blocking_condition": "R0005 cannot close until mandatory MT5 logic parity, MT5 tick, execution divergence, and fold-isolated evidence are recorded",
            "revisit_when": "after C0006 R0005 MT5 evidence files contain measured results",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_campaign_status() -> None:
    data = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = "runs/R0005"
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["run_id"] = "R0005"
    next_candidate["direction"] = "active_c0006_r0005_mt5_logic_parity"
    next_candidate["reason"] = "R0005 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0006_r0005_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = "campaigns/C0006_liquidity_sweep_reclaim_event_discovery"
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = "campaigns/C0006_liquidity_sweep_reclaim_event_discovery"
    completed = list(next_work.get("completed") or [])
    if "produce_c0006_r0005_proxy_evidence" not in completed:
        completed.append("produce_c0006_r0005_proxy_evidence")
    next_action = "produce_c0006_r0005_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_run"] = "campaigns/C0006_liquidity_sweep_reclaim_event_discovery/runs/R0005"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0006_liquidity_sweep_reclaim_event_discovery"
    data["active_run"] = "campaigns/C0006_liquidity_sweep_reclaim_event_discovery/runs/R0005"
    data["latest_operation"] = {
        "id": "produce_c0006_r0005_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0006_liquidity_sweep_reclaim_event_discovery/runs/R0005/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0006_r0005_mt5_logic_parity_evidence",
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


def replace_run_markers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: replace_run_markers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_run_markers(item) for item in value]
    if isinstance(value, str):
        replacements = {
            "C0004": "C0006",
            "R0005": "R0005",
            "c0004_r0001_fold_local_state_archetype": "c0006_r0005_reclaim_retest_rejection",
            "c0004_r0001": "c0006_r0005",
            "fold_local_state_archetype_discovery": "liquidity_sweep_reclaim_event_discovery",
            "fold_local_train_only_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

