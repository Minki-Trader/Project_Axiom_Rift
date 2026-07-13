from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.apply_project_goal_audit_v1 import (  # noqa: E402
    AUTHORITY_OPERATION_ID,
    EXPECTED_FINAL_ACTION,
    EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS,
    EXPECTED_MISSION_ID,
    PROTOCOL_OPERATION_ID,
    build_correction_plan,
    correction_steps,
    inspect_correction_prefix,
    read_frozen_audit_report,
    require_frozen_report_unchanged,
    validate_correction_progress,
)
from axiom_rift.core.canonical import canonical_bytes  # noqa: E402
from axiom_rift.operations.permits import (  # noqa: E402
    Permit,
    PermitAuthority,
    PermitKeyStore,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.validation import (  # noqa: E402
    EvidenceValidatorRegistry,
)
from axiom_rift.operations.writer import StateWriter, TransitionResult  # noqa: E402
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID  # noqa: E402
from axiom_rift.research.forest_replay import (  # noqa: E402
    CompositeValidationPlan,
    P0_COMPOSITE_PLAN_OUTPUT,
    P0_REPLAY_EVIDENCE_MODES,
    build_p0_composite_validation_plan,
    compute_p0_forest_replay,
    forest_replay_dependency_paths,
)
from axiom_rift.research.governance import (  # noqa: E402
    DiagnosisConfidence,
    EvidenceState,
    ResearchLayer,
    StudyDiagnosis,
)
from axiom_rift.research.portfolio import (  # noqa: E402
    BatchSpec,
    DecisionOption,
    PortfolioAction,
    PortfolioAxis,
    PortfolioDecision,
    PortfolioSnapshot,
)
from axiom_rift.research.portfolio_projection import (  # noqa: E402
    component_surface_registry,
    portfolio_axes_from_projection,
)
from axiom_rift.research.selection_inference import (  # noqa: E402
    DEFAULT_BASE_SEED,
    DEFAULT_BLOCK_LENGTHS,
    DEFAULT_BOOTSTRAP_SAMPLES,
    HistoricalSearchContext,
)
from axiom_rift.research.validation_v2 import (  # noqa: E402
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    ScientificAdjudicationValidatorV2,
)
from axiom_rift.storage.index import LocalIndex  # noqa: E402


MISSION_ID = EXPECTED_MISSION_ID
INITIATIVE_ID = "INI-0017"
STUDY_ID = "STU-0105"
BATCH_DISPLAY_ID = "BAT-0105"
AXIS_ID = "axis-p0-composite-audit-reanalysis"
OPERATION_PREFIX = "p0-composite-audit-v1-"
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"
CALLABLE_IDENTITY = (
    "axiom_rift.research.forest_replay.compute_p0_forest_replay"
)
JOB_PROTOCOL = "python.source.p0_composite_reanalysis.v1"


@dataclass(frozen=True, slots=True)
class OperationStep:
    operation_id: str
    event_kind: str


STUDY_CLOSE_STEPS = (
    OperationStep(OPERATION_PREFIX + "open-initiative", "initiative_opened"),
    OperationStep(
        OPERATION_PREFIX + "structural-decision",
        "portfolio_decision_recorded",
    ),
    OperationStep(
        OPERATION_PREFIX + "expanded-snapshot",
        "portfolio_snapshot_recorded",
    ),
    OperationStep(OPERATION_PREFIX + "work-decision", "portfolio_decision_recorded"),
    OperationStep(OPERATION_PREFIX + "study-permit", "permit_issued"),
    OperationStep(OPERATION_PREFIX + "open-study", "study_opened"),
    OperationStep(OPERATION_PREFIX + "batch-permit", "permit_issued"),
    OperationStep(OPERATION_PREFIX + "open-batch", "batch_opened"),
    OperationStep(OPERATION_PREFIX + "register-trial", "trial_registered"),
    OperationStep(OPERATION_PREFIX + "declare-job", "job_declared"),
    OperationStep(OPERATION_PREFIX + "job-permit", "permit_issued"),
    OperationStep(OPERATION_PREFIX + "start-job", "job_started"),
    OperationStep(OPERATION_PREFIX + "complete-job", "job_completed"),
    OperationStep(OPERATION_PREFIX + "judge-job", "job_evidence_judged"),
    OperationStep(OPERATION_PREFIX + "dispose-batch", "batch_disposed"),
    OperationStep(OPERATION_PREFIX + "close-study", "study_closed"),
)
DIAGNOSE_STEPS = (
    OperationStep(OPERATION_PREFIX + "diagnose-study", "study_diagnosis_recorded"),
    OperationStep(
        OPERATION_PREFIX + "preserve-decision",
        "portfolio_decision_recorded",
    ),
    OperationStep(
        OPERATION_PREFIX + "preserved-snapshot",
        "portfolio_snapshot_recorded",
    ),
    OperationStep(OPERATION_PREFIX + "close-initiative", "initiative_closed"),
)
ALL_STEPS = (*STUDY_CLOSE_STEPS, *DIAGNOSE_STEPS)


@dataclass(frozen=True, slots=True)
class ForestStudyDesign:
    report_hash: str
    base_snapshot_id: str
    source_axis_id: str
    alternate_axis_id: str
    replay_plan: CompositeValidationPlan
    prior_axes: tuple[PortfolioAxis, ...]
    audit_axis: PortfolioAxis
    structural_decision: PortfolioDecision
    expanded_snapshot: PortfolioSnapshot
    work_decision: PortfolioDecision
    question: Mapping[str, Any]
    proposal: Mapping[str, Any]
    batch_spec: BatchSpec


def _operation_record(writer: StateWriter, operation_id: str) -> Any:
    with LocalIndex(writer.index_path) as index:
        record = index.get("operation", operation_id)
    if record is None or record.status != "success":
        raise RuntimeError(f"operation is absent or unsuccessful: {operation_id}")
    return record


def _operation_result(writer: StateWriter, operation_id: str) -> Mapping[str, Any]:
    record = _operation_record(writer, operation_id)
    result = record.payload.get("result")
    if not isinstance(result, Mapping):
        raise RuntimeError(f"operation result is absent: {operation_id}")
    return result


def _permit_from_operation(writer: StateWriter, operation_id: str) -> Permit:
    result = _operation_result(writer, operation_id)
    permit = result.get("permit")
    if not isinstance(permit, Mapping):
        raise RuntimeError(f"permit operation result is malformed: {operation_id}")
    return Permit.from_mapping(permit)


def inspect_operation_prefix(
    writer: StateWriter,
    *,
    predecessor_revision: int,
    predecessor_event_id: str,
    steps: Sequence[OperationStep] = ALL_STEPS,
) -> int:
    """Prove one exact gap-free operation suffix with no interleaved state write."""

    ordered = tuple(steps)
    expected_ids = {step.operation_id for step in ordered}
    with LocalIndex(writer.index_path) as index:
        unknown = sorted(
            record.record_id
            for record in index.records_by_kind("operation")
            if record.record_id.startswith(OPERATION_PREFIX)
            and record.record_id not in expected_ids
        )
        records = tuple(index.get("operation", step.operation_id) for step in ordered)
    if unknown:
        raise RuntimeError(
            "unknown P0 composite audit operation exists: " + ", ".join(unknown)
        )
    present = tuple(record is not None for record in records)
    prefix = 0
    while prefix < len(present) and present[prefix]:
        prefix += 1
    if any(present[prefix:]):
        raise RuntimeError("P0 composite audit operations are not a strict prefix")
    expected_event_id = predecessor_event_id
    for offset, (step, operation) in enumerate(
        zip(ordered[:prefix], records[:prefix])
    ):
        assert operation is not None
        expected_revision = predecessor_revision + offset + 1
        if (
            operation.status != "success"
            or operation.authority_sequence != expected_revision
            or operation.payload.get("event_kind") != step.event_kind
            or operation.authority_event_id is None
            or operation.authority_offset is None
        ):
            raise RuntimeError("P0 composite audit operation authority is invalid")
        event = writer.journal.read_event_at(
            offset=operation.authority_offset,
            expected_sequence=expected_revision,
            expected_event_id=operation.authority_event_id,
        )
        if (
            event.get("operation_id") != step.operation_id
            or event.get("event_kind") != step.event_kind
            or event.get("sequence") != expected_revision
        ):
            raise RuntimeError("P0 composite audit Journal suffix is invalid")
        expected_event_id = operation.authority_event_id
    control = writer.read_control()
    if (
        control is None
        or control.get("revision") != predecessor_revision + prefix
        or control.get("heads", {}).get("journal", {}).get("event_id")
        != expected_event_id
    ):
        raise RuntimeError("control head differs from the P0 composite audit prefix")
    return prefix


def _has_forest_operations(writer: StateWriter) -> bool:
    with LocalIndex(writer.index_path) as index:
        return any(
            record.record_id.startswith(OPERATION_PREFIX)
            for record in index.records_by_kind("operation")
        )


def _verify_active_protocol(writer: StateWriter, report_hash: str) -> None:
    control = writer.read_control()
    if control is None:
        raise RuntimeError("control is absent")
    with LocalIndex(writer.index_path) as index:
        head = index.event_head("research-protocol:scientific")
        protocol = None if head is None else index.get(head.record_kind, head.record_id)
    if (
        protocol is None
        or protocol.status != "active"
        or protocol.payload.get("protocol") != "scientific_adjudication_v2"
        or protocol.payload.get("validator_id")
        != SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
        or protocol.payload.get("audit_artifact_hash") != report_hash
        or protocol.payload.get("authority_manifest_digest")
        != control.get("authority", {}).get("manifest_digest")
    ):
        raise RuntimeError("active scientific v2 protocol differs from audit authority")


def _verify_activated_authority_files(writer: StateWriter) -> None:
    operation = _operation_record(writer, AUTHORITY_OPERATION_ID)
    event = writer.journal.read_event_at(
        offset=operation.authority_offset,
        expected_sequence=operation.authority_sequence,
        expected_event_id=operation.authority_event_id,
    )
    rows = event.get("payload", {}).get("replacements")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("audit authority replacement manifest is absent")
    for row in rows:
        if not isinstance(row, Mapping):
            raise RuntimeError("audit authority replacement row is malformed")
        relative = row.get("path")
        expected_hash = row.get("new_sha256")
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise RuntimeError("audit authority replacement identity is malformed")
        target = (writer.foundation_root / relative).resolve()
        try:
            target.relative_to(writer.foundation_root.resolve())
        except ValueError as exc:
            raise RuntimeError("audit authority path escapes the repository") from exc
        if not target.is_file() or sha256(target.read_bytes()).hexdigest() != expected_hash:
            raise RuntimeError("activated audit authority file bytes changed")


def verify_production_preconditions(
    writer: StateWriter,
) -> tuple[str, int, str]:
    """Verify the correction boundary or its exact downstream causal suffix."""

    report_bytes, report_hash = read_frozen_audit_report(writer.root)
    require_frozen_report_unchanged(root=writer.root, expected_hash=report_hash)
    correction_prefix = inspect_correction_prefix(writer, steps=correction_steps())
    if correction_prefix != len(correction_steps()):
        raise RuntimeError("Project Goal audit correction is not complete")
    correction_tail = _operation_record(
        writer, correction_steps()[-1].operation_id
    )
    if not _has_forest_operations(writer):
        plan = build_correction_plan(writer, root=writer.root)
        if validate_correction_progress(writer, plan=plan) != len(plan.steps):
            raise RuntimeError("Project Goal audit correction postconditions failed")
    else:
        if writer.evidence.read_verified(report_hash) != report_bytes:
            raise RuntimeError("frozen audit report evidence differs")
        _verify_activated_authority_files(writer)
        _verify_active_protocol(writer, report_hash)
        _operation_record(writer, PROTOCOL_OPERATION_ID)
    if (
        correction_tail.authority_sequence is None
        or correction_tail.authority_event_id is None
    ):
        raise RuntimeError("correction tail authority is absent")
    return (
        report_hash,
        correction_tail.authority_sequence,
        correction_tail.authority_event_id,
    )


def _base_snapshot_id(writer: StateWriter, prefix: int) -> str:
    if prefix >= 2:
        decision_id = _operation_result(
            writer, STUDY_CLOSE_STEPS[1].operation_id
        ).get("decision_id")
        with LocalIndex(writer.index_path) as index:
            decision = (
                None
                if not isinstance(decision_id, str)
                else index.get("portfolio-decision", decision_id)
            )
        if decision is None:
            raise RuntimeError("structural Decision projection is absent")
        snapshot_id = decision.payload.get("portfolio_snapshot_id")
    else:
        with LocalIndex(writer.index_path) as index:
            head = index.event_head(f"portfolio:{MISSION_ID}")
        snapshot_id = None if head is None else head.record_id
    if not isinstance(snapshot_id, str):
        raise RuntimeError("base Portfolio snapshot is absent")
    return snapshot_id


def _projection_payloads(
    index: LocalIndex,
    replay_plan: CompositeValidationPlan,
) -> tuple[Mapping[str, Any], ...]:
    payloads: list[Mapping[str, Any]] = [
        replay_plan.baseline_executable.to_identity_payload(),
        replay_plan.executable.to_identity_payload(),
    ]
    for kind in (
        "trial",
        "portfolio-decision",
        "study-open",
        "portfolio-snapshot",
    ):
        payloads.extend(record.payload for record in index.records_by_kind(kind))
    return tuple(payloads)


def build_forest_study_design(
    writer: StateWriter,
    *,
    report_hash: str,
    base_snapshot_id: str,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    block_lengths: tuple[int, ...] = DEFAULT_BLOCK_LENGTHS,
    base_seed: int = DEFAULT_BASE_SEED,
) -> ForestStudyDesign:
    if len(report_hash) != 64:
        raise RuntimeError("audit report hash is invalid")
    historical_context = HistoricalSearchContext(
        context_id=f"audit-report-sha256:{report_hash}",
        prior_global_exposure_count=EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS,
    )
    replay_plan = build_p0_composite_validation_plan(
        mission_id=MISSION_ID,
        historical_context=historical_context,
        bootstrap_samples=bootstrap_samples,
        block_lengths=block_lengths,
        base_seed=base_seed,
    )
    with LocalIndex(writer.index_path) as index:
        snapshot_record = index.get("portfolio-snapshot", base_snapshot_id)
        if snapshot_record is None:
            raise RuntimeError("base Portfolio snapshot projection is absent")
        components = component_surface_registry(
            _projection_payloads(index, replay_plan)
        )
    prior_axes = portfolio_axes_from_projection(
        snapshot_record.payload["axes"], components
    )
    if any(axis.axis_id == AXIS_ID for axis in prior_axes):
        raise RuntimeError("P0 composite audit axis already predates this operation chain")
    eligible = tuple(
        axis for axis in prior_axes if axis.status != "pruned"
    )
    preferred = tuple(
        axis
        for axis in eligible
        if axis.primary_research_layer is not ResearchLayer.DATA_SOURCE
    )
    source_axis = (preferred or eligible)[0] if (preferred or eligible) else None
    if source_axis is None:
        raise RuntimeError("Portfolio has no eligible structural source axis")
    alternate_axis = next(
        (axis for axis in eligible if axis.axis_id != source_axis.axis_id),
        source_axis,
    )
    chassis = replay_plan.controlled_chassis()
    audit_axis = PortfolioAxis(
        axis_id=AXIS_ID,
        causal_question=(
            "Does exact post-selection composite reanalysis preserve audit "
            "integrity without creating candidate authority?"
        ),
        mechanism_family="historical-post-selection-composite-audit",
        primary_research_layer=ResearchLayer.SYNTHESIS,
        system_architecture_family=chassis.architecture.identity,
        changed_domains=tuple(chassis.changed_domains),
        controlled_domains=tuple(chassis.controlled_domains),
        why_now=(
            "the exhaustive audit requires one bounded common-control replay of "
            "the selected P0 historical surfaces"
        ),
        stop_or_reopen_condition=(
            "stop after the exact validator-v2 result and reopen only under a "
            "separately preregistered prospective protocol"
        ),
        architecture_chassis=chassis.architecture,
    )
    structural_decision = PortfolioDecision(
        decision_id="DEC-P0-COMPOSITE-AUDIT-STRUCTURE",
        chosen_option_id="add-composite-audit-axis",
        options=(
            DecisionOption(
                option_id="add-composite-audit-axis",
                action=PortfolioAction.NEW_MECHANISM,
                target_id=source_axis.axis_id,
                expected_information_value=(
                    "high integrity information about the selected historical set"
                ),
                opportunity_cost="one bounded descriptive replay Study",
            ),
            DecisionOption(
                option_id="retain-current-forest-only",
                action=PortfolioAction.PRESERVE,
                target_id=alternate_axis.axis_id,
                expected_information_value="no new audit information",
                opportunity_cost="leave the cross-surface audit defect unresolved",
                omission_reason=(
                    "the frozen audit report requires a typed composite replay axis"
                ),
            ),
        ),
        rationale=(
            "add one pure-SYNTHESIS audit mechanism while retaining every prior axis"
        ),
        commitment_batches=1,
    )
    expanded_snapshot = PortfolioSnapshot(
        mission_id=MISSION_ID,
        axes=(*prior_axes, audit_axis),
        opportunity_cost_basis=(
            "retain the complete current forest and spend one Batch on the frozen "
            "P0 composite audit"
        ),
        research_intake_id=snapshot_record.payload.get("research_intake_id"),
        exhaustion_standard=snapshot_record.payload.get("exhaustion_standard"),
    )
    work_decision = PortfolioDecision(
        decision_id="DEC-P0-COMPOSITE-AUDIT-WORK",
        chosen_option_id="run-composite-audit",
        options=(
            DecisionOption(
                option_id="run-composite-audit",
                action=PortfolioAction.SYNTHESIZE,
                target_id=audit_axis.axis_id,
                expected_information_value=(
                    "one common-control integrity and sensitivity result"
                ),
                opportunity_cost="one immutable trial and one bounded Job",
            ),
            DecisionOption(
                option_id="defer-to-existing-axis",
                action=PortfolioAction.CONTRAST,
                target_id=alternate_axis.axis_id,
                expected_information_value="future prospective contrast information",
                opportunity_cost="defer the frozen historical audit",
                omission_reason=(
                    "the composite audit is the bounded P0 correction dependency"
                ),
            ),
        ),
        rationale=(
            "run exactly one post-selection descriptive composite without candidate "
            "or prospective claim authority"
        ),
        commitment_batches=1,
        baseline_executable=replay_plan.baseline_executable,
    )
    question = {
        "causal_question": (
            "Does exact P0 post-selection composite reanalysis preserve audit integrity?"
        ),
        "changed_variables": ["synthesis_reanalysis"],
        "controlled_variables": [
            "label",
            "model",
            "trade",
            "lifecycle",
            "execution",
        ],
        "done_conditions": [
            "the exact validator-v2 composite result is complete",
            "candidate authority remains absent",
        ],
        "evidence_modes": list(P0_REPLAY_EVIDENCE_MODES),
    }
    proposal = {
        "authority": "post_selection_descriptive_audit_only",
        "candidate_eligible": False,
        "mechanism": "selected_set_composite_reanalysis",
        "report_sha256": report_hash,
    }
    study_hash = writer.study_input_hash(
        question=question,
        material_identity=OBSERVED_MATERIAL_ID,
        semantic_proposal=proposal,
        controlled_chassis=chassis,
        portfolio_axis_id=audit_axis.axis_id,
        portfolio_axis_identity=audit_axis.identity,
        portfolio_decision_id=work_decision.identity,
    )
    batch_spec = BatchSpec(
        batch_id=BATCH_DISPLAY_ID,
        study_id=STUDY_ID,
        study_hash=study_hash,
        display_name="P0 selected-set composite audit Batch",
        max_trials=1,
        max_compute_seconds=3600,
        max_wall_seconds=5400,
        stop_rule="stop after the exact one-Job composite audit result",
        source_contract_ids=tuple(replay_plan.executable.source_contracts),
        acceptance_profile={
            "candidate_authority": "none",
            "scientific_verdict": "validator_v2_pass",
            "trial_count": 1,
        },
        adaptive_basis={
            "uncertainty": "historical selection context is explicit",
            "causal_complexity": "one exact selected-set composition",
            "surface_curvature": "not adaptive",
            "compute_cost": "one bounded 41999-sample replay at production default",
            "expected_information_value": "repair cross-surface interpretation",
            "portfolio_opportunity_cost": "all other axes remain retained",
        },
    )
    return ForestStudyDesign(
        report_hash=report_hash,
        base_snapshot_id=base_snapshot_id,
        source_axis_id=source_axis.axis_id,
        alternate_axis_id=alternate_axis.axis_id,
        replay_plan=replay_plan,
        prior_axes=prior_axes,
        audit_axis=audit_axis,
        structural_decision=structural_decision,
        expanded_snapshot=expanded_snapshot,
        work_decision=work_decision,
        question=question,
        proposal=proposal,
        batch_spec=batch_spec,
    )


def _study_permit(writer: StateWriter, design: ForestStudyDesign) -> Permit:
    chassis = design.replay_plan.controlled_chassis()
    study_hash = writer.study_input_hash(
        question=design.question,
        material_identity=OBSERVED_MATERIAL_ID,
        semantic_proposal=design.proposal,
        controlled_chassis=chassis,
        portfolio_axis_id=design.audit_axis.axis_id,
        portfolio_axis_identity=design.audit_axis.identity,
        portfolio_decision_id=design.work_decision.identity,
    )
    return writer.issue_permit(
        kind=PermitKind.STUDY,
        subject_kind=SubjectKind.INITIATIVE,
        subject_id=INITIATIVE_ID,
        input_hash=study_hash,
        actions=("open_study",),
        scope=tuple(
            sorted(
                {
                    "study",
                    f"decision:{design.work_decision.identity}",
                    f"axis:{design.audit_axis.identity}",
                    (
                        "baseline:"
                        f"{design.replay_plan.baseline_executable.identity}"
                    ),
                    f"chassis:{chassis.architecture.identity}",
                    f"snapshot:{design.expanded_snapshot.identity}",
                }
            )
        ),
        expires_at_utc=PERMIT_EXPIRY_UTC,
        one_shot=True,
        operation_id=STUDY_CLOSE_STEPS[4].operation_id,
    )


def _finalize_job_inputs(
    writer: StateWriter, design: ForestStudyDesign
) -> str:
    source_hashes = sorted(
        {
            writer.evidence.finalize(path.read_bytes()).sha256
            for path in forest_replay_dependency_paths()
        }
    )
    implementation = writer.evidence.finalize(
        canonical_bytes(
            {
                "artifact_hashes": source_hashes,
                "callable_identity": CALLABLE_IDENTITY,
                "protocol": JOB_PROTOCOL,
                "schema": "job_implementation_evidence.v1",
            }
        )
    )
    plan_artifact = writer.evidence.finalize(
        canonical_bytes(dict(design.replay_plan.plan))
    )
    if plan_artifact.sha256 != design.replay_plan.plan_hash:
        raise RuntimeError("preregistered validation plan hash changed")
    writer.evidence.verify(plan_artifact.sha256)
    return implementation.sha256


def _job_spec(
    writer: StateWriter, design: ForestStudyDesign
) -> Mapping[str, Any]:
    implementation_identity = _finalize_job_inputs(writer, design)
    return {
        "budget": {"compute_seconds": 3600, "wall_seconds": 5400},
        "callable_identity": CALLABLE_IDENTITY,
        "evidence_subject": {
            "id": design.replay_plan.executable_id,
            "kind": "Executable",
        },
        "expected_outputs": list(design.replay_plan.expected_outputs()),
        "implementation_identity": implementation_identity,
        "input_hashes": list(design.replay_plan.job_input_hashes()),
        "log_path": "local/jobs/p0-forest/stu-0105.log",
        "output_classes": design.replay_plan.output_classes(),
        "resume_action": "stop_batch",
        "scientific_binding": design.replay_plan.scientific_binding(
            validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
        ),
        "timeout_or_stop_rule": "finish the exact composite audit replay",
        "worker_claims": [],
    }


def _materialize_bundle(writer: StateWriter, bundle: Any) -> tuple[int, int]:
    payloads = bundle.artifact_bytes()
    classes = bundle.output_classes()
    hashes = bundle.output_hashes()
    if set(payloads) != set(classes) or set(payloads) != set(hashes):
        raise RuntimeError("forest replay output surfaces differ")
    durable_count = 0
    cache_count = 0
    for output_name in sorted(payloads):
        content = payloads[output_name]
        if classes[output_name] == "durable_evidence":
            artifact = writer.evidence.finalize(content)
            if artifact.sha256 != hashes[output_name]:
                raise RuntimeError("durable forest output hash changed")
            durable_count += 1
            continue
        if classes[output_name] != "reproducible_cache":
            raise RuntimeError("forest replay output class is unsupported")
        target = (writer.root / output_name).resolve()
        cache_root = (writer.root / "local" / "cache").resolve()
        if cache_root not in target.parents:
            raise RuntimeError("forest cache path escapes local/cache")
        if target.exists():
            if not target.is_file() or target.read_bytes() != content:
                raise RuntimeError("existing forest cache bytes differ")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        cache_count += 1
    if (durable_count, cache_count) != (3, 11):
        raise RuntimeError("forest replay must materialize exactly 3 durable and 11 cache outputs")
    return durable_count, cache_count


def _apply_study_close_step(
    writer: StateWriter,
    *,
    design: ForestStudyDesign,
    repository_root: Path,
    step_index: int,
) -> TransitionResult | Permit:
    operation_id = STUDY_CLOSE_STEPS[step_index].operation_id
    if step_index == 0:
        return writer.open_initiative(
            initiative_id=INITIATIVE_ID,
            objective={
                "objective": "run one exact P0 selected-set composite audit",
                "bounds": {
                    "bootstrap_samples": design.replay_plan.bootstrap_samples,
                    "trial_delta": 1,
                    "wall_seconds": 5400,
                },
                "done_conditions": [
                    "one validator-v2 result is complete",
                    "no candidate or holdout authority is created",
                ],
            },
            operation_id=operation_id,
        )
    if step_index == 1:
        return writer.record_portfolio_decision(
            decision=design.structural_decision,
            operation_id=operation_id,
        )
    if step_index == 2:
        return writer.record_portfolio_snapshot(
            snapshot=design.expanded_snapshot,
            operation_id=operation_id,
        )
    if step_index == 3:
        return writer.record_portfolio_decision(
            decision=design.work_decision,
            operation_id=operation_id,
        )
    if step_index == 4:
        return _study_permit(writer, design)
    if step_index == 5:
        return writer.open_study(
            study_id=STUDY_ID,
            question=design.question,
            material_identity=OBSERVED_MATERIAL_ID,
            material_display_name="foundation observed development material",
            semantic_proposal=design.proposal,
            controlled_chassis=design.replay_plan.controlled_chassis(),
            portfolio_axis_id=design.audit_axis.axis_id,
            portfolio_axis_identity=design.audit_axis.identity,
            portfolio_decision_id=design.work_decision.identity,
            permit=_permit_from_operation(
                writer, STUDY_CLOSE_STEPS[4].operation_id
            ),
            operation_id=operation_id,
        )
    if step_index == 6:
        return writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id=STUDY_ID,
            input_hash=design.batch_spec.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=PERMIT_EXPIRY_UTC,
            one_shot=True,
            operation_id=operation_id,
        )
    if step_index == 7:
        return writer.open_batch(
            batch_spec=design.batch_spec,
            permit=_permit_from_operation(
                writer, STUDY_CLOSE_STEPS[6].operation_id
            ),
            operation_id=operation_id,
        )
    if step_index == 8:
        return writer.register_trial(
            executable=design.replay_plan.executable,
            operation_id=operation_id,
        )
    if step_index == 9:
        declared = writer.declare_job(
            spec=_job_spec(writer, design),
            operation_id=operation_id,
        )
        if declared.result.get("disposition") == "reuse_success":
            raise RuntimeError("P0 audit unexpectedly reused an earlier Job success")
        return declared
    if step_index == 10:
        declaration = _operation_result(
            writer, STUDY_CLOSE_STEPS[9].operation_id
        )
        return writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=declaration["job_id"],
            input_hash=declaration["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=PERMIT_EXPIRY_UTC,
            one_shot=True,
            operation_id=operation_id,
        )
    if step_index == 11:
        return writer.start_job(
            permit=_permit_from_operation(
                writer, STUDY_CLOSE_STEPS[10].operation_id
            ),
            operation_id=operation_id,
        )
    if step_index == 12:
        declaration = _operation_result(
            writer, STUDY_CLOSE_STEPS[9].operation_id
        )
        bundle = compute_p0_forest_replay(
            repository_root,
            replay_plan=design.replay_plan,
            job_id=declaration["job_id"],
            job_hash=declaration["job_hash"],
        )
        _materialize_bundle(writer, bundle)
        return writer.complete_job(
            outcome="success",
            output_manifest=bundle.output_hashes(),
            operation_id=operation_id,
        )
    if step_index == 13:
        completion = _operation_result(
            writer, STUDY_CLOSE_STEPS[12].operation_id
        )
        return writer.judge_job_evidence(
            completion_record_id=completion["completion_record_id"],
            disposition="stop_batch",
            operation_id=operation_id,
        )
    if step_index == 14:
        return writer.dispose_batch(
            outcome="completed",
            operation_id=operation_id,
        )
    if step_index == 15:
        completion = _operation_result(
            writer, STUDY_CLOSE_STEPS[12].operation_id
        )
        return writer.close_study(
            outcome="preserved",
            kpi_completion_record_id=completion["completion_record_id"],
            operation_id=operation_id,
        )
    raise RuntimeError("unknown P0 composite audit Study-close step")


