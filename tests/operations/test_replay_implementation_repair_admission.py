from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.replay_implementation_repair_admission import (
    ReplayImplementationRepairAdmissionIntegrityError,
    current_replay_implementation_repair_admission,
    inspect_replay_implementation_repair_boundary,
    require_replay_implementation_repair_link,
)
from axiom_rift.operations.replay_study_admission import (
    ReplayRegistrationState,
    inspect_replay_study_registration,
)
from axiom_rift.storage.index import EventHead, IndexRecord
from replay_repair_admission_fixtures import (
    BATCH_ID,
    BATCH_SPEC,
    CONCURRENT_FAMILY,
    MANIFESTS,
    MATERIAL_IDENTITY,
    NEW_IMPLEMENTATION,
    OBLIGATION_ID,
    REGISTERED,
    STUDY_ID,
    _add_failed_science_memory,
    _add_second_implementation_repair,
    _add_terminal_cause_repair,
    _content_record,
    _event_id,
    _prepend_failed_attempt,
    _rehash_completion,
    _rehash_preflight,
    _repair_fixture,
    _replace_attempt_payload,
    _replace_resume_payload,
    _request,
)

def test_repair_successor_authenticates_durable_production_chain(
    tmp_path: Path,
) -> None:
    fixture = _repair_fixture(tmp_path)

    require_replay_implementation_repair_link(
        fixture.index,
        predecessor_admission=fixture.predecessor,
        admission=fixture.admission,
        study_id=STUDY_ID,
    )
    assert current_replay_implementation_repair_admission(
        fixture.index,
        study_id=STUDY_ID,
        base_admission=fixture.predecessor,
    ) == fixture.admission


def test_repair_successor_preserves_failed_changed_basis_history(
    tmp_path: Path,
) -> None:
    fixture = _repair_fixture(tmp_path)
    failed = _prepend_failed_attempt(fixture)

    require_replay_implementation_repair_link(
        fixture.index,
        predecessor_admission=fixture.predecessor,
        admission=fixture.admission,
        study_id=STUDY_ID,
    )
    assert fixture.attempt.payload["prior_attempt_record_id"] == failed.record_id


def test_repair_successor_rejects_rehashed_skipped_failed_attempt(
    tmp_path: Path,
) -> None:
    fixture = _repair_fixture(tmp_path)
    _prepend_failed_attempt(fixture)
    _replace_attempt_payload(
        fixture,
        {
            **fixture.attempt.payload,
            "previous_basis_hash": fixture.repair_open.fingerprint,
            "prior_attempt_record_id": None,
        },
    )

    with pytest.raises(ReplayImplementationRepairAdmissionIntegrityError):
        require_replay_implementation_repair_link(
            fixture.index,
            predecessor_admission=fixture.predecessor,
            admission=fixture.admission,
            study_id=STUDY_ID,
        )


def test_failed_repaired_science_requires_exact_negative_memory(
    tmp_path: Path,
) -> None:
    fixture = _repair_fixture(tmp_path)
    memory = _add_failed_science_memory(fixture)

    require_replay_implementation_repair_link(
        fixture.index,
        predecessor_admission=fixture.predecessor,
        admission=fixture.admission,
        study_id=STUDY_ID,
    )

    forged = replace(
        memory,
        payload={**memory.payload, "forged": True},
    )
    fixture.replace_records(((memory, forged),))
    with pytest.raises(ReplayImplementationRepairAdmissionIntegrityError):
        require_replay_implementation_repair_link(
            fixture.index,
            predecessor_admission=fixture.predecessor,
            admission=fixture.admission,
            study_id=STUDY_ID,
        )


def test_multi_implementation_repair_requires_every_continuous_semantic_edge(
    tmp_path: Path,
) -> None:
    fixture = _repair_fixture(tmp_path)
    _add_second_implementation_repair(fixture, continuous=True)

    require_replay_implementation_repair_link(
        fixture.index,
        predecessor_admission=fixture.predecessor,
        admission=fixture.admission,
        study_id=STUDY_ID,
    )

    validation = dict(
        fixture.repair_close.payload["semantic_equivalence_validation"]
    )
    facts = dict(validation["facts"])
    facts["authority_deltas"] = {
        **facts["authority_deltas"],
        "scientific_claim": 1,
    }
    validation["facts"] = facts
    attempt = replace(
        fixture.attempt,
        payload={
            **fixture.attempt.payload,
            "semantic_equivalence_validation": validation,
        },
    )
    close = replace(
        fixture.repair_close,
        payload={
            **fixture.repair_close.payload,
            "semantic_equivalence_validation": validation,
        },
    )
    fixture.replace_records(
        ((fixture.attempt, attempt), (fixture.repair_close, close))
    )

    with pytest.raises(ReplayImplementationRepairAdmissionIntegrityError):
        require_replay_implementation_repair_link(
            fixture.index,
            predecessor_admission=fixture.predecessor,
            admission=fixture.admission,
            study_id=STUDY_ID,
        )


