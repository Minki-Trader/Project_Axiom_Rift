"""Read-only validation for one crash-resumable Writer operation chain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from axiom_rift.storage.index import LocalIndex


class StrictOperationChainError(RuntimeError):
    """Raised when durable operations are not one exact authority prefix."""


@dataclass(frozen=True, slots=True)
class OperationStep:
    operation_id: str
    event_kind: str
    stage: str

    def __post_init__(self) -> None:
        for name, value in (
            ("operation_id", self.operation_id),
            ("event_kind", self.event_kind),
            ("stage", self.stage),
        ):
            if type(value) is not str or not value or not value.isascii():
                raise StrictOperationChainError(f"{name} must be non-empty ASCII")


def validate_operation_plan(
    steps: Sequence[OperationStep],
    *,
    operation_prefix: str,
) -> tuple[OperationStep, ...]:
    normalized = tuple(steps)
    if (
        not normalized
        or type(operation_prefix) is not str
        or not operation_prefix
        or not operation_prefix.isascii()
        or any(not isinstance(step, OperationStep) for step in normalized)
    ):
        raise StrictOperationChainError("strict operation plan is invalid")
    operation_ids = tuple(step.operation_id for step in normalized)
    if len(operation_ids) != len(set(operation_ids)) or any(
        not value.startswith(operation_prefix) for value in operation_ids
    ):
        raise StrictOperationChainError(
            "strict operation plan has duplicate or foreign operation ids"
        )
    return normalized


def inspect_operation_prefix(
    *,
    index: LocalIndex,
    journal: Any,
    steps: Sequence[OperationStep],
    operation_prefix: str,
    predecessor_sequence: int,
    predecessor_event_id: str,
    current_sequence: int,
) -> int:
    """Return the exact completed prefix without recovering or mutating state."""

    normalized = validate_operation_plan(
        steps,
        operation_prefix=operation_prefix,
    )
    if (
        type(predecessor_sequence) is not int
        or predecessor_sequence < 1
        or type(current_sequence) is not int
        or current_sequence < predecessor_sequence
        or type(predecessor_event_id) is not str
        or len(predecessor_event_id) != 64
    ):
        raise StrictOperationChainError("strict operation predecessor is invalid")
    expected_ids = {step.operation_id for step in normalized}
    foreign = tuple(
        record.record_id
        for record in index.records_by_kind("operation")
        if record.record_id.startswith(operation_prefix)
        and record.record_id not in expected_ids
    )
    if foreign:
        raise StrictOperationChainError(
            "operation prefix contains an undeclared operation: "
            + ",".join(sorted(foreign))
        )

    prefix = 0
    hole = False
    prior_event_id = predecessor_event_id
    for position, step in enumerate(normalized):
        record = index.get("operation", step.operation_id)
        if record is None:
            hole = True
            continue
        if hole:
            raise StrictOperationChainError("durable operations are not a strict prefix")
        sequence = predecessor_sequence + position + 1
        if (
            record.status != "success"
            or record.payload.get("event_kind") != step.event_kind
            or record.authority_sequence != sequence
            or not isinstance(record.authority_event_id, str)
            or record.authority_offset is None
        ):
            raise StrictOperationChainError(
                f"operation authority binding differs: {step.operation_id}"
            )
        event = journal.read_event_at(
            offset=record.authority_offset,
            expected_sequence=sequence,
            expected_event_id=record.authority_event_id,
        )
        if (
            not isinstance(event, Mapping)
            or event.get("operation_id") != step.operation_id
            or event.get("event_kind") != step.event_kind
            or event.get("previous_event_id") != prior_event_id
        ):
            raise StrictOperationChainError(
                f"Journal operation binding differs: {step.operation_id}"
            )
        prior_event_id = record.authority_event_id
        prefix += 1
    if prefix < len(normalized) and current_sequence != predecessor_sequence + prefix:
        raise StrictOperationChainError(
            "a foreign authority event interrupts the resumable operation prefix"
        )
    if prefix == len(normalized) and current_sequence < predecessor_sequence + prefix:
        raise StrictOperationChainError("completed operation chain is ahead of control")
    return prefix


def stage_bounds(
    steps: Sequence[OperationStep],
    *,
    stage: str,
) -> tuple[int, int]:
    normalized = tuple(steps)
    positions = tuple(
        position for position, step in enumerate(normalized) if step.stage == stage
    )
    if not positions or positions != tuple(range(positions[0], positions[-1] + 1)):
        raise StrictOperationChainError("operation stage is absent or non-contiguous")
    return positions[0], positions[-1] + 1


__all__ = [
    "OperationStep",
    "StrictOperationChainError",
    "inspect_operation_prefix",
    "stage_bounds",
    "validate_operation_plan",
]
