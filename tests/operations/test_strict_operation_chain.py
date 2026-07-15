from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from axiom_rift.operations.strict_operation_chain import (
    OperationStep,
    StrictOperationChainError,
    inspect_operation_prefix,
    validate_operation_plan,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


class _Journal:
    def __init__(self, events: dict[int, dict[str, object]]) -> None:
        self._events = events

    def read_event_at(
        self,
        *,
        offset: int,
        expected_sequence: int,
        expected_event_id: str,
    ) -> dict[str, object]:
        event = self._events[offset]
        if (
            event["sequence"] != expected_sequence
            or event["event_id"] != expected_event_id
        ):
            raise AssertionError("Journal authority lookup differs")
        return event


class _MemoryIndex:
    def __init__(self, records: dict[str, object]) -> None:
        self.records = records
        self.prefix_calls: list[tuple[str, str]] = []

    def records_by_kind(self, _kind: str):
        raise AssertionError("strict operation inspection must not scan one kind")

    def records_by_kind_prefix(self, kind: str, record_id_prefix: str):
        self.prefix_calls.append((kind, record_id_prefix))
        return tuple(
            record
            for record_id, record in sorted(self.records.items())
            if record_id.startswith(record_id_prefix)
        )

    def get(self, kind: str, record_id: str):
        if kind != "operation":
            raise AssertionError("unexpected record kind")
        return self.records.get(record_id)


def _bound_operation(
    step: OperationStep,
    *,
    sequence: int,
    offset: int,
) -> tuple[object, dict[str, object]]:
    event_id = f"{sequence:064x}"
    record = SimpleNamespace(
        record_id=step.operation_id,
        status="success",
        payload={"event_kind": step.event_kind},
        authority_sequence=sequence,
        authority_event_id=event_id,
        authority_offset=offset,
    )
    event = {
        "event_id": event_id,
        "event_kind": step.event_kind,
        "operation_id": step.operation_id,
        "sequence": sequence,
    }
    return record, event


class StrictOperationChainTests(unittest.TestCase):
    def test_inspection_uses_indexed_prefix_and_preserves_plan_order(self) -> None:
        predecessor = "0" * 64
        steps = (
            OperationStep("resume-z", "z_done", "run"),
            OperationStep("resume-a", "a_done", "run"),
            OperationStep("resume-m", "m_done", "close"),
        )
        records: dict[str, object] = {}
        events: dict[int, dict[str, object]] = {}
        prior = predecessor
        for position, step in enumerate(steps[:2], start=1):
            record, event = _bound_operation(
                step,
                sequence=100 + position,
                offset=position,
            )
            event["previous_event_id"] = prior
            records[step.operation_id] = record
            events[position] = event
            prior = str(event["event_id"])
        index = _MemoryIndex(records)

        self.assertEqual(
            inspect_operation_prefix(
                index=index,  # type: ignore[arg-type]
                journal=_Journal(events),
                steps=steps,
                operation_prefix="resume-",
                predecessor_sequence=100,
                predecessor_event_id=predecessor,
                current_sequence=102,
            ),
            2,
        )
        self.assertEqual(index.prefix_calls, [("operation", "resume-")])

    def test_duplicate_foreign_and_hole_semantics_remain_fail_closed(self) -> None:
        predecessor = "0" * 64
        steps = (
            OperationStep("resume-a", "a_done", "run"),
            OperationStep("resume-b", "b_done", "run"),
            OperationStep("resume-c", "c_done", "close"),
        )
        with self.assertRaisesRegex(StrictOperationChainError, "duplicate"):
            validate_operation_plan(
                (steps[0], steps[0]),
                operation_prefix="resume-",
            )

        records: dict[str, object] = {}
        events: dict[int, dict[str, object]] = {}
        prior = predecessor
        for position in (0, 2):
            step = steps[position]
            record, event = _bound_operation(
                step,
                sequence=101 + position,
                offset=position + 1,
            )
            event["previous_event_id"] = prior
            records[step.operation_id] = record
            events[position + 1] = event
            prior = str(event["event_id"])
        with self.assertRaisesRegex(StrictOperationChainError, "strict prefix"):
            inspect_operation_prefix(
                index=_MemoryIndex(records),  # type: ignore[arg-type]
                journal=_Journal(events),
                steps=steps,
                operation_prefix="resume-",
                predecessor_sequence=100,
                predecessor_event_id=predecessor,
                current_sequence=102,
            )

        records["resume-foreign"] = SimpleNamespace(record_id="resume-foreign")
        with self.assertRaisesRegex(StrictOperationChainError, "undeclared"):
            inspect_operation_prefix(
                index=_MemoryIndex(records),  # type: ignore[arg-type]
                journal=_Journal(events),
                steps=steps,
                operation_prefix="resume-",
                predecessor_sequence=100,
                predecessor_event_id=predecessor,
                current_sequence=102,
            )

    def test_cost_follows_selected_prefix_and_read_only_bytes_do_not_change(self) -> None:
        predecessor = "0" * 64
        steps = (
            OperationStep("resume-z", "z_done", "run"),
            OperationStep("resume-a", "a_done", "run"),
            OperationStep("resume-m", "m_done", "close"),
        )
        events: dict[int, dict[str, object]] = {}
        records = [
            IndexRecord(
                kind="operation",
                record_id=f"unrelated-{number:05d}",
                subject="Fixture:unrelated",
                status="success",
                fingerprint=f"unrelated-{number:05d}",
                payload={"event_kind": "unrelated"},
            )
            for number in range(5_000)
        ]
        prior = predecessor
        for position, step in enumerate(steps[:2], start=1):
            sequence = 100 + position
            event_id = f"{sequence:064x}"
            records.append(
                IndexRecord(
                    kind="operation",
                    record_id=step.operation_id,
                    subject="Fixture:resume",
                    status="success",
                    fingerprint=f"resume-{position}",
                    payload={"event_kind": step.event_kind},
                    authority_sequence=sequence,
                    authority_event_id=event_id,
                    authority_offset=position,
                )
            )
            events[position] = {
                "event_id": event_id,
                "event_kind": step.event_kind,
                "operation_id": step.operation_id,
                "previous_event_id": prior,
                "sequence": sequence,
            }
            prior = event_id

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.sqlite3"
            with LocalIndex(path) as index:
                index.rebuild(records)
                self.assertEqual(
                    index.records_by_kind_prefix_access_shape(
                        "operation",
                        "resume-",
                    ),
                    ("SEARCH:records",),
                )
            before_hash = sha256(path.read_bytes()).hexdigest()
            before_names = tuple(sorted(item.name for item in path.parent.iterdir()))

            decoded: list[str] = []
            with LocalIndex.open_read_only(
                path,
                authority_validator=lambda item: decoded.append(item.record_id),
            ) as index:
                self.assertEqual(
                    inspect_operation_prefix(
                        index=index,
                        journal=_Journal(events),
                        steps=steps,
                        operation_prefix="resume-",
                        predecessor_sequence=100,
                        predecessor_event_id=predecessor,
                        current_sequence=102,
                    ),
                    2,
                )

            self.assertEqual(
                decoded,
                ["resume-a", "resume-z", "resume-z", "resume-a"],
            )
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), before_hash)
            self.assertEqual(
                tuple(sorted(item.name for item in path.parent.iterdir())),
                before_names,
            )


if __name__ == "__main__":
    unittest.main()
