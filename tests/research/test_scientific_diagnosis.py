from __future__ import annotations

from axiom_rift.research.governance import (
    DiagnosisConfidence,
    EvidenceState,
)
from axiom_rift.research.scientific_diagnosis import (
    diagnose_scientific_adjudications,
)


def _adjudication(
    *,
    state: str = "partial_positive",
    control: str = "contradicted",
    selection: str = "contradicted",
    economics: str = "supported",
    stability: str = "supported",
    failed_risk_diagnostic: bool = False,
) -> dict[str, object]:
    claims = {
        "activity_and_concentration": "supported",
        "after_cost_fixed_lot_economics": economics,
        "causality_and_execution_validity": "supported",
        "registered_control_contrast": control,
        "selection_aware_signal_evidence": selection,
        "temporal_and_regime_stability": stability,
    }
    return {
        "candidate_eligible": False,
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
        "criteria": (
            [
                {
                    "claim_id": "after_cost_fixed_lot_economics",
                    "comparison_state": "failed",
                    "criterion_id": "B04-risk-concentration",
                    "decision_role": "risk_diagnostic",
                    "metric": "risk_share_ppm",
                    "operator": "le",
                    "scientific_state": "diagnostic",
                    "state": "failed",
                    "threshold": 500_000,
                    "value": 1_000_000_000,
                }
            ]
            if failed_risk_diagnostic
            else []
        ),
        "evaluable": True,
        "evidence_depth": "discovery",
        "invalid_metrics": [],
        "legacy_verdict": "failed",
        "multiplicity": [],
        "schema": "scientific_adjudication.v1",
        "state": state,
    }


def test_absolute_profit_cannot_compensate_for_failed_causal_contrast() -> None:
    diagnosis = diagnose_scientific_adjudications(
        (_adjudication(failed_risk_diagnostic=True),)
    )
    assert diagnosis.evidence_state is EvidenceState.ABSENT_INFORMATION
    assert diagnosis.confidence is DiagnosisConfidence.HIGH
    assert diagnosis.reason_code == (
        "registered_control_contrast_uniformly_contradicted"
    )
    assert "after_cost_fixed_lot_economics" in diagnosis.supported_claim_ids
    assert diagnosis.diagnostic_criterion_ids == ("B04-risk-concentration",)


def test_disposition_target_is_not_diluted_by_control_member_role() -> None:
    target = diagnose_scientific_adjudications(
        (
            _adjudication(
                state="frontier",
                control="supported",
                selection="supported",
            ),
        )
    )
    assert target.evidence_state is EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION

    undifferentiated_family = diagnose_scientific_adjudications(
        (
            _adjudication(control="contradicted"),
            _adjudication(
                state="frontier",
                control="supported",
                selection="supported",
            ),
        )
    )
    assert undifferentiated_family.evidence_state is EvidenceState.STABILITY_CONCENTRATION


def test_member_concentrated_control_support_is_not_global_confirmation() -> None:
    diagnosis = diagnose_scientific_adjudications(
        (
            _adjudication(control="supported"),
            _adjudication(control="contradicted"),
        )
    )
    assert diagnosis.evidence_state is EvidenceState.STABILITY_CONCENTRATION
    assert diagnosis.reason_code == (
        "registered_control_support_member_concentrated"
    )


def test_selection_only_failure_routes_to_selection_bottleneck() -> None:
    diagnosis = diagnose_scientific_adjudications(
        (_adjudication(control="supported"),)
    )
    assert diagnosis.evidence_state is EvidenceState.CALIBRATION_SELECTION


def test_exact_frontier_retains_axis_local_confirmation_debt() -> None:
    diagnosis = diagnose_scientific_adjudications(
        (
            _adjudication(
                state="frontier",
                control="supported",
                selection="supported",
            ),
        )
    )
    assert diagnosis.evidence_state is EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION


def test_frontier_label_cannot_override_a_contradicted_decisive_claim() -> None:
    diagnosis = diagnose_scientific_adjudications(
        (_adjudication(state="frontier", control="contradicted"),)
    )
    assert diagnosis.evidence_state is EvidenceState.NOT_IDENTIFIABLE
    assert diagnosis.reason_code == (
        "adjudication_state_claim_inventory_inconsistent"
    )


def test_heterogeneous_primary_inventory_cannot_fall_back_to_support() -> None:
    first = _adjudication()
    second = _adjudication()
    second["claims"] = [
        claim
        for claim in second["claims"]
        if claim["claim_id"] != "registered_control_contrast"
    ]
    diagnosis = diagnose_scientific_adjudications((first, second))
    assert diagnosis.evidence_state is EvidenceState.NOT_IDENTIFIABLE
    assert diagnosis.primary_question_recognized is True
