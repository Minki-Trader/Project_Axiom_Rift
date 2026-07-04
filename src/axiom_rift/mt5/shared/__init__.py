"""Shared MT5 helper boundary for run-specific probes."""

from axiom_rift.mt5.shared.folds import schedule_fold_summary, tester_date_to_iso, tester_dates_for_window, tester_to_date_to_end_iso
from axiom_rift.mt5.shared.io import read_compile_log, read_csv_rows, read_status_csv, tester_model_label, wait_for_status
from axiom_rift.mt5.shared.kpi import (
    append_rate,
    bool_text,
    direction_summary,
    int_delta,
    kpi_float,
    kpi_int,
    max_drawdown_percent,
    missing_required_by_fold_fields,
    missing_required_execution_fields,
    missing_required_kpi_fields,
    missing_value_checks,
    numeric_delta,
    rounded,
    to_float,
)
from axiom_rift.mt5.shared.modes import (
    LOGIC_PARITY_MODE,
    TICK_EXECUTION_MODE,
    VALID_MT5_MODES,
    normalize_mt5_mode,
    normalize_output_scope,
    use_closed_bar_exit_for_mode,
)
from axiom_rift.mt5.shared.parity import (
    compare_entry_sequence,
    compare_exit_sequence,
    compare_mt5_entry_events,
    compare_mt5_exit_events,
    direction_value,
    economics_shift_status,
    event_bar_time,
    execution_divergence_status,
    match_rate,
    parity_mismatch_summary,
    parse_time,
    time_text,
)
from axiom_rift.mt5.shared.results import CompileResult, TesterResult
