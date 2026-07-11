"""Reconstructible, keyed SQLite projection for durable Axiom records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterator

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest


class LocalIndexError(RuntimeError):
    """Base error for local-index failures."""


class RecordCollisionError(LocalIndexError):
    """An immutable key or event position was reused with different content."""


class IndexIntegrityError(LocalIndexError):
    """The SQLite projection failed an integrity or foreign-key check."""


class QueryPlanError(LocalIndexError):
    """A named current-work lookup would scan its history-growing table."""


@dataclass(frozen=True, slots=True)
class IndexRecord:
    """One immutable durable-record projection.

    ``fingerprint`` is the caller's semantic/content identity.  Idempotency is
    stricter than fingerprint equality: all projected fields and canonical
    payload bytes must agree when ``(kind, record_id)`` already exists.
    """

    kind: str
    record_id: str
    subject: str
    status: str
    fingerprint: str
    payload: Mapping[str, Any]
    event_stream: str | None = None
    event_sequence: int | None = None
    authority_sequence: int | None = None
    authority_event_id: str | None = None
    authority_offset: int | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "IndexRecord":
        return cls(
            kind=value["kind"],
            record_id=value["record_id"],
            subject=value["subject"],
            status=value["status"],
            fingerprint=value["fingerprint"],
            payload=value.get("payload", {}),
            event_stream=value.get("event_stream"),
            event_sequence=value.get("event_sequence"),
            authority_sequence=value.get("authority_sequence"),
            authority_event_id=value.get("authority_event_id"),
            authority_offset=value.get("authority_offset"),
        )


@dataclass(frozen=True, slots=True)
class EventHead:
    """Latest event position projected for one append-only stream."""

    stream: str
    sequence: int
    record_kind: str
    record_id: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class _PreparedRecord:
    record: IndexRecord
    payload_json: str
    record_digest: str
    projection_member_digest: str


@dataclass(frozen=True, slots=True)
class CurrentAccessTrace:
    """Mechanical evidence for one bounded current-work lookup."""

    query_name: str
    access_shape: tuple[str, ...]
    uniqueness_basis: str
    visited_row_upper_bound: int
    returned_row_count: int
    manifest_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _HotQuery:
    sql: str
    target_table: str
    key_columns: tuple[str, ...] = ()
    plan_marker: str = ""


_RECORD_COLUMN_NAMES = (
    "kind",
    "record_id",
    "subject",
    "status",
    "fingerprint",
    "payload_json",
    "event_stream",
    "event_sequence",
    "authority_sequence",
    "authority_event_id",
    "authority_offset",
    "record_digest",
)

_SELECT_RECORD_COLUMNS = ", ".join(_RECORD_COLUMN_NAMES)

_HOT_QUERIES: dict[str, _HotQuery] = {
    "record_by_key": _HotQuery(
        f"SELECT {_SELECT_RECORD_COLUMNS} FROM records "
        "WHERE kind = ? AND record_id = ?",
        "records",
        ("kind", "record_id"),
        "USING PRIMARY KEY",
    ),
    "records_by_subject_status": _HotQuery(
        f"SELECT {_SELECT_RECORD_COLUMNS} FROM records "
        "WHERE subject = ? AND status = ? ORDER BY kind, record_id",
        "records",
    ),
    "records_by_fingerprint": _HotQuery(
        f"SELECT {_SELECT_RECORD_COLUMNS} FROM records "
        "WHERE fingerprint = ? ORDER BY kind, record_id",
        "records",
    ),
    "records_by_kind": _HotQuery(
        f"SELECT {_SELECT_RECORD_COLUMNS} FROM records "
        "WHERE kind = ? ORDER BY record_id",
        "records",
        ("kind",),
        "USING PRIMARY KEY",
    ),
    "event_head_by_stream": _HotQuery(
        "SELECT stream, sequence, record_kind, record_id, fingerprint "
        "FROM event_heads WHERE stream = ?",
        "event_heads",
        ("stream",),
        "USING PRIMARY KEY",
    ),
    "latest_event_record_by_stream": _HotQuery(
        f"SELECT {_SELECT_RECORD_COLUMNS} FROM records "
        "WHERE event_stream = ? ORDER BY event_sequence DESC LIMIT 1",
        "records",
        ("event_stream",),
        "USING INDEX uq_records_event_position",
    ),
    "event_record_by_position": _HotQuery(
        f"SELECT {_SELECT_RECORD_COLUMNS} FROM records "
        "WHERE event_stream = ? AND event_sequence = ?",
        "records",
        ("event_stream", "event_sequence"),
        "USING INDEX uq_records_event_position",
    ),
    "projection_record_count": _HotQuery(
        "SELECT record_count FROM projection_stats WHERE singleton = ?",
        "projection_stats",
        ("singleton",),
        "USING PRIMARY KEY",
    ),
}

_EMPTY_PROJECTION_DIGEST = canonical_digest(
    domain="index-projection-chain", payload={"empty": True}
)

_CURRENT_QUERY_NAMES = (
    "record_by_key",
    "event_head_by_stream",
    "latest_event_record_by_stream",
    "event_record_by_position",
    "projection_record_count",
)


_CREATE_SCHEMA = """
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS records (
    kind           TEXT NOT NULL,
    record_id      TEXT NOT NULL,
    subject        TEXT NOT NULL,
    status         TEXT NOT NULL,
    fingerprint    TEXT NOT NULL,
    payload_json   TEXT NOT NULL,
    event_stream   TEXT,
    event_sequence INTEGER,
    authority_sequence INTEGER,
    authority_event_id TEXT,
    authority_offset INTEGER,
    record_digest  TEXT NOT NULL,
    PRIMARY KEY (kind, record_id),
    CHECK (length(kind) > 0),
    CHECK (length(record_id) > 0),
    CHECK (length(subject) > 0),
    CHECK (length(status) > 0),
    CHECK (length(fingerprint) > 0),
    CHECK (length(record_digest) = 64),
    CHECK (
        (authority_sequence IS NULL AND authority_event_id IS NULL AND
         authority_offset IS NULL) OR
        (authority_sequence IS NOT NULL AND authority_sequence >= 1 AND
         authority_event_id IS NOT NULL AND length(authority_event_id) = 64 AND
         authority_offset IS NOT NULL AND authority_offset >= 0)
    ),
    CHECK (
        (event_stream IS NULL AND event_sequence IS NULL) OR
        (event_stream IS NOT NULL AND length(event_stream) > 0 AND
         event_sequence IS NOT NULL AND event_sequence >= 0)
    )
) STRICT, WITHOUT ROWID;

