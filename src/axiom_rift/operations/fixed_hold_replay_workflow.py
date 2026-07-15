"""Crash-resumable Mission workflow for exact fixed-hold replay families.

The workflow owns operational ceremony once.  A protocol adapter supplies the
exact family Executables, scientific plans, controlled chassis, and Job
runner.  Durable operations contain no callback or import-path authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.component_surface import (
    COMPONENT_SURFACE_ARCHITECTURE_ROLE,
)
from axiom_rift.core.identity import ExecutableSpec
from axiom_rift.operations.batch_budget import (
    FIXED_HOLD_REPLAY_BUDGET_POLICY_ID,
    FIXED_HOLD_REPLAY_BUDGET_REPAIR_REASON,
    FIXED_HOLD_REPLAY_CONSUMER_BUDGET,
    FIXED_HOLD_REPLAY_PRODUCER_BUDGET,
    registered_batch_budget_for_output_classes,
)
from axiom_rift.operations.effective_axis_projection import (
    effective_axis_resolutions,
)
from axiom_rift.operations.replay_projection import (
    obligation_heads,
    replay_evidence_record_ids,
    scheduler_constraints,
    with_scheduler_constraints,
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
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyBindingError,
    HistoricalFamilySpec,
    historical_family_authority_from_payload,
    historical_family_from_manifest,
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
    PortfolioAxis,
    PortfolioDecision,
    PortfolioSnapshot,
    QuantTeamDecisionReview,
)
from axiom_rift.research.portfolio_projection import (
    architecture_surfaces_from_axis_projection,
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
from axiom_rift.storage.index import IndexRecord, LocalIndexView


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


def _quant_team_review(
    *,
    option_ids: Sequence[str],
    chosen_option_id: str,
    basis_records: Sequence[DecisionBasisRecord],
    primary_lens: DecisionLens,
    primary_finding: str,
    reservation_lens: DecisionLens,
    reservation_finding: str,
    claim_boundary: str,
    resolution_basis: str,
    disagreement_resolution: str,
) -> QuantTeamDecisionReview:
    """Build one compact evidence-bound allocation review."""

    normalized_options = tuple(sorted(option_ids))
    normalized_basis = tuple(
        sorted(basis_records, key=lambda record: record.sort_key)
    )
    assessments = tuple(
        sorted(
            (
                DecisionLensAssessment(
                    lens=primary_lens,
                    position=DecisionLensPosition.SUPPORT,
                    option_ids=normalized_options,
                    basis_records=normalized_basis,
                    finding=_ascii("primary quant-team finding", primary_finding),
                ),
                DecisionLensAssessment(
                    lens=reservation_lens,
                    position=DecisionLensPosition.UNCERTAIN,
                    option_ids=(chosen_option_id,),
                    basis_records=normalized_basis,
                    finding=_ascii(
                        "reservation quant-team finding",
                        reservation_finding,
                    ),
                ),
            ),
            key=lambda assessment: assessment.lens.value,
        )
    )
    return QuantTeamDecisionReview(
        assessments=assessments,
        claim_boundary=_ascii("quant-team claim boundary", claim_boundary),
        resolution_basis=_ascii("quant-team resolution basis", resolution_basis),
        disagreement_resolution=_ascii(
            "quant-team disagreement resolution",
            disagreement_resolution,
        ),
    )


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
    bridge_axis_id: str
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
            "bridge_axis_id",
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


def _canonical_statistical_family_ids(
    members: Sequence[FixedHoldReplayMember],
) -> tuple[str, ...]:
    """Return set-like family membership without changing execution order."""

    executable_ids = tuple(
        member.executable.identity for member in members
    )
    if not executable_ids or len(set(executable_ids)) != len(executable_ids):
        raise ValueError(
            "replay statistical family requires unique Executables"
        )
    return tuple(sorted(executable_ids))


def fixed_hold_replay_job_budget(
    member: FixedHoldReplayMember,
) -> dict[str, int]:
    """Reserve producer work once and a smaller proof-only consumer bound."""

    if member.job_plan.produces_family_cache:
        return dict(FIXED_HOLD_REPLAY_PRODUCER_BUDGET)
    return dict(FIXED_HOLD_REPLAY_CONSUMER_BUDGET)


def fixed_hold_replay_batch_budget(
    members: Sequence[FixedHoldReplayMember],
) -> dict[str, int]:
    budgets = tuple(fixed_hold_replay_job_budget(member) for member in members)
    if not budgets:
        raise ValueError("fixed-hold replay Batch requires members")
    return {
        field: sum(budget[field] for budget in budgets)
        for field in ("compute_seconds", "wall_seconds")
    }


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
        statistical_family_ids = _canonical_statistical_family_ids(
            self.members
        )
        definition_ids = self.members[0].job_plan.definition.prospective_executable_ids
        concurrent_family = self.batch_spec.concurrent_family
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
        if (
            concurrent_family is None
            or concurrent_family.executable_ids != statistical_family_ids
        ):
            raise ValueError(
                "replay Batch statistical family is not canonical"
            )

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
    with writer.open_stable_index() as (_control, index):
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
    index: LocalIndexView,
    spec: FixedHoldReplayMissionSpec,
) -> str:
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


def _accepted_decision_review_mode(
    index: LocalIndexView,
    operation_id: str,
) -> bool | None:
    """Preserve an accepted legacy identity; require review for new work."""

    operation = index.get("operation", operation_id)
    if operation is None:
        return None
    result = operation.payload.get("result")
    decision_id = (
        None if not isinstance(result, Mapping) else result.get("decision_id")
    )
    decision = (
        None
        if not isinstance(decision_id, str)
        else index.get("portfolio-decision", decision_id)
    )
    if (
        operation.status != "success"
        or operation.payload.get("event_kind")
        != "portfolio_decision_recorded"
        or decision is None
    ):
        raise RuntimeError("accepted replay Decision projection is invalid")
    return isinstance(decision.payload.get("quant_team_review"), Mapping)


def _projection_payloads(
    index: LocalIndexView,
    members: Sequence[FixedHoldReplayMember],
    axes: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    """Read only Component manifests named by the base Portfolio snapshot."""

    values: list[Mapping[str, Any]] = [
        member.executable.to_identity_payload() for member in members
    ]
    required_surfaces = architecture_surfaces_from_axis_projection(axes)
    values.extend(
        record.payload
        for record in index.component_manifests_by_surfaces(
            COMPONENT_SURFACE_ARCHITECTURE_ROLE,
            required_surfaces,
        )
    )
    return tuple(values)


def _terminal_replay_reconstruction_allowed(
    index: LocalIndexView,
    spec: FixedHoldReplayMissionSpec,
    target_head: IndexRecord,
) -> bool:
    """Permit read-only reconstruction only after the exact diagnosis chain."""

    if target_head.status not in {"satisfied", "deferred"}:
        return False
    expected = (
        ("diagnose-study", {"study_diagnosis_recorded"}),
        (
            "resolve-replay",
            {
                "historical_replay_obligations_resolved",
                "historical_replay_obligations_deferred",
            },
        ),
        ("disposition-decision", {"portfolio_decision_recorded"}),
        ("disposition-snapshot", {"portfolio_snapshot_recorded"}),
        ("close-initiative", {"initiative_closed"}),
    )
    records = tuple(
        index.get("operation", spec.operation_prefix + suffix)
        for suffix, _event_kinds in expected
    )
    if any(record is None for record in records):
        return False
    if any(
        record.status != "success"
        or record.payload.get("event_kind") not in event_kinds
        for record, (_suffix, event_kinds) in zip(
            records,
            expected,
            strict=True,
        )
        if record is not None
    ):
        return False
    close_result = records[-1].payload.get("result")
    return (
        isinstance(close_result, Mapping)
        and close_result.get("initiative_id") == spec.initiative_id
    )


def build_fixed_hold_replay_design(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    members: tuple[FixedHoldReplayMember, ...],
    target_executable_id: str,
    controlled_chassis: ControlledStudyChassis,
    historical_family_manifest: Mapping[str, Any],
    historical_family_authority_id: str,
    criterion_ids: tuple[str, ...],
    causal_question: str,
    mechanism_family: str,
    why_now: str,
    stop_or_reopen_condition: str,
) -> FixedHoldReplayDesign:
    """Build one exact forest-preserving replay design from durable state."""

    with writer.open_stable_index() as (_control, index):
        base_snapshot_id = _base_snapshot_id(index, spec)
        snapshot_record = index.get("portfolio-snapshot", base_snapshot_id)
        if snapshot_record is None:
            raise RuntimeError("replay base Portfolio snapshot is absent")
        raw_axes = snapshot_record.payload.get("axes")
        if not isinstance(raw_axes, list) or any(
            not isinstance(axis, Mapping) for axis in raw_axes
        ):
            raise RuntimeError("replay base Portfolio axes are malformed")
        components = component_surface_registry(
            _projection_payloads(index, members, raw_axes)
        )
        prior_axes = portfolio_axes_from_projection(
            raw_axes,
            components,
        )
        projected_axes = {
            item["axis_id"]: item for item in raw_axes
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
        obligations = {
            obligation.identity: (obligation, head)
            for obligation, head in obligation_heads(
                index,
                mission_id=spec.mission_id,
            )
        }
        target = obligations.get(spec.target_obligation_id)
        family_authority_record = index.get(
            "historical-family-authority",
            historical_family_authority_id,
        )
        terminal_reconstruction = (
            target is not None
            and _terminal_replay_reconstruction_allowed(
                index,
                spec,
                target[1],
            )
        )
        bridge_review_mode = _accepted_decision_review_mode(
            index,
            spec.operation_prefix + "bridge-decision",
        )
        replay_review_mode = _accepted_decision_review_mode(
            index,
            spec.operation_prefix + "replay-decision",
        )
    if (
        any(axis.axis_id == spec.axis_id for axis in prior_axes)
        or not selectable
        or target is None
        or (
            target[1].status not in {"pending", "in_progress"}
            and not terminal_reconstruction
        )
    ):
        raise RuntimeError("replay axis, bridge, or obligation boundary is invalid")
    obligation, _target_head = target
    definition_family = members[0].job_plan.definition.family
    if not isinstance(definition_family, HistoricalFamilySpec):
        raise RuntimeError(
            "prospective replay definition must use Writer-bound family data"
        )
    try:
        if family_authority_record is None:
            raise HistoricalFamilyBindingError(
                "historical family authority is absent"
            )
        family_authority = historical_family_authority_from_payload(
            family_authority_record.payload
        )
        caller_family = historical_family_from_manifest(
            dict(historical_family_manifest)
        )
    except HistoricalFamilyBindingError as exc:
        raise RuntimeError(
            "prospective replay historical family authority is malformed"
        ) from exc
    manifest_family = family_authority.family
    if (
        historical_family_authority_id != family_authority.identity
        or family_authority_record.record_id != family_authority.identity
        or family_authority_record.subject
        != f"ReplayObligation:{spec.target_obligation_id}"
        or family_authority_record.status != "accepted"
        or family_authority_record.fingerprint
        != family_authority.identity.removeprefix(
            "historical-family-authority:"
        )
        or family_authority.replay_obligation_id
        != spec.target_obligation_id
        or family_authority.family != definition_family
        or caller_family != manifest_family
    ):
        raise RuntimeError(
            "prospective replay family differs from durable authority"
        )
    target_members = tuple(
        member
        for member in members
        if member.executable.identity == target_executable_id
    )
    manifest_references = tuple(
        item.historical_reference_executable_id
        for item in manifest_family.members
    )
    if (
        len(target_members) != 1
        or obligation.original_study_id != spec.original_study_id
        or obligation.original_executable_id
        != target_members[0].historical_reference_executable_id
        or obligation.criterion_ids != criterion_ids
        or manifest_family.original_study_id != spec.original_study_id
        or manifest_family.target_historical_executable_id
        != obligation.original_executable_id
        or manifest_references
        != tuple(
            member.historical_reference_executable_id for member in members
        )
    ):
        raise RuntimeError("replay design differs from its exact obligation")
    bridge_axes = tuple(
        axis for axis in selectable if axis.axis_id == spec.bridge_axis_id
    )
    if len(bridge_axes) != 1:
        raise RuntimeError("replay bridge axis is not exactly selectable")
    source_axis = bridge_axes[0]
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
    bridge_options = (
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
        )
    bridge_decision = PortfolioDecision(
        decision_id=spec.decision_prefix + "-BRIDGE",
        chosen_option_id="add-bounded-replay-bridge",
        options=bridge_options,
        rationale=(
            "add one replay bridge without mutating or reinterpreting prior axes"
        ),
        commitment_batches=1,
        quant_team_review=None if bridge_review_mode is False else _quant_team_review(
            option_ids=tuple(option.option_id for option in bridge_options),
            chosen_option_id="add-bounded-replay-bridge",
            basis_records=(
                DecisionBasisRecord(
                    kind="historical-replay-obligation",
                    record_id=spec.target_obligation_id,
                ),
                DecisionBasisRecord(
                    kind="portfolio-snapshot",
                    record_id=snapshot_record.record_id,
                ),
            ),
            primary_lens=DecisionLens.CAUSALITY,
            primary_finding=(
                "the exact obligation isolates one historical criterion defect"
            ),
            reservation_lens=DecisionLens.RISK,
            reservation_finding=(
                "one bounded replay Batch delays unrelated forest allocation"
            ),
            claim_boundary=(
                "bridge admission only; no scientific or candidate authority"
            ),
            resolution_basis=(
                "the exact locally executable obligation has bounded high information"
            ),
            disagreement_resolution=(
                "retain every unrelated eligible axis independently selectable"
            ),
        ),
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
    work_options = (
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
        )
    work_decision = PortfolioDecision(
        decision_id=spec.decision_prefix + "-REPLAY",
        chosen_option_id="run-exact-concurrent-family",
        options=work_options,
        rationale=(
            "select only the exact typed P1 obligation while peers remain schedulable"
        ),
        commitment_batches=1,
        quant_team_review=None if replay_review_mode is False else _quant_team_review(
            option_ids=tuple(option.option_id for option in work_options),
            chosen_option_id="run-exact-concurrent-family",
            basis_records=(
                DecisionBasisRecord(
                    kind="historical-replay-obligation",
                    record_id=spec.target_obligation_id,
                ),
                DecisionBasisRecord(
                    kind="portfolio-snapshot",
                    record_id=expanded_snapshot.identity,
                ),
            ),
            primary_lens=DecisionLens.STATISTICS,
            primary_finding=(
                "the synchronized family recomputes the exact selection inference"
            ),
            reservation_lens=DecisionLens.EXECUTION,
            reservation_finding=(
                "the full family consumes bounded local compute before other work"
            ),
            claim_boundary=(
                "one replay obligation only; no unrelated claim or candidate authority"
            ),
            resolution_basis=(
                "exact family recomputation dominates deferral while inputs are available"
            ),
            disagreement_resolution=(
                "cap work at one Batch and leave peer obligations schedulable"
            ),
        ),
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
        "historical_obligation_id": spec.target_obligation_id,
        "mechanism": mechanism_family,
        "original_study_id": spec.original_study_id,
    }
    proposal.update(
        {
            "concurrent_family": manifest_family.manifest(),
            "historical_family_authority_id": family_authority.identity,
            "historical_family_identity": manifest_family.identity,
        }
    )
    study_hash = writer.study_input_hash(
        question=question,
        material_identity=OBSERVED_MATERIAL_ID,
        semantic_proposal=proposal,
        controlled_chassis=controlled_chassis,
        portfolio_axis_id=replay_axis.axis_id,
        portfolio_axis_identity=replay_axis.identity,
        portfolio_decision_id=work_decision.identity,
    )
    batch_budget = fixed_hold_replay_batch_budget(members)
    batch_spec = BatchSpec(
        batch_id=spec.batch_display_id,
        study_id=spec.study_id,
        study_hash=study_hash,
        display_name=spec.display_name,
        max_trials=len(members),
        max_compute_seconds=batch_budget["compute_seconds"],
        max_wall_seconds=batch_budget["wall_seconds"],
        stop_rule="stop only after the exact registered family",
        source_contract_ids=(),
        concurrent_family=ConcurrentFamilyManifest(
            evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
            executable_ids=_canonical_statistical_family_ids(members),
        ),
        acceptance_profile={
            "candidate_authority": "none",
            "exact_original_criteria": list(criterion_ids),
            "historical_family_authority_id": family_authority.identity,
            "historical_family_identity": manifest_family.identity,
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
    *,
    _index: LocalIndexView | None = None,
) -> IndexRecord | None:
    operation_id = (
        design.spec.operation_prefix + member.label + "-complete-job"
    )
    index_context = (
        writer.open_stable_index()
        if _index is None
        else nullcontext((None, _index))
    )
    with index_context as (_control, index):
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


def _workflow_job_declarations(
    index: LocalIndexView,
    design: FixedHoldReplayDesign,
    *,
    batch_id: str,
) -> tuple[IndexRecord, ...]:
    """Resolve this exact family's Job declarations through immutable keys."""

    declarations: list[IndexRecord] = []
    for member in design.members:
        operation_id = (
            design.spec.operation_prefix + member.label + "-declare-job"
        )
        operation = index.get("operation", operation_id)
        if operation is None:
            continue
        result = operation.payload.get("result")
        job_id = result.get("job_id") if isinstance(result, Mapping) else None
        job_hash = (
            result.get("job_hash") if isinstance(result, Mapping) else None
        )
        declaration = (
            index.get("job-declared", job_id)
            if isinstance(job_id, str)
            else None
        )
        evidence_subject = (
            None
            if declaration is None
            else declaration.payload.get("spec", {}).get("evidence_subject")
        )
        if (
            operation.status != "success"
            or operation.payload.get("event_kind") != "job_declared"
            or declaration is None
            or declaration.record_id != job_id
            or declaration.status != "declared"
            or declaration.payload.get("batch_id") != batch_id
            or declaration.payload.get("study_id") != design.spec.study_id
            or declaration.payload.get("mission_id") != design.spec.mission_id
            or not isinstance(evidence_subject, Mapping)
            or evidence_subject.get("kind") != "Executable"
            or evidence_subject.get("id") != member.executable.identity
            or job_id != "job:" + str(job_hash)
        ):
            raise RuntimeError(
                "replay Job declaration projection is malformed"
            )
        declarations.append(declaration)
    return tuple(declarations)


