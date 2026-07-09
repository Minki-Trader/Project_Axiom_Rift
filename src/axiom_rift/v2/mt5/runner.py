"""Bounded MT5 compile and tester jobs for the V2 native reference path."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from axiom_rift.mt5.runtime_config import load_runtime_config
from axiom_rift.mt5.terminal_hygiene import cleanup_headless_terminal, prepare_headless_terminal
from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.v2.features import FEATURE_NAMES
from axiom_rift.v2.materialization.fixture import (
    FIXTURE_HOLD_BARS,
    FIXTURE_MAX_DAILY_ENTRIES,
    FIXTURE_THRESHOLD,
    evaluate_fixture,
    fixture_identity,
    reference_linear_bundle,
    synthetic_fixture_bars,
    write_fixture_bars,
    write_fixture_expected,
)
from axiom_rift.v2.materialization.linear_onnx import export_linear_onnx


SOURCE_ROOT = PROJECT_ROOT / "src" / "axiom_rift" / "v2" / "mt5"
EA_SOURCE = SOURCE_ROOT / "experts" / "AxiomV2ReferenceEA.mq5"
FEATURE_INCLUDE = SOURCE_ROOT / "include" / "AxiomV2Features.mqh"
ONNX_INCLUDE = SOURCE_ROOT / "include" / "AxiomV2Onnx.mqh"
MODEL_SOURCE = SOURCE_ROOT / "models" / "axiom_v2_reference.onnx"
DEPLOY_RELATIVE = Path("MQL5") / "Experts" / "AxiomRiftV2"
EXPERT_TESTER_NAME = "AxiomRiftV2\\experts\\AxiomV2ReferenceEA"
COMMON_SUBDIR = Path("AxiomRiftV2")


class Mt5JobError(RuntimeError):
    """Raised when a bounded V2 MT5 evidence job fails."""


@dataclass(frozen=True)
class CompileResult:
    source_sha256: str
    model_sha256: str
    ex5_sha256: str
    deployed_ex5: Path
    durable_ex5: Path
    log: Path
    duration_seconds: float


@dataclass(frozen=True)
class TesterResult:
    config: Path
    report: Path
    status: Path
    output: Path
    decision_log: Path
    duration_seconds: float
    process_returncode: int


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _read_compile_log(path: Path) -> str:
    raw = path.read_bytes() if path.exists() else b""
    for encoding in ("utf-16", "utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def compile_reference_ea(job_dir: Path, timeout_seconds: int = 60) -> CompileResult:
    job_dir = job_dir.resolve()
    started = time.monotonic()
    runtime = load_runtime_config()
    if not runtime.metaeditor_exe.is_file():
        raise Mt5JobError(f"MetaEditor is missing: {runtime.metaeditor_exe}")
    export_linear_onnx(MODEL_SOURCE, reference_linear_bundle())
    deploy_root = runtime.terminal_data_dir / DEPLOY_RELATIVE
    for directory in ("experts", "include", "models"):
        (deploy_root / directory).mkdir(parents=True, exist_ok=True)
    copies = (
        (EA_SOURCE, deploy_root / "experts" / EA_SOURCE.name),
        (FEATURE_INCLUDE, deploy_root / "include" / FEATURE_INCLUDE.name),
        (ONNX_INCLUDE, deploy_root / "include" / ONNX_INCLUDE.name),
        (MODEL_SOURCE, deploy_root / "models" / MODEL_SOURCE.name),
    )
    for source, target in copies:
        shutil.copy2(source, target)
    target = deploy_root / "experts" / EA_SOURCE.name
    log = job_dir / "compile" / "metaeditor.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [str(runtime.metaeditor_exe), f"/compile:{target}", f"/log:{log}"],
        cwd=str(PROJECT_ROOT),
        timeout=timeout_seconds,
        check=False,
    )
    ex5 = target.with_suffix(".ex5")
    log_text = _read_compile_log(log)
    if not ex5.is_file() or "0 errors" not in log_text:
        tail = " | ".join(line.strip() for line in log_text.splitlines()[-12:])
        raise Mt5JobError(f"MetaEditor compile failed rc={completed.returncode}: {tail}")
    durable_ex5 = job_dir / "compile" / ex5.name
    shutil.copy2(ex5, durable_ex5)
    return CompileResult(
        source_sha256=sha256_file(EA_SOURCE),
        model_sha256=sha256_file(MODEL_SOURCE),
        ex5_sha256=sha256_file(ex5),
        deployed_ex5=ex5,
        durable_ex5=durable_ex5,
        log=log,
        duration_seconds=time.monotonic() - started,
    )


def common_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "MetaQuotes" / "Terminal" / "Common" / "Files" / COMMON_SUBDIR


def clear_common_outputs() -> None:
    directory = common_dir().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    expected_parent = (Path(os.environ["APPDATA"]) / "MetaQuotes" / "Terminal" / "Common" / "Files").resolve()
    if expected_parent not in directory.parents:
        raise Mt5JobError("refusing to clear output outside the MT5 common files directory")
    for name in ("fixture_actual.csv", "status.csv", "online_decisions.csv"):
        (directory / name).unlink(missing_ok=True)


def _account_lines() -> list[str]:
    runtime = load_runtime_config()
    return runtime.tester_account_lines()


def write_tester_config(
    job_dir: Path,
    *,
    mode: str,
    tester_model: int,
    from_date: str,
    to_date: str,
    dry_run: bool,
) -> tuple[Path, Path]:
    job_dir = job_dir.resolve()
    if mode not in {"fixture", "online"}:
        raise ValueError(f"unsupported reference mode: {mode}")
    runtime = load_runtime_config()
    config = job_dir / f"tester_{mode}_model{tester_model}.ini"
    report = job_dir / f"tester_{mode}_model{tester_model}_report.htm"
    lines = [
        "[Tester]",
        f"Expert={EXPERT_TESTER_NAME}",
        f"Symbol={runtime.symbol}",
        f"Period={runtime.timeframe}",
        f"Model={tester_model}",
        f"FromDate={from_date}",
        f"ToDate={to_date}",
        "ForwardMode=0",
        *_account_lines(),
        "Optimization=0",
        "Visual=0",
        f"Report={report.with_suffix('')}",
        "ReplaceReport=1",
        "ShutdownTerminal=Yes",
        "",
        "[TesterInputs]",
        f"InpMode={mode}",
        "InpFixturePath=AxiomRiftV2\\fixture_bars.csv",
        "InpFixtureOutputPath=AxiomRiftV2\\fixture_actual.csv",
        "InpStatusPath=AxiomRiftV2\\status.csv",
        "InpDecisionLogPath=AxiomRiftV2\\online_decisions.csv",
        f"InpScoreThreshold={FIXTURE_THRESHOLD:g}",
        f"InpHoldBars={FIXTURE_HOLD_BARS}",
        f"InpMaxDailyEntries={FIXTURE_MAX_DAILY_ENTRIES}",
        f"InpDryRun={'true' if dry_run else 'false'}",
        f"InpLot={runtime.default_lot:g}",
        "InpMagic=2200001",
        "",
    ]
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("\n".join(lines), encoding="ascii")
    return config, report


def _read_status(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="ascii", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {str(row.get("field")): str(row.get("value")) for row in rows}


def run_reference_tester(
    job_dir: Path,
    *,
    mode: str,
    tester_model: int,
    from_date: str,
    to_date: str,
    dry_run: bool,
    timeout_seconds: int = 60,
) -> TesterResult:
    runtime = load_runtime_config()
    config, report = write_tester_config(
        job_dir,
        mode=mode,
        tester_model=tester_model,
        from_date=from_date,
        to_date=to_date,
        dry_run=dry_run,
    )
    status = common_dir() / "status.csv"
    output = common_dir() / "fixture_actual.csv"
    decision_log = common_dir() / "online_decisions.csv"
    report.unlink(missing_ok=True)
    clear_common_outputs()
    prepare_headless_terminal(runtime.terminal_data_dir)
    started = time.monotonic()
    process: subprocess.Popen[bytes] | None = None
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [str(runtime.terminal_exe), f"/config:{config}"],
            cwd=str(PROJECT_ROOT),
            creationflags=creationflags,
        )
        deadline = time.monotonic() + timeout_seconds
        expected = "fixture_completed" if mode == "fixture" else "online_completed"
        while time.monotonic() < deadline:
            payload = _read_status(status)
            if payload.get("status") == expected:
                break
            if payload.get("status") in {"init_failed", "fixture_failed"}:
                raise Mt5JobError(f"MT5 reference job failed: {payload}")
            if process.poll() is not None and payload.get("status") != expected:
                raise Mt5JobError(f"MT5 exited before expected status: rc={process.returncode}, status={payload}")
            time.sleep(0.2)
        else:
            raise Mt5JobError(f"MT5 reference job exceeded {timeout_seconds}s: {mode}")
        try:
            returncode = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            returncode = process.wait(timeout=10)
    except Exception:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        raise
    finally:
        cleanup_headless_terminal(runtime.terminal_data_dir)
    return TesterResult(
        config=config,
        report=report,
        status=status,
        output=output,
        decision_log=decision_log,
        duration_seconds=time.monotonic() - started,
        process_returncode=returncode,
    )


def compare_fixture_csv(expected_path: Path, actual_path: Path, tolerance: float = 2e-5) -> dict[str, Any]:
    with expected_path.open("r", encoding="ascii", newline="") as handle:
        expected = list(csv.DictReader(handle))
    with actual_path.open("r", encoding="ascii", newline="") as handle:
        actual = list(csv.DictReader(handle))
    if len(expected) != len(actual):
        raise Mt5JobError(f"fixture row count mismatch: Python={len(expected)} MQL={len(actual)}")
    numeric_fields = [*[f"f{index}" for index in range(len(FEATURE_NAMES))], "score"]
    exact_fields = ["index", "time", "raw_direction", "admitted_direction", "active_direction", "event"]
    maximum_error = 0.0
    for row_index, (left, right) in enumerate(zip(expected, actual, strict=True)):
        for field in exact_fields:
            if left[field] != right[field]:
                raise Mt5JobError(f"fixture exact mismatch row={row_index} field={field}: {left[field]} != {right[field]}")
        for field in numeric_fields:
            error = abs(float(left[field]) - float(right[field]))
            maximum_error = max(maximum_error, error)
            if error > tolerance:
                raise Mt5JobError(f"fixture numeric mismatch row={row_index} field={field}: error={error}")
    return {
        "schema": "axiom_rift_v2_fixture_parity_v1",
        "row_count": len(expected),
        "numeric_tolerance": tolerance,
        "maximum_absolute_error": maximum_error,
        "timestamp_direction_lifecycle_exact": True,
        "python_mql_feature_parity": True,
        "python_onnx_score_parity": True,
        "mql_onnx_score_path_executed": True,
        "claim_ceiling": "none",
    }


def run_reference_fixture_job(job_dir: Path) -> dict[str, Any]:
    job_dir = job_dir.resolve()
    started_at = utc_now()
    started = time.monotonic()
    job_dir.mkdir(parents=True, exist_ok=True)
    bundle = reference_linear_bundle()
    export_linear_onnx(MODEL_SOURCE, bundle)
    bars = synthetic_fixture_bars()
    fixture_path = job_dir / "fixture_bars.csv"
    expected_path = job_dir / "fixture_expected.csv"
    write_fixture_bars(fixture_path, bars)
    expected_rows = evaluate_fixture(bars, bundle, onnx_path=MODEL_SOURCE)
    write_fixture_expected(expected_path, expected_rows)
    destination = common_dir() / "fixture_bars.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fixture_path, destination)
    compiled = compile_reference_ea(job_dir)
    tester = run_reference_tester(
        job_dir,
        mode="fixture",
        tester_model=2,
        from_date="2026.04.01",
        to_date="2026.04.02",
        dry_run=True,
    )
    actual_path = job_dir / "fixture_actual.csv"
    shutil.copy2(tester.output, actual_path)
    parity = compare_fixture_csv(expected_path, actual_path)
    receipt = {
        "schema": "axiom_rift_v2_reference_fixture_receipt_v1",
        "status": "passed",
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
        "duration_seconds": time.monotonic() - started,
        "job_kind": "bounded_non_economic_fixture",
        "fixture_identity_sha256": fixture_identity(expected_rows),
        "model_bundle_sha256": bundle.content_sha256,
        "model_sha256": compiled.model_sha256,
        "source_sha256": compiled.source_sha256,
        "ex5_sha256": compiled.ex5_sha256,
        "compile_duration_seconds": compiled.duration_seconds,
        "tester_duration_seconds": tester.duration_seconds,
        "tester_model": 2,
        "tester_mode": "closed_bar_fixture",
        "paths": {
            "fixture_bars": rel(fixture_path),
            "fixture_expected": rel(expected_path),
            "fixture_actual": rel(actual_path),
            "model": rel(MODEL_SOURCE),
            "ea_source": rel(EA_SOURCE),
            "ea_binary": rel(compiled.durable_ex5),
            "compile_log": rel(compiled.log),
            "tester_config": rel(tester.config),
            "tester_report": rel(tester.report),
        },
        "parity": parity,
        "economics_claim": False,
        "runtime_authority": False,
        "claim_ceiling": "none",
    }
    receipt_path = job_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="ascii")
    return receipt


def run_reference_online_smoke_job(job_dir: Path, *, real_ticks: bool = True) -> dict[str, Any]:
    job_dir = job_dir.resolve()
    started_at = utc_now()
    started = time.monotonic()
    job_dir.mkdir(parents=True, exist_ok=True)
    compiled = compile_reference_ea(job_dir)
    model = 4 if real_ticks else 2
    tester = run_reference_tester(
        job_dir,
        mode="online",
        tester_model=model,
        from_date="2026.04.01",
        to_date="2026.04.03",
        dry_run=False,
        timeout_seconds=60,
    )
    durable_decisions = job_dir / "online_decisions.csv"
    if not tester.decision_log.is_file():
        raise Mt5JobError("online reference path produced no decision ledger")
    shutil.copy2(tester.decision_log, durable_decisions)
    with durable_decisions.open("r", encoding="ascii", newline="") as handle:
        decisions = list(csv.DictReader(handle))
    admitted = sum(int(row.get("admitted_direction", "0")) != 0 for row in decisions)
    receipt = {
        "schema": "axiom_rift_v2_reference_online_smoke_receipt_v1",
        "status": "passed",
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
        "duration_seconds": time.monotonic() - started,
        "tester_model": model,
        "real_ticks": real_ticks,
        "dry_run": False,
        "decision_count": len(decisions),
        "admitted_entry_count": admitted,
        "native_signal_generation": True,
        "native_position_lifecycle": True,
        "model_sha256": compiled.model_sha256,
        "ex5_sha256": compiled.ex5_sha256,
        "decision_ledger_path": rel(durable_decisions),
        "tester_config_path": rel(tester.config),
        "tester_report_path": rel(tester.report),
        "diagnostic_only": True,
        "economics_claim": False,
        "runtime_authority": False,
        "claim_ceiling": "none",
    }
    (job_dir / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="ascii")
    return receipt
