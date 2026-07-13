"""Canonical tracked high-water for Study-close Git delivery."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from axiom_rift.core.canonical import canonical_bytes, parse_canonical


CHECKPOINT_PATH = "records/STUDY_CLOSE_DELIVERY_CHECKPOINT.json"
CHECKPOINT_SCHEMA = "study_close_delivery_checkpoint.v1"
CHECKPOINT_VALIDATOR_VERSION = "study_close_delivery_checkpoint.v1"
EMPTY_CLOSE_CHAIN_DIGEST = sha256(
    b"axiom-study-close-delivery-empty"
).hexdigest()

_HEX = frozenset("0123456789abcdef")
_BASES = frozenset({"full_audit", "study_close"})


class StudyCloseCheckpointError(ValueError):
    """The tracked delivery checkpoint is malformed."""


def _digest(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in _HEX for character in value)
    ):
        raise StudyCloseCheckpointError(f"{label} is invalid")
    return value


def _optional_digest(value: object, label: str) -> str | None:
    return None if value is None else _digest(value, label)


def _commit(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) not in {40, 64}
        or any(character not in _HEX for character in value)
    ):
        raise StudyCloseCheckpointError(f"{label} is invalid")
    return value


def _optional_commit(value: object, label: str) -> str | None:
    return None if value is None else _commit(value, label)


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise StudyCloseCheckpointError(f"{label} is invalid")
    return value


def _journal_path(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or "\\" in value:
        raise StudyCloseCheckpointError("checkpoint Journal path is invalid")
    path = PurePosixPath(value)
    valid = value == "records/journal.jsonl" or (
        tuple(path.parts[:2]) == ("records", "journal")
        and value.endswith(".jsonl")
    )
    if (
        not valid
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise StudyCloseCheckpointError("checkpoint Journal path is invalid")
    return value


@dataclass(frozen=True, slots=True)
class JournalDeliveryCursor:
    """One authenticated Journal boundary; later checks read only its suffix."""

    sequence: int
    event_id: str | None
    previous_event_id: str | None
    event_offset: int | None
    event_bytes: int
    next_offset: int
    boundary_sha256: str
    journal_path: str | None

    @classmethod
    def from_events(
        cls,
        events: Sequence[Mapping[str, Any]],
        *,
        journal_path: str | None,
    ) -> "JournalDeliveryCursor":
        if not events:
            return cls(
                sequence=0,
                event_id=None,
                previous_event_id=None,
                event_offset=None,
                event_bytes=0,
                next_offset=0,
                boundary_sha256=sha256(b"").hexdigest(),
                journal_path=None,
            )
        tail = events[-1]
        framed = canonical_bytes(tail) + b"\n"
        offset = _integer(tail.get("journal_offset"), "Journal event offset")
        return cls(
            sequence=_integer(tail.get("sequence"), "Journal sequence", minimum=1),
            event_id=_digest(tail.get("event_id"), "Journal event id"),
            previous_event_id=_optional_digest(
                tail.get("previous_event_id"), "previous Journal event id"
            ),
            event_offset=offset,
            event_bytes=len(framed),
            next_offset=offset + len(framed),
            boundary_sha256=sha256(framed).hexdigest(),
            journal_path=_journal_path(journal_path),
        )

    @classmethod
    def from_mapping(cls, value: object) -> "JournalDeliveryCursor":
        expected = {
            "boundary_sha256",
            "event_bytes",
            "event_id",
            "event_offset",
            "journal_path",
            "next_offset",
            "previous_event_id",
            "sequence",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise StudyCloseCheckpointError("checkpoint Journal cursor fields differ")
        sequence = _integer(value["sequence"], "checkpoint Journal sequence")
        event_bytes = _integer(value["event_bytes"], "checkpoint event bytes")
        next_offset = _integer(value["next_offset"], "checkpoint next offset")
        event_offset = value["event_offset"]
        if sequence == 0:
            if (
                value["event_id"] is not None
                or value["previous_event_id"] is not None
                or event_offset is not None
                or value["journal_path"] is not None
                or event_bytes != 0
                or next_offset != 0
                or value["boundary_sha256"] != sha256(b"").hexdigest()
            ):
                raise StudyCloseCheckpointError("empty Journal cursor differs")
            return cls.from_events((), journal_path=None)
        offset = _integer(event_offset, "checkpoint Journal event offset")
        if event_bytes < 2 or offset + event_bytes != next_offset:
            raise StudyCloseCheckpointError("checkpoint Journal frame differs")
        return cls(
            sequence=sequence,
            event_id=_digest(value["event_id"], "checkpoint Journal event id"),
            previous_event_id=_optional_digest(
                value["previous_event_id"], "checkpoint previous Journal event id"
            ),
            event_offset=offset,
            event_bytes=event_bytes,
            next_offset=next_offset,
            boundary_sha256=_digest(
                value["boundary_sha256"], "checkpoint Journal boundary hash"
            ),
            journal_path=_journal_path(value["journal_path"]),
        )

    def payload(self) -> dict[str, Any]:
        return {
            "boundary_sha256": self.boundary_sha256,
            "event_bytes": self.event_bytes,
            "event_id": self.event_id,
            "event_offset": self.event_offset,
            "journal_path": self.journal_path,
            "next_offset": self.next_offset,
            "previous_event_id": self.previous_event_id,
            "sequence": self.sequence,
        }


@dataclass(frozen=True, slots=True)
class StudyCloseDeliveryCheckpoint:
    """Small Git-tracked proof that a full prefix was previously audited."""

    basis: str
    parent_main: str
    previous_checkpoint_commit: str | None
    previous_checkpoint_digest: str | None
    cursor: JournalDeliveryCursor
    prospective_close_count: int
    prospective_close_chain_digest: str
    repair_manifest_digest: str | None
    control_sha256: str
    kpi_sha256: str
    last_study_close_event_id: str | None
    last_study_close_revision: int | None

    def body(self) -> dict[str, Any]:
        return {
            "basis": self.basis,
            "control_sha256": self.control_sha256,
            "journal_cursor": self.cursor.payload(),
            "kpi_sha256": self.kpi_sha256,
            "last_study_close_event_id": self.last_study_close_event_id,
            "last_study_close_revision": self.last_study_close_revision,
            "parent_main": self.parent_main,
            "previous_checkpoint_commit": self.previous_checkpoint_commit,
            "previous_checkpoint_digest": self.previous_checkpoint_digest,
            "prospective_close_chain_digest": self.prospective_close_chain_digest,
            "prospective_close_count": self.prospective_close_count,
            "repair_manifest_digest": self.repair_manifest_digest,
            "schema": CHECKPOINT_SCHEMA,
            "validator_version": CHECKPOINT_VALIDATOR_VERSION,
        }

    @property
    def checkpoint_digest(self) -> str:
        return sha256(canonical_bytes(self.body())).hexdigest()

    def render(self) -> bytes:
        return canonical_bytes(
            {**self.body(), "checkpoint_digest": self.checkpoint_digest}
        ) + b"\n"

    @classmethod
    def from_bytes(cls, content: bytes) -> "StudyCloseDeliveryCheckpoint":
        try:
            if not content.endswith(b"\n") or content.count(b"\n") != 1:
                raise StudyCloseCheckpointError("checkpoint framing differs")
            value = parse_canonical(content[:-1])
        except (TypeError, ValueError) as exc:
            raise StudyCloseCheckpointError("checkpoint is not canonical") from exc
        expected = {
            "basis",
            "checkpoint_digest",
            "control_sha256",
            "journal_cursor",
            "kpi_sha256",
            "last_study_close_event_id",
            "last_study_close_revision",
            "parent_main",
            "previous_checkpoint_commit",
            "previous_checkpoint_digest",
            "prospective_close_chain_digest",
            "prospective_close_count",
            "repair_manifest_digest",
            "schema",
            "validator_version",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise StudyCloseCheckpointError("checkpoint fields differ")
        if (
            value["schema"] != CHECKPOINT_SCHEMA
            or value["validator_version"] != CHECKPOINT_VALIDATOR_VERSION
            or value["basis"] not in _BASES
        ):
            raise StudyCloseCheckpointError("checkpoint version or basis differs")
        close_count = _integer(
            value["prospective_close_count"], "prospective close count"
        )
        last_event = _optional_digest(
            value["last_study_close_event_id"], "last Study-close event id"
        )
        last_revision_value = value["last_study_close_revision"]
        last_revision = (
            None
            if last_revision_value is None
            else _integer(last_revision_value, "last Study-close revision", minimum=1)
        )
        if value["basis"] == "full_audit":
            if last_event is not None or last_revision is not None:
                raise StudyCloseCheckpointError("full-audit checkpoint close differs")
        elif last_event is None or last_revision is None:
            raise StudyCloseCheckpointError("Study-close checkpoint close is absent")
        previous_commit = _optional_commit(
            value["previous_checkpoint_commit"], "previous checkpoint commit"
        )
        previous_digest = _optional_digest(
            value["previous_checkpoint_digest"], "previous checkpoint digest"
        )
        if (previous_commit is None) != (previous_digest is None):
            raise StudyCloseCheckpointError("previous checkpoint binding differs")
        checkpoint = cls(
            basis=value["basis"],
            parent_main=_commit(value["parent_main"], "checkpoint parent main"),
            previous_checkpoint_commit=previous_commit,
            previous_checkpoint_digest=previous_digest,
            cursor=JournalDeliveryCursor.from_mapping(value["journal_cursor"]),
            prospective_close_count=close_count,
            prospective_close_chain_digest=_digest(
                value["prospective_close_chain_digest"],
                "prospective close chain digest",
            ),
            repair_manifest_digest=_optional_digest(
                value["repair_manifest_digest"], "repair manifest digest"
            ),
            control_sha256=_digest(value["control_sha256"], "control hash"),
            kpi_sha256=_digest(value["kpi_sha256"], "KPI hash"),
            last_study_close_event_id=last_event,
            last_study_close_revision=last_revision,
        )
        if close_count == 0 and (
            checkpoint.prospective_close_chain_digest != EMPTY_CLOSE_CHAIN_DIGEST
        ):
            raise StudyCloseCheckpointError("empty close chain differs")
        if checkpoint.cursor.sequence < close_count:
            raise StudyCloseCheckpointError("close count exceeds Journal high-water")
        if (
            _digest(value["checkpoint_digest"], "checkpoint digest")
            != checkpoint.checkpoint_digest
        ):
            raise StudyCloseCheckpointError("checkpoint digest differs")
        return checkpoint


def advance_close_chain(current: str, event_id: str, revision: int) -> str:
    return sha256(
        canonical_bytes(
            {
                "previous_digest": _digest(current, "close chain digest"),
                "state_revision": _integer(revision, "Study-close revision", minimum=1),
                "study_close_event_id": _digest(event_id, "Study-close event id"),
            }
        )
    ).hexdigest()


__all__ = [
    "CHECKPOINT_PATH",
    "CHECKPOINT_SCHEMA",
    "CHECKPOINT_VALIDATOR_VERSION",
    "EMPTY_CLOSE_CHAIN_DIGEST",
    "JournalDeliveryCursor",
    "StudyCloseCheckpointError",
    "StudyCloseDeliveryCheckpoint",
    "advance_close_chain",
]
