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
from axiom_rift.research.external_observed_development import (
    ExternalObservedDevelopmentError,
    publish_immutable_raw_snapshot,
)
from axiom_rift.research.sources import (
    INDEPENDENT_POINT_IN_TIME_FACT_FIELDS,
    MT5_ABSOLUTE_TIME_AUTHORITY,
    MT5_DOCUMENTED_TIME_REFERENCE,
    MT5_DOCUMENTED_TIME_STANDARD,
    MT5_EPOCH_COORDINATE,
    MT5_OFFSET_POLICY,
    MT5_SESSION_TIME_AUTHORITY,
    SourceContract,
    SourceType,
    mt5_epoch_coordinate_observation_is_valid,
)


USDJPY_SYMBOL = "USDJPY"
USDJPY_SERVER = "FPMarketsSC-Live"
USDJPY_RAW_RELATIVE_PATH = "data/raw/mt5_bars/m5/USDJPY_M5_fixed.csv"
USDJPY_HISTORICAL_SNAPSHOT_SHA256 = (
    "364d94e662e5ee53e1092d11629deb8461575f82510a5b02d40f9ad46aabfa4e"
)
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
            "session": "FPMarkets_dynamic_forex_session_label_timezone_DST_unverified",
            "timezone": (
                f"{MT5_EPOCH_COORDINATE}_{MT5_ABSOLUTE_TIME_AUTHORITY}"
            ),
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
            "bar_open": "bid_open_at_MT5_epoch_coordinate",
            "bar_close": "bid_close_at_MT5_epoch_coordinate_plus_5m",
            "event_time": (
                "MT5_epoch_rendered_with_UTC_formatter_absolute_timezone_unverified"
            ),
            "information_complete_at": (
                "runtime_observed_bar_close_historical_point_in_time_unknown"
            ),
            "first_available_at": (
                "runtime_probe_observation_only_historical_unknown"
            ),
        },
        clock_semantics={
            "decision_alignment": "exact_same_MT5_epoch_coordinate_no_offset_inference",
            "timezone_conversion": "none_absolute_timezone_authority_unknown",
            "broker_session_label_timezone_dst_authority": (
                MT5_SESSION_TIME_AUTHORITY
            ),
            "documented_time_standard": MT5_DOCUMENTED_TIME_STANDARD,
            "documented_time_reference": MT5_DOCUMENTED_TIME_REFERENCE,
            "observed_time_coordinate": MT5_EPOCH_COORDINATE,
            "absolute_time_authority": MT5_ABSOLUTE_TIME_AUTHORITY,
            "offset_policy": MT5_OFFSET_POLICY,
        },
        availability_semantics={
            "acquisition": "MetaTrader5.copy_rates_range_local_terminal",
            "content_hash": f"sha256:{USDJPY_HISTORICAL_SNAPSHOT_SHA256}",
            "coverage": (
                "2018-05-07T01:00:00_through_2026-06-26T23:50:00_"
                "MT5_epoch_coordinate"
            ),
            "gap_policy": "exact_timestamp_inner_join_fail_closed_no_fill",
            "revision_or_vintage": (
                "historical_unknown_requires_independent_vintage_ledger"
            ),
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
    try:
        publish_immutable_raw_snapshot(root, "USDJPY", content)
    except ExternalObservedDevelopmentError as exc:
        raise USDJPYSourceError("USDJPY immutable raw publication failed") from exc
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
        frame["time"], format="%Y.%m.%d %H:%M:%S", errors="coerce"
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
    first = None if not valid_time.all() else time.iloc[0].isoformat()
    last = None if not valid_time.all() else time.iloc[-1].isoformat()
    expected_first = USDJPY_START_UTC.replace(tzinfo=None).isoformat()
    expected_last = USDJPY_END_UTC.replace(tzinfo=None).isoformat()
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
    negative_tick_volume_rows = int(
        (numeric["tick_volume"].to_numpy(dtype=float) < 0).sum()
    )
    negative_real_volume_rows = int(
        (numeric["real_volume"].to_numpy(dtype=float) < 0).sum()
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
        and negative_tick_volume_rows == 0
        and negative_real_volume_rows == 0
        and invalid_ohlc_rows == 0
    )
    coverage_ok = first == expected_first and last == expected_last
    raw_sha256 = sha256(content).hexdigest()
    facts = {
        "acquisition_observed": bool(acquisition_ok),
        "content_hash_verified": raw_sha256 == USDJPY_HISTORICAL_SNAPSHOT_SHA256,
        "event_time_audited": bool(valid_time.all() and off_grid_rows == 0),
        "information_complete_at_audited": False,
        "first_availability_audited": False,
        "coverage_audited": bool(coverage_ok),
        "gaps_audited": bool(structure_ok),
        "revision_or_vintage_audited": False,
    }
    return {
        "schema": "usdjpy_historical_audit_measurement.v3",
        "source_contract_id": usdjpy_source_contract().source_contract_id,
        "observed_at_utc": observed_at_utc,
        "evidence_scope": "current_mt5_epoch_coordinate_history_reconstruction",
        "freshness_scope": (
            "retrieval_observed_at_utc_not_historical_bar_availability"
        ),
        "timestamp_provenance": (
            "UTC_formatter_applied_to_MT5_epoch_absolute_timezone_unverified"
        ),
        "point_in_time_authority": {
            name: "unknown_no_independent_evidence"
            for name in sorted(INDEPENDENT_POINT_IN_TIME_FACT_FIELDS)
        },
        "raw_sha256": raw_sha256,
        "columns": list(USDJPY_COLUMNS),
        "row_count": int(len(frame)),
        "first_time_mt5_epoch_coordinate": first,
        "last_time_mt5_epoch_coordinate": last,
        "duplicate_rows": duplicate_rows,
        "non_monotonic_rows": non_monotonic_rows,
        "off_grid_rows": off_grid_rows,
        "nonfinite_rows": nonfinite_rows,
        "negative_spread_rows": negative_spread_rows,
        "negative_tick_volume_rows": negative_tick_volume_rows,
        "negative_real_volume_rows": negative_real_volume_rows,
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
        "absolute_time_authority",
        "broker_session_timezone_dst_authority",
        "documented_time_standard",
        "latest_rate_mt5_epoch_seconds",
        "mt5_epoch_minus_observed_utc_seconds",
        "mt5_epoch_sequence_coherent",
        "mt5_package_version",
        "observed_at_utc",
        "observed_utc_epoch_seconds",
        "offset_policy",
        "terminal_build",
        "tick_mt5_epoch_seconds",
        "time_coordinate",
        "evidence_scope",
        "freshness_scope",
        "dtype_fields",
    }
    if not required.issubset(probe):
        raise USDJPYSourceError("USDJPY runtime probe schema is incomplete")
    integer_fields = (
        "digits",
        "latest_rate_mt5_epoch_seconds",
        "mt5_epoch_minus_observed_utc_seconds",
        "observed_utc_epoch_seconds",
        "rates_count",
        "retrieval_latency_ms",
        "terminal_build",
        "tick_mt5_epoch_seconds",
    )
    if any(type(probe[name]) is not int for name in integer_fields):
        raise USDJPYSourceError("USDJPY runtime probe integer fields are invalid")
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
        and probe["rates_count"] >= 3
        and probe["finite_tick"] is True
        and mt5_epoch_coordinate_observation_is_valid(probe)
        and probe["evidence_scope"] == "local_terminal_runtime_observation"
        and probe["freshness_scope"]
        == "live_retrieval_latency_at_observed_at_utc"
    )
    return {
        "local_realtime_retrieval": bool(retrieval),
        "fresh": bool(retrieval and 0 <= latency <= 30_000),
        "synchronized": bool(retrieval and probe["consecutive_closed_bars"] is True),
        "complete_or_closed": bool(
            retrieval
            and (probe["closed_bar_available"] is True or probe["market_closed"] is True)
        ),
        "latency_ms": latency,
        "historical_runtime_field_parity": bool(exact_spec),
    }


