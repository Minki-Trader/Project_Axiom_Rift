
from __future__ import annotations

from hashlib import sha256
import unittest
from unittest.mock import patch
import warnings

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research import session_inventory_followup_discovery as followup


def synthetic_frame(rows: int = 1_200) -> pd.DataFrame:
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


class SessionInventoryFollowupDiscoveryTests(unittest.TestCase):
    def test_surface_has_exact_registered_twelve_and_bound_dependencies(self) -> None:
        configurations = followup.session_inventory_followup_configurations()
        executables = [
            followup.session_inventory_followup_executable(item)
            for item in configurations
        ]
        self.assertEqual(len(configurations), 12)
        self.assertEqual(len({item.identity for item in executables}), 12)
        self.assertEqual(
            [item.configuration_id for item in configurations[:4]],
            [
                "broker_02_inventory_11-fade-h24",
                "broker_02_inventory_11-fade-h72",
                "broker_02_inventory_11-follow-h24",
                "broker_02_inventory_11-follow-h72",
            ],
        )
        for executable in executables:
            self.assertIn(
                followup.session_inventory_followup_implementation_sha256(),
                executable.engine_contract,
            )
            self.assertIn(
                followup.trend_dependency_sha256(), executable.engine_contract
            )
            self.assertIn(
                followup.loader_implementation_sha256(), executable.engine_contract
            )
            self.assertIn("bonferroni_150", executable.engine_contract)

    def test_feature_is_prefix_invariant_and_rewarms_after_gap(self) -> None:
        frame = synthetic_frame()
        opportunities = {
            "broker_02_inventory_11": (1, 55),
            "broker_08_inventory_48": (7, 55),
            "broker_15_inventory_72": (14, 55),
        }
        for profile, expected_clock in opportunities.items():
            with warnings.catch_warnings():
                warnings.simplefilter("error", RuntimeWarning)
                full, _, _ = followup.compute_session_inventory_followup_score(
                    frame, profile
                )
            prefix, _, _ = followup.compute_session_inventory_followup_score(
                frame.iloc[:900], profile
            )
            np.testing.assert_allclose(
                full[:900], prefix, rtol=0.0, atol=0.0, equal_nan=True
            )
            finite_time = pd.to_datetime(frame.loc[np.isfinite(full), "time"])
            self.assertGreater(len(finite_time), 0)
            self.assertEqual(
                set(zip(finite_time.dt.hour, finite_time.dt.minute, strict=True)),
                {expected_clock},
            )

        gapped = frame[frame["time"] != pd.Timestamp("2024-01-02 07:45")].reset_index(
            drop=True
        )
        score, _, run = followup.compute_session_inventory_followup_score(
            gapped, "broker_08_inventory_48"
        )
        second = gapped.index[gapped["time"] == pd.Timestamp("2024-01-02 07:55")][0]
        third = gapped.index[gapped["time"] == pd.Timestamp("2024-01-03 07:55")][0]
        self.assertEqual(run[second], 2)
        self.assertTrue(np.isnan(score[second]))
        self.assertTrue(np.isfinite(score[third]))

    def test_fixed_broker_clock_rejects_timezone_relabelling(self) -> None:
        frame = synthetic_frame()
        frame["time"] = frame["time"].dt.tz_localize("UTC")
        with self.assertRaisesRegex(ValueError, "timezone-naive broker clock"):
            followup.compute_session_inventory_followup_score(
                frame, "broker_02_inventory_11"
            )

    def test_selector_is_fold_only_opportunity_median(self) -> None:
        score = np.arange(200, dtype=float)
        train = np.zeros(200, dtype=bool)
        train[:150] = True
        expected = np.quantile(np.abs(score[:150]), 0.50, method="higher")
        self.assertEqual(followup.calibrate_selector(score, train), expected)
        train[:] = False
        train[:99] = True
        with self.assertRaisesRegex(ValueError, "fewer than 100 opportunities"):
            followup.calibrate_selector(score, train)
        train[99] = True
        self.assertEqual(
            followup.calibrate_selector(score, train),
            np.quantile(np.abs(score[:100]), 0.50, method="higher"),
        )

    def test_registered_control_metrics_are_pairwise_noncompensatory(self) -> None:
        days = pd.date_range("2025-01-01", periods=40, freq="D")
        profile_net = {
            "broker_02_inventory_11": 100,
            "broker_08_inventory_48": 80,
            "broker_15_inventory_72": 60,
        }
        results = []
        for configuration in followup.session_inventory_followup_configurations():
            net = profile_net[configuration.profile] + 10 * configuration.signal_sign
            results.append(
                followup._ConfigurationResult(
                    configuration=configuration,
                    executable_id=followup.session_inventory_followup_executable(
                        configuration
                    ).identity,
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
            == "broker_02_inventory_11-follow-h24"
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
        for configuration in followup.session_inventory_followup_configurations():
            identity = followup.session_inventory_followup_executable(
                configuration
            ).identity
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
            "discovery_implementation_sha256": (
                followup.session_inventory_followup_implementation_sha256()
            ),
            "engine_environment": {}, "evaluations": evaluations,
            "loader_implementation_sha256": followup.loader_implementation_sha256(),
            "material_identity": followup.OBSERVED_MATERIAL_ID,
            "schema": "session_inventory_followup_surface.v1", "selection_context": context,
            "selection_method": {}, "session_semantics": "fixture",
            "split_artifact_sha256": followup.ROLLING_SPLIT_SHA256,
            "trend_dependency_sha256": followup.trend_dependency_sha256(),
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
        projected = followup.project_session_inventory_followup_evaluation(
            surface,
            job_execution=execution,
            subject_executable_id=subject,
            surface_artifact_hash=surface_hash,
            surface_manifest_hash="e" * 64,
        )
        self.assertEqual(projected["schema"], "session_inventory_followup_evaluation.v1")
        self.assertEqual(projected["subject_executable_id"], subject)
        canonical_bytes(projected)


if __name__ == "__main__":
    unittest.main()
