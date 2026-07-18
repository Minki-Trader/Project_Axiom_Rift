from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from axiom_rift.operations.replay_workflow_recovery import (
    _pre_admission_protocol_activation_suffix_is_exact,
)
from axiom_rift.operations.recorded_transition_authority import (
    RecordedTransitionAuthorityError,
)
from axiom_rift.storage.index import IndexRecord


PREFIX = "fixture-pre-admission-replay-"
BOUNDARY_EVENT_ID = "a" * 64
ACTIVATION_EVENT_ID = "b" * 64
VALIDATOR_DIGEST = "c" * 64
ACTIVATION_ID = "research-protocol:" + "d" * 64
SUBJECT = "ProjectGoal:OPERATING_DIRECTION.md"


def _record(
    *,
    kind: str,
    record_id: str,
    status: str,
    payload: dict[str, object],
    authority_sequence: int,
    authority_event_id: str,
    event_stream: str | None = None,
    event_sequence: int | None = None,
) -> IndexRecord:
    return IndexRecord(
        kind=kind,
        record_id=record_id,
        subject=SUBJECT,
        status=status,
        fingerprint=record_id.removeprefix("research-protocol:"),
        payload=payload,
        event_stream=event_stream,
        event_sequence=event_sequence,
        authority_sequence=authority_sequence,
        authority_event_id=authority_event_id,
        authority_offset=42,
    )


def _records() -> tuple[IndexRecord, IndexRecord, IndexRecord, IndexRecord]:
    operation_id = PREFIX + "activate-v2-protocol-" + VALIDATOR_DIGEST
    result = {
        "activation_record_id": ACTIVATION_ID,
        "ordinal": 2,
        "protocol": "scientific_adjudication_v2",
        "trial_delta": 0,
        "validator_id": "validator:" + VALIDATOR_DIGEST,
    }
    boundary = _record(
        kind="journal-event",
        record_id=BOUNDARY_EVENT_ID,
        status="portfolio_decision_recorded",
        payload={"operation_id": "predecessor-operation"},
        authority_sequence=10,
        authority_event_id=BOUNDARY_EVENT_ID,
        event_stream="control",
        event_sequence=10,
    )
    operation = _record(
        kind="operation",
        record_id=operation_id,
        status="success",
        payload={
            "event_kind": "research_protocol_activated",
            "result": result,
        },
        authority_sequence=11,
        authority_event_id=ACTIVATION_EVENT_ID,
    )
    activation = _record(
        kind="research-protocol-activation",
        record_id=ACTIVATION_ID,
        status="active",
        payload={
            "audit_artifact_hash": "e" * 64,
            "authority_manifest_digest": "f" * 64,
            "ordinal": 2,
            "protocol": "scientific_adjudication_v2",
            "schema": "research_protocol_activation.v1",
            "scientific_trial_delta": 0,
            "supersedes_activation_record_id": "research-protocol:" + "0" * 64,
            "validator_id": "validator:" + VALIDATOR_DIGEST,
        },
        authority_sequence=11,
        authority_event_id=ACTIVATION_EVENT_ID,
        event_stream="research-protocol:scientific",
        event_sequence=2,
    )
    journal = _record(
        kind="journal-event",
        record_id=ACTIVATION_EVENT_ID,
        status="research_protocol_activated",
        payload={"operation_id": operation_id},
        authority_sequence=11,
        authority_event_id=ACTIVATION_EVENT_ID,
        event_stream="control",
        event_sequence=11,
    )
    return boundary, operation, activation, journal


class _Index:
    def __init__(
        self,
        *,
        boundary: IndexRecord,
        operation: IndexRecord,
        activation: IndexRecord,
        journal: IndexRecord,
    ) -> None:
        self._records = {
            (boundary.kind, boundary.record_id): boundary,
            (operation.kind, operation.record_id): operation,
            (activation.kind, activation.record_id): activation,
            (journal.kind, journal.record_id): journal,
        }
        self._operation = operation

    def get(self, kind: str, record_id: str) -> IndexRecord | None:
        return self._records.get((kind, record_id))

    def records_by_kind_prefix(
        self,
        kind: str,
        prefix: str,
    ) -> tuple[IndexRecord, ...]:
        if kind == "operation" and self._operation.record_id.startswith(prefix):
            return (self._operation,)
        return ()

    def records_by_kind_at_authority_sequence(
        self,
        kind: str,
        authority_sequence: int,
    ) -> tuple[IndexRecord, ...]:
        if (
            kind == "operation"
            and self._operation.authority_sequence == authority_sequence
        ):
            return (self._operation,)
        return ()


def _accepted(
    *,
    operation: IndexRecord | None = None,
    activation: IndexRecord | None = None,
    current_sequence: int = 11,
    authority_valid: bool = True,
) -> bool:
    boundary, base_operation, base_activation, journal = _records()
    operation = base_operation if operation is None else operation
    activation = base_activation if activation is None else activation
    index = _Index(
        boundary=boundary,
        operation=operation,
        activation=activation,
        journal=journal,
    )
    authority_result = (
        "research_protocol_activated",
        operation.payload["result"],
    )
    authority_side_effect = (
        None
        if authority_valid
        else RecordedTransitionAuthorityError("cross-event fixture")
    )
    with patch(
        "axiom_rift.operations.replay_workflow_recovery."
        "require_same_event_operation_result",
        return_value=authority_result,
        side_effect=authority_side_effect,
    ):
        return _pre_admission_protocol_activation_suffix_is_exact(
            index=index,
            spec=SimpleNamespace(operation_prefix=PREFIX),
            boundary=SimpleNamespace(sequence=10, event_id=BOUNDARY_EVENT_ID),
            current_sequence=current_sequence,
            current_event_id=ACTIVATION_EVENT_ID,
        )


def test_exact_zero_credit_activation_suffix_is_admitted() -> None:
    assert _accepted()


@pytest.mark.parametrize(
    "mutation",
    ["credit", "validator", "gap", "authority"],
)
def test_nonexact_activation_suffix_is_rejected(mutation: str) -> None:
    _boundary, operation, activation, _journal = _records()
    current_sequence = 11
    authority_valid = True
    if mutation == "credit":
        payload = dict(operation.payload)
        result = dict(payload["result"])
        result["trial_delta"] = 1
        payload["result"] = result
        operation = replace(operation, payload=payload)
    elif mutation == "validator":
        payload = dict(activation.payload)
        payload["validator_id"] = "validator:" + "9" * 64
        activation = replace(activation, payload=payload)
    elif mutation == "gap":
        current_sequence = 12
    else:
        authority_valid = False

    assert not _accepted(
        operation=operation,
        activation=activation,
        current_sequence=current_sequence,
        authority_valid=authority_valid,
    )
