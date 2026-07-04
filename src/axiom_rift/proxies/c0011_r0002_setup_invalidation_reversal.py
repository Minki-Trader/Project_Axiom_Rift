"""C0011 R0002 proxy evidence for setup invalidation reversal discovery."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies.common import base


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0011_setup_lifecycle_timing_discovery" / "runs" / "R0002"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0011_setup_lifecycle_timing_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0011_r0002_proxy_trades.csv"
LIFECYCLE_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0011_r0002_setup_invalidation_reversal_summary.json"
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
    "setup_age_norm",
    "compression_maturity_24_over_288",
    "compression_maturity_96_over_288",
    "trigger_strength",
    "trigger_freshness",
    "directional_range_location_96",
    "directional_edge_retest_count_norm",
    "early_impulse_3",
    "early_impulse_6",
    "trend_alignment_24",
    "adverse_tail_pressure_24",
    "prior_directional_drawdown_72",
    "volatility_transition_12_vs_96",
    "spread_over_range",
    "spread_pressure_48",
    "session_progress",
    "directional_body_fraction",
    "decay_risk",
)
MODEL_FAMILY = "fold_local_setup_invalidation_reversal_rank"
LABEL_SHAPE = "opposite_direction_target_first_after_failed_or_decayed_setup"
SELECTION_RULE = "top_fold_local_failed_setup_reversal_scores_per_active_day"
POSITIVE_LABEL_THRESHOLD = 0.08
ADVERSE_LABEL_THRESHOLD = -0.34
FEATURE_WEIGHT_FLOOR = 0.25
FEATURE_WEIGHT_CEILING = 2.50
SETUP_LOOKBACK_BARS = 96
RANGE_CONTEXT_BARS = 288
TRIGGER_LOOKBACK_BARS = 24
TRIGGER_FRESHNESS_BARS = 12
EDGE_RETEST_LOOKBACK_BARS = 30
FAILED_SETUP_PHASES = {"decay", "mature_setup"}
MIN_FAILED_SETUP_DECAY_RISK = 0.62
MAX_FAILED_TRIGGER_FRESHNESS = 0.58
MIN_FAILED_TRIGGER_STRENGTH = 0.06


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
class FeatureSnapshot:
    features: tuple[float, ...]
    state_key: str
    phase: str
    setup_age: int
    trigger_age: int
    trigger_strength: float
    trigger_freshness: float
    decay_risk: float
    compression_maturity: float


def run_c0011_r0002_proxy(write: bool = True) -> dict[str, object]:
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
    range_series = build_range_series(bars)
    trades: list[base.Trade] = []
    fold_models: list[dict[str, object]] = []
    state_distributions: dict[str, dict[str, float | int | None]] = {}
    candidates_by_fold: dict[str, dict[str, int]] = {}
    for fold_id in sorted(fold_id for fold_id, split in windows.items() if {"train_is", "test_oos"} <= set(split)):
        split = windows[fold_id]
        train_candidates = build_candidates(
            bars,
            range_series,
            split["train_is"],
            fold_id,
            include_labels=True,
        )
        model = fit_linear_edge_model(train_candidates, fold_id)
        test_candidates = build_candidates(
            bars,
            range_series,
            split["test_oos"],
            fold_id,
            include_labels=False,
        )
        scored_candidates = score_candidates(test_candidates, model)
        selected = base.select_daily_candidates(scored_candidates)
        fold_trades = base.simulate_trades(bars, range_series["range_48"], selected, split["test_oos"])
        trades.extend(fold_trades)
        fold_models.append(linear_model_summary(model))
        state_distributions[fold_id] = lifecycle_distribution(scored_candidates, selected, fold_trades, model)
        candidates_by_fold[fold_id] = {
            "train_candidate_count": len(train_candidates),
            "test_candidate_count": len(test_candidates),
            "selected_candidate_count": len(selected),
            "proxy_trade_count": len(fold_trades),
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


def build_range_series(bars: list[base.Bar]) -> dict[str, list[float | None]]:
    ranges = [max(bar.high - bar.low, 0.0) for bar in bars]
    spreads = [bar.spread_points for bar in bars]
    return {
        "range_12": base.previous_rolling_average(ranges, 12),
        "range_24": base.previous_rolling_average(ranges, 24),
        "range_48": base.previous_rolling_average(ranges, 48),
        "range_96": base.previous_rolling_average(ranges, 96),
        "range_288": base.previous_rolling_average(ranges, RANGE_CONTEXT_BARS),
        "spread_48": base.previous_rolling_average(spreads, 48),
    }


def build_candidates(
    bars: list[base.Bar],
    range_series: dict[str, list[float | None]],
    window: base.SplitWindow,
    fold_id: str,
    include_labels: bool,
) -> list[base.Candidate]:
    start_index = max(
        base.first_index_at_or_after(bars, window.start),
        RANGE_CONTEXT_BARS,
        SETUP_LOOKBACK_BARS,
        base.POSITION_BARS,
        base.LABEL_HORIZON_BARS + TRIGGER_FRESHNESS_BARS,
    )
    end_index = min(base.last_index_at_or_before(bars, window.end), len(bars) - base.LABEL_HORIZON_BARS - 2)
    candidates: list[base.Candidate] = []
    for index in range(start_index, end_index + 1):
        if not base.in_core_session(bars[index].time):
            continue
        for direction in (1, -1):
            failed_snapshot = setup_lifecycle_snapshot(bars, range_series, index, direction)
            if failed_snapshot is None or not is_failed_setup_reversal_candidate(failed_snapshot):
                continue
            reversal_direction = -direction
            label = (
                setup_lifecycle_label(bars, range_series, index, reversal_direction, failed_snapshot)
                if include_labels
                else None
            )
            candidates.append(
                base.Candidate(
                    fold_id=fold_id,
                    index=index,
                    direction=reversal_direction,
                    day=bars[index].time.strftime("%Y-%m-%d"),
                    state_key=reversal_state_key(direction, failed_snapshot),
                    features=reversal_features(failed_snapshot),
                    label=label,
                )
            )
    return candidates


def is_failed_setup_reversal_candidate(snapshot: FeatureSnapshot) -> bool:
    if snapshot.phase in FAILED_SETUP_PHASES and snapshot.decay_risk >= MIN_FAILED_SETUP_DECAY_RISK:
        return True
    stale_trigger = snapshot.trigger_strength >= MIN_FAILED_TRIGGER_STRENGTH and snapshot.trigger_freshness <= MAX_FAILED_TRIGGER_FRESHNESS
    adverse_decay = snapshot.decay_risk >= MIN_FAILED_SETUP_DECAY_RISK and snapshot.compression_maturity >= 0.04
    return stale_trigger and adverse_decay


def reversal_features(snapshot: FeatureSnapshot) -> tuple[float, ...]:
    # Reversal features keep the failed setup's context but invert directional impulse fields.
    values = list(snapshot.features)
    for index in (3, 5, 7, 8, 9, 16):
        values[index] = -values[index]
    values[4] = 1.0 - values[4]
    values[17] = snapshot.decay_risk
    return tuple(values)


def reversal_state_key(failed_direction: int, snapshot: FeatureSnapshot) -> str:
    failed_side = "long" if failed_direction > 0 else "short"
    reversal_side = "short" if failed_direction > 0 else "long"
    return f"{reversal_side}|reversal_from_{failed_side}|{snapshot.state_key}"


def setup_lifecycle_snapshot(
    bars: list[base.Bar],
    range_series: dict[str, list[float | None]],
    index: int,
    direction: int,
) -> FeatureSnapshot | None:
    range_12 = range_series["range_12"][index]
    range_24 = range_series["range_24"][index]
    range_48 = range_series["range_48"][index]
    range_96 = range_series["range_96"][index]
    range_288 = range_series["range_288"][index]
    spread_48 = range_series["spread_48"][index]
    if (
        range_12 is None
        or range_24 is None
        or range_48 is None
        or range_96 is None
        or range_288 is None
        or spread_48 is None
        or min(range_12, range_24, range_48, range_96, range_288) <= 0.0
    ):
        return None
    bar = bars[index]
    bar_range = max(bar.high - bar.low, 0.0)
    if bar_range <= 0.0:
        return None
    prior_low_96, prior_high_96 = prior_window_low_high(bars, index, SETUP_LOOKBACK_BARS)
    prior_low_24, prior_high_24 = prior_window_low_high(bars, index, TRIGGER_LOOKBACK_BARS)
    range_width_96 = max(prior_high_96 - prior_low_96, 1e-9)
    long_location = (bar.close - prior_low_96) / range_width_96
    directional_location = clamp(long_location if direction > 0 else 1.0 - long_location, 0.0, 1.0)
    compression_maturity_24 = clamp(1.0 - (range_24 / max(range_288, 1e-9)), -1.0, 1.0)
    compression_maturity_96 = clamp(1.0 - (range_96 / max(range_288, 1e-9)), -1.0, 1.0)
    compression_maturity = 0.65 * compression_maturity_24 + 0.35 * compression_maturity_96
    setup_age = bars_since_compression(range_series, index)
    setup_age_norm = setup_age / SETUP_LOOKBACK_BARS
    trigger_level = prior_high_24 if direction > 0 else prior_low_24
    breakout_distance = direction * (bar.close - trigger_level) / range_48
    ret_3 = direction * (bar.close - bars[index - 3].close) / range_48
    ret_6 = direction * (bar.close - bars[index - 6].close) / range_48
    trigger_strength = breakout_distance + 0.42 * ret_3 + 0.18 * max(ret_6, 0.0)
    trigger_age = bars_since_trigger(bars, range_series, index, direction)
    trigger_freshness = clamp(1.0 - (trigger_age / TRIGGER_FRESHNESS_BARS), 0.0, 1.0)
    retest_norm = edge_retest_count(bars, index, direction, trigger_level, range_48) / 5.0
    trend_alignment = signed_step_average(
        [direction * (bars[offset].close - bars[offset - 1].close) for offset in range(index - 23, index + 1)]
    )
    adverse_tail = adverse_tail_pressure(bars, index, direction, 24)
    prior_drawdown = prior_directional_drawdown(bars, index, direction, range_48)
    volatility_transition = (range_12 / max(range_96, 1e-9)) - (range_96 / max(range_288, 1e-9))
    spread_over_range = bar.spread_points / range_48
    spread_pressure = bar.spread_points / max(spread_48, 1e-9)
    session_progress = core_session_progress(bar.time)
    body_fraction = direction * (bar.close - bar.open) / bar_range
    close_location = ((bar.close - bar.low) / bar_range) if direction > 0 else ((bar.high - bar.close) / bar_range)
    early_impulse_3 = ret_3 + 0.28 * body_fraction + 0.20 * (close_location - 0.5)
    early_impulse_6 = ret_6 + 0.16 * trend_alignment
    decay_risk = (
        0.42 * max(setup_age_norm - 0.42, 0.0)
        + 0.38 * max((trigger_age / TRIGGER_FRESHNESS_BARS) - 0.45, 0.0)
        + 0.28 * adverse_tail
        + 0.24 * prior_drawdown
        + 0.22 * max(spread_pressure - 1.25, 0.0)
        + 0.16 * max(spread_over_range - 0.26, 0.0)
    )
    if spread_over_range > 0.72 or spread_pressure > 2.10 or decay_risk > 1.35:
        return None
    phase = lifecycle_phase(compression_maturity, trigger_strength, trigger_freshness, early_impulse_3, decay_risk)
    state_key = lifecycle_state_key(direction, phase, compression_maturity, trigger_strength, trigger_freshness, decay_risk, bar.time)
    return FeatureSnapshot(
        features=(
            setup_age_norm,
            compression_maturity_24,
            compression_maturity_96,
            trigger_strength,
            trigger_freshness,
            directional_location,
            retest_norm,
            early_impulse_3,
            early_impulse_6,
            trend_alignment,
            adverse_tail,
            prior_drawdown,
            volatility_transition,
            spread_over_range,
            spread_pressure,
            session_progress,
            body_fraction,
            decay_risk,
        ),
        state_key=state_key,
        phase=phase,
        setup_age=setup_age,
        trigger_age=trigger_age,
        trigger_strength=trigger_strength,
        trigger_freshness=trigger_freshness,
        decay_risk=decay_risk,
        compression_maturity=compression_maturity,
    )


def setup_lifecycle_label(
    bars: list[base.Bar],
    range_series: dict[str, list[float | None]],
    index: int,
    direction: int,
    snapshot: FeatureSnapshot,
) -> float | None:
    entry_index = index + 1
    exit_index = min(index + base.LABEL_HORIZON_BARS, len(bars) - 1)
    average_range = range_series["range_48"][index]
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
            if first_favorable_bar == len(path) and bar.high - entry >= 0.45 * average_range:
                first_favorable_bar = offset
            if first_adverse_bar == len(path) and entry - bar.low >= 0.35 * average_range:
                first_adverse_bar = offset
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
            if first_favorable_bar == len(path) and entry - bar.low >= 0.45 * average_range:
                first_favorable_bar = offset
            if first_adverse_bar == len(path) and bar.high - entry >= 0.35 * average_range:
                first_adverse_bar = offset
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
    early_path = path[: min(3, len(path))]
    early_favorable = directional_path_favorable(early_path, entry, direction) / average_range
    early_adverse = directional_path_adverse(early_path, entry, direction) / average_range
    target_speed = (len(path) - event_bar + 1) / len(path) if first_hit > 0.0 else 0.0
    stop_speed = (len(path) - event_bar + 1) / len(path) if first_hit < 0.0 else 0.0
    favorable_delay = first_favorable_bar / len(path)
    adverse_first_penalty = 1.0 if first_adverse_bar < first_favorable_bar else 0.0
    path_alignment = aligned_close_count / len(path)
    spread_norm = bars[entry_index].spread_points / average_range
    path_spread_peak = max(bar.spread_points for bar in path) / average_range
    spread_drift = max(0.0, path_spread_peak - spread_norm)
    trigger_decay = max(0.0, snapshot.trigger_age / TRIGGER_FRESHNESS_BARS)
    setup_age_penalty = max(0.0, snapshot.setup_age / SETUP_LOOKBACK_BARS - 0.45)
    return (
        1.10 * first_hit
        + 0.36 * target_speed
        - 0.48 * stop_speed
        + 0.30 * early_favorable
        + 0.22 * favorable
        + 0.18 * terminal_norm
        + 0.16 * (path_alignment - 0.5)
        - 0.50 * early_adverse
        - 0.58 * adverse
        - 0.42 * favorable_delay
        - 0.36 * adverse_first_penalty
        - 0.28 * snapshot.decay_risk
        - 0.18 * trigger_decay
        - 0.14 * setup_age_penalty
        - 0.72 * spread_norm
        - 0.36 * spread_drift
    )


def fit_linear_edge_model(candidates: list[base.Candidate], fold_id: str) -> LinearEdgeModel:
    labeled = [candidate for candidate in candidates if candidate.label is not None]
    feature_count = len(FEATURE_NAMES)
    if not labeled:
        return LinearEdgeModel(
            fold_id=fold_id,
            feature_mean=np.zeros(feature_count, dtype=float),
            feature_std=np.ones(feature_count, dtype=float),
            score_direction=np.zeros(feature_count, dtype=float),
            feature_weights=np.ones(feature_count, dtype=float),
            train_candidate_count=0,
            global_mean=0.0,
            positive_label_rate=0.0,
            adverse_label_rate=0.0,
            label_std=0.0,
        )
    feature_matrix = np.asarray([candidate.features for candidate in labeled], dtype=float)
    labels = np.asarray([candidate.label for candidate in labeled if candidate.label is not None], dtype=float)
    feature_mean = feature_matrix.mean(axis=0)
    feature_std = feature_matrix.std(axis=0)
    feature_std[feature_std < 1e-9] = 1.0
    scaled = (feature_matrix - feature_mean) / feature_std
    centered = labels - labels.mean()
    label_std = float(labels.std())
    if label_std <= 1e-9:
        signed_correlation = np.zeros(feature_count, dtype=float)
    else:
        signed_correlation = (scaled * centered[:, None]).mean(axis=0) / label_std
    positive_mask = labels > POSITIVE_LABEL_THRESHOLD
    adverse_mask = labels < ADVERSE_LABEL_THRESHOLD
    separation = np.zeros(feature_count, dtype=float)
    if positive_mask.any() and adverse_mask.any():
        separation = scaled[positive_mask].mean(axis=0) - scaled[adverse_mask].mean(axis=0)
    raw_strength = np.abs(signed_correlation) + 0.12 * np.abs(separation)
    raw_strength[~np.isfinite(raw_strength)] = 0.0
    positive_strength = raw_strength[raw_strength > 0.0]
    if positive_strength.size:
        scale = float(np.median(positive_strength))
        if scale <= 1e-12:
            scale = float(positive_strength.max())
        weights = np.sqrt(np.maximum(raw_strength / max(scale, 1e-12), 0.0))
        weights = np.clip(weights, FEATURE_WEIGHT_FLOOR, FEATURE_WEIGHT_CEILING)
        weights = weights / max(float(weights.mean()), 1e-12)
    else:
        weights = np.ones(feature_count, dtype=float)
    direction = signed_correlation + 0.08 * separation
    direction[~np.isfinite(direction)] = 0.0
    return LinearEdgeModel(
        fold_id=fold_id,
        feature_mean=feature_mean,
        feature_std=feature_std,
        score_direction=direction,
        feature_weights=weights,
        train_candidate_count=len(labeled),
        global_mean=float(labels.mean()),
        positive_label_rate=float(np.mean(positive_mask)),
        adverse_label_rate=float(np.mean(adverse_mask)),
        label_std=label_std,
    )


def score_candidates(candidates: list[base.Candidate], model: LinearEdgeModel) -> list[base.Candidate]:
    if not candidates:
        return []
    features = np.asarray([candidate.features for candidate in candidates], dtype=float)
    scaled = (features - model.feature_mean) / model.feature_std
    score_vector = model.score_direction * model.feature_weights
    denominator = math.sqrt(max(len(score_vector), 1))
    scores = model.global_mean + (scaled @ score_vector) / denominator
    scored: list[base.Candidate] = []
    for index, candidate in enumerate(candidates):
        score = float(scores[index])
        if not math.isfinite(score):
            score = None  # type: ignore[assignment]
        scored.append(copy_with_score(candidate, score))
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
    payload["campaign_id"] = "C0011"
    payload["work_unit_id"] = "C0011"
    payload["run_id"] = "R0002"
    payload["proxy_id"] = "PX-C0011-R0002"
    payload["proxy_engine"] = "axiom_rift.proxies.c0011_r0002_setup_invalidation_reversal"
    payload["proxy_config_path"] = "campaigns/C0011_setup_lifecycle_timing_discovery/runs/R0002/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_train_is_setup_invalidation_reversal_rank_fit"
    payload["proxy_artifact_paths"] = [
        "campaigns/C0011_setup_lifecycle_timing_discovery/runs/R0002/kpi/proxy.json",
        "campaigns/C0011_setup_lifecycle_timing_discovery/runs/R0002/artifacts/c0011_r0002_proxy_trades.csv",
        "campaigns/C0011_setup_lifecycle_timing_discovery/runs/R0002/artifacts/c0011_r0002_setup_invalidation_reversal_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["setup_invalidation_reversal_profile"] = {  # type: ignore[index]
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
            "setup_lookback_bars": SETUP_LOOKBACK_BARS,
            "range_context_bars": RANGE_CONTEXT_BARS,
            "trigger_lookback_bars": TRIGGER_LOOKBACK_BARS,
            "trigger_freshness_bars": TRIGGER_FRESHNESS_BARS,
            "failed_setup_phases": sorted(FAILED_SETUP_PHASES),
            "min_failed_setup_decay_risk": MIN_FAILED_SETUP_DECAY_RISK,
            "max_failed_trigger_freshness": MAX_FAILED_TRIGGER_FRESHNESS,
            "min_failed_trigger_strength": MIN_FAILED_TRIGGER_STRENGTH,
            "fold_models": fold_models,
            "state_distributions": state_distributions,
            "candidates_by_fold": candidates_by_fold,
            "selection_rule": SELECTION_RULE,
            "candidate_direction": "opposite_direction_after_failed_or_decayed_setup",
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
            "next_action": "produce_c0011_r0002_mt5_logic_parity_evidence",
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
            "setup_lookback_bars": SETUP_LOOKBACK_BARS,
            "range_context_bars": RANGE_CONTEXT_BARS,
            "trigger_lookback_bars": TRIGGER_LOOKBACK_BARS,
            "trigger_freshness_bars": TRIGGER_FRESHNESS_BARS,
            "failed_setup_phases": sorted(FAILED_SETUP_PHASES),
            "min_failed_setup_decay_risk": MIN_FAILED_SETUP_DECAY_RISK,
            "max_failed_trigger_freshness": MAX_FAILED_TRIGGER_FRESHNESS,
            "min_failed_trigger_strength": MIN_FAILED_TRIGGER_STRENGTH,
            "score_interpretation": "higher_score_means_fold_local_failed_setup_reversal_quality",
            "variant_boundary": "setup_decay_failed_trigger_reversal_not_lifecycle_score_floor_phase_whitelist_or_retry_nudge",
        }
    )
    return config


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
        "score_interpretation": "higher_score_means_fold_local_failed_setup_reversal_quality",
    }


def lifecycle_distribution(
    scored: list[base.Candidate],
    selected: list[base.Candidate],
    trades: list[base.Trade],
    model: LinearEdgeModel,
) -> dict[str, float | int | None]:
    scores = [candidate.score or 0.0 for candidate in scored if candidate.score is not None]
    selected_scores = [candidate.score or 0.0 for candidate in selected]
    phase_counts: dict[str, int] = {}
    for candidate in scored:
        phase = parse_phase(candidate.state_key)
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
    selected_phase_counts: dict[str, int] = {}
    for candidate in selected:
        phase = parse_phase(candidate.state_key)
        selected_phase_counts[phase] = selected_phase_counts.get(phase, 0) + 1
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
        "decay_phase_candidate_count": phase_counts.get("decay", 0),
        "mature_setup_phase_candidate_count": phase_counts.get("mature_setup", 0),
        "trigger_phase_candidate_count": phase_counts.get("trigger", 0),
        "early_confirmation_phase_candidate_count": phase_counts.get("early_confirmation", 0),
        "selected_decay_phase_candidate_count": selected_phase_counts.get("decay", 0),
        "selected_mature_setup_phase_candidate_count": selected_phase_counts.get("mature_setup", 0),
    }


def write_proxy_evidence(payload: dict[str, object], trades: list[base.Trade]) -> None:
    RUN_DIR.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    RUN_DIR.joinpath("kpi").mkdir(parents=True, exist_ok=True)
    base.write_trade_artifact(trades, TRADE_ARTIFACT_PATH)
    write_lifecycle_summary_artifact(payload, LIFECYCLE_SUMMARY_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = base.sha256_file(TRADE_ARTIFACT_PATH)
    summary_hash = base.sha256_file(LIFECYCLE_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = base.sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)


def write_lifecycle_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_fold_local_setup_invalidation_reversal_summary_v1",
        "template": False,
        "work_unit_id": "C0011",
        "campaign_id": "C0011",
        "run_id": "R0002",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "setup_invalidation_reversal_profile": profiles["setup_invalidation_reversal_profile"]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "setup_invalidation_reversal_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-C0011-R0002-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/C0011_setup_lifecycle_timing_discovery/runs/R0002/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0011_setup_lifecycle_timing_discovery/runs/R0002/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-C0011-R0002-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/C0011_setup_lifecycle_timing_discovery/runs/R0002/artifacts/c0011_r0002_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0011_setup_lifecycle_timing_discovery/runs/R0002/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-C0011-R0002-SETUP-INVALIDATION-REVERSAL-SUMMARY",
                "setup_invalidation_reversal_summary_artifact",
                "json",
                "campaigns/C0011_setup_lifecycle_timing_discovery/runs/R0002/artifacts/c0011_r0002_setup_invalidation_reversal_summary.json",
                summary_hash,
                ["campaigns/C0011_setup_lifecycle_timing_discovery/runs/R0002/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0011_r0002_mt5_logic_parity_evidence",
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
        "produced_by": "axiom_rift.proxies.c0011_r0002_setup_invalidation_reversal",
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
    evidence["proxy_trade_artifact"] = "artifacts/c0011_r0002_proxy_trades.csv"
    evidence["setup_invalidation_reversal_summary"] = "artifacts/c0011_r0002_setup_invalidation_reversal_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0011_r0002_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0011_r0002_proxy_trades.csv",
        "artifacts/c0011_r0002_setup_invalidation_reversal_summary.json",
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
            "revisit_when": "after C0011 R0002 MT5 evidence files contain measured results",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_campaign_status() -> None:
    data = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = "runs/R0002"
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["run_id"] = "R0002"
    next_candidate["direction"] = "active_c0011_r0002_mt5_logic_parity"
    next_candidate["reason"] = "R0002 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0011_r0002_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    data["project"]["active_campaign"] = "campaigns/C0011_setup_lifecycle_timing_discovery"
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = "campaigns/C0011_setup_lifecycle_timing_discovery"
    completed = list(next_work.get("completed") or [])
    for item in (
        "open_c0011_setup_lifecycle_timing_discovery",
        "open_c0011_r0002_setup_invalidation_reversal_run",
        "produce_c0011_r0002_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_c0011_r0002_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_run"] = "campaigns/C0011_setup_lifecycle_timing_discovery/runs/R0002"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0011_setup_lifecycle_timing_discovery"
    data["active_run"] = "campaigns/C0011_setup_lifecycle_timing_discovery/runs/R0002"
    data["latest_operation"] = {
        "id": "produce_c0011_r0002_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0011_setup_lifecycle_timing_discovery/runs/R0002/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_c0011_r0002_mt5_logic_parity_evidence",
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
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def bars_since_compression(range_series: dict[str, list[float | None]], index: int) -> int:
    for age in range(0, SETUP_LOOKBACK_BARS + 1):
        offset = index - age
        range_24 = range_series["range_24"][offset]
        range_288 = range_series["range_288"][offset]
        if range_24 is None or range_288 is None or range_288 <= 0.0:
            continue
        if range_24 / range_288 <= 0.86:
            return age
    return SETUP_LOOKBACK_BARS


def bars_since_trigger(
    bars: list[base.Bar],
    range_series: dict[str, list[float | None]],
    index: int,
    direction: int,
) -> int:
    for age in range(0, TRIGGER_FRESHNESS_BARS + 1):
        offset = index - age
        average_range = range_series["range_48"][offset]
        if average_range is None or average_range <= 0.0 or offset < TRIGGER_LOOKBACK_BARS:
            continue
        low, high = prior_window_low_high(bars, offset, TRIGGER_LOOKBACK_BARS)
        trigger_level = high if direction > 0 else low
        breakout = direction * (bars[offset].close - trigger_level) / average_range
        impulse = direction * (bars[offset].close - bars[offset - 3].close) / average_range
        if breakout + 0.35 * impulse >= 0.10:
            return age
    return TRIGGER_FRESHNESS_BARS


def prior_window_low_high(bars: list[base.Bar], index: int, lookback: int) -> tuple[float, float]:
    window = bars[index - lookback : index]
    return min(bar.low for bar in window), max(bar.high for bar in window)


def edge_retest_count(
    bars: list[base.Bar],
    index: int,
    direction: int,
    trigger_level: float,
    average_range: float,
) -> int:
    threshold = 0.22 * average_range
    count = 0
    for offset in range(index - EDGE_RETEST_LOOKBACK_BARS + 1, index + 1):
        bar = bars[offset]
        touched = abs(bar.low - trigger_level) <= threshold if direction > 0 else abs(bar.high - trigger_level) <= threshold
        rejected = bar.close >= trigger_level if direction > 0 else bar.close <= trigger_level
        if touched and rejected:
            count += 1
    return count


def signed_step_average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(1.0 if value > 0 else -1.0 if value < 0 else 0.0 for value in values) / len(values)


def adverse_tail_pressure(bars: list[base.Bar], index: int, direction: int, lookback: int) -> float:
    pressure = 0.0
    for bar in bars[index - lookback + 1 : index + 1]:
        bar_range = max(bar.high - bar.low, 1e-9)
        upper_tail = bar.high - max(bar.open, bar.close)
        lower_tail = min(bar.open, bar.close) - bar.low
        adverse_tail = upper_tail if direction > 0 else lower_tail
        pressure += adverse_tail / bar_range
    return pressure / lookback


def prior_directional_drawdown(bars: list[base.Bar], index: int, direction: int, average_range: float) -> float:
    closes = [bars[offset].close for offset in range(index - 71, index + 1)]
    if direction > 0:
        return max(0.0, max(closes) - bars[index].close) / average_range
    return max(0.0, bars[index].close - min(closes)) / average_range


def directional_path_favorable(path: list[base.Bar], entry: float, direction: int) -> float:
    if direction > 0:
        return max(bar.high - entry for bar in path)
    return max(entry - bar.low for bar in path)


def directional_path_adverse(path: list[base.Bar], entry: float, direction: int) -> float:
    if direction > 0:
        return max(entry - bar.low for bar in path)
    return max(bar.high - entry for bar in path)


def core_session_progress(timestamp: datetime) -> float:
    minute = base.minute_of_day(timestamp)
    span = max(base.CORE_SESSION_END_MINUTE - base.CORE_SESSION_START_MINUTE, 1)
    return clamp((minute - base.CORE_SESSION_START_MINUTE) / span, 0.0, 1.0)


def lifecycle_phase(
    compression_maturity: float,
    trigger_strength: float,
    trigger_freshness: float,
    early_impulse: float,
    decay_risk: float,
) -> str:
    if decay_risk >= 0.92:
        return "decay"
    if trigger_strength >= 0.18 and trigger_freshness >= 0.55:
        return "trigger"
    if trigger_freshness >= 0.25 and early_impulse >= 0.12 and decay_risk < 0.82:
        return "early_confirmation"
    if compression_maturity >= 0.18:
        return "mature_setup"
    return "birth"


def lifecycle_state_key(
    direction: int,
    phase: str,
    compression_maturity: float,
    trigger_strength: float,
    trigger_freshness: float,
    decay_risk: float,
    timestamp: datetime,
) -> str:
    side = "long" if direction > 0 else "short"
    compression = bucket(compression_maturity, 0.12, 0.28, "low", "mid", "high")
    trigger = bucket(trigger_strength, 0.10, 0.28, "soft", "firm", "strong")
    freshness = bucket(trigger_freshness, 0.30, 0.70, "stale", "fresh", "new")
    decay = bucket(decay_risk, 0.36, 0.72, "low_decay", "mid_decay", "high_decay")
    session = session_bucket(timestamp)
    return f"{side}|phase_{phase}|compression_{compression}|trigger_{trigger}|fresh_{freshness}|{decay}|{session}"


def parse_phase(state_key: str) -> str:
    for part in state_key.split("|"):
        if part.startswith("phase_"):
            return part.replace("phase_", "", 1)
    return "unknown"


def bucket(value: float, low: float, high: float, low_name: str, mid_name: str, high_name: str) -> str:
    if value < low:
        return low_name
    if value < high:
        return mid_name
    return high_name


def session_bucket(timestamp: datetime) -> str:
    minute = base.minute_of_day(timestamp)
    if minute < 8 * 60:
        return "early_session"
    if minute < 13 * 60:
        return "europe_morning"
    if minute < 17 * 60:
        return "us_overlap"
    return "late_session"


def clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def replace_run_markers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: replace_run_markers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_run_markers(item) for item in value]
    if isinstance(value, str):
        replacements = {
            "C0004": "C0011",
            "c0004_r0002_fold_local_state_archetype": "c0011_r0002_setup_invalidation_reversal",
            "c0004_r0002": "c0011_r0002",
            "fold_local_state_archetype_discovery": "setup_lifecycle_timing_discovery",
            "fold_local_train_only_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "directional_target_before_stop_plus_forward_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "setup_invalidation_reversal_summary",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value

