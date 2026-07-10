"""H/S/R/P/M, identity, and compact control-state transition rules."""

from __future__ import annotations

import re
from typing import Any, Iterable


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
    "idle": "none",
    "bootstrap": "none",
    "H": "none",
    "S": "diagnostic_observation",
    "R": "research_candidate",
    "P": "selected",
    "M": "pre_live_ready",
}
STAGE_TRANSITIONS = {
    "idle": {"H"},
    "bootstrap": {"H"},
    "H": {"S"},
    "S": {"H", "R"},
    "R": {"H", "P"},
    "P": {"H", "M"},
    "M": set(),
}
ROOT_TERMINAL_OUTCOMES = frozenset({
    "completed_pre_live_handoff",
    "closed_no_candidate",
    "blocked_external",
    "stopped_by_user",
})
INTERNAL_GOAL_TERMINAL_OUTCOMES = frozenset({
    "completed_internal_goal",
    "closed_no_candidate",
    "blocked_internal",
    "stopped_internal",
})
INTERNAL_TO_ROOT_OUTCOME = {
    "completed_internal_goal": "completed_pre_live_handoff",
    "closed_no_candidate": "closed_no_candidate",
    "blocked_internal": "blocked_external",
    "stopped_internal": "stopped_by_user",
}
TERMINAL_OUTCOMES = ROOT_TERMINAL_OUTCOMES

IDENTITY_SPECS = {
    "goal": ("V2G", "next_goal"),
    "hypothesis": ("V2H", "next_hypothesis"),
    "scout": ("V2S", "next_scout"),
    "confirmation": ("V2R", "next_confirmation"),
    "promotion": ("V2P", "next_promotion"),
    "materialization": ("V2M", "next_materialization"),
}

STAGE_IDENTITY_KINDS = {
    "H": "hypothesis",
    "S": "scout",
    "R": "confirmation",
    "P": "promotion",
    "M": "materialization",
}

NEXT_ACTION_KINDS = {
    "none",
    "open_goal",
    "preregister_hypothesis",
    "open_stage",
    "declare_job",
    "run_job",
    "resume_job",
    "record_evidence",
    "close_goal",
    "close_root_mission",
    "validate_root_closeout",
    "verify_git_closeout",
    "repair",
}

NEXT_ACTION_FIELDS = {
    "kind",
    "goal_id",
    "stage",
    "subject_id",
    "job_kind",
    "prerequisite_receipt_ids",
    "summary",
    "mission_id",
    "terminal_outcome",
    "basis_evidence_id",
}

ACTIVE_JOB_STATUSES = {
    "declared",
    "running",
    "completed_pending_record",
    "failed",
    "timed_out",
}


class TransitionError(RuntimeError):
    """Raised when stage or claim progression is invalid."""


def format_identity(kind: str, counter: int) -> str:
    spec = IDENTITY_SPECS.get(kind)
    if spec is None:
        raise TransitionError(f"unknown identity kind: {kind}")
    if not isinstance(counter, int) or isinstance(counter, bool) or counter < 1 or counter > 9999:
        raise TransitionError(f"invalid {kind} counter: {counter}")
    return f"{spec[0]}{counter:04d}"


def namespace_key(kind: str) -> str:
    spec = IDENTITY_SPECS.get(kind)
    if spec is None:
        raise TransitionError(f"unknown identity kind: {kind}")
    return spec[1]


def validate_identity(kind: str, value: str, expected_counter: int | None = None) -> None:
    prefix, _key = IDENTITY_SPECS.get(kind, (None, None))
    if prefix is None or not isinstance(value, str) or re.fullmatch(rf"{prefix}[0-9]{{4}}", value) is None:
        raise TransitionError(f"invalid {kind} identity: {value}")
    if expected_counter is not None and value != format_identity(kind, expected_counter):
        raise TransitionError(
            f"{kind} identity does not match namespace: expected "
            f"{format_identity(kind, expected_counter)}, observed {value}"
        )


def identity_kind_for_stage(stage: str) -> str:
    kind = STAGE_IDENTITY_KINDS.get(stage)
    if kind is None:
        raise TransitionError(f"stage does not allocate an identity: {stage}")
    return kind


def make_next_action(
    kind: str,
    *,
    goal_id: str | None = None,
    stage: str | None = None,
    subject_id: str | None = None,
    job_kind: str | None = None,
    prerequisite_receipt_ids: Iterable[str] = (),
    summary: str | None = None,
    mission_id: str | None = None,
    terminal_outcome: str | None = None,
    basis_evidence_id: str | None = None,
) -> dict[str, Any]:
    action = {
        "kind": kind,
        "goal_id": goal_id,
        "stage": stage,
        "subject_id": subject_id,
        "job_kind": job_kind,
        "prerequisite_receipt_ids": list(dict.fromkeys(prerequisite_receipt_ids)),
        "summary": summary,
        "mission_id": mission_id,
        "terminal_outcome": terminal_outcome,
        "basis_evidence_id": basis_evidence_id,
    }
    validate_next_action(action)
    return action


