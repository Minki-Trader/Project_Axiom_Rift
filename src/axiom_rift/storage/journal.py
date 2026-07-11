"""Hash-chained JSONL authority for durable state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import os

from axiom_rift.core.canonical import CanonicalJSONError, canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest


class JournalError(RuntimeError):
    """Base journal failure."""


class TornJournalError(JournalError):
    """The journal ends in an incomplete or oversized record."""


class JournalIntegrityError(JournalError):
    """A journal sequence, chain, or content hash is invalid."""


_WRITE_CAPABILITY_SENTINEL = object()


class _JournalWriteCapability:
    __slots__ = ("_sentinel",)

    def __init__(self, sentinel: object) -> None:
        if sentinel is not _WRITE_CAPABILITY_SENTINEL:
            raise JournalError("Journal write capability cannot be constructed")
        self._sentinel = sentinel


def _issue_journal_write_capability() -> _JournalWriteCapability:
    return _JournalWriteCapability(_WRITE_CAPABILITY_SENTINEL)


@dataclass(frozen=True, slots=True)
class JournalHead:
    sequence: int
    event_id: str | None


class DurableJournal:
    """Append one fsynced canonical event at a time.

    Routine append verifies only the bounded tail. Full replay belongs to
    explicit boot, recovery, rebuild, or audit work.
    """

    MAX_EVENT_BYTES = 1_048_576

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _base(event: Mapping[str, Any]) -> dict[str, Any]:
        base = dict(event)
        base.pop("event_id", None)
        return base

    @classmethod
    def validate_event(
        cls,
        event: Mapping[str, Any],
        *,
        expected_sequence: int,
        expected_previous: str | None,
        expected_offset: int | None = None,
    ) -> dict[str, Any]:
        if event.get("schema") != "journal_event":
            raise JournalIntegrityError("unexpected journal event schema")
        if event.get("sequence") != expected_sequence:
            raise JournalIntegrityError("journal sequence mismatch")
        if event.get("previous_event_id") != expected_previous:
            raise JournalIntegrityError("journal previous-event mismatch")
        journal_offset = event.get("journal_offset")
        if (
            isinstance(journal_offset, bool)
            or not isinstance(journal_offset, int)
            or journal_offset < 0
            or (expected_offset is not None and journal_offset != expected_offset)
        ):
            raise JournalIntegrityError("journal byte offset mismatch")
        record_count = event.get("index_record_count")
        if (
            isinstance(record_count, bool)
            or not isinstance(record_count, int)
            or record_count < 1
        ):
            raise JournalIntegrityError("journal index record count is invalid")
        projection_digest = event.get("index_projection_digest")
        if (
            type(projection_digest) is not str
            or len(projection_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in projection_digest
            )
        ):
            raise JournalIntegrityError("journal index projection digest is invalid")
        event_id = event.get("event_id")
        if not isinstance(event_id, str):
            raise JournalIntegrityError("journal event_id is missing")
        expected_id = canonical_digest(
            domain="journal-event", payload=cls._base(event)
        )
        if event_id != expected_id:
            raise JournalIntegrityError("journal event hash mismatch")
        return dict(event)

    def _parse_line(
        self,
        line: bytes,
        *,
        expected_sequence: int,
        expected_previous: str | None,
        expected_offset: int,
    ) -> dict[str, Any]:
        if not line or len(line) > self.MAX_EVENT_BYTES:
            raise TornJournalError("journal record is empty or exceeds bound")
        try:
            value = parse_canonical(line)
        except CanonicalJSONError as exc:
            raise JournalIntegrityError("journal record is not canonical") from exc
        if not isinstance(value, dict):
            raise JournalIntegrityError("journal record must be an object")
        return self.validate_event(
            value,
            expected_sequence=expected_sequence,
            expected_previous=expected_previous,
            expected_offset=expected_offset,
        )

    def tail(self) -> tuple[JournalHead, dict[str, Any] | None]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return JournalHead(0, None), None
        size = self.path.stat().st_size
        chunk_offset = max(0, size - self.MAX_EVENT_BYTES - 2)
        with self.path.open("rb") as handle:
            handle.seek(chunk_offset)
            chunk = handle.read()
        if not chunk.endswith(b"\n"):
            raise TornJournalError("journal has an incomplete tail")
        content = chunk[:-1]
        split = content.rfind(b"\n")
        if split >= 0:
            line = content[split + 1 :]
            line_offset = chunk_offset + split + 1
        elif size > len(chunk):
            raise TornJournalError("journal tail exceeds the event bound")
        else:
            line = content
            line_offset = chunk_offset
        try:
            value = parse_canonical(line)
        except CanonicalJSONError as exc:
            raise JournalIntegrityError("journal tail is not canonical") from exc
        if not isinstance(value, dict):
            raise JournalIntegrityError("journal tail must be an object")
        sequence = value.get("sequence")
        event_id = value.get("event_id")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise JournalIntegrityError("journal tail sequence is invalid")
        if not isinstance(event_id, str):
            raise JournalIntegrityError("journal tail event_id is invalid")
        if value.get("journal_offset") != line_offset:
            raise JournalIntegrityError("journal tail byte offset mismatch")
        expected_id = canonical_digest(
            domain="journal-event", payload=self._base(value)
        )
        if expected_id != event_id:
            raise JournalIntegrityError("journal tail hash mismatch")
        return JournalHead(sequence, event_id), dict(value)

    def read_all(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return ()
        data = self.path.read_bytes()
        if not data.endswith(b"\n"):
            raise TornJournalError("journal has an incomplete tail")
        events: list[dict[str, Any]] = []
        previous: str | None = None
        offset = 0
        for sequence, framed in enumerate(data.splitlines(keepends=True), start=1):
            if not framed.endswith(b"\n"):
                raise TornJournalError("journal has an incomplete record")
            line = framed[:-1]
            event = self._parse_line(
                line,
                expected_sequence=sequence,
                expected_previous=previous,
                expected_offset=offset,
            )
            previous = event["event_id"]
            events.append(event)
            offset += len(framed)
        return tuple(events)

    def read_event_at(
        self,
        *,
        offset: int,
        expected_sequence: int,
        expected_event_id: str,
    ) -> dict[str, Any]:
        """Read one Journal event by its committed byte offset."""

        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise JournalIntegrityError("journal lookup offset is invalid")
        if not self.path.is_file():
            raise JournalIntegrityError("journal is absent")
        with self.path.open("rb") as handle:
            handle.seek(offset)
            framed = handle.readline(self.MAX_EVENT_BYTES + 2)
        if not framed.endswith(b"\n") or len(framed) > self.MAX_EVENT_BYTES:
            raise TornJournalError("journal indexed event is incomplete or oversized")
        try:
            value = parse_canonical(framed[:-1])
        except CanonicalJSONError as exc:
            raise JournalIntegrityError("journal indexed event is not canonical") from exc
        if not isinstance(value, dict):
            raise JournalIntegrityError("journal indexed event must be an object")
        event = self.validate_event(
            value,
            expected_sequence=expected_sequence,
            expected_previous=value.get("previous_event_id"),
            expected_offset=offset,
        )
        if event["event_id"] != expected_event_id:
            raise JournalIntegrityError("journal indexed event identity mismatch")
        return event

    def _append_authorized(
        self,
        *,
        capability: _JournalWriteCapability,
        expected_head: JournalHead,
        event_kind: str,
        operation_id: str,
        subject: str,
        occurred_at_utc: str,
        payload: Mapping[str, Any],
        control: Mapping[str, Any],
        index_records: list[Mapping[str, Any]],
        index_record_count: int,
        index_projection_digest: str,
    ) -> dict[str, Any]:
        if (
            not isinstance(capability, _JournalWriteCapability)
            or capability._sentinel is not _WRITE_CAPABILITY_SENTINEL
        ):
            raise JournalError("StateWriter capability is required for Journal append")
        actual_head, _ = self.tail()
        if actual_head != expected_head:
            raise JournalIntegrityError("journal tail changed before append")
        journal_offset = self.path.stat().st_size if self.path.exists() else 0
        base: dict[str, Any] = {
            "schema": "journal_event",
            "sequence": expected_head.sequence + 1,
            "previous_event_id": expected_head.event_id,
            "journal_offset": journal_offset,
            "event_kind": event_kind,
            "operation_id": operation_id,
            "subject": subject,
            "occurred_at_utc": occurred_at_utc,
            "payload": dict(payload),
            "control": dict(control),
            "index_records": [dict(item) for item in index_records],
            "index_record_count": index_record_count,
            "index_projection_digest": index_projection_digest,
        }
        event_id = canonical_digest(domain="journal-event", payload=base)
        event = {**base, "event_id": event_id}
        framed = canonical_bytes(event) + b"\n"
        if len(framed) > self.MAX_EVENT_BYTES:
            raise JournalError("journal event exceeds the bounded record size")
        with self.path.open("ab", buffering=0) as handle:
            written = handle.write(framed)
            if written != len(framed):
                raise JournalError("journal append was short")
            handle.flush()
            os.fsync(handle.fileno())
        return event
