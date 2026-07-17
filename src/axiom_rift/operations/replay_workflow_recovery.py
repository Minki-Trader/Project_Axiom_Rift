"""Exact replay terminal reconstruction and router-bound admission."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from axiom_rift.operations.architecture_review_direction import (
    ARCHITECTURE_CONTINUATION_ACTION_FIELDS,
)
from axiom_rift.operations.replay_initiative_lifecycle import (
    ReplayInitiativeBindingPhase,
    ReplayInitiativeLifecycle,
)
from axiom_rift.operations.replay_projection import (
    scheduler_constraints,
    with_scheduler_constraints,
)
from axiom_rift.storage.index import IndexRecord, LocalIndexView


class ReplayLifecycleSpec(Protocol):
    """Minimal replay identity needed by recovery checks."""

    mission_id: str
    initiative_id: str
    study_id: str
    operation_prefix: str
    target_obligation_id: str
    replay_obligation_ids: tuple[str, ...]
    initiative_lifecycle: ReplayInitiativeLifecycle
    axis_admission: Any


class ReplayBoundaryJournal(Protocol):
    def read_event_at(
        self,
        *,
        offset: int,
        expected_sequence: int,
        expected_event_id: str,
    ) -> Mapping[str, Any]: ...


class ReplayBoundaryWriter(Protocol):
    journal: ReplayBoundaryJournal


_PORTFOLIO_DECISION_CONTEXT_FIELDS = frozenset(
    {
        "architecture_review_id",
        "constraint_source_id",
        "excluded_architecture_family",
        "excluded_research_layers",
        "required_target_axis_ids",
        "study_diagnosis_id",
        *ARCHITECTURE_CONTINUATION_ACTION_FIELDS,
    }
)


def _authority_event_id(name: str, value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RuntimeError(f"{name} is invalid")
    return value


def derive_replay_admission_boundary_identity(
    writer: ReplayBoundaryWriter,
    *,
    index: LocalIndexView,
    control: Mapping[str, Any],
    first_operation_id: str,
) -> tuple[int, str]:
    """Bind the current idle head or recover the first operation's parent."""

    if type(first_operation_id) is not str or not first_operation_id:
        raise RuntimeError("replay first operation identity is invalid")
    first = index.get("operation", first_operation_id)
    if first is None:
        heads = control.get("heads")
        journal = heads.get("journal") if isinstance(heads, Mapping) else None
        sequence = journal.get("sequence") if isinstance(journal, Mapping) else None
        event_id = journal.get("event_id") if isinstance(journal, Mapping) else None
        if type(sequence) is not int or sequence < 1:
            raise RuntimeError("replay current authority sequence is invalid")
        return sequence, _authority_event_id(
            "replay current authority event",
            event_id,
        )
    if (
        first.status != "success"
        or first.authority_sequence is None
        or first.authority_event_id is None
        or first.authority_offset is None
        or first.authority_sequence < 2
    ):
        raise RuntimeError("replay first-operation authority is incomplete")
    event = writer.journal.read_event_at(
        offset=first.authority_offset,
        expected_sequence=first.authority_sequence,
        expected_event_id=first.authority_event_id,
    )
    previous = _authority_event_id(
        "replay predecessor event",
        event.get("previous_event_id"),
    )
    return first.authority_sequence - 1, previous


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
        raise RuntimeError("replay recovery operation is malformed")
    return record


