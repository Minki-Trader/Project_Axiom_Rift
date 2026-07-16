"""Typed, append-only obligations for bounded historical scientific replay.

Historical adjudication can discover that an old conclusion needs new
measurement.  An adjudication record alone is not schedulable, however: it
does not say whether the replay is pending, running, satisfied, or explicitly
deferred.  This module derives one immutable obligation from that authority
and defines the exact bindings accepted when the obligation changes state.

The types are deliberately pure.  They neither inspect nor mutate control
state; :class:`axiom_rift.operations.writer.StateWriter` remains the only
canonical writer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.historical_adjudication import ReplayPriority


class ReplayObligationError(ValueError):
    """Raised when replay authority or a state binding is not exact."""


class ReplayObligationStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SATISFIED = "satisfied"
    DEFERRED = "deferred"


class ReplayResolutionScope(str, Enum):
    """Scientific reach of the replay that satisfied an obligation."""

    AUDIT_ONLY = "audit_only"
    SCIENTIFIC = "scientific"


class ReplayDeferralBasisKind(str, Enum):
    """Finite durable authorities that may explain a replay deferral."""

    STUDY_DIAGNOSIS = "study_diagnosis"
    SOURCE_AUTHORITY_INVALIDATION = "source_authority_invalidation"
    EXTERNAL_BLOCKER = "external_blocker"
    ARCHITECTURE_REVIEW = "architecture_review"


class ReplayResumeConditionKind(str, Enum):
    """Finite state changes that may requeue, but never satisfy, replay."""

    REGISTERED_DEVELOPMENT_MATERIAL = "registered_development_material"
    SAME_PROTOCOL_REPAIR = "same_protocol_repair"
    REPLACEMENT_SOURCE_CONTRACT = "replacement_source_contract"
    EXTERNAL_DEPENDENCY_AVAILABLE = "external_dependency_available"


class ReplayRepairBasisKind(str, Enum):
    """Exact defect class repaired without changing replay science."""

    OPERATIONAL_FAILURE = "operational_failure"
    SCIENTIFIC_INVALIDITY = "scientific_invalidity"


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ReplayObligationError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ReplayObligationError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    suffix = text.removeprefix(prefix)
    if text == suffix or len(suffix) != 64 or any(
        char not in "0123456789abcdef" for char in suffix
    ):
        raise ReplayObligationError(f"{name} must use {prefix}<sha256>")
    return text


def _sorted_unique_ascii(name: str, values: object, *, nonempty: bool) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise ReplayObligationError(f"{name} must be a tuple")
    normalized = tuple(sorted(_ascii(name, item) for item in values))
    if (nonempty and not normalized) or len(normalized) != len(set(normalized)):
        raise ReplayObligationError(f"{name} must be unique and non-empty")
    return normalized


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalReplayObligation:
    """One immutable replay requirement derived from one adjudication."""

    governing_mission_id: str
    historical_adjudication_id: str
    replay_priority: ReplayPriority
    original_study_id: str
    original_study_close_record_id: str
    original_completion_record_id: str
    original_executable_id: str
    audit_artifact_hash: str
    validation_plan_hash: str
    measurement_artifact_hash: str
    claim_ids: tuple[str, ...]
    criterion_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("governing Mission id", self.governing_mission_id)
        _identity(
            "historical adjudication id",
            self.historical_adjudication_id,
            "historical-adjudication:",
        )
        if self.replay_priority not in {ReplayPriority.P0, ReplayPriority.P1}:
            raise ReplayObligationError("replay obligation priority must be p0 or p1")
        _ascii("original Study id", self.original_study_id)
        _digest("original Study close record", self.original_study_close_record_id)
        _digest("original completion record", self.original_completion_record_id)
        _identity("original Executable id", self.original_executable_id, "executable:")
        _digest("audit artifact", self.audit_artifact_hash)
        _digest("validation plan", self.validation_plan_hash)
        _digest("measurement artifact", self.measurement_artifact_hash)
        claims = _sorted_unique_ascii("claim ids", self.claim_ids, nonempty=True)
        criteria = _sorted_unique_ascii(
            "criterion ids", self.criterion_ids, nonempty=True
        )
        reasons = _sorted_unique_ascii(
            "replay reason codes", self.reason_codes, nonempty=True
        )
        object.__setattr__(self, "claim_ids", claims)
        object.__setattr__(self, "criterion_ids", criteria)
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(
            self,
            "identity",
            "historical-replay-obligation:"
            + canonical_digest(
                domain="historical-replay-obligation",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "audit_artifact_hash": self.audit_artifact_hash,
            "claim_ids": list(self.claim_ids),
            "criterion_ids": list(self.criterion_ids),
            "governing_mission_id": self.governing_mission_id,
            "historical_adjudication_id": self.historical_adjudication_id,
            "measurement_artifact_hash": self.measurement_artifact_hash,
            "original_completion_record_id": self.original_completion_record_id,
            "original_executable_id": self.original_executable_id,
            "original_study_close_record_id": self.original_study_close_record_id,
            "original_study_id": self.original_study_id,
            "reason_codes": list(self.reason_codes),
            "replay_priority": self.replay_priority.value,
            "schema": "historical_replay_obligation.v1",
            "validation_plan_hash": self.validation_plan_hash,
        }


def derive_historical_replay_obligation(
    *,
    governing_mission_id: str,
    historical_adjudication_id: str,
    adjudication_payload: Mapping[str, Any],
) -> HistoricalReplayObligation:
    """Derive a replay obligation from exact durable adjudication authority."""

    if not isinstance(adjudication_payload, Mapping):
        raise ReplayObligationError("historical adjudication payload is absent")
    adjudication = adjudication_payload.get("adjudication")
    if (
        adjudication_payload.get("schema") != "historical_scientific_adjudication.v2"
        or adjudication_payload.get("disposition") != "replay_required"
        or adjudication_payload.get("replay_priority") not in {"p0", "p1"}
        or not isinstance(adjudication, Mapping)
        or adjudication.get("candidate_eligible") is not False
        or not isinstance(adjudication.get("claims"), list)
        or not isinstance(adjudication.get("criteria"), list)
    ):
        raise ReplayObligationError(
            "historical adjudication does not grant replay-obligation authority"
        )
    try:
        claim_ids = tuple(item["claim_id"] for item in adjudication["claims"])
        criterion_ids = tuple(item["criterion_id"] for item in adjudication["criteria"])
        obligation = HistoricalReplayObligation(
            governing_mission_id=governing_mission_id,
            historical_adjudication_id=historical_adjudication_id,
            replay_priority=ReplayPriority(adjudication_payload["replay_priority"]),
            original_study_id=adjudication_payload["study_id"],
            original_study_close_record_id=adjudication_payload[
                "study_close_record_id"
            ],
            original_completion_record_id=adjudication_payload[
                "completion_record_id"
            ],
            original_executable_id=adjudication_payload["executable_id"],
            audit_artifact_hash=adjudication_payload["audit_artifact_hash"],
            validation_plan_hash=adjudication_payload["validation_plan_hash"],
            measurement_artifact_hash=adjudication_payload[
                "measurement_artifact_hash"
            ],
            claim_ids=claim_ids,
            criterion_ids=criterion_ids,
            reason_codes=tuple(adjudication_payload["reason_codes"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayObligationError(
            "historical adjudication cannot be bound as a replay obligation"
        ) from exc
    return obligation


def historical_replay_obligation_from_identity_payload(
    value: Mapping[str, Any],
) -> HistoricalReplayObligation:
    """Rehydrate and byte-check one durable obligation identity payload."""

    expected = {
        "audit_artifact_hash",
        "claim_ids",
        "criterion_ids",
        "governing_mission_id",
        "historical_adjudication_id",
        "measurement_artifact_hash",
        "original_completion_record_id",
        "original_executable_id",
        "original_study_close_record_id",
        "original_study_id",
        "reason_codes",
        "replay_priority",
        "schema",
        "validation_plan_hash",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != expected
        or value.get("schema") != "historical_replay_obligation.v1"
    ):
        raise ReplayObligationError("historical replay obligation payload is malformed")
    try:
        obligation = HistoricalReplayObligation(
            governing_mission_id=value["governing_mission_id"],
            historical_adjudication_id=value["historical_adjudication_id"],
            replay_priority=ReplayPriority(value["replay_priority"]),
            original_study_id=value["original_study_id"],
            original_study_close_record_id=value["original_study_close_record_id"],
            original_completion_record_id=value["original_completion_record_id"],
            original_executable_id=value["original_executable_id"],
            audit_artifact_hash=value["audit_artifact_hash"],
            validation_plan_hash=value["validation_plan_hash"],
            measurement_artifact_hash=value["measurement_artifact_hash"],
            claim_ids=tuple(value["claim_ids"]),
            criterion_ids=tuple(value["criterion_ids"]),
            reason_codes=tuple(value["reason_codes"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayObligationError(
            "historical replay obligation cannot be rebuilt"
        ) from exc
    if obligation.to_identity_payload() != dict(value):
        raise ReplayObligationError(
            "historical replay obligation payload changed on rebuild"
        )
    return obligation


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayPriorityEscalation:
    """Additive P1-to-P0 authority over one immutable replay obligation.

    The original obligation and its identity never change.  This record is
    intentionally one-way: an audit may escalate urgent corrected work, but
    it cannot demote an existing P0 duty or rewrite historical lineage.
    """

    governing_mission_id: str
    obligation_id: str
    superseding_historical_adjudication_id: str
    completion_validity_invalidation_id: str
    accepted_satisfaction_record_id: str
    audit_artifact_hash: str
    reason_codes: tuple[str, ...]
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("governing Mission id", self.governing_mission_id)
        _identity(
            "replay obligation id",
            self.obligation_id,
            "historical-replay-obligation:",
        )
        _identity(
            "superseding historical adjudication id",
            self.superseding_historical_adjudication_id,
            "historical-adjudication:",
        )
        _identity(
            "completion validity invalidation id",
            self.completion_validity_invalidation_id,
            "historical-scientific-validity-invalidation:",
        )
        _identity(
            "accepted replay satisfaction id",
            self.accepted_satisfaction_record_id,
            "historical-replay-satisfaction:",
        )
        _digest("priority escalation audit artifact", self.audit_artifact_hash)
        reasons = _sorted_unique_ascii(
            "priority escalation reason codes",
            self.reason_codes,
            nonempty=True,
        )
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(
            self,
            "identity",
            "historical-replay-priority-escalation:"
            + canonical_digest(
                domain="historical-replay-priority-escalation",
                payload=self.to_identity_payload(),
            ),
        )

    @property
    def prior_priority(self) -> ReplayPriority:
        return ReplayPriority.P1

    @property
    def effective_priority(self) -> ReplayPriority:
        return ReplayPriority.P0

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "accepted_satisfaction_record_id": (
                self.accepted_satisfaction_record_id
            ),
            "audit_artifact_hash": self.audit_artifact_hash,
            "completion_validity_invalidation_id": (
                self.completion_validity_invalidation_id
            ),
            "effective_priority": ReplayPriority.P0.value,
            "governing_mission_id": self.governing_mission_id,
            "obligation_id": self.obligation_id,
            "prior_priority": ReplayPriority.P1.value,
            "reason_codes": list(self.reason_codes),
            "schema": "historical_replay_priority_escalation.v1",
            "superseding_historical_adjudication_id": (
                self.superseding_historical_adjudication_id
            ),
        }


def replay_priority_escalation_from_identity_payload(
    value: Mapping[str, Any],
) -> ReplayPriorityEscalation:
    """Rehydrate an exact one-way replay priority escalation."""

    expected = {
        "accepted_satisfaction_record_id",
        "audit_artifact_hash",
        "completion_validity_invalidation_id",
        "effective_priority",
        "governing_mission_id",
        "obligation_id",
        "prior_priority",
        "reason_codes",
        "schema",
        "superseding_historical_adjudication_id",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != expected
        or value.get("schema")
        != "historical_replay_priority_escalation.v1"
        or value.get("prior_priority") != ReplayPriority.P1.value
        or value.get("effective_priority") != ReplayPriority.P0.value
    ):
        raise ReplayObligationError(
            "historical replay priority escalation payload is malformed"
        )
    try:
        escalation = ReplayPriorityEscalation(
            governing_mission_id=value["governing_mission_id"],
            obligation_id=value["obligation_id"],
            superseding_historical_adjudication_id=value[
                "superseding_historical_adjudication_id"
            ],
            completion_validity_invalidation_id=value[
                "completion_validity_invalidation_id"
            ],
            accepted_satisfaction_record_id=value[
                "accepted_satisfaction_record_id"
            ],
            audit_artifact_hash=value["audit_artifact_hash"],
            reason_codes=tuple(value["reason_codes"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayObligationError(
            "historical replay priority escalation cannot be rebuilt"
        ) from exc
    if escalation.to_identity_payload() != dict(value):
        raise ReplayObligationError(
            "historical replay priority escalation changed on rebuild"
        )
    return escalation


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayExecutionBinding:
    """Exact prospective Decision and Study selected to execute obligations."""

    obligation_ids: tuple[str, ...]
    portfolio_decision_id: str
    replay_study_id: str
    replay_executable_id: str
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        obligations = _sorted_unique_ascii(
            "replay obligation ids", self.obligation_ids, nonempty=True
        )
        for obligation_id in obligations:
            _identity(
                "replay obligation id",
                obligation_id,
                "historical-replay-obligation:",
            )
        _identity("Portfolio Decision id", self.portfolio_decision_id, "decision:")
        _ascii("replay Study id", self.replay_study_id)
        _identity("replay Executable id", self.replay_executable_id, "executable:")
        object.__setattr__(self, "obligation_ids", obligations)
        object.__setattr__(
            self,
            "identity",
            "replay-execution-binding:"
            + canonical_digest(
                domain="replay-execution-binding",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "obligation_ids": list(self.obligation_ids),
            "portfolio_decision_id": self.portfolio_decision_id,
            "replay_executable_id": self.replay_executable_id,
            "replay_study_id": self.replay_study_id,
            "schema": "replay_execution_binding.v1",
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplaySatisfaction:
    """Evidence-bound satisfaction of one replay obligation."""

    obligation_id: str
    resolution_scope: ReplayResolutionScope
    portfolio_decision_id: str
    replay_study_id: str
    replay_executable_id: str
    replay_study_close_record_id: str
    study_diagnosis_id: str
    satisfied_criterion_ids: tuple[str, ...]
    evidence_record_ids: tuple[str, ...]
    remaining_scientific_condition: str | None = None
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _identity(
            "replay obligation id",
            self.obligation_id,
            "historical-replay-obligation:",
        )
        if not isinstance(self.resolution_scope, ReplayResolutionScope):
            raise ReplayObligationError("replay resolution scope is not typed")
        _identity("Portfolio Decision id", self.portfolio_decision_id, "decision:")
        _ascii("replay Study id", self.replay_study_id)
        _identity("replay Executable id", self.replay_executable_id, "executable:")
        _digest("replay Study close record", self.replay_study_close_record_id)
        _identity("Study diagnosis id", self.study_diagnosis_id, "diagnosis:")
        criteria = _sorted_unique_ascii(
            "satisfied criterion ids", self.satisfied_criterion_ids, nonempty=True
        )
        evidence = _sorted_unique_ascii(
            "replay evidence record ids", self.evidence_record_ids, nonempty=True
        )
        remaining = self.remaining_scientific_condition
        if self.resolution_scope is ReplayResolutionScope.AUDIT_ONLY:
            _ascii("remaining scientific condition", remaining)
        elif remaining is not None:
            raise ReplayObligationError(
                "scientific satisfaction cannot retain an unresolved condition"
            )
        object.__setattr__(self, "satisfied_criterion_ids", criteria)
        object.__setattr__(self, "evidence_record_ids", evidence)
        object.__setattr__(
            self,
            "identity",
            "historical-replay-satisfaction:"
            + canonical_digest(
                domain="historical-replay-satisfaction",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "evidence_record_ids": list(self.evidence_record_ids),
            "obligation_id": self.obligation_id,
            "portfolio_decision_id": self.portfolio_decision_id,
            "remaining_scientific_condition": self.remaining_scientific_condition,
            "replay_executable_id": self.replay_executable_id,
            "replay_study_close_record_id": self.replay_study_close_record_id,
            "replay_study_id": self.replay_study_id,
            "resolution_scope": self.resolution_scope.value,
            "satisfied_criterion_ids": list(self.satisfied_criterion_ids),
            "schema": "historical_replay_satisfaction.v1",
            "study_diagnosis_id": self.study_diagnosis_id,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayDeferralBasis:
    """One exact durable reason and its typed provenance subject."""

    kind: ReplayDeferralBasisKind
    record_id: str
    subject_id: str
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ReplayDeferralBasisKind):
            raise ReplayObligationError("replay deferral basis kind is not typed")
        if self.kind is ReplayDeferralBasisKind.STUDY_DIAGNOSIS:
            _identity("Study diagnosis basis", self.record_id, "diagnosis:")
            _ascii("diagnosed Study id", self.subject_id)
        elif self.kind is ReplayDeferralBasisKind.SOURCE_AUTHORITY_INVALIDATION:
            _identity(
                "source invalidation basis",
                self.record_id,
                "source-authority-invalidation:",
            )
            _identity("invalidated SourceContract", self.subject_id, "source:")
        elif self.kind is ReplayDeferralBasisKind.ARCHITECTURE_REVIEW:
            _identity("architecture review basis", self.record_id, "architecture-review:")
            _identity(
                "reviewed architecture family",
                self.subject_id,
                "architecture-family:",
            )
        else:
            _digest("external blocker basis", self.record_id)
            _ascii("external dependency id", self.subject_id)
        object.__setattr__(
            self,
            "identity",
            "historical-replay-deferral-basis:"
            + canonical_digest(
                domain="historical-replay-deferral-basis",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "record_id": self.record_id,
            "schema": "historical_replay_deferral_basis.v1",
            "subject_id": self.subject_id,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayResumeCondition:
    """One finite trigger over an immutable original replay protocol surface."""

    kind: ReplayResumeConditionKind
    protocol_id: str
    original_executable_ids: tuple[str, ...]
    criterion_ids: tuple[str, ...]
    subject_id: str | None = None
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ReplayResumeConditionKind):
            raise ReplayObligationError("replay resume condition kind is not typed")
        _ascii("replay protocol id", self.protocol_id)
        executables = _sorted_unique_ascii(
            "resume original Executable ids",
            self.original_executable_ids,
            nonempty=True,
        )
        for executable_id in executables:
            _identity("resume original Executable id", executable_id, "executable:")
        criteria = _sorted_unique_ascii(
            "resume criterion ids", self.criterion_ids, nonempty=True
        )
        if self.kind in {
            ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL,
            ReplayResumeConditionKind.SAME_PROTOCOL_REPAIR,
        }:
            if self.subject_id is not None:
                raise ReplayObligationError(
                    "material or repair resume cannot carry a provenance subject"
                )
        elif self.kind is ReplayResumeConditionKind.REPLACEMENT_SOURCE_CONTRACT:
            _identity("invalidated SourceContract", self.subject_id, "source:")
        else:
            _ascii("external dependency id", self.subject_id)
        object.__setattr__(self, "original_executable_ids", executables)
        object.__setattr__(self, "criterion_ids", criteria)
        object.__setattr__(
            self,
            "identity",
            "historical-replay-resume-condition:"
            + canonical_digest(
                domain="historical-replay-resume-condition",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "criterion_ids": list(self.criterion_ids),
            "kind": self.kind.value,
            "original_executable_ids": list(self.original_executable_ids),
            "protocol_id": self.protocol_id,
            "schema": "historical_replay_resume_condition.v1",
            "subject_id": self.subject_id,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayRepairProvenance:
    """Writer-verified implementation, failure, and validation-plan provenance."""

    basis_kind: ReplayRepairBasisKind
    prior_completion_record_id: str
    study_diagnosis_id: str
    protocol_id: str
    validation_plan_hash: str
    criterion_ids: tuple[str, ...]
    previous_implementation_identity: str
    repaired_implementation_identity: str
    changed_cause_proof_hash: str
    prior_failure_signature: str | None
    invalid_criterion_ids: tuple[str, ...]
    new_evidence_hashes: tuple[str, ...]
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.basis_kind, ReplayRepairBasisKind):
            raise ReplayObligationError("replay repair basis kind is not typed")
        _digest("replay prior completion", self.prior_completion_record_id)
        _identity("replay repair Study diagnosis", self.study_diagnosis_id, "diagnosis:")
        _ascii("replay repair protocol id", self.protocol_id)
        _digest("replay repair validation plan", self.validation_plan_hash)
        criteria = _sorted_unique_ascii(
            "replay repair criterion ids", self.criterion_ids, nonempty=True
        )
        _digest(
            "previous replay implementation", self.previous_implementation_identity
        )
        _digest(
            "repaired replay implementation", self.repaired_implementation_identity
        )
        if self.previous_implementation_identity == self.repaired_implementation_identity:
            raise ReplayObligationError(
                "replay repair must change implementation identity"
            )
        _digest("replay changed-cause proof", self.changed_cause_proof_hash)
        invalid_criteria = _sorted_unique_ascii(
            "replay repair invalid criterion ids",
            self.invalid_criterion_ids,
            nonempty=(
                self.basis_kind is ReplayRepairBasisKind.SCIENTIFIC_INVALIDITY
            ),
        )
        if self.basis_kind is ReplayRepairBasisKind.OPERATIONAL_FAILURE:
            _digest("replay prior failure signature", self.prior_failure_signature)
            if invalid_criteria:
                raise ReplayObligationError(
                    "operational replay repair cannot claim invalid criteria"
                )
        elif self.prior_failure_signature is not None:
            raise ReplayObligationError(
                "scientific replay repair cannot claim an operational failure"
            )
        evidence = _sorted_unique_ascii(
            "replay repair new evidence hashes",
            self.new_evidence_hashes,
            nonempty=True,
        )
        for evidence_hash in evidence:
            _digest("replay repair new evidence", evidence_hash)
        if self.repaired_implementation_identity not in evidence:
            raise ReplayObligationError(
                "replay repair evidence omits the repaired implementation"
            )
        object.__setattr__(self, "criterion_ids", criteria)
        object.__setattr__(self, "invalid_criterion_ids", invalid_criteria)
        object.__setattr__(self, "new_evidence_hashes", evidence)
        object.__setattr__(
            self,
            "identity",
            "historical-replay-repair-provenance:"
            + canonical_digest(
                domain="historical-replay-repair-provenance",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "basis_kind": self.basis_kind.value,
            "changed_cause_proof_hash": self.changed_cause_proof_hash,
            "criterion_ids": list(self.criterion_ids),
            "invalid_criterion_ids": list(self.invalid_criterion_ids),
            "new_evidence_hashes": list(self.new_evidence_hashes),
            "previous_implementation_identity": (
                self.previous_implementation_identity
            ),
            "prior_failure_signature": self.prior_failure_signature,
            "prior_completion_record_id": self.prior_completion_record_id,
            "protocol_id": self.protocol_id,
            "repaired_implementation_identity": (
                self.repaired_implementation_identity
            ),
            "schema": "historical_replay_repair_provenance.v1",
            "study_diagnosis_id": self.study_diagnosis_id,
            "validation_plan_hash": self.validation_plan_hash,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayDeferralExecutionBinding:
    """The exact diagnosed replay execution being deferred."""

    portfolio_decision_id: str
    replay_study_id: str
    replay_executable_id: str
    replay_study_close_record_id: str
    study_diagnosis_id: str
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _identity("Portfolio Decision id", self.portfolio_decision_id, "decision:")
        _ascii("replay Study id", self.replay_study_id)
        _identity("replay Executable id", self.replay_executable_id, "executable:")
        _digest("replay Study close record", self.replay_study_close_record_id)
        _identity("Study diagnosis id", self.study_diagnosis_id, "diagnosis:")
        object.__setattr__(
            self,
            "identity",
            "historical-replay-deferral-execution:"
            + canonical_digest(
                domain="historical-replay-deferral-execution",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "portfolio_decision_id": self.portfolio_decision_id,
            "replay_executable_id": self.replay_executable_id,
            "replay_study_close_record_id": self.replay_study_close_record_id,
            "replay_study_id": self.replay_study_id,
            "schema": "historical_replay_deferral_execution.v1",
            "study_diagnosis_id": self.study_diagnosis_id,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayDeferral:
    """A typed non-terminal deferral with finite durable resume conditions."""

    obligation_id: str
    basis: ReplayDeferralBasis
    reason_codes: tuple[str, ...]
    resume_conditions: tuple[ReplayResumeCondition, ...]
    execution_binding: ReplayDeferralExecutionBinding | None = None
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _identity(
            "replay obligation id",
            self.obligation_id,
            "historical-replay-obligation:",
        )
        if not isinstance(self.basis, ReplayDeferralBasis):
            raise ReplayObligationError("replay deferral basis is not typed")
        reasons = _sorted_unique_ascii(
            "deferral reason codes", self.reason_codes, nonempty=True
        )
        if type(self.resume_conditions) is not tuple or not self.resume_conditions:
            raise ReplayObligationError("replay resume conditions must be non-empty")
        if any(
            not isinstance(item, ReplayResumeCondition)
            for item in self.resume_conditions
        ):
            raise ReplayObligationError("replay resume condition is not typed")
        conditions = tuple(sorted(self.resume_conditions, key=lambda item: item.identity))
        if len({item.identity for item in conditions}) != len(conditions):
            raise ReplayObligationError("replay resume conditions must be unique")
        if self.execution_binding is not None and not isinstance(
            self.execution_binding, ReplayDeferralExecutionBinding
        ):
            raise ReplayObligationError("replay deferral execution binding is not typed")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "resume_conditions", conditions)
        object.__setattr__(
            self,
            "identity",
            "historical-replay-deferral:"
            + canonical_digest(
                domain="historical-replay-deferral",
                payload=self.to_identity_payload(),
            ),
        )

    @property
    def basis_record_id(self) -> str:
        return self.basis.record_id

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "basis": self.basis.to_identity_payload(),
            "execution_binding": (
                None
                if self.execution_binding is None
                else self.execution_binding.to_identity_payload()
            ),
            "obligation_id": self.obligation_id,
            "reason_codes": list(self.reason_codes),
            "resume_conditions": [
                item.to_identity_payload() for item in self.resume_conditions
            ],
            "schema": "historical_replay_deferral.v2",
        }


def replay_deferral_from_identity_payload(value: Mapping[str, Any]) -> ReplayDeferral:
    """Rehydrate and byte-check one stored typed replay deferral."""

    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "basis",
            "execution_binding",
            "obligation_id",
            "reason_codes",
            "resume_conditions",
            "schema",
        }
        or value.get("schema") != "historical_replay_deferral.v2"
    ):
        raise ReplayObligationError("historical replay deferral payload is malformed")
    try:
        basis_payload = value["basis"]
        if not isinstance(basis_payload, Mapping):
            raise TypeError("basis")
        basis = ReplayDeferralBasis(
            kind=ReplayDeferralBasisKind(basis_payload["kind"]),
            record_id=basis_payload["record_id"],
            subject_id=basis_payload["subject_id"],
        )
        condition_values = value["resume_conditions"]
        if not isinstance(condition_values, list):
            raise TypeError("conditions")
        conditions = tuple(
            ReplayResumeCondition(
                kind=ReplayResumeConditionKind(item["kind"]),
                protocol_id=item["protocol_id"],
                original_executable_ids=tuple(item["original_executable_ids"]),
                criterion_ids=tuple(item["criterion_ids"]),
                subject_id=item["subject_id"],
            )
            for item in condition_values
        )
        execution_payload = value["execution_binding"]
        execution = (
            None
            if execution_payload is None
            else ReplayDeferralExecutionBinding(
                portfolio_decision_id=execution_payload["portfolio_decision_id"],
                replay_study_id=execution_payload["replay_study_id"],
                replay_executable_id=execution_payload["replay_executable_id"],
                replay_study_close_record_id=execution_payload[
                    "replay_study_close_record_id"
                ],
                study_diagnosis_id=execution_payload["study_diagnosis_id"],
            )
        )
        deferral = ReplayDeferral(
            obligation_id=value["obligation_id"],
            basis=basis,
            reason_codes=tuple(value["reason_codes"]),
            resume_conditions=conditions,
            execution_binding=execution,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayObligationError(
            "historical replay deferral cannot be rebuilt"
        ) from exc
    if deferral.to_identity_payload() != dict(value):
        raise ReplayObligationError("historical replay deferral changed on rebuild")
    return deferral


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayResumeEvidence:
    """One exact later durable record satisfying one stored resume condition."""

    obligation_id: str
    deferral_id: str
    resume_condition_id: str
    trigger_record_id: str
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _identity(
            "replay obligation id",
            self.obligation_id,
            "historical-replay-obligation:",
        )
        _identity("replay deferral id", self.deferral_id, "historical-replay-deferral:")
        _identity(
            "replay resume condition id",
            self.resume_condition_id,
            "historical-replay-resume-condition:",
        )
        _ascii("replay resume trigger record", self.trigger_record_id)
        object.__setattr__(
            self,
            "identity",
            "historical-replay-resume-evidence:"
            + canonical_digest(
                domain="historical-replay-resume-evidence",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "deferral_id": self.deferral_id,
            "obligation_id": self.obligation_id,
            "resume_condition_id": self.resume_condition_id,
            "schema": "historical_replay_resume_evidence.v1",
            "trigger_record_id": self.trigger_record_id,
        }


def highest_pending_priority(
    obligations: tuple[HistoricalReplayObligation, ...],
) -> ReplayPriority | None:
    """Return the strict priority to schedule next for pending obligations."""

    if type(obligations) is not tuple or any(
        not isinstance(item, HistoricalReplayObligation) for item in obligations
    ):
        raise ReplayObligationError("pending obligations are not typed")
    priorities = {item.replay_priority for item in obligations}
    if ReplayPriority.P0 in priorities:
        return ReplayPriority.P0
    if ReplayPriority.P1 in priorities:
        return ReplayPriority.P1
    return None


__all__ = [
    "HistoricalReplayObligation",
    "ReplayDeferral",
    "ReplayDeferralBasis",
    "ReplayDeferralBasisKind",
    "ReplayDeferralExecutionBinding",
    "ReplayExecutionBinding",
    "ReplayObligationError",
    "ReplayObligationStatus",
    "ReplayPriorityEscalation",
    "ReplayRepairBasisKind",
    "ReplayResolutionScope",
    "ReplayRepairProvenance",
    "ReplayResumeCondition",
    "ReplayResumeConditionKind",
    "ReplayResumeEvidence",
    "ReplaySatisfaction",
    "derive_historical_replay_obligation",
    "historical_replay_obligation_from_identity_payload",
    "highest_pending_priority",
    "replay_priority_escalation_from_identity_payload",
    "replay_deferral_from_identity_payload",
]
