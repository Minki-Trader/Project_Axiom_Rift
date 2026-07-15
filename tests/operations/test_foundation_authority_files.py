from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.operations.foundation_authority_files import (
    FoundationAuthorityFileError,
    canonical_foundation_path,
    hash_foundation_file,
    read_foundation_file,
    replace_foundation_file,
)


class FoundationAuthorityFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "contracts" / "operations.yaml"
        self.path.parent.mkdir()
        self.original = b"schema: original\n"
        self.path.write_bytes(self.original)

    def test_read_hash_and_cas_replace_exact_file(self) -> None:
        self.assertEqual(
            canonical_foundation_path(
                self.root,
                "contracts/operations.yaml",
            ),
            self.path,
        )
        self.assertEqual(
            read_foundation_file(self.root, "contracts/operations.yaml"),
            self.original,
        )
        original_hash = sha256(self.original).hexdigest()
        self.assertEqual(
            hash_foundation_file(self.root, "contracts/operations.yaml"),
            original_hash,
        )

        replacement = b"schema: replacement\n"
        replace_foundation_file(
            self.root,
            "contracts/operations.yaml",
            replacement,
            expected_current_sha256=original_hash,
        )
        self.assertEqual(self.path.read_bytes(), replacement)

    def test_cas_mismatch_preserves_original_bytes(self) -> None:
        with self.assertRaisesRegex(
            FoundationAuthorityFileError,
            "replacement failed",
        ):
            replace_foundation_file(
                self.root,
                "contracts/operations.yaml",
                b"schema: replacement\n",
                expected_current_sha256="0" * 64,
            )
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_noncanonical_paths_are_rejected(self) -> None:
        for relative in (
            "../outside.yaml",
            "contracts\\operations.yaml",
            "/contracts/operations.yaml",
        ):
            with self.subTest(relative=relative), self.assertRaises(
                FoundationAuthorityFileError
            ):
                canonical_foundation_path(self.root, relative)

    def test_hard_link_alias_is_rejected_without_mutation(self) -> None:
        alias = self.root / "contracts" / "alias.yaml"
        os.link(self.path, alias)
        with self.assertRaisesRegex(
            FoundationAuthorityFileError,
            "unsafe or unavailable",
        ):
            read_foundation_file(self.root, "contracts/operations.yaml")
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(alias.read_bytes(), self.original)

    def test_file_symlink_is_rejected_without_external_mutation(self) -> None:
        outside = self.root / "outside.yaml"
        outside.write_bytes(b"outside\n")
        self.path.unlink()
        try:
            self.path.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"file symlinks unavailable: {exc}")
        with self.assertRaises(FoundationAuthorityFileError):
            replace_foundation_file(
                self.root,
                "contracts/operations.yaml",
                b"replacement\n",
                expected_current_sha256=sha256(b"outside\n").hexdigest(),
            )
        self.assertEqual(outside.read_bytes(), b"outside\n")


if __name__ == "__main__":
    unittest.main()
