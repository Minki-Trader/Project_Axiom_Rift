"""Single-file compare-and-swap control state."""

from __future__ import annotations

import copy
import os
import re
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import yaml

from axiom_rift.v2.identity import ObjectStore
from axiom_rift.v2.state.transitions import (
    IDENTITY_SPECS,
    ROOT_TERMINAL_OUTCOMES,
    STAGE_IDENTITY_KINDS,
    TERMINAL_OUTCOMES,
    TransitionError,
    identity_kind_for_stage,
    validate_active_job,
    validate_claim_for_stage,
    validate_identity,
    validate_next_action,
)


class ControlStateError(RuntimeError):
    """Raised when V2 control state cannot be read or committed safely."""


CONTROL_STATE_SCHEMA_V1 = "axiom_rift_v2_control_state_v1"
CONTROL_STATE_SCHEMA_V2 = "axiom_rift_v2_control_state_v2"
RECENT_CLOSED_GOAL_LIMIT = 8
APPLIED_IDEMPOTENCY_KEY_LIMIT = 100
CLOSED_GOAL_HISTORY_OUTCOMES = TERMINAL_OUTCOMES | {"completed_v2_activation"}


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _validate_root_mission(root_mission: Any) -> None:
    if not isinstance(root_mission, dict):
        raise ControlStateError("schema v2 requires root_mission")
    for field in ("mission_id", "contract_path", "contract_sha256", "status"):
        if not isinstance(root_mission.get(field), str) or not root_mission[field]:
            raise ControlStateError(f"root_mission.{field} is required")
    if re.fullmatch(r"AXIOM_ROOT_[0-9]{4}", root_mission["mission_id"]) is None:
        raise ControlStateError("root_mission.mission_id is invalid")
    if not _is_sha256(root_mission.get("contract_sha256")):
        raise ControlStateError("root_mission.contract_sha256 must be a lowercase sha256")
    if root_mission.get("status") not in {"ready", "active", "terminal"}:
        raise ControlStateError("root_mission.status is invalid")
    terminal = root_mission.get("terminal_outcome")
    if terminal is not None and terminal not in ROOT_TERMINAL_OUTCOMES:
        raise ControlStateError(f"invalid root terminal outcome: {terminal}")
    if (terminal is None) != (root_mission.get("status") != "terminal"):
        raise ControlStateError("root terminal outcome and terminal status must be set together")


def _validate_mission_budget(mission_budget: Any) -> None:
    if not isinstance(mission_budget, dict):
        raise ControlStateError("schema v2 requires mission_budget")
    if not isinstance(mission_budget.get("frozen"), bool):
        raise ControlStateError("mission_budget.frozen must be boolean")
    limits = mission_budget.get("limits")
    remaining = mission_budget.get("remaining")
    if not isinstance(limits, dict) or not isinstance(remaining, dict) or set(limits) != set(remaining):
        raise ControlStateError("mission_budget limits and remaining keys must match")
    for key, limit in limits.items():
        observed = remaining.get(key)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 0
            or not isinstance(observed, int)
            or isinstance(observed, bool)
            or observed < 0
            or observed > limit
        ):
            raise ControlStateError(f"invalid mission budget counter: {key}")


def _validate_slice_budget(slice_budget: Any) -> None:
    if slice_budget is None:
        return
    if not isinstance(slice_budget, dict) or not isinstance(slice_budget.get("slice_id"), str):
        raise ControlStateError("slice_budget must be null or a named mapping")
    for key in (
        "implementation_remaining",
        "validation_remaining",
        "repair_remaining",
        "recheck_remaining",
    ):
        value = slice_budget.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value not in {0, 1}:
            raise ControlStateError(f"slice_budget.{key} must be zero or one")
    if slice_budget.get("identical_retry_allowed") is not False:
        raise ControlStateError("slice_budget identical retry must remain disabled")
    if slice_budget.get("automatic_timeout_extension_allowed") is not False:
        raise ControlStateError("slice_budget timeout extension must remain disabled")


def _validate_v2_namespace(namespace: Any) -> None:
    if not isinstance(namespace, dict):
        raise ControlStateError("schema v2 requires namespace counters")
    for _kind, (_prefix, key) in IDENTITY_SPECS.items():
        value = namespace.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 9999:
            raise ControlStateError(f"namespace.{key} must be an integer from 1 to 9999")


