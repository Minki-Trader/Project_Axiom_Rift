"""Content-addressed correction plans and unpublished Git delivery guards.

The immutable plan core binds the baseline, reviewed code and evidence, and
every ordered action/binding.  Its SHA-256 derives every operation id.  Exact
receipts are produced only after those ids are fixed and are sealed with the
entire core in a separate final plan artifact.  This explicit core/envelope
split avoids a plan-hash -> operation-id -> event -> receipt -> plan-hash cycle.
The module is read-only; a project-specific orchestrator owns StateWriter calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.storage.journal import DurableJournal


RECEIPT_ENVELOPE_SCHEMA = "content_addressed_correction_receipt_envelope.v1"
PLAN_CORE_SCHEMA = "correction_plan_core.v1"
BASELINE_SCHEMA = "content_addressed_correction_baseline.v3"
AUTHORITY_FILE_SCHEMA = "content_addressed_authority_file_binding.v1"
EVIDENCE_BINDING_SCHEMA = "content_addressed_correction_evidence_binding.v1"
CODE_CHECKPOINT_FILE_SCHEMA = "content_addressed_code_checkpoint_file_binding.v1"
EXECUTION_FILE_SCHEMA = "content_addressed_correction_execution_file_binding.v1"
EVENT_RECEIPT_SCHEMA = "content_addressed_correction_event_receipt_binding.v2"
EVENT_INTENT_SCHEMA = "content_addressed_correction_event_intent.v3"
OPERATION_ID_RULE = "<namespace>-<core_sha256>-<ordinal_2d>"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_GIT_OBJECT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_NAME = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_UTC = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z\Z"
)
_JOURNAL_EVENT_FIELDS = {
    "control",
    "event_id",
    "event_kind",
    "index_projection_digest",
    "index_record_count",
    "index_records",
    "journal_offset",
    "occurred_at_utc",
    "operation_id",
    "payload",
    "previous_event_id",
    "schema",
    "sequence",
    "subject",
}
_EXECUTION_SUFFIXES = frozenset(
    {".dll", ".pyc", ".pyd", ".py", ".pyi", ".so"}
)


class ContentAddressedCorrectionError(RuntimeError):
    """A plan, Journal prefix, or Git delivery boundary is not exact."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ContentAddressedCorrectionError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if _DIGEST.fullmatch(text) is None:
        raise ContentAddressedCorrectionError(f"{name} must be a SHA-256 digest")
    return text


def _git_object(name: str, value: object) -> str:
    text = _ascii(name, value)
    if _GIT_OBJECT.fullmatch(text) is None:
        raise ContentAddressedCorrectionError(f"{name} must be a Git object id")
    return text


def _integer(name: str, value: object, *, positive: bool = False) -> int:
    floor = 1 if positive else 0
    if type(value) is not int or value < floor:
        raise ContentAddressedCorrectionError(f"{name} must be >= {floor}")
    return value


def _relative(name: str, value: object) -> str:
    text = _ascii(name, value)
    if (
        "\\" in text
        or ":" in text
        or any(part in {"", ".", ".."} for part in text.split("/"))
    ):
        raise ContentAddressedCorrectionError(f"{name} is not normalized")
    return text


