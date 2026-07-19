from __future__ import annotations

import pytest

from axiom_rift.operations.study_diagnosis_admission import (
    StudyDiagnosisAdmissionError,
    require_primary_control_consistency,
)
from axiom_rift.research.governance import (
    DiagnosisConfidence,
    EvidenceState,
    StudyDiagnosis,
)


def _diagnosis(
    *,
    state: EvidenceState,
    reason: str | None,
    supported: tuple[str, ...] = (),
    contradicted: tuple[str, ...] = (),
    unresolved: tuple[str, ...] = (),
) -> StudyDiagnosis:
    return StudyDiagnosis(
        study_id="STU-ADMISSION",
        study_close_record_id="a" * 64,
        evidence_state=state,
        confidence=DiagnosisConfidence.HIGH,
        rationale="exact prospective diagnosis",
        counterfactual="a distinct mechanism could change the result",
        reopen_condition="reopen only with exact new evidence",
        diagnosis_reason_code=reason,
        supported_claim_ids=supported,
        contradicted_claim_ids=contradicted,
        unresolved_claim_ids=unresolved,
    )


def test_component_positive_cannot_compensate_for_failed_primary_control() -> None:
    diagnosis = _diagnosis(
        state=EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION,
        reason="component_metrics_positive",
        supported=("after_cost_fixed_lot_economics",),
        contradicted=("registered_control_contrast",),
    )
    with pytest.raises(
        StudyDiagnosisAdmissionError,
        match="requires supported registered control contrast",
    ):
        require_primary_control_consistency(diagnosis, claim_scoped=None)


def test_claim_scoped_confirmation_with_supported_control_is_admitted() -> None:
    diagnosis = _diagnosis(
        state=EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION,
        reason="all_decisive_claims_supported",
        supported=(
            "after_cost_fixed_lot_economics",
            "registered_control_contrast",
        ),
    )
    require_primary_control_consistency(diagnosis, claim_scoped=None)


def test_uniform_control_contradiction_reason_cannot_claim_support() -> None:
    diagnosis = _diagnosis(
        state=EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION,
        reason="registered_control_contrast_uniformly_contradicted",
        supported=("registered_control_contrast",),
    )
    with pytest.raises(StudyDiagnosisAdmissionError):
        require_primary_control_consistency(diagnosis, claim_scoped=None)


def test_legacy_diagnosis_without_claim_basis_remains_reconstructible() -> None:
    diagnosis = _diagnosis(
        state=EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION,
        reason=None,
    )
    require_primary_control_consistency(diagnosis, claim_scoped=None)
