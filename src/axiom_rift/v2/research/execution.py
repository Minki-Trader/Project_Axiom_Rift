"""Sequential admission and fixed-horizon bid/spread simulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from axiom_rift.v2.research.features import FeatureRow
from axiom_rift.v2.research.modeling import ValidationBand
from axiom_rift.v2.research.specs import (
    Bar,
    BoundaryPurge,
    IndexBoundary,
    SelectorSpec,
    TradeSpec,
)


class UnknownCostError(ValueError):
    """Raised when zero spread makes execution cost unknown rather than free."""


@dataclass(frozen=True)
class Signal:
    decision_index: int
    decision_timestamp: str
    direction: int
    score: float
    lower_score: float
    upper_score: float
    entry_index: int
    exit_index: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "decision_index": self.decision_index,
            "decision_timestamp": self.decision_timestamp,
            "direction": self.direction,
            "score": self.score,
            "lower_score": self.lower_score,
            "upper_score": self.upper_score,
            "entry_index": self.entry_index,
            "exit_index": self.exit_index,
        }


@dataclass(frozen=True)
class Trade:
    decision_index: int
    entry_index: int
    exit_index: int
    direction: int
    entry_price: float
    exit_price: float
    gross_bid_move: float
    spread_cost: float
    commission: float
    net_pnl: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "decision_index": self.decision_index,
            "entry_index": self.entry_index,
            "exit_index": self.exit_index,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "gross_bid_move": self.gross_bid_move,
            "spread_cost": self.spread_cost,
            "commission": self.commission,
            "net_pnl": self.net_pnl,
        }


@dataclass(frozen=True)
class SimulationResult:
    trades: tuple[Trade, ...]
    net_pnl: float
    gross_bid_move: float
    spread_cost: float
    commission: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "trades": [trade.to_payload() for trade in self.trades],
            "net_pnl": self.net_pnl,
            "gross_bid_move": self.gross_bid_move,
            "spread_cost": self.spread_cost,
            "commission": self.commission,
        }


def assert_known_spreads(bars: tuple[Bar, ...]) -> None:
    if any(bar.spread_points == 0 for bar in bars):
        raise UnknownCostError("zero spread is unknown cost and cannot be treated as free execution")


def trade_crosses_end(decision_index: int, hold_bars: int, boundary: IndexBoundary) -> bool:
    return decision_index + hold_bars >= boundary.end


def select_sequential(
    scored_rows: Iterable[tuple[FeatureRow, float]],
    validation_band: ValidationBand,
    selector_spec: SelectorSpec,
    trade_spec: TradeSpec,
    boundary: IndexBoundary,
    purge: BoundaryPurge,
) -> tuple[Signal, ...]:
    """Admit in timestamp order; never rank against later same-day decisions."""

    signals: list[Signal] = []
    previous_index: int | None = None
    occupied_through = -1
    for row, score in scored_rows:
        index = row.decision_index
        if previous_index is not None and index <= previous_index:
            raise ValueError("scored rows must be strictly chronological")
        previous_index = index
        if index < boundary.start or index >= boundary.end:
            raise ValueError("scored row is outside the evaluation boundary")
        if index < occupied_through:
            continue
        entry_index = index + 1
        exit_index = index + trade_spec.hold_bars
        if purge.purge_trade_horizon_at_end and trade_crosses_end(index, trade_spec.hold_bars, boundary):
            continue
        lower = float(score + validation_band.lower_residual)
        upper = float(score + validation_band.upper_residual)
        direction = 0
        if selector_spec.allow_long and lower > selector_spec.minimum_edge:
            direction = 1
        elif selector_spec.allow_short and upper < -selector_spec.minimum_edge:
            direction = -1
        if direction == 0:
            continue
        signals.append(
            Signal(
                decision_index=index,
                decision_timestamp=row.decision_timestamp,
                direction=direction,
                score=float(score),
                lower_score=lower,
                upper_score=upper,
                entry_index=entry_index,
                exit_index=exit_index,
            )
        )
        occupied_through = exit_index
    return tuple(signals)


def simulate_fixed_horizon(
    bars: tuple[Bar, ...], signals: tuple[Signal, ...], trade_spec: TradeSpec
) -> SimulationResult:
    """Execute on bid OHLC, paying observed spread on the applicable side."""

    trades: list[Trade] = []
    previous_exit = -1
    for signal in signals:
        if signal.entry_index <= previous_exit:
            raise ValueError("signals overlap and violate the one-position contract")
        if signal.exit_index >= len(bars):
            raise ValueError("signal exit exceeds available bars")
        entry_bar = bars[signal.entry_index]
        exit_bar = bars[signal.exit_index]
        if entry_bar.spread_points == 0 or exit_bar.spread_points == 0:
            raise UnknownCostError("entry or exit spread is zero and therefore unknown")
        if signal.direction == 1:
            spread_cost = entry_bar.spread_points * trade_spec.point_size
            entry_price = entry_bar.open_bid + spread_cost
            exit_price = exit_bar.close_bid
            gross = exit_bar.close_bid - entry_bar.open_bid
        elif signal.direction == -1:
            spread_cost = exit_bar.spread_points * trade_spec.point_size
            entry_price = entry_bar.open_bid
            exit_price = exit_bar.close_bid + spread_cost
            gross = entry_bar.open_bid - exit_bar.close_bid
        else:
            raise ValueError("signal direction must be long or short")
        commission = trade_spec.commission_per_trade
        net = gross - spread_cost - commission
        trades.append(
            Trade(
                decision_index=signal.decision_index,
                entry_index=signal.entry_index,
                exit_index=signal.exit_index,
                direction=signal.direction,
                entry_price=float(entry_price),
                exit_price=float(exit_price),
                gross_bid_move=float(gross),
                spread_cost=float(spread_cost),
                commission=float(commission),
                net_pnl=float(net),
            )
        )
        previous_exit = signal.exit_index
    return SimulationResult(
        trades=tuple(trades),
        net_pnl=float(sum(trade.net_pnl for trade in trades)),
        gross_bid_move=float(sum(trade.gross_bid_move for trade in trades)),
        spread_cost=float(sum(trade.spread_cost for trade in trades)),
        commission=float(sum(trade.commission for trade in trades)),
    )
