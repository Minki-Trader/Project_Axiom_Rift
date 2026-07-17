from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import pytest

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.historical_family_authority_admission import (
    HistoricalFamilyAuthorityAdmissionError,
    prepare_historical_family_authority_record,
    require_recorded_historical_family_authority,
    require_sibling_recertification_family_core,
)
from axiom_rift.operations.replay_projection import initial_obligation_record
from axiom_rift.research.historical_family_binding import (
    ControlBinding,
    HistoricalFamilyAuthority,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
    historical_family_core_identity,
)
from axiom_rift.research.replay_obligation import (
    derive_historical_replay_obligation,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


MISSION_ID = "MIS-HISTORICAL-FAMILY-ADMISSION"
STUDY_ID = "STU-9001"
SOURCE_RELATIVE_PATH = "src/axiom_rift/research/family_fixture.py"
SOURCE_NAME = "family_fixture.py"


@dataclass(frozen=True, slots=True)
class _AdmissionFixture:
    repository_root: Path
    index: LocalIndex
    primary_family: HistoricalFamilySpec
    sibling_authority: HistoricalFamilyAuthority
    source_sha256: str


def _member_manifest(ordinal: int) -> dict[str, object]:
    return {
        "parameters": {"variant": ordinal},
        "schema": "historical_family_admission_member.v1",
    }


def _executable_id(manifest: dict[str, object]) -> str:
    return "executable:" + canonical_digest(
        domain="executable",
        payload=manifest,
    )


def _controls(references: tuple[str, ...]) -> tuple[ControlBinding, ...]:
    return (
        ControlBinding(
            subject_historical_executable_id=references[0],
            opposite_historical_executable_id=references[1],
            feature_historical_executable_ids=(references[2],),
        ),
        ControlBinding(
            subject_historical_executable_id=references[1],
            opposite_historical_executable_id=references[0],
            feature_historical_executable_ids=(references[3],),
        ),
        ControlBinding(
            subject_historical_executable_id=references[2],
            opposite_historical_executable_id=references[3],
            feature_historical_executable_ids=(references[0],),
        ),
        ControlBinding(
            subject_historical_executable_id=references[3],
            opposite_historical_executable_id=references[2],
            feature_historical_executable_ids=(references[1],),
        ),
    )


def _admission_fixture(tmp_path: Path) -> _AdmissionFixture:
    repository_root = tmp_path / "repository"
    source = repository_root / SOURCE_RELATIVE_PATH
    source.parent.mkdir(parents=True)
    source.write_bytes(b"historical family admission fixture\n")
    source_sha256 = sha256(source.read_bytes()).hexdigest()

    manifests = tuple(_member_manifest(ordinal) for ordinal in range(1, 5))
    references = tuple(_executable_id(manifest) for manifest in manifests)
    batch_spec = {
        "max_trials": len(references),
        "study_hash": "1" * 64,
    }
    batch_digest = canonical_digest(domain="batch-spec", payload=batch_spec)
    batch_id = "batch:" + batch_digest
    members = tuple(
        HistoricalMemberSpec(
            ordinal=ordinal,
            configuration_id=f"configuration-{ordinal}",
            historical_reference_executable_id=references[ordinal - 1],
            parameters={"variant": ordinal},
        )
        for ordinal in range(1, 5)
    )
    controls = _controls(references)
    primary_family = HistoricalFamilySpec(
        original_study_id=STUDY_ID,
        original_batch_id=batch_id,
        target_historical_executable_id=references[0],
        members=members,
        controls=controls,
    )
    sibling_family = HistoricalFamilySpec(
        original_study_id=STUDY_ID,
        original_batch_id=batch_id,
        target_historical_executable_id=references[1],
        members=members,
        controls=controls,
    )
    adjudication_payload = {
        "adjudication": {
            "candidate_eligible": False,
            "claims": [{"claim_id": "family-sibling-claim"}],
            "criteria": [{"criterion_id": "family-sibling-criterion"}],
        },
        "audit_artifact_hash": "2" * 64,
        "completion_record_id": "3" * 64,
        "disposition": "replay_required",
        "executable_id": references[1],
        "measurement_artifact_hash": "4" * 64,
        "reason_codes": ["missing_exact_uncertainty"],
        "replay_priority": "p1",
        "schema": "historical_scientific_adjudication.v2",
        "study_close_record_id": "5" * 64,
        "study_id": STUDY_ID,
        "validation_plan_hash": "6" * 64,
    }
    obligation = derive_historical_replay_obligation(
        governing_mission_id=MISSION_ID,
        historical_adjudication_id="historical-adjudication:" + "7" * 64,
        adjudication_payload=adjudication_payload,
    )
    sibling_authority = HistoricalFamilyAuthority(
        replay_obligation_id=obligation.identity,
        family=sibling_family,
        reconstruction_source_path=SOURCE_RELATIVE_PATH,
        reconstruction_source_sha256=source_sha256,
    )
    study = IndexRecord(
        kind="study-open",
        record_id=STUDY_ID,
        subject=f"Study:{STUDY_ID}",
        status="closed",
        fingerprint=batch_spec["study_hash"],
        payload={},
    )
    batch = IndexRecord(
        kind="batch-open",
        record_id=batch_id,
        subject=f"Study:{STUDY_ID}",
        status="open",
        fingerprint=batch_digest,
        payload={"batch_hash": batch_digest, "spec": batch_spec},
    )
    trials = tuple(
        IndexRecord(
            kind="trial",
            record_id=reference,
            subject=f"Batch:{batch_id}",
            status="evaluated",
            fingerprint=reference.removeprefix("executable:"),
            payload={"executable": manifest, "study_id": STUDY_ID},
            event_stream=f"batch-trials:{batch_id}",
            event_sequence=ordinal,
        )
        for ordinal, (reference, manifest) in enumerate(
            zip(references, manifests, strict=True),
            start=1,
        )
    )
    index = LocalIndex(tmp_path / "historical-family-admission.sqlite")
    index.put_many(
        (
            IndexRecord(
                kind="historical-scientific-adjudication",
                record_id=obligation.historical_adjudication_id,
                subject=f"Study:{STUDY_ID}",
                status="replay_required",
                fingerprint="7" * 64,
                payload=adjudication_payload,
            ),
            initial_obligation_record(obligation),
            study,
            batch,
            *trials,
        )
    )
    return _AdmissionFixture(
        repository_root=repository_root,
        index=index,
        primary_family=primary_family,
        sibling_authority=sibling_authority,
        source_sha256=source_sha256,
    )


def _registry_patches(
    fixture: _AdmissionFixture,
    *,
    family_core_identity: str,
) -> tuple[object, object, object]:
    return (
        patch.dict(
            "axiom_rift.operations.historical_family_authority_admission."
            "HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256",
            {SOURCE_NAME: fixture.source_sha256},
            clear=True,
        ),
        patch.dict(
            "axiom_rift.operations.historical_family_authority_admission."
            "HISTORICAL_FAMILY_IDENTITY_BY_MODULE",
            {SOURCE_NAME: fixture.primary_family.identity},
            clear=True,
        ),
        patch.dict(
            "axiom_rift.operations.historical_family_authority_admission."
            "HISTORICAL_FAMILY_CORE_IDENTITY_BY_MODULE",
            {SOURCE_NAME: family_core_identity},
            clear=True,
        ),
    )


def _record_authority(
    fixture: _AdmissionFixture,
    *,
    event_kind: str,
    result_authority_id: str | None = None,
    authority_event_id: str | None = None,
    index_authority: bool = True,
) -> IndexRecord:
    authority = fixture.sibling_authority
    sequence = 21
    event_id = "a" * 64
    offset = 2100
    record = IndexRecord(
        kind="historical-family-authority",
        record_id=authority.identity,
        subject=f"ReplayObligation:{authority.replay_obligation_id}",
        status="accepted",
        fingerprint=authority.identity.removeprefix(
            "historical-family-authority:"
        ),
        payload=authority.to_identity_payload(),
        authority_sequence=sequence,
        authority_event_id=authority_event_id or event_id,
        authority_offset=offset,
    )
    bound_id = result_authority_id or authority.identity
    result = (
        {"historical_family_authority_id": bound_id}
        if event_kind == "historical_replay_satisfaction_invalidated"
        else {"historical_family_authority_ids": [bound_id]}
    )
    operation = IndexRecord(
        kind="operation",
        record_id=f"operation:{event_kind}",
        subject=f"Mission:{MISSION_ID}",
        status="success",
        fingerprint="8" * 64,
        payload={"event_kind": event_kind, "result": result},
        authority_sequence=sequence,
        authority_event_id=event_id,
        authority_offset=offset,
    )
    journal = IndexRecord(
        kind="journal-event",
        record_id=event_id,
        subject=f"Mission:{MISSION_ID}",
        status=event_kind,
        fingerprint=event_id,
        payload={"operation_id": operation.record_id},
        event_stream="control",
        event_sequence=sequence,
        authority_sequence=sequence,
        authority_event_id=event_id,
        authority_offset=offset,
    )
    fixture.index.put_many(
        (record, operation, journal) if index_authority else (operation, journal)
    )
    return record


def _record_source_replay_study(fixture: _AdmissionFixture) -> str:
    study_id = "STU-REPLAY-FAMILY-CORE"
    authority = fixture.sibling_authority
    fixture.index.put(
        IndexRecord(
            kind="study-open",
            record_id=study_id,
            subject=f"Study:{study_id}",
            status="open",
            fingerprint="9" * 64,
            payload={
                "semantic_proposal": {
                    "concurrent_family": authority.family.manifest(),
                    "historical_family_authority_id": authority.identity,
                    "historical_family_identity": authority.family.identity,
                    "historical_obligation_id": authority.replay_obligation_id,
                }
            },
        )
    )
    return study_id


def test_target_variant_authority_is_admitted_by_exact_family_core(
    tmp_path: Path,
) -> None:
    fixture = _admission_fixture(tmp_path)
    patches = _registry_patches(
        fixture,
        family_core_identity=historical_family_core_identity(
            fixture.primary_family
        ),
    )
    try:
        with patches[0], patches[1], patches[2]:
            record = prepare_historical_family_authority_record(
                repository_root=fixture.repository_root,
                index=fixture.index,
                authority=fixture.sibling_authority,
            )
        assert (
            fixture.primary_family.identity
            != fixture.sibling_authority.family.identity
        )
        assert record.record_id == fixture.sibling_authority.identity
        assert record.payload == fixture.sibling_authority.to_identity_payload()
    finally:
        fixture.index.close()


def test_target_variant_authority_rejects_mismatched_family_core(
    tmp_path: Path,
) -> None:
    fixture = _admission_fixture(tmp_path)
    patches = _registry_patches(
        fixture,
        family_core_identity="historical-family-core:" + "0" * 64,
    )
    try:
        with patches[0], patches[1], patches[2]:
            with pytest.raises(
                HistoricalFamilyAuthorityAdmissionError,
                match="source differs from frozen history",
            ):
                prepare_historical_family_authority_record(
                    repository_root=fixture.repository_root,
                    index=fixture.index,
                    authority=fixture.sibling_authority,
                )
    finally:
        fixture.index.close()


@pytest.mark.parametrize(
    "event_kind",
    (
        "historical_replay_family_authorities_registered",
        "historical_replay_satisfaction_invalidated",
        "historical_replay_sibling_evidence_recertified",
    ),
)
def test_recorded_authority_requires_exact_writer_event(
    tmp_path: Path,
    event_kind: str,
) -> None:
    fixture = _admission_fixture(tmp_path)
    try:
        record = _record_authority(fixture, event_kind=event_kind)

        observed = require_recorded_historical_family_authority(
            fixture.index,
            record,
        )

        assert observed == fixture.sibling_authority
    finally:
        fixture.index.close()


@pytest.mark.parametrize(
    "tamper",
    ("absent_record", "cross_event", "wrong_result"),
)
def test_recorded_authority_rejects_unindexed_or_cross_event_record(
    tmp_path: Path,
    tamper: str,
) -> None:
    fixture = _admission_fixture(tmp_path)
    try:
        record = _record_authority(
            fixture,
            event_kind="historical_replay_family_authorities_registered",
            result_authority_id=(
                "historical-family-authority:" + "0" * 64
                if tamper == "wrong_result"
                else None
            ),
            authority_event_id="b" * 64 if tamper == "cross_event" else None,
            index_authority=tamper != "absent_record",
        )
        if tamper == "absent_record":
            assert fixture.index.get(record.kind, record.record_id) is None
        elif tamper == "cross_event":
            assert fixture.index.get(record.kind, record.record_id) == record

        with pytest.raises(
            HistoricalFamilyAuthorityAdmissionError,
            match="same-event Writer authority",
        ):
            require_recorded_historical_family_authority(
                fixture.index,
                replace(record),
            )
    finally:
        fixture.index.close()


def test_sibling_recertification_requires_same_recorded_family_core(
    tmp_path: Path,
) -> None:
    fixture = _admission_fixture(tmp_path)
    try:
        _record_authority(
            fixture,
            event_kind="historical_replay_family_authorities_registered",
        )
        study_id = _record_source_replay_study(fixture)

        observed = require_sibling_recertification_family_core(
            fixture.index,
            target_authority=fixture.sibling_authority,
            source_replay_study_id=study_id,
        )

        assert observed == fixture.sibling_authority
    finally:
        fixture.index.close()


def test_sibling_recertification_rejects_cross_family_core(
    tmp_path: Path,
) -> None:
    fixture = _admission_fixture(tmp_path)
    try:
        _record_authority(
            fixture,
            event_kind="historical_replay_family_authorities_registered",
        )
        study_id = _record_source_replay_study(fixture)
        source_family = fixture.sibling_authority.family
        changed_members = (
            replace(
                source_family.members[0],
                configuration_id="configuration-other",
                parameters=source_family.members[0].parameter_values(),
            ),
            *source_family.members[1:],
        )
        changed_family = HistoricalFamilySpec(
            original_study_id=source_family.original_study_id,
            original_batch_id=source_family.original_batch_id,
            target_historical_executable_id=(
                source_family.target_historical_executable_id
            ),
            members=changed_members,
            controls=source_family.controls,
        )
        changed_authority = HistoricalFamilyAuthority(
            replay_obligation_id=fixture.sibling_authority.replay_obligation_id,
            family=changed_family,
            reconstruction_source_path=(
                fixture.sibling_authority.reconstruction_source_path
            ),
            reconstruction_source_sha256=(
                fixture.sibling_authority.reconstruction_source_sha256
            ),
        )

        with pytest.raises(
            HistoricalFamilyAuthorityAdmissionError,
            match="source and target family cores differ",
        ):
            require_sibling_recertification_family_core(
                fixture.index,
                target_authority=changed_authority,
                source_replay_study_id=study_id,
            )
    finally:
        fixture.index.close()
