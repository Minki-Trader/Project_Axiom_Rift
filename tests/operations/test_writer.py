from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
import unittest

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec, canonical_digest
from axiom_rift.operations.permits import PermitAuthority, PermitError, PermitKind, SubjectKind
from axiom_rift.operations.writer import (
    IdenticalFailedRetryError,
    InjectedCrash,
    RecoveryRequired,
    StateWriter,
    TransitionError,
)
from axiom_rift.operations.validation import (
    ENGINEERING_RUNTIME_PLAN_HASH,
    ENGINEERING_VALIDATOR_ID,
    EvidenceValidatorRegistry,
)
from tests.operations.fixture_validators import (
    ExternalFixtureValidator,
    ScientificFixtureValidator,
)
from axiom_rift.research.sources import (
    SourceContract,
    SourceContractError,
    SourceEligibility,
    SourceEligibilityReceipt,
    SourceEligibilityState,
    SourceTransitionEvidence,
    SourceType,
)
from axiom_rift.research.portfolio import (
    BatchSpec,
    DecisionOption,
    PortfolioAction,
    PortfolioAxis,
    PortfolioDecision,
    PortfolioSnapshot,
)
from axiom_rift.research.trials import NegativeMemory
from axiom_rift.storage.journal import JournalIntegrityError, TornJournalError
from axiom_rift.storage.index import IndexRecord, LocalIndex
from axiom_rift.runtime.guards import (
    EvidenceDepth,
    REQUIRED_CASES,
    REQUIRED_PARITY,
    REQUIRED_RELEASE_ARTIFACT_ROLES,
    ReleaseEvidence,
    SealedHoldoutManifest,
)


FIXED_NOW = "2026-07-11T00:00:00Z"
FIXED_EXPIRY = "2026-07-12T00:00:00Z"
REPO_ROOT = Path(__file__).resolve().parents[2]
OBSERVED_MATERIAL_ID = "36caaaeef95d4bfeac4e3df7b2108702a4e64632c94e88d46528ac0cccbd2065"


def digest(domain: str, value: object) -> str:
    return canonical_digest(domain=domain, payload=value)


def job_implementation_identity(
    writer: StateWriter, *, callable_identity: str, revision: int = 1
) -> str:
    source = writer.evidence.finalize(
        canonical_bytes(
            {
                "callable_identity": callable_identity,
                "fixture_revision": revision,
                "schema": "fixture_job_source.v1",
            }
        )
    )
    manifest = writer.evidence.finalize(
        canonical_bytes(
            {
                "artifact_hashes": [source.sha256],
                "callable_identity": callable_identity,
                "protocol": "python.source.fixture.v1",
                "schema": "job_implementation_evidence.v1",
            }
        )
    )
    return manifest.sha256


def job_spec(
    writer: StateWriter,
    evidence_subject: dict[str, str] | None = None,
) -> dict[str, object]:
    callable_identity = "fixture.callable"
    return {
        "callable_identity": callable_identity,
        "implementation_identity": job_implementation_identity(
            writer, callable_identity=callable_identity
        ),
        "input_hashes": [digest("input", {"fixture": 1})],
        "budget": {"compute_seconds": 30, "wall_seconds": 30, "trials": 1},
        "expected_outputs": ["local/jobs/fixture/fixture.json"],
        "output_classes": {"local/jobs/fixture/fixture.json": "transient"},
        "log_path": "local/jobs/fixture.log",
        "timeout_or_stop_rule": "stop_at_30_seconds",
        "resume_action": "resume_fixture_job",
        "evidence_subject": evidence_subject
        or {"kind": "Study", "id": "STU-FIXTURE"},
        "worker_claims": [
            {
                "worker_id": "worker-a",
                "inputs": ["input-a"],
                "outputs": ["output-a"],
                "resources": ["cpu-a"],
            },
            {
                "worker_id": "worker-b",
                "inputs": ["input-b"],
                "outputs": ["output-b"],
                "resources": ["cpu-b"],
            },
        ],
    }


def runtime_job_spec(
    *,
    writer: StateWriter,
    executable_id: str,
    depth: EvidenceDepth,
    output_name: str,
    artifact_roles: tuple[str, ...],
) -> dict[str, object]:
    spec = job_spec(writer, {"kind": "Executable", "id": executable_id})
    result_name = f"{output_name}-result"
    measurement_name = f"{output_name}-measurement"
    role_outputs = {
        role: f"{output_name}-role-{role}" for role in artifact_roles
    }
    spec["expected_outputs"] = [
        result_name,
        measurement_name,
        *role_outputs.values(),
    ]
    spec["output_classes"] = {
        result_name: "durable_evidence",
        measurement_name: "durable_evidence",
        **{output: "durable_evidence" for output in role_outputs.values()},
    }
    spec["input_hashes"] = [
        *spec["input_hashes"],  # type: ignore[list-item]
        ENGINEERING_RUNTIME_PLAN_HASH,
    ]
    if depth is EvidenceDepth.EXECUTION_PROOF:
        action = "run_execution_proof"
        parity = sorted(REQUIRED_PARITY)
        cases: list[str] = []
    elif depth is EvidenceDepth.MATERIALIZATION:
        action = "materialize"
        parity = []
        cases = sorted(REQUIRED_CASES)
    else:
        raise AssertionError("fixture runtime depth is invalid")
    spec["runtime_binding"] = {
        "action": action,
        "evidence_depth": depth.value,
        "planned_materialization_cases": cases,
        "planned_parity_surfaces": parity,
        "result_manifest_output": result_name,
        "artifact_roles": role_outputs,
        "numeric_tolerances": {"default": "fixture_exact"},
        "validation_plan_hash": ENGINEERING_RUNTIME_PLAN_HASH,
        "validator_id": ENGINEERING_VALIDATOR_ID,
    }
    return spec


def source_contract() -> SourceContract:
    return SourceContract(
        display_name="synthetic external source",
        canonical_instrument="synthetic-index",
        runtime_identifier="SYN.IDX",
        source_type=SourceType.BAR,
        instrument_semantics={
            "asset_type": "index",
            "quote_basis": "bid",
            "contract_size": "one",
            "currency": "USD",
            "digits": 2,
            "point": "0.01",
            "session": "declared",
            "timezone": "UTC",
            "adjustment": "none",
            "roll": "none",
        },
        mapping_semantics={
            "runtime_symbol": "SYN.IDX",
            "mapping_rule": "exact_local_symbol",
        },
        schema_semantics={
            "columns": ["time", "open", "high", "low", "close"],
            "schema_revision": "fixture-one",
        },
        field_semantics={
            "bar_open": "open",
            "bar_close": "close",
            "event_time": "bar_open_time",
            "information_complete_at": "bar_close_time",
            "first_available_at": "first_local_observation",
        },
        clock_semantics={
            "decision_alignment": "completed_m5_bar",
            "timezone_conversion": "declared_utc",
        },
        availability_semantics={
            "acquisition": "local_fixture_connector",
            "content_hash": "sha256",
            "coverage": "declared_fixture_window",
            "gap_policy": "fail_closed",
            "revision_or_vintage": "immutable_fixture",
            "causal_ttl_seconds": 60,
            "runtime_retrieval_method": "local_fixture_poll",
        },
    )


def mission_goal(tag: str) -> dict[str, object]:
    return {
        "objective": f"exercise {tag} operating invariant",
        "scope": ["isolated", "engineering_fixture"],
        "terminal_contract": "no_scientific_terminal",
    }


def initiative_objective(tag: str) -> dict[str, object]:
    return {
        "objective": f"exercise {tag} work boundary",
        "bounds": {"wall_seconds": 30, "trial_delta": 0},
        "done_conditions": ["focused invariant observed"],
    }


def study_question(tag: str) -> dict[str, object]:
    return {
        "causal_question": f"does {tag} preserve the declared boundary",
        "changed_variables": [tag],
        "controlled_variables": ["fixture_input", "fixture_clock"],
        "done_conditions": ["guard accepts or rejects before work"],
        "evidence_modes": [
            "causal_contrast",
            "cost_and_execution",
            "sensitivity_or_stress",
        ],
    }


def exhaustion_standard() -> dict[str, object]:
    return {
        "minimum_axes": 3,
        "minimum_distinct_studies_per_axis": 2,
        "minimum_mechanism_families": 3,
        "minimum_negative_executables_per_family": 2,
        "required_evidence_modes": [
            "causal_contrast",
            "cost_and_execution",
            "sensitivity_or_stress",
        ],
        "stop_basis": "all preregistered structural frontiers lose positive information value",
    }


def batch_spec(
    *,
    source_contract_ids: tuple[str, ...] = (),
    batch_id: str = "BAT-FIXTURE",
    study_id: str = "STU-FIXTURE",
    study_hash: str = "a" * 64,
    max_trials: int = 20,
    stop_rule: str = "stop at frozen bound or accepted decision",
) -> BatchSpec:
    return BatchSpec(
        batch_id=batch_id,
        study_id=study_id,
        study_hash=study_hash,
        display_name="bounded adaptive fixture",
        max_trials=max_trials,
        max_compute_seconds=60,
        max_wall_seconds=90,
        stop_rule=stop_rule,
        source_contract_ids=source_contract_ids,
        acceptance_profile={"causality": "required", "unknown_cost": "reject"},
        adaptive_basis={
            "uncertainty": "fixture",
            "causal_complexity": "fixture",
            "surface_curvature": "fixture",
            "compute_cost": "bounded",
            "expected_information_value": "positive",
            "portfolio_opportunity_cost": "declared",
        },
    )


def executable_spec(tag: str) -> ExecutableSpec:
    component = ComponentSpec(
        display_name=f"{tag} fixture component",
        protocol="feature.engineering_fixture.v1",
        implementation="fixture.component",
        spec={"tag": tag},
    )
    return ExecutableSpec(
        display_name=f"{tag} fixture executable",
        components=(component,),
        parameters={"tag": tag},
        data_contract="data:engineering_fixture",
        split_contract="split:engineering_fixture",
        clock_contract="clock:completed_bar_fixture",
        cost_contract="cost:engineering_fixture",
        engine_contract="engine:engineering_fixture",
    )


def scientific_executable_spec(tag: str) -> ExecutableSpec:
    component = ComponentSpec(
        display_name=f"{tag} scientific component",
        protocol="feature.scientific_boundary_fixture.v1",
        implementation="fixture.scientific.component",
        spec={"tag": tag},
    )
    return ExecutableSpec(
        display_name=f"{tag} scientific executable",
        components=(component,),
        parameters={"tag": tag},
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract="split:foundation-observed-development",
        clock_contract="clock:completed-m5-bar",
        cost_contract="cost:fixed-lot-boundary-fixture",
        engine_contract="engine:python-boundary-fixture",
    )


class WriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.writer = StateWriter(
            self.root,
            permit_authority=PermitAuthority(b"p" * 32),
            clock=lambda: FIXED_NOW,
            engineering_fixture=True,
            foundation_root=REPO_ROOT,
        )
        self.writer.initialize_ready()

    def open_mission_and_initiative(self) -> None:
        self.writer.open_mission(
            mission_id="MIS-FIXTURE",
            goal=mission_goal("mission handoff"),
            operation_id="open-mission",
        )
        self.writer.open_initiative(
            initiative_id="INI-FIXTURE",
            objective=initiative_objective("initiative handoff"),
            operation_id="open-initiative",
        )

    def test_engineering_fixture_cannot_target_the_real_worktree(self) -> None:
        with self.assertRaises(TransitionError):
            StateWriter(REPO_ROOT, engineering_fixture=True)

    def open_fixture_study(
        self,
        *,
        study_id: str,
        question: dict[str, object],
        semantic_proposal: dict[str, object],
        operation_prefix: str,
    ):
        study_hash = self.writer.study_input_hash(
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            semantic_proposal=semantic_proposal,
        )
        permit = self.writer.issue_permit(
            kind=PermitKind.STUDY,
            subject_kind=SubjectKind.INITIATIVE,
            subject_id="INI-FIXTURE",
            input_hash=study_hash,
            actions=("open_study",),
            scope=("study",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id=f"{operation_prefix}-permit",
        )
        return self.writer.open_study(
            study_id=study_id,
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            material_display_name="renamed-local-development-frame",
            semantic_proposal=semantic_proposal,
            permit=permit,
            operation_id=f"{operation_prefix}-open",
        )

    def test_exact_ready_boundary_and_atomic_mission_handoff(self) -> None:
        ready = self.writer.read_control()
        assert ready is not None
        self.assertEqual(ready["initiative"]["outcome"], "completed_ready_boundary")
        self.assertEqual(ready["next_action"], {"kind": "await_root_goal"})
        self.assertEqual(ready["scientific"]["holdout_reveals"], 0)
        self.assertIsNone(ready["scientific"]["active_mission"])

        self.open_mission_and_initiative()
        self.writer.close_initiative(outcome="completed", operation_id="close-initiative")
        state = self.writer.read_control()
        assert state is not None
        self.assertEqual(state["scientific"]["active_mission"], "MIS-FIXTURE")
        self.assertIsNone(state["scientific"]["active_initiative"])
        self.assertEqual(state["next_action"]["kind"], "choose_next_initiative_or_terminal")

    def test_running_job_blocks_unrelated_lifecycle_drift(self) -> None:
        self.writer.open_mission(
            mission_id="MIS-ACTIVE-JOB",
            goal=mission_goal("active Job coherence"),
            operation_id="active-job-mission",
        )
        declared = self.writer.declare_job(
            spec=job_spec(
                self.writer, {"kind": "Mission", "id": "MIS-ACTIVE-JOB"}
            ),
            operation_id="active-job-declare",
        )
        permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=declared.result["job_id"],
            input_hash=declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="active-job-permit",
        )
        self.writer.start_job(permit=permit, operation_id="active-job-start")
        before = self.writer.read_control()
        with self.assertRaises(TransitionError):
            self.writer.open_initiative(
                initiative_id="INI-FORBIDDEN",
                objective=initiative_objective("must not overwrite Job"),
                operation_id="reject-initiative-during-job",
            )
        after = self.writer.read_control()
        self.assertEqual(after, before)

    def test_unregistered_runtime_validator_fails_before_engine_work(self) -> None:
        with TemporaryDirectory() as root:
            writer = StateWriter(
                root,
                permit_authority=PermitAuthority(b"v" * 32),
                clock=lambda: FIXED_NOW,
                engineering_fixture=True,
                foundation_root=REPO_ROOT,
                validation_registry=EvidenceValidatorRegistry(),
            )
            writer.initialize_ready()
            writer.open_mission(
                mission_id="MIS-NO-VALIDATOR",
                goal=mission_goal("fail closed validator"),
                operation_id="no-validator-mission",
            )
            executable = executable_spec("no-validator")
            candidate = writer.freeze_candidate(
                executable=executable,
                evidence_refs=("engineering-fixture",),
                operation_id="no-validator-candidate",
            )
            spec = runtime_job_spec(
                writer=writer,
                executable_id=executable.identity,
                depth=EvidenceDepth.EXECUTION_PROOF,
                output_name="evidence/no-validator",
                artifact_roles=("native_execution_report",),
            )
            declared = writer.declare_job(
                spec=spec, operation_id="no-validator-job"
            )
            job_permit = writer.issue_permit(
                kind=PermitKind.JOB,
                subject_kind=SubjectKind.JOB,
                subject_id=declared.result["job_id"],
                input_hash=declared.result["job_hash"],
                actions=("start_job",),
                scope=("job",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="no-validator-job-permit",
            )
            runtime_permit = writer.issue_permit(
                kind=PermitKind.RUNTIME,
                subject_kind=SubjectKind.EXECUTABLE,
                subject_id=executable.identity,
                input_hash=declared.result["job_hash"],
                actions=("run_execution_proof",),
                scope=(
                    f"candidate:{candidate.result['candidate_id']}",
                    "depth:execution_proof",
                    f"executable:{executable.identity}",
                    f"job:{declared.result['job_id']}",
                ),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=False,
                operation_id="no-validator-runtime-permit",
            )
            with self.assertRaises(TransitionError):
                writer.start_job(
                    permit=job_permit,
                    runtime_permit=runtime_permit,
                    operation_id="reject-no-validator-start",
                )
            self.assertEqual(
                writer.read_control()["scientific"]["active_job"]["status"],  # type: ignore[index]
                "declared",
            )

    def test_unregistered_external_validator_cannot_count_blocker_attempt(self) -> None:
        with TemporaryDirectory() as root:
            writer = StateWriter(
                root,
                permit_authority=PermitAuthority(b"x" * 32),
                clock=lambda: FIXED_NOW,
                foundation_root=REPO_ROOT,
            )
            writer.initialize_ready()
            writer.open_mission(
                mission_id="MIS-EXTERNAL-VALIDATOR",
                goal=mission_goal("external dependency validation"),
                operation_id="external-validator-mission",
            )
            plan = writer.evidence.finalize(b"external validation plan fixture")
            spec = job_spec(
                writer,
                {"kind": "Mission", "id": "MIS-EXTERNAL-VALIDATOR"}
            )
            result_name = "evidence/external-result"
            measurement_name = "evidence/external-measurement"
            spec["input_hashes"] = [*spec["input_hashes"], plan.sha256]
            spec["expected_outputs"] = [result_name, measurement_name]
            spec["output_classes"] = {
                result_name: "durable_evidence",
                measurement_name: "durable_evidence",
            }
            spec["external_dependency_binding"] = {
                "blocked_mission_capability": "indispensable broker history acquisition",
                "dependency_id": "fpmarkets-history-service",
                "dependency_kind": "market_data_service",
                "exact_resume_action": "resume_fixture_job",
                "recovery_kind": "external_probe",
                "recovery_path_id": "broker-history-probe",
                "result_manifest_output": result_name,
                "required_external_change": "broker history service becomes available",
                "validation_plan_hash": plan.sha256,
                "validator_id": "validator:" + "f" * 64,
            }
            declared = writer.declare_job(
                spec=spec, operation_id="external-validator-declare"
            )
            permit = writer.issue_permit(
                kind=PermitKind.JOB,
                subject_kind=SubjectKind.JOB,
                subject_id=declared.result["job_id"],
                input_hash=declared.result["job_hash"],
                actions=("start_job",),
                scope=("job",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="external-validator-permit",
            )
            with self.assertRaises(TransitionError):
                writer.start_job(
                    permit=permit, operation_id="reject-unvalidated-external-probe"
                )
            with LocalIndex(writer.index_path) as index:
                self.assertIsNone(
                    index.event_head(
                        "external-dependency:fpmarkets-history-service"
                    )
                )

    def test_empty_mission_cannot_forge_negative_or_external_terminal(self) -> None:
        with TemporaryDirectory() as root:
            writer = StateWriter(root, clock=lambda: FIXED_NOW, foundation_root=REPO_ROOT)
            writer.initialize_ready()
            writer.open_mission(
                mission_id="MIS-EMPTY",
                goal=mission_goal("empty terminal rejection"),
                operation_id="empty-mission",
            )
            with LocalIndex(writer.index_path) as index:
                mission_record = index.records_by_subject_status(
                    subject="Mission:MIS-EMPTY", status="open"
                )[0]
            with self.assertRaises(TransitionError):
                writer.accept_exhaustion_audit(
                    frontiers={
                        "invented-axis": (
                            {
                                "kind": mission_record.kind,
                                "record_id": mission_record.record_id,
                            },
                        )
                    },
                    diversity_basis="caller prose is not authority",
                    opportunity_cost_audit="no work occurred",
                    operation_id="reject-empty-exhaustion",
                )
            with self.assertRaises(TransitionError):
                writer.record_external_blocker(
                    dependency_id="local-parser-error",
                    completion_record_ids=("fake-one", "fake-two", "fake-three"),
                    operation_id="reject-fake-external-blocker",
                )
            self.assertEqual(
                writer.read_control()["scientific"]["active_mission"],  # type: ignore[index]
                "MIS-EMPTY",
            )

    def test_portfolio_decision_requires_a_current_declared_target(self) -> None:
        self.open_mission_and_initiative()
        snapshot = PortfolioSnapshot(
            mission_id="MIS-FIXTURE",
            axes=(
                PortfolioAxis(
                    axis_id="axis-microstructure",
                    causal_question="Does local state alter short-horizon response?",
                    mechanism_family="microstructure",
                ),
                PortfolioAxis(
                    axis_id="axis-macro",
                    causal_question="Does macro state alter conditional direction?",
                    mechanism_family="macro",
                ),
            ),
            opportunity_cost_basis="compare unrelated causal mechanisms",
        )
        self.writer.record_portfolio_snapshot(
            snapshot=snapshot, operation_id="portfolio-snapshot"
        )
        invalid = PortfolioDecision(
            decision_id="DEC-INVALID-TARGET",
            chosen_option_id="invalid",
            options=(
                DecisionOption(
                    option_id="invalid",
                    action=PortfolioAction.DEEPEN,
                    target_id="axis-does-not-exist",
                    expected_information_value="high if it existed",
                    opportunity_cost="unknown",
                ),
                DecisionOption(
                    option_id="contrast",
                    action=PortfolioAction.CONTRAST,
                    target_id="axis-macro",
                    expected_information_value="moderate",
                    opportunity_cost="bounded",
                    omission_reason="invalid target was nominally chosen",
                ),
            ),
            rationale="exercise durable Portfolio target validation",
            commitment_batches=1,
        )
        with self.assertRaises(TransitionError):
            self.writer.record_portfolio_decision(
                decision=invalid, operation_id="reject-unknown-portfolio-target"
            )
        valid = PortfolioDecision(
            decision_id="DEC-VALID-TARGET",
            chosen_option_id="micro",
            options=(
                DecisionOption(
                    option_id="micro",
                    action=PortfolioAction.DEEPEN,
                    target_id="axis-microstructure",
                    expected_information_value="high",
                    opportunity_cost="bounded",
                ),
                DecisionOption(
                    option_id="macro",
                    action=PortfolioAction.CONTRAST,
                    target_id="axis-macro",
                    expected_information_value="moderate",
                    opportunity_cost="defer one Batch",
                    omission_reason="microstructure has higher immediate information value",
                ),
            ),
            rationale="retain a structurally distinct alternative",
            commitment_batches=1,
        )
        recorded = self.writer.record_portfolio_decision(
            decision=valid, operation_id="record-valid-portfolio-target"
        )
        self.assertEqual(recorded.result["decision_id"], valid.identity)
        self.assertEqual(
            self.writer.read_control()["next_action"]["target_id"],  # type: ignore[index]
            "axis-microstructure",
        )

    def test_portfolio_cannot_bypass_required_initiative_open(self) -> None:
        self.writer.open_mission(
            mission_id="MIS-PORTFOLIO-ORDER",
            goal=mission_goal("Portfolio Initiative order"),
            operation_id="portfolio-order-mission",
        )
        snapshot = PortfolioSnapshot(
            mission_id="MIS-PORTFOLIO-ORDER",
            axes=(
                PortfolioAxis(
                    axis_id="order-axis-a",
                    causal_question="Does order axis A carry information?",
                    mechanism_family="order-family-a",
                ),
                PortfolioAxis(
                    axis_id="order-axis-b",
                    causal_question="Does order axis B carry information?",
                    mechanism_family="order-family-b",
                ),
            ),
            opportunity_cost_basis="Initiative must own Portfolio construction",
        )
        before = self.writer.read_control()
        with self.assertRaises(TransitionError):
            self.writer.record_portfolio_snapshot(
                snapshot=snapshot,
                operation_id="reject-portfolio-before-initiative",
            )
        self.assertEqual(self.writer.read_control(), before)

    def test_active_batch_blocks_portfolio_mutation(self) -> None:
        self.open_mission_and_initiative()
        snapshot = PortfolioSnapshot(
            mission_id="MIS-FIXTURE",
            axes=(
                PortfolioAxis(
                    axis_id="axis-a",
                    causal_question="Does axis A carry conditional information?",
                    mechanism_family="family-a",
                ),
                PortfolioAxis(
                    axis_id="axis-b",
                    causal_question="Does axis B carry conditional information?",
                    mechanism_family="family-b",
                ),
            ),
            opportunity_cost_basis="retain independent mechanisms",
        )
        self.writer.record_portfolio_snapshot(
            snapshot=snapshot, operation_id="active-batch-snapshot"
        )
        decision = PortfolioDecision(
            decision_id="DEC-ACTIVE-BATCH",
            chosen_option_id="work-a",
            options=(
                DecisionOption(
                    option_id="work-a",
                    action=PortfolioAction.DEEPEN,
                    target_id="axis-a",
                    expected_information_value="high",
                    opportunity_cost="bounded",
                ),
                DecisionOption(
                    option_id="retain-b",
                    action=PortfolioAction.CONTRAST,
                    target_id="axis-b",
                    expected_information_value="moderate",
                    opportunity_cost="one Batch",
                    omission_reason="axis A has higher current information value",
                ),
            ),
            rationale="exercise active work drift guard",
            commitment_batches=1,
        )
        self.writer.record_portfolio_decision(
            decision=decision, operation_id="active-batch-decision"
        )
        study = self.open_fixture_study(
            study_id="STU-ACTIVE-BATCH",
            question=study_question("active Batch Portfolio guard"),
            semantic_proposal={"mechanism": "active work drift"},
            operation_prefix="active-batch-study",
        )
        batch = batch_spec(
            batch_id="BAT-ACTIVE",
            study_id="STU-ACTIVE-BATCH",
            study_hash=study.result["study_hash"],
        )
        permit = self.writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-ACTIVE-BATCH",
            input_hash=batch.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="active-batch-permit",
        )
        self.writer.open_batch(
            batch_spec=batch, permit=permit, operation_id="active-batch-open"
        )
        before = self.writer.read_control()
        with self.assertRaises(TransitionError):
            self.writer.record_portfolio_snapshot(
                snapshot=snapshot, operation_id="reject-snapshot-during-batch"
            )
        with self.assertRaises(TransitionError):
            self.writer.record_portfolio_decision(
                decision=decision, operation_id="reject-decision-during-batch"
            )
        self.assertEqual(self.writer.read_control(), before)

    def test_portfolio_batch_commitment_is_mechanical(self) -> None:
        with TemporaryDirectory() as root:
            writer = StateWriter(
                root,
                permit_authority=PermitAuthority(b"m" * 32),
                clock=lambda: FIXED_NOW,
                foundation_root=REPO_ROOT,
            )
            writer.initialize_ready()
            writer.open_mission(
                mission_id="MIS-COMMITMENT",
                goal=mission_goal("Portfolio Batch commitment"),
                operation_id="commitment-mission",
            )
            writer.open_initiative(
                initiative_id="INI-COMMITMENT",
                objective=initiative_objective("Portfolio commitment"),
                operation_id="commitment-initiative",
            )
            axis_a = PortfolioAxis(
                axis_id="axis-commit-a",
                causal_question="Does committed axis A add information?",
                mechanism_family="commit-family-a",
            )
            axis_b = PortfolioAxis(
                axis_id="axis-commit-b",
                causal_question="Does committed axis B add information?",
                mechanism_family="commit-family-b",
            )
            axis_c = PortfolioAxis(
                axis_id="axis-commit-c",
                causal_question="Does committed axis C add information?",
                mechanism_family="commit-family-c",
            )
            snapshot = PortfolioSnapshot(
                mission_id="MIS-COMMITMENT",
                axes=(axis_a, axis_b, axis_c),
                opportunity_cost_basis="one bounded Batch before reconsideration",
                exhaustion_standard=exhaustion_standard(),
            )
            writer.record_portfolio_snapshot(
                snapshot=snapshot, operation_id="commitment-snapshot"
            )
            decision = PortfolioDecision(
                decision_id="DEC-COMMITMENT",
                chosen_option_id="choose-a",
                options=(
                    DecisionOption(
                        option_id="choose-a",
                        action=PortfolioAction.DEEPEN,
                        target_id=axis_a.axis_id,
                        expected_information_value="positive",
                        opportunity_cost="one Batch",
                    ),
                    DecisionOption(
                        option_id="retain-b",
                        action=PortfolioAction.CONTRAST,
                        target_id=axis_b.axis_id,
                        expected_information_value="positive",
                        opportunity_cost="deferred",
                        omission_reason="axis A receives the single commitment",
                    ),
                ),
                rationale="bind exactly one Batch",
                commitment_batches=1,
            )
            writer.record_portfolio_decision(
                decision=decision, operation_id="commitment-decision"
            )
            question = study_question("mechanical commitment")
            proposal = {"mechanism": "commitment enforcement"}
            study_hash = writer.study_input_hash(
                question=question,
                material_identity=OBSERVED_MATERIAL_ID,
                semantic_proposal=proposal,
                portfolio_axis_id=axis_a.axis_id,
                portfolio_axis_identity=axis_a.identity,
                portfolio_decision_id=decision.identity,
            )
            study_permit = writer.issue_permit(
                kind=PermitKind.STUDY,
                subject_kind=SubjectKind.INITIATIVE,
                subject_id="INI-COMMITMENT",
                input_hash=study_hash,
                actions=("open_study",),
                scope=("study",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="commitment-study-permit",
            )
            opened = writer.open_study(
                study_id="STU-COMMITMENT",
                question=question,
                material_identity=OBSERVED_MATERIAL_ID,
                material_display_name="foundation development material",
                semantic_proposal=proposal,
                portfolio_axis_id=axis_a.axis_id,
                portfolio_axis_identity=axis_a.identity,
                portfolio_decision_id=decision.identity,
                permit=study_permit,
                operation_id="commitment-study-open",
            )
            first = batch_spec(
                batch_id="BAT-COMMITMENT-1",
                study_id="STU-COMMITMENT",
                study_hash=opened.result["study_hash"],
            )
            first_permit = writer.issue_permit(
                kind=PermitKind.BATCH,
                subject_kind=SubjectKind.STUDY,
                subject_id="STU-COMMITMENT",
                input_hash=first.identity.removeprefix("batch:"),
                actions=("open_batch",),
                scope=("batch",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="commitment-first-permit",
            )
            writer.open_batch(
                batch_spec=first,
                permit=first_permit,
                operation_id="commitment-first-open",
            )
            writer.dispose_batch(
                outcome="completed", operation_id="commitment-first-close"
            )
            second = batch_spec(
                batch_id="BAT-COMMITMENT-2",
                study_id="STU-COMMITMENT",
                study_hash=opened.result["study_hash"],
                max_trials=21,
            )
            second_permit = writer.issue_permit(
                kind=PermitKind.BATCH,
                subject_kind=SubjectKind.STUDY,
                subject_id="STU-COMMITMENT",
                input_hash=second.identity.removeprefix("batch:"),
                actions=("open_batch",),
                scope=("batch",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="commitment-second-permit",
            )
            with self.assertRaises(TransitionError):
                writer.open_batch(
                    batch_spec=second,
                    permit=second_permit,
                    operation_id="reject-second-committed-batch",
                )

    def test_permit_matrix_and_revocation_prevent_work_before_entry(self) -> None:
        self.open_mission_and_initiative()
        with self.assertRaises(PermitError):
            self.writer.issue_permit(
                kind=PermitKind.JOB,
                subject_kind=SubjectKind.MISSION,
                subject_id="MIS-FIXTURE",
                input_hash=digest("job", {"wrong_subject": True}),
                actions=("start_job",),
                scope=("job",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="reject-wrong-permit-subject",
            )
        question = study_question("revoked study")
        study_hash = self.writer.study_input_hash(
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            semantic_proposal={"mechanism": "revocation fixture"},
        )
        permit = self.writer.issue_permit(
            kind=PermitKind.STUDY,
            subject_kind=SubjectKind.INITIATIVE,
            subject_id="INI-FIXTURE",
            input_hash=study_hash,
            actions=("open_study",),
            scope=("study",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="issue-revoked-study-permit",
        )
        self.writer.revoke_permit(
            permit_id=permit.permit_id,
            reason="fixture revocation before engine entry",
            operation_id="revoke-study-permit",
        )
        with self.assertRaises(PermitError):
            self.writer.open_study(
                study_id="STU-REVOKED",
                question=question,
                material_identity=OBSERVED_MATERIAL_ID,
                material_display_name="fixture-material",
                semantic_proposal={"mechanism": "revocation fixture"},
                permit=permit,
                operation_id="reject-revoked-study-open",
            )

    def test_batch_job_one_writer_repair_and_cache_guards(self) -> None:
        self.open_mission_and_initiative()
        question = study_question("batch job repair")
        study = self.open_fixture_study(
            study_id="STU-FIXTURE",
            question=question,
            semantic_proposal={"mechanism": "fixture"},
            operation_prefix="study",
        )
        self.assertEqual(study.result["prior_global_multiplicity"], 18)
        frozen_batch = batch_spec(study_hash=study.result["study_hash"])
        batch_hash = frozen_batch.identity.removeprefix("batch:")
        batch_permit = self.writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-FIXTURE",
            input_hash=batch_hash,
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="issue-batch-permit",
        )
        self.writer.open_batch(
            batch_spec=frozen_batch,
            permit=batch_permit,
            operation_id="open-batch",
        )
        with self.assertRaises(TransitionError):
            self.writer.close_initiative(outcome="invalid", operation_id="close-too-early")

        oversized_job = job_spec(self.writer)
        oversized_job["budget"] = {
            "compute_seconds": 61,
            "wall_seconds": 30,
            "trials": 1,
        }
        with self.assertRaises(TransitionError):
            self.writer.declare_job(
                spec=oversized_job,
                operation_id="reject-oversized-job",
            )
        declared = self.writer.declare_job(
            spec=job_spec(self.writer), operation_id="declare-job"
        )
        job_id = declared.result["job_id"]
        job_hash = declared.result["job_hash"]
        with self.assertRaises(TransitionError):
            self.writer.declare_job(
                spec=job_spec(self.writer), operation_id="declare-conflict"
            )

        start_permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=job_id,
            input_hash=job_hash,
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="issue-start-permit",
        )
        repair_permit = self.writer.issue_permit(
            kind=PermitKind.REPAIR,
            subject_kind=SubjectKind.JOB,
            subject_id=job_id,
            input_hash=job_hash,
            actions=("open_repair",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="issue-repair-permit",
        )
        # The unrelated permit issue changed global revision but not Job auth.
        self.writer.start_job(permit=start_permit, operation_id="start-job")
        with self.assertRaises((PermitError, TransitionError)):
            self.writer.start_job(permit=start_permit, operation_id="replay-start")

        before = self.writer.read_control()
        reproduction = self.writer.evidence.finalize(b"fixture parser failure reproduction")
        self.writer.open_repair(
            permit=repair_permit,
            failure={
                "failure_kind": "engineering",
                "minimum_reproduction_evidence": [reproduction.sha256],
                "root_cause": "fixture parser rejected declared input",
                "interrupted_action": "fixture.callable",
            },
            operation_id="open-repair",
        )
        changed_cause = self.writer.evidence.finalize(b"fixture parser repaired proof")
        self.writer.close_repair(
            changed_cause_proof_hash=changed_cause.sha256,
            operation_id="close-repair",
        )
        after = self.writer.read_control()
        assert before is not None and after is not None
        for key in ("holdout_reveals", "active_executable", "required_future_holdout_id"):
            self.assertEqual(before["scientific"][key], after["scientific"][key])
        self.assertEqual(after["scientific"]["active_job"]["status"], "running")

        transient = self.root / "local" / "jobs" / "fixture" / "fixture.json"
        transient.parent.mkdir(parents=True, exist_ok=True)
        transient.write_bytes(b"fixture output")
        self.writer.complete_job(
            outcome="success",
            output_manifest={
                "local/jobs/fixture/fixture.json": sha256(b"fixture output").hexdigest()
            },
            operation_id="complete-job",
        )
        self.assertFalse(transient.exists())
        executable = executable_spec("trial")
        first = self.writer.register_trial(
            executable=executable,
            operation_id="trial-one",
        )
        cached = self.writer.register_trial(
            executable=executable.renamed("renamed trial fixture"),
            operation_id="trial-cache",
        )
        self.assertEqual(first.result["trial_delta"], 0)
        self.assertEqual(cached.result["trial_delta"], 0)

        self.writer.dispose_batch(
            outcome="engineering_fixture_complete", operation_id="dispose-batch"
        )
        self.writer.close_study(
            outcome="engineering_fixture_complete", operation_id="close-study"
        )
        self.writer.close_initiative(
            outcome="engineering_fixture_complete", operation_id="close-initiative"
        )
        with self.assertRaises(TransitionError):
            self.writer.close_mission(
                outcome="completed_pre_live_handoff",
                basis_record_id="fixture-evidence",
                operation_id="false-terminal",
            )

    def test_durable_source_gate_requires_exact_transition_before_permit(self) -> None:
        self.open_mission_and_initiative()
        source_study = self.open_fixture_study(
            study_id="STU-SOURCE",
            question=study_question("external source gate"),
            semantic_proposal={"mechanism": "external source feasibility"},
            operation_prefix="source-study",
        )
        contract = source_contract()
        context = SourceEligibility.register(contract)
        self.writer.record_source_eligibility(
            eligibility=context,
            receipt=None,
            operation_id="register-source",
        )
        with self.assertRaises(PermitError):
            self.writer.issue_permit(
                kind=PermitKind.SOURCE,
                subject_kind=SubjectKind.STUDY,
                subject_id="STU-SOURCE",
                input_hash=digest("source-use", {"fixture": True}),
                actions=("performance_batch",),
                scope=(f"source:{contract.source_contract_id}",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="source-permit-too-early",
            )
        historical_artifact = self.writer.evidence.finalize(b"historical source audit fixture")
        historical_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.HISTORICAL_AUDIT,
            producer_completion_id="engineering-fixture",
            observed_at_utc=FIXED_NOW,
            artifact_hashes=(historical_artifact.sha256,),
            facts={
                "acquisition_observed": True,
                "content_hash_verified": True,
                "event_time_audited": True,
                "information_complete_at_audited": True,
                "first_availability_audited": True,
                "coverage_audited": True,
                "gaps_audited": True,
                "revision_or_vintage_audited": True,
            },
        )
        runtime_artifact = self.writer.evidence.finalize(b"runtime source proof fixture")
        runtime_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
            producer_completion_id="engineering-fixture",
            observed_at_utc=FIXED_NOW,
            artifact_hashes=(runtime_artifact.sha256,),
            facts={
                "local_realtime_retrieval": True,
                "fresh": True,
                "synchronized": True,
                "complete_or_closed": True,
                "latency_ms": 5,
                "historical_runtime_field_parity": True,
            },
        )
        audited = context.complete_historical_audit(historical_receipt.identity)
        wrong = SourceEligibility(
            contract=contract,
            state=SourceEligibilityState.HISTORICAL_AUDITED,
            evidence_receipt_id=runtime_receipt.identity,
        )
        with self.assertRaises(SourceContractError):
            self.writer.record_source_eligibility(
                eligibility=wrong,
                receipt=runtime_receipt,
                operation_id="wrong-source-edge",
            )
        self.writer.record_source_eligibility(
            eligibility=audited,
            receipt=historical_receipt,
            operation_id="audit-source",
        )
        eligible = audited.prove_runtime_availability(runtime_receipt.identity)
        self.writer.record_source_eligibility(
            eligibility=eligible,
            receipt=runtime_receipt,
            operation_id="qualify-source",
        )
        source_batch = batch_spec(
            source_contract_ids=(contract.source_contract_id,),
            batch_id="BAT-SOURCE",
            study_id="STU-SOURCE",
            study_hash=source_study.result["study_hash"],
        )
        source_batch_hash = source_batch.identity.removeprefix("batch:")
        permit = self.writer.issue_permit(
            kind=PermitKind.SOURCE,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-SOURCE",
            input_hash=source_batch_hash,
            actions=("performance_batch",),
            scope=(f"source:{contract.source_contract_id}",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="issue-source-permit",
        )
        self.assertEqual(permit.kind, PermitKind.SOURCE)
        batch_permit = self.writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-SOURCE",
            input_hash=source_batch_hash,
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="issue-source-batch-permit",
        )
        drift_artifact = self.writer.evidence.finalize(b"source mapping drift fixture")
        drift_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.DRIFT,
            producer_completion_id="engineering-fixture",
            observed_at_utc=FIXED_NOW,
            artifact_hashes=(drift_artifact.sha256,),
            facts={
                "changed_surface": "mapping",
                "observed_change": "fixture mapping changed",
                "dependent_action": "fail_closed",
            },
        )
        suspended = eligible.suspend(
            receipt_id=drift_receipt.identity,
            reason="fixture mapping drift",
        )
        self.writer.record_source_eligibility(
            eligibility=suspended,
            receipt=drift_receipt,
            operation_id="suspend-source",
        )
        with self.assertRaises(PermitError):
            self.writer.open_batch(
                batch_spec=source_batch,
                permit=batch_permit,
                source_permits=(permit,),
                operation_id="reject-stale-source-permit",
            )
        recert_artifact = self.writer.evidence.finalize(b"source recertification fixture")
        recert_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION,
            producer_completion_id="engineering-fixture",
            observed_at_utc=FIXED_NOW,
            artifact_hashes=(recert_artifact.sha256,),
            facts={
                "semantic_equivalence": True,
                "mapping_parity": True,
                "schema_field_clock_parity": True,
            },
        )
        restored = SourceEligibility(
            contract=contract,
            state=SourceEligibilityState.RUNTIME_ELIGIBLE,
            evidence_receipt_id=recert_receipt.identity,
        )
        self.writer.record_source_eligibility(
            eligibility=restored,
            receipt=recert_receipt,
            operation_id="recertify-source",
        )
        replacement_permit = self.writer.issue_permit(
            kind=PermitKind.SOURCE,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-SOURCE",
            input_hash=source_batch_hash,
            actions=("performance_batch",),
            scope=(f"source:{contract.source_contract_id}",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="issue-recertified-source-permit",
        )
        self.writer.open_batch(
            batch_spec=source_batch,
            permit=batch_permit,
            source_permits=(replacement_permit,),
            operation_id="open-source-batch",
        )

    def test_source_projection_tamper_cannot_issue_permit_and_recovers(self) -> None:
        self.open_mission_and_initiative()
        self.open_fixture_study(
            study_id="STU-TAMPER",
            question=study_question("source projection tamper"),
            semantic_proposal={"mechanism": "projection integrity"},
            operation_prefix="tamper-study",
        )
        contract = source_contract()
        registered = SourceEligibility.register(contract)
        self.writer.record_source_eligibility(
            eligibility=registered,
            receipt=None,
            operation_id="register-tamper-source",
        )
        before_revision = self.writer.read_control()["revision"]  # type: ignore[index]
        with LocalIndex(self.writer.index_path) as index:
            head = index.event_head(f"source:{contract.source_contract_id}")
            assert head is not None
            index._connection.execute(  # noqa: SLF001 - adversarial projection test
                "UPDATE records SET status = ? WHERE kind = ? AND record_id = ?",
                ("runtime_eligible", head.record_kind, head.record_id),
            )
        with self.assertRaises((PermitError, RecoveryRequired)):
            self.writer.issue_permit(
                kind=PermitKind.SOURCE,
                subject_kind=SubjectKind.STUDY,
                subject_id="STU-TAMPER",
                input_hash=digest("source-tamper", {"attempt": 1}),
                actions=("performance_batch",),
                scope=(f"source:{contract.source_contract_id}",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="reject-tampered-source-permit",
            )
        self.assertEqual(
            self.writer.read_control()["revision"],  # type: ignore[index]
            before_revision,
        )
        recovered = self.writer.recover()
        self.assertTrue(recovered["index_rebuilt"])
        with LocalIndex(self.writer.index_path) as index:
            head = index.event_head(f"source:{contract.source_contract_id}")
            assert head is not None
            restored = index.get(head.record_kind, head.record_id)
            self.assertEqual(restored.status, "context_only")  # type: ignore[union-attr]

    def test_identical_success_reuses_and_failed_retry_is_rejected(self) -> None:
        self.writer.open_mission(
            mission_id="MIS-WORK-CACHE",
            goal=mission_goal("work result cache"),
            operation_id="open-work-cache-mission",
        )
        success = {
            "callable_identity": "fixture.cache",
            "input_identity": "success-case",
        }
        self.writer.record_work_result(
            work=success,
            outcome="success",
            details={"fixture": True},
            operation_id="work-success",
        )
        reused = self.writer.record_work_result(
            work=success,
            outcome="success",
            details={"fixture": True},
            operation_id="work-success-reuse",
        )
        self.assertEqual(reused.result["disposition"], "reuse_success")

        failed = {
            "callable_identity": "fixture.cache",
            "input_identity": "failed-case",
        }
        self.writer.record_work_result(
            work=failed,
            outcome="failed",
            details={"cause": "fixture"},
            operation_id="work-failed",
        )
        with self.assertRaises(IdenticalFailedRetryError):
            self.writer.record_work_result(
                work=failed,
                outcome="failed",
                details={"cause": "fixture"},
                operation_id="work-failed-retry",
            )

    def test_holdout_seal_and_one_time_permit(self) -> None:
        self.writer.open_mission(
            mission_id="MIS-HOLDOUT",
            goal=mission_goal("holdout"),
            operation_id="holdout-mission",
        )
        executable = executable_spec("holdout")
        frozen = self.writer.freeze_candidate(
            executable=executable,
            evidence_refs=("engineering-fixture",),
            operation_id="freeze-fixture",
        )
        executable_id = frozen.result["executable_id"]
        artifact = self.writer.evidence.finalize(b"synthetic sealed values")
        sealed_rows = SealedHoldoutManifest.rows_identity(
            artifact_sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
        )
        sealed_start = "2026-07-01T00:00:00Z"
        sealed_end = "2026-07-10T00:00:00Z"
        sealed = SealedHoldoutManifest(
            artifact_sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            data_receipt_id=SealedHoldoutManifest.dataset_identity(
                artifact.sha256
            ),
            split_identity=SealedHoldoutManifest.split_identity_for(
                row_identity=sealed_rows,
                starts_at_utc=sealed_start,
                ends_at_utc=sealed_end,
                predecessor_holdout_id=None,
            ),
            row_identity=sealed_rows,
            starts_at_utc=sealed_start,
            ends_at_utc=sealed_end,
        )
        self.writer.record_holdout_seal(
            manifest=sealed, operation_id="seal-semantic-holdout"
        )
        relabelled_start = "2026-07-11T00:00:00Z"
        relabelled_end = "2026-07-20T00:00:00Z"
        relabelled_same_rows = SealedHoldoutManifest(
            artifact_sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            data_receipt_id=SealedHoldoutManifest.dataset_identity(
                artifact.sha256
            ),
            split_identity=SealedHoldoutManifest.split_identity_for(
                row_identity=sealed_rows,
                starts_at_utc=relabelled_start,
                ends_at_utc=relabelled_end,
                predecessor_holdout_id=None,
            ),
            row_identity=sealed_rows,
            starts_at_utc=relabelled_start,
            ends_at_utc=relabelled_end,
        )
        with self.assertRaises(TransitionError):
            self.writer.record_holdout_seal(
                manifest=relabelled_same_rows,
                operation_id="reject-relabelled-holdout-rows",
            )
        second_root_artifact = self.writer.evidence.finalize(
            b"synthetic duplicate root holdout"
        )
        duplicate_rows = SealedHoldoutManifest.rows_identity(
            artifact_sha256=second_root_artifact.sha256,
            size_bytes=second_root_artifact.size_bytes,
        )
        duplicate_start = "2026-07-11T00:00:00Z"
        duplicate_end = "2026-07-20T00:00:00Z"
        duplicate_root = SealedHoldoutManifest(
            artifact_sha256=second_root_artifact.sha256,
            size_bytes=second_root_artifact.size_bytes,
            data_receipt_id=SealedHoldoutManifest.dataset_identity(
                second_root_artifact.sha256
            ),
            split_identity=SealedHoldoutManifest.split_identity_for(
                row_identity=duplicate_rows,
                starts_at_utc=duplicate_start,
                ends_at_utc=duplicate_end,
                predecessor_holdout_id=None,
            ),
            row_identity=duplicate_rows,
            starts_at_utc=duplicate_start,
            ends_at_utc=duplicate_end,
        )
        with self.assertRaises(TransitionError):
            self.writer.record_holdout_seal(
                manifest=duplicate_root,
                operation_id="reject-duplicate-holdout-root",
            )
        state_before = self.writer.read_control()
        assert state_before is not None
        self.assertNotIn("synthetic", str(sealed))
        self.assertFalse(hasattr(type(self.writer.evidence), "_read_verified"))
        self.assertEqual(state_before["scientific"]["holdout_reveals"], 0)

        with self.assertRaises(PermitError):
            self.writer.issue_permit(
                kind=PermitKind.HOLDOUT,
                subject_kind=SubjectKind.EXECUTABLE,
                subject_id=executable_id,
                input_hash=artifact.sha256,
                actions=("reveal_holdout",),
                scope=(f"executable:{executable_id}",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="reject-artifact-only-holdout-permit",
            )

        result_name = "evidence/holdout-result"
        measurement_name = "evidence/holdout-measurement"
        evaluation_spec = job_spec(
            self.writer, {"kind": "Executable", "id": executable_id}
        )
        evaluation_spec["input_hashes"] = [
            *evaluation_spec["input_hashes"],  # type: ignore[list-item]
            sealed.identity.removeprefix("holdout:"),
            ENGINEERING_RUNTIME_PLAN_HASH,
        ]
        evaluation_spec["expected_outputs"] = [result_name, measurement_name]
        evaluation_spec["output_classes"] = {
            result_name: "durable_evidence",
            measurement_name: "durable_evidence",
        }
        evaluation_spec["scientific_binding"] = {
            "evidence_depth": "confirmation",
            "evidence_modes": [
                "causal_contrast",
                "cost_and_execution",
                "sensitivity_or_stress",
            ],
            "planned_claims": ["final_forward_metric"],
            "result_manifest_output": result_name,
            "validation_plan_hash": ENGINEERING_RUNTIME_PLAN_HASH,
            "validator_id": ENGINEERING_VALIDATOR_ID,
        }
        evaluation_spec["holdout_binding"] = {"holdout_id": sealed.identity}
        declared = self.writer.declare_job(
            spec=evaluation_spec, operation_id="declare-holdout-evaluation"
        )
        job_permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=declared.result["job_id"],
            input_hash=declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="issue-holdout-job-permit",
        )
        permit = self.writer.issue_permit(
            kind=PermitKind.HOLDOUT,
            subject_kind=SubjectKind.EXECUTABLE,
            subject_id=executable_id,
            input_hash=sealed.identity.removeprefix("holdout:"),
            actions=("reveal_holdout",),
            scope=(
                sealed.identity,
                f"candidate:{frozen.result['candidate_id']}",
                f"executable:{executable_id}",
            ),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="issue-holdout-permit",
        )
        self.writer.start_job(
            permit=job_permit, operation_id="start-holdout-evaluation"
        )
        values = self.writer.reveal_holdout_values(
            permit=permit,
            executable_id=executable_id,
            operation_id="reveal-once",
        )
        self.assertEqual(values, b"synthetic sealed values")
        self.assertEqual(self.writer.read_control()["scientific"]["holdout_reveals"], 1)  # type: ignore[index]
        with self.assertRaises(PermitError):
            self.writer.reveal_holdout_values(
                permit=permit,
                executable_id=executable_id,
                operation_id="reveal-once",
            )
        with self.assertRaises((PermitError, TransitionError)):
            self.writer.reveal_holdout_values(
                permit=permit,
                executable_id=executable_id,
                operation_id="reveal-replay",
            )
        with self.assertRaises(TransitionError):
            self.writer.dispose_candidate(
                disposition="rejected",
                reason="holdout-directed retune is forbidden",
                operation_id="reject-post-holdout-retune",
            )

    def test_candidate_refreeze_advances_activation_and_stales_old_permit(self) -> None:
        self.writer.open_mission(
            mission_id="MIS-REFREEZE",
            goal=mission_goal("candidate reactivation"),
            operation_id="refreeze-mission",
        )
        executable = executable_spec("reactivation")
        first = self.writer.freeze_candidate(
            executable=executable,
            evidence_refs=("engineering-evidence-one",),
            operation_id="freeze-first-activation",
        )
        executable_id = first.result["executable_id"]
        old_permit = self.writer.issue_permit(
            kind=PermitKind.RUNTIME,
            subject_kind=SubjectKind.EXECUTABLE,
            subject_id=executable_id,
            input_hash=digest("runtime", {"activation": 1}),
            actions=("start_runtime",),
            scope=(
                f"depth:{EvidenceDepth.EXECUTION_PROOF.value}",
                f"executable:{executable_id}",
            ),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=False,
            operation_id="issue-first-activation-runtime-permit",
        )
        self.writer.dispose_candidate(
            disposition="returned_to_library",
            reason="new independent evidence is available",
            operation_id="dispose-first-activation",
        )
        second = self.writer.freeze_candidate(
            executable=executable,
            evidence_refs=("engineering-evidence-two",),
            operation_id="freeze-second-activation",
        )
        self.assertNotEqual(first.result["candidate_id"], second.result["candidate_id"])
        with LocalIndex(self.writer.index_path) as index:
            self.assertEqual(index.event_head(f"candidate:{executable_id}").sequence, 3)  # type: ignore[union-attr]
        with self.assertRaises((PermitError, TransitionError)):
            self.writer.validate_runtime_entry(
                permit=old_permit,
                executable_id=executable_id,
                input_hash=old_permit.input_hash,
                action="start_runtime",
                depth=EvidenceDepth.EXECUTION_PROOF,
                operation_id="reject-old-candidate-activation",
            )

    def test_candidate_disposition_routes_through_current_initiative_state(self) -> None:
        self.open_mission_and_initiative()
        snapshot = PortfolioSnapshot(
            mission_id="MIS-FIXTURE",
            axes=(
                PortfolioAxis(
                    axis_id="candidate-route-axis-a",
                    causal_question="Does candidate route axis A carry information?",
                    mechanism_family="candidate-route-family-a",
                ),
                PortfolioAxis(
                    axis_id="candidate-route-axis-b",
                    causal_question="Does candidate route axis B carry information?",
                    mechanism_family="candidate-route-family-b",
                ),
            ),
            opportunity_cost_basis="preserve a coherent post-candidate route",
        )
        self.writer.record_portfolio_snapshot(
            snapshot=snapshot, operation_id="candidate-route-snapshot"
        )
        executable = executable_spec("candidate-route")
        self.writer.freeze_candidate(
            executable=executable,
            evidence_refs=("engineering-route-evidence-one",),
            operation_id="candidate-route-freeze-with-initiative",
        )
        self.writer.dispose_candidate(
            disposition="returned_to_library",
            reason="compare the current Portfolio",
            operation_id="candidate-route-dispose-with-initiative",
        )
        state = self.writer.read_control()
        assert state is not None
        self.assertEqual(
            state["next_action"],
            {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": snapshot.identity,
            },
        )

        self.writer.close_initiative(
            outcome="engineering_fixture_complete",
            operation_id="candidate-route-close-initiative",
        )
        self.writer.freeze_candidate(
            executable=executable,
            evidence_refs=("engineering-route-evidence-two",),
            operation_id="candidate-route-freeze-without-initiative",
        )
        self.writer.dispose_candidate(
            disposition="returned_to_library",
            reason="a new Initiative must own the next decision",
            operation_id="candidate-route-dispose-without-initiative",
        )
        state = self.writer.read_control()
        assert state is not None
        self.assertEqual(
            state["next_action"],
            {"kind": "open_initiative", "mission_id": "MIS-FIXTURE"},
        )
        decision = PortfolioDecision(
            decision_id="DEC-CANDIDATE-ROUTE",
            chosen_option_id="route-a",
            options=(
                DecisionOption(
                    option_id="route-a",
                    action=PortfolioAction.DEEPEN,
                    target_id="candidate-route-axis-a",
                    expected_information_value="positive",
                    opportunity_cost="bounded",
                ),
                DecisionOption(
                    option_id="route-b",
                    action=PortfolioAction.CONTRAST,
                    target_id="candidate-route-axis-b",
                    expected_information_value="positive",
                    opportunity_cost="bounded",
                    omission_reason="a new Initiative must open first",
                ),
            ),
            rationale="exercise the Initiative ownership boundary",
            commitment_batches=1,
        )
        with self.assertRaises(TransitionError):
            self.writer.record_portfolio_decision(
                decision=decision,
                operation_id="reject-candidate-route-without-initiative",
            )

    def test_release_basis_is_derived_only_from_runtime_bound_jobs(self) -> None:
        self.writer.open_mission(
            mission_id="MIS-RELEASE-PROOF",
            goal=mission_goal("release provenance"),
            operation_id="release-proof-mission",
        )
        executable = executable_spec("release-proof")
        frozen = self.writer.freeze_candidate(
            executable=executable,
            evidence_refs=("engineering-candidate-evidence",),
            operation_id="release-proof-candidate",
        )
        executable_id = frozen.result["executable_id"]
        candidate_id = frozen.result["candidate_id"]

        generic_spec = job_spec(
            self.writer, {"kind": "Executable", "id": executable_id}
        )
        generic_spec["expected_outputs"] = ["evidence/generic-proof"]
        generic_spec["output_classes"] = {"evidence/generic-proof": "durable_evidence"}
        generic = self.writer.declare_job(
            spec=generic_spec, operation_id="declare-generic-release-forgery"
        )
        generic_permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=generic.result["job_id"],
            input_hash=generic.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="permit-generic-release-forgery",
        )
        self.writer.start_job(
            permit=generic_permit, operation_id="start-generic-release-forgery"
        )
        generic_artifact = self.writer.evidence.finalize(b"generic durable artifact")
        generic_completion = self.writer.complete_job(
            outcome="success",
            output_manifest={"evidence/generic-proof": generic_artifact.sha256},
            operation_id="complete-generic-release-forgery",
        )
        with self.assertRaises(TransitionError):
            self.writer.validate_release_basis_fixture(
                executable_id=executable_id,
                candidate_id=candidate_id,
                completion_record_ids=(
                    generic_completion.result["completion_record_id"],
                ),
            )

        def run_runtime_job(
            depth: EvidenceDepth,
            tag: str,
            roles: tuple[str, ...],
            prior_role_hashes: dict[str, str],
        ) -> tuple[str, dict[str, str]]:
            output_name = f"evidence/{tag}"
            spec = runtime_job_spec(
                writer=self.writer,
                executable_id=executable_id,
                depth=depth,
                output_name=output_name,
                artifact_roles=roles,
            )
            declared = self.writer.declare_job(
                spec=spec,
                operation_id=f"declare-{tag}",
            )
            job_permit = self.writer.issue_permit(
                kind=PermitKind.JOB,
                subject_kind=SubjectKind.JOB,
                subject_id=declared.result["job_id"],
                input_hash=declared.result["job_hash"],
                actions=("start_job",),
                scope=("job",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id=f"permit-job-{tag}",
            )
            action = (
                "run_execution_proof"
                if depth is EvidenceDepth.EXECUTION_PROOF
                else "materialize"
            )
            runtime_permit = self.writer.issue_permit(
                kind=PermitKind.RUNTIME,
                subject_kind=SubjectKind.EXECUTABLE,
                subject_id=executable_id,
                input_hash=declared.result["job_hash"],
                actions=(action,),
                scope=(
                    f"candidate:{candidate_id}",
                    f"depth:{depth.value}",
                    f"executable:{executable_id}",
                    f"job:{declared.result['job_id']}",
                ),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=False,
                operation_id=f"permit-runtime-{tag}",
            )
            self.writer.start_job(
                permit=job_permit,
                runtime_permit=runtime_permit,
                operation_id=f"start-{tag}",
            )
            entry = self.writer.validate_runtime_entry(
                permit=runtime_permit,
                executable_id=executable_id,
                input_hash=declared.result["job_hash"],
                action=action,
                depth=depth,
                operation_id=f"runtime-entry-{tag}",
            )
            self.assertEqual(entry.result["permit_id"], runtime_permit.permit_id)
            binding = spec["runtime_binding"]
            assert isinstance(binding, dict)
            result_name = binding["result_manifest_output"]
            measurement_name = f"{output_name}-measurement"
            claims = (
                sorted(REQUIRED_PARITY)
                if depth is EvidenceDepth.EXECUTION_PROOF
                else sorted(REQUIRED_CASES)
            )
            measurement = self.writer.evidence.finalize(
                canonical_bytes(
                    {
                        "claims": claims,
                        "schema": "engineering_runtime_measurement.v1",
                    }
                )
            )
            role_outputs = binding["artifact_roles"]
            assert isinstance(role_outputs, dict)
            role_hashes = dict(prior_role_hashes)
            output_manifest = {measurement_name: measurement.sha256}
            for role, role_output in role_outputs.items():
                if role == "local_handoff_manifest":
                    continue
                role_artifact = self.writer.evidence.finalize(
                    canonical_bytes(
                        {"role": role, "schema": "engineering_runtime_role.v1"}
                    )
                )
                output_manifest[role_output] = role_artifact.sha256
                role_hashes[role] = role_artifact.sha256
            if "local_handoff_manifest" in role_outputs:
                control = self.writer.read_control()
                assert control is not None
                handoff = self.writer.evidence.finalize(
                    canonical_bytes(
                        {
                            "artifact_roles": dict(sorted(role_hashes.items())),
                            "authority_manifest_digest": control["authority"][
                                "manifest_digest"
                            ],
                            "candidate_id": candidate_id,
                            "executable_id": executable_id,
                            "mission_id": "MIS-RELEASE-PROOF",
                            "schema": "axiom_local_handoff.v1",
                            "source_receipt_ids": [],
                        }
                    )
                )
                output_manifest[
                    role_outputs["local_handoff_manifest"]
                ] = handoff.sha256
                role_hashes["local_handoff_manifest"] = handoff.sha256
            manifest = {
                "schema": "runtime_job_evidence.v1",
                "action": action,
                "candidate_id": candidate_id,
                "evidence_depth": depth.value,
                "executable_id": executable_id,
                "job_hash": declared.result["job_hash"],
                "job_id": declared.result["job_id"],
                "mission_id": "MIS-RELEASE-PROOF",
                "observations": [
                    {
                        "claim_id": claim,
                        "measurement_artifact_hash": measurement.sha256,
                        "status": "caller_reported",
                    }
                    for claim in claims
                ],
                "runtime_permit_id": runtime_permit.permit_id,
            }
            if depth is EvidenceDepth.EXECUTION_PROOF:
                arbitrary = self.writer.evidence.finalize(b"not runtime evidence")
                with self.assertRaises(TransitionError):
                    self.writer.complete_job(
                        outcome="success",
                        output_manifest={
                            **output_manifest,
                            result_name: arbitrary.sha256,
                        },
                        operation_id="reject-arbitrary-runtime-bytes",
                    )
            result_artifact = self.writer.evidence.finalize(canonical_bytes(manifest))
            completed = self.writer.complete_job(
                outcome="success",
                output_manifest={
                    **output_manifest,
                    result_name: result_artifact.sha256,
                },
                operation_id=f"complete-{tag}",
            )
            with self.assertRaises(TransitionError):
                self.writer.validate_runtime_entry(
                    permit=runtime_permit,
                    executable_id=executable_id,
                    input_hash=declared.result["job_hash"],
                    action=action,
                    depth=depth,
                    operation_id=f"reject-reentry-{tag}",
                )
            return completed.result["completion_record_id"], role_hashes

        execution_roles = ("native_execution_report", "parity_report")
        execution_completion, execution_role_hashes = run_runtime_job(
            EvidenceDepth.EXECUTION_PROOF,
            "execution-proof",
            execution_roles,
            {},
        )
        materialization_roles = tuple(
            sorted(REQUIRED_RELEASE_ARTIFACT_ROLES - set(execution_roles))
        )
        materialization_completion, all_role_hashes = run_runtime_job(
            EvidenceDepth.MATERIALIZATION,
            "materialization",
            materialization_roles,
            execution_role_hashes,
        )
        basis = self.writer.validate_release_basis_fixture(
            executable_id=executable_id,
            candidate_id=candidate_id,
            completion_record_ids=(
                execution_completion,
                materialization_completion,
            ),
        )
        self.assertEqual(set(basis["parity_surfaces"]), REQUIRED_PARITY)
        self.assertEqual(set(basis["materialization_cases"]), REQUIRED_CASES)
        self.assertEqual(basis["artifact_roles"], dict(sorted(all_role_hashes.items())))
        self.assertEqual(len(basis["artifact_hashes"]), 14)
        with LocalIndex(self.writer.index_path) as index:
            self.assertIsNone(index.get("release-declared", "REL-FIXTURE"))

    def test_pending_positive_terminal_allows_only_frozen_release_invalidation(
        self,
    ) -> None:
        self.writer.open_mission(
            mission_id="MIS-RELEASE-WITHDRAWAL",
            goal=mission_goal("frozen Release withdrawal"),
            operation_id="release-withdrawal-mission",
        )
        executable = executable_spec("release-withdrawal")
        candidate = self.writer.freeze_candidate(
            executable=executable,
            evidence_refs=("engineering-release-withdrawal-evidence",),
            operation_id="release-withdrawal-candidate",
        )
        release_id = "REL-FROZEN-WITHDRAWAL"

        def seed_frozen_release(current, _index):
            assert current is not None
            body = self.writer._body(current)
            body["scientific"]["active_release"] = {
                "id": release_id,
                "status": "frozen",
                "candidate_id": candidate.result["candidate_id"],
                "executable_id": executable.identity,
            }
            body["next_action"] = {
                "kind": "close_mission",
                "outcome": "completed_pre_live_handoff",
                "basis_record_id": release_id,
            }
            release = IndexRecord(
                kind="release",
                record_id=release_id,
                subject=f"Executable:{executable.identity}",
                status="frozen",
                fingerprint="f" * 64,
                payload={
                    "candidate_id": candidate.result["candidate_id"],
                    "executable_id": executable.identity,
                    "mission_id": "MIS-RELEASE-WITHDRAWAL",
                },
                event_stream=f"release:{release_id}",
                event_sequence=1,
            )
            return body, [release], {"release_id": release_id}

        self.writer._commit(
            event_kind="fixture_frozen_release_seeded",
            operation_id="seed-frozen-release-withdrawal",
            subject=f"Release:{release_id}",
            payload={"release_id": release_id},
            prepare=seed_frozen_release,
        )
        with self.assertRaises(TransitionError):
            self.writer.record_work_result(
                work={
                    "callable_identity": "fixture.unrelated",
                    "input_identity": "fixture.unrelated.input",
                },
                outcome="success",
                details={"scope": "must remain blocked"},
                operation_id="reject-unrelated-positive-terminal-transition",
            )
        disposed = self.writer.abandon_release(
            release_id=release_id,
            disposition="invalidated",
            reason="final Release revalidation failed",
            operation_id="invalidate-frozen-positive-basis",
        )
        self.assertEqual(disposed.result["disposition"], "invalidated")
        state = self.writer.read_control()
        assert state is not None
        self.assertIsNone(state["scientific"]["active_release"])
        self.assertEqual(
            state["next_action"],
            {
                "kind": "plan_candidate_bound_evidence",
                "executable_id": executable.identity,
            },
        )

    def test_evidence_finalize_crash_is_reusable_repair_surface(self) -> None:
        self.writer.open_mission(
            mission_id="MIS-CRASH",
            goal=mission_goal("crash recovery"),
            operation_id="crash-mission",
        )
        declared = self.writer.declare_job(
            spec=job_spec(self.writer, {"kind": "Mission", "id": "MIS-CRASH"}),
            operation_id="crash-job",
        )
        permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=declared.result["job_id"],
            input_hash=declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="crash-job-permit",
        )
        self.writer.start_job(permit=permit, operation_id="crash-job-start")
        revision = self.writer.read_control()["revision"]  # type: ignore[index]
        transient = self.root / "local" / "jobs" / "fixture" / "fixture.json"
        transient.parent.mkdir(parents=True, exist_ok=True)
        transient.write_bytes(b"sealed fixture output")
        evidence_root = self.root / "local" / "evidence"
        before_crash = {item for item in evidence_root.rglob("*") if item.is_file()}
        with self.assertRaises(InjectedCrash):
            self.writer.complete_job(
                outcome="success",
                output_manifest={
                    "local/jobs/fixture/fixture.json": sha256(
                        b"sealed fixture output"
                    ).hexdigest()
                },
                evidence_blobs=(b"same evidence",),
                operation_id="crash-complete",
                crash_after="after_evidence",
            )
        self.assertEqual(self.writer.read_control()["revision"], revision)  # type: ignore[index]
        after_crash = {item for item in evidence_root.rglob("*") if item.is_file()}
        self.assertEqual(len(after_crash - before_crash), 1)
        completed = self.writer.complete_job(
            outcome="success",
            output_manifest={
                "local/jobs/fixture/fixture.json": sha256(
                    b"sealed fixture output"
                ).hexdigest()
            },
            evidence_blobs=(b"same evidence",),
            operation_id="crash-complete",
        )
        self.assertFalse(completed.reused)
        after_resume = {item for item in evidence_root.rglob("*") if item.is_file()}
        self.assertEqual(after_resume, after_crash)

    def test_first_job_requires_content_addressed_implementation_evidence(self) -> None:
        self.writer.open_mission(
            mission_id="MIS-IMPLEMENTATION-EVIDENCE",
            goal=mission_goal("implementation evidence boundary"),
            operation_id="implementation-evidence-mission",
        )
        absent = job_spec(
            self.writer,
            {"kind": "Mission", "id": "MIS-IMPLEMENTATION-EVIDENCE"},
        )
        absent["implementation_identity"] = "f" * 64
        with self.assertRaises(TransitionError):
            self.writer.declare_job(
                spec=absent, operation_id="reject-absent-implementation-manifest"
            )

        missing_source_manifest = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "artifact_hashes": ["e" * 64],
                    "callable_identity": absent["callable_identity"],
                    "protocol": "python.source.fixture.v1",
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        missing_source = dict(absent)
        missing_source["implementation_identity"] = missing_source_manifest.sha256
        with self.assertRaises(TransitionError):
            self.writer.declare_job(
                spec=missing_source,
                operation_id="reject-missing-implementation-source",
            )

        valid = job_spec(
            self.writer,
            {"kind": "Mission", "id": "MIS-IMPLEMENTATION-EVIDENCE"},
        )
        declared = self.writer.declare_job(
            spec=valid, operation_id="accept-bound-implementation-evidence"
        )
        self.assertTrue(declared.result["job_id"].startswith("job:"))

    def test_failed_job_requires_bound_reproduction_and_resume_evidence(self) -> None:
        self.writer.open_mission(
            mission_id="MIS-FAILURE",
            goal=mission_goal("structured failure"),
            operation_id="failure-mission",
        )
        declared = self.writer.declare_job(
            spec=job_spec(
                self.writer, {"kind": "Mission", "id": "MIS-FAILURE"}
            ),
            operation_id="failure-job",
        )
        permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=declared.result["job_id"],
            input_hash=declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="failure-job-permit",
        )
        self.writer.start_job(permit=permit, operation_id="failure-job-start")
        with self.assertRaises(TransitionError):
            self.writer.complete_job(
                outcome="failed",
                output_manifest={},
                operation_id="reject-unexplained-failure",
            )
        reproduction = self.writer.evidence.finalize(b"minimum failure reproduction")
        completed = self.writer.complete_job(
            outcome="failed",
            output_manifest={},
            failure={
                "failure_kind": "engineering",
                "minimum_reproduction_evidence": [reproduction.sha256],
                "root_cause": "fixture callable rejected its input",
                "interrupted_action": "fixture.callable",
                "resume_action": "resume_fixture_job",
            },
            operation_id="record-structured-failure",
        )
        self.assertEqual(completed.result["outcome"], "failed")
        self.assertIsNone(self.writer.read_control()["scientific"]["active_job"])  # type: ignore[index]
        changed_budget = job_spec(
            self.writer, {"kind": "Mission", "id": "MIS-FAILURE"}
        )
        changed_budget["budget"] = {
            "compute_seconds": 31,
            "wall_seconds": 30,
            "trials": 1,
        }
        with self.assertRaises(IdenticalFailedRetryError):
            self.writer.declare_job(
                spec=changed_budget,
                operation_id="reject-budget-only-failed-retry",
            )
        changed_timeout = job_spec(
            self.writer, {"kind": "Mission", "id": "MIS-FAILURE"}
        )
        changed_timeout["timeout_or_stop_rule"] = "stop_at_31_seconds"
        with self.assertRaises(IdenticalFailedRetryError):
            self.writer.declare_job(
                spec=changed_timeout,
                operation_id="reject-timeout-only-failed-retry",
            )
        cosmetic_retry = job_spec(
            self.writer, {"kind": "Mission", "id": "MIS-FAILURE"}
        )
        cosmetic_retry["log_path"] = "local/jobs/cosmetic-retry.log"
        cosmetic_retry["expected_outputs"] = [
            "local/jobs/fixture/cosmetic-retry.json"
        ]
        cosmetic_retry["output_classes"] = {
            "local/jobs/fixture/cosmetic-retry.json": "transient"
        }
        with self.assertRaises(IdenticalFailedRetryError):
            self.writer.declare_job(
                spec=cosmetic_retry,
                operation_id="reject-cosmetic-failed-retry",
            )
        previous_implementation = cosmetic_retry["implementation_identity"]
        previous_artifact = self.writer.evidence.verify(previous_implementation)
        previous_manifest = parse_canonical(
            (
                self.writer.evidence._root / previous_artifact.relative_path
            ).read_bytes()
        )
        assert isinstance(previous_manifest, dict)
        protocol_only_manifest = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    **previous_manifest,
                    "protocol": "python.source.fixture.cosmetic.v2",
                }
            )
        )
        protocol_only_proof = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "changed_dimension": "implementation",
                    "explanation": "only the manifest protocol label changed",
                    "new_evidence_hashes": [
                        protocol_only_manifest.sha256,
                        *previous_manifest["artifact_hashes"],
                    ],
                    "new_implementation_identity": protocol_only_manifest.sha256,
                    "prior_failure_signature": completed.result[
                        "failure_signature"
                    ],
                    "previous_implementation_identity": previous_implementation,
                    "schema": "job_changed_cause.v1",
                }
            )
        )
        protocol_only_retry = dict(cosmetic_retry)
        protocol_only_retry["implementation_identity"] = protocol_only_manifest.sha256
        protocol_only_retry["changed_cause_proof_hash"] = protocol_only_proof.sha256
        with self.assertRaises(IdenticalFailedRetryError):
            self.writer.declare_job(
                spec=protocol_only_retry,
                operation_id="reject-protocol-only-failed-retry",
            )
        second_source = self.writer.evidence.finalize(
            b"second implementation source used for ordering guard"
        )
        unordered_hashes = sorted(
            [*previous_manifest["artifact_hashes"], second_source.sha256],
            reverse=True,
        )
        unordered_manifest = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    **previous_manifest,
                    "artifact_hashes": unordered_hashes,
                }
            )
        )
        unordered_retry = dict(cosmetic_retry)
        unordered_retry["implementation_identity"] = unordered_manifest.sha256
        with self.assertRaises(TransitionError):
            self.writer.declare_job(
                spec=unordered_retry,
                operation_id="reject-unordered-implementation-manifest",
            )
        changed_source = self.writer.evidence.finalize(
            b"repaired fixture callable implementation source"
        )
        changed_evidence = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "artifact_hashes": [changed_source.sha256],
                    "callable_identity": cosmetic_retry["callable_identity"],
                    "protocol": "python.source.fixture.v1",
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        cosmetic_retry["implementation_identity"] = changed_evidence.sha256
        changed = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "changed_dimension": "implementation",
                    "explanation": "fixture callable implementation was repaired",
                    "new_evidence_hashes": [
                        changed_evidence.sha256,
                        changed_source.sha256,
                    ],
                    "new_implementation_identity": changed_evidence.sha256,
                    "prior_failure_signature": completed.result[
                        "failure_signature"
                    ],
                    "previous_implementation_identity": previous_implementation,
                    "schema": "job_changed_cause.v1",
                }
            )
        )
        cosmetic_retry["changed_cause_proof_hash"] = changed.sha256
        retried = self.writer.declare_job(
            spec=cosmetic_retry,
            operation_id="allow-changed-cause-retry",
        )
        self.assertNotEqual(retried.result["job_id"], declared.result["job_id"])

    def test_success_cache_requires_present_hash_bound_reusable_outputs(self) -> None:
        self.writer.open_mission(
            mission_id="MIS-SUCCESS-CACHE",
            goal=mission_goal("successful Job cache"),
            operation_id="success-cache-mission",
        )
        spec = job_spec(
            self.writer, {"kind": "Mission", "id": "MIS-SUCCESS-CACHE"}
        )
        declared = self.writer.declare_job(
            spec=spec, operation_id="success-cache-declare"
        )
        permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=declared.result["job_id"],
            input_hash=declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="success-cache-permit",
        )
        self.writer.start_job(permit=permit, operation_id="success-cache-start")
        output_name = spec["expected_outputs"][0]
        target = self.root / output_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"successful cache output")
        completed = self.writer.complete_job(
            outcome="success",
            output_manifest={
                output_name: sha256(b"successful cache output").hexdigest()
            },
            operation_id="success-cache-complete",
        )
        self.assertFalse(target.exists())
        with self.assertRaises(RecoveryRequired):
            self.writer.declare_job(
                spec=spec, operation_id="reject-deleted-transient-cache"
            )

        cache_spec = job_spec(
            self.writer, {"kind": "Mission", "id": "MIS-SUCCESS-CACHE"}
        )
        cache_name = "local/cache/fixture/reproducible.bin"
        cache_spec["expected_outputs"] = [cache_name]
        cache_spec["output_classes"] = {cache_name: "reproducible_cache"}
        cache_declared = self.writer.declare_job(
            spec=cache_spec, operation_id="reproducible-cache-declare"
        )
        cache_permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=cache_declared.result["job_id"],
            input_hash=cache_declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="reproducible-cache-permit",
        )
        self.writer.start_job(
            permit=cache_permit, operation_id="reproducible-cache-start"
        )
        cache_target = self.root / cache_name
        cache_target.parent.mkdir(parents=True, exist_ok=True)
        cache_content = b"reproducible cache output"
        cache_target.write_bytes(cache_content)
        cache_completed = self.writer.complete_job(
            outcome="success",
            output_manifest={cache_name: sha256(cache_content).hexdigest()},
            operation_id="reproducible-cache-complete",
        )
        control_before_reuse = self.writer.read_control()
        journal_before_reuse = self.writer.journal.tail()[0]
        with LocalIndex(self.writer.index_path) as index:
            count_before_reuse = index.record_count()
            operations_before_reuse = len(index.records_by_kind("operation"))
        for ordinal in (1, 2):
            reused = self.writer.declare_job(
                spec=cache_spec, operation_id=f"reproducible-cache-reuse-{ordinal}"
            )
            self.assertTrue(reused.reused)
            self.assertEqual(reused.result["disposition"], "reuse_success")
            self.assertEqual(
                reused.result["completion_record_id"],
                cache_completed.result["completion_record_id"],
            )
        self.assertEqual(self.writer.read_control(), control_before_reuse)
        self.assertEqual(self.writer.journal.tail()[0], journal_before_reuse)
        with LocalIndex(self.writer.index_path) as index:
            self.assertEqual(index.record_count(), count_before_reuse)
            self.assertEqual(
                len(index.records_by_kind("operation")), operations_before_reuse
            )
        cache_target.write_bytes(b"tampered cache output")
        with self.assertRaises(RecoveryRequired):
            self.writer.declare_job(
                spec=cache_spec, operation_id="reject-hash-mismatched-cache"
            )
        cache_target.unlink()
        with self.assertRaises(RecoveryRequired):
            self.writer.declare_job(
                spec=cache_spec, operation_id="reject-deleted-reproducible-cache"
            )

        durable_spec = job_spec(
            self.writer, {"kind": "Mission", "id": "MIS-SUCCESS-CACHE"}
        )
        durable_name = "evidence/durable-cache-output"
        durable_spec["expected_outputs"] = [durable_name]
        durable_spec["output_classes"] = {durable_name: "durable_evidence"}
        durable_declared = self.writer.declare_job(
            spec=durable_spec, operation_id="durable-cache-declare"
        )
        durable_permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=durable_declared.result["job_id"],
            input_hash=durable_declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="durable-cache-permit",
        )
        self.writer.start_job(
            permit=durable_permit, operation_id="durable-cache-start"
        )
        durable_artifact = self.writer.evidence.finalize(b"durable cache evidence")
        durable_completed = self.writer.complete_job(
            outcome="success",
            output_manifest={durable_name: durable_artifact.sha256},
            operation_id="durable-cache-complete",
        )
        durable_reuse = self.writer.declare_job(
            spec=durable_spec, operation_id="durable-cache-reuse"
        )
        self.assertEqual(
            durable_reuse.result["completion_record_id"],
            durable_completed.result["completion_record_id"],
        )
        durable_path = self.writer.evidence._root / durable_artifact.relative_path
        durable_path.write_bytes(b"tampered durable cache evidence")
        with self.assertRaises(RecoveryRequired):
            self.writer.declare_job(
                spec=durable_spec, operation_id="reject-tampered-durable-cache"
            )
        durable_path.unlink()
        with self.assertRaises(RecoveryRequired):
            self.writer.declare_job(
                spec=durable_spec, operation_id="reject-deleted-durable-cache"
            )