def _engineering_failure_member(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
    *,
    _index: LocalIndexView | None = None,
) -> tuple[FixedHoldReplayMember, IndexRecord] | None:
    failures: list[tuple[FixedHoldReplayMember, IndexRecord]] = []
    for member in design.members:
        completion = _member_completion(
            writer,
            design,
            member,
            _index=_index,
        )
        failure = None if completion is None else completion.payload.get("failure")
        disposition = (
            None
            if completion is None
            else completion.payload.get("engineering_disposition")
        )
        if (
            completion is not None
            and getattr(completion, "status", None) == "failed"
            and isinstance(failure, Mapping)
            and failure.get("failure_kind") == "engineering"
            and isinstance(disposition, Mapping)
            and disposition.get("schema")
            == "engineering_failure_disposition.v1"
        ):
            failures.append((member, completion))
    if len(failures) > 1:
        raise RuntimeError("replay family has multiple terminal engineering failures")
    return None if not failures else failures[0]


def _member_unrecovered_repair_operation_id(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
    member: FixedHoldReplayMember,
) -> str | None:
    matches = tuple(
        step.operation_id
        for step in _member_repair_chain_complete(writer, design, member)
        if step.event_kind == "repair_concluded_unrecovered"
    )
    if len(matches) > 1:
        raise RuntimeError("replay member has multiple unrecovered Repairs")
    return None if not matches else matches[0]


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


