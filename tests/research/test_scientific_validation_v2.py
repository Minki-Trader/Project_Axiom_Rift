from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    EvidenceValidatorRegistry,
    ValidationArtifact,
    validator_identity,
    validator_implementation_sha256,
)
from axiom_rift.research.validation import (
    SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
    ScientificDiscoveryValidator,
)
from axiom_rift.research.scientific_trace import (
    SCIENTIFIC_TRACE_PROTOCOL_IDS,
    scientific_trace_validation_dependency_paths,
)
from axiom_rift.research.evidence_proofs import (
    COST_EXECUTION_PROOF_KIND,
    PAIRED_CONTROL_PROOF_KIND,
    TEMPORAL_STABILITY_PROOF_KIND,
    ScientificEvidenceProofError,
    build_mode_proof,
    build_proof_references,
    parse_proof_requirements,
    proof_requirements_for_modes,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_PROFILE_SCHEMA,
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    SCIENTIFIC_MEASUREMENT_V2_SCHEMA,
    SCIENTIFIC_RESULT_SCHEMA,
    SCIENTIFIC_VALIDATION_V2_DEPENDENCIES,
    SCIENTIFIC_VALIDATION_V2_DOMAINS,
    SCIENTIFIC_VALIDATION_V2_PROTOCOL,
    SCIENTIFIC_V2_MULTIPLICITY_METHOD,
    SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD,
    ScientificAdjudicationValidatorV2,
    build_validation_plan_v2,
    multiplicity_family_registration_hash,
)


MISSION_ID = "MIS-SCIENCE-V2"
EXECUTABLE_ID = "executable:" + "e" * 64
JOB_ID = "job:" + "d" * 64
JOB_HASH = "a" * 64
CLAIMS = ("causal_validity", "economic_edge", "selection_control")
MODES = ("causal_contrast", "cost_and_execution", "temporal_stability")
FAMILY_ID = "family:two-concurrent-hypotheses"
FAMILY_MEMBERS = ("hypothesis:alpha", "hypothesis:beta")
FAMILY_HASH = multiplicity_family_registration_hash(
    family_id=FAMILY_ID,
    alpha_ppm=100_000,
    method=SCIENTIFIC_V2_MULTIPLICITY_METHOD,
    ordered_member_ids=FAMILY_MEMBERS,
)
PROOF_OUTPUTS = {
    PAIRED_CONTROL_PROOF_KIND: "proofs/causal-contrast.json",
    COST_EXECUTION_PROOF_KIND: "proofs/cost-execution.json",
    TEMPORAL_STABILITY_PROOF_KIND: "proofs/temporal-stability.json",
}


def _criterion(
    criterion_id: str,
    claim_id: str,
    evidence_mode: str,
    metric: str,
    operator: str,
    threshold: int,
    decision_role: str,
) -> dict[str, object]:
    return {
        "claim_id": claim_id,
        "criterion_id": criterion_id,
        "decision_role": decision_role,
        "evidence_mode": evidence_mode,
        "metric": metric,
        "operator": operator,
        "threshold": threshold,
    }


