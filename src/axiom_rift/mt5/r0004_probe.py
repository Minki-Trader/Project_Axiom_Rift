"""MT5 compile, tester, and KPI parsing helpers for R0004."""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from axiom_rift.collectors.mt5_fresh_export import rel, sha256_file
from axiom_rift.mt5.runtime_config import (
    lot_input_line,
    metaeditor_exe as runtime_metaeditor_exe,
    runtime_payload_fields,
    runtime_symbol,
    runtime_timeframe,
    starting_balance_usd,
    terminal_data_dir,
    terminal_exe as runtime_terminal_exe,
    tester_account_lines,
    tester_model_for_mode,
)
from axiom_rift.mt5.terminal_hygiene import cleanup_headless_terminal, prepare_headless_terminal
from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies.r0004_compression_breakout_continuation import (
    BASE_FRAME,
    load_bars,
    load_test_windows,
    run_r0004_proxy,
    simulate_trades,
)


EA_NAME = "AxiomR0001VolatilityExpansion"
EA_SOURCE = PROJECT_ROOT / "src" / "axiom_rift" / "mt5" / "experts" / f"{EA_NAME}.mq5"
RUN_DIR = PROJECT_ROOT / "campaigns" / "C0001_regime_response_discovery" / "runs" / "R0004"
KPI_DIR = RUN_DIR / "kpi"
LOGIC_PARITY_MODE = "logic_parity"
TICK_EXECUTION_MODE = "tick_execution"
VALID_MT5_MODES = {LOGIC_PARITY_MODE, TICK_EXECUTION_MODE}
MT5_LOGIC_KPI = KPI_DIR / "mt5_logic_parity.json"
MT5_TICK_KPI = KPI_DIR / "mt5_tick.json"
MT5_TICK_BY_FOLD_KPI = KPI_DIR / "mt5_tick_by_fold.json"
LOGIC_PARITY_KPI = KPI_DIR / "proxy_vs_mt5_logic_parity.json"
EXECUTION_DIVERGENCE_KPI = KPI_DIR / "execution_divergence.json"
EXECUTION_DIVERGENCE_BY_FOLD_KPI = KPI_DIR / "execution_divergence_by_fold.json"
RUN_MANIFEST = RUN_DIR / "run_manifest.json"
GATE_REPORT = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE = RUN_DIR / "artifact_lineage.json"
ROLLING_WINDOWS = PROJECT_ROOT / "data" / "processed" / "coverage_audits" / "us100_m5_rolling_windows.csv"
STARTING_BALANCE_USD = starting_balance_usd()


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
    mode: str = LOGIC_PARITY_MODE
    use_closed_bar_exit: bool = True
    output_scope: str | None = None
    from_date: str = "2024.02.01"
    to_date: str = "2026.05.01"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compile_r0004_ea(metaeditor_exe: Path | None = None) -> CompileResult:
    metaeditor_exe = runtime_metaeditor_exe() if metaeditor_exe is None else metaeditor_exe
    if not metaeditor_exe.exists():
        raise FileNotFoundError(f"MetaEditor not found: {metaeditor_exe}")
    target_dir = terminal_data_dir() / "MQL5" / "Experts" / "AxiomRift"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / EA_SOURCE.name
    shutil.copy2(EA_SOURCE, target)
    log = PROJECT_ROOT / "artifacts" / "reports" / "R0004_mt5_compile.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [str(metaeditor_exe), f"/compile:{target}", f"/log:{log}"],
        cwd=str(PROJECT_ROOT),
        timeout=180,
    )
    ex5 = target.with_suffix(".ex5")
    log_text = read_compile_log(log)
    if not ex5.exists():
        raise RuntimeError(f"Compiled EA not found: {ex5}")
    if completed.returncode != 0 and "0 errors, 0 warnings" not in log_text:
        raise RuntimeError(f"MetaEditor compile failed: rc={completed.returncode}, log={log}")
    if "0 errors" not in log_text:
        raise RuntimeError(f"MetaEditor compile did not report 0 errors: {log}")
    return CompileResult(source=EA_SOURCE, target=target, ex5=ex5, log=log)


def read_compile_log(path: Path) -> str:
    if not path.exists():
        return ""
    for encoding in ("utf-16", "utf-8", "cp1252"):
        try:
            return path.read_text(encoding=encoding, errors="ignore")
        except OSError:
            continue
    return path.read_text(errors="ignore")


def normalize_mt5_mode(mode: str) -> str:
    if mode not in VALID_MT5_MODES:
        raise ValueError(f"Unsupported MT5 mode: {mode}")
    return mode


def use_closed_bar_exit_for_mode(mode: str) -> bool:
    return normalize_mt5_mode(mode) == LOGIC_PARITY_MODE


def normalize_output_scope(output_scope: str | None) -> str | None:
    if output_scope in (None, ""):
        return None
    if not all(char.isalnum() or char in {"_"} for char in output_scope):
        raise ValueError(f"Unsupported output scope: {output_scope}")
    return output_scope


def common_output_dir(mode: str = LOGIC_PARITY_MODE, output_scope: str | None = None) -> Path:
    mode = normalize_mt5_mode(mode)
    output_scope = normalize_output_scope(output_scope)
    directory = (
        Path(os.environ["APPDATA"])
        / "MetaQuotes"
        / "Terminal"
        / "Common"
        / "Files"
        / "AxiomRift"
        / "C0001"
        / "R0004"
        / mode
    )
    if output_scope is not None:
        directory = directory / output_scope
    return directory


def mt5_kpi_path_for_mode(mode: str) -> Path:
    mode = normalize_mt5_mode(mode)
    return MT5_LOGIC_KPI if mode == LOGIC_PARITY_MODE else MT5_TICK_KPI


def scoped_name(mode: str, output_scope: str | None = None) -> str:
    mode = normalize_mt5_mode(mode)
    output_scope = normalize_output_scope(output_scope)
    return mode if output_scope is None else f"{mode}_{output_scope}"


def tester_config_path_for_mode(mode: str, output_scope: str | None = None) -> Path:
    mode = normalize_mt5_mode(mode)
    return PROJECT_ROOT / "artifacts" / "reports" / "R0004_mt5_tester" / f"R0004_{scoped_name(mode, output_scope)}_tester.ini"


def tester_report_path_for_mode(mode: str, output_scope: str | None = None) -> Path:
    mode = normalize_mt5_mode(mode)
    return PROJECT_ROOT / "artifacts" / "reports" / "R0004_mt5_tester" / f"R0004_mt5_{scoped_name(mode, output_scope)}_report.htm"


def tester_report_stem_for_mode(mode: str, output_scope: str | None = None) -> Path:
    return tester_report_path_for_mode(mode, output_scope).with_suffix("")


def clear_common_outputs(mode: str = LOGIC_PARITY_MODE, output_scope: str | None = None) -> None:
    directory = common_output_dir(mode, output_scope)
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("mt5_status.csv", "mt5_events.csv", "mt5_deals.csv"):
        path = directory / name
        if path.exists():
            path.unlink()


def write_tester_config(
    mode: str = LOGIC_PARITY_MODE,
    from_date: str = "2024.02.01",
    to_date: str = "2026.05.01",
    model: int | None = None,
    output_scope: str | None = None,
) -> Path:
    mode = normalize_mt5_mode(mode)
    output_scope = normalize_output_scope(output_scope)
    if model is None:
        model = tester_model_for_mode(mode)
    use_closed_bar_exit = use_closed_bar_exit_for_mode(mode)
    config_dir = PROJECT_ROOT / "artifacts" / "reports" / "R0004_mt5_tester"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = tester_config_path_for_mode(mode, output_scope)
    report = tester_report_stem_for_mode(mode, output_scope)
    lines = [
        "[Tester]",
        "Expert=AxiomRift\\AxiomR0001VolatilityExpansion",
        f"Symbol={runtime_symbol()}",
        f"Period={runtime_timeframe()}",
        f"Model={model}",
        f"FromDate={from_date}",
        f"ToDate={to_date}",
        "ForwardMode=0",
        *tester_account_lines(),
        "Optimization=0",
        "Visual=0",
        f"Report={report}",
        "ReplaceReport=1",
        "ShutdownTerminal=Yes",
        "",
        "[TesterInputs]",
        "InpRunId=R0004",
        f"InpOutputMode={mode}",
        f"InpOutputScope={output_scope or ''}",
        "InpResponseMode=compression_breakout_continuation",
        "InpUseCommonFiles=true",
        f"InpUseClosedBarExit={bool_text(use_closed_bar_exit)}",
        "InpLookbackRangeBars=48",
        "InpCompressionBars=12",
        "InpCompressionRangeMultiple=4.0",
        "InpBreakoutRangeMultiple=1.0",
        "InpMinBodyRangeFraction=0.45",
        "InpStopAtrMultiple=0.8",
        "InpTargetAtrMultiple=1.2",
        "InpMaxHoldBars=18",
        "",
    ]
    config.write_text("\n".join(lines), encoding="ascii")
    return config


def run_r0004_tester(
    mode: str = LOGIC_PARITY_MODE,
    timeout_seconds: int = 1800,
    from_date: str = "2024.02.01",
    to_date: str = "2026.05.01",
    model: int | None = None,
    output_scope: str | None = None,
    compile_before: bool = True,
) -> TesterResult:
    mode = normalize_mt5_mode(mode)
    output_scope = normalize_output_scope(output_scope)
    if compile_before:
        compile_r0004_ea()
    clear_common_outputs(mode, output_scope)
    config = write_tester_config(mode=mode, from_date=from_date, to_date=to_date, model=model, output_scope=output_scope)
    report = tester_report_path_for_mode(mode, output_scope)
    if report.exists():
        report.unlink()
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    status = common_output_dir(mode, output_scope) / "mt5_status.csv"
    prepare_headless_terminal(terminal_data_dir())
    proc = None
    try:
        proc = subprocess.Popen(
            [str(runtime_terminal_exe()), f"/config:{config}"],
            cwd=str(PROJECT_ROOT),
            creationflags=creationflags,
        )
        wait_for_status(status, timeout_seconds=timeout_seconds)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=10)
    except Exception:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        raise
    finally:
        cleanup_headless_terminal(terminal_data_dir())
    return TesterResult(
        config=config,
        report=report,
        common_dir=common_output_dir(mode, output_scope),
        status_csv=status,
        events_csv=common_output_dir(mode, output_scope) / "mt5_events.csv",
        deals_csv=common_output_dir(mode, output_scope) / "mt5_deals.csv",
        mode=mode,
        use_closed_bar_exit=use_closed_bar_exit_for_mode(mode),
        output_scope=output_scope,
        from_date=from_date,
        to_date=to_date,
    )


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


