from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta

import numpy as np

from axiom_rift.v2.features import BarArrays
from axiom_rift.v2.research.compression_release import (
    EVENT_CONFIGURATIONS,
    evaluate_compression_release,
    evaluate_configuration,
)


def fixture_bars(*, release_direction: int = 1, reversal: bool = False, count: int = 40) -> BarArrays:
    opening = np.full(count, 100.0)
    high = np.full(count, 101.0)
    low = np.full(count, 99.0)
    close = np.full(count, 100.0)
    release = 30
    if count <= release:
        pass
    elif release_direction > 0:
        opening[release], high[release], low[release], close[release] = 100.0, 102.2, 99.8, 102.0
        if reversal:
            opening[31], high[31], low[31], close[31] = 100.8, 100.9, 99.0, 99.5
    else:
        opening[release], high[release], low[release], close[release] = 100.0, 100.2, 97.8, 98.0
        if reversal:
            opening[31], high[31], low[31], close[31] = 99.2, 101.0, 99.1, 100.5
    start = datetime(2026, 1, 5, 9, 0)
    return BarArrays(
        time=tuple(start + timedelta(minutes=5 * index) for index in range(count)),
        open=opening,
        high=high,
        low=low,
        close=close,
        tick_volume=np.full(count, 100.0),
        spread=np.full(count, 75.0),
    )


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


class CompressionReleaseTests(unittest.TestCase):
    def test_five_roles_and_immutable_identity_are_exact(self) -> None:
        self.assertEqual(
            tuple(row.role for row in EVENT_CONFIGURATIONS),
            (
                "continuation_low",
                "continuation_base",
                "continuation_high",
                "failed_break_reversal",
                "compression_ablation",
            ),
        )
        self.assertEqual(tuple(row.compression_ratio_max for row in EVENT_CONFIGURATIONS), (2.0, 2.5, 3.0, 2.5, None))
        self.assertEqual(len({row.identity_sha256 for row in EVENT_CONFIGURATIONS}), 5)
        with self.assertRaises(FrozenInstanceError):
            EVENT_CONFIGURATIONS[0].role = "changed"  # type: ignore[misc]

    def test_completed_bar_results_are_prefix_and_append_invariant(self) -> None:
        bars = fixture_bars(reversal=True)
        cut = 34
        for configuration in EVENT_CONFIGURATIONS:
            full = evaluate_configuration(bars, configuration)
            short = evaluate_configuration(prefix(bars, cut), configuration)
            self.assertEqual(short.features, full.features[:cut])
            self.assertEqual(short.signals, full.signals[:cut])

        appended = fixture_bars(reversal=True, count=48)
        first = evaluate_compression_release(bars)
        second = evaluate_compression_release(appended)
        for left, right in zip(first, second, strict=True):
            self.assertEqual(left.features, right.features[: len(bars)])
            self.assertEqual(left.signals, right.signals[: len(bars)])

    def test_continuation_and_failed_break_are_long_short_symmetric(self) -> None:
        long_bars = fixture_bars(release_direction=1, reversal=True)
        short_bars = fixture_bars(release_direction=-1, reversal=True)
        base = EVENT_CONFIGURATIONS[1]
        reversal = EVENT_CONFIGURATIONS[3]

        long_release = evaluate_configuration(long_bars, base).signals[30]
        short_release = evaluate_configuration(short_bars, base).signals[30]
        self.assertEqual((long_release.direction, short_release.direction), (1, -1))
        self.assertAlmostEqual(long_release.score, -short_release.score)

        long_failure = evaluate_configuration(long_bars, reversal).signals[31]
        short_failure = evaluate_configuration(short_bars, reversal).signals[31]
        self.assertEqual((long_failure.direction, short_failure.direction), (-1, 1))
        self.assertAlmostEqual(long_failure.score, -short_failure.score)

    def test_compression_roles_are_distinct_from_ablation(self) -> None:
        bars = fixture_bars()
        opening = bars.open.copy()
        high = bars.high.copy()
        low = bars.low.copy()
        close = bars.close.copy()
        for index in range(6, 18):
            opening[index] = close[index] = 99.375
            high[index] = 99.875
            low[index] = 98.875
        for offset, index in enumerate(range(18, 30)):
            center = 99.375 + offset * (1.25 / 11.0)
            opening[index] = center
            close[index] = center
            high[index] = center + 0.5
            low[index] = center - 0.5
        opening[30], high[30], low[30], close[30] = 100.8, 101.9, 100.7, 101.7
        changed = BarArrays(bars.time, opening, high, low, close, bars.tick_volume, bars.spread)

        rows = {row.configuration.role: row.signals[30] for row in evaluate_compression_release(changed)}
        self.assertEqual(rows["continuation_low"].direction, 0)
        self.assertEqual(rows["continuation_base"].direction, 1)
        self.assertEqual(rows["continuation_high"].direction, 1)
        self.assertEqual(rows["compression_ablation"].direction, 1)

    def test_warmup_and_zero_ranges_have_explicit_invalid_reasons(self) -> None:
        short = fixture_bars(count=10)
        result = evaluate_configuration(short, EVENT_CONFIGURATIONS[0])
        self.assertTrue(all(not row.valid and row.reason == "warmup" for row in result.signals))

        flat = fixture_bars()
        flat.open[:] = 100.0
        flat.high[:] = 100.0
        flat.low[:] = 100.0
        flat.close[:] = 100.0
        zero_atr = evaluate_configuration(flat, EVENT_CONFIGURATIONS[0])
        self.assertFalse(zero_atr.signals[30].valid)
        self.assertEqual(zero_atr.signals[30].reason, "zero_atr")

        zero_release = fixture_bars()
        zero_release.open[30] = zero_release.high[30] = zero_release.low[30] = zero_release.close[30] = 100.0
        zero_range = evaluate_configuration(zero_release, EVENT_CONFIGURATIONS[0])
        self.assertFalse(zero_range.signals[30].valid)
        self.assertEqual(zero_range.signals[30].reason, "zero_release_range")

    def test_hashed_thresholds_determine_executed_behavior(self) -> None:
        release_bars = fixture_bars()
        base = EVENT_CONFIGURATIONS[1]
        blocked_release = replace(base, release_buffer_atr=99.0)
        self.assertNotEqual(base.identity_sha256, blocked_release.identity_sha256)
        self.assertEqual(evaluate_configuration(release_bars, base).signals[30].direction, 1)
        self.assertEqual(
            evaluate_configuration(release_bars, blocked_release).signals[30].direction,
            0,
        )

        reversal_bars = fixture_bars(reversal=True)
        reversal = EVENT_CONFIGURATIONS[3]
        blocked_reversal = replace(reversal, compression_ratio_max=0.1)
        self.assertNotEqual(reversal.identity_sha256, blocked_reversal.identity_sha256)
        self.assertEqual(
            evaluate_configuration(reversal_bars, reversal).signals[31].direction,
            -1,
        )
        self.assertEqual(
            evaluate_configuration(reversal_bars, blocked_reversal).signals[31].direction,
            0,
        )


if __name__ == "__main__":
    unittest.main()
