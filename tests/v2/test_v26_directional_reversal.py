from __future__ import annotations

import unittest
from datetime import datetime, timedelta

import numpy as np

from axiom_rift.v2.features import BarArrays
from axiom_rift.v2.research.compression_release import (
    COMPRESSION_RELEASE_EXECUTABLE_SHA256,
    EVENT_CONFIGURATIONS,
    evaluate_configuration as evaluate_event_configuration,
)
from axiom_rift.v2.research.directional_reversal import (
    DIRECTIONAL_EVENT_CONFIGURATIONS,
    DIRECTIONAL_REVERSAL_EXECUTABLE_SHA256,
    DIRECTION_FILTERED_REASON,
    evaluate_directional_configuration,
    evaluate_directional_reversal,
)


OLD_EVENT_CONFIGURATION_HASHES = (
    "4f00a93d4102d8a6ca0b4a2066bf2aa0201a992f1d5ced7fa2d78257ed46a6b1",
    "9329900e9733fe98feab947c6cd4b81684ab20f69cfc45fef882d18f929f4ae1",
    "caf7019752e36d970e9ca3b90210d45c11447d5dee6545f820337f27afcc1156",
    "3a8d990220eecf273b747e9be9e848612c20072d032e50adacea4895a30e33f7",
    "499b81ba0a795fec4393e6473ab8622a4da33a495ad04d7e3b9994a0cf2f233c",
)


def fixture_bars(
    *,
    release_direction: int = 1,
    reversal: bool = False,
    count: int = 40,
) -> BarArrays:
    opening = np.full(count, 100.0)
    high = np.full(count, 101.0)
    low = np.full(count, 99.0)
    close = np.full(count, 100.0)
    release = 30
    if count > release and release_direction > 0:
        opening[release], high[release], low[release], close[release] = (
            100.0,
            102.2,
            99.8,
            102.0,
        )
        if reversal:
            opening[31], high[31], low[31], close[31] = 100.8, 100.9, 99.0, 99.5
    elif count > release:
        opening[release], high[release], low[release], close[release] = (
            100.0,
            100.2,
            97.8,
            98.0,
        )
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


class DirectionalReversalTests(unittest.TestCase):
    def test_old_event_configuration_hashes_are_unchanged(self) -> None:
        self.assertEqual(
            tuple(row.identity_sha256 for row in EVENT_CONFIGURATIONS),
            OLD_EVENT_CONFIGURATION_HASHES,
        )

    def test_five_directional_identities_are_exact_and_unique(self) -> None:
        self.assertEqual(
            tuple(row.role for row in DIRECTIONAL_EVENT_CONFIGURATIONS),
            (
                "short_reversal_low",
                "short_reversal_base",
                "short_reversal_high",
                "long_reversal_control",
                "short_continuation_control",
            ),
        )
        self.assertEqual(
            tuple(row.compression_ratio_max for row in DIRECTIONAL_EVENT_CONFIGURATIONS),
            (2.0, 2.5, 3.0, 2.5, 2.5),
        )
        self.assertEqual(
            tuple(row.direction_filter for row in DIRECTIONAL_EVENT_CONFIGURATIONS),
            (-1, -1, -1, 1, -1),
        )
        self.assertEqual(
            tuple(row.event_kind for row in DIRECTIONAL_EVENT_CONFIGURATIONS),
            (
                "failed_break_reversal",
                "failed_break_reversal",
                "failed_break_reversal",
                "failed_break_reversal",
                "continuation",
            ),
        )
        identities = {
            row.identity_sha256 for row in DIRECTIONAL_EVENT_CONFIGURATIONS
        }
        self.assertEqual(len(identities), 5)
        self.assertTrue(
            all(
                row.identity_payload()["schema"]
                == "axiom_rift_v2_directional_reversal_configuration_v1"
                for row in DIRECTIONAL_EVENT_CONFIGURATIONS
            )
        )
        self.assertNotEqual(
            DIRECTIONAL_REVERSAL_EXECUTABLE_SHA256,
            COMPRESSION_RELEASE_EXECUTABLE_SHA256,
        )

    def test_matching_base_signal_has_behavioral_parity_before_filter(self) -> None:
        bars = fixture_bars(release_direction=1, reversal=True)
        configuration = DIRECTIONAL_EVENT_CONFIGURATIONS[1]
        base = evaluate_event_configuration(
            bars,
            configuration.as_event_configuration(),
        )
        directional = evaluate_directional_configuration(bars, configuration)

        self.assertEqual(directional.features, base.features)
        self.assertEqual(base.signals[31].direction, -1)
        self.assertEqual(directional.signals[31].direction, base.signals[31].direction)
        self.assertEqual(directional.signals[31].score, base.signals[31].score)
        self.assertEqual(directional.signals[31].valid, base.signals[31].valid)
        self.assertEqual(directional.signals[31].reason, base.signals[31].reason)
        self.assertEqual(
            directional.signals[31].configuration_sha256,
            configuration.identity_sha256,
        )
        self.assertEqual(
            directional.executable_sha256,
            DIRECTIONAL_REVERSAL_EXECUTABLE_SHA256,
        )

    def test_opposite_nonzero_direction_is_filtered_with_explicit_reason(self) -> None:
        bars = fixture_bars(release_direction=-1, reversal=True)
        configuration = DIRECTIONAL_EVENT_CONFIGURATIONS[1]
        base = evaluate_event_configuration(
            bars,
            configuration.as_event_configuration(),
        )
        directional = evaluate_directional_configuration(bars, configuration)

        self.assertEqual(base.signals[31].direction, 1)
        self.assertEqual(base.signals[31].reason, "triggered")
        self.assertEqual(directional.signals[31].direction, 0)
        self.assertEqual(directional.signals[31].score, 0.0)
        self.assertTrue(directional.signals[31].valid)
        self.assertEqual(
            directional.signals[31].reason,
            DIRECTION_FILTERED_REASON,
        )
        self.assertEqual(directional.signals[29].reason, base.signals[29].reason)

    def test_results_are_prefix_causal_for_every_role(self) -> None:
        bars = fixture_bars(release_direction=1, reversal=True)
        cut = 34
        full = evaluate_directional_reversal(bars)
        short = evaluate_directional_reversal(prefix(bars, cut))
        for left, right in zip(short, full, strict=True):
            self.assertEqual(left.features, right.features[:cut])
            self.assertEqual(left.signals, right.signals[:cut])


if __name__ == "__main__":
    unittest.main()
