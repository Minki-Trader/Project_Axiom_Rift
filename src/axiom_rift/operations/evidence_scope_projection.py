"""Read-only projection of additive historical evidence-scope corrections."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from axiom_rift.operations.completion_evidence_scope import (
    CompletionEvidenceScopeError,
    EffectiveCompletionEvidenceScope,
    raw_completion_evidence_scope,
)
from axiom_rift.operations.completion_validity_projection import (
    CompletionValidityProjectionError,
    current_completion_validity_invalidation,
)
from axiom_rift.operations.historical_cost_semantics_reader import (
    HistoricalCompletionCostAuthority,
    HistoricalCostSemanticsProjectionError,
    effective_historical_completion_cost_authority,
)
from axiom_rift.research.effective_evidence_scope import (
    EvidenceScopeError,
    HistoricalEvidenceScopeOverlay,
    historical_evidence_scope_from_payload,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class EvidenceScopeProjectionError(RuntimeError):
    """The effective completion scope projection is malformed."""


def evidence_scope_stream(completion_record_id: str) -> str:
    return f"historical-evidence-scope:{completion_record_id}"


def evidence_scope_overlay_record(
    overlay: HistoricalEvidenceScopeOverlay,
) -> IndexRecord:
    return IndexRecord(
        kind="historical-evidence-scope-overlay",
        record_id=overlay.identity,
        subject=f"JobCompletion:{overlay.completion_record_id}",
        status="audit_only",
        fingerprint=overlay.identity.removeprefix("historical-evidence-scope:"),
        payload=overlay.to_identity_payload(),
        event_stream=evidence_scope_stream(overlay.completion_record_id),
        event_sequence=1,
    )


def _raw_scope(completion: IndexRecord) -> EffectiveCompletionEvidenceScope:
    try:
        return raw_completion_evidence_scope(completion)
    except CompletionEvidenceScopeError as exc:
        raise EvidenceScopeProjectionError(str(exc)) from exc


def _apply_cost_authority(
    raw: EffectiveCompletionEvidenceScope,
    authority: HistoricalCompletionCostAuthority | None,
) -> EffectiveCompletionEvidenceScope:
    if authority is None or not authority.scientific:
        return raw
    modes = tuple(
        mode for mode in raw.evidence_modes if mode != "cost_and_execution"
    )
    if "cost_and_execution" in raw.evidence_modes:
        modes = tuple(sorted((*modes, "completed_period_proxy_cost")))
    return replace(
        raw,
        evidence_modes=modes,
        candidate_eligible=False,
        economic_credit=0,
        candidate_credit=0,
        terminal_credit=(
            0 if authority.requires_axis_reopen else raw.terminal_credit
        ),
        negative_memory_authoritative=False,
        negative_memory_role="diagnostic_only",
        cost_semantics_latch_id=authority.latch_record_id,
        cost_semantics_proxy_only=True,
        preserved_independent_scopes=authority.preserved_independent_scopes,
    )


def effective_completion_evidence_scope(
    index: LocalIndex | LocalIndexView,
    completion: IndexRecord,
) -> EffectiveCompletionEvidenceScope:
    """Resolve raw completion facts through the current additive overlay."""

    raw = _raw_scope(completion)
    try:
        cost_authority = effective_historical_completion_cost_authority(
            index,
            completion,
        )
    except HistoricalCostSemanticsProjectionError as exc:
        raise EvidenceScopeProjectionError(str(exc)) from exc
    raw = _apply_cost_authority(raw, cost_authority)
    try:
        validity = current_completion_validity_invalidation(
            index,
            completion.record_id,
        )
    except CompletionValidityProjectionError as exc:
        raise EvidenceScopeProjectionError(str(exc)) from exc
    stream = evidence_scope_stream(completion.record_id)
    head = index.event_head(stream)
    if head is None:
        if validity is None:
            return raw
        return EffectiveCompletionEvidenceScope(
            completion_record_id=completion.record_id,
            evidence_modes=("audit_integrity",),
            scientific_eligible=False,
            candidate_eligible=False,
            scientific_credit=0,
            economic_credit=0,
            candidate_credit=0,
            terminal_credit=0,
            negative_memory_authoritative=False,
            negative_memory_role="diagnostic_only",
            invalidation_record_id=validity.invalidation_record_id,
        )
    record = index.get(head.record_kind, head.record_id)
    try:
        overlay = historical_evidence_scope_from_payload(
            {} if record is None else record.payload
        )
    except EvidenceScopeError as exc:
        raise EvidenceScopeProjectionError(
            "historical evidence scope overlay is malformed"
        ) from exc
    if (
        head.sequence != 1
        or record is None
        or record.kind != "historical-evidence-scope-overlay"
        or record.status != "audit_only"
        or record.record_id != overlay.identity
        or record.subject != f"JobCompletion:{completion.record_id}"
        or record.event_stream != stream
        or record.event_sequence != head.sequence
        or overlay.completion_record_id != completion.record_id
    ):
        raise EvidenceScopeProjectionError(
            "historical evidence scope overlay head is invalid"
        )
    declaration = index.get(
        "job-declared", completion.payload.get("job_id", "")
    )
    replay_study = index.get("study-open", overlay.replay_study_id)
    if (
        declaration is None
        or declaration.payload.get("mission_id") != overlay.governing_mission_id
        or replay_study is None
        or replay_study.payload.get("mission_id") != overlay.governing_mission_id
    ):
        raise EvidenceScopeProjectionError(
            "historical evidence scope Mission binding is invalid"
        )
    resolutions: list[Mapping[str, Any]] = []
    for resolution_id in overlay.replay_resolution_ids:
        resolution = index.get(
            "historical-replay-obligation-resolution", resolution_id
        )
        value = None if resolution is None else resolution.payload.get("resolution")
        if (
            resolution is None
            or resolution.status != "satisfied"
            or resolution.subject != f"Mission:{overlay.governing_mission_id}"
            or not isinstance(value, Mapping)
            or resolution.payload.get("obligation_id")
            != value.get("obligation_id")
            or value.get("resolution_scope") != "audit_only"
            or value.get("replay_study_id") != overlay.replay_study_id
            or completion.record_id not in value.get("evidence_record_ids", [])
        ):
            raise EvidenceScopeProjectionError(
                "historical evidence scope lacks its audit-only resolution"
            )
        resolutions.append(value)
    resolution_obligations = tuple(
        value.get("obligation_id") for value in resolutions
    )
    if any(type(item) is not str for item in resolution_obligations) or tuple(
        sorted(resolution_obligations)
    ) != overlay.replay_obligation_ids:
        raise EvidenceScopeProjectionError(
            "historical evidence scope obligation closure is invalid"
        )
    return EffectiveCompletionEvidenceScope(
        completion_record_id=completion.record_id,
        evidence_modes=("audit_integrity",),
        scientific_eligible=False,
        candidate_eligible=False,
        scientific_credit=0,
        economic_credit=0,
        candidate_credit=0,
        terminal_credit=0,
        negative_memory_authoritative=False,
        negative_memory_role="diagnostic_only",
        overlay_record_id=overlay.identity,
        invalidation_record_id=(
            None if validity is None else validity.invalidation_record_id
        ),
    )


__all__ = [
    "EffectiveCompletionEvidenceScope",
    "EvidenceScopeProjectionError",
    "effective_completion_evidence_scope",
    "evidence_scope_overlay_record",
    "evidence_scope_stream",
]