CREATE UNIQUE INDEX IF NOT EXISTS uq_records_event_position
ON records(event_stream, event_sequence)
WHERE event_stream IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_records_subject_status
ON records(subject, status, kind, record_id);

CREATE INDEX IF NOT EXISTS ix_records_fingerprint
ON records(fingerprint, kind, record_id);

CREATE TABLE IF NOT EXISTS event_heads (
    stream       TEXT NOT NULL PRIMARY KEY,
    sequence     INTEGER NOT NULL CHECK (sequence >= 0),
    record_kind  TEXT NOT NULL,
    record_id    TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,
    FOREIGN KEY (record_kind, record_id)
        REFERENCES records(kind, record_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS projection_stats (
    singleton    INTEGER NOT NULL PRIMARY KEY CHECK (singleton = 1),
    record_count INTEGER NOT NULL CHECK (record_count >= 0),
    projection_digest TEXT NOT NULL CHECK (length(projection_digest) = 64),
    projection_valid INTEGER NOT NULL CHECK (projection_valid IN (0, 1))
) STRICT, WITHOUT ROWID;

INSERT OR IGNORE INTO projection_stats(
    singleton, record_count, projection_digest, projection_valid
)
VALUES (1, 0, '04ea52d5a458f4242a8221ed978ecddcaf1c03c615ea32daa783ce6f0caac13e', 1);

CREATE TRIGGER IF NOT EXISTS records_projection_count_insert
AFTER INSERT ON records
BEGIN
    UPDATE projection_stats SET record_count = record_count + 1 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS records_projection_count_delete
AFTER DELETE ON records
BEGIN
    UPDATE projection_stats
    SET record_count = record_count - 1, projection_valid = 0
    WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS records_projection_update_invalid
AFTER UPDATE ON records
BEGIN
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS event_heads_projection_insert_invalid
AFTER INSERT ON event_heads
BEGIN
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS event_heads_projection_update_invalid
AFTER UPDATE ON event_heads
BEGIN
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS event_heads_projection_delete_invalid
AFTER DELETE ON event_heads
BEGIN
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

COMMIT;
"""


_INSERT_RECORD = """
INSERT INTO records (
    kind, record_id, subject, status, fingerprint, payload_json,
    event_stream, event_sequence, authority_sequence, authority_event_id,
    authority_offset, record_digest
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_UPSERT_EVENT_HEAD = """
INSERT INTO event_heads (
    stream, sequence, record_kind, record_id, fingerprint
) VALUES (?, ?, ?, ?, ?)
ON CONFLICT(stream) DO UPDATE SET
    sequence = excluded.sequence,
    record_kind = excluded.record_kind,
    record_id = excluded.record_id,
    fingerprint = excluded.fingerprint
WHERE excluded.sequence > event_heads.sequence
"""


def _canonical_json(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise TypeError("record payload must be a mapping")
    try:
        return canonical_bytes(dict(payload)).decode("ascii")
    except (TypeError, ValueError) as exc:
        raise ValueError("record payload is not canonical JSON data") from exc


def _require_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _prepare(value: IndexRecord | Mapping[str, Any]) -> _PreparedRecord:
    record = value if isinstance(value, IndexRecord) else IndexRecord.from_mapping(value)
    _require_text("kind", record.kind)
    _require_text("record_id", record.record_id)
    _require_text("subject", record.subject)
    _require_text("status", record.status)
    _require_text("fingerprint", record.fingerprint)
    if (record.event_stream is None) != (record.event_sequence is None):
        raise ValueError("event_stream and event_sequence must be set together")
    if record.event_stream is not None:
        _require_text("event_stream", record.event_stream)
        if isinstance(record.event_sequence, bool) or not isinstance(
            record.event_sequence, int
        ):
            raise ValueError("event_sequence must be a non-negative integer")
        if record.event_sequence < 0:
            raise ValueError("event_sequence must be a non-negative integer")
    authority_values = (
        record.authority_sequence,
        record.authority_event_id,
        record.authority_offset,
    )
    if any(value is not None for value in authority_values):
        if any(value is None for value in authority_values):
            raise ValueError("record authority fields must be set together")
        if (
            isinstance(record.authority_sequence, bool)
            or not isinstance(record.authority_sequence, int)
            or record.authority_sequence < 1
            or type(record.authority_event_id) is not str
            or len(record.authority_event_id) != 64
            or any(
                character not in "0123456789abcdef"
                for character in record.authority_event_id
            )
            or isinstance(record.authority_offset, bool)
            or not isinstance(record.authority_offset, int)
            or record.authority_offset < 0
        ):
            raise ValueError("record authority fields are invalid")
    payload_json = _canonical_json(record.payload)
    return _PreparedRecord(
        record=record,
        payload_json=payload_json,
        record_digest=_record_digest(record, payload_json),
        projection_member_digest=_projection_member_digest(record, payload_json),
    )


def _record_digest(record: IndexRecord, payload_json: str) -> str:
    """Digest the exact Journal-committed projection fields.

    The digest is included in the Journal event through the record projection
    and checked on every decode.  It turns an in-place SQLite row edit into an
    explicit projection-integrity failure instead of a new authority claim.
    """

    payload = parse_canonical(payload_json)
    return canonical_digest(
        domain="index-record-projection",
        payload={
            "event_sequence": record.event_sequence,
            "event_stream": record.event_stream,
            "fingerprint": record.fingerprint,
            "kind": record.kind,
            "payload": payload,
            "record_id": record.record_id,
            "status": record.status,
            "subject": record.subject,
            "authority_sequence": record.authority_sequence,
            "authority_event_id": record.authority_event_id,
            "authority_offset": record.authority_offset,
        },
    )


def _projection_member_digest(record: IndexRecord, payload_json: str) -> str:
    """Digest the authority-neutral record fields committed inside a Journal event."""

    payload = parse_canonical(payload_json)
    return canonical_digest(
        domain="index-projection-member",
        payload={
            "event_sequence": record.event_sequence,
            "event_stream": record.event_stream,
            "fingerprint": record.fingerprint,
            "kind": record.kind,
            "payload": payload,
            "record_id": record.record_id,
            "status": record.status,
            "subject": record.subject,
        },
    )


def _advance_projection_digest(previous: str, member: str) -> str:
    return canonical_digest(
        domain="index-projection-chain",
        payload={"member": member, "previous": previous},
    )


class LocalIndex:
    """Small local SQLite projection reconstructed from durable records.

    The database intentionally uses the rollback journal.  The bundled SQLite
    version is not assumed safe for concurrent WAL checkpoint/write activity.
    All mutations use one explicit ``BEGIN IMMEDIATE`` transaction.
    """

    BUSY_TIMEOUT_MS = 5_000

    def __init__(
        self,
        path: str | Path,
        *,
        authority_validator: Callable[[IndexRecord], None] | None = None,
    ) -> None:
        self.path = Path(path)
        self._authority_validator = authority_validator
        if str(path) == ":memory:":
            raise ValueError("LocalIndex requires a filesystem path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self.path,
            isolation_level=None,
            timeout=self.BUSY_TIMEOUT_MS / 1_000,
        )
        self._connection.row_factory = sqlite3.Row
        try:
            self._configure()
            self._connection.executescript(_CREATE_SCHEMA)
        except BaseException:
            self._connection.close()
            raise

    def __enter__(self) -> "LocalIndex":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def _configure(self) -> None:
        journal_mode = self._connection.execute(
            "PRAGMA journal_mode=DELETE"
        ).fetchone()[0]
        if str(journal_mode).lower() != "delete":
            raise LocalIndexError(f"rollback journal unavailable: {journal_mode}")
        self._connection.execute("PRAGMA synchronous=EXTRA")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA trusted_schema=OFF")
        self._connection.execute(f"PRAGMA busy_timeout={self.BUSY_TIMEOUT_MS}")
        expected = {
            "synchronous": 3,
            "foreign_keys": 1,
            "trusted_schema": 0,
            "busy_timeout": self.BUSY_TIMEOUT_MS,
        }
        for pragma, wanted in expected.items():
            actual = self._connection.execute(f"PRAGMA {pragma}").fetchone()[0]
            if actual != wanted:
                raise LocalIndexError(
                    f"SQLite pragma {pragma} is {actual!r}, expected {wanted!r}"
                )

    def settings(self) -> dict[str, int | str]:
        """Return the connection settings relevant to durability and safety."""

        return {
            "journal_mode": self._connection.execute(
                "PRAGMA journal_mode"
            ).fetchone()[0],
            "synchronous": self._connection.execute(
                "PRAGMA synchronous"
            ).fetchone()[0],
            "foreign_keys": self._connection.execute(
                "PRAGMA foreign_keys"
            ).fetchone()[0],
            "trusted_schema": self._connection.execute(
                "PRAGMA trusted_schema"
            ).fetchone()[0],
            "busy_timeout": self._connection.execute(
                "PRAGMA busy_timeout"
            ).fetchone()[0],
        }

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        if self._connection.in_transaction:
            raise LocalIndexError("nested LocalIndex write transaction")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        else:
            try:
                self._connection.execute("COMMIT")
            except BaseException:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def put(self, value: IndexRecord | Mapping[str, Any]) -> bool:
        """Insert one immutable record.

        Returns ``True`` for a new row and ``False`` for an identical cache hit.
        Reusing a key or event position with different content raises
        :class:`RecordCollisionError`.
        """

        prepared = _prepare(value)
        with self._write_transaction():
            return self._insert_prepared(prepared)

    def put_many(
        self, values: Iterable[IndexRecord | Mapping[str, Any]]
    ) -> tuple[bool, ...]:
        """Project one journal event and its records in one transaction."""

        prepared = tuple(_prepare(value) for value in values)
        inserted: list[bool] = []
        with self._write_transaction():
            for value in prepared:
                inserted.append(self._insert_prepared(value))
        return tuple(inserted)

    def put_record(
        self,
        *,
        kind: str,
        record_id: str,
        subject: str,
        status: str,
        fingerprint: str,
        payload: Mapping[str, Any] | None = None,
        event_stream: str | None = None,
        event_sequence: int | None = None,
    ) -> bool:
        """Keyword-oriented convenience wrapper around :meth:`put`."""

        return self.put(
            IndexRecord(
                kind=kind,
                record_id=record_id,
                subject=subject,
                status=status,
                fingerprint=fingerprint,
                payload={} if payload is None else payload,
                event_stream=event_stream,
                event_sequence=event_sequence,
            )
        )

    def _insert_prepared(self, prepared: _PreparedRecord) -> bool:
        record = prepared.record
        _, projection_was_valid = self.projection_guard()
        existing = self._connection.execute(
            _HOT_QUERIES["record_by_key"].sql,
            (record.kind, record.record_id),
        ).fetchone()
        if existing is not None:
            if self._row_identity(existing) == self._prepared_identity(prepared):
                return False
            raise RecordCollisionError(
                f"immutable record collision: ({record.kind!r}, {record.record_id!r})"
            )
        parameters = (
            record.kind,
            record.record_id,
            record.subject,
            record.status,
            record.fingerprint,
            prepared.payload_json,
            record.event_stream,
            record.event_sequence,
            record.authority_sequence,
            record.authority_event_id,
            record.authority_offset,
            prepared.record_digest,
        )
        try:
            self._connection.execute(_INSERT_RECORD, parameters)
            if record.kind != "journal-event":
                guard = self._connection.execute(
                    "SELECT projection_digest FROM projection_stats WHERE singleton = 1"
                ).fetchone()
                if guard is None:
                    raise IndexIntegrityError("projection guard is absent")
                self._connection.execute(
                    "UPDATE projection_stats SET projection_digest = ? WHERE singleton = 1",
                    (
                        _advance_projection_digest(
                            guard["projection_digest"],
                            prepared.projection_member_digest,
                        ),
                    ),
                )
            if record.event_stream is not None:
                self._connection.execute(
                    _UPSERT_EVENT_HEAD,
                    (
                        record.event_stream,
                        record.event_sequence,
                        record.kind,
                        record.record_id,
                        record.fingerprint,
                    ),
                )
                # The event-head triggers make every out-of-band mutation
                # fail closed.  Only this transaction, which began from a
                # valid projection and just derived the head from the inserted
                # immutable record, may restore the guard.
                if projection_was_valid:
                    self._connection.execute(
                        "UPDATE projection_stats SET projection_valid = 1 "
                        "WHERE singleton = 1"
                    )
        except sqlite3.IntegrityError as exc:
            raise RecordCollisionError(
                "immutable event position or record constraint collision"
            ) from exc
        return True

    @staticmethod
    def _row_identity(row: sqlite3.Row) -> tuple[Any, ...]:
        return tuple(row[column] for column in _RECORD_COLUMN_NAMES)

    @staticmethod
    def _prepared_identity(prepared: _PreparedRecord) -> tuple[Any, ...]:
        record = prepared.record
        return (
            record.kind,
            record.record_id,
            record.subject,
            record.status,
            record.fingerprint,
            prepared.payload_json,
            record.event_stream,
            record.event_sequence,
            record.authority_sequence,
            record.authority_event_id,
            record.authority_offset,
            prepared.record_digest,
        )

    def _decode_record(self, row: sqlite3.Row) -> IndexRecord:
        record = IndexRecord(
            kind=row["kind"],
            record_id=row["record_id"],
            subject=row["subject"],
            status=row["status"],
            fingerprint=row["fingerprint"],
            payload=parse_canonical(row["payload_json"]),
            event_stream=row["event_stream"],
            event_sequence=row["event_sequence"],
            authority_sequence=row["authority_sequence"],
            authority_event_id=row["authority_event_id"],
            authority_offset=row["authority_offset"],
        )
        if _record_digest(record, row["payload_json"]) != row["record_digest"]:
            raise IndexIntegrityError(
                f"journal projection record digest mismatch: "
                f"({record.kind!r}, {record.record_id!r})"
            )
        if self._authority_validator is not None:
            self._authority_validator(record)
        return record

    def get(self, kind: str, record_id: str) -> IndexRecord | None:
        row = self._connection.execute(
            _HOT_QUERIES["record_by_key"].sql,
            (_require_text("kind", kind), _require_text("record_id", record_id)),
        ).fetchone()
        return None if row is None else self._decode_record(row)

    def records_by_subject_status(
        self, subject: str, status: str
    ) -> tuple[IndexRecord, ...]:
        rows = self._connection.execute(
            _HOT_QUERIES["records_by_subject_status"].sql,
            (_require_text("subject", subject), _require_text("status", status)),
        ).fetchall()
        return tuple(self._decode_record(row) for row in rows)

    def records_by_fingerprint(self, fingerprint: str) -> tuple[IndexRecord, ...]:
        rows = self._connection.execute(
            _HOT_QUERIES["records_by_fingerprint"].sql,
            (_require_text("fingerprint", fingerprint),),
        ).fetchall()
        return tuple(self._decode_record(row) for row in rows)

    def records_by_kind(self, kind: str) -> tuple[IndexRecord, ...]:
        """Return one typed history slice for terminal or maintenance audits."""

        rows = self._connection.execute(
            _HOT_QUERIES["records_by_kind"].sql,
            (_require_text("kind", kind),),
        ).fetchall()
        return tuple(self._decode_record(row) for row in rows)

    def event_head(self, stream: str) -> EventHead | None:
        row = self._connection.execute(
            _HOT_QUERIES["event_head_by_stream"].sql,
            (_require_text("stream", stream),),
        ).fetchone()
        if row is None:
            return None
        head = EventHead(
            stream=row["stream"],
            sequence=row["sequence"],
            record_kind=row["record_kind"],
            record_id=row["record_id"],
            fingerprint=row["fingerprint"],
        )
        record = self.get(head.record_kind, head.record_id)
        latest = self._connection.execute(
            _HOT_QUERIES["latest_event_record_by_stream"].sql,
            (stream,),
        ).fetchone()
        if (
            record is None
            or record.event_stream != head.stream
            or record.event_sequence != head.sequence
            or record.fingerprint != head.fingerprint
            or latest is None
            or latest["kind"] != head.record_kind
            or latest["record_id"] != head.record_id
            or latest["event_sequence"] != head.sequence
        ):
            raise IndexIntegrityError(f"event head is not bound to its record: {stream!r}")
        self._decode_record(latest)
        return head

    def event_record(self, stream: str, sequence: int) -> IndexRecord | None:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("event sequence must be a non-negative integer")
        row = self._connection.execute(
            _HOT_QUERIES["event_record_by_position"].sql,
            (_require_text("stream", stream), sequence),
        ).fetchone()
        return None if row is None else self._decode_record(row)

    def record_count(self) -> int:
        return self._connection.execute(
            _HOT_QUERIES["projection_record_count"].sql,
            (1,),
        ).fetchone()[0]

    def projection_guard(self) -> tuple[str, bool]:
        row = self._connection.execute(
            "SELECT projection_digest, projection_valid "
            "FROM projection_stats WHERE singleton = 1"
        ).fetchone()
        if (
            row is None
            or type(row["projection_digest"]) is not str
            or len(row["projection_digest"]) != 64
            or row["projection_valid"] not in {0, 1}
        ):
            raise IndexIntegrityError("projection digest guard is invalid")
        return row["projection_digest"], bool(row["projection_valid"])

    def projected_digest(
        self, records: Iterable[IndexRecord | Mapping[str, Any]]
    ) -> str:
        """Return the bounded digest expected after appending these records."""

        digest, valid = self.projection_guard()
        if not valid:
            raise IndexIntegrityError("projection was invalidated by mutation")
        for prepared in (_prepare(record) for record in records):
            if prepared.record.kind != "journal-event":
                digest = _advance_projection_digest(
                    digest, prepared.projection_member_digest
                )
        return digest

    def rebuild(
        self, records: Iterable[IndexRecord | Mapping[str, Any]]
    ) -> int:
        """Atomically rebuild the projection from durable event records.

        The iterable is fully prepared before the old projection is touched.
        Any collision rolls back the complete rebuild.
        """

        prepared = tuple(_prepare(record) for record in records)
        inserted = 0
        with self._write_transaction():
            self._connection.execute("DELETE FROM event_heads")
            self._connection.execute("DELETE FROM records")
            self._connection.execute(
                "UPDATE projection_stats SET record_count = 0, "
                "projection_digest = ?, projection_valid = 1 WHERE singleton = 1",
                (_EMPTY_PROJECTION_DIGEST,),
            )
            for record in prepared:
                inserted += int(self._insert_prepared(record))
        return inserted

    def exactly_matches(
        self, records: Iterable[IndexRecord | Mapping[str, Any]]
    ) -> bool:
        """Full maintenance audit against the Journal-derived record set."""

        prepared = tuple(_prepare(record) for record in records)
        expected: dict[tuple[str, str], tuple[Any, ...]] = {}
        for item in prepared:
            key = (item.record.kind, item.record.record_id)
            identity = self._prepared_identity(item)
            if key in expected and expected[key] != identity:
                return False
            expected[key] = identity
        rows = self._connection.execute(
            f"SELECT {_SELECT_RECORD_COLUMNS} FROM records"
        ).fetchall()
        if len(rows) != len(expected):
            return False
        for row in rows:
            self._decode_record(row)
            key = (row["kind"], row["record_id"])
            if expected.get(key) != self._row_identity(row):
                return False
        return True

    def integrity_report(self) -> dict[str, tuple[Any, ...]]:
        integrity = tuple(
            row[0] for row in self._connection.execute("PRAGMA integrity_check")
        )
        foreign_keys = tuple(
            tuple(row) for row in self._connection.execute("PRAGMA foreign_key_check")
        )
        return {"integrity_check": integrity, "foreign_key_check": foreign_keys}

    def check_integrity(self) -> None:
        report = self.integrity_report()
        if report["integrity_check"] != ("ok",) or report["foreign_key_check"]:
            raise IndexIntegrityError(f"local index integrity failure: {report!r}")
        observed = self._connection.execute("SELECT count(*) FROM records").fetchone()[0]
        if observed != self.record_count():
            raise IndexIntegrityError("local projection record-count guard mismatch")
        projection_digest, projection_valid = self.projection_guard()
        if not projection_valid:
            raise IndexIntegrityError("local projection was invalidated by mutation")
        rows = self._connection.execute(
            f"SELECT {_SELECT_RECORD_COLUMNS} FROM records"
        ).fetchall()
        for row in rows:
            self._decode_record(row)
        head_streams = tuple(
            row[0]
            for row in self._connection.execute(
                "SELECT stream FROM event_heads ORDER BY stream"
            )
        )
        record_streams = tuple(
            row[0]
            for row in self._connection.execute(
                "SELECT DISTINCT event_stream FROM records "
                "WHERE event_stream IS NOT NULL ORDER BY event_stream"
            )
        )
        if head_streams != record_streams:
            raise IndexIntegrityError("event-head stream set differs from event records")
        for stream in head_streams:
            self.event_head(stream)

    @staticmethod
    def hot_query_names() -> tuple[str, ...]:
        return _CURRENT_QUERY_NAMES

    @staticmethod
    def current_lookup_row_bounds() -> dict[str, int]:
        return {name: 1 for name in _CURRENT_QUERY_NAMES}

    def trace_current_lookup(
        self,
        name: str,
        parameters: tuple[Any, ...],
        *,
        manifest_paths: tuple[str, ...] = (),
    ) -> CurrentAccessTrace:
        """Trace one current-key lookup and prove its bounded access contract.

        SQLite's indexed SEARCH shape and the named UNIQUE/PRIMARY KEY are the
        visited-row bound; fetching at most two rows mechanically rejects a
        violated uniqueness assumption.  Manifest paths are explicit inputs,
        so a validator cannot substitute a repository-root walk.
        """

        if name not in _CURRENT_QUERY_NAMES:
            raise QueryPlanError(f"query is not a current-work lookup: {name!r}")
        normalized_paths: list[str] = []
        for value in manifest_paths:
            path = Path(value)
            if (
                type(value) is not str
                or not value
                or path.is_absolute()
                or ".." in path.parts
                or value in {".", "./"}
            ):
                raise QueryPlanError("manifest trace paths must be explicit repository paths")
            normalized_paths.append(path.as_posix())
        if len(set(normalized_paths)) != len(normalized_paths):
            raise QueryPlanError("manifest trace paths must be unique")
        query = _HOT_QUERIES[name]
        rows = self._connection.execute(query.sql, parameters).fetchmany(2)
        if len(rows) > 1:
            raise QueryPlanError(f"current lookup {name!r} returned more than one row")
        basis = {
            "record_by_key": "records.PRIMARY_KEY(kind,record_id)",
            "event_head_by_stream": "event_heads.PRIMARY_KEY(stream)",
            "latest_event_record_by_stream": (
                "records.UNIQUE(event_stream,event_sequence) ordered seek"
            ),
            "event_record_by_position": (
                "records.UNIQUE(event_stream,event_sequence)"
            ),
            "projection_record_count": "projection_stats.PRIMARY_KEY(singleton)",
        }[name]
        return CurrentAccessTrace(
            query_name=name,
            access_shape=self.hot_query_access_shape(name, parameters),
            uniqueness_basis=basis,
            visited_row_upper_bound=1,
            returned_row_count=len(rows),
            manifest_paths=tuple(normalized_paths),
        )

    def explain_hot_query(
        self, name: str, parameters: tuple[Any, ...]
    ) -> tuple[str, ...]:
        try:
            query = _HOT_QUERIES[name]
        except KeyError as exc:
            raise KeyError(f"unknown hot query: {name}") from exc
        rows = self._connection.execute(
            f"EXPLAIN QUERY PLAN {query.sql}", parameters
        ).fetchall()
        return tuple(str(row[3]) for row in rows)

    def hot_query_access_shape(
        self, name: str, parameters: tuple[Any, ...]
    ) -> tuple[str, ...]:
        """Return a release-tolerant SEARCH/SCAN shape for a named lookup."""

        try:
            query = _HOT_QUERIES[name]
            target = query.target_table
        except KeyError as exc:
            raise KeyError(f"unknown hot query: {name}") from exc
        shape: list[str] = []
        for detail in self.explain_hot_query(name, parameters):
            words = detail.split()
            operation = words[0].upper() if words else "UNKNOWN"
            table = words[1] if len(words) > 1 else ""
            shape.append(f"{operation}:{table}")
            if operation == "SCAN" and table == target:
                raise QueryPlanError(
                    f"hot query {name!r} scans target table {target!r}: {detail}"
                )
        if not any(item == f"SEARCH:{target}" for item in shape):
            raise QueryPlanError(
                f"hot query {name!r} has no indexed SEARCH on {target!r}: {shape!r}"
            )
        if name in _CURRENT_QUERY_NAMES and not any(
            query.plan_marker in detail
            and all(f"{column}=?" in detail for column in query.key_columns)
            for detail in self.explain_hot_query(name, parameters)
        ):
            raise QueryPlanError(
                f"current lookup {name!r} does not use its complete keyed plan"
            )
        return tuple(shape)

    def check_hot_queries(self) -> dict[str, tuple[str, ...]]:
        representative = {
            "record_by_key": ("kind", "record"),
            "event_head_by_stream": ("stream",),
            "latest_event_record_by_stream": ("stream",),
            "event_record_by_position": ("stream", 1),
            "projection_record_count": (1,),
        }
        return {
            name: self.hot_query_access_shape(name, representative[name])
            for name in self.hot_query_names()
        }
