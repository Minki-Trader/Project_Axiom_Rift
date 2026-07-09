"""Canonical causal completed-bar feature computation for V2."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

from axiom_rift.v2.identity import sha256_payload


FEATURE_NAMES = (
    "log_return_1",
    "log_return_3",
    "log_return_12",
    "realized_vol_12",
    "realized_vol_48",
    "true_range_ratio_24",
    "body_ratio_24",
    "close_location",
    "tick_volume_z_48",
    "spread_ratio_24",
    "time_of_day_sin",
    "time_of_day_cos",
)
FEATURE_DTYPE = "float32"
FEATURE_SHAPE = (len(FEATURE_NAMES),)
WARMUP_BARS = 48


class FeatureContractError(ValueError):
    """Raised when a feature contract or input violates causal requirements."""


@dataclass(frozen=True)
class BarArrays:
    time: tuple[datetime, ...]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    tick_volume: np.ndarray
    spread: np.ndarray

    def __len__(self) -> int:
        return len(self.time)


@dataclass(frozen=True)
class FeatureMatrix:
    values: np.ndarray
    valid: np.ndarray
    reasons: tuple[str, ...]
    true_range_mean_24: np.ndarray
    feature_order_sha256: str


def feature_order_sha256() -> str:
    return sha256_payload(
        {
            "dtype": FEATURE_DTYPE,
            "names": list(FEATURE_NAMES),
            "shape": list(FEATURE_SHAPE),
        }
    )


def load_feature_contract(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="ascii"))
    if not isinstance(payload, dict):
        raise FeatureContractError("feature contract must be a mapping")
    names = tuple(row.get("name") for row in payload.get("features", []) if isinstance(row, dict))
    if names != FEATURE_NAMES:
        raise FeatureContractError("feature names or order differ from the canonical engine")
    if payload.get("warmup_bars") != WARMUP_BARS:
        raise FeatureContractError("feature warmup differs from the canonical engine")
    output = payload.get("output")
    if not isinstance(output, dict):
        raise FeatureContractError("feature output contract is missing")
    if output.get("dtype") != FEATURE_DTYPE or tuple(output.get("shape", [])) != FEATURE_SHAPE:
        raise FeatureContractError("feature dtype or shape differs from the canonical engine")
    if output.get("feature_order_sha256") != feature_order_sha256():
        raise FeatureContractError("feature order hash differs from the canonical engine")
    if payload.get("zero_spread_behavior") != "reject_as_unknown_cost":
        raise FeatureContractError("zero spread must be rejected as unknown cost")
    if payload.get("real_volume_eligible") is not False:
        raise FeatureContractError("real_volume is not eligible for the V2 base dataset")
    return payload


def feature_program_sha256(contract: Mapping[str, Any]) -> str:
    return sha256_payload(dict(contract))


def bars_from_rows(rows: Sequence[Mapping[str, Any]]) -> BarArrays:
    times: list[datetime] = []
    fields: dict[str, list[float]] = {
        "open": [],
        "high": [],
        "low": [],
        "close": [],
        "tick_volume": [],
        "spread": [],
    }
    previous: datetime | None = None
    for row in rows:
        raw_time = row["time"]
        timestamp = raw_time if isinstance(raw_time, datetime) else datetime.strptime(str(raw_time), "%Y-%m-%d %H:%M:%S")
        if previous is not None and timestamp <= previous:
            raise FeatureContractError("bar times must be strictly increasing")
        previous = timestamp
        times.append(timestamp)
        for field in fields:
            fields[field].append(float(row[field]))
    arrays = {name: np.asarray(values, dtype=np.float64) for name, values in fields.items()}
    return BarArrays(time=tuple(times), **arrays)


def compute_feature_matrix(bars: BarArrays) -> FeatureMatrix:
    size = len(bars)
    values = np.full((size, len(FEATURE_NAMES)), np.nan, dtype=np.float32)
    valid = np.zeros(size, dtype=bool)
    reasons = ["warmup" for _ in range(size)]
    mean_true_range = np.full(size, np.nan, dtype=np.float64)
    if size == 0:
        return FeatureMatrix(values, valid, tuple(reasons), mean_true_range, feature_order_sha256())
    numeric = np.column_stack((bars.open, bars.high, bars.low, bars.close, bars.tick_volume, bars.spread))
    if not np.isfinite(numeric).all():
        raise FeatureContractError("bar input contains non-finite values")
    if np.any(bars.open <= 0.0) or np.any(bars.high <= 0.0) or np.any(bars.low <= 0.0) or np.any(bars.close <= 0.0):
        raise FeatureContractError("bar prices must be positive")
    true_range = np.full(size, np.nan, dtype=np.float64)
    if size > 1:
        true_range[1:] = np.maximum.reduce(
            (
                bars.high[1:] - bars.low[1:],
                np.abs(bars.high[1:] - bars.close[:-1]),
                np.abs(bars.low[1:] - bars.close[:-1]),
            )
        )
    one_bar_return = np.full(size, np.nan, dtype=np.float64)
    if size > 1:
        one_bar_return[1:] = np.log(bars.close[1:] / bars.close[:-1])
    for index in range(WARMUP_BARS, size):
        spread_window = bars.spread[index - 23 : index + 1]
        if np.any(spread_window <= 0.0):
            reasons[index] = "unknown_cost_zero_spread"
            continue
        range_window = true_range[index - 23 : index + 1]
        average_range = float(np.mean(range_window))
        bar_range = float(bars.high[index] - bars.low[index])
        volume_window = bars.tick_volume[index - 47 : index + 1]
        volume_std = float(np.std(volume_window, ddof=0))
        if not math.isfinite(average_range) or average_range <= 0.0:
            reasons[index] = "invalid_true_range"
            continue
        if bar_range <= 0.0:
            reasons[index] = "zero_bar_range"
            continue
        if volume_std <= 0.0:
            reasons[index] = "zero_tick_volume_scale"
            continue
        decision_time = bars.time[index] + timedelta(minutes=5)
        new_york_time = decision_time - timedelta(hours=7)
        minute = new_york_time.hour * 60 + new_york_time.minute
        angle = 2.0 * math.pi * minute / 1440.0
        row = (
            math.log(bars.close[index] / bars.close[index - 1]),
            math.log(bars.close[index] / bars.close[index - 3]),
            math.log(bars.close[index] / bars.close[index - 12]),
            float(np.std(one_bar_return[index - 11 : index + 1], ddof=0)),
            float(np.std(one_bar_return[index - 47 : index + 1], ddof=0)),
            float(true_range[index] / average_range),
            float(abs(bars.close[index] - bars.open[index]) / average_range),
            float((bars.close[index] - bars.low[index]) / bar_range),
            float((bars.tick_volume[index] - float(np.mean(volume_window))) / volume_std),
            float(bars.spread[index] / float(np.mean(spread_window))),
            math.sin(angle),
            math.cos(angle),
        )
        if not all(math.isfinite(item) for item in row):
            reasons[index] = "nonfinite_feature"
            continue
        values[index] = np.asarray(row, dtype=np.float32)
        valid[index] = True
        reasons[index] = "ok"
        mean_true_range[index] = average_range
    return FeatureMatrix(values, valid, tuple(reasons), mean_true_range, feature_order_sha256())
