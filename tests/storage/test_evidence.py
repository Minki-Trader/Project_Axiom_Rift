from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.storage.evidence import EvidenceStore
from axiom_rift.storage.path_boundary import (
    PathBoundaryError,
    ensure_link_free_directory_chain,
)


class EvidenceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "evidence"
        self.store = EvidenceStore(self.root)

    def test_finalize_and_read_use_the_exact_content_identity(self) -> None:
        content = b'[{"schema":"evidence-fixture.v1"}]\n'
        artifact = self.store.finalize(content)

        self.assertEqual(artifact.sha256, sha256(content).hexdigest())
        self.assertEqual(artifact.size_bytes, len(content))
        self.assertEqual(self.store.read_verified(artifact.sha256), content)
        self.assertEqual(self.store.verify(artifact.sha256), artifact)

    def test_verified_path_is_public_but_still_requires_verified_bytes(self) -> None:
        content = b'verified path consumer\n'
        artifact = self.store.finalize(content)

        path = self.store.verified_path(artifact.sha256)

        self.assertEqual(path, self.root / artifact.relative_path)
        self.assertEqual(path.read_bytes(), content)

        path.write_bytes(b"changed after path handoff\n")
        with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
            self.store.verified_path(artifact.sha256)

    def test_concurrent_same_content_publication_is_idempotent(self) -> None:
        content = b"concurrent immutable evidence\n"

        with ThreadPoolExecutor(max_workers=8) as pool:
            artifacts = tuple(pool.map(self.store.finalize, (content,) * 24))

        self.assertEqual({artifact.sha256 for artifact in artifacts}, {sha256(content).hexdigest()})
        self.assertEqual(self.store.read_verified(artifacts[0].sha256), content)
        target = self.root / artifacts[0].relative_path
        self.assertEqual(target.stat().st_nlink, 1)

    def test_existing_wrong_bytes_are_never_overwritten(self) -> None:
        content = b"expected immutable evidence\n"
        identity = sha256(content).hexdigest()
        target = self.root / "sha256" / identity[:2] / identity
        target.parent.mkdir(parents=True)
        target.write_bytes(b"wrong bytes\n")

        with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
            self.store.finalize(content)

        self.assertEqual(target.read_bytes(), b"wrong bytes\n")

    def test_hard_link_alias_is_rejected_until_removed(self) -> None:
        content = b"single-link evidence\n"
        artifact = self.store.finalize(content)
        target = self.root / artifact.relative_path
        alias = target.with_name(f"{target.name}.alias")
        os.link(target, alias)

        with self.assertRaisesRegex(RuntimeError, "hard-link alias"):
            self.store.read_verified(artifact.sha256)

        alias.unlink()
        self.assertEqual(self.store.read_verified(artifact.sha256), content)

    def test_symbolic_link_artifact_is_rejected(self) -> None:
        content = b"symbolic-link target\n"
        identity = sha256(content).hexdigest()
        outside = Path(self.temporary.name) / "outside"
        outside.write_bytes(content)
        target = self.root / "sha256" / identity[:2] / identity
        target.parent.mkdir(parents=True)
        try:
            target.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"symbolic links unavailable: {exc}")

        with self.assertRaisesRegex(RuntimeError, "link-like"):
            self.store.verify(identity)

    def test_symbolic_link_store_root_is_rejected(self) -> None:
        real_root = Path(self.temporary.name) / "real-evidence"
        real_root.mkdir()
        linked_root = Path(self.temporary.name) / "linked-evidence"
        try:
            linked_root.symlink_to(real_root, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symbolic links unavailable: {exc}")

        with self.assertRaisesRegex(RuntimeError, "directory chain"):
            EvidenceStore(linked_root).finalize(b"must not follow a linked root")

    def test_missing_directory_below_symbolic_link_is_not_created(self) -> None:
        outside = Path(self.temporary.name) / "outside-evidence"
        outside.mkdir()
        linked_root = Path(self.temporary.name) / "linked-evidence"
        try:
            linked_root.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symbolic links unavailable: {exc}")

        with self.assertRaisesRegex(RuntimeError, "directory chain"):
            EvidenceStore(linked_root / "missing").finalize(
                b"must not create below a linked ancestor"
            )

        self.assertFalse((outside / "missing").exists())

    def test_link_like_existing_ancestor_is_rejected_before_creation(self) -> None:
        linked = Path(os.path.abspath(Path(self.temporary.name) / "linked"))
        target = linked / "missing"
        real_lstat = Path.lstat
        link_metadata = os.stat_result(
            (stat.S_IFLNK | 0o777, 0, 0, 1, 0, 0, 0, 0, 0, 0)
        )

        def simulated_lstat(path: Path) -> os.stat_result:
            if path == target:
                raise FileNotFoundError(path)
            if path == linked:
                return link_metadata
            return real_lstat(path)

        with (
            patch.object(Path, "lstat", simulated_lstat),
            patch.object(Path, "mkdir") as mkdir,
            self.assertRaisesRegex(PathBoundaryError, "link-like"),
        ):
            ensure_link_free_directory_chain(target)

        mkdir.assert_not_called()


if __name__ == "__main__":
    unittest.main()
