"""Project scientific diagnosis through additive completion evidence scope."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from axiom_rift.operations.completion_evidence_scope import (
    EffectiveCompletionEvidenceScope,
)
from axiom_rift.research.governance import DiagnosisConfidence, EvidenceState
from axiom_rift.research.scientific_diagnosis import (
    ScientificDiagnosisError,
    ScientificDiagnosisPattern,
    diagnose_scientific_adjudications,
)


class EffectiveScientificDiagnosisError(RuntimeError):
    """Effective completion scope cannot support a deterministic diagnosis."""


def diagnose_effective_scientific_adjudications(
    values: Sequence[
        tuple[Mapping[str, Any], EffectiveCompletionEvidenceScope]
    ],
) -> ScientificDiagnosisPattern:
    """Diagnose only completions that retain scientific authority.

    Audit-only and validity-invalidated completions remain durable evidence,
    but their claims cannot create axis-level confirmation debt. When every
    disposition-driving completion is non-scientific, preserve its exact claim
    inventory as diagnostic context and return a typed non-identifiable state.
    """

    if not isinstance(values, Sequence) or not values:
        raise EffectiveScientificDiagnosisError(
            "effective scientific diagnosis requires completion evidence"
        )
    adjudications: list[Mapping[str, Any]] = []
    eligible: list[Mapping[str, Any]] = []
    scopes: list[EffectiveCompletionEvidenceScope] = []
    completion_ids: set[str] = set()
    for value in values:
        if type(value) is not tuple or len(value) != 2:
            raise EffectiveScientificDiagnosisError(
                "effective scientific diagnosis entry is malformed"
            )
        adjudication, scope = value
        if not isinstance(adjudication, Mapping) or not isinstance(
            scope, EffectiveCompletionEvidenceScope
        ):
            raise EffectiveScientificDiagnosisError(
                "effective scientific diagnosis entry is untyped"
            )
        if (
            not scope.completion_record_id
            or not scope.completion_record_id.isascii()
            or scope.completion_record_id in completion_ids
            or scope.scientific_credit not in {0, 1}
            or scope.scientific_eligible != bool(scope.scientific_credit)
        ):
            raise EffectiveScientificDiagnosisError(
                "effective scientific diagnosis scope is inconsistent"
            )
        completion_ids.add(scope.completion_record_id)
        adjudications.append(adjudication)
        scopes.append(scope)
        if scope.scientific_eligible:
            eligible.append(adjudication)

    try:
        if eligible:
            return diagnose_scientific_adjudications(tuple(eligible))
        diagnostic = diagnose_scientific_adjudications(tuple(adjudications))
    except ScientificDiagnosisError as exc:
        raise EffectiveScientificDiagnosisError(
            "effective scientific diagnosis evidence is malformed"
        ) from exc

    audit_only = all(
        scope.evidence_modes == ("audit_integrity",)
        and scope.overlay_record_id is not None
        and scope.invalidation_record_id is None
        for scope in scopes
    )
    validity_invalidated = any(
        scope.invalidation_record_id is not None for scope in scopes
    )
    if audit_only:
        reason_code = "audit_only_scope_cannot_create_scientific_confirmation"
        confidence = DiagnosisConfidence.HIGH
    elif validity_invalidated:
        reason_code = "completion_scientific_validity_invalidated"
        confidence = DiagnosisConfidence.HIGH
    else:
        reason_code = "no_scientifically_eligible_completion"
        confidence = DiagnosisConfidence.MEDIUM
    return replace(
        diagnostic,
        evidence_state=EvidenceState.NOT_IDENTIFIABLE,
        confidence=confidence,
        reason_code=reason_code,
        primary_question_recognized=True,
    )


__all__ = [
    "EffectiveScientificDiagnosisError",
    "diagnose_effective_scientific_adjudications",
]
