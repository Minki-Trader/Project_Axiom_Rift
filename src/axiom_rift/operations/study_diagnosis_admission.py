"""Prospective admission rules for claim-scoped Study diagnoses.

Historical diagnosis objects remain reconstructible even when later audit
found them scientifically wrong.  These checks therefore live at the Writer
admission boundary rather than in the immutable ``StudyDiagnosis`` type.
"""

from __future__ import annotations

from axiom_rift.research.governance import EvidenceState, StudyDiagnosis
from axiom_rift.research.scientific_diagnosis import ScientificDiagnosisPattern


_PRIMARY_CONTROL_CLAIM = "registered_control_contrast"
_CONTROL_CONTRADICTED_REASON = (
    "registered_control_contrast_uniformly_contradicted"
)


class StudyDiagnosisAdmissionError(ValueError):
    """A new diagnosis contradicts its own primary-control claim basis."""


def require_primary_control_consistency(
    diagnosis: StudyDiagnosis,
    *,
    claim_scoped: ScientificDiagnosisPattern | None,
) -> None:
    """Reject component-positive compensation at the prospective boundary.

    A legacy v1 diagnosis with no claim inventory remains readable.  Once a
    caller supplies a v2 claim basis, however, axis-level confirmation requires
    explicit support for the registered control contrast.  Supported economics
    or stability components cannot compensate for a contradicted or unresolved
    primary contrast.
    """

    if not isinstance(diagnosis, StudyDiagnosis):
        raise TypeError("diagnosis must be a StudyDiagnosis")
    if claim_scoped is not None and not isinstance(
        claim_scoped, ScientificDiagnosisPattern
    ):
        raise TypeError("claim_scoped must be a ScientificDiagnosisPattern")

    supported = set(diagnosis.supported_claim_ids)
    contradicted = set(diagnosis.contradicted_claim_ids)
    unresolved = set(diagnosis.unresolved_claim_ids)
    has_claim_basis = diagnosis.diagnosis_reason_code is not None

    if claim_scoped is not None and (
        diagnosis.evidence_state is not claim_scoped.evidence_state
        or diagnosis.diagnosis_reason_code != claim_scoped.reason_code
        or diagnosis.supported_claim_ids != claim_scoped.supported_claim_ids
        or diagnosis.contradicted_claim_ids
        != claim_scoped.contradicted_claim_ids
        or diagnosis.unresolved_claim_ids != claim_scoped.unresolved_claim_ids
        or diagnosis.diagnostic_criterion_ids
        != claim_scoped.diagnostic_criterion_ids
    ):
        raise StudyDiagnosisAdmissionError(
            "diagnosis differs from the writer-derived claim-scoped pattern"
        )

    if diagnosis.evidence_state is EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION:
        if (
            _PRIMARY_CONTROL_CLAIM in contradicted
            or _PRIMARY_CONTROL_CLAIM in unresolved
            or (has_claim_basis and _PRIMARY_CONTROL_CLAIM not in supported)
        ):
            raise StudyDiagnosisAdmissionError(
                "axis-level confirmation requires supported registered control "
                "contrast"
            )

    if diagnosis.diagnosis_reason_code == _CONTROL_CONTRADICTED_REASON and (
        diagnosis.evidence_state is not EvidenceState.ABSENT_INFORMATION
        or _PRIMARY_CONTROL_CLAIM not in contradicted
        or _PRIMARY_CONTROL_CLAIM in supported
        or _PRIMARY_CONTROL_CLAIM in unresolved
    ):
        raise StudyDiagnosisAdmissionError(
            "uniformly contradicted control reason requires an absent-information "
            "diagnosis and the exact contradicted primary claim"
        )


__all__ = [
    "StudyDiagnosisAdmissionError",
    "require_primary_control_consistency",
]
