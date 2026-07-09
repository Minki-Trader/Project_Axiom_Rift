"""Blackout boundaries that remove samples crossing missing market history."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class BoundaryGap:
    start: datetime
    end: datetime
    missing_bars: int
    action: str
    classification: str


def load_non_allow_gaps(path: Path) -> tuple[BoundaryGap, ...]:
    payload = json.loads(path.read_text(encoding="ascii"))
    rows = payload.get("suspicious_gaps", [])
    return tuple(
        BoundaryGap(
            start=datetime.strptime(row["from"], TIME_FORMAT),
            end=datetime.strptime(row["to"], TIME_FORMAT),
            missing_bars=int(row["missing_bars"]),
            action=str(row["training_action"]),
            classification=str(row["classification"]),
        )
        for row in rows
        if row.get("training_action") != "allow"
    )


def interval_crosses_non_allow_boundary(start: datetime, end: datetime, gaps: tuple[BoundaryGap, ...]) -> bool:
    if end < start:
        raise ValueError("sample interval end precedes start")
    return any(start <= gap.start and end >= gap.end for gap in gaps)


def summarize_non_allow_boundaries(gaps: tuple[BoundaryGap, ...]) -> dict[str, object]:
    """Return stable counts used by data receipts and policy checks."""

    action_counts = Counter(gap.action for gap in gaps)
    classification_counts = Counter(gap.classification for gap in gaps)
    return {
        "non_allow_boundary_count": len(gaps),
        "action_counts": dict(sorted(action_counts.items())),
        "classification_counts": dict(sorted(classification_counts.items())),
    }


BlackoutGap = BoundaryGap
load_blackout_gaps = load_non_allow_gaps
interval_crosses_blackout = interval_crosses_non_allow_boundary
