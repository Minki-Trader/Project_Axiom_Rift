from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.core.canonical import canonical_bytes, parse_canonical  # noqa: E402
from axiom_rift.core.identity import canonical_digest  # noqa: E402
from axiom_rift.operations.replay_projection import (  # noqa: E402
    ReplayAuthorityError,
    obligation_heads,
    replay_evidence_record_ids,
    require_satisfaction_invalidation_record,
)
from axiom_rift.operations.running_job import RunningJobExecution  # noqa: E402
from axiom_rift.operations.running_job_context import (  # noqa: E402
    running_job_execution_context_dependency_paths,
)
from axiom_rift.operations.scientific_history import (  # noqa: E402
    HistoricalBatchFamilyObservation,
    HistoricalFamilyMemberExpectation,
    project_historical_batch_family_observation,
)
from axiom_rift.operations.strict_operation_chain import (  # noqa: E402
    OperationStep,
    inspect_operation_prefix,
    stage_bounds,
)
from axiom_rift.operations.validation import (  # noqa: E402
    EvidenceValidatorRegistry,
)
from axiom_rift.operations.writer import (  # noqa: E402
    RecoveryRequired,
    StateWriter,
)
from axiom_rift.research import data as data_module  # noqa: E402
from axiom_rift.research import adjudication as adjudication_module  # noqa: E402
from axiom_rift.research import discovery as discovery_module  # noqa: E402
from axiom_rift.research import evidence_proofs as evidence_proofs_module  # noqa: E402
from axiom_rift.research import selection_inference as selection_module  # noqa: E402
from axiom_rift.research import scientific_trace as scientific_trace_module  # noqa: E402
from axiom_rift.research import validation_v2 as validation_v2_module  # noqa: E402
from axiom_rift.research.analog_state_family import (  # noqa: E402
    AnalogFamilyConfiguration,
    analog_family_executable,
    analog_family_executable_map,
    analog_replay_controlled_chassis,
)
from axiom_rift.research.historical_analog_family_stu0061 import (  # noqa: E402
    STU0061_ANALOG_FAMILY as P1_STU0061_ANALOG_FAMILY,
)
from axiom_rift.research import analog_state_family as family_module  # noqa: E402
from axiom_rift.research import analog_state_replay as replay_module  # noqa: E402
from axiom_rift.research import analog_state_trace as trace_module  # noqa: E402
from axiom_rift.research.analog_state_replay import (  # noqa: E402
    ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME,
    CALLABLE_IDENTITY,
    STU0061_REPLAY_CRITERION_IDS,
    AnalogReplayPlan,
    build_analog_replay_plan,
    execute_analog_replay_job,
    validated_stu0061_recomputed_criterion_ids,
    verify_analog_family_trace_cache_producer,
)
from axiom_rift.research.analog_state_trace import (  # noqa: E402
    ANALOG_REPLAY_CLAIMS,
    ANALOG_REPLAY_CRITERIA,
    ANALOG_REPLAY_EVIDENCE_MODES,
    ANALOG_REPLAY_PRIOR_GLOBAL_EXPOSURE_COUNT,
)
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID  # noqa: E402
from axiom_rift.research.effective_axis import (  # noqa: E402
    EffectiveAxisStatus,
)
from axiom_rift.operations.effective_axis_projection import (  # noqa: E402
    effective_axis_resolutions,
)
from axiom_rift.research.governance import (  # noqa: E402
    DiagnosisConfidence,
    EvidenceState,
    ResearchLayer,
    StudyDiagnosis,
)
from axiom_rift.research.portfolio import (  # noqa: E402
    BatchSpec,
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
    DecisionOption,
    PortfolioAction,
    PortfolioAxis,
    PortfolioDecision,
    PortfolioSnapshot,
)
from axiom_rift.research.portfolio_projection import (  # noqa: E402
    PortfolioProjectionError,
    component_surface_registry,
    portfolio_axes_from_projection,
    portfolio_decision_from_projection,
)
from axiom_rift.research.replay_obligation import (  # noqa: E402
    ReplayDeferral,
    ReplayDeferralBasis,
    ReplayDeferralBasisKind,
    ReplayDeferralExecutionBinding,
    ReplayResolutionScope,
    ReplayResumeCondition,
    ReplayResumeConditionKind,
    ReplaySatisfaction,
    historical_replay_obligation_from_identity_payload,
)
from axiom_rift.research.trials import NegativeMemory, TrialAccountant  # noqa: E402
from axiom_rift.research.validation_v2 import (  # noqa: E402
    SCIENTIFIC_VALIDATION_V2_DEPENDENCIES,
    ScientificAdjudicationValidatorV2,
)
from axiom_rift.operations.permits import (  # noqa: E402
    Permit,
    PermitAuthority,
    PermitKind,
    PermitKeyStore,
    SubjectKind,
)
from axiom_rift.storage.index import (  # noqa: E402
    IndexRecord,
    LocalIndex,
    LocalIndexView,
)


MISSION_ID = "MIS-0006"
INITIATIVE_ID = "INI-0018"
STUDY_ID = "STU-0106"
BATCH_DISPLAY_ID = "BAT-0106"
AXIS_ID = "axis-stu0061-analog-state-replay-bridge"
OPERATION_PREFIX = "p1-stu0061-replay-v2-"
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"
JOB_PROTOCOL = "python.source.analog_state_replay.v1"
EXPECTED_CORRECTION_REVISION = 4938
CORRECTION_OPERATION_IDS = (
    "project-goal-audit-v2-authority",
    "project-goal-audit-v2-activate-protocol",
    "project-goal-audit-v2-record-replay-correction",
)
TARGET_OBLIGATION_ID = (
    "historical-replay-obligation:"
    "56799cac8878850c33c0fe59b35ae43425d8ea0f2446f3db1db66c592f63adc8"
)
TARGET_ORIGINAL_EXECUTABLE_ID = (
    "executable:61a3e085beb97af8ab8251125463bd3106cdebdbac511915b0434f07f14589e8"
)


@dataclass(frozen=True, slots=True)
class CorrectionBoundary:
    revision: int
    event_id: str


@dataclass(frozen=True, slots=True)
class ReplayMember:
    ordinal: int
    configuration: AnalogFamilyConfiguration
    executable: Any
    replay_plan: AnalogReplayPlan

    @property
    def label(self) -> str:
        return f"member-{self.ordinal:02d}"


def _canonical_statistical_family_ids(
    members: Sequence[ReplayMember],
) -> tuple[str, ...]:
    """Return family-set order without changing member execution order."""

    executable_ids = tuple(member.executable.identity for member in members)
    if not executable_ids or len(set(executable_ids)) != len(executable_ids):
        raise ValueError(
            "STU-0061 statistical family requires unique Executables"
        )
    return tuple(sorted(executable_ids))


@dataclass(frozen=True, slots=True)
class ReplayInterpretation:
    all_original_criteria_recomputed: bool
    close_outcome: str
    diagnosis_state: EvidenceState
    disposition: PortfolioAction
    reason_code: str


@dataclass(frozen=True, slots=True)
class P1ReplayDesign:
    base_snapshot_id: str
    prior_axes: tuple[PortfolioAxis, ...]
    source_axis_id: str
    replay_axis: PortfolioAxis
    bridge_decision: PortfolioDecision
    expanded_snapshot: PortfolioSnapshot
    work_decision: PortfolioDecision
    members: tuple[ReplayMember, ...]
    question: Mapping[str, Any]
    proposal: Mapping[str, Any]
    batch_spec: BatchSpec
    controlled_chassis: Any
    historical_family: HistoricalBatchFamilyObservation

    def __post_init__(self) -> None:
        if not self.members or tuple(
            member.ordinal for member in self.members
        ) != tuple(range(1, len(self.members) + 1)):
            raise ValueError("STU-0061 replay members are not exactly ordered")
        concurrent_family = self.batch_spec.concurrent_family
        if (
            concurrent_family is None
            or concurrent_family.executable_ids
            != _canonical_statistical_family_ids(self.members)
        ):
            raise ValueError(
                "STU-0061 Batch statistical family is not canonical"
            )

    @property
    def target_member(self) -> ReplayMember:
        matches = tuple(
            member
            for member in self.members
            if member.configuration.historical_reference_executable_id
            == TARGET_ORIGINAL_EXECUTABLE_ID
        )
        if len(matches) != 1 or matches[0] is not self.members[-1]:
            raise RuntimeError("STU-0061 target replay member is not uniquely final")
        return matches[0]


def _payload_value_count(value: object, target: str) -> int:
    if value == target:
        return 1
    if isinstance(value, Mapping):
        return sum(_payload_value_count(item, target) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_payload_value_count(item, target) for item in value)
    return 0


def ordered_replay_members() -> tuple[ReplayMember, ...]:
    configurations = P1_STU0061_ANALOG_FAMILY.configurations()
    ordered = tuple(
        sorted(
            configurations,
            key=lambda item: (
                item.historical_reference_executable_id
                == TARGET_ORIGINAL_EXECUTABLE_ID,
                item.configuration_id,
            ),
        )
    )
    members = tuple(
        ReplayMember(
            ordinal=ordinal,
            configuration=configuration,
            executable=(executable := analog_family_executable(configuration)),
            replay_plan=build_analog_replay_plan(
                mission_id=MISSION_ID,
                study_id=STUDY_ID,
                executable_id=executable.identity,
            ),
        )
        for ordinal, configuration in enumerate(ordered, start=1)
    )
    references = tuple(
        member.configuration.historical_reference_executable_id
        for member in members
    )
    occurrence_vectors = tuple(
        tuple(
            _payload_value_count(
                member.executable.to_identity_payload(),
                str(reference),
            )
            for reference in references
        )
        for member in members
    )
    if (
        len(members) != 4
        or len(set(references)) != 4
        or references[-1] != TARGET_ORIGINAL_EXECUTABLE_ID
        or any(reference is None for reference in references)
        or members[0].executable.identity
        != str(trace_module.expected_analog_family_inventory()[0]["executable_id"])
        or set(analog_family_executable_map(P1_STU0061_ANALOG_FAMILY))
        != {member.executable.identity for member in members}
        or occurrence_vectors
        != tuple(
            tuple(1 if row == column else 0 for column in range(4))
            for row in range(4)
        )
    ):
        raise RuntimeError("STU-0061 replay family is not the exact four-member set")
    return members


def _require_historical_non_p1_exposure(
    writer: StateWriter,
    index: LocalIndex | LocalIndexView,
    members: Sequence[ReplayMember],
) -> HistoricalBatchFamilyObservation:
    """Recover STU-0106 only as immutable audit/exposure observation."""

    prior_floor = TrialAccountant.from_foundation(
        writer.foundation_root
    ).prior_global_multiplicity_floor
    observation = project_historical_batch_family_observation(
        index,
        prior_global_exposure_floor=prior_floor,
        study_id=STUDY_ID,
        batch_id=None,
        expected_members=tuple(
            HistoricalFamilyMemberExpectation(
                configuration_id=member.configuration.configuration_id,
                historical_reference_executable_id=str(
                    member.configuration.historical_reference_executable_id
                ),
            )
            for member in members
        ),
        expected_prior_global_exposure_count=(
            ANALOG_REPLAY_PRIOR_GLOBAL_EXPOSURE_COUNT
        ),
        # The legacy STU-0061 Executables predate embedded context fields.
        exposure_parameter_name=None,
    )
    return observation


def _projection_payloads(
    index: LocalIndex,
    members: Sequence[ReplayMember],
) -> tuple[Mapping[str, Any], ...]:
    payloads: list[Mapping[str, Any]] = [
        member.executable.to_identity_payload() for member in members
    ]
    for kind in ("trial", "portfolio-decision", "study-open", "portfolio-snapshot"):
        payloads.extend(record.payload for record in index.records_by_kind(kind))
    return tuple(payloads)


def _base_snapshot_id(writer: StateWriter) -> str:
    with LocalIndex.open_read_only(writer.index_path) as index:
        bridge_operation = index.get(
            "operation", OPERATION_PREFIX + "bridge-decision"
        )
        if bridge_operation is None:
            head = index.event_head(f"portfolio:{MISSION_ID}")
            snapshot_id = None if head is None else head.record_id
        else:
            result = bridge_operation.payload.get("result")
            decision_id = (
                None if not isinstance(result, Mapping) else result.get("decision_id")
            )
            decision = (
                None
                if not isinstance(decision_id, str)
                else index.get("portfolio-decision", decision_id)
            )
            snapshot_id = (
                None
                if decision is None
                else decision.payload.get("portfolio_snapshot_id")
            )
    if not isinstance(snapshot_id, str):
        raise RuntimeError("P1 replay base Portfolio snapshot is unavailable")
    return snapshot_id


