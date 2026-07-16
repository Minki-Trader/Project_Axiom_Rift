from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec, canonical_digest
from axiom_rift.operations.permits import PermitAuthority, PermitError, PermitKind, SubjectKind
from axiom_rift.operations.running_job import RunningJobAuthority
from axiom_rift.operations.external_observed_development_binding import (
    external_observed_development_job_binding,
    require_current_external_observed_development_job_binding,
)
from axiom_rift.operations.study_close_delivery import StudyCloseGuardCapability
from axiom_rift.operations.external_dependency import (
    ExternalChangeEvidence,
    ExternalRecoveryPath,
    ExternalRecoveryPlan,
    ExternalResumeAction,
    ExternalResumeCondition,
)
from axiom_rift.operations.writer import (
    IdenticalFailedRetryError,
    InjectedCrash,
    RecoveryRequired,
    RunningJobExecution,
    StateWriter,
    TransitionError,
    _job_requires_current_source_authority,
    _require_study_evidence_modes,
    _terminal_scientific_evidence_modes,
)
from axiom_rift.operations.validation import (
    ENGINEERING_RETRY_VALIDATOR_ID,
    ENGINEERING_RUNTIME_PLAN_HASH,
    ENGINEERING_VALIDATOR_ID,
    EngineeringFixtureValidator,
    EvidenceValidationError,
    EvidenceValidatorRegistry,
)
from tests.operations.fixture_validators import (
    ComponentParityFixtureValidator,
    EngineeringRetryBoundaryFixtureValidator,
    ExternalFixtureValidator,
    RUNTIME_BOUNDARY_PLAN_HASH,
    RuntimeBoundaryFixtureValidator,
    ScientificFixtureValidator,
    SOURCE_BOUNDARY_PLAN_HASH,
    SourceBoundaryFixtureValidator,
)
from axiom_rift.research.sources import (
    RuntimeSourceDriftObservation,
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
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
    DecisionBasisRecord,
    DecisionLens,
    DecisionLensAssessment,
    DecisionLensPosition,
    DecisionOption,
    PortfolioAction,
    PortfolioAxis as _PortfolioAxis,
    PortfolioDecision,
    PortfolioSnapshot,
    QuantTeamDecisionReview,
)
from axiom_rift.research.study_continuation import (
    StopRuleState,
    StudyContinuationDecision,
    StudyContinuationError,
    StudyContinuationOutcome,
)
from axiom_rift.research.governance import (
    ArchitectureContinuationDirection,
    ArchitectureContinuationMode,
    ArchitectureReview,
    ArchitectureReviewConclusion,
    DiagnosisConfidence,
    EvidenceState,
    MissionResearchIntake,
    REQUIRED_INTAKE_SURFACES,
    ResearchLayer,
    StudyDiagnosis,
)
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ComponentParityDimension,
    ComponentParityEvidence,
    ControlledStudyChassis,
)
from axiom_rift.research.trials import NegativeMemory
from axiom_rift.research.historical_adjudication import (
    HistoricalAdjudicationRequest,
    HistoricalDisposition,
    HistoricalValidityOverride,
    HistoricalValidityReason,
    ReplayPriority,
)
from axiom_rift.research.adjudication import (
    AdjudicationProfile,
    bonferroni_concurrent_family,
)
from axiom_rift.research.source_authority import (
    SourceAuthorityAuditManifest,
    SourceAuthorityInvalidation,
    SourceAuthorityLatch,
    SourceAuthorityReason,
    SourceAuthoritySurface,
)
from axiom_rift.research.decision_withdrawal import (
    PortfolioDecisionWithdrawalManifest,
    PortfolioDecisionWithdrawalReason,
)
from axiom_rift.research.protocol import (
    ResearchProtocol,
    ResearchProtocolActivation,
)
from axiom_rift.research.validation_v2 import (
    ScientificAdjudicationValidatorV2,
)
from axiom_rift.research.scientific_study import (
    PLANNED_CLAIMS,
    discovery_criteria,
)
from axiom_rift.storage.journal import JournalIntegrityError, TornJournalError
from axiom_rift.storage.index import IndexRecord, LocalIndex
from axiom_rift.storage.state import control_hash
from axiom_rift.runtime.source_lifecycle_coverage import (
    derive_source_lifecycle_coverage,
)
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
FIXTURE_DELIVERY_CAPABILITY = (
    StudyCloseGuardCapability.ISOLATED_ENGINEERING_FIXTURE
)
_FIXTURE_IMPLEMENTATION_BYTES: dict[str, bytes] = {}
_AUTHORITY_AND_FOUNDATION_PATHS = (
    "OPERATING_DIRECTION.md",
    "contracts/operations.yaml",
    "contracts/science.yaml",
    "contracts/evidence.yaml",
    "contracts/runtime.yaml",
    "foundation/market.yaml",
    "foundation/environment.yaml",
    "foundation/data.yaml",
    "foundation/data_exposure.yaml",
    "foundation/prior_scientific_memory.yaml",
    "foundation/origin.yaml",
)


def legacy_scientific_fixture_foundation(root: Path) -> Path:
    """Copy a synthetic pre-V2 authority for legacy validator lifecycle tests."""

    target = root / "legacy-scientific-fixture-authority"
    replacements = 0
    for relative in _AUTHORITY_AND_FOUNDATION_PATHS:
        source = REPO_ROOT / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = source.read_bytes()
        marker = b"scientific_adjudication_v2:"
        if marker in content:
            replacements += content.count(marker)
            content = content.replace(marker, b"scientific_fixture_v1:")
        destination.write_bytes(content)
    if replacements != 2:
        raise AssertionError("legacy scientific fixture authority marker count drifted")
    source_relative = Path(
        "src/axiom_rift/research/implementation_closure.py"
    )
    source_destination = target / source_relative
    source_destination.parent.mkdir(parents=True, exist_ok=True)
    source_destination.write_bytes((REPO_ROOT / source_relative).read_bytes())
    return target


def fixture_component_implementation(name: str) -> str:
    source = canonical_bytes(
        {"implementation": name, "schema": "fixture_component_source.v1"}
    )
    source_hash = sha256(source).hexdigest()
    _FIXTURE_IMPLEMENTATION_BYTES[source_hash] = source
    return f"{name}@sha256:{source_hash}"


def source_audit_report_bytes(
    *,
    finding_id: str,
    source_contract_id: str,
    source_state_record_id: str,
) -> bytes:
    return (
        "# Source Authority Audit\n\n"
        f"- {finding_id}:\n"
        f"  {source_contract_id},\n"
        f"  audited head {source_state_record_id};\n"
    ).encode("ascii")


def architecture_chassis(tag: str) -> ArchitectureChassisSpec:
    variant = "alternate" if "alternate" in tag else "common"
    baseline = scientific_executable_spec(
        f"architecture-{variant}", architecture_variant=variant
    )
    return ArchitectureChassisSpec.from_executable(baseline)


def PortfolioAxis(
    *,
    axis_id: str,
    causal_question: str,
    mechanism_family: str,
    status: str = "open",
) -> _PortfolioAxis:
    token = axis_id.rsplit("-", 1)[-1]
    slot = {"a": 0, "b": 1, "c": 2, "0": 0, "1": 1, "2": 2}.get(
        token, 0
    )
    layer = (
        ResearchLayer.CALIBRATION,
        ResearchLayer.LABEL,
        ResearchLayer.LIFECYCLE,
    )[slot]
    controlled = tuple(
        candidate
        for candidate in (
            ResearchLayer.FEATURE,
            ResearchLayer.LABEL,
            ResearchLayer.MODEL,
            ResearchLayer.CALIBRATION,
            ResearchLayer.SELECTOR,
            ResearchLayer.TRADE,
            ResearchLayer.LIFECYCLE,
            ResearchLayer.RISK,
            ResearchLayer.EXECUTION,
        )
        if candidate != layer
    )
    chassis = architecture_chassis("fixture-baseline" if slot < 2 else "fixture-alternate")
    return _PortfolioAxis(
        axis_id=axis_id,
        causal_question=causal_question,
        mechanism_family=mechanism_family,
        primary_research_layer=layer,
        system_architecture_family=chassis.identity,
        changed_domains=(layer,),
        controlled_domains=controlled,
        why_now="fixture requires a causally distinct research axis",
        stop_or_reopen_condition="stop at the frozen fixture evidence boundary",
        architecture_chassis=chassis,
        status=status,
    )


def portfolio_axis_baseline(axis: _PortfolioAxis) -> ExecutableSpec:
    token = axis.axis_id.rsplit("-", 1)[-1]
    variant = "alternate" if token in {"c", "2"} else "common"
    return scientific_executable_spec(
        f"architecture-{variant}", architecture_variant=variant
    )


def record_fixture_research_intake(
    writer: StateWriter,
    *,
    mission_id: str,
    operation_id: str,
) -> MissionResearchIntake:
    control = writer.read_control()
    assert control is not None
    intake = MissionResearchIntake(
        mission_id=mission_id,
        history_head_sequence=control["heads"]["journal"]["sequence"],
        history_head_event_id=control["heads"]["journal"]["event_id"],
        reviewed_surfaces=tuple(sorted(REQUIRED_INTAKE_SURFACES)),
        mission_thesis="exercise the typed research-direction boundary",
        architecture_findings=(
            "no prior fixture science changes the broad baseline requirement",
        ),
        bottleneck_hypotheses=(
            "the selected mechanism may contain no stable information",
            "the common architecture may hide a distinct research-layer bottleneck",
        ),
        underexplored_layers=(
            ResearchLayer.FEATURE,
            ResearchLayer.LABEL,
            ResearchLayer.MODEL,
            ResearchLayer.TRADE,
        ),
        legacy_limitations="fixture history has no legacy classification authority",
    )
    writer.record_research_intake(
        intake=intake,
        operation_id=operation_id,
    )
    return intake


def record_fixture_study_diagnosis(
    writer: StateWriter,
    *,
    study_id: str,
    evidence_state: EvidenceState,
    operation_id: str,
) -> StudyDiagnosis:
    control = writer.read_control()
    assert control is not None
    close_record_id = control["next_action"]["study_close_record_id"]
    diagnosis = StudyDiagnosis(
        study_id=study_id,
        study_close_record_id=close_record_id,
        evidence_state=evidence_state,
        confidence=DiagnosisConfidence.MEDIUM,
        rationale="the exact disposition evidence isolates the typed fixture state",
        counterfactual="a materially changed research layer would distinguish the cause",
        reopen_condition="reopen only with the diagnosis-authorized changed information",
    )
    writer.record_study_diagnosis(
        diagnosis=diagnosis,
        operation_id=operation_id,
    )
    return diagnosis


def quant_team_review_for_current_action(
    writer: StateWriter,
    *,
    options: tuple[DecisionOption, ...],
    chosen_option_id: str,
) -> QuantTeamDecisionReview:
    """Build a compact real-work review from the Writer's durable action bases."""

    control = writer.read_control()
    assert control is not None
    next_action = control["next_action"]
    snapshot_id = next_action.get("portfolio_snapshot_id")
    assert isinstance(snapshot_id, str)
    bases = [
        DecisionBasisRecord(
            kind="portfolio-snapshot",
            record_id=snapshot_id,
        )
    ]
    diagnosis_id = next_action.get("study_diagnosis_id")
    if isinstance(diagnosis_id, str):
        bases.append(
            DecisionBasisRecord(
                kind="study-diagnosis",
                record_id=diagnosis_id,
            )
        )
    architecture_review_id = next_action.get("architecture_review_id")
    if isinstance(architecture_review_id, str):
        bases.append(
            DecisionBasisRecord(
                kind="architecture-review",
                record_id=architecture_review_id,
            )
        )
    architecture_trigger_id = next_action.get("architecture_review_trigger_id")
    if isinstance(architecture_trigger_id, str):
        bases.append(
            DecisionBasisRecord(
                kind="architecture-review-trigger",
                record_id=architecture_trigger_id,
            )
        )
    for covered_diagnosis_id in next_action.get("covered_diagnosis_ids", []):
        bases.append(
            DecisionBasisRecord(
                kind="study-diagnosis",
                record_id=covered_diagnosis_id,
            )
        )
    for obligation_id in next_action.get("replay_obligation_ids", []):
        bases.append(
            DecisionBasisRecord(
                kind="historical-replay-obligation",
                record_id=obligation_id,
            )
        )
    basis_records = tuple(sorted(bases, key=lambda item: item.sort_key))
    option_ids = tuple(sorted(option.option_id for option in options))
    return QuantTeamDecisionReview(
        assessments=(
            DecisionLensAssessment(
                lens=DecisionLens.CAUSALITY,
                position=DecisionLensPosition.SUPPORT,
                option_ids=option_ids,
                basis_records=basis_records,
                finding="the chosen branch isolates its registered causal question",
            ),
            DecisionLensAssessment(
                lens=DecisionLens.RISK,
                position=DecisionLensPosition.UNCERTAIN,
                option_ids=(chosen_option_id,),
                basis_records=basis_records,
                finding="one Batch delays but does not retire the risk alternative",
            ),
        ),
        claim_boundary="allocation only; no scientific or candidate authority",
        resolution_basis="bounded information gain exceeds one Batch opportunity cost",
        disagreement_resolution="retain the risk alternative in the live forest",
    )


def study_continuation_review(
    *,
    snapshot_id: str,
    batch_close_record_id: str,
    completion_record_ids: tuple[str, ...],
) -> QuantTeamDecisionReview:
    bases = [
        DecisionBasisRecord(
            kind="batch-close",
            record_id=batch_close_record_id,
        ),
        DecisionBasisRecord(
            kind="portfolio-snapshot",
            record_id=snapshot_id,
        ),
        *(
            DecisionBasisRecord(
                kind="job-completed",
                record_id=completion_id,
            )
            for completion_id in completion_record_ids
        ),
    ]
    basis_records = tuple(sorted(bases, key=lambda item: item.sort_key))
    option_ids = ("close-study", "continue-study")
    return QuantTeamDecisionReview(
        assessments=(
            DecisionLensAssessment(
                lens=DecisionLens.CAUSALITY,
                position=DecisionLensPosition.SUPPORT,
                option_ids=option_ids,
                basis_records=basis_records,
                finding="the unchanged Study question can isolate one more Batch",
            ),
            DecisionLensAssessment(
                lens=DecisionLens.ECONOMICS,
                position=DecisionLensPosition.UNCERTAIN,
                option_ids=option_ids,
                basis_records=basis_records,
                finding="one more Batch has bounded forest opportunity cost",
            ),
        ),
        claim_boundary="continuation allocation only; no scientific promotion",
        resolution_basis="durable Batch evidence retains bounded information value",
        disagreement_resolution="pre-bind one Batch and preserve every other axis",
    )


def digest(domain: str, value: object) -> str:
    return canonical_digest(domain=domain, payload=value)


def job_implementation_identity(
    writer: StateWriter,
    *,
    callable_identity: str,
    revision: int = 1,
    component_hashes: tuple[str, ...] = (),
) -> str:
    if writer.engineering_fixture:
        source_bytes = (
            f"# fixture revision {revision}\n"
            "def fixture_job_entry(*args, **kwargs):\n"
            f"    return {callable_identity!r}\n"
        ).encode("ascii")
        source_path = "tests/fixtures/job_entry.py"
        shared_helper = writer.evidence.finalize(
            b"def fixture_helper():\n    return 'helper'\n"
        )
    else:
        current_path = (
            REPO_ROOT
            / "src"
            / "axiom_rift"
            / "research"
            / "implementation_closure.py"
        )
        source_bytes = current_path.read_bytes()
        source_path = "axiom_rift/research/implementation_closure.py"
        shared_helper = None
    source = writer.evidence.finalize(source_bytes)
    for component_hash in component_hashes:
        artifact = writer.evidence.finalize(
            _FIXTURE_IMPLEMENTATION_BYTES[component_hash]
        )
        assert artifact.sha256 == component_hash
    dependencies = [
        {"path": source_path, "sha256": source.sha256},
        *(
            (
                {
                    "path": "tests/fixtures/shared_helper.py",
                    "sha256": shared_helper.sha256,
                },
                {
                    "path": "tests/fixtures/shared_helper_alias.py",
                    "sha256": shared_helper.sha256,
                },
            )
            if shared_helper is not None
            else ()
        ),
        *(
            {
                "path": f"tests/fixtures/components/{ordinal:04d}.artifact",
                "sha256": component_hash,
            }
            for ordinal, component_hash in enumerate(component_hashes)
            if writer.engineering_fixture
        ),
    ]
    closure = writer.evidence.finalize(
        canonical_bytes(
            {
                "callable_identity": callable_identity,
                "dependencies": sorted(
                    dependencies, key=lambda item: item["path"]
                ),
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
                        source.sha256,
                        *(
                            (shared_helper.sha256,)
                            if shared_helper is not None
                            else ()
                        ),
                        *component_hashes,
                    }
                ),
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
    callable_identity = (
        "fixture.callable"
        if writer.engineering_fixture
        else (
            "axiom_rift.research.implementation_closure."
            "require_current_job_source_closure.v1"
        )
    )
    subject = evidence_subject or {"kind": "Study", "id": "STU-FIXTURE"}
    component_hashes: tuple[str, ...] = ()
    if subject["kind"] == "Executable":
        with LocalIndex(writer.index_path) as index:
            trial = index.get("trial", subject["id"])
        if trial is not None:
            component_hashes = tuple(
                sorted(
                    manifest["implementation"].rsplit("@sha256:", 1)[1]
                    for manifest in trial.payload["executable"][
                        "component_manifests"
                    ]
                )
            )
    return {
        "callable_identity": callable_identity,
        "implementation_identity": job_implementation_identity(
            writer,
            callable_identity=callable_identity,
            component_hashes=component_hashes,
        ),
        "input_hashes": [digest("input", {"fixture": 1})],
        "budget": {"compute_seconds": 30, "wall_seconds": 30, "trials": 1},
        "expected_outputs": ["local/jobs/fixture/fixture.json"],
        "output_classes": {"local/jobs/fixture/fixture.json": "transient"},
        "log_path": "local/jobs/fixture.log",
        "timeout_or_stop_rule": "stop_at_30_seconds",
        "resume_action": "resume_fixture_job",
        "evidence_subject": subject,
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


def repair_attempt_proof(
    writer: StateWriter,
    *,
    outcome: str,
    changed_dimension: str,
    new_basis_hash: str,
    new_evidence_hashes: tuple[str, ...],
    verification_evidence_hashes: tuple[str, ...],
    implementation_proof_hash: str | None = None,
) -> str:
    control = writer.read_control()
    assert control is not None
    repair = control["scientific"]["active_repair"]
    job = control["scientific"]["active_job"]
    assert isinstance(repair, dict) and isinstance(job, dict)
    with LocalIndex(writer.index_path) as index:
        opened = index.get("repair-open", repair["id"])
    assert opened is not None
    check_plan = writer.evidence.finalize(
        canonical_bytes(
            {
                "changed_dimension": changed_dimension,
                "job_id": job["id"],
                "new_basis_hash": new_basis_hash,
                "schema": "fixture_repair_check_plan.v1",
            }
        )
    )
    verification_receipt = writer.evidence.finalize(
        canonical_bytes(
            {
                "cause_hash": repair["cause_hash"],
                "changed_dimension": changed_dimension,
                "check_plan_hash": check_plan.sha256,
                "job_hash": job["hash"],
                "job_id": job["id"],
                "new_basis_hash": new_basis_hash,
                "outcome": outcome,
                "repair_id": repair["id"],
                "result_artifact_hashes": sorted(
                    verification_evidence_hashes
                ),
                "resume_action": repair["resume_action"],
                "schema": "repair_verification_receipt.v1",
                "scientific_semantics_changed": False,
                "verdict": (
                    "passed"
                    if outcome == "repaired"
                    else "failure_reproduced"
                ),
                "verification_method": "fixture affected-surface check",
            }
        )
    )
    proof = writer.evidence.finalize(
        canonical_bytes(
            {
                "cause_hash": repair["cause_hash"],
                "changed_dimension": changed_dimension,
                "explanation": "exercise exact changed-basis Repair evidence",
                "failure_observation": (
                    "changed basis still reproduces the engineering failure"
                    if outcome == "failed"
                    else None
                ),
                "implementation_proof_hash": implementation_proof_hash,
                "job_hash": job["hash"],
                "job_id": job["id"],
                "new_basis_hash": new_basis_hash,
                "new_evidence_hashes": sorted(new_evidence_hashes),
                "outcome": outcome,
                "previous_basis_hash": repair["latest_basis_hash"],
                "prior_attempt_record_id": repair[
                    "latest_attempt_record_id"
                ],
                "repair_id": repair["id"],
                "reproduction_evidence_hashes": sorted(
                    opened.payload["minimum_reproduction_evidence"]
                ),
                "resume_action": repair["resume_action"],
                "schema": "running_job_repair_attempt.v1",
                "scientific_semantics_changed": False,
                "verification_evidence_hashes": sorted(
                    [verification_receipt.sha256]
                ),
            }
        )
    )
    return proof.sha256


def engineering_failure_disposition(
    writer: StateWriter,
    *,
    job_id: str,
    evidence_hashes: tuple[str, ...],
    repair_attempt_record_ids: tuple[str, ...] = (),
    disposition: str = "requires_scientific_change",
    cause_hash: str | None = None,
) -> str:
    control = writer.read_control()
    assert control is not None
    active_repair = control["scientific"]["active_repair"]
    repair_id = (
        active_repair["id"]
        if isinstance(active_repair, dict)
        else None
    )
    if cause_hash is None and isinstance(active_repair, dict):
        cause_hash = active_repair["cause_hash"]
    assert isinstance(cause_hash, str)
    active_job = control["scientific"]["active_job"]
    assert isinstance(active_job, dict) and active_job["id"] == job_id
    attempt_entries: list[dict[str, object]] = []
    reproduction_evidence_hashes = sorted(evidence_hashes)
    with LocalIndex(writer.index_path) as index:
        if isinstance(active_repair, dict):
            opened = index.get("repair-open", active_repair["id"])
            assert opened is not None
            reproduction_evidence_hashes = sorted(
                opened.payload["minimum_reproduction_evidence"]
            )
        for attempt_record_id in sorted(repair_attempt_record_ids):
            attempt = index.get("repair-attempt", attempt_record_id)
            assert attempt is not None
            attempt_entries.append(
                {
                    "attempt_proof_hash": attempt.payload[
                        "attempt_proof_hash"
                    ],
                    "changed_dimension": attempt.payload[
                        "changed_dimension"
                    ],
                    "new_basis_hash": attempt.payload["new_basis_hash"],
                    "repair_attempt_record_id": attempt.record_id,
                    "verification_receipt_hashes": sorted(
                        attempt.payload["verification_evidence_hashes"]
                    ),
                }
            )
    basis_by_disposition = {
        "repair_exhausted_changed_causes": (
            False,
            False,
            "not_applicable",
            [],
        ),
        "repair_infeasible": (False, False, "not_applicable", []),
        "repair_nonpositive_expected_value": (
            True,
            False,
            "nonpositive",
            ["remaining bounded repair cause"],
        ),
        "requires_scientific_change": (
            False,
            True,
            "not_applicable",
            [],
        ),
    }
    repairable, semantic_change, expected_value, remaining = (
        basis_by_disposition[disposition]
    )
    verification_results = {
        "repair_exhausted_changed_causes": "changed_causes_exhausted",
        "repair_infeasible": "repair_infeasible",
        "repair_nonpositive_expected_value": "nonpositive_expected_value",
        "requires_scientific_change": "scientific_change_required",
    }
    assessment_plan = writer.evidence.finalize(
        canonical_bytes(
            {
                "cause_hash": cause_hash,
                "disposition": disposition,
                "job_hash": active_job["hash"],
                "job_id": job_id,
                "repair_attempt_record_ids": sorted(
                    repair_attempt_record_ids
                ),
                "repair_id": repair_id,
                "schema": "fixture_engineering_disposition_check.v1",
            }
        )
    )
    assessment_result = writer.evidence.finalize(
        canonical_bytes(
            {
                "evidence_hashes": sorted(evidence_hashes),
                "schema": "fixture_engineering_disposition_result.v1",
                "verification_result": verification_results[disposition],
            }
        )
    )
    observation = writer.evidence.finalize(
        canonical_bytes(
            {
                "cause_hash": cause_hash,
                "check_plan_hash": assessment_plan.sha256,
                "disposition": disposition,
                "job_hash": active_job["hash"],
                "job_id": job_id,
                "minimum_reproduction_evidence_hashes": (
                    reproduction_evidence_hashes
                ),
                "repair_attempts": sorted(
                    attempt_entries,
                    key=lambda item: item["repair_attempt_record_id"],
                ),
                "repair_id": repair_id,
                "result_artifact_hashes": [assessment_result.sha256],
                "schema": "engineering_failure_disposition_observation.v1",
                "scientific_semantics_changed": False,
                "verification_method": "fixture bounded recovery assessment",
                "verification_result": verification_results[disposition],
            }
        )
    )
    basis = writer.evidence.finalize(
        canonical_bytes(
            {
                "cause_hash": cause_hash,
                "disposition": disposition,
                "expected_value": expected_value,
                "job_id": job_id,
                "observation_manifest_hash": observation.sha256,
                "remaining_changed_causes": remaining,
                "repair_id": repair_id,
                "repairable_without_scientific_change": repairable,
                "schema": "engineering_failure_disposition_basis.v1",
                "scientific_semantics_change_required": semantic_change,
            }
        )
    )
    artifact = writer.evidence.finalize(
        canonical_bytes(
            {
                "basis_manifest_hash": basis.sha256,
                "cause_hash": cause_hash,
                "disposition": disposition,
                "job_id": job_id,
                "rationale": "repair would alter registered scientific semantics",
                "repair_id": repair_id,
                "repair_attempt_record_ids": sorted(
                    repair_attempt_record_ids
                ),
                "resume_condition": "admit a new exact scientific work identity",
                "schema": "engineering_failure_disposition.v1",
                "successor_scope": (
                    "study"
                    if disposition == "requires_scientific_change"
                    else None
                ),
            }
        )
    )
    return artifact.sha256


def engineering_retry_validation_artifacts(
    writer: StateWriter,
    *,
    binding: dict[str, object],
    validator_id: str,
    resolved: bool = True,
) -> tuple[str, list[str]]:
    plan = writer.evidence.finalize(
        canonical_bytes(
            {
                "operation": "canonical_required_transition",
                "schema": "engineering_retry_fixture_plan.v1",
            }
        )
    )
    prior = {"binding": sha256(canonical_bytes(binding)).hexdigest(), "status": "failed"}
    required = {
        "binding": sha256(canonical_bytes(binding)).hexdigest(),
        "status": "passed",
    }
    measurement = writer.evidence.finalize(
        canonical_bytes(
            {
                "binding_sha256": sha256(
                    canonical_bytes(binding)
                ).hexdigest(),
                "current_measurement": required if resolved else prior,
                "prior_measurement": prior,
                "required_measurement": required,
                "schema": "engineering_retry_fixture_measurement.v1",
            }
        )
    )
    if not validator_id:
        raise AssertionError("engineering retry fixture validator is absent")
    return plan.sha256, [measurement.sha256]


def runtime_job_spec(
    *,
    writer: StateWriter,
    executable_id: str,
    depth: EvidenceDepth,
    output_name: str,
    artifact_roles: tuple[str, ...],
    validation_plan_hash: str = ENGINEERING_RUNTIME_PLAN_HASH,
    validator_id: str = ENGINEERING_VALIDATOR_ID,
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
        validation_plan_hash,
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
    lifecycle_coverage_ids: list[str] = []
    if depth is EvidenceDepth.MATERIALIZATION:
        with LocalIndex(writer.index_path) as index:
            candidate_head = index.event_head(f"candidate:{executable_id}")
            candidate = (
                None
                if candidate_head is None
                else index.get(
                    candidate_head.record_kind, candidate_head.record_id
                )
            )
        if candidate is not None:
            lifecycle_coverage_ids = [
                row["coverage_id"]
                for row in derive_source_lifecycle_coverage(
                    candidate.payload["executable"]
                )
            ]
    spec["runtime_binding"] = {
        "action": action,
        "evidence_depth": depth.value,
        "planned_materialization_cases": cases,
        "planned_parity_surfaces": parity,
        "planned_source_lifecycle_coverage_ids": lifecycle_coverage_ids,
        "result_manifest_output": result_name,
        "artifact_roles": role_outputs,
        "numeric_tolerances": {"default": "fixture_exact"},
        "validation_plan_hash": validation_plan_hash,
        "validator_id": validator_id,
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
        "architecture_review_minimum_axes": 2,
        "architecture_review_minimum_studies": 3,
        "minimum_axes": 3,
        "minimum_distinct_studies_per_axis": 2,
        "minimum_mechanism_families": 3,
        "minimum_negative_executables_per_family": 2,
        "minimum_primary_research_layers": 3,
        "minimum_system_architecture_families": 2,
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
    max_compute_seconds: int = 60,
    stop_rule: str = "stop at frozen bound or accepted decision",
) -> BatchSpec:
    return BatchSpec(
        batch_id=batch_id,
        study_id=study_id,
        study_hash=study_hash,
        display_name="bounded adaptive fixture",
        max_trials=max_trials,
        max_compute_seconds=max_compute_seconds,
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


def scientific_executable_spec(
    tag: str,
    *,
    data_identity: str = OBSERVED_MATERIAL_ID,
    split_contract: str = "split:foundation-observed-development",
    architecture_variant: str = "common",
) -> ExecutableSpec:
    components: list[ComponentSpec] = []
    by_domain: dict[str, ComponentSpec] = {}
    for domain in (
        "feature",
        "label",
        "model",
        "calibration",
        "selector",
        "trade",
        "lifecycle",
        "risk",
        "execution",
    ):
        dependencies: tuple[str, ...] = ()
        if domain == "model":
            dependencies = (
                by_domain["feature"].identity,
                by_domain["label"].identity,
            )
        elif components:
            dependencies = (f"role:{components[-1].protocol.split('.', 1)[0]}",)
        variant = (
            architecture_variant
            if domain == "execution"
            else "common"
        )
        value = ComponentSpec(
            display_name=f"{tag} {domain} scientific component",
            protocol=f"{domain}.scientific_boundary_fixture.v1",
            implementation=fixture_component_implementation(
                f"fixture.scientific.{domain}.{variant}"
            ),
            spec={
                "architecture_variant": variant,
                "fixture_semantics": domain,
                "parameter_fields": [],
            },
            semantic_dependencies=dependencies,
        )
        components.append(value)
        by_domain[domain] = value
    return ExecutableSpec(
        display_name=f"{tag} scientific executable",
        components=tuple(components),
        parameters={"tag": tag},
        data_contract=f"data:{data_identity}",
        split_contract=split_contract,
        clock_contract="clock:completed-m5-bar",
        cost_contract="cost:fixed-lot-boundary-fixture",
        engine_contract="engine:python-boundary-fixture",
    )


def changed_domain_executable(
    baseline: ExecutableSpec,
    *,
    domain: str,
    change_tag: str,
) -> ExecutableSpec:
    original = next(
        component
        for component in baseline.components
        if component.protocol.startswith(f"{domain}.")
    )
    changed = ComponentSpec(
        display_name=f"{domain} changed fixture",
        protocol=original.protocol,
        implementation=fixture_component_implementation(
            f"{original.protocol}.changed.{change_tag}"
        ),
        spec={**original.specification(), "scientific_change": change_tag},
        semantic_dependencies=original.semantic_dependencies,
    )
    return ExecutableSpec(
        display_name=f"{change_tag} changed {domain} executable",
        components=tuple(
            changed if component is original else component
            for component in baseline.components
        ),
        parameters=baseline.parameter_values(),
        data_contract=baseline.data_contract,
        split_contract=baseline.split_contract,
        clock_contract=baseline.clock_contract,
        cost_contract=baseline.cost_contract,
        engine_contract=baseline.engine_contract,
        source_contracts=baseline.source_contracts,
    )


class WriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        foundation_root = (
            legacy_scientific_fixture_foundation(self.root)
            if self._testMethodName == "test_holdout_seal_and_one_time_permit"
            else REPO_ROOT
        )
        self.writer = StateWriter(
            self.root,
            permit_authority=PermitAuthority(b"p" * 32),
            clock=lambda: FIXED_NOW,
            engineering_fixture=True,
            foundation_root=foundation_root,
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

    def test_current_source_authority_policy_covers_every_job_subject(self) -> None:
        for subject_kind in (
            "Mission",
            "Initiative",
            "Study",
            "Executable",
            "Release",
        ):
            with self.subTest(subject_kind=subject_kind):
                self.assertTrue(
                    _job_requires_current_source_authority(
                        engineering_fixture=False,
                        evidence_subject_kind=subject_kind,
                    )
                )
                self.assertFalse(
                    _job_requires_current_source_authority(
                        engineering_fixture=True,
                        evidence_subject_kind=subject_kind,
                    )
                )
        with self.assertRaisesRegex(TransitionError, "unsupported"):
            _job_requires_current_source_authority(
                engineering_fixture=False,
                evidence_subject_kind="Unknown",
            )
        with self.assertRaisesRegex(TransitionError, "must be boolean"):
            _job_requires_current_source_authority(
                engineering_fixture=1,  # type: ignore[arg-type]
                evidence_subject_kind="Study",
            )

    def test_writer_authority_and_budget_counters_reject_bool(self) -> None:
        for event in (
            {"sequence": True, "index_record_count": 1},
            {"sequence": 1, "index_record_count": True},
        ):
            with self.assertRaises(JournalIntegrityError):
                self.writer._assemble(event)
        spec = job_spec(self.writer)
        spec["budget"]["compute_seconds"] = True
        with self.assertRaisesRegex(TransitionError, "positive integer"):
            self.writer._validate_job_spec(spec)

    def test_fixture_seed_direction_exemption_is_capability_and_shape_bound(
        self,
    ) -> None:
        def seed_pending_diagnosis(writer: StateWriter, operation_id: str) -> None:
            def prepare(current, _index):
                assert current is not None
                body = writer._body(current)
                body["next_action"] = {
                    "kind": "diagnose_study",
                    "study_close_event_id": "d" * 64,
                    "study_close_revision": 1,
                    "study_id": "STU-0001",
                }
                return body, [], {"seeded": True}

            writer._commit(
                event_kind="direction_gate_test_seeded",
                operation_id=operation_id,
                subject="Test:direction-gate",
                payload={"seeded": True},
                prepare=prepare,
            )

        seed_pending_diagnosis(self.writer, "fixture-pending-diagnosis")

        def unchanged(current, _index):
            assert current is not None
            return self.writer._body(current), [], {"seeded": True}

        accepted = self.writer._commit(
            event_kind="legacy_trial_fixture_seeded",
            operation_id="accept-inventoried-fixture-seed",
            subject="Executable:legacy",
            payload={"trial_delta": 0},
            prepare=unchanged,
        )
        self.assertFalse(accepted.reused)
        for event_kind, subject, payload in (
            ("arbitrary_fixture_seeded", "Executable:legacy", {"trial_delta": 0}),
            ("legacy_trial_fixture_seeded", "Executable:forged", {"trial_delta": 0}),
            ("legacy_trial_fixture_seeded", "Executable:legacy", {"trial_delta": True}),
        ):
            with self.subTest(
                event_kind=event_kind,
                subject=subject,
                payload=payload,
            ), self.assertRaisesRegex(TransitionError, "cannot bypass"):
                self.writer._commit(
                    event_kind=event_kind,
                    operation_id=(
                        "reject-fixture-seed-"
                        + canonical_digest(
                            domain="fixture-seed-rejection",
                            payload={
                                "event_kind": event_kind,
                                "payload": payload,
                                "subject": subject,
                            },
                        )
                    ),
                    subject=subject,
                    payload=payload,
                    prepare=unchanged,
                )

        with TemporaryDirectory() as root:
            production = StateWriter(
                root,
                clock=lambda: FIXED_NOW,
                engineering_fixture=False,
                foundation_root=REPO_ROOT,
            )
            production.initialize_ready()
            seed_pending_diagnosis(production, "production-pending-diagnosis")

            def production_unchanged(current, _index):
                assert current is not None
                return production._body(current), [], {"bypassed": True}

            with self.assertRaisesRegex(TransitionError, "cannot bypass"):
                production._commit(
                    event_kind="legacy_trial_fixture_seeded",
                    operation_id="production-reject-inventoried-fixture-seed",
                    subject="Executable:legacy",
                    payload={"trial_delta": 0},
                    prepare=production_unchanged,
                )

        source_id = "source:" + "a" * 64

        class BoolSourceHeadIndex:
            def __init__(self, *, authority: bool) -> None:
                self.authority = authority

            def event_head(self, stream: str) -> SimpleNamespace | None:
                if stream.startswith("source-authority:"):
                    if not self.authority:
                        return None
                    return SimpleNamespace(
                        sequence=True,
                        record_kind="source-authority-invalidation",
                        record_id="invalid",
                    )
                return SimpleNamespace(
                    sequence=True,
                    record_kind="source-state",
                    record_id="runtime",
                )

            @staticmethod
            def get(_kind: str, _record_id: str) -> SimpleNamespace:
                return SimpleNamespace(status="runtime_eligible")

        for authority in (False, True):
            with self.subTest(bool_source_head_authority=authority):
                with self.assertRaisesRegex(
                    TransitionError, "lacks current runtime provenance"
                ):
                    self.writer._require_runtime_source(
                        BoolSourceHeadIndex(authority=authority),  # type: ignore[arg-type]
                        source_id,
                    )

    def test_stable_head_read_is_bounded_and_does_not_mutate_authority(self) -> None:
        control_before = self.writer.read_control()
        journal_before = self.writer.journal.tail()[0]
        with LocalIndex(self.writer.index_path) as index:
            count_before = index.record_count()
            projection_before = index.projection_guard()
        report = self.writer.require_stable_head()
        self.assertEqual(report["control"], control_before)
        self.assertEqual(report["control_revision"], control_before["revision"])
        self.assertEqual(report["index_record_count"], count_before)
        self.assertEqual(report["projection_digest"], projection_before[0])
        self.assertEqual(self.writer.read_control(), control_before)
        self.assertEqual(self.writer.journal.tail()[0], journal_before)
        with LocalIndex(self.writer.index_path) as index:
            self.assertEqual(index.record_count(), count_before)
            self.assertEqual(index.projection_guard(), projection_before)

    def test_audit_integrity_is_valid_but_has_no_terminal_science_credit(self) -> None:
        self.assertEqual(
            _require_study_evidence_modes(
                {"evidence_modes": ["audit_integrity"]}
            ),
            ("audit_integrity",),
        )
        self.assertEqual(
            _terminal_scientific_evidence_modes(("audit_integrity",)),
            (),
        )
        self.assertEqual(
            _terminal_scientific_evidence_modes(
                ("causal_contrast", "audit_integrity")
            ),
            ("causal_contrast",),
        )

    def test_stable_mission_authority_and_protocol_boundary_is_explicit(self) -> None:
        self.open_mission_and_initiative()
        self.writer.close_initiative(
            outcome="completed",
            operation_id="stable-mission-close-initiative",
        )
        control = self.writer.read_control()
        assert control is not None
        self.assertIsNone(
            self.writer._authority_migration_boundary(
                control,
                allow_active_stable_boundary=False,
            )
        )
        self.assertEqual(
            self.writer._authority_migration_boundary(
                control,
                allow_active_stable_boundary=True,
            ),
            "active_stable",
        )
        audit = self.writer.evidence.finalize(b"stable Mission protocol audit")
        self.writer.validation_registry = EvidenceValidatorRegistry(
            (ScientificAdjudicationValidatorV2(),)
        )
        activation = ResearchProtocolActivation(
            protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
            validator_id=ScientificAdjudicationValidatorV2.validator_id,
            authority_manifest_digest=control["authority"]["manifest_digest"],
            audit_artifact_hash=audit.sha256,
        )
        with self.assertRaisesRegex(TransitionError, "explicit stable Mission"):
            self.writer.activate_research_protocol(
                activation=activation,
                operation_id="reject-implicit-stable-mission-protocol",
            )
        activated = self.writer.activate_research_protocol(
            activation=activation,
            operation_id="activate-at-explicit-stable-mission",
            allow_active_stable_boundary=True,
        )
        self.assertEqual(activated.result["ordinal"], 1)

    def test_stable_mission_protocol_flag_does_not_widen_other_boundaries(self) -> None:
        self.writer.open_mission(
            mission_id="MIS-NOT-STABLE",
            goal=mission_goal("protocol boundary negative fixture"),
            operation_id="open-not-stable-mission",
        )
        control = self.writer.read_control()
        assert control is not None
        audit = self.writer.evidence.finalize(b"not stable protocol audit")
        self.writer.validation_registry = EvidenceValidatorRegistry(
            (ScientificAdjudicationValidatorV2(),)
        )
        activation = ResearchProtocolActivation(
            protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
            validator_id=ScientificAdjudicationValidatorV2.validator_id,
            authority_manifest_digest=control["authority"]["manifest_digest"],
            audit_artifact_hash=audit.sha256,
        )
        with self.assertRaisesRegex(TransitionError, "explicit stable Mission"):
            self.writer.activate_research_protocol(
                activation=activation,
                operation_id="reject-record-intake-boundary-protocol",
                allow_active_stable_boundary=True,
            )

    def test_validator_rebind_is_limited_to_an_unexecuted_study(self) -> None:
        self.open_mission_and_initiative()
        self.writer.close_initiative(
            outcome="completed",
            operation_id="unexecuted-rebind-close-first-initiative",
        )
        historical_audit = self.writer.evidence.finalize(
            b"historical validator before unexecuted Study rebind"
        )
        self.writer.validation_registry = EvidenceValidatorRegistry(
            (
                ScientificAdjudicationValidatorV2(),
                ScientificFixtureValidator(),
            )
        )
        stable = self.writer.read_control()
        assert stable is not None
        historical = ResearchProtocolActivation(
            protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
            validator_id=ScientificFixtureValidator.validator_id,
            authority_manifest_digest=stable["authority"]["manifest_digest"],
            audit_artifact_hash=historical_audit.sha256,
        )
        with patch(
            "axiom_rift.research.validation_v2."
            "SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID",
            ScientificFixtureValidator.validator_id,
        ):
            first = self.writer.activate_research_protocol(
                activation=historical,
                operation_id="activate-validator-before-unexecuted-study",
                allow_active_stable_boundary=True,
            )
        self.assertEqual(first.result["ordinal"], 1)

        initiative_id = "INI-PROTOCOL-REBIND"
        study_id = "STU-PROTOCOL-REBIND"
        self.writer.open_initiative(
            initiative_id=initiative_id,
            objective=initiative_objective("unexecuted protocol rebind"),
            operation_id="open-unexecuted-rebind-initiative",
        )
        question = study_question("unexecuted protocol rebind")
        proposal = {"mechanism": "validator implementation drift"}
        study_hash = self.writer.study_input_hash(
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            semantic_proposal=proposal,
        )
        study_permit = self.writer.issue_permit(
            kind=PermitKind.STUDY,
            subject_kind=SubjectKind.INITIATIVE,
            subject_id=initiative_id,
            input_hash=study_hash,
            actions=("open_study",),
            scope=("study",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="permit-unexecuted-rebind-study",
        )
        opened = self.writer.open_study(
            study_id=study_id,
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            material_display_name="unexecuted protocol rebind material",
            semantic_proposal=proposal,
            permit=study_permit,
            operation_id="open-unexecuted-rebind-study",
        )
        batch = batch_spec(
            batch_id="BAT-PROTOCOL-REBIND",
            study_id=study_id,
            study_hash=opened.result["study_hash"],
        )
        batch_permit = self.writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id=study_id,
            input_hash=batch.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="permit-unexecuted-rebind-batch",
        )
        self.writer.open_batch(
            batch_spec=batch,
            permit=batch_permit,
            operation_id="open-unexecuted-rebind-batch",
        )

        before = self.writer.read_control()
        assert before is not None
        current_audit = self.writer.evidence.finalize(
            b"current validator at exact pre-Job boundary"
        )
        self.writer.validation_registry = EvidenceValidatorRegistry(
            (ScientificAdjudicationValidatorV2(),)
        )
        current = ResearchProtocolActivation(
            protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
            validator_id=ScientificAdjudicationValidatorV2.validator_id,
            authority_manifest_digest=before["authority"]["manifest_digest"],
            audit_artifact_hash=current_audit.sha256,
        )
        rebound = self.writer.activate_research_protocol(
            activation=current,
            operation_id="rebind-at-unexecuted-study-boundary",
            allow_active_unexecuted_study_boundary=True,
        )
        after = self.writer.read_control()
        assert after is not None
        self.assertEqual(rebound.result["ordinal"], 2)
        self.assertEqual(rebound.result["trial_delta"], 0)
        self.assertEqual(after["scientific"], before["scientific"])
        self.assertEqual(after["next_action"], before["next_action"])
        with LocalIndex(self.writer.index_path) as index:
            record = index.get(
                "research-protocol-activation",
                rebound.result["activation_record_id"],
            )
        assert record is not None
        self.assertEqual(
            record.payload["supersedes_activation_record_id"],
            historical.identity,
        )

        self.writer.declare_job(
            spec=job_spec(
                self.writer,
                {"kind": "Study", "id": study_id},
            ),
            operation_id="declare-before-rebind-rejection",
        )
        with self.assertRaisesRegex(TransitionError, "active Job must resume"):
            self.writer.activate_research_protocol(
                activation=current,
                operation_id="reject-rebind-after-first-job",
                allow_active_unexecuted_study_boundary=True,
            )

    def test_protocol_rebind_supersedes_an_intact_historical_validator(self) -> None:
        self.open_mission_and_initiative()
        self.writer.close_initiative(
            outcome="completed",
            operation_id="historical-validator-close-initiative",
        )
        audit = self.writer.evidence.finalize(
            b"historical validator supersession audit"
        )
        self.writer.validation_registry = EvidenceValidatorRegistry(
            (
                ScientificAdjudicationValidatorV2(),
                ScientificFixtureValidator(),
            )
        )
        control = self.writer.read_control()
        assert control is not None
        historical = ResearchProtocolActivation(
            protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
            validator_id=ScientificFixtureValidator.validator_id,
            authority_manifest_digest=control["authority"]["manifest_digest"],
            audit_artifact_hash=audit.sha256,
        )
        with patch(
            "axiom_rift.research.validation_v2."
            "SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID",
            ScientificFixtureValidator.validator_id,
        ):
            activated = self.writer.activate_research_protocol(
                activation=historical,
                operation_id="activate-historical-scientific-validator",
                allow_active_stable_boundary=True,
            )
        self.assertEqual(activated.result["ordinal"], 1)

        authority_fixture = self.root / "historical-validator-authority"
        authority_paths = (
            control["authority"]["operating_direction"],
            *control["authority"]["contracts"],
            *control["authority"]["foundation_inputs"],
        )
        for relative in authority_paths:
            destination = authority_fixture / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((REPO_ROOT / relative).read_bytes())
        self.writer.foundation_root = authority_fixture
        operations_path = authority_fixture / "contracts/operations.yaml"
        replacement = operations_path.read_bytes() + (
            b"\n# historical validator supersession fixture\n"
        )
        self.writer.migrate_authority(
            replacements={"contracts/operations.yaml": replacement},
            reason="bind the current validator to replacement authority",
            operation_id="migrate-historical-validator-authority",
            allow_active_stable_boundary=True,
        )
        rebound_control = self.writer.read_control()
        assert rebound_control is not None
        current = ResearchProtocolActivation(
            protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
            validator_id=ScientificAdjudicationValidatorV2.validator_id,
            authority_manifest_digest=rebound_control["authority"][
                "manifest_digest"
            ],
            audit_artifact_hash=audit.sha256,
        )
        rebound = self.writer.activate_research_protocol(
            activation=current,
            operation_id="supersede-historical-scientific-validator",
            allow_active_stable_boundary=True,
        )
        self.assertEqual(rebound.result["ordinal"], 2)
        with LocalIndex(self.writer.index_path) as index:
            record = index.get(
                "research-protocol-activation",
                rebound.result["activation_record_id"],
            )
        assert record is not None
        self.assertEqual(
            record.payload["supersedes_activation_record_id"],
            historical.identity,
        )

    def test_job_implementation_rejects_hardcoded_study_identity(self) -> None:
        callable_identity = "fixture.generic.runner"
        source = self.writer.evidence.finalize(
            b'"""Example mentions STU-0001 without binding it."""\n'
            b'# Historical note: STU-0002\n'
            b'STUDY_ID = "STU-" + "9999"\n'
        )
        manifest = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "artifact_hashes": [source.sha256],
                    "callable_identity": callable_identity,
                    "protocol": "python.source.fixture.v1",
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        spec = job_spec(self.writer)
        spec["callable_identity"] = callable_identity
        spec["implementation_identity"] = manifest.sha256
        with self.assertRaisesRegex(TransitionError, "hardcodes"):
            self.writer._require_job_implementation_evidence(spec)

        non_python_source = self.writer.evidence.finalize(
            b'input string StudyId = "STU-9998"; // MQL5 fixture\n'
        )
        non_python_manifest = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "artifact_hashes": [non_python_source.sha256],
                    "callable_identity": callable_identity,
                    "protocol": "mql5.source.fixture.v1",
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        spec["implementation_identity"] = non_python_manifest.sha256
        with self.assertRaisesRegex(TransitionError, "hardcodes"):
            self.writer._require_job_implementation_evidence(spec)

    def test_job_evidence_domain_bindings_are_mutually_exclusive(self) -> None:
        spec = job_spec(self.writer)
        spec["component_parity_binding"] = {}
        spec["external_dependency_binding"] = {}
        with self.assertRaisesRegex(TransitionError, "cannot mix"):
            self.writer._validate_job_spec(spec)

    def test_job_output_names_are_canonical_portable_and_lane_bound(self) -> None:
        for output_name, output_class in (
            ("./evidence/result.json", "durable_evidence"),
            ("src/axiom_rift/result.json", "durable_evidence"),
            ("evidence\\result.json", "durable_evidence"),
            ("C:/evidence/result.json", "durable_evidence"),
            ("evidence/CON.json", "durable_evidence"),
            ("evidence/result./value.json", "durable_evidence"),
            ("local/cache-only.json", "reproducible_cache"),
            ("local/cache/value.json", "transient"),
        ):
            with self.subTest(output_name=output_name):
                spec = job_spec(self.writer)
                spec["expected_outputs"] = [output_name]
                spec["output_classes"] = {output_name: output_class}
                with self.assertRaises(TransitionError):
                    self.writer._validate_job_spec(spec)

        for output_name, output_class in (
            ("evidence/result.json", "durable_evidence"),
            ("scientific/STU-0001/result.json", "durable_evidence"),
            ("source/us500/result.json", "durable_evidence"),
            ("local/cache/value.json", "reproducible_cache"),
            ("local/jobs/value.json", "transient"),
        ):
            with self.subTest(valid_output_name=output_name):
                spec = job_spec(self.writer)
                spec["expected_outputs"] = [output_name]
                spec["output_classes"] = {output_name: output_class}
                self.writer._validate_job_spec(spec)

        for log_path in (
            "../escape.log",
            "local\\jobs\\alias.log",
            "C:/local/jobs/drive.log",
            "local/jobs/CON.log",
            "local/cache/not-a-job.log",
        ):
            with self.subTest(log_path=log_path):
                spec = job_spec(self.writer)
                spec["log_path"] = log_path
                with self.assertRaises(TransitionError):
                    self.writer._validate_job_spec(spec)

        valid_log = job_spec(self.writer)
        valid_log["log_path"] = "local/jobs/research/member-01.log"
        self.writer._validate_job_spec(valid_log)

    def test_job_outputs_and_worker_claims_reject_casefold_aliases(self) -> None:
        spec = job_spec(self.writer)
        spec["expected_outputs"] = [
            "evidence/Result.json",
            "evidence/result.json",
        ]
        spec["output_classes"] = {
            output_name: "durable_evidence"
            for output_name in spec["expected_outputs"]
        }
        with self.assertRaisesRegex(TransitionError, "case-insensitive"):
            self.writer._validate_job_spec(spec)

        claim_alias = job_spec(self.writer)
        claim_alias["worker_claims"][0]["outputs"] = ["Build/Result.json"]
        claim_alias["worker_claims"][1]["outputs"] = ["build/result.json"]
        with self.assertRaisesRegex(TransitionError, "worker outputs overlap"):
            self.writer._validate_job_spec(claim_alias)

        for claim_key, left, right in (
            ("inputs", "Input-A", "input-a"),
            ("resources", "CPU-A", "cpu-a"),
        ):
            with self.subTest(claim_key=claim_key):
                logical_alias = job_spec(self.writer)
                logical_alias["worker_claims"][0][claim_key] = [left]
                logical_alias["worker_claims"][1][claim_key] = [right]
                with self.assertRaisesRegex(
                    TransitionError, f"worker {claim_key} overlap"
                ):
                    self.writer._validate_job_spec(logical_alias)

        worker_alias = job_spec(self.writer)
        worker_alias["worker_claims"][0]["worker_id"] = "Worker-A"
        worker_alias["worker_claims"][1]["worker_id"] = "worker-a"
        with self.assertRaisesRegex(TransitionError, "worker_id values"):
            self.writer._validate_job_spec(worker_alias)

        for claim_key, invalid in (
            ("inputs", ""),
            ("inputs", "input/path"),
            ("resources", "cpu:0"),
            ("resources", "cpu space"),
        ):
            with self.subTest(claim_key=claim_key, invalid=invalid):
                invalid_claim = job_spec(self.writer)
                invalid_claim["worker_claims"][0][claim_key] = [invalid]
                with self.assertRaisesRegex(TransitionError, "logical identifier"):
                    self.writer._validate_job_spec(invalid_claim)

        work_shard_labels = job_spec(self.writer)
        self.assertFalse(
            set(work_shard_labels["worker_claims"][0]["outputs"]).issubset(
                work_shard_labels["expected_outputs"]
            )
        )
        self.writer._validate_job_spec(work_shard_labels)

    def test_scientific_validator_excludes_auxiliary_durable_outputs(self) -> None:
        plan = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "proof_requirements": [
                        {"output_name": "evidence/calculation.json"},
                        {"output_name": "evidence/trace.json"},
                    ],
                    "schema": "scientific_validation_plan.v2",
                }
            )
        )
        output_manifest = {
            "evidence/plan.json": plan.sha256,
            "evidence/result.json": "a" * 64,
            "evidence/measurement.json": "b" * 64,
            "evidence/calculation.json": "c" * 64,
            "evidence/trace.json": "d" * 64,
            "evidence/cache-provenance.json": "e" * 64,
        }
        output_classes = {
            output_name: "durable_evidence"
            for output_name in output_manifest
        }
        routed = self.writer._scientific_validator_artifact_output_names(
            binding={"validation_plan_hash": plan.sha256},
            result_name="evidence/result.json",
            measurement_hashes={"b" * 64},
            output_manifest=output_manifest,
            output_classes=output_classes,
        )
        self.assertEqual(
            routed,
            frozenset(
                {
                    "evidence/plan.json",
                    "evidence/result.json",
                    "evidence/measurement.json",
                    "evidence/calculation.json",
                    "evidence/trace.json",
                }
            ),
        )
        self.assertNotIn("evidence/cache-provenance.json", routed)

    def test_scientific_completion_preserves_exact_multiplicity_registration(
        self,
    ) -> None:
        job_id = "job:" + "1" * 64
        job_hash = "2" * 64
        executable_id = "executable:" + "3" * 64
        claim_id = "selection-control"
        members = (
            executable_id,
            "executable:" + "4" * 64,
            "executable:" + "5" * 64,
        )
        family_id = "selection-family"
        family_hash = canonical_digest(
            domain="scientific-v2-multiplicity-family",
            payload={
                "alpha_ppm": 100_000,
                "family_id": family_id,
                "family_size": len(members),
                "method": "bonferroni_concurrent_family.v1",
                "ordered_member_ids": list(members),
                "schema": "scientific_multiplicity_family_registration.v1",
            },
        )
        registration = {
            "alpha_ppm": 100_000,
            "criterion_id": "E01-familywise-selection",
            "family_id": family_id,
            "family_registration_hash": family_hash,
            "family_size": len(members),
            "member_id": executable_id,
            "method": "bonferroni_concurrent_family.v1",
            "ordered_member_ids": list(members),
        }
        plan = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "adjudication_profile": {
                        "multiplicity": [registration]
                    },
                    "executable_id": executable_id,
                    "mission_id": "MIS-FIXTURE",
                    "schema": "scientific_validation_plan.v2",
                }
            )
        )
        concurrent_family = ConcurrentFamilyManifest(
            evaluation_mode=ConcurrentFamilyEvaluationMode.CONCURRENT,
            executable_ids=members,
        )
        batch_record = IndexRecord(
            kind="batch-open",
            record_id="batch:" + "7" * 64,
            subject="Study:STU-FIXTURE",
            status="open",
            fingerprint="7" * 64,
            payload={
                "spec": {
                    "acceptance_profile": {
                        "concurrent_family": (
                            concurrent_family.to_identity_payload()
                        )
                    },
                    "max_trials": len(members),
                }
            },
        )
        measurement = self.writer.evidence.finalize(b"v2 measurement")
        result = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "evidence_depth": "discovery",
                    "executable_id": executable_id,
                    "job_hash": job_hash,
                    "job_id": job_id,
                    "mission_id": "MIS-FIXTURE",
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
        adjudication = {
            "candidate_eligible": False,
            "claims": [{"claim_id": claim_id}],
            "criteria": [],
            "evaluable": True,
            "evidence_depth": "discovery",
            "invalid_metrics": [],
            "legacy_verdict": "passed",
            "multiplicity": [
                {
                    "adjusted_pvalue_ppm": 20_000,
                    "alpha_ppm": registration["alpha_ppm"],
                    "criterion_id": registration["criterion_id"],
                    "family_id": registration["family_id"],
                    "family_size": registration["family_size"],
                    "method": registration["method"],
                    "raw_pvalue_ppm": 10_000,
                }
            ],
            "schema": "scientific_adjudication.v1",
            "state": "frontier",
        }
        validated = SimpleNamespace(
            candidate_eligible=False,
            claims=(claim_id,),
            facts={
                "executed_evidence_modes": ["temporal_stability"],
                "multiplicity_registrations": [registration],
                "scientific_adjudication": adjudication,
            },
            measurement_artifact_hashes=(measurement.sha256,),
            scientific_eligible=True,
            verdict="passed",
        )
        binding = {
            "evidence_depth": "discovery",
            "evidence_modes": ["temporal_stability"],
            "planned_claims": [claim_id],
            "result_manifest_output": "evidence/result.json",
            "validation_plan_hash": plan.sha256,
            "validator_id": ScientificAdjudicationValidatorV2.validator_id,
        }
        outputs = {
            "evidence/measurement.json": measurement.sha256,
            "evidence/result.json": result.sha256,
        }
        output_classes = {
            name: "durable_evidence" for name in outputs
        }
        with patch.object(
            self.writer,
            "_scientific_validator_artifact_output_names",
            return_value=frozenset(outputs),
        ), patch.object(
            self.writer,
            "_run_registered_validator",
            return_value=(validated, {"validator_id": binding["validator_id"]}),
        ):
            scientific = self.writer._derive_scientific_job_evidence(
                job_id=job_id,
                job_hash=job_hash,
                mission_id="MIS-FIXTURE",
                executable_id=executable_id,
                binding=binding,
                output_manifest=outputs,
                output_classes=output_classes,
                batch_record=batch_record,
                expected_batch_id=batch_record.record_id,
            )
        self.assertEqual(
            scientific["multiplicity_registrations"], [registration]
        )
        self.assertEqual(
            scientific["multiplicity_batch_binding"]["batch_id"],
            batch_record.record_id,
        )
        self.assertEqual(
            scientific["multiplicity_batch_binding"][
                "concurrent_family_identity"
            ],
            concurrent_family.identity,
        )
        self.assertEqual(
            scientific["multiplicity_batch_binding"][
                "ordered_member_ids"
            ],
            list(members),
        )

        reversed_family = ConcurrentFamilyManifest(
            evaluation_mode=ConcurrentFamilyEvaluationMode.CONCURRENT,
            executable_ids=tuple(reversed(members)),
        )
        reversed_batch = IndexRecord(
            kind="batch-open",
            record_id="batch:" + "6" * 64,
            subject="Study:STU-FIXTURE",
            status="open",
            fingerprint="6" * 64,
            payload={
                "spec": {
                    "acceptance_profile": {
                        "concurrent_family": (
                            reversed_family.to_identity_payload()
                        )
                    },
                    "max_trials": len(members),
                }
            },
        )
        with patch.object(
            self.writer,
            "_scientific_validator_artifact_output_names",
            return_value=frozenset(outputs),
        ), patch.object(
            self.writer,
            "_run_registered_validator",
            return_value=(validated, {"validator_id": binding["validator_id"]}),
        ), self.assertRaisesRegex(
            TransitionError, "differs from its exact Batch family"
        ):
            self.writer._derive_scientific_job_evidence(
                job_id=job_id,
                job_hash=job_hash,
                mission_id="MIS-FIXTURE",
                executable_id=executable_id,
                binding=binding,
                output_manifest=outputs,
                output_classes=output_classes,
                batch_record=reversed_batch,
                expected_batch_id=reversed_batch.record_id,
            )

        family_variants = (
            (
                "extra",
                (*members, "executable:" + "8" * 64),
                "8",
            ),
            ("missing", members[:-1], "9"),
        )
        for label, variant_members, marker in family_variants:
            with self.subTest(batch_family=label):
                variant_family = ConcurrentFamilyManifest(
                    evaluation_mode=(
                        ConcurrentFamilyEvaluationMode.CONCURRENT
                    ),
                    executable_ids=variant_members,
                )
                variant_batch = IndexRecord(
                    kind="batch-open",
                    record_id="batch:" + marker * 64,
                    subject="Study:STU-FIXTURE",
                    status="open",
                    fingerprint=marker * 64,
                    payload={
                        "spec": {
                            "acceptance_profile": {
                                "concurrent_family": (
                                    variant_family.to_identity_payload()
                                )
                            },
                            "max_trials": len(variant_members),
                        }
                    },
                )
                with patch.object(
                    self.writer,
                    "_scientific_validator_artifact_output_names",
                    return_value=frozenset(outputs),
                ), patch.object(
                    self.writer,
                    "_run_registered_validator",
                    return_value=(
                        validated,
                        {"validator_id": binding["validator_id"]},
                    ),
                ), self.assertRaisesRegex(
                    TransitionError,
                    "differs from its exact Batch family",
                ):
                    self.writer._derive_scientific_job_evidence(
                        job_id=job_id,
                        job_hash=job_hash,
                        mission_id="MIS-FIXTURE",
                        executable_id=executable_id,
                        binding=binding,
                        output_manifest=outputs,
                        output_classes=output_classes,
                        batch_record=variant_batch,
                        expected_batch_id=variant_batch.record_id,
                    )

        with patch.object(
            self.writer,
            "_scientific_validator_artifact_output_names",
            return_value=frozenset(outputs),
        ), patch.object(
            self.writer,
            "_run_registered_validator",
            return_value=(validated, {"validator_id": binding["validator_id"]}),
        ), self.assertRaisesRegex(
            TransitionError, "belongs to another Batch"
        ):
            self.writer._derive_scientific_job_evidence(
                job_id=job_id,
                job_hash=job_hash,
                mission_id="MIS-FIXTURE",
                executable_id=executable_id,
                binding=binding,
                output_manifest=outputs,
                output_classes=output_classes,
                batch_record=batch_record,
                expected_batch_id="batch:" + "0" * 64,
            )

        wrong_member_registration = {
            **registration,
            "member_id": members[1],
        }
        wrong_member_plan = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "adjudication_profile": {
                        "multiplicity": [wrong_member_registration]
                    },
                    "executable_id": executable_id,
                    "mission_id": "MIS-FIXTURE",
                    "schema": "scientific_validation_plan.v2",
                }
            )
        )
        wrong_member_binding = {
            **binding,
            "validation_plan_hash": wrong_member_plan.sha256,
        }
        wrong_member_validated = SimpleNamespace(
            candidate_eligible=False,
            claims=(claim_id,),
            facts={
                "executed_evidence_modes": ["temporal_stability"],
                "multiplicity_registrations": [
                    wrong_member_registration
                ],
                "scientific_adjudication": adjudication,
            },
            measurement_artifact_hashes=(measurement.sha256,),
            scientific_eligible=True,
            verdict="passed",
        )
        with patch.object(
            self.writer,
            "_scientific_validator_artifact_output_names",
            return_value=frozenset(outputs),
        ), patch.object(
            self.writer,
            "_run_registered_validator",
            return_value=(
                wrong_member_validated,
                {"validator_id": binding["validator_id"]},
            ),
        ), self.assertRaisesRegex(
            TransitionError, "differs from its exact Batch family"
        ):
            self.writer._derive_scientific_job_evidence(
                job_id=job_id,
                job_hash=job_hash,
                mission_id="MIS-FIXTURE",
                executable_id=executable_id,
                binding=wrong_member_binding,
                output_manifest=outputs,
                output_classes=output_classes,
                batch_record=batch_record,
                expected_batch_id=batch_record.record_id,
            )

        with patch.object(
            self.writer,
            "_scientific_validator_artifact_output_names",
            return_value=frozenset(outputs),
        ), patch.object(
            self.writer,
            "_run_registered_validator",
            return_value=(validated, {"validator_id": binding["validator_id"]}),
        ), self.assertRaisesRegex(
            TransitionError, "lacks an exact concurrent Batch"
        ):
            self.writer._derive_scientific_job_evidence(
                job_id=job_id,
                job_hash=job_hash,
                mission_id="MIS-FIXTURE",
                executable_id=executable_id,
                binding=binding,
                output_manifest=outputs,
                output_classes=output_classes,
                expected_batch_id=batch_record.record_id,
            )

        arbitrary = parse_canonical(canonical_bytes(validated.facts))
        arbitrary["multiplicity_registrations"][0][
            "ordered_member_ids"
        ].reverse()
        validated.facts = arbitrary
        with patch.object(
            self.writer,
            "_scientific_validator_artifact_output_names",
            return_value=frozenset(outputs),
        ), patch.object(
            self.writer,
            "_run_registered_validator",
            return_value=(validated, {"validator_id": binding["validator_id"]}),
        ), self.assertRaisesRegex(
            TransitionError, "differ from the durable plan"
        ):
            self.writer._derive_scientific_job_evidence(
                job_id=job_id,
                job_hash=job_hash,
                mission_id="MIS-FIXTURE",
                executable_id=executable_id,
                binding=binding,
                output_manifest=outputs,
                output_classes=output_classes,
                batch_record=batch_record,
                expected_batch_id=batch_record.record_id,
            )

    def test_scientific_schema_preflight_runs_before_job_declaration(self) -> None:
        validator_id = "validator:" + "a" * 64
        plan_hash = "b" * 64
        result_name = "evidence/preflight-result"
        measurement_name = "evidence/preflight-measurement"
        spec = job_spec(
            self.writer,
            {"kind": "Executable", "id": "executable:" + "c" * 64},
        )
        spec["input_hashes"] = [*spec["input_hashes"], plan_hash]
        spec["expected_outputs"] = [measurement_name, result_name]
        spec["output_classes"] = {
            measurement_name: "durable_evidence",
            result_name: "durable_evidence",
        }
        spec["scientific_binding"] = {
            "evidence_depth": "discovery",
            "evidence_modes": [
                "causal_contrast",
                "cost_and_execution",
                "sensitivity_or_stress",
            ],
            "evaluation_schema": "unregistered_evaluation.v1",
            "planned_claims": ["claim-a"],
            "result_manifest_output": result_name,
            "validation_plan_hash": plan_hash,
            "validator_id": validator_id,
        }
        calls: list[dict[str, object]] = []

        def reject_preflight(**kwargs: object) -> None:
            calls.append(dict(kwargs))
            raise EvidenceValidationError("evaluation schema is not registered")

        self.writer.validation_registry = SimpleNamespace(
            preflight_binding=reject_preflight
        )
        before = self.writer.read_control()

        with self.assertRaisesRegex(
            TransitionError, "scientific validation preflight failed"
        ):
            self.writer.declare_job(
                spec=spec, operation_id="reject-unregistered-evaluation-schema"
            )

        self.assertEqual(self.writer.read_control(), before)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["domain"], "scientific")

    def test_component_manifest_backfill_is_zero_credit_and_idempotent(self) -> None:
        legacy = executable_spec("legacy-component-projection")

        def seed(current, _index):
            assert current is not None
            record = IndexRecord(
                kind="trial",
                record_id=legacy.identity,
                subject="Batch:legacy",
                status="evaluated",
                fingerprint=legacy.identity.removeprefix("executable:"),
                payload={"executable": legacy.to_identity_payload()},
            )
            return self.writer._body(current), [record], {"seeded": True}

        before = self.writer.read_control()
        assert before is not None
        self.writer._commit(
            event_kind="legacy_trial_fixture_seeded",
            operation_id="legacy-trial-fixture-seed",
            subject="Executable:legacy",
            payload={"trial_delta": 0},
            prepare=seed,
        )
        result = self.writer.backfill_component_manifests(
            operation_id="component-manifest-backfill-fixture"
        )
        self.assertEqual(result.result["trial_delta"], 0)
        self.assertEqual(result.result["holdout_delta"], 0)
        self.assertEqual(result.result["claim"], "none")
        self.assertEqual(result.result["component_manifest_count"], 1)
        with LocalIndex(self.writer.index_path) as index:
            component_record = index.get(
                "component-manifest", legacy.component_identities[0]
            )
        self.assertIsNotNone(component_record)
        after = self.writer.read_control()
        assert after is not None
        self.assertEqual(after["next_action"], before["next_action"])
        self.assertEqual(after["scientific"], before["scientific"])
        reused = self.writer.backfill_component_manifests(
            operation_id="component-manifest-backfill-fixture"
        )
        self.assertTrue(reused.reused)

    def test_executable_surface_backfill_is_zero_credit_and_idempotent(self) -> None:
        legacy = executable_spec("legacy-executable-surface")
        legacy_component = legacy.components[0]
        alias_component = ComponentSpec(
            display_name="legacy protocol alias",
            protocol="feature.engineering_fixture.v7",
            implementation=legacy_component.implementation,
            spec=legacy_component.specification(),
            semantic_dependencies=legacy_component.semantic_dependencies,
        )
        alias = ExecutableSpec(
            display_name="legacy executable protocol alias",
            components=(alias_component,),
            parameters=legacy.parameter_values(),
            data_contract=legacy.data_contract,
            split_contract=legacy.split_contract,
            clock_contract=legacy.clock_contract,
            cost_contract=legacy.cost_contract,
            engine_contract=legacy.engine_contract,
        )

        def seed(current, _index):
            assert current is not None
            records = [
                IndexRecord(
                    kind="trial",
                    record_id=value.identity,
                    subject="Batch:legacy",
                    status="evaluated",
                    fingerprint=value.identity.removeprefix("executable:"),
                    payload={"executable": value.to_identity_payload()},
                )
                for value in (legacy, alias)
            ]
            return self.writer._body(current), records, {"seeded": True}

        before = self.writer.read_control()
        assert before is not None
        self.writer._commit(
            event_kind="legacy_surface_trial_fixture_seeded",
            operation_id="legacy-surface-trial-fixture-seed",
            subject="Executable:legacy",
            payload={"trial_delta": 0},
            prepare=seed,
        )
        result = self.writer.backfill_executable_semantic_surfaces(
            operation_id="executable-surface-backfill-fixture"
        )
        self.assertEqual(result.result["trial_delta"], 0)
        self.assertEqual(result.result["holdout_delta"], 0)
        self.assertEqual(result.result["claim"], "none")
        self.assertEqual(result.result["exact_executable_count"], 2)
        self.assertEqual(result.result["surface_count"], 1)
        from axiom_rift.research.chassis import (
            executable_semantic_surface_identity,
        )

        surface_id = executable_semantic_surface_identity(legacy)
        with LocalIndex(self.writer.index_path) as index:
            surface = index.get("executable-surface", surface_id)
        self.assertIsNotNone(surface)
        assert surface is not None
        self.assertEqual(
            surface.payload["exact_executable_ids"],
            sorted((legacy.identity, alias.identity)),
        )
        after = self.writer.read_control()
        assert after is not None
        self.assertEqual(after["next_action"], before["next_action"])
        self.assertEqual(after["scientific"], before["scientific"])
        reused = self.writer.backfill_executable_semantic_surfaces(
            operation_id="executable-surface-backfill-fixture"
        )
        self.assertTrue(reused.reused)

    def test_legacy_surface_collision_allows_exact_reuse_only(self) -> None:
        original = ComponentSpec(
            display_name="legacy feature v1",
            protocol="feature.legacy_control.v1",
            implementation="fixture.legacy.control",
            spec={"meaning": "fixed", "parameter_fields": []},
        )
        legacy_alias = ComponentSpec(
            display_name="legacy feature v2",
            protocol="feature.legacy_control.v2",
            implementation=original.implementation,
            spec=original.specification(),
        )
        exact = ExecutableSpec(
            display_name="exact legacy reuse",
            components=(legacy_alias,),
            parameters={},
            data_contract="data:fixture",
            split_contract="split:fixture",
            clock_contract="clock:fixture",
            cost_contract="cost:fixture",
            engine_contract="engine:fixture",
        )
        new_alias = ComponentSpec(
            display_name="legacy feature v3",
            protocol="feature.legacy_control.v3",
            implementation=original.implementation,
            spec=original.specification(),
        )
        drifted = ExecutableSpec(
            display_name="new legacy alias",
            components=(new_alias,),
            parameters={},
            data_contract=exact.data_contract,
            split_contract=exact.split_contract,
            clock_contract=exact.clock_contract,
            cost_contract=exact.cost_contract,
            engine_contract=exact.engine_contract,
        )
        duplicate_surface = ExecutableSpec(
            display_name="two aliases in one Executable",
            components=(original, legacy_alias),
            parameters={},
            data_contract=exact.data_contract,
            split_contract=exact.split_contract,
            clock_contract=exact.clock_contract,
            cost_contract=exact.cost_contract,
            engine_contract=exact.engine_contract,
        )
        meaning_change = ComponentSpec(
            display_name="meaningful feature change",
            protocol=original.protocol,
            implementation=original.implementation,
            spec={"meaning": "changed", "parameter_fields": []},
        )
        changed = ExecutableSpec(
            display_name="meaningful changed component",
            components=(meaning_change,),
            parameters={},
            data_contract=exact.data_contract,
            split_contract=exact.split_contract,
            clock_contract=exact.clock_contract,
            cost_contract=exact.cost_contract,
            engine_contract=exact.engine_contract,
        )
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                self.writer._component_manifest_record(
                    component_id=original.identity,
                    manifest=original.to_identity_payload(),
                )
            )
            index.put(
                self.writer._component_manifest_record(
                    component_id=legacy_alias.identity,
                    manifest=legacy_alias.to_identity_payload(),
                )
            )
            self.assertEqual(
                self.writer._project_executable_components(index, exact), []
            )
            with self.assertRaisesRegex(TransitionError, "protocol/name drift"):
                self.writer._project_executable_components(index, drifted)
            with self.assertRaisesRegex(TransitionError, "duplicate protocol-neutral"):
                self.writer._project_executable_components(
                    index, duplicate_surface
                )
            projected = self.writer._project_executable_components(index, changed)
            self.assertEqual(
                [record.record_id for record in projected],
                [meaning_change.identity],
            )

    def test_architecture_parity_unifies_legacy_protocol_alias_endpoints(self) -> None:
        from axiom_rift.research.chassis import (
            architecture_component_semantic_surface_identity,
        )

        first_alias = ComponentSpec(
            display_name="legacy model v1",
            protocol="model.legacy_alias.v1",
            implementation="fixture.legacy.model",
            spec={"meaning": "same"},
        )
        second_alias = ComponentSpec(
            display_name="legacy model v7",
            protocol="model.legacy_alias.v7",
            implementation=first_alias.implementation,
            spec=first_alias.specification(),
        )
        first_refactor = ComponentSpec(
            display_name="first model refactor",
            protocol=first_alias.protocol,
            implementation="fixture.refactor.model.first",
            spec=first_alias.specification(),
        )
        second_refactor = ComponentSpec(
            display_name="second model refactor",
            protocol=second_alias.protocol,
            implementation="fixture.refactor.model.second",
            spec=second_alias.specification(),
        )
        edges = (
            ComponentParityEvidence(
                canonical_component=first_alias,
                equivalent_component=first_refactor,
                dimensions=tuple(ComponentParityDimension),
                parity_manifest_hash="a" * 64,
                completion_record_id="1" * 64,
            ).to_identity_payload(),
            ComponentParityEvidence(
                canonical_component=second_alias,
                equivalent_component=second_refactor,
                dimensions=tuple(ComponentParityDimension),
                parity_manifest_hash="b" * 64,
                completion_record_id="2" * 64,
            ).to_identity_payload(),
        )
        replacements = self.writer._architecture_parity_surface_replacements(edges)
        surfaces = {
            replacements[
                architecture_component_semantic_surface_identity(component)
            ]
            for component in (
                first_alias,
                second_alias,
                first_refactor,
                second_refactor,
            )
        }
        self.assertEqual(len(surfaces), 1)

    def test_seeded_parity_resolution_does_not_scan_unrelated_history(self) -> None:
        with LocalIndex(self.writer.index_path) as index:
            index.records_by_kind = lambda _kind: (_ for _ in ()).throw(  # type: ignore[method-assign]
                AssertionError("seeded parity resolution used a full history scan")
            )
            resolved = self.writer._verified_component_parity_edges(
                index,
                surface_seeds=("architecture-component-surface:" + "a" * 64,),
            )
        self.assertEqual(resolved, ())

    def test_legacy_axis_prospective_anchor_cannot_split_by_name(self) -> None:
        legacy_axis = {
            "architecture_chassis": None,
            "architecture_chassis_identity": None,
            "axis_identity": "axis:legacy-fixture",
        }
        first_payload = {
            "architecture_chassis": {"schema": "architecture_chassis.v1"},
            "architecture_chassis_identity": "architecture-family:" + "a" * 64,
            "baseline_executable": {"schema": "executable_spec.v1"},
            "baseline_executable_id": "executable:" + "b" * 64,
            "target_axis_identity": legacy_axis["axis_identity"],
        }
        second_payload = {
            **first_payload,
            "architecture_chassis_identity": "architecture-family:" + "c" * 64,
        }
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                IndexRecord(
                    kind="portfolio-decision",
                    record_id="decision:" + "1" * 64,
                    subject="Mission:MIS-LEGACY",
                    status="deepen",
                    fingerprint="1" * 64,
                    payload=first_payload,
                )
            )
            with patch.object(
                index,
                "records_by_kind",
                side_effect=AssertionError(
                    "legacy axis anchor decoded unrelated Decision history"
                ),
            ):
                anchor = self.writer._axis_architecture_anchor(index, legacy_axis)
            assert anchor is not None
            self.assertEqual(
                anchor["architecture_chassis_identity"],
                first_payload["architecture_chassis_identity"],
            )
            index.put(
                IndexRecord(
                    kind="portfolio-decision",
                    record_id="decision:" + "2" * 64,
                    subject="Mission:MIS-LEGACY",
                    status="deepen",
                    fingerprint="2" * 64,
                    payload=second_payload,
                )
            )
            with patch.object(
                index,
                "records_by_kind",
                side_effect=AssertionError(
                    "legacy axis anchor decoded unrelated Decision history"
                ),
            ), self.assertRaisesRegex(RecoveryRequired, "conflicting"):
                self.writer._axis_architecture_anchor(index, legacy_axis)

    def test_existing_axis_chassis_requires_prior_trial_baseline(self) -> None:
        baseline = scientific_executable_spec("prior-baseline")
        invented = scientific_executable_spec("invented-baseline")
        axis_identity = "axis:" + "7" * 64
        self.assertNotEqual(baseline.identity, invented.identity)
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                IndexRecord(
                    kind="study-open",
                    record_id="STU-7000",
                    subject="Study:STU-7000",
                    status="open",
                    fingerprint="7" * 64,
                    payload={
                        "controlled_chassis": {
                            "baseline_executable": baseline.to_identity_payload(),
                        },
                        "mission_id": "MIS-PRIOR",
                        "portfolio_axis_identity": axis_identity,
                    },
                )
            )
            index.put(
                IndexRecord(
                    kind="trial",
                    record_id=baseline.identity,
                    subject="Batch:BAT-PRIOR",
                    status="evaluated",
                    fingerprint=baseline.identity.removeprefix("executable:"),
                    payload={
                        "engineering_fixture": False,
                        "executable": baseline.to_identity_payload(),
                        "mission_id": "MIS-PRIOR",
                        "scientific_eligible": True,
                        "study_id": "STU-7000",
                    },
                )
            )

            class ExactBaselineIndex:
                def get(self, kind: str, record_id: str):
                    return index.get(kind, record_id)

                def records_by_kind(self, kind: str):
                    if kind == "trial":
                        raise AssertionError(
                            "exact scientific baseline performed a global trial scan"
                        )
                    return index.records_by_kind(kind)

            self.assertEqual(
                self.writer._prior_scientific_baseline(
                    ExactBaselineIndex(), baseline, axis_identity
                ).record_id,
                baseline.identity,
            )
            with self.assertRaisesRegex(TransitionError, "prior scientific"):
                self.writer._prior_scientific_baseline(
                    index, invented, axis_identity
                )

    def test_architecture_review_inventory_is_mission_keyed_and_parity_aware(
        self,
    ) -> None:
        mission_id = "MIS-ARCHITECTURE-LOOKUP"
        snapshot_id = "portfolio:" + "6" * 64
        reviewed_id = "diagnosis:" + "1" * 64
        pending_id = "diagnosis:" + "2" * 64
        study_id = "STU-ARCHITECTURE-LOOKUP"
        family = "architecture-family:" + "3" * 64
        parity = ({"equivalence": "bounded-fixture"},)
        with LocalIndex(self.writer.index_path) as index:
            index.put_many(
                (
                    IndexRecord(
                        kind="portfolio-snapshot",
                        record_id=snapshot_id,
                        subject=f"Mission:{mission_id}",
                        status="active",
                        fingerprint="6" * 64,
                        payload={
                            "exhaustion_standard": {
                                "architecture_review_minimum_axes": 1,
                                "architecture_review_minimum_studies": 1,
                            },
                            "mission_id": mission_id,
                        },
                    ),
                    IndexRecord(
                        kind="study-open",
                        record_id=study_id,
                        subject=f"Study:{study_id}",
                        status="open",
                        fingerprint="7" * 64,
                        payload={"mission_id": mission_id},
                    ),
                    *(
                        IndexRecord(
                            kind="study-diagnosis",
                            record_id=record_id,
                            subject=f"Study:{study_id}",
                            status="contradicted",
                            fingerprint=str(ordinal) * 64,
                            payload={
                                "evidence_state": "contradicted",
                                "mission_id": mission_id,
                                "portfolio_axis_id": f"axis-{ordinal}",
                                "primary_research_layer": "system_architecture",
                                "study_id": study_id,
                            },
                        )
                        for ordinal, record_id in enumerate(
                            (reviewed_id, pending_id),
                            start=1,
                        )
                    ),
                    IndexRecord(
                        kind="architecture-review",
                        record_id="architecture-review:" + "8" * 64,
                        subject=f"Mission:{mission_id}",
                        status="rotate",
                        fingerprint="8" * 64,
                        payload={
                            "covered_diagnosis_ids": [reviewed_id],
                            "mission_id": mission_id,
                        },
                    ),
                    IndexRecord(
                        kind="study-diagnosis",
                        record_id="diagnosis:" + "9" * 64,
                        subject="Study:STU-UNRELATED",
                        status="contradicted",
                        fingerprint="9" * 64,
                        payload={"mission_id": "MIS-UNRELATED"},
                    ),
                )
            )
            payload_calls: list[tuple[str, str, str]] = []
            payload_lookup = index.records_by_payload_text

            def counted_payload(kind: str, lookup_name: str, value: str):
                payload_calls.append((kind, lookup_name, value))
                return payload_lookup(kind, lookup_name, value)

            with patch.object(
                index,
                "records_by_payload_text",
                side_effect=counted_payload,
            ), patch.object(
                index,
                "records_by_kind",
                side_effect=AssertionError(
                    "architecture review decoded project-wide history"
                ),
            ), patch.object(
                self.writer,
                "_study_resolved_architecture_family",
                return_value=family,
            ) as resolve_family:
                trigger = self.writer._pending_architecture_review_trigger(
                    index=index,
                    mission_id=mission_id,
                    portfolio_snapshot_id=snapshot_id,
                    architecture_family=family,
                    extra_equivalences=parity,
                )
            expected_study = index.get("study-open", study_id)
        assert trigger is not None
        self.assertEqual(trigger.payload["diagnosis_ids"], [pending_id])
        self.assertEqual(
            payload_calls,
            [
                ("architecture-review", "mission_id", mission_id),
                ("study-diagnosis", "mission_id", mission_id),
            ],
        )
        resolve_family.assert_called_once_with(
            index=index,
            study=expected_study,
            extra_equivalences=parity,
        )

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

    def test_completed_job_budget_overreservation_has_typed_repair(self) -> None:
        self.open_mission_and_initiative()
        opened = self.open_fixture_study(
            study_id="STU-BUDGET-REPAIR",
            question=study_question("typed Batch budget repair"),
            semantic_proposal={"mechanism": "budget reservation repair"},
            operation_prefix="budget-repair-study",
        )
        batch = batch_spec(
            batch_id="BAT-BUDGET-REPAIR",
            study_id="STU-BUDGET-REPAIR",
            study_hash=opened.result["study_hash"],
            max_trials=2,
            max_compute_seconds=40,
        )
        batch_permit = self.writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-BUDGET-REPAIR",
            input_hash=batch.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="budget-repair-batch-permit",
        )
        self.writer.open_batch(
            batch_spec=batch,
            permit=batch_permit,
            operation_id="budget-repair-batch-open",
        )
        first_spec = job_spec(
            self.writer,
            {"kind": "Study", "id": "STU-BUDGET-REPAIR"},
        )
        first = self.writer.declare_job(
            spec=first_spec,
            operation_id="budget-repair-first-declare",
        )
        first_permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=first.result["job_id"],
            input_hash=first.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="budget-repair-first-permit",
        )
        self.writer.start_job(
            permit=first_permit,
            operation_id="budget-repair-first-start",
        )
        output = self.writer.root / "local" / "jobs" / "fixture" / "fixture.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"typed budget repair fixture")
        completed = self.writer.complete_job(
            outcome="success",
            output_manifest={
                "local/jobs/fixture/fixture.json": sha256(
                    b"typed budget repair fixture"
                ).hexdigest()
            },
            operation_id="budget-repair-first-complete",
        )
        self.writer.judge_job_evidence(
            completion_record_id=completed.result["completion_record_id"],
            disposition="continue_batch",
            operation_id="budget-repair-first-judge",
        )
        second_spec = job_spec(
            self.writer,
            {"kind": "Study", "id": "STU-BUDGET-REPAIR"},
        )
        second_spec["input_hashes"] = [
            *second_spec["input_hashes"],
            digest("input", {"budget_repair_second": True}),
        ]
        with self.assertRaisesRegex(TransitionError, "exceeds the frozen Batch"):
            self.writer.declare_job(
                spec=second_spec,
                operation_id="budget-repair-second-rejected",
            )
        corrected = {
            first.result["job_id"]: {
                "compute_seconds": 10,
                "wall_seconds": 10,
            }
        }
        policy_id = "fixture.completed_job_reservation.v1"
        reason = "release a proven completed Job over-reservation"
        manifest = self.writer.plan_batch_budget_reservation_repair(
            corrected_job_budgets=corrected,
            policy_id=policy_id,
            reason=reason,
        )
        proof = self.writer.evidence.finalize(canonical_bytes(manifest))
        repaired = self.writer.repair_batch_budget_reservations(
            corrected_job_budgets=corrected,
            policy_id=policy_id,
            reason=reason,
            proof_hash=proof.sha256,
            operation_id="budget-repair-apply",
        )
        self.assertEqual(
            repaired.result["corrected_reserved_totals"],
            {"compute_seconds": 10, "wall_seconds": 10},
        )
        self.assertEqual(repaired.result["scientific_trial_delta"], 0)
        second = self.writer.declare_job(
            spec=second_spec,
            operation_id="budget-repair-second-declare",
        )
        self.assertTrue(second.result["job_id"].startswith("job:"))
        with LocalIndex(self.writer.index_path) as index:
            repairs = tuple(index.records_by_kind("batch-budget-repair"))
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0].payload["proof_hash"], proof.sha256)

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
        started = self.writer.start_job(
            permit=permit, operation_id="active-job-start"
        )
        execution = RunningJobExecution.from_mapping(started.result["execution"])
        stable_before_verification = self.writer.read_control()
        writer_binding = self.writer.verify_running_job_execution(
            execution,
            expected_callable_identity="fixture.callable",
            expected_evidence_subject={
                "kind": "Mission",
                "id": "MIS-ACTIVE-JOB",
            },
            required_input_hashes=(digest("input", {"fixture": 1}),),
        )
        authority = RunningJobAuthority(
            self.writer.root,
            foundation_root=self.writer.foundation_root,
        )
        self.assertFalse(hasattr(authority, "evidence"))
        authority_binding = authority.verify_running_job_execution(
            execution,
            expected_callable_identity="fixture.callable",
            expected_evidence_subject={
                "kind": "Mission",
                "id": "MIS-ACTIVE-JOB",
            },
            required_input_hashes=(digest("input", {"fixture": 1}),),
        )
        self.assertEqual(authority_binding, writer_binding)
        self.assertEqual(
            self.writer.read_control(),
            stable_before_verification,
        )
        forged = RunningJobExecution(
            job_id=execution.job_id,
            job_hash=execution.job_hash,
            start_record_id="0" * 64,
            job_permit_id=execution.job_permit_id,
        )
        with self.assertRaises(PermitError):
            self.writer.verify_running_job_execution(
                forged,
                expected_callable_identity="fixture.callable",
                expected_evidence_subject={
                    "kind": "Mission",
                    "id": "MIS-ACTIVE-JOB",
                },
            )
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
                study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
                foundation_root=REPO_ROOT,
            )
            writer.initialize_ready()
            writer.open_mission(
                mission_id="MIS-EXTERNAL-VALIDATOR",
                goal=mission_goal("external dependency validation"),
                operation_id="external-validator-mission",
            )
            record_fixture_research_intake(
                writer,
                mission_id="MIS-EXTERNAL-VALIDATOR",
                operation_id="external-validator-intake",
            )
            plan = writer.evidence.finalize(b"external validation plan fixture")
            recovery_plan = ExternalRecoveryPlan(
                boundary_event_id=writer.read_control()["heads"]["journal"][  # type: ignore[index]
                    "event_id"
                ],
                condition=ExternalResumeCondition(
                    dependency_id="fpmarkets-history-service",
                    dependency_kind="market_data_service",
                    blocked_mission_capability=(
                        "indispensable broker history acquisition"
                    ),
                    required_external_change=(
                        "broker history service becomes available"
                    ),
                    validator_id="validator:" + "f" * 64,
                    validation_plan_hash=plan.sha256,
                    resume_action=ExternalResumeAction.from_next_action(
                        writer.read_control()["next_action"]  # type: ignore[index]
                    ),
                ),
                paths=(
                    ExternalRecoveryPath(
                        recovery_kind="external_probe",
                        recovery_path_id="broker-history-probe",
                    ),
                    ExternalRecoveryPath(
                        recovery_kind="local_recovery",
                        recovery_path_id="broker-history-local-recovery",
                    ),
                    ExternalRecoveryPath(
                        recovery_kind="safe_substitute_search",
                        recovery_path_id="broker-history-substitute-search",
                    ),
                ),
            )
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
                "recovery_plan": recovery_plan.to_identity_payload(),
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
            writer = StateWriter(
                root,
                clock=lambda: FIXED_NOW,
                study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
                foundation_root=REPO_ROOT,
            )
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

    def test_pre_intake_generic_job_cannot_guess_a_future_study(self) -> None:
        with TemporaryDirectory() as root:
            writer = StateWriter(
                root,
                permit_authority=PermitAuthority(b"g" * 32),
                clock=lambda: FIXED_NOW,
                study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
                foundation_root=REPO_ROOT,
            )
            writer.initialize_ready()
            writer.open_mission(
                mission_id="MIS-PRE-INTAKE-JOB",
                goal=mission_goal("pre-intake Job rejection"),
                operation_id="pre-intake-job-mission",
            )
            self.assertEqual(
                writer.read_control()["next_action"]["kind"],  # type: ignore[index]
                "record_research_intake",
            )
            with self.assertRaisesRegex(TransitionError, "cannot bypass pending research intake"):
                writer.declare_job(
                    spec=job_spec(
                        writer,
                        {"kind": "Mission", "id": "MIS-PRE-INTAKE-JOB"},
                    ),
                    operation_id="reject-pre-intake-guessed-study-job",
                )

    def test_deferred_axis_requires_preserve_before_work_but_remains_an_option(self) -> None:
        self.open_mission_and_initiative()
        open_axis = PortfolioAxis(
            axis_id="axis-open-work",
            causal_question="Does the open axis add bounded information?",
            mechanism_family="open-work-family",
        )
        deferred_axis = PortfolioAxis(
            axis_id="axis-deferred-work",
            causal_question="Should the deferred axis be explicitly reopened?",
            mechanism_family="deferred-work-family",
            status="deferred",
        )
        snapshot = PortfolioSnapshot(
            mission_id="MIS-FIXTURE",
            axes=(open_axis, deferred_axis),
            opportunity_cost_basis="preserve the deferred forest branch",
        )
        self.writer.record_portfolio_snapshot(
            snapshot=snapshot,
            operation_id="deferred-axis-snapshot",
        )
        direct_work = PortfolioDecision(
            decision_id="DEC-DEFERRED-DIRECT-WORK",
            chosen_option_id="work-deferred",
            options=(
                DecisionOption(
                    option_id="work-deferred",
                    action=PortfolioAction.CONTRAST,
                    target_id=deferred_axis.axis_id,
                    expected_information_value="unknown until explicitly reopened",
                    opportunity_cost="one unauthorized Batch",
                ),
                DecisionOption(
                    option_id="retain-open",
                    action=PortfolioAction.CONTRAST,
                    target_id=open_axis.axis_id,
                    expected_information_value="positive",
                    opportunity_cost="defer one Batch",
                    omission_reason="the invalid direct work was nominally chosen",
                ),
            ),
            rationale="exercise the deferred-axis work guard",
            commitment_batches=1,
        )
        with self.assertRaisesRegex(
            TransitionError,
            "requires an exact preserve/reopen Decision",
        ):
            self.writer.record_portfolio_decision(
                decision=direct_work,
                operation_id="reject-deferred-axis-direct-work",
            )

        reopen = PortfolioDecision(
            decision_id="DEC-DEFERRED-PRESERVE",
            chosen_option_id="preserve-deferred",
            options=(
                DecisionOption(
                    option_id="preserve-deferred",
                    action=PortfolioAction.PRESERVE,
                    target_id=deferred_axis.axis_id,
                    expected_information_value="retain and explicitly reopen the branch",
                    opportunity_cost="one structural snapshot transition",
                ),
                DecisionOption(
                    option_id="retain-open",
                    action=PortfolioAction.CONTRAST,
                    target_id=open_axis.axis_id,
                    expected_information_value="positive",
                    opportunity_cost="defer one Batch",
                    omission_reason="the deferred branch needs explicit preservation",
                ),
            ),
            rationale="use the typed structural boundary before scientific work",
            commitment_batches=1,
        )
        self.writer.record_portfolio_decision(
            decision=reopen,
            operation_id="preserve-deferred-axis",
        )
        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["next_action"]["kind"], "record_portfolio_snapshot")
        self.assertEqual(control["next_action"]["action"], "preserve")

    def test_portfolio_decision_requires_a_current_declared_target(self) -> None:
        self.open_mission_and_initiative()
        contract = source_contract()
        context = SourceEligibility.register(contract)
        self.writer.record_source_eligibility(
            eligibility=context,
            receipt=None,
            operation_id="register-audit-invalidated-source",
        )
        historical_artifact = self.writer.evidence.finalize(
            b"historical point-in-time source fixture"
        )
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
        audited = context.complete_historical_audit(historical_receipt.identity)
        self.writer.record_source_eligibility(
            eligibility=audited,
            receipt=historical_receipt,
            operation_id="audit-invalidated-source",
        )
        runtime_artifact = self.writer.evidence.finalize(
            b"runtime source fixture before audit invalidation"
        )
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
        eligible = audited.prove_runtime_availability(runtime_receipt.identity)
        self.writer.record_source_eligibility(
            eligibility=eligible,
            receipt=runtime_receipt,
            operation_id="qualify-invalidated-source",
        )
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

        def seed_scheduler_constraint(current, _index):
            assert current is not None
            body = self.writer._body(current)
            action = dict(body["next_action"])
            action.update(
                {
                    "constraint_source_id": "portfolio-fixture:source-audit",
                    "required_target_axis_ids": ["axis-microstructure"],
                }
            )
            body["next_action"] = action
            return body, [], {"seeded": True}

        self.writer._commit(
            event_kind="portfolio_scheduler_constraint_fixture_seeded",
            operation_id="seed-portfolio-scheduler-constraint",
            subject="Portfolio:active",
            payload={"target_id": "axis-microstructure"},
            prepare=seed_scheduler_constraint,
        )
        unconstrained_baseline = scientific_executable_spec("withdrawal-source")
        unconstrained_component = unconstrained_baseline.components[-1]
        source_component = ComponentSpec(
            display_name="withdrawal source fixture component",
            protocol=unconstrained_component.protocol,
            implementation=unconstrained_component.implementation,
            spec=unconstrained_component.specification(),
            semantic_dependencies=(
                *unconstrained_component.semantic_dependencies,
                contract.source_contract_id,
            ),
        )
        source_baseline = ExecutableSpec(
            display_name="withdrawal source fixture executable",
            components=(
                *unconstrained_baseline.components[:-1],
                source_component,
            ),
            parameters=unconstrained_baseline.parameter_values(),
            data_contract=unconstrained_baseline.data_contract,
            split_contract=unconstrained_baseline.split_contract,
            clock_contract=unconstrained_baseline.clock_contract,
            cost_contract=unconstrained_baseline.cost_contract,
            engine_contract=unconstrained_baseline.engine_contract,
            source_contracts=(contract.source_contract_id,),
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
            baseline_executable=source_baseline,
        )
        recorded = self.writer.record_portfolio_decision(
            decision=valid, operation_id="record-valid-portfolio-target"
        )
        self.assertEqual(recorded.result["decision_id"], valid.identity)
        self.assertEqual(
            self.writer.read_control()["next_action"]["target_id"],  # type: ignore[index]
            "axis-microstructure",
        )
        with LocalIndex(self.writer.index_path) as index:
            source_head = index.event_head(
                f"source:{contract.source_contract_id}"
            )
            accepted_decision = index.get("portfolio-decision", valid.identity)
        assert source_head is not None
        assert accepted_decision is not None
        self.assertEqual(
            accepted_decision.payload["scheduler_constraints"],
            {
                "constraint_source_id": "portfolio-fixture:source-audit",
                "required_target_axis_ids": ["axis-microstructure"],
            },
        )
        self.assertEqual(
            accepted_decision.payload["source_authority_subject_ids"],
            [contract.source_contract_id],
        )
        report = self.writer.evidence.finalize(
            source_audit_report_bytes(
                finding_id="SOURCE-AUTH-001",
                source_contract_id=contract.source_contract_id,
                source_state_record_id=source_head.record_id,
            )
        )
        target_axis = next(
            axis
            for axis in snapshot.to_identity_payload()["axes"]
            if axis["axis_id"] == "axis-microstructure"
        )
        withdrawal_manifest = PortfolioDecisionWithdrawalManifest(
            report_artifact_hash=report.sha256,
            report_finding_id="SOURCE-AUTH-001",
            decision_id=valid.identity,
            portfolio_snapshot_id=snapshot.identity,
            target_axis_id="axis-microstructure",
            target_axis_identity=target_axis["axis_identity"],
            baseline_executable_id=source_baseline.identity,
            source_contract_id=contract.source_contract_id,
            source_state_record_id=source_head.record_id,
            reason_code=(
                PortfolioDecisionWithdrawalReason.SOURCE_AUTHORITY_INVALIDATED
            ),
            reason="source authority no longer supports the accepted execution path",
        )
        audit = self.writer.evidence.finalize(
            canonical_bytes(withdrawal_manifest.to_identity_payload())
        )
        forged_basis_manifest = PortfolioDecisionWithdrawalManifest(
            report_artifact_hash=report.sha256,
            report_finding_id="SOURCE-AUTH-001",
            decision_id=valid.identity,
            portfolio_snapshot_id=snapshot.identity,
            target_axis_id="axis-microstructure",
            target_axis_identity=target_axis["axis_identity"],
            baseline_executable_id="executable:" + "f" * 64,
            source_contract_id=contract.source_contract_id,
            source_state_record_id=source_head.record_id,
            reason_code=(
                PortfolioDecisionWithdrawalReason.SOURCE_AUTHORITY_INVALIDATED
            ),
            reason="source authority no longer supports the accepted execution path",
        )
        forged_basis = self.writer.evidence.finalize(
            canonical_bytes(forged_basis_manifest.to_identity_payload())
        )
        with self.assertRaisesRegex(TransitionError, "exact basis"):
            self.writer.withdraw_pending_portfolio_decision(
                manifest_artifact_hash=forged_basis.sha256,
                operation_id="reject-forged-withdrawal-basis",
            )
        scattered_withdrawal_report = self.writer.evidence.finalize(
            (
                "# Invalid Decision Withdrawal Audit\n\n"
                "- SOURCE-AUTH-001:\n"
                "  unrelated finding body;\n\n"
                f"{contract.source_contract_id}\n"
                f"audited head {source_head.record_id}\n"
            ).encode("ascii")
        )
        scattered_withdrawal_manifest = PortfolioDecisionWithdrawalManifest(
            report_artifact_hash=scattered_withdrawal_report.sha256,
            report_finding_id="SOURCE-AUTH-001",
            decision_id=valid.identity,
            portfolio_snapshot_id=snapshot.identity,
            target_axis_id="axis-microstructure",
            target_axis_identity=target_axis["axis_identity"],
            baseline_executable_id=source_baseline.identity,
            source_contract_id=contract.source_contract_id,
            source_state_record_id=source_head.record_id,
            reason_code=(
                PortfolioDecisionWithdrawalReason.SOURCE_AUTHORITY_INVALIDATED
            ),
            reason="source authority no longer supports the accepted execution path",
        )
        scattered_withdrawal = self.writer.evidence.finalize(
            canonical_bytes(scattered_withdrawal_manifest.to_identity_payload())
        )
        with self.assertRaisesRegex(TransitionError, "canonical manifest"):
            self.writer.withdraw_pending_portfolio_decision(
                manifest_artifact_hash=scattered_withdrawal.sha256,
                operation_id="reject-scattered-withdrawal-report-facts",
            )
        withdrawn = self.writer.withdraw_pending_portfolio_decision(
            manifest_artifact_hash=audit.sha256,
            operation_id="withdraw-invalidated-portfolio-target",
        )
        self.assertEqual(withdrawn.result["decision_id"], valid.identity)
        self.assertEqual(
            self.writer.read_control()["next_action"],  # type: ignore[index]
            {
                "constraint_source_id": "portfolio-fixture:source-audit",
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": snapshot.identity,
                "required_target_axis_ids": ["axis-microstructure"],
            },
        )
        with LocalIndex(self.writer.index_path) as index:
            withdrawal = index.get(
                "portfolio-decision-withdrawal",
                withdrawn.result["withdrawal_record_id"],
            )
            withdrawal_head = index.event_head(
                f"portfolio-decision-status:{valid.identity}"
            )
            accepted = index.get("portfolio-decision", valid.identity)
            active = StateWriter._active_portfolio_decision(index, valid.identity)
            assert accepted is not None
            legacy_anchor = StateWriter._axis_architecture_anchor(
                index,
                {"axis_identity": accepted.payload["target_axis_identity"]},
            )
        assert withdrawal is not None
        self.assertEqual(withdrawal.status, "withdrawn_pre_execution")
        assert withdrawal_head is not None
        self.assertEqual(withdrawal_head.record_id, withdrawal.record_id)
        self.assertEqual(withdrawal_head.sequence, 1)
        self.assertIsNone(active)
        self.assertIsNone(legacy_anchor)
        observed_defect = (
            "current broker snapshot cannot prove first availability or vintage"
        )
        reused_artifact_invalidation = SourceAuthorityInvalidation(
            source_contract_id=contract.source_contract_id,
            source_state_record_id=source_head.record_id,
            audit_artifact_hash=audit.sha256,
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect=observed_defect,
            observed_at_utc=FIXED_NOW,
        )
        with self.assertRaisesRegex(TransitionError, "canonical audit manifest"):
            self.writer.suspend_source_authority_from_audit(
                invalidation=reused_artifact_invalidation,
                operation_id="reject-arbitrary-source-audit-artifact",
            )
        audit_report = report
        scattered_report = self.writer.evidence.finalize(
            (
                "# Invalid Source Audit\n\n"
                "- SOURCE-AUTH-001:\n"
                "  unrelated finding body;\n\n"
                f"{contract.source_contract_id}\n"
                f"audited head {source_head.record_id}\n"
            ).encode("ascii")
        )
        scattered_manifest = SourceAuthorityAuditManifest(
            report_artifact_hash=scattered_report.sha256,
            report_finding_id="SOURCE-AUTH-001",
            source_contract_id=contract.source_contract_id,
            source_state_record_id=source_head.record_id,
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect=observed_defect,
            observed_at_utc=FIXED_NOW,
        )
        scattered_manifest_artifact = self.writer.evidence.finalize(
            canonical_bytes(scattered_manifest.to_identity_payload())
        )
        with self.assertRaisesRegex(TransitionError, "canonical audit manifest"):
            self.writer.suspend_source_authority_from_audit(
                invalidation=SourceAuthorityInvalidation(
                    source_contract_id=contract.source_contract_id,
                    source_state_record_id=source_head.record_id,
                    audit_artifact_hash=scattered_manifest_artifact.sha256,
                    surface=SourceAuthoritySurface.AVAILABILITY,
                    reason_code=(
                        SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN
                    ),
                    observed_defect=observed_defect,
                    observed_at_utc=FIXED_NOW,
                ),
                operation_id="reject-scattered-source-audit-facts",
            )
        mismatched_manifest = SourceAuthorityAuditManifest(
            report_artifact_hash=audit_report.sha256,
            report_finding_id="SOURCE-AUTH-001",
            source_contract_id=contract.source_contract_id,
            source_state_record_id=source_head.record_id,
            surface=SourceAuthoritySurface.CLOCK,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect=observed_defect,
            observed_at_utc=FIXED_NOW,
        )
        mismatched_manifest_artifact = self.writer.evidence.finalize(
            canonical_bytes(mismatched_manifest.to_identity_payload())
        )
        mismatched_manifest_invalidation = SourceAuthorityInvalidation(
            source_contract_id=contract.source_contract_id,
            source_state_record_id=source_head.record_id,
            audit_artifact_hash=mismatched_manifest_artifact.sha256,
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect=observed_defect,
            observed_at_utc=FIXED_NOW,
        )
        with self.assertRaisesRegex(TransitionError, "canonical audit manifest"):
            self.writer.suspend_source_authority_from_audit(
                invalidation=mismatched_manifest_invalidation,
                operation_id="reject-mismatched-source-audit-manifest",
            )
        missing_report_manifest = SourceAuthorityAuditManifest(
            report_artifact_hash="f" * 64,
            report_finding_id="SOURCE-AUTH-001",
            source_contract_id=contract.source_contract_id,
            source_state_record_id=source_head.record_id,
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect=observed_defect,
            observed_at_utc=FIXED_NOW,
        )
        missing_report_manifest_artifact = self.writer.evidence.finalize(
            canonical_bytes(missing_report_manifest.to_identity_payload())
        )
        missing_report_invalidation = SourceAuthorityInvalidation(
            source_contract_id=contract.source_contract_id,
            source_state_record_id=source_head.record_id,
            audit_artifact_hash=missing_report_manifest_artifact.sha256,
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect=observed_defect,
            observed_at_utc=FIXED_NOW,
        )
        with self.assertRaisesRegex(TransitionError, "canonical audit manifest"):
            self.writer.suspend_source_authority_from_audit(
                invalidation=missing_report_invalidation,
                operation_id="reject-missing-source-audit-report",
            )
        audit_manifest = SourceAuthorityAuditManifest(
            report_artifact_hash=audit_report.sha256,
            report_finding_id="SOURCE-AUTH-001",
            source_contract_id=contract.source_contract_id,
            source_state_record_id=source_head.record_id,
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect=observed_defect,
            observed_at_utc=FIXED_NOW,
        )
        audit_manifest_artifact = self.writer.evidence.finalize(
            canonical_bytes(audit_manifest.to_identity_payload())
        )
        invalidation = SourceAuthorityInvalidation(
            source_contract_id=contract.source_contract_id,
            source_state_record_id=source_head.record_id,
            audit_artifact_hash=audit_manifest_artifact.sha256,
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect=observed_defect,
            observed_at_utc=FIXED_NOW,
        )
        drift_artifact = self.writer.evidence.finalize(
            b"ordinary source suspension before audit latch"
        )
        drift_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.DRIFT,
            producer_completion_id="engineering-fixture",
            observed_at_utc=FIXED_NOW,
            artifact_hashes=(drift_artifact.sha256,),
            facts={
                "changed_surface": "availability",
                "observed_change": "ordinary pre-audit source drift",
                "dependent_action": "fail_closed",
            },
        )
        ordinary_suspended = eligible.suspend(
            receipt_id=drift_receipt.identity,
            reason="ordinary pre-audit source drift",
        )
        ordinary_result = self.writer.record_source_eligibility(
            eligibility=ordinary_suspended,
            receipt=drift_receipt,
            operation_id="ordinary-source-suspension-before-audit-latch",
        )
        before_action = self.writer.read_control()["next_action"]  # type: ignore[index]
        with self.assertRaises(InjectedCrash):
            self.writer.suspend_source_authority_from_audit(
                invalidation=invalidation,
                operation_id="suspend-invalid-source-authority",
                crash_after="after_journal",
            )
        recovery = self.writer.recover()
        self.assertGreater(recovery["journal_sequence"], 0)
        suspended = self.writer.suspend_source_authority_from_audit(
            invalidation=invalidation,
            operation_id="suspend-invalid-source-authority",
        )
        self.assertTrue(suspended.reused)
        self.assertEqual(suspended.result["state"], "suspended")
        self.assertEqual(suspended.result["trial_delta"], 0)
        self.assertEqual(
            self.writer.read_control()["next_action"],  # type: ignore[index]
            before_action,
        )
        with LocalIndex(self.writer.index_path) as index:
            new_head = index.event_head(f"source:{contract.source_contract_id}")
            correction = index.get(
                "source-authority-invalidation", invalidation.identity
            )
            source_state = (
                None
                if new_head is None
                else index.get(new_head.record_kind, new_head.record_id)
            )
        assert correction is not None and source_state is not None
        self.assertEqual(correction.status, "confirmed_and_suspended")
        self.assertEqual(correction.event_sequence, 1)
        self.assertEqual(new_head.sequence, 5)
        self.assertEqual(source_state.status, "suspended")
        self.assertEqual(
            correction.payload["audit_manifest"],
            audit_manifest.to_identity_payload(),
        )
        self.assertEqual(
            correction.payload["preserved_receipt_id"], runtime_receipt.identity
        )
        self.assertEqual(
            correction.payload["eligible_source_state_record_id"],
            source_head.record_id,
        )
        self.assertEqual(
            correction.payload["prior_active_source_state_record_id"],
            canonical_digest(
                domain="source-state",
                payload={
                    "source_id": contract.source_contract_id,
                    "state": "suspended",
                    "ordinal": ordinary_result.result["ordinal"],
                    "evidence_receipt_id": drift_receipt.identity,
                },
            ),
        )
        self.assertEqual(
            source_state.payload["transition_evidence"], "authority_invalidation"
        )
        self.assertEqual(
            source_state.payload["evidence_receipt_id"], runtime_receipt.identity
        )
        self.assertEqual(
            source_state.payload["receipt"],
            runtime_receipt.to_identity_payload(),
        )
        self.assertEqual(
            source_state.payload["source_authority_latch"]["invalidation_id"],
            invalidation.identity,
        )
        with LocalIndex(self.writer.index_path) as index:
            with self.assertRaisesRegex(PermitError, "permanently audit-invalidated"):
                self.writer._require_source_authority_for_actions(
                    index,
                    contract.source_contract_id,
                    actions=("performance_batch",),
                    error_type=PermitError,
                )
        recert_artifact = self.writer.evidence.finalize(
            b"audit-invalidated source recertification fixture"
        )
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
        with self.assertRaisesRegex(TransitionError, "new SourceContract"):
            self.writer.record_source_eligibility(
                eligibility=restored,
                receipt=recert_receipt,
                operation_id="reject-audit-invalidated-source-recertification",
            )
        replacement_contract = SourceContract(
            display_name="replacement synthetic external source",
            canonical_instrument=contract.canonical_instrument,
            runtime_identifier="SYN.IDX.V2",
            source_type=contract.source_type,
            instrument_semantics=contract.instrument(),
            mapping_semantics={
                "runtime_symbol": "SYN.IDX.V2",
                "mapping_rule": "exact_local_symbol",
            },
            schema_semantics=contract.schema(),
            field_semantics=contract.fields(),
            clock_semantics=contract.clock(),
            availability_semantics=contract.availability(),
        )
        self.assertNotEqual(
            replacement_contract.source_contract_id,
            contract.source_contract_id,
        )
        replacement_context = SourceEligibility.register(replacement_contract)
        replacement_registration = self.writer.record_source_eligibility(
            eligibility=replacement_context,
            receipt=None,
            operation_id="register-replacement-source-contract",
        )
        self.assertEqual(replacement_registration.result["state"], "context_only")
        with self.assertRaisesRegex(TransitionError, "permanently audit-invalidated"):
            self.writer.suspend_source_authority_from_audit(
                invalidation=invalidation,
                operation_id="reject-repeated-source-suspension",
            )
        self.writer.validation_registry = EvidenceValidatorRegistry(
            (
                ScientificAdjudicationValidatorV2(),
                ScientificFixtureValidator(),
            )
        )
        control = self.writer.read_control()
        assert control is not None
        activation = ResearchProtocolActivation(
            protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
            validator_id=ScientificAdjudicationValidatorV2.validator_id,
            authority_manifest_digest=control["authority"]["manifest_digest"],
            audit_artifact_hash=audit.sha256,
        )
        activated = self.writer.activate_research_protocol(
            activation=activation,
            operation_id="activate-scientific-adjudication-v2",
        )
        self.assertEqual(activated.result["trial_delta"], 0)
        self.assertEqual(activated.result["ordinal"], 1)
        with self.assertRaisesRegex(TransitionError, "already bound"):
            self.writer.activate_research_protocol(
                activation=activation,
                operation_id="reject-duplicate-scientific-protocol-binding",
            )
        authority_fixture = self.root / "protocol-authority"
        authority_paths = (
            control["authority"]["operating_direction"],
            *control["authority"]["contracts"],
            *control["authority"]["foundation_inputs"],
        )
        for relative in authority_paths:
            destination = authority_fixture / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((REPO_ROOT / relative).read_bytes())
        self.writer.foundation_root = authority_fixture
        operations_path = self.writer.foundation_root / "contracts/operations.yaml"
        replacement = operations_path.read_bytes() + b"\n# protocol rebind fixture\n"
        self.writer.migrate_authority(
            replacements={"contracts/operations.yaml": replacement},
            reason="exercise authority-bound protocol reactivation",
            operation_id="migrate-authority-for-protocol-rebind",
            allow_active_stable_boundary=True,
        )
        rebound_control = self.writer.read_control()
        assert rebound_control is not None
        rebound = ResearchProtocolActivation(
            protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
            validator_id=ScientificAdjudicationValidatorV2.validator_id,
            authority_manifest_digest=rebound_control["authority"][
                "manifest_digest"
            ],
            audit_artifact_hash=audit.sha256,
        )
        reactivated = self.writer.activate_research_protocol(
            activation=rebound,
            operation_id="reactivate-scientific-adjudication-v2",
        )
        self.assertEqual(reactivated.result["ordinal"], 2)
        legacy_plan = self.writer.evidence.finalize(b"legacy scientific plan")
        legacy_spec = job_spec(
            self.writer,
            {"kind": "Executable", "id": "executable:" + "e" * 64},
        )
        legacy_spec["input_hashes"] = [
            *legacy_spec["input_hashes"],  # type: ignore[list-item]
            legacy_plan.sha256,
        ]
        legacy_spec["expected_outputs"] = [
            "evidence/legacy-measurement",
            "evidence/legacy-result",
        ]
        legacy_spec["output_classes"] = {
            "evidence/legacy-measurement": "durable_evidence",
            "evidence/legacy-result": "durable_evidence",
        }
        legacy_spec["scientific_binding"] = {
            "evidence_depth": "discovery",
            "evidence_modes": [
                "causal_contrast",
                "cost_and_execution",
                "sensitivity_or_stress",
            ],
            "planned_claims": ["claim-a"],
            "result_manifest_output": "evidence/legacy-result",
            "validation_plan_hash": legacy_plan.sha256,
            "validator_id": ScientificFixtureValidator.validator_id,
        }
        with self.assertRaisesRegex(TransitionError, "active v2 protocol"):
            self.writer.declare_job(
                spec=legacy_spec,
                operation_id="reject-legacy-scientific-validator-after-activation",
            )

    def test_v2_authority_fails_closed_without_protocol_activation(self) -> None:
        self.open_mission_and_initiative()
        snapshot = PortfolioSnapshot(
            mission_id="MIS-FIXTURE",
            axes=(
                PortfolioAxis(
                    axis_id="v2-fail-closed-axis-a",
                    causal_question="Does mechanism A survive controlled comparison?",
                    mechanism_family="v2-family-a",
                ),
                PortfolioAxis(
                    axis_id="v2-fail-closed-axis-b",
                    causal_question="Does mechanism B survive controlled comparison?",
                    mechanism_family="v2-family-b",
                ),
            ),
            opportunity_cost_basis="preserve two independent mechanisms",
        )
        self.writer.record_portfolio_snapshot(
            snapshot=snapshot,
            operation_id="record-v2-fail-closed-portfolio",
        )
        control = self.writer.read_control()
        assert control is not None
        authority_fixture = self.root / "v2-fail-closed-authority"
        authority_paths = (
            control["authority"]["operating_direction"],
            *control["authority"]["contracts"],
            *control["authority"]["foundation_inputs"],
        )
        for relative in authority_paths:
            destination = authority_fixture / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((REPO_ROOT / relative).read_bytes())
        self.writer.foundation_root = authority_fixture
        science_path = authority_fixture / "contracts/science.yaml"
        replacement = (
            science_path.read_bytes()
            + b"\nscientific_adjudication_v2:\n  required: true\n"
        )
        self.writer.migrate_authority(
            replacements={"contracts/science.yaml": replacement},
            reason="exercise fail-closed scientific protocol authority",
            operation_id="migrate-v2-fail-closed-authority",
            allow_active_stable_boundary=True,
        )
        self.writer.validation_registry = EvidenceValidatorRegistry(
            (
                ScientificAdjudicationValidatorV2(),
                ScientificFixtureValidator(),
            )
        )
        plan = self.writer.evidence.finalize(b"legacy validator plan")
        spec = job_spec(
            self.writer,
            {"kind": "Executable", "id": "executable:" + "d" * 64},
        )
        spec["input_hashes"] = [
            *spec["input_hashes"],  # type: ignore[list-item]
            plan.sha256,
        ]
        spec["expected_outputs"] = [
            "evidence/v2-fail-closed-measurement",
            "evidence/v2-fail-closed-result",
        ]
        spec["output_classes"] = {
            "evidence/v2-fail-closed-measurement": "durable_evidence",
            "evidence/v2-fail-closed-result": "durable_evidence",
        }
        spec["scientific_binding"] = {
            "evidence_depth": "discovery",
            "evidence_modes": [
                "causal_contrast",
                "cost_and_execution",
                "sensitivity_or_stress",
            ],
            "planned_claims": ["claim-a"],
            "result_manifest_output": "evidence/v2-fail-closed-result",
            "validation_plan_hash": plan.sha256,
            "validator_id": ScientificFixtureValidator.validator_id,
        }
        with self.assertRaisesRegex(
            TransitionError,
            "authority requires an active v2 scientific protocol",
        ):
            self.writer.declare_job(
                spec=spec,
                operation_id="reject-v2-authority-without-activation",
            )

    def test_context_only_source_can_be_permanently_rejected_by_audit(self) -> None:
        self.open_mission_and_initiative()
        contract = source_contract()
        context = SourceEligibility.register(contract)
        registered = self.writer.record_source_eligibility(
            eligibility=context,
            receipt=None,
            operation_id="register-context-only-source-for-audit",
        )
        source_state_record_id = canonical_digest(
            domain="source-state",
            payload={
                "source_id": contract.source_contract_id,
                "state": "context_only",
                "ordinal": registered.result["ordinal"],
                "evidence_receipt_id": None,
            },
        )
        snapshot = PortfolioSnapshot(
            mission_id="MIS-FIXTURE",
            axes=(
                PortfolioAxis(
                    axis_id="context-audit-axis-a",
                    causal_question="Can the audited source support a causal claim?",
                    mechanism_family="source-authority-audit",
                ),
                PortfolioAxis(
                    axis_id="context-audit-axis-b",
                    causal_question="What independent axis remains available?",
                    mechanism_family="independent-control",
                ),
            ),
            opportunity_cost_basis="reject invalid authority before evidence production",
        )
        self.writer.record_portfolio_snapshot(
            snapshot=snapshot,
            operation_id="context-only-audit-portfolio",
        )
        report = self.writer.evidence.finalize(
            source_audit_report_bytes(
                finding_id="SOURCE-CONTEXT-001",
                source_contract_id=contract.source_contract_id,
                source_state_record_id=source_state_record_id,
            )
        )
        manifest = SourceAuthorityAuditManifest(
            report_artifact_hash=report.sha256,
            report_finding_id="SOURCE-CONTEXT-001",
            source_contract_id=contract.source_contract_id,
            source_state_record_id=source_state_record_id,
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect="context contract asserts unavailable point-in-time facts",
            observed_at_utc=FIXED_NOW,
        )
        manifest_artifact = self.writer.evidence.finalize(
            canonical_bytes(manifest.to_identity_payload())
        )
        invalidation = SourceAuthorityInvalidation(
            source_contract_id=contract.source_contract_id,
            source_state_record_id=source_state_record_id,
            audit_artifact_hash=manifest_artifact.sha256,
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect="context contract asserts unavailable point-in-time facts",
            observed_at_utc=FIXED_NOW,
        )
        suspended = self.writer.suspend_source_authority_from_audit(
            invalidation=invalidation,
            operation_id="reject-context-only-source-from-audit",
        )
        self.assertEqual(suspended.result["invalidated_state"], "context_only")
        self.assertEqual(suspended.result["state"], "suspended")
        with LocalIndex(self.writer.index_path) as index:
            correction = index.get(
                "source-authority-invalidation", invalidation.identity
            )
            head = index.event_head(f"source:{contract.source_contract_id}")
            assert head is not None
            state = index.get(head.record_kind, head.record_id)
            with self.assertRaisesRegex(
                PermitError, "permanently audit-invalidated"
            ):
                self.writer._require_source_authority_for_actions(
                    index,
                    contract.source_contract_id,
                    actions=("performance_batch",),
                    error_type=PermitError,
                )
        assert correction is not None and state is not None
        self.assertIsNone(correction.payload["preserved_receipt_id"])
        self.assertEqual(correction.payload["invalidated_state"], "context_only")
        self.assertIsNone(state.payload["receipt"])
        self.assertEqual(state.status, "suspended")
        with self.assertRaisesRegex(TransitionError, "new SourceContract"):
            self.writer.record_source_eligibility(
                eligibility=context,
                receipt=None,
                operation_id="reject-context-only-source-reregistration",
            )

    def test_historical_adjudication_is_additive_and_replay_scoped(self) -> None:
        self.open_mission_and_initiative()
        study_id = "STU-HISTORICAL-ADJUDICATION"
        source_id = "source:" + "e" * 64
        trial_executable = {
            "schema": "historical_trial_fixture.v1",
            "source_contracts": [source_id],
        }
        executable_id = "executable:" + canonical_digest(
            domain="executable", payload=trial_executable
        )
        job_id = "job:" + "b" * 64
        completion_id = canonical_digest(
            domain="fixture-completion", payload={"study_id": study_id}
        )
        close_id = canonical_digest(
            domain="fixture-study-close", payload={"study_id": study_id}
        )
        memory_id = "negative-memory:" + canonical_digest(
            domain="fixture-negative-memory", payload={"study_id": study_id}
        )
        eligible_state_id = canonical_digest(
            domain="fixture-source-state",
            payload={"source_id": source_id, "state": "runtime_eligible"},
        )
        audit = self.writer.evidence.finalize(
            source_audit_report_bytes(
                finding_id="SOURCE-AUTH-HISTORICAL",
                source_contract_id=source_id,
                source_state_record_id=eligible_state_id,
            )
        )
        observed_defect = "legacy source had no point-in-time authority"
        source_manifest = SourceAuthorityAuditManifest(
            report_artifact_hash=audit.sha256,
            report_finding_id="SOURCE-AUTH-HISTORICAL",
            source_contract_id=source_id,
            source_state_record_id=eligible_state_id,
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect=observed_defect,
            observed_at_utc=FIXED_NOW,
        )
        source_manifest_artifact = self.writer.evidence.finalize(
            canonical_bytes(source_manifest.to_identity_payload())
        )
        source_invalidation = SourceAuthorityInvalidation(
            source_contract_id=source_id,
            source_state_record_id=eligible_state_id,
            audit_artifact_hash=source_manifest_artifact.sha256,
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect=observed_defect,
            observed_at_utc=FIXED_NOW,
        )
        source_override = HistoricalValidityOverride(
            reason=HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED,
            subject_id=source_id,
            evidence_record_id=source_invalidation.identity,
        )
        source_latch = SourceAuthorityLatch.bind(
            invalidation=source_invalidation,
            manifest=source_manifest,
        )
        suspended_state_id = canonical_digest(
            domain="fixture-source-state",
            payload={"source_id": source_id, "state": "suspended"},
        )
        preserved_receipt_id = "source-receipt:" + "f" * 64
        preserved_receipt = {"fixture": "historical-source-receipt"}
        criteria = discovery_criteria(
            control_delta_metric="control_delta_net_profit_micropoints",
            control_pvalue_metric="control_pvalue_upper_ppm",
            include_opposite_sign=False,
        )
        evidence_modes = [
            "causal_contrast",
            "cost_and_execution",
            "extreme_or_boundary",
            "regime_stability",
            "sensitivity_or_stress",
            "temporal_stability",
        ]
        plan = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "candidate_eligible_on_pass": False,
                    "criteria": list(criteria),
                    "evidence_depth": "discovery",
                    "evidence_modes": evidence_modes,
                    "executable_id": executable_id,
                    "mission_id": "MIS-FIXTURE",
                    "planned_claims": list(PLANNED_CLAIMS),
                    "schema": "scientific_validation_plan.v1",
                }
            )
        )
        measurement = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "claims": list(PLANNED_CLAIMS),
                    "evidence_depth": "discovery",
                    "evidence_modes": evidence_modes,
                    "executable_id": executable_id,
                    "job_hash": job_id.removeprefix("job:"),
                    "job_id": job_id,
                    "metrics": {
                        "activity_and_concentration": {
                            "entries_per_day_milli": 5_000,
                            "top5_profit_day_share_ppm": 150_000,
                            "trade_count": 1_000,
                        },
                        "after_cost_fixed_lot_economics": {
                            "median_fold_profit_factor_milli": 1_200,
                            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": 800_000,
                            "net_profit_micropoints": 9_000_000_000,
                            "stress_net_profit_micropoints": 6_000_000_000,
                        },
                        "causal_feature_and_execution_validity": {
                            "append_invariance_mismatch_count": 0,
                            "causality_violation_count": 0,
                            "nonfinite_metric_count": 0,
                            "prefix_invariance_mismatch_count": 0,
                            "unknown_cost_unresolved_signal_count": 0,
                        },
                        "registered_control_contrast": {
                            "control_delta_net_profit_micropoints": 2_000_000_000,
                            "control_pvalue_upper_ppm": 1_000_000,
                        },
                        "selection_aware_signal_evidence": {
                            "selection_aware_pvalue_ppm": 1_000_000,
                        },
                        "temporal_and_regime_stability": {
                            "evaluable_folds": 9,
                            "supported_positive_regime_count": 2,
                            "winning_fold_count": 6,
                        },
                    },
                    "mission_id": "MIS-FIXTURE",
                    "schema": "scientific_measurement.v1",
                }
            )
        )

        def seed(current, _index):
            assert current is not None
            body = self.writer._body(current)
            body["next_action"] = {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": "portfolio:" + "c" * 64,
            }
            records = [
                IndexRecord(
                    kind="study-open",
                    record_id=study_id,
                    subject=f"Study:{study_id}",
                    status="open",
                    fingerprint="d" * 64,
                    payload={"mission_id": "MIS-FIXTURE"},
                ),
                IndexRecord(
                    kind="study-close",
                    record_id=close_id,
                    subject=f"Study:{study_id}",
                    status="not_supported",
                    fingerprint="d" * 64,
                    payload={"outcome": "not_supported"},
                ),
                IndexRecord(
                    kind="job-declared",
                    record_id=job_id,
                    subject=f"Job:{job_id}",
                    status="declared",
                    fingerprint=job_id.removeprefix("job:"),
                    payload={
                        "mission_id": "MIS-FIXTURE",
                        "study_id": study_id,
                        "spec": {
                            "evidence_subject": {
                                "kind": "Executable",
                                "id": executable_id,
                            },
                            "input_hashes": [plan.sha256],
                        },
                    },
                ),
                IndexRecord(
                    kind="job-completed",
                    record_id=completion_id,
                    subject=f"Job:{job_id}",
                    status="failed",
                    fingerprint=job_id.removeprefix("job:"),
                    payload={
                        "job_id": job_id,
                        "outputs": {
                            "validation-plan.json": plan.sha256,
                            "measurement.json": measurement.sha256,
                        },
                        "scientific": {
                            "executable_id": executable_id,
                            "measurement_artifact_hashes": [measurement.sha256],
                            "validation_plan_hash": plan.sha256,
                            "verdict": "failed",
                        },
                    },
                ),
                IndexRecord(
                    kind="negative-memory",
                    record_id=memory_id,
                    subject=f"Executable:{executable_id}",
                    status="durable",
                    fingerprint=memory_id.removeprefix("negative-memory:"),
                    payload={"study_id": study_id},
                ),
                IndexRecord(
                    kind="trial",
                    record_id=executable_id,
                    subject="Batch:BAT-HISTORICAL",
                    status="evaluated",
                    fingerprint=executable_id.removeprefix("executable:"),
                    payload={"executable": trial_executable},
                ),
                IndexRecord(
                    kind="source-state",
                    record_id=eligible_state_id,
                    subject=f"Source:{source_id}",
                    status="runtime_eligible",
                    fingerprint=source_id,
                    payload={
                        "evidence_receipt_id": preserved_receipt_id,
                        "receipt": preserved_receipt,
                    },
                    event_stream=f"source:{source_id}",
                    event_sequence=1,
                ),
                IndexRecord(
                    kind="source-authority-invalidation",
                    record_id=source_invalidation.identity,
                    subject=f"Source:{source_id}",
                    status="confirmed_and_suspended",
                    fingerprint=source_invalidation.identity.removeprefix(
                        "source-authority-invalidation:"
                    ),
                    payload={
                        "audit_manifest": source_manifest.to_identity_payload(),
                        "eligible_source_state_record_id": eligible_state_id,
                        "invalidated_state": "runtime_eligible",
                        "invalidation": source_invalidation.to_identity_payload(),
                        "latch": source_latch.to_identity_payload(),
                        "preserved_receipt_id": preserved_receipt_id,
                        "prior_active_source_state_record_id": eligible_state_id,
                        "replacement_state_record_id": suspended_state_id,
                        "scientific_trial_delta": 0,
                    },
                    event_stream=f"source-authority:{source_id}",
                    event_sequence=1,
                ),
                IndexRecord(
                    kind="source-state",
                    record_id=suspended_state_id,
                    subject=f"Source:{source_id}",
                    status="suspended",
                    fingerprint=source_id,
                    payload={
                        "evidence_receipt_id": preserved_receipt_id,
                        "eligible_source_state_record_id": eligible_state_id,
                        "prior_active_source_state_record_id": eligible_state_id,
                        "receipt": preserved_receipt,
                        "source_authority_latch": source_latch.to_identity_payload(),
                        "transition_evidence": "authority_invalidation",
                    },
                    event_stream=f"source:{source_id}",
                    event_sequence=2,
                ),
            ]
            return body, records, {"seeded": True}

        self.writer._commit(
            event_kind="historical_adjudication_fixture_seeded",
            operation_id="historical-adjudication-seed",
            subject=f"Study:{study_id}",
            payload={"study_id": study_id},
            prepare=seed,
        )
        before = self.writer.read_control()
        recorded = self.writer.record_historical_scientific_adjudications(
            requests=(
                HistoricalAdjudicationRequest(
                    completion_record_id=completion_id,
                    disposition=HistoricalDisposition.REPLAY_REQUIRED,
                    replay_priority=ReplayPriority.P0,
                    reason_codes=(
                        "global_multiplicity_not_a_concurrent_family",
                        "raw_uncertainty_replay_required",
                    ),
                    validity_overrides=(source_override,),
                ),
            ),
            audit_artifact_hash=audit.sha256,
            operation_id="record-historical-adjudication",
        )
        after = self.writer.read_control()
        assert before is not None and after is not None
        self.assertEqual(
            after["next_action"]["kind"], before["next_action"]["kind"]
        )
        self.assertEqual(
            after["next_action"]["portfolio_snapshot_id"],
            before["next_action"]["portfolio_snapshot_id"],
        )
        self.assertEqual(after["next_action"]["required_replay_priority"], "p0")
        self.assertEqual(
            after["next_action"]["pending_replay_obligation_ids"],
            recorded.result["replay_obligation_ids"],
        )
        self.assertEqual(after["scientific"], before["scientific"])
        self.assertEqual(recorded.result["trial_delta"], 0)
        self.assertEqual(recorded.result["holdout_delta"], 0)
        self.assertEqual(recorded.result["candidate_delta"], 0)
        with LocalIndex(self.writer.index_path) as index:
            overlay = index.get(
                "historical-scientific-adjudication",
                recorded.result["adjudication_record_ids"][0],
            )
            original = index.get("job-completed", completion_id)
            memory = index.get("negative-memory", memory_id)
        assert overlay is not None and original is not None and memory is not None
        self.assertEqual(overlay.status, "replay_required")
        self.assertEqual(overlay.payload["adjudication"]["state"], "partial_positive")
        self.assertEqual(overlay.payload["adjudication"]["legacy_verdict"], "failed")
        self.assertEqual(overlay.payload["negative_memory_ids"], [memory_id])
        self.assertEqual(original.status, "failed")
        self.assertEqual(memory.status, "durable")

        source_qualified = self.writer.record_historical_scientific_adjudications(
            requests=(
                HistoricalAdjudicationRequest(
                    completion_record_id=completion_id,
                    disposition=(
                        HistoricalDisposition.NOT_EVALUABLE_QUALIFICATION
                    ),
                    replay_priority=ReplayPriority.NONE,
                    reason_codes=("source_authority_invalidated",),
                    validity_overrides=(source_override,),
                ),
            ),
            audit_artifact_hash=audit.sha256,
            operation_id="record-source-invalidated-historical-adjudication",
        )
        with LocalIndex(self.writer.index_path) as index:
            source_overlay = index.get(
                "historical-scientific-adjudication",
                source_qualified.result["adjudication_record_ids"][0],
            )
        assert source_overlay is not None
        self.assertEqual(source_overlay.status, "not_evaluable_qualification")
        self.assertEqual(source_overlay.payload["effective_state"], "not_evaluable")
        self.assertEqual(
            source_overlay.payload["profile_authority"],
            "writer_derived_fixed_legacy_v1",
        )
        self.assertEqual(
            source_overlay.payload["validity_override_authority"],
            "writer_derived_durable_source_latches",
        )
        self.assertEqual(
            source_overlay.payload["validity_overrides"],
            [
                {
                    "evidence_record_id": source_invalidation.identity,
                    "reason": "source_authority_invalidated",
                    "subject_id": source_id,
                }
            ],
        )

        with self.assertRaisesRegex(
            TransitionError, "Writer-derived durable source-authority latches"
        ):
            self.writer.record_historical_scientific_adjudications(
                requests=(
                    HistoricalAdjudicationRequest(
                        completion_record_id=completion_id,
                        disposition=(
                            HistoricalDisposition.NOT_EVALUABLE_QUALIFICATION
                        ),
                        replay_priority=ReplayPriority.NONE,
                        reason_codes=("forged_source_invalidation",),
                        validity_overrides=(
                            HistoricalValidityOverride(
                                reason=(
                                    HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED
                                ),
                                subject_id=source_id,
                                evidence_record_id=(
                                    "source-authority-invalidation:" + "f" * 64
                                ),
                            ),
                        ),
                    ),
                ),
                audit_artifact_hash=audit.sha256,
                operation_id="reject-forged-source-validity-override",
            )

        with self.assertRaisesRegex(
            TransitionError, "Writer-derived durable source-authority latches"
        ):
            self.writer.record_historical_scientific_adjudications(
                requests=(
                    HistoricalAdjudicationRequest(
                        completion_record_id=completion_id,
                        disposition=(
                            HistoricalDisposition.NOT_EVALUABLE_QUALIFICATION
                        ),
                        replay_priority=ReplayPriority.NONE,
                        reason_codes=("unbound_source_invalidation",),
                        validity_overrides=(
                            HistoricalValidityOverride(
                                reason=(
                                    HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED
                                ),
                                subject_id="source:" + "d" * 64,
                                evidence_record_id=source_invalidation.identity,
                            ),
                        ),
                    ),
                ),
                audit_artifact_hash=audit.sha256,
                operation_id="reject-unbound-source-validity-override",
            )

        with self.assertRaisesRegex(TransitionError, "idempotency key"):
            self.writer.record_historical_scientific_adjudications(
                requests=(
                    HistoricalAdjudicationRequest(
                        completion_record_id=completion_id,
                        disposition=HistoricalDisposition.REPLAY_REQUIRED,
                        replay_priority=ReplayPriority.P0,
                        reason_codes=(
                            "global_multiplicity_not_a_concurrent_family",
                            "raw_uncertainty_replay_required",
                        ),
                        validity_overrides=(source_override,),
                        profile=AdjudicationProfile(
                            multiplicity=(
                                bonferroni_concurrent_family(
                                    criterion_id="E01-familywise-selection",
                                    family_id="fixture-concurrent-family",
                                    family_size=2,
                                    raw_pvalue_ppm=10_000,
                                    alpha_ppm=50_000,
                                ),
                            ),
                        ),
                    ),
                ),
                audit_artifact_hash=audit.sha256,
                operation_id="record-historical-adjudication",
            )

        with self.assertRaisesRegex(
            TransitionError, "profile differs from the Writer-derived"
        ):
            self.writer.record_historical_scientific_adjudications(
                requests=(
                    HistoricalAdjudicationRequest(
                        completion_record_id=completion_id,
                        disposition=HistoricalDisposition.REPLAY_REQUIRED,
                        replay_priority=ReplayPriority.P0,
                        reason_codes=("caller_forged_multiplicity",),
                        validity_overrides=(source_override,),
                        profile=AdjudicationProfile(
                            multiplicity=(
                                bonferroni_concurrent_family(
                                    criterion_id="E01-familywise-selection",
                                    family_id="forged-concurrent-family",
                                    family_size=2,
                                    raw_pvalue_ppm=1,
                                    alpha_ppm=50_000,
                                ),
                            ),
                        ),
                    ),
                ),
                audit_artifact_hash=audit.sha256,
                operation_id="reject-caller-forged-historical-profile",
            )

        rich_job_id = "job:" + "a" * 64
        rich_completion_id = canonical_digest(
            domain="fixture-rich-completion", payload={"study_id": study_id}
        )

        def seed_rich_completion(current, _index):
            assert current is not None
            return self.writer._body(current), [
                IndexRecord(
                    kind="job-declared",
                    record_id=rich_job_id,
                    subject=f"Job:{rich_job_id}",
                    status="declared",
                    fingerprint=rich_job_id.removeprefix("job:"),
                    payload={
                        "mission_id": "MIS-FIXTURE",
                        "study_id": study_id,
                        "spec": {
                            "evidence_subject": {
                                "kind": "Executable",
                                "id": executable_id,
                            },
                            "input_hashes": [plan.sha256],
                        },
                    },
                ),
                IndexRecord(
                    kind="job-completed",
                    record_id=rich_completion_id,
                    subject=f"Job:{rich_job_id}",
                    status="success",
                    fingerprint=rich_job_id.removeprefix("job:"),
                    payload={
                        "job_id": rich_job_id,
                        "outputs": {
                            "validation-plan.json": plan.sha256,
                            "measurement.json": measurement.sha256,
                        },
                        "scientific": {
                            "adjudication": {
                                "schema": "scientific_adjudication.v2"
                            },
                            "executable_id": executable_id,
                            "measurement_artifact_hashes": [measurement.sha256],
                            "validation_plan_hash": plan.sha256,
                            "verdict": "failed",
                        },
                    },
                ),
            ], {"seeded": True}

        self.writer._commit(
            event_kind="rich_scientific_completion_fixture_seeded",
            operation_id="rich-scientific-completion-seed",
            subject=f"Study:{study_id}",
            payload={"completion_record_id": rich_completion_id},
            prepare=seed_rich_completion,
        )
        with self.assertRaisesRegex(
            TransitionError, "restricted to legacy completions"
        ):
            self.writer.record_historical_scientific_adjudications(
                requests=(
                    HistoricalAdjudicationRequest(
                        completion_record_id=rich_completion_id,
                        disposition=HistoricalDisposition.REPLAY_REQUIRED,
                        replay_priority=ReplayPriority.P0,
                        reason_codes=("cannot_rejudge_rich_v2",),
                        validity_overrides=(source_override,),
                    ),
                ),
                audit_artifact_hash=audit.sha256,
                operation_id="reject-rich-v2-historical-overlay",
            )

        with self.assertRaisesRegex(
            TransitionError, "Writer-derived durable source-authority latches"
        ):
            self.writer.record_historical_scientific_adjudications(
                requests=(
                    HistoricalAdjudicationRequest(
                        completion_record_id=completion_id,
                        disposition=(
                            HistoricalDisposition.NOT_EVALUABLE_QUALIFICATION
                        ),
                        replay_priority=ReplayPriority.NONE,
                        reason_codes=("caller_cannot_withdraw_source_invalidity",),
                    ),
                ),
                audit_artifact_hash=audit.sha256,
                operation_id="reject-historical-validity-withdrawal",
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
                study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
                foundation_root=REPO_ROOT,
            )
            writer.initialize_ready()
            writer.open_mission(
                mission_id="MIS-COMMITMENT",
                goal=mission_goal("Portfolio Batch commitment"),
                operation_id="commitment-mission",
            )
            intake = record_fixture_research_intake(
                writer,
                mission_id="MIS-COMMITMENT",
                operation_id="commitment-intake",
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
                research_intake_id=intake.identity,
                exhaustion_standard=exhaustion_standard(),
            )
            writer.record_portfolio_snapshot(
                snapshot=snapshot, operation_id="commitment-snapshot"
            )
            options = (
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
            )
            decision = PortfolioDecision(
                decision_id="DEC-COMMITMENT",
                chosen_option_id="choose-a",
                options=options,
                rationale="bind exactly one Batch",
                commitment_batches=1,
                baseline_executable=portfolio_axis_baseline(axis_a),
                quant_team_review=quant_team_review_for_current_action(
                    writer,
                    options=options,
                    chosen_option_id="choose-a",
                ),
            )
            writer.record_portfolio_decision(
                decision=decision, operation_id="commitment-decision"
            )
            question = study_question("mechanical commitment")
            proposal = {"mechanism": "commitment enforcement"}
            assert axis_a.architecture_chassis is not None
            controlled_chassis = ControlledStudyChassis(
                baseline_executable=decision.baseline_executable,
                changed_domains=axis_a.changed_domains,
                controlled_domains=axis_a.controlled_domains,
                architecture=axis_a.architecture_chassis,
            )
            study_hash = writer.study_input_hash(
                question=question,
                material_identity=OBSERVED_MATERIAL_ID,
                semantic_proposal=proposal,
                controlled_chassis=controlled_chassis,
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
                scope=(
                    "study",
                    f"decision:{decision.identity}",
                    f"axis:{axis_a.identity}",
                    f"baseline:{decision.baseline_executable.identity}",
                    f"chassis:{decision.architecture_chassis.identity}",
                    f"snapshot:{snapshot.identity}",
                ),
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
                controlled_chassis=controlled_chassis,
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
                outcome="not_evaluable", operation_id="commitment-first-close"
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
        started = self.writer.start_job(
            permit=start_permit,
            operation_id="start-job",
        )
        with self.assertRaises((PermitError, TransitionError)):
            self.writer.start_job(permit=start_permit, operation_id="replay-start")

        before = self.writer.read_control()
        reproduction = self.writer.evidence.finalize(b"fixture parser failure reproduction")
        first_repair_open = self.writer.open_repair(
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
        with self.assertRaisesRegex(TransitionError, "canonical evidence"):
            self.writer.close_repair(
                changed_cause_proof_hash=changed_cause.sha256,
                operation_id="reject-untyped-close-repair",
            )
        failed_basis_one = self.writer.evidence.finalize(
            b"first failed basis in first Repair episode"
        )
        failed_verification_one = self.writer.evidence.finalize(
            b"first failed verification in first Repair episode"
        )
        failed_attempt_one = self.writer.record_failed_repair_attempt(
            attempt_proof_hash=repair_attempt_proof(
                self.writer,
                outcome="failed",
                changed_dimension="cause",
                new_basis_hash=failed_basis_one.sha256,
                new_evidence_hashes=(failed_basis_one.sha256,),
                verification_evidence_hashes=(
                    failed_verification_one.sha256,
                ),
            ),
            operation_id="record-first-episode-failed-attempt-one",
        )
        failed_basis_two = self.writer.evidence.finalize(
            b"second failed basis in first Repair episode"
        )
        failed_verification_two = self.writer.evidence.finalize(
            b"second failed verification in first Repair episode"
        )
        failed_attempt_two = self.writer.record_failed_repair_attempt(
            attempt_proof_hash=repair_attempt_proof(
                self.writer,
                outcome="failed",
                changed_dimension="information",
                new_basis_hash=failed_basis_two.sha256,
                new_evidence_hashes=(failed_basis_two.sha256,),
                verification_evidence_hashes=(
                    failed_verification_two.sha256,
                ),
            ),
            operation_id="record-first-episode-failed-attempt-two",
        )
        repair_verification = self.writer.evidence.finalize(
            b"independent fixture parser Repair verification"
        )
        changed_cause_proof_hash = repair_attempt_proof(
            self.writer,
            outcome="repaired",
            changed_dimension="cause",
            new_basis_hash=changed_cause.sha256,
            new_evidence_hashes=(changed_cause.sha256,),
            verification_evidence_hashes=(repair_verification.sha256,),
        )
        first_repair_close = self.writer.close_repair(
            changed_cause_proof_hash=changed_cause_proof_hash,
            operation_id="close-repair",
        )
        retried_repair_close = self.writer.close_repair(
            changed_cause_proof_hash=changed_cause_proof_hash,
            operation_id="close-repair",
        )
        self.assertTrue(retried_repair_close.reused)
        self.assertEqual(
            first_repair_close.result,
            retried_repair_close.result,
        )
        after = self.writer.read_control()
        assert before is not None and after is not None
        for key in ("holdout_reveals", "active_executable", "required_future_holdout_id"):
            self.assertEqual(before["scientific"][key], after["scientific"][key])
        self.assertEqual(after["scientific"]["active_job"]["status"], "running")
        execution = RunningJobExecution.from_mapping(
            started.result["execution"]
        )
        with self.assertRaisesRegex(
            TransitionError,
            "re-enter its exact engine before completion",
        ):
            self.writer.complete_job(
                outcome="success",
                output_manifest={
                    "local/jobs/fixture/fixture.json": sha256(
                        b"not executed after Repair"
                    ).hexdigest()
                },
                operation_id="reject-completion-before-repaired-resume",
            )

        repeated_cause_permit = self.writer.issue_permit(
            kind=PermitKind.REPAIR,
            subject_kind=SubjectKind.JOB,
            subject_id=job_id,
            input_hash=job_hash,
            actions=("open_repair",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="issue-repeated-cause-repair-permit",
        )
        with self.assertRaisesRegex(
            TransitionError,
            "re-enter its engine before another Repair",
        ):
            self.writer.open_repair(
                permit=repeated_cause_permit,
                failure={
                    "failure_kind": "engineering",
                    "minimum_reproduction_evidence": [reproduction.sha256],
                    "root_cause": "fixture parser rejected declared input",
                    "interrupted_action": "fixture.callable",
                },
                operation_id="reject-repair-before-engine-reentry",
            )
        resumed_first = self.writer.verify_running_job_execution(
            execution,
            expected_callable_identity="fixture.callable",
        )
        self.assertIsNotNone(resumed_first["repair_resume_record_id"])
        repeated_cause_open = self.writer.open_repair(
            permit=repeated_cause_permit,
            failure={
                "failure_kind": "engineering",
                "minimum_reproduction_evidence": [reproduction.sha256],
                "root_cause": "fixture parser rejected declared input",
                "interrupted_action": "fixture.callable",
            },
            operation_id="open-repeated-cause-repair",
        )
        self.assertNotEqual(
            first_repair_open.result["repair_id"],
            repeated_cause_open.result["repair_id"],
        )
        stale_exhaustion = engineering_failure_disposition(
            self.writer,
            job_id=job_id,
            evidence_hashes=(reproduction.sha256,),
            repair_attempt_record_ids=(
                failed_attempt_one.result["attempt_record_id"],
                failed_attempt_two.result["attempt_record_id"],
            ),
            disposition="repair_exhausted_changed_causes",
        )
        with self.assertRaisesRegex(
            TransitionError,
            "differs from exact failed Repair attempts",
        ):
            self.writer.conclude_repair_unrecovered(
                disposition_hash=stale_exhaustion,
                operation_id="reject-prior-episode-exhaustion",
            )
        repeated_change = self.writer.evidence.finalize(
            b"second changed basis for repeated parser cause"
        )
        repeated_verification = self.writer.evidence.finalize(
            b"second independent verification for repeated parser cause"
        )
        repeated_attempt = repair_attempt_proof(
            self.writer,
            outcome="repaired",
            changed_dimension="input",
            new_basis_hash=repeated_change.sha256,
            new_evidence_hashes=(repeated_change.sha256,),
            verification_evidence_hashes=(
                repeated_verification.sha256,
            ),
        )
        with self.assertRaisesRegex(
            TransitionError,
            "changed Job input requires a new Job identity",
        ):
            self.writer.close_repair(
                changed_cause_proof_hash=repeated_attempt,
                operation_id="reject-in-place-input-repair",
            )
        repeated_attempt = repair_attempt_proof(
            self.writer,
            outcome="repaired",
            changed_dimension="cause",
            new_basis_hash=repeated_change.sha256,
            new_evidence_hashes=(repeated_change.sha256,),
            verification_evidence_hashes=(
                repeated_verification.sha256,
            ),
        )
        self.writer.close_repair(
            changed_cause_proof_hash=repeated_attempt,
            operation_id="close-repeated-cause-repair",
        )
        resumed_second = self.writer.verify_running_job_execution(
            execution,
            expected_callable_identity="fixture.callable",
        )
        self.assertNotEqual(
            resumed_first["repair_resume_record_id"],
            resumed_second["repair_resume_record_id"],
        )

        implementation_reproduction = self.writer.evidence.finalize(
            b"fixture running Job implementation defect"
        )
        implementation_permit = self.writer.issue_permit(
            kind=PermitKind.REPAIR,
            subject_kind=SubjectKind.JOB,
            subject_id=job_id,
            input_hash=job_hash,
            actions=("open_repair",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="issue-implementation-repair-permit",
        )
        implementation_open = self.writer.open_repair(
            permit=implementation_permit,
            failure={
                "failure_kind": "engineering",
                "minimum_reproduction_evidence": [
                    implementation_reproduction.sha256
                ],
                "root_cause": "fixture running implementation defect",
                "interrupted_action": "fixture.callable",
            },
            operation_id="open-implementation-repair",
        )
        changed_source = self.writer.evidence.finalize(
            b"fixture repaired running Job source"
        )
        changed_implementation = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "artifact_hashes": [changed_source.sha256],
                    "callable_identity": "fixture.callable",
                    "protocol": "python.source.fixture.v1",
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        proof_manifest = {
            "changed_dimension": "implementation",
            "explanation": "repair fixture running implementation",
            "job_hash": job_hash,
            "job_id": job_id,
            "new_evidence_hashes": sorted(
                [
                    changed_implementation.sha256,
                    changed_source.sha256,
                ]
            ),
            "new_implementation_identity": changed_implementation.sha256,
            "previous_implementation_identity": oversized_job[
                "implementation_identity"
            ],
            "repair_id": implementation_open.result["repair_id"],
            "reproduction_evidence_hashes": [
                implementation_reproduction.sha256
            ],
            "schema": "running_job_implementation_repair.v1",
        }
        incomplete_proof = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    **proof_manifest,
                    "new_evidence_hashes": [
                        changed_implementation.sha256
                    ],
                }
            )
        )
        implementation_verification = self.writer.evidence.finalize(
            b"independent running Job implementation Repair verification"
        )
        incomplete_attempt = repair_attempt_proof(
            self.writer,
            outcome="repaired",
            changed_dimension="implementation",
            new_basis_hash=changed_implementation.sha256,
            new_evidence_hashes=(
                changed_implementation.sha256,
                incomplete_proof.sha256,
            ),
            verification_evidence_hashes=(
                implementation_verification.sha256,
            ),
            implementation_proof_hash=incomplete_proof.sha256,
        )
        with self.assertRaisesRegex(TransitionError, "omits source bytes"):
            self.writer.close_repair(
                changed_cause_proof_hash=incomplete_attempt,
                operation_id="reject-incomplete-implementation-repair",
            )
        changed_proof = self.writer.evidence.finalize(
            canonical_bytes(proof_manifest)
        )
        changed_attempt = repair_attempt_proof(
            self.writer,
            outcome="repaired",
            changed_dimension="implementation",
            new_basis_hash=changed_implementation.sha256,
            new_evidence_hashes=(
                changed_implementation.sha256,
                changed_proof.sha256,
                changed_source.sha256,
            ),
            verification_evidence_hashes=(
                implementation_verification.sha256,
            ),
            implementation_proof_hash=changed_proof.sha256,
        )
        repaired = self.writer.close_repair(
            changed_cause_proof_hash=changed_attempt,
            operation_id="close-implementation-repair",
        )
        self.assertEqual(
            repaired.result["effective_implementation_identity"],
            changed_implementation.sha256,
        )
        binding = self.writer.verify_running_job_execution(
            execution,
            expected_callable_identity="fixture.callable",
        )
        self.assertEqual(
            binding["effective_implementation_identity"],
            changed_implementation.sha256,
        )
        self.assertIsNotNone(binding["implementation_repair_record_id"])

        transient = self.root / "local" / "jobs" / "fixture" / "fixture.json"
        transient.parent.mkdir(parents=True, exist_ok=True)
        transient.write_bytes(b"fixture output")
        completion = self.writer.complete_job(
            outcome="success",
            output_manifest={
                "local/jobs/fixture/fixture.json": sha256(b"fixture output").hexdigest()
            },
            operation_id="complete-job",
        )
        self.assertFalse(transient.exists())

        self.writer.judge_job_evidence(
            completion_record_id=completion.result["completion_record_id"],
            disposition="stop_batch",
            operation_id="judge-completed-job",
        )

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

    def test_failed_repair_attempts_require_changed_basis_and_typed_exit(self) -> None:
        self.open_mission_and_initiative()
        opened_study = self.open_fixture_study(
            study_id="STU-REPAIR-EXIT",
            question=study_question("typed unrecovered Repair exit"),
            semantic_proposal={"mechanism": "repair exit fixture"},
            operation_prefix="repair-exit-study",
        )
        repair_batch = batch_spec(
            batch_id="BAT-REPAIR-EXIT",
            study_id="STU-REPAIR-EXIT",
            study_hash=opened_study.result["study_hash"],
        )
        batch_permit = self.writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-REPAIR-EXIT",
            input_hash=repair_batch.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="permit-repair-exit-batch",
        )
        self.writer.open_batch(
            batch_spec=repair_batch,
            permit=batch_permit,
            operation_id="open-repair-exit-batch",
        )
        spec = job_spec(
            self.writer,
            {"kind": "Study", "id": "STU-REPAIR-EXIT"},
        )
        declared = self.writer.declare_job(
            spec=spec,
            operation_id="declare-failed-repair-attempt-job",
        )
        job_id = declared.result["job_id"]
        job_hash = declared.result["job_hash"]
        start_permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=job_id,
            input_hash=job_hash,
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="permit-failed-repair-attempt-job",
        )
        self.writer.start_job(
            permit=start_permit,
            operation_id="start-failed-repair-attempt-job",
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
            operation_id="permit-failed-repair-attempt",
        )
        reproduction = self.writer.evidence.finalize(
            b"persistent engineering failure reproduction"
        )
        self.writer.open_repair(
            permit=repair_permit,
            failure={
                "failure_kind": "engineering",
                "minimum_reproduction_evidence": [reproduction.sha256],
                "root_cause": "first suspected parser cause",
                "interrupted_action": spec["callable_identity"],
            },
            operation_id="open-failed-repair-attempt",
        )

        first_basis = self.writer.evidence.finalize(
            b"first changed Repair basis"
        )
        first_verification = self.writer.evidence.finalize(
            b"first independent Repair verification"
        )
        first_proof = repair_attempt_proof(
            self.writer,
            outcome="failed",
            changed_dimension="cause",
            new_basis_hash=first_basis.sha256,
            new_evidence_hashes=(first_basis.sha256,),
            verification_evidence_hashes=(first_verification.sha256,),
        )
        first = self.writer.record_failed_repair_attempt(
            attempt_proof_hash=first_proof,
            operation_id="record-first-failed-repair-attempt",
        )
        retried_first = self.writer.record_failed_repair_attempt(
            attempt_proof_hash=first_proof,
            operation_id="record-first-failed-repair-attempt",
        )
        self.assertTrue(retried_first.reused)
        self.assertEqual(first.result, retried_first.result)
        with self.assertRaises(TransitionError):
            self.writer.record_failed_repair_attempt(
                attempt_proof_hash=first_proof,
                operation_id="reject-identical-failed-repair-attempt",
            )
        one_attempt_disposition = engineering_failure_disposition(
            self.writer,
            job_id=job_id,
            evidence_hashes=(first_verification.sha256,),
            repair_attempt_record_ids=(first.result["attempt_record_id"],),
            disposition="repair_exhausted_changed_causes",
        )
        with self.assertRaisesRegex(TransitionError, "one failed Repair attempt"):
            self.writer.conclude_repair_unrecovered(
                disposition_hash=one_attempt_disposition,
                operation_id="reject-single-attempt-exhaustion",
            )

        second_basis = self.writer.evidence.finalize(
            b"second changed Repair basis"
        )
        second_verification = self.writer.evidence.finalize(
            b"second independent Repair verification"
        )
        second_proof = repair_attempt_proof(
            self.writer,
            outcome="failed",
            changed_dimension="information",
            new_basis_hash=second_basis.sha256,
            new_evidence_hashes=(second_basis.sha256,),
            verification_evidence_hashes=(second_verification.sha256,),
        )
        second = self.writer.record_failed_repair_attempt(
            attempt_proof_hash=second_proof,
            operation_id="record-second-failed-repair-attempt",
        )
        disposition_hash = engineering_failure_disposition(
            self.writer,
            job_id=job_id,
            evidence_hashes=(
                first_verification.sha256,
                second_verification.sha256,
            ),
            repair_attempt_record_ids=(
                first.result["attempt_record_id"],
                second.result["attempt_record_id"],
            ),
            disposition="repair_exhausted_changed_causes",
        )
        with patch.object(
            LocalIndex,
            "records_by_kind",
            side_effect=AssertionError(
                "Repair disposition must use the indexed subject/status query"
            ),
        ):
            concluded = self.writer.conclude_repair_unrecovered(
                disposition_hash=disposition_hash,
                operation_id="conclude-changed-cause-exhaustion",
            )
        retried_conclusion = self.writer.conclude_repair_unrecovered(
            disposition_hash=disposition_hash,
            operation_id="conclude-changed-cause-exhaustion",
        )
        self.assertTrue(retried_conclusion.reused)
        self.assertEqual(concluded.result, retried_conclusion.result)
        self.assertEqual(
            concluded.result["disposition_hash"], disposition_hash
        )
        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(
            control["next_action"],
            {
                "disposition_hash": disposition_hash,
                "job_id": job_id,
                "kind": "complete_engineering_failure",
            },
        )
        completed = self.writer.complete_job(
            outcome="failed",
            output_manifest={},
            failure={
                "failure_kind": "engineering",
                "minimum_reproduction_evidence": [reproduction.sha256],
                "root_cause": "first suspected parser cause",
                "interrupted_action": spec["callable_identity"],
                "repair_disposition_hash": disposition_hash,
                "resume_action": spec["resume_action"],
            },
            operation_id="complete-typed-unrecovered-engineering-failure",
        )
        with LocalIndex(self.writer.index_path) as index:
            record = index.get(
                "job-completed", completed.result["completion_record_id"]
            )
        assert record is not None
        self.assertEqual(
            record.payload["engineering_disposition"]["disposition"],
            "repair_exhausted_changed_causes",
        )
        self.writer.judge_job_evidence(
            completion_record_id=completed.result["completion_record_id"],
            disposition="stop_batch",
            operation_id="judge-unrecovered-engineering-failure",
        )
        with LocalIndex(self.writer.index_path) as index:
            kpi_source = self.writer._study_kpi_from_completion(
                index=index,
                study_id="STU-REPAIR-EXIT",
                completion_record_id=completed.result[
                    "completion_record_id"
                ],
            )
        self.assertEqual(
            kpi_source["source"],
            "typed_engineering_failure_completion",
        )
        self.assertEqual(
            kpi_source["unavailable_reason"],
            "engineering_failure",
        )
        self.writer.dispose_batch(
            outcome="engineering_failure",
            operation_id="dispose-unrecovered-engineering-batch",
        )
        closed = self.writer.close_study(
            outcome="not_evaluable",
            kpi_completion_record_id=completed.result[
                "completion_record_id"
            ],
            operation_id="close-unrecovered-engineering-study",
        )
        self.assertEqual(closed.result["outcome"], "not_evaluable")

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
        self.writer.clock = lambda: "2026-07-11T01:00:00Z"
        with self.assertRaisesRegex(PermitError, "runtime provenance"):
            self.writer.issue_permit(
                kind=PermitKind.SOURCE,
                subject_kind=SubjectKind.STUDY,
                subject_id="STU-SOURCE",
                input_hash=source_batch_hash,
                actions=("runtime_source_use",),
                scope=(f"source:{contract.source_contract_id}",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="reject-stale-runtime-source-permit",
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
        source_component = ComponentSpec(
            display_name="stale offline source fixture component",
            protocol="feature.engineering_fixture.v1",
            implementation="fixture.component.stale_offline_source",
            spec={"tag": "stale-offline-source"},
            semantic_dependencies=(contract.source_contract_id,),
        )
        source_executable = ExecutableSpec(
            display_name="stale offline source fixture executable",
            components=(source_component,),
            parameters={"tag": "stale-offline-source"},
            data_contract="data:engineering_fixture",
            split_contract="split:engineering_fixture",
            clock_contract="clock:completed_bar_fixture",
            cost_contract="cost:engineering_fixture",
            engine_contract="engine:engineering_fixture",
            source_contracts=(contract.source_contract_id,),
        )
        registered = self.writer.register_trial(
            executable=source_executable,
            operation_id="register-stale-offline-source-trial",
        )
        self.assertEqual(registered.result["trial_delta"], 0)

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

    def test_stale_candidate_runtime_can_report_and_recertify_its_source(
        self,
    ) -> None:
        self.writer.open_mission(
            mission_id="MIS-CANDIDATE-SOURCE-RECOVERY",
            goal=mission_goal("candidate source recovery"),
            operation_id="candidate-source-recovery-mission",
        )
        self.writer.validation_registry = EvidenceValidatorRegistry(
            (
                EngineeringFixtureValidator(),
                SourceBoundaryFixtureValidator(),
            )
        )
        contract = source_contract()
        context = SourceEligibility.register(contract)
        self.writer.record_source_eligibility(
            eligibility=context,
            receipt=None,
            operation_id="candidate-source-recovery-context",
        )
        historical_artifact = self.writer.evidence.finalize(
            b"candidate source historical audit"
        )
        historical_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.HISTORICAL_AUDIT,
            producer_completion_id="engineering-fixture",
            observed_at_utc=FIXED_NOW,
            artifact_hashes=(historical_artifact.sha256,),
            facts={
                "acquisition_observed": True,
                "content_hash_verified": True,
                "coverage_audited": True,
                "event_time_audited": True,
                "first_availability_audited": True,
                "gaps_audited": True,
                "information_complete_at_audited": True,
                "revision_or_vintage_audited": True,
            },
        )
        audited = context.complete_historical_audit(
            historical_receipt.identity
        )
        self.writer.record_source_eligibility(
            eligibility=audited,
            receipt=historical_receipt,
            operation_id="candidate-source-recovery-audit",
        )
        runtime_artifact = self.writer.evidence.finalize(
            b"candidate source initial runtime proof"
        )
        runtime_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
            producer_completion_id="engineering-fixture",
            observed_at_utc=FIXED_NOW,
            artifact_hashes=(runtime_artifact.sha256,),
            facts={
                "complete_or_closed": True,
                "fresh": True,
                "historical_runtime_field_parity": True,
                "latency_ms": 5,
                "local_realtime_retrieval": True,
                "synchronized": True,
            },
        )
        eligible = audited.prove_runtime_availability(
            runtime_receipt.identity
        )
        self.writer.record_source_eligibility(
            eligibility=eligible,
            receipt=runtime_receipt,
            operation_id="candidate-source-recovery-runtime",
        )
        component = ComponentSpec(
            display_name="candidate source recovery component",
            protocol="feature.engineering_fixture.v1",
            implementation="fixture.component.candidate_source_recovery",
            spec={"tag": "candidate-source-recovery"},
            semantic_dependencies=(contract.source_contract_id,),
        )
        executable = ExecutableSpec(
            display_name="candidate source recovery executable",
            components=(component,),
            parameters={"tag": "candidate-source-recovery"},
            data_contract="data:engineering_fixture",
            split_contract="split:engineering_fixture",
            clock_contract="clock:completed_bar_fixture",
            cost_contract="cost:engineering_fixture",
            engine_contract="engine:engineering_fixture",
            source_contracts=(contract.source_contract_id,),
        )
        frozen = self.writer.freeze_candidate(
            executable=executable,
            evidence_refs=("engineering-source-candidate-evidence",),
            operation_id="candidate-source-recovery-freeze",
        )
        runtime_spec = runtime_job_spec(
            writer=self.writer,
            executable_id=executable.identity,
            depth=EvidenceDepth.EXECUTION_PROOF,
            output_name="evidence/stale-candidate-runtime",
            artifact_roles=("native_execution_report", "parity_report"),
        )
        declared = self.writer.declare_job(
            spec=runtime_spec,
            operation_id="stale-candidate-runtime-declare",
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
            operation_id="stale-candidate-runtime-job-permit",
        )
        runtime_permit = self.writer.issue_permit(
            kind=PermitKind.RUNTIME,
            subject_kind=SubjectKind.EXECUTABLE,
            subject_id=executable.identity,
            input_hash=declared.result["job_hash"],
            actions=("run_execution_proof",),
            scope=(
                f"candidate:{frozen.result['candidate_id']}",
                "depth:execution_proof",
                f"executable:{executable.identity}",
                f"job:{declared.result['job_id']}",
                f"source:{contract.source_contract_id}",
            ),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=False,
            operation_id="stale-candidate-runtime-permit",
        )
        self.writer.start_job(
            permit=job_permit,
            runtime_permit=runtime_permit,
            operation_id="stale-candidate-runtime-start",
        )
        self.writer.clock = lambda: "2026-07-11T01:00:00Z"
        with self.assertRaisesRegex(PermitError, "runtime provenance"):
            self.writer.validate_runtime_entry(
                permit=runtime_permit,
                executable_id=executable.identity,
                input_hash=declared.result["job_hash"],
                action="run_execution_proof",
                depth=EvidenceDepth.EXECUTION_PROOF,
                operation_id="stale-candidate-runtime-entry",
            )
        with LocalIndex(self.writer.index_path) as index:
            source_head = index.event_head(
                f"source:{contract.source_contract_id}"
            )
        assert source_head is not None
        stale_observation = self.writer.evidence.finalize(
            b"candidate runtime source TTL expired before engine entry"
        )
        completed = self.writer.complete_job(
            outcome="not_evaluable",
            output_manifest={},
            failure={
                "failure_kind": "runtime_source_ineligibility",
                "interrupted_action": runtime_spec["callable_identity"],
                "minimum_reproduction_evidence": [stale_observation.sha256],
                "resume_action": runtime_spec["resume_action"],
                "root_cause": "runtime source eligibility TTL expired",
                "source_contract_id": contract.source_contract_id,
                "source_state_record_id": source_head.record_id,
            },
            operation_id="stale-candidate-runtime-complete",
        )
        self.assertEqual(completed.result["outcome"], "not_evaluable")
        self.assertEqual(
            self.writer.read_control()["next_action"],  # type: ignore[index]
            {
                "executable_id": executable.identity,
                "kind": "plan_candidate_bound_evidence",
            },
        )
        drift_artifact = self.writer.evidence.finalize(
            b"candidate source stale drift receipt"
        )
        drift_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.DRIFT,
            producer_completion_id="engineering-fixture",
            observed_at_utc="2026-07-11T01:00:00Z",
            artifact_hashes=(drift_artifact.sha256,),
            facts={
                "changed_surface": "availability",
                "dependent_action": "fail_closed",
                "observed_change": "runtime eligibility TTL expired",
            },
        )
        suspended = eligible.suspend(
            receipt_id=drift_receipt.identity,
            reason="runtime eligibility TTL expired",
        )
        self.writer.record_source_eligibility(
            eligibility=suspended,
            receipt=drift_receipt,
            operation_id="candidate-source-recovery-suspend",
        )
        result_name = "evidence/candidate-source-recert-result"
        measurement_name = "evidence/candidate-source-recert-measurement"
        source_spec = job_spec(
            self.writer,
            {"kind": "Executable", "id": executable.identity},
        )
        source_spec["input_hashes"] = [
            *source_spec["input_hashes"],  # type: ignore[list-item]
            SOURCE_BOUNDARY_PLAN_HASH,
        ]
        source_spec["expected_outputs"] = [result_name, measurement_name]
        source_spec["output_classes"] = {
            result_name: "durable_evidence",
            measurement_name: "durable_evidence",
        }
        source_spec["source_binding"] = {
            "result_manifest_output": result_name,
            "source_contract_id": contract.source_contract_id,
            "transition_evidence": "same_semantics_recertification",
            "validation_plan_hash": SOURCE_BOUNDARY_PLAN_HASH,
            "validator_id": SourceBoundaryFixtureValidator.validator_id,
        }
        source_declared = self.writer.declare_job(
            spec=source_spec,
            operation_id="candidate-source-recert-declare",
        )
        source_permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=source_declared.result["job_id"],
            input_hash=source_declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="candidate-source-recert-permit",
        )
        self.writer.start_job(
            permit=source_permit,
            operation_id="candidate-source-recert-start",
        )
        recert_facts = {
            "mapping_parity": True,
            "schema_field_clock_parity": True,
            "semantic_equivalence": True,
        }
        measurement = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "facts": recert_facts,
                    "schema": "source_boundary_measurement.v1",
                }
            )
        )
        result = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "facts": recert_facts,
                    "job_hash": source_declared.result["job_hash"],
                    "job_id": source_declared.result["job_id"],
                    "measurement_artifact_hashes": [measurement.sha256],
                    "mission_id": "MIS-CANDIDATE-SOURCE-RECOVERY",
                    "observed_at_utc": "2026-07-11T01:00:00Z",
                    "schema": "source_eligibility_evidence.v1",
                    "source_contract_id": contract.source_contract_id,
                    "transition_evidence": "same_semantics_recertification",
                }
            )
        )
        source_completed = self.writer.complete_job(
            outcome="success",
            output_manifest={
                result_name: result.sha256,
                measurement_name: measurement.sha256,
            },
            operation_id="candidate-source-recert-complete",
        )
        recert_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION,
            producer_completion_id=source_completed.result[
                "completion_record_id"
            ],
            observed_at_utc="2026-07-11T01:00:00Z",
            artifact_hashes=(measurement.sha256,),
            facts=recert_facts,
        )
        restored = SourceEligibility(
            contract=contract,
            state=SourceEligibilityState.RUNTIME_ELIGIBLE,
            evidence_receipt_id=recert_receipt.identity,
        )
        self.writer.record_source_eligibility(
            eligibility=restored,
            receipt=recert_receipt,
            operation_id="candidate-source-recert-record",
        )
        self.assertEqual(
            self.writer.read_control()["next_action"],  # type: ignore[index]
            {
                "executable_id": executable.identity,
                "kind": "plan_candidate_bound_evidence",
            },
        )
        drift_runtime_declared = self.writer.declare_job(
            spec=runtime_spec,
            operation_id="active-drift-runtime-declare",
        )
        drift_job_permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=drift_runtime_declared.result["job_id"],
            input_hash=drift_runtime_declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="active-drift-runtime-job-permit",
        )
        drift_runtime_permit = self.writer.issue_permit(
            kind=PermitKind.RUNTIME,
            subject_kind=SubjectKind.EXECUTABLE,
            subject_id=executable.identity,
            input_hash=drift_runtime_declared.result["job_hash"],
            actions=("run_execution_proof",),
            scope=(
                f"candidate:{frozen.result['candidate_id']}",
                "depth:execution_proof",
                f"executable:{executable.identity}",
                f"job:{drift_runtime_declared.result['job_id']}",
                f"source:{contract.source_contract_id}",
            ),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=False,
            operation_id="active-drift-runtime-permit",
        )
        self.writer.start_job(
            permit=drift_job_permit,
            runtime_permit=drift_runtime_permit,
            operation_id="active-drift-runtime-start",
        )
        entered = self.writer.validate_runtime_entry(
            permit=drift_runtime_permit,
            executable_id=executable.identity,
            input_hash=drift_runtime_declared.result["job_hash"],
            action="run_execution_proof",
            depth=EvidenceDepth.EXECUTION_PROOF,
            operation_id="active-drift-runtime-entry",
        )
        control = self.writer.read_control()
        assert control is not None
        active_job = control["scientific"]["active_job"]
        assert isinstance(active_job, dict)
        with LocalIndex(self.writer.index_path) as index:
            source_head = index.event_head(f"source:{contract.source_contract_id}")
        assert source_head is not None
        drift_facts = {
            "changed_surface": "runtime_availability",
            "dependent_action": "fail_closed",
            "observed_change": "source became unavailable during runtime execution",
        }
        observation = RuntimeSourceDriftObservation(
            candidate_id=frozen.result["candidate_id"],
            executable_id=executable.identity,
            facts=drift_facts,
            job_hash=drift_runtime_declared.result["job_hash"],
            job_id=drift_runtime_declared.result["job_id"],
            job_start_record_id=active_job["start_record_id"],
            observed_at_utc="2026-07-11T01:00:00Z",
            prior_source_receipt_id=recert_receipt.identity,
            prior_source_state_record_id=source_head.record_id,
            producer_record_id=entered.result["runtime_entry_record_id"],
            source_contract_id=contract.source_contract_id,
        )
        raw_drift = self.writer.evidence.finalize(
            b"untyped active runtime source drift"
        )
        untyped_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.DRIFT,
            producer_completion_id=entered.result["runtime_entry_record_id"],
            observed_at_utc="2026-07-11T01:00:00Z",
            artifact_hashes=(raw_drift.sha256,),
            facts=drift_facts,
        )
        with self.assertRaisesRegex(TransitionError, "typed observation"):
            self.writer.record_source_eligibility(
                eligibility=restored.suspend(
                    receipt_id=untyped_receipt.identity,
                    reason="active runtime source drift",
                ),
                receipt=untyped_receipt,
                operation_id="reject-untyped-active-runtime-drift",
            )
        observation_artifact = self.writer.evidence.finalize(observation.to_bytes())
        active_drift_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.DRIFT,
            producer_completion_id=entered.result["runtime_entry_record_id"],
            observed_at_utc="2026-07-11T01:00:00Z",
            artifact_hashes=(observation_artifact.sha256,),
            facts=drift_facts,
        )
        active_suspended = restored.suspend(
            receipt_id=active_drift_receipt.identity,
            reason="active runtime source drift",
        )
        drift_recorded = self.writer.record_source_eligibility(
            eligibility=active_suspended,
            receipt=active_drift_receipt,
            operation_id="record-active-runtime-drift",
        )
        self.assertEqual(
            drift_recorded.result["runtime_source_drift_observation_id"],
            observation.identity,
        )
        with LocalIndex(self.writer.index_path) as index:
            suspended_head = index.event_head(
                f"source:{contract.source_contract_id}"
            )
        assert suspended_head is not None
        self.assertEqual(
            self.writer.read_control()["next_action"],  # type: ignore[index]
            {
                "job_id": drift_runtime_declared.result["job_id"],
                "kind": "complete_runtime_source_ineligibility",
                "observation_id": observation.identity,
                "source_contract_id": contract.source_contract_id,
                "source_state_record_id": suspended_head.record_id,
            },
        )
        completed_drift = self.writer.complete_job(
            outcome="not_evaluable",
            output_manifest={},
            failure={
                "failure_kind": "runtime_source_ineligibility",
                "interrupted_action": runtime_spec["callable_identity"],
                "minimum_reproduction_evidence": [observation_artifact.sha256],
                "resume_action": runtime_spec["resume_action"],
                "root_cause": "source drifted during runtime execution",
                "source_contract_id": contract.source_contract_id,
                "source_state_record_id": suspended_head.record_id,
            },
            operation_id="complete-active-runtime-drift",
        )
        self.assertEqual(completed_drift.result["outcome"], "not_evaluable")
        self.assertEqual(
            self.writer.read_control()["next_action"],  # type: ignore[index]
            {
                "executable_id": executable.identity,
                "kind": "plan_candidate_bound_evidence",
            },
        )

    def test_generic_job_cannot_report_scientific_falsification(self) -> None:
        self.open_mission_and_initiative()
        spec = job_spec(
            self.writer,
            {"kind": "Initiative", "id": "INI-FIXTURE"},
        )
        declared = self.writer.declare_job(
            spec=spec,
            operation_id="declare-generic-failure-kind-boundary",
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
            operation_id="permit-generic-failure-kind-boundary",
        )
        self.writer.start_job(
            permit=permit,
            operation_id="start-generic-failure-kind-boundary",
        )
        reproduction = self.writer.evidence.finalize(
            b"generic Job failure-kind boundary fixture"
        )
        common = {
            "minimum_reproduction_evidence": [reproduction.sha256],
            "root_cause": "fixture failure",
            "interrupted_action": spec["callable_identity"],
            "resume_action": spec["resume_action"],
        }
        with self.assertRaisesRegex(
            TransitionError,
            "scientific verdict is not a Job execution failure",
        ):
            self.writer.complete_job(
                outcome="failed",
                output_manifest={},
                failure={
                    **common,
                    "failure_kind": "scientific_falsification",
                },
                operation_id="reject-generic-scientific-falsification",
            )
        with self.assertRaisesRegex(
            TransitionError,
            "engineering failure disposition",
        ):
            self.writer.complete_job(
                outcome="failed",
                output_manifest={},
                failure={**common, "failure_kind": "engineering"},
                operation_id="reject-unexplained-engineering-abandonment",
            )
        disposition_hash = engineering_failure_disposition(
            self.writer,
            job_id=declared.result["job_id"],
            evidence_hashes=(reproduction.sha256,),
            cause_hash=canonical_digest(
                domain="repair-cause",
                payload={
                    "failure_kind": "engineering",
                    "interrupted_action": spec["callable_identity"],
                    "minimum_reproduction_evidence": [
                        reproduction.sha256
                    ],
                    "root_cause": "fixture failure",
                },
            ),
        )
        with self.assertRaisesRegex(
            TransitionError,
            "exact durable disposition",
        ):
            self.writer.complete_job(
                outcome="failed",
                output_manifest={},
                failure={
                    **common,
                    "failure_kind": "engineering",
                    "repair_disposition_hash": disposition_hash,
                },
                operation_id="reject-unrecorded-engineering-disposition",
            )
        self.writer.record_engineering_failure_disposition(
            failure={
                "failure_kind": "engineering",
                "interrupted_action": spec["callable_identity"],
                "minimum_reproduction_evidence": [reproduction.sha256],
                "root_cause": "fixture failure",
            },
            disposition_hash=disposition_hash,
            operation_id="record-generic-engineering-disposition",
        )
        completed = self.writer.complete_job(
            outcome="failed",
            output_manifest={},
            failure={
                **common,
                "failure_kind": "engineering",
                "repair_disposition_hash": disposition_hash,
            },
            operation_id="complete-generic-engineering-failure",
        )
        self.assertEqual(completed.result["outcome"], "failed")

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
        common_failure = {
            "minimum_reproduction_evidence": [reproduction.sha256],
            "root_cause": "fixture callable rejected its input",
            "interrupted_action": "fixture.callable",
            "resume_action": "resume_fixture_job",
        }
        with self.assertRaisesRegex(
            TransitionError,
            "validator verdict",
        ):
            self.writer.complete_job(
                outcome="not_evaluable",
                output_manifest={},
                failure={
                    **common_failure,
                    "failure_kind": "not_evaluable",
                },
                operation_id="reject-untyped-not-evaluable-label",
            )
        with self.assertRaisesRegex(
            TransitionError,
            "exact failure-kind semantics",
        ):
            self.writer.complete_job(
                outcome="failed",
                output_manifest={},
                failure={
                    **common_failure,
                    "failure_kind": "runtime_source_ineligibility",
                },
                operation_id="reject-failed-runtime-source-label",
            )
        with self.assertRaisesRegex(
            TransitionError,
            "requires a runtime-bound Job",
        ):
            self.writer.complete_job(
                outcome="not_evaluable",
                output_manifest={},
                failure={
                    **common_failure,
                    "failure_kind": "runtime_source_ineligibility",
                    "source_contract_id": "source:non-runtime-fixture",
                    "source_state_record_id": "a" * 64,
                },
                operation_id="reject-non-runtime-source-ineligibility",
            )
        cause_failure = {
            "failure_kind": "engineering",
            "minimum_reproduction_evidence": [reproduction.sha256],
            "root_cause": "fixture callable rejected its input",
            "interrupted_action": "fixture.callable",
        }
        cause_hash = canonical_digest(
            domain="repair-cause",
            payload=cause_failure,
        )
        disposition_hash = engineering_failure_disposition(
            self.writer,
            job_id=declared.result["job_id"],
            evidence_hashes=(reproduction.sha256,),
            disposition="repair_infeasible",
            cause_hash=cause_hash,
        )
        self.writer.record_engineering_failure_disposition(
            failure=cause_failure,
            disposition_hash=disposition_hash,
            operation_id="record-structured-engineering-disposition",
        )
        completed = self.writer.complete_job(
            outcome="failed",
            output_manifest={},
            failure={
                "failure_kind": "engineering",
                "minimum_reproduction_evidence": [reproduction.sha256],
                "root_cause": "fixture callable rejected its input",
                "interrupted_action": "fixture.callable",
                "resume_action": "resume_fixture_job",
                "repair_disposition_hash": disposition_hash,
            },
            operation_id="record-structured-failure",
        )
        self.assertEqual(completed.result["outcome"], "failed")
        self.assertIsNone(self.writer.read_control()["scientific"]["active_job"])  # type: ignore[index]
        duplicate_input_retry = job_spec(
            self.writer, {"kind": "Mission", "id": "MIS-FAILURE"}
        )
        duplicate_input_retry["input_hashes"] = [
            *duplicate_input_retry["input_hashes"],
            duplicate_input_retry["input_hashes"][0],
        ]
        with self.assertRaisesRegex(TransitionError, "sorted unique"):
            self.writer.declare_job(
                spec=duplicate_input_retry,
                operation_id="reject-duplicate-input-failed-retry",
            )
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
        implementation_retry = job_spec(
            self.writer, {"kind": "Mission", "id": "MIS-FAILURE"}
        )
        previous_implementation = implementation_retry[
            "implementation_identity"
        ]
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
        protocol_only_retry = dict(implementation_retry)
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
        unordered_retry = dict(implementation_retry)
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
                    "callable_identity": implementation_retry[
                        "callable_identity"
                    ],
                    "protocol": "python.source.fixture.v1",
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        implementation_retry["implementation_identity"] = (
            changed_evidence.sha256
        )
        with LocalIndex(self.writer.index_path) as index:
            prior_declaration = index.get(
                "job-declared",
                declared.result["job_id"],
            )
        assert prior_declaration is not None
        implementation_binding = {
            "authority_kind": "implementation_cause_resolution",
            "changed_dimension": "implementation",
            "failure_signature": completed.result["failure_signature"],
            "new_artifact_hashes": [changed_source.sha256],
            "new_implementation_identity": changed_evidence.sha256,
            "new_work_fingerprint": prior_declaration.payload[
                "work_fingerprint"
            ],
            "previous_artifact_hashes": list(
                previous_manifest["artifact_hashes"]
            ),
            "previous_implementation_identity": previous_implementation,
            "prior_completion_record_id": completed.result[
                "completion_record_id"
            ],
            "prior_job_hash": prior_declaration.fingerprint,
            "prior_job_id": prior_declaration.record_id,
            "prior_work_fingerprint": prior_declaration.payload[
                "work_fingerprint"
            ],
            "retry_family_fingerprint": prior_declaration.payload[
                "retry_family_fingerprint"
            ],
            "schema": "engineering_retry_validation_binding.v1",
            "scientific_semantics_changed": False,
        }
        validation_plan_hash, validation_results = (
            engineering_retry_validation_artifacts(
                self.writer,
                binding=implementation_binding,
                validator_id=ENGINEERING_RETRY_VALIDATOR_ID,
            )
        )
        changed = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "changed_dimension": "implementation",
                    "explanation": "fixture callable implementation was repaired",
                    "new_evidence_hashes": sorted(
                        [changed_evidence.sha256, changed_source.sha256]
                    ),
                    "new_implementation_identity": changed_evidence.sha256,
                    "prior_failure_signature": completed.result[
                        "failure_signature"
                    ],
                    "previous_implementation_identity": previous_implementation,
                    "result_artifact_hashes": validation_results,
                    "schema": "job_changed_cause.v1",
                    "validation_plan_hash": validation_plan_hash,
                    "validator_id": ENGINEERING_RETRY_VALIDATOR_ID,
                }
            )
        )
        implementation_retry["changed_cause_proof_hash"] = changed.sha256
        retried = self.writer.declare_job(
            spec=implementation_retry,
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
        duplicate_cache_input = dict(cache_spec)
        duplicate_cache_input["input_hashes"] = [
            *cache_spec["input_hashes"],
            cache_spec["input_hashes"][0],
        ]
        with self.assertRaisesRegex(TransitionError, "sorted unique"):
            self.writer.declare_job(
                spec=duplicate_cache_input,
                operation_id="reject-duplicate-input-cache-bypass",
            )
        self.assertEqual(self.writer.read_control(), control_before_reuse)
        self.assertEqual(self.writer.journal.tail()[0], journal_before_reuse)
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
    @staticmethod
    def _seal_candidate_holdout(
        writer: StateWriter,
        *,
        tag: str,
    ) -> SealedHoldoutManifest:
        artifact = writer.evidence.finalize(
            f"sealed holdout values for {tag}".encode("ascii")
        )
        starts_at = "2026-07-01T00:00:00Z"
        ends_at = "2026-07-10T00:00:00Z"
        rows = SealedHoldoutManifest.rows_identity(
            artifact_sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
        )
        manifest = SealedHoldoutManifest(
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
            manifest=manifest,
            operation_id=f"{tag}-holdout-seal",
        )
        return manifest

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
        material_identity: str = OBSERVED_MATERIAL_ID,
        verify_material_guard: bool = False,
    ):
        spec = job_spec(writer, {"kind": "Executable", "id": executable_id})
        result_name = f"evidence/{tag}-result"
        measurement_name = f"evidence/{tag}-measurement"
        spec["input_hashes"] = [
            *spec["input_hashes"],
            material_identity,
            plan_hash,
        ]
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
        if verify_material_guard:
            missing_material = dict(spec)
            missing_material["input_hashes"] = [
                value
                for value in spec["input_hashes"]
                if value != material_identity
            ]
            control_before = writer.read_control()
            journal_before = writer.journal.tail()[0]
            with self.assertRaisesRegex(
                TransitionError, "omits its lineage material input"
            ):
                writer.declare_job(
                    spec=missing_material,
                    operation_id=f"{tag}-reject-missing-material",
                )
            self.assertEqual(writer.read_control(), control_before)
            self.assertEqual(writer.journal.tail()[0], journal_before)
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
        outputs = {
            result_name: result.sha256,
            measurement_name: measurement.sha256,
        }
        if verdict == "failed":
            with self.assertRaisesRegex(
                TransitionError,
                "scientific verdict is not a Job execution failure",
            ):
                writer.complete_job(
                    outcome="failed",
                    output_manifest=outputs,
                    failure={
                        "failure_kind": "scientific_falsification",
                        "minimum_reproduction_evidence": [measurement.sha256],
                        "root_cause": "fixture validator rejected the claim",
                        "interrupted_action": spec["callable_identity"],
                        "resume_action": spec["resume_action"],
                    },
                    operation_id=f"{tag}-reject-conflated-outcome",
                )
        completed = writer.complete_job(
            outcome="success",
            output_manifest=outputs,
            operation_id=f"{tag}-complete",
        )
        with LocalIndex(writer.index_path) as index:
            completion = index.get(
                "job-completed", completed.result["completion_record_id"]
            )
        assert completion is not None
        self.assertEqual(completion.status, "success")
        self.assertIsNone(completion.payload["failure"])
        self.assertEqual(completed.result["scientific_verdict"], verdict)
        trace = completion.payload["scientific"]["validation_trace"]
        self.assertEqual(trace["declared_artifact_count"], 2)
        self.assertEqual(trace["opened_artifact_count"], 2)
        return completed

    def _build_frozen_candidate(
        self, root: str, *, verify_material_guard: bool = False
    ):
        validator = ScientificFixtureValidator()
        foundation_root = legacy_scientific_fixture_foundation(Path(root))
        writer = StateWriter(
            root,
            permit_authority=PermitAuthority(b"h" * 32),
            clock=lambda: FIXED_NOW,
            study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
            foundation_root=foundation_root,
            validation_registry=EvidenceValidatorRegistry((validator,)),
        )
        writer.initialize_ready()
        writer.open_mission(
            mission_id="MIS-HOLDOUT-LIFECYCLE",
            goal=mission_goal("holdout disposition lifecycle"),
            operation_id="holdout-life-mission",
        )
        intake = record_fixture_research_intake(
            writer,
            mission_id="MIS-HOLDOUT-LIFECYCLE",
            operation_id="holdout-life-intake",
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
            research_intake_id=intake.identity,
            exhaustion_standard=exhaustion_standard(),
        )
        writer.record_portfolio_snapshot(
            snapshot=snapshot, operation_id="holdout-life-snapshot"
        )
        options = (
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
        )
        decision = PortfolioDecision(
            decision_id="DEC-HOLDOUT-LIFECYCLE",
            chosen_option_id="choose-a",
            options=options,
            rationale="build one frozen candidate while retaining alternatives",
            commitment_batches=1,
            baseline_executable=portfolio_axis_baseline(axes[0]),
            quant_team_review=quant_team_review_for_current_action(
                writer,
                options=options,
                chosen_option_id="choose-a",
            ),
        )
        writer.record_portfolio_decision(
            decision=decision, operation_id="holdout-life-decision"
        )
        question = study_question("holdout candidate evidence")
        proposal = {"mechanism": "holdout lifecycle boundary"}
        assert axes[0].architecture_chassis is not None
        controlled_chassis = ControlledStudyChassis(
            baseline_executable=decision.baseline_executable,
            changed_domains=axes[0].changed_domains,
            controlled_domains=axes[0].controlled_domains,
            architecture=axes[0].architecture_chassis,
        )
        study_hash = writer.study_input_hash(
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            semantic_proposal=proposal,
            controlled_chassis=controlled_chassis,
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
            scope=(
                "study",
                f"decision:{decision.identity}",
                f"axis:{axes[0].identity}",
                f"baseline:{decision.baseline_executable.identity}",
                f"chassis:{decision.architecture_chassis.identity}",
                f"snapshot:{snapshot.identity}",
            ),
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
            controlled_chassis=controlled_chassis,
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
            max_compute_seconds=90,
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
        generic_spec = job_spec(
            writer,
            {"kind": "Study", "id": "STU-HOLDOUT-LIFECYCLE"},
        )
        generic = writer.declare_job(
            spec=generic_spec,
            operation_id="holdout-life-generic-declare",
        )
        generic_permit = writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=generic.result["job_id"],
            input_hash=generic.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="holdout-life-generic-permit",
        )
        writer.start_job(
            permit=generic_permit,
            operation_id="holdout-life-generic-start",
        )
        generic_output = writer.root / "local" / "jobs" / "fixture" / "fixture.json"
        generic_output.parent.mkdir(parents=True, exist_ok=True)
        generic_output.write_bytes(b"generic engineering output")
        generic_completion = writer.complete_job(
            outcome="success",
            output_manifest={
                "local/jobs/fixture/fixture.json": sha256(
                    b"generic engineering output"
                ).hexdigest()
            },
            operation_id="holdout-life-generic-complete",
        )
        with self.assertRaisesRegex(TransitionError, "validator-derived"):
            writer.judge_job_evidence(
                completion_record_id=generic_completion.result[
                    "completion_record_id"
                ],
                disposition="stop_batch",
                operation_id="holdout-life-reject-generic-stop",
            )
        writer.judge_job_evidence(
            completion_record_id=generic_completion.result["completion_record_id"],
            disposition="continue_batch",
            operation_id="holdout-life-continue-generic",
        )
        with self.assertRaisesRegex(TransitionError, "budget is not exhausted"):
            writer.dispose_batch(
                outcome="budget_exhausted",
                operation_id="holdout-life-reject-false-budget-end",
            )
        with self.assertRaisesRegex(TransitionError, "failure basis"):
            writer.dispose_batch(
                outcome="engineering_failure",
                operation_id="holdout-life-reject-false-engineering-failure",
            )
        assert decision.baseline_executable is not None
        executable = changed_domain_executable(
            decision.baseline_executable,
            domain="calibration",
            change_tag="holdout-lifecycle",
        )
        writer.register_trial(
            executable=executable, operation_id="holdout-life-trial"
        )
        plan = writer.evidence.finalize(
            canonical_bytes({"schema": "scientific_boundary_plan.v1"})
        )
        completions = []
        for ordinal, depth in enumerate(("discovery", "confirmation"), start=1):
            tag = f"holdout-life-{depth}"
            claim = f"{depth}-claim"
            spec, declared = self._declare_and_start_scientific_job(
                writer=writer,
                executable_id=executable.identity,
                plan_hash=plan.sha256,
                depth=depth,
                claim_id=claim,
                tag=tag,
                verify_material_guard=(
                    verify_material_guard and ordinal == 1
                ),
            )
            completion = self._complete_scientific_job(
                writer=writer,
                spec=spec,
                declared=declared,
                executable_id=executable.identity,
                depth=depth,
                claim_id=claim,
                verdict="passed",
                tag=tag,
            )
            completions.append(completion)
            writer.judge_job_evidence(
                completion_record_id=completion.result["completion_record_id"],
                disposition=("continue_batch" if ordinal == 1 else "stop_batch"),
                operation_id=f"{tag}-judge",
            )
        writer.dispose_batch(
            outcome="completed", operation_id="holdout-life-batch-close"
        )
        with self.assertRaisesRegex(TransitionError, "validator completion"):
            writer.close_study(
                outcome="supported",
                operation_id="holdout-life-study-close-missing-kpi",
            )
        original_rebuild = writer.rebuild_study_kpi_projection

        def reject_routine_rebuild() -> bool:
            raise AssertionError("Study close rebuilt the KPI navigation projection")

        writer.rebuild_study_kpi_projection = reject_routine_rebuild  # type: ignore[method-assign]
        close_arguments = {
            "outcome": "supported",
            "operation_id": "holdout-life-study-close",
            "kpi_completion_record_id": completions[-1].result[
                "completion_record_id"
            ],
        }
        closed = writer.close_study(**close_arguments)
        self.assertFalse(closed.reused)
        reused_close = writer.close_study(**close_arguments)
        self.assertTrue(reused_close.reused)
        writer.rebuild_study_kpi_projection = original_rebuild  # type: ignore[method-assign]
        self.assertFalse((writer.root / "records" / "STUDY_KPI.md").exists())
        self.assertTrue(writer.rebuild_study_kpi_projection())
        kpi_ledger = (writer.root / "records" / "STUDY_KPI.md").read_text(
            encoding="ascii"
        )
        self.assertIn("| 000001 |", kpi_ledger)
        self.assertIn("STU-HOLDOUT-LIFECYCLE", kpi_ledger)
        self.assertIn("| supported |", kpi_ledger)
        with LocalIndex(writer.index_path) as index:
            kpi_record = index.get("study-kpi", "STU-HOLDOUT-LIFECYCLE")
        assert kpi_record is not None
        self.assertEqual(kpi_record.event_stream, "study-kpi")
        self.assertEqual(kpi_record.event_sequence, 1)
        self.assertEqual(
            kpi_record.payload["completion_record_id"],
            completions[-1].result["completion_record_id"],
        )
        self.assertFalse(writer.rebuild_study_kpi_projection())
        record_fixture_study_diagnosis(
            writer,
            study_id="STU-HOLDOUT-LIFECYCLE",
            evidence_state=EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION,
            operation_id="holdout-life-study-diagnosis",
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

    def test_unstarted_real_batch_closes_with_writer_derived_dash_kpi(self) -> None:
        with TemporaryDirectory() as temporary:
            writer = StateWriter(
                temporary,
                permit_authority=PermitAuthority(b"u" * 32),
                clock=lambda: FIXED_NOW,
                study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
                foundation_root=REPO_ROOT,
            )
            writer.initialize_ready()
            writer.open_mission(
                mission_id="MIS-UNSTARTED",
                goal=mission_goal("unstarted Batch closeout"),
                operation_id="unstarted-mission",
            )
            intake = record_fixture_research_intake(
                writer,
                mission_id="MIS-UNSTARTED",
                operation_id="unstarted-intake",
            )
            writer.open_initiative(
                initiative_id="INI-UNSTARTED",
                objective=initiative_objective("unstarted Batch closeout"),
                operation_id="unstarted-initiative",
            )
            axes = tuple(
                PortfolioAxis(
                    axis_id=f"unstarted-axis-{letter}",
                    causal_question=f"Does unstarted axis {letter} carry information?",
                    mechanism_family=f"unstarted-family-{letter}",
                )
                for letter in ("a", "b", "c")
            )
            snapshot = PortfolioSnapshot(
                mission_id="MIS-UNSTARTED",
                axes=axes,
                opportunity_cost_basis="retain independent unstarted axes",
                research_intake_id=intake.identity,
                exhaustion_standard=exhaustion_standard(),
            )
            writer.record_portfolio_snapshot(
                snapshot=snapshot,
                operation_id="unstarted-snapshot",
            )
            options = (
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
                    omission_reason="axis A receives the bounded commitment",
                ),
            )
            decision = PortfolioDecision(
                decision_id="DEC-UNSTARTED",
                chosen_option_id="choose-a",
                options=options,
                rationale="exercise a Writer-derived unavailable closeout",
                commitment_batches=2,
                baseline_executable=portfolio_axis_baseline(axes[0]),
                quant_team_review=quant_team_review_for_current_action(
                    writer,
                    options=options,
                    chosen_option_id="choose-a",
                ),
            )
            writer.record_portfolio_decision(
                decision=decision,
                operation_id="unstarted-decision",
            )
            question = study_question("unstarted Batch closeout")
            proposal = {"mechanism": "unstarted Batch closeout"}
            assert axes[0].architecture_chassis is not None
            controlled_chassis = ControlledStudyChassis(
                baseline_executable=decision.baseline_executable,
                changed_domains=axes[0].changed_domains,
                controlled_domains=axes[0].controlled_domains,
                architecture=axes[0].architecture_chassis,
            )
            study_hash = writer.study_input_hash(
                question=question,
                material_identity=OBSERVED_MATERIAL_ID,
                semantic_proposal=proposal,
                controlled_chassis=controlled_chassis,
                portfolio_axis_id=axes[0].axis_id,
                portfolio_axis_identity=axes[0].identity,
                portfolio_decision_id=decision.identity,
            )
            study_permit = writer.issue_permit(
                kind=PermitKind.STUDY,
                subject_kind=SubjectKind.INITIATIVE,
                subject_id="INI-UNSTARTED",
                input_hash=study_hash,
                actions=("open_study",),
                scope=(
                    "study",
                    f"decision:{decision.identity}",
                    f"axis:{axes[0].identity}",
                    f"baseline:{decision.baseline_executable.identity}",
                    f"chassis:{decision.architecture_chassis.identity}",
                    f"snapshot:{snapshot.identity}",
                ),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="unstarted-study-permit",
            )
            opened = writer.open_study(
                study_id="STU-UNSTARTED",
                question=question,
                material_identity=OBSERVED_MATERIAL_ID,
                material_display_name="foundation observed material",
                semantic_proposal=proposal,
                controlled_chassis=controlled_chassis,
                portfolio_axis_id=axes[0].axis_id,
                portfolio_axis_identity=axes[0].identity,
                portfolio_decision_id=decision.identity,
                permit=study_permit,
                operation_id="unstarted-study-open",
            )
            with self.assertRaisesRegex(TransitionError, "exact next action"):
                writer.close_study(
                    outcome="not_evaluable",
                    operation_id="unstarted-reject-no-batch",
                )
            batch = batch_spec(
                batch_id="BAT-UNSTARTED",
                study_id="STU-UNSTARTED",
                study_hash=opened.result["study_hash"],
            )
            batch_permit = writer.issue_permit(
                kind=PermitKind.BATCH,
                subject_kind=SubjectKind.STUDY,
                subject_id="STU-UNSTARTED",
                input_hash=batch.identity.removeprefix("batch:"),
                actions=("open_batch",),
                scope=("batch",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="unstarted-batch-permit",
            )
            writer.open_batch(
                batch_spec=batch,
                permit=batch_permit,
                operation_id="unstarted-batch-open",
            )
            with self.assertRaisesRegex(TransitionError, "unavailable disposition"):
                writer.dispose_batch(
                    outcome="completed",
                    operation_id="unstarted-reject-completed",
                )
            writer.dispose_batch(
                outcome="not_evaluable",
                operation_id="unstarted-batch-close",
            )
            control = writer.read_control()
            assert control is not None
            close_record_id = control["next_action"][
                "batch_close_record_id"
            ]
            continuation = StudyContinuationDecision(
                study_id="STU-UNSTARTED",
                study_hash=opened.result["study_hash"],
                question_hash=canonical_digest(
                    domain="study-question",
                    payload=question,
                ),
                controlled_chassis_identity=(
                    controlled_chassis.controlled_chassis_identity
                ),
                portfolio_snapshot_id=snapshot.identity,
                portfolio_axis_id=axes[0].axis_id,
                portfolio_axis_identity=axes[0].identity,
                portfolio_decision_id=decision.identity,
                prior_batch_id=batch.identity,
                prior_batch_close_record_id=close_record_id,
                member_executable_ids=(),
                member_job_ids=(),
                completion_record_ids=(),
                evidence_hashes=(),
                stop_rule=batch.stop_rule,
                stop_rule_state=StopRuleState.UNRESOLVED,
                remaining_uncertainty="no evidence was produced",
                expected_information_value="no justified continuation value",
                other_axis_ids=tuple(
                    sorted(axis.axis_id for axis in axes[1:])
                ),
                other_axis_opportunity_cost="preserve both untested axes",
                outcome=StudyContinuationOutcome.CLOSE,
                next_batch_id=None,
                quant_team_review=study_continuation_review(
                    snapshot_id=snapshot.identity,
                    batch_close_record_id=close_record_id,
                    completion_record_ids=(),
                ),
            )
            writer.review_study_continuation(
                decision=continuation,
                operation_id="unstarted-study-continuation-close",
            )
            closed = writer.close_study(
                outcome="not_evaluable",
                operation_id="unstarted-study-close",
            )
            self.assertEqual(closed.result["study_kpi_sequence"], 1)
            self.assertFalse(
                (writer.root / "records" / "STUDY_KPI.md").exists()
            )
            with LocalIndex(writer.index_path) as index:
                kpi_record = index.get("study-kpi", "STU-UNSTARTED")
            assert kpi_record is not None
            self.assertEqual(
                kpi_record.payload["source"],
                "writer_derived_unavailable",
            )
            self.assertEqual(
                kpi_record.payload["unavailable_reason"],
                "unstarted_batch_not_evaluable_without_final_validator_completion",
            )
            self.assertTrue(writer.rebuild_study_kpi_projection())
            ledger = (writer.root / "records" / "STUDY_KPI.md").read_text(
                encoding="ascii"
            )
            self.assertIn(
                "| 000001 | 2026-07-11 09:00 | STU-UNSTARTED | - | - | - | - | - | not_evaluable |",
                ledger,
            )
            self.assertFalse(writer.rebuild_study_kpi_projection())

            record_fixture_study_diagnosis(
                writer,
                study_id="STU-UNSTARTED",
                evidence_state=EvidenceState.NOT_IDENTIFIABLE,
                operation_id="unstarted-study-diagnosis",
            )

            budget_options = (
                DecisionOption(
                    option_id="choose-c",
                    action=PortfolioAction.ROTATE,
                    target_id=axes[2].axis_id,
                    expected_information_value="positive",
                    opportunity_cost="bounded",
                ),
                DecisionOption(
                    option_id="retain-b",
                    action=PortfolioAction.CONTRAST,
                    target_id=axes[1].axis_id,
                    expected_information_value="positive",
                    opportunity_cost="one Batch",
                    omission_reason="axis C receives the bounded commitment",
                ),
            )
            budget_decision = PortfolioDecision(
                decision_id="DEC-BUDGET-END",
                chosen_option_id="choose-c",
                options=budget_options,
                rationale="exercise an exhausted non-validator Job budget",
                commitment_batches=1,
                baseline_executable=portfolio_axis_baseline(axes[2]),
                quant_team_review=quant_team_review_for_current_action(
                    writer,
                    options=budget_options,
                    chosen_option_id="choose-c",
                ),
            )
            writer.record_portfolio_decision(
                decision=budget_decision,
                operation_id="budget-end-decision",
            )
            budget_question = study_question("exhausted non-validator Job budget")
            budget_proposal = {"mechanism": "budget exhaustion closeout"}
            assert axes[2].architecture_chassis is not None
            budget_controlled_chassis = ControlledStudyChassis(
                baseline_executable=budget_decision.baseline_executable,
                changed_domains=axes[2].changed_domains,
                controlled_domains=axes[2].controlled_domains,
                architecture=axes[2].architecture_chassis,
            )
            budget_study_hash = writer.study_input_hash(
                question=budget_question,
                material_identity=OBSERVED_MATERIAL_ID,
                semantic_proposal=budget_proposal,
                controlled_chassis=budget_controlled_chassis,
                portfolio_axis_id=axes[2].axis_id,
                portfolio_axis_identity=axes[2].identity,
                portfolio_decision_id=budget_decision.identity,
            )
            budget_study_permit = writer.issue_permit(
                kind=PermitKind.STUDY,
                subject_kind=SubjectKind.INITIATIVE,
                subject_id="INI-UNSTARTED",
                input_hash=budget_study_hash,
                actions=("open_study",),
                scope=(
                    "study",
                    f"decision:{budget_decision.identity}",
                    f"axis:{axes[2].identity}",
                    f"baseline:{budget_decision.baseline_executable.identity}",
                    f"chassis:{budget_decision.architecture_chassis.identity}",
                    f"snapshot:{snapshot.identity}",
                ),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="budget-end-study-permit",
            )
            budget_study = writer.open_study(
                study_id="STU-BUDGET-END",
                question=budget_question,
                material_identity=OBSERVED_MATERIAL_ID,
                material_display_name="foundation observed material",
                semantic_proposal=budget_proposal,
                controlled_chassis=budget_controlled_chassis,
                portfolio_axis_id=axes[2].axis_id,
                portfolio_axis_identity=axes[2].identity,
                portfolio_decision_id=budget_decision.identity,
                permit=budget_study_permit,
                operation_id="budget-end-study-open",
            )
            budget_batch = batch_spec(
                batch_id="BAT-BUDGET-END",
                study_id="STU-BUDGET-END",
                study_hash=budget_study.result["study_hash"],
                max_compute_seconds=30,
            )
            budget_batch_permit = writer.issue_permit(
                kind=PermitKind.BATCH,
                subject_kind=SubjectKind.STUDY,
                subject_id="STU-BUDGET-END",
                input_hash=budget_batch.identity.removeprefix("batch:"),
                actions=("open_batch",),
                scope=("batch",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="budget-end-batch-permit",
            )
            writer.open_batch(
                batch_spec=budget_batch,
                permit=budget_batch_permit,
                operation_id="budget-end-batch-open",
            )
            generic_spec = job_spec(
                writer,
                {"kind": "Study", "id": "STU-BUDGET-END"},
            )
            generic = writer.declare_job(
                spec=generic_spec,
                operation_id="budget-end-generic-declare",
            )
            generic_permit = writer.issue_permit(
                kind=PermitKind.JOB,
                subject_kind=SubjectKind.JOB,
                subject_id=generic.result["job_id"],
                input_hash=generic.result["job_hash"],
                actions=("start_job",),
                scope=("job",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="budget-end-generic-permit",
            )
            writer.start_job(
                permit=generic_permit,
                operation_id="budget-end-generic-start",
            )
            generic_output = (
                writer.root / "local" / "jobs" / "fixture" / "fixture.json"
            )
            generic_output.parent.mkdir(parents=True, exist_ok=True)
            generic_output.write_bytes(b"full budget generic output")
            generic_completion = writer.complete_job(
                outcome="success",
                output_manifest={
                    "local/jobs/fixture/fixture.json": sha256(
                        b"full budget generic output"
                    ).hexdigest()
                },
                operation_id="budget-end-generic-complete",
            )
            with self.assertRaisesRegex(TransitionError, "validator-derived"):
                writer.judge_job_evidence(
                    completion_record_id=generic_completion.result[
                        "completion_record_id"
                    ],
                    disposition="stop_batch",
                    operation_id="budget-end-reject-generic-stop",
                )
            writer.judge_job_evidence(
                completion_record_id=generic_completion.result[
                    "completion_record_id"
                ],
                disposition="continue_batch",
                operation_id="budget-end-continue-generic",
            )
            over_budget_spec = job_spec(
                writer,
                {"kind": "Study", "id": "STU-BUDGET-END"},
            )
            over_budget_spec["input_hashes"] = [
                *over_budget_spec["input_hashes"],
                digest("input", {"over_budget": True}),
            ]
            over_budget_spec["budget"] = {
                "compute_seconds": 1,
                "wall_seconds": 1,
                "trials": 1,
            }
            with self.assertRaisesRegex(TransitionError, "exceeds the frozen Batch"):
                writer.declare_job(
                    spec=over_budget_spec,
                    operation_id="budget-end-reject-next-job",
                )
            writer.dispose_batch(
                outcome="budget_exhausted",
                operation_id="budget-end-batch-close",
            )
            budget_closed = writer.close_study(
                outcome="evidence_gap",
                operation_id="budget-end-study-close",
            )
            self.assertEqual(budget_closed.result["study_kpi_sequence"], 2)
            self.assertEqual(
                (writer.root / "records" / "STUDY_KPI.md").read_text(
                    encoding="ascii"
                ),
                ledger,
            )
            with LocalIndex(writer.index_path) as index:
                budget_kpi = index.get("study-kpi", "STU-BUDGET-END")
            assert budget_kpi is not None
            self.assertEqual(
                budget_kpi.payload["unavailable_reason"],
                "started_batch_budget_exhausted_without_final_validator_completion",
            )
            self.assertTrue(writer.rebuild_study_kpi_projection())
            ledger = (writer.root / "records" / "STUDY_KPI.md").read_text(
                encoding="ascii"
            )
            self.assertIn(
                "| 000002 | 2026-07-11 09:00 | STU-BUDGET-END | - | - | - | - | - | evidence_gap |",
                ledger,
            )
            self.assertFalse(writer.rebuild_study_kpi_projection())
            record_fixture_study_diagnosis(
                writer,
                study_id="STU-BUDGET-END",
                evidence_state=EvidenceState.NOT_IDENTIFIABLE,
                operation_id="budget-end-study-diagnosis",
            )

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
        new_executable = scientific_executable_spec(
            "post-holdout",
            data_identity=material_identity,
            split_contract=f"split:{split_identity}",
        )
        options = (
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
        )
        decision = PortfolioDecision(
            decision_id="DEC-POST-HOLDOUT-DEVELOPMENT",
            chosen_option_id="develop-a",
            options=options,
            rationale="reenter the existing broad Portfolio on genuinely later material",
            commitment_batches=1,
            baseline_executable=new_executable,
            quant_team_review=quant_team_review_for_current_action(
                writer,
                options=options,
                chosen_option_id="develop-a",
            ),
        )
        writer.record_portfolio_decision(
            decision=decision,
            operation_id="failed-post-holdout-portfolio-decision",
        )
        question = study_question("post-holdout development material")
        proposal = {"mechanism": "post-holdout structural reentry"}
        post_holdout_architecture = architecture_chassis("fixture-baseline")
        self.assertEqual(
            post_holdout_architecture.identity,
            axes[0]["architecture_chassis_identity"],
        )
        controlled_chassis = ControlledStudyChassis(
            baseline_executable=decision.baseline_executable,
            changed_domains=tuple(
                ResearchLayer(value) for value in axes[0]["changed_domains"]
            ),
            controlled_domains=tuple(
                ResearchLayer(value) for value in axes[0]["controlled_domains"]
            ),
            architecture=post_holdout_architecture,
        )
        study_hash = writer.study_input_hash(
            question=question,
            material_identity=material_identity,
            semantic_proposal=proposal,
            controlled_chassis=controlled_chassis,
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
            scope=(
                "study",
                f"decision:{decision.identity}",
                f"axis:{axes[0]['axis_identity']}",
                f"baseline:{decision.baseline_executable.identity}",
                f"chassis:{decision.architecture_chassis.identity}",
                f"snapshot:{snapshot.record_id}",
            ),
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
            controlled_chassis=controlled_chassis,
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
        new_executable = changed_domain_executable(
            decision.baseline_executable,
            domain="calibration",
            change_tag="post-holdout-development",
        )
        counted = writer.register_trial(
            executable=new_executable,
            operation_id="failed-post-holdout-trial",
        )
        self.assertEqual(counted.result["trial_delta"], 1)
        completions = []
        for ordinal, depth in enumerate(("discovery", "confirmation"), start=1):
            tag = f"failed-post-holdout-{depth}"
            claim = f"post-holdout-{depth}-claim"
            spec, declared = self._declare_and_start_scientific_job(
                writer=writer,
                executable_id=new_executable.identity,
                plan_hash=plan_hash,
                depth=depth,
                claim_id=claim,
                tag=tag,
                material_identity=material_identity,
            )
            completion = self._complete_scientific_job(
                writer=writer,
                spec=spec,
                declared=declared,
                executable_id=new_executable.identity,
                depth=depth,
                claim_id=claim,
                verdict="passed",
                tag=tag,
            )
            completions.append(completion)
            writer.judge_job_evidence(
                completion_record_id=completion.result["completion_record_id"],
                disposition=("continue_batch" if ordinal == 1 else "stop_batch"),
                operation_id=f"{tag}-judge",
            )
        writer.dispose_batch(
            outcome="completed",
            operation_id="failed-post-holdout-batch-close",
        )
        writer.close_study(
            outcome="supported",
            operation_id="failed-post-holdout-study-close",
            kpi_completion_record_id=completions[-1].result[
                "completion_record_id"
            ],
        )
        record_fixture_study_diagnosis(
            writer,
            study_id="STU-POST-HOLDOUT-DEVELOPMENT",
            evidence_state=EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION,
            operation_id="failed-post-holdout-study-diagnosis",
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

    def test_typed_study_continuation_prebinds_exact_next_batch(self) -> None:
        with TemporaryDirectory() as root:
            validator = ScientificFixtureValidator()
            foundation_root = legacy_scientific_fixture_foundation(Path(root))
            writer = StateWriter(
                root,
                permit_authority=PermitAuthority(b"n" * 32),
                clock=lambda: FIXED_NOW,
                study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
                foundation_root=foundation_root,
                validation_registry=EvidenceValidatorRegistry((validator,)),
            )
            writer.initialize_ready()
            writer.open_mission(
                mission_id="MIS-HOLDOUT-LIFECYCLE",
                goal=mission_goal("typed Study continuation"),
                operation_id="continuation-mission",
            )
            intake = record_fixture_research_intake(
                writer,
                mission_id="MIS-HOLDOUT-LIFECYCLE",
                operation_id="continuation-intake",
            )
            writer.open_initiative(
                initiative_id="INI-CONTINUATION",
                objective=initiative_objective("typed Study continuation"),
                operation_id="continuation-initiative",
            )
            axes = tuple(
                PortfolioAxis(
                    axis_id=f"continuation-axis-{letter}",
                    causal_question=(
                        f"Does continuation axis {letter} carry information?"
                    ),
                    mechanism_family=f"continuation-family-{letter}",
                )
                for letter in ("a", "b", "c")
            )
            snapshot = PortfolioSnapshot(
                mission_id="MIS-HOLDOUT-LIFECYCLE",
                axes=axes,
                opportunity_cost_basis="retain two alternative continuation axes",
                research_intake_id=intake.identity,
                exhaustion_standard=exhaustion_standard(),
            )
            writer.record_portfolio_snapshot(
                snapshot=snapshot,
                operation_id="continuation-snapshot",
            )
            options = (
                DecisionOption(
                    option_id="choose-a",
                    action=PortfolioAction.DEEPEN,
                    target_id=axes[0].axis_id,
                    expected_information_value="positive",
                    opportunity_cost="three bounded Batches",
                ),
                DecisionOption(
                    option_id="retain-b",
                    action=PortfolioAction.CONTRAST,
                    target_id=axes[1].axis_id,
                    expected_information_value="positive",
                    opportunity_cost="deferred",
                    omission_reason="axis A has the current bounded priority",
                ),
            )
            portfolio_decision = PortfolioDecision(
                decision_id="DEC-CONTINUATION",
                chosen_option_id="choose-a",
                options=options,
                rationale="permit evidence-bound continuation without causal drift",
                commitment_batches=3,
                baseline_executable=portfolio_axis_baseline(axes[0]),
                quant_team_review=quant_team_review_for_current_action(
                    writer,
                    options=options,
                    chosen_option_id="choose-a",
                ),
            )
            writer.record_portfolio_decision(
                decision=portfolio_decision,
                operation_id="continuation-portfolio-decision",
            )
            question = study_question("typed Study continuation")
            proposal = {"mechanism": "evidence-bound continuation"}
            assert axes[0].architecture_chassis is not None
            controlled_chassis = ControlledStudyChassis(
                baseline_executable=portfolio_decision.baseline_executable,
                changed_domains=axes[0].changed_domains,
                controlled_domains=axes[0].controlled_domains,
                architecture=axes[0].architecture_chassis,
            )
            study_hash = writer.study_input_hash(
                question=question,
                material_identity=OBSERVED_MATERIAL_ID,
                semantic_proposal=proposal,
                controlled_chassis=controlled_chassis,
                portfolio_axis_id=axes[0].axis_id,
                portfolio_axis_identity=axes[0].identity,
                portfolio_decision_id=portfolio_decision.identity,
            )
            study_permit = writer.issue_permit(
                kind=PermitKind.STUDY,
                subject_kind=SubjectKind.INITIATIVE,
                subject_id="INI-CONTINUATION",
                input_hash=study_hash,
                actions=("open_study",),
                scope=(
                    "study",
                    f"decision:{portfolio_decision.identity}",
                    f"axis:{axes[0].identity}",
                    f"baseline:{portfolio_decision.baseline_executable.identity}",
                    f"chassis:{portfolio_decision.architecture_chassis.identity}",
                    f"snapshot:{snapshot.identity}",
                ),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="continuation-study-permit",
            )
            opened = writer.open_study(
                study_id="STU-CONTINUATION",
                question=question,
                material_identity=OBSERVED_MATERIAL_ID,
                material_display_name="foundation observed material",
                semantic_proposal=proposal,
                controlled_chassis=controlled_chassis,
                portfolio_axis_id=axes[0].axis_id,
                portfolio_axis_identity=axes[0].identity,
                portfolio_decision_id=portfolio_decision.identity,
                permit=study_permit,
                operation_id="continuation-study-open",
            )
            first_batch = batch_spec(
                batch_id="BAT-CONTINUATION-1",
                study_id="STU-CONTINUATION",
                study_hash=opened.result["study_hash"],
                max_compute_seconds=90,
            )
            first_permit = writer.issue_permit(
                kind=PermitKind.BATCH,
                subject_kind=SubjectKind.STUDY,
                subject_id="STU-CONTINUATION",
                input_hash=first_batch.identity.removeprefix("batch:"),
                actions=("open_batch",),
                scope=("batch",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="continuation-first-batch-permit",
            )
            writer.open_batch(
                batch_spec=first_batch,
                permit=first_permit,
                operation_id="continuation-first-batch-open",
            )
            plan = writer.evidence.finalize(
                canonical_bytes({"schema": "scientific_boundary_plan.v1"})
            )

            def execute_member(
                *, tag: str, change_tag: str, disposition: str
            ) -> object:
                assert portfolio_decision.baseline_executable is not None
                executable = changed_domain_executable(
                    portfolio_decision.baseline_executable,
                    domain="calibration",
                    change_tag=change_tag,
                )
                writer.register_trial(
                    executable=executable,
                    operation_id=f"{tag}-trial",
                )
                spec, declared = self._declare_and_start_scientific_job(
                    writer=writer,
                    executable_id=executable.identity,
                    plan_hash=plan.sha256,
                    depth="discovery",
                    claim_id=f"{tag}-claim",
                    tag=tag,
                )
                completion = self._complete_scientific_job(
                    writer=writer,
                    spec=spec,
                    declared=declared,
                    executable_id=executable.identity,
                    depth="discovery",
                    claim_id=f"{tag}-claim",
                    verdict="passed",
                    tag=tag,
                )
                writer.judge_job_evidence(
                    completion_record_id=completion.result[
                        "completion_record_id"
                    ],
                    disposition=disposition,
                    operation_id=f"{tag}-judge",
                )
                return completion

            execute_member(
                tag="continuation-first",
                change_tag="continuation-first",
                disposition="continue_batch",
            )
            writer.dispose_batch(
                outcome="stopped_early",
                operation_id="continuation-first-close",
            )
            second_batch = batch_spec(
                batch_id="BAT-CONTINUATION-2",
                study_id="STU-CONTINUATION",
                study_hash=opened.result["study_hash"],
                max_compute_seconds=90,
                max_trials=19,
            )

            def continuation_for(
                *,
                batch: BatchSpec,
                next_batch: BatchSpec | None,
                stop_rule_state: StopRuleState,
                outcome: StudyContinuationOutcome,
                other_axis_ids: tuple[str, ...] | None = None,
                evidence_hashes: tuple[str, ...] | None = None,
            ) -> StudyContinuationDecision:
                control = writer.read_control()
                assert control is not None
                close_id = control["next_action"]["batch_close_record_id"]
                with LocalIndex(writer.index_path) as index:
                    bindings = writer._batch_continuation_bindings(
                        index, batch.identity
                    )
                    study_record = index.get(
                        "study-open", "STU-CONTINUATION"
                    )
                assert study_record is not None
                completions = bindings["completion_record_ids"]
                return StudyContinuationDecision(
                    study_id="STU-CONTINUATION",
                    study_hash=opened.result["study_hash"],
                    question_hash=study_record.payload["question_hash"],
                    controlled_chassis_identity=(
                        controlled_chassis.controlled_chassis_identity
                    ),
                    portfolio_snapshot_id=snapshot.identity,
                    portfolio_axis_id=axes[0].axis_id,
                    portfolio_axis_identity=axes[0].identity,
                    portfolio_decision_id=portfolio_decision.identity,
                    prior_batch_id=batch.identity,
                    prior_batch_close_record_id=close_id,
                    member_executable_ids=bindings[
                        "member_executable_ids"
                    ],
                    member_job_ids=bindings["member_job_ids"],
                    completion_record_ids=completions,
                    evidence_hashes=(
                        bindings["evidence_hashes"]
                        if evidence_hashes is None
                        else evidence_hashes
                    ),
                    stop_rule=batch.stop_rule,
                    stop_rule_state=stop_rule_state,
                    remaining_uncertainty="the unchanged question remains unresolved",
                    expected_information_value="one bounded Batch can resolve it",
                    other_axis_ids=(
                        tuple(sorted(axis.axis_id for axis in axes[1:]))
                        if other_axis_ids is None
                        else other_axis_ids
                    ),
                    other_axis_opportunity_cost="defer but preserve both alternatives",
                    outcome=outcome,
                    next_batch_id=(
                        None if next_batch is None else next_batch.identity
                    ),
                    quant_team_review=study_continuation_review(
                        snapshot_id=snapshot.identity,
                        batch_close_record_id=close_id,
                        completion_record_ids=completions,
                    ),
                )

            with self.assertRaisesRegex(
                StudyContinuationError, "evidence-bearing"
            ):
                continuation_for(
                    batch=first_batch,
                    next_batch=second_batch,
                    stop_rule_state=StopRuleState.NOT_REACHED,
                    outcome=StudyContinuationOutcome.CONTINUE,
                    evidence_hashes=(),
                )
            drifted_forest = continuation_for(
                batch=first_batch,
                next_batch=second_batch,
                stop_rule_state=StopRuleState.NOT_REACHED,
                outcome=StudyContinuationOutcome.CONTINUE,
                other_axis_ids=(axes[1].axis_id,),
            )
            with self.assertRaisesRegex(TransitionError, "Portfolio forest"):
                writer.review_study_continuation(
                    decision=drifted_forest,
                    operation_id="reject-drifted-continuation-forest",
                )
            continuation = continuation_for(
                batch=first_batch,
                next_batch=second_batch,
                stop_rule_state=StopRuleState.NOT_REACHED,
                outcome=StudyContinuationOutcome.CONTINUE,
            )
            writer.review_study_continuation(
                decision=continuation,
                operation_id="continuation-first-review",
            )
            wrong_batch = batch_spec(
                batch_id="BAT-CONTINUATION-WRONG",
                study_id="STU-CONTINUATION",
                study_hash=opened.result["study_hash"],
                max_trials=18,
            )
            wrong_permit = writer.issue_permit(
                kind=PermitKind.BATCH,
                subject_kind=SubjectKind.STUDY,
                subject_id="STU-CONTINUATION",
                input_hash=wrong_batch.identity.removeprefix("batch:"),
                actions=("open_batch",),
                scope=("batch",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="continuation-wrong-batch-permit",
            )
            with self.assertRaisesRegex(TransitionError, "exact continuation"):
                writer.open_batch(
                    batch_spec=wrong_batch,
                    permit=wrong_permit,
                    operation_id="reject-unbound-continuation-batch",
                )
            second_permit = writer.issue_permit(
                kind=PermitKind.BATCH,
                subject_kind=SubjectKind.STUDY,
                subject_id="STU-CONTINUATION",
                input_hash=second_batch.identity.removeprefix("batch:"),
                actions=("open_batch",),
                scope=("batch",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="continuation-second-batch-permit",
            )
            writer.open_batch(
                batch_spec=second_batch,
                permit=second_permit,
                operation_id="continuation-second-batch-open",
            )
            execute_member(
                tag="continuation-second",
                change_tag="continuation-second",
                disposition="stop_batch",
            )
            writer.dispose_batch(
                outcome="completed",
                operation_id="continuation-second-close",
            )
            forged_not_reached = continuation_for(
                batch=second_batch,
                next_batch=batch_spec(
                    batch_id="BAT-CONTINUATION-3",
                    study_id="STU-CONTINUATION",
                    study_hash=opened.result["study_hash"],
                    max_trials=17,
                ),
                stop_rule_state=StopRuleState.NOT_REACHED,
                outcome=StudyContinuationOutcome.CONTINUE,
            )
            with self.assertRaisesRegex(
                TransitionError, "stop-rule state differs"
            ):
                writer.review_study_continuation(
                    decision=forged_not_reached,
                    operation_id="reject-forged-not-reached",
                )
            close_decision = continuation_for(
                batch=second_batch,
                next_batch=None,
                stop_rule_state=StopRuleState.REACHED,
                outcome=StudyContinuationOutcome.CLOSE,
            )
            writer.review_study_continuation(
                decision=close_decision,
                operation_id="continuation-second-review-close",
            )
            self.assertEqual(
                writer.read_control()["next_action"],
                {"kind": "judge_study", "study_id": "STU-CONTINUATION"},
            )

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
                if verdict == "passed":
                    with self.assertRaisesRegex(
                        TransitionError,
                        "before its exact reveal",
                    ):
                        self._complete_scientific_job(
                            writer=writer,
                            spec=spec,
                            declared=declared,
                            executable_id=executable.identity,
                            depth="confirmation",
                            claim_id=claim,
                            verdict=verdict,
                            tag=tag,
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

    def test_scientific_job_requires_its_observed_lineage_material_input(self) -> None:
        with TemporaryDirectory() as root:
            self._build_frozen_candidate(
                root,
                verify_material_guard=True,
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

    def test_revealed_holdout_engineering_gap_disposes_without_scientific_loss(
        self,
    ) -> None:
        with TemporaryDirectory() as root:
            writer, executable, candidate, plan = self._build_frozen_candidate(root)
            content = b"sealed holdout values for engineering gap"
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
                manifest=sealed,
                operation_id="engineering-gap-holdout-seal",
            )
            spec, declared = self._declare_and_start_scientific_job(
                writer=writer,
                executable_id=executable.identity,
                plan_hash=plan.sha256,
                depth="confirmation",
                claim_id="engineering-gap-holdout-claim",
                tag="engineering-gap-holdout",
                holdout_id=sealed.identity,
                evidence_modes=(
                    "causal_contrast",
                    "cost_and_execution",
                    "sensitivity_or_stress",
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
                operation_id="engineering-gap-holdout-reveal-permit",
            )
            self.assertEqual(
                writer.reveal_holdout_values(
                    permit=holdout_permit,
                    executable_id=executable.identity,
                    operation_id="engineering-gap-holdout-values-reveal",
                ),
                content,
            )
            reproduction = writer.evidence.finalize(
                b"holdout evaluator engineering failure reproduction"
            )
            cause = {
                "failure_kind": "engineering",
                "minimum_reproduction_evidence": [reproduction.sha256],
                "root_cause": "holdout evaluator could not parse its sealed input",
                "interrupted_action": spec["callable_identity"],
            }
            cause_hash = canonical_digest(domain="repair-cause", payload=cause)
            disposition_hash = engineering_failure_disposition(
                writer,
                job_id=declared.result["job_id"],
                evidence_hashes=(reproduction.sha256,),
                cause_hash=cause_hash,
            )
            writer.record_engineering_failure_disposition(
                failure=cause,
                disposition_hash=disposition_hash,
                operation_id="engineering-gap-holdout-disposition",
            )
            completed = writer.complete_job(
                outcome="failed",
                output_manifest={},
                failure={
                    **cause,
                    "repair_disposition_hash": disposition_hash,
                    "resume_action": spec["resume_action"],
                },
                operation_id="engineering-gap-holdout-complete",
            )
            completion_id = completed.result["completion_record_id"]
            self.assertEqual(
                writer.read_control()["next_action"],  # type: ignore[index]
                {
                    "completion_record_id": completion_id,
                    "holdout_id": sealed.identity,
                    "job_id": declared.result["job_id"],
                    "kind": "dispose_revealed_holdout_engineering_gap",
                },
            )
            disposed = writer.dispose_revealed_holdout_engineering_gap(
                completion_record_id=completion_id,
                operation_id="engineering-gap-holdout-terminal",
            )
            self.assertEqual(disposed.result["verdict"], "engineering_gap")
            control = writer.read_control()
            assert control is not None
            self.assertIsNone(
                control["scientific"]["active_holdout_evaluation"]
            )
            self.assertIsNone(control["scientific"]["active_executable"])
            self.assertEqual(
                control["next_action"],
                {
                    "kind": "await_new_future_holdout_data",
                    "predecessor_holdout_id": sealed.identity,
                },
            )
            with LocalIndex(writer.index_path) as index:
                holdout_disposition = index.event_record(
                    f"holdout-reveal:{sealed.identity}", 2
                )
                candidate_holdout = index.get(
                    "candidate-holdout", candidate.result["candidate_id"]
                )
                candidate_head = index.event_head(
                    f"candidate:{executable.identity}"
                )
                candidate_disposition = (
                    None
                    if candidate_head is None
                    else index.get(
                        candidate_head.record_kind,
                        candidate_head.record_id,
                    )
                )
                negative_memories = index.records_by_kind("negative-memory")
            assert holdout_disposition is not None
            assert candidate_holdout is not None
            assert candidate_disposition is not None
            self.assertEqual(holdout_disposition.status, "engineering_gap")
            self.assertEqual(candidate_holdout.status, "engineering_gap")
            self.assertEqual(candidate_disposition.status, "invalidated")
            self.assertEqual(
                candidate_disposition.payload["reason"],
                "final_holdout_engineering_gap",
            )
            self.assertFalse(negative_memories)

    def test_pre_reveal_holdout_scientific_change_invalidates_only_the_candidate(
        self,
    ) -> None:
        with TemporaryDirectory() as root:
            writer, executable, candidate, plan = self._build_frozen_candidate(
                root
            )
            sealed = self._seal_candidate_holdout(
                writer,
                tag="pre-reveal-scientific-change",
            )
            spec, declared = self._declare_and_start_scientific_job(
                writer=writer,
                executable_id=executable.identity,
                plan_hash=plan.sha256,
                depth="confirmation",
                claim_id="pre-reveal-scientific-change-claim",
                tag="pre-reveal-scientific-change",
                holdout_id=sealed.identity,
            )
            reproduction = writer.evidence.finalize(
                b"pre-reveal evaluator requires a scientific change"
            )
            cause = {
                "failure_kind": "engineering",
                "minimum_reproduction_evidence": [reproduction.sha256],
                "root_cause": "evaluator repair would change registered semantics",
                "interrupted_action": spec["callable_identity"],
            }
            cause_hash = canonical_digest(domain="repair-cause", payload=cause)
            disposition_hash = engineering_failure_disposition(
                writer,
                job_id=declared.result["job_id"],
                evidence_hashes=(reproduction.sha256,),
                cause_hash=cause_hash,
            )
            writer.record_engineering_failure_disposition(
                failure=cause,
                disposition_hash=disposition_hash,
                operation_id="pre-reveal-scientific-change-disposition",
            )
            completed = writer.complete_job(
                outcome="failed",
                output_manifest={},
                failure={
                    **cause,
                    "repair_disposition_hash": disposition_hash,
                    "resume_action": spec["resume_action"],
                },
                operation_id="pre-reveal-scientific-change-complete",
            )
            action = writer.read_control()["next_action"]  # type: ignore[index]
            self.assertEqual(action["kind"], "resolve_candidate_engineering_gap")
            self.assertEqual(action["work_context"], "pre_reveal_holdout")
            self.assertEqual(action["target_id"], sealed.identity)
            self.assertEqual(action["successor_scope"], "study")
            self.assertEqual(
                action["completion_record_id"],
                completed.result["completion_record_id"],
            )
            control = writer.read_control()
            assert control is not None
            self.assertEqual(control["scientific"]["holdout_reveals"], 0)
            self.assertIsNone(
                control["scientific"]["active_holdout_evaluation"]
            )
            with self.assertRaises(TransitionError):
                writer.declare_job(
                    spec=spec,
                    operation_id="reject-old-pre-reveal-retry-after-scientific-change",
                )
            with self.assertRaisesRegex(TransitionError, "must invalidate"):
                writer.dispose_candidate(
                    disposition="returned_to_library",
                    reason="keep an invalid frozen identity",
                    operation_id="reject-pre-reveal-noninvalidation",
                )
            disposed = writer.dispose_candidate(
                disposition="invalidated",
                reason="engineering_requires_scientific_change",
                operation_id="invalidate-pre-reveal-candidate",
            )
            self.assertEqual(
                disposed.result["executable_id"], executable.identity
            )
            with LocalIndex(writer.index_path) as index:
                gap = index.records_by_kind(
                    "holdout-evaluation-operational-gap"
                )
                candidate_head = index.event_head(
                    f"candidate:{executable.identity}"
                )
                negative_memories = index.records_by_kind("negative-memory")
            self.assertEqual(len(gap), 1)
            self.assertTrue(gap[0].payload["sealed_holdout_preserved"])
            self.assertEqual(gap[0].payload["scientific_trial_delta"], 0)
            self.assertIsNotNone(candidate_head)
            assert candidate_head is not None
            self.assertNotEqual(candidate_head.record_id, candidate.result["candidate_id"])
            self.assertFalse(negative_memories)

    def test_pre_entry_runtime_engineering_gap_allows_only_same_depth_repair(
        self,
    ) -> None:
        with TemporaryDirectory() as root:
            writer, executable, candidate, _plan = self._build_frozen_candidate(
                root
            )
            writer.validation_registry = EvidenceValidatorRegistry(
                (
                    EngineeringRetryBoundaryFixtureValidator(),
                    ScientificFixtureValidator(),
                    RuntimeBoundaryFixtureValidator(),
                )
            )
            spec = runtime_job_spec(
                writer=writer,
                executable_id=executable.identity,
                depth=EvidenceDepth.EXECUTION_PROOF,
                output_name="evidence/pre-entry-runtime-gap",
                artifact_roles=("native_execution_report", "parity_report"),
                validation_plan_hash=RUNTIME_BOUNDARY_PLAN_HASH,
                validator_id=RuntimeBoundaryFixtureValidator.validator_id,
            )
            declared = writer.declare_job(
                spec=spec,
                operation_id="pre-entry-runtime-gap-declare",
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
                operation_id="pre-entry-runtime-gap-job-permit",
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
                operation_id="pre-entry-runtime-gap-runtime-permit",
            )
            writer.start_job(
                permit=job_permit,
                runtime_permit=runtime_permit,
                operation_id="pre-entry-runtime-gap-start",
            )
            reproduction = writer.evidence.finalize(
                b"runtime adapter failed before engine entry"
            )
            cause = {
                "failure_kind": "engineering",
                "minimum_reproduction_evidence": [reproduction.sha256],
                "root_cause": "runtime adapter initialization failed",
                "interrupted_action": spec["callable_identity"],
            }
            cause_hash = canonical_digest(domain="repair-cause", payload=cause)
            disposition_hash = engineering_failure_disposition(
                writer,
                job_id=declared.result["job_id"],
                evidence_hashes=(reproduction.sha256,),
                disposition="repair_infeasible",
                cause_hash=cause_hash,
            )
            writer.record_engineering_failure_disposition(
                failure=cause,
                disposition_hash=disposition_hash,
                operation_id="pre-entry-runtime-gap-disposition",
            )
            completed = writer.complete_job(
                outcome="failed",
                output_manifest={},
                failure={
                    **cause,
                    "repair_disposition_hash": disposition_hash,
                    "resume_action": spec["resume_action"],
                },
                operation_id="pre-entry-runtime-gap-complete",
            )
            action = writer.read_control()["next_action"]  # type: ignore[index]
            self.assertEqual(
                action,
                {
                    "completion_record_id": completed.result[
                        "completion_record_id"
                    ],
                    "disposition": "repair_infeasible",
                    "executable_id": executable.identity,
                    "job_id": declared.result["job_id"],
                    "kind": "resolve_candidate_engineering_gap",
                    "resume_condition": "admit a new exact scientific work identity",
                    "successor_scope": None,
                    "target_id": "execution_proof",
                    "work_context": "runtime",
                },
            )
            materialization_spec = runtime_job_spec(
                writer=writer,
                executable_id=executable.identity,
                depth=EvidenceDepth.MATERIALIZATION,
                output_name="evidence/reject-pre-entry-depth-skip",
                artifact_roles=("materialization_report",),
                validation_plan_hash=RUNTIME_BOUNDARY_PLAN_HASH,
                validator_id=RuntimeBoundaryFixtureValidator.validator_id,
            )
            with self.assertRaises(TransitionError):
                writer.declare_job(
                    spec=materialization_spec,
                    operation_id="reject-pre-entry-depth-skip",
                )
            repair_basis = writer.evidence.finalize(
                b"bounded runtime adapter repair basis"
            )
            input_bypass_spec = dict(spec)
            input_bypass_spec["input_hashes"] = [
                *spec["input_hashes"],
                repair_basis.sha256,
            ]
            with self.assertRaises(IdenticalFailedRetryError):
                writer.declare_job(
                    spec=input_bypass_spec,
                    operation_id="reject-pre-entry-input-bypass",
                )
            completion_record_id = completed.result["completion_record_id"]
            with LocalIndex(writer.index_path) as index:
                completion = index.get(
                    "job-completed",
                    completion_record_id,
                )
                declaration = index.get(
                    "job-declared",
                    declared.result["job_id"],
                )
                assert completion is not None and declaration is not None
            failure = completion.payload["failure"]
            disposition = completion.payload["engineering_disposition"]
            retry_validation_binding = {
                "authority_kind": "same_implementation_retry",
                "changed_dimension": "cause",
                "engineering_disposition_hash": failure[
                    "repair_disposition_hash"
                ],
                "failure_signature": failure["failure_signature"],
                "new_basis_hash": repair_basis.sha256,
                "new_work_fingerprint": declaration.payload[
                    "work_fingerprint"
                ],
                "previous_basis_hash": disposition["basis_manifest_hash"],
                "prior_completion_record_id": completion.record_id,
                "prior_job_hash": declaration.fingerprint,
                "prior_job_id": declaration.record_id,
                "prior_work_fingerprint": declaration.payload[
                    "work_fingerprint"
                ],
                "resume_condition": disposition["resume_condition"],
                "retry_family_fingerprint": declaration.payload[
                    "retry_family_fingerprint"
                ],
                "schema": "engineering_retry_validation_binding.v1",
                "scientific_semantics_changed": False,
            }
            check_plan_hash, check_result_hashes = (
                engineering_retry_validation_artifacts(
                    writer,
                    binding=retry_validation_binding,
                    validator_id=(
                        EngineeringRetryBoundaryFixtureValidator.validator_id
                    ),
                )
            )
            verification = writer.evidence.finalize(
                canonical_bytes(
                    {
                        "changed_dimension": "cause",
                        "check_plan_hash": check_plan_hash,
                        "engineering_disposition_hash": failure[
                            "repair_disposition_hash"
                        ],
                        "failure_signature": failure["failure_signature"],
                        "new_basis_hash": repair_basis.sha256,
                        "new_work_fingerprint": declaration.payload[
                            "work_fingerprint"
                        ],
                        "prior_completion_record_id": completion.record_id,
                        "prior_job_hash": declaration.fingerprint,
                        "prior_job_id": declaration.record_id,
                        "result_artifact_hashes": check_result_hashes,
                        "resume_condition": disposition["resume_condition"],
                        "retry_family_fingerprint": declaration.payload[
                            "retry_family_fingerprint"
                        ],
                        "schema": "job_retry_resume_verification.v1",
                        "scientific_semantics_changed": False,
                        "validator_id": (
                            EngineeringRetryBoundaryFixtureValidator.validator_id
                        ),
                        "verdict": "passed",
                        "verification_method": "independent fixture rerun",
                    }
                )
            )
            authority = writer.evidence.finalize(
                canonical_bytes(
                    {
                        "changed_dimension": "cause",
                        "engineering_disposition_hash": failure[
                            "repair_disposition_hash"
                        ],
                        "failure_signature": failure["failure_signature"],
                        "new_basis_hash": repair_basis.sha256,
                        "new_evidence_hashes": [repair_basis.sha256],
                        "new_work_fingerprint": declaration.payload[
                            "work_fingerprint"
                        ],
                        "previous_basis_hash": disposition[
                            "basis_manifest_hash"
                        ],
                        "prior_completion_record_id": completion.record_id,
                        "prior_job_hash": declaration.fingerprint,
                        "prior_job_id": declaration.record_id,
                        "prior_work_fingerprint": declaration.payload[
                            "work_fingerprint"
                        ],
                        "resume_condition": disposition["resume_condition"],
                        "retry_family_fingerprint": declaration.payload[
                            "retry_family_fingerprint"
                        ],
                        "schema": "job_retry_resume_authority.v1",
                        "scientific_semantics_changed": False,
                        "verification_receipt_hashes": [verification.sha256],
                    }
                )
            )
            retry_spec = dict(spec)
            retry_spec["changed_cause_proof_hash"] = authority.sha256
            retry = writer.declare_job(
                spec=retry_spec,
                operation_id="pre-entry-same-depth-retry",
            )
            self.assertNotEqual(retry.result["job_id"], declared.result["job_id"])
            self.assertEqual(
                writer.read_control()["next_action"],  # type: ignore[index]
                {
                    "job_id": retry.result["job_id"],
                    "kind": "issue_job_permit",
                },
            )

    def test_real_runtime_completion_reopens_the_second_release_depth(self) -> None:
        with TemporaryDirectory() as root:
            writer, executable, candidate, _plan = self._build_frozen_candidate(
                root
            )
            writer.validation_registry = EvidenceValidatorRegistry(
                (
                    ScientificFixtureValidator(),
                    RuntimeBoundaryFixtureValidator(),
                )
            )
            executable_id = executable.identity
            candidate_id = candidate.result["candidate_id"]
            output_name = "evidence/real-execution-proof"
            spec = runtime_job_spec(
                writer=writer,
                executable_id=executable_id,
                depth=EvidenceDepth.EXECUTION_PROOF,
                output_name=output_name,
                artifact_roles=(
                    "native_execution_report",
                    "parity_report",
                ),
                validation_plan_hash=RUNTIME_BOUNDARY_PLAN_HASH,
                validator_id=RuntimeBoundaryFixtureValidator.validator_id,
            )
            declared = writer.declare_job(
                spec=spec,
                operation_id="real-runtime-execution-declare",
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
                operation_id="real-runtime-execution-job-permit",
            )
            runtime_permit = writer.issue_permit(
                kind=PermitKind.RUNTIME,
                subject_kind=SubjectKind.EXECUTABLE,
                subject_id=executable_id,
                input_hash=declared.result["job_hash"],
                actions=("run_execution_proof",),
                scope=(
                    f"candidate:{candidate_id}",
                    "depth:execution_proof",
                    f"executable:{executable_id}",
                    f"job:{declared.result['job_id']}",
                ),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=False,
                operation_id="real-runtime-execution-runtime-permit",
            )
            writer.start_job(
                permit=job_permit,
                runtime_permit=runtime_permit,
                operation_id="real-runtime-execution-start",
            )
            writer.validate_runtime_entry(
                permit=runtime_permit,
                executable_id=executable_id,
                input_hash=declared.result["job_hash"],
                action="run_execution_proof",
                depth=EvidenceDepth.EXECUTION_PROOF,
                operation_id="real-runtime-execution-entry",
            )
            binding = spec["runtime_binding"]
            assert isinstance(binding, dict)
            measurement = writer.evidence.finalize(
                canonical_bytes(
                    {
                        "claims": sorted(REQUIRED_PARITY),
                        "schema": "engineering_runtime_measurement.v1",
                    }
                )
            )
            outputs = {
                f"{output_name}-measurement": measurement.sha256,
            }
            execution_role_hashes: dict[str, str] = {}
            for role, output in binding["artifact_roles"].items():
                artifact = writer.evidence.finalize(
                    canonical_bytes(
                        {
                            "role": role,
                            "schema": "engineering_runtime_role.v1",
                        }
                    )
                )
                outputs[output] = artifact.sha256
                execution_role_hashes[role] = artifact.sha256
            result = writer.evidence.finalize(
                canonical_bytes(
                    {
                        "action": "run_execution_proof",
                        "candidate_id": candidate_id,
                        "evidence_depth": "execution_proof",
                        "executable_id": executable_id,
                        "job_hash": declared.result["job_hash"],
                        "job_id": declared.result["job_id"],
                        "mission_id": "MIS-HOLDOUT-LIFECYCLE",
                        "observations": [
                            {
                                "claim_id": claim,
                                "measurement_artifact_hash": measurement.sha256,
                                "status": "caller_reported",
                            }
                            for claim in sorted(REQUIRED_PARITY)
                        ],
                        "runtime_permit_id": runtime_permit.permit_id,
                        "schema": "runtime_job_evidence.v1",
                    }
                )
            )
            outputs[binding["result_manifest_output"]] = result.sha256
            completed = writer.complete_job(
                outcome="success",
                output_manifest=outputs,
                operation_id="real-runtime-execution-complete",
            )
            self.assertEqual(
                writer.read_control()["next_action"],  # type: ignore[index]
                {
                    "executable_id": executable_id,
                    "kind": "plan_candidate_bound_evidence",
                },
            )
            materialization = runtime_job_spec(
                writer=writer,
                executable_id=executable_id,
                depth=EvidenceDepth.MATERIALIZATION,
                output_name="evidence/real-materialization",
                artifact_roles=tuple(
                    sorted(
                        REQUIRED_RELEASE_ARTIFACT_ROLES
                        - set(execution_role_hashes)
                    )
                ),
                validation_plan_hash=RUNTIME_BOUNDARY_PLAN_HASH,
                validator_id=RuntimeBoundaryFixtureValidator.validator_id,
            )
            second = writer.declare_job(
                spec=materialization,
                operation_id="real-runtime-materialization-declare",
            )
            self.assertNotEqual(
                second.result["job_id"],
                declared.result["job_id"],
            )
            with LocalIndex(writer.index_path) as index:
                first_completion = index.get(
                    "job-completed",
                    completed.result["completion_record_id"],
                )
                second_declaration = index.get(
                    "job-declared",
                    second.result["job_id"],
                )
            assert first_completion is not None
            assert second_declaration is not None
            self.assertEqual(
                first_completion.payload["candidate_execution_context"],
                second_declaration.payload["candidate_execution_context"],
            )
            materialization_job_permit = writer.issue_permit(
                kind=PermitKind.JOB,
                subject_kind=SubjectKind.JOB,
                subject_id=second.result["job_id"],
                input_hash=second.result["job_hash"],
                actions=("start_job",),
                scope=("job",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="real-runtime-materialization-job-permit",
            )
            materialization_runtime_permit = writer.issue_permit(
                kind=PermitKind.RUNTIME,
                subject_kind=SubjectKind.EXECUTABLE,
                subject_id=executable_id,
                input_hash=second.result["job_hash"],
                actions=("materialize",),
                scope=(
                    f"candidate:{candidate_id}",
                    "depth:materialization",
                    f"executable:{executable_id}",
                    f"job:{second.result['job_id']}",
                ),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=False,
                operation_id="real-runtime-materialization-runtime-permit",
            )
            writer.start_job(
                permit=materialization_job_permit,
                runtime_permit=materialization_runtime_permit,
                operation_id="real-runtime-materialization-start",
            )
            writer.validate_runtime_entry(
                permit=materialization_runtime_permit,
                executable_id=executable_id,
                input_hash=second.result["job_hash"],
                action="materialize",
                depth=EvidenceDepth.MATERIALIZATION,
                operation_id="real-runtime-materialization-entry",
            )
            materialization_binding = materialization["runtime_binding"]
            assert isinstance(materialization_binding, dict)
            materialization_measurement = writer.evidence.finalize(
                canonical_bytes(
                    {
                        "claims": sorted(REQUIRED_CASES),
                        "schema": "engineering_runtime_measurement.v1",
                    }
                )
            )
            materialization_outputs = {
                "evidence/real-materialization-measurement": (
                    materialization_measurement.sha256
                )
            }
            all_role_hashes = dict(execution_role_hashes)
            local_handoff_output = None
            for role, output in materialization_binding["artifact_roles"].items():
                if role == "local_handoff_manifest":
                    local_handoff_output = output
                    continue
                artifact = writer.evidence.finalize(
                    canonical_bytes(
                        {
                            "role": role,
                            "schema": "engineering_runtime_role.v1",
                        }
                    )
                )
                materialization_outputs[output] = artifact.sha256
                all_role_hashes[role] = artifact.sha256
            assert isinstance(local_handoff_output, str)
            control = writer.read_control()
            assert control is not None
            local_handoff = writer.evidence.finalize(
                canonical_bytes(
                    {
                        "artifact_roles": dict(sorted(all_role_hashes.items())),
                        "authority_manifest_digest": control["authority"][
                            "manifest_digest"
                        ],
                        "candidate_id": candidate_id,
                        "executable_id": executable_id,
                        "mission_id": "MIS-HOLDOUT-LIFECYCLE",
                        "schema": "axiom_local_handoff.v1",
                        "source_receipt_ids": [],
                    }
                )
            )
            materialization_outputs[local_handoff_output] = local_handoff.sha256
            all_role_hashes["local_handoff_manifest"] = local_handoff.sha256
            materialization_result = writer.evidence.finalize(
                canonical_bytes(
                    {
                        "action": "materialize",
                        "candidate_id": candidate_id,
                        "evidence_depth": "materialization",
                        "executable_id": executable_id,
                        "job_hash": second.result["job_hash"],
                        "job_id": second.result["job_id"],
                        "mission_id": "MIS-HOLDOUT-LIFECYCLE",
                        "observations": [
                            {
                                "claim_id": claim,
                                "measurement_artifact_hash": (
                                    materialization_measurement.sha256
                                ),
                                "status": "caller_reported",
                            }
                            for claim in sorted(REQUIRED_CASES)
                        ],
                        "runtime_permit_id": (
                            materialization_runtime_permit.permit_id
                        ),
                        "schema": "runtime_job_evidence.v1",
                    }
                )
            )
            materialization_outputs[
                materialization_binding["result_manifest_output"]
            ] = materialization_result.sha256
            second_completed = writer.complete_job(
                outcome="success",
                output_manifest=materialization_outputs,
                operation_id="real-runtime-materialization-complete",
            )
            release_id = "REL-REAL-PRE-LIVE-HANDOFF"
            declared_release = writer.declare_release(
                release_id=release_id,
                executable_id=executable_id,
                candidate_id=candidate_id,
                evidence=ReleaseEvidence(
                    completion_record_ids=(
                        completed.result["completion_record_id"],
                        second_completed.result["completion_record_id"],
                    )
                ),
                operation_id="real-release-declare",
            )
            release_permit = writer.issue_permit(
                kind=PermitKind.RELEASE,
                subject_kind=SubjectKind.RELEASE,
                subject_id=release_id,
                input_hash=declared_release.result["release_hash"],
                actions=("freeze_release",),
                scope=(f"release:{release_id}",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="real-release-permit",
            )
            writer.freeze_release(
                release_id=release_id,
                permit=release_permit,
                operation_id="real-release-freeze",
            )
            terminal = writer.close_mission(
                outcome="completed_pre_live_handoff",
                basis_record_id=release_id,
                operation_id="real-release-mission-terminal",
            )
            self.assertTrue(terminal.result["project_goal_complete"])
            terminal_control = writer.read_control()
            assert terminal_control is not None
            self.assertEqual(
                terminal_control["next_action"]["kind"],
                "project_goal_complete",
            )

    def test_candidate_rejects_an_unrelated_source_job(self) -> None:
        with TemporaryDirectory() as root:
            writer, executable, _candidate, _plan = self._build_frozen_candidate(
                root
            )
            writer.validation_registry = EvidenceValidatorRegistry(
                (
                    ScientificFixtureValidator(),
                    SourceBoundaryFixtureValidator(),
                )
            )
            contract = source_contract()
            context = SourceEligibility.register(contract)
            writer.record_source_eligibility(
                eligibility=context,
                receipt=None,
                operation_id="candidate-source-register-context",
            )
            expected_return = {
                "executable_id": executable.identity,
                "kind": "plan_candidate_bound_evidence",
            }
            self.assertEqual(
                writer.read_control()["next_action"],  # type: ignore[index]
                expected_return,
            )
            result_name = "evidence/candidate-source-result"
            measurement_name = "evidence/candidate-source-measurement"
            spec = job_spec(
                writer,
                {"kind": "Executable", "id": executable.identity},
            )
            spec["input_hashes"] = [
                *spec["input_hashes"],  # type: ignore[list-item]
                SOURCE_BOUNDARY_PLAN_HASH,
            ]
            spec["expected_outputs"] = [result_name, measurement_name]
            spec["output_classes"] = {
                result_name: "durable_evidence",
                measurement_name: "durable_evidence",
            }
            spec["source_binding"] = {
                "result_manifest_output": result_name,
                "source_contract_id": contract.source_contract_id,
                "transition_evidence": "historical_audit",
                "validation_plan_hash": SOURCE_BOUNDARY_PLAN_HASH,
                "validator_id": SourceBoundaryFixtureValidator.validator_id,
            }
            with self.assertRaisesRegex(
                TransitionError,
                "one of its frozen SourceContracts",
            ):
                writer.declare_job(
                    spec=spec,
                    operation_id="candidate-source-declare",
                )


class ExternalBlockerLifecycleTests(unittest.TestCase):
    def _run_attempt(
        self,
        *,
        writer: StateWriter,
        plan_hash: str,
        recovery_plan: ExternalRecoveryPlan,
        recovery_kind: str,
        ordinal: int,
        indispensable: bool,
        contract_valid_next_action_found: bool,
        verdict: str = "failed",
        judge: bool = True,
        tag: str = "external",
    ) -> str:
        dependency_id = "required-broker-history-service"
        observed_state = "service unavailable after bounded probe"
        required_change = "broker history service becomes available"
        blocked_capability = "indispensable FPMarkets US100 history acquisition"
        recovery_path = recovery_plan.paths[ordinal - 1]
        self.assertEqual(recovery_path.recovery_kind, recovery_kind)
        result_name = f"evidence/{tag}-{ordinal}-result"
        measurement_name = f"evidence/{tag}-{ordinal}-measurement"
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
            "recovery_path_id": recovery_path.recovery_path_id,
            "recovery_plan": recovery_plan.to_identity_payload(),
            "result_manifest_output": result_name,
            "required_external_change": required_change,
            "validation_plan_hash": plan_hash,
            "validator_id": ExternalFixtureValidator.validator_id,
        }
        declared = writer.declare_job(
            spec=spec, operation_id=f"{tag}-{ordinal}-declare"
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
            operation_id=f"{tag}-{ordinal}-permit",
        )
        writer.start_job(permit=permit, operation_id=f"{tag}-{ordinal}-start")
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
                    "verdict": verdict,
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
        failure = None
        if verdict != "passed":
            failure = {
                "external_dependency_id": dependency_id,
                "failure_kind": "external_dependency",
                "interrupted_action": spec["callable_identity"],
                "minimum_reproduction_evidence": [measurement.sha256],
                "observed_external_state": observed_state,
                "resume_action": spec["resume_action"],
                "root_cause": "validated required external service outage",
            }
        completed = writer.complete_job(
            outcome=("success" if verdict == "passed" else verdict),
            output_manifest={
                result_name: result.sha256,
                measurement_name: measurement.sha256,
            },
            failure=failure,
            operation_id=f"{tag}-{ordinal}-complete",
        )
        if judge:
            writer.judge_external_dependency_evidence(
                completion_record_id=completed.result["completion_record_id"],
                operation_id=f"{tag}-{ordinal}-judge",
            )
        return completed.result["completion_record_id"]

    def _writer(
        self, root: str
    ) -> tuple[StateWriter, str, ExternalRecoveryPlan]:
        writer = StateWriter(
            root,
            permit_authority=PermitAuthority(b"e" * 32),
            clock=lambda: FIXED_NOW,
            study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
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
        record_fixture_research_intake(
            writer,
            mission_id="MIS-EXTERNAL-BLOCKER",
            operation_id="external-blocker-intake",
        )
        plan = writer.evidence.finalize(
            canonical_bytes({"schema": "external_boundary_plan.v1"})
        )
        resume_action = ExternalResumeAction.from_next_action(
            writer.read_control()["next_action"]  # type: ignore[index]
        )
        recovery_plan = ExternalRecoveryPlan(
            boundary_event_id=writer.read_control()["heads"]["journal"][  # type: ignore[index]
                "event_id"
            ],
            condition=ExternalResumeCondition(
                dependency_id="required-broker-history-service",
                dependency_kind="market_data_service",
                blocked_mission_capability=(
                    "indispensable FPMarkets US100 history acquisition"
                ),
                required_external_change=(
                    "broker history service becomes available"
                ),
                validator_id=ExternalFixtureValidator.validator_id,
                validation_plan_hash=plan.sha256,
                resume_action=resume_action,
            ),
            paths=tuple(
                ExternalRecoveryPath(
                    recovery_kind=recovery_kind,
                    recovery_path_id=f"recovery-path-{ordinal}",
                )
                for ordinal, recovery_kind in enumerate(
                    (
                        "external_probe",
                        "local_recovery",
                        "safe_substitute_search",
                    ),
                    start=1,
                )
            ),
        )
        return writer, plan.sha256, recovery_plan

    def test_blocker_requires_validated_indispensability_and_no_next_action(self) -> None:
        recovery_kinds = (
            "external_probe",
            "local_recovery",
            "safe_substitute_search",
        )
        with TemporaryDirectory() as root:
            writer, plan_hash, recovery_plan = self._writer(root)
            completions = tuple(
                self._run_attempt(
                    writer=writer,
                    plan_hash=plan_hash,
                    recovery_plan=recovery_plan,
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
            writer, plan_hash, recovery_plan = self._writer(root)
            completion_id = self._run_attempt(
                writer=writer,
                plan_hash=plan_hash,
                recovery_plan=recovery_plan,
                recovery_kind="external_probe",
                ordinal=1,
                indispensable=False,
                contract_valid_next_action_found=True,
            )
            self.assertEqual(
                writer.read_control()["next_action"],  # type: ignore[index]
                recovery_plan.condition.resume_action.to_next_action(),
            )
            with LocalIndex(writer.index_path) as index:
                decisions = index.records_by_kind(
                    "external-dependency-judgement"
                )
            self.assertEqual(
                decisions[-1].payload,
                {
                    "blocker_credit": False,
                    "completion_record_id": completion_id,
                    "disposition": "restore_non_blocking_external_failure",
                    "recovery_path_id": "recovery-path-1",
                    "recovery_plan_id": recovery_plan.identity,
                    "verdict": "failed",
                },
            )

    def test_external_completion_must_be_judged_before_the_next_path(self) -> None:
        with TemporaryDirectory() as root:
            writer, plan_hash, recovery_plan = self._writer(root)
            completion_id = self._run_attempt(
                writer=writer,
                plan_hash=plan_hash,
                recovery_plan=recovery_plan,
                recovery_kind="external_probe",
                ordinal=1,
                indispensable=True,
                contract_valid_next_action_found=False,
                judge=False,
            )
            with self.assertRaisesRegex(
                TransitionError,
                "pending external dependency judgement",
            ):
                self._run_attempt(
                    writer=writer,
                    plan_hash=plan_hash,
                    recovery_plan=recovery_plan,
                    recovery_kind="local_recovery",
                    ordinal=2,
                    indispensable=True,
                    contract_valid_next_action_found=False,
                )
            judged = writer.judge_external_dependency_evidence(
                completion_record_id=completion_id,
                operation_id="external-preemption-judge",
            )
            self.assertEqual(judged.result["verdict"], "failed")
            self.assertEqual(
                writer.read_control()["next_action"],  # type: ignore[index]
                {
                    "kind": "declare_external_dependency_job",
                    "prior_completion_record_ids": [completion_id],
                    "recovery_path_id": "recovery-path-2",
                    "recovery_plan_id": recovery_plan.identity,
                },
            )

    def test_external_local_engineering_gap_restores_without_blocker_credit(
        self,
    ) -> None:
        with TemporaryDirectory() as root:
            writer, plan_hash, recovery_plan = self._writer(root)
            path = recovery_plan.paths[0]
            result_name = "evidence/external-engineering-result"
            measurement_name = "evidence/external-engineering-measurement"
            spec = job_spec(
                writer,
                {"kind": "Mission", "id": "MIS-EXTERNAL-BLOCKER"},
            )
            spec["input_hashes"] = [
                *spec["input_hashes"],  # type: ignore[list-item]
                plan_hash,
            ]
            spec["expected_outputs"] = [result_name, measurement_name]
            spec["output_classes"] = {
                result_name: "durable_evidence",
                measurement_name: "durable_evidence",
            }
            spec["external_dependency_binding"] = {
                "blocked_mission_capability": (
                    "indispensable FPMarkets US100 history acquisition"
                ),
                "dependency_id": "required-broker-history-service",
                "dependency_kind": "market_data_service",
                "exact_resume_action": "resume_fixture_job",
                "recovery_kind": path.recovery_kind,
                "recovery_path_id": path.recovery_path_id,
                "recovery_plan": recovery_plan.to_identity_payload(),
                "result_manifest_output": result_name,
                "required_external_change": (
                    "broker history service becomes available"
                ),
                "validation_plan_hash": plan_hash,
                "validator_id": ExternalFixtureValidator.validator_id,
            }
            declared = writer.declare_job(
                spec=spec,
                operation_id="external-engineering-declare",
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
                operation_id="external-engineering-permit",
            )
            writer.start_job(
                permit=permit,
                operation_id="external-engineering-start",
            )
            reproduction = writer.evidence.finalize(
                b"external probe local parser failure"
            )
            cause = {
                "failure_kind": "engineering",
                "minimum_reproduction_evidence": [reproduction.sha256],
                "root_cause": "local external probe parser failed",
                "interrupted_action": spec["callable_identity"],
            }
            disposition_hash = engineering_failure_disposition(
                writer,
                job_id=declared.result["job_id"],
                evidence_hashes=(reproduction.sha256,),
                disposition="repair_infeasible",
                cause_hash=canonical_digest(
                    domain="repair-cause",
                    payload=cause,
                ),
            )
            writer.record_engineering_failure_disposition(
                failure=cause,
                disposition_hash=disposition_hash,
                operation_id="external-engineering-disposition",
            )
            completed = writer.complete_job(
                outcome="failed",
                output_manifest={},
                failure={
                    **cause,
                    "repair_disposition_hash": disposition_hash,
                    "resume_action": spec["resume_action"],
                },
                operation_id="external-engineering-complete",
            )
            completion_id = completed.result["completion_record_id"]
            self.assertEqual(
                writer.read_control()["next_action"],  # type: ignore[index]
                {
                    "completion_record_id": completion_id,
                    "job_id": declared.result["job_id"],
                    "kind": "judge_external_dependency_evidence",
                },
            )
            judged = writer.judge_external_dependency_evidence(
                completion_record_id=completion_id,
                operation_id="external-engineering-judge",
            )
            self.assertEqual(judged.result["verdict"], "engineering_gap")
            self.assertEqual(
                writer.read_control()["next_action"],  # type: ignore[index]
                recovery_plan.condition.resume_action.to_next_action(),
            )
            with LocalIndex(writer.index_path) as index:
                attempts = index.records_by_kind(
                    "external-dependency-attempt"
                )
                decisions = index.records_by_kind(
                    "external-dependency-judgement"
                )
                gaps = index.records_by_kind(
                    "external-dependency-operational-gap"
                )
            self.assertEqual(attempts[-1].status, "local_failure")
            self.assertFalse(decisions)
            self.assertEqual(len(gaps), 1)
            self.assertEqual(gaps[0].payload["scientific_trial_delta"], 0)
            self.assertEqual(gaps[0].payload["scientific_failure_delta"], 0)

    def test_passed_and_not_evaluable_restore_the_exact_mission_action(self) -> None:
        for verdict in ("passed", "not_evaluable"):
            with self.subTest(verdict=verdict), TemporaryDirectory() as root:
                writer, plan_hash, recovery_plan = self._writer(root)
                self._run_attempt(
                    writer=writer,
                    plan_hash=plan_hash,
                    recovery_plan=recovery_plan,
                    recovery_kind="external_probe",
                    ordinal=1,
                    indispensable=True,
                    contract_valid_next_action_found=False,
                    verdict=verdict,
                )
                self.assertEqual(
                    writer.read_control()["next_action"],  # type: ignore[index]
                    recovery_plan.condition.resume_action.to_next_action(),
                )
                with LocalIndex(writer.index_path) as index:
                    decisions = index.records_by_kind(
                        "external-dependency-judgement"
                    )
                    attempts = index.records_by_kind(
                        "external-dependency-attempt"
                    )
                self.assertEqual(decisions[-1].status, verdict)
                self.assertEqual(
                    decisions[-1].payload["disposition"],
                    (
                        "resume_mission_action"
                        if verdict == "passed"
                        else "restore_without_blocker_credit"
                    ),
                )
                self.assertEqual(
                    attempts[-1].status,
                    "available" if verdict == "passed" else "external_unresolved",
                )

    def test_recurrent_outage_replans_at_a_new_exact_boundary(self) -> None:
        with TemporaryDirectory() as root:
            writer, plan_hash, recovery_plan = self._writer(root)
            self._run_attempt(
                writer=writer,
                plan_hash=plan_hash,
                recovery_plan=recovery_plan,
                recovery_kind="external_probe",
                ordinal=1,
                indispensable=True,
                contract_valid_next_action_found=False,
                verdict="passed",
            )
            restored = writer.read_control()
            assert restored is not None
            recurrent_plan = ExternalRecoveryPlan(
                boundary_event_id=restored["heads"]["journal"]["event_id"],
                condition=recovery_plan.condition,
                paths=recovery_plan.paths,
            )
            self.assertNotEqual(recurrent_plan.identity, recovery_plan.identity)
            stale_plan = ExternalRecoveryPlan(
                boundary_event_id=recovery_plan.boundary_event_id,
                condition=recovery_plan.condition,
                paths=tuple(
                    ExternalRecoveryPath(
                        recovery_kind=path.recovery_kind,
                        recovery_path_id=f"stale-{path.recovery_path_id}",
                    )
                    for path in recovery_plan.paths
                ),
            )
            with self.assertRaisesRegex(TransitionError, "cannot preempt"):
                self._run_attempt(
                    writer=writer,
                    plan_hash=plan_hash,
                    recovery_plan=stale_plan,
                    recovery_kind="external_probe",
                    ordinal=1,
                    indispensable=True,
                    contract_valid_next_action_found=False,
                    tag="stale-recurrence",
                )
            self._run_attempt(
                writer=writer,
                plan_hash=plan_hash,
                recovery_plan=recurrent_plan,
                recovery_kind="external_probe",
                ordinal=1,
                indispensable=True,
                contract_valid_next_action_found=False,
                verdict="not_evaluable",
                tag="accepted-recurrence",
            )
            self.assertEqual(
                writer.read_control()["next_action"],  # type: ignore[index]
                recurrent_plan.condition.resume_action.to_next_action(),
            )

    def test_blocked_terminal_without_portfolio_reenters_same_mission(self) -> None:
        with TemporaryDirectory() as root:
            writer, plan_hash, recovery_plan = self._writer(root)
            initial_control = writer.read_control()
            assert initial_control is not None
            initial_authorization_hash = initial_control["authorizations"][
                "Mission:MIS-EXTERNAL-BLOCKER"
            ]["authorization_hash"]
            completions = tuple(
                self._run_attempt(
                    writer=writer,
                    plan_hash=plan_hash,
                    recovery_plan=recovery_plan,
                    recovery_kind=recovery_kind,
                    ordinal=ordinal,
                    indispensable=True,
                    contract_valid_next_action_found=False,
                )
                for ordinal, recovery_kind in enumerate(
                    (
                        "external_probe",
                        "local_recovery",
                        "safe_substitute_search",
                    ),
                    start=1,
                )
            )
            blocker = writer.record_external_blocker(
                dependency_id="required-broker-history-service",
                completion_record_ids=completions,
                operation_id="external-reentry-blocker",
            )
            writer.close_mission(
                outcome="blocked_external",
                basis_record_id=blocker.result["basis_record_id"],
                operation_id="external-reentry-close",
            )
            blocked = writer.read_control()
            assert blocked is not None
            close_id = blocked["next_action"][
                "predecessor_mission_close_record_id"
            ]
            self.assertEqual(blocked["next_action"]["kind"], "await_external_change")
            with LocalIndex(writer.index_path) as index:
                self.assertEqual(index.records_by_kind("portfolio-snapshot"), ())

            expected_facts = {
                "blocked_mission_capability": (
                    recovery_plan.condition.blocked_mission_capability
                ),
                "dependency_id": recovery_plan.condition.dependency_id,
                "external_change_satisfied": True,
                "resume_condition_id": recovery_plan.condition.identity,
            }
            measurement = writer.evidence.finalize(
                canonical_bytes(
                    {
                        "facts": expected_facts,
                        "schema": "external_boundary_measurement.v1",
                        "verdict": "passed",
                    }
                )
            )
            result = writer.evidence.finalize(
                canonical_bytes(
                    {
                        "blocker_basis_record_id": blocker.result[
                            "basis_record_id"
                        ],
                        "condition_id": recovery_plan.condition.identity,
                        "measurement_artifact_hashes": [measurement.sha256],
                        "mission_close_record_id": close_id,
                        "mission_id": "MIS-EXTERNAL-BLOCKER",
                        "schema": "external_change_evidence.v1",
                    }
                )
            )
            evidence = ExternalChangeEvidence(
                condition_id=recovery_plan.condition.identity,
                result_manifest_output="evidence/external-change-result",
                output_manifest=(
                    ("evidence/external-change-result", result.sha256),
                    ("evidence/external-change-measurement", measurement.sha256),
                ),
            )
            stale_evidence = ExternalChangeEvidence(
                condition_id="external-resume-condition:" + "0" * 64,
                result_manifest_output=evidence.result_manifest_output,
                output_manifest=evidence.output_manifest,
            )
            with self.assertRaises(TransitionError):
                writer.resume_blocked_mission(
                    basis_record_id=blocker.result["basis_record_id"],
                    mission_close_record_id=close_id,
                    evidence=stale_evidence,
                    operation_id="reject-stale-external-reentry",
                )
            resumed = writer.resume_blocked_mission(
                basis_record_id=blocker.result["basis_record_id"],
                mission_close_record_id=close_id,
                evidence=evidence,
                operation_id="accept-external-reentry",
            )
            self.assertEqual(resumed.result["authorization_epoch"], 2)
            control = writer.read_control()
            assert control is not None
            self.assertEqual(
                control["scientific"]["active_mission"],
                "MIS-EXTERNAL-BLOCKER",
            )
            self.assertEqual(
                control["next_action"],
                recovery_plan.condition.resume_action.to_next_action(),
            )
            self.assertEqual(
                control["authorizations"]["Mission:MIS-EXTERNAL-BLOCKER"][
                    "authorization_epoch"
                ],
                2,
            )
            self.assertNotEqual(
                control["authorizations"]["Mission:MIS-EXTERNAL-BLOCKER"][
                    "authorization_hash"
                ],
                initial_authorization_hash,
            )
            reused = writer.resume_blocked_mission(
                basis_record_id=blocker.result["basis_record_id"],
                mission_close_record_id=close_id,
                evidence=evidence,
                operation_id="accept-external-reentry",
            )
            self.assertTrue(reused.reused)
            with self.assertRaises(TransitionError):
                writer.resume_blocked_mission(
                    basis_record_id=blocker.result["basis_record_id"],
                    mission_close_record_id=close_id,
                    evidence=evidence,
                    operation_id="reject-replayed-external-reentry",
                )
            with LocalIndex(writer.index_path) as index:
                self.assertEqual(len(index.records_by_kind("mission-open")), 1)
                self.assertEqual(len(index.records_by_kind("mission-reentry")), 1)
                self.assertEqual(index.records_by_kind("trial"), ())


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
            altered["engineering"]["commissioning_fixture"] = True
            altered["control_hash"] = control_hash(altered)
            writer.control.path.write_bytes(canonical_bytes(altered))
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

class ResearchDirectionFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.writer = StateWriter(
            self.temporary.name,
            permit_authority=PermitAuthority(b"q" * 32),
            clock=lambda: FIXED_NOW,
            study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
            foundation_root=REPO_ROOT,
            validation_registry=EvidenceValidatorRegistry(
                (ComponentParityFixtureValidator(),)
            ),
        )
        self.writer.initialize_ready()
        self.writer.open_mission(
            mission_id="MIS-DIRECTION",
            goal=mission_goal("research direction state machine"),
            operation_id="direction-mission",
        )
        with self.assertRaisesRegex(TransitionError, "research intake"):
            self.writer.open_initiative(
                initiative_id="INI-DIRECTION",
                objective=initiative_objective("research direction"),
                operation_id="reject-direction-initiative-before-intake",
            )
        self.intake = record_fixture_research_intake(
            self.writer,
            mission_id="MIS-DIRECTION",
            operation_id="direction-intake",
        )
        self.writer.open_initiative(
            initiative_id="INI-DIRECTION",
            objective=initiative_objective("research direction"),
            operation_id="direction-initiative",
        )
        self.axes = tuple(
            PortfolioAxis(
                axis_id=f"direction-axis-{letter}",
                causal_question=f"Does direction axis {letter} identify the bottleneck?",
                mechanism_family=f"direction-family-{letter}",
            )
            for letter in ("a", "b", "c")
        )
        missing_intake_snapshot = PortfolioSnapshot(
            mission_id="MIS-DIRECTION",
            axes=self.axes,
            opportunity_cost_basis="reject an unbound initial Portfolio",
            exhaustion_standard=exhaustion_standard(),
        )
        with self.assertRaisesRegex(TransitionError, "exact Initiative action"):
            self.writer.record_portfolio_snapshot(
                snapshot=missing_intake_snapshot,
                operation_id="reject-direction-snapshot-without-intake",
            )
        self.snapshot = PortfolioSnapshot(
            mission_id="MIS-DIRECTION",
            axes=self.axes,
            opportunity_cost_basis="compare layer and architecture alternatives",
            research_intake_id=self.intake.identity,
            exhaustion_standard=exhaustion_standard(),
        )
        self.writer.record_portfolio_snapshot(
            snapshot=self.snapshot,
            operation_id="direction-snapshot",
        )

    def test_legacy_trials_allow_one_controlled_chassis_bootstrap(self) -> None:
        baseline = portfolio_axis_baseline(self.axes[0])
        axis_identity = self.axes[0].identity
        legacy_trial = SimpleNamespace(
            payload={"executable": {"data_contract": baseline.data_contract}}
        )

        bootstrap_decision = SimpleNamespace(
            record_id="decision:legacy-bootstrap",
            payload={
                "baseline_executable_id": baseline.identity,
                "baseline_executable": baseline.to_identity_payload(),
                "baseline_provenance": {
                    "data_contract": baseline.data_contract,
                    "kind": "first_controlled_chassis_bootstrap",
                },
                "target_axis_identity": axis_identity,
            }
        )

        class LegacyIndex:
            def __init__(self, *, controlled: bool, anchored: bool = False) -> None:
                self.controlled = controlled
                self.anchored = anchored

            def get(self, kind: str, record_id: str):
                if (
                    kind == "portfolio-decision"
                    and self.anchored
                    and record_id == bootstrap_decision.record_id
                ):
                    return bootstrap_decision
                return None

            def event_head(self, stream: str):
                return None

            def records_by_payload_text(
                self,
                kind: str,
                lookup_name: str,
                value: str,
            ):
                if (
                    kind == "trial"
                    and lookup_name == "trial_data_contract"
                    and value == baseline.data_contract
                ):
                    return [legacy_trial]
                if (
                    kind == "portfolio-decision"
                    and lookup_name == "target_axis_identity"
                    and value == axis_identity
                    and self.anchored
                ):
                    return [bootstrap_decision]
                if (
                    kind == "study-open"
                    and lookup_name == "study_open_baseline_data_contract"
                    and value == baseline.data_contract
                    and self.controlled
                ):
                    return [
                        SimpleNamespace(
                            payload={
                                "controlled_chassis": {
                                    "baseline_executable": {
                                        "data_contract": baseline.data_contract
                                    }
                                },
                                "portfolio_axis_identity": axis_identity,
                            }
                        )
                    ]
                return []

            def records_by_kind(self, kind: str):
                raise AssertionError(
                    f"bounded legacy baseline lookup scanned {kind} history"
                )

            def records_by_payload_text_values(
                self,
                kind: str,
                lookup_name: str,
                values,
            ):
                if (
                    kind == "portfolio-decision"
                    and lookup_name == "target_axis_identity"
                    and axis_identity in values
                    and self.anchored
                ):
                    return [bootstrap_decision]
                return []

        self.assertIsNone(
            StateWriter._prior_scientific_baseline(
                LegacyIndex(controlled=False), baseline
            )
        )
        with self.assertRaisesRegex(
            TransitionError, "must reuse a prior scientific Executable"
        ):
            StateWriter._prior_scientific_baseline(
                LegacyIndex(controlled=True), baseline
            )
        self.assertIsNone(
            StateWriter._prior_scientific_baseline(
                LegacyIndex(controlled=True, anchored=True),
                baseline,
            )
        )
        self.assertIsNone(
            StateWriter._prior_scientific_baseline(
                LegacyIndex(controlled=True),
                baseline,
                portfolio_axis_identity=self.axes[1].identity,
            )
        )

    def _quant_team_review(
        self,
        *,
        options: tuple[DecisionOption, ...],
        chosen_option_id: str,
    ) -> QuantTeamDecisionReview:
        return quant_team_review_for_current_action(
            self.writer,
            options=options,
            chosen_option_id=chosen_option_id,
        )

    def _decision(
        self,
        *,
        tag: str,
        target_index: int,
        action: PortfolioAction,
    ) -> PortfolioDecision:
        alternative_index = (target_index + 1) % len(self.axes)
        chosen_id = f"choose-{tag}"
        alternative_id = f"alternative-{tag}"
        options = (
            DecisionOption(
                option_id=chosen_id,
                action=action,
                target_id=self.axes[target_index].axis_id,
                expected_information_value="positive",
                opportunity_cost="one bounded Batch",
            ),
            DecisionOption(
                option_id=alternative_id,
                action=PortfolioAction.ROTATE,
                target_id=self.axes[alternative_index].axis_id,
                expected_information_value="positive",
                opportunity_cost="deferred",
                omission_reason="the chosen branch is tested first",
            ),
        )
        review = self._quant_team_review(
            options=options,
            chosen_option_id=chosen_id,
        )
        decision = PortfolioDecision(
            decision_id=f"DEC-DIRECTION-{tag}",
            chosen_option_id=chosen_id,
            options=options,
            rationale="follow the typed diagnosis while preserving the forest",
            commitment_batches=1,
            quant_team_review=review,
            baseline_executable=portfolio_axis_baseline(self.axes[target_index]),
        )
        return decision

    def _source_authority_decision(
        self,
        *,
        tag: str,
        source_id: str,
    ) -> PortfolioDecision:
        template = self._decision(
            tag=tag,
            target_index=0,
            action=PortfolioAction.DEEPEN,
        )
        assert template.baseline_executable is not None
        baseline = template.baseline_executable
        source_component = ComponentSpec(
            display_name=f"{tag} eligibility-only source authority",
            protocol="external_source.writer_projection_fixture.v1",
            implementation=fixture_component_implementation(
                "fixture.external_source.writer_projection"
            ),
            spec={
                "performance_allowed": False,
                "source_contract_id": source_id,
            },
        )
        source_baseline = ExecutableSpec(
            display_name=f"{tag} source-authority baseline",
            components=(*baseline.components, source_component),
            parameters=baseline.parameter_values(),
            data_contract=baseline.data_contract,
            split_contract=baseline.split_contract,
            clock_contract=baseline.clock_contract,
            cost_contract=baseline.cost_contract,
            engine_contract=baseline.engine_contract,
        )
        self.assertEqual(source_baseline.source_contracts, ())
        self.assertEqual(
            ArchitectureChassisSpec.from_executable(source_baseline).identity,
            self.axes[0].architecture_chassis.identity,
        )
        return PortfolioDecision(
            decision_id=f"DEC-DIRECTION-{tag}-SOURCE",
            chosen_option_id=template.chosen_option_id,
            options=template.options,
            rationale=template.rationale,
            commitment_batches=template.commitment_batches,
            quant_team_review=template.quant_team_review,
            baseline_executable=source_baseline,
        )

    def _register_context_source(self) -> tuple[SourceContract, str]:
        contract = source_contract()
        registered = self.writer.record_source_eligibility(
            eligibility=SourceEligibility.register(contract),
            receipt=None,
            operation_id="direction-register-context-source",
        )
        state_record_id = canonical_digest(
            domain="source-state",
            payload={
                "source_id": contract.source_contract_id,
                "state": "context_only",
                "ordinal": registered.result["ordinal"],
                "evidence_receipt_id": None,
            },
        )
        return contract, state_record_id

    def _invalidate_context_source(
        self,
        *,
        contract: SourceContract,
        state_record_id: str,
    ) -> None:
        finding_id = "SOURCE-DIRECTION-ZERO-TRIAL"
        report = self.writer.evidence.finalize(
            source_audit_report_bytes(
                finding_id=finding_id,
                source_contract_id=contract.source_contract_id,
                source_state_record_id=state_record_id,
            )
        )
        manifest = SourceAuthorityAuditManifest(
            report_artifact_hash=report.sha256,
            report_finding_id=finding_id,
            source_contract_id=contract.source_contract_id,
            source_state_record_id=state_record_id,
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect="context source lacks point-in-time authority",
            observed_at_utc=FIXED_NOW,
        )
        manifest_artifact = self.writer.evidence.finalize(
            canonical_bytes(manifest.to_identity_payload())
        )
        invalidation = SourceAuthorityInvalidation(
            source_contract_id=contract.source_contract_id,
            source_state_record_id=state_record_id,
            audit_artifact_hash=manifest_artifact.sha256,
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect="context source lacks point-in-time authority",
            observed_at_utc=FIXED_NOW,
        )
        self.writer.suspend_source_authority_from_audit(
            invalidation=invalidation,
            operation_id="direction-invalidate-context-source",
        )

    def test_zero_trial_source_authority_blocks_prospective_decision(self) -> None:
        contract, state_record_id = self._register_context_source()
        self._invalidate_context_source(
            contract=contract,
            state_record_id=state_record_id,
        )
        decision = self._source_authority_decision(
            tag="ZERO-TRIAL-BLOCK",
            source_id=contract.source_contract_id,
        )

        with self.assertRaisesRegex(TransitionError, "invalidated source"):
            self.writer.record_portfolio_decision(
                decision=decision,
                operation_id="reject-zero-trial-invalidated-source-decision",
            )
        with LocalIndex(self.writer.index_path) as index:
            self.assertIsNone(index.get("portfolio-decision", decision.identity))
            self.assertEqual(len(index.records_by_kind("trial")), 0)

    def test_study_open_rechecks_accepted_source_authority_projection(self) -> None:
        contract, _ = self._register_context_source()
        decision = self._source_authority_decision(
            tag="STUDY-RECHECK",
            source_id=contract.source_contract_id,
        )
        self.writer.record_portfolio_decision(
            decision=decision,
            operation_id="accept-source-authority-study-decision",
        )
        with LocalIndex(self.writer.index_path) as index:
            accepted = index.get("portfolio-decision", decision.identity)
        assert accepted is not None
        self.assertEqual(
            accepted.payload["source_authority_subject_ids"],
            [contract.source_contract_id],
        )

        axis = self.axes[0]
        assert decision.baseline_executable is not None
        assert decision.architecture_chassis is not None
        controlled_chassis = ControlledStudyChassis(
            baseline_executable=decision.baseline_executable,
            changed_domains=axis.changed_domains,
            controlled_domains=axis.controlled_domains,
            embedded_controlled_domains=(ResearchLayer.DATA_SOURCE,),
            architecture=decision.architecture_chassis,
        )
        question = study_question("accepted source authority is current at Study open")
        proposal = {"mechanism": "source authority recheck"}
        study_hash = self.writer.study_input_hash(
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            semantic_proposal=proposal,
            controlled_chassis=controlled_chassis,
            portfolio_axis_id=axis.axis_id,
            portfolio_axis_identity=axis.identity,
            portfolio_decision_id=decision.identity,
        )
        permit = self.writer.issue_permit(
            kind=PermitKind.STUDY,
            subject_kind=SubjectKind.INITIATIVE,
            subject_id="INI-DIRECTION",
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
            operation_id="source-authority-study-recheck-permit",
        )
        observed: dict[str, tuple[str, ...]] = {}

        def blocked_resolution(
            _index,
            _axis,
            *,
            prospective_source_ids=(),
        ):
            observed["source_ids"] = tuple(prospective_source_ids)
            return SimpleNamespace(selectable=False)

        with patch.object(
            self.writer,
            "_effective_axis_resolution",
            side_effect=blocked_resolution,
        ):
            with self.assertRaisesRegex(
                TransitionError,
                "blocked by current source authority",
            ):
                self.writer.open_study(
                    study_id="STU-SOURCE-AUTHORITY-RECHECK",
                    question=question,
                    material_identity=OBSERVED_MATERIAL_ID,
                    material_display_name="foundation observed material",
                    semantic_proposal=proposal,
                    controlled_chassis=controlled_chassis,
                    portfolio_axis_id=axis.axis_id,
                    portfolio_axis_identity=axis.identity,
                    portfolio_decision_id=decision.identity,
                    permit=permit,
                    operation_id="reject-stale-source-authority-study-open",
                )
        self.assertEqual(
            observed["source_ids"],
            (contract.source_contract_id,),
        )

    def test_real_portfolio_decision_requires_evidence_bound_plural_judgment(
        self,
    ) -> None:
        reviewed = self._decision(
            tag="REQUIRE-QUANT-TEAM",
            target_index=0,
            action=PortfolioAction.DEEPEN,
        )
        legacy = PortfolioDecision(
            decision_id="DEC-DIRECTION-UNREVIEWED",
            chosen_option_id=reviewed.chosen_option_id,
            options=reviewed.options,
            rationale=reviewed.rationale,
            commitment_batches=reviewed.commitment_batches,
            baseline_executable=reviewed.baseline_executable,
        )
        with self.assertRaisesRegex(TransitionError, "plural quant-team"):
            self.writer.record_portfolio_decision(
                decision=legacy,
                operation_id="reject-one-dimensional-real-decision",
            )

        assert reviewed.quant_team_review is not None
        review = reviewed.quant_team_review
        missing = DecisionBasisRecord(
            kind="portfolio-snapshot",
            record_id="portfolio:" + "f" * 64,
        )
        forged_review = QuantTeamDecisionReview(
            assessments=tuple(
                DecisionLensAssessment(
                    lens=assessment.lens,
                    position=assessment.position,
                    option_ids=assessment.option_ids,
                    basis_records=(missing,),
                    finding=assessment.finding,
                )
                for assessment in review.assessments
            ),
            claim_boundary=review.claim_boundary,
            resolution_basis=review.resolution_basis,
            disagreement_resolution=review.disagreement_resolution,
        )
        forged = PortfolioDecision(
            decision_id="DEC-DIRECTION-FORGED-QUANT-TEAM",
            chosen_option_id=reviewed.chosen_option_id,
            options=reviewed.options,
            rationale=reviewed.rationale,
            commitment_batches=reviewed.commitment_batches,
            quant_team_review=forged_review,
            baseline_executable=reviewed.baseline_executable,
        )
        with self.assertRaisesRegex(TransitionError, "unavailable durable evidence"):
            self.writer.record_portfolio_decision(
                decision=forged,
                operation_id="reject-forged-quant-team-basis",
            )

        result = self.writer.record_portfolio_decision(
            decision=reviewed,
            operation_id="accept-evidence-bound-quant-team-decision",
        )
        self.assertEqual(result.result["decision_id"], reviewed.identity)

    def test_executable_job_requires_component_source_closure(self) -> None:
        decision = self._decision(
            tag="IMPLEMENTATION-CLOSURE",
            target_index=0,
            action=PortfolioAction.DEEPEN,
        )
        self.writer.record_portfolio_decision(
            decision=decision,
            operation_id="implementation-closure-decision",
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
        question = study_question("Executable Job implementation closure")
        proposal = {"mechanism": "component source closure"}
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
            subject_id="INI-DIRECTION",
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
            operation_id="implementation-closure-study-permit",
        )
        opened = self.writer.open_study(
            study_id="STU-IMPLEMENTATION-CLOSURE",
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            material_display_name="foundation observed material",
            semantic_proposal=proposal,
            controlled_chassis=controlled_chassis,
            portfolio_axis_id=axis.axis_id,
            portfolio_axis_identity=axis.identity,
            portfolio_decision_id=decision.identity,
            permit=study_permit,
            operation_id="implementation-closure-study-open",
        )
        batch = batch_spec(
            batch_id="BAT-IMPLEMENTATION-CLOSURE",
            study_id="STU-IMPLEMENTATION-CLOSURE",
            study_hash=opened.result["study_hash"],
        )
        batch_permit = self.writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-IMPLEMENTATION-CLOSURE",
            input_hash=batch.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="implementation-closure-batch-permit",
        )
        self.writer.open_batch(
            batch_spec=batch,
            permit=batch_permit,
            operation_id="implementation-closure-batch-open",
        )
        executable = changed_domain_executable(
            decision.baseline_executable,
            domain="calibration",
            change_tag="implementation-closure",
        )
        self.writer.register_trial(
            executable=executable,
            operation_id="implementation-closure-trial",
        )

        incomplete = job_spec(
            self.writer,
            {"kind": "Executable", "id": executable.identity},
        )
        incomplete_source = self.writer.evidence.finalize(
            b"incomplete fixture Job source"
        )
        incomplete_callable = "fixture.incomplete_component_closure"
        incomplete_manifest = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "artifact_hashes": [incomplete_source.sha256],
                    "callable_identity": incomplete_callable,
                    "protocol": "python.source.fixture.v1",
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        incomplete["callable_identity"] = incomplete_callable
        incomplete["implementation_identity"] = incomplete_manifest.sha256
        with self.assertRaisesRegex(
            TransitionError, "omits Component source bytes"
        ):
            self.writer.declare_job(
                spec=incomplete,
                operation_id="reject-incomplete-component-closure",
            )

        complete = job_spec(
            self.writer,
            {"kind": "Executable", "id": executable.identity},
        )
        expected_hashes = sorted(
            {
                component.implementation.rsplit("@sha256:", 1)[1]
                for component in executable.components
            }
        )
        current_source_path = (
            REPO_ROOT
            / "src"
            / "axiom_rift"
            / "research"
            / "implementation_closure.py"
        )
        current_source = self.writer.evidence.finalize(
            current_source_path.read_bytes()
        )
        callable_identity = (
            "axiom_rift.research.implementation_closure."
            "require_current_job_source_closure.v1"
        )
        legacy_callable_only = job_spec(
            self.writer,
            {"kind": "Executable", "id": executable.identity},
        )
        legacy_manifest = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "artifact_hashes": sorted(
                        {
                            current_source.sha256,
                            *expected_hashes,
                        }
                    ),
                    "callable_identity": callable_identity,
                    "protocol": "python.source.fixture.v1",
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        legacy_callable_only["callable_identity"] = callable_identity
        legacy_callable_only["implementation_identity"] = (
            legacy_manifest.sha256
        )
        with self.assertRaisesRegex(
            TransitionError,
            "requires one exact current source closure",
        ):
            self.writer.declare_job(
                spec=legacy_callable_only,
                operation_id="reject-callable-only-legacy-job",
            )
        source_closure = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "callable_identity": callable_identity,
                    "dependencies": [
                        {
                            "path": (
                                "axiom_rift/research/"
                                "implementation_closure.py"
                            ),
                            "sha256": current_source.sha256,
                        }
                    ],
                    "schema": "job_implementation_source_closure.v1",
                }
            )
        )
        implementation = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "artifact_hashes": sorted(
                        {
                            current_source.sha256,
                            source_closure.sha256,
                            *expected_hashes,
                        }
                    ),
                    "callable_identity": callable_identity,
                    "protocol": "python.source.current_project.v1",
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        complete["callable_identity"] = callable_identity
        complete["implementation_identity"] = implementation.sha256
        with patch(
            "axiom_rift.operations.writer."
            "external_observed_development_job_binding",
            wraps=external_observed_development_job_binding,
        ) as declaration_external_binding:
            declared = self.writer.declare_job(
                spec=complete,
                operation_id="accept-complete-component-closure",
            )
        declaration_external_binding.assert_called_once()
        with LocalIndex(self.writer.index_path) as index:
            record = index.get("job-declared", declared.result["job_id"])
        assert record is not None
        self.assertEqual(
            record.payload["component_implementation_hashes"],
            expected_hashes,
        )
        self.assertNotIn("source_closure_exemption", record.payload)
        self.assertEqual(
            record.payload["source_closure_authority"][
                "callable_module_path"
            ],
            "axiom_rift/research/implementation_closure.py",
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
            operation_id="implementation-closure-job-permit",
        )
        original_read_bytes = Path.read_bytes

        def drift_current_source(path: Path) -> bytes:
            content = original_read_bytes(path)
            if path.resolve() == current_source_path.resolve():
                return content + b"\n# post-declaration drift\n"
            return content

        with patch.object(Path, "read_bytes", drift_current_source):
            with self.assertRaisesRegex(
                TransitionError,
                "current project source bytes",
            ):
                self.writer.start_job(
                    permit=permit,
                    operation_id="reject-source-drift-before-job-start",
                )
        with patch(
            "axiom_rift.operations.writer."
            "require_current_external_observed_development_job_binding",
            wraps=require_current_external_observed_development_job_binding,
        ) as start_external_binding:
            started = self.writer.start_job(
                permit=permit,
                operation_id="implementation-closure-job-start",
            )
        start_external_binding.assert_called_once()
        self.assertEqual(started.result["job_id"], declared.result["job_id"])

    def _accept_component_parity_for_decision(
        self,
        *,
        decision: PortfolioDecision,
        canonical_component: ComponentSpec,
        equivalent_component: ComponentSpec,
        tag: str,
    ) -> None:
        assert decision.architecture_chassis is not None
        dimensions = sorted(
            dimension.value for dimension in ComponentParityDimension
        )
        plan = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "schema": "component_parity_validation_plan.v1",
                    "tag": tag,
                }
            )
        )
        spec = job_spec(
            self.writer,
            {"kind": "Mission", "id": "MIS-DIRECTION"},
        )
        result_name = f"evidence/{tag}-parity-result"
        measurement_name = f"evidence/{tag}-parity-measurement"
        spec["input_hashes"] = [
            *spec["input_hashes"],
            plan.sha256,
            canonical_component.identity.removeprefix("component:"),
            equivalent_component.identity.removeprefix("component:"),
        ]
        spec["expected_outputs"] = [result_name, measurement_name]
        spec["output_classes"] = {
            result_name: "durable_evidence",
            measurement_name: "durable_evidence",
        }
        spec["resume_action"] = "execute_portfolio_decision"
        spec["component_parity_binding"] = {
            "architecture_chassis_identity": decision.architecture_chassis.identity,
            "canonical_component_id": canonical_component.identity,
            "canonical_component_manifest": canonical_component.to_identity_payload(),
            "dimensions": dimensions,
            "equivalent_component_id": equivalent_component.identity,
            "equivalent_component_manifest": equivalent_component.to_identity_payload(),
            "portfolio_axis_identity": next(
                axis.identity
                for axis in self.axes
                if axis.axis_id == decision.chosen.target_id
            ),
            "portfolio_decision_id": decision.identity,
            "portfolio_snapshot_id": self.snapshot.identity,
            "result_manifest_output": result_name,
            "validation_plan_hash": plan.sha256,
            "validator_id": ComponentParityFixtureValidator.validator_id,
        }
        declared = self.writer.declare_job(
            spec=spec,
            operation_id=f"{tag}-parity-job-declare",
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
            operation_id=f"{tag}-parity-job-permit",
        )
        self.writer.start_job(
            permit=permit,
            operation_id=f"{tag}-parity-job-start",
        )
        measurement = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "canonical_component_id": canonical_component.identity,
                    "dimensions": dimensions,
                    "equivalent": True,
                    "equivalent_component_id": equivalent_component.identity,
                    "schema": "component_parity_measurement.v1",
                }
            )
        )
        parity_manifest = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "architecture_chassis_identity": decision.architecture_chassis.identity,
                    "artifact_hashes": [measurement.sha256],
                    "canonical_component_id": canonical_component.identity,
                    "dimensions": dimensions,
                    "equivalent_component_id": equivalent_component.identity,
                    "job_hash": declared.result["job_hash"],
                    "job_id": declared.result["job_id"],
                    "mission_id": "MIS-DIRECTION",
                    "portfolio_axis_identity": spec["component_parity_binding"][
                        "portfolio_axis_identity"
                    ],
                    "portfolio_decision_id": decision.identity,
                    "portfolio_snapshot_id": self.snapshot.identity,
                    "schema": "component_parity_result.v2",
                    "verdict": "equivalent",
                }
            )
        )
        completed = self.writer.complete_job(
            outcome="success",
            output_manifest={
                result_name: parity_manifest.sha256,
                measurement_name: measurement.sha256,
            },
            operation_id=f"{tag}-parity-job-complete",
        )
        self.writer.judge_job_evidence(
            completion_record_id=completed.result["completion_record_id"],
            disposition="accept_component_parity",
            operation_id=f"{tag}-parity-job-accept",
        )

    def test_predecision_study_permit_and_job_registration_are_blocked(self) -> None:
        with self.assertRaisesRegex(PermitError, "accepted current Portfolio Decision"):
            self.writer.issue_permit(
                kind=PermitKind.STUDY,
                subject_kind=SubjectKind.INITIATIVE,
                subject_id="INI-DIRECTION",
                input_hash="a" * 64,
                actions=("open_study",),
                scope=(
                    "study",
                    "decision:future",
                    "axis:future",
                    f"snapshot:{self.snapshot.identity}",
                ),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="reject-predecision-study-permit",
            )
        with self.assertRaisesRegex(TransitionError, "cannot preempt"):
            self.writer.declare_job(
                spec=job_spec(
                    self.writer,
                    {"kind": "Initiative", "id": "INI-DIRECTION"},
                ),
                operation_id="reject-predecision-job-registration",
            )
        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["next_action"]["kind"], "portfolio_decision")

    def test_writer_accepts_typed_parity_and_rejects_protocol_surface_drift(self) -> None:
        axis = self.axes[0]
        decision = self._decision(
            tag="CONTROLLED-IDENTITY",
            target_index=0,
            action=PortfolioAction.DEEPEN,
        )
        self.writer.record_portfolio_decision(
            decision=decision,
            operation_id="controlled-identity-decision",
        )
        baseline = decision.baseline_executable
        assert baseline is not None and decision.architecture_chassis is not None
        unregistered_baseline = scientific_executable_spec(
            "caller-invented-baseline"
        )
        self.assertNotEqual(unregistered_baseline.identity, baseline.identity)
        unregistered_chassis = ControlledStudyChassis(
            baseline_executable=unregistered_baseline,
            changed_domains=axis.changed_domains,
            controlled_domains=axis.controlled_domains,
            architecture=decision.architecture_chassis,
        )
        unregistered_question = study_question("unregistered baseline")
        unregistered_proposal = {"mechanism": "unregistered baseline"}
        unregistered_hash = self.writer.study_input_hash(
            question=unregistered_question,
            material_identity=OBSERVED_MATERIAL_ID,
            semantic_proposal=unregistered_proposal,
            controlled_chassis=unregistered_chassis,
            portfolio_axis_id=axis.axis_id,
            portfolio_axis_identity=axis.identity,
            portfolio_decision_id=decision.identity,
        )
        unregistered_permit = self.writer.issue_permit(
            kind=PermitKind.STUDY,
            subject_kind=SubjectKind.INITIATIVE,
            subject_id="INI-DIRECTION",
            input_hash=unregistered_hash,
            actions=("open_study",),
            scope=(
                "study",
                f"decision:{decision.identity}",
                f"axis:{axis.identity}",
                f"baseline:{baseline.identity}",
                f"chassis:{decision.architecture_chassis.identity}",
                f"snapshot:{self.snapshot.identity}",
            ),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="unregistered-baseline-study-permit",
        )
        with self.assertRaisesRegex(TransitionError, "Decision anchor"):
            self.writer.open_study(
                study_id="STU-9018",
                question=unregistered_question,
                material_identity=OBSERVED_MATERIAL_ID,
                material_display_name="foundation observed material",
                semantic_proposal=unregistered_proposal,
                controlled_chassis=unregistered_chassis,
                portfolio_axis_id=axis.axis_id,
                portfolio_axis_identity=axis.identity,
                portfolio_decision_id=decision.identity,
                permit=unregistered_permit,
                operation_id="reject-unregistered-baseline-study-open",
            )
        old_model = next(
            component
            for component in baseline.components
            if component.protocol.startswith("model.")
        )
        equivalent_model = ComponentSpec(
            display_name="controlled refactored model",
            protocol=old_model.protocol,
            implementation="fixture.scientific.model.refactored",
            spec=old_model.specification(),
            semantic_dependencies=old_model.semantic_dependencies,
        )
        dimensions = sorted(
            dimension.value for dimension in ComponentParityDimension
        )
        fake_manifest = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "artifact_hashes": ["a" * 64],
                    "canonical_component_id": old_model.identity,
                    "dimensions": dimensions,
                    "equivalent_component_id": equivalent_model.identity,
                    "schema": "component_parity_result.v2",
                    "verdict": "equivalent",
                }
            )
        )
        fake_parity = ComponentParityEvidence(
            canonical_component=old_model,
            equivalent_component=equivalent_model,
            dimensions=tuple(ComponentParityDimension),
            parity_manifest_hash=fake_manifest.sha256,
            completion_record_id="f" * 64,
        )
        fake_chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=axis.changed_domains,
            controlled_domains=axis.controlled_domains,
            architecture=decision.architecture_chassis,
            equivalences=(fake_parity,),
        )
        fake_question = study_question("unvalidated component parity")
        fake_proposal = {"mechanism": "unvalidated component parity"}
        fake_hash = self.writer.study_input_hash(
            question=fake_question,
            material_identity=OBSERVED_MATERIAL_ID,
            semantic_proposal=fake_proposal,
            controlled_chassis=fake_chassis,
            portfolio_axis_id=axis.axis_id,
            portfolio_axis_identity=axis.identity,
            portfolio_decision_id=decision.identity,
        )
        fake_permit = self.writer.issue_permit(
            kind=PermitKind.STUDY,
            subject_kind=SubjectKind.INITIATIVE,
            subject_id="INI-DIRECTION",
            input_hash=fake_hash,
            actions=("open_study",),
            scope=(
                "study",
                f"decision:{decision.identity}",
                f"axis:{axis.identity}",
                f"baseline:{baseline.identity}",
                f"chassis:{decision.architecture_chassis.identity}",
                f"snapshot:{self.snapshot.identity}",
            ),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="unvalidated-parity-study-permit",
        )
        with self.assertRaisesRegex(TransitionError, "registered-validator"):
            self.writer.open_study(
                study_id="STU-9019",
                question=fake_question,
                material_identity=OBSERVED_MATERIAL_ID,
                material_display_name="foundation observed material",
                semantic_proposal=fake_proposal,
                controlled_chassis=fake_chassis,
                portfolio_axis_id=axis.axis_id,
                portfolio_axis_identity=axis.identity,
                portfolio_decision_id=decision.identity,
                permit=fake_permit,
                operation_id="reject-unvalidated-parity-study-open",
            )

        plan = self.writer.evidence.finalize(
            canonical_bytes({"schema": "component_parity_validation_plan.v1"})
        )
        parity_spec = job_spec(
            self.writer,
            {"kind": "Mission", "id": "MIS-DIRECTION"},
        )
        result_name = "evidence/component-parity-result"
        measurement_name = "evidence/component-parity-measurement"
        parity_spec["input_hashes"] = [
            *parity_spec["input_hashes"],
            plan.sha256,
            old_model.identity.removeprefix("component:"),
            equivalent_model.identity.removeprefix("component:"),
        ]
        parity_spec["expected_outputs"] = [result_name, measurement_name]
        parity_spec["output_classes"] = {
            result_name: "durable_evidence",
            measurement_name: "durable_evidence",
        }
        parity_spec["resume_action"] = "execute_portfolio_decision"
        parity_spec["component_parity_binding"] = {
            "architecture_chassis_identity": decision.architecture_chassis.identity,
            "canonical_component_id": old_model.identity,
            "canonical_component_manifest": old_model.to_identity_payload(),
            "dimensions": dimensions,
            "equivalent_component_id": equivalent_model.identity,
            "equivalent_component_manifest": equivalent_model.to_identity_payload(),
            "portfolio_axis_identity": axis.identity,
            "portfolio_decision_id": decision.identity,
            "portfolio_snapshot_id": self.snapshot.identity,
            "result_manifest_output": result_name,
            "validation_plan_hash": plan.sha256,
            "validator_id": ComponentParityFixtureValidator.validator_id,
        }
        unrelated_model = ComponentSpec(
            display_name="unrelated parity endpoint",
            protocol=old_model.protocol,
            implementation="fixture.scientific.model.unrelated",
            spec=old_model.specification(),
            semantic_dependencies=old_model.semantic_dependencies,
        )
        unrelated_spec = parse_canonical(canonical_bytes(parity_spec))
        assert isinstance(unrelated_spec, dict)
        unrelated_spec["input_hashes"] = [
            unrelated_model.identity.removeprefix("component:")
            if value == old_model.identity.removeprefix("component:")
            else value
            for value in unrelated_spec["input_hashes"]
        ]
        unrelated_binding = unrelated_spec["component_parity_binding"]
        assert isinstance(unrelated_binding, dict)
        unrelated_binding["canonical_component_id"] = unrelated_model.identity
        unrelated_binding[
            "canonical_component_manifest"
        ] = unrelated_model.to_identity_payload()
        with self.assertRaisesRegex(TransitionError, "outside the accepted baseline"):
            self.writer.declare_job(
                spec=unrelated_spec,
                operation_id="reject-unrelated-component-parity-endpoint",
            )
        declared = self.writer.declare_job(
            spec=parity_spec,
            operation_id="component-parity-job-declare",
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
            operation_id="component-parity-job-permit",
        )
        self.writer.start_job(
            permit=job_permit,
            operation_id="component-parity-job-start",
        )
        measurement = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "canonical_component_id": old_model.identity,
                    "dimensions": dimensions,
                    "equivalent": True,
                    "equivalent_component_id": equivalent_model.identity,
                    "schema": "component_parity_measurement.v1",
                }
            )
        )
        parity_manifest = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "architecture_chassis_identity": decision.architecture_chassis.identity,
                    "artifact_hashes": [measurement.sha256],
                    "canonical_component_id": old_model.identity,
                    "dimensions": dimensions,
                    "equivalent_component_id": equivalent_model.identity,
                    "job_hash": declared.result["job_hash"],
                    "job_id": declared.result["job_id"],
                    "mission_id": "MIS-DIRECTION",
                    "portfolio_axis_identity": axis.identity,
                    "portfolio_decision_id": decision.identity,
                    "portfolio_snapshot_id": self.snapshot.identity,
                    "schema": "component_parity_result.v2",
                    "verdict": "equivalent",
                }
            )
        )
        completed = self.writer.complete_job(
            outcome="success",
            output_manifest={
                result_name: parity_manifest.sha256,
                measurement_name: measurement.sha256,
            },
            operation_id="component-parity-job-complete",
        )
        self.writer.judge_job_evidence(
            completion_record_id=completed.result["completion_record_id"],
            disposition="accept_component_parity",
            operation_id="component-parity-job-accept",
        )
        with LocalIndex(self.writer.index_path) as index:
            parity_members = index.records_by_kind("component-parity-member")
        self.assertEqual(len(parity_members), 2)
        self.assertEqual(
            {record.subject for record in parity_members},
            {
                f"Component:{old_model.identity}",
                f"Component:{equivalent_model.identity}",
            },
        )
        refactored_baseline = ExecutableSpec(
            display_name="parity successor baseline",
            components=tuple(
                equivalent_model if component is old_model else component
                for component in baseline.components
            ),
            parameters=baseline.parameter_values(),
            data_contract=baseline.data_contract,
            split_contract=baseline.split_contract,
            clock_contract=baseline.clock_contract,
            cost_contract=baseline.cost_contract,
            engine_contract=baseline.engine_contract,
        )
        with LocalIndex(self.writer.index_path) as index:
            original_family = self.writer._resolved_architecture_family(
                index=index,
                architecture_payload=ArchitectureChassisSpec.from_executable(
                    baseline
                ).to_identity_payload(),
            )
            successor_family = self.writer._resolved_architecture_family(
                index=index,
                architecture_payload=ArchitectureChassisSpec.from_executable(
                    refactored_baseline
                ).to_identity_payload(),
            )
        self.assertEqual(original_family, successor_family)
        parity = ComponentParityEvidence(
            canonical_component=old_model,
            equivalent_component=equivalent_model,
            dimensions=tuple(ComponentParityDimension),
            parity_manifest_hash=parity_manifest.sha256,
            completion_record_id=completed.result["completion_record_id"],
        )
        assert axis.architecture_chassis is not None
        controlled_chassis = ControlledStudyChassis(
            baseline_executable=decision.baseline_executable,
            changed_domains=axis.changed_domains,
            controlled_domains=axis.controlled_domains,
            architecture=decision.architecture_chassis,
            equivalences=(parity,),
        )
        question = study_question("controlled identity parity")
        proposal = {"mechanism": "controlled identity parity"}
        study_hash = self.writer.study_input_hash(
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            semantic_proposal=proposal,
            controlled_chassis=controlled_chassis,
            portfolio_axis_id=axis.axis_id,
            portfolio_axis_identity=axis.identity,
            portfolio_decision_id=decision.identity,
        )
        permit = self.writer.issue_permit(
            kind=PermitKind.STUDY,
            subject_kind=SubjectKind.INITIATIVE,
            subject_id="INI-DIRECTION",
            input_hash=study_hash,
            actions=("open_study",),
            scope=(
                "study",
                f"decision:{decision.identity}",
                f"axis:{axis.identity}",
                f"baseline:{baseline.identity}",
                f"chassis:{decision.architecture_chassis.identity}",
                f"snapshot:{self.snapshot.identity}",
            ),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="controlled-identity-study-permit",
        )
        opened = self.writer.open_study(
            study_id="STU-9020",
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            material_display_name="foundation observed material",
            semantic_proposal=proposal,
            controlled_chassis=controlled_chassis,
            portfolio_axis_id=axis.axis_id,
            portfolio_axis_identity=axis.identity,
            portfolio_decision_id=decision.identity,
            permit=permit,
            operation_id="controlled-identity-study-open",
        )
        batch = batch_spec(
            batch_id="BAT-CONTROLLED-IDENTITY",
            study_id="STU-9020",
            study_hash=opened.result["study_hash"],
        )
        batch_permit = self.writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-9020",
            input_hash=batch.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id="controlled-identity-batch-permit",
        )
        self.writer.open_batch(
            batch_spec=batch,
            permit=batch_permit,
            operation_id="controlled-identity-batch-open",
        )
        baseline_calibration = next(
            component
            for component in baseline.components
            if component.protocol.startswith("calibration.")
        )
        changed_calibration = ComponentSpec(
            display_name="meaningfully changed calibration",
            protocol=baseline_calibration.protocol,
            implementation="fixture.scientific.calibration.changed",
            spec={
                **baseline_calibration.specification(),
                "scientific_change": "controlled-identity-test",
            },
            semantic_dependencies=baseline_calibration.semantic_dependencies,
        )
        candidate_components = tuple(
            equivalent_model
            if component is old_model
            else changed_calibration
            if component is baseline_calibration
            else component
            for component in baseline.components
        )
        candidate = ExecutableSpec(
            display_name="controlled parity candidate",
            components=candidate_components,
            parameters=baseline.parameter_values(),
            data_contract=baseline.data_contract,
            split_contract=baseline.split_contract,
            clock_contract=baseline.clock_contract,
            cost_contract=baseline.cost_contract,
            engine_contract=baseline.engine_contract,
        )
        counted = self.writer.register_trial(
            executable=candidate,
            operation_id="controlled-identity-trial",
        )
        self.assertEqual(counted.result["trial_delta"], 1)
        combination = self.writer.study_chassis_combination_identity(
            left_study_id="STU-9020",
            right_study_id="STU-9020",
            shared_domains=(ResearchLayer.MODEL,),
        )
        self.assertTrue(combination.startswith("chassis-combination:"))

        old_feature = next(
            component
            for component in candidate.components
            if component.protocol.startswith("calibration.")
        )
        bumped_feature = ComponentSpec(
            display_name="protocol-only bumped feature",
            protocol="calibration.scientific_boundary_fixture.v2",
            implementation=old_feature.implementation,
            spec=old_feature.specification(),
            semantic_dependencies=old_feature.semantic_dependencies,
        )
        drifted = ExecutableSpec(
            display_name="protocol drift candidate",
            components=tuple(
                bumped_feature if component is old_feature else component
                for component in candidate.components
            ),
            parameters=candidate.parameter_values(),
            data_contract=candidate.data_contract,
            split_contract=candidate.split_contract,
            clock_contract=candidate.clock_contract,
            cost_contract=candidate.cost_contract,
            engine_contract=candidate.engine_contract,
        )
        with self.assertRaisesRegex(
            TransitionError, "protocol-neutral Executable duplicate"
        ):
            self.writer.register_trial(
                executable=drifted,
                operation_id="reject-controlled-protocol-drift",
            )
        measurement_artifact = self.writer.evidence.verify(measurement.sha256)
        (
            self.writer.evidence._root / measurement_artifact.relative_path
        ).unlink()
        with self.assertRaisesRegex(TransitionError, "bytes are unavailable"):
            self.writer.study_chassis_combination_identity(
                left_study_id="STU-9020",
                right_study_id="STU-9020",
                shared_domains=(ResearchLayer.MODEL,),
            )

    def _run_unavailable_study(
        self,
        *,
        tag: str,
        study_id: str,
        target_index: int,
        decision: PortfolioDecision,
    ) -> None:
        self.writer.record_portfolio_decision(
            decision=decision,
            operation_id=f"{tag}-decision",
        )
        question = study_question(f"{tag} diagnosis")
        proposal = {"mechanism": f"{tag} unavailable contrast"}
        axis = self.axes[target_index]
        assert axis.architecture_chassis is not None
        controlled_chassis = ControlledStudyChassis(
            baseline_executable=decision.baseline_executable,
            changed_domains=axis.changed_domains,
            controlled_domains=axis.controlled_domains,
            architecture=axis.architecture_chassis,
        )
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
            subject_id="INI-DIRECTION",
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
            operation_id=f"{tag}-study-permit",
        )
        opened = self.writer.open_study(
            study_id=study_id,
            question=question,
            material_identity=OBSERVED_MATERIAL_ID,
            material_display_name="foundation observed material",
            semantic_proposal=proposal,
            controlled_chassis=controlled_chassis,
            portfolio_axis_id=axis.axis_id,
            portfolio_axis_identity=axis.identity,
            portfolio_decision_id=decision.identity,
            permit=study_permit,
            operation_id=f"{tag}-study-open",
        )
        batch = batch_spec(
            batch_id=f"BAT-{tag}",
            study_id=study_id,
            study_hash=opened.result["study_hash"],
        )
        batch_permit = self.writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id=study_id,
            input_hash=batch.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=FIXED_EXPIRY,
            one_shot=True,
            operation_id=f"{tag}-batch-permit",
        )
        self.writer.open_batch(
            batch_spec=batch,
            permit=batch_permit,
            operation_id=f"{tag}-batch-open",
        )
        self.writer.dispose_batch(
            outcome="not_evaluable",
            operation_id=f"{tag}-batch-close",
        )
        self.writer.close_study(
            outcome="not_evaluable",
            operation_id=f"{tag}-study-close",
        )
        with self.assertRaisesRegex(TransitionError, "cannot bypass"):
            self.writer.close_initiative(
                outcome="completed",
                operation_id=f"{tag}-reject-initiative-close-before-diagnosis",
            )
        with self.assertRaisesRegex(TransitionError, "cannot bypass"):
            self.writer.issue_permit(
                kind=PermitKind.STUDY,
                subject_kind=SubjectKind.INITIATIVE,
                subject_id="INI-DIRECTION",
                input_hash="f" * 64,
                actions=("open_study",),
                scope=("study",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id=f"{tag}-reject-permit-before-diagnosis",
            )
        record_fixture_study_diagnosis(
            self.writer,
            study_id=study_id,
            evidence_state=EvidenceState.NOT_IDENTIFIABLE,
            operation_id=f"{tag}-diagnosis",
        )

    def _reach_architecture_review(
        self,
        *,
        tag: str,
    ) -> tuple[dict[str, object], object]:
        for ordinal, target_index, action in (
            (1, 0, PortfolioAction.DEEPEN),
            (2, 1, PortfolioAction.CONTRAST),
            (3, 0, PortfolioAction.ROTATE),
        ):
            study_tag = f"{tag}-{ordinal}"
            self._run_unavailable_study(
                tag=study_tag,
                study_id=f"STU-{tag.upper()}-{ordinal}",
                target_index=target_index,
                decision=self._decision(
                    tag=f"{tag.upper()}-{ordinal}",
                    target_index=target_index,
                    action=action,
                ),
            )
        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["next_action"]["kind"], "review_architecture")
        with LocalIndex(self.writer.index_path) as index:
            trigger = index.get(
                "architecture-review-trigger",
                control["next_action"]["trigger_record_id"],
            )
        self.assertIsNotNone(trigger)
        assert trigger is not None
        return control, trigger

    def test_bounded_review_can_continue_an_exact_covered_existing_axis(self) -> None:
        control, trigger = self._reach_architecture_review(tag="bounded-existing")
        direction = ArchitectureContinuationDirection(
            mode=ArchitectureContinuationMode.EXISTING_AXIS,
            reviewed_architecture_family=self.axes[0].system_architecture_family,
            trigger_record_id=control["next_action"]["trigger_record_id"],
            covered_diagnosis_ids=tuple(trigger.payload["diagnosis_ids"]),
            target_axis_id=self.axes[0].axis_id,
            target_axis_identity=self.axes[0].identity,
        )
        review = ArchitectureReview(
            mission_id="MIS-DIRECTION",
            trigger_record_id=direction.trigger_record_id,
            system_architecture_family=direction.reviewed_architecture_family,
            conclusion=ArchitectureReviewConclusion.BOUNDED_SAME_ARCHITECTURE,
            rationale="the covered axis still has one causal bounded contrast",
            stop_or_reopen_condition="stop if the exact contrast remains unidentified",
            continuation_direction=direction,
        )
        self.writer.record_architecture_review(
            review=review,
            operation_id="bounded-existing-review",
        )
        action = self.writer.read_control()["next_action"]
        self.assertEqual(action["architecture_continuation_mode"], "existing_axis")
        self.assertEqual(
            action["required_architecture_family"],
            self.axes[0].system_architecture_family,
        )
        self.assertEqual(action["required_target_axis_ids"], [self.axes[0].axis_id])
        self.assertEqual(
            action["required_target_axis_identity"], self.axes[0].identity
        )
        recovered = self.writer.recover()
        self.assertFalse(recovered["control_repaired"])
        self.assertFalse(recovered["index_rebuilt"])
        self.assertEqual(self.writer.read_control()["next_action"], action)

        missing_basis = self._decision(
            tag="BOUNDED-EXISTING-MISSING-BASIS",
            target_index=0,
            action=PortfolioAction.DEEPEN,
        )
        assert missing_basis.quant_team_review is not None
        incomplete_review = QuantTeamDecisionReview(
            assessments=tuple(
                DecisionLensAssessment(
                    lens=assessment.lens,
                    position=assessment.position,
                    option_ids=assessment.option_ids,
                    basis_records=tuple(
                        basis
                        for basis in assessment.basis_records
                        if basis.kind
                        not in {
                            "architecture-review-trigger",
                            "study-diagnosis",
                        }
                    ),
                    finding=assessment.finding,
                )
                for assessment in missing_basis.quant_team_review.assessments
            ),
            claim_boundary=missing_basis.quant_team_review.claim_boundary,
            resolution_basis=missing_basis.quant_team_review.resolution_basis,
            disagreement_resolution=(
                missing_basis.quant_team_review.disagreement_resolution
            ),
        )
        incomplete = PortfolioDecision(
            decision_id="DEC-BOUNDED-EXISTING-INCOMPLETE-BASIS",
            chosen_option_id=missing_basis.chosen_option_id,
            options=missing_basis.options,
            rationale=missing_basis.rationale,
            commitment_batches=missing_basis.commitment_batches,
            quant_team_review=incomplete_review,
            baseline_executable=missing_basis.baseline_executable,
        )
        with self.assertRaisesRegex(TransitionError, "bounded architecture bases"):
            self.writer.record_portfolio_decision(
                decision=incomplete,
                operation_id="reject-bounded-incomplete-basis",
            )

        bypass = self._decision(
            tag="BOUNDED-EXISTING-BYPASS",
            target_index=1,
            action=PortfolioAction.CONTRAST,
        )
        with self.assertRaisesRegex(TransitionError, "exact bounded existing axis"):
            self.writer.record_portfolio_decision(
                decision=bypass,
                operation_id="reject-bounded-existing-bypass",
            )
        accepted = self._decision(
            tag="BOUNDED-EXISTING-ACCEPT",
            target_index=0,
            action=PortfolioAction.DEEPEN,
        )
        self.writer.record_portfolio_decision(
            decision=accepted,
            operation_id="accept-bounded-covered-axis",
        )
        with LocalIndex(self.writer.index_path) as index:
            accepted_record = index.get("portfolio-decision", accepted.identity)
        assert accepted_record is not None
        self.assertEqual(
            accepted_record.payload["scheduler_constraints"],
            {
                key: action[key]
                for key in (
                    "architecture_continuation_mode",
                    "architecture_review_id",
                    "architecture_review_trigger_id",
                    "constraint_source_id",
                    "covered_diagnosis_ids",
                    "required_architecture_family",
                    "required_target_axis_identity",
                    "required_target_axis_ids",
                )
            },
        )
        self.assertEqual(
            self.writer.read_control()["next_action"]["kind"],
            "execute_portfolio_decision",
        )
        assert accepted.baseline_executable is not None
        canonical_execution = next(
            component
            for component in accepted.baseline_executable.components
            if component.protocol.startswith("execution.")
        )
        alternate_baseline = portfolio_axis_baseline(self.axes[2])
        alternate_execution = next(
            component
            for component in alternate_baseline.components
            if component.protocol.startswith("execution.")
        )
        self._accept_component_parity_for_decision(
            decision=accepted,
            canonical_component=canonical_execution,
            equivalent_component=alternate_execution,
            tag="bounded-existing-parity",
        )
        rerouted = self.writer.read_control()["next_action"]
        self.assertEqual(rerouted["kind"], "portfolio_decision")
        self.assertEqual(
            rerouted["architecture_continuation_mode"], "existing_axis"
        )
        self.assertEqual(
            rerouted["covered_diagnosis_ids"], list(direction.covered_diagnosis_ids)
        )
        self.assertEqual(
            rerouted["required_architecture_family"],
            direction.reviewed_architecture_family,
        )

    def test_bounded_review_admits_new_mechanism_in_exact_layer_and_family(
        self,
    ) -> None:
        control, trigger = self._reach_architecture_review(tag="bounded-new")
        direction = ArchitectureContinuationDirection(
            mode=ArchitectureContinuationMode.NEW_MECHANISM,
            reviewed_architecture_family=self.axes[0].system_architecture_family,
            trigger_record_id=control["next_action"]["trigger_record_id"],
            covered_diagnosis_ids=tuple(trigger.payload["diagnosis_ids"]),
            required_research_layer=ResearchLayer.MODEL,
        )
        review = ArchitectureReview(
            mission_id="MIS-DIRECTION",
            trigger_record_id=direction.trigger_record_id,
            system_architecture_family=direction.reviewed_architecture_family,
            conclusion=ArchitectureReviewConclusion.BOUNDED_SAME_ARCHITECTURE,
            rationale="the architecture remains useful for one distinct model mechanism",
            stop_or_reopen_condition="stop if the model mechanism adds no information",
            continuation_direction=direction,
        )
        self.writer.record_architecture_review(
            review=review,
            operation_id="bounded-new-review",
        )
        admit_options = (
            DecisionOption(
                option_id="admit-bounded-model",
                action=PortfolioAction.NEW_MECHANISM,
                target_id=self.axes[0].axis_id,
                expected_information_value="positive",
                opportunity_cost="one bounded model contrast",
            ),
            DecisionOption(
                option_id="defer-alternate-family",
                action=PortfolioAction.ROTATE,
                target_id=self.axes[2].axis_id,
                expected_information_value="positive",
                opportunity_cost="deferred",
                omission_reason="the expert-bound same-family mechanism is tested first",
            ),
        )
        admit = PortfolioDecision(
            decision_id="DEC-BOUNDED-NEW-MECHANISM",
            chosen_option_id="admit-bounded-model",
            options=admit_options,
            rationale="admit one distinct model mechanism under the reviewed family",
            commitment_batches=1,
            quant_team_review=self._quant_team_review(
                options=admit_options,
                chosen_option_id="admit-bounded-model",
            ),
        )
        self.writer.record_portfolio_decision(
            decision=admit,
            operation_id="bounded-new-decision",
        )
        snapshot_action = self.writer.read_control()["next_action"]
        self.assertEqual(snapshot_action["kind"], "record_portfolio_snapshot")
        self.assertEqual(snapshot_action["required_followup_layers"], ["model"])
        self.assertEqual(
            snapshot_action["required_architecture_family"],
            self.axes[0].system_architecture_family,
        )

        common_chassis = self.axes[0].architecture_chassis
        assert common_chassis is not None
        controlled = tuple(
            layer
            for layer in (
                ResearchLayer.FEATURE,
                ResearchLayer.LABEL,
                ResearchLayer.CALIBRATION,
                ResearchLayer.SELECTOR,
                ResearchLayer.TRADE,
                ResearchLayer.LIFECYCLE,
                ResearchLayer.RISK,
                ResearchLayer.EXECUTION,
            )
            if layer is not ResearchLayer.MODEL
        )
        alternate_chassis = self.axes[2].architecture_chassis
        assert alternate_chassis is not None
        wrong_family_axis = _PortfolioAxis(
            axis_id="direction-axis-bounded-wrong-family",
            causal_question="Does an out-of-family model mechanism bypass the review?",
            mechanism_family="direction-family-bounded-wrong-family",
            primary_research_layer=ResearchLayer.MODEL,
            system_architecture_family=alternate_chassis.identity,
            changed_domains=(ResearchLayer.MODEL,),
            controlled_domains=controlled,
            why_now="this fixture must be rejected by the exact family constraint",
            stop_or_reopen_condition="stop immediately at the family boundary",
            architecture_chassis=alternate_chassis,
        )
        wrong_family_snapshot = PortfolioSnapshot(
            mission_id="MIS-DIRECTION",
            axes=(*self.axes, wrong_family_axis),
            opportunity_cost_basis="reject an architecture-review bypass",
            research_intake_id=self.intake.identity,
            exhaustion_standard=self.snapshot.exhaustion_standard_value(),
        )
        with self.assertRaisesRegex(
            TransitionError,
            "bounded architecture direction",
        ):
            self.writer.record_portfolio_snapshot(
                snapshot=wrong_family_snapshot,
                operation_id="reject-bounded-wrong-family",
            )
        model_axis = _PortfolioAxis(
            axis_id="direction-axis-bounded-model",
            causal_question="Does a distinct model mechanism resolve the reviewed gaps?",
            mechanism_family="direction-family-bounded-model",
            primary_research_layer=ResearchLayer.MODEL,
            system_architecture_family=common_chassis.identity,
            changed_domains=(ResearchLayer.MODEL,),
            controlled_domains=controlled,
            why_now="the typed architecture review selected this bounded mechanism",
            stop_or_reopen_condition="stop if the exact mechanism remains unidentified",
            architecture_chassis=common_chassis,
        )
        bounded_snapshot = PortfolioSnapshot(
            mission_id="MIS-DIRECTION",
            axes=(*self.axes, model_axis),
            opportunity_cost_basis="one same-family model mechanism before rotation",
            research_intake_id=self.intake.identity,
            exhaustion_standard=self.snapshot.exhaustion_standard_value(),
        )
        self.writer.record_portfolio_snapshot(
            snapshot=bounded_snapshot,
            operation_id="bounded-new-snapshot",
        )
        decision_action = self.writer.read_control()["next_action"]
        self.assertEqual(
            decision_action["required_target_axis_ids"],
            [model_axis.axis_id],
        )
        self.assertEqual(
            decision_action["architecture_continuation_mode"],
            "new_mechanism",
        )
        execute_options = (
            DecisionOption(
                option_id="execute-bounded-model",
                action=PortfolioAction.CONTRAST,
                target_id=model_axis.axis_id,
                expected_information_value="positive",
                opportunity_cost="one bounded Batch",
            ),
            DecisionOption(
                option_id="retain-alternate-family",
                action=PortfolioAction.ROTATE,
                target_id=self.axes[2].axis_id,
                expected_information_value="positive",
                opportunity_cost="deferred",
                omission_reason="the newly admitted mechanism receives its first test",
            ),
        )
        execute = PortfolioDecision(
            decision_id="DEC-BOUNDED-EXECUTE-MODEL",
            chosen_option_id="execute-bounded-model",
            options=execute_options,
            rationale="execute the exact materialized architecture continuation",
            commitment_batches=1,
            quant_team_review=self._quant_team_review(
                options=execute_options,
                chosen_option_id="execute-bounded-model",
            ),
            baseline_executable=portfolio_axis_baseline(model_axis),
        )
        self.writer.record_portfolio_decision(
            decision=execute,
            operation_id="bounded-execute-model",
        )
        self.assertEqual(
            self.writer.read_control()["next_action"]["target_id"],
            model_axis.axis_id,
        )

    def test_repeated_architecture_gap_forces_review_and_rotation(self) -> None:
        self.assertNotEqual(self.axes[0].axis_id, self.axes[1].axis_id)
        self.assertNotEqual(
            self.axes[0].mechanism_family, self.axes[1].mechanism_family
        )
        self.assertEqual(
            self.axes[0].system_architecture_family,
            self.axes[1].system_architecture_family,
        )
        first = self._decision(
            tag="FIRST",
            target_index=0,
            action=PortfolioAction.DEEPEN,
        )
        self._run_unavailable_study(
            tag="direction-first",
            study_id="STU-9001",
            target_index=0,
            decision=first,
        )
        second = self._decision(
            tag="SECOND",
            target_index=1,
            action=PortfolioAction.CONTRAST,
        )
        self._run_unavailable_study(
            tag="direction-second",
            study_id="STU-9002",
            target_index=1,
            decision=second,
        )
        exact_combination = self.writer.study_chassis_combination_identity(
            left_study_id="STU-9001",
            right_study_id="STU-9002",
            shared_domains=(ResearchLayer.MODEL, ResearchLayer.EXECUTION),
        )
        self.assertTrue(exact_combination.startswith("chassis-combination:"))
        third = self._decision(
            tag="THIRD",
            target_index=0,
            action=PortfolioAction.ROTATE,
        )
        self._run_unavailable_study(
            tag="direction-third",
            study_id="STU-9003",
            target_index=0,
            decision=third,
        )
        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["next_action"]["kind"], "review_architecture")
        review = ArchitectureReview(
            mission_id="MIS-DIRECTION",
            trigger_record_id=control["next_action"]["trigger_record_id"],
            system_architecture_family=self.axes[0].system_architecture_family,
            conclusion=ArchitectureReviewConclusion.ROTATE_ARCHITECTURE,
            rationale="three gaps across two axes make another same-chassis pass low value",
            stop_or_reopen_condition="reopen only after changed architecture evidence",
        )
        stale_review = ArchitectureReview(
            mission_id="MIS-DIRECTION",
            trigger_record_id="0" * 64,
            system_architecture_family=self.axes[0].system_architecture_family,
            conclusion=ArchitectureReviewConclusion.ROTATE_ARCHITECTURE,
            rationale="three gaps across two axes make another same-chassis pass low value",
            stop_or_reopen_condition="reopen only after changed architecture evidence",
        )
        self.assertNotEqual(stale_review.identity, review.identity)
        with self.assertRaisesRegex(TransitionError, "trigger is absent or stale"):
            self.writer.record_architecture_review(
                review=stale_review,
                operation_id="reject-stale-architecture-review-trigger",
            )
        self.writer.record_architecture_review(
            review=review,
            operation_id="direction-architecture-review",
        )
        invalid = self._decision(
            tag="INVALID-SAME-ARCH",
            target_index=0,
            action=PortfolioAction.ROTATE,
        )
        with self.assertRaisesRegex(TransitionError, "did not rotate"):
            self.writer.record_portfolio_decision(
                decision=invalid,
                operation_id="reject-same-architecture-after-review",
            )
        valid = self._decision(
            tag="VALID-NEW-ARCH",
            target_index=2,
            action=PortfolioAction.ROTATE,
        )
        self.writer.record_portfolio_decision(
            decision=valid,
            operation_id="accept-new-architecture-after-review",
        )
        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["next_action"]["kind"], "execute_portfolio_decision")
        self.assertEqual(control["next_action"]["target_id"], self.axes[2].axis_id)
        assert valid.baseline_executable is not None
        reviewed_baseline = portfolio_axis_baseline(self.axes[0])
        canonical_execution = next(
            component
            for component in valid.baseline_executable.components
            if component.protocol.startswith("execution.")
        )
        reviewed_execution = next(
            component
            for component in reviewed_baseline.components
            if component.protocol.startswith("execution.")
        )
        self._accept_component_parity_for_decision(
            decision=valid,
            canonical_component=canonical_execution,
            equivalent_component=reviewed_execution,
            tag="review-collapse",
        )
        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["next_action"]["kind"], "portfolio_decision")
        self.assertEqual(
            control["next_action"]["architecture_review_id"], review.identity
        )
        self.assertIn("excluded_architecture_family", control["next_action"])

    def test_parity_collapse_rechecks_architecture_review_threshold(self) -> None:
        studies = (
            ("collapse-first", "STU-9031", 0, PortfolioAction.DEEPEN),
            ("collapse-second", "STU-9032", 2, PortfolioAction.ROTATE),
            ("collapse-third", "STU-9033", 0, PortfolioAction.CONTRAST),
        )
        for tag, study_id, target_index, action in studies:
            self._run_unavailable_study(
                tag=tag,
                study_id=study_id,
                target_index=target_index,
                decision=self._decision(
                    tag=tag.upper(),
                    target_index=target_index,
                    action=action,
                ),
            )
            control = self.writer.read_control()
            assert control is not None
            self.assertEqual(control["next_action"]["kind"], "portfolio_decision")

        decision = self._decision(
            tag="COLLAPSE-PARITY",
            target_index=2,
            action=PortfolioAction.ROTATE,
        )
        self.writer.record_portfolio_decision(
            decision=decision,
            operation_id="collapse-parity-decision",
        )
        assert decision.baseline_executable is not None
        common_baseline = portfolio_axis_baseline(self.axes[0])
        canonical_execution = next(
            component
            for component in decision.baseline_executable.components
            if component.protocol.startswith("execution.")
        )
        common_execution = next(
            component
            for component in common_baseline.components
            if component.protocol.startswith("execution.")
        )
        self._accept_component_parity_for_decision(
            decision=decision,
            canonical_component=canonical_execution,
            equivalent_component=common_execution,
            tag="threshold-collapse",
        )
        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["next_action"]["kind"], "review_architecture")
        with LocalIndex(self.writer.index_path) as index:
            trigger = index.get(
                "architecture-review-trigger",
                control["next_action"]["trigger_record_id"],
            )
        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertEqual(len(trigger.payload["diagnosis_ids"]), 3)
        self.assertEqual(len(trigger.payload["portfolio_axis_ids"]), 2)

    def test_diagnosis_constrains_new_axis_and_forces_its_first_decision(self) -> None:
        first = self._decision(
            tag="NEW-AXIS-BASELINE",
            target_index=0,
            action=PortfolioAction.DEEPEN,
        )
        self._run_unavailable_study(
            tag="direction-new-axis-baseline",
            study_id="STU-9011",
            target_index=0,
            decision=first,
        )
        admit_options = (
                DecisionOption(
                    option_id="admit-label",
                    action=PortfolioAction.NEW_MECHANISM,
                    target_id=self.axes[0].axis_id,
                    expected_information_value="positive",
                    opportunity_cost="one bounded label contrast",
                ),
                DecisionOption(
                    option_id="rotate-c",
                    action=PortfolioAction.ROTATE,
                    target_id=self.axes[2].axis_id,
                    expected_information_value="positive",
                    opportunity_cost="deferred",
                    omission_reason="the diagnosis-authorized label contrast comes first",
                ),
            )
        admit = PortfolioDecision(
            decision_id="DEC-DIRECTION-ADMIT-LABEL",
            chosen_option_id="admit-label",
            options=admit_options,
            rationale="admit the layer identified by the not-identifiable diagnosis",
            commitment_batches=1,
            quant_team_review=self._quant_team_review(
                options=admit_options,
                chosen_option_id="admit-label",
            ),
        )
        self.writer.record_portfolio_decision(
            decision=admit,
            operation_id="direction-admit-label-decision",
        )

        def new_axis(axis_id: str, layer: ResearchLayer) -> _PortfolioAxis:
            chassis = architecture_chassis(f"{layer.value}-followup")
            return _PortfolioAxis(
                axis_id=axis_id,
                causal_question=f"Does the {layer.value} contrast resolve identifiability?",
                mechanism_family=f"direction-{layer.value}-followup",
                primary_research_layer=layer,
                system_architecture_family=chassis.identity,
                changed_domains=(layer,),
                controlled_domains=tuple(
                    candidate
                    for candidate in (
                        ResearchLayer.FEATURE,
                        ResearchLayer.LABEL,
                        ResearchLayer.MODEL,
                        ResearchLayer.TRADE,
                        ResearchLayer.LIFECYCLE,
                        ResearchLayer.EXECUTION,
                    )
                    if candidate != layer
                ),
                why_now="the prior diagnosis identified a bounded follow-up layer",
                stop_or_reopen_condition="stop if the causal contrast remains unidentified",
                architecture_chassis=chassis,
            )

        invalid_axis = new_axis("direction-axis-model-followup", ResearchLayer.MODEL)
        invalid_snapshot = PortfolioSnapshot(
            mission_id="MIS-DIRECTION",
            axes=(*self.axes, invalid_axis),
            opportunity_cost_basis="reject a layer outside the diagnosis branch",
            research_intake_id=self.intake.identity,
            exhaustion_standard=self.snapshot.exhaustion_standard_value(),
        )
        with self.assertRaisesRegex(TransitionError, "does not satisfy"):
            self.writer.record_portfolio_snapshot(
                snapshot=invalid_snapshot,
                operation_id="reject-direction-model-followup",
            )

        label_axis = new_axis("direction-axis-label-followup", ResearchLayer.LABEL)
        label_snapshot = PortfolioSnapshot(
            mission_id="MIS-DIRECTION",
            axes=(*self.axes, label_axis),
            opportunity_cost_basis="admit the diagnosis-authorized label contrast",
            research_intake_id=self.intake.identity,
            exhaustion_standard=self.snapshot.exhaustion_standard_value(),
        )
        self.writer.record_portfolio_snapshot(
            snapshot=label_snapshot,
            operation_id="accept-direction-label-followup",
        )
        bypass = self._decision(
            tag="BYPASS-ADMITTED-LABEL",
            target_index=1,
            action=PortfolioAction.CONTRAST,
        )
        with self.assertRaisesRegex(TransitionError, "admitted constrained axis"):
            self.writer.record_portfolio_decision(
                decision=bypass,
                operation_id="reject-bypass-admitted-label",
            )
        execute_label_options = (
                DecisionOption(
                    option_id="execute-label",
                    action=PortfolioAction.CONTRAST,
                    target_id=label_axis.axis_id,
                    expected_information_value="positive",
                    opportunity_cost="one bounded Batch",
                ),
                DecisionOption(
                    option_id="retain-c",
                    action=PortfolioAction.ROTATE,
                    target_id=self.axes[2].axis_id,
                    expected_information_value="positive",
                    opportunity_cost="deferred",
                    omission_reason="the newly admitted axis must receive its first test",
                ),
            )
        execute_label = PortfolioDecision(
            decision_id="DEC-DIRECTION-EXECUTE-LABEL",
            chosen_option_id="execute-label",
            options=execute_label_options,
            rationale="execute the exact newly admitted diagnosis branch",
            commitment_batches=1,
            quant_team_review=self._quant_team_review(
                options=execute_label_options,
                chosen_option_id="execute-label",
            ),
            baseline_executable=portfolio_axis_baseline(label_axis),
        )
        self.writer.record_portfolio_decision(
            decision=execute_label,
            operation_id="execute-direction-label-followup",
        )
        control = self.writer.read_control()
        assert control is not None
        self.assertEqual(control["next_action"]["target_id"], label_axis.axis_id)


if __name__ == "__main__":
    unittest.main()
