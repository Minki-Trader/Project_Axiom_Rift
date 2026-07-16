"""Reconstructible, keyed SQLite projection for durable Axiom records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import stat
from typing import Any, Callable, Iterator

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.component_surface import (
    COMPONENT_SURFACE_ARCHITECTURE_ROLE,
    COMPONENT_SURFACE_DOMAIN_AWARE,
    COMPONENT_SURFACE_KINDS,
    COMPONENT_SURFACE_PROTOCOL_NEUTRAL,
    ComponentManifestError,
    ComponentSurfaceIdentities,
    component_manifest_surfaces,
)
from axiom_rift.core.identity import canonical_digest
from axiom_rift.storage.path_boundary import (
    PathBoundaryError,
    ensure_link_free_directory_chain,
    require_link_free_directory_chain,
)


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
_INDEX_SCHEMA_VERSION = 3

_RECORDS_BY_KIND_PREFIX_SQL = (
    f"SELECT {_SELECT_RECORD_COLUMNS} FROM records "
    "WHERE kind = ? AND record_id >= ? AND record_id < ? "
    "ORDER BY record_id"
)

_COUNT_BY_KIND_BEFORE_AUTHORITY_SEQUENCE_SQL = (
    "SELECT count(*) AS record_count FROM records "
    "WHERE kind = ? AND authority_sequence < ?"
)

_RECORDS_BY_KIND_AT_AUTHORITY_SEQUENCE_SQL = (
    f"SELECT {_SELECT_RECORD_COLUMNS} FROM records "
    "INDEXED BY ix_records_kind_authority_sequence "
    "WHERE kind = ? AND authority_sequence = ? ORDER BY record_id"
)


@dataclass(frozen=True, slots=True)
class _PayloadTextLookup:
    path: tuple[str, ...]
    json_path: str
    index_name: str


_PAYLOAD_TEXT_LOOKUPS: dict[str, _PayloadTextLookup] = {
    "batch_id": _PayloadTextLookup(
        path=("batch_id",),
        json_path="$.batch_id",
        index_name="ix_records_kind_payload_batch_id",
    ),
    "completion_record_id": _PayloadTextLookup(
        path=("completion_record_id",),
        json_path="$.completion_record_id",
        index_name="ix_records_kind_payload_completion_record_id",
    ),
    "lineage_mission_id": _PayloadTextLookup(
        path=("lineage", "mission_id"),
        json_path="$.lineage.mission_id",
        index_name="ix_records_kind_payload_lineage_mission_id",
    ),
    "lineage_original_axis_identity": _PayloadTextLookup(
        path=("lineage", "original_axis_identity"),
        json_path="$.lineage.original_axis_identity",
        index_name="ix_records_kind_payload_lineage_original_axis_identity",
    ),
    "mission_id": _PayloadTextLookup(
        path=("mission_id",),
        json_path="$.mission_id",
        index_name="ix_records_kind_payload_mission_id",
    ),
    "obligation_governing_mission_id": _PayloadTextLookup(
        path=("obligation", "governing_mission_id"),
        json_path="$.obligation.governing_mission_id",
        index_name="ix_records_kind_payload_obligation_governing_mission_id",
    ),
    "obligation_original_executable_id": _PayloadTextLookup(
        path=("obligation", "original_executable_id"),
        json_path="$.obligation.original_executable_id",
        index_name="ix_records_kind_payload_obligation_original_executable_id",
    ),
    "portfolio_axis_identity": _PayloadTextLookup(
        path=("portfolio_axis_identity",),
        json_path="$.portfolio_axis_identity",
        index_name="ix_records_kind_payload_portfolio_axis_identity",
    ),
    "study_kpi_executable_display_id": _PayloadTextLookup(
        path=("executable_display_id",),
        json_path="$.executable_display_id",
        index_name="ix_records_kind_payload_executable_display_id",
    ),
    "study_kpi_executable_id": _PayloadTextLookup(
        path=("executable_id",),
        json_path="$.executable_id",
        index_name="ix_records_kind_payload_executable_id",
    ),
    "study_open_baseline_data_contract": _PayloadTextLookup(
        path=(
            "controlled_chassis",
            "baseline_executable",
            "data_contract",
        ),
        json_path="$.controlled_chassis.baseline_executable.data_contract",
        index_name="ix_records_kind_payload_study_baseline_data_contract",
    ),
    "scientific_executable_id": _PayloadTextLookup(
        path=("scientific", "executable_id"),
        json_path="$.scientific.executable_id",
        index_name="ix_records_kind_payload_scientific_executable_id",
    ),
    "target_axis_identity": _PayloadTextLookup(
        path=("target_axis_identity",),
        json_path="$.target_axis_identity",
        index_name="ix_records_kind_payload_target_axis_identity",
    ),
    "trial_data_contract": _PayloadTextLookup(
        path=("executable", "data_contract"),
        json_path="$.executable.data_contract",
        index_name="ix_records_kind_payload_trial_data_contract",
    ),
}


def _payload_text_lookup_sql(lookup: _PayloadTextLookup) -> str:
    return (
        f"SELECT {_SELECT_RECORD_COLUMNS} FROM records "
        f"INDEXED BY {lookup.index_name} "
        f"WHERE kind = ? "
        f"AND json_type(payload_json, '{lookup.json_path}') = 'text' "
        f"AND json_extract(payload_json, '{lookup.json_path}') = ? "
        "ORDER BY record_id"
    )


def _payload_text_values_lookup_sql(
    lookup: _PayloadTextLookup,
    value_count: int,
) -> str:
    if type(value_count) is not int or value_count < 1:
        raise ValueError("payload lookup value count must be positive")
    placeholders = ", ".join("?" for _ in range(value_count))
    return (
        f"SELECT {_SELECT_RECORD_COLUMNS} FROM records "
        f"INDEXED BY {lookup.index_name} "
        f"WHERE kind = ? "
        f"AND json_type(payload_json, '{lookup.json_path}') = 'text' "
        f"AND json_extract(payload_json, '{lookup.json_path}') "
        f"IN ({placeholders}) ORDER BY record_id"
    )

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
    "record_count_by_kind": _HotQuery(
        "SELECT record_count FROM record_kind_stats WHERE kind = ?",
        "record_kind_stats",
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

_EMPTY_COMPONENT_SURFACE_DIGEST = canonical_digest(
    domain="component-surface-binding-set",
    payload={
        "bindings": [],
        "schema": "component_surface_binding_set.v1",
    },
)

_CONTROLLED_CHASSIS_STUDY_GUARD_SQL = (
    "SELECT study_count, presence_valid "
    "FROM controlled_chassis_study_stats WHERE singleton = ?"
)

_CURRENT_QUERY_NAMES = (
    "record_by_key",
    "event_head_by_stream",
    "latest_event_record_by_stream",
    "event_record_by_position",
    "projection_record_count",
    "record_count_by_kind",
)


_CREATE_SCHEMA = f"""
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

CREATE INDEX IF NOT EXISTS ix_records_kind_authority_sequence
ON records(kind, authority_sequence)
WHERE authority_sequence IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_records_kind_payload_batch_id
ON records(kind, json_extract(payload_json, '$.batch_id'), record_id)
WHERE json_type(payload_json, '$.batch_id') = 'text';

CREATE INDEX IF NOT EXISTS ix_records_kind_payload_completion_record_id
ON records(kind, json_extract(payload_json, '$.completion_record_id'), record_id)
WHERE json_type(payload_json, '$.completion_record_id') = 'text';

CREATE INDEX IF NOT EXISTS ix_records_kind_payload_lineage_mission_id
ON records(kind, json_extract(payload_json, '$.lineage.mission_id'), record_id)
WHERE json_type(payload_json, '$.lineage.mission_id') = 'text';

CREATE INDEX IF NOT EXISTS ix_records_kind_payload_lineage_original_axis_identity
ON records(
    kind,
    json_extract(payload_json, '$.lineage.original_axis_identity'),
    record_id
)
WHERE json_type(payload_json, '$.lineage.original_axis_identity') = 'text';

CREATE INDEX IF NOT EXISTS ix_records_kind_payload_mission_id
ON records(kind, json_extract(payload_json, '$.mission_id'), record_id)
WHERE json_type(payload_json, '$.mission_id') = 'text';

CREATE INDEX IF NOT EXISTS ix_records_kind_payload_obligation_governing_mission_id
ON records(
    kind,
    json_extract(payload_json, '$.obligation.governing_mission_id'),
    record_id
)
WHERE json_type(payload_json, '$.obligation.governing_mission_id') = 'text';

CREATE INDEX IF NOT EXISTS ix_records_kind_payload_obligation_original_executable_id
ON records(
    kind,
    json_extract(payload_json, '$.obligation.original_executable_id'),
    record_id
)
WHERE json_type(payload_json, '$.obligation.original_executable_id') = 'text';

CREATE INDEX IF NOT EXISTS ix_records_kind_payload_portfolio_axis_identity
ON records(kind, json_extract(payload_json, '$.portfolio_axis_identity'), record_id)
WHERE json_type(payload_json, '$.portfolio_axis_identity') = 'text';

