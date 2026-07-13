"""Typed additive dispositions for one immutable Portfolio axis.

An axis disposition does not rewrite a Portfolio snapshot or turn incomplete
evidence into a prune.  It binds the exact evidence that currently exists and
states what a successor campaign must preserve, replay, reopen, defer, or
retire with an explicit reason.  The StateWriter independently derives the
effective evidence state and candidate eligibility from the referenced durable
records before accepting this proposal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from axiom_rift.core.identity import canonical_digest


class AxisDispositionError(ValueError):
    """Raised when an axis disposition is not typed or tightly bound."""


class AxisEvidenceState(str, Enum):
    """Terminal-relevant aggregate states derived from exact evidence."""

    FRONTIER = "frontier"
    PARTIAL_POSITIVE = "partial_positive"
    INVALID = "invalid"
    NOT_EVALUABLE = "not_evaluable"
    UNRESOLVED = "unresolved"
    LOW_INFORMATION = "low_information"


class AxisDispositionAction(str, Enum):
    """Honest current-Mission disposition without universal claim authority."""

    PRESERVE = "preserve"
    REPLAY = "replay"
    REOPEN = "reopen"
    DEFER = "defer"
    RETIRE_WITH_REASON = "retire_with_reason"


class AxisEvidenceKind(str, Enum):
    """Durable record kinds from which the Writer can derive axis state."""

    JOB_COMPLETION = "job-completed"
    HISTORICAL_ADJUDICATION = "historical-scientific-adjudication"
    NEGATIVE_MEMORY = "negative-memory"


_ACTIONS_BY_STATE = {
    AxisEvidenceState.FRONTIER: frozenset(
        {
            AxisDispositionAction.PRESERVE,
            AxisDispositionAction.REPLAY,
            AxisDispositionAction.REOPEN,
            AxisDispositionAction.DEFER,
        }
    ),
    AxisEvidenceState.PARTIAL_POSITIVE: frozenset(
        {
            AxisDispositionAction.PRESERVE,
            AxisDispositionAction.REPLAY,
            AxisDispositionAction.REOPEN,
            AxisDispositionAction.DEFER,
        }
    ),
    AxisEvidenceState.INVALID: frozenset(
        {
            AxisDispositionAction.REPLAY,
            AxisDispositionAction.REOPEN,
            AxisDispositionAction.DEFER,
            AxisDispositionAction.RETIRE_WITH_REASON,
        }
    ),
    AxisEvidenceState.NOT_EVALUABLE: frozenset(
        {
            AxisDispositionAction.REPLAY,
            AxisDispositionAction.REOPEN,
            AxisDispositionAction.DEFER,
            AxisDispositionAction.RETIRE_WITH_REASON,
        }
    ),
    AxisEvidenceState.UNRESOLVED: frozenset(
        {
            AxisDispositionAction.REPLAY,
            AxisDispositionAction.REOPEN,
            AxisDispositionAction.DEFER,
            AxisDispositionAction.RETIRE_WITH_REASON,
        }
    ),
    AxisEvidenceState.LOW_INFORMATION: frozenset(
        {
            AxisDispositionAction.REPLAY,
            AxisDispositionAction.REOPEN,
            AxisDispositionAction.DEFER,
            AxisDispositionAction.RETIRE_WITH_REASON,
        }
    ),
}


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise AxisDispositionError(f"{name} must be non-empty ASCII")
    return value


def _identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    digest = text.removeprefix(prefix)
    if text == digest or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise AxisDispositionError(f"{name} must use {prefix}<sha256>")
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class AxisEvidenceReference:
    """One exact durable input to a Writer-derived axis state."""

    kind: AxisEvidenceKind
    record_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AxisEvidenceKind):
            raise AxisDispositionError("axis evidence kind is not typed")
        _ascii("axis evidence record_id", self.record_id)

    def manifest(self) -> dict[str, str]:
        return {"kind": self.kind.value, "record_id": self.record_id}


@dataclass(frozen=True, slots=True, kw_only=True)
class AxisDisposition:
    """A typed proposal whose evidence state is recomputed by the Writer."""

    mission_id: str
    portfolio_snapshot_id: str
    axis_id: str
    axis_identity: str
    evidence_state: AxisEvidenceState
    action: AxisDispositionAction
    evidence_references: tuple[AxisEvidenceReference, ...]
    reason_codes: tuple[str, ...]
    rationale: str
    continuation_or_reopen_condition: str
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("axis disposition mission_id", self.mission_id)
        _identity(
            "axis disposition portfolio_snapshot_id",
            self.portfolio_snapshot_id,
            "portfolio:",
        )
        _ascii("axis disposition axis_id", self.axis_id)
        _identity("axis disposition axis_identity", self.axis_identity, "axis:")
        if not isinstance(self.evidence_state, AxisEvidenceState):
            raise AxisDispositionError("axis evidence state is not typed")
        if not isinstance(self.action, AxisDispositionAction):
            raise AxisDispositionError("axis disposition action is not typed")
        if self.action not in _ACTIONS_BY_STATE[self.evidence_state]:
            raise AxisDispositionError(
                "axis disposition action conflicts with its evidence state"
            )
        if type(self.evidence_references) is not tuple or not self.evidence_references:
            raise AxisDispositionError("axis disposition requires durable evidence")
        if any(
            not isinstance(reference, AxisEvidenceReference)
            for reference in self.evidence_references
        ):
            raise AxisDispositionError("axis evidence references are not typed")
        references = tuple(
            sorted(
                self.evidence_references,
                key=lambda item: (item.kind.value, item.record_id),
            )
        )
        if len({(item.kind, item.record_id) for item in references}) != len(references):
            raise AxisDispositionError("axis evidence references must be unique")
        reasons = tuple(sorted(_ascii("axis reason code", item) for item in self.reason_codes))
        if not reasons or len(set(reasons)) != len(reasons):
            raise AxisDispositionError("axis reason codes must be unique and non-empty")
        _ascii("axis disposition rationale", self.rationale)
        _ascii(
            "axis continuation or reopen condition",
            self.continuation_or_reopen_condition,
        )
        object.__setattr__(self, "evidence_references", references)
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(
            self,
            "identity",
            "axis-disposition:"
            + canonical_digest(
                domain="axis-disposition",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "axis_id": self.axis_id,
            "axis_identity": self.axis_identity,
            "continuation_or_reopen_condition": self.continuation_or_reopen_condition,
            "evidence_references": [
                item.manifest() for item in self.evidence_references
            ],
            "evidence_state": self.evidence_state.value,
            "mission_id": self.mission_id,
            "portfolio_snapshot_id": self.portfolio_snapshot_id,
            "rationale": self.rationale,
            "reason_codes": list(self.reason_codes),
            "schema": "axis_disposition.v1",
        }


__all__ = [
    "AxisDisposition",
    "AxisDispositionAction",
    "AxisDispositionError",
    "AxisEvidenceKind",
    "AxisEvidenceReference",
    "AxisEvidenceState",
]
