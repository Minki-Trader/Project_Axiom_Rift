"""Durable read projection and record preparation for historical replay.

The scientific types and state-machine vocabulary live in
``research.replay_obligation``.  This adapter verifies their Journal-backed
SQLite projection and prepares immutable records.  It never writes control,
the Journal, or the index; StateWriter owns the single commit boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.evidence_scope_projection import (
    evidence_scope_overlay_record,
    evidence_scope_stream,
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
    ReplayRepairBasisKind,
    ReplayRepairProvenance,
    ReplayResolutionScope,
    ReplayResumeCondition,
    ReplayResumeConditionKind,
    ReplayResumeEvidence,
    ReplaySatisfaction,
    derive_historical_replay_obligation,
    historical_replay_obligation_from_identity_payload,
    replay_deferral_from_identity_payload,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
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


@dataclass(frozen=True, slots=True)
class _DiagnosedReplayExecution:
    progress: IndexRecord
    study: IndexRecord
    trial: IndexRecord
    close: IndexRecord
    diagnosis: IndexRecord
    completion: IndexRecord
    declaration: IndexRecord


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
    index: LocalIndex,
    *,
    mission_id: str,
) -> tuple[tuple[HistoricalReplayObligation, IndexRecord], ...]:
    """Return exact current heads for one Mission's replay obligations."""

    resolved: list[tuple[HistoricalReplayObligation, IndexRecord]] = []
    for initial in index.records_by_kind("historical-replay-obligation"):
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
            or initial.subject != f"Mission:{mission_id}"
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
) -> dict[str, Any] | None:
    pending = tuple(obligations)
    if not pending:
        return None
    priority = (
        ReplayPriority.P0
        if any(item.replay_priority is ReplayPriority.P0 for item in pending)
        else ReplayPriority.P1
    )
    return {
        "pending_replay_obligation_ids": sorted(
            item.identity for item in pending if item.replay_priority is priority
        ),
        "required_replay_priority": priority.value,
    }


