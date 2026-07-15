"""Small authenticated projection for one Writer-recorded stream transition."""

from __future__ import annotations

from collections.abc import Mapping

from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class RecordedTransitionAuthorityError(RuntimeError):
    """A stream record is not bound to one exact Writer Journal event."""


def authority_key(record: IndexRecord) -> tuple[int, str, int]:
    sequence = record.authority_sequence
    event_id = record.authority_event_id
    offset = record.authority_offset
    if (
        type(sequence) is not int
        or sequence < 1
        or type(event_id) is not str
        or len(event_id) != 64
        or any(character not in "0123456789abcdef" for character in event_id)
        or type(offset) is not int
        or offset < 0
    ):
        raise RecordedTransitionAuthorityError(
            "recorded transition lacks exact Journal authority"
        )
    return sequence, event_id, offset


def require_recorded_transition_authority(
    index: LocalIndex | LocalIndexView,
    *,
    record: IndexRecord,
    expected_event_kinds: frozenset[str],
    require_current_head: bool,
) -> tuple[str, Mapping[str, object]]:
    """Authenticate a stream record, its predecessor, operation, and event."""

    if (
        not isinstance(index, (LocalIndex, LocalIndexView))
        or not isinstance(record, IndexRecord)
        or type(expected_event_kinds) is not frozenset
        or not expected_event_kinds
        or any(
            type(value) is not str or not value or not value.isascii()
            for value in expected_event_kinds
        )
        or type(require_current_head) is not bool
    ):
        raise RecordedTransitionAuthorityError(
            "recorded transition authority request is invalid"
        )
    stream = record.event_stream
    sequence_in_stream = record.event_sequence
    if (
        type(stream) is not str
        or not stream
        or type(sequence_in_stream) is not int
        or sequence_in_stream < 2
        or index.event_record(stream, sequence_in_stream) != record
    ):
        raise RecordedTransitionAuthorityError(
            "recorded transition is not its exact stream event"
        )
    if require_current_head:
        head = index.event_head(stream)
        if (
            head is None
            or head.sequence != sequence_in_stream
            or head.record_kind != record.kind
            or head.record_id != record.record_id
            or head.fingerprint != record.fingerprint
        ):
            raise RecordedTransitionAuthorityError(
                "recorded transition is not the current stream head"
            )
    predecessor = index.event_record(stream, sequence_in_stream - 1)
    if (
        predecessor is None
        or predecessor.subject != record.subject
        or predecessor.status != record.payload.get("prior_status")
        or predecessor.event_stream != stream
        or predecessor.event_sequence != sequence_in_stream - 1
    ):
        raise RecordedTransitionAuthorityError(
            "recorded transition differs from its actual predecessor"
        )
    return require_same_event_operation_result(
        index,
        record=record,
        expected_event_kinds=expected_event_kinds,
    )


def require_same_event_operation_result(
    index: LocalIndex | LocalIndexView,
    *,
    record: IndexRecord,
    expected_event_kinds: frozenset[str],
) -> tuple[str, Mapping[str, object]]:
    """Bind any indexed record to its one Writer operation and Journal event."""

    if (
        not isinstance(index, (LocalIndex, LocalIndexView))
        or not isinstance(record, IndexRecord)
        or type(expected_event_kinds) is not frozenset
        or not expected_event_kinds
        or any(
            type(value) is not str or not value or not value.isascii()
            for value in expected_event_kinds
        )
    ):
        raise RecordedTransitionAuthorityError(
            "same-event operation authority request is invalid"
        )
    sequence, event_id, offset = authority_key(record)
    operations = index.records_by_kind_at_authority_sequence(
        "operation",
        sequence,
    )
    if len(operations) != 1:
        raise RecordedTransitionAuthorityError(
            "recorded transition lacks one same-authority Writer operation"
        )
    operation = operations[0]
    event_kind = operation.payload.get("event_kind")
    result = operation.payload.get("result")
    if (
        authority_key(operation) != (sequence, event_id, offset)
        or operation.status != "success"
        or operation.event_stream is not None
        or operation.event_sequence is not None
        or set(operation.payload) != {"event_kind", "result"}
        or event_kind not in expected_event_kinds
        or not isinstance(result, Mapping)
    ):
        raise RecordedTransitionAuthorityError(
            "recorded transition Writer operation is malformed or cross-event"
        )
    journal_event = index.get("journal-event", event_id)
    if (
        journal_event is None
        or authority_key(journal_event) != (sequence, event_id, offset)
        or journal_event.status != event_kind
        or journal_event.event_stream != "control"
        or journal_event.event_sequence != sequence
        or journal_event.payload.get("operation_id") != operation.record_id
    ):
        raise RecordedTransitionAuthorityError(
            "recorded transition Journal event is unavailable or cross-event"
        )
    return event_kind, result


__all__ = [
    "RecordedTransitionAuthorityError",
    "authority_key",
    "require_recorded_transition_authority",
    "require_same_event_operation_result",
]
