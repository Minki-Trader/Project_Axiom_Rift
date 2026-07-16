"""Additive correction records for legacy scientific evidence.

Historical adjudication never rewrites a Study close, Job completion, trial,
or negative-memory record.  It binds an exact legacy completion and its
evidence artifacts to a component-aware interpretation, then states the
smallest honest follow-up.  Missing raw uncertainty evidence therefore opens a
bounded replay; it never manufactures a historical pass or candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.adjudication import (
    AdjudicationProfile,
    ScientificAdjudication,
    adjudicate_plan_measurement,
)


class HistoricalAdjudicationError(ValueError):
    """Raised when a corrective interpretation is not tightly evidence-bound."""


class ReplayPriority(str, Enum):
    NONE = "none"
    P0 = "p0"
    P1 = "p1"


class HistoricalDisposition(str, Enum):
    """Allowed additive outcomes; none of them grants candidate authority."""

    CLAIM_SCOPED_QUALIFICATION = "claim_scoped_qualification"
    EXACT_SURFACE_PRUNE_RETAINED = "exact_surface_prune_retained"
    INVENTORY_PARTIAL_POSITIVE = "inventory_partial_positive"
    NOT_EVALUABLE_QUALIFICATION = "not_evaluable_qualification"
    REPLAY_REQUIRED = "replay_required"


class HistoricalValidityReason(str, Enum):
    """External audit facts that remove historical claim evaluability."""

    DECISION_INPUT_POINT_IN_TIME_UNPROVEN = (
        "decision_input_point_in_time_unproven"
    )
    SOURCE_AUTHORITY_INVALIDATED = "source_authority_invalidated"


_DISPOSITIONS_BY_STATE = {
    "not_evaluable": frozenset(
        {
            HistoricalDisposition.CLAIM_SCOPED_QUALIFICATION,
            HistoricalDisposition.NOT_EVALUABLE_QUALIFICATION,
            HistoricalDisposition.REPLAY_REQUIRED,
        }
    ),
    "contradicted": frozenset(
        {
            HistoricalDisposition.CLAIM_SCOPED_QUALIFICATION,
            HistoricalDisposition.EXACT_SURFACE_PRUNE_RETAINED,
            HistoricalDisposition.REPLAY_REQUIRED,
        }
    ),
    "unresolved": frozenset(
        {
            HistoricalDisposition.CLAIM_SCOPED_QUALIFICATION,
            HistoricalDisposition.EXACT_SURFACE_PRUNE_RETAINED,
            HistoricalDisposition.INVENTORY_PARTIAL_POSITIVE,
            HistoricalDisposition.REPLAY_REQUIRED,
        }
    ),
    "partial_positive": frozenset(
        {
            HistoricalDisposition.CLAIM_SCOPED_QUALIFICATION,
            HistoricalDisposition.EXACT_SURFACE_PRUNE_RETAINED,
            HistoricalDisposition.INVENTORY_PARTIAL_POSITIVE,
            HistoricalDisposition.REPLAY_REQUIRED,
        }
    ),
    "frontier": frozenset(
        {
            HistoricalDisposition.CLAIM_SCOPED_QUALIFICATION,
            HistoricalDisposition.INVENTORY_PARTIAL_POSITIVE,
            HistoricalDisposition.REPLAY_REQUIRED,
        }
    ),
    "confirmed": frozenset(
        {
            HistoricalDisposition.CLAIM_SCOPED_QUALIFICATION,
            HistoricalDisposition.INVENTORY_PARTIAL_POSITIVE,
            HistoricalDisposition.REPLAY_REQUIRED,
        }
    ),
}


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise HistoricalAdjudicationError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise HistoricalAdjudicationError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    digest = text.removeprefix(prefix)
    if text == digest or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise HistoricalAdjudicationError(f"{name} must use {prefix}<sha256>")
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalValidityOverride:
    """One exact invalidated dependency and its durable correction record."""

    reason: HistoricalValidityReason
    subject_id: str
    evidence_record_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, HistoricalValidityReason):
            raise HistoricalAdjudicationError("validity override reason is not typed")
        if self.reason is HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED:
            _identity("validity override subject_id", self.subject_id, "source:")
            _identity(
                "validity override evidence_record_id",
                self.evidence_record_id,
                "source-authority-invalidation:",
            )
        elif (
            self.reason
            is HistoricalValidityReason.DECISION_INPUT_POINT_IN_TIME_UNPROVEN
        ):
            _digest("validity override subject_id", self.subject_id)
            _identity(
                "validity override evidence_record_id",
                self.evidence_record_id,
                "historical-scientific-validity-invalidation:",
            )
        else:  # pragma: no cover - defensive against future unhandled reasons.
            raise HistoricalAdjudicationError(
                "validity override reason has no subject binding"
            )

    def manifest(self) -> dict[str, str]:
        return {
            "evidence_record_id": self.evidence_record_id,
            "reason": self.reason.value,
            "subject_id": self.subject_id,
        }


def profile_manifest(profile: AdjudicationProfile) -> dict[str, Any]:
    """Return the exact prospective policy used for one legacy interpretation."""

    if not isinstance(profile, AdjudicationProfile):
        raise HistoricalAdjudicationError("profile must be an AdjudicationProfile")
    return {
        "decisive_risk_criterion_ids": sorted(profile.decisive_risk_criterion_ids),
        "multiplicity": [
            item.manifest()
            for item in sorted(
                profile.multiplicity,
                key=lambda value: (value.criterion_id, value.family_id),
            )
        ],
        "schema": "scientific_adjudication_profile.v1",
    }


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalAdjudicationRequest:
    """A proposal whose legacy interpretation is recomputed by the Writer.

    ``profile`` and ``validity_overrides`` are descriptive request fields, not
    capabilities.  The Writer accepts them only when they exactly match the
    fixed legacy profile and the monotone durable dependency facts.
    """

    completion_record_id: str
    disposition: HistoricalDisposition
    replay_priority: ReplayPriority
    reason_codes: tuple[str, ...]
    validity_overrides: tuple[HistoricalValidityOverride, ...] = ()
    profile: AdjudicationProfile = field(default_factory=AdjudicationProfile)

    def __post_init__(self) -> None:
        _digest("completion_record_id", self.completion_record_id)
        if not isinstance(self.disposition, HistoricalDisposition):
            raise HistoricalAdjudicationError("disposition is not typed")
        if not isinstance(self.replay_priority, ReplayPriority):
            raise HistoricalAdjudicationError("replay priority is not typed")
        if not isinstance(self.profile, AdjudicationProfile):
            raise HistoricalAdjudicationError("profile is not typed")
        if type(self.validity_overrides) is not tuple or any(
            not isinstance(item, HistoricalValidityOverride)
            for item in self.validity_overrides
        ):
            raise HistoricalAdjudicationError(
                "validity overrides must be a tuple of typed values"
            )
        normalized_overrides = tuple(
            sorted(
                self.validity_overrides,
                key=lambda item: (
                    item.reason.value,
                    item.subject_id,
                    item.evidence_record_id,
                ),
            )
        )
        if len({item.subject_id for item in normalized_overrides}) != len(
            normalized_overrides
        ):
            raise HistoricalAdjudicationError(
                "validity override subjects must be unique"
            )
        normalized = tuple(sorted(_ascii("reason code", item) for item in self.reason_codes))
        if not normalized or len(normalized) != len(set(normalized)):
            raise HistoricalAdjudicationError("reason codes must be unique and non-empty")
        if (
            self.disposition is HistoricalDisposition.REPLAY_REQUIRED
        ) != (self.replay_priority is not ReplayPriority.NONE):
            raise HistoricalAdjudicationError(
                "only replay_required may carry a non-none replay priority"
            )
        object.__setattr__(self, "reason_codes", normalized)
        object.__setattr__(self, "validity_overrides", normalized_overrides)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalScientificAdjudication:
    """One immutable additive overlay over an exact legacy completion."""

    audit_artifact_hash: str
    study_id: str
    study_close_record_id: str
    completion_record_id: str
    executable_id: str
    validation_plan_hash: str
    measurement_artifact_hash: str
    original_job_status: str
    original_scientific_verdict: str
    disposition: HistoricalDisposition
    replay_priority: ReplayPriority
    reason_codes: tuple[str, ...]
    profile: AdjudicationProfile
    adjudication: ScientificAdjudication
    validity_overrides: tuple[HistoricalValidityOverride, ...] = ()
    negative_memory_ids: tuple[str, ...] = ()
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _digest("audit_artifact_hash", self.audit_artifact_hash)
        _ascii("study_id", self.study_id)
        _digest("study_close_record_id", self.study_close_record_id)
        _digest("completion_record_id", self.completion_record_id)
        _identity("executable_id", self.executable_id, "executable:")
        _digest("validation_plan_hash", self.validation_plan_hash)
        _digest("measurement_artifact_hash", self.measurement_artifact_hash)
        if self.original_job_status not in {"failed", "not_evaluable", "success"}:
            raise HistoricalAdjudicationError("legacy Job status is invalid")
        if self.original_scientific_verdict not in {
            "failed",
            "not_evaluable",
            "passed",
        }:
            raise HistoricalAdjudicationError("legacy scientific verdict is invalid")
        if not isinstance(self.disposition, HistoricalDisposition):
            raise HistoricalAdjudicationError("disposition is not typed")
        if not isinstance(self.replay_priority, ReplayPriority):
            raise HistoricalAdjudicationError("replay priority is not typed")
        if not isinstance(self.profile, AdjudicationProfile):
            raise HistoricalAdjudicationError("profile is not typed")
        if not isinstance(self.adjudication, ScientificAdjudication):
            raise HistoricalAdjudicationError("scientific adjudication is not typed")
        if type(self.validity_overrides) is not tuple or any(
            not isinstance(item, HistoricalValidityOverride)
            for item in self.validity_overrides
        ):
            raise HistoricalAdjudicationError(
                "validity overrides must be a tuple of typed values"
            )
        overrides = tuple(
            sorted(
                self.validity_overrides,
                key=lambda item: (
                    item.reason.value,
                    item.subject_id,
                    item.evidence_record_id,
                ),
            )
        )
        if len({item.subject_id for item in overrides}) != len(overrides):
            raise HistoricalAdjudicationError(
                "validity override subjects must be unique"
            )
        if self.adjudication.candidate_eligible:
            raise HistoricalAdjudicationError(
                "historical adjudication cannot create candidate authority"
            )
        allowed = _DISPOSITIONS_BY_STATE[self.effective_state]
        if self.disposition not in allowed:
            raise HistoricalAdjudicationError(
                "disposition conflicts with the component-aware state"
            )
        if (
            self.disposition is HistoricalDisposition.REPLAY_REQUIRED
        ) != (self.replay_priority is not ReplayPriority.NONE):
            raise HistoricalAdjudicationError(
                "replay disposition and priority conflict"
            )
        reasons = tuple(sorted(_ascii("reason code", item) for item in self.reason_codes))
        if not reasons or len(reasons) != len(set(reasons)):
            raise HistoricalAdjudicationError("reason codes must be unique and non-empty")
        memories = tuple(sorted(self.negative_memory_ids))
        if len(memories) != len(set(memories)):
            raise HistoricalAdjudicationError("negative-memory identities must be unique")
        for memory_id in memories:
            _identity("negative_memory_id", memory_id, "negative-memory:")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "negative_memory_ids", memories)
        object.__setattr__(self, "validity_overrides", overrides)
        object.__setattr__(
            self,
            "identity",
            "historical-adjudication:"
            + canonical_digest(
                domain="historical-scientific-adjudication",
                payload=self.to_identity_payload(),
            ),
        )

    @property
    def effective_state(self) -> str:
        return "not_evaluable" if self.validity_overrides else self.adjudication.state

    def to_identity_payload(self) -> dict[str, Any]:
        claims = [
            {
                "claim_id": item.claim_id,
                "decisive_criterion_ids": list(item.decisive_criterion_ids),
                "state": item.state,
            }
            for item in self.adjudication.claims
        ]
        criteria = [
            {
                "claim_id": item.claim_id,
                "criterion_id": item.criterion_id,
                "decision_role": item.decision_role,
                "metric": item.metric,
                "operator": item.operator,
                "state": item.state,
                "threshold": item.threshold,
                "value": item.value,
            }
            for item in self.adjudication.criteria
        ]
        return {
            "adjudication": {
                "candidate_eligible": False,
                "claims": claims,
                "criteria": criteria,
                "evaluable": self.adjudication.evaluable,
                "evidence_depth": self.adjudication.evidence_depth,
                "invalid_metrics": list(self.adjudication.invalid_metrics),
                "legacy_verdict": self.adjudication.legacy_verdict,
                "multiplicity": [
                    item.manifest()
                    for item in sorted(
                        self.adjudication.multiplicity,
                        key=lambda value: (value.criterion_id, value.family_id),
                    )
                ],
                "state": self.adjudication.state,
            },
            "audit_artifact_hash": self.audit_artifact_hash,
            "completion_record_id": self.completion_record_id,
            "disposition": self.disposition.value,
            "executable_id": self.executable_id,
            "effective_state": self.effective_state,
            "measurement_artifact_hash": self.measurement_artifact_hash,
            "negative_memory_ids": list(self.negative_memory_ids),
            "original_job_status": self.original_job_status,
            "original_scientific_verdict": self.original_scientific_verdict,
            "profile": profile_manifest(self.profile),
            "reason_codes": list(self.reason_codes),
            "replay_priority": self.replay_priority.value,
            "schema": "historical_scientific_adjudication.v2",
            "study_close_record_id": self.study_close_record_id,
            "study_id": self.study_id,
            "validation_plan_hash": self.validation_plan_hash,
            "validity_overrides": [
                item.manifest() for item in self.validity_overrides
            ],
        }


def derive_historical_adjudication(
    *,
    audit_artifact_hash: str,
    study_id: str,
    study_close_record_id: str,
    completion_record_id: str,
    executable_id: str,
    validation_plan_hash: str,
    measurement_artifact_hash: str,
    original_job_status: str,
    original_scientific_verdict: str,
    plan: Mapping[str, Any],
    measurement: Mapping[str, Any],
    request: HistoricalAdjudicationRequest,
    negative_memory_ids: tuple[str, ...] = (),
) -> HistoricalScientificAdjudication:
    """Derive, rather than accept, the corrected interpretation."""

    if completion_record_id != request.completion_record_id:
        raise HistoricalAdjudicationError("request targets another completion")
    adjudication = adjudicate_plan_measurement(
        plan,
        measurement,
        profile=request.profile,
    )
    return HistoricalScientificAdjudication(
        audit_artifact_hash=audit_artifact_hash,
        study_id=study_id,
        study_close_record_id=study_close_record_id,
        completion_record_id=completion_record_id,
        executable_id=executable_id,
        validation_plan_hash=validation_plan_hash,
        measurement_artifact_hash=measurement_artifact_hash,
        original_job_status=original_job_status,
        original_scientific_verdict=original_scientific_verdict,
        disposition=request.disposition,
        replay_priority=request.replay_priority,
        reason_codes=request.reason_codes,
        profile=request.profile,
        adjudication=adjudication,
        validity_overrides=request.validity_overrides,
        negative_memory_ids=negative_memory_ids,
    )


__all__ = [
    "HistoricalAdjudicationError",
    "HistoricalAdjudicationRequest",
    "HistoricalDisposition",
    "HistoricalScientificAdjudication",
    "HistoricalValidityOverride",
    "HistoricalValidityReason",
    "ReplayPriority",
    "derive_historical_adjudication",
    "profile_manifest",
]
