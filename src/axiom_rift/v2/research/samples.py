"""Fold-isolated label construction and explicit boundary purge hooks."""

from __future__ import annotations

from dataclasses import dataclass

from axiom_rift.v2.research.features import FeatureRow, build_feature_rows
from axiom_rift.v2.research.specs import (
    Bar,
    BoundaryPurge,
    FeatureSpec,
    IndexBoundary,
    LabelSpec,
)


@dataclass(frozen=True)
class SupervisedSample:
    decision_index: int
    decision_timestamp: str
    features: tuple[float, ...]
    target: float


def label_crosses_end(decision_index: int, horizon_bars: int, boundary: IndexBoundary) -> bool:
    return decision_index + horizon_bars >= boundary.end


def label_value(bars: tuple[Bar, ...], decision_index: int, spec: LabelSpec) -> float:
    """Return next-bid-open to fixed-horizon-bid-close return."""

    if spec.name != "next_open_to_close_return":
        raise ValueError(f"label is not implemented: {spec.name}")
    entry = bars[decision_index + 1].open_bid
    exit_bid = bars[decision_index + spec.horizon_bars].close_bid
    if entry == 0:
        raise ValueError("zero bid entry price cannot define a return label")
    return exit_bid / entry - 1.0


def build_supervised_samples(
    bars: tuple[Bar, ...],
    feature_spec: FeatureSpec,
    label_spec: LabelSpec,
    boundary: IndexBoundary,
    purge: BoundaryPurge,
) -> tuple[SupervisedSample, ...]:
    rows = build_feature_rows(bars, feature_spec, boundary, purge)
    samples: list[SupervisedSample] = []
    for row in rows:
        if row.decision_index + label_spec.horizon_bars >= len(bars):
            continue
        if purge.purge_label_horizon_at_end and label_crosses_end(
            row.decision_index, label_spec.horizon_bars, boundary
        ):
            continue
        samples.append(
            SupervisedSample(
                decision_index=row.decision_index,
                decision_timestamp=row.decision_timestamp,
                features=row.values,
                target=float(label_value(bars, row.decision_index, label_spec)),
            )
        )
    return tuple(samples)
