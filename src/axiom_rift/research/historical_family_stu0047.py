"""Exact immutable STU-0047 gap-path family."""

from axiom_rift.research.historical_fixed_four_family import (
    build_historical_fixed_four_family,
)


STU0047_HISTORICAL_FAMILY = build_historical_fixed_four_family(
    original_study_id="STU-0047",
    original_batch_id=(
        "batch:ac8964c29cf3de1af00f0c489ca27e2221bb5a7db008e5f80723aeb36b88a2de"
    ),
    target_historical_executable_id=(
        "executable:7d6965fae41cf40d73dab95cb11e2c62f26962610c6814b4fcb9337d52a0ba0f"
    ),
    rows=(
        (
            1,
            "residual_gap_after_first_bar-continuation-h6",
            "executable:7d6965fae41cf40d73dab95cb11e2c62f26962610c6814b4fcb9337d52a0ba0f",
            {
                "holding_bars": 6,
                "minimum_gap_minutes": 30,
                "profile": "residual_gap_after_first_bar",
                "selector_quantile_bp": 7000,
                "signal_sign": 1,
                "unknown_entry_action": "cancel_before_open",
            },
        ),
        (
            2,
            "residual_gap_after_first_bar-recovery-h6",
            "executable:cc0ec384262e15cd42da33ead9d2ac58b9a41083e355333924ecf0f9bab7badc",
            {
                "holding_bars": 6,
                "minimum_gap_minutes": 30,
                "profile": "residual_gap_after_first_bar",
                "selector_quantile_bp": 7000,
                "signal_sign": -1,
                "unknown_entry_action": "cancel_before_open",
            },
        ),
        (
            3,
            "gap_fill_fraction_after_first_bar-continuation-h6",
            "executable:32c20b02cefee954338c0aa8e59562ff3e2c774ac07145a2d326e85546fa79bd",
            {
                "holding_bars": 6,
                "minimum_gap_minutes": 30,
                "profile": "gap_fill_fraction_after_first_bar",
                "selector_quantile_bp": 7000,
                "signal_sign": 1,
                "unknown_entry_action": "cancel_before_open",
            },
        ),
        (
            4,
            "gap_fill_fraction_after_first_bar-recovery-h6",
            "executable:f33b5130bff13c97b76a376480115a8e5d4efabfbc1dec519cbe3ff73298e360",
            {
                "holding_bars": 6,
                "minimum_gap_minutes": 30,
                "profile": "gap_fill_fraction_after_first_bar",
                "selector_quantile_bp": 7000,
                "signal_sign": -1,
                "unknown_entry_action": "cancel_before_open",
            },
        ),
    ),
)


__all__ = ["STU0047_HISTORICAL_FAMILY"]
