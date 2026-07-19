"""Typed authority for a prospective Study engineering reentry.

An engineering gap is neither scientific evidence nor a reason to strand an
otherwise valuable Portfolio axis.  This type binds one closed predecessor,
its exact requires-scientific-change disposition, and one distinct successor
protocol before the successor can be selected or opened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from axiom_rift.core.canonical import CanonicalValue
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.semantic_question import (
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)


PROSPECTIVE_ENGINEERING_REENTRY_SCHEMA = (
    "prospective_engineering_reentry.v1"
)
_ALLOWED_ACTIONS = frozenset({"contrast", "deepen"})


class ProspectiveEngineeringReentryError(ValueError):
    """Raised when prospective reentry authority is incomplete or ambiguous."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ProspectiveEngineeringReentryError(
            f"{name} must be non-empty ASCII"
        )
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ProspectiveEngineeringReentryError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


def _identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    suffix = text.removeprefix(prefix)
    if text == suffix:
        raise ProspectiveEngineeringReentryError(
            f"{name} must use the {prefix} namespace"
        )
    _digest(name, suffix)
    return text


def _study_id(name: str, value: object) -> str:
    text = _ascii(name, value)
    suffix = text.removeprefix("STU-")
    if (
        text == suffix
        or not suffix
        or suffix[0] == "-"
        or suffix[-1] == "-"
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
            for character in suffix
        )
    ):
        raise ProspectiveEngineeringReentryError(
            f"{name} must be a canonical Study id"
        )
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class ProspectiveEngineeringReentry:
    mission_id: str
    portfolio_snapshot_id: str
    target_axis_id: str
    target_axis_identity: str
    predecessor_study_id: str
    successor_study_id: str
    study_diagnosis_id: str
    study_close_record_id: str
    completion_record_id: str
    disposition_record_id: str
    disposition_hash: str
    successor_artifact_hash: str
    successor_baseline_executable_id: str
    portfolio_action: str
    semantic_question_lineage: SemanticQuestionLineageProposal
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("mission_id", self.mission_id)
        _identity(
            "portfolio_snapshot_id",
            self.portfolio_snapshot_id,
            "portfolio:",
        )
        _ascii("target_axis_id", self.target_axis_id)
        _identity(
            "target_axis_identity",
            self.target_axis_identity,
            "axis:",
        )
        predecessor = _study_id(
            "predecessor_study_id",
            self.predecessor_study_id,
        )
        successor = _study_id(
            "successor_study_id",
            self.successor_study_id,
        )
        if predecessor == successor:
            raise ProspectiveEngineeringReentryError(
                "engineering reentry requires a distinct successor Study"
            )
        _identity(
            "study_diagnosis_id",
            self.study_diagnosis_id,
            "diagnosis:",
        )
        _digest("study_close_record_id", self.study_close_record_id)
        _digest("completion_record_id", self.completion_record_id)
        _digest("disposition_record_id", self.disposition_record_id)
        _digest("disposition_hash", self.disposition_hash)
        _digest("successor_artifact_hash", self.successor_artifact_hash)
        _identity(
            "successor_baseline_executable_id",
            self.successor_baseline_executable_id,
            "executable:",
        )
        action = _ascii("portfolio_action", self.portfolio_action)
        if action not in _ALLOWED_ACTIONS:
            raise ProspectiveEngineeringReentryError(
                "engineering reentry action must be contrast or deepen"
            )
        lineage = self.semantic_question_lineage
        if (
            not isinstance(lineage, SemanticQuestionLineageProposal)
            or lineage.relation
            is not SemanticQuestionRelation.ENGINEERING_REENTRY
            or lineage.predecessor_study_id != predecessor
            or lineage.successor_study_id != successor
            or lineage.predecessor_core_id != lineage.successor_core_id
        ):
            raise ProspectiveEngineeringReentryError(
                "engineering reentry requires exact same-core typed lineage"
            )
        object.__setattr__(
            self,
            "identity",
            "prospective-engineering-reentry:"
            + canonical_digest(
                domain="prospective-engineering-reentry",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "completion_record_id": self.completion_record_id,
            "disposition_hash": self.disposition_hash,
            "disposition_record_id": self.disposition_record_id,
            "mission_id": self.mission_id,
            "portfolio_action": self.portfolio_action,
            "portfolio_snapshot_id": self.portfolio_snapshot_id,
            "predecessor_study_id": self.predecessor_study_id,
            "schema": PROSPECTIVE_ENGINEERING_REENTRY_SCHEMA,
            "semantic_question_lineage": (
                self.semantic_question_lineage.to_identity_payload()
            ),
            "semantic_question_lineage_id": (
                self.semantic_question_lineage.identity
            ),
            "study_close_record_id": self.study_close_record_id,
            "study_diagnosis_id": self.study_diagnosis_id,
            "successor_artifact_hash": self.successor_artifact_hash,
            "successor_baseline_executable_id": (
                self.successor_baseline_executable_id
            ),
            "successor_study_id": self.successor_study_id,
            "target_axis_id": self.target_axis_id,
            "target_axis_identity": self.target_axis_identity,
        }

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, object],
    ) -> ProspectiveEngineeringReentry:
        fields = {
            "completion_record_id",
            "disposition_hash",
            "disposition_record_id",
            "mission_id",
            "portfolio_action",
            "portfolio_snapshot_id",
            "predecessor_study_id",
            "schema",
            "semantic_question_lineage",
            "semantic_question_lineage_id",
            "study_close_record_id",
            "study_diagnosis_id",
            "successor_artifact_hash",
            "successor_baseline_executable_id",
            "successor_study_id",
            "target_axis_id",
            "target_axis_identity",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ProspectiveEngineeringReentryError(
                "engineering reentry payload fields differ"
            )
        if value.get("schema") != PROSPECTIVE_ENGINEERING_REENTRY_SCHEMA:
            raise ProspectiveEngineeringReentryError(
                "engineering reentry schema is unsupported"
            )
        lineage_value = value.get("semantic_question_lineage")
        if not isinstance(lineage_value, Mapping):
            raise ProspectiveEngineeringReentryError(
                "engineering reentry lineage payload is absent"
            )
        try:
            lineage = SemanticQuestionLineageProposal.from_identity_payload(
                lineage_value
            )
        except (TypeError, ValueError) as exc:
            raise ProspectiveEngineeringReentryError(str(exc)) from exc
        plan = cls(
            completion_record_id=value["completion_record_id"],  # type: ignore[arg-type]
            disposition_hash=value["disposition_hash"],  # type: ignore[arg-type]
            disposition_record_id=value["disposition_record_id"],  # type: ignore[arg-type]
            mission_id=value["mission_id"],  # type: ignore[arg-type]
            portfolio_action=value["portfolio_action"],  # type: ignore[arg-type]
            portfolio_snapshot_id=value["portfolio_snapshot_id"],  # type: ignore[arg-type]
            predecessor_study_id=value["predecessor_study_id"],  # type: ignore[arg-type]
            semantic_question_lineage=lineage,
            study_close_record_id=value["study_close_record_id"],  # type: ignore[arg-type]
            study_diagnosis_id=value["study_diagnosis_id"],  # type: ignore[arg-type]
            successor_artifact_hash=value["successor_artifact_hash"],  # type: ignore[arg-type]
            successor_baseline_executable_id=value["successor_baseline_executable_id"],  # type: ignore[arg-type]
            successor_study_id=value["successor_study_id"],  # type: ignore[arg-type]
            target_axis_id=value["target_axis_id"],  # type: ignore[arg-type]
            target_axis_identity=value["target_axis_identity"],  # type: ignore[arg-type]
        )
        if (
            value.get("semantic_question_lineage_id")
            != lineage.identity
            or plan.to_identity_payload() != dict(value)
        ):
            raise ProspectiveEngineeringReentryError(
                "engineering reentry payload is not canonical"
            )
        return plan


__all__ = [
    "PROSPECTIVE_ENGINEERING_REENTRY_SCHEMA",
    "ProspectiveEngineeringReentry",
    "ProspectiveEngineeringReentryError",
]
