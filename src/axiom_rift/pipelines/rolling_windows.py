"""Build rolling-window split registries for US100 M5 research."""

from __future__ import annotations

import calendar
import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from axiom_rift.paths import DATA_DIR, PROJECT_ROOT, REGISTRY_DIR
from axiom_rift.pipelines.clean_periods import GapEvent, find_gap_events, read_times, time_text


TRAIN_MONTHS = 18
VALIDATION_MONTHS = 3
TEST_MONTHS = 3
STEP_MONTHS = 3
FIRST_FOLD_MONTH = date(2022, 5, 1)
LARGE_GAP_MISSING_BARS = 2


@dataclass(frozen=True)
class SplitWindow:
    name: str
    start: datetime
    end: datetime
    row_count: int
    calendar_days: float
    suspicious_gap_count: int
    large_suspicious_gap_count: int
    single_missing_m5_gap_count: int


@dataclass(frozen=True)
class Fold:
    fold_id: str
    train_is: SplitWindow
    validation_oos: SplitWindow
    test_oos: SplitWindow


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def first_bar_on_or_after(times: list[datetime], boundary: date) -> datetime | None:
    boundary_dt = datetime.combine(boundary, datetime.min.time())
    for value in times:
        if value >= boundary_dt:
            return value
    return None


def last_bar_before(times: list[datetime], boundary: date) -> datetime | None:
    boundary_dt = datetime.combine(boundary, datetime.min.time())
    for value in reversed(times):
        if value < boundary_dt:
            return value
    return None


def row_count(times: list[datetime], start: datetime, end: datetime) -> int:
    return sum(1 for value in times if start <= value <= end)


def split_gap_counts(start: datetime, end: datetime, suspicious_gaps: list[GapEvent]) -> dict[str, int]:
    in_split = [gap for gap in suspicious_gaps if start <= gap.from_time and gap.to_time <= end]
    return {
        "suspicious_gap_count": len(in_split),
        "large_suspicious_gap_count": sum(1 for gap in in_split if gap.missing_bars >= LARGE_GAP_MISSING_BARS),
        "single_missing_m5_gap_count": sum(1 for gap in in_split if gap.missing_bars == 1),
    }


def make_split(
    name: str,
    start_boundary: date,
    end_boundary_exclusive: date,
    times: list[datetime],
    suspicious_gaps: list[GapEvent],
) -> SplitWindow:
    start = first_bar_on_or_after(times, start_boundary)
    end = last_bar_before(times, end_boundary_exclusive)
    if start is None or end is None or start > end:
        raise ValueError(f"No rows for split {name}: {start_boundary}..{end_boundary_exclusive}")
    counts = split_gap_counts(start, end, suspicious_gaps)
    return SplitWindow(
        name=name,
        start=start,
        end=end,
        row_count=row_count(times, start, end),
        calendar_days=round((end - start).total_seconds() / 86400, 3),
        suspicious_gap_count=counts["suspicious_gap_count"],
        large_suspicious_gap_count=counts["large_suspicious_gap_count"],
        single_missing_m5_gap_count=counts["single_missing_m5_gap_count"],
    )


def split_dict(split: SplitWindow) -> dict[str, object]:
    return {
        "start": time_text(split.start),
        "end": time_text(split.end),
        "row_count": split.row_count,
        "calendar_days": split.calendar_days,
        "suspicious_gap_count": split.suspicious_gap_count,
        "large_suspicious_gap_count": split.large_suspicious_gap_count,
        "single_missing_m5_gap_count": split.single_missing_m5_gap_count,
    }


def fold_dict(fold: Fold) -> dict[str, object]:
    return {
        "fold_id": fold.fold_id,
        "train_is": split_dict(fold.train_is),
        "validation_oos": split_dict(fold.validation_oos),
        "test_oos": split_dict(fold.test_oos),
    }


