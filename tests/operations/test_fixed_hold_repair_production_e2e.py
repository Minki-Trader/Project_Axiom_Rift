from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ExecutableSpec, canonical_digest
from axiom_rift.operations.fixed_hold_repair_equivalence import (
    FIXED_HOLD_AUTHORITY_CORRECTION_PROTOCOL,
    FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_ID,
    FixedHoldAuthorityCorrectionEquivalenceValidator,
)
from axiom_rift.operations.fixed_hold_repair_materializer import (
    materialize_running_job_implementation_repair_proof,
)
from axiom_rift.operations.fixed_hold_repair_validation import (
    FixedHoldRepairAttemptValidator,
)
from axiom_rift.operations.repair_disposition_materializer import (
    materialize_engineering_repair_disposition,
)
from axiom_rift.operations.repair_disposition_validation import (
    EngineeringSemanticChangeNecessityValidator,
)
from axiom_rift.operations.permits import (
    PermitAuthority,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.replay_repair_operational_authority import (
    require_repair_chain,
)
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidatorRegistry,
)
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.portfolio import (
    BatchSpec,
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
    DecisionOption,
    PortfolioAction,
    PortfolioAxis,
    PortfolioDecision,
    PortfolioSnapshot,
)
from axiom_rift.research.validation_v2 import (
    ScientificAdjudicationValidatorV2,
)
from tests.operations.fixed_hold_repair_e2e_fixture import (
    CALLABLE_IDENTITY,
    COMPONENT_IMPLEMENTATION_HASHES,
    EXECUTABLE_ID,
    PROTOCOL_ID,
    Event5433RepairFixture,
    copy_foundation,
    write_source_snapshot,
)
from tests.operations.test_writer import (
    FIXED_EXPIRY,
    FIXED_NOW,
    FIXTURE_DELIVERY_CAPABILITY,
    REPO_ROOT,
    changed_domain_executable,
    exhaustion_standard,
    quant_team_review_for_current_action,
    record_fixture_research_intake,
)