class ScientificLifecycleTests(unittest.TestCase):
    def _declare_and_start_scientific_job(
        self,
        *,
        writer: StateWriter,
        executable_id: str,
        plan_hash: str,
        depth: str,
        claim_id: str,
        tag: str,
        holdout_id: str | None = None,
        evidence_modes: tuple[str, ...] = (
            "causal_contrast",
            "cost_and_execution",
            "sensitivity_or_stress",
        ),
    ):
        spec = job_spec(writer, {"kind": "Executable", "id": executable_id})
        result_name = f"evidence/{tag}-result"
        measurement_name = f"evidence/{tag}-measurement"
        spec["input_hashes"] = [*spec["input_hashes"], plan_hash]
        if holdout_id is not None:
            spec["input_hashes"] = [
                *spec["input_hashes"],
                holdout_id.removeprefix("holdout:"),
            ]
            spec["holdout_binding"] = {"holdout_id": holdout_id}
        spec["expected_outputs"] = [result_name, measurement_name]
        spec["output_classes"] = {
            result_name: "durable_evidence",
            measurement_name: "durable_evidence",
        }
        spec["scientific_binding"] = {
            "evidence_depth": depth,
            "evidence_modes": sorted(evidence_modes),
            "planned_claims": [claim_id],
            "result_manifest_output": result_name,
            "validation_plan_hash": plan_hash,
            "validator_id": ScientificFixtureValidator.validator_id,
        }
        declared = writer.declare_job(
            spec=spec, operation_id=f"{tag}-declare"
        )
        permit = writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=declared.result["job_id"],
            input_hash=declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id=f"{tag}-permit",
        )
        writer.start_job(permit=permit, operation_id=f"{tag}-start")
        return spec, declared

    def _complete_scientific_job(
        self,
        *,
        writer: StateWriter,
        spec: dict[str, object],
        declared: object,
        executable_id: str,
        depth: str,
        claim_id: str,
        verdict: str,
        tag: str,
    ):
        candidate_eligible = verdict == "passed" and depth == "confirmation"
        measurement = writer.evidence.finalize(
            canonical_bytes(
                {
                    "candidate_eligible": candidate_eligible,
                    "claim_id": claim_id,
                    "executed_evidence_modes": list(
                        spec["scientific_binding"]["evidence_modes"]  # type: ignore[index]
                    ),
                    "schema": "scientific_boundary_measurement.v1",
                    "verdict": verdict,
                }
            )
        )
        result_name = spec["scientific_binding"]["result_manifest_output"]  # type: ignore[index]
        measurement_name = next(
            name
            for name in spec["expected_outputs"]  # type: ignore[union-attr]
            if name != result_name
        )
        result = writer.evidence.finalize(
            canonical_bytes(
                {
                    "evidence_depth": depth,
                    "executable_id": executable_id,
                    "job_hash": declared.result["job_hash"],
                    "job_id": declared.result["job_id"],
                    "mission_id": "MIS-HOLDOUT-LIFECYCLE",
                    "observations": [
                        {
                            "claim_id": claim_id,
                            "measurement_artifact_hash": measurement.sha256,
                        }
                    ],
                    "schema": "scientific_job_evidence.v1",
                }
            )
        )
        outcome = {
            "passed": "success",
            "failed": "failed",
            "not_evaluable": "not_evaluable",
        }[verdict]
        failure = None
        if outcome != "success":
            failure = {
                "failure_kind": (
                    "scientific_falsification"
                    if verdict == "failed"
                    else "not_evaluable"
                ),
                "minimum_reproduction_evidence": [measurement.sha256],
                "root_cause": f"fixture scientific verdict {verdict}",
                "interrupted_action": spec["callable_identity"],
                "resume_action": spec["resume_action"],
            }
        completed = writer.complete_job(
            outcome=outcome,
            output_manifest={
                result_name: result.sha256,
                measurement_name: measurement.sha256,
            },
            failure=failure,
            operation_id=f"{tag}-complete",
        )
        with LocalIndex(writer.index_path) as index:
            completion = index.get(
                "job-completed", completed.result["completion_record_id"]
            )
        assert completion is not None
        trace = completion.payload["scientific"]["validation_trace"]
        self.assertEqual(trace["declared_artifact_count"], 2)
        self.assertEqual(trace["opened_artifact_count"], 2)
        return completed

    def _build_frozen_candidate(self, root: str):
        validator = ScientificFixtureValidator()
        writer = StateWriter(
            root,
            permit_authority=PermitAuthority(b"h" * 32),
            clock=lambda: FIXED_NOW,
            foundation_root=REPO_ROOT,
            validation_registry=EvidenceValidatorRegistry((validator,)),
        )
        writer.initialize_ready()
        writer.open_mission(
            mission_id="MIS-HOLDOUT-LIFECYCLE",
            goal=mission_goal("holdout disposition lifecycle"),
            operation_id="holdout-life-mission",
        )
        writer.open_initiative(
            initiative_id="INI-HOLDOUT-LIFECYCLE",
            objective=initiative_objective("holdout disposition lifecycle"),
            operation_id="holdout-life-initiative",
        )
        axes = tuple(
            PortfolioAxis(
                axis_id=f"holdout-axis-{letter}",
                causal_question=f"Does holdout axis {letter} carry information?",
                mechanism_family=f"holdout-family-{letter}",
            )
            for letter in ("a", "b", "c")
        )
        snapshot = PortfolioSnapshot(
            mission_id="MIS-HOLDOUT-LIFECYCLE",
            axes=axes,
            opportunity_cost_basis="retain three independent holdout research axes",
            exhaustion_standard=exhaustion_standard(),
        )
        writer.record_portfolio_snapshot(
            snapshot=snapshot, operation_id="holdout-life-snapshot"
        )
        decision = PortfolioDecision(
            decision_id="DEC-HOLDOUT-LIFECYCLE",
            chosen_option_id="choose-a",
            options=(
                DecisionOption(
                    option_id="choose-a",
                    action=PortfolioAction.DEEPEN,
                    target_id=axes[0].axis_id,
                    expected_information_value="positive",
                    opportunity_cost="bounded",
                ),
                DecisionOption(
                    option_id="retain-b",
                    action=PortfolioAction.CONTRAST,
                    target_id=axes[1].axis_id,
                    expected_information_value="positive",
                    opportunity_cost="one Batch",
                    omission_reason="axis A is selected for confirmation",
                ),
            ),
            rationale="build one frozen candidate while retaining alternatives",
            commitment_batches=1,
        )
        writer.record_portfolio_decision(
            decision=decision, operation_id="holdout-life-decision"
        )
        question = study_question("holdout candidate evidence")
        proposal = {"mechanism": "holdout lifecycle boundary"}
        study_hash = writer.study_input_hash(
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            semantic_proposal=proposal,
            portfolio_axis_id=axes[0].axis_id,
            portfolio_axis_identity=axes[0].identity,
            portfolio_decision_id=decision.identity,
        )
        study_permit = writer.issue_permit(
            kind=PermitKind.STUDY,
            subject_kind=SubjectKind.INITIATIVE,
            subject_id="INI-HOLDOUT-LIFECYCLE",
            input_hash=study_hash,
            actions=("open_study",),
            scope=("study",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="holdout-life-study-permit",
        )
        opened = writer.open_study(
            study_id="STU-HOLDOUT-LIFECYCLE",
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            material_display_name="foundation observed material",
            semantic_proposal=proposal,
            portfolio_axis_id=axes[0].axis_id,
            portfolio_axis_identity=axes[0].identity,
            portfolio_decision_id=decision.identity,
            permit=study_permit,
            operation_id="holdout-life-study-open",
        )
        batch = batch_spec(
            batch_id="BAT-HOLDOUT-LIFECYCLE",
            study_id="STU-HOLDOUT-LIFECYCLE",
            study_hash=opened.result["study_hash"],
        )
        batch_permit = writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-HOLDOUT-LIFECYCLE",
            input_hash=batch.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="holdout-life-batch-permit",
        )
        writer.open_batch(
            batch_spec=batch,
            permit=batch_permit,
            operation_id="holdout-life-batch-open",
        )
        executable = scientific_executable_spec("holdout-lifecycle")
        writer.register_trial(
            executable=executable, operation_id="holdout-life-trial"
        )
        plan = writer.evidence.finalize(
            canonical_bytes({"schema": "scientific_boundary_plan.v1"})
        )
        completions = []
        for depth in ("discovery", "confirmation"):
            tag = f"holdout-life-{depth}"
            claim = f"{depth}-claim"
            spec, declared = self._declare_and_start_scientific_job(
                writer=writer,
                executable_id=executable.identity,
                plan_hash=plan.sha256,
                depth=depth,
                claim_id=claim,
                tag=tag,
            )
            completions.append(
                self._complete_scientific_job(
                    writer=writer,
                    spec=spec,
                    declared=declared,
                    executable_id=executable.identity,
                    depth=depth,
                    claim_id=claim,
                    verdict="passed",
                    tag=tag,
                )
            )
        writer.dispose_batch(
            outcome="completed", operation_id="holdout-life-batch-close"
        )
        writer.close_study(
            outcome="supported", operation_id="holdout-life-study-close"
        )
        writer.close_initiative(
            outcome="completed", operation_id="holdout-life-initiative-close"
        )
        candidate = writer.freeze_candidate(
            executable=executable,
            evidence_refs=tuple(
                completion.result["completion_record_id"]
                for completion in completions
            ),
            operation_id="holdout-life-candidate",
        )
        return writer, executable, candidate, plan

    def _exercise_future_development_reentry(
        self,
        *,
        writer: StateWriter,
        predecessor: SealedHoldoutManifest,
        successor: SealedHoldoutManifest,
        old_executable: ExecutableSpec,
        old_candidate_id: str,
        plan_hash: str,
    ) -> None:
        material_artifact = writer.evidence.finalize(
            b"genuinely later post-holdout development values"
        )
        development_start = "2026-07-10T01:00:00Z"
        development_end = "2026-07-10T23:00:00Z"
        material_identity = canonical_digest(
            domain="post-holdout-development-material",
            payload={
                "development_ends_at_utc": development_end,
                "development_starts_at_utc": development_start,
                "material_content_sha256": material_artifact.sha256,
                "predecessor_holdout_id": predecessor.identity,
                "successor_holdout_id": successor.identity,
            },
        )
        split_identity = canonical_digest(
            domain="post-holdout-development-split",
            payload={
                "development_ends_at_utc": development_end,
                "development_starts_at_utc": development_start,
                "material_identity": material_identity,
                "predecessor_holdout_id": predecessor.identity,
                "successor_holdout_id": successor.identity,
            },
        )
        material_receipt = writer.evidence.finalize(
            canonical_bytes(
                {
                    "development_ends_at_utc": development_end,
                    "development_starts_at_utc": development_start,
                    "material_content_sha256": material_artifact.sha256,
                    "material_identity": material_identity,
                    "mission_id": "MIS-HOLDOUT-LIFECYCLE",
                    "predecessor_holdout_id": predecessor.identity,
                    "schema": "post_holdout_development_material.v1",
                    "split_identity": split_identity,
                    "successor_holdout_id": successor.identity,
                    "successor_values_exposed": False,
                }
            )
        )
        registered = writer.register_future_development_material(
            material_receipt_hash=material_receipt.sha256,
            operation_id="failed-register-future-development",
        )
        self.assertEqual(
            writer.read_control()["next_action"],  # type: ignore[index]
            {
                "kind": "open_initiative",
                "mission_id": "MIS-HOLDOUT-LIFECYCLE",
            },
        )
        with LocalIndex(writer.index_path) as index:
            authority = index.get(
                "post-holdout-development",
                registered.result["post_holdout_development_id"],
            )
            development = index.get("development-material", material_identity)
            old_candidate = index.get("candidate", old_candidate_id)
            self.assertIsNone(index.event_head(f"holdout-reveal:{successor.identity}"))
        assert authority is not None and development is not None
        assert old_candidate is not None
        self.assertEqual(development.payload["material_content_sha256"], material_artifact.sha256)
        with self.assertRaises(TransitionError):
            writer.freeze_candidate(
                executable=old_executable,
                evidence_refs=tuple(old_candidate.payload["evidence_refs"]),
                operation_id="failed-reject-old-material-after-registration",
            )

        writer.open_initiative(
            initiative_id="INI-POST-HOLDOUT-DEVELOPMENT",
            objective=initiative_objective("post-holdout development"),
            operation_id="failed-open-post-holdout-initiative",
        )
        with LocalIndex(writer.index_path) as index:
            portfolio_head = index.event_head("portfolio:MIS-HOLDOUT-LIFECYCLE")
            assert portfolio_head is not None
            snapshot = index.get(portfolio_head.record_kind, portfolio_head.record_id)
        assert snapshot is not None
        axes = snapshot.payload["axes"]
        decision = PortfolioDecision(
            decision_id="DEC-POST-HOLDOUT-DEVELOPMENT",
            chosen_option_id="develop-a",
            options=(
                DecisionOption(
                    option_id="develop-a",
                    action=PortfolioAction.DEEPEN,
                    target_id=axes[0]["axis_id"],
                    expected_information_value="positive",
                    opportunity_cost="one bounded Batch",
                ),
                DecisionOption(
                    option_id="retain-b",
                    action=PortfolioAction.CONTRAST,
                    target_id=axes[1]["axis_id"],
                    expected_information_value="positive",
                    opportunity_cost="deferred",
                    omission_reason="new material first tests the selected causal axis",
                ),
            ),
            rationale="reenter the existing broad Portfolio on genuinely later material",
            commitment_batches=1,
        )
        writer.record_portfolio_decision(
            decision=decision,
            operation_id="failed-post-holdout-portfolio-decision",
        )
        question = study_question("post-holdout development material")
        proposal = {"mechanism": "post-holdout structural reentry"}
        study_hash = writer.study_input_hash(
            question=question,
            material_identity=material_identity,
            semantic_proposal=proposal,
            portfolio_axis_id=axes[0]["axis_id"],
            portfolio_axis_identity=axes[0]["axis_identity"],
            portfolio_decision_id=decision.identity,
        )
        study_permit = writer.issue_permit(
            kind=PermitKind.STUDY,
            subject_kind=SubjectKind.INITIATIVE,
            subject_id="INI-POST-HOLDOUT-DEVELOPMENT",
            input_hash=study_hash,
            actions=("open_study",),
            scope=("study",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="failed-post-holdout-study-permit",
        )
        opened = writer.open_study(
            study_id="STU-POST-HOLDOUT-DEVELOPMENT",
            question=question,
            material_identity=material_identity,
            material_display_name="registered later development material",
            semantic_proposal=proposal,
            permit=study_permit,
            operation_id="failed-post-holdout-study-open",
            portfolio_axis_id=axes[0]["axis_id"],
            portfolio_axis_identity=axes[0]["axis_identity"],
            portfolio_decision_id=decision.identity,
        )
        batch = batch_spec(
            batch_id="BAT-POST-HOLDOUT-DEVELOPMENT",
            study_id="STU-POST-HOLDOUT-DEVELOPMENT",
            study_hash=opened.result["study_hash"],
        )
        batch_permit = writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-POST-HOLDOUT-DEVELOPMENT",
            input_hash=batch.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="failed-post-holdout-batch-permit",
        )
        writer.open_batch(
            batch_spec=batch,
            permit=batch_permit,
            operation_id="failed-post-holdout-batch-open",
        )
        component = ComponentSpec(
            display_name="post-holdout scientific component",
            protocol="feature.post_holdout_boundary_fixture.v1",
            implementation="fixture.post_holdout.component",
            spec={"material_identity": material_identity},
        )
        new_executable = ExecutableSpec(
            display_name="post-holdout scientific executable",
            components=(component,),
            parameters={"material_identity": material_identity},
            data_contract=f"data:{material_identity}",
            split_contract=f"split:{split_identity}",
            clock_contract="clock:completed-m5-bar",
            cost_contract="cost:fixed-lot-boundary-fixture",
            engine_contract="engine:python-boundary-fixture",
        )
        counted = writer.register_trial(
            executable=new_executable,
            operation_id="failed-post-holdout-trial",
        )
        self.assertEqual(counted.result["trial_delta"], 1)
        completions = []
        for depth in ("discovery", "confirmation"):
            tag = f"failed-post-holdout-{depth}"
            claim = f"post-holdout-{depth}-claim"
            spec, declared = self._declare_and_start_scientific_job(
                writer=writer,
                executable_id=new_executable.identity,
                plan_hash=plan_hash,
                depth=depth,
                claim_id=claim,
                tag=tag,
            )
            completions.append(
                self._complete_scientific_job(
                    writer=writer,
                    spec=spec,
                    declared=declared,
                    executable_id=new_executable.identity,
                    depth=depth,
                    claim_id=claim,
                    verdict="passed",
                    tag=tag,
                )
            )
        writer.dispose_batch(
            outcome="completed",
            operation_id="failed-post-holdout-batch-close",
        )
        writer.close_study(
            outcome="supported",
            operation_id="failed-post-holdout-study-close",
        )
        writer.close_initiative(
            outcome="completed",
            operation_id="failed-post-holdout-initiative-close",
        )
        with LocalIndex(writer.index_path) as index:
            for completion in completions:
                completed_record = index.get(
                    "job-completed", completion.result["completion_record_id"]
                )
                assert completed_record is not None
                self.assertGreater(
                    completed_record.authority_sequence,
                    authority.authority_sequence,
                )
        frozen = writer.freeze_candidate(
            executable=new_executable,
            evidence_refs=tuple(
                completion.result["completion_record_id"]
                for completion in completions
            ),
            operation_id="failed-post-holdout-candidate-freeze",
        )
        self.assertEqual(frozen.result["executable_id"], new_executable.identity)

    def test_holdout_pass_fail_and_not_evaluable_dispositions(self) -> None:
        for verdict in ("passed", "failed", "not_evaluable"):
            with self.subTest(verdict=verdict), TemporaryDirectory() as root:
                writer, executable, candidate, plan = self._build_frozen_candidate(root)
                content = f"sealed holdout values for {verdict}".encode("ascii")
                artifact = writer.evidence.finalize(content)
                starts_at = "2026-07-01T00:00:00Z"
                ends_at = "2026-07-10T00:00:00Z"
                rows = SealedHoldoutManifest.rows_identity(
                    artifact_sha256=artifact.sha256,
                    size_bytes=artifact.size_bytes,
                )
                sealed = SealedHoldoutManifest(
                    artifact_sha256=artifact.sha256,
                    size_bytes=artifact.size_bytes,
                    data_receipt_id=SealedHoldoutManifest.dataset_identity(
                        artifact.sha256
                    ),
                    split_identity=SealedHoldoutManifest.split_identity_for(
                        row_identity=rows,
                        starts_at_utc=starts_at,
                        ends_at_utc=ends_at,
                        predecessor_holdout_id=None,
                    ),
                    row_identity=rows,
                    starts_at_utc=starts_at,
                    ends_at_utc=ends_at,
                )
                writer.record_holdout_seal(
                    manifest=sealed, operation_id=f"{verdict}-holdout-seal"
                )
                tag = f"{verdict}-holdout-evaluation"
                claim = "final-holdout-claim"
                spec, declared = self._declare_and_start_scientific_job(
                    writer=writer,
                    executable_id=executable.identity,
                    plan_hash=plan.sha256,
                    depth="confirmation",
                    claim_id=claim,
                    tag=tag,
                    holdout_id=sealed.identity,
                    evidence_modes=(
                        ("causal_contrast",)
                        if verdict == "failed"
                        else (
                            "causal_contrast",
                            "cost_and_execution",
                            "sensitivity_or_stress",
                        )
                    ),
                )
                holdout_permit = writer.issue_permit(
                    kind=PermitKind.HOLDOUT,
                    subject_kind=SubjectKind.EXECUTABLE,
                    subject_id=executable.identity,
                    input_hash=sealed.identity.removeprefix("holdout:"),
                    actions=("reveal_holdout",),
                    scope=(
                        sealed.identity,
                        f"candidate:{candidate.result['candidate_id']}",
                        f"executable:{executable.identity}",
                    ),
                    expires_at_utc=FIXED_EXPIRY,
                    one_shot=True,
                    operation_id=f"{tag}-holdout-permit",
                )
                self.assertEqual(
                    writer.reveal_holdout_values(
                        permit=holdout_permit,
                        executable_id=executable.identity,
                        operation_id=f"{tag}-reveal",
                    ),
                    content,
                )
                completion = self._complete_scientific_job(
                    writer=writer,
                    spec=spec,
                    declared=declared,
                    executable_id=executable.identity,
                    depth="confirmation",
                    claim_id=claim,
                    verdict=verdict,
                    tag=tag,
                )
                negative_id = None
                if verdict == "failed":
                    memory = NegativeMemory(
                        executable_identity=executable.identity,
                        scope="final holdout confirmation",
                        evidence_references=(
                            completion.result["completion_record_id"],
                        ),
                        reason="final holdout falsified the candidate",
                        reopen_condition="genuinely later sealed data only",
                    )
                    recorded = writer.record_negative_memory(
                        memory=memory,
                        operation_id=f"{tag}-negative-memory",
                    )
                    negative_id = recorded.result["negative_memory_id"]
                    with LocalIndex(writer.index_path) as index:
                        negative = index.get("negative-memory", negative_id)
                    assert negative is not None
                    self.assertEqual(
                        negative.payload["executed_evidence_modes"],
                        ["causal_contrast"],
                    )
                writer.record_holdout_evaluation(
                    completion_record_id=completion.result[
                        "completion_record_id"
                    ],
                    negative_memory_id=negative_id,
                    operation_id=f"{tag}-disposition",
                )
                state = writer.read_control()
                assert state is not None
                self.assertIsNone(
                    state["scientific"]["active_holdout_evaluation"]
                )
                if verdict == "passed":
                    self.assertEqual(
                        state["scientific"]["active_executable"],
                        executable.identity,
                    )
                    self.assertEqual(
                        state["next_action"]["kind"],
                        "plan_candidate_bound_evidence",
                    )
                    writer.dispose_candidate(
                        disposition="returned_to_library",
                        reason="runtime evidence requires a new scientific composition",
                        operation_id="passed-dispose-after-holdout",
                    )
                    self.assertEqual(
                        writer.read_control()["next_action"],  # type: ignore[index]
                        {
                            "kind": "await_new_future_holdout_data",
                            "predecessor_holdout_id": sealed.identity,
                        },
                    )
                else:
                    self.assertIsNone(state["scientific"]["active_executable"])
                    self.assertEqual(
                        state["next_action"]["kind"],
                        "await_new_future_holdout_data",
                    )
                    successor_artifact = writer.evidence.finalize(
                        f"later holdout values for {verdict}".encode("ascii")
                    )
                    successor_start = "2026-07-11T00:00:00Z"
                    successor_end = "2026-07-20T00:00:00Z"
                    successor_rows = SealedHoldoutManifest.rows_identity(
                        artifact_sha256=successor_artifact.sha256,
                        size_bytes=successor_artifact.size_bytes,
                    )
                    successor = SealedHoldoutManifest(
                        artifact_sha256=successor_artifact.sha256,
                        size_bytes=successor_artifact.size_bytes,
                        data_receipt_id=SealedHoldoutManifest.dataset_identity(
                            successor_artifact.sha256
                        ),
                        split_identity=SealedHoldoutManifest.split_identity_for(
                            row_identity=successor_rows,
                            starts_at_utc=successor_start,
                            ends_at_utc=successor_end,
                            predecessor_holdout_id=sealed.identity,
                        ),
                        row_identity=successor_rows,
                        starts_at_utc=successor_start,
                        ends_at_utc=successor_end,
                        predecessor_holdout_id=sealed.identity,
                    )
                    writer.record_holdout_seal(
                        manifest=successor,
                        operation_id=f"{tag}-successor-seal",
                    )
                    self.assertEqual(
                        writer.read_control()["scientific"][  # type: ignore[index]
                            "required_future_holdout_id"
                        ],
                        successor.identity,
                    )
                    self.assertEqual(
                        writer.read_control()["next_action"],  # type: ignore[index]
                        {
                            "kind": "register_future_development_material",
                            "holdout_id": successor.identity,
                            "mission_id": "MIS-HOLDOUT-LIFECYCLE",
                            "predecessor_holdout_id": sealed.identity,
                        },
                    )
                    with LocalIndex(writer.index_path) as index:
                        old_candidate = index.get(
                            "candidate", candidate.result["candidate_id"]
                        )
                    assert old_candidate is not None
                    with self.assertRaises(TransitionError):
                        writer.freeze_candidate(
                            executable=executable,
                            evidence_refs=tuple(old_candidate.payload["evidence_refs"]),
                            operation_id=f"{tag}-reject-old-candidate-refreeze",
                        )
                    if verdict == "failed":
                        self._exercise_future_development_reentry(
                            writer=writer,
                            predecessor=sealed,
                            successor=successor,
                            old_executable=executable,
                            old_candidate_id=candidate.result["candidate_id"],
                            plan_hash=plan.sha256,
                        )

    def test_scientific_job_cannot_execute_an_unregistered_study_mode(self) -> None:
        with TemporaryDirectory() as root:
            writer, executable, _candidate, plan = self._build_frozen_candidate(root)
            with self.assertRaises(TransitionError):
                self._declare_and_start_scientific_job(
                    writer=writer,
                    executable_id=executable.identity,
                    plan_hash=plan.sha256,
                    depth="confirmation",
                    claim_id="unregistered-mode-claim",
                    tag="unregistered-mode",
                    evidence_modes=("ablation",),
                )


