from __future__ import annotations

from dataclasses import replace
import unittest

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.permits import (
    PermitAuthority,
    PermitError,
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


if __name__ == "__main__":
    unittest.main()
