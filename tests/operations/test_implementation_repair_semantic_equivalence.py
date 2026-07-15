from __future__ import annotations

from tempfile import TemporaryDirectory
import unittest

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.permits import (
    PermitAuthority,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.repair_semantic_equivalence import (
    IMPLEMENTATION_REPAIR_V2_SCHEMA,
    ImplementationRepairSemanticEquivalenceValidator,
    RepairSemanticEquivalenceError,
    SEMANTIC_EQUIVALENCE_VALIDATOR_ID,
    build_semantic_equivalence_binding,
    build_semantic_equivalence_plan,
    semantic_equivalence_measurement,
    semantic_equivalence_result_manifest,
)
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    EvidenceValidatorRegistry,
    ValidationArtifact,
)
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.research.analog_fixed_hold_replay_job import RUNTIME_ADAPTER
from axiom_rift.research.chassis import ControlledStudyChassis
from axiom_rift.research.fixed_hold_replay_runtime import (
    fixed_hold_replay_job_implementation_artifact,
    fixed_hold_replay_runtime_dependency_paths,
)
from axiom_rift.research.portfolio import (
    DecisionOption,
    PortfolioAction,
    PortfolioDecision,
    PortfolioSnapshot,
)
from axiom_rift.storage.index import LocalIndex
from tests.operations.test_writer import (
    FIXED_EXPIRY,
    FIXED_NOW,
    FIXTURE_DELIVERY_CAPABILITY,
    OBSERVED_MATERIAL_ID,
    PortfolioAxis,
    REPO_ROOT,
    batch_spec,
    changed_domain_executable,
    engineering_failure_disposition,
    exhaustion_standard,
    initiative_objective,
    job_implementation_identity,
    job_spec,
    mission_goal,
    portfolio_axis_baseline,
    quant_team_review_for_current_action,
    record_fixture_research_intake,
    repair_attempt_proof,
    study_question,
)


class ImplementationRepairSemanticEquivalenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.validator = ImplementationRepairSemanticEquivalenceValidator()
        self.writer = StateWriter(
            self.temporary.name,
            permit_authority=PermitAuthority(b"e" * 32),
            clock=lambda: FIXED_NOW,
            study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
            foundation_root=REPO_ROOT,
            validation_registry=EvidenceValidatorRegistry((self.validator,)),
        )
        self.writer.initialize_ready()
        self.writer.open_mission(
            mission_id="MIS-REPAIR-EQUIVALENCE",
            goal=mission_goal("implementation Repair equivalence"),
            operation_id="repair-equivalence-mission",
        )
        intake = record_fixture_research_intake(
            self.writer,
            mission_id="MIS-REPAIR-EQUIVALENCE",
            operation_id="repair-equivalence-intake",
        )
        self.writer.open_initiative(
            initiative_id="INI-REPAIR-EQUIVALENCE",
            objective=initiative_objective(
                "implementation Repair equivalence"
            ),
            operation_id="repair-equivalence-initiative",
        )
        self.axes = tuple(
            PortfolioAxis(
                axis_id=f"repair-equivalence-axis-{letter}",
                causal_question=(
                    f"Does Repair equivalence axis {letter} isolate meaning?"
                ),
                mechanism_family=f"repair-equivalence-family-{letter}",
            )
            for letter in ("a", "b", "c")
        )
        self.snapshot = PortfolioSnapshot(
            mission_id="MIS-REPAIR-EQUIVALENCE",
            axes=self.axes,
            opportunity_cost_basis="preserve three independent mechanisms",
            research_intake_id=intake.identity,
            exhaustion_standard=exhaustion_standard(),
        )
        self.writer.record_portfolio_snapshot(
            snapshot=self.snapshot,
            operation_id="repair-equivalence-snapshot",
        )
        chosen_id = "repair-equivalence-chosen"
        options = (
            DecisionOption(
                option_id=chosen_id,
                action=PortfolioAction.DEEPEN,
                target_id=self.axes[0].axis_id,
                expected_information_value="positive",
                opportunity_cost="one bounded Batch",
            ),
            DecisionOption(
                option_id="repair-equivalence-alternative",
                action=PortfolioAction.ROTATE,
                target_id=self.axes[1].axis_id,
                expected_information_value="positive",
                opportunity_cost="deferred",
                omission_reason="retain as the next forest branch",
            ),
        )
        decision = PortfolioDecision(
            decision_id="DEC-REPAIR-EQUIVALENCE",
            chosen_option_id=chosen_id,
            options=options,
            rationale="test one bounded implementation equivalence boundary",
            commitment_batches=1,
            quant_team_review=quant_team_review_for_current_action(
                self.writer,
                options=options,
                chosen_option_id=chosen_id,
            ),
            baseline_executable=portfolio_axis_baseline(self.axes[0]),
        )
        self.writer.record_portfolio_decision(
            decision=decision,
            operation_id="repair-equivalence-decision",
        )
        axis = self.axes[0]
        assert decision.baseline_executable is not None
        assert decision.architecture_chassis is not None
        controlled_chassis = ControlledStudyChassis(
            baseline_executable=decision.baseline_executable,
            changed_domains=axis.changed_domains,
            controlled_domains=axis.controlled_domains,
            architecture=decision.architecture_chassis,
        )
        question = study_question("implementation Repair equivalence")
        proposal = {"mechanism": "registered semantic equivalence"}
        study_hash = self.writer.study_input_hash(
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            semantic_proposal=proposal,
            controlled_chassis=controlled_chassis,
            portfolio_axis_id=axis.axis_id,
            portfolio_axis_identity=axis.identity,
            portfolio_decision_id=decision.identity,
        )
        study_permit = self.writer.issue_permit(
            kind=PermitKind.STUDY,
            subject_kind=SubjectKind.INITIATIVE,
            subject_id="INI-REPAIR-EQUIVALENCE",
            input_hash=study_hash,
            actions=("open_study",),
            scope=(
                "study",
                f"decision:{decision.identity}",
                f"axis:{axis.identity}",
                f"baseline:{decision.baseline_executable.identity}",
                f"chassis:{decision.architecture_chassis.identity}",
                f"snapshot:{self.snapshot.identity}",
            ),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="repair-equivalence-study-permit",
        )
        opened = self.writer.open_study(
            study_id="STU-REPAIR-EQUIVALENCE",
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            material_display_name="foundation observed material",
            semantic_proposal=proposal,
            controlled_chassis=controlled_chassis,
            portfolio_axis_id=axis.axis_id,
            portfolio_axis_identity=axis.identity,
            portfolio_decision_id=decision.identity,
            permit=study_permit,
            operation_id="repair-equivalence-study-open",
        )
        batch = batch_spec(
            batch_id="BAT-REPAIR-EQUIVALENCE",
            study_id="STU-REPAIR-EQUIVALENCE",
            study_hash=opened.result["study_hash"],
        )
        batch_permit = self.writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-REPAIR-EQUIVALENCE",
            input_hash=batch.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="repair-equivalence-batch-permit",
        )
        self.writer.open_batch(
            batch_spec=batch,
            permit=batch_permit,
            operation_id="repair-equivalence-batch-open",
        )
        self.executable = changed_domain_executable(
            decision.baseline_executable,
            domain="calibration",
            change_tag="repair-equivalence",
        )
        self.writer.register_trial(
            executable=self.executable,
            operation_id="repair-equivalence-trial",
        )
        self.spec = job_spec(
            self.writer,
            {"kind": "Executable", "id": self.executable.identity},
        )
        self.component_hashes = tuple(
            sorted(
                component.implementation.rsplit("@sha256:", 1)[1]
                for component in self.executable.components
            )
        )
        declared = self.writer.declare_job(
            spec=self.spec,
            operation_id="repair-equivalence-job-declare",
        )
        self.job_id = declared.result["job_id"]
        self.job_hash = declared.result["job_hash"]
        start_permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=self.job_id,
            input_hash=self.job_hash,
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="repair-equivalence-job-permit",
        )
        repair_permit = self.writer.issue_permit(
            kind=PermitKind.REPAIR,
            subject_kind=SubjectKind.JOB,
            subject_id=self.job_id,
            input_hash=self.job_hash,
            actions=("open_repair",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="repair-equivalence-repair-permit",
        )
        started = self.writer.start_job(
            permit=start_permit,
            operation_id="repair-equivalence-job-start",
        )
        self.execution = RunningJobExecution.from_mapping(
            started.result["execution"]
        )
        self.reproduction = self.writer.evidence.finalize(
            b"production implementation defect reproduction"
        )
        opened_repair = self.writer.open_repair(
            permit=repair_permit,
            failure={
                "failure_kind": "engineering",
                "minimum_reproduction_evidence": [self.reproduction.sha256],
                "root_cause": "implementation branch defect",
                "interrupted_action": self.spec["callable_identity"],
            },
            operation_id="repair-equivalence-repair-open",
        )
        self.repair_id = opened_repair.result["repair_id"]
        self.new_implementation_identity = (
            self._comment_only_implementation_identity()
        )
        new_manifest = parse_canonical(
            self.writer.evidence.read_verified(
                self.new_implementation_identity
            )
        )
        assert isinstance(new_manifest, dict)
        self.new_implementation_artifact_hashes = tuple(
            new_manifest["artifact_hashes"]
        )

    def _semantic_change_implementation_identity(self) -> str:
        manifest, closure = self._source_closure_for_implementation(
            str(self.spec["implementation_identity"])
        )
        dependencies = [dict(item) for item in closure["dependencies"]]
        source = dependencies[0]
        changed_source = self.writer.evidence.finalize(
            self.writer.evidence.read_verified(source["sha256"])
            + b"\nSEMANTIC_EQUIVALENCE_BEHAVIOR_CHANGE = 1\n"
        )
        source["sha256"] = changed_source.sha256
        return self._implementation_from_dependencies(
            manifest=manifest,
            dependencies=dependencies,
        )

    def _source_closure_for_implementation(
        self, implementation_identity: str
    ) -> tuple[dict[str, object], dict[str, object]]:
        manifest = parse_canonical(
            self.writer.evidence.read_verified(implementation_identity)
        )
        assert isinstance(manifest, dict)
        closures: list[dict[str, object]] = []
        for identity in manifest["artifact_hashes"]:
            try:
                candidate = parse_canonical(
                    self.writer.evidence.read_verified(identity)
                )
            except ValueError:
                continue
            if (
                isinstance(candidate, dict)
                and candidate.get("schema")
                == "job_implementation_source_closure.v1"
            ):
                closures.append(candidate)
        self.assertEqual(len(closures), 1)
        return manifest, closures[0]

    def _comment_only_implementation_identity(self) -> str:
        manifest, closure = self._source_closure_for_implementation(
            str(self.spec["implementation_identity"])
        )
        dependencies = [dict(item) for item in closure["dependencies"]]
        source = dependencies[0]
        changed_source = self.writer.evidence.finalize(
            self.writer.evidence.read_verified(source["sha256"])
            + b"\n# implementation Repair comment-only change\n"
        )
        source["sha256"] = changed_source.sha256
        return self._implementation_from_dependencies(
            manifest=manifest,
            dependencies=dependencies,
        )

    def _implementation_from_dependencies(
        self,
        *,
        manifest: dict[str, object],
        dependencies: list[dict[str, str]],
    ) -> str:
        prior_source_artifacts: set[str] | None = None
        for identity in manifest["artifact_hashes"]:
            try:
                candidate = parse_canonical(
                    self.writer.evidence.read_verified(identity)
                )
            except ValueError:
                continue
            if (
                isinstance(candidate, dict)
                and candidate.get("schema")
                == "job_implementation_source_closure.v1"
            ):
                self.assertIsNone(prior_source_artifacts)
                prior_source_artifacts = {
                    identity,
                    *(item["sha256"] for item in candidate["dependencies"]),
                }
        self.assertIsNotNone(prior_source_artifacts)
        preserved_non_source = set(manifest["artifact_hashes"]).difference(
            prior_source_artifacts
        )
        closure = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "callable_identity": manifest["callable_identity"],
                    "dependencies": sorted(
                        dependencies, key=lambda item: item["path"]
                    ),
                    "schema": "job_implementation_source_closure.v1",
                }
            )
        )
        implementation = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "artifact_hashes": sorted(
                        {
                            closure.sha256,
                            *(item["sha256"] for item in dependencies),
                            *preserved_non_source,
                        }
                    ),
                    "callable_identity": manifest["callable_identity"],
                    "protocol": manifest["protocol"],
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        return implementation.sha256

    def _path_swapped_implementation_identity(
        self,
        implementation_identity: str | None = None,
    ) -> str:
        manifest, closure = self._source_closure_for_implementation(
            (
                str(self.spec["implementation_identity"])
                if implementation_identity is None
                else implementation_identity
            )
        )
        dependencies = [dict(item) for item in closure["dependencies"]]
        by_path = {item["path"]: item for item in dependencies}
        entry = by_path["tests/fixtures/job_entry.py"]
        helper = by_path["tests/fixtures/shared_helper.py"]
        entry["sha256"], helper["sha256"] = (
            helper["sha256"],
            entry["sha256"],
        )
        return self._implementation_from_dependencies(
            manifest=manifest,
            dependencies=dependencies,
        )

    def _synthetic_constant_only_pair(self) -> tuple[str, str]:
        old_source = self.writer.evidence.finalize(
            b"def fixture_job_entry(*args, **kwargs):\n"
            b"    return 'stable'\n"
        )
        new_source = self.writer.evidence.finalize(
            b"# comment-only implementation Repair\n"
            b"def fixture_job_entry(*args, **kwargs):\n"
            b"    return 'stable'\n"
        )
        shared_helper = self.writer.evidence.finalize(
            b"def fixture_helper():\n    return 'helper'\n"
        )

        def materialize(source_hash: str) -> str:
            dependencies = [
                {
                    "path": "tests/fixtures/job_entry.py",
                    "sha256": source_hash,
                },
                {
                    "path": "tests/fixtures/shared_helper.py",
                    "sha256": shared_helper.sha256,
                },
                {
                    "path": "tests/fixtures/shared_helper_alias.py",
                    "sha256": shared_helper.sha256,
                },
            ]
            closure = self.writer.evidence.finalize(
                canonical_bytes(
                    {
                        "callable_identity": "fixture.callable",
                        "dependencies": dependencies,
                        "schema": "job_implementation_source_closure.v1",
                    }
                )
            )
            implementation = self.writer.evidence.finalize(
                canonical_bytes(
                    {
                        "artifact_hashes": sorted(
                            {
                                closure.sha256,
                                source_hash,
                                shared_helper.sha256,
                                *self.component_hashes,
                            }
                        ),
                        "callable_identity": "fixture.callable",
                        "protocol": "python.source.fixture.v1",
                        "schema": "job_implementation_evidence.v1",
                    }
                )
            )
            return implementation.sha256

        return materialize(old_source.sha256), materialize(new_source.sha256)

    def _hash_set_only_implementation_identity(self) -> str:
        source = self.writer.evidence.finalize(
            b"# no typed source closure\n"
            b"def fixture_job_entry(*args, **kwargs):\n"
            b"    return 'fixture.callable'\n"
        )
        manifest = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "artifact_hashes": sorted(
                        {source.sha256, *self.component_hashes}
                    ),
                    "callable_identity": self.spec["callable_identity"],
                    "protocol": "python.source.fixture.v1",
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        return manifest.sha256

    def _packet(
        self,
        *,
        new_implementation_identity: str | None = None,
        missing_pair: bool = False,
        expected_verdict: str = "not_evaluable",
        forged_observations: bool = False,
    ) -> tuple[str, str, tuple[str, ...]]:
        implementation_identity = (
            self.new_implementation_identity
            if new_implementation_identity is None
            else new_implementation_identity
        )
        new_manifest = parse_canonical(
            self.writer.evidence.read_verified(implementation_identity)
        )
        assert isinstance(new_manifest, dict)
        new_artifact_hashes = tuple(new_manifest["artifact_hashes"])
        plan = self.writer.plan_implementation_repair_semantic_equivalence(
            new_implementation_identity=implementation_identity,
        )
        plan_artifact = self.writer.evidence.finalize(canonical_bytes(plan))
        pairs = list(plan["changed_source_pair_bindings"])
        self.assertTrue(pairs)
        if missing_pair:
            pairs = pairs[:-1]
        measurements: list[str] = []
        for pair in pairs:
            if forged_observations:
                measurement_payload = {
                    "comparison": "canonical_exact",
                    "new_observation": {"value": "stable"},
                    "old_observation": {"value": "stable"},
                    "schema": (
                        "implementation_repair_semantic_equivalence_"
                        "measurement.v1"
                    ),
                    "surface_id": plan["claims"][0],
                    "validation_plan_hash": plan_artifact.sha256,
                }
            else:
                measurement_payload = semantic_equivalence_measurement(
                    validation_plan_hash=plan_artifact.sha256,
                    relative_path=pair["relative_path"],
                    old_artifact_hash=pair["old_artifact_hash"],
                    new_artifact_hash=pair["new_artifact_hash"],
                )
            measurement = self.writer.evidence.finalize(
                canonical_bytes(measurement_payload)
            )
            measurements.append(measurement.sha256)
        measurement_hashes = tuple(sorted(measurements))
        verdict = "not_evaluable" if missing_pair else expected_verdict
        result = semantic_equivalence_result_manifest(
            plan=plan,
            validation_plan_hash=plan_artifact.sha256,
            measurement_artifact_hashes=measurement_hashes,
            surface_verdicts={
                surface_id: verdict for surface_id in plan["claims"]
            },
        )
        result_artifact = self.writer.evidence.finalize(
            canonical_bytes(result)
        )
        inner_evidence = tuple(
            sorted(
                {
                    implementation_identity,
                    *new_artifact_hashes,
                    plan_artifact.sha256,
                    result_artifact.sha256,
                    *measurement_hashes,
                }
            )
        )
        inner = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "changed_dimension": "implementation",
                    "explanation": "repair implementation without changing meaning",
                    "job_hash": self.job_hash,
                    "job_id": self.job_id,
                    "new_evidence_hashes": list(inner_evidence),
                    "new_implementation_identity": (
                        implementation_identity
                    ),
                    "previous_implementation_identity": self.spec[
                        "implementation_identity"
                    ],
                    "repair_id": self.repair_id,
                    "reproduction_evidence_hashes": [
                        self.reproduction.sha256
                    ],
                    "schema": IMPLEMENTATION_REPAIR_V2_SCHEMA,
                    "semantic_equivalence_measurement_artifact_hashes": list(
                        measurement_hashes
                    ),
                    "semantic_equivalence_result_manifest_hash": (
                        result_artifact.sha256
                    ),
                    "semantic_equivalence_validation_plan_hash": (
                        plan_artifact.sha256
                    ),
                    "semantic_equivalence_validator_id": (
                        SEMANTIC_EQUIVALENCE_VALIDATOR_ID
                    ),
                }
            )
        )
        verification = self.writer.evidence.finalize(
            b"independent semantic-equivalence verification receipt input"
        )
        outer_evidence = tuple(sorted({inner.sha256, *inner_evidence}))
        outer = repair_attempt_proof(
            self.writer,
            outcome="repaired",
            changed_dimension="implementation",
            new_basis_hash=implementation_identity,
            new_evidence_hashes=outer_evidence,
            verification_evidence_hashes=(verification.sha256,),
            implementation_proof_hash=inner.sha256,
        )
        return outer, inner.sha256, outer_evidence

    def _validate_direct_implementation_pair(
        self,
        *,
        old_implementation_identity: str,
        new_implementation_identity: str,
        expected_verdict: str,
    ):
        old_manifest = parse_canonical(
            self.writer.evidence.read_verified(old_implementation_identity)
        )
        new_manifest = parse_canonical(
            self.writer.evidence.read_verified(new_implementation_identity)
        )
        assert isinstance(old_manifest, dict)
        assert isinstance(new_manifest, dict)
        with LocalIndex(self.writer.index_path) as index:
            trial = index.get("trial", self.executable.identity)
        assert trial is not None
        plan = build_semantic_equivalence_plan(
            validator_id=SEMANTIC_EQUIVALENCE_VALIDATOR_ID,
            repair_id=self.repair_id,
            job_id=self.job_id,
            job_hash=self.job_hash,
            executable_id=self.executable.identity,
            job_spec={
                **self.spec,
                "callable_identity": old_manifest["callable_identity"],
            },
            executable_manifest=trial.payload["executable"],
            old_implementation_identity=old_implementation_identity,
            old_implementation_manifest=old_manifest,
            new_implementation_identity=new_implementation_identity,
            new_implementation_manifest=new_manifest,
            artifact_reader=self.writer.evidence.read_verified,
        )
        plan_artifact = self.writer.evidence.finalize(canonical_bytes(plan))
        measurement_hashes: list[str] = []
        for pair in plan["changed_source_pair_bindings"]:
            measurement = self.writer.evidence.finalize(
                canonical_bytes(
                    semantic_equivalence_measurement(
                        validation_plan_hash=plan_artifact.sha256,
                        relative_path=pair["relative_path"],
                        old_artifact_hash=pair["old_artifact_hash"],
                        new_artifact_hash=pair["new_artifact_hash"],
                    )
                )
            )
            measurement_hashes.append(measurement.sha256)
        measurements = tuple(sorted(measurement_hashes))
        result = semantic_equivalence_result_manifest(
            plan=plan,
            validation_plan_hash=plan_artifact.sha256,
            measurement_artifact_hashes=measurements,
            surface_verdicts={
                claim: expected_verdict for claim in plan["claims"]
            },
        )
        result_artifact = self.writer.evidence.finalize(
            canonical_bytes(result)
        )
        binding = build_semantic_equivalence_binding(
            plan=plan,
            validation_plan_hash=plan_artifact.sha256,
            result_manifest_hash=result_artifact.sha256,
            measurement_artifact_hashes=measurements,
        )
        artifacts: list[ValidationArtifact] = []
        for ordinal, identity in enumerate(
            binding["declared_artifact_hashes"]
        ):
            artifact = self.writer.evidence.verify(identity)
            artifacts.append(
                ValidationArtifact(
                    output_name=f"direct-semantic-{ordinal:04d}",
                    sha256=identity,
                    _source=(
                        self.writer.evidence._root / artifact.relative_path
                    ),
                )
            )
        return self.validator.validate(
            EvidenceValidationRequest(
                domain="scientific",
                validator_id=SEMANTIC_EQUIVALENCE_VALIDATOR_ID,
                validation_plan_hash=plan_artifact.sha256,
                job_id=self.job_id,
                job_hash=self.job_hash,
                mission_id="MIS-REPAIR-EQUIVALENCE",
                evidence_subject={
                    "kind": "Executable",
                    "id": self.executable.identity,
                },
                binding=binding,
                result_manifest=result,
                artifacts=tuple(artifacts),
                engineering_fixture=False,
            )
        )

    def _legacy_false_packet(self) -> str:
        inner_evidence = tuple(
            sorted(
                {
                    self.new_implementation_identity,
                    *self.new_implementation_artifact_hashes,
                }
            )
        )
        inner = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "changed_dimension": "implementation",
                    "explanation": "claim unchanged meaning without proof",
                    "job_hash": self.job_hash,
                    "job_id": self.job_id,
                    "new_evidence_hashes": list(inner_evidence),
                    "new_implementation_identity": (
                        self.new_implementation_identity
                    ),
                    "previous_implementation_identity": self.spec[
                        "implementation_identity"
                    ],
                    "repair_id": self.repair_id,
                    "reproduction_evidence_hashes": [
                        self.reproduction.sha256
                    ],
                    "schema": "running_job_implementation_repair.v1",
                }
            )
        )
        verification = self.writer.evidence.finalize(
            b"legacy self-authored false verification"
        )
        return repair_attempt_proof(
            self.writer,
            outcome="repaired",
            changed_dimension="implementation",
            new_basis_hash=self.new_implementation_identity,
            new_evidence_hashes=tuple(
                sorted({inner.sha256, *inner_evidence})
            ),
            verification_evidence_hashes=(verification.sha256,),
            implementation_proof_hash=inner.sha256,
        )

    def test_false_unchanged_declaration_cannot_close_production_repair(self) -> None:
        proof = self._legacy_false_packet()
        with self.assertRaisesRegex(
            TransitionError, "requires_scientific_change"
        ):
            self.writer.close_repair(
                changed_cause_proof_hash=proof,
                operation_id="reject-self-authored-false",
            )

    def test_missing_pair_or_changed_ast_cannot_close(self) -> None:
        partial, _inner, _evidence = self._packet(missing_pair=True)
        with self.assertRaisesRegex(
            TransitionError, "requires_scientific_change"
        ):
            self.writer.close_repair(
                changed_cause_proof_hash=partial,
                operation_id="reject-partial-equivalence",
            )
        changed_identity = self._semantic_change_implementation_identity()
        failed, _inner, _evidence = self._packet(
            new_implementation_identity=changed_identity,
            expected_verdict="failed",
        )
        with self.assertRaisesRegex(
            TransitionError, "requires_scientific_change"
        ):
            self.writer.close_repair(
                changed_cause_proof_hash=failed,
                operation_id="reject-failed-equivalence",
            )

    def test_identical_caller_observations_cannot_forge_equivalence(self) -> None:
        changed_identity = self._semantic_change_implementation_identity()
        forged, _inner, _evidence = self._packet(
            new_implementation_identity=changed_identity,
            forged_observations=True,
        )
        with self.assertRaisesRegex(
            TransitionError, "requires_scientific_change"
        ):
            self.writer.close_repair(
                changed_cause_proof_hash=forged,
                operation_id="reject-forged-identical-observations",
            )

    def test_path_swap_cannot_pass_hash_set_equivalence(self) -> None:
        old_identity, _comment_only_identity = (
            self._synthetic_constant_only_pair()
        )
        swapped_identity = self._path_swapped_implementation_identity(
            old_identity
        )
        validated = self._validate_direct_implementation_pair(
            old_implementation_identity=old_identity,
            new_implementation_identity=swapped_identity,
            expected_verdict="failed",
        )
        self.assertEqual(validated.verdict, "failed")
        self.assertEqual(validated.facts["pairing_status"], "semantic_change")

    def test_hash_set_only_manifest_has_no_generic_equivalence_authority(
        self,
    ) -> None:
        hash_only = self._hash_set_only_implementation_identity()
        with self.assertRaisesRegex(
            TransitionError, "source closure|source-closure"
        ):
            self.writer.plan_implementation_repair_semantic_equivalence(
                new_implementation_identity=hash_only,
            )

    def test_unregistered_or_mutated_validator_cannot_close(self) -> None:
        proof, _inner, _evidence = self._packet()
        registered = self.writer.validation_registry
        self.writer.validation_registry = EvidenceValidatorRegistry()
        with self.assertRaisesRegex(TransitionError, "requires_scientific_change"):
            self.writer.close_repair(
                changed_cause_proof_hash=proof,
                operation_id="reject-unregistered-equivalence-validator",
            )
        self.writer.validation_registry = registered
        self.validator.protocol = "tampered.after.registration"
        try:
            with self.assertRaisesRegex(
                TransitionError, "requires_scientific_change"
            ):
                self.writer.close_repair(
                    changed_cause_proof_hash=proof,
                    operation_id="reject-mutated-equivalence-validator",
                )
        finally:
            del self.validator.protocol

    def test_real_fixed_hold_comment_only_is_not_generic_equivalence(
        self,
    ) -> None:
        source_root = RUNTIME_ADAPTER.adapter_source_path.parents[2]
        dependency_paths = fixed_hold_replay_runtime_dependency_paths(
            RUNTIME_ADAPTER
        )
        old_dependencies: list[dict[str, str]] = []
        for path in dependency_paths:
            artifact = self.writer.evidence.finalize(path.read_bytes())
            old_dependencies.append(
                {
                    "path": path.relative_to(source_root).as_posix(),
                    "sha256": artifact.sha256,
                }
            )
        old_closure = self.writer.evidence.finalize(
            fixed_hold_replay_job_implementation_artifact(RUNTIME_ADAPTER)
        )
        old_manifest = {
            "artifact_hashes": sorted(
                {
                    old_closure.sha256,
                    *(item["sha256"] for item in old_dependencies),
                }
            ),
            "callable_identity": RUNTIME_ADAPTER.callable_identity,
            "protocol": RUNTIME_ADAPTER.job_implementation_protocol,
            "schema": "job_implementation_evidence.v1",
        }
        old_implementation = self.writer.evidence.finalize(
            canonical_bytes(old_manifest)
        )

        changed_path = RUNTIME_ADAPTER.adapter_source_path.relative_to(
            source_root
        ).as_posix()
        changed_source = self.writer.evidence.finalize(
            RUNTIME_ADAPTER.adapter_source_path.read_bytes()
            + b"\n# implementation Repair comment-only change\n"
        )
        new_dependencies = [dict(item) for item in old_dependencies]
        for dependency in new_dependencies:
            if dependency["path"] == changed_path:
                dependency["sha256"] = changed_source.sha256
                break
        else:
            self.fail("fixed-hold adapter source is absent from its closure")
        new_implementation = self._implementation_from_dependencies(
            manifest=old_manifest,
            dependencies=new_dependencies,
        )

        validated = self._validate_direct_implementation_pair(
            old_implementation_identity=old_implementation.sha256,
            new_implementation_identity=new_implementation,
            expected_verdict="not_evaluable",
        )
        self.assertEqual(validated.verdict, "not_evaluable")
        self.assertEqual(
            validated.facts["pairing_status"],
            "source_observation_unproven",
        )
        risks = validated.facts["source_observation_risks"]
        self.assertTrue(risks)
        self.assertTrue(any(changed_path in risk for risk in risks))

    def test_synthetic_constant_only_comment_change_passes_validator(
        self,
    ) -> None:
        old_identity, new_identity = self._synthetic_constant_only_pair()
        validated = self._validate_direct_implementation_pair(
            old_implementation_identity=old_identity,
            new_implementation_identity=new_identity,
            expected_verdict="passed",
        )
        self.assertEqual(validated.verdict, "passed")
        self.assertEqual(validated.facts["pairing_status"], "passed")
        self.assertEqual(
            list(validated.claims),
            validated.facts["covered_surface_ids"],
        )
        source_bindings = validated.facts["source_path_bindings"]
        shared = {
            item["relative_path"]: item
            for item in source_bindings
            if item["relative_path"].endswith(
                ("shared_helper.py", "shared_helper_alias.py")
            )
        }
        self.assertEqual(len(shared), 2)
        self.assertEqual(
            {
                item["old_artifact_hash"] for item in shared.values()
            },
            {
                item["new_artifact_hash"] for item in shared.values()
            },
        )
        self.assertEqual(
            len(
                {
                    item["old_artifact_hash"] for item in shared.values()
                }
            ),
            1,
        )
        self.assertTrue(all(not item["changed"] for item in shared.values()))
        self.assertTrue(
            set(self.component_hashes).issubset(
                validated.facts["unchanged_artifact_hashes"]
            )
        )

    def test_non_source_artifact_drift_fails_in_plan_and_validator(
        self,
    ) -> None:
        old_identity, new_identity = self._synthetic_constant_only_pair()
        old_manifest = parse_canonical(
            self.writer.evidence.read_verified(old_identity)
        )
        new_manifest = parse_canonical(
            self.writer.evidence.read_verified(new_identity)
        )
        assert isinstance(old_manifest, dict)
        assert isinstance(new_manifest, dict)
        with LocalIndex(self.writer.index_path) as index:
            trial = index.get("trial", self.executable.identity)
        assert trial is not None
        effective_spec = {
            **self.spec,
            "callable_identity": old_manifest["callable_identity"],
        }
        good_plan = build_semantic_equivalence_plan(
            validator_id=SEMANTIC_EQUIVALENCE_VALIDATOR_ID,
            repair_id=self.repair_id,
            job_id=self.job_id,
            job_hash=self.job_hash,
            executable_id=self.executable.identity,
            job_spec=effective_spec,
            executable_manifest=trial.payload["executable"],
            old_implementation_identity=old_identity,
            old_implementation_manifest=old_manifest,
            new_implementation_identity=new_identity,
            new_implementation_manifest=new_manifest,
            artifact_reader=self.writer.evidence.read_verified,
        )
        unexpected = self.writer.evidence.finalize(
            b"unexpected non-source implementation artifact"
        )
        drifted_manifest = {
            **new_manifest,
            "artifact_hashes": sorted(
                {*new_manifest["artifact_hashes"], unexpected.sha256}
            ),
        }
        drifted = self.writer.evidence.finalize(
            canonical_bytes(drifted_manifest)
        )
        with self.assertRaisesRegex(
            RepairSemanticEquivalenceError,
            "non-source artifact closure",
        ):
            build_semantic_equivalence_plan(
                validator_id=SEMANTIC_EQUIVALENCE_VALIDATOR_ID,
                repair_id=self.repair_id,
                job_id=self.job_id,
                job_hash=self.job_hash,
                executable_id=self.executable.identity,
                job_spec=effective_spec,
                executable_manifest=trial.payload["executable"],
                old_implementation_identity=old_identity,
                old_implementation_manifest=old_manifest,
                new_implementation_identity=drifted.sha256,
                new_implementation_manifest=drifted_manifest,
                artifact_reader=self.writer.evidence.read_verified,
            )

        forged_plan = {
            **good_plan,
            "new_implementation_artifact_hashes": drifted_manifest[
                "artifact_hashes"
            ],
            "new_implementation_identity": drifted.sha256,
        }
        plan_artifact = self.writer.evidence.finalize(
            canonical_bytes(forged_plan)
        )
        measurements: list[str] = []
        for pair in forged_plan["changed_source_pair_bindings"]:
            measurement = self.writer.evidence.finalize(
                canonical_bytes(
                    semantic_equivalence_measurement(
                        validation_plan_hash=plan_artifact.sha256,
                        relative_path=pair["relative_path"],
                        old_artifact_hash=pair["old_artifact_hash"],
                        new_artifact_hash=pair["new_artifact_hash"],
                    )
                )
            )
            measurements.append(measurement.sha256)
        measurement_hashes = tuple(sorted(measurements))
        result = semantic_equivalence_result_manifest(
            plan=forged_plan,
            validation_plan_hash=plan_artifact.sha256,
            measurement_artifact_hashes=measurement_hashes,
            surface_verdicts={
                claim: "passed" for claim in forged_plan["claims"]
            },
        )
        result_artifact = self.writer.evidence.finalize(
            canonical_bytes(result)
        )
        binding = build_semantic_equivalence_binding(
            plan=forged_plan,
            validation_plan_hash=plan_artifact.sha256,
            result_manifest_hash=result_artifact.sha256,
            measurement_artifact_hashes=measurement_hashes,
        )
        artifacts: list[ValidationArtifact] = []
        for ordinal, identity in enumerate(
            binding["declared_artifact_hashes"]
        ):
            artifact = self.writer.evidence.verify(identity)
            artifacts.append(
                ValidationArtifact(
                    output_name=f"drifted-non-source-{ordinal:04d}",
                    sha256=identity,
                    _source=(
                        self.writer.evidence._root / artifact.relative_path
                    ),
                )
            )
        with self.assertRaisesRegex(
            EvidenceValidationError,
            "source-closure authority",
        ):
            self.validator.validate(
                EvidenceValidationRequest(
                    domain="scientific",
                    validator_id=SEMANTIC_EQUIVALENCE_VALIDATOR_ID,
                    validation_plan_hash=plan_artifact.sha256,
                    job_id=self.job_id,
                    job_hash=self.job_hash,
                    mission_id="MIS-REPAIR-EQUIVALENCE",
                    evidence_subject={
                        "kind": "Executable",
                        "id": self.executable.identity,
                    },
                    binding=binding,
                    result_manifest=result,
                    artifacts=tuple(artifacts),
                    engineering_fixture=False,
                )
            )

    def test_actual_comment_only_is_not_evaluable_and_cannot_close(
        self,
    ) -> None:
        validated = self._validate_direct_implementation_pair(
            old_implementation_identity=str(
                self.spec["implementation_identity"]
            ),
            new_implementation_identity=self.new_implementation_identity,
            expected_verdict="not_evaluable",
        )
        self.assertEqual(validated.verdict, "not_evaluable")
        self.assertEqual(
            validated.facts["pairing_status"],
            "source_observation_unproven",
        )
        proof, _inner, _evidence = self._packet()
        with self.assertRaisesRegex(
            TransitionError, "requires_scientific_change"
        ):
            self.writer.close_repair(
                changed_cause_proof_hash=proof,
                operation_id="reject-unproven-comment-only-equivalence",
            )

    def test_rejected_equivalence_preserves_requires_scientific_change_exit(
        self,
    ) -> None:
        repaired_proof, inner_hash, outer_evidence = self._packet(
            missing_pair=True
        )
        with self.assertRaisesRegex(
            TransitionError, "requires_scientific_change"
        ):
            self.writer.close_repair(
                changed_cause_proof_hash=repaired_proof,
                operation_id="reject-equivalence-before-scientific-exit",
            )
        failed_verification = self.writer.evidence.finalize(
            b"semantic equivalence remains incomplete"
        )
        failed_proof = repair_attempt_proof(
            self.writer,
            outcome="failed",
            changed_dimension="implementation",
            new_basis_hash=self.new_implementation_identity,
            new_evidence_hashes=outer_evidence,
            verification_evidence_hashes=(failed_verification.sha256,),
            implementation_proof_hash=inner_hash,
        )
        failed = self.writer.record_failed_repair_attempt(
            attempt_proof_hash=failed_proof,
            operation_id="record-equivalence-failure",
        )
        disposition_hash = engineering_failure_disposition(
            self.writer,
            job_id=self.job_id,
            evidence_hashes=(self.reproduction.sha256,),
            repair_attempt_record_ids=(failed.result["attempt_record_id"],),
            disposition="requires_scientific_change",
        )
        concluded = self.writer.conclude_repair_unrecovered(
            disposition_hash=disposition_hash,
            operation_id="conclude-requires-scientific-change",
        )
        self.assertEqual(
            concluded.result["disposition_hash"], disposition_hash
        )
        control = self.writer.read_control()
        assert control is not None
        self.assertIsNone(control["scientific"]["active_repair"])
        self.assertEqual(
            control["next_action"],
            {
                "disposition_hash": disposition_hash,
                "job_id": self.job_id,
                "kind": "complete_engineering_failure",
            },
        )


if __name__ == "__main__":
    unittest.main()