class ExternalBlockerLifecycleTests(unittest.TestCase):
    def _run_attempt(
        self,
        *,
        writer: StateWriter,
        plan_hash: str,
        recovery_kind: str,
        ordinal: int,
        indispensable: bool,
        contract_valid_next_action_found: bool,
    ) -> str:
        dependency_id = "required-broker-history-service"
        observed_state = "service unavailable after bounded probe"
        required_change = "broker history service becomes available"
        blocked_capability = "indispensable FPMarkets US100 history acquisition"
        result_name = f"evidence/external-{ordinal}-result"
        measurement_name = f"evidence/external-{ordinal}-measurement"
        spec = job_spec(
            writer, {"kind": "Mission", "id": "MIS-EXTERNAL-BLOCKER"}
        )
        spec["input_hashes"] = [*spec["input_hashes"], plan_hash]
        spec["expected_outputs"] = [result_name, measurement_name]
        spec["output_classes"] = {
            result_name: "durable_evidence",
            measurement_name: "durable_evidence",
        }
        spec["external_dependency_binding"] = {
            "blocked_mission_capability": blocked_capability,
            "dependency_id": dependency_id,
            "dependency_kind": "market_data_service",
            "exact_resume_action": "resume_fixture_job",
            "recovery_kind": recovery_kind,
            "recovery_path_id": f"recovery-path-{ordinal}",
            "result_manifest_output": result_name,
            "required_external_change": required_change,
            "validation_plan_hash": plan_hash,
            "validator_id": ExternalFixtureValidator.validator_id,
        }
        declared = writer.declare_job(
            spec=spec, operation_id=f"external-{ordinal}-declare"
        )
        permit = writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=declared.result["job_id"],
            input_hash=declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id=f"external-{ordinal}-permit",
        )
        writer.start_job(permit=permit, operation_id=f"external-{ordinal}-start")
        facts = {
            "blocked_mission_capability": blocked_capability,
            "contract_valid_next_action_found": contract_valid_next_action_found,
            "dependency_id": dependency_id,
            "indispensable_to_mission_terminal": indispensable,
            "observed_external_state": observed_state,
            "recovery_kind": recovery_kind,
            "required_external_change": required_change,
            "safe_substitute_found": False,
        }
        measurement = writer.evidence.finalize(
            canonical_bytes(
                {
                    "facts": facts,
                    "schema": "external_boundary_measurement.v1",
                    "verdict": "failed",
                }
            )
        )
        result = writer.evidence.finalize(
            canonical_bytes(
                {
                    "contract_valid_next_action_found": contract_valid_next_action_found,
                    "dependency_id": dependency_id,
                    "indispensable_to_mission_terminal": indispensable,
                    "job_hash": declared.result["job_hash"],
                    "job_id": declared.result["job_id"],
                    "measurement_artifact_hashes": [measurement.sha256],
                    "mission_id": "MIS-EXTERNAL-BLOCKER",
                    "observed_external_state": observed_state,
                    "recovery_kind": recovery_kind,
                    "required_external_change": required_change,
                    "safe_substitute_found": False,
                    "schema": "external_dependency_evidence.v1",
                }
            )
        )
        completed = writer.complete_job(
            outcome="failed",
            output_manifest={
                result_name: result.sha256,
                measurement_name: measurement.sha256,
            },
            failure={
                "external_dependency_id": dependency_id,
                "failure_kind": "external_dependency",
                "interrupted_action": spec["callable_identity"],
                "minimum_reproduction_evidence": [measurement.sha256],
                "observed_external_state": observed_state,
                "resume_action": spec["resume_action"],
                "root_cause": "validated required external service outage",
            },
            operation_id=f"external-{ordinal}-complete",
        )
        return completed.result["completion_record_id"]

    def _writer(self, root: str) -> tuple[StateWriter, str]:
        writer = StateWriter(
            root,
            permit_authority=PermitAuthority(b"e" * 32),
            clock=lambda: FIXED_NOW,
            foundation_root=REPO_ROOT,
            validation_registry=EvidenceValidatorRegistry(
                (ExternalFixtureValidator(),)
            ),
        )
        writer.initialize_ready()
        writer.open_mission(
            mission_id="MIS-EXTERNAL-BLOCKER",
            goal=mission_goal("validated genuine external blocker"),
            operation_id="external-blocker-mission",
        )
        plan = writer.evidence.finalize(
            canonical_bytes({"schema": "external_boundary_plan.v1"})
        )
        return writer, plan.sha256

    def test_blocker_requires_validated_indispensability_and_no_next_action(self) -> None:
        recovery_kinds = (
            "external_probe",
            "local_recovery",
            "safe_substitute_search",
        )
        with TemporaryDirectory() as root:
            writer, plan_hash = self._writer(root)
            completions = tuple(
                self._run_attempt(
                    writer=writer,
                    plan_hash=plan_hash,
                    recovery_kind=recovery_kind,
                    ordinal=ordinal,
                    indispensable=True,
                    contract_valid_next_action_found=False,
                )
                for ordinal, recovery_kind in enumerate(recovery_kinds, start=1)
            )
            blocker = writer.record_external_blocker(
                dependency_id="required-broker-history-service",
                completion_record_ids=completions,
                operation_id="accept-validated-external-blocker",
            )
            self.assertEqual(
                writer.read_control()["next_action"],  # type: ignore[index]
                {
                    "basis_record_id": blocker.result["basis_record_id"],
                    "kind": "close_mission",
                    "outcome": "blocked_external",
                },
            )

        with TemporaryDirectory() as root:
            writer, plan_hash = self._writer(root)
            completions = tuple(
                self._run_attempt(
                    writer=writer,
                    plan_hash=plan_hash,
                    recovery_kind=recovery_kind,
                    ordinal=ordinal,
                    indispensable=False,
                    contract_valid_next_action_found=True,
                )
                for ordinal, recovery_kind in enumerate(recovery_kinds, start=1)
            )
            with self.assertRaises(TransitionError):
                writer.record_external_blocker(
                    dependency_id="required-broker-history-service",
                    completion_record_ids=completions,
                    operation_id="reject-optional-external-blocker",
                )


