"""Pure delivery checkpoint transitions and exact staging policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from axiom_rift.operations.study_close_backfill import (
    HistoricalBackfillProofError,
    historical_backfill_event,
    validate_proof_event,
)
from axiom_rift.operations.study_close_checkpoint import (
    CHECKPOINT_PATH,
    CHECKPOINT_SCHEMA,
    HistoricalKpiBackfillProof,
    JournalDeliveryCursor,
    StudyCloseCheckpointError,
    StudyCloseDeliveryCheckpoint,
    validate_checkpoint_transition,
)


class StudyCloseDeliveryPolicyError(ValueError):
    """A pure checkpoint or exact-staging invariant failed."""


class StudyCloseGuardCapability(Enum):
    """Explicit non-production capability accepted by the delivery guard."""

    ISOLATED_ENGINEERING_FIXTURE = "isolated_engineering_fixture"


@dataclass(frozen=True, slots=True)
class StudyCloseDeliveryObservation:
    """Plan-bound local proof that the tracked close checkpoint was delivered."""

    checkpoint_commit: str
    checkpoint_digest: str
    main_head: str
    remote_commit: str
    remote_ref: str = "origin/main"
    schema: str = "study_close_delivery_observation.v1"

    def __post_init__(self) -> None:
        hex_characters = frozenset("0123456789abcdef")
        for name, value in (
            ("checkpoint commit", self.checkpoint_commit),
            ("main head", self.main_head),
            ("remote commit", self.remote_commit),
        ):
            if (
                type(value) is not str
                or len(value) not in {40, 64}
                or any(character not in hex_characters for character in value)
            ):
                raise StudyCloseDeliveryPolicyError(f"{name} is malformed")
        if (
            type(self.checkpoint_digest) is not str
            or len(self.checkpoint_digest) != 64
            or any(
                character not in hex_characters
                for character in self.checkpoint_digest
            )
        ):
            raise StudyCloseDeliveryPolicyError(
                "checkpoint digest is malformed"
            )
        if self.remote_ref != "origin/main":
            raise StudyCloseDeliveryPolicyError(
                "delivery observation remote ref is unsupported"
            )
        if self.schema != "study_close_delivery_observation.v1":
            raise StudyCloseDeliveryPolicyError(
                "delivery observation schema is unsupported"
            )

    def to_payload(self) -> dict[str, str]:
        return {
            "checkpoint_commit": self.checkpoint_commit,
            "checkpoint_digest": self.checkpoint_digest,
            "main_head": self.main_head,
            "remote_commit": self.remote_commit,
            "remote_ref": self.remote_ref,
            "schema": self.schema,
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "StudyCloseDeliveryObservation":
        expected = {
            "checkpoint_commit",
            "checkpoint_digest",
            "main_head",
            "remote_commit",
            "remote_ref",
            "schema",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise StudyCloseDeliveryPolicyError(
                "delivery observation payload is malformed"
            )
        if any(type(payload[name]) is not str for name in expected):
            raise StudyCloseDeliveryPolicyError(
                "delivery observation fields must be strings"
            )
        return cls(
            checkpoint_commit=payload["checkpoint_commit"],
            checkpoint_digest=payload["checkpoint_digest"],
            main_head=payload["main_head"],
            remote_commit=payload["remote_commit"],
            remote_ref=payload["remote_ref"],
            schema=payload["schema"],
        )


@dataclass(frozen=True, slots=True)
class StudyCloseCheckpointPlan:
    """Read-only exact staging plan and the checkpoint it would render."""

    checkpoint: StudyCloseDeliveryCheckpoint
    required_staged_paths: tuple[str, ...]
    allowed_milestone_paths: tuple[str, ...]

    @property
    def next_stage_command(self) -> str:
        return "git add -- " + " ".join(self.required_staged_paths)


def prospective_closes(
    events: Sequence[Mapping[str, Any]],
) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for event in events:
        if any(
            record.get("kind") == "study-kpi"
            and record.get("payload", {}).get("provenance") == "prospective_close"
            for record in event.get("index_records", [])
        ):
            result.append((event["event_id"], event["sequence"]))
    return result


def validate_delivery_checkpoint(
    checkpoint: StudyCloseDeliveryCheckpoint,
    *,
    kpi_content: bytes,
    close_chain: tuple[int, str] | None = None,
    events: Sequence[Mapping[str, Any]] | None = None,
    cursor: JournalDeliveryCursor | None = None,
    previous: StudyCloseDeliveryCheckpoint | None = None,
    suffix_events: Sequence[Mapping[str, Any]] = (),
    suffix_closes: Sequence[tuple[str, int]] | None = None,
) -> None:
    """Common invariant validator for full audit, CLI, hook, and guard paths."""

    kpi_digest = sha256(kpi_content).hexdigest()
    try:
        if previous is not None:
            validate_checkpoint_transition(
                previous,
                checkpoint,
                suffix_closes=(
                    prospective_closes(suffix_events)
                    if suffix_closes is None
                    else suffix_closes
                ),
                current_kpi_sha256=kpi_digest,
            )
            return
        if events is None or cursor is None or close_chain is None:
            raise StudyCloseCheckpointError(
                "full checkpoint validation facts are absent"
            )
        count, chain = close_chain
        if (
            checkpoint.schema != CHECKPOINT_SCHEMA
            or checkpoint.prospective_close_count != count
            or checkpoint.prospective_close_chain_digest != chain
            or checkpoint.cursor != cursor
            or checkpoint.kpi_sha256 != kpi_digest
        ):
            raise StudyCloseCheckpointError(
                "full-audit checkpoint projection differs"
            )
        backfill_event = historical_backfill_event(events)
        proof = checkpoint.historical_kpi_backfill
        if (backfill_event is None) != (proof is None):
            raise StudyCloseCheckpointError(
                "historical KPI backfill proof presence differs"
            )
        if backfill_event is not None and proof is not None:
            validate_proof_event(proof, events)
    except (
        HistoricalBackfillProofError,
        StudyCloseCheckpointError,
    ) as exc:
        raise StudyCloseDeliveryPolicyError(
            "Study-close delivery checkpoint validation failed"
        ) from exc


def canonical_milestone_paths(paths: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in paths:
        if type(value) is not str or not value or "\\" in value:
            raise StudyCloseDeliveryPolicyError(
                "allowed milestone path is invalid"
            )
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.as_posix() != value
        ):
            raise StudyCloseDeliveryPolicyError(
                "allowed milestone path escapes the repository"
            )
        result.append(value)
    if result != sorted(set(result)):
        raise StudyCloseDeliveryPolicyError(
            "allowed milestone paths must be sorted and unique"
        )
    return tuple(result)


def exact_staging_paths(
    *,
    projection_paths: Sequence[str],
    allowed_milestone_paths: Sequence[str],
    staged_paths: Sequence[str],
    unstaged_paths: Sequence[str],
    protected_paths: Sequence[str],
) -> tuple[str, ...]:
    allowed = canonical_milestone_paths(allowed_milestone_paths)
    protected = set(protected_paths) | {CHECKPOINT_PATH}
    if set(allowed) & protected:
        raise StudyCloseDeliveryPolicyError(
            "allowed milestone path overlaps the projection allowlist"
        )
    expected = set(projection_paths) | set(allowed)
    staged = set(staged_paths)
    unstaged = set(unstaged_paths)
    missing = expected - staged
    unexpected = staged - expected
    split = expected & unstaged
    if missing or unexpected or split:
        details = []
        if missing:
            details.append("missing=" + ",".join(sorted(missing)))
        if unexpected:
            details.append("unexpected=" + ",".join(sorted(unexpected)))
        if split:
            details.append("also_unstaged=" + ",".join(sorted(split)))
        raise StudyCloseDeliveryPolicyError(
            "checkpoint exact staging preflight failed: " + "; ".join(details)
        )
    return tuple(sorted(expected))


def project_checkpoint_v2_upgrade(
    *,
    previous: StudyCloseDeliveryCheckpoint,
    previous_commit: str,
    parent_main: str,
    cursor: JournalDeliveryCursor,
    close_chain: tuple[int, str],
    repair_manifest_digest: str | None,
    control_content: bytes,
    kpi_content: bytes,
    historical_kpi_backfill: HistoricalKpiBackfillProof | None,
) -> StudyCloseDeliveryCheckpoint:
    close_count, close_chain_digest = close_chain
    return StudyCloseDeliveryCheckpoint(
        basis="checkpoint_upgrade",
        parent_main=parent_main,
        previous_checkpoint_commit=previous_commit,
        previous_checkpoint_digest=previous.checkpoint_digest,
        cursor=cursor,
        prospective_close_count=close_count,
        prospective_close_chain_digest=close_chain_digest,
        repair_manifest_digest=repair_manifest_digest,
        control_sha256=sha256(control_content).hexdigest(),
        kpi_sha256=sha256(kpi_content).hexdigest(),
        last_study_close_event_id=None,
        last_study_close_revision=None,
        historical_kpi_backfill=historical_kpi_backfill,
    )


def project_checkpoint_maintenance(
    *,
    previous: StudyCloseDeliveryCheckpoint,
    previous_commit: str,
    parent_main: str,
    cursor: JournalDeliveryCursor,
    repair_manifest_digest: str | None,
    control_content: bytes,
    kpi_content: bytes,
) -> StudyCloseDeliveryCheckpoint:
    """Advance a no-close cursor and/or explicit KPI navigation materialization."""

    return StudyCloseDeliveryCheckpoint(
        basis="maintenance",
        parent_main=parent_main,
        previous_checkpoint_commit=previous_commit,
        previous_checkpoint_digest=previous.checkpoint_digest,
        cursor=cursor,
        prospective_close_count=previous.prospective_close_count,
        prospective_close_chain_digest=previous.prospective_close_chain_digest,
        repair_manifest_digest=repair_manifest_digest,
        control_sha256=sha256(control_content).hexdigest(),
        kpi_sha256=sha256(kpi_content).hexdigest(),
        last_study_close_event_id=None,
        last_study_close_revision=None,
        historical_kpi_backfill=previous.historical_kpi_backfill,
    )


__all__ = [
    "StudyCloseCheckpointPlan",
    "StudyCloseDeliveryObservation",
    "StudyCloseDeliveryPolicyError",
    "StudyCloseGuardCapability",
    "canonical_milestone_paths",
    "exact_staging_paths",
    "project_checkpoint_maintenance",
    "project_checkpoint_v2_upgrade",
    "prospective_closes",
    "validate_delivery_checkpoint",
]
