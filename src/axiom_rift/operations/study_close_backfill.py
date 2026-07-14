"""Pure checkpoint-v2 proof rules for the historical Study KPI backfill."""

from __future__ import annotations

from hashlib import sha256
import re
from typing import Any, Mapping, Sequence

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.study_close_checkpoint import (
    CheckpointPathBlob,
    HistoricalKpiBackfillProof,
    HistoricalKpiSource,
    StudyCloseCheckpointError,
)


BACKFILL_TRAILER = "Axiom-Study-KPI-Backfill"
_DIGEST = r"[0-9a-f]{64}"


class HistoricalBackfillProofError(ValueError):
    """The historical backfill event or Git proof is inconsistent."""


def historical_backfill_event(
    events: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    matches = [event for event in events if event.get("event_kind") == "study_kpi_backfilled"]
    if len(matches) > 1:
        raise HistoricalBackfillProofError(
            "historical KPI backfill event is not unique"
        )
    return None if not matches else matches[0]


def historical_backfill_sources(
    events: Sequence[Mapping[str, Any]],
    event: Mapping[str, Any],
) -> tuple[HistoricalKpiSource, ...]:
    by_event_id = {item.get("event_id"): item for item in events}
    sources: list[HistoricalKpiSource] = []
    for record in event.get("index_records", []):
        payload = record.get("payload", {})
        if (
            record.get("kind") != "study-kpi"
            or payload.get("provenance") != "historical_backfill"
        ):
            continue
        event_id = payload.get("historical_study_close_event_id")
        record_id = payload.get("historical_study_close_record_id")
        revision = payload.get("historical_study_close_revision")
        source_event = by_event_id.get(event_id)
        if (
            not isinstance(source_event, Mapping)
            or source_event.get("sequence") != revision
            or source_event.get("event_kind") != "study_closed"
        ):
            raise HistoricalBackfillProofError(
                "historical KPI source event identity differs"
            )
        source_records = [
            source_record
            for source_record in source_event.get("index_records", [])
            if source_record.get("kind") == "study-close"
            and source_record.get("record_id") == record_id
        ]
        if len(source_records) != 1:
            raise HistoricalBackfillProofError(
                "historical KPI source Study-close record differs"
            )
        if record.get("event_sequence") != payload.get("sequence"):
            raise HistoricalBackfillProofError(
                "historical KPI record stream sequence differs"
            )
        try:
            source = HistoricalKpiSource.from_mapping(
                {
                    "kpi_record_id": record.get("record_id"),
                    "kpi_record_sha256": sha256(
                        canonical_bytes(record)
                    ).hexdigest(),
                    "kpi_sequence": payload.get("sequence"),
                    "study_close_event_id": event_id,
                    "study_close_record_id": record_id,
                    "study_close_revision": revision,
                    "study_id": payload.get("study_id"),
                }
            )
        except StudyCloseCheckpointError as exc:
            raise HistoricalBackfillProofError(
                "historical KPI source record is invalid"
            ) from exc
        sources.append(source)
    sources.sort(key=lambda item: item.kpi_sequence)
    return tuple(sources)


def validate_parent_source_set(
    parent_events: Sequence[Mapping[str, Any]],
    sources: Sequence[HistoricalKpiSource],
) -> None:
    if historical_backfill_event(parent_events) is not None:
        raise HistoricalBackfillProofError(
            "historical KPI backfill already exists in its parent snapshot"
        )
    parent_by_id = {item.get("event_id"): item for item in parent_events}
    for source in sources:
        source_event = parent_by_id.get(source.study_close_event_id)
        if (
            not isinstance(source_event, Mapping)
            or source_event.get("sequence") != source.study_close_revision
            or not any(
                record.get("kind") == "study-close"
                and record.get("record_id") == source.study_close_record_id
                for record in source_event.get("index_records", [])
            )
        ):
            raise HistoricalBackfillProofError(
                "historical KPI backfill source is absent from parent ancestry"
            )


def validate_backfill_trailers(message: str, event_id: str, revision: int) -> None:
    event_values = re.findall(
        rf"^{re.escape(BACKFILL_TRAILER)}:\s*({_DIGEST})\s*$",
        message,
        re.MULTILINE,
    )
    revision_values = re.findall(
        r"^Axiom-State-Revision:\s*([0-9]+)\s*$", message, re.MULTILINE
    )
    expected_suffix = (
        f"{BACKFILL_TRAILER}: {event_id}\n"
        f"Axiom-State-Revision: {revision}"
    )
    if (
        event_values != [event_id]
        or revision_values != [str(revision)]
        or not message.rstrip().endswith(expected_suffix)
    ):
        raise HistoricalBackfillProofError(
            "historical KPI backfill commit trailers differ"
        )


def backfill_trailer_commits(log_output: str) -> dict[tuple[str, int], list[str]]:
    result: dict[tuple[str, int], list[str]] = {}
    for row in log_output.split("\x1e"):
        parts = row.strip().split("\x1f", 1)
        if len(parts) != 2:
            continue
        event_values = re.findall(
            rf"^{re.escape(BACKFILL_TRAILER)}:\s*({_DIGEST})\s*$",
            parts[1],
            re.MULTILINE,
        )
        revision_values = re.findall(
            r"^Axiom-State-Revision:\s*([0-9]+)\s*$",
            parts[1],
            re.MULTILINE,
        )
        if len(event_values) == 1 and len(revision_values) == 1:
            result.setdefault(
                (event_values[0], int(revision_values[0])), []
            ).append(parts[0].strip())
    return result


def build_historical_backfill_proof(
    *,
    event: Mapping[str, Any],
    sources: Sequence[HistoricalKpiSource],
    commit: str,
    commit_parent: str,
    commit_tree: str,
    ancestry_anchor: str,
    message: str,
    path_blobs: Sequence[CheckpointPathBlob],
) -> HistoricalKpiBackfillProof:
    try:
        event_id = event["event_id"]
        revision = event["sequence"]
        validate_backfill_trailers(message, event_id, revision)
        proof = HistoricalKpiBackfillProof(
            event_id=event_id,
            revision=revision,
            operation_id=event["operation_id"],
            event_sha256=sha256(canonical_bytes(event) + b"\n").hexdigest(),
            sources=tuple(sources),
            source_set_digest=(
                HistoricalKpiBackfillProof.expected_source_set_digest(sources)
            ),
            commit=commit,
            commit_parent=commit_parent,
            commit_tree=commit_tree,
            ancestry_anchor=ancestry_anchor,
            trailer_sha256=(
                HistoricalKpiBackfillProof.expected_trailer_sha256(
                    event_id, revision
                )
            ),
            path_blobs=tuple(path_blobs),
        )
        proof.validate()
    except (KeyError, StudyCloseCheckpointError, TypeError, ValueError) as exc:
        raise HistoricalBackfillProofError(
            "historical KPI backfill proof is invalid"
        ) from exc
    return proof


def validate_proof_event(
    proof: HistoricalKpiBackfillProof,
    events: Sequence[Mapping[str, Any]],
) -> None:
    event = historical_backfill_event(events)
    if event is None:
        raise HistoricalBackfillProofError(
            "historical KPI backfill event is absent"
        )
    sources = historical_backfill_sources(events, event)
    if (
        proof.event_id != event.get("event_id")
        or proof.revision != event.get("sequence")
        or proof.operation_id != event.get("operation_id")
        or proof.event_sha256
        != sha256(canonical_bytes(event) + b"\n").hexdigest()
        or proof.sources != sources
    ):
        raise HistoricalBackfillProofError(
            "historical KPI backfill event or source set differs"
        )


def validate_proof_objects(
    proof: HistoricalKpiBackfillProof,
    *,
    observed_parent: str,
    observed_tree: str,
    message: str,
    observed_path_blobs: Mapping[str, str],
    commit_in_anchor: bool,
    anchor_in_checkpoint_parent: bool,
) -> None:
    try:
        proof.validate()
    except StudyCloseCheckpointError as exc:
        raise HistoricalBackfillProofError(
            "historical KPI backfill checkpoint proof is invalid"
        ) from exc
    if not commit_in_anchor or not anchor_in_checkpoint_parent:
        raise HistoricalBackfillProofError(
            "historical KPI backfill checkpoint ancestry differs"
        )
    if observed_parent != proof.commit_parent or observed_tree != proof.commit_tree:
        raise HistoricalBackfillProofError(
            "historical KPI backfill commit object differs"
        )
    validate_backfill_trailers(message, proof.event_id, proof.revision)
    expected = {binding.path: binding.blob for binding in proof.path_blobs}
    if observed_path_blobs != expected:
        raise HistoricalBackfillProofError(
            "historical KPI backfill path/blob differs"
        )


__all__ = [
    "BACKFILL_TRAILER",
    "HistoricalBackfillProofError",
    "backfill_trailer_commits",
    "build_historical_backfill_proof",
    "historical_backfill_event",
    "historical_backfill_sources",
    "validate_backfill_trailers",
    "validate_parent_source_set",
    "validate_proof_event",
    "validate_proof_objects",
]
