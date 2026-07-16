from __future__ import annotations

import unittest
from hashlib import sha256
import sys

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    DiscoveryBoundaryError,
    TrendConfiguration,
    _adjusted_bootstrap_upper_pvalue,
    _causal_prefix_mismatch_count,
    _compute_registered_trend_surface,
    _monthly_realized_exit_drawdown,
    _validate_fold_payloads,
    causal_effective_spread,
    completed_bar_execution_spreads,
    completed_bar_spread_proxy_indices,
    compute_trend_score,
    discovery_implementation_sha256,
    execution_pnl,
    execution_pnl_breakdown,
    loader_implementation_sha256,
    project_trend_evaluation,
    simulate_fixed_hold,
    trend_configurations,
    trend_executable,
)


def synthetic_frame(rows: int = 5_000) -> pd.DataFrame:
    time = pd.date_range("2024-01-01 00:00:00", periods=rows, freq="5min")
    index = np.arange(rows, dtype=float)
    close = 15_000 + 0.05 * index + 1.5 * np.sin(index / 23)
    return pd.DataFrame(
        {
            "time": time,
            "open": close - 0.01,
            "high": close + 0.20,
            "low": close - 0.20,
            "close": close,
            "tick_volume": np.full(rows, 100),
            "spread": np.full(rows, 2.0),
            "real_volume": np.zeros(rows),
        }
    )


