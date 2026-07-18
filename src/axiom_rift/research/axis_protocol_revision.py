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
AXIS_PROTOCOL_REVISION_SCHEMA_V2 = "axis_protocol_revision_proposal.v2"
AXIS_PROTOCOL_REVISION_SCHEMA_V3 = "axis_protocol_revision_proposal.v3"


class AxisProtocolRevisionReason(str, Enum):
    COMPLETION_VALIDITY_INVALIDATED = "completion_validity_invalidated"
    ENGINEERING_REQUIRES_SCIENTIFIC_CHANGE = (
        "engineering_requires_scientific_change"
    )
    HISTORICAL_COMPLETION_VALIDITY_INVALIDATED = (
        "historical_completion_validity_invalidated"
    )


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
    satisfaction_invalidation_record_id: str | None
    semantic_question_lineage: SemanticQuestionLineageProposal
    reason_code: AxisProtocolRevisionReason
    reason: str
    scientific_change_return_record_id: str | None = None
    completion_validity_invalidation_record_id: str | None = None
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
        if (
            self.reason_code
            is AxisProtocolRevisionReason.COMPLETION_VALIDITY_INVALIDATED
        ):
            _identity(
                "satisfaction_invalidation_record_id",
                self.satisfaction_invalidation_record_id,
                prefix="historical-replay-satisfaction-invalidation:",
            )
            if self.scientific_change_return_record_id is not None:
                raise ValueError(
                    "completion invalidation revision cannot bind a science return"
                )
            if self.completion_validity_invalidation_record_id is not None:
                raise ValueError(
                    "satisfaction invalidation revision cannot bind a completion "
                    "validity invalidation"
                )
        elif (
            self.reason_code
            is AxisProtocolRevisionReason.ENGINEERING_REQUIRES_SCIENTIFIC_CHANGE
        ):
            if self.satisfaction_invalidation_record_id is not None:
                raise ValueError(
                    "scientific-change revision cannot bind a satisfaction invalidation"
                )
            _identity(
                "scientific_change_return_record_id",
                self.scientific_change_return_record_id,
                prefix="historical-replay-scientific-change-return:",
            )
            if self.completion_validity_invalidation_record_id is not None:
                raise ValueError(
                    "scientific-change revision cannot bind a completion validity "
                    "invalidation"
                )
        elif (
            self.reason_code
            is AxisProtocolRevisionReason.HISTORICAL_COMPLETION_VALIDITY_INVALIDATED
        ):
            if self.satisfaction_invalidation_record_id is not None:
                raise ValueError(
                    "historical completion revision cannot bind a satisfaction "
                    "invalidation"
                )
            if self.scientific_change_return_record_id is not None:
                raise ValueError(
                    "historical completion revision cannot bind a science return"
                )
            _identity(
                "completion_validity_invalidation_record_id",
                self.completion_validity_invalidation_record_id,
                prefix="historical-scientific-validity-invalidation:",
            )
        else:
            raise ValueError("protocol revision reason is unsupported")
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
        payload: dict[str, CanonicalValue] = {
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
            "semantic_question_lineage": (
                self.semantic_question_lineage.to_identity_payload()
            ),
            "semantic_question_lineage_id": (
                self.semantic_question_lineage.identity
            ),
            "successor_architecture_family": self.successor_architecture_family,
            "successor_axis_identity": self.successor_axis_identity,
        }
        if (
            self.reason_code
            is AxisProtocolRevisionReason.COMPLETION_VALIDITY_INVALIDATED
        ):
            payload["satisfaction_invalidation_record_id"] = (
                self.satisfaction_invalidation_record_id
            )
            payload["schema"] = AXIS_PROTOCOL_REVISION_SCHEMA
        elif (
            self.reason_code
            is AxisProtocolRevisionReason.ENGINEERING_REQUIRES_SCIENTIFIC_CHANGE
        ):
            payload["scientific_change_return_record_id"] = (
                self.scientific_change_return_record_id
            )
            payload["schema"] = AXIS_PROTOCOL_REVISION_SCHEMA_V2
        else:
            payload["completion_validity_invalidation_record_id"] = (
                self.completion_validity_invalidation_record_id
            )
            payload["schema"] = AXIS_PROTOCOL_REVISION_SCHEMA_V3
        return payload

    @property
    def authority_kind(self) -> str:
        if (
            self.reason_code
            is AxisProtocolRevisionReason.COMPLETION_VALIDITY_INVALIDATED
        ):
            return "historical-replay-satisfaction-invalidation"
        if (
            self.reason_code
            is AxisProtocolRevisionReason.ENGINEERING_REQUIRES_SCIENTIFIC_CHANGE
        ):
            return "historical-replay-scientific-change-return"
        return "historical-scientific-validity-invalidation"

    @property
    def authority_record_id(self) -> str:
        if (
            self.reason_code
            is AxisProtocolRevisionReason.COMPLETION_VALIDITY_INVALIDATED
        ):
            value = self.satisfaction_invalidation_record_id
        elif (
            self.reason_code
            is AxisProtocolRevisionReason.ENGINEERING_REQUIRES_SCIENTIFIC_CHANGE
        ):
            value = self.scientific_change_return_record_id
        else:
            value = self.completion_validity_invalidation_record_id
        assert isinstance(value, str)
        return value

    @classmethod
    def from_mapping(cls, value: object) -> AxisProtocolRevisionProposal:
        common_fields = {
            "axis_id",
            "mechanism_family",
            "mission_id",
            "predecessor_architecture_family",
            "predecessor_axis_identity",
            "reason",
            "reason_code",
            "replay_obligation_id",
            "schema",
            "semantic_question_lineage",
            "semantic_question_lineage_id",
            "successor_architecture_family",
            "successor_axis_identity",
        }
        if not isinstance(value, Mapping):
            raise ValueError("axis protocol revision payload is malformed")
        schema = value.get("schema")
        if schema == AXIS_PROTOCOL_REVISION_SCHEMA:
            fields = common_fields | {"satisfaction_invalidation_record_id"}
        elif schema == AXIS_PROTOCOL_REVISION_SCHEMA_V2:
            fields = common_fields | {"scientific_change_return_record_id"}
        elif schema == AXIS_PROTOCOL_REVISION_SCHEMA_V3:
            fields = common_fields | {
                "completion_validity_invalidation_record_id"
            }
        else:
            raise ValueError("axis protocol revision schema is unsupported")
        if set(value) != fields:
            raise ValueError("axis protocol revision payload is malformed")
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
            satisfaction_invalidation_record_id=(
                value["satisfaction_invalidation_record_id"]
                if schema == AXIS_PROTOCOL_REVISION_SCHEMA
                else None
            ),  # type: ignore[arg-type]
            semantic_question_lineage=lineage,
            reason_code=AxisProtocolRevisionReason(value["reason_code"]),
            reason=value["reason"],  # type: ignore[arg-type]
            scientific_change_return_record_id=(
                value["scientific_change_return_record_id"]
                if schema == AXIS_PROTOCOL_REVISION_SCHEMA_V2
                else None
            ),  # type: ignore[arg-type]
            completion_validity_invalidation_record_id=(
                value["completion_validity_invalidation_record_id"]
                if schema == AXIS_PROTOCOL_REVISION_SCHEMA_V3
                else None
            ),  # type: ignore[arg-type]
        )
        if proposal.to_identity_payload() != dict(value):
            raise ValueError("axis protocol revision payload is not canonical")
        return proposal


__all__ = [
    "AXIS_PROTOCOL_REVISION_SCHEMA",
    "AXIS_PROTOCOL_REVISION_SCHEMA_V2",
    "AXIS_PROTOCOL_REVISION_SCHEMA_V3",
    "AxisProtocolRevisionProposal",
    "AxisProtocolRevisionReason",
]