def build_p1_replay_design(
    writer: StateWriter,
    *,
    base_snapshot_id: str | None = None,
) -> P1ReplayDesign:
    members = ordered_replay_members()
    chassis = analog_replay_controlled_chassis(P1_STU0061_ANALOG_FAMILY)
    snapshot_id = _base_snapshot_id(writer) if base_snapshot_id is None else base_snapshot_id
    with LocalIndex.open_read_only(writer.index_path) as index:
        historical_family = _require_historical_non_p1_exposure(
            writer,
            index,
            members,
        )
        snapshot_record = index.get("portfolio-snapshot", snapshot_id)
        if snapshot_record is None:
            raise RuntimeError("P1 replay base Portfolio projection is absent")
        components = component_surface_registry(_projection_payloads(index, members))
        prior_axes = portfolio_axes_from_projection(
            snapshot_record.payload["axes"], components
        )
        projected_axes = {
            item["axis_id"]: item for item in snapshot_record.payload["axes"]
        }
        axis_resolutions = effective_axis_resolutions(
            index,
            tuple(projected_axes[axis.axis_id] for axis in prior_axes),
        )
        selectable = tuple(
            axis
            for axis, resolution in zip(
                prior_axes,
                axis_resolutions,
                strict=True,
            )
            if resolution.status is EffectiveAxisStatus.SELECTABLE
        )
    if any(axis.axis_id == AXIS_ID for axis in prior_axes):
        raise RuntimeError("P1 replay bridge axis predates its operation chain")
    if not selectable:
        raise RuntimeError("P1 replay lacks one selectable Portfolio bridge target")
    source_axis = selectable[0]
    replay_axis = PortfolioAxis(
        axis_id=AXIS_ID,
        causal_question=(
            "Does an exact prospective reconstruction of the four-member STU-0061 "
            "analog family recompute every original criterion without leakage?"
        ),
        mechanism_family="prospective-stu0061-analog-family-replay",
        primary_research_layer=ResearchLayer.SYNTHESIS,
        system_architecture_family=chassis.architecture.identity,
        changed_domains=tuple(chassis.changed_domains),
        controlled_domains=tuple(chassis.controlled_domains),
        why_now=(
            "the audit left STU-0061 as the highest-information P1 replay and the "
            "registered family restores its exact four-way control surface"
        ),
        stop_or_reopen_condition=(
            "stop after all four registered members; reopen only under the typed "
            "ReplayDeferral resume condition or new registered development material"
        ),
        architecture_chassis=chassis.architecture,
    )
    bridge_decision = PortfolioDecision(
        decision_id="DEC-P1-STU0061-BRIDGE",
        chosen_option_id="add-stu0061-replay-bridge",
        options=(
            DecisionOption(
                option_id="add-stu0061-replay-bridge",
                action=PortfolioAction.NEW_MECHANISM,
                target_id=source_axis.axis_id,
                expected_information_value=(
                    "high because one exact four-member replay can resolve a bounded P1 duty"
                ),
                opportunity_cost="one bounded four-Job concurrent family",
            ),
            DecisionOption(
                option_id="continue-unrelated-forest",
                action=PortfolioAction.PRESERVE,
                target_id=source_axis.axis_id,
                expected_information_value="valid unrelated forest work remains available",
                opportunity_cost="leave the selected P1 obligation pending",
                omission_reason=(
                    "the typed P1 queue grants this bounded replay its current opportunity"
                ),
            ),
        ),
        rationale=(
            "add one new-mechanism bridge without mutating or reinterpreting prior axes"
        ),
        commitment_batches=1,
    )
    expanded_snapshot = PortfolioSnapshot(
        mission_id=MISSION_ID,
        axes=(*prior_axes, replay_axis),
        opportunity_cost_basis=(
            "retain the complete forest and spend one Batch on exact STU-0061 replay"
        ),
        research_intake_id=snapshot_record.payload.get("research_intake_id"),
        exhaustion_standard=snapshot_record.payload.get("exhaustion_standard"),
    )
    work_decision = PortfolioDecision(
        decision_id="DEC-P1-STU0061-REPLAY",
        chosen_option_id="run-exact-stu0061-family",
        options=(
            DecisionOption(
                option_id="run-exact-stu0061-family",
                action=PortfolioAction.SYNTHESIZE,
                target_id=replay_axis.axis_id,
                expected_information_value=(
                    "highest bounded value from exact original-criterion recomputation"
                ),
                opportunity_cost="four sequential Jobs under one concurrent family",
            ),
            DecisionOption(
                option_id="defer-exact-stu0061-family",
                action=PortfolioAction.NEW_MECHANISM,
                target_id=replay_axis.axis_id,
                expected_information_value="no immediate STU-0061 resolution",
                opportunity_cost="retain unresolved historical uncertainty",
                omission_reason="the required family is locally executable now",
            ),
        ),
        rationale=(
            "select only the exact STU-0061 P1 obligation while other P1 duties remain pending"
        ),
        commitment_batches=1,
        baseline_executable=chassis.baseline_executable,
        replay_obligation_ids=(TARGET_OBLIGATION_ID,),
    )
    question = {
        "causal_question": replay_axis.causal_question,
        "changed_variables": [item.value for item in chassis.changed_domains],
        "controlled_variables": [item.value for item in chassis.controlled_domains],
        "done_conditions": [
            "all four preregistered family members are evaluated",
            "the exact original STU-0061 criteria are recomputed",
            "no candidate or holdout authority is created",
        ],
        "evidence_modes": list(ANALOG_REPLAY_EVIDENCE_MODES),
    }
    proposal = {
        "candidate_eligible": False,
        "concurrent_family": P1_STU0061_ANALOG_FAMILY.manifest(),
        "historical_obligation_id": TARGET_OBLIGATION_ID,
        "mechanism": "exact_stu0061_analog_family_reconstruction",
        "original_study_id": "STU-0061",
    }
    study_hash = writer.study_input_hash(
        question=question,
        material_identity=OBSERVED_MATERIAL_ID,
        semantic_proposal=proposal,
        controlled_chassis=chassis,
        portfolio_axis_id=replay_axis.axis_id,
        portfolio_axis_identity=replay_axis.identity,
        portfolio_decision_id=work_decision.identity,
    )
    batch_spec = BatchSpec(
        batch_id=BATCH_DISPLAY_ID,
        study_id=STUDY_ID,
        study_hash=study_hash,
        display_name="STU-0061 exact analog replay family",
        max_trials=4,
        max_compute_seconds=14_400,
        max_wall_seconds=21_600,
        stop_rule="stop only after the exact four registered family members",
        source_contract_ids=(),
        concurrent_family=ConcurrentFamilyManifest(
            evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
            executable_ids=_canonical_statistical_family_ids(members),
        ),
        acceptance_profile={
            "candidate_authority": "none",
            "exact_original_criteria": list(STU0061_REPLAY_CRITERION_IDS),
            "replay_obligation_id": TARGET_OBLIGATION_ID,
        },
        adaptive_basis={
            "uncertainty": "one historical P1 criterion family is unresolved",
            "causal_complexity": "two profiles by two signal signs",
            "surface_curvature": "exact factorial family; no adaptive additions",
            "compute_cost": "four bounded sequential Jobs",
            "expected_information_value": "resolve or exactly defer STU-0061",
            "portfolio_opportunity_cost": "six other P1 duties remain schedulable",
        },
    )
    design = P1ReplayDesign(
        base_snapshot_id=snapshot_id,
        prior_axes=prior_axes,
        source_axis_id=source_axis.axis_id,
        replay_axis=replay_axis,
        bridge_decision=bridge_decision,
        expanded_snapshot=expanded_snapshot,
        work_decision=work_decision,
        members=members,
        question=question,
        proposal=proposal,
        batch_spec=batch_spec,
        controlled_chassis=chassis,
        historical_family=historical_family,
    )
    design.target_member
    return design


def _require_current_prospective_execution_family(
    design: P1ReplayDesign,
) -> None:
    """Forbid historical payload substitution into a mutating execution."""

    current_ids = tuple(member.executable.identity for member in design.members)
    if design.historical_family.family_executable_ids != current_ids:
        raise RuntimeError(
            "STU-0106 is an audit-only historical family; current execution "
            "must use the successor STU-0112 workflow"
        )


def _scientific_facts(completion: IndexRecord) -> Mapping[str, object] | None:
    scientific = completion.payload.get("scientific")
    if not isinstance(scientific, Mapping):
        return None
    adjudication = scientific.get("adjudication")
    modes = scientific.get("executed_evidence_modes")
    if not isinstance(adjudication, Mapping) or not isinstance(modes, list):
        return None
    return {
        "executed_evidence_modes": modes,
        "scientific_adjudication": adjudication,
    }


def interpret_replay_completion(completion: IndexRecord) -> ReplayInterpretation:
    facts = _scientific_facts(completion)
    adjudication = None if facts is None else facts.get("scientific_adjudication")
    recomputed = False
    if facts is not None:
        try:
            recomputed = (
                validated_stu0061_recomputed_criterion_ids(facts)
                == STU0061_REPLAY_CRITERION_IDS
            )
        except ValueError:
            recomputed = False
    state = (
        None
        if not isinstance(adjudication, Mapping)
        else adjudication.get("state")
    )
    if recomputed and state in {"confirmed", "frontier", "partial_positive"}:
        return ReplayInterpretation(
            all_original_criteria_recomputed=recomputed,
            close_outcome="preserved",
            diagnosis_state=EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION,
            disposition=PortfolioAction.PRESERVE,
            reason_code=(
                "exact_original_criteria_recomputed"
                if recomputed
                else "original_criterion_recomputation_incomplete"
            ),
        )
    if recomputed and state == "contradicted":
        return ReplayInterpretation(
            all_original_criteria_recomputed=recomputed,
            close_outcome="pruned",
            diagnosis_state=EvidenceState.STABILITY_CONCENTRATION,
            disposition=PortfolioAction.PRUNE,
            reason_code=(
                "exact_original_criteria_recomputed_negative"
                if recomputed
                else "original_criterion_recomputation_incomplete"
            ),
        )
    return ReplayInterpretation(
        all_original_criteria_recomputed=False,
        close_outcome="not_evaluable",
        diagnosis_state=EvidenceState.NOT_IDENTIFIABLE,
        disposition=PortfolioAction.PRESERVE,
        reason_code=(
            "original_criterion_recomputation_incomplete"
            if facts is not None
            else "original_criterion_recomputation_unavailable"
        ),
    )


def _operation_record(writer: StateWriter, operation_id: str) -> IndexRecord:
    with LocalIndex.open_read_only(writer.index_path) as index:
        record = index.get("operation", operation_id)
    if record is None or record.status != "success":
        raise RuntimeError(f"operation is absent or unsuccessful: {operation_id}")
    return record


def _operation_result(
    writer: StateWriter,
    operation_id: str,
) -> Mapping[str, Any]:
    result = _operation_record(writer, operation_id).payload.get("result")
    if not isinstance(result, Mapping):
        raise RuntimeError(f"operation result is absent: {operation_id}")
    return result


def _permit_from_operation(writer: StateWriter, operation_id: str) -> Permit:
    permit = _operation_result(writer, operation_id).get("permit")
    if not isinstance(permit, Mapping):
        raise RuntimeError(f"permit operation result is malformed: {operation_id}")
    return Permit.from_mapping(permit)


def _member_completion(
    writer: StateWriter,
    member: ReplayMember,
) -> IndexRecord | None:
    operation_id = OPERATION_PREFIX + member.label + "-complete-job"
    with LocalIndex.open_read_only(writer.index_path) as index:
        operation = index.get("operation", operation_id)
        result = None if operation is None else operation.payload.get("result")
        completion_id = (
            None
            if not isinstance(result, Mapping)
            else result.get("completion_record_id")
        )
        return (
            None
            if not isinstance(completion_id, str)
            else index.get("job-completed", completion_id)
        )


def operation_steps(
    writer: StateWriter | None = None,
    *,
    design: P1ReplayDesign | None = None,
    failed_member_ordinals: Sequence[int] = (),
    replay_recomputed: bool = False,
) -> tuple[OperationStep, ...]:
    members = ordered_replay_members() if design is None else design.members
    failed = set(failed_member_ordinals)
    if writer is not None:
        failed = {
            member.ordinal
            for member in members
            if (
                (completion := _member_completion(writer, member)) is not None
                and isinstance(completion.payload.get("scientific"), Mapping)
                and completion.payload["scientific"].get("verdict") == "failed"
            )
        }
        target = _member_completion(writer, members[-1])
        replay_recomputed = (
            target is not None
            and interpret_replay_completion(
                target
            ).all_original_criteria_recomputed
        )
    steps: list[OperationStep] = [
        OperationStep(OPERATION_PREFIX + "open-initiative", "initiative_opened", "study-close"),
        OperationStep(OPERATION_PREFIX + "bridge-decision", "portfolio_decision_recorded", "study-close"),
        OperationStep(OPERATION_PREFIX + "expanded-snapshot", "portfolio_snapshot_recorded", "study-close"),
        OperationStep(OPERATION_PREFIX + "replay-decision", "portfolio_decision_recorded", "study-close"),
        OperationStep(OPERATION_PREFIX + "study-permit", "permit_issued", "study-close"),
        OperationStep(OPERATION_PREFIX + "open-study", "study_opened", "study-close"),
        OperationStep(OPERATION_PREFIX + "batch-permit", "permit_issued", "study-close"),
        OperationStep(OPERATION_PREFIX + "open-batch", "batch_opened", "study-close"),
    ]
    for member in members:
        steps.append(
            OperationStep(
                OPERATION_PREFIX + member.label + "-register-trial",
                "trial_registered",
                "study-close",
            )
        )
    for member in members:
        stem = OPERATION_PREFIX + member.label
        steps.extend(
            (
                OperationStep(stem + "-declare-job", "job_declared", "study-close"),
                OperationStep(stem + "-job-permit", "permit_issued", "study-close"),
                OperationStep(stem + "-start-job", "job_started", "study-close"),
                OperationStep(stem + "-complete-job", "job_completed", "study-close"),
            )
        )
        if member.ordinal in failed:
            steps.append(
                OperationStep(
                    stem + "-negative-memory",
                    "negative_memory_recorded",
                    "study-close",
                )
            )
        steps.append(
            OperationStep(stem + "-judge-job", "job_evidence_judged", "study-close")
        )
    steps.extend(
        (
            OperationStep(OPERATION_PREFIX + "dispose-batch", "batch_disposed", "study-close"),
            OperationStep(OPERATION_PREFIX + "close-study", "study_closed", "study-close"),
            OperationStep(OPERATION_PREFIX + "diagnose-study", "study_diagnosis_recorded", "diagnose"),
            OperationStep(
                OPERATION_PREFIX + "resolve-replay",
                (
                    "historical_replay_obligations_resolved"
                    if replay_recomputed
                    else "historical_replay_obligations_deferred"
                ),
                "diagnose",
            ),
            OperationStep(OPERATION_PREFIX + "disposition-decision", "portfolio_decision_recorded", "diagnose"),
            OperationStep(OPERATION_PREFIX + "disposition-snapshot", "portfolio_snapshot_recorded", "diagnose"),
            OperationStep(OPERATION_PREFIX + "close-initiative", "initiative_closed", "diagnose"),
        )
    )
    return tuple(steps)