CREATE INDEX IF NOT EXISTS ix_records_kind_payload_executable_display_id
ON records(kind, json_extract(payload_json, '$.executable_display_id'), record_id)
WHERE json_type(payload_json, '$.executable_display_id') = 'text';

CREATE INDEX IF NOT EXISTS ix_records_kind_payload_executable_id
ON records(kind, json_extract(payload_json, '$.executable_id'), record_id)
WHERE json_type(payload_json, '$.executable_id') = 'text';

CREATE INDEX IF NOT EXISTS ix_records_kind_payload_scientific_executable_id
ON records(kind, json_extract(payload_json, '$.scientific.executable_id'), record_id)
WHERE json_type(payload_json, '$.scientific.executable_id') = 'text';

CREATE INDEX IF NOT EXISTS ix_records_kind_payload_target_axis_identity
ON records(kind, json_extract(payload_json, '$.target_axis_identity'), record_id)
WHERE json_type(payload_json, '$.target_axis_identity') = 'text';

CREATE INDEX IF NOT EXISTS ix_records_kind_payload_study_baseline_data_contract
ON records(
    kind,
    json_extract(
        payload_json,
        '$.controlled_chassis.baseline_executable.data_contract'
    ),
    record_id
)
WHERE json_type(
    payload_json,
    '$.controlled_chassis.baseline_executable.data_contract'
) = 'text';

CREATE INDEX IF NOT EXISTS ix_records_kind_payload_trial_data_contract
ON records(kind, json_extract(payload_json, '$.executable.data_contract'), record_id)
WHERE json_type(payload_json, '$.executable.data_contract') = 'text';

CREATE TABLE IF NOT EXISTS component_surface_bindings (
    surface_kind     TEXT NOT NULL,
    surface_identity TEXT NOT NULL,
    component_id     TEXT NOT NULL,
    PRIMARY KEY (surface_kind, surface_identity, component_id),
    UNIQUE (surface_kind, component_id),
    CHECK (
        surface_kind IN (
            'architecture_role',
            'domain_aware',
            'protocol_neutral'
        )
    ),
    CHECK (length(surface_identity) > 0),
    CHECK (length(component_id) = 74),
    CHECK (substr(component_id, 1, 10) = 'component:')
) STRICT, WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_component_surface_bindings_component
ON component_surface_bindings(component_id, surface_kind, surface_identity);

CREATE TABLE IF NOT EXISTS component_surface_stats (
    singleton        INTEGER NOT NULL PRIMARY KEY CHECK (singleton = 1),
    component_count  INTEGER NOT NULL CHECK (component_count >= 0),
    binding_count    INTEGER NOT NULL CHECK (binding_count >= 0),
    binding_digest   TEXT NOT NULL CHECK (length(binding_digest) = 64),
    binding_valid    INTEGER NOT NULL CHECK (binding_valid IN (0, 1))
) STRICT, WITHOUT ROWID;

INSERT OR IGNORE INTO component_surface_stats(
    singleton, component_count, binding_count, binding_digest, binding_valid
)
VALUES (1, 0, 0, '{_EMPTY_COMPONENT_SURFACE_DIGEST}', 1);

CREATE TABLE IF NOT EXISTS record_kind_stats (
    kind         TEXT NOT NULL PRIMARY KEY,
    record_count INTEGER NOT NULL CHECK (record_count > 0)
) STRICT, WITHOUT ROWID;

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

CREATE TABLE IF NOT EXISTS controlled_chassis_study_stats (
    singleton      INTEGER NOT NULL PRIMARY KEY CHECK (singleton = 1),
    study_count    INTEGER NOT NULL CHECK (study_count >= 0),
    presence_valid INTEGER NOT NULL CHECK (presence_valid IN (0, 1))
) STRICT, WITHOUT ROWID;

INSERT OR IGNORE INTO controlled_chassis_study_stats(
    singleton, study_count, presence_valid
)
VALUES (1, 0, 0);

CREATE TRIGGER IF NOT EXISTS records_projection_count_insert
AFTER INSERT ON records
BEGIN
    UPDATE projection_stats SET record_count = record_count + 1 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS records_kind_count_insert
AFTER INSERT ON records
BEGIN
    INSERT INTO record_kind_stats(kind, record_count) VALUES (NEW.kind, 1)
    ON CONFLICT(kind) DO UPDATE SET record_count = record_count + 1;
END;

CREATE TRIGGER IF NOT EXISTS records_projection_count_delete
AFTER DELETE ON records
BEGIN
    UPDATE projection_stats
    SET record_count = record_count - 1, projection_valid = 0
    WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS records_controlled_chassis_study_insert
AFTER INSERT ON records
WHEN NEW.kind = 'study-open'
 AND json_type(NEW.payload_json, '$.controlled_chassis') = 'object'
BEGIN
    UPDATE controlled_chassis_study_stats
    SET study_count = study_count + 1
    WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS records_controlled_chassis_study_delete
AFTER DELETE ON records
WHEN OLD.kind = 'study-open'
 AND json_type(OLD.payload_json, '$.controlled_chassis') = 'object'
BEGIN
    UPDATE controlled_chassis_study_stats
    SET study_count = study_count - 1
    WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS records_controlled_chassis_study_update
AFTER UPDATE ON records
WHEN (
    OLD.kind = 'study-open'
    AND json_type(OLD.payload_json, '$.controlled_chassis') = 'object'
) OR (
    NEW.kind = 'study-open'
    AND json_type(NEW.payload_json, '$.controlled_chassis') = 'object'
)
BEGIN
    UPDATE controlled_chassis_study_stats
    SET study_count = study_count
        - CASE
            WHEN OLD.kind = 'study-open'
             AND json_type(OLD.payload_json, '$.controlled_chassis') = 'object'
            THEN 1 ELSE 0
          END
        + CASE
            WHEN NEW.kind = 'study-open'
             AND json_type(NEW.payload_json, '$.controlled_chassis') = 'object'
            THEN 1 ELSE 0
          END
    WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS records_kind_count_delete
AFTER DELETE ON records
BEGIN
    DELETE FROM record_kind_stats
    WHERE kind = OLD.kind AND record_count = 1;
    UPDATE record_kind_stats
    SET record_count = record_count - 1
    WHERE kind = OLD.kind;
END;

CREATE TRIGGER IF NOT EXISTS records_kind_count_update
AFTER UPDATE OF kind ON records
WHEN OLD.kind != NEW.kind
BEGIN
    DELETE FROM record_kind_stats
    WHERE kind = OLD.kind AND record_count = 1;
    UPDATE record_kind_stats
    SET record_count = record_count - 1
    WHERE kind = OLD.kind;
    INSERT INTO record_kind_stats(kind, record_count) VALUES (NEW.kind, 1)
    ON CONFLICT(kind) DO UPDATE SET record_count = record_count + 1;
END;

CREATE TRIGGER IF NOT EXISTS records_projection_update_invalid
AFTER UPDATE ON records
BEGIN
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS record_kind_stats_insert_invalid
AFTER INSERT ON record_kind_stats
BEGIN
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS record_kind_stats_update_invalid
AFTER UPDATE ON record_kind_stats
BEGIN
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS record_kind_stats_delete_invalid
AFTER DELETE ON record_kind_stats
BEGIN
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS controlled_chassis_study_stats_insert_invalid
AFTER INSERT ON controlled_chassis_study_stats
BEGIN
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS controlled_chassis_study_stats_update_invalid
AFTER UPDATE ON controlled_chassis_study_stats
BEGIN
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS controlled_chassis_study_stats_delete_invalid
AFTER DELETE ON controlled_chassis_study_stats
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

CREATE TRIGGER IF NOT EXISTS component_surface_bindings_insert_invalid
AFTER INSERT ON component_surface_bindings
BEGIN
    UPDATE component_surface_stats SET binding_valid = 0 WHERE singleton = 1;
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS component_surface_bindings_update_invalid
AFTER UPDATE ON component_surface_bindings
BEGIN
    UPDATE component_surface_stats SET binding_valid = 0 WHERE singleton = 1;
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS component_surface_bindings_delete_invalid
AFTER DELETE ON component_surface_bindings
BEGIN
    UPDATE component_surface_stats SET binding_valid = 0 WHERE singleton = 1;
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS component_surface_stats_insert_invalid
AFTER INSERT ON component_surface_stats
BEGIN
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS component_surface_stats_update_invalid
AFTER UPDATE ON component_surface_stats
BEGIN
    UPDATE projection_stats SET projection_valid = 0 WHERE singleton = 1;
END;

CREATE TRIGGER IF NOT EXISTS component_surface_stats_delete_invalid
AFTER DELETE ON component_surface_stats
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


def _ascii_prefix_bounds(name: str, value: Any) -> tuple[str, str]:
    prefix = _require_text(name, value)
    if not prefix.isascii() or any(
        ord(character) < 0x20 or ord(character) > 0x7E
        for character in prefix
    ):
        raise ValueError(f"{name} must contain printable ASCII only")
    characters = list(prefix)
    for index in range(len(characters) - 1, -1, -1):
        if ord(characters[index]) < 0x7E:
            characters[index] = chr(ord(characters[index]) + 1)
            return prefix, "".join(characters[: index + 1])
    raise ValueError(f"{name} has no finite printable-ASCII upper bound")


