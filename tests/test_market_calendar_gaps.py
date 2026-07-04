from __future__ import annotations

import unittest
from datetime import datetime

from axiom_rift.pipelines.clean_periods import GapEvent, find_gap_events
from axiom_rift.pipelines.market_calendar import (
    ALLOW,
    BLACKOUT,
    FLAG_FOR_REVIEW,
    classify_gap_with_calendar,
)
from axiom_rift.pipelines.rolling_windows import split_gap_counts


EMPTY_CALENDAR = {"schema": "axiom_rift_market_calendar_v1", "verified_special_closures": []}


def at(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


class MarketCalendarGapTest(unittest.TestCase):
    def test_regular_daily_weekend_and_dst_closes_are_allowed(self) -> None:
        cases = [
            ("2026-01-01 23:55:00", "2026-01-02 01:00:00", "regular_daily_close"),
            ("2026-01-02 23:55:00", "2026-01-05 01:00:00", "regular_weekend_close"),
            ("2026-03-30 00:55:00", "2026-03-30 02:00:00", "regular_dst_daily_close"),
        ]
        for previous, current, expected in cases:
            with self.subTest(expected=expected):
                decision = classify_gap_with_calendar(at(previous), at(current), EMPTY_CALENDAR)
                self.assertEqual(decision.classification, expected)
                self.assertEqual(decision.training_action, ALLOW)

    def test_verified_special_closure_is_allowed(self) -> None:
        calendar = {
            "schema": "axiom_rift_market_calendar_v1",
            "verified_special_closures": [
                {"id": "christmas_2026", "date": "2026-12-25", "reason": "christmas"}
            ],
        }

        decision = classify_gap_with_calendar(
            at("2026-12-24 16:00:00"),
            at("2026-12-25 01:00:00"),
            calendar,
        )

        self.assertEqual(decision.classification, "verified_special_closure")
        self.assertEqual(decision.training_action, ALLOW)
        self.assertEqual(decision.calendar_match_id, "christmas_2026")

    def test_unverified_special_close_candidate_is_review_gap(self) -> None:
        decision = classify_gap_with_calendar(
            at("2026-12-24 16:00:00"),
            at("2026-12-25 01:00:00"),
            EMPTY_CALENDAR,
        )

        self.assertEqual(decision.classification, "unverified_special_close_candidate")
        self.assertEqual(decision.training_action, FLAG_FOR_REVIEW)

    def test_unexpected_data_gaps_get_review_or_blackout_actions(self) -> None:
        single = classify_gap_with_calendar(at("2026-01-06 09:00:00"), at("2026-01-06 09:10:00"), EMPTY_CALENDAR)
        large = classify_gap_with_calendar(at("2026-01-06 09:00:00"), at("2026-01-06 09:20:00"), EMPTY_CALENDAR)

        self.assertEqual(single.classification, "unexpected_single_m5_gap")
        self.assertEqual(single.training_action, FLAG_FOR_REVIEW)
        self.assertEqual(large.classification, "unexpected_multi_bar_gap")
        self.assertEqual(large.training_action, BLACKOUT)

    def test_find_gap_events_records_calendar_fields(self) -> None:
        times = [
            at("2026-01-06 09:00:00"),
            at("2026-01-06 09:20:00"),
        ]

        events = find_gap_events(times, EMPTY_CALENDAR)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].training_action, BLACKOUT)
        self.assertEqual(events[0].calendar_status, "not_regular_or_verified_closure")

    def test_rolling_window_counts_new_gap_actions(self) -> None:
        gaps = [
            GapEvent(
                from_time=at("2026-01-06 09:00:00"),
                to_time=at("2026-01-06 09:10:00"),
                delta_minutes=10,
                missing_bars=1,
                classification="unexpected_single_m5_gap",
                calendar_status="not_regular_or_verified_closure",
                training_action=FLAG_FOR_REVIEW,
                reason="single missing M5 bar outside regular or verified closure",
            ),
            GapEvent(
                from_time=at("2026-01-06 10:00:00"),
                to_time=at("2026-01-06 10:20:00"),
                delta_minutes=20,
                missing_bars=3,
                classification="unexpected_multi_bar_gap",
                calendar_status="not_regular_or_verified_closure",
                training_action=BLACKOUT,
                reason="multi-bar gap outside regular or verified closure",
            ),
            GapEvent(
                from_time=at("2026-01-07 16:00:00"),
                to_time=at("2026-01-08 01:00:00"),
                delta_minutes=540,
                missing_bars=107,
                classification="unverified_special_close_candidate",
                calendar_status="unverified_calendar",
                training_action=FLAG_FOR_REVIEW,
                reason="time pattern resembles special close but no calendar entry matched",
            ),
        ]

        counts = split_gap_counts(at("2026-01-06 00:00:00"), at("2026-01-08 23:55:00"), gaps)

        self.assertEqual(counts["suspicious_gap_count"], 3)
        self.assertEqual(counts["flag_for_review_gap_count"], 2)
        self.assertEqual(counts["blackout_gap_count"], 1)
        self.assertEqual(counts["unverified_special_close_candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