def scheduler_constraints(
    index: LocalIndex,
    *,
    mission_id: str,
) -> dict[str, Any] | None:
    return constraints_for_pending(
        obligation
        for obligation, head in obligation_heads(index, mission_id=mission_id)
        if head.status == ReplayObligationStatus.PENDING.value
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

    constraints = scheduler_constraints(index, mission_id=mission_id)
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
    selected = set(replay_obligation_ids)
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
        if diagnosis_cleanup:
            pass
        elif action in work_actions and not selected:
            raise ReplayTransitionError(
                "scientific work cannot bypass the highest-priority replay queue"
            )
        if action not in work_actions and (action != "new_mechanism" or selected):
            raise ReplayTransitionError(
                "pending replay permits only bound work or a new-mechanism bridge"
            )
    elif selected:
        raise ReplayTransitionError(
            "Portfolio Decision replay binding lacks scheduler authority"
        )
    return constraints


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


def prepare_execution_progress(
    index: LocalIndex,
    *,
    study_record: IndexRecord,
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

    if not isinstance(executable_payload, Mapping):
        raise ReplayProjectionError("replay Executable manifest is malformed")
    parameters = executable_payload.get("parameters")
    manifests = executable_payload.get("component_manifests")
    if not isinstance(parameters, Mapping) or not isinstance(manifests, list):
        return None
    reference = parameters.get("historical_reference_executable_id")
    declarations = tuple(
        item
        for item in manifests
        if isinstance(item, Mapping)
        and isinstance(item.get("spec"), Mapping)
        and "historical_reference_executable_id"
        in item["spec"].get("parameter_fields", [])
    )
    if reference is None and not declarations:
        return None
    if (
        type(reference) is not str
        or not reference.startswith("executable:")
        or len(reference) != len("executable:") + 64
        or any(char not in "0123456789abcdef" for char in reference.split(":", 1)[1])
        or len(declarations) != 1
    ):
        raise ReplayTransitionError(
            "replay Executable historical reference is not one typed component field"
        )
    return reference


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


def _require_scientific_satisfaction_evidence(
    index: LocalIndex,
    *,
    obligation: HistoricalReplayObligation,
    satisfaction: ReplaySatisfaction,
    diagnosis: IndexRecord,
) -> None:
    """Recompute the admissibility of a scientific replay resolution.

    The completion was derived by Writer at Job close, but resolution is a
    separate authority boundary.  Rechecking its exact registered-validator,
    subject, historical-definition, and criterion-state bindings prevents a
    caller-created ``ReplaySatisfaction`` from becoming a capability.
    """

    from axiom_rift.research.validation_v2 import (
        SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    )

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
        or binding.get("validator_id")
        != SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
        or scientific.get("validator_id")
        != SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
        or scientific.get("validation_plan_hash")
        != binding.get("validation_plan_hash")
        or scientific.get("scientific_eligible") is not True
        or scientific.get("candidate_eligible") is not False
        or not isinstance(trace, Mapping)
        or trace.get("validator_id")
        != SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
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


def require_satisfaction(
    index: LocalIndex,
    *,
    obligation: HistoricalReplayObligation,
    satisfaction: ReplaySatisfaction,
    allow_legacy_decision_binding: bool,
) -> None:
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
    executable_payload = trial.payload.get("executable")
    if not isinstance(executable_payload, dict) or not payload_contains_exact_value(
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
        )


def build_correction_plan(
    index: LocalIndex,
    *,
    mission_id: str,
    adjudication_record_ids: Sequence[str],
    replay_study_id: str,
) -> dict[str, Any]:
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
    constraints = constraints_for_pending(
        obligation
        for obligation, head in heads.values()
        if head.status == ReplayObligationStatus.PENDING.value
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
    trial = index.get("trial", obligation.original_executable_id)
    completion = index.get(
        "job-completed", obligation.original_completion_record_id
    )
    declaration = (
        None
        if completion is None
        else index.get("job-declared", completion.payload.get("job_id", ""))
    )
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
        and trial is not None
        and trial.payload.get("study_id") == obligation.original_study_id
        and completion is not None
        and declaration is not None
        and declaration.payload.get("study_id") == obligation.original_study_id
        and declaration.payload.get("spec", {}).get("evidence_subject")
        == {"kind": "Executable", "id": obligation.original_executable_id}
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
) -> _DiagnosedReplayExecution:
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
        or len(exact_completions) != 1
        or any(
            item.kind
            not in {
                ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL,
                ReplayResumeConditionKind.SAME_PROTOCOL_REPAIR,
            }
            for item in deferral.resume_conditions
        )
    ):
        raise ReplayTransitionError(
            "in-progress replay deferral lacks exact trial, close, and diagnosis"
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
    constraints = constraints_for_pending(
        obligation
        for obligation, head in heads.values()
        if head.status == ReplayObligationStatus.PENDING.value
        and obligation.identity not in deferred_ids
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
    constraints = constraints_for_pending(
        obligation
        for obligation, head in heads.values()
        if head.status == ReplayObligationStatus.PENDING.value
        or obligation.identity in resumed_ids
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
    "ReplayProjectionError",
    "ReplayTransitionError",
    "build_correction_plan",
    "constraints_for_pending",
    "derive_obligation_from_record",
    "initial_obligation_record",
    "obligation_heads",
    "prepare_correction",
    "prepare_audit_only_scope_overlay",
    "prepare_audit_only_scope_overlays",
    "prepare_deferral",
    "prepare_execution_progress",
    "prepare_resume",
    "prepare_resolution",
    "replay_obligation_capability_id",
    "require_diagnosed_replay",
    "require_study_execution_complete",
    "require_study_pending",
    "scheduler_constraints",
    "validate_decision_selection",
    "with_scheduler_constraints",
]
