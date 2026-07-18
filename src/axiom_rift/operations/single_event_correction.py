"""Pure full-envelope planning for one content-addressed correction event."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import re
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.content_addressed_correction import (
    CorrectionEventReceiptBinding,
    CorrectionPlanCore,
)
from axiom_rift.storage.journal import DurableJournal


BINDING_SCHEMA = "single_event_correction_binding.v1"
_BINDING_KEYS = {
    "control_projection",
    "control_projection_sha256",
    "event_payload",
    "event_payload_sha256",
    "guards",
    "operation_result",
    "operation_result_sha256",
    "schema",
    "semantic_index_record_count",
    "semantic_index_records",
    "semantic_index_records_sha256",
}
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
_CANONICAL_UTC = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z\Z"
)


class SingleEventCorrectionError(RuntimeError):
    """A full correction mapping or independently assembled event drifted."""


def _canonical_mapping(name: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SingleEventCorrectionError(f"{name} must be a mapping")
    try:
        normalized = parse_canonical(canonical_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise SingleEventCorrectionError(f"{name} is not canonical") from exc
    if not isinstance(normalized, dict):
        raise SingleEventCorrectionError(f"{name} is not a mapping")
    return normalized


def _canonical_records(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SingleEventCorrectionError(
            "semantic index records must be a sequence"
        )
    records = tuple(
        _canonical_mapping("semantic index record", item) for item in value
    )
    if not records:
        raise SingleEventCorrectionError("semantic index records are empty")
    required = {
        "event_sequence",
        "event_stream",
        "fingerprint",
        "kind",
        "payload",
        "record_id",
        "status",
        "subject",
    }
    if any(set(record) != required for record in records):
        raise SingleEventCorrectionError(
            "semantic index record mapping is not exact"
        )
    if any(record["kind"] in {"journal-event", "operation"} for record in records):
        raise SingleEventCorrectionError(
            "semantic records cannot impersonate envelope authority"
        )
    identities = tuple((record["kind"], record["record_id"]) for record in records)
    if len(set(identities)) != len(identities):
        raise SingleEventCorrectionError("semantic index records are duplicated")
    return records


def _sha256(value: object) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _utc(value: object) -> str:
    if type(value) is not str or _CANONICAL_UTC.fullmatch(value) is None:
        raise SingleEventCorrectionError(
            "correction timestamp must be canonical UTC"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SingleEventCorrectionError(
            "correction timestamp is invalid UTC"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise SingleEventCorrectionError(
            "correction timestamp is not UTC"
        )
    return value


@dataclass(frozen=True, slots=True)
class SingleEventCorrectionBinding:
    """Core-bound full mappings plus non-event execution guards."""

    control_projection: Mapping[str, Any]
    event_payload: Mapping[str, Any]
    operation_result: Mapping[str, Any]
    semantic_index_records: tuple[Mapping[str, Any], ...]
    guards: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "control_projection",
            _canonical_mapping("control projection", self.control_projection),
        )
        object.__setattr__(
            self,
            "event_payload",
            _canonical_mapping("event payload", self.event_payload),
        )
        object.__setattr__(
            self,
            "operation_result",
            _canonical_mapping("operation result", self.operation_result),
        )
        object.__setattr__(
            self,
            "semantic_index_records",
            _canonical_records(self.semantic_index_records),
        )
        object.__setattr__(
            self,
            "guards",
            _canonical_mapping("correction guards", self.guards),
        )

    def to_payload(self) -> dict[str, Any]:
        records = [dict(record) for record in self.semantic_index_records]
        control = dict(self.control_projection)
        event_payload = dict(self.event_payload)
        result = dict(self.operation_result)
        return {
            "control_projection": control,
            "control_projection_sha256": _sha256(control),
            "event_payload": event_payload,
            "event_payload_sha256": _sha256(event_payload),
            "guards": dict(self.guards),
            "operation_result": result,
            "operation_result_sha256": _sha256(result),
            "schema": BINDING_SCHEMA,
            "semantic_index_record_count": len(records),
            "semantic_index_records": records,
            "semantic_index_records_sha256": _sha256(records),
        }

    @classmethod
    def from_mapping(cls, value: object) -> "SingleEventCorrectionBinding":
        if (
            not isinstance(value, Mapping)
            or set(value) != _BINDING_KEYS
            or value.get("schema") != BINDING_SCHEMA
        ):
            raise SingleEventCorrectionError(
                "single-event correction binding is malformed"
            )
        result = cls(
            control_projection=value["control_projection"],
            event_payload=value["event_payload"],
            operation_result=value["operation_result"],
            semantic_index_records=tuple(value["semantic_index_records"]),
            guards=value["guards"],
        )
        rebuilt = result.to_payload()
        if dict(value) != rebuilt:
            raise SingleEventCorrectionError(
                "single-event correction mapping or digest drifted"
            )
        return result


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


def _operation_record(
    core: CorrectionPlanCore,
    binding: SingleEventCorrectionBinding,
) -> dict[str, Any]:
    event = core.events[0]
    return {
        "event_sequence": None,
        "event_stream": None,
        "fingerprint": canonical_digest(
            domain="operation",
            payload={
                "event_kind": event.event_kind,
                "payload": dict(binding.event_payload),
            },
        ),
        "kind": "operation",
        "payload": {
            "event_kind": event.event_kind,
            "result": dict(binding.operation_result),
        },
        "record_id": event.operation_id,
        "status": "success",
        "subject": event.subject,
    }


def build_single_correction_event(
    core: CorrectionPlanCore,
    *,
    occurred_at_utc: str,
) -> dict[str, Any]:
    """Assemble every Journal field without consulting Writer or Journal output."""

    if not isinstance(core, CorrectionPlanCore) or core.event_count != 1:
        raise SingleEventCorrectionError(
            "single-event envelope requires exactly one planned action"
        )
    occurred_at_utc = _utc(occurred_at_utc)
    binding = SingleEventCorrectionBinding.from_mapping(
        core.event_intents[0].binding
    )
    operation = _operation_record(core, binding)
    rows = [operation, *[dict(row) for row in binding.semantic_index_records]]
    projection = core.baseline.index_projection_digest
    for row in rows:
        projection = canonical_digest(
            domain="index-projection-chain",
            payload={
                "member": _projection_member_digest(row),
                "previous": projection,
            },
        )
    planned = core.events[0]
    event: dict[str, Any] = {
        "control": dict(binding.control_projection),
        "event_kind": planned.event_kind,
        "index_projection_digest": projection,
        "index_record_count": (
            core.baseline.index_record_count + 1 + len(rows)
        ),
        "index_records": rows,
        "journal_offset": (
            core.baseline.journal_start_offset
            + core.baseline.journal_size_bytes
        ),
        "occurred_at_utc": occurred_at_utc,
        "operation_id": planned.operation_id,
        "payload": dict(binding.event_payload),
        "previous_event_id": core.baseline.journal_event_id,
        "schema": "journal_event",
        "sequence": core.baseline.journal_sequence + 1,
        "subject": planned.subject,
    }
    event["event_id"] = canonical_digest(domain="journal-event", payload=event)
    if set(event) != _JOURNAL_EVENT_FIELDS:
        raise SingleEventCorrectionError("assembled Journal mapping is incomplete")
    if len(canonical_bytes(event)) + 1 > DurableJournal.MAX_EVENT_BYTES:
        raise SingleEventCorrectionError(
            "assembled correction event exceeds the Journal bound"
        )
    return event


def require_bound_single_correction_suffix(
    core: CorrectionPlanCore,
    suffix: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Require an existing suffix to equal the core-derived event byte for byte."""

    if not isinstance(core, CorrectionPlanCore) or core.event_count != 1:
        raise SingleEventCorrectionError(
            "bound correction suffix requires one planned event"
        )
    if not isinstance(suffix, Sequence) or isinstance(suffix, (str, bytes)):
        raise SingleEventCorrectionError("correction suffix must be a sequence")
    if not suffix:
        return ()
    if len(suffix) != 1:
        raise SingleEventCorrectionError(
            "bound correction suffix may contain only its one planned event"
        )
    observed = _canonical_mapping("correction suffix event", suffix[0])
    occurred_at_utc = observed.get("occurred_at_utc")
    if type(occurred_at_utc) is not str:
        raise SingleEventCorrectionError(
            "correction suffix timestamp is malformed"
        )
    expected = build_single_correction_event(
        core,
        occurred_at_utc=occurred_at_utc,
    )
    if canonical_bytes(observed) != canonical_bytes(expected):
        raise SingleEventCorrectionError(
            "correction suffix differs from its core-bound full event"
        )
    return (observed,)


