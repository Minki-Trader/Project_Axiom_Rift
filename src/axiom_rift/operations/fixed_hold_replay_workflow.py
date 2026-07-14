"""Crash-resumable Mission workflow for exact fixed-hold replay families.

The workflow owns operational ceremony once.  A protocol adapter supplies the
exact family Executables, scientific plans, controlled chassis, and Job
runner.  Durable operations contain no callback or import-path authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ExecutableSpec
from axiom_rift.operations.effective_axis_projection import (
    effective_axis_resolution,
)
from axiom_rift.operations.replay_projection import (
    obligation_heads,
    replay_evidence_record_ids,
)
from axiom_rift.operations.strict_operation_chain import (
    OperationStep,
    inspect_operation_prefix,
    stage_bounds,
)
from axiom_rift.operations.writer import (
    RecoveryRequired,
    RunningJobExecution,
    StateWriter,
)
from axiom_rift.research.chassis import ControlledStudyChassis
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID
from axiom_rift.research.effective_axis import EffectiveAxisStatus
from axiom_rift.research.fixed_hold_family_job import (
    FixedHoldFamilyJobPacket,
    FixedHoldFamilyJobPlan,
    validated_fixed_hold_recomputed_criterion_ids,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_REPLAY_EVIDENCE_MODES,
)
from axiom_rift.research.governance import (
    DiagnosisConfidence,
    EvidenceState,
    ResearchLayer,
    StudyDiagnosis,
)
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
from axiom_rift.research.portfolio_projection import (
    component_surface_registry,
    portfolio_axes_from_projection,
)
from axiom_rift.research.protocol import (
    ResearchProtocol,
    ResearchProtocolActivation,
)
from axiom_rift.research.replay_obligation import (
    ReplayDeferral,
    ReplayDeferralBasis,
    ReplayDeferralBasisKind,
    ReplayDeferralExecutionBinding,
    ReplayResolutionScope,
    ReplayResumeCondition,
    ReplayResumeConditionKind,
    ReplaySatisfaction,
)
from axiom_rift.research.trials import NegativeMemory
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
)
from axiom_rift.operations.permits import Permit, PermitKind, SubjectKind
from axiom_rift.storage.index import IndexRecord, LocalIndex


STUDY_CLOSE_STAGE = "study-close"
DIAGNOSE_STAGE = "diagnose"


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


@dataclass(frozen=True, slots=True)
class ReplayAuthorityBoundary:
    sequence: int
    event_id: str

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("replay predecessor sequence is invalid")
        _digest("replay predecessor event", self.event_id)


@dataclass(frozen=True, slots=True)
class FixedHoldReplayMissionSpec:
    mission_id: str
    initiative_id: str
    study_id: str
    batch_display_id: str
    axis_id: str
    operation_prefix: str
    decision_prefix: str
    target_obligation_id: str
    original_study_id: str
    job_protocol: str
    callable_identity: str
    job_implementation_identity: str
    permit_expiry_utc: str
    boundary: ReplayAuthorityBoundary
    display_name: str

    def __post_init__(self) -> None:
        for name in (
            "mission_id",
            "initiative_id",
            "study_id",
            "batch_display_id",
            "axis_id",
            "operation_prefix",
            "decision_prefix",
            "target_obligation_id",
            "original_study_id",
            "job_protocol",
            "callable_identity",
            "permit_expiry_utc",
            "display_name",
        ):
            _ascii(name, getattr(self, name))
        _digest("Job implementation identity", self.job_implementation_identity)
        if not self.target_obligation_id.startswith(
            "historical-replay-obligation:"
        ):
            raise ValueError("replay target obligation namespace is invalid")


@dataclass(frozen=True, slots=True)
class FixedHoldReplayMember:
    ordinal: int
    configuration_id: str
    historical_reference_executable_id: str
    executable: ExecutableSpec
    job_plan: FixedHoldFamilyJobPlan

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise ValueError("replay member ordinal is invalid")
        _ascii("replay configuration", self.configuration_id)
        _ascii(
            "historical replay executable",
            self.historical_reference_executable_id,
        )
        if (
            not isinstance(self.executable, ExecutableSpec)
            or not isinstance(self.job_plan, FixedHoldFamilyJobPlan)
            or self.job_plan.executable_id != self.executable.identity
        ):
            raise ValueError("replay member Executable and Job plan differ")

    @property
    def label(self) -> str:
        return f"member-{self.ordinal:02d}"


@dataclass(frozen=True, slots=True)
class ReplayInterpretation:
    all_criteria_recomputed: bool
    close_outcome: str
    diagnosis_state: EvidenceState
    disposition: PortfolioAction
    reason_code: str


@dataclass(frozen=True, slots=True)
class FixedHoldReplayDesign:
    spec: FixedHoldReplayMissionSpec
    base_snapshot_id: str
    prior_axes: tuple[PortfolioAxis, ...]
    replay_axis: PortfolioAxis
    bridge_decision: PortfolioDecision
    expanded_snapshot: PortfolioSnapshot
    work_decision: PortfolioDecision
    members: tuple[FixedHoldReplayMember, ...]
    target_executable_id: str
    question: Mapping[str, Any]
    proposal: Mapping[str, Any]
    batch_spec: BatchSpec
    controlled_chassis: ControlledStudyChassis
    criterion_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.members or tuple(
            member.ordinal for member in self.members
        ) != tuple(range(1, len(self.members) + 1)):
            raise ValueError("replay members are not exactly ordered")
        executable_ids = tuple(
            member.executable.identity for member in self.members
        )
        definition_ids = self.members[0].job_plan.definition.prospective_executable_ids
        if (
            len(set(executable_ids)) != len(executable_ids)
            or executable_ids != definition_ids
            or self.target_executable_id not in executable_ids
            or any(
                member.job_plan.definition.identity
                != self.members[0].job_plan.definition.identity
                for member in self.members
            )
        ):
            raise ValueError("replay family identity or target drifted")

    @property
    def target_member(self) -> FixedHoldReplayMember:
        matches = tuple(
            member
            for member in self.members
            if member.executable.identity == self.target_executable_id
        )
        if len(matches) != 1:
            raise RuntimeError("replay target member is ambiguous")
        return matches[0]

    @property
    def producer_member(self) -> FixedHoldReplayMember:
        matches = tuple(
            member for member in self.members if member.job_plan.produces_family_cache
        )
        if len(matches) != 1:
            raise RuntimeError("replay cache producer is ambiguous")
        return matches[0]


def _operation_record(
    writer: StateWriter,
    operation_id: str,
) -> IndexRecord:
    with LocalIndex(writer.index_path) as index:
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


def _permit_from_operation(
    writer: StateWriter,
    operation_id: str,
) -> Permit:
    raw = _operation_result(writer, operation_id).get("permit")
    if not isinstance(raw, Mapping):
        raise RuntimeError(f"permit operation result is malformed: {operation_id}")
    return Permit.from_mapping(raw)


def _base_snapshot_id(
    writer: StateWriter,
    spec: FixedHoldReplayMissionSpec,
) -> str:
    with LocalIndex(writer.index_path) as index:
        bridge = index.get(
            "operation",
            spec.operation_prefix + "bridge-decision",
        )
        if bridge is None:
            head = index.event_head(f"portfolio:{spec.mission_id}")
            snapshot_id = None if head is None else head.record_id
        else:
            result = bridge.payload.get("result")
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
        raise RuntimeError("replay base Portfolio snapshot is unavailable")
    return snapshot_id


def _projection_payloads(
    index: LocalIndex,
    members: Sequence[FixedHoldReplayMember],
) -> tuple[Mapping[str, Any], ...]:
    values: list[Mapping[str, Any]] = [
        member.executable.to_identity_payload() for member in members
    ]
    for kind in (
        "trial",
        "portfolio-decision",
        "study-open",
        "portfolio-snapshot",
    ):
        values.extend(record.payload for record in index.records_by_kind(kind))
    return tuple(values)


def build_fixed_hold_replay_design(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    members: tuple[FixedHoldReplayMember, ...],
    target_executable_id: str,
    controlled_chassis: ControlledStudyChassis,
    historical_family_manifest: Mapping[str, Any],
    criterion_ids: tuple[str, ...],
    causal_question: str,
    mechanism_family: str,
    why_now: str,
    stop_or_reopen_condition: str,
) -> FixedHoldReplayDesign:
    """Build one exact forest-preserving replay design from durable state."""

    base_snapshot_id = _base_snapshot_id(writer, spec)
    with LocalIndex(writer.index_path) as index:
        snapshot_record = index.get("portfolio-snapshot", base_snapshot_id)
        if snapshot_record is None:
            raise RuntimeError("replay base Portfolio snapshot is absent")
        components = component_surface_registry(
            _projection_payloads(index, members)
        )
        prior_axes = portfolio_axes_from_projection(
            snapshot_record.payload["axes"],
            components,
        )
        projected_axes = {
            item["axis_id"]: item for item in snapshot_record.payload["axes"]
        }
        selectable = tuple(
            axis
            for axis in prior_axes
            if effective_axis_resolution(
                index,
                projected_axes[axis.axis_id],
            ).status
            is EffectiveAxisStatus.SELECTABLE
        )
        obligations = {
            obligation.identity: head
            for obligation, head in obligation_heads(
                index,
                mission_id=spec.mission_id,
            )
        }
    target_head = obligations.get(spec.target_obligation_id)
    if (
        any(axis.axis_id == spec.axis_id for axis in prior_axes)
        or not selectable
        or target_head is None
        or target_head.status not in {"pending", "in_progress"}
    ):
        raise RuntimeError("replay axis, bridge, or obligation boundary is invalid")
    source_axis = selectable[0]
    replay_axis = PortfolioAxis(
        axis_id=spec.axis_id,
        causal_question=_ascii("replay causal question", causal_question),
        mechanism_family=_ascii("replay mechanism", mechanism_family),
        primary_research_layer=ResearchLayer.SYNTHESIS,
        system_architecture_family=controlled_chassis.architecture.identity,
        changed_domains=tuple(controlled_chassis.changed_domains),
        controlled_domains=tuple(controlled_chassis.controlled_domains),
        why_now=_ascii("replay why now", why_now),
        stop_or_reopen_condition=_ascii(
            "replay stop or reopen condition",
            stop_or_reopen_condition,
        ),
        architecture_chassis=controlled_chassis.architecture,
    )
    bridge_decision = PortfolioDecision(
        decision_id=spec.decision_prefix + "-BRIDGE",
        chosen_option_id="add-bounded-replay-bridge",
        options=(
            DecisionOption(
                option_id="add-bounded-replay-bridge",
                action=PortfolioAction.NEW_MECHANISM,
                target_id=source_axis.axis_id,
                expected_information_value=(
                    "high because one exact family resolves a bounded P1 duty"
                ),
                opportunity_cost=(
                    f"one bounded {len(members)}-Job concurrent family"
                ),
            ),
            DecisionOption(
                option_id="continue-unrelated-forest",
                action=PortfolioAction.PRESERVE,
                target_id=source_axis.axis_id,
                expected_information_value=(
                    "valid unrelated forest work remains available"
                ),
                opportunity_cost="leave the selected P1 obligation pending",
                omission_reason=(
                    "the typed P1 queue grants this replay its current opportunity"
                ),
            ),
        ),
        rationale=(
            "add one replay bridge without mutating or reinterpreting prior axes"
        ),
        commitment_batches=1,
    )
    expanded_snapshot = PortfolioSnapshot(
        mission_id=spec.mission_id,
        axes=(*prior_axes, replay_axis),
        opportunity_cost_basis=(
            "retain the complete forest and spend one Batch on exact replay"
        ),
        research_intake_id=snapshot_record.payload.get("research_intake_id"),
        exhaustion_standard=snapshot_record.payload.get("exhaustion_standard"),
    )
    work_decision = PortfolioDecision(
        decision_id=spec.decision_prefix + "-REPLAY",
        chosen_option_id="run-exact-concurrent-family",
        options=(
            DecisionOption(
                option_id="run-exact-concurrent-family",
                action=PortfolioAction.SYNTHESIZE,
                target_id=replay_axis.axis_id,
                expected_information_value=(
                    "highest bounded value from exact criterion recomputation"
                ),
                opportunity_cost=(
                    f"{len(members)} sequential Jobs under one concurrent family"
                ),
            ),
            DecisionOption(
                option_id="defer-exact-concurrent-family",
                action=PortfolioAction.NEW_MECHANISM,
                target_id=replay_axis.axis_id,
                expected_information_value="no immediate replay resolution",
                opportunity_cost="retain unresolved historical uncertainty",
                omission_reason="the required family is locally executable now",
            ),
        ),
        rationale=(
            "select only the exact typed P1 obligation while peers remain schedulable"
        ),
        commitment_batches=1,
        baseline_executable=controlled_chassis.baseline_executable,
        replay_obligation_ids=(spec.target_obligation_id,),
    )
    question = {
        "causal_question": causal_question,
        "changed_variables": [
            value.value for value in controlled_chassis.changed_domains
        ],
        "controlled_variables": [
            value.value for value in controlled_chassis.controlled_domains
        ],
        "done_conditions": [
            "all preregistered family members are evaluated",
            "the exact historical criteria are recomputed",
            "no candidate or holdout authority is created",
        ],
        "evidence_modes": list(FIXED_HOLD_REPLAY_EVIDENCE_MODES),
    }
    proposal = {
        "candidate_eligible": False,
        "concurrent_family": dict(historical_family_manifest),
        "historical_obligation_id": spec.target_obligation_id,
        "mechanism": mechanism_family,
        "original_study_id": spec.original_study_id,
    }
    study_hash = writer.study_input_hash(
        question=question,
        material_identity=OBSERVED_MATERIAL_ID,
        semantic_proposal=proposal,
        controlled_chassis=controlled_chassis,
        portfolio_axis_id=replay_axis.axis_id,
        portfolio_axis_identity=replay_axis.identity,
        portfolio_decision_id=work_decision.identity,
    )
    batch_spec = BatchSpec(
        batch_id=spec.batch_display_id,
        study_id=spec.study_id,
        study_hash=study_hash,
        display_name=spec.display_name,
        max_trials=len(members),
        max_compute_seconds=14_400,
        max_wall_seconds=21_600,
        stop_rule="stop only after the exact registered family",
        source_contract_ids=(),
        concurrent_family=ConcurrentFamilyManifest(
            evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
            executable_ids=tuple(
                member.executable.identity for member in members
            ),
        ),
        acceptance_profile={
            "candidate_authority": "none",
            "exact_original_criteria": list(criterion_ids),
            "replay_obligation_id": spec.target_obligation_id,
        },
        adaptive_basis={
            "uncertainty": "one historical P1 criterion family is unresolved",
            "causal_complexity": (
                f"one exact registered family with {len(members)} members"
            ),
            "surface_curvature": "fixed family; no adaptive additions",
            "compute_cost": f"{len(members)} bounded sequential Jobs",
            "expected_information_value": (
                f"resolve or exactly defer {spec.original_study_id}"
            ),
            "portfolio_opportunity_cost": (
                "other P1 duties and open forest axes remain schedulable"
            ),
        },
    )
    return FixedHoldReplayDesign(
        spec=spec,
        base_snapshot_id=base_snapshot_id,
        prior_axes=prior_axes,
        replay_axis=replay_axis,
        bridge_decision=bridge_decision,
        expanded_snapshot=expanded_snapshot,
        work_decision=work_decision,
        members=members,
        target_executable_id=target_executable_id,
        question=question,
        proposal=proposal,
        batch_spec=batch_spec,
        controlled_chassis=controlled_chassis,
        criterion_ids=criterion_ids,
    )


def _member_completion(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
    member: FixedHoldReplayMember,
) -> IndexRecord | None:
    operation_id = (
        design.spec.operation_prefix + member.label + "-complete-job"
    )
    with LocalIndex(writer.index_path) as index:
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


def _scientific_facts(
    completion: IndexRecord,
) -> Mapping[str, object] | None:
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


def interpret_fixed_hold_completion(
    completion: IndexRecord,
    *,
    criterion_ids: tuple[str, ...],
) -> ReplayInterpretation:
    facts = _scientific_facts(completion)
    recomputed = False
    if facts is not None:
        try:
            recomputed = (
                validated_fixed_hold_recomputed_criterion_ids(facts)
                == criterion_ids
            )
        except ValueError:
            recomputed = False
    adjudication = None if facts is None else facts.get("scientific_adjudication")
    state = (
        None
        if not isinstance(adjudication, Mapping)
        else adjudication.get("state")
    )
    if recomputed and state in {"confirmed", "frontier", "partial_positive"}:
        return ReplayInterpretation(
            all_criteria_recomputed=True,
            close_outcome="preserved",
            diagnosis_state=EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION,
            disposition=PortfolioAction.PRESERVE,
            reason_code="exact_original_criteria_recomputed",
        )
    if recomputed and state == "contradicted":
        return ReplayInterpretation(
            all_criteria_recomputed=True,
            close_outcome="pruned",
            diagnosis_state=EvidenceState.STABILITY_CONCENTRATION,
            disposition=PortfolioAction.PRUNE,
            reason_code="exact_original_criteria_recomputed_negative",
        )
    return ReplayInterpretation(
        all_criteria_recomputed=False,
        close_outcome="not_evaluable",
        diagnosis_state=EvidenceState.NOT_IDENTIFIABLE,
        disposition=PortfolioAction.PRESERVE,
        reason_code=(
            "original_criterion_recomputation_incomplete"
            if facts is not None
            else "original_criterion_recomputation_unavailable"
        ),
    )


def _protocol_activation_operation_id(
    design: FixedHoldReplayDesign,
) -> str:
    return design.spec.operation_prefix + "activate-current-v2-protocol"


def _protocol_activation_step_needed(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> bool:
    """Keep a required activation in the strict chain after it is recorded."""

    index_path = getattr(writer, "index_path", None)
    if index_path is None:
        return False
    control = writer.read_control()
    if not isinstance(control, Mapping):
        raise RuntimeError("replay protocol preflight lacks control")
    operation_id = _protocol_activation_operation_id(design)
    authority_digest = control.get("authority", {}).get("manifest_digest")
    with LocalIndex(index_path) as index:
        if index.get("operation", operation_id) is not None:
            return True
        head = index.event_head("research-protocol:scientific")
        record = (
            None
            if head is None
            else index.get(head.record_kind, head.record_id)
        )
    return not (
        record is not None
        and record.kind == "research-protocol-activation"
        and record.status == "active"
        and record.payload.get("protocol") == "scientific_adjudication_v2"
        and record.payload.get("validator_id")
        == SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
        and record.payload.get("authority_manifest_digest")
        == authority_digest
    )


def _member_repair_chain_started(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
    member: FixedHoldReplayMember,
) -> bool:
    """Preserve a typed in-flight Repair inside the strict replay chain."""

    index_path = getattr(writer, "index_path", None)
    if index_path is None:
        return False
    stem = design.spec.operation_prefix + member.label
    with LocalIndex(index_path) as index:
        return any(
            index.get("operation", stem + suffix) is not None
            for suffix in (
                "-repair-permit",
                "-open-repair",
                "-close-repair",
            )
        )


def activate_current_scientific_protocol(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> Any:
    """Audit and bind the current validator before this Study's first Job."""

    control = writer.read_control()
    if not isinstance(control, Mapping):
        raise RuntimeError("replay protocol activation lacks control")
    authority_digest = control.get("authority", {}).get("manifest_digest")
    if type(authority_digest) is not str:
        raise RuntimeError("replay protocol activation lacks authority")
    science = control.get("scientific", {})
    study_id = science.get("active_study") if isinstance(science, Mapping) else None
    batch = science.get("active_batch") if isinstance(science, Mapping) else None
    with LocalIndex(writer.index_path) as index:
        head = index.event_head("research-protocol:scientific")
        prior = (
            None
            if head is None
            else index.get(head.record_kind, head.record_id)
        )
        current_study_job_count = sum(
            record.payload.get("study_id") == study_id
            for record in index.records_by_kind("job-declared")
        ) if isinstance(study_id, str) else 0
    audit = writer.evidence.finalize(
        canonical_bytes(
            {
                "authority_manifest_digest": authority_digest,
                "batch_id": (
                    batch.get("id") if isinstance(batch, Mapping) else None
                ),
                "candidate_delta": 0,
                "holdout_reveal_delta": 0,
                "mission_id": (
                    science.get("active_mission")
                    if isinstance(science, Mapping)
                    else None
                ),
                "prior_activation_record_id": (
                    None if prior is None else prior.record_id
                ),
                "prior_validator_id": (
                    None if prior is None else prior.payload.get("validator_id")
                ),
                "prospective_job_declaration_count": current_study_job_count,
                "prospective_job_implementation_identity": (
                    design.spec.job_implementation_identity
                ),
                "reason": (
                    "bind the current validated implementation before the first "
                    "prospective scientific Job"
                ),
                "replacement_validator_id": (
                    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
                ),
                "schema": "scientific_protocol_reactivation_audit.v1",
                "study_id": study_id,
                "trial_delta": 0,
            }
        )
    )
    activation = ResearchProtocolActivation(
        protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
        validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        authority_manifest_digest=authority_digest,
        audit_artifact_hash=audit.sha256,
    )
    return writer.activate_research_protocol(
        activation=activation,
        operation_id=_protocol_activation_operation_id(design),
        allow_active_stable_boundary=True,
        allow_active_unexecuted_study_boundary=True,
    )


