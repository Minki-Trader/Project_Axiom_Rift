from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "apply_project_goal_audit_v1.py"


def load_script():
    spec = importlib.util.spec_from_file_location(
        "apply_project_goal_audit_v1_tested",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeIndex:
    records: dict[str, object] = {}

    def __init__(self, _path: object) -> None:
        pass

    @classmethod
    def open_read_only(cls, path: object):
        return cls(path)

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def records_by_kind(self, kind: str):
        if kind != "operation":
            return ()
        return tuple(self.records.values())

    def records_by_kind_prefix(self, kind: str, prefix: str):
        return tuple(
            record
            for record in self.records_by_kind(kind)
            if record.record_id.startswith(prefix)
        )

    def get(self, kind: str, record_id: str):
        if kind != "operation":
            return None
        return self.records.get(record_id)


class FakeJournal:
    def __init__(self, events: dict[int, dict[str, object]]) -> None:
        self.events = events

    def read_event_at(
        self,
        *,
        offset: int,
        expected_sequence: int,
        expected_event_id: str,
    ):
        event = self.events[offset]
        if (
            event["sequence"] != expected_sequence
            or event["event_id"] != expected_event_id
        ):
            raise AssertionError("fake authority binding differs")
        return event


class ProjectGoalAuditOrchestratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_script()

    def test_fixed_plan_has_one_strict_33_step_chain(self) -> None:
        steps = self.module.correction_steps()
        self.assertEqual(len(steps), 33)
        self.assertEqual(
            [step.event_kind for step in steps[:8]],
            [
                "portfolio_decision_withdrawn",
                "authority_migrated",
                "research_protocol_activated",
                *("source_authority_suspended_from_audit" for _ in range(5)),
            ],
        )
        self.assertEqual(
            steps[8].operation_id,
            "project-goal-audit-v1-historical-001-020",
        )
        self.assertEqual(
            steps[-2].operation_id,
            "project-goal-audit-v1-historical-461-470",
        )
        self.assertEqual(steps[-1].event_kind, "initiative_closed")
        self.assertTrue(
            all("apply-authority" not in step.operation_id for step in steps)
        )

    def test_source_corrections_bind_exact_report_and_timestamp(self) -> None:
        report_hash = "a" * 64
        corrections = self.module.build_source_corrections(report_hash)
        self.assertEqual(len(corrections), 5)
        self.assertEqual(
            {item.manifest.report_artifact_hash for item in corrections},
            {report_hash},
        )
        self.assertEqual(
            {item.manifest.observed_at_utc for item in corrections},
            {"2026-07-13T14:34:18Z"},
        )
        self.assertEqual(
            len({item.invalidation.identity for item in corrections}),
            5,
        )
        self.assertEqual(
            {
                item.spec.source_state_record_id
                for item in corrections
            },
            {
                item.invalidation.source_state_record_id
                for item in corrections
            },
        )

    def test_report_freeze_rejects_a_missing_exact_source_head(self) -> None:
        relative = self.module.AUDIT_REPORT_RELATIVE_PATH
        source = (REPO_ROOT / relative).read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / relative
            target.parent.mkdir(parents=True)
            target.write_bytes(source)
            content, digest = self.module.read_frozen_audit_report(root)
            self.assertEqual(content, source)
            self.assertEqual(len(digest), 64)
            head = self.module.SOURCE_CORRECTION_SPECS[0].source_state_record_id
            target.write_bytes(source.replace(head.encode("ascii"), b"0" * 64))
            with self.assertRaisesRegex(RuntimeError, "frozen correction basis"):
                self.module.read_frozen_audit_report(root)

    def test_prefix_inspection_rejects_standalone_authority_or_a_hole(self) -> None:
        steps = self.module.correction_steps()

        def operation(position: int):
            step = steps[position]
            sequence = self.module.EXPECTED_INITIAL_REVISION + position + 1
            return SimpleNamespace(
                kind="operation",
                record_id=step.operation_id,
                status="success",
                payload={"event_kind": step.event_kind},
                authority_sequence=sequence,
                authority_event_id=f"event-{sequence}",
                authority_offset=sequence,
            )

        def writer_for(positions: tuple[int, ...]):
            events = {}
            FakeIndex.records = {}
            for position in positions:
                record = operation(position)
                FakeIndex.records[record.record_id] = record
                events[record.authority_offset] = {
                    "event_id": record.authority_event_id,
                    "event_kind": record.payload["event_kind"],
                    "operation_id": record.record_id,
                    "sequence": record.authority_sequence,
                }
            return SimpleNamespace(index_path=Path("unused"), journal=FakeJournal(events))

        with patch.object(self.module, "LocalIndex", FakeIndex):
            self.assertEqual(
                self.module.inspect_correction_prefix(writer_for((0, 1, 2))),
                3,
            )
            with self.assertRaisesRegex(RuntimeError, "strict prefix"):
                self.module.inspect_correction_prefix(writer_for((1,)))
            with self.assertRaisesRegex(RuntimeError, "strict prefix"):
                self.module.inspect_correction_prefix(writer_for((0, 2)))

    def test_historical_chunks_are_fixed_twenty_item_units(self) -> None:
        values = tuple(range(470))
        chunks = self.module.request_chunks(values, size=20)
        self.assertEqual(len(chunks), 24)
        self.assertEqual(tuple(len(chunk) for chunk in chunks), (20,) * 23 + (10,))
        self.assertEqual(tuple(item for chunk in chunks for item in chunk), values)

    def test_completed_boundary_accepts_a_legal_later_suffix(self) -> None:
        boundary = self.module.EXPECTED_INITIAL_REVISION + len(
            self.module.correction_steps()
        )
        close_event = {
            "sequence": boundary,
            "event_id": "a" * 64,
            "payload": {"outcome": "superseded"},
            "control": {
                "next_action": self.module.EXPECTED_FINAL_ACTION,
                "scientific": {
                    "active_mission": self.module.EXPECTED_MISSION_ID,
                    "active_initiative": None,
                    "holdout_reveals": 0,
                    "claim": "none",
                },
            },
        }
        for suffix in (0, 1, 20, 10_000):
            with self.subTest(suffix=suffix):
                current = {
                    "revision": boundary + suffix,
                    "heads": {"journal": {"sequence": boundary + suffix}},
                }
                self.assertEqual(
                    self.module.validate_completed_correction_suffix_boundary(
                        current=current,
                        close_event=close_event,
                        boundary_revision=boundary,
                    ),
                    suffix,
                )

    def test_completed_boundary_rejects_a_foreign_or_rewound_head(self) -> None:
        boundary = self.module.EXPECTED_INITIAL_REVISION + len(
            self.module.correction_steps()
        )
        close_event = {
            "sequence": boundary,
            "event_id": "a" * 64,
            "payload": {"outcome": "superseded"},
            "control": {
                "next_action": self.module.EXPECTED_FINAL_ACTION,
                "scientific": {
                    "active_mission": self.module.EXPECTED_MISSION_ID,
                    "active_initiative": None,
                    "holdout_reveals": 0,
                    "claim": "none",
                },
            },
        }
        invalid = (
            {"revision": boundary - 1, "heads": {"journal": {"sequence": boundary - 1}}},
            {"revision": boundary + 1, "heads": {"journal": {"sequence": boundary}}},
        )
        for current in invalid:
            with self.subTest(current=current):
                with self.assertRaisesRegex(RuntimeError, "legal correction suffix"):
                    self.module.validate_completed_correction_suffix_boundary(
                        current=current,
                        close_event=close_event,
                        boundary_revision=boundary,
                    )


if __name__ == "__main__":
    unittest.main()
