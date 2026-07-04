"""MT5 schedule-replay logic parity helpers for C0005 R0004."""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

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
from axiom_rift.mt5.shared import (
    LOGIC_PARITY_MODE,
    TICK_EXECUTION_MODE,
    VALID_MT5_MODES,
    bool_text,
    compare_mt5_entry_events,
    compare_mt5_exit_events,
    compare_entry_sequence,
    compare_exit_sequence,
    direction_summary,
    economics_shift_status,
    execution_divergence_status,
    int_delta,
    kpi_float,
    kpi_int,
    max_drawdown_percent,
    missing_required_execution_fields,
    missing_required_kpi_fields,
    missing_value_checks,
    normalize_mt5_mode,
    normalize_output_scope,
    numeric_delta,
    parity_mismatch_summary,
    read_compile_log,
    read_csv_rows,
    read_status_csv,
    rounded,
    tester_date_to_iso,
    tester_model_label,
    tester_to_date_to_end_iso,
    to_float,
    wait_for_status,
)
from axiom_rift.mt5.shared import (
    CompileResult,
    TesterResult,
    event_bar_time,
    missing_required_by_fold_fields,
    parse_time,
    tester_dates_for_window,
    time_text,
)
from axiom_rift.mt5.terminal_hygiene import cleanup_headless_terminal, prepare_headless_terminal
from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies.c0005_r0004_target_first_tail_hazard_analog_memory import (
    BASE_FRAME,
    ROLLING_WINDOWS,
    SplitWindow,
    Trade,
    load_bars,
    load_proxy_trades,
    load_windows,
)


EA_NAME = "AxiomC0002ScheduleReplay"
EA_SOURCE = PROJECT_ROOT / "src" / "axiom_rift" / "mt5" / "experts" / f"{EA_NAME}.mq5"
CAMPAIGN_ID = "C0005"
RUN_ID = "R0004"
CAMPAIGN_ROOT = PROJECT_ROOT / "campaigns" / "C0005_continuous_analog_memory_discovery"
RUN_DIR = CAMPAIGN_ROOT / "runs" / RUN_ID
CAMPAIGN = CAMPAIGN_ROOT / "campaign.yaml"
KPI_DIR = RUN_DIR / "kpi"
RUN_ARTIFACT_DIR = RUN_DIR / "artifacts"
MT5_LOGIC_KPI = KPI_DIR / "mt5_logic_parity.json"
MT5_TICK_KPI = KPI_DIR / "mt5_tick.json"
MT5_TICK_BY_FOLD_KPI = KPI_DIR / "mt5_tick_by_fold.json"
LOGIC_PARITY_KPI = KPI_DIR / "proxy_vs_mt5_logic_parity.json"
EXECUTION_DIVERGENCE_KPI = KPI_DIR / "execution_divergence.json"
EXECUTION_DIVERGENCE_BY_FOLD_KPI = KPI_DIR / "execution_divergence_by_fold.json"
RUN_MANIFEST = RUN_DIR / "run_manifest.json"
GATE_REPORT = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE = RUN_DIR / "artifact_lineage.json"
CLAIM_STATE = PROJECT_ROOT / "registries" / "claim_state.yaml"
SCHEDULE_ARTIFACT = RUN_ARTIFACT_DIR / "c0005_r0004_schedule.csv"
SCHEDULE_COMMON_REL = "AxiomRift\\C0005\\R0004\\schedule\\c0005_r0004_schedule.csv"
STARTING_BALANCE_USD = starting_balance_usd()
RESPONSE_MODE = "fold_local_target_first_tail_hazard_analog_memory_schedule_replay"
MAX_HOLD_BARS = 10
MAGIC = 500004
TESTER_FROM_DATE = "2024.02.01"
TESTER_TO_DATE = "2026.05.01"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compile_c0005_r0004_ea(metaeditor_exe: Path | None = None) -> CompileResult:
    metaeditor_exe = runtime_metaeditor_exe() if metaeditor_exe is None else metaeditor_exe
    if not metaeditor_exe.exists():
        raise FileNotFoundError(f"MetaEditor not found: {metaeditor_exe}")
    target_dir = terminal_data_dir() / "MQL5" / "Experts" / "AxiomRift"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / EA_SOURCE.name
    shutil.copy2(EA_SOURCE, target)
    log = PROJECT_ROOT / "artifacts" / "reports" / "C0005_R0004_mt5_compile.log"
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


def use_closed_bar_exit_for_mode(mode: str) -> bool:
    return normalize_mt5_mode(mode) == LOGIC_PARITY_MODE


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
        / CAMPAIGN_ID
        / RUN_ID
        / mode
    )
    if output_scope is not None:
        directory = directory / output_scope
    return directory


def schedule_common_path() -> Path:
    return (
        Path(os.environ["APPDATA"])
        / "MetaQuotes"
        / "Terminal"
        / "Common"
        / "Files"
        / Path(SCHEDULE_COMMON_REL.replace("\\", "/"))
    )


def mt5_kpi_path_for_mode(mode: str) -> Path:
    mode = normalize_mt5_mode(mode)
    return MT5_LOGIC_KPI if mode == LOGIC_PARITY_MODE else MT5_TICK_KPI


def scoped_name(mode: str, output_scope: str | None = None) -> str:
    mode = normalize_mt5_mode(mode)
    output_scope = normalize_output_scope(output_scope)
    return mode if output_scope is None else f"{mode}_{output_scope}"