def _utc(name: str, value: object) -> str:
    text = _ascii(name, value)
    if _UTC.fullmatch(text) is None:
        raise ContentAddressedCorrectionError(f"{name} must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ContentAddressedCorrectionError(f"{name} is invalid UTC") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ContentAddressedCorrectionError(f"{name} is not UTC")
    return text


def _mapping(name: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContentAddressedCorrectionError(f"{name} must be a mapping")
    try:
        normalized = parse_canonical(canonical_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise ContentAddressedCorrectionError(f"{name} is not canonical") from exc
    if not isinstance(normalized, dict):
        raise ContentAddressedCorrectionError(f"{name} is not a mapping")
    return normalized


def _exact(value: object, *, schema: str, keys: set[str]) -> Mapping[str, Any]:
    if (
        not isinstance(value, Mapping)
        or value.get("schema") != schema
        or set(value) != keys | {"schema"}
    ):
        raise ContentAddressedCorrectionError(f"{schema} payload is malformed")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectionBaseline:
    control_revision: int
    journal_sequence: int
    journal_event_id: str
    journal_path: str
    control_sha256: str
    journal_sha256: str
    journal_start_offset: int
    journal_size_bytes: int
    authority_manifest_digest: str
    index_record_count: int
    index_projection_digest: str
    mission_id: str
    initiative_id: str
    next_action_kind: str
    code_checkpoint_commit: str
    code_checkpoint_tree: str
    origin_main_commit: str
    journal_manifest_sha256: str | None = None

    def __post_init__(self) -> None:
        _integer("control revision", self.control_revision, positive=True)
        _integer("Journal sequence", self.journal_sequence, positive=True)
        _digest("Journal event", self.journal_event_id)
        path = _relative("Journal path", self.journal_path)
        if path != "records/journal.jsonl" and not path.startswith("records/journal/"):
            raise ContentAddressedCorrectionError("Journal path is outside records")
        _digest("control hash", self.control_sha256)
        _digest("Journal hash", self.journal_sha256)
        _integer("Journal start offset", self.journal_start_offset)
        _integer("Journal bytes", self.journal_size_bytes)
        _digest("authority manifest", self.authority_manifest_digest)
        _integer("index count", self.index_record_count, positive=True)
        _digest("index projection", self.index_projection_digest)
        if not _ascii("Mission", self.mission_id).startswith("MIS-"):
            raise ContentAddressedCorrectionError("Mission id is malformed")
        if not _ascii("Initiative", self.initiative_id).startswith("INI-"):
            raise ContentAddressedCorrectionError("Initiative id is malformed")
        _ascii("next action", self.next_action_kind)
        _git_object("code checkpoint commit", self.code_checkpoint_commit)
        _git_object("code checkpoint tree", self.code_checkpoint_tree)
        _git_object("origin/main commit", self.origin_main_commit)
        if self.journal_manifest_sha256 is not None:
            _digest("Journal manifest", self.journal_manifest_sha256)

    def to_payload(self) -> dict[str, Any]:
        return {
            "authority_manifest_digest": self.authority_manifest_digest,
            "code_checkpoint_commit": self.code_checkpoint_commit,
            "code_checkpoint_tree": self.code_checkpoint_tree,
            "control_revision": self.control_revision,
            "control_sha256": self.control_sha256,
            "index_projection_digest": self.index_projection_digest,
            "index_record_count": self.index_record_count,
            "initiative_id": self.initiative_id,
            "journal_event_id": self.journal_event_id,
            "journal_manifest_sha256": self.journal_manifest_sha256,
            "journal_path": self.journal_path,
            "journal_sequence": self.journal_sequence,
            "journal_sha256": self.journal_sha256,
            "journal_start_offset": self.journal_start_offset,
            "journal_size_bytes": self.journal_size_bytes,
            "mission_id": self.mission_id,
            "next_action_kind": self.next_action_kind,
            "origin_main_commit": self.origin_main_commit,
            "schema": BASELINE_SCHEMA,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "CorrectionBaseline":
        keys = set(cls.__dataclass_fields__) - {"journal_manifest_sha256"}
        keys.add("journal_manifest_sha256")
        item = _exact(value, schema=BASELINE_SCHEMA, keys=keys)
        return cls(**{name: item[name] for name in keys})  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True, order=True, kw_only=True)
class AuthorityFileBinding:
    path: str
    predecessor_sha256: str
    prospective_sha256: str

    def __post_init__(self) -> None:
        _relative("authority path", self.path)
        _digest("predecessor authority hash", self.predecessor_sha256)
        _digest("prospective authority hash", self.prospective_sha256)

    @property
    def changed(self) -> bool:
        return self.predecessor_sha256 != self.prospective_sha256

    def to_payload(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "path": self.path,
            "predecessor_sha256": self.predecessor_sha256,
            "prospective_sha256": self.prospective_sha256,
            "schema": AUTHORITY_FILE_SCHEMA,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "AuthorityFileBinding":
        item = _exact(
            value,
            schema=AUTHORITY_FILE_SCHEMA,
            keys={"changed", "path", "predecessor_sha256", "prospective_sha256"},
        )
        result = cls(
            path=item["path"],  # type: ignore[arg-type]
            predecessor_sha256=item["predecessor_sha256"],  # type: ignore[arg-type]
            prospective_sha256=item["prospective_sha256"],  # type: ignore[arg-type]
        )
        if item["changed"] is not result.changed:
            raise ContentAddressedCorrectionError("authority changed marker is false")
        return result


@dataclass(frozen=True, slots=True, order=True, kw_only=True)
class CorrectionEvidenceBinding:
    role: str
    sha256: str

    def __post_init__(self) -> None:
        if _NAME.fullmatch(_ascii("evidence role", self.role)) is None:
            raise ContentAddressedCorrectionError("evidence role is not canonical")
        _digest("evidence hash", self.sha256)

    def to_payload(self) -> dict[str, str]:
        return {"role": self.role, "schema": EVIDENCE_BINDING_SCHEMA, "sha256": self.sha256}

    @classmethod
    def from_mapping(cls, value: object) -> "CorrectionEvidenceBinding":
        item = _exact(value, schema=EVIDENCE_BINDING_SCHEMA, keys={"role", "sha256"})
        return cls(role=item["role"], sha256=item["sha256"])  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True, order=True, kw_only=True)
class CodeCheckpointFileBinding:
    path: str
    change_kind: str
    predecessor_sha256: str | None
    checkpoint_sha256: str | None

    def __post_init__(self) -> None:
        _relative("code checkpoint path", self.path)
        if self.change_kind not in {"added", "deleted", "modified", "type-changed"}:
            raise ContentAddressedCorrectionError(
                "code checkpoint change kind is invalid"
            )
        if self.predecessor_sha256 is not None:
            _digest("predecessor code hash", self.predecessor_sha256)
        if self.checkpoint_sha256 is not None:
            _digest("checkpoint code hash", self.checkpoint_sha256)
        if (
            (self.change_kind == "added")
            != (self.predecessor_sha256 is None and self.checkpoint_sha256 is not None)
            or (self.change_kind == "deleted")
            != (self.predecessor_sha256 is not None and self.checkpoint_sha256 is None)
            or (
                self.change_kind in {"modified", "type-changed"}
                and (
                    self.predecessor_sha256 is None
                    or self.checkpoint_sha256 is None
                    or self.predecessor_sha256 == self.checkpoint_sha256
                )
            )
        ):
            raise ContentAddressedCorrectionError(
                "code checkpoint hashes do not match the change kind"
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "change_kind": self.change_kind,
            "checkpoint_sha256": self.checkpoint_sha256,
            "path": self.path,
            "predecessor_sha256": self.predecessor_sha256,
            "schema": CODE_CHECKPOINT_FILE_SCHEMA,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "CodeCheckpointFileBinding":
        item = _exact(
            value,
            schema=CODE_CHECKPOINT_FILE_SCHEMA,
            keys={
                "change_kind",
                "checkpoint_sha256",
                "path",
                "predecessor_sha256",
            },
        )
        return cls(
            path=item["path"],  # type: ignore[arg-type]
            change_kind=item["change_kind"],  # type: ignore[arg-type]
            predecessor_sha256=item["predecessor_sha256"],  # type: ignore[arg-type]
            checkpoint_sha256=item["checkpoint_sha256"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True, order=True, kw_only=True)
class CorrectionExecutionFileBinding:
    path: str
    sha256: str

    def __post_init__(self) -> None:
        _relative("execution file path", self.path)
        _digest("execution file hash", self.sha256)

    def to_payload(self) -> dict[str, str]:
        return {
            "path": self.path,
            "schema": EXECUTION_FILE_SCHEMA,
            "sha256": self.sha256,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "CorrectionExecutionFileBinding":
        item = _exact(value, schema=EXECUTION_FILE_SCHEMA, keys={"path", "sha256"})
        return cls(path=item["path"], sha256=item["sha256"])  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectionEventReceiptBinding:
    canonical_event_byte_count: int
    canonical_event_sha256: str
    event_id: str
    occurred_at_utc: str
    journal_offset: int
    event_payload_sha256: str
    control_projection_sha256: str
    operation_result_sha256: str
    semantic_index_records_sha256: str
    semantic_index_record_count: int

    def __post_init__(self) -> None:
        size = _integer(
            "canonical event byte count",
            self.canonical_event_byte_count,
            positive=True,
        )
        if size > DurableJournal.MAX_EVENT_BYTES:
            raise ContentAddressedCorrectionError(
                "canonical event byte count exceeds the Journal limit"
            )
        _digest("canonical event receipt", self.canonical_event_sha256)
        _digest("event id receipt", self.event_id)
        _utc("event occurred UTC receipt", self.occurred_at_utc)
        _integer("event Journal offset receipt", self.journal_offset)
        _digest("event payload receipt", self.event_payload_sha256)
        _digest("control projection receipt", self.control_projection_sha256)
        _digest("operation result receipt", self.operation_result_sha256)
        _digest("semantic index receipt", self.semantic_index_records_sha256)
        _integer("semantic index record count", self.semantic_index_record_count)

    def to_payload(self) -> dict[str, Any]:
        return {
            "canonical_event_byte_count": self.canonical_event_byte_count,
            "canonical_event_sha256": self.canonical_event_sha256,
            "control_projection_sha256": self.control_projection_sha256,
            "event_id": self.event_id,
            "event_payload_sha256": self.event_payload_sha256,
            "journal_offset": self.journal_offset,
            "occurred_at_utc": self.occurred_at_utc,
            "operation_result_sha256": self.operation_result_sha256,
            "schema": EVENT_RECEIPT_SCHEMA,
            "semantic_index_record_count": self.semantic_index_record_count,
            "semantic_index_records_sha256": self.semantic_index_records_sha256,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "CorrectionEventReceiptBinding":
        item = _exact(
            value,
            schema=EVENT_RECEIPT_SCHEMA,
            keys={
                "control_projection_sha256",
                "canonical_event_byte_count",
                "canonical_event_sha256",
                "event_id",
                "event_payload_sha256",
                "journal_offset",
                "occurred_at_utc",
                "operation_result_sha256",
                "semantic_index_record_count",
                "semantic_index_records_sha256",
            },
        )
        return cls(
            canonical_event_byte_count=item["canonical_event_byte_count"],  # type: ignore[arg-type]
            canonical_event_sha256=item["canonical_event_sha256"],  # type: ignore[arg-type]
            event_id=item["event_id"],  # type: ignore[arg-type]
            occurred_at_utc=item["occurred_at_utc"],  # type: ignore[arg-type]
            journal_offset=item["journal_offset"],  # type: ignore[arg-type]
            event_payload_sha256=item["event_payload_sha256"],  # type: ignore[arg-type]
            control_projection_sha256=item["control_projection_sha256"],  # type: ignore[arg-type]
            operation_result_sha256=item["operation_result_sha256"],  # type: ignore[arg-type]
            semantic_index_records_sha256=item["semantic_index_records_sha256"],  # type: ignore[arg-type]
            semantic_index_record_count=item["semantic_index_record_count"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectionEventIntent:
    action: str
    event_kind: str
    subject: str
    binding: Mapping[str, Any]

    def __post_init__(self) -> None:
        if _NAME.fullmatch(_ascii("event action", self.action)) is None:
            raise ContentAddressedCorrectionError("event action is not canonical")
        _ascii("event kind", self.event_kind)
        _ascii("event subject", self.subject)
        object.__setattr__(self, "binding", _mapping("event binding", self.binding))

    @property
    def binding_sha256(self) -> str:
        return sha256(canonical_bytes(dict(self.binding))).hexdigest()

    def to_payload(self, ordinal: int) -> dict[str, Any]:
        return {
            "action": self.action,
            "binding": dict(self.binding),
            "binding_sha256": self.binding_sha256,
            "event_kind": self.event_kind,
            "ordinal": ordinal,
            "schema": EVENT_INTENT_SCHEMA,
            "subject": self.subject,
        }

    @classmethod
    def from_mapping(cls, value: object, ordinal: int) -> "CorrectionEventIntent":
        item = _exact(
            value,
            schema=EVENT_INTENT_SCHEMA,
            keys={
                "action", "binding", "binding_sha256", "event_kind", "ordinal",
                "subject",
            },
        )
        if item["ordinal"] != ordinal:
            raise ContentAddressedCorrectionError("event intent is out of order")
        result = cls(
            action=item["action"],  # type: ignore[arg-type]
            event_kind=item["event_kind"],  # type: ignore[arg-type]
            subject=item["subject"],  # type: ignore[arg-type]
            binding=item["binding"],  # type: ignore[arg-type]
        )
        if item["binding_sha256"] != result.binding_sha256:
            raise ContentAddressedCorrectionError("event binding hash is invalid")
        return result


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedCorrectionEvent:
    ordinal: int
    action: str
    event_kind: str
    subject: str
    operation_id: str
    binding: Mapping[str, Any]
    binding_sha256: str
    receipt: CorrectionEventReceiptBinding | None = None

    def prefix_tuple(self) -> tuple[str, str, str]:
        return self.operation_id, self.event_kind, self.subject

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "action": self.action,
            "binding": dict(self.binding),
            "binding_sha256": self.binding_sha256,
            "event_kind": self.event_kind,
            "operation_id": self.operation_id,
            "ordinal": self.ordinal,
            "subject": self.subject,
        }
        if self.receipt is not None:
            payload["receipt"] = self.receipt.to_payload()
        return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectionPlanCore:
    operation_namespace: str
    baseline: CorrectionBaseline
    prospective_authority_manifest_digest: str
    authority_files: tuple[AuthorityFileBinding, ...]
    code_checkpoint_files: tuple[CodeCheckpointFileBinding, ...]
    execution_files: tuple[CorrectionExecutionFileBinding, ...]
    evidence_bindings: tuple[CorrectionEvidenceBinding, ...]
    event_intents: tuple[CorrectionEventIntent, ...]
    purpose: str
    core_hash: str = field(init=False)
    _core_bytes: bytes = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if _NAME.fullmatch(_ascii("operation namespace", self.operation_namespace)) is None:
            raise ContentAddressedCorrectionError("operation namespace is invalid")
        if not isinstance(self.baseline, CorrectionBaseline):
            raise ContentAddressedCorrectionError("baseline is not typed")
        _digest("prospective authority", self.prospective_authority_manifest_digest)
        authority = tuple(sorted(self.authority_files, key=lambda item: item.path))
        checkpoint = tuple(sorted(self.code_checkpoint_files, key=lambda item: item.path))
        execution = tuple(sorted(self.execution_files, key=lambda item: item.path))
        evidence = tuple(sorted(self.evidence_bindings, key=lambda item: item.role))
        events = tuple(self.event_intents)
        authority_bytes_change = any(item.changed for item in authority)
        authority_manifest_change = (
            self.prospective_authority_manifest_digest
            != self.baseline.authority_manifest_digest
        )
        if (
            not authority
            or len({item.path for item in authority}) != len(authority)
            or not all(isinstance(item, AuthorityFileBinding) for item in authority)
            or authority_bytes_change != authority_manifest_change
        ):
            raise ContentAddressedCorrectionError("authority inventory is not exact")
        if (
            len({item.path for item in checkpoint}) != len(checkpoint)
            or not all(isinstance(item, CodeCheckpointFileBinding) for item in checkpoint)
        ):
            raise ContentAddressedCorrectionError(
                "code checkpoint inventory is not exact"
            )
        if (
            not execution
            or len({item.path for item in execution}) != len(execution)
            or not all(
                isinstance(item, CorrectionExecutionFileBinding)
                for item in execution
            )
        ):
            raise ContentAddressedCorrectionError("execution inventory is not exact")
        if (
            not evidence
            or len({item.role for item in evidence}) != len(evidence)
            or not all(isinstance(item, CorrectionEvidenceBinding) for item in evidence)
        ):
            raise ContentAddressedCorrectionError("evidence inventory is not exact")
        if (
            not events
            or len(events) > 99
            or len({item.action for item in events}) != len(events)
            or not all(isinstance(item, CorrectionEventIntent) for item in events)
        ):
            raise ContentAddressedCorrectionError("event inventory is not exact")
        _ascii("plan purpose", self.purpose)
        object.__setattr__(self, "authority_files", authority)
        object.__setattr__(self, "code_checkpoint_files", checkpoint)
        object.__setattr__(self, "execution_files", execution)
        object.__setattr__(self, "evidence_bindings", evidence)
        object.__setattr__(self, "event_intents", events)
        document = canonical_bytes(self.to_payload())
        object.__setattr__(self, "_core_bytes", document)
        object.__setattr__(self, "core_hash", sha256(document).hexdigest())

    @property
    def core_bytes(self) -> bytes:
        return self._core_bytes

    @property
    def identity(self) -> str:
        return f"correction-plan-core:{self.core_hash}"

    @property
    def event_count(self) -> int:
        return len(self.event_intents)

    @property
    def authority_replacements(self) -> tuple[AuthorityFileBinding, ...]:
        return tuple(item for item in self.authority_files if item.changed)

    @property
    def events(self) -> tuple[ResolvedCorrectionEvent, ...]:
        return tuple(
            ResolvedCorrectionEvent(
                ordinal=ordinal,
                action=intent.action,
                event_kind=intent.event_kind,
                subject=intent.subject,
                operation_id=self.operation_id(ordinal),
                binding=intent.binding,
                binding_sha256=intent.binding_sha256,
            )
            for ordinal, intent in enumerate(self.event_intents, 1)
        )

    def event(self, action: str) -> ResolvedCorrectionEvent:
        found = tuple(item for item in self.events if item.action == action)
        if len(found) != 1:
            raise KeyError(action)
        return found[0]

    def operation_id(self, ordinal: int) -> str:
        if type(ordinal) is not int or ordinal < 1 or ordinal > self.event_count:
            raise ContentAddressedCorrectionError("event ordinal is outside the core")
        return f"{self.operation_namespace}-{self.core_hash}-{ordinal:02d}"

    def intent(self, action: str) -> CorrectionEventIntent:
        found = tuple(item for item in self.event_intents if item.action == action)
        if len(found) != 1:
            raise KeyError(action)
        return found[0]

    def to_payload(self) -> dict[str, Any]:
        return {
            "authority_files": [item.to_payload() for item in self.authority_files],
            "baseline": self.baseline.to_payload(),
            "code_checkpoint_files": [
                item.to_payload() for item in self.code_checkpoint_files
            ],
            "event_count": len(self.event_intents),
            "event_intents": [item.to_payload(n) for n, item in enumerate(self.event_intents, 1)],
            "evidence_bindings": [item.to_payload() for item in self.evidence_bindings],
            "execution_files": [item.to_payload() for item in self.execution_files],
            "operation_id_rule": OPERATION_ID_RULE,
            "operation_namespace": self.operation_namespace,
            "prospective_authority_manifest_digest": self.prospective_authority_manifest_digest,
            "purpose": self.purpose,
            "schema": PLAN_CORE_SCHEMA,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "CorrectionPlanCore":
        item = _exact(
            value,
            schema=PLAN_CORE_SCHEMA,
            keys={
                "authority_files", "baseline", "code_checkpoint_files",
                "event_count", "event_intents", "evidence_bindings",
                "execution_files", "operation_id_rule", "operation_namespace",
                "prospective_authority_manifest_digest", "purpose",
            },
        )
        if item["operation_id_rule"] != OPERATION_ID_RULE:
            raise ContentAddressedCorrectionError("operation-id rule is foreign")
        raw_events = item["event_intents"]
        if not isinstance(raw_events, list):
            raise ContentAddressedCorrectionError("event intents are malformed")
        events = tuple(
            CorrectionEventIntent.from_mapping(raw, n)
            for n, raw in enumerate(raw_events, 1)
        )
        if item["event_count"] != len(events):
            raise ContentAddressedCorrectionError("event count is caller-authored")
        return cls(
            operation_namespace=item["operation_namespace"],  # type: ignore[arg-type]
            baseline=CorrectionBaseline.from_mapping(item["baseline"]),
            prospective_authority_manifest_digest=item["prospective_authority_manifest_digest"],  # type: ignore[arg-type]
            authority_files=tuple(AuthorityFileBinding.from_mapping(raw) for raw in item["authority_files"]),  # type: ignore[union-attr]
            code_checkpoint_files=tuple(
                CodeCheckpointFileBinding.from_mapping(raw)
                for raw in item["code_checkpoint_files"]  # type: ignore[union-attr]
            ),
            execution_files=tuple(
                CorrectionExecutionFileBinding.from_mapping(raw)
                for raw in item["execution_files"]  # type: ignore[union-attr]
            ),
            evidence_bindings=tuple(CorrectionEvidenceBinding.from_mapping(raw) for raw in item["evidence_bindings"]),  # type: ignore[union-attr]
            event_intents=events,
            purpose=item["purpose"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_bytes(
        cls,
        document: bytes,
        *,
        expected_core_hash: str | None = None,
    ) -> "CorrectionPlanCore":
        if expected_core_hash is not None:
            _digest("expected correction core", expected_core_hash)
            if sha256(document).hexdigest() != expected_core_hash:
                raise ContentAddressedCorrectionError(
                    "correction core differs from its expected identity"
                )
        try:
            value = parse_canonical(document)
        except (TypeError, ValueError) as exc:
            raise ContentAddressedCorrectionError("core is not canonical") from exc
        core = cls.from_mapping(value)
        if core.core_bytes != document:
            raise ContentAddressedCorrectionError("core changed on rebuild")
        return core

    @classmethod
    def hash_from_operation_id(cls, operation_id: str, *, namespace: str) -> str:
        prefix = f"{namespace}-"
        remainder = operation_id.removeprefix(prefix) if operation_id.startswith(prefix) else ""
        digest, separator, ordinal = remainder.rpartition("-")
        if separator != "-" or _DIGEST.fullmatch(digest) is None or not re.fullmatch(r"[0-9]{2}", ordinal) or ordinal == "00":
            raise ContentAddressedCorrectionError("operation id does not bind a core")
        return digest


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectionReceiptEnvelope:
    core: CorrectionPlanCore
    event_receipts: tuple[CorrectionEventReceiptBinding, ...]
    artifact_hash: str = field(init=False)
    _artifact_bytes: bytes = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.core, CorrectionPlanCore):
            raise ContentAddressedCorrectionError("correction core is not typed")
        receipts = tuple(self.event_receipts)
        if (
            len(receipts) != self.core.event_count
            or not all(
                isinstance(item, CorrectionEventReceiptBinding) for item in receipts
            )
        ):
            raise ContentAddressedCorrectionError(
                "receipt inventory does not match the correction core"
            )
        object.__setattr__(self, "event_receipts", receipts)
        document = canonical_bytes(self.to_payload())
        object.__setattr__(self, "_artifact_bytes", document)
        object.__setattr__(self, "artifact_hash", sha256(document).hexdigest())

    @property
    def artifact_bytes(self) -> bytes:
        return self._artifact_bytes

    @property
    def core_hash(self) -> str:
        return self.core.core_hash

    @property
    def identity(self) -> str:
        return f"correction-receipt-envelope:{self.artifact_hash}"

    @property
    def operation_namespace(self) -> str:
        return self.core.operation_namespace

    @property
    def baseline(self) -> CorrectionBaseline:
        return self.core.baseline

    @property
    def prospective_authority_manifest_digest(self) -> str:
        return self.core.prospective_authority_manifest_digest

    @property
    def authority_files(self) -> tuple[AuthorityFileBinding, ...]:
        return self.core.authority_files

    @property
    def authority_replacements(self) -> tuple[AuthorityFileBinding, ...]:
        return self.core.authority_replacements

    @property
    def code_checkpoint_files(self) -> tuple[CodeCheckpointFileBinding, ...]:
        return self.core.code_checkpoint_files

    @property
    def execution_files(self) -> tuple[CorrectionExecutionFileBinding, ...]:
        return self.core.execution_files

    @property
    def evidence_bindings(self) -> tuple[CorrectionEvidenceBinding, ...]:
        return self.core.evidence_bindings

    @property
    def event_count(self) -> int:
        return self.core.event_count

    @property
    def purpose(self) -> str:
        return self.core.purpose

    @property
    def events(self) -> tuple[ResolvedCorrectionEvent, ...]:
        return tuple(
            ResolvedCorrectionEvent(
                ordinal=ordinal,
                action=intent.action,
                event_kind=intent.event_kind,
                subject=intent.subject,
                operation_id=self.core.operation_id(ordinal),
                binding=intent.binding,
                binding_sha256=intent.binding_sha256,
                receipt=receipt,
            )
            for ordinal, (intent, receipt) in enumerate(
                zip(self.core.event_intents, self.event_receipts),
                1,
            )
        )

    def event(self, action: str) -> ResolvedCorrectionEvent:
        found = tuple(item for item in self.events if item.action == action)
        if len(found) != 1:
            raise KeyError(action)
        return found[0]

    def to_payload(self) -> dict[str, Any]:
        return {
            "core": self.core.to_payload(),
            "core_hash": self.core_hash,
            "event_count": self.event_count,
            "event_receipts": [
                {"ordinal": ordinal, "receipt": receipt.to_payload()}
                for ordinal, receipt in enumerate(self.event_receipts, 1)
            ],
            "schema": RECEIPT_ENVELOPE_SCHEMA,
        }

    @classmethod
    def from_bytes(
        cls,
        document: bytes,
        *,
        expected_artifact_hash: str | None = None,
        expected_core_hash: str | None = None,
    ) -> "CorrectionReceiptEnvelope":
        if expected_artifact_hash is not None:
            _digest("expected plan artifact", expected_artifact_hash)
            if sha256(document).hexdigest() != expected_artifact_hash:
                raise ContentAddressedCorrectionError(
                    "final plan differs from its expected artifact identity"
                )
        try:
            value = parse_canonical(document)
        except (TypeError, ValueError) as exc:
            raise ContentAddressedCorrectionError("plan is not canonical") from exc
        item = _exact(
            value,
            schema=RECEIPT_ENVELOPE_SCHEMA,
            keys={"core", "core_hash", "event_count", "event_receipts"},
        )
        core = CorrectionPlanCore.from_mapping(item["core"])
        if item["core_hash"] != core.core_hash:
            raise ContentAddressedCorrectionError("plan core hash is invalid")
        if expected_core_hash is not None and core.core_hash != _digest(
            "expected correction core", expected_core_hash
        ):
            raise ContentAddressedCorrectionError(
                "final plan binds a foreign correction core"
            )
        raw_receipts = item["event_receipts"]
        if not isinstance(raw_receipts, list):
            raise ContentAddressedCorrectionError("event receipts are malformed")
        receipts: list[CorrectionEventReceiptBinding] = []
        for ordinal, raw in enumerate(raw_receipts, 1):
            entry = raw
            if (
                not isinstance(entry, Mapping)
                or set(entry) != {"ordinal", "receipt"}
                or entry.get("ordinal") != ordinal
            ):
                raise ContentAddressedCorrectionError(
                    "event receipt envelope is out of order"
                )
            receipts.append(
                CorrectionEventReceiptBinding.from_mapping(entry["receipt"])
            )
        if item["event_count"] != core.event_count or len(receipts) != core.event_count:
            raise ContentAddressedCorrectionError(
                "final plan event count differs from its core"
            )
        plan = cls(core=core, event_receipts=tuple(receipts))
        if plan.artifact_bytes != document:
            raise ContentAddressedCorrectionError("plan changed on rebuild")
        return plan

    @classmethod
    def core_hash_from_operation_id(
        cls,
        operation_id: str,
        *,
        namespace: str,
    ) -> str:
        return CorrectionPlanCore.hash_from_operation_id(
            operation_id,
            namespace=namespace,
        )


def require_exact_correction_prefix(
    plan: CorrectionPlanCore | CorrectionReceiptEnvelope,
    events: Sequence[Mapping[str, Any]],
) -> tuple[ResolvedCorrectionEvent, ...]:
    if len(events) > plan.event_count:
        raise ContentAddressedCorrectionError("Journal suffix exceeds the plan")
    expected = plan.events[: len(events)]
    previous = plan.baseline.journal_event_id
    for position, (event, item) in enumerate(zip(events, expected), 1):
        event_id = event.get("event_id") if isinstance(event, Mapping) else None
        if (
            not isinstance(event, Mapping)
            or (event.get("operation_id"), event.get("event_kind"), event.get("subject"))
            != item.prefix_tuple()
            or event.get("sequence") != plan.baseline.journal_sequence + position
            or event.get("previous_event_id") != previous
            or type(event_id) is not str
            or _DIGEST.fullmatch(event_id) is None
        ):
            raise ContentAddressedCorrectionError("Journal suffix is foreign or out of order")
        previous = event_id
    return expected


def _canonical_sha256(value: object) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _projection_member_digest(record: Mapping[str, Any]) -> str:
    return canonical_digest(
        domain="index-projection-member",
        payload={
            "event_sequence": record.get("event_sequence"),
            "event_stream": record.get("event_stream"),
            "fingerprint": record.get("fingerprint"),
            "kind": record.get("kind"),
            "payload": record.get("payload"),
            "record_id": record.get("record_id"),
            "status": record.get("status"),
            "subject": record.get("subject"),
        },
    )


def require_exact_correction_receipts(
    plan: CorrectionReceiptEnvelope,
    events: Sequence[Mapping[str, Any]],
) -> tuple[ResolvedCorrectionEvent, ...]:
    """Verify every durable event field bound before recovery or reuse.

    Receipt hashes intentionally exclude the operation record from the semantic
    inventory.  Its exact record is reconstructed here from the final plan-
    derived operation id, the exact committed payload, and the bound result.
    The projection chain is then advanced from the plan's authenticated baseline
    across every exact operation and semantic record, so an old malformed event
    cannot be forgotten by a later stable head.
    """

    expected = require_exact_correction_prefix(plan, events)
    projection_digest = plan.baseline.index_projection_digest
    record_count = plan.baseline.index_record_count
    journal_offset = (
        plan.baseline.journal_start_offset
        + plan.baseline.journal_size_bytes
    )
    for event, item in zip(events, expected):
        payload = event.get("payload")
        control = event.get("control")
        rows = event.get("index_records")
        event_id = event.get("event_id")
        if (
            set(event) != _JOURNAL_EVENT_FIELDS
            or event.get("schema") != "journal_event"
            or not isinstance(payload, Mapping)
            or not isinstance(control, Mapping)
            or not isinstance(rows, list)
            or not rows
            or any(not isinstance(row, Mapping) for row in rows)
            or canonical_digest(
                domain="journal-event",
                payload={key: value for key, value in event.items() if key != "event_id"},
            )
            != event_id
        ):
            raise ContentAddressedCorrectionError(
                "Journal correction event envelope is not exact"
            )
        operation = rows[0]
        operation_payload = operation.get("payload")
        result = (
            None
            if not isinstance(operation_payload, Mapping)
            else operation_payload.get("result")
        )
        committed_payload = dict(payload)
        expected_operation = {
            "event_sequence": None,
            "event_stream": None,
            "fingerprint": canonical_digest(
                domain="operation",
                payload={
                    "event_kind": item.event_kind,
                    "payload": committed_payload,
                },
            ),
            "kind": "operation",
            "payload": {
                "event_kind": item.event_kind,
                "result": result,
            },
            "record_id": item.operation_id,
            "status": "success",
            "subject": item.subject,
        }
        semantic_rows = rows[1:]
        receipt = item.receipt
        framed_byte_count = len(canonical_bytes(dict(event))) + 1
        if (
            receipt is None
            or dict(operation) != expected_operation
            or _canonical_sha256(dict(event)) != receipt.canonical_event_sha256
            or event_id != receipt.event_id
            or event.get("occurred_at_utc") != receipt.occurred_at_utc
            or event.get("journal_offset") != receipt.journal_offset
            or event.get("journal_offset") != journal_offset
            or _canonical_sha256(payload) != receipt.event_payload_sha256
            or _canonical_sha256(control) != receipt.control_projection_sha256
            or _canonical_sha256(result) != receipt.operation_result_sha256
            or len(semantic_rows) != receipt.semantic_index_record_count
            or _canonical_sha256(semantic_rows)
            != receipt.semantic_index_records_sha256
            or framed_byte_count != receipt.canonical_event_byte_count
            or framed_byte_count > DurableJournal.MAX_EVENT_BYTES
        ):
            raise ContentAddressedCorrectionError(
                "Journal correction event differs from its plan receipt"
            )
        journal_offset += framed_byte_count
        for row in rows:
            projection_digest = canonical_digest(
                domain="index-projection-chain",
                payload={
                    "member": _projection_member_digest(row),
                    "previous": projection_digest,
                },
            )
        record_count += 1 + len(rows)
        if (
            event.get("index_projection_digest") != projection_digest
            or event.get("index_record_count") != record_count
        ):
            raise ContentAddressedCorrectionError(
                "Journal correction event index projection is not exact"
            )
    return expected


def correction_suffix_from_journal(
    plan: CorrectionPlanCore | CorrectionReceiptEnvelope,
    journal_events: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    n = plan.baseline.journal_sequence
    if n > len(journal_events) or journal_events[n - 1].get("event_id") != plan.baseline.journal_event_id:
        raise ContentAddressedCorrectionError("Journal lacks the plan baseline")
    suffix = tuple(journal_events[n:])
    if isinstance(plan, CorrectionReceiptEnvelope):
        require_exact_correction_receipts(plan, suffix)
    else:
        require_exact_correction_prefix(plan, suffix)
    return suffix


def _control_prefix_count(
    plan: CorrectionPlanCore | CorrectionReceiptEnvelope,
    current_control: Mapping[str, Any],
    suffix: Sequence[Mapping[str, Any]],
    *,
    allow_lag: bool,
) -> int:
    require_exact_correction_prefix(plan, suffix)
    heads = current_control.get("heads")
    journal = heads.get("journal") if isinstance(heads, Mapping) else None
    authority = current_control.get("authority")
    sequence = journal.get("sequence") if isinstance(journal, Mapping) else None
    if type(sequence) is not int:
        raise ContentAddressedCorrectionError("control Journal sequence is malformed")
    count = sequence - plan.baseline.journal_sequence
    lag = len(suffix) - count
    if count < 0 or count > len(suffix) or (lag and not (allow_lag and lag == 1)):
        raise ContentAddressedCorrectionError("control is not an allowed plan prefix")
    event_id = plan.baseline.journal_event_id if not count else suffix[count - 1].get("event_id")
    digest = plan.baseline.authority_manifest_digest if not count else plan.prospective_authority_manifest_digest
    if (
        journal.get("event_id") != event_id
        or not isinstance(authority, Mapping)
        or authority.get("manifest_digest") != digest
    ):
        raise ContentAddressedCorrectionError("control payload differs from its plan prefix")
    return count


def _expected_control_for_prefix(
    *,
    base_control_bytes: bytes,
    suffix: Sequence[Mapping[str, Any]],
    count: int,
) -> Mapping[str, Any]:
    """Independently reconstruct the exact control for a verified prefix."""

    if count == 0:
        try:
            baseline = parse_canonical(base_control_bytes)
        except (TypeError, ValueError) as exc:
            raise ContentAddressedCorrectionError(
                "Git baseline control is not canonical"
            ) from exc
        if not isinstance(baseline, Mapping):
            raise ContentAddressedCorrectionError(
                "Git baseline control is not a mapping"
            )
        return baseline
    if count < 0 or count > len(suffix):
        raise ContentAddressedCorrectionError(
            "control prefix count is outside the verified suffix"
        )
    event = suffix[count - 1]
    body = event.get("control")
    sequence = event.get("sequence")
    event_id = event.get("event_id")
    record_count = event.get("index_record_count")
    projection_digest = event.get("index_projection_digest")
    if (
        not isinstance(body, Mapping)
        or any(key in body for key in {"control_hash", "heads", "revision"})
        or type(sequence) is not int
        or sequence < 1
        or type(event_id) is not str
        or not _DIGEST.fullmatch(event_id)
        or type(record_count) is not int
        or record_count < 0
        or type(projection_digest) is not str
        or not _DIGEST.fullmatch(projection_digest)
    ):
        raise ContentAddressedCorrectionError(
            "correction event cannot independently assemble control"
        )
    try:
        assembled = parse_canonical(canonical_bytes(dict(body)))
    except (TypeError, ValueError) as exc:
        raise ContentAddressedCorrectionError(
            "correction event control body is not canonical"
        ) from exc
    if not isinstance(assembled, dict):
        raise ContentAddressedCorrectionError(
            "correction event control body is not a mapping"
        )
    assembled["revision"] = sequence
    assembled["heads"] = {
        "journal": {"sequence": sequence, "event_id": event_id},
        "index": {
            "required_sequence": sequence,
            "required_record_count": record_count,
            "required_projection_digest": projection_digest,
        },
    }
    assembled["control_hash"] = canonical_digest(
        domain="control",
        payload=assembled,
    )
    return assembled


def require_plan_control_head(
    plan: CorrectionPlanCore | CorrectionReceiptEnvelope,
    *,
    current_control: Mapping[str, Any],
    suffix: Sequence[Mapping[str, Any]],
) -> None:
    _control_prefix_count(plan, current_control, suffix, allow_lag=False)


def require_correction_journal_storage_headroom(
    plan: CorrectionPlanCore | CorrectionReceiptEnvelope,
    *,
    suffix: Sequence[Mapping[str, Any]],
    journal_manifest: Mapping[str, Any] | None,
    active_segment_bytes: int,
) -> dict[str, Any]:
    require_exact_correction_prefix(plan, suffix)
    if isinstance(plan, CorrectionReceiptEnvelope) and len(suffix) != plan.event_count:
        raise ContentAddressedCorrectionError(
            "post-execution receipt envelope cannot authorize remaining events"
        )
    _integer("active segment bytes", active_segment_bytes)
    present = len(suffix)
    remaining = plan.event_count - present
    event_byte_bounds = (DurableJournal.MAX_EVENT_BYTES,) * plan.event_count
    remaining_bytes = sum(event_byte_bounds[present:])
    result = {
        "already_present": present,
        "correction_event_byte_upper_bound": sum(event_byte_bounds),
        "correction_event_upper_bound": plan.event_count,
        "event_bound_source": "journal_max_event_bytes",
        "event_byte_bounds": list(event_byte_bounds),
        "remaining": remaining,
        "remaining_event_byte_upper_bound": remaining_bytes,
        "schema": "content_addressed_correction_journal_headroom.v1",
        "segmented_rollover_allowed": False,
    }
    if journal_manifest is None:
        return {**result, "layout": "legacy"}
    active = journal_manifest.get("active_segment")
    first = active.get("first_sequence") if isinstance(active, Mapping) else None
    sequence = plan.baseline.journal_sequence + present
    if (
        journal_manifest.get("schema") != "journal_manifest_v1"
        or not isinstance(active, Mapping)
        or active.get("path") != plan.baseline.journal_path
        or type(first) is not int
        or first < 1
        or sequence < first - 1
    ):
        raise ContentAddressedCorrectionError("active Journal segment is not plan-bound")
    event_count = max(0, sequence - first + 1)
    if (
        event_count + remaining > DurableJournal.MAX_SEGMENT_EVENTS
        or active_segment_bytes + remaining_bytes > DurableJournal.MAX_SEGMENT_BYTES
    ):
        raise ContentAddressedCorrectionError("correction lacks no-rollover headroom")
    return {
        **result,
        "active_event_count": event_count,
        "active_segment_bytes": active_segment_bytes,
        "layout": "segmented",
        "max_segment_bytes": DurableJournal.MAX_SEGMENT_BYTES,
        "max_segment_events": DurableJournal.MAX_SEGMENT_EVENTS,
    }


def require_correction_journal_headroom(
    plan: CorrectionPlanCore | CorrectionReceiptEnvelope,
    *,
    current_control: Mapping[str, Any],
    suffix: Sequence[Mapping[str, Any]],
    journal_manifest: Mapping[str, Any] | None,
    active_segment_bytes: int,
) -> dict[str, Any]:
    require_plan_control_head(plan, current_control=current_control, suffix=suffix)
    return require_correction_journal_storage_headroom(
        plan,
        suffix=suffix,
        journal_manifest=journal_manifest,
        active_segment_bytes=active_segment_bytes,
    )


def _git(root: Path, *args: str, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(("git", *args), cwd=root, check=check, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContentAddressedCorrectionError(f"Git failed: {' '.join(args)}") from exc


def _git_text(root: Path, *args: str) -> str:
    try:
        return _git(root, *args).stdout.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ContentAddressedCorrectionError("Git output is non-ASCII") from exc


def _batch_blobs(
    root: Path,
    requests: Sequence[tuple[str, str]],
    *,
    timeout: int = 120,
) -> dict[tuple[str, str], bytes | None]:
    """Read exact Git blobs in one process without weakening missing checks."""

    ordered: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    encoded: list[bytes] = []
    for ref, candidate in requests:
        path = _relative("Git blob path", candidate)
        if not ref or any(character in ref for character in "\r\n\0"):
            raise ContentAddressedCorrectionError("Git blob reference is malformed")
        request = (ref, path)
        if request in seen:
            continue
        try:
            spec = f"{ref}:{path}".encode("ascii")
        except UnicodeEncodeError as exc:
            raise ContentAddressedCorrectionError(
                "Git blob request is non-ASCII"
            ) from exc
        ordered.append(request)
        encoded.append(spec)
        seen.add(request)
    if not ordered:
        return {}
    try:
        completed = subprocess.run(
            ("git", "cat-file", "--batch"),
            cwd=root,
            check=True,
            capture_output=True,
            input=b"\n".join(encoded) + b"\n",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContentAddressedCorrectionError("Git batch blob read failed") from exc

    output = completed.stdout
    cursor = 0
    result: dict[tuple[str, str], bytes | None] = {}
    for request, spec in zip(ordered, encoded, strict=True):
        header_end = output.find(b"\n", cursor)
        if header_end < 0:
            raise ContentAddressedCorrectionError(
                "Git batch blob response is truncated"
            )
        header = output[cursor:header_end]
        cursor = header_end + 1
        if header == spec + b" missing":
            result[request] = None
            continue
        fields = header.split(b" ")
        try:
            object_id, object_type, raw_size = fields
            size = int(raw_size.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ContentAddressedCorrectionError(
                "Git batch blob header is malformed"
            ) from exc
        if (
            object_type != b"blob"
            or size < 0
            or len(object_id) not in {40, 64}
            or any(character not in b"0123456789abcdef" for character in object_id)
            or cursor + size >= len(output)
            or output[cursor + size : cursor + size + 1] != b"\n"
        ):
            raise ContentAddressedCorrectionError(
                "Git batch blob object is malformed"
            )
        result[request] = output[cursor : cursor + size]
        cursor += size + 1
    if cursor != len(output):
        raise ContentAddressedCorrectionError(
            "Git batch blob response has trailing bytes"
        )
    return result


def _checkpoint_file_inventory(
    root: Path,
    *,
    origin_commit: str,
    checkpoint_commit: str,
) -> tuple[CodeCheckpointFileBinding, ...]:
    try:
        output = _git(
            root,
            "diff",
            "--name-status",
            "--no-renames",
            origin_commit,
            checkpoint_commit,
            "--",
        ).stdout.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ContentAddressedCorrectionError(
            "Git checkpoint inventory is non-ASCII"
        ) from exc
    kinds = {"A": "added", "D": "deleted", "M": "modified", "T": "type-changed"}
    changes: list[tuple[str, str]] = []
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or fields[0] not in kinds:
            raise ContentAddressedCorrectionError(
                "Git checkpoint inventory contains a rename or foreign status"
            )
        path = _relative("Git checkpoint path", fields[1])
        changes.append((path, kinds[fields[0]]))
    blobs = _batch_blobs(
        root,
        tuple(
            request
            for path, _kind in changes
            for request in ((origin_commit, path), (checkpoint_commit, path))
        ),
    )
    result: list[CodeCheckpointFileBinding] = []
    for path, kind in changes:
        predecessor = blobs[(origin_commit, path)]
        checkpoint = blobs[(checkpoint_commit, path)]
        result.append(
            CodeCheckpointFileBinding(
                path=path,
                change_kind=kind,
                predecessor_sha256=(
                    None if predecessor is None else sha256(predecessor).hexdigest()
                ),
                checkpoint_sha256=(
                    None if checkpoint is None else sha256(checkpoint).hexdigest()
                ),
            )
        )
    ordered = tuple(sorted(result, key=lambda item: item.path))
    if len({item.path for item in ordered}) != len(ordered):
        raise ContentAddressedCorrectionError(
            "Git checkpoint inventory contains duplicate paths"
        )
    return ordered


def capture_local_correction_checkpoint(
    root: str | Path,
    *,
    execution_paths: Sequence[str | Path],
) -> dict[str, Any]:
    """Capture the exact local commit/tree and reviewed Python closure.

    Construction is intentionally read-only and may run before the checkpoint
    is committed.  The apply boundary later requires every reviewed execution
    byte to be tracked by this exact commit and rejects untracked files from the
    reviewed execution closure. A provisional plan can therefore be inspected
    but cannot mutate state.
    """

    repository = Path(root).resolve()
    checkpoint_commit = _git_text(repository, "rev-parse", "HEAD")
    checkpoint_tree = _git_text(repository, "rev-parse", "HEAD^{tree}")
    origin_commit = _git_text(repository, "rev-parse", "origin/main")
    execution: list[CorrectionExecutionFileBinding] = []
    for candidate in execution_paths:
        path = Path(candidate)
        absolute = path.resolve() if path.is_absolute() else (repository / path).resolve()
        try:
            relative = absolute.relative_to(repository).as_posix()
        except ValueError as exc:
            raise ContentAddressedCorrectionError(
                "execution file is outside the repository"
            ) from exc
        normalized = _relative("execution file", relative)
        try:
            if absolute.is_symlink() or not absolute.is_file():
                raise OSError
            content = absolute.read_bytes()
        except OSError as exc:
            raise ContentAddressedCorrectionError(
                "execution file is unavailable or link-like"
            ) from exc
        execution.append(
            CorrectionExecutionFileBinding(
                path=normalized,
                sha256=sha256(content).hexdigest(),
            )
        )
    ordered_execution = tuple(sorted(execution, key=lambda item: item.path))
    if (
        not ordered_execution
        or len({item.path for item in ordered_execution}) != len(ordered_execution)
    ):
        raise ContentAddressedCorrectionError(
            "reviewed execution inventory is empty or duplicated"
        )
    return {
        "code_checkpoint_commit": checkpoint_commit,
        "code_checkpoint_files": _checkpoint_file_inventory(
            repository,
            origin_commit=origin_commit,
            checkpoint_commit=checkpoint_commit,
        ),
        "code_checkpoint_tree": checkpoint_tree,
        "execution_files": ordered_execution,
        "origin_main_commit": origin_commit,
    }


def require_local_main_correction_boundary(
    root: str | Path,
    plan: CorrectionPlanCore | CorrectionReceiptEnvelope,
    *,
    current_control: Mapping[str, Any],
    journal_events: Sequence[Mapping[str, Any]],
    allow_one_event_projection_lag: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    repository = Path(root).resolve()
    if _git_text(repository, "branch", "--show-current") != "main":
        raise ContentAddressedCorrectionError("correction apply requires local main")
    head = _git_text(repository, "rev-parse", "HEAD")
    tree = _git_text(repository, "rev-parse", "HEAD^{tree}")
    origin = _git_text(repository, "rev-parse", "origin/main")
    if (
        head != plan.baseline.code_checkpoint_commit
        or tree != plan.baseline.code_checkpoint_tree
        or origin != plan.baseline.origin_main_commit
    ):
        raise ContentAddressedCorrectionError(
            "Git commit, tree, or origin/main differs from the reviewed plan"
        )
    if head == origin or _git(repository, "merge-base", "--is-ancestor", origin, head, check=False, timeout=timeout_seconds).returncode:
        raise ContentAddressedCorrectionError("origin/main is not a strict HEAD ancestor")
    observed_checkpoint = _checkpoint_file_inventory(
        repository,
        origin_commit=origin,
        checkpoint_commit=head,
    )
    if observed_checkpoint != plan.code_checkpoint_files:
        raise ContentAddressedCorrectionError(
            "Git checkpoint file inventory differs from the reviewed plan"
        )
    if _git(repository, "diff", "--cached", "--quiet", check=False, timeout=timeout_seconds).returncode:
        raise ContentAddressedCorrectionError("Git index is not empty")

    try:
        tracked_paths = tuple(
            path
            for path in _git(
                repository,
                "ls-files",
                "-z",
            ).stdout.decode("ascii").split("\0")
            if path
        )
    except UnicodeDecodeError as exc:
        raise ContentAddressedCorrectionError(
            "tracked path inventory is non-ASCII"
        ) from exc
    tracked_path_set = frozenset(tracked_paths)
    execution_blobs = _batch_blobs(
        repository,
        tuple((head, item.path) for item in plan.execution_files),
        timeout=timeout_seconds,
    )
    for item in plan.execution_files:
        if item.path not in tracked_path_set:
            raise ContentAddressedCorrectionError(
                "reviewed execution file is not tracked by the checkpoint"
            )
        head_bytes = execution_blobs[(head, item.path)]
        try:
            worktree_path = repository / item.path
            if worktree_path.is_symlink() or not worktree_path.is_file():
                raise OSError
            worktree_bytes = worktree_path.read_bytes()
        except OSError as exc:
            raise ContentAddressedCorrectionError(
                "reviewed execution file is unavailable or link-like"
            ) from exc
        if (
            head_bytes is None
            or sha256(head_bytes).hexdigest() != item.sha256
            or worktree_bytes != head_bytes
        ):
            raise ContentAddressedCorrectionError(
                "reviewed execution bytes differ from the checkpoint"
            )
    try:
        untracked_paths = _git(
            repository,
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        ).stdout.decode("ascii").split("\0")
    except UnicodeDecodeError as exc:
        raise ContentAddressedCorrectionError(
            "untracked path inventory is non-ASCII"
        ) from exc
    untracked_execution = tuple(
        sorted(
            path
            for path in untracked_paths
            if path and Path(path).suffix.lower() in _EXECUTION_SUFFIXES
        )
    )
    automatic_module_names = frozenset({"sitecustomize", "usercustomize"})

    def automatic_or_extension_shadow(path: str) -> bool:
        normalized = path.replace("\\", "/").casefold()
        under_import_root = (
            "/" not in normalized
            or normalized.startswith("src/")
            or normalized.startswith("scripts/")
        )
        relative = normalized
        for prefix in ("src/", "scripts/"):
            if relative.startswith(prefix):
                relative = relative.removeprefix(prefix)
                break
        first = relative.split("/", 1)[0]
        stem = Path(first).stem.casefold()
        automatic = stem in automatic_module_names
        extension_shadow = (
            under_import_root
            and Path(relative).suffix.casefold()
            in {".dll", ".pyc", ".pyd", ".so"}
        )
        return automatic or extension_shadow

    tracked_automatic_load = tuple(
        path for path in tracked_paths if automatic_or_extension_shadow(path)
    )
    if tracked_automatic_load:
        raise ContentAddressedCorrectionError(
            "tracked Python automatic-load or binary shadow is present at "
            "the apply boundary"
        )

    untracked_automatic_load = tuple(
        path
        for path in untracked_execution
        if automatic_or_extension_shadow(path)
    )
    if untracked_automatic_load:
        raise ContentAddressedCorrectionError(
            "untracked Python automatic-load source is present at the apply boundary"
        )

    expected_baseline = {
        "state/control.json": plan.baseline.control_sha256,
        plan.baseline.journal_path: plan.baseline.journal_sha256,
    }
    boundary_requests = [
        request
        for path in expected_baseline
        for request in (("HEAD", path), ("origin/main", path))
    ]
    if plan.baseline.journal_manifest_sha256 is not None:
        boundary_requests.extend(
            (
                ("HEAD", "records/journal/manifest.json"),
                ("origin/main", "records/journal/manifest.json"),
            )
        )
    boundary_requests.extend(
        request
        for item in plan.authority_files
        for request in (("origin/main", item.path), ("HEAD", item.path))
    )
    boundary_blobs = _batch_blobs(
        repository,
        tuple(boundary_requests),
        timeout=timeout_seconds,
    )

    def required_blob(ref: str, path: str) -> bytes:
        content = boundary_blobs.get((ref, path))
        if content is None:
            raise ContentAddressedCorrectionError(
                f"missing Git blob {ref}:{path}"
            )
        return content

    for path, expected_hash in expected_baseline.items():
        head_bytes = required_blob("HEAD", path)
        origin_bytes = required_blob("origin/main", path)
        if head_bytes != origin_bytes or sha256(head_bytes).hexdigest() != expected_hash:
            raise ContentAddressedCorrectionError("control/Journal Git baseline drifted")

    manifest_path = repository / "records/journal/manifest.json"
    manifest: Mapping[str, Any] | None = None
    if plan.baseline.journal_manifest_sha256 is None:
        if manifest_path.exists():
            raise ContentAddressedCorrectionError("legacy plan has a Journal manifest")
    else:
        head_bytes = required_blob("HEAD", "records/journal/manifest.json")
        origin_bytes = required_blob("origin/main", "records/journal/manifest.json")
        try:
            worktree_bytes = manifest_path.read_bytes()
            value = json.loads(worktree_bytes.decode("ascii"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContentAddressedCorrectionError("Journal manifest is malformed") from exc
        if (
            head_bytes != origin_bytes
            or head_bytes != worktree_bytes
            or sha256(head_bytes).hexdigest() != plan.baseline.journal_manifest_sha256
            or not isinstance(value, Mapping)
        ):
            raise ContentAddressedCorrectionError("Journal manifest Git baseline drifted")
        manifest = value

    for item in plan.authority_files:
        origin_bytes = required_blob("origin/main", item.path)
        head_bytes = required_blob("HEAD", item.path)
        try:
            current = (repository / item.path).read_bytes()
        except OSError as exc:
            raise ContentAddressedCorrectionError("authority file is unavailable") from exc
        if (
            sha256(origin_bytes).hexdigest() != item.predecessor_sha256
            or sha256(head_bytes).hexdigest() != item.prospective_sha256
            or current != head_bytes
        ):
            raise ContentAddressedCorrectionError("authority replacement bytes drifted")

    suffix = correction_suffix_from_journal(plan, journal_events)
    control_count = _control_prefix_count(
        plan,
        current_control,
        suffix,
        allow_lag=allow_one_event_projection_lag,
    )
    control_path = repository / "state/control.json"
    journal_path = repository / plan.baseline.journal_path
    control_bytes, journal_bytes = control_path.read_bytes(), journal_path.read_bytes()
    base_control = required_blob("HEAD", "state/control.json")
    base_journal = required_blob("HEAD", plan.baseline.journal_path)
    try:
        supplied_control_bytes = canonical_bytes(dict(current_control))
        expected_control_bytes = canonical_bytes(
            _expected_control_for_prefix(
                base_control_bytes=base_control,
                suffix=suffix,
                count=control_count,
            )
        )
        expected_journal_bytes = base_journal + b"".join(
            canonical_bytes(dict(event)) + b"\n" for event in suffix
        )
    except (TypeError, ValueError) as exc:
        raise ContentAddressedCorrectionError(
            "supplied control or Journal snapshot is not canonical"
        ) from exc
    if (
        supplied_control_bytes != expected_control_bytes
        or control_bytes != expected_control_bytes
        or journal_bytes != expected_journal_bytes
        or bool(control_count) != (control_bytes != base_control)
        or bool(suffix) != (journal_bytes != base_journal)
    ):
        raise ContentAddressedCorrectionError(
            "worktree state bytes differ from the exact supplied correction prefix"
        )
    expected_changes = tuple(sorted((*(('state/control.json',) if control_count else ()), *((plan.baseline.journal_path,) if suffix else ()))))
    changed = tuple(sorted(line for line in _git_text(repository, "diff", "--name-only").splitlines() if line))
    if changed != expected_changes:
        raise ContentAddressedCorrectionError("tracked changes are not the exact suffix")
    untracked = _git_text(
        repository,
        "ls-files", "--others", "--exclude-standard", "--",
        "state/control.json", "records/journal", "records/journal.jsonl",
    )
    if untracked:
        raise ContentAddressedCorrectionError("untracked state path is foreign")
    headroom = require_correction_journal_storage_headroom(
        plan,
        suffix=suffix,
        journal_manifest=manifest,
        active_segment_bytes=len(journal_bytes),
    )
    return {
        "code_checkpoint_head": head,
        "code_checkpoint_tree": tree,
        "code_checkpoint_file_count": len(observed_checkpoint),
        "correction_commit_paths": ["state/control.json", plan.baseline.journal_path],
        "structural_core_prefix_count": len(suffix),
        "excluded_untracked_non_authority_paths": list(untracked_execution),
        "force_push_allowed": False,
        "journal_headroom": headroom,
        "origin_main": origin,
        "origin_main_is_strict_ancestor": True,
        "plan_artifact_hash": (
            plan.artifact_hash
            if isinstance(plan, CorrectionReceiptEnvelope)
            else None
        ),
        "plan_core_hash": plan.core_hash,
        "projection_prefix_count": control_count,
        "reviewed_execution_file_count": len(plan.execution_files),
        "schema": "content_addressed_correction_local_main_boundary.v2",
    }


__all__ = [
    "AuthorityFileBinding",
    "CodeCheckpointFileBinding",
    "ContentAddressedCorrectionError",
    "CorrectionReceiptEnvelope",
    "CorrectionBaseline",
    "CorrectionEventIntent",
    "CorrectionEventReceiptBinding",
    "CorrectionEvidenceBinding",
    "CorrectionExecutionFileBinding",
    "CorrectionPlanCore",
    "ResolvedCorrectionEvent",
    "capture_local_correction_checkpoint",
    "correction_suffix_from_journal",
    "require_correction_journal_headroom",
    "require_correction_journal_storage_headroom",
    "require_exact_correction_prefix",
    "require_exact_correction_receipts",
    "require_local_main_correction_boundary",
    "require_plan_control_head",
]
