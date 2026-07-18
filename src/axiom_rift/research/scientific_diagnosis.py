"""Claim-scoped scientific diagnosis without unrelated-claim compensation.

The rich adjudication state intentionally preserves useful partial evidence.
It is not, by itself, an answer to the Portfolio axis' primary causal
question.  In particular, absolute economics cannot compensate for a failed
registered control contrast.  This module keeps those two decisions separate
and projects the narrowest evidence-state diagnosis supported by the opened
claim inventory.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from axiom_rift.research.governance import (
    DiagnosisConfidence,
    EvidenceState,
)


_ADJUDICATION_STATES = frozenset(
    {
        "confirmed",
        "contradicted",
        "frontier",
        "not_evaluable",
        "partial_positive",
        "unresolved",
    }
)
_CLAIM_STATES = frozenset({"contradicted", "supported", "unresolved"})
_CONTROL_CLAIM = "registered_control_contrast"
_SELECTION_CLAIM = "selection_aware_signal_evidence"
_ECONOMICS_CLAIM = "after_cost_fixed_lot_economics"
_STABILITY_CLAIMS = frozenset(
    {
        "activity_and_concentration",
        "temporal_and_regime_stability",
    }
)
_VALIDITY_CLAIMS = frozenset(
    {
        "causal_feature_and_execution_validity",
        "causality_and_execution_validity",
    }
)


class ScientificDiagnosisError(ValueError):
    """Raised when a purported adjudication inventory is malformed."""


@dataclass(frozen=True, slots=True)
class ScientificDiagnosisPattern:
    """One deterministic primary-question diagnosis over exact completions."""

    evidence_state: EvidenceState
    confidence: DiagnosisConfidence
    reason_code: str
    adjudication_states: tuple[str, ...]
    supported_claim_ids: tuple[str, ...]
    contradicted_claim_ids: tuple[str, ...]
    unresolved_claim_ids: tuple[str, ...]
    diagnostic_criterion_ids: tuple[str, ...]
    primary_question_recognized: bool

    def to_payload(self) -> dict[str, Any]:
        """Return the exact claim-scoped decision basis for durable records."""

        return {
            "adjudication_states": list(self.adjudication_states),
            "confidence": self.confidence.value,
            "contradicted_claim_ids": list(self.contradicted_claim_ids),
            "diagnostic_criterion_ids": list(self.diagnostic_criterion_ids),
            "evidence_state": self.evidence_state.value,
            "primary_question_recognized": self.primary_question_recognized,
            "reason_code": self.reason_code,
            "schema": "scientific_diagnosis_pattern.v1",
            "supported_claim_ids": list(self.supported_claim_ids),
            "unresolved_claim_ids": list(self.unresolved_claim_ids),
        }


def _claim_inventory(
    adjudication: Mapping[str, Any],
) -> dict[str, str]:
    if adjudication.get("schema") != "scientific_adjudication.v1":
        raise ScientificDiagnosisError("scientific adjudication schema is invalid")
    state = adjudication.get("state")
    if state not in _ADJUDICATION_STATES:
        raise ScientificDiagnosisError("scientific adjudication state is invalid")
    if type(adjudication.get("evaluable")) is not bool:
        raise ScientificDiagnosisError("scientific adjudication evaluability is invalid")
    raw_claims = adjudication.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise ScientificDiagnosisError("scientific adjudication claims are absent")
    claims: dict[str, str] = {}
    for raw in raw_claims:
        if not isinstance(raw, Mapping):
            raise ScientificDiagnosisError("scientific adjudication claim is malformed")
        claim_id = raw.get("claim_id")
        claim_state = raw.get("state")
        if (
            type(claim_id) is not str
            or not claim_id
            or not claim_id.isascii()
            or claim_state not in _CLAIM_STATES
            or claim_id in claims
        ):
            raise ScientificDiagnosisError("scientific adjudication claim is invalid")
        claims[claim_id] = str(claim_state)
    return claims


def _pattern(
    *,
    evidence_state: EvidenceState,
    confidence: DiagnosisConfidence,
    reason_code: str,
    states: tuple[str, ...],
    matrix: Mapping[str, tuple[str, ...]],
    diagnostic_criterion_ids: tuple[str, ...],
    recognized: bool,
) -> ScientificDiagnosisPattern:
    return ScientificDiagnosisPattern(
        evidence_state=evidence_state,
        confidence=confidence,
        reason_code=reason_code,
        adjudication_states=states,
        supported_claim_ids=tuple(
            sorted(
                claim_id
                for claim_id, values in matrix.items()
                if values and all(value == "supported" for value in values)
            )
        ),
        contradicted_claim_ids=tuple(
            sorted(
                claim_id
                for claim_id, values in matrix.items()
                if any(value == "contradicted" for value in values)
            )
        ),
        unresolved_claim_ids=tuple(
            sorted(
                claim_id
                for claim_id, values in matrix.items()
                if any(value == "unresolved" for value in values)
            )
        ),
        diagnostic_criterion_ids=diagnostic_criterion_ids,
        primary_question_recognized=recognized,
    )


def _diagnostic_criterion_ids(
    adjudications: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Preserve non-dispositive warnings instead of hiding them in one label."""

    identifiers: set[str] = set()
    for adjudication in adjudications:
        raw_criteria = adjudication.get("criteria")
        if not isinstance(raw_criteria, list):
            raise ScientificDiagnosisError("scientific adjudication criteria are invalid")
        for raw in raw_criteria:
            if not isinstance(raw, Mapping):
                raise ScientificDiagnosisError(
                    "scientific adjudication criterion is malformed"
                )
            role = raw.get("decision_role")
            comparison = raw.get("comparison_state")
            if role not in {"diagnostic", "risk_diagnostic"} or comparison != "failed":
                continue
            criterion_id = raw.get("criterion_id")
            if (
                type(criterion_id) is not str
                or not criterion_id
                or not criterion_id.isascii()
            ):
                raise ScientificDiagnosisError(
                    "scientific diagnostic criterion identity is invalid"
                )
            identifiers.add(criterion_id)
    return tuple(sorted(identifiers))