def tester_config_path_for_mode(mode: str, output_scope: str | None = None) -> Path:
    return PROJECT_ROOT / "artifacts" / "reports" / "C0005_R0004_mt5_tester" / f"C0005_R0004_{scoped_name(mode, output_scope)}_tester.ini"


def tester_report_path_for_mode(mode: str, output_scope: str | None = None) -> Path:
    return PROJECT_ROOT / "artifacts" / "reports" / "C0005_R0004_mt5_tester" / f"C0005_R0004_mt5_{scoped_name(mode, output_scope)}_report.htm"


def tester_report_stem_for_mode(mode: str, output_scope: str | None = None) -> Path:
    return tester_report_path_for_mode(mode, output_scope).with_suffix("")


def clear_common_outputs(mode: str = LOGIC_PARITY_MODE, output_scope: str | None = None) -> None:
    directory = common_output_dir(mode, output_scope)
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("mt5_status.csv", "mt5_events.csv", "mt5_deals.csv"):
        path = directory / name
        if path.exists():
            path.unlink()


def write_schedule_files() -> tuple[Path, Path]:
    rows = schedule_rows(load_proxy_trades())
    RUN_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    write_schedule_csv(SCHEDULE_ARTIFACT, rows)
    common_path = schedule_common_path()
    common_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCHEDULE_ARTIFACT, common_path)
    return SCHEDULE_ARTIFACT, common_path


def schedule_rows(trades: list[Trade]) -> list[dict[str, object]]:
    bars = load_bars(BASE_FRAME)
    index_by_time = {bar.time: index for index, bar in enumerate(bars)}
    rows: list[dict[str, object]] = []
    for trade in trades:
        entry_index = index_by_time.get(trade.entry_time)
        signal_time = bars[entry_index - 1].time if entry_index is not None and entry_index > 0 else trade.entry_time - timedelta(minutes=5)
        rows.append(
            {
                "fold_id": trade.fold_id,
                "signal_time": mql_time(signal_time),
                "entry_time": mql_time(trade.entry_time),
                "exit_time": mql_time(trade.exit_time),
                "direction": "long" if trade.direction > 0 else "short",
                "score": rounded(trade.score),
                "entry_price": rounded(trade.entry_price),
                "exit_price": rounded(trade.exit_price),
                "stop_price": rounded(trade.stop_price),
                "target_price": rounded(trade.target_price),
                "bars_held": trade.bars_held,
                "exit_reason": trade.exit_reason,
            }
        )
    return rows


