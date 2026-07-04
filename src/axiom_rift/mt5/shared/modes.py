"""Shared MT5 execution mode helpers."""

from __future__ import annotations


LOGIC_PARITY_MODE = "logic_parity"
TICK_EXECUTION_MODE = "tick_execution"
VALID_MT5_MODES = {LOGIC_PARITY_MODE, TICK_EXECUTION_MODE}


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
