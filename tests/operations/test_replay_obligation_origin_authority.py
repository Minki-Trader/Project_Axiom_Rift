from __future__ import annotations

from pathlib import Path

import pytest

from axiom_rift.operations.running_job import RunningJobAuthorityError
from axiom_rift.operations.running_job_context import (
    _require_recorded_new_replay_obligation_origin,
)
from axiom_rift.research.historical_adjudication import ReplayPriority
from axiom_rift.research.replay_obligation import HistoricalReplayObligation
from axiom_rift.storage.index import IndexRecord, LocalIndex


def _fixture_records(
    tamper: str | None = None,
) -> tuple[HistoricalReplayObligation, list[IndexRecord]]:
    mission_id = "MIS-ORIGIN"
    study_id = "STU-ORIGIN"
    adjudication_id = "historical-adjudication:" + "1" * 64
    obligation = HistoricalReplayObligation(
        governing_mission_id=mission_id,
        historical_adjudication_id=adjudication_id,
        replay_priority=ReplayPriority.P1,
        original_study_id=study_id,
        original_study_close_record_id="2" * 64,
        original_completion_record_id="3" * 64,
        original_executable_id="executable:" + "4" * 64,
        audit_artifact_hash="5" * 64,
        validation_plan_hash="6" * 64,
        measurement_artifact_hash="7" * 64,
        claim_ids=("claim-origin",),
        criterion_ids=("criterion-origin",),
        reason_codes=("prospective_exact_replay_required",),
    )
    authority_sequence = 11
    authority_event_id = "8" * 64
    authority_offset = 800
    adjudication_payload = {
        "adjudication": {
            "candidate_eligible": False,
            "claims": [{"claim_id": "claim-origin"}],
            "criteria": [{"criterion_id": "criterion-origin"}],
        },
        "audit_artifact_hash": obligation.audit_artifact_hash,
        "candidate_delta": 0,
        "completion_record_id": obligation.original_completion_record_id,
        "disposition": "replay_required",
        "executable_id": obligation.original_executable_id,
        "holdout_delta": 0,
        "measurement_artifact_hash": obligation.measurement_artifact_hash,
        "reason_codes": list(obligation.reason_codes),
        "replay_obligation_authority": (
            "reused_existing" if tamper == "adjudication_origin" else "derived_new"
        ),
        "replay_obligation_id": obligation.identity,
        "replay_obligation_origin_adjudication_id": adjudication_id,
        "replay_priority": obligation.replay_priority.value,
        "schema": "historical_scientific_adjudication.v2",
        "study_close_record_id": obligation.original_study_close_record_id,
        "study_id": obligation.original_study_id,
        "trial_delta": 0,
        "validation_plan_hash": obligation.validation_plan_hash,
    }
    adjudication = IndexRecord(
        kind="historical-scientific-adjudication",
        record_id=adjudication_id,
        subject=f"Study:{study_id}",
        status="replay_required",
        fingerprint=adjudication_id.removeprefix("historical-adjudication:"),
        payload=adjudication_payload,
        authority_sequence=authority_sequence,
        authority_event_id=(
            "9" * 64 if tamper == "cross_event" else authority_event_id
        ),
        authority_offset=authority_offset,
    )
    stream = f"historical-replay-obligation:{obligation.identity}"
    initial = IndexRecord(
        kind="historical-replay-obligation",
        record_id=obligation.identity,
        subject=f"Mission:{mission_id}",
        status="pending",
        fingerprint=obligation.identity.removeprefix(
            "historical-replay-obligation:"
        ),
        payload={"obligation": obligation.to_identity_payload()},
        event_stream=stream,
        event_sequence=1,
        authority_sequence=authority_sequence,
        authority_event_id=authority_event_id,
        authority_offset=authority_offset,
    )
    replay_ids = [
        (
            "historical-replay-obligation:" + "0" * 64
            if tamper == "operation_result"
            else obligation.identity
        )
    ]
    operation_id = "record-origin-adjudication"
    operation = IndexRecord(
        kind="operation",
        record_id=operation_id,
        subject="ProjectGoal:OPERATING_DIRECTION.md",
        status="success",
        fingerprint=operation_id,
        payload={
            "event_kind": "historical_scientific_adjudications_recorded",
            "result": {
                "adjudication_record_ids": [adjudication_id],
                "audit_artifact_hash": obligation.audit_artifact_hash,
                "candidate_delta": 0,
                "holdout_delta": 0,
                "replay_obligation_ids": replay_ids,
                "replay_priority_escalation_ids": [],
                "reused_replay_obligation_ids": [],
                "trial_delta": 0,
            },
        },
        authority_sequence=authority_sequence,
        authority_event_id=authority_event_id,
        authority_offset=authority_offset,
    )
    journal = IndexRecord(
        kind="journal-event",
        record_id=authority_event_id,
        subject="ProjectGoal:OPERATING_DIRECTION.md",
        status="historical_scientific_adjudications_recorded",
        fingerprint=authority_event_id,
        payload={"operation_id": operation_id},
        event_stream="control",
        event_sequence=authority_sequence,
        authority_sequence=authority_sequence,
        authority_event_id=authority_event_id,
        authority_offset=authority_offset,
    )
    return obligation, [initial, adjudication, operation, journal]


def _build_index(root: Path, records: list[IndexRecord]) -> LocalIndex:
    index = LocalIndex(root / "index.sqlite")
    index.rebuild(records)
    return index


def test_direct_adjudication_origin_is_exactly_authenticated(tmp_path: Path) -> None:
    obligation, records = _fixture_records()
    with _build_index(tmp_path, records) as index:
        _require_recorded_new_replay_obligation_origin(
            index,
            obligation=obligation,
            record=records[0],
        )


@pytest.mark.parametrize(
    "tamper",
    ("operation_result", "adjudication_origin", "cross_event"),
)
def test_direct_adjudication_origin_rejects_cross_record_tampering(
    tmp_path: Path,
    tamper: str,
) -> None:
    obligation, records = _fixture_records(tamper)
    with _build_index(tmp_path, records) as index:
        with pytest.raises(RunningJobAuthorityError):
            _require_recorded_new_replay_obligation_origin(
                index,
                obligation=obligation,
                record=records[0],
            )