def test_multi_implementation_repair_rejects_discontinuous_artifact_chain(
    tmp_path: Path,
) -> None:
    fixture = _repair_fixture(tmp_path)
    _add_second_implementation_repair(fixture, continuous=False)

    with pytest.raises(
        ReplayImplementationRepairAdmissionIntegrityError,
        match="semantic closures are discontinuous",
    ):
        require_replay_implementation_repair_link(
            fixture.index,
            predecessor_admission=fixture.predecessor,
            admission=fixture.admission,
            study_id=STUDY_ID,
        )


def test_later_cause_repair_does_not_block_implementation_recertification(
    tmp_path: Path,
) -> None:
    fixture = _repair_fixture(tmp_path)
    _add_terminal_cause_repair(fixture)

    require_replay_implementation_repair_link(
        fixture.index,
        predecessor_admission=fixture.predecessor,
        admission=fixture.admission,
        study_id=STUDY_ID,
    )


@pytest.mark.parametrize(
    "attack",
    (
        "preflight_callable",
        "preflight_mission",
        "preflight_validation_plans",
        "preflight_extra_field",
        "job_scientific_binding",
        "completion_without_science",
        "completion_other_batch",
        "judgment_fingerprint",
        "judgment_after_admission",
        "base_fingerprint",
        "semantic_authority_delta",
        "repair_trial_delta",
        "repair_open_extra_field",
        "attempt_job_hash",
        "attempt_extra_field",
        "close_extra_field",
        "resume_extra_field",
        "predecessor_after_declaration",
    ),
)
def test_repair_successor_rejects_rehashed_and_temporal_attacks(
    tmp_path: Path,
    attack: str,
) -> None:
    fixture = _repair_fixture(tmp_path)
    if attack.startswith("preflight_"):
        field, value = {
            "preflight_callable": ("callable_identity", "forged.replay:run"),
            "preflight_mission": ("mission_id", "MIS-FORGED"),
            "preflight_validation_plans": (
                "validation_plan_hashes",
                ["f" * 64, "f" * 64],
            ),
            "preflight_extra_field": ("forged", True),
        }[attack]
        _rehash_preflight(
            fixture,
            {**fixture.preflight.payload, field: value},
        )
    elif attack == "job_scientific_binding":
        spec = {
            **fixture.declaration.payload["spec"],
            "scientific_binding": {
                **fixture.declaration.payload["spec"]["scientific_binding"],
                "validation_plan_hash": "f" * 64,
            },
        }
        declaration = replace(
            fixture.declaration,
            payload={**fixture.declaration.payload, "spec": spec},
        )
        fixture.replace_records(((fixture.declaration, declaration),))
    elif attack == "completion_without_science":
        _rehash_completion(fixture, None)
    elif attack == "completion_other_batch":
        scientific = dict(fixture.completion.payload["scientific"])
        projected = dict(scientific["multiplicity_batch_binding"])
        projected["batch_id"] = "batch:" + "f" * 64
        binding_payload = {
            key: value
            for key, value in projected.items()
            if key != "binding_hash"
        }
        projected["binding_hash"] = canonical_digest(
            domain="scientific-multiplicity-batch-binding",
            payload=binding_payload,
        )
        scientific["multiplicity_batch_binding"] = projected
        _rehash_completion(fixture, scientific)
    elif attack == "judgment_fingerprint":
        judgment = replace(fixture.judgment, fingerprint="0" * 64)
        fixture.replace_records(((fixture.judgment, judgment),))
    elif attack == "judgment_after_admission":
        judgment = replace(
            fixture.judgment,
            authority_sequence=25,
            authority_event_id=_event_id(25),
        )
        fixture.replace_records(((fixture.judgment, judgment),))
    elif attack == "base_fingerprint":
        predecessor = replace(fixture.predecessor, fingerprint="0" * 64)
        fixture.replace_records(((fixture.predecessor, predecessor),))
    elif attack == "semantic_authority_delta":
        validation = dict(
            fixture.repair_close.payload["semantic_equivalence_validation"]
        )
        facts = dict(validation["facts"])
        facts["authority_deltas"] = {
            **facts["authority_deltas"],
            "scientific_trial": 1,
        }
        validation["facts"] = facts
        attempt = replace(
            fixture.attempt,
            payload={
                **fixture.attempt.payload,
                "semantic_equivalence_validation": validation,
            },
        )
        close = replace(
            fixture.repair_close,
            payload={
                **fixture.repair_close.payload,
                "semantic_equivalence_validation": validation,
            },
        )
        fixture.replace_records(
            ((fixture.attempt, attempt), (fixture.repair_close, close))
        )
    elif attack == "repair_trial_delta":
        attempt = replace(
            fixture.attempt,
            payload={**fixture.attempt.payload, "scientific_trial_delta": 1},
        )
        close = replace(
            fixture.repair_close,
            payload={
                **fixture.repair_close.payload,
                "scientific_trial_delta": 1,
            },
        )
        fixture.replace_records(
            ((fixture.attempt, attempt), (fixture.repair_close, close))
        )
    elif attack == "repair_open_extra_field":
        opened = replace(
            fixture.repair_open,
            payload={**fixture.repair_open.payload, "forged": True},
        )
        fixture.replace_records(((fixture.repair_open, opened),))
    elif attack == "attempt_job_hash":
        _replace_attempt_payload(
            fixture,
            {**fixture.attempt.payload, "job_hash": "0" * 64},
        )
    elif attack == "attempt_extra_field":
        _replace_attempt_payload(
            fixture,
            {**fixture.attempt.payload, "forged": True},
        )
    elif attack == "close_extra_field":
        close = replace(
            fixture.repair_close,
            payload={**fixture.repair_close.payload, "forged": True},
        )
        fixture.replace_records(((fixture.repair_close, close),))
    elif attack == "resume_extra_field":
        _replace_resume_payload(
            fixture,
            {**fixture.resume.payload, "forged": True},
        )
    else:
        predecessor = replace(
            fixture.predecessor,
            authority_sequence=fixture.declaration.authority_sequence,
            authority_event_id=fixture.declaration.authority_event_id,
        )
        fixture.replace_records(((fixture.predecessor, predecessor),))

    with pytest.raises(ReplayImplementationRepairAdmissionIntegrityError):
        require_replay_implementation_repair_link(
            fixture.index,
            predecessor_admission=fixture.predecessor,
            admission=fixture.admission,
            study_id=STUDY_ID,
        )


