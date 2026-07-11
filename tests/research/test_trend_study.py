from __future__ import annotations

import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.writer import RunningJobExecution
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    discovery_implementation_sha256,
    loader_implementation_sha256,
    trend_configurations,
    trend_executable,
)
from axiom_rift.research.trend_study import (
    CALLABLE_IDENTITY,
    EVIDENCE_MODES,
    PLANNED_CLAIMS,
    build_measurement,
    build_environment_manifest,
    build_result_manifest,
    build_trend_validation_plan,
    execute_trend_job,
    output_names,
    planned_verdict,
    surface_cache_output_name,
    surface_manifest_output_name,
)


def evaluation(*, evaluable: bool = True, net: int = 1_000_000) -> dict[str, object]:
    return {
        "evaluable": evaluable,
        "metrics": {
            "append_invariance_mismatch_count": 0,
            "causality_violation_count": 0,
            "daily_entries_max_milli": 6000,
            "daily_entries_median_milli": 1000,
            "daily_entries_p10_milli": 0,
            "daily_entries_p90_milli": 3000,
            "eligible_day_count": 500,
            "entries_per_day_milli": 1000,
            "evaluable_folds": 9,
            "feature_control_worst_delta_net_profit_micropoints": 50_000,
            "feature_control_worst_pvalue_upper_ppm": 50_000,
            "gap_excluded_signal_count": 3,
            "median_fold_profit_factor_milli": 1200,
            "monthly_realized_exit_drawdown_micropoints": 100_000,
            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": 200_000,
            "net_profit_micropoints": net,
            "nonfinite_metric_count": 0,
            "opposite_sign_pvalue_upper_ppm": 50_000,
            "opposite_sign_worst_delta_net_profit_micropoints": 50_000,
            "positive_regime_count": 3,
            "prefix_invariance_mismatch_count": 0,
            "selection_aware_pvalue_ppm": 50_000,
            "stress_net_profit_micropoints": 100_000,
            "supported_positive_regime_count": 3,
            "top5_profit_day_share_ppm": 200_000,
            "trade_count": 500,
            "unknown_cost_unresolved_signal_count": 0,
            "winning_fold_count": 7,
            "zero_entry_day_rate_ppm": 100_000,
        },
    }


class TrendStudyPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.executable_id = trend_executable(trend_configurations()[0]).identity
        self.plan = build_trend_validation_plan(self.executable_id)

    def test_plan_is_canonical_and_covers_all_claims_and_modes(self) -> None:
        canonical_bytes(self.plan)
        self.assertEqual(tuple(self.plan["planned_claims"]), PLANNED_CLAIMS)
        self.assertEqual(tuple(self.plan["evidence_modes"]), EVIDENCE_MODES)
        self.assertEqual(
            {item["claim_id"] for item in self.plan["criteria"]},
            set(PLANNED_CLAIMS),
        )
        self.assertEqual(
            {item["evidence_mode"] for item in self.plan["criteria"]},
            set(EVIDENCE_MODES),
        )

    def test_measurement_and_result_are_exactly_bound(self) -> None:
        measurement = build_measurement(
            executable_id=self.executable_id,
            job_id="job:" + "a" * 64,
            job_hash="b" * 64,
            evaluation_artifact_hash="d" * 64,
            evaluation=evaluation(),
        )
        result = build_result_manifest(
            executable_id=self.executable_id,
            job_id="job:" + "a" * 64,
            job_hash="b" * 64,
            measurement_artifact_hash="c" * 64,
        )
        canonical_bytes(measurement)
        canonical_bytes(result)
        self.assertEqual(tuple(measurement["claims"]), PLANNED_CLAIMS)
        self.assertEqual(len(result["observations"]), len(PLANNED_CLAIMS))
        self.assertEqual(planned_verdict(self.plan, measurement), "passed")

    def test_failed_and_not_evaluable_completion_paths_are_distinct(self) -> None:
        failed = build_measurement(
            executable_id=self.executable_id,
            job_id="job:" + "a" * 64,
            job_hash="b" * 64,
            evaluation_artifact_hash="d" * 64,
            evaluation=evaluation(net=-1),
        )
        unavailable = build_measurement(
            executable_id=self.executable_id,
            job_id="job:" + "a" * 64,
            job_hash="b" * 64,
            evaluation_artifact_hash="d" * 64,
            evaluation=evaluation(evaluable=False),
        )
        self.assertEqual(planned_verdict(self.plan, failed), "failed")
        self.assertEqual(planned_verdict(self.plan, unavailable), "not_evaluable")

    def test_production_runner_binds_plan_environment_and_artifact_chain(self) -> None:
        environment = build_environment_manifest()
        from hashlib import sha256

        plan_hash = sha256(canonical_bytes(self.plan)).hexdigest()
        environment_hash = sha256(canonical_bytes(environment)).hexdigest()
        execution = RunningJobExecution(
            job_id="job:" + "a" * 64,
            job_hash="b" * 64,
            job_permit_id="c" * 64,
            start_record_id="d" * 64,
        )
        names = output_names(self.executable_id)
        cache_name = surface_cache_output_name()
        manifest_name = surface_manifest_output_name()
        expected_outputs = [*names.values(), cache_name, manifest_name]
        spec = {
            "callable_identity": CALLABLE_IDENTITY,
            "evidence_subject": {
                "kind": "Executable",
                "id": self.executable_id,
            },
            "expected_outputs": sorted(expected_outputs),
            "input_hashes": sorted(
                {
                    DATASET_SHA256,
                    OBSERVED_MATERIAL_ID,
                    ROLLING_SPLIT_SHA256,
                    discovery_implementation_sha256(),
                    environment_hash,
                    loader_implementation_sha256(),
                    plan_hash,
                }
            ),
            "output_classes": {
                **{name: "durable_evidence" for name in names.values()},
                cache_name: "reproducible_cache",
                manifest_name: "durable_evidence",
            },
            "scientific_binding": {
                "evidence_depth": "discovery",
                "evidence_modes": list(EVIDENCE_MODES),
                "planned_claims": list(PLANNED_CLAIMS),
                "result_manifest_output": names["result"],
                "validation_plan_hash": plan_hash,
                "validator_id": environment["validator_id"],
            },
        }
        binding = {
            "batch_id": "batch:fixture",
            "execution": execution.payload(),
            "initiative_id": "INI-0002",
            "mission_id": "MIS-0001",
            "spec": spec,
            "study_id": "STU-0002",
        }
        with TemporaryDirectory() as temporary, patch(
            "axiom_rift.research.trend_study.StateWriter.verify_running_job_execution",
            return_value=binding,
        ), patch(
            "axiom_rift.research.trend_study._compute_registered_trend_surface",
            return_value={"schema": "fixture_surface"},
        ), patch(
            "axiom_rift.research.trend_study.project_trend_evaluation",
            return_value=evaluation(),
        ):
            packet = execute_trend_job(
                repository_root=temporary,
                execution=execution,
            )
            consumer_execution = RunningJobExecution(
                job_id="job:" + "e" * 64,
                job_hash="f" * 64,
                job_permit_id="1" * 64,
                start_record_id="2" * 64,
            )
            consumer_spec = {
                **spec,
                "expected_outputs": sorted(names.values()),
                "input_hashes": sorted(
                    {
                        *spec["input_hashes"],
                        packet.surface_artifact_hash,
                        packet.surface_manifest_hash,
                    }
                ),
                "output_classes": {
                    name: "durable_evidence" for name in names.values()
                },
            }
            consumer_binding = {
                **binding,
                "execution": consumer_execution.payload(),
                "spec": consumer_spec,
            }
            with patch(
                "axiom_rift.research.trend_study.StateWriter.verify_running_job_execution",
                return_value=consumer_binding,
            ), patch(
                "axiom_rift.research.trend_study.StateWriter.verify_reproducible_cache_producer",
                return_value=None,
            ), patch(
                "axiom_rift.research.trend_study._compute_registered_trend_surface",
                side_effect=AssertionError("consumer recomputed the surface"),
            ):
                consumer_packet = execute_trend_job(
                    repository_root=temporary,
                    execution=consumer_execution,
                )
        hashes = packet.artifact_hashes()
        measurement = packet.artifact("measurement")
        result = packet.artifact("result")
        self.assertEqual(
            measurement["evaluation_artifact_hash"], hashes["context"]
        )
        self.assertTrue(
            all(
                item["measurement_artifact_hash"] == hashes["measurement"]
                for item in result["observations"]
            )
        )
        self.assertEqual(
            set(packet.completion_output_manifest()), set(expected_outputs)
        )
        self.assertEqual(
            consumer_packet.surface_artifact_hash,
            packet.surface_artifact_hash,
        )
        self.assertEqual(
            set(consumer_packet.completion_output_manifest()), set(names.values())
        )
        self.assertEqual(packet.verdict, "passed")


if __name__ == "__main__":
    unittest.main()