class CrashRecoveryTests(unittest.TestCase):
    def test_each_transaction_boundary_recovers_idempotently(self) -> None:
        for crash_after in ("after_evidence", "after_journal", "after_cursor", "after_index"):
            with self.subTest(crash_after=crash_after), TemporaryDirectory() as root:
                writer = StateWriter(
                    root,
                    permit_authority=PermitAuthority(b"c" * 32),
                    clock=lambda: FIXED_NOW,
                    engineering_fixture=True,
                    foundation_root=REPO_ROOT,
                )
                with self.assertRaises(InjectedCrash):
                    writer.initialize_ready(crash_after=crash_after)
                report = writer.recover()
                if crash_after == "after_evidence":
                    self.assertEqual(report["journal_sequence"], 0)
                retried = writer.initialize_ready()
                state = writer.read_control()
                assert state is not None
                self.assertEqual(state["revision"], 1)
                self.assertEqual(state["next_action"], {"kind": "await_root_goal"})
                self.assertEqual(retried.reused, crash_after != "after_evidence")

    def test_torn_tail_is_preserved_and_rejected(self) -> None:
        with TemporaryDirectory() as root:
            writer = StateWriter(root, clock=lambda: FIXED_NOW, foundation_root=REPO_ROOT)
            writer.initialize_ready()
            with (Path(root) / "records" / "journal.jsonl").open("ab") as handle:
                handle.write(b'{"torn"')
            with self.assertRaises(TornJournalError):
                writer.recover()

    def test_non_tail_journal_chain_damage_is_rejected(self) -> None:
        with TemporaryDirectory() as root:
            writer = StateWriter(root, clock=lambda: FIXED_NOW, foundation_root=REPO_ROOT)
            writer.initialize_ready()
            writer.open_mission(
                mission_id="MIS-JOURNAL-CHAIN",
                goal=mission_goal("full journal chain integrity"),
                operation_id="journal-chain-mission",
            )
            journal_path = Path(root) / "records" / "journal.jsonl"
            framed = journal_path.read_bytes().splitlines(keepends=True)
            first = parse_canonical(framed[0][:-1])
            assert isinstance(first, dict)
            first["occurred_at_utc"] = "2026-07-11T00:00:01Z"
            base = dict(first)
            base.pop("event_id")
            first["event_id"] = canonical_digest(
                domain="journal-event", payload=base
            )
            replaced = canonical_bytes(first) + b"\n"
            self.assertEqual(len(replaced), len(framed[0]))
            journal_path.write_bytes(replaced + b"".join(framed[1:]))
            with self.assertRaises(JournalIntegrityError):
                writer.recover()

    def test_same_head_control_or_extra_index_row_cannot_authorize_work(self) -> None:
        with TemporaryDirectory() as root:
            writer = StateWriter(root, clock=lambda: FIXED_NOW, foundation_root=REPO_ROOT)
            writer.initialize_ready()
            altered = writer.read_control()
            assert altered is not None
            altered["next_action"] = {"kind": "forged_same_head_action"}
            writer.control.replace(altered)
            with self.assertRaises(RecoveryRequired):
                writer.record_work_result(
                    work={
                        "callable_identity": "fixture.forged",
                        "input_identity": "control",
                    },
                    outcome="success",
                    details={"fixture": True},
                    operation_id="reject-forged-control",
                )
            repaired = writer.recover()
            self.assertTrue(repaired["control_repaired"])
            self.assertEqual(writer.read_control()["next_action"], {"kind": "await_root_goal"})  # type: ignore[index]

            with LocalIndex(writer.index_path) as index:
                index.put(
                    IndexRecord(
                        kind="release",
                        record_id="forged-release",
                        subject="Release:forged",
                        status="frozen",
                        fingerprint="f" * 64,
                        payload={"fixture": True},
                    )
                )
            with self.assertRaises(RecoveryRequired):
                writer.record_work_result(
                    work={
                        "callable_identity": "fixture.forged",
                        "input_identity": "index",
                    },
                    outcome="success",
                    details={"fixture": True},
                    operation_id="reject-forged-index",
                )
            rebuilt = writer.recover()
            self.assertTrue(rebuilt["index_rebuilt"])
            with LocalIndex(writer.index_path) as index:
                self.assertIsNone(index.get("release", "forged-release"))

            with LocalIndex(writer.index_path) as index:
                legitimate = index.get(
                    "initiative-close", "INI-0001:completed_ready_boundary"
                )
                assert legitimate is not None
                index._connection.execute(  # noqa: SLF001 - adversarial projection test
                    "DELETE FROM records WHERE kind = ? AND record_id = ?",
                    (legitimate.kind, legitimate.record_id),
                )
                index._connection.commit()  # noqa: SLF001 - adversarial projection test
                index.put(
                    IndexRecord(
                        kind="negative-memory",
                        record_id="same-count-forgery",
                        subject="Executable:forged",
                        status="durable",
                        fingerprint="e" * 64,
                        payload={"fixture": True},
                    )
                )
            with self.assertRaises(RecoveryRequired):
                writer.open_mission(
                    mission_id="MIS-REJECT-FORGED-INDEX",
                    goal=mission_goal("same-count index forgery"),
                    operation_id="reject-same-count-forgery",
                )
            rebuilt_again = writer.recover()
            self.assertTrue(rebuilt_again["index_rebuilt"])
            with LocalIndex(writer.index_path) as index:
                self.assertIsNone(index.get("negative-memory", "same-count-forgery"))
                self.assertIsNotNone(
                    index.get(
                        "initiative-close", "INI-0001:completed_ready_boundary"
                    )
                )


if __name__ == "__main__":
    unittest.main()