def _study_close_record_id(writer: StateWriter) -> str:
    with LocalIndex(writer.index_path) as index:
        records = tuple(
            record
            for record in index.records_by_subject_status(
                f"Study:{STUDY_ID}", "preserved"
            )
            if record.kind == "study-close"
        )
    if len(records) != 1:
        raise RuntimeError("exact P0 composite audit Study-close record is unavailable")
    return records[0].record_id


def _assert_common_scientific_boundary(writer: StateWriter) -> Mapping[str, Any]:
    control = writer.read_control()
    if control is None:
        raise RuntimeError("control is absent")
    science = control.get("scientific")
    if (
        not isinstance(science, Mapping)
        or science.get("active_mission") != MISSION_ID
        or science.get("holdout_reveals") != 0
        or science.get("claim") != "none"
        or science.get("required_future_holdout_id") is not None
        or any(
            science.get(name) is not None
            for name in (
                "active_batch",
                "active_executable",
                "active_holdout_evaluation",
                "active_job",
                "active_lineage",
                "active_release",
                "active_repair",
                "active_study",
            )
        )
    ):
        raise RuntimeError("P0 composite audit left an unsafe scientific boundary")
    return control


def verify_study_close_postconditions(
    writer: StateWriter, design: ForestStudyDesign
) -> Mapping[str, Any]:
    control = _assert_common_scientific_boundary(writer)
    close_record_id = _study_close_record_id(writer)
    expected_action = {
        "kind": "diagnose_study",
        "study_id": STUDY_ID,
        "study_close_record_id": close_record_id,
        "portfolio_snapshot_id": design.expanded_snapshot.identity,
    }
    if (
        control["scientific"].get("active_initiative") != INITIATIVE_ID
        or control.get("next_action") != expected_action
    ):
        raise RuntimeError("Study-close checkpoint direction is invalid")
    completion_id = _operation_result(
        writer, STUDY_CLOSE_STEPS[12].operation_id
    )["completion_record_id"]
    with LocalIndex(writer.index_path) as index:
        trial = index.get("trial", design.replay_plan.executable_id)
        completion = index.get("job-completed", completion_id)
        candidate = index.event_head(
            f"candidate:{design.replay_plan.executable_id}"
        )
    scientific = None if completion is None else completion.payload.get("scientific")
    if (
        trial is None
        or trial.payload.get("trial_delta") != 1
        or completion is None
        or not isinstance(scientific, Mapping)
        or scientific.get("verdict") != "passed"
        or scientific.get("candidate_eligible") is not False
        or candidate is not None
    ):
        raise RuntimeError("P0 composite audit evidence postconditions failed")
    for output_name, output_class in design.replay_plan.output_classes().items():
        output_hash = completion.payload["outputs"][output_name]
        if output_class == "durable_evidence":
            writer.evidence.verify(output_hash)
            if (writer.root / output_name).exists():
                raise RuntimeError("durable evidence was duplicated in the workspace")
        else:
            target = writer.root / output_name
            if not target.is_file() or sha256(target.read_bytes()).hexdigest() != output_hash:
                raise RuntimeError("reproducible forest cache is absent or changed")
    return control