def diagnosis_architecture_review_trigger(
    index: LocalIndexView,
    spec: ReplayLifecycleSpec,
) -> str | None:
    """Return the exact review handoff created by this replay diagnosis."""

    operation = index.get(
        "operation",
        spec.operation_prefix + "diagnose-study",
    )
    if operation is None:
        return None
    result = operation.payload.get("result")
    diagnosis_id = (
        None if not isinstance(result, Mapping) else result.get("study_diagnosis_id")
    )
    diagnosis = (
        None
        if not isinstance(diagnosis_id, str)
        else index.get("study-diagnosis", diagnosis_id)
    )
    if (
        operation.status != "success"
        or operation.payload.get("event_kind") != "study_diagnosis_recorded"
        or operation.authority_sequence is None
        or operation.authority_event_id is None
        or diagnosis is None
        or diagnosis.subject != f"Study:{spec.study_id}"
        or diagnosis.payload.get("mission_id") != spec.mission_id
        or diagnosis.authority_sequence != operation.authority_sequence
        or diagnosis.authority_event_id != operation.authority_event_id
    ):
        raise RuntimeError("replay diagnosis operation projection is malformed")
    trigger_id = result.get("architecture_review_trigger_id")
    if trigger_id is None:
        return None
    trigger = (
        index.get("architecture-review-trigger", trigger_id)
        if isinstance(trigger_id, str)
        else None
    )
    diagnosis_ids = (
        None if trigger is None else trigger.payload.get("diagnosis_ids")
    )
    if (
        trigger is None
        or trigger.record_id != trigger_id
        or trigger.status != "required"
        or trigger.subject != f"Mission:{spec.mission_id}"
        or trigger.payload.get("schema") != "architecture_review_trigger.v1"
        or trigger.payload.get("mission_id") != spec.mission_id
        or not isinstance(diagnosis_ids, list)
        or any(not isinstance(item, str) for item in diagnosis_ids)
        or diagnosis_ids != sorted(set(diagnosis_ids))
        or diagnosis_id not in diagnosis_ids
        or trigger.payload.get("portfolio_snapshot_id")
        != diagnosis.payload.get("portfolio_snapshot_id")
        or trigger.payload.get("system_architecture_family")
        != diagnosis.payload.get("system_architecture_family")
        or trigger.authority_sequence != operation.authority_sequence
        or trigger.authority_event_id != operation.authority_event_id
    ):
        raise RuntimeError("replay architecture-review handoff is malformed")
    return trigger_id


