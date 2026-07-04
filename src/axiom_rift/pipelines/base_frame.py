"""Build clean base frames from raw bar exports."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from axiom_rift.paths import DATA_DIR, PROJECT_ROOT, REGISTRY_DIR
from axiom_rift.validation.price_quality import (
    PRICE_QUALITY_AUDIT_RELATIVE_PATH,
    build_price_quality_audit,
    require_no_price_quality_blockers,
)


EXPECTED_M5_SECONDS = 300
TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M:%S")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def parse_timestamp(value: str) -> datetime:
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported timestamp format: {value}")


def format_timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def build_us100_m5_base_frame(
    raw_csv: Path | None = None,
    output_csv: Path | None = None,
    coverage_json: Path | None = None,
    price_quality_json: Path | None = None,
) -> dict[str, object]:
    raw_csv = raw_csv or DATA_DIR / "raw" / "mt5_bars" / "m5" / "US100_M5_max.csv"
    output_csv = output_csv or DATA_DIR / "processed" / "datasets" / "us100_m5_base_frame.csv"
    coverage_json = coverage_json or DATA_DIR / "processed" / "coverage_audits" / "us100_m5_coverage.json"
    price_quality_json = price_quality_json or PROJECT_ROOT / PRICE_QUALITY_AUDIT_RELATIVE_PATH

    if not raw_csv.exists():
        raise FileNotFoundError(f"Raw bar CSV not found: {raw_csv}")

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    duplicate_count = 0
    with raw_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            timestamp = format_timestamp(parse_timestamp(row["time"]))
            if timestamp in seen:
                duplicate_count += 1
                continue
            seen.add(timestamp)
            row["time"] = timestamp
            rows.append(row)

    rows.sort(key=lambda row: row["time"])
    gaps: list[dict[str, object]] = []
    previous: datetime | None = None
    for row in rows:
        current = parse_timestamp(row["time"])
        if previous is not None:
            delta = int((current - previous).total_seconds())
            if delta > EXPECTED_M5_SECONDS:
                gaps.append(
                    {
                        "from": previous.strftime("%Y-%m-%d %H:%M:%S"),
                        "to": current.strftime("%Y-%m-%d %H:%M:%S"),
                        "gap_seconds": delta - EXPECTED_M5_SECONDS,
                    }
                )
        previous = current

    created_at_utc = utc_now()
    price_quality = build_price_quality_audit(
        rows,
        created_at_utc=created_at_utc,
        source_raw_csv=rel(raw_csv),
        base_frame_csv=rel(output_csv),
    )
    require_no_price_quality_blockers(price_quality)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    output_hash = sha256_file(output_csv)

    price_quality["base_frame_sha256"] = output_hash
    price_quality_json.parent.mkdir(parents=True, exist_ok=True)
    price_quality_json.write_text(json.dumps(price_quality, indent=2, sort_keys=True) + "\n", encoding="ascii")
    price_quality_hash = sha256_file(price_quality_json)

    coverage = {
        "schema": "axiom_rift_us100_m5_coverage_v1",
        "created_at_utc": created_at_utc,
        "source_raw_csv": rel(raw_csv),
        "base_frame_csv": rel(output_csv),
        "row_count": len(rows),
        "first_time": rows[0]["time"] if rows else None,
        "last_time": rows[-1]["time"] if rows else None,
        "duplicate_count": duplicate_count,
        "gap_count": len(gaps),
        "gaps_preview": gaps[:100],
        "expected_step_seconds": EXPECTED_M5_SECONDS,
        "sha256": output_hash,
        "price_quality_audit": rel(price_quality_json),
        "price_quality_sha256": price_quality_hash,
        "price_quality_blocker_count": price_quality["blocker_count"],
        "price_quality_warning_count": price_quality["warning_count"],
        "claim_boundary": {
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "runtime_authority": False,
            "live_ready": False,
        },
    }
    coverage_json.parent.mkdir(parents=True, exist_ok=True)
    coverage_json.write_text(json.dumps(coverage, indent=2, sort_keys=True), encoding="ascii")
    register_artifact("us100_m5_base_frame", "dataset", output_csv, coverage["sha256"])
    register_artifact("us100_m5_coverage", "coverage_audit", coverage_json, sha256_file(coverage_json))
    register_artifact("us100_m5_price_quality", "coverage_audit", price_quality_json, price_quality_hash)
    append_run_event(
        {
            "schema": "axiom_rift_run_event_v1",
            "event_id": f"evt_us100_m5_base_frame_build_{utc_stamp()}",
            "created_at_utc": utc_now(),
            "kind": "base_frame_build",
            "status": "completed",
            "source_raw_csv": rel(raw_csv),
            "base_frame_csv": rel(output_csv),
            "row_count": len(rows),
            "first_time": coverage["first_time"],
            "last_time": coverage["last_time"],
            "gap_count": len(gaps),
            "duplicate_count": duplicate_count,
            "price_quality_audit": rel(price_quality_json),
            "price_quality_blocker_count": price_quality["blocker_count"],
            "price_quality_warning_count": price_quality["warning_count"],
            "claim_authority": False,
        }
    )
    return coverage


def register_artifact(artifact_id: str, role: str, path: Path, sha256: str) -> None:
    registry = REGISTRY_DIR / "artifact_registry.csv"
    fieldnames = ["artifact_id", "role", "path", "sha256", "produced_by", "created_local", "status", "notes"]
    row = {
        "artifact_id": artifact_id,
        "role": role,
        "path": rel(path),
        "sha256": sha256,
        "produced_by": "build_us100_m5_base_frame",
        "created_local": utc_now(),
        "status": "active",
        "notes": "fresh_mt5_export_no_label_feature_model_claim",
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