def build_folds(times: list[datetime], suspicious_gaps: list[GapEvent]) -> list[Fold]:
    folds: list[Fold] = []
    fold_month = FIRST_FOLD_MONTH
    fold_number = 1
    latest_time = times[-1]
    total_months = TRAIN_MONTHS + VALIDATION_MONTHS + TEST_MONTHS
    while datetime.combine(add_months(fold_month, total_months), datetime.min.time()) <= latest_time:
        validation_start = add_months(fold_month, TRAIN_MONTHS)
        test_start = add_months(validation_start, VALIDATION_MONTHS)
        fold_end_exclusive = add_months(test_start, TEST_MONTHS)
        folds.append(
            Fold(
                fold_id=f"rw_{fold_number:03d}",
                train_is=make_split("train_is", fold_month, validation_start, times, suspicious_gaps),
                validation_oos=make_split("validation_oos", validation_start, test_start, times, suspicious_gaps),
                test_oos=make_split("test_oos", test_start, fold_end_exclusive, times, suspicious_gaps),
            )
        )
        fold_month = add_months(fold_month, STEP_MONTHS)
        fold_number += 1
    return folds


def build_tail_holdout(times: list[datetime], folds: list[Fold], suspicious_gaps: list[GapEvent]) -> SplitWindow | None:
    if not folds:
        return None
    next_day = folds[-1].test_oos.end.date() + timedelta(days=1)
    if datetime.combine(next_day, datetime.min.time()) > times[-1]:
        return None
    return make_split("tail_holdout_partial", next_day, times[-1].date() + timedelta(days=1), times, suspicious_gaps)


def build_rolling_windows(
    base_frame_csv: Path | None = None,
    rolling_windows_json: Path | None = None,
    rolling_windows_csv: Path | None = None,
) -> dict[str, object]:
    base_frame_csv = base_frame_csv or DATA_DIR / "processed" / "datasets" / "us100_m5_base_frame.csv"
    rolling_windows_json = rolling_windows_json or DATA_DIR / "processed" / "coverage_audits" / "us100_m5_rolling_windows.json"
    rolling_windows_csv = rolling_windows_csv or DATA_DIR / "processed" / "coverage_audits" / "us100_m5_rolling_windows.csv"
    times = read_times(base_frame_csv)
    events = find_gap_events(times)
    suspicious_gaps = [event for event in events if event.classification == "suspicious"]
    folds = build_folds(times, suspicious_gaps)
    tail_holdout = build_tail_holdout(times, folds, suspicious_gaps)
    payload = {
        "schema": "axiom_rift_rolling_windows_v1",
        "created_at_utc": utc_now(),
        "source_base_frame": rel(base_frame_csv),
        "policy": {
            "split_method": "rolling_window",
            "fold_anchor": "calendar_month",
            "train_is_months": TRAIN_MONTHS,
            "validation_oos_months": VALIDATION_MONTHS,
            "test_oos_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "first_fold_month": FIRST_FOLD_MONTH.isoformat(),
            "complete_test_oos_required": True,
            "tail_holdout_policy": "record_partial_tail_outside_full_folds",
            "suspicious_gap_policy": "audit_and_blackout_candidates_not_split_freeze",
        },
        "observed": {
            "first_time": time_text(times[0]),
            "last_time": time_text(times[-1]),
            "row_count": len(times),
            "suspicious_gap_count": len(suspicious_gaps),
            "large_suspicious_gap_count": sum(1 for gap in suspicious_gaps if gap.missing_bars >= LARGE_GAP_MISSING_BARS),
        },
        "fold_count": len(folds),
        "folds": [fold_dict(fold) for fold in folds],
        "tail_holdout_partial": split_dict(tail_holdout) if tail_holdout is not None else None,
        "claim_boundary": {
            "split_policy_adopted": True,
            "split_boundaries_frozen": False,
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "runtime_authority": False,
            "live_ready": False,
        },
    }
    rolling_windows_json.parent.mkdir(parents=True, exist_ok=True)
    rolling_windows_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="ascii")
    write_rolling_windows_csv(rolling_windows_csv, folds, tail_holdout)
    write_rolling_window_registry(payload, rolling_windows_json, rolling_windows_csv)
    register_artifact("us100_m5_rolling_windows", "split_registry", rolling_windows_json, sha256_file(rolling_windows_json))
    register_artifact("us100_m5_rolling_windows_csv", "split_registry", rolling_windows_csv, sha256_file(rolling_windows_csv))
    append_run_event(
        {
            "schema": "axiom_rift_run_event_v1",
            "event_id": f"evt_us100_m5_rolling_windows_{utc_stamp()}",
            "created_at_utc": utc_now(),
            "kind": "rolling_window_registry_build",
            "status": "completed",
            "source_base_frame": rel(base_frame_csv),
            "fold_count": len(folds),
            "claim_authority": False,
        }
    )
    return payload


