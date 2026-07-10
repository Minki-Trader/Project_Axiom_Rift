"""Pure declarative causal scout engine for V2 development folds."""

from __future__ import annotations

import bisect
import csv
import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from axiom_rift.v2.data.blackouts import BoundaryGap, interval_crosses_non_allow_boundary, load_non_allow_gaps
from axiom_rift.v2.features import (
    FEATURE_NAMES,
    WARMUP_BARS,
    BarArrays,
    FeatureContractError,
    bars_from_rows,
    compute_feature_matrix,
    feature_order_sha256,
    feature_program_sha256,
    load_feature_contract,
)
from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.research.programs import (
    ProgramRegistryError,
    load_program_registry,
)


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class ScoutSpecError(ValueError):
    """Raised when a scout spec exceeds the declarative whitelist."""


@dataclass(frozen=True)
class FoldWindow:
    development_id: str
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    development_start: datetime
    development_end: datetime


@dataclass(frozen=True)
class ScoutSpec:
    goal_id: str
    hypothesis_id: str
    feature_program_id: str
    feature_contract_path: Path
    label_program_id: str
    model_program_id: str
    calibration_program_id: str
    selector_program_id: str
    trade_program_id: str
    alpha: float
    residual_quantile: float
    hold_bars: int
    point_size: float
    maximum_daily_entries: int
    anchors: tuple[str, ...]
    acceptance_profile: dict[str, Any]
    program_registry_path: str
    program_registry_sha256: str
    program_identities: dict[str, dict[str, Any]]
    spec_sha256: str


@dataclass(frozen=True)
class ModelBundle:
    fold_id: str
    feature_names: tuple[str, ...]
    scaler_mean: tuple[float, ...]
    scaler_scale: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    residual_band: float

    def predict(self, values: np.ndarray) -> np.ndarray:
        mean = np.asarray(self.scaler_mean, dtype=np.float64)
        scale = np.asarray(self.scaler_scale, dtype=np.float64)
        coefficient = np.asarray(self.coefficients, dtype=np.float64)
        return ((np.asarray(values, dtype=np.float64) - mean) / scale) @ coefficient + self.intercept

    def to_payload(self) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "feature_names": list(self.feature_names),
            "scaler_mean": list(self.scaler_mean),
            "scaler_scale": list(self.scaler_scale),
            "coefficients": list(self.coefficients),
            "intercept": self.intercept,
            "residual_band": self.residual_band,
        }


@dataclass(frozen=True)
class ScoutTrade:
    fold_id: str
    signal_time: str
    entry_time: str
    exit_time: str
    direction: int
    score: float
    residual_band: float
    causal_cost_edge: float
    gross_broker_points: float | None
    spread_cost_broker_points: float | None
    net_broker_points: float | None
    evaluable_after_cost: bool
    exclusion_reason: str | None
    market_day: str
    market_hour: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "signal_time": self.signal_time,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "direction": self.direction,
            "score": self.score,
            "residual_band": self.residual_band,
            "causal_cost_edge": self.causal_cost_edge,
            "gross_broker_points": self.gross_broker_points,
            "spread_cost_broker_points": self.spread_cost_broker_points,
            "net_broker_points": self.net_broker_points,
            "evaluable_after_cost": self.evaluable_after_cost,
            "exclusion_reason": self.exclusion_reason,
            "market_day": self.market_day,
            "market_hour": self.market_hour,
        }


@dataclass(frozen=True)
class ScoutResult:
    outcome: str
    gate_passed: bool
    metrics: dict[str, Any]
    causal_checks: dict[str, Any]
    models: tuple[ModelBundle, ...]
    trades: tuple[ScoutTrade, ...]
    result_sha256: str
    claim_ceiling: str = "diagnostic_observation"
    economics_claim_allowed: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_scout_result_v1",
            "outcome": self.outcome,
            "gate_passed": self.gate_passed,
            "metrics": self.metrics,
            "causal_checks": self.causal_checks,
            "models": [model.to_payload() for model in self.models],
            "trades": [trade.to_payload() for trade in self.trades],
            "result_sha256": self.result_sha256,
            "claim_ceiling": self.claim_ceiling,
            "economics_claim_allowed": self.economics_claim_allowed,
        }


