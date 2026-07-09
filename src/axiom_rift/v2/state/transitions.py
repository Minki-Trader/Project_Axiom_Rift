"""H/S/R/P/M and scalar claim transition rules."""

from __future__ import annotations

from typing import Any


CLAIM_LEVELS = (
    "none",
    "diagnostic_observation",
    "research_candidate",
    "robustness_candidate",
    "economics_pass",
    "selected",
    "onnx_ready",
    "materialization_ready",
    "pre_live_ready",
)
STAGE_CEILINGS = {
    "bootstrap": "none",
    "H": "none",
    "S": "diagnostic_observation",
    "R": "research_candidate",
    "P": "selected",
    "M": "pre_live_ready",
}
STAGE_TRANSITIONS = {
    "bootstrap": {"H"},
    "H": {"S"},
    "S": {"H", "R"},
    "R": {"H", "P"},
    "P": {"H", "M"},
    "M": set(),
}
TERMINAL_OUTCOMES = {
    "completed_pre_live_handoff",
    "closed_no_candidate",
    "blocked_external",
    "stopped_by_user",
}


class TransitionError(RuntimeError):
    """Raised when stage or claim progression is invalid."""


def claim_index(level: str) -> int:
    try:
        return CLAIM_LEVELS.index(level)
    except ValueError as exc:
        raise TransitionError(f"unknown claim level: {level}") from exc


def validate_claim_for_stage(stage: str, level: str) -> None:
    if stage not in STAGE_CEILINGS:
        raise TransitionError(f"unknown stage: {stage}")
    if claim_index(level) > claim_index(STAGE_CEILINGS[stage]):
        raise TransitionError(f"claim {level} exceeds stage {stage} ceiling")


def promote_claim(claim: dict[str, Any], new_level: str, basis_receipt_ids: list[str]) -> dict[str, Any]:
    current = str(claim.get("current_level"))
    if claim_index(new_level) != claim_index(current) + 1:
        raise TransitionError(f"claim transition must advance one level: {current} -> {new_level}")
    if not basis_receipt_ids:
        raise TransitionError("claim promotion requires receipt IDs")
    updated = dict(claim)
    updated["current_level"] = new_level
    updated["basis_receipt_ids"] = list(dict.fromkeys(basis_receipt_ids))
    return updated


def transition_stage(cursor: dict[str, Any], new_stage: str, stage_id: str) -> dict[str, Any]:
    current = str(cursor.get("stage"))
    if new_stage not in STAGE_TRANSITIONS.get(current, set()):
        raise TransitionError(f"stage transition is not allowed: {current} -> {new_stage}")
    updated = dict(cursor)
    updated.update({"stage": new_stage, "stage_id": stage_id, "stage_status": "in_progress"})
    return updated
