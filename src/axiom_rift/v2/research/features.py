"""Causal completed-bar feature construction for the bounded V2 core."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Callable

from axiom_rift.v2.research.specs import Bar, BoundaryPurge, FeatureSpec, IndexBoundary


@dataclass(frozen=True)
class FeatureRow:
    decision_index: int
    decision_timestamp: str
    values: tuple[float, ...]


FeatureBuilder = Callable[[tuple[Bar, ...], int], float]


def _safe_denominator(value: float) -> float:
    return max(abs(value), 1e-12)


def _return_1(bars: tuple[Bar, ...], index: int) -> float:
    return bars[index].close_bid / _safe_denominator(bars[index - 1].close_bid) - 1.0


def _body_fraction(bars: tuple[Bar, ...], index: int) -> float:
    bar = bars[index]
    return (bar.close_bid - bar.open_bid) / max(bar.high_bid - bar.low_bid, 1e-12)


def _range_fraction(bars: tuple[Bar, ...], index: int) -> float:
    bar = bars[index]
    return (bar.high_bid - bar.low_bid) / _safe_denominator(bar.close_bid)


def _momentum_3(bars: tuple[Bar, ...], index: int) -> float:
    return bars[index].close_bid / _safe_denominator(bars[index - 3].close_bid) - 1.0


def _volume_ratio_5(bars: tuple[Bar, ...], index: int) -> float:
    window = bars[index - 4 : index + 1]
    mean_volume = fmean(bar.tick_volume for bar in window)
    if mean_volume <= 0:
        return 0.0
    return bars[index].tick_volume / mean_volume - 1.0


_FEATURE_BUILDERS: dict[str, tuple[int, FeatureBuilder]] = {
    "body_fraction": (1, _body_fraction),
    "momentum_3": (4, _momentum_3),
    "range_fraction": (1, _range_fraction),
    "return_1": (2, _return_1),
    "volume_ratio_5": (5, _volume_ratio_5),
}


def required_lookback(spec: FeatureSpec) -> int:
    """Return the number of completed bars needed by the widest feature."""

    return max(_FEATURE_BUILDERS[name][0] for name in spec.names)


def feature_crosses_start(decision_index: int, lookback: int, boundary: IndexBoundary) -> bool:
    return decision_index - lookback + 1 < boundary.start


def build_feature_rows(
    bars: tuple[Bar, ...],
    spec: FeatureSpec,
    boundary: IndexBoundary,
    purge: BoundaryPurge,
) -> tuple[FeatureRow, ...]:
    """Build features using only bars at or before each completed decision bar."""

    boundary.validate(len(bars))
    lookback = required_lookback(spec)
    rows: list[FeatureRow] = []
    for index in range(max(boundary.start, lookback - 1), boundary.end):
        if purge.purge_feature_lookback_at_start and feature_crosses_start(index, lookback, boundary):
            continue
        values = tuple(float(_FEATURE_BUILDERS[name][1](bars, index)) for name in spec.names)
        rows.append(FeatureRow(index, bars[index].timestamp, values))
    return tuple(rows)
