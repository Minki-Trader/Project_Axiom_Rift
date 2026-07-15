from __future__ import annotations

import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import axiom_rift.storage.atomic_file as atomic_file_module
from axiom_rift.storage.atomic_file import (
    AtomicFileError,
    publish_stable_regular_file_if_changed,
)


class AtomicFileConditionalPublicationTests(unittest.TestCase):
    def test_normal_publication_is_exact_and_reports_changed(self) -> None:
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / "nested" / "projection.txt"
            initial = b"initial publication\n"
            replacement = b"exact replacement\n"

            self.assertTrue(
                publish_stable_regular_file_if_changed(target, initial)
            )
            self.assertEqual(target.read_bytes(), initial)
            self.assertTrue(
                publish_stable_regular_file_if_changed(target, replacement)
            )

            self.assertEqual(target.read_bytes(), replacement)
            self.assertEqual(target.stat().st_nlink, 1)
            self.assertEqual(tuple(target.parent.glob(".*.tmp")), ())

    def test_identical_target_is_a_write_free_no_op(self) -> None:
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / "projection.txt"
            content = b"already exact\n"
            target.write_bytes(content)
            identity = (target.stat().st_dev, target.stat().st_ino)

            with patch.object(
                atomic_file_module.tempfile,
                "mkstemp",
                side_effect=AssertionError("no-op created a temporary"),
            ):
                self.assertFalse(
                    publish_stable_regular_file_if_changed(target, content)
                )

            self.assertEqual(target.read_bytes(), content)
            self.assertEqual(
                (target.stat().st_dev, target.stat().st_ino),
                identity,
            )

    def test_existing_change_before_publication_check_is_not_overwritten(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / "projection.txt"
            target.write_bytes(b"initial\n")
            manual = b"manual concurrent edit\n"
            original_snapshot = atomic_file_module._stable_snapshot
            target_snapshots = 0

            def snapshot_with_change(
                path: Path,
                *,
                max_bytes: int,
                missing_ok: bool,
            ) -> tuple[bytes, tuple[int, int, int, int, int, int]] | None:
                nonlocal target_snapshots
                if Path(path) == target:
                    target_snapshots += 1
                    if target_snapshots == 2:
                        target.write_bytes(manual)
                return original_snapshot(
                    path,
                    max_bytes=max_bytes,
                    missing_ok=missing_ok,
                )

            with (
                patch.object(
                    atomic_file_module,
                    "_stable_snapshot",
                    side_effect=snapshot_with_change,
                ),
                self.assertRaisesRegex(AtomicFileError, "target changed"),
            ):
                publish_stable_regular_file_if_changed(target, b"new bytes\n")

            self.assertEqual(target.read_bytes(), manual)

    def test_missing_target_creation_race_is_not_overwritten(self) -> None:
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / "projection.txt"
            manual = b"concurrent creator\n"
            original_publish = atomic_file_module._publish_missing_target

            def publish_after_concurrent_create(
                temporary_path: Path,
                target_path: Path,
                *,
                temporary_identity: tuple[int, int],
                parent_identity: tuple[int, int],
            ) -> None:
                target_path.write_bytes(manual)
                original_publish(
                    temporary_path,
                    target_path,
                    temporary_identity=temporary_identity,
                    parent_identity=parent_identity,
                )

            with (
                patch.object(
                    atomic_file_module,
                    "_publish_missing_target",
                    side_effect=publish_after_concurrent_create,
                ),
                self.assertRaisesRegex(AtomicFileError, "was created"),
            ):
                publish_stable_regular_file_if_changed(target, b"new bytes\n")

            self.assertEqual(target.read_bytes(), manual)

    def test_link_alias_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside.txt"
            outside.write_bytes(b"outside\n")
            linked = root / "linked.txt"
            try:
                linked.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            with self.assertRaisesRegex(AtomicFileError, "regular single-link"):
                publish_stable_regular_file_if_changed(linked, b"replacement\n")
            self.assertEqual(outside.read_bytes(), b"outside\n")

    def test_hard_link_alias_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "projection.txt"
            alias = root / "projection.alias"
            target.write_bytes(b"original\n")
            os.link(target, alias)

            with self.assertRaisesRegex(AtomicFileError, "regular single-link"):
                publish_stable_regular_file_if_changed(target, b"replacement\n")

            self.assertEqual(target.read_bytes(), b"original\n")
            self.assertEqual(alias.read_bytes(), b"original\n")

    def test_parent_identity_change_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "projection.txt"
            original_identity = atomic_file_module._directory_identity
            identity_calls = 0

            def changed_parent_identity(path: Path) -> tuple[int, int]:
                nonlocal identity_calls
                identity = original_identity(path)
                identity_calls += 1
                if identity_calls >= 2:
                    return identity[0], identity[1] + 1
                return identity

            with (
                patch.object(
                    atomic_file_module,
                    "_directory_identity",
                    side_effect=changed_parent_identity,
                ),
                self.assertRaisesRegex(AtomicFileError, "directory changed"),
            ):
                publish_stable_regular_file_if_changed(target, b"new bytes\n")
            self.assertFalse(target.exists())

    def test_reparse_like_target_is_rejected_where_flag_is_available(self) -> None:
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if not reparse_flag:
            self.skipTest("reparse-point metadata flag unavailable")
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / "projection.txt"
            target.write_bytes(b"original\n")
            metadata = target.lstat()
            simulated = SimpleNamespace(
                st_mode=metadata.st_mode,
                st_file_attributes=(
                    getattr(metadata, "st_file_attributes", 0) | reparse_flag
                ),
                st_nlink=metadata.st_nlink,
                st_dev=metadata.st_dev,
                st_ino=metadata.st_ino,
                st_size=metadata.st_size,
                st_mtime_ns=metadata.st_mtime_ns,
                st_ctime_ns=metadata.st_ctime_ns,
            )
            original_lstat = Path.lstat

            def simulated_lstat(path: Path) -> os.stat_result | SimpleNamespace:
                if path == target:
                    return simulated
                return original_lstat(path)

            with (
                patch.object(Path, "lstat", simulated_lstat),
                self.assertRaisesRegex(AtomicFileError, "regular single-link"),
            ):
                publish_stable_regular_file_if_changed(target, b"replacement\n")

            self.assertEqual(target.read_bytes(), b"original\n")


if __name__ == "__main__":
    unittest.main()
