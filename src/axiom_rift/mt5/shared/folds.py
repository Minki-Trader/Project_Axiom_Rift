"""Shared MT5 date and fold helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from axiom_rift.mt5.shared.io import read_csv_rows
from axiom_rift.mt5.shared.parity import event_bar_time, parse_time


def tester_dates_for_window(window: Any) -> tuple[str, str]:
    from_date = window.start.strftime("%Y.%m.%d")
    to_date = (window.end + timedelta(days=1)).strftime("%Y.%m.%d")
    return from_date, to_date


def tester_date_to_iso(value: str) -> str:
    return datetime.strptime(value, "%Y.%m.%d").date().isoformat()


def tester_to_date_to_end_iso(value: str) -> str:
    return (datetime.strptime(value, "%Y.%m.%d") - timedelta(days=1)).date().isoformat()


def schedule_fold_summary(
    events: list[dict[str, str]],
    profits: list[float],
    schedule_artifact: Path,
) -> dict[str, object]:
    entries = [row for row in events if row.get("event") == "entry"]
    schedule_rows = read_csv_rows(schedule_artifact) if schedule_artifact.exists() else []
    schedule_rows_by_entry = {
        parse_time(row["entry_time"]): row.get("fold_id", "")
        for row in schedule_rows
        if parse_time(row.get("entry_time")) is not None
    }
    buckets: dict[str, int] = {}
    for row in entries:
        timestamp = event_bar_time(row)
        fold_id = schedule_rows_by_entry.get(timestamp, "unknown")
        buckets[fold_id] = buckets.get(fold_id, 0) + 1
    return {
        "entry_count_by_fold": dict(sorted(buckets.items())),
        "trade_count_total": len(entries),
        "profit_count": len(profits),
    }
