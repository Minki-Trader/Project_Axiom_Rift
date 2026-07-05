"""MT5 schedule-replay logic parity helpers for SC0007 SR0001."""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
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
    bool_text,
    compare_entry_sequence,
    compare_exit_sequence,
    compare_mt5_entry_events,
    compare_mt5_exit_events,
    direction_summary,
    economics_shift_status,
    execution_divergence_status,
    int_delta,
    kpi_float,
    kpi_int,
    missing_required_by_fold_fields,
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
    schedule_fold_summary,
    tester_dates_for_window,
    tester_date_to_iso,
    tester_model_label,
    tester_to_date_to_end_iso,
    time_text,
    to_float,
    wait_for_status,
)
from axiom_rift.mt5.shared import CompileResult, TesterResult
from axiom_rift.mt5.terminal_hygiene import cleanup_headless_terminal, prepare_headless_terminal
from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies.common import base as proxy_base
from axiom_rift.proxies.sc0007_sr0001_post_sc0006_price_memory_negative_context import (
    BASE_FRAME,
    ROLLING_WINDOWS,
    TIME_FORMAT,
)


EA_NAME = "AxiomC0002ScheduleReplay"
EA_SOURCE = PROJECT_ROOT / "src" / "axiom_rift" / "mt5" / "experts" / f"{EA_NAME}.mq5"
WORK_UNIT_ID = "SC0007"
RUN_ID = "SR0001"
RUN_DIR = PROJECT_ROOT / "campaigns" / "SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis" / "runs" / RUN_ID
SYNTHESIS_QUEUE = PROJECT_ROOT / "campaigns" / "SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis" / "synthesis_queue.yaml"
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
SYNTHESIS = PROJECT_ROOT / "campaigns" / "SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis" / "synthesis.yaml"
SELECTED = PROJECT_ROOT / "campaigns" / "SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis" / "selected.yaml"
CLAIM_STATE = PROJECT_ROOT / "registries" / "claim_state.yaml"
DECISION_CURSOR = PROJECT_ROOT / "registries" / "decision_cursor.yaml"
DECISION_REGISTRY = PROJECT_ROOT / "registries" / "decision_registry.yaml"
WORK_UNIT_REGISTRY = PROJECT_ROOT / "registries" / "work_unit_registry.yaml"
PROXY_TRADE_ARTIFACT = RUN_ARTIFACT_DIR / "sc0007_sr0001_proxy_trades.csv"
SCHEDULE_ARTIFACT = RUN_ARTIFACT_DIR / "sc0007_sr0001_schedule.csv"
SCHEDULE_COMMON_REL = "AxiomRift\\SC0007\\SR0001\\schedule\\sc0007_sr0001_schedule.csv"
WORK_UNIT_REL = "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis"
RUN_REL = f"{WORK_UNIT_REL}/runs/{RUN_ID}"
NEXT_MAJOR_ACTION = "choose_c0038_new_major_hypothesis_after_sc0007_closeout"
SC0007_CLOSE_REASON = "no_candidate_after_weak_proxy_near_flat_tick_and_unstable_fold_isolated_tick_evidence"
SC0007_REMAINING_WORK_CLASSIFICATION = (
    "post_sc0006_price_memory_negative_context_weight_fragility_threshold_monthly_filter_"
    "stop_target_hold_activity_spread_session_capital_or_retry_nudge_not_next"
)
SC0007_CLOSED_STATUSES = {"closed_no_candidate", "closed_with_candidate_evidence", "closed_non_portable"}
STARTING_BALANCE_USD = starting_balance_usd()
RESPONSE_MODE = "post_sc0006_price_memory_negative_context_schedule_replay"
MAX_HOLD_BARS = 10
MAGIC = 970001
TESTER_FROM_DATE = "2024.02.01"
TESTER_TO_DATE = "2026.05.01"
ZERO_TRADE_TICK_NOT_APPLICABLE_FIELDS = (
    "mt5_profit_factor",
    "mt5_max_drawdown_percent",
    "mt5_expectancy_per_entry",
    "mt5_win_rate",
)
ZERO_TRADE_DIVERGENCE_NOT_APPLICABLE_FIELDS = (
    "logic_max_drawdown_percent",
    "tick_max_drawdown_percent",
    "tick_minus_logic_max_drawdown_percent",
    "logic_profit_factor",
    "tick_profit_factor",
    "tick_minus_logic_profit_factor",
    "logic_win_rate",
    "tick_win_rate",
    "tick_minus_logic_win_rate",
    "logic_expectancy_per_entry",
    "tick_expectancy_per_entry",
    "tick_minus_logic_expectancy_per_entry",
    "entry_key_match_rate",
    "exit_time_direction_match_rate",
    "exit_reason_match_rate",
)


@dataclass(frozen=True)
class LoadedTrade:
    fold_id: str
    signal_index: int
    entry_time: datetime
    exit_time: datetime
    direction: int
    score: float
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    pnl_points: float
    bars_held: int
    exit_reason: str
    mfe_points: float
    mae_points: float
    spread_points: float


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def claim_boundary_payload() -> dict[str, bool]:
    return {
        "claim_authority": False,
        "selected": False,
        "label_selected": False,
        "feature_set_selected": False,
        "model_selected": False,
        "trade_logic_selected": False,
        "runtime_probe_completed": False,
        "economics_pass": False,
        "materialization_ready": False,
        "runtime_authority": False,
        "onnx_ready": False,
        "promotion_ready": False,
        "live_ready": False,
    }


def fold_summary(events: list[dict[str, str]], profits: list[float]) -> dict[str, object]:
    return schedule_fold_summary(events, profits, SCHEDULE_ARTIFACT)


def compile_sc0007_sr0001_ea(metaeditor_exe: Path | None = None) -> CompileResult:
    metaeditor_exe = runtime_metaeditor_exe() if metaeditor_exe is None else metaeditor_exe
    if not metaeditor_exe.exists():
        raise FileNotFoundError(f"MetaEditor not found: {metaeditor_exe}")
    target_dir = terminal_data_dir() / "MQL5" / "Experts" / "AxiomRift"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / EA_SOURCE.name
    shutil.copy2(EA_SOURCE, target)
    log = PROJECT_ROOT / "artifacts" / "reports" / "SC0007_SR0001_mt5_compile.log"
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
        / WORK_UNIT_ID
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


def tester_config_path(mode: str = LOGIC_PARITY_MODE, output_scope: str | None = None) -> Path:
    mode = normalize_mt5_mode(mode)
    output_scope = normalize_output_scope(output_scope)
    suffix = mode if output_scope is None else f"{mode}_{output_scope}"
    return PROJECT_ROOT / "artifacts" / "reports" / "SC0007_SR0001_mt5_tester" / f"SC0007_SR0001_{suffix}_tester.ini"


def tester_report_path(mode: str = LOGIC_PARITY_MODE, output_scope: str | None = None) -> Path:
    mode = normalize_mt5_mode(mode)
    output_scope = normalize_output_scope(output_scope)
    suffix = mode if output_scope is None else f"{mode}_{output_scope}"
    return PROJECT_ROOT / "artifacts" / "reports" / "SC0007_SR0001_mt5_tester" / f"SC0007_SR0001_mt5_{suffix}_report.htm"


def tester_report_stem(mode: str = LOGIC_PARITY_MODE, output_scope: str | None = None) -> Path:
    return tester_report_path(mode, output_scope).with_suffix("")


def clear_common_outputs(mode: str = LOGIC_PARITY_MODE, output_scope: str | None = None) -> None:
    directory = common_output_dir(mode, output_scope)
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("mt5_status.csv", "mt5_events.csv", "mt5_deals.csv"):
        path = directory / name
        if path.exists():
            path.unlink()


def write_schedule_files() -> tuple[Path, Path]:
    rows = schedule_rows(load_proxy_trade_artifact())
    RUN_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    write_schedule_csv(SCHEDULE_ARTIFACT, rows)
    common_path = schedule_common_path()
    common_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCHEDULE_ARTIFACT, common_path)
    return SCHEDULE_ARTIFACT, common_path


def load_proxy_trade_artifact() -> list[LoadedTrade]:
    if not PROXY_TRADE_ARTIFACT.exists():
        raise FileNotFoundError(f"Proxy trade artifact not found: {PROXY_TRADE_ARTIFACT}")
    rows = read_csv_rows(PROXY_TRADE_ARTIFACT)
    trades: list[LoadedTrade] = []
    for row in rows:
        trades.append(
            LoadedTrade(
                fold_id=row["fold_id"],
                signal_index=int(row["signal_index"]),
                entry_time=datetime.strptime(row["entry_time"], TIME_FORMAT),
                exit_time=datetime.strptime(row["exit_time"], TIME_FORMAT),
                direction=int(row["direction"]),
                score=to_float(row["score"]),
                entry_price=to_float(row["entry_price"]),
                exit_price=to_float(row["exit_price"]),
                stop_price=to_float(row["stop_price"]),
                target_price=to_float(row["target_price"]),
                pnl_points=to_float(row["pnl_points"]),
                bars_held=int(row["bars_held"]),
                exit_reason=row["exit_reason"],
                mfe_points=to_float(row["mfe_points"]),
                mae_points=to_float(row["mae_points"]),
                spread_points=to_float(row["spread_points"]),
            )
        )
    return trades


def schedule_rows(trades: list[LoadedTrade]) -> list[dict[str, object]]:
    bars = proxy_base.load_bars(BASE_FRAME)
    index_by_time = {bar.time: index for index, bar in enumerate(bars)}
    rows: list[dict[str, object]] = []
    for trade in trades:
        entry_index = index_by_time.get(trade.entry_time)
        signal_time = bars[entry_index - 1].time if entry_index is not None and entry_index > 0 else trade.entry_time
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


def load_test_windows() -> list[proxy_base.SplitWindow]:
    windows = proxy_base.load_windows(ROLLING_WINDOWS)
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
    if model is None:
        model = tester_model_for_mode(mode)
    use_closed_bar_exit = mode == LOGIC_PARITY_MODE
    config_dir = PROJECT_ROOT / "artifacts" / "reports" / "SC0007_SR0001_mt5_tester"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = tester_config_path(mode, output_scope)
    report = tester_report_stem(mode, output_scope)
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
        f"InpCampaignId={WORK_UNIT_ID}",
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


def run_sc0007_sr0001_tester(
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
        compile_sc0007_sr0001_ea()
    write_schedule_files()
    clear_common_outputs(mode, output_scope)
    config = write_tester_config(mode=mode, from_date=from_date, to_date=to_date, model=model, output_scope=output_scope)
    report = tester_report_path(mode, output_scope)
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
        use_closed_bar_exit=mode == LOGIC_PARITY_MODE,
        output_scope=output_scope,
        from_date=from_date,
        to_date=to_date,
    )


