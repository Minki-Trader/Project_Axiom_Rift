"""Pure scientific adjudication and concurrent-family multiplicity.

This module separates four questions that legacy noncompensatory verdicts
collapsed into one string:

* whether the evidence is valid and evaluable;
* which discovery components are supported, contradicted, or unresolved;
* whether a risk criterion is a decision gate or only a diagnostic; and
* whether explicit confirmation can authorize candidate eligibility.

The concurrent-family API deliberately has no project-history exposure input.
Unrelated historical trials therefore cannot change a registered family's
adjustment.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal


PER_MILLION = 1_000_000

VALIDITY_METRICS = frozenset(
    {
        "append_invariance_mismatch_count",
        "causality_violation_count",
        "nonfinite_metric_count",
        "prefix_invariance_mismatch_count",
        "unknown_cost_unresolved_signal_count",
    }
)
RISK_DIAGNOSTIC_CRITERION_IDS = frozenset(
    {"B04-monthly-realized-drawdown-share"}
)
MULTIPLICITY_CRITERION_IDS = frozenset(
    {
        "D02-opposite-sign-uncertainty",
        "D04-primary-control-uncertainty",
        "E01-familywise-selection",
    }
)

CriterionComparisonState = Literal["passed", "failed", "unavailable"]
# Backward-compatible type name for callers that treated the criterion state as
# the raw threshold comparison.  New code should use CriterionComparisonState.
CriterionState = CriterionComparisonState
CriterionScientificState = Literal[
    "supported",
    "contradicted",
    "unresolved",
    "invalid",
    "diagnostic",
]
DecisionRole = Literal[
    "validity",
    "component",
    "risk_gate",
    "risk_diagnostic",
    "multiplicity",
]
ClaimState = Literal["supported", "contradicted", "unresolved"]
AdjudicationState = Literal[
    "not_evaluable",
    "contradicted",
    "unresolved",
    "partial_positive",
    "frontier",
    "confirmed",
]


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _ppm(name: str, value: object, *, allow_zero: bool = True) -> int:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or not minimum <= value <= PER_MILLION:
        raise ValueError(f"{name} must be an integer in [{minimum}, {PER_MILLION}]")
    return value


def criterion_passed(*, value: int, operator: str, threshold: int) -> bool:
    """Evaluate one integer criterion without caller-supplied verdict state."""

    if type(value) is not int or type(threshold) is not int:
        raise ValueError("criterion value and threshold must be integers")
    comparisons = {
        "eq": value == threshold,
        "ge": value >= threshold,
        "gt": value > threshold,
        "le": value <= threshold,
        "lt": value < threshold,
    }
    if operator not in comparisons:
        raise ValueError("criterion operator is invalid")
    return comparisons[operator]


@dataclass(frozen=True, slots=True)
class MultiplicityAssessment:
    """One preregistered, concurrently compared hypothesis family."""

    criterion_id: str
    family_id: str
    family_size: int
    raw_pvalue_ppm: int
    adjusted_pvalue_ppm: int
    alpha_ppm: int
    method: str

    def __post_init__(self) -> None:
        _ascii("multiplicity criterion_id", self.criterion_id)
        _ascii("multiplicity family_id", self.family_id)
        _ascii("multiplicity method", self.method)
        if type(self.family_size) is not int or self.family_size < 1:
            raise ValueError("multiplicity family_size must be a positive integer")
        _ppm("raw_pvalue_ppm", self.raw_pvalue_ppm)
        _ppm("adjusted_pvalue_ppm", self.adjusted_pvalue_ppm)
        _ppm("alpha_ppm", self.alpha_ppm, allow_zero=False)
        if self.adjusted_pvalue_ppm < self.raw_pvalue_ppm:
            raise ValueError("adjusted p-value cannot be smaller than raw p-value")

    @property
    def passed(self) -> bool:
        return self.adjusted_pvalue_ppm <= self.alpha_ppm

    def manifest(self) -> dict[str, str | int]:
        return {
            "adjusted_pvalue_ppm": self.adjusted_pvalue_ppm,
            "alpha_ppm": self.alpha_ppm,
            "criterion_id": self.criterion_id,
            "family_id": self.family_id,
            "family_size": self.family_size,
            "method": self.method,
            "raw_pvalue_ppm": self.raw_pvalue_ppm,
        }


def bonferroni_concurrent_family(
    *,
    criterion_id: str,
    family_id: str,
    family_size: int,
    raw_pvalue_ppm: int,
    alpha_ppm: int,
) -> MultiplicityAssessment:
    """Adjust within one explicit concurrent family, never project history."""

    if type(family_size) is not int or family_size < 1:
        raise ValueError("multiplicity family_size must be a positive integer")
    raw = _ppm("raw_pvalue_ppm", raw_pvalue_ppm)
    adjusted = min(PER_MILLION, raw * family_size)
    return MultiplicityAssessment(
        adjusted_pvalue_ppm=adjusted,
        alpha_ppm=alpha_ppm,
        criterion_id=criterion_id,
        family_id=family_id,
        family_size=family_size,
        method="bonferroni_concurrent_family.v1",
        raw_pvalue_ppm=raw,
    )


@dataclass(frozen=True, slots=True)
class AdjudicationProfile:
    """Prospective decision roles that do not alter legacy evidence schemas."""

    decisive_risk_criterion_ids: frozenset[str] = frozenset()
    multiplicity: tuple[MultiplicityAssessment, ...] = ()

    def __post_init__(self) -> None:
        for criterion_id in self.decisive_risk_criterion_ids:
            _ascii("decisive risk criterion_id", criterion_id)
        unknown = self.decisive_risk_criterion_ids - RISK_DIAGNOSTIC_CRITERION_IDS
        if unknown:
            raise ValueError("decisive risk criteria are not registered diagnostics")
        identities = [item.criterion_id for item in self.multiplicity]
        if len(identities) != len(set(identities)):
            raise ValueError("multiplicity criterion assessments must be unique")
        if set(identities) - MULTIPLICITY_CRITERION_IDS:
            raise ValueError("multiplicity assessments use unregistered criteria")

    def multiplicity_by_criterion(self) -> dict[str, MultiplicityAssessment]:
        return {item.criterion_id: item for item in self.multiplicity}


@dataclass(frozen=True, slots=True)
class CriterionAdjudication:
    claim_id: str
    criterion_id: str
    decision_role: DecisionRole
    metric: str
    operator: str
    state: CriterionComparisonState
    threshold: int
    value: int | None

    def __post_init__(self) -> None:
        if self.state not in {"passed", "failed", "unavailable"}:
            raise ValueError("criterion comparison state is invalid")
        if self.decision_role not in {
            "validity",
            "component",
            "risk_gate",
            "risk_diagnostic",
            "multiplicity",
        }:
            raise ValueError("criterion decision role is invalid")

    @property
    def comparison_state(self) -> CriterionComparisonState:
        """Name the legacy state explicitly as a threshold comparison."""

        return self.state

    @property
    def scientific_state(self) -> CriterionScientificState:
        """Interpret the comparison without collapsing scientific meaning."""

        if self.decision_role == "risk_diagnostic":
            return "diagnostic"
        if self.decision_role == "validity":
            return "supported" if self.state == "passed" else "invalid"
        if self.state == "passed":
            return "supported"
        if self.state == "failed":
            return "contradicted"
        return "unresolved"


@dataclass(frozen=True, slots=True)
class ClaimAdjudication:
    claim_id: str
    state: ClaimState
    decisive_criterion_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScientificAdjudication:
    """Typed result that preserves partial information and stage boundaries."""

    evidence_depth: str
    state: AdjudicationState
    legacy_verdict: str
    evaluable: bool
    candidate_eligible: bool
    invalid_metrics: tuple[str, ...]
    criteria: tuple[CriterionAdjudication, ...]
    claims: tuple[ClaimAdjudication, ...]
    multiplicity: tuple[MultiplicityAssessment, ...]

    @property
    def risk_diagnostics(self) -> tuple[CriterionAdjudication, ...]:
        return tuple(
            item for item in self.criteria if item.decision_role == "risk_diagnostic"
        )


def scientific_adjudication_manifest(
    adjudication: ScientificAdjudication,
) -> dict[str, object]:
    """Project one rich adjudication without collapsing claim information."""

    if not isinstance(adjudication, ScientificAdjudication):
        raise TypeError("adjudication must be a ScientificAdjudication")
    return {
        "candidate_eligible": adjudication.candidate_eligible,
        "claims": [
            {
                "claim_id": item.claim_id,
                "decisive_criterion_ids": list(item.decisive_criterion_ids),
                "state": item.state,
            }
            for item in adjudication.claims
        ],
        "criteria": [
            {
                "claim_id": item.claim_id,
                "criterion_id": item.criterion_id,
                "comparison_state": item.comparison_state,
                "decision_role": item.decision_role,
                "metric": item.metric,
                "operator": item.operator,
                "state": item.state,
                "scientific_state": item.scientific_state,
                "threshold": item.threshold,
                "value": item.value,
            }
            for item in adjudication.criteria
        ],
        "evaluable": adjudication.evaluable,
        "evidence_depth": adjudication.evidence_depth,
        "invalid_metrics": list(adjudication.invalid_metrics),
        "legacy_verdict": adjudication.legacy_verdict,
        "multiplicity": [
            item.manifest()
            for item in sorted(
                adjudication.multiplicity,
                key=lambda value: (value.criterion_id, value.family_id),
            )
        ],
        "schema": "scientific_adjudication.v1",
        "state": adjudication.state,
    }


def candidate_eligible_for(
    *,
    evidence_depth: str,
    passed: bool,
    candidate_eligible_on_pass: bool,
) -> bool:
    """Keep candidate authority behind explicit passing confirmation only."""

    if evidence_depth not in {"discovery", "confirmation"}:
        raise ValueError("scientific evidence depth is invalid")
    if type(passed) is not bool or type(candidate_eligible_on_pass) is not bool:
        raise ValueError("candidate eligibility inputs must be boolean")
    return bool(
        evidence_depth == "confirmation"
        and passed
        and candidate_eligible_on_pass
    )


def _criterion_value(
    criterion: Mapping[str, object],
    metrics: Mapping[str, Mapping[str, int | None]],
) -> int | None:
    claim_id = str(criterion["claim_id"])
    metric = str(criterion["metric"])
    claim_metrics = metrics.get(claim_id)
    if claim_metrics is None or metric not in claim_metrics:
        return None
    return claim_metrics[metric]


def _invalid_metrics(
    metrics: Mapping[str, Mapping[str, int | None]],
) -> tuple[str, ...]:
    invalid: set[str] = set()
    for claim_metrics in metrics.values():
        for metric, value in claim_metrics.items():
            if metric in VALIDITY_METRICS and value != 0:
                invalid.add(metric)
    return tuple(sorted(invalid))


def _legacy_compatibility_verdict(
    criteria: Sequence[Mapping[str, object]],
    metrics: Mapping[str, Mapping[str, int | None]],
) -> str:
    """Project the rich input onto v1 semantics without trusting new roles."""

    unavailable = False
    failed = False
    for criterion in criteria:
        claim_id = str(criterion["claim_id"])
        metric = str(criterion["metric"])
        claim_metrics = metrics.get(claim_id)
        if claim_metrics is None or metric not in claim_metrics:
            unavailable = True
            continue
        value = claim_metrics[metric]
        if value is None:
            unavailable = True
            continue
        threshold = criterion["threshold"]
        if type(threshold) is not int:
            raise ValueError("criterion threshold must be an integer")
        if not criterion_passed(
            value=value,
            operator=str(criterion["operator"]),
            threshold=threshold,
        ):
            failed = True
    return "not_evaluable" if unavailable else "failed" if failed else "passed"


def _criterion_role(
    criterion_id: str,
    metric: str,
    profile: AdjudicationProfile,
) -> DecisionRole:
    if metric in VALIDITY_METRICS:
        return "validity"
    if criterion_id in MULTIPLICITY_CRITERION_IDS:
        return "multiplicity"
    if criterion_id in RISK_DIAGNOSTIC_CRITERION_IDS:
        if criterion_id in profile.decisive_risk_criterion_ids:
            return "risk_gate"
        return "risk_diagnostic"
    return "component"


def _criterion_adjudication(
    criterion: Mapping[str, object],
    metrics: Mapping[str, Mapping[str, int | None]],
    profile: AdjudicationProfile,
    multiplicity: Mapping[str, MultiplicityAssessment],
) -> CriterionAdjudication:
    claim_id = _ascii("criterion claim_id", criterion.get("claim_id"))
    criterion_id = _ascii("criterion_id", criterion.get("criterion_id"))
    metric = _ascii("criterion metric", criterion.get("metric"))
    operator = _ascii("criterion operator", criterion.get("operator"))
    threshold = criterion.get("threshold")
    if type(threshold) is not int:
        raise ValueError("criterion threshold must be an integer")
    role = _criterion_role(criterion_id, metric, profile)
    value = _criterion_value(criterion, metrics)
    effective_operator = operator
    effective_threshold = threshold
    if role == "multiplicity":
        assessment = multiplicity.get(criterion_id)
        if assessment is None:
            value = None
        else:
            value = assessment.adjusted_pvalue_ppm
            effective_operator = "le"
            effective_threshold = assessment.alpha_ppm
    if value is None:
        comparison_state: CriterionComparisonState = "unavailable"
    elif criterion_passed(
        value=value,
        operator=effective_operator,
        threshold=effective_threshold,
    ):
        comparison_state = "passed"
    else:
        comparison_state = "failed"
    return CriterionAdjudication(
        claim_id=claim_id,
        criterion_id=criterion_id,
        decision_role=role,
        metric=metric,
        operator=effective_operator,
        state=comparison_state,
        threshold=effective_threshold,
        value=value,
    )


def _claim_adjudications(
    planned_claims: Sequence[str],
    criteria: Sequence[CriterionAdjudication],
) -> tuple[ClaimAdjudication, ...]:
    results: list[ClaimAdjudication] = []
    for claim_id in planned_claims:
        decisive = tuple(
            item
            for item in criteria
            if item.claim_id == claim_id
            and item.decision_role not in {"validity", "risk_diagnostic"}
        )
        validity = tuple(
            item
            for item in criteria
            if item.claim_id == claim_id and item.decision_role == "validity"
        )
        state: ClaimState
        if any(item.scientific_state == "invalid" for item in validity):
            state = "unresolved"
        elif not decisive and validity and all(
            item.scientific_state == "supported" for item in validity
        ):
            state = "supported"
        elif not decisive or any(
            item.scientific_state == "unresolved" for item in decisive
        ):
            state = "unresolved"
        elif any(item.scientific_state == "contradicted" for item in decisive):
            state = "contradicted"
        else:
            state = "supported"
        results.append(
            ClaimAdjudication(
                claim_id=claim_id,
                state=state,
                decisive_criterion_ids=tuple(item.criterion_id for item in decisive),
            )
        )
    return tuple(results)


def adjudicate_plan_measurement(
    plan: Mapping[str, Any],
    measurement: Mapping[str, Any],
    *,
    profile: AdjudicationProfile | None = None,
) -> ScientificAdjudication:
    """Adjudicate a plan and measurement without mutating durable evidence."""

    decision_profile = AdjudicationProfile() if profile is None else profile
    evidence_depth = _ascii("evidence_depth", plan.get("evidence_depth"))
    if evidence_depth not in {"discovery", "confirmation"}:
        raise ValueError("scientific evidence depth is invalid")
    candidate_policy = plan.get("candidate_eligible_on_pass", False)
    if type(candidate_policy) is not bool:
        raise ValueError("candidate policy must be boolean")
    raw_claims = plan.get("planned_claims")
    raw_criteria = plan.get("criteria")
    raw_metrics = measurement.get("metrics")
    if (
        not isinstance(raw_claims, (list, tuple))
        or not raw_claims
        or not isinstance(raw_criteria, (list, tuple))
        or not raw_criteria
        or not isinstance(raw_metrics, Mapping)
    ):
        raise ValueError("scientific plan or measurement is incomplete")
    planned_claims = tuple(_ascii("planned claim", item) for item in raw_claims)
    metrics: dict[str, Mapping[str, int | None]] = {}
    for claim_id, values in raw_metrics.items():
        claim = _ascii("measurement claim", claim_id)
        if not isinstance(values, Mapping):
            raise ValueError("scientific claim metrics must be mappings")
        normalized: dict[str, int | None] = {}
        for metric, value in values.items():
            name = _ascii("measurement metric", metric)
            if value is not None and type(value) is not int:
                raise ValueError("scientific metrics must be integer or null")
            normalized[name] = value
        metrics[claim] = normalized
    multiplicity = decision_profile.multiplicity_by_criterion()
    criterion_results = tuple(
        _criterion_adjudication(item, metrics, decision_profile, multiplicity)
        for item in raw_criteria
        if isinstance(item, Mapping)
    )
    if len(criterion_results) != len(raw_criteria):
        raise ValueError("scientific criteria must be mappings")
    invalid = tuple(
        sorted(
            set(_invalid_metrics(metrics))
            | {
                item.metric
                for item in criterion_results
                if item.decision_role == "validity"
                and item.scientific_state == "invalid"
            }
        )
    )
    claim_results = _claim_adjudications(planned_claims, criterion_results)
    if invalid:
        state: AdjudicationState = "not_evaluable"
    else:
        decision_claims = tuple(
            item for item in claim_results if item.decisive_criterion_ids
        )
        supported = sum(item.state == "supported" for item in decision_claims)
        unresolved = sum(item.state == "unresolved" for item in decision_claims)
        if decision_claims and supported == len(decision_claims):
            state = "confirmed" if evidence_depth == "confirmation" else "frontier"
        elif supported:
            state = "partial_positive"
        elif unresolved:
            state = "unresolved"
        else:
            state = "contradicted"
    passed = state in {"frontier", "confirmed"}
    eligible = candidate_eligible_for(
        evidence_depth=evidence_depth,
        passed=passed,
        candidate_eligible_on_pass=candidate_policy,
    )
    legacy_verdict = _legacy_compatibility_verdict(raw_criteria, metrics)
    return ScientificAdjudication(
        evidence_depth=evidence_depth,
        state=state,
        legacy_verdict=legacy_verdict,
        evaluable=not invalid,
        candidate_eligible=eligible,
        invalid_metrics=invalid,
        criteria=criterion_results,
        claims=claim_results,
        multiplicity=decision_profile.multiplicity,
    )


def legacy_noncompensatory_verdict(
    criteria: Sequence[Mapping[str, object]],
    metrics: Mapping[str, Mapping[str, int | None]],
) -> str:
    """Preserve the exact v1 all-criteria verdict for historical evidence."""

    unavailable = False
    failed = False
    comparisons = {
        "eq": lambda value, threshold: value == threshold,
        "ge": lambda value, threshold: value >= threshold,
        "gt": lambda value, threshold: value > threshold,
        "le": lambda value, threshold: value <= threshold,
        "lt": lambda value, threshold: value < threshold,
    }
    for criterion in criteria:
        claim_id = str(criterion["claim_id"])
        metric = str(criterion["metric"])
        value = metrics[claim_id][metric]
        if value is None:
            unavailable = True
            continue
        if not comparisons[str(criterion["operator"])](
            value, criterion["threshold"]
        ):
            failed = True
    return "not_evaluable" if unavailable else "failed" if failed else "passed"


__all__ = [
    "AdjudicationProfile",
    "ClaimAdjudication",
    "CriterionAdjudication",
    "CriterionComparisonState",
    "CriterionScientificState",
    "CriterionState",
    "MULTIPLICITY_CRITERION_IDS",
    "MultiplicityAssessment",
    "PER_MILLION",
    "RISK_DIAGNOSTIC_CRITERION_IDS",
    "ScientificAdjudication",
    "VALIDITY_METRICS",
    "adjudicate_plan_measurement",
    "bonferroni_concurrent_family",
    "candidate_eligible_for",
    "criterion_passed",
    "legacy_noncompensatory_verdict",
    "scientific_adjudication_manifest",
]
