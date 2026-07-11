



from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research import composite_consensus_discovery as followup


def synthetic_frame(rows: int = 600) -> pd.DataFrame:
    time = pd.date_range("2024-01-01", periods=rows, freq="5min")
    index = np.arange(rows, dtype=float)
    close = 15_000 + 0.02 * index + 2.0 * np.sin(index / 11)
    return pd.DataFrame(
        {
            "time": time,
            "open": close - 0.01,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "tick_volume": np.full(rows, 100.0),
            "spread": np.full(rows, 2.0),
        }
    )


def router_frame(rows: int = 6_000) -> pd.DataFrame:
    time = pd.date_range("2024-01-01", periods=rows, freq="5min")
    index = np.arange(rows, dtype=float)
    close = (
        15_000
        + 0.03 * index
        + 3.0 * np.sin(index / 13)
        + 1.5 * np.sin(index / 3.7)
    )
    body = 0.15 * np.sin(index / 5) + 0.05 * np.cos(index / 17)
    open_ = close - body
    high = np.maximum(open_, close) + 0.25 + 0.08 * (1 + np.sin(index / 11))
    low = np.minimum(open_, close) - 0.25 - 0.08 * (1 + np.cos(index / 9))
    tick_volume = np.maximum(
        5,
        np.round(
            120
            + 45 * np.sin(index / 37)
            + 30 * np.sin(index / 7)
            + 20 * np.cos(index / 113)
        ),
    )
    return pd.DataFrame(
        {
            "time": time,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "tick_volume": tick_volume,
            "spread": np.full(rows, 2.0),
        }
    )


