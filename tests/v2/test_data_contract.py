from __future__ import annotations

import csv
import hashlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from axiom_rift.v2.data.blackouts import (
    BoundaryGap,
    interval_crosses_non_allow_boundary,
    load_non_allow_gaps,
    summarize_non_allow_boundaries,
)
from axiom_rift.v2.data.clock import ClockPolicy
from axiom_rift.v2.data.datasets import (
    EXPECTED_COLUMNS,
    UnknownSpreadCostError,
    compare_raw_to_base,
    inspect_base_frame,
    spread_price_cost,
)
from axiom_rift.v2.data.splits import (
    SplitAccessError,
    adapt_split_set,
    assert_split_access,
    sample_lifecycle_within_role,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ClockContractTests(unittest.TestCase):
    def test_server_clock_follows_new_york_dst_not_european_dst(self) -> None:
        policy = ClockPolicy()
        march = policy.stamp(datetime(2025, 3, 20, 15, 0))
        april = policy.stamp(datetime(2025, 4, 1, 15, 0))
        winter = policy.stamp(datetime(2025, 1, 20, 15, 0))
        self.assertEqual("2025-03-20T12:05:00+00:00", march.decision_available_at_utc.isoformat())
        self.assertEqual("2025-03-20T08:05:00-04:00", march.decision_available_at_market.isoformat())
        self.assertEqual("2025-04-01T12:05:00+00:00", april.decision_available_at_utc.isoformat())
        self.assertEqual("2025-04-01T08:05:00-04:00", april.decision_available_at_market.isoformat())
        self.assertEqual("2025-01-20T13:05:00+00:00", winter.decision_available_at_utc.isoformat())
        self.assertEqual("2025-01-20T08:05:00-05:00", winter.decision_available_at_market.isoformat())


class DatasetContractTests(unittest.TestCase):
    def test_active_base_frame_reports_cost_and_volume_quality(self) -> None:
        path = PROJECT_ROOT / "data/processed/datasets/us100_m5_base_frame.csv"
        receipt = inspect_base_frame(
            path,
            "fb02fe8754b8b9643a346982367813238d11475ca39de46f1cd8d4d0e33a2aa5",
        )
        self.assertEqual(571771, receipt["row_count"])
        self.assertEqual(3497, receipt["zero_spread_count"])
        self.assertEqual(1, receipt["nonzero_real_volume_count"])
        self.assertFalse(receipt["real_volume_eligible"])

    def test_small_base_frame_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "base.csv"
            with path.open("w", encoding="ascii", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=EXPECTED_COLUMNS)
                writer.writeheader()
                writer.writerow({"time":"2025-01-01 01:00:00","open":"100","high":"102","low":"99","close":"101","tick_volume":"10","spread":"5","real_volume":"0"})
                writer.writerow({"time":"2025-01-01 01:05:00","open":"101","high":"103","low":"100","close":"102","tick_volume":"11","spread":"6","real_volume":"0"})
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            receipt = inspect_base_frame(path, digest)
            self.assertEqual(2, receipt["row_count"])
            self.assertEqual(0, receipt["invalid_ohlc_count"])
            self.assertEqual(0, receipt["off_grid_count"])
            self.assertEqual(0, receipt["nonfinite_numeric_count"])
            self.assertEqual(0, receipt["zero_spread_count"])
            self.assertFalse(receipt["real_volume_eligible"])
            self.assertEqual("broker_server_bar_open", receipt["time_semantics"])
            raw_path = Path(temp_dir) / "raw.csv"
            raw_path.write_text(path.read_text(encoding="ascii").replace("2025-01-01", "2025.01.01"), encoding="ascii")
            comparison = compare_raw_to_base(raw_path, path)
            self.assertEqual(2, comparison["row_count"])
            self.assertEqual(0, comparison["mismatch_count"])

    def test_blackout_is_applied_to_crossing_sample(self) -> None:
        gap = BoundaryGap(datetime(2025, 1, 1, 1, 0), datetime(2025, 1, 1, 2, 0), 11, "flag_for_review", "unknown")
        self.assertTrue(interval_crosses_non_allow_boundary(datetime(2025, 1, 1, 0, 30), datetime(2025, 1, 1, 2, 30), (gap,)))
        self.assertFalse(interval_crosses_non_allow_boundary(datetime(2025, 1, 1, 2, 0), datetime(2025, 1, 1, 2, 30), (gap,)))

    def test_all_non_allow_boundaries_remain_quarantined(self) -> None:
        path = PROJECT_ROOT / "data/processed/coverage_audits/us100_m5_clean_periods.json"
        gaps = load_non_allow_gaps(path)
        summary = summarize_non_allow_boundaries(gaps)
        self.assertEqual(57, summary["non_allow_boundary_count"])
        self.assertEqual({"blackout": 6, "flag_for_review": 51}, summary["action_counts"])

    def test_zero_spread_is_not_free_cost(self) -> None:
        self.assertEqual(1.1, spread_price_cost(110, 0.01))
        with self.assertRaises(UnknownSpreadCostError):
            spread_price_cost(0, 0.01)
        with self.assertRaises(ValueError):
            spread_price_cost(0, 0.01, causal_fallback_points=120)
        self.assertEqual(
            1.2,
            spread_price_cost(0, 0.01, causal_fallback_points=120, fallback_policy_id="prior_only_median_v1"),
        )


class SplitContractTests(unittest.TestCase):
    def test_legacy_test_is_adapted_to_development_and_tail_is_quarantined(self) -> None:
        path = PROJECT_ROOT / "data/processed/coverage_audits/us100_m5_rolling_windows.json"
        split_set = adapt_split_set(path, "21830ac109c810cf2b463106127090d586d90de96472c3d043990246d75aa606", "dataset-object", "fb02fe8754b8b9643a346982367813238d11475ca39de46f1cd8d4d0e33a2aa5")
        self.assertEqual("development_cv", split_set["legacy_test_role"])
        self.assertFalse(split_set["tail"]["claim_use_allowed"])
        self.assertEqual(["V2D002", "V2D005", "V2D008"], split_set["scout_anchor_ids"])
        self.assertFalse(split_set["scout_anchor_selection"]["performance_inputs_used"])
        self.assertEqual(
            "21830ac109c810cf2b463106127090d586d90de96472c3d043990246d75aa606",
            split_set["scout_anchor_selection"]["source_split_sha256"],
        )

    def test_stage_access_is_bounded(self) -> None:
        assert_split_access("S", "V2D002", "development_cv")
        assert_split_access("R", "V2D002", "validation_oos")
        with self.assertRaises(SplitAccessError):
            assert_split_access("S", "V2D001", "development_cv")
        with self.assertRaises(SplitAccessError):
            assert_split_access("R", "V2D001", "forward_holdout")
        with self.assertRaises(SplitAccessError):
            assert_split_access("P", "BOGUS", "secret")
        with self.assertRaises(SplitAccessError):
            assert_split_access("P", "V2D001", "tail")
        with self.assertRaises(SplitAccessError):
            assert_split_access("M", "V2D001", "forward_holdout", reveal_permit=True, frozen_identity_bundle_sha256="frozen")
        assert_split_access("M", "sealed", "sealed_holdout_receipt")

    def test_feature_context_may_predate_role_but_lifecycle_may_not_cross_end(self) -> None:
        role_start = datetime(2025, 1, 1)
        role_end = datetime(2025, 1, 31, 23, 55)
        common = {
            "feature_context_start": datetime(2024, 12, 31, 23, 0),
            "decision_bar_open": datetime(2025, 1, 31, 23, 40),
            "role_start": role_start,
            "role_end": role_end,
        }
        self.assertTrue(
            sample_lifecycle_within_role(
                **common,
                label_end_bar_open=datetime(2025, 1, 31, 23, 50),
                trade_end_bar_open=datetime(2025, 1, 31, 23, 55),
            )
        )
        self.assertFalse(
            sample_lifecycle_within_role(
                **common,
                label_end_bar_open=datetime(2025, 2, 1, 0, 0),
                trade_end_bar_open=datetime(2025, 1, 31, 23, 55),
            )
        )
        self.assertFalse(
            sample_lifecycle_within_role(
                **common,
                label_end_bar_open=datetime(2025, 1, 31, 23, 50),
                trade_end_bar_open=datetime(2025, 2, 1, 0, 0),
            )
        )


if __name__ == "__main__":
    unittest.main()
