"""Lightweight evidence scope for same-Study cache handoff."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class CompletionEvidenceScopeError(RuntimeError):
    """A completion scope is malformed or no longer current."""


@dataclass(frozen=True, slots=True)
class EffectiveCompletionEvidenceScope:
    completion_record_id: str
    evidence_modes: tuple[str, ...]
    scientific_eligible: bool
    candidate_eligible: bool
    scientific_credit: int
    economic_credit: int
    candidate_credit: int
    terminal_credit: int
    negative_memory_authoritative: bool
    negative_memory_role: str
    overlay_record_id: str | None = None
    invalidation_record_id: str | None = None
    cost_semantics_latch_id: str | None = None
    cost_semantics_proxy_only: bool = False
    preserved_independent_scopes: tuple[str, ...] = ()


def raw_completion_evidence_scope(
    completion: IndexRecord,
) -> EffectiveCompletionEvidenceScope:
    """Project only validator-created facts from one completion record."""

    scientific = completion.payload.get("scientific")
    modes = (
        None
        if not isinstance(scientific, Mapping)
        else scientific.get("executed_evidence_modes")
    )
    if (
        not isinstance(scientific, Mapping)
        or not isinstance(modes, list)
        or not modes
        or modes != sorted(set(modes))
        or any(type(item) is not str or not item.isascii() for item in modes)
        or type(scientific.get("scientific_eligible")) is not bool
        or type(scientific.get("candidate_eligible")) is not bool
    ):
        raise CompletionEvidenceScopeError(
            "scientific completion evidence scope is malformed"
        )
    eligible = scientific["scientific_eligible"]
    return EffectiveCompletionEvidenceScope(
        completion_record_id=completion.record_id,
        evidence_modes=tuple(modes),
        scientific_eligible=eligible,
        candidate_eligible=scientific["candidate_eligible"],
        scientific_credit=int(eligible),
        economic_credit=int(eligible and "cost_and_execution" in modes),
        candidate_credit=int(eligible and scientific["candidate_eligible"]),
        terminal_credit=int(eligible),
        negative_memory_authoritative=eligible,
        negative_memory_role=(
            "scientific" if eligible else "diagnostic_only"
        ),
    )


def current_study_cache_evidence_scope(
    index: LocalIndex | LocalIndexView,
    completion: IndexRecord,
) -> EffectiveCompletionEvidenceScope:
    """Require an uncorrected same-Study producer for cache reuse.

    This is intentionally narrower than the historical scheduler projection.
    A cache consumer runs while the producer Study is still active, so any
    historical cost projection, audit-only scope overlay, or later validity
    correction is a contradiction rather than another policy layer to load.
    """

    scope = raw_completion_evidence_scope(completion)
    completion_id = completion.record_id
    if (
        index.get("historical-cost-semantics-completion", completion_id)
        is not None
        or index.event_head(
            f"historical-evidence-scope:{completion_id}"
        )
        is not None
        or index.event_head(
            f"completion-scientific-validity:{completion_id}"
        )
        is not None
    ):
        raise CompletionEvidenceScopeError(
            "same-Study cache producer has a historical evidence correction"
        )
    return scope


__all__ = [
    "CompletionEvidenceScopeError",
    "EffectiveCompletionEvidenceScope",
    "current_study_cache_evidence_scope",
    "raw_completion_evidence_scope",
]
