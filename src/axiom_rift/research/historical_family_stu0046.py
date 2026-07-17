"""Exact immutable STU-0046 gap-event family."""

from axiom_rift.research.historical_fixed_four_family import (
    build_historical_fixed_four_family,
)


STU0046_HISTORICAL_FAMILY = build_historical_fixed_four_family(
    original_study_id="STU-0046",
    original_batch_id=(
        "batch:dc34ce62b224dc292e2b39429b6a82fe3a99fa7ab437eeef19c9bbe24fd35739"
    ),
    target_historical_executable_id=(
        "executable:7af6e5bc53cc96315fb9db9652fda221243188e6ec00209e21180341b51bd536"
    ),
    rows=(
        (
            1,
            "open_gap_30m-continuation-h12",
            "executable:7af6e5bc53cc96315fb9db9652fda221243188e6ec00209e21180341b51bd536",
            {
                "holding_bars": 12,
                "minimum_gap_minutes": 30,
                "profile": "open_gap_30m",
                "selector_quantile_bp": 7000,
                "signal_sign": 1,
                "unknown_entry_action": "cancel_before_open",
            },
        ),
        (
            2,
            "open_gap_30m-recovery-h12",
            "executable:a5223063c1cbaad273fa6a88ce986c89f05d6f8dad6ab059fb8e0052e4228afa",
            {
                "holding_bars": 12,
                "minimum_gap_minutes": 30,
                "profile": "open_gap_30m",
                "selector_quantile_bp": 7000,
                "signal_sign": -1,
                "unknown_entry_action": "cancel_before_open",
            },
        ),
        (
            3,
            "first_bar_response_30m-continuation-h12",
            "executable:109b5e7e865a5c6bf0fffb5ab8aec17d01cfa6805368545ead58537676c2b903",
            {
                "holding_bars": 12,
                "minimum_gap_minutes": 30,
                "profile": "first_bar_response_30m",
                "selector_quantile_bp": 7000,
                "signal_sign": 1,
                "unknown_entry_action": "cancel_before_open",
            },
        ),
        (
            4,
            "first_bar_response_30m-recovery-h12",
            "executable:66b951f0a1dd61396d5c350ba4d471914b6ebcebb4dcefd5777520fb0f47a335",
            {
                "holding_bars": 12,
                "minimum_gap_minutes": 30,
                "profile": "first_bar_response_30m",
                "selector_quantile_bp": 7000,
                "signal_sign": -1,
                "unknown_entry_action": "cancel_before_open",
            },
        ),
    ),
)


__all__ = ["STU0046_HISTORICAL_FAMILY"]
