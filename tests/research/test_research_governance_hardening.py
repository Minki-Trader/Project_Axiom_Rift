from __future__ import annotations

import unittest

from axiom_rift.research import (
    DiagnosisConfidence,
    EvidenceState,
    ResearchGovernanceError,
    StudyDiagnosis,
)


class StudyDiagnosisConfidenceTests(unittest.TestCase):
    def make_diagnosis(
        self,
        *,
        evidence_state: EvidenceState,
        confidence: DiagnosisConfidence,
    ) -> StudyDiagnosis:
        return StudyDiagnosis(
            study_id="STU-CONFIDENCE",
            study_close_record_id="a" * 64,
            evidence_state=evidence_state,
            confidence=confidence,
            rationale="the bound evidence supports this narrow interpretation",
            counterfactual="one preregistered contrast would distinguish the alternatives",
            reopen_condition="reopen only after the decisive contrast exists",
        )

    def test_low_confidence_cannot_open_a_specific_layer_branch(self) -> None:
        with self.assertRaisesRegex(
            ResearchGovernanceError,
            "low-confidence diagnosis must remain not_identifiable",
        ):
            self.make_diagnosis(
                evidence_state=EvidenceState.MODEL_CAPACITY,
                confidence=DiagnosisConfidence.LOW,
            )

    def test_low_confidence_not_identifiable_is_allowed(self) -> None:
        diagnosis = self.make_diagnosis(
            evidence_state=EvidenceState.NOT_IDENTIFIABLE,
            confidence=DiagnosisConfidence.LOW,
        )
        self.assertEqual(diagnosis.evidence_state, EvidenceState.NOT_IDENTIFIABLE)

    def test_specific_bottleneck_can_use_medium_confidence(self) -> None:
        diagnosis = self.make_diagnosis(
            evidence_state=EvidenceState.TARGET_MISMATCH,
            confidence=DiagnosisConfidence.MEDIUM,
        )
        self.assertEqual(diagnosis.confidence, DiagnosisConfidence.MEDIUM)


if __name__ == "__main__":
    unittest.main()
