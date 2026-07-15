from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.permits import (
    PermitAuthority,
    PermitError,
    PermitKeyStore,
    PermitKind,
    PermitStatus,
    SubjectKind,
    SubjectRef,
)


class PermitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authority = PermitAuthority(b"k" * 32)
        self.subject = SubjectRef(
            kind=SubjectKind.JOB,
            subject_id="job:fixture",
            authorization_epoch=1,
            authorization_hash=canonical_digest(
                domain="auth", payload={"job": "fixture"}
            ),
        )
        self.input_hash = canonical_digest(domain="input", payload={"x": 1})
        self.permit = self.authority.issue(
            kind=PermitKind.JOB,
            subject=self.subject,
            input_hash=self.input_hash,
            actions=("start_job",),
            scope=("job",),
            issued_at_utc="2026-07-11T00:00:00Z",
            expires_at_utc="2026-07-12T00:00:00Z",
            one_shot=True,
            audit_revision=10,
        )

    def validate(self, permit=None, **overrides) -> None:
        arguments = {
            "permit": permit or self.permit,
            "expected_kind": PermitKind.JOB,
            "action": "start_job",
            "current_subject": self.subject,
            "status": PermitStatus.ISSUED,
            "now_utc": "2026-07-11T12:00:00Z",
            "required_scope": ("job",),
            "expected_input_hash": self.input_hash,
        }
        arguments.update(overrides)
        self.authority.validate(**arguments)

    def test_valid_permit_ignores_unrelated_global_revision(self) -> None:
        self.validate()
        self.assertEqual(self.permit.audit_revision, 10)

    def test_forged_stale_expired_revoked_and_replayed_are_rejected(self) -> None:
        forged = replace(self.permit, signature="0" * 64)
        stale = replace(
            self.subject,
            authorization_epoch=2,
            authorization_hash=canonical_digest(domain="auth", payload={"job": "changed"}),
        )
        cases = (
            {"permit": forged},
            {"current_subject": stale},
            {"now_utc": "2026-07-10T23:59:59Z"},
            {"now_utc": "2026-07-12T00:00:00Z"},
            {"status": PermitStatus.REVOKED},
            {"status": PermitStatus.CONSUMED},
            {"expected_kind": PermitKind.RUNTIME},
            {"action": "other"},
            {"expected_input_hash": "1" * 64},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(PermitError):
                self.validate(**overrides)


class PermitKeyStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "local" / "permit.key"

    def test_concurrent_first_creation_returns_one_durable_key(self) -> None:
        stores = tuple(PermitKeyStore(self.path) for _ in range(16))

        with ThreadPoolExecutor(max_workers=8) as pool:
            secrets = tuple(pool.map(lambda store: store.load_or_create(), stores))

        self.assertEqual(len(set(secrets)), 1)
        self.assertEqual(secrets[0], self.path.read_bytes())
        self.assertEqual(len(secrets[0]), 32)
        self.assertEqual(
            tuple(self.path.parent.glob(".permit-key.*.tmp")),
            (),
        )

    def test_public_key_path_is_never_chmodded_after_publication(self) -> None:
        with patch.object(
            Path,
            "chmod",
            side_effect=AssertionError("public path chmod is unsafe"),
        ):
            secret = PermitKeyStore(self.path).load_or_create()

        self.assertEqual(self.path.read_bytes(), secret)

    def test_invalid_or_hard_linked_key_fails_closed(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"short")
        with self.assertRaisesRegex(PermitError, "invalid"):
            PermitKeyStore(self.path).load_or_create()

        self.path.write_bytes(b"k" * 32)
        alias = self.path.with_suffix(".alias")
        os.link(self.path, alias)
        with self.assertRaisesRegex(PermitError, "hard-link alias"):
            PermitKeyStore(self.path).load_or_create()

    def test_symbolic_link_key_is_rejected(self) -> None:
        self.path.parent.mkdir(parents=True)
        outside = Path(self.temporary.name) / "outside.key"
        outside.write_bytes(b"x" * 32)
        try:
            self.path.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"symbolic links unavailable: {exc}")

        with self.assertRaisesRegex(PermitError, "link-like"):
            PermitKeyStore(self.path).load_or_create()

    def test_missing_directory_below_symbolic_link_is_not_created(self) -> None:
        outside = Path(self.temporary.name) / "outside-keys"
        outside.mkdir()
        linked_parent = Path(self.temporary.name) / "linked-keys"
        try:
            linked_parent.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symbolic links unavailable: {exc}")

        nested_key = linked_parent / "missing" / "permit.key"
        with self.assertRaisesRegex(PermitError, "link-like"):
            PermitKeyStore(nested_key).load_or_create()

        self.assertFalse((outside / "missing").exists())


if __name__ == "__main__":
    unittest.main()