def diagnose_scientific_adjudications(
    adjudications: Sequence[Mapping[str, Any]],
) -> ScientificDiagnosisPattern:
    """Diagnose exact completions by primary claims, never by state alone.

    A uniform failed registered control contrast is direct evidence that the
    changed mechanism did not separate from its causal control.  Supported
    activity, economics, validity, or stability components remain preserved in
    the adjudication, but cannot manufacture axis-level confirmation debt.
    """

    if not isinstance(adjudications, Sequence) or not adjudications:
        raise ScientificDiagnosisError("scientific diagnosis requires adjudications")
    normalized = tuple(adjudications)
    if any(not isinstance(value, Mapping) for value in normalized):
        raise ScientificDiagnosisError("scientific diagnosis input is malformed")
    inventories = tuple(_claim_inventory(value) for value in normalized)
    diagnostic_criterion_ids = _diagnostic_criterion_ids(normalized)
    claim_sets = {frozenset(value) for value in inventories}
    states = tuple(sorted(str(value["state"]) for value in normalized))
    if len(claim_sets) != 1:
        heterogeneous_claim_ids = tuple(
            sorted({claim_id for inventory in inventories for claim_id in inventory})
        )
        heterogeneous_matrix = {
            claim_id: tuple(
                inventory[claim_id]
                for inventory in inventories
                if claim_id in inventory
            )
            for claim_id in heterogeneous_claim_ids
        }
        return _pattern(
            evidence_state=EvidenceState.NOT_IDENTIFIABLE,
            confidence=DiagnosisConfidence.LOW,
            reason_code="claim_inventory_heterogeneous",
            states=states,
            matrix=heterogeneous_matrix,
            diagnostic_criterion_ids=diagnostic_criterion_ids,
            recognized=any(_CONTROL_CLAIM in value for value in inventories),
        )
    claim_ids = tuple(sorted(next(iter(claim_sets))))
    matrix = {
        claim_id: tuple(inventory[claim_id] for inventory in inventories)
        for claim_id in claim_ids
    }
    recognized = _CONTROL_CLAIM in matrix
    if any(value.get("evaluable") is not True for value in normalized) or any(
        state in {"not_evaluable", "unresolved"} for state in states
    ):
        return _pattern(
            evidence_state=EvidenceState.NOT_IDENTIFIABLE,
            confidence=DiagnosisConfidence.LOW,
            reason_code="decisive_evidence_not_evaluable",
            states=states,
            matrix=matrix,
            diagnostic_criterion_ids=diagnostic_criterion_ids,
            recognized=recognized,
        )
    validity_values = tuple(
        value
        for claim_id in _VALIDITY_CLAIMS
        for value in matrix.get(claim_id, ())
    )
    if validity_values and any(value != "supported" for value in validity_values):
        return _pattern(
            evidence_state=EvidenceState.NOT_IDENTIFIABLE,
            confidence=DiagnosisConfidence.HIGH,
            reason_code="causal_validity_not_supported",
            states=states,
            matrix=matrix,
            diagnostic_criterion_ids=diagnostic_criterion_ids,
            recognized=recognized,
        )
    if all(state in {"confirmed", "frontier"} for state in states):
        if any(
            value != "supported"
            for values in matrix.values()
            for value in values
        ):
            return _pattern(
                evidence_state=EvidenceState.NOT_IDENTIFIABLE,
                confidence=DiagnosisConfidence.HIGH,
                reason_code="adjudication_state_claim_inventory_inconsistent",
                states=states,
                matrix=matrix,
                diagnostic_criterion_ids=diagnostic_criterion_ids,
                recognized=recognized,
            )
        return _pattern(
            evidence_state=EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION,
            confidence=DiagnosisConfidence.HIGH,
            reason_code="all_decisive_claims_supported",
            states=states,
            matrix=matrix,
            diagnostic_criterion_ids=diagnostic_criterion_ids,
            recognized=recognized,
        )
    control_values = matrix.get(_CONTROL_CLAIM, ())
    if control_values and all(value == "contradicted" for value in control_values):
        return _pattern(
            evidence_state=EvidenceState.ABSENT_INFORMATION,
            confidence=DiagnosisConfidence.HIGH,
            reason_code="registered_control_contrast_uniformly_contradicted",
            states=states,
            matrix=matrix,
            diagnostic_criterion_ids=diagnostic_criterion_ids,
            recognized=True,
        )
    if control_values and {
        value for value in control_values
    } == {"contradicted", "supported"}:
        return _pattern(
            evidence_state=EvidenceState.STABILITY_CONCENTRATION,
            confidence=DiagnosisConfidence.HIGH,
            reason_code="registered_control_support_member_concentrated",
            states=states,
            matrix=matrix,
            diagnostic_criterion_ids=diagnostic_criterion_ids,
            recognized=True,
        )
    if control_values and any(value == "unresolved" for value in control_values):
        return _pattern(
            evidence_state=EvidenceState.NOT_IDENTIFIABLE,
            confidence=DiagnosisConfidence.MEDIUM,
            reason_code="registered_control_contrast_unresolved",
            states=states,
            matrix=matrix,
            diagnostic_criterion_ids=diagnostic_criterion_ids,
            recognized=True,
        )
    selection_values = matrix.get(_SELECTION_CLAIM, ())
    if selection_values and all(
        value == "contradicted" for value in selection_values
    ):
        return _pattern(
            evidence_state=EvidenceState.CALIBRATION_SELECTION,
            confidence=DiagnosisConfidence.HIGH,
            reason_code="selection_aware_evidence_uniformly_contradicted",
            states=states,
            matrix=matrix,
            diagnostic_criterion_ids=diagnostic_criterion_ids,
            recognized=recognized,
        )
    if selection_values and any(
        value == "contradicted" for value in selection_values
    ):
        return _pattern(
            evidence_state=EvidenceState.STABILITY_CONCENTRATION,
            confidence=DiagnosisConfidence.MEDIUM,
            reason_code="selection_aware_support_member_concentrated",
            states=states,
            matrix=matrix,
            diagnostic_criterion_ids=diagnostic_criterion_ids,
            recognized=recognized,
        )
    economics_values = matrix.get(_ECONOMICS_CLAIM, ())
    if economics_values and all(
        value == "contradicted" for value in economics_values
    ):
        return _pattern(
            evidence_state=EvidenceState.EXECUTION_COST,
            confidence=DiagnosisConfidence.MEDIUM,
            reason_code="after_cost_economics_uniformly_contradicted",
            states=states,
            matrix=matrix,
            diagnostic_criterion_ids=diagnostic_criterion_ids,
            recognized=recognized,
        )
    if any(
        value == "contradicted"
        for claim_id in _STABILITY_CLAIMS
        for value in matrix.get(claim_id, ())
    ):
        return _pattern(
            evidence_state=EvidenceState.STABILITY_CONCENTRATION,
            confidence=DiagnosisConfidence.MEDIUM,
            reason_code="activity_or_temporal_support_concentrated",
            states=states,
            matrix=matrix,
            diagnostic_criterion_ids=diagnostic_criterion_ids,
            recognized=recognized,
        )
    return _pattern(
        evidence_state=EvidenceState.NOT_IDENTIFIABLE,
        confidence=DiagnosisConfidence.MEDIUM,
        reason_code="partial_evidence_does_not_identify_bottleneck",
        states=states,
        matrix=matrix,
        diagnostic_criterion_ids=diagnostic_criterion_ids,
        recognized=recognized,
    )


__all__ = [
    "ScientificDiagnosisError",
    "ScientificDiagnosisPattern",
    "diagnose_scientific_adjudications",
]
