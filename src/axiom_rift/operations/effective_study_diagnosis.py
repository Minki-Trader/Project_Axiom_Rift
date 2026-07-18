"""Validated effective projection over immutable Study diagnosis records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.recorded_transition_authority import (
    RecordedTransitionAuthorityError,
    require_same_event_operation_result,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class EffectiveStudyDiagnosisError(RuntimeError):
    """The additive correction stream is missing or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class EffectiveStudyDiagnosis:
    """One original identity with an optional effective correction overlay."""

    original: IndexRecord
    correction: IndexRecord | None
    payload: Mapping[str, Any]

    @property
    def record_id(self) -> str:
        """Keep the immutable diagnosis identity for historical lineage."""

        return self.original.record_id

    @property
    def authority_record_id(self) -> str:
        return (
            self.original.record_id
            if self.correction is None
            else self.correction.record_id
        )

    @property
    def status(self) -> str:
        value = self.payload.get("evidence_state")
        if not isinstance(value, str):
            raise EffectiveStudyDiagnosisError(
                "effective Study diagnosis state is malformed"
            )
        return value


def effective_study_diagnosis(
    index: LocalIndex | LocalIndexView,
    original_diagnosis_id: str,
    *,
    _validated_batch_keys: set[tuple[int, str]] | None = None,
) -> EffectiveStudyDiagnosis:
    """Open one fail-closed effective diagnosis without rewriting history."""

    original = index.get("study-diagnosis", original_diagnosis_id)
    if original is None:
        raise EffectiveStudyDiagnosisError("original Study diagnosis is absent")
    stream = f"study-diagnosis-correction:{original_diagnosis_id}"
    head = index.event_head(stream)
    if head is None:
        return EffectiveStudyDiagnosis(
            original=original,
            correction=None,
            payload=dict(original.payload),
        )
    correction = index.get(head.record_kind, head.record_id)
    payload = None if correction is None else correction.payload
    audit_id = None if not isinstance(payload, Mapping) else payload.get("audit_id")
    audit = (
        None
        if not isinstance(audit_id, str)
        else index.get("study-diagnosis-correction-audit", audit_id)
    )
    audit_payload = None if audit is None else audit.payload
    audit_original_ids = (
        ()
        if not isinstance(audit_payload, Mapping)
        else audit_payload.get("original_diagnosis_ids", ())
    )
    correction_digest = (
        None
        if not isinstance(payload, Mapping)
        else canonical_digest(
            domain="study-diagnosis-correction",
            payload=dict(payload),
        )
    )
    audit_digest = (
        None
        if not isinstance(audit_payload, Mapping)
        else canonical_digest(
            domain="study-diagnosis-correction-audit",
            payload=dict(audit_payload),
        )
    )
    expected_original_payload_digest = canonical_digest(
        domain="study-diagnosis-payload",
        payload=dict(original.payload),
    )
    affected_completion_ids = sorted(
        reference.get("record_id")
        for reference in original.payload.get("evidence_basis", [])
        if isinstance(reference, Mapping)
        and reference.get("kind") == "job-completed"
        and isinstance(reference.get("record_id"), str)
    )
    if (
        correction is None
        or correction.kind != "study-diagnosis-correction"
        or correction.event_stream != stream
        or correction.event_sequence != head.sequence
        or correction.subject != original.subject
        or not isinstance(payload, Mapping)
        or payload.get("schema") != "study_diagnosis_correction.v1"
        or payload.get("original_diagnosis_id") != original.record_id
        or payload.get("study_id") != original.payload.get("study_id")
        or payload.get("study_close_record_id")
        != original.payload.get("study_close_record_id")
        or payload.get("mission_id") != original.payload.get("mission_id")
        or payload.get("original_evidence_state")
        != original.payload.get("evidence_state")
        or payload.get("effective_evidence_state") != correction.status
        or not isinstance(payload.get("allowed_actions"), list)
        or not isinstance(payload.get("allowed_research_layers"), list)
        or not isinstance(payload.get("claim_scoped_diagnosis"), Mapping)
        or not isinstance(payload.get("effective_confidence"), str)
        or not isinstance(payload.get("effective_reason_code"), str)
        or payload.get("original_diagnosis_payload_digest")
        != expected_original_payload_digest
        or payload.get("affected_completion_record_ids")
        != affected_completion_ids
        or payload.get("projection_scope")
        != "study_primary_question_over_all_completion_references"
        or payload.get("candidate_authority_delta") != 0
        or payload.get("holdout_reveal_delta") != 0
        or payload.get("replay_satisfaction_delta") != 0
        or payload.get("scientific_trial_delta") != 0
        or correction_digest is None
        or correction.record_id != "diagnosis-correction:" + correction_digest
        or correction.fingerprint != correction_digest
        or audit is None
        or audit.kind != "study-diagnosis-correction-audit"
        or audit.record_id != audit_id
        or audit.subject != f"Mission:{payload.get('mission_id')}"
        or not isinstance(audit_payload, Mapping)
        or audit_payload.get("schema")
        != "study_diagnosis_correction_audit.v1"
        or audit_payload.get("mission_id") != payload.get("mission_id")
        or audit_payload.get("protocol_id") != payload.get("audit_protocol_id")
        or not isinstance(audit_original_ids, list)
        or audit_original_ids != sorted(set(audit_original_ids))
        or original.record_id not in audit_original_ids
        or audit_digest is None
        or audit.record_id != "diagnosis-correction-audit:" + audit_digest
        or audit.fingerprint != audit_digest
        or type(correction.authority_sequence) is not int
        or correction.authority_sequence != audit.authority_sequence
        or not isinstance(correction.authority_event_id, str)
        or correction.authority_event_id != audit.authority_event_id
    ):
        raise EffectiveStudyDiagnosisError(
            "Study diagnosis correction stream is malformed"
        )
    batch_key = (correction.authority_sequence, audit.record_id)
    if _validated_batch_keys is not None and batch_key in _validated_batch_keys:
        same_event = ()
        operations = ()
    else:
        same_event = index.records_by_kind_at_authority_sequence(
        "study-diagnosis-correction",
        correction.authority_sequence,
        )
        raw_same_event_original_ids = tuple(
            record.payload.get("original_diagnosis_id") for record in same_event
        )
        same_event_original_ids = (
            sorted(raw_same_event_original_ids)
            if all(isinstance(value, str) for value in raw_same_event_original_ids)
            else []
        )
        expected_result = {
            "audit_id": audit.record_id,
            "candidate_authority_delta": 0,
            "corrected_diagnosis_count": len(same_event),
            "holdout_reveal_delta": 0,
            "replay_satisfaction_delta": 0,
            "scientific_trial_delta": 0,
            "study_diagnosis_correction_ids": sorted(
                record.record_id for record in same_event
            ),
        }
        try:
            event_kind, operation_result = require_same_event_operation_result(
                index,
                record=correction,
                expected_event_kinds=frozenset({"study_diagnoses_corrected"}),
            )
        except RecordedTransitionAuthorityError as exc:
            raise EffectiveStudyDiagnosisError(
                "Study diagnosis correction lacks exact Journal authority"
            ) from exc
        if (
            same_event_original_ids != audit_original_ids
            or any(
                record.authority_event_id != correction.authority_event_id
                or record.payload.get("audit_id") != audit.record_id
                for record in same_event
            )
            or event_kind != "study_diagnoses_corrected"
            or dict(operation_result) != expected_result
        ):
            raise EffectiveStudyDiagnosisError(
                "Study diagnosis correction audit batch is incomplete"
            )
        if _validated_batch_keys is not None:
            _validated_batch_keys.add(batch_key)
    merged = dict(original.payload)
    merged.update(
        {
            "allowed_actions": list(payload["allowed_actions"]),
            "allowed_research_layers": list(
                payload["allowed_research_layers"]
            ),
            "claim_scoped_diagnosis": dict(payload["claim_scoped_diagnosis"]),
            "confidence": payload["effective_confidence"],
            "contradicted_claim_ids": list(
                payload["claim_scoped_diagnosis"].get(
                    "contradicted_claim_ids", []
                )
            ),
            "diagnosis_reason_code": payload["effective_reason_code"],
            "diagnostic_criterion_ids": list(
                payload["claim_scoped_diagnosis"].get(
                    "diagnostic_criterion_ids", []
                )
            ),
            "evidence_state": payload["effective_evidence_state"],
            "study_diagnosis_correction_id": correction.record_id,
            "supported_claim_ids": list(
                payload["claim_scoped_diagnosis"].get("supported_claim_ids", [])
            ),
            "unresolved_claim_ids": list(
                payload["claim_scoped_diagnosis"].get("unresolved_claim_ids", [])
            ),
        }
    )
    return EffectiveStudyDiagnosis(
        original=original,
        correction=correction,
        payload=merged,
    )


