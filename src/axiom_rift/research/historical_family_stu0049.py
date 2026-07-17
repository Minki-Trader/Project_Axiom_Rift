"""Exact immutable STU-0049 drawdown-interaction family."""

from axiom_rift.research.historical_fixed_four_family import (
    build_historical_fixed_four_family,
)


STU0049_HISTORICAL_FAMILY = build_historical_fixed_four_family(
    original_study_id="STU-0049",
    original_batch_id=(
        "batch:0ba429867a477cb4606730735ab6efcc69fa97ef74d20b7dc955afb63e553503"
    ),
    target_historical_executable_id=(
        "executable:5ddc970ceaf451377f49c3bf17f7b2b026175381cf28c2d375ec966a8c5f90a4"
    ),
    rows=(
        (
            1,
            "depth_duration_interaction_576-follow-h12",
            "executable:5ddc970ceaf451377f49c3bf17f7b2b026175381cf28c2d375ec966a8c5f90a4",
            {
                "holding_bars": 12,
                "lookback_bars": 576,
                "profile": "depth_duration_interaction_576",
                "selector_quantile_bp": 8500,
                "signal_sign": 1,
                "unknown_entry_action": "cancel_before_open",
            },
        ),
        (
            2,
            "depth_duration_interaction_576-reverse-h12",
            "executable:72eb24bf5f73a141d193fc23b4f12023d98e600fbe4bdb08efdb490d6c962396",
            {
                "holding_bars": 12,
                "lookback_bars": 576,
                "profile": "depth_duration_interaction_576",
                "selector_quantile_bp": 8500,
                "signal_sign": -1,
                "unknown_entry_action": "cancel_before_open",
            },
        ),
        (
            3,
            "drawdown_recovery_velocity_12-follow-h12",
            "executable:3ff3f7bbbed7193984a3d3a94fdd11e3c5849256a2b8d0b953a3813894e44318",
            {
                "holding_bars": 12,
                "lookback_bars": 576,
                "profile": "drawdown_recovery_velocity_12",
                "selector_quantile_bp": 8500,
                "signal_sign": 1,
                "unknown_entry_action": "cancel_before_open",
            },
        ),
        (
            4,
            "drawdown_recovery_velocity_12-reverse-h12",
            "executable:fb58cdf8f6fabff38deb72cb4c089fd759b0abb7bfe37ea74b7415caae83a26e",
            {
                "holding_bars": 12,
                "lookback_bars": 576,
                "profile": "drawdown_recovery_velocity_12",
                "selector_quantile_bp": 8500,
                "signal_sign": -1,
                "unknown_entry_action": "cancel_before_open",
            },
        ),
    ),
)


__all__ = ["STU0049_HISTORICAL_FAMILY"]