def study_close_summary(
    writer: StateWriter,
    design: ForestStudyDesign,
    *,
    initial_prefix: int,
) -> dict[str, Any]:
    verify_study_close_postconditions(writer, design)
    close = _operation_record(writer, STUDY_CLOSE_STEPS[-1].operation_id)
    return {
        "applied_step_count": len(STUDY_CLOSE_STEPS) - initial_prefix,
        "bootstrap_samples": design.replay_plan.bootstrap_samples,
        "candidate_created": False,
        "durable_output_count": 3,
        "executable_id": design.replay_plan.executable_id,
        "holdout_reveal_delta": 0,
        "initiative_id": INITIATIVE_ID,
        "mode": "study_close_checkpoint",
        "next_stage": "diagnose_after_exact_local_main_checkpoint",
        "reproducible_cache_count": 11,
        "report_sha256": design.report_hash,
        "schema": "p0_composite_audit_study_close.v1",
        "study_close_event_id": close.authority_event_id,
        "study_close_record_id": _study_close_record_id(writer),
        "study_close_revision": close.authority_sequence,
        "study_id": STUDY_ID,
        "trial_delta": 1,
    }


def run_study_close_stage(
    writer: StateWriter,
    *,
    design: ForestStudyDesign,
    repository_root: Path,
    predecessor_revision: int,
    predecessor_event_id: str,
) -> dict[str, Any]:
    prefix = inspect_operation_prefix(
        writer,
        predecessor_revision=predecessor_revision,
        predecessor_event_id=predecessor_event_id,
    )
    if prefix > len(STUDY_CLOSE_STEPS):
        raise RuntimeError("diagnosis already began; use the diagnose stage")
    initial_prefix = prefix
    for step_index in range(prefix, len(STUDY_CLOSE_STEPS)):
        observed = inspect_operation_prefix(
            writer,
            predecessor_revision=predecessor_revision,
            predecessor_event_id=predecessor_event_id,
        )
        if observed != step_index:
            raise RuntimeError("P0 composite audit prefix changed concurrently")
        _apply_study_close_step(
            writer,
            design=design,
            repository_root=repository_root,
            step_index=step_index,
        )
        advanced = inspect_operation_prefix(
            writer,
            predecessor_revision=predecessor_revision,
            predecessor_event_id=predecessor_event_id,
        )
        if advanced != step_index + 1:
            raise RuntimeError("P0 composite audit step did not advance exactly once")
    return study_close_summary(writer, design, initial_prefix=initial_prefix)


