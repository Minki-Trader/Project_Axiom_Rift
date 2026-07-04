"""Market-calendar-aware gap classification for US100 M5 data."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from axiom_rift.paths import CONFIG_DIR

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only in missing optional dependency environments
    yaml = None


MARKET_CALENDAR_SCHEMA = "axiom_rift_market_calendar_v1"
MARKET_CALENDAR_RELATIVE_PATH = "configs/market_calendar.yaml"
ALLOW = "allow"
FLAG_FOR_REVIEW = "flag_for_review"
BLACKOUT = "blackout"


@dataclass(frozen=True)
class GapDecision:
    classification: str
    calendar_status: str
    training_action: str
    reason: str
    calendar_match_id: str | None = None


def default_market_calendar_path() -> Path:
    return CONFIG_DIR / "market_calendar.yaml"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_market_calendar(path: Path | None = None) -> dict[str, Any]:
    path = path or default_market_calendar_path()
    if not path.exists():
        raise FileNotFoundError(f"Market calendar registry not found: {path}")
    if yaml is None:
        raise RuntimeError("PyYAML is required to parse market calendar YAML")
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    if not isinstance(data, dict):
        raise ValueError(f"Market calendar registry must be a mapping: {path}")
    if data.get("schema") != MARKET_CALENDAR_SCHEMA:
        raise ValueError(f"Unsupported market calendar schema: {data.get('schema')!r}")
    return data


def classify_gap_with_calendar(previous: datetime, current: datetime, calendar: dict[str, Any]) -> GapDecision:
    prev_time = previous.strftime("%H:%M")
    current_time = current.strftime("%H:%M")
    delta_minutes = int((current - previous).total_seconds() // 60)
    missing_bars = delta_minutes // 5 - 1
    if is_regular_daily_close(previous, current, prev_time, current_time):
        return GapDecision("regular_daily_close", "regular_rule", ALLOW, "daily close rule matched")
    if is_regular_dst_close(previous, current, prev_time, current_time):
        return GapDecision("regular_dst_daily_close", "regular_rule", ALLOW, "DST daily close rule matched")
    if is_regular_weekend_close(previous, current, prev_time, current_time):
        return GapDecision("regular_weekend_close", "regular_rule", ALLOW, "weekend close rule matched")
    if is_special_close_candidate(previous, current, prev_time, current_time, delta_minutes):
        match = find_verified_special_closure(previous, current, calendar)
        if match is not None:
            return GapDecision(
                "verified_special_closure",
                "verified_calendar",
                ALLOW,
                str(match.get("reason", "verified special closure")),
                calendar_match_id=str(match.get("id") or match.get("date")),
            )
        return GapDecision(
            "unverified_special_close_candidate",
            "unverified_calendar",
            FLAG_FOR_REVIEW,
            "time pattern resembles special close but no calendar entry matched",
        )
    if missing_bars <= 1:
        return GapDecision(
            "unexpected_single_m5_gap",
            "not_regular_or_verified_closure",
            FLAG_FOR_REVIEW,
            "single missing M5 bar outside regular or verified closure",
        )
    return GapDecision(
        "unexpected_multi_bar_gap",
        "not_regular_or_verified_closure",
        BLACKOUT,
        "multi-bar gap outside regular or verified closure",
    )


def classify_gap(previous: datetime, current: datetime, calendar: dict[str, Any] | None = None) -> str:
    return classify_gap_with_calendar(previous, current, calendar or empty_calendar()).classification


def gap_needs_review_or_blackout(gap: Any) -> bool:
    return getattr(gap, "training_action", None) != ALLOW


def gap_is_blackout(gap: Any) -> bool:
    return getattr(gap, "training_action", None) == BLACKOUT


def gap_is_flag_for_review(gap: Any) -> bool:
    return getattr(gap, "training_action", None) == FLAG_FOR_REVIEW


def gap_action_counts(gaps: list[Any]) -> dict[str, int]:
    return {
        "allow_gap_count": sum(1 for gap in gaps if getattr(gap, "training_action", None) == ALLOW),
        "flag_for_review_gap_count": sum(
            1 for gap in gaps if getattr(gap, "training_action", None) == FLAG_FOR_REVIEW
        ),
        "blackout_gap_count": sum(1 for gap in gaps if getattr(gap, "training_action", None) == BLACKOUT),
        "unverified_special_close_candidate_count": sum(
            1 for gap in gaps if getattr(gap, "classification", None) == "unverified_special_close_candidate"
        ),
        "verified_special_closure_count": sum(
            1 for gap in gaps if getattr(gap, "classification", None) == "verified_special_closure"
        ),
    }


def is_regular_daily_close(previous: datetime, current: datetime, prev_time: str, current_time: str) -> bool:
    return (
        previous.date() + timedelta(days=1) == current.date()
        and prev_time in {"23:50", "23:55"}
        and current_time in {"01:00", "02:00"}
    )


def is_regular_dst_close(previous: datetime, current: datetime, prev_time: str, current_time: str) -> bool:
    return previous.date() == current.date() and prev_time == "00:55" and current_time == "02:00"


def is_regular_weekend_close(previous: datetime, current: datetime, prev_time: str, current_time: str) -> bool:
    return (
        previous.weekday() == 4
        and current.weekday() == 0
        and prev_time >= "16:00"
        and current_time in {"01:00", "02:00"}
    )


def is_special_close_candidate(
    previous: datetime, current: datetime, prev_time: str, current_time: str, delta_minutes: int
) -> bool:
    return current_time in {"01:00", "02:00"} and prev_time >= "16:00" and delta_minutes >= 285


def find_verified_special_closure(
    previous: datetime, current: datetime, calendar: dict[str, Any]
) -> dict[str, Any] | None:
    entries = calendar.get("verified_special_closures")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if special_closure_entry_matches(previous, current, entry):
            return entry
    return None


def special_closure_entry_matches(previous: datetime, current: datetime, entry: dict[str, Any]) -> bool:
    entry_date = entry.get("date")
    if isinstance(entry_date, str) and entry_date in {previous.date().isoformat(), current.date().isoformat()}:
        return True
    from_date = entry.get("from_date")
    to_date = entry.get("to_date")
    if isinstance(from_date, str) and isinstance(to_date, str):
        previous_day = previous.date().isoformat()
        current_day = current.date().isoformat()
        return from_date <= previous_day <= to_date or from_date <= current_day <= to_date
    return False


def empty_calendar() -> dict[str, Any]:
    return {"schema": MARKET_CALENDAR_SCHEMA, "verified_special_closures": []}
