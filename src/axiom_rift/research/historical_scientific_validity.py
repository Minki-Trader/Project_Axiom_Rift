"""Completion-scoped invalidation of historical scientific authority.

The original completion, Study close, adjudication, and negative memory stay
immutable.  This record binds one exact audit finding that a decision used an
input whose claimed point-in-time availability was not proven.  It removes
authority from that completion without converting the defect into a scientific
failure or deleting diagnostic history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.historical_adjudication import HistoricalValidityReason


AUDIT_MANIFEST_SCHEMA = "historical_scientific_validity_invalidation.v1"
AUDIT_SLICE_SCHEMA = "historical_scientific_validity_audit_slice.v1"
AUTHORITY_DELTA_ZERO = {
    "candidate": 0,
    "economic": 0,
    "holdout": 0,
    "scientific": 0,
    "terminal": 0,
    "trial": 0,
}
DECISION_INPUT_FIELD = "spread"
CLAIMED_AVAILABILITY = "same_scheduled_or_deferred_entry_bar_before_order"
ALLOWED_AVAILABILITY = "completed_period_bar_close_only"
NEGATIVE_MEMORY_ROLE = "diagnostic_only"


class HistoricalScientificValidityError(ValueError):
    """A completion-validity audit record is malformed or overclaims."""


class JobBindingKind(str, Enum):
    """Historical Job boundary directly named by the audit slice."""

    DECLARATION = "declaration"
    START = "start"


class DecisionPredicateActivationState(str, Enum):
    """Observed activation depth without confusing evaluation with activation."""

    ACTIVATED = "activated"
    EVALUATED_NOT_ACTIVATED = "evaluated_not_activated"
    LEGACY_AGGREGATE_NOT_SERIALIZED = "legacy_aggregate_not_serialized"


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise HistoricalScientificValidityError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise HistoricalScientificValidityError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


def _identity(name: str, value: object, *, prefix: str) -> str:
    text = _ascii(name, value)
    if not text.startswith(prefix):
        raise HistoricalScientificValidityError(
            f"{name} must use the {prefix!r} namespace"
        )
    _digest(f"{name} digest", text.removeprefix(prefix))
    return text


def _ascii_set(name: str, value: object) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise HistoricalScientificValidityError(f"{name} must be a non-empty tuple")
    normalized = tuple(sorted(_ascii(name, item) for item in value))
    if len(normalized) != len(set(normalized)):
        raise HistoricalScientificValidityError(f"{name} must be unique")
    return normalized


def _digest_set(name: str, value: object) -> tuple[str, ...]:
    normalized = _ascii_set(name, value)
    for item in normalized:
        _digest(name, item)
    return normalized


def _is_exact_zero_authority_delta(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == set(AUTHORITY_DELTA_ZERO)
        and all(type(value[name]) is int and value[name] == 0 for name in value)
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalScientificValidityInvalidation:
    """Canonical audit manifest for one invalid historical completion."""

    study_id: str
    study_close_record_id: str
    job_id: str
    job_binding_kind: JobBindingKind
    job_binding_record_id: str
    completion_record_id: str
    executable_id: str
    validation_plan_hash: str
    measurement_artifact_hash: str
    result_manifest_hash: str
    component_implementation_hashes: tuple[str, ...]
    clock_contract: str
    cost_contract: str
    predicate_evaluated: bool
    activation_state: DecisionPredicateActivationState
    predicate_activation_count: int | None
    affected_claim_ids: tuple[str, ...]
    affected_evidence_modes: tuple[str, ...]
    affected_criterion_ids: tuple[str, ...]
    audit_finding_id: str
    audit_artifact_hash: str
    audit_slice_digest: str | None = None
    reason: HistoricalValidityReason = (
        HistoricalValidityReason.DECISION_INPUT_POINT_IN_TIME_UNPROVEN
    )
    decision_input_field: str = DECISION_INPUT_FIELD
    claimed_availability: str = CLAIMED_AVAILABILITY
    allowed_availability: str = ALLOWED_AVAILABILITY
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("Study id", self.study_id)
        _digest("Study close record id", self.study_close_record_id)
        _identity("Job id", self.job_id, prefix="job:")
        if not isinstance(self.job_binding_kind, JobBindingKind):
            raise HistoricalScientificValidityError("Job binding kind is not typed")
        if self.job_binding_kind is JobBindingKind.DECLARATION:
            if self.job_binding_record_id != self.job_id:
                raise HistoricalScientificValidityError(
                    "declaration binding must name the exact Job declaration"
                )
        else:
            _digest("Job start record id", self.job_binding_record_id)
        _digest("completion record id", self.completion_record_id)
        _identity("Executable id", self.executable_id, prefix="executable:")
        _digest("validation plan hash", self.validation_plan_hash)
        _digest("measurement artifact hash", self.measurement_artifact_hash)
        _digest("result manifest hash", self.result_manifest_hash)
        implementations = _digest_set(
            "component implementation hashes",
            self.component_implementation_hashes,
        )
        _ascii("clock contract", self.clock_contract)
        _ascii("cost contract", self.cost_contract)
        if not self.clock_contract.startswith("clock:"):
            raise HistoricalScientificValidityError(
                "clock contract must use the clock namespace"
            )
        if not self.cost_contract.startswith("cost:"):
            raise HistoricalScientificValidityError(
                "cost contract must use the cost namespace"
            )
        if self.predicate_evaluated is not True:
            raise HistoricalScientificValidityError(
                "the unavailable decision predicate must have been evaluated"
            )
        if not isinstance(self.activation_state, DecisionPredicateActivationState):
            raise HistoricalScientificValidityError("activation state is not typed")
        if self.activation_state is DecisionPredicateActivationState.ACTIVATED:
            if (
                type(self.predicate_activation_count) is not int
                or self.predicate_activation_count < 1
            ):
                raise HistoricalScientificValidityError(
                    "activated predicates require a positive activation count"
                )
        elif (
            self.activation_state
            is DecisionPredicateActivationState.EVALUATED_NOT_ACTIVATED
        ):
            if (
                type(self.predicate_activation_count) is not int
                or self.predicate_activation_count != 0
            ):
                raise HistoricalScientificValidityError(
                    "evaluated non-activation requires an exact zero count"
                )
        elif self.predicate_activation_count is not None:
            raise HistoricalScientificValidityError(
                "legacy aggregate activation count must remain unserialized"
            )
        claims = _ascii_set("affected claim ids", self.affected_claim_ids)
        modes = _ascii_set(
            "affected evidence modes",
            self.affected_evidence_modes,
        )
        criteria = _ascii_set(
            "affected criterion ids",
            self.affected_criterion_ids,
        )
        finding_id = _ascii("audit finding id", self.audit_finding_id)
        if not finding_id.startswith("AX-") or any(
            char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
            for char in finding_id
        ):
            raise HistoricalScientificValidityError(
                "audit finding id must be an uppercase AX- identifier"
            )
        _digest("audit artifact hash", self.audit_artifact_hash)
        if (
            not isinstance(self.reason, HistoricalValidityReason)
            or self.reason
            is not HistoricalValidityReason.DECISION_INPUT_POINT_IN_TIME_UNPROVEN
        ):
            raise HistoricalScientificValidityError(
                "completion invalidation reason is unsupported"
            )
        if self.decision_input_field != DECISION_INPUT_FIELD:
            raise HistoricalScientificValidityError(
                "completion invalidation supports only the audited spread field"
            )
        if self.claimed_availability != CLAIMED_AVAILABILITY:
            raise HistoricalScientificValidityError(
                "claimed point-in-time availability is unsupported"
            )
        if self.allowed_availability != ALLOWED_AVAILABILITY:
            raise HistoricalScientificValidityError(
                "allowed availability must be completed-period bar close only"
            )
        object.__setattr__(self, "component_implementation_hashes", implementations)
        object.__setattr__(self, "affected_claim_ids", claims)
        object.__setattr__(self, "affected_evidence_modes", modes)
        object.__setattr__(self, "affected_criterion_ids", criteria)
        expected_slice_digest = canonical_digest(
            domain="historical-scientific-validity-audit-slice",
            payload=self.to_audit_slice_payload(),
        )
        if self.audit_slice_digest is None:
            object.__setattr__(self, "audit_slice_digest", expected_slice_digest)
        elif (
            _digest("audit slice digest", self.audit_slice_digest)
            != expected_slice_digest
        ):
            raise HistoricalScientificValidityError(
                "audit slice digest does not match the semantic finding slice"
            )
        object.__setattr__(
            self,
            "identity",
            "historical-scientific-validity-invalidation:"
            + canonical_digest(
                domain="historical-scientific-validity-invalidation",
                payload=self.to_identity_payload(),
            ),
        )

    @property
    def candidate_eligible(self) -> bool:
        return False

    @property
    def scientific_eligible(self) -> bool:
        return False

    @property
    def negative_memory_role(self) -> str:
        return NEGATIVE_MEMORY_ROLE

    def to_audit_slice_payload(self) -> dict[str, Any]:
        """Return the canonical per-completion facts independently of prose."""

        return {
            "activation_state": self.activation_state.value,
            "affected_claim_ids": list(self.affected_claim_ids),
            "affected_criterion_ids": list(self.affected_criterion_ids),
            "affected_evidence_modes": list(self.affected_evidence_modes),
            "allowed_availability": self.allowed_availability,
            "audit_finding_id": self.audit_finding_id,
            "claimed_availability": self.claimed_availability,
            "clock_contract": self.clock_contract,
            "completion_record_id": self.completion_record_id,
            "component_implementation_hashes": list(
                self.component_implementation_hashes
            ),
            "cost_contract": self.cost_contract,
            "decision_input_field": self.decision_input_field,
            "executable_id": self.executable_id,
            "job_binding_kind": self.job_binding_kind.value,
            "job_binding_record_id": self.job_binding_record_id,
            "job_id": self.job_id,
            "measurement_artifact_hash": self.measurement_artifact_hash,
            "predicate_activation_count": self.predicate_activation_count,
            "predicate_evaluated": True,
            "reason": self.reason.value,
            "result_manifest_hash": self.result_manifest_hash,
            "schema": AUDIT_SLICE_SCHEMA,
            "study_close_record_id": self.study_close_record_id,
            "study_id": self.study_id,
            "validation_plan_hash": self.validation_plan_hash,
        }

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "activation_state": self.activation_state.value,
            "affected_claim_ids": list(self.affected_claim_ids),
            "affected_criterion_ids": list(self.affected_criterion_ids),
            "affected_evidence_modes": list(self.affected_evidence_modes),
            "allowed_availability": self.allowed_availability,
            "audit_artifact_hash": self.audit_artifact_hash,
            "audit_finding_id": self.audit_finding_id,
            "audit_slice_digest": self.audit_slice_digest,
            "authority_delta": dict(AUTHORITY_DELTA_ZERO),
            "candidate_eligible": False,
            "claimed_availability": self.claimed_availability,
            "clock_contract": self.clock_contract,
            "completion_record_id": self.completion_record_id,
            "component_implementation_hashes": list(
                self.component_implementation_hashes
            ),
            "cost_contract": self.cost_contract,
            "decision_input_field": self.decision_input_field,
            "executable_id": self.executable_id,
            "job_binding_kind": self.job_binding_kind.value,
            "job_binding_record_id": self.job_binding_record_id,
            "job_id": self.job_id,
            "measurement_artifact_hash": self.measurement_artifact_hash,
            "negative_memory_role": NEGATIVE_MEMORY_ROLE,
            "predicate_activation_count": self.predicate_activation_count,
            "predicate_evaluated": True,
            "reason": self.reason.value,
            "result_manifest_hash": self.result_manifest_hash,
            "schema": AUDIT_MANIFEST_SCHEMA,
            "scientific_eligible": False,
            "study_close_record_id": self.study_close_record_id,
            "study_id": self.study_id,
            "validation_plan_hash": self.validation_plan_hash,
        }

    @classmethod
    def from_mapping(
        cls,
        value: object,
    ) -> HistoricalScientificValidityInvalidation:
        expected = {
            "activation_state",
            "affected_claim_ids",
            "affected_criterion_ids",
            "affected_evidence_modes",
            "allowed_availability",
            "audit_artifact_hash",
            "audit_finding_id",
            "audit_slice_digest",
            "authority_delta",
            "candidate_eligible",
            "claimed_availability",
            "clock_contract",
            "completion_record_id",
            "component_implementation_hashes",
            "cost_contract",
            "decision_input_field",
            "executable_id",
            "job_binding_kind",
            "job_binding_record_id",
            "job_id",
            "measurement_artifact_hash",
            "negative_memory_role",
            "predicate_activation_count",
            "predicate_evaluated",
            "reason",
            "result_manifest_hash",
            "schema",
            "scientific_eligible",
            "study_close_record_id",
            "study_id",
            "validation_plan_hash",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != expected
            or value.get("schema") != AUDIT_MANIFEST_SCHEMA
            or not _is_exact_zero_authority_delta(value.get("authority_delta"))
            or value.get("candidate_eligible") is not False
            or value.get("scientific_eligible") is not False
            or value.get("negative_memory_role") != NEGATIVE_MEMORY_ROLE
            or value.get("predicate_evaluated") is not True
            or any(
                not isinstance(value.get(name), list)
                for name in (
                    "affected_claim_ids",
                    "affected_criterion_ids",
                    "affected_evidence_modes",
                    "component_implementation_hashes",
                )
            )
        ):
            raise HistoricalScientificValidityError(
                "historical scientific validity payload is malformed"
            )
        try:
            record = cls(
                study_id=value["study_id"],  # type: ignore[arg-type]
                study_close_record_id=value["study_close_record_id"],  # type: ignore[arg-type]
                job_id=value["job_id"],  # type: ignore[arg-type]
                job_binding_kind=JobBindingKind(value["job_binding_kind"]),
                job_binding_record_id=value["job_binding_record_id"],  # type: ignore[arg-type]
                completion_record_id=value["completion_record_id"],  # type: ignore[arg-type]
                executable_id=value["executable_id"],  # type: ignore[arg-type]
                validation_plan_hash=value["validation_plan_hash"],  # type: ignore[arg-type]
                measurement_artifact_hash=value["measurement_artifact_hash"],  # type: ignore[arg-type]
                result_manifest_hash=value["result_manifest_hash"],  # type: ignore[arg-type]
                component_implementation_hashes=tuple(
                    value["component_implementation_hashes"]  # type: ignore[arg-type]
                ),
                clock_contract=value["clock_contract"],  # type: ignore[arg-type]
                cost_contract=value["cost_contract"],  # type: ignore[arg-type]
                predicate_evaluated=value["predicate_evaluated"],  # type: ignore[arg-type]
                activation_state=DecisionPredicateActivationState(
                    value["activation_state"]
                ),
                predicate_activation_count=value["predicate_activation_count"],  # type: ignore[arg-type]
                affected_claim_ids=tuple(
                    value["affected_claim_ids"]  # type: ignore[arg-type]
                ),
                affected_evidence_modes=tuple(
                    value["affected_evidence_modes"]  # type: ignore[arg-type]
                ),
                affected_criterion_ids=tuple(
                    value["affected_criterion_ids"]  # type: ignore[arg-type]
                ),
                audit_finding_id=value["audit_finding_id"],  # type: ignore[arg-type]
                audit_artifact_hash=value["audit_artifact_hash"],  # type: ignore[arg-type]
                audit_slice_digest=value["audit_slice_digest"],  # type: ignore[arg-type]
                reason=HistoricalValidityReason(value["reason"]),
                decision_input_field=value["decision_input_field"],  # type: ignore[arg-type]
                claimed_availability=value["claimed_availability"],  # type: ignore[arg-type]
                allowed_availability=value["allowed_availability"],  # type: ignore[arg-type]
            )
        except HistoricalScientificValidityError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoricalScientificValidityError(
                "historical scientific validity payload cannot be rebuilt"
            ) from exc
        if record.to_identity_payload() != dict(value):
            raise HistoricalScientificValidityError(
                "historical scientific validity payload changed on rebuild"
            )
        return record

    @classmethod
    def from_bytes(
        cls,
        document: bytes,
    ) -> HistoricalScientificValidityInvalidation:
        return cls.from_mapping(parse_canonical(document))


def historical_scientific_validity_invalidation_from_payload(
    value: object,
) -> HistoricalScientificValidityInvalidation:
    """Parse one exact direct Journal/index payload."""

    return HistoricalScientificValidityInvalidation.from_mapping(value)


def historical_scientific_validity_invalidation_from_bytes(
    document: bytes,
) -> HistoricalScientificValidityInvalidation:
    """Parse one canonical audit manifest document."""

    return HistoricalScientificValidityInvalidation.from_bytes(document)


completion_validity_invalidation_from_payload = (
    historical_scientific_validity_invalidation_from_payload
)
completion_validity_invalidation_from_bytes = (
    historical_scientific_validity_invalidation_from_bytes
)


__all__ = [
    "ALLOWED_AVAILABILITY",
    "AUDIT_MANIFEST_SCHEMA",
    "AUDIT_SLICE_SCHEMA",
    "AUTHORITY_DELTA_ZERO",
    "CLAIMED_AVAILABILITY",
    "DECISION_INPUT_FIELD",
    "DecisionPredicateActivationState",
    "HistoricalScientificValidityError",
    "HistoricalScientificValidityInvalidation",
    "JobBindingKind",
    "NEGATIVE_MEMORY_ROLE",
    "completion_validity_invalidation_from_bytes",
    "completion_validity_invalidation_from_payload",
    "historical_scientific_validity_invalidation_from_bytes",
    "historical_scientific_validity_invalidation_from_payload",
]