def write_schedule_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "fold_id",
        "signal_time",
        "entry_time",
        "exit_time",
        "direction",
        "score",
        "entry_price",
        "exit_price",
        "stop_price",
        "target_price",
        "bars_held",
        "exit_reason",
    ]
    with path.open("w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def mql_time(value: datetime) -> str:
    return value.strftime("%Y.%m.%d %H:%M:%S")


def load_test_windows() -> list[SplitWindow]:
    windows = load_windows(ROLLING_WINDOWS)
    return [splits["test_oos"] for fold_id, splits in sorted(windows.items()) if "test_oos" in splits and fold_id != "tail"]


def write_tester_config(
    mode: str = LOGIC_PARITY_MODE,
    from_date: str = TESTER_FROM_DATE,
    to_date: str = TESTER_TO_DATE,
    model: int | None = None,
    output_scope: str | None = None,
) -> Path:
    mode = normalize_mt5_mode(mode)
    output_scope = normalize_output_scope(output_scope)
    if mode not in VALID_MT5_MODES:
        raise ValueError(f"Unsupported MT5 mode: {mode}")
    if model is None:
        model = tester_model_for_mode(mode)
    use_closed_bar_exit = use_closed_bar_exit_for_mode(mode)
    config_dir = PROJECT_ROOT / "artifacts" / "reports" / "C0005_R0004_mt5_tester"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = tester_config_path_for_mode(mode, output_scope)
    report = tester_report_stem_for_mode(mode, output_scope)
    lines = [
        "[Tester]",
        "Expert=AxiomRift\\AxiomC0002ScheduleReplay",
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
        f"InpRunId={RUN_ID}",
        f"InpCampaignId={CAMPAIGN_ID}",
        f"InpOutputMode={mode}",
        f"InpOutputScope={output_scope or ''}",
        f"InpResponseMode={RESPONSE_MODE}",
        f"InpSchedulePath={SCHEDULE_COMMON_REL}",
        f"InpMagic={MAGIC}",
        lot_input_line(),
        f"InpMaxHoldBars={MAX_HOLD_BARS}",
        "InpUseCommonFiles=true",
        f"InpUseClosedBarExit={bool_text(use_closed_bar_exit)}",
        "",
    ]
    config.write_text("\n".join(lines), encoding="ascii")
    return config


def run_c0005_r0004_tester(
    mode: str = LOGIC_PARITY_MODE,
    timeout_seconds: int = 1800,
    from_date: str = TESTER_FROM_DATE,
    to_date: str = TESTER_TO_DATE,
    model: int | None = None,
    output_scope: str | None = None,
    compile_before: bool = True,
) -> TesterResult:
    mode = normalize_mt5_mode(mode)
    output_scope = normalize_output_scope(output_scope)
    if compile_before:
        compile_c0005_r0004_ea()
    write_schedule_files()
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


def parse_c0005_r0004_mt5(
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
            from_date=TESTER_FROM_DATE,
            to_date=TESTER_TO_DATE,
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
            "A-C0005-R0004-MT5-SCHEDULE",
            "mt5_schedule_csv",
            "mt5_logic_parity_input",
            rel(SCHEDULE_ARTIFACT),
            sha256_file(SCHEDULE_ARTIFACT),
            ["campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/kpi/proxy.json"],
        )
        upsert_artifact_lineage(
            "A-C0005-R0004-MT5-LOGIC-KPI",
            "mt5_logic_parity_kpi",
            "mt5_logic_parity",
            rel(MT5_LOGIC_KPI),
            sha256_file(MT5_LOGIC_KPI),
            [
                "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/artifacts/c0005_r0004_schedule.csv",
                "configs/market.yaml",
            ],
        )
    else:
        upsert_artifact_lineage(
            "A-C0005-R0004-MT5-TICK-KPI",
            "mt5_tick_kpi",
            "mt5_tick",
            rel(MT5_TICK_KPI),
            sha256_file(MT5_TICK_KPI),
            [
                "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/artifacts/c0005_r0004_schedule.csv",
                "configs/market.yaml",
            ],
        )
    update_run_after_mt5(mode)
    return payload


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
    if status.get("campaign_id") != CAMPAIGN_ID:
        raise RuntimeError(f"MT5 campaign_id mismatch: expected={CAMPAIGN_ID} actual={status.get('campaign_id')}")
    if status.get("run_id") != RUN_ID:
        raise RuntimeError(f"MT5 run_id mismatch: expected={RUN_ID} actual={status.get('run_id')}")
    if status.get("response_mode") != RESPONSE_MODE:
        raise RuntimeError(f"MT5 response_mode mismatch: expected={RESPONSE_MODE} actual={status.get('response_mode')}")


def fold_summary(events: list[dict[str, str]], profits: list[float]) -> dict[str, object]:
    entries = [row for row in events if row.get("event") == "entry"]
    schedule_rows = read_csv_rows(SCHEDULE_ARTIFACT) if SCHEDULE_ARTIFACT.exists() else []
    schedule_rows_by_entry = {
        parse_time(row["entry_time"]): row.get("fold_id", "")
        for row in schedule_rows
        if parse_time(row.get("entry_time")) is not None
    }
    buckets: dict[str, int] = {}
    for row in entries:
        timestamp = event_bar_time(row)
        fold_id = schedule_rows_by_entry.get(timestamp, "unknown")
        buckets[fold_id] = buckets.get(fold_id, 0) + 1
    return {
        "entry_count_by_fold": dict(sorted(buckets.items())),
        "trade_count_total": len(entries),
        "profit_count": len(profits),
    }

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
    report_paths = [rel(result.status_csv), rel(result.events_csv), rel(result.deals_csv), rel(SCHEDULE_ARTIFACT)]
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
    schedule_rows_count = len(read_csv_rows(SCHEDULE_ARTIFACT)) if SCHEDULE_ARTIFACT.exists() else 0
    family = "mt5_logic_parity" if mode == LOGIC_PARITY_MODE else "mt5_tick"
    return {
        "schema": "axiom_rift_mt5_logic_parity_kpi_v1" if mode == LOGIC_PARITY_MODE else "axiom_rift_mt5_tick_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "synthesis_id_when_applicable": None,
        "run_id": RUN_ID,
        "mt5_probe_id": "MT5-C0005-R0004",
        "mt5_kpi_family": family,
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
        "mt5_report_hashes": [
            sha256_file(path)
            for path in (result.status_csv, result.events_csv, result.deals_csv, SCHEDULE_ARTIFACT)
            if path.exists()
        ],
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
                    "lot": status.get("lot"),
                    "starting_balance_usd": STARTING_BALANCE_USD,
                },
            },
            "analog_memory_schedule_profile": {
                "applies": True,
                "fields": {
                    "analog_memory_source": "rolling_train_is_proxy_schedule",
                    "schedule_rows": schedule_rows_count,
                    "schedule_artifact_path": rel(SCHEDULE_ARTIFACT),
                    "model_selected": False,
                    "feature_set_selected": False,
                    "label_selected": False,
                    "runtime_portability_claim": False,
                },
            },
            "runtime_reproducibility_profile": {
                "applies": True,
                "fields": {
                    "mt5_tester_status": status.get("status"),
                    "runtime_data_availability_status": "tester_output_present",
                    "ea_mode": "schedule_replay_for_logic_parity" if mode == LOGIC_PARITY_MODE else "schedule_replay_for_tick_execution",
                    "known_runtime_blockers": known_blockers,
                },
            },
        },
        "mt5_probe_status": "completed" if status.get("status") == "completed" else status.get("status", "unknown"),
        "mt5_known_blockers": known_blockers,
        "missing_required_kpi_fields": missing_required,
        "deferred_with_reason": [
            {
                "field": "native_mql_or_onnx_analog_memory_surface",
                "requirement_class": "deferred_with_reason",
                "reason": "C0005 R0004 logic parity replays the proxy target-first tail-hazard analog-memory schedule; native model or ONNX materialization is not claimed at this stage",
                "blocking_condition": "candidate quality must be established before materialization work freezes export requirements",
                "revisit_when": "after fold-isolated MT5 tick evidence supports candidate quality",
                "claim_boundary": {"claim_authority": False, "onnx_ready": False, "runtime_authority": False},
            }
        ],
        "claim_boundary": {
            "claim_authority": False,
            "runtime_probe_completed": False,
            "runtime_authority": False,
            "live_ready": False,
        },
    }
