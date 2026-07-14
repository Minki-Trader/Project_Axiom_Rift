"""Prospective component-aware scientific evidence validation.

Version 2 keeps the writer-facing scientific result and facts surfaces
compatible with version 1.  Its plan and measurement schemas are separate,
strict, and contain only preregistered component roles plus concurrent-family
multiplicity.  Project-wide trial history is deliberately not an input.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import axiom_rift.research.adjudication as adjudication_module
import axiom_rift.research.analog_state_family as analog_family_module
import axiom_rift.research.analog_state_trace as analog_trace_module
import axiom_rift.research.audit_integrity_proof as audit_proof_module
import axiom_rift.research.evidence_proofs as evidence_proof_module
import axiom_rift.research.selection_inference as selection_inference_module
import axiom_rift.research.scientific_trace as scientific_trace_module
from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    ValidatedEvidence,
    validator_identity,
    validator_implementation_sha256,
)
from axiom_rift.research.adjudication import (
    MULTIPLICITY_CRITERION_IDS,
    PER_MILLION,
    RISK_DIAGNOSTIC_CRITERION_IDS,
    VALIDITY_METRICS,
    AdjudicationProfile,
    MultiplicityAssessment,
    adjudicate_plan_measurement,
    bonferroni_concurrent_family,
    scientific_adjudication_manifest,
)
from axiom_rift.research.evidence_proofs import (
    ProofReference,
    ProofRequirement,
    ScientificEvidenceProofError,
    parse_proof_references,
    parse_proof_requirements,
    validate_proof_artifacts,
)


SCIENTIFIC_VALIDATION_PLAN_V2_SCHEMA = "scientific_validation_plan.v2"
SCIENTIFIC_ADJUDICATION_PROFILE_SCHEMA = "scientific_adjudication_profile.v1"
SCIENTIFIC_MEASUREMENT_V2_SCHEMA = "scientific_measurement.v2"
SCIENTIFIC_RESULT_SCHEMA = "scientific_job_evidence.v1"
SCIENTIFIC_VALIDATION_V2_PROTOCOL = "scientific_adjudication.v2"
SCIENTIFIC_VALIDATION_V2_DOMAINS = frozenset({"scientific"})
SCIENTIFIC_V2_CRITERION_OPERATORS = frozenset({"eq", "ge", "gt", "le", "lt"})
SCIENTIFIC_V2_DECISION_ROLES = frozenset(
    {"component", "multiplicity", "risk_diagnostic", "risk_gate", "validity"}
)
SCIENTIFIC_V2_MULTIPLICITY_METHOD = "bonferroni_concurrent_family.v1"

_PLAN_FIELDS = {
    "adjudication_profile",
    "candidate_eligible_on_pass",
    "criteria",
    "evidence_depth",
    "evidence_modes",
    "executable_id",
    "mission_id",
    "planned_claims",
    "proof_requirements",
    "schema",
}
_CRITERION_FIELDS = {
    "claim_id",
    "criterion_id",
    "decision_role",
    "evidence_mode",
    "metric",
    "operator",
    "threshold",
}
_PROFILE_FIELDS = {
    "decisive_risk_criterion_ids",
    "multiplicity",
    "promotion_criterion_ids",
    "schema",
}
_MULTIPLICITY_REGISTRATION_FIELDS = {
    "alpha_ppm",
    "criterion_id",
    "family_id",
    "family_registration_hash",
    "family_size",
    "member_id",
    "method",
    "ordered_member_ids",
}
_MULTIPLICITY_RESULT_FIELDS = _MULTIPLICITY_REGISTRATION_FIELDS | {
    "adjusted_pvalue_ppm",
    "raw_pvalue_ppm",
}
_MEASUREMENT_FIELDS = {
    "evidence_depth",
    "evidence_modes",
    "executable_id",
    "job_hash",
    "job_id",
    "metrics",
    "mission_id",
    "multiplicity",
    "proofs",
    "schema",
}
_RESULT_FIELDS = {
    "evidence_depth",
    "executable_id",
    "job_hash",
    "job_id",
    "mission_id",
    "observations",
    "schema",
}
_BINDING_FIELDS = {
    "evidence_depth",
    "evidence_modes",
    "planned_claims",
    "result_manifest_output",
    "validation_plan_hash",
    "validator_id",
}


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise EvidenceValidationError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise EvidenceValidationError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _plain(value: object) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return value


def _sorted_ascii_sequence(
    name: str,
    value: object,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or (not value and not allow_empty):
        qualifier = "a sequence" if allow_empty else "a non-empty sequence"
        raise EvidenceValidationError(f"{name} must be {qualifier}")
    normalized = tuple(_ascii(name, item) for item in value)
    if normalized != tuple(sorted(set(normalized))):
        raise EvidenceValidationError(f"{name} must be sorted and unique")
    return normalized


def _ordered_ascii_sequence(name: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise EvidenceValidationError(f"{name} must be a non-empty sequence")
    normalized = tuple(_ascii(name, item) for item in value)
    if len(set(normalized)) != len(normalized):
        raise EvidenceValidationError(f"{name} must contain unique values")
    return normalized


def _ppm(name: str, value: object, *, allow_zero: bool = True) -> int:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or not minimum <= value <= PER_MILLION:
        raise EvidenceValidationError(
            f"{name} must be an integer in [{minimum}, {PER_MILLION}]"
        )
    return value


def multiplicity_family_registration_hash(
    *,
    family_id: str,
    alpha_ppm: int,
    method: str,
    ordered_member_ids: tuple[str, ...],
) -> str:
    """Freeze one exact prospective family before any Job result exists."""

    family = _ascii("multiplicity family_id", family_id)
    alpha = _ppm("multiplicity alpha_ppm", alpha_ppm, allow_zero=False)
    registered_method = _ascii("multiplicity method", method)
    if registered_method != SCIENTIFIC_V2_MULTIPLICITY_METHOD:
        raise EvidenceValidationError(
            "scientific v2 multiplicity method is not registered"
        )
    members = _ordered_ascii_sequence(
        "multiplicity ordered_member_ids", ordered_member_ids
    )
    return canonical_digest(
        domain="scientific-v2-multiplicity-family",
        payload={
            "alpha_ppm": alpha,
            "family_id": family,
            "family_size": len(members),
            "method": registered_method,
            "ordered_member_ids": list(members),
            "schema": "scientific_multiplicity_family_registration.v1",
        },
    )


@dataclass(frozen=True, slots=True)
class _Criterion:
    claim_id: str
    criterion_id: str
    decision_role: str
    evidence_mode: str
    metric: str
    operator: str
    threshold: int

    @property
    def sort_key(self) -> tuple[str, str]:
        return self.claim_id, self.criterion_id

    @property
    def metric_key(self) -> tuple[str, str]:
        return self.claim_id, self.metric


@dataclass(frozen=True, slots=True)
class _MultiplicityRegistration:
    alpha_ppm: int
    criterion_id: str
    family_id: str
    family_registration_hash: str
    family_size: int
    member_id: str
    method: str
    ordered_member_ids: tuple[str, ...]

    @property
    def family_metadata(self) -> tuple[object, ...]:
        return (
            self.family_size,
            self.alpha_ppm,
            self.method,
            self.ordered_member_ids,
            self.family_registration_hash,
        )


@dataclass(frozen=True, slots=True)
class _Profile:
    decisive_risk_criterion_ids: tuple[str, ...]
    multiplicity: tuple[_MultiplicityRegistration, ...]
    promotion_criterion_ids: tuple[str, ...]


def _criterion(value: object) -> _Criterion:
    if not isinstance(value, Mapping) or set(value) != _CRITERION_FIELDS:
        raise EvidenceValidationError("scientific v2 criterion schema is invalid")
    operator = _ascii("criterion operator", value["operator"])
    if operator not in SCIENTIFIC_V2_CRITERION_OPERATORS:
        raise EvidenceValidationError("scientific v2 criterion operator is invalid")
    role = _ascii("criterion decision_role", value["decision_role"])
    if role not in SCIENTIFIC_V2_DECISION_ROLES:
        raise EvidenceValidationError("scientific v2 decision role is invalid")
    threshold = value["threshold"]
    if type(threshold) is not int:
        raise EvidenceValidationError("scientific v2 threshold must be an integer")
    return _Criterion(
        claim_id=_ascii("criterion claim_id", value["claim_id"]),
        criterion_id=_ascii("criterion_id", value["criterion_id"]),
        decision_role=role,
        evidence_mode=_ascii("criterion evidence_mode", value["evidence_mode"]),
        metric=_ascii("criterion metric", value["metric"]),
        operator=operator,
        threshold=threshold,
    )


def _multiplicity_registration(value: object) -> _MultiplicityRegistration:
    if (
        not isinstance(value, Mapping)
        or set(value) != _MULTIPLICITY_REGISTRATION_FIELDS
    ):
        raise EvidenceValidationError(
            "scientific v2 multiplicity registration schema is invalid"
        )
    family_size = value["family_size"]
    if type(family_size) is not int or family_size < 1:
        raise EvidenceValidationError(
            "scientific v2 multiplicity family_size must be positive"
        )
    method = _ascii("multiplicity method", value["method"])
    if method != SCIENTIFIC_V2_MULTIPLICITY_METHOD:
        raise EvidenceValidationError(
            "scientific v2 multiplicity method is not registered"
        )
    family_id = _ascii("multiplicity family_id", value["family_id"])
    alpha_ppm = _ppm(
        "multiplicity alpha_ppm", value["alpha_ppm"], allow_zero=False
    )
    members = _ordered_ascii_sequence(
        "multiplicity ordered_member_ids", value["ordered_member_ids"]
    )
    if len(members) != family_size:
        raise EvidenceValidationError(
            "scientific v2 ordered family membership differs from family_size"
        )
    member_id = _ascii("multiplicity member_id", value["member_id"])
    if member_id not in members:
        raise EvidenceValidationError(
            "scientific v2 multiplicity member is outside its family"
        )
    registration_hash = _digest(
        "multiplicity family_registration_hash",
        value["family_registration_hash"],
    )
    expected_hash = multiplicity_family_registration_hash(
        family_id=family_id,
        alpha_ppm=alpha_ppm,
        method=method,
        ordered_member_ids=members,
    )
    if registration_hash != expected_hash:
        raise EvidenceValidationError(
            "scientific v2 multiplicity family registration hash is invalid"
        )
    return _MultiplicityRegistration(
        alpha_ppm=alpha_ppm,
        criterion_id=_ascii("multiplicity criterion_id", value["criterion_id"]),
        family_id=family_id,
        family_registration_hash=registration_hash,
        family_size=family_size,
        member_id=member_id,
        method=method,
        ordered_member_ids=members,
    )


def _parse_profile(value: object) -> _Profile:
    if (
        not isinstance(value, Mapping)
        or set(value) != _PROFILE_FIELDS
        or value.get("schema") != SCIENTIFIC_ADJUDICATION_PROFILE_SCHEMA
    ):
        raise EvidenceValidationError("scientific v2 profile schema is invalid")
    decisive = _sorted_ascii_sequence(
        "decisive risk criterion_ids",
        value["decisive_risk_criterion_ids"],
        allow_empty=True,
    )
    if set(decisive) - RISK_DIAGNOSTIC_CRITERION_IDS:
        raise EvidenceValidationError("scientific v2 decisive risk profile is invalid")
    promotion = _sorted_ascii_sequence(
        "promotion criterion_ids",
        value["promotion_criterion_ids"],
        allow_empty=True,
    )
    raw_multiplicity = value["multiplicity"]
    if not isinstance(raw_multiplicity, (list, tuple)):
        raise EvidenceValidationError("scientific v2 multiplicity profile is invalid")
    multiplicity = tuple(
        _multiplicity_registration(item) for item in raw_multiplicity
    )
    identities = tuple(item.criterion_id for item in multiplicity)
    if identities != tuple(sorted(set(identities))):
        raise EvidenceValidationError(
            "scientific v2 multiplicity registrations must be sorted and unique"
        )
    family_metadata: dict[str, tuple[object, ...]] = {}
    family_counts: dict[str, int] = {}
    family_members: dict[str, set[str]] = {}
    for item in multiplicity:
        previous = family_metadata.setdefault(item.family_id, item.family_metadata)
        if previous != item.family_metadata:
            raise EvidenceValidationError(
                "scientific v2 family metadata must be internally consistent"
            )
        family_counts[item.family_id] = family_counts.get(item.family_id, 0) + 1
        members = family_members.setdefault(item.family_id, set())
        if item.member_id in members:
            raise EvidenceValidationError(
                "scientific v2 multiplicity family member is registered twice"
            )
        members.add(item.member_id)
    for item in multiplicity:
        if (
            family_counts[item.family_id] != item.family_size
            or family_members[item.family_id] != set(item.ordered_member_ids)
        ):
            raise EvidenceValidationError(
                "scientific v2 multiplicity family registration is incomplete"
            )
    return _Profile(
        decisive_risk_criterion_ids=decisive,
        multiplicity=multiplicity,
        promotion_criterion_ids=promotion,
    )


def _expected_role(criterion: _Criterion, profile: _Profile) -> str:
    if criterion.metric in VALIDITY_METRICS:
        return "validity"
    if criterion.criterion_id in MULTIPLICITY_CRITERION_IDS:
        return "multiplicity"
    if criterion.criterion_id in RISK_DIAGNOSTIC_CRITERION_IDS:
        if criterion.criterion_id in profile.decisive_risk_criterion_ids:
            return "risk_gate"
        return "risk_diagnostic"
    return "component"


def _parse_plan(
    value: object,
) -> tuple[
    dict[str, Any],
    tuple[_Criterion, ...],
    _Profile,
    tuple[ProofRequirement, ...],
]:
    if (
        not isinstance(value, dict)
        or set(value) != _PLAN_FIELDS
        or value.get("schema") != SCIENTIFIC_VALIDATION_PLAN_V2_SCHEMA
    ):
        raise EvidenceValidationError("scientific v2 validation plan schema is invalid")
    _ascii("plan mission_id", value["mission_id"])
    _ascii("plan executable_id", value["executable_id"])
    depth = value["evidence_depth"]
    if depth not in {"discovery", "confirmation"}:
        raise EvidenceValidationError("scientific v2 evidence depth is invalid")
    candidate_policy = value["candidate_eligible_on_pass"]
    if type(candidate_policy) is not bool:
        raise EvidenceValidationError("scientific v2 candidate policy is invalid")
    if depth == "discovery" and candidate_policy:
        raise EvidenceValidationError("scientific v2 discovery cannot authorize a candidate")
    claims = _sorted_ascii_sequence(
        "plan claims", value["planned_claims"], allow_empty=False
    )
    modes = _sorted_ascii_sequence(
        "plan evidence modes", value["evidence_modes"], allow_empty=False
    )
    try:
        proof_requirements = parse_proof_requirements(
            value["proof_requirements"], evidence_modes=modes
        )
    except ScientificEvidenceProofError as exc:
        raise EvidenceValidationError(
            "scientific v2 proof requirements are invalid"
        ) from exc
    raw_criteria = value["criteria"]
    if not isinstance(raw_criteria, (list, tuple)) or not raw_criteria:
        raise EvidenceValidationError("scientific v2 plan requires criteria")
    criteria = tuple(_criterion(item) for item in raw_criteria)
    sort_keys = tuple(item.sort_key for item in criteria)
    if sort_keys != tuple(sorted(sort_keys)):
        raise EvidenceValidationError("scientific v2 criteria are not canonical")
    criterion_ids = tuple(item.criterion_id for item in criteria)
    if len(set(criterion_ids)) != len(criterion_ids):
        raise EvidenceValidationError("scientific v2 criterion ids must be unique")
    if {item.claim_id for item in criteria} != set(claims):
        raise EvidenceValidationError("scientific v2 criteria do not cover every claim")
    if {item.evidence_mode for item in criteria} != set(modes):
        raise EvidenceValidationError(
            "scientific v2 criteria do not cover every evidence mode"
        )
    metric_modes: dict[tuple[str, str], str] = {}
    for item in criteria:
        previous = metric_modes.setdefault(item.metric_key, item.evidence_mode)
        if previous != item.evidence_mode:
            raise EvidenceValidationError(
                "one scientific v2 metric cannot establish multiple evidence modes"
            )

    profile = _parse_profile(value["adjudication_profile"])
    by_id = {item.criterion_id: item for item in criteria}
    if not set(profile.decisive_risk_criterion_ids).issubset(by_id):
        raise EvidenceValidationError("scientific v2 decisive risk criterion is absent")
    for item in criteria:
        if item.decision_role != _expected_role(item, profile):
            raise EvidenceValidationError(
                "scientific v2 decision role differs from its profile"
            )
    decisive_roles = {"component", "multiplicity", "risk_gate"}
    decisive_count = 0
    for claim in claims:
        claim_roles = {
            item.decision_role for item in criteria if item.claim_id == claim
        }
        decisive_count += sum(
            item.decision_role in decisive_roles
            for item in criteria
            if item.claim_id == claim
        )
        if (
            not claim_roles.intersection(decisive_roles)
            and claim_roles != {"validity"}
        ):
            raise EvidenceValidationError(
                "scientific v2 non-validity claims require a decisive component"
            )
    if decisive_count == 0:
        raise EvidenceValidationError(
            "scientific v2 plan requires at least one decisive component"
        )
    registered_multiplicity = {
        item.criterion_id: item for item in profile.multiplicity
    }
    required_multiplicity = {
        item.criterion_id
        for item in criteria
        if item.decision_role == "multiplicity"
    }
    if set(registered_multiplicity) != required_multiplicity:
        raise EvidenceValidationError(
            "scientific v2 multiplicity profile differs from its criteria"
        )
    for criterion_id, registration in registered_multiplicity.items():
        criterion = by_id[criterion_id]
        if (
            criterion.operator != "le"
            or criterion.threshold != registration.alpha_ppm
        ):
            raise EvidenceValidationError(
                "scientific v2 multiplicity threshold differs from alpha"
            )
    if not set(profile.promotion_criterion_ids).issubset(by_id):
        raise EvidenceValidationError("scientific v2 promotion criterion is absent")
    for criterion_id in profile.promotion_criterion_ids:
        if by_id[criterion_id].decision_role not in {
            "component",
            "multiplicity",
            "risk_gate",
        }:
            raise EvidenceValidationError(
                "scientific v2 promotion criteria must be decisive"
            )
    if candidate_policy and not profile.promotion_criterion_ids:
        raise EvidenceValidationError(
            "scientific v2 candidate policy requires promotion gates"
        )
    return value, criteria, profile, proof_requirements


def build_validation_plan_v2(
    *,
    mission_id: str,
    executable_id: str,
    evidence_depth: str,
    planned_claims: tuple[str, ...],
    evidence_modes: tuple[str, ...],
    criteria: tuple[Mapping[str, object], ...],
    adjudication_profile: Mapping[str, object],
    proof_requirements: tuple[Mapping[str, object], ...],
    candidate_eligible_on_pass: bool = False,
) -> dict[str, object]:
    """Build and fully validate one canonical-ready v2 plan."""

    plan: dict[str, object] = {
        "adjudication_profile": _plain(adjudication_profile),
        "candidate_eligible_on_pass": candidate_eligible_on_pass,
        "criteria": [_plain(item) for item in criteria],
        "evidence_depth": evidence_depth,
        "evidence_modes": list(evidence_modes),
        "executable_id": executable_id,
        "mission_id": mission_id,
        "planned_claims": list(planned_claims),
        "proof_requirements": [_plain(item) for item in proof_requirements],
        "schema": SCIENTIFIC_VALIDATION_PLAN_V2_SCHEMA,
    }
    _parse_plan(plan)
    canonical_bytes(plan)
    return plan


def _parse_multiplicity_results(
    value: object,
    *,
    registrations: tuple[_MultiplicityRegistration, ...],
    criteria: tuple[_Criterion, ...],
    metrics: Mapping[str, Mapping[str, int | None]],
) -> tuple[MultiplicityAssessment, ...]:
    if not isinstance(value, (list, tuple)):
        raise EvidenceValidationError("scientific v2 multiplicity results are invalid")
    registration_by_id = {item.criterion_id: item for item in registrations}
    criterion_by_id = {item.criterion_id: item for item in criteria}
    results: list[MultiplicityAssessment] = []
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != _MULTIPLICITY_RESULT_FIELDS:
            raise EvidenceValidationError(
                "scientific v2 multiplicity result schema is invalid"
            )
        criterion_id = _ascii("multiplicity criterion_id", raw["criterion_id"])
        registration = registration_by_id.get(criterion_id)
        if registration is None:
            raise EvidenceValidationError(
                "scientific v2 multiplicity result was not preregistered"
            )
        family_id = _ascii("multiplicity family_id", raw["family_id"])
        family_registration_hash = _digest(
            "multiplicity family_registration_hash",
            raw["family_registration_hash"],
        )
        family_size = raw["family_size"]
        if type(family_size) is not int or family_size < 1:
            raise EvidenceValidationError(
                "scientific v2 multiplicity result family_size is invalid"
            )
        alpha_ppm = _ppm(
            "multiplicity result alpha_ppm", raw["alpha_ppm"], allow_zero=False
        )
        method = _ascii("multiplicity method", raw["method"])
        member_id = _ascii("multiplicity member_id", raw["member_id"])
        ordered_member_ids = _ordered_ascii_sequence(
            "multiplicity ordered_member_ids", raw["ordered_member_ids"]
        )
        metadata = (
            family_id,
            family_size,
            alpha_ppm,
            method,
            member_id,
            ordered_member_ids,
            family_registration_hash,
        )
        expected_metadata = (
            registration.family_id,
            registration.family_size,
            registration.alpha_ppm,
            registration.method,
            registration.member_id,
            registration.ordered_member_ids,
            registration.family_registration_hash,
        )
        if metadata != expected_metadata:
            raise EvidenceValidationError(
                "scientific v2 multiplicity result differs from preregistration"
            )
        raw_pvalue = _ppm("raw_pvalue_ppm", raw["raw_pvalue_ppm"])
        adjusted_pvalue = _ppm(
            "adjusted_pvalue_ppm", raw["adjusted_pvalue_ppm"]
        )
        criterion = criterion_by_id[criterion_id]
        if metrics[criterion.claim_id][criterion.metric] != raw_pvalue:
            raise EvidenceValidationError(
                "scientific v2 raw p-value differs from its measurement metric"
            )
        try:
            expected_assessment = bonferroni_concurrent_family(
                criterion_id=criterion_id,
                family_id=registration.family_id,
                family_size=registration.family_size,
                alpha_ppm=registration.alpha_ppm,
                raw_pvalue_ppm=raw_pvalue,
            )
        except ValueError as exc:
            raise EvidenceValidationError(
                "scientific v2 multiplicity result is invalid"
            ) from exc
        if adjusted_pvalue != expected_assessment.adjusted_pvalue_ppm:
            raise EvidenceValidationError(
                "scientific v2 adjusted p-value differs from raw family adjustment"
            )
        results.append(expected_assessment)
    identities = tuple(item.criterion_id for item in results)
    if identities != tuple(sorted(registration_by_id)):
        raise EvidenceValidationError(
            "scientific v2 multiplicity results are incomplete or unordered"
        )
    return tuple(results)


def _parse_measurement(
    value: object,
    *,
    criteria: tuple[_Criterion, ...],
    profile: _Profile,
    claims: tuple[str, ...],
    proof_requirements: tuple[ProofRequirement, ...],
) -> tuple[
    dict[str, Any],
    dict[str, dict[str, int | None]],
    tuple[MultiplicityAssessment, ...],
    tuple[ProofReference, ...],
]:
    if (
        not isinstance(value, dict)
        or set(value) != _MEASUREMENT_FIELDS
        or value.get("schema") != SCIENTIFIC_MEASUREMENT_V2_SCHEMA
    ):
        raise EvidenceValidationError("scientific v2 measurement schema is invalid")
    _ascii("measurement mission_id", value["mission_id"])
    _ascii("measurement executable_id", value["executable_id"])
    _ascii("measurement job_id", value["job_id"])
    _digest("measurement job_hash", value["job_hash"])
    if value["evidence_depth"] not in {"discovery", "confirmation"}:
        raise EvidenceValidationError("scientific v2 measurement depth is invalid")
    _sorted_ascii_sequence(
        "measurement evidence modes", value["evidence_modes"], allow_empty=False
    )
    raw_metrics = value["metrics"]
    if not isinstance(raw_metrics, Mapping) or set(raw_metrics) != set(claims):
        raise EvidenceValidationError("scientific v2 measurement claims are invalid")
    expected_metrics: dict[str, set[str]] = {claim: set() for claim in claims}
    for item in criteria:
        expected_metrics[item.claim_id].add(item.metric)
    metrics: dict[str, dict[str, int | None]] = {}
    for claim in claims:
        values = raw_metrics[claim]
        if not isinstance(values, Mapping) or set(values) != expected_metrics[claim]:
            raise EvidenceValidationError(
                "scientific v2 measurement metrics differ from preregistration"
            )
        normalized: dict[str, int | None] = {}
        for metric, metric_value in values.items():
            name = _ascii("measurement metric", metric)
            if metric_value is not None and type(metric_value) is not int:
                raise EvidenceValidationError(
                    "scientific v2 metrics must be integer or null"
                )
            normalized[name] = metric_value
        metrics[claim] = normalized
    multiplicity = _parse_multiplicity_results(
        value["multiplicity"],
        registrations=profile.multiplicity,
        criteria=criteria,
        metrics=metrics,
    )
    try:
        proof_references = parse_proof_references(
            value["proofs"], requirements=proof_requirements
        )
    except ScientificEvidenceProofError as exc:
        raise EvidenceValidationError(
            "scientific v2 proof references are invalid"
        ) from exc
    return value, metrics, multiplicity, proof_references


def _parse_result(value: object) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != _RESULT_FIELDS
        or value.get("schema") != SCIENTIFIC_RESULT_SCHEMA
    ):
        raise EvidenceValidationError("scientific v2 result manifest schema is invalid")
    _ascii("result mission_id", value["mission_id"])
    _ascii("result executable_id", value["executable_id"])
    _ascii("result job_id", value["job_id"])
    _digest("result job_hash", value["job_hash"])
    if value["evidence_depth"] not in {"discovery", "confirmation"}:
        raise EvidenceValidationError("scientific v2 result depth is invalid")
    return value


_THIS_IMPLEMENTATION = Path(__file__).resolve()
_ADJUDICATION_DEPENDENCY = Path(adjudication_module.__file__).resolve()
_ANALOG_FAMILY_DEPENDENCY = Path(analog_family_module.__file__).resolve()
_ANALOG_TRACE_DEPENDENCY = Path(analog_trace_module.__file__).resolve()
_AUDIT_PROOF_DEPENDENCY = Path(audit_proof_module.__file__).resolve()
_EVIDENCE_PROOF_DEPENDENCY = Path(evidence_proof_module.__file__).resolve()
_SELECTION_INFERENCE_DEPENDENCY = Path(
    selection_inference_module.__file__
).resolve()
_SCIENTIFIC_TRACE_DEPENDENCY = Path(scientific_trace_module.__file__).resolve()
_ANALOG_SCOPED_JOB_DEPENDENCY = (
    Path(__file__).with_name("analog_state_scoped_job.py").resolve()
)
SCIENTIFIC_VALIDATION_V2_DEPENDENCIES = (
    _ADJUDICATION_DEPENDENCY,
    _ANALOG_FAMILY_DEPENDENCY,
    _ANALOG_TRACE_DEPENDENCY,
    _ANALOG_SCOPED_JOB_DEPENDENCY,
    _AUDIT_PROOF_DEPENDENCY,
    _EVIDENCE_PROOF_DEPENDENCY,
    _SELECTION_INFERENCE_DEPENDENCY,
    _SCIENTIFIC_TRACE_DEPENDENCY,
)
SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID = validator_identity(
    protocol=SCIENTIFIC_VALIDATION_V2_PROTOCOL,
    domains=SCIENTIFIC_VALIDATION_V2_DOMAINS,
    implementation_sha256=validator_implementation_sha256(
        implementation_path=_THIS_IMPLEMENTATION,
        dependency_paths=SCIENTIFIC_VALIDATION_V2_DEPENDENCIES,
    ),
)


class ScientificAdjudicationValidatorV2:
    """Validate prospective component-aware scientific evidence."""

    validator_id = SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
    domains = SCIENTIFIC_VALIDATION_V2_DOMAINS
    implementation_path = _THIS_IMPLEMENTATION
    dependency_paths = SCIENTIFIC_VALIDATION_V2_DEPENDENCIES
    protocol = SCIENTIFIC_VALIDATION_V2_PROTOCOL

    def preflight_binding(
        self, *, domain: str, binding: Mapping[str, Any]
    ) -> None:
        value = _plain(binding)
        if (
            domain != "scientific"
            or not isinstance(value, dict)
            or set(value) != _BINDING_FIELDS
            or value.get("validator_id") != self.validator_id
        ):
            raise EvidenceValidationError(
                "scientific v2 validator preflight binding is invalid"
            )
        if value["evidence_depth"] not in {"discovery", "confirmation"}:
            raise EvidenceValidationError("scientific v2 binding depth is invalid")
        _sorted_ascii_sequence(
            "binding evidence modes", value["evidence_modes"], allow_empty=False
        )
        _sorted_ascii_sequence(
            "binding planned claims", value["planned_claims"], allow_empty=False
        )
        _ascii("binding result manifest output", value["result_manifest_output"])
        _digest("binding validation_plan_hash", value["validation_plan_hash"])

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        if (
            request.domain != "scientific"
            or request.engineering_fixture
            or request.validator_id != self.validator_id
        ):
            raise EvidenceValidationError("scientific v2 request is unauthorized")
        captured = tuple(
            (artifact, artifact.read_bytes()) for artifact in request.artifacts
        )
        if len(captured) < 4:
            raise EvidenceValidationError(
                "scientific v2 requires plan, measurement, result, and proof"
            )
        parsed: list[tuple[Any, dict[str, Any]]] = []
        for artifact, content in captured:
            try:
                value = parse_canonical(content)
            except (TypeError, ValueError) as exc:
                raise EvidenceValidationError(
                    "scientific v2 artifact is not canonical"
                ) from exc
            if not isinstance(value, dict):
                raise EvidenceValidationError("scientific v2 artifact must be an object")
            parsed.append((artifact, value))

        def unique(schema: str) -> tuple[Any, dict[str, Any]]:
            matches = [item for item in parsed if item[1].get("schema") == schema]
            if len(matches) != 1:
                raise EvidenceValidationError(
                    "scientific v2 requires one artifact per schema"
                )
            return matches[0]

        plan_artifact, plan_value = unique(SCIENTIFIC_VALIDATION_PLAN_V2_SCHEMA)
        measurement_artifact, measurement_value = unique(
            SCIENTIFIC_MEASUREMENT_V2_SCHEMA
        )
        result_artifact, result_value = unique(SCIENTIFIC_RESULT_SCHEMA)
        if plan_artifact.sha256 != request.validation_plan_hash:
            raise EvidenceValidationError(
                "scientific v2 plan hash differs from request"
            )

        binding = _plain(request.binding)
        self.preflight_binding(domain=request.domain, binding=binding)
        if (
            binding["validation_plan_hash"] != request.validation_plan_hash
            or result_artifact.output_name != binding["result_manifest_output"]
        ):
            raise EvidenceValidationError("scientific v2 binding is inconsistent")
        if _plain(request.result_manifest) != result_value:
            raise EvidenceValidationError(
                "scientific v2 caller result differs from artifact"
            )
        subject = _plain(request.evidence_subject)
        if (
            not isinstance(subject, dict)
            or set(subject) != {"id", "kind"}
            or subject["kind"] != "Executable"
        ):
            raise EvidenceValidationError("scientific v2 evidence subject is invalid")
        executable_id = _ascii("evidence executable_id", subject["id"])

        plan, criteria, profile, proof_requirements = _parse_plan(plan_value)
        claims = _sorted_ascii_sequence(
            "binding planned claims", binding["planned_claims"], allow_empty=False
        )
        modes = _sorted_ascii_sequence(
            "binding evidence modes", binding["evidence_modes"], allow_empty=False
        )
        if (
            plan["mission_id"] != request.mission_id
            or plan["executable_id"] != executable_id
            or plan["evidence_depth"] != binding["evidence_depth"]
            or tuple(plan["planned_claims"]) != claims
            or tuple(plan["evidence_modes"]) != modes
        ):
            raise EvidenceValidationError("scientific v2 plan differs from binding")

        measurement, metrics, multiplicity, proof_references = _parse_measurement(
            measurement_value,
            criteria=criteria,
            profile=profile,
            claims=claims,
            proof_requirements=proof_requirements,
        )
        if (
            measurement["mission_id"] != request.mission_id
            or measurement["executable_id"] != executable_id
            or measurement["job_id"] != request.job_id
            or measurement["job_hash"] != request.job_hash
            or measurement["evidence_depth"] != binding["evidence_depth"]
            or tuple(measurement["evidence_modes"]) != modes
        ):
            raise EvidenceValidationError(
                "scientific v2 measurement belongs to another execution"
            )

        result = _parse_result(result_value)
        if (
            result["mission_id"] != request.mission_id
            or result["executable_id"] != executable_id
            or result["job_id"] != request.job_id
            or result["job_hash"] != request.job_hash
            or result["evidence_depth"] != binding["evidence_depth"]
        ):
            raise EvidenceValidationError(
                "scientific v2 result belongs to another execution"
            )
        observations = result["observations"]
        if not isinstance(observations, list) or len(observations) != len(claims):
            raise EvidenceValidationError("scientific v2 observations are invalid")
        observed_claims: list[str] = []
        for observation in observations:
            if not isinstance(observation, dict) or set(observation) != {
                "claim_id",
                "measurement_artifact_hash",
            }:
                raise EvidenceValidationError(
                    "scientific v2 observation schema is invalid"
                )
            observed_claims.append(
                _ascii("observation claim_id", observation["claim_id"])
            )
            if observation["measurement_artifact_hash"] != measurement_artifact.sha256:
                raise EvidenceValidationError(
                    "scientific v2 observation is not measurement-bound"
                )
        if tuple(observed_claims) != claims:
            raise EvidenceValidationError(
                "scientific v2 observations differ from preregistration"
            )

        output_names = tuple(artifact.output_name for artifact, _ in parsed)
        if len(set(output_names)) != len(output_names):
            raise EvidenceValidationError(
                "scientific v2 artifact output names must be unique"
            )
        core_outputs = {
            plan_artifact.output_name,
            measurement_artifact.output_name,
            result_artifact.output_name,
        }
        proof_values = {
            artifact.output_name: value
            for artifact, value in parsed
            if artifact.output_name not in core_outputs
        }
        proof_hashes = {
            artifact.output_name: artifact.sha256
            for artifact, _ in parsed
            if artifact.output_name not in core_outputs
        }
        expected_bindings: dict[str, list[dict[str, object]]] = {
            mode: [] for mode in modes
        }
        for criterion in criteria:
            expected_bindings[criterion.evidence_mode].append(
                {
                    "claim_id": criterion.claim_id,
                    "metric": criterion.metric,
                    "value": metrics[criterion.claim_id][criterion.metric],
                }
            )
        normalized_bindings = {
            mode: tuple(
                sorted(
                    values,
                    key=lambda item: (str(item["claim_id"]), str(item["metric"])),
                )
            )
            for mode, values in expected_bindings.items()
        }
        try:
            demonstrated_modes = validate_proof_artifacts(
                requirements=proof_requirements,
                references=proof_references,
                artifacts=proof_values,
                artifact_hashes=proof_hashes,
                expected_metric_bindings_by_mode=normalized_bindings,
                mission_id=request.mission_id,
                executable_id=executable_id,
                job_id=request.job_id,
                job_hash=request.job_hash,
            )
        except ScientificEvidenceProofError as exc:
            raise EvidenceValidationError(
                "scientific v2 evidence-mode proof validation failed"
            ) from exc
        if demonstrated_modes != modes:
            raise EvidenceValidationError(
                "scientific v2 demonstrated modes differ from preregistration"
            )

        try:
            adjudication_profile = AdjudicationProfile(
                decisive_risk_criterion_ids=frozenset(
                    profile.decisive_risk_criterion_ids
                ),
                multiplicity=multiplicity,
            )
            adjudication = adjudicate_plan_measurement(
                plan,
                {"metrics": metrics},
                profile=adjudication_profile,
            )
        except ValueError as exc:
            raise EvidenceValidationError(
                "scientific v2 adjudication input is invalid"
            ) from exc
        # The writer has a legacy three-state surface.  Preserve partial
        # positives as non-terminal evidence; only exact contradiction is a
        # coarse scientific failure.
        if adjudication.state in {"frontier", "confirmed"}:
            verdict = "passed"
        elif adjudication.state == "contradicted":
            verdict = "failed"
        else:
            verdict = "not_evaluable"
        criterion_states = {item.criterion_id: item.state for item in adjudication.criteria}
        promotions_passed = bool(profile.promotion_criterion_ids) and all(
            criterion_states[item] == "passed"
            for item in profile.promotion_criterion_ids
        )
        candidate_eligible = bool(
            adjudication.candidate_eligible and promotions_passed
        )
        for artifact, _ in captured:
            artifact.require_source_unchanged()
        return ValidatedEvidence(
            verdict=verdict,
            claims=claims,
            measurement_artifact_hashes=(measurement_artifact.sha256,),
            facts={
                "executed_evidence_modes": list(demonstrated_modes),
                "scientific_adjudication": scientific_adjudication_manifest(
                    adjudication
                ),
            },
            scientific_eligible=True,
            candidate_eligible=candidate_eligible,
            release_eligible=False,
        )


__all__ = [
    "SCIENTIFIC_ADJUDICATION_PROFILE_SCHEMA",
    "SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID",
    "SCIENTIFIC_MEASUREMENT_V2_SCHEMA",
    "SCIENTIFIC_RESULT_SCHEMA",
    "SCIENTIFIC_VALIDATION_PLAN_V2_SCHEMA",
    "SCIENTIFIC_VALIDATION_V2_DEPENDENCIES",
    "SCIENTIFIC_VALIDATION_V2_DOMAINS",
    "SCIENTIFIC_VALIDATION_V2_PROTOCOL",
    "SCIENTIFIC_V2_CRITERION_OPERATORS",
    "SCIENTIFIC_V2_DECISION_ROLES",
    "SCIENTIFIC_V2_MULTIPLICITY_METHOD",
    "ScientificAdjudicationValidatorV2",
    "build_validation_plan_v2",
    "multiplicity_family_registration_hash",
]