def operation_steps(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> tuple[OperationStep, ...]:
    prefix = design.spec.operation_prefix
    failed = {
        member.ordinal
        for member in design.members
        if (
            (completion := _member_completion(writer, design, member))
            is not None
            and isinstance(completion.payload.get("scientific"), Mapping)
            and completion.payload["scientific"].get("verdict") == "failed"
        )
    }
    target = _member_completion(writer, design, design.target_member)
    recomputed = (
        target is not None
        and interpret_fixed_hold_completion(
            target,
            criterion_ids=design.criterion_ids,
        ).all_criteria_recomputed
    )
    steps: list[OperationStep] = [
        OperationStep(prefix + "open-initiative", "initiative_opened", STUDY_CLOSE_STAGE),
        OperationStep(prefix + "bridge-decision", "portfolio_decision_recorded", STUDY_CLOSE_STAGE),
        OperationStep(prefix + "expanded-snapshot", "portfolio_snapshot_recorded", STUDY_CLOSE_STAGE),
        OperationStep(prefix + "replay-decision", "portfolio_decision_recorded", STUDY_CLOSE_STAGE),
        OperationStep(prefix + "study-permit", "permit_issued", STUDY_CLOSE_STAGE),
        OperationStep(prefix + "open-study", "study_opened", STUDY_CLOSE_STAGE),
        OperationStep(prefix + "batch-permit", "permit_issued", STUDY_CLOSE_STAGE),
        OperationStep(prefix + "open-batch", "batch_opened", STUDY_CLOSE_STAGE),
    ]
    steps.extend(
        OperationStep(
            prefix + member.label + "-register-trial",
            "trial_registered",
            STUDY_CLOSE_STAGE,
        )
        for member in design.members
    )
    if _protocol_activation_step_needed(writer, design):
        steps.append(
            OperationStep(
                _protocol_activation_operation_id(design),
                "research_protocol_activated",
                STUDY_CLOSE_STAGE,
            )
        )
    for member in design.members:
        stem = prefix + member.label
        steps.extend(
            (
                OperationStep(stem + "-declare-job", "job_declared", STUDY_CLOSE_STAGE),
                OperationStep(stem + "-job-permit", "permit_issued", STUDY_CLOSE_STAGE),
                OperationStep(stem + "-start-job", "job_started", STUDY_CLOSE_STAGE),
            )
        )
        if _member_repair_chain_started(writer, design, member):
            steps.extend(
                (
                    OperationStep(
                        stem + "-repair-permit",
                        "permit_issued",
                        STUDY_CLOSE_STAGE,
                    ),
                    OperationStep(
                        stem + "-open-repair",
                        "repair_opened",
                        STUDY_CLOSE_STAGE,
                    ),
                    OperationStep(
                        stem + "-close-repair",
                        "repair_closed",
                        STUDY_CLOSE_STAGE,
                    ),
                )
            )
        steps.append(
            OperationStep(
                stem + "-complete-job",
                "job_completed",
                STUDY_CLOSE_STAGE,
            )
        )
        if member.ordinal in failed:
            steps.append(
                OperationStep(
                    stem + "-negative-memory",
                    "negative_memory_recorded",
                    STUDY_CLOSE_STAGE,
                )
            )
        steps.append(
            OperationStep(
                stem + "-judge-job",
                "job_evidence_judged",
                STUDY_CLOSE_STAGE,
            )
        )
    steps.extend(
        (
            OperationStep(prefix + "dispose-batch", "batch_disposed", STUDY_CLOSE_STAGE),
            OperationStep(prefix + "close-study", "study_closed", STUDY_CLOSE_STAGE),
            OperationStep(prefix + "diagnose-study", "study_diagnosis_recorded", DIAGNOSE_STAGE),
            OperationStep(
                prefix + "resolve-replay",
                (
                    "historical_replay_obligations_resolved"
                    if recomputed
                    else "historical_replay_obligations_deferred"
                ),
                DIAGNOSE_STAGE,
            ),
            OperationStep(prefix + "disposition-decision", "portfolio_decision_recorded", DIAGNOSE_STAGE),
            OperationStep(prefix + "disposition-snapshot", "portfolio_snapshot_recorded", DIAGNOSE_STAGE),
            OperationStep(prefix + "close-initiative", "initiative_closed", DIAGNOSE_STAGE),
        )
    )
    return tuple(steps)


def inspect_replay_prefix(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> tuple[int, tuple[OperationStep, ...]]:
    steps = operation_steps(writer, design)
    control = writer.read_control()
    if control is None:
        raise RuntimeError("replay control is absent")
    with LocalIndex(writer.index_path) as index:
        completed = inspect_operation_prefix(
            index=index,
            journal=writer.journal,
            steps=steps,
            operation_prefix=design.spec.operation_prefix,
            predecessor_sequence=design.spec.boundary.sequence,
            predecessor_event_id=design.spec.boundary.event_id,
            current_sequence=control["heads"]["journal"]["sequence"],
        )
    return completed, steps


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
                "stable-head validation failed; rerun the stage with recovery"
            ) from exc
        writer.recover()
        return writer.require_stable_head()


def _job_cache_contract(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
    member: FixedHoldReplayMember,
) -> tuple[tuple[str, ...], dict[str, str], tuple[str, ...]]:
    plan = member.job_plan
    if plan.produces_family_cache:
        return (
            plan.expected_outputs(),
            plan.expected_output_classes(),
            plan.job_input_hashes(),
        )
    producer = design.producer_member
    completion = _member_completion(writer, design, producer)
    outputs = None if completion is None else completion.payload.get("outputs")
    if (
        completion is None
        or completion.status != "success"
        or not isinstance(outputs, Mapping)
        or set(outputs) != set(producer.job_plan.expected_outputs())
    ):
        raise RuntimeError("replay cache consumer lacks exact producer completion")
    cache_hash = outputs.get(plan.cache_output_name)
    provenance_hash = outputs.get(plan.cache_provenance_output_name)
    producer_trace_hash = outputs.get(producer.job_plan.output_names["trace"])
    for name, value in (
        ("cache", cache_hash),
        ("cache provenance", provenance_hash),
        ("producer trace", producer_trace_hash),
    ):
        _digest(f"replay {name}", value)
    assert isinstance(cache_hash, str)
    assert isinstance(provenance_hash, str)
    assert isinstance(producer_trace_hash, str)
    inputs = plan.job_input_hashes(
        cache_sha256=cache_hash,
        cache_provenance_sha256=provenance_hash,
        producer_trace_sha256=producer_trace_hash,
    )
    return plan.expected_outputs(), plan.expected_output_classes(), inputs


def build_replay_job_spec(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
    member: FixedHoldReplayMember,
) -> Mapping[str, Any]:
    plan_content = canonical_bytes(member.job_plan.plan)
    if writer.evidence.finalize(plan_content).sha256 != member.job_plan.plan_hash:
        raise RuntimeError("replay validation plan identity drifted")
    expected_outputs, output_classes, input_hashes = _job_cache_contract(
        writer,
        design,
        member,
    )
    return {
        "budget": {"compute_seconds": 3_600, "wall_seconds": 5_400},
        "callable_identity": design.spec.callable_identity,
        "evidence_subject": {
            "kind": "Executable",
            "id": member.executable.identity,
        },
        "expected_outputs": list(expected_outputs),
        "implementation_identity": design.spec.job_implementation_identity,
        "input_hashes": list(input_hashes),
        "log_path": (
            f"local/jobs/{design.spec.study_id.lower()}/{member.label}.log"
        ),
        "output_classes": output_classes,
        "resume_action": (
            "continue_batch"
            if member.ordinal < len(design.members)
            else "stop_batch"
        ),
        "scientific_binding": member.job_plan.scientific_binding(),
        "timeout_or_stop_rule": "finish the exact registered replay member",
        "worker_claims": [],
    }


def _study_permit(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> Permit:
    spec = design.spec
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
        subject_id=spec.initiative_id,
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
        expires_at_utc=spec.permit_expiry_utc,
        one_shot=True,
        operation_id=spec.operation_prefix + "study-permit",
    )


def _initiative_objective(
    design: FixedHoldReplayDesign,
) -> Mapping[str, Any]:
    count = len(design.members)
    return {
        "objective": (
            f"execute one exact {design.spec.original_study_id} P1 replay family"
        ),
        "bounds": {
            "batch_count": 1,
            "job_count": count,
            "trial_count": count,
            "wall_seconds": 21_600,
        },
        "done_conditions": [
            "the exact family is evaluated",
            "the replay obligation is satisfied or exactly deferred",
            "no candidate or holdout authority is created",
        ],
    }


def _negative_memory(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
    member: FixedHoldReplayMember,
) -> NegativeMemory:
    completion = _member_completion(writer, design, member)
    if completion is None:
        raise RuntimeError("negative memory lacks exact member completion")
    return NegativeMemory(
        executable_identity=member.executable.identity,
        scope=(
            f"{design.spec.original_study_id.lower().replace('-', '')}_replay_"
            f"{member.configuration_id}"
        ),
        evidence_references=(completion.record_id,),
        reason=(
            "The registered replay member contradicted every supported path "
            "needed for its coarse scientific verdict."
        ),
        reopen_condition=(
            "Reopen only with registered development material or a materially "
            "different causal mechanism."
        ),
    )


def _apply_study_close_step(
    writer: StateWriter,
    *,
    design: FixedHoldReplayDesign,
    step: OperationStep,
    repository_root: Path,
    job_runner: Callable[..., FixedHoldFamilyJobPacket],
    job_implementation_materializer: Callable[[StateWriter], str],
) -> Any:
    spec = design.spec
    operation_id = step.operation_id
    prefix = spec.operation_prefix
    if operation_id == prefix + "open-initiative":
        return writer.open_initiative(
            initiative_id=spec.initiative_id,
            objective=_initiative_objective(design),
            operation_id=operation_id,
        )
    if operation_id == prefix + "bridge-decision":
        return writer.record_portfolio_decision(
            decision=design.bridge_decision,
            operation_id=operation_id,
        )
    if operation_id == prefix + "expanded-snapshot":
        return writer.record_portfolio_snapshot(
            snapshot=design.expanded_snapshot,
            operation_id=operation_id,
        )
    if operation_id == prefix + "replay-decision":
        return writer.record_portfolio_decision(
            decision=design.work_decision,
            operation_id=operation_id,
        )
    if operation_id == prefix + "study-permit":
        return _study_permit(writer, design)
    if operation_id == prefix + "open-study":
        return writer.open_study(
            study_id=spec.study_id,
            question=design.question,
            material_identity=OBSERVED_MATERIAL_ID,
            material_display_name="foundation observed development material",
            semantic_proposal=design.proposal,
            controlled_chassis=design.controlled_chassis,
            portfolio_axis_id=design.replay_axis.axis_id,
            portfolio_axis_identity=design.replay_axis.identity,
            portfolio_decision_id=design.work_decision.identity,
            permit=_permit_from_operation(writer, prefix + "study-permit"),
            operation_id=operation_id,
        )
    if operation_id == prefix + "batch-permit":
        return writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id=spec.study_id,
            input_hash=design.batch_spec.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=spec.permit_expiry_utc,
            one_shot=True,
            operation_id=operation_id,
        )
    if operation_id == prefix + "open-batch":
        return writer.open_batch(
            batch_spec=design.batch_spec,
            permit=_permit_from_operation(writer, prefix + "batch-permit"),
            operation_id=operation_id,
        )
    if operation_id == _protocol_activation_operation_id(design):
        return activate_current_scientific_protocol(writer, design)
    for member in design.members:
        stem = prefix + member.label
        if operation_id == stem + "-register-trial":
            return writer.register_trial(
                executable=member.executable,
                operation_id=operation_id,
            )
        if operation_id == stem + "-declare-job":
            implementation_identity = job_implementation_materializer(writer)
            if implementation_identity != spec.job_implementation_identity:
                raise RuntimeError(
                    "replay Job implementation materialization drifted"
                )
            result = writer.declare_job(
                spec=build_replay_job_spec(writer, design, member),
                operation_id=operation_id,
            )
            if result.result.get("disposition") == "reuse_success":
                raise RuntimeError("replay unexpectedly reused an earlier Job")
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
                expires_at_utc=spec.permit_expiry_utc,
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
                writer,
                stem + "-start-job",
            ).get("execution")
            if not isinstance(execution_payload, Mapping):
                raise RuntimeError("replay Job execution binding is absent")
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
                memory=_negative_memory(writer, design, member),
                operation_id=operation_id,
            )
        if operation_id == stem + "-judge-job":
            completion = _member_completion(writer, design, member)
            if completion is None:
                raise RuntimeError("replay Job judgement lacks completion")
            scientific = completion.payload.get("scientific")
            failed = (
                isinstance(scientific, Mapping)
                and scientific.get("verdict") == "failed"
            )
            memory_id = None
            if failed:
                memory_id = _operation_result(
                    writer,
                    stem + "-negative-memory",
                ).get("negative_memory_id")
                if not isinstance(memory_id, str):
                    raise RuntimeError("replay falsification lacks negative memory")
            return writer.judge_job_evidence(
                completion_record_id=completion.record_id,
                disposition=(
                    "continue_batch"
                    if member.ordinal < len(design.members)
                    else "stop_batch"
                ),
                negative_memory_id=memory_id,
                operation_id=operation_id,
            )
    if operation_id == prefix + "dispose-batch":
        return writer.dispose_batch(
            outcome="completed",
            operation_id=operation_id,
        )
    if operation_id == prefix + "close-study":
        completion = _member_completion(writer, design, design.target_member)
        if completion is None:
            raise RuntimeError("replay close lacks target completion")
        interpretation = interpret_fixed_hold_completion(
            completion,
            criterion_ids=design.criterion_ids,
        )
        return writer.close_study(
            outcome=interpretation.close_outcome,
            kpi_completion_record_id=completion.record_id,
            operation_id=operation_id,
        )
    raise RuntimeError(f"unknown replay Study-close operation: {operation_id}")


