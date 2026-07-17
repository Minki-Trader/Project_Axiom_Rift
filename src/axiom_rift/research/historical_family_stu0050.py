"""Exact immutable STU-0050 volatility-duration family."""

from axiom_rift.research.historical_fixed_four_family import (
    build_historical_fixed_four_family,
)


STU0050_HISTORICAL_FAMILY = build_historical_fixed_four_family(
    original_study_id="STU-0050",
    original_batch_id=(
        "batch:a1ef094c696c05fcad9a29ab3869039b8395074db23b1cdf55449cae753155d1"
    ),
    target_historical_executable_id=(
        "executable:88ea5f16e0a92c9aeacc160bf899013fee1061af2d700aa61f062b07afb0a095"
    ),
    rows=(
        (
            1,
            "volatility_level_96_576-follow-h12",
            "executable:88ea5f16e0a92c9aeacc160bf899013fee1061af2d700aa61f062b07afb0a095",
            {
                "holding_bars": 12,
                "profile": "volatility_level_96_576",
                "selector_quantile_bp": 7000,
                "signal_sign": 1,
                "state_window": 576,
                "unknown_entry_action": "cancel_before_open",
                "volatility_window": 96,
            },
        ),
        (
            2,
            "volatility_level_96_576-reverse-h12",
            "executable:ab0e239807092e4d499788651ec8ab222330165c9d52df8f76570f34f777b2a6",
            {
                "holding_bars": 12,
                "profile": "volatility_level_96_576",
                "selector_quantile_bp": 7000,
                "signal_sign": -1,
                "state_window": 576,
                "unknown_entry_action": "cancel_before_open",
                "volatility_window": 96,
            },
        ),
        (
            3,
            "volatility_duration_96_576-follow-h12",
            "executable:f1171e5747b2c95c0f20a45cf1274fc4d39a8c0e5914c5b5706c87941a6e1af3",
            {
                "holding_bars": 12,
                "profile": "volatility_duration_96_576",
                "selector_quantile_bp": 7000,
                "signal_sign": 1,
                "state_window": 576,
                "unknown_entry_action": "cancel_before_open",
                "volatility_window": 96,
            },
        ),
        (
            4,
            "volatility_duration_96_576-reverse-h12",
            "executable:2a0751ab91e0aeb0dc3f07d4c8890cf019ff1698cac3377218e3976fc3e945a5",
            {
                "holding_bars": 12,
                "profile": "volatility_duration_96_576",
                "selector_quantile_bp": 7000,
                "signal_sign": -1,
                "state_window": 576,
                "unknown_entry_action": "cancel_before_open",
                "volatility_window": 96,
            },
        ),
    ),
)


__all__ = ["STU0050_HISTORICAL_FAMILY"]
