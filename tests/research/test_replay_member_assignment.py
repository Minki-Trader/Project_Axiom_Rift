from __future__ import annotations

from dataclasses import replace

import pytest

from axiom_rift.research.replay_member_assignment import (
    ReplayMemberAssignment,
    ReplayMemberAssignmentError,
    ReplayMemberAssignmentSet,
    assignment_set_from_semantic_proposal,
    replay_member_assignment_set_from_payload,
)


def _identity(prefix: str, token: str) -> str:
    return prefix + token * 64


def _assignment(token: str) -> ReplayMemberAssignment:
    return ReplayMemberAssignment(
        obligation_id=_identity("historical-replay-obligation:", token),
        original_executable_id=_identity("executable:", token),
        replay_executable_id=_identity("executable:", chr(ord(token) + 2)),
        historical_family_authority_id=_identity(
            "historical-family-authority:",
            chr(ord(token) + 4),
        ),
        criterion_ids=("criterion-a", "criterion-b"),
    )


def test_assignment_set_round_trips_with_stable_bijection_identity() -> None:
    first = _assignment("1")
    second = _assignment("2")
    assignment_set = ReplayMemberAssignmentSet(
        mission_id="MIS-REPLAY-ASSIGNMENT",
        primary_obligation_id=first.obligation_id,
        assignments=(first, second),
    )

    rebuilt = replay_member_assignment_set_from_payload(
        assignment_set.to_identity_payload()
    )

    assert rebuilt == assignment_set
    assert rebuilt.identity == assignment_set.identity
    assert assignment_set.obligation_ids == (
        first.obligation_id,
        second.obligation_id,
    )
    assert assignment_set.primary == first
    assert assignment_set.by_obligation()[second.obligation_id] == second
    assert assignment_set_from_semantic_proposal(
        {"replay_member_assignments": assignment_set.to_identity_payload()}
    ) == assignment_set


@pytest.mark.parametrize(
    "field",
    (
        "obligation_id",
        "original_executable_id",
        "replay_executable_id",
        "historical_family_authority_id",
    ),
)
def test_assignment_set_rejects_every_non_bijective_mapping(
    field: str,
) -> None:
    first = _assignment("1")
    second = replace(_assignment("2"), **{field: getattr(first, field)})

    with pytest.raises(ReplayMemberAssignmentError, match="not one-to-one"):
        ReplayMemberAssignmentSet(
            mission_id="MIS-REPLAY-ASSIGNMENT",
            primary_obligation_id=first.obligation_id,
            assignments=(first, second),
        )


def test_assignment_set_rejects_order_drift_and_absent_primary() -> None:
    first = _assignment("1")
    second = _assignment("2")
    with pytest.raises(ReplayMemberAssignmentError, match="ordered"):
        ReplayMemberAssignmentSet(
            mission_id="MIS-REPLAY-ASSIGNMENT",
            primary_obligation_id=first.obligation_id,
            assignments=(second, first),
        )
    with pytest.raises(ReplayMemberAssignmentError, match="outside"):
        ReplayMemberAssignmentSet(
            mission_id="MIS-REPLAY-ASSIGNMENT",
            primary_obligation_id=_identity(
                "historical-replay-obligation:", "9"
            ),
            assignments=(first, second),
        )


def test_assignment_set_payload_rejects_noncanonical_or_forged_shape() -> None:
    first = _assignment("1")
    second = _assignment("2")
    assignment_set = ReplayMemberAssignmentSet(
        mission_id="MIS-REPLAY-ASSIGNMENT",
        primary_obligation_id=first.obligation_id,
        assignments=(first, second),
    )
    payload = assignment_set.to_identity_payload()
    payload["unexpected"] = True

    with pytest.raises(ReplayMemberAssignmentError, match="malformed"):
        replay_member_assignment_set_from_payload(payload)
