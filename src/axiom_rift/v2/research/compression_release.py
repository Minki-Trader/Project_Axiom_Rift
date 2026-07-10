"""Pure causal completed-bar compression-release event engine."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

import numpy as np

from axiom_rift.v2.features import BarArrays
from axiom_rift.v2.identity import sha256_payload


ATR_LOOKBACK = 24
BOX_LOOKBACK = 12
RELEASE_BUFFER_ATR = 0.05
RELEASE_CLV_LONG_MIN = 0.75
RELEASE_CLV_SHORT_MAX = 0.25
RELEASE_BODY_ATR_MIN = 0.30
REVERSAL_CLV_AFTER_UP_MAX = 0.35
REVERSAL_CLV_AFTER_DOWN_MIN = 0.65
REVERSAL_BODY_ATR_MIN = 0.20
CONTINUATION_WARMUP_BARS = ATR_LOOKBACK + 1
REVERSAL_WARMUP_BARS = CONTINUATION_WARMUP_BARS + 1
COMPRESSION_RELEASE_IMPLEMENTATION_KEY = "causal_compression_release_events_v1"


class CompressionReleaseError(ValueError):
    """Raised when the immutable bar container is structurally invalid."""


@dataclass(frozen=True)
class EventConfiguration:
    role: str
    event_kind: str
    compression_ratio_max: float | None
    atr_lookback: int = ATR_LOOKBACK
    box_lookback: int = BOX_LOOKBACK
    release_buffer_atr: float = RELEASE_BUFFER_ATR
    release_clv_long_min: float = RELEASE_CLV_LONG_MIN
    release_clv_short_max: float = RELEASE_CLV_SHORT_MAX
    release_body_atr_min: float = RELEASE_BODY_ATR_MIN
    reversal_clv_after_up_max: float = REVERSAL_CLV_AFTER_UP_MAX
    reversal_clv_after_down_min: float = REVERSAL_CLV_AFTER_DOWN_MIN
    reversal_body_atr_min: float = REVERSAL_BODY_ATR_MIN

    def __post_init__(self) -> None:
        if not self.role:
            raise CompressionReleaseError("configuration role must be non-empty")
        allowed = {"continuation", "failed_break_reversal", "unconditioned_breakout"}
        if self.event_kind not in allowed:
            raise CompressionReleaseError("unknown compression-release event kind")
        if self.event_kind == "unconditioned_breakout":
            if self.compression_ratio_max is not None:
                raise CompressionReleaseError("compression ablation may not have a ratio limit")
        elif self.compression_ratio_max is None or self.compression_ratio_max <= 0.0:
            raise CompressionReleaseError("conditioned events require a positive ratio limit")
        if self.atr_lookback != ATR_LOOKBACK or self.box_lookback != BOX_LOOKBACK:
            raise CompressionReleaseError("lookbacks are fixed by the executable identity")
        numeric = (
            self.release_buffer_atr,
            self.release_clv_long_min,
            self.release_clv_short_max,
            self.release_body_atr_min,
            self.reversal_clv_after_up_max,
            self.reversal_clv_after_down_min,
            self.reversal_body_atr_min,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise CompressionReleaseError("configuration thresholds must be finite")
        if (
            self.release_buffer_atr < 0.0
            or self.release_body_atr_min < 0.0
            or self.reversal_body_atr_min < 0.0
            or not 0.0 <= self.release_clv_short_max <= 1.0
            or not 0.0 <= self.release_clv_long_min <= 1.0
            or not 0.0 <= self.reversal_clv_after_up_max <= 1.0
            or not 0.0 <= self.reversal_clv_after_down_min <= 1.0
        ):
            raise CompressionReleaseError("configuration thresholds are outside their domains")
        if (
            self.compression_ratio_max is not None
            and not math.isfinite(self.compression_ratio_max)
        ):
            raise CompressionReleaseError("compression ratio must be finite")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_compression_release_configuration_v1",
            "role": self.role,
            "event_kind": self.event_kind,
            "compression_ratio_max": self.compression_ratio_max,
            "atr_lookback": self.atr_lookback,
            "box_lookback": self.box_lookback,
            "release_buffer_atr": self.release_buffer_atr,
            "release_clv_long_min": self.release_clv_long_min,
            "release_clv_short_max": self.release_clv_short_max,
            "release_body_atr_min": self.release_body_atr_min,
            "reversal_clv_after_up_max": self.reversal_clv_after_up_max,
            "reversal_clv_after_down_min": self.reversal_clv_after_down_min,
            "reversal_body_atr_min": self.reversal_body_atr_min,
        }

    @property
    def identity_sha256(self) -> str:
        return sha256_payload(self.identity_payload())


EVENT_CONFIGURATIONS = (
    EventConfiguration("continuation_low", "continuation", 2.0),
    EventConfiguration("continuation_base", "continuation", 2.5),
    EventConfiguration("continuation_high", "continuation", 3.0),
    EventConfiguration("failed_break_reversal", "failed_break_reversal", 2.5),
    EventConfiguration("compression_ablation", "unconditioned_breakout", None),
)


def executable_identity_payload() -> dict[str, Any]:
    return {
        "schema": "axiom_rift_v2_compression_release_executable_v1",
        "implementation_key": COMPRESSION_RELEASE_IMPLEMENTATION_KEY,
        "causal_decision": "completed_bar_only",
        "configurations": [row.identity_payload() for row in EVENT_CONFIGURATIONS],
    }


COMPRESSION_RELEASE_EXECUTABLE_SHA256 = sha256_payload(executable_identity_payload())


@dataclass(frozen=True)
class CompressionFeatures:
    decision_index: int
    decision_time: datetime
    release_index: int
    atr_24: float | None
    box_low: float | None
    box_high: float | None
    compression_ratio: float | None
    release_close_location: float | None
    release_body_atr: float | None
    release_direction: int
    confirmation_close_location: float | None
    confirmation_body_atr: float | None
    valid: bool
    reason: str


@dataclass(frozen=True)
class CompressionSignal:
    role: str
    configuration_sha256: str
    decision_index: int
    decision_time: datetime
    direction: int
    score: float
    valid: bool
    reason: str


@dataclass(frozen=True)
class CompressionEvaluation:
    configuration: EventConfiguration
    configuration_sha256: str
    executable_sha256: str
    features: tuple[CompressionFeatures, ...]
    signals: tuple[CompressionSignal, ...]

    @property
    def directions(self) -> tuple[int, ...]:
        return tuple(row.direction for row in self.signals)

    @property
    def scores(self) -> tuple[float, ...]:
        return tuple(row.score for row in self.signals)

    @property
    def valid_mask(self) -> tuple[bool, ...]:
        return tuple(row.valid for row in self.signals)

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(row.reason for row in self.signals)


def _validate_container(bars: BarArrays) -> None:
    size = len(bars)
    for name in ("open", "high", "low", "close", "tick_volume", "spread"):
        values = getattr(bars, name)
        if not isinstance(values, np.ndarray) or values.ndim != 1 or len(values) != size:
            raise CompressionReleaseError(f"bars.{name} must be a one-dimensional aligned array")
    if any(left >= right for left, right in zip(bars.time, bars.time[1:])):
        raise CompressionReleaseError("bar times must be strictly increasing")


def _price_reason(bars: BarArrays, index: int) -> str | None:
    opening = float(bars.open[index])
    high = float(bars.high[index])
    low = float(bars.low[index])
    close = float(bars.close[index])
    if not all(math.isfinite(value) for value in (opening, high, low, close)):
        return "nonfinite_price"
    if min(opening, high, low, close) <= 0.0:
        return "nonpositive_price"
    if high < low or opening < low or opening > high or close < low or close > high:
        return "invalid_ohlc"
    return None


def _true_range(bars: BarArrays, index: int) -> float | None:
    if index <= 0 or _price_reason(bars, index) or _price_reason(bars, index - 1):
        return None
    high = float(bars.high[index])
    low = float(bars.low[index])
    previous_close = float(bars.close[index - 1])
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def _invalid_feature(bars: BarArrays, index: int, release_index: int, reason: str) -> CompressionFeatures:
    return CompressionFeatures(
        index,
        bars.time[index],
        release_index,
        None,
        None,
        None,
        None,
        None,
        None,
        0,
        None,
        None,
        False,
        reason,
    )


def _signal(config: EventConfiguration, bars: BarArrays, index: int, direction: int, score: float, valid: bool, reason: str) -> CompressionSignal:
    return CompressionSignal(
        config.role,
        config.identity_sha256,
        index,
        bars.time[index],
        direction,
        float(score),
        valid,
        reason,
    )


def _release_context(
    bars: BarArrays,
    index: int,
    config: EventConfiguration,
) -> tuple[CompressionFeatures, int, float] | CompressionFeatures:
    if index < CONTINUATION_WARMUP_BARS:
        return _invalid_feature(bars, index, index, "warmup")
    start = index - ATR_LOOKBACK
    ranges = tuple(_true_range(bars, item) for item in range(start, index))
    if any(value is None for value in ranges):
        return _invalid_feature(bars, index, index, "invalid_atr_window")
    atr = float(sum(value for value in ranges if value is not None) / ATR_LOOKBACK)
    if not math.isfinite(atr) or atr <= 0.0:
        return _invalid_feature(bars, index, index, "zero_atr")
    if any(_price_reason(bars, item) for item in range(index - BOX_LOOKBACK, index + 1)):
        return _invalid_feature(bars, index, index, "invalid_price_window")
    box_low = float(np.min(bars.low[index - BOX_LOOKBACK : index]))
    box_high = float(np.max(bars.high[index - BOX_LOOKBACK : index]))
    if box_high <= box_low:
        return _invalid_feature(bars, index, index, "zero_box_range")
    bar_range = float(bars.high[index] - bars.low[index])
    if bar_range <= 0.0:
        return _invalid_feature(bars, index, index, "zero_release_range")
    close = float(bars.close[index])
    clv = (close - float(bars.low[index])) / bar_range
    body_atr = abs(close - float(bars.open[index])) / atr
    ratio = (box_high - box_low) / atr
    buffer = config.release_buffer_atr * atr
    direction = 0
    if (
        close > box_high + buffer
        and clv >= config.release_clv_long_min
        and body_atr >= config.release_body_atr_min
    ):
        direction = 1
    elif (
        close < box_low - buffer
        and clv <= config.release_clv_short_max
        and body_atr >= config.release_body_atr_min
    ):
        direction = -1
    feature = CompressionFeatures(
        index,
        bars.time[index],
        index,
        atr,
        box_low,
        box_high,
        ratio,
        clv,
        body_atr,
        direction,
        None,
        None,
        True,
        "ok",
    )
    score = 0.0
    if direction > 0:
        score = (close - box_high) / atr
    elif direction < 0:
        score = -(box_low - close) / atr
    return feature, direction, float(score)


def _continuation_row(bars: BarArrays, index: int, config: EventConfiguration) -> tuple[CompressionFeatures, CompressionSignal]:
    context = _release_context(bars, index, config)
    if isinstance(context, CompressionFeatures):
        return context, _signal(config, bars, index, 0, 0.0, False, context.reason)
    feature, direction, score = context
    if config.compression_ratio_max is not None and feature.compression_ratio is not None and feature.compression_ratio > config.compression_ratio_max:
        return feature, _signal(config, bars, index, 0, 0.0, True, "not_compressed")
    if direction == 0:
        return feature, _signal(config, bars, index, 0, 0.0, True, "no_release")
    return feature, _signal(config, bars, index, direction, score, True, "triggered")


def _reversal_row(bars: BarArrays, index: int, config: EventConfiguration) -> tuple[CompressionFeatures, CompressionSignal]:
    if index < REVERSAL_WARMUP_BARS:
        feature = _invalid_feature(bars, index, max(0, index - 1), "warmup")
        return feature, _signal(config, bars, index, 0, 0.0, False, "warmup")
    prior = _release_context(bars, index - 1, config)
    if isinstance(prior, CompressionFeatures):
        feature = _invalid_feature(bars, index, index - 1, prior.reason)
        return feature, _signal(config, bars, index, 0, 0.0, False, prior.reason)
    release, release_direction, _ = prior
    current_reason = _price_reason(bars, index)
    if current_reason is not None:
        feature = _invalid_feature(bars, index, index - 1, current_reason)
        return feature, _signal(config, bars, index, 0, 0.0, False, current_reason)
    current_range = float(bars.high[index] - bars.low[index])
    if current_range <= 0.0:
        feature = _invalid_feature(bars, index, index - 1, "zero_confirmation_range")
        return feature, _signal(config, bars, index, 0, 0.0, False, feature.reason)
    assert release.atr_24 is not None and release.box_low is not None and release.box_high is not None
    close = float(bars.close[index])
    clv = (close - float(bars.low[index])) / current_range
    body_atr = abs(close - float(bars.open[index])) / release.atr_24
    feature = CompressionFeatures(
        index,
        bars.time[index],
        index - 1,
        release.atr_24,
        release.box_low,
        release.box_high,
        release.compression_ratio,
        release.release_close_location,
        release.release_body_atr,
        release_direction,
        clv,
        body_atr,
        True,
        "ok",
    )
    if (
        release.compression_ratio is None
        or config.compression_ratio_max is None
        or release.compression_ratio > config.compression_ratio_max
        or release_direction == 0
    ):
        return feature, _signal(config, bars, index, 0, 0.0, True, "no_prior_compressed_release")
    if not release.box_low < close < release.box_high:
        return feature, _signal(config, bars, index, 0, 0.0, True, "no_strict_reentry")
    if body_atr < config.reversal_body_atr_min:
        return feature, _signal(config, bars, index, 0, 0.0, True, "weak_reversal_body")
    if release_direction > 0:
        if clv > config.reversal_clv_after_up_max:
            return feature, _signal(config, bars, index, 0, 0.0, True, "no_reversal_clv")
        score = -(release.box_high - close) / release.atr_24
        direction = -1
    else:
        if clv < config.reversal_clv_after_down_min:
            return feature, _signal(config, bars, index, 0, 0.0, True, "no_reversal_clv")
        score = (close - release.box_low) / release.atr_24
        direction = 1
    return feature, _signal(config, bars, index, direction, score, True, "triggered")


def evaluate_configuration(bars: BarArrays, configuration: EventConfiguration) -> CompressionEvaluation:
    """Evaluate one role without I/O, state mutation, or future-bar access."""

    _validate_container(bars)
    features: list[CompressionFeatures] = []
    signals: list[CompressionSignal] = []
    for index in range(len(bars)):
        if configuration.event_kind == "failed_break_reversal":
            feature, signal = _reversal_row(bars, index, configuration)
        else:
            feature, signal = _continuation_row(bars, index, configuration)
        features.append(feature)
        signals.append(signal)
    return CompressionEvaluation(
        configuration,
        configuration.identity_sha256,
        COMPRESSION_RELEASE_EXECUTABLE_SHA256,
        tuple(features),
        tuple(signals),
    )


def evaluate_compression_release(
    bars: BarArrays,
    configurations: Iterable[EventConfiguration] = EVENT_CONFIGURATIONS,
) -> tuple[CompressionEvaluation, ...]:
    """Evaluate the frozen five-role surface in caller-supplied order."""

    frozen = tuple(configurations)
    return tuple(evaluate_configuration(bars, configuration) for configuration in frozen)


__all__ = [
    "COMPRESSION_RELEASE_EXECUTABLE_SHA256",
    "COMPRESSION_RELEASE_IMPLEMENTATION_KEY",
    "CompressionEvaluation",
    "CompressionFeatures",
    "CompressionReleaseError",
    "CompressionSignal",
    "EVENT_CONFIGURATIONS",
    "EventConfiguration",
    "evaluate_compression_release",
    "evaluate_configuration",
    "executable_identity_payload",
]