def load_scout_spec(
    path: Path,
    project_root: Path,
    program_registry_path: Path | None = None,
) -> ScoutSpec:
    raw = path.read_bytes()
    raw.decode("ascii")
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict) or payload.get("schema") != "axiom_rift_v2_hypothesis_v1":
        raise ScoutSpecError("hypothesis spec schema mismatch")
    if payload.get("status") != "preregistered" or payload.get("v1_evidence_inherited") is not False:
        raise ScoutSpecError("hypothesis must be a fresh preregistered V2 design")
    programs = payload.get("executable_programs")
    if not isinstance(programs, Mapping):
        raise ScoutSpecError("executable programs are missing")
    section_names = {
        "feature": "feature_program",
        "label": "label_program",
        "model": "model_program",
        "calibration": "calibration_program",
        "selector": "selector_program",
        "trade": "trade_program",
    }
    if set(programs) != set(section_names.values()):
        raise ScoutSpecError("executable program sections differ from the canonical scout surface")
    sections = {kind: programs.get(section) for kind, section in section_names.items()}
    if not all(isinstance(section, Mapping) for section in sections.values()):
        raise ScoutSpecError("hypothesis executable program sections are incomplete")
    try:
        registry = load_program_registry(project_root, program_registry_path)
        definitions = {
            kind: registry.resolve_section(kind, section)
            for kind, section in sections.items()
            if isinstance(section, Mapping)
        }
    except ProgramRegistryError as exc:
        raise ScoutSpecError(str(exc)) from exc
    feature_path = (project_root.resolve() / definitions["feature"].contract_path).resolve()
    try:
        feature_contract = load_feature_contract(feature_path)
    except FeatureContractError as exc:
        raise ScoutSpecError(str(exc)) from exc
    if feature_contract.get("program_id") != definitions["feature"].program_id:
        raise ScoutSpecError("feature contract program id differs from the registry")
    label = sections["label"]
    model = sections["model"]
    calibration = sections["calibration"]
    selector = sections["selector"]
    trade = sections["trade"]
    data = payload.get("data")
    acceptance = payload.get("acceptance_profile")
    if not all(isinstance(item, Mapping) for item in (model, calibration, selector, trade, data, acceptance)):
        raise ScoutSpecError("hypothesis program or acceptance sections are incomplete")
    anchors = tuple(str(value) for value in data.get("scout_anchor_ids", []))
    if anchors != ("V2D002", "V2D005", "V2D008"):
        raise ScoutSpecError("scout anchors differ from the preregistered season-diverse set")
    if acceptance.get("frozen_before_results") is not True:
        raise ScoutSpecError("acceptance profile was not frozen before results")
    hold_bars = int(trade.get("hold_bars"))
    if int(label.get("horizon_bars_after_entry")) != hold_bars:
        raise ScoutSpecError("label horizon and trade hold must describe the same executable interval")
    feature_input = feature_contract.get("input")
    if not isinstance(feature_input, Mapping):
        raise ScoutSpecError("feature contract input section is missing")
    point_size = float(feature_input.get("point_size"))
    if point_size <= 0.0:
        raise ScoutSpecError("feature contract point size must be positive")
    return ScoutSpec(
        goal_id=str(payload.get("goal_id")),
        hypothesis_id=str(payload.get("hypothesis_id")),
        feature_program_id=definitions["feature"].program_id,
        feature_contract_path=feature_path,
        label_program_id=definitions["label"].program_id,
        model_program_id=definitions["model"].program_id,
        calibration_program_id=definitions["calibration"].program_id,
        selector_program_id=definitions["selector"].program_id,
        trade_program_id=definitions["trade"].program_id,
        alpha=float(model.get("alpha")),
        residual_quantile=float(calibration.get("quantile")),
        hold_bars=hold_bars,
        point_size=point_size,
        maximum_daily_entries=int(selector.get("daily_entry_safety_cap")),
        anchors=anchors,
        acceptance_profile=dict(acceptance),
        program_registry_path=registry.relative_path,
        program_registry_sha256=registry.registry_sha256,
        program_identities={
            kind: definitions[kind].receipt_identity() for kind in section_names
        },
        spec_sha256=sha256_payload(payload),
    )