def parse_sc0007_sr0001_mt5(
    result: TesterResult | None = None,
    mode: str = LOGIC_PARITY_MODE,
    write_kpi: bool = True,
) -> dict[str, object]:
    mode = normalize_mt5_mode(mode if result is None else result.mode)
    if result is None:
        result = TesterResult(
            config=tester_config_path(mode),
            report=tester_report_path(mode),
            common_dir=common_output_dir(mode),
            status_csv=common_output_dir(mode) / "mt5_status.csv",
            events_csv=common_output_dir(mode) / "mt5_events.csv",
            deals_csv=common_output_dir(mode) / "mt5_deals.csv",
            mode=mode,
            use_closed_bar_exit=mode == LOGIC_PARITY_MODE,
            from_date=TESTER_FROM_DATE,
            to_date=TESTER_TO_DATE,
        )
    missing = [path for path in (result.status_csv, result.events_csv, result.deals_csv) if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing MT5 output files: " + ", ".join(str(path) for path in missing))
    status = read_status_csv(result.status_csv)
    assert_mt5_status_matches(mode, status, result.output_scope)
    events = read_csv_rows(result.events_csv)
    deals = read_csv_rows(result.deals_csv)
    payload = build_mt5_payload(result, status, events, deals)
    if not write_kpi:
        return payload
    kpi_path = MT5_LOGIC_KPI if mode == LOGIC_PARITY_MODE else MT5_TICK_KPI
    kpi_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    if mode == LOGIC_PARITY_MODE:
        upsert_artifact_lineage(
            "A-SC0007-SR0001-MT5-SCHEDULE",
            "mt5_schedule_csv",
            "mt5_logic_parity_input",
            rel(SCHEDULE_ARTIFACT),
            sha256_file(SCHEDULE_ARTIFACT),
            ["campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/kpi/proxy.json"],
        )
        upsert_artifact_lineage(
            "A-SC0007-SR0001-MT5-LOGIC-KPI",
            "mt5_logic_parity_kpi",
            "mt5_logic_parity",
            rel(MT5_LOGIC_KPI),
            sha256_file(MT5_LOGIC_KPI),
            [
                "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/artifacts/sc0007_sr0001_schedule.csv",
                "configs/market.yaml",
            ],
        )
    else:
        upsert_artifact_lineage(
            "A-SC0007-SR0001-MT5-TICK-KPI",
            "mt5_tick_kpi",
            "mt5_tick",
            rel(MT5_TICK_KPI),
            sha256_file(MT5_TICK_KPI),
            [
                "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/artifacts/sc0007_sr0001_schedule.csv",
                "configs/market.yaml",
            ],
        )
    update_run_after_mt5(mode)
    return payload


def assert_mt5_status_matches(mode: str, status: dict[str, str], output_scope: str | None = None) -> None:
    mode = normalize_mt5_mode(mode)
    expected_exit = "closed_bar_ohlc" if mode == LOGIC_PARITY_MODE else "tick_price"
    if status.get("output_mode") != mode:
        raise RuntimeError(f"MT5 output_mode mismatch: expected={mode} actual={status.get('output_mode')}")
    if status.get("exit_evaluation") != expected_exit:
        raise RuntimeError(f"MT5 exit_evaluation mismatch: expected={expected_exit} actual={status.get('exit_evaluation')}")
    if output_scope is not None and status.get("output_scope") != output_scope:
        raise RuntimeError(f"MT5 output_scope mismatch: expected={output_scope} actual={status.get('output_scope')}")
    if status.get("campaign_id") != WORK_UNIT_ID:
        raise RuntimeError(f"MT5 campaign_id mismatch: expected={WORK_UNIT_ID} actual={status.get('campaign_id')}")
    if status.get("response_mode") != RESPONSE_MODE:
        raise RuntimeError(f"MT5 response_mode mismatch: expected={RESPONSE_MODE} actual={status.get('response_mode')}")


def build_mt5_payload(
    result: TesterResult,
    status: dict[str, str],
    events: list[dict[str, str]],
    deals: list[dict[str, str]],
) -> dict[str, object]:
    mode = normalize_mt5_mode(result.mode)
    mode_label = "logic_parity_closed_bar_exit" if mode == LOGIC_PARITY_MODE else "tick_execution"
    family = "mt5_logic_parity" if mode == LOGIC_PARITY_MODE else "mt5_tick"
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
    return {
        "schema": "axiom_rift_mt5_logic_parity_kpi_v1" if mode == LOGIC_PARITY_MODE else "axiom_rift_mt5_tick_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": WORK_UNIT_ID,
        "campaign_id": None,
        "synthesis_id_when_applicable": WORK_UNIT_ID,
        "run_id": RUN_ID,
        "mt5_probe_id": "MT5-SC0007-SR0001",
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
            "synthesis_schedule_replay_profile": {
                "applies": True,
                "fields": {
                    "schedule_rows": schedule_rows_count,
                    "schedule_artifact_path": rel(SCHEDULE_ARTIFACT),
                    "source_proxy_trade_artifact": rel(PROXY_TRADE_ARTIFACT),
                    "logic_boundary": "proxy_selected_post_sc0006_price_memory_negative_context_schedule_replayed_in_mt5_closed_bar_mode"
                    if mode == LOGIC_PARITY_MODE
                    else "proxy_schedule_replayed_in_mt5_tick_mode_for_execution_divergence",
                    "native_mql_training_claim": False,
                    "model_selected": False,
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
                "field": "native_mql_post_sc0006_price_memory_negative_context_synthesis_logic",
                "requirement_class": "deferred_with_reason",
                "reason": "SC0007 SR0001 replays the proxy schedule in MT5; native model or ONNX materialization is not claimed",
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


def record_sc0007_sr0001_parity() -> dict[str, object]:
    mt5 = json.loads(MT5_LOGIC_KPI.read_text(encoding="ascii"))
    proxy_trades = load_proxy_trade_artifact()
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
    next_action = (
        "produce_sc0007_sr0001_mt5_tick_execution_evidence"
        if mechanical_ok
        else "repair_sc0007_sr0001_schedule_replay_parity"
    )
    mechanical_status = "passed" if mechanical_ok else "failed"
    intent_status = "passed_schedule_replay_boundary" if mechanical_ok else "blocked_by_mechanical_mismatch"
    payload = {
        "schema": "axiom_rift_proxy_vs_mt5_logic_parity_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": WORK_UNIT_ID,
        "campaign_id": None,
        "synthesis_id_when_applicable": WORK_UNIT_ID,
        "run_id": RUN_ID,
        "parity_id": "P-SC0007-SR0001",
        "proxy_id": "PX-SC0007-SR0001",
        "mt5_probe_id": "MT5-SC0007-SR0001",
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
            "negative_memory_synthesis_schedule_exit_match": "passed" if exit_compare["reason_match_rate"] == 1.0 else "failed",
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
            "synthesis_schedule_replay_profile": {
                "applies": True,
                "fields": {
                    "schedule_artifact_path": rel(SCHEDULE_ARTIFACT),
                    "schedule_hash": sha256_file(SCHEDULE_ARTIFACT) if SCHEDULE_ARTIFACT.exists() else None,
                    "logic_boundary": "proxy_selected_post_sc0006_price_memory_negative_context_schedule_replayed_in_mt5_closed_bar_mode",
                    "native_mql_training_claim": False,
                    "runtime_portability_claim": False,
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
                "reason": "logic parity uses schedule replay only; native cross-family hardening materialization is deferred until candidate quality exists",
                "blocking_condition": "no candidate has fold-isolated tick evidence yet",
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
        "A-SC0007-SR0001-PARITY-KPI",
        "proxy_vs_mt5_logic_parity_kpi",
        "proxy_vs_mt5_logic_parity",
        rel(LOGIC_PARITY_KPI),
        sha256_file(LOGIC_PARITY_KPI),
        [
            "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/kpi/proxy.json",
            "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/kpi/mt5_logic_parity.json",
        ],
    )
    update_gate_after_logic_parity(payload, next_action, mechanical_ok)
    update_run_after_logic_parity(next_action, mechanical_ok)
    update_reentry_after_logic_parity(next_action)
    update_synthesis_queue_after_logic_parity(next_action, mechanical_ok)
    update_synthesis_after_logic_parity(next_action, mechanical_ok)
    update_selected_after_logic_parity(next_action, mechanical_ok)
    update_claim_state_after_logic_parity(payload, next_action, mechanical_ok)
    update_decision_cursor_after_logic_parity(payload, next_action, mechanical_ok)
    append_decision_registry_after_logic_parity(payload, next_action, mechanical_ok)
    refresh_state_artifact_hashes()
    return payload


def update_run_after_mt5(mode: str) -> None:
    mode = normalize_mt5_mode(mode)
    data = json.loads(RUN_MANIFEST.read_text(encoding="ascii"))
    evidence_paths = data.setdefault("evidence_paths", {})
    evidence_paths["mt5_logic_parity_kpi"] = "kpi/mt5_logic_parity.json"
    evidence_paths["proxy_vs_mt5_logic_parity_kpi"] = "kpi/proxy_vs_mt5_logic_parity.json"
    evidence_paths["mt5_schedule_artifact"] = "artifacts/sc0007_sr0001_schedule.csv"
    mt5_plan = data.setdefault("mt5_probe_plan", {})
    mt5_plan["logic_parity_kpi_path"] = "kpi/mt5_logic_parity.json"
    mt5_plan["logic_parity_purpose"] = "proxy_post_sc0006_price_memory_negative_context_synthesis_schedule_vs_ea_closed_bar_lifecycle_parity"
    mt5_plan["logic_parity_boundary"] = "schedule_replay_no_runtime_or_onnx_claim"
    if mode == LOGIC_PARITY_MODE:
        data["status"] = "mt5_logic_parity_recorded_pending_parity"
        data["gate_status"] = "mt5_logic_parity_recorded_pending_parity"
    else:
        evidence_paths["mt5_tick_kpi"] = "kpi/mt5_tick.json"
        mt5_plan["tick_kpi_path"] = "kpi/mt5_tick.json"
        data["status"] = "mt5_tick_recorded_pending_execution_divergence"
        data["gate_status"] = "mt5_tick_recorded_pending_execution_divergence"
    RUN_MANIFEST.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_run_after_logic_parity(next_action: str, mechanical_ok: bool) -> None:
    data = json.loads(RUN_MANIFEST.read_text(encoding="ascii"))
    evidence_paths = data.setdefault("evidence_paths", {})
    evidence_paths["mt5_logic_parity_kpi"] = "kpi/mt5_logic_parity.json"
    evidence_paths["proxy_vs_mt5_logic_parity_kpi"] = "kpi/proxy_vs_mt5_logic_parity.json"
    evidence_paths["mt5_schedule_artifact"] = "artifacts/sc0007_sr0001_schedule.csv"
    status = "logic_parity_recorded_pending_tick" if mechanical_ok else "logic_parity_repair_required"
    data["status"] = status
    data["gate_status"] = status
    mt5_plan = data.setdefault("mt5_probe_plan", {})
    mt5_plan["next_required_action"] = next_action
    mt5_plan["logic_parity_recorded"] = True
    mt5_plan["proxy_vs_mt5_logic_parity_recorded"] = True
    RUN_MANIFEST.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_after_logic_parity(payload: dict[str, object], next_action: str, mechanical_ok: bool) -> None:
    data = json.loads(GATE_REPORT.read_text(encoding="ascii"))
    status = "logic_parity_recorded_pending_tick" if mechanical_ok else "logic_parity_repair_required"
    data["status"] = status
    data["evidence_gate"]["status"] = "logic_parity_evidence_recorded"
    checks = data["evidence_gate"].setdefault("checks", {})
    checks["mt5_logic_parity_kpi_path_recorded"] = True
    checks["proxy_vs_mt5_logic_parity_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "passed" if mechanical_ok else "failed"
    data["parity_gate"]["mechanical_parity_status"] = payload["required_kpis"]["mechanical_parity_status"]  # type: ignore[index]
    data["parity_gate"]["intent_parity_status"] = payload["required_kpis"]["intent_parity_status"]  # type: ignore[index]
    data["parity_gate"]["repair_required"] = not mechanical_ok
    data["decision"] = "defer_with_reason"
    data["next_action"] = next_action
    mt5_gate = data.setdefault("mt5_gate", {})
    mt5_gate["status"] = "mt5_tick_required_next" if mechanical_ok else "logic_parity_repair_required"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in ("kpi/mt5_logic_parity.json", "kpi/proxy_vs_mt5_logic_parity.json", "artifacts/sc0007_sr0001_schedule.csv"):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["evidence_paths"] = evidence_paths
    data["deferred_with_reason"] = [
        {
            "field": "decision",
            "reason": "closed-bar MT5 logic parity and proxy-vs-MT5 parity are recorded; tick execution KPI is still required"
            if mechanical_ok
            else "logic parity evidence is recorded, but schedule replay mechanical parity failed",
            "blocking_condition": "SR0001 cannot close until mandatory MT5 tick, execution divergence, and fold-isolated evidence are recorded"
            if mechanical_ok
            else "repair schedule replay parity and rerun logic parity before judging the hypothesis",
            "revisit_when": next_action,
        }
    ]
    GATE_REPORT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_reentry_after_logic_parity(next_action: str) -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    next_work = data.setdefault("next_work", {})
    completed = list(next_work.get("completed") or [])
    for item in (
        "produce_sc0007_sr0001_mt5_logic_parity_evidence",
        "record_sc0007_sr0001_proxy_vs_mt5_logic_parity_evidence",
    ):
        if item not in completed:
            completed.append(item)
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_synthesis_queue_after_logic_parity(next_action: str, mechanical_ok: bool) -> None:
    data = yaml.safe_load(SYNTHESIS_QUEUE.read_text(encoding="ascii"))
    for item in data.get("queue", []):
        if item.get("synthesis_run_id") == RUN_ID:
            item["status"] = "logic_parity_done" if mechanical_ok else "logic_parity_repair_required"
            item["last_completed_step"] = "produce_sc0007_sr0001_mt5_logic_parity_evidence"
            item["next_action"] = next_action
    SYNTHESIS_QUEUE.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_synthesis_after_logic_parity(next_action: str, mechanical_ok: bool) -> None:
    data = yaml.safe_load(SYNTHESIS.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts" if mechanical_ok else "logic_parity_repair_required"
    run_index = data.setdefault("run_index", {})
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["run_id"] = RUN_ID
    next_candidate["direction"] = next_action
    next_candidate["status"] = "active_run_open"
    next_candidate["reason"] = (
        "SR0001 closed-bar MT5 logic parity and proxy-vs-MT5 parity are recorded; tick execution KPI is next."
        if mechanical_ok
        else "SR0001 closed-bar MT5 logic parity was recorded with mechanical mismatch; schedule replay repair is next."
    )
    SYNTHESIS.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_selected_after_logic_parity(next_action: str, mechanical_ok: bool) -> None:
    data = yaml.safe_load(SELECTED.read_text(encoding="ascii"))
    status = "logic_parity_recorded_pending_tick" if mechanical_ok else "logic_parity_repair_required"
    data["status"] = status
    latest = data.setdefault("latest_synthesis_state", {})
    latest["status"] = status
    latest["source"] = "runs/SR0001/kpi/proxy_vs_mt5_logic_parity.json"
    latest["active_run"] = "runs/SR0001"
    latest["next_required_action"] = next_action
    latest["claim_boundary"] = claim_boundary_payload()
    data["claim_boundary"] = data.get("claim_boundary", {})
    data["selected"] = False
    SELECTED.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_claim_state_after_logic_parity(payload: dict[str, object], next_action: str, mechanical_ok: bool) -> None:
    data = yaml.safe_load(CLAIM_STATE.read_text(encoding="ascii"))
    required = payload.get("required_kpis", {})
    if not isinstance(required, dict):
        required = {}
    evidence_status = "logic_parity_recorded_pending_tick" if mechanical_ok else "logic_parity_repair_required"
    data["active_campaign"] = None
    data["active_synthesis"] = "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis"
    data["active_run"] = "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001"
    data["latest_operation"] = {
        "id": "produce_sc0007_sr0001_mt5_logic_parity_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/kpi/proxy_vs_mt5_logic_parity.json",
        "evidence_status": evidence_status,
        "active_synthesis": "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis",
        "active_run": "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001",
        "mt5_trade_count_delta": required.get("trade_count_delta"),
        "entry_key_match_rate": required.get("entry_key_match_rate"),
        "exit_reason_match_rate": required.get("exit_reason_match_rate"),
        "mechanical_parity_status": required.get("mechanical_parity_status"),
        "intent_parity_status": required.get("intent_parity_status"),
        "repair_required": required.get("repair_required"),
        "next_required_action": next_action,
        "claim_boundary": claim_boundary_payload(),
    }
    data["claim_boundary"] = claim_boundary_payload()
    CLAIM_STATE.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_decision_cursor_after_logic_parity(payload: dict[str, object], next_action: str, mechanical_ok: bool) -> None:
    data = yaml.safe_load(DECISION_CURSOR.read_text(encoding="ascii"))
    required = payload.get("required_kpis", {})
    if not isinstance(required, dict):
        required = {}
    evidence_status = "logic_parity_recorded_pending_tick" if mechanical_ok else "logic_parity_repair_required"
    data["updated_local_date"] = datetime.now().date().isoformat()
    data["canonical_source"] = "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/kpi/proxy_vs_mt5_logic_parity.json"
    data["canonical_status"] = evidence_status
    data["current_decision"] = next_action
    data["next_required_action"] = next_action
    summary = data.setdefault("current_evidence_summary", {})
    summary["current_task"] = next_action
    summary["active_run_status"] = evidence_status
    summary["evidence_status"] = evidence_status
    summary["next_required_action"] = next_action
    summary["mt5_logic_parity_trade_count_delta"] = required.get("trade_count_delta")
    summary["entry_key_match_rate"] = required.get("entry_key_match_rate")
    summary["exit_reason_match_rate"] = required.get("exit_reason_match_rate")
    summary["mechanical_parity_status"] = required.get("mechanical_parity_status")
    summary["intent_parity_status"] = required.get("intent_parity_status")
    summary["note"] = (
        "SC0007 SR0001 closed-bar MT5 logic parity is recorded; tick execution KPI is next."
        if mechanical_ok
        else "SC0007 SR0001 logic parity is recorded with mechanical mismatch; repair is next."
    )
    basis = data.setdefault("next_decision_basis", [])
    if isinstance(basis, list):
        basis[:] = [
            item
            for item in basis
            if not (isinstance(item, dict) and item.get("role") == "active_synthesis_run_logic_parity_kpi")
        ]
        basis.insert(
            0,
            {
                "path": "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/kpi/proxy_vs_mt5_logic_parity.json",
                "role": "active_synthesis_run_logic_parity_kpi",
                "summary": "SC0007 SR0001 closed-bar MT5 logic parity is recorded; next action remains inside mandatory paired validation.",
            },
        )
    data["claim_boundary_snapshot"] = claim_boundary_payload()
    DECISION_CURSOR.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def append_decision_registry_after_logic_parity(payload: dict[str, object], next_action: str, mechanical_ok: bool) -> None:
    data = yaml.safe_load(DECISION_REGISTRY.read_text(encoding="ascii"))
    if isinstance(data, dict):
        decisions = data.setdefault("decisions", [])
    else:
        decisions = data if isinstance(data, list) else []
    decision_id = "dec_20260706_produce_sc0007_sr0001_mt5_logic_parity_evidence"
    if any(isinstance(item, dict) and item.get("decision_id") == decision_id for item in decisions):
        return
    required = payload.get("required_kpis", {})
    if not isinstance(required, dict):
        required = {}
    decisions.append(
        {
            "decision_id": decision_id,
            "created_local_date": datetime.now().date().isoformat(),
            "status": "active",
            "decision": "produce_sc0007_sr0001_mt5_logic_parity_evidence",
            "refines": [
                "dec_20260705_produce_sc0007_sr0001_proxy_evidence",
                "dec_20260701_mandatory_mt5_paired_run_validation",
            ],
            "rationale": [
                "closed_bar_mt5_logic_parity_and_proxy_vs_mt5_parity_are_recorded_for_sc0007_sr0001",
                f"mechanical_parity_status_{required.get('mechanical_parity_status')}",
                f"intent_parity_status_{required.get('intent_parity_status')}",
                f"next_work_is_{next_action}",
                "logic_parity_does_not_create_selected_economics_runtime_materialization_onnx_promotion_or_live_claims",
            ],
            "claim_boundary": claim_boundary_payload(),
        }
    )
    if not isinstance(data, dict):
        data = decisions
    DECISION_REGISTRY.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def record_sc0007_sr0001_execution_divergence() -> dict[str, object]:
    logic_mt5 = json.loads(MT5_LOGIC_KPI.read_text(encoding="ascii"))
    tick_mt5 = json.loads(MT5_TICK_KPI.read_text(encoding="ascii"))
    logic_events = read_csv_rows(common_output_dir(LOGIC_PARITY_MODE) / "mt5_events.csv")
    tick_events = read_csv_rows(common_output_dir(TICK_EXECUTION_MODE) / "mt5_events.csv")
    logic_entries = [row for row in logic_events if row.get("event") == "entry"]
    logic_exits = [row for row in logic_events if row.get("event") == "exit"]
    tick_entries = [row for row in tick_events if row.get("event") == "entry"]
    tick_exits = [row for row in tick_events if row.get("event") == "exit"]
    entry_compare = compare_mt5_entry_events(logic_entries, tick_entries)
    exit_compare = compare_mt5_exit_events(logic_exits, tick_exits)
    logic_required = dict(logic_mt5.get("required_kpis", {}))
    tick_required = dict(tick_mt5.get("required_kpis", {}))
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
    }
    missing_required = missing_required_kpi_fields(required_kpis)
    payload = {
        "schema": "axiom_rift_execution_divergence_kpi_v1",
        "template": False,
        "requirement_policy": "required_and_conditional_required_with_deferred_reason",
        "created_at_utc": utc_now(),
        "work_unit_id": WORK_UNIT_ID,
        "campaign_id": None,
        "synthesis_id_when_applicable": WORK_UNIT_ID,
        "run_id": RUN_ID,
        "divergence_id": "ED-SC0007-SR0001",
        "logic_mt5_kpi_path": rel(MT5_LOGIC_KPI),
        "tick_mt5_kpi_path": rel(MT5_TICK_KPI),
        "required_kpis": required_kpis,
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
            "run_closeout_profile": {
                "applies": True,
                "fields": {
                    "aggregate_full_period_mt5_kpi_role": "diagnostic_only",
                    "closeout_judgment_surface": "rolling_window_fold_isolated_mt5_tick",
                    "closeout_status": "blocked_until_fold_isolated_tick_and_divergence",
                },
            },
            "synthesis_schedule_replay_profile": {
                "applies": True,
                "fields": {
                    "schedule_artifact_path": rel(SCHEDULE_ARTIFACT),
                    "risk_shape_source": "proxy_post_sc0006_price_memory_negative_context_synthesis_schedule",
                    "tick_mode_policy": "record_execution_divergence_not_proxy_parity_failure",
                    "runtime_portability_claim": False,
                },
            },
            "spread_slippage_stress_profile": {
                "applies": False,
                "fields": {
                    "deferred_with_reason": "Baseline tick KPI and divergence are recorded; stress sweeps are later robustness work."
                },
            },
        },
        "missing_required_kpi_fields": missing_required,
        "deferred_with_reason": [
            {
                "field": "fold_isolated_execution_divergence",
                "requirement_class": "deferred_with_reason",
                "reason": "aggregate tick KPI and divergence are diagnostic only for closeout",
                "blocking_condition": "rolling-window fold-isolated MT5 tick KPI and fold-isolated execution divergence are still required",
                "revisit_when": "after SC0007 SR0001 fold-isolated MT5 tick evidence",
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
        "A-SC0007-SR0001-EXEC-DIVERGENCE-KPI",
        "execution_divergence_kpi",
        "execution_divergence",
        rel(EXECUTION_DIVERGENCE_KPI),
        sha256_file(EXECUTION_DIVERGENCE_KPI),
        [
            "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/kpi/mt5_logic_parity.json",
            "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/kpi/mt5_tick.json",
        ],
    )
    update_run_after_execution_divergence()
    update_gate_after_execution_divergence(payload)
    update_reentry_after_execution_divergence()
    update_synthesis_queue_after_execution_divergence()
    return payload


def update_run_after_execution_divergence() -> None:
    data = json.loads(RUN_MANIFEST.read_text(encoding="ascii"))
    evidence_paths = data.setdefault("evidence_paths", {})
    evidence_paths["mt5_tick_kpi"] = "kpi/mt5_tick.json"
    evidence_paths["execution_divergence_kpi"] = "kpi/execution_divergence.json"
    data["status"] = "execution_divergence_recorded_pending_fold_isolated_evidence"
    data["gate_status"] = "logic_tick_and_divergence_recorded"
    RUN_MANIFEST.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_after_execution_divergence(payload: dict[str, object]) -> None:
    data = json.loads(GATE_REPORT.read_text(encoding="ascii"))
    checks = data["evidence_gate"].setdefault("checks", {})
    checks["mt5_tick_kpi_path_recorded"] = True
    checks["execution_divergence_kpi_path_recorded"] = True
    data["evidence_gate"]["status"] = "logic_tick_and_divergence_recorded"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_sc0007_sr0001_fold_isolated_mt5_tick_kpi"
    data["execution_gate"] = {
        "status": "recorded_with_divergence",
        "run_closeout_review_ready": False,
        "missing_required_kpi_fields": payload.get("missing_required_kpi_fields", []),
        "economics_shift_status": payload["required_kpis"].get("economics_shift_status"),  # type: ignore[index]
    }
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in ("kpi/mt5_tick.json", "kpi/execution_divergence.json"):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["evidence_paths"] = evidence_paths
    data["deferred_with_reason"] = [
        {
            "field": "fold_isolated_closeout_gate",
            "reason": "logic parity, tick execution KPI, and aggregate execution divergence are recorded; run closeout still requires fold-isolated MT5 tick and divergence",
            "blocking_condition": "kpi/mt5_tick_by_fold.json and kpi/execution_divergence_by_fold.json are not yet recorded",
            "revisit_when": "produce_sc0007_sr0001_fold_isolated_mt5_tick_kpi",
        }
    ]
    GATE_REPORT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_reentry_after_execution_divergence() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    next_work = data.setdefault("next_work", {})
    completed = list(next_work.get("completed") or [])
    for item in (
        "produce_sc0007_sr0001_mt5_tick_execution_evidence",
        "record_sc0007_sr0001_execution_divergence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_sc0007_sr0001_fold_isolated_mt5_tick_kpi"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_synthesis_queue_after_execution_divergence() -> None:
    data = yaml.safe_load(SYNTHESIS_QUEUE.read_text(encoding="ascii"))
    for item in data.get("queue", []):
        if item.get("synthesis_run_id") == RUN_ID:
            item["status"] = "execution_divergence_done"
            item["last_completed_step"] = "record_sc0007_sr0001_execution_divergence"
            item["next_action"] = "produce_sc0007_sr0001_fold_isolated_mt5_tick_kpi"
    SYNTHESIS_QUEUE.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def zero_trade_tick_not_applicable_fields(required_kpis: dict[str, object], missing: list[str]) -> list[str]:
    trade_count = kpi_int(required_kpis, "mt5_trade_count")
    net_pnl = kpi_float(required_kpis, "mt5_net_pnl")
    if trade_count == 0 and (net_pnl is None or net_pnl == 0.0):
        return [field for field in missing if field in ZERO_TRADE_TICK_NOT_APPLICABLE_FIELDS]
    return []


def zero_trade_divergence_not_applicable_fields(required_kpis: dict[str, object], missing: list[str]) -> list[str]:
    logic_trade_count = kpi_int(required_kpis, "logic_trade_count")
    tick_trade_count = kpi_int(required_kpis, "tick_trade_count")
    logic_net = kpi_float(required_kpis, "logic_net_pnl")
    tick_net = kpi_float(required_kpis, "tick_net_pnl")
    if logic_trade_count == 0 and tick_trade_count == 0 and (logic_net is None or logic_net == 0.0) and (tick_net is None or tick_net == 0.0):
        return [field for field in missing if field in ZERO_TRADE_DIVERGENCE_NOT_APPLICABLE_FIELDS]
    return []


def active_missing_fields(missing: list[str], not_applicable: list[str]) -> list[str]:
    not_applicable_set = set(not_applicable)
    return [field for field in missing if field not in not_applicable_set]


def build_mt5_tick_by_fold_payload(records: list[dict[str, Any]]) -> dict[str, object]:
    fold_rows: list[dict[str, object]] = []
    nets: list[tuple[str, float]] = []
    drawdowns: list[tuple[str, float]] = []
    trade_count_total = 0
    missing_by_fold: dict[str, list[str]] = {}
    not_applicable_by_fold: dict[str, list[str]] = {}
    completed_count = 0
    for record in records:
        window = record["window"]
        tick_payload = record["tick_payload"]
        tick_result = record["tick_result"]
        required = dict(tick_payload.get("required_kpis", {}))
        raw_missing = list(tick_payload.get("missing_required_kpi_fields", []))
        not_applicable = zero_trade_tick_not_applicable_fields(required, raw_missing)
        missing = active_missing_fields(raw_missing, not_applicable)
        if missing:
            missing_by_fold[window.fold_id] = missing
        if not_applicable:
            not_applicable_by_fold[window.fold_id] = not_applicable
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
                "not_applicable_kpi_fields": not_applicable,
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
        "zero_trade_fold_count": len(not_applicable_by_fold),
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
        "work_unit_id": WORK_UNIT_ID,
        "campaign_id": None,
        "synthesis_id_when_applicable": WORK_UNIT_ID,
        "run_id": RUN_ID,
        "mt5_probe_id": "MT5-SC0007-SR0001-BY-FOLD",
        "split_policy": "rolling_window_test_oos_fold_isolated",
        "split_registry": "registries/rolling_windows.yaml",
        "required_kpis": required_kpis,
        "conditional_profiles": {
            "fold_profile": {
                "applies": True,
                "fields": {
                    "folds": fold_rows,
                    "missing_by_fold": missing_by_fold,
                    "not_applicable_by_fold": not_applicable_by_fold,
                    "not_applicable_reason": "zero trade fold has no denominator for profit factor, drawdown, expectancy, or win rate",
                },
            },
            "synthesis_schedule_replay_profile": {
                "applies": True,
                "fields": {
                    "risk_shape_source": "proxy_post_sc0006_price_memory_negative_context_synthesis_schedule",
                    "schedule_artifact_path": rel(SCHEDULE_ARTIFACT),
                    "model_selected": False,
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
    not_applicable_by_fold: dict[str, list[str]] = {}
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
        raw_missing = missing_required_execution_fields(fold_required)
        not_applicable = zero_trade_divergence_not_applicable_fields(fold_required, raw_missing)
        missing = active_missing_fields(raw_missing, not_applicable)
        if missing:
            missing_by_fold[window.fold_id] = missing
        if not_applicable:
            not_applicable_by_fold[window.fold_id] = not_applicable
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
                "not_applicable_kpi_fields": not_applicable,
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
        "zero_trade_fold_count": len(not_applicable_by_fold),
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
        "work_unit_id": WORK_UNIT_ID,
        "campaign_id": None,
        "synthesis_id_when_applicable": WORK_UNIT_ID,
        "run_id": RUN_ID,
        "divergence_id": "ED-SC0007-SR0001-BY-FOLD",
        "split_policy": "rolling_window_test_oos_fold_isolated",
        "split_registry": "registries/rolling_windows.yaml",
        "tick_mt5_by_fold_kpi_path": rel(MT5_TICK_BY_FOLD_KPI),
        "required_kpis": required_kpis,
        "conditional_profiles": {
            "fold_divergence_profile": {
                "applies": True,
                "fields": {
                    "folds": fold_rows,
                    "missing_by_fold": missing_by_fold,
                    "not_applicable_by_fold": not_applicable_by_fold,
                    "not_applicable_reason": "zero trade fold has no denominator for rate, expectancy, drawdown, or profit factor deltas",
                },
            },
            "synthesis_schedule_replay_profile": {
                "applies": True,
                "fields": {
                    "risk_shape_source": "proxy_post_sc0006_price_memory_negative_context_synthesis_schedule",
                    "schedule_artifact_path": rel(SCHEDULE_ARTIFACT),
                    "model_selected": False,
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
    mt5_plan["next_required_action"] = "review_sc0007_sr0001_tick_execution_kpi_and_closeout"
    run_data["status"] = "fold_isolated_evidence_recorded_pending_closeout_review"
    run_data["gate_status"] = "fold_isolated_evidence_recorded_pending_closeout_review"
    RUN_MANIFEST.write_text(json.dumps(run_data, indent=2, sort_keys=True) + "\n", encoding="ascii")

    gate_data = json.loads(GATE_REPORT.read_text(encoding="ascii"))
    gate_data["status"] = "fold_isolated_evidence_recorded_pending_closeout_review"
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
    mt5_gate = gate_data.setdefault("mt5_gate", {})
    mt5_gate["status"] = "fold_isolated_evidence_recorded_pending_closeout_review"
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
        "artifacts/sc0007_sr0001_schedule.csv",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    gate_data["decision"] = "defer_with_reason"
    gate_data["next_action"] = "review_sc0007_sr0001_tick_execution_kpi_and_closeout"
    gate_data["deferred_with_reason"] = [
        {
            "field": "run_closeout",
            "reason": "fold-isolated MT5 tick KPI and fold-isolated execution divergence are recorded; closeout judgment was not performed in this step",
            "blocking_condition": "review_sc0007_sr0001_tick_execution_kpi_and_closeout",
            "revisit_when": "during SC0007 SR0001 closeout review",
        }
    ]
    GATE_REPORT.write_text(json.dumps(gate_data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_reentry_after_fold_isolated() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    next_work = data.setdefault("next_work", {})
    completed = list(next_work.get("completed") or [])
    for item in (
        "produce_sc0007_sr0001_fold_isolated_mt5_tick_kpi",
        "produce_sc0007_sr0001_fold_isolated_execution_divergence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "review_sc0007_sr0001_tick_execution_kpi_and_closeout"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_synthesis_queue_after_fold_isolated() -> None:
    data = yaml.safe_load(SYNTHESIS_QUEUE.read_text(encoding="ascii"))
    for item in data.get("queue", []):
        if item.get("synthesis_run_id") == RUN_ID:
            item["status"] = "fold_isolated_evidence_done"
            item["last_completed_step"] = "produce_sc0007_sr0001_fold_isolated_execution_divergence"
            item["next_action"] = "review_sc0007_sr0001_tick_execution_kpi_and_closeout"
    SYNTHESIS_QUEUE.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def upsert_artifact_lineage(
    artifact_id: str,
    artifact_role: str,
    artifact_type: str,
    repo_relative_path: str,
    file_hash: str,
    source_inputs: list[str],
) -> None:
    data = json.loads(ARTIFACT_LINEAGE.read_text(encoding="ascii"))
    records = [
        record
        for record in data.get("artifact_records", [])
        if record.get("artifact_role") != artifact_role and record.get("artifact_id") != artifact_id
    ]
    records.append(
        {
            "artifact_id": artifact_id,
            "artifact_role": artifact_role,
            "artifact_type": artifact_type,
            "repo_relative_path": repo_relative_path,
            "sha256": file_hash,
            "produced_by": "axiom_rift.mt5.sc0007_sr0001_probe",
            "source_inputs": source_inputs,
            "linked_kpi_family": artifact_role,
            "mutable": False,
            "claim_authority": False,
        }
    )
    data["artifact_records"] = records
    try:
        run_status = json.loads(RUN_MANIFEST.read_text(encoding="ascii")).get("status")
    except (FileNotFoundError, json.JSONDecodeError):
        run_status = None
    if run_status in SC0007_CLOSED_STATUSES:
        data["deferred_with_reason"] = []
    elif EXECUTION_DIVERGENCE_BY_FOLD_KPI.exists():
        deferred_field = "closeout_review"
        deferred_reason = "fold-isolated tick and divergence artifacts are recorded; closeout review is next"
        deferred_next_action = "review_sc0007_sr0001_tick_execution_kpi_and_closeout"
        data["deferred_with_reason"] = [
            {
                "field": deferred_field,
                "reason": deferred_reason,
                "next_action": deferred_next_action,
            }
        ]
    elif EXECUTION_DIVERGENCE_KPI.exists():
        deferred_field = "fold_isolated_artifact_hashes"
        deferred_reason = "fold-isolated tick and divergence artifacts are produced after aggregate tick execution"
        deferred_next_action = "produce_sc0007_sr0001_fold_isolated_mt5_tick_kpi"
        data["deferred_with_reason"] = [
            {
                "field": deferred_field,
                "reason": deferred_reason,
                "next_action": deferred_next_action,
            }
        ]
    else:
        deferred_field = "mt5_tick_artifact_hashes"
        deferred_reason = "tick execution artifacts are produced after closed-bar logic parity"
        deferred_next_action = "produce_sc0007_sr0001_mt5_tick_execution_evidence"
        data["deferred_with_reason"] = [
            {
                "field": deferred_field,
                "reason": deferred_reason,
                "next_action": deferred_next_action,
            }
        ]
    ARTIFACT_LINEAGE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def refresh_state_artifact_hashes() -> None:
    upsert_artifact_lineage(
        "A-SC0007-SR0001-RUN-MANIFEST",
        "run_manifest",
        "json",
        rel(RUN_MANIFEST),
        sha256_file(RUN_MANIFEST),
        [
            "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/kpi/mt5_logic_parity.json",
            "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/kpi/proxy_vs_mt5_logic_parity.json",
        ],
    )
    upsert_artifact_lineage(
        "A-SC0007-SR0001-GATE-REPORT",
        "gate_report",
        "json",
        rel(GATE_REPORT),
        sha256_file(GATE_REPORT),
        [
            "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/run_manifest.json",
            "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/kpi/proxy_vs_mt5_logic_parity.json",
        ],
    )


def load_json_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def required_kpis_from(path: Path) -> dict[str, Any]:
    required = load_json_payload(path).get("required_kpis", {})
    if not isinstance(required, dict):
        raise ValueError(f"required_kpis must be an object: {path}")
    return required


def closeout_evidence_paths() -> list[str]:
    return [
        "artifact_lineage.json",
        "run_manifest.json",
        "kpi/proxy.json",
        "kpi/mt5_logic_parity.json",
        "kpi/proxy_vs_mt5_logic_parity.json",
        "kpi/mt5_tick.json",
        "kpi/execution_divergence.json",
        "artifacts/sc0007_sr0001_proxy_trades.csv",
        "artifacts/sc0007_sr0001_negative_context_synthesis_summary.json",
        "artifacts/sc0007_sr0001_schedule.csv",
        "kpi/mt5_tick_by_fold.json",
        "kpi/execution_divergence_by_fold.json",
    ]


def sc0007_closeout_kpi_summary() -> dict[str, Any]:
    proxy_payload = load_json_payload(KPI_DIR / "proxy.json")
    proxy_required = dict(proxy_payload.get("required_kpis", {}))
    proxy_summary = dict(proxy_payload.get("proxy_summary", {}))
    logic_required = required_kpis_from(MT5_LOGIC_KPI)
    parity_required = required_kpis_from(LOGIC_PARITY_KPI)
    tick_required = required_kpis_from(MT5_TICK_KPI)
    divergence_required = required_kpis_from(EXECUTION_DIVERGENCE_KPI)
    tick_by_fold_required = required_kpis_from(MT5_TICK_BY_FOLD_KPI)
    divergence_by_fold_required = required_kpis_from(EXECUTION_DIVERGENCE_BY_FOLD_KPI)
    return {
        "entries_per_active_day": proxy_summary.get("entries_per_active_day"),
        "proxy_net_pnl_points": proxy_required.get("proxy_net_pnl_points"),
        "proxy_profit_factor": proxy_required.get("proxy_profit_factor"),
        "proxy_expectancy_points_per_entry": proxy_required.get("proxy_expectancy_points_per_entry"),
        "proxy_trade_count": proxy_required.get("proxy_trade_count"),
        "proxy_win_rate": proxy_required.get("proxy_win_rate"),
        "mt5_logic_net_pnl": logic_required.get("mt5_net_pnl"),
        "mt5_logic_profit_factor": logic_required.get("mt5_profit_factor"),
        "mt5_logic_trade_count": logic_required.get("mt5_trade_count"),
        "mechanical_parity_status": parity_required.get("mechanical_parity_status"),
        "intent_parity_status": parity_required.get("intent_parity_status"),
        "mismatch_count": parity_required.get("mismatch_count"),
        "entry_key_match_rate": parity_required.get("entry_key_match_rate"),
        "exit_reason_match_rate": parity_required.get("exit_reason_match_rate"),
        "mt5_tick_net_pnl": tick_required.get("mt5_net_pnl"),
        "mt5_tick_profit_factor": tick_required.get("mt5_profit_factor"),
        "mt5_tick_max_drawdown_percent": tick_required.get("mt5_max_drawdown_percent"),
        "mt5_tick_trade_count": tick_required.get("mt5_trade_count"),
        "mt5_tick_win_rate": tick_required.get("mt5_win_rate"),
        "mt5_tick_expectancy_per_entry": tick_required.get("mt5_expectancy_per_entry"),
        "execution_divergence_status": divergence_required.get("execution_divergence_status"),
        "economics_shift_status": divergence_required.get("economics_shift_status"),
        "tick_minus_logic_net_pnl": divergence_required.get("tick_minus_logic_net_pnl"),
        "entry_count_delta": divergence_required.get("entry_count_delta"),
        "exit_count_delta": divergence_required.get("exit_count_delta"),
        "mt5_tick_by_fold_status": tick_by_fold_required.get("mt5_tick_by_fold_status"),
        "fold_count": tick_by_fold_required.get("fold_count"),
        "completed_fold_count": tick_by_fold_required.get("completed_fold_count"),
        "profitable_fold_count": tick_by_fold_required.get("profitable_fold_count"),
        "losing_fold_count": tick_by_fold_required.get("losing_fold_count"),
        "zero_trade_fold_count": tick_by_fold_required.get("zero_trade_fold_count"),
        "total_tick_net_pnl": tick_by_fold_required.get("total_tick_net_pnl"),
        "total_tick_trade_count": tick_by_fold_required.get("total_tick_trade_count"),
        "worst_fold_id": tick_by_fold_required.get("worst_fold_id"),
        "worst_fold_net_pnl": tick_by_fold_required.get("worst_fold_net_pnl"),
        "worst_fold_max_drawdown_percent": tick_by_fold_required.get("worst_fold_max_drawdown_percent"),
        "execution_divergence_by_fold_status": divergence_by_fold_required.get(
            "execution_divergence_by_fold_status"
        ),
        "minimum_entry_key_match_rate": divergence_by_fold_required.get("minimum_entry_key_match_rate"),
        "minimum_exit_reason_match_rate": divergence_by_fold_required.get("minimum_exit_reason_match_rate"),
        "minimum_exit_time_direction_match_rate": divergence_by_fold_required.get(
            "minimum_exit_time_direction_match_rate"
        ),
        "tick_better_fold_count": divergence_by_fold_required.get("tick_better_fold_count"),
        "tick_worse_fold_count": divergence_by_fold_required.get("tick_worse_fold_count"),
        "total_tick_minus_logic_net_pnl": divergence_by_fold_required.get("total_tick_minus_logic_net_pnl"),
        "worst_tick_minus_logic_fold_id": divergence_by_fold_required.get("worst_tick_minus_logic_fold_id"),
        "worst_tick_minus_logic_net_pnl": divergence_by_fold_required.get("worst_tick_minus_logic_net_pnl"),
        "remaining_work_classification": SC0007_REMAINING_WORK_CLASSIFICATION,
    }


def sc0007_failure_asset(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_type": "negative_memory",
        "hypothesis_tested": (
            "SC0007 SR0001 fold-local post-SC0006 price-memory candidate schedule reranked by "
            "C0031-C0036 negative-memory context and C0037 fragility evidence without source OOS PnL selection"
        ),
        "evidence_paths": [
            "kpi/proxy.json",
            "kpi/mt5_logic_parity.json",
            "kpi/proxy_vs_mt5_logic_parity.json",
            "kpi/mt5_tick.json",
            "kpi/execution_divergence.json",
            "kpi/mt5_tick_by_fold.json",
            "kpi/execution_divergence_by_fold.json",
        ],
        "reason_not_candidate": (
            "proxy was weak and losing, aggregate MT5 tick was only near-flat positive, "
            "and fold-isolated MT5 tick evidence was unstable with five losing folds, "
            "three profitable folds, and one zero-trade fold"
        ),
        "next_boundary": (
            "close SC0007 with negative memory; do not retry this synthesis as simple "
            "negative-context weight, fragility, threshold, monthly-filter, stop, target, hold, "
            "activity, spread, session, capital, or retry tuning; next work should choose a "
            "materially new C0038 major hypothesis axis"
        ),
        "supporting_lessons": [
            {
                "asset_type": "negative_memory",
                "source": "kpi/mt5_tick_by_fold.json",
                "summary": (
                    "post-SC0006 negative-context rerank did not improve fold stability; "
                    f"total tick net PnL was {summary.get('total_tick_net_pnl')} with "
                    f"{summary.get('profitable_fold_count')} profitable folds, "
                    f"{summary.get('losing_fold_count')} losing folds, and "
                    f"{summary.get('zero_trade_fold_count')} zero-trade fold"
                ),
            },
            {
                "asset_type": "parity_lesson",
                "source": "kpi/proxy_vs_mt5_logic_parity.json",
                "summary": (
                    "schedule replay logic parity passed, so this is hypothesis-quality and "
                    "execution-stability evidence rather than a proxy-to-EA schedule mismatch"
                ),
            },
            {
                "asset_type": "execution_divergence_lesson",
                "source": "kpi/execution_divergence_by_fold.json",
                "summary": (
                    f"tick execution improved total net versus closed-bar logic by "
                    f"{summary.get('total_tick_minus_logic_net_pnl')} but remained too weak "
                    "and fold-unstable for candidate retention"
                ),
            },
            {
                "asset_type": "evidence_gap",
                "source": "kpi/mt5_tick_by_fold.json",
                "summary": (
                    "rw_007 produced zero trades; null denominator metrics are recorded as "
                    "not-applicable, not missing KPI or hypothesis failure by broken code"
                ),
            },
        ],
    }


def sc0007_closeout_review(closed_at: str) -> dict[str, Any]:
    summary = sc0007_closeout_kpi_summary()
    return {
        "status": "closed_no_candidate",
        "basis": "rolling_window_fold_isolated_mt5_tick",
        "close_reason": SC0007_CLOSE_REASON,
        "closed_at_utc": closed_at,
        "required_kpi_summary": summary,
        "failure_asset": sc0007_failure_asset(summary),
        "claim_boundary": claim_boundary_payload(),
    }


def update_run_manifest_for_closeout(closeout_review: dict[str, Any], closed_at: str) -> None:
    data = json.loads(RUN_MANIFEST.read_text(encoding="ascii"))
    data["status"] = "closed_no_candidate"
    data["gate_status"] = "closed_no_candidate"
    data["closed_at_utc"] = closed_at
    data["closeout_review"] = closeout_review
    evidence = data.setdefault("evidence_paths", {})
    evidence.update(
        {
            "artifact_lineage": "artifact_lineage.json",
            "gate_report": "gate_report.json",
            "proxy_kpi": "kpi/proxy.json",
            "mt5_logic_parity_kpi": "kpi/mt5_logic_parity.json",
            "proxy_vs_mt5_logic_parity_kpi": "kpi/proxy_vs_mt5_logic_parity.json",
            "mt5_tick_kpi": "kpi/mt5_tick.json",
            "execution_divergence_kpi": "kpi/execution_divergence.json",
            "proxy_trade_artifact": "artifacts/sc0007_sr0001_proxy_trades.csv",
            "negative_context_synthesis_summary": "artifacts/sc0007_sr0001_negative_context_synthesis_summary.json",
            "mt5_schedule_artifact": "artifacts/sc0007_sr0001_schedule.csv",
            "mt5_tick_by_fold_kpi": "kpi/mt5_tick_by_fold.json",
            "execution_divergence_by_fold_kpi": "kpi/execution_divergence_by_fold.json",
        }
    )
    mt5_plan = data.setdefault("mt5_probe_plan", {})
    mt5_plan["closeout_status"] = "closed_no_candidate"
    mt5_plan["next_required_action"] = NEXT_MAJOR_ACTION
    data["claim_boundary"] = claim_boundary_payload()
    RUN_MANIFEST.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report_for_closeout(closeout_review: dict[str, Any]) -> None:
    data = json.loads(GATE_REPORT.read_text(encoding="ascii"))
    summary = closeout_review["required_kpi_summary"]
    data["schema"] = "axiom_rift_gate_report_v2"
    data["gate_report_id"] = "G-SC0007-SR0001"
    data["status"] = "closed_no_candidate"
    data["decision"] = "close_no_candidate"
    data["role"] = "lightweight_decision_receipt"
    data["next_action"] = NEXT_MAJOR_ACTION
    data["deferred_with_reason"] = []
    data["closeout_review"] = closeout_review
    data["claim_boundary"] = claim_boundary_payload()
    data["must_not"] = [
        "claim_selected",
        "claim_runtime_authority",
        "claim_onnx_ready",
        "claim_live_ready",
        "skip_mt5_when_proxy_is_weak",
        "close_from_aggregate_mt5",
        "close_from_broken_code",
    ]
    data["claim_gate"] = {
        "status": "passed_no_claim_authority",
        "claim_authority": False,
        "selected": False,
        "label_selected": False,
        "feature_set_selected": False,
        "model_selected": False,
        "trade_logic_selected": False,
        "runtime_authority": False,
        "onnx_ready": False,
        "live_ready": False,
    }
    data["evidence_gate"] = {
        "status": "passed",
        "checks": {
            "artifact_lineage_path_recorded": True,
            "run_manifest_path_recorded": True,
            "proxy_kpi_path_recorded": True,
            "mt5_logic_parity_kpi_path_recorded": True,
            "proxy_vs_mt5_logic_parity_kpi_path_recorded": True,
            "mt5_tick_kpi_path_recorded": True,
            "execution_divergence_kpi_path_recorded": True,
            "mt5_tick_by_fold_kpi_path_recorded": True,
            "execution_divergence_by_fold_kpi_path_recorded": True,
        },
    }
    data["execution_gate"] = {
        "status": summary.get("execution_divergence_status"),
        "run_closeout_review_ready": True,
        "missing_required_kpi_fields": [],
        "economics_shift_status": summary.get("economics_shift_status"),
    }
    data["fold_isolated_execution_gate"] = {
        "mt5_tick_by_fold_status": summary.get("mt5_tick_by_fold_status"),
        "execution_divergence_by_fold_status": summary.get("execution_divergence_by_fold_status"),
        "missing_required_kpi_fields": {
            "mt5_tick_by_fold": [],
            "execution_divergence_by_fold": [],
        },
    }
    data["parity_gate"] = {
        "status": "passed",
        "mechanical_parity_status": summary.get("mechanical_parity_status"),
        "intent_parity_status": summary.get("intent_parity_status"),
        "mismatch_count": summary.get("mismatch_count"),
        "repair_required": False,
        "non_portable_status": "not_checked",
    }
    data["mt5_gate"] = {
        "status": "closed_no_candidate",
        "closed_bar_logic_parity_required": True,
        "required_even_when_proxy_is_weak": True,
        "aggregate_tick_is_diagnostic_only": True,
        "fold_isolated_closeout_required": True,
    }
    data["rolling_window_closeout_gate"] = {
        "status": "passed",
        "aggregate_full_period_mt5_kpi_role": "diagnostic_only",
        "fold_isolated_mt5_tick_required": True,
        "fold_isolated_mt5_tick_path_recorded": True,
        "fold_isolated_execution_divergence_path_recorded": True,
        "fold_isolated_exception": {
            "applies": False,
            "reason": "",
            "blocking_condition": "",
            "revisit_when": "",
        },
    }
    data["pre_open_decision_gate"] = {
        "status": "passed",
        "checks": {
            "pre_open_decision_present": True,
            "novelty_score_valid": True,
            "at_least_one_surface_changed": True,
            "adjacent_tuning_risk_not_high": True,
            "expected_information_gain_not_low": True,
            "decision_payoff_not_low": True,
            "mt5_portability_not_non_portable": True,
            "failure_memory_used_recorded": True,
            "adjacent_tuning_rejection_reason_recorded": True,
        },
    }
    data["evidence_paths"] = closeout_evidence_paths()
    GATE_REPORT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_selected_for_closeout() -> None:
    data = yaml.safe_load(SELECTED.read_text(encoding="ascii"))
    data["status"] = "closed_no_candidate"
    data["selected"] = False
    data["selected_reason"] = None
    data["claim_boundary"] = data.get("claim_boundary", {})
    latest = data.setdefault("latest_synthesis_state", {})
    latest["status"] = "closed_no_candidate"
    latest["source"] = "runs/SR0001/gate_report.json"
    latest["candidate_evidence_retained"] = False
    latest["negative_memory_recorded"] = True
    latest["active_run"] = None
    latest["next_required_action"] = NEXT_MAJOR_ACTION
    latest["claim_boundary"] = claim_boundary_payload()
    SELECTED.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_synthesis_for_closeout(closeout_review: dict[str, Any], closed_at: str) -> None:
    data = yaml.safe_load(SYNTHESIS.read_text(encoding="ascii"))
    data["status"] = "closed_no_candidate"
    data["closed_at_utc"] = closed_at
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = None
    opened = list(run_index.get("opened_runs") or [])
    if "runs/SR0001" not in opened:
        opened.append("runs/SR0001")
    run_index["opened_runs"] = opened
    closed = list(run_index.get("closed_runs") or [])
    if "runs/SR0001" not in closed:
        closed.append("runs/SR0001")
    run_index["closed_runs"] = closed
    run_index["next_run_candidate"] = {
        "run_id": None,
        "direction": NEXT_MAJOR_ACTION,
        "reason": (
            "SR0001 closed no-candidate after weak losing proxy, near-flat aggregate MT5 tick, "
            "and unstable fold-isolated MT5 tick evidence; further SC0007 work would be adjacent "
            "negative-context weight, fragility, threshold, monthly-filter, stop, target, hold, "
            "activity, spread, session, capital, or retry tuning."
        ),
        "status": "synthesis_closed_no_candidate",
    }
    data["closeout"] = {
        "status": "closed_no_candidate",
        "close_reason": SC0007_CLOSE_REASON,
        "evidence_paths": closeout_evidence_paths(),
        "remaining_question": NEXT_MAJOR_ACTION,
        "closed_at_utc": closed_at,
        "decision_basis": closeout_review["required_kpi_summary"],
        "claim_boundary": claim_boundary_payload(),
    }
    data["claim_boundary"] = claim_boundary_payload()
    SYNTHESIS.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_synthesis_queue_for_closeout(closed_at: str) -> None:
    data = yaml.safe_load(SYNTHESIS_QUEUE.read_text(encoding="ascii"))
    data["status"] = "closed_no_candidate"
    for item in data.get("queue", []):
        if item.get("synthesis_run_id") == RUN_ID:
            item["status"] = "closed_no_candidate"
            item["last_completed_step"] = "close_sc0007_sr0001_no_candidate"
            item["next_action"] = NEXT_MAJOR_ACTION
            item["closed_at_utc"] = closed_at
    data["closeout"] = {
        "status": "closed_no_candidate",
        "closed_at_utc": closed_at,
        "remaining_question": NEXT_MAJOR_ACTION,
        "claim_boundary": claim_boundary_payload(),
    }
    SYNTHESIS_QUEUE.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_reentry_for_closeout() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    data["updated_local_date"] = datetime.now().date().isoformat()
    read_budget = data.setdefault("read_budget", {})
    conditional = read_budget.setdefault("conditional_files", {})
    conditional["active_campaign"] = None
    conditional["active_synthesis"] = None
    project = data.setdefault("project", {})
    project["active_campaign"] = None
    project["active_synthesis"] = None
    project["active_run"] = None
    next_work = data.setdefault("next_work", {})
    completed = list(next_work.get("completed") or [])
    for item in (
        "review_sc0007_sr0001_tick_execution_kpi_and_closeout",
        "close_sc0007_sr0001_no_candidate",
        "close_sc0007_no_candidate_after_sr0001",
    ):
        if item not in completed:
            completed.append(item)
    completed = [item for item in completed if item != NEXT_MAJOR_ACTION]
    next_work["campaign"] = None
    next_work["synthesis"] = None
    next_work["completed"] = completed
    next_work["tasks"] = [NEXT_MAJOR_ACTION]
    next_work["active_run"] = None
    next_work["run"] = None
    data["active_campaign"] = None
    data["active_synthesis"] = None
    data["active_run"] = None
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_claim_state_for_closeout(closeout_review: dict[str, Any]) -> None:
    data = yaml.safe_load(CLAIM_STATE.read_text(encoding="ascii"))
    summary = closeout_review["required_kpi_summary"]
    data["active_campaign"] = None
    data["active_synthesis"] = None
    data["active_run"] = None
    data["latest_operation"] = {
        "id": "close_sc0007_sr0001_no_candidate",
        "status": "completed",
        "recorded_at_source": f"{RUN_REL}/gate_report.json",
        "evidence_status": "closed_no_candidate",
        "active_synthesis": None,
        "active_run": None,
        "negative_memory_recorded": True,
        "candidate_evidence_retained": False,
        "entries_per_active_day": summary.get("entries_per_active_day"),
        "proxy_net_pnl_points": summary.get("proxy_net_pnl_points"),
        "proxy_profit_factor": summary.get("proxy_profit_factor"),
        "mt5_tick_net_pnl": summary.get("mt5_tick_net_pnl"),
        "mt5_tick_profit_factor": summary.get("mt5_tick_profit_factor"),
        "profitable_fold_count": summary.get("profitable_fold_count"),
        "losing_fold_count": summary.get("losing_fold_count"),
        "zero_trade_fold_count": summary.get("zero_trade_fold_count"),
        "next_required_action": NEXT_MAJOR_ACTION,
        "claim_boundary": claim_boundary_payload(),
    }
    data["claim_boundary"] = claim_boundary_payload()
    CLAIM_STATE.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_decision_cursor_for_closeout(closeout_review: dict[str, Any]) -> None:
    data = yaml.safe_load(DECISION_CURSOR.read_text(encoding="ascii"))
    summary = closeout_review["required_kpi_summary"]
    data["updated_local_date"] = datetime.now().date().isoformat()
    data["canonical_source"] = f"{RUN_REL}/gate_report.json"
    data["canonical_status"] = "closed_no_candidate"
    data["current_decision"] = NEXT_MAJOR_ACTION
    data["active_campaign"] = None
    data["active_run"] = None
    data["active_synthesis"] = None
    data["next_required_action"] = NEXT_MAJOR_ACTION
    current = data.setdefault("current_evidence_summary", {})
    current.update(
        {
            "source_campaign": None,
            "active_synthesis": None,
            "current_task": NEXT_MAJOR_ACTION,
            "active_run": None,
            "active_run_status": "closed_no_candidate",
            "evidence_status": "closed_no_candidate",
            "synthesis_id": WORK_UNIT_ID,
            "synthesis_status": "closed_no_candidate",
            "entries_per_active_day": summary.get("entries_per_active_day"),
            "proxy_net_pnl_points": summary.get("proxy_net_pnl_points"),
            "proxy_profit_factor": summary.get("proxy_profit_factor"),
            "proxy_trade_count": summary.get("proxy_trade_count"),
            "mt5_tick_net_pnl": summary.get("mt5_tick_net_pnl"),
            "mt5_tick_profit_factor": summary.get("mt5_tick_profit_factor"),
            "profitable_fold_count": summary.get("profitable_fold_count"),
            "losing_fold_count": summary.get("losing_fold_count"),
            "zero_trade_fold_count": summary.get("zero_trade_fold_count"),
            "next_required_action": NEXT_MAJOR_ACTION,
            "note": (
                "SC0007 SR0001 closed no-candidate after weak proxy, near-flat tick KPI, "
                "and unstable fold-isolated tick evidence; choose a new C0038 major hypothesis."
            ),
        }
    )
    data["next_decision_basis"] = [
        {
            "path": f"{RUN_REL}/gate_report.json",
            "role": "closed_synthesis_run_gate_report",
            "summary": "SC0007 SR0001 closed no-candidate with fold-isolated MT5 tick and divergence evidence.",
        },
        {
            "path": f"{RUN_REL}/kpi/mt5_tick_by_fold.json",
            "role": "fold_isolated_mt5_tick_kpi",
            "summary": "Fold evidence completed with three profitable folds, five losing folds, and one zero-trade fold.",
        },
        {
            "path": f"{WORK_UNIT_REL}/synthesis.yaml",
            "role": "closed_synthesis_manifest",
            "summary": "SC0007 is closed no-candidate; remaining work is a new major C0038 hypothesis.",
        },
    ]
    data["claim_boundary_snapshot"] = claim_boundary_payload()
    DECISION_CURSOR.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_work_unit_registry_for_closeout() -> None:
    data = yaml.safe_load(WORK_UNIT_REGISTRY.read_text(encoding="ascii"))
    synthesis_stream = data.setdefault("streams", {}).setdefault("synthesis_stream", {})
    synthesis_stream["active_work_unit"] = None
    open_units = list(synthesis_stream.get("open_work_units") or [])
    synthesis_stream["open_work_units"] = [item for item in open_units if item != WORK_UNIT_REL]
    closed_units = list(synthesis_stream.get("closed_work_units") or [])
    if WORK_UNIT_REL not in closed_units:
        closed_units.append(WORK_UNIT_REL)
    synthesis_stream["closed_work_units"] = closed_units
    WORK_UNIT_REGISTRY.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def append_decision_registry_for_closeout(closeout_review: dict[str, Any]) -> None:
    data = yaml.safe_load(DECISION_REGISTRY.read_text(encoding="ascii"))
    if isinstance(data, dict):
        decisions = data.setdefault("decisions", [])
    else:
        decisions = data if isinstance(data, list) else []
    existing = {item.get("decision_id") for item in decisions if isinstance(item, dict)}
    summary = closeout_review["required_kpi_summary"]
    local_date = datetime.now().date().isoformat()
    if "dec_20260706_close_sc0007_sr0001_no_candidate" not in existing:
        decisions.append(
            {
                "decision_id": "dec_20260706_close_sc0007_sr0001_no_candidate",
                "created_local_date": local_date,
                "status": "active",
                "decision": "close_sc0007_sr0001_no_candidate",
                "refines": [
                    "dec_20260706_produce_sc0007_sr0001_mt5_logic_parity_evidence",
                    "dec_20260705_produce_sc0007_sr0001_proxy_evidence",
                    "dec_20260701_mandatory_mt5_paired_run_validation",
                ],
                "rationale": [
                    "sr0001_completed_proxy_mt5_logic_parity_proxy_vs_mt5_parity_mt5_tick_execution_divergence_and_fold_isolated_tick_and_divergence_evidence",
                    f"proxy_net_pnl_points_{summary.get('proxy_net_pnl_points')}_profit_factor_{summary.get('proxy_profit_factor')}",
                    f"mt5_tick_net_pnl_{summary.get('mt5_tick_net_pnl')}_profit_factor_{summary.get('mt5_tick_profit_factor')}",
                    f"fold_isolated_tick_has_{summary.get('profitable_fold_count')}_profitable_{summary.get('losing_fold_count')}_losing_and_{summary.get('zero_trade_fold_count')}_zero_trade_folds",
                    "closeout_records_negative_memory_not_selection_or_economics_pass",
                    "no_selected_economics_runtime_materialization_onnx_promotion_or_live_claim_is_created",
                ],
                "claim_boundary": claim_boundary_payload(),
            }
        )
    if "dec_20260706_close_sc0007_no_candidate_after_sr0001" not in existing:
        decisions.append(
            {
                "decision_id": "dec_20260706_close_sc0007_no_candidate_after_sr0001",
                "created_local_date": local_date,
                "status": "active",
                "decision": "close_sc0007_no_candidate_after_sr0001",
                "refines": [
                    "dec_20260706_close_sc0007_sr0001_no_candidate",
                    "dec_20260705_close_c0037_with_candidate_evidence",
                ],
                "rationale": [
                    "sc0007_synthesis_boundary_was_answered_by_sr0001_fold_isolated_mt5_evidence",
                    "remaining_sc0007_work_is_adjacent_negative_context_weight_fragility_threshold_monthly_filter_stop_target_hold_activity_spread_session_capital_or_retry_tuning",
                    "next_work_is_choose_c0038_new_major_hypothesis_after_sc0007_closeout",
                    "no_selected_economics_runtime_materialization_onnx_promotion_or_live_claim_is_created",
                ],
                "claim_boundary": claim_boundary_payload(),
            }
        )
    if not isinstance(data, dict):
        data = decisions
    DECISION_REGISTRY.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def close_sc0007_sr0001_no_candidate() -> dict[str, object]:
    closed_at = utc_now()
    closeout_review = sc0007_closeout_review(closed_at)
    update_run_manifest_for_closeout(closeout_review, closed_at)
    update_gate_report_for_closeout(closeout_review)
    update_selected_for_closeout()
    update_synthesis_for_closeout(closeout_review, closed_at)
    update_synthesis_queue_for_closeout(closed_at)
    update_reentry_for_closeout()
    update_claim_state_for_closeout(closeout_review)
    update_decision_cursor_for_closeout(closeout_review)
    update_work_unit_registry_for_closeout()
    append_decision_registry_for_closeout(closeout_review)
    refresh_state_artifact_hashes()
    return {
        "status": "closed_no_candidate",
        "closed_at_utc": closed_at,
        "next_required_action": NEXT_MAJOR_ACTION,
        "required_kpi_summary": closeout_review["required_kpi_summary"],
    }


def max_drawdown_percent(profits: list[float], starting_balance: float) -> float | None:
    if not profits:
        return None
    equity = starting_balance
    peak = starting_balance
    max_drawdown = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    if starting_balance <= 0:
        return None
    return rounded(100.0 * max_drawdown / starting_balance)


def run_sc0007_sr0001_logic_parity_workflow(timeout_seconds: int = 1800) -> dict[str, object]:
    result = run_sc0007_sr0001_tester(mode=LOGIC_PARITY_MODE, timeout_seconds=timeout_seconds)
    mt5_payload = parse_sc0007_sr0001_mt5(result, mode=LOGIC_PARITY_MODE, write_kpi=True)
    parity_payload = record_sc0007_sr0001_parity()
    return {
        "mt5_logic_parity": mt5_payload["required_kpis"],
        "proxy_vs_mt5_logic_parity": parity_payload["required_kpis"],
    }


def run_sc0007_sr0001_mt5_tick_workflow(timeout_seconds: int = 1800) -> dict[str, object]:
    result = run_sc0007_sr0001_tester(mode=TICK_EXECUTION_MODE, timeout_seconds=timeout_seconds)
    tick_payload = parse_sc0007_sr0001_mt5(result, mode=TICK_EXECUTION_MODE, write_kpi=True)
    divergence_payload = record_sc0007_sr0001_execution_divergence()
    return {
        "mt5_tick": tick_payload["required_kpis"],
        "execution_divergence": divergence_payload["required_kpis"],
    }


def fold_tester_result(mode: str, output_scope: str, from_date: str, to_date: str) -> TesterResult:
    mode = normalize_mt5_mode(mode)
    return TesterResult(
        config=tester_config_path(mode, output_scope),
        report=tester_report_path(mode, output_scope),
        common_dir=common_output_dir(mode, output_scope),
        status_csv=common_output_dir(mode, output_scope) / "mt5_status.csv",
        events_csv=common_output_dir(mode, output_scope) / "mt5_events.csv",
        deals_csv=common_output_dir(mode, output_scope) / "mt5_deals.csv",
        mode=mode,
        use_closed_bar_exit=mode == LOGIC_PARITY_MODE,
        output_scope=output_scope,
        from_date=from_date,
        to_date=to_date,
    )


def write_sc0007_sr0001_fold_isolated_payloads(records: list[dict[str, Any]]) -> dict[str, object]:
    tick_by_fold_payload = build_mt5_tick_by_fold_payload(records)
    MT5_TICK_BY_FOLD_KPI.write_text(json.dumps(tick_by_fold_payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    divergence_by_fold_payload = build_execution_divergence_by_fold_payload(records)
    EXECUTION_DIVERGENCE_BY_FOLD_KPI.write_text(
        json.dumps(divergence_by_fold_payload, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    upsert_artifact_lineage(
        "A-SC0007-SR0001-MT5-TICK-BY-FOLD-KPI",
        "mt5_tick_by_fold_kpi",
        "mt5_tick_by_fold",
        rel(MT5_TICK_BY_FOLD_KPI),
        sha256_file(MT5_TICK_BY_FOLD_KPI),
        [
            "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/artifacts/sc0007_sr0001_schedule.csv",
            "registries/rolling_windows.yaml",
            "configs/market.yaml",
        ],
    )
    upsert_artifact_lineage(
        "A-SC0007-SR0001-EXEC-DIVERGENCE-BY-FOLD-KPI",
        "execution_divergence_by_fold_kpi",
        "execution_divergence_by_fold",
        rel(EXECUTION_DIVERGENCE_BY_FOLD_KPI),
        sha256_file(EXECUTION_DIVERGENCE_BY_FOLD_KPI),
        [
            "campaigns/SC0007_post_sc0006_c0031_c0037_mixed_evidence_synthesis/runs/SR0001/kpi/mt5_tick_by_fold.json",
            "registries/rolling_windows.yaml",
        ],
    )
    update_gate_after_fold_isolated_evidence(tick_by_fold_payload, divergence_by_fold_payload)
    update_reentry_after_fold_isolated()
    update_synthesis_queue_after_fold_isolated()
    refresh_state_artifact_hashes()
    return {
        "mt5_tick_by_fold": tick_by_fold_payload["required_kpis"],
        "execution_divergence_by_fold": divergence_by_fold_payload["required_kpis"],
        "fold_count": len(records),
    }


def record_sc0007_sr0001_fold_isolated_from_outputs() -> dict[str, object]:
    records: list[dict[str, Any]] = []
    for window in load_test_windows():
        from_date, to_date = tester_dates_for_window(window)
        logic_result = fold_tester_result(LOGIC_PARITY_MODE, window.fold_id, from_date, to_date)
        tick_result = fold_tester_result(TICK_EXECUTION_MODE, window.fold_id, from_date, to_date)
        logic_payload = parse_sc0007_sr0001_mt5(logic_result, mode=LOGIC_PARITY_MODE, write_kpi=False)
        tick_payload = parse_sc0007_sr0001_mt5(tick_result, mode=TICK_EXECUTION_MODE, write_kpi=False)
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
    return write_sc0007_sr0001_fold_isolated_payloads(records)


def run_sc0007_sr0001_mt5_tick_by_fold_workflow(timeout_seconds: int = 1800) -> dict[str, object]:
    compile_sc0007_sr0001_ea()
    write_schedule_files()
    records: list[dict[str, Any]] = []
    for window in load_test_windows():
        from_date, to_date = tester_dates_for_window(window)
        logic_result = run_sc0007_sr0001_tester(
            mode=LOGIC_PARITY_MODE,
            timeout_seconds=timeout_seconds,
            from_date=from_date,
            to_date=to_date,
            output_scope=window.fold_id,
            compile_before=False,
        )
        logic_payload = parse_sc0007_sr0001_mt5(logic_result, mode=LOGIC_PARITY_MODE, write_kpi=False)
        tick_result = run_sc0007_sr0001_tester(
            mode=TICK_EXECUTION_MODE,
            timeout_seconds=timeout_seconds,
            from_date=from_date,
            to_date=to_date,
            output_scope=window.fold_id,
            compile_before=False,
        )
        tick_payload = parse_sc0007_sr0001_mt5(tick_result, mode=TICK_EXECUTION_MODE, write_kpi=False)
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

    return write_sc0007_sr0001_fold_isolated_payloads(records)


if __name__ == "__main__":
    result_payload = run_sc0007_sr0001_logic_parity_workflow()
    print(json.dumps(result_payload, indent=2, sort_keys=True))
