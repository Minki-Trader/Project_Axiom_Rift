"""Shared MT5 CSV and tester output helpers."""

from __future__ import annotations

import csv
import time
from pathlib import Path


def read_compile_log(path: Path) -> str:
    if not path.exists():
        return ""
    for encoding in ("utf-16", "utf-8", "cp1252"):
        try:
            return path.read_text(encoding=encoding, errors="ignore")
        except OSError:
            continue
    return path.read_text(errors="ignore")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_status_csv(path: Path) -> dict[str, str]:
    rows = read_csv_rows(path)
    return {row["field"]: row["value"] for row in rows if "field" in row and "value" in row}


def wait_for_status(path: Path, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_status = "missing"
    while time.time() < deadline:
        if path.exists() and path.stat().st_size > 0:
            try:
                fields = read_status_csv(path)
            except (OSError, KeyError, UnicodeDecodeError, csv.Error):
                time.sleep(1)
                continue
            last_status = fields.get("status", "")
            if last_status == "completed":
                return
            if last_status.startswith("invalid") or last_status.endswith("failed"):
                raise RuntimeError(f"MT5 tester wrote failure status: {last_status}")
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for completed MT5 status file: {path}; last_status={last_status}")


def tester_model_label(config: Path) -> str:
    model_value = ""
    if config.exists():
        for line in config.read_text(encoding="ascii").splitlines():
            if line.startswith("Model="):
                model_value = line.split("=", 1)[1].strip()
                break
    labels = {
        "1": "ohlc_model_1",
        "2": "open_prices_model_2",
        "4": "real_ticks_model_4",
    }
    return labels.get(model_value, f"mt5_model_{model_value}" if model_value else "unknown")