def _plan(
    *,
    evidence_depth: str = "discovery",
    candidate_eligible_on_pass: bool = False,
    b04_decisive: bool = False,
) -> dict[str, object]:
    b04_role = "risk_gate" if b04_decisive else "risk_diagnostic"
    criteria = (
        _criterion(
            "C03-decision-time-causality",
            "causal_validity",
            "causal_contrast",
            "causality_violation_count",
            "eq",
            0,
            "validity",
        ),
        _criterion(
            "C04-resolved-cost",
            "causal_validity",
            "cost_and_execution",
            "unknown_cost_unresolved_signal_count",
            "eq",
            0,
            "validity",
        ),
        _criterion(
            "C05-finite-metrics",
            "causal_validity",
            "causal_contrast",
            "nonfinite_metric_count",
            "eq",
            0,
            "validity",
        ),
        _criterion(
            "B01-positive-native-cost",
            "economic_edge",
            "cost_and_execution",
            "net_profit_micropoints",
            "gt",
            0,
            "component",
        ),
        _criterion(
            "B04-monthly-realized-drawdown-share",
            "economic_edge",
            "cost_and_execution",
            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm",
            "le",
            500_000,
            b04_role,
        ),
        _criterion(
            "D04-primary-control-uncertainty",
            "selection_control",
            "temporal_stability",
            "primary_control_raw_pvalue_ppm",
            "le",
            100_000,
            "multiplicity",
        ),
        _criterion(
            "E01-familywise-selection",
            "selection_control",
            "temporal_stability",
            "selection_raw_pvalue_ppm",
            "le",
            100_000,
            "multiplicity",
        ),
    )
    profile = {
        "decisive_risk_criterion_ids": (
            ["B04-monthly-realized-drawdown-share"] if b04_decisive else []
        ),
        "multiplicity": [
            {
                "alpha_ppm": 100_000,
                "criterion_id": "D04-primary-control-uncertainty",
                "family_id": FAMILY_ID,
                "family_registration_hash": FAMILY_HASH,
                "family_size": 2,
                "member_id": FAMILY_MEMBERS[0],
                "method": SCIENTIFIC_V2_MULTIPLICITY_METHOD,
                "ordered_member_ids": list(FAMILY_MEMBERS),
            },
            {
                "alpha_ppm": 100_000,
                "criterion_id": "E01-familywise-selection",
                "family_id": FAMILY_ID,
                "family_registration_hash": FAMILY_HASH,
                "family_size": 2,
                "member_id": FAMILY_MEMBERS[1],
                "method": SCIENTIFIC_V2_MULTIPLICITY_METHOD,
                "ordered_member_ids": list(FAMILY_MEMBERS),
            }
        ],
        "promotion_criterion_ids": [
            "B01-positive-native-cost",
            "D04-primary-control-uncertainty",
            "E01-familywise-selection",
        ],
        "schema": SCIENTIFIC_ADJUDICATION_PROFILE_SCHEMA,
    }
    return build_validation_plan_v2(
        mission_id=MISSION_ID,
        executable_id=EXECUTABLE_ID,
        evidence_depth=evidence_depth,
        planned_claims=CLAIMS,
        evidence_modes=MODES,
        criteria=criteria,
        adjudication_profile=profile,
        proof_requirements=proof_requirements_for_modes(
            evidence_modes=MODES,
            output_names=PROOF_OUTPUTS,
        ),
        candidate_eligible_on_pass=candidate_eligible_on_pass,
    )


def _measurement(*, evidence_depth: str = "discovery") -> dict[str, object]:
    return {
        "evidence_depth": evidence_depth,
        "evidence_modes": list(MODES),
        "executable_id": EXECUTABLE_ID,
        "job_hash": JOB_HASH,
        "job_id": JOB_ID,
        "metrics": {
            "causal_validity": {
                "causality_violation_count": 0,
                "nonfinite_metric_count": 0,
                "unknown_cost_unresolved_signal_count": 0,
            },
            "economic_edge": {
                "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": 800_000,
                "net_profit_micropoints": 1_000,
            },
            "selection_control": {
                "primary_control_raw_pvalue_ppm": 30_000,
                "selection_raw_pvalue_ppm": 20_000,
            },
        },
        "mission_id": MISSION_ID,
        "multiplicity": [
            {
                "adjusted_pvalue_ppm": 60_000,
                "alpha_ppm": 100_000,
                "criterion_id": "D04-primary-control-uncertainty",
                "family_id": FAMILY_ID,
                "family_registration_hash": FAMILY_HASH,
                "family_size": 2,
                "member_id": FAMILY_MEMBERS[0],
                "method": SCIENTIFIC_V2_MULTIPLICITY_METHOD,
                "ordered_member_ids": list(FAMILY_MEMBERS),
                "raw_pvalue_ppm": 30_000,
            },
            {
                "adjusted_pvalue_ppm": 40_000,
                "alpha_ppm": 100_000,
                "criterion_id": "E01-familywise-selection",
                "family_id": FAMILY_ID,
                "family_registration_hash": FAMILY_HASH,
                "family_size": 2,
                "member_id": FAMILY_MEMBERS[1],
                "method": SCIENTIFIC_V2_MULTIPLICITY_METHOD,
                "ordered_member_ids": list(FAMILY_MEMBERS),
                "raw_pvalue_ppm": 20_000,
            }
        ],
        "proofs": [],
        "schema": SCIENTIFIC_MEASUREMENT_V2_SCHEMA,
    }


