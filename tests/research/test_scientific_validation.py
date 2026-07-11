from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    EvidenceValidatorRegistry,
    ValidationArtifact,
    validator_identity,
)
from axiom_rift.research.validation import (
    SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
    SCIENTIFIC_MEASUREMENT_SCHEMA,
    SCIENTIFIC_VALIDATION_DOMAINS,
    SCIENTIFIC_VALIDATION_PROTOCOL,
    ScientificDiscoveryValidator,
    build_validation_plan,
)


MISSION_ID = "MIS-SCIENCE"
EXECUTABLE_ID = "executable:" + "e" * 64
JOB_ID = "job:" + "d" * 64
JOB_HASH = "a" * 64
CLAIM_ID = "after_cost_edge"
MODES = (
    "causal_contrast",
    "cost_and_execution",
    "sensitivity_or_stress",
)


def criteria() -> tuple[dict[str, object], ...]:
    return (
        {
            "claim_id": CLAIM_ID,
            "criterion_id": "C01-control-delta",
            "evidence_mode": "causal_contrast",
            "metric": "control_delta_net_profit_micropoints",
            "operator": "gt",
            "threshold": 0,
        },
        {
            "claim_id": CLAIM_ID,
            "criterion_id": "C02-native-cost",
            "evidence_mode": "cost_and_execution",
            "metric": "net_profit_micropoints",
            "operator": "gt",
            "threshold": 0,
        },
        {
            "claim_id": CLAIM_ID,
            "criterion_id": "C03-stress-cost",
            "evidence_mode": "sensitivity_or_stress",
            "metric": "stress_net_profit_micropoints",
            "operator": "ge",
            "threshold": 0,
        },
        {
            "claim_id": CLAIM_ID,
            "criterion_id": "C04-causal-invariant",
            "evidence_mode": "causal_contrast",
            "metric": "causality_violation_count",
            "operator": "eq",
            "threshold": 0,
        },
    )


def passing_metrics() -> dict[str, int | None]:
    return {
        "causality_violation_count": 0,
        "control_delta_net_profit_micropoints": 41_000,
        "evaluable_folds": 8,
        "net_profit_micropoints": 125_000,
        "stress_net_profit_micropoints": 8_000,
        "trade_count": 137,
    }


class ScientificValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _artifact(self, output_name: str, payload: object) -> ValidationArtifact:
        content = canonical_bytes(payload)
        digest = sha256(content).hexdigest()
        path = self.root / f"{len(tuple(self.root.iterdir())):02d}-{digest}.json"
        path.write_bytes(content)
        return ValidationArtifact(output_name=output_name, sha256=digest, _source=path)

    def _request(
        self,
        *,
        raw_metrics: dict[str, int | None] | None = None,
        depth: str = "discovery",
        candidate_eligible_on_pass: bool = False,
        measurement_updates: dict[str, object] | None = None,
        result_manifest_updates: dict[str, object] | None = None,
        request_result_updates: dict[str, object] | None = None,
        plan_updates: dict[str, object] | None = None,
        validation_plan_hash: str | None = None,
        include_auxiliary: bool = False,
        evaluation_schema: str = "trend_discovery_evaluation.v3",
        selection_total_exposures: int = 42,
    ) -> tuple[EvidenceValidationRequest, tuple[ValidationArtifact, ...]]:
        plan = build_validation_plan(
            mission_id=MISSION_ID,
            executable_id=EXECUTABLE_ID,
            evidence_depth=depth,
            planned_claims=(CLAIM_ID,),
            evidence_modes=MODES,
            criteria=criteria(),
            candidate_eligible_on_pass=candidate_eligible_on_pass,
        )
        if plan_updates:
            plan.update(plan_updates)
        plan_artifact = self._artifact("evidence/validation-plan", plan)
        observed_metrics = raw_metrics or passing_metrics()
        context_metrics = {
            key: (0 if value is None else value)
            for key, value in observed_metrics.items()
        }
        context_metrics.update(
            {
                "append_invariance_mismatch_count": 0,
                "causality_violation_count": 0,
                "nonfinite_metric_count": 0,
                "prefix_invariance_mismatch_count": 0,
                "selection_aware_pvalue_ppm": context_metrics.get(
                    "selection_aware_pvalue_ppm", 50_000
                ),
                "unknown_cost_unresolved_signal_count": (
                    1 if any(value is None for value in observed_metrics.values()) else 0
                ),
            }
        )
        context_metrics.setdefault("net_profit_micropoints", 0)
        selection_context = [
            {
                "configuration_id": "subject",
                "executable_id": EXECUTABLE_ID,
                "net_profit_micropoints": context_metrics["net_profit_micropoints"],
                "selection_aware_pvalue_ppm": context_metrics[
                    "selection_aware_pvalue_ppm"
                ],
            }
        ] + [
            {
                "configuration_id": f"control-{index}",
                "executable_id": "executable:" + f"{index:064x}",
                "net_profit_micropoints": 0,
                "selection_aware_pvalue_ppm": 1_000_000,
            }
            for index in range(1, 12)
        ]
        job_execution = {
            "job_hash": JOB_HASH,
            "job_id": JOB_ID,
            "job_permit_id": "b" * 64,
            "start_record_id": "c" * 64,
        }
        evaluation = {
            "claim_limits": ["discovery_only"],
            "direction_metrics": [
                {"direction": "long", "net_profit_micropoints": 1, "trade_count": 1},
                {"direction": "short", "net_profit_micropoints": 1, "trade_count": 1},
            ],
            "evaluable": not any(value is None for value in observed_metrics.values()),
            "fold_metrics": [
                {"fold_id": f"rw_{index:03d}", "trade_count": 1}
                for index in range(1, 10)
            ],
            "job_execution": {
                **job_execution,
                "identity": canonical_digest(
                    domain="running-job-execution",
                    payload=job_execution,
                ),
            },
            "metrics": context_metrics,
            "regime_metrics": [
                {"regime": name, "trade_count": 1}
                for name in ("low", "middle", "high")
            ],
            "schema": evaluation_schema,
            "selection_context": selection_context,
            "selection_method": {
                "bootstrap_samples": 41999,
                "block_days": [5, 10, 20],
                "method": (
                    "centered_non_circular_moving_block_studentized_one_sided_"
                    "then_bonferroni"
                ),
                "monte_carlo_upper_confidence_ppm": 990000,
                "multiple_block_rule": "maximum_adjusted_pvalue",
                "paired_control_rule": (
                    "same_eligible_decision_day_intersection_union_worst_control"
                ),
                "seed": 612337279,
                "seed_derivation": (
                    "sha256_base_seed_label_block_length_first_u64"
                ),
                "total_exposures": selection_total_exposures,
            },
            "session_metrics": [
                {"session": name, "trade_count": 1}
                for name in (
                    "broker_01_07",
                    "broker_08_14",
                    "broker_15_22",
                    "broker_23_00",
                )
            ],
            "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
            "subject_configuration_id": "subject",
            "subject_executable_id": EXECUTABLE_ID,
            "surface_artifact_hash": "f" * 64,
            "surface_manifest_hash": "1" * 64,
        }
        evaluation_artifact = self._artifact("evidence/evaluation", evaluation)
        measurement: dict[str, object] = {
            "claims": [CLAIM_ID],
            "evidence_depth": depth,
            "evidence_modes": list(MODES),
            "evaluation_artifact_hash": evaluation_artifact.sha256,
            "executable_id": EXECUTABLE_ID,
            "job_hash": JOB_HASH,
            "job_id": JOB_ID,
            "metrics": {CLAIM_ID: observed_metrics},
            "mission_id": MISSION_ID,
            "schema": SCIENTIFIC_MEASUREMENT_SCHEMA,
        }
        if measurement_updates:
            measurement.update(measurement_updates)
        measurement_artifact = self._artifact("evidence/measurement", measurement)
        result: dict[str, object] = {
            "evidence_depth": depth,
            "executable_id": EXECUTABLE_ID,
            "job_hash": JOB_HASH,
            "job_id": JOB_ID,
            "mission_id": MISSION_ID,
            "observations": [
                {
                    "claim_id": CLAIM_ID,
                    "measurement_artifact_hash": measurement_artifact.sha256,
                }
            ],
            "schema": "scientific_job_evidence.v1",
        }
        if result_manifest_updates:
            result.update(result_manifest_updates)
        result_artifact = self._artifact("evidence/result", result)
        request_result = parse_canonical(canonical_bytes(result))
        assert isinstance(request_result, dict)
        if request_result_updates:
            request_result.update(request_result_updates)
        artifacts: list[ValidationArtifact] = [
            result_artifact,
            plan_artifact,
            evaluation_artifact,
        ]
        if include_auxiliary:
            artifacts.append(
                self._artifact(
                    "evidence/fold-context",
                    {"fold_count": 9, "schema": "scientific_fold_context.v1"},
                )
            )
        artifacts.append(measurement_artifact)
        plan_hash = validation_plan_hash or plan_artifact.sha256
        request = EvidenceValidationRequest(
            domain="scientific",
            validator_id=SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
            validation_plan_hash=plan_hash,
            job_id=JOB_ID,
            job_hash=JOB_HASH,
            mission_id=MISSION_ID,
            evidence_subject={"kind": "Executable", "id": EXECUTABLE_ID},
            binding={
                "evidence_depth": depth,
                "evidence_modes": list(MODES),
                "planned_claims": [CLAIM_ID],
                "result_manifest_output": "evidence/result",
                "validation_plan_hash": plan_hash,
                "validator_id": SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
            },
            result_manifest=request_result,
            artifacts=tuple(artifacts),
        )
        return request, tuple(artifacts)

    def _validate(self, request: EvidenceValidationRequest):
        registry = EvidenceValidatorRegistry((ScientificDiscoveryValidator(),))
        return registry.validate(request)

    def test_identity_binds_protocol_domain_and_implementation_bytes(self) -> None:
        validator = ScientificDiscoveryValidator()
        implementation_hash = sha256(validator.implementation_path.read_bytes()).hexdigest()
        self.assertEqual(
            SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
            validator_identity(
                protocol=SCIENTIFIC_VALIDATION_PROTOCOL,
                domains=SCIENTIFIC_VALIDATION_DOMAINS,
                implementation_sha256=implementation_hash,
            ),
        )
        EvidenceValidatorRegistry((validator,))

    def test_pass_is_derived_and_every_durable_artifact_is_read(self) -> None:
        request, artifacts = self._request(include_auxiliary=True)

        validated, trace = self._validate(request)

        self.assertEqual(validated.verdict, "passed")
        self.assertEqual(validated.claims, (CLAIM_ID,))
        self.assertEqual(
            dict(validated.facts), {"executed_evidence_modes": list(MODES)}
        )
        self.assertTrue(validated.scientific_eligible)
        self.assertFalse(validated.candidate_eligible)
        self.assertFalse(validated.release_eligible)
        self.assertEqual(trace.declared_artifact_count, 5)
        self.assertEqual(trace.opened_artifact_count, 5)
        self.assertTrue(all(artifact.was_read for artifact in artifacts))

    def test_cross_asset_relative_strength_schema_binds_234_exposures(self) -> None:
        request, _ = self._request(
            evaluation_schema="cross_asset_relative_strength_evaluation.v1",
            selection_total_exposures=234,
        )

        validated, _ = self._validate(request)

        self.assertEqual(validated.verdict, "passed")
        self.assertTrue(validated.scientific_eligible)
        self.assertFalse(validated.candidate_eligible)

    def test_cross_asset_downside_spillover_schema_binds_246_exposures(self) -> None:
        request, _ = self._request(
            evaluation_schema="cross_asset_downside_spillover_evaluation.v1",
            selection_total_exposures=246,
        )

        validated, _ = self._validate(request)

        self.assertEqual(validated.verdict, "passed")
        self.assertTrue(validated.scientific_eligible)
        self.assertFalse(validated.candidate_eligible)

        stale_request, _ = self._request(
            evaluation_schema="cross_asset_downside_spillover_evaluation.v1",
            selection_total_exposures=234,
        )
        with self.assertRaises(EvidenceValidationError):
            self._validate(stale_request)

    def test_failed_and_not_evaluable_are_independently_derived(self) -> None:
        cases = {
            "failed": {
                **passing_metrics(),
                "net_profit_micropoints": -1,
            },
            "not_evaluable": {
                **passing_metrics(),
                "stress_net_profit_micropoints": None,
            },
        }
        for expected, raw_metrics in cases.items():
            with self.subTest(expected=expected):
                request, _ = self._request(raw_metrics=raw_metrics)
                validated, _ = self._validate(request)
                self.assertEqual(validated.verdict, expected)
                self.assertTrue(validated.scientific_eligible)
                self.assertFalse(validated.candidate_eligible)

    def test_null_metric_prevents_partial_failure_from_becoming_falsification(self) -> None:
        raw_metrics = {
            **passing_metrics(),
            "net_profit_micropoints": -1,
            "stress_net_profit_micropoints": None,
        }
        request, _ = self._request(raw_metrics=raw_metrics)

        validated, _ = self._validate(request)

        self.assertEqual(validated.verdict, "not_evaluable")

    def test_candidate_requires_explicit_passing_confirmation_plan(self) -> None:
        request, _ = self._request(
            depth="confirmation", candidate_eligible_on_pass=True
        )
        validated, _ = self._validate(request)
        self.assertTrue(validated.candidate_eligible)

        failed_metrics = {**passing_metrics(), "net_profit_micropoints": 0}
        failed_request, _ = self._request(
            depth="confirmation",
            candidate_eligible_on_pass=True,
            raw_metrics=failed_metrics,
        )
        failed, _ = self._validate(failed_request)
        self.assertEqual(failed.verdict, "failed")
        self.assertFalse(failed.candidate_eligible)

        with self.assertRaises(EvidenceValidationError):
            build_validation_plan(
                mission_id=MISSION_ID,
                executable_id=EXECUTABLE_ID,
                evidence_depth="discovery",
                planned_claims=(CLAIM_ID,),
                evidence_modes=MODES,
                criteria=criteria(),
                candidate_eligible_on_pass=True,
            )

    def test_caller_verdict_or_check_fields_are_rejected_not_trusted(self) -> None:
        request, artifacts = self._request(
            measurement_updates={"checks": {"all_passed": True}, "verdict": "passed"}
        )

        with self.assertRaisesRegex(
            EvidenceValidationError, "measurement schema is invalid"
        ):
            self._validate(request)
        self.assertTrue(all(artifact.was_read for artifact in artifacts))

    def test_plan_hash_and_result_manifest_bytes_are_rechecked(self) -> None:
        wrong_hash_request, _ = self._request(validation_plan_hash="f" * 64)
        with self.assertRaisesRegex(EvidenceValidationError, "plan hash differs"):
            self._validate(wrong_hash_request)

        caller_tamper, _ = self._request(
            request_result_updates={"job_id": "job:caller-tamper"}
        )
        with self.assertRaisesRegex(EvidenceValidationError, "caller result manifest"):
            self._validate(caller_tamper)

    def test_measurement_cannot_differ_from_raw_evaluation(self) -> None:
        changed = {**passing_metrics(), "net_profit_micropoints": 999_999}
        request, _ = self._request(
            measurement_updates={"metrics": {CLAIM_ID: changed}}
        )
        with self.assertRaisesRegex(
            EvidenceValidationError, "differs from raw evaluation"
        ):
            self._validate(request)

    def test_mission_job_executable_depth_claims_and_modes_are_exact(self) -> None:
        cases = (
            {"mission_id": "MIS-OTHER"},
            {"job_id": "job:other"},
            {"executable_id": "executable:" + "f" * 64},
            {"evidence_depth": "confirmation"},
            {"claims": ["other_claim"]},
            {"evidence_modes": ["causal_contrast"]},
        )
        for update in cases:
            with self.subTest(update=update):
                request, _ = self._request(measurement_updates=update)
                with self.assertRaises(EvidenceValidationError):
                    self._validate(request)

    def test_missing_preregistered_metric_is_engineering_invalidity(self) -> None:
        raw_metrics = passing_metrics()
        del raw_metrics["net_profit_micropoints"]
        request, _ = self._request(raw_metrics=raw_metrics)

        with self.assertRaisesRegex(EvidenceValidationError, "omits a preregistered"):
            self._validate(request)


if __name__ == "__main__":
    unittest.main()