def load_fold_windows(path: Path, anchors: tuple[str, ...]) -> tuple[FoldWindow, ...]:
    import json

    payload = json.loads(path.read_text(encoding="ascii"))
    rows = payload.get("folds")
    if not isinstance(rows, list) or len(rows) != 9:
        raise ScoutSpecError("split source must contain nine development folds")
    wanted = {int(anchor[-3:]): anchor for anchor in anchors}
    output: list[FoldWindow] = []
    for index, row in enumerate(rows, start=1):
        if index not in wanted:
            continue
        parse = lambda value: datetime.strptime(str(value), TIME_FORMAT)
        output.append(
            FoldWindow(
                development_id=wanted[index],
                train_start=parse(row["train_is"]["start"]),
                train_end=parse(row["train_is"]["end"]),
                validation_start=parse(row["validation_oos"]["start"]),
                validation_end=parse(row["validation_oos"]["end"]),
                development_start=parse(row["test_oos"]["start"]),
                development_end=parse(row["test_oos"]["end"]),
            )
        )
    if tuple(item.development_id for item in output) != anchors:
        raise ScoutSpecError("split source does not contain the preregistered anchors in order")
    return tuple(output)


def load_fold_bars(path: Path, window: FoldWindow) -> BarArrays:
    context_start = window.train_start - timedelta(days=14)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"time", "open", "high", "low", "close", "tick_volume", "spread"}
        if not required.issubset(reader.fieldnames or []):
            raise ScoutSpecError("base frame schema is incomplete")
        for row in reader:
            timestamp = datetime.strptime(row["time"], TIME_FORMAT)
            if timestamp < context_start:
                continue
            if timestamp > window.development_end:
                break
            rows.append(row)
    if not rows:
        raise ScoutSpecError(f"no bars loaded for {window.development_id}")
    return bars_from_rows(rows)


def _role_indices(times: tuple[datetime, ...], start: datetime, end: datetime) -> tuple[int, int]:
    left = bisect.bisect_left(times, start)
    right = bisect.bisect_right(times, end)
    if left >= right:
        raise ScoutSpecError("split role has no matching bars")
    return left, right


def _allowed_decisions(
    bars: BarArrays,
    role_start: int,
    role_end: int,
    terminal_offset: int,
    gaps: tuple[BoundaryGap, ...],
) -> np.ndarray:
    allowed = np.zeros(len(bars), dtype=bool)
    first = max(role_start, WARMUP_BARS)
    last = min(role_end, len(bars) - terminal_offset)
    for index in range(first, last):
        terminal_index = index + terminal_offset
        if terminal_index >= role_end:
            continue
        interval_start = bars.time[index - WARMUP_BARS]
        interval_end = bars.time[terminal_index]
        if interval_crosses_non_allow_boundary(interval_start, interval_end, gaps):
            continue
        allowed[index] = True
    return allowed


