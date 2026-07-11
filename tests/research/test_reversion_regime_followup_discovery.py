
from __future__ import annotations

from hashlib import sha256
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research import reversion_regime_followup_discovery as followup


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


class ReversionRegimeFollowupDiscoveryTests(unittest.TestCase):
    def test_surface_has_exact_registered_twelve_and_bound_dependencies(self) -> None:
        configurations = followup.reversion_regime_followup_configurations()
        executables = [followup.reversion_regime_followup_executable(item) for item in configurations]
        self.assertEqual(len(configurations), 12)
        self.assertEqual(len({item.identity for item in executables}), 12)
        self.assertEqual(
            [item.configuration_id for item in configurations[:4]],
            [
                "slow96_unfiltered-reversion-h3",
                "slow96_unfiltered-reversion-h12",
                "slow96_unfiltered-continuation-h3",
                "slow96_unfiltered-continuation-h12",
            ],
        )
        for executable in executables:
            self.assertIn(followup.reversion_regime_followup_implementation_sha256(), executable.engine_contract)
            self.assertIn(followup.trend_dependency_sha256(), executable.engine_contract)
            self.assertIn(followup.loader_implementation_sha256(), executable.engine_contract)
            self.assertIn("bonferroni_186", executable.engine_contract)

    def test_feature_is_prefix_invariant_and_rewarms_after_gap(self) -> None:
        frame = synthetic_frame()
        full, _, _ = followup.compute_overextension_score(frame, 96)
        prefix, _, _ = followup.compute_overextension_score(frame.iloc[:400], 96)
        np.testing.assert_allclose(full[:400], prefix, rtol=0.0, atol=0.0, equal_nan=True)

        gapped = frame.copy()
        gapped.loc[250:, "time"] += pd.Timedelta(hours=2)
        score, _, run = followup.compute_overextension_score(gapped, 96)
        self.assertEqual(run[250], 1)
        self.assertTrue(np.isnan(score[345]))
        self.assertTrue(np.isfinite(score[346]))

    def test_middle_tertile_and_broker_clock_gates_are_exact(self) -> None:
        time = pd.Series(pd.date_range("2024-01-01", periods=288, freq="5min"))
        score = np.ones(288, dtype=float)
        volatility = np.linspace(0.0, 3.0, 288)
        middle = followup.apply_profile_gate(
            score,
            volatility,
            time,
            profile="slow96_middle_volatility_train_tertile",
            volatility_cutoffs=(1.0, 2.0),
        )
        self.assertTrue(
            np.all(
                np.isfinite(middle)
                == ((volatility >= 1.0) & (volatility <= 2.0))
            )
        )
        session = followup.apply_profile_gate(
            score,
            volatility,
            time,
            profile="slow96_broker15_22",
            volatility_cutoffs=(1.0, 2.0),
        )
        hour = time.dt.hour.to_numpy()
        self.assertTrue(
            np.all(np.isfinite(session) == ((hour >= 15) & (hour <= 22)))
        )

    def test_selector_is_fold_only_ninety_fifth_percentile(self) -> None:
        score = np.arange(2_000, dtype=float)
        train = np.zeros(2_000, dtype=bool)
        train[:1_500] = True
        expected = np.quantile(np.abs(score[:1_500]), 0.95, method="higher")
        self.assertEqual(followup.calibrate_selector(score, train), expected)

    def test_registered_control_metrics_are_pairwise_noncompensatory(self) -> None:
        days = pd.date_range("2025-01-01", periods=40, freq="D")
        profile_net = {
            "slow96_unfiltered": 100,
            "slow96_middle_volatility_train_tertile": 80,
            "slow96_broker15_22": 60,
        }
        results = []
        for configuration in followup.reversion_regime_followup_configurations():
            net = profile_net[configuration.profile] + 10 * configuration.signal_sign
            results.append(
                followup._ConfigurationResult(
                    configuration=configuration,
                    executable_id=followup.reversion_regime_followup_executable(configuration).identity,
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
            == "slow96_unfiltered-continuation-h3"
        )
        self.assertEqual(subject.metrics["feature_control_worst_delta_net_profit_micropoints"], 20)
        self.assertEqual(subject.metrics["opposite_sign_worst_delta_net_profit_micropoints"], 20)
        self.assertEqual(subject.metrics["feature_control_worst_pvalue_upper_ppm"], 50_000)

    def test_canonical_surface_projects_one_bound_subject(self) -> None:
        evaluations = []
        context = []
        for configuration in followup.reversion_regime_followup_configurations():
            identity = followup.reversion_regime_followup_executable(configuration).identity
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
            "discovery_implementation_sha256": followup.reversion_regime_followup_implementation_sha256(),
            "engine_environment": {}, "evaluations": evaluations,
            "loader_implementation_sha256": followup.loader_implementation_sha256(),
            "material_identity": followup.OBSERVED_MATERIAL_ID,
            "schema": "reversion_regime_followup_surface.v1", "selection_context": context,
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
        projected = followup.project_reversion_regime_followup_evaluation(
            surface,
            job_execution=execution,
            subject_executable_id=subject,
            surface_artifact_hash=surface_hash,
            surface_manifest_hash="e" * 64,
        )
        self.assertEqual(projected["schema"], "reversion_regime_followup_evaluation.v1")
        self.assertEqual(projected["subject_executable_id"], subject)
        canonical_bytes(projected)


if __name__ == "__main__":
    unittest.main()

