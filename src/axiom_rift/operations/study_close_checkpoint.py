"""Canonical tracked high-water for Study-close Git delivery."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from axiom_rift.core.canonical import canonical_bytes, parse_canonical


CHECKPOINT_PATH = "records/STUDY_CLOSE_DELIVERY_CHECKPOINT.json"
LEGACY_CHECKPOINT_SCHEMA = "study_close_delivery_checkpoint.v1"
CHECKPOINT_SCHEMA = "study_close_delivery_checkpoint.v2"
LEGACY_V2_CHECKPOINT_VALIDATOR_VERSION = "study_close_delivery_checkpoint.v2"
CHECKPOINT_VALIDATOR_VERSION = "study_close_delivery_checkpoint.v3"
HISTORICAL_BACKFILL_ROW_COUNT = 21
EMPTY_CLOSE_CHAIN_DIGEST = sha256(
    b"axiom-study-close-delivery-empty"
).hexdigest()

_HEX = frozenset("0123456789abcdef")
_BASES = frozenset(
    {"full_audit", "checkpoint_upgrade", "maintenance", "study_close"}
)
_VALIDATORS_BY_SCHEMA = {
    LEGACY_CHECKPOINT_SCHEMA: frozenset({"study_close_delivery_checkpoint.v1"}),
    CHECKPOINT_SCHEMA: frozenset(
        {
            LEGACY_V2_CHECKPOINT_VALIDATOR_VERSION,
            CHECKPOINT_VALIDATOR_VERSION,
        }
    ),
}


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


def _repository_path(value: object, label: str) -> str:
    if type(value) is not str or not value or "\\" in value:
        raise StudyCloseCheckpointError(f"{label} is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise StudyCloseCheckpointError(f"{label} is invalid")
    return value


def _identity(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise StudyCloseCheckpointError(f"{label} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class CheckpointPathBlob:
    """One required path and its exact Git blob identity."""

    path: str
    blob: str

    @classmethod
    def from_mapping(cls, value: object) -> "CheckpointPathBlob":
        if not isinstance(value, dict) or set(value) != {"blob", "path"}:
            raise StudyCloseCheckpointError("backfill path/blob fields differ")
        return cls(
            path=_repository_path(value["path"], "backfill path"),
            blob=_commit(value["blob"], "backfill blob"),
        )

    def payload(self) -> dict[str, str]:
        return {"blob": self.blob, "path": self.path}


@dataclass(frozen=True, slots=True)
class HistoricalKpiSource:
    """Exact historical Study-close source of one backfilled KPI record."""

    kpi_sequence: int
    study_id: str
    kpi_record_id: str
    kpi_record_sha256: str
    study_close_event_id: str
    study_close_record_id: str
    study_close_revision: int

    @classmethod
    def from_mapping(cls, value: object) -> "HistoricalKpiSource":
        expected = {
            "kpi_record_id",
            "kpi_record_sha256",
            "kpi_sequence",
            "study_close_event_id",
            "study_close_record_id",
            "study_close_revision",
            "study_id",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise StudyCloseCheckpointError("historical KPI source fields differ")
        return cls(
            kpi_sequence=_integer(
                value["kpi_sequence"], "historical KPI sequence", minimum=1
            ),
            study_id=_identity(value["study_id"], "historical Study id"),
            kpi_record_id=_identity(
                value["kpi_record_id"], "historical KPI record id"
            ),
            kpi_record_sha256=_digest(
                value["kpi_record_sha256"], "historical KPI record hash"
            ),
            study_close_event_id=_digest(
                value["study_close_event_id"], "historical Study-close event id"
            ),
            study_close_record_id=_identity(
                value["study_close_record_id"],
                "historical Study-close record id",
            ),
            study_close_revision=_integer(
                value["study_close_revision"],
                "historical Study-close revision",
                minimum=1,
            ),
        )

    def payload(self) -> dict[str, Any]:
        return {
            "kpi_record_id": self.kpi_record_id,
            "kpi_record_sha256": self.kpi_record_sha256,
            "kpi_sequence": self.kpi_sequence,
            "study_close_event_id": self.study_close_event_id,
            "study_close_record_id": self.study_close_record_id,
            "study_close_revision": self.study_close_revision,
            "study_id": self.study_id,
        }


@dataclass(frozen=True, slots=True)
class HistoricalKpiBackfillProof:
    """Git-authenticated proof of the one historical KPI backfill milestone."""

    event_id: str
    revision: int
    operation_id: str
    event_sha256: str
    sources: tuple[HistoricalKpiSource, ...]
    source_set_digest: str
    commit: str
    commit_parent: str
    commit_tree: str
    ancestry_anchor: str
    trailer_sha256: str
    path_blobs: tuple[CheckpointPathBlob, ...]

    @staticmethod
    def expected_source_set_digest(
        sources: Sequence[HistoricalKpiSource],
    ) -> str:
        return sha256(
            canonical_bytes([source.payload() for source in sources])
        ).hexdigest()

    @staticmethod
    def expected_trailer_sha256(event_id: str, revision: int) -> str:
        return sha256(
            (
                f"Axiom-Study-KPI-Backfill: {event_id}\n"
                f"Axiom-State-Revision: {revision}"
            ).encode("ascii")
        ).hexdigest()

    @classmethod
    def from_mapping(cls, value: object) -> "HistoricalKpiBackfillProof":
        expected = {
            "ancestry_anchor",
            "commit",
            "commit_parent",
            "commit_tree",
            "event_id",
            "event_sha256",
            "operation_id",
            "path_blobs",
            "revision",
            "source_set",
            "source_set_digest",
            "trailer_sha256",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise StudyCloseCheckpointError("historical backfill proof fields differ")
        source_values = value["source_set"]
        path_values = value["path_blobs"]
        if not isinstance(source_values, list) or not isinstance(path_values, list):
            raise StudyCloseCheckpointError("historical backfill proof lists differ")
        sources = tuple(HistoricalKpiSource.from_mapping(item) for item in source_values)
        path_blobs = tuple(CheckpointPathBlob.from_mapping(item) for item in path_values)
        event_id = _digest(value["event_id"], "historical backfill event id")
        revision = _integer(
            value["revision"], "historical backfill revision", minimum=1
        )
        proof = cls(
            event_id=event_id,
            revision=revision,
            operation_id=_identity(
                value["operation_id"], "historical backfill operation id"
            ),
            event_sha256=_digest(
                value["event_sha256"], "historical backfill event hash"
            ),
            sources=sources,
            source_set_digest=_digest(
                value["source_set_digest"], "historical backfill source-set hash"
            ),
            commit=_commit(value["commit"], "historical backfill commit"),
            commit_parent=_commit(
                value["commit_parent"], "historical backfill commit parent"
            ),
            commit_tree=_commit(
                value["commit_tree"], "historical backfill commit tree"
            ),
            ancestry_anchor=_commit(
                value["ancestry_anchor"], "historical backfill ancestry anchor"
            ),
            trailer_sha256=_digest(
                value["trailer_sha256"], "historical backfill trailer hash"
            ),
            path_blobs=path_blobs,
        )
        proof.validate()
        return proof

    def validate(self) -> None:
        if len(self.sources) != HISTORICAL_BACKFILL_ROW_COUNT:
            raise StudyCloseCheckpointError(
                "historical backfill must bind exactly 21 KPI records"
            )
        if [source.kpi_sequence for source in self.sources] != list(
            range(1, HISTORICAL_BACKFILL_ROW_COUNT + 1)
        ):
            raise StudyCloseCheckpointError(
                "historical backfill KPI sequence is not contiguous"
            )
        if len({source.study_id for source in self.sources}) != len(self.sources):
            raise StudyCloseCheckpointError(
                "historical backfill Study identities are not unique"
            )
        if len({source.kpi_record_id for source in self.sources}) != len(self.sources):
            raise StudyCloseCheckpointError(
                "historical backfill KPI record identities are not unique"
            )
        revisions = [source.study_close_revision for source in self.sources]
        if revisions != sorted(revisions) or len(set(revisions)) != len(revisions):
            raise StudyCloseCheckpointError(
                "historical backfill source revisions are not strictly monotone"
            )
        if revisions[-1] >= self.revision:
            raise StudyCloseCheckpointError(
                "historical backfill source does not precede the backfill event"
            )
        if self.source_set_digest != self.expected_source_set_digest(self.sources):
            raise StudyCloseCheckpointError(
                "historical backfill source-set digest differs"
            )
        if self.trailer_sha256 != self.expected_trailer_sha256(
            self.event_id, self.revision
        ):
            raise StudyCloseCheckpointError(
                "historical backfill trailer digest differs"
            )
        paths = [binding.path for binding in self.path_blobs]
        if paths != sorted(paths) or len(set(paths)) != len(paths):
            raise StudyCloseCheckpointError(
                "historical backfill path/blob bindings are not canonical"
            )
        required = {"state/control.json", "records/STUDY_KPI.md"}
        if not required.issubset(paths) or not any(
            path == "records/journal.jsonl"
            or (path.startswith("records/journal/") and path.endswith(".jsonl"))
            for path in paths
        ):
            raise StudyCloseCheckpointError(
                "historical backfill required path/blob binding is absent"
            )

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "ancestry_anchor": self.ancestry_anchor,
            "commit": self.commit,
            "commit_parent": self.commit_parent,
            "commit_tree": self.commit_tree,
            "event_id": self.event_id,
            "event_sha256": self.event_sha256,
            "operation_id": self.operation_id,
            "path_blobs": [binding.payload() for binding in self.path_blobs],
            "revision": self.revision,
            "source_set": [source.payload() for source in self.sources],
            "source_set_digest": self.source_set_digest,
            "trailer_sha256": self.trailer_sha256,
        }


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
    historical_kpi_backfill: HistoricalKpiBackfillProof | None = None
    schema: str = CHECKPOINT_SCHEMA
    validator_version: str | None = None

    def __post_init__(self) -> None:
        if self.validator_version is None:
            default = (
                "study_close_delivery_checkpoint.v1"
                if self.schema == LEGACY_CHECKPOINT_SCHEMA
                else CHECKPOINT_VALIDATOR_VERSION
            )
            object.__setattr__(self, "validator_version", default)

    def body(self) -> dict[str, Any]:
        if (
            self.schema not in _VALIDATORS_BY_SCHEMA
            or self.validator_version not in _VALIDATORS_BY_SCHEMA[self.schema]
        ):
            raise StudyCloseCheckpointError("checkpoint version differs")
        assert self.validator_version is not None
        body: dict[str, Any] = {
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
            "schema": self.schema,
            "validator_version": self.validator_version,
        }
        if self.schema == CHECKPOINT_SCHEMA:
            body["historical_kpi_backfill"] = (
                None
                if self.historical_kpi_backfill is None
                else self.historical_kpi_backfill.payload()
            )
        return body

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
        if not isinstance(value, dict):
            raise StudyCloseCheckpointError("checkpoint must be an object")
        schema = value.get("schema")
        if schema not in _VALIDATORS_BY_SCHEMA:
            raise StudyCloseCheckpointError("checkpoint version differs")
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
        if schema == CHECKPOINT_SCHEMA:
            expected.add("historical_kpi_backfill")
        if set(value) != expected:
            raise StudyCloseCheckpointError("checkpoint fields differ")
        if (
            value["validator_version"] not in _VALIDATORS_BY_SCHEMA[schema]
            or value["basis"] not in _BASES
        ):
            raise StudyCloseCheckpointError("checkpoint version or basis differs")
        if schema == LEGACY_CHECKPOINT_SCHEMA and value["basis"] in {
            "checkpoint_upgrade",
            "maintenance",
        }:
            raise StudyCloseCheckpointError("legacy checkpoint basis differs")
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
        if value["basis"] in {"full_audit", "checkpoint_upgrade", "maintenance"}:
            if last_event is not None or last_revision is not None:
                raise StudyCloseCheckpointError("non-close checkpoint close differs")
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
        if schema == CHECKPOINT_SCHEMA:
            if value["basis"] == "full_audit" and previous_commit is not None:
                raise StudyCloseCheckpointError(
                    "initial full-audit checkpoint has a predecessor"
                )
            if value["basis"] != "full_audit" and previous_commit is None:
                raise StudyCloseCheckpointError(
                    "advanced checkpoint predecessor is absent"
                )
        backfill_value = value.get("historical_kpi_backfill")
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
            historical_kpi_backfill=(
                None
                if backfill_value is None
                else HistoricalKpiBackfillProof.from_mapping(backfill_value)
            ),
            schema=schema,
            validator_version=value["validator_version"],
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


def validate_checkpoint_transition(
    previous: StudyCloseDeliveryCheckpoint,
    current: StudyCloseDeliveryCheckpoint,
    *,
    suffix_closes: Sequence[tuple[str, int]],
    current_kpi_sha256: str,
) -> None:
    """Validate one v2 high-water transition from independently derived facts."""

    _digest(current_kpi_sha256, "current KPI hash")
    if current.schema != CHECKPOINT_SCHEMA:
        raise StudyCloseCheckpointError("new checkpoint is not v2")
    if current.validator_version not in _VALIDATORS_BY_SCHEMA[CHECKPOINT_SCHEMA]:
        raise StudyCloseCheckpointError("new checkpoint validator differs")
    if (
        previous.validator_version == CHECKPOINT_VALIDATOR_VERSION
        and current.validator_version != CHECKPOINT_VALIDATOR_VERSION
    ):
        raise StudyCloseCheckpointError("checkpoint validator version regressed")
    if current.cursor.sequence < previous.cursor.sequence:
        raise StudyCloseCheckpointError("checkpoint Journal cursor regressed")
    if current.cursor.next_offset < previous.cursor.next_offset:
        raise StudyCloseCheckpointError("checkpoint Journal byte cursor regressed")
    if current.historical_kpi_backfill != previous.historical_kpi_backfill:
        if previous.schema != LEGACY_CHECKPOINT_SCHEMA:
            raise StudyCloseCheckpointError(
                "historical KPI backfill proof changed after v2 activation"
            )
    if current.kpi_sha256 != current_kpi_sha256:
        raise StudyCloseCheckpointError("checkpoint KPI hash differs")

    if current.basis == "study_close":
        if len(suffix_closes) != 1:
            raise StudyCloseCheckpointError(
                "Study-close checkpoint must advance by exactly one close"
            )
        event_id, revision = suffix_closes[0]
        if (
            current.last_study_close_event_id != event_id
            or current.last_study_close_revision != revision
            or current.cursor.event_id != event_id
            or current.cursor.sequence != revision
        ):
            raise StudyCloseCheckpointError(
                "Study-close checkpoint cursor and last close differ"
            )
        if revision <= previous.cursor.sequence:
            raise StudyCloseCheckpointError(
                "Study-close checkpoint revision is not monotone"
            )
        if current.prospective_close_count != previous.prospective_close_count + 1:
            raise StudyCloseCheckpointError(
                "Study-close checkpoint count did not advance by one"
            )
        expected_chain = advance_close_chain(
            previous.prospective_close_chain_digest, event_id, revision
        )
        if current.prospective_close_chain_digest != expected_chain:
            raise StudyCloseCheckpointError(
                "Study-close checkpoint chain did not advance exactly"
            )
        if current.validator_version == CHECKPOINT_VALIDATOR_VERSION and (
            previous.validator_version != CHECKPOINT_VALIDATOR_VERSION
        ):
            raise StudyCloseCheckpointError(
                "bounded Study close requires explicit checkpoint maintenance"
            )
        if (
            current.validator_version == CHECKPOINT_VALIDATOR_VERSION
            and current.kpi_sha256 != previous.kpi_sha256
        ):
            raise StudyCloseCheckpointError(
                "routine Study close changed the explicit KPI materialization"
            )
        return

    if current.basis not in {"checkpoint_upgrade", "maintenance"}:
        raise StudyCloseCheckpointError("checkpoint transition basis differs")
    if suffix_closes:
        raise StudyCloseCheckpointError(
            "non-close checkpoint cannot absorb an unauthenticated Study close"
        )
    if (
        current.last_study_close_event_id is not None
        or current.last_study_close_revision is not None
    ):
        raise StudyCloseCheckpointError("non-close checkpoint has a last close")
    if (
        current.prospective_close_count != previous.prospective_close_count
        or current.prospective_close_chain_digest
        != previous.prospective_close_chain_digest
    ):
        raise StudyCloseCheckpointError(
            "non-close checkpoint changed the close chain"
        )
    if current.basis == "checkpoint_upgrade":
        if previous.schema != LEGACY_CHECKPOINT_SCHEMA:
            raise StudyCloseCheckpointError(
                "checkpoint upgrade requires the legacy checkpoint"
            )
        return
    if previous.schema != CHECKPOINT_SCHEMA:
        raise StudyCloseCheckpointError("checkpoint maintenance requires v2")
    if (
        current.cursor.sequence == previous.cursor.sequence
        and current.cursor.next_offset == previous.cursor.next_offset
        and current.kpi_sha256 == previous.kpi_sha256
        and current.validator_version == previous.validator_version
    ):
        raise StudyCloseCheckpointError(
            "checkpoint maintenance did not advance its Journal cursor or "
            "navigation projection"
        )


def validate_no_close_suffix(
    checkpoint: StudyCloseDeliveryCheckpoint,
    *,
    suffix_closes: Sequence[tuple[str, int]],
    current_cursor: JournalDeliveryCursor,
    current_kpi_sha256: str,
) -> None:
    """Validate a routine no-close suffix against authenticated high-water.

    ``current_kpi_sha256`` is the digest of the last explicit Markdown
    materialization recorded by the checkpoint.  Routine callers inherit that
    authenticated value; they do not re-read the lag-tolerant navigation file.
    """

    if suffix_closes:
        raise StudyCloseCheckpointError(
            "Study close exists after the tracked delivery checkpoint"
        )
    if current_cursor.sequence < checkpoint.cursor.sequence:
        raise StudyCloseCheckpointError("current Journal cursor regressed")
    if current_cursor.next_offset < checkpoint.cursor.next_offset:
        raise StudyCloseCheckpointError("current Journal byte cursor regressed")
    if _digest(current_kpi_sha256, "current KPI hash") != checkpoint.kpi_sha256:
        raise StudyCloseCheckpointError(
            "current KPI changed across a no-close Journal suffix"
        )


__all__ = [
    "CHECKPOINT_PATH",
    "CHECKPOINT_SCHEMA",
    "CHECKPOINT_VALIDATOR_VERSION",
    "CheckpointPathBlob",
    "EMPTY_CLOSE_CHAIN_DIGEST",
    "HISTORICAL_BACKFILL_ROW_COUNT",
    "HistoricalKpiBackfillProof",
    "HistoricalKpiSource",
    "JournalDeliveryCursor",
    "LEGACY_CHECKPOINT_SCHEMA",
    "LEGACY_V2_CHECKPOINT_VALIDATOR_VERSION",
    "StudyCloseCheckpointError",
    "StudyCloseDeliveryCheckpoint",
    "advance_close_chain",
    "validate_checkpoint_transition",
    "validate_no_close_suffix",
]
