from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.runtime.guards import (
    CandidateBinding,
    EvidenceDepth,
    ReleaseEvidence,
    RuntimeClaimError,
    RuntimeClaimGuard,
    seal_holdout_fixture,
)
from axiom_rift.storage.evidence import EvidenceStore


class RuntimeGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = CandidateBinding(
            candidate_id="candidate:fixture",
            executable_id="executable:fixture",
            frozen=True,
            source_bindings=(),
        )

    def test_discovery_cannot_enter_candidate_bound_runtime(self) -> None:
        with self.assertRaises(RuntimeClaimError):
            RuntimeClaimGuard.require_entry(
                depth=EvidenceDepth.DISCOVERY,
                candidate=self.candidate,
            )
        RuntimeClaimGuard.require_entry(
            depth=EvidenceDepth.EXECUTION_PROOF,
            candidate=self.candidate,
        )

    def test_release_evidence_shape_is_non_compensatory(self) -> None:
        with self.assertRaises(RuntimeClaimError):
            ReleaseEvidence(completion_record_ids=())
        complete = ReleaseEvidence(completion_record_ids=("completion:fixture",))
        RuntimeClaimGuard.require_release(
            candidate=self.candidate,
            evidence=complete,
        )

    def test_restricted_confirmation_and_sealed_ingestion_boundaries(self) -> None:
        self.assertFalse(
            RuntimeClaimGuard.restricted_confirmation_is_untouched(
                observed=True, informed_redesign=True
            )
        )
        with TemporaryDirectory() as root:
            manifest = seal_holdout_fixture(
                EvidenceStore(Path(root) / "evidence"), b"hidden fixture values"
            )
            self.assertFalse(manifest.value_exposed)
            self.assertEqual(manifest.holdout_reveal_delta, 0)
            self.assertEqual(manifest.scientific_trial_delta, 0)


if __name__ == "__main__":
    unittest.main()
