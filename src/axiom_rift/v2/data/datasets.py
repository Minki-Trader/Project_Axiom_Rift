"""Read-only V2 dataset inspection that returns a receipt payload."""

from __future__ import annotations

import csv
import hashlib
import math
from datetime import datetime
from pathlib import Path
from typing import Any


EXPECTED_COLUMNS = (
    "time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
)
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class UnknownSpreadCostError(ValueError):
    """Raised when an entry would silently receive zero or unknown spread cost."""


def spread_price_cost(
    spread_points: float,
    point_size: float,
    *,
    causal_fallback_points: float | None = None,
    fallback_policy_id: str | None = None,
) -> float:
    """Convert broker spread points to price cost without treating zero as free.

    A fallback is accepted only when its preregistered policy identity is supplied.
    The caller remains responsible for computing that fallback from information
    available no later than the decision time.
    """

    if not math.isfinite(spread_points) or spread_points < 0:
        raise ValueError("spread points must be finite and non-negative")
    if not math.isfinite(point_size) or point_size <= 0:
        raise ValueError("point size must be finite and positive")
    effective_points = spread_points
    if spread_points == 0:
        if causal_fallback_points is None:
            raise UnknownSpreadCostError("zero spread is unknown cost and default policy rejects the entry")
        if not fallback_policy_id:
            raise ValueError("causal spread fallback requires a preregistered policy id")
        if not math.isfinite(causal_fallback_points) or causal_fallback_points <= 0:
            raise ValueError("causal spread fallback must be finite and positive")
        effective_points = causal_fallback_points
    return effective_points * point_size


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_base_frame(path: Path, expected_sha256: str) -> dict[str, Any]:
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ValueError("base-frame hash differs from preregistered V2 input")
    row_count = 0
    duplicate_count = 0
    non_monotonic_count = 0
    invalid_ohlc_count = 0
    negative_spread_count = 0
    zero_spread_count = 0
    negative_tick_volume_count = 0
    negative_real_volume_count = 0
    nonzero_real_volume_count = 0
    off_grid_count = 0
    nonfinite_numeric_count = 0
    timestamp_gap_count = 0
    first_time: datetime | None = None
    last_time: datetime | None = None
    previous: datetime | None = None
    with path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
            raise ValueError("base-frame schema differs from the V2 contract")
        for row in reader:
            timestamp = datetime.strptime(row["time"], TIME_FORMAT)
            if first_time is None:
                first_time = timestamp
            if previous is not None:
                duplicate_count += int(timestamp == previous)
                non_monotonic_count += int(timestamp < previous)
                timestamp_gap_count += int((timestamp - previous).total_seconds() != 300)
            off_grid_count += int(timestamp.second != 0 or timestamp.microsecond != 0 or timestamp.minute % 5 != 0)
            previous = timestamp
            last_time = timestamp
            opening = float(row["open"])
            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])
            tick_volume = float(row["tick_volume"])
            spread = float(row["spread"])
            real_volume = float(row["real_volume"])
            numeric = (opening, high, low, close, tick_volume, spread, real_volume)
            nonfinite_numeric_count += int(not all(math.isfinite(value) for value in numeric))
            invalid_ohlc_count += int(high < max(opening, close) or low > min(opening, close) or high < low)
            negative_spread_count += int(spread < 0)
            zero_spread_count += int(spread == 0)
            negative_tick_volume_count += int(tick_volume < 0)
            negative_real_volume_count += int(real_volume < 0)
            nonzero_real_volume_count += int(real_volume != 0)
            row_count += 1
    if first_time is None or last_time is None:
        raise ValueError("base frame is empty")
    return {
        "schema": "axiom_rift_v2_dataset_receipt_v1",
        "dataset_id": "V2DATA0001",
        "path": path.as_posix(),
        "sha256": actual_sha256,
        "columns": list(EXPECTED_COLUMNS),
        "row_count": row_count,
        "first_time": first_time.strftime(TIME_FORMAT),
        "last_time": last_time.strftime(TIME_FORMAT),
        "duplicate_count": duplicate_count,
        "non_monotonic_count": non_monotonic_count,
        "invalid_ohlc_count": invalid_ohlc_count,
        "negative_spread_count": negative_spread_count,
        "zero_spread_count": zero_spread_count,
        "zero_spread_semantics": "unknown_cost",
        "zero_spread_default_action": "reject_entry_and_economics",
        "negative_tick_volume_count": negative_tick_volume_count,
        "negative_real_volume_count": negative_real_volume_count,
        "nonzero_real_volume_count": nonzero_real_volume_count,
        "real_volume_eligible": False,
        "real_volume_ineligibility_reason": "near_total_absence",
        "tick_volume_semantics": "broker_tick_count_not_traded_volume",
        "off_grid_count": off_grid_count,
        "nonfinite_numeric_count": nonfinite_numeric_count,
        "timestamp_gap_count": timestamp_gap_count,
        "dtypes": {
            "time": "broker_server_datetime_seconds",
            "open": "float64",
            "high": "float64",
            "low": "float64",
            "close": "float64",
            "tick_volume": "int64",
            "spread": "int64_broker_points",
            "real_volume": "int64",
        },
        "time_semantics": "broker_server_bar_open",
        "claim_ceiling": "none",
    }


def compare_raw_to_base(raw_path: Path, base_path: Path) -> dict[str, Any]:
    mismatch_count = 0
    row_count = 0
    with raw_path.open("r", encoding="ascii", newline="") as raw_handle, base_path.open("r", encoding="ascii", newline="") as base_handle:
        raw_reader = csv.DictReader(raw_handle)
        base_reader = csv.DictReader(base_handle)
        if tuple(raw_reader.fieldnames or ()) != EXPECTED_COLUMNS or tuple(base_reader.fieldnames or ()) != EXPECTED_COLUMNS:
            raise ValueError("raw or base schema differs from the V2 contract")
        for raw_row, base_row in zip(raw_reader, base_reader, strict=True):
            normalized = dict(raw_row)
            normalized["time"] = normalized["time"].replace(".", "-")
            mismatch_count += int(normalized != base_row)
            row_count += 1
    return {"row_count": row_count, "mismatch_count": mismatch_count}
