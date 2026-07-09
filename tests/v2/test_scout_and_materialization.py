from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.v2.features import (
    BarArrays,
    compute_feature_matrix,
    feature_order_sha256,
    load_feature_contract,
)
from axiom_rift.v2.materialization.fixture import (
    evaluate_fixture,
    reference_linear_bundle,
    synthetic_fixture_bars,
)
from axiom_rift.v2.materialization.linear_onnx import export_linear_onnx
from axiom_rift.v2.research.scout import load_fold_windows, load_scout_spec


class ScoutAndMaterializationTests(unittest.TestCase):
    def test_first_scout_is_declarative_and_season_diverse(self) -> None:
        hypothesis = PROJECT_ROOT / "campaigns/v2/V2G0001_v2_activation/hypotheses/V2H0001.yaml"
        spec = load_scout_spec(hypothesis, PROJECT_ROOT)
        self.assertEqual(spec.anchors, ("V2D002", "V2D005", "V2D008"))
        self.assertEqual(spec.hold_bars, 6)
        self.assertEqual(spec.point_size, 0.01)
        self.assertEqual(spec.maximum_daily_entries, 10)
        self.assertEqual(spec.acceptance_profile["frozen_before_results"], True)
        windows = load_fold_windows(
            PROJECT_ROOT / "data/processed/coverage_audits/us100_m5_rolling_windows.json",
            spec.anchors,
        )
        self.assertEqual(tuple(window.development_id for window in windows), spec.anchors)
        self.assertEqual(len({window.development_start.month for window in windows}), 3)

    def test_canonical_features_are_prefix_invariant_and_zero_spread_is_unknown(self) -> None:
        bars = synthetic_fixture_bars()
        full = compute_feature_matrix(bars)
        cutoff = 87
        prefix_bars = BarArrays(
            time=bars.time[:cutoff],
            open=bars.open[:cutoff],
            high=bars.high[:cutoff],
            low=bars.low[:cutoff],
            close=bars.close[:cutoff],
            tick_volume=bars.tick_volume[:cutoff],
            spread=bars.spread[:cutoff],
        )
        prefix = compute_feature_matrix(prefix_bars)
        np.testing.assert_array_equal(full.valid[:cutoff], prefix.valid)
        np.testing.assert_allclose(full.values[:cutoff], prefix.values, rtol=0.0, atol=0.0, equal_nan=True)

        changed_spread = bars.spread.copy()
        changed_spread[70] = 0.0
        zero_cost_bars = BarArrays(
            time=bars.time,
            open=bars.open,
            high=bars.high,
            low=bars.low,
            close=bars.close,
            tick_volume=bars.tick_volume,
            spread=changed_spread,
        )
        zero_cost = compute_feature_matrix(zero_cost_bars)
        self.assertFalse(zero_cost.valid[70])
        self.assertEqual(zero_cost.reasons[70], "unknown_cost_zero_spread")

    def test_feature_contract_hash_is_shared_with_mql(self) -> None:
        contract_path = PROJECT_ROOT / "configs/v2/feature_programs/causal_bar_v1.yaml"
        contract = load_feature_contract(contract_path)
        order_hash = feature_order_sha256()
        self.assertEqual(contract["output"]["feature_order_sha256"], order_hash)
        mql = (PROJECT_ROOT / "src/axiom_rift/v2/mt5/include/AxiomV2Features.mqh").read_text(encoding="ascii")
        self.assertIn(order_hash, mql)

    def test_non_economic_python_onnx_fixture_is_deterministic(self) -> None:
        bars = synthetic_fixture_bars()
        bundle = reference_linear_bundle()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.onnx"
            export_linear_onnx(path, bundle)
            first = evaluate_fixture(bars, bundle, onnx_path=path)
            second = evaluate_fixture(bars, bundle, onnx_path=path)
        self.assertEqual(first, second)
        self.assertGreater(len(first), 50)
        self.assertTrue(any(row.admitted_direction != 0 for row in first))


if __name__ == "__main__":
    unittest.main()
