from __future__ import annotations

import unittest
from datetime import datetime, timedelta

import numpy as np

from axiom_rift.v2.features import BarArrays
from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.research.session_gap_failure import (
    CALENDAR_AUTHORITY,
    CLOCK_AUTHORITY_VERIFIED,
    CLOCK_POLICY,
    SESSION_GAP_CONFIGURATIONS,
    SESSION_GAP_FAILURE_EXECUTABLE_SHA256,
    clock_identity_payload,
    evaluate_session_gap_configuration,
    evaluate_session_gap_failure,
    executable_identity_payload,
)


def fixture_bars(*, gap_direction: int = 1) -> tuple[BarArrays, int, int, int]:
    day = datetime(2026, 1, 6)
    anchor_time = day - timedelta(days=1) + timedelta(hours=22, minutes=55)
    preopen_start = day + timedelta(hours=14, minutes=25)
    preopen_times = tuple(
        preopen_start + timedelta(minutes=5 * offset) for offset in range(25)
    )
    cash_open_time = day + timedelta(hours=16, minutes=30)
    after = tuple(
        cash_open_time + timedelta(minutes=5 * offset) for offset in range(1, 16)
    )
    times = (anchor_time, *preopen_times, cash_open_time, *after)
    size = len(times)
    opening = np.full(size, 100.0)
    high = np.full(size, 101.0)
    low = np.full(size, 99.0)
    close = np.full(size, 100.0)
    cash_open_index = 1 + len(preopen_times)
    if gap_direction > 0:
        opening[cash_open_index] = 102.0
        high[cash_open_index] = 102.2
        low[cash_open_index] = 100.8
        close[cash_open_index] = 101.0
    else:
        opening[cash_open_index] = 98.0
        high[cash_open_index] = 99.2
        low[cash_open_index] = 97.8
        close[cash_open_index] = 99.0
    bars = BarArrays(
        time=tuple(times),
        open=opening,
        high=high,
        low=low,
        close=close,
        tick_volume=np.full(size, 100.0),
        spread=np.full(size, 75.0),
    )
    delayed_index = cash_open_index + 12
    return bars, 0, cash_open_index, delayed_index


def prefix(bars: BarArrays, size: int) -> BarArrays:
    return BarArrays(
        time=bars.time[:size],
        open=bars.open[:size],
        high=bars.high[:size],
        low=bars.low[:size],
        close=bars.close[:size],
        tick_volume=bars.tick_volume[:size],
        spread=bars.spread[:size],
    )


def without_index(bars: BarArrays, index: int) -> BarArrays:
    keep = np.ones(len(bars), dtype=bool)
    keep[index] = False
    return BarArrays(
        time=tuple(value for offset, value in enumerate(bars.time) if offset != index),
        open=bars.open[keep],
        high=bars.high[keep],
        low=bars.low[keep],
        close=bars.close[keep],
        tick_volume=bars.tick_volume[keep],
        spread=bars.spread[keep],
    )