class FixedHoldRepairProductionE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = Event5433RepairFixture.load(REPO_ROOT)

    @staticmethod
    def _axis(
        *,
        fixture: Event5433RepairFixture,
        axis_id: str,
        changed_domains: tuple[ResearchLayer, ...],
        primary_layer: ResearchLayer,
        mechanism_family: str,
        architecture_baseline: ExecutableSpec | None = None,
    ) -> PortfolioAxis:
        baseline = (
            fixture.baseline
            if architecture_baseline is None
            else architecture_baseline
        )
        architecture = ArchitectureChassisSpec.from_executable(
            baseline
        )
        controlled_domains = tuple(
            layer
            for layer in (
                ResearchLayer.FEATURE,
                ResearchLayer.LABEL,
                ResearchLayer.MODEL,
                ResearchLayer.CALIBRATION,
                ResearchLayer.SELECTOR,
                ResearchLayer.TRADE,
                ResearchLayer.LIFECYCLE,
                ResearchLayer.RISK,
                ResearchLayer.EXECUTION,
                ResearchLayer.SYNTHESIS,
                ResearchLayer.PORTFOLIO,
            )
            if layer not in changed_domains
        )
        return PortfolioAxis(
            axis_id=axis_id,
            causal_question=(
                "Does the event 5433 fixed-hold family preserve its exact "
                "causal surface?"
            ),
            mechanism_family=mechanism_family,
            primary_research_layer=primary_layer,
            system_architecture_family=architecture.identity,
            changed_domains=changed_domains,
            controlled_domains=controlled_domains,
            why_now="the registered historical Repair requires production proof",
            stop_or_reopen_condition=(
                "stop only after the exact Repair and engine re-entry chain"
            ),
            architecture_chassis=architecture,
        )

    @staticmethod
    def _materialize_implementation(
        writer: StateWriter,
        sources: dict[str, bytes],
    ) -> str:
        dependencies: list[dict[str, str]] = []
        for relative_path in sorted(sources):
            artifact = writer.evidence.finalize(sources[relative_path])
            dependencies.append(
                {"path": relative_path, "sha256": artifact.sha256}
            )
        closure = writer.evidence.finalize(
            canonical_bytes(
                {
                    "callable_identity": CALLABLE_IDENTITY,
                    "dependencies": dependencies,
                    "schema": "job_implementation_source_closure.v1",
                }
            )
        )
        manifest = writer.evidence.finalize(
            canonical_bytes(
                {
                    "artifact_hashes": sorted(
                        {
                            closure.sha256,
                            *(item["sha256"] for item in dependencies),
                            *COMPONENT_IMPLEMENTATION_HASHES,
                        }
                    ),
                    "callable_identity": CALLABLE_IDENTITY,
                    "protocol": PROTOCOL_ID,
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        return manifest.sha256

    def _open_running_repair(
        self,
        *,
        root: Path,
        foundation_root: Path,
    ) -> tuple[StateWriter, RunningJobExecution, str, str]:
        fixture = self.fixture
        scientific = fixture.scientific_surface["study"]
        target_source_root = foundation_root / "src"
        validator = FixedHoldAuthorityCorrectionEquivalenceValidator(
            source_root=target_source_root
        )
        writer = StateWriter(
            root,
            permit_authority=PermitAuthority(b"r" * 32),
            clock=lambda: FIXED_NOW,
            engineering_fixture=False,
            study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
            foundation_root=foundation_root,
            validation_registry=EvidenceValidatorRegistry(
                (
                    ScientificAdjudicationValidatorV2(),
                    validator,
                    FixedHoldRepairAttemptValidator(),
                    EngineeringSemanticChangeNecessityValidator(),
                )
            ),
        )
        writer.initialize_ready()
        writer.open_mission(
            mission_id="MIS-EVENT-5433-REPAIR-E2E",
            goal={
                "objective": "prove the event 5433 production Repair chain",
                "scope": ["isolated", "production_validation"],
                "terminal_contract": "continue_after_repaired_engine_reentry",
            },
            operation_id="event-5433-mission",
        )
        intake = record_fixture_research_intake(
            writer,
            mission_id="MIS-EVENT-5433-REPAIR-E2E",
            operation_id="event-5433-research-intake",
        )
        writer.open_initiative(
            initiative_id="INI-EVENT-5433-REPAIR-E2E",
            objective={
                "objective": "exercise one exact historical Repair lifecycle",
                "bounds": {"wall_seconds": 300, "trial_delta": 4},
                "done_conditions": ["Repair chain and engine re-entry verified"],
            },
            operation_id="event-5433-initiative",
        )
        changed_domains = tuple(
            ResearchLayer(value) for value in scientific["changed_domains"]
        )
        real_axis = self._axis(
            fixture=fixture,
            axis_id="event-5433-axis",
            changed_domains=changed_domains,
            primary_layer=ResearchLayer(
                scientific["primary_research_layer"]
            ),
            mechanism_family=scientific["mechanism_family"],
        )
        alternate_architecture = changed_domain_executable(
            fixture.baseline,
            domain="execution",
            change_tag="event-5433-independent-architecture",
        )
        calibration_axis = self._axis(
            fixture=fixture,
            axis_id="event-5433-calibration-axis",
            changed_domains=(ResearchLayer.CALIBRATION,),
            primary_layer=ResearchLayer.CALIBRATION,
            mechanism_family="event-5433-calibration-control-family",
        )
        lifecycle_axis = self._axis(
            fixture=fixture,
            axis_id="event-5433-lifecycle-axis",
            changed_domains=(ResearchLayer.LIFECYCLE,),
            primary_layer=ResearchLayer.LIFECYCLE,
            mechanism_family="event-5433-lifecycle-control-family",
            architecture_baseline=alternate_architecture,
        )
        snapshot = PortfolioSnapshot(
            mission_id="MIS-EVENT-5433-REPAIR-E2E",
            axes=(real_axis, calibration_axis, lifecycle_axis),
            opportunity_cost_basis=(
                "retain two independent controls while repairing the exact family"
            ),
            research_intake_id=intake.identity,
            exhaustion_standard=exhaustion_standard(),
        )
        writer.record_portfolio_snapshot(
            snapshot=snapshot,
            operation_id="event-5433-portfolio-snapshot",
        )
        options = (
            DecisionOption(
                option_id="repair-exact-family",
                action=PortfolioAction.SYNTHESIZE,
                target_id=real_axis.axis_id,
                expected_information_value="exact production Repair evidence",
                opportunity_cost="one bounded four-member Batch",
            ),
            DecisionOption(
                option_id="retain-calibration-control",
                action=PortfolioAction.CONTRAST,
                target_id=calibration_axis.axis_id,
                expected_information_value="independent calibration contrast",
                opportunity_cost="deferred until the Repair is verified",
                omission_reason="the interrupted production Job has priority",
            ),
        )
        decision = PortfolioDecision(
            decision_id="DEC-EVENT-5433-REPAIR-E2E",
            chosen_option_id="repair-exact-family",
            options=options,
            rationale="repair the exact registered implementation in place",
            commitment_batches=1,
            quant_team_review=quant_team_review_for_current_action(
                writer,
                options=options,
                chosen_option_id="repair-exact-family",
            ),
            baseline_executable=fixture.baseline,
        )
        writer.record_portfolio_decision(
            decision=decision,
            operation_id="event-5433-portfolio-decision",
        )
        assert decision.architecture_chassis is not None
        controlled_chassis = ControlledStudyChassis(
            baseline_executable=fixture.baseline,
            changed_domains=real_axis.changed_domains,
            controlled_domains=real_axis.controlled_domains,
            architecture=decision.architecture_chassis,
        )
        question = scientific["question"]
        proposal = {
            "mechanism": scientific["mechanism_family"],
            "source_event_sequence": 5433,
        }
        study_hash = writer.study_input_hash(
            question=question,
            material_identity=scientific["material_identity"],
            semantic_proposal=proposal,
            controlled_chassis=controlled_chassis,
            portfolio_axis_id=real_axis.axis_id,
            portfolio_axis_identity=real_axis.identity,
            portfolio_decision_id=decision.identity,
        )
        study_permit = writer.issue_permit(
            kind=PermitKind.STUDY,
            subject_kind=SubjectKind.INITIATIVE,
            subject_id="INI-EVENT-5433-REPAIR-E2E",
            input_hash=study_hash,
            actions=("open_study",),
            scope=(
                "study",
                f"decision:{decision.identity}",
                f"axis:{real_axis.identity}",
                f"baseline:{fixture.baseline.identity}",
                f"chassis:{decision.architecture_chassis.identity}",
                f"snapshot:{snapshot.identity}",
            ),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="event-5433-study-permit",
        )
        opened_study = writer.open_study(
            study_id="STU-EVENT-5433-REPAIR-E2E",
            question=question,
            material_identity=scientific["material_identity"],
            material_display_name="event 5433 observed development material",
            semantic_proposal=proposal,
            controlled_chassis=controlled_chassis,
            portfolio_axis_id=real_axis.axis_id,
            portfolio_axis_identity=real_axis.identity,
            portfolio_decision_id=decision.identity,
            permit=study_permit,
            operation_id="event-5433-study-open",
        )
        family = ConcurrentFamilyManifest(
            evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
            executable_ids=tuple(
                executable.identity for executable in fixture.executables
            ),
        )
        batch_surface = fixture.scientific_surface["batch"]
        acceptance = dict(batch_surface["acceptance_profile"])
        acceptance.pop("concurrent_family")
        batch = BatchSpec(
            batch_id="BAT-EVENT-5433-REPAIR-E2E",
            study_id="STU-EVENT-5433-REPAIR-E2E",
            study_hash=opened_study.result["study_hash"],
            display_name="event 5433 exact concurrent family",
            max_trials=4,
            max_compute_seconds=300,
            max_wall_seconds=300,
            stop_rule=batch_surface["stop_rule"],
            source_contract_ids=(),
            concurrent_family=family,
            acceptance_profile=acceptance,
            adaptive_basis={
                "uncertainty": "historical implementation authority",
                "causal_complexity": "exact four-member concurrent family",
                "surface_curvature": "registered fixed-hold surface",
                "compute_cost": "one bounded Repair verification",
                "expected_information_value": "exact operational authority",
                "portfolio_opportunity_cost": "two preserved control axes",
            },
        )
        batch_permit = writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-EVENT-5433-REPAIR-E2E",
            input_hash=batch.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="event-5433-batch-permit",
        )
        writer.open_batch(
            batch_spec=batch,
            permit=batch_permit,
            operation_id="event-5433-batch-open",
        )
        for ordinal, executable in enumerate(fixture.executables, start=1):
            writer.register_trial(
                executable=executable,
                operation_id=f"event-5433-register-member-{ordinal}",
            )
        old_identity = self._materialize_implementation(
            writer, fixture.old_sources
        )
        self.assertEqual(
            old_identity,
            fixture.expected_old_implementation_identity(),
        )
        job_input_hash = canonical_digest(
            domain="event-5433-repair-e2e-input",
            payload={"event_sequence": 5433, "executable_id": EXECUTABLE_ID},
        )
        spec = {
            "callable_identity": CALLABLE_IDENTITY,
            "implementation_identity": old_identity,
            "input_hashes": [job_input_hash],
            "budget": {
                "compute_seconds": 300,
                "wall_seconds": 300,
                "trials": 1,
            },
            "expected_outputs": ["local/jobs/event-5433/result.json"],
            "output_classes": {
                "local/jobs/event-5433/result.json": "transient"
            },
            "log_path": "local/jobs/event-5433/job.log",
            "timeout_or_stop_rule": "stop at the exact bounded Repair proof",
            "resume_action": "continue_batch",
            "evidence_subject": {
                "kind": "Executable",
                "id": EXECUTABLE_ID,
            },
            "worker_claims": [
                {
                    "worker_id": "event-5433-worker-a",
                    "inputs": ["event-5433-input-a"],
                    "outputs": ["event-5433-output-a"],
                    "resources": ["event-5433-cpu-a"],
                },
                {
                    "worker_id": "event-5433-worker-b",
                    "inputs": ["event-5433-input-b"],
                    "outputs": ["event-5433-output-b"],
                    "resources": ["event-5433-cpu-b"],
                },
            ],
        }
        declared = writer.declare_job(
            spec=spec,
            operation_id="event-5433-job-declare",
        )
        job_id = declared.result["job_id"]
        job_hash = declared.result["job_hash"]
        start_permit = writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=job_id,
            input_hash=job_hash,
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="event-5433-start-permit",
        )
        repair_permit = writer.issue_permit(
            kind=PermitKind.REPAIR,
            subject_kind=SubjectKind.JOB,
            subject_id=job_id,
            input_hash=job_hash,
            actions=("open_repair",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="event-5433-repair-permit",
        )
        started = writer.start_job(
            permit=start_permit,
            operation_id="event-5433-job-start",
        )
        execution = RunningJobExecution.from_mapping(
            started.result["execution"]
        )
        reproduction = writer.evidence.finalize(
            b"event 5433 fixed-hold implementation defect reproduction"
        )
        opened_repair = writer.open_repair(
            permit=repair_permit,
            failure={
                "failure_kind": "engineering",
                "minimum_reproduction_evidence": [reproduction.sha256],
                "root_cause": "registered fixed-hold implementation authority defect",
                "interrupted_action": CALLABLE_IDENTITY,
            },
            operation_id="event-5433-repair-open",
        )
        return writer, execution, opened_repair.result["repair_id"], old_identity

    def test_event_5433_candidate_closes_resumes_and_reconstructs_chain(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            foundation = copy_foundation(REPO_ROOT, root / "authority")
            write_source_snapshot(foundation / "src", self.fixture.old_sources)
            writer, execution, repair_id, old_identity = (
                self._open_running_repair(
                    root=root / "writer",
                    foundation_root=foundation,
                )
            )
            self.assertFalse(writer.engineering_fixture)
            self.assertEqual(
                writer.read_control()["scientific"]["active_repair"]["id"],
                repair_id,
            )
            write_source_snapshot(
                foundation / "src", self.fixture.new_sources
            )
            candidate_hash = (
                materialize_running_job_implementation_repair_proof(
                    writer,
                    callable_identity=CALLABLE_IDENTITY,
                    implementation_materializer=lambda context: (
                        self._materialize_implementation(
                            context, self.fixture.new_sources
                        )
                    ),
                    explanation=(
                        "repair event 5433 fixed-hold authority without changing "
                        "scientific semantics"
                    ),
                )
            )
            evaluated = writer.evaluate_repair_candidate(
                candidate_hash=candidate_hash,
                operation_id="event-5433-evaluate-repair-candidate",
            )
            close_id = evaluated.result["repair_close_record_id"]
            self.assertEqual(
                evaluated.result["effective_implementation_identity"],
                self.fixture.expected_new_implementation_identity(),
            )
            authority = writer.verify_running_job_execution(
                execution,
                expected_callable_identity=CALLABLE_IDENTITY,
                expected_evidence_subject={
                    "kind": "Executable",
                    "id": EXECUTABLE_ID,
                },
            )
            self.assertEqual(
                authority["execution"]["job_id"], execution.job_id
            )
            self.assertEqual(
                authority["implementation_repair_record_id"], close_id
            )
            self.assertIsNotNone(authority["repair_resume_record_id"])
            with writer.open_stable_index() as (_control, index):
                declaration = index.get("job-declared", execution.job_id)
                self.assertIsNotNone(declaration)
                closes = require_repair_chain(
                    index,
                    job_id=execution.job_id,
                    declared_implementation_identity=old_identity,
                    expected_implementation_identity=(
                        self.fixture.expected_new_implementation_identity()
                    ),
                    trigger_repair_close_record_id=close_id,
                    declaration=declaration,
                    executable_id=EXECUTABLE_ID,
                )
            self.assertEqual(len(closes), 1)
            self.assertEqual(closes[0].record_id, close_id)

    def test_production_terminal_requires_registered_domain_inventory(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            foundation = copy_foundation(REPO_ROOT, root / "authority")
            write_source_snapshot(foundation / "src", self.fixture.old_sources)
            writer, _execution, repair_id, _old_identity = (
                self._open_running_repair(
                    root=root / "writer",
                    foundation_root=foundation,
                )
            )
            support = writer.evidence.finalize(
                b"event 5433 infeasible correction evidence"
            )
            with self.assertRaisesRegex(
                EvidenceValidationError,
                "no registered validator authorizes",
            ):
                materialize_engineering_repair_disposition(
                    writer,
                    inventory_validator_id="validator:" + "0" * 64,
                    inventory_protocol="event_5433_terminal_inventory.v1",
                    inventory_result_artifacts={
                        "bounded_route_audit": support.sha256,
                    },
                    rationale="the bounded correction has no executable route",
                    resume_condition="complete the typed engineering failure",
                )
            control = writer.read_control()
            assert control is not None
            self.assertEqual(
                control["scientific"]["active_repair"]["id"],
                repair_id,
            )

    def test_production_semantic_exit_cannot_bypass_inventory_authority(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            foundation = copy_foundation(REPO_ROOT, root / "authority")
            write_source_snapshot(foundation / "src", self.fixture.old_sources)
            writer, _execution, _repair_id, _old_identity = (
                self._open_running_repair(
                    root=root / "writer",
                    foundation_root=foundation,
                )
            )
            inventory = writer.evidence.finalize(
                b"unregistered event 5433 semantic inventory"
            )
            successor = writer.evidence.finalize(
                b"caller-authored semantic successor cannot grant authority"
            )
            with self.assertRaisesRegex(
                EvidenceValidationError,
                "no registered validator authorizes",
            ):
                materialize_engineering_repair_disposition(
                    writer,
                    inventory_validator_id="validator:" + "1" * 64,
                    inventory_protocol="event_5433_semantic_inventory.v1",
                    inventory_result_artifacts={
                        "semantic_route_audit": inventory.sha256,
                    },
                    rationale="the correction changes registered semantics",
                    resume_condition="admit a new Study identity",
                    semantic_change_successor_artifact_hash=successor.sha256,
                )
            control = writer.read_control()
            assert control is not None
            self.assertIsNotNone(control["scientific"]["active_repair"])

    def test_source_root_is_instance_bound_and_registry_sealed(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            validator = FixedHoldAuthorityCorrectionEquivalenceValidator(
                source_root=first
            )
            registry = EvidenceValidatorRegistry((validator,))
            self.assertEqual(validator.source_root, first.resolve())
            validator._source_root = second.resolve()
            with self.assertRaises(EvidenceValidationError):
                registry.require_registered_protocol(
                    validator_id=FIXED_HOLD_AUTHORITY_CORRECTION_VALIDATOR_ID,
                    domain="scientific",
                    protocol=FIXED_HOLD_AUTHORITY_CORRECTION_PROTOCOL,
                )


if __name__ == "__main__":
    unittest.main()
