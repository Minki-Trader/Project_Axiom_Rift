

from __future__ import annotations

from hashlib import sha256
import unittest
from unittest.mock import patch
import warnings

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research import trend_null_followup_discovery as trend_null


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


class TrendNullFollowupDiscoveryTests(unittest.TestCase):
    def test_surface_has_exact_registered_twelve_and_bound_dependencies(self) -> None:
        configurations = trend_null.trend_null_configurations()
        executables = [
            trend_null.trend_null_executable(item) for item in configurations
        ]
        self.assertEqual(len(configurations), 12)
        self.assertEqual(len({item.identity for item in executables}), 12)
        self.assertEqual(
            [item.configuration_id for item in configurations[:4]],
            [
                "observed_trend_24-reversal-h12",
                "observed_trend_24-reversal-h48",
                "observed_trend_24-continuation-h12",
                "observed_trend_24-continuation-h48",
            ],
        )
        for executable in executables:
            self.assertIn(
                trend_null.trend_null_implementation_sha256(),
                executable.engine_contract,
            )
            self.assertIn(
                trend_null.trend_dependency_sha256(), executable.engine_contract
            )
            self.assertIn(
                trend_null.loader_implementation_sha256(), executable.engine_contract
            )
            self.assertIn("bonferroni_174", executable.engine_contract)

    def test_feature_is_prefix_invariant_and_rewarms_after_gap(self) -> None:
        frame = synthetic_frame()
        for profile in (
            "observed_trend_24",
            "prior_day_lag_null_24",
            "deterministic_day_phase_null_24",
        ):
            full, _, _ = trend_null.compute_trend_null_score(frame, profile)
            prefix, _, _ = trend_null.compute_trend_null_score(
                frame.iloc[:400], profile
            )
            np.testing.assert_allclose(
                full[:400], prefix, rtol=0.0, atol=0.0, equal_nan=True
            )

        gapped = frame.copy()
        gapped.loc[250:, "time"] += pd.Timedelta(hours=2)
        score, _, run = trend_null.compute_trend_null_score(
            gapped, "observed_trend_24"
        )
        self.assertEqual(run[250], 1)
        self.assertTrue(np.isnan(score[273]))
        self.assertTrue(np.isfinite(score[274]))

    def test_lag_and_day_phase_nulls_are_exact_and_deterministic(self) -> None:
        frame = synthetic_frame()
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            observed, _, _ = trend_null.compute_trend_null_score(
                frame, "observed_trend_24"
            )
            lagged, _, _ = trend_null.compute_trend_null_score(
                frame, "prior_day_lag_null_24"
            )
            phased_one, _, _ = trend_null.compute_trend_null_score(
                frame, "deterministic_day_phase_null_24"
            )
            phased_two, _, _ = trend_null.compute_trend_null_score(
                frame, "deterministic_day_phase_null_24"
            )
        np.testing.assert_allclose(lagged[288:], observed[:-288], equal_nan=True)
        time_ns = frame["time"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
        day_index = time_ns // (24 * 60 * 60 * 1_000_000_000)
        minute = frame["time"].dt.hour.to_numpy() * 60 + frame["time"].dt.minute.to_numpy()
        phase_sign = np.where((day_index + minute // 360 + 1) % 2 == 0, 1.0, -1.0)
        np.testing.assert_allclose(phased_one, observed * phase_sign, equal_nan=True)
        np.testing.assert_allclose(phased_one, phased_two, rtol=0.0, atol=0.0, equal_nan=True)

    def test_selector_is_fold_only_ninety_fifth_percentile(self) -> None:
        score = np.arange(2_000, dtype=float)
        train = np.zeros(2_000, dtype=bool)
        train[:1_500] = True
        expected = np.quantile(np.abs(score[:1_500]), 0.95, method="higher")
        self.assertEqual(trend_null.calibrate_selector(score, train), expected)

    def test_registered_control_metrics_are_pairwise_noncompensatory(self) -> None:
        days = pd.date_range("2025-01-01", periods=40, freq="D")
        profile_net = {
            "observed_trend_24": 100,
            "prior_day_lag_null_24": 80,
            "deterministic_day_phase_null_24": 60,
        }
        results = []
        for configuration in trend_null.trend_null_configurations():
            net = profile_net[configuration.profile] + 10 * configuration.signal_sign
            results.append(
                trend_null._ConfigurationResult(
                    configuration=configuration,
                    executable_id=trend_null.trend_null_executable(configuration).identity,
                    metrics={"net_profit_micropoints": net},
                    fold_metrics=[],
                    regime_metrics=[],
                    session_metrics=[],
                    direction_metrics=[],
                    daily_pnl=pd.Series(float(net) / len(days), index=days),
                )
            )
        with patch.object(
            trend_null, "_adjusted_bootstrap_upper_pvalue", return_value=50_000
        ):
            trend_null._populate_pvalues_and_controls(results)
        subject = next(
            item for item in results
            if item.configuration.configuration_id
            == "observed_trend_24-continuation-h12"
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
        for configuration in trend_null.trend_null_configurations():
            identity = trend_null.trend_null_executable(configuration).identity
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
            "dataset_sha256": trend_null.DATASET_SHA256,
            "discovery_implementation_sha256": (
                trend_null.trend_null_implementation_sha256()
            ),
            "engine_environment": {}, "evaluations": evaluations,
            "loader_implementation_sha256": trend_null.loader_implementation_sha256(),
            "material_identity": trend_null.OBSERVED_MATERIAL_ID,
            "schema": "trend_null_followup_surface.v1", "selection_context": context,
            "selection_method": {}, "session_semantics": "fixture",
            "split_artifact_sha256": trend_null.ROLLING_SPLIT_SHA256,
            "trend_dependency_sha256": trend_null.trend_dependency_sha256(),
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
        projected = trend_null.project_trend_null_evaluation(
            surface,
            job_execution=execution,
            subject_executable_id=subject,
            surface_artifact_hash=surface_hash,
            surface_manifest_hash="e" * 64,
        )
        self.assertEqual(projected["schema"], "trend_null_followup_evaluation.v1")
        self.assertEqual(projected["subject_executable_id"], subject)
        canonical_bytes(projected)


if __name__ == "__main__":
    unittest.main()

