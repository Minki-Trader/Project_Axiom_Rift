"""FPMarkets VIX M5 source contract for eligibility-only research."""

from __future__ import annotations

from axiom_rift.research.sources import (
    MT5_ABSOLUTE_TIME_AUTHORITY,
    MT5_DOCUMENTED_TIME_REFERENCE,
    MT5_DOCUMENTED_TIME_STANDARD,
    MT5_EPOCH_COORDINATE,
    MT5_OFFSET_POLICY,
    MT5_SESSION_TIME_AUTHORITY,
    SourceContract,
    SourceType,
)


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
            "session": (
                "FPMarkets_dynamic_broker_session_label_timezone_DST_unverified"
            ),
            "timezone": (
                f"{MT5_EPOCH_COORDINATE}_{MT5_ABSOLUTE_TIME_AUTHORITY}"
            ),
            "underlier": "volatility_index_future",
            "roll": (
                "broker_continuous_front_future_alias_historical_roll_"
                "not_identifiable"
            ),
            "adjustment": "historical_adjustment_method_not_identifiable",
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
            "decision_alignment": (
                "exact_same_MT5_epoch_coordinate_no_offset_inference"
            ),
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
            "content_hash": "sha256_of_deterministic_csv_bytes",
            "coverage": (
                "2022-01-03T01:00:00_through_2026-04-30T23:55:00_"
                "MT5_epoch_coordinate"
            ),
            "gap_policy": "exact_timestamp_inner_join_fail_closed_no_fill",
            "revision_or_vintage": (
                "historical_roll_adjustment_and_vintage_not_identifiable_"
                "context_only"
            ),
            "causal_ttl_seconds": 360,
            "eligibility_receipt_ttl_seconds": 21_600,
            "runtime_retrieval_method": "copy_rates_from_pos_plus_symbol_tick",
        },
    )


__all__ = ["VIX_COLUMNS", "VIX_SERVER", "VIX_SYMBOL", "vix_source_contract"]
