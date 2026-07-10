"""Pure causal cash-open gap-failure session event surface.

The event uses broker-server timestamp proxies bound to the active FPMarkets
clock rule.  It does not claim an exchange calendar.  The delayed control
caches the completed 16:30 trigger and emits at the completed 17:30 bar without
reading intervening OHLC values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from typing import Any, Iterable

import numpy as np

from axiom_rift.v2.data.clock import ClockError, ClockPolicy
from axiom_rift.v2.features import BarArrays
from axiom_rift.v2.identity import sha256_payload


ATR_LOOKBACK = 24
GAP_ATR_MIN = 0.50
FAILURE_BODY_ATR_MIN = 0.20
UP_GAP_FAILURE_CLV_MAX = 0.35
DOWN_GAP_FAILURE_CLV_MIN = 0.65
GAP_RETRACE_MIN = 0.25
CASH_OPEN_SERVER_TIME = time(16, 30)
PRIOR_CASH_CLOSE_SERVER_TIME = time(22, 55)
IMMEDIATE_DELAY_MINUTES = 0
PLUS_60_DELAY_MINUTES = 60
SESSION_GAP_FAILURE_IMPLEMENTATION_KEY = "causal_cash_open_gap_failure_events_v1"

CLOCK_POLICY = ClockPolicy()
CLOCK_AUTHORITY_VERIFIED = False
CALENDAR_AUTHORITY = False


class SessionGapFailureError(ValueError):
    """Raised when an input container or frozen configuration is invalid."""


def clock_identity_payload() -> dict[str, Any]:
    """Return the explicit non-calendar clock identity used by the surface."""

    return {
        "rule_id": CLOCK_POLICY.rule_id,
        "market_timezone": CLOCK_POLICY.market_timezone,
        "bar_minutes": CLOCK_POLICY.bar_minutes,
        "server_minus_market_hours": CLOCK_POLICY.server_minus_market_hours,
        "authority": CLOCK_POLICY.authority,
        "authority_verified": CLOCK_AUTHORITY_VERIFIED,
        "calendar_authority": CALENDAR_AUTHORITY,
        "cash_open_server_bar_proxy": CASH_OPEN_SERVER_TIME.strftime("%H:%M"),
        "prior_cash_close_server_bar_proxy": (
            PRIOR_CASH_CLOSE_SERVER_TIME.strftime("%H:%M")
        ),
    }


@dataclass(frozen=True)
class SessionGapConfiguration:
    """One structural role on the matched cash-open failure event set."""

    role: str
    direction_mode: str
    decision_delay_minutes: int
    event_kind: str = "cash_open_gap_failure"
    atr_lookback: int = ATR_LOOKBACK
    gap_atr_min: float = GAP_ATR_MIN
    failure_body_atr_min: float = FAILURE_BODY_ATR_MIN
    up_gap_failure_clv_max: float = UP_GAP_FAILURE_CLV_MAX
    down_gap_failure_clv_min: float = DOWN_GAP_FAILURE_CLV_MIN
    gap_retrace_min: float = GAP_RETRACE_MIN

    def __post_init__(self) -> None:
        if not self.role or not self.role.isascii():
            raise SessionGapFailureError("configuration role must be nonempty ASCII")
        if self.event_kind != "cash_open_gap_failure":
            raise SessionGapFailureError("session event kind is fixed")
        if self.direction_mode not in {"reversal", "continuation"}:
            raise SessionGapFailureError("unknown session direction mode")
        if self.decision_delay_minutes not in {
            IMMEDIATE_DELAY_MINUTES,
            PLUS_60_DELAY_MINUTES,
        }:
            raise SessionGapFailureError("session delay must be zero or sixty minutes")
        if self.decision_delay_minutes and self.direction_mode != "reversal":
            raise SessionGapFailureError("the delayed control must retain reversal direction")
        if self.atr_lookback != ATR_LOOKBACK:
            raise SessionGapFailureError("session ATR lookback is fixed")
        numeric = (
            self.gap_atr_min,
            self.failure_body_atr_min,
            self.up_gap_failure_clv_max,
            self.down_gap_failure_clv_min,
            self.gap_retrace_min,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise SessionGapFailureError("session thresholds must be finite")
        if (
            self.gap_atr_min <= 0.0
            or self.failure_body_atr_min < 0.0
            or not 0.0 <= self.up_gap_failure_clv_max <= 1.0
            or not 0.0 <= self.down_gap_failure_clv_min <= 1.0
            or not 0.0 <= self.gap_retrace_min <= 1.0
        ):
            raise SessionGapFailureError("session thresholds are outside their domains")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_session_gap_failure_configuration_v1",
            "role": self.role,
            "event_kind": self.event_kind,
            "direction_mode": self.direction_mode,
            "decision_delay_minutes": self.decision_delay_minutes,
            "decision_delay_bars": self.decision_delay_bars,
            "atr_lookback": self.atr_lookback,
            "gap_atr_min": self.gap_atr_min,
            "failure_body_atr_min": self.failure_body_atr_min,
            "up_gap_failure_clv_max": self.up_gap_failure_clv_max,
            "down_gap_failure_clv_min": self.down_gap_failure_clv_min,
            "gap_retrace_min": self.gap_retrace_min,
            "clock": clock_identity_payload(),
        }

    @property
    def identity_sha256(self) -> str:
        return sha256_payload(self.identity_payload())

    @property
    def decision_delay_bars(self) -> int:
        return self.decision_delay_minutes // CLOCK_POLICY.bar_minutes


SESSION_GAP_CONFIGURATIONS = (
    SessionGapConfiguration(
        "cash_open_failure_reversal_primary",
        "reversal",
        IMMEDIATE_DELAY_MINUTES,
    ),
    SessionGapConfiguration(
        "cash_open_failure_continuation_control",
        "continuation",
        IMMEDIATE_DELAY_MINUTES,
    ),
    SessionGapConfiguration(
        "cash_open_failure_plus_60m_control",
        "reversal",
        PLUS_60_DELAY_MINUTES,
    ),
)
SESSION_EVENT_CONFIGURATIONS = SESSION_GAP_CONFIGURATIONS


def executable_identity_payload() -> dict[str, Any]:
    return {
        "schema": "axiom_rift_v2_session_gap_failure_executable_v1",
        "implementation_key": SESSION_GAP_FAILURE_IMPLEMENTATION_KEY,
        "causal_decision": "completed_bar_only",
        "entry": "next_bar_open",
        "score": "signed_cash_open_failure_body_atr_at_trigger",
        "delayed_control_intervening_ohlc_used": False,
        "clock": clock_identity_payload(),
        "configurations": [
            configuration.identity_payload()
            for configuration in SESSION_GAP_CONFIGURATIONS
        ],
    }


SESSION_GAP_FAILURE_EXECUTABLE_SHA256 = sha256_payload(
    executable_identity_payload()
)
CASH_OPEN_GAP_FAILURE_EXECUTABLE_SHA256 = (
    SESSION_GAP_FAILURE_EXECUTABLE_SHA256
)
SESSION_GAP_EXECUTABLE_SHA256 = SESSION_GAP_FAILURE_EXECUTABLE_SHA256


@dataclass(frozen=True)
class SessionGapFeatures:
    decision_index: int
    decision_time: datetime
    trigger_index: int | None
    trigger_time: datetime | None
    anchor_index: int | None
    dependency_start_index: int | None
    atr_window_start_index: int | None
    atr_24: float | None
    prior_cash_close: float | None
    cash_open: float | None
    gap: float | None
    gap_direction: int
    gap_atr: float | None
    failure_body_atr: float | None
    failure_close_location: float | None
    gap_retrace_fraction: float | None
    clock_rule_id: str
    clock_authority_verified: bool
    calendar_authority: bool
    valid: bool
    reason: str


@dataclass(frozen=True)
class SessionGapSignal:
    role: str
    configuration_sha256: str
    decision_index: int
    decision_time: datetime
    direction: int
    score: float
    valid: bool
    reason: str


@dataclass(frozen=True)
class SessionGapEvaluation:
    configuration: SessionGapConfiguration
    configuration_sha256: str
    executable_sha256: str
    features: tuple[SessionGapFeatures, ...]
    signals: tuple[SessionGapSignal, ...]

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

    @property
    def clock_rule_id(self) -> str:
        return CLOCK_POLICY.rule_id

    @property
    def clock_authority_claim(self) -> bool:
        return False


def _validate_container(bars: BarArrays) -> None:
    size = len(bars)
    for name in ("open", "high", "low", "close", "tick_volume", "spread"):
        values = getattr(bars, name)
        if not isinstance(values, np.ndarray) or values.ndim != 1 or len(values) != size:
            raise SessionGapFailureError(
                f"bars.{name} must be a one-dimensional aligned array"
            )
    if any(value.tzinfo is not None for value in bars.time):
        raise SessionGapFailureError("broker bar timestamps must be naive")
    if any(left >= right for left, right in zip(bars.time, bars.time[1:])):
        raise SessionGapFailureError("bar times must be strictly increasing")


def _price_reason(bars: BarArrays, index: int) -> str | None:
    opening = float(bars.open[index])
    high = float(bars.high[index])
    low = float(bars.low[index])
    close = float(bars.close[index])
    if not all(math.isfinite(value) for value in (opening, high, low, close)):
        return "nonfinite_price"
    if min(opening, high, low, close) <= 0.0:
        return "nonpositive_price"
    if high < low or not low <= opening <= high or not low <= close <= high:
        return "invalid_ohlc"
    return None


def _true_range(bars: BarArrays, index: int) -> float | None:
    if index <= 0 or _price_reason(bars, index) or _price_reason(bars, index - 1):
        return None
    high = float(bars.high[index])
    low = float(bars.low[index])
    previous_close = float(bars.close[index - 1])
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def _base_feature(
    bars: BarArrays,
    index: int,
    *,
    valid: bool = True,
    reason: str = "not_session_decision_bar",
) -> SessionGapFeatures:
    return SessionGapFeatures(
        decision_index=index,
        decision_time=bars.time[index],
        trigger_index=None,
        trigger_time=None,
        anchor_index=None,
        dependency_start_index=None,
        atr_window_start_index=None,
        atr_24=None,
        prior_cash_close=None,
        cash_open=None,
        gap=None,
        gap_direction=0,
        gap_atr=None,
        failure_body_atr=None,
        failure_close_location=None,
        gap_retrace_fraction=None,
        clock_rule_id=CLOCK_POLICY.rule_id,
        clock_authority_verified=CLOCK_AUTHORITY_VERIFIED,
        calendar_authority=CALENDAR_AUTHORITY,
        valid=valid,
        reason=reason,
    )


def _signal(
    configuration: SessionGapConfiguration,
    bars: BarArrays,
    index: int,
    *,
    direction: int = 0,
    score: float = 0.0,
    valid: bool = True,
    reason: str = "not_session_decision_bar",
) -> SessionGapSignal:
    return SessionGapSignal(
        role=configuration.role,
        configuration_sha256=configuration.identity_sha256,
        decision_index=index,
        decision_time=bars.time[index],
        direction=direction,
        score=float(score),
        valid=valid,
        reason=reason,
    )


def _matches_clock_proxy(timestamp: datetime, expected_market_close: time) -> bool:
    try:
        stamp = CLOCK_POLICY.stamp(timestamp)
    except ClockError as exc:  # pragma: no cover - 16:30/22:55 are unambiguous
        raise SessionGapFailureError(f"clock policy rejected server timestamp: {exc}") from exc
    observed = stamp.decision_available_at_market.timetz().replace(tzinfo=None)
    return observed == expected_market_close


def _is_cash_open_proxy(timestamp: datetime) -> bool:
    return (
        timestamp.time() == CASH_OPEN_SERVER_TIME
        and _matches_clock_proxy(timestamp, time(9, 35))
    )


def _is_prior_cash_close_proxy(timestamp: datetime) -> bool:
    return (
        timestamp.time() == PRIOR_CASH_CLOSE_SERVER_TIME
        and _matches_clock_proxy(timestamp, time(16, 0))
    )


def _cash_open_context(
    bars: BarArrays,
    index: int,
    configuration: SessionGapConfiguration,
) -> SessionGapFeatures:
    feature = _base_feature(bars, index)
    if index < configuration.atr_lookback + 1:
        return replace(feature, valid=False, reason="incomplete_preopen_window")
    preopen_start = index - configuration.atr_lookback - 1
    expected_times = tuple(
        bars.time[preopen_start] + timedelta(minutes=5 * offset)
        for offset in range(configuration.atr_lookback + 2)
    )
    if tuple(bars.time[preopen_start : index + 1]) != expected_times:
        return replace(feature, valid=False, reason="incomplete_preopen_window")
    anchor_index = next(
        (
            candidate
            for candidate in range(index - 1, -1, -1)
            if _is_prior_cash_close_proxy(bars.time[candidate])
        ),
        None,
    )
    if anchor_index is None:
        return replace(feature, valid=False, reason="missing_prior_cash_close")
    if _price_reason(bars, anchor_index) or _price_reason(bars, index):
        return replace(
            feature,
            anchor_index=anchor_index,
            dependency_start_index=min(anchor_index, preopen_start),
            atr_window_start_index=preopen_start,
            valid=False,
            reason="invalid_event_price",
        )
    ranges = tuple(
        _true_range(bars, candidate)
        for candidate in range(index - configuration.atr_lookback, index)
    )
    if any(value is None for value in ranges):
        return replace(
            feature,
            anchor_index=anchor_index,
            dependency_start_index=min(anchor_index, preopen_start),
            atr_window_start_index=preopen_start,
            valid=False,
            reason="invalid_atr_window",
        )
    atr = float(sum(float(value) for value in ranges) / configuration.atr_lookback)
    if not math.isfinite(atr) or atr <= 0.0:
        return replace(
            feature,
            anchor_index=anchor_index,
            dependency_start_index=min(anchor_index, preopen_start),
            atr_window_start_index=preopen_start,
            valid=False,
            reason="zero_atr",
        )
    prior_close = float(bars.close[anchor_index])
    opening = float(bars.open[index])
    close = float(bars.close[index])
    high = float(bars.high[index])
    low = float(bars.low[index])
    gap = opening - prior_close
    gap_direction = 1 if gap > 0.0 else -1 if gap < 0.0 else 0
    gap_atr = abs(gap) / atr
    bar_range = high - low
    if bar_range <= 0.0:
        return replace(
            feature,
            trigger_index=index,
            trigger_time=bars.time[index],
            anchor_index=anchor_index,
            dependency_start_index=min(anchor_index, preopen_start),
            atr_window_start_index=preopen_start,
            atr_24=atr,
            prior_cash_close=prior_close,
            cash_open=opening,
            gap=gap,
            gap_direction=gap_direction,
            gap_atr=gap_atr,
            valid=False,
            reason="zero_cash_open_range",
        )
    body_atr = abs(close - opening) / atr
    close_location = (close - low) / bar_range
    retrace = (
        (opening - close) / abs(gap)
        if gap_direction > 0
        else (close - opening) / abs(gap)
        if gap_direction < 0
        else 0.0
    )
    context = replace(
        feature,
        trigger_index=index,
        trigger_time=bars.time[index],
        anchor_index=anchor_index,
        dependency_start_index=min(anchor_index, preopen_start),
        atr_window_start_index=preopen_start,
        atr_24=atr,
        prior_cash_close=prior_close,
        cash_open=opening,
        gap=gap,
        gap_direction=gap_direction,
        gap_atr=gap_atr,
        failure_body_atr=body_atr,
        failure_close_location=close_location,
        gap_retrace_fraction=retrace,
        valid=True,
        reason="ok",
    )
    if gap_direction == 0 or gap_atr < configuration.gap_atr_min:
        return replace(context, reason="gap_below_threshold")
    opposite_move = close < opening if gap_direction > 0 else close > opening
    if not opposite_move:
        return replace(context, reason="no_opposite_cash_open_body")
    if body_atr < configuration.failure_body_atr_min:
        return replace(context, reason="weak_failure_body")
    clv_passed = (
        close_location <= configuration.up_gap_failure_clv_max
        if gap_direction > 0
        else close_location >= configuration.down_gap_failure_clv_min
    )
    if not clv_passed:
        return replace(context, reason="failure_clv_not_met")
    if retrace < configuration.gap_retrace_min:
        return replace(context, reason="insufficient_gap_retrace")
    return replace(context, reason="triggered")


def evaluate_session_gap_configuration(
    bars: BarArrays,
    configuration: SessionGapConfiguration,
) -> SessionGapEvaluation:
    """Evaluate one role using only information available at each decision."""

    _validate_container(bars)
    features = [_base_feature(bars, index) for index in range(len(bars))]
    signals = [_signal(configuration, bars, index) for index in range(len(bars))]
    delayed: dict[datetime, SessionGapFeatures] = {}
    for index, timestamp in enumerate(bars.time):
        cached = delayed.get(timestamp)
        if cached is not None:
            observed = replace(
                cached,
                decision_index=index,
                decision_time=timestamp,
                reason="triggered",
            )
            assert cached.trigger_index is not None
            assert cached.trigger_time is not None
            expected_index = (
                cached.trigger_index + configuration.decision_delay_bars
            )
            expected_times = tuple(
                cached.trigger_time + timedelta(minutes=5 * offset)
                for offset in range(configuration.decision_delay_bars + 1)
            )
            observed_times = tuple(
                bars.time[cached.trigger_index : index + 1]
            )
            if index != expected_index or observed_times != expected_times:
                features[index] = replace(
                    observed,
                    valid=False,
                    reason="incomplete_delayed_clock_path",
                )
                signals[index] = _signal(
                    configuration,
                    bars,
                    index,
                    valid=False,
                    reason="incomplete_delayed_clock_path",
                )
            else:
                direction = -cached.gap_direction
                assert cached.failure_body_atr is not None
                features[index] = observed
                signals[index] = _signal(
                    configuration,
                    bars,
                    index,
                    direction=direction,
                    score=direction * cached.failure_body_atr,
                    reason="triggered",
                )
        if not _is_cash_open_proxy(timestamp):
            continue
        context = _cash_open_context(bars, index, configuration)
        features[index] = context
        if context.reason != "triggered":
            signals[index] = _signal(
                configuration,
                bars,
                index,
                valid=context.valid,
                reason=context.reason,
            )
            continue
        if configuration.decision_delay_minutes:
            delayed[timestamp + timedelta(minutes=configuration.decision_delay_minutes)] = (
                context
            )
            signals[index] = _signal(
                configuration,
                bars,
                index,
                reason="trigger_cached",
            )
            continue
        direction = (
            -context.gap_direction
            if configuration.direction_mode == "reversal"
            else context.gap_direction
        )
        assert context.failure_body_atr is not None
        signals[index] = _signal(
            configuration,
            bars,
            index,
            direction=direction,
            score=direction * context.failure_body_atr,
            reason="triggered",
        )
    return SessionGapEvaluation(
        configuration=configuration,
        configuration_sha256=configuration.identity_sha256,
        executable_sha256=SESSION_GAP_FAILURE_EXECUTABLE_SHA256,
        features=tuple(features),
        signals=tuple(signals),
    )


def evaluate_session_gap_failure(
    bars: BarArrays,
    configurations: Iterable[SessionGapConfiguration] = SESSION_GAP_CONFIGURATIONS,
) -> tuple[SessionGapEvaluation, ...]:
    """Evaluate the frozen three-role session surface in supplied order."""

    return tuple(
        evaluate_session_gap_configuration(bars, configuration)
        for configuration in tuple(configurations)
    )


evaluate_configuration = evaluate_session_gap_configuration


__all__ = [
    "ATR_LOOKBACK",
    "CALENDAR_AUTHORITY",
    "CASH_OPEN_GAP_FAILURE_EXECUTABLE_SHA256",
    "CASH_OPEN_SERVER_TIME",
    "CLOCK_AUTHORITY_VERIFIED",
    "CLOCK_POLICY",
    "DOWN_GAP_FAILURE_CLV_MIN",
    "FAILURE_BODY_ATR_MIN",
    "GAP_ATR_MIN",
    "GAP_RETRACE_MIN",
    "PRIOR_CASH_CLOSE_SERVER_TIME",
    "SESSION_EVENT_CONFIGURATIONS",
    "SESSION_GAP_CONFIGURATIONS",
    "SESSION_GAP_FAILURE_EXECUTABLE_SHA256",
    "SESSION_GAP_EXECUTABLE_SHA256",
    "SESSION_GAP_FAILURE_IMPLEMENTATION_KEY",
    "SessionGapConfiguration",
    "SessionGapEvaluation",
    "SessionGapFailureError",
    "SessionGapFeatures",
    "SessionGapSignal",
    "UP_GAP_FAILURE_CLV_MAX",
    "clock_identity_payload",
    "evaluate_configuration",
    "evaluate_session_gap_configuration",
    "evaluate_session_gap_failure",
    "executable_identity_payload",
]