def test_repair_boundary_consumes_typed_durable_registration(
    tmp_path: Path,
) -> None:
    fixture = _repair_fixture(tmp_path, include_admission=False)
    registration = inspect_replay_study_registration(
        fixture.index,
        study_record=fixture.study,
        batch_record=fixture.batch,
    ).require_usable()

    boundary = inspect_replay_implementation_repair_boundary(
        fixture.index,
        predecessor_admission=fixture.predecessor,
        study_record=fixture.study,
        batch_record=fixture.batch,
        request=_request(NEW_IMPLEMENTATION),
        registration_inspection=registration,
        trigger_repair_close_record_id=fixture.repair_close.record_id,
    )

    assert registration.state is ReplayRegistrationState.COMPLETE
    assert boundary.predecessor_admission_id == fixture.predecessor.record_id
    assert boundary.repair_close_record_ids == (fixture.repair_close.record_id,)
    assert boundary.registered_executable_ids == REGISTERED
    assert boundary.admission_event_sequence == 1


def test_repair_link_rejects_missing_durable_trial_prefix(tmp_path: Path) -> None:
    fixture = _repair_fixture(tmp_path)
    second_trial_records = tuple(
        record
        for record in fixture.records
        if (
            record.record_id == REGISTERED[1]
            or record.payload.get("executable_id") == REGISTERED[1]
            or record.record_id == "register-fixture-trial-2"
            or (
                record.kind == "journal-event"
                and record.event_sequence == 3
            )
        )
    )
    fixture.remove_records(second_trial_records)

    with pytest.raises(ReplayImplementationRepairAdmissionIntegrityError):
        require_replay_implementation_repair_link(
            fixture.index,
            predecessor_admission=fixture.predecessor,
            admission=fixture.admission,
            study_id=STUDY_ID,
        )