def validate_correction_predecessor(writer: StateWriter) -> CorrectionBoundary:
    from scripts.apply_project_goal_audit_v2 import (
        validate_completed_correction_ancestor,
    )

    summary = validate_completed_correction_ancestor(writer, root=writer.root)
    if summary.get("boundary_revision") != EXPECTED_CORRECTION_REVISION:
        raise RuntimeError("Project Goal audit V2 correction revision differs")
    with LocalIndex.open_read_only(writer.index_path) as index:
        operations = tuple(
            index.get("operation", operation_id)
            for operation_id in CORRECTION_OPERATION_IDS
        )
    expected_kinds = (
        "authority_migrated",
        "research_protocol_activated",
        "historical_replay_correction_recorded",
    )
    for offset, (operation, event_kind) in enumerate(
        zip(operations, expected_kinds, strict=True),
        start=1,
    ):
        if (
            operation is None
            or operation.status != "success"
            or operation.authority_sequence != 4935 + offset
            or operation.payload.get("event_kind") != event_kind
        ):
            raise RuntimeError("Project Goal audit V2 correction predecessor differs")
    final = operations[-1]
    assert final is not None and final.authority_event_id is not None
    if summary.get("boundary_event_id") != final.authority_event_id:
        raise RuntimeError("Project Goal audit V2 correction event differs")
    return CorrectionBoundary(
        revision=EXPECTED_CORRECTION_REVISION,
        event_id=final.authority_event_id,
    )


def require_stable_head(
    writer: StateWriter,
    *,
    explicit_recovery: bool,
) -> Mapping[str, Any]:
    try:
        return writer.require_stable_head()
    except RecoveryRequired as exc:
        if not explicit_recovery:
            raise RuntimeError(
                "stable-head validation failed; rerun the requested stage with --recover"
            ) from exc
        writer.recover()
        return writer.require_stable_head()


def inspect_replay_prefix(
    writer: StateWriter,
    *,
    design: P1ReplayDesign,
    boundary: CorrectionBoundary,
) -> tuple[int, tuple[OperationStep, ...]]:
    steps = operation_steps(writer, design=design)
    control = writer.read_control()
    if control is None:
        raise RuntimeError("P1 replay control is absent")
    with LocalIndex.open_read_only(writer.index_path) as index:
        prefix = inspect_operation_prefix(
            index=index,
            journal=writer.journal,
            steps=steps,
            operation_prefix=OPERATION_PREFIX,
            predecessor_sequence=boundary.revision,
            predecessor_event_id=boundary.event_id,
            current_sequence=control["heads"]["journal"]["sequence"],
        )
    current_ids = tuple(member.executable.identity for member in design.members)
    if design.historical_family.family_executable_ids != current_ids:
        if prefix != len(steps):
            raise RuntimeError(
                "STU-0106 historical audit chain is incomplete and cannot resume"
            )
        validate_historical_replay_prefix_semantics(
            writer,
            design=design,
            prefix=prefix,
            steps=steps,
        )
    else:
        validate_replay_prefix_semantics(
            writer,
            design=design,
            prefix=prefix,
            steps=steps,
        )
    return prefix, steps


def _implementation_dependency_paths() -> tuple[Path, ...]:
    direct_modules = (
        adjudication_module,
        data_module,
        discovery_module,
        evidence_proofs_module,
        family_module,
        replay_module,
        scientific_trace_module,
        selection_module,
        trace_module,
        validation_v2_module,
    )
    paths = tuple(
        sorted(
            {
                Path(module.__file__).resolve()
                for module in direct_modules
            }
            | {
                Path(path).resolve()
                for path in SCIENTIFIC_VALIDATION_V2_DEPENDENCIES
            }
            | {
                Path(path).resolve()
                for path in running_job_execution_context_dependency_paths()
            }
        )
    )
    if any(not path.is_file() for path in paths):
        raise RuntimeError("analog replay implementation dependency is unavailable")
    return paths


def _implementation_identity(
    writer: StateWriter,
    *,
    materialize: bool,
) -> str:
    artifact_hashes = tuple(
        sorted(
            (
                writer.evidence.finalize(path.read_bytes()).sha256
                if materialize
                else sha256(path.read_bytes()).hexdigest()
            )
            for path in _implementation_dependency_paths()
        )
    )
    content = canonical_bytes(
        {
            "artifact_hashes": list(artifact_hashes),
            "callable_identity": CALLABLE_IDENTITY,
            "protocol": JOB_PROTOCOL,
            "schema": "job_implementation_evidence.v1",
        }
    )
    return (
        writer.evidence.finalize(content).sha256
        if materialize
        else sha256(content).hexdigest()
    )