def terminal_replay_reconstruction_allowed(
    index: LocalIndexView,
    spec: ReplayLifecycleSpec,
    target_head: IndexRecord,
    *,
    control: Mapping[str, Any] | None = None,
) -> bool:
    """Permit reconstruction at any exact post-resolution workflow prefix."""

    scientific_change_return = target_head.status == "pending"
    if target_head.status not in {"pending", "satisfied", "deferred"}:
        return False
    resolution_events = (
        {
            (
                "historical_replay_obligations_"
                "returned_for_scientific_change"
            )
        }
        if scientific_change_return
        else {
            "historical_replay_obligations_disposed",
            (
                "historical_replay_obligations_resolved"
                if target_head.status == "satisfied"
                else "historical_replay_obligations_deferred"
            ),
        }
    )
    trigger_id = diagnosis_architecture_review_trigger(index, spec)
    expected: tuple[tuple[str, set[str]], ...] = (
        ("diagnose-study", {"study_diagnosis_recorded"}),
        ("resolve-replay", resolution_events),
    )
    if (
        trigger_id is None
        and spec.initiative_lifecycle
        is ReplayInitiativeLifecycle.OWN_BOUNDED_INITIATIVE
    ):
        expected = (
            *expected,
            ("disposition-decision", {"portfolio_decision_recorded"}),
            ("disposition-snapshot", {"portfolio_snapshot_recorded"}),
            ("close-initiative", {"initiative_closed"}),
        )
    records = tuple(
        index.get("operation", spec.operation_prefix + suffix)
        for suffix, _event_kinds in expected
    )
    present = tuple(record is not None for record in records)
    if present[:2] != (True, True):
        return False
    first_absent = next(
        (position for position, value in enumerate(present) if not value),
        len(present),
    )
    if any(present[first_absent:]):
        return False
    if any(
        record.status != "success"
        or record.payload.get("event_kind") not in event_kinds
        for record, (_suffix, event_kinds) in zip(records, expected, strict=True)
        if record is not None
    ):
        return False
    forbidden_suffixes = (
        ("disposition-decision", "disposition-snapshot", "close-initiative")
        if trigger_id is not None
        or spec.initiative_lifecycle
        is ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE
        else ()
    )
    if any(
        index.get("operation", spec.operation_prefix + suffix) is not None
        for suffix in forbidden_suffixes
    ):
        return False
    resolution_result = records[1].payload.get("result")
    result_field = (
        "returned_replay_obligation_ids"
        if scientific_change_return
        else "satisfied_replay_obligation_ids"
        if target_head.status == "satisfied"
        else "deferred_replay_obligation_ids"
    )
    expected_result_ids = list(spec.replay_obligation_ids)
    resolution_operation = records[1]
    if (
        not isinstance(resolution_result, Mapping)
        or resolution_result.get(result_field) != expected_result_ids
        or target_head.payload.get("obligation_id") != spec.target_obligation_id
        or resolution_operation.authority_sequence is None
        or resolution_operation.authority_event_id is None
        or target_head.authority_sequence != resolution_operation.authority_sequence
        or target_head.authority_event_id != resolution_operation.authority_event_id
    ):
        return False
    if control is not None:
        action = control.get("next_action")
        head = control.get("heads", {}).get("journal", {})
        last_operation = records[first_absent - 1]
        immediate = (
            isinstance(head, Mapping)
            and head.get("sequence") == last_operation.authority_sequence
            and head.get("event_id") == last_operation.authority_event_id
        )
        if not immediate:
            if (
                first_absent < len(expected)
                or not isinstance(head, Mapping)
                or type(head.get("sequence")) is not int
                or type(last_operation.authority_sequence) is not int
                or head["sequence"] <= last_operation.authority_sequence
            ):
                return False
            return True
        if not isinstance(action, Mapping):
            return False
        constraints = scheduler_constraints(index, mission_id=spec.mission_id)
        if first_absent == 2:
            diagnosis_result = records[0].payload.get("result")
            diagnosis_id = (
                diagnosis_result.get("study_diagnosis_id")
                if isinstance(diagnosis_result, Mapping)
                else None
            )
            diagnosis = (
                index.get("study-diagnosis", diagnosis_id)
                if isinstance(diagnosis_id, str)
                else None
            )
            snapshot_id = (
                None
                if diagnosis is None
                else diagnosis.payload.get("portfolio_snapshot_id")
            )
            if not isinstance(snapshot_id, str):
                return False
            expected_action = with_scheduler_constraints(
                (
                    {
                        "kind": "review_architecture",
                        "trigger_record_id": trigger_id,
                    }
                    if trigger_id is not None
                    else {
                        "kind": "portfolio_decision",
                        "portfolio_snapshot_id": snapshot_id,
                        "study_diagnosis_id": diagnosis_id,
                    }
                ),
                constraints,
            )
        elif first_absent == 3:
            decision_result = records[2].payload.get("result")
            decision_id = (
                decision_result.get("decision_id")
                if isinstance(decision_result, Mapping)
                else None
            )
            decision = (
                index.get("portfolio-decision", decision_id)
                if isinstance(decision_id, str)
                else None
            )
            options = () if decision is None else decision.payload.get("options", ())
            chosen_id = (
                None if decision is None else decision.payload.get("chosen_option_id")
            )
            chosen = tuple(
                option
                for option in options
                if isinstance(option, Mapping)
                and option.get("option_id") == chosen_id
            )
            if (
                decision is None
                or len(chosen) != 1
                or not isinstance(decision.payload.get("target_axis_identity"), str)
                or not isinstance(decision.payload.get("portfolio_snapshot_id"), str)
            ):
                return False
            expected_action = {
                "action": chosen[0].get("action"),
                "decision_id": decision_id,
                "kind": "record_portfolio_snapshot",
                "portfolio_snapshot_id": decision.payload["portfolio_snapshot_id"],
                "target_axis_identity": decision.payload["target_axis_identity"],
                "target_id": chosen[0].get("target_id"),
            }
            replay_ids = decision.payload.get("replay_obligation_ids", ())
            if replay_ids:
                expected_action["replay_obligation_ids"] = list(replay_ids)
            expected_action = with_scheduler_constraints(
                expected_action,
                constraints,
            )
        elif first_absent == 4:
            snapshot_result = records[3].payload.get("result")
            snapshot_id = (
                snapshot_result.get("portfolio_snapshot_id")
                if isinstance(snapshot_result, Mapping)
                else None
            )
            if not isinstance(snapshot_id, str):
                return False
            expected_action = with_scheduler_constraints(
                {
                    "kind": "portfolio_decision",
                    "portfolio_snapshot_id": snapshot_id,
                },
                constraints,
            )
        elif first_absent == 5 and len(expected) == 5:
            expected_action = with_scheduler_constraints(
                {
                    "kind": "choose_next_initiative_or_terminal",
                    "mission_id": spec.mission_id,
                },
                constraints,
            )
        else:
            return False
        if action != expected_action:
            return False
    return True


