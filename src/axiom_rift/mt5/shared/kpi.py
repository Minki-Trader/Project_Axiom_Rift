"""Shared MT5 KPI helpers."""

from __future__ import annotations

from collections import Counter
from typing import Any


def rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def to_float(value: str | None) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def kpi_float(required_kpis: dict[str, object], field: str) -> float | None:
    value = required_kpis.get(field)
    if value in (None, ""):
        return None
    return float(value)


def kpi_int(required_kpis: dict[str, object], field: str) -> int | None:
    value = required_kpis.get(field)
    if value in (None, ""):
        return None
    return int(value)


def numeric_delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return rounded(left - right)


def int_delta(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    return left - right


def max_drawdown_percent(profits: list[float], starting_balance: float) -> float | None:
    if not profits or starting_balance <= 0:
        return None
    equity = starting_balance
    peak = starting_balance
    max_drawdown = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return rounded((max_drawdown / starting_balance) * 100.0)


def missing_value_checks(status: dict[str, str], events: list[dict[str, str]], deals: list[dict[str, str]]) -> list[str]:
    blockers: list[str] = []
    if status.get("status") != "completed":
        blockers.append("status_not_completed")
    if not events:
        blockers.append("events_missing")
    if not deals:
        blockers.append("deals_missing")
    if not any(row.get("event") == "entry" for row in events):
        blockers.append("entry_events_missing")
    if not any(row.get("event") == "exit" for row in events):
        blockers.append("exit_events_missing")
    return blockers


def missing_required_kpi_fields(required_kpis: dict[str, object]) -> list[str]:
    trade_count = int(required_kpis.get("mt5_trade_count") or 0)
    missing: list[str] = []
    for field, value in required_kpis.items():
        if field == "mt5_profit_factor" and trade_count > 0:
            continue
        if value is None or value == "":
            missing.append(field)
    return missing


def missing_required_execution_fields(required_kpis: dict[str, object]) -> list[str]:
    return [field for field, value in required_kpis.items() if value is None or value == ""]


def missing_required_by_fold_fields(required_kpis: dict[str, object]) -> list[str]:
    return [field for field, value in required_kpis.items() if value is None or value == ""]


def append_rate(target: list[float], value: object) -> None:
    if value is not None:
        target.append(float(value))


def direction_summary(events: list[dict[str, str]], exit_deals: list[dict[str, str]]) -> dict[str, Any]:
    direction_counts = Counter(row.get("direction") for row in events if row.get("event") == "entry")
    return {
        "long_entry_count": direction_counts.get("long", 0),
        "short_entry_count": direction_counts.get("short", 0),
        "closed_deal_count": len(exit_deals),
    }