def _preserve_decision(design: ForestStudyDesign) -> PortfolioDecision:
    return PortfolioDecision(
        decision_id="DEC-P0-COMPOSITE-AUDIT-PRESERVE",
        chosen_option_id="preserve-composite-audit-axis",
        options=(
            DecisionOption(
                option_id="preserve-composite-audit-axis",
                action=PortfolioAction.PRESERVE,
                target_id=design.audit_axis.axis_id,
                expected_information_value=(
                    "retain supported audit integrity with confirmation still required"
                ),
                opportunity_cost="no candidate or prospective claim authority",
            ),
            DecisionOption(
                option_id="open-another-mechanism-now",
                action=PortfolioAction.NEW_MECHANISM,
                target_id=design.source_axis_id,
                expected_information_value="future prospective mechanism information",
                opportunity_cost="start another Initiative before closing this audit",
                omission_reason=(
                    "the bounded audit Initiative closes at its preserved diagnosis"
                ),
            ),
        ),
        rationale=(
            "the exact descriptive audit passed, but post-selection evidence cannot "
            "promote a candidate"
        ),
        commitment_batches=1,
    )


def _preserved_snapshot(design: ForestStudyDesign) -> PortfolioSnapshot:
    axes = tuple(
        replace(axis, status="preserved")
        if axis.axis_id == design.audit_axis.axis_id
        else axis
        for axis in design.expanded_snapshot.axes
    )
    return PortfolioSnapshot(
        mission_id=MISSION_ID,
        axes=axes,
        opportunity_cost_basis=(
            "preserve the supported descriptive audit while retaining every forest branch"
        ),
        research_intake_id=design.expanded_snapshot.research_intake_id,
        exhaustion_standard=design.expanded_snapshot.exhaustion_standard_value(),
    )


