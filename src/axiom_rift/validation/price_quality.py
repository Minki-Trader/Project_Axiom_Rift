"""Price quality audit helpers for processed US100 M5 bars."""

from __future__ import annotations

from typing import Any


PRICE_QUALITY_AUDIT_SCHEMA = "axiom_rift_us100_m5_price_quality_v1"
PRICE_QUALITY_AUDIT_RELATIVE_PATH = "data/processed/coverage_audits/us100_m5_price_quality.json"
BASE_FRAME_RELATIVE_PATH = "data/processed/datasets/us100_m5_base_frame.csv"

PRICE_FIELDS = ("open", "high", "low", "close")
VOLUME_AND_COST_FIELDS = ("tick_volume", "spread", "real_volume")
NUMERIC_FIELDS = PRICE_FIELDS + VOLUME_AND_COST_FIELDS
SPIKE_MULTIPLIER = 5.0
MAX_BLOCKER_PREVIEW = 25
MAX_WARNING_SAMPLES = 10


class PriceQualityError(ValueError):
    """Raised when a base-frame price quality audit has blocking issues."""

    def __init__(self, audit: dict[str, Any]) -> None:
        self.audit = audit
        super().__init__(f"price quality audit has {audit.get('blocker_count', 0)} blocking issues")


def build_price_quality_audit(
    rows: list[dict[str, str]],
    *,
    created_at_utc: str,
    source_raw_csv: str,
    base_frame_csv: str,
    base_frame_sha256: str | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    blocker_count = 0
    valid_rows: list[dict[str, Any]] = []

    def add_blocker(code: str, row_number: int, row: dict[str, str], detail: str) -> None:
        nonlocal blocker_count
        blocker_count += 1
        if len(blockers) >= MAX_BLOCKER_PREVIEW:
            return
        blockers.append(
            {
                "severity": "error",
                "code": code,
                "row_number": row_number,
                "time": row.get("time"),
                "detail": detail,
                "values": {field: row.get(field) for field in ("open", "high", "low", "close", "spread", "tick_volume", "real_volume")},
            }
        )

    for row_index, row in enumerate(rows, start=2):
        parsed: dict[str, float] = {}
        row_blocker_start = blocker_count
        for field in NUMERIC_FIELDS:
            raw_value = row.get(field)
            try:
                if raw_value in (None, ""):
                    raise ValueError("missing value")
                parsed[field] = float(raw_value)
            except ValueError as exc:
                add_blocker("numeric_parse_failed", row_index, row, f"{field}: {exc}")
        if set(parsed) != set(NUMERIC_FIELDS):
            continue

        high = parsed["high"]
        low = parsed["low"]
        open_price = parsed["open"]
        close = parsed["close"]
        if high < open_price:
            add_blocker("high_below_open", row_index, row, "high is below open")
        if high < close:
            add_blocker("high_below_close", row_index, row, "high is below close")
        if low > open_price:
            add_blocker("low_above_open", row_index, row, "low is above open")
        if low > close:
            add_blocker("low_above_close", row_index, row, "low is above close")
        if high < low:
            add_blocker("high_below_low", row_index, row, "high is below low")
        for field in VOLUME_AND_COST_FIELDS:
            if parsed[field] < 0:
                add_blocker(f"negative_{field}", row_index, row, f"{field} is negative")

        if blocker_count == row_blocker_start:
            valid_rows.append(
                {
                    "row_number": row_index,
                    "time": row.get("time"),
                    "open": parsed["open"],
                    "high": parsed["high"],
                    "low": parsed["low"],
                    "close": parsed["close"],
                    "tick_volume": parsed["tick_volume"],
                    "spread": parsed["spread"],
                    "real_volume": parsed["real_volume"],
                    "range_points": parsed["high"] - parsed["low"],
                }
            )

    warnings = build_warning_summaries(valid_rows)
    warning_count = sum(int(warning["count"]) for warning in warnings)
    return {
        "schema": PRICE_QUALITY_AUDIT_SCHEMA,
        "created_at_utc": created_at_utc,
        "source_raw_csv": source_raw_csv,
        "base_frame_csv": base_frame_csv,
        "base_frame_sha256": base_frame_sha256,
        "row_count": len(rows),
        "valid_price_row_count": len(valid_rows),
        "blocker_count": blocker_count,
        "blocker_preview": blockers,
        "warning_count": warning_count,
        "warnings": warnings,
        "statistics": build_statistics(valid_rows),
        "checks": {
            "blocker_policy": [
                "numeric_ohlc_spread_volume_required",
                "high_must_cover_open_and_close",
                "low_must_cover_open_and_close",
                "high_must_not_be_below_low",
                "spread_and_volume_must_be_non_negative",
            ],
            "warning_policy": {
                "range_spike": f"range_points > p99 * {SPIKE_MULTIPLIER}",
                "close_jump_spike": f"abs_close_delta_points > p99 * {SPIKE_MULTIPLIER}",
                "spread_spike": f"spread > p99 * {SPIKE_MULTIPLIER}",
                "zero_tick_volume": "tick_volume == 0",
            },
        },
        "claim_boundary": {
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "runtime_authority": False,
            "live_ready": False,
        },
    }


def require_no_price_quality_blockers(audit: dict[str, Any]) -> None:
    if int(audit.get("blocker_count") or 0) > 0:
        raise PriceQualityError(audit)


def build_warning_summaries(valid_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    warnings.extend(spike_warning(valid_rows, "range_spike", "range_points"))
    warnings.extend(spike_warning(valid_rows, "spread_spike", "spread"))
    warnings.extend(close_jump_warning(valid_rows))
    zero_tick_rows = [row for row in valid_rows if row["tick_volume"] == 0]
    if zero_tick_rows:
        warnings.append(
            {
                "severity": "warning",
                "code": "zero_tick_volume",
                "metric": "tick_volume",
                "count": len(zero_tick_rows),
                "samples": sample_rows(zero_tick_rows),
            }
        )
    return warnings


def spike_warning(rows: list[dict[str, Any]], code: str, metric: str) -> list[dict[str, Any]]:
    values = [float(row[metric]) for row in rows]
    if not values:
        return []
    p99 = percentile(values, 0.99)
    threshold = p99 * SPIKE_MULTIPLIER
    if threshold <= 0:
        return []
    offenders = [row for row in rows if float(row[metric]) > threshold]
    if not offenders:
        return []
    return [
        {
            "severity": "warning",
            "code": code,
            "metric": metric,
            "count": len(offenders),
            "p99": rounded(p99),
            "threshold": rounded(threshold),
            "threshold_basis": f"p99_x_{SPIKE_MULTIPLIER}",
            "max": rounded(max(values)),
            "samples": sample_rows(sorted(offenders, key=lambda row: float(row[metric]), reverse=True), metric),
        }
    ]


def close_jump_warning(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deltas: list[dict[str, Any]] = []
    previous_close: float | None = None
    for row in rows:
        close = float(row["close"])
        if previous_close is not None:
            delta = abs(close - previous_close)
            enriched = dict(row)
            enriched["abs_close_delta_points"] = delta
            deltas.append(enriched)
        previous_close = close
    values = [float(row["abs_close_delta_points"]) for row in deltas]
    if not values:
        return []
    p99 = percentile(values, 0.99)
    threshold = p99 * SPIKE_MULTIPLIER
    if threshold <= 0:
        return []
    offenders = [row for row in deltas if float(row["abs_close_delta_points"]) > threshold]
    if not offenders:
        return []
    return [
        {
            "severity": "warning",
            "code": "close_jump_spike",
            "metric": "abs_close_delta_points",
            "count": len(offenders),
            "p99": rounded(p99),
            "threshold": rounded(threshold),
            "threshold_basis": f"p99_x_{SPIKE_MULTIPLIER}",
            "max": rounded(max(values)),
            "samples": sample_rows(
                sorted(offenders, key=lambda row: float(row["abs_close_delta_points"]), reverse=True),
                "abs_close_delta_points",
            ),
        }
    ]


def build_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "range_points": metric_stats(rows, "range_points"),
        "spread": metric_stats(rows, "spread"),
        "tick_volume": metric_stats(rows, "tick_volume"),
        "abs_close_delta_points": close_delta_stats(rows),
        "zero_tick_volume_count": sum(1 for row in rows if row["tick_volume"] == 0),
    }


def metric_stats(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    values = [float(row[metric]) for row in rows]
    if not values:
        return {"count": 0, "p99": None, "max": None}
    return {"count": len(values), "p99": rounded(percentile(values, 0.99)), "max": rounded(max(values))}


def close_delta_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    previous_close: float | None = None
    values: list[float] = []
    for row in rows:
        close = float(row["close"])
        if previous_close is not None:
            values.append(abs(close - previous_close))
        previous_close = close
    if not values:
        return {"count": 0, "p99": None, "max": None}
    return {"count": len(values), "p99": rounded(percentile(values, 0.99)), "max": rounded(max(values))}


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def sample_rows(rows: list[dict[str, Any]], metric: str | None = None) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in rows[:MAX_WARNING_SAMPLES]:
        sample = {
            "row_number": row["row_number"],
            "time": row["time"],
            "open": rounded(row["open"]),
            "high": rounded(row["high"]),
            "low": rounded(row["low"]),
            "close": rounded(row["close"]),
            "spread": rounded(row["spread"]),
            "tick_volume": rounded(row["tick_volume"]),
            "real_volume": rounded(row["real_volume"]),
        }
        if metric is not None:
            sample[metric] = rounded(row[metric])
        samples.append(sample)
    return samples


def rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 10)
    return value