def validate_next_action(action: Any) -> None:
    if not isinstance(action, dict):
        raise TransitionError("next_action must be a mapping")
    unknown = set(action) - NEXT_ACTION_FIELDS
    if unknown:
        raise TransitionError("next_action has unsupported fields: " + ", ".join(sorted(unknown)))
    kind = action.get("kind")
    if kind not in NEXT_ACTION_KINDS:
        raise TransitionError(f"invalid next_action kind: {kind}")
    for field in (
        "goal_id",
        "stage",
        "subject_id",
        "job_kind",
        "summary",
        "mission_id",
        "terminal_outcome",
        "basis_evidence_id",
    ):
        value = action.get(field)
        if value is not None and not isinstance(value, str):
            raise TransitionError(f"next_action.{field} must be a string or null")
    prerequisites = action.get("prerequisite_receipt_ids", [])
    if not isinstance(prerequisites, list) or not all(isinstance(item, str) and item for item in prerequisites):
        raise TransitionError("next_action.prerequisite_receipt_ids must be a string list")
    goal_id = action.get("goal_id")
    if goal_id is not None:
        validate_identity("goal", goal_id)
    stage = action.get("stage")
    if stage is not None and stage not in STAGE_IDENTITY_KINDS:
        raise TransitionError(f"invalid next_action stage: {stage}")
    subject_id = action.get("subject_id")
    if stage is not None and subject_id is not None:
        validate_identity(identity_kind_for_stage(stage), subject_id)
    if kind == "none" and any(action.get(field) is not None for field in ("goal_id", "stage", "subject_id", "job_kind")):
        raise TransitionError("next_action none may not name a goal, stage, subject, or job")
    if kind in {"preregister_hypothesis", "open_stage", "declare_job", "run_job", "resume_job", "record_evidence", "close_goal"}:
        if goal_id is None:
            raise TransitionError(f"next_action {kind} requires goal_id")
    if kind == "open_stage" and (stage is None or subject_id is None):
        raise TransitionError("next_action open_stage requires stage and subject_id")
    if kind in {"declare_job", "run_job", "resume_job"} and not action.get("job_kind"):
        raise TransitionError(f"next_action {kind} requires job_kind")
    root_fields = (
        action.get("mission_id"),
        action.get("terminal_outcome"),
        action.get("basis_evidence_id"),
    )
    if kind == "close_root_mission":
        mission_id, terminal_outcome, basis_evidence_id = root_fields
        if not isinstance(mission_id, str) or re.fullmatch(r"AXIOM_ROOT_[0-9]{4}", mission_id) is None:
            raise TransitionError("next_action close_root_mission requires mission_id")
        if terminal_outcome not in ROOT_TERMINAL_OUTCOMES:
            raise TransitionError("next_action close_root_mission requires a root terminal outcome")
        if not isinstance(basis_evidence_id, str) or not basis_evidence_id:
            raise TransitionError("next_action close_root_mission requires basis_evidence_id")
        if any(action.get(field) is not None for field in ("goal_id", "stage", "subject_id", "job_kind")):
            raise TransitionError("next_action close_root_mission may not name goal, stage, subject, or job")
        if basis_evidence_id not in prerequisites:
            raise TransitionError("root closeout basis must be a prerequisite receipt")
    elif any(value is not None for value in root_fields):
        raise TransitionError("root closeout fields are exclusive to close_root_mission")


def validate_active_job(job: Any) -> None:
    if job is None:
        return
    if not isinstance(job, dict):
        raise TransitionError("active_job must be a mapping or null")
    required = (
        "job_id",
        "goal_id",
        "stage_id",
        "kind",
        "command",
        "status",
        "spec_object_id",
        "input_hash",
        "timeout_seconds",
        "output_path",
        "expected_artifacts",
        "log_path",
        "declared_at_utc",
        "resume_action",
    )
    missing = [field for field in required if job.get(field) in (None, "")]
    if missing:
        raise TransitionError("active_job missing fields: " + ", ".join(missing))
    validate_identity("goal", str(job["goal_id"]))
    if job.get("status") not in ACTIVE_JOB_STATUSES:
        raise TransitionError(f"invalid active_job status: {job.get('status')}")
    for field in (
        "job_id",
        "stage_id",
        "kind",
        "command",
        "output_path",
        "log_path",
        "declared_at_utc",
        "resume_action",
    ):
        if not isinstance(job.get(field), str) or not job[field]:
            raise TransitionError(f"active_job.{field} must be a nonempty string")
    expected_artifacts = job.get("expected_artifacts")
    if not isinstance(expected_artifacts, list) or not expected_artifacts or not all(
        isinstance(item, str) and item for item in expected_artifacts
    ):
        raise TransitionError("active_job.expected_artifacts must be a nonempty string list")
    for artifact in expected_artifacts:
        normalized = artifact.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise TransitionError("active_job.expected_artifacts must stay repository-relative")
    if not isinstance(job.get("timeout_seconds"), int) or isinstance(job.get("timeout_seconds"), bool) or job["timeout_seconds"] < 1:
        raise TransitionError("active_job.timeout_seconds must be a positive integer")
    for field in ("spec_object_id", "input_hash"):
        value = job.get(field)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise TransitionError(f"active_job.{field} must be a lowercase sha256")
    if job.get("status") == "running" and job.get("started_at_utc") in (None, ""):
        raise TransitionError("running active_job requires started_at_utc")


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
    validate_identity(identity_kind_for_stage(new_stage), stage_id)
    updated = dict(cursor)
    updated.update({"stage": new_stage, "stage_id": stage_id, "stage_status": "in_progress"})
    return updated
