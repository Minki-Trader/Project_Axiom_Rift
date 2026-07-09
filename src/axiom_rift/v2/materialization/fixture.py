"""Deterministic non-economic fixture for Python, ONNX, MQL5, and lifecycle parity."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from axiom_rift.v2.features import FEATURE_NAMES, BarArrays, compute_feature_matrix
from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.materialization.linear_onnx import LinearModelBundle, onnx_scores, python_scores


FIXTURE_THRESHOLD = 0.25
FIXTURE_HOLD_BARS = 6
FIXTURE_MAX_DAILY_ENTRIES = 10


@dataclass(frozen=True)
class FixtureDecision:
    index: int
    time: str
    features: tuple[float, ...]
    score: float
    raw_direction: int
    admitted_direction: int
    active_direction: int
    event: str


def reference_linear_bundle() -> LinearModelBundle:
    return LinearModelBundle(
        mean=(0.0,) * len(FEATURE_NAMES),
        scale=(0.002, 0.004, 0.012, 0.001, 0.001, 1.0, 0.5, 0.5, 1.0, 1.0, 1.0, 1.0),
        coefficient=(0.08, -0.05, 0.04, -0.03, 0.02, 0.08, 0.05, 0.07, 0.12, -0.04, 0.32, -0.18),
        intercept=0.0,
    )


def synthetic_fixture_bars(count: int = 120) -> BarArrays:
    if count < 60:
        raise ValueError("fixture requires at least 60 bars")
    start = datetime(2026, 1, 12, 8, 0, 0)
    rows: list[dict[str, Any]] = []
    previous_close = 20000.0
    for index in range(count):
        opening = previous_close + 0.10 * math.sin(index * 0.41)
        movement = 0.35 + 0.95 * math.sin(index * 0.27) + 0.25 * math.cos(index * 0.11)
        close = opening + movement
        high = max(opening, close) + 0.8 + 0.07 * (index % 5)
        low = min(opening, close) - 0.75 - 0.05 * (index % 7)
        rows.append(
            {
                "time": start + timedelta(minutes=5 * index),
                "open": opening,
                "high": high,
                "low": low,
                "close": close,
                "tick_volume": 100 + ((index * 17) % 43) + int(round(3 * math.sin(index * 0.19))),
                "spread": 75 + (index % 9),
            }
        )
        previous_close = close
    from axiom_rift.v2.features import bars_from_rows

    return bars_from_rows(rows)


def write_fixture_bars(path: Path, bars: BarArrays) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"))
        for index, timestamp in enumerate(bars.time):
            writer.writerow(
                (
                    timestamp.strftime("%Y.%m.%d %H:%M:%S"),
                    f"{bars.open[index]:.12f}",
                    f"{bars.high[index]:.12f}",
                    f"{bars.low[index]:.12f}",
                    f"{bars.close[index]:.12f}",
                    str(int(bars.tick_volume[index])),
                    f"{bars.spread[index]:.0f}",
                    "0",
                )
            )
    return path


def evaluate_fixture(
    bars: BarArrays,
    bundle: LinearModelBundle,
    *,
    onnx_path: Path | None = None,
    threshold: float = FIXTURE_THRESHOLD,
    hold_bars: int = FIXTURE_HOLD_BARS,
    max_daily_entries: int = FIXTURE_MAX_DAILY_ENTRIES,
) -> tuple[FixtureDecision, ...]:
    matrix = compute_feature_matrix(bars)
    valid_indices = np.flatnonzero(matrix.valid)
    direct_scores = python_scores(matrix.values[valid_indices], bundle)
    if onnx_path is not None:
        runtime_scores = onnx_scores(onnx_path, matrix.values[valid_indices])
        if not np.allclose(direct_scores, runtime_scores, rtol=0.0, atol=1e-6):
            raise ValueError("Python and ONNX fixture scores differ")
    active_direction = 0
    entry_signal_index: int | None = None
    entries_by_day: dict[str, int] = {}
    output: list[FixtureDecision] = []
    for offset, index in enumerate(valid_indices.tolist()):
        event_parts: list[str] = []
        if active_direction and entry_signal_index is not None and index - entry_signal_index >= hold_bars:
            active_direction = 0
            entry_signal_index = None
            event_parts.append("exit")
        score = float(direct_scores[offset])
        raw_direction = 1 if score > threshold else -1 if score < -threshold else 0
        admitted = 0
        decision_time = bars.time[index] + timedelta(minutes=5)
        market_time = decision_time - timedelta(hours=7)
        day = market_time.strftime("%Y-%m-%d")
        if active_direction == 0 and raw_direction != 0 and entries_by_day.get(day, 0) < max_daily_entries:
            admitted = raw_direction
            active_direction = raw_direction
            entry_signal_index = index
            entries_by_day[day] = entries_by_day.get(day, 0) + 1
            event_parts.append("enter")
        event = "_then_".join(event_parts) if event_parts else ("hold" if active_direction else "flat")
        output.append(
            FixtureDecision(
                index=index,
                time=bars.time[index].strftime("%Y.%m.%d %H:%M:%S"),
                features=tuple(float(value) for value in matrix.values[index]),
                score=score,
                raw_direction=raw_direction,
                admitted_direction=admitted,
                active_direction=active_direction,
                event=event,
            )
        )
    return tuple(output)


def write_fixture_expected(path: Path, rows: Iterable[FixtureDecision]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["index", "time", *[f"f{index}" for index in range(len(FEATURE_NAMES))], "score", "raw_direction", "admitted_direction", "active_direction", "event"]
    with path.open("w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            payload: dict[str, Any] = {
                "index": row.index,
                "time": row.time,
                "score": f"{row.score:.9f}",
                "raw_direction": row.raw_direction,
                "admitted_direction": row.admitted_direction,
                "active_direction": row.active_direction,
                "event": row.event,
            }
            payload.update({f"f{index}": f"{value:.9f}" for index, value in enumerate(row.features)})
            writer.writerow(payload)
    return path


def fixture_identity(rows: Iterable[FixtureDecision]) -> str:
    return sha256_payload(
        [
            {
                "active_direction": row.active_direction,
                "admitted_direction": row.admitted_direction,
                "event": row.event,
                "features": list(row.features),
                "index": row.index,
                "raw_direction": row.raw_direction,
                "score": row.score,
                "time": row.time,
            }
            for row in rows
        ]
    )
