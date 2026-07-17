"""Exact Initiative ownership for bounded replay workflows."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

from axiom_rift.storage.index import LocalIndexView


_INITIATIVE_TERMINAL_STATUSES = (
    "blocked_external",
    "completed",
    "continued_handoff",
    "engineering_fixture_complete",
    "no_action",
    "superseded",
)


class ReplayInitiativeLifecycle(str, Enum):
    """Declare whether replay owns or temporarily borrows an Initiative."""

    OWN_BOUNDED_INITIATIVE = "own_bounded_initiative"
    BORROW_ACTIVE_INITIATIVE = "borrow_active_initiative"


class ReplayInitiativeBindingPhase(str, Enum):
    """Separate strict execution authority from later historical recovery."""

    EXECUTION = "execution"
    TERMINAL_HANDOFF = "terminal_handoff"


def _successful_operation(
    index: LocalIndexView,
    operation_id: str,
    event_kinds: str | frozenset[str],
) -> Any | None:
    record = index.get("operation", operation_id)
    if record is None:
        return None
    allowed = (
        frozenset((event_kinds,))
        if isinstance(event_kinds, str)
        else event_kinds
    )
    if (
        record.status != "success"
        or record.payload.get("event_kind") not in allowed
    ):
        raise RuntimeError("replay Initiative lifecycle operation is malformed")
    return record


def _initiative_authorization(
    control: Mapping[str, Any],
    initiative_id: str,
) -> Mapping[str, Any] | None:
    authorizations = control.get("authorizations")
    if not isinstance(authorizations, Mapping):
        raise RuntimeError("replay Initiative authorization projection is absent")
    authorization = authorizations.get(f"Initiative:{initiative_id}")
    if authorization is None:
        return None
    if not isinstance(authorization, Mapping):
        raise RuntimeError("replay Initiative authorization projection is malformed")
    return authorization


def _exact_active_authority(
    control: Mapping[str, Any],
    initiative_id: str,
) -> bool:
    science = control.get("scientific")
    authorization = _initiative_authorization(control, initiative_id)
    return bool(
        isinstance(science, Mapping)
        and science.get("active_initiative") == initiative_id
        and authorization is not None
        and authorization.get("kind") == "Initiative"
        and authorization.get("subject_id") == initiative_id
    )


def _later_owner_handoff_is_coherent(
    *,
    control: Mapping[str, Any],
    index: LocalIndexView,
    initiative_id: str,
    terminal_operation: Any,
) -> bool:
    """Prove that the Initiative owner, not replay, closed after handoff."""

    terminal_sequence = terminal_operation.authority_sequence
    terminal_event_id = terminal_operation.authority_event_id
    journal_head = control.get("heads", {}).get("journal", {})
    if (
        type(terminal_sequence) is not int
        or not isinstance(terminal_event_id, str)
        or not isinstance(journal_head, Mapping)
        or type(journal_head.get("sequence")) is not int
        or journal_head["sequence"] <= terminal_sequence
        or _initiative_authorization(control, initiative_id) is not None
    ):
        return False
    subject = f"Initiative:{initiative_id}"
    closes = tuple(
        record
        for status in _INITIATIVE_TERMINAL_STATUSES
        for record in index.records_by_subject_status(subject, status)
        if record.kind == "initiative-close"
        and record.subject == subject
        and isinstance(record.status, str)
        and record.status
        and isinstance(record.payload, Mapping)
        and record.payload.get("outcome") == record.status
        and isinstance(record.authority_event_id, str)
        and type(record.authority_sequence) is int
        and terminal_sequence < record.authority_sequence <= journal_head["sequence"]
    )
    if len(closes) != 1:
        return False
    science = control.get("scientific")
    if not isinstance(science, Mapping):
        return False
    active = science.get("active_initiative")
    if active is None:
        return True
    if not isinstance(active, str) or active == initiative_id:
        return False
    successor = index.get("initiative-open", active)
    successor_authorization = _initiative_authorization(control, active)
    return bool(
        successor is not None
        and successor.subject == f"Initiative:{active}"
        and successor.status == "open"
        and successor_authorization is not None
        and successor_authorization.get("kind") == "Initiative"
        and successor_authorization.get("subject_id") == active
    )


def require_replay_initiative_binding(
    *,
    control: Mapping[str, Any],
    index: LocalIndexView,
    lifecycle: ReplayInitiativeLifecycle,
    mission_id: str,
    initiative_id: str,
    operation_prefix: str,
    phase: ReplayInitiativeBindingPhase = ReplayInitiativeBindingPhase.EXECUTION,
) -> None:
    """Fail closed unless control, authorization, and workflow ownership agree."""

    if not isinstance(lifecycle, ReplayInitiativeLifecycle):
        raise RuntimeError("replay Initiative lifecycle is not typed")
    if not isinstance(phase, ReplayInitiativeBindingPhase):
        raise RuntimeError("replay Initiative binding phase is not typed")
    science = control.get("scientific")
    if not isinstance(science, Mapping) or science.get("active_mission") != mission_id:
        raise RuntimeError("replay Initiative belongs to another active Mission")
    active_initiative = science.get("active_initiative")
    authorization = _initiative_authorization(control, initiative_id)
    open_operation = _successful_operation(
        index,
        operation_prefix + "open-initiative",
        "initiative_opened",
    )
    close_operation = _successful_operation(
        index,
        operation_prefix + "close-initiative",
        "initiative_closed",
    )
    terminal_operation = (
        None
        if phase is ReplayInitiativeBindingPhase.EXECUTION
        else _successful_operation(
            index,
            operation_prefix + "resolve-replay",
            frozenset(
                {
                    "historical_replay_obligations_deferred",
                    "historical_replay_obligations_disposed",
                    "historical_replay_obligations_resolved",
                }
            ),
        )
    )
    if (
        phase is ReplayInitiativeBindingPhase.TERMINAL_HANDOFF
        and terminal_operation is None
    ):
        raise RuntimeError("terminal replay handoff lacks its exact resolution")

    if lifecycle is ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE:
        initiative = index.get("initiative-open", initiative_id)
        if open_operation is not None or close_operation is not None:
            raise RuntimeError(
                "borrowed replay is not bound to the exact active Initiative"
            )
        if (
            initiative is not None
            and initiative.subject == f"Initiative:{initiative_id}"
            and initiative.status == "open"
            and _exact_active_authority(control, initiative_id)
        ):
            return
        if (
            terminal_operation is not None
            and _later_owner_handoff_is_coherent(
                control=control,
                index=index,
                initiative_id=initiative_id,
                terminal_operation=terminal_operation,
            )
        ):
            return
        raise RuntimeError(
            "borrowed replay is not bound to the exact active Initiative"
        )

    if close_operation is not None and open_operation is None:
        raise RuntimeError("owned replay Initiative close lacks its open")
    if open_operation is None:
        if active_initiative is not None or authorization is not None:
            raise RuntimeError(
                "owned replay requires an empty Initiative boundary before open"
            )
        return

    open_result = open_operation.payload.get("result")
    if (
        not isinstance(open_result, Mapping)
        or open_result.get("initiative_id") != initiative_id
    ):
        raise RuntimeError("owned replay Initiative open identity drifted")
    if close_operation is None:
        if _exact_active_authority(control, initiative_id):
            return
        if (
            terminal_operation is not None
            and _later_owner_handoff_is_coherent(
                control=control,
                index=index,
                initiative_id=initiative_id,
                terminal_operation=terminal_operation,
            )
        ):
            return
        raise RuntimeError("owned replay Initiative is not exactly active")

    close_result = close_operation.payload.get("result")
    successor_authorization = (
        None
        if active_initiative is None
        or active_initiative == initiative_id
        or not isinstance(active_initiative, str)
        else _initiative_authorization(control, active_initiative)
    )
    if (
        not isinstance(close_result, Mapping)
        or close_result.get("initiative_id") != initiative_id
        or active_initiative == initiative_id
        or authorization is not None
        or (
            active_initiative is not None
            and (
                successor_authorization is None
                or successor_authorization.get("kind") != "Initiative"
                or successor_authorization.get("subject_id")
                != active_initiative
            )
        )
    ):
        raise RuntimeError("owned replay Initiative terminal binding drifted")


__all__ = [
    "ReplayInitiativeBindingPhase",
    "ReplayInitiativeLifecycle",
    "require_replay_initiative_binding",
]
