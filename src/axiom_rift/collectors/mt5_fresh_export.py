"""MT5 fresh export helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from axiom_rift.paths import DATA_DIR, PROJECT_ROOT, REGISTRY_DIR


DEFAULT_TERMINAL_EXE = Path(r"C:\Program Files\MetaTrader 5\terminal64.exe")
DEFAULT_METAEDITOR_EXE = Path(r"C:\Program Files\MetaTrader 5\MetaEditor64.exe")
DEFAULT_SYMBOL = "US100"
DEFAULT_TIMEFRAME = "M5"
EXPORT_SCRIPT_NAME = "AxiomFreshExport"
TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M:%S")


@dataclass(frozen=True)
class ExportResult:
    symbol: str
    timeframe: str
    raw_csv: Path
    status_csv: Path
    terminal_file_csv: Path
    row_count: int
    first_time: str | None
    last_time: str | None
    sha256: str


def terminal_data_dir() -> Path:
    return PROJECT_ROOT.parents[2]


def terminal_scripts_dir() -> Path:
    return terminal_data_dir() / "MQL5" / "Scripts" / "AxiomRift"


def terminal_files_dir() -> Path:
    return terminal_data_dir() / "MQL5" / "Files" / "AxiomRift"


def raw_bar_dir() -> Path:
    return DATA_DIR / "raw" / "mt5_bars" / "m5"


def processed_dataset_dir() -> Path:
    return DATA_DIR / "processed" / "datasets"


def coverage_audit_dir() -> Path:
    return DATA_DIR / "processed" / "coverage_audits"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def normalize_time(value: str | None) -> str | None:
    if not value:
        return value
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return value


def copy_export_script() -> Path:
    source = PROJECT_ROOT / "src" / "axiom_rift" / "mt5" / "scripts" / f"{EXPORT_SCRIPT_NAME}.mq5"
    target_dir = terminal_scripts_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{EXPORT_SCRIPT_NAME}.mq5"
    shutil.copy2(source, target)
    return target


def compile_script(script_path: Path, metaeditor_exe: Path = DEFAULT_METAEDITOR_EXE) -> Path:
    if not metaeditor_exe.exists():
        raise FileNotFoundError(f"MetaEditor not found: {metaeditor_exe}")
    log_path = PROJECT_ROOT / "artifacts" / "reports" / "mt5_export_compile.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(metaeditor_exe), f"/compile:{script_path}", f"/log:{log_path}"]
    completed = subprocess.run(cmd, cwd=str(PROJECT_ROOT), timeout=120)
    ex5_path = script_path.with_suffix(".ex5")
    if not ex5_path.exists():
        raise RuntimeError(f"Compiled script not found: {ex5_path}")
    log_text = log_path.read_text(encoding="utf-16", errors="ignore") if log_path.exists() else ""
    if completed.returncode != 0 and "0 errors, 0 warnings" not in log_text:
        raise RuntimeError(f"MetaEditor compile failed: rc={completed.returncode}, log={log_path}")
    return log_path


def write_startup_config(symbol: str, timeframe: str) -> Path:
    config_dir = PROJECT_ROOT / "artifacts" / "reports" / "mt5_export_startup"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"{symbol}_{timeframe}_fresh_export.ini"
    config_path.write_text(
        "\n".join(
            [
                "[StartUp]",
                f"Symbol={symbol}",
                f"Period={timeframe}",
                f"Script=AxiomRift\\{EXPORT_SCRIPT_NAME}",
                "ShutdownTerminal=Yes",
                "",
            ]
        ),
        encoding="ascii",
    )
    return config_path


def wait_for_file(path: Path, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for {path}")


def run_terminal_export(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = DEFAULT_TIMEFRAME,
    terminal_exe: Path = DEFAULT_TERMINAL_EXE,
    timeout_seconds: int = 240,
) -> ExportResult:
    if not terminal_exe.exists():
        raise FileNotFoundError(f"Terminal not found: {terminal_exe}")

    script_path = copy_export_script()
    compile_script(script_path)

    files_dir = terminal_files_dir()
    files_dir.mkdir(parents=True, exist_ok=True)
    terminal_csv = files_dir / f"{symbol}_{timeframe}_max.csv"
    terminal_status = files_dir / f"{symbol}_{timeframe}_max_status.csv"
    for path in (terminal_csv, terminal_status):
        if path.exists():
            path.unlink()

    config_path = write_startup_config(symbol, timeframe)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        [str(terminal_exe), f"/config:{config_path}"],
        cwd=str(PROJECT_ROOT),
        creationflags=creationflags,
    )
    try:
        wait_for_file(terminal_status, timeout_seconds=timeout_seconds)
        wait_for_file(terminal_csv, timeout_seconds=timeout_seconds)
    finally:
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.terminate()

    target_raw = raw_bar_dir() / terminal_csv.name
    raw_bar_dir().mkdir(parents=True, exist_ok=True)
    shutil.copy2(terminal_csv, target_raw)
    status_target = raw_bar_dir() / terminal_status.name
    shutil.copy2(terminal_status, status_target)

    result = summarize_bar_csv(target_raw, symbol=symbol, timeframe=timeframe, status_csv=status_target)
    write_source_inventory(result)
    write_source_path_decision(result)
    append_run_event(
        {
            "schema": "axiom_rift_run_event_v1",
            "event_id": f"evt_mt5_fresh_export_max_bars_{utc_stamp()}",
            "created_at_utc": utc_now(),
            "kind": "mt5_fresh_export",
            "status": "completed",
            "symbol": symbol,
            "timeframe": timeframe,
            "raw_csv": rel(result.raw_csv),
            "row_count": result.row_count,
            "first_time": result.first_time,
            "last_time": result.last_time,
            "claim_authority": False,
        }
    )
    return result


def summarize_bar_csv(path: Path, symbol: str, timeframe: str, status_csv: Path) -> ExportResult:
    row_count = 0
    first_time: str | None = None
    last_time: str | None = None
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            row_count += 1
            value = row.get("time")
            if row_count == 1:
                first_time = normalize_time(value)
            last_time = normalize_time(value)
    return ExportResult(
        symbol=symbol,
        timeframe=timeframe,
        raw_csv=path,
        status_csv=status_csv,
        terminal_file_csv=terminal_files_dir() / path.name,
        row_count=row_count,
        first_time=first_time,
        last_time=last_time,
        sha256=sha256_file(path),
    )


def write_source_inventory(result: ExportResult) -> Path:
    inventory = {
        "schema": "axiom_rift_source_inventory_v1",
        "created_at_utc": utc_now(),
        "source_strategy": "fresh_export",
        "broker": "FPMarkets",
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "mt5_bars": {
            "available": result.row_count > 0,
            "path": rel(result.raw_csv),
            "status_path": rel(result.status_csv),
            "row_count": result.row_count,
            "first_time": result.first_time,
            "last_time": result.last_time,
            "sha256": result.sha256,
        },
        "real_ticks": {
            "available_in_terminal_cache": tick_cache_available(result.symbol),
            "exported": False,
            "note": "tick export intentionally not run in this first pass",
        },
        "claim_boundary": {
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "runtime_authority": False,
            "live_ready": False,
        },
    }
    path = REGISTRY_DIR / "source_inventory.json"
    path.write_text(json.dumps(inventory, indent=2, sort_keys=True), encoding="ascii")
    return path


def write_source_path_decision(result: ExportResult) -> Path:
    text = "\n".join(
        [
            "schema: axiom_rift_source_path_decision_v1",
            "created_at_utc: " + utc_now(),
            "decision: fresh_export",
            "source: MT5",
            "broker: FPMarkets",
            f"symbol: {result.symbol}",
            f"timeframe: {result.timeframe}",
            "date_range_policy: max_available_from_terminal",
            "observed_range:",
            f"  first_time: {result.first_time}",
            f"  last_time: {result.last_time}",
            f"  row_count: {result.row_count}",
            f"  raw_sha256: {result.sha256}",
            "paths:",
            f"  raw_m5_bars: {rel(result.raw_csv)}",
            f"  mt5_export_status: {rel(result.status_csv)}",
            "claim_boundary:",
            "  label_selected: false",
            "  feature_set_selected: false",
            "  model_selected: false",
            "  runtime_authority: false",
            "  live_ready: false",
            "",
        ]
    )
    path = REGISTRY_DIR / "source_path_decision.yaml"
    path.write_text(text, encoding="ascii")
    return path


def tick_cache_available(symbol: str) -> bool:
    tick_dir = terminal_data_dir() / "bases" / "FPMarketsSC-Live" / "ticks" / symbol
    return tick_dir.exists() and any(tick_dir.glob("*.tkc"))


def append_run_event(event: dict[str, object]) -> None:
    path = REGISTRY_DIR / "run_registry.jsonl"
    with path.open("a", encoding="ascii", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()
