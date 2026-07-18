from __future__ import annotations

from dataclasses import replace

import pytest

from axiom_rift.operations.completion_evidence_scope import (
    EffectiveCompletionEvidenceScope,
)
from axiom_rift.operations.effective_scientific_diagnosis import (
    EffectiveScientificDiagnosisError,
    diagnose_effective_scientific_adjudications,
)
from axiom_rift.research.governance import DiagnosisConfidence, EvidenceState


def _adjudication(
    *,
    claims: dict[str, str],
    state: str = "frontier",
) -> dict[str, object]:
    return {
        "claims": [
            {
                "claim_id": claim_id,
                "decisive_criterion_ids": [f"criterion-{ordinal}"],
                "state": claim_state,
            }
            for ordinal, (claim_id, claim_state) in enumerate(
                sorted(claims.items()), start=1
            )
        ],
        "criteria": [],
        "evaluable": True,
        "schema": "scientific_adjudication.v1",
        "state": state,
    }


def _scope(
    completion: str,
    *,
    eligible: bool,
    modes: tuple[str, ...],
    overlay: str | None = None,
    invalidation: str | None = None,
) -> EffectiveCompletionEvidenceScope:
    return EffectiveCompletionEvidenceScope(
        completion_record_id=completion,
        evidence_modes=modes,
        scientific_eligible=eligible,
        candidate_eligible=False,
        scientific_credit=int(eligible),
        economic_credit=0,
        candidate_credit=0,
        terminal_credit=int(eligible),
        negative_memory_authoritative=eligible,
        negative_memory_role=("scientific" if eligible else "diagnostic_only"),
        overlay_record_id=overlay,
        invalidation_record_id=invalidation,
    )


def test_audit_only_completion_cannot_create_confirmation_debt() -> None:
    result = diagnose_effective_scientific_adjudications(
        (
            (
                _adjudication(
                    claims={
                        "audit_reanalysis_integrity": "supported",
                        "historical_post_selection_diagnostic": "supported",
                    }
                ),
                _scope(
                    "a" * 64,
                    eligible=False,
                    modes=("audit_integrity",),
                    overlay="historical-evidence-scope:" + "b" * 64,
                ),
            ),
        )
    )

    assert result.evidence_state is EvidenceState.NOT_IDENTIFIABLE
    assert result.confidence is DiagnosisConfidence.HIGH
    assert result.reason_code == (
        "audit_only_scope_cannot_create_scientific_confirmation"
    )
    assert result.primary_question_recognized is True
    assert result.supported_claim_ids == (
        "audit_reanalysis_integrity",
        "historical_post_selection_diagnostic",
    )


def test_audit_only_member_cannot_compensate_for_scientific_member() -> None:
    result = diagnose_effective_scientific_adjudications(
        (
            (
                _adjudication(claims={"audit_reanalysis_integrity": "supported"}),
                _scope(
                    "a" * 64,
                    eligible=False,
                    modes=("audit_integrity",),
                    overlay="historical-evidence-scope:" + "b" * 64,
                ),
            ),
            (
                _adjudication(
                    claims={
                        "registered_control_contrast": "contradicted",
                        "after_cost_fixed_lot_economics": "supported",
                    },
                    state="partial_positive",
                ),
                _scope(
                    "c" * 64,
                    eligible=True,
                    modes=("causal_contrast", "cost_and_execution"),
                ),
            ),
        )
    )

    assert result.evidence_state is EvidenceState.ABSENT_INFORMATION
    assert result.reason_code == (
        "registered_control_contrast_uniformly_contradicted"
    )
    assert "audit_reanalysis_integrity" not in result.supported_claim_ids


def test_validity_invalidated_completion_is_not_scientific_support() -> None:
    result = diagnose_effective_scientific_adjudications(
        (
            (
                _adjudication(
                    claims={"registered_control_contrast": "supported"}
                ),
                _scope(
                    "a" * 64,
                    eligible=False,
                    modes=("audit_integrity",),
                    invalidation="completion-validity:" + "d" * 64,
                ),
            ),
        )
    )

    assert result.evidence_state is EvidenceState.NOT_IDENTIFIABLE
    assert result.reason_code == "completion_scientific_validity_invalidated"
    assert result.confidence is DiagnosisConfidence.HIGH


def test_scope_credit_and_eligibility_must_agree() -> None:
    inconsistent = replace(
        _scope(
            "a" * 64,
            eligible=False,
            modes=("audit_integrity",),
        ),
        scientific_credit=1,
    )
    with pytest.raises(
        EffectiveScientificDiagnosisError,
        match="scope is inconsistent",
    ):
        diagnose_effective_scientific_adjudications(
            (
                (
                    _adjudication(
                        claims={"audit_reanalysis_integrity": "supported"}
                    ),
                    inconsistent,
                ),
            )
        )