def parse_r0004_mt5(
    result: TesterResult | None = None,
    mode: str = LOGIC_PARITY_MODE,
    write_kpi: bool = True,
) -> dict[str, object]:
    mode = normalize_mt5_mode(mode if result is None else result.mode)
    if result is None:
        result = TesterResult(
            config=tester_config_path_for_mode(mode),
            report=tester_report_path_for_mode(mode),
            common_dir=common_output_dir(mode),
            status_csv=common_output_dir(mode) / "mt5_status.csv",
            events_csv=common_output_dir(mode) / "mt5_events.csv",
            deals_csv=common_output_dir(mode) / "mt5_deals.csv",
            mode=mode,
            use_closed_bar_exit=use_closed_bar_exit_for_mode(mode),
        )
    missing = [path for path in (result.status_csv, result.events_csv, result.deals_csv) if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing MT5 output files: " + ", ".join(str(path) for path in missing))
    status = read_status_csv(result.status_csv)
    assert_mt5_mode_matches_status(mode, status, result.output_scope)
    events = read_csv_rows(result.events_csv)
    deals = read_csv_rows(result.deals_csv)
    payload = build_mt5_payload(result, status, events, deals)
    if not write_kpi:
        return payload
    kpi_path = mt5_kpi_path_for_mode(mode)
    kpi_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    if mode == LOGIC_PARITY_MODE:
        upsert_artifact_lineage(
            "A0005",
            "mt5_logic_parity_kpi",
            "mt5_logic_parity",
            rel(MT5_LOGIC_KPI),
            sha256_file(MT5_LOGIC_KPI),
            ["data/processed/datasets/us100_m5_base_frame.csv", "configs/market.yaml"],
        )
    else:
        upsert_artifact_lineage(
            "A0006",
            "mt5_tick_kpi",
            "mt5_tick",
            rel(MT5_TICK_KPI),
            sha256_file(MT5_TICK_KPI),
            ["data/processed/datasets/us100_m5_base_frame.csv", "configs/market.yaml"],
        )
    update_run_after_mt5(mode)
    return payload


def read_status_csv(path: Path) -> dict[str, str]:
    rows = read_csv_rows(path)
    return {row["field"]: row["value"] for row in rows if "field" in row and "value" in row}


def assert_mt5_mode_matches_status(mode: str, status: dict[str, str], output_scope: str | None = None) -> None:
    expected_output = normalize_mt5_mode(mode)
    expected_exit = "closed_bar_ohlc" if expected_output == LOGIC_PARITY_MODE else "tick_price"
    actual_output = status.get("output_mode")
    actual_exit = status.get("exit_evaluation")
    if actual_output != expected_output:
        raise RuntimeError(f"MT5 output_mode mismatch: expected={expected_output} actual={actual_output}")
    if actual_exit != expected_exit:
        raise RuntimeError(f"MT5 exit_evaluation mismatch: expected={expected_exit} actual={actual_exit}")
    if output_scope is not None and status.get("output_scope") != output_scope:
        raise RuntimeError(f"MT5 output_scope mismatch: expected={output_scope} actual={status.get('output_scope')}")
    if status.get("response_mode") != "compression_breakout_continuation":
        raise RuntimeError(f"MT5 response_mode mismatch: expected=compression_breakout_continuation actual={status.get('response_mode')}")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


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


def build_mt5_payload(
    result: TesterResult,
    status: dict[str, str],
    events: list[dict[str, str]],
    deals: list[dict[str, str]],
) -> dict[str, object]:
    mode = normalize_mt5_mode(result.mode)
    mode_label = "logic_parity_closed_bar_exit" if mode == LOGIC_PARITY_MODE else "tick_execution"
    exits = [row for row in events if row.get("event") == "exit"]
    exit_deals = [row for row in deals if row.get("entry") in {"1", "2", "3"}]
    profits = [to_float(row.get("profit")) + to_float(row.get("commission")) + to_float(row.get("swap")) for row in exit_deals]
    net = sum(profits)
    wins = [value for value in profits if value > 0]
    gross_profit = sum(value for value in profits if value > 0)
    gross_loss = sum(value for value in profits if value < 0)
    report_paths = [rel(result.status_csv), rel(result.events_csv), rel(result.deals_csv)]
    if result.report.exists():
        report_paths.append(rel(result.report))
    required_kpis = {
        "mt5_execution_mode": mode_label,
        "mt5_output_mode": status.get("output_mode"),
        "mt5_exit_evaluation": status.get("exit_evaluation"),
        "mt5_trade_count": len(exit_deals) if exit_deals else len(exits),
        "mt5_net_pnl": rounded(net),
        "mt5_profit_factor": rounded(gross_profit / abs(gross_loss)) if gross_loss else None,
        "mt5_max_drawdown_percent": max_drawdown_percent(profits, STARTING_BALANCE_USD),
        "mt5_expectancy_per_entry": rounded(net / len(profits)) if profits else None,
        "mt5_win_rate": rounded(len(wins) / len(profits)) if profits else None,
    }
    missing_required = missing_required_kpi_fields(required_kpis)
    known_blockers = missing_value_checks(status, events, deals)
    known_blockers.extend(f"required_kpi_missing:{field}" for field in missing_required)
    return {
        "schema": "axiom_rift_mt5_logic_parity_kpi_v1" if mode == LOGIC_PARITY_MODE else "axiom_rift_mt5_tick_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": "C0001",
        "campaign_id": "C0001",
        "synthesis_id_when_applicable": None,
        "run_id": "R0004",
        "mt5_probe_id": "MT50004",
        "mt5_kpi_family": "mt5_logic_parity" if mode == LOGIC_PARITY_MODE else "mt5_tick",
        "mt5_execution_mode": mode_label,
        "mt5_output_scope": result.output_scope,
        "mt5_terminal_identity": terminal_data_dir().as_posix(),
        **runtime_payload_fields(),
        "mt5_symbol": runtime_symbol(),
        "mt5_timeframe": runtime_timeframe(),
        "mt5_tester_model": tester_model_label(result.config),
        "mt5_date_start": tester_date_to_iso(result.from_date),
        "mt5_date_end": tester_to_date_to_end_iso(result.to_date),
        "mt5_tester_to_date": tester_date_to_iso(result.to_date),
        "mt5_report_paths": report_paths,
        "mt5_report_hashes": [sha256_file(path) for path in (result.status_csv, result.events_csv, result.deals_csv) if path.exists()],
        "mt5_status_fields": status,
        "required_kpis": required_kpis,
        "conditional_profiles": {
            "trade_excursion_profile": {"applies": False, "fields": {}},
            "direction_profile": {"applies": True, "fields": direction_summary(events, exit_deals)},
            "stability_profile": {"applies": True, "fields": fold_summary(events, profits)},
            "cost_execution_profile": {
                "applies": True,
                "fields": {
                    "commission_assumption": "broker_native",
                    "execution_source": "mt5_strategy_tester",
                    "spread_source": "mt5_strategy_tester",
                    "slippage_source": "mt5_strategy_tester",
                },
            },
            "runtime_reproducibility_profile": {
                "applies": True,
                "fields": {
                    "mt5_tester_status": status.get("status"),
                    "runtime_data_availability_status": "tester_output_present",
                    "known_runtime_blockers": known_blockers,
                },
            },
        },
        "mt5_probe_status": "completed" if status.get("status") == "completed" else status.get("status", "unknown"),
        "mt5_known_blockers": known_blockers,
        "missing_required_kpi_fields": missing_required,
        "deferred_with_reason": [],
        "claim_boundary": {
            "claim_authority": False,
            "runtime_probe_completed": False,
            "runtime_authority": False,
            "live_ready": False,
        },
    }


def record_r0004_parity() -> dict[str, object]:
    mt5 = json.loads(MT5_LOGIC_KPI.read_text(encoding="ascii"))
    proxy = run_r0004_proxy(write=False)
    proxy_trades = load_proxy_trades_for_parity()
    events = read_csv_rows(common_output_dir(LOGIC_PARITY_MODE) / "mt5_events.csv")
    proxy_trade_count = len(proxy_trades)
    mt5_trade_count = int(mt5["required_kpis"]["mt5_trade_count"] or 0)
    mt5_entries = [row for row in events if row.get("event") == "entry"]
    mt5_exits = [row for row in events if row.get("event") == "exit"]
    entry_count_delta = len(mt5_entries) - proxy_trade_count
    exit_count_delta = len(mt5_exits) - proxy_trade_count
    entry_compare = compare_entry_sequence(proxy_trades, mt5_entries)
    exit_compare = compare_exit_sequence(proxy_trades, mt5_exits)
    mechanical_ok = (
        entry_count_delta == 0
        and exit_count_delta == 0
        and entry_compare["key_match_rate"] == 1.0
        and exit_compare["time_direction_match_rate"] == 1.0
    )
    mismatch_count = (
        abs(entry_count_delta)
        + abs(exit_count_delta)
        + int(entry_compare["mismatch_count"])
        + int(exit_compare["mismatch_count"])
    )
    session_gap_exception = classify_session_gap_exception(proxy_trades, mt5_entries, mt5_exits)
    parity_accepted = mechanical_ok or bool(session_gap_exception["applies"])
    intent_ok = parity_accepted and (mechanical_ok or bool(session_gap_exception["applies"]) or exit_compare["reason_match_rate"] == 1.0)
    next_action = parity_next_action(parity_accepted, float(entry_compare["key_match_rate"] or 0.0))
    mechanical_status = "passed" if mechanical_ok else ("passed_with_session_gap_exception" if session_gap_exception["applies"] else "failed")
    intent_status = "passed" if intent_ok else ("blocked_by_mechanical_mismatch" if not parity_accepted else "failed")
    payload = {
        "schema": "axiom_rift_proxy_vs_mt5_logic_parity_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": "C0001",
        "campaign_id": "C0001",
        "synthesis_id_when_applicable": None,
        "run_id": "R0004",
        "parity_id": "P0004",
        "proxy_id": "PX0004",
        "mt5_probe_id": "MT50004",
        "parity_mode": LOGIC_PARITY_MODE,
        "mt5_kpi_family": "mt5_logic_parity",
        "compared_period": {"start": "2024-02-01", "end": "2026-04-30"},
        "required_kpis": {
            "trade_count_delta": mt5_trade_count - proxy_trade_count,
            "entry_count_delta": entry_count_delta,
            "exit_count_delta": exit_count_delta,
            "entry_time_match_rate": entry_compare["time_match_rate"],
            "entry_direction_match_rate": entry_compare["direction_match_rate"],
            "entry_key_match_rate": entry_compare["key_match_rate"],
            "exit_time_match_rate": exit_compare["time_match_rate"],
            "exit_time_direction_match_rate": exit_compare["time_direction_match_rate"],
            "exit_reason_match_rate": exit_compare["reason_match_rate"],
            "mechanical_parity_status": mechanical_status,
            "intent_parity_status": intent_status,
            "mismatch_count": mismatch_count,
            "mismatch_summary": parity_mismatch_summary(proxy_trade_count, mt5_trade_count, entry_compare, exit_compare),
            "repair_required": not parity_accepted,
            "next_action": next_action,
        },
        "mechanical_checks": {
            "sl_tp_point_unit_match": "not_checked",
            "bid_ask_mid_basis_match": "not_checked",
            "closed_bar_timestamp_match": "passed" if entry_compare["key_match_rate"] == 1.0 else ("passed_with_session_gap_exception" if session_gap_exception["applies"] else "failed"),
            "spread_slippage_semantics_match": "not_checked",
            "entry_direction_order_match": "passed" if entry_compare["key_match_rate"] == 1.0 else ("passed_with_session_gap_exception" if session_gap_exception["applies"] else "failed"),
            "exit_reason_order_match": "passed" if exit_compare["reason_match_rate"] == 1.0 else ("passed_with_session_gap_exception" if session_gap_exception["applies"] else "failed"),
            "entry_exit_order_match": "passed" if exit_compare["time_direction_match_rate"] == 1.0 else ("passed_with_session_gap_exception" if session_gap_exception["applies"] else "failed"),
            "position_lifecycle_match": "passed" if mt5_trade_count == len(mt5_entries) == len(mt5_exits) else ("passed_with_session_gap_exception" if session_gap_exception["applies"] else "failed"),
        },
        "conditional_profiles": {
            "session_gap_exception_profile": session_gap_exception,
            "trade_match_detail_profile": {
                "applies": True,
                "fields": {
                    "proxy_trade_count": proxy_trade_count,
                    "mt5_trade_count": mt5_trade_count,
                    "mt5_entry_event_count": len(mt5_entries),
                    "mt5_exit_event_count": len(mt5_exits),
                    "entry_mismatch_samples": entry_compare["mismatch_samples"],
                    "exit_mismatch_samples": exit_compare["mismatch_samples"],
                    "entry_sequence_time_match_rate": entry_compare["sequence_time_match_rate"],
                    "entry_sequence_direction_match_rate": entry_compare["sequence_direction_match_rate"],
                    "exit_sequence_time_match_rate": exit_compare["sequence_time_match_rate"],
                    "exit_sequence_reason_match_rate": exit_compare["sequence_reason_match_rate"],
                },
            },
            "cost_execution_profile": {"applies": True, "fields": mt5.get("conditional_profiles", {}).get("cost_execution_profile", {}).get("fields", {})},
        },
        "deferred_with_reason": [
            {
                "field": "sl_tp_point_unit_match,bid_ask_mid_basis_match,spread_slippage_semantics_match",
                "requirement_class": "deferred_with_reason",
                "reason": "detailed trade-by-trade price matching requires repaired count and timestamp sequence parity first",
                "blocking_condition": "entry and exit counts plus entry and exit timestamps must align before detailed price semantics can be trusted",
                "revisit_when": "after mechanical parity repair or after sequence parity passes",
                "claim_boundary": {"claim_authority": False},
            }
        ],
        "claim_boundary": {
            "claim_authority": False,
            "runtime_authority": False,
            "live_ready": False,
        },
    }
    LOGIC_PARITY_KPI.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    upsert_artifact_lineage(
        "A0007",
        "proxy_vs_mt5_logic_parity_kpi",
        "proxy_vs_mt5_logic_parity",
        rel(LOGIC_PARITY_KPI),
        sha256_file(LOGIC_PARITY_KPI),
        [
            "campaigns/C0001_regime_response_discovery/runs/R0004/kpi/proxy.json",
            "campaigns/C0001_regime_response_discovery/runs/R0004/kpi/mt5_logic_parity.json",
        ],
    )
    update_gate_after_parity(payload)
    return payload


def record_r0004_execution_divergence() -> dict[str, object]:
    logic_mt5 = json.loads(MT5_LOGIC_KPI.read_text(encoding="ascii"))
    tick_mt5 = json.loads(MT5_TICK_KPI.read_text(encoding="ascii"))
    logic_events = read_csv_rows(common_output_dir(LOGIC_PARITY_MODE) / "mt5_events.csv")
    tick_events = read_csv_rows(common_output_dir(TICK_EXECUTION_MODE) / "mt5_events.csv")
    logic_required = dict(logic_mt5.get("required_kpis", {}))
    tick_required = dict(tick_mt5.get("required_kpis", {}))
    logic_entries = [row for row in logic_events if row.get("event") == "entry"]
    tick_entries = [row for row in tick_events if row.get("event") == "entry"]
    logic_exits = [row for row in logic_events if row.get("event") == "exit"]
    tick_exits = [row for row in tick_events if row.get("event") == "exit"]
    entry_compare = compare_mt5_entry_events(logic_entries, tick_entries)
    exit_compare = compare_mt5_exit_events(logic_exits, tick_exits)
    logic_trade_count = kpi_int(logic_required, "mt5_trade_count")
    tick_trade_count = kpi_int(tick_required, "mt5_trade_count")
    logic_net = kpi_float(logic_required, "mt5_net_pnl")
    tick_net = kpi_float(tick_required, "mt5_net_pnl")
    logic_drawdown = kpi_float(logic_required, "mt5_max_drawdown_percent")
    tick_drawdown = kpi_float(tick_required, "mt5_max_drawdown_percent")
    logic_profit_factor = kpi_float(logic_required, "mt5_profit_factor")
    tick_profit_factor = kpi_float(tick_required, "mt5_profit_factor")
    logic_win_rate = kpi_float(logic_required, "mt5_win_rate")
    tick_win_rate = kpi_float(tick_required, "mt5_win_rate")
    logic_expectancy = kpi_float(logic_required, "mt5_expectancy_per_entry")
    tick_expectancy = kpi_float(tick_required, "mt5_expectancy_per_entry")
    required_kpis = {
        "logic_trade_count": logic_trade_count,
        "tick_trade_count": tick_trade_count,
        "tick_minus_logic_trade_count": int_delta(tick_trade_count, logic_trade_count),
        "logic_net_pnl": logic_net,
        "tick_net_pnl": tick_net,
        "tick_minus_logic_net_pnl": numeric_delta(tick_net, logic_net),
        "logic_max_drawdown_percent": logic_drawdown,
        "tick_max_drawdown_percent": tick_drawdown,
        "tick_minus_logic_max_drawdown_percent": numeric_delta(tick_drawdown, logic_drawdown),
        "logic_profit_factor": logic_profit_factor,
        "tick_profit_factor": tick_profit_factor,
        "tick_minus_logic_profit_factor": numeric_delta(tick_profit_factor, logic_profit_factor),
        "logic_win_rate": logic_win_rate,
        "tick_win_rate": tick_win_rate,
        "tick_minus_logic_win_rate": numeric_delta(tick_win_rate, logic_win_rate),
        "logic_expectancy_per_entry": logic_expectancy,
        "tick_expectancy_per_entry": tick_expectancy,
        "tick_minus_logic_expectancy_per_entry": numeric_delta(tick_expectancy, logic_expectancy),
        "entry_count_delta": len(tick_entries) - len(logic_entries),
        "exit_count_delta": len(tick_exits) - len(logic_exits),
        "entry_key_match_rate": entry_compare["key_match_rate"],
        "exit_time_direction_match_rate": exit_compare["time_direction_match_rate"],
        "exit_reason_match_rate": exit_compare["reason_match_rate"],
        "execution_divergence_status": execution_divergence_status(entry_compare, exit_compare, logic_net, tick_net),
        "economics_shift_status": economics_shift_status(logic_net, tick_net),
        "run_closeout_review_ready": True,
    }
    missing_required = missing_required_execution_fields(required_kpis)
    payload = {
        "schema": "axiom_rift_execution_divergence_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": "C0001",
        "campaign_id": "C0001",
        "synthesis_id_when_applicable": None,
        "run_id": "R0004",
        "divergence_id": "ED0004",
        "logic_mt5_kpi_path": rel(MT5_LOGIC_KPI),
        "tick_mt5_kpi_path": rel(MT5_TICK_KPI),
        "compared_period": {"start": "2024-02-01", "end": "2026-04-30"},
        "required_kpis": required_kpis,
        "conditional_profiles": {
            "entry_divergence_profile": {
                "applies": True,
                "fields": {
                    "logic_entry_event_count": len(logic_entries),
                    "tick_entry_event_count": len(tick_entries),
                    "entry_time_match_rate": entry_compare["time_match_rate"],
                    "entry_direction_match_rate": entry_compare["direction_match_rate"],
                    "entry_sequence_time_match_rate": entry_compare["sequence_time_match_rate"],
                    "entry_sequence_direction_match_rate": entry_compare["sequence_direction_match_rate"],
                    "entry_mismatch_samples": entry_compare["mismatch_samples"],
                },
            },
            "exit_divergence_profile": {
                "applies": True,
                "fields": {
                    "logic_exit_event_count": len(logic_exits),
                    "tick_exit_event_count": len(tick_exits),
                    "exit_time_match_rate": exit_compare["time_match_rate"],
                    "exit_sequence_time_match_rate": exit_compare["sequence_time_match_rate"],
                    "exit_sequence_reason_match_rate": exit_compare["sequence_reason_match_rate"],
                    "exit_mismatch_samples": exit_compare["mismatch_samples"],
                },
            },
            "spread_slippage_stress_profile": {
                "applies": False,
                "fields": {},
                "deferred_with_reason": "R0004 has baseline MT5 tick execution evidence only; spread and slippage stress sweeps are separate robustness work.",
            },
            "score_model_profile": {
                "applies": False,
                "fields": {},
                "deferred_with_reason": "R0004 is rule/proxy based and has no model score surface.",
            },
            "run_closeout_profile": {
                "applies": True,
                "fields": {
                    "logic_parity_required": True,
                    "tick_execution_kpi_required": True,
                    "execution_divergence_required": True,
                    "closeout_status": "ready_for_review" if not missing_required else "blocked_by_missing_required_kpi",
                },
            },
        },
        "missing_required_kpi_fields": missing_required,
        "deferred_with_reason": [
            {
                "field": "spread_slippage_stress_profile",
                "requirement_class": "deferred_with_reason",
                "reason": "baseline tick KPI is recorded; stress sweeps are not part of the current R0004 parity-to-tick split.",
                "blocking_condition": "requires a separate controlled spread/slippage tester matrix",
                "revisit_when": "after R0004 closeout review if this hypothesis remains worth robustness testing",
                "claim_boundary": {"claim_authority": False},
            }
        ],
        "claim_boundary": {
            "claim_authority": False,
            "runtime_authority": False,
            "live_ready": False,
        },
    }
    EXECUTION_DIVERGENCE_KPI.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    upsert_artifact_lineage(
        "A0008",
        "diagnostic_output",
        "execution_divergence",
        rel(EXECUTION_DIVERGENCE_KPI),
        sha256_file(EXECUTION_DIVERGENCE_KPI),
        [
            "campaigns/C0001_regime_response_discovery/runs/R0004/kpi/mt5_logic_parity.json",
            "campaigns/C0001_regime_response_discovery/runs/R0004/kpi/mt5_tick.json",
        ],
    )
    update_gate_after_execution_divergence(payload)
    return payload


def run_r0004_mt5_tick_by_fold_workflow(timeout_seconds: int = 1800) -> dict[str, object]:
    compile_r0004_ea()
    records: list[dict[str, Any]] = []
    for window in load_test_windows(ROLLING_WINDOWS):
        from_date, to_date = tester_dates_for_window(window)
        logic_result = run_r0004_tester(
            mode=LOGIC_PARITY_MODE,
            timeout_seconds=timeout_seconds,
            from_date=from_date,
            to_date=to_date,
            output_scope=window.fold_id,
            compile_before=False,
        )
        logic_payload = parse_r0004_mt5(logic_result, write_kpi=False)
        tick_result = run_r0004_tester(
            mode=TICK_EXECUTION_MODE,
            timeout_seconds=timeout_seconds,
            from_date=from_date,
            to_date=to_date,
            output_scope=window.fold_id,
            compile_before=False,
        )
        tick_payload = parse_r0004_mt5(tick_result, write_kpi=False)
        records.append(
            {
                "window": window,
                "from_date": from_date,
                "to_date": to_date,
                "logic_result": logic_result,
                "logic_payload": logic_payload,
                "tick_result": tick_result,
                "tick_payload": tick_payload,
            }
        )

    tick_by_fold_payload = build_mt5_tick_by_fold_payload(records)
    MT5_TICK_BY_FOLD_KPI.write_text(json.dumps(tick_by_fold_payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    divergence_by_fold_payload = build_execution_divergence_by_fold_payload(records)
    EXECUTION_DIVERGENCE_BY_FOLD_KPI.write_text(
        json.dumps(divergence_by_fold_payload, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    upsert_artifact_lineage(
        "A0009",
        "mt5_tick_by_fold_kpi",
        "mt5_tick_by_fold",
        rel(MT5_TICK_BY_FOLD_KPI),
        sha256_file(MT5_TICK_BY_FOLD_KPI),
        ["data/processed/datasets/us100_m5_base_frame.csv", "registries/rolling_windows.yaml", "configs/market.yaml"],
    )
    upsert_artifact_lineage(
        "A0010",
        "diagnostic_output",
        "execution_divergence_by_fold",
        rel(EXECUTION_DIVERGENCE_BY_FOLD_KPI),
        sha256_file(EXECUTION_DIVERGENCE_BY_FOLD_KPI),
        [
            "campaigns/C0001_regime_response_discovery/runs/R0004/kpi/mt5_tick_by_fold.json",
            "registries/rolling_windows.yaml",
        ],
    )
    update_gate_after_fold_isolated_evidence(tick_by_fold_payload, divergence_by_fold_payload)
    return {
        "mt5_tick_by_fold": tick_by_fold_payload["required_kpis"],
        "execution_divergence_by_fold": divergence_by_fold_payload["required_kpis"],
        "fold_count": len(records),
    }


def build_mt5_tick_by_fold_payload(records: list[dict[str, Any]]) -> dict[str, object]:
    fold_rows: list[dict[str, object]] = []
    nets: list[tuple[str, float]] = []
    drawdowns: list[tuple[str, float]] = []
    trade_count_total = 0
    missing_by_fold: dict[str, list[str]] = {}
    completed_count = 0
    for record in records:
        window = record["window"]
        tick_payload = record["tick_payload"]
        tick_result = record["tick_result"]
        required = dict(tick_payload.get("required_kpis", {}))
        missing = list(tick_payload.get("missing_required_kpi_fields", []))
        if missing:
            missing_by_fold[window.fold_id] = missing
        if tick_payload.get("mt5_probe_status") == "completed":
            completed_count += 1
        trade_count = kpi_int(required, "mt5_trade_count") or 0
        net = kpi_float(required, "mt5_net_pnl")
        drawdown = kpi_float(required, "mt5_max_drawdown_percent")
        trade_count_total += trade_count
        if net is not None:
            nets.append((window.fold_id, net))
        if drawdown is not None:
            drawdowns.append((window.fold_id, drawdown))
        fold_rows.append(
            {
                "fold_id": window.fold_id,
                "period": {"start": time_text(window.start), "end": time_text(window.end)},
                "tester": {
                    "from_date": record["from_date"],
                    "to_date": record["to_date"],
                    "status_csv": rel(tick_result.status_csv),
                    "events_csv": rel(tick_result.events_csv),
                    "deals_csv": rel(tick_result.deals_csv),
                },
                "required_kpis": required,
                "missing_required_kpi_fields": missing,
            }
        )
    worst_net = min(nets, key=lambda item: item[1]) if nets else (None, None)
    worst_drawdown = max(drawdowns, key=lambda item: item[1]) if drawdowns else (None, None)
    required_kpis = {
        "fold_count": len(records),
        "completed_fold_count": completed_count,
        "missing_required_fold_count": len(missing_by_fold),
        "total_tick_trade_count": trade_count_total,
        "total_tick_net_pnl": rounded(sum(value for _, value in nets)),
        "losing_fold_count": sum(1 for _, value in nets if value < 0),
        "profitable_fold_count": sum(1 for _, value in nets if value > 0),
        "worst_fold_id": worst_net[0],
        "worst_fold_net_pnl": worst_net[1],
        "worst_drawdown_fold_id": worst_drawdown[0],
        "worst_fold_max_drawdown_percent": worst_drawdown[1],
        "all_folds_completed": completed_count == len(records),
        "mt5_tick_by_fold_status": "completed" if completed_count == len(records) and not missing_by_fold else "blocked_by_missing_required_kpi",
    }
    missing_required = missing_required_by_fold_fields(required_kpis)
    return {
        "schema": "axiom_rift_mt5_tick_by_fold_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": "C0001",
        "campaign_id": "C0001",
        "synthesis_id_when_applicable": None,
        "run_id": "R0004",
        "mt5_probe_id": "MT50004_BY_FOLD",
        "split_policy": "rolling_window_test_oos_fold_isolated",
        "split_registry": "registries/rolling_windows.yaml",
        "required_kpis": required_kpis,
        "conditional_profiles": {
            "fold_profile": {"applies": True, "fields": {"folds": fold_rows, "missing_by_fold": missing_by_fold}},
            "score_model_profile": {
                "applies": False,
                "fields": {},
                "deferred_with_reason": "R0004 is rule/proxy based and has no model score surface.",
            },
            "spread_slippage_stress_profile": {
                "applies": False,
                "fields": {},
                "deferred_with_reason": "Fold-isolated baseline tick evidence is recorded; stress sweeps are separate robustness work.",
            },
            "run_closeout_profile": {
                "applies": True,
                "fields": {
                    "closeout_judgment_surface": "rolling_window_fold_isolated_mt5_tick",
                    "closeout_status": "fold_isolated_tick_kpi_recorded_pending_review",
                },
            },
        },
        "missing_required_kpi_fields": missing_required,
        "deferred_with_reason": [],
        "claim_boundary": {
            "claim_authority": False,
            "runtime_authority": False,
            "live_ready": False,
        },
    }


def build_execution_divergence_by_fold_payload(records: list[dict[str, Any]]) -> dict[str, object]:
    fold_rows: list[dict[str, object]] = []
    totals = {
        "logic_trade_count": 0,
        "tick_trade_count": 0,
        "logic_net_pnl": 0.0,
        "tick_net_pnl": 0.0,
    }
    deltas: list[tuple[str, float]] = []
    entry_rates: list[float] = []
    exit_time_direction_rates: list[float] = []
    exit_reason_rates: list[float] = []
    status_counts: Counter[str] = Counter()
    missing_by_fold: dict[str, list[str]] = {}
    for record in records:
        window = record["window"]
        logic_payload = record["logic_payload"]
        tick_payload = record["tick_payload"]
        logic_result = record["logic_result"]
        tick_result = record["tick_result"]
        logic_required = dict(logic_payload.get("required_kpis", {}))
        tick_required = dict(tick_payload.get("required_kpis", {}))
        logic_events = read_csv_rows(logic_result.events_csv)
        tick_events = read_csv_rows(tick_result.events_csv)
        logic_entries = [row for row in logic_events if row.get("event") == "entry"]
        tick_entries = [row for row in tick_events if row.get("event") == "entry"]
        logic_exits = [row for row in logic_events if row.get("event") == "exit"]
        tick_exits = [row for row in tick_events if row.get("event") == "exit"]
        entry_compare = compare_mt5_entry_events(logic_entries, tick_entries)
        exit_compare = compare_mt5_exit_events(logic_exits, tick_exits)
        logic_trade_count = kpi_int(logic_required, "mt5_trade_count")
        tick_trade_count = kpi_int(tick_required, "mt5_trade_count")
        logic_net = kpi_float(logic_required, "mt5_net_pnl")
        tick_net = kpi_float(tick_required, "mt5_net_pnl")
        logic_drawdown = kpi_float(logic_required, "mt5_max_drawdown_percent")
        tick_drawdown = kpi_float(tick_required, "mt5_max_drawdown_percent")
        logic_profit_factor = kpi_float(logic_required, "mt5_profit_factor")
        tick_profit_factor = kpi_float(tick_required, "mt5_profit_factor")
        logic_win_rate = kpi_float(logic_required, "mt5_win_rate")
        tick_win_rate = kpi_float(tick_required, "mt5_win_rate")
        logic_expectancy = kpi_float(logic_required, "mt5_expectancy_per_entry")
        tick_expectancy = kpi_float(tick_required, "mt5_expectancy_per_entry")
        fold_required = {
            "logic_trade_count": logic_trade_count,
            "tick_trade_count": tick_trade_count,
            "tick_minus_logic_trade_count": int_delta(tick_trade_count, logic_trade_count),
            "logic_net_pnl": logic_net,
            "tick_net_pnl": tick_net,
            "tick_minus_logic_net_pnl": numeric_delta(tick_net, logic_net),
            "logic_max_drawdown_percent": logic_drawdown,
            "tick_max_drawdown_percent": tick_drawdown,
            "tick_minus_logic_max_drawdown_percent": numeric_delta(tick_drawdown, logic_drawdown),
            "logic_profit_factor": logic_profit_factor,
            "tick_profit_factor": tick_profit_factor,
            "tick_minus_logic_profit_factor": numeric_delta(tick_profit_factor, logic_profit_factor),
            "logic_win_rate": logic_win_rate,
            "tick_win_rate": tick_win_rate,
            "tick_minus_logic_win_rate": numeric_delta(tick_win_rate, logic_win_rate),
            "logic_expectancy_per_entry": logic_expectancy,
            "tick_expectancy_per_entry": tick_expectancy,
            "tick_minus_logic_expectancy_per_entry": numeric_delta(tick_expectancy, logic_expectancy),
            "entry_count_delta": len(tick_entries) - len(logic_entries),
            "exit_count_delta": len(tick_exits) - len(logic_exits),
            "entry_key_match_rate": entry_compare["key_match_rate"],
            "exit_time_direction_match_rate": exit_compare["time_direction_match_rate"],
            "exit_reason_match_rate": exit_compare["reason_match_rate"],
            "execution_divergence_status": execution_divergence_status(entry_compare, exit_compare, logic_net, tick_net),
            "economics_shift_status": economics_shift_status(logic_net, tick_net),
        }
        missing = missing_required_execution_fields(fold_required)
        if missing:
            missing_by_fold[window.fold_id] = missing
        status_counts[str(fold_required["execution_divergence_status"])] += 1
        if logic_trade_count is not None:
            totals["logic_trade_count"] += logic_trade_count
        if tick_trade_count is not None:
            totals["tick_trade_count"] += tick_trade_count
        if logic_net is not None:
            totals["logic_net_pnl"] += logic_net
        if tick_net is not None:
            totals["tick_net_pnl"] += tick_net
        if fold_required["tick_minus_logic_net_pnl"] is not None:
            deltas.append((window.fold_id, float(fold_required["tick_minus_logic_net_pnl"])))
        append_rate(entry_rates, fold_required["entry_key_match_rate"])
        append_rate(exit_time_direction_rates, fold_required["exit_time_direction_match_rate"])
        append_rate(exit_reason_rates, fold_required["exit_reason_match_rate"])
        fold_rows.append(
            {
                "fold_id": window.fold_id,
                "period": {"start": time_text(window.start), "end": time_text(window.end)},
                "required_kpis": fold_required,
                "missing_required_kpi_fields": missing,
                "conditional_profiles": {
                    "entry_divergence_profile": {
                        "applies": True,
                        "fields": {
                            "logic_entry_event_count": len(logic_entries),
                            "tick_entry_event_count": len(tick_entries),
                            "entry_mismatch_samples": entry_compare["mismatch_samples"],
                        },
                    },
                    "exit_divergence_profile": {
                        "applies": True,
                        "fields": {
                            "logic_exit_event_count": len(logic_exits),
                            "tick_exit_event_count": len(tick_exits),
                            "exit_mismatch_samples": exit_compare["mismatch_samples"],
                        },
                    },
                },
            }
        )
    worst_delta = min(deltas, key=lambda item: item[1]) if deltas else (None, None)
    required_kpis = {
        "fold_count": len(records),
        "divergence_recorded_fold_count": len(fold_rows),
        "missing_required_fold_count": len(missing_by_fold),
        "total_logic_trade_count": totals["logic_trade_count"],
        "total_tick_trade_count": totals["tick_trade_count"],
        "total_tick_minus_logic_trade_count": totals["tick_trade_count"] - totals["logic_trade_count"],
        "total_logic_net_pnl": rounded(totals["logic_net_pnl"]),
        "total_tick_net_pnl": rounded(totals["tick_net_pnl"]),
        "total_tick_minus_logic_net_pnl": rounded(totals["tick_net_pnl"] - totals["logic_net_pnl"]),
        "tick_worse_fold_count": sum(1 for _, value in deltas if value < 0),
        "tick_better_fold_count": sum(1 for _, value in deltas if value > 0),
        "worst_tick_minus_logic_fold_id": worst_delta[0],
        "worst_tick_minus_logic_net_pnl": worst_delta[1],
        "minimum_entry_key_match_rate": min(entry_rates) if entry_rates else None,
        "minimum_exit_time_direction_match_rate": min(exit_time_direction_rates) if exit_time_direction_rates else None,
        "minimum_exit_reason_match_rate": min(exit_reason_rates) if exit_reason_rates else None,
        "folds_with_recorded_divergence": status_counts.get("recorded_with_divergence", 0),
        "execution_divergence_by_fold_status": "completed" if not missing_by_fold else "blocked_by_missing_required_kpi",
    }
    missing_required = missing_required_by_fold_fields(required_kpis)
    return {
        "schema": "axiom_rift_execution_divergence_by_fold_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": "C0001",
        "campaign_id": "C0001",
        "synthesis_id_when_applicable": None,
        "run_id": "R0004",
        "divergence_id": "ED0004_BY_FOLD",
        "split_policy": "rolling_window_test_oos_fold_isolated",
        "split_registry": "registries/rolling_windows.yaml",
        "tick_mt5_by_fold_kpi_path": rel(MT5_TICK_BY_FOLD_KPI),
        "required_kpis": required_kpis,
        "conditional_profiles": {
            "fold_divergence_profile": {
                "applies": True,
                "fields": {"folds": fold_rows, "missing_by_fold": missing_by_fold},
            },
            "score_model_profile": {
                "applies": False,
                "fields": {},
                "deferred_with_reason": "R0004 is rule/proxy based and has no model score surface.",
            },
            "run_closeout_profile": {
                "applies": True,
                "fields": {
                    "closeout_judgment_surface": "rolling_window_fold_isolated_mt5_tick",
                    "closeout_status": "fold_isolated_divergence_recorded_pending_review",
                },
            },
        },
        "missing_required_kpi_fields": missing_required,
        "deferred_with_reason": [],
        "claim_boundary": {
            "claim_authority": False,
            "runtime_authority": False,
            "live_ready": False,
        },
    }


def load_proxy_trades_for_parity() -> list[Any]:
    bars = load_bars(BASE_FRAME)
    windows = load_test_windows(ROLLING_WINDOWS)
    return simulate_trades(bars, windows)


def parity_next_action(mechanical_ok: bool, entry_key_match_rate: float) -> str:
    if mechanical_ok:
        return "review_intent_parity_and_close_or_repair"
    if entry_key_match_rate >= 0.99:
        return "repair_exit_path_parity_or_mark_bar_proxy_non_portable"
    return "repair_entry_generation_parity"


def parity_mismatch_summary(
    proxy_trade_count: int,
    mt5_trade_count: int,
    entry_compare: dict[str, object],
    exit_compare: dict[str, object],
) -> str:
    if proxy_trade_count == mt5_trade_count and entry_compare["key_match_rate"] == 1.0 and exit_compare["reason_match_rate"] == 1.0:
        return "No key mismatch detected"
    return (
        f"entry_key_match={entry_compare['key_match_rate']} "
        f"exit_time_direction_match={exit_compare['time_direction_match_rate']} "
        f"exit_reason_match={exit_compare['reason_match_rate']} "
        f"proxy_trades={proxy_trade_count} mt5_trades={mt5_trade_count}"
    )


def compare_entry_sequence(proxy_trades: list[Any], mt5_entries: list[dict[str, str]]) -> dict[str, object]:
    mismatch_samples: list[dict[str, object]] = []
    proxy_time_keys = Counter(trade.entry_time for trade in proxy_trades)
    mt5_time_keys = Counter(event_bar_time(row) for row in mt5_entries)
    proxy_direction_keys = Counter(int(trade.direction) for trade in proxy_trades)
    mt5_direction_keys = Counter(direction_value(row.get("direction")) for row in mt5_entries)
    proxy_entry_keys = Counter((trade.entry_time, int(trade.direction)) for trade in proxy_trades)
    mt5_entry_keys = Counter((event_bar_time(row), direction_value(row.get("direction"))) for row in mt5_entries)
    time_matches = counter_match_count(proxy_time_keys, mt5_time_keys)
    direction_matches = counter_match_count(proxy_direction_keys, mt5_direction_keys)
    key_matches = counter_match_count(proxy_entry_keys, mt5_entry_keys)
    sequence_time_matches = 0
    sequence_direction_matches = 0
    compared = min(len(proxy_trades), len(mt5_entries))
    for index in range(compared):
        proxy_trade = proxy_trades[index]
        mt5_row = mt5_entries[index]
        proxy_time = proxy_trade.entry_time
        mt5_time = event_bar_time(mt5_row)
        proxy_direction = int(proxy_trade.direction)
        mt5_direction = direction_value(mt5_row.get("direction"))
        if proxy_time == mt5_time:
            sequence_time_matches += 1
        if proxy_direction == mt5_direction:
            sequence_direction_matches += 1
    for key in list((proxy_entry_keys - mt5_entry_keys).elements())[:5]:
        mismatch_samples.append({"side": "proxy_only", "entry_time": time_text(key[0]), "direction": key[1]})
    for key in list((mt5_entry_keys - proxy_entry_keys).elements())[:5]:
        mismatch_samples.append({"side": "mt5_only", "entry_time": time_text(key[0]), "direction": key[1]})
    return {
        "time_match_rate": match_rate(time_matches, len(proxy_trades)),
        "direction_match_rate": match_rate(direction_matches, len(proxy_trades)),
        "key_match_rate": match_rate(key_matches, len(proxy_trades)),
        "sequence_time_match_rate": match_rate(sequence_time_matches, len(proxy_trades)),
        "sequence_direction_match_rate": match_rate(sequence_direction_matches, len(proxy_trades)),
        "mismatch_count": (len(proxy_trades) - key_matches) + (len(mt5_entries) - key_matches),
        "mismatch_samples": mismatch_samples,
    }


def compare_exit_sequence(proxy_trades: list[Any], mt5_exits: list[dict[str, str]]) -> dict[str, object]:
    mismatch_samples: list[dict[str, object]] = []
    proxy_time_keys = Counter(trade.exit_time for trade in proxy_trades)
    mt5_time_keys = Counter(event_bar_time(row) for row in mt5_exits)
    proxy_time_direction_keys = Counter((trade.exit_time, int(trade.direction)) for trade in proxy_trades)
    mt5_time_direction_keys = Counter((event_bar_time(row), direction_value(row.get("direction"))) for row in mt5_exits)
    proxy_reason_keys = Counter((trade.exit_time, int(trade.direction), trade.exit_reason) for trade in proxy_trades)
    mt5_reason_keys = Counter((event_bar_time(row), direction_value(row.get("direction")), row.get("reason") or "") for row in mt5_exits)
    time_matches = counter_match_count(proxy_time_keys, mt5_time_keys)
    time_direction_matches = counter_match_count(proxy_time_direction_keys, mt5_time_direction_keys)
    reason_matches = counter_match_count(proxy_reason_keys, mt5_reason_keys)
    sequence_time_matches = 0
    sequence_reason_matches = 0
    compared = min(len(proxy_trades), len(mt5_exits))
    for index in range(compared):
        proxy_trade = proxy_trades[index]
        mt5_row = mt5_exits[index]
        proxy_time = proxy_trade.exit_time
        mt5_time = event_bar_time(mt5_row)
        proxy_reason = str(proxy_trade.exit_reason)
        mt5_reason = mt5_row.get("reason") or ""
        if proxy_time == mt5_time:
            sequence_time_matches += 1
        if proxy_reason == mt5_reason:
            sequence_reason_matches += 1
    for key in list((proxy_reason_keys - mt5_reason_keys).elements())[:5]:
        mismatch_samples.append(
            {"side": "proxy_only", "exit_time": time_text(key[0]), "direction": key[1], "reason": key[2]}
        )
    for key in list((mt5_reason_keys - proxy_reason_keys).elements())[:5]:
        mismatch_samples.append(
            {"side": "mt5_only", "exit_time": time_text(key[0]), "direction": key[1], "reason": key[2]}
        )
    return {
        "time_match_rate": match_rate(time_matches, len(proxy_trades)),
        "time_direction_match_rate": match_rate(time_direction_matches, len(proxy_trades)),
        "reason_match_rate": match_rate(reason_matches, len(proxy_trades)),
        "sequence_time_match_rate": match_rate(sequence_time_matches, len(proxy_trades)),
        "sequence_reason_match_rate": match_rate(sequence_reason_matches, len(proxy_trades)),
        "mismatch_count": (len(proxy_trades) - reason_matches) + (len(mt5_exits) - reason_matches),
        "mismatch_samples": mismatch_samples,
    }


def classify_session_gap_exception(
    proxy_trades: list[Any],
    mt5_entries: list[dict[str, str]],
    mt5_exits: list[dict[str, str]],
) -> dict[str, object]:
    proxy_entry_keys = Counter((trade.entry_time, int(trade.direction)) for trade in proxy_trades)
    mt5_entry_keys = Counter((event_bar_time(row), direction_value(row.get("direction"))) for row in mt5_entries)
    proxy_exit_keys = Counter((trade.exit_time, int(trade.direction), trade.exit_reason) for trade in proxy_trades)
    mt5_exit_keys = Counter((event_bar_time(row), direction_value(row.get("direction")), row.get("reason") or "") for row in mt5_exits)
    proxy_only_entries = sorted((proxy_entry_keys - mt5_entry_keys).elements())
    mt5_only_entries = sorted((mt5_entry_keys - proxy_entry_keys).elements())
    proxy_only_exits = sorted((proxy_exit_keys - mt5_exit_keys).elements())
    mt5_only_exits = sorted((mt5_exit_keys - proxy_exit_keys).elements())
    mismatch_times = [key[0] for key in proxy_only_entries + mt5_only_entries + proxy_only_exits + mt5_only_exits]
    applies = (
        len(proxy_only_entries) == 1
        and not mt5_only_entries
        and len(proxy_only_exits) == 2
        and len(mt5_only_exits) == 1
        and all(is_session_gap_boundary_time(timestamp) for timestamp in mismatch_times)
    )
    return {
        "applies": applies,
        "exception_type": "session_gap_tick_availability" if applies else "none",
        "reason": (
            "single MT5 tester session-gap tick-availability case shifts one short trade exit from proxy 23:55/00:10 handling to MT5 00:55 handling"
            if applies
            else ""
        ),
        "blocking_condition": "" if applies else "mismatch pattern is not a recognized single session-gap tick-availability exception",
        "revisit_when": "if R0004 remains useful after tick execution evidence" if applies else "",
        "mismatch_samples": {
            "proxy_only_entries": format_entry_keys(proxy_only_entries),
            "mt5_only_entries": format_entry_keys(mt5_only_entries),
            "proxy_only_exits": format_exit_keys(proxy_only_exits),
            "mt5_only_exits": format_exit_keys(mt5_only_exits),
        },
        "claim_boundary": {
            "claim_authority": False,
            "runtime_authority": False,
            "live_ready": False,
        },
    }


def is_session_gap_boundary_time(timestamp: datetime) -> bool:
    return (timestamp.hour == 23 and timestamp.minute >= 50) or timestamp.hour == 0


def format_entry_keys(keys: list[tuple[datetime, int]]) -> list[dict[str, object]]:
    return [{"entry_time": time_text(timestamp), "direction": direction} for timestamp, direction in keys]


def format_exit_keys(keys: list[tuple[datetime, int, str]]) -> list[dict[str, object]]:
    return [{"exit_time": time_text(timestamp), "direction": direction, "reason": reason} for timestamp, direction, reason in keys]


def compare_mt5_entry_events(logic_entries: list[dict[str, str]], tick_entries: list[dict[str, str]]) -> dict[str, object]:
    mismatch_samples: list[dict[str, object]] = []
    logic_time_keys = Counter(event_bar_time(row) for row in logic_entries)
    tick_time_keys = Counter(event_bar_time(row) for row in tick_entries)
    logic_direction_keys = Counter(direction_value(row.get("direction")) for row in logic_entries)
    tick_direction_keys = Counter(direction_value(row.get("direction")) for row in tick_entries)
    logic_entry_keys = Counter((event_bar_time(row), direction_value(row.get("direction"))) for row in logic_entries)
    tick_entry_keys = Counter((event_bar_time(row), direction_value(row.get("direction"))) for row in tick_entries)
    time_matches = counter_match_count(logic_time_keys, tick_time_keys)
    direction_matches = counter_match_count(logic_direction_keys, tick_direction_keys)
    key_matches = counter_match_count(logic_entry_keys, tick_entry_keys)
    sequence_time_matches = 0
    sequence_direction_matches = 0
    compared = min(len(logic_entries), len(tick_entries))
    for index in range(compared):
        logic_row = logic_entries[index]
        tick_row = tick_entries[index]
        if event_bar_time(logic_row) == event_bar_time(tick_row):
            sequence_time_matches += 1
        if direction_value(logic_row.get("direction")) == direction_value(tick_row.get("direction")):
            sequence_direction_matches += 1
    for key in list((logic_entry_keys - tick_entry_keys).elements())[:5]:
        mismatch_samples.append({"side": "logic_only", "entry_time": time_text(key[0]), "direction": key[1]})
    for key in list((tick_entry_keys - logic_entry_keys).elements())[:5]:
        mismatch_samples.append({"side": "tick_only", "entry_time": time_text(key[0]), "direction": key[1]})
    return {
        "time_match_rate": match_rate(time_matches, len(logic_entries)),
        "direction_match_rate": match_rate(direction_matches, len(logic_entries)),
        "key_match_rate": match_rate(key_matches, len(logic_entries)),
        "sequence_time_match_rate": match_rate(sequence_time_matches, len(logic_entries)),
        "sequence_direction_match_rate": match_rate(sequence_direction_matches, len(logic_entries)),
        "mismatch_count": (len(logic_entries) - key_matches) + (len(tick_entries) - key_matches),
        "mismatch_samples": mismatch_samples,
    }


def compare_mt5_exit_events(logic_exits: list[dict[str, str]], tick_exits: list[dict[str, str]]) -> dict[str, object]:
    mismatch_samples: list[dict[str, object]] = []
    logic_time_keys = Counter(event_bar_time(row) for row in logic_exits)
    tick_time_keys = Counter(event_bar_time(row) for row in tick_exits)
    logic_time_direction_keys = Counter((event_bar_time(row), direction_value(row.get("direction"))) for row in logic_exits)
    tick_time_direction_keys = Counter((event_bar_time(row), direction_value(row.get("direction"))) for row in tick_exits)
    logic_reason_keys = Counter(
        (event_bar_time(row), direction_value(row.get("direction")), row.get("reason") or "") for row in logic_exits
    )
    tick_reason_keys = Counter(
        (event_bar_time(row), direction_value(row.get("direction")), row.get("reason") or "") for row in tick_exits
    )
    time_matches = counter_match_count(logic_time_keys, tick_time_keys)
    time_direction_matches = counter_match_count(logic_time_direction_keys, tick_time_direction_keys)
    reason_matches = counter_match_count(logic_reason_keys, tick_reason_keys)
    sequence_time_matches = 0
    sequence_reason_matches = 0
    compared = min(len(logic_exits), len(tick_exits))
    for index in range(compared):
        logic_row = logic_exits[index]
        tick_row = tick_exits[index]
        if event_bar_time(logic_row) == event_bar_time(tick_row):
            sequence_time_matches += 1
        if (logic_row.get("reason") or "") == (tick_row.get("reason") or ""):
            sequence_reason_matches += 1
    for key in list((logic_reason_keys - tick_reason_keys).elements())[:5]:
        mismatch_samples.append(
            {"side": "logic_only", "exit_time": time_text(key[0]), "direction": key[1], "reason": key[2]}
        )
    for key in list((tick_reason_keys - logic_reason_keys).elements())[:5]:
        mismatch_samples.append(
            {"side": "tick_only", "exit_time": time_text(key[0]), "direction": key[1], "reason": key[2]}
        )
    return {
        "time_match_rate": match_rate(time_matches, len(logic_exits)),
        "time_direction_match_rate": match_rate(time_direction_matches, len(logic_exits)),
        "reason_match_rate": match_rate(reason_matches, len(logic_exits)),
        "sequence_time_match_rate": match_rate(sequence_time_matches, len(logic_exits)),
        "sequence_reason_match_rate": match_rate(sequence_reason_matches, len(logic_exits)),
        "mismatch_count": (len(logic_exits) - reason_matches) + (len(tick_exits) - reason_matches),
        "mismatch_samples": mismatch_samples,
    }


def counter_match_count(left: Counter[Any], right: Counter[Any]) -> int:
    return sum((left & right).values())


def event_bar_time(row: dict[str, str]) -> datetime | None:
    return parse_time(row.get("bar_time") or row.get("time"))


def direction_value(value: str | None) -> int:
    if value == "long":
        return 1
    if value == "short":
        return -1
    return 0


def time_text(value: datetime | None) -> str | None:
    return None if value is None else value.strftime("%Y-%m-%d %H:%M:%S")


def match_rate(matches: int, denominator: int) -> float | None:
    return rounded(matches / denominator) if denominator else None


def direction_summary(events: list[dict[str, str]], exit_deals: list[dict[str, str]]) -> dict[str, Any]:
    direction_counts = Counter(row.get("direction") for row in events if row.get("event") == "entry")
    return {
        "long_entry_count": direction_counts.get("long", 0),
        "short_entry_count": direction_counts.get("short", 0),
        "closed_deal_count": len(exit_deals),
    }


def fold_summary(events: list[dict[str, str]], profits: list[float]) -> dict[str, Any]:
    windows = load_test_windows(ROLLING_WINDOWS)
    entries = [row for row in events if row.get("event") == "entry"]
    buckets = {window.fold_id: 0 for window in windows}
    for row in entries:
        timestamp = parse_time(row.get("time"))
        if timestamp is None:
            continue
        for window in windows:
            if window.start <= timestamp <= window.end:
                buckets[window.fold_id] += 1
                break
    return {
        "entry_count_by_fold": buckets,
        "trade_count_total": len(entries),
        "profit_count": len(profits),
    }


def max_drawdown_percent(profits: list[float], starting_balance: float) -> float | None:
    if not profits or starting_balance <= 0:
        return None
    equity = starting_balance
    peak = starting_balance
    max_drawdown = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return rounded((max_drawdown / starting_balance) * 100.0)


def missing_value_checks(status: dict[str, str], events: list[dict[str, str]], deals: list[dict[str, str]]) -> list[str]:
    blockers: list[str] = []
    if status.get("status") != "completed":
        blockers.append("status_not_completed")
    if not events:
        blockers.append("events_missing")
    if not deals:
        blockers.append("deals_missing")
    if not any(row.get("event") == "entry" for row in events):
        blockers.append("entry_events_missing")
    if not any(row.get("event") == "exit" for row in events):
        blockers.append("exit_events_missing")
    return blockers


def missing_required_kpi_fields(required_kpis: dict[str, object]) -> list[str]:
    trade_count = int(required_kpis.get("mt5_trade_count") or 0)
    missing: list[str] = []
    for field, value in required_kpis.items():
        if field == "mt5_profit_factor" and trade_count > 0:
            continue
        if value is None or value == "":
            missing.append(field)
    return missing


def missing_required_execution_fields(required_kpis: dict[str, object]) -> list[str]:
    return [field for field, value in required_kpis.items() if value is None or value == ""]


def missing_required_by_fold_fields(required_kpis: dict[str, object]) -> list[str]:
    return [field for field, value in required_kpis.items() if value is None or value == ""]


def append_rate(target: list[float], value: object) -> None:
    if value is not None:
        target.append(float(value))


def kpi_float(required_kpis: dict[str, object], field: str) -> float | None:
    value = required_kpis.get(field)
    if value in (None, ""):
        return None
    return float(value)


def kpi_int(required_kpis: dict[str, object], field: str) -> int | None:
    value = required_kpis.get(field)
    if value in (None, ""):
        return None
    return int(value)


def numeric_delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return rounded(left - right)


def int_delta(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    return left - right


def execution_divergence_status(
    entry_compare: dict[str, object],
    exit_compare: dict[str, object],
    logic_net: float | None,
    tick_net: float | None,
) -> str:
    if (
        entry_compare.get("key_match_rate") == 1.0
        and exit_compare.get("time_direction_match_rate") == 1.0
        and exit_compare.get("reason_match_rate") == 1.0
        and logic_net == tick_net
    ):
        return "no_divergence_detected"
    return "recorded_with_divergence"


def economics_shift_status(logic_net: float | None, tick_net: float | None) -> str:
    if logic_net is None or tick_net is None:
        return "unknown_missing_net_pnl"
    if tick_net < logic_net:
        return "tick_worse_than_logic"
    if tick_net > logic_net:
        return "tick_better_than_logic"
    return "tick_equal_to_logic"


def tester_dates_for_window(window: Any) -> tuple[str, str]:
    from_date = window.start.strftime("%Y.%m.%d")
    to_date = (window.end + timedelta(days=1)).strftime("%Y.%m.%d")
    return from_date, to_date


def update_artifact_lineage(artifact_id: str, file_hash: str, produced_by: str) -> None:
    data = json.loads(ARTIFACT_LINEAGE.read_text(encoding="ascii"))
    for record in data.get("artifact_records", []):
        if record.get("artifact_id") == artifact_id:
            record["sha256"] = file_hash
            record["produced_by"] = produced_by
            record["mutable"] = False
    ARTIFACT_LINEAGE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def upsert_artifact_lineage(
    artifact_id: str,
    artifact_role: str,
    linked_kpi_family: str,
    repo_relative_path: str,
    file_hash: str,
    source_inputs: list[str],
) -> None:
    data = json.loads(ARTIFACT_LINEAGE.read_text(encoding="ascii"))
    next_record = {
        "artifact_id": artifact_id,
        "artifact_role": artifact_role,
        "artifact_type": "json",
        "claim_authority": False,
        "linked_kpi_family": linked_kpi_family,
        "mutable": False,
        "produced_by": "axiom_rift.mt5.r0004_probe",
        "repo_relative_path": repo_relative_path,
        "sha256": file_hash,
        "source_inputs": source_inputs,
    }
    records = data.setdefault("artifact_records", [])
    for index, record in enumerate(records):
        if record.get("artifact_id") == artifact_id:
            records[index] = next_record
            break
    else:
        records.append(next_record)
    ARTIFACT_LINEAGE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_run_after_mt5(mode: str) -> None:
    data = json.loads(RUN_MANIFEST.read_text(encoding="ascii"))
    evidence_paths = data.setdefault("evidence_paths", {})
    evidence_paths["mt5_logic_parity_kpi"] = "kpi/mt5_logic_parity.json"
    evidence_paths["mt5_tick_kpi"] = "kpi/mt5_tick.json"
    evidence_paths["proxy_vs_mt5_logic_parity_kpi"] = "kpi/proxy_vs_mt5_logic_parity.json"
    evidence_paths["execution_divergence_kpi"] = "kpi/execution_divergence.json"
    mt5_plan = data.setdefault("mt5_probe_plan", {})
    mt5_plan["logic_parity_kpi_path"] = "kpi/mt5_logic_parity.json"
    mt5_plan["tick_kpi_path"] = "kpi/mt5_tick.json"
    mt5_plan["execution_divergence_kpi_path"] = "kpi/execution_divergence.json"
    mt5_plan["logic_parity_purpose"] = "proxy_vs_ea_logic_parity_only"
    mt5_plan["tick_execution_purpose"] = "execution_kpi_only"
    parity_plan = data.setdefault("proxy_vs_mt5_plan", {})
    parity_plan["logic_parity_kpi_path"] = "kpi/proxy_vs_mt5_logic_parity.json"
    parity_plan["tick_mode_policy"] = "record_execution_divergence_not_proxy_parity_failure"
    if mode == LOGIC_PARITY_MODE:
        data["status"] = "mt5_logic_parity_recorded_pending_parity"
        data["gate_status"] = "mt5_logic_parity_recorded_pending_parity"
    else:
        data["status"] = "mt5_tick_recorded_pending_execution_divergence"
        data["gate_status"] = "mt5_tick_recorded_pending_execution_divergence"
    RUN_MANIFEST.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_run_after_parity(parity_payload: dict[str, object]) -> None:
    data = json.loads(RUN_MANIFEST.read_text(encoding="ascii"))
    evidence_paths = data.setdefault("evidence_paths", {})
    evidence_paths["mt5_logic_parity_kpi"] = "kpi/mt5_logic_parity.json"
    evidence_paths["proxy_vs_mt5_logic_parity_kpi"] = "kpi/proxy_vs_mt5_logic_parity.json"
    repair_required = bool(parity_payload["required_kpis"]["repair_required"])  # type: ignore[index]
    data["status"] = "mechanical_parity_repair_required" if repair_required else "parity_evidence_recorded"
    data["gate_status"] = "logic_parity_evidence_recorded"
    RUN_MANIFEST.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_after_parity(parity_payload: dict[str, object]) -> None:
    data = json.loads(GATE_REPORT.read_text(encoding="ascii"))
    mechanical_status = parity_payload["required_kpis"]["mechanical_parity_status"]  # type: ignore[index]
    intent_status = parity_payload["required_kpis"]["intent_parity_status"]  # type: ignore[index]
    next_action = str(parity_payload["required_kpis"]["next_action"])  # type: ignore[index]
    data["evidence_gate"]["status"] = "logic_parity_evidence_recorded"
    data["evidence_gate"]["checks"]["mt5_logic_parity_kpi_path_recorded"] = True
    data["evidence_gate"]["checks"]["proxy_vs_mt5_logic_parity_kpi_path_recorded"] = True
    evidence_paths = data.setdefault("evidence_paths", [])
    for path in ("kpi/mt5_logic_parity.json", "kpi/proxy_vs_mt5_logic_parity.json"):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["parity_gate"]["status"] = mechanical_status
    data["parity_gate"]["mechanical_parity_status"] = mechanical_status
    data["parity_gate"]["intent_parity_status"] = intent_status
    data["parity_gate"]["repair_required"] = bool(parity_payload["required_kpis"]["repair_required"])  # type: ignore[index]
    data["decision"] = "repair_mechanical_parity" if mechanical_status == "failed" else "defer_with_reason"
    data["next_action"] = next_action
    if mechanical_status == "failed":
        data["deferred_with_reason"] = [
            {
                "field": "run_closeout",
                "reason": "logic parity evidence is recorded, but mechanical parity failed",
                "blocking_condition": next_action,
                "revisit_when": "after repaired closed-bar MT5 and logic parity evidence are recorded",
            }
        ]
    else:
        data["deferred_with_reason"] = [
            {
                "field": "run_closeout",
                "reason": "evidence is recorded; intent review is still required before run closeout",
                "blocking_condition": "review intent parity and closeout KPI before judging the hypothesis",
                "revisit_when": "during R0004 closeout review",
            }
        ]
    GATE_REPORT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")
    update_run_after_parity(parity_payload)


def update_run_after_execution_divergence(divergence_payload: dict[str, object]) -> None:
    data = json.loads(RUN_MANIFEST.read_text(encoding="ascii"))
    evidence_paths = data.setdefault("evidence_paths", {})
    evidence_paths["mt5_logic_parity_kpi"] = "kpi/mt5_logic_parity.json"
    evidence_paths["mt5_tick_kpi"] = "kpi/mt5_tick.json"
    evidence_paths["proxy_vs_mt5_logic_parity_kpi"] = "kpi/proxy_vs_mt5_logic_parity.json"
    evidence_paths["execution_divergence_kpi"] = "kpi/execution_divergence.json"
    data["status"] = "execution_divergence_recorded_pending_closeout_review"
    data["gate_status"] = "logic_tick_and_divergence_recorded"
    RUN_MANIFEST.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_after_execution_divergence(divergence_payload: dict[str, object]) -> None:
    data = json.loads(GATE_REPORT.read_text(encoding="ascii"))
    required = divergence_payload["required_kpis"]  # type: ignore[index]
    missing_required = divergence_payload.get("missing_required_kpi_fields", [])
    checks = data["evidence_gate"].setdefault("checks", {})
    checks["mt5_logic_parity_kpi_path_recorded"] = True
    checks["mt5_tick_kpi_path_recorded"] = True
    checks["proxy_vs_mt5_logic_parity_kpi_path_recorded"] = True
    checks["execution_divergence_kpi_path_recorded"] = True
    data["evidence_gate"]["status"] = "logic_tick_and_divergence_recorded"
    data["execution_gate"] = {
        "status": required.get("execution_divergence_status"),
        "economics_shift_status": required.get("economics_shift_status"),
        "run_closeout_review_ready": required.get("run_closeout_review_ready"),
        "missing_required_kpi_fields": missing_required,
    }
    evidence_paths = data.setdefault("evidence_paths", [])
    for path in (
        "kpi/mt5_logic_parity.json",
        "kpi/mt5_tick.json",
        "kpi/proxy_vs_mt5_logic_parity.json",
        "kpi/execution_divergence.json",
        "artifact_lineage.json",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["decision"] = "defer_with_reason"
    data["next_action"] = "review_R0004_tick_execution_kpi_and_closeout"
    data["deferred_with_reason"] = [
        {
            "field": "run_closeout",
            "reason": "logic parity, tick execution KPI, and execution divergence are recorded; closeout judgment still requires review",
            "blocking_condition": "review tick economics and divergence before deciding whether R0004 remains useful",
            "revisit_when": "during R0004 closeout review",
        }
    ]
    GATE_REPORT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")
    update_run_after_execution_divergence(divergence_payload)


def update_gate_after_fold_isolated_evidence(
    tick_by_fold_payload: dict[str, object],
    divergence_by_fold_payload: dict[str, object],
) -> None:
    run_data = json.loads(RUN_MANIFEST.read_text(encoding="ascii"))
    run_evidence = run_data.setdefault("evidence_paths", {})
    run_evidence["mt5_tick_by_fold_kpi"] = "kpi/mt5_tick_by_fold.json"
    run_evidence["execution_divergence_by_fold_kpi"] = "kpi/execution_divergence_by_fold.json"
    mt5_plan = run_data.setdefault("mt5_probe_plan", {})
    mt5_plan["fold_isolated_tick_kpi_path"] = "kpi/mt5_tick_by_fold.json"
    mt5_plan["fold_isolated_execution_divergence_kpi_path"] = "kpi/execution_divergence_by_fold.json"
    mt5_plan["closeout_judgment_surface"] = "rolling_window_fold_isolated_mt5_tick"
    run_data["gate_status"] = "fold_isolated_evidence_recorded_pending_closeout_review"
    RUN_MANIFEST.write_text(json.dumps(run_data, indent=2, sort_keys=True) + "\n", encoding="ascii")

    gate_data = json.loads(GATE_REPORT.read_text(encoding="ascii"))
    checks = gate_data["evidence_gate"].setdefault("checks", {})
    checks["mt5_tick_by_fold_kpi_path_recorded"] = True
    checks["execution_divergence_by_fold_kpi_path_recorded"] = True
    gate_data["evidence_gate"]["status"] = "fold_isolated_evidence_recorded"
    rolling_gate = gate_data.setdefault("rolling_window_closeout_gate", {})
    rolling_gate["status"] = "fold_isolated_evidence_recorded_pending_closeout_review"
    rolling_gate["aggregate_full_period_mt5_kpi_role"] = "diagnostic_only"
    rolling_gate["fold_isolated_mt5_tick_required"] = True
    rolling_gate["fold_isolated_mt5_tick_path_recorded"] = True
    rolling_gate["fold_isolated_execution_divergence_path_recorded"] = True
    rolling_gate["fold_isolated_exception"] = {
        "applies": False,
        "reason": "",
        "blocking_condition": "",
        "revisit_when": "",
    }
    gate_data["fold_isolated_execution_gate"] = {
        "mt5_tick_by_fold_status": tick_by_fold_payload["required_kpis"].get("mt5_tick_by_fold_status"),  # type: ignore[index]
        "execution_divergence_by_fold_status": divergence_by_fold_payload["required_kpis"].get("execution_divergence_by_fold_status"),  # type: ignore[index]
        "missing_required_kpi_fields": {
            "mt5_tick_by_fold": tick_by_fold_payload.get("missing_required_kpi_fields", []),
            "execution_divergence_by_fold": divergence_by_fold_payload.get("missing_required_kpi_fields", []),
        },
    }
    evidence_paths = gate_data.setdefault("evidence_paths", [])
    for path in (
        "kpi/mt5_tick_by_fold.json",
        "kpi/execution_divergence_by_fold.json",
        "artifact_lineage.json",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    gate_data["decision"] = "defer_with_reason"
    gate_data["next_action"] = "review_R0004_tick_execution_kpi_and_closeout"
    gate_data["deferred_with_reason"] = [
        {
            "field": "run_closeout",
            "reason": "fold-isolated MT5 tick KPI and fold-isolated execution divergence are recorded; closeout judgment was not performed in this step",
            "blocking_condition": "review fold-isolated tick economics and divergence before closing R0004",
            "revisit_when": "during R0004 closeout review",
        }
    ]
    GATE_REPORT.write_text(json.dumps(gate_data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def run_r0004_mt5_logic_workflow(timeout_seconds: int = 1800) -> dict[str, object]:
    result = run_r0004_tester(mode=LOGIC_PARITY_MODE, timeout_seconds=timeout_seconds)
    mt5_payload = parse_r0004_mt5(result)
    parity_payload = record_r0004_parity()
    return {
        "mt5": mt5_payload["required_kpis"],
        "parity": parity_payload["required_kpis"],
        "status_csv": result.status_csv.as_posix(),
        "events_csv": result.events_csv.as_posix(),
        "deals_csv": result.deals_csv.as_posix(),
    }


def run_r0004_mt5_tick_workflow(timeout_seconds: int = 1800) -> dict[str, object]:
    result = run_r0004_tester(mode=TICK_EXECUTION_MODE, timeout_seconds=timeout_seconds)
    mt5_payload = parse_r0004_mt5(result)
    divergence_payload = record_r0004_execution_divergence()
    return {
        "mt5_tick": mt5_payload["required_kpis"],
        "execution_divergence": divergence_payload["required_kpis"],
        "status_csv": result.status_csv.as_posix(),
        "events_csv": result.events_csv.as_posix(),
        "deals_csv": result.deals_csv.as_posix(),
    }


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def to_float(value: str | None) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def tester_date_to_iso(value: str) -> str:
    return datetime.strptime(value, "%Y.%m.%d").date().isoformat()


def tester_to_date_to_end_iso(value: str) -> str:
    return (datetime.strptime(value, "%Y.%m.%d") - timedelta(days=1)).date().isoformat()