def _apply_diagnose_step(
    writer: StateWriter,
    *,
    design: ForestStudyDesign,
    step_index: int,
) -> TransitionResult:
    operation_id = DIAGNOSE_STEPS[step_index].operation_id
    close_record_id = _study_close_record_id(writer)
    if step_index == 0:
        return writer.record_study_diagnosis(
            diagnosis=StudyDiagnosis(
                study_id=STUDY_ID,
                study_close_record_id=close_record_id,
                evidence_state=EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION,
                confidence=DiagnosisConfidence.HIGH,
                rationale=(
                    "all preregistered audit integrity criteria passed under the exact "
                    "historical selection context"
                ),
                counterfactual=(
                    "a prospective independently registered family could change the "
                    "forward trading conclusion"
                ),
                reopen_condition=(
                    "reopen only under a new prospective protocol with independent "
                    "candidate evidence"
                ),
            ),
            operation_id=operation_id,
        )
    if step_index == 1:
        return writer.record_portfolio_decision(
            decision=_preserve_decision(design),
            operation_id=operation_id,
        )
    if step_index == 2:
        return writer.record_portfolio_snapshot(
            snapshot=_preserved_snapshot(design),
            operation_id=operation_id,
        )
    if step_index == 3:
        return writer.close_initiative(
            outcome="completed",
            operation_id=operation_id,
        )
    raise RuntimeError("unknown P0 composite audit diagnosis step")