def _validate_v2_cursor(cursor: dict[str, Any]) -> None:
    stage = str(cursor.get("stage"))
    active_goal_id = cursor.get("active_goal_id")
    active_hypothesis_id = cursor.get("active_hypothesis_id")
    if active_goal_id is not None:
        try:
            validate_identity("goal", active_goal_id)
        except TransitionError as exc:
            raise ControlStateError(str(exc)) from exc
    if active_hypothesis_id is not None:
        try:
            validate_identity("hypothesis", active_hypothesis_id)
        except TransitionError as exc:
            raise ControlStateError(str(exc)) from exc
        if active_goal_id is None:
            raise ControlStateError("active hypothesis requires an active goal")
    if stage == "idle":
        if cursor.get("stage_id") is not None:
            raise ControlStateError("idle cursor may not retain stage_id")
        if active_hypothesis_id is not None:
            raise ControlStateError("idle cursor may not retain active_hypothesis_id")
    elif stage in STAGE_IDENTITY_KINDS:
        stage_id = cursor.get("stage_id")
        try:
            validate_identity(identity_kind_for_stage(stage), stage_id)
        except TransitionError as exc:
            raise ControlStateError(str(exc)) from exc
    elif stage != "bootstrap":
        raise ControlStateError(f"unknown stage: {stage}")
    try:
        validate_next_action(cursor.get("next_action"))
    except TransitionError as exc:
        raise ControlStateError(str(exc)) from exc


def _validate_v2_history(history: Any) -> None:
    if not isinstance(history, dict):
        raise ControlStateError("schema v2 requires bounded history")
    recent = history.get("recent_closed_goals", [])
    if not isinstance(recent, list):
        raise ControlStateError("history.recent_closed_goals must be a list")
    if len(recent) > RECENT_CLOSED_GOAL_LIMIT:
        raise ControlStateError(
            f"history.recent_closed_goals exceeds {RECENT_CLOSED_GOAL_LIMIT} entries"
        )
    for item in recent:
        if not isinstance(item, dict):
            raise ControlStateError("closed-goal history item must be a mapping")
        try:
            validate_identity("goal", item.get("goal_id"))
        except TransitionError as exc:
            raise ControlStateError(str(exc)) from exc
        if item.get("outcome") not in CLOSED_GOAL_HISTORY_OUTCOMES:
            raise ControlStateError("closed-goal history outcome is invalid")
        if not _is_sha256(item.get("summary_object_id")):
            raise ControlStateError("closed-goal history requires summary_object_id")


def _validate_holdout_state(holdout: Any) -> None:
    if not isinstance(holdout, dict):
        raise ControlStateError("schema v2 requires holdout state")
    reveal_count = holdout.get("reveal_count")
    max_reveals = holdout.get("max_reveals")
    if not isinstance(reveal_count, int) or isinstance(reveal_count, bool) or reveal_count < 0:
        raise ControlStateError("holdout.reveal_count must be a nonnegative integer")
    if not isinstance(max_reveals, int) or isinstance(max_reveals, bool) or max_reveals != 1:
        raise ControlStateError("holdout.max_reveals must remain one")
    if reveal_count > max_reveals:
        raise ControlStateError("holdout reveal count exceeds permit")
    permit = holdout.get("permit")
    if permit is not None:
        if not isinstance(permit, dict):
            raise ControlStateError("holdout.permit must be a mapping or null")
        for field in (
            "permit_id",
            "permit_object_id",
            "candidate_id",
            "frozen_identity_bundle_sha256",
            "p_gate_receipt_id",
            "trial_accounting_receipt_id",
        ):
            if not isinstance(permit.get(field), str) or not permit[field]:
                raise ControlStateError(f"holdout.permit.{field} is required")
        if not _is_sha256(permit.get("permit_object_id")) or not _is_sha256(
            permit.get("frozen_identity_bundle_sha256")
        ):
            raise ControlStateError("holdout permit hashes are invalid")


def validate_control_state(state: dict[str, Any]) -> None:
    schema = state.get("schema")
    if schema not in {CONTROL_STATE_SCHEMA_V1, CONTROL_STATE_SCHEMA_V2}:
        raise ControlStateError("control state schema mismatch")
    revision = state.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise ControlStateError("control state revision must be a positive integer")
    cursor = state.get("cursor")
    claim = state.get("claim")
    if not isinstance(cursor, dict) or not isinstance(claim, dict):
        raise ControlStateError("cursor and claim mappings are required")
    stage = str(cursor.get("stage"))
    level = str(claim.get("current_level"))
    try:
        validate_claim_for_stage(stage, level)
    except TransitionError as exc:
        raise ControlStateError(str(exc)) from exc
    terminal = cursor.get("terminal_outcome")
    if terminal is not None and terminal not in TERMINAL_OUTCOMES:
        raise ControlStateError(f"invalid terminal outcome: {terminal}")
    if schema == CONTROL_STATE_SCHEMA_V1:
        if not isinstance(cursor.get("exact_next_action"), str):
            raise ControlStateError("cursor requires one exact next action")
    else:
        _validate_root_mission(state.get("root_mission"))
        _validate_mission_budget(state.get("mission_budget"))
        _validate_slice_budget(state.get("slice_budget"))
        _validate_v2_namespace(state.get("namespace"))
        _validate_v2_cursor(cursor)
        reentry = state.get("reentry")
        if not isinstance(reentry, dict):
            raise ControlStateError("schema v2 requires reentry")
        try:
            validate_active_job(reentry.get("active_job"))
        except TransitionError as exc:
            raise ControlStateError(str(exc)) from exc
        _validate_v2_history(state.get("history"))
        _validate_holdout_state(state.get("holdout"))
        root_terminal = state["root_mission"].get("terminal_outcome")
        if root_terminal is not None:
            if cursor.get("active_goal_id") is not None or reentry.get("active_job") is not None:
                raise ControlStateError("terminal root mission may not retain active goal or job")
            if cursor["next_action"].get("kind") != "none":
                raise ControlStateError("terminal root mission requires next_action none")
        applied = state.get("applied_idempotency_keys", [])
        if not isinstance(applied, list) or not all(isinstance(item, str) and item for item in applied):
            raise ControlStateError("applied_idempotency_keys must be a string list")
        if len(applied) > APPLIED_IDEMPOTENCY_KEY_LIMIT:
            raise ControlStateError("applied_idempotency_keys exceeds bounded history")
    if _contains_forbidden_live_ready(state):
        raise ControlStateError("live_ready is outside the V2 control-state schema")


