"""Exact member-level lineage for one concurrent replay family.

The replay Study can execute a complete statistical family while selecting a
subset of its members for historical obligations.  This module keeps that
selection explicit: one obligation maps to one original Executable, one new
Executable, and one target-specific historical-family authority.  It carries
no execution or scientific credit by itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from axiom_rift.core.identity import canonical_bytes, canonical_digest


REPLAY_MEMBER_ASSIGNMENT_SCHEMA = "replay_member_assignment.v1"
REPLAY_MEMBER_ASSIGNMENT_SET_SCHEMA = "replay_member_assignment_set.v1"


class ReplayMemberAssignmentError(ValueError):
    """A replay member assignment is malformed or ambiguous."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ReplayMemberAssignmentError(f"{name} must be non-empty ASCII")
    return value


def _identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    suffix = text.removeprefix(prefix)
    if (
        not text.startswith(prefix)
        or len(suffix) != 64
        or any(character not in "0123456789abcdef" for character in suffix)
    ):
        raise ReplayMemberAssignmentError(f"{name} identity is invalid")
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayMemberAssignment:
    """One exact selected historical subject and its prospective member."""

    obligation_id: str
    original_executable_id: str
    replay_executable_id: str
    historical_family_authority_id: str
    criterion_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _identity(
            "replay obligation",
            self.obligation_id,
            "historical-replay-obligation:",
        )
        _identity(
            "original replay Executable",
            self.original_executable_id,
            "executable:",
        )
        _identity(
            "prospective replay Executable",
            self.replay_executable_id,
            "executable:",
        )
        _identity(
            "historical family authority",
            self.historical_family_authority_id,
            "historical-family-authority:",
        )
        criteria = self.criterion_ids
        if (
            type(criteria) is not tuple
            or not criteria
            or any(
                type(item) is not str or not item or not item.isascii()
                for item in criteria
            )
            or criteria != tuple(sorted(set(criteria)))
        ):
            raise ReplayMemberAssignmentError(
                "replay assignment criteria must be sorted unique ASCII"
            )

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "criterion_ids": list(self.criterion_ids),
            "historical_family_authority_id": (
                self.historical_family_authority_id
            ),
            "obligation_id": self.obligation_id,
            "original_executable_id": self.original_executable_id,
            "replay_executable_id": self.replay_executable_id,
            "schema": REPLAY_MEMBER_ASSIGNMENT_SCHEMA,
        }


