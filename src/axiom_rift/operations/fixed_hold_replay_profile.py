"""Fail-closed production bindings for replay profiles."""

from __future__ import annotations

from axiom_rift.operations.fixed_hold_replay_workflow import (
    FixedHoldReplayDesign,
    ReplayInitiativeLifecycle,
    fixed_hold_replay_study_input_hash,
    operation_steps,
)
from axiom_rift.operations.writer import StateWriter
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