def verify_diagnose_postconditions(
    writer: StateWriter, design: ForestStudyDesign
) -> None:
    control = _assert_common_scientific_boundary(writer)
    if (
        control["scientific"].get("active_initiative") is not None
        or control.get("next_action") != EXPECTED_FINAL_ACTION
    ):
        raise RuntimeError("diagnosed audit did not close INI-0017 at a stable boundary")
    preserved = _preserved_snapshot(design)
    with LocalIndex(writer.index_path) as index:
        head = index.event_head(f"portfolio:{MISSION_ID}")
        snapshot = None if head is None else index.get(head.record_kind, head.record_id)
        candidate = index.event_head(
            f"candidate:{design.replay_plan.executable_id}"
        )
    if (
        snapshot is None
        or snapshot.record_id != preserved.identity
        or candidate is not None
    ):
        raise RuntimeError("preserved Portfolio terminal projection is invalid")


def run_diagnose_stage(
    writer: StateWriter,
    *,
    design: ForestStudyDesign,
    predecessor_revision: int,
    predecessor_event_id: str,
    study_close_event_id: str,
    study_close_revision: int,
) -> dict[str, Any]:
    prefix = inspect_operation_prefix(
        writer,
        predecessor_revision=predecessor_revision,
        predecessor_event_id=predecessor_event_id,
    )
    close = _operation_record(writer, STUDY_CLOSE_STEPS[-1].operation_id)
    if (
        prefix < len(STUDY_CLOSE_STEPS)
        or close.authority_event_id != study_close_event_id
        or close.authority_sequence != study_close_revision
    ):
        raise RuntimeError("diagnosis arguments do not bind the exact Study-close authority")
    if prefix == len(STUDY_CLOSE_STEPS):
        control = writer.read_control()
        if (
            control is None
            or control.get("revision") != study_close_revision
            or control.get("heads", {}).get("journal", {}).get("event_id")
            != study_close_event_id
            or control.get("next_action", {}).get("study_close_record_id")
            != _study_close_record_id(writer)
        ):
            raise RuntimeError("Study-close checkpoint control head is not exact")
    writer._require_study_close_delivery_guard()
    initial_prefix = prefix
    for absolute_index in range(prefix, len(ALL_STEPS)):
        diagnose_index = absolute_index - len(STUDY_CLOSE_STEPS)
        observed = inspect_operation_prefix(
            writer,
            predecessor_revision=predecessor_revision,
            predecessor_event_id=predecessor_event_id,
        )
        if observed != absolute_index:
            raise RuntimeError("diagnosis prefix changed concurrently")
        _apply_diagnose_step(
            writer,
            design=design,
            step_index=diagnose_index,
        )
        advanced = inspect_operation_prefix(
            writer,
            predecessor_revision=predecessor_revision,
            predecessor_event_id=predecessor_event_id,
        )
        if advanced != absolute_index + 1:
            raise RuntimeError("diagnosis step did not advance exactly once")
    verify_diagnose_postconditions(writer, design)
    return {
        "applied_step_count": len(ALL_STEPS) - initial_prefix,
        "axis_id": AXIS_ID,
        "axis_status": "preserved",
        "candidate_created": False,
        "holdout_reveal_delta": 0,
        "initiative_id": INITIATIVE_ID,
        "mode": "diagnosed_and_initiative_closed",
        "next_action": EXPECTED_FINAL_ACTION,
        "report_sha256": design.report_hash,
        "schema": "p0_composite_audit_diagnosis.v1",
        "study_close_event_id": study_close_event_id,
        "study_close_revision": study_close_revision,
        "study_id": STUDY_ID,
    }


