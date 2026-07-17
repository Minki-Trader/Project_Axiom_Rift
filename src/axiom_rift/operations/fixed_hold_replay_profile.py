"""Fail-closed production bindings for replay profiles."""

from __future__ import annotations

from axiom_rift.operations.fixed_hold_replay_workflow import (
    FixedHoldReplayDesign,
    ReplayAxisAdmission,
    ReplayInitiativeLifecycle,
    fixed_hold_replay_study_input_hash,
    operation_steps,
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
    """Prove lifecycle, lineage, hashes, and the executable operation plan."""

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
        new_axis_action = design.spec.resolved_new_axis_action
        if (
            design.bridge_decision is None
            or new_axis_action is None
            or design.bridge_decision.chosen.action
            is not new_axis_action
            or new_axis_action
            not in {
                PortfolioAction.COMPLEMENTARY_SLEEVE,
                PortfolioAction.CONTRAST,
                PortfolioAction.NEW_MECHANISM,
                PortfolioAction.RECOMBINE,
                PortfolioAction.ROTATE,
                PortfolioAction.SYNTHESIZE,
            }
            or (
                new_axis_action is not PortfolioAction.NEW_MECHANISM
                and design.bridge_decision.baseline_executable is None
            )
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
    steps = operation_steps(writer, design)
    if (
        any(step.event_kind in _FORBIDDEN_BORROWED_EVENTS for step in steps)
        or any(
            step.operation_id
            == design.spec.operation_prefix + suffix
            for step in steps
            for suffix in _FORBIDDEN_BORROWED_SUFFIXES
        )
        or sum(
            step.operation_id == design.spec.operation_prefix + "resolve-replay"
            for step in steps
        )
        != 1
    ):
        raise RuntimeError("borrowed production replay operation plan owns Initiative state")
    return design


__all__ = ["require_borrowed_production_profile"]