def write_rolling_windows_csv(path: Path, folds: list[Fold], tail_holdout: SplitWindow | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "fold_id",
        "split",
        "start",
        "end",
        "row_count",
        "calendar_days",
        "suspicious_gap_count",
        "large_suspicious_gap_count",
        "single_missing_m5_gap_count",
    ]
    with path.open("w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for fold in folds:
            for split in (fold.train_is, fold.validation_oos, fold.test_oos):
                writer.writerow({"fold_id": fold.fold_id, "split": split.name, **split_dict(split)})
        if tail_holdout is not None:
            writer.writerow({"fold_id": "tail", "split": tail_holdout.name, **split_dict(tail_holdout)})


def write_rolling_window_registry(payload: dict[str, object], json_path: Path, csv_path: Path) -> None:
    folds = payload["folds"]
    first_fold = folds[0] if folds else None
    last_fold = folds[-1] if folds else None
    lines = [
        "schema: axiom_rift_rolling_windows_v1",
        "created_at_utc: " + str(payload["created_at_utc"]),
        "source_base_frame: " + str(payload["source_base_frame"]),
        "policy:",
        "  split_method: rolling_window",
        "  fold_anchor: calendar_month",
        "  train_is_months: " + str(payload["policy"]["train_is_months"]),
        "  validation_oos_months: " + str(payload["policy"]["validation_oos_months"]),
        "  test_oos_months: " + str(payload["policy"]["test_oos_months"]),
        "  step_months: " + str(payload["policy"]["step_months"]),
        "  complete_test_oos_required: true",
        "  tail_holdout_policy: record_partial_tail_outside_full_folds",
        "observed:",
        "  first_time: " + str(payload["observed"]["first_time"]),
        "  last_time: " + str(payload["observed"]["last_time"]),
        "  row_count: " + str(payload["observed"]["row_count"]),
        "  suspicious_gap_count: " + str(payload["observed"]["suspicious_gap_count"]),
        "  large_suspicious_gap_count: " + str(payload["observed"]["large_suspicious_gap_count"]),
        "fold_count: " + str(payload["fold_count"]),
    ]
    if first_fold is not None and last_fold is not None:
        lines.extend(
            [
                "fold_range:",
                "  first_fold_id: " + str(first_fold["fold_id"]),
                "  first_train_start: " + str(first_fold["train_is"]["start"]),
                "  last_fold_id: " + str(last_fold["fold_id"]),
                "  last_test_end: " + str(last_fold["test_oos"]["end"]),
            ]
        )
    if payload["tail_holdout_partial"] is not None:
        tail = payload["tail_holdout_partial"]
        lines.extend(
            [
                "tail_holdout_partial:",
                "  start: " + str(tail["start"]),
                "  end: " + str(tail["end"]),
                "  row_count: " + str(tail["row_count"]),
            ]
        )
    lines.extend(
        [
            "artifacts:",
            "  rolling_windows_json: " + rel(json_path),
            "  rolling_windows_csv: " + rel(csv_path),
            "claim_boundary:",
            "  split_policy_adopted: true",
            "  split_boundaries_frozen: false",
            "  label_selected: false",
            "  feature_set_selected: false",
            "  model_selected: false",
            "  runtime_authority: false",
            "  live_ready: false",
            "",
        ]
    )
    (REGISTRY_DIR / "rolling_windows.yaml").write_text("\n".join(lines), encoding="ascii")


def register_artifact(artifact_id: str, role: str, path: Path, sha256: str) -> None:
    registry = REGISTRY_DIR / "artifact_registry.csv"
    fieldnames = ["artifact_id", "role", "path", "sha256", "produced_by", "created_local", "status", "notes"]
    row = {
        "artifact_id": artifact_id,
        "role": role,
        "path": rel(path),
        "sha256": sha256,
        "produced_by": "build_rolling_windows",
        "created_local": utc_now(),
        "status": "active",
        "notes": "rolling_window_split_policy_no_label_feature_model_claim",
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
