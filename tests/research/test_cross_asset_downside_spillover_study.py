from __future__ import annotations

import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.validation import (
    EvidenceValidationRequest,
    EvidenceValidatorRegistry,
    ValidationArtifact,
)
from axiom_rift.operations.writer import RunningJobExecution, StateWriter
from axiom_rift.research import cross_asset_downside_spillover_discovery as discovery
from axiom_rift.research.cross_asset_downside_spillover_discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    cross_asset_downside_spillover_implementation_sha256,
    loader_implementation_sha256,
    cross_asset_downside_spillover_executable_configuration_map,
    trend_dependency_sha256,
    us500_raw_sha256,
    us500_source_implementation_sha256,
)
from axiom_rift.research.us500_source import (
    US500_RAW_RELATIVE_PATH,
    us500_source_contract,
)
from axiom_rift.research.us500_source_study import (
    source_study_implementation_sha256,
    source_validator_implementation_sha256,
)
from axiom_rift.research.validation import (
    SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
    ScientificDiscoveryValidator,
)
from axiom_rift.research.cross_asset_downside_spillover_study import (
    CALLABLE_IDENTITY,
    EVALUATION_SCHEMA,
    EVIDENCE_MODES,
    PLANNED_CLAIMS,
    SELECTION_TOTAL_EXPOSURES,
    SURFACE_SCHEMA,
    build_measurement,
    build_environment_manifest,
    build_result_manifest,
    build_cross_asset_downside_spillover_validation_plan,
    execute_cross_asset_downside_spillover_job,
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


def validator_surface(repository_root: Path) -> dict[str, object]:
    """Build a cheap exact surface whose projection must pass the real validator."""

    configuration_map = cross_asset_downside_spillover_executable_configuration_map(
        repository_root
    )
    metrics = evaluation()["metrics"]
    assert isinstance(metrics, dict)
    folds = [
        {
            "fold_id": f"rw_{index:03d}",
            "net_profit_micropoints": 100_000,
            "profit_factor_milli": 1_200,
            "stress_net_profit_micropoints": 50_000,
            "trade_count": 50,
            "unresolved_cost_signal_count": 0,
        }
        for index in range(1, 10)
    ]
    regimes = [
        {
            "evaluable_fold_count": 9,
            "net_profit_micropoints": 100_000,
            "regime": regime,
            "trade_count": 100,
            "winning_fold_count": 7,
        }
        for regime in ("low", "middle", "high")
    ]
    sessions = [
        {
            "net_profit_micropoints": 100_000,
            "session": session,
            "trade_count": 100,
        }
        for session in (
            "broker_01_07",
            "broker_08_14",
            "broker_15_22",
            "broker_23_00",
        )
    ]
    directions = [
        {
            "direction": direction,
            "net_profit_micropoints": 100_000,
            "trade_count": 100,
        }
        for direction in ("long", "short")
    ]
    evaluations = [
        {
            "direction_metrics": directions,
            "evaluable": True,
            "fold_metrics": folds,
            "metrics": dict(metrics),
            "regime_metrics": regimes,
            "session_metrics": sessions,
            "subject_configuration_id": configuration.configuration_id,
            "subject_executable_id": executable_id,
        }
        for executable_id, configuration in sorted(configuration_map.items())
    ]
    raw_sha256 = us500_raw_sha256(repository_root)
    value: dict[str, object] = {
        "claim_limits": ["discovery_only"],
        "dataset_sha256": DATASET_SHA256,
        "discovery_implementation_sha256": (
            cross_asset_downside_spillover_implementation_sha256()
        ),
        "engine_environment": {"fixture": "validator_packet"},
        "evaluations": evaluations,
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "schema": SURFACE_SCHEMA,
        "selection_context": [
            {
                "configuration_id": configuration.configuration_id,
                "executable_id": executable_id,
                "net_profit_micropoints": metrics["net_profit_micropoints"],
                "selection_aware_pvalue_ppm": metrics[
                    "selection_aware_pvalue_ppm"
                ],
            }
            for executable_id, configuration in sorted(configuration_map.items())
        ],
        "selection_method": discovery._selection_method(),
        "session_semantics": (
            "broker_clock_fixed_bins_no_dst_or_cash_session_claim"
        ),
        "source_contract_identities": discovery._source_identity_payload(),
        "source_development_prefix_sha256": "e" * 64,
        "source_implementation_sha256": us500_source_implementation_sha256(),
        "source_raw_sha256": raw_sha256,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "trend_dependency_sha256": trend_dependency_sha256(),
    }
    canonical_bytes(value)
    return value


class CrossAssetDownsideSpilloverStudyPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        raw_path = self.root / US500_RAW_RELATIVE_PATH
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(b"time,open,high,low,close,tick_volume,spread,real_volume\n")
        configuration_map = cross_asset_downside_spillover_executable_configuration_map(
            self.root
        )
        executable_ids = sorted(configuration_map)
        self.assertEqual(len(executable_ids), 12)
        self.assertEqual(
            {configuration.profile for configuration in configuration_map.values()},
            {
                "source_downside_expansion",
                "source_symmetric_expansion",
                "target_only_downside",
            },
        )
        self.assertEqual(
            {configuration.holding_bars for configuration in configuration_map.values()},
            {3, 12},
        )
        self.assertEqual(
            {configuration.route_sign for configuration in configuration_map.values()},
            {-1, 1},
        )
        self.assertEqual(
            {
                (
                    configuration.profile,
                    configuration.route_sign,
                    configuration.holding_bars,
                )
                for configuration in configuration_map.values()
            },
            {
                (profile, route_sign, holding_bars)
                for profile in (
                    "source_downside_expansion",
                    "source_symmetric_expansion",
                    "target_only_downside",
                )
                for route_sign in (-1, 1)
                for holding_bars in (3, 12)
            },
        )
        self.executable_id = executable_ids[0]
        self.plan = build_cross_asset_downside_spillover_validation_plan(self.executable_id)

    def test_plan_is_canonical_and_covers_all_claims_and_modes(self) -> None:
        canonical_bytes(self.plan)
        self.assertEqual(tuple(self.plan["planned_claims"]), PLANNED_CLAIMS)
        self.assertEqual(len(PLANNED_CLAIMS), 6)
        self.assertEqual(len(EVIDENCE_MODES), 6)
        self.assertFalse(self.plan["candidate_eligible_on_pass"])
        self.assertEqual(SELECTION_TOTAL_EXPOSURES, 246)
        self.assertEqual(SURFACE_SCHEMA, "cross_asset_downside_spillover_surface.v1")
        self.assertEqual(
            EVALUATION_SCHEMA,
            "cross_asset_downside_spillover_evaluation.v1",
        )
        self.assertIn("daily_entries_p90_milli", evaluation()["metrics"])
        self.assertNotIn("daily_entries_p246_milli", evaluation()["metrics"])
        self.assertEqual(
            CALLABLE_IDENTITY,
            "axiom_rift.research.cross_asset_downside_spillover_study."
            "execute_cross_asset_downside_spillover_job.v1",
        )
        self.assertTrue(
            all(
                name.startswith("scientific/STU-0021/")
                for name in output_names(self.executable_id).values()
            )
        )
        self.assertTrue(
            surface_cache_output_name(self.root).startswith(
                "local/cache/STU-0021/"
            )
        )
        self.assertTrue(
            surface_manifest_output_name().startswith("scientific/STU-0021/")
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
        environment = build_environment_manifest(self.root)
        from hashlib import sha256

        source_id = us500_source_contract().source_contract_id
        self.assertEqual(environment["source_contract_id"], source_id)
        self.assertEqual(
            environment["source_contract_sha256"],
            source_id.removeprefix("source:"),
        )
        self.assertEqual(environment["source_raw_sha256"], us500_raw_sha256(self.root))
        self.assertEqual(
            environment["source_loader_implementation_sha256"],
            us500_source_implementation_sha256(),
        )
        self.assertEqual(
            environment["source_study_implementation_sha256"],
            source_study_implementation_sha256(),
        )
        self.assertEqual(
            environment["source_validator_implementation_sha256"],
            source_validator_implementation_sha256(),
        )
        plan_hash = sha256(canonical_bytes(self.plan)).hexdigest()
        environment_hash = sha256(canonical_bytes(environment)).hexdigest()
        execution = RunningJobExecution(
            job_id="job:" + "a" * 64,
            job_hash="b" * 64,
            job_permit_id="c" * 64,
            start_record_id="d" * 64,
        )
        names = output_names(self.executable_id)
        cache_name = surface_cache_output_name(self.root)
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
                    cross_asset_downside_spillover_implementation_sha256(),
                    environment_hash,
                    environment["runner_implementation_sha256"],
                    loader_implementation_sha256(),
                    plan_hash,
                    trend_dependency_sha256(),
                    environment["source_contract_sha256"],
                    environment["source_raw_sha256"],
                    environment["source_loader_implementation_sha256"],
                    environment["source_study_implementation_sha256"],
                    environment["source_validator_implementation_sha256"],
                    environment["scientific_validator_implementation_sha256"],
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
            "initiative_id": "INI-0005",
            "mission_id": "MIS-0001",
            "spec": spec,
            "study_id": "STU-0021",
        }
        with patch(
            "axiom_rift.research.cross_asset_downside_spillover_study.StateWriter.verify_running_job_execution",
            return_value=binding,
        ), patch(
            "axiom_rift.research.cross_asset_downside_spillover_study._compute_registered_cross_asset_downside_spillover_surface",
            return_value={"schema": SURFACE_SCHEMA},
        ), patch(
            "axiom_rift.research.cross_asset_downside_spillover_study.project_cross_asset_downside_spillover_evaluation",
            return_value=evaluation(),
        ):
            packet = execute_cross_asset_downside_spillover_job(
                repository_root=self.root,
                execution=execution,
            )
            consumer_cases = []
            for index, consumer_executable_id in enumerate(
                sorted(
                    cross_asset_downside_spillover_executable_configuration_map(
                        self.root
                    )
                )[1:],
                start=1,
            ):
                consumer_plan = build_cross_asset_downside_spillover_validation_plan(
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
                            cross_asset_downside_spillover_implementation_sha256(),
                            environment_hash,
                            environment["runner_implementation_sha256"],
                            loader_implementation_sha256(),
                            consumer_plan_hash,
                            trend_dependency_sha256(),
                            environment["source_contract_sha256"],
                            environment["source_raw_sha256"],
                            environment["source_loader_implementation_sha256"],
                            environment["source_study_implementation_sha256"],
                            environment["source_validator_implementation_sha256"],
                            environment["scientific_validator_implementation_sha256"],
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
                "axiom_rift.research.cross_asset_downside_spillover_study.StateWriter.verify_running_job_execution",
                side_effect=[case[1] for case in consumer_cases],
            ), patch(
                "axiom_rift.research.cross_asset_downside_spillover_study.StateWriter.verify_reproducible_cache_producer",
                return_value=None,
            ) as verify_producer, patch(
                "axiom_rift.research.cross_asset_downside_spillover_study._compute_registered_cross_asset_downside_spillover_surface",
                side_effect=AssertionError("consumer recomputed the surface"),
            ) as recompute:
                consumer_packets = [
                    (
                        execute_cross_asset_downside_spillover_job(
                            repository_root=self.root,
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

    def test_full_packet_passes_the_registered_scientific_validator(self) -> None:
        from hashlib import sha256

        environment = build_environment_manifest(self.root)
        plan_hash = sha256(canonical_bytes(self.plan)).hexdigest()
        environment_hash = sha256(canonical_bytes(environment)).hexdigest()
        execution = RunningJobExecution(
            job_id="job:" + "1" * 64,
            job_hash="2" * 64,
            job_permit_id="3" * 64,
            start_record_id="4" * 64,
        )
        names = output_names(self.executable_id)
        cache_name = surface_cache_output_name(self.root)
        manifest_name = surface_manifest_output_name()
        spec = {
            "callable_identity": CALLABLE_IDENTITY,
            "evidence_subject": {
                "kind": "Executable",
                "id": self.executable_id,
            },
            "expected_outputs": sorted(
                [*names.values(), cache_name, manifest_name]
            ),
            "input_hashes": sorted(
                {
                    DATASET_SHA256,
                    OBSERVED_MATERIAL_ID,
                    ROLLING_SPLIT_SHA256,
                    cross_asset_downside_spillover_implementation_sha256(),
                    environment_hash,
                    environment["runner_implementation_sha256"],
                    loader_implementation_sha256(),
                    plan_hash,
                    trend_dependency_sha256(),
                    environment["source_contract_sha256"],
                    environment["source_raw_sha256"],
                    environment["source_loader_implementation_sha256"],
                    environment["source_study_implementation_sha256"],
                    environment["source_validator_implementation_sha256"],
                    environment["scientific_validator_implementation_sha256"],
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
                "validator_id": SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
            },
        }
        binding = {
            "batch_id": "batch:validator-fixture",
            "execution": execution.payload(),
            "initiative_id": "INI-0005",
            "mission_id": "MIS-0001",
            "spec": spec,
            "study_id": "STU-0021",
        }
        with patch(
            "axiom_rift.research.cross_asset_downside_spillover_study.StateWriter.verify_running_job_execution",
            return_value=binding,
        ), patch(
            "axiom_rift.research.cross_asset_downside_spillover_study._compute_registered_cross_asset_downside_spillover_surface",
            return_value=validator_surface(self.root),
        ):
            packet = execute_cross_asset_downside_spillover_job(
                repository_root=self.root,
                execution=execution,
            )

        context = packet.artifact("context")
        self.assertEqual(
            set(context),
            {
                "claim_limits",
                "direction_metrics",
                "evaluable",
                "fold_metrics",
                "job_execution",
                "metrics",
                "regime_metrics",
                "schema",
                "selection_context",
                "selection_method",
                "session_metrics",
                "session_semantics",
                "subject_configuration_id",
                "subject_executable_id",
                "surface_artifact_hash",
                "surface_manifest_hash",
            },
        )
        self.assertEqual(
            context["selection_method"]["paired_control_rule"],
            "same_eligible_decision_day_intersection_union_worst_control",
        )
        self.assertEqual(
            context["session_semantics"],
            "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        )
        output_manifest = packet.completion_output_manifest()
        output_classes = dict(packet.output_classes)
        writer = StateWriter(self.root)
        artifacts: list[ValidationArtifact] = []
        for output_name, artifact_hash in sorted(output_manifest.items()):
            if output_classes[output_name] != "durable_evidence":
                continue
            artifact = writer.evidence.verify(artifact_hash)
            artifacts.append(
                ValidationArtifact(
                    output_name=output_name,
                    sha256=artifact.sha256,
                    _source=writer.evidence._root / artifact.relative_path,
                )
            )
        request = EvidenceValidationRequest(
            domain="scientific",
            validator_id=SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
            validation_plan_hash=plan_hash,
            job_id=execution.job_id,
            job_hash=execution.job_hash,
            mission_id="MIS-0001",
            evidence_subject=spec["evidence_subject"],
            binding=spec["scientific_binding"],
            result_manifest=packet.completion_result_manifest(),
            artifacts=tuple(artifacts),
        )
        validated, trace = EvidenceValidatorRegistry(
            (ScientificDiscoveryValidator(),)
        ).validate(request)
        self.assertEqual(validated.verdict, "passed")
        self.assertTrue(validated.scientific_eligible)
        self.assertFalse(validated.candidate_eligible)
        self.assertEqual(trace.declared_artifact_count, 6)
        self.assertEqual(trace.opened_artifact_count, 6)


if __name__ == "__main__":
    unittest.main()
