"""Durable read projection and record preparation for historical replay.

The scientific types and state-machine vocabulary live in
``research.replay_obligation``.  This adapter verifies their Journal-backed
SQLite projection and prepares immutable records.  It never writes control,
the Journal, or the index; StateWriter owns the single commit boundary.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.recorded_transition_authority import (
    RecordedTransitionAuthorityError,
    require_recorded_transition_authority,
    require_same_event_operation_result,
)
from axiom_rift.operations.evidence_scope_projection import (
    evidence_scope_overlay_record,
    evidence_scope_stream,
)
from axiom_rift.operations.executable_axis_lineage import (
    ExecutableAxisLineageError,
    completion_executable_axis_lineage,
)
from axiom_rift.operations.completion_validity_projection import (
    CompletionValidityProjectionError,
    current_completion_validity_invalidation,
)
from axiom_rift.operations.scientific_multiplicity_authority import (
    MULTIPLICITY_BATCH_BINDING_FIELDS,
    build_multiplicity_batch_binding,
)
from axiom_rift.research.effective_evidence_scope import (
    HistoricalEvidenceScopeOverlay,
)
from axiom_rift.research.historical_adjudication import ReplayPriority
from axiom_rift.research.replay_obligation import (
    HistoricalReplayObligation,
    ReplayDeferral,
    ReplayDeferralBasisKind,
    ReplayExecutionBinding,
    ReplayObligationStatus,
    ReplayPriorityEscalation,
    ReplayRepairBasisKind,
    ReplayRepairProvenance,
    ReplayResolutionScope,
    ReplayResumeCondition,
    ReplayResumeConditionKind,
    ReplayResumeEvidence,
    ReplaySatisfaction,
    derive_historical_replay_obligation,
    historical_replay_obligation_from_identity_payload,
    replay_priority_escalation_from_identity_payload,
    replay_deferral_from_identity_payload,
)
from axiom_rift.research.replay_satisfaction_invalidation import (
    ReplayCompletionValidityDefect,
    ReplayCompletionValidityDefectCode,
    ReplayCompletionValidityObservation,
    ReplayMultiplicityBindingDefect,
    ReplayMultiplicityDefectCode,
    ReplaySatisfactionInvalidationAuditManifest,
    ReplaySatisfactionInvalidationAuditManifestV2,
    ReplaySatisfactionInvalidationManifest,
    ReplaySelectionFamilyObservation,
    SELECTION_CRITERION_ID,
    replay_satisfaction_invalidation_manifest_from_mapping,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView
from axiom_rift.storage.evidence import EvidenceStore
from axiom_rift.storage.study_kpi import validate_study_id


_STUDY_OUTCOMES = (
    "supported",
    "not_supported",
    "not_evaluable",
    "evidence_gap",
    "pruned",
    "preserved",
)


class ReplayAuthorityError(RuntimeError):
    """Base error for historical replay projection and transition requests."""


class ReplayProjectionError(ReplayAuthorityError):
    """Durable replay authority is malformed or incomplete."""


class ReplayTransitionError(ReplayAuthorityError):
    """A requested replay transition is not currently authorized."""


class ReplayMultiplicityBindingError(ReplayTransitionError):
    """The exact Batch-wide E01 family no longer supports satisfaction."""

    def __init__(self, defect: ReplayMultiplicityBindingDefect) -> None:
        super().__init__(
            "scientific replay selection family does not bind the exact Batch family"
        )
        self.defect = defect


class _HistoricalRegistrationOrderDiagnostic(ReplayTransitionError):
    """A same-member legacy order mismatch with no revocation authority."""

    def __init__(
        self,
        *,
        expected_ordered_member_ids: tuple[str, ...],
        observations: tuple[ReplaySelectionFamilyObservation, ...],
    ) -> None:
        super().__init__(
            "scientific replay selection registration order differs from the "
            "exact prospective Batch order"
        )
        self.expected_ordered_member_ids = expected_ordered_member_ids
        self.observations = observations


@dataclass(frozen=True, slots=True)
class _DiagnosedReplayExecution:
    progress: IndexRecord
    study: IndexRecord
    trial: IndexRecord
    close: IndexRecord
    diagnosis: IndexRecord
    completion: IndexRecord
    declaration: IndexRecord


@dataclass(frozen=True, slots=True)
class _DiagnosedReplayPreflightInvalidation:
    progress: IndexRecord
    study: IndexRecord
    trial: IndexRecord
    close: IndexRecord
    diagnosis: IndexRecord
    preflight: IndexRecord
    batch_close: IndexRecord


def _record(
    *,
    kind: str,
    record_id: str,
    subject: str,
    status: str,
    fingerprint: str,
    payload: Mapping[str, Any],
    event_stream: str,
    event_sequence: int,
) -> IndexRecord:
    return IndexRecord(
        kind=kind,
        record_id=record_id,
        subject=subject,
        status=status,
        fingerprint=fingerprint,
        payload=dict(payload),
        event_stream=event_stream,
        event_sequence=event_sequence,
    )


def obligation_stream(obligation_id: str) -> str:
    return f"historical-replay-obligation:{obligation_id}"


def replay_priority_stream(obligation_id: str) -> str:
    return f"historical-replay-priority:{obligation_id}"


def replay_priority_escalation_record(
    escalation: ReplayPriorityEscalation,
) -> IndexRecord:
    """Prepare one independent, append-only P1-to-P0 priority overlay."""

    if not isinstance(escalation, ReplayPriorityEscalation):
        raise ReplayTransitionError("replay priority escalation is not typed")
    return _record(
        kind="historical-replay-priority-escalation",
        record_id=escalation.identity,
        subject=f"Mission:{escalation.governing_mission_id}",
        status=ReplayPriority.P0.value,
        fingerprint=escalation.identity.removeprefix(
            "historical-replay-priority-escalation:"
        ),
        payload={"escalation": escalation.to_identity_payload()},
        event_stream=replay_priority_stream(escalation.obligation_id),
        event_sequence=1,
    )


def current_replay_priority_escalation(
    index: LocalIndex | LocalIndexView,
    obligation: HistoricalReplayObligation,
) -> ReplayPriorityEscalation | None:
    """Open and authenticate the one possible effective-priority overlay."""

    if not isinstance(obligation, HistoricalReplayObligation):
        raise ReplayProjectionError("replay priority subject is not typed")
    stream = replay_priority_stream(obligation.identity)
    head = index.event_head(stream)
    if head is None:
        return None
    record = index.get(head.record_kind, head.record_id)
    raw = None if record is None else record.payload.get("escalation")
    try:
        escalation = replay_priority_escalation_from_identity_payload(raw)
    except (TypeError, ValueError) as exc:
        raise ReplayProjectionError(
            "replay priority escalation payload is malformed"
        ) from exc
    if (
        record is None
        or head.sequence != 1
        or record.kind != "historical-replay-priority-escalation"
        or record.record_id != escalation.identity
        or record.status != ReplayPriority.P0.value
        or record.subject != f"Mission:{obligation.governing_mission_id}"
        or record.fingerprint
        != escalation.identity.removeprefix(
            "historical-replay-priority-escalation:"
        )
        or record.event_stream != stream
        or record.event_sequence != head.sequence
        or set(record.payload) != {"escalation"}
        or obligation.replay_priority is not ReplayPriority.P1
        or escalation.obligation_id != obligation.identity
        or escalation.governing_mission_id != obligation.governing_mission_id
    ):
        raise ReplayProjectionError(
            "replay priority escalation stream is malformed"
        )
    try:
        validity = current_completion_validity_invalidation(
            index,
            obligation.original_completion_record_id,
        )
    except CompletionValidityProjectionError as exc:
        raise ReplayProjectionError(
            "replay priority escalation completion validity is malformed"
        ) from exc
    adjudication = index.get(
        "historical-scientific-adjudication",
        escalation.superseding_historical_adjudication_id,
    )
    adjudication_stream = (
        f"historical-adjudication:{obligation.original_completion_record_id}"
    )
    adjudication_head = index.event_head(adjudication_stream)
    current_adjudication = (
        None
        if adjudication_head is None
        else index.get(
            adjudication_head.record_kind,
            adjudication_head.record_id,
        )
    )
    escalation_adjudication_is_in_lineage = False
    seen_adjudication_ids: set[str] = set()
    while current_adjudication is not None:
        if (
            current_adjudication.record_id in seen_adjudication_ids
            or current_adjudication.kind
            != "historical-scientific-adjudication"
            or current_adjudication.event_stream != adjudication_stream
            or type(current_adjudication.event_sequence) is not int
            or current_adjudication.event_sequence < 1
        ):
            raise ReplayProjectionError(
                "replay priority escalation adjudication lineage is malformed"
            )
        seen_adjudication_ids.add(current_adjudication.record_id)
        if (
            current_adjudication.record_id
            == escalation.superseding_historical_adjudication_id
        ):
            escalation_adjudication_is_in_lineage = True
            break
        prior_adjudication_id = current_adjudication.payload.get(
            "supersedes_record_id"
        )
        if prior_adjudication_id is None:
            current_adjudication = None
        elif not isinstance(prior_adjudication_id, str):
            raise ReplayProjectionError(
                "replay priority escalation adjudication lineage is malformed"
            )
        else:
            current_adjudication = index.get(
                "historical-scientific-adjudication",
                prior_adjudication_id,
            )
    satisfaction = index.get(
        "historical-replay-obligation-resolution",
        escalation.accepted_satisfaction_record_id,
    )
    if (
        validity is None
        or validity.invalidation_record_id
        != escalation.completion_validity_invalidation_id
        or adjudication is None
        or adjudication_head is None
        or current_adjudication is None
        or not escalation_adjudication_is_in_lineage
        or adjudication.status != "replay_required"
        or adjudication.payload.get("completion_record_id")
        != obligation.original_completion_record_id
        or adjudication.payload.get("audit_artifact_hash")
        != escalation.audit_artifact_hash
        or adjudication.payload.get("replay_priority")
        != ReplayPriority.P0.value
        or adjudication.payload.get("replay_obligation_id")
        != obligation.identity
        or adjudication.payload.get("replay_obligation_authority")
        != "reused_existing_lineage"
        or satisfaction is None
        or satisfaction.status != ReplayObligationStatus.SATISFIED.value
        or satisfaction.event_stream != obligation_stream(obligation.identity)
        or satisfaction.payload.get("obligation_id") != obligation.identity
    ):
        raise ReplayProjectionError(
            "replay priority escalation lost its exact additive authority"
        )
    try:
        event_kind, result = require_same_event_operation_result(
            index,
            record=record,
            expected_event_kinds=frozenset(
                {"historical_scientific_adjudications_recorded"}
            ),
        )
    except RecordedTransitionAuthorityError as exc:
        raise ReplayProjectionError(
            "replay priority escalation lacks same-event Writer authority"
        ) from exc
    escalation_ids = result.get("replay_priority_escalation_ids")
    adjudication_ids = result.get("adjudication_record_ids")
    new_obligation_ids = result.get("replay_obligation_ids")
    reused_obligation_ids = result.get("reused_replay_obligation_ids")
    if (
        event_kind != "historical_scientific_adjudications_recorded"
        or set(result)
        != {
            "adjudication_record_ids",
            "audit_artifact_hash",
            "candidate_delta",
            "holdout_delta",
            "replay_obligation_ids",
            "replay_priority_escalation_ids",
            "reused_replay_obligation_ids",
            "trial_delta",
        }
        or result.get("audit_artifact_hash") != escalation.audit_artifact_hash
        or not isinstance(escalation_ids, list)
        or any(type(item) is not str for item in escalation_ids)
        or escalation_ids != sorted(set(escalation_ids))
        or escalation.identity not in escalation_ids
        or not isinstance(adjudication_ids, list)
        or any(type(item) is not str for item in adjudication_ids)
        or len(adjudication_ids) != len(set(adjudication_ids))
        or escalation.superseding_historical_adjudication_id
        not in adjudication_ids
        or not isinstance(new_obligation_ids, list)
        or any(type(item) is not str for item in new_obligation_ids)
        or len(new_obligation_ids) != len(set(new_obligation_ids))
        or obligation.identity in new_obligation_ids
        or not isinstance(reused_obligation_ids, list)
        or any(type(item) is not str for item in reused_obligation_ids)
        or reused_obligation_ids != sorted(set(reused_obligation_ids))
        or obligation.identity not in reused_obligation_ids
        or any(
            result.get(name) != 0
            for name in ("candidate_delta", "holdout_delta", "trial_delta")
        )
    ):
        raise ReplayProjectionError(
            "replay priority escalation Writer result is not exact"
        )
    return escalation


def effective_replay_priority(
    index: LocalIndex | LocalIndexView,
    obligation: HistoricalReplayObligation,
) -> ReplayPriority:
    escalation = current_replay_priority_escalation(index, obligation)
    return (
        obligation.replay_priority
        if escalation is None
        else escalation.effective_priority
    )


def initial_obligation_record(
    obligation: HistoricalReplayObligation,
) -> IndexRecord:
    return _record(
        kind="historical-replay-obligation",
        record_id=obligation.identity,
        subject=f"Mission:{obligation.governing_mission_id}",
        status=ReplayObligationStatus.PENDING.value,
        fingerprint=obligation.identity.removeprefix(
            "historical-replay-obligation:"
        ),
        payload={"obligation": obligation.to_identity_payload()},
        event_stream=obligation_stream(obligation.identity),
        event_sequence=1,
    )


def satisfaction_record(
    *,
    obligation: HistoricalReplayObligation,
    satisfaction: ReplaySatisfaction,
    prior_status: ReplayObligationStatus,
    sequence: int,
) -> IndexRecord:
    return _record(
        kind="historical-replay-obligation-resolution",
        record_id=satisfaction.identity,
        subject=f"Mission:{obligation.governing_mission_id}",
        status=ReplayObligationStatus.SATISFIED.value,
        fingerprint=satisfaction.identity.removeprefix(
            "historical-replay-satisfaction:"
        ),
        payload={
            "obligation_id": obligation.identity,
            "prior_status": prior_status.value,
            "resolution": satisfaction.to_identity_payload(),
        },
        event_stream=obligation_stream(obligation.identity),
        event_sequence=sequence,
    )


def deferral_record(
    *,
    obligation: HistoricalReplayObligation,
    deferral: ReplayDeferral,
    prior_status: ReplayObligationStatus,
    sequence: int,
) -> IndexRecord:
    return _record(
        kind="historical-replay-obligation-resolution",
        record_id=deferral.identity,
        subject=f"Mission:{obligation.governing_mission_id}",
        status=ReplayObligationStatus.DEFERRED.value,
        fingerprint=deferral.identity.removeprefix("historical-replay-deferral:"),
        payload={
            "obligation_id": obligation.identity,
            "prior_status": prior_status.value,
            "resolution": deferral.to_identity_payload(),
        },
        event_stream=obligation_stream(obligation.identity),
        event_sequence=sequence,
    )


def resume_record(
    *,
    obligation: HistoricalReplayObligation,
    evidence: ReplayResumeEvidence,
    sequence: int,
) -> IndexRecord:
    """Prepare one append-only deferred-to-pending replay transition."""

    return _record(
        kind="historical-replay-obligation-resume",
        record_id=evidence.identity,
        subject=f"Mission:{obligation.governing_mission_id}",
        status=ReplayObligationStatus.PENDING.value,
        fingerprint=evidence.identity.removeprefix(
            "historical-replay-resume-evidence:"
        ),
        payload={
            "obligation_id": obligation.identity,
            "prior_status": ReplayObligationStatus.DEFERRED.value,
            "resume_evidence": evidence.to_identity_payload(),
            "scientific_claim_delta": 0,
            "scientific_satisfaction_delta": 0,
            "scientific_trial_delta": 0,
        },
        event_stream=obligation_stream(obligation.identity),
        event_sequence=sequence,
    )


def obligation_heads(
    index: LocalIndex | LocalIndexView,
    *,
    mission_id: str,
) -> tuple[tuple[HistoricalReplayObligation, IndexRecord], ...]:
    """Return exact current heads for one Mission's replay obligations."""

    resolved: list[tuple[HistoricalReplayObligation, IndexRecord]] = []
    mission_subject = f"Mission:{mission_id}"
    for initial in index.records_by_subject_status(
        mission_subject,
        ReplayObligationStatus.PENDING.value,
    ):
        if initial.kind != "historical-replay-obligation":
            continue
        raw = initial.payload.get("obligation")
        try:
            obligation = historical_replay_obligation_from_identity_payload(raw)
        except (TypeError, ValueError) as exc:
            raise ReplayProjectionError(
                "historical replay obligation projection is malformed"
            ) from exc
        if obligation.governing_mission_id != mission_id:
            continue
        stream = obligation_stream(obligation.identity)
        if (
            initial.record_id != obligation.identity
            or initial.subject != mission_subject
            or initial.status != ReplayObligationStatus.PENDING.value
            or initial.event_stream != stream
            or initial.event_sequence != 1
            or set(initial.payload) != {"obligation"}
        ):
            raise ReplayProjectionError(
                "historical replay obligation initial state is malformed"
            )
        adjudication = index.get(
            "historical-scientific-adjudication",
            obligation.historical_adjudication_id,
        )
        if adjudication is None:
            raise ReplayProjectionError(
                "historical replay obligation lost its adjudication authority"
            )
        try:
            expected = derive_historical_replay_obligation(
                governing_mission_id=mission_id,
                historical_adjudication_id=adjudication.record_id,
                adjudication_payload=adjudication.payload,
            )
        except ValueError as exc:
            raise ReplayProjectionError(
                "historical replay obligation adjudication is malformed"
            ) from exc
        if expected != obligation:
            raise ReplayProjectionError(
                "historical replay obligation differs from its adjudication"
            )
        head = index.event_head(stream)
        current = None if head is None else index.get(head.record_kind, head.record_id)
        if (
            head is None
            or current is None
            or current.event_stream != stream
            or current.event_sequence != head.sequence
            or current.status not in {item.value for item in ReplayObligationStatus}
            or current.payload.get("obligation_id")
            not in {None, obligation.identity}
        ):
            raise ReplayProjectionError(
                "historical replay obligation stream head is malformed"
            )
        if head.sequence == 1 and current.record_id != initial.record_id:
            raise ReplayProjectionError(
                "historical replay obligation initial head is inconsistent"
            )
        resolved.append((obligation, current))
    return tuple(sorted(resolved, key=lambda item: item[0].identity))


