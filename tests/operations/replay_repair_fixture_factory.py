from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.replay_implementation_repair_admission import (
    repair_admission_stream,
    repair_preflight_stream,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
from replay_repair_fixture_records import (
    ATTEMPT_PROOF_HASH,
    BATCH_ID,
    BATCH_SPEC,
    JOB_ID,
    MANIFESTS,
    MATERIAL_IDENTITY,
    MISSION_ID,
    NEW_IMPLEMENTATION,
    OBLIGATION_ID,
    OLD_IMPLEMENTATION,
    REGISTERED,
    STUDY_ID,
    VALIDATION_PLAN_HASH,
    _completion_record,
    _content_record,
    _event_id,
    _judgment_record,
    _repair_attempt_and_close_records,
    _repair_attempt_fingerprint_record,
    _repair_open_record,
    _repair_semantic_validation,
    _request,
    _resume_record,
    _scientific_binding,
    _scientific_completion,
    _trial_authority_records,
)

@dataclass(slots=True)
class _RepairFixture:
    index: LocalIndex
    records: list[IndexRecord]
    predecessor: IndexRecord
    admission: IndexRecord
    study: IndexRecord
    batch: IndexRecord
    declaration: IndexRecord
    repair_open: IndexRecord
    attempt: IndexRecord
    repair_close: IndexRecord
    resume: IndexRecord
    completion: IndexRecord
    judgment: IndexRecord
    preflight: IndexRecord
    registered: tuple[str, ...]

    def _rebuild(self) -> None:
        self.index.rebuild(self.records)

    def replace_records(
        self,
        replacements: tuple[tuple[IndexRecord, IndexRecord], ...],
    ) -> None:
        record_fields = (
            "predecessor",
            "admission",
            "study",
            "batch",
            "declaration",
            "repair_open",
            "attempt",
            "repair_close",
            "resume",
            "completion",
            "judgment",
            "preflight",
        )
        for old, new in replacements:
            try:
                position = self.records.index(old)
            except ValueError as exc:
                raise AssertionError("fixture replacement record is absent") from exc
            self.records[position] = new
            for field in record_fields:
                if getattr(self, field) == old:
                    setattr(self, field, new)
        self._rebuild()

    def remove_records(self, records: tuple[IndexRecord, ...]) -> None:
        for record in records:
            self.records.remove(record)
        self._rebuild()

    def add_records(self, records: tuple[IndexRecord, ...]) -> None:
        self.records.extend(records)
        self._rebuild()


def _repair_fixture(
    tmp_path: Path,
    *,
    include_admission: bool = True,
    registered_repair_authority: bool = False,
) -> _RepairFixture:
    old_request = _request(OLD_IMPLEMENTATION)
    new_request = _request(NEW_IMPLEMENTATION)
    source_authority = {
        "schema": "fixture_source_closure.v1",
        "source_closure_hash": "4" * 64,
    }
    surface = {"family": "unchanged", "registered": list(REGISTERED)}
    surface_hash = canonical_digest(
        domain="replay-job-scientific-surface",
        payload=surface,
    )
    predecessor_payload = {
        "accepted_replacement_preflight_id": None,
        "authority_manifest_digest": "5" * 64,
        "batch_id": BATCH_ID,
        "request": old_request,
        "research_protocol_activation_id": "protocol:" + "6" * 64,
        "schema": "replay_implementation_admission.v1",
        "scientific_surface": surface,
        "scientific_surface_hash": surface_hash,
        "source_closure_authority": source_authority,
        "study_id": STUDY_ID,
    }
    predecessor = _content_record(
        kind="replay-implementation-admission",
        prefix="replay-implementation-admission:",
        domain="replay-implementation-admission",
        subject=f"Study:{STUDY_ID}",
        status="active",
        payload=predecessor_payload,
        authority_sequence=5,
    )
    study = IndexRecord(
        kind="study-open",
        record_id=STUDY_ID,
        subject=f"Study:{STUDY_ID}",
        status="open",
        fingerprint="2" * 64,
        payload={
            "material_identity": MATERIAL_IDENTITY,
            "mission_id": MISSION_ID,
            "portfolio_axis_id": None,
            "portfolio_axis_identity": None,
            "portfolio_decision_id": None,
            "portfolio_snapshot_id": None,
            "prior_global_multiplicity": 0,
            "prior_material_trial_count": 0,
            "replay_implementation_admission_id": predecessor.record_id,
            "replay_obligation_ids": [OBLIGATION_ID],
        },
        authority_sequence=5,
        authority_event_id=_event_id(5),
        authority_offset=1,
    )
    batch = IndexRecord(
        kind="batch-open",
        record_id=BATCH_ID,
        subject=f"Study:{STUDY_ID}",
        status="open",
        fingerprint=BATCH_ID.removeprefix("batch:"),
        payload={"spec": BATCH_SPEC.to_identity_payload()},
        event_stream=f"study-batches:{STUDY_ID}",
        event_sequence=1,
        authority_sequence=6,
        authority_event_id=_event_id(6),
        authority_offset=0,
    )
    declaration = IndexRecord(
        kind="job-declared",
        record_id=JOB_ID,
        subject=f"Job:{JOB_ID}",
        status="declared",
        fingerprint=JOB_ID.removeprefix("job:"),
        payload={
            "batch_id": BATCH_ID,
            "mission_id": MISSION_ID,
            "study_id": STUDY_ID,
            "spec": {
                "callable_identity": old_request["callable_identity"],
                "evidence_subject": {
                    "kind": "Executable",
                    "id": REGISTERED[0],
                },
                "implementation_identity": OLD_IMPLEMENTATION,
                "resume_action": "continue_batch",
                "scientific_binding": _scientific_binding(),
            },
            "work_fingerprint": "e" * 64,
        },
        authority_sequence=10,
        authority_event_id=_event_id(10),
        authority_offset=0,
    )
    repair_open = _repair_open_record(
        episode=1,
        predecessor_close_id=None,
        authority_sequence=18,
        root_cause="fixture implementation defect",
        registered_authority=registered_repair_authority,
    )
    semantic_validation = _repair_semantic_validation(
        REGISTERED[0],
        repair_id=repair_open.record_id,
    )
    attempt, repair_close = _repair_attempt_and_close_records(
        opened=repair_open,
        previous_implementation=OLD_IMPLEMENTATION,
        next_implementation=NEW_IMPLEMENTATION,
        semantic_validation=semantic_validation,
        event_sequence=1,
        authority_sequence=20,
        attempt_proof_hash=ATTEMPT_PROOF_HASH,
    )
    attempt_fingerprint_record = _repair_attempt_fingerprint_record(attempt)
    resume = _resume_record(
        repair_close,
        event_sequence=1,
        authority_sequence=21,
    )
    completion = _completion_record(
        resume_record_id=resume.record_id,
        scientific=_scientific_completion(REGISTERED[0]),
    )
    judgment = _judgment_record(completion)
    request_identity = (
        "replay-job-implementation-preflight-request:"
        + canonical_digest(
            domain="replay-job-implementation-preflight-request",
            payload=new_request,
        )
    )
    preflight_payload = {
        "artifact_hashes": [NEW_IMPLEMENTATION],
        "batch_id": BATCH_ID,
        "callable_identity": new_request["callable_identity"],
        "component_implementation_hashes": [],
        "executable_ids": list(REGISTERED),
        "executable_manifests": list(new_request["executable_manifests"]),
        "failure_detail": None,
        "failure_fingerprint": None,
        "implementation_identity": NEW_IMPLEMENTATION,
        "mission_id": MISSION_ID,
        "outcome": "accepted",
        "protocol_id": new_request["protocol_id"],
        "reason_code": None,
        "remediation_kind": None,
        "repair_close_record_id": repair_close.record_id,
        "replacement_for_preflight_id": None,
        "replay_obligation_ids": [OBLIGATION_ID],
        "request_identity": request_identity,
        "schema": "replay_job_implementation_preflight.v1",
        "scientific_surface": surface,
        "scientific_surface_hash": surface_hash,
        "source_closure_authority": source_authority,
        "study_id": STUDY_ID,
        "validation_plan_hashes": [
            VALIDATION_PLAN_HASH,
            VALIDATION_PLAN_HASH,
        ],
    }
    preflight = _content_record(
        kind="job-implementation-preflight",
        prefix="job-implementation-preflight:",
        domain="replay-job-implementation-preflight",
        subject=f"Batch:{BATCH_ID}",
        status="accepted",
        payload=preflight_payload,
        event_stream=repair_preflight_stream(repair_close.record_id),
        event_sequence=1,
        authority_sequence=24,
    )
    admission_payload = {
        "accepted_replacement_preflight_id": None,
        "authority_manifest_digest": predecessor_payload[
            "authority_manifest_digest"
        ],
        "batch_id": BATCH_ID,
        "predecessor_admission_id": predecessor.record_id,
        "recertification_preflight_id": preflight.record_id,
        "registered_prefix_executable_ids": list(REGISTERED),
        "repair_close_record_ids": [repair_close.record_id],
        "repair_executable_id": REGISTERED[0],
        "repair_job_id": JOB_ID,
        "request": new_request,
        "research_protocol_activation_id": predecessor_payload[
            "research_protocol_activation_id"
        ],
        "schema": "replay_implementation_admission.v3",
        "scientific_surface": surface,
        "scientific_surface_hash": surface_hash,
        "source_closure_authority": source_authority,
        "study_id": STUDY_ID,
        "trigger_repair_close_record_id": repair_close.record_id,
    }
    admission = _content_record(
        kind="replay-implementation-admission",
        prefix="replay-implementation-admission:",
        domain="replay-implementation-admission",
        subject=f"Study:{STUDY_ID}",
        status="active",
        payload=admission_payload,
        event_stream=repair_admission_stream(STUDY_ID),
        event_sequence=1,
        authority_sequence=24,
    )
    filler_event = IndexRecord(
        kind="journal-event",
        record_id=_event_id(1),
        subject="Control:fixture",
        status="fixture_opened",
        fingerprint=_event_id(1),
        payload={"operation_id": "fixture-open"},
        event_stream="control",
        event_sequence=1,
        authority_sequence=1,
        authority_event_id=_event_id(1),
        authority_offset=0,
    )
    trial_records = tuple(
        record
        for ordinal, (executable_id, manifest) in enumerate(
            zip(REGISTERED, MANIFESTS, strict=True),
            start=1,
        )
        for record in _trial_authority_records(
            executable_id=executable_id,
            executable_manifest=dict(manifest),
            ordinal=ordinal,
        )
    )
    records = [
        filler_event,
        *trial_records,
        predecessor,
        study,
        batch,
        declaration,
        repair_open,
        *((attempt_fingerprint_record,) if attempt_fingerprint_record else ()),
        attempt,
        repair_close,
        resume,
        completion,
        judgment,
        preflight,
        *(() if not include_admission else (admission,)),
    ]
    index = LocalIndex(tmp_path / "repair-admission.sqlite")
    index.rebuild(records)
    return _RepairFixture(
        index=index,
        records=records,
        predecessor=predecessor,
        admission=admission,
        study=study,
        batch=batch,
        declaration=declaration,
        repair_open=repair_open,
        attempt=attempt,
        repair_close=repair_close,
        resume=resume,
        completion=completion,
        judgment=judgment,
        preflight=preflight,
        registered=REGISTERED,
    )
