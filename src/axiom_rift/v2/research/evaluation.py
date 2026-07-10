"""Pure, non-compensatory KPI interpretation for V2 research stages.

The evaluator does not invent acceptance thresholds, mutate state, or combine
unrelated KPIs into a weighted score.  A preregistered profile supplies the
metric rules.  The evaluator classifies every registered metric, collapses the
classifications by dimension, and selects one deterministic next route.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from numbers import Real
from typing import Any, Iterable, Mapping


class KpiEvaluationError(ValueError):
    """Raised when an evaluation profile or invocation is inconsistent."""


class Stage(str, Enum):
    H = "H"
    S = "S"
    R = "R"
    P = "P"
    M = "M"


class ObservationStatus(str, Enum):
    OBSERVED = "observed"
    CENSORED = "censored"
    NOT_EVALUABLE = "not_evaluable"
    NOT_SCHEDULED = "not_scheduled"
    NOT_APPLICABLE = "not_applicable"
    MISSING = "missing"
    NOT_REQUIRED = "not_required"
    INVALID = "invalid"


class VerdictStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    CENSORED = "censored"
    NOT_EVALUABLE = "not_evaluable"
    NOT_SCHEDULED = "not_scheduled"
    NOT_APPLICABLE = "not_applicable"
    MISSING = "missing"
    NOT_REQUIRED = "not_required"
    INVALID = "invalid"


class Comparison(str, Enum):
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    RANGE = "range"
    EQUAL = "equal"


class FailureEffect(str, Enum):
    REPAIR = "repair"
    REJECT = "reject"
    DIAGNOSTIC = "diagnostic"
    EVIDENCE_GAP = "evidence_gap"


class TuningRole(str, Enum):
    NONE = "none"
    SENSITIVITY_ONLY = "sensitivity_only"
    CALIBRATABLE = "calibratable"


class SensitivityState(str, Enum):
    NOT_ASSESSED = "not_assessed"
    PENDING = "pending"
    PLATEAU = "plateau"
    COHERENT_SLOPE = "coherent_slope"
    NEEDLE = "needle"
    EDGE_HIT = "edge_hit"
    BOUNDARY_TREND = "boundary_trend"
    UNSTABLE = "unstable"
    WEAK = "weak"
    INCONCLUSIVE = "inconclusive"
    NOT_REQUIRED = "not_required"


STANDARD_DIMENSIONS = (
    "integrity",
    "inferential_density",
    "activity",
    "economics",
    "risk",
    "stability",
    "execution",
    "portfolio_fit",
)

PASS_ROUTE = {
    Stage.H: "hypothesis_ready",
    Stage.S: "route_to_R",
    Stage.R: "route_to_P",
    Stage.P: "route_to_M",
    Stage.M: "materialization_complete",
}

REJECT_ROUTE = {
    Stage.H: "hypothesis_rejected",
    Stage.S: "scout_rejected",
    Stage.R: "confirmation_rejected",
    Stage.P: "promotion_rejected",
    Stage.M: "materialization_rejected",
}


def _stages(
    values: Iterable[Stage | str], *, allow_empty: bool = False
) -> frozenset[Stage]:
    try:
        result = frozenset(Stage(value) for value in values)
    except ValueError as exc:
        raise KpiEvaluationError(f"unknown V2 stage: {exc}") from exc
    if not result and not allow_empty:
        raise KpiEvaluationError("a metric rule must apply to at least one stage")
    return result


@dataclass(frozen=True)
class MetricObservation:
    status: ObservationStatus
    value: Any = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ObservationStatus):
            raise KpiEvaluationError("metric observation has an invalid status")

    @classmethod
    def observed(cls, value: Any) -> "MetricObservation":
        return cls(ObservationStatus.OBSERVED, value=value)

    @classmethod
    def missing(cls, reason: str | None = None) -> "MetricObservation":
        return cls(ObservationStatus.MISSING, reason=reason)

    @classmethod
    def censored(cls, reason: str | None = None) -> "MetricObservation":
        return cls(ObservationStatus.CENSORED, reason=reason)

    @classmethod
    def not_evaluable(cls, reason: str | None = None) -> "MetricObservation":
        return cls(ObservationStatus.NOT_EVALUABLE, reason=reason)

    @classmethod
    def not_scheduled(cls, reason: str | None = None) -> "MetricObservation":
        return cls(ObservationStatus.NOT_SCHEDULED, reason=reason)

    @classmethod
    def not_applicable(cls, reason: str | None = None) -> "MetricObservation":
        return cls(ObservationStatus.NOT_APPLICABLE, reason=reason)

    @classmethod
    def not_required(cls, reason: str | None = None) -> "MetricObservation":
        return cls(ObservationStatus.NOT_REQUIRED, reason=reason)

    @classmethod
    def invalid(cls, reason: str) -> "MetricObservation":
        return cls(ObservationStatus.INVALID, reason=reason)


@dataclass(frozen=True)
class MetricRule:
    name: str
    dimension: str
    comparison: Comparison
    applicable_stages: frozenset[Stage]
    required_stages: frozenset[Stage]
    pass_min: float | None = None
    pass_max: float | None = None
    hard_min: float | None = None
    hard_max: float | None = None
    expected: Any = None
    failure_effect: FailureEffect = FailureEffect.REJECT
    tuning_role: TuningRole = TuningRole.NONE

    def __post_init__(self) -> None:
        if not self.name or not self.dimension:
            raise KpiEvaluationError("metric name and dimension must be non-empty")
        if not isinstance(self.comparison, Comparison):
            raise KpiEvaluationError(f"metric {self.name} has an invalid comparison")
        if not all(isinstance(stage, Stage) for stage in self.applicable_stages):
            raise KpiEvaluationError(f"metric {self.name} has invalid applicable stages")
        if not all(isinstance(stage, Stage) for stage in self.required_stages):
            raise KpiEvaluationError(f"metric {self.name} has invalid required stages")
        if not self.required_stages.issubset(self.applicable_stages):
            raise KpiEvaluationError(
                f"required stages are not applicable for metric {self.name}"
            )
        if not isinstance(self.failure_effect, FailureEffect):
            raise KpiEvaluationError(f"metric {self.name} has an invalid failure effect")
        if not isinstance(self.tuning_role, TuningRole):
            raise KpiEvaluationError(f"metric {self.name} has an invalid tuning role")
        for threshold in (self.pass_min, self.pass_max, self.hard_min, self.hard_max):
            if threshold is not None and not math.isfinite(threshold):
                raise KpiEvaluationError(f"metric {self.name} has a non-finite threshold")
        if self.comparison is Comparison.MINIMUM:
            if self.pass_min is None:
                raise KpiEvaluationError(f"minimum rule {self.name} lacks pass_min")
            if self.hard_min is not None and self.hard_min > self.pass_min:
                raise KpiEvaluationError(
                    f"minimum rule {self.name} has hard_min above pass_min"
                )
        elif self.comparison is Comparison.MAXIMUM:
            if self.pass_max is None:
                raise KpiEvaluationError(f"maximum rule {self.name} lacks pass_max")
            if self.hard_max is not None and self.hard_max < self.pass_max:
                raise KpiEvaluationError(
                    f"maximum rule {self.name} has hard_max below pass_max"
                )
        elif self.comparison is Comparison.RANGE:
            if self.pass_min is None or self.pass_max is None:
                raise KpiEvaluationError(f"range rule {self.name} lacks a pass band")
            if self.pass_min > self.pass_max:
                raise KpiEvaluationError(f"range rule {self.name} has an inverted pass band")
            if self.hard_min is not None and self.hard_min > self.pass_min:
                raise KpiEvaluationError(f"range rule {self.name} has an invalid hard_min")
            if self.hard_max is not None and self.hard_max < self.pass_max:
                raise KpiEvaluationError(f"range rule {self.name} has an invalid hard_max")
        elif self.comparison is Comparison.EQUAL:
            if self.expected is None:
                raise KpiEvaluationError(f"equal rule {self.name} cannot expect None")
            if isinstance(self.expected, float) and not math.isfinite(self.expected):
                raise KpiEvaluationError(f"equal rule {self.name} has non-finite expected value")

    @classmethod
    def minimum(
        cls,
        name: str,
        dimension: str,
        *,
        stages: Iterable[Stage | str],
        pass_at: float,
        fail_below: float | None = None,
        required_stages: Iterable[Stage | str] | None = None,
        failure_effect: FailureEffect = FailureEffect.REJECT,
        tuning_role: TuningRole = TuningRole.NONE,
    ) -> "MetricRule":
        applicable = _stages(stages)
        required = (
            applicable
            if required_stages is None
            else _stages(required_stages, allow_empty=True)
        )
        return cls(
            name=name,
            dimension=dimension,
            comparison=Comparison.MINIMUM,
            applicable_stages=applicable,
            required_stages=required,
            pass_min=float(pass_at),
            hard_min=None if fail_below is None else float(fail_below),
            failure_effect=failure_effect,
            tuning_role=tuning_role,
        )

    @classmethod
    def maximum(
        cls,
        name: str,
        dimension: str,
        *,
        stages: Iterable[Stage | str],
        pass_at: float,
        fail_above: float | None = None,
        required_stages: Iterable[Stage | str] | None = None,
        failure_effect: FailureEffect = FailureEffect.REJECT,
        tuning_role: TuningRole = TuningRole.NONE,
    ) -> "MetricRule":
        applicable = _stages(stages)
        required = (
            applicable
            if required_stages is None
            else _stages(required_stages, allow_empty=True)
        )
        return cls(
            name=name,
            dimension=dimension,
            comparison=Comparison.MAXIMUM,
            applicable_stages=applicable,
            required_stages=required,
            pass_max=float(pass_at),
            hard_max=None if fail_above is None else float(fail_above),
            failure_effect=failure_effect,
            tuning_role=tuning_role,
        )

    @classmethod
    def range(
        cls,
        name: str,
        dimension: str,
        *,
        stages: Iterable[Stage | str],
        pass_min: float,
        pass_max: float,
        fail_below: float | None = None,
        fail_above: float | None = None,
        required_stages: Iterable[Stage | str] | None = None,
        failure_effect: FailureEffect = FailureEffect.REJECT,
        tuning_role: TuningRole = TuningRole.NONE,
    ) -> "MetricRule":
        applicable = _stages(stages)
        required = (
            applicable
            if required_stages is None
            else _stages(required_stages, allow_empty=True)
        )
        return cls(
            name=name,
            dimension=dimension,
            comparison=Comparison.RANGE,
            applicable_stages=applicable,
            required_stages=required,
            pass_min=float(pass_min),
            pass_max=float(pass_max),
            hard_min=None if fail_below is None else float(fail_below),
            hard_max=None if fail_above is None else float(fail_above),
            failure_effect=failure_effect,
            tuning_role=tuning_role,
        )

    @classmethod
    def equal(
        cls,
        name: str,
        dimension: str,
        *,
        stages: Iterable[Stage | str],
        expected: Any,
        required_stages: Iterable[Stage | str] | None = None,
        failure_effect: FailureEffect = FailureEffect.REJECT,
        tuning_role: TuningRole = TuningRole.NONE,
    ) -> "MetricRule":
        applicable = _stages(stages)
        required = (
            applicable
            if required_stages is None
            else _stages(required_stages, allow_empty=True)
        )
        return cls(
            name=name,
            dimension=dimension,
            comparison=Comparison.EQUAL,
            applicable_stages=applicable,
            required_stages=required,
            expected=expected,
            failure_effect=failure_effect,
            tuning_role=tuning_role,
        )


@dataclass(frozen=True)
class EvaluationProfile:
    profile_id: str
    rules: tuple[MetricRule, ...]
    dimension_order: tuple[str, ...] = STANDARD_DIMENSIONS
    require_sensitivity_for_tunable_warnings: bool = True

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise KpiEvaluationError("profile_id must be non-empty")
        if not isinstance(self.rules, tuple):
            raise KpiEvaluationError("evaluation profile rules must be an immutable tuple")
        if not all(isinstance(rule, MetricRule) for rule in self.rules):
            raise KpiEvaluationError("evaluation profile contains an invalid metric rule")
        names = [rule.name for rule in self.rules]
        if len(names) != len(set(names)):
            raise KpiEvaluationError("evaluation profile has duplicate metric names")
        if len(self.dimension_order) != len(set(self.dimension_order)):
            raise KpiEvaluationError("dimension_order contains duplicates")


@dataclass(frozen=True)
class TuningContext:
    sensitivity_state: SensitivityState = SensitivityState.NOT_ASSESSED
    sensitivity_budget_remaining: int = 0
    calibration_budget_remaining: int = 0
    candidate_frozen: bool = False
    holdout_revealed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.sensitivity_state, SensitivityState):
            raise KpiEvaluationError("tuning context has an invalid sensitivity state")
        if self.sensitivity_budget_remaining < 0 or self.calibration_budget_remaining < 0:
            raise KpiEvaluationError("tuning budgets cannot be negative")


@dataclass(frozen=True)
class MetricVerdict:
    name: str
    dimension: str
    status: VerdictStatus
    value: Any
    reason_code: str
    failure_effect: FailureEffect
    tuning_role: TuningRole
    required: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dimension": self.dimension,
            "status": self.status.value,
            "value": self.value,
            "reason_code": self.reason_code,
            "failure_effect": self.failure_effect.value,
            "tuning_role": self.tuning_role.value,
            "required": self.required,
        }


@dataclass(frozen=True)
class DimensionVerdict:
    dimension: str
    status: VerdictStatus
    metric_names: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "status": self.status.value,
            "metric_names": list(self.metric_names),
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class KpiEvaluation:
    profile_id: str
    stage: Stage
    route: str
    metric_verdicts: tuple[MetricVerdict, ...]
    dimension_verdicts: tuple[DimensionVerdict, ...]
    reason_codes: tuple[str, ...]
    unregistered_metric_names: tuple[str, ...] = field(default_factory=tuple)

    def metric(self, name: str) -> MetricVerdict:
        for verdict in self.metric_verdicts:
            if verdict.name == name:
                return verdict
        raise KeyError(name)

    def dimension(self, name: str) -> DimensionVerdict:
        for verdict in self.dimension_verdicts:
            if verdict.dimension == name:
                return verdict
        raise KeyError(name)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_kpi_evaluation_v1",
            "profile_id": self.profile_id,
            "stage": self.stage.value,
            "route": self.route,
            "aggregation": "non_compensatory_precedence",
            "metric_verdicts": [row.to_payload() for row in self.metric_verdicts],
            "dimension_verdicts": [row.to_payload() for row in self.dimension_verdicts],
            "reason_codes": list(self.reason_codes),
            "unregistered_metric_names": list(self.unregistered_metric_names),
        }


def _observation(value: Any) -> MetricObservation:
    if isinstance(value, MetricObservation):
        return value
    return MetricObservation.observed(value)


def _numeric_value(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _evaluate_observed(rule: MetricRule, value: Any) -> tuple[VerdictStatus, str]:
    if value is None:
        return VerdictStatus.INVALID, "observed_value_is_none"
    if rule.comparison is Comparison.EQUAL:
        if isinstance(rule.expected, bool) and not isinstance(value, bool):
            return VerdictStatus.INVALID, "observed_value_wrong_type"
        if isinstance(rule.expected, str) and not isinstance(value, str):
            return VerdictStatus.INVALID, "observed_value_wrong_type"
        if (
            isinstance(value, Real)
            and not isinstance(value, bool)
            and not math.isfinite(float(value))
        ):
            return VerdictStatus.INVALID, "observed_value_not_finite"
        if value == rule.expected:
            return VerdictStatus.PASS, "matches_expected"
        return VerdictStatus.FAIL, "does_not_match_expected"
    numeric = _numeric_value(value)
    if numeric is None:
        if isinstance(value, Real) and not isinstance(value, bool):
            return VerdictStatus.INVALID, "observed_value_not_finite"
        return VerdictStatus.INVALID, "observed_value_wrong_type"
    if rule.comparison is Comparison.MINIMUM:
        assert rule.pass_min is not None
        if numeric >= rule.pass_min:
            return VerdictStatus.PASS, "within_pass_band"
        if rule.hard_min is not None and numeric >= rule.hard_min:
            return VerdictStatus.WARN, "inside_warning_band"
        return VerdictStatus.FAIL, "outside_hard_boundary"
    if rule.comparison is Comparison.MAXIMUM:
        assert rule.pass_max is not None
        if numeric <= rule.pass_max:
            return VerdictStatus.PASS, "within_pass_band"
        if rule.hard_max is not None and numeric <= rule.hard_max:
            return VerdictStatus.WARN, "inside_warning_band"
        return VerdictStatus.FAIL, "outside_hard_boundary"
    assert rule.pass_min is not None and rule.pass_max is not None
    if rule.pass_min <= numeric <= rule.pass_max:
        return VerdictStatus.PASS, "within_pass_band"
    lower_boundary = rule.pass_min if rule.hard_min is None else rule.hard_min
    upper_boundary = rule.pass_max if rule.hard_max is None else rule.hard_max
    lower_ok = numeric >= lower_boundary
    upper_ok = numeric <= upper_boundary
    if lower_ok and upper_ok and (rule.hard_min is not None or rule.hard_max is not None):
        return VerdictStatus.WARN, "inside_warning_band"
    return VerdictStatus.FAIL, "outside_hard_boundary"


def _evaluate_metric(
    rule: MetricRule,
    stage: Stage,
    supplied: bool,
    raw_value: Any,
) -> MetricVerdict:
    if stage not in rule.applicable_stages:
        return MetricVerdict(
            rule.name,
            rule.dimension,
            VerdictStatus.NOT_SCHEDULED,
            None,
            "stage_not_applicable",
            rule.failure_effect,
            rule.tuning_role,
            False,
        )
    required = stage in rule.required_stages
    if not supplied:
        status = VerdictStatus.MISSING if required else VerdictStatus.NOT_REQUIRED
        reason = "required_metric_missing" if required else "optional_metric_not_supplied"
        return MetricVerdict(
            rule.name,
            rule.dimension,
            status,
            None,
            reason,
            rule.failure_effect,
            rule.tuning_role,
            required,
        )
    observation = _observation(raw_value)
    if observation.status is ObservationStatus.MISSING:
        status = VerdictStatus.MISSING if required else VerdictStatus.NOT_REQUIRED
        reason = observation.reason or (
            "required_metric_missing" if required else "optional_metric_not_supplied"
        )
    elif observation.status is ObservationStatus.CENSORED:
        status = VerdictStatus.CENSORED
        reason = observation.reason or "metric_is_censored"
    elif observation.status is ObservationStatus.NOT_EVALUABLE:
        status = VerdictStatus.NOT_EVALUABLE
        reason = observation.reason or "metric_is_not_evaluable"
    elif observation.status is ObservationStatus.NOT_SCHEDULED:
        if required:
            status = VerdictStatus.INVALID
            reason = "required_metric_declared_not_scheduled"
        else:
            status = VerdictStatus.NOT_SCHEDULED
            reason = observation.reason or "metric_not_scheduled"
    elif observation.status is ObservationStatus.NOT_APPLICABLE:
        if required:
            status = VerdictStatus.INVALID
            reason = "required_metric_declared_not_applicable"
        else:
            status = VerdictStatus.NOT_APPLICABLE
            reason = observation.reason or "metric_not_applicable"
    elif observation.status is ObservationStatus.NOT_REQUIRED:
        if required:
            status = VerdictStatus.INVALID
            reason = "required_metric_declared_not_required"
        else:
            status = VerdictStatus.NOT_REQUIRED
            reason = observation.reason or "optional_metric_not_required"
    elif observation.status is ObservationStatus.INVALID:
        status = VerdictStatus.INVALID
        reason = observation.reason or "metric_declared_invalid"
    else:
        status, reason = _evaluate_observed(rule, observation.value)
    return MetricVerdict(
        rule.name,
        rule.dimension,
        status,
        observation.value,
        reason,
        rule.failure_effect,
        rule.tuning_role,
        required,
    )


_DIMENSION_PRECEDENCE = {
    VerdictStatus.INVALID: 6,
    VerdictStatus.MISSING: 5,
    VerdictStatus.FAIL: 4,
    VerdictStatus.NOT_EVALUABLE: 4,
    VerdictStatus.CENSORED: 4,
    VerdictStatus.WARN: 3,
    VerdictStatus.PASS: 2,
    VerdictStatus.NOT_SCHEDULED: 1,
    VerdictStatus.NOT_APPLICABLE: 1,
    VerdictStatus.NOT_REQUIRED: 1,
}


def _dimension_verdicts(
    profile: EvaluationProfile,
    metrics: tuple[MetricVerdict, ...],
) -> tuple[DimensionVerdict, ...]:
    declared = list(profile.dimension_order)
    for rule in profile.rules:
        if rule.dimension not in declared:
            declared.append(rule.dimension)
    rows: list[DimensionVerdict] = []
    for dimension in declared:
        members = tuple(row for row in metrics if row.dimension == dimension)
        if not members:
            status = VerdictStatus.NOT_REQUIRED
        else:
            status = max(members, key=lambda row: _DIMENSION_PRECEDENCE[row.status]).status
        rows.append(
            DimensionVerdict(
                dimension=dimension,
                status=status,
                metric_names=tuple(row.name for row in members),
                reason_codes=tuple(
                    row.reason_code
                    for row in members
                    if row.status
                    not in {
                        VerdictStatus.PASS,
                        VerdictStatus.NOT_REQUIRED,
                        VerdictStatus.NOT_SCHEDULED,
                        VerdictStatus.NOT_APPLICABLE,
                    }
                ),
            )
        )
    return tuple(rows)


def _tuning_route(
    stage: Stage,
    profile: EvaluationProfile,
    attention: tuple[MetricVerdict, ...],
    rejecting_failures: tuple[MetricVerdict, ...],
    context: TuningContext,
) -> tuple[str | None, str | None]:
    if stage not in {Stage.S, Stage.R} or context.candidate_frozen or context.holdout_revealed:
        return None, None
    if not attention:
        return None, None
    if any(row.tuning_role is TuningRole.NONE for row in rejecting_failures):
        return None, None
    if context.sensitivity_state in {
        SensitivityState.NEEDLE,
        SensitivityState.EDGE_HIT,
        SensitivityState.BOUNDARY_TREND,
        SensitivityState.UNSTABLE,
        SensitivityState.INCONCLUSIVE,
        SensitivityState.WEAK,
    }:
        return REJECT_ROUTE[stage], "sensitivity_shape_not_robust"
    if context.sensitivity_state in {
        SensitivityState.NOT_ASSESSED,
        SensitivityState.PENDING,
    }:
        if context.sensitivity_budget_remaining > 0:
            return "sensitivity_review", "bounded_sensitivity_required"
        if rejecting_failures or profile.require_sensitivity_for_tunable_warnings:
            return REJECT_ROUTE[stage], "sensitivity_budget_unavailable"
        return None, None
    calibratable = tuple(
        row for row in attention if row.tuning_role is TuningRole.CALIBRATABLE
    )
    if context.sensitivity_state is SensitivityState.PLATEAU:
        non_calibratable_failures = tuple(
            row
            for row in rejecting_failures
            if row.tuning_role is not TuningRole.CALIBRATABLE
        )
        if calibratable and not non_calibratable_failures:
            if context.calibration_budget_remaining > 0:
                return (
                    "local_calibration_eligible",
                    "sensitivity_supports_bounded_calibration",
                )
            if rejecting_failures:
                return REJECT_ROUTE[stage], "calibration_budget_unavailable"
    return None, None


def interpret_kpis(
    stage: Stage | str,
    metrics: Mapping[str, Any],
    profile: EvaluationProfile,
    *,
    tuning: TuningContext | None = None,
) -> KpiEvaluation:
    """Interpret registered KPIs without state mutation or score aggregation."""

    try:
        resolved_stage = Stage(stage)
    except ValueError as exc:
        raise KpiEvaluationError(f"unknown V2 stage: {stage}") from exc
    if not isinstance(metrics, Mapping):
        raise KpiEvaluationError("metrics must be a mapping")
    context = tuning or TuningContext()
    verdicts = tuple(
        _evaluate_metric(rule, resolved_stage, rule.name in metrics, metrics.get(rule.name))
        for rule in profile.rules
    )
    dimensions = _dimension_verdicts(profile, verdicts)
    repair_rows = tuple(
        row
        for row in verdicts
        if row.status in {VerdictStatus.MISSING, VerdictStatus.INVALID}
        or (row.status is VerdictStatus.FAIL and row.failure_effect is FailureEffect.REPAIR)
    )
    evidence_gap_rows = tuple(
        row
        for row in verdicts
        if row.failure_effect is FailureEffect.EVIDENCE_GAP
        and row.status
        in {
            VerdictStatus.FAIL,
            VerdictStatus.CENSORED,
            VerdictStatus.NOT_EVALUABLE,
        }
    )
    rejecting_failures = tuple(
        row
        for row in verdicts
        if (
            row.status is VerdictStatus.FAIL
            or (row.required and row.status in {VerdictStatus.CENSORED, VerdictStatus.NOT_EVALUABLE})
        )
        and row.failure_effect is FailureEffect.REJECT
    )
    attention = tuple(
        row
        for row in verdicts
        if row.status in {
            VerdictStatus.WARN,
            VerdictStatus.FAIL,
            VerdictStatus.CENSORED,
            VerdictStatus.NOT_EVALUABLE,
        }
        and row.failure_effect is FailureEffect.REJECT
        and row.tuning_role is not TuningRole.NONE
    )
    fragile_sensitivity = context.sensitivity_state in {
        SensitivityState.NEEDLE,
        SensitivityState.EDGE_HIT,
        SensitivityState.BOUNDARY_TREND,
        SensitivityState.UNSTABLE,
        SensitivityState.INCONCLUSIVE,
        SensitivityState.WEAK,
    }
    if repair_rows:
        route = "repair_required"
        route_reason = "evidence_integrity_or_completeness_failed"
    elif evidence_gap_rows:
        route = "evidence_gap"
        route_reason = "required_evidence_is_not_identified"
    elif resolved_stage in {Stage.S, Stage.R} and fragile_sensitivity:
        route = REJECT_ROUTE[resolved_stage]
        route_reason = "sensitivity_shape_not_robust"
    else:
        route, route_reason = _tuning_route(
            resolved_stage,
            profile,
            attention,
            rejecting_failures,
            context,
        )
        if route is None:
            if rejecting_failures:
                route = REJECT_ROUTE[resolved_stage]
                route_reason = "non_compensatory_hard_gate_failed"
            else:
                route = PASS_ROUTE[resolved_stage]
                route_reason = "all_required_hard_gates_passed"
    issues = tuple(
        f"{row.name}:{row.reason_code}"
        for row in verdicts
        if row.status
        not in {
            VerdictStatus.PASS,
            VerdictStatus.NOT_REQUIRED,
            VerdictStatus.NOT_SCHEDULED,
            VerdictStatus.NOT_APPLICABLE,
        }
    )
    registered_names = {rule.name for rule in profile.rules}
    unregistered = tuple(sorted(str(name) for name in metrics if name not in registered_names))
    return KpiEvaluation(
        profile_id=profile.profile_id,
        stage=resolved_stage,
        route=route,
        metric_verdicts=verdicts,
        dimension_verdicts=dimensions,
        reason_codes=(str(route_reason), *issues),
        unregistered_metric_names=unregistered,
    )


__all__ = [
    "Comparison",
    "DimensionVerdict",
    "EvaluationProfile",
    "FailureEffect",
    "KpiEvaluation",
    "KpiEvaluationError",
    "MetricObservation",
    "MetricRule",
    "MetricVerdict",
    "ObservationStatus",
    "SensitivityState",
    "Stage",
    "TuningContext",
    "TuningRole",
    "VerdictStatus",
    "interpret_kpis",
]