def _payload_text_value(
    payload: Mapping[str, Any],
    lookup: _PayloadTextLookup,
) -> object:
    value: object = payload
    for part in lookup.path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _payload_lookup_values(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("payload lookup values must be an iterable of strings")
    try:
        normalized = tuple(
            sorted(
                {
                    _require_text("payload lookup value", value)
                    for value in values
                }
            )
        )
    except TypeError as exc:
        raise TypeError(
            "payload lookup values must be an iterable of strings"
        ) from exc
    if len(normalized) > 900:
        raise ValueError("payload lookup value count exceeds the bounded union")
    return normalized


_COMPONENT_SURFACE_PREFIXES = {
    COMPONENT_SURFACE_ARCHITECTURE_ROLE: "architecture-component-surface:",
    COMPONENT_SURFACE_DOMAIN_AWARE: "component-surface:",
    COMPONENT_SURFACE_PROTOCOL_NEUTRAL: "component-protocol-neutral:",
}
_QUALIFIED_RECORD_COLUMNS = ", ".join(
    f"record.{name} AS {name}" for name in _RECORD_COLUMN_NAMES
)


def _component_surface_kind(value: str) -> str:
    kind = _require_text("component surface kind", value)
    if kind not in COMPONENT_SURFACE_KINDS:
        raise ValueError("component surface kind is not supported")
    return kind


def _component_surface_identity(surface_kind: str, value: str) -> str:
    identity = _require_text("component surface identity", value)
    prefix = _COMPONENT_SURFACE_PREFIXES[_component_surface_kind(surface_kind)]
    digest = identity.removeprefix(prefix)
    if (
        not identity.startswith(prefix)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("component surface identity has the wrong namespace")
    return identity


def _component_surface_values(
    surface_kind: str,
    values: Iterable[str],
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("component surfaces must be an iterable of strings")
    kind = _component_surface_kind(surface_kind)
    try:
        normalized = tuple(
            sorted({_component_surface_identity(kind, value) for value in values})
        )
    except TypeError as exc:
        raise TypeError(
            "component surfaces must be an iterable of strings"
        ) from exc
    if len(normalized) > 900:
        raise ValueError("component surface count exceeds the bounded union")
    return normalized


def _component_surface_lookup_sql(value_count: int) -> str:
    if type(value_count) is not int or value_count < 1:
        raise ValueError("component surface value count must be positive")
    placeholders = ", ".join("?" for _ in range(value_count))
    return (
        "SELECT binding.surface_identity AS binding_surface_identity, "
        f"{_QUALIFIED_RECORD_COLUMNS} "
        "FROM component_surface_bindings AS binding "
        "JOIN records AS record "
        "ON record.kind = 'component-manifest' "
        "AND record.record_id = binding.component_id "
        "WHERE binding.surface_kind = ? "
        f"AND binding.surface_identity IN ({placeholders}) "
        "ORDER BY binding.surface_identity, binding.component_id"
    )


def _component_surface_binding_digest(
    bindings: Iterable[tuple[str, str, str]],
) -> str:
    payload = [
        {
            "component_id": component_id,
            "surface_identity": surface_identity,
            "surface_kind": surface_kind,
        }
        for surface_kind, surface_identity, component_id in sorted(bindings)
    ]
    return canonical_digest(
        domain="component-surface-binding-set",
        payload={
            "bindings": payload,
            "schema": "component_surface_binding_set.v1",
        },
    )


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
        if type(record.event_sequence) is not int:
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
            type(record.authority_sequence) is not int
            or record.authority_sequence < 1
            or type(record.authority_event_id) is not str
            or len(record.authority_event_id) != 64
            or any(
                character not in "0123456789abcdef"
                for character in record.authority_event_id
            )
            or type(record.authority_offset) is not int
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

    @staticmethod
    def _reject_durable_state_path(path: Path) -> None:
        """Keep reconstructible SQLite bytes out of durable state authority."""

        if (
            path.parent.name.casefold() == "state"
            and path.name.casefold().startswith("index.sqlite")
        ):
            raise LocalIndexError(
                "local index belongs under local/, never under durable state/"
            )

    def __init__(
        self,
        path: str | Path,
        *,
        authority_validator: Callable[[IndexRecord], None] | None = None,
        _read_only_existing: bool = False,
    ) -> None:
        self.path = Path(path)
        self._reject_durable_state_path(self.path)
        self._authority_validator = authority_validator
        if type(_read_only_existing) is not bool:
            raise TypeError("LocalIndex read-only mode must be boolean")
        self._read_only_existing = _read_only_existing
        self._read_snapshot_active = False
        if str(path) == ":memory:":
            raise ValueError("LocalIndex requires a filesystem path")
        before: tuple[int, int, int, int] | None = None
        if self._read_only_existing:
            before = self._require_existing_read_only_path()
            connection_target: str | Path = (
                self.path.resolve(strict=True).as_uri() + "?mode=ro"
            )
        else:
            try:
                ensure_link_free_directory_chain(self.path.parent)
            except PathBoundaryError as exc:
                raise LocalIndexError(
                    "local index directory boundary is invalid"
                ) from exc
            connection_target = self.path
        try:
            self._connection = sqlite3.connect(
                connection_target,
                isolation_level=None,
                timeout=self.BUSY_TIMEOUT_MS / 1_000,
                uri=self._read_only_existing,
            )
        except sqlite3.Error as exc:
            raise LocalIndexError("local index could not be opened") from exc
        self._connection.row_factory = sqlite3.Row
        try:
            if self._read_only_existing:
                self._configure_read_only()
                if self._require_existing_read_only_path() != before:
                    raise IndexIntegrityError(
                        "local index changed identity while opening read-only"
                    )
                self._begin_read_snapshot()
                self._require_current_schema()
            else:
                require_link_free_directory_chain(self.path.parent)
                self._configure()
                self._connection.executescript(_CREATE_SCHEMA)
                self._migrate_schema()
        except PathBoundaryError as exc:
            self.close()
            raise LocalIndexError(
                "local index directory changed during open"
            ) from exc
        except BaseException:
            self.close()
            raise

    def _require_existing_read_only_path(self) -> tuple[int, int, int, int]:
        try:
            require_link_free_directory_chain(self.path.parent)
            metadata = self.path.lstat()
        except (OSError, PathBoundaryError) as exc:
            raise LocalIndexError(
                "read-only local index must already exist"
            ) from exc
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or bool(
                getattr(metadata, "st_file_attributes", 0) & reparse_flag
            )
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
        ):
            raise IndexIntegrityError(
                "read-only local index must be a regular single-link file"
            )
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
        )

    def __enter__(self) -> "LocalIndex":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            if self._read_snapshot_active and self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
        finally:
            self._read_snapshot_active = False
            self._connection.close()

    def read_only(self) -> "LocalIndexView":
        """Return a capability that exposes no projection mutation methods."""

        return LocalIndexView(self)

    @classmethod
    def materialize_payload_lookup_indexes(
        cls,
        path: str | Path,
    ) -> dict[str, int | str]:
        """Install schema-v3 query projections without changing authority rows.

        This is an explicit local-projection maintenance boundary.  It accepts
        only an already valid v1, v2, or v3 database; installs allowlisted
        expression indexes and derived Component surface bindings; and proves
        that the authority-neutral record count, digest, and validity bit did
        not move.
        """

        target = Path(path)
        try:
            require_link_free_directory_chain(target.parent)
            metadata = target.lstat()
        except (OSError, PathBoundaryError) as exc:
            raise LocalIndexError(
                "payload lookup index maintenance requires an existing index"
            ) from exc
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or bool(
                getattr(metadata, "st_file_attributes", 0) & reparse_flag
            )
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
        ):
            raise IndexIntegrityError(
                "payload lookup index maintenance requires a regular single-link file"
            )
        file_identity = (metadata.st_dev, metadata.st_ino)

        def snapshot() -> tuple[int, int, str, int]:
            try:
                connection = sqlite3.connect(
                    target.resolve(strict=True).as_uri() + "?mode=ro",
                    isolation_level=None,
                    uri=True,
                )
                row = connection.execute(
                    "SELECT record_count, projection_digest, projection_valid "
                    "FROM projection_stats WHERE singleton = 1"
                ).fetchone()
                version = connection.execute(
                    "PRAGMA user_version"
                ).fetchone()[0]
            except sqlite3.Error as exc:
                raise LocalIndexError(
                    "payload lookup index maintenance cannot read projection"
                ) from exc
            finally:
                if "connection" in locals():
                    connection.close()
            if (
                type(version) is not int
                or version not in {1, 2, _INDEX_SCHEMA_VERSION}
                or row is None
                or type(row[0]) is not int
                or type(row[1]) is not str
                or type(row[2]) is not int
                or row[2] != 1
            ):
                raise IndexIntegrityError(
                    "query projection maintenance requires one valid v1, v2, or v3 projection"
                )
            return version, row[0], row[1], row[2]

        before = snapshot()
        with cls(target) as index:
            index._require_payload_lookup_indexes()
            index.check_integrity()
            component_guard = index.component_surface_guard()
            controlled_chassis_study_guard = (
                index.controlled_chassis_study_guard()
            )
        after = snapshot()
        try:
            after_metadata = target.lstat()
        except OSError as exc:
            raise IndexIntegrityError(
                "payload lookup index changed path identity during maintenance"
            ) from exc
        if (
            (after_metadata.st_dev, after_metadata.st_ino) != file_identity
            or stat.S_ISLNK(after_metadata.st_mode)
            or bool(
                getattr(after_metadata, "st_file_attributes", 0)
                & reparse_flag
            )
            or not stat.S_ISREG(after_metadata.st_mode)
            or after_metadata.st_nlink != 1
            or before[1:] != after[1:]
            or after[0] != _INDEX_SCHEMA_VERSION
        ):
            raise IndexIntegrityError(
                "payload lookup index maintenance changed projection authority"
            )
        return {
            "component_binding_count": component_guard[1],
            "component_count": component_guard[0],
            "component_surface_digest": component_guard[2],
            "controlled_chassis_study_count": (
                controlled_chassis_study_guard[0]
            ),
            "from_schema_version": before[0],
            "projection_digest": after[2],
            "record_count": after[1],
            "to_schema_version": after[0],
        }

    @classmethod
    def open_read_only(
        cls,
        path: str | Path,
        *,
        authority_validator: Callable[[IndexRecord], None] | None = None,
    ) -> "LocalIndexView":
        """Open one existing current-schema projection without write authority."""

        return LocalIndexView(
            cls(
                path,
                authority_validator=authority_validator,
                _read_only_existing=True,
            ),
            _owns_index=True,
        )

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

    def _configure_read_only(self) -> None:
        """Configure a query-only connection without changing database state."""

        self._connection.execute("PRAGMA query_only=ON")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA trusted_schema=OFF")
        self._connection.execute(f"PRAGMA busy_timeout={self.BUSY_TIMEOUT_MS}")
        expected = {
            "query_only": 1,
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
        journal_mode = self._connection.execute(
            "PRAGMA journal_mode"
        ).fetchone()[0]
        if str(journal_mode).lower() != "delete":
            raise LocalIndexError(
                "read-only local index is not in rollback-journal mode"
            )

    def _begin_read_snapshot(self) -> None:
        """Pin one projection snapshot for an owned read-only view.

        ``BEGIN`` alone is deferred by SQLite.  The guarded projection read is
        therefore intentional: it acquires the rollback-journal shared lock
        before the view escapes, so every later query observes one projection
        generation.  Views borrowed from a writable ``LocalIndex`` never call
        this boundary and continue to follow their owner's transaction.
        """

        if not self._read_only_existing or self._connection.in_transaction:
            raise LocalIndexError("read-only snapshot boundary is invalid")
        self._connection.execute("BEGIN")
        try:
            row = self._connection.execute(
                "SELECT projection_valid FROM projection_stats "
                "WHERE singleton = 1"
            ).fetchone()
            if row is None or row[0] != 1:
                raise IndexIntegrityError(
                    "read-only local index projection is not valid"
                )
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        self._read_snapshot_active = True

    def _require_current_schema(self) -> None:
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if type(version) is not int or version != _INDEX_SCHEMA_VERSION:
            raise LocalIndexError(
                "read-only local index schema requires explicit local-index "
                f"materialization: {version!r}"
            )
        self._require_payload_lookup_indexes()
        self._require_component_surface_schema()
        self._require_controlled_chassis_study_schema()
        self._require_component_surface_guard()
        self._require_controlled_chassis_study_guard()

    def _require_payload_lookup_indexes(self) -> None:
        rows = self._connection.execute("PRAGMA index_list('records')").fetchall()
        present = {str(row[1]) for row in rows}
        missing = sorted(
            lookup.index_name
            for lookup in _PAYLOAD_TEXT_LOOKUPS.values()
            if lookup.index_name not in present
        )
        if missing:
            raise LocalIndexError(
                "local index lacks required payload lookup indexes: "
                + ", ".join(missing)
            )
        for lookup in _PAYLOAD_TEXT_LOOKUPS.values():
            details = tuple(
                str(row[3])
                for row in self._connection.execute(
                    f"EXPLAIN QUERY PLAN {_payload_text_lookup_sql(lookup)}",
                    ("schema-check-kind", "schema-check-value"),
                ).fetchall()
            )
            if not any(
                detail.startswith(
                    f"SEARCH records USING INDEX {lookup.index_name}"
                )
                and "kind=?" in detail
                for detail in details
            ):
                raise LocalIndexError(
                    "local index payload lookup definition is malformed: "
                    + lookup.index_name
                )

    def _require_component_surface_schema(self) -> None:
        columns = tuple(
            str(row[1])
            for row in self._connection.execute(
                "PRAGMA table_info('component_surface_bindings')"
            ).fetchall()
        )
        if columns != ("surface_kind", "surface_identity", "component_id"):
            raise LocalIndexError(
                "local index Component surface binding table is malformed"
            )
        indexes = {
            str(row[1])
            for row in self._connection.execute(
                "PRAGMA index_list('component_surface_bindings')"
            ).fetchall()
        }
        if "ix_component_surface_bindings_component" not in indexes:
            raise LocalIndexError(
                "local index lacks the Component surface reverse index"
            )
        required_triggers = {
            "component_surface_bindings_delete_invalid",
            "component_surface_bindings_insert_invalid",
            "component_surface_bindings_update_invalid",
            "component_surface_stats_delete_invalid",
            "component_surface_stats_insert_invalid",
            "component_surface_stats_update_invalid",
        }
        triggers = {
            str(row[0])
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            ).fetchall()
        }
        if not required_triggers.issubset(triggers):
            raise LocalIndexError(
                "local index lacks Component surface invalidation triggers"
            )
        details = tuple(
            str(row[3])
            for row in self._connection.execute(
                f"EXPLAIN QUERY PLAN {_component_surface_lookup_sql(1)}",
                (
                    COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                    "architecture-component-surface:" + "0" * 64,
                ),
            ).fetchall()
        )
        if (
            any(detail.startswith("SCAN binding") for detail in details)
            or any(detail.startswith("SCAN record") for detail in details)
            or not any(
                detail.startswith("SEARCH binding USING PRIMARY KEY")
                and "surface_kind=?" in detail
                and "surface_identity=?" in detail
                for detail in details
            )
            or not any(
                detail.startswith("SEARCH record USING PRIMARY KEY")
                and "kind=?" in detail
                and "record_id=?" in detail
                for detail in details
            )
        ):
            raise LocalIndexError(
                "local index Component surface lookup plan is malformed"
            )

    def _require_controlled_chassis_study_schema(self) -> None:
        columns = tuple(
            str(row[1])
            for row in self._connection.execute(
                "PRAGMA table_info('controlled_chassis_study_stats')"
            ).fetchall()
        )
        if columns != ("singleton", "study_count", "presence_valid"):
            raise LocalIndexError(
                "local index controlled-chassis Study projection is malformed"
            )
        required_triggers = {
            "controlled_chassis_study_stats_delete_invalid",
            "controlled_chassis_study_stats_insert_invalid",
            "controlled_chassis_study_stats_update_invalid",
            "records_controlled_chassis_study_delete",
            "records_controlled_chassis_study_insert",
            "records_controlled_chassis_study_update",
        }
        triggers = {
            str(row[0])
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            ).fetchall()
        }
        if not required_triggers.issubset(triggers):
            raise LocalIndexError(
                "local index lacks controlled-chassis Study projection triggers"
            )
        details = tuple(
            str(row[3])
            for row in self._connection.execute(
                "EXPLAIN QUERY PLAN "
                + _CONTROLLED_CHASSIS_STUDY_GUARD_SQL,
                (1,),
            ).fetchall()
        )
        if any(
            detail.startswith("SCAN controlled_chassis_study_stats")
            for detail in details
        ) or not any(
            detail.startswith(
                "SEARCH controlled_chassis_study_stats USING PRIMARY KEY"
            )
            and "singleton=?" in detail
            for detail in details
        ):
            raise LocalIndexError(
                "local index controlled-chassis Study lookup plan is malformed"
            )

    def _migrate_schema(self) -> None:
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if version == _INDEX_SCHEMA_VERSION:
            self._require_payload_lookup_indexes()
            self._require_component_surface_schema()
            self._require_controlled_chassis_study_schema()
            # A writable owner is also the explicit recovery capability.  It
            # must be able to open a structurally current but corrupt derived
            # projection so ``check_integrity`` can classify it and ``rebuild``
            # can reconstruct it from durable authority.  Read-only opens use
            # ``_require_current_schema`` and still require this guard before
            # exposing any query capability.
            return
        if version not in {0, 1, 2}:
            raise LocalIndexError(
                f"local index schema version is unsupported: {version}"
            )
        with self._write_transaction():
            projection_valid = self.projection_guard()[1]
            if not projection_valid:
                raise IndexIntegrityError(
                    "local index schema migration requires a valid projection"
                )
            if version == 0:
                self._connection.execute("DELETE FROM record_kind_stats")
                self._connection.execute(
                    "INSERT INTO record_kind_stats(kind, record_count) "
                    "SELECT kind, count(*) FROM records GROUP BY kind"
                )
                self._connection.execute(
                    "UPDATE projection_stats SET projection_valid = 0 "
                    "WHERE singleton = 1"
                )
            self._rebuild_component_surface_bindings()
            self._refresh_controlled_chassis_study_guard()
            self._connection.execute(
                f"PRAGMA user_version = {_INDEX_SCHEMA_VERSION}"
            )
            self._connection.execute(
                "UPDATE projection_stats SET projection_valid = ? "
                "WHERE singleton = 1",
                (int(projection_valid),),
            )
        self._require_payload_lookup_indexes()
        self._require_component_surface_schema()
        self._require_controlled_chassis_study_schema()
        self._require_component_surface_guard()
        self._require_controlled_chassis_study_guard()

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
        if self._read_only_existing:
            raise LocalIndexError("read-only local index cannot mutate projection")
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
        has_components = any(
            value.record.kind == "component-manifest" for value in prepared
        )
        with self._write_transaction():
            projection_was_valid = self.projection_guard()[1]
            if has_components:
                self._require_component_surface_guard()
            inserted_component = False
            for value in prepared:
                is_component = value.record.kind == "component-manifest"
                changed = self._insert_prepared(
                    value,
                    _defer_component_surface_guard=is_component,
                )
                inserted.append(changed)
                inserted_component = inserted_component or (
                    is_component and changed
                )
            if inserted_component:
                self._refresh_component_surface_guard()
                if projection_was_valid:
                    self._connection.execute(
                        "UPDATE projection_stats SET projection_valid = 1 "
                        "WHERE singleton = 1"
                    )
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

    @staticmethod
    def _component_surfaces_for_record(
        record: IndexRecord,
    ) -> ComponentSurfaceIdentities:
        payload = record.payload
        manifest = payload.get("manifest")
        if (
            record.kind != "component-manifest"
            or record.status != "registered"
            or set(payload)
            != {
                "component_id",
                "manifest",
                "protocol_domain",
                "schema",
                "semantic_surface_identity",
            }
            or payload.get("schema") != "component_manifest_projection.v1"
            or not isinstance(manifest, Mapping)
        ):
            raise IndexIntegrityError(
                "Component manifest projection envelope is malformed"
            )
        try:
            surfaces = component_manifest_surfaces(manifest)
        except ComponentManifestError as exc:
            raise IndexIntegrityError(
                "Component manifest projection contains an invalid manifest"
            ) from exc
        protocol = manifest.get("protocol")
        protocol_domain = (
            None
            if not isinstance(protocol, str)
            else protocol.split(".", 1)[0]
        )
        if (
            record.record_id != surfaces.component_id
            or record.subject != f"Component:{surfaces.component_id}"
            or record.fingerprint != surfaces.domain_aware
            or payload.get("component_id") != surfaces.component_id
            or payload.get("protocol_domain") != protocol_domain
            or payload.get("semantic_surface_identity") != surfaces.domain_aware
        ):
            raise IndexIntegrityError(
                "Component manifest projection differs from canonical surfaces"
            )
        return surfaces

    def _insert_component_surface_bindings(self, record: IndexRecord) -> None:
        surfaces = self._component_surfaces_for_record(record)
        for surface_kind, surface_identity in surfaces.bindings():
            self._connection.execute(
                "INSERT INTO component_surface_bindings("
                "surface_kind, surface_identity, component_id"
                ") VALUES (?, ?, ?)",
                (surface_kind, surface_identity, surfaces.component_id),
            )

    def _component_surface_binding_rows(
        self,
    ) -> tuple[tuple[str, str, str], ...]:
        return tuple(
            (str(row[0]), str(row[1]), str(row[2]))
            for row in self._connection.execute(
                "SELECT surface_kind, surface_identity, component_id "
                "FROM component_surface_bindings "
                "ORDER BY surface_kind, surface_identity, component_id"
            ).fetchall()
        )

    def _refresh_component_surface_guard(self) -> None:
        bindings = self._component_surface_binding_rows()
        component_count_row = self._connection.execute(
            "SELECT record_count FROM record_kind_stats WHERE kind = ?",
            ("component-manifest",),
        ).fetchone()
        component_count = (
            0 if component_count_row is None else int(component_count_row[0])
        )
        self._connection.execute(
            "UPDATE component_surface_stats SET component_count = ?, "
            "binding_count = ?, binding_digest = ?, binding_valid = 1 "
            "WHERE singleton = 1",
            (
                component_count,
                len(bindings),
                _component_surface_binding_digest(bindings),
            ),
        )

    def component_surface_guard(self) -> tuple[int, int, str, bool]:
        """Return the derived Component projection guard after exact checks."""

        _, projection_valid = self.projection_guard()
        if not projection_valid:
            raise IndexIntegrityError(
                "Component surface projection has invalid record authority"
            )
        row = self._connection.execute(
            "SELECT component_count, binding_count, binding_digest, "
            "binding_valid FROM component_surface_stats WHERE singleton = 1"
        ).fetchone()
        source_count_row = self._connection.execute(
            "SELECT record_count FROM record_kind_stats WHERE kind = ?",
            ("component-manifest",),
        ).fetchone()
        source_count = 0 if source_count_row is None else source_count_row[0]
        if (
            row is None
            or type(row["component_count"]) is not int
            or type(row["binding_count"]) is not int
            or type(row["binding_digest"]) is not str
            or len(row["binding_digest"]) != 64
            or row["binding_valid"] not in {0, 1}
            or row["component_count"] != source_count
            or row["binding_count"] < row["component_count"] * 2
            or row["binding_count"] > row["component_count"] * 3
            or row["binding_valid"] != 1
        ):
            raise IndexIntegrityError(
                "Component surface projection guard is invalid"
            )
        return (
            row["component_count"],
            row["binding_count"],
            row["binding_digest"],
            bool(row["binding_valid"]),
        )

    def _require_component_surface_guard(self) -> None:
        self.component_surface_guard()

    def _validate_component_surface_projection(self) -> None:
        expected: set[tuple[str, str, str]] = set()
        rows = self._connection.execute(
            _HOT_QUERIES["records_by_kind"].sql,
            ("component-manifest",),
        ).fetchall()
        for row in rows:
            record = self._decode_record(row)
            surfaces = self._component_surfaces_for_record(record)
            expected.update(
                (surface_kind, surface_identity, surfaces.component_id)
                for surface_kind, surface_identity in surfaces.bindings()
            )
        observed = self._component_surface_binding_rows()
        stats = self._connection.execute(
            "SELECT component_count, binding_count, binding_digest, "
            "binding_valid FROM component_surface_stats WHERE singleton = 1"
        ).fetchone()
        if (
            tuple(sorted(expected)) != observed
            or stats is None
            or stats["component_count"] != len(rows)
            or stats["binding_count"] != len(observed)
            or stats["binding_digest"]
            != _component_surface_binding_digest(observed)
            or stats["binding_valid"] != 1
        ):
            raise IndexIntegrityError(
                "Component surface projection differs from Component records"
            )

    def _rebuild_component_surface_bindings(self) -> None:
        self._connection.execute("DELETE FROM component_surface_bindings")
        rows = self._connection.execute(
            _HOT_QUERIES["records_by_kind"].sql,
            ("component-manifest",),
        ).fetchall()
        for row in rows:
            self._insert_component_surface_bindings(self._decode_record(row))
        self._refresh_component_surface_guard()
        self._validate_component_surface_projection()

    def _refresh_controlled_chassis_study_guard(self) -> None:
        row = self._connection.execute(
            "SELECT count(*) FROM records WHERE kind = 'study-open' "
            "AND json_type(payload_json, '$.controlled_chassis') = 'object'"
        ).fetchone()
        if row is None or type(row[0]) is not int or row[0] < 0:
            raise IndexIntegrityError(
                "controlled-chassis Study source count is invalid"
            )
        self._connection.execute(
            "INSERT INTO controlled_chassis_study_stats("
            "singleton, study_count, presence_valid) VALUES (1, ?, 1) "
            "ON CONFLICT(singleton) DO UPDATE SET "
            "study_count = excluded.study_count, presence_valid = 1",
            (row[0],),
        )

    def controlled_chassis_study_guard(self) -> tuple[int, bool]:
        """Return the exact schema-bound Study-presence count in O(1)."""

        _, projection_valid = self.projection_guard()
        if not projection_valid:
            raise IndexIntegrityError(
                "controlled-chassis Study projection has invalid authority"
            )
        row = self._connection.execute(
            _CONTROLLED_CHASSIS_STUDY_GUARD_SQL,
            (1,),
        ).fetchone()
        if (
            row is None
            or type(row["study_count"]) is not int
            or row["study_count"] < 0
            or row["presence_valid"] != 1
        ):
            raise IndexIntegrityError(
                "controlled-chassis Study projection guard is invalid"
            )
        return row["study_count"], True

    def _require_controlled_chassis_study_guard(self) -> None:
        self.controlled_chassis_study_guard()

    def _validate_controlled_chassis_study_projection(self) -> None:
        expected = self._connection.execute(
            "SELECT count(*) FROM records WHERE kind = 'study-open' "
            "AND json_type(payload_json, '$.controlled_chassis') = 'object'"
        ).fetchone()
        observed = self._connection.execute(
            _CONTROLLED_CHASSIS_STUDY_GUARD_SQL,
            (1,),
        ).fetchone()
        if (
            expected is None
            or observed is None
            or observed["study_count"] != expected[0]
            or observed["presence_valid"] != 1
        ):
            raise IndexIntegrityError(
                "controlled-chassis Study projection differs from Study records"
            )

    def _insert_prepared(
        self,
        prepared: _PreparedRecord,
        *,
        _defer_component_surface_guard: bool = False,
    ) -> bool:
        record = prepared.record
        _, projection_was_valid = self.projection_guard()
        is_component = record.kind == "component-manifest"
        if is_component and not _defer_component_surface_guard:
            self._require_component_surface_guard()
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
            if is_component:
                self._insert_component_surface_bindings(record)
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
            # Event-head and kind-count triggers make every out-of-band
            # mutation fail closed.  Only this transaction, which began from
            # a valid projection and derived both views from the inserted
            # immutable record, may restore the guard.
            if is_component and not _defer_component_surface_guard:
                self._refresh_component_surface_guard()
            if projection_was_valid and not (
                is_component and _defer_component_surface_guard
            ):
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

    def records_by_kind_prefix(
        self,
        kind: str,
        record_id_prefix: str,
    ) -> tuple[IndexRecord, ...]:
        """Return one authority-checked record-id prefix through the primary key.

        This is the bounded workflow-history path.  Unlike ``records_by_kind``,
        its cost follows the selected workflow prefix rather than every record
        of the kind accumulated by the project.
        """

        lower, upper = _ascii_prefix_bounds(
            "record_id_prefix",
            record_id_prefix,
        )
        rows = self._connection.execute(
            _RECORDS_BY_KIND_PREFIX_SQL,
            (_require_text("kind", kind), lower, upper),
        ).fetchall()
        records = tuple(self._decode_record(row) for row in rows)
        if any(not record.record_id.startswith(lower) for record in records):
            raise IndexIntegrityError("record prefix lookup escaped its bound")
        return records

    def records_by_kind_prefix_access_shape(
        self,
        kind: str,
        record_id_prefix: str,
    ) -> tuple[str, ...]:
        """Prove the workflow-prefix lookup uses the composite primary key."""

        lower, upper = _ascii_prefix_bounds(
            "record_id_prefix",
            record_id_prefix,
        )
        details = tuple(
            str(row[3])
            for row in self._connection.execute(
                f"EXPLAIN QUERY PLAN {_RECORDS_BY_KIND_PREFIX_SQL}",
                (_require_text("kind", kind), lower, upper),
            ).fetchall()
        )
        shape: list[str] = []
        for detail in details:
            words = detail.split()
            operation = words[0].upper() if words else "UNKNOWN"
            table = words[1] if len(words) > 1 else ""
            shape.append(f"{operation}:{table}")
            if operation == "SCAN" and table == "records":
                raise QueryPlanError(
                    "record prefix lookup scans the history-growing table"
                )
        if not any(
            detail.startswith("SEARCH records USING PRIMARY KEY")
            and "kind=?" in detail
            and "record_id>?" in detail
            and "record_id<?" in detail
            for detail in details
        ):
            raise QueryPlanError(
                "record prefix lookup lacks its complete primary-key range"
            )
        return tuple(shape)

    def records_by_payload_text(
        self,
        kind: str,
        lookup_name: str,
        value: str,
    ) -> tuple[IndexRecord, ...]:
        """Return an allowlisted payload-text equality slice through schema v2.

        The JSON path is selected only by this module's static allowlist; a
        caller cannot turn this into an arbitrary JSON query or a table scan.
        Decoded records are independently rejoined to their canonical payload
        before returning.
        """

        lookup = _PAYLOAD_TEXT_LOOKUPS.get(lookup_name)
        if lookup is None:
            raise ValueError("payload lookup name is not allowlisted")
        typed_value = _require_text("payload lookup value", value)
        rows = self._connection.execute(
            _payload_text_lookup_sql(lookup),
            (_require_text("kind", kind), typed_value),
        ).fetchall()
        records = tuple(self._decode_record(row) for row in rows)
        if any(
            _payload_text_value(record.payload, lookup) != typed_value
            for record in records
        ):
            raise IndexIntegrityError(
                "payload lookup index differs from canonical record payload"
            )
        return records

    def records_by_payload_text_access_shape(
        self,
        kind: str,
        lookup_name: str,
        value: str,
    ) -> tuple[str, ...]:
        """Prove an allowlisted payload lookup uses its exact expression index."""

        lookup = _PAYLOAD_TEXT_LOOKUPS.get(lookup_name)
        if lookup is None:
            raise ValueError("payload lookup name is not allowlisted")
        details = tuple(
            str(row[3])
            for row in self._connection.execute(
                f"EXPLAIN QUERY PLAN {_payload_text_lookup_sql(lookup)}",
                (
                    _require_text("kind", kind),
                    _require_text("payload lookup value", value),
                ),
            ).fetchall()
        )
        if any(detail.startswith("SCAN records") for detail in details):
            raise QueryPlanError(
                "allowlisted payload lookup scans the history-growing table"
            )
        if not any(
            detail.startswith(f"SEARCH records USING INDEX {lookup.index_name}")
            and "kind=?" in detail
            for detail in details
        ):
            raise QueryPlanError(
                "allowlisted payload lookup lacks its exact expression index"
            )
        return details

    def records_by_payload_text_values(
        self,
        kind: str,
        lookup_name: str,
        values: Iterable[str],
    ) -> tuple[IndexRecord, ...]:
        """Return one indexed union for a non-empty canonical value set."""

        lookup = _PAYLOAD_TEXT_LOOKUPS.get(lookup_name)
        if lookup is None:
            raise ValueError("payload lookup name is not allowlisted")
        typed_values = _payload_lookup_values(values)
        if not typed_values:
            return ()
        rows = self._connection.execute(
            _payload_text_values_lookup_sql(lookup, len(typed_values)),
            (_require_text("kind", kind), *typed_values),
        ).fetchall()
        records = tuple(self._decode_record(row) for row in rows)
        allowed = set(typed_values)
        if any(
            _payload_text_value(record.payload, lookup) not in allowed
            for record in records
        ):
            raise IndexIntegrityError(
                "payload lookup union differs from canonical record payload"
            )
        return records

    def records_by_payload_text_values_access_shape(
        self,
        kind: str,
        lookup_name: str,
        values: Iterable[str],
    ) -> tuple[str, ...]:
        """Prove a payload lookup union retains the exact expression index."""

        lookup = _PAYLOAD_TEXT_LOOKUPS.get(lookup_name)
        if lookup is None:
            raise ValueError("payload lookup name is not allowlisted")
        typed_values = _payload_lookup_values(values)
        if not typed_values:
            raise ValueError("payload lookup access shape requires a value")
        details = tuple(
            str(row[3])
            for row in self._connection.execute(
                "EXPLAIN QUERY PLAN "
                + _payload_text_values_lookup_sql(
                    lookup,
                    len(typed_values),
                ),
                (_require_text("kind", kind), *typed_values),
            ).fetchall()
        )
        if any(detail.startswith("SCAN records") for detail in details):
            raise QueryPlanError(
                "allowlisted payload lookup union scans the history-growing table"
            )
        if not any(
            detail.startswith(f"SEARCH records USING INDEX {lookup.index_name}")
            and "kind=?" in detail
            for detail in details
        ):
            raise QueryPlanError(
                "allowlisted payload lookup union lacks its expression index"
            )
        return details

    def component_manifests_by_surface(
        self,
        surface_kind: str,
        surface_identity: str,
    ) -> tuple[IndexRecord, ...]:
        """Return exact Component manifests for one derived semantic surface."""

        return self.component_manifests_by_surfaces(
            surface_kind,
            (surface_identity,),
        )

    def component_manifests_by_surfaces(
        self,
        surface_kind: str,
        surface_identities: Iterable[str],
    ) -> tuple[IndexRecord, ...]:
        """Return an indexed union of Component manifests with post-verification."""

        self._require_component_surface_guard()
        kind = _component_surface_kind(surface_kind)
        identities = _component_surface_values(kind, surface_identities)
        if not identities:
            return ()
        rows = self._connection.execute(
            _component_surface_lookup_sql(len(identities)),
            (kind, *identities),
        ).fetchall()
        allowed = set(identities)
        records: list[IndexRecord] = []
        for row in rows:
            record = self._decode_record(row)
            surfaces = self._component_surfaces_for_record(record)
            binding_surface = row["binding_surface_identity"]
            if (
                binding_surface not in allowed
                or surfaces.identity_for(kind) != binding_surface
            ):
                raise IndexIntegrityError(
                    "Component surface binding differs from canonical manifest"
                )
            records.append(record)
        return tuple(records)

    def component_manifests_by_surfaces_access_shape(
        self,
        surface_kind: str,
        surface_identities: Iterable[str],
    ) -> tuple[str, ...]:
        """Prove Component surface lookup uses both exact primary keys."""

        kind = _component_surface_kind(surface_kind)
        identities = _component_surface_values(kind, surface_identities)
        if not identities:
            raise ValueError("Component surface access shape requires a value")
        details = tuple(
            str(row[3])
            for row in self._connection.execute(
                "EXPLAIN QUERY PLAN "
                + _component_surface_lookup_sql(len(identities)),
                (kind, *identities),
            ).fetchall()
        )
        if any(
            detail.startswith("SCAN binding")
            or detail.startswith("SCAN record")
            for detail in details
        ):
            raise QueryPlanError(
                "Component surface lookup scans a history-growing table"
            )
        if not any(
            detail.startswith("SEARCH binding USING PRIMARY KEY")
            and "surface_kind=?" in detail
            and "surface_identity=?" in detail
            for detail in details
        ) or not any(
            detail.startswith("SEARCH record USING PRIMARY KEY")
            and "kind=?" in detail
            and "record_id=?" in detail
            for detail in details
        ):
            raise QueryPlanError(
                "Component surface lookup lacks its complete keyed plan"
            )
        return details

    def component_surface_bindings_for_component(
        self,
        component_id: str,
    ) -> tuple[tuple[str, str], ...]:
        """Return and fully verify one Component's reverse surface projection."""

        self._require_component_surface_guard()
        identity = _require_text("component_id", component_id)
        digest = identity.removeprefix("component:")
        if (
            not identity.startswith("component:")
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("component_id is not a Component identity")
        record = self.get("component-manifest", identity)
        rows = self._connection.execute(
            "SELECT surface_kind, surface_identity "
            "FROM component_surface_bindings "
            "INDEXED BY ix_component_surface_bindings_component "
            "WHERE component_id = ? ORDER BY surface_kind, surface_identity",
            (identity,),
        ).fetchall()
        observed = tuple((str(row[0]), str(row[1])) for row in rows)
        if record is None:
            if observed:
                raise IndexIntegrityError(
                    "Component surface binding has no Component manifest"
                )
            return ()
        expected = self._component_surfaces_for_record(record).bindings()
        if observed != expected:
            raise IndexIntegrityError(
                "Component reverse surface projection is incomplete"
            )
        return observed

    def component_surface_bindings_for_component_access_shape(
        self,
        component_id: str,
    ) -> tuple[str, ...]:
        identity = _require_text("component_id", component_id)
        details = tuple(
            str(row[3])
            for row in self._connection.execute(
                "EXPLAIN QUERY PLAN SELECT surface_kind, surface_identity "
                "FROM component_surface_bindings "
                "INDEXED BY ix_component_surface_bindings_component "
                "WHERE component_id = ? ORDER BY surface_kind, surface_identity",
                (identity,),
            ).fetchall()
        )
        if any(detail.startswith("SCAN component_surface_bindings") for detail in details):
            raise QueryPlanError("Component reverse lookup scans all bindings")
        if not any(
            "ix_component_surface_bindings_component" in detail
            and "component_id=?" in detail
            for detail in details
        ):
            raise QueryPlanError("Component reverse lookup lacks its exact index")
        return details

    def has_controlled_chassis_study(self) -> bool:
        """Return whether any Study binds a controlled-chassis JSON object.

        This intentionally exposes one schema-bound question instead of an
        arbitrary JSON-path query.  Its answer comes from a singleton derived
        projection maintained with every immutable record transaction.
        """

        study_count, _valid = self.controlled_chassis_study_guard()
        return study_count > 0

    def has_controlled_chassis_study_access_shape(self) -> tuple[str, ...]:
        """Prove the presence lookup uses one singleton primary-key search."""

        details = tuple(
            str(row[3])
            for row in self._connection.execute(
                "EXPLAIN QUERY PLAN "
                + _CONTROLLED_CHASSIS_STUDY_GUARD_SQL,
                (1,),
            ).fetchall()
        )
        if any(
            detail.startswith("SCAN controlled_chassis_study_stats")
            for detail in details
        ) or not any(
            detail.startswith(
                "SEARCH controlled_chassis_study_stats USING PRIMARY KEY"
            )
            and "singleton=?" in detail
            for detail in details
        ):
            raise QueryPlanError(
                "controlled-chassis Study presence lookup is not O(1)"
            )
        return details

    def check_hot_queries(self) -> dict[str, tuple[str, ...]]:
        representative = {
            "record_by_key": ("kind", "record"),
            "event_head_by_stream": ("stream",),
            "latest_event_record_by_stream": ("stream",),
            "event_record_by_position": ("stream", 1),
            "projection_record_count": (1,),
            "record_count_by_kind": ("kind",),
        }
        return {
            name: self.hot_query_access_shape(name, representative[name])
            for name in self.hot_query_names()
        }

    def count_by_kind(self, kind: str) -> int:
        """Return one keyed aggregate without materializing authority rows."""

        _, projection_valid = self.projection_guard()
        if not projection_valid:
            raise IndexIntegrityError("record-kind count projection is invalid")
        row = self._connection.execute(
            _HOT_QUERIES["record_count_by_kind"].sql,
            (_require_text("kind", kind),),
        ).fetchone()
        if row is None:
            return 0
        count = row["record_count"]
        if type(count) is not int or count < 0:
            raise IndexIntegrityError("record-kind count projection is invalid")
        return count

    def count_by_kind_before_authority_sequence(
        self,
        kind: str,
        authority_sequence: int,
    ) -> int:
        """Count one kind before an immutable Journal position.

        The covering ``(kind, authority_sequence)`` index keeps this aggregate
        inside SQLite.  Callers recover a historical ordinal without decoding
        every older record of the kind into Python.
        """

        if (
            type(authority_sequence) is not int
            or authority_sequence < 1
        ):
            raise ValueError("authority_sequence must be a positive integer")
        row = self._connection.execute(
            _COUNT_BY_KIND_BEFORE_AUTHORITY_SEQUENCE_SQL,
            (_require_text("kind", kind), authority_sequence),
        ).fetchone()
        if row is None:
            raise IndexIntegrityError("authority-prefix count is unavailable")
        count = row["record_count"]
        if type(count) is not int or count < 0:
            raise IndexIntegrityError("authority-prefix count is invalid")
        return count

    def count_by_kind_before_authority_sequence_access_shape(
        self,
        kind: str,
        authority_sequence: int,
    ) -> tuple[str, ...]:
        """Prove the historical ordinal aggregate uses its covering index."""

        if (
            type(authority_sequence) is not int
            or authority_sequence < 1
        ):
            raise ValueError("authority_sequence must be a positive integer")
        details = tuple(
            str(row[3])
            for row in self._connection.execute(
                f"EXPLAIN QUERY PLAN "
                f"{_COUNT_BY_KIND_BEFORE_AUTHORITY_SEQUENCE_SQL}",
                (_require_text("kind", kind), authority_sequence),
            ).fetchall()
        )
        if any(detail.startswith("SCAN records") for detail in details):
            raise QueryPlanError(
                "authority-prefix count scans the history-growing table"
            )
        if not any(
            "ix_records_kind_authority_sequence" in detail
            and "kind=?" in detail
            and "authority_sequence<?" in detail
            for detail in details
        ):
            raise QueryPlanError(
                "authority-prefix count lacks its complete covering range"
            )
        return details

    def records_by_kind_at_authority_sequence(
        self,
        kind: str,
        authority_sequence: int,
    ) -> tuple[IndexRecord, ...]:
        """Return one kind from one exact immutable Journal event.

        The partial ``(kind, authority_sequence)`` index keeps this lookup
        bounded to the named event rather than scanning every operation or
        other history-growing record of the kind.
        """

        if type(authority_sequence) is not int or authority_sequence < 1:
            raise ValueError("authority_sequence must be a positive integer")
        rows = self._connection.execute(
            _RECORDS_BY_KIND_AT_AUTHORITY_SEQUENCE_SQL,
            (_require_text("kind", kind), authority_sequence),
        ).fetchall()
        return tuple(self._decode_record(row) for row in rows)

    def records_by_kind_at_authority_sequence_access_shape(
        self,
        kind: str,
        authority_sequence: int,
    ) -> tuple[str, ...]:
        """Prove exact-event kind lookup uses its covering authority index."""

        if type(authority_sequence) is not int or authority_sequence < 1:
            raise ValueError("authority_sequence must be a positive integer")
        details = tuple(
            str(row[3])
            for row in self._connection.execute(
                f"EXPLAIN QUERY PLAN "
                f"{_RECORDS_BY_KIND_AT_AUTHORITY_SEQUENCE_SQL}",
                (_require_text("kind", kind), authority_sequence),
            ).fetchall()
        )
        if any(detail.startswith("SCAN records") for detail in details):
            raise QueryPlanError(
                "exact authority-event lookup scans the history-growing table"
            )
        if not any(
            "ix_records_kind_authority_sequence" in detail
            and "kind=?" in detail
            and "authority_sequence=?" in detail
            for detail in details
        ):
            raise QueryPlanError(
                "exact authority-event lookup lacks its complete indexed key"
            )
        return details

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
        if type(sequence) is not int or sequence < 0:
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
            # Re-anchor the count before DELETE triggers run so recovery also
            # works when only this derived singleton was corrupted or absent.
            self._refresh_controlled_chassis_study_guard()
            self._connection.execute("DELETE FROM event_heads")
            self._connection.execute("DELETE FROM component_surface_bindings")
            self._connection.execute("DELETE FROM records")
            self._connection.execute("DELETE FROM record_kind_stats")
            self._connection.execute(
                "UPDATE controlled_chassis_study_stats "
                "SET study_count = 0, presence_valid = 1 WHERE singleton = 1"
            )
            self._connection.execute(
                "UPDATE component_surface_stats SET component_count = 0, "
                "binding_count = 0, binding_digest = ?, binding_valid = 1 "
                "WHERE singleton = 1",
                (_EMPTY_COMPONENT_SURFACE_DIGEST,),
            )
            self._connection.execute(
                "UPDATE projection_stats SET record_count = 0, "
                "projection_digest = ?, projection_valid = 1 WHERE singleton = 1",
                (_EMPTY_PROJECTION_DIGEST,),
            )
            for record in prepared:
                inserted += int(
                    self._insert_prepared(
                        record,
                        _defer_component_surface_guard=True,
                    )
                )
            self._refresh_component_surface_guard()
            self._connection.execute(
                "UPDATE projection_stats SET projection_valid = 1 "
                "WHERE singleton = 1"
            )
            self._validate_component_surface_projection()
            self._validate_controlled_chassis_study_projection()
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
        try:
            self._require_component_surface_guard()
            self._validate_component_surface_projection()
            self._require_controlled_chassis_study_guard()
            self._validate_controlled_chassis_study_projection()
        except IndexIntegrityError:
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
        self._require_component_surface_schema()
        self._require_controlled_chassis_study_schema()
        report = self.integrity_report()
        if report["integrity_check"] != ("ok",) or report["foreign_key_check"]:
            raise IndexIntegrityError(f"local index integrity failure: {report!r}")
        observed = self._connection.execute("SELECT count(*) FROM records").fetchone()[0]
        if observed != self.record_count():
            raise IndexIntegrityError("local projection record-count guard mismatch")
        projection_digest, projection_valid = self.projection_guard()
        if not projection_valid:
            raise IndexIntegrityError("local projection was invalidated by mutation")
        observed_kind_counts = tuple(
            tuple(row)
            for row in self._connection.execute(
                "SELECT kind, record_count FROM record_kind_stats ORDER BY kind"
            )
        )
        expected_kind_counts = tuple(
            tuple(row)
            for row in self._connection.execute(
                "SELECT kind, count(*) FROM records GROUP BY kind ORDER BY kind"
            )
        )
        if observed_kind_counts != expected_kind_counts:
            raise IndexIntegrityError("local record-kind count projection differs")
        self._require_component_surface_guard()
        self._validate_component_surface_projection()
        self._require_controlled_chassis_study_guard()
        self._validate_controlled_chassis_study_projection()
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
            "record_count_by_kind": "record_kind_stats.PRIMARY_KEY(kind)",
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


class LocalIndexView:
    """Read-only capability over one open, optionally authenticated index."""

    __slots__ = ("__index", "__owns_index")

    def __init__(self, index: LocalIndex, *, _owns_index: bool = False) -> None:
        if not isinstance(index, LocalIndex):
            raise TypeError("LocalIndexView requires LocalIndex")
        if type(_owns_index) is not bool:
            raise TypeError("LocalIndexView ownership must be boolean")
        self.__index = index
        self.__owns_index = _owns_index

    def __enter__(self) -> "LocalIndexView":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        if self.__owns_index:
            self.__index.close()

    @property
    def path(self) -> Path:
        """Expose only the stable backing location needed by read projections."""

        return self.__index.path

    def get(self, kind: str, record_id: str) -> IndexRecord | None:
        return self.__index.get(kind, record_id)

    def records_by_subject_status(
        self,
        subject: str,
        status: str,
    ) -> tuple[IndexRecord, ...]:
        return self.__index.records_by_subject_status(subject, status)

    def records_by_fingerprint(
        self,
        fingerprint: str,
    ) -> tuple[IndexRecord, ...]:
        return self.__index.records_by_fingerprint(fingerprint)

    def records_by_kind(self, kind: str) -> tuple[IndexRecord, ...]:
        return self.__index.records_by_kind(kind)

    def records_by_kind_prefix(
        self,
        kind: str,
        record_id_prefix: str,
    ) -> tuple[IndexRecord, ...]:
        return self.__index.records_by_kind_prefix(kind, record_id_prefix)

    def records_by_kind_prefix_access_shape(
        self,
        kind: str,
        record_id_prefix: str,
    ) -> tuple[str, ...]:
        return self.__index.records_by_kind_prefix_access_shape(
            kind,
            record_id_prefix,
        )

    def records_by_payload_text(
        self,
        kind: str,
        lookup_name: str,
        value: str,
    ) -> tuple[IndexRecord, ...]:
        return self.__index.records_by_payload_text(
            kind,
            lookup_name,
            value,
        )

    def records_by_payload_text_access_shape(
        self,
        kind: str,
        lookup_name: str,
        value: str,
    ) -> tuple[str, ...]:
        return self.__index.records_by_payload_text_access_shape(
            kind,
            lookup_name,
            value,
        )

    def records_by_payload_text_values(
        self,
        kind: str,
        lookup_name: str,
        values: Iterable[str],
    ) -> tuple[IndexRecord, ...]:
        return self.__index.records_by_payload_text_values(
            kind,
            lookup_name,
            values,
        )

    def records_by_payload_text_values_access_shape(
        self,
        kind: str,
        lookup_name: str,
        values: Iterable[str],
    ) -> tuple[str, ...]:
        return self.__index.records_by_payload_text_values_access_shape(
            kind,
            lookup_name,
            values,
        )

    def component_manifests_by_surface(
        self,
        surface_kind: str,
        surface_identity: str,
    ) -> tuple[IndexRecord, ...]:
        return self.__index.component_manifests_by_surface(
            surface_kind,
            surface_identity,
        )

    def component_manifests_by_surfaces(
        self,
        surface_kind: str,
        surface_identities: Iterable[str],
    ) -> tuple[IndexRecord, ...]:
        return self.__index.component_manifests_by_surfaces(
            surface_kind,
            surface_identities,
        )

    def component_manifests_by_surfaces_access_shape(
        self,
        surface_kind: str,
        surface_identities: Iterable[str],
    ) -> tuple[str, ...]:
        return self.__index.component_manifests_by_surfaces_access_shape(
            surface_kind,
            surface_identities,
        )

    def component_surface_bindings_for_component(
        self,
        component_id: str,
    ) -> tuple[tuple[str, str], ...]:
        return self.__index.component_surface_bindings_for_component(
            component_id
        )

    def component_surface_bindings_for_component_access_shape(
        self,
        component_id: str,
    ) -> tuple[str, ...]:
        return self.__index.component_surface_bindings_for_component_access_shape(
            component_id
        )

    def component_surface_guard(self) -> tuple[int, int, str, bool]:
        return self.__index.component_surface_guard()

    def has_controlled_chassis_study(self) -> bool:
        return self.__index.has_controlled_chassis_study()

    def has_controlled_chassis_study_access_shape(self) -> tuple[str, ...]:
        return self.__index.has_controlled_chassis_study_access_shape()

    def controlled_chassis_study_guard(self) -> tuple[int, bool]:
        return self.__index.controlled_chassis_study_guard()

    def count_by_kind(self, kind: str) -> int:
        return self.__index.count_by_kind(kind)

    def count_by_kind_before_authority_sequence(
        self,
        kind: str,
        authority_sequence: int,
    ) -> int:
        return self.__index.count_by_kind_before_authority_sequence(
            kind,
            authority_sequence,
        )

    def count_by_kind_before_authority_sequence_access_shape(
        self,
        kind: str,
        authority_sequence: int,
    ) -> tuple[str, ...]:
        return self.__index.count_by_kind_before_authority_sequence_access_shape(
            kind,
            authority_sequence,
        )

    def records_by_kind_at_authority_sequence(
        self,
        kind: str,
        authority_sequence: int,
    ) -> tuple[IndexRecord, ...]:
        return self.__index.records_by_kind_at_authority_sequence(
            kind,
            authority_sequence,
        )

    def records_by_kind_at_authority_sequence_access_shape(
        self,
        kind: str,
        authority_sequence: int,
    ) -> tuple[str, ...]:
        return self.__index.records_by_kind_at_authority_sequence_access_shape(
            kind,
            authority_sequence,
        )

    def event_head(self, stream: str) -> EventHead | None:
        return self.__index.event_head(stream)

    def event_record(self, stream: str, sequence: int) -> IndexRecord | None:
        return self.__index.event_record(stream, sequence)

    def record_count(self) -> int:
        return self.__index.record_count()

    def projection_guard(self) -> tuple[str, bool]:
        return self.__index.projection_guard()

    def projected_digest(
        self,
        records: Iterable[IndexRecord | Mapping[str, Any]],
    ) -> str:
        """Project an append digest without exposing projection mutation."""

        return self.__index.projected_digest(records)

    def full_maintenance_exactly_matches(
        self,
        records: Iterable[IndexRecord | Mapping[str, Any]],
    ) -> bool:
        """Audit the full projection only at an explicit maintenance boundary."""

        return self.__index.exactly_matches(records)
