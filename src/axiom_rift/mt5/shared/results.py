"""Shared MT5 result containers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CompileResult:
    source: Path
    target: Path
    ex5: Path
    log: Path


@dataclass(frozen=True)
class TesterResult:
    config: Path
    report: Path
    common_dir: Path
    status_csv: Path
    events_csv: Path
    deals_csv: Path
    mode: str = "logic_parity"
    use_closed_bar_exit: bool = True
    output_scope: str | None = None
    from_date: str = "2024.02.01"
    to_date: str = "2026.05.01"
