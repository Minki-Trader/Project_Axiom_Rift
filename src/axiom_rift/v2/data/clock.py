"""Explicit broker-bar and market-time availability semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


class ClockError(ValueError):
    """Raised when a broker timestamp cannot be localized safely."""


@dataclass(frozen=True)
class ClockStamp:
    bar_open_server: datetime
    bar_close_server: datetime
    decision_available_at_server: datetime
    decision_available_at_utc: datetime
    decision_available_at_market: datetime


@dataclass(frozen=True)
class ClockPolicy:
    market_timezone: str = "America/New_York"
    bar_minutes: int = 5
    server_minus_market_hours: int = 7
    rule_id: str = "fpmarkets_ny_close_plus_7_v1"
    authority: str = "broker_documented_rule_pending_mt5_clock_receipt"

    def stamp(self, broker_bar_open: datetime, *, fold: int | None = None) -> ClockStamp:
        if broker_bar_open.tzinfo is not None:
            raise ClockError("broker bar open must be a naive exported server timestamp")
        market_zone = ZoneInfo(self.market_timezone)
        market_naive = broker_bar_open - timedelta(hours=self.server_minus_market_hours)
        first = market_naive.replace(tzinfo=market_zone, fold=0)
        second = market_naive.replace(tzinfo=market_zone, fold=1)
        ambiguous = first.utcoffset() != second.utcoffset()
        if ambiguous and fold is None:
            raise ClockError("ambiguous New York timestamp requires an explicit fold")
        market_open = market_naive.replace(tzinfo=market_zone, fold=fold or 0)
        roundtrip = market_open.astimezone(ZoneInfo("UTC")).astimezone(market_zone).replace(tzinfo=None)
        if roundtrip != market_naive:
            raise ClockError("nonexistent New York timestamp in broker clock mapping")
        market_offset = market_open.utcoffset()
        if market_offset is None:
            raise ClockError("market UTC offset is unavailable")
        server_offset = market_offset + timedelta(hours=self.server_minus_market_hours)
        if server_offset not in {timedelta(hours=2), timedelta(hours=3)}:
            raise ClockError(f"unexpected FPMarkets server offset: {server_offset}")
        server_open = broker_bar_open.replace(tzinfo=timezone(server_offset))
        close = server_open + timedelta(minutes=self.bar_minutes)
        decision_utc = close.astimezone(timezone.utc)
        return ClockStamp(
            bar_open_server=server_open,
            bar_close_server=close,
            decision_available_at_server=close,
            decision_available_at_utc=decision_utc,
            decision_available_at_market=decision_utc.astimezone(market_zone),
        )
