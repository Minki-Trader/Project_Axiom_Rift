"""Small command line entrypoint for workspace checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .collectors.mt5_fresh_export import run_terminal_export
from .paths import CAMPAIGN_DIR, CONFIG_DIR, CONTRACT_DIR, PROJECT_ROOT, REGISTRY_DIR
from .pipelines.base_frame import build_us100_m5_base_frame
from .pipelines.clean_periods import derive_clean_periods
from .pipelines.rolling_windows import build_rolling_windows
from .mt5.r0001_probe import (
    LOGIC_PARITY_MODE,
    TICK_EXECUTION_MODE,
    compile_r0001_ea,
    parse_r0001_mt5,
    record_r0001_execution_divergence,
    record_r0001_parity,
    run_r0001_mt5_logic_workflow,
    run_r0001_mt5_tick_by_fold_workflow,
    run_r0001_mt5_tick_workflow,
)
from .mt5.r0002_probe import (
    compile_r0002_ea,
    parse_r0002_mt5,
    record_r0002_execution_divergence,
    record_r0002_parity,
    run_r0002_mt5_logic_workflow,
    run_r0002_mt5_tick_by_fold_workflow,
    run_r0002_mt5_tick_workflow,
)
from .mt5.r0003_probe import (
    compile_r0003_ea,
    parse_r0003_mt5,
    record_r0003_execution_divergence,
    record_r0003_parity,
    run_r0003_mt5_logic_workflow,
    run_r0003_mt5_tick_by_fold_workflow,
    run_r0003_mt5_tick_workflow,
)
from .mt5.r0004_probe import (
    compile_r0004_ea,
    parse_r0004_mt5,
    record_r0004_execution_divergence,
    record_r0004_parity,
    run_r0004_mt5_logic_workflow,
    run_r0004_mt5_tick_by_fold_workflow,
    run_r0004_mt5_tick_workflow,
)
from .mt5.r0005_probe import (
    compile_r0005_ea,
    parse_r0005_mt5,
    record_r0005_execution_divergence,
    record_r0005_parity,
    run_r0005_mt5_logic_workflow,
    run_r0005_mt5_tick_by_fold_workflow,
    run_r0005_mt5_tick_workflow,
)
from .mt5.r0006_probe import (
    compile_r0006_ea,
    parse_r0006_mt5,
    record_r0006_execution_divergence,
    record_r0006_parity,
    run_r0006_mt5_logic_workflow,
    run_r0006_mt5_tick_by_fold_workflow,
    run_r0006_mt5_tick_workflow,
)
from .mt5.r0007_probe import (
    compile_r0007_ea,
    parse_r0007_mt5,
    record_r0007_execution_divergence,
    record_r0007_parity,
    run_r0007_mt5_logic_workflow,
    run_r0007_mt5_tick_by_fold_workflow,
    run_r0007_mt5_tick_workflow,
)
from .mt5.c0002_r0001_probe import (
    compile_c0002_r0001_ea,
    parse_c0002_r0001_mt5,
    record_c0002_r0001_execution_divergence,
    record_c0002_r0001_parity,
    run_c0002_r0001_mt5_logic_workflow,
    run_c0002_r0001_mt5_tick_by_fold_workflow,
    run_c0002_r0001_mt5_tick_workflow,
)
from .mt5.c0002_r0002_probe import (
    compile_c0002_r0002_ea,
    parse_c0002_r0002_mt5,
    record_c0002_r0002_execution_divergence,
    record_c0002_r0002_parity,
    run_c0002_r0002_mt5_logic_workflow,
    run_c0002_r0002_mt5_tick_by_fold_workflow,
    run_c0002_r0002_mt5_tick_workflow,
)
from .mt5.c0002_r0003_probe import (
    compile_c0002_r0003_ea,
    parse_c0002_r0003_mt5,
    record_c0002_r0003_execution_divergence,
    record_c0002_r0003_parity,
    run_c0002_r0003_mt5_logic_workflow,
    run_c0002_r0003_mt5_tick_by_fold_workflow,
    run_c0002_r0003_mt5_tick_workflow,
)
from .mt5.c0002_r0004_probe import (
    compile_c0002_r0004_ea,
    parse_c0002_r0004_mt5,
    record_c0002_r0004_execution_divergence,
    record_c0002_r0004_parity,
    run_c0002_r0004_mt5_logic_workflow,
    run_c0002_r0004_mt5_tick_by_fold_workflow,
    run_c0002_r0004_mt5_tick_workflow,
)
from .mt5.sc0001_sr0001_probe import (
    compile_sc0001_sr0001_ea,
    parse_sc0001_sr0001_mt5,
    record_sc0001_sr0001_execution_divergence,
    record_sc0001_sr0001_parity,
    run_sc0001_sr0001_logic_parity_workflow,
    run_sc0001_sr0001_mt5_tick_by_fold_workflow,
    run_sc0001_sr0001_mt5_tick_workflow,
)
from .mt5.c0004_r0001_probe import (
    compile_c0004_r0001_ea,
    parse_c0004_r0001_mt5,
    record_c0004_r0001_execution_divergence,
    record_c0004_r0001_parity,
    run_c0004_r0001_mt5_logic_workflow,
    run_c0004_r0001_mt5_tick_by_fold_workflow,
    run_c0004_r0001_mt5_tick_workflow,
)
from .mt5.c0004_r0002_probe import (
    compile_c0004_r0002_ea,
    parse_c0004_r0002_mt5,
    record_c0004_r0002_execution_divergence,
    record_c0004_r0002_parity,
    run_c0004_r0002_mt5_logic_workflow,
    run_c0004_r0002_mt5_tick_by_fold_workflow,
    run_c0004_r0002_mt5_tick_workflow,
)
from .mt5.c0004_r0003_probe import (
    compile_c0004_r0003_ea,
    parse_c0004_r0003_mt5,
    record_c0004_r0003_execution_divergence,
    record_c0004_r0003_parity,
    run_c0004_r0003_mt5_logic_workflow,
    run_c0004_r0003_mt5_tick_by_fold_workflow,
    run_c0004_r0003_mt5_tick_workflow,
)
from .mt5.c0004_r0004_probe import (
    compile_c0004_r0004_ea,
    parse_c0004_r0004_mt5,
    record_c0004_r0004_execution_divergence,
    record_c0004_r0004_parity,
    run_c0004_r0004_mt5_logic_workflow,
    run_c0004_r0004_mt5_tick_by_fold_workflow,
    run_c0004_r0004_mt5_tick_workflow,
)
from .mt5.c0005_r0001_probe import (
    compile_c0005_r0001_ea,
    parse_c0005_r0001_mt5,
    record_c0005_r0001_execution_divergence,
    record_c0005_r0001_parity,
    run_c0005_r0001_mt5_logic_workflow,
    run_c0005_r0001_mt5_tick_by_fold_workflow,
    run_c0005_r0001_mt5_tick_workflow,
)
from .mt5.c0005_r0002_probe import (
    compile_c0005_r0002_ea,
    parse_c0005_r0002_mt5,
    record_c0005_r0002_execution_divergence,
    record_c0005_r0002_parity,
    run_c0005_r0002_mt5_logic_workflow,
    run_c0005_r0002_mt5_tick_by_fold_workflow,
    run_c0005_r0002_mt5_tick_workflow,
)
from .proxies.r0001_volatility_expansion import run_r0001_proxy
from .proxies.r0002_failed_continuation_reversal import run_r0002_proxy
from .proxies.r0003_failed_breakout_reclaim_reversal import run_r0003_proxy
from .proxies.r0004_compression_breakout_continuation import run_r0004_proxy
from .proxies.r0005_expansion_exhaustion_reversal import run_r0005_proxy
from .proxies.r0006_compression_breakout_reversal import run_r0006_proxy
from .proxies.r0007_core_session_expansion_continuation import run_r0007_proxy
from .proxies.c0002_r0001_score_conditioned import run_c0002_r0001_proxy
from .proxies.c0002_r0002_exhaustion_reversal import run_c0002_r0002_proxy
from .proxies.c0002_r0003_dual_direction_cell_score import run_c0002_r0003_proxy
from .proxies.c0002_r0004_stump_rank_ensemble import run_c0002_r0004_proxy
from .proxies.c0004_r0001_fold_local_state_archetype import run_c0004_r0001_proxy
from .proxies.c0004_r0002_path_quality_archetype import run_c0004_r0002_proxy
from .proxies.c0004_r0003_adverse_archetype_inversion import run_c0004_r0003_proxy
from .proxies.c0004_r0004_temporal_stability_archetype import run_c0004_r0004_proxy
from .proxies.c0005_r0001_continuous_analog_memory import run_c0005_r0001_proxy
from .proxies.c0005_r0002_directional_contrast_analog_memory import run_c0005_r0002_proxy
from .proxies.sc0001_sr0001_synthesis_constraints import run_sc0001_sr0001_proxy
from .validation.work_units import result_json, validate_templates, validate_work_unit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="axiom-rift")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="print key workspace paths as JSON")
    export_parser = subparsers.add_parser("export-mt5-max-bars", help="fresh-export max MT5 bars")
    export_parser.add_argument("--symbol", default="US100")
    export_parser.add_argument("--timeframe", default="M5")
    export_parser.add_argument("--timeout-seconds", type=int, default=240)
    subparsers.add_parser("build-us100-base-frame", help="build US100 M5 base frame from raw CSV")
    subparsers.add_parser("derive-us100-clean-periods", help="derive clean period candidates")
    subparsers.add_parser("build-us100-rolling-windows", help="build rolling-window split registry")
    r0001_proxy_parser = subparsers.add_parser("run-r0001-proxy", help="run R0001 proxy evidence")
    r0001_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-r0001-ea", help="compile R0001 MT5 EA")
    r0001_mt5_logic_parser = subparsers.add_parser("run-r0001-mt5-logic", help="run R0001 MT5 closed-bar logic parity workflow")
    r0001_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    r0001_mt5_tick_parser = subparsers.add_parser("run-r0001-mt5-tick", help="run R0001 MT5 tick execution KPI workflow")
    r0001_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    r0001_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-r0001-mt5-tick-by-fold",
        help="run R0001 fold-isolated MT5 tick KPI and divergence workflow",
    )
    r0001_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_r0001_mt5_parser = subparsers.add_parser("parse-r0001-mt5", help="parse existing R0001 MT5 output files")
    parse_r0001_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-r0001-parity", help="record R0001 proxy-vs-MT5 parity from parsed outputs")
    subparsers.add_parser("record-r0001-execution-divergence", help="record R0001 closed-bar-vs-tick execution divergence")
    r0002_proxy_parser = subparsers.add_parser("run-r0002-proxy", help="run R0002 failed-continuation reversal proxy evidence")
    r0002_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-r0002-ea", help="compile shared MT5 EA for R0002 reversal mode")
    r0002_mt5_logic_parser = subparsers.add_parser("run-r0002-mt5-logic", help="run R0002 MT5 closed-bar logic parity workflow")
    r0002_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    r0002_mt5_tick_parser = subparsers.add_parser("run-r0002-mt5-tick", help="run R0002 MT5 tick execution KPI workflow")
    r0002_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    r0002_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-r0002-mt5-tick-by-fold",
        help="run R0002 fold-isolated MT5 tick KPI and divergence workflow",
    )
    r0002_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_r0002_mt5_parser = subparsers.add_parser("parse-r0002-mt5", help="parse existing R0002 MT5 output files")
    parse_r0002_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-r0002-parity", help="record R0002 proxy-vs-MT5 parity from parsed outputs")
    subparsers.add_parser("record-r0002-execution-divergence", help="record R0002 closed-bar-vs-tick execution divergence")
    r0003_proxy_parser = subparsers.add_parser("run-r0003-proxy", help="run R0003 failed-breakout reclaim reversal proxy evidence")
    r0003_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-r0003-ea", help="compile shared MT5 EA for R0003 failed-breakout reclaim mode")
    r0003_mt5_logic_parser = subparsers.add_parser("run-r0003-mt5-logic", help="run R0003 MT5 closed-bar logic parity workflow")
    r0003_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    r0003_mt5_tick_parser = subparsers.add_parser("run-r0003-mt5-tick", help="run R0003 MT5 tick execution KPI workflow")
    r0003_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    r0003_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-r0003-mt5-tick-by-fold",
        help="run R0003 fold-isolated MT5 tick KPI and divergence workflow",
    )
    r0003_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_r0003_mt5_parser = subparsers.add_parser("parse-r0003-mt5", help="parse existing R0003 MT5 output files")
    parse_r0003_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-r0003-parity", help="record R0003 proxy-vs-MT5 parity from parsed outputs")
    subparsers.add_parser("record-r0003-execution-divergence", help="record R0003 closed-bar-vs-tick execution divergence")
    r0004_proxy_parser = subparsers.add_parser("run-r0004-proxy", help="run R0004 compression-breakout continuation proxy evidence")
    r0004_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-r0004-ea", help="compile shared MT5 EA for R0004 compression-breakout mode")
    r0004_mt5_logic_parser = subparsers.add_parser("run-r0004-mt5-logic", help="run R0004 MT5 closed-bar logic parity workflow")
    r0004_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    r0004_mt5_tick_parser = subparsers.add_parser("run-r0004-mt5-tick", help="run R0004 MT5 tick execution KPI workflow")
    r0004_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    r0004_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-r0004-mt5-tick-by-fold",
        help="run R0004 fold-isolated MT5 tick KPI and divergence workflow",
    )
    r0004_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_r0004_mt5_parser = subparsers.add_parser("parse-r0004-mt5", help="parse existing R0004 MT5 output files")
    parse_r0004_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-r0004-parity", help="record R0004 proxy-vs-MT5 parity from parsed outputs")
    subparsers.add_parser("record-r0004-execution-divergence", help="record R0004 closed-bar-vs-tick execution divergence")
    r0005_proxy_parser = subparsers.add_parser("run-r0005-proxy", help="run R0005 expansion-exhaustion reversal proxy evidence")
    r0005_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-r0005-ea", help="compile shared MT5 EA for R0005 expansion-exhaustion reversal mode")
    r0005_mt5_logic_parser = subparsers.add_parser("run-r0005-mt5-logic", help="run R0005 MT5 closed-bar logic parity workflow")
    r0005_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    r0005_mt5_tick_parser = subparsers.add_parser("run-r0005-mt5-tick", help="run R0005 MT5 tick execution KPI workflow")
    r0005_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    r0005_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-r0005-mt5-tick-by-fold",
        help="run R0005 fold-isolated MT5 tick KPI and divergence workflow",
    )
    r0005_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_r0005_mt5_parser = subparsers.add_parser("parse-r0005-mt5", help="parse existing R0005 MT5 output files")
    parse_r0005_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-r0005-parity", help="record R0005 proxy-vs-MT5 parity from parsed outputs")
    subparsers.add_parser("record-r0005-execution-divergence", help="record R0005 closed-bar-vs-tick execution divergence")
    r0006_proxy_parser = subparsers.add_parser("run-r0006-proxy", help="run R0006 compression-breakout reversal proxy evidence")
    r0006_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-r0006-ea", help="compile shared MT5 EA for R0006 compression-breakout reversal mode")
    r0006_mt5_logic_parser = subparsers.add_parser("run-r0006-mt5-logic", help="run R0006 MT5 closed-bar logic parity workflow")
    r0006_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    r0006_mt5_tick_parser = subparsers.add_parser("run-r0006-mt5-tick", help="run R0006 MT5 tick execution KPI workflow")
    r0006_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    r0006_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-r0006-mt5-tick-by-fold",
        help="run R0006 fold-isolated MT5 tick KPI and divergence workflow",
    )
    r0006_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_r0006_mt5_parser = subparsers.add_parser("parse-r0006-mt5", help="parse existing R0006 MT5 output files")
    parse_r0006_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-r0006-parity", help="record R0006 proxy-vs-MT5 parity from parsed outputs")
    subparsers.add_parser("record-r0006-execution-divergence", help="record R0006 closed-bar-vs-tick execution divergence")
    r0007_proxy_parser = subparsers.add_parser("run-r0007-proxy", help="run R0007 core-session expansion continuation proxy evidence")
    r0007_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-r0007-ea", help="compile shared MT5 EA for R0007 core-session expansion continuation mode")
    r0007_mt5_logic_parser = subparsers.add_parser("run-r0007-mt5-logic", help="run R0007 MT5 closed-bar logic parity workflow")
    r0007_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    r0007_mt5_tick_parser = subparsers.add_parser("run-r0007-mt5-tick", help="run R0007 MT5 tick execution KPI workflow")
    r0007_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    r0007_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-r0007-mt5-tick-by-fold",
        help="run R0007 fold-isolated MT5 tick KPI and divergence workflow",
    )
    r0007_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_r0007_mt5_parser = subparsers.add_parser("parse-r0007-mt5", help="parse existing R0007 MT5 output files")
    parse_r0007_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-r0007-parity", help="record R0007 proxy-vs-MT5 parity from parsed outputs")
    subparsers.add_parser("record-r0007-execution-divergence", help="record R0007 closed-bar-vs-tick execution divergence")
    c0002_r0001_proxy_parser = subparsers.add_parser(
        "run-c0002-r0001-proxy",
        help="run C0002 R0001 score-conditioned candidate-selection proxy evidence",
    )
    c0002_r0001_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-c0002-r0001-ea", help="compile C0002 R0001 MT5 schedule-replay EA")
    c0002_r0001_mt5_logic_parser = subparsers.add_parser(
        "run-c0002-r0001-mt5-logic",
        help="run C0002 R0001 MT5 closed-bar logic parity workflow",
    )
    c0002_r0001_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0002_r0001_mt5_tick_parser = subparsers.add_parser(
        "run-c0002-r0001-mt5-tick",
        help="run C0002 R0001 MT5 tick execution KPI workflow",
    )
    c0002_r0001_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0002_r0001_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-c0002-r0001-mt5-tick-by-fold",
        help="run C0002 R0001 fold-isolated MT5 tick KPI and divergence workflow",
    )
    c0002_r0001_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_c0002_r0001_mt5_parser = subparsers.add_parser(
        "parse-c0002-r0001-mt5",
        help="parse existing C0002 R0001 MT5 output files",
    )
    parse_c0002_r0001_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-c0002-r0001-parity", help="record C0002 R0001 proxy-vs-MT5 logic parity")
    subparsers.add_parser(
        "record-c0002-r0001-execution-divergence",
        help="record C0002 R0001 closed-bar-vs-tick execution divergence",
    )
    c0002_r0002_proxy_parser = subparsers.add_parser(
        "run-c0002-r0002-proxy",
        help="run C0002 R0002 score-conditioned exhaustion-reversal proxy evidence",
    )
    c0002_r0002_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-c0002-r0002-ea", help="compile C0002 generic MT5 schedule-replay EA for R0002")
    c0002_r0002_mt5_logic_parser = subparsers.add_parser(
        "run-c0002-r0002-mt5-logic",
        help="run C0002 R0002 MT5 closed-bar logic parity workflow",
    )
    c0002_r0002_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0002_r0002_mt5_tick_parser = subparsers.add_parser(
        "run-c0002-r0002-mt5-tick",
        help="run C0002 R0002 MT5 tick execution KPI workflow",
    )
    c0002_r0002_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0002_r0002_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-c0002-r0002-mt5-tick-by-fold",
        help="run C0002 R0002 fold-isolated MT5 tick KPI and divergence workflow",
    )
    c0002_r0002_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_c0002_r0002_mt5_parser = subparsers.add_parser(
        "parse-c0002-r0002-mt5",
        help="parse existing C0002 R0002 MT5 output files",
    )
    parse_c0002_r0002_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-c0002-r0002-parity", help="record C0002 R0002 proxy-vs-MT5 logic parity")
    subparsers.add_parser(
        "record-c0002-r0002-execution-divergence",
        help="record C0002 R0002 closed-bar-vs-tick execution divergence",
    )
    c0002_r0003_proxy_parser = subparsers.add_parser(
        "run-c0002-r0003-proxy",
        help="run C0002 R0003 dual-direction cell-score proxy evidence",
    )
    c0002_r0003_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-c0002-r0003-ea", help="compile C0002 generic MT5 schedule-replay EA for R0003")
    c0002_r0003_mt5_logic_parser = subparsers.add_parser(
        "run-c0002-r0003-mt5-logic",
        help="run C0002 R0003 MT5 closed-bar logic parity workflow",
    )
    c0002_r0003_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0002_r0003_mt5_tick_parser = subparsers.add_parser(
        "run-c0002-r0003-mt5-tick",
        help="run C0002 R0003 MT5 tick execution KPI workflow",
    )
    c0002_r0003_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0002_r0003_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-c0002-r0003-mt5-tick-by-fold",
        help="run C0002 R0003 fold-isolated MT5 tick KPI and divergence workflow",
    )
    c0002_r0003_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_c0002_r0003_mt5_parser = subparsers.add_parser(
        "parse-c0002-r0003-mt5",
        help="parse existing C0002 R0003 MT5 output files",
    )
    parse_c0002_r0003_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-c0002-r0003-parity", help="record C0002 R0003 proxy-vs-MT5 logic parity")
    subparsers.add_parser(
        "record-c0002-r0003-execution-divergence",
        help="record C0002 R0003 closed-bar-vs-tick execution divergence",
    )
    c0002_r0004_proxy_parser = subparsers.add_parser(
        "run-c0002-r0004-proxy",
        help="run C0002 R0004 stump-rank ensemble proxy evidence",
    )
    c0002_r0004_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-c0002-r0004-ea", help="compile C0002 generic MT5 schedule-replay EA for R0004")
    c0002_r0004_mt5_logic_parser = subparsers.add_parser(
        "run-c0002-r0004-mt5-logic",
        help="run C0002 R0004 MT5 closed-bar logic parity workflow",
    )
    c0002_r0004_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0002_r0004_mt5_tick_parser = subparsers.add_parser(
        "run-c0002-r0004-mt5-tick",
        help="run C0002 R0004 MT5 tick execution KPI workflow",
    )
    c0002_r0004_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0002_r0004_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-c0002-r0004-mt5-tick-by-fold",
        help="run C0002 R0004 fold-isolated MT5 tick KPI and divergence workflow",
    )
    c0002_r0004_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_c0002_r0004_mt5_parser = subparsers.add_parser(
        "parse-c0002-r0004-mt5",
        help="parse existing C0002 R0004 MT5 output files",
    )
    parse_c0002_r0004_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-c0002-r0004-parity", help="record C0002 R0004 proxy-vs-MT5 logic parity")
    subparsers.add_parser(
        "record-c0002-r0004-execution-divergence",
        help="record C0002 R0004 closed-bar-vs-tick execution divergence",
    )
    sc0001_sr0001_proxy_parser = subparsers.add_parser(
        "run-sc0001-sr0001-proxy",
        help="run SC0001 SR0001 synthesis constraint proxy evidence",
    )
    sc0001_sr0001_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-sc0001-sr0001-ea", help="compile shared schedule replay EA for SC0001 SR0001")
    sc0001_sr0001_mt5_logic_parser = subparsers.add_parser(
        "run-sc0001-sr0001-mt5-logic",
        help="run SC0001 SR0001 MT5 closed-bar logic parity workflow",
    )
    sc0001_sr0001_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    sc0001_sr0001_mt5_tick_parser = subparsers.add_parser(
        "run-sc0001-sr0001-mt5-tick",
        help="run SC0001 SR0001 MT5 tick execution KPI workflow",
    )
    sc0001_sr0001_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    sc0001_sr0001_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-sc0001-sr0001-mt5-tick-by-fold",
        help="run SC0001 SR0001 fold-isolated MT5 tick KPI and divergence workflow",
    )
    sc0001_sr0001_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_sc0001_sr0001_mt5_parser = subparsers.add_parser(
        "parse-sc0001-sr0001-mt5",
        help="parse existing SC0001 SR0001 MT5 output files",
    )
    parse_sc0001_sr0001_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-sc0001-sr0001-parity", help="record SC0001 SR0001 proxy-vs-MT5 logic parity")
    subparsers.add_parser(
        "record-sc0001-sr0001-execution-divergence",
        help="record SC0001 SR0001 closed-bar-vs-tick execution divergence",
    )
    c0004_r0001_proxy_parser = subparsers.add_parser(
        "run-c0004-r0001-proxy",
        help="run C0004 R0001 fold-local state archetype proxy evidence",
    )
    c0004_r0001_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-c0004-r0001-ea", help="compile shared schedule replay EA for C0004 R0001")
    c0004_r0001_mt5_logic_parser = subparsers.add_parser(
        "run-c0004-r0001-mt5-logic",
        help="run C0004 R0001 MT5 closed-bar logic parity workflow",
    )
    c0004_r0001_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0004_r0001_mt5_tick_parser = subparsers.add_parser(
        "run-c0004-r0001-mt5-tick",
        help="run C0004 R0001 MT5 tick execution KPI workflow",
    )
    c0004_r0001_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0004_r0001_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-c0004-r0001-mt5-tick-by-fold",
        help="run C0004 R0001 fold-isolated MT5 tick KPI and divergence workflow",
    )
    c0004_r0001_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_c0004_r0001_mt5_parser = subparsers.add_parser(
        "parse-c0004-r0001-mt5",
        help="parse existing C0004 R0001 MT5 output files",
    )
    parse_c0004_r0001_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-c0004-r0001-parity", help="record C0004 R0001 proxy-vs-MT5 logic parity")
    subparsers.add_parser("record-c0004-r0001-execution-divergence", help="record C0004 R0001 closed-bar-vs-tick execution divergence")
    c0004_r0002_proxy_parser = subparsers.add_parser(
        "run-c0004-r0002-proxy",
        help="run C0004 R0002 path-quality state archetype proxy evidence",
    )
    c0004_r0002_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-c0004-r0002-ea", help="compile shared schedule replay EA for C0004 R0002")
    c0004_r0002_mt5_logic_parser = subparsers.add_parser(
        "run-c0004-r0002-mt5-logic",
        help="run C0004 R0002 MT5 closed-bar logic parity workflow",
    )
    c0004_r0002_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0004_r0002_mt5_tick_parser = subparsers.add_parser(
        "run-c0004-r0002-mt5-tick",
        help="run C0004 R0002 MT5 tick execution KPI workflow",
    )
    c0004_r0002_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0004_r0002_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-c0004-r0002-mt5-tick-by-fold",
        help="run C0004 R0002 fold-isolated MT5 tick KPI and divergence workflow",
    )
    c0004_r0002_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_c0004_r0002_mt5_parser = subparsers.add_parser(
        "parse-c0004-r0002-mt5",
        help="parse existing C0004 R0002 MT5 output files",
    )
    parse_c0004_r0002_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-c0004-r0002-parity", help="record C0004 R0002 proxy-vs-MT5 logic parity")
    subparsers.add_parser("record-c0004-r0002-execution-divergence", help="record C0004 R0002 closed-bar-vs-tick execution divergence")
    c0004_r0003_proxy_parser = subparsers.add_parser(
        "run-c0004-r0003-proxy",
        help="run C0004 R0003 adverse archetype inversion proxy evidence",
    )
    c0004_r0003_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-c0004-r0003-ea", help="compile shared schedule replay EA for C0004 R0003")
    c0004_r0003_mt5_logic_parser = subparsers.add_parser(
        "run-c0004-r0003-mt5-logic",
        help="run C0004 R0003 MT5 closed-bar logic parity workflow",
    )
    c0004_r0003_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0004_r0003_mt5_tick_parser = subparsers.add_parser(
        "run-c0004-r0003-mt5-tick",
        help="run C0004 R0003 MT5 tick execution KPI workflow",
    )
    c0004_r0003_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0004_r0003_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-c0004-r0003-mt5-tick-by-fold",
        help="run C0004 R0003 fold-isolated MT5 tick KPI and divergence workflow",
    )
    c0004_r0003_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_c0004_r0003_mt5_parser = subparsers.add_parser(
        "parse-c0004-r0003-mt5",
        help="parse existing C0004 R0003 MT5 output files",
    )
    parse_c0004_r0003_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-c0004-r0003-parity", help="record C0004 R0003 proxy-vs-MT5 logic parity")
    subparsers.add_parser("record-c0004-r0003-execution-divergence", help="record C0004 R0003 closed-bar-vs-tick execution divergence")
    c0004_r0004_proxy_parser = subparsers.add_parser(
        "run-c0004-r0004-proxy",
        help="run C0004 R0004 temporal-stability archetype proxy evidence",
    )
    c0004_r0004_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-c0004-r0004-ea", help="compile shared schedule replay EA for C0004 R0004")
    c0004_r0004_mt5_logic_parser = subparsers.add_parser(
        "run-c0004-r0004-mt5-logic",
        help="run C0004 R0004 MT5 closed-bar logic parity workflow",
    )
    c0004_r0004_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0004_r0004_mt5_tick_parser = subparsers.add_parser(
        "run-c0004-r0004-mt5-tick",
        help="run C0004 R0004 MT5 tick execution KPI workflow",
    )
    c0004_r0004_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0004_r0004_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-c0004-r0004-mt5-tick-by-fold",
        help="run C0004 R0004 fold-isolated MT5 tick KPI and divergence workflow",
    )
    c0004_r0004_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_c0004_r0004_mt5_parser = subparsers.add_parser(
        "parse-c0004-r0004-mt5",
        help="parse existing C0004 R0004 MT5 output files",
    )
    parse_c0004_r0004_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-c0004-r0004-parity", help="record C0004 R0004 proxy-vs-MT5 logic parity")
    subparsers.add_parser("record-c0004-r0004-execution-divergence", help="record C0004 R0004 closed-bar-vs-tick execution divergence")
    c0005_r0001_proxy_parser = subparsers.add_parser(
        "run-c0005-r0001-proxy",
        help="run C0005 R0001 continuous analog-memory proxy evidence",
    )
    c0005_r0001_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-c0005-r0001-ea", help="compile shared schedule replay EA for C0005 R0001")
    c0005_r0001_mt5_logic_parser = subparsers.add_parser(
        "run-c0005-r0001-mt5-logic",
        help="run C0005 R0001 MT5 closed-bar logic parity workflow",
    )
    c0005_r0001_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0005_r0001_mt5_tick_parser = subparsers.add_parser(
        "run-c0005-r0001-mt5-tick",
        help="run C0005 R0001 MT5 tick execution KPI workflow",
    )
    c0005_r0001_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0005_r0001_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-c0005-r0001-mt5-tick-by-fold",
        help="run C0005 R0001 fold-isolated MT5 tick KPI and divergence workflow",
    )
    c0005_r0001_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_c0005_r0001_mt5_parser = subparsers.add_parser(
        "parse-c0005-r0001-mt5",
        help="parse existing C0005 R0001 MT5 output files",
    )
    parse_c0005_r0001_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-c0005-r0001-parity", help="record C0005 R0001 proxy-vs-MT5 logic parity")
    subparsers.add_parser("record-c0005-r0001-execution-divergence", help="record C0005 R0001 closed-bar-vs-tick execution divergence")
    c0005_r0002_proxy_parser = subparsers.add_parser(
        "run-c0005-r0002-proxy",
        help="run C0005 R0002 directional contrast analog-memory proxy evidence",
    )
    c0005_r0002_proxy_parser.add_argument("--dry-run", action="store_true", help="print proxy payload without writing files")
    subparsers.add_parser("compile-c0005-r0002-ea", help="compile shared schedule replay EA for C0005 R0002")
    c0005_r0002_mt5_logic_parser = subparsers.add_parser(
        "run-c0005-r0002-mt5-logic",
        help="run C0005 R0002 MT5 closed-bar logic parity workflow",
    )
    c0005_r0002_mt5_logic_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0005_r0002_mt5_tick_parser = subparsers.add_parser(
        "run-c0005-r0002-mt5-tick",
        help="run C0005 R0002 MT5 tick execution KPI workflow",
    )
    c0005_r0002_mt5_tick_parser.add_argument("--timeout-seconds", type=int, default=1800)
    c0005_r0002_mt5_tick_by_fold_parser = subparsers.add_parser(
        "run-c0005-r0002-mt5-tick-by-fold",
        help="run C0005 R0002 fold-isolated MT5 tick KPI and divergence workflow",
    )
    c0005_r0002_mt5_tick_by_fold_parser.add_argument("--timeout-seconds", type=int, default=1800)
    parse_c0005_r0002_mt5_parser = subparsers.add_parser(
        "parse-c0005-r0002-mt5",
        help="parse existing C0005 R0002 MT5 output files",
    )
    parse_c0005_r0002_mt5_parser.add_argument("--mode", choices=(LOGIC_PARITY_MODE, TICK_EXECUTION_MODE), default=LOGIC_PARITY_MODE)
    subparsers.add_parser("record-c0005-r0002-parity", help="record C0005 R0002 proxy-vs-MT5 logic parity")
    subparsers.add_parser("record-c0005-r0002-execution-divergence", help="record C0005 R0002 closed-bar-vs-tick execution divergence")
    subparsers.add_parser("validate-templates", help="validate campaign templates and contract alignment")
    work_unit_parser = subparsers.add_parser("validate-work-unit", help="validate a generated campaign work unit")
    work_unit_parser.add_argument("path", help="path such as campaigns/C0001_short_slug")
    return parser


def status_payload() -> dict[str, str]:
    paths: dict[str, Path] = {
        "project_root": PROJECT_ROOT,
        "configs": CONFIG_DIR,
        "contracts": CONTRACT_DIR,
        "campaigns": CAMPAIGN_DIR,
        "registries": REGISTRY_DIR,
        "claim_state": REGISTRY_DIR / "claim_state.yaml",
        "reentry": REGISTRY_DIR / "reentry.yaml",
    }
    return {key: value.as_posix() for key, value in paths.items()}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "status":
        print(json.dumps(status_payload(), indent=2, sort_keys=True))
        return 0
    if args.command == "export-mt5-max-bars":
        result = run_terminal_export(args.symbol, args.timeframe, timeout_seconds=args.timeout_seconds)
        print(
            json.dumps(
                {
                    "raw_csv": result.raw_csv.as_posix(),
                    "row_count": result.row_count,
                    "first_time": result.first_time,
                    "last_time": result.last_time,
                    "sha256": result.sha256,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "build-us100-base-frame":
        coverage = build_us100_m5_base_frame()
        print(json.dumps(coverage, indent=2, sort_keys=True))
        return 0
    if args.command == "derive-us100-clean-periods":
        payload = derive_clean_periods()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "build-us100-rolling-windows":
        payload = build_rolling_windows()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0001-proxy":
        payload = run_r0001_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-r0001-ea":
        result = compile_r0001_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0001-mt5-logic":
        payload = run_r0001_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0001-mt5-tick":
        payload = run_r0001_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0001-mt5-tick-by-fold":
        payload = run_r0001_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-r0001-mt5":
        payload = parse_r0001_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-r0001-parity":
        payload = record_r0001_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-r0001-execution-divergence":
        payload = record_r0001_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0002-proxy":
        payload = run_r0002_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-r0002-ea":
        result = compile_r0002_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0002-mt5-logic":
        payload = run_r0002_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0002-mt5-tick":
        payload = run_r0002_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0002-mt5-tick-by-fold":
        payload = run_r0002_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-r0002-mt5":
        payload = parse_r0002_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-r0002-parity":
        payload = record_r0002_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-r0002-execution-divergence":
        payload = record_r0002_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0003-proxy":
        payload = run_r0003_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-r0003-ea":
        result = compile_r0003_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0003-mt5-logic":
        payload = run_r0003_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0003-mt5-tick":
        payload = run_r0003_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0003-mt5-tick-by-fold":
        payload = run_r0003_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-r0003-mt5":
        payload = parse_r0003_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-r0003-parity":
        payload = record_r0003_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-r0003-execution-divergence":
        payload = record_r0003_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0004-proxy":
        payload = run_r0004_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-r0004-ea":
        result = compile_r0004_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0004-mt5-logic":
        payload = run_r0004_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0004-mt5-tick":
        payload = run_r0004_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0004-mt5-tick-by-fold":
        payload = run_r0004_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-r0004-mt5":
        payload = parse_r0004_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-r0004-parity":
        payload = record_r0004_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-r0004-execution-divergence":
        payload = record_r0004_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0005-proxy":
        payload = run_r0005_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-r0005-ea":
        result = compile_r0005_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0005-mt5-logic":
        payload = run_r0005_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0005-mt5-tick":
        payload = run_r0005_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0005-mt5-tick-by-fold":
        payload = run_r0005_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-r0005-mt5":
        payload = parse_r0005_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-r0005-parity":
        payload = record_r0005_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-r0005-execution-divergence":
        payload = record_r0005_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0006-proxy":
        payload = run_r0006_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-r0006-ea":
        result = compile_r0006_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0006-mt5-logic":
        payload = run_r0006_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0006-mt5-tick":
        payload = run_r0006_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0006-mt5-tick-by-fold":
        payload = run_r0006_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-r0006-mt5":
        payload = parse_r0006_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-r0006-parity":
        payload = record_r0006_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-r0006-execution-divergence":
        payload = record_r0006_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0007-proxy":
        payload = run_r0007_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-r0007-ea":
        result = compile_r0007_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0007-mt5-logic":
        payload = run_r0007_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0007-mt5-tick":
        payload = run_r0007_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-r0007-mt5-tick-by-fold":
        payload = run_r0007_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-r0007-mt5":
        payload = parse_r0007_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-r0007-parity":
        payload = record_r0007_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-r0007-execution-divergence":
        payload = record_r0007_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0001-proxy":
        payload = run_c0002_r0001_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-c0002-r0001-ea":
        result = compile_c0002_r0001_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0001-mt5-logic":
        payload = run_c0002_r0001_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0001-mt5-tick":
        payload = run_c0002_r0001_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0001-mt5-tick-by-fold":
        payload = run_c0002_r0001_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-c0002-r0001-mt5":
        payload = parse_c0002_r0001_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0002-r0001-parity":
        payload = record_c0002_r0001_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0002-r0001-execution-divergence":
        payload = record_c0002_r0001_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0002-proxy":
        payload = run_c0002_r0002_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-c0002-r0002-ea":
        result = compile_c0002_r0002_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0002-mt5-logic":
        payload = run_c0002_r0002_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0002-mt5-tick":
        payload = run_c0002_r0002_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0002-mt5-tick-by-fold":
        payload = run_c0002_r0002_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-c0002-r0002-mt5":
        payload = parse_c0002_r0002_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0002-r0002-parity":
        payload = record_c0002_r0002_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0002-r0002-execution-divergence":
        payload = record_c0002_r0002_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0003-proxy":
        payload = run_c0002_r0003_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-c0002-r0003-ea":
        result = compile_c0002_r0003_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0003-mt5-logic":
        payload = run_c0002_r0003_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0003-mt5-tick":
        payload = run_c0002_r0003_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0003-mt5-tick-by-fold":
        payload = run_c0002_r0003_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-c0002-r0003-mt5":
        payload = parse_c0002_r0003_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0002-r0003-parity":
        payload = record_c0002_r0003_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0002-r0003-execution-divergence":
        payload = record_c0002_r0003_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0004-proxy":
        payload = run_c0002_r0004_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-c0002-r0004-ea":
        result = compile_c0002_r0004_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0004-mt5-logic":
        payload = run_c0002_r0004_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0004-mt5-tick":
        payload = run_c0002_r0004_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0002-r0004-mt5-tick-by-fold":
        payload = run_c0002_r0004_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-c0002-r0004-mt5":
        payload = parse_c0002_r0004_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0002-r0004-parity":
        payload = record_c0002_r0004_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0002-r0004-execution-divergence":
        payload = record_c0002_r0004_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-sc0001-sr0001-proxy":
        payload = run_sc0001_sr0001_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-sc0001-sr0001-ea":
        result = compile_sc0001_sr0001_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-sc0001-sr0001-mt5-logic":
        payload = run_sc0001_sr0001_logic_parity_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-sc0001-sr0001-mt5-tick":
        payload = run_sc0001_sr0001_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-sc0001-sr0001-mt5-tick-by-fold":
        payload = run_sc0001_sr0001_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-sc0001-sr0001-mt5":
        payload = parse_sc0001_sr0001_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-sc0001-sr0001-parity":
        payload = record_sc0001_sr0001_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-sc0001-sr0001-execution-divergence":
        payload = record_sc0001_sr0001_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0001-proxy":
        payload = run_c0004_r0001_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-c0004-r0001-ea":
        result = compile_c0004_r0001_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0001-mt5-logic":
        payload = run_c0004_r0001_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0001-mt5-tick":
        payload = run_c0004_r0001_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0001-mt5-tick-by-fold":
        payload = run_c0004_r0001_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-c0004-r0001-mt5":
        payload = parse_c0004_r0001_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0004-r0001-parity":
        payload = record_c0004_r0001_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0004-r0001-execution-divergence":
        payload = record_c0004_r0001_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0002-proxy":
        payload = run_c0004_r0002_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-c0004-r0002-ea":
        result = compile_c0004_r0002_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0002-mt5-logic":
        payload = run_c0004_r0002_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0002-mt5-tick":
        payload = run_c0004_r0002_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0002-mt5-tick-by-fold":
        payload = run_c0004_r0002_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-c0004-r0002-mt5":
        payload = parse_c0004_r0002_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0004-r0002-parity":
        payload = record_c0004_r0002_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0004-r0002-execution-divergence":
        payload = record_c0004_r0002_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0003-proxy":
        payload = run_c0004_r0003_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-c0004-r0003-ea":
        result = compile_c0004_r0003_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0003-mt5-logic":
        payload = run_c0004_r0003_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0003-mt5-tick":
        payload = run_c0004_r0003_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0003-mt5-tick-by-fold":
        payload = run_c0004_r0003_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-c0004-r0003-mt5":
        payload = parse_c0004_r0003_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0004-r0003-parity":
        payload = record_c0004_r0003_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0004-r0003-execution-divergence":
        payload = record_c0004_r0003_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0004-proxy":
        payload = run_c0004_r0004_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-c0004-r0004-ea":
        result = compile_c0004_r0004_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0004-mt5-logic":
        payload = run_c0004_r0004_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0004-mt5-tick":
        payload = run_c0004_r0004_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0004-r0004-mt5-tick-by-fold":
        payload = run_c0004_r0004_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-c0004-r0004-mt5":
        payload = parse_c0004_r0004_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0004-r0004-parity":
        payload = record_c0004_r0004_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0004-r0004-execution-divergence":
        payload = record_c0004_r0004_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0005-r0001-proxy":
        payload = run_c0005_r0001_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-c0005-r0001-ea":
        result = compile_c0005_r0001_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0005-r0001-mt5-logic":
        payload = run_c0005_r0001_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0005-r0001-mt5-tick":
        payload = run_c0005_r0001_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0005-r0001-mt5-tick-by-fold":
        payload = run_c0005_r0001_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-c0005-r0001-mt5":
        payload = parse_c0005_r0001_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0005-r0001-parity":
        payload = record_c0005_r0001_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0005-r0001-execution-divergence":
        payload = record_c0005_r0001_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0005-r0002-proxy":
        payload = run_c0005_r0002_proxy(write=not args.dry_run)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "compile-c0005-r0002-ea":
        result = compile_c0005_r0002_ea()
        print(json.dumps({"ex5": result.ex5.as_posix(), "log": result.log.as_posix()}, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0005-r0002-mt5-logic":
        payload = run_c0005_r0002_mt5_logic_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0005-r0002-mt5-tick":
        payload = run_c0005_r0002_mt5_tick_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run-c0005-r0002-mt5-tick-by-fold":
        payload = run_c0005_r0002_mt5_tick_by_fold_workflow(timeout_seconds=args.timeout_seconds)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "parse-c0005-r0002-mt5":
        payload = parse_c0005_r0002_mt5(mode=args.mode)
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0005-r0002-parity":
        payload = record_c0005_r0002_parity()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "record-c0005-r0002-execution-divergence":
        payload = record_c0005_r0002_execution_divergence()
        print(json.dumps(payload["required_kpis"], indent=2, sort_keys=True))
        return 0
    if args.command == "validate-templates":
        result = validate_templates()
        print(result_json(result))
        return 0 if result.ok else 1
    if args.command == "validate-work-unit":
        result = validate_work_unit(Path(args.path))
        print(result_json(result))
        return 0 if result.ok else 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
