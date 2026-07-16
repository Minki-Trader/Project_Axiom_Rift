from __future__ import annotations

from copy import deepcopy
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
from axiom_rift.research.adjudication import scientific_adjudication_manifest
from axiom_rift.research.analog_state_replay import (
    build_analog_replay_measurement,
    build_analog_replay_plan,
    build_analog_replay_result,
)
from axiom_rift.research.analog_state_trace import (
    build_analog_trace_calculation,
    expected_analog_family_inventory,
)
from axiom_rift.research.validation import (
    SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
    ScientificDiscoveryValidator,
)
from axiom_rift.research.scientific_trace import (
    ANALOG_STATE_TRACE_PROTOCOL_ID,
    SCIENTIFIC_TRACE_PROTOCOL_IDS,
    scientific_trace_validation_dependency_paths,
)
from axiom_rift.research.evidence_proofs import (
    ATOMIC_TRACE_PROOF_KIND,
    AUDIT_INTEGRITY_MODE,
    AUDIT_STATISTICAL_PROOF_KIND,
    AUDIT_SUPPORT_PROOF_KIND,
    CALCULATION_PROOF_KIND,
    COST_EXECUTION_PROOF_KIND,
    PAIRED_CONTROL_PROOF_KIND,
    ProofRequirement,
    SCIENTIFIC_MODE_PROOF_SCHEMA,
    SENSITIVITY_STRESS_PROOF_KIND,
    TEMPORAL_STABILITY_PROOF_KIND,
    TERMINAL_EVIDENCE_MODES,
    ScientificEvidenceProofError,
    build_mode_proof,
    build_proof_references,
    parse_proof_requirements,
    proof_requirements_for_modes,
    validate_proof_artifacts,
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
    adjudicate_validation_measurement_v2,
    build_validation_plan_v2,
    multiplicity_family_registration_hash,
)
from tests.research.test_analog_state_trace import (
    MISSION_ID as ATOMIC_MISSION_ID,
    STUDY_ID as ATOMIC_STUDY_ID,
    _synthetic_trace,
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
    ATOMIC_TRACE_PROOF_KIND: "proofs/evaluation-trace.json",
    CALCULATION_PROOF_KIND: "proofs/calculation.json",
}
LEGACY_SUMMARY_OUTPUTS = {
    PAIRED_CONTROL_PROOF_KIND: "proofs/causal-contrast.json",
    COST_EXECUTION_PROOF_KIND: "proofs/cost-execution.json",
    SENSITIVITY_STRESS_PROOF_KIND: "proofs/sensitivity-stress.json",
    TEMPORAL_STABILITY_PROOF_KIND: "proofs/temporal-stability.json",
}
LEGACY_SUMMARY_KINDS_BY_MODE = {
    "causal_contrast": PAIRED_CONTROL_PROOF_KIND,
    "cost_and_execution": COST_EXECUTION_PROOF_KIND,
    "sensitivity_or_stress": SENSITIVITY_STRESS_PROOF_KIND,
    "temporal_stability": TEMPORAL_STABILITY_PROOF_KIND,
}


def _legacy_summary_requirements(
    evidence_modes: tuple[str, ...] = MODES,
) -> tuple[dict[str, str], ...]:
    return tuple(
        sorted(
            (
                {
                    "artifact_schema": SCIENTIFIC_MODE_PROOF_SCHEMA,
                    "evidence_mode": mode,
                    "output_name": LEGACY_SUMMARY_OUTPUTS[kind],
                    "proof_kind": kind,
                }
                for mode in evidence_modes
                for kind in (LEGACY_SUMMARY_KINDS_BY_MODE[mode],)
            ),
            key=lambda item: (
                item["evidence_mode"],
                item["proof_kind"],
                item["output_name"],
            ),
        )
    )


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
            proof_protocol_id=ANALOG_STATE_TRACE_PROTOCOL_ID,
        ),
        candidate_eligible_on_pass=candidate_eligible_on_pass,
    )