def _completed_rate_epochs(
    epochs: np.ndarray,
    *,
    tick_mt5_epoch_seconds: int,
) -> np.ndarray:
    """Select completed bars on the observed MT5 coordinate only."""

    return epochs[epochs + 300 <= tick_mt5_epoch_seconds]


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
    tick_mt5_epoch_seconds = int(tick.time)
    latest_rate_mt5_epoch_seconds = (
        -1 if len(epochs) == 0 else int(np.max(epochs))
    )
    observed_utc_epoch_seconds = int(observed.timestamp())
    mt5_epoch_minus_observed_utc_seconds = (
        tick_mt5_epoch_seconds - observed_utc_epoch_seconds
    )
    mt5_epoch_sequence_coherent = bool(
        len(epochs) >= 1
        and 0
        <= tick_mt5_epoch_seconds - latest_rate_mt5_epoch_seconds
        <= 600
    )
    closed = _completed_rate_epochs(
        epochs,
        tick_mt5_epoch_seconds=tick_mt5_epoch_seconds,
    )
    consecutive = len(closed) >= 3 and bool(np.all(np.diff(closed[-3:]) == 300))
    tick_values = np.array([tick.bid, tick.ask, float(tick.time)], dtype=float)
    probe = {
        "schema": "usdjpy_runtime_probe_measurement.v2",
        "source_contract_id": usdjpy_source_contract().source_contract_id,
        "observed_at_utc": observed.isoformat().replace("+00:00", "Z"),
        "observed_utc_epoch_seconds": observed_utc_epoch_seconds,
        "evidence_scope": "local_terminal_runtime_observation",
        "freshness_scope": "live_retrieval_latency_at_observed_at_utc",
        "time_coordinate": MT5_EPOCH_COORDINATE,
        "documented_time_standard": MT5_DOCUMENTED_TIME_STANDARD,
        "absolute_time_authority": MT5_ABSOLUTE_TIME_AUTHORITY,
        "offset_policy": MT5_OFFSET_POLICY,
        "broker_session_timezone_dst_authority": MT5_SESSION_TIME_AUTHORITY,
        "mt5_package_version": str(mt5.__version__),
        "terminal_build": int(terminal.build),
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
        "tick_mt5_epoch_seconds": tick_mt5_epoch_seconds,
        "latest_rate_mt5_epoch_seconds": latest_rate_mt5_epoch_seconds,
        "mt5_epoch_minus_observed_utc_seconds": (
            mt5_epoch_minus_observed_utc_seconds
        ),
        "mt5_epoch_sequence_coherent": mt5_epoch_sequence_coherent,
        "latest_closed_bar_mt5_epoch_coordinate": (
            None
            if len(closed) == 0
            else datetime.fromtimestamp(int(closed[-1]), timezone.utc)
            .replace(tzinfo=None)
            .isoformat()
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
        "schema": "usdjpy_source_validation_plan.v3",
        "source_contract_id": usdjpy_source_contract().source_contract_id,
        "transition_evidence": transition_evidence,
        "required_fact_fields": list(fields),
        "verdict_rule": (
            "current_reconstruction_and_independent_point_in_time_facts_true_"
            "then_runtime_facts_true_and_latency_nonnegative"
        ),
    }


def source_validation_plan_hash(transition_evidence: str) -> str:
    return sha256(canonical_bytes(source_validation_plan(transition_evidence))).hexdigest()


__all__ = [
    "HISTORICAL_FACT_FIELDS",
    "RUNTIME_FACT_FIELDS",
    "USDJPY_COLUMNS",
    "USDJPY_END_UTC",
    "USDJPY_HISTORICAL_SNAPSHOT_SHA256",
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
