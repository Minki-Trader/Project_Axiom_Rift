from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.running_job import RunningJobAuthorityIntegrityError
from axiom_rift.operations.running_job_repair_projection import (
    effective_repair_head_implementation,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
from replay_repair_fixture_factory import _repair_fixture
from replay_repair_fixture_mutations import _add_terminal_cause_repair
from replay_repair_fixture_records import (
    JOB_ID as REPLAY_JOB_ID,
    NEW_IMPLEMENTATION,
)


JOB_ID = "job:" + "1" * 64
EXECUTABLE_ID = "executable:" + "2" * 64
IMPLEMENTATION_ID = "3" * 64
REPAIR_ID = "repair:" + "4" * 64
PROOF_HASH = "5" * 64


def _fixture(tmp_path: Path) -> tuple[LocalIndex, IndexRecord]:
    declaration = IndexRecord(
        kind="job-declared",
        record_id=JOB_ID,
        subject=f"Job:{JOB_ID}",
        status="declared",
        fingerprint=JOB_ID.removeprefix("job:"),
        payload={
            "spec": {
                "evidence_subject": {
                    "id": EXECUTABLE_ID,
                    "kind": "Executable",
                },
                "implementation_identity": IMPLEMENTATION_ID,
            }
        },
    )
    trial = IndexRecord(
        kind="trial",
        record_id=EXECUTABLE_ID,
        subject="Batch:fixture",
        status="evaluated",
        fingerprint=EXECUTABLE_ID.removeprefix("executable:"),
        payload={
            "engineering_fixture": False,
            "scientific_eligible": True,
        },
    )
    close_payload = {
        "attempt_record_id": "6" * 64,
        "changed_cause_proof_hash": PROOF_HASH,
        "changed_dimension": "cause",
        "effective_implementation_identity": IMPLEMENTATION_ID,
        "implementation_changed": False,
        "job_id": JOB_ID,
        "previous_effective_implementation_identity": IMPLEMENTATION_ID,
        "prior_attempt_record_id": None,
        "repair_id": REPAIR_ID,
        "resume_action": "continue_batch",
        "scientific_failure_delta": 0,
        "scientific_trial_delta": 0,
        "verification_evidence_hashes": ["7" * 64],
    }
    close_id = canonical_digest(
        domain="repair-close",
        payload={"proof": PROOF_HASH, "repair_id": REPAIR_ID},
    )
    close = IndexRecord(
        kind="repair-close",
        record_id=close_id,
        subject=f"Job:{JOB_ID}",
        status="repaired",
        fingerprint=PROOF_HASH,
        payload=close_payload,
        event_stream=f"job-repair:{JOB_ID}",
        event_sequence=1,
        authority_sequence=3,
        authority_event_id="8" * 64,
        authority_offset=0,
    )
    index = LocalIndex(tmp_path / "repair-projection.sqlite")
    index.rebuild((declaration, trial, close))
    return index, close


def test_production_nonimplementation_repair_preserves_implementation(
    tmp_path: Path,
) -> None:
    index, close = _fixture(tmp_path)

    assert effective_repair_head_implementation(
        index,
        job_id=JOB_ID,
        declared_implementation_identity=IMPLEMENTATION_ID,
    ) == (IMPLEMENTATION_ID, close.record_id)


def test_nonimplementation_repair_cannot_rewrite_implementation(
    tmp_path: Path,
) -> None:
    index, close = _fixture(tmp_path)
    forged = replace(
        close,
        payload={
            **close.payload,
            "effective_implementation_identity": "9" * 64,
        },
    )
    declaration = index.get("job-declared", JOB_ID)
    trial = index.get("trial", EXECUTABLE_ID)
    assert declaration is not None and trial is not None
    index.rebuild((declaration, trial, forged))

    with pytest.raises(RunningJobAuthorityIntegrityError):
        effective_repair_head_implementation(
            index,
            job_id=JOB_ID,
            declared_implementation_identity=IMPLEMENTATION_ID,
        )


def test_terminal_cause_repair_revalidates_prior_implementation_chain(
    tmp_path: Path,
) -> None:
    fixture = _repair_fixture(tmp_path)
    _add_terminal_cause_repair(fixture)
    terminal_close_id = fixture.resume.payload["repair_close_record_id"]

    assert effective_repair_head_implementation(
        fixture.index,
        job_id=REPLAY_JOB_ID,
        declared_implementation_identity=(
            fixture.declaration.payload["spec"]["implementation_identity"]
        ),
    ) == (NEW_IMPLEMENTATION, terminal_close_id)


def test_terminal_cause_repair_rejects_forged_predecessor_close(
    tmp_path: Path,
) -> None:
    fixture = _repair_fixture(tmp_path)
    _add_terminal_cause_repair(fixture)
    forged = replace(
        fixture.repair_close,
        payload={**fixture.repair_close.payload, "forged": True},
    )
    fixture.replace_records(((fixture.repair_close, forged),))

    with pytest.raises(RunningJobAuthorityIntegrityError):
        effective_repair_head_implementation(
            fixture.index,
            job_id=REPLAY_JOB_ID,
            declared_implementation_identity=(
                fixture.declaration.payload["spec"][
                    "implementation_identity"
                ]
            ),
        )