def record_c0005_r0004_parity() -> dict[str, object]:
    mt5 = json.loads(MT5_LOGIC_KPI.read_text(encoding="ascii"))
    proxy_trades = load_proxy_trades()
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
        and exit_compare["reason_match_rate"] == 1.0
    )
    mismatch_count = (
        abs(entry_count_delta)
        + abs(exit_count_delta)
        + int(entry_compare["mismatch_count"])
        + int(exit_compare["mismatch_count"])
    )
    next_action = "produce_c0005_r0004_mt5_tick_execution_evidence" if mechanical_ok else "repair_c0005_r0004_schedule_replay_parity"
    mechanical_status = "passed" if mechanical_ok else "failed"
    intent_status = "passed_schedule_replay_boundary" if mechanical_ok else "blocked_by_mechanical_mismatch"
    payload = {
        "schema": "axiom_rift_proxy_vs_mt5_logic_parity_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "synthesis_id_when_applicable": None,
        "run_id": RUN_ID,
        "parity_id": "P-C0005-R0004",
        "proxy_id": "PX-C0005-R0004",
        "mt5_probe_id": "MT5-C0005-R0004",
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
            "repair_required": not mechanical_ok,
            "next_action": next_action,
        },
        "mechanical_checks": {
            "entry_count_match": "passed" if entry_count_delta == 0 else "failed",
            "exit_count_match": "passed" if exit_count_delta == 0 else "failed",
            "entry_time_direction_match": "passed" if entry_compare["key_match_rate"] == 1.0 else "failed",
            "analog_memory_schedule_match": "passed" if entry_compare["key_match_rate"] == 1.0 else "failed",
            "exit_time_reason_order_match": "passed" if exit_compare["reason_match_rate"] == 1.0 else "failed",
            "entry_exit_order_match": "passed" if exit_compare["time_direction_match_rate"] == 1.0 else "failed",
            "position_lifecycle_match": "passed" if mt5_trade_count == len(mt5_entries) == len(mt5_exits) else "failed",
        },
        "conditional_profiles": {
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
            "analog_memory_schedule_replay_profile": {
                "applies": True,
                "fields": {
                    "schedule_artifact_path": rel(SCHEDULE_ARTIFACT),
                    "schedule_hash": sha256_file(SCHEDULE_ARTIFACT) if SCHEDULE_ARTIFACT.exists() else None,
                    "logic_boundary": "proxy_selected_fold_local_target_first_tail_hazard_analog_memory_schedule_replayed_in_mt5_closed_bar_mode",
                    "native_mql_or_onnx_state_surface_claim": False,
                },
            },
            "cost_execution_profile": {
                "applies": True,
                "fields": mt5.get("conditional_profiles", {}).get("cost_execution_profile", {}).get("fields", {}),
            },
        },
        "deferred_with_reason": [
            {
                "field": "runtime_or_onnx_portability",
                "requirement_class": "deferred_with_reason",
                "reason": "logic parity uses schedule replay only; native analog-memory surface materialization is deferred until candidate quality exists",
                "blocking_condition": "no C0005 candidate has fold-isolated tick evidence yet",
                "revisit_when": "after fold-isolated MT5 tick closeout review",
                "claim_boundary": {"claim_authority": False, "runtime_authority": False, "onnx_ready": False},
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
        "A-C0005-R0004-PROXY-VS-MT5-LOGIC-KPI",
        "proxy_vs_mt5_logic_parity_kpi",
        "proxy_vs_mt5_logic_parity",
        rel(LOGIC_PARITY_KPI),
        sha256_file(LOGIC_PARITY_KPI),
        [
            "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/kpi/proxy.json",
            "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/kpi/mt5_logic_parity.json",
        ],
    )
    update_gate_after_parity(payload)
    update_reentry_after_logic_parity(next_action, mechanical_ok)
    update_campaign_after_logic_parity(next_action)
    update_claim_state_after_logic_parity(payload, mt5)
    return payload


def update_run_after_mt5(mode: str) -> None:
    data = json.loads(RUN_MANIFEST.read_text(encoding="ascii"))
    mode = normalize_mt5_mode(mode)
    evidence_paths = data.setdefault("evidence_paths", {})
    evidence_paths["mt5_logic_parity_kpi"] = "kpi/mt5_logic_parity.json"
    evidence_paths["proxy_vs_mt5_logic_parity_kpi"] = "kpi/proxy_vs_mt5_logic_parity.json"
    evidence_paths["mt5_schedule_artifact"] = "artifacts/c0005_r0004_schedule.csv"
    mt5_plan = data.setdefault("mt5_probe_plan", {})
    mt5_plan["logic_parity_kpi_path"] = "kpi/mt5_logic_parity.json"
    mt5_plan["logic_parity_purpose"] = "proxy_selected_target_first_tail_hazard_analog_memory_schedule_vs_ea_closed_bar_lifecycle_parity"
    mt5_plan["logic_parity_boundary"] = "schedule_replay_no_runtime_or_onnx_claim"
    parity_plan = data.setdefault("proxy_vs_mt5_plan", {})
    parity_plan["logic_parity_kpi_path"] = "kpi/proxy_vs_mt5_logic_parity.json"
    if mode == LOGIC_PARITY_MODE:
        data["status"] = "mt5_logic_parity_recorded_pending_parity"
        data["gate_status"] = "mt5_logic_parity_recorded_pending_parity"
    else:
        evidence_paths["mt5_tick_kpi"] = "kpi/mt5_tick.json"
        mt5_plan["tick_kpi_path"] = "kpi/mt5_tick.json"
        data["status"] = "mt5_tick_recorded_pending_execution_divergence"
        data["gate_status"] = "mt5_tick_recorded_pending_execution_divergence"
    RUN_MANIFEST.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_run_after_parity(parity_payload: dict[str, object]) -> None:
    data = json.loads(RUN_MANIFEST.read_text(encoding="ascii"))
    evidence_paths = data.setdefault("evidence_paths", {})
    evidence_paths["mt5_logic_parity_kpi"] = "kpi/mt5_logic_parity.json"
    evidence_paths["proxy_vs_mt5_logic_parity_kpi"] = "kpi/proxy_vs_mt5_logic_parity.json"
    evidence_paths["mt5_schedule_artifact"] = "artifacts/c0005_r0004_schedule.csv"
    repair_required = bool(parity_payload["required_kpis"]["repair_required"])  # type: ignore[index]
    data["status"] = "mechanical_parity_failed" if repair_required else "parity_evidence_recorded"
    data["gate_status"] = "logic_parity_evidence_recorded"
    RUN_MANIFEST.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_after_parity(parity_payload: dict[str, object]) -> None:
    data = json.loads(GATE_REPORT.read_text(encoding="ascii"))
    mechanical_status = parity_payload["required_kpis"]["mechanical_parity_status"]  # type: ignore[index]
    intent_status = parity_payload["required_kpis"]["intent_parity_status"]  # type: ignore[index]
    next_action = str(parity_payload["required_kpis"]["next_action"])  # type: ignore[index]
    data["evidence_gate"]["status"] = "logic_parity_evidence_recorded"
    checks = data["evidence_gate"].setdefault("checks", {})
    checks["mt5_logic_parity_kpi_path_recorded"] = True
    checks["proxy_vs_mt5_logic_parity_kpi_path_recorded"] = True
    evidence_paths = data.setdefault("evidence_paths", [])
    for path in ("kpi/mt5_logic_parity.json", "kpi/proxy_vs_mt5_logic_parity.json", "artifacts/c0005_r0004_schedule.csv"):
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
                "reason": "logic parity evidence is recorded, but schedule replay mechanical parity failed",
                "blocking_condition": next_action,
                "revisit_when": "after repaired closed-bar MT5 and logic parity evidence are recorded",
            }
        ]
    else:
        data["deferred_with_reason"] = [
            {
                "field": "run_closeout",
                "reason": "closed-bar MT5 logic parity and proxy-vs-MT5 parity are recorded; tick execution KPI is still required",
                "blocking_condition": "produce_c0005_r0004_mt5_tick_execution_evidence",
                "revisit_when": "after C0005 R0004 tick execution KPI and execution divergence are recorded",
            }
        ]
    GATE_REPORT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")
    update_run_after_parity(parity_payload)


