"""Lossless transport for original and additive Study-diagnosis authority."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from axiom_rift.operations.effective_study_diagnosis import (
    EffectiveStudyDiagnosis,
    EffectiveStudyDiagnosisError,
    effective_study_diagnosis,
)
from axiom_rift.storage.index import LocalIndex, LocalIndexView


class DiagnosisAuthorityContextError(RuntimeError):
    """A decision boundary dropped or changed diagnosis authority."""


def _optional_ascii(name: str, value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or not value.isascii():
        raise DiagnosisAuthorityContextError(f"{name} is malformed")
    return value


@dataclass(frozen=True, slots=True)
class DiagnosisAuthorityContext:
    """Three-field authority packet carried through every Decision boundary."""

    study_diagnosis_id: str | None = None
    study_diagnosis_correction_id: str | None = None
    diagnosis_correction_audit_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "study_diagnosis_id",
            "study_diagnosis_correction_id",
            "diagnosis_correction_audit_id",
        ):
            _optional_ascii(name, getattr(self, name))
        if self.study_diagnosis_id is None and (
            self.study_diagnosis_correction_id is not None
            or self.diagnosis_correction_audit_id is not None
        ):
            raise DiagnosisAuthorityContextError(
                "diagnosis overlay authority lacks its original diagnosis"
            )
        if (
            self.study_diagnosis_correction_id is None
        ) != (
            self.diagnosis_correction_audit_id is None
        ):
            raise DiagnosisAuthorityContextError(
                "diagnosis correction and complete-inventory audit must travel together"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DiagnosisAuthorityContext":
        return cls(
            study_diagnosis_id=_optional_ascii(
                "study diagnosis identity",
                value.get("study_diagnosis_id"),
            ),
            study_diagnosis_correction_id=_optional_ascii(
                "Study diagnosis correction identity",
                value.get("study_diagnosis_correction_id"),
            ),
            diagnosis_correction_audit_id=_optional_ascii(
                "diagnosis correction audit identity",
                value.get("diagnosis_correction_audit_id"),
            ),
        )

    def to_action_fields(self) -> dict[str, str]:
        return {
            name: value
            for name, value in (
                ("study_diagnosis_id", self.study_diagnosis_id),
                (
                    "study_diagnosis_correction_id",
                    self.study_diagnosis_correction_id,
                ),
                (
                    "diagnosis_correction_audit_id",
                    self.diagnosis_correction_audit_id,
                ),
            )
            if value is not None
        }

    def basis_pairs(self) -> frozenset[tuple[str, str]]:
        return frozenset(
            (kind, record_id)
            for kind, record_id in (
                ("study-diagnosis", self.study_diagnosis_id),
                (
                    "study-diagnosis-correction",
                    self.study_diagnosis_correction_id,
                ),
                (
                    "study-diagnosis-correction-audit",
                    self.diagnosis_correction_audit_id,
                ),
            )
            if record_id is not None
        )

    def require_effective(
        self,
        index: LocalIndex | LocalIndexView,
        *,
        mission_id: str | None = None,
    ) -> EffectiveStudyDiagnosis | None:
        if self.study_diagnosis_id is None:
            return None
        try:
            diagnosis = effective_study_diagnosis(
                index,
                self.study_diagnosis_id,
            )
        except EffectiveStudyDiagnosisError as exc:
            raise DiagnosisAuthorityContextError(str(exc)) from exc
        observed_correction_id = (
            None if diagnosis.correction is None else diagnosis.correction.record_id
        )
        observed_audit_id = (
            None
            if diagnosis.correction is None
            else diagnosis.correction.payload.get("audit_id")
        )
        if (
            self.study_diagnosis_correction_id != observed_correction_id
            or (
                diagnosis.correction is not None
                and self.diagnosis_correction_audit_id != observed_audit_id
            )
        ):
            raise DiagnosisAuthorityContextError(
                "effective Study diagnosis authority drifted"
            )
        if self.diagnosis_correction_audit_id is not None:
            audit = index.get(
                "study-diagnosis-correction-audit",
                self.diagnosis_correction_audit_id,
            )
            if audit is None or (
                mission_id is not None
                and audit.subject != f"Mission:{mission_id}"
            ):
                raise DiagnosisAuthorityContextError(
                    "diagnosis correction audit is unavailable"
                )
        if mission_id is not None and (
            diagnosis.payload.get("mission_id") != mission_id
        ):
            raise DiagnosisAuthorityContextError(
                "Study diagnosis belongs to another Mission"
            )
        return diagnosis


__all__ = [
    "DiagnosisAuthorityContext",
    "DiagnosisAuthorityContextError",
]