def constraints_for_pending(
    obligations: Sequence[HistoricalReplayObligation],
    *,
    effective_priorities: Mapping[str, ReplayPriority] | None = None,
) -> dict[str, Any] | None:
    pending = tuple(obligations)
    if not pending:
        return None
    priorities = {} if effective_priorities is None else dict(effective_priorities)
    identities = {item.identity for item in pending}
    if (
        set(priorities) - identities
        or any(not isinstance(value, ReplayPriority) for value in priorities.values())
        or any(
            priorities.get(item.identity, item.replay_priority)
            not in {item.replay_priority, ReplayPriority.P0}
            or (
                priorities.get(item.identity, item.replay_priority)
                is ReplayPriority.P0
                and item.replay_priority not in {ReplayPriority.P0, ReplayPriority.P1}
            )
            for item in pending
        )
    ):
        raise ReplayProjectionError("effective replay priority inventory is invalid")
    by_id = {
        item.identity: priorities.get(item.identity, item.replay_priority)
        for item in pending
    }
    priority = (
        ReplayPriority.P0
        if ReplayPriority.P0 in by_id.values()
        else ReplayPriority.P1
    )
    return {
        "pending_replay_obligation_ids": sorted(
            item.identity for item in pending if by_id[item.identity] is priority
        ),
        "required_replay_priority": priority.value,
    }


def constraints_for_pending_from_index(
    index: LocalIndex | LocalIndexView,
    obligations: Sequence[HistoricalReplayObligation],
) -> dict[str, Any] | None:
    pending = tuple(obligations)
    return constraints_for_pending(
        pending,
        effective_priorities={
            item.identity: effective_replay_priority(index, item)
            for item in pending
        },
    )


def scheduler_constraints(
    index: LocalIndex | LocalIndexView,
    *,
    mission_id: str,
) -> dict[str, Any] | None:
    return constraints_for_pending_from_index(
        index,
        tuple(
        obligation
        for obligation, head in obligation_heads(index, mission_id=mission_id)
        if head.status == ReplayObligationStatus.PENDING.value
        ),
    )