def _require_completed_job_spec_compatible(
    writer: StateWriter,
    *,
    actual: object,
    expected_current: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Verify old Job semantics without assigning current code identities.

    Implementation bytes, their input hashes, and the validator identity are
    prospective version bindings. A completed Job retains those historical
    values after repository code advances. Every invariant field, validation
    plan, stored source closure, and stored input byte remains mandatory.
    """

    if not isinstance(actual, Mapping):
        raise RuntimeError("completed P1 replay Job specification is absent")
    versioned_fields = {
        "implementation_identity",
        "input_hashes",
        "scientific_binding",
    }
    if {
        key: value
        for key, value in actual.items()
        if key not in versioned_fields
    } != {
        key: value
        for key, value in expected_current.items()
        if key not in versioned_fields
    }:
        raise RuntimeError("completed P1 replay Job semantics drifted")
    actual_binding = actual.get("scientific_binding")
    expected_binding = expected_current.get("scientific_binding")
    if not isinstance(actual_binding, Mapping) or not isinstance(
        expected_binding, Mapping
    ):
        raise RuntimeError("completed P1 replay scientific binding is absent")
    if {
        key: value
        for key, value in actual_binding.items()
        if key != "validator_id"
    } != {
        key: value
        for key, value in expected_binding.items()
        if key != "validator_id"
    }:
        raise RuntimeError("completed P1 replay scientific plan drifted")
    validator_id = actual_binding.get("validator_id")
    validator_digest = (
        validator_id.removeprefix("validator:")
        if isinstance(validator_id, str)
        else ""
    )
    if len(validator_digest) != 64 or any(
        character not in "0123456789abcdef"
        for character in validator_digest
    ):
        raise RuntimeError("completed P1 replay validator identity is invalid")
    inputs = actual.get("input_hashes")
    if (
        not isinstance(inputs, list)
        or inputs != sorted(set(inputs))
        or any(
            type(value) is not str
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in inputs
        )
    ):
        raise RuntimeError("completed P1 replay Job inputs are invalid")
    try:
        writer.evidence.read_verified(
            str(actual_binding["validation_plan_hash"])
        )
        writer._require_job_implementation_evidence(
            actual,
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(
            "completed P1 replay Job source closure is unavailable"
        ) from exc
    return actual_binding


def _job_cache_contract(
    writer: StateWriter,
    member: ReplayMember,
) -> tuple[bool, tuple[str, ...], dict[str, str], tuple[str, ...]]:
    members = ordered_replay_members()
    matching = tuple(
        expected
        for expected in members
        if expected.executable.identity == member.executable.identity
    )
    if len(matching) != 1 or matching[0].ordinal != member.ordinal:
        raise RuntimeError("analog replay member ordinal identity drifted")
    produce_family_cache = member.ordinal == 1
    expected_outputs = member.replay_plan.expected_outputs(
        produce_family_cache=produce_family_cache
    )
    output_classes = member.replay_plan.expected_output_classes(
        produce_family_cache=produce_family_cache
    )
    if produce_family_cache:
        return (
            True,
            expected_outputs,
            output_classes,
            member.replay_plan.job_input_hashes(),
        )

    first_member = members[0]
    completion = _member_completion(writer, first_member)
    outputs = None if completion is None else completion.payload.get("outputs")
    first_expected = set(
        first_member.replay_plan.expected_outputs(produce_family_cache=True)
    )
    if (
        completion is None
        or completion.status != "success"
        or not isinstance(outputs, Mapping)
        or set(outputs) != first_expected
    ):
        raise RuntimeError(
            "analog replay cache consumers lack the exact first completion"
        )
    cache_hash = outputs.get(ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME)
    manifest_hash = outputs.get(first_member.replay_plan.output_names["trace"])
    for label, digest in (
        ("family cache", cache_hash),
        ("family cache producer trace", manifest_hash),
    ):
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise RuntimeError(f"analog replay {label} hash is invalid")
    assert isinstance(cache_hash, str) and isinstance(manifest_hash, str)
    input_hashes = member.replay_plan.job_input_hashes(
        family_trace_cache_hash=cache_hash,
        family_trace_manifest_hash=manifest_hash,
    )
    if (
        input_hashes.count(cache_hash) != 1
        or input_hashes.count(manifest_hash) != 1
    ):
        raise RuntimeError("analog replay cache inputs are not bound exactly once")
    return False, expected_outputs, output_classes, input_hashes


def build_job_spec(
    writer: StateWriter,
    member: ReplayMember,
    *,
    materialize_evidence: bool = True,
) -> Mapping[str, Any]:
    plan_content = canonical_bytes(dict(member.replay_plan.plan))
    plan_hash = sha256(plan_content).hexdigest()
    if plan_hash != member.replay_plan.plan_hash:
        raise RuntimeError("analog replay validation plan identity drifted")
    if materialize_evidence:
        writer.evidence.finalize(plan_content)
    (
        _produce_family_cache,
        expected_outputs,
        output_classes,
        input_hashes,
    ) = _job_cache_contract(writer, member)
    return {
        "budget": {"compute_seconds": 3_600, "wall_seconds": 5_400},
        "callable_identity": CALLABLE_IDENTITY,
        "evidence_subject": {"kind": "Executable", "id": member.executable.identity},
        "expected_outputs": list(expected_outputs),
        "implementation_identity": _implementation_identity(
            writer,
            materialize=materialize_evidence,
        ),
        "input_hashes": list(input_hashes),
        "log_path": f"local/jobs/p1-stu0061/{member.label}.log",
        "output_classes": output_classes,
        "resume_action": "continue_batch" if member.ordinal < 4 else "stop_batch",
        "scientific_binding": member.replay_plan.scientific_binding(),
        "timeout_or_stop_rule": "finish the exact registered analog replay member",
        "worker_claims": [],
    }


def _study_permit(writer: StateWriter, design: P1ReplayDesign) -> Permit:
    study_hash = writer.study_input_hash(
        question=design.question,
        material_identity=OBSERVED_MATERIAL_ID,
        semantic_proposal=design.proposal,
        controlled_chassis=design.controlled_chassis,
        portfolio_axis_id=design.replay_axis.axis_id,
        portfolio_axis_identity=design.replay_axis.identity,
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
                    f"axis:{design.replay_axis.identity}",
                    f"baseline:{design.controlled_chassis.baseline_executable.identity}",
                    f"chassis:{design.controlled_chassis.architecture.identity}",
                    f"snapshot:{design.expanded_snapshot.identity}",
                }
            )
        ),
        expires_at_utc=PERMIT_EXPIRY_UTC,
        one_shot=True,
        operation_id=OPERATION_PREFIX + "study-permit",
    )


def _negative_memory(
    writer: StateWriter,
    member: ReplayMember,
) -> NegativeMemory:
    completion = _member_completion(writer, member)
    if completion is None:
        raise RuntimeError("negative memory lacks its exact member completion")
    return NegativeMemory(
        executable_identity=member.executable.identity,
        scope=f"stu0061_replay_{member.configuration.configuration_id}",
        evidence_references=(completion.record_id,),
        reason=(
            "The registered STU-0061 replay member contradicted one or more "
            "preregistered criteria under the exact concurrent family."
        ),
        reopen_condition=(
            "Reopen only with newly registered development material or a materially "
            "different causal analog mechanism."
        ),
    )


def _initiative_objective() -> Mapping[str, Any]:
    return {
        "objective": "execute one exact STU-0061 P1 replay family",
        "bounds": {
            "batch_count": 1,
            "job_count": 4,
            "trial_count": 4,
            "wall_seconds": 21_600,
        },
        "done_conditions": [
            "four exact family members are evaluated",
            "the replay obligation is satisfied or exactly deferred",
            "no candidate or holdout authority is created",
        ],
    }


def _apply_study_close_step(
    writer: StateWriter,
    *,
    design: P1ReplayDesign,
    step: OperationStep,
    repository_root: Path,
    job_runner: Callable[..., Any],
) -> Any:
    operation_id = step.operation_id
    if operation_id == OPERATION_PREFIX + "open-initiative":
        return writer.open_initiative(
            initiative_id=INITIATIVE_ID,
            objective=_initiative_objective(),
            operation_id=operation_id,
        )
    if operation_id == OPERATION_PREFIX + "bridge-decision":
        return writer.record_portfolio_decision(
            decision=design.bridge_decision,
            operation_id=operation_id,
        )
    if operation_id == OPERATION_PREFIX + "expanded-snapshot":
        return writer.record_portfolio_snapshot(
            snapshot=design.expanded_snapshot,
            operation_id=operation_id,
        )
    if operation_id == OPERATION_PREFIX + "replay-decision":
        return writer.record_portfolio_decision(
            decision=design.work_decision,
            operation_id=operation_id,
        )
    if operation_id == OPERATION_PREFIX + "study-permit":
        return _study_permit(writer, design)
    if operation_id == OPERATION_PREFIX + "open-study":
        return writer.open_study(
            study_id=STUDY_ID,
            question=design.question,
            material_identity=OBSERVED_MATERIAL_ID,
            material_display_name="foundation observed development material",
            semantic_proposal=design.proposal,
            controlled_chassis=design.controlled_chassis,
            portfolio_axis_id=design.replay_axis.axis_id,
            portfolio_axis_identity=design.replay_axis.identity,
            portfolio_decision_id=design.work_decision.identity,
            permit=_permit_from_operation(
                writer, OPERATION_PREFIX + "study-permit"
            ),
            operation_id=operation_id,
        )
    if operation_id == OPERATION_PREFIX + "batch-permit":
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
    if operation_id == OPERATION_PREFIX + "open-batch":
        return writer.open_batch(
            batch_spec=design.batch_spec,
            permit=_permit_from_operation(
                writer, OPERATION_PREFIX + "batch-permit"
            ),
            operation_id=operation_id,
        )

    for member in design.members:
        stem = OPERATION_PREFIX + member.label
        if operation_id == stem + "-register-trial":
            return writer.register_trial(
                executable=member.executable,
                operation_id=operation_id,
            )
        if operation_id == stem + "-declare-job":
            result = writer.declare_job(
                spec=build_job_spec(writer, member),
                operation_id=operation_id,
            )
            if result.result.get("disposition") == "reuse_success":
                raise RuntimeError("P1 replay unexpectedly reused an earlier Job")
            return result
        if operation_id == stem + "-job-permit":
            declaration = _operation_result(writer, stem + "-declare-job")
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
        if operation_id == stem + "-start-job":
            return writer.start_job(
                permit=_permit_from_operation(writer, stem + "-job-permit"),
                operation_id=operation_id,
            )
        if operation_id == stem + "-complete-job":
            execution_payload = _operation_result(
                writer, stem + "-start-job"
            ).get("execution")
            if not isinstance(execution_payload, Mapping):
                raise RuntimeError("P1 replay Job execution binding is absent")
            packet = job_runner(
                repository_root=repository_root,
                execution=RunningJobExecution.from_mapping(execution_payload),
            )
            return writer.complete_job(
                outcome="success",
                output_manifest=packet.outputs(),
                operation_id=operation_id,
            )
        if operation_id == stem + "-negative-memory":
            return writer.record_negative_memory(
                memory=_negative_memory(writer, member),
                operation_id=operation_id,
            )
        if operation_id == stem + "-judge-job":
            completion = _member_completion(writer, member)
            if completion is None:
                raise RuntimeError("P1 replay Job judgement lacks completion")
            scientific = completion.payload.get("scientific")
            failed = (
                isinstance(scientific, Mapping)
                and scientific.get("verdict") == "failed"
            )
            memory_id = None
            if failed:
                memory_id = _operation_result(
                    writer, stem + "-negative-memory"
                ).get("negative_memory_id")
                if not isinstance(memory_id, str):
                    raise RuntimeError("P1 replay falsification lacks negative memory")
            return writer.judge_job_evidence(
                completion_record_id=completion.record_id,
                disposition=(
                    "continue_batch" if member.ordinal < 4 else "stop_batch"
                ),
                negative_memory_id=memory_id,
                operation_id=operation_id,
            )

    if operation_id == OPERATION_PREFIX + "dispose-batch":
        return writer.dispose_batch(
            outcome="completed",
            operation_id=operation_id,
        )
    if operation_id == OPERATION_PREFIX + "close-study":
        completion = _member_completion(writer, design.target_member)
        if completion is None:
            raise RuntimeError("P1 replay close lacks its target completion")
        interpretation = interpret_replay_completion(completion)
        return writer.close_study(
            outcome=interpretation.close_outcome,
            kpi_completion_record_id=completion.record_id,
            operation_id=operation_id,
        )
    raise RuntimeError(f"unknown P1 replay Study-close operation: {operation_id}")


def _study_close_record(writer: StateWriter) -> IndexRecord:
    close_operation = _operation_record(writer, OPERATION_PREFIX + "close-study")
    with LocalIndex.open_read_only(writer.index_path) as index:
        matches = tuple(
            record
            for record in index.records_by_kind("study-close")
            if record.subject == f"Study:{STUDY_ID}"
            and record.authority_sequence == close_operation.authority_sequence
            and record.authority_event_id == close_operation.authority_event_id
        )
    if len(matches) != 1:
        raise RuntimeError("P1 replay Study-close projection is ambiguous")
    return matches[0]


def _diagnosis(
    writer: StateWriter,
    design: P1ReplayDesign,
) -> StudyDiagnosis:
    completion = _member_completion(writer, design.target_member)
    if completion is None:
        raise RuntimeError("P1 replay diagnosis lacks target completion")
    interpretation = interpret_replay_completion(completion)
    state = completion.payload.get("scientific", {}).get("adjudication", {}).get(
        "state"
    )
    return StudyDiagnosis(
        study_id=STUDY_ID,
        study_close_record_id=_study_close_record(writer).record_id,
        evidence_state=interpretation.diagnosis_state,
        confidence=(
            DiagnosisConfidence.HIGH
            if interpretation.all_original_criteria_recomputed
            else DiagnosisConfidence.LOW
        ),
        rationale=(
            "The exact four-member family recomputed all original criteria; the "
            f"target scientific state is {state}."
            if interpretation.all_original_criteria_recomputed
            else "The exact original criterion inventory was unavailable or invalid."
        ),
        counterfactual=(
            "New registered development material could change the family state "
            "without changing this historical replay result."
        ),
        reopen_condition=(
            "Reopen only when repaired implementation or newly registered data "
            "permits the same exact four-member mapping and original criteria."
        ),
    )


def _diagnosis_record(writer: StateWriter) -> IndexRecord:
    result = _operation_result(writer, OPERATION_PREFIX + "diagnose-study")
    diagnosis_id = result.get("study_diagnosis_id")
    with LocalIndex.open_read_only(writer.index_path) as index:
        record = (
            None
            if not isinstance(diagnosis_id, str)
            else index.get("study-diagnosis", diagnosis_id)
        )
    if record is None:
        raise RuntimeError("P1 replay diagnosis projection is absent")
    return record


def _replay_resolution(
    writer: StateWriter,
    design: P1ReplayDesign,
) -> ReplaySatisfaction | ReplayDeferral:
    completion = _member_completion(writer, design.target_member)
    if completion is None:
        raise RuntimeError("P1 replay resolution lacks target completion")
    interpretation = interpret_replay_completion(completion)
    diagnosis = _diagnosis_record(writer)
    close_record = _study_close_record(writer)
    with LocalIndex.open_read_only(writer.index_path) as index:
        pairs = {
            obligation.identity: (obligation, head)
            for obligation, head in obligation_heads(index, mission_id=MISSION_ID)
        }
        pair = pairs.get(TARGET_OBLIGATION_ID)
        trial = index.get("trial", design.target_member.executable.identity)
        if pair is None or trial is None:
            raise RuntimeError("P1 replay obligation or target trial is absent")
        obligation, _ = pair
        evidence_ids = replay_evidence_record_ids(
            diagnosis=diagnosis,
            close_record=close_record,
            trial=trial,
        )
    if interpretation.all_original_criteria_recomputed:
        facts = _scientific_facts(completion)
        assert facts is not None
        criterion_ids = validated_stu0061_recomputed_criterion_ids(facts)
        if criterion_ids != obligation.criterion_ids:
            raise RuntimeError("recomputed criteria differ from replay obligation")
        return ReplaySatisfaction(
            obligation_id=TARGET_OBLIGATION_ID,
            resolution_scope=ReplayResolutionScope.SCIENTIFIC,
            portfolio_decision_id=design.work_decision.identity,
            replay_study_id=STUDY_ID,
            replay_executable_id=design.target_member.executable.identity,
            replay_study_close_record_id=close_record.record_id,
            study_diagnosis_id=diagnosis.record_id,
            satisfied_criterion_ids=criterion_ids,
            evidence_record_ids=evidence_ids,
        )
    return ReplayDeferral(
        obligation_id=TARGET_OBLIGATION_ID,
        basis=ReplayDeferralBasis(
            kind=ReplayDeferralBasisKind.STUDY_DIAGNOSIS,
            record_id=diagnosis.record_id,
            subject_id=STUDY_ID,
        ),
        reason_codes=(interpretation.reason_code,),
        resume_conditions=tuple(
            ReplayResumeCondition(
                kind=kind,
                protocol_id=JOB_PROTOCOL,
                original_executable_ids=tuple(
                    member.configuration.historical_reference_executable_id
                    for member in design.members
                ),
                criterion_ids=obligation.criterion_ids,
            )
            for kind in (
                ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL,
                ReplayResumeConditionKind.SAME_PROTOCOL_REPAIR,
            )
        ),
        execution_binding=ReplayDeferralExecutionBinding(
            portfolio_decision_id=design.work_decision.identity,
            replay_study_id=STUDY_ID,
            replay_executable_id=design.target_member.executable.identity,
            replay_study_close_record_id=close_record.record_id,
            study_diagnosis_id=diagnosis.record_id,
        ),
    )


def _disposition_decision(
    writer: StateWriter,
    design: P1ReplayDesign,
) -> PortfolioDecision:
    completion = _member_completion(writer, design.target_member)
    if completion is None:
        raise RuntimeError("P1 replay disposition lacks target completion")
    interpretation = interpret_replay_completion(completion)
    chosen_id = (
        "preserve-recomputed-replay"
        if interpretation.disposition is PortfolioAction.PRESERVE
        else "prune-recomputed-replay"
    )
    return PortfolioDecision(
        decision_id="DEC-P1-STU0061-DISPOSITION",
        chosen_option_id=chosen_id,
        options=(
            DecisionOption(
                option_id=chosen_id,
                action=interpretation.disposition,
                target_id=design.replay_axis.axis_id,
                expected_information_value=(
                    "retain exact partial support"
                    if interpretation.disposition is PortfolioAction.PRESERVE
                    else "retire this exact family while retaining its reopen condition"
                ),
                opportunity_cost="end this bounded replay Initiative",
            ),
            DecisionOption(
                option_id="open-adjacent-replay-variant",
                action=PortfolioAction.NEW_MECHANISM,
                target_id=design.replay_axis.axis_id,
                expected_information_value="unknown adjacent-search value",
                opportunity_cost="expand beyond the exact historical obligation",
                omission_reason=(
                    "the Initiative must not turn one bounded replay into adjacent tuning"
                ),
            ),
        ),
        rationale=(
            "separate replay completion from scientific state and dispose the axis honestly"
        ),
        commitment_batches=1,
    )


def _disposition_snapshot(
    writer: StateWriter,
    design: P1ReplayDesign,
) -> PortfolioSnapshot:
    decision = _disposition_decision(writer, design)
    status = "preserved" if decision.chosen.action is PortfolioAction.PRESERVE else "pruned"
    axes = tuple(
        replace(axis, status=status)
        if axis.axis_id == design.replay_axis.axis_id
        else axis
        for axis in design.expanded_snapshot.axes
    )
    return PortfolioSnapshot(
        mission_id=MISSION_ID,
        axes=axes,
        opportunity_cost_basis=(
            "close the bounded replay while retaining all unrelated forest branches"
        ),
        research_intake_id=design.expanded_snapshot.research_intake_id,
        exhaustion_standard=design.expanded_snapshot.exhaustion_standard_value(),
    )


def _apply_diagnose_step(
    writer: StateWriter,
    *,
    design: P1ReplayDesign,
    step: OperationStep,
) -> Any:
    operation_id = step.operation_id
    if operation_id == OPERATION_PREFIX + "diagnose-study":
        return writer.record_study_diagnosis(
            diagnosis=_diagnosis(writer, design),
            operation_id=operation_id,
        )
    if operation_id == OPERATION_PREFIX + "resolve-replay":
        resolution = _replay_resolution(writer, design)
        if isinstance(resolution, ReplaySatisfaction):
            return writer.resolve_historical_replay_obligations(
                satisfactions=(resolution,),
                operation_id=operation_id,
            )
        return writer.defer_historical_replay_obligations(
            deferrals=(resolution,),
            operation_id=operation_id,
        )
    if operation_id == OPERATION_PREFIX + "disposition-decision":
        return writer.record_portfolio_decision(
            decision=_disposition_decision(writer, design),
            operation_id=operation_id,
        )
    if operation_id == OPERATION_PREFIX + "disposition-snapshot":
        return writer.record_portfolio_snapshot(
            snapshot=_disposition_snapshot(writer, design),
            operation_id=operation_id,
        )
    if operation_id == OPERATION_PREFIX + "close-initiative":
        return writer.close_initiative(
            outcome="completed",
            operation_id=operation_id,
        )
    raise RuntimeError(f"unknown P1 replay diagnosis operation: {operation_id}")


def _require_identity_payload(
    record: IndexRecord | None,
    expected: Mapping[str, Any],
    *,
    label: str,
) -> IndexRecord:
    if record is None or any(
        record.payload.get(name) != value for name, value in expected.items()
    ):
        raise RuntimeError(f"completed P1 replay {label} identity drifted")
    return record


def _require_job_judgement_binding(
    index: LocalIndex,
    *,
    operation: IndexRecord,
    completion: IndexRecord,
    expected_disposition: str,
    expected_negative_memory_id: str | None,
    label: str,
) -> None:
    """Bind the compact operation result to its same-event decision record."""

    result = operation.payload.get("result")
    job_id = completion.payload.get("job_id")
    decisions = tuple(
        record
        for record in index.records_by_kind("job-evidence-decision")
        if record.subject == f"Job:{job_id}"
        and record.authority_sequence == operation.authority_sequence
        and record.authority_event_id == operation.authority_event_id
    )
    if (
        not isinstance(result, Mapping)
        or not isinstance(job_id, str)
        or result.get("job_id") != job_id
        or result.get("disposition") != expected_disposition
        or len(decisions) != 1
    ):
        raise RuntimeError(f"completed P1 replay {label} judgement drifted")
    decision = decisions[0]
    if (
        decision.status != expected_disposition
        or decision.fingerprint != completion.fingerprint
        or decision.payload
        != {
            "completion_record_id": completion.record_id,
            "negative_memory_id": expected_negative_memory_id,
        }
    ):
        raise RuntimeError(f"completed P1 replay {label} judgement drifted")


_HISTORICAL_DECISION_IDENTITY_FIELDS = frozenset(
    {
        "architecture_chassis",
        "architecture_chassis_identity",
        "baseline_executable",
        "baseline_executable_id",
        "chosen_option_id",
        "commitment_batches",
        "decision_id",
        "locks_future_portfolio",
        "options",
        "quant_team_review",
        "rationale",
        "recent_positive_lineage_id",
        "replay_obligation_ids",
        "schema",
    }
)


def _require_historical_digest(name: str, value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise RuntimeError(f"historical STU-0106 {name} digest is invalid")
    return value


def _historical_operation(
    index: LocalIndex | LocalIndexView,
    steps: Sequence[OperationStep],
    suffix: str,
    *,
    subject: str | None = None,
) -> tuple[IndexRecord, Mapping[str, Any]]:
    operation_id = OPERATION_PREFIX + suffix
    expected = tuple(step for step in steps if step.operation_id == operation_id)
    record = index.get("operation", operation_id)
    result = None if record is None else record.payload.get("result")
    if (
        len(expected) != 1
        or record is None
        or record.status != "success"
        or record.payload.get("event_kind") != expected[0].event_kind
        or not isinstance(result, Mapping)
        or (subject is not None and record.subject != subject)
    ):
        raise RuntimeError(
            f"historical STU-0106 operation ownership drifted: {suffix}"
        )
    return record, result


def _historical_portfolio_decision(
    index: LocalIndex | LocalIndexView,
    decision_id: object,
) -> IndexRecord:
    if type(decision_id) is not str:
        raise RuntimeError("historical STU-0106 Decision id is invalid")
    record = index.get("portfolio-decision", decision_id)
    if record is None:
        raise RuntimeError("historical STU-0106 Decision is absent")
    identity_payload = {
        name: value
        for name, value in record.payload.items()
        if name in _HISTORICAL_DECISION_IDENTITY_FIELDS
    }
    try:
        decision = portfolio_decision_from_projection(identity_payload)
    except PortfolioProjectionError as exc:
        raise RuntimeError(
            "historical STU-0106 Decision payload is malformed"
        ) from exc
    if decision.identity != decision_id or record.record_id != decision_id:
        raise RuntimeError(
            "historical STU-0106 Decision identity is inconsistent"
        )
    return record


def _historical_portfolio_snapshot(
    index: LocalIndex | LocalIndexView,
    snapshot_id: object,
) -> IndexRecord:
    if type(snapshot_id) is not str:
        raise RuntimeError("historical STU-0106 snapshot id is invalid")
    record = index.get("portfolio-snapshot", snapshot_id)
    if (
        record is None
        or record.subject != f"Mission:{MISSION_ID}"
        or record.record_id
        != "portfolio:"
        + canonical_digest(
            domain="portfolio-snapshot",
            payload=record.payload,
        )
    ):
        raise RuntimeError(
            "historical STU-0106 Portfolio snapshot is malformed"
        )
    return record


def _require_historical_chassis_identity(
    controlled: object,
) -> Mapping[str, Any]:
    if not isinstance(controlled, Mapping):
        raise RuntimeError("historical STU-0106 controlled chassis is absent")
    architecture = controlled.get("architecture")
    baseline = controlled.get("baseline_executable")
    components = controlled.get("controlled_component_identities")
    parameters = controlled.get("controlled_parameter_bindings")
    if (
        not isinstance(architecture, Mapping)
        or not isinstance(baseline, Mapping)
        or not isinstance(components, Mapping)
        or not isinstance(parameters, Mapping)
    ):
        raise RuntimeError("historical STU-0106 controlled chassis is malformed")
    architecture_family = "architecture-family:" + canonical_digest(
        domain="architecture-chassis",
        payload=architecture,
    )
    baseline_id = "executable:" + canonical_digest(
        domain="executable",
        payload=baseline,
    )
    controlled_id = "controlled-chassis:" + canonical_digest(
        domain="controlled-component-chassis",
        payload={
            "architecture_family": architecture_family,
            "controlled_components": dict(components),
            "controlled_parameter_bindings": dict(parameters),
            "schema": "controlled_component_chassis.v1",
        },
    )
    if (
        controlled.get("architecture_family") != architecture_family
        or controlled.get("baseline_executable_id") != baseline_id
        or controlled.get("controlled_chassis_identity") != controlled_id
    ):
        raise RuntimeError(
            "historical STU-0106 controlled chassis identity is inconsistent"
        )
    return controlled


def _require_historical_output_evidence(
    writer: StateWriter,
    *,
    completion: IndexRecord,
    result: Mapping[str, Any],
    declaration_spec: Mapping[str, Any],
) -> None:
    outputs = completion.payload.get("outputs")
    output_classes = completion.payload.get("output_classes")
    expected_outputs = declaration_spec.get("expected_outputs")
    if (
        not isinstance(outputs, Mapping)
        or not isinstance(output_classes, Mapping)
        or not isinstance(expected_outputs, list)
        or set(outputs) != set(output_classes)
        or set(outputs) != set(expected_outputs)
        or output_classes != declaration_spec.get("output_classes")
        or output_classes != result.get("output_classes")
    ):
        raise RuntimeError(
            "historical STU-0106 Job output inventory is inconsistent"
        )
    for output_name, output_hash in outputs.items():
        if type(output_name) is not str or not output_name.isascii():
            raise RuntimeError("historical STU-0106 output name is invalid")
        digest = _require_historical_digest("output", output_hash)
        output_class = output_classes.get(output_name)
        if output_class == "durable_evidence":
            writer.evidence.read_verified(digest)
        elif output_class != "reproducible_cache":
            raise RuntimeError(
                "historical STU-0106 output storage class is invalid"
            )


def _validate_historical_completed_replay_chain(
    writer: StateWriter,
    index: LocalIndex | LocalIndexView,
    *,
    design: P1ReplayDesign,
    steps: Sequence[OperationStep],
) -> None:
    """Audit immutable completed authority without rebuilding current identities."""

    family = design.historical_family
    if (
        family.study_id != STUDY_ID
        or family.prior_global_exposure_count
        != ANALOG_REPLAY_PRIOR_GLOBAL_EXPOSURE_COUNT
        or len(family.members) != 4
    ):
        raise RuntimeError("historical STU-0106 family observation is malformed")

    _open_initiative, initiative_result = _historical_operation(
        index,
        steps,
        "open-initiative",
        subject=f"Initiative:{INITIATIVE_ID}",
    )
    initiative = index.get("initiative-open", INITIATIVE_ID)
    if (
        initiative_result != {"initiative_id": INITIATIVE_ID}
        or initiative is None
        or initiative.subject != f"Initiative:{INITIATIVE_ID}"
        or initiative.status != "open"
    ):
        raise RuntimeError("historical STU-0106 Initiative is malformed")

    _bridge_operation, bridge_result = _historical_operation(
        index,
        steps,
        "bridge-decision",
        subject="Portfolio:active",
    )
    bridge = _historical_portfolio_decision(
        index,
        bridge_result.get("decision_id"),
    )
    base_snapshot = _historical_portfolio_snapshot(
        index,
        bridge.payload.get("portfolio_snapshot_id"),
    )
    _expanded_operation, expanded_result = _historical_operation(
        index,
        steps,
        "expanded-snapshot",
        subject=f"Mission:{MISSION_ID}",
    )
    expanded = _historical_portfolio_snapshot(
        index,
        expanded_result.get("portfolio_snapshot_id"),
    )
    base_axes = base_snapshot.payload.get("axes")
    expanded_axes = expanded.payload.get("axes")
    base_axes_by_id = (
        {
            axis.get("axis_id"): axis
            for axis in base_axes
            if isinstance(axis, Mapping)
        }
        if isinstance(base_axes, list)
        else {}
    )
    expanded_axes_by_id = (
        {
            axis.get("axis_id"): axis
            for axis in expanded_axes
            if isinstance(axis, Mapping)
        }
        if isinstance(expanded_axes, list)
        else {}
    )
    if (
        not isinstance(base_axes, list)
        or not isinstance(expanded_axes, list)
        or len(base_axes_by_id) != len(base_axes)
        or len(expanded_axes_by_id) != len(expanded_axes)
        or set(expanded_axes_by_id).difference(base_axes_by_id) != {AXIS_ID}
        or any(
            expanded_axes_by_id.get(axis_id) != axis
            for axis_id, axis in base_axes_by_id.items()
        )
        or bridge.payload.get("target_axis_identity")
        not in {
            axis.get("axis_identity")
            for axis in base_axes
            if isinstance(axis, Mapping)
        }
    ):
        raise RuntimeError("historical STU-0106 bridge snapshot is malformed")

    _replay_operation, replay_result = _historical_operation(
        index,
        steps,
        "replay-decision",
        subject="Portfolio:active",
    )
    replay_decision = _historical_portfolio_decision(
        index,
        replay_result.get("decision_id"),
    )
    replay_axis = expanded_axes_by_id[AXIS_ID]
    if (
        replay_decision.payload.get("portfolio_snapshot_id")
        != expanded.record_id
        or replay_decision.payload.get("target_axis_identity")
        != replay_axis.get("axis_identity")
        or replay_decision.payload.get("replay_obligation_ids")
        != [TARGET_OBLIGATION_ID]
    ):
        raise RuntimeError("historical STU-0106 replay Decision is malformed")

    _study_permit_operation, study_permit_result = _historical_operation(
        index,
        steps,
        "study-permit",
        subject=f"Initiative:{INITIATIVE_ID}",
    )
    study_permit = Permit.from_mapping(study_permit_result.get("permit"))
    _study_operation, study_result = _historical_operation(
        index,
        steps,
        "open-study",
        subject=f"Study:{STUDY_ID}",
    )
    study = index.get("study-open", STUDY_ID)
    controlled = _require_historical_chassis_identity(
        None if study is None else study.payload.get("controlled_chassis")
    )
    if (
        study is None
        or study.subject != f"Study:{STUDY_ID}"
        or study.status != "open"
        or study.payload.get("mission_id") != MISSION_ID
        or study.payload.get("portfolio_snapshot_id") != expanded.record_id
        or study.payload.get("portfolio_decision_id") != replay_decision.record_id
        or study.payload.get("portfolio_axis_identity")
        != replay_axis.get("axis_identity")
        or study.payload.get("replay_obligation_ids")
        != [TARGET_OBLIGATION_ID]
        or study.payload.get("prior_global_multiplicity")
        != family.prior_global_exposure_count
        or study_result.get("study_id") != STUDY_ID
        or study_result.get("study_hash") != study.fingerprint
        or study_result.get("controlled_chassis_identity")
        != controlled.get("controlled_chassis_identity")
        or study_permit.kind is not PermitKind.STUDY
        or study_permit.subject.kind is not SubjectKind.INITIATIVE
        or study_permit.subject.subject_id != INITIATIVE_ID
        or study_permit.input_hash != study.fingerprint
        or study_permit.actions != ("open_study",)
    ):
        raise RuntimeError("historical STU-0106 Study authority is malformed")

    _batch_permit_operation, batch_permit_result = _historical_operation(
        index,
        steps,
        "batch-permit",
        subject=f"Study:{STUDY_ID}",
    )
    batch_permit = Permit.from_mapping(batch_permit_result.get("permit"))
    _batch_operation, batch_result = _historical_operation(
        index,
        steps,
        "open-batch",
        subject=f"Batch:{family.batch_id}",
    )
    batch = index.get("batch-open", family.batch_id)
    if (
        batch is None
        or batch.subject != f"Study:{STUDY_ID}"
        or batch.payload.get("spec") != family.batch_spec_payload()
        or batch.fingerprint != family.batch_id.removeprefix("batch:")
        or batch.payload["spec"].get("study_hash") != study.fingerprint
        or batch_result != {"batch_id": family.batch_id}
        or batch_permit.kind is not PermitKind.BATCH
        or batch_permit.subject.kind is not SubjectKind.STUDY
        or batch_permit.subject.subject_id != STUDY_ID
        or batch_permit.input_hash != family.batch_id.removeprefix("batch:")
        or batch_permit.actions != ("open_batch",)
    ):
        raise RuntimeError("historical STU-0106 Batch authority is malformed")

    completions: list[IndexRecord] = []
    negative_memory_ids: dict[int, str | None] = {}
    step_ids = {step.operation_id for step in steps}
    for member in family.members:
        stem = f"member-{member.ordinal:02d}"
        trial_operation, trial_result = _historical_operation(
            index,
            steps,
            stem + "-register-trial",
            subject=f"Executable:{member.executable_id}",
        )
        trial = index.get("trial", member.executable_id)
        expected_replay_ids = (
            [TARGET_OBLIGATION_ID] if member.ordinal == 4 else None
        )
        if (
            trial is None
            or trial.subject != f"Batch:{family.batch_id}"
            or trial.status != "evaluated"
            or trial.payload.get("executable") != member.to_identity_payload()
            or trial.payload.get("study_id") != STUDY_ID
            or trial.payload.get("trial_delta") != 1
            or trial.payload.get("replay_obligation_ids") != expected_replay_ids
            or trial.authority_event_id != trial_operation.authority_event_id
            or trial_result.get("trial_delta") != 1
            or trial_result.get("global_multiplicity")
            != family.prior_global_exposure_count + member.ordinal
        ):
            raise RuntimeError(
                f"historical STU-0106 {stem} trial authority is malformed"
            )

        declaration_operation, declaration_result = _historical_operation(
            index,
            steps,
            stem + "-declare-job",
            subject=f"Executable:{member.executable_id}",
        )
        job_id = declaration_result.get("job_id")
        job_hash = declaration_result.get("job_hash")
        declaration = (
            None if type(job_id) is not str else index.get("job-declared", job_id)
        )
        declaration_spec = (
            None if declaration is None else declaration.payload.get("spec")
        )
        evidence_subject = (
            None
            if not isinstance(declaration_spec, Mapping)
            else declaration_spec.get("evidence_subject")
        )
        if (
            type(job_hash) is not str
            or job_id != "job:" + job_hash
            or declaration is None
            or declaration.subject != f"Job:{job_id}"
            or declaration.status != "declared"
            or declaration.fingerprint != job_hash
            or declaration.authority_event_id
            != declaration_operation.authority_event_id
            or declaration.event_sequence != 1
            or declaration.payload.get("mission_id") != MISSION_ID
            or declaration.payload.get("initiative_id") != INITIATIVE_ID
            or declaration.payload.get("study_id") != STUDY_ID
            or declaration.payload.get("batch_id") != family.batch_id
            or not isinstance(declaration_spec, Mapping)
            or not isinstance(evidence_subject, Mapping)
            or evidence_subject
            != {"kind": "Executable", "id": member.executable_id}
        ):
            raise RuntimeError(
                f"historical STU-0106 {stem} Job declaration is malformed"
            )
        writer._require_job_implementation_evidence(declaration_spec)

        _permit_operation, permit_result = _historical_operation(
            index,
            steps,
            stem + "-job-permit",
            subject=f"Job:{job_id}",
        )
        permit = Permit.from_mapping(permit_result.get("permit"))
        if (
            permit.kind is not PermitKind.JOB
            or permit.subject.kind is not SubjectKind.JOB
            or permit.subject.subject_id != job_id
            or permit.input_hash != job_hash
            or permit.actions != ("start_job",)
        ):
            raise RuntimeError(
                f"historical STU-0106 {stem} Job permit is malformed"
            )

        _start_operation, start_result = _historical_operation(
            index,
            steps,
            stem + "-start-job",
            subject=f"Job:{job_id}",
        )
        execution_payload = start_result.get("execution")
        if not isinstance(execution_payload, Mapping):
            raise RuntimeError(
                f"historical STU-0106 {stem} execution is absent"
            )
        execution = RunningJobExecution.from_mapping(execution_payload)
        start = index.get("job-started", execution.start_record_id)
        if (
            execution.job_id != job_id
            or execution.job_hash != job_hash
            or execution.job_permit_id != permit.permit_id
            or start is None
            or start.subject != f"Job:{job_id}"
            or start.status != "running"
            or start.fingerprint != job_hash
            or start.payload.get("job_permit_id") != permit.permit_id
        ):
            raise RuntimeError(
                f"historical STU-0106 {stem} Job start is malformed"
            )

        completion_operation, completion_result = _historical_operation(
            index,
            steps,
            stem + "-complete-job",
            subject="Job:active",
        )
        completion_id = completion_result.get("completion_record_id")
        completion = (
            None
            if type(completion_id) is not str
            else index.get("job-completed", completion_id)
        )
        scientific = (
            None if completion is None else completion.payload.get("scientific")
        )
        scientific_binding = declaration_spec.get("scientific_binding")
        if (
            completion is None
            or completion.status != "success"
            or completion.subject != f"Job:{job_id}"
            or completion.fingerprint != job_hash
            or completion.authority_event_id
            != completion_operation.authority_event_id
            or completion.event_stream != declaration.event_stream
            or completion.event_sequence != 2
            or completion.payload.get("job_id") != job_id
            or completion.payload.get("start_record_id") != start.record_id
            or completion_result.get("job_id") != job_id
            or completion_result.get("outcome") != "success"
            or not isinstance(scientific, Mapping)
            or not isinstance(scientific_binding, Mapping)
            or scientific.get("executable_id") != member.executable_id
            or scientific.get("candidate_eligible") is not False
            or scientific.get("scientific_eligible") is not True
            or scientific.get("validation_plan_hash")
            != scientific_binding.get("validation_plan_hash")
            or scientific.get("validator_id")
            != scientific_binding.get("validator_id")
        ):
            raise RuntimeError(
                f"historical STU-0106 {stem} Job completion is malformed"
            )
        _require_historical_output_evidence(
            writer,
            completion=completion,
            result=completion_result,
            declaration_spec=declaration_spec,
        )
        completions.append(completion)

        negative_suffix = stem + "-negative-memory"
        negative_memory_id: str | None = None
        if OPERATION_PREFIX + negative_suffix in step_ids:
            _negative_operation, negative_result = _historical_operation(
                index,
                steps,
                negative_suffix,
            )
            value = negative_result.get("negative_memory_id")
            memory = (
                None if type(value) is not str else index.get("negative-memory", value)
            )
            if (
                memory is None
                or memory.payload.get("study_id") != STUDY_ID
                or completion.record_id
                not in memory.payload.get("evidence_references", ())
            ):
                raise RuntimeError(
                    f"historical STU-0106 {stem} negative memory is malformed"
                )
            negative_memory_id = value
        negative_memory_ids[member.ordinal] = negative_memory_id

        judgement_operation, _judgement_result = _historical_operation(
            index,
            steps,
            stem + "-judge-job",
            subject="Job:completed",
        )
        _require_job_judgement_binding(
            index,
            operation=judgement_operation,
            completion=completion,
            expected_disposition=(
                "continue_batch" if member.ordinal < 4 else "stop_batch"
            ),
            expected_negative_memory_id=negative_memory_id,
            label=stem,
        )

    dispose_operation, dispose_result = _historical_operation(
        index,
        steps,
        "dispose-batch",
        subject="Batch:active",
    )
    batch_closes = tuple(
        record
        for record in index.records_by_subject_status(
            f"Batch:{family.batch_id}",
            "completed",
        )
        if record.kind == "batch-close"
        and record.authority_event_id == dispose_operation.authority_event_id
    )
    if (
        dispose_result
        != {"batch_id": family.batch_id, "outcome": "completed"}
        or len(batch_closes) != 1
        or batch_closes[0].payload.get("outcome") != "completed"
    ):
        raise RuntimeError("historical STU-0106 Batch close is malformed")
    batch_close = batch_closes[0]

    close_operation, close_result = _historical_operation(
        index,
        steps,
        "close-study",
        subject="Study:active",
    )
    close_outcome = close_result.get("outcome")
    study_closes = tuple(
        record
        for record in index.records_by_subject_status(
            f"Study:{STUDY_ID}",
            str(close_outcome),
        )
        if record.kind == "study-close"
        and record.authority_event_id == close_operation.authority_event_id
    )
    kpi_id = close_result.get("study_kpi_record_id")
    kpi = None if type(kpi_id) is not str else index.get("study-kpi", kpi_id)
    if (
        close_result.get("study_id") != STUDY_ID
        or len(study_closes) != 1
        or kpi is None
        or kpi.subject != f"Study:{STUDY_ID}"
    ):
        raise RuntimeError("historical STU-0106 Study close is malformed")
    study_close = study_closes[0]

    _diagnose_operation, diagnose_result = _historical_operation(
        index,
        steps,
        "diagnose-study",
        subject=f"Study:{STUDY_ID}",
    )
    diagnosis_id = diagnose_result.get("study_diagnosis_id")
    diagnosis = (
        None
        if type(diagnosis_id) is not str
        else index.get("study-diagnosis", diagnosis_id)
    )
    evidence_basis = None if diagnosis is None else diagnosis.payload.get("evidence_basis")
    basis_pairs = {
        (item.get("kind"), item.get("record_id"))
        for item in evidence_basis
        if isinstance(item, Mapping)
    } if isinstance(evidence_basis, list) else set()
    required_basis = {
        ("batch-open", family.batch_id),
        ("batch-close", batch_close.record_id),
        ("study-close", study_close.record_id),
        *(("job-completed", completion.record_id) for completion in completions),
    }
    if (
        diagnosis is None
        or diagnosis.subject != f"Study:{STUDY_ID}"
        or not required_basis.issubset(basis_pairs)
    ):
        raise RuntimeError("historical STU-0106 diagnosis is malformed")

    resolution_operation, resolution_result = _historical_operation(
        index,
        steps,
        "resolve-replay",
        subject="Mission:active",
    )
    stream = f"historical-replay-obligation:{TARGET_OBLIGATION_ID}"
    historical_resolution = index.event_record(stream, 3)
    resolution_payload = (
        None
        if historical_resolution is None
        else historical_resolution.payload.get("resolution")
    )
    if (
        historical_resolution is None
        or historical_resolution.kind
        != "historical-replay-obligation-resolution"
        or historical_resolution.status != "satisfied"
        or historical_resolution.authority_event_id
        != resolution_operation.authority_event_id
        or historical_resolution.payload.get("obligation_id")
        != TARGET_OBLIGATION_ID
        or not isinstance(resolution_payload, Mapping)
        or historical_resolution.record_id
        != "historical-replay-satisfaction:"
        + canonical_digest(
            domain="historical-replay-satisfaction",
            payload=resolution_payload,
        )
        or resolution_payload.get("replay_study_id") != STUDY_ID
        or resolution_payload.get("replay_executable_id")
        != family.members[-1].executable_id
        or resolution_payload.get("replay_study_close_record_id")
        != study_close.record_id
        or resolution_payload.get("study_diagnosis_id") != diagnosis.record_id
        or resolution_result.get("satisfied_replay_obligation_ids")
        != [TARGET_OBLIGATION_ID]
    ):
        raise RuntimeError(
            "historical STU-0106 satisfaction record is malformed"
        )

    _disposition_operation, disposition_result = _historical_operation(
        index,
        steps,
        "disposition-decision",
        subject="Portfolio:active",
    )
    disposition = _historical_portfolio_decision(
        index,
        disposition_result.get("decision_id"),
    )
    _final_snapshot_operation, final_snapshot_result = _historical_operation(
        index,
        steps,
        "disposition-snapshot",
        subject=f"Mission:{MISSION_ID}",
    )
    final_snapshot = _historical_portfolio_snapshot(
        index,
        final_snapshot_result.get("portfolio_snapshot_id"),
    )
    final_axes = final_snapshot.payload.get("axes")
    if (
        disposition.payload.get("portfolio_snapshot_id") != expanded.record_id
        or disposition.payload.get("study_diagnosis_id") != diagnosis.record_id
        or not isinstance(final_axes, list)
        or len(final_axes) != len(expanded_axes)
        or {
            axis.get("axis_id")
            for axis in final_axes
            if isinstance(axis, Mapping)
        }
        != {
            axis.get("axis_id")
            for axis in expanded_axes
            if isinstance(axis, Mapping)
        }
    ):
        raise RuntimeError(
            "historical STU-0106 disposition authority is malformed"
        )

    _close_initiative_operation, close_initiative_result = _historical_operation(
        index,
        steps,
        "close-initiative",
        subject="Initiative:active",
    )
    if close_initiative_result != {
        "initiative_id": INITIATIVE_ID,
        "outcome": "completed",
    }:
        raise RuntimeError("historical STU-0106 Initiative close is malformed")


def _require_historical_replay_zero_credit(
    index: LocalIndex | LocalIndexView,
) -> None:
    initial = index.get("historical-replay-obligation", TARGET_OBLIGATION_ID)
    obligation_payload = (
        None if initial is None else initial.payload.get("obligation")
    )
    try:
        obligation = historical_replay_obligation_from_identity_payload(
            obligation_payload
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "historical STU-0106 replay obligation is malformed"
        ) from exc
    stream = f"historical-replay-obligation:{TARGET_OBLIGATION_ID}"
    head = index.event_head(stream)
    record = (
        None
        if head is None
        else index.get(head.record_kind, head.record_id)
    )
    if (
        head is None
        or head.sequence < 4
        or record is None
        or record.kind != "historical-replay-satisfaction-invalidation"
        or record.status != "pending"
    ):
        raise RuntimeError(
            "historical STU-0106 audit lacks zero-credit invalidation authority"
        )
    try:
        require_satisfaction_invalidation_record(
            index,
            obligation=obligation,
            record=record,
        )
    except ReplayAuthorityError as exc:
        raise RuntimeError(
            "historical STU-0106 zero-credit invalidation is malformed"
        ) from exc


def validate_historical_replay_prefix_semantics(
    writer: StateWriter,
    *,
    design: P1ReplayDesign,
    prefix: int,
    steps: Sequence[OperationStep],
) -> None:
    """Validate a completed audit-only chain with zero scientific credit."""

    if prefix != len(tuple(steps)):
        raise RuntimeError("historical STU-0106 audit chain is not complete")
    with LocalIndex.open_read_only(writer.index_path) as index:
        _validate_historical_completed_replay_chain(
            writer,
            index,
            design=design,
            steps=steps,
        )
        _require_historical_replay_zero_credit(index)


def validate_replay_prefix_semantics(
    writer: StateWriter,
    *,
    design: P1ReplayDesign,
    prefix: int,
    steps: Sequence[OperationStep],
) -> None:
    """Bind every completed ordinal operation to the rebuilt exact design."""

    completed = {step.operation_id for step in steps[:prefix]}

    def done(suffix: str) -> bool:
        return OPERATION_PREFIX + suffix in completed

    with LocalIndex.open_read_only(writer.index_path) as index:
        if done("open-initiative"):
            initiative = _require_identity_payload(
                index.get("initiative-open", INITIATIVE_ID),
                {"objective": dict(_initiative_objective())},
                label="Initiative",
            )
            if _operation_result(
                writer, OPERATION_PREFIX + "open-initiative"
            ).get("initiative_id") != INITIATIVE_ID:
                raise RuntimeError("completed P1 replay Initiative result drifted")
            if initiative.status != "open":
                raise RuntimeError("completed P1 replay Initiative is not open")
        for suffix, decision in (
            ("bridge-decision", design.bridge_decision),
            ("replay-decision", design.work_decision),
        ):
            if done(suffix):
                record = _require_identity_payload(
                    index.get("portfolio-decision", decision.identity),
                    decision.to_identity_payload(),
                    label=suffix,
                )
                if (
                    record.record_id != decision.identity
                    or _operation_result(writer, OPERATION_PREFIX + suffix).get(
                        "decision_id"
                    )
                    != decision.identity
                ):
                    raise RuntimeError(
                        f"completed P1 replay {suffix} result drifted"
                    )
        if done("expanded-snapshot"):
            snapshot = _require_identity_payload(
                index.get("portfolio-snapshot", design.expanded_snapshot.identity),
                design.expanded_snapshot.to_identity_payload(),
                label="expanded snapshot",
            )
            if (
                snapshot.record_id != design.expanded_snapshot.identity
                or _operation_result(
                    writer, OPERATION_PREFIX + "expanded-snapshot"
                ).get("portfolio_snapshot_id")
                != design.expanded_snapshot.identity
            ):
                raise RuntimeError("completed P1 replay expanded snapshot drifted")
        if done("study-permit"):
            permit = _permit_from_operation(
                writer, OPERATION_PREFIX + "study-permit"
            )
            expected_study_hash = writer.study_input_hash(
                question=design.question,
                material_identity=OBSERVED_MATERIAL_ID,
                semantic_proposal=design.proposal,
                controlled_chassis=design.controlled_chassis,
                portfolio_axis_id=design.replay_axis.axis_id,
                portfolio_axis_identity=design.replay_axis.identity,
                portfolio_decision_id=design.work_decision.identity,
            )
            if (
                permit.kind is not PermitKind.STUDY
                or permit.subject.kind is not SubjectKind.INITIATIVE
                or permit.subject.subject_id != INITIATIVE_ID
                or permit.input_hash != expected_study_hash
                or permit.actions != ("open_study",)
            ):
                raise RuntimeError("completed P1 replay Study permit drifted")
        if done("open-study"):
            study = _require_identity_payload(
                index.get("study-open", STUDY_ID),
                {
                    "controlled_chassis": design.controlled_chassis.to_identity_payload(),
                    "material_identity": OBSERVED_MATERIAL_ID,
                    "mission_id": MISSION_ID,
                    "portfolio_axis_id": design.replay_axis.axis_id,
                    "portfolio_axis_identity": design.replay_axis.identity,
                    "portfolio_decision_id": design.work_decision.identity,
                    "question": dict(design.question),
                    "replay_obligation_ids": [TARGET_OBLIGATION_ID],
                },
                label="Study",
            )
            if (
                study.fingerprint != design.batch_spec.study_hash
                or _operation_result(writer, OPERATION_PREFIX + "open-study").get(
                    "study_hash"
                )
                != design.batch_spec.study_hash
            ):
                raise RuntimeError("completed P1 replay Study hash drifted")
        if done("batch-permit"):
            permit = _permit_from_operation(
                writer, OPERATION_PREFIX + "batch-permit"
            )
            if (
                permit.kind is not PermitKind.BATCH
                or permit.subject.kind is not SubjectKind.STUDY
                or permit.subject.subject_id != STUDY_ID
                or permit.input_hash
                != design.batch_spec.identity.removeprefix("batch:")
                or permit.actions != ("open_batch",)
            ):
                raise RuntimeError("completed P1 replay Batch permit drifted")
        if done("open-batch"):
            batch = _require_identity_payload(
                index.get("batch-open", design.batch_spec.identity),
                {"spec": design.batch_spec.to_identity_payload()},
                label="Batch",
            )
            if (
                batch.record_id != design.batch_spec.identity
                or _operation_result(writer, OPERATION_PREFIX + "open-batch").get(
                    "batch_id"
                )
                != design.batch_spec.identity
            ):
                raise RuntimeError("completed P1 replay Batch result drifted")

        for member in design.members:
            stem = member.label
            operation_stem = OPERATION_PREFIX + stem
            if done(stem + "-register-trial"):
                trial = _require_identity_payload(
                    index.get("trial", member.executable.identity),
                    {
                        "executable": member.executable.to_identity_payload(),
                        "study_id": STUDY_ID,
                        "trial_delta": 1,
                    },
                    label=f"{stem} trial",
                )
                expected_replay_ids = (
                    [TARGET_OBLIGATION_ID]
                    if member is design.target_member
                    else None
                )
                if trial.payload.get("replay_obligation_ids") != expected_replay_ids:
                    raise RuntimeError(f"completed P1 replay {stem} binding drifted")
            if done(stem + "-declare-job"):
                declaration_result = _operation_result(
                    writer, operation_stem + "-declare-job"
                )
                job_id = declaration_result.get("job_id")
                declaration = (
                    None
                    if not isinstance(job_id, str)
                    else index.get("job-declared", job_id)
                )
                expected_spec = StateWriter._normalize_job_spec(
                    build_job_spec(
                        writer,
                        member,
                        materialize_evidence=False,
                    )
                )
                if (
                    declaration is None
                    or declaration.payload.get("study_id") != STUDY_ID
                    or declaration.payload.get("batch_id")
                    != design.batch_spec.identity
                    or declaration.fingerprint != declaration_result.get("job_hash")
                ):
                    raise RuntimeError(
                        f"completed P1 replay {stem} Job declaration drifted"
                    )
                _require_completed_job_spec_compatible(
                    writer,
                    actual=declaration.payload.get("spec"),
                    expected_current=expected_spec,
                )
            if done(stem + "-job-permit"):
                declaration_result = _operation_result(
                    writer, operation_stem + "-declare-job"
                )
                permit = _permit_from_operation(
                    writer, operation_stem + "-job-permit"
                )
                if (
                    permit.kind is not PermitKind.JOB
                    or permit.subject.kind is not SubjectKind.JOB
                    or permit.subject.subject_id != declaration_result.get("job_id")
                    or permit.input_hash != declaration_result.get("job_hash")
                    or permit.actions != ("start_job",)
                ):
                    raise RuntimeError(
                        f"completed P1 replay {stem} Job permit drifted"
                    )
            if done(stem + "-start-job"):
                execution_payload = _operation_result(
                    writer, operation_stem + "-start-job"
                ).get("execution")
                declaration_result = _operation_result(
                    writer, operation_stem + "-declare-job"
                )
                if not isinstance(execution_payload, Mapping):
                    raise RuntimeError(
                        f"completed P1 replay {stem} execution is absent"
                    )
                execution = RunningJobExecution.from_mapping(execution_payload)
                if (
                    execution.job_id != declaration_result.get("job_id")
                    or execution.job_hash != declaration_result.get("job_hash")
                ):
                    raise RuntimeError(
                        f"completed P1 replay {stem} execution drifted"
                    )
            if done(stem + "-complete-job"):
                completion = _member_completion(writer, member)
                scientific = (
                    None if completion is None else completion.payload.get("scientific")
                )
                expected_outputs = set(
                    member.replay_plan.expected_outputs(
                        produce_family_cache=member.ordinal == 1
                    )
                )
                declaration_result = _operation_result(
                    writer, operation_stem + "-declare-job"
                )
                declaration = index.get(
                    "job-declared",
                    str(declaration_result.get("job_id")),
                )
                declared_spec = (
                    None if declaration is None else declaration.payload.get("spec")
                )
                declared_binding = (
                    None
                    if not isinstance(declared_spec, Mapping)
                    else declared_spec.get("scientific_binding")
                )
                historical_validator_id = (
                    None
                    if not isinstance(declared_binding, Mapping)
                    else declared_binding.get("validator_id")
                )
                validation_trace = (
                    None
                    if not isinstance(scientific, Mapping)
                    else scientific.get("validation_trace")
                )
                if (
                    completion is None
                    or completion.status != "success"
                    or completion.payload.get("job_id")
                    != declaration_result.get("job_id")
                    or set(completion.payload.get("outputs", {}))
                    != expected_outputs
                    or not isinstance(scientific, Mapping)
                    or scientific.get("executable_id") != member.executable.identity
                    or scientific.get("validator_id")
                    != historical_validator_id
                    or not isinstance(validation_trace, Mapping)
                    or validation_trace.get("validator_id")
                    != historical_validator_id
                    or scientific.get("validation_plan_hash")
                    != member.replay_plan.plan_hash
                    or scientific.get("scientific_eligible") is not True
                    or scientific.get("candidate_eligible") is not False
                ):
                    raise RuntimeError(
                        f"completed P1 replay {stem} completion drifted"
                    )
            if done(stem + "-negative-memory"):
                expected = _negative_memory(writer, member)
                memory_id = _operation_result(
                    writer, operation_stem + "-negative-memory"
                ).get("negative_memory_id")
                memory = (
                    None
                    if not isinstance(memory_id, str)
                    else index.get("negative-memory", memory_id)
                )
                if memory is None or memory_id != expected.identity:
                    raise RuntimeError(
                        f"completed P1 replay {stem} negative memory drifted"
                    )
            if done(stem + "-judge-job"):
                completion = _member_completion(writer, member)
                expected_disposition = (
                    "continue_batch" if member.ordinal < 4 else "stop_batch"
                )
                operation = index.get(
                    "operation", operation_stem + "-judge-job"
                )
                if completion is None or operation is None:
                    raise RuntimeError(
                        f"completed P1 replay {stem} judgement drifted"
                    )
                negative_memory_id = None
                if done(stem + "-negative-memory"):
                    negative_memory_id = _operation_result(
                        writer, operation_stem + "-negative-memory"
                    ).get("negative_memory_id")
                    if not isinstance(negative_memory_id, str):
                        raise RuntimeError(
                            f"completed P1 replay {stem} judgement drifted"
                        )
                _require_job_judgement_binding(
                    index,
                    operation=operation,
                    completion=completion,
                    expected_disposition=expected_disposition,
                    expected_negative_memory_id=negative_memory_id,
                    label=stem,
                )

        if done("close-study"):
            close_record = _study_close_record(writer)
            target = _member_completion(writer, design.target_member)
            if (
                target is None
                or close_record.status
                != interpret_replay_completion(target).close_outcome
                or close_record.subject != f"Study:{STUDY_ID}"
            ):
                raise RuntimeError("completed P1 replay Study close drifted")
        if done("diagnose-study"):
            diagnosis = _diagnosis_record(writer)
            if diagnosis.record_id != _diagnosis(writer, design).identity:
                raise RuntimeError("completed P1 replay diagnosis drifted")
        if done("resolve-replay"):
            expected_resolution = _replay_resolution(writer, design)
            pair = {
                obligation.identity: head
                for obligation, head in obligation_heads(
                    index, mission_id=MISSION_ID
                )
            }.get(TARGET_OBLIGATION_ID)
            expected_status = (
                "satisfied"
                if isinstance(expected_resolution, ReplaySatisfaction)
                else "deferred"
            )
            if (
                pair is None
                or pair.record_id != expected_resolution.identity
                or pair.status != expected_status
            ):
                raise RuntimeError("completed P1 replay resolution drifted")
        if done("disposition-decision"):
            decision = _disposition_decision(writer, design)
            _require_identity_payload(
                index.get("portfolio-decision", decision.identity),
                decision.to_identity_payload(),
                label="disposition Decision",
            )
        if done("disposition-snapshot"):
            snapshot = _disposition_snapshot(writer, design)
            _require_identity_payload(
                index.get("portfolio-snapshot", snapshot.identity),
                snapshot.to_identity_payload(),
                label="disposition snapshot",
            )
        if done("close-initiative"):
            result = _operation_result(
                writer, OPERATION_PREFIX + "close-initiative"
            )
            if result != {"initiative_id": INITIATIVE_ID, "outcome": "completed"}:
                raise RuntimeError("completed P1 replay Initiative close drifted")


def _verify_no_candidate_or_holdout(writer: StateWriter, design: P1ReplayDesign) -> None:
    control = writer.read_control()
    if (
        control is None
        or control.get("scientific", {}).get("holdout_reveals") != 0
        or control.get("scientific", {}).get("active_holdout_evaluation") is not None
        or control.get("scientific", {}).get("required_future_holdout_id") is not None
    ):
        raise RuntimeError("P1 replay changed or opened holdout authority")
    with LocalIndex.open_read_only(writer.index_path) as index:
        candidates = tuple(
            member.executable.identity
            for member in design.members
            if index.event_head(f"candidate:{member.executable.identity}") is not None
        )
    if candidates:
        raise RuntimeError("P1 replay created candidate authority")


def _verify_durable_family_trace_provenance(
    writer: StateWriter,
    design: P1ReplayDesign,
    *,
    member_completions: Sequence[tuple[ReplayMember, IndexRecord]],
    cache_hash: str,
) -> None:
    if len(member_completions) != 4:
        raise RuntimeError("P1 replay durable family is incomplete")
    first_member, first_completion = member_completions[0]
    first_outputs = first_completion.payload.get("outputs")
    if not isinstance(first_outputs, Mapping):
        raise RuntimeError("P1 replay producer output manifest is absent")
    producer_trace_hash = first_outputs.get(
        first_member.replay_plan.output_names["trace"]
    )
    if not isinstance(producer_trace_hash, str):
        raise RuntimeError("P1 replay producer trace output is absent")
    consumer_inputs = design.members[1].replay_plan.job_input_hashes(
        family_trace_cache_hash=cache_hash,
        family_trace_manifest_hash=producer_trace_hash,
    )
    family_cache, observed_trace_hash, producer_manifest = (
        verify_analog_family_trace_cache_producer(
            writer,
            replay_plan=design.members[1].replay_plan,
            repository_root=writer.root,
            input_hashes=consumer_inputs,
            materialize_missing=False,
        )
    )
    if (
        family_cache.sha256 != cache_hash
        or observed_trace_hash != producer_trace_hash
    ):
        raise RuntimeError("P1 replay durable producer binding drifted")
    for member, completion in member_completions[1:]:
        outputs = completion.payload.get("outputs")
        if not isinstance(outputs, Mapping):
            raise RuntimeError("P1 replay subject output manifest is absent")
        trace_hash = outputs.get(member.replay_plan.output_names["trace"])
        if not isinstance(trace_hash, str):
            raise RuntimeError("P1 replay durable subject trace is absent")
        content = writer.evidence.read_verified(trace_hash)
        try:
            trace = parse_canonical(content)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "P1 replay durable subject trace is not canonical"
            ) from exc
        if not isinstance(trace, dict) or canonical_bytes(trace) != content:
            raise RuntimeError("P1 replay durable subject trace is not canonical")
        try:
            neutral, manifest = (
                trace_module.extract_analog_family_trace_cache_material(
                    trace,
                    require_producer=member.ordinal == 1,
                )
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError("P1 replay durable subject trace is invalid") from exc
        if (
            canonical_bytes(neutral) != family_cache.content
            or manifest != producer_manifest
            or trace.get("mission_id") != MISSION_ID
            or trace.get("subject_executable_id") != member.executable.identity
            or trace.get("job_id") != completion.payload.get("job_id")
            or trace.get("job_hash") != completion.fingerprint
        ):
            raise RuntimeError("P1 replay durable subject provenance drifted")


def verify_study_close_postconditions(
    writer: StateWriter,
    design: P1ReplayDesign,
    *,
    boundary: CorrectionBoundary,
) -> Mapping[str, Any]:
    prefix, steps = inspect_replay_prefix(
        writer,
        design=design,
        boundary=boundary,
    )
    _, study_close_end = stage_bounds(steps, stage="study-close")
    if prefix != study_close_end:
        raise RuntimeError("P1 replay Study-close stage is not exact")
    close_operation = _operation_record(writer, OPERATION_PREFIX + "close-study")
    close_record = _study_close_record(writer)
    control = writer.read_control()
    if (
        control is None
        or close_operation.authority_event_id
        != control.get("heads", {}).get("journal", {}).get("event_id")
        or close_operation.authority_sequence != control.get("revision")
        or control.get("scientific", {}).get("active_initiative") != INITIATIVE_ID
        or any(
            control.get("scientific", {}).get(name) is not None
            for name in (
                "active_batch",
                "active_executable",
                "active_job",
                "active_repair",
                "active_study",
            )
        )
        or control.get("next_action", {}).get("kind") != "diagnose_study"
        or control.get("next_action", {}).get("study_id") != STUDY_ID
        or control.get("next_action", {}).get("study_close_record_id")
        != close_record.record_id
    ):
        raise RuntimeError("P1 replay Study-close control boundary drifted")
    member_completions: list[tuple[ReplayMember, IndexRecord]] = []
    cache_hash: str | None = None
    with LocalIndex.open_read_only(writer.index_path) as index:
        heads = {
            obligation.identity: head
            for obligation, head in obligation_heads(index, mission_id=MISSION_ID)
        }
        target_head = heads.get(TARGET_OBLIGATION_ID)
        for member in design.members:
            trial = index.get("trial", member.executable.identity)
            completion = _member_completion(writer, member)
            output_classes = member.replay_plan.expected_output_classes(
                produce_family_cache=member.ordinal == 1
            )
            outputs = None if completion is None else completion.payload.get("outputs")
            if (
                trial is None
                or trial.payload.get("trial_delta") != 1
                or completion is None
                or not isinstance(outputs, Mapping)
                or set(outputs) != set(output_classes)
            ):
                raise RuntimeError("P1 replay four-member evidence is incomplete")
            for output_name, output_class in output_classes.items():
                output_hash = outputs.get(output_name)
                if not isinstance(output_hash, str):
                    raise RuntimeError("P1 replay output manifest is incomplete")
                if output_class == "durable_evidence":
                    writer.evidence.verify(output_hash)
                    continue
                if (
                    output_class != "reproducible_cache"
                    or output_name != ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME
                    or member.ordinal != 1
                ):
                    raise RuntimeError("P1 replay output storage class drifted")
                cache_hash = output_hash
            member_completions.append((member, completion))
        if target_head is None or target_head.status != "in_progress":
            raise RuntimeError("P1 replay obligation is not exactly in progress")
    if cache_hash is None or len(member_completions) != 4:
        raise RuntimeError("P1 replay first-member cache manifest is absent")
    _verify_durable_family_trace_provenance(
        writer,
        design,
        member_completions=member_completions,
        cache_hash=cache_hash,
    )
    _verify_no_candidate_or_holdout(writer, design)
    return {
        "candidate_created": False,
        "holdout_reveal_delta": 0,
        "study_close_event_id": close_operation.authority_event_id,
        "study_close_record_id": close_record.record_id,
        "study_close_revision": close_operation.authority_sequence,
    }


def run_study_close_stage(
    writer: StateWriter,
    *,
    design: P1ReplayDesign,
    boundary: CorrectionBoundary,
    repository_root: Path,
    explicit_recovery: bool = False,
    job_runner: Callable[..., Any] = execute_analog_replay_job,
) -> dict[str, Any]:
    _require_current_prospective_execution_family(design)
    require_stable_head(writer, explicit_recovery=explicit_recovery)
    prefix, steps = inspect_replay_prefix(
        writer,
        design=design,
        boundary=boundary,
    )
    _, study_close_end = stage_bounds(steps, stage="study-close")
    if prefix > study_close_end:
        raise RuntimeError("P1 replay diagnosis already began; use diagnose stage")
    initial_prefix = prefix
    while True:
        prefix, steps = inspect_replay_prefix(
            writer,
            design=design,
            boundary=boundary,
        )
        _, study_close_end = stage_bounds(steps, stage="study-close")
        if prefix == study_close_end:
            break
        if prefix > study_close_end or steps[prefix].stage != "study-close":
            raise RuntimeError("P1 replay Study-close prefix changed concurrently")
        _apply_study_close_step(
            writer,
            design=design,
            step=steps[prefix],
            repository_root=repository_root,
            job_runner=job_runner,
        )
        advanced, _ = inspect_replay_prefix(
            writer,
            design=design,
            boundary=boundary,
        )
        if advanced != prefix + 1:
            raise RuntimeError("P1 replay Study-close step did not advance exactly once")
    verified = verify_study_close_postconditions(
        writer,
        design,
        boundary=boundary,
    )
    final_prefix, final_steps = inspect_replay_prefix(
        writer,
        design=design,
        boundary=boundary,
    )
    _, final_end = stage_bounds(final_steps, stage="study-close")
    return {
        "applied_step_count": final_prefix - initial_prefix,
        "batch_id": design.batch_spec.identity,
        "candidate_created": False,
        "checkpoint_required": True,
        "durable_output_count": 20,
        "reproducible_cache_output_count": 1,
        "executable_ids": [member.executable.identity for member in design.members],
        "holdout_reveal_delta": 0,
        "initiative_id": INITIATIVE_ID,
        "mode": "study_close_checkpoint",
        "next_stage": "diagnose_after_exact_local_main_checkpoint",
        "operation_count": final_end,
        "replay_obligation_id": TARGET_OBLIGATION_ID,
        "schema": "p1_stu0061_replay_study_close.v1",
        "study_id": STUDY_ID,
        "trial_delta": 4,
        **dict(verified),
    }


def verify_diagnose_postconditions(
    writer: StateWriter,
    design: P1ReplayDesign,
    *,
    boundary: CorrectionBoundary,
) -> Mapping[str, Any]:
    prefix, steps = inspect_replay_prefix(
        writer,
        design=design,
        boundary=boundary,
    )
    if prefix != len(steps):
        raise RuntimeError("P1 replay diagnosis chain is incomplete")
    control = writer.read_control()
    if (
        control is None
        or control.get("scientific", {}).get("active_initiative") is not None
        or any(
            control.get("scientific", {}).get(name) is not None
            for name in (
                "active_batch",
                "active_executable",
                "active_job",
                "active_repair",
                "active_study",
            )
        )
    ):
        raise RuntimeError("P1 replay Initiative did not close at a stable boundary")
    expected_snapshot = _disposition_snapshot(writer, design)
    diagnosis = _diagnosis_record(writer)
    completion_ids = {
        completion.record_id
        for member in design.members
        if (completion := _member_completion(writer, member)) is not None
    }
    basis_completion_ids = {
        item.get("record_id")
        for item in diagnosis.payload.get("evidence_basis", [])
        if isinstance(item, Mapping) and item.get("kind") == "job-completed"
    }
    with LocalIndex.open_read_only(writer.index_path) as index:
        p1 = {
            obligation.identity: head
            for obligation, head in obligation_heads(index, mission_id=MISSION_ID)
            if obligation.replay_priority.value == "p1"
        }
        target = p1.get(TARGET_OBLIGATION_ID)
        pending = sorted(
            obligation_id
            for obligation_id, head in p1.items()
            if obligation_id != TARGET_OBLIGATION_ID and head.status == "pending"
        )
        portfolio_head = index.event_head(f"portfolio:{MISSION_ID}")
    if (
        len(p1) != 7
        or target is None
        or target.status not in {"satisfied", "deferred"}
        or len(pending) != 6
        or any(
            head.status != "pending"
            for obligation_id, head in p1.items()
            if obligation_id != TARGET_OBLIGATION_ID
        )
        or control.get("next_action")
        != {
            "kind": "choose_next_initiative_or_terminal",
            "mission_id": MISSION_ID,
            "pending_replay_obligation_ids": pending,
            "required_replay_priority": "p1",
        }
        or portfolio_head is None
        or portfolio_head.record_id != expected_snapshot.identity
        or completion_ids != basis_completion_ids
    ):
        raise RuntimeError("P1 replay final scientific or scheduler state drifted")
    _verify_no_candidate_or_holdout(writer, design)
    return {
        "axis_status": (
            "preserved"
            if _disposition_decision(writer, design).chosen.action
            is PortfolioAction.PRESERVE
            else "pruned"
        ),
        "pending_p1_obligation_ids": pending,
        "replay_obligation_status": target.status,
    }


def run_diagnose_stage(
    writer: StateWriter,
    *,
    design: P1ReplayDesign,
    boundary: CorrectionBoundary,
    study_close_event_id: str,
    study_close_revision: int,
    explicit_recovery: bool = False,
) -> dict[str, Any]:
    _require_current_prospective_execution_family(design)
    require_stable_head(writer, explicit_recovery=explicit_recovery)
    prefix, steps = inspect_replay_prefix(
        writer,
        design=design,
        boundary=boundary,
    )
    diagnose_start, diagnose_end = stage_bounds(steps, stage="diagnose")
    close = _operation_record(writer, OPERATION_PREFIX + "close-study")
    if (
        prefix < diagnose_start
        or close.authority_event_id != study_close_event_id
        or close.authority_sequence != study_close_revision
    ):
        raise RuntimeError("diagnosis arguments do not bind exact Study-close authority")
    if prefix == diagnose_start:
        control = writer.read_control()
        if (
            control is None
            or control.get("revision") != study_close_revision
            or control.get("heads", {}).get("journal", {}).get("event_id")
            != study_close_event_id
            or control.get("next_action", {}).get("study_close_record_id")
            != _study_close_record(writer).record_id
        ):
            raise RuntimeError("Study-close checkpoint control head is not exact")
    writer._require_study_close_delivery_guard()
    initial_prefix = prefix
    while True:
        prefix, steps = inspect_replay_prefix(
            writer,
            design=design,
            boundary=boundary,
        )
        _, diagnose_end = stage_bounds(steps, stage="diagnose")
        if prefix == diagnose_end:
            break
        if prefix < diagnose_start or steps[prefix].stage != "diagnose":
            raise RuntimeError("P1 replay diagnosis prefix changed concurrently")
        _apply_diagnose_step(
            writer,
            design=design,
            step=steps[prefix],
        )
        advanced, _ = inspect_replay_prefix(
            writer,
            design=design,
            boundary=boundary,
        )
        if advanced != prefix + 1:
            raise RuntimeError("P1 replay diagnosis step did not advance exactly once")
    verified = verify_diagnose_postconditions(
        writer,
        design,
        boundary=boundary,
    )
    return {
        "applied_step_count": diagnose_end - initial_prefix,
        "candidate_created": False,
        "holdout_reveal_delta": 0,
        "initiative_id": INITIATIVE_ID,
        "mode": "diagnosed_replay_and_initiative_closed",
        "next_action": writer.read_control()["next_action"],
        "replay_obligation_id": TARGET_OBLIGATION_ID,
        "schema": "p1_stu0061_replay_diagnosis.v1",
        "study_close_event_id": study_close_event_id,
        "study_close_revision": study_close_revision,
        "study_id": STUDY_ID,
        "trial_delta": 4,
        **dict(verified),
    }


def _read_only_summary(
    writer: StateWriter,
    design: P1ReplayDesign,
    *,
    boundary: CorrectionBoundary,
) -> dict[str, Any]:
    prefix, steps = inspect_replay_prefix(
        writer,
        design=design,
        boundary=boundary,
    )
    study_close_start, study_close_end = stage_bounds(steps, stage="study-close")
    diagnose_start, diagnose_end = stage_bounds(steps, stage="diagnose")
    output_classes = tuple(
        output_class
        for member in design.members
        for output_class in member.replay_plan.expected_output_classes(
            produce_family_cache=member.ordinal == 1
        ).values()
    )
    return {
        "audit_only": True,
        "axis_count_after": len(design.expanded_snapshot.axes),
        "axis_count_before": len(design.prior_axes),
        "base_snapshot_id": design.base_snapshot_id,
        "candidate_eligible": False,
        "current_prefix": prefix,
        "diagnose_operation_count": diagnose_end - diagnose_start,
        "durable_output_count": output_classes.count("durable_evidence"),
        "executable_ids": list(design.historical_family.family_executable_ids),
        "historical_batch_id": design.historical_family.batch_id,
        "historical_reference_executable_ids": [
            member.configuration.historical_reference_executable_id
            for member in design.members
        ],
        "historical_registered_executable_ids": list(
            design.historical_family.family_executable_ids
        ),
        "initiative_id": INITIATIVE_ID,
        "historical_non_p1_exposure_count": (
            design.historical_family.prior_global_exposure_count
        ),
        "mode": "read_only_plan",
        "new_axis_id": design.replay_axis.axis_id,
        "prospective_current_executable_ids": [
            member.executable.identity for member in design.members
        ],
        "replay_obligation_ids": list(design.work_decision.replay_obligation_ids),
        "reproducible_cache_output_count": output_classes.count(
            "reproducible_cache"
        ),
        "schema": "p1_stu0061_replay_plan.v1",
        "scientific_credit": 0,
        "study_close_operation_count": study_close_end - study_close_start,
        "study_id": STUDY_ID,
        "target_member_ordinal": design.target_member.ordinal,
        "terminal_credit": 0,
        "trial_delta": 4,
    }


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or crash-resumably execute the exact STU-0061 P1 replay "
            "and its post-checkpoint diagnosis."
        )
    )
    parser.add_argument(
        "--stage",
        choices=("study-close", "diagnose"),
        help="omit for a read-only plan",
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        help="explicitly recover a mutating stage before resuming it",
    )
    parser.add_argument("--study-close-event-id")
    parser.add_argument("--study-close-revision", type=int)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    arguments = parse_arguments(argv)
    if arguments.stage is None and arguments.recover:
        raise RuntimeError("read-only plan does not perform recovery")
    registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
    writer = StateWriter(ROOT, validation_registry=registry)
    require_stable_head(
        writer,
        explicit_recovery=bool(arguments.stage and arguments.recover),
    )
    boundary = validate_correction_predecessor(writer)
    design = build_p1_replay_design(writer)
    if arguments.stage is None:
        if (
            arguments.study_close_event_id is not None
            or arguments.study_close_revision is not None
        ):
            raise RuntimeError("Study-close authority arguments require diagnose stage")
        print(
            json.dumps(
                _read_only_summary(writer, design, boundary=boundary),
                sort_keys=True,
            )
        )
        return
    writer.permit_authority = PermitAuthority(
        PermitKeyStore(ROOT / "local" / "permit.key").load_or_create()
    )
    if arguments.stage == "study-close":
        if (
            arguments.study_close_event_id is not None
            or arguments.study_close_revision is not None
        ):
            raise RuntimeError("Study-close stage rejects checkpoint arguments")
        summary = run_study_close_stage(
            writer,
            design=design,
            boundary=boundary,
            repository_root=ROOT,
            explicit_recovery=arguments.recover,
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
        boundary=boundary,
        study_close_event_id=arguments.study_close_event_id,
        study_close_revision=arguments.study_close_revision,
        explicit_recovery=arguments.recover,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