class SessionGapFailureTests(unittest.TestCase):
    def test_exact_three_role_identity_and_unverified_clock_boundary(self) -> None:
        self.assertEqual(
            tuple(row.role for row in SESSION_GAP_CONFIGURATIONS),
            (
                "cash_open_failure_reversal_primary",
                "cash_open_failure_continuation_control",
                "cash_open_failure_plus_60m_control",
            ),
        )
        self.assertEqual(
            tuple(row.direction_mode for row in SESSION_GAP_CONFIGURATIONS),
            ("reversal", "continuation", "reversal"),
        )
        self.assertEqual(
            tuple(row.decision_delay_minutes for row in SESSION_GAP_CONFIGURATIONS),
            (0, 0, 60),
        )
        self.assertEqual(
            len({row.identity_sha256 for row in SESSION_GAP_CONFIGURATIONS}), 3
        )
        clock = clock_identity_payload()
        self.assertEqual(clock["rule_id"], "fpmarkets_ny_close_plus_7_v1")
        self.assertEqual(
            clock["authority"],
            "broker_documented_rule_pending_mt5_clock_receipt",
        )
        self.assertFalse(clock["authority_verified"])
        self.assertFalse(clock["calendar_authority"])
        self.assertFalse(CLOCK_AUTHORITY_VERIFIED)
        self.assertFalse(CALENDAR_AUTHORITY)
        self.assertEqual(
            SESSION_GAP_FAILURE_EXECUTABLE_SHA256,
            sha256_payload(executable_identity_payload()),
        )
        self.assertFalse(
            executable_identity_payload()["delayed_control_intervening_ohlc_used"]
        )

    def test_clock_proxy_maps_cash_open_in_winter_and_summer(self) -> None:
        for stamp in (
            datetime(2026, 1, 6, 16, 30),
            datetime(2026, 7, 6, 16, 30),
        ):
            with self.subTest(stamp=stamp):
                observed = CLOCK_POLICY.stamp(stamp)
                self.assertEqual(
                    observed.decision_available_at_market.strftime("%H:%M"),
                    "09:35",
                )

    def test_up_gap_emits_matched_directions_and_exact_dependency(self) -> None:
        bars, anchor, cash_open, delayed = fixture_bars(gap_direction=1)
        primary, continuation, plus_60 = evaluate_session_gap_failure(bars)
        self.assertEqual(primary.signals[cash_open].direction, -1)
        self.assertEqual(continuation.signals[cash_open].direction, 1)
        self.assertEqual(plus_60.signals[cash_open].direction, 0)
        self.assertEqual(plus_60.signals[cash_open].reason, "trigger_cached")
        self.assertEqual(plus_60.signals[delayed].direction, -1)
        self.assertEqual(primary.signals[cash_open].score, -0.5)
        self.assertEqual(continuation.signals[cash_open].score, 0.5)
        self.assertEqual(plus_60.signals[delayed].score, -0.5)
        for evaluation, index in (
            (primary, cash_open),
            (continuation, cash_open),
            (plus_60, delayed),
        ):
            feature = evaluation.features[index]
            self.assertEqual(feature.anchor_index, anchor)
            self.assertEqual(feature.dependency_start_index, anchor)
            self.assertEqual(feature.atr_window_start_index, cash_open - 25)
            self.assertEqual(feature.atr_24, 2.0)
            self.assertEqual(feature.gap_atr, 1.0)
            self.assertFalse(feature.clock_authority_verified)
            self.assertFalse(feature.calendar_authority)
        self.assertEqual(plus_60.features[delayed].trigger_index, cash_open)
        self.assertEqual(plus_60.features[delayed].trigger_time, bars.time[cash_open])
        self.assertEqual(plus_60.signals[delayed].decision_time, bars.time[delayed])

    def test_down_gap_reverses_all_matched_directions(self) -> None:
        bars, _anchor, cash_open, delayed = fixture_bars(gap_direction=-1)
        primary, continuation, plus_60 = evaluate_session_gap_failure(bars)
        self.assertEqual(primary.signals[cash_open].direction, 1)
        self.assertEqual(continuation.signals[cash_open].direction, -1)
        self.assertEqual(plus_60.signals[delayed].direction, 1)
        self.assertAlmostEqual(
            primary.features[cash_open].failure_close_location or 0.0,
            6.0 / 7.0,
        )

    def test_trigger_filters_are_strict_and_preregistered(self) -> None:
        cases = (
            ("gap_below_threshold", (100.8, 101.0, 100.2, 100.4)),
            ("no_opposite_cash_open_body", (102.0, 102.6, 101.8, 102.4)),
            ("weak_failure_body", (102.0, 102.1, 101.5, 101.7)),
            ("failure_clv_not_met", (102.0, 102.1, 100.0, 101.0)),
            ("insufficient_gap_retrace", (102.0, 102.0, 101.4, 101.6)),
        )
        configuration = SESSION_GAP_CONFIGURATIONS[0]
        for expected, values in cases:
            with self.subTest(expected=expected):
                bars, _anchor, cash_open, _delayed = fixture_bars()
                opening = bars.open.copy()
                high = bars.high.copy()
                low = bars.low.copy()
                close = bars.close.copy()
                opening[cash_open], high[cash_open], low[cash_open], close[cash_open] = values
                changed = BarArrays(
                    bars.time,
                    opening,
                    high,
                    low,
                    close,
                    bars.tick_volume,
                    bars.spread,
                )
                observed = evaluate_session_gap_configuration(changed, configuration)
                self.assertEqual(observed.signals[cash_open].direction, 0)
                self.assertEqual(observed.signals[cash_open].reason, expected)

    def test_missing_anchor_and_incomplete_preopen_window_do_not_emit(self) -> None:
        bars, anchor, cash_open, _delayed = fixture_bars()
        no_anchor = without_index(bars, anchor)
        observed = evaluate_session_gap_configuration(
            no_anchor, SESSION_GAP_CONFIGURATIONS[0]
        )
        shifted_cash_open = cash_open - 1
        self.assertEqual(observed.signals[shifted_cash_open].reason, "missing_prior_cash_close")
        self.assertFalse(observed.signals[shifted_cash_open].valid)

        broken = without_index(bars, cash_open - 5)
        observed = evaluate_session_gap_configuration(
            broken, SESSION_GAP_CONFIGURATIONS[0]
        )
        shifted_cash_open = cash_open - 1
        self.assertEqual(observed.signals[shifted_cash_open].reason, "incomplete_preopen_window")
        self.assertFalse(observed.signals[shifted_cash_open].valid)

    def test_delayed_control_does_not_inspect_intervening_ohlc(self) -> None:
        bars, _anchor, cash_open, delayed = fixture_bars()
        opening = bars.open.copy()
        high = bars.high.copy()
        low = bars.low.copy()
        close = bars.close.copy()
        for index in range(cash_open + 1, delayed):
            opening[index] = 300.0 + index
            high[index] = 500.0 + index
            low[index] = 200.0 + index
            close[index] = 400.0 + index
        changed = BarArrays(
            bars.time,
            opening,
            high,
            low,
            close,
            bars.tick_volume,
            bars.spread,
        )
        configuration = SESSION_GAP_CONFIGURATIONS[2]
        baseline = evaluate_session_gap_configuration(bars, configuration)
        observed = evaluate_session_gap_configuration(changed, configuration)
        self.assertEqual(observed.signals[delayed], baseline.signals[delayed])
        self.assertEqual(observed.features[delayed], baseline.features[delayed])

    def test_delayed_control_requires_all_twelve_timestamp_steps(self) -> None:
        bars, _anchor, cash_open, delayed = fixture_bars()
        broken = without_index(bars, cash_open + 5)
        observed = evaluate_session_gap_configuration(
            broken,
            SESSION_GAP_CONFIGURATIONS[2],
        )
        shifted_delayed = delayed - 1
        self.assertEqual(observed.signals[shifted_delayed].direction, 0)
        self.assertFalse(observed.signals[shifted_delayed].valid)
        self.assertEqual(
            observed.signals[shifted_delayed].reason,
            "incomplete_delayed_clock_path",
        )

    def test_results_are_prefix_causal_for_every_role(self) -> None:
        bars, _anchor, cash_open, delayed = fixture_bars()
        full = evaluate_session_gap_failure(bars)
        for cut in (cash_open + 1, delayed + 1):
            short = evaluate_session_gap_failure(prefix(bars, cut))
            for left, right in zip(short, full, strict=True):
                self.assertEqual(left.features, right.features[:cut])
                self.assertEqual(left.signals, right.signals[:cut])


if __name__ == "__main__":
    unittest.main()