def with_scheduler_constraints(
    action: Mapping[str, Any],
    constraints: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result = dict(action)
    for name in ("pending_replay_obligation_ids", "required_replay_priority"):
        result.pop(name, None)
    if constraints is not None:
        result.update(constraints)
    return result


def validate_snapshot_scheduler_projection(
    *,
    next_action: Mapping[str, Any],
    decision_payload: Mapping[str, Any],
    constraints: Mapping[str, Any] | None,
) -> bool:
    """Validate snapshot scheduling and identify one exact legacy omission."""

    fields = ("pending_replay_obligation_ids", "required_replay_priority")
    expected = dict(constraints or {})
    projected = {
        name: next_action.get(name)
        for name in fields
        if next_action.get(name) is not None
    }
    if projected == expected:
        return False
    stored = decision_payload.get("scheduler_constraints")
    stored_replay = (
        {}
        if not isinstance(stored, Mapping)
        else {
            name: stored.get(name)
            for name in fields
            if stored.get(name) is not None
        }
    )
    recoverable_legacy_omission = (
        not projected
        and bool(expected)
        and stored_replay == expected
        and next_action.get("kind") == "record_portfolio_snapshot"
        and next_action.get("action") in {"preserve", "prune"}
        and isinstance(decision_payload.get("study_diagnosis_id"), str)
    )
    if recoverable_legacy_omission:
        return True
    raise ReplayTransitionError(
        "Portfolio mutation replay scheduler authority is stale"
    )


def _obligation_affected_axis_identity(
    index: LocalIndex,
    obligation: HistoricalReplayObligation,
) -> str:
    """Resolve the immutable axis whose historical credit is under replay."""

    completion = index.get(
        "job-completed", obligation.original_completion_record_id
    )
    close_record = index.get(
        "study-close", obligation.original_study_close_record_id
    )
    try:
        lineage = (
            None
            if completion is None
            else completion_executable_axis_lineage(index, completion)
        )
    except ExecutableAxisLineageError as exc:
        raise ReplayProjectionError(
            "historical replay affected-axis lineage is malformed or ambiguous"
        ) from exc
    if (
        lineage is None
        or lineage.executable_id != obligation.original_executable_id
        or lineage.study_id != obligation.original_study_id
        or close_record is None
        or close_record.kind != "study-close"
        or close_record.subject != f"Study:{obligation.original_study_id}"
        or close_record.status not in {*_STUDY_OUTCOMES, "failed"}
        or close_record.payload.get("study_id")
        not in (None, obligation.original_study_id)
        or close_record.payload.get("portfolio_axis_id")
        not in (None, lineage.axis_id)
        or close_record.payload.get("portfolio_axis_identity")
        not in (None, lineage.axis_identity)
    ):
        raise ReplayProjectionError(
            "historical replay affected-axis lineage is malformed or ambiguous"
        )
    return lineage.axis_identity


def _decision_target_axis_identity(
    index: LocalIndex,
    *,
    mission_id: str,
    next_action: Mapping[str, Any],
    target_axis_id: str,
) -> str:
    """Resolve the exact current target instead of trusting its display id."""

    snapshot_id = next_action.get("portfolio_snapshot_id")
    snapshot = (
        None
        if type(snapshot_id) is not str
        else index.get("portfolio-snapshot", snapshot_id)
    )
    axes = None if snapshot is None else snapshot.payload.get("axes")
    matches = (
        ()
        if not isinstance(axes, list)
        else tuple(
            axis
            for axis in axes
            if isinstance(axis, Mapping)
            and axis.get("axis_id") == target_axis_id
        )
    )
    identity = None if len(matches) != 1 else matches[0].get("axis_identity")
    digest = (
        "" if type(identity) is not str else identity.removeprefix("axis:")
    )
    if (
        snapshot is None
        or snapshot.subject != f"Mission:{mission_id}"
        or snapshot.status != "current"
        or snapshot.payload.get("mission_id") != mission_id
        or len(matches) != 1
        or type(identity) is not str
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ReplayProjectionError(
            "Portfolio Decision target-axis projection is malformed or ambiguous"
        )
    return identity


def validate_decision_selection(
    index: LocalIndex,
    *,
    mission_id: str,
    next_action: Mapping[str, Any],
    replay_obligation_ids: Sequence[str],
    action: str,
    target_axis_id: str,
    work_actions: frozenset[str],
) -> dict[str, Any] | None:
    """Validate one Decision against the current highest-priority queue."""

    current_heads = obligation_heads(index, mission_id=mission_id)
    pending_pairs = tuple(
        (obligation, head)
        for obligation, head in current_heads
        if head.status == ReplayObligationStatus.PENDING.value
    )
    constraints = constraints_for_pending_from_index(
        index,
        tuple(obligation for obligation, _head in pending_pairs),
    )
    projected = {
        name: next_action.get(name)
        for name in ("pending_replay_obligation_ids", "required_replay_priority")
        if next_action.get(name) is not None
    }
    if projected != (constraints or {}):
        raise ReplayTransitionError(
            "Portfolio Decision replay scheduler authority is absent or stale"
        )
    pending = set(
        () if constraints is None else constraints["pending_replay_obligation_ids"]
    )
    selected_ids = tuple(replay_obligation_ids)
    if (
        selected_ids != tuple(sorted(set(selected_ids)))
        or any(type(item) is not str for item in selected_ids)
    ):
        raise ReplayTransitionError(
            "Portfolio Decision replay binding is not sorted and unique"
        )
    selected = set(selected_ids)
    diagnosis_id = next_action.get("study_diagnosis_id")
    diagnosis = (
        None
        if not isinstance(diagnosis_id, str)
        else index.get("study-diagnosis", diagnosis_id)
    )
    diagnosis_cleanup = (
        action in {"preserve", "prune"}
        and not selected
        and diagnosis is not None
        and diagnosis.payload.get("mission_id") == mission_id
        and diagnosis.payload.get("portfolio_axis_id") == target_axis_id
        and diagnosis.payload.get("portfolio_snapshot_id")
        == next_action.get("portfolio_snapshot_id")
    )
    if not selected.issubset(pending):
        raise ReplayTransitionError(
            "Portfolio Decision names a non-pending replay obligation"
        )
    if constraints is not None:
        priority = ReplayPriority(constraints["required_replay_priority"])
        if diagnosis_cleanup:
            pass
        elif selected and action in {*work_actions, "revise_protocol"}:
            pass
        elif selected:
            raise ReplayTransitionError(
                "pending replay permits only bound scientific work"
            )
        elif priority is ReplayPriority.P0 and action in work_actions:
            raise ReplayTransitionError(
                "scientific work cannot bypass the highest-priority replay queue"
            )
        elif priority is ReplayPriority.P0 and action != "new_mechanism":
            raise ReplayTransitionError(
                "pending replay permits only bound work or a new-mechanism bridge"
            )
        elif priority is ReplayPriority.P1 and (
            action in work_actions
            or action in {"new_mechanism", "preserve", "prune"}
        ):
            target_identity = _decision_target_axis_identity(
                index,
                mission_id=mission_id,
                next_action=next_action,
                target_axis_id=target_axis_id,
            )
            affected_identities = {
                _obligation_affected_axis_identity(index, obligation)
                for obligation, _head in pending_pairs
                if obligation.identity in pending
            }
            if target_identity in affected_identities:
                raise ReplayTransitionError(
                    "pending P1 replay blocks unbound work on its affected axis"
                )
        elif priority is ReplayPriority.P1:
            raise ReplayTransitionError(
                "pending P1 replay permits only exact bound work or unrelated "
                "bounded forest work"
            )
    elif selected:
        raise ReplayTransitionError(
            "Portfolio Decision replay binding lacks scheduler authority"
        )
    return constraints


def validate_replay_review_basis(
    *,
    constraints: Mapping[str, Any] | None,
    selected_obligation_ids: Sequence[str],
    review_basis: Collection[tuple[str, str]],
) -> None:
    """Require bounded review of the authenticated highest-priority queue.

    A selected replay must be cited exactly.  When the highest-priority queue
    is deliberately not selected, a real quant-team review must still cite at
    least one currently exposed obligation.  This prevents silent starvation
    while leaving the review free to choose higher-value unrelated work.
    """

    selected = tuple(selected_obligation_ids)
    if selected:
        if any(
            ("historical-replay-obligation", obligation_id) not in review_basis
            for obligation_id in selected
        ):
            raise ReplayTransitionError(
                "quant-team review omits its selected replay-obligation basis"
            )
        return
    if constraints is None:
        return
    pending = constraints.get("pending_replay_obligation_ids")
    if (
        not isinstance(pending, list)
        or not pending
        or pending != sorted(set(pending))
        or any(type(item) is not str for item in pending)
    ):
        raise ReplayProjectionError(
            "replay scheduler review queue is malformed"
        )
    if not any(
        ("historical-replay-obligation", obligation_id) in review_basis
        for obligation_id in pending
    ):
        raise ReplayTransitionError(
            "quant-team review omits the highest-priority replay opportunity"
        )


def require_study_pending(
    index: LocalIndex,
    *,
    mission_id: str,
    decision_payload: Mapping[str, Any],
    next_action: Mapping[str, Any],
) -> tuple[str, ...]:
    raw = decision_payload.get("replay_obligation_ids", [])
    projected = next_action.get("replay_obligation_ids", [])
    if (
        not isinstance(raw, list)
        or raw != sorted(set(raw))
        or raw != projected
        or any(type(item) is not str for item in raw)
    ):
        raise ReplayTransitionError(
            "Study replay obligations differ from its accepted Decision"
        )
    heads = {
        obligation.identity: head
        for obligation, head in obligation_heads(index, mission_id=mission_id)
    }
    if any(
        item not in heads
        or heads[item].status != ReplayObligationStatus.PENDING.value
        for item in raw
    ):
        raise ReplayTransitionError("Study replay obligation is no longer pending")
    return tuple(raw)


def _is_bound_lower_priority_family_control(
    index: LocalIndex,
    *,
    study_record: IndexRecord,
    batch_record: IndexRecord | None,
    executable_id: str,
    reference_executable_id: str,
    selected_obligation_ids: tuple[str, ...],
    matched_obligation_id: str,
    heads: Mapping[
        str,
        tuple[HistoricalReplayObligation, IndexRecord],
    ],
) -> bool:
    """Recognize a preregistered P1 control required by one selected P0 family."""

    if len(selected_obligation_ids) != 1 or batch_record is None:
        return False
    proposal = study_record.payload.get("semantic_proposal")
    if not isinstance(proposal, Mapping) or not any(
        name in proposal
        for name in (
            "concurrent_family",
            "historical_family_authority_id",
            "historical_family_identity",
        )
    ):
        return False
    from axiom_rift.research.historical_family_binding import (
        HistoricalFamilyBindingError,
        historical_family_authority_from_payload,
        historical_family_from_manifest,
    )

    authority_id = proposal.get("historical_family_authority_id")
    authority_record = (
        None
        if not isinstance(authority_id, str)
        else index.get("historical-family-authority", authority_id)
    )
    try:
        if authority_record is None:
            raise HistoricalFamilyBindingError(
                "historical family authority is absent"
            )
        authority = historical_family_authority_from_payload(
            authority_record.payload
        )
        proposed_family = historical_family_from_manifest(
            proposal.get("concurrent_family")
        )
    except HistoricalFamilyBindingError as exc:
        raise ReplayProjectionError(
            "replay family control authority is malformed"
        ) from exc
    selected_id = selected_obligation_ids[0]
    selected_pair = heads.get(selected_id)
    control_pair = heads.get(matched_obligation_id)
    if selected_pair is None or control_pair is None:
        raise ReplayProjectionError(
            "replay family control obligation projection is incomplete"
        )
    selected, selected_head = selected_pair
    control, control_head = control_pair
    batch_spec = batch_record.payload.get("spec")
    profile = (
        None
        if not isinstance(batch_spec, Mapping)
        else batch_spec.get("acceptance_profile")
    )
    concurrent = (
        None
        if not isinstance(profile, Mapping)
        else profile.get("concurrent_family")
    )
    member_ids = (
        None
        if not isinstance(concurrent, Mapping)
        else concurrent.get("executable_ids")
    )
    references = tuple(
        member.historical_reference_executable_id
        for member in authority.family.members
    )
    return bool(
        authority_record.record_id == authority.identity == authority_id
        and authority_record.status == "accepted"
        and authority_record.subject
        == f"ReplayObligation:{selected_id}"
        and authority.replay_obligation_id == selected_id
        and authority.family == proposed_family
        and proposal.get("historical_family_identity")
        == authority.family.identity
        and proposal.get("historical_obligation_id") == selected_id
        and proposal.get("original_study_id")
        == authority.family.original_study_id
        and batch_record.subject == f"Study:{study_record.record_id}"
        and isinstance(profile, Mapping)
        and profile.get("historical_family_authority_id") == authority.identity
        and profile.get("historical_family_identity") == authority.family.identity
        and isinstance(concurrent, Mapping)
        and concurrent.get("schema") == "concurrent_family_manifest.v1"
        and isinstance(member_ids, list)
        and all(type(member_id) is str for member_id in member_ids)
        and member_ids == sorted(set(member_ids))
        and concurrent.get("family_size") == len(member_ids)
        and executable_id in member_ids
        and selected.governing_mission_id == control.governing_mission_id
        == study_record.payload.get("mission_id")
        and selected.original_study_id == control.original_study_id
        == authority.family.original_study_id
        and selected.original_executable_id
        == authority.family.target_historical_executable_id
        and reference_executable_id in references
        and reference_executable_id
        != authority.family.target_historical_executable_id
        and control.original_executable_id == reference_executable_id
        and selected.claim_ids == control.claim_ids
        and selected.criterion_ids == control.criterion_ids
        and selected_head.status == ReplayObligationStatus.PENDING.value
        and control_head.status == ReplayObligationStatus.PENDING.value
        and effective_replay_priority(index, selected) is ReplayPriority.P0
        and effective_replay_priority(index, control) is ReplayPriority.P1
    )


def prepare_execution_progress(
    index: LocalIndex,
    *,
    study_record: IndexRecord,
    batch_record: IndexRecord | None = None,
    executable_id: str,
    executable_payload: Mapping[str, Any],
) -> tuple[tuple[str, ...], list[IndexRecord]]:
    """Bind one new trial to at most one exact pending replay obligation.

    A replay Study may contain several legacy Executables.  Registering its
    first trial therefore cannot advance the whole Study-level obligation
    set.  The new trial advances only the obligation whose immutable original
    Executable identity occurs in the actual trial manifest.  A non-matching
    trial is ordinary Study work and is a no-op here; a manifest matching two
    obligations is ambiguous and fails closed.
    """

    obligation_ids = tuple(study_record.payload.get("replay_obligation_ids", ()))
    if not obligation_ids:
        return (), []
    if (
        list(obligation_ids) != sorted(set(obligation_ids))
        or any(type(item) is not str for item in obligation_ids)
    ):
        raise ReplayProjectionError("Study replay obligation projection is malformed")
    mission_id = study_record.payload.get("mission_id")
    if not isinstance(mission_id, str):
        raise ReplayProjectionError("Study replay Mission is malformed")
    heads = {
        obligation.identity: (obligation, head)
        for obligation, head in obligation_heads(index, mission_id=mission_id)
    }
    if any(obligation_id not in heads for obligation_id in obligation_ids):
        raise ReplayProjectionError("Study replay obligation projection is incomplete")
    reference = typed_replay_reference_executable_id(executable_payload)
    global_matches = tuple(
        obligation_id
        for obligation_id, (obligation, _head) in heads.items()
        if obligation.original_executable_id == reference
    )
    if len(global_matches) > 1:
        raise ReplayTransitionError(
            "trial manifest ambiguously matches multiple replay obligations"
        )
    if not global_matches:
        return (), []
    obligation_id = global_matches[0]
    if obligation_id not in obligation_ids:
        if _is_bound_lower_priority_family_control(
            index,
            study_record=study_record,
            batch_record=batch_record,
            executable_id=executable_id,
            reference_executable_id=reference,
            selected_obligation_ids=obligation_ids,
            matched_obligation_id=obligation_id,
            heads=heads,
        ):
            return (), []
        raise ReplayTransitionError(
            "trial manifest references an unselected Mission replay obligation"
        )
    _, head = heads[obligation_id]
    existing_trial = index.get("trial", executable_id)
    if existing_trial is not None and existing_trial.payload.get(
        "study_id"
    ) != study_record.record_id:
        raise ReplayTransitionError(
            "matching replay trial identity belongs to another Study"
        )
    if head.status == ReplayObligationStatus.IN_PROGRESS.value:
        prior_binding = head.payload.get("binding")
        if (
            isinstance(prior_binding, dict)
            and prior_binding.get("replay_study_id") == study_record.record_id
            and prior_binding.get("replay_executable_id") == executable_id
        ):
            return (), []
        raise ReplayTransitionError(
            "matching replay obligation is already bound to another trial or Study"
        )
    if existing_trial is not None:
        raise ReplayProjectionError(
            "matching replay trial exists without its obligation progress"
        )
    if head.status != ReplayObligationStatus.PENDING.value:
        raise ReplayTransitionError("matching replay obligation is no longer pending")
    try:
        binding = ReplayExecutionBinding(
            obligation_ids=(obligation_id,),
            portfolio_decision_id=study_record.payload["portfolio_decision_id"],
            replay_study_id=study_record.record_id,
            replay_executable_id=executable_id,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayProjectionError("Study replay binding is malformed") from exc
    payload = {
        "binding": binding.to_identity_payload(),
        "obligation_id": obligation_id,
        "prior_status": ReplayObligationStatus.PENDING.value,
    }
    record_id = "historical-replay-progress:" + canonical_digest(
        domain="historical-replay-obligation-progress", payload=payload
    )
    return (obligation_id,), [
        _record(
            kind="historical-replay-obligation-progress",
            record_id=record_id,
            subject=f"Mission:{mission_id}",
            status=ReplayObligationStatus.IN_PROGRESS.value,
            fingerprint=binding.identity,
            payload=payload,
            event_stream=obligation_stream(obligation_id),
            event_sequence=(head.event_sequence or 0) + 1,
        )
    ]


def require_study_execution_complete(
    index: LocalIndex,
    *,
    mission_id: str,
    study: IndexRecord,
) -> tuple[str, ...]:
    """Require every replay obligation to have its own exact Study trial."""

    obligation_ids = study.payload.get("replay_obligation_ids", [])
    if not obligation_ids:
        return ()
    if not isinstance(mission_id, str):
        raise ReplayProjectionError("replay Study Mission projection is malformed")
    if (
        not isinstance(obligation_ids, list)
        or obligation_ids != sorted(set(obligation_ids))
        or any(type(item) is not str for item in obligation_ids)
    ):
        raise ReplayProjectionError("replay Study obligation projection is malformed")
    heads = {
        obligation.identity: (obligation, head)
        for obligation, head in obligation_heads(index, mission_id=mission_id)
    }
    for obligation_id in obligation_ids:
        pair = heads.get(obligation_id)
        if pair is None:
            raise ReplayProjectionError(
                "replay Study obligation projection is incomplete"
            )
        obligation, head = pair
        binding = head.payload.get("binding")
        executable_id = (
            None if not isinstance(binding, dict) else binding.get("replay_executable_id")
        )
        trial = (
            None
            if not isinstance(executable_id, str)
            else index.get("trial", executable_id)
        )
        if (
            head.status != ReplayObligationStatus.IN_PROGRESS.value
            or not isinstance(binding, dict)
            or binding.get("obligation_ids") != [obligation_id]
            or binding.get("portfolio_decision_id")
            != study.payload.get("portfolio_decision_id")
            or binding.get("replay_study_id") != study.record_id
            or trial is None
            or trial.payload.get("study_id") != study.record_id
            or trial.payload.get("replay_obligation_ids") != [obligation_id]
            or typed_replay_reference_executable_id(
                trial.payload.get("executable", {})
            )
            != obligation.original_executable_id
        ):
            raise ReplayTransitionError(
                "replay Study does not have one exact trial per obligation"
            )
    return tuple(obligation_ids)


def require_diagnosed_replay(
    index: LocalIndex,
    *,
    mission_id: str,
    study: IndexRecord,
    diagnosis_id: str,
) -> tuple[str, ...]:
    obligation_ids = require_study_execution_complete(
        index,
        mission_id=mission_id,
        study=study,
    )
    if not diagnosis_id.startswith("diagnosis:"):
        raise ReplayProjectionError("Study diagnosis identity is malformed")
    return obligation_ids


def derive_obligation_from_record(
    index: LocalIndex,
    *,
    adjudication_record_id: str,
    mission_id: str,
) -> HistoricalReplayObligation:
    adjudication = index.get(
        "historical-scientific-adjudication", adjudication_record_id
    )
    completion = (
        None
        if adjudication is None
        else index.get(
            "job-completed", adjudication.payload.get("completion_record_id", "")
        )
    )
    declaration = (
        None
        if completion is None
        else index.get("job-declared", completion.payload.get("job_id", ""))
    )
    mission_open = index.get("mission-open", mission_id)
    if (
        adjudication is None
        or adjudication.status != "replay_required"
        or completion is None
        or declaration is None
        or mission_open is None
        or adjudication.authority_sequence is None
        or mission_open.authority_sequence is None
        or adjudication.authority_sequence <= mission_open.authority_sequence
    ):
        raise ReplayTransitionError(
            "historical replay adjudication is unavailable for this Mission"
        )
    try:
        return derive_historical_replay_obligation(
            governing_mission_id=mission_id,
            historical_adjudication_id=adjudication.record_id,
            adjudication_payload=adjudication.payload,
        )
    except ValueError as exc:
        raise ReplayProjectionError(
            "historical replay adjudication cannot derive its obligation"
        ) from exc


def payload_contains_exact_value(value: object, target: str) -> bool:
    if value == target:
        return True
    if isinstance(value, Mapping):
        return any(payload_contains_exact_value(child, target) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(payload_contains_exact_value(child, target) for child in value)
    return False


def typed_replay_reference_executable_id(
    executable_payload: Mapping[str, Any],
) -> str | None:
    """Read the sole typed historical reference from a prospective Executable."""

    from axiom_rift.research.historical_family_binding import (
        HistoricalFamilyBindingError,
        historical_reference_executable_id_from_manifest,
    )

    try:
        return historical_reference_executable_id_from_manifest(
            dict(executable_payload)
        )
    except HistoricalFamilyBindingError as exc:
        raise ReplayTransitionError(str(exc)) from exc


def replay_evidence_record_ids(
    *,
    diagnosis: IndexRecord,
    close_record: IndexRecord,
    trial: IndexRecord,
) -> tuple[str, ...]:
    basis = diagnosis.payload.get("evidence_basis")
    if not isinstance(basis, list) or any(
        not isinstance(item, dict)
        or set(item) != {"kind", "record_id"}
        or not isinstance(item.get("record_id"), str)
        for item in basis
    ):
        raise ReplayProjectionError(
            "replay Study diagnosis evidence basis is malformed"
        )
    return tuple(
        sorted(
            {
                diagnosis.record_id,
                close_record.record_id,
                trial.record_id,
                *(item["record_id"] for item in basis),
            }
        )
    )


_ADJUDICATED_MULTIPLICITY_FIELDS = {
    "adjusted_pvalue_ppm",
    "alpha_ppm",
    "criterion_id",
    "family_id",
    "family_size",
    "method",
    "raw_pvalue_ppm",
}
_BONFERRONI_CONCURRENT_FAMILY_METHOD = "bonferroni_concurrent_family.v1"
_SYNCHRONIZED_MAX_FAMILYWISE_METHOD = (
    "synchronized_max_moving_block_familywise.v1"
)
_BATCH_SELECTION_MULTIPLICITY_CRITERION = SELECTION_CRITERION_ID
_MULTIPLICITY_REGISTRATION_FIELDS = {
    "alpha_ppm",
    "criterion_id",
    "family_id",
    "family_registration_hash",
    "family_size",
    "member_id",
    "method",
    "ordered_member_ids",
}
def _is_executable_identity(value: object) -> bool:
    return (
        type(value) is str
        and value.startswith("executable:")
        and len(value) == len("executable:") + 64
        and all(
            character in "0123456789abcdef"
            for character in value.removeprefix("executable:")
        )
    )


def _selection_registration_from_completion(
    index: LocalIndex,
    *,
    completion: IndexRecord,
    declaration: IndexRecord,
    scientific: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Recover the exact Writer-validated E01 registration.

    New completions project the validator-derived registration directly.
    Historical v2 completions predate that projection, so recover the same
    immutable registration from the exact content-addressed validation plan
    that Writer bound as both a Job input and a durable completion output.
    A malformed projected field never downgrades to the historical route.
    """

    registrations = scientific.get("multiplicity_registrations")
    if registrations is None:
        spec = declaration.payload.get("spec")
        binding = (
            None if not isinstance(spec, Mapping) else spec.get("scientific_binding")
        )
        plan_hash = (
            None if not isinstance(binding, Mapping) else binding.get("validation_plan_hash")
        )
        outputs = completion.payload.get("outputs")
        output_classes = completion.payload.get("output_classes")
        if (
            type(plan_hash) is not str
            or len(plan_hash) != 64
            or any(character not in "0123456789abcdef" for character in plan_hash)
            or scientific.get("validation_plan_hash") != plan_hash
            or not isinstance(outputs, Mapping)
            or not isinstance(output_classes, Mapping)
        ):
            raise ReplayTransitionError(
                "scientific replay selection registration lacks its exact plan"
            )
        plan_outputs = tuple(
            output_name
            for output_name, output_hash in outputs.items()
            if output_hash == plan_hash
            and output_classes.get(output_name) == "durable_evidence"
        )
        if len(plan_outputs) != 1:
            raise ReplayTransitionError(
                "scientific replay selection registration plan is not one durable output"
            )
        try:
            content = EvidenceStore(index.path.parent / "evidence").read_verified(
                plan_hash
            )
            plan = parse_canonical(content)
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ReplayTransitionError(
                "scientific replay selection registration plan is unavailable"
            ) from exc
        if (
            not isinstance(plan, Mapping)
            or plan.get("schema") != "scientific_validation_plan.v2"
            or plan.get("executable_id")
            != scientific.get("executable_id")
        ):
            raise ReplayTransitionError(
                "scientific replay selection registration plan is malformed"
            )
        profile = plan.get("adjudication_profile")
        registrations = (
            None if not isinstance(profile, Mapping) else profile.get("multiplicity")
        )
    if not isinstance(registrations, list) or any(
        not isinstance(item, Mapping) for item in registrations
    ):
        raise ReplayTransitionError(
            "scientific replay selection registrations are malformed"
        )
    matches = tuple(
        item
        for item in registrations
        if item.get("criterion_id") == _BATCH_SELECTION_MULTIPLICITY_CRITERION
    )
    if len(matches) != 1 or set(matches[0]) != _MULTIPLICITY_REGISTRATION_FIELDS:
        raise ReplayTransitionError(
            "scientific replay selection registration is not exact"
        )
    return matches[0]


def _require_projected_multiplicity_batch_binding(
    *,
    scientific: Mapping[str, Any],
    registration: Mapping[str, Any],
    batch_id: str,
    concurrent_family: Mapping[str, Any],
    ordered_member_ids: tuple[str, ...],
    executable_id: str,
    required: bool,
) -> None:
    """Recompute one Writer-derived durable E01-to-Batch binding.

    Historical completions predate this additive projection and are rebuilt
    from their independent Batch, plan, validator and completion records.
    Completions declared under the current source-authority boundary must
    carry the durable binding; when present, every historical record must
    still match it byte-for-byte.
    """

    projected = scientific.get("multiplicity_batch_binding")
    if projected is None:
        if required:
            raise ReplayTransitionError(
                "scientific replay completion lacks its durable Batch binding"
            )
        return
    try:
        expected = build_multiplicity_batch_binding(
            batch_id=batch_id,
            concurrent_family=concurrent_family,
            selection_registration=registration,
            executable_id=executable_id,
            ordered_member_ids=ordered_member_ids,
        )
    except KeyError as exc:
        raise ReplayTransitionError(
            "scientific replay selection registration is malformed"
        ) from exc
    if (
        not isinstance(projected, Mapping)
        or set(projected) != MULTIPLICITY_BATCH_BINDING_FIELDS
        or dict(projected) != expected
    ):
        raise ReplayTransitionError(
            "scientific replay durable Batch binding differs from its exact "
            "Batch, subject, or validator registration"
        )


def _validated_adjudicated_multiplicity(
    adjudication: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    criteria = adjudication.get("criteria")
    if not isinstance(criteria, list) or any(
        not isinstance(item, Mapping) for item in criteria
    ):
        raise ReplayTransitionError(
            "scientific replay multiplicity criteria are malformed"
        )
    multiplicity_items = tuple(
        item for item in criteria if item.get("decision_role") == "multiplicity"
    )
    multiplicity_criteria = {
        item.get("criterion_id"): item
        for item in multiplicity_items
    }
    if (
        any(
            type(item.get("criterion_id")) is not str
            or not item["criterion_id"]
            or not item["criterion_id"].isascii()
            for item in multiplicity_items
        )
        or len(multiplicity_criteria) != len(multiplicity_items)
    ):
        raise ReplayTransitionError(
            "scientific replay multiplicity criterion identity is malformed"
        )
    raw_rows = adjudication.get("multiplicity", [])
    if not multiplicity_criteria:
        if raw_rows not in (None, []):
            raise ReplayTransitionError(
                "scientific replay has undeclared multiplicity results"
            )
        return ()
    if not isinstance(raw_rows, list) or any(
        not isinstance(item, Mapping)
        or set(item) != _ADJUDICATED_MULTIPLICITY_FIELDS
        for item in raw_rows
    ):
        raise ReplayTransitionError(
            "scientific replay multiplicity results are malformed"
        )
    rows = tuple(raw_rows)
    by_criterion = {item.get("criterion_id"): item for item in rows}
    if (
        None in by_criterion
        or len(by_criterion) != len(rows)
        or set(by_criterion) != set(multiplicity_criteria)
    ):
        raise ReplayTransitionError(
            "scientific replay multiplicity inventory is incomplete"
        )
    for criterion_id, row in by_criterion.items():
        family_id = row.get("family_id")
        family_size = row.get("family_size")
        raw_pvalue = row.get("raw_pvalue_ppm")
        adjusted_pvalue = row.get("adjusted_pvalue_ppm")
        alpha_ppm = row.get("alpha_ppm")
        method = row.get("method")
        criterion = multiplicity_criteria[criterion_id]
        if (
            type(family_id) is not str
            or not family_id
            or not family_id.isascii()
            or type(family_size) is not int
            or family_size < 1
            or type(raw_pvalue) is not int
            or type(adjusted_pvalue) is not int
            or type(alpha_ppm) is not int
            or not 0 <= raw_pvalue <= adjusted_pvalue <= 1_000_000
            or not 1 <= alpha_ppm <= 1_000_000
            or criterion.get("operator") != "le"
            or criterion.get("threshold") != alpha_ppm
            or criterion.get("value") != adjusted_pvalue
        ):
            raise ReplayTransitionError(
                "scientific replay multiplicity adjustment is inconsistent"
            )
        if method == _BONFERRONI_CONCURRENT_FAMILY_METHOD:
            if adjusted_pvalue != min(1_000_000, raw_pvalue * family_size):
                raise ReplayTransitionError(
                    "scientific replay Bonferroni adjustment is inconsistent"
                )
        elif method != _SYNCHRONIZED_MAX_FAMILYWISE_METHOD:
            raise ReplayTransitionError(
                "scientific replay multiplicity method is not registered"
            )
    return rows


def _require_multiplicity_batch_binding(
    index: LocalIndex,
    *,
    satisfaction: ReplaySatisfaction,
    diagnosis: IndexRecord,
    target_completion: IndexRecord,
    target_declaration: IndexRecord,
    adjudication: Mapping[str, Any],
) -> None:
    """Bind Batch-wide selection inference to its exact concurrent family.

    Multiplicity families are criterion scoped.  E01 is the selection family
    over every Executable in the preregistered Batch.  Other criteria can use
    smaller per-Executable control families (D02 is one such family), so their
    family identities and sizes must not be coerced to the Batch manifest.
    """

    target_rows = _validated_adjudicated_multiplicity(adjudication)
    target_selection_rows = tuple(
        row
        for row in target_rows
        if row.get("criterion_id") == _BATCH_SELECTION_MULTIPLICITY_CRITERION
    )
    if not target_selection_rows:
        return
    if len(target_selection_rows) != 1:
        raise ReplayTransitionError(
            "scientific replay selection multiplicity is ambiguous"
        )
    target_selection = target_selection_rows[0]
    basis = diagnosis.payload.get("evidence_basis")
    if not isinstance(basis, list):
        raise ReplayTransitionError(
            "scientific replay multiplicity lacks a diagnosis evidence basis"
        )
    batch_id = target_declaration.payload.get("batch_id")
    if type(batch_id) is not str:
        raise ReplayTransitionError(
            "scientific replay multiplicity Job lacks a Batch binding"
        )
    batch_references = tuple(
        item.get("record_id")
        for item in basis
        if isinstance(item, Mapping) and item.get("kind") == "batch-open"
    )
    if batch_references.count(batch_id) != 1:
        raise ReplayTransitionError(
            "scientific replay multiplicity lacks one exact Batch-open binding"
        )
    batch = index.get("batch-open", batch_id)
    spec = None if batch is None else batch.payload.get("spec")
    profile = None if not isinstance(spec, Mapping) else spec.get("acceptance_profile")
    family = (
        None
        if not isinstance(profile, Mapping)
        else profile.get("concurrent_family")
    )
    if (
        batch is None
        or batch.subject != f"Study:{satisfaction.replay_study_id}"
        or not isinstance(family, Mapping)
        or family.get("schema") != "concurrent_family_manifest.v1"
    ):
        raise ReplayTransitionError(
            "scientific replay multiplicity Batch family is malformed"
        )
    raw_member_ids = family.get("executable_ids")
    family_size = family.get("family_size")
    if (
        not isinstance(raw_member_ids, list)
        or not raw_member_ids
        or any(
            type(item) is not str
            or not item.startswith("executable:")
            or len(item) != len("executable:") + 64
            or any(
                character not in "0123456789abcdef"
                for character in item.removeprefix("executable:")
            )
            for item in raw_member_ids
        )
        or len(set(raw_member_ids)) != len(raw_member_ids)
        or type(family_size) is not int
        or family_size != len(raw_member_ids)
        or satisfaction.replay_executable_id not in raw_member_ids
    ):
        raise ReplayTransitionError(
            "scientific replay multiplicity Batch membership is not exact"
        )
    member_ids = tuple(raw_member_ids)

    for member_id in member_ids:
        trial = index.get("trial", member_id)
        if (
            trial is None
            or trial.payload.get("study_id") != satisfaction.replay_study_id
        ):
            raise ReplayTransitionError(
                "scientific replay Batch member is not bound to its Study"
            )

    completion_references = tuple(
        item.get("record_id")
        for item in basis
        if isinstance(item, Mapping) and item.get("kind") == "job-completed"
    )
    family_completions: dict[str, tuple[IndexRecord, Mapping[str, Any]]] = {}
    for completion_id in completion_references:
        completion = (
            None
            if not isinstance(completion_id, str)
            else index.get("job-completed", completion_id)
        )
        job_id = None if completion is None else completion.payload.get("job_id")
        declaration = (
            None
            if not isinstance(job_id, str)
            else index.get("job-declared", job_id)
        )
        if declaration is None or declaration.payload.get("batch_id") != batch_id:
            continue
        declaration_spec = declaration.payload.get("spec")
        subject = (
            None
            if not isinstance(declaration_spec, Mapping)
            else declaration_spec.get("evidence_subject")
        )
        scientific = (
            None if completion is None else completion.payload.get("scientific")
        )
        member_id = (
            None
            if not isinstance(subject, Mapping)
            else subject.get("id")
        )
        if (
            completion is None
            or completion.status != "success"
            or declaration.payload.get("study_id")
            != satisfaction.replay_study_id
            or not isinstance(subject, Mapping)
            or subject.get("kind") != "Executable"
            or member_id not in member_ids
            or not isinstance(scientific, Mapping)
            or scientific.get("executable_id") != member_id
            or member_id in family_completions
        ):
            raise ReplayTransitionError(
                "scientific replay Batch completion binding is inconsistent"
            )
        family_completions[member_id] = (completion, scientific)
    if set(family_completions) != set(member_ids):
        raise ReplayTransitionError(
            "scientific replay lacks one completion per exact Batch member"
        )
    if family_completions[satisfaction.replay_executable_id][0] != target_completion:
        raise ReplayTransitionError(
            "scientific replay target completion differs from its Batch member"
        )

    close_references = tuple(
        item.get("record_id")
        for item in basis
        if isinstance(item, Mapping) and item.get("kind") == "batch-close"
    )
    matching_closes = tuple(
        close
        for record_id in close_references
        if isinstance(record_id, str)
        for close in (index.get("batch-close", record_id),)
        if close is not None and close.subject == f"Batch:{batch_id}"
    )
    if (
        len(matching_closes) != 1
        or matching_closes[0].status != "completed"
        or matching_closes[0].payload.get("outcome") != "completed"
    ):
        raise ReplayTransitionError(
            "scientific replay multiplicity Batch is not exactly completed"
        )
    batch_close = matching_closes[0]

    observations: list[ReplaySelectionFamilyObservation] = []
    selection_family_bindings: set[tuple[object, ...]] = set()
    for member_id in sorted(family_completions):
        completion, scientific = family_completions[member_id]
        member_adjudication = scientific.get("adjudication")
        if not isinstance(member_adjudication, Mapping):
            raise ReplayTransitionError(
                "scientific replay Batch member lacks an adjudication"
            )
        rows = _validated_adjudicated_multiplicity(member_adjudication)
        selection_rows = tuple(
            row
            for row in rows
            if row.get("criterion_id")
            == _BATCH_SELECTION_MULTIPLICITY_CRITERION
        )
        if len(selection_rows) != 1:
            raise ReplayTransitionError(
                "scientific replay selection multiplicity is ambiguous"
            )
        selection = selection_rows[0]
        job_id = completion.payload.get("job_id")
        declaration = (
            None
            if not isinstance(job_id, str)
            else index.get("job-declared", job_id)
        )
        if declaration is None:
            raise ReplayTransitionError(
                "scientific replay selection registration lacks its Job declaration"
            )
        registration = _selection_registration_from_completion(
            index,
            completion=completion,
            declaration=declaration,
            scientific=scientific,
        )
        _require_projected_multiplicity_batch_binding(
            scientific=scientific,
            registration=registration,
            batch_id=batch_id,
            concurrent_family=family,
            ordered_member_ids=member_ids,
            executable_id=member_id,
            required=(
                "source_closure_authority" in declaration.payload
            ),
        )
        registered_member_ids = registration.get("ordered_member_ids")
        if (
            registration.get("alpha_ppm") != selection.get("alpha_ppm")
            or registration.get("family_id") != selection.get("family_id")
            or registration.get("family_size") != selection.get("family_size")
            or registration.get("method") != selection.get("method")
            or not isinstance(registered_member_ids, list)
        ):
            raise ReplayTransitionError(
                "scientific replay selection registration is unrelated to its "
                "adjudicated Batch member"
            )
        try:
            observation = ReplaySelectionFamilyObservation(
                executable_id=member_id,
                completion_record_id=completion.record_id,
                family_id=selection["family_id"],
                family_size=selection["family_size"],
                method=selection["method"],
                alpha_ppm=selection["alpha_ppm"],
                registered_member_id=registration["member_id"],
                ordered_member_ids=tuple(registered_member_ids),
                family_registration_hash=registration[
                    "family_registration_hash"
                ],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ReplayTransitionError(
                "scientific replay selection registration is malformed"
            ) from exc
        observations.append(observation)
        selection_family_bindings.add(
            (
                selection.get("family_id"),
                selection.get("family_size"),
                selection.get("method"),
                selection.get("alpha_ppm"),
            )
        )

    if any(item.family_size != family_size for item in observations):
        raise ReplayMultiplicityBindingError(
            ReplayMultiplicityBindingDefect(
                code=(
                    ReplayMultiplicityDefectCode.SELECTION_FAMILY_SIZE_MISMATCH
                ),
                criterion_id=_BATCH_SELECTION_MULTIPLICITY_CRITERION,
                batch_open_record_id=batch_id,
                batch_close_record_id=batch_close.record_id,
                expected_executable_ids=member_ids,
                expected_family_size=family_size,
                observations=tuple(observations),
            )
        )
    expected_selection_binding = (
        target_selection.get("family_id"),
        target_selection.get("family_size"),
        target_selection.get("method"),
        target_selection.get("alpha_ppm"),
    )
    if selection_family_bindings != {expected_selection_binding}:
        raise ReplayMultiplicityBindingError(
            ReplayMultiplicityBindingDefect(
                code=(
                    ReplayMultiplicityDefectCode.SELECTION_FAMILY_DISAGREEMENT
                ),
                criterion_id=_BATCH_SELECTION_MULTIPLICITY_CRITERION,
                batch_open_record_id=batch_id,
                batch_close_record_id=batch_close.record_id,
                expected_executable_ids=member_ids,
                expected_family_size=family_size,
                observations=tuple(observations),
            )
        )

    expected_ordered_member_ids = member_ids
    expected_member_set = set(member_ids)
    if any(
        item.registered_member_id != item.executable_id
        or any(
            not _is_executable_identity(registered_member_id)
            for registered_member_id in item.ordered_member_ids
        )
        for item in observations
    ):
        raise ReplayTransitionError(
            "scientific replay selection registration is unrelated to its "
            "exact Batch membership"
        )
    if any(
        set(item.ordered_member_ids) != expected_member_set
        for item in observations
    ):
        raise ReplayMultiplicityBindingError(
            ReplayMultiplicityBindingDefect(
                code=(
                    ReplayMultiplicityDefectCode.SELECTION_FAMILY_MEMBERSHIP_MISMATCH
                ),
                criterion_id=_BATCH_SELECTION_MULTIPLICITY_CRITERION,
                batch_open_record_id=batch_id,
                batch_close_record_id=batch_close.record_id,
                expected_executable_ids=member_ids,
                expected_family_size=family_size,
                observations=tuple(observations),
            )
        )
    if any(
        item.ordered_member_ids != expected_ordered_member_ids
        for item in observations
    ):
        raise _HistoricalRegistrationOrderDiagnostic(
            expected_ordered_member_ids=expected_ordered_member_ids,
            observations=tuple(observations),
        )


def _require_scientific_satisfaction_evidence(
    index: LocalIndex,
    *,
    obligation: HistoricalReplayObligation,
    satisfaction: ReplaySatisfaction,
    diagnosis: IndexRecord,
    revalidate_current_multiplicity_binding: bool,
) -> None:
    """Recompute the admissibility of a scientific replay resolution.

    The completion was derived by Writer at Job close, but resolution is a
    separate authority boundary.  Rechecking its exact recorded-validator,
    subject, historical-definition, and criterion-state bindings prevents a
    caller-created ``ReplaySatisfaction`` from becoming a capability.

    The validator identity is intentionally read from the immutable Job
    declaration and cross-checked against its completion.  Requiring the
    current source tree's validator identity would make a code upgrade revoke
    already validated historical evidence and deadlock every later axis read.
    """

    basis = diagnosis.payload.get("evidence_basis")
    completion_ids = (
        ()
        if not isinstance(basis, list)
        else tuple(
            item.get("record_id")
            for item in basis
            if isinstance(item, Mapping) and item.get("kind") == "job-completed"
        )
    )
    matches: list[tuple[IndexRecord, IndexRecord, Mapping[str, Any]]] = []
    for completion_id in completion_ids:
        completion = (
            None
            if not isinstance(completion_id, str)
            else index.get("job-completed", completion_id)
        )
        scientific = (
            None if completion is None else completion.payload.get("scientific")
        )
        job_id = None if completion is None else completion.payload.get("job_id")
        declaration = (
            None
            if not isinstance(job_id, str)
            else index.get("job-declared", job_id)
        )
        spec = None if declaration is None else declaration.payload.get("spec")
        subject = None if not isinstance(spec, Mapping) else spec.get("evidence_subject")
        if (
            completion is not None
            and declaration is not None
            and isinstance(scientific, Mapping)
            and isinstance(subject, Mapping)
            and subject.get("kind") == "Executable"
            and subject.get("id") == satisfaction.replay_executable_id
            and scientific.get("executable_id") == satisfaction.replay_executable_id
        ):
            matches.append((completion, declaration, scientific))
    if len(matches) != 1:
        raise ReplayTransitionError(
            "scientific replay satisfaction lacks one exact subject completion"
        )
    completion, declaration, scientific = matches[0]
    spec = declaration.payload.get("spec")
    binding = None if not isinstance(spec, Mapping) else spec.get("scientific_binding")
    trace = scientific.get("validation_trace")
    adjudication = scientific.get("adjudication")
    recorded_validator_id = (
        None if not isinstance(binding, Mapping) else binding.get("validator_id")
    )
    historical = index.get(
        "historical-scientific-adjudication",
        obligation.historical_adjudication_id,
    )
    historical_adjudication = (
        None if historical is None else historical.payload.get("adjudication")
    )
    if (
        completion.status != "success"
        or declaration.payload.get("study_id") != satisfaction.replay_study_id
        or not isinstance(binding, Mapping)
        or type(recorded_validator_id) is not str
        or not recorded_validator_id.startswith("validator:")
        or len(recorded_validator_id.removeprefix("validator:")) != 64
        or any(
            character not in "0123456789abcdef"
            for character in recorded_validator_id.removeprefix("validator:")
        )
        or scientific.get("validator_id") != recorded_validator_id
        or scientific.get("validation_plan_hash")
        != binding.get("validation_plan_hash")
        or scientific.get("scientific_eligible") is not True
        or scientific.get("candidate_eligible") is not False
        or not isinstance(trace, Mapping)
        or trace.get("validator_id") != recorded_validator_id
        or type(trace.get("declared_artifact_count")) is not int
        or trace.get("declared_artifact_count", 0) <= 0
        or trace.get("declared_artifact_count")
        != trace.get("opened_artifact_count")
        or not isinstance(adjudication, Mapping)
        or adjudication.get("schema") != "scientific_adjudication.v1"
        or adjudication.get("evaluable") is not True
        or adjudication.get("invalid_metrics") != []
        or not isinstance(historical_adjudication, Mapping)
    ):
        raise ReplayTransitionError(
            "scientific replay satisfaction lacks active complete V2 evidence"
        )
    observed_items = adjudication.get("criteria")
    expected_items = historical_adjudication.get("criteria")
    if (
        not isinstance(observed_items, list)
        or not isinstance(expected_items, list)
        or any(not isinstance(item, Mapping) for item in observed_items)
        or any(not isinstance(item, Mapping) for item in expected_items)
    ):
        raise ReplayTransitionError(
            "scientific replay satisfaction criterion evidence is malformed"
        )
    observed = {item.get("criterion_id"): item for item in observed_items}
    expected = {item.get("criterion_id"): item for item in expected_items}
    criterion_ids = set(satisfaction.satisfied_criterion_ids)
    if (
        None in observed
        or None in expected
        or len(observed) != len(observed_items)
        or len(expected) != len(expected_items)
        or set(observed) != criterion_ids
        or set(expected) != criterion_ids
    ):
        raise ReplayTransitionError(
            "scientific replay satisfaction criterion inventory differs"
        )
    definition_fields = (
        "claim_id",
        "criterion_id",
        "decision_role",
        "metric",
        "operator",
        "threshold",
    )
    for criterion_id in sorted(criterion_ids):
        item = observed[criterion_id]
        prior = expected[criterion_id]
        comparison = item.get("comparison_state")
        role = item.get("decision_role")
        expected_state = (
            "diagnostic"
            if role == "risk_diagnostic"
            else (
                "invalid"
                if role == "validity" and comparison == "failed"
                else "supported"
                if comparison == "passed"
                else "contradicted"
            )
        )
        if (
            any(item.get(field) != prior.get(field) for field in definition_fields)
            or comparison not in {"passed", "failed"}
            or type(item.get("value")) is not int
            or item.get("scientific_state") != expected_state
            or expected_state == "invalid"
        ):
            raise ReplayTransitionError(
                "scientific replay satisfaction did not validly recompute every criterion"
            )
    if revalidate_current_multiplicity_binding:
        _require_multiplicity_batch_binding(
            index,
            satisfaction=satisfaction,
            diagnosis=diagnosis,
            target_completion=completion,
            target_declaration=declaration,
            adjudication=adjudication,
        )


def prepare_audit_only_scope_overlay(
    index: LocalIndex,
    *,
    mission_id: str,
    satisfactions: Sequence[ReplaySatisfaction],
) -> IndexRecord:
    """Prepare one zero-credit overlay for a shared audit-only completion."""

    normalized = tuple(satisfactions)
    if not normalized or any(
        item.resolution_scope is not ReplayResolutionScope.AUDIT_ONLY
        for item in normalized
    ):
        raise ReplayTransitionError(
            "historical evidence scope requires audit-only satisfactions"
        )
    completion_sets = []
    for satisfaction in normalized:
        completions = {
            record_id
            for record_id in satisfaction.evidence_record_ids
            if index.get("job-completed", record_id) is not None
        }
        if len(completions) != 1:
            raise ReplayTransitionError(
                "audit-only satisfaction must bind one exact completion"
            )
        completion_sets.append(completions)
    completion_ids = set.intersection(*completion_sets)
    study_ids = {item.replay_study_id for item in normalized}
    if len(completion_ids) != 1 or len(study_ids) != 1:
        raise ReplayTransitionError(
            "audit-only scope overlay requires one shared Study completion"
        )
    completion_id = next(iter(completion_ids))
    if index.event_head(evidence_scope_stream(completion_id)) is not None:
        raise ReplayTransitionError(
            "historical completion already has an effective evidence scope"
        )
    try:
        overlay = HistoricalEvidenceScopeOverlay(
            completion_record_id=completion_id,
            governing_mission_id=mission_id,
            replay_study_id=next(iter(study_ids)),
            replay_obligation_ids=tuple(
                item.obligation_id for item in normalized
            ),
            replay_resolution_ids=tuple(item.identity for item in normalized),
        )
    except (TypeError, ValueError) as exc:
        raise ReplayProjectionError(
            "historical evidence scope overlay cannot be derived"
        ) from exc
    return evidence_scope_overlay_record(overlay)


def prepare_audit_only_scope_overlays(
    index: LocalIndex,
    *,
    mission_id: str,
    satisfactions: Sequence[ReplaySatisfaction],
) -> tuple[IndexRecord, ...]:
    """Group audit-only resolutions by the exact completion they demote."""

    grouped: dict[str, list[ReplaySatisfaction]] = {}
    for satisfaction in satisfactions:
        completion_ids = tuple(
            record_id
            for record_id in satisfaction.evidence_record_ids
            if index.get("job-completed", record_id) is not None
        )
        if len(completion_ids) != 1:
            raise ReplayTransitionError(
                "audit-only satisfaction must bind one exact completion"
            )
        grouped.setdefault(completion_ids[0], []).append(satisfaction)
    return tuple(
        prepare_audit_only_scope_overlay(
            index,
            mission_id=mission_id,
            satisfactions=tuple(grouped[completion_id]),
        )
        for completion_id in sorted(grouped)
    )


def _require_satisfaction_lineage(
    index: LocalIndex | LocalIndexView,
    *,
    obligation: HistoricalReplayObligation,
    satisfaction: ReplaySatisfaction,
    allow_legacy_decision_binding: bool,
) -> tuple[
    IndexRecord,
    IndexRecord,
    IndexRecord,
    IndexRecord,
    IndexRecord,
    Mapping[str, Any],
]:
    """Open the immutable subject lineage named by one satisfaction."""

    decision = index.get("portfolio-decision", satisfaction.portfolio_decision_id)
    study = index.get("study-open", satisfaction.replay_study_id)
    trial = index.get("trial", satisfaction.replay_executable_id)
    close_record = index.get("study-close", satisfaction.replay_study_close_record_id)
    diagnosis = index.get("study-diagnosis", satisfaction.study_diagnosis_id)
    decision_obligations = (
        [] if decision is None else decision.payload.get("replay_obligation_ids", [])
    )
    if (
        satisfaction.obligation_id != obligation.identity
        or tuple(satisfaction.satisfied_criterion_ids) != obligation.criterion_ids
        or decision is None
        or study is None
        or trial is None
        or close_record is None
        or diagnosis is None
        or study.payload.get("mission_id") != obligation.governing_mission_id
        or study.payload.get("portfolio_decision_id") != decision.record_id
        or trial.payload.get("study_id") != study.record_id
        or close_record.subject != f"Study:{study.record_id}"
        or diagnosis.payload.get("study_id") != study.record_id
        or diagnosis.payload.get("study_close_record_id") != close_record.record_id
        or not isinstance(decision_obligations, list)
        or (
            not allow_legacy_decision_binding
            and obligation.identity not in decision_obligations
        )
    ):
        raise ReplayTransitionError(
            "historical replay satisfaction lacks exact Decision/Study/Executable binding"
        )
    expected_evidence = replay_evidence_record_ids(
        diagnosis=diagnosis,
        close_record=close_record,
        trial=trial,
    )
    if tuple(satisfaction.evidence_record_ids) != expected_evidence:
        raise ReplayTransitionError(
            "historical replay satisfaction evidence binding is incomplete"
        )
    basis = diagnosis.payload.get("evidence_basis")
    if not isinstance(basis, list):
        raise ReplayTransitionError(
            "historical replay satisfaction evidence lineage is malformed"
        )
    for item in basis:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"kind", "record_id"}
            or type(item.get("kind")) is not str
            or type(item.get("record_id")) is not str
            or index.get(item["kind"], item["record_id"]) is None
        ):
            raise ReplayTransitionError(
                "historical replay satisfaction evidence lineage is unavailable"
            )
    executable_payload = trial.payload.get("executable")
    if not isinstance(executable_payload, Mapping):
        raise ReplayTransitionError(
            "replay Executable manifest is malformed"
        )
    return decision, study, trial, close_record, diagnosis, executable_payload


def _require_satisfaction(
    index: LocalIndex,
    *,
    obligation: HistoricalReplayObligation,
    satisfaction: ReplaySatisfaction,
    allow_legacy_decision_binding: bool,
    revalidate_current_multiplicity_binding: bool,
) -> None:
    (
        _decision,
        _study,
        _trial,
        _close_record,
        diagnosis,
        executable_payload,
    ) = _require_satisfaction_lineage(
        index,
        obligation=obligation,
        satisfaction=satisfaction,
        allow_legacy_decision_binding=allow_legacy_decision_binding,
    )
    if not payload_contains_exact_value(
        executable_payload, obligation.original_executable_id
    ):
        raise ReplayTransitionError(
            "replay Executable does not contain the original obligation surface"
        )
    if satisfaction.resolution_scope is ReplayResolutionScope.AUDIT_ONLY:
        if not payload_contains_exact_value(
            executable_payload, "post_selection_descriptive_audit_only"
        ):
            raise ReplayTransitionError(
                "audit-only replay lacks descriptive-only execution authority"
            )
        completion_ids = {
            item["record_id"]
            for item in diagnosis.payload["evidence_basis"]
            if item["kind"] == "job-completed"
        }
        completions = [index.get("job-completed", item) for item in completion_ids]
        if not completions or any(
            completion is None
            or not isinstance(completion.payload.get("scientific"), dict)
            or completion.payload["scientific"].get("candidate_eligible") is not False
            for completion in completions
        ):
            raise ReplayTransitionError(
                "audit-only replay completion could grant candidate authority"
            )
    else:
        if (
            typed_replay_reference_executable_id(executable_payload)
            != obligation.original_executable_id
        ):
            raise ReplayTransitionError(
                "scientific replay Executable lacks its typed original reference"
            )
        _require_scientific_satisfaction_evidence(
            index,
            obligation=obligation,
            satisfaction=satisfaction,
            diagnosis=diagnosis,
            revalidate_current_multiplicity_binding=(
                revalidate_current_multiplicity_binding
            ),
        )


def require_satisfaction(
    index: LocalIndex,
    *,
    obligation: HistoricalReplayObligation,
    satisfaction: ReplaySatisfaction,
    allow_legacy_decision_binding: bool,
) -> None:
    """Authorize a satisfaction under the current replay protocol."""

    _require_satisfaction(
        index,
        obligation=obligation,
        satisfaction=satisfaction,
        allow_legacy_decision_binding=allow_legacy_decision_binding,
        revalidate_current_multiplicity_binding=True,
    )


def require_recorded_satisfaction(
    index: LocalIndex | LocalIndexView,
    *,
    obligation: HistoricalReplayObligation,
    satisfaction: ReplaySatisfaction,
    allow_legacy_decision_binding: bool,
    satisfaction_head: IndexRecord | None = None,
    require_current_head: bool = True,
) -> None:
    """Authenticate one Writer-accepted satisfaction under recorded authority.

    Projection proves the exact stream transition, immutable subject lineage,
    Journal authority, and same-event Writer operation.  It deliberately does
    not rerun validator, adjudication, criterion, or multiplicity semantics
    that may have changed after the immutable satisfaction was accepted.
    Current rules remain mandatory in ``require_satisfaction`` at every new
    resolution and in the explicit typed invalidation audit.
    """

    stored = (
        index.get(
            "historical-replay-obligation-resolution",
            satisfaction.identity,
        )
        if satisfaction_head is None
        else satisfaction_head
    )
    if stored is None:
        raise ReplayProjectionError("recorded replay satisfaction is unavailable")
    parsed = _satisfaction_from_head(obligation=obligation, head=stored)
    if parsed != satisfaction:
        raise ReplayProjectionError(
            "recorded replay satisfaction differs from its stored head"
        )
    event_kind, result = _require_recorded_transition_authority(
        index,
        obligation=obligation,
        record=stored,
        expected_event_kinds={
            "historical_replay_correction_recorded",
            "historical_replay_obligations_resolved",
        },
        require_current_head=require_current_head,
    )
    satisfied_ids = result.get("satisfied_replay_obligation_ids")
    if (
        not isinstance(satisfied_ids, list)
        or any(type(item) is not str for item in satisfied_ids)
        or len(satisfied_ids) != len(set(satisfied_ids))
        or satisfied_ids != sorted(satisfied_ids)
        or obligation.identity not in satisfied_ids
    ):
        raise ReplayProjectionError(
            "recorded replay satisfaction lacks same-event Writer acceptance"
        )
    _require_satisfaction_lineage(
        index,
        obligation=obligation,
        satisfaction=satisfaction,
        allow_legacy_decision_binding=(
            allow_legacy_decision_binding
            or event_kind == "historical_replay_correction_recorded"
        ),
    )


def _satisfaction_from_head(
    *,
    obligation: HistoricalReplayObligation,
    head: IndexRecord,
) -> ReplaySatisfaction:
    raw = head.payload.get("resolution")
    if not isinstance(raw, Mapping):
        raise ReplayProjectionError("replay satisfaction head is malformed")
    try:
        satisfaction = ReplaySatisfaction(
            obligation_id=raw["obligation_id"],
            resolution_scope=ReplayResolutionScope(raw["resolution_scope"]),
            portfolio_decision_id=raw["portfolio_decision_id"],
            replay_study_id=raw["replay_study_id"],
            replay_executable_id=raw["replay_executable_id"],
            replay_study_close_record_id=raw["replay_study_close_record_id"],
            study_diagnosis_id=raw["study_diagnosis_id"],
            satisfied_criterion_ids=tuple(raw["satisfied_criterion_ids"]),
            evidence_record_ids=tuple(raw["evidence_record_ids"]),
            remaining_scientific_condition=raw.get(
                "remaining_scientific_condition"
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayProjectionError("replay satisfaction head is malformed") from exc
    if (
        head.kind != "historical-replay-obligation-resolution"
        or head.status != ReplayObligationStatus.SATISFIED.value
        or head.record_id != satisfaction.identity
        or head.subject != f"Mission:{obligation.governing_mission_id}"
        or head.event_stream != obligation_stream(obligation.identity)
        or type(head.event_sequence) is not int
        or head.event_sequence < 2
        or head.payload
        != {
            "obligation_id": obligation.identity,
            "prior_status": head.payload.get("prior_status"),
            "resolution": satisfaction.to_identity_payload(),
        }
        or head.payload.get("prior_status")
        not in {
            ReplayObligationStatus.PENDING.value,
            ReplayObligationStatus.IN_PROGRESS.value,
        }
        or satisfaction.obligation_id != obligation.identity
    ):
        raise ReplayProjectionError("replay satisfaction head is malformed")
    return satisfaction


def _require_recorded_transition_authority(
    index: LocalIndex | LocalIndexView,
    *,
    obligation: HistoricalReplayObligation,
    record: IndexRecord,
    expected_event_kinds: set[str],
    require_current_head: bool,
) -> tuple[str, Mapping[str, Any]]:
    """Authenticate one stored stream transition and its Writer operation."""

    if record.event_stream != obligation_stream(obligation.identity):
        raise ReplayProjectionError(
            "recorded replay transition is outside its obligation stream"
        )
    try:
        return require_recorded_transition_authority(
            index,
            record=record,
            expected_event_kinds=frozenset(expected_event_kinds),
            require_current_head=require_current_head,
        )
    except RecordedTransitionAuthorityError as exc:
        raise ReplayProjectionError(str(exc)) from exc


def _completion_validity_defect(
    index: LocalIndex,
    *,
    satisfaction: ReplaySatisfaction,
) -> tuple[tuple[str, ...], ReplayCompletionValidityDefect | None]:
    """Derive invalid family members only from authenticated current heads."""

    completion_ids = tuple(
        sorted(
            record_id
            for record_id in satisfaction.evidence_record_ids
            if index.get("job-completed", record_id) is not None
        )
    )
    if not completion_ids:
        raise ReplayProjectionError(
            "scientific replay satisfaction lacks its completion family"
        )
    observations: list[ReplayCompletionValidityObservation] = []
    for completion_id in completion_ids:
        try:
            current = current_completion_validity_invalidation(
                index,
                completion_id,
            )
        except CompletionValidityProjectionError as exc:
            raise ReplayProjectionError(
                "replay completion validity authority is malformed"
            ) from exc
        if current is None:
            continue
        observations.append(
            ReplayCompletionValidityObservation(
                completion_record_id=current.completion_record_id,
                executable_id=current.executable_id,
                invalidation_record_id=current.invalidation_record_id,
                reason=current.reason,
                affected_criterion_ids=current.affected_criterion_ids,
                validity_stream_sequence=current.validity_stream_sequence,
                authority_event_id=current.authority_event_id,
                authority_sequence=current.authority_sequence,
                authority_offset=current.authority_offset,
            )
        )
    if not observations:
        return completion_ids, None
    try:
        return completion_ids, ReplayCompletionValidityDefect(
            code=(
                ReplayCompletionValidityDefectCode.EVIDENCE_COMPLETION_VALIDITY_INVALID
            ),
            observations=tuple(observations),
        )
    except (TypeError, ValueError) as exc:
        raise ReplayProjectionError(
            "replay completion validity defect cannot be derived"
        ) from exc


def derive_satisfaction_invalidation_manifest(
    index: LocalIndex,
    *,
    obligation: HistoricalReplayObligation,
    satisfaction_head: IndexRecord,
) -> ReplaySatisfactionInvalidationManifest:
    """Revalidate one satisfied head and derive every exact typed defect."""

    satisfaction = _satisfaction_from_head(
        obligation=obligation,
        head=satisfaction_head,
    )
    if satisfaction.resolution_scope is not ReplayResolutionScope.SCIENTIFIC:
        raise ReplayTransitionError(
            "only scientific replay satisfaction can be validity-invalidated"
        )
    completion_ids, validity_defect = _completion_validity_defect(
        index,
        satisfaction=satisfaction,
    )
    multiplicity_defect: ReplayMultiplicityBindingDefect | None = None
    try:
        require_satisfaction(
            index,
            obligation=obligation,
            satisfaction=satisfaction,
            allow_legacy_decision_binding=False,
        )
    except ReplayMultiplicityBindingError as exc:
        multiplicity_defect = exc.defect
    except _HistoricalRegistrationOrderDiagnostic:
        # The immutable history preserves both the frozen Batch member order
        # and each registration's same-member order.  Their order-only
        # difference is diagnostic for old accepted satisfactions, never a
        # revocation capability.  A separately authenticated completion-
        # validity head may still revoke the satisfaction; prospective
        # satisfaction admission continues to reject this diagnostic above.
        if validity_defect is None:
            raise
    except ReplayAuthorityError:
        raise
    if multiplicity_defect is None and validity_defect is None:
        raise ReplayTransitionError(
            "historical replay satisfaction remains valid under the current protocol"
        )
    if multiplicity_defect is None:
        defects = (validity_defect,)
    elif validity_defect is None:
        defect = multiplicity_defect
        return ReplaySatisfactionInvalidationAuditManifest(
            governing_mission_id=obligation.governing_mission_id,
            obligation_id=obligation.identity,
            satisfaction_record_id=satisfaction.identity,
            satisfaction_event_sequence=satisfaction_head.event_sequence,
            portfolio_decision_id=satisfaction.portfolio_decision_id,
            replay_study_id=satisfaction.replay_study_id,
            replay_executable_id=satisfaction.replay_executable_id,
            replay_study_close_record_id=satisfaction.replay_study_close_record_id,
            study_diagnosis_id=satisfaction.study_diagnosis_id,
            completion_record_ids=tuple(
                item.completion_record_id for item in defect.observations
            ),
            defect=defect,
        )
    else:
        defects = (multiplicity_defect, validity_defect)
    assert all(defect is not None for defect in defects)
    return ReplaySatisfactionInvalidationAuditManifestV2(
        governing_mission_id=obligation.governing_mission_id,
        obligation_id=obligation.identity,
        satisfaction_record_id=satisfaction.identity,
        satisfaction_event_sequence=satisfaction_head.event_sequence,
        portfolio_decision_id=satisfaction.portfolio_decision_id,
        replay_study_id=satisfaction.replay_study_id,
        replay_executable_id=satisfaction.replay_executable_id,
        replay_study_close_record_id=satisfaction.replay_study_close_record_id,
        study_diagnosis_id=satisfaction.study_diagnosis_id,
        completion_record_ids=completion_ids,
        defects=defects,  # type: ignore[arg-type]
    )


def build_satisfaction_invalidation_plan(
    index: LocalIndex,
    *,
    mission_id: str,
    obligation_id: str,
) -> dict[str, Any]:
    """Build the canonical audit artifact without mutating any authority."""

    matches = tuple(
        (obligation, head)
        for obligation, head in obligation_heads(index, mission_id=mission_id)
        if obligation.identity == obligation_id
    )
    if len(matches) != 1:
        raise ReplayTransitionError(
            "replay satisfaction invalidation names an unknown obligation"
        )
    obligation, head = matches[0]
    if head.status != ReplayObligationStatus.SATISFIED.value:
        raise ReplayTransitionError(
            "replay satisfaction invalidation requires a satisfied head"
        )
    manifest = derive_satisfaction_invalidation_manifest(
        index,
        obligation=obligation,
        satisfaction_head=head,
    )
    payload = manifest.to_identity_payload()
    return {
        "audit_manifest": payload,
        "audit_manifest_sha256": sha256(canonical_bytes(payload)).hexdigest(),
        "operation": "invalidate_historical_replay_satisfaction",
        "schema": "replay_satisfaction_invalidation_plan.v1",
    }


def satisfaction_invalidation_record(
    *,
    obligation: HistoricalReplayObligation,
    manifest: ReplaySatisfactionInvalidationManifest,
    audit_manifest_hash: str,
    sequence: int,
) -> IndexRecord:
    payload = {
        "audit_manifest": manifest.to_identity_payload(),
        "audit_manifest_hash": audit_manifest_hash,
        "candidate_delta": 0,
        "holdout_reveal_delta": 0,
        "obligation_id": obligation.identity,
        "prior_satisfaction_record_id": manifest.satisfaction_record_id,
        "prior_status": ReplayObligationStatus.SATISFIED.value,
        "scientific_claim_delta": 0,
        "scientific_satisfaction_delta": 0,
        "scientific_trial_delta": 0,
        "terminal_credit_delta": 0,
    }
    return _record(
        kind="historical-replay-satisfaction-invalidation",
        record_id=manifest.identity,
        subject=f"Mission:{obligation.governing_mission_id}",
        status=ReplayObligationStatus.PENDING.value,
        fingerprint=manifest.identity.removeprefix(
            "historical-replay-satisfaction-invalidation:"
        ),
        payload=payload,
        event_stream=obligation_stream(obligation.identity),
        event_sequence=sequence,
    )


def require_satisfaction_invalidation_record(
    index: LocalIndex | LocalIndexView,
    *,
    obligation: HistoricalReplayObligation,
    record: IndexRecord,
) -> ReplaySatisfactionInvalidationManifest:
    """Rebuild a pending invalidation head from its exact prior satisfaction."""

    raw_manifest = record.payload.get("audit_manifest")
    audit_manifest_hash = record.payload.get("audit_manifest_hash")
    try:
        manifest = replay_satisfaction_invalidation_manifest_from_mapping(
            raw_manifest
        )
    except (TypeError, ValueError) as exc:
        raise ReplayProjectionError(
            "replay satisfaction invalidation manifest is malformed"
        ) from exc
    expected_payload = {
        "audit_manifest": manifest.to_identity_payload(),
        "audit_manifest_hash": audit_manifest_hash,
        "candidate_delta": 0,
        "holdout_reveal_delta": 0,
        "obligation_id": obligation.identity,
        "prior_satisfaction_record_id": manifest.satisfaction_record_id,
        "prior_status": ReplayObligationStatus.SATISFIED.value,
        "scientific_claim_delta": 0,
        "scientific_satisfaction_delta": 0,
        "scientific_trial_delta": 0,
        "terminal_credit_delta": 0,
    }
    if (
        type(audit_manifest_hash) is not str
        or sha256(canonical_bytes(manifest.to_identity_payload())).hexdigest()
        != audit_manifest_hash
        or record.kind != "historical-replay-satisfaction-invalidation"
        or record.record_id != manifest.identity
        or record.subject != f"Mission:{obligation.governing_mission_id}"
        or record.status != ReplayObligationStatus.PENDING.value
        or record.fingerprint
        != manifest.identity.removeprefix(
            "historical-replay-satisfaction-invalidation:"
        )
        or record.payload != expected_payload
        or record.event_stream != obligation_stream(obligation.identity)
        or record.event_sequence != manifest.satisfaction_event_sequence + 1
        or manifest.governing_mission_id != obligation.governing_mission_id
        or manifest.obligation_id != obligation.identity
    ):
        raise ReplayProjectionError(
            "replay satisfaction invalidation record is malformed"
        )
    _event_kind, result = _require_recorded_transition_authority(
        index,
        obligation=obligation,
        record=record,
        expected_event_kinds={
            "historical_replay_satisfaction_invalidated",
        },
        require_current_head=True,
    )
    pending_ids = result.get("pending_replay_obligation_ids")
    if (
        result.get("audit_manifest_hash") != audit_manifest_hash
        or result.get("invalidated_satisfaction_record_id")
        != manifest.satisfaction_record_id
        or result.get("replay_obligation_id") != obligation.identity
        or not isinstance(pending_ids, list)
        or any(type(item) is not str for item in pending_ids)
        or len(pending_ids) != len(set(pending_ids))
        or pending_ids != sorted(pending_ids)
        or obligation.identity not in pending_ids
        or any(
            result.get(field) != 0
            for field in (
                "candidate_delta",
                "holdout_reveal_delta",
                "scientific_claim_delta",
                "scientific_satisfaction_delta",
                "scientific_trial_delta",
            )
        )
    ):
        raise ReplayProjectionError(
            "replay satisfaction invalidation lacks exact zero-delta Writer authority"
        )
    prior = index.get(
        "historical-replay-obligation-resolution",
        manifest.satisfaction_record_id,
    )
    if prior is None or prior.event_sequence != manifest.satisfaction_event_sequence:
        raise ReplayProjectionError(
            "replay satisfaction invalidation lost its exact prior head"
        )
    satisfaction = _satisfaction_from_head(
        obligation=obligation,
        head=prior,
    )
    require_recorded_satisfaction(
        index,
        obligation=obligation,
        satisfaction=satisfaction,
        allow_legacy_decision_binding=False,
        satisfaction_head=prior,
        require_current_head=False,
    )
    if (
        manifest.satisfaction_record_id != satisfaction.identity
        or manifest.satisfaction_event_sequence != prior.event_sequence
        or manifest.portfolio_decision_id
        != satisfaction.portfolio_decision_id
        or manifest.replay_study_id != satisfaction.replay_study_id
        or manifest.replay_executable_id
        != satisfaction.replay_executable_id
        or manifest.replay_study_close_record_id
        != satisfaction.replay_study_close_record_id
        or manifest.study_diagnosis_id != satisfaction.study_diagnosis_id
    ):
        raise ReplayProjectionError(
            "replay satisfaction invalidation lost its exact prior satisfaction"
        )
    stored_evidence_ids = set(satisfaction.evidence_record_ids)
    stored_completion_ids = {
        record_id
        for record_id in stored_evidence_ids
        if index.get("job-completed", record_id) is not None
    }
    if set(manifest.completion_record_ids) != stored_completion_ids:
        raise ReplayProjectionError(
            "replay satisfaction invalidation manifest left its stored evidence lineage"
        )
    defects = (
        (manifest.defect,)
        if isinstance(manifest, ReplaySatisfactionInvalidationAuditManifest)
        else manifest.defects
    )
    for defect in defects:
        if isinstance(defect, ReplayMultiplicityBindingDefect):
            if (
                defect.batch_open_record_id not in stored_evidence_ids
                or defect.batch_close_record_id not in stored_evidence_ids
                or index.get("batch-open", defect.batch_open_record_id) is None
                or index.get("batch-close", defect.batch_close_record_id) is None
            ):
                raise ReplayProjectionError(
                    "replay multiplicity defect left its stored Batch lineage"
                )
            continue
        if not isinstance(defect, ReplayCompletionValidityDefect):
            raise ReplayProjectionError(
                "replay satisfaction invalidation defect is unsupported"
            )
        for observation in defect.observations:
            try:
                current = current_completion_validity_invalidation(
                    index,
                    observation.completion_record_id,
                )
            except CompletionValidityProjectionError as exc:
                raise ReplayProjectionError(
                    "replay completion validity head is malformed"
                ) from exc
            if (
                current is None
                or current.completion_record_id
                != observation.completion_record_id
                or current.executable_id != observation.executable_id
                or current.invalidation_record_id
                != observation.invalidation_record_id
                or current.reason != observation.reason
                or current.affected_criterion_ids
                != observation.affected_criterion_ids
                or current.validity_stream_sequence
                != observation.validity_stream_sequence
                or current.authority_event_id != observation.authority_event_id
                or current.authority_sequence != observation.authority_sequence
                or current.authority_offset != observation.authority_offset
                or not set(observation.affected_criterion_ids).intersection(
                    satisfaction.satisfied_criterion_ids
                )
            ):
                raise ReplayProjectionError(
                    "replay completion validity defect is stale or unrelated"
                )
    return manifest


def prepare_satisfaction_invalidation(
    index: LocalIndex,
    *,
    mission_id: str,
    obligation_id: str,
    manifest: ReplaySatisfactionInvalidationManifest,
    audit_manifest_hash: str,
) -> tuple[list[IndexRecord], dict[str, Any], dict[str, Any]]:
    """Prepare satisfied-to-pending revocation and restore its scheduler duty."""

    plan = build_satisfaction_invalidation_plan(
        index,
        mission_id=mission_id,
        obligation_id=obligation_id,
    )
    expected = replay_satisfaction_invalidation_manifest_from_mapping(
        plan["audit_manifest"]
    )
    if (
        manifest != expected
        or manifest.obligation_id != obligation_id
        or plan["audit_manifest_sha256"] != audit_manifest_hash
    ):
        raise ReplayTransitionError(
            "replay satisfaction invalidation artifact differs from current authority"
        )
    pairs = {
        obligation.identity: (obligation, head)
        for obligation, head in obligation_heads(index, mission_id=mission_id)
    }
    obligation, head = pairs[obligation_id]
    record = satisfaction_invalidation_record(
        obligation=obligation,
        manifest=manifest,
        audit_manifest_hash=audit_manifest_hash,
        sequence=(head.event_sequence or 0) + 1,
    )
    constraints = constraints_for_pending_from_index(
        index,
        tuple(
        item
        for item, current_head in pairs.values()
        if current_head.status == ReplayObligationStatus.PENDING.value
        or item.identity == obligation_id
        ),
    )
    if constraints is None:
        raise ReplayProjectionError(
            "replay satisfaction invalidation lost its scheduler constraint"
        )
    return [record], constraints, {
        "audit_manifest_hash": audit_manifest_hash,
        "invalidated_satisfaction_record_id": manifest.satisfaction_record_id,
        "pending_replay_obligation_ids": constraints[
            "pending_replay_obligation_ids"
        ],
        "replay_obligation_id": obligation_id,
        "scientific_claim_delta": 0,
        "scientific_satisfaction_delta": 0,
        "scientific_trial_delta": 0,
        "holdout_reveal_delta": 0,
        "candidate_delta": 0,
    }


def build_explicit_historical_replay_correction_audit_plan(
    index: LocalIndex,
    *,
    mission_id: str,
    adjudication_record_ids: Sequence[str],
    replay_study_id: str,
) -> dict[str, Any]:
    """Build the explicit complete-history audit for one replay correction.

    This is a rare operator-requested correction boundary, not a routine
    scheduler projection.  The Trial and Study-diagnosis kind scans below are
    deliberately complete-history audits: historical records do not have a
    trusted replay-Study lookup key, and silently narrowing the slice could
    omit conflicting evidence.  Keep callers on this explicitly named path
    instead of reusing these scans for normal routing.
    """

    validate_study_id(replay_study_id)
    obligations = tuple(
        derive_obligation_from_record(
            index,
            adjudication_record_id=item,
            mission_id=mission_id,
        )
        for item in adjudication_record_ids
    )
    study = index.get("study-open", replay_study_id)
    # Intentional complete-history audit slice; never use for routine routing.
    trials = tuple(
        record
        for record in index.records_by_kind("trial")
        if record.payload.get("study_id") == replay_study_id
    )
    closes = tuple(
        record
        for status in _STUDY_OUTCOMES
        for record in index.records_by_subject_status(f"Study:{replay_study_id}", status)
        if record.kind == "study-close"
    )
    # Intentional complete-history audit slice; never use for routine routing.
    diagnoses = tuple(
        record
        for record in index.records_by_kind("study-diagnosis")
        if record.payload.get("study_id") == replay_study_id
    )
    decision = (
        None
        if study is None
        else index.get(
            "portfolio-decision", study.payload.get("portfolio_decision_id", "")
        )
    )
    if (
        study is None
        or study.payload.get("mission_id") != mission_id
        or decision is None
        or len(trials) != 1
        or len(closes) != 1
        or len(diagnoses) != 1
    ):
        raise ReplayTransitionError(
            "replay correction Study evidence is unavailable or ambiguous"
        )
    trial, close_record, diagnosis = trials[0], closes[0], diagnoses[0]
    evidence_ids = replay_evidence_record_ids(
        diagnosis=diagnosis,
        close_record=close_record,
        trial=trial,
    )
    represented = {
        obligation.identity
        for obligation in obligations
        if payload_contains_exact_value(
            trial.payload.get("executable", {}), obligation.original_executable_id
        )
    }
    p0 = tuple(
        item for item in obligations if item.replay_priority is ReplayPriority.P0
    )
    if represented != {item.identity for item in p0}:
        raise ReplayTransitionError(
            "replay correction Study does not exactly cover the p0 family"
        )
    satisfaction_values = tuple(
        ReplaySatisfaction(
            evidence_record_ids=evidence_ids,
            obligation_id=item.identity,
            portfolio_decision_id=decision.record_id,
            remaining_scientific_condition=(
                "prospective_paired_control_or_independent_family"
            ),
            replay_executable_id=trial.record_id,
            replay_study_close_record_id=close_record.record_id,
            replay_study_id=study.record_id,
            resolution_scope=ReplayResolutionScope.AUDIT_ONLY,
            satisfied_criterion_ids=item.criterion_ids,
            study_diagnosis_id=diagnosis.record_id,
        )
        for item in p0
    )
    overlay_record = prepare_audit_only_scope_overlay(
        index,
        mission_id=mission_id,
        satisfactions=satisfaction_values,
    )
    return {
        "adjudication_record_ids": list(adjudication_record_ids),
        "governing_mission_id": mission_id,
        "operation": "record_historical_replay_correction",
        "pending_after_apply": sorted(
            item.identity
            for item in obligations
            if item.replay_priority is ReplayPriority.P1
        ),
        "effective_scope_overlay": {
            "payload": dict(overlay_record.payload),
            "record_id": overlay_record.record_id,
        },
        "satisfaction_templates": [
            item.to_identity_payload() for item in satisfaction_values
        ],
        "satisfied_after_apply": sorted(item.identity for item in p0),
        "schema": "historical_replay_correction_plan.v2",
    }


def build_correction_plan(
    index: LocalIndex,
    *,
    mission_id: str,
    adjudication_record_ids: Sequence[str],
    replay_study_id: str,
) -> dict[str, Any]:
    """Compatibility wrapper for the explicit historical correction audit."""

    return build_explicit_historical_replay_correction_audit_plan(
        index,
        mission_id=mission_id,
        adjudication_record_ids=adjudication_record_ids,
        replay_study_id=replay_study_id,
    )


def prepare_correction(
    index: LocalIndex,
    *,
    mission_id: str,
    adjudication_record_ids: Sequence[str],
    satisfactions: Sequence[ReplaySatisfaction],
) -> tuple[list[IndexRecord], dict[str, Any] | None, dict[str, Any]]:
    obligations = tuple(
        derive_obligation_from_record(
            index,
            adjudication_record_id=item,
            mission_id=mission_id,
        )
        for item in adjudication_record_ids
    )
    by_id = {item.identity: item for item in obligations}
    satisfied_ids = {item.obligation_id for item in satisfactions}
    if satisfied_ids - set(by_id):
        raise ReplayTransitionError(
            "historical replay satisfaction targets another correction"
        )
    if any(
        index.get("historical-replay-obligation", item.identity) is not None
        for item in obligations
    ):
        raise ReplayTransitionError(
            "historical replay correction was already materialized"
        )
    p0_ids = {
        item.identity
        for item in obligations
        if item.replay_priority is ReplayPriority.P0
    }
    if satisfied_ids != p0_ids:
        raise ReplayTransitionError(
            "historical replay correction must satisfy exactly the p0 family"
        )
    records = [initial_obligation_record(item) for item in obligations]
    for satisfaction in satisfactions:
        obligation = by_id[satisfaction.obligation_id]
        require_satisfaction(
            index,
            obligation=obligation,
            satisfaction=satisfaction,
            allow_legacy_decision_binding=True,
        )
        records.append(
            satisfaction_record(
                obligation=obligation,
                satisfaction=satisfaction,
                prior_status=ReplayObligationStatus.PENDING,
                sequence=2,
            )
        )
    overlay_records = prepare_audit_only_scope_overlays(
        index,
        mission_id=mission_id,
        satisfactions=satisfactions,
    )
    if len(overlay_records) != 1:
        raise ReplayTransitionError(
            "historical correction requires one shared audit completion"
        )
    overlay_record = overlay_records[0]
    records.append(overlay_record)
    constraints = constraints_for_pending(
        item for item in obligations if item.identity not in satisfied_ids
    )
    return records, constraints, {
        "pending_replay_obligation_ids": (
            [] if constraints is None else constraints["pending_replay_obligation_ids"]
        ),
        "satisfied_replay_obligation_ids": sorted(satisfied_ids),
        "effective_scope_overlay_id": overlay_record.record_id,
    }


def prepare_resolution(
    index: LocalIndex,
    *,
    mission_id: str,
    next_action: Mapping[str, Any],
    satisfactions: Sequence[ReplaySatisfaction],
) -> tuple[list[IndexRecord], dict[str, Any] | None, dict[str, Any]]:
    if (
        next_action.get("kind") != "resolve_historical_replay_obligations"
        or next_action.get("replay_obligation_ids")
        != [item.obligation_id for item in satisfactions]
        or not isinstance(next_action.get("resume_next_action"), dict)
    ):
        raise ReplayTransitionError("replay resolution is not the exact next action")
    heads = {
        obligation.identity: (obligation, head)
        for obligation, head in obligation_heads(index, mission_id=mission_id)
    }
    records = []
    for satisfaction in satisfactions:
        pair = heads.get(satisfaction.obligation_id)
        if pair is None or pair[1].status != ReplayObligationStatus.IN_PROGRESS.value:
            raise ReplayTransitionError(
                "replay satisfaction is not currently in progress"
            )
        obligation, head = pair
        require_satisfaction(
            index,
            obligation=obligation,
            satisfaction=satisfaction,
            allow_legacy_decision_binding=False,
        )
        records.append(
            satisfaction_record(
                obligation=obligation,
                satisfaction=satisfaction,
                prior_status=ReplayObligationStatus.IN_PROGRESS,
                sequence=(head.event_sequence or 0) + 1,
            )
        )
    audit_satisfactions = tuple(
        item
        for item in satisfactions
        if item.resolution_scope is ReplayResolutionScope.AUDIT_ONLY
    )
    overlay_ids: list[str] = []
    if audit_satisfactions:
        overlay_records = prepare_audit_only_scope_overlays(
            index,
            mission_id=mission_id,
            satisfactions=audit_satisfactions,
        )
        records.extend(overlay_records)
        overlay_ids.extend(item.record_id for item in overlay_records)
    constraints = constraints_for_pending_from_index(
        index,
        tuple(
        obligation
        for obligation, head in heads.values()
        if head.status == ReplayObligationStatus.PENDING.value
        ),
    )
    return records, constraints, {
        "effective_scope_overlay_ids": overlay_ids,
        "satisfied_replay_obligation_ids": [
            item.obligation_id for item in satisfactions
        ]
    }


def replay_obligation_capability_id(obligation_id: str) -> str:
    """Return the exact Mission capability name used by external blockers."""

    if (
        type(obligation_id) is not str
        or not obligation_id.startswith("historical-replay-obligation:")
    ):
        raise ReplayProjectionError("replay obligation capability id is malformed")
    return "historical-replay-resolution:" + canonical_digest(
        domain="historical-replay-resolution-capability",
        payload={"obligation_id": obligation_id},
    )


def _diagnosis_binds_original_obligation(
    index: LocalIndex,
    *,
    diagnosis: IndexRecord,
    obligation: HistoricalReplayObligation,
) -> bool:
    basis = diagnosis.payload.get("evidence_basis")
    completion = index.get(
        "job-completed", obligation.original_completion_record_id
    )
    try:
        lineage = (
            None
            if completion is None
            else completion_executable_axis_lineage(index, completion)
        )
    except ExecutableAxisLineageError:
        lineage = None
    close_record = index.get(
        "study-close", obligation.original_study_close_record_id
    )
    references = (
        set()
        if not isinstance(basis, list)
        else {
            (item.get("kind"), item.get("record_id"))
            for item in basis
            if isinstance(item, Mapping)
            and set(item) == {"kind", "record_id"}
        }
    )
    return bool(
        diagnosis.kind == "study-diagnosis"
        and diagnosis.subject == f"Study:{obligation.original_study_id}"
        and diagnosis.payload.get("mission_id") == obligation.governing_mission_id
        and diagnosis.payload.get("study_id") == obligation.original_study_id
        and diagnosis.payload.get("study_close_record_id")
        == obligation.original_study_close_record_id
        and (
            "study-close",
            obligation.original_study_close_record_id,
        )
        in references
        and (
            "job-completed",
            obligation.original_completion_record_id,
        )
        in references
        and lineage is not None
        and lineage.study_id == obligation.original_study_id
        and lineage.executable_id == obligation.original_executable_id
        and close_record is not None
        and close_record.subject == f"Study:{obligation.original_study_id}"
    )


def _require_resume_condition_surface(
    *,
    obligation: HistoricalReplayObligation,
    deferral: ReplayDeferral,
) -> None:
    surfaces = {
        (
            item.protocol_id,
            item.original_executable_ids,
            item.criterion_ids,
        )
        for item in deferral.resume_conditions
    }
    if (
        len(surfaces) != 1
        or any(
            item.criterion_ids != obligation.criterion_ids
            or obligation.original_executable_id
            not in item.original_executable_ids
            for item in deferral.resume_conditions
        )
    ):
        raise ReplayTransitionError(
            "replay deferral resume conditions change the original protocol surface"
        )


def _require_pending_deferral_basis(
    index: LocalIndex,
    *,
    obligation: HistoricalReplayObligation,
    deferral: ReplayDeferral,
) -> None:
    basis = deferral.basis
    if deferral.execution_binding is not None:
        raise ReplayTransitionError(
            "pending replay deferral cannot claim an execution closure"
        )
    allowed_conditions = {
        item.kind for item in deferral.resume_conditions
    }
    if basis.kind is ReplayDeferralBasisKind.STUDY_DIAGNOSIS:
        record = index.get("study-diagnosis", basis.record_id)
        if (
            record is None
            or basis.subject_id != obligation.original_study_id
            or not _diagnosis_binds_original_obligation(
                index, diagnosis=record, obligation=obligation
            )
            or not allowed_conditions.issubset(
                {
                    ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL,
                    ReplayResumeConditionKind.SAME_PROTOCOL_REPAIR,
                }
            )
        ):
            raise ReplayTransitionError(
                "pending replay diagnosis basis is not bound to the obligation"
            )
        return
    if basis.kind is ReplayDeferralBasisKind.SOURCE_AUTHORITY_INVALIDATION:
        record = index.get("source-authority-invalidation", basis.record_id)
        trial = index.get("trial", obligation.original_executable_id)
        executable = None if trial is None else trial.payload.get("executable")
        correction_head = index.event_head(f"source-authority:{basis.subject_id}")
        invalidation = None if record is None else record.payload.get("invalidation")
        if (
            record is None
            or record.subject != f"Source:{basis.subject_id}"
            or record.status != "confirmed_and_suspended"
            or not isinstance(invalidation, Mapping)
            or invalidation.get("source_contract_id") != basis.subject_id
            or correction_head is None
            or correction_head.record_id != basis.record_id
            or not isinstance(executable, Mapping)
            or basis.subject_id not in executable.get("source_contracts", [])
            or allowed_conditions
            != {ReplayResumeConditionKind.REPLACEMENT_SOURCE_CONTRACT}
            or any(
                item.subject_id != basis.subject_id
                for item in deferral.resume_conditions
            )
        ):
            raise ReplayTransitionError(
                "pending replay source basis is not bound to original source provenance"
            )
        return
    if basis.kind is ReplayDeferralBasisKind.EXTERNAL_BLOCKER:
        record = index.get("external-blocker", basis.record_id)
        cause = None if record is None else record.payload.get("cause")
        if (
            record is None
            or record.subject != f"Mission:{obligation.governing_mission_id}"
            or record.status != "complete"
            or not isinstance(cause, Mapping)
            or cause.get("dependency_id") != basis.subject_id
            or cause.get("blocked_mission_capability")
            != replay_obligation_capability_id(obligation.identity)
            or allowed_conditions
            != {ReplayResumeConditionKind.EXTERNAL_DEPENDENCY_AVAILABLE}
            or any(
                item.subject_id != basis.subject_id
                for item in deferral.resume_conditions
            )
        ):
            raise ReplayTransitionError(
                "pending replay external basis is not bound to its exact capability"
            )
        return
    record = index.get("architecture-review", basis.record_id)
    covered = () if record is None else record.payload.get("covered_diagnosis_ids", ())
    matching = tuple(
        diagnosis
        for diagnosis_id in covered
        if isinstance(diagnosis_id, str)
        and (diagnosis := index.get("study-diagnosis", diagnosis_id)) is not None
        and _diagnosis_binds_original_obligation(
            index, diagnosis=diagnosis, obligation=obligation
        )
    )
    if (
        record is None
        or record.subject != f"Mission:{obligation.governing_mission_id}"
        or record.payload.get("mission_id") != obligation.governing_mission_id
        or record.payload.get("system_architecture_family") != basis.subject_id
        or len(matching) != 1
        or not allowed_conditions.issubset(
            {
                ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL,
                ReplayResumeConditionKind.SAME_PROTOCOL_REPAIR,
            }
        )
    ):
        raise ReplayTransitionError(
            "pending replay architecture basis lacks exact covered provenance"
        )


def _require_in_progress_deferral_basis(
    index: LocalIndex,
    *,
    obligation: HistoricalReplayObligation,
    head: IndexRecord,
    deferral: ReplayDeferral,
) -> _DiagnosedReplayExecution | _DiagnosedReplayPreflightInvalidation:
    execution = deferral.execution_binding
    binding = head.payload.get("binding")
    if (
        execution is None
        or deferral.basis.kind is not ReplayDeferralBasisKind.STUDY_DIAGNOSIS
        or deferral.basis.record_id != execution.study_diagnosis_id
        or deferral.basis.subject_id != execution.replay_study_id
        or not isinstance(binding, Mapping)
        or binding.get("obligation_ids") != [obligation.identity]
        or binding.get("portfolio_decision_id") != execution.portfolio_decision_id
        or binding.get("replay_study_id") != execution.replay_study_id
        or binding.get("replay_executable_id") != execution.replay_executable_id
    ):
        raise ReplayTransitionError(
            "in-progress replay deferral lacks its exact execution binding"
        )
    study = index.get("study-open", execution.replay_study_id)
    trial = index.get("trial", execution.replay_executable_id)
    close_record = index.get(
        "study-close", execution.replay_study_close_record_id
    )
    diagnosis = index.get("study-diagnosis", execution.study_diagnosis_id)
    evidence_basis = (
        None if diagnosis is None else diagnosis.payload.get("evidence_basis")
    )
    completion_ids = (
        ()
        if not isinstance(evidence_basis, list)
        else tuple(
            item.get("record_id")
            for item in evidence_basis
            if isinstance(item, Mapping) and item.get("kind") == "job-completed"
        )
    )
    exact_completions = tuple(
        completion
        for completion_id in completion_ids
        if isinstance(completion_id, str)
        and (completion := index.get("job-completed", completion_id)) is not None
        and (
            declaration := index.get(
                "job-declared", completion.payload.get("job_id", "")
            )
        )
        is not None
        and declaration.payload.get("study_id") == execution.replay_study_id
        and declaration.payload.get("spec", {}).get("evidence_subject")
        == {"kind": "Executable", "id": execution.replay_executable_id}
    )
    preflight_ids = (
        ()
        if not isinstance(evidence_basis, list)
        else tuple(
            item.get("record_id")
            for item in evidence_basis
            if isinstance(item, Mapping)
            and item.get("kind") == "job-implementation-preflight"
        )
    )
    exact_preflights = tuple(
        preflight
        for preflight_id in preflight_ids
        if isinstance(preflight_id, str)
        and (
            preflight := index.get(
                "job-implementation-preflight",
                preflight_id,
            )
        )
        is not None
        and preflight.status == "rejected"
        and preflight.payload.get("schema")
        == "replay_job_implementation_preflight.v1"
        and preflight.payload.get("mission_id")
        == obligation.governing_mission_id
        and preflight.payload.get("study_id") == execution.replay_study_id
        and preflight.payload.get("replay_obligation_ids")
        == [obligation.identity]
        and execution.replay_executable_id
        in preflight.payload.get("executable_ids", [])
    )
    basis_references = (
        set()
        if not isinstance(evidence_basis, list)
        else {
            (item.get("kind"), item.get("record_id"))
            for item in evidence_basis
            if isinstance(item, Mapping)
        }
    )
    if (
        study is None
        or study.payload.get("mission_id") != obligation.governing_mission_id
        or study.payload.get("portfolio_decision_id")
        != execution.portfolio_decision_id
        or obligation.identity not in study.payload.get("replay_obligation_ids", [])
        or trial is None
        or trial.payload.get("study_id") != study.record_id
        or trial.payload.get("replay_obligation_ids") != [obligation.identity]
        or typed_replay_reference_executable_id(
            trial.payload.get("executable", {})
        )
        != obligation.original_executable_id
        or close_record is None
        or close_record.subject != f"Study:{study.record_id}"
        or close_record.status not in _STUDY_OUTCOMES
        or diagnosis is None
        or diagnosis.subject != f"Study:{study.record_id}"
        or diagnosis.payload.get("mission_id") != obligation.governing_mission_id
        or diagnosis.payload.get("study_id") != study.record_id
        or diagnosis.payload.get("study_close_record_id") != close_record.record_id
    ):
        raise ReplayTransitionError(
            "in-progress replay deferral lacks exact trial, close, and diagnosis"
        )
    if len(exact_completions) == 1 and not exact_preflights:
        if any(
            item.kind
            not in {
                ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL,
                ReplayResumeConditionKind.SAME_PROTOCOL_REPAIR,
            }
            for item in deferral.resume_conditions
        ):
            raise ReplayTransitionError(
                "in-progress replay deferral changes its diagnosed Job surface"
            )
        completion = exact_completions[0]
        declaration = index.get(
            "job-declared", completion.payload.get("job_id", "")
        )
        if declaration is None:
            raise ReplayTransitionError(
                "in-progress replay deferral lacks its diagnosed Job declaration"
            )
        return _DiagnosedReplayExecution(
            progress=head,
            study=study,
            trial=trial,
            close=close_record,
            diagnosis=diagnosis,
            completion=completion,
            declaration=declaration,
        )
    if len(exact_completions) != 0 or len(exact_preflights) != 1:
        raise ReplayTransitionError(
            "in-progress replay deferral mixes Job and preflight evidence"
        )
    preflight = exact_preflights[0]
    batch_id = trial.subject.removeprefix("Batch:")
    batch_closes = tuple(
        record
        for record in index.records_by_subject_status(
            f"Batch:{batch_id}",
            "not_evaluable",
        )
        if record.kind == "batch-close"
        and ("batch-close", record.record_id) in basis_references
    )
    batch_declarations = tuple(
        index.records_by_payload_text(
            "job-declared",
            "batch_id",
            batch_id,
        )
    )
    budget_head = index.event_head(f"batch-budget:{batch_id}")
    executable_manifests = preflight.payload.get("executable_manifests")
    current_manifest = trial.payload.get("executable")
    if (
        trial.subject != f"Batch:{batch_id}"
        or preflight.subject != f"Batch:{batch_id}"
        or preflight.payload.get("batch_id") != batch_id
        or preflight.payload.get("remediation_kind")
        != "replacement_required"
        or not isinstance(executable_manifests, list)
        or current_manifest not in executable_manifests
        or len(batch_closes) != 1
        or batch_declarations
        or budget_head is not None
        or batch_closes[0].payload.get("basis_record_id")
        != preflight.record_id
        or close_record.status not in {"evidence_gap", "not_evaluable"}
        or diagnosis.status != "engineering_gap"
        or diagnosis.payload.get("evidence_state") != "engineering_gap"
        or {item.kind for item in deferral.resume_conditions}
        != {ReplayResumeConditionKind.REPLACEMENT_PROSPECTIVE_IMPLEMENTATION}
        or any(
            item.protocol_id != preflight.payload.get("protocol_id")
            for item in deferral.resume_conditions
        )
        or type(preflight.authority_sequence) is not int
        or type(batch_closes[0].authority_sequence) is not int
        or type(close_record.authority_sequence) is not int
        or type(diagnosis.authority_sequence) is not int
        or not (
            preflight.authority_sequence
            < batch_closes[0].authority_sequence
            < close_record.authority_sequence
            < diagnosis.authority_sequence
        )
    ):
        raise ReplayTransitionError(
            "in-progress replay preflight deferral lacks exact engineering evidence"
        )
    return _DiagnosedReplayPreflightInvalidation(
        progress=head,
        study=study,
        trial=trial,
        close=close_record,
        diagnosis=diagnosis,
        preflight=preflight,
        batch_close=batch_closes[0],
    )


def prepare_deferral(
    index: LocalIndex,
    *,
    mission_id: str,
    deferrals: Sequence[ReplayDeferral],
) -> tuple[list[IndexRecord], dict[str, Any] | None, dict[str, Any]]:
    heads = {
        obligation.identity: (obligation, head)
        for obligation, head in obligation_heads(index, mission_id=mission_id)
    }
    deferred_ids = {item.obligation_id for item in deferrals}
    if not deferrals or len(deferred_ids) != len(deferrals):
        raise ReplayTransitionError("replay deferral request is empty or duplicated")
    records = []
    for deferral in deferrals:
        pair = heads.get(deferral.obligation_id)
        if (
            pair is None
            or pair[1].status
            not in {
                ReplayObligationStatus.PENDING.value,
                ReplayObligationStatus.IN_PROGRESS.value,
            }
        ):
            raise ReplayTransitionError(
                "replay deferral lacks an unresolved obligation"
            )
        obligation, head = pair
        _require_resume_condition_surface(
            obligation=obligation,
            deferral=deferral,
        )
        if head.status == ReplayObligationStatus.PENDING.value:
            _require_pending_deferral_basis(
                index,
                obligation=obligation,
                deferral=deferral,
            )
        else:
            _require_in_progress_deferral_basis(
                index,
                obligation=obligation,
                head=head,
                deferral=deferral,
            )
        records.append(
            deferral_record(
                obligation=obligation,
                deferral=deferral,
                prior_status=ReplayObligationStatus(head.status),
                sequence=(head.event_sequence or 0) + 1,
            )
        )
    constraints = constraints_for_pending_from_index(
        index,
        tuple(
        obligation
        for obligation, head in heads.values()
        if head.status == ReplayObligationStatus.PENDING.value
        and obligation.identity not in deferred_ids
        ),
    )
    return records, constraints, {
        "deferred_replay_obligation_ids": sorted(deferred_ids)
    }


def _require_later_trigger(
    *,
    deferral_head: IndexRecord,
    trigger: IndexRecord,
) -> None:
    if (
        type(deferral_head.authority_sequence) is not int
        or type(trigger.authority_sequence) is not int
        or trigger.authority_sequence <= deferral_head.authority_sequence
    ):
        raise ReplayTransitionError(
            "replay resume trigger must be durable and later than its deferral"
        )


def _require_development_material_trigger(
    index: LocalIndex,
    *,
    obligation: HistoricalReplayObligation,
    trigger_record_id: str,
) -> IndexRecord:
    trigger = index.get("development-material", trigger_record_id)
    authority_id = (
        None if trigger is None else trigger.payload.get("post_holdout_development_id")
    )
    authority = (
        None
        if not isinstance(authority_id, str)
        else index.get("post-holdout-development", authority_id)
    )
    shared_fields = (
        "material_content_sha256",
        "material_identity",
        "material_receipt_hash",
        "mission_id",
        "split_identity",
    )
    if (
        trigger is None
        or trigger.status != "accepted"
        or trigger.subject != f"Mission:{obligation.governing_mission_id}"
        or trigger.payload.get("mission_id") != obligation.governing_mission_id
        or trigger.payload.get("material_identity") != trigger.record_id
        or authority is None
        or authority.status != "accepted"
        or authority.subject != f"Material:{trigger.record_id}"
        or any(
            authority.payload.get(field) != trigger.payload.get(field)
            for field in shared_fields
        )
    ):
        raise ReplayTransitionError(
            "replay resume lacks exact newly registered development material"
        )
    return trigger


_JOB_WORK_FIELDS = (
    "callable_identity",
    "component_parity_binding",
    "evidence_subject",
    "external_dependency_binding",
    "holdout_binding",
    "input_hashes",
    "runtime_binding",
    "scientific_binding",
    "source_binding",
)


def _job_work_fingerprint(declaration: IndexRecord) -> str | None:
    spec = declaration.payload.get("spec")
    mission_id = declaration.payload.get("mission_id")
    if (
        not isinstance(spec, Mapping)
        or not isinstance(mission_id, str)
        or not isinstance(spec.get("scientific_binding"), Mapping)
    ):
        return None
    work = {name: spec.get(name) for name in _JOB_WORK_FIELDS}
    return canonical_digest(
        domain="job-work",
        payload={"mission_id": mission_id, "work": work},
    )


def _invalid_scientific_criterion_ids(
    completion: IndexRecord,
    condition: ReplayResumeCondition,
) -> tuple[str, ...] | None:
    scientific = completion.payload.get("scientific")
    adjudication = (
        None if not isinstance(scientific, Mapping) else scientific.get("adjudication")
    )
    if adjudication is None:
        return condition.criterion_ids
    if not isinstance(adjudication, Mapping):
        return None
    raw_criteria = adjudication.get("criteria")
    if not isinstance(raw_criteria, list):
        return condition.criterion_ids
    by_id: dict[str, Mapping[str, Any]] = {}
    for item in raw_criteria:
        if not isinstance(item, Mapping):
            return None
        criterion_id = item.get("criterion_id")
        if (
            not isinstance(criterion_id, str)
            or criterion_id in by_id
            or criterion_id not in condition.criterion_ids
        ):
            return None
        by_id[criterion_id] = item
    invalid = set(condition.criterion_ids) - set(by_id)
    invalid.update(
        criterion_id
        for criterion_id, item in by_id.items()
        if item.get("scientific_state") in {"invalid", "unresolved"}
        or item.get("comparison_state") == "not_evaluable"
    )
    if not invalid and adjudication.get("state") in {
        "not_evaluable",
        "unresolved",
    }:
        invalid.update(condition.criterion_ids)
    return tuple(sorted(invalid))


def _require_replacement_prospective_implementation_trigger(
    index: LocalIndex,
    *,
    obligation: HistoricalReplayObligation,
    deferral: ReplayDeferral,
    deferral_head: IndexRecord,
    condition: ReplayResumeCondition,
    trigger_record_id: str,
) -> IndexRecord:
    progress = (
        None
        if deferral_head.payload.get("prior_status")
        != ReplayObligationStatus.IN_PROGRESS.value
        or not isinstance(deferral_head.event_stream, str)
        or type(deferral_head.event_sequence) is not int
        or deferral_head.event_sequence < 2
        else index.event_record(
            deferral_head.event_stream,
            deferral_head.event_sequence - 1,
        )
    )
    if progress is None or progress.status != ReplayObligationStatus.IN_PROGRESS.value:
        raise ReplayTransitionError(
            "replacement implementation requires the exact deferred replay execution"
        )
    diagnosed = _require_in_progress_deferral_basis(
        index,
        obligation=obligation,
        head=progress,
        deferral=deferral,
    )
    if not isinstance(diagnosed, _DiagnosedReplayPreflightInvalidation):
        raise ReplayTransitionError(
            "replacement implementation lacks a diagnosed pre-Job invalidation"
        )
    trigger = index.get("job-implementation-preflight", trigger_record_id)
    manifests = (
        None if trigger is None else trigger.payload.get("executable_manifests")
    )
    executable_ids = (
        None if trigger is None else trigger.payload.get("executable_ids")
    )
    references = (
        ()
        if not isinstance(manifests, list)
        else tuple(
            typed_replay_reference_executable_id(manifest)
            for manifest in manifests
            if isinstance(manifest, Mapping)
        )
    )
    trigger_head = (
        None
        if trigger is None or not isinstance(trigger.event_stream, str)
        else index.event_head(trigger.event_stream)
    )
    from axiom_rift.operations.replay_job_implementation_preflight import (
        ReplayJobImplementationPreflightError,
        require_replacement_replay_job_scientific_surface,
    )

    try:
        require_replacement_replay_job_scientific_surface(
            prior_preflight_id=diagnosed.preflight.record_id,
            prior_payload=diagnosed.preflight.payload,
            replacement_payload=(
                {} if trigger is None else trigger.payload
            ),
        )
    except ReplayJobImplementationPreflightError as exc:
        raise ReplayTransitionError(
            "replacement implementation scientific surface is malformed"
        ) from exc
    if (
        trigger is None
        or trigger.status != "accepted"
        or trigger.payload.get("schema")
        != "replay_job_implementation_preflight.v1"
        or trigger.payload.get("outcome") != "accepted"
        or trigger.payload.get("mission_id") != obligation.governing_mission_id
        or trigger.payload.get("batch_id") is not None
        or trigger.payload.get("study_id") is not None
        or trigger.payload.get("replacement_for_preflight_id")
        != diagnosed.preflight.record_id
        or trigger.payload.get("replay_obligation_ids") != [obligation.identity]
        or trigger.payload.get("protocol_id") != condition.protocol_id
        or not isinstance(executable_ids, list)
        or len(executable_ids) != len(set(executable_ids))
        or not isinstance(manifests, list)
        or len(manifests) != len(executable_ids)
        or tuple(sorted(references)) != condition.original_executable_ids
        or any(reference is None for reference in references)
        or not isinstance(trigger.payload.get("source_closure_authority"), Mapping)
        or trigger.payload.get("failure_fingerprint") is not None
        or trigger.payload.get("reason_code") is not None
        or trigger.payload.get("remediation_kind") is not None
        or trigger_head is None
        or trigger_head.record_id != trigger.record_id
        or trigger.event_stream
        != (
            "replay-job-implementation-preflight-replacement:"
            + diagnosed.preflight.record_id
        )
    ):
        raise ReplayTransitionError(
            "replay resume lacks exact accepted replacement implementation preflight"
        )
    return trigger


def _require_same_protocol_repair_trigger(
    index: LocalIndex,
    *,
    obligation: HistoricalReplayObligation,
    deferral: ReplayDeferral,
    deferral_head: IndexRecord,
    condition: ReplayResumeCondition,
    trigger_record_id: str,
    repair_provenance: Callable[
        [IndexRecord, IndexRecord, IndexRecord, IndexRecord],
        ReplayRepairProvenance,
    ]
    | None,
) -> IndexRecord:
    progress = (
        None
        if deferral_head.payload.get("prior_status")
        != ReplayObligationStatus.IN_PROGRESS.value
        or not isinstance(deferral_head.event_stream, str)
        or type(deferral_head.event_sequence) is not int
        or deferral_head.event_sequence < 2
        else index.event_record(
            deferral_head.event_stream, deferral_head.event_sequence - 1
        )
    )
    if progress is None or progress.status != ReplayObligationStatus.IN_PROGRESS.value:
        raise ReplayTransitionError(
            "same-protocol repair requires the exact deferred replay execution"
        )
    diagnosed = _require_in_progress_deferral_basis(
        index,
        obligation=obligation,
        head=progress,
        deferral=deferral,
    )
    if not isinstance(diagnosed, _DiagnosedReplayExecution):
        raise ReplayTransitionError(
            "same-protocol Job repair lacks a diagnosed Job completion"
        )
    trigger = index.get("job-completed", trigger_record_id)
    declaration = (
        None
        if trigger is None
        else index.get("job-declared", trigger.payload.get("job_id", ""))
    )
    previous_completion = (
        None
        if declaration is None
        or not isinstance(declaration.event_stream, str)
        or type(declaration.event_sequence) is not int
        or declaration.event_sequence < 2
        else index.event_record(
            declaration.event_stream, declaration.event_sequence - 1
        )
    )
    previous_declaration = (
        None
        if previous_completion is None
        else index.get(
            "job-declared", previous_completion.payload.get("job_id", "")
        )
    )
    spec = None if declaration is None else declaration.payload.get("spec")
    previous_spec = (
        None if previous_declaration is None else previous_declaration.payload.get("spec")
    )
    work_fingerprint = (
        None if declaration is None else _job_work_fingerprint(declaration)
    )
    previous_work_fingerprint = (
        None
        if previous_declaration is None
        else _job_work_fingerprint(previous_declaration)
    )
    scientific_binding = (
        None if not isinstance(spec, Mapping) else spec.get("scientific_binding")
    )
    previous_scientific_binding = (
        None
        if not isinstance(previous_spec, Mapping)
        else previous_spec.get("scientific_binding")
    )
    attempt_head = (
        None
        if declaration is None or not isinstance(declaration.event_stream, str)
        else index.event_head(declaration.event_stream)
    )
    failure = diagnosed.completion.payload.get("failure")
    invalid_criteria = _invalid_scientific_criterion_ids(
        diagnosed.completion,
        condition,
    )
    operational_failure = (
        diagnosed.completion.status == "failed"
        and isinstance(failure, Mapping)
        and isinstance(failure.get("failure_signature"), str)
    )
    scientific_invalidity = (
        diagnosed.completion.status == "success"
        and diagnosed.close.status in {"not_evaluable", "evidence_gap"}
        and diagnosed.diagnosis.status in {"not_identifiable", "engineering_gap"}
        and invalid_criteria is not None
        and bool(invalid_criteria)
    )
    execution = deferral.execution_binding
    if (
        execution is None
        or trigger is None
        or trigger.status != "success"
        or declaration is None
        or declaration.payload.get("mission_id") != obligation.governing_mission_id
        or declaration.payload.get("study_id") != execution.replay_study_id
        or not isinstance(spec, Mapping)
        or spec.get("evidence_subject")
        != {"kind": "Executable", "id": execution.replay_executable_id}
        or not isinstance(spec.get("changed_cause_proof_hash"), str)
        or previous_completion is None
        or previous_completion.record_id != diagnosed.completion.record_id
        or previous_completion.kind != "job-completed"
        or previous_completion.status not in {"failed", "success"}
        or previous_declaration is None
        or previous_declaration.record_id != diagnosed.declaration.record_id
        or previous_declaration.payload.get("mission_id")
        != obligation.governing_mission_id
        or previous_declaration.payload.get("study_id") != execution.replay_study_id
        or not isinstance(previous_spec, Mapping)
        or previous_spec.get("evidence_subject")
        != {"kind": "Executable", "id": execution.replay_executable_id}
        or spec.get("implementation_identity")
        == previous_spec.get("implementation_identity")
        or not isinstance(scientific_binding, Mapping)
        or scientific_binding != previous_scientific_binding
        or work_fingerprint is None
        or work_fingerprint != previous_work_fingerprint
        or declaration.payload.get("work_fingerprint") != work_fingerprint
        or previous_declaration.payload.get("work_fingerprint") != work_fingerprint
        or declaration.event_stream != f"job-attempt:{work_fingerprint}"
        or previous_declaration.event_stream != declaration.event_stream
        or trigger.event_stream != declaration.event_stream
        or type(trigger.event_sequence) is not int
        or trigger.event_sequence <= declaration.event_sequence
        or attempt_head is None
        or attempt_head.record_id != trigger.record_id
        or not (operational_failure or scientific_invalidity)
        or type(diagnosed.completion.authority_sequence) is not int
        or type(deferral_head.authority_sequence) is not int
        or type(declaration.authority_sequence) is not int
        or type(trigger.authority_sequence) is not int
        or diagnosed.completion.authority_sequence
        >= deferral_head.authority_sequence
        or declaration.authority_sequence <= deferral_head.authority_sequence
        or trigger.authority_sequence <= declaration.authority_sequence
        or condition.criterion_ids != obligation.criterion_ids
    ):
        raise ReplayTransitionError(
            "replay resume lacks the exact diagnosed same-protocol repair lineage"
        )
    if repair_provenance is None:
        raise ReplayTransitionError(
            "same-protocol repair lacks Writer-verified artifact provenance"
        )
    try:
        provenance = repair_provenance(
            diagnosed.completion,
            diagnosed.declaration,
            declaration,
            diagnosed.diagnosis,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayProjectionError(
            "replay repair artifact provenance cannot be resolved"
        ) from exc
    if (
        not isinstance(provenance, ReplayRepairProvenance)
        or provenance.prior_completion_record_id != diagnosed.completion.record_id
        or provenance.study_diagnosis_id != diagnosed.diagnosis.record_id
        or provenance.protocol_id != condition.protocol_id
        or provenance.validation_plan_hash
        != scientific_binding.get("validation_plan_hash")
        or provenance.criterion_ids != condition.criterion_ids
        or provenance.previous_implementation_identity
        != previous_spec.get("implementation_identity")
        or provenance.repaired_implementation_identity
        != spec.get("implementation_identity")
        or provenance.changed_cause_proof_hash
        != spec.get("changed_cause_proof_hash")
        or provenance.basis_kind
        != (
            ReplayRepairBasisKind.OPERATIONAL_FAILURE
            if operational_failure
            else ReplayRepairBasisKind.SCIENTIFIC_INVALIDITY
        )
        or provenance.prior_failure_signature
        != (
            failure.get("failure_signature")
            if operational_failure and isinstance(failure, Mapping)
            else None
        )
        or provenance.invalid_criterion_ids
        != (() if operational_failure else invalid_criteria)
    ):
        raise ReplayTransitionError(
            "replay repair provenance changes protocol, criteria, or implementation"
        )
    return trigger


def _require_replacement_source_trigger(
    index: LocalIndex,
    *,
    obligation: HistoricalReplayObligation,
    deferral: ReplayDeferral,
    trigger_record_id: str,
) -> IndexRecord:
    trigger = index.get("source-state", trigger_record_id)
    source_id = (
        None
        if trigger is None
        else trigger.subject.removeprefix("Source:")
    )
    old_invalidation = index.get(
        "source-authority-invalidation", deferral.basis.record_id
    )
    old_state_id = (
        None
        if old_invalidation is None
        else old_invalidation.payload.get("eligible_source_state_record_id")
    )
    old_state = (
        None
        if not isinstance(old_state_id, str)
        else index.get("source-state", old_state_id)
    )
    old_contract = None if old_state is None else old_state.payload.get("contract")
    new_contract = None if trigger is None else trigger.payload.get("contract")
    source_head = (
        None
        if not isinstance(source_id, str)
        else index.event_head(f"source:{source_id}")
    )
    if (
        trigger is None
        or trigger.status not in {"historical_audited", "runtime_eligible"}
        or source_id == deferral.basis.subject_id
        or source_head is None
        or source_head.record_id != trigger.record_id
        or not isinstance(old_contract, Mapping)
        or not isinstance(new_contract, Mapping)
        or new_contract.get("canonical_instrument")
        != old_contract.get("canonical_instrument")
        or new_contract.get("source_type") != old_contract.get("source_type")
        or canonical_digest(domain="source-contract", payload=new_contract)
        != source_id.removeprefix("source:")
    ):
        raise ReplayTransitionError(
            "replay resume lacks a current replacement SourceContract"
        )
    return trigger


def _require_external_available_trigger(
    index: LocalIndex,
    *,
    obligation: HistoricalReplayObligation,
    condition: ReplayResumeCondition,
    trigger_record_id: str,
) -> IndexRecord:
    trigger = index.get("external-dependency-attempt", trigger_record_id)
    external = None if trigger is None else trigger.payload.get("external")
    completion_id = None if trigger is None else trigger.payload.get("completion_record_id")
    completion = (
        None
        if not isinstance(completion_id, str)
        else index.get("job-completed", completion_id)
    )
    dependency_head = (
        None
        if condition.subject_id is None
        else index.event_head(f"external-dependency:{condition.subject_id}")
    )
    if (
        trigger is None
        or trigger.status != "available"
        or trigger.subject != f"Mission:{obligation.governing_mission_id}"
        or trigger.payload.get("dependency_id") != condition.subject_id
        or trigger.payload.get("blocked_mission_capability")
        != replay_obligation_capability_id(obligation.identity)
        or not isinstance(external, Mapping)
        or external.get("dependency_id") != condition.subject_id
        or external.get("blocked_mission_capability")
        != replay_obligation_capability_id(obligation.identity)
        or external.get("verdict") != "passed"
        or completion is None
        or completion.status != "success"
        or dependency_head is None
        or dependency_head.record_id != trigger.record_id
    ):
        raise ReplayTransitionError(
            "replay resume lacks current validated external availability"
        )
    return trigger


def prepare_resume(
    index: LocalIndex,
    *,
    mission_id: str,
    resumes: Sequence[ReplayResumeEvidence],
    repair_provenance: Callable[
        [IndexRecord, IndexRecord, IndexRecord, IndexRecord],
        ReplayRepairProvenance,
    ]
    | None = None,
) -> tuple[list[IndexRecord], dict[str, Any] | None, dict[str, Any]]:
    """Requeue exact deferred obligations without granting scientific credit."""

    heads = {
        obligation.identity: (obligation, head)
        for obligation, head in obligation_heads(index, mission_id=mission_id)
    }
    resumed_ids = {item.obligation_id for item in resumes}
    if not resumes or len(resumed_ids) != len(resumes):
        raise ReplayTransitionError("replay resume request is empty or duplicated")
    records: list[IndexRecord] = []
    for evidence in resumes:
        pair = heads.get(evidence.obligation_id)
        if (
            pair is None
            or pair[1].status != ReplayObligationStatus.DEFERRED.value
            or pair[1].record_id != evidence.deferral_id
        ):
            raise ReplayTransitionError(
                "replay resume does not target the exact current deferral"
            )
        obligation, head = pair
        raw = head.payload.get("resolution")
        try:
            deferral = replay_deferral_from_identity_payload(raw)
        except (TypeError, ValueError) as exc:
            raise ReplayProjectionError(
                "current replay deferral projection is malformed"
            ) from exc
        if (
            deferral.identity != head.record_id
            or deferral.obligation_id != obligation.identity
        ):
            raise ReplayProjectionError(
                "current replay deferral differs from its stream head"
            )
        _require_resume_condition_surface(
            obligation=obligation,
            deferral=deferral,
        )
        condition = next(
            (
                item
                for item in deferral.resume_conditions
                if item.identity == evidence.resume_condition_id
            ),
            None,
        )
        if condition is None:
            raise ReplayTransitionError(
                "replay resume condition was not stored by the exact deferral"
            )
        if condition.kind is ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL:
            trigger = _require_development_material_trigger(
                index,
                obligation=obligation,
                trigger_record_id=evidence.trigger_record_id,
            )
        elif condition.kind is ReplayResumeConditionKind.SAME_PROTOCOL_REPAIR:
            trigger = _require_same_protocol_repair_trigger(
                index,
                obligation=obligation,
                deferral=deferral,
                deferral_head=head,
                condition=condition,
                trigger_record_id=evidence.trigger_record_id,
                repair_provenance=repair_provenance,
            )
        elif condition.kind is (
            ReplayResumeConditionKind.REPLACEMENT_PROSPECTIVE_IMPLEMENTATION
        ):
            trigger = _require_replacement_prospective_implementation_trigger(
                index,
                obligation=obligation,
                deferral=deferral,
                deferral_head=head,
                condition=condition,
                trigger_record_id=evidence.trigger_record_id,
            )
        elif condition.kind is ReplayResumeConditionKind.REPLACEMENT_SOURCE_CONTRACT:
            trigger = _require_replacement_source_trigger(
                index,
                obligation=obligation,
                deferral=deferral,
                trigger_record_id=evidence.trigger_record_id,
            )
        else:
            trigger = _require_external_available_trigger(
                index,
                obligation=obligation,
                condition=condition,
                trigger_record_id=evidence.trigger_record_id,
            )
        _require_later_trigger(deferral_head=head, trigger=trigger)
        records.append(
            resume_record(
                obligation=obligation,
                evidence=evidence,
                sequence=(head.event_sequence or 0) + 1,
            )
        )
    constraints = constraints_for_pending_from_index(
        index,
        tuple(
        obligation
        for obligation, head in heads.values()
        if head.status == ReplayObligationStatus.PENDING.value
        or obligation.identity in resumed_ids
        ),
    )
    return records, constraints, {
        "resume_condition_ids": sorted(
            item.resume_condition_id for item in resumes
        ),
        "resume_trigger_record_ids": sorted(
            item.trigger_record_id for item in resumes
        ),
        "resumed_replay_obligation_ids": sorted(resumed_ids),
        "scientific_claim_delta": 0,
        "scientific_satisfaction_delta": 0,
        "scientific_trial_delta": 0,
    }


__all__ = [
    "ReplayAuthorityError",
    "ReplayMultiplicityBindingError",
    "ReplayProjectionError",
    "ReplayTransitionError",
    "build_correction_plan",
    "build_explicit_historical_replay_correction_audit_plan",
    "build_satisfaction_invalidation_plan",
    "constraints_for_pending",
    "constraints_for_pending_from_index",
    "current_replay_priority_escalation",
    "derive_obligation_from_record",
    "effective_replay_priority",
    "initial_obligation_record",
    "obligation_heads",
    "prepare_correction",
    "prepare_audit_only_scope_overlay",
    "prepare_audit_only_scope_overlays",
    "prepare_deferral",
    "prepare_execution_progress",
    "prepare_resume",
    "prepare_resolution",
    "prepare_satisfaction_invalidation",
    "replay_obligation_capability_id",
    "replay_priority_escalation_record",
    "replay_priority_stream",
    "require_diagnosed_replay",
    "require_recorded_satisfaction",
    "require_satisfaction_invalidation_record",
    "require_study_execution_complete",
    "require_study_pending",
    "scheduler_constraints",
    "validate_decision_selection",
    "validate_replay_review_basis",
    "validate_snapshot_scheduler_projection",
    "with_scheduler_constraints",
]