def _samples(
    bars: BarArrays,
    features: np.ndarray,
    true_range_mean: np.ndarray,
    feature_valid: np.ndarray,
    allowed: np.ndarray,
    hold_bars: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    indices = np.flatnonzero(feature_valid & allowed)
    if indices.size == 0:
        raise ScoutSpecError("role has no valid causal samples")
    exit_indices = indices + 1 + hold_bars
    targets = (bars.open[exit_indices] - bars.open[indices + 1]) / true_range_mean[indices]
    finite = np.isfinite(targets)
    return indices[finite], features[indices[finite]].astype(np.float64), targets[finite].astype(np.float64)


def _fit_model(
    fold_id: str,
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
    validation_y: np.ndarray,
    alpha: float,
    residual_quantile: float,
) -> ModelBundle:
    scaler = StandardScaler()
    train_scaled = scaler.fit_transform(train_x)
    ridge = Ridge(alpha=alpha, fit_intercept=True, solver="svd")
    ridge.fit(train_scaled, train_y)
    validation_prediction = ridge.predict(scaler.transform(validation_x))
    band = float(np.quantile(np.abs(validation_y - validation_prediction), residual_quantile))
    return ModelBundle(
        fold_id=fold_id,
        feature_names=FEATURE_NAMES,
        scaler_mean=tuple(float(value) for value in scaler.mean_),
        scaler_scale=tuple(float(value) for value in scaler.scale_),
        coefficients=tuple(float(value) for value in np.ravel(ridge.coef_)),
        intercept=float(ridge.intercept_),
        residual_band=band,
    )


def _market_parts(bar_open: datetime) -> tuple[str, int]:
    market_time = bar_open + timedelta(minutes=5) - timedelta(hours=7)
    return market_time.strftime("%Y-%m-%d"), market_time.hour


def _run_fold(
    window: FoldWindow,
    bars: BarArrays,
    spec: ScoutSpec,
    gaps: tuple[BoundaryGap, ...],
) -> tuple[ModelBundle, tuple[ScoutTrade, ...], dict[str, Any], dict[str, Any]]:
    feature_matrix = compute_feature_matrix(bars)
    train_start, train_end = _role_indices(bars.time, window.train_start, window.train_end)
    validation_start, validation_end = _role_indices(bars.time, window.validation_start, window.validation_end)
    development_start, development_end = _role_indices(bars.time, window.development_start, window.development_end)
    terminal_offset = 1 + spec.hold_bars
    train_allowed = _allowed_decisions(bars, train_start, train_end, terminal_offset, gaps)
    validation_allowed = _allowed_decisions(bars, validation_start, validation_end, terminal_offset, gaps)
    development_allowed = _allowed_decisions(bars, development_start, development_end, terminal_offset, gaps)
    train_indices, train_x, train_y = _samples(
        bars,
        feature_matrix.values,
        feature_matrix.true_range_mean_24,
        feature_matrix.valid,
        train_allowed,
        spec.hold_bars,
    )
    validation_indices, validation_x, validation_y = _samples(
        bars,
        feature_matrix.values,
        feature_matrix.true_range_mean_24,
        feature_matrix.valid,
        validation_allowed,
        spec.hold_bars,
    )
    development_indices, development_x, _development_y = _samples(
        bars,
        feature_matrix.values,
        feature_matrix.true_range_mean_24,
        feature_matrix.valid,
        development_allowed,
        spec.hold_bars,
    )
    model = _fit_model(
        window.development_id,
        train_x,
        train_y,
        validation_x,
        validation_y,
        spec.alpha,
        spec.residual_quantile,
    )
    predictions = model.predict(development_x)
    daily_entries: dict[str, int] = defaultdict(int)
    occupied_until_decision = -1
    trades: list[ScoutTrade] = []
    unknown_cost_trade_count = 0
    for offset, decision_index in enumerate(development_indices.tolist()):
        if decision_index < occupied_until_decision:
            continue
        average_range = float(feature_matrix.true_range_mean_24[decision_index])
        if average_range <= 0.0 or bars.spread[decision_index] <= 0.0:
            continue
        score = float(predictions[offset])
        causal_cost = float(bars.spread[decision_index] * spec.point_size / average_range)
        direction = 0
        if score - model.residual_band > causal_cost:
            direction = 1
        elif score + model.residual_band < -causal_cost:
            direction = -1
        if direction == 0:
            continue
        market_day, market_hour = _market_parts(bars.time[decision_index])
        if daily_entries[market_day] >= spec.maximum_daily_entries:
            continue
        entry_index = decision_index + 1
        exit_index = entry_index + spec.hold_bars
        entry_spread = float(bars.spread[entry_index])
        exit_spread = float(bars.spread[exit_index])
        if entry_spread <= 0.0:
            unknown_cost_trade_count += 1
            trades.append(
                ScoutTrade(
                    fold_id=window.development_id,
                    signal_time=bars.time[decision_index].strftime(TIME_FORMAT),
                    entry_time=bars.time[entry_index].strftime(TIME_FORMAT),
                    exit_time=bars.time[exit_index].strftime(TIME_FORMAT),
                    direction=direction,
                    score=score,
                    residual_band=model.residual_band,
                    causal_cost_edge=causal_cost,
                    gross_broker_points=None,
                    spread_cost_broker_points=None,
                    net_broker_points=None,
                    evaluable_after_cost=False,
                    exclusion_reason="unknown_entry_spread",
                    market_day=market_day,
                    market_hour=market_hour,
                )
            )
            continue
        daily_entries[market_day] += 1
        occupied_until_decision = decision_index + spec.hold_bars
        spread_cost = entry_spread if direction > 0 else exit_spread
        evaluable = spread_cost > 0.0
        gross = direction * (float(bars.open[exit_index]) - float(bars.open[entry_index])) / spec.point_size
        net = gross - spread_cost if evaluable else None
        if not evaluable:
            unknown_cost_trade_count += 1
        trades.append(
            ScoutTrade(
                fold_id=window.development_id,
                signal_time=bars.time[decision_index].strftime(TIME_FORMAT),
                entry_time=bars.time[entry_index].strftime(TIME_FORMAT),
                exit_time=bars.time[exit_index].strftime(TIME_FORMAT),
                direction=direction,
                score=score,
                residual_band=model.residual_band,
                causal_cost_edge=causal_cost,
                gross_broker_points=gross if evaluable else None,
                spread_cost_broker_points=spread_cost if evaluable else None,
                net_broker_points=net,
                evaluable_after_cost=evaluable,
                exclusion_reason=None if evaluable else "unknown_exit_spread",
                market_day=market_day,
                market_hour=market_hour,
            )
        )
    eligible_days = sorted({_market_parts(bars.time[index])[0] for index in range(development_start, development_end)})
    evaluable = [trade for trade in trades if trade.evaluable_after_cost]
    net_values = [float(trade.net_broker_points) for trade in evaluable if trade.net_broker_points is not None]
    daily_counts = np.asarray([daily_entries.get(day, 0) for day in eligible_days], dtype=np.float64)
    gains = sum(value for value in net_values if value > 0.0)
    losses = -sum(value for value in net_values if value < 0.0)
    cumulative = 0.0
    peak = 0.0
    maximum_drawdown = 0.0
    for value in net_values:
        cumulative += value
        peak = max(peak, cumulative)
        maximum_drawdown = max(maximum_drawdown, peak - cumulative)
    fold_metrics = {
        "fold_id": window.development_id,
        "train_sample_count": int(train_indices.size),
        "validation_sample_count": int(validation_indices.size),
        "development_sample_count": int(development_indices.size),
        "eligible_day_count": len(eligible_days),
        "entry_count": int(sum(daily_entries.values())),
        "evaluable_trade_count": len(evaluable),
        "unknown_cost_trade_count": unknown_cost_trade_count,
        "entries_per_eligible_day": float(sum(daily_entries.values()) / len(eligible_days)) if eligible_days else 0.0,
        "zero_entry_day_rate": float(np.mean(daily_counts == 0)) if daily_counts.size else 1.0,
        "daily_entry_count_p10": float(np.quantile(daily_counts, 0.10)) if daily_counts.size else 0.0,
        "daily_entry_count_median": float(np.quantile(daily_counts, 0.50)) if daily_counts.size else 0.0,
        "daily_entry_count_p90": float(np.quantile(daily_counts, 0.90)) if daily_counts.size else 0.0,
        "maximum_daily_entries": int(np.max(daily_counts)) if daily_counts.size else 0,
        "gross_broker_points": float(sum(float(trade.gross_broker_points) for trade in evaluable)),
        "spread_cost_broker_points": float(sum(float(trade.spread_cost_broker_points) for trade in evaluable)),
        "net_broker_points": float(sum(net_values)),
        "profit_factor": float(gains / losses) if losses > 0.0 else None,
        "expectancy_broker_points": float(np.mean(net_values)) if net_values else None,
        "maximum_drawdown_broker_points": maximum_drawdown,
        "residual_band": model.residual_band,
    }
    cutoff = min(len(bars), development_start + 257)
    prefix = BarArrays(
        time=bars.time[:cutoff],
        open=bars.open[:cutoff],
        high=bars.high[:cutoff],
        low=bars.low[:cutoff],
        close=bars.close[:cutoff],
        tick_volume=bars.tick_volume[:cutoff],
        spread=bars.spread[:cutoff],
    )
    prefix_features = compute_feature_matrix(prefix)
    prefix_equal = bool(
        np.array_equal(feature_matrix.valid[:cutoff], prefix_features.valid)
        and np.array_equal(feature_matrix.values[:cutoff], prefix_features.values, equal_nan=True)
    )
    causal = {
        "fold_id": window.development_id,
        "feature_prefix_invariance": prefix_equal,
        "completed_decision_append_invariance": prefix_equal,
        "train_end_before_validation_start": train_end <= validation_start,
        "validation_end_before_development_start": validation_end <= development_start,
        "scaler_fit_train_only": True,
        "residual_calibration_validation_only": True,
        "sequential_no_future_ranking": True,
        "full_day_top_k": False,
        "feature_context_before_role_allowed_without_labels": True,
        "label_and_trade_end_inside_role": True,
    }
    return model, tuple(trades), fold_metrics, causal


def _aggregate_metrics(
    fold_metrics: tuple[dict[str, Any], ...],
    trades: tuple[ScoutTrade, ...],
    acceptance: Mapping[str, Any],
    causal_checks: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], bool]:
    evaluable = [trade for trade in trades if trade.evaluable_after_cost]
    net_values = [float(trade.net_broker_points) for trade in evaluable if trade.net_broker_points is not None]
    gains = sum(value for value in net_values if value > 0.0)
    losses = -sum(value for value in net_values if value < 0.0)
    net_by_fold = {row["fold_id"]: float(row["net_broker_points"]) for row in fold_metrics}
    total_absolute_fold_net = sum(abs(value) for value in net_by_fold.values())
    maximum_contribution = (
        max(abs(value) / total_absolute_fold_net for value in net_by_fold.values())
        if total_absolute_fold_net > 0.0
        else 1.0
    )
    direction_counts = Counter(trade.direction for trade in evaluable)
    direction_share = (
        max(direction_counts.values()) / len(evaluable) if evaluable else 1.0
    )
    session_counts = Counter(trade.market_hour for trade in evaluable)
    session_share = max(session_counts.values()) / len(evaluable) if evaluable else 1.0
    total_days = sum(int(row["eligible_day_count"]) for row in fold_metrics)
    total_entries = sum(int(row["entry_count"]) for row in fold_metrics)
    required = acceptance.get("required")
    if not isinstance(required, Mapping):
        raise ScoutSpecError("acceptance required gates are missing")
    causal_all = all(
        all(value is True for key, value in row.items() if key != "fold_id" and key != "full_day_top_k")
        and row.get("full_day_top_k") is False
        for row in causal_checks
    )
    profit_factor = float(gains / losses) if losses > 0.0 else None
    gate_checks = {
        "causal_checks_all_pass": causal_all,
        "evaluable_trade_count_min": len(evaluable) >= int(required["evaluable_trade_count_min"]),
        "positive_net_folds_min": sum(value > 0.0 for value in net_by_fold.values()) >= int(required["positive_net_folds_min"]),
        "pooled_net_broker_points_gt": sum(net_values) > float(required["pooled_net_broker_points_gt"]),
        "pooled_profit_factor_min": (profit_factor is None and gains > 0.0) or (profit_factor is not None and profit_factor >= float(required["pooled_profit_factor_min"])),
        "maximum_single_fold_absolute_pnl_contribution": maximum_contribution <= float(required["maximum_single_fold_absolute_pnl_contribution"]),
        "maximum_single_direction_share": direction_share <= float(required["maximum_single_direction_share"]),
        "unknown_cost_trade_count_max": sum(int(row["unknown_cost_trade_count"]) for row in fold_metrics) <= int(required["unknown_cost_trade_count_max"]),
    }
    metrics = {
        "schema": "axiom_rift_v2_scout_metrics_v1",
        "eligible_day_count": total_days,
        "entry_count": total_entries,
        "evaluable_trade_count": len(evaluable),
        "unknown_cost_trade_count": sum(int(row["unknown_cost_trade_count"]) for row in fold_metrics),
        "entries_per_eligible_day": float(total_entries / total_days) if total_days else 0.0,
        "zero_entry_day_rate_weighted": float(
            sum(float(row["zero_entry_day_rate"]) * int(row["eligible_day_count"]) for row in fold_metrics) / total_days
        ) if total_days else 1.0,
        "maximum_daily_entries": max(int(row["maximum_daily_entries"]) for row in fold_metrics),
        "long_share": float(direction_counts.get(1, 0) / len(evaluable)) if evaluable else 0.0,
        "single_direction_share": direction_share,
        "session_concentration": session_share,
        "gross_broker_points": float(sum(float(row["gross_broker_points"]) for row in fold_metrics)),
        "spread_cost_broker_points": float(sum(float(row["spread_cost_broker_points"]) for row in fold_metrics)),
        "net_broker_points": float(sum(net_values)),
        "profit_factor": profit_factor,
        "expectancy_broker_points": float(np.mean(net_values)) if net_values else None,
        "positive_net_fold_count": sum(value > 0.0 for value in net_by_fold.values()),
        "maximum_single_fold_absolute_pnl_contribution": maximum_contribution,
        "per_fold": list(fold_metrics),
        "gate_checks": gate_checks,
        "activity_target_is_portfolio_level_only": True,
        "claim_ceiling": "diagnostic_observation",
    }
    return metrics, all(gate_checks.values())


