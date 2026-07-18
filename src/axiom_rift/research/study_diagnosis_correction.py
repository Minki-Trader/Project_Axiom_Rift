"""Typed additive correction authority for claim-scoped Study diagnosis."""

from __future__ import annotations

from dataclasses import dataclass, field

from axiom_rift.core.canonical import CanonicalValue
from axiom_rift.core.identity import canonical_digest


CLAIM_SCOPED_DIAGNOSIS_PROTOCOL_ID = (
    "protocol:claim_scoped_noncompensating_diagnosis.v1"
)


class StudyDiagnosisCorrectionError(ValueError):
    """A correction request is incomplete, stale, or not ASCII canonical."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise StudyDiagnosisCorrectionError(f"{name} must be non-empty ASCII")
    return value


def _diagnosis_id(value: object) -> str:
    text = _ascii("original diagnosis identity", value)
    digest = text.removeprefix("diagnosis:")
    if (
        text == digest
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise StudyDiagnosisCorrectionError(
            "original diagnosis identity is malformed"
        )
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class StudyDiagnosisCorrectionAudit:
    """Expected complete mismatch inventory at one stable Mission boundary."""

    mission_id: str
    original_diagnosis_ids: tuple[str, ...]
    prior_journal_event_id: str
    prior_journal_sequence: int
    rationale: str
    protocol_id: str = CLAIM_SCOPED_DIAGNOSIS_PROTOCOL_ID
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("mission_id", self.mission_id)
        _ascii("correction rationale", self.rationale)
        _ascii("correction protocol", self.protocol_id)
        prior_event = _ascii(
            "prior Journal event identity",
            self.prior_journal_event_id,
        )
        if (
            len(prior_event) != 64
            or any(character not in "0123456789abcdef" for character in prior_event)
        ):
            raise StudyDiagnosisCorrectionError(
                "prior Journal event identity is malformed"
            )
        if (
            type(self.prior_journal_sequence) is not int
            or self.prior_journal_sequence < 1
        ):
            raise StudyDiagnosisCorrectionError(
                "prior Journal sequence must be positive"
            )
        values = self.original_diagnosis_ids
        if type(values) is not tuple or not values:
            raise StudyDiagnosisCorrectionError(
                "correction audit requires diagnosis identities"
            )
        normalized = tuple(sorted(_diagnosis_id(value) for value in values))
        if len(set(normalized)) != len(normalized):
            raise StudyDiagnosisCorrectionError(
                "correction audit diagnosis identities are not unique"
            )
        object.__setattr__(self, "original_diagnosis_ids", normalized)
        object.__setattr__(
            self,
            "identity",
            "diagnosis-correction-audit:"
            + canonical_digest(
                domain="study-diagnosis-correction-audit",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "mission_id": self.mission_id,
            "original_diagnosis_ids": list(self.original_diagnosis_ids),
            "prior_journal_event_id": self.prior_journal_event_id,
            "prior_journal_sequence": self.prior_journal_sequence,
            "protocol_id": self.protocol_id,
            "rationale": self.rationale,
            "schema": "study_diagnosis_correction_audit.v1",
        }


__all__ = [
    "CLAIM_SCOPED_DIAGNOSIS_PROTOCOL_ID",
    "StudyDiagnosisCorrectionAudit",
    "StudyDiagnosisCorrectionError",
]
