"""Read-only durable projection adapter for current Portfolio axis status.

Portfolio snapshots stay immutable.  This module joins later source
invalidations, historical replay streams, and audit-only evidence-scope
overlays to the exact Executable/Study/axis lineage they affect.  A malformed
or ambiguous join fails closed instead of silently blocking or freeing the
wrong branch of the research forest.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.evidence_scope_projection import (
    EvidenceScopeProjectionError,
    effective_completion_evidence_scope,
)
from axiom_rift.operations.replay_projection import (
    ReplayAuthorityError,
    ReplayProjectionError,
    obligation_heads,
    require_satisfaction,
)
from axiom_rift.research.effective_axis import (
    EffectiveAxisResolution,
    EvidenceScopeAxisBinding,
    ReplayAxisBinding,
    SourceInvalidationBinding,
    SourceReplacementBinding,
    resolve_effective_axis,
)
from axiom_rift.research.effective_evidence_scope import (
    EvidenceScopeError,
    HistoricalEvidenceScopeOverlay,
    historical_evidence_scope_from_payload,
)
from axiom_rift.research.replay_obligation import (
    HistoricalReplayObligation,
    ReplayDeferral,
    ReplayExecutionBinding,
    ReplayObligationStatus,
    ReplayResolutionScope,
    ReplaySatisfaction,
    historical_replay_obligation_from_identity_payload,
    replay_deferral_from_identity_payload,
)
from axiom_rift.research.source_authority import (
    SourceAuthorityAuditManifest,
    SourceAuthorityInvalidation,
    SourceAuthorityLatch,
    SourceReplacementLineage,
)
from axiom_rift.research.sources import (
    SourceContract,
    SourceEligibilityReceipt,
    SourceEligibilityState,
    SourceTransitionEvidence,
    SourceType,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


class EffectiveAxisProjectionError(RuntimeError):
    """Durable axis, replay, scope, or source authority is malformed."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise EffectiveAxisProjectionError(f"{name} must be non-empty ASCII")
    return value


def _identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    digest = text.removeprefix(prefix)
    if text == digest or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise EffectiveAxisProjectionError(f"{name} must use {prefix}<sha256>")
    return text


def _axis_source_lineage(index: LocalIndex) -> dict[str, set[str]]:
    record_count = index.record_count()
    cached = getattr(index, "_axiom_axis_source_lineage_cache", None)
    if (
        isinstance(cached, tuple)
        and len(cached) == 2
        and cached[0] == record_count
        and isinstance(cached[1], dict)
    ):
        return cached[1]
    lineage: dict[str, set[str]] = {}

    def register(identity: object, executable: object) -> None:
        if identity is None and executable is None:
            return
        if identity is None:
            raise EffectiveAxisProjectionError(
                "Executable source lineage lacks its axis identity"
            )
        typed_identity = _identity("axis source-lineage identity", identity, "axis:")
        if executable is None:
            return
        if not isinstance(executable, Mapping):
            raise EffectiveAxisProjectionError("axis source lineage is malformed")
        sources = executable.get("source_contracts", ())
        if not isinstance(sources, list):
            raise EffectiveAxisProjectionError("axis source lineage is malformed")
        if sources != sorted(set(sources)) or any(
            type(source_id) is not str for source_id in sources
        ):
            raise EffectiveAxisProjectionError(
                "axis source lineage is not unique and canonical"
            )
        for source_id in sources:
            _identity("axis source contract", source_id, "source:")
        lineage.setdefault(typed_identity, set()).update(sources)

    for decision in index.records_by_kind("portfolio-decision"):
        register(
            decision.payload.get("target_axis_identity"),
            decision.payload.get("baseline_executable"),
        )
    for study in index.records_by_kind("study-open"):
        controlled = study.payload.get("controlled_chassis")
        baseline = (
            None
            if controlled is None
            else controlled.get("baseline_executable")
            if isinstance(controlled, Mapping)
            else controlled
        )
        register(study.payload.get("portfolio_axis_identity"), baseline)
    for trial in index.records_by_kind("trial"):
        register(
            trial.payload.get("portfolio_axis_identity"),
            trial.payload.get("executable"),
        )
    setattr(index, "_axiom_axis_source_lineage_cache", (record_count, lineage))
    return lineage


def axis_source_contract_ids(
    index: LocalIndex,
    axis: Mapping[str, Any],
) -> tuple[str, ...]:
    """Derive immutable source lineage from all durable axis executions."""

    axis_identity = _identity(
        "Portfolio axis identity", axis.get("axis_identity"), "axis:"
    )
    return tuple(sorted(_axis_source_lineage(index).get(axis_identity, set())))


