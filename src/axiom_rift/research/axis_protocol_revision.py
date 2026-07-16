"""Typed authority for one same-mechanism prospective protocol revision."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from axiom_rift.core.canonical import CanonicalValue
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.governance import require_architecture_family
from axiom_rift.research.semantic_question import (
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)


AXIS_PROTOCOL_REVISION_SCHEMA = "axis_protocol_revision_proposal.v1"


class AxisProtocolRevisionReason(str, Enum):
    COMPLETION_VALIDITY_INVALIDATED = "completion_validity_invalidated"


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _identity(name: str, value: object, *, prefix: str) -> str:
    text = _ascii(name, value)
    digest = text.removeprefix(prefix)
    if text == digest or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{name} must use {prefix}<sha256>")
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class AxisProtocolRevisionProposal:
    mission_id: str
    axis_id: str
    predecessor_axis_identity: str
    successor_axis_identity: str
    mechanism_family: str
    predecessor_architecture_family: str
    successor_architecture_family: str
    replay_obligation_id: str
    satisfaction_invalidation_record_id: str
    semantic_question_lineage: SemanticQuestionLineageProposal
    reason_code: AxisProtocolRevisionReason
    reason: str
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("mission_id", self.mission_id)
        _ascii("axis_id", self.axis_id)
        _identity(
            "predecessor_axis_identity",
            self.predecessor_axis_identity,
            prefix="axis:",
        )
        _identity(
            "successor_axis_identity",
            self.successor_axis_identity,
            prefix="axis:",
        )
        if self.predecessor_axis_identity == self.successor_axis_identity:
            raise ValueError("protocol revision must change the axis identity")
        _ascii("mechanism_family", self.mechanism_family)
        require_architecture_family(self.predecessor_architecture_family)
        require_architecture_family(self.successor_architecture_family)
        if self.predecessor_architecture_family == self.successor_architecture_family:
            raise ValueError("protocol revision must change its exact architecture")
        _identity(
            "replay_obligation_id",
            self.replay_obligation_id,
            prefix="historical-replay-obligation:",
        )
        _identity(
            "satisfaction_invalidation_record_id",
            self.satisfaction_invalidation_record_id,
            prefix="historical-replay-satisfaction-invalidation:",
        )
        if (
            not isinstance(
                self.semantic_question_lineage,
                SemanticQuestionLineageProposal,
            )
            or self.semantic_question_lineage.relation
            is not SemanticQuestionRelation.CONTINUATION
            or self.semantic_question_lineage.predecessor_core_id
            != self.semantic_question_lineage.successor_core_id
        ):
            raise ValueError(
                "protocol revision requires exact same-core continuation lineage"
            )
        if (
            self.reason_code
            is not AxisProtocolRevisionReason.COMPLETION_VALIDITY_INVALIDATED
        ):
            raise ValueError("protocol revision reason is unsupported")
        _ascii("protocol revision reason", self.reason)
        object.__setattr__(
            self,
            "identity",
            "axis-protocol-revision:"
            + canonical_digest(
                domain="axis-protocol-revision-proposal",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "axis_id": self.axis_id,
            "mechanism_family": self.mechanism_family,
            "mission_id": self.mission_id,
            "predecessor_architecture_family": (
                self.predecessor_architecture_family
            ),
            "predecessor_axis_identity": self.predecessor_axis_identity,
            "reason": self.reason,
            "reason_code": self.reason_code.value,
            "replay_obligation_id": self.replay_obligation_id,
            "satisfaction_invalidation_record_id": (
                self.satisfaction_invalidation_record_id
            ),
            "schema": AXIS_PROTOCOL_REVISION_SCHEMA,
            "semantic_question_lineage": (
                self.semantic_question_lineage.to_identity_payload()
            ),
            "semantic_question_lineage_id": (
                self.semantic_question_lineage.identity
            ),
            "successor_architecture_family": self.successor_architecture_family,
            "successor_axis_identity": self.successor_axis_identity,
        }

    @classmethod
    def from_mapping(cls, value: object) -> AxisProtocolRevisionProposal:
        fields = {
            "axis_id",
            "mechanism_family",
            "mission_id",
            "predecessor_architecture_family",
            "predecessor_axis_identity",
            "reason",
            "reason_code",
            "replay_obligation_id",
            "satisfaction_invalidation_record_id",
            "schema",
            "semantic_question_lineage",
            "semantic_question_lineage_id",
            "successor_architecture_family",
            "successor_axis_identity",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("axis protocol revision payload is malformed")
        if value.get("schema") != AXIS_PROTOCOL_REVISION_SCHEMA:
            raise ValueError("axis protocol revision schema is unsupported")
        lineage_value = value.get("semantic_question_lineage")
        if not isinstance(lineage_value, Mapping):
            raise ValueError("axis protocol revision lineage is absent")
        lineage = SemanticQuestionLineageProposal.from_identity_payload(
            lineage_value
        )
        if value.get("semantic_question_lineage_id") != lineage.identity:
            raise ValueError("axis protocol revision lineage identity drifted")
        proposal = cls(
            mission_id=value["mission_id"],  # type: ignore[arg-type]
            axis_id=value["axis_id"],  # type: ignore[arg-type]
            predecessor_axis_identity=value["predecessor_axis_identity"],  # type: ignore[arg-type]
            successor_axis_identity=value["successor_axis_identity"],  # type: ignore[arg-type]
            mechanism_family=value["mechanism_family"],  # type: ignore[arg-type]
            predecessor_architecture_family=value["predecessor_architecture_family"],  # type: ignore[arg-type]
            successor_architecture_family=value["successor_architecture_family"],  # type: ignore[arg-type]
            replay_obligation_id=value["replay_obligation_id"],  # type: ignore[arg-type]
            satisfaction_invalidation_record_id=value["satisfaction_invalidation_record_id"],  # type: ignore[arg-type]
            semantic_question_lineage=lineage,
            reason_code=AxisProtocolRevisionReason(value["reason_code"]),
            reason=value["reason"],  # type: ignore[arg-type]
        )
        if proposal.to_identity_payload() != dict(value):
            raise ValueError("axis protocol revision payload is not canonical")
        return proposal


__all__ = [
    "AXIS_PROTOCOL_REVISION_SCHEMA",
    "AxisProtocolRevisionProposal",
    "AxisProtocolRevisionReason",
]
