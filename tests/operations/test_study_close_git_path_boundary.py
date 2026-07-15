from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import axiom_rift.operations.study_close_git as study_close_git
from axiom_rift.operations.study_close_checkpoint import JournalDeliveryCursor
from axiom_rift.storage.journal import LEGACY_JOURNAL_RELATIVE_PATH


class StudyCloseGitPathBoundaryTests(unittest.TestCase):
    def test_local_writer_rejects_link_like_parent(self) -> None:
        with TemporaryDirectory() as root_value, TemporaryDirectory() as outside_value:
            root = Path(root_value)
            outside = Path(outside_value)
            linked = root / "local"
            try:
                linked.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")

            with self.assertRaisesRegex(OSError, "write directory is unsafe"):
                study_close_git._write_local_file_atomically(
                    linked / "receipt.json",
                    b"{}\n",
                    short_write_error="short fixture write",
                )
            self.assertEqual(tuple(outside.iterdir()), ())

    def test_sealed_verifier_construction_is_read_only(self) -> None:
        with TemporaryDirectory() as root_value:
            root = Path(root_value)
            study_close_git._sealed_journal_verifier.cache_clear()
            verifier = study_close_git._sealed_journal_verifier(str(root))
            self.assertEqual(
                verifier.path,
                root / LEGACY_JOURNAL_RELATIVE_PATH,
            )
            self.assertFalse((root / "records").exists())

    def test_suffix_scan_constructs_read_only_journal(self) -> None:
        cursor = JournalDeliveryCursor.from_events((), journal_path=None)
        with TemporaryDirectory() as root_value, patch.object(
            study_close_git,
            "DurableJournal",
            side_effect=RuntimeError("stop after construction"),
        ) as journal:
            root = Path(root_value)
            with self.assertRaisesRegex(RuntimeError, "stop after construction"):
                study_close_git._scan_tracked_journal_suffix(root, cursor)
            journal.assert_called_once_with(
                root / LEGACY_JOURNAL_RELATIVE_PATH,
                create_parent=False,
            )


if __name__ == "__main__":
    unittest.main()