class CompositeConsensusDiscoveryTests(unittest.TestCase):
    def test_heavy_synthetic_surface_reaches_bound_projection(self) -> None:
        frame = router_frame()
        fold = {
            "fold_id": "rw_001",
            "train_is": {
                "start": frame["time"].iloc[0],
                "end": frame["time"].iloc[3_999],
            },
            "test_oos": {
                "start": frame["time"].iloc[4_000],
                "end": frame["time"].iloc[-1],
            },
        }
        with (
            patch.object(
                followup,
                "load_observed_development",
                return_value=SimpleNamespace(frame=frame),
            ),
            patch.object(followup, "_validate_engine_environment"),
            patch.object(followup, "_validate_production_data"),
            patch.object(followup, "_validate_fold_payloads"),
            patch.object(followup, "_fold_payloads", return_value=(fold,)),
            patch.object(
                followup, "_adjusted_bootstrap_upper_pvalue", return_value=50_000
            ),
        ):
            surface = followup._compute_registered_composite_consensus_surface(".")
        self.assertEqual(len(surface["evaluations"]), 12)
        self.assertTrue(
            all(
                "daily_entries_p90_milli" in item["metrics"]
                for item in surface["evaluations"]
            )
        )
        surface_hash = sha256(canonical_bytes(surface)).hexdigest()
        payload = {
            "job_hash": "a" * 64,
            "job_id": "job:" + "b" * 64,
            "job_permit_id": "c" * 64,
            "start_record_id": "d" * 64,
        }
        execution = {
            **payload,
            "identity": canonical_digest(
                domain="running-job-execution", payload=payload
            ),
        }
        projected = followup.project_composite_consensus_evaluation(
            surface,
            job_execution=execution,
            subject_executable_id=surface["evaluations"][0][
                "subject_executable_id"
            ],
            surface_artifact_hash=surface_hash,
            surface_manifest_hash="e" * 64,
        )
        self.assertEqual(projected["schema"], "composite_consensus_evaluation.v1")

    def test_surface_has_exact_registered_twelve_and_bound_dependencies(self) -> None:
        configurations = followup.composite_consensus_configurations()
        executables = [followup.composite_consensus_executable(item) for item in configurations]
        self.assertEqual(len(configurations), 12)
        self.assertEqual(len({item.identity for item in executables}), 12)
        self.assertEqual(
            [item.configuration_id for item in configurations[:4]],
            [
                "full_regime_consensus-inverted-h24",
                "full_regime_consensus-inverted-h48",
                "full_regime_consensus-routed-h24",
                "full_regime_consensus-routed-h48",
            ],
        )
        for executable in executables:
            self.assertIn(followup.composite_consensus_implementation_sha256(), executable.engine_contract)
            self.assertIn(followup.trend_dependency_sha256(), executable.engine_contract)
            self.assertIn(followup.loader_implementation_sha256(), executable.engine_contract)
            self.assertIn(
                followup.volatility_dependency_sha256(), executable.engine_contract
            )
            self.assertIn(
                followup.volume_price_dependency_sha256(), executable.engine_contract
            )
            self.assertIn(
                followup.reversion_dependency_sha256(), executable.engine_contract
            )
            self.assertIn("bonferroni_222", executable.engine_contract)

    def test_feature_is_prefix_invariant_and_rewarms_after_gap(self) -> None:
        frame = synthetic_frame()
        full = followup.compute_composite_sleeve_scores(frame)
        prefix = followup.compute_composite_sleeve_scores(frame.iloc[:400])
        for left, right in (
            (full.volume[:400], prefix.volume),
            (full.reversion[:400], prefix.reversion),
            (full.volatility_sleeve[:400], prefix.volatility_sleeve),
            (full.realized_volatility[:400], prefix.realized_volatility),
        ):
            np.testing.assert_allclose(
                left, right, rtol=0.0, atol=0.0, equal_nan=True
            )

        gapped = frame.copy()
        gapped.loc[250:, "time"] += pd.Timedelta(hours=2)
        features = followup.compute_composite_sleeve_scores(gapped)
        self.assertEqual(features.run[250], 1)
        self.assertTrue(np.isnan(features.volatility_sleeve[393]))
        self.assertTrue(np.isfinite(features.volatility_sleeve[394]))

    def test_consensus_and_controls_use_same_sign_minimum_strength(self) -> None:
        features = followup._RouterFeatures(
            volume=np.array([2.0, 2.0, -3.0]),
            reversion=np.array([3.0, 3.0, 3.0]),
            volatility_sleeve=np.array([-4.0, 4.0, -4.0]),
            realized_volatility=np.array([0.5, 1.5, 2.5]),
            run=np.full(3, 145),
        )
        thresholds = {"volume": 1.0, "reversion": 1.0, "volatility": 1.0}
        routed = followup.route_consensus_score(
            features,
            profile="full_regime_consensus",
            volatility_cutoffs=(1.0, 2.0),
            sleeve_thresholds=thresholds,
        )
        np.testing.assert_allclose(routed, np.array([2.0, 2.0, -3.0]))
        volume_primary = followup.route_consensus_score(
            features,
            profile="volume_primary_all_regimes",
            volatility_cutoffs=(1.0, 2.0),
            sleeve_thresholds=thresholds,
        )
        np.testing.assert_allclose(volume_primary, np.array([2.0, 2.0, -3.0]))
        no_high = followup.route_consensus_score(
            features,
            profile="middle_consensus_no_high",
            volatility_cutoffs=(1.0, 2.0),
            sleeve_thresholds=thresholds,
        )
        self.assertTrue(np.isnan(no_high[2]))
        disagree = followup._RouterFeatures(
            volume=features.volume,
            reversion=np.array([3.0, -3.0, 3.0]),
            volatility_sleeve=np.array([-4.0, 4.0, 4.0]),
            realized_volatility=features.realized_volatility,
            run=features.run,
        )
        rejected = followup.route_consensus_score(
            disagree,
            profile="full_regime_consensus",
            volatility_cutoffs=(1.0, 2.0),
            sleeve_thresholds=thresholds,
        )
        self.assertTrue(np.isnan(rejected[1]))
        self.assertTrue(np.isnan(rejected[2]))

    def test_selector_is_fold_only_ninety_seventh_and_half_percentile(self) -> None:
        score = np.arange(2_000, dtype=float)
        train = np.zeros(2_000, dtype=bool)
        train[:1_500] = True
        expected = np.quantile(np.abs(score[:1_500]), 0.975, method="higher")
        self.assertEqual(followup.calibrate_selector(score, train), expected)

    def test_registered_control_metrics_are_pairwise_noncompensatory(self) -> None:
        days = pd.date_range("2025-01-01", periods=40, freq="D")
        profile_net = {
            "full_regime_consensus": 100,
            "volume_primary_all_regimes": 80,
            "middle_consensus_no_high": 60,
        }
        results = []
        for configuration in followup.composite_consensus_configurations():
            net = profile_net[configuration.profile] + 10 * configuration.signal_sign
            results.append(
                followup._ConfigurationResult(
                    configuration=configuration,
                    executable_id=followup.composite_consensus_executable(configuration).identity,
                    metrics={"net_profit_micropoints": net},
                    fold_metrics=[],
                    regime_metrics=[],
                    session_metrics=[],
                    direction_metrics=[],
                    daily_pnl=pd.Series(float(net) / len(days), index=days),
                )
            )
        with patch.object(
            followup, "_adjusted_bootstrap_upper_pvalue", return_value=50_000
        ):
            followup._populate_pvalues_and_controls(results)
        subject = next(
            item for item in results
            if item.configuration.configuration_id
            == "full_regime_consensus-routed-h24"
        )
        self.assertEqual(subject.metrics["feature_control_worst_delta_net_profit_micropoints"], 20)
        self.assertEqual(subject.metrics["opposite_sign_worst_delta_net_profit_micropoints"], 20)
        self.assertEqual(subject.metrics["feature_control_worst_pvalue_upper_ppm"], 50_000)

    def test_canonical_surface_projects_one_bound_subject(self) -> None:
        evaluations = []
        context = []
        for configuration in followup.composite_consensus_configurations():
            identity = followup.composite_consensus_executable(configuration).identity
            evaluations.append(
                {
                    "direction_metrics": [], "evaluable": True, "fold_metrics": [],
                    "metrics": {}, "regime_metrics": [], "session_metrics": [],
                    "subject_configuration_id": configuration.configuration_id,
                    "subject_executable_id": identity,
                }
            )
            context.append(
                {
                    "configuration_id": configuration.configuration_id,
                    "executable_id": identity,
                    "net_profit_micropoints": 0,
                    "selection_aware_pvalue_ppm": 1_000_000,
                }
            )
        surface = {
            "claim_limits": ["discovery_only"],
            "dataset_sha256": followup.DATASET_SHA256,
            "discovery_implementation_sha256": followup.composite_consensus_implementation_sha256(),
            "engine_environment": {}, "evaluations": evaluations,
            "loader_implementation_sha256": followup.loader_implementation_sha256(),
            "material_identity": followup.OBSERVED_MATERIAL_ID,
            "reversion_dependency_sha256": followup.reversion_dependency_sha256(),
            "schema": "composite_consensus_surface.v1", "selection_context": context,
            "selection_method": {}, "session_semantics": "fixture",
            "split_artifact_sha256": followup.ROLLING_SPLIT_SHA256,
            "trend_dependency_sha256": followup.trend_dependency_sha256(),
            "volatility_dependency_sha256": followup.volatility_dependency_sha256(),
            "volume_price_dependency_sha256": followup.volume_price_dependency_sha256(),
        }
        surface_hash = sha256(canonical_bytes(surface)).hexdigest()
        payload = {
            "job_hash": "a" * 64, "job_id": "job:" + "b" * 64,
            "job_permit_id": "c" * 64, "start_record_id": "d" * 64,
        }
        execution = {
            **payload,
            "identity": canonical_digest(domain="running-job-execution", payload=payload),
        }
        subject = evaluations[0]["subject_executable_id"]
        projected = followup.project_composite_consensus_evaluation(
            surface,
            job_execution=execution,
            subject_executable_id=subject,
            surface_artifact_hash=surface_hash,
            surface_manifest_hash="e" * 64,
        )
        self.assertEqual(projected["schema"], "composite_consensus_evaluation.v1")
        self.assertEqual(projected["subject_executable_id"], subject)
        canonical_bytes(projected)


if __name__ == "__main__":
    unittest.main()