def _read_only_summary(
    writer: StateWriter,
    design: ForestStudyDesign,
    *,
    prefix: int,
) -> dict[str, Any]:
    classes = design.replay_plan.output_classes()
    return {
        "axis_count_after": len(design.expanded_snapshot.axes),
        "axis_count_before": len(design.prior_axes),
        "bootstrap_samples": design.replay_plan.bootstrap_samples,
        "candidate_eligible": False,
        "current_prefix": prefix,
        "diagnose_operation_count": len(DIAGNOSE_STEPS),
        "durable_output_count": sum(
            value == "durable_evidence" for value in classes.values()
        ),
        "executable_id": design.replay_plan.executable_id,
        "historical_context": design.replay_plan.historical_context.manifest(),
        "initiative_id": INITIATIVE_ID,
        "mode": "read_only_plan",
        "new_axis_id": AXIS_ID,
        "preregistered_plan_output": P0_COMPOSITE_PLAN_OUTPUT,
        "reproducible_cache_count": sum(
            value == "reproducible_cache" for value in classes.values()
        ),
        "report_sha256": design.report_hash,
        "schema": "p0_composite_audit_plan.v1",
        "study_close_operation_count": len(STUDY_CLOSE_STEPS),
        "study_id": STUDY_ID,
        "trial_delta": 1,
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or crash-resumably execute the P0 composite audit Study and "
            "its post-checkpoint diagnosis."
        )
    )
    parser.add_argument(
        "--stage",
        choices=("study-close", "diagnose"),
        help="omit for a read-only plan",
    )
    parser.add_argument("--study-close-event-id")
    parser.add_argument("--study-close-revision", type=int)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
    writer = StateWriter(ROOT, validation_registry=registry)
    writer.recover()
    report_hash, predecessor_revision, predecessor_event_id = (
        verify_production_preconditions(writer)
    )
    prefix = inspect_operation_prefix(
        writer,
        predecessor_revision=predecessor_revision,
        predecessor_event_id=predecessor_event_id,
    )
    base_snapshot_id = _base_snapshot_id(writer, prefix)
    design = build_forest_study_design(
        writer,
        report_hash=report_hash,
        base_snapshot_id=base_snapshot_id,
    )
    if arguments.stage is None:
        if (
            arguments.study_close_event_id is not None
            or arguments.study_close_revision is not None
        ):
            raise RuntimeError("Study-close authority arguments require diagnose stage")
        print(json.dumps(_read_only_summary(writer, design, prefix=prefix), sort_keys=True))
        return
    writer.permit_authority = PermitAuthority(
        PermitKeyStore(ROOT / "local" / "permit.key").load_or_create()
    )
    if arguments.stage == "study-close":
        if (
            arguments.study_close_event_id is not None
            or arguments.study_close_revision is not None
        ):
            raise RuntimeError("Study-close stage does not accept checkpoint arguments")
        summary = run_study_close_stage(
            writer,
            design=design,
            repository_root=ROOT,
            predecessor_revision=predecessor_revision,
            predecessor_event_id=predecessor_event_id,
        )
        print(json.dumps(summary, sort_keys=True))
        return
    if (
        arguments.study_close_event_id is None
        or arguments.study_close_revision is None
    ):
        raise RuntimeError(
            "diagnose stage requires exact --study-close-event-id and "
            "--study-close-revision"
        )
    summary = run_diagnose_stage(
        writer,
        design=design,
        predecessor_revision=predecessor_revision,
        predecessor_event_id=predecessor_event_id,
        study_close_event_id=arguments.study_close_event_id,
        study_close_revision=arguments.study_close_revision,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