class TrendDiscoveryTests(unittest.TestCase):
    def test_causal_prefix_check_covers_every_simulation_array(self) -> None:
        names = ("score", "volatility", "run", "effective_spread")
        full = tuple(
            (name, np.array([1.0, 2.0, np.nan, 4.0])) for name in names
        )
        prefix = tuple(
            (name, np.array([1.0, 2.0, np.nan])) for name in names
        )
        self.assertEqual(
            _causal_prefix_mismatch_count(
                full_surfaces=full,
                prefix_surfaces=prefix,
                compared_row_count=3,
            ),
            0,
        )

        for changed_name in names:
            changed = tuple(
                (
                    name,
                    np.array([1.0, 9.0, np.nan])
                    if name == changed_name
                    else np.array([1.0, 2.0, np.nan]),
                )
                for name in names
            )
            with self.subTest(changed_name=changed_name):
                self.assertEqual(
                    _causal_prefix_mismatch_count(
                        full_surfaces=full,
                        prefix_surfaces=changed,
                        compared_row_count=3,
                    ),
                    1,
                )

    def test_surface_has_twelve_unique_registered_semantics(self) -> None:
        configurations = trend_configurations()
        identities = [trend_executable(value).identity for value in configurations]
        self.assertEqual(len(configurations), 12)
        self.assertEqual(len(set(identities)), 12)
        self.assertEqual(
            {value.profile for value in configurations},
            {"single_12", "multi_fast", "multi_slow"},
        )
        self.assertEqual({value.signal_sign for value in configurations}, {-1, 1})
        self.assertEqual({value.holding_bars for value in configurations}, {3, 12})

    def test_display_aliases_are_absent_from_identity_parameters(self) -> None:
        configuration = TrendConfiguration(
            profile="multi_fast", signal_sign=1, holding_bars=3
        )
        parameters = configuration.semantic_parameters()
        self.assertNotIn("configuration_id", parameters)
        self.assertNotIn("profile", parameters)
        self.assertEqual(parameters["lookbacks"], [3, 12])
        with self.assertRaises(ValueError):
            TrendConfiguration(profile="renamed", signal_sign=1, holding_bars=3)

    def test_executable_binds_current_discovery_and_loader_bytes(self) -> None:
        executable = trend_executable(trend_configurations()[0])
        self.assertIn(discovery_implementation_sha256(), executable.engine_contract)
        self.assertIn(loader_implementation_sha256(), executable.engine_contract)
        for component in executable.components:
            self.assertIn(discovery_implementation_sha256(), component.implementation)

    def test_feature_is_exactly_prefix_invariant(self) -> None:
        frame = synthetic_frame()
        full, _, _ = compute_trend_score(frame, (3, 12))
        prefix, _, _ = compute_trend_score(frame.iloc[:3000], (3, 12))
        np.testing.assert_allclose(
            full[:3000], prefix, rtol=0.0, atol=0.0, equal_nan=True
        )

    def test_zero_spread_median_is_lagged_and_resets_at_gap(self) -> None:
        frame = synthetic_frame(80)
        spread = np.full(80, 4.0)
        spread[35] = 0.0
        effective = causal_effective_spread(
            spread, frame.time.to_numpy(dtype="datetime64[ns]").astype("int64")
        )
        self.assertEqual(effective[35], 4.0)

        frame.loc[40:, "time"] = frame.loc[40:, "time"] + pd.Timedelta(hours=2)
        spread[40:] = 0.0
        reset = causal_effective_spread(
            spread, frame.time.to_numpy(dtype="datetime64[ns]").astype("int64")
        )
        self.assertTrue(np.isnan(reset[60]))

    def test_direction_correct_spread_economics(self) -> None:
        long_native, long_stress = execution_pnl(
            direction=1,
            entry_bid=100.0,
            exit_bid=101.0,
            entry_spread_points=2.0,
            exit_spread_points=3.0,
        )
        short_native, short_stress = execution_pnl(
            direction=-1,
            entry_bid=101.0,
            exit_bid=100.0,
            entry_spread_points=2.0,
            exit_spread_points=3.0,
        )
        self.assertAlmostEqual(long_native, 0.98)
        self.assertAlmostEqual(short_native, 0.97)
        self.assertLess(long_stress, long_native)
        self.assertLess(short_stress, short_native)
        long_breakdown = execution_pnl_breakdown(
            direction=1,
            entry_bid=100.0,
            exit_bid=101.0,
            entry_spread_points=2.0,
            exit_spread_points=3.0,
        )
        short_breakdown = execution_pnl_breakdown(
            direction=-1,
            entry_bid=101.0,
            exit_bid=100.0,
            entry_spread_points=2.0,
            exit_spread_points=3.0,
        )
        self.assertAlmostEqual(long_breakdown.gross_pnl, 1.0)
        self.assertAlmostEqual(long_breakdown.native_cost, 0.02)
        self.assertAlmostEqual(long_breakdown.stress_cost, 0.045)
        self.assertAlmostEqual(short_breakdown.native_cost, 0.03)
        self.assertAlmostEqual(short_breakdown.stress_cost, 0.055)

    def test_execution_spread_proxy_uses_only_completed_bars(self) -> None:
        self.assertEqual(
            completed_bar_spread_proxy_indices(
                np.int64(11), spread_count=20
            ),
            10,
        )
        np.testing.assert_array_equal(
            completed_bar_spread_proxy_indices(
                np.array([1, 7, 19], dtype=np.int64),
                spread_count=20,
            ),
            np.array([0, 6, 18]),
        )
        spreads = np.arange(20, dtype=float)
        execution = completed_bar_execution_spreads(
            spreads,
            entry_index=np.int64(7),
            exit_index=np.int64(12),
        )
        self.assertEqual(execution.entry_proxy_index, 6)
        self.assertEqual(execution.exit_proxy_index, 11)
        self.assertEqual(execution.entry_spread_points, 6.0)
        self.assertEqual(execution.exit_spread_points, 11.0)
        for invalid in (0, 20):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                completed_bar_spread_proxy_indices(
                    invalid,
                    spread_count=20,
                )

    def test_execution_bar_spread_cannot_change_trade_sample_or_pnl(self) -> None:
        frame = synthetic_frame(200)
        score = np.zeros(200)
        decision_index = 100
        score[decision_index] = 2.0
        volatility = np.ones(200)
        run = np.arange(1, 201, dtype=np.int32)
        configuration = TrendConfiguration(
            profile="single_12", signal_sign=1, holding_bars=3
        )

        def simulate(spreads: np.ndarray):
            return simulate_fixed_hold(
                frame=frame,
                score=score,
                volatility=volatility,
                run=run,
                threshold=1.0,
                configuration=configuration,
                test_start=frame.time.iloc[80],
                test_end=frame.time.iloc[150],
                fold_id="fixture",
                regime_cutoffs=(0.5, 1.5),
                effective_spread=spreads,
            )

        baseline_spreads = np.full(len(frame), 2.0)
        baseline = simulate(baseline_spreads)
        execution_bar_perturbed = baseline_spreads.copy()
        execution_bar_perturbed[decision_index + 1] = 999.0
        execution_bar_perturbed[decision_index + 4] = 999.0
        perturbed = simulate(execution_bar_perturbed)
        self.assertEqual(baseline.intent_rows, perturbed.intent_rows)
        pd.testing.assert_frame_equal(baseline.trades, perturbed.trades)

        decision_bar_perturbed = baseline_spreads.copy()
        decision_bar_perturbed[decision_index] = 4.0
        repriced = simulate(decision_bar_perturbed)
        self.assertEqual(len(repriced.trades), len(baseline.trades))
        self.assertEqual(repriced.intent_rows, baseline.intent_rows)
        self.assertAlmostEqual(
            float(baseline.trades.iloc[0]["pnl"])
            - float(repriced.trades.iloc[0]["pnl"]),
            0.02,
        )

    def test_decision_time_is_bar_close_and_equals_next_open(self) -> None:
        frame = synthetic_frame(200)
        score = np.zeros(200)
        score[100] = 2.0
        volatility = np.ones(200)
        run = np.arange(1, 201, dtype=np.int32)
        result = simulate_fixed_hold(
            frame=frame,
            score=score,
            volatility=volatility,
            run=run,
            threshold=1.0,
            configuration=TrendConfiguration(
                profile="single_12", signal_sign=1, holding_bars=3
            ),
            test_start=frame.time.iloc[80],
            test_end=frame.time.iloc[150],
            fold_id="fixture",
            regime_cutoffs=(0.5, 1.5),
        )
        self.assertEqual(len(result.trades), 1)
        trade = result.trades.iloc[0]
        self.assertEqual(
            trade.decision_time,
            trade.decision_bar_open_time + pd.Timedelta(minutes=5),
        )
        self.assertEqual(trade.decision_time, trade.entry_time)
        self.assertEqual(result.causality_violation_count, 0)
        self.assertAlmostEqual(
            trade.gross_pnl - trade.native_cost,
            trade.pnl,
        )
        self.assertAlmostEqual(
            trade.gross_pnl - trade.stress_cost,
            trade.stress_pnl,
        )

    def test_unresolved_cost_preserves_position_occupancy(self) -> None:
        frame = synthetic_frame(120)
        frame.loc[40:, "time"] = frame.loc[40:, "time"] + pd.Timedelta(hours=2)
        frame.loc[40:, "spread"] = 0.0
        score = np.zeros(120)
        score[70:75] = 2.0
        volatility = np.ones(120)
        run = np.arange(1, 121, dtype=np.int32)
        run[40:] = np.arange(1, 81, dtype=np.int32)
        result = simulate_fixed_hold(
            frame=frame,
            score=score,
            volatility=volatility,
            run=run,
            threshold=1.0,
            configuration=TrendConfiguration(
                profile="single_12", signal_sign=1, holding_bars=3
            ),
            test_start=frame.time.iloc[60],
            test_end=frame.time.iloc[100],
            fold_id="fixture",
            regime_cutoffs=(0.5, 1.5),
        )
        self.assertEqual(len(result.trades), 0)
        self.assertEqual(result.unresolved_cost_signal_count, 2)

    def test_fold_overlap_and_row_count_are_rejected(self) -> None:
        frame = synthetic_frame(3000)

        def window(start: int, end: int) -> dict[str, object]:
            return {
                "start": frame.time.iloc[start],
                "end": frame.time.iloc[end],
                "row_count": end - start + 1,
            }

        folds = []
        for index in range(9):
            base = index * 300
            folds.append(
                {
                    "fold_id": f"rw_{index + 1:03d}",
                    "train_is": window(0, 99),
                    "validation_oos": window(100, 149),
                    "test_oos": window(base + 150, base + 299),
                }
            )
        _validate_fold_payloads(frame, folds)
        overlap_start = folds[0]["test_oos"]["end"]
        assert isinstance(overlap_start, pd.Timestamp)
        folds[1]["test_oos"] = {
            "start": overlap_start,
            "end": overlap_start + pd.Timedelta(minutes=5 * 149),
            "row_count": 150,
        }
        with self.assertRaisesRegex(DiscoveryBoundaryError, "overlap"):
            _validate_fold_payloads(frame, folds)

    def test_production_entry_rejects_arbitrary_frame(self) -> None:
        with self.assertRaisesRegex(
            DiscoveryBoundaryError, "repository path"
        ):
            _compute_registered_trend_surface(synthetic_frame())  # type: ignore[arg-type]

    def test_bootstrap_is_deterministic_and_uses_conservative_upper_bound(self) -> None:
        values = 10.0 + np.sin(np.arange(90, dtype=float))
        first = _adjusted_bootstrap_upper_pvalue(
            values, seed_label="fixture:positive"
        )
        second = _adjusted_bootstrap_upper_pvalue(
            values, seed_label="fixture:positive"
        )
        self.assertEqual(first, second)
        self.assertLess(first, 100_000)
        self.assertEqual(
            _adjusted_bootstrap_upper_pvalue(
                -values, seed_label="fixture:negative"
            ),
            1_000_000,
        )

    def test_monthly_drawdown_share_is_same_month_noncompensatory(self) -> None:
        trades = pd.DataFrame(
            {
                "exit_time": pd.to_datetime(
                    ["2025-01-02", "2025-01-03", "2025-02-02"]
                ),
                "pnl": [10.0, -4.0, 20.0],
            }
        )
        drawdown, share = _monthly_realized_exit_drawdown(trades)
        self.assertEqual(drawdown, 4.0)
        self.assertEqual(share, 400_000)

    def test_surface_projection_binds_cache_and_running_job(self) -> None:
        evaluations = []
        selection_context = []
        for configuration in trend_configurations():
            executable = trend_executable(configuration)
            evaluations.append(
                {
                    "direction_metrics": [],
                    "evaluable": True,
                    "fold_metrics": [],
                    "metrics": {},
                    "regime_metrics": [],
                    "session_metrics": [],
                    "subject_configuration_id": configuration.configuration_id,
                    "subject_executable_id": executable.identity,
                }
            )
            selection_context.append(
                {
                    "configuration_id": configuration.configuration_id,
                    "executable_id": executable.identity,
                    "net_profit_micropoints": 0,
                    "selection_aware_pvalue_ppm": 1_000_000,
                }
            )
        surface = {
            "claim_limits": ["discovery_only"],
            "dataset_sha256": DATASET_SHA256,
            "discovery_implementation_sha256": discovery_implementation_sha256(),
            "engine_environment": {
                "numpy": np.__version__,
                "pandas": pd.__version__,
                "python": ".".join(str(item) for item in sys.version_info[:3]),
                "scipy": scipy.__version__,
            },
            "evaluations": evaluations,
            "loader_implementation_sha256": loader_implementation_sha256(),
            "material_identity": OBSERVED_MATERIAL_ID,
            "schema": "trend_discovery_surface.v1",
            "selection_context": selection_context,
            "selection_method": {},
            "session_semantics": "fixture",
            "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        }
        surface_hash = sha256(canonical_bytes(surface)).hexdigest()
        execution_payload = {
            "job_hash": "a" * 64,
            "job_id": "job:" + "b" * 64,
            "job_permit_id": "c" * 64,
            "start_record_id": "d" * 64,
        }
        execution = {
            **execution_payload,
            "identity": canonical_digest(
                domain="running-job-execution", payload=execution_payload
            ),
        }
        subject = trend_executable(trend_configurations()[0]).identity
        projected = project_trend_evaluation(
            surface,
            job_execution=execution,
            subject_executable_id=subject,
            surface_artifact_hash=surface_hash,
            surface_manifest_hash="e" * 64,
        )
        self.assertEqual(projected["schema"], "trend_discovery_evaluation.v3")
        self.assertEqual(projected["job_execution"], execution)
        with self.assertRaisesRegex(DiscoveryBoundaryError, "artifact hash"):
            project_trend_evaluation(
                surface,
                job_execution=execution,
                subject_executable_id=subject,
                surface_artifact_hash="f" * 64,
                surface_manifest_hash="e" * 64,
            )


if __name__ == "__main__":
    unittest.main()