def _study_close_record(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> IndexRecord:
    operation = _operation_record(
        writer,
        design.spec.operation_prefix + "close-study",
    )
    with LocalIndex(writer.index_path) as index:
        matches = tuple(
            record
            for record in index.records_by_kind("study-close")
            if record.subject == f"Study:{design.spec.study_id}"
            and record.authority_sequence == operation.authority_sequence
            and record.authority_event_id == operation.authority_event_id
        )
    if len(matches) != 1:
        raise RuntimeError("replay Study-close projection is ambiguous")
    return matches[0]


def _diagnosis(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> StudyDiagnosis:
    completion = _member_completion(writer, design, design.target_member)
    if completion is None:
        raise RuntimeError("replay diagnosis lacks target completion")
    interpretation = interpret_fixed_hold_completion(
        completion,
        criterion_ids=design.criterion_ids,
    )
    state = completion.payload.get("scientific", {}).get(
        "adjudication",
        {},
    ).get("state")
    return StudyDiagnosis(
        study_id=design.spec.study_id,
        study_close_record_id=_study_close_record(writer, design).record_id,
        evidence_state=interpretation.diagnosis_state,
        confidence=(
            DiagnosisConfidence.HIGH
            if interpretation.all_criteria_recomputed
            else DiagnosisConfidence.LOW
        ),
        rationale=(
            "The exact concurrent family recomputed every original criterion; "
            f"the target scientific state is {state}."
            if interpretation.all_criteria_recomputed
            else "The exact original criterion inventory was unavailable or invalid."
        ),
        counterfactual=(
            "New registered development material could change the family state "
            "without changing this historical replay result."
        ),
        reopen_condition=(
            "Reopen only when repaired implementation or registered data permits "
            "the same exact family and criterion inventory."
        ),
    )


def _diagnosis_record(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> IndexRecord:
    result = _operation_result(
        writer,
        design.spec.operation_prefix + "diagnose-study",
    )
    diagnosis_id = result.get("study_diagnosis_id")
    with LocalIndex(writer.index_path) as index:
        record = (
            None
            if not isinstance(diagnosis_id, str)
            else index.get("study-diagnosis", diagnosis_id)
        )
    if record is None:
        raise RuntimeError("replay diagnosis projection is absent")
    return record


def _replay_resolution(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> ReplaySatisfaction | ReplayDeferral:
    completion = _member_completion(writer, design, design.target_member)
    if completion is None:
        raise RuntimeError("replay resolution lacks target completion")
    interpretation = interpret_fixed_hold_completion(
        completion,
        criterion_ids=design.criterion_ids,
    )
    diagnosis = _diagnosis_record(writer, design)
    close_record = _study_close_record(writer, design)
    with LocalIndex(writer.index_path) as index:
        pairs = {
            obligation.identity: (obligation, head)
            for obligation, head in obligation_heads(
                index,
                mission_id=design.spec.mission_id,
            )
        }
        pair = pairs.get(design.spec.target_obligation_id)
        trial = index.get("trial", design.target_member.executable.identity)
        if pair is None or trial is None:
            raise RuntimeError("replay obligation or target trial is absent")
        obligation, _ = pair
        evidence_ids = replay_evidence_record_ids(
            diagnosis=diagnosis,
            close_record=close_record,
            trial=trial,
        )
    if interpretation.all_criteria_recomputed:
        facts = _scientific_facts(completion)
        assert facts is not None
        criterion_ids = validated_fixed_hold_recomputed_criterion_ids(facts)
        if criterion_ids != obligation.criterion_ids:
            raise RuntimeError("recomputed criteria differ from replay obligation")
        return ReplaySatisfaction(
            obligation_id=design.spec.target_obligation_id,
            resolution_scope=ReplayResolutionScope.SCIENTIFIC,
            portfolio_decision_id=design.work_decision.identity,
            replay_study_id=design.spec.study_id,
            replay_executable_id=design.target_member.executable.identity,
            replay_study_close_record_id=close_record.record_id,
            study_diagnosis_id=diagnosis.record_id,
            satisfied_criterion_ids=criterion_ids,
            evidence_record_ids=evidence_ids,
        )
    return ReplayDeferral(
        obligation_id=design.spec.target_obligation_id,
        basis=ReplayDeferralBasis(
            kind=ReplayDeferralBasisKind.STUDY_DIAGNOSIS,
            record_id=diagnosis.record_id,
            subject_id=design.spec.study_id,
        ),
        reason_codes=(interpretation.reason_code,),
        resume_conditions=tuple(
            ReplayResumeCondition(
                kind=kind,
                protocol_id=design.spec.job_protocol,
                original_executable_ids=tuple(
                    member.historical_reference_executable_id
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
            replay_study_id=design.spec.study_id,
            replay_executable_id=design.target_member.executable.identity,
            replay_study_close_record_id=close_record.record_id,
            study_diagnosis_id=diagnosis.record_id,
        ),
    )


def _disposition_decision(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> PortfolioDecision:
    completion = _member_completion(writer, design, design.target_member)
    if completion is None:
        raise RuntimeError("replay disposition lacks target completion")
    interpretation = interpret_fixed_hold_completion(
        completion,
        criterion_ids=design.criterion_ids,
    )
    chosen_id = (
        "preserve-recomputed-replay"
        if interpretation.disposition is PortfolioAction.PRESERVE
        else "prune-recomputed-replay"
    )
    return PortfolioDecision(
        decision_id=design.spec.decision_prefix + "-DISPOSITION",
        chosen_option_id=chosen_id,
        options=(
            DecisionOption(
                option_id=chosen_id,
                action=interpretation.disposition,
                target_id=design.replay_axis.axis_id,
                expected_information_value=(
                    "retain exact partial support"
                    if interpretation.disposition is PortfolioAction.PRESERVE
                    else "retire this exact family with its reopen condition"
                ),
                opportunity_cost="end this bounded replay Initiative",
            ),
            DecisionOption(
                option_id="open-adjacent-replay-variant",
                action=PortfolioAction.NEW_MECHANISM,
                target_id=design.replay_axis.axis_id,
                expected_information_value="unknown adjacent-search value",
                opportunity_cost="expand beyond the historical obligation",
                omission_reason=(
                    "the Initiative must not turn bounded replay into tuning"
                ),
            ),
        ),
        rationale=(
            "separate replay completion from scientific state and dispose honestly"
        ),
        commitment_batches=1,
    )


def _disposition_snapshot(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> PortfolioSnapshot:
    decision = _disposition_decision(writer, design)
    status = (
        "preserved"
        if decision.chosen.action is PortfolioAction.PRESERVE
        else "pruned"
    )
    axes = tuple(
        replace(axis, status=status)
        if axis.axis_id == design.replay_axis.axis_id
        else axis
        for axis in design.expanded_snapshot.axes
    )
    return PortfolioSnapshot(
        mission_id=design.spec.mission_id,
        axes=axes,
        opportunity_cost_basis=(
            "close the bounded replay while retaining unrelated forest branches"
        ),
        research_intake_id=design.expanded_snapshot.research_intake_id,
        exhaustion_standard=design.expanded_snapshot.exhaustion_standard_value(),
    )


def _apply_diagnose_step(
    writer: StateWriter,
    *,
    design: FixedHoldReplayDesign,
    step: OperationStep,
) -> Any:
    prefix = design.spec.operation_prefix
    operation_id = step.operation_id
    if operation_id == prefix + "diagnose-study":
        return writer.record_study_diagnosis(
            diagnosis=_diagnosis(writer, design),
            operation_id=operation_id,
        )
    if operation_id == prefix + "resolve-replay":
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
    if operation_id == prefix + "disposition-decision":
        return writer.record_portfolio_decision(
            decision=_disposition_decision(writer, design),
            operation_id=operation_id,
        )
    if operation_id == prefix + "disposition-snapshot":
        return writer.record_portfolio_snapshot(
            snapshot=_disposition_snapshot(writer, design),
            operation_id=operation_id,
        )
    if operation_id == prefix + "close-initiative":
        return writer.close_initiative(
            outcome="completed",
            operation_id=operation_id,
        )
    raise RuntimeError(f"unknown replay diagnosis operation: {operation_id}")


def _verify_no_candidate_or_holdout(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> None:
    executable_ids = {
        member.executable.identity for member in design.members
    }
    control = writer.read_control()
    with LocalIndex(writer.index_path) as index:
        candidate_records = tuple(index.records_by_kind("candidate"))
    if (
        control is None
        or control.get("scientific", {}).get("holdout_reveals") != 0
        or control.get("scientific", {}).get("active_holdout_evaluation")
        is not None
        or any(
            record.record_id in executable_ids
            or record.subject.removeprefix("Executable:") in executable_ids
            for record in candidate_records
        )
    ):
        raise RuntimeError("replay created candidate or holdout authority")


def verify_study_close_postconditions(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> Mapping[str, Any]:
    completed, steps = inspect_replay_prefix(writer, design)
    _, study_close_end = stage_bounds(steps, stage=STUDY_CLOSE_STAGE)
    if completed != study_close_end:
        raise RuntimeError("replay Study-close chain is incomplete")
    close_operation = _operation_record(
        writer,
        design.spec.operation_prefix + "close-study",
    )
    close_record = _study_close_record(writer, design)
    control = writer.read_control()
    completions = tuple(
        _member_completion(writer, design, member) for member in design.members
    )
    if (
        control is None
        or any(value is None for value in completions)
        or control.get("next_action", {}).get("kind") != "diagnose_study"
        or control.get("next_action", {}).get("study_close_record_id")
        != close_record.record_id
        or control.get("scientific", {}).get("active_study") is not None
        or control.get("scientific", {}).get("active_batch") is not None
        or control.get("scientific", {}).get("active_job") is not None
    ):
        raise RuntimeError("replay Study-close state drifted")
    for member, completion in zip(design.members, completions, strict=True):
        assert completion is not None
        outputs = completion.payload.get("outputs")
        if (
            completion.status != "success"
            or not isinstance(outputs, Mapping)
            or set(outputs) != set(member.job_plan.expected_outputs())
        ):
            raise RuntimeError("replay member completion output drifted")
    target = completions[design.target_member.ordinal - 1]
    assert target is not None
    interpretation = interpret_fixed_hold_completion(
        target,
        criterion_ids=design.criterion_ids,
    )
    if not interpretation.all_criteria_recomputed:
        raise RuntimeError("replay target did not recompute exact criteria")
    with LocalIndex(writer.index_path) as index:
        heads = {
            obligation.identity: head
            for obligation, head in obligation_heads(
                index,
                mission_id=design.spec.mission_id,
            )
        }
    target_head = heads.get(design.spec.target_obligation_id)
    if target_head is None or target_head.status != "in_progress":
        raise RuntimeError("replay obligation is not exactly in progress")
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
    design: FixedHoldReplayDesign,
    repository_root: Path,
    job_runner: Callable[..., FixedHoldFamilyJobPacket],
    job_implementation_materializer: Callable[[StateWriter], str],
    explicit_recovery: bool = False,
) -> dict[str, Any]:
    require_stable_head(writer, explicit_recovery=explicit_recovery)
    initial, steps = inspect_replay_prefix(writer, design)
    _, end = stage_bounds(steps, stage=STUDY_CLOSE_STAGE)
    if initial > end:
        raise RuntimeError("replay diagnosis already began")
    while True:
        completed, steps = inspect_replay_prefix(writer, design)
        _, end = stage_bounds(steps, stage=STUDY_CLOSE_STAGE)
        if completed == end:
            break
        if completed > end or steps[completed].stage != STUDY_CLOSE_STAGE:
            raise RuntimeError("replay Study-close prefix changed concurrently")
        _apply_study_close_step(
            writer,
            design=design,
            step=steps[completed],
            repository_root=repository_root,
            job_runner=job_runner,
            job_implementation_materializer=(
                job_implementation_materializer
            ),
        )
        advanced, _ = inspect_replay_prefix(writer, design)
        if advanced != completed + 1:
            raise RuntimeError("replay Study-close step did not advance once")
    verified = verify_study_close_postconditions(writer, design)
    final, final_steps = inspect_replay_prefix(writer, design)
    _, final_end = stage_bounds(final_steps, stage=STUDY_CLOSE_STAGE)
    return {
        "applied_step_count": final - initial,
        "batch_id": design.batch_spec.identity,
        "candidate_created": False,
        "checkpoint_required": True,
        "executable_ids": [
            member.executable.identity for member in design.members
        ],
        "holdout_reveal_delta": 0,
        "initiative_id": design.spec.initiative_id,
        "mode": "study_close_checkpoint",
        "next_stage": "diagnose_after_exact_local_main_checkpoint",
        "operation_count": final_end,
        "replay_obligation_id": design.spec.target_obligation_id,
        "schema": "fixed_hold_replay_study_close.v1",
        "study_id": design.spec.study_id,
        "trial_delta": len(design.members),
        **dict(verified),
    }


def verify_diagnose_postconditions(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> Mapping[str, Any]:
    completed, steps = inspect_replay_prefix(writer, design)
    if completed != len(steps):
        raise RuntimeError("replay diagnosis chain is incomplete")
    control = writer.read_control()
    expected_snapshot = _disposition_snapshot(writer, design)
    with LocalIndex(writer.index_path) as index:
        p1 = {
            obligation.identity: head
            for obligation, head in obligation_heads(
                index,
                mission_id=design.spec.mission_id,
            )
            if obligation.replay_priority.value == "p1"
        }
        target = p1.get(design.spec.target_obligation_id)
        pending = sorted(
            obligation_id
            for obligation_id, head in p1.items()
            if head.status == "pending"
        )
        portfolio_head = index.event_head(
            f"portfolio:{design.spec.mission_id}"
        )
    if (
        control is None
        or target is None
        or target.status not in {"satisfied", "deferred"}
        or any(
            control.get("scientific", {}).get(name) is not None
            for name in (
                "active_batch",
                "active_executable",
                "active_initiative",
                "active_job",
                "active_repair",
                "active_study",
            )
        )
        or control.get("next_action")
        != {
            "kind": "choose_next_initiative_or_terminal",
            "mission_id": design.spec.mission_id,
            "pending_replay_obligation_ids": pending,
            "required_replay_priority": "p1",
        }
        or portfolio_head is None
        or portfolio_head.record_id != expected_snapshot.identity
    ):
        raise RuntimeError("replay final scientific or scheduler state drifted")
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
    design: FixedHoldReplayDesign,
    study_close_event_id: str,
    study_close_revision: int,
    explicit_recovery: bool = False,
) -> dict[str, Any]:
    require_stable_head(writer, explicit_recovery=explicit_recovery)
    initial, steps = inspect_replay_prefix(writer, design)
    start, end = stage_bounds(steps, stage=DIAGNOSE_STAGE)
    close = _operation_record(
        writer,
        design.spec.operation_prefix + "close-study",
    )
    if (
        initial < start
        or close.authority_event_id != study_close_event_id
        or close.authority_sequence != study_close_revision
    ):
        raise RuntimeError("diagnosis does not bind exact Study-close authority")
    if initial == start:
        control = writer.read_control()
        if (
            control is None
            or control.get("revision") != study_close_revision
            or control.get("heads", {}).get("journal", {}).get("event_id")
            != study_close_event_id
            or control.get("next_action", {}).get("study_close_record_id")
            != _study_close_record(writer, design).record_id
        ):
            raise RuntimeError("Study-close checkpoint control head is not exact")
    writer._require_study_close_delivery_guard()
    while True:
        completed, steps = inspect_replay_prefix(writer, design)
        _, end = stage_bounds(steps, stage=DIAGNOSE_STAGE)
        if completed == end:
            break
        if completed < start or steps[completed].stage != DIAGNOSE_STAGE:
            raise RuntimeError("replay diagnosis prefix changed concurrently")
        _apply_diagnose_step(
            writer,
            design=design,
            step=steps[completed],
        )
        advanced, _ = inspect_replay_prefix(writer, design)
        if advanced != completed + 1:
            raise RuntimeError("replay diagnosis step did not advance once")
    verified = verify_diagnose_postconditions(writer, design)
    return {
        "applied_step_count": end - initial,
        "candidate_created": False,
        "holdout_reveal_delta": 0,
        "initiative_id": design.spec.initiative_id,
        "mode": "diagnosed_replay_and_initiative_closed",
        "next_action": writer.read_control()["next_action"],
        "replay_obligation_id": design.spec.target_obligation_id,
        "schema": "fixed_hold_replay_diagnosis.v1",
        "study_close_event_id": study_close_event_id,
        "study_close_revision": study_close_revision,
        "study_id": design.spec.study_id,
        "trial_delta": len(design.members),
        **dict(verified),
    }


def read_only_summary(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> dict[str, Any]:
    completed, steps = inspect_replay_prefix(writer, design)
    close_start, close_end = stage_bounds(steps, stage=STUDY_CLOSE_STAGE)
    diagnose_start, diagnose_end = stage_bounds(steps, stage=DIAGNOSE_STAGE)
    classes = tuple(
        output_class
        for member in design.members
        for output_class in member.job_plan.expected_output_classes().values()
    )
    return {
        "axis_count_after": len(design.expanded_snapshot.axes),
        "axis_count_before": len(design.prior_axes),
        "base_snapshot_id": design.base_snapshot_id,
        "candidate_eligible": False,
        "current_prefix": completed,
        "diagnose_operation_count": diagnose_end - diagnose_start,
        "durable_output_count": classes.count("durable_evidence"),
        "executable_ids": [
            member.executable.identity for member in design.members
        ],
        "historical_reference_executable_ids": [
            member.historical_reference_executable_id
            for member in design.members
        ],
        "initiative_id": design.spec.initiative_id,
        "mode": "read_only_plan",
        "new_axis_id": design.replay_axis.axis_id,
        "replay_obligation_ids": list(
            design.work_decision.replay_obligation_ids
        ),
        "reproducible_cache_output_count": classes.count(
            "reproducible_cache"
        ),
        "schema": "fixed_hold_replay_plan.v1",
        "study_close_operation_count": close_end - close_start,
        "study_id": design.spec.study_id,
        "target_member_ordinal": design.target_member.ordinal,
        "trial_delta": len(design.members),
    }


__all__ = [
    "DIAGNOSE_STAGE",
    "STUDY_CLOSE_STAGE",
    "FixedHoldReplayDesign",
    "FixedHoldReplayMember",
    "FixedHoldReplayMissionSpec",
    "ReplayAuthorityBoundary",
    "ReplayInterpretation",
    "build_fixed_hold_replay_design",
    "build_replay_job_spec",
    "activate_current_scientific_protocol",
    "inspect_replay_prefix",
    "interpret_fixed_hold_completion",
    "operation_steps",
    "read_only_summary",
    "require_stable_head",
    "run_diagnose_stage",
    "run_study_close_stage",
    "verify_diagnose_postconditions",
    "verify_study_close_postconditions",
]
