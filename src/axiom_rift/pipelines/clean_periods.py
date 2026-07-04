"""Derive usable clean periods from the US100 M5 base frame."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from axiom_rift.paths import DATA_DIR, PROJECT_ROOT, REGISTRY_DIR
from axiom_rift.pipelines.market_calendar import (
    classify_gap as classify_gap_label,
    classify_gap_with_calendar,
    default_market_calendar_path,
    gap_action_counts,
    gap_is_blackout,
    gap_needs_review_or_blackout,
    load_market_calendar,
)


BROAD_MODELING_START = datetime(2022, 5, 1)
LEGACY_PRACTICAL_START = datetime(2022, 9, 1)
EXPECTED_STEP_MINUTES = 5
PRACTICAL_SPLIT_MISSING_BARS = 2


@dataclass(frozen=True)
class GapEvent:
    from_time: datetime
    to_time: datetime
    delta_minutes: int
    missing_bars: int
    classification: str
    calendar_status: str
    training_action: str
    reason: str
    calendar_match_id: str | None = None


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    row_count: int
    calendar_days: float


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def time_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_times(path: Path) -> list[datetime]:
    if not path.exists():
        raise FileNotFoundError(f"Base frame not found: {path}")
    rows: list[datetime] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            timestamp = parse_time(row["time"])
            if timestamp >= BROAD_MODELING_START:
                rows.append(timestamp)
    if not rows:
        raise ValueError(f"No rows at or after {time_text(BROAD_MODELING_START)}")
    return rows


def classify_gap(previous: datetime, current: datetime) -> str:
    return classify_gap_label(previous, current)


def find_gap_events(times: list[datetime], market_calendar: dict[str, object] | None = None) -> list[GapEvent]:
    market_calendar = market_calendar or load_market_calendar()
    events: list[GapEvent] = []
    previous: datetime | None = None
    for current in times:
        if previous is not None:
            delta_minutes = int((current - previous).total_seconds() // 60)
            if delta_minutes > EXPECTED_STEP_MINUTES:
                missing_bars = delta_minutes // EXPECTED_STEP_MINUTES - 1
                decision = classify_gap_with_calendar(previous, current, market_calendar)
                events.append(
                    GapEvent(
                        from_time=previous,
                        to_time=current,
                        delta_minutes=delta_minutes,
                        missing_bars=missing_bars,
                        classification=decision.classification,
                        calendar_status=decision.calendar_status,
                        training_action=decision.training_action,
                        reason=decision.reason,
                        calendar_match_id=decision.calendar_match_id,
                    )
                )
        previous = current
    return events


def row_count(times: list[datetime], start: datetime, end: datetime) -> int:
    return sum(1 for value in times if start <= value <= end)


def window(times: list[datetime], start: datetime, end: datetime) -> Window:
    return Window(
        start=start,
        end=end,
        row_count=row_count(times, start, end),
        calendar_days=round((end - start).total_seconds() / 86400, 3),
    )


def split_windows(times: list[datetime], suspicious_gaps: list[GapEvent], missing_bar_threshold: int) -> list[Window]:
    windows: list[Window] = []
    start = times[0]
    for gap in suspicious_gaps:
        if gap.missing_bars >= missing_bar_threshold:
            if gap.from_time >= start:
                windows.append(window(times, start, gap.from_time))
            start = gap.to_time
    if start <= times[-1]:
        windows.append(window(times, start, times[-1]))
    return [item for item in windows if item.row_count > 0]


def first_bar_on_or_after_day(times: list[datetime], day: date) -> datetime | None:
    for value in times:
        if value.date() >= day:
            return value
    return None


def last_bar_on_or_before_day(times: list[datetime], day: date) -> datetime | None:
    for value in reversed(times):
        if value.date() <= day:
            return value
    return None


def trim_to_full_days(times: list[datetime], source: Window) -> Window:
    start_day = source.start.date()
    end_day = source.end.date()
    if source.start.time() > datetime.strptime("01:00", "%H:%M").time():
        start_day = start_day + timedelta(days=1)
    if source.end.time() < datetime.strptime("23:50", "%H:%M").time():
        end_day = end_day - timedelta(days=1)
    start = first_bar_on_or_after_day(times, start_day)
    end = last_bar_on_or_before_day(times, end_day)
    if start is None or end is None or start > end:
        return source
    return window(times, start, end)


def window_gap_counts(item: Window, suspicious_gaps: list[GapEvent]) -> dict[str, int]:
    in_window = [gap for gap in suspicious_gaps if item.start <= gap.from_time and gap.to_time <= item.end]
    action_counts = gap_action_counts(in_window)
    return {
        "suspicious_gap_count": len(in_window),
        "large_suspicious_gap_count": sum(1 for gap in in_window if gap.missing_bars >= PRACTICAL_SPLIT_MISSING_BARS),
        "single_missing_m5_gap_count": sum(1 for gap in in_window if gap.missing_bars == 1),
        "flag_for_review_gap_count": action_counts["flag_for_review_gap_count"],
        "blackout_gap_count": action_counts["blackout_gap_count"],
        "unverified_special_close_candidate_count": action_counts["unverified_special_close_candidate_count"],
    }


def window_dict(item: Window, suspicious_gaps: list[GapEvent] | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "start": time_text(item.start),
        "end": time_text(item.end),
        "row_count": item.row_count,
        "calendar_days": item.calendar_days,
    }
    if suspicious_gaps is not None:
        result.update(window_gap_counts(item, suspicious_gaps))
    return result


def gap_dict(item: GapEvent) -> dict[str, object]:
    return {
        "from": time_text(item.from_time),
        "to": time_text(item.to_time),
        "delta_minutes": item.delta_minutes,
        "missing_bars": item.missing_bars,
        "classification": item.classification,
        "calendar_status": item.calendar_status,
        "training_action": item.training_action,
        "reason": item.reason,
        "calendar_match_id": item.calendar_match_id,
    }


def derive_clean_periods(
    base_frame_csv: Path | None = None,
    clean_periods_json: Path | None = None,
    clean_windows_csv: Path | None = None,
    market_calendar_yaml: Path | None = None,
) -> dict[str, object]:
    base_frame_csv = base_frame_csv or DATA_DIR / "processed" / "datasets" / "us100_m5_base_frame.csv"
    clean_periods_json = clean_periods_json or DATA_DIR / "processed" / "coverage_audits" / "us100_m5_clean_periods.json"
    clean_windows_csv = clean_windows_csv or DATA_DIR / "processed" / "coverage_audits" / "us100_m5_clean_windows.csv"
    market_calendar_yaml = market_calendar_yaml or default_market_calendar_path()
    market_calendar = load_market_calendar(market_calendar_yaml)
    calendar_hash = sha256_file(market_calendar_yaml)
    times = read_times(base_frame_csv)
    events = find_gap_events(times, market_calendar)
    suspicious = [event for event in events if gap_needs_review_or_blackout(event)]
    blackout_gaps = [event for event in events if gap_is_blackout(event)]
    action_counts = gap_action_counts(events)
    strict_windows = split_windows(times, blackout_gaps, missing_bar_threshold=1)
    practical_windows = split_windows(times, blackout_gaps, missing_bar_threshold=PRACTICAL_SPLIT_MISSING_BARS)
    continuous_raw = max(practical_windows, key=lambda item: (item.calendar_days, item.row_count))
    continuous_trimmed = trim_to_full_days(times, continuous_raw)
    recommended = window(times, times[0], times[-1])
    suggested_splits = build_suggested_splits(times, recommended, suspicious)
    payload = {
        "schema": "axiom_rift_clean_periods_v1",
        "created_at_utc": utc_now(),
        "source_base_frame": rel(base_frame_csv),
        "market_calendar": {
            "path": rel(market_calendar_yaml),
            "sha256": calendar_hash,
            "schema": market_calendar.get("schema"),
        },
        "policy": {
            "broad_modeling_start": time_text(BROAD_MODELING_START),
            "legacy_practical_start": time_text(LEGACY_PRACTICAL_START),
            "expected_step_minutes": EXPECTED_STEP_MINUTES,
            "regular_gap_policy": [
                "daily_close",
                "dst_daily_close",
                "weekend_close",
            ],
            "special_closure_policy": "only_configs_market_calendar_verified_special_closures_are_allowed",
            "unverified_special_close_candidate_action": "flag_for_review",
            "unexpected_multi_bar_gap_action": "blackout",
            "strict_windows_split_on_suspicious_missing_bars_gte": 1,
            "practical_windows_split_on_suspicious_missing_bars_gte": PRACTICAL_SPLIT_MISSING_BARS,
            "recommended_window_policy": "keep broad US100 span and treat suspicious gaps as audit or blackout events",
            "continuous_window_policy": "single missing M5 bar is tolerated for continuous-window ranking",
        },
        "observed": {
            "first_time": time_text(times[0]),
            "last_time": time_text(times[-1]),
            "row_count": len(times),
            "gap_event_count": len(events),
            "suspicious_gap_count": len(suspicious),
            "blackout_gap_count": action_counts["blackout_gap_count"],
            "flag_for_review_gap_count": action_counts["flag_for_review_gap_count"],
            "verified_special_closure_count": action_counts["verified_special_closure_count"],
            "unverified_special_close_candidate_count": action_counts["unverified_special_close_candidate_count"],
        },
        "recommended_modeling_window": window_dict(recommended, suspicious),
        "longest_practical_continuous_window": window_dict(continuous_trimmed, suspicious),
        "longest_raw_continuous_window": window_dict(continuous_raw, suspicious),
        "suggested_initial_splits": suggested_splits,
        "strict_windows_top": [
            window_dict(item) for item in sorted(strict_windows, key=lambda x: x.calendar_days, reverse=True)[:8]
        ],
        "practical_windows_top": [
            window_dict(item) for item in sorted(practical_windows, key=lambda x: x.calendar_days, reverse=True)[:8]
        ],
        "suspicious_gaps": [gap_dict(item) for item in suspicious],
        "blackout_gaps": [gap_dict(item) for item in blackout_gaps],
        "claim_boundary": {
            "split_frozen": False,
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "runtime_authority": False,
            "live_ready": False,
        },
    }
    clean_periods_json.parent.mkdir(parents=True, exist_ok=True)
    clean_periods_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="ascii")
    write_clean_windows_csv(clean_windows_csv, strict_windows, practical_windows)
    write_clean_period_registry(payload, clean_periods_json, clean_windows_csv)
    register_artifact("us100_m5_clean_periods", "coverage_audit", clean_periods_json, sha256_file(clean_periods_json))
    register_artifact("us100_m5_clean_windows", "coverage_audit", clean_windows_csv, sha256_file(clean_windows_csv))
    append_run_event(
        {
            "schema": "axiom_rift_run_event_v1",
            "event_id": f"evt_us100_m5_clean_periods_{utc_stamp()}",
            "created_at_utc": utc_now(),
            "kind": "clean_period_derivation",
            "status": "completed",
            "source_base_frame": rel(base_frame_csv),
            "market_calendar": rel(market_calendar_yaml),
            "market_calendar_sha256": calendar_hash,
            "recommended_start": payload["recommended_modeling_window"]["start"],
            "recommended_end": payload["recommended_modeling_window"]["end"],
            "longest_continuous_start": payload["longest_practical_continuous_window"]["start"],
            "longest_continuous_end": payload["longest_practical_continuous_window"]["end"],
            "suspicious_gap_count": len(suspicious),
            "blackout_gap_count": action_counts["blackout_gap_count"],
            "flag_for_review_gap_count": action_counts["flag_for_review_gap_count"],
            "claim_authority": False,
        }
    )
    return payload


def build_suggested_splits(
    times: list[datetime], recommended: Window, suspicious_gaps: list[GapEvent]
) -> dict[str, dict[str, object]]:
    split_bounds = {
        "train": (recommended.start, datetime(2024, 12, 31, 23, 55)),
        "validation": (datetime(2025, 1, 2, 1, 0), datetime(2025, 9, 30, 23, 55)),
        "backtest": (datetime(2025, 10, 1, 1, 0), recommended.end),
    }
    splits: dict[str, dict[str, object]] = {}
    for split, (start, end) in split_bounds.items():
        if start < recommended.start:
            start = recommended.start
        if end > recommended.end:
            end = recommended.end
        splits[split] = window_dict(window(times, start, end), suspicious_gaps)
    return splits


def write_clean_windows_csv(path: Path, strict_windows: list[Window], practical_windows: list[Window]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="") as handle:
        fieldnames = ["window_set", "rank", "start", "end", "row_count", "calendar_days"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for window_set, items in (("strict", strict_windows), ("practical", practical_windows)):
            ranked = sorted(items, key=lambda item: item.calendar_days, reverse=True)
            for rank, item in enumerate(ranked, start=1):
                writer.writerow({"window_set": window_set, "rank": rank, **window_dict(item)})


def write_clean_period_registry(payload: dict[str, object], json_path: Path, windows_path: Path) -> None:
    observed = payload["observed"]
    recommended = payload["recommended_modeling_window"]
    continuous = payload["longest_practical_continuous_window"]
    splits = payload["suggested_initial_splits"]
    lines = [
        "schema: axiom_rift_clean_periods_v1",
        "created_at_utc: " + str(payload["created_at_utc"]),
        "source_base_frame: " + str(payload["source_base_frame"]),
        "market_calendar:",
        "  path: " + str(payload["market_calendar"]["path"]),
        "  sha256: " + str(payload["market_calendar"]["sha256"]),
        "policy:",
        "  broad_modeling_start: " + str(payload["policy"]["broad_modeling_start"]),
        "  legacy_practical_start: " + str(payload["policy"]["legacy_practical_start"]),
        "  regular_gap_policy: daily_close_weekend_dst",
        "  special_closure_policy: calendar_verified_only",
        "  unverified_special_close_candidate_action: flag_for_review",
        "  unexpected_multi_bar_gap_action: blackout",
        "  practical_windows_split_on_suspicious_missing_bars_gte: "
        + str(payload["policy"]["practical_windows_split_on_suspicious_missing_bars_gte"]),
        "  single_missing_m5_bar_tolerated: true",
        "  recommended_window_policy: broad_span_with_gap_audit",
        "observed:",
        "  first_time: " + str(observed["first_time"]),
        "  last_time: " + str(observed["last_time"]),
        "  row_count: " + str(observed["row_count"]),
        "  suspicious_gap_count: " + str(observed["suspicious_gap_count"]),
        "  flag_for_review_gap_count: " + str(observed["flag_for_review_gap_count"]),
        "  blackout_gap_count: " + str(observed["blackout_gap_count"]),
        "  verified_special_closure_count: " + str(observed["verified_special_closure_count"]),
        "  unverified_special_close_candidate_count: "
        + str(observed["unverified_special_close_candidate_count"]),
        "recommended_modeling_window:",
        "  start: " + str(recommended["start"]),
        "  end: " + str(recommended["end"]),
        "  row_count: " + str(recommended["row_count"]),
        "  calendar_days: " + str(recommended["calendar_days"]),
        "  suspicious_gap_count: " + str(recommended["suspicious_gap_count"]),
        "  large_suspicious_gap_count: " + str(recommended["large_suspicious_gap_count"]),
        "  flag_for_review_gap_count: " + str(recommended["flag_for_review_gap_count"]),
        "  blackout_gap_count: " + str(recommended["blackout_gap_count"]),
        "longest_practical_continuous_window:",
        "  start: " + str(continuous["start"]),
        "  end: " + str(continuous["end"]),
        "  row_count: " + str(continuous["row_count"]),
        "  calendar_days: " + str(continuous["calendar_days"]),
        "suggested_initial_splits:",
    ]
    for split_name, split in splits.items():
        lines.extend(
            [
                "  " + split_name + ":",
                "    start: " + str(split["start"]),
                "    end: " + str(split["end"]),
                "    row_count: " + str(split["row_count"]),
                "    suspicious_gap_count: " + str(split["suspicious_gap_count"]),
                "    large_suspicious_gap_count: " + str(split["large_suspicious_gap_count"]),
            ]
        )
    lines.extend(
        [
            "artifacts:",
            "  clean_periods_json: " + rel(json_path),
            "  clean_windows_csv: " + rel(windows_path),
            "claim_boundary:",
            "  split_frozen: false",
            "  label_selected: false",
            "  feature_set_selected: false",
            "  model_selected: false",
            "  runtime_authority: false",
            "  live_ready: false",
            "",
        ]
    )
    (REGISTRY_DIR / "clean_periods.yaml").write_text("\n".join(lines), encoding="ascii")


def register_artifact(artifact_id: str, role: str, path: Path, sha256: str) -> None:
    registry = REGISTRY_DIR / "artifact_registry.csv"
    fieldnames = ["artifact_id", "role", "path", "sha256", "produced_by", "created_local", "status", "notes"]
    row = {
        "artifact_id": artifact_id,
        "role": role,
        "path": rel(path),
        "sha256": sha256,
        "produced_by": "derive_clean_periods",
        "created_local": utc_now(),
        "status": "active",
        "notes": "clean_period_candidate_no_label_feature_model_claim",
    }
    rows: list[dict[str, str]] = []
    if registry.exists() and registry.stat().st_size > 0:
        with registry.open("r", encoding="ascii", newline="") as handle:
            rows = [existing for existing in csv.DictReader(handle) if existing.get("artifact_id") != artifact_id]
    rows.append(row)
    with registry.open("w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_run_event(event: dict[str, object]) -> None:
    path = REGISTRY_DIR / "run_registry.jsonl"
    with path.open("a", encoding="ascii", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
