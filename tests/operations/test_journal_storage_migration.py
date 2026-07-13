from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.operations.writer import InjectedCrash, StateWriter
from axiom_rift.storage.journal import DurableJournal


FIXED_NOW = "2026-07-13T00:00:00Z"
REPO_ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_PATHS = (
    "OPERATING_DIRECTION.md",
    "contracts/operations.yaml",
    "contracts/science.yaml",
    "contracts/evidence.yaml",
    "contracts/runtime.yaml",
    "foundation/market.yaml",
    "foundation/environment.yaml",
    "foundation/data.yaml",
    "foundation/data_exposure.yaml",
    "foundation/prior_scientific_memory.yaml",
    "foundation/origin.yaml",
)


class JournalStorageMigrationTests(unittest.TestCase):
    def make_writer(self, root: Path) -> StateWriter:
        for relative in AUTHORITY_PATHS:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            copyfile(REPO_ROOT / relative, target)
        writer = StateWriter(
            root,
            clock=lambda: FIXED_NOW,
            engineering_fixture=True,
            foundation_root=root,
        )
        writer.initialize_ready()
        return writer

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.writer = self.make_writer(self.root)

    def migrate(
        self, writer: StateWriter | None = None, *, crash_after: str | None = None
    ):
        target = self.writer if writer is None else writer
        return target.migrate_journal_storage(
            reason="bound exact legacy bytes to immutable Journal segments",
            operation_id="journal-storage-segmentation-v1",
            crash_after=crash_after,
        )

    def test_typed_migration_preserves_scientific_body_and_rebuilds_index(self) -> None:
        before_control = deepcopy(self.writer.read_control())
        assert before_control is not None
        legacy = (self.root / "records" / "journal.jsonl").read_bytes()
        first_event = self.writer.journal.read_all()[0]

        result = self.migrate()

        after_control = self.writer.read_control()
        assert after_control is not None
        self.assertEqual(result.revision, 2)
        self.assertEqual(after_control["scientific"], before_control["scientific"])
        self.assertEqual(after_control["next_action"], before_control["next_action"])
        self.assertEqual(after_control["authority"], before_control["authority"])
        self.assertEqual(after_control["revision"], before_control["revision"] + 1)
        self.assertFalse((self.root / "records" / "journal.jsonl").exists())
        sealed = self.root / "records" / "journal" / "journal-000001.jsonl"
        self.assertTrue(sealed.read_bytes().startswith(legacy))
        events = self.writer.journal.read_all()
        self.assertEqual(events[0], first_event)
        self.assertEqual(events[-1]["event_kind"], "journal_storage_migrated")
        self.assertEqual(events[-1]["payload"]["trial_delta"], 0)
        self.assertEqual(events[-1]["payload"]["holdout_delta"], 0)
        report = self.writer.recover()
        self.assertEqual(report["journal_sequence"], 2)
        self.assertFalse(report["control_repaired"])
        self.assertFalse(report["index_rebuilt"])

    def test_migration_is_idempotent_after_activation(self) -> None:
        first = self.migrate()
        second = self.migrate()
        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(second.event_id, first.event_id)
        self.assertEqual(len(self.writer.journal.read_all()), 2)

    def test_every_transaction_crash_boundary_recovers_without_duplicate_event(self) -> None:
        crash_points = (
            "after_journal",
            "after_segment",
            "after_seal",
            "after_active",
            "after_manifest",
            "after_legacy_removal",
            "after_journal_storage",
            "after_cursor",
            "after_index",
        )
        for crash_after in crash_points:
            with self.subTest(crash_after=crash_after):
                with TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    writer = self.make_writer(root)
                    with self.assertRaisesRegex(InjectedCrash, crash_after):
                        self.migrate(writer, crash_after=crash_after)
                    recovered = StateWriter(
                        root,
                        clock=lambda: FIXED_NOW,
                        engineering_fixture=True,
                        foundation_root=root,
                    )
                    report = recovered.recover()
                    self.assertEqual(report["journal_sequence"], 2)
                    self.assertEqual(len(recovered.journal.read_all()), 2)
                    self.assertEqual(
                        recovered.journal.read_all()[-1]["event_kind"],
                        "journal_storage_migrated",
                    )
                    control = recovered.read_control()
                    assert control is not None
                    self.assertEqual(control["revision"], 2)
                    retried = self.migrate(recovered)
                    self.assertTrue(retried.reused)
                    self.assertEqual(len(recovered.journal.read_all()), 2)

    def test_writer_recovers_control_and_index_after_cross_segment_append(self) -> None:
        self.migrate()
        direction = (self.root / "OPERATING_DIRECTION.md").read_bytes()
        with patch.object(DurableJournal, "MAX_SEGMENT_EVENTS", 1):
            self.writer.migrate_authority(
                replacements={
                    "OPERATING_DIRECTION.md": direction
                    + b"\n<!-- segmented migration one -->\n"
                },
                reason="exercise first segmented state transition",
                operation_id="segmented-authority-one",
            )
            with self.assertRaisesRegex(InjectedCrash, "after_journal"):
                self.writer.migrate_authority(
                    replacements={
                        "OPERATING_DIRECTION.md": direction
                        + b"\n<!-- segmented migration two -->\n"
                    },
                    reason="exercise cross segment recovery",
                    operation_id="segmented-authority-two",
                    crash_after="after_journal",
                )
        manifest = self.root / "records" / "journal" / "manifest.json"
        self.assertIn(b'"id":"000003"', manifest.read_bytes())
        recovered = StateWriter(
            self.root,
            clock=lambda: FIXED_NOW,
            engineering_fixture=True,
            foundation_root=self.root,
        )
        report = recovered.recover()
        self.assertEqual(report["journal_sequence"], 4)
        self.assertTrue(report["control_repaired"])
        self.assertTrue(report["index_rebuilt"])
        events = recovered.journal.read_all()
        self.assertEqual([event["sequence"] for event in events], [1, 2, 3, 4])
        self.assertEqual(
            events[-1]["journal_offset"],
            (
                self.root
                / "records"
                / "journal"
                / "journal-000001.jsonl"
            ).stat().st_size
            + (
                self.root
                / "records"
                / "journal"
                / "journal-000002.jsonl"
            ).stat().st_size,
        )


if __name__ == "__main__":
    unittest.main()
