"""Typed additive correction of historical completion evidence scope."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from axiom_rift.core.identity import canonical_digest


class EvidenceScopeError(ValueError):
    """Historical evidence scope is malformed or grants forbidden credit."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise EvidenceScopeError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise EvidenceScopeError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _identities(name: str, value: object, prefix: str) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise EvidenceScopeError(f"{name} must be a non-empty tuple")
    normalized = tuple(sorted(_ascii(name, item) for item in value))
    if len(normalized) != len(set(normalized)):
        raise EvidenceScopeError(f"{name} must be unique")
    for item in normalized:
        digest = item.removeprefix(prefix)
        if item == digest:
            raise EvidenceScopeError(f"{name} must use {prefix}<sha256>")
        _digest(name, digest)
    return normalized


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalEvidenceScopeOverlay:
    """Remove scientific/economic/terminal credit without rewriting evidence."""

    completion_record_id: str
    governing_mission_id: str
    replay_study_id: str
    replay_obligation_ids: tuple[str, ...]
    replay_resolution_ids: tuple[str, ...]
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _digest("completion record id", self.completion_record_id)
        _ascii("governing Mission id", self.governing_mission_id)
        _ascii("replay Study id", self.replay_study_id)
        obligations = _identities(
            "replay obligation ids",
            self.replay_obligation_ids,
            "historical-replay-obligation:",
        )
        resolutions = _identities(
            "replay resolution ids",
            self.replay_resolution_ids,
            "historical-replay-satisfaction:",
        )
        if len(obligations) != len(resolutions):
            raise EvidenceScopeError(
                "evidence scope must bind one resolution per obligation"
            )
        object.__setattr__(self, "replay_obligation_ids", obligations)
        object.__setattr__(self, "replay_resolution_ids", resolutions)
        object.__setattr__(
            self,
            "identity",
            "historical-evidence-scope:"
            + canonical_digest(
                domain="historical-evidence-scope",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "candidate_eligible": False,
            "completion_record_id": self.completion_record_id,
            "credit": {
                "candidate": 0,
                "economic": 0,
                "scientific": 0,
                "terminal": 0,
            },
            "effective_evidence_modes": ["audit_integrity"],
            "governing_mission_id": self.governing_mission_id,
            "reason": "post_selection_descriptive_audit_only",
            "replay_obligation_ids": list(self.replay_obligation_ids),
            "replay_resolution_ids": list(self.replay_resolution_ids),
            "replay_study_id": self.replay_study_id,
            "schema": "historical_evidence_scope_overlay.v1",
            "scientific_eligible": False,
        }


def historical_evidence_scope_from_payload(
    value: Mapping[str, Any],
) -> HistoricalEvidenceScopeOverlay:
    expected = {
        "candidate_eligible",
        "completion_record_id",
        "credit",
        "effective_evidence_modes",
        "governing_mission_id",
        "reason",
        "replay_obligation_ids",
        "replay_resolution_ids",
        "replay_study_id",
        "schema",
        "scientific_eligible",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != expected
        or value.get("schema") != "historical_evidence_scope_overlay.v1"
        or value.get("candidate_eligible") is not False
        or value.get("scientific_eligible") is not False
        or value.get("effective_evidence_modes") != ["audit_integrity"]
        or value.get("reason") != "post_selection_descriptive_audit_only"
        or value.get("credit")
        != {"candidate": 0, "economic": 0, "scientific": 0, "terminal": 0}
    ):
        raise EvidenceScopeError("historical evidence scope payload is malformed")
    try:
        overlay = HistoricalEvidenceScopeOverlay(
            completion_record_id=value["completion_record_id"],
            governing_mission_id=value["governing_mission_id"],
            replay_study_id=value["replay_study_id"],
            replay_obligation_ids=tuple(value["replay_obligation_ids"]),
            replay_resolution_ids=tuple(value["replay_resolution_ids"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidenceScopeError(
            "historical evidence scope cannot be rebuilt"
        ) from exc
    if overlay.to_identity_payload() != dict(value):
        raise EvidenceScopeError("historical evidence scope changed on rebuild")
    return overlay


__all__ = [
    "EvidenceScopeError",
    "HistoricalEvidenceScopeOverlay",
    "historical_evidence_scope_from_payload",
]
