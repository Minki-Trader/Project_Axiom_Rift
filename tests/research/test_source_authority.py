from __future__ import annotations

from hashlib import sha256
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.source_authority import (
    AUTHORITY_RECOVERY_POLICY,
    SourceAuthorityAuditManifest,
    SourceAuthorityInvalidation,
    SourceAuthorityLatch,
    SourceAuthorityReason,
    SourceAuthoritySurface,
)


class SourceAuthorityTests(unittest.TestCase):
    def manifest(
        self,
        *,
        surface: SourceAuthoritySurface = SourceAuthoritySurface.AVAILABILITY,
    ) -> SourceAuthorityAuditManifest:
        return SourceAuthorityAuditManifest(
            report_artifact_hash="a" * 64,
            report_finding_id="SOURCE-AUTH-001",
            source_contract_id="source:" + "b" * 64,
            source_state_record_id="c" * 64,
            surface=surface,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect="first availability is not proven",
            observed_at_utc="2026-07-13T00:00:00Z",
        )

    def invalidation(
        self,
        manifest: SourceAuthorityAuditManifest,
    ) -> SourceAuthorityInvalidation:
        return SourceAuthorityInvalidation(
            source_contract_id=manifest.source_contract_id,
            source_state_record_id=manifest.source_state_record_id,
            audit_artifact_hash=sha256(
                canonical_bytes(manifest.to_identity_payload())
            ).hexdigest(),
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=manifest.reason_code,
            observed_defect=manifest.observed_defect,
            observed_at_utc=manifest.observed_at_utc,
        )

    def test_manifest_round_trip_binds_the_exact_finding(self) -> None:
        manifest = self.manifest()
        parsed = SourceAuthorityAuditManifest.from_bytes(
            canonical_bytes(manifest.to_identity_payload())
        )
        self.assertEqual(parsed, manifest)
        self.invalidation(manifest).require_manifest(parsed)

    def test_arbitrary_artifact_and_changed_finding_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SourceAuthorityAuditManifest.from_bytes(
                canonical_bytes({"schema": "unrelated_audit_artifact.v1"})
            )
        manifest = self.manifest(surface=SourceAuthoritySurface.CLOCK)
        with self.assertRaisesRegex(ValueError, "does not bind"):
            self.invalidation(manifest).require_manifest(manifest)

    def test_latch_round_trip_preserves_new_contract_only_recovery(self) -> None:
        manifest = self.manifest()
        invalidation = self.invalidation(manifest)
        latch = SourceAuthorityLatch.bind(
            invalidation=invalidation,
            manifest=manifest,
        )
        payload = latch.to_identity_payload()
        self.assertEqual(payload["recovery_policy"], AUTHORITY_RECOVERY_POLICY)
        self.assertEqual(SourceAuthorityLatch.from_mapping(payload), latch)
        tampered = {**payload, "recovery_policy": "same_contract_recertification"}
        with self.assertRaisesRegex(ValueError, "policy"):
            SourceAuthorityLatch.from_mapping(tampered)

    def test_report_binding_requires_facts_inside_one_exact_ascii_finding(self) -> None:
        manifest = self.manifest()
        valid = (
            "# Source Audit\n\n"
            "- SOURCE-AUTH-001:\n"
            f"  {manifest.source_contract_id},\n"
            f"  audited head {manifest.source_state_record_id};\n"
        ).encode("ascii")
        manifest.require_report(valid)

        scattered = (
            "# Source Audit\n\n"
            "- SOURCE-AUTH-001:\n"
            "  unrelated finding body;\n\n"
            f"{manifest.source_contract_id}\n"
            f"audited head {manifest.source_state_record_id}\n"
        ).encode("ascii")
        with self.assertRaisesRegex(ValueError, "exact bound facts"):
            manifest.require_report(scattered)

        duplicated = valid + valid
        with self.assertRaisesRegex(ValueError, "absent or duplicated"):
            manifest.require_report(duplicated)

        with self.assertRaisesRegex(ValueError, "ASCII"):
            manifest.require_report(valid + b"non-ascii: \xc3\xa9\n")


if __name__ == "__main__":
    unittest.main()