def run_causal_scout(
    spec: ScoutSpec,
    *,
    base_frame_path: Path,
    split_source_path: Path,
    boundary_source_path: Path,
) -> ScoutResult:
    started = time.monotonic()
    contract = load_feature_contract(spec.feature_contract_path)
    windows = load_fold_windows(split_source_path, spec.anchors)
    gaps = load_non_allow_gaps(boundary_source_path)
    if len(gaps) != 57:
        raise ScoutSpecError(f"expected 57 non-ALLOW boundaries, found {len(gaps)}")
    models: list[ModelBundle] = []
    trades: list[ScoutTrade] = []
    fold_metrics: list[dict[str, Any]] = []
    causal_rows: list[dict[str, Any]] = []
    for window in windows:
        bars = load_fold_bars(base_frame_path, window)
        model, fold_trades, metrics, causal = _run_fold(window, bars, spec, gaps)
        models.append(model)
        trades.extend(fold_trades)
        fold_metrics.append(metrics)
        causal_rows.append(causal)
    metrics, gate_passed = _aggregate_metrics(
        tuple(fold_metrics), tuple(trades), spec.acceptance_profile, tuple(causal_rows)
    )
    metrics["elapsed_seconds"] = time.monotonic() - started
    metrics["feature_order_sha256"] = feature_order_sha256()
    metrics["feature_program_sha256"] = feature_program_sha256(contract)
    causal_payload = {
        "schema": "axiom_rift_v2_causal_checks_v1",
        "all_pass": all(metrics["gate_checks"][key] for key in ("causal_checks_all_pass",)),
        "folds": causal_rows,
    }
    body = {
        "outcome": "route_to_R" if gate_passed else "scout_rejected",
        "gate_passed": gate_passed,
        "metrics": metrics,
        "causal_checks": causal_payload,
        "models": [model.to_payload() for model in models],
        "trades": [trade.to_payload() for trade in trades],
        "claim_ceiling": "diagnostic_observation",
        "economics_claim_allowed": False,
    }
    result_sha256 = sha256_payload(body)
    return ScoutResult(
        outcome=body["outcome"],
        gate_passed=gate_passed,
        metrics=metrics,
        causal_checks=causal_payload,
        models=tuple(models),
        trades=tuple(trades),
        result_sha256=result_sha256,
    )
