"""Run one preregistered same-sleeve realized-loss risk contrast.

The operation is intentionally prospective.  ``build_design`` reads only the
Foundation material identity, fold calendar, current Portfolio, and durable
diagnoses.  No trade or performance value is computed until both exact family
members have been registered and the first Job has entered its Writer-bound
execution context.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SOURCE_ROOT))

from axiom_rift.core.canonical import canonical_bytes  # noqa: E402
from axiom_rift.core.component_surface import (  # noqa: E402
    COMPONENT_SURFACE_ARCHITECTURE_ROLE,
)
from axiom_rift.core.identity import ExecutableSpec  # noqa: E402
from axiom_rift.operations.permits import (  # noqa: E402
    Permit,
    PermitAuthority,
    PermitKeyStore,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.prospective_job_materialization import (  # noqa: E402
    materialize_prospective_job_implementation,
    prospective_job_implementation_sha256,
)
from axiom_rift.operations.running_job import RunningJobExecution  # noqa: E402
from axiom_rift.operations.validation import (  # noqa: E402
    EvidenceValidatorRegistry,
)
from axiom_rift.operations.writer import (  # noqa: E402
    StateWriter,
)
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID  # noqa: E402
from axiom_rift.research.governance import ResearchLayer  # noqa: E402
from axiom_rift.research.portfolio import (  # noqa: E402
    BatchSpec,
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
    DecisionBasisRecord,
    DecisionLens,
    DecisionLensAssessment,
    DecisionLensPosition,
    DecisionOption,
    PortfolioAction,
    PortfolioAxis,
    PortfolioDecision,
    PortfolioSnapshot,
    QuantTeamDecisionReview,
)
from axiom_rift.research.portfolio_projection import (  # noqa: E402
    architecture_surfaces_from_axis_projection,
    component_surface_registry,
    portfolio_axes_from_projection,
)
from axiom_rift.research.prospective_pair_trace import (  # noqa: E402
    PROSPECTIVE_PAIR_EVIDENCE_MODES,
)
from axiom_rift.research.sleeve_loss_skip_risk_chassis import (  # noqa: E402
    sleeve_loss_skip_risk_configurations,
    sleeve_loss_skip_risk_controlled_chassis,
    sleeve_loss_skip_risk_executable,
)
from axiom_rift.research.sleeve_loss_skip_risk_runtime import (  # noqa: E402
    CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL,
    execute_sleeve_loss_skip_risk_job,
    sleeve_loss_skip_risk_runtime_path,
)
from axiom_rift.research.sleeve_loss_skip_risk_study import (  # noqa: E402
    SleeveLossSkipRiskJobPlan,
    build_sleeve_loss_skip_risk_job_plan,
)
from axiom_rift.research.semantic_question import (  # noqa: E402
    SemanticQuestionLineageProposal,
)
from axiom_rift.research.trials import NegativeMemory  # noqa: E402
from axiom_rift.research.validation_v2 import (  # noqa: E402
    ScientificAdjudicationValidatorV2,
)


MISSION_ID = "MIS-0006"
INITIATIVE_ID = "INI-0025"
STUDY_ID = "STU-0122"
BATCH_DISPLAY_ID = "BAT-0122"
BASE_SNAPSHOT_ID = (
    "portfolio:083c52d62b53de26c18d04372ebd84fca6942d5e27710a72e7bd591c325e20f5"
)
SOURCE_AXIS_ID = "axis-cost-aware-execution"
ALTERNATE_AXIS_ID = "axis-p0-composite-audit-reanalysis"
NEW_AXIS_ID = "axis-sleeve-realized-loss-skip-risk"
MECHANISM_FAMILY = "sleeve_realized_loss_skip_risk"
SOURCE_DIAGNOSIS_ID = (
    "diagnosis:2de6bb8800c0bf098447eded5e0324e236deb4d043dc4fa3cf99471072d94d06"
)
MONTHLY_LOCK_DIAGNOSIS_ID = (
    "diagnosis:c3e0f3d73fd056af41ea4dcc5f3ddf335439e61fcf2d86a62b90ce8c211795c7"
)
POSITIVE_SLEEVE_DIAGNOSIS_ID = (
    "diagnosis:d085ff876416d1ab136a7113600dae4eae0c145374b6d466b42294b86ca06b2c"
)
OPERATION_PREFIX = "goal-audit-sleeve-loss-skip-risk-v1-"
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"


@dataclass(frozen=True, slots=True)
class StudyMember:
    label: str
    executable: ExecutableSpec
    job_plan: SleeveLossSkipRiskJobPlan


@dataclass(frozen=True, slots=True)
class StudyRunBinding:
    study_id: str
    initiative_id: str
    operation_prefix: str
    permit_expiry_utc: str
    portfolio_snapshot_id: str
    study_permit_suffix: str
    superseded_operation_suffixes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StudyDesign:
    binding: StudyRunBinding
    prior_axes: tuple[PortfolioAxis, ...]
    axis: PortfolioAxis
    structural_decision: PortfolioDecision | None
    expanded_snapshot: PortfolioSnapshot
    work_decision: PortfolioDecision
    question: Mapping[str, Any]
    proposal: Mapping[str, Any]
    batch_spec: BatchSpec
    members: tuple[StudyMember, ...]
    semantic_question_lineage: SemanticQuestionLineageProposal | None

    @property
    def control(self) -> StudyMember:
        return self.members[0]

    @property
    def subject(self) -> StudyMember:
        return self.members[1]


def _basis(*values: tuple[str, str]) -> tuple[DecisionBasisRecord, ...]:
    return tuple(
        DecisionBasisRecord(kind=kind, record_id=record_id)
        for kind, record_id in sorted(set(values))
    )


def _current_snapshot_axes(
    writer: StateWriter,
) -> tuple[tuple[PortfolioAxis, ...], Mapping[str, Any]]:
    with writer.open_stable_index() as (control, index):
        if (
            control["scientific"]["active_mission"] != MISSION_ID
            or control["scientific"]["active_initiative"] != INITIATIVE_ID
        ):
            raise RuntimeError("loss-skip Study Mission or Initiative drifted")
        snapshot = index.get("portfolio-snapshot", BASE_SNAPSHOT_ID)
        if snapshot is None:
            raise RuntimeError("loss-skip base Portfolio snapshot is absent")
        raw_axes = snapshot.payload.get("axes")
        if not isinstance(raw_axes, list) or any(
            not isinstance(axis, Mapping) for axis in raw_axes
        ):
            raise RuntimeError("loss-skip base Portfolio axes are malformed")
        required_surfaces = architecture_surfaces_from_axis_projection(raw_axes)
        payloads = tuple(
            record.payload
            for record in index.component_manifests_by_surfaces(
                COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                required_surfaces,
            )
        )
        prior_axes = portfolio_axes_from_projection(
            raw_axes,
            component_surface_registry(payloads),
        )
        for kind, record_id in (
            ("study-diagnosis", SOURCE_DIAGNOSIS_ID),
            ("study-diagnosis", MONTHLY_LOCK_DIAGNOSIS_ID),
            ("study-diagnosis", POSITIVE_SLEEVE_DIAGNOSIS_ID),
        ):
            if index.get(kind, record_id) is None:
                raise RuntimeError("loss-skip durable diagnosis basis is absent")
        return prior_axes, snapshot.payload


def build_design(writer: StateWriter) -> StudyDesign:
    prior_axes, snapshot_payload = _current_snapshot_axes(writer)
    by_id = {axis.axis_id: axis for axis in prior_axes}
    if NEW_AXIS_ID in by_id:
        raise RuntimeError("loss-skip axis already predates this operation")
    if SOURCE_AXIS_ID not in by_id or ALTERNATE_AXIS_ID not in by_id:
        raise RuntimeError("loss-skip allocation axes are absent")

    chassis = sleeve_loss_skip_risk_controlled_chassis()
    configurations = sleeve_loss_skip_risk_configurations()
    executables = tuple(sleeve_loss_skip_risk_executable(item) for item in configurations)
    definition_plan = build_sleeve_loss_skip_risk_job_plan(
        repository_root=ROOT,
        mission_id=MISSION_ID,
        study_id=STUDY_ID,
        executable_id=executables[0].identity,
    )
    definition = definition_plan.definition
    if tuple(item.identity for item in executables) != (
        definition.prospective_executable_ids
    ):
        raise RuntimeError("loss-skip Executable family identity drifted")
    if executables[0].identity != chassis.baseline_executable.identity:
        raise RuntimeError("loss-skip control is not the exact prior baseline")

    axis = PortfolioAxis(
        axis_id=NEW_AXIS_ID,
        causal_question=(
            "Does skipping exactly the next otherwise eligible same-sleeve entry "
            "after a realized native-net loss reduce loss clustering and monthly "
            "drawdown without destroying after-cost activity and utility?"
        ),
        mechanism_family=MECHANISM_FAMILY,
        primary_research_layer=ResearchLayer.PORTFOLIO,
        system_architecture_family=chassis.architecture.identity,
        changed_domains=chassis.changed_domains,
        controlled_domains=chassis.controlled_domains,
        why_now=(
            "STU-0089 retained a positive-sleeve frontier but diagnosed concentration, "
            "while STU-0082 showed that a calendar-wide monthly lock collapsed activity; "
            "one causal same-sleeve event response isolates the risk timing mechanism."
        ),
        stop_or_reopen_condition=(
            "Stop after the exact two-member discovery contrast; reopen only for a "
            "preregistered distinct loss-state mechanism, new material, or confirmation."
        ),
        architecture_chassis=chassis.architecture,
    )
    structural_basis = _basis(
        ("portfolio-snapshot", BASE_SNAPSHOT_ID),
        ("study-diagnosis", MONTHLY_LOCK_DIAGNOSIS_ID),
        ("study-diagnosis", POSITIVE_SLEEVE_DIAGNOSIS_ID),
        ("study-diagnosis", SOURCE_DIAGNOSIS_ID),
    )
    structural_options = (
        DecisionOption(
            option_id="add-loss-skip-risk-axis",
            action=PortfolioAction.NEW_MECHANISM,
            target_id=SOURCE_AXIS_ID,
            expected_information_value=(
                "identify whether realized same-sleeve loss state carries bounded "
                "portfolio-risk information"
            ),
            opportunity_cost="one frozen two-member discovery Batch",
        ),
        DecisionOption(
            option_id="rotate-independent-forest",
            action=PortfolioAction.ROTATE,
            target_id=ALTERNATE_AXIS_ID,
            expected_information_value=(
                "advance another independent open forest branch"
            ),
            opportunity_cost=(
                "leave the positive-sleeve concentration mechanism untested"
            ),
            omission_reason=(
                "the loss-state contrast is uniquely low-dimensional and directly "
                "authorized by the retained sleeve and failed-lock diagnoses"
            ),
        ),
    )
    structural_review = QuantTeamDecisionReview(
        assessments=(
            DecisionLensAssessment(
                lens=DecisionLens.ARCHITECTURE,
                position=DecisionLensPosition.SUPPORT,
                option_ids=(
                    "add-loss-skip-risk-axis",
                    "rotate-independent-forest",
                ),
                basis_records=structural_basis,
                finding=(
                    "the proposed branch reuses the exact signal chassis and changes "
                    "only portfolio and risk state"
                ),
            ),
            DecisionLensAssessment(
                lens=DecisionLens.CAUSALITY,
                position=DecisionLensPosition.SUPPORT,
                option_ids=(
                    "add-loss-skip-risk-axis",
                    "rotate-independent-forest",
                ),
                basis_records=structural_basis,
                finding=(
                    "a realized prior same-sleeve exit precedes the one-entry response "
                    "and isolates it from the failed calendar-wide lock"
                ),
            ),
            DecisionLensAssessment(
                lens=DecisionLens.RISK,
                position=DecisionLensPosition.UNCERTAIN,
                option_ids=("add-loss-skip-risk-axis",),
                basis_records=structural_basis,
                finding=(
                    "even one skipped entry can reduce activity, so drawdown and "
                    "activity must remain claim-separated diagnostics"
                ),
            ),
        ),
        claim_boundary="allocation only; no scientific, candidate, or terminal claim",
        resolution_basis=(
            "use one concurrent fixed pair with no threshold, window, or tuning grid"
        ),
        disagreement_resolution=(
            "retain activity as an independent component claim and stop after one Batch"
        ),
    )
    structural_decision = PortfolioDecision(
        decision_id="DEC-SLEEVE-LOSS-SKIP-RISK-STRUCTURE",
        chosen_option_id="add-loss-skip-risk-axis",
        options=structural_options,
        rationale=(
            "add one distinct portfolio-risk branch while preserving every existing "
            "forest axis and one live independent rotation option"
        ),
        commitment_batches=1,
        quant_team_review=structural_review,
        proposed_axis=axis,
    )
    expanded_snapshot = PortfolioSnapshot(
        mission_id=MISSION_ID,
        axes=(*prior_axes, axis),
        opportunity_cost_basis=(
            "retain the entire current forest and spend one bounded pair on the "
            "lowest-dimensional causal response to retained sleeve concentration"
        ),
        research_intake_id=snapshot_payload.get("research_intake_id"),
        exhaustion_standard=snapshot_payload.get("exhaustion_standard"),
    )

    work_basis = _basis(
        ("portfolio-decision", structural_decision.identity),
        ("portfolio-snapshot", expanded_snapshot.identity),
        ("study-diagnosis", MONTHLY_LOCK_DIAGNOSIS_ID),
        ("study-diagnosis", POSITIVE_SLEEVE_DIAGNOSIS_ID),
    )
    work_decision = PortfolioDecision(
        decision_id="DEC-SLEEVE-LOSS-SKIP-RISK-WORK",
        chosen_option_id="run-loss-skip-pair",
        options=(
            DecisionOption(
                option_id="rotate-independent-forest",
                action=PortfolioAction.ROTATE,
                target_id=ALTERNATE_AXIS_ID,
                expected_information_value="advance a distinct open forest branch",
                opportunity_cost="defer the exact realized-loss causal contrast",
                omission_reason=(
                    "the frozen pair is cheaper and more identifiable than another "
                    "structural allocation"
                ),
            ),
            DecisionOption(
                option_id="run-loss-skip-pair",
                action=PortfolioAction.CONTRAST,
                target_id=NEW_AXIS_ID,
                expected_information_value=(
                    "one exact causal, economic, temporal, and risk comparison"
                ),
                opportunity_cost="two member Jobs and one bounded Batch",
            ),
        ),
        rationale=(
            "compare the exact prior unrestricted control with one no-tuning causal "
            "risk policy before any result is observed"
        ),
        commitment_batches=1,
        quant_team_review=QuantTeamDecisionReview(
            assessments=(
                DecisionLensAssessment(
                    lens=DecisionLens.ECONOMICS,
                    position=DecisionLensPosition.SUPPORT,
                    option_ids=(
                        "rotate-independent-forest",
                        "run-loss-skip-pair",
                    ),
                    basis_records=work_basis,
                    finding=(
                        "the pair measures native and stressed fixed-lot economics "
                        "against the exact unrestricted control"
                    ),
                ),
                DecisionLensAssessment(
                    lens=DecisionLens.RISK,
                    position=DecisionLensPosition.UNCERTAIN,
                    option_ids=("run-loss-skip-pair",),
                    basis_records=work_basis,
                    finding=(
                        "loss clustering may improve at the cost of density, so neither "
                        "metric may overwrite the other"
                    ),
                ),
                DecisionLensAssessment(
                    lens=DecisionLens.STATISTICS,
                    position=DecisionLensPosition.SUPPORT,
                    option_ids=(
                        "rotate-independent-forest",
                        "run-loss-skip-pair",
                    ),
                    basis_records=work_basis,
                    finding=(
                        "the exact two-member family permits synchronized selection "
                        "inference without a tuning search"
                    ),
                ),
            ),
            claim_boundary=(
                "discovery allocation only; candidate eligibility remains false"
            ),
            resolution_basis=(
                "run the exact fixed pair and preserve component-aware outcomes"
            ),
            disagreement_resolution=(
                "predeclare density and drawdown separately and make neither a hidden "
                "rescue criterion"
            ),
        ),
        baseline_executable=chassis.baseline_executable,
    )
    question = {
        "causal_question": axis.causal_question,
        "changed_variables": [
            "portfolio_entry_acceptance_state",
            "same_sleeve_realized_loss_one_entry_skip",
        ],
        "controlled_variables": [
            "calibration",
            "completed_bar_clock",
            "execution_cost",
            "features",
            "labels",
            "lifecycle",
            "models",
            "regime",
            "selectors",
            "signal_synthesis",
            "trade_direction",
        ],
        "done_conditions": [
            "both exact family members receive one validator-v2 completion",
            "activity, economics, risk, causality, and temporal claims remain separate",
            "candidate authority remains absent",
        ],
        "evidence_modes": list(PROSPECTIVE_PAIR_EVIDENCE_MODES),
    }
    proposal = {
        "candidate_eligible": False,
        "concurrent_family": {
            "control_executable_id": executables[0].identity,
            "ordered_executable_ids": list(definition.prospective_executable_ids),
            "subject_executable_id": executables[1].identity,
        },
        "control_policy": configurations[0].configuration_id,
        "estimand": (
            "subject minus unrestricted control under one common eligible calendar"
        ),
        "mechanism": MECHANISM_FAMILY,
        "schema": "sleeve_loss_skip_risk_study.v1",
        "subject_policy": configurations[1].configuration_id,
    }
    study_hash = writer.study_input_hash(
        question=question,
        material_identity=OBSERVED_MATERIAL_ID,
        semantic_proposal=proposal,
        controlled_chassis=chassis,
        portfolio_axis_id=axis.axis_id,
        portfolio_axis_identity=axis.identity,
        portfolio_decision_id=work_decision.identity,
    )
    concurrent_family = ConcurrentFamilyManifest(
        evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
        executable_ids=tuple(sorted(definition.prospective_executable_ids)),
    )
    batch_spec = BatchSpec(
        batch_id=BATCH_DISPLAY_ID,
        study_id=STUDY_ID,
        study_hash=study_hash,
        display_name="same-sleeve realized-loss one-entry skip pair",
        max_trials=2,
        max_compute_seconds=14400,
        max_wall_seconds=21600,
        stop_rule=(
            "stop after both preregistered members receive exactly one validated Job; "
            "no adaptive variant, threshold, or retry without changed information"
        ),
        source_contract_ids=tuple(chassis.baseline_executable.source_contracts),
        acceptance_profile={
            "candidate_authority": "none_discovery_only",
            "concurrent_family_size": 2,
            "required_member_completions": 2,
            "scientific_judgment": "component_aware_validator_v2",
        },
        adaptive_basis={
            "uncertainty": "one binary causal policy contrast",
            "causal_complexity": "one realized event arms one same-sleeve skip",
            "surface_curvature": "not searched; no tunable surface",
            "compute_cost": "two bounded subject Jobs over one exact pair family",
            "expected_information_value": (
                "separate risk-timing value from activity destruction"
            ),
            "portfolio_opportunity_cost": (
                "one Batch while all unrelated forest axes remain selectable"
            ),
        },
        concurrent_family=concurrent_family,
    )
    members = tuple(
        StudyMember(
            label=("control" if ordinal == 0 else "loss-skip"),
            executable=executable,
            job_plan=(
                definition_plan
                if ordinal == 0
                else build_sleeve_loss_skip_risk_job_plan(
                    repository_root=ROOT,
                    mission_id=MISSION_ID,
                    study_id=STUDY_ID,
                    executable_id=executable.identity,
                )
            ),
        )
        for ordinal, executable in enumerate(executables)
    )
    if any(
        member.job_plan.definition.manifest() != definition.manifest()
        for member in members
    ):
        raise RuntimeError("loss-skip member definitions differ")
    return StudyDesign(
        binding=StudyRunBinding(
            study_id=STUDY_ID,
            initiative_id=INITIATIVE_ID,
            operation_prefix=OPERATION_PREFIX,
            permit_expiry_utc=PERMIT_EXPIRY_UTC,
            portfolio_snapshot_id=BASE_SNAPSHOT_ID,
            study_permit_suffix="study-permit",
            superseded_operation_suffixes=(),
        ),
        prior_axes=prior_axes,
        axis=axis,
        structural_decision=structural_decision,
        expanded_snapshot=expanded_snapshot,
        work_decision=work_decision,
        question=question,
        proposal=proposal,
        batch_spec=batch_spec,
        members=members,
        semantic_question_lineage=None,
    )


def _operation_record(writer: StateWriter, operation_id: str) -> Any | None:
    with writer.open_stable_index() as (_control, index):
        return index.get("operation", operation_id)


def _operation_result(writer: StateWriter, operation_id: str) -> Mapping[str, Any]:
    record = _operation_record(writer, operation_id)
    result = None if record is None else record.payload.get("result")
    if record is None or record.status != "success" or not isinstance(result, Mapping):
        raise RuntimeError(f"operation is absent or unsuccessful: {operation_id}")
    return result


def _durable_or_planned_batch_id(
    writer: StateWriter,
    design: StudyDesign,
) -> str:
    operation = _operation_record(
        writer,
        design.binding.operation_prefix + "open-batch",
    )
    if operation is None:
        return design.batch_spec.identity
    result = _operation_result(writer, operation.record_id)
    batch_id = result.get("batch_id")
    if not isinstance(batch_id, str):
        raise RuntimeError("loss-skip Batch operation is malformed")
    return batch_id


def _permit_from_operation(writer: StateWriter, operation_id: str) -> Permit:
    raw = _operation_result(writer, operation_id).get("permit")
    if not isinstance(raw, Mapping):
        raise RuntimeError(f"permit operation is malformed: {operation_id}")
    return Permit.from_mapping(raw)


def _ensure_operation(
    writer: StateWriter,
    binding: StudyRunBinding,
    suffix: str,
    action: Callable[[], Any],
) -> Mapping[str, Any]:
    operation_id = binding.operation_prefix + suffix
    existing = _operation_record(writer, operation_id)
    if existing is None:
        print(json.dumps({"operation": operation_id, "status": "starting"}), flush=True)
        action()
    result = _operation_result(writer, operation_id)
    print(json.dumps({"operation": operation_id, "status": "complete"}), flush=True)
    return result


def _study_permit(writer: StateWriter, design: StudyDesign) -> Permit:
    binding = design.binding
    chassis = sleeve_loss_skip_risk_controlled_chassis()
    study_hash = writer.study_input_hash(
        question=design.question,
        material_identity=OBSERVED_MATERIAL_ID,
        semantic_proposal=design.proposal,
        semantic_question_lineage=design.semantic_question_lineage,
        controlled_chassis=chassis,
        portfolio_axis_id=design.axis.axis_id,
        portfolio_axis_identity=design.axis.identity,
        portfolio_decision_id=design.work_decision.identity,
    )
    return writer.issue_permit(
        kind=PermitKind.STUDY,
        subject_kind=SubjectKind.INITIATIVE,
        subject_id=binding.initiative_id,
        input_hash=study_hash,
        actions=("open_study",),
        scope=tuple(
            sorted(
                {
                    "study",
                    f"axis:{design.axis.identity}",
                    f"baseline:{chassis.baseline_executable.identity}",
                    f"chassis:{chassis.architecture.identity}",
                    f"decision:{design.work_decision.identity}",
                    f"snapshot:{design.expanded_snapshot.identity}",
                }
            )
        ),
        expires_at_utc=binding.permit_expiry_utc,
        one_shot=True,
        operation_id=(
            binding.operation_prefix + binding.study_permit_suffix
        ),
    )


def _materialize_job_authority(
    writer: StateWriter,
    design: StudyDesign,
) -> str:
    implementation = materialize_prospective_job_implementation(
        writer,
        entry_path=sleeve_loss_skip_risk_runtime_path(),
        callable_identity=CALLABLE_IDENTITY,
        protocol=JOB_IMPLEMENTATION_PROTOCOL,
        source_root=SOURCE_ROOT,
    )
    if implementation != _job_implementation_identity():
        raise RuntimeError("loss-skip Job implementation materialization drifted")
    for member in design.members:
        artifact = writer.evidence.finalize(canonical_bytes(member.job_plan.plan))
        if artifact.sha256 != member.job_plan.plan_hash:
            raise RuntimeError("loss-skip validation plan materialization drifted")
    return implementation


def _job_implementation_identity() -> str:
    return prospective_job_implementation_sha256(
        entry_path=sleeve_loss_skip_risk_runtime_path(),
        callable_identity=CALLABLE_IDENTITY,
        protocol=JOB_IMPLEMENTATION_PROTOCOL,
        source_root=SOURCE_ROOT,
    )


def _job_spec(
    member: StudyMember,
    *,
    binding: StudyRunBinding,
    implementation_identity: str,
    ordinal: int,
) -> Mapping[str, Any]:
    return {
        "budget": {"compute_seconds": 7200, "wall_seconds": 10800},
        "callable_identity": CALLABLE_IDENTITY,
        "evidence_subject": {
            "kind": "Executable",
            "id": member.executable.identity,
        },
        "expected_outputs": list(member.job_plan.expected_outputs()),
        "implementation_identity": implementation_identity,
        "input_hashes": list(member.job_plan.job_input_hashes()),
        "log_path": f"local/jobs/{binding.study_id.lower()}/{member.label}.log",
        "output_classes": member.job_plan.expected_output_classes(),
        "resume_action": "continue_batch" if ordinal == 0 else "stop_batch",
        "scientific_binding": member.job_plan.scientific_binding(),
        "timeout_or_stop_rule": "finish the exact registered loss-skip pair member",
        "worker_claims": [],
    }


def _completion(
    writer: StateWriter,
    binding: StudyRunBinding,
    member: StudyMember,
) -> Any:
    result = _operation_result(
        writer,
        f"{binding.operation_prefix}{member.label}-complete-job",
    )
    completion_id = result.get("completion_record_id")
    with writer.open_stable_index() as (_control, index):
        completion = (
            None
            if not isinstance(completion_id, str)
            else index.get("job-completed", completion_id)
        )
    if completion is None:
        raise RuntimeError("loss-skip Job completion is unavailable")
    return completion


def _record_negative_memory_if_required(
    writer: StateWriter,
    binding: StudyRunBinding,
    member: StudyMember,
) -> str | None:
    completion = _completion(writer, binding, member)
    scientific = completion.payload.get("scientific")
    failed = (
        isinstance(scientific, Mapping)
        and scientific.get("scientific_eligible") is True
        and scientific.get("verdict") == "failed"
    )
    operation_id = binding.operation_prefix + member.label + "-negative-memory"
    existing = _operation_record(writer, operation_id)
    if not failed:
        if existing is not None:
            raise RuntimeError("loss-skip negative memory exists for a non-failure")
        return None
    memory = NegativeMemory(
        executable_identity=member.executable.identity,
        scope=(
            f"{binding.study_id.lower().replace('-', '')}_"
            f"{member.label.replace('-', '_')}_discovery"
        ),
        evidence_references=(completion.record_id,),
        reason=(
            "The exact registered member contradicted the decisive component paths "
            "required for its coarse scientific verdict."
        ),
        reopen_condition=(
            "Reopen only with new registered material or a materially distinct causal "
            "risk mechanism, not an unchanged retry."
        ),
    )
    result = _ensure_operation(
        writer,
        binding,
        member.label + "-negative-memory",
        lambda: writer.record_negative_memory(
            memory=memory,
            operation_id=operation_id,
        ),
    )
    memory_id = result.get("negative_memory_id")
    if memory_id != memory.identity:
        raise RuntimeError("loss-skip negative memory identity drifted")
    return memory.identity


def _close_outcome(completion: Any) -> str:
    scientific = completion.payload.get("scientific")
    adjudication = (
        None if not isinstance(scientific, Mapping) else scientific.get("adjudication")
    )
    state = None if not isinstance(adjudication, Mapping) else adjudication.get("state")
    if state in {"confirmed", "frontier", "partial_positive"}:
        return "preserved"
    if state == "contradicted":
        return "pruned"
    if state in {"not_evaluable", "unresolved"}:
        return "not_evaluable"
    raise RuntimeError("loss-skip subject adjudication state is malformed")


def _known_operation_ids(design: StudyDesign) -> set[str]:
    suffixes = {
        "batch-permit",
        "close-study",
        "dispose-batch",
        "open-batch",
        "open-study",
        "register-control",
        "register-loss-skip",
        "work-decision",
    }
    suffixes.add(design.binding.study_permit_suffix)
    suffixes.update(design.binding.superseded_operation_suffixes)
    if design.structural_decision is not None:
        suffixes.update({"record-snapshot", "structural-decision"})
    for label in ("control", "loss-skip"):
        suffixes.update(
            {
                f"{label}-complete-job",
                f"{label}-declare-job",
                f"{label}-job-permit",
                f"{label}-judge-job",
                f"{label}-negative-memory",
                f"{label}-start-job",
            }
        )
    return {design.binding.operation_prefix + suffix for suffix in suffixes}


def _require_operation_ownership(
    writer: StateWriter,
    design: StudyDesign,
) -> None:
    with writer.open_stable_index() as (_control, index):
        observed = {
            record.record_id
            for record in index.records_by_kind_prefix(
                "operation",
                design.binding.operation_prefix,
            )
        }
    unknown = sorted(observed.difference(_known_operation_ids(design)))
    if unknown:
        raise RuntimeError("unknown loss-skip operation ids: " + ", ".join(unknown))


def run_study_close(writer: StateWriter, design: StudyDesign) -> Mapping[str, Any]:
    binding = design.binding
    _require_operation_ownership(writer, design)
    if design.structural_decision is not None:
        _ensure_operation(
            writer,
            binding,
            "structural-decision",
            lambda: writer.record_portfolio_decision(
                decision=design.structural_decision,
                operation_id=binding.operation_prefix + "structural-decision",
            ),
        )
        _ensure_operation(
            writer,
            binding,
            "record-snapshot",
            lambda: writer.record_portfolio_snapshot(
                snapshot=design.expanded_snapshot,
                operation_id=binding.operation_prefix + "record-snapshot",
            ),
        )
    _ensure_operation(
        writer,
        binding,
        "work-decision",
        lambda: writer.record_portfolio_decision(
            decision=design.work_decision,
            operation_id=binding.operation_prefix + "work-decision",
        ),
    )
    _ensure_operation(
        writer,
        binding,
        binding.study_permit_suffix,
        lambda: _study_permit(writer, design),
    )
    chassis = sleeve_loss_skip_risk_controlled_chassis()
    _ensure_operation(
        writer,
        binding,
        "open-study",
        lambda: writer.open_study(
            study_id=binding.study_id,
            question=design.question,
            material_identity=OBSERVED_MATERIAL_ID,
            material_display_name="foundation observed development material",
            semantic_proposal=design.proposal,
            semantic_question_lineage=design.semantic_question_lineage,
            controlled_chassis=chassis,
            portfolio_axis_id=design.axis.axis_id,
            portfolio_axis_identity=design.axis.identity,
            portfolio_decision_id=design.work_decision.identity,
            permit=_permit_from_operation(
                writer,
                binding.operation_prefix + binding.study_permit_suffix,
            ),
            operation_id=binding.operation_prefix + "open-study",
        ),
    )
    _ensure_operation(
        writer,
        binding,
        "batch-permit",
        lambda: writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id=binding.study_id,
            input_hash=design.batch_spec.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=binding.permit_expiry_utc,
            one_shot=True,
            operation_id=binding.operation_prefix + "batch-permit",
        ),
    )
    _ensure_operation(
        writer,
        binding,
        "open-batch",
        lambda: writer.open_batch(
            batch_spec=design.batch_spec,
            permit=_permit_from_operation(
                writer,
                binding.operation_prefix + "batch-permit",
            ),
            operation_id=binding.operation_prefix + "open-batch",
        ),
    )
    for member in design.members:
        _ensure_operation(
            writer,
            binding,
            "register-" + member.label,
            lambda member=member: writer.register_trial(
                executable=member.executable,
                operation_id=(
                    binding.operation_prefix + "register-" + member.label
                ),
            ),
        )

    implementation_identity = _materialize_job_authority(writer, design)
    for ordinal, member in enumerate(design.members):
        stem = member.label
        declaration = _ensure_operation(
            writer,
            binding,
            stem + "-declare-job",
            lambda member=member, ordinal=ordinal: writer.declare_job(
                spec=_job_spec(
                    member,
                    binding=binding,
                    implementation_identity=implementation_identity,
                    ordinal=ordinal,
                ),
                operation_id=(
                    binding.operation_prefix + stem + "-declare-job"
                ),
            ),
        )
        if declaration.get("disposition") == "reuse_success":
            raise RuntimeError("loss-skip Study unexpectedly reused a prior Job")
        job_id = declaration.get("job_id")
        job_hash = declaration.get("job_hash")
        if not isinstance(job_id, str) or not isinstance(job_hash, str):
            raise RuntimeError("loss-skip Job declaration is malformed")
        _ensure_operation(
            writer,
            binding,
            stem + "-job-permit",
            lambda job_id=job_id, job_hash=job_hash, stem=stem: writer.issue_permit(
                kind=PermitKind.JOB,
                subject_kind=SubjectKind.JOB,
                subject_id=job_id,
                input_hash=job_hash,
                actions=("start_job",),
                scope=("job",),
                expires_at_utc=binding.permit_expiry_utc,
                one_shot=True,
                operation_id=(
                    binding.operation_prefix + stem + "-job-permit"
                ),
            ),
        )
        _ensure_operation(
            writer,
            binding,
            stem + "-start-job",
            lambda stem=stem: writer.start_job(
                permit=_permit_from_operation(
                    writer,
                    binding.operation_prefix + stem + "-job-permit",
                ),
                operation_id=(
                    binding.operation_prefix + stem + "-start-job"
                ),
            ),
        )

        def complete(member: StudyMember = member, stem: str = stem) -> Any:
            execution_payload = _operation_result(
                writer,
                binding.operation_prefix + stem + "-start-job",
            ).get("execution")
            if not isinstance(execution_payload, Mapping):
                raise RuntimeError("loss-skip running Job execution is absent")
            packet = execute_sleeve_loss_skip_risk_job(
                repository_root=ROOT,
                execution=RunningJobExecution.from_mapping(execution_payload),
            )
            return writer.complete_job(
                outcome="success",
                output_manifest=packet.outputs(),
                operation_id=(
                    binding.operation_prefix + stem + "-complete-job"
                ),
            )

        _ensure_operation(writer, binding, stem + "-complete-job", complete)
        completion = _completion(writer, binding, member)
        scientific = completion.payload.get("scientific")
        if not isinstance(scientific, Mapping):
            raise RuntimeError("loss-skip completion lacks scientific adjudication")
        negative_memory_id = _record_negative_memory_if_required(
            writer,
            binding,
            member,
        )
        _ensure_operation(
            writer,
            binding,
            stem + "-judge-job",
            lambda completion=completion, negative_memory_id=negative_memory_id, ordinal=ordinal, stem=stem: writer.judge_job_evidence(
                completion_record_id=completion.record_id,
                disposition="continue_batch" if ordinal == 0 else "stop_batch",
                negative_memory_id=negative_memory_id,
                operation_id=(
                    binding.operation_prefix + stem + "-judge-job"
                ),
            ),
        )
    _ensure_operation(
        writer,
        binding,
        "dispose-batch",
        lambda: writer.dispose_batch(
            outcome="completed",
            operation_id=binding.operation_prefix + "dispose-batch",
        ),
    )
    subject_completion = _completion(writer, binding, design.subject)
    outcome = _close_outcome(subject_completion)
    _ensure_operation(
        writer,
        binding,
        "close-study",
        lambda: writer.close_study(
            outcome=outcome,
            kpi_completion_record_id=subject_completion.record_id,
            operation_id=binding.operation_prefix + "close-study",
        ),
    )
    close_operation = _operation_record(
        writer,
        binding.operation_prefix + "close-study",
    )
    if close_operation is None:
        raise RuntimeError("loss-skip Study close operation is absent")
    return {
        "batch_id": _durable_or_planned_batch_id(writer, design),
        "control_executable_id": design.control.executable.identity,
        "outcome": outcome,
        "study_close_event_id": close_operation.authority_event_id,
        "study_close_revision": close_operation.authority_sequence,
        "study_id": binding.study_id,
        "subject_executable_id": design.subject.executable.identity,
    }


def read_only_summary(writer: StateWriter, design: StudyDesign) -> Mapping[str, Any]:
    with writer.open_stable_index() as (control, index):
        operations = tuple(
            index.records_by_kind_prefix(
                "operation",
                design.binding.operation_prefix,
            )
        )
    return {
        "axis_id": design.axis.axis_id,
        "axis_identity": design.axis.identity,
        "base_snapshot_id": design.binding.portfolio_snapshot_id,
        "batch_id": _durable_or_planned_batch_id(writer, design),
        "control_executable_id": design.control.executable.identity,
        "expanded_snapshot_id": design.expanded_snapshot.identity,
        "job_implementation_identity": _job_implementation_identity(),
        "job_protocol": JOB_IMPLEMENTATION_PROTOCOL,
        "next_action": control["next_action"],
        "operation_count": len(operations),
        "revision": control["revision"],
        "structural_decision_id": (
            None
            if design.structural_decision is None
            else design.structural_decision.identity
        ),
        "study_id": design.binding.study_id,
        "subject_executable_id": design.subject.executable.identity,
        "work_decision_id": design.work_decision.identity,
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan or run the prospective sleeve loss-skip risk Study."
    )
    parser.add_argument(
        "--stage",
        choices=("study-close",),
        help="omit for a read-only preregistration plan",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
    writer = StateWriter(ROOT, validation_registry=registry)
    writer.require_stable_head()
    design = build_design(writer)
    _require_operation_ownership(writer, design)
    if arguments.stage is None:
        print(json.dumps(read_only_summary(writer, design), sort_keys=True))
        return
    writer.permit_authority = PermitAuthority(
        PermitKeyStore(ROOT / "local" / "permit.key").load_or_create()
    )
    print(json.dumps(run_study_close(writer, design), sort_keys=True))


if __name__ == "__main__":
    main()