def replay_member_assignment_from_payload(
    value: object,
) -> ReplayMemberAssignment:
    if (
        type(value) is not dict
        or set(value)
        != {
            "criterion_ids",
            "historical_family_authority_id",
            "obligation_id",
            "original_executable_id",
            "replay_executable_id",
            "schema",
        }
        or value.get("schema") != REPLAY_MEMBER_ASSIGNMENT_SCHEMA
        or not isinstance(value.get("criterion_ids"), list)
    ):
        raise ReplayMemberAssignmentError(
            "replay member assignment payload is malformed"
        )
    assignment = ReplayMemberAssignment(
        obligation_id=value["obligation_id"],
        original_executable_id=value["original_executable_id"],
        replay_executable_id=value["replay_executable_id"],
        historical_family_authority_id=value[
            "historical_family_authority_id"
        ],
        criterion_ids=tuple(value["criterion_ids"]),
    )
    if canonical_bytes(assignment.to_identity_payload()) != canonical_bytes(value):
        raise ReplayMemberAssignmentError(
            "replay member assignment payload is not canonical"
        )
    return assignment


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayMemberAssignmentSet:
    """A canonical bijection for all obligations selected by one Study."""

    mission_id: str
    primary_obligation_id: str
    assignments: tuple[ReplayMemberAssignment, ...]
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("replay assignment Mission", self.mission_id)
        _identity(
            "primary replay obligation",
            self.primary_obligation_id,
            "historical-replay-obligation:",
        )
        assignments = self.assignments
        if (
            type(assignments) is not tuple
            or not assignments
            or any(
                not isinstance(item, ReplayMemberAssignment)
                for item in assignments
            )
        ):
            raise ReplayMemberAssignmentError(
                "replay assignment set must be a non-empty typed tuple"
            )
        normalized = tuple(sorted(assignments, key=lambda item: item.obligation_id))
        if assignments != normalized:
            raise ReplayMemberAssignmentError(
                "replay assignments must be ordered by obligation identity"
            )
        for name, values in (
            ("obligation", tuple(item.obligation_id for item in assignments)),
            (
                "original Executable",
                tuple(item.original_executable_id for item in assignments),
            ),
            (
                "prospective Executable",
                tuple(item.replay_executable_id for item in assignments),
            ),
            (
                "historical family authority",
                tuple(
                    item.historical_family_authority_id for item in assignments
                ),
            ),
        ):
            if len(values) != len(set(values)):
                raise ReplayMemberAssignmentError(
                    f"replay assignment {name} mapping is not one-to-one"
                )
        if self.primary_obligation_id not in {
            item.obligation_id for item in assignments
        }:
            raise ReplayMemberAssignmentError(
                "primary replay obligation is outside its assignment set"
            )
        object.__setattr__(
            self,
            "identity",
            "replay-member-assignment-set:"
            + canonical_digest(
                domain="replay-member-assignment-set",
                payload=self.to_identity_payload(),
            ),
        )

    @property
    def obligation_ids(self) -> tuple[str, ...]:
        return tuple(item.obligation_id for item in self.assignments)

    @property
    def replay_executable_ids(self) -> tuple[str, ...]:
        return tuple(item.replay_executable_id for item in self.assignments)

    @property
    def historical_family_authority_ids(self) -> tuple[str, ...]:
        return tuple(
            item.historical_family_authority_id
            for item in self.assignments
        )

    @property
    def primary(self) -> ReplayMemberAssignment:
        return next(
            item
            for item in self.assignments
            if item.obligation_id == self.primary_obligation_id
        )

    def by_obligation(self) -> dict[str, ReplayMemberAssignment]:
        return {item.obligation_id: item for item in self.assignments}

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "assignments": [
                item.to_identity_payload() for item in self.assignments
            ],
            "mission_id": self.mission_id,
            "primary_obligation_id": self.primary_obligation_id,
            "schema": REPLAY_MEMBER_ASSIGNMENT_SET_SCHEMA,
        }


def replay_member_assignment_set_from_payload(
    value: object,
) -> ReplayMemberAssignmentSet:
    if (
        type(value) is not dict
        or set(value)
        != {
            "assignments",
            "mission_id",
            "primary_obligation_id",
            "schema",
        }
        or value.get("schema") != REPLAY_MEMBER_ASSIGNMENT_SET_SCHEMA
        or not isinstance(value.get("assignments"), list)
    ):
        raise ReplayMemberAssignmentError(
            "replay member assignment set payload is malformed"
        )
    assignment_set = ReplayMemberAssignmentSet(
        mission_id=value["mission_id"],
        primary_obligation_id=value["primary_obligation_id"],
        assignments=tuple(
            replay_member_assignment_from_payload(item)
            for item in value["assignments"]
        ),
    )
    if canonical_bytes(assignment_set.to_identity_payload()) != canonical_bytes(
        value
    ):
        raise ReplayMemberAssignmentError(
            "replay member assignment set payload is not canonical"
        )
    return assignment_set


def assignment_set_from_semantic_proposal(
    proposal: Mapping[str, Any],
) -> ReplayMemberAssignmentSet | None:
    raw = proposal.get("replay_member_assignments")
    if raw is None:
        return None
    return replay_member_assignment_set_from_payload(raw)


__all__ = [
    "REPLAY_MEMBER_ASSIGNMENT_SCHEMA",
    "REPLAY_MEMBER_ASSIGNMENT_SET_SCHEMA",
    "ReplayMemberAssignment",
    "ReplayMemberAssignmentError",
    "ReplayMemberAssignmentSet",
    "assignment_set_from_semantic_proposal",
    "replay_member_assignment_from_payload",
    "replay_member_assignment_set_from_payload",
]