def require_borrowed_replay_admission(
    *,
    control: Mapping[str, Any],
    index: LocalIndexView,
    spec: ReplayLifecycleSpec,
) -> None:
    """Require the exact idle Portfolio boundary before borrowing begins."""

    if (
        spec.initiative_lifecycle
        is not ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE
    ):
        return
    admission = getattr(spec.axis_admission, "value", spec.axis_admission)
    first_suffix = (
        "replay-decision"
        if admission == "reuse_exact_axis"
        else "bridge-decision"
    )
    bridge = index.get(
        "operation",
        spec.operation_prefix + first_suffix,
    )
    if bridge is not None:
        if (
            bridge.status != "success"
            or bridge.payload.get("event_kind")
            != "portfolio_decision_recorded"
        ):
            raise RuntimeError("borrowed replay bridge operation is malformed")
        return
    science = control.get("scientific")
    head = control.get("heads", {}).get("journal", {})
    boundary = getattr(spec, "boundary", None)
    if (
        not isinstance(science, Mapping)
        or any(
            science.get(name) is not None
            for name in (
                "active_batch",
                "active_executable",
                "active_holdout_evaluation",
                "active_job",
                "active_lineage",
                "active_release",
                "active_repair",
                "active_study",
            )
        )
        or not isinstance(head, Mapping)
        or boundary is None
        or head.get("sequence") != boundary.sequence
        or head.get("event_id") != boundary.event_id
    ):
        raise RuntimeError("borrowed replay admission boundary is not idle and exact")
    portfolio_head = index.event_head(f"portfolio:{spec.mission_id}")
    if portfolio_head is None or portfolio_head.record_kind != "portfolio-snapshot":
        raise RuntimeError("borrowed replay current Portfolio is unavailable")
    constraints = scheduler_constraints(index, mission_id=spec.mission_id)
    action = control.get("next_action")
    context = (
        {
            name: action[name]
            for name in _PORTFOLIO_DECISION_CONTEXT_FIELDS
            if name in action
        }
        if isinstance(action, Mapping)
        else {}
    )
    expected_action = with_scheduler_constraints(
        {
            "kind": "portfolio_decision",
            "portfolio_snapshot_id": portfolio_head.record_id,
            **context,
        },
        constraints,
    )
    if action != expected_action:
        raise RuntimeError("borrowed replay is not the exact Portfolio action")


def replay_resolution_operation_present(
    index: LocalIndexView,
    spec: ReplayLifecycleSpec,
) -> bool:
    """Reject malformed completed prefixes while detecting consumed identity."""

    return _successful_operation(
        index,
        spec.operation_prefix + "resolve-replay",
        frozenset(
            {
                "historical_replay_obligations_deferred",
                "historical_replay_obligations_disposed",
                "historical_replay_obligations_resolved",
                (
                    "historical_replay_obligations_"
                    "returned_for_scientific_change"
                ),
            }
        ),
    ) is not None


def replay_initiative_binding_phase(
    *,
    control: Mapping[str, Any],
    index: LocalIndexView,
    spec: ReplayLifecycleSpec,
    target_head: IndexRecord,
) -> ReplayInitiativeBindingPhase:
    """Derive execution versus historical handoff from exact durable state."""

    if target_head.status in {"pending", "in_progress"}:
        resolution_present = replay_resolution_operation_present(index, spec)
        if (
            target_head.status == "pending"
            and resolution_present
            and terminal_replay_reconstruction_allowed(
                index,
                spec,
                target_head,
                control=control,
            )
        ):
            return ReplayInitiativeBindingPhase.TERMINAL_HANDOFF
        if resolution_present:
            raise RuntimeError(
                "reopened replay obligation requires fresh workflow identities"
            )
        return ReplayInitiativeBindingPhase.EXECUTION
    if terminal_replay_reconstruction_allowed(
        index,
        spec,
        target_head,
        control=control,
    ):
        return ReplayInitiativeBindingPhase.TERMINAL_HANDOFF
    raise RuntimeError("replay obligation is outside its exact lifecycle")


__all__ = [
    "diagnosis_architecture_review_trigger",
    "replay_initiative_binding_phase",
    "replay_resolution_operation_present",
    "require_borrowed_replay_admission",
    "terminal_replay_reconstruction_allowed",
]
