from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.effective_study_diagnosis import (
    EffectiveStudyDiagnosisError,
    effective_study_diagnosis,
)
from axiom_rift.operations.diagnosis_authority_context import (
    DiagnosisAuthorityContext,
    DiagnosisAuthorityContextError,
)
from axiom_rift.research.governance import (
    DiagnosisConfidence,
    EvidenceState,
    ResearchLayer,
    StudyDiagnosis,
    diagnosis_branch,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


ORIGINAL_ID = "diagnosis:" + "a" * 64
AUTHORITY_EVENT_ID = "d" * 64
AUTHORITY_SEQUENCE = 2
COMPLETION_ID = "c" * 64


def _original() -> IndexRecord:
    return IndexRecord(
        kind="study-diagnosis",
        record_id=ORIGINAL_ID,
        subject="Study:STU-CORRECTION",
        status="supported_requires_confirmation",
        fingerprint="a" * 64,
        payload={
            "allowed_actions": ["preserve"],
            "allowed_research_layers": ["synthesis"],
            "confidence": "high",
            "evidence_state": "supported_requires_confirmation",
            "evidence_basis": [
                {"kind": "job-completed", "record_id": COMPLETION_ID}
            ],
            "mission_id": "MIS-CORRECTION",
            "study_close_record_id": "c" * 64,
            "study_id": "STU-CORRECTION",
        },
    )


def _audit_payload() -> dict[str, object]:
    return {
        "mission_id": "MIS-CORRECTION",
        "original_diagnosis_ids": [ORIGINAL_ID],
        "prior_journal_event_id": "e" * 64,
        "prior_journal_sequence": 1,
        "protocol_id": "protocol:claim_scoped_noncompensating_diagnosis.v1",
        "rationale": "correct a complete claim-scoped mismatch inventory",
        "schema": "study_diagnosis_correction_audit.v1",
    }


def _audit() -> IndexRecord:
    payload = _audit_payload()
    digest = canonical_digest(
        domain="study-diagnosis-correction-audit",
        payload=payload,
    )
    return IndexRecord(
        kind="study-diagnosis-correction-audit",
        record_id="diagnosis-correction-audit:" + digest,
        subject="Mission:MIS-CORRECTION",
        status="complete_mismatch_inventory",
        fingerprint=digest,
        payload=payload,
        authority_sequence=AUTHORITY_SEQUENCE,
        authority_event_id=AUTHORITY_EVENT_ID,
        authority_offset=100,
    )


def _correction(*, effective_state: str = "absent_information") -> IndexRecord:
    audit = _audit()
    payload = {
            "affected_completion_record_ids": [COMPLETION_ID],
            "allowed_actions": ["new_mechanism", "prune", "rotate"],
            "allowed_research_layers": ["execution", "selector", "trade"],
            "audit_id": audit.record_id,
            "audit_protocol_id": _audit_payload()["protocol_id"],
            "candidate_authority_delta": 0,
            "claim_scoped_diagnosis": {
                "contradicted_claim_ids": ["registered_control_contrast"],
                "diagnostic_criterion_ids": ["B04-risk"],
                "supported_claim_ids": ["after_cost_fixed_lot_economics"],
                "unresolved_claim_ids": [],
            },
            "effective_confidence": "high",
            "effective_evidence_state": effective_state,
            "effective_reason_code": (
                "registered_control_contrast_uniformly_contradicted"
            ),
            "holdout_reveal_delta": 0,
            "mission_id": "MIS-CORRECTION",
            "original_diagnosis_id": ORIGINAL_ID,
            "original_diagnosis_payload_digest": canonical_digest(
                domain="study-diagnosis-payload",
                payload=dict(_original().payload),
            ),
            "original_evidence_state": "supported_requires_confirmation",
            "projection_scope": (
                "study_primary_question_over_all_completion_references"
            ),
            "replay_satisfaction_delta": 0,
            "schema": "study_diagnosis_correction.v1",
            "scientific_trial_delta": 0,
            "study_close_record_id": "c" * 64,
            "study_id": "STU-CORRECTION",
        }
    digest = canonical_digest(
        domain="study-diagnosis-correction",
        payload=payload,
    )
    return IndexRecord(
        kind="study-diagnosis-correction",
        record_id="diagnosis-correction:" + digest,
        subject="Study:STU-CORRECTION",
        status=effective_state,
        fingerprint=digest,
        payload=payload,
        event_stream=f"study-diagnosis-correction:{ORIGINAL_ID}",
        event_sequence=1,
        authority_sequence=AUTHORITY_SEQUENCE,
        authority_event_id=AUTHORITY_EVENT_ID,
        authority_offset=100,
    )


def _operation(correction: IndexRecord) -> IndexRecord:
    audit = _audit()
    return IndexRecord(
        kind="operation",
        record_id="diagnosis-correction-operation",
        subject="Mission:MIS-CORRECTION",
        status="success",
        fingerprint="f" * 64,
        payload={
            "event_kind": "study_diagnoses_corrected",
            "result": {
                "audit_id": audit.record_id,
                "candidate_authority_delta": 0,
                "corrected_diagnosis_count": 1,
                "holdout_reveal_delta": 0,
                "replay_satisfaction_delta": 0,
                "scientific_trial_delta": 0,
                "study_diagnosis_correction_ids": [correction.record_id],
            },
        },
        authority_sequence=AUTHORITY_SEQUENCE,
        authority_event_id=AUTHORITY_EVENT_ID,
        authority_offset=100,
    )


def _journal_event(operation: IndexRecord) -> IndexRecord:
    return IndexRecord(
        kind="journal-event",
        record_id=AUTHORITY_EVENT_ID,
        subject="Mission:MIS-CORRECTION",
        status="study_diagnoses_corrected",
        fingerprint=AUTHORITY_EVENT_ID,
        payload={"operation_id": operation.record_id},
        event_stream="control",
        event_sequence=AUTHORITY_SEQUENCE,
        authority_sequence=AUTHORITY_SEQUENCE,
        authority_event_id=AUTHORITY_EVENT_ID,
        authority_offset=100,
    )


def _put_valid_batch(index: LocalIndex) -> IndexRecord:
    correction = _correction()
    operation = _operation(correction)
    index.put(_original())
    index.put(_audit())
    index.put(correction)
    index.put(operation)
    index.put(_journal_event(operation))
    return correction


def test_effective_projection_preserves_original_lineage_and_overlays_state() -> None:
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "local" / "index.sqlite"
        with LocalIndex(path) as index:
            correction = _put_valid_batch(index)
            projected = effective_study_diagnosis(index, ORIGINAL_ID)

    assert projected.record_id == ORIGINAL_ID
    assert projected.authority_record_id == correction.record_id
    assert projected.status == "absent_information"
    assert projected.payload["diagnostic_criterion_ids"] == ["B04-risk"]
    assert projected.payload["allowed_research_layers"] == [
        "execution",
        "selector",
        "trade",
    ]


def test_effective_projection_rejects_status_payload_divergence() -> None:
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "local" / "index.sqlite"
        with LocalIndex(path) as index:
            index.put(_original())
            index.put(_audit())
            correction = _correction(
                effective_state="stability_concentration"
            )
            index.put(correction)
            record = index.get(
                "study-diagnosis-correction", correction.record_id
            )
            assert record is not None
            # Immutable index collision protection prevents forging in place;
            # construct the malformed projection in a fresh index.
        malformed_path = Path(temporary) / "other" / "local" / "index.sqlite"
        with LocalIndex(malformed_path) as index:
            index.put(_original())
            index.put(_audit())
            malformed = _correction(effective_state="stability_concentration")
            malformed = replace(malformed, status="absent_information")
            index.put(malformed)
            index.put(_operation(malformed))
            with pytest.raises(
                EffectiveStudyDiagnosisError,
                match="correction stream is malformed",
            ):
                effective_study_diagnosis(index, ORIGINAL_ID)


def test_effective_projection_rejects_missing_audit_authority() -> None:
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "local" / "index.sqlite"
        with LocalIndex(path) as index:
            index.put(_original())
            correction = _correction()
            index.put(correction)
            index.put(_operation(correction))
            with pytest.raises(
                EffectiveStudyDiagnosisError,
                match="correction stream is malformed",
            ):
                effective_study_diagnosis(index, ORIGINAL_ID)


def test_effective_projection_rejects_missing_journal_event_authority() -> None:
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "local" / "index.sqlite"
        with LocalIndex(path) as index:
            correction = _correction()
            index.put(_original())
            index.put(_audit())
            index.put(correction)
            index.put(_operation(correction))
            with pytest.raises(
                EffectiveStudyDiagnosisError,
                match="exact Journal authority",
            ):
                effective_study_diagnosis(index, ORIGINAL_ID)


def test_diagnosis_authority_packet_is_complete_and_effective() -> None:
    with pytest.raises(
        DiagnosisAuthorityContextError,
        match="must travel together",
    ):
        DiagnosisAuthorityContext(
            study_diagnosis_id=ORIGINAL_ID,
            study_diagnosis_correction_id=_correction().record_id,
        )
    with pytest.raises(
        DiagnosisAuthorityContextError,
        match="must travel together",
    ):
        DiagnosisAuthorityContext(
            study_diagnosis_id=ORIGINAL_ID,
            diagnosis_correction_audit_id=_audit().record_id,
        )
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "local" / "index.sqlite"
        with LocalIndex(path) as index:
            correction = _put_valid_batch(index)
            context = DiagnosisAuthorityContext(
                study_diagnosis_id=ORIGINAL_ID,
                study_diagnosis_correction_id=correction.record_id,
                diagnosis_correction_audit_id=_audit().record_id,
            )
            effective = context.require_effective(
                index,
                mission_id="MIS-CORRECTION",
            )
    assert effective is not None
    assert effective.status == "absent_information"
    assert context.basis_pairs() == frozenset(
        {
            ("study-diagnosis", ORIGINAL_ID),
            ("study-diagnosis-correction", correction.record_id),
            ("study-diagnosis-correction-audit", _audit().record_id),
        }
    )


def test_claim_scoped_diagnosis_is_identity_bound_and_routes_changed_layer() -> None:
    diagnosis = StudyDiagnosis(
        study_id="STU-CORRECTION",
        study_close_record_id="c" * 64,
        evidence_state=EvidenceState.ABSENT_INFORMATION,
        confidence=DiagnosisConfidence.HIGH,
        rationale="registered contrast did not separate from its control",
        counterfactual="a changed execution mechanism could separate the paths",
        reopen_condition="reopen with a causally active execution policy",
        diagnosis_reason_code=(
            "registered_control_contrast_uniformly_contradicted"
        ),
        supported_claim_ids=("after_cost_fixed_lot_economics",),
        contradicted_claim_ids=("registered_control_contrast",),
        diagnostic_criterion_ids=("B04-risk",),
    )
    assert diagnosis.to_identity_payload()["schema"] == "study_diagnosis.v2"
    actions, layers = diagnosis_branch(
        diagnosis.evidence_state,
        primary_layer=ResearchLayer.SYNTHESIS,
        changed_layers=(ResearchLayer.EXECUTION, ResearchLayer.SYNTHESIS),
        reason_code=diagnosis.diagnosis_reason_code,
    )
    assert "new_mechanism" in actions
    assert {"execution", "selector", "trade", "synthesis"}.issubset(layers)
