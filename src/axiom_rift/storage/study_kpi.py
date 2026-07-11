"""Deterministic tracked projection of immutable Study KPI records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
import tempfile
from typing import Iterable


LEDGER_RELATIVE_PATH = "records/STUDY_KPI.md"
_KST = timezone(timedelta(hours=9))
_METRIC_NAMES = (
    "net_profit_micropoints",
    "median_fold_profit_factor_milli",
    "trade_count",
    "monthly_realized_exit_drawdown_share_of_gross_profit_ppm",
)


def _ascii(name: str, value: str) -> str:
    if not isinstance(value, str) or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    if any(character in value for character in "|\r\n"):
        raise ValueError(f"{name} is unsafe for a Markdown row")
    return value


def _metric(name: str, value: int | None) -> int | None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValueError(f"{name} must be an integer or null")
    return value


def validate_study_id(value: str) -> str:
    try:
        study_id = _ascii("Study id", value)
    except ValueError as exc:
        raise ValueError("Study KPI row has an invalid Study id") from exc
    suffix = study_id.removeprefix("STU-")
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")
    if (
        not study_id.startswith("STU-")
        or not suffix
        or suffix[0] == "-"
        or suffix[-1] == "-"
        or any(character not in allowed for character in suffix)
    ):
        raise ValueError("Study KPI row has an invalid Study id")
    return study_id


@dataclass(frozen=True, slots=True, kw_only=True)
class StudyKpiProjectionRow:
    sequence: int
    closed_at_utc: str
    study_id: str
    executable_id: str | None
    executable_display_id: str | None
    net_profit_micropoints: int | None
    median_fold_profit_factor_milli: int | None
    trade_count: int | None
    monthly_realized_exit_drawdown_share_of_gross_profit_ppm: int | None
    outcome: str

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise ValueError("Study KPI sequence must be an integer")
        if self.sequence < 1:
            raise ValueError("Study KPI sequence must be positive")
        _closed_at_kst(self.closed_at_utc)
        validate_study_id(self.study_id)
        if self.executable_id is not None:
            executable_id = _ascii("Executable id", self.executable_id)
            digest = executable_id.removeprefix("executable:")
            if (
                not executable_id.startswith("executable:")
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError("Study KPI row has an invalid Executable id")
            display = _ascii("Executable display id", self.executable_display_id)
            display_digest = display.removeprefix("EXE-")
            if (
                not display.startswith("EXE-")
                or len(display_digest) < 12
                or len(display_digest) > 64
                or len(display_digest) % 4 != 0
                or any(
                    character not in "0123456789abcdef"
                    for character in display_digest
                )
                or not digest.startswith(display_digest)
            ):
                raise ValueError("Study KPI row has an invalid Executable display id")
        elif self.executable_display_id is not None:
            raise ValueError("Unavailable Study KPI cannot have an Executable display id")
        for name in _METRIC_NAMES:
            _metric(name, getattr(self, name))
        _ascii("Study outcome", self.outcome)


def _closed_at_kst(value: str) -> str:
    _ascii("Study close time", value)
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Study close time is not ISO-8601") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Study close time must include an offset")
    return instant.astimezone(_KST).strftime("%Y-%m-%d %H:%M")


def _integer(value: int | None) -> str:
    return "-" if value is None else f"{value:,}"


def _compact_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _profit_factor(value: int | None) -> str:
    if value is None:
        return "-"
    return _compact_decimal(Decimal(value) / Decimal(1000))


def _drawdown_share(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{_compact_decimal(Decimal(value) / Decimal(10000))}%"


def render_study_kpi(rows: Iterable[StudyKpiProjectionRow]) -> bytes:
    ordered = tuple(sorted(rows, key=lambda row: row.sequence))
    if [row.sequence for row in ordered] != list(range(1, len(ordered) + 1)):
        raise ValueError("Study KPI sequences must be contiguous from one")
    study_ids = [row.study_id for row in ordered]
    if len(set(study_ids)) != len(study_ids):
        raise ValueError("Study KPI projection contains a duplicate Study")
    display_owners: dict[str, str] = {}
    for row in ordered:
        if row.executable_id is None:
            continue
        owner = display_owners.get(row.executable_display_id)
        if owner is not None and owner != row.executable_id:
            raise ValueError("Executable display id collision")
        display_owners[row.executable_display_id] = row.executable_id
    lines = [
        "# Study KPI Ledger",
        "",
        "This file is a non-authoritative Git projection of immutable `study-kpi`",
        "Journal records. Rows are prospective from checkpoint activation; no",
        "historical KPI or representative Executable is inferred.",
        "",
        "`Executable` is a stable collision-checked display prefix assigned in the",
        "Journal record. The full immutable identity remains there. Missing KPI is `-`.",
        "",
        "| No | Closed at (KST) | Study | Executable | Net profit (micropoints) | Median fold PF | Trades | Monthly DD / gross | Outcome |",
        "| ---: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | :--- |",
    ]
    for row in ordered:
        executable = (
            "-"
            if row.executable_id is None
            else row.executable_display_id
        )
        lines.append(
            "| "
            + " | ".join(
                (
                    f"{row.sequence:06d}",
                    _closed_at_kst(row.closed_at_utc),
                    row.study_id,
                    executable,
                    _integer(row.net_profit_micropoints),
                    _profit_factor(row.median_fold_profit_factor_milli),
                    _integer(row.trade_count),
                    _drawdown_share(
                        row.monthly_realized_exit_drawdown_share_of_gross_profit_ppm
                    ),
                    row.outcome,
                )
            )
            + " |"
        )
    content = ("\n".join(lines) + "\n").encode("ascii")
    return content


def materialize_study_kpi(
    path: str | Path,
    rows: Iterable[StudyKpiProjectionRow],
) -> bool:
    target = Path(path)
    content = render_study_kpi(rows)
    if target.is_file() and target.read_bytes() == content:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    if target.read_bytes() != content:
        raise OSError("Study KPI projection did not materialize exact bytes")
    return True


__all__ = [
    "LEDGER_RELATIVE_PATH",
    "StudyKpiProjectionRow",
    "materialize_study_kpi",
    "render_study_kpi",
    "validate_study_id",
]
