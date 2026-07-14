"""Git-object orchestration boundary for historical KPI backfill proofs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from axiom_rift.operations.study_close_backfill import (
    HistoricalBackfillProofError,
    build_historical_backfill_proof,
    historical_backfill_event,
    historical_backfill_sources,
    validate_parent_source_set,
    validate_proof_objects,
)
from axiom_rift.operations.study_close_checkpoint import (
    CheckpointPathBlob,
    HistoricalKpiBackfillProof,
)


@dataclass(frozen=True, slots=True)
class BackfillCommitMetadata:
    parent: str
    tree: str
    message: str


@dataclass(frozen=True, slots=True)
class BackfillCommitSnapshot:
    events: tuple[Mapping[str, Any], ...]
    parent_events: tuple[Mapping[str, Any], ...]
    required_path_blobs: tuple[CheckpointPathBlob, ...]
    changed_paths: frozenset[str]


def build_git_authenticated_backfill_proof(
    *,
    events: Sequence[Mapping[str, Any]],
    ancestry_anchor: str,
    trailer_commits: Mapping[tuple[str, int], Sequence[str]],
    commit_is_ancestor: bool,
    metadata: BackfillCommitMetadata,
    snapshot: BackfillCommitSnapshot,
) -> HistoricalKpiBackfillProof | None:
    event = historical_backfill_event(events)
    if event is None:
        return None
    sources = historical_backfill_sources(events, event)
    matches = tuple(trailer_commits.get((event["event_id"], event["sequence"]), ()))
    if len(matches) != 1:
        raise HistoricalBackfillProofError(
            "historical KPI backfill lacks one authenticated commit"
        )
    if not commit_is_ancestor:
        raise HistoricalBackfillProofError(
            "historical KPI backfill commit is not in the checkpoint ancestry"
        )
    commit_event = historical_backfill_event(snapshot.events)
    if (
        commit_event is None
        or snapshot.events[-1].get("event_id") != event["event_id"]
        or snapshot.events[-1].get("sequence") != event["sequence"]
        or commit_event.get("event_id") != event["event_id"]
        or historical_backfill_sources(snapshot.events, commit_event) != sources
    ):
        raise HistoricalBackfillProofError(
            "historical KPI backfill commit event or source set differs"
        )
    validate_parent_source_set(snapshot.parent_events, sources)
    required = {binding.path for binding in snapshot.required_path_blobs}
    if not required.issubset(snapshot.changed_paths):
        raise HistoricalBackfillProofError(
            "historical KPI backfill commit split required projection paths"
        )
    return build_historical_backfill_proof(
        event=event,
        sources=sources,
        commit=matches[0],
        commit_parent=metadata.parent,
        commit_tree=metadata.tree,
        ancestry_anchor=ancestry_anchor,
        message=metadata.message,
        path_blobs=snapshot.required_path_blobs,
    )


def authenticate_git_backfill_proof(
    proof: HistoricalKpiBackfillProof,
    *,
    metadata: BackfillCommitMetadata,
    observed_path_blobs: Mapping[str, str],
    commit_in_anchor: bool,
    anchor_in_checkpoint_parent: bool,
) -> None:
    validate_proof_objects(
        proof,
        observed_parent=metadata.parent,
        observed_tree=metadata.tree,
        message=metadata.message,
        observed_path_blobs=observed_path_blobs,
        commit_in_anchor=commit_in_anchor,
        anchor_in_checkpoint_parent=anchor_in_checkpoint_parent,
    )


__all__ = [
    "BackfillCommitMetadata",
    "BackfillCommitSnapshot",
    "authenticate_git_backfill_proof",
    "build_git_authenticated_backfill_proof",
]
