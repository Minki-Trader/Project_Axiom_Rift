"""Eligibility-only audit for the exact FPMarkets VIX rolling symbol."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.vix_source import VIX_COLUMNS, VIX_SERVER, VIX_SYMBOL


_START_UTC = datetime(2022, 1, 1, tzinfo=timezone.utc)
_END_UTC = datetime(2026, 4, 30, 23, 55, tzinfo=timezone.utc)


class VIXSourceAuditError(RuntimeError):
    """The exact VIX audit could not produce a deterministic measurement."""


def _terminal_path(root: Path) -> str:
    value = yaml.safe_load(
        (root / "foundation" / "environment.yaml").read_text(encoding="ascii")
    )
    mt5 = value.get("mt5") if isinstance(value, dict) else None
    if not isinstance(mt5, dict) or not isinstance(mt5.get("terminal"), str):
        raise VIXSourceAuditError("MT5 terminal path is absent")
    return mt5["terminal"]


def _history_bytes(rates: np.ndarray) -> bytes:
    rows = [",".join(VIX_COLUMNS)]
    for row in rates:
        stamp = datetime.fromtimestamp(int(row["time"]), timezone.utc)
        rows.append(
            f"{stamp:%Y.%m.%d %H:%M:%S},"
            f"{float(row['open']):.2f},{float(row['high']):.2f},"
            f"{float(row['low']):.2f},{float(row['close']):.2f},"
            f"{int(row['tick_volume'])},{int(row['spread'])},"
            f"{int(row['real_volume'])}"
        )
    return ("\n".join(rows) + "\n").encode("ascii")


def audit_vix_source(repository_root: str | Path) -> dict[str, Any]:
    """Measure availability while failing closed on undocumented roll semantics."""

    root = Path(repository_root).resolve()
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:  # pragma: no cover - production dependency
        raise VIXSourceAuditError("MetaTrader5 Python package is unavailable") from exc
    if not mt5.initialize(path=_terminal_path(root)):
        raise VIXSourceAuditError(f"MT5 initialization failed: {mt5.last_error()!r}")
    try:
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        if not mt5.symbol_select(VIX_SYMBOL, True):
            raise VIXSourceAuditError("VIX symbol selection failed")
        info = mt5.symbol_info(VIX_SYMBOL)
        tick = mt5.symbol_info_tick(VIX_SYMBOL)
        yearly: list[np.ndarray] = []
        yearly_counts: dict[str, int] = {}
        for year in range(_START_UTC.year, _END_UTC.year + 1):
            start = max(_START_UTC, datetime(year, 1, 1, tzinfo=timezone.utc))
            end = min(
                _END_UTC,
                datetime(year + 1, 1, 1, tzinfo=timezone.utc),
            )
            rates = mt5.copy_rates_range(VIX_SYMBOL, mt5.TIMEFRAME_M5, start, end)
            if rates is None or len(rates) == 0:
                raise VIXSourceAuditError(
                    f"VIX historical retrieval failed for {year}: {mt5.last_error()!r}"
                )
            yearly.append(rates)
            yearly_counts[str(year)] = int(len(rates))
    finally:
        mt5.shutdown()
    if account is None or terminal is None or info is None or tick is None:
        raise VIXSourceAuditError("VIX runtime surface is incomplete")
    rates = np.concatenate(yearly)
    order = np.argsort(rates["time"], kind="stable")
    rates = rates[order]
    epochs = np.asarray(rates["time"], dtype=np.int64)
    unique_epochs, unique_indices = np.unique(epochs, return_index=True)
    duplicate_rows = int(len(epochs) - len(unique_epochs))
    rates = rates[unique_indices]
    epochs = unique_epochs
    differences = np.diff(epochs)
    off_grid_rows = int(
        sum(
            1
            for value in epochs
            if datetime.fromtimestamp(int(value), timezone.utc).minute % 5 != 0
            or datetime.fromtimestamp(int(value), timezone.utc).second != 0
        )
    )
    numeric = np.column_stack(
        [np.asarray(rates[name], dtype=float) for name in VIX_COLUMNS[1:]]
    )
    finite_rows = np.isfinite(numeric).all(axis=1)
    open_ = np.asarray(rates["open"], dtype=float)
    high = np.asarray(rates["high"], dtype=float)
    low = np.asarray(rates["low"], dtype=float)
    close = np.asarray(rates["close"], dtype=float)
    invalid_ohlc = (
        (high < np.maximum.reduce((open_, low, close)))
        | (low > np.minimum.reduce((open_, high, close)))
        | (low <= 0)
    )
    description = str(info.description)
    current_contract_disclosed = bool(" Exp " in description and "VIX" in description)
    roll_metadata_available = bool(
        getattr(info, "basis", "")
        or getattr(info, "category", "")
        or getattr(info, "start_time", 0)
        or getattr(info, "expiration_time", 0)
    )
    raw = _history_bytes(rates)
    first = datetime.fromtimestamp(int(epochs[0]), timezone.utc)
    last = datetime.fromtimestamp(int(epochs[-1]), timezone.utc)
    observed = datetime.now(timezone.utc).replace(microsecond=0)
    facts = {
        "connected_to_expected_server": bool(
            terminal.connected and account.server == VIX_SERVER
        ),
        "current_contract_disclosed": current_contract_disclosed,
        "development_prefix_only": bool(last <= _END_UTC),
        "historical_acquisition_observed": bool(len(rates) > 100_000),
        "historical_structure_valid": bool(
            duplicate_rows == 0
            and off_grid_rows == 0
            and finite_rows.all()
            and not invalid_ohlc.any()
            and (np.asarray(rates["spread"], dtype=float) >= 0).all()
        ),
        "roll_metadata_available": roll_metadata_available,
        "roll_semantics_audited": False,
        "performance_eligible": False,
        "runtime_symbol_available": bool(info.name == VIX_SYMBOL and tick.time > 0),
    }
    measurement = {
        "schema": "vix_source_eligibility_audit.v1",
        "observed_at_utc": observed.isoformat().replace("+00:00", "Z"),
        "server": account.server,
        "runtime_symbol": info.name,
        "runtime_description": description,
        "runtime_path": str(info.path),
        "digits": int(info.digits),
        "point": f"{float(info.point):.2f}",
        "tick_size": f"{float(info.trade_tick_size):.2f}",
        "contract_size": f"{float(info.trade_contract_size):.1f}",
        "first_time_utc": first.isoformat().replace("+00:00", "Z"),
        "last_time_utc": last.isoformat().replace("+00:00", "Z"),
        "row_count": int(len(rates)),
        "yearly_row_counts": yearly_counts,
        "raw_sha256": sha256(raw).hexdigest(),
        "duplicate_rows": duplicate_rows,
        "off_grid_rows": off_grid_rows,
        "nonfinite_rows": int((~finite_rows).sum()),
        "negative_spread_rows": int(
            (np.asarray(rates["spread"], dtype=float) < 0).sum()
        ),
        "invalid_ohlc_rows": int(invalid_ohlc.sum()),
        "timestamp_gap_count": int((differences != 300).sum()),
        "facts": facts,
        "ineligibility_reason": (
            "The exact VIX runtime description identifies an expiring futures contract, "
            "but the broker surface supplies no historical contract map, roll schedule, "
            "or adjustment metadata for the continuous alias."
        ),
    }
    canonical_bytes(measurement)
    return measurement


__all__ = ["VIXSourceAuditError", "audit_vix_source"]