def _workflow_interpretation(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> ReplayInterpretation:
    if _engineering_failure_member(writer, design) is not None:
        return ReplayInterpretation(
            all_criteria_recomputed=False,
            close_outcome="not_evaluable",
            diagnosis_state=EvidenceState.ENGINEERING_GAP,
            disposition=PortfolioAction.PRESERVE,
            reason_code="unrecovered_same_protocol_engineering_gap",
        )
    completion = _member_completion(writer, design, design.target_member)
    if completion is None:
        raise RuntimeError("replay target completion is unavailable")
    return interpret_fixed_hold_completion(
        completion,
        criterion_ids=design.criterion_ids,
    )


def _protocol_activation_operation_id(
    design: FixedHoldReplayDesign,
) -> str:
    validator_digest = SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID.removeprefix(
        "validator:"
    )
    return (
        design.spec.operation_prefix
        + "activate-v2-protocol-"
        + validator_digest
    )


def _recorded_protocol_activation_operation_ids(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
    *,
    _index: LocalIndexView | None = None,
) -> tuple[str, ...]:
    """Preserve every prior validator activation in strict replay order."""

    prefix = design.spec.operation_prefix
    legacy_id = prefix + "activate-current-v2-protocol"
    versioned_prefix = prefix + "activate-v2-protocol-"
    ordered: list[tuple[int, str]] = []
    index_context = (
        writer.open_stable_index()
        if _index is None
        else nullcontext((None, _index))
    )
    with index_context as (_control, index):
        for operation in index.records_by_kind_prefix("operation", prefix):
            if not (
                operation.record_id == legacy_id
                or operation.record_id.startswith(versioned_prefix)
            ):
                continue
            result = operation.payload.get("result")
            activation_id = (
                result.get("activation_record_id")
                if isinstance(result, Mapping)
                else None
            )
            activation = (
                index.get("research-protocol-activation", activation_id)
                if isinstance(activation_id, str)
                else None
            )
            if (
                operation.status != "success"
                or operation.payload.get("event_kind")
                != "research_protocol_activated"
                or activation is None
                or activation.kind != "research-protocol-activation"
                or type(activation.event_sequence) is not int
            ):
                raise RuntimeError(
                    "recorded replay protocol activation is malformed"
                )
            ordered.append((activation.event_sequence, operation.record_id))
    ordered.sort()
    operation_ids = tuple(operation_id for _ordinal, operation_id in ordered)
    if len(operation_ids) != len(set(operation_ids)):
        raise RuntimeError("replay protocol activation history is ambiguous")
    return operation_ids


def _protocol_activation_step_needed(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
    *,
    _control: Mapping[str, Any] | None = None,
    _index: LocalIndexView | None = None,
) -> bool:
    """Keep a required activation in the strict chain after it is recorded."""

    if (_control is None) != (_index is None):
        raise RuntimeError("replay protocol snapshot is incomplete")
    operation_id = _protocol_activation_operation_id(design)
    index_context = (
        writer.open_stable_index()
        if _index is None
        else nullcontext((_control, _index))
    )
    with index_context as (control, index):
        assert control is not None
        authority_digest = control.get("authority", {}).get("manifest_digest")
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


def _member_repair_chain_complete(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
    member: FixedHoldReplayMember,
    *,
    _index: LocalIndexView | None = None,
    _operations: tuple[IndexRecord, ...] | None = None,
) -> tuple[OperationStep, ...]:
    """Preserve every complete Repair episode inside the strict chain.

    Episode one keeps the historical operation names.  Later episodes use an
    explicit three-digit episode namespace.  A partial episode is an exact
    resume boundary; a skipped episode, missing engine re-entry, or Repair
    after an unrecovered terminal is rejected rather than silently omitted.
    """

    if (_index is None) != (_operations is None):
        raise RuntimeError("replay Repair operation snapshot is incomplete")
    stem = design.spec.operation_prefix + member.label

    def names(episode: int) -> dict[str, str]:
        if episode == 1:
            return {
                "permit": stem + "-repair-permit",
                "open": stem + "-open-repair",
                "attempt_prefix": stem + "-repair-attempt-",
                "close": stem + "-close-repair",
                "conclude": stem + "-conclude-repair",
                "resume": stem + "-resume-repaired-job",
            }
        base = f"{stem}-repair-episode-{episode:03d}"
        return {
            "permit": base + "-permit",
            "open": base + "-open",
            "attempt_prefix": base + "-attempt-",
            "close": base + "-close",
            "conclude": base + "-conclude",
            "resume": base + "-resume",
        }

    legacy_names = set(names(1).values())
    numbered_prefix = stem + "-repair-episode-"
    index_context = (
        writer.open_stable_index()
        if _index is None
        else nullcontext((None, _index))
    )
    with index_context as (_control, index):
        operations = (
            tuple(
                index.records_by_kind_prefix(
                    "operation",
                    design.spec.operation_prefix,
                )
            )
            if _operations is None
            else _operations
        )
        relevant_by_id = {
            record.record_id: record
            for record in operations
            if record.record_id in legacy_names
            or record.record_id.startswith(numbered_prefix)
        }
        for operation_id in legacy_names:
            legacy = index.get("operation", operation_id)
            if legacy is not None:
                relevant_by_id[legacy.record_id] = legacy
        relevant = tuple(relevant_by_id.values())
        if not relevant:
            return ()
        episodes: set[int] = set()
        for operation in relevant:
            if operation.record_id in legacy_names:
                episodes.add(1)
                continue
            suffix = operation.record_id[len(numbered_prefix) :]
            ordinal_text, separator, _tail = suffix.partition("-")
            if (
                separator != "-"
                or len(ordinal_text) != 3
                or not ordinal_text.isdigit()
                or int(ordinal_text) < 2
            ):
                raise RuntimeError(
                    "replay Repair episode operation identity is malformed"
                )
            episodes.add(int(ordinal_text))
        ordered_episodes = tuple(sorted(episodes))
        if ordered_episodes != tuple(range(1, ordered_episodes[-1] + 1)):
            raise RuntimeError("replay Repair episodes are not contiguous")

        steps: list[OperationStep] = []
        prior_close_id: str | None = None
        prior_resume_sequence: int | None = None
        prior_unrecovered = False
        for episode in ordered_episodes:
            if prior_unrecovered:
                raise RuntimeError(
                    "replay Repair continues after an unrecovered terminal"
                )
            expected = names(episode)
            permit = index.get("operation", expected["permit"])
            opened_operation = index.get("operation", expected["open"])
            close_operation = index.get("operation", expected["close"])
            conclude_operation = index.get(
                "operation", expected["conclude"]
            )
            terminals = tuple(
                record
                for record in (close_operation, conclude_operation)
                if record is not None
            )
            missing = tuple(
                operation_id
                for operation_id, record in (
                    (expected["permit"], permit),
                    (expected["open"], opened_operation),
                )
                if record is None
            )
            if missing or len(terminals) != 1:
                terminal_missing = (
                    ()
                    if terminals
                    else (expected["close"] + "|" + expected["conclude"],)
                )
                raise RuntimeError(
                    "replay Repair is incomplete; resume exact operations: "
                    + ",".join((*missing, *terminal_missing))
                )
            terminal = terminals[0]
            terminal_event = (
                "repair_closed"
                if terminal.record_id == expected["close"]
                else "repair_concluded_unrecovered"
            )
            for record, event_kind in (
                (permit, "permit_issued"),
                (opened_operation, "repair_opened"),
                (terminal, terminal_event),
            ):
                assert record is not None
                if (
                    record.status != "success"
                    or record.payload.get("event_kind") != event_kind
                    or type(record.authority_sequence) is not int
                ):
                    raise RuntimeError(
                        "replay Repair operation chain is malformed"
                    )
            assert permit is not None and opened_operation is not None
            if not (
                permit.authority_sequence
                < opened_operation.authority_sequence
                < terminal.authority_sequence
            ):
                raise RuntimeError("replay Repair operation order drifted")
            if (
                prior_resume_sequence is not None
                and prior_resume_sequence >= permit.authority_sequence
            ):
                raise RuntimeError(
                    "replay Repair episode precedes prior engine re-entry"
                )
            repair_id = opened_operation.payload.get("result", {}).get(
                "repair_id"
            )
            opened = (
                None
                if not isinstance(repair_id, str)
                else index.get("repair-open", repair_id)
            )
            if (
                opened is None
                or opened.payload.get("episode") != episode
                or opened.payload.get("predecessor_repair_close_record_id")
                != prior_close_id
            ):
                raise RuntimeError(
                    "replay Repair episode provenance is unavailable"
                )
            terminal_result = terminal.payload.get("result", {})
            terminal_repair_id = terminal_result.get("repair_id")
            if (
                terminal_repair_id is not None
                and terminal_repair_id != repair_id
            ):
                raise RuntimeError(
                    "replay Repair terminal names another Repair"
                )
            repair_close_id = terminal_result.get("repair_close_record_id")
            repair_close = (
                None
                if not isinstance(repair_close_id, str)
                else index.get("repair-close", repair_close_id)
            )
            expected_close_status = (
                "repaired"
                if terminal_event == "repair_closed"
                else "unrecovered"
            )
            if (
                repair_close is None
                or repair_close.status != expected_close_status
                or repair_close.payload.get("repair_id") != repair_id
            ):
                raise RuntimeError(
                    "replay Repair terminal projection is unavailable"
                )
            failed = tuple(
                sorted(
                    (
                        record
                        for record in operations
                        if record.payload.get("event_kind")
                        == "repair_attempt_failed"
                        and record.payload.get("result", {}).get("repair_id")
                        == repair_id
                    ),
                    key=lambda record: (
                        record.authority_sequence,
                        record.record_id,
                    ),
                )
            )
            projected_for_subject = tuple(
                record
                for record in index.records_by_subject_status(
                    f"Repair:{repair_id}",
                    "failed",
                )
                if record.kind == "repair-attempt"
            )
            if any(
                record.payload.get("repair_id") != repair_id
                for record in projected_for_subject
            ):
                raise RuntimeError(
                    "replay Repair attempt projection names another Repair"
                )
            projected_failed = tuple(
                sorted(
                    projected_for_subject,
                    key=lambda record: (
                        record.event_sequence,
                        record.record_id,
                    ),
                )
            )
            if len(failed) != len(projected_failed):
                raise RuntimeError(
                    "replay Repair attempt operation/projection count drifted"
                )
            if any(
                record.record_id
                != expected["attempt_prefix"] + f"{ordinal:03d}"
                or record.status != "success"
                or type(record.authority_sequence) is not int
                or record.payload.get("result", {}).get(
                    "attempt_record_id"
                )
                != projected_failed[ordinal - 1].record_id
                or projected_failed[ordinal - 1].status != "failed"
                or projected_failed[ordinal - 1].event_stream
                != f"repair-attempt:{repair_id}"
                or projected_failed[ordinal - 1].event_sequence != ordinal
                or not (
                    opened_operation.authority_sequence
                    < record.authority_sequence
                    < terminal.authority_sequence
                )
                for ordinal, record in enumerate(failed, start=1)
            ):
                raise RuntimeError(
                    "replay Repair attempt is outside its exact operation chain"
                )
            steps.extend(
                (
                    OperationStep(
                        expected["permit"],
                        "permit_issued",
                        STUDY_CLOSE_STAGE,
                    ),
                    OperationStep(
                        expected["open"],
                        "repair_opened",
                        STUDY_CLOSE_STAGE,
                    ),
                    *(
                        OperationStep(
                            record.record_id,
                            "repair_attempt_failed",
                            STUDY_CLOSE_STAGE,
                        )
                        for record in failed
                    ),
                    OperationStep(
                        terminal.record_id,
                        terminal_event,
                        STUDY_CLOSE_STAGE,
                    ),
                )
            )
            if terminal_event == "repair_closed":
                resume = index.get("operation", expected["resume"])
                if resume is not None and (
                    resume.status != "success"
                    or resume.payload.get("event_kind")
                    != "job_repaired_execution_resumed"
                    or resume.payload.get("result", {}).get(
                        "repair_close_record_id"
                    )
                    != repair_close_id
                    or type(resume.authority_sequence) is not int
                    or resume.authority_sequence
                    <= terminal.authority_sequence
                ):
                    raise RuntimeError(
                        "replay Repair engine re-entry is malformed"
                    )
                if episode < ordered_episodes[-1] and resume is None:
                    raise RuntimeError(
                        "replay Repair episode omits engine re-entry"
                    )
                steps.append(
                    OperationStep(
                        expected["resume"],
                        "job_repaired_execution_resumed",
                        STUDY_CLOSE_STAGE,
                    )
                )
                prior_resume_sequence = (
                    None if resume is None else resume.authority_sequence
                )
            else:
                if index.get("operation", expected["resume"]) is not None:
                    raise RuntimeError(
                        "unrecovered replay Repair cannot resume execution"
                    )
                prior_unrecovered = True
                prior_resume_sequence = None
            prior_close_id = repair_close_id
    return tuple(steps)


def _all_member_repair_chains(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
    *,
    _index: LocalIndexView | None = None,
) -> dict[int, tuple[OperationStep, ...]]:
    """Read one authoritative workflow slice and share it across the family."""

    index_context = (
        writer.open_stable_index()
        if _index is None
        else nullcontext((None, _index))
    )
    with index_context as (_control, index):
        operations = tuple(
            index.records_by_kind_prefix(
                "operation",
                design.spec.operation_prefix,
            )
        )
        return {
            member.ordinal: _member_repair_chain_complete(
                writer,
                design,
                member,
                _index=index,
                _operations=operations,
            )
            for member in design.members
        }


def activate_current_scientific_protocol(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> Any:
    """Audit and bind the current validator before this Study's first Job."""

    with writer.open_stable_index() as (control, index):
        authority_digest = control.get("authority", {}).get("manifest_digest")
        if type(authority_digest) is not str:
            raise RuntimeError("replay protocol activation lacks authority")
        science = control.get("scientific", {})
        study_id = (
            science.get("active_study")
            if isinstance(science, Mapping)
            else None
        )
        batch = (
            science.get("active_batch")
            if isinstance(science, Mapping)
            else None
        )
        head = index.event_head("research-protocol:scientific")
        prior = (
            None
            if head is None
            else index.get(head.record_kind, head.record_id)
        )
        batch_id = batch.get("id") if isinstance(batch, Mapping) else None
        current_study_job_count = (
            len(
                _workflow_job_declarations(
                    index,
                    design,
                    batch_id=batch_id,
                )
            )
            if isinstance(study_id, str) and isinstance(batch_id, str)
            else 0
        )
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


def _batch_budget_repair_operation_id(
    design: FixedHoldReplayDesign,
) -> str:
    return design.spec.operation_prefix + "repair-batch-budget-reservations"


def _corrected_declared_job_budget(
    declaration: IndexRecord,
) -> dict[str, int]:
    spec = declaration.payload.get("spec")
    output_classes = (
        None if not isinstance(spec, Mapping) else spec.get("output_classes")
    )
    if not isinstance(output_classes, Mapping):
        raise RuntimeError("replay budget repair Job classes are malformed")
    try:
        return registered_batch_budget_for_output_classes(
            policy_id=FIXED_HOLD_REPLAY_BUDGET_POLICY_ID,
            output_classes=output_classes,
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def _batch_budget_repair_boundary(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
    *,
    _control: Mapping[str, Any] | None = None,
    _index: LocalIndexView | None = None,
) -> int | None:
    if (_control is None) != (_index is None):
        raise RuntimeError("replay Batch budget snapshot is incomplete")
    operation_id = _batch_budget_repair_operation_id(design)
    index_context = (
        writer.open_stable_index()
        if _index is None
        else nullcontext((_control, _index))
    )
    with index_context as (control, index):
        assert control is not None
        operation = index.get("operation", operation_id)
        if operation is not None:
            result = operation.payload.get("result")
            count = (
                None
                if not isinstance(result, Mapping)
                else result.get("completed_job_count")
            )
            if (
                operation.status != "success"
                or operation.payload.get("event_kind")
                != "batch_budget_repaired"
                or type(count) is not int
                or count < 1
                or count >= len(design.members)
            ):
                raise RuntimeError("replay Batch budget Repair is malformed")
            return count
        science = control.get("scientific")
        batch = (
            None
            if not isinstance(science, Mapping)
            else science.get("active_batch")
        )
        if not isinstance(batch, Mapping) or type(batch.get("id")) is not str:
            return None
        declarations = _workflow_job_declarations(
            index,
            design,
            batch_id=batch["id"],
        )
    if not declarations:
        return None
    drifted = False
    for declaration in declarations:
        spec = declaration.payload.get("spec")
        declared = None if not isinstance(spec, Mapping) else spec.get("budget")
        corrected = _corrected_declared_job_budget(declaration)
        if not isinstance(declared, Mapping):
            raise RuntimeError("replay budget repair Job budget is malformed")
        observed = {
            "compute_seconds": declared.get("compute_seconds"),
            "wall_seconds": declared.get("wall_seconds"),
        }
        if any(
            type(observed[field]) is not int
            or corrected[field] > observed[field]
            for field in ("compute_seconds", "wall_seconds")
        ):
            raise RuntimeError("replay budget policy cannot rebase this Job")
        drifted = drifted or observed != corrected
    if not drifted:
        return None
    count = len(declarations)
    if count >= len(design.members):
        raise RuntimeError("completed replay family cannot need budget repair")
    return count


def repair_fixed_hold_replay_batch_budget(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> Any:
    with writer.open_stable_index() as (control, index):
        science = control.get("scientific")
        batch = (
            None
            if not isinstance(science, Mapping)
            else science.get("active_batch")
        )
        if not isinstance(batch, Mapping) or type(batch.get("id")) is not str:
            raise RuntimeError("replay Batch budget Repair lacks an active Batch")
        declarations = _workflow_job_declarations(
            index,
            design,
            batch_id=batch["id"],
        )
    corrected = {
        declaration.record_id: _corrected_declared_job_budget(declaration)
        for declaration in declarations
    }
    manifest = writer.plan_batch_budget_reservation_repair(
        corrected_job_budgets=corrected,
        policy_id=FIXED_HOLD_REPLAY_BUDGET_POLICY_ID,
        reason=FIXED_HOLD_REPLAY_BUDGET_REPAIR_REASON,
    )
    proof = writer.evidence.finalize(canonical_bytes(manifest))
    return writer.repair_batch_budget_reservations(
        corrected_job_budgets=corrected,
        policy_id=FIXED_HOLD_REPLAY_BUDGET_POLICY_ID,
        reason=FIXED_HOLD_REPLAY_BUDGET_REPAIR_REASON,
        proof_hash=proof.sha256,
        operation_id=_batch_budget_repair_operation_id(design),
    )


def operation_steps(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
    *,
    _control: Mapping[str, Any] | None = None,
    _index: LocalIndexView | None = None,
) -> tuple[OperationStep, ...]:
    if (_control is None) != (_index is None):
        raise RuntimeError("replay operation-plan snapshot is incomplete")
    if _index is None:
        with writer.open_stable_index() as (control, index):
            return operation_steps(
                writer,
                design,
                _control=control,
                _index=index,
            )
    assert _control is not None
    prefix = design.spec.operation_prefix
    budget_repair_boundary = _batch_budget_repair_boundary(
        writer,
        design,
        _control=_control,
        _index=_index,
    )
    failed = {
        member.ordinal
        for member in design.members
        if (
            (
                completion := _member_completion(
                    writer,
                    design,
                    member,
                    _index=_index,
                )
            )
            is not None
            and isinstance(completion.payload.get("scientific"), Mapping)
            and completion.payload["scientific"].get("verdict") == "failed"
        )
    }
    target = _member_completion(
        writer,
        design,
        design.target_member,
        _index=_index,
    )
    engineering_failure = _engineering_failure_member(
        writer,
        design,
        _index=_index,
    )
    repair_chains = _all_member_repair_chains(
        writer,
        design,
        _index=_index,
    )
    unrecovered_present = any(
        step.event_kind == "repair_concluded_unrecovered"
        for chain in repair_chains.values()
        for step in chain
    )
    recomputed = (
        engineering_failure is None
        and not unrecovered_present
        and target is not None
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
    activation_operation_ids = list(
        _recorded_protocol_activation_operation_ids(
            writer,
            design,
            _index=_index,
        )
    )
    current_activation_operation_id = _protocol_activation_operation_id(design)
    if (
        _protocol_activation_step_needed(
            writer,
            design,
            _control=_control,
            _index=_index,
        )
        and current_activation_operation_id not in activation_operation_ids
    ):
        activation_operation_ids.append(current_activation_operation_id)
    for activation_operation_id in activation_operation_ids:
        steps.append(
            OperationStep(
                activation_operation_id,
                "research_protocol_activated",
                STUDY_CLOSE_STAGE,
            )
        )
    # Freeze the complete concurrent family before any member Job can expose
    # evidence.  Registration order remains the protocol's execution order;
    # the Batch manifest separately carries canonical set-like membership.
    for member in design.members:
        stem = prefix + member.label
        steps.append(
            OperationStep(
                stem + "-register-trial",
                "trial_registered",
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
        repair_steps = repair_chains[member.ordinal]
        steps.extend(repair_steps)
        unrecovered_repair = any(
            item.event_kind == "repair_concluded_unrecovered"
            for item in repair_steps
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
        if unrecovered_repair:
            break
        if budget_repair_boundary == member.ordinal:
            steps.append(
                OperationStep(
                    _batch_budget_repair_operation_id(design),
                    "batch_budget_repaired",
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
    with writer.open_stable_index() as (control, index):
        steps = operation_steps(
            writer,
            design,
            _control=control,
            _index=index,
        )
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
        "budget": fixed_hold_replay_job_budget(member),
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
    budget = fixed_hold_replay_batch_budget(design.members)
    return {
        "objective": (
            f"execute one exact {design.spec.original_study_id} P1 replay family"
        ),
        "bounds": {
            "batch_count": 1,
            "job_count": count,
            "trial_count": count,
            "wall_seconds": budget["wall_seconds"],
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
    if operation_id == _batch_budget_repair_operation_id(design):
        return repair_fixed_hold_replay_batch_budget(writer, design)
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
        repair_resume_operation_ids = (
            {
                repair_step.operation_id
                for repair_step in _member_repair_chain_complete(
                    writer,
                    design,
                    member,
                )
                if repair_step.event_kind
                == "job_repaired_execution_resumed"
            }
            if operation_id == stem + "-resume-repaired-job"
            or operation_id.startswith(stem + "-repair-episode-")
            else set()
        )
        if operation_id in repair_resume_operation_ids:
            execution_payload = _operation_result(
                writer,
                stem + "-start-job",
            ).get("execution")
            declaration_result = _operation_result(
                writer,
                stem + "-declare-job",
            )
            job_id = declaration_result.get("job_id")
            with writer.open_stable_index() as (_control, index):
                declaration = (
                    None
                    if not isinstance(job_id, str)
                    else index.get("job-declared", job_id)
                )
            job_spec = (
                None
                if declaration is None
                else declaration.payload.get("spec")
            )
            if (
                not isinstance(execution_payload, Mapping)
                or not isinstance(job_spec, Mapping)
            ):
                raise RuntimeError("replay Repair resume binding is absent")
            return writer.resume_repaired_job_execution(
                RunningJobExecution.from_mapping(execution_payload),
                expected_callable_identity=spec.callable_identity,
                expected_evidence_subject=job_spec["evidence_subject"],
                required_input_hashes=tuple(job_spec["input_hashes"]),
                operation_id=operation_id,
            )
        if operation_id == stem + "-complete-job":
            unrecovered_operation_id = (
                _member_unrecovered_repair_operation_id(
                    writer,
                    design,
                    member,
                )
            )
            if unrecovered_operation_id is not None:
                conclusion = _operation_result(
                    writer,
                    unrecovered_operation_id,
                )
                repair_id = conclusion.get("repair_id")
                disposition_hash = conclusion.get("disposition_hash")
                with writer.open_stable_index() as (_control, index):
                    opened = (
                        None
                        if not isinstance(repair_id, str)
                        else index.get("repair-open", repair_id)
                    )
                if (
                    opened is None
                    or not isinstance(disposition_hash, str)
                ):
                    raise RuntimeError(
                        "unrecovered replay Repair provenance is absent"
                    )
                return writer.complete_job(
                    outcome="failed",
                    output_manifest={},
                    failure={
                        "failure_kind": "engineering",
                        "interrupted_action": opened.payload[
                            "interrupted_action"
                        ],
                        "minimum_reproduction_evidence": list(
                            opened.payload[
                                "minimum_reproduction_evidence"
                            ]
                        ),
                        "repair_disposition_hash": disposition_hash,
                        "resume_action": opened.payload["resume_action"],
                        "root_cause": opened.payload["root_cause"],
                    },
                    operation_id=operation_id,
                )
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
            engineering_failed = (
                completion.status == "failed"
                and isinstance(
                    completion.payload.get("engineering_disposition"),
                    Mapping,
                )
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
                    "stop_batch"
                    if engineering_failed
                    or member.ordinal == len(design.members)
                    else "continue_batch"
                ),
                negative_memory_id=memory_id,
                operation_id=operation_id,
            )
    if operation_id == prefix + "dispose-batch":
        return writer.dispose_batch(
            outcome=(
                "engineering_failure"
                if _engineering_failure_member(writer, design) is not None
                else "completed"
            ),
            operation_id=operation_id,
        )
    if operation_id == prefix + "close-study":
        engineering_failure = _engineering_failure_member(writer, design)
        if engineering_failure is not None:
            _failed_member, failed_completion = engineering_failure
            return writer.close_study(
                outcome="not_evaluable",
                kpi_completion_record_id=failed_completion.record_id,
                operation_id=operation_id,
            )
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
    *,
    _index: LocalIndexView | None = None,
) -> IndexRecord:
    operation_id = design.spec.operation_prefix + "close-study"
    index_context = (
        writer.open_stable_index()
        if _index is None
        else nullcontext((None, _index))
    )
    with index_context as (_control, index):
        operation = index.get("operation", operation_id)
        if operation is None or operation.status != "success":
            raise RuntimeError(
                f"operation is absent or unsuccessful: {operation_id}"
            )
        result = operation.payload.get("result")
        outcome = result.get("outcome") if isinstance(result, Mapping) else None
        if not isinstance(outcome, str):
            raise RuntimeError("replay Study-close operation outcome is absent")
        matches = tuple(
            record
            for record in index.records_by_subject_status(
                f"Study:{design.spec.study_id}",
                outcome,
            )
            if record.kind == "study-close"
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
    engineering_failure = _engineering_failure_member(writer, design)
    completion = _member_completion(writer, design, design.target_member)
    interpretation = _workflow_interpretation(writer, design)
    state = (
        None
        if completion is None
        else completion.payload.get("scientific", {}).get(
            "adjudication",
            {},
        ).get("state")
    )
    if engineering_failure is not None:
        rationale = (
            "A typed unrecovered Repair ended execution without creating "
            "scientific evidence; this is an engineering gap."
        )
        counterfactual = (
            "A same-protocol engineering Repair could make the exact family "
            "evaluable without changing its scientific semantics."
        )
        reopen_condition = (
            "Reopen through the exact same-protocol Repair lineage."
        )
    elif interpretation.all_criteria_recomputed:
        rationale = (
            "The exact concurrent family recomputed every original criterion; "
            f"the target scientific state is {state}."
        )
        counterfactual = (
            "New registered development material could change the family state "
            "without changing this historical replay result."
        )
        # This is a scientific continuation boundary, not an implementation
        # repair.  Reuse the condition preregistered on the exact replay axis
        # instead of inventing a contradictory diagnosis-time condition.
        reopen_condition = design.replay_axis.stop_or_reopen_condition
    else:
        unavailable = (
            interpretation.reason_code
            == "original_criterion_recomputation_unavailable"
        )
        rationale = (
            "The exact original criterion inventory was unavailable."
            if unavailable
            else "The exact original criterion inventory was not fully recomputed."
        )
        counterfactual = (
            "Registering the exact original criterion inventory and its required "
            "data could make the same frozen family evaluable."
            if unavailable
            else "Registering the exact missing criterion inputs could complete "
            "the same frozen-family evaluation."
        )
        reopen_condition = (
            "Reopen only when the exact original criterion inventory and its "
            "required registered data are available for the same frozen family."
            if unavailable
            else "Reopen only when the exact missing criterion inputs are "
            "registered for the same frozen family."
        )
    return StudyDiagnosis(
        study_id=design.spec.study_id,
        study_close_record_id=_study_close_record(writer, design).record_id,
        evidence_state=interpretation.diagnosis_state,
        confidence=(
            DiagnosisConfidence.HIGH
            if interpretation.all_criteria_recomputed
            else DiagnosisConfidence.LOW
        ),
        rationale=rationale,
        counterfactual=counterfactual,
        reopen_condition=reopen_condition,
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
    with writer.open_stable_index() as (_control, index):
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
    engineering_failure = _engineering_failure_member(writer, design)
    completion = _member_completion(writer, design, design.target_member)
    interpretation = _workflow_interpretation(writer, design)
    diagnosis = _diagnosis_record(writer, design)
    close_record = _study_close_record(writer, design)
    with writer.open_stable_index() as (_control, index):
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
        assert completion is not None
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
                (ReplayResumeConditionKind.SAME_PROTOCOL_REPAIR,)
                if engineering_failure is not None
                else (
                    ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL,
                    ReplayResumeConditionKind.SAME_PROTOCOL_REPAIR,
                )
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
    interpretation = _workflow_interpretation(writer, design)
    chosen_id = (
        "preserve-recomputed-replay"
        if interpretation.disposition is PortfolioAction.PRESERVE
        else "prune-recomputed-replay"
    )
    options = (
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
        )
    diagnosis = _diagnosis_record(writer, design)
    with writer.open_stable_index() as (_control, index):
        review_mode = _accepted_decision_review_mode(
            index,
            design.spec.operation_prefix + "disposition-decision",
        )
    return PortfolioDecision(
        decision_id=design.spec.decision_prefix + "-DISPOSITION",
        chosen_option_id=chosen_id,
        options=options,
        rationale=(
            "separate replay completion from scientific state and dispose honestly"
        ),
        commitment_batches=1,
        quant_team_review=None if review_mode is False else _quant_team_review(
            option_ids=tuple(option.option_id for option in options),
            chosen_option_id=chosen_id,
            basis_records=(
                DecisionBasisRecord(
                    kind="historical-replay-obligation",
                    record_id=design.spec.target_obligation_id,
                ),
                DecisionBasisRecord(
                    kind="portfolio-snapshot",
                    record_id=design.expanded_snapshot.identity,
                ),
                DecisionBasisRecord(
                    kind="study-diagnosis",
                    record_id=diagnosis.record_id,
                ),
            ),
            primary_lens=DecisionLens.CAUSALITY,
            primary_finding=(
                "the exact diagnosis separates scientific state from execution status"
            ),
            reservation_lens=DecisionLens.RISK,
            reservation_finding=(
                "disposing the bounded replay can leave adjacent uncertainty unresolved"
            ),
            claim_boundary=(
                "exact replay-axis disposition only; unrelated axes remain unchanged"
            ),
            resolution_basis=(
                "the completed diagnosis supports the exact preserve or prune boundary"
            ),
            disagreement_resolution=(
                "retain the typed reopen condition and independent forest branches"
            ),
        ),
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
    with writer.open_stable_index() as (control, index):
        candidate_records: list[IndexRecord] = []
        for executable_id in sorted(executable_ids):
            stream = f"candidate:{executable_id}"
            head = index.event_head(stream)
            if head is not None:
                head_record = index.get(head.record_kind, head.record_id)
                if head_record is None or head_record.event_stream != stream:
                    raise RuntimeError("replay candidate history projection drifted")
            executable_hash = executable_id.removeprefix("executable:")
            exact_candidates = tuple(
                record
                for record in index.records_by_fingerprint(executable_hash)
                if record.kind == "candidate"
                and (
                    record.record_id == executable_id
                    or record.subject == f"Executable:{executable_id}"
                )
            )
            if (
                head is not None
                and head.record_kind in {"candidate", "candidate-disposition"}
                and not exact_candidates
            ):
                raise RuntimeError("replay candidate history projection drifted")
            candidate_records.extend(exact_candidates)
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


def _require_scientific_study_close_projection(
    *,
    close_record: IndexRecord,
    completion: IndexRecord,
    study_kpi: IndexRecord | None,
    interpretation: ReplayInterpretation,
) -> None:
    """Verify a scientific close without converting deferral into failure."""

    if (
        close_record.status != interpretation.close_outcome
        or study_kpi is None
        or study_kpi.status != interpretation.close_outcome
        or study_kpi.payload.get("completion_record_id") != completion.record_id
    ):
        raise RuntimeError("replay scientific Study-close projection drifted")
    if interpretation.all_criteria_recomputed:
        return
    if (
        interpretation.close_outcome != "not_evaluable"
        or interpretation.diagnosis_state != EvidenceState.NOT_IDENTIFIABLE
        or interpretation.disposition != PortfolioAction.PRESERVE
        or interpretation.reason_code
        not in {
            "original_criterion_recomputation_incomplete",
            "original_criterion_recomputation_unavailable",
        }
    ):
        raise RuntimeError(
            "replay incomplete criteria lack the exact deferral boundary"
        )


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
    completions = tuple(
        _member_completion(writer, design, member) for member in design.members
    )
    engineering_failure = _engineering_failure_member(writer, design)
    with writer.open_stable_index() as (control, index):
        study_kpi = index.get("study-kpi", design.spec.study_id)
        heads = {
            obligation.identity: head
            for obligation, head in obligation_heads(
                index,
                mission_id=design.spec.mission_id,
            )
        }
    if (
        control is None
        or control.get("next_action", {}).get("kind") != "diagnose_study"
        or control.get("next_action", {}).get("study_close_record_id")
        != close_record.record_id
        or control.get("scientific", {}).get("active_study") is not None
        or control.get("scientific", {}).get("active_batch") is not None
        or control.get("scientific", {}).get("active_job") is not None
    ):
        raise RuntimeError("replay Study-close state drifted")
    if engineering_failure is None:
        if any(value is None for value in completions):
            raise RuntimeError("replay member completion is absent")
        for member, completion in zip(
            design.members,
            completions,
            strict=True,
        ):
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
        _require_scientific_study_close_projection(
            close_record=close_record,
            completion=target,
            study_kpi=study_kpi,
            interpretation=interpretation,
        )
    else:
        failed_member, failed_completion = engineering_failure
        for member, completion in zip(
            design.members,
            completions,
            strict=True,
        ):
            if member.ordinal < failed_member.ordinal:
                if completion is None or completion.status != "success":
                    raise RuntimeError(
                        "replay pre-gap member completion drifted"
                    )
            elif member.ordinal == failed_member.ordinal:
                if (
                    completion is None
                    or completion.record_id != failed_completion.record_id
                ):
                    raise RuntimeError(
                        "replay engineering-gap completion drifted"
                    )
            elif completion is not None:
                raise RuntimeError(
                    "replay executed work after terminal engineering gap"
                )
        disposed = _operation_result(
            writer,
            design.spec.operation_prefix + "dispose-batch",
        )
        if (
            disposed.get("outcome") != "engineering_failure"
            or close_record.status != "not_evaluable"
            or study_kpi is None
            or study_kpi.payload.get("completion_record_id")
            != failed_completion.record_id
            or study_kpi.payload.get("source")
            != "typed_engineering_failure_completion"
            or study_kpi.payload.get("unavailable_reason")
            != "engineering_failure"
        ):
            raise RuntimeError(
                "replay engineering gap lacks typed Batch, Study, or KPI terminal"
            )
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
        "batch_id": _operation_result(
            writer,
            design.spec.operation_prefix + "open-batch",
        )["batch_id"],
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
    expected_snapshot = _disposition_snapshot(writer, design)
    with writer.open_stable_index() as (control, index):
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
        constraints = scheduler_constraints(
            index,
            mission_id=design.spec.mission_id,
        )
        portfolio_head = index.event_head(
            f"portfolio:{design.spec.mission_id}"
        )
    expected_next_action = with_scheduler_constraints(
        {
            "kind": "choose_next_initiative_or_terminal",
            "mission_id": design.spec.mission_id,
        },
        constraints,
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
        or control.get("next_action") != expected_next_action
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
        with writer.open_stable_index() as (control, _index):
            if (
                control.get("revision") != study_close_revision
                or control.get("heads", {}).get("journal", {}).get("event_id")
                != study_close_event_id
                or control.get("next_action", {}).get("study_close_record_id")
                != _study_close_record(writer, design, _index=_index).record_id
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
    with writer.open_stable_index() as (final_control, _index):
        next_action = final_control["next_action"]
    return {
        "applied_step_count": end - initial,
        "candidate_created": False,
        "holdout_reveal_delta": 0,
        "initiative_id": design.spec.initiative_id,
        "mode": "diagnosed_replay_and_initiative_closed",
        "next_action": next_action,
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
    "FIXED_HOLD_REPLAY_BUDGET_POLICY_ID",
    "STUDY_CLOSE_STAGE",
    "FixedHoldReplayDesign",
    "FixedHoldReplayMember",
    "FixedHoldReplayMissionSpec",
    "ReplayAuthorityBoundary",
    "ReplayInterpretation",
    "build_fixed_hold_replay_design",
    "build_replay_job_spec",
    "activate_current_scientific_protocol",
    "fixed_hold_replay_batch_budget",
    "fixed_hold_replay_job_budget",
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
