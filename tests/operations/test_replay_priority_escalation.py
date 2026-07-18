from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from axiom_rift.operations.replay_projection import (
    ReplayProjectionError,
    constraints_for_pending_from_index,
    effective_replay_priority,
    initial_obligation_record,
    replay_priority_escalation_record,
    require_initial_completion_validity_revision_record,
)
from axiom_rift.research.historical_adjudication import ReplayPriority
from axiom_rift.research.replay_obligation import (
    ReplayPriorityEscalation,
    derive_historical_replay_obligation,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


MISSION_ID = "MIS-REPLAY-PRIORITY"


def _digest(token: str) -> str:
    return (token * 64)[:64]


def _obligation():
    payload = {
        "adjudication": {
            "candidate_eligible": False,
            "claims": [{"claim_id": "claim"}],
            "criteria": [{"criterion_id": "criterion"}],
        },
        "audit_artifact_hash": _digest("1"),
        "completion_record_id": _digest("2"),
        "disposition": "replay_required",
        "executable_id": "executable:" + _digest("3"),
        "measurement_artifact_hash": _digest("4"),
        "reason_codes": ["legacy_replay"],
        "replay_priority": "p1",
        "schema": "historical_scientific_adjudication.v2",
        "study_close_record_id": _digest("5"),
        "study_id": "STU-OLD",
        "validation_plan_hash": _digest("6"),
    }
    return derive_historical_replay_obligation(
        governing_mission_id=MISSION_ID,
        historical_adjudication_id="historical-adjudication:" + _digest("7"),
        adjudication_payload=payload,
    )


def _fixture_records(obligation, escalation):
    original = IndexRecord(
        kind="historical-scientific-adjudication",
        record_id=obligation.historical_adjudication_id,
        subject="Study:STU-OLD",
        status="replay_required",
        fingerprint=_digest("7"),
        payload={
            **{
                "adjudication": {
                    "candidate_eligible": False,
                    "claims": [{"claim_id": "claim"}],
                    "criteria": [{"criterion_id": "criterion"}],
                },
                "audit_artifact_hash": obligation.audit_artifact_hash,
                "completion_record_id": obligation.original_completion_record_id,
                "disposition": "replay_required",
                "executable_id": obligation.original_executable_id,
                "measurement_artifact_hash": obligation.measurement_artifact_hash,
                "reason_codes": list(obligation.reason_codes),
                "replay_priority": "p1",
                "schema": "historical_scientific_adjudication.v2",
                "study_close_record_id": obligation.original_study_close_record_id,
                "study_id": obligation.original_study_id,
                "validation_plan_hash": obligation.validation_plan_hash,
            }
        },
        event_stream=(
            "historical-adjudication:"
            + obligation.original_completion_record_id
        ),
        event_sequence=1,
    )
    superseding = IndexRecord(
        kind="historical-scientific-adjudication",
        record_id=escalation.superseding_historical_adjudication_id,
        subject="Study:STU-OLD",
        status="replay_required",
        fingerprint=escalation.superseding_historical_adjudication_id.removeprefix(
            "historical-adjudication:"
        ),
        payload={
            "audit_artifact_hash": escalation.audit_artifact_hash,
            "completion_record_id": obligation.original_completion_record_id,
            "disposition": "replay_required",
            "replay_obligation_authority": "reused_existing_lineage",
            "replay_obligation_id": obligation.identity,
            "replay_priority": "p0",
            "schema": "historical_scientific_adjudication.v2",
            "supersedes_record_id": original.record_id,
        },
        event_stream=original.event_stream,
        event_sequence=2,
    )
    satisfaction = IndexRecord(
        kind="historical-replay-obligation-resolution",
        record_id=escalation.accepted_satisfaction_record_id,
        subject=f"Mission:{MISSION_ID}",
        status="satisfied",
        fingerprint=escalation.accepted_satisfaction_record_id.removeprefix(
            "historical-replay-satisfaction:"
        ),
        payload={"obligation_id": obligation.identity},
        event_stream=f"historical-replay-obligation:{obligation.identity}",
        event_sequence=2,
    )
    return (
        initial_obligation_record(obligation),
        original,
        superseding,
        satisfaction,
        replay_priority_escalation_record(escalation),
    )


def test_effective_priority_survives_later_adjudication_supersession() -> None:
    obligation = _obligation()
    escalation = ReplayPriorityEscalation(
        governing_mission_id=MISSION_ID,
        obligation_id=obligation.identity,
        superseding_historical_adjudication_id=(
            "historical-adjudication:" + _digest("8")
        ),
        completion_validity_invalidation_id=(
            "historical-scientific-validity-invalidation:" + _digest("9")
        ),
        accepted_satisfaction_record_id=(
            "historical-replay-satisfaction:" + _digest("a")
        ),
        audit_artifact_hash=_digest("b"),
        reason_codes=(
            "accepted_replay_satisfaction_revocation_pending",
            "decision_input_point_in_time_unproven",
        ),
    )
    with TemporaryDirectory() as temporary:
        with LocalIndex(Path(temporary) / "index.sqlite") as index:
            fixture_records = _fixture_records(obligation, escalation)
            escalation_adjudication = fixture_records[2]
            later_adjudication_id = "historical-adjudication:" + _digest("c")
            later_adjudication = IndexRecord(
                kind="historical-scientific-adjudication",
                record_id=later_adjudication_id,
                subject="Study:STU-OLD",
                status="replay_required",
                fingerprint=_digest("c"),
                payload={
                    "audit_artifact_hash": _digest("d"),
                    "completion_record_id": (
                        obligation.original_completion_record_id
                    ),
                    "disposition": "replay_required",
                    "replay_obligation_authority": (
                        "reused_existing_lineage"
                    ),
                    "replay_obligation_id": obligation.identity,
                    "replay_priority": "p0",
                    "schema": "historical_scientific_adjudication.v2",
                    "supersedes_record_id": escalation_adjudication.record_id,
                },
                event_stream=escalation_adjudication.event_stream,
                event_sequence=3,
            )
            index.put_many((*fixture_records, later_adjudication))
            result = {
                "adjudication_record_ids": [
                    escalation.superseding_historical_adjudication_id
                ],
                "audit_artifact_hash": escalation.audit_artifact_hash,
                "candidate_delta": 0,
                "holdout_delta": 0,
                "replay_obligation_ids": [],
                "replay_priority_escalation_ids": [escalation.identity],
                "reused_replay_obligation_ids": [obligation.identity],
                "trial_delta": 0,
            }
            with (
                patch(
                    "axiom_rift.operations.replay_projection."
                    "current_completion_validity_invalidation",
                    return_value=SimpleNamespace(
                        invalidation_record_id=(
                            escalation.completion_validity_invalidation_id
                        )
                    ),
                ),
                patch(
                    "axiom_rift.operations.replay_projection."
                    "require_same_event_operation_result",
                    return_value=(
                        "historical_scientific_adjudications_recorded",
                        result,
                    ),
                ),
            ):
                assert effective_replay_priority(index, obligation) is ReplayPriority.P0
                assert constraints_for_pending_from_index(index, (obligation,)) == {
                    "pending_replay_obligation_ids": [obligation.identity],
                    "required_replay_priority": "p0",
                }


def test_escalation_rejects_missing_same_event_writer_inventory() -> None:
    obligation = _obligation()
    escalation = ReplayPriorityEscalation(
        governing_mission_id=MISSION_ID,
        obligation_id=obligation.identity,
        superseding_historical_adjudication_id=(
            "historical-adjudication:" + _digest("8")
        ),
        completion_validity_invalidation_id=(
            "historical-scientific-validity-invalidation:" + _digest("9")
        ),
        accepted_satisfaction_record_id=(
            "historical-replay-satisfaction:" + _digest("a")
        ),
        audit_artifact_hash=_digest("b"),
        reason_codes=("decision_input_point_in_time_unproven",),
    )
    with TemporaryDirectory() as temporary:
        with LocalIndex(Path(temporary) / "index.sqlite") as index:
            index.put_many(_fixture_records(obligation, escalation))
            with (
                patch(
                    "axiom_rift.operations.replay_projection."
                    "current_completion_validity_invalidation",
                    return_value=SimpleNamespace(
                        invalidation_record_id=(
                            escalation.completion_validity_invalidation_id
                        )
                    ),
                ),
                patch(
                    "axiom_rift.operations.replay_projection."
                    "require_same_event_operation_result",
                    return_value=(
                        "historical_scientific_adjudications_recorded",
                        {
                            "adjudication_record_ids": [
                                escalation.superseding_historical_adjudication_id
                            ],
                            "audit_artifact_hash": escalation.audit_artifact_hash,
                            "candidate_delta": 0,
                            "holdout_delta": 0,
                            "replay_obligation_ids": [],
                            "replay_priority_escalation_ids": [],
                            "reused_replay_obligation_ids": [
                                obligation.identity
                            ],
                            "trial_delta": 0,
                        },
                    ),
                ),
            ):
                with pytest.raises(ReplayProjectionError, match="not exact"):
                    effective_replay_priority(index, obligation)


def test_initial_protocol_revision_binds_exact_completion_invalidity() -> None:
    adjudication_id = "historical-adjudication:" + _digest("c")
    invalidation_id = (
        "historical-scientific-validity-invalidation:" + _digest("d")
    )
    adjudication_payload = {
        "adjudication": {
            "candidate_eligible": False,
            "claims": [{"claim_id": "claim"}],
            "criteria": [{"criterion_id": "criterion"}],
        },
        "audit_artifact_hash": _digest("1"),
        "completion_record_id": _digest("2"),
        "disposition": "replay_required",
        "executable_id": "executable:" + _digest("3"),
        "measurement_artifact_hash": _digest("4"),
        "reason_codes": [
            "decision_input_point_in_time_unproven",
            "prospective_exact_replay_required",
        ],
        "replay_priority": "p1",
        "schema": "historical_scientific_adjudication.v2",
        "study_close_record_id": _digest("5"),
        "study_id": "STU-OLD",
        "validation_plan_hash": _digest("6"),
    }
    obligation = derive_historical_replay_obligation(
        governing_mission_id=MISSION_ID,
        historical_adjudication_id=adjudication_id,
        adjudication_payload=adjudication_payload,
    )
    reason = "decision_input_point_in_time_unproven"
    recorded_adjudication = IndexRecord(
        kind="historical-scientific-adjudication",
        record_id=adjudication_id,
        subject="Study:STU-OLD",
        status="replay_required",
        fingerprint=_digest("c"),
        payload={
            **adjudication_payload,
            "replay_obligation_id": obligation.identity,
            "validity_overrides": [
                {
                    "evidence_record_id": invalidation_id,
                    "reason": reason,
                    "subject_id": obligation.original_completion_record_id,
                }
            ],
        },
    )
    invalidation = SimpleNamespace(
        affected_claim_ids=obligation.claim_ids,
        affected_criterion_ids=obligation.criterion_ids,
        audit_artifact_hash=obligation.audit_artifact_hash,
        completion_record_id=obligation.original_completion_record_id,
        executable_id=obligation.original_executable_id,
        measurement_artifact_hash=obligation.measurement_artifact_hash,
        study_close_record_id=obligation.original_study_close_record_id,
        study_id=obligation.original_study_id,
        validation_plan_hash=obligation.validation_plan_hash,
    )
    validity = SimpleNamespace(
        invalidation=invalidation,
        invalidation_record_id=invalidation_id,
        reason=reason,
    )
    with TemporaryDirectory() as temporary:
        with LocalIndex(Path(temporary) / "index.sqlite") as index:
            index.put(recorded_adjudication)
            with patch(
                "axiom_rift.operations.replay_projection."
                "current_completion_validity_invalidation",
                return_value=validity,
            ):
                assert (
                    require_initial_completion_validity_revision_record(
                        index,
                        obligation=obligation,
                        invalidation_record_id=invalidation_id,
                    )
                    is validity
                )
                with pytest.raises(
                    ReplayProjectionError,
                    match="exact completion-invalidity",
                ):
                    require_initial_completion_validity_revision_record(
                        index,
                        obligation=obligation,
                        invalidation_record_id=(
                            "historical-scientific-validity-invalidation:"
                            + _digest("e")
                        ),
                    )