class _MemoryIndex:
    def __init__(self, records: tuple[IndexRecord, ...] = ()) -> None:
        self.records = {(record.kind, record.record_id): record for record in records}
        self.streams: dict[str, dict[int, IndexRecord]] = {}
        for record in records:
            if record.event_stream is not None and record.event_sequence is not None:
                self.streams.setdefault(record.event_stream, {})[
                    record.event_sequence
                ] = record

    def get(self, kind: str, record_id: str) -> IndexRecord | None:
        return self.records.get((kind, record_id))

    def event_head(self, stream: str) -> EventHead | None:
        values = self.streams.get(stream)
        if not values:
            return None
        sequence = max(values)
        record = values[sequence]
        return EventHead(
            stream=stream,
            sequence=sequence,
            record_kind=record.kind,
            record_id=record.record_id,
            fingerprint=record.fingerprint,
        )

    def event_record(self, stream: str, sequence: int) -> IndexRecord | None:
        return self.streams.get(stream, {}).get(sequence)


def test_initial_admission_order_overrides_set_like_batch_order() -> None:
    admission_payload = {
        "batch_id": BATCH_ID,
        "request": {"executable_manifests": list(MANIFESTS)},
        "schema": "replay_implementation_admission.v1",
        "study_id": STUDY_ID,
    }
    admission = _content_record(
        kind="replay-implementation-admission",
        prefix="replay-implementation-admission:",
        domain="replay-implementation-admission",
        subject=f"Study:{STUDY_ID}",
        status="active",
        payload=admission_payload,
        authority_sequence=1,
    )
    study = IndexRecord(
        kind="study-open",
        record_id=STUDY_ID,
        subject=f"Study:{STUDY_ID}",
        status="open",
        fingerprint="2" * 64,
        payload={
            "material_identity": MATERIAL_IDENTITY,
            "prior_global_multiplicity": 0,
            "prior_material_trial_count": 0,
            "replay_implementation_admission_id": admission.record_id,
            "replay_obligation_ids": [OBLIGATION_ID],
        },
        authority_sequence=1,
        authority_event_id=_event_id(1),
    )
    batch_record = IndexRecord(
        kind="batch-open",
        record_id=BATCH_ID,
        subject=f"Study:{STUDY_ID}",
        status="open",
        fingerprint=BATCH_ID.removeprefix("batch:"),
        payload={"spec": BATCH_SPEC.to_identity_payload()},
    )

    inspection = inspect_replay_study_registration(
        _MemoryIndex((admission,)),
        study_record=study,
        batch_record=batch_record,
    )

    assert inspection.state is ReplayRegistrationState.EMPTY
    assert inspection.expected_executable_ids == REGISTERED
    assert REGISTERED != CONCURRENT_FAMILY.executable_ids


def test_recertified_admission_order_overrides_set_like_batch_order() -> None:
    stream = f"replay-implementation-admission-study:{STUDY_ID}"
    admission_payload = {
        "batch_id": BATCH_ID,
        "request": {"executable_manifests": list(MANIFESTS)},
        "schema": "replay_implementation_admission.v2",
        "study_id": STUDY_ID,
    }
    admission = _content_record(
        kind="replay-implementation-admission",
        prefix="replay-implementation-admission:",
        domain="replay-implementation-admission",
        subject=f"Study:{STUDY_ID}",
        status="active",
        payload=admission_payload,
        event_stream=stream,
        event_sequence=1,
        authority_sequence=2,
    )
    study = IndexRecord(
        kind="study-open",
        record_id=STUDY_ID,
        subject=f"Study:{STUDY_ID}",
        status="open",
        fingerprint="2" * 64,
        payload={
            "material_identity": MATERIAL_IDENTITY,
            "prior_global_multiplicity": 0,
            "prior_material_trial_count": 0,
            "replay_obligation_ids": [OBLIGATION_ID],
        },
        authority_sequence=1,
        authority_event_id=_event_id(1),
    )
    batch_record = IndexRecord(
        kind="batch-open",
        record_id=BATCH_ID,
        subject=f"Study:{STUDY_ID}",
        status="open",
        fingerprint=BATCH_ID.removeprefix("batch:"),
        payload={"spec": BATCH_SPEC.to_identity_payload()},
    )

    inspection = inspect_replay_study_registration(
        _MemoryIndex((admission,)),
        study_record=study,
        batch_record=batch_record,
    )

    assert inspection.state is ReplayRegistrationState.EMPTY
    assert inspection.expected_executable_ids == REGISTERED
