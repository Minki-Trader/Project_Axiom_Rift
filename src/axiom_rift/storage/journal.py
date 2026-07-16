"""Hash-chained JSONL authority with immutable segmented storage."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from hmac import new as new_hmac
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any, Callable, Iterable, Iterator, Mapping
import json
import os
import stat as stat_module

from axiom_rift.core.canonical import CanonicalJSONError, canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.storage.atomic_file import (
    AtomicFileError,
    replace_stable_regular_file,
)
from axiom_rift.storage.path_boundary import (
    PathBoundaryError,
    ensure_link_free_directory_chain,
    require_link_free_directory_chain,
)


LEGACY_JOURNAL_RELATIVE_PATH = "records/journal.jsonl"
JOURNAL_DIRECTORY_RELATIVE_PATH = "records/journal"
JOURNAL_MANIFEST_RELATIVE_PATH = "records/journal/manifest.json"
JOURNAL_MANIFEST_SCHEMA = "journal_manifest_v1"
JOURNAL_SEGMENT_SEAL_SCHEMA = "journal_segment_seal_v1"
JOURNAL_OFFSET_MODE = "global_virtual"
JOURNAL_STORAGE_MIGRATION_SCHEMA = "journal_storage_migration.v1"

_MAX_EVENT_BYTES = 1_048_576
_MAX_SEGMENT_BYTES = 32 * 1_048_576
_MAX_SEGMENT_EVENTS = 5_000
_TAIL_READ_CHUNK_BYTES = 64 * 1_024
_WRITE_CAPABILITY_SENTINEL = object()
_HEX = frozenset("0123456789abcdef")


class JournalError(RuntimeError):
    """Base journal failure."""


class TornJournalError(JournalError):
    """A journal segment ends in an incomplete or oversized record."""


class JournalIntegrityError(JournalError):
    """A journal layout, sequence, chain, or content hash is invalid."""


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


class JournalPreappendExpectation:
    """One-shot exact event constraint checked before any Journal mutation.

    The expectation grants no write authority.  It only narrows the existing
    StateWriter capability by requiring the next fully assembled event to be
    byte-identical to an independently prepared event.
    """

    __slots__ = (
        "_canonical_event",
        "_consumed",
        "event_id",
        "operation_id",
        "sequence",
    )

    def __init__(self, event: Mapping[str, Any]) -> None:
        if not isinstance(event, Mapping):
            raise JournalIntegrityError("preappend expectation must be an event")
        sequence = event.get("sequence")
        previous = event.get("previous_event_id")
        if type(sequence) is not int or sequence < 1:
            raise JournalIntegrityError(
                "preappend expectation sequence is invalid"
            )
        if previous is not None and not isinstance(previous, str):
            raise JournalIntegrityError(
                "preappend expectation predecessor is invalid"
            )
        normalized = _validate_event(
            event,
            expected_sequence=sequence,
            expected_previous=previous,
            expected_offset=event.get("journal_offset"),
        )
        operation_id = normalized.get("operation_id")
        if type(operation_id) is not str or not operation_id:
            raise JournalIntegrityError(
                "preappend expectation operation is invalid"
            )
        canonical_event = canonical_bytes(normalized)
        if not canonical_event or len(canonical_event) + 1 > _MAX_EVENT_BYTES:
            raise JournalIntegrityError(
                "preappend expectation exceeds the event bound"
            )
        self._canonical_event = canonical_event
        self._consumed = False
        self.event_id = normalized["event_id"]
        self.operation_id = operation_id
        self.sequence = sequence

    @property
    def canonical_event_sha256(self) -> str:
        return sha256(self._canonical_event).hexdigest()

    @property
    def consumed(self) -> bool:
        return self._consumed

    def _consume(self, event: Mapping[str, Any]) -> None:
        if self._consumed:
            raise JournalIntegrityError(
                "preappend expectation was already consumed"
            )
        self._consumed = True
        if canonical_bytes(dict(event)) != self._canonical_event:
            raise JournalIntegrityError(
                "assembled Journal event differs from the preappend expectation"
            )


@dataclass(frozen=True, slots=True)
class JournalSnapshot:
    """One fully validated virtual Journal snapshot."""

    layout: str
    events: tuple[dict[str, Any], ...]
    active_path: str | None
    manifest_path: str | None
    segment_paths: tuple[str, ...]
    seal_paths: tuple[str, ...]

    @property
    def journal_paths(self) -> tuple[str, ...]:
        paths: list[str] = []
        if self.manifest_path is not None:
            paths.append(self.manifest_path)
        paths.extend(self.segment_paths)
        paths.extend(self.seal_paths)
        if self.layout == "legacy":
            paths.append(LEGACY_JOURNAL_RELATIVE_PATH)
        return tuple(sorted(set(paths)))

    @property
    def head(self) -> JournalHead:
        if not self.events:
            return JournalHead(0, None)
        tail = self.events[-1]
        return JournalHead(tail["sequence"], tail["event_id"])


@dataclass(frozen=True, slots=True)
class _FileSignature:
    size: int
    modified_ns: int
    changed_ns: int
    inode: int
    device: int

    def payload(self) -> dict[str, int]:
        return {
            "changed_ns": self.changed_ns,
            "device": self.device,
            "inode": self.inode,
            "modified_ns": self.modified_ns,
            "size": self.size,
        }

    def same_file_bytes(self, other: "_FileSignature") -> bool:
        return (
            self.size,
            self.modified_ns,
            self.inode,
            self.device,
        ) == (
            other.size,
            other.modified_ns,
            other.inode,
            other.device,
        )


@dataclass(frozen=True, slots=True)
class _SealedSegmentCacheEntry:
    descriptor_digest: str
    content_signature: _FileSignature
    seal_signature: _FileSignature
    content: bytes
    seal_content: bytes
    token: str


SnapshotLoader = Callable[[str], bytes | None]


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise JournalIntegrityError(f"{label} fields differ")


def _require_int(
    value: object, label: str, *, minimum: int = 0
) -> int:
    if type(value) is not int or value < minimum:
        raise JournalIntegrityError(f"{label} is invalid")
    return value


def _require_digest(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in _HEX for character in value)
    ):
        raise JournalIntegrityError(f"{label} is invalid")
    return value


def _require_segment_id(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 6 or not value.isdigit() or value == "000000":
        raise JournalIntegrityError(f"{label} is invalid")
    return value


def _require_journal_path(value: object, label: str, suffix: str) -> str:
    if type(value) is not str or "\\" in value:
        raise JournalIntegrityError(f"{label} is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or tuple(path.parts[:2]) != ("records", "journal")
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
        or not value.endswith(suffix)
    ):
        raise JournalIntegrityError(f"{label} escapes the Journal directory")
    return value


def _segment_path(segment_id: str) -> str:
    return f"records/journal/journal-{segment_id}.jsonl"


def _seal_path(segment_id: str) -> str:
    return f"records/journal/journal-{segment_id}.seal.json"


def _manifest_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    payload.pop("manifest_digest", None)
    return payload


def _manifest_digest(value: Mapping[str, Any]) -> str:
    return canonical_digest(domain="journal-manifest", payload=_manifest_payload(value))


def _render_manifest(
    *, sealed_segments: Iterable[Mapping[str, Any]], active_segment: Mapping[str, Any]
) -> bytes:
    base: dict[str, Any] = {
        "schema": JOURNAL_MANIFEST_SCHEMA,
        "offset_mode": JOURNAL_OFFSET_MODE,
        "sealed_segments": [dict(item) for item in sealed_segments],
        "active_segment": dict(active_segment),
    }
    return canonical_bytes({**base, "manifest_digest": _manifest_digest(base)})


def _render_seal(descriptor: Mapping[str, Any]) -> bytes:
    return canonical_bytes(
        {
            "schema": JOURNAL_SEGMENT_SEAL_SCHEMA,
            "segment_id": descriptor["id"],
            "path": descriptor["path"],
            "start_offset": descriptor["start_offset"],
            "byte_length": descriptor["byte_length"],
            "first_sequence": descriptor["first_sequence"],
            "last_sequence": descriptor["last_sequence"],
            "first_event_id": descriptor["first_event_id"],
            "last_event_id": descriptor["last_event_id"],
            "sha256": descriptor["sha256"],
        }
    )


def _parse_manifest(content: bytes) -> dict[str, Any]:
    try:
        value = parse_canonical(content)
    except CanonicalJSONError as exc:
        raise JournalIntegrityError("Journal manifest is not canonical") from exc
    if not isinstance(value, dict):
        raise JournalIntegrityError("Journal manifest must be an object")
    _require_exact_keys(
        value,
        {
            "schema",
            "offset_mode",
            "sealed_segments",
            "active_segment",
            "manifest_digest",
        },
        "Journal manifest",
    )
    if value["schema"] != JOURNAL_MANIFEST_SCHEMA:
        raise JournalIntegrityError("Journal manifest schema differs")
    if value["offset_mode"] != JOURNAL_OFFSET_MODE:
        raise JournalIntegrityError("Journal offset mode differs")
    if _require_digest(value["manifest_digest"], "Journal manifest digest") != _manifest_digest(value):
        raise JournalIntegrityError("Journal manifest digest mismatch")
    sealed = value["sealed_segments"]
    active = value["active_segment"]
    if not isinstance(sealed, list) or not isinstance(active, dict):
        raise JournalIntegrityError("Journal manifest segment declarations are invalid")
    normalized_sealed: list[dict[str, Any]] = []
    for index, item in enumerate(sealed):
        if not isinstance(item, dict):
            raise JournalIntegrityError("sealed Journal segment must be an object")
        _require_exact_keys(
            item,
            {
                "id",
                "path",
                "seal_path",
                "start_offset",
                "byte_length",
                "first_sequence",
                "last_sequence",
                "first_event_id",
                "last_event_id",
                "sha256",
            },
            "sealed Journal segment",
        )
        segment_id = _require_segment_id(item["id"], "sealed segment id")
        if int(segment_id) != index + 1:
            raise JournalIntegrityError("sealed Journal segment ids are not contiguous")
        path = _require_journal_path(item["path"], "sealed segment path", ".jsonl")
        seal_path = _require_journal_path(item["seal_path"], "segment seal path", ".seal.json")
        if path != _segment_path(segment_id) or seal_path != _seal_path(segment_id):
            raise JournalIntegrityError("sealed Journal segment path differs from its id")
        normalized_sealed.append(
            {
                "id": segment_id,
                "path": path,
                "seal_path": seal_path,
                "start_offset": _require_int(item["start_offset"], "segment start offset"),
                "byte_length": _require_int(item["byte_length"], "segment byte length", minimum=1),
                "first_sequence": _require_int(item["first_sequence"], "segment first sequence", minimum=1),
                "last_sequence": _require_int(item["last_sequence"], "segment last sequence", minimum=1),
                "first_event_id": _require_digest(item["first_event_id"], "segment first event id"),
                "last_event_id": _require_digest(item["last_event_id"], "segment last event id"),
                "sha256": _require_digest(item["sha256"], "segment sha256"),
            }
        )
    _require_exact_keys(
        active,
        {"id", "path", "start_offset", "first_sequence", "previous_event_id"},
        "active Journal segment",
    )
    active_id = _require_segment_id(active["id"], "active segment id")
    if int(active_id) != len(normalized_sealed) + 1:
        raise JournalIntegrityError("active Journal segment id is not contiguous")
    active_path = _require_journal_path(active["path"], "active segment path", ".jsonl")
    if active_path != _segment_path(active_id):
        raise JournalIntegrityError("active Journal segment path differs from its id")
    previous_event_id = active["previous_event_id"]
    if previous_event_id is not None:
        previous_event_id = _require_digest(previous_event_id, "active previous event id")
    normalized_active = {
        "id": active_id,
        "path": active_path,
        "start_offset": _require_int(active["start_offset"], "active segment start offset"),
        "first_sequence": _require_int(active["first_sequence"], "active segment first sequence", minimum=1),
        "previous_event_id": previous_event_id,
    }
    expected_offset = 0
    expected_sequence = 1
    expected_previous: str | None = None
    for descriptor in normalized_sealed:
        if (
            descriptor["start_offset"] != expected_offset
            or descriptor["first_sequence"] != expected_sequence
            or descriptor["last_sequence"] < descriptor["first_sequence"]
        ):
            raise JournalIntegrityError(
                "sealed Journal manifest coordinates contain a gap or overlap"
            )
        expected_offset += descriptor["byte_length"]
        expected_sequence = descriptor["last_sequence"] + 1
        expected_previous = descriptor["last_event_id"]
    if (
        normalized_active["start_offset"] != expected_offset
        or normalized_active["first_sequence"] != expected_sequence
        or normalized_active["previous_event_id"] != expected_previous
    ):
        raise JournalIntegrityError("active Journal manifest coordinates differ")
    return {
        "schema": JOURNAL_MANIFEST_SCHEMA,
        "offset_mode": JOURNAL_OFFSET_MODE,
        "sealed_segments": normalized_sealed,
        "active_segment": normalized_active,
        "manifest_digest": value["manifest_digest"],
    }


def _parse_seal(content: bytes, descriptor: Mapping[str, Any]) -> None:
    try:
        value = parse_canonical(content)
    except CanonicalJSONError as exc:
        raise JournalIntegrityError("Journal segment seal is not canonical") from exc
    if not isinstance(value, dict):
        raise JournalIntegrityError("Journal segment seal must be an object")
    expected = parse_canonical(_render_seal(descriptor))
    if value != expected:
        raise JournalIntegrityError("Journal segment seal differs from manifest")


def _base(event: Mapping[str, Any]) -> dict[str, Any]:
    base = dict(event)
    base.pop("event_id", None)
    return base


def _validate_event(
    event: Mapping[str, Any],
    *,
    expected_sequence: int,
    expected_previous: str | None,
    expected_offset: int | None = None,
) -> dict[str, Any]:
    if event.get("schema") != "journal_event":
        raise JournalIntegrityError("unexpected journal event schema")
    sequence = event.get("sequence")
    if (
        type(expected_sequence) is not int
        or expected_sequence < 1
        or type(sequence) is not int
        or sequence != expected_sequence
    ):
        raise JournalIntegrityError("journal sequence mismatch")
    if expected_offset is not None and (
        type(expected_offset) is not int or expected_offset < 0
    ):
        raise JournalIntegrityError("expected journal byte offset is invalid")
    if event.get("previous_event_id") != expected_previous:
        raise JournalIntegrityError("journal previous-event mismatch")
    journal_offset = event.get("journal_offset")
    if (
        type(journal_offset) is not int
        or journal_offset < 0
        or (expected_offset is not None and journal_offset != expected_offset)
    ):
        raise JournalIntegrityError("journal byte offset mismatch")
    record_count = event.get("index_record_count")
    if type(record_count) is not int or record_count < 1:
        raise JournalIntegrityError("journal index record count is invalid")
    _require_digest(event.get("index_projection_digest"), "journal index projection digest")
    event_id = event.get("event_id")
    if not isinstance(event_id, str):
        raise JournalIntegrityError("journal event_id is missing")
    expected_id = canonical_digest(domain="journal-event", payload=_base(event))
    if event_id != expected_id:
        raise JournalIntegrityError("journal event hash mismatch")
    return dict(event)


def _parse_segment(
    content: bytes,
    *,
    expected_sequence: int,
    expected_previous: str | None,
    start_offset: int,
) -> tuple[list[dict[str, Any]], int, str | None]:
    if content and not content.endswith(b"\n"):
        raise TornJournalError("journal segment has an incomplete tail")
    events: list[dict[str, Any]] = []
    sequence = expected_sequence
    previous = expected_previous
    offset = start_offset
    for framed in content.splitlines(keepends=True):
        if not framed.endswith(b"\n"):
            raise TornJournalError("journal segment has an incomplete record")
        line = framed[:-1]
        if not line or len(line) > _MAX_EVENT_BYTES:
            raise TornJournalError("journal record is empty or exceeds bound")
        try:
            value = parse_canonical(line)
        except CanonicalJSONError as exc:
            raise JournalIntegrityError("journal record is not canonical") from exc
        if not isinstance(value, dict):
            raise JournalIntegrityError("journal record must be an object")
        event = _validate_event(
            value,
            expected_sequence=sequence,
            expected_previous=previous,
            expected_offset=offset,
        )
        events.append(event)
        previous = event["event_id"]
        sequence += 1
        offset += len(framed)
    return events, offset, previous


def _parse_segment_structural(
    content: bytes,
    *,
    expected_sequence: int,
    expected_previous: str | None,
    start_offset: int,
) -> tuple[list[dict[str, Any]], int, str | None]:
    """Parse immutable Git snapshots without recomputing every historical hash."""

    if content and not content.endswith(b"\n"):
        raise TornJournalError("journal segment has an incomplete tail")
    events: list[dict[str, Any]] = []
    sequence = expected_sequence
    previous = expected_previous
    offset = start_offset
    for framed in content.splitlines(keepends=True):
        if not framed.endswith(b"\n") or len(framed) > _MAX_EVENT_BYTES + 1:
            raise TornJournalError("journal record is incomplete or exceeds bound")
        try:
            value = json.loads(framed[:-1].decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JournalIntegrityError("journal record is not JSON") from exc
        if not isinstance(value, dict):
            raise JournalIntegrityError("journal record must be an object")
        if (
            value.get("sequence") != sequence
            or value.get("previous_event_id") != previous
            or value.get("journal_offset") != offset
        ):
            raise JournalIntegrityError("journal structural coordinate mismatch")
        event_id = value.get("event_id")
        if type(event_id) is not str or len(event_id) != 64:
            raise JournalIntegrityError("journal event identity is invalid")
        events.append(value)
        previous = event_id
        sequence += 1
        offset += len(framed)
    return events, offset, previous


def read_journal_snapshot(
    loader: SnapshotLoader,
    *,
    listed_paths: Iterable[str] | None = None,
    validate_events: bool = True,
) -> JournalSnapshot:
    """Read a legacy or segmented Journal through an arbitrary snapshot loader."""

    parser = _parse_segment if validate_events else _parse_segment_structural
    legacy = loader(LEGACY_JOURNAL_RELATIVE_PATH)
    manifest_content = loader(JOURNAL_MANIFEST_RELATIVE_PATH)
    if legacy is not None and manifest_content is not None:
        raise JournalIntegrityError("legacy and segmented Journal layouts overlap")
    if legacy is not None:
        events, _, _ = parser(
            legacy, expected_sequence=1, expected_previous=None, start_offset=0
        )
        return JournalSnapshot(
            layout="legacy",
            events=tuple(events),
            active_path=LEGACY_JOURNAL_RELATIVE_PATH,
            manifest_path=None,
            segment_paths=(),
            seal_paths=(),
        )
    if manifest_content is None:
        if listed_paths is not None and any(
            path.startswith(JOURNAL_DIRECTORY_RELATIVE_PATH + "/")
            and (path.endswith(".jsonl") or path.endswith(".seal.json"))
            for path in listed_paths
        ):
            raise JournalIntegrityError("Journal segments exist without a manifest")
        return JournalSnapshot(
            layout="empty",
            events=(),
            active_path=None,
            manifest_path=None,
            segment_paths=(),
            seal_paths=(),
        )
    manifest = _parse_manifest(manifest_content)
    events: list[dict[str, Any]] = []
    expected_sequence = 1
    expected_previous: str | None = None
    expected_offset = 0
    segment_paths: list[str] = []
    seal_paths: list[str] = []
    for descriptor in manifest["sealed_segments"]:
        if descriptor["start_offset"] != expected_offset:
            raise JournalIntegrityError("sealed Journal byte ranges contain a gap or overlap")
        if descriptor["first_sequence"] != expected_sequence:
            raise JournalIntegrityError("sealed Journal sequence ranges contain a gap or overlap")
        content = loader(descriptor["path"])
        seal = loader(descriptor["seal_path"])
        if content is None or seal is None:
            raise JournalIntegrityError("sealed Journal segment or seal is absent")
        if len(content) != descriptor["byte_length"]:
            raise JournalIntegrityError("sealed Journal segment byte length differs")
        if sha256(content).hexdigest() != descriptor["sha256"]:
            raise JournalIntegrityError("sealed Journal segment hash differs")
        _parse_seal(seal, descriptor)
        segment_events, next_offset, next_previous = parser(
            content,
            expected_sequence=expected_sequence,
            expected_previous=expected_previous,
            start_offset=expected_offset,
        )
        if not segment_events:
            raise JournalIntegrityError("sealed Journal segment is empty")
        if (
            segment_events[0]["sequence"] != descriptor["first_sequence"]
            or segment_events[-1]["sequence"] != descriptor["last_sequence"]
            or segment_events[0]["event_id"] != descriptor["first_event_id"]
            or segment_events[-1]["event_id"] != descriptor["last_event_id"]
            or next_offset != expected_offset + descriptor["byte_length"]
        ):
            raise JournalIntegrityError("sealed Journal segment boundary differs")
        events.extend(segment_events)
        expected_sequence = descriptor["last_sequence"] + 1
        expected_previous = descriptor["last_event_id"]
        expected_offset = next_offset
        segment_paths.append(descriptor["path"])
        seal_paths.append(descriptor["seal_path"])
    active = manifest["active_segment"]
    if (
        active["start_offset"] != expected_offset
        or active["first_sequence"] != expected_sequence
        or active["previous_event_id"] != expected_previous
    ):
        raise JournalIntegrityError("active Journal boundary differs")
    active_content = loader(active["path"])
    if active_content is None:
        raise JournalIntegrityError("active Journal segment is absent")
    active_events, _, _ = parser(
        active_content,
        expected_sequence=expected_sequence,
        expected_previous=expected_previous,
        start_offset=expected_offset,
    )
    events.extend(active_events)
    segment_paths.append(active["path"])
    referenced = {
        JOURNAL_MANIFEST_RELATIVE_PATH,
        *segment_paths,
        *seal_paths,
    }
    if listed_paths is not None:
        declared = {
            path
            for path in listed_paths
            if path == JOURNAL_MANIFEST_RELATIVE_PATH
            or (
                path.startswith(JOURNAL_DIRECTORY_RELATIVE_PATH + "/")
                and (path.endswith(".jsonl") or path.endswith(".seal.json"))
            )
        }
        if declared != referenced:
            raise JournalIntegrityError("unreferenced or missing Journal segment exists")
    return JournalSnapshot(
        layout="segmented",
        events=tuple(events),
        active_path=active["path"],
        manifest_path=JOURNAL_MANIFEST_RELATIVE_PATH,
        segment_paths=tuple(segment_paths),
        seal_paths=tuple(seal_paths),
    )


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, content: bytes) -> None:
    try:
        replace_stable_regular_file(path, content)
    except AtomicFileError as exc:
        raise JournalError("Journal atomic write boundary is invalid") from exc


class DurableJournal:
    """Append one fsynced canonical event to a virtual legacy or segmented Journal."""

    MAX_EVENT_BYTES = _MAX_EVENT_BYTES
    MAX_SEGMENT_BYTES = _MAX_SEGMENT_BYTES
    MAX_SEGMENT_EVENTS = _MAX_SEGMENT_EVENTS
    MAX_VERIFIED_SEALED_CACHE_BYTES = 2 * (
        _MAX_SEGMENT_BYTES + _MAX_EVENT_BYTES
    )

    def __init__(
        self,
        path: str | Path,
        *,
        create_parent: bool = True,
    ) -> None:
        if type(create_parent) is not bool:
            raise ValueError("Journal create_parent must be boolean")
        self.path = Path(path)
        if create_parent:
            try:
                ensure_link_free_directory_chain(self.path.parent)
            except PathBoundaryError as exc:
                raise JournalError(
                    "Journal directory boundary is invalid"
                ) from exc
        self.repository_root = self.path.parent.parent
        self.manifest_path = self.repository_root / JOURNAL_MANIFEST_RELATIVE_PATH
        self.segment_directory = self.repository_root / JOURNAL_DIRECTORY_RELATIVE_PATH
        self._tail_cache: tuple[tuple[Any, ...], JournalHead, dict[str, Any] | None] | None = None
        self._sealed_cache_secret = os.urandom(32)
        self._sealed_segment_cache: dict[str, _SealedSegmentCacheEntry] = {}
        self._sealed_cache_lock = RLock()
        self._preappend_expectation: JournalPreappendExpectation | None = None
        self._preappend_lock = RLock()

    @staticmethod
    def _base(event: Mapping[str, Any]) -> dict[str, Any]:
        return _base(event)

    @classmethod
    def validate_event(
        cls,
        event: Mapping[str, Any],
        *,
        expected_sequence: int,
        expected_previous: str | None,
        expected_offset: int | None = None,
    ) -> dict[str, Any]:
        return _validate_event(
            event,
            expected_sequence=expected_sequence,
            expected_previous=expected_previous,
            expected_offset=expected_offset,
        )

    @contextmanager
    def expect_next_event(
        self,
        event: Mapping[str, Any],
    ) -> Iterator[JournalPreappendExpectation]:
        """Constrain one authorized append to an exact precomputed event.

        The constraint is checked after full event assembly but before segment
        rotation, file open, or write.  A mismatch, nested expectation, reused
        expectation, or context that performs no append fails closed.
        """

        expectation = JournalPreappendExpectation(event)
        with self._preappend_lock:
            if self._preappend_expectation is not None:
                raise JournalIntegrityError(
                    "a preappend expectation is already active"
                )
            self._preappend_expectation = expectation
            try:
                yield expectation
            except BaseException:
                self._preappend_expectation = None
                raise
            else:
                self._preappend_expectation = None
                if not expectation.consumed:
                    raise JournalIntegrityError(
                        "preappend expectation was not consumed"
                    )

    def _absolute(self, relative: str) -> Path:
        return self.repository_root / PurePosixPath(relative)

    @staticmethod
    def _file_signature_from_stat(value: os.stat_result) -> _FileSignature:
        if not stat_module.S_ISREG(value.st_mode):
            raise JournalIntegrityError("sealed Journal artifact is not a regular file")
        return _FileSignature(
            size=value.st_size,
            modified_ns=value.st_mtime_ns,
            changed_ns=value.st_ctime_ns,
            inode=value.st_ino,
            device=value.st_dev,
        )

    @classmethod
    def _file_signature(cls, path: Path) -> _FileSignature:
        try:
            return cls._file_signature_from_stat(path.stat())
        except OSError as exc:
            raise JournalIntegrityError(
                "sealed Journal artifact is unavailable"
            ) from exc

    @classmethod
    def _read_stable_file(cls, path: Path) -> tuple[bytes, _FileSignature]:
        try:
            path_before = cls._file_signature(path)
            with path.open("rb") as handle:
                before = cls._file_signature_from_stat(os.fstat(handle.fileno()))
                content = handle.read()
                after = cls._file_signature_from_stat(os.fstat(handle.fileno()))
            path_after = cls._file_signature(path)
        except OSError as exc:
            raise JournalIntegrityError(
                "sealed Journal artifact is unavailable"
            ) from exc
        if (
            before != after
            or path_before != path_after
            or not after.same_file_bytes(path_after)
            or len(content) != path_after.size
        ):
            raise JournalIntegrityError(
                "sealed Journal artifact changed while it was verified"
            )
        return content, path_after

    @staticmethod
    def _sealed_descriptor_digest(descriptor: Mapping[str, Any]) -> str:
        return sha256(canonical_bytes(dict(descriptor))).hexdigest()

    def _sealed_cache_token(
        self,
        *,
        descriptor_digest: str,
        content_signature: _FileSignature,
        seal_signature: _FileSignature,
        content: bytes,
        seal_content: bytes,
    ) -> str:
        return new_hmac(
            self._sealed_cache_secret,
            canonical_bytes(
                {
                    "content_object_id": id(content),
                    "content_signature": content_signature.payload(),
                    "descriptor_digest": descriptor_digest,
                    "seal_object_id": id(seal_content),
                    "seal_signature": seal_signature.payload(),
                }
            ),
            sha256,
        ).hexdigest()

    def _ensure_sealed_cache_state(self) -> None:
        if (
            type(self._sealed_cache_secret) is not bytes
            or len(self._sealed_cache_secret) != 32
            or type(self._sealed_segment_cache) is not dict
        ):
            self._sealed_cache_secret = os.urandom(32)
            self._sealed_segment_cache = {}

    def _sealed_entry_current(
        self,
        entry: object,
        descriptor: Mapping[str, Any],
    ) -> bool:
        if not isinstance(entry, _SealedSegmentCacheEntry):
            return False
        descriptor_digest = self._sealed_descriptor_digest(descriptor)
        expected_token = self._sealed_cache_token(
            descriptor_digest=descriptor_digest,
            content_signature=entry.content_signature,
            seal_signature=entry.seal_signature,
            content=entry.content,
            seal_content=entry.seal_content,
        )
        if (
            entry.descriptor_digest != descriptor_digest
            or entry.token != expected_token
        ):
            return False
        try:
            return (
                self._file_signature(self._absolute(descriptor["path"]))
                == entry.content_signature
                and self._file_signature(self._absolute(descriptor["seal_path"]))
                == entry.seal_signature
            )
        except JournalIntegrityError:
            return False

    def _read_and_verify_sealed_segment(
        self, descriptor: Mapping[str, Any]
    ) -> _SealedSegmentCacheEntry:
        content, content_signature = self._read_stable_file(
            self._absolute(descriptor["path"])
        )
        seal_content, seal_signature = self._read_stable_file(
            self._absolute(descriptor["seal_path"])
        )
        if (
            len(content) != descriptor["byte_length"]
            or sha256(content).hexdigest() != descriptor["sha256"]
        ):
            raise JournalIntegrityError("sealed Journal segment differs")
        _parse_seal(seal_content, descriptor)
        descriptor_digest = self._sealed_descriptor_digest(descriptor)
        return _SealedSegmentCacheEntry(
            descriptor_digest=descriptor_digest,
            content_signature=content_signature,
            seal_signature=seal_signature,
            content=content,
            seal_content=seal_content,
            token=self._sealed_cache_token(
                descriptor_digest=descriptor_digest,
                content_signature=content_signature,
                seal_signature=seal_signature,
                content=content,
                seal_content=seal_content,
            ),
        )

    def _verified_sealed_segment(
        self, descriptor: Mapping[str, Any]
    ) -> _SealedSegmentCacheEntry:
        with self._sealed_cache_lock:
            return self._verified_sealed_segment_locked(descriptor)

    def _verified_sealed_segment_locked(
        self, descriptor: Mapping[str, Any]
    ) -> _SealedSegmentCacheEntry:
        self._ensure_sealed_cache_state()
        relative = descriptor["path"]
        entry = self._sealed_segment_cache.get(relative)
        if self._sealed_entry_current(entry, descriptor):
            assert isinstance(entry, _SealedSegmentCacheEntry)
            self._sealed_segment_cache.pop(relative)
            self._sealed_segment_cache[relative] = entry
            return entry
        self._sealed_segment_cache.pop(relative, None)
        verified = self._read_and_verify_sealed_segment(descriptor)
        if not self._sealed_entry_current(verified, descriptor):
            raise JournalIntegrityError(
                "sealed Journal segment changed after verification"
            )
        try:
            cached_bytes = sum(
                len(item.content) + len(item.seal_content)
                for item in self._sealed_segment_cache.values()
                if isinstance(item, _SealedSegmentCacheEntry)
            )
            if not all(
                isinstance(item, _SealedSegmentCacheEntry)
                for item in self._sealed_segment_cache.values()
            ):
                raise TypeError("sealed cache entry differs")
        except (AttributeError, TypeError):
            self._sealed_segment_cache.clear()
            cached_bytes = 0
        added_bytes = len(verified.content) + len(verified.seal_content)
        while (
            self._sealed_segment_cache
            and cached_bytes + added_bytes
            > self.MAX_VERIFIED_SEALED_CACHE_BYTES
        ):
            oldest = next(iter(self._sealed_segment_cache))
            removed = self._sealed_segment_cache.pop(oldest)
            assert isinstance(removed, _SealedSegmentCacheEntry)
            cached_bytes -= len(removed.content) + len(removed.seal_content)
        self._sealed_segment_cache[relative] = verified
        return verified

    def _prune_sealed_cache(self, manifest: Mapping[str, Any]) -> None:
        with self._sealed_cache_lock:
            self._ensure_sealed_cache_state()
            current = {item["path"] for item in manifest["sealed_segments"]}
            for relative in tuple(self._sealed_segment_cache):
                if relative not in current:
                    del self._sealed_segment_cache[relative]

    def verify_sealed_segments(
        self, *, expected_manifest_sha256: str | None = None
    ) -> int:
        """Verify current immutable segments, reusing only stable cached bytes."""

        legacy = self.path.is_file()
        segmented = self.manifest_path.is_file()
        if legacy and segmented:
            raise JournalIntegrityError("legacy and segmented Journal layouts overlap")
        if not segmented:
            with self._sealed_cache_lock:
                self._ensure_sealed_cache_state()
                self._sealed_segment_cache.clear()
            if self._listed_paths():
                raise JournalIntegrityError("Journal segments exist without a manifest")
            if expected_manifest_sha256 is not None:
                raise JournalIntegrityError("expected Journal manifest is absent")
            return 0
        manifest_content = self.manifest_path.read_bytes()
        if (
            expected_manifest_sha256 is not None
            and sha256(manifest_content).hexdigest() != expected_manifest_sha256
        ):
            raise JournalIntegrityError("Journal manifest changed before verification")
        manifest = _parse_manifest(manifest_content)
        self._prune_sealed_cache(manifest)
        entries = tuple(
            self._verified_sealed_segment(descriptor)
            for descriptor in manifest["sealed_segments"]
        )
        if any(
            not self._sealed_entry_current(entry, descriptor)
            for entry, descriptor in zip(
                entries, manifest["sealed_segments"], strict=True
            )
        ):
            raise JournalIntegrityError(
                "sealed Journal segment changed during verification"
            )
        if self.manifest_path.read_bytes() != manifest_content:
            raise JournalIntegrityError(
                "Journal manifest changed during sealed verification"
            )
        return len(entries)

    def _load_file(self, relative: str) -> bytes | None:
        path = self._absolute(relative)
        return path.read_bytes() if path.is_file() else None

    def _listed_paths(self) -> tuple[str, ...]:
        if not self.segment_directory.is_dir():
            return ()
        return tuple(
            path.relative_to(self.repository_root).as_posix()
            for path in self.segment_directory.iterdir()
            if path.is_file() and not path.name.startswith(".")
        )

    def _validate_segment_layout_paths(self, manifest: Mapping[str, Any]) -> None:
        referenced = {
            JOURNAL_MANIFEST_RELATIVE_PATH,
            manifest["active_segment"]["path"],
            *[item["path"] for item in manifest["sealed_segments"]],
            *[item["seal_path"] for item in manifest["sealed_segments"]],
        }
        declared = {
            path
            for path in self._listed_paths()
            if path == JOURNAL_MANIFEST_RELATIVE_PATH
            or (
                path.startswith(JOURNAL_DIRECTORY_RELATIVE_PATH + "/")
                and (path.endswith(".jsonl") or path.endswith(".seal.json"))
            )
        }
        if declared != referenced:
            raise JournalIntegrityError(
                "unreferenced or missing Journal segment exists"
            )

    def _snapshot(self) -> JournalSnapshot:
        return read_journal_snapshot(self._load_file, listed_paths=self._listed_paths())

    def _legacy_events(self) -> tuple[dict[str, Any], ...]:
        if not self.path.is_file():
            return ()
        events, _, _ = _parse_segment(
            self.path.read_bytes(),
            expected_sequence=1,
            expected_previous=None,
            start_offset=0,
        )
        return tuple(events)

    def _segmented_cache_key(self, manifest: Mapping[str, Any]) -> tuple[Any, ...]:
        rows: list[Any] = [manifest["manifest_digest"]]
        declared: list[tuple[str, int | None]] = []
        for descriptor in manifest["sealed_segments"]:
            declared.append((descriptor["path"], descriptor["byte_length"]))
            declared.append((descriptor["seal_path"], None))
        declared.append((manifest["active_segment"]["path"], None))
        for relative, expected_size in declared:
            path = self._absolute(relative)
            try:
                value = path.stat()
            except OSError as exc:
                raise JournalIntegrityError("Journal segment is unavailable") from exc
            if not stat_module.S_ISREG(value.st_mode):
                raise JournalIntegrityError("Journal segment is not a regular file")
            if expected_size is not None and value.st_size != expected_size:
                raise JournalIntegrityError(
                    "sealed Journal segment byte length differs"
                )
            rows.append(
                (
                    relative,
                    value.st_size,
                    value.st_mtime_ns,
                    value.st_ctime_ns,
                    value.st_ino,
                    value.st_dev,
                )
            )
        return tuple(rows)

    def _read_segment_boundary_frames(
        self, path: Path
    ) -> tuple[int, bytes | None, bytes | None, int | None]:
        """Read only the first and last bounded frames from one stable segment."""

        try:
            path_before = self._file_signature(path)
            with path.open("rb") as handle:
                opened_before = self._file_signature_from_stat(os.fstat(handle.fileno()))
                size = opened_before.size
                if size == 0:
                    first_framed = None
                    last_framed = None
                    last_offset = None
                else:
                    first_framed = handle.readline(self.MAX_EVENT_BYTES + 2)
                    maximum_window = min(size, self.MAX_EVENT_BYTES + 2)
                    window_size = min(maximum_window, _TAIL_READ_CHUNK_BYTES)
                    window_offset = size - window_size
                    handle.seek(window_offset)
                    window = handle.read(window_size)
                    if len(window) != window_size:
                        raise JournalIntegrityError(
                            "Journal segment changed while its boundary was read"
                        )
                    if not window.endswith(b"\n"):
                        raise TornJournalError(
                            "journal segment has an incomplete tail"
                        )
                    split = window[:-1].rfind(b"\n")
                    while split < 0 and window_offset > 0:
                        if len(window) == maximum_window:
                            raise TornJournalError(
                                "journal tail exceeds the event bound"
                            )
                        prefix_size = min(
                            _TAIL_READ_CHUNK_BYTES,
                            window_offset,
                            maximum_window - len(window),
                        )
                        window_offset -= prefix_size
                        handle.seek(window_offset)
                        prefix = handle.read(prefix_size)
                        if len(prefix) != prefix_size:
                            raise JournalIntegrityError(
                                "Journal segment changed while its boundary was read"
                            )
                        window = prefix + window
                        split = window[:-1].rfind(b"\n")
                    if split >= 0:
                        last_framed = window[split + 1 :]
                        last_offset = window_offset + split + 1
                    else:
                        last_framed = window
                        last_offset = 0
                opened_after = self._file_signature_from_stat(os.fstat(handle.fileno()))
            path_after = self._file_signature(path)
        except OSError as exc:
            raise JournalIntegrityError("Journal segment is unavailable") from exc
        if (
            opened_before != opened_after
            or path_before != path_after
            or not opened_after.same_file_bytes(path_after)
        ):
            raise JournalIntegrityError(
                "Journal segment changed while its boundary was read"
            )
        return size, first_framed, last_framed, last_offset

    def _parse_bounded_frame(self, framed: bytes, *, label: str) -> dict[str, Any]:
        if (
            not framed.endswith(b"\n")
            or framed == b"\n"
            or len(framed) > self.MAX_EVENT_BYTES
        ):
            raise TornJournalError(
                f"{label} is empty, incomplete, or exceeds the event bound"
            )
        try:
            value = parse_canonical(framed[:-1])
        except CanonicalJSONError as exc:
            raise JournalIntegrityError(f"{label} is not canonical") from exc
        if not isinstance(value, dict):
            raise JournalIntegrityError(f"{label} must be an object")
        return value

    def _sealed_segment_boundary_tail(
        self,
        descriptor: Mapping[str, Any],
        *,
        expected_previous: str | None,
    ) -> dict[str, Any]:
        seal_content, _ = self._read_stable_file(
            self._absolute(descriptor["seal_path"])
        )
        if len(seal_content) > self.MAX_EVENT_BYTES:
            raise JournalIntegrityError("Journal segment seal exceeds the bound")
        _parse_seal(seal_content, descriptor)
        size, first_framed, last_framed, last_offset = (
            self._read_segment_boundary_frames(self._absolute(descriptor["path"]))
        )
        if (
            size != descriptor["byte_length"]
            or first_framed is None
            or last_framed is None
            or last_offset is None
        ):
            raise JournalIntegrityError("sealed Journal segment boundary differs")
        first_value = self._parse_bounded_frame(
            first_framed, label="sealed Journal first record"
        )
        first = self.validate_event(
            first_value,
            expected_sequence=descriptor["first_sequence"],
            expected_previous=expected_previous,
            expected_offset=descriptor["start_offset"],
        )
        if first["event_id"] != descriptor["first_event_id"]:
            raise JournalIntegrityError("sealed Journal first identity differs")
        if last_offset == 0:
            tail = first
            if (
                descriptor["last_sequence"] != descriptor["first_sequence"]
                or descriptor["last_event_id"] != descriptor["first_event_id"]
            ):
                raise JournalIntegrityError("sealed Journal range differs")
        else:
            last_value = self._parse_bounded_frame(
                last_framed, label="sealed Journal last record"
            )
            previous = _require_digest(
                last_value.get("previous_event_id"),
                "sealed Journal last previous event id",
            )
            tail = self.validate_event(
                last_value,
                expected_sequence=descriptor["last_sequence"],
                expected_previous=previous,
                expected_offset=descriptor["start_offset"] + last_offset,
            )
            if descriptor["last_sequence"] <= descriptor["first_sequence"]:
                raise JournalIntegrityError("sealed Journal range differs")
        if (
            tail["event_id"] != descriptor["last_event_id"]
            or last_offset + len(last_framed) != descriptor["byte_length"]
        ):
            raise JournalIntegrityError("sealed Journal last boundary differs")
        return tail

    def _segmented_tail(
        self, manifest: Mapping[str, Any]
    ) -> tuple[JournalHead, dict[str, Any] | None]:
        sealed = manifest["sealed_segments"]
        sealed_tail: dict[str, Any] | None = None
        if sealed:
            predecessor = None if len(sealed) == 1 else sealed[-2]["last_event_id"]
            sealed_tail = self._sealed_segment_boundary_tail(
                sealed[-1], expected_previous=predecessor
            )

        active = manifest["active_segment"]
        size, first_framed, last_framed, last_offset = (
            self._read_segment_boundary_frames(self._absolute(active["path"]))
        )
        if size == 0:
            if sealed_tail is None:
                return JournalHead(0, None), None
            return (
                JournalHead(sealed_tail["sequence"], sealed_tail["event_id"]),
                sealed_tail,
            )
        if first_framed is None or last_framed is None or last_offset is None:
            raise JournalIntegrityError("active Journal segment boundary differs")
        first_value = self._parse_bounded_frame(
            first_framed, label="active Journal first record"
        )
        first = self.validate_event(
            first_value,
            expected_sequence=active["first_sequence"],
            expected_previous=active["previous_event_id"],
            expected_offset=active["start_offset"],
        )
        if last_offset == 0:
            tail = first
        else:
            last_value = self._parse_bounded_frame(
                last_framed, label="active Journal last record"
            )
            sequence = _require_int(
                last_value.get("sequence"),
                "active Journal last sequence",
                minimum=active["first_sequence"] + 1,
            )
            previous = _require_digest(
                last_value.get("previous_event_id"),
                "active Journal last previous event id",
            )
            tail = self.validate_event(
                last_value,
                expected_sequence=sequence,
                expected_previous=previous,
                expected_offset=active["start_offset"] + last_offset,
            )
        if last_offset + len(last_framed) != size:
            raise JournalIntegrityError("active Journal last boundary differs")
        return JournalHead(tail["sequence"], tail["event_id"]), tail

    def _legacy_tail(self) -> tuple[JournalHead, dict[str, Any] | None]:
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
        if type(sequence) is not int or sequence < 1:
            raise JournalIntegrityError("journal tail sequence is invalid")
        if not isinstance(event_id, str):
            raise JournalIntegrityError("journal tail event_id is invalid")
        journal_offset = value.get("journal_offset")
        if (
            type(journal_offset) is not int
            or journal_offset != line_offset
        ):
            raise JournalIntegrityError("journal tail byte offset mismatch")
        if canonical_digest(domain="journal-event", payload=_base(value)) != event_id:
            raise JournalIntegrityError("journal tail hash mismatch")
        return JournalHead(sequence, event_id), dict(value)

    def tail(self) -> tuple[JournalHead, dict[str, Any] | None]:
        legacy = self.path.is_file()
        segmented = self.manifest_path.is_file()
        if legacy and segmented:
            raise JournalIntegrityError("legacy and segmented Journal layouts overlap")
        if legacy or not segmented:
            if not segmented and self._listed_paths():
                raise JournalIntegrityError("Journal segments exist without a manifest")
            return self._legacy_tail()
        manifest_content = self.manifest_path.read_bytes()
        manifest = _parse_manifest(manifest_content)
        self._validate_segment_layout_paths(manifest)
        key = self._segmented_cache_key(manifest)
        if self._tail_cache is not None and self._tail_cache[0] == key:
            return self._tail_cache[1], self._tail_cache[2]
        result = self._segmented_tail(manifest)
        if self.manifest_path.read_bytes() != manifest_content:
            raise JournalIntegrityError("Journal manifest changed during tail read")
        self._validate_segment_layout_paths(manifest)
        if self._segmented_cache_key(manifest) != key:
            raise JournalIntegrityError("Journal segment changed during tail read")
        self._tail_cache = (key, result[0], result[1])
        return result

    def read_all(self) -> tuple[dict[str, Any], ...]:
        return self._snapshot().events

    def active_relative_path(self) -> str:
        snapshot = self._snapshot()
        if snapshot.active_path is None:
            return LEGACY_JOURNAL_RELATIVE_PATH
        return snapshot.active_path

    def read_event_at(
        self,
        *,
        offset: int,
        expected_sequence: int,
        expected_event_id: str,
    ) -> dict[str, Any]:
        if type(offset) is not int or offset < 0:
            raise JournalIntegrityError("journal lookup offset is invalid")
        legacy = self.path.is_file()
        segmented = self.manifest_path.is_file()
        if legacy and segmented:
            raise JournalIntegrityError("legacy and segmented Journal layouts overlap")
        if legacy:
            relative = offset
            source = self.path
            sealed_entry: _SealedSegmentCacheEntry | None = None
            sealed_descriptor: Mapping[str, Any] | None = None
        elif segmented:
            manifest = _parse_manifest(self.manifest_path.read_bytes())
            self._prune_sealed_cache(manifest)
            selected: Mapping[str, Any] | None = None
            sealed_entry = None
            sealed_descriptor = None
            for descriptor in manifest["sealed_segments"]:
                if descriptor["start_offset"] <= offset < descriptor["start_offset"] + descriptor["byte_length"]:
                    selected = descriptor
                    sealed_descriptor = descriptor
                    sealed_entry = self._verified_sealed_segment(descriptor)
                    break
            if selected is None:
                active = manifest["active_segment"]
                active_path = self._absolute(active["path"])
                size = active_path.stat().st_size if active_path.is_file() else -1
                if not (active["start_offset"] <= offset < active["start_offset"] + size):
                    raise JournalIntegrityError("journal lookup offset is outside the virtual Journal")
                selected = active
            source = self._absolute(selected["path"])
            relative = offset - selected["start_offset"]
        else:
            raise JournalIntegrityError("journal is absent")
        if sealed_entry is None:
            with source.open("rb") as handle:
                handle.seek(relative)
                framed = handle.readline(self.MAX_EVENT_BYTES + 2)
        else:
            upper = min(len(sealed_entry.content), relative + self.MAX_EVENT_BYTES + 2)
            newline = sealed_entry.content.find(b"\n", relative, upper)
            framed = sealed_entry.content[
                relative : upper if newline < 0 else newline + 1
            ]
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
        if (
            sealed_entry is not None
            and sealed_descriptor is not None
            and not self._sealed_entry_current(sealed_entry, sealed_descriptor)
        ):
            with self._sealed_cache_lock:
                self._sealed_segment_cache.pop(sealed_descriptor["path"], None)
            raise JournalIntegrityError(
                "sealed Journal segment changed during indexed lookup"
            )
        return event

    def _descriptor_for_active(
        self, manifest: Mapping[str, Any], content: bytes
    ) -> dict[str, Any]:
        active = manifest["active_segment"]
        events, _, _ = _parse_segment(
            content,
            expected_sequence=active["first_sequence"],
            expected_previous=active["previous_event_id"],
            start_offset=active["start_offset"],
        )
        if not events:
            raise JournalIntegrityError("empty active Journal segment cannot be sealed")
        return {
            "id": active["id"],
            "path": active["path"],
            "seal_path": _seal_path(active["id"]),
            "start_offset": active["start_offset"],
            "byte_length": len(content),
            "first_sequence": events[0]["sequence"],
            "last_sequence": events[-1]["sequence"],
            "first_event_id": events[0]["event_id"],
            "last_event_id": events[-1]["event_id"],
            "sha256": sha256(content).hexdigest(),
        }

    @staticmethod
    def _next_active(descriptor: Mapping[str, Any]) -> dict[str, Any]:
        number = int(descriptor["id"]) + 1
        if number > 999_999:
            raise JournalError("Journal segment id space is exhausted")
        segment_id = f"{number:06d}"
        return {
            "id": segment_id,
            "path": _segment_path(segment_id),
            "start_offset": descriptor["start_offset"] + descriptor["byte_length"],
            "first_sequence": descriptor["last_sequence"] + 1,
            "previous_event_id": descriptor["last_event_id"],
        }

    @staticmethod
    def _inject(crash_after: str | None, label: str) -> None:
        if crash_after == label:
            raise JournalError(f"injected Journal storage crash: {label}")

    def _rotate(self, *, crash_after: str | None = None) -> None:
        manifest = _parse_manifest(self.manifest_path.read_bytes())
        snapshot = self._snapshot()
        if snapshot.layout != "segmented":
            raise JournalIntegrityError("Journal rotation requires segmented storage")
        active_path = self._absolute(manifest["active_segment"]["path"])
        content = active_path.read_bytes()
        descriptor = self._descriptor_for_active(manifest, content)
        next_active = self._next_active(descriptor)
        with active_path.open("rb+") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        seal_path = self._absolute(descriptor["seal_path"])
        if seal_path.exists():
            raise JournalIntegrityError("active Journal segment already has a seal")
        _atomic_write(seal_path, _render_seal(descriptor))
        self._inject(crash_after, "after_seal")
        next_path = self._absolute(next_active["path"])
        if next_path.exists():
            raise JournalIntegrityError("next active Journal segment already exists")
        _atomic_write(next_path, b"")
        self._inject(crash_after, "after_active")
        _atomic_write(
            self.manifest_path,
            _render_manifest(
                sealed_segments=(*manifest["sealed_segments"], descriptor),
                active_segment=next_active,
            ),
        )
        self._inject(crash_after, "after_manifest")
        self._tail_cache = None

    def recover_rotation(self) -> bool:
        """Complete an interrupted seal-first rotation without adding an event."""

        if not self.manifest_path.is_file():
            return False
        manifest = _parse_manifest(self.manifest_path.read_bytes())
        active = manifest["active_segment"]
        active_path = self._absolute(active["path"])
        seal_path = self._absolute(_seal_path(active["id"]))
        next_id = f"{int(active['id']) + 1:06d}"
        next_path = self._absolute(_segment_path(next_id))
        if not seal_path.exists():
            if next_path.exists():
                raise JournalIntegrityError("orphan next Journal segment lacks a seal")
            return False
        if not active_path.is_file():
            raise JournalIntegrityError("interrupted Journal rotation lost its active segment")
        content = active_path.read_bytes()
        descriptor = self._descriptor_for_active(manifest, content)
        _parse_seal(seal_path.read_bytes(), descriptor)
        if not next_path.exists():
            _atomic_write(next_path, b"")
        elif next_path.read_bytes() != b"":
            raise JournalIntegrityError("uncommitted next Journal segment is not empty")
        next_active = self._next_active(descriptor)
        _atomic_write(
            self.manifest_path,
            _render_manifest(
                sealed_segments=(*manifest["sealed_segments"], descriptor),
                active_segment=next_active,
            ),
        )
        self._tail_cache = None
        self._snapshot()
        return True

    def _migration_payload(self, event: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = event.get("payload")
        if event.get("event_kind") != "journal_storage_migrated" or not isinstance(payload, dict):
            raise JournalIntegrityError("Journal storage migration event is malformed")
        if payload.get("schema") != JOURNAL_STORAGE_MIGRATION_SCHEMA:
            raise JournalIntegrityError("Journal storage migration schema differs")
        expected = {
            "legacy_path": LEGACY_JOURNAL_RELATIVE_PATH,
            "manifest_path": JOURNAL_MANIFEST_RELATIVE_PATH,
            "sealed_segment_id": "000001",
            "sealed_segment_path": _segment_path("000001"),
            "seal_path": _seal_path("000001"),
            "active_segment_id": "000002",
            "active_segment_path": _segment_path("000002"),
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise JournalIntegrityError("Journal storage migration paths differ")
        pre = payload.get("pre_migration")
        if not isinstance(pre, dict):
            raise JournalIntegrityError("Journal storage migration predecessor is absent")
        _require_exact_keys(
            pre,
            {"byte_length", "sha256", "first_sequence", "last_sequence", "first_event_id", "last_event_id"},
            "Journal storage migration predecessor",
        )
        _require_int(pre["byte_length"], "pre-migration byte length", minimum=1)
        _require_digest(pre["sha256"], "pre-migration sha256")
        _require_int(pre["first_sequence"], "pre-migration first sequence", minimum=1)
        _require_int(pre["last_sequence"], "pre-migration last sequence", minimum=1)
        _require_digest(pre["first_event_id"], "pre-migration first event id")
        _require_digest(pre["last_event_id"], "pre-migration last event id")
        if (
            payload.get("trial_delta") != 0
            or payload.get("holdout_delta") != 0
            or payload.get("candidate_delta") != 0
            or payload.get("claim_delta") != 0
        ):
            raise JournalIntegrityError("Journal storage migration changes scientific state")
        return payload

    def materialize_legacy_migration(
        self,
        event: Mapping[str, Any],
        *,
        after_stage: Callable[[str], None] | None = None,
    ) -> None:
        """Copy exact legacy bytes, seal them, activate a new empty segment, then unlink legacy."""

        payload = self._migration_payload(event)

        def staged(label: str) -> None:
            if after_stage is not None:
                after_stage(label)

        if not self.path.is_file():
            if not self.manifest_path.is_file():
                raise JournalIntegrityError("Journal migration lost both storage layouts")
            snapshot = self._snapshot()
            if snapshot.head != JournalHead(event["sequence"], event["event_id"]):
                raise JournalIntegrityError("segmented Journal migration head differs")
            return
        legacy_content = self.path.read_bytes()
        legacy_events, _, _ = _parse_segment(
            legacy_content,
            expected_sequence=1,
            expected_previous=None,
            start_offset=0,
        )
        if not legacy_events or legacy_events[-1]["event_id"] != event["event_id"]:
            raise JournalIntegrityError("Journal migration event is not the legacy tail")
        pre = payload["pre_migration"]
        prefix = legacy_content[: pre["byte_length"]]
        if (
            len(prefix) != pre["byte_length"]
            or sha256(prefix).hexdigest() != pre["sha256"]
            or event["journal_offset"] != pre["byte_length"]
            or event["sequence"] != pre["last_sequence"] + 1
            or legacy_events[0]["sequence"] != pre["first_sequence"]
            or legacy_events[0]["event_id"] != pre["first_event_id"]
            or legacy_events[-2]["sequence"] != pre["last_sequence"]
            or legacy_events[-2]["event_id"] != pre["last_event_id"]
        ):
            raise JournalIntegrityError("Journal migration predecessor bytes differ")
        descriptor = {
            "id": "000001",
            "path": _segment_path("000001"),
            "seal_path": _seal_path("000001"),
            "start_offset": 0,
            "byte_length": len(legacy_content),
            "first_sequence": legacy_events[0]["sequence"],
            "last_sequence": legacy_events[-1]["sequence"],
            "first_event_id": legacy_events[0]["event_id"],
            "last_event_id": legacy_events[-1]["event_id"],
            "sha256": sha256(legacy_content).hexdigest(),
        }
        active = self._next_active(descriptor)
        segment_path = self._absolute(descriptor["path"])
        if segment_path.is_file():
            if segment_path.read_bytes() != legacy_content:
                raise JournalIntegrityError("migrated Journal segment bytes differ")
        else:
            _atomic_write(segment_path, legacy_content)
        staged("after_segment")
        seal_path = self._absolute(descriptor["seal_path"])
        seal_bytes = _render_seal(descriptor)
        if seal_path.is_file():
            if seal_path.read_bytes() != seal_bytes:
                raise JournalIntegrityError("migrated Journal seal differs")
        else:
            _atomic_write(seal_path, seal_bytes)
        staged("after_seal")
        active_path = self._absolute(active["path"])
        if active_path.is_file():
            if active_path.read_bytes() != b"":
                raise JournalIntegrityError("migrated active Journal is not empty")
        else:
            _atomic_write(active_path, b"")
        staged("after_active")
        manifest_bytes = _render_manifest(sealed_segments=(descriptor,), active_segment=active)
        if self.manifest_path.is_file():
            if self.manifest_path.read_bytes() != manifest_bytes:
                raise JournalIntegrityError("migrated Journal manifest differs")
        else:
            _atomic_write(self.manifest_path, manifest_bytes)
        staged("after_manifest")
        segmented = read_journal_snapshot(
            lambda relative: (
                None
                if relative == LEGACY_JOURNAL_RELATIVE_PATH
                else self._load_file(relative)
            ),
            listed_paths=self._listed_paths(),
        )
        if segmented.events != tuple(legacy_events):
            raise JournalIntegrityError("segmented Journal replay differs before activation")
        self.path.unlink()
        _fsync_directory(self.path.parent)
        staged("after_legacy_removal")
        self._tail_cache = None
        if self._snapshot().events != tuple(legacy_events):
            raise JournalIntegrityError("segmented Journal replay differs after activation")

    def recover_storage(self) -> bool:
        """Complete a typed legacy migration or interrupted segment rotation."""

        changed = False
        if self.path.is_file():
            events = self._legacy_events()
            residue = self.manifest_path.exists() or bool(self._listed_paths())
            if events and events[-1].get("event_kind") == "journal_storage_migrated":
                self.materialize_legacy_migration(events[-1])
                changed = True
            elif residue:
                raise JournalIntegrityError("Journal storage residue lacks a migration event")
        elif not self.manifest_path.is_file() and self._listed_paths():
            raise JournalIntegrityError("Journal segments exist without recoverable authority")
        if self.manifest_path.is_file() and self.recover_rotation():
            changed = True
        return changed

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
        segmented = self.manifest_path.is_file()
        if self.path.is_file() and segmented:
            raise JournalIntegrityError("legacy and segmented Journal layouts overlap")
        if segmented:
            manifest = _parse_manifest(self.manifest_path.read_bytes())
            active = manifest["active_segment"]
            active_path = self._absolute(active["path"])
            active_size = active_path.stat().st_size
            journal_offset = active["start_offset"] + active_size
            active_count = max(0, expected_head.sequence - active["first_sequence"] + 1)
        else:
            manifest = None
            active_path = self.path
            active_size = self.path.stat().st_size if self.path.exists() else 0
            journal_offset = active_size
            active_count = expected_head.sequence
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
        with self._preappend_lock:
            expectation = self._preappend_expectation
            if expectation is not None:
                expectation._consume(event)
        if segmented and active_count > 0 and (
            active_count >= self.MAX_SEGMENT_EVENTS
            or active_size + len(framed) > self.MAX_SEGMENT_BYTES
        ):
            self._rotate()
            manifest = _parse_manifest(self.manifest_path.read_bytes())
            active_path = self._absolute(manifest["active_segment"]["path"])
            if manifest["active_segment"]["start_offset"] != journal_offset:
                raise JournalIntegrityError("rotated Journal global offset changed")
        try:
            ensure_link_free_directory_chain(active_path.parent)
        except PathBoundaryError as exc:
            raise JournalError(
                "Journal append directory boundary is invalid"
            ) from exc
        with active_path.open("ab", buffering=0) as handle:
            try:
                require_link_free_directory_chain(active_path.parent)
            except PathBoundaryError as exc:
                raise JournalError(
                    "Journal append directory changed"
                ) from exc
            written = handle.write(framed)
            if written != len(framed):
                raise JournalError("journal append was short")
            handle.flush()
            os.fsync(handle.fileno())
        if segmented:
            manifest = _parse_manifest(self.manifest_path.read_bytes())
            key = self._segmented_cache_key(manifest)
            self._tail_cache = (key, JournalHead(event["sequence"], event_id), event)
        return event


__all__ = [
    "DurableJournal",
    "JOURNAL_DIRECTORY_RELATIVE_PATH",
    "JOURNAL_MANIFEST_RELATIVE_PATH",
    "JOURNAL_STORAGE_MIGRATION_SCHEMA",
    "JournalError",
    "JournalHead",
    "JournalIntegrityError",
    "JournalPreappendExpectation",
    "JournalSnapshot",
    "LEGACY_JOURNAL_RELATIVE_PATH",
    "TornJournalError",
    "read_journal_snapshot",
]