def correction_event_receipt(
    event: Mapping[str, Any],
) -> CorrectionEventReceiptBinding:
    """Derive the exact receipt from one fully verified event."""

    if set(event) != _JOURNAL_EVENT_FIELDS:
        raise SingleEventCorrectionError("correction event mapping is malformed")
    rows = event.get("index_records")
    if (
        not isinstance(rows, list)
        or len(rows) < 2
        or not isinstance(rows[0], Mapping)
    ):
        raise SingleEventCorrectionError("correction event rows are malformed")
    result = rows[0].get("payload", {}).get("result")
    if not isinstance(result, Mapping):
        raise SingleEventCorrectionError("correction operation result is malformed")
    return CorrectionEventReceiptBinding(
        canonical_event_byte_count=len(canonical_bytes(dict(event))) + 1,
        canonical_event_sha256=sha256(canonical_bytes(dict(event))).hexdigest(),
        event_id=event["event_id"],
        occurred_at_utc=event["occurred_at_utc"],
        journal_offset=event["journal_offset"],
        event_payload_sha256=_sha256(event["payload"]),
        control_projection_sha256=_sha256(event["control"]),
        operation_result_sha256=_sha256(result),
        semantic_index_records_sha256=_sha256(rows[1:]),
        semantic_index_record_count=len(rows) - 1,
    )


__all__ = [
    "BINDING_SCHEMA",
    "SingleEventCorrectionBinding",
    "SingleEventCorrectionError",
    "build_single_correction_event",
    "correction_event_receipt",
    "require_bound_single_correction_suffix",
]
