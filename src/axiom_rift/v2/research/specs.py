"""Declarative, whitelisted specifications for the V2 research core."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


ALLOWED_FEATURES = frozenset(
    {
        "body_fraction",
        "momentum_3",
        "range_fraction",
        "return_1",
        "volume_ratio_5",
    }
)
ALLOWED_LABELS = frozenset({"next_open_to_close_return"})
ALLOWED_MODELS = frozenset({"ridge"})
ALLOWED_SELECTORS = frozenset({"sequential_residual_band"})
ALLOWED_TRADE_SHAPES = frozenset({"fixed_horizon"})


class ResearchSpecError(ValueError):
    """Raised when a research specification exceeds the bounded whitelist."""


@dataclass(frozen=True)
class Bar:
    """One completed bid OHLC bar with its observed broker spread."""

    timestamp: str
    open_bid: float
    high_bid: float
    low_bid: float
    close_bid: float
    spread_points: float
    tick_volume: float

    def __post_init__(self) -> None:
        numeric = (
            self.open_bid,
            self.high_bid,
            self.low_bid,
            self.close_bid,
            self.spread_points,
            self.tick_volume,
        )
        if not self.timestamp:
            raise ResearchSpecError("bar timestamp is required")
        if not all(math.isfinite(value) for value in numeric):
            raise ResearchSpecError("bar values must be finite")
        if self.high_bid < max(self.open_bid, self.close_bid):
            raise ResearchSpecError("bid high is below the bid body")
        if self.low_bid > min(self.open_bid, self.close_bid):
            raise ResearchSpecError("bid low is above the bid body")
        if self.high_bid < self.low_bid:
            raise ResearchSpecError("bid high is below bid low")
        if self.spread_points < 0:
            raise ResearchSpecError("negative spread is invalid")
        if self.tick_volume < 0:
            raise ResearchSpecError("negative tick volume is invalid")

    def to_payload(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "open_bid": self.open_bid,
            "high_bid": self.high_bid,
            "low_bid": self.low_bid,
            "close_bid": self.close_bid,
            "spread_points": self.spread_points,
            "tick_volume": self.tick_volume,
        }


@dataclass(frozen=True)
class IndexBoundary:
    """Half-open bar-index boundary for one isolated data role."""

    role: str
    start: int
    end: int

    def validate(self, bar_count: int) -> None:
        if not self.role:
            raise ResearchSpecError("boundary role is required")
        if self.start < 0 or self.end <= self.start or self.end > bar_count:
            raise ResearchSpecError(
                f"invalid {self.role} boundary [{self.start}, {self.end}) for {bar_count} bars"
            )

    def to_payload(self) -> dict[str, Any]:
        return {"role": self.role, "start": self.start, "end": self.end}


@dataclass(frozen=True)
class BoundaryPurge:
    """Explicit hooks that prevent feature, label, or trade boundary crossing."""

    purge_feature_lookback_at_start: bool = True
    purge_label_horizon_at_end: bool = True
    purge_trade_horizon_at_end: bool = True

    def to_payload(self) -> dict[str, bool]:
        return {
            "purge_feature_lookback_at_start": self.purge_feature_lookback_at_start,
            "purge_label_horizon_at_end": self.purge_label_horizon_at_end,
            "purge_trade_horizon_at_end": self.purge_trade_horizon_at_end,
        }


@dataclass(frozen=True)
class FeatureSpec:
    names: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "names", tuple(self.names))
        if not self.names:
            raise ResearchSpecError("at least one feature is required")
        if len(set(self.names)) != len(self.names):
            raise ResearchSpecError("feature names must be unique")
        unknown = sorted(set(self.names) - ALLOWED_FEATURES)
        if unknown:
            raise ResearchSpecError(f"features are not whitelisted: {unknown}")

    def to_payload(self) -> dict[str, Any]:
        return {"names": list(self.names)}


@dataclass(frozen=True)
class LabelSpec:
    name: str = "next_open_to_close_return"
    horizon_bars: int = 2

    def __post_init__(self) -> None:
        if self.name not in ALLOWED_LABELS:
            raise ResearchSpecError(f"label is not whitelisted: {self.name}")
        if self.horizon_bars < 1:
            raise ResearchSpecError("label horizon must be positive")

    def to_payload(self) -> dict[str, Any]:
        return {"name": self.name, "horizon_bars": self.horizon_bars}


@dataclass(frozen=True)
class ModelSpec:
    family: str = "ridge"
    alpha: float = 1.0
    residual_alpha: float = 0.2

    def __post_init__(self) -> None:
        if self.family not in ALLOWED_MODELS:
            raise ResearchSpecError(f"model is not whitelisted: {self.family}")
        if not math.isfinite(self.alpha) or self.alpha <= 0:
            raise ResearchSpecError("ridge alpha must be positive and finite")
        if not math.isfinite(self.residual_alpha) or not 0 < self.residual_alpha < 1:
            raise ResearchSpecError("residual_alpha must be between zero and one")

    def to_payload(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "alpha": self.alpha,
            "residual_alpha": self.residual_alpha,
        }


@dataclass(frozen=True)
class SelectorSpec:
    kind: str = "sequential_residual_band"
    minimum_edge: float = 0.0
    allow_long: bool = True
    allow_short: bool = True

    def __post_init__(self) -> None:
        if self.kind not in ALLOWED_SELECTORS:
            raise ResearchSpecError(f"selector is not whitelisted: {self.kind}")
        if not math.isfinite(self.minimum_edge) or self.minimum_edge < 0:
            raise ResearchSpecError("minimum edge must be nonnegative and finite")
        if not self.allow_long and not self.allow_short:
            raise ResearchSpecError("selector must allow at least one direction")

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "minimum_edge": self.minimum_edge,
            "allow_long": self.allow_long,
            "allow_short": self.allow_short,
        }


@dataclass(frozen=True)
class TradeSpec:
    kind: str = "fixed_horizon"
    hold_bars: int = 2
    point_size: float = 0.1
    commission_per_trade: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in ALLOWED_TRADE_SHAPES:
            raise ResearchSpecError(f"trade shape is not whitelisted: {self.kind}")
        if self.hold_bars < 1:
            raise ResearchSpecError("trade hold must be positive")
        if not math.isfinite(self.point_size) or self.point_size <= 0:
            raise ResearchSpecError("point size must be positive and finite")
        if self.commission_per_trade != 0.0:
            raise ResearchSpecError("FPMarkets US100 V2 discovery commission must remain zero")

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "hold_bars": self.hold_bars,
            "point_size": self.point_size,
            "commission_per_trade": self.commission_per_trade,
        }


@dataclass(frozen=True)
class ResearchSpec:
    features: FeatureSpec
    label: LabelSpec = LabelSpec()
    model: ModelSpec = ModelSpec()
    selector: SelectorSpec = SelectorSpec()
    trade: TradeSpec = TradeSpec()
    purge: BoundaryPurge = BoundaryPurge()

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_research_spec_v1",
            "features": self.features.to_payload(),
            "label": self.label.to_payload(),
            "model": self.model.to_payload(),
            "selector": self.selector.to_payload(),
            "trade": self.trade.to_payload(),
            "purge": self.purge.to_payload(),
        }
