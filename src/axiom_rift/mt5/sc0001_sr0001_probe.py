"""MT5 schedule-replay logic parity helpers for SC0001 SR0001."""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from axiom_rift.collectors.mt5_fresh_export import (
    DEFAULT_METAEDITOR_EXE,
    DEFAULT_TERMINAL_EXE,
    rel,
    sha256_file,
    terminal_data_dir,
)
from axiom_rift.mt5.c0002_r0004_probe import (
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
    fold_summary,
    int_delta,
    kpi_float,
    kpi_int,
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
from axiom_rift.mt5.r0007_probe import CompileResult, TesterResult
from axiom_rift.mt5.terminal_hygiene import cleanup_headless_terminal, prepare_headless_terminal
from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies.sc0001_sr0001_synthesis_constraints import BASE_FRAME, TIME_FORMAT, load_bars


EA_NAME = "AxiomC0002ScheduleReplay"
EA_SOURCE = PROJECT_ROOT / "src" / "axiom_rift" / "mt5" / "experts" / f"{EA_NAME}.mq5"
WORK_UNIT_ID = "SC0001"
RUN_ID = "SR0001"
RUN_DIR = PROJECT_ROOT / "campaigns" / "SC0001_accumulated_negative_memory_synthesis" / "runs" / RUN_ID
SYNTHESIS_QUEUE = PROJECT_ROOT / "campaigns" / "SC0001_accumulated_negative_memory_synthesis" / "synthesis_queue.yaml"
KPI_DIR = RUN_DIR / "kpi"
RUN_ARTIFACT_DIR = RUN_DIR / "artifacts"
MT5_LOGIC_KPI = KPI_DIR / "mt5_logic_parity.json"
MT5_TICK_KPI = KPI_DIR / "mt5_tick.json"
LOGIC_PARITY_KPI = KPI_DIR / "proxy_vs_mt5_logic_parity.json"
EXECUTION_DIVERGENCE_KPI = KPI_DIR / "execution_divergence.json"
RUN_MANIFEST = RUN_DIR / "run_manifest.json"
GATE_REPORT = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE = RUN_DIR / "artifact_lineage.json"
PROXY_TRADE_ARTIFACT = RUN_ARTIFACT_DIR / "sc0001_sr0001_proxy_trades.csv"
SCHEDULE_ARTIFACT = RUN_ARTIFACT_DIR / "sc0001_sr0001_schedule.csv"
SCHEDULE_COMMON_REL = "AxiomRift\\SC0001\\SR0001\\schedule\\sc0001_sr0001_schedule.csv"
STARTING_BALANCE_USD = 500.0
RESPONSE_MODE = "negative_memory_constraint_schedule_replay"
MAX_HOLD_BARS = 7
MAGIC = 910001
TESTER_FROM_DATE = "2024.02.01"
TESTER_TO_DATE = "2026.05.01"


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


def compile_sc0001_sr0001_ea(metaeditor_exe: Path = DEFAULT_METAEDITOR_EXE) -> CompileResult:
    if not metaeditor_exe.exists():
        raise FileNotFoundError(f"MetaEditor not found: {metaeditor_exe}")
    target_dir = terminal_data_dir() / "MQL5" / "Experts" / "AxiomRift"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / EA_SOURCE.name
    shutil.copy2(EA_SOURCE, target)
    log = PROJECT_ROOT / "artifacts" / "reports" / "SC0001_SR0001_mt5_compile.log"
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
    return PROJECT_ROOT / "artifacts" / "reports" / "SC0001_SR0001_mt5_tester" / f"SC0001_SR0001_{suffix}_tester.ini"


def tester_report_path(mode: str = LOGIC_PARITY_MODE, output_scope: str | None = None) -> Path:
    mode = normalize_mt5_mode(mode)
    output_scope = normalize_output_scope(output_scope)
    suffix = mode if output_scope is None else f"{mode}_{output_scope}"
    return PROJECT_ROOT / "artifacts" / "reports" / "SC0001_SR0001_mt5_tester" / f"SC0001_SR0001_mt5_{suffix}_report.htm"


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
    bars = load_bars(BASE_FRAME)
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
        model = 2 if mode == LOGIC_PARITY_MODE else 4
    use_closed_bar_exit = mode == LOGIC_PARITY_MODE
    config_dir = PROJECT_ROOT / "artifacts" / "reports" / "SC0001_SR0001_mt5_tester"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = tester_config_path(mode, output_scope)
    report = tester_report_stem(mode, output_scope)
    lines = [
        "[Tester]",
        "Expert=AxiomRift\\AxiomC0002ScheduleReplay",
        "Symbol=US100",
        "Period=M5",
        f"Model={model}",
        f"FromDate={from_date}",
        f"ToDate={to_date}",
        "ForwardMode=0",
        "Deposit=500",
        "Currency=USD",
        "Leverage=100",
        "ExecutionMode=0",
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
        "InpLot=0.01",
        f"InpMaxHoldBars={MAX_HOLD_BARS}",
        "InpUseCommonFiles=true",
        f"InpUseClosedBarExit={bool_text(use_closed_bar_exit)}",
        "",
    ]
    config.write_text("\n".join(lines), encoding="ascii")
    return config


def run_sc0001_sr0001_tester(
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
        compile_sc0001_sr0001_ea()
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
            [str(DEFAULT_TERMINAL_EXE), f"/config:{config}"],
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


def parse_sc0001_sr0001_mt5(
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
            "A-SC0001-SR0001-MT5-SCHEDULE",
            "mt5_schedule_csv",
            "mt5_logic_parity_input",
            rel(SCHEDULE_ARTIFACT),
            sha256_file(SCHEDULE_ARTIFACT),
            ["campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/kpi/proxy.json"],
        )
        upsert_artifact_lineage(
            "A-SC0001-SR0001-MT5-LOGIC-KPI",
            "mt5_logic_parity_kpi",
            "mt5_logic_parity",
            rel(MT5_LOGIC_KPI),
            sha256_file(MT5_LOGIC_KPI),
            [
                "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/artifacts/sc0001_sr0001_schedule.csv",
                "configs/market.yaml",
            ],
        )
    else:
        upsert_artifact_lineage(
            "A-SC0001-SR0001-MT5-TICK-KPI",
            "mt5_tick_kpi",
            "mt5_tick",
            rel(MT5_TICK_KPI),
            sha256_file(MT5_TICK_KPI),
            [
                "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/artifacts/sc0001_sr0001_schedule.csv",
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
        "mt5_probe_id": "MT5-SC0001-SR0001",
        "mt5_kpi_family": family,
        "mt5_execution_mode": mode_label,
        "mt5_output_scope": result.output_scope,
        "mt5_terminal_identity": terminal_data_dir().as_posix(),
        "mt5_symbol": "US100",
        "mt5_timeframe": "M5",
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
                    "logic_boundary": "proxy_selected_negative_memory_constraint_schedule_replayed_in_mt5_closed_bar_mode"
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
                "field": "native_mql_negative_memory_constraint_logic",
                "requirement_class": "deferred_with_reason",
                "reason": "SC0001 SR0001 replays the proxy schedule in MT5; native model or ONNX materialization is not claimed",
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


def record_sc0001_sr0001_parity() -> dict[str, object]:
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
        "produce_sc0001_sr0001_mt5_tick_execution_evidence"
        if mechanical_ok
        else "repair_sc0001_sr0001_schedule_replay_parity"
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
        "parity_id": "P-SC0001-SR0001",
        "proxy_id": "PX-SC0001-SR0001",
        "mt5_probe_id": "MT5-SC0001-SR0001",
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
            "constraint_schedule_exit_match": "passed" if exit_compare["reason_match_rate"] == 1.0 else "failed",
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
                    "logic_boundary": "proxy_selected_negative_memory_constraint_schedule_replayed_in_mt5_closed_bar_mode",
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
                "reason": "logic parity uses schedule replay only; native synthesis constraint materialization is deferred until candidate quality exists",
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
        "A-SC0001-SR0001-PARITY-KPI",
        "proxy_vs_mt5_logic_parity_kpi",
        "proxy_vs_mt5_logic_parity",
        rel(LOGIC_PARITY_KPI),
        sha256_file(LOGIC_PARITY_KPI),
        [
            "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/kpi/proxy.json",
            "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/kpi/mt5_logic_parity.json",
        ],
    )
    update_gate_after_logic_parity(payload, next_action, mechanical_ok)
    update_reentry_after_logic_parity(next_action)
    update_synthesis_queue_after_logic_parity(next_action, mechanical_ok)
    return payload


def update_run_after_mt5(mode: str) -> None:
    mode = normalize_mt5_mode(mode)
    data = json.loads(RUN_MANIFEST.read_text(encoding="ascii"))
    evidence_paths = data.setdefault("evidence_paths", {})
    evidence_paths["mt5_logic_parity_kpi"] = "kpi/mt5_logic_parity.json"
    evidence_paths["proxy_vs_mt5_logic_parity_kpi"] = "kpi/proxy_vs_mt5_logic_parity.json"
    evidence_paths["mt5_schedule_artifact"] = "artifacts/sc0001_sr0001_schedule.csv"
    mt5_plan = data.setdefault("mt5_probe_plan", {})
    mt5_plan["logic_parity_kpi_path"] = "kpi/mt5_logic_parity.json"
    mt5_plan["logic_parity_purpose"] = "proxy_selected_negative_memory_constraint_schedule_vs_ea_closed_bar_lifecycle_parity"
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


def update_gate_after_logic_parity(payload: dict[str, object], next_action: str, mechanical_ok: bool) -> None:
    data = json.loads(GATE_REPORT.read_text(encoding="ascii"))
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
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in ("kpi/mt5_logic_parity.json", "kpi/proxy_vs_mt5_logic_parity.json", "artifacts/sc0001_sr0001_schedule.csv"):
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
        "produce_sc0001_sr0001_mt5_logic_parity_evidence",
        "record_sc0001_sr0001_proxy_vs_mt5_logic_parity_evidence",
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
            item["last_completed_step"] = "produce_sc0001_sr0001_mt5_logic_parity_evidence"
            item["next_action"] = next_action
    SYNTHESIS_QUEUE.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def record_sc0001_sr0001_execution_divergence() -> dict[str, object]:
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
        "divergence_id": "ED-SC0001-SR0001",
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
                    "risk_shape_source": "proxy_negative_memory_constraint_schedule",
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
                "revisit_when": "after SC0001 SR0001 fold-isolated MT5 tick evidence",
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
        "A-SC0001-SR0001-EXEC-DIVERGENCE-KPI",
        "execution_divergence_kpi",
        "execution_divergence",
        rel(EXECUTION_DIVERGENCE_KPI),
        sha256_file(EXECUTION_DIVERGENCE_KPI),
        [
            "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/kpi/mt5_logic_parity.json",
            "campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/kpi/mt5_tick.json",
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
    data["next_action"] = "produce_sc0001_sr0001_fold_isolated_mt5_tick_kpi"
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
            "revisit_when": "produce_sc0001_sr0001_fold_isolated_mt5_tick_kpi",
        }
    ]
    GATE_REPORT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_reentry_after_execution_divergence() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    next_work = data.setdefault("next_work", {})
    completed = list(next_work.get("completed") or [])
    for item in (
        "produce_sc0001_sr0001_mt5_tick_execution_evidence",
        "record_sc0001_sr0001_execution_divergence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_sc0001_sr0001_fold_isolated_mt5_tick_kpi"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_synthesis_queue_after_execution_divergence() -> None:
    data = yaml.safe_load(SYNTHESIS_QUEUE.read_text(encoding="ascii"))
    for item in data.get("queue", []):
        if item.get("synthesis_run_id") == RUN_ID:
            item["status"] = "execution_divergence_done"
            item["last_completed_step"] = "record_sc0001_sr0001_execution_divergence"
            item["next_action"] = "produce_sc0001_sr0001_fold_isolated_mt5_tick_kpi"
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
            "produced_by": "axiom_rift.mt5.sc0001_sr0001_probe",
            "source_inputs": source_inputs,
            "linked_kpi_family": artifact_role,
            "mutable": False,
            "claim_authority": False,
        }
    )
    data["artifact_records"] = records
    deferred_next_action = (
        "produce_sc0001_sr0001_fold_isolated_mt5_tick_kpi"
        if EXECUTION_DIVERGENCE_KPI.exists()
        else "produce_sc0001_sr0001_mt5_tick_execution_evidence"
    )
    data["deferred_with_reason"] = [
        {
            "field": "fold_isolated_artifact_hashes" if EXECUTION_DIVERGENCE_KPI.exists() else "mt5_tick_artifact_hashes",
            "reason": "fold-isolated tick and divergence artifacts are produced after aggregate tick execution"
            if EXECUTION_DIVERGENCE_KPI.exists()
            else "tick execution artifacts are produced after closed-bar logic parity",
            "next_action": deferred_next_action,
        }
    ]
    ARTIFACT_LINEAGE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


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


def run_sc0001_sr0001_logic_parity_workflow(timeout_seconds: int = 1800) -> dict[str, object]:
    result = run_sc0001_sr0001_tester(mode=LOGIC_PARITY_MODE, timeout_seconds=timeout_seconds)
    mt5_payload = parse_sc0001_sr0001_mt5(result, mode=LOGIC_PARITY_MODE, write_kpi=True)
    parity_payload = record_sc0001_sr0001_parity()
    return {
        "mt5_logic_parity": mt5_payload["required_kpis"],
        "proxy_vs_mt5_logic_parity": parity_payload["required_kpis"],
    }


def run_sc0001_sr0001_mt5_tick_workflow(timeout_seconds: int = 1800) -> dict[str, object]:
    result = run_sc0001_sr0001_tester(mode=TICK_EXECUTION_MODE, timeout_seconds=timeout_seconds)
    tick_payload = parse_sc0001_sr0001_mt5(result, mode=TICK_EXECUTION_MODE, write_kpi=True)
    divergence_payload = record_sc0001_sr0001_execution_divergence()
    return {
        "mt5_tick": tick_payload["required_kpis"],
        "execution_divergence": divergence_payload["required_kpis"],
    }


if __name__ == "__main__":
    result_payload = run_sc0001_sr0001_logic_parity_workflow()
    print(json.dumps(result_payload, indent=2, sort_keys=True))
