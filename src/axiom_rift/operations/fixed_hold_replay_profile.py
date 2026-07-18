"""Fail-closed production bindings for replay profiles."""

from __future__ import annotations

from axiom_rift.operations.fixed_hold_replay_workflow import (
    FIXED_HOLD_REPLAY_RESOLUTION_EVENT_KINDS,
    FixedHoldReplayDesign,
    ReplayAxisAdmission,
    ReplayInitiativeLifecycle,
    fixed_hold_replay_post_study_steps,
    fixed_hold_replay_study_input_hash,
)
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.portfolio import PortfolioAction
from axiom_rift.research.semantic_question import SemanticQuestionCore


_FORBIDDEN_BORROWED_EVENTS = frozenset(
    {
        "initiative_opened",
        "initiative_closed",
    }
)
_FORBIDDEN_BORROWED_SUFFIXES = (
    "disposition-decision",
    "disposition-snapshot",
)


def require_borrowed_production_profile(
    writer: StateWriter,
    design: FixedHoldReplayDesign,
) -> FixedHoldReplayDesign:
    """Prove lifecycle, lineage, hashes, and terminal ownership contract."""

    if (
        design.spec.initiative_lifecycle
        is not ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE
    ):
        raise RuntimeError("production replay profile must borrow its Initiative")
    lineage = design.semantic_question_lineage
    question_core = SemanticQuestionCore.from_question_manifest(design.question)
    if (
        lineage is None
        or lineage.successor_study_id != design.spec.study_id
        or lineage.successor_core_id != question_core.identity
    ):
        raise RuntimeError("production replay profile lacks exact semantic lineage")
    study_hash = fixed_hold_replay_study_input_hash(writer, design)
    if design.batch_spec.study_hash != study_hash:
        raise RuntimeError("production replay Study, Batch, and permit hashes differ")
    admission = design.spec.axis_admission
    axis_count_before = len(design.prior_axes)
    axis_count_after = len(design.expanded_snapshot.axes)
    if admission is ReplayAxisAdmission.ADD_NEW_MECHANISM:
        if (
            design.bridge_decision is None
            or design.bridge_decision.chosen.action
            is not PortfolioAction.NEW_MECHANISM
            or design.bridge_decision.baseline_executable is not None
            or design.bridge_decision.proposed_axis != design.replay_axis
            or design.protocol_revision is not None
            or axis_count_after != axis_count_before + 1
        ):
            raise RuntimeError("new-mechanism replay admission is malformed")
    elif admission is ReplayAxisAdmission.REVISE_PROTOCOL:
        if (
            design.bridge_decision is None
            or design.bridge_decision.chosen.action.value != "revise_protocol"
            or design.bridge_decision.protocol_revision
            != design.protocol_revision
            or axis_count_after != axis_count_before
            or design.replay_axis.axis_id
            != design.spec.bridge_axis_id
        ):
            raise RuntimeError("protocol-revision replay admission is malformed")
    elif admission is ReplayAxisAdmission.REUSE_EXACT_AXIS:
        matches = tuple(
            axis
            for axis in design.prior_axes
            if axis.axis_id == design.replay_axis.axis_id
        )
        if (
            design.bridge_decision is not None
            or design.protocol_revision is not None
            or axis_count_after != axis_count_before
            or len(matches) != 1
            or matches[0] != design.replay_axis
            or design.expanded_snapshot.identity != design.base_snapshot_id
        ):
            raise RuntimeError("exact-axis replay admission is malformed")
    else:
        raise RuntimeError("production replay axis admission is untyped")
    terminal_contracts = tuple(
        fixed_hold_replay_post_study_steps(
            design,
            resolution_event_kind=event_kind,
            architecture_review_triggered=architecture_review_triggered,
        )
        for event_kind in FIXED_HOLD_REPLAY_RESOLUTION_EVENT_KINDS
        for architecture_review_triggered in (False, True)
    )
    if any(
        any(
            step.event_kind in _FORBIDDEN_BORROWED_EVENTS
            for step in steps
        )
        or any(
            step.operation_id
            == design.spec.operation_prefix + suffix
            for step in steps
            for suffix in _FORBIDDEN_BORROWED_SUFFIXES
        )
        or sum(
            step.operation_id
            == design.spec.operation_prefix + "resolve-replay"
            for step in steps
        )
        != 1
        for steps in terminal_contracts
    ):
        raise RuntimeError(
            "borrowed production replay operation plan owns Initiative state"
        )
    return design


__all__ = ["require_borrowed_production_profile"]
