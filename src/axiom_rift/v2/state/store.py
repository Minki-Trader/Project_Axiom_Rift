"""Single-file compare-and-swap control state."""

from __future__ import annotations

import copy
import os
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import yaml

from axiom_rift.v2.identity import ObjectStore
from axiom_rift.v2.state.transitions import TERMINAL_OUTCOMES, TransitionError, validate_claim_for_stage


class ControlStateError(RuntimeError):
    """Raised when V2 control state cannot be read or committed safely."""


def validate_control_state(state: dict[str, Any]) -> None:
    if state.get("schema") != "axiom_rift_v2_control_state_v1":
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
    if not isinstance(cursor.get("exact_next_action"), str):
        raise ControlStateError("cursor requires one exact next action")
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

    def commit(
        self,
        expected_revision: int,
        idempotency_key: str,
        mutation: Callable[[dict[str, Any]], dict[str, Any] | None],
        referenced_object_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        lock = self.path.with_suffix(".lock")
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
            draft["applied_idempotency_keys"] = keys[-100:]
            validate_control_state(draft)
            text = yaml.safe_dump(draft, sort_keys=False, allow_unicode=False)
            text.encode("ascii")
            with temp.open("x", encoding="ascii", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            self.replace_func(temp, self.path)
            return self.load()
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            if isinstance(exc, ControlStateError):
                raise
            raise ControlStateError(f"control-state commit failed: {exc}") from exc
        finally:
            temp.unlink(missing_ok=True)
            lock.unlink(missing_ok=True)
