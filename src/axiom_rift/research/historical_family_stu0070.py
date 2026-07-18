"""Frozen two-policy family reconstructed from the STU-0070 trial stream."""

from __future__ import annotations

from axiom_rift.research.historical_family_binding import (
    HistoricalFamilySpec,
    HistoricalMemberSpec,
    PrimaryControlBinding,
)


_CONTROL = (
    "executable:4906f193080ed2dab041aaa26420b8dcceb1df606922f1b14bc1723ef439df2f"
)
_TARGET = (
    "executable:33ad1cd7b5eabe24d65fad22be9757826a19fa20f6a2e16f871c6ff32a68a9d3"
)
_COMMON = {
    "holding_bars": 48,
    "label_profile": "first_passage_label_48",
    "selector_quantile_bp": 8500,
    "signal_sign": 1,
    "spread_limit_milli": 1200,
    "spread_reference_bars": 288,
}


STU0070_HISTORICAL_FAMILY = HistoricalFamilySpec(
    original_study_id="STU-0070",
    original_batch_id=(
        "batch:74edbc027f84120675081e0d1d885b4ee918fccd37e7413f35c721b879a332ab"
    ),
    target_historical_executable_id=_TARGET,
    members=(
        HistoricalMemberSpec(
            ordinal=1,
            configuration_id="unconditional_next_open-direct-h48",
            historical_reference_executable_id=_CONTROL,
            parameters={
                **_COMMON,
                "execution_policy": "unconditional_next_open",
            },
        ),
        HistoricalMemberSpec(
            ordinal=2,
            configuration_id="causal_spread_abstention-direct-h48",
            historical_reference_executable_id=_TARGET,
            parameters={
                **_COMMON,
                "execution_policy": "causal_spread_abstention",
            },
        ),
    ),
    controls=(
        PrimaryControlBinding(
            subject_historical_executable_id=_CONTROL,
            primary_control_historical_executable_id=_TARGET,
        ),
        PrimaryControlBinding(
            subject_historical_executable_id=_TARGET,
            primary_control_historical_executable_id=_CONTROL,
        ),
    ),
)


__all__ = ["STU0070_HISTORICAL_FAMILY"]
