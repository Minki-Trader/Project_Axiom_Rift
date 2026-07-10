"""Pure causal direction-filtered compression-release event surface."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable

from axiom_rift.v2.features import BarArrays
from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.research.compression_release import (
    COMPRESSION_RELEASE_EXECUTABLE_SHA256,
    CompressionEvaluation,
    CompressionReleaseError,
    EventConfiguration,
    evaluate_configuration as evaluate_event_configuration,
)


DIRECTIONAL_REVERSAL_IMPLEMENTATION_KEY = "causal_directional_reversal_events_v1"
DIRECTION_FILTERED_REASON = "direction_filtered"


@dataclass(frozen=True)
class DirectionalEventConfiguration(EventConfiguration):
    """Compression-release configuration with a preregistered direction."""

    direction_filter: int = -1

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.direction_filter not in {-1, 1}:
            raise CompressionReleaseError("direction filter must be -1 or 1")

    def identity_payload(self) -> dict[str, Any]:
        payload = super().identity_payload()
        payload["schema"] = "axiom_rift_v2_directional_reversal_configuration_v1"
        payload["direction_filter"] = self.direction_filter
        return payload

    def as_event_configuration(self) -> EventConfiguration:
        """Return the behavior-equivalent unfiltered base configuration."""

        return EventConfiguration(
            role=self.role,
            event_kind=self.event_kind,
            compression_ratio_max=self.compression_ratio_max,
            atr_lookback=self.atr_lookback,
            box_lookback=self.box_lookback,
            release_buffer_atr=self.release_buffer_atr,
            release_clv_long_min=self.release_clv_long_min,
            release_clv_short_max=self.release_clv_short_max,
            release_body_atr_min=self.release_body_atr_min,
            reversal_clv_after_up_max=self.reversal_clv_after_up_max,
            reversal_clv_after_down_min=self.reversal_clv_after_down_min,
            reversal_body_atr_min=self.reversal_body_atr_min,
        )


DIRECTIONAL_EVENT_CONFIGURATIONS = (
    DirectionalEventConfiguration(
        "short_reversal_low",
        "failed_break_reversal",
        2.0,
        direction_filter=-1,
    ),
    DirectionalEventConfiguration(
        "short_reversal_base",
        "failed_break_reversal",
        2.5,
        direction_filter=-1,
    ),
    DirectionalEventConfiguration(
        "short_reversal_high",
        "failed_break_reversal",
        3.0,
        direction_filter=-1,
    ),
    DirectionalEventConfiguration(
        "long_reversal_control",
        "failed_break_reversal",
        2.5,
        direction_filter=1,
    ),
    DirectionalEventConfiguration(
        "short_continuation_control",
        "continuation",
        2.5,
        direction_filter=-1,
    ),
)

# Short alias for callers that already name the module-level surface.
DIRECTIONAL_CONFIGURATIONS = DIRECTIONAL_EVENT_CONFIGURATIONS


def directional_executable_identity_payload() -> dict[str, Any]:
    return {
        "schema": "axiom_rift_v2_directional_reversal_executable_v1",
        "implementation_key": DIRECTIONAL_REVERSAL_IMPLEMENTATION_KEY,
        "base_executable_sha256": COMPRESSION_RELEASE_EXECUTABLE_SHA256,
        "causal_decision": "completed_bar_only",
        "direction_filter_stage": "before_downstream_trade_and_cost_logic",
        "configurations": [
            row.identity_payload() for row in DIRECTIONAL_EVENT_CONFIGURATIONS
        ],
    }


DIRECTIONAL_REVERSAL_EXECUTABLE_SHA256 = sha256_payload(
    directional_executable_identity_payload()
)


def evaluate_directional_configuration(
    bars: BarArrays,
    configuration: DirectionalEventConfiguration,
) -> CompressionEvaluation:
    """Evaluate one role and suppress only opposite nonzero directions."""

    base = evaluate_event_configuration(bars, configuration.as_event_configuration())
    configuration_sha256 = configuration.identity_sha256
    signals = []
    for signal in base.signals:
        changes: dict[str, Any] = {
            "role": configuration.role,
            "configuration_sha256": configuration_sha256,
        }
        if signal.direction != 0 and signal.direction != configuration.direction_filter:
            changes.update(
                direction=0,
                score=0.0,
                reason=DIRECTION_FILTERED_REASON,
            )
        signals.append(replace(signal, **changes))
    return CompressionEvaluation(
        configuration=configuration,
        configuration_sha256=configuration_sha256,
        executable_sha256=DIRECTIONAL_REVERSAL_EXECUTABLE_SHA256,
        features=base.features,
        signals=tuple(signals),
    )


def evaluate_directional_reversal(
    bars: BarArrays,
    configurations: Iterable[DirectionalEventConfiguration] = (
        DIRECTIONAL_EVENT_CONFIGURATIONS
    ),
) -> tuple[CompressionEvaluation, ...]:
    """Evaluate the frozen five-role surface in caller-supplied order."""

    frozen = tuple(configurations)
    return tuple(
        evaluate_directional_configuration(bars, configuration)
        for configuration in frozen
    )


__all__ = [
    "DIRECTIONAL_CONFIGURATIONS",
    "DIRECTIONAL_EVENT_CONFIGURATIONS",
    "DIRECTIONAL_REVERSAL_EXECUTABLE_SHA256",
    "DIRECTIONAL_REVERSAL_IMPLEMENTATION_KEY",
    "DIRECTION_FILTERED_REASON",
    "DirectionalEventConfiguration",
    "directional_executable_identity_payload",
    "evaluate_directional_configuration",
    "evaluate_directional_reversal",
]