def effective_study_diagnoses_for_mission(
    index: LocalIndex | LocalIndexView,
    *,
    mission_id: str,
) -> tuple[EffectiveStudyDiagnosis, ...]:
    validated_batch_keys: set[tuple[int, str]] = set()
    values = tuple(
        effective_study_diagnosis(
            index,
            record.record_id,
            _validated_batch_keys=validated_batch_keys,
        )
        for record in index.records_by_payload_text(
            "study-diagnosis", "mission_id", mission_id
        )
    )
    return tuple(sorted(values, key=lambda value: value.record_id))


def effective_study_diagnoses_by_study(
    index: LocalIndex | LocalIndexView,
    *,
    mission_id: str,
) -> Mapping[str, EffectiveStudyDiagnosis]:
    """Decode one Mission diagnosis projection once for batch consumers."""

    values = effective_study_diagnoses_for_mission(
        index,
        mission_id=mission_id,
    )
    by_study: dict[str, EffectiveStudyDiagnosis] = {}
    for value in values:
        study_id = value.payload.get("study_id")
        if not isinstance(study_id, str) or not study_id:
            raise EffectiveStudyDiagnosisError(
                "effective Study diagnosis lost its Study identity"
            )
        if study_id in by_study:
            raise EffectiveStudyDiagnosisError(
                "Study has ambiguous diagnosis authority"
            )
        by_study[study_id] = value
    return by_study


__all__ = [
    "EffectiveStudyDiagnosis",
    "EffectiveStudyDiagnosisError",
    "effective_study_diagnosis",
    "effective_study_diagnoses_by_study",
    "effective_study_diagnoses_for_mission",
]