def _contains_forbidden_live_ready(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key == "live_ready" or _contains_forbidden_live_ready(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden_live_ready(item) for item in value)
    return value == "live_ready"


class ControlStore:
    """Atomic single-state store with bounded lock and revision CAS."""

    def __init__(
        self,
        path: Path,
        *,
        object_store: ObjectStore | None = None,
        replace_func: Callable[[Path, Path], None] | None = None,
    ) -> None:
        self.path = path.resolve()
        self.object_store = object_store
        self.replace_func = replace_func or (lambda source, target: os.replace(source, target))

    def load(self) -> dict[str, Any]:
        try:
            text = self.path.read_text(encoding="ascii")
            state = yaml.safe_load(text)
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ControlStateError(f"cannot load control state: {exc}") from exc
        if not isinstance(state, dict):
            raise ControlStateError("control state must be a YAML mapping")
        validate_control_state(state)
        return state

    @property
    def recovery_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".recovery")

    def load_recovery(self) -> dict[str, Any] | None:
        path = self.recovery_path
        if not path.exists():
            return None
        try:
            state = yaml.safe_load(path.read_text(encoding="ascii"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ControlStateError(f"cannot load pending control recovery: {exc}") from exc
        if not isinstance(state, dict):
            raise ControlStateError("pending control recovery must be a mapping")
        validate_control_state(state)
        return state

    def apply_recovery(self) -> dict[str, Any]:
        candidate = self.load_recovery()
        if candidate is None:
            raise ControlStateError("no pending control recovery exists")
        current = self.load()
        if candidate.get("revision") != current.get("revision") + 1:
            raise ControlStateError("pending control recovery revision does not extend current state")
        os.replace(self.recovery_path, self.path)
        return self.load()

    def commit(
        self,
        expected_revision: int,
        idempotency_key: str,
        mutation: Callable[[dict[str, Any]], dict[str, Any] | None],
        referenced_object_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        lock = self.path.with_suffix(".lock")
        if self.recovery_path.exists():
            raise ControlStateError("pending control recovery must be reconciled before mutation")
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise ControlStateError(f"control-state lock exists: {lock}") from exc
        os.close(descriptor)
        temp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            current = self.load()
            applied = current.get("applied_idempotency_keys", [])
            if idempotency_key in applied:
                return current
            if current["revision"] != expected_revision:
                raise ControlStateError(
                    f"revision conflict: expected {expected_revision}, actual {current['revision']}"
                )
            if self.object_store is not None:
                for object_id in referenced_object_ids:
                    self.object_store.get(object_id)
            draft = copy.deepcopy(current)
            result = mutation(draft)
            if result is not None:
                draft = result
            if not isinstance(draft, dict):
                raise ControlStateError("state mutation must produce a mapping")
            draft["revision"] = expected_revision + 1
            keys = list(draft.get("applied_idempotency_keys", []))
            keys.append(idempotency_key)
            draft["applied_idempotency_keys"] = keys[-APPLIED_IDEMPOTENCY_KEY_LIMIT:]
            validate_control_state(draft)
            text = yaml.safe_dump(draft, sort_keys=False, allow_unicode=False)
            text.encode("ascii")
            with temp.open("x", encoding="ascii", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                self.replace_func(temp, self.path)
            except OSError:
                if temp.exists():
                    os.replace(temp, self.recovery_path)
                raise
            return self.load()
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            if isinstance(exc, ControlStateError):
                raise
            raise ControlStateError(f"control-state commit failed: {exc}") from exc
        finally:
            temp.unlink(missing_ok=True)
            lock.unlink(missing_ok=True)
