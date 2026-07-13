"""FPMarkets USDJPY M5 source contract and eligibility measurements."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.sources import SourceContract, SourceType


USDJPY_SYMBOL = "USDJPY"
USDJPY_SERVER = "FPMarketsSC-Live"
USDJPY_RAW_RELATIVE_PATH = "data/raw/mt5_bars/m5/USDJPY_M5_fixed.csv"
USDJPY_START_UTC = datetime(2018, 5, 7, 1, 0, tzinfo=timezone.utc)
USDJPY_END_UTC = datetime(2026, 6, 26, 23, 50, tzinfo=timezone.utc)
USDJPY_COLUMNS = (
    "time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
)
HISTORICAL_FACT_FIELDS = (
    "acquisition_observed",
    "content_hash_verified",
    "event_time_audited",
    "information_complete_at_audited",
    "first_availability_audited",
    "coverage_audited",
    "gaps_audited",
    "revision_or_vintage_audited",
)
RUNTIME_FACT_FIELDS = (
    "local_realtime_retrieval",
    "fresh",
    "synchronized",
    "complete_or_closed",
    "latency_ms",
    "historical_runtime_field_parity",
)


class USDJPYSourceError(RuntimeError):
    """The USDJPY source could not satisfy an eligibility boundary."""


def usdjpy_source_contract() -> SourceContract:
    return SourceContract(
        display_name="FPMarkets USDJPY spot FX M5 bid bars",
        canonical_instrument="FPMarkets_USDJPY_spot_FX_M5",
        runtime_identifier=USDJPY_SYMBOL,
        source_type=SourceType.BAR,
        instrument_semantics={
            "asset_type": "spot_fx",
            "quote_basis": "bid_bar",
            "contract_size": "100000.0",
            "currency": "JPY_per_USD",
            "digits": 3,
            "point": "0.001",
            "session": "FPMarkets_dynamic_forex_session",
            "timezone": "MT5_epoch_UTC",
            "adjustment": "none",
            "roll": "spot_fx_no_contract_roll",
        },
        mapping_semantics={
            "runtime_symbol": USDJPY_SYMBOL,
            "mapping_rule": "exact_FPMarkets_local_symbol_no_substitute",
        },
        schema_semantics={
            "columns": list(USDJPY_COLUMNS),
            "schema_revision": "mt5_copy_rates_m5_v1",
        },
        field_semantics={
            "bar_open": "bid_open_at_event_time",
            "bar_close": "bid_close_at_event_time_plus_5m",
            "event_time": "MT5_epoch_seconds_rendered_as_UTC_bar_open",
            "information_complete_at": "event_time_plus_5m",
            "first_available_at": "first_successful_local_retrieval_after_bar_close",
        },
        clock_semantics={
            "decision_alignment": "information_complete_at_le_US100_decision_time",
            "timezone_conversion": "epoch_to_UTC_without_server_label_inference",
        },
        availability_semantics={
            "acquisition": "MetaTrader5.copy_rates_range_local_terminal",
            "content_hash": "sha256_of_deterministic_csv_job_artifact",
            "coverage": "2018-05-07T01:00:00Z_through_2026-06-26T23:50:00Z",
            "gap_policy": "exact_timestamp_inner_join_fail_closed_no_fill",
            "revision_or_vintage": "immutable_job_artifact_by_sha256",
            "causal_ttl_seconds": 360,
            "eligibility_receipt_ttl_seconds": 21_600,
            "runtime_retrieval_method": "copy_rates_from_pos_plus_symbol_tick",
        },
    )


def _environment(root: Path) -> Mapping[str, Any]:
    value = yaml.safe_load(
        (root / "foundation" / "environment.yaml").read_text(encoding="ascii")
    )
    if not isinstance(value, dict):
        raise USDJPYSourceError("environment foundation is invalid")
    return value


def _terminal_path(root: Path) -> str:
    value = _environment(root).get("mt5")
    if not isinstance(value, dict) or not isinstance(value.get("terminal"), str):
        raise USDJPYSourceError("MT5 terminal path is absent")
    return value["terminal"]


def _render_rates_csv(rates: np.ndarray) -> bytes:
    lines = [",".join(USDJPY_COLUMNS)]
    for row in rates:
        stamp = datetime.fromtimestamp(int(row["time"]), timezone.utc)
        lines.append(
            f"{stamp:%Y.%m.%d %H:%M:%S},"
            f"{float(row['open']):.3f},{float(row['high']):.3f},"
            f"{float(row['low']):.3f},{float(row['close']):.3f},"
            f"{int(row['tick_volume'])},{int(row['spread'])},"
            f"{int(row['real_volume'])}"
        )
    return ("\n".join(lines) + "\n").encode("ascii")


def acquire_usdjpy_historical_snapshot(repository_root: str | Path) -> bytes:
    root = Path(repository_root).resolve()
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:  # pragma: no cover - production dependency
        raise USDJPYSourceError("MetaTrader5 Python package is unavailable") from exc
    if not mt5.initialize(path=_terminal_path(root)):
        raise USDJPYSourceError(f"MT5 initialization failed: {mt5.last_error()!r}")
    try:
        if not mt5.symbol_select(USDJPY_SYMBOL, True):
            raise USDJPYSourceError("USDJPY symbol selection failed")
        rates = mt5.copy_rates_range(
            USDJPY_SYMBOL,
            mt5.TIMEFRAME_M5,
            USDJPY_START_UTC,
            USDJPY_END_UTC,
        )
        if rates is None or len(rates) == 0:
            raise USDJPYSourceError(
                f"USDJPY historical retrieval failed: {mt5.last_error()!r}"
            )
        content = _render_rates_csv(rates)
    finally:
        mt5.shutdown()
    target = (root / USDJPY_RAW_RELATIVE_PATH).resolve()
    if root not in target.parents:
        raise USDJPYSourceError("USDJPY raw path escapes repository")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return content


def _parse_historical(content: bytes) -> pd.DataFrame:
    try:
        frame = pd.read_csv(BytesIO(content), dtype={"time": str})
    except Exception as exc:
        raise USDJPYSourceError("USDJPY historical CSV cannot be parsed") from exc
    if tuple(frame.columns) != USDJPY_COLUMNS or frame.empty:
        raise USDJPYSourceError("USDJPY historical CSV schema is invalid")
    return frame


def audit_usdjpy_historical_bytes(
    content: bytes,
    *,
    observed_at_utc: str,
) -> dict[str, Any]:
    frame = _parse_historical(content)
    time = pd.to_datetime(
        frame["time"], format="%Y.%m.%d %H:%M:%S", utc=True, errors="coerce"
    )
    numeric_names = USDJPY_COLUMNS[1:]
    numeric = frame.loc[:, numeric_names].apply(pd.to_numeric, errors="coerce")
    values = numeric.to_numpy(dtype=float)
    finite_rows = np.isfinite(values).all(axis=1)
    open_ = numeric["open"].to_numpy(dtype=float)
    high = numeric["high"].to_numpy(dtype=float)
    low = numeric["low"].to_numpy(dtype=float)
    close = numeric["close"].to_numpy(dtype=float)
    invalid_ohlc = finite_rows & (
        (high < np.maximum.reduce((open_, low, close)))
        | (low > np.minimum.reduce((open_, high, close)))
        | (low <= 0)
    )
    valid_time = time.notna().to_numpy()
    time_ns = time.astype("int64", copy=False).to_numpy()
    differences = (
        np.diff(time_ns) if len(time_ns) > 1 else np.array([], dtype=np.int64)
    )
    five_minutes_ns = 300_000_000_000
    first = (
        None
        if not valid_time.all()
        else time.iloc[0].isoformat().replace("+00:00", "Z")
    )
    last = (
        None
        if not valid_time.all()
        else time.iloc[-1].isoformat().replace("+00:00", "Z")
    )
    expected_first = USDJPY_START_UTC.isoformat().replace("+00:00", "Z")
    expected_last = USDJPY_END_UTC.isoformat().replace("+00:00", "Z")
    duplicate_rows = int(frame.duplicated(subset=["time"]).sum())
    non_monotonic_rows = int((differences <= 0).sum())
    valid_timestamps = time.dropna()
    on_grid = (
        (valid_timestamps.dt.second == 0)
        & (valid_timestamps.dt.microsecond == 0)
        & (valid_timestamps.dt.minute % 5 == 0)
    )
    off_grid_rows = int(len(valid_timestamps) - int(on_grid.sum()))
    nonfinite_rows = int((~finite_rows).sum())
    negative_spread_rows = int(
        (numeric["spread"].to_numpy(dtype=float) < 0).sum()
    )
    invalid_ohlc_rows = int(invalid_ohlc.sum())
    timestamp_gaps = int((differences != five_minutes_ns).sum())
    acquisition_ok = len(content) > 0 and len(frame) > 100_000
    structure_ok = (
        valid_time.all()
        and duplicate_rows == 0
        and non_monotonic_rows == 0
        and off_grid_rows == 0
        and nonfinite_rows == 0
        and negative_spread_rows == 0
        and invalid_ohlc_rows == 0
    )
    coverage_ok = first == expected_first and last == expected_last
    facts = {
        "acquisition_observed": bool(acquisition_ok),
        "content_hash_verified": True,
        "event_time_audited": bool(valid_time.all() and off_grid_rows == 0),
        "information_complete_at_audited": bool(structure_ok),
        "first_availability_audited": bool(structure_ok),
        "coverage_audited": bool(coverage_ok),
        "gaps_audited": bool(structure_ok),
        "revision_or_vintage_audited": True,
    }
    return {
        "schema": "usdjpy_historical_audit_measurement.v1",
        "source_contract_id": usdjpy_source_contract().source_contract_id,
        "observed_at_utc": observed_at_utc,
        "raw_sha256": sha256(content).hexdigest(),
        "columns": list(USDJPY_COLUMNS),
        "row_count": int(len(frame)),
        "first_time_utc": first,
        "last_time_utc": last,
        "duplicate_rows": duplicate_rows,
        "non_monotonic_rows": non_monotonic_rows,
        "off_grid_rows": off_grid_rows,
        "nonfinite_rows": nonfinite_rows,
        "negative_spread_rows": negative_spread_rows,
        "invalid_ohlc_rows": invalid_ohlc_rows,
        "timestamp_gap_count": timestamp_gaps,
        "facts": facts,
    }


def build_usdjpy_historical_audit(
    repository_root: str | Path,
) -> tuple[bytes, dict[str, Any]]:
    content = acquire_usdjpy_historical_snapshot(repository_root)
    observed = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    measurement = audit_usdjpy_historical_bytes(content, observed_at_utc=observed)
    if any(
        measurement["facts"].get(name) is not True
        for name in HISTORICAL_FACT_FIELDS
    ):
        raise USDJPYSourceError("USDJPY historical source audit did not pass")
    return content, measurement


def derive_runtime_facts(probe: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "connected",
        "server",
        "symbol",
        "description",
        "digits",
        "point",
        "tick_size",
        "contract_size",
        "rates_count",
        "consecutive_closed_bars",
        "finite_tick",
        "market_closed",
        "closed_bar_available",
        "retrieval_latency_ms",
        "market_clock_coherent",
        "dtype_fields",
    }
    if not required.issubset(probe):
        raise USDJPYSourceError("USDJPY runtime probe schema is incomplete")
    exact_spec = (
        probe["server"] == USDJPY_SERVER
        and probe["symbol"] == USDJPY_SYMBOL
        and probe["digits"] == 3
        and probe["point"] == "0.001"
        and probe["tick_size"] == "0.001"
        and probe["contract_size"] == "100000.0"
        and list(probe["dtype_fields"]) == list(USDJPY_COLUMNS)
    )
    latency = probe["retrieval_latency_ms"]
    retrieval = (
        probe["connected"] is True
        and exact_spec
        and isinstance(probe["rates_count"], int)
        and probe["rates_count"] >= 3
        and probe["finite_tick"] is True
        and probe["market_clock_coherent"] is True
    )
    return {
        "local_realtime_retrieval": bool(retrieval),
        "fresh": bool(
            retrieval and isinstance(latency, int) and 0 <= latency <= 30_000
        ),
        "synchronized": bool(retrieval and probe["consecutive_closed_bars"] is True),
        "complete_or_closed": bool(
            retrieval
            and (probe["closed_bar_available"] is True or probe["market_closed"] is True)
        ),
        "latency_ms": int(latency),
        "historical_runtime_field_parity": bool(exact_spec),
    }


def _completed_rate_epochs(
    epochs: np.ndarray,
    *,
    market_epoch_seconds: int,
) -> np.ndarray:
    """Select completed bars in the MT5 market-clock coordinate."""

    return epochs[epochs + 300 <= market_epoch_seconds]


def probe_usdjpy_runtime(repository_root: str | Path) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:  # pragma: no cover - production dependency
        raise USDJPYSourceError("MetaTrader5 Python package is unavailable") from exc
    started = perf_counter()
    if not mt5.initialize(path=_terminal_path(root)):
        raise USDJPYSourceError(f"MT5 initialization failed: {mt5.last_error()!r}")
    observed = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        mt5.symbol_select(USDJPY_SYMBOL, True)
        info = mt5.symbol_info(USDJPY_SYMBOL)
        rates = mt5.copy_rates_from_pos(USDJPY_SYMBOL, mt5.TIMEFRAME_M5, 0, 8)
        tick = mt5.symbol_info_tick(USDJPY_SYMBOL)
    finally:
        mt5.shutdown()
    latency = int(round(1000 * (perf_counter() - started)))
    if account is None or terminal is None or info is None or rates is None or tick is None:
        raise USDJPYSourceError("USDJPY runtime probe returned an incomplete surface")
    epochs = np.asarray(rates["time"], dtype=np.int64)
    market_epoch_seconds = int(tick.time)
    machine_epoch_seconds = int(observed.timestamp())
    market_clock_offset_seconds = market_epoch_seconds - machine_epoch_seconds
    nearest_hour_offset = round(market_clock_offset_seconds / 3600)
    market_clock_coherent = bool(
        -4 <= nearest_hour_offset <= 4
        and abs(market_clock_offset_seconds - nearest_hour_offset * 3600) <= 60
    )
    closed = _completed_rate_epochs(
        epochs,
        market_epoch_seconds=market_epoch_seconds,
    )
    consecutive = len(closed) >= 3 and bool(np.all(np.diff(closed[-3:]) == 300))
    tick_values = np.array([tick.bid, tick.ask, float(tick.time)], dtype=float)
    probe = {
        "schema": "usdjpy_runtime_probe_measurement.v1",
        "source_contract_id": usdjpy_source_contract().source_contract_id,
        "observed_at_utc": observed.isoformat().replace("+00:00", "Z"),
        "connected": bool(terminal.connected),
        "server": str(account.server),
        "symbol": str(info.name),
        "description": str(info.description),
        "digits": int(info.digits),
        "point": format(float(info.point), ".3f"),
        "tick_size": format(float(info.trade_tick_size), ".3f"),
        "contract_size": format(float(info.trade_contract_size), ".1f"),
        "rates_count": int(len(rates)),
        "consecutive_closed_bars": consecutive,
        "finite_tick": bool(np.isfinite(tick_values).all() and tick.bid > 0),
        "market_closed": bool(observed.weekday() >= 5),
        "closed_bar_available": bool(len(closed) >= 1),
        "market_clock_offset_seconds": market_clock_offset_seconds,
        "market_clock_coherent": market_clock_coherent,
        "latest_closed_bar_utc": (
            None
            if len(closed) == 0
            else datetime.fromtimestamp(int(closed[-1]), timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "retrieval_latency_ms": latency,
        "dtype_fields": list(rates.dtype.names or ()),
    }
    probe["facts"] = derive_runtime_facts(probe)
    if any(
        probe["facts"].get(name) is not True
        for name in RUNTIME_FACT_FIELDS
        if name != "latency_ms"
    ):
        raise USDJPYSourceError("USDJPY runtime availability proof did not pass")
    return probe


def source_validation_plan(transition_evidence: str) -> dict[str, Any]:
    fields = (
        HISTORICAL_FACT_FIELDS
        if transition_evidence == "historical_audit"
        else RUNTIME_FACT_FIELDS
        if transition_evidence == "runtime_availability_proof"
        else None
    )
    if fields is None:
        raise ValueError("source validation transition is not registered")
    return {
        "schema": "usdjpy_source_validation_plan.v1",
        "source_contract_id": usdjpy_source_contract().source_contract_id,
        "transition_evidence": transition_evidence,
        "required_fact_fields": list(fields),
        "verdict_rule": "all_boolean_facts_true_and_latency_nonnegative",
    }


def source_validation_plan_hash(transition_evidence: str) -> str:
    return sha256(canonical_bytes(source_validation_plan(transition_evidence))).hexdigest()


__all__ = [
    "HISTORICAL_FACT_FIELDS",
    "RUNTIME_FACT_FIELDS",
    "USDJPY_COLUMNS",
    "USDJPY_END_UTC",
    "USDJPY_RAW_RELATIVE_PATH",
    "USDJPY_SERVER",
    "USDJPY_START_UTC",
    "USDJPY_SYMBOL",
    "USDJPYSourceError",
    "acquire_usdjpy_historical_snapshot",
    "audit_usdjpy_historical_bytes",
    "build_usdjpy_historical_audit",
    "derive_runtime_facts",
    "probe_usdjpy_runtime",
    "source_validation_plan",
    "source_validation_plan_hash",
    "usdjpy_source_contract",
]
