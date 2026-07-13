"""FPMarkets VIX M5 source contract for eligibility-only research."""

from __future__ import annotations

from axiom_rift.research.sources import SourceContract, SourceType


VIX_SYMBOL = "VIX"
VIX_SERVER = "FPMarketsSC-Live"
VIX_COLUMNS = (
    "time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
)


def vix_source_contract() -> SourceContract:
    """Bind the exact broker surface without claiming unverified roll semantics."""

    return SourceContract(
        display_name="FPMarkets VIX rolling futures CFD M5 bid bars",
        canonical_instrument="FPMarkets_VIX_rolling_futures_CFD_M5",
        runtime_identifier=VIX_SYMBOL,
        source_type=SourceType.BAR,
        instrument_semantics={
            "asset_type": "rolling_futures_cfd",
            "quote_basis": "bid_bar",
            "contract_size": "1.0",
            "currency": "USD",
            "digits": 2,
            "point": "0.01",
            "session": "FPMarkets_dynamic_broker_session",
            "timezone": "MT5_epoch_UTC",
            "underlier": "volatility_index_future",
            "roll": "broker_continuous_front_future_alias_requires_audit",
            "adjustment": "unverified_pending_historical_roll_audit",
        },
        mapping_semantics={
            "runtime_symbol": VIX_SYMBOL,
            "mapping_rule": "exact_FPMarkets_local_symbol_no_substitute",
            "description_must_identify_current_expiring_future": True,
        },
        schema_semantics={
            "columns": list(VIX_COLUMNS),
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
            "content_hash": "sha256_of_deterministic_csv_bytes",
            "coverage": "2022-01-03T01:00:00Z_through_2026-04-30T23:55:00Z",
            "gap_policy": "exact_timestamp_inner_join_fail_closed_no_fill",
            "revision_or_vintage": "broker_snapshot_and_roll_semantics_require_audit",
            "causal_ttl_seconds": 360,
            "eligibility_receipt_ttl_seconds": 21_600,
            "runtime_retrieval_method": "copy_rates_from_pos_plus_symbol_tick",
        },
    )


__all__ = ["VIX_COLUMNS", "VIX_SERVER", "VIX_SYMBOL", "vix_source_contract"]