def _source_contract_state(
    index: LocalIndex,
    *,
    source_id: str,
    state_record_id: str,
    eligible_required: bool,
) -> tuple[IndexRecord, SourceContract]:
    """Rebuild one canonical source state used by replacement authority."""

    _identity("source replacement SourceContract", source_id, "source:")
    record = index.get("source-state", state_record_id)
    allowed_states = {
        SourceEligibilityState.HISTORICAL_AUDITED.value,
        SourceEligibilityState.RUNTIME_ELIGIBLE.value,
    }
    if not eligible_required:
        allowed_states.add(SourceEligibilityState.CONTEXT_ONLY.value)
    contract_payload = (
        None if record is None else record.payload.get("contract")
    )
    try:
        contract = SourceContract(
            display_name="source-replacement-projection",
            canonical_instrument=contract_payload["canonical_instrument"],
            runtime_identifier=contract_payload["runtime_identifier"],
            source_type=SourceType(contract_payload["source_type"]),
            instrument_semantics=contract_payload["instrument_semantics"],
            mapping_semantics=contract_payload["mapping_semantics"],
            schema_semantics=contract_payload["schema_semantics"],
            field_semantics=contract_payload["field_semantics"],
            clock_semantics=contract_payload["clock_semantics"],
            availability_semantics=contract_payload["availability_semantics"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectiveAxisProjectionError(
            "source replacement SourceContract state is malformed"
        ) from exc
    sequence = None if record is None else record.event_sequence
    expected_id = (
        None
        if record is None or sequence is None
        else canonical_digest(
            domain="source-state",
            payload={
                "source_id": source_id,
                "state": record.status,
                "ordinal": sequence,
                "evidence_receipt_id": record.payload.get(
                    "evidence_receipt_id"
                ),
            },
        )
    )
    if (
        record is None
        or record.status not in allowed_states
        or record.subject != f"Source:{source_id}"
        or record.fingerprint != source_id
        or record.event_stream != f"source:{source_id}"
        or sequence is None
        or sequence < 1
        or record.payload.get("ordinal") != sequence
        or record.record_id != expected_id
        or contract.source_contract_id != source_id
        or contract.to_identity_payload() != contract_payload
        or record.payload.get("contract_hash") != source_id.removeprefix("source:")
        or record.payload.get("mapping_identity") != contract.mapping_identity
        or record.payload.get("schema_identity") != contract.schema_identity
        or record.payload.get("field_identity") != contract.field_identity
        or record.payload.get("clock_identity") != contract.clock_identity
        or record.payload.get("availability_identity")
        != contract.availability_identity
    ):
        raise EffectiveAxisProjectionError(
            "source replacement SourceContract state is not canonical"
        )
    receipt_payload = record.payload.get("receipt")
    evidence_receipt_id = record.payload.get("evidence_receipt_id")
    transition = record.payload.get("transition_evidence")
    if record.status == SourceEligibilityState.CONTEXT_ONLY.value:
        if any(
            value is not None
            for value in (receipt_payload, evidence_receipt_id, transition)
        ):
            raise EffectiveAxisProjectionError(
                "context-only source replacement state carries evidence"
            )
        return record, contract
    try:
        receipt = SourceEligibilityReceipt(
            source_contract_id=receipt_payload["source_contract_id"],
            evidence=SourceTransitionEvidence(receipt_payload["evidence"]),
            producer_completion_id=receipt_payload["producer_completion_id"],
            observed_at_utc=receipt_payload["observed_at_utc"],
            artifact_hashes=tuple(receipt_payload["artifact_hashes"]),
            facts=receipt_payload["facts"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectiveAxisProjectionError(
            "source replacement eligibility receipt is malformed"
        ) from exc
    legal_evidence = (
        receipt.evidence is SourceTransitionEvidence.HISTORICAL_AUDIT
        if record.status == SourceEligibilityState.HISTORICAL_AUDITED.value
        else receipt.evidence
        in {
            SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
            SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION,
        }
    )
    if (
        receipt.source_contract_id != source_id
        or receipt.identity != evidence_receipt_id
        or receipt.to_identity_payload() != receipt_payload
        or transition != receipt.evidence.value
        or not legal_evidence
    ):
        raise EffectiveAxisProjectionError(
            "source replacement eligibility receipt is not canonical"
        )
    return record, contract


def validate_source_replacement_lineage(
    index: LocalIndex,
    lineage: SourceReplacementLineage,
    *,
    require_current_replacement_source: bool,
) -> SourceReplacementBinding:
    """Verify the exact invalidation, source-state, and two-axis lineage."""

    if not isinstance(lineage, SourceReplacementLineage):
        raise EffectiveAxisProjectionError(
            "source replacement lineage is not typed"
        )
    snapshot = index.get("portfolio-snapshot", lineage.portfolio_snapshot_id)
    raw_axes = None if snapshot is None else snapshot.payload.get("axes")
    if (
        snapshot is None
        or snapshot.subject != f"Mission:{lineage.mission_id}"
        or not isinstance(raw_axes, list)
    ):
        raise EffectiveAxisProjectionError(
            "source replacement Portfolio snapshot is unavailable"
        )
    axes = {
        axis.get("axis_id"): axis
        for axis in raw_axes
        if isinstance(axis, Mapping) and isinstance(axis.get("axis_id"), str)
    }
    original_axis = axes.get(lineage.original_axis_id)
    replacement_axis = axes.get(lineage.replacement_axis_id)
    if (
        len(axes) != len(raw_axes)
        or original_axis is None
        or replacement_axis is None
        or original_axis.get("axis_identity") != lineage.original_axis_identity
        or replacement_axis.get("axis_identity")
        != lineage.replacement_axis_identity
        or replacement_axis.get("status") not in {"open", "preserved"}
    ):
        raise EffectiveAxisProjectionError(
            "source replacement axes are missing, stale, or not schedulable"
        )
    original_sources = set(axis_source_contract_ids(index, original_axis))
    replacement_sources = set(axis_source_contract_ids(index, replacement_axis))
    if (
        lineage.invalidated_source_contract_id not in original_sources
        or lineage.replacement_source_contract_id not in replacement_sources
        or lineage.invalidated_source_contract_id in replacement_sources
    ):
        raise EffectiveAxisProjectionError(
            "source replacement axes lack their exact source lineage"
        )
    invalidation_record = index.get(
        "source-authority-invalidation", lineage.invalidation_id
    )
    try:
        invalidation = SourceAuthorityInvalidation.from_identity_payload(
            None
            if invalidation_record is None
            else invalidation_record.payload.get("invalidation")
        )
        manifest = SourceAuthorityAuditManifest.from_mapping(
            None
            if invalidation_record is None
            else invalidation_record.payload.get("audit_manifest")
        )
        latch = SourceAuthorityLatch.from_mapping(
            None
            if invalidation_record is None
            else invalidation_record.payload.get("latch")
        )
        invalidation.require_manifest(manifest)
        expected_latch = SourceAuthorityLatch.bind(
            invalidation=invalidation,
            manifest=manifest,
        )
    except (TypeError, ValueError) as exc:
        raise EffectiveAxisProjectionError(
            "source replacement invalidation authority is malformed"
        ) from exc
    authority_head = index.event_head(
        f"source-authority:{lineage.invalidated_source_contract_id}"
    )
    if (
        invalidation_record is None
        or invalidation_record.status != "confirmed_and_suspended"
        or invalidation_record.subject
        != f"Source:{lineage.invalidated_source_contract_id}"
        or invalidation_record.record_id != invalidation.identity
        or invalidation_record.fingerprint
        != invalidation.identity.removeprefix(
            "source-authority-invalidation:"
        )
        or invalidation.source_contract_id
        != lineage.invalidated_source_contract_id
        or invalidation.identity != lineage.invalidation_id
        or latch.to_identity_payload() != expected_latch.to_identity_payload()
        or authority_head is None
        or authority_head.record_id != invalidation_record.record_id
        or authority_head.sequence != invalidation_record.event_sequence
    ):
        raise EffectiveAxisProjectionError(
            "source replacement invalidation authority is not current"
        )
    _old_state, old_contract = _source_contract_state(
        index,
        source_id=lineage.invalidated_source_contract_id,
        state_record_id=invalidation.source_state_record_id,
        eligible_required=False,
    )
    replacement_state, replacement_contract = _source_contract_state(
        index,
        source_id=lineage.replacement_source_contract_id,
        state_record_id=lineage.replacement_source_state_record_id,
        eligible_required=True,
    )
    if (
        old_contract.canonical_instrument
        != replacement_contract.canonical_instrument
        or old_contract.source_type is not replacement_contract.source_type
    ):
        raise EffectiveAxisProjectionError(
            "replacement SourceContract changes the source subject"
        )
    replacement_authority_head = index.event_head(
        f"source-authority:{lineage.replacement_source_contract_id}"
    )
    if require_current_replacement_source:
        replacement_head = index.event_head(
            f"source:{lineage.replacement_source_contract_id}"
        )
        if (
            replacement_head is None
            or replacement_head.record_id != replacement_state.record_id
            or replacement_authority_head is not None
        ):
            raise EffectiveAxisProjectionError(
                "replacement SourceContract is not the current eligible head"
            )
    try:
        return SourceReplacementBinding(
            record_id=lineage.identity,
            mission_id=lineage.mission_id,
            original_axis_id=lineage.original_axis_id,
            original_axis_identity=lineage.original_axis_identity,
            invalidation_record_id=lineage.invalidation_id,
            invalidated_source_contract_id=(
                lineage.invalidated_source_contract_id
            ),
            replacement_source_contract_id=(
                lineage.replacement_source_contract_id
            ),
            replacement_source_state_record_id=(
                lineage.replacement_source_state_record_id
            ),
            replacement_axis_id=lineage.replacement_axis_id,
            replacement_axis_identity=lineage.replacement_axis_identity,
        )
    except ValueError as exc:
        raise EffectiveAxisProjectionError(
            "source replacement binding is malformed"
        ) from exc


@dataclass(frozen=True, slots=True)
class _ExecutableAxisLineage:
    executable_id: str
    mission_id: str
    study_id: str
    axis_id: str
    axis_identity: str


def _trial_axis_lineage(
    index: LocalIndex,
    executable_id: str,
) -> _ExecutableAxisLineage:
    executable_id = _identity("lineage Executable id", executable_id, "executable:")
    trial = index.get("trial", executable_id)
    if trial is None:
        raise EffectiveAxisProjectionError(
            "replay or evidence-scope Executable lacks its counted trial"
        )
    payload = trial.payload
    mission_id = _ascii("trial Mission id", payload.get("mission_id"))
    study_id = _ascii("trial Study id", payload.get("study_id"))
    axis_id = _ascii("trial Portfolio axis id", payload.get("portfolio_axis_id"))
    axis_identity = _identity(
        "trial Portfolio axis identity",
        payload.get("portfolio_axis_identity"),
        "axis:",
    )
    study = index.get("study-open", study_id)
    if (
        trial.record_id != executable_id
        or trial.status != "evaluated"
        or trial.fingerprint != executable_id.removeprefix("executable:")
        or study is None
        or study.status not in {"open", "closed"}
        or study.payload.get("mission_id") != mission_id
        or study.payload.get("portfolio_axis_id") != axis_id
        or study.payload.get("portfolio_axis_identity") != axis_identity
        or study.subject != f"Study:{study_id}"
    ):
        raise EffectiveAxisProjectionError(
            "Executable trial-to-Study-to-axis lineage is malformed or ambiguous"
        )
    return _ExecutableAxisLineage(
        executable_id=executable_id,
        mission_id=mission_id,
        study_id=study_id,
        axis_id=axis_id,
        axis_identity=axis_identity,
    )


def _completion_axis_lineage(
    index: LocalIndex,
    completion: IndexRecord,
) -> _ExecutableAxisLineage:
    scientific = completion.payload.get("scientific")
    executable_id = (
        None
        if not isinstance(scientific, Mapping)
        else scientific.get("executable_id")
    )
    lineage = _trial_axis_lineage(
        index,
        _identity("completion Executable id", executable_id, "executable:"),
    )
    job_id = _ascii("completion Job id", completion.payload.get("job_id"))
    declaration = index.get("job-declared", job_id)
    if (
        completion.status not in {"success", "failed", "not_evaluable"}
        or declaration is None
        or declaration.payload.get("mission_id") != lineage.mission_id
        or declaration.payload.get("study_id") != lineage.study_id
    ):
        raise EffectiveAxisProjectionError(
            "completion-to-Job-to-Executable axis lineage is malformed"
        )
    return lineage


def _obligation_axis_lineage(
    index: LocalIndex,
    obligation: HistoricalReplayObligation,
) -> _ExecutableAxisLineage:
    lineage = _trial_axis_lineage(index, obligation.original_executable_id)
    completion = index.get(
        "job-completed", obligation.original_completion_record_id
    )
    close_record = index.get(
        "study-close", obligation.original_study_close_record_id
    )
    completion_lineage = (
        None
        if completion is None
        else _completion_axis_lineage(index, completion)
    )
    if (
        lineage.study_id != obligation.original_study_id
        or completion_lineage != lineage
        or close_record is None
        or close_record.subject != f"Study:{obligation.original_study_id}"
    ):
        raise EffectiveAxisProjectionError(
            "replay obligation is not bound to its exact original Executable axis"
        )
    return lineage


def _all_obligation_heads(
    index: LocalIndex,
) -> tuple[tuple[HistoricalReplayObligation, IndexRecord], ...]:
    mission_ids: set[str] = set()
    initials = tuple(index.records_by_kind("historical-replay-obligation"))
    for initial in initials:
        try:
            obligation = historical_replay_obligation_from_identity_payload(
                initial.payload.get("obligation", {})
            )
        except (TypeError, ValueError) as exc:
            raise EffectiveAxisProjectionError(
                "historical replay obligation projection is malformed"
            ) from exc
        mission_ids.add(obligation.governing_mission_id)
    resolved: list[tuple[HistoricalReplayObligation, IndexRecord]] = []
    try:
        for mission_id in sorted(mission_ids):
            resolved.extend(obligation_heads(index, mission_id=mission_id))
    except ReplayProjectionError as exc:
        raise EffectiveAxisProjectionError(str(exc)) from exc
    if len(resolved) != len(initials) or len(
        {obligation.identity for obligation, _head in resolved}
    ) != len(resolved):
        raise EffectiveAxisProjectionError(
            "historical replay obligation Mission projection is ambiguous"
        )
    return tuple(sorted(resolved, key=lambda item: item[0].identity))


def _execution_binding(value: object) -> ReplayExecutionBinding:
    if not isinstance(value, Mapping):
        raise EffectiveAxisProjectionError("replay execution binding is malformed")
    try:
        binding = ReplayExecutionBinding(
            obligation_ids=tuple(value["obligation_ids"]),
            portfolio_decision_id=value["portfolio_decision_id"],
            replay_study_id=value["replay_study_id"],
            replay_executable_id=value["replay_executable_id"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectiveAxisProjectionError(
            "replay execution binding is malformed"
        ) from exc
    if binding.to_identity_payload() != dict(value):
        raise EffectiveAxisProjectionError("replay execution binding changed on rebuild")
    return binding


def _satisfaction(value: object) -> ReplaySatisfaction:
    if not isinstance(value, Mapping):
        raise EffectiveAxisProjectionError("replay satisfaction is malformed")
    try:
        satisfaction = ReplaySatisfaction(
            obligation_id=value["obligation_id"],
            resolution_scope=ReplayResolutionScope(value["resolution_scope"]),
            portfolio_decision_id=value["portfolio_decision_id"],
            replay_study_id=value["replay_study_id"],
            replay_executable_id=value["replay_executable_id"],
            replay_study_close_record_id=value["replay_study_close_record_id"],
            study_diagnosis_id=value["study_diagnosis_id"],
            satisfied_criterion_ids=tuple(value["satisfied_criterion_ids"]),
            evidence_record_ids=tuple(value["evidence_record_ids"]),
            remaining_scientific_condition=value.get(
                "remaining_scientific_condition"
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectiveAxisProjectionError("replay satisfaction is malformed") from exc
    if satisfaction.to_identity_payload() != dict(value):
        raise EffectiveAxisProjectionError("replay satisfaction changed on rebuild")
    return satisfaction


def _deferral(value: object) -> ReplayDeferral:
    try:
        return replay_deferral_from_identity_payload(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise EffectiveAxisProjectionError("replay deferral is malformed") from exc


@dataclass(frozen=True, slots=True)
class _OverlayAuthority:
    overlay: HistoricalEvidenceScopeOverlay
    record: IndexRecord
    completion_binding: EvidenceScopeAxisBinding


def _overlay_authorities(
    index: LocalIndex,
    *,
    known_obligation_ids: set[str],
) -> tuple[_OverlayAuthority, ...]:
    resolved: list[_OverlayAuthority] = []
    seen_completions: set[str] = set()
    for record in index.records_by_kind("historical-evidence-scope-overlay"):
        try:
            overlay = historical_evidence_scope_from_payload(record.payload)
        except EvidenceScopeError as exc:
            raise EffectiveAxisProjectionError(
                "historical evidence-scope overlay is malformed"
            ) from exc
        completion = index.get("job-completed", overlay.completion_record_id)
        if completion is None:
            raise EffectiveAxisProjectionError(
                "historical evidence-scope overlay lost its completion"
            )
        try:
            effective_scope = effective_completion_evidence_scope(index, completion)
        except EvidenceScopeProjectionError as exc:
            raise EffectiveAxisProjectionError(str(exc)) from exc
        if (
            overlay.completion_record_id in seen_completions
            or record.record_id != overlay.identity
            or effective_scope.overlay_record_id != overlay.identity
            or effective_scope.scientific_credit != 0
            or effective_scope.economic_credit != 0
            or effective_scope.terminal_credit != 0
            or set(overlay.replay_obligation_ids).difference(
                known_obligation_ids
            )
        ):
            raise EffectiveAxisProjectionError(
                "historical evidence-scope overlay binding is incomplete or ambiguous"
            )
        lineage = _completion_axis_lineage(index, completion)
        try:
            completion_binding = EvidenceScopeAxisBinding(
                axis_id=lineage.axis_id,
                axis_identity=lineage.axis_identity,
                completion_record_id=overlay.completion_record_id,
                executable_id=lineage.executable_id,
                governing_mission_id=overlay.governing_mission_id,
                overlay_record_id=overlay.identity,
                replay_obligation_ids=overlay.replay_obligation_ids,
            )
        except ValueError as exc:
            raise EffectiveAxisProjectionError(
                "historical evidence-scope axis binding is malformed"
            ) from exc
        seen_completions.add(overlay.completion_record_id)
        resolved.append(
            _OverlayAuthority(
                overlay=overlay,
                record=record,
                completion_binding=completion_binding,
            )
        )
    return tuple(sorted(resolved, key=lambda item: item.overlay.identity))


def _replay_axis_binding(
    *,
    index: LocalIndex,
    obligation: HistoricalReplayObligation,
    head: IndexRecord,
    lineage: _ExecutableAxisLineage,
    overlays: tuple[_OverlayAuthority, ...],
) -> ReplayAxisBinding:
    try:
        status = ReplayObligationStatus(head.status)
    except ValueError as exc:
        raise EffectiveAxisProjectionError(
            "historical replay obligation status is malformed"
        ) from exc
    if (
        head.subject != f"Mission:{obligation.governing_mission_id}"
        or head.payload.get("obligation_id")
        not in {None, obligation.identity}
    ):
        raise EffectiveAxisProjectionError(
            "historical replay obligation state binding is malformed"
        )
    resolution_scope: ReplayResolutionScope | None = None
    overlay_id: str | None = None
    if status is ReplayObligationStatus.PENDING:
        if (
            head.kind != "historical-replay-obligation"
            or head.record_id != obligation.identity
            or head.payload != {"obligation": obligation.to_identity_payload()}
        ):
            raise EffectiveAxisProjectionError(
                "pending replay obligation head is malformed"
            )
    elif status is ReplayObligationStatus.IN_PROGRESS:
        binding = _execution_binding(head.payload.get("binding"))
        expected_payload = {
            "binding": binding.to_identity_payload(),
            "obligation_id": obligation.identity,
            "prior_status": ReplayObligationStatus.PENDING.value,
        }
        expected_id = "historical-replay-progress:" + canonical_digest(
            domain="historical-replay-obligation-progress",
            payload=expected_payload,
        )
        if (
            head.kind != "historical-replay-obligation-progress"
            or binding.obligation_ids != (obligation.identity,)
            or head.payload != expected_payload
            or head.record_id != expected_id
            or head.fingerprint != binding.identity
        ):
            raise EffectiveAxisProjectionError(
                "in-progress replay obligation head is malformed"
            )
    elif status is ReplayObligationStatus.DEFERRED:
        deferral = _deferral(head.payload.get("resolution"))
        deferral_bases = tuple(
            record
            for kind in (
                "architecture-review",
                "external-blocker",
                "source-authority-invalidation",
                "study-diagnosis",
            )
            if (record := index.get(kind, deferral.basis_record_id)) is not None
        )
        if (
            head.kind != "historical-replay-obligation-resolution"
            or deferral.obligation_id != obligation.identity
            or len(deferral_bases) != 1
            or head.record_id != deferral.identity
            or head.payload
            != {
                "obligation_id": obligation.identity,
                "prior_status": head.payload.get("prior_status"),
                "resolution": deferral.to_identity_payload(),
            }
            or head.payload.get("prior_status")
            not in {
                ReplayObligationStatus.PENDING.value,
                ReplayObligationStatus.IN_PROGRESS.value,
            }
        ):
            raise EffectiveAxisProjectionError(
                "deferred replay obligation head is malformed"
            )
    else:
        satisfaction = _satisfaction(head.payload.get("resolution"))
        if (
            head.kind != "historical-replay-obligation-resolution"
            or satisfaction.obligation_id != obligation.identity
            or head.record_id != satisfaction.identity
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
        ):
            raise EffectiveAxisProjectionError(
                "satisfied replay obligation head is malformed"
            )
        resolution_scope = satisfaction.resolution_scope
        try:
            require_satisfaction(
                index,
                obligation=obligation,
                satisfaction=satisfaction,
                allow_legacy_decision_binding=(
                    resolution_scope is ReplayResolutionScope.AUDIT_ONLY
                ),
            )
        except ReplayAuthorityError as exc:
            raise EffectiveAxisProjectionError(
                "satisfied replay lacks exact scientific or audit authority"
            ) from exc
        matching_overlays = tuple(
            authority
            for authority in overlays
            if obligation.identity in authority.overlay.replay_obligation_ids
            and satisfaction.identity in authority.overlay.replay_resolution_ids
        )
        if resolution_scope is ReplayResolutionScope.AUDIT_ONLY:
            if len(matching_overlays) != 1:
                raise EffectiveAxisProjectionError(
                    "audit-only replay lacks one exact evidence-scope overlay"
                )
            overlay_id = matching_overlays[0].overlay.identity
        elif matching_overlays:
            raise EffectiveAxisProjectionError(
                "scientific replay is incorrectly bound to an audit-only overlay"
            )
    try:
        return ReplayAxisBinding(
            axis_id=lineage.axis_id,
            axis_identity=lineage.axis_identity,
            governing_mission_id=obligation.governing_mission_id,
            obligation_id=obligation.identity,
            original_executable_id=obligation.original_executable_id,
            original_study_id=obligation.original_study_id,
            state_record_id=head.record_id,
            status=status,
            resolution_scope=resolution_scope,
            evidence_scope_overlay_id=overlay_id,
        )
    except ValueError as exc:
        raise EffectiveAxisProjectionError(
            "historical replay axis binding is malformed"
        ) from exc


@dataclass(frozen=True, slots=True)
class _EffectiveAuthorityIndex:
    replay_by_axis: Mapping[str, tuple[ReplayAxisBinding, ...]]
    scope_by_axis: Mapping[str, tuple[EvidenceScopeAxisBinding, ...]]
    source_replacements_by_axis: Mapping[
        str, tuple[SourceReplacementBinding, ...]
    ]
    replay_bindings: tuple[ReplayAxisBinding, ...]
    scope_bindings: tuple[EvidenceScopeAxisBinding, ...]
    source_replacement_bindings: tuple[SourceReplacementBinding, ...]


def _source_replacement_bindings(
    index: LocalIndex,
) -> tuple[SourceReplacementBinding, ...]:
    resolved: list[SourceReplacementBinding] = []
    seen_streams: set[str] = set()
    for record in index.records_by_kind("source-replacement-lineage"):
        try:
            lineage = SourceReplacementLineage.from_mapping(
                record.payload.get("lineage")
            )
            binding = validate_source_replacement_lineage(
                index,
                lineage,
                require_current_replacement_source=False,
            )
        except (TypeError, ValueError) as exc:
            raise EffectiveAxisProjectionError(
                "source replacement lineage projection is malformed"
            ) from exc
        expected_stream = (
            f"source-replacement:{lineage.mission_id}:"
            f"{lineage.original_axis_identity}:"
            f"{lineage.invalidated_source_contract_id}"
        )
        head = index.event_head(expected_stream)
        expected_payload = {
            "candidate_delta": 0,
            "claim_delta": "none",
            "holdout_delta": 0,
            "lineage": lineage.to_identity_payload(),
            "scientific_credit": 0,
            "terminal_scientific_credit": 0,
            "trial_delta": 0,
        }
        if (
            expected_stream in seen_streams
            or record.record_id != lineage.identity
            or binding.record_id != lineage.identity
            or record.subject != f"Axis:{lineage.original_axis_identity}"
            or record.status != "retired_original_axis"
            or record.fingerprint
            != lineage.identity.removeprefix("source-replacement-lineage:")
            or record.payload != expected_payload
            or record.event_stream != expected_stream
            or record.event_sequence != 1
            or head is None
            or head.sequence != 1
            or head.record_id != record.record_id
            or head.record_kind != record.kind
        ):
            raise EffectiveAxisProjectionError(
                "source replacement lineage record is not canonical"
            )
        seen_streams.add(expected_stream)
        resolved.append(binding)
    return tuple(
        sorted(
            resolved,
            key=lambda item: (
                item.original_axis_identity,
                item.invalidated_source_contract_id,
            ),
        )
    )


def _effective_authority_index(index: LocalIndex) -> _EffectiveAuthorityIndex:
    record_count = index.record_count()
    cached = getattr(index, "_axiom_effective_axis_authority_cache", None)
    if (
        isinstance(cached, tuple)
        and len(cached) == 2
        and cached[0] == record_count
        and isinstance(cached[1], _EffectiveAuthorityIndex)
    ):
        return cached[1]
    heads = _all_obligation_heads(index)
    obligation_ids = {obligation.identity for obligation, _head in heads}
    overlays = _overlay_authorities(
        index,
        known_obligation_ids=obligation_ids,
    )
    replay_bindings = tuple(
        _replay_axis_binding(
            index=index,
            obligation=obligation,
            head=head,
            lineage=_obligation_axis_lineage(index, obligation),
            overlays=overlays,
        )
        for obligation, head in heads
    )
    replay_by_id = {binding.obligation_id: binding for binding in replay_bindings}
    for authority in overlays:
        if any(
            obligation_id not in replay_by_id
            or replay_by_id[obligation_id].status
            is not ReplayObligationStatus.SATISFIED
            or replay_by_id[obligation_id].resolution_scope
            is not ReplayResolutionScope.AUDIT_ONLY
            or replay_by_id[obligation_id].evidence_scope_overlay_id
            != authority.overlay.identity
            for obligation_id in authority.overlay.replay_obligation_ids
        ):
            raise EffectiveAxisProjectionError(
                "audit-only evidence-scope overlay lacks current replay authority"
            )
    scope_bindings = tuple(
        authority.completion_binding for authority in overlays
    )
    source_replacement_bindings = _source_replacement_bindings(index)
    replay_by_axis: dict[str, list[ReplayAxisBinding]] = {}
    for binding in replay_bindings:
        replay_by_axis.setdefault(binding.axis_identity, []).append(binding)
    scope_by_axis: dict[str, list[EvidenceScopeAxisBinding]] = {}
    for binding in scope_bindings:
        scope_by_axis.setdefault(binding.axis_identity, []).append(binding)
    source_replacements_by_axis: dict[str, list[SourceReplacementBinding]] = {}
    for binding in source_replacement_bindings:
        source_replacements_by_axis.setdefault(
            binding.original_axis_identity, []
        ).append(binding)
    authority_index = _EffectiveAuthorityIndex(
        replay_by_axis={
            axis_identity: tuple(
                sorted(values, key=lambda item: item.obligation_id)
            )
            for axis_identity, values in replay_by_axis.items()
        },
        scope_by_axis={
            axis_identity: tuple(
                sorted(values, key=lambda item: item.overlay_record_id)
            )
            for axis_identity, values in scope_by_axis.items()
        },
        source_replacements_by_axis={
            axis_identity: tuple(
                sorted(
                    values,
                    key=lambda item: item.invalidated_source_contract_id,
                )
            )
            for axis_identity, values in source_replacements_by_axis.items()
        },
        replay_bindings=replay_bindings,
        scope_bindings=scope_bindings,
        source_replacement_bindings=source_replacement_bindings,
    )
    setattr(
        index,
        "_axiom_effective_axis_authority_cache",
        (record_count, authority_index),
    )
    return authority_index


def effective_replay_axis_bindings(
    index: LocalIndex,
    *,
    mission_id: str | None = None,
) -> tuple[ReplayAxisBinding, ...]:
    """Return immutable replay-to-original-axis bindings, optionally by Mission."""

    if mission_id is not None:
        _ascii("replay governing Mission id", mission_id)
    bindings = _effective_authority_index(index).replay_bindings
    return tuple(
        binding
        for binding in bindings
        if mission_id is None or binding.governing_mission_id == mission_id
    )


def mission_effective_axis_blockers(
    index: LocalIndex,
    *,
    mission_id: str,
) -> tuple[ReplayAxisBinding, ...]:
    """Return unresolved replay facts that currently forbid a Mission terminal.

    A satisfied audit-only replay completes its exact audit obligation, while
    its evidence-scope overlay removes credit only from the bound completion.
    It therefore does not block or exclude the causal axis.  A historical
    pruned axis with that remainder is projected as requiring explicit reopen.
    """

    _ascii("terminal Mission id", mission_id)
    authority = _effective_authority_index(index)
    replay = tuple(
        binding
        for binding in authority.replay_bindings
        if binding.governing_mission_id == mission_id and binding.blocks_terminal
    )
    return replay


def effective_axis_resolution(
    index: LocalIndex,
    axis: Mapping[str, Any],
    *,
    prospective_source_ids: Sequence[str] = (),
) -> EffectiveAxisResolution:
    axis_identity = _identity(
        "Portfolio axis identity", axis.get("axis_identity"), "axis:"
    )
    sources = tuple(
        sorted(set(axis_source_contract_ids(index, axis)).union(prospective_source_ids))
    )
    invalidations = []
    for source_id in sources:
        _identity("axis source contract", source_id, "source:")
        head = index.event_head(f"source-authority:{source_id}")
        if head is None:
            continue
        record = index.get(head.record_kind, head.record_id)
        try:
            invalidation = SourceAuthorityInvalidation.from_identity_payload(
                record.payload.get("invalidation") if record is not None else None
            )
            manifest = SourceAuthorityAuditManifest.from_mapping(
                record.payload.get("audit_manifest") if record is not None else None
            )
            latch = SourceAuthorityLatch.from_mapping(
                record.payload.get("latch") if record is not None else None
            )
            invalidation.require_manifest(manifest)
            expected_latch = SourceAuthorityLatch.bind(
                invalidation=invalidation,
                manifest=manifest,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise EffectiveAxisProjectionError(
                "axis source-authority invalidation payload is malformed"
            ) from exc
        if (
            head.sequence != 1
            or record is None
            or record.kind != "source-authority-invalidation"
            or record.status != "confirmed_and_suspended"
            or record.subject != f"Source:{source_id}"
            or record.event_stream != f"source-authority:{source_id}"
            or record.event_sequence != head.sequence
            or record.record_id != invalidation.identity
            or record.fingerprint
            != invalidation.identity.removeprefix(
                "source-authority-invalidation:"
            )
            or invalidation.source_contract_id != source_id
            or record.payload.get("eligible_source_state_record_id")
            != invalidation.source_state_record_id
            or latch.to_identity_payload() != expected_latch.to_identity_payload()
            or record.payload.get("scientific_trial_delta") != 0
        ):
            raise EffectiveAxisProjectionError(
                "axis source-authority invalidation projection is malformed"
            )
        try:
            invalidations.append(
                SourceInvalidationBinding(
                    source_contract_id=source_id,
                    invalidation_record_id=record.record_id,
                )
            )
        except ValueError as exc:
            raise EffectiveAxisProjectionError(
                "axis source-authority identity is malformed"
            ) from exc
    authority = _effective_authority_index(index)
    try:
        return resolve_effective_axis(
            axis_id=axis["axis_id"],
            axis_identity=axis_identity,
            snapshot_status=axis["status"],
            source_contract_ids=sources,
            invalidations=tuple(invalidations),
            source_replacements=authority.source_replacements_by_axis.get(
                axis_identity, ()
            ),
            replay_bindings=authority.replay_by_axis.get(axis_identity, ()),
            evidence_scope_bindings=authority.scope_by_axis.get(
                axis_identity, ()
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectiveAxisProjectionError(
            "effective Portfolio axis cannot be resolved"
        ) from exc


def selectable_axis_ids(
    index: LocalIndex,
    axes: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Resolve a scheduler set without allowing one blocked axis to hide peers."""

    resolutions = tuple(effective_axis_resolution(index, axis) for axis in axes)
    axis_ids = tuple(item.axis_id for item in resolutions)
    if len(axis_ids) != len(set(axis_ids)):
        raise EffectiveAxisProjectionError("Portfolio scheduler axis ids are ambiguous")
    return tuple(sorted(item.axis_id for item in resolutions if item.selectable))


__all__ = [
    "EffectiveAxisProjectionError",
    "axis_source_contract_ids",
    "effective_axis_resolution",
    "effective_replay_axis_bindings",
    "mission_effective_axis_blockers",
    "selectable_axis_ids",
    "validate_source_replacement_lineage",
]