def _measurement(*, evidence_depth: str = "discovery") -> dict[str, object]:
    requirements = parse_proof_requirements(
        proof_requirements_for_modes(
            evidence_modes=MODES,
            output_names=PROOF_OUTPUTS,
            proof_protocol_id=ANALOG_STATE_TRACE_PROTOCOL_ID,
        ),
        evidence_modes=MODES,
    )
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
        "proofs": list(
            build_proof_references(
                requirements=requirements,
                artifact_hashes={
                    output_name: sha256(output_name.encode("ascii")).hexdigest()
                    for output_name in PROOF_OUTPUTS.values()
                },
            )
        ),
        "schema": SCIENTIFIC_MEASUREMENT_V2_SCHEMA,
    }


def _request(
    root: Path,
    *,
    plan: dict[str, object],
    measurement: dict[str, object],
) -> EvidenceValidationRequest:
    measurement = deepcopy(measurement)
    requirements = tuple(
        ProofRequirement(
            artifact_schema=item["artifact_schema"],
            evidence_mode=item["evidence_mode"],
            output_name=item["output_name"],
            proof_kind=item["proof_kind"],
        )
        for item in plan["proof_requirements"]
    )
    proof_payloads = {
        requirement.output_name: canonical_bytes(
            {"schema": requirement.artifact_schema}
        )
        for requirement in requirements
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


def _atomic_request(root: Path) -> EvidenceValidationRequest:
    executable_id = str(expected_analog_family_inventory()[0]["executable_id"])
    replay_plan = build_analog_replay_plan(
        mission_id=ATOMIC_MISSION_ID,
        study_id=ATOMIC_STUDY_ID,
        executable_id=executable_id,
    )
    trace = _synthetic_trace(executable_id)
    trace_content = canonical_bytes(trace)
    trace_hash = sha256(trace_content).hexdigest()
    calculation = build_analog_trace_calculation(
        trace=trace,
        trace_output_name=replay_plan.output_names["trace"],
        trace_hash=trace_hash,
    )
    calculation_content = canonical_bytes(calculation)
    calculation_hash = sha256(calculation_content).hexdigest()
    measurement = build_analog_replay_measurement(
        replay_plan=replay_plan,
        job_id=JOB_ID,
        job_hash=JOB_HASH,
        calculation=calculation,
        trace_hash=trace_hash,
        calculation_hash=calculation_hash,
    )
    measurement_content = canonical_bytes(measurement)
    result = build_analog_replay_result(
        replay_plan=replay_plan,
        job_id=JOB_ID,
        job_hash=JOB_HASH,
        measurement_hash=sha256(measurement_content).hexdigest(),
    )
    payloads = {
        replay_plan.output_names["calculation"]: calculation_content,
        replay_plan.output_names["measurement"]: measurement_content,
        replay_plan.output_names["plan"]: canonical_bytes(replay_plan.plan),
        replay_plan.output_names["result"]: canonical_bytes(result),
        replay_plan.output_names["trace"]: trace_content,
    }
    artifacts = []
    for index, (output_name, content) in enumerate(payloads.items()):
        path = root / f"atomic-artifact-{index}.json"
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
        validation_plan_hash=replay_plan.plan_hash,
        job_id=JOB_ID,
        job_hash=JOB_HASH,
        mission_id=ATOMIC_MISSION_ID,
        evidence_subject={"kind": "Executable", "id": executable_id},
        binding=replay_plan.scientific_binding(),
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

    def test_registered_atomic_trace_passes_the_full_validator(self) -> None:
        with TemporaryDirectory() as root:
            request = _atomic_request(Path(root))
            validated = self._validate(request)

        self.assertEqual(
            validated.facts["executed_evidence_modes"],
            [
                "causal_contrast",
                "cost_and_execution",
                "sensitivity_or_stress",
                "temporal_stability",
            ],
        )
        self.assertTrue(all(artifact.was_read for artifact in request.artifacts))

    def test_discovery_adjudication_keeps_b04_diagnostic_non_candidate(
        self,
    ) -> None:
        plan = _plan()
        adjudication = adjudicate_validation_measurement_v2(
            plan,
            _measurement(),
        )
        manifest = scientific_adjudication_manifest(adjudication)

        self.assertEqual(manifest["schema"], "scientific_adjudication.v1")
        self.assertEqual(manifest["state"], "frontier")
        self.assertEqual(manifest["evidence_depth"], "discovery")
        self.assertFalse(manifest["candidate_eligible"])
        self.assertEqual(
            manifest["multiplicity"][0]["family_id"],
            "family:two-concurrent-hypotheses",
        )
        self.assertIn(
            "risk_diagnostic",
            {item["decision_role"] for item in manifest["criteria"]},
        )

    def test_terminal_modes_require_a_registered_atomic_protocol(self) -> None:
        for mode in sorted(TERMINAL_EVIDENCE_MODES):
            with self.subTest(mode=mode), self.assertRaisesRegex(
                ScientificEvidenceProofError,
                "requires a registered atomic trace protocol",
            ):
                proof_requirements_for_modes(
                    evidence_modes=(mode,),
                    output_names={},
                )

    def test_terminal_summary_requirements_are_rejected_by_plan_parser(
        self,
    ) -> None:
        for mode in sorted(TERMINAL_EVIDENCE_MODES):
            with self.subTest(mode=mode), self.assertRaisesRegex(
                ScientificEvidenceProofError,
                "proof kind is invalid",
            ):
                parse_proof_requirements(
                    _legacy_summary_requirements((mode,)),
                    evidence_modes=(mode,),
                )

    def test_proof_validator_independently_rejects_terminal_summary_kind(
        self,
    ) -> None:
        summary = ProofRequirement(
            artifact_schema=SCIENTIFIC_MODE_PROOF_SCHEMA,
            evidence_mode="causal_contrast",
            output_name=LEGACY_SUMMARY_OUTPUTS[PAIRED_CONTROL_PROOF_KIND],
            proof_kind=PAIRED_CONTROL_PROOF_KIND,
        )
        with self.assertRaisesRegex(
            ScientificEvidenceProofError,
            "requires an atomic trace and calculation proof",
        ):
            validate_proof_artifacts(
                requirements=(summary,),
                references=(),
                artifacts={},
                artifact_hashes={},
                expected_metric_bindings_by_mode={},
                mission_id=MISSION_ID,
                executable_id=EXECUTABLE_ID,
                job_id=JOB_ID,
                job_hash=JOB_HASH,
            )

    def test_full_validator_rejects_a_raw_legacy_summary_plan(self) -> None:
        plan = deepcopy(_plan())
        plan["proof_requirements"] = list(_legacy_summary_requirements())
        with TemporaryDirectory() as root:
            request = _request(
                Path(root), plan=plan, measurement=_measurement()
            )
            with self.assertRaisesRegex(
                EvidenceValidationError,
                "proof requirements are invalid",
            ):
                self._validate(request)

    def test_audit_default_and_registered_atomic_protocols_remain_valid(
        self,
    ) -> None:
        audit = proof_requirements_for_modes(
            evidence_modes=(AUDIT_INTEGRITY_MODE,),
            output_names={
                AUDIT_SUPPORT_PROOF_KIND: "proofs/audit-support.json",
                AUDIT_STATISTICAL_PROOF_KIND: "proofs/audit-statistical.json",
            },
        )
        parsed_audit = parse_proof_requirements(
            audit,
            evidence_modes=(AUDIT_INTEGRITY_MODE,),
        )
        self.assertEqual(
            {item.proof_kind for item in parsed_audit},
            {AUDIT_SUPPORT_PROOF_KIND, AUDIT_STATISTICAL_PROOF_KIND},
        )

        atomic = proof_requirements_for_modes(
            evidence_modes=MODES,
            output_names=PROOF_OUTPUTS,
            proof_protocol_id=ANALOG_STATE_TRACE_PROTOCOL_ID,
        )
        parsed_atomic = parse_proof_requirements(
            atomic,
            evidence_modes=MODES,
        )
        self.assertEqual(
            {item.proof_kind for item in parsed_atomic},
            {ATOMIC_TRACE_PROOF_KIND, CALCULATION_PROOF_KIND},
        )

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
        adjudication = adjudicate_validation_measurement_v2(
            _plan(b04_decisive=True),
            _measurement(),
        )
        self.assertNotIn(adjudication.state, {"frontier", "confirmed"})
        self.assertFalse(adjudication.candidate_eligible)

    def test_validity_failure_is_not_evaluable(self) -> None:
        measurement = _measurement()
        measurement["metrics"]["causal_validity"]["nonfinite_metric_count"] = 1
        adjudication = adjudicate_validation_measurement_v2(
            _plan(),
            measurement,
        )
        self.assertEqual(adjudication.state, "not_evaluable")
        self.assertFalse(adjudication.candidate_eligible)

    def test_raw_adjusted_mismatch_is_rejected(self) -> None:
        measurement = _measurement()
        measurement["multiplicity"][0]["adjusted_pvalue_ppm"] = 40_001
        with self.assertRaises(EvidenceValidationError):
            adjudicate_validation_measurement_v2(_plan(), measurement)

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
        adjudication = adjudicate_validation_measurement_v2(
            plan,
            measurement,
        )
        multiplicity = scientific_adjudication_manifest(adjudication)[
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
        with self.assertRaises(EvidenceValidationError):
            adjudicate_validation_measurement_v2(plan, _measurement())

    def test_adjudication_preserves_exact_multiplicity_registrations(
        self,
    ) -> None:
        plan = _plan()
        adjudication = adjudicate_validation_measurement_v2(
            plan,
            _measurement(),
        )
        registrations = plan["adjudication_profile"]["multiplicity"]
        self.assertEqual(
            [item.criterion_id for item in adjudication.multiplicity],
            [item["criterion_id"] for item in registrations],
        )
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
        with self.assertRaisesRegex(
            EvidenceValidationError, "incomplete or unordered"
        ):
            adjudicate_validation_measurement_v2(_plan(), missing_result)

    def test_confirmation_requires_policy_and_all_promotion_gates(self) -> None:
        passing = adjudicate_validation_measurement_v2(
            _plan(
                evidence_depth="confirmation",
                candidate_eligible_on_pass=True,
            ),
            _measurement(evidence_depth="confirmation"),
        )
        self.assertEqual(passing.state, "confirmed")
        self.assertTrue(passing.candidate_eligible)

        failed_measurement = _measurement(evidence_depth="confirmation")
        failed_measurement["metrics"]["economic_edge"][
            "net_profit_micropoints"
        ] = 0
        rejected = adjudicate_validation_measurement_v2(
            _plan(
                evidence_depth="confirmation",
                candidate_eligible_on_pass=True,
            ),
            failed_measurement,
        )
        self.assertNotEqual(rejected.state, "confirmed")
        self.assertFalse(rejected.candidate_eligible)

        not_promoted = adjudicate_validation_measurement_v2(
            _plan(evidence_depth="confirmation"),
            _measurement(evidence_depth="confirmation"),
        )
        self.assertEqual(not_promoted.state, "confirmed")
        self.assertFalse(not_promoted.candidate_eligible)

    def test_only_exact_component_contradiction_projects_to_failed(self) -> None:
        measurement = _measurement()
        measurement["metrics"]["economic_edge"]["net_profit_micropoints"] = 0
        measurement["metrics"]["selection_control"][
            "selection_raw_pvalue_ppm"
        ] = 100_000
        measurement["multiplicity"][1]["raw_pvalue_ppm"] = 100_000
        measurement["multiplicity"][1]["adjusted_pvalue_ppm"] = 200_000
        adjudication = adjudicate_validation_measurement_v2(
            _plan(),
            measurement,
        )
        self.assertEqual(adjudication.state, "contradicted")
        self.assertFalse(adjudication.candidate_eligible)

    def test_discovery_candidate_policy_is_rejected_at_plan_boundary(self) -> None:
        with self.assertRaises(EvidenceValidationError):
            _plan(candidate_eligible_on_pass=True)


if __name__ == "__main__":
    unittest.main()
