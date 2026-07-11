from __future__ import annotations

import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.writer import RunningJobExecution
from axiom_rift.research.composite_consensus_discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    composite_consensus_implementation_sha256,
    loader_implementation_sha256,
    composite_consensus_executable_configuration_map,
    trend_dependency_sha256,
    volatility_dependency_sha256,
    reversion_dependency_sha256,
    volume_price_dependency_sha256,
)
from axiom_rift.research.composite_consensus_study import (
    CALLABLE_IDENTITY,
    EVALUATION_SCHEMA,
    EVIDENCE_MODES,
    PLANNED_CLAIMS,
    SELECTION_TOTAL_EXPOSURES,
    SURFACE_SCHEMA,
    build_measurement,
    build_environment_manifest,
    build_result_manifest,
    build_composite_consensus_validation_plan,
    execute_composite_consensus_job,
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
        "schema": EVALUATION_SCHEMA,
    }


class CompositeConsensusStudyPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        configuration_map = composite_consensus_executable_configuration_map()
        executable_ids = sorted(configuration_map)
        self.assertEqual(len(executable_ids), 12)
        self.assertEqual(
            {configuration.profile for configuration in configuration_map.values()},
            {
                "full_regime_consensus",
                "volume_primary_all_regimes",
                "middle_consensus_no_high",
            },
        )
        self.assertEqual(
            {configuration.holding_bars for configuration in configuration_map.values()},
            {24, 48},
        )
        self.assertEqual(
            {configuration.route_sign for configuration in configuration_map.values()},
            {-1, 1},
        )
        self.executable_id = executable_ids[0]
        self.plan = build_composite_consensus_validation_plan(self.executable_id)

    def test_plan_is_canonical_and_covers_all_claims_and_modes(self) -> None:
        canonical_bytes(self.plan)
        self.assertEqual(tuple(self.plan["planned_claims"]), PLANNED_CLAIMS)
        self.assertFalse(self.plan["candidate_eligible_on_pass"])
        self.assertEqual(SELECTION_TOTAL_EXPOSURES, 222)
        self.assertEqual(SURFACE_SCHEMA, "composite_consensus_surface.v1")
        self.assertEqual(
            EVALUATION_SCHEMA,
            "composite_consensus_evaluation.v1",
        )
        self.assertIn("daily_entries_p90_milli", evaluation()["metrics"])
        self.assertNotIn("daily_entries_p222_milli", evaluation()["metrics"])
        self.assertEqual(
            CALLABLE_IDENTITY,
            "axiom_rift.research.composite_consensus_study."
            "execute_composite_consensus_job.v1",
        )
        self.assertTrue(
            all(
                name.startswith("scientific/STU-0017/")
                for name in output_names(self.executable_id).values()
            )
        )
        self.assertTrue(
            surface_cache_output_name().startswith("local/cache/STU-0017/")
        )
        self.assertTrue(
            surface_manifest_output_name().startswith("scientific/STU-0017/")
        )
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
                    composite_consensus_implementation_sha256(),
                    environment_hash,
                    loader_implementation_sha256(),
                    plan_hash,
                    trend_dependency_sha256(),
                    volatility_dependency_sha256(),
                    reversion_dependency_sha256(),
                    volume_price_dependency_sha256(),
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
            "study_id": "STU-0017",
        }
        with TemporaryDirectory() as temporary, patch(
            "axiom_rift.research.composite_consensus_study.StateWriter.verify_running_job_execution",
            return_value=binding,
        ), patch(
            "axiom_rift.research.composite_consensus_study._compute_registered_composite_consensus_surface",
            return_value={"schema": SURFACE_SCHEMA},
        ), patch(
            "axiom_rift.research.composite_consensus_study.project_composite_consensus_evaluation",
            return_value=evaluation(),
        ):
            packet = execute_composite_consensus_job(
                repository_root=temporary,
                execution=execution,
            )
            consumer_cases = []
            for index, consumer_executable_id in enumerate(
                sorted(composite_consensus_executable_configuration_map())[1:],
                start=1,
            ):
                consumer_plan = build_composite_consensus_validation_plan(
                    consumer_executable_id
                )
                consumer_plan_hash = sha256(
                    canonical_bytes(consumer_plan)
                ).hexdigest()
                consumer_names = output_names(consumer_executable_id)
                consumer_execution = RunningJobExecution(
                    job_id="job:" + f"{index:064x}",
                    job_hash=f"{index + 20:064x}",
                    job_permit_id=f"{index + 40:064x}",
                    start_record_id=f"{index + 60:064x}",
                )
                consumer_spec = {
                    **spec,
                    "evidence_subject": {
                        "kind": "Executable",
                        "id": consumer_executable_id,
                    },
                    "expected_outputs": sorted(consumer_names.values()),
                    "input_hashes": sorted(
                        {
                            DATASET_SHA256,
                            OBSERVED_MATERIAL_ID,
                            ROLLING_SPLIT_SHA256,
                            composite_consensus_implementation_sha256(),
                            environment_hash,
                            loader_implementation_sha256(),
                            consumer_plan_hash,
                            trend_dependency_sha256(),
                            volatility_dependency_sha256(),
                            reversion_dependency_sha256(),
                            volume_price_dependency_sha256(),
                            packet.surface_artifact_hash,
                            packet.surface_manifest_hash,
                        }
                    ),
                    "output_classes": {
                        name: "durable_evidence"
                        for name in consumer_names.values()
                    },
                    "scientific_binding": {
                        "evidence_depth": "discovery",
                        "evidence_modes": list(EVIDENCE_MODES),
                        "planned_claims": list(PLANNED_CLAIMS),
                        "result_manifest_output": consumer_names["result"],
                        "validation_plan_hash": consumer_plan_hash,
                        "validator_id": environment["validator_id"],
                    },
                }
                consumer_binding = {
                    **binding,
                    "execution": consumer_execution.payload(),
                    "spec": consumer_spec,
                }
                consumer_cases.append(
                    (consumer_execution, consumer_binding, consumer_names)
                )
            with patch(
                "axiom_rift.research.composite_consensus_study.StateWriter.verify_running_job_execution",
                side_effect=[case[1] for case in consumer_cases],
            ), patch(
                "axiom_rift.research.composite_consensus_study.StateWriter.verify_reproducible_cache_producer",
                return_value=None,
            ) as verify_producer, patch(
                "axiom_rift.research.composite_consensus_study._compute_registered_composite_consensus_surface",
                side_effect=AssertionError("consumer recomputed the surface"),
            ) as recompute:
                consumer_packets = [
                    (
                        execute_composite_consensus_job(
                            repository_root=temporary,
                            execution=consumer_execution,
                        ),
                        consumer_names,
                    )
                    for consumer_execution, _, consumer_names in consumer_cases
                ]
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
        self.assertEqual(len(consumer_packets), 11)
        self.assertEqual(verify_producer.call_count, 11)
        self.assertEqual(recompute.call_count, 0)
        for consumer_packet, consumer_names in consumer_packets:
            self.assertEqual(
                consumer_packet.surface_artifact_hash,
                packet.surface_artifact_hash,
            )
            self.assertEqual(
                set(consumer_packet.completion_output_manifest()),
                set(consumer_names.values()),
            )
        self.assertEqual(packet.verdict, "passed")


if __name__ == "__main__":
    unittest.main()