def _request(
    root: Path,
    *,
    plan: dict[str, object],
    measurement: dict[str, object],
) -> EvidenceValidationRequest:
    measurement = deepcopy(measurement)
    requirements = parse_proof_requirements(
        plan["proof_requirements"], evidence_modes=MODES
    )
    bindings_by_mode: dict[str, list[dict[str, object]]] = {
        mode: [] for mode in MODES
    }
    for criterion in plan["criteria"]:
        bindings_by_mode[criterion["evidence_mode"]].append(
            {
                "claim_id": criterion["claim_id"],
                "metric": criterion["metric"],
                "value": measurement["metrics"][criterion["claim_id"]][
                    criterion["metric"]
                ],
            }
        )
    metric_bindings = {
        mode: sorted(
            values,
            key=lambda item: (str(item["claim_id"]), str(item["metric"])),
        )
        for mode, values in bindings_by_mode.items()
    }
    mode_proofs = {
        PAIRED_CONTROL_PROOF_KIND: build_mode_proof(
            evidence_mode="causal_contrast",
            proof_kind=PAIRED_CONTROL_PROOF_KIND,
            mission_id=MISSION_ID,
            executable_id=EXECUTABLE_ID,
            job_id=JOB_ID,
            job_hash=JOB_HASH,
            proof={
                "calendar_identity": "calendar:" + "1" * 64,
                "control_executable_id": "executable:" + "c" * 64,
                "delta_metric": "primary_control_delta_micropoints",
                "metric_bindings": metric_bindings["causal_contrast"],
                "paired_observation_count": 120,
                "subject_executable_id": EXECUTABLE_ID,
                "uncertainty_metric": "primary_control_raw_pvalue_ppm",
            },
        ),
        COST_EXECUTION_PROOF_KIND: build_mode_proof(
            evidence_mode="cost_and_execution",
            proof_kind=COST_EXECUTION_PROOF_KIND,
            mission_id=MISSION_ID,
            executable_id=EXECUTABLE_ID,
            job_id=JOB_ID,
            job_hash=JOB_HASH,
            proof={
                "cost_contract": "cost:fixed-test-spread-and-stress",
                "metric_bindings": metric_bindings["cost_and_execution"],
                "native_cost_observation_count": 120,
                "stress_cost_observation_count": 120,
                "unresolved_cost_observation_count": 0,
            },
        ),
        TEMPORAL_STABILITY_PROOF_KIND: build_mode_proof(
            evidence_mode="temporal_stability",
            proof_kind=TEMPORAL_STABILITY_PROOF_KIND,
            mission_id=MISSION_ID,
            executable_id=EXECUTABLE_ID,
            job_id=JOB_ID,
            job_hash=JOB_HASH,
            proof={
                "calendar_identity": "calendar:" + "1" * 64,
                "metric_bindings": metric_bindings["temporal_stability"],
                "observation_count": 120,
                "window_count": 9,
            },
        ),
    }
    proof_payloads = {
        PROOF_OUTPUTS[kind]: canonical_bytes(value)
        for kind, value in mode_proofs.items()
    }
    measurement["proofs"] = list(
        build_proof_references(
            requirements=requirements,
            artifact_hashes={
                output_name: sha256(content).hexdigest()
                for output_name, content in proof_payloads.items()
            },
        )
    )
    plan_content = canonical_bytes(plan)
    measurement_content = canonical_bytes(measurement)
    plan_hash = sha256(plan_content).hexdigest()
    measurement_hash = sha256(measurement_content).hexdigest()
    result = {
        "evidence_depth": plan["evidence_depth"],
        "executable_id": EXECUTABLE_ID,
        "job_hash": JOB_HASH,
        "job_id": JOB_ID,
        "mission_id": MISSION_ID,
        "observations": [
            {
                "claim_id": claim,
                "measurement_artifact_hash": measurement_hash,
            }
            for claim in CLAIMS
        ],
        "schema": SCIENTIFIC_RESULT_SCHEMA,
    }
    result_content = canonical_bytes(result)
    payloads = {
        "plan": plan_content,
        "measurement": measurement_content,
        "result": result_content,
        **proof_payloads,
    }
    artifacts: list[ValidationArtifact] = []
    for output_name, content in payloads.items():
        path = root / output_name
        if path.suffix != ".json":
            path = path.with_suffix(".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        artifacts.append(
            ValidationArtifact(
                output_name=output_name,
                sha256=sha256(content).hexdigest(),
                _source=path,
            )
        )
    return EvidenceValidationRequest(
        domain="scientific",
        validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        validation_plan_hash=plan_hash,
        job_id=JOB_ID,
        job_hash=JOB_HASH,
        mission_id=MISSION_ID,
        evidence_subject={"kind": "Executable", "id": EXECUTABLE_ID},
        binding={
            "evidence_depth": plan["evidence_depth"],
            "evidence_modes": list(MODES),
            "planned_claims": list(CLAIMS),
            "result_manifest_output": "result",
            "validation_plan_hash": plan_hash,
            "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        },
        result_manifest=result,
        artifacts=tuple(artifacts),
    )


class ScientificValidationV2Tests(unittest.TestCase):
    def _validate(self, request: EvidenceValidationRequest):
        registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
        return registry.validate(request)[0]

    def test_v1_and_v2_identities_bind_declared_dependency_closures(self) -> None:
        v1_validator = ScientificDiscoveryValidator()
        self.assertEqual(
            SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
            validator_identity(
                protocol=v1_validator.protocol,
                domains=v1_validator.domains,
                implementation_sha256=validator_implementation_sha256(
                    implementation_path=v1_validator.implementation_path,
                    dependency_paths=v1_validator.dependency_paths,
                ),
            ),
        )
        validator = ScientificAdjudicationValidatorV2()
        implementation_hash = validator_implementation_sha256(
            implementation_path=validator.implementation_path,
            dependency_paths=SCIENTIFIC_VALIDATION_V2_DEPENDENCIES,
        )
        self.assertEqual(
            SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
            validator_identity(
                protocol=SCIENTIFIC_VALIDATION_V2_PROTOCOL,
                domains=SCIENTIFIC_VALIDATION_V2_DOMAINS,
                implementation_sha256=implementation_hash,
            ),
        )

    def test_v2_identity_covers_every_lazy_trace_protocol_dependency(self) -> None:
        dependency_paths = set(SCIENTIFIC_VALIDATION_V2_DEPENDENCIES)
        trace_paths = set(scientific_trace_validation_dependency_paths())
        self.assertTrue(trace_paths.issubset(dependency_paths))
        self.assertEqual(len(SCIENTIFIC_TRACE_PROTOCOL_IDS), 8)
        trace_names = {path.name for path in trace_paths}
        self.assertEqual(
            trace_names,
            {
                "analog_state_family.py",
                "analog_state_replay.py",
                "analog_state_replay_v2.py",
                "analog_state_scoped_job.py",
                "analog_state_trace.py",
                "fixed_hold_family_trace.py",
                "historical_family_binding.py",
            },
        )
        self.assertTrue(
            {
                "analog_fixed_hold_replay.py",
                "composite_consensus_replay.py",
                "composite_router_replay.py",
                "distribution_asymmetry_replay.py",
                "historical_family_replay.py",
                "historical_family_stu0016.py",
                "historical_family_stu0017.py",
                "historical_family_stu0032.py",
                "historical_family_stu0048.py",
                "historical_family_stu0051.py",
                "historical_family_stu0061.py",
                "volatility_duration_replay.py",
            }.isdisjoint(trace_names)
        )
        self.assertIn(
            Path(__file__).resolve().parents[2]
            / "src"
            / "axiom_rift"
            / "research"
            / "p0_replay_inventory.json",
            dependency_paths,
        )

    def test_discovery_passes_with_b04_diagnostic_but_never_candidate(self) -> None:
        with TemporaryDirectory() as root:
            request = _request(
                Path(root), plan=_plan(), measurement=_measurement()
            )

            validated = self._validate(request)

        self.assertEqual(validated.verdict, "passed")
        self.assertFalse(validated.candidate_eligible)
        facts = dict(validated.facts)
        self.assertEqual(facts["executed_evidence_modes"], list(MODES))
        adjudication = facts["scientific_adjudication"]
        self.assertEqual(adjudication["schema"], "scientific_adjudication.v1")
        self.assertEqual(adjudication["state"], "frontier")
        self.assertEqual(adjudication["evidence_depth"], "discovery")
        self.assertFalse(adjudication["candidate_eligible"])
        self.assertEqual(
            adjudication["multiplicity"][0]["family_id"],
            "family:two-concurrent-hypotheses",
        )
        self.assertIn(
            "risk_diagnostic",
            {item["decision_role"] for item in adjudication["criteria"]},
        )

    def test_missing_or_hash_drifted_mode_proof_is_rejected(self) -> None:
        with TemporaryDirectory() as root:
            request = _request(
                Path(root), plan=_plan(), measurement=_measurement()
            )
            missing = replace(
                request,
                artifacts=tuple(
                    artifact
                    for artifact in request.artifacts
                    if artifact.output_name
                    != PROOF_OUTPUTS[TEMPORAL_STABILITY_PROOF_KIND]
                ),
            )
            with self.assertRaises(EvidenceValidationError):
                self._validate(missing)

            target = next(
                artifact
                for artifact in request.artifacts
                if artifact.output_name
                == PROOF_OUTPUTS[TEMPORAL_STABILITY_PROOF_KIND]
            )
            drifted_content = target.read_bytes().replace(
                b'"window_count":9', b'"window_count":8'
            )
            self.assertNotEqual(drifted_content, target.read_bytes())
            drifted_path = Path(root) / "proofs/drifted-temporal.json"
            drifted_path.write_bytes(drifted_content)
            drifted_artifact = ValidationArtifact(
                output_name=target.output_name,
                sha256=sha256(drifted_content).hexdigest(),
                _source=drifted_path,
            )
            hash_drifted = replace(
                request,
                artifacts=tuple(
                    drifted_artifact if artifact is target else artifact
                    for artifact in request.artifacts
                ),
            )
            with self.assertRaises(EvidenceValidationError):
                self._validate(hash_drifted)

    def test_paired_control_proof_cannot_reuse_subject_as_control(self) -> None:
        with self.assertRaises(ScientificEvidenceProofError):
            build_mode_proof(
                evidence_mode="causal_contrast",
                proof_kind=PAIRED_CONTROL_PROOF_KIND,
                mission_id=MISSION_ID,
                executable_id=EXECUTABLE_ID,
                job_id=JOB_ID,
                job_hash=JOB_HASH,
                proof={
                    "calendar_identity": "calendar:" + "1" * 64,
                    "control_executable_id": EXECUTABLE_ID,
                    "delta_metric": "primary_control_delta_micropoints",
                    "metric_bindings": [],
                    "paired_observation_count": 120,
                    "subject_executable_id": EXECUTABLE_ID,
                    "uncertainty_metric": "primary_control_raw_pvalue_ppm",
                },
            )

    def test_b04_is_decisive_only_when_profile_registers_risk_gate(self) -> None:
        with TemporaryDirectory() as root:
            request = _request(
                Path(root),
                plan=_plan(b04_decisive=True),
                measurement=_measurement(),
            )

            validated = self._validate(request)

        self.assertEqual(validated.verdict, "not_evaluable")
        self.assertFalse(validated.candidate_eligible)

    def test_validity_failure_is_not_evaluable(self) -> None:
        measurement = _measurement()
        measurement["metrics"]["causal_validity"]["nonfinite_metric_count"] = 1
        with TemporaryDirectory() as root:
            request = _request(
                Path(root), plan=_plan(), measurement=measurement
            )

            validated = self._validate(request)

        self.assertEqual(validated.verdict, "not_evaluable")
        self.assertFalse(validated.candidate_eligible)

    def test_raw_adjusted_mismatch_is_rejected(self) -> None:
        measurement = _measurement()
        measurement["multiplicity"][0]["adjusted_pvalue_ppm"] = 40_001
        with TemporaryDirectory() as root:
            request = _request(
                Path(root), plan=_plan(), measurement=measurement
            )

            with self.assertRaises(EvidenceValidationError):
                self._validate(request)

    def test_synchronized_familywise_method_uses_exact_family_and_raw_pair(
        self,
    ) -> None:
        plan = deepcopy(_plan())
        measurement = _measurement()
        for registration in plan["adjudication_profile"]["multiplicity"]:
            registration["method"] = SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD
            registration["family_registration_hash"] = (
                multiplicity_family_registration_hash(
                    family_id=registration["family_id"],
                    alpha_ppm=registration["alpha_ppm"],
                    method=SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD,
                    ordered_member_ids=tuple(
                        registration["ordered_member_ids"]
                    ),
                )
            )
        for result in measurement["multiplicity"]:
            result["method"] = SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD
            result["family_registration_hash"] = (
                multiplicity_family_registration_hash(
                    family_id=result["family_id"],
                    alpha_ppm=result["alpha_ppm"],
                    method=SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD,
                    ordered_member_ids=tuple(result["ordered_member_ids"]),
                )
            )
        measurement["metrics"]["selection_control"][
            "primary_control_raw_pvalue_ppm"
        ] = 60_000
        measurement["metrics"]["selection_control"][
            "selection_raw_pvalue_ppm"
        ] = 40_000
        with TemporaryDirectory() as root:
            request = _request(
                Path(root),
                plan=plan,
                measurement=measurement,
            )
            validated = self._validate(request)
        multiplicity = validated.facts["scientific_adjudication"][
            "multiplicity"
        ]
        self.assertEqual(
            {item["method"] for item in multiplicity},
            {SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD},
        )
        self.assertEqual(
            {(item["raw_pvalue_ppm"], item["adjusted_pvalue_ppm"])
             for item in multiplicity},
            {(20_000, 40_000), (30_000, 60_000)},
        )

    def test_exact_schema_rejects_project_history_input(self) -> None:
        plan = deepcopy(_plan())
        plan["adjudication_profile"]["multiplicity"][0][
            "project_total_exposures"
        ] = 595
        with TemporaryDirectory() as root:
            request = _request(
                Path(root), plan=plan, measurement=_measurement()
            )

            with self.assertRaises(EvidenceValidationError):
                self._validate(request)

    def test_validated_facts_preserve_exact_multiplicity_registrations(
        self,
    ) -> None:
        plan = _plan()
        with TemporaryDirectory() as root:
            validated = self._validate(
                _request(Path(root), plan=plan, measurement=_measurement())
            )

        self.assertEqual(
            validated.facts["multiplicity_registrations"],
            plan["adjudication_profile"]["multiplicity"],
        )
        registrations = validated.facts["multiplicity_registrations"]
        self.assertEqual(
            [item["criterion_id"] for item in registrations],
            sorted(item["criterion_id"] for item in registrations),
        )
        self.assertEqual(
            {item["family_registration_hash"] for item in registrations},
            {FAMILY_HASH},
        )
        self.assertEqual(
            {tuple(item["ordered_member_ids"]) for item in registrations},
            {FAMILY_MEMBERS},
        )

    def test_prospective_family_registration_is_exact_and_subject_bound(self) -> None:
        incomplete = deepcopy(_plan())
        incomplete["adjudication_profile"]["multiplicity"].pop()
        with self.assertRaisesRegex(
            EvidenceValidationError, "profile differs from its criteria"
        ):
            build_validation_plan_v2(
                mission_id=MISSION_ID,
                executable_id=EXECUTABLE_ID,
                evidence_depth="discovery",
                planned_claims=CLAIMS,
                evidence_modes=MODES,
                criteria=tuple(incomplete["criteria"]),
                adjudication_profile=incomplete["adjudication_profile"],
                proof_requirements=tuple(incomplete["proof_requirements"]),
            )

        drifted = deepcopy(_plan())
        drifted["adjudication_profile"]["multiplicity"][0][
            "ordered_member_ids"
        ].reverse()
        with self.assertRaisesRegex(
            EvidenceValidationError, "registration hash is invalid"
        ):
            build_validation_plan_v2(
                mission_id=MISSION_ID,
                executable_id=EXECUTABLE_ID,
                evidence_depth="discovery",
                planned_claims=CLAIMS,
                evidence_modes=MODES,
                criteria=tuple(drifted["criteria"]),
                adjudication_profile=drifted["adjudication_profile"],
                proof_requirements=tuple(drifted["proof_requirements"]),
            )

        missing_result = _measurement()
        missing_result["multiplicity"].pop()
        with TemporaryDirectory() as root:
            request = _request(
                Path(root), plan=_plan(), measurement=missing_result
            )
            with self.assertRaisesRegex(
                EvidenceValidationError, "incomplete or unordered"
            ):
                self._validate(request)

    def test_confirmation_requires_policy_and_all_promotion_gates(self) -> None:
        with TemporaryDirectory() as root:
            passing = _request(
                Path(root),
                plan=_plan(
                    evidence_depth="confirmation",
                    candidate_eligible_on_pass=True,
                ),
                measurement=_measurement(evidence_depth="confirmation"),
            )
            validated = self._validate(passing)
        self.assertEqual(validated.verdict, "passed")
        self.assertTrue(validated.candidate_eligible)

        failed_measurement = _measurement(evidence_depth="confirmation")
        failed_measurement["metrics"]["economic_edge"][
            "net_profit_micropoints"
        ] = 0
        with TemporaryDirectory() as root:
            failed = _request(
                Path(root),
                plan=_plan(
                    evidence_depth="confirmation",
                    candidate_eligible_on_pass=True,
                ),
                measurement=failed_measurement,
            )
            rejected = self._validate(failed)
        self.assertEqual(rejected.verdict, "not_evaluable")
        self.assertFalse(rejected.candidate_eligible)

        with TemporaryDirectory() as root:
            no_policy = _request(
                Path(root),
                plan=_plan(evidence_depth="confirmation"),
                measurement=_measurement(evidence_depth="confirmation"),
            )
            not_promoted = self._validate(no_policy)
        self.assertEqual(not_promoted.verdict, "passed")
        self.assertFalse(not_promoted.candidate_eligible)

    def test_only_exact_component_contradiction_projects_to_failed(self) -> None:
        measurement = _measurement()
        measurement["metrics"]["economic_edge"]["net_profit_micropoints"] = 0
        measurement["metrics"]["selection_control"][
            "selection_raw_pvalue_ppm"
        ] = 100_000
        measurement["multiplicity"][1]["raw_pvalue_ppm"] = 100_000
        measurement["multiplicity"][1]["adjusted_pvalue_ppm"] = 200_000
        with TemporaryDirectory() as root:
            request = _request(
                Path(root), plan=_plan(), measurement=measurement
            )

            validated = self._validate(request)

        self.assertEqual(validated.verdict, "failed")
        self.assertFalse(validated.candidate_eligible)

    def test_discovery_candidate_policy_is_rejected_at_plan_boundary(self) -> None:
        with self.assertRaises(EvidenceValidationError):
            _plan(candidate_eligible_on_pass=True)


if __name__ == "__main__":
    unittest.main()
