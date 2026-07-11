
from __future__ import annotations

from hashlib import sha256
import unittest
from unittest.mock import patch
import warnings

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research import volume_price_discovery as volume_price


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


class VolumePriceDiscoveryTests(unittest.TestCase):
    def test_surface_has_exact_registered_twelve_and_bound_dependencies(self) -> None:
        configurations = volume_price.volume_price_configurations()
        executables = [
            volume_price.volume_price_executable(item) for item in configurations
        ]
        self.assertEqual(len(configurations), 12)
        self.assertEqual(len({item.identity for item in executables}), 12)
        self.assertEqual(
            [item.configuration_id for item in configurations[:4]],
            [
                "body_pressure_12_96-fade-h12",
                "body_pressure_12_96-fade-h48",
                "body_pressure_12_96-follow-h12",
                "body_pressure_12_96-follow-h48",
            ],
        )
        for executable in executables:
            self.assertIn(
                volume_price.volume_price_implementation_sha256(),
                executable.engine_contract,
            )
            self.assertIn(
                volume_price.trend_dependency_sha256(), executable.engine_contract
            )
            self.assertIn(
                volume_price.loader_implementation_sha256(), executable.engine_contract
            )
            self.assertIn("bonferroni_78", executable.engine_contract)

    def test_feature_is_prefix_invariant_and_rewarms_after_gap(self) -> None:
        frame = synthetic_frame()
        for profile in (
            "body_pressure_12_96",
            "close_location_24_120",
            "range_direction_48_192",
        ):
            full, _, _ = volume_price.compute_volume_price_pressure_score(frame, profile)
            prefix, _, _ = volume_price.compute_volume_price_pressure_score(
                frame.iloc[:400], profile
            )
            np.testing.assert_allclose(
                full[:400], prefix, rtol=0.0, atol=0.0, equal_nan=True
            )

        gapped = frame.copy()
        gapped.loc[250:, "time"] += pd.Timedelta(hours=2)
        score, _, run = volume_price.compute_volume_price_pressure_score(
            gapped, "body_pressure_12_96"
        )
        self.assertEqual(run[250], 1)
        self.assertTrue(np.isnan(score[357]))
        self.assertTrue(np.isfinite(score[358]))

    def test_tick_volume_is_required_and_real_volume_is_never_used(self) -> None:
        frame = synthetic_frame()
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            baseline, _, _ = volume_price.compute_volume_price_pressure_score(
                frame, "body_pressure_12_96"
            )

            boosted = frame.copy()
            boosted.loc[588:, "tick_volume"] = 400.0
            changed, _, _ = volume_price.compute_volume_price_pressure_score(
                boosted, "body_pressure_12_96"
            )
            self.assertNotEqual(float(baseline[-1]), float(changed[-1]))

            with_real_volume = boosted.copy()
            with_real_volume["real_volume"] = np.arange(len(with_real_volume)) ** 2
            ignored, _, _ = volume_price.compute_volume_price_pressure_score(
                with_real_volume, "body_pressure_12_96"
            )
        np.testing.assert_allclose(changed, ignored, equal_nan=True)
        with self.assertRaises(KeyError):
            volume_price.compute_volume_price_pressure_score(
                frame.drop(columns=["tick_volume"]), "body_pressure_12_96"
            )

    def test_selector_is_fold_only_ninety_seventh_and_half_percentile(self) -> None:
        score = np.arange(2_000, dtype=float)
        train = np.zeros(2_000, dtype=bool)
        train[:1_500] = True
        expected = np.quantile(np.abs(score[:1_500]), 0.975, method="higher")
        self.assertEqual(volume_price.calibrate_selector(score, train), expected)

    def test_registered_control_metrics_are_pairwise_noncompensatory(self) -> None:
        days = pd.date_range("2025-01-01", periods=40, freq="D")
        profile_net = {
            "body_pressure_12_96": 100,
            "close_location_24_120": 80,
            "range_direction_48_192": 60,
        }
        results = []
        for configuration in volume_price.volume_price_configurations():
            net = profile_net[configuration.profile] + 10 * configuration.signal_sign
            results.append(
                volume_price._ConfigurationResult(
                    configuration=configuration,
                    executable_id=volume_price.volume_price_executable(configuration).identity,
                    metrics={"net_profit_micropoints": net},
                    fold_metrics=[],
                    regime_metrics=[],
                    session_metrics=[],
                    direction_metrics=[],
                    daily_pnl=pd.Series(float(net) / len(days), index=days),
                )
            )
        with patch.object(
            volume_price, "_adjusted_bootstrap_upper_pvalue", return_value=50_000
        ):
            volume_price._populate_pvalues_and_controls(results)
        subject = next(
            item for item in results
            if item.configuration.configuration_id == "body_pressure_12_96-follow-h12"
        )
        self.assertEqual(
            subject.metrics["feature_control_worst_delta_net_profit_micropoints"], 20
        )
        self.assertEqual(
            subject.metrics["opposite_sign_worst_delta_net_profit_micropoints"], 20
        )
        self.assertEqual(
            subject.metrics["feature_control_worst_pvalue_upper_ppm"], 50_000
        )

    def test_canonical_surface_projects_one_bound_subject(self) -> None:
        evaluations = []
        context = []
        for configuration in volume_price.volume_price_configurations():
            identity = volume_price.volume_price_executable(configuration).identity
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
            "dataset_sha256": volume_price.DATASET_SHA256,
            "discovery_implementation_sha256": (
                volume_price.volume_price_implementation_sha256()
            ),
            "engine_environment": {}, "evaluations": evaluations,
            "loader_implementation_sha256": volume_price.loader_implementation_sha256(),
            "material_identity": volume_price.OBSERVED_MATERIAL_ID,
            "schema": "volume_price_discovery_surface.v1", "selection_context": context,
            "selection_method": {}, "session_semantics": "fixture",
            "split_artifact_sha256": volume_price.ROLLING_SPLIT_SHA256,
            "trend_dependency_sha256": volume_price.trend_dependency_sha256(),
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
        projected = volume_price.project_volume_price_evaluation(
            surface,
            job_execution=execution,
            subject_executable_id=subject,
            surface_artifact_hash=surface_hash,
            surface_manifest_hash="e" * 64,
        )
        self.assertEqual(projected["schema"], "volume_price_discovery_evaluation.v1")
        self.assertEqual(projected["subject_executable_id"], subject)
        canonical_bytes(projected)


if __name__ == "__main__":
    unittest.main()