def update_reentry_after_logic_parity(next_action: str, mechanical_ok: bool) -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    next_work = data.setdefault("next_work", {})
    completed = list(next_work.get("completed") or [])
    for item in (
        "produce_c0005_r0004_mt5_logic_parity_evidence",
        "record_c0005_r0004_proxy_vs_mt5_logic_parity_evidence",
    ):
        if item not in completed:
            completed.append(item)
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_campaign_after_logic_parity(next_action: str) -> None:
    data = yaml.safe_load(CAMPAIGN.read_text(encoding="ascii"))
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = next_action
    run_index = data.setdefault("run_index", {})
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["direction"] = "active_c0005_r0004_tick_execution" if "mt5_tick" in next_action else "active_c0005_r0004_parity_repair"
    next_candidate["reason"] = (
        "R0004 closed-bar MT5 logic parity and proxy-vs-MT5 parity are recorded; next work is mandatory tick execution evidence."
        if "mt5_tick" in next_action
        else "R0004 closed-bar MT5 logic parity is recorded but mechanical parity repair is required before hypothesis judgment."
    )
    next_candidate["status"] = "active_run_open"
    CAMPAIGN.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_claim_state_after_logic_parity(parity_payload: dict[str, object], mt5_payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE.read_text(encoding="ascii"))
    required = parity_payload["required_kpis"]  # type: ignore[index]
    mt5_required = mt5_payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0005_continuous_analog_memory_discovery"
    data["active_run"] = "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004"
    data["latest_operation"] = {
        "id": "produce_c0005_r0004_mt5_logic_parity_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/kpi/mt5_logic_parity.json",
        "paired_parity_source": "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/kpi/proxy_vs_mt5_logic_parity.json",
        "evidence_status": "logic_parity_evidence_recorded",
        "mt5_trade_count": mt5_required.get("mt5_trade_count"),
        "mt5_net_pnl": mt5_required.get("mt5_net_pnl"),
        "mechanical_parity_status": required.get("mechanical_parity_status"),
        "intent_parity_status": required.get("intent_parity_status"),
        "repair_required": required.get("repair_required"),
        "next_required_action": required.get("next_action"),
        "claim_boundary": {
            "claim_authority": False,
            "selected": False,
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "runtime_authority": False,
            "onnx_ready": False,
            "promotion_ready": False,
            "live_ready": False,
        },
    }
    CLAIM_STATE.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def record_c0005_r0004_execution_divergence() -> dict[str, object]:
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
        "run_closeout_review_ready": False,
    }
    missing_required = missing_required_execution_fields(required_kpis)
    payload = {
        "schema": "axiom_rift_execution_divergence_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "synthesis_id_when_applicable": None,
        "run_id": RUN_ID,
        "divergence_id": "ED-C0005-R0004",
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
            "analog_memory_schedule_profile": {
                "applies": True,
                "fields": {
                    "analog_memory_source": "rolling_train_is_proxy_schedule",
                    "schedule_artifact_path": rel(SCHEDULE_ARTIFACT),
                    "model_selected": False,
                    "feature_set_selected": False,
                    "label_selected": False,
                    "runtime_portability_claim": False,
                },
            },
            "spread_slippage_stress_profile": {
                "applies": False,
                "fields": {},
                "deferred_with_reason": "Baseline tick KPI is recorded; spread/slippage stress sweeps are separate robustness work.",
            },
            "run_closeout_profile": {
                "applies": True,
                "fields": {
                    "logic_parity_required": True,
                    "tick_execution_kpi_required": True,
                    "execution_divergence_required": True,
                    "fold_isolated_closeout_required": True,
                    "closeout_status": "blocked_until_fold_isolated_tick_and_divergence",
                },
            },
        },
        "missing_required_kpi_fields": missing_required,
        "deferred_with_reason": [
            {
                "field": "run_closeout_review_ready",
                "requirement_class": "deferred_with_reason",
                "reason": "aggregate tick KPI and divergence are diagnostic only for closeout",
                "blocking_condition": "rolling-window fold-isolated MT5 tick KPI and fold-isolated execution divergence are still required",
                "revisit_when": "after C0005 R0004 fold-isolated MT5 tick evidence",
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
        "A-C0005-R0004-EXECUTION-DIVERGENCE-KPI",
        "diagnostic_output",
        "execution_divergence",
        rel(EXECUTION_DIVERGENCE_KPI),
        sha256_file(EXECUTION_DIVERGENCE_KPI),
        [
            "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/kpi/mt5_logic_parity.json",
            "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/kpi/mt5_tick.json",
        ],
    )
    update_gate_after_execution_divergence(payload)
    update_reentry_after_tick_and_divergence()
    update_campaign_after_tick_and_divergence()
    update_claim_state_after_tick_and_divergence(payload, tick_mt5)
    return payload


def update_run_after_execution_divergence() -> None:
    data = json.loads(RUN_MANIFEST.read_text(encoding="ascii"))
    evidence_paths = data.setdefault("evidence_paths", {})
    evidence_paths["mt5_logic_parity_kpi"] = "kpi/mt5_logic_parity.json"
    evidence_paths["mt5_tick_kpi"] = "kpi/mt5_tick.json"
    evidence_paths["proxy_vs_mt5_logic_parity_kpi"] = "kpi/proxy_vs_mt5_logic_parity.json"
    evidence_paths["execution_divergence_kpi"] = "kpi/execution_divergence.json"
    evidence_paths["mt5_schedule_artifact"] = "artifacts/c0005_r0004_schedule.csv"
    data["status"] = "execution_divergence_recorded_pending_fold_isolated_tick"
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
        "artifacts/c0005_r0004_schedule.csv",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0005_r0004_fold_isolated_mt5_tick_kpi"
    data["deferred_with_reason"] = [
        {
            "field": "run_closeout",
            "reason": "logic parity, aggregate tick execution KPI, and execution divergence are recorded; closeout judgment still requires fold-isolated evidence",
            "blocking_condition": "produce_c0005_r0004_fold_isolated_mt5_tick_kpi",
            "revisit_when": "after fold-isolated tick KPI and fold-isolated execution divergence are recorded",
        }
    ]
    GATE_REPORT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")
    update_run_after_execution_divergence()


def update_reentry_after_tick_and_divergence() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    next_work = data.setdefault("next_work", {})
    completed = list(next_work.get("completed") or [])
    for item in (
        "produce_c0005_r0004_mt5_tick_execution_evidence",
        "record_c0005_r0004_execution_divergence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_c0005_r0004_fold_isolated_mt5_tick_kpi"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_campaign_after_tick_and_divergence() -> None:
    next_action = "produce_c0005_r0004_fold_isolated_mt5_tick_kpi"
    data = yaml.safe_load(CAMPAIGN.read_text(encoding="ascii"))
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = next_action
    run_index = data.setdefault("run_index", {})
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["direction"] = "active_c0005_r0004_fold_isolated_tick"
    next_candidate["reason"] = "R0004 aggregate tick execution and execution divergence are recorded; next work is mandatory fold-isolated MT5 tick evidence."
    next_candidate["status"] = "active_run_open"
    CAMPAIGN.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_claim_state_after_tick_and_divergence(divergence_payload: dict[str, object], tick_payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE.read_text(encoding="ascii"))
    required = divergence_payload["required_kpis"]  # type: ignore[index]
    tick_required = tick_payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0005_continuous_analog_memory_discovery"
    data["active_run"] = "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004"
    data["latest_operation"] = {
        "id": "produce_c0005_r0004_mt5_tick_execution_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/kpi/mt5_tick.json",
        "paired_divergence_source": "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/kpi/execution_divergence.json",
        "evidence_status": "logic_tick_and_divergence_recorded",
        "mt5_trade_count": tick_required.get("mt5_trade_count"),
        "mt5_net_pnl": tick_required.get("mt5_net_pnl"),
        "mt5_profit_factor": tick_required.get("mt5_profit_factor"),
        "execution_divergence_status": required.get("execution_divergence_status"),
        "economics_shift_status": required.get("economics_shift_status"),
        "next_required_action": "produce_c0005_r0004_fold_isolated_mt5_tick_kpi",
        "claim_boundary": {
            "claim_authority": False,
            "selected": False,
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "runtime_authority": False,
            "onnx_ready": False,
            "promotion_ready": False,
            "live_ready": False,
        },
    }
    CLAIM_STATE.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


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
    run_data["status"] = "fold_isolated_evidence_recorded_pending_closeout_review"
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
        "artifacts/c0005_r0004_schedule.csv",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    gate_data["decision"] = "defer_with_reason"
    gate_data["next_action"] = "review_c0005_r0004_tick_execution_kpi_and_closeout"
    gate_data["deferred_with_reason"] = [
        {
            "field": "run_closeout",
            "reason": "fold-isolated MT5 tick KPI and fold-isolated execution divergence are recorded; closeout judgment was not performed in this step",
            "blocking_condition": "review_c0005_r0004_tick_execution_kpi_and_closeout",
            "revisit_when": "during C0005 R0004 closeout review",
        }
    ]
    GATE_REPORT.write_text(json.dumps(gate_data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_reentry_after_fold_isolated() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    next_work = data.setdefault("next_work", {})
    completed = list(next_work.get("completed") or [])
    for item in (
        "produce_c0005_r0004_fold_isolated_mt5_tick_kpi",
        "produce_c0005_r0004_fold_isolated_execution_divergence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "review_c0005_r0004_tick_execution_kpi_and_closeout"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_campaign_after_fold_isolated() -> None:
    next_action = "review_c0005_r0004_tick_execution_kpi_and_closeout"
    data = yaml.safe_load(CAMPAIGN.read_text(encoding="ascii"))
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = next_action
    run_index = data.setdefault("run_index", {})
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["direction"] = "active_c0005_r0004_closeout_review"
    next_candidate["reason"] = "R0004 fold-isolated MT5 tick KPI and fold-isolated execution divergence are recorded; next work is closeout review."
    next_candidate["status"] = "active_run_open"
    CAMPAIGN.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_claim_state_after_fold_isolated(
    tick_by_fold_payload: dict[str, object],
    divergence_by_fold_payload: dict[str, object],
) -> None:
    data = yaml.safe_load(CLAIM_STATE.read_text(encoding="ascii"))
    tick_required = tick_by_fold_payload["required_kpis"]  # type: ignore[index]
    divergence_required = divergence_by_fold_payload["required_kpis"]  # type: ignore[index]
    data["active_campaign"] = "campaigns/C0005_continuous_analog_memory_discovery"
    data["active_run"] = "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004"
    data["latest_operation"] = {
        "id": "produce_c0005_r0004_fold_isolated_mt5_tick_kpi",
        "status": "completed",
        "recorded_at_source": "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/kpi/mt5_tick_by_fold.json",
        "paired_divergence_source": "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/kpi/execution_divergence_by_fold.json",
        "evidence_status": "fold_isolated_evidence_recorded_pending_closeout_review",
        "fold_count": tick_required.get("fold_count"),
        "completed_fold_count": tick_required.get("completed_fold_count"),
        "total_tick_trade_count": tick_required.get("total_tick_trade_count"),
        "total_tick_net_pnl": tick_required.get("total_tick_net_pnl"),
        "mt5_tick_by_fold_status": tick_required.get("mt5_tick_by_fold_status"),
        "execution_divergence_by_fold_status": divergence_required.get("execution_divergence_by_fold_status"),
        "total_tick_minus_logic_net_pnl": divergence_required.get("total_tick_minus_logic_net_pnl"),
        "next_required_action": "review_c0005_r0004_tick_execution_kpi_and_closeout",
        "claim_boundary": {
            "claim_authority": False,
            "selected": False,
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "runtime_authority": False,
            "onnx_ready": False,
            "promotion_ready": False,
            "live_ready": False,
        },
    }
    CLAIM_STATE.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


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
        "artifact_type": "csv" if repo_relative_path.endswith(".csv") else "json",
        "claim_authority": False,
        "linked_kpi_family": linked_kpi_family,
        "mutable": False,
        "produced_by": "axiom_rift.mt5.c0005_r0004_probe",
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
    if linked_kpi_family == "execution_divergence_by_fold":
        data["deferred_with_reason"] = [
            {
                "field": "closeout_review",
                "reason": "fold-isolated MT5 tick and execution divergence artifacts are recorded; closeout review is the next mandatory sequence step",
                "next_action": "review_c0005_r0004_tick_execution_kpi_and_closeout",
            }
        ]
    elif linked_kpi_family == "mt5_tick_by_fold":
        data["deferred_with_reason"] = [
            {
                "field": "fold_isolated_execution_divergence",
                "reason": "fold-isolated MT5 tick KPI is recorded; fold-isolated execution divergence remains required",
                "next_action": "produce_c0005_r0004_fold_isolated_execution_divergence",
            }
        ]
    elif linked_kpi_family == "execution_divergence":
        data["deferred_with_reason"] = [
            {
                "field": "fold_isolated_artifact_hashes",
                "reason": "aggregate tick and execution divergence artifacts are recorded; fold-isolated evidence is the next mandatory sequence step",
                "next_action": "produce_c0005_r0004_fold_isolated_mt5_tick_kpi",
            }
        ]
    else:
        data["deferred_with_reason"] = [
            {
                "field": "mt5_tick_and_fold_isolated_artifact_hashes",
                "reason": "logic parity artifacts are recorded; tick execution and fold-isolated evidence are later mandatory sequence steps",
                "next_action": "produce_c0005_r0004_mt5_tick_execution_evidence",
            }
        ]
    ARTIFACT_LINEAGE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def run_c0005_r0004_mt5_logic_workflow(timeout_seconds: int = 1800) -> dict[str, object]:
    result = run_c0005_r0004_tester(mode=LOGIC_PARITY_MODE, timeout_seconds=timeout_seconds)
    mt5_payload = parse_c0005_r0004_mt5(result)
    parity_payload = record_c0005_r0004_parity()
    return {
        "mt5": mt5_payload["required_kpis"],
        "parity": parity_payload["required_kpis"],
        "schedule_csv": SCHEDULE_ARTIFACT.as_posix(),
        "status_csv": result.status_csv.as_posix(),
        "events_csv": result.events_csv.as_posix(),
        "deals_csv": result.deals_csv.as_posix(),
    }


def run_c0005_r0004_mt5_tick_workflow(timeout_seconds: int = 1800) -> dict[str, object]:
    result = run_c0005_r0004_tester(mode=TICK_EXECUTION_MODE, timeout_seconds=timeout_seconds)
    mt5_payload = parse_c0005_r0004_mt5(result)
    divergence_payload = record_c0005_r0004_execution_divergence()
    return {
        "mt5_tick": mt5_payload["required_kpis"],
        "execution_divergence": divergence_payload["required_kpis"],
        "status_csv": result.status_csv.as_posix(),
        "events_csv": result.events_csv.as_posix(),
        "deals_csv": result.deals_csv.as_posix(),
    }


def run_c0005_r0004_mt5_tick_by_fold_workflow(timeout_seconds: int = 1800) -> dict[str, object]:
    compile_c0005_r0004_ea()
    write_schedule_files()
    records: list[dict[str, Any]] = []
    for window in load_test_windows():
        from_date, to_date = tester_dates_for_window(window)
        logic_result = run_c0005_r0004_tester(
            mode=LOGIC_PARITY_MODE,
            timeout_seconds=timeout_seconds,
            from_date=from_date,
            to_date=to_date,
            output_scope=window.fold_id,
            compile_before=False,
        )
        logic_payload = parse_c0005_r0004_mt5(logic_result, write_kpi=False)
        tick_result = run_c0005_r0004_tester(
            mode=TICK_EXECUTION_MODE,
            timeout_seconds=timeout_seconds,
            from_date=from_date,
            to_date=to_date,
            output_scope=window.fold_id,
            compile_before=False,
        )
        tick_payload = parse_c0005_r0004_mt5(tick_result, write_kpi=False)
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
        "A-C0005-R0004-MT5-TICK-BY-FOLD-KPI",
        "mt5_tick_by_fold_kpi",
        "mt5_tick_by_fold",
        rel(MT5_TICK_BY_FOLD_KPI),
        sha256_file(MT5_TICK_BY_FOLD_KPI),
        [
            "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/artifacts/c0005_r0004_schedule.csv",
            "registries/rolling_windows.yaml",
            "configs/market.yaml",
        ],
    )
    upsert_artifact_lineage(
        "A-C0005-R0004-EXECUTION-DIVERGENCE-BY-FOLD-KPI",
        "diagnostic_output",
        "execution_divergence_by_fold",
        rel(EXECUTION_DIVERGENCE_BY_FOLD_KPI),
        sha256_file(EXECUTION_DIVERGENCE_BY_FOLD_KPI),
        [
            "campaigns/C0005_continuous_analog_memory_discovery/runs/R0004/kpi/mt5_tick_by_fold.json",
            "registries/rolling_windows.yaml",
        ],
    )
    update_gate_after_fold_isolated_evidence(tick_by_fold_payload, divergence_by_fold_payload)
    update_reentry_after_fold_isolated()
    update_campaign_after_fold_isolated()
    update_claim_state_after_fold_isolated(tick_by_fold_payload, divergence_by_fold_payload)
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
        "work_unit_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "synthesis_id_when_applicable": None,
        "run_id": RUN_ID,
        "mt5_probe_id": "MT5-C0005-R0004-BY-FOLD",
        "split_policy": "rolling_window_test_oos_fold_isolated",
        "split_registry": "registries/rolling_windows.yaml",
        "required_kpis": required_kpis,
        "conditional_profiles": {
            "fold_profile": {"applies": True, "fields": {"folds": fold_rows, "missing_by_fold": missing_by_fold}},
            "analog_memory_schedule_profile": {
                "applies": True,
                "fields": {
                    "analog_memory_source": "rolling_train_is_proxy_schedule",
                    "schedule_artifact_path": rel(SCHEDULE_ARTIFACT),
                    "model_selected": False,
                    "feature_set_selected": False,
                    "label_selected": False,
                    "runtime_portability_claim": False,
                },
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
        for target, value in (
            (entry_rates, fold_required["entry_key_match_rate"]),
            (exit_time_direction_rates, fold_required["exit_time_direction_match_rate"]),
            (exit_reason_rates, fold_required["exit_reason_match_rate"]),
        ):
            if value is not None:
                target.append(float(value))
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
        "work_unit_id": CAMPAIGN_ID,
        "campaign_id": CAMPAIGN_ID,
        "synthesis_id_when_applicable": None,
        "run_id": RUN_ID,
        "divergence_id": "ED-C0005-R0004-BY-FOLD",
        "split_policy": "rolling_window_test_oos_fold_isolated",
        "split_registry": "registries/rolling_windows.yaml",
        "tick_mt5_by_fold_kpi_path": rel(MT5_TICK_BY_FOLD_KPI),
        "required_kpis": required_kpis,
        "conditional_profiles": {
            "fold_divergence_profile": {
                "applies": True,
                "fields": {"folds": fold_rows, "missing_by_fold": missing_by_fold},
            },
            "analog_memory_schedule_profile": {
                "applies": True,
                "fields": {
                    "analog_memory_source": "rolling_train_is_proxy_schedule",
                    "schedule_artifact_path": rel(SCHEDULE_ARTIFACT),
                    "model_selected": False,
                    "feature_set_selected": False,
                    "label_selected": False,
                    "runtime_portability_claim": False,
                },
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
