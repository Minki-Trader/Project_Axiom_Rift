"""Pure bounded sensitivity planning and surface classification for V2.

The module permits only two registered non-structural numeric targets.  It
creates one-at-a-time validation-OOS diagnostic extremes, accounts for every
trial, and never selects on outer-development metrics.  A single inward
midpoint may be proposed only when one unambiguous one-sided plateau supports
it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from numbers import Real
from typing import Any, Mapping


class SensitivityError(ValueError):
    """Raised when a sensitivity request violates the bounded policy."""


ALLOWED_TARGETS = (
    "model.alpha",
    "calibration.quantile",
)
MAX_KNOBS = 2
MAX_INITIAL_VARIANTS = 5
MAX_LOCAL_CALIBRATION_EVALUATIONS_PER_OUTER_FOLD = 1
ALLOWED_STAGES = frozenset({"S", "R"})


def _canonical_json(payload: Any) -> str:
    try:
        return json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise SensitivityError(f"payload is not canonical JSON: {exc}") from exc


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("ascii")).hexdigest()


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise SensitivityError(f"{label} must be a real number, not bool")
    result = float(value)
    if not math.isfinite(result):
        raise SensitivityError(f"{label} must be finite")
    return result


def _validate_target_value(path: str, value: Any, label: str) -> float:
    result = _finite_float(value, label)
    if path == "model.alpha" and result <= 0.0:
        raise SensitivityError("model.alpha values must be greater than zero")
    if path == "calibration.quantile" and not 0.0 < result < 1.0:
        raise SensitivityError("calibration.quantile values must be inside (0, 1)")
    return result


def _nested_get(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise SensitivityError(f"baseline parameters do not contain {path}")
        current = current[part]
    return current


def _nested_set(payload: Mapping[str, Any], path: str, value: float) -> dict[str, Any]:
    result = copy.deepcopy(dict(payload))
    current: dict[str, Any] = result
    parts = path.split(".")
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            raise SensitivityError(f"baseline parameter parent is not a mapping: {path}")
        current = child
    if parts[-1] not in current:
        raise SensitivityError(f"baseline parameters do not contain {path}")
    current[parts[-1]] = value
    return result


@dataclass(frozen=True)
class KnobSpec:
    path: str
    value_type: str
    low: float
    baseline: float
    high: float

    def __post_init__(self) -> None:
        if self.path not in ALLOWED_TARGETS:
            raise SensitivityError(
                f"target {self.path} is structural, unregistered, or not calibratable"
            )
        if self.value_type != "float":
            raise SensitivityError(f"target {self.path} must declare type float")
        low = _validate_target_value(self.path, self.low, f"{self.path}.low")
        baseline = _validate_target_value(
            self.path, self.baseline, f"{self.path}.baseline"
        )
        high = _validate_target_value(self.path, self.high, f"{self.path}.high")
        if not low < baseline < high:
            raise SensitivityError(
                f"target {self.path} must satisfy low < baseline < high"
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": self.value_type,
            "low": self.low,
            "baseline": self.baseline,
            "high": self.high,
        }


def _flatten_nested_policy(
    payload: Mapping[str, Any], prefix: tuple[str, ...] = ()
) -> list[KnobSpec]:
    if not isinstance(payload, Mapping) or not payload:
        raise SensitivityError("nested sensitivity policy must be a non-empty mapping")
    rows: list[KnobSpec] = []
    leaf_keys = {"type", "low", "baseline", "high"}
    for key in sorted(payload):
        if not isinstance(key, str) or not key:
            raise SensitivityError("sensitivity policy keys must be non-empty strings")
        value = payload[key]
        path = (*prefix, key)
        if isinstance(value, Mapping) and set(value) & leaf_keys:
            if set(value) != leaf_keys:
                raise SensitivityError(
                    f"policy leaf {'.'.join(path)} must contain type, low, baseline, high"
                )
            target = ".".join(path)
            if target not in ALLOWED_TARGETS:
                raise SensitivityError(
                    f"target {target} is structural, unregistered, or not calibratable"
                )
            rows.append(
                KnobSpec(
                    path=target,
                    value_type=value["type"],
                    low=_validate_target_value(target, value["low"], f"{target}.low"),
                    baseline=_validate_target_value(
                        target, value["baseline"], f"{target}.baseline"
                    ),
                    high=_validate_target_value(target, value["high"], f"{target}.high"),
                )
            )
        elif isinstance(value, Mapping):
            rows.extend(_flatten_nested_policy(value, path))
        else:
            raise SensitivityError(
                f"policy node {'.'.join(path)} must be a mapping"
            )
    return rows


def _nested_policy_payload(knobs: tuple[KnobSpec, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for knob in knobs:
        current = result
        parts = knob.path.split(".")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = knob.to_payload()
    return result


@dataclass(frozen=True)
class SensitivityVariant:
    variant_id: str
    variant_sha256: str
    role: str
    knob_path: str | None
    knob_value: float | None
    parameters_json: str
    parameters_sha256: str
    diagnostic_only: bool
    development_selection_allowed: bool = False

    @property
    def parameters(self) -> dict[str, Any]:
        return json.loads(self.parameters_json)

    def to_payload(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "variant_sha256": self.variant_sha256,
            "role": self.role,
            "knob_path": self.knob_path,
            "knob_value": self.knob_value,
            "parameters": self.parameters,
            "parameters_sha256": self.parameters_sha256,
            "diagnostic_only": self.diagnostic_only,
            "development_selection_allowed": self.development_selection_allowed,
        }


def _make_variant(
    *,
    hypothesis_id: str,
    stage: str,
    role: str,
    knob_path: str | None,
    knob_value: float | None,
    parameters: Mapping[str, Any],
    diagnostic_only: bool,
    source_identity: str | None = None,
) -> SensitivityVariant:
    parameters_json = _canonical_json(parameters)
    parameters_sha256 = hashlib.sha256(parameters_json.encode("ascii")).hexdigest()
    seed = {
        "schema": "axiom_rift_v2_sensitivity_variant_seed_v1",
        "hypothesis_id": hypothesis_id,
        "stage": stage,
        "role": role,
        "knob_path": knob_path,
        "knob_value": knob_value,
        "parameters_sha256": parameters_sha256,
        "source_identity": source_identity,
    }
    variant_sha256 = _sha256(seed)
    return SensitivityVariant(
        variant_id=f"V2SV{variant_sha256[:12].upper()}",
        variant_sha256=variant_sha256,
        role=role,
        knob_path=knob_path,
        knob_value=knob_value,
        parameters_json=parameters_json,
        parameters_sha256=parameters_sha256,
        diagnostic_only=diagnostic_only,
    )


@dataclass(frozen=True)
class SensitivityPlan:
    plan_id: str
    plan_sha256: str
    hypothesis_id: str
    stage: str
    data_role: str
    baseline_parameters_json: str
    baseline_parameters_sha256: str
    knobs: tuple[KnobSpec, ...]
    variants: tuple[SensitivityVariant, ...]
    holdout_revealed: bool
    candidate_frozen: bool
    disabled_reason: str | None = None
    extremes_are_diagnostic_only: bool = True
    development_variant_selection_allowed: bool = False
    local_calibration_new_evaluations_per_outer_fold_max: int = (
        MAX_LOCAL_CALIBRATION_EVALUATIONS_PER_OUTER_FOLD
    )

    @property
    def baseline_parameters(self) -> dict[str, Any]:
        return json.loads(self.baseline_parameters_json)

    def variant(self, role: str, knob_path: str | None = None) -> SensitivityVariant:
        matches = tuple(
            row
            for row in self.variants
            if row.role == role and row.knob_path == knob_path
        )
        if len(matches) != 1:
            raise KeyError((role, knob_path))
        return matches[0]

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_sensitivity_plan_v1",
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
            "hypothesis_id": self.hypothesis_id,
            "stage": self.stage,
            "data_role": self.data_role,
            "baseline_parameters": self.baseline_parameters,
            "baseline_parameters_sha256": self.baseline_parameters_sha256,
            "policy": _nested_policy_payload(self.knobs),
            "variants": [row.to_payload() for row in self.variants],
            "limits": {
                "knobs_max": MAX_KNOBS,
                "initial_variants_max": MAX_INITIAL_VARIANTS,
                "local_calibration_new_evaluations_per_outer_fold_max": (
                    self.local_calibration_new_evaluations_per_outer_fold_max
                ),
            },
            "extremes_are_diagnostic_only": self.extremes_are_diagnostic_only,
            "development_variant_selection_allowed": self.development_variant_selection_allowed,
            "holdout_revealed": self.holdout_revealed,
            "candidate_frozen": self.candidate_frozen,
            "sensitivity_enabled": bool(self.knobs),
            "disabled_reason": self.disabled_reason,
        }


def build_oat_plan(
    *,
    hypothesis_id: str,
    stage: str,
    baseline_parameters: Mapping[str, Any],
    nested_policy: Mapping[str, Any],
    data_role: str = "validation_oos",
    holdout_revealed: bool = False,
    candidate_frozen: bool = False,
    disabled_reason: str | None = None,
) -> SensitivityPlan:
    """Build baseline plus low/high one-at-a-time diagnostic variants."""

    if not hypothesis_id:
        raise SensitivityError("hypothesis_id must be non-empty")
    if stage not in ALLOWED_STAGES:
        raise SensitivityError("sensitivity planning is allowed only in S or R")
    if data_role != "validation_oos":
        raise SensitivityError("sensitivity uses validation_oos data only")
    if holdout_revealed:
        raise SensitivityError("holdout retuning is forbidden")
    if candidate_frozen:
        raise SensitivityError("candidate freeze disables sensitivity and calibration")
    if not isinstance(baseline_parameters, Mapping):
        raise SensitivityError("baseline_parameters must be a nested mapping")
    baseline_json = _canonical_json(baseline_parameters)
    baseline_copy = json.loads(baseline_json)
    baseline_sha256 = hashlib.sha256(baseline_json.encode("ascii")).hexdigest()
    if not isinstance(nested_policy, Mapping):
        raise SensitivityError("nested sensitivity policy must be a mapping")
    knobs = (
        tuple(sorted(_flatten_nested_policy(nested_policy), key=lambda row: row.path))
        if nested_policy
        else ()
    )
    if len(knobs) > MAX_KNOBS:
        raise SensitivityError(f"at most {MAX_KNOBS} sensitivity knobs are allowed")
    if len({row.path for row in knobs}) != len(knobs):
        raise SensitivityError("sensitivity policy contains duplicate targets")
    for knob in knobs:
        baseline_value = _validate_target_value(
            knob.path,
            _nested_get(baseline_copy, knob.path),
            f"baseline_parameters.{knob.path}",
        )
        if baseline_value != knob.baseline:
            raise SensitivityError(
                f"policy baseline for {knob.path} differs from executable baseline"
            )
    variants: list[SensitivityVariant] = [
        _make_variant(
            hypothesis_id=hypothesis_id,
            stage=stage,
            role="baseline",
            knob_path=None,
            knob_value=None,
            parameters=baseline_copy,
            diagnostic_only=False,
        )
    ]
    for knob in knobs:
        for role, value in (("extreme_low", knob.low), ("extreme_high", knob.high)):
            variants.append(
                _make_variant(
                    hypothesis_id=hypothesis_id,
                    stage=stage,
                    role=role,
                    knob_path=knob.path,
                    knob_value=value,
                    parameters=_nested_set(baseline_copy, knob.path, value),
                    diagnostic_only=True,
                )
            )
    if len(variants) > MAX_INITIAL_VARIANTS:
        raise SensitivityError(
            f"OAT sensitivity plan exceeds {MAX_INITIAL_VARIANTS} initial variants"
        )
    if len({row.variant_id for row in variants}) != len(variants):
        raise SensitivityError("deterministic variant ID collision")
    plan_seed = {
        "schema": "axiom_rift_v2_sensitivity_plan_seed_v1",
        "hypothesis_id": hypothesis_id,
        "stage": stage,
        "data_role": data_role,
        "baseline_parameters_sha256": baseline_sha256,
        "policy": _nested_policy_payload(knobs),
        "variant_sha256s": [row.variant_sha256 for row in variants],
        "holdout_revealed": holdout_revealed,
        "candidate_frozen": candidate_frozen,
        "disabled_reason": disabled_reason,
    }
    plan_sha256 = _sha256(plan_seed)
    return SensitivityPlan(
        plan_id=f"V2SP{plan_sha256[:12].upper()}",
        plan_sha256=plan_sha256,
        hypothesis_id=hypothesis_id,
        stage=stage,
        data_role=data_role,
        baseline_parameters_json=baseline_json,
        baseline_parameters_sha256=baseline_sha256,
        knobs=knobs,
        variants=tuple(variants),
        holdout_revealed=holdout_revealed,
        candidate_frozen=candidate_frozen,
        disabled_reason=disabled_reason,
    )


@dataclass(frozen=True)
class FoldMetric:
    fold_id: str
    value: float

    def __post_init__(self) -> None:
        if not self.fold_id:
            raise SensitivityError("fold_id must be non-empty")
        _finite_float(self.value, f"fold {self.fold_id} metric")


@dataclass(frozen=True)
class FoldFeasibility:
    fold_id: str
    feasible: bool
    causal_checks_passed: bool
    unknown_cost_observation_count: int
    evaluable_trade_count: int
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.fold_id:
            raise SensitivityError("fold feasibility requires fold_id")
        if not isinstance(self.feasible, bool) or not isinstance(self.causal_checks_passed, bool):
            raise SensitivityError("fold feasibility booleans are invalid")
        for name, value in (
            ("unknown_cost_observation_count", self.unknown_cost_observation_count),
            ("evaluable_trade_count", self.evaluable_trade_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SensitivityError(f"{name} must be a nonnegative integer")

    def to_payload(self) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "feasible": self.feasible,
            "causal_checks_passed": self.causal_checks_passed,
            "unknown_cost_observation_count": self.unknown_cost_observation_count,
            "evaluable_trade_count": self.evaluable_trade_count,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class VariantEvidence:
    variant_id: str
    aggregate_value: float
    folds: tuple[FoldMetric, ...]
    feasibility: tuple[FoldFeasibility, ...]
    data_role: str = "validation_oos"

    def __post_init__(self) -> None:
        if not self.variant_id:
            raise SensitivityError("variant evidence requires variant_id")
        if self.data_role != "validation_oos":
            raise SensitivityError("sensitivity evidence must use validation_oos")
        _finite_float(self.aggregate_value, f"variant {self.variant_id} aggregate")
        if not self.folds:
            raise SensitivityError("variant evidence requires at least one fold")
        fold_ids = tuple(row.fold_id for row in self.folds)
        if len(fold_ids) != len(set(fold_ids)):
            raise SensitivityError(f"variant {self.variant_id} repeats a fold")
        feasibility_ids = tuple(row.fold_id for row in self.feasibility)
        if feasibility_ids != fold_ids:
            raise SensitivityError("variant feasibility must match metric fold IDs in order")

    @property
    def feasibility_passed(self) -> bool:
        return all(row.feasible for row in self.feasibility)

    def to_payload(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "aggregate_value": self.aggregate_value,
            "data_role": self.data_role,
            "folds": [
                {"fold_id": row.fold_id, "value": row.value} for row in self.folds
            ],
            "feasibility": [row.to_payload() for row in self.feasibility],
            "feasibility_passed": self.feasibility_passed,
        }

    @classmethod
    def from_mapping(
        cls,
        variant_id: str,
        aggregate_value: float,
        fold_values: Mapping[str, float],
        fold_feasibility: Mapping[str, Mapping[str, Any]],
        data_role: str = "validation_oos",
    ) -> "VariantEvidence":
        if not isinstance(fold_feasibility, Mapping) or set(fold_feasibility) != set(fold_values):
            raise SensitivityError("fold feasibility keys must match metric fold keys")
        if not all(isinstance(row, Mapping) for row in fold_feasibility.values()):
            raise SensitivityError("fold feasibility rows must be mappings")
        return cls(
            variant_id=variant_id,
            aggregate_value=_finite_float(aggregate_value, "aggregate_value"),
            folds=tuple(
                FoldMetric(str(fold_id), _finite_float(value, f"fold {fold_id}"))
                for fold_id, value in sorted(fold_values.items())
            ),
            feasibility=tuple(
                FoldFeasibility(
                    fold_id=str(fold_id),
                    feasible=row.get("feasible"),
                    causal_checks_passed=row.get("causal_checks_passed"),
                    unknown_cost_observation_count=row.get(
                        "unknown_cost_observation_count"
                    ),
                    evaluable_trade_count=row.get("evaluable_trade_count"),
                    reason_codes=tuple(str(value) for value in row.get("reason_codes", [])),
                )
                for fold_id, row in sorted(fold_feasibility.items())
            ),
            data_role=data_role,
        )


@dataclass(frozen=True)
class SurfaceRule:
    metric_name: str
    higher_is_better: bool
    pass_threshold: float
    plateau_tolerance: float
    fold_consistency_min: float = 0.67
    viability_threshold: float | None = None

    def __post_init__(self) -> None:
        if not self.metric_name:
            raise SensitivityError("surface metric_name must be non-empty")
        if not isinstance(self.higher_is_better, bool):
            raise SensitivityError("higher_is_better must be bool")
        _finite_float(self.pass_threshold, "pass_threshold")
        viability = self.effective_viability_threshold
        tolerance = _finite_float(self.plateau_tolerance, "plateau_tolerance")
        consistency = _finite_float(self.fold_consistency_min, "fold_consistency_min")
        if tolerance < 0.0:
            raise SensitivityError("plateau_tolerance cannot be negative")
        if not 0.0 < consistency <= 1.0:
            raise SensitivityError("fold_consistency_min must be inside (0, 1]")
        if self.higher_is_better and viability > self.pass_threshold:
            raise SensitivityError("viability_threshold cannot exceed pass_threshold")
        if not self.higher_is_better and viability < self.pass_threshold:
            raise SensitivityError("viability_threshold cannot be below pass_threshold")

    @property
    def effective_viability_threshold(self) -> float:
        if self.viability_threshold is None:
            return _finite_float(self.pass_threshold, "pass_threshold")
        return _finite_float(self.viability_threshold, "viability_threshold")


def _surface_rule_payload(rule: SurfaceRule) -> dict[str, Any]:
    return {
        "metric_name": rule.metric_name,
        "higher_is_better": rule.higher_is_better,
        "pass_threshold": rule.pass_threshold,
        "viability_threshold": rule.effective_viability_threshold,
        "plateau_tolerance": rule.plateau_tolerance,
        "fold_consistency_min": rule.fold_consistency_min,
    }


@dataclass(frozen=True)
class TrialCounts:
    distinct_variant_count: int
    fold_evaluation_count: int
    selection_count: int

    def to_payload(self) -> dict[str, int]:
        return {
            "distinct_variant_count": self.distinct_variant_count,
            "fold_evaluation_count": self.fold_evaluation_count,
            "selection_count": self.selection_count,
        }


@dataclass(frozen=True)
class KnobSurface:
    knob_path: str
    shape: str
    plateau_side: str | None
    boundary_direction: str | None
    low_value: float
    baseline_value: float
    high_value: float
    fold_consistency: float
    local_midpoint_eligible: bool
    reason_codes: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "knob_path": self.knob_path,
            "shape": self.shape,
            "plateau_side": self.plateau_side,
            "boundary_direction": self.boundary_direction,
            "values": {
                "low": self.low_value,
                "baseline": self.baseline_value,
                "high": self.high_value,
            },
            "fold_consistency": self.fold_consistency,
            "local_midpoint_eligible": self.local_midpoint_eligible,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class SensitivityAssessment:
    assessment_id: str
    assessment_sha256: str
    plan_id: str
    metric_name: str
    surface_rule_sha256: str
    surfaces: tuple[KnobSurface, ...]
    trial_counts: TrialCounts
    validation_fold_ids: tuple[str, ...]
    infeasible_variant_ids: tuple[str, ...]
    feasibility_passed: bool
    development_variant_selected: bool = False

    def surface(self, knob_path: str) -> KnobSurface:
        matches = tuple(row for row in self.surfaces if row.knob_path == knob_path)
        if len(matches) != 1:
            raise KeyError(knob_path)
        return matches[0]

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_sensitivity_assessment_v1",
            "assessment_id": self.assessment_id,
            "assessment_sha256": self.assessment_sha256,
            "plan_id": self.plan_id,
            "metric_name": self.metric_name,
            "surface_rule_sha256": self.surface_rule_sha256,
            "surfaces": [row.to_payload() for row in self.surfaces],
            "trial_counts": self.trial_counts.to_payload(),
            "validation_fold_ids": list(self.validation_fold_ids),
            "infeasible_variant_ids": list(self.infeasible_variant_ids),
            "feasibility_passed": self.feasibility_passed,
            "development_variant_selected": self.development_variant_selected,
        }


def _utility(value: float, rule: SurfaceRule) -> float:
    return value if rule.higher_is_better else -value


def _shape(
    low: float,
    baseline: float,
    high: float,
    rule: SurfaceRule,
) -> tuple[str, str | None, str | None]:
    low_u, base_u, high_u = (
        _utility(low, rule),
        _utility(baseline, rule),
        _utility(high, rule),
    )
    threshold = _utility(rule.pass_threshold, rule)
    viability = _utility(rule.effective_viability_threshold, rule)
    tolerance = rule.plateau_tolerance
    passes = (
        low_u >= threshold,
        base_u >= threshold,
        high_u >= threshold,
    )
    near_low = abs(low_u - base_u) <= tolerance
    near_high = abs(high_u - base_u) <= tolerance
    if all(passes) and near_low and near_high:
        return "plateau", "both", None
    if passes[1]:
        low_neighbor = passes[0] and near_low
        high_neighbor = passes[2] and near_high
        if low_neighbor or high_neighbor:
            return "plateau", "baseline", None
    else:
        baseline_viable = base_u >= viability
        low_calibration_edge = passes[0] and near_low
        high_calibration_edge = passes[2] and near_high
        if baseline_viable and low_calibration_edge != high_calibration_edge:
            return (
                "plateau",
                "low" if low_calibration_edge else "high",
                None,
            )
    if not any(passes):
        return "weak", None, None
    if base_u > low_u + tolerance and base_u > high_u + tolerance:
        return "needle", None, None
    if low_u + tolerance < base_u and base_u + tolerance < high_u:
        return "boundary_trend", None, "high"
    if high_u + tolerance < base_u and base_u + tolerance < low_u:
        return "boundary_trend", None, "low"
    return "unstable", None, None


def _relation_matches(
    shape: str,
    plateau_side: str | None,
    boundary_direction: str | None,
    low: float,
    baseline: float,
    high: float,
    rule: SurfaceRule,
) -> bool:
    low_u, base_u, high_u = (
        _utility(low, rule),
        _utility(baseline, rule),
        _utility(high, rule),
    )
    tolerance = rule.plateau_tolerance
    threshold = _utility(rule.pass_threshold, rule)
    viability = _utility(rule.effective_viability_threshold, rule)
    near_low = abs(low_u - base_u) <= tolerance
    near_high = abs(high_u - base_u) <= tolerance
    if shape == "weak":
        return True
    if shape == "plateau" and plateau_side == "both":
        return (
            low_u >= threshold
            and base_u >= threshold
            and high_u >= threshold
            and near_low
            and near_high
        )
    if shape == "plateau" and plateau_side == "low":
        return (
            viability <= base_u < threshold
            and low_u >= threshold
            and near_low
            and not (high_u >= threshold and near_high)
        )
    if shape == "plateau" and plateau_side == "high":
        return (
            viability <= base_u < threshold
            and high_u >= threshold
            and near_high
            and not (low_u >= threshold and near_low)
        )
    if shape == "plateau" and plateau_side == "baseline":
        return base_u >= threshold and (
            (low_u >= threshold and near_low)
            or (high_u >= threshold and near_high)
        )
    if shape == "needle":
        return base_u > low_u + tolerance and base_u > high_u + tolerance
    if shape == "boundary_trend" and boundary_direction == "high":
        return low_u + tolerance < base_u and base_u + tolerance < high_u
    if shape == "boundary_trend" and boundary_direction == "low":
        return high_u + tolerance < base_u and base_u + tolerance < low_u
    return False


def assess_sensitivity(
    plan: SensitivityPlan,
    evidence: tuple[VariantEvidence, ...],
    rule: SurfaceRule,
) -> SensitivityAssessment:
    """Classify each OAT surface without selecting a development variant."""

    if plan.holdout_revealed or plan.candidate_frozen or plan.data_role != "validation_oos":
        raise SensitivityError("sensitivity assessment cannot retune frozen or holdout state")
    if not isinstance(evidence, tuple) or not all(
        isinstance(row, VariantEvidence) for row in evidence
    ):
        raise SensitivityError("evidence must be an immutable tuple of VariantEvidence")
    evidence_by_id = {row.variant_id: row for row in evidence}
    if len(evidence_by_id) != len(evidence):
        raise SensitivityError("variant evidence IDs must be unique")
    expected_ids = {row.variant_id for row in plan.variants}
    if set(evidence_by_id) != expected_ids:
        missing = sorted(expected_ids - set(evidence_by_id))
        extra = sorted(set(evidence_by_id) - expected_ids)
        raise SensitivityError(f"sensitivity evidence identity mismatch: missing={missing}, extra={extra}")
    fold_id_sets = {
        tuple(row.fold_id for row in evidence_by_id[variant.variant_id].folds)
        for variant in plan.variants
    }
    if len(fold_id_sets) != 1:
        raise SensitivityError("all sensitivity variants must evaluate identical fold IDs")
    infeasible_variant_ids = tuple(
        sorted(row.variant_id for row in evidence if not row.feasibility_passed)
    )
    feasibility_passed = not infeasible_variant_ids
    baseline = plan.variant("baseline")
    baseline_evidence = evidence_by_id[baseline.variant_id]
    surfaces: list[KnobSurface] = []
    for knob in plan.knobs:
        low_variant = plan.variant("extreme_low", knob.path)
        high_variant = plan.variant("extreme_high", knob.path)
        low_evidence = evidence_by_id[low_variant.variant_id]
        high_evidence = evidence_by_id[high_variant.variant_id]
        shape, side, direction = _shape(
            low_evidence.aggregate_value,
            baseline_evidence.aggregate_value,
            high_evidence.aggregate_value,
            rule,
        )
        matches = 0
        fold_count = len(baseline_evidence.folds)
        for index in range(fold_count):
            if _relation_matches(
                shape,
                side,
                direction,
                low_evidence.folds[index].value,
                baseline_evidence.folds[index].value,
                high_evidence.folds[index].value,
                rule,
            ):
                matches += 1
        consistency = matches / fold_count
        reasons: list[str] = [f"aggregate_shape_{shape}"]
        if shape != "weak" and consistency < rule.fold_consistency_min:
            shape, side, direction = "unstable", None, None
            reasons.append("fold_relation_inconsistent")
        else:
            reasons.append("fold_relation_consistent")
        midpoint_eligible = (
            feasibility_passed and shape == "plateau" and side in {"low", "high"}
        )
        if not feasibility_passed:
            reasons.append("selection_feasibility_failed")
        if shape == "boundary_trend":
            reasons.append("edge_chase_forbidden")
        if shape == "needle":
            reasons.append("isolated_baseline_not_calibratable")
        surfaces.append(
            KnobSurface(
                knob_path=knob.path,
                shape=shape,
                plateau_side=side,
                boundary_direction=direction,
                low_value=low_evidence.aggregate_value,
                baseline_value=baseline_evidence.aggregate_value,
                high_value=high_evidence.aggregate_value,
                fold_consistency=consistency,
                local_midpoint_eligible=midpoint_eligible,
                reason_codes=tuple(reasons),
            )
        )
    trial_counts = TrialCounts(
        distinct_variant_count=len(evidence_by_id),
        fold_evaluation_count=sum(len(row.folds) for row in evidence),
        selection_count=0,
    )
    assessment_seed = {
        "schema": "axiom_rift_v2_sensitivity_assessment_seed_v1",
        "plan_id": plan.plan_id,
        "metric_name": rule.metric_name,
        "surface_rule": _surface_rule_payload(rule),
        "evidence": [
            row.to_payload()
            for row in sorted(evidence, key=lambda item: item.variant_id)
        ],
        "surfaces": [row.to_payload() for row in surfaces],
        "trial_counts": trial_counts.to_payload(),
        "infeasible_variant_ids": list(infeasible_variant_ids),
        "feasibility_passed": feasibility_passed,
    }
    assessment_sha256 = _sha256(assessment_seed)
    return SensitivityAssessment(
        assessment_id=f"V2SA{assessment_sha256[:12].upper()}",
        assessment_sha256=assessment_sha256,
        plan_id=plan.plan_id,
        metric_name=rule.metric_name,
        surface_rule_sha256=_sha256(_surface_rule_payload(rule)),
        surfaces=tuple(surfaces),
        trial_counts=trial_counts,
        validation_fold_ids=next(iter(fold_id_sets)),
        infeasible_variant_ids=infeasible_variant_ids,
        feasibility_passed=feasibility_passed,
    )


@dataclass(frozen=True)
class CalibrationProposal:
    proposal_id: str
    proposal_sha256: str
    plan_id: str
    assessment_id: str
    variant: SensitivityVariant
    trial_counts_after_registration: TrialCounts
    no_edge_chase: bool = True
    development_variant_selected: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_local_calibration_proposal_v1",
            "proposal_id": self.proposal_id,
            "proposal_sha256": self.proposal_sha256,
            "plan_id": self.plan_id,
            "assessment_id": self.assessment_id,
            "variant": self.variant.to_payload(),
            "trial_counts_after_registration": self.trial_counts_after_registration.to_payload(),
            "no_edge_chase": self.no_edge_chase,
            "development_variant_selected": self.development_variant_selected,
        }


def propose_local_midpoint(
    plan: SensitivityPlan,
    assessment: SensitivityAssessment,
    *,
    calibration_new_evaluations_used_for_outer_fold: int = 0,
) -> CalibrationProposal:
    """Propose one inward midpoint only for one unambiguous one-sided plateau."""

    if assessment.plan_id != plan.plan_id:
        raise SensitivityError("assessment does not belong to sensitivity plan")
    if plan.holdout_revealed or plan.candidate_frozen or plan.stage not in ALLOWED_STAGES:
        raise SensitivityError("local calibration is forbidden after freeze or holdout")
    if not assessment.feasibility_passed:
        raise SensitivityError("selection feasibility failure forbids local calibration")
    if calibration_new_evaluations_used_for_outer_fold != 0:
        raise SensitivityError("local calibration new-evaluation budget is exhausted")
    eligible = tuple(row for row in assessment.surfaces if row.local_midpoint_eligible)
    if len(eligible) != 1:
        raise SensitivityError(
            "local midpoint requires exactly one unambiguous one-sided plateau"
        )
    if any(
        row.shape != "plateau" or row.plateau_side not in {"both", "baseline"}
        for row in assessment.surfaces
        if row is not eligible[0]
    ):
        raise SensitivityError(
            "other sensitivity knobs must be stable passing plateaus before calibration"
        )
    surface = eligible[0]
    knob = next(row for row in plan.knobs if row.path == surface.knob_path)
    if surface.plateau_side == "low":
        midpoint = (knob.low + knob.baseline) / 2.0
        if not knob.low < midpoint < knob.baseline:
            raise SensitivityError("low-side midpoint is not strictly inside the bracket")
    elif surface.plateau_side == "high":
        midpoint = (knob.baseline + knob.high) / 2.0
        if not knob.baseline < midpoint < knob.high:
            raise SensitivityError("high-side midpoint is not strictly inside the bracket")
    else:
        raise SensitivityError("two-sided plateau does not require local calibration")
    variant = _make_variant(
        hypothesis_id=plan.hypothesis_id,
        stage=plan.stage,
        role="local_midpoint",
        knob_path=knob.path,
        knob_value=midpoint,
        parameters=_nested_set(plan.baseline_parameters, knob.path, midpoint),
        diagnostic_only=True,
        source_identity=assessment.assessment_sha256,
    )
    counts = TrialCounts(
        distinct_variant_count=assessment.trial_counts.distinct_variant_count + 1,
        fold_evaluation_count=assessment.trial_counts.fold_evaluation_count,
        selection_count=assessment.trial_counts.selection_count + 1,
    )
    proposal_seed = {
        "schema": "axiom_rift_v2_local_calibration_proposal_seed_v1",
        "plan_id": plan.plan_id,
        "assessment_id": assessment.assessment_id,
        "variant_sha256": variant.variant_sha256,
        "trial_counts_after_registration": counts.to_payload(),
        "no_edge_chase": True,
        "development_variant_selected": False,
    }
    proposal_sha256 = _sha256(proposal_seed)
    return CalibrationProposal(
        proposal_id=f"V2LC{proposal_sha256[:12].upper()}",
        proposal_sha256=proposal_sha256,
        plan_id=plan.plan_id,
        assessment_id=assessment.assessment_id,
        variant=variant,
        trial_counts_after_registration=counts,
    )


@dataclass(frozen=True)
class SensitivityFinalization:
    finalization_id: str
    finalization_sha256: str
    plan_id: str
    assessment_id: str
    selected_variant: SensitivityVariant
    selection_basis: str
    source_data_role: str
    freeze_target_role: str
    trial_counts: TrialCounts
    promotion_blocked: bool
    promotion_block_reasons: tuple[str, ...]
    midpoint_evidence_sha256: str | None
    development_metrics_inspected: bool = False
    development_cv_parameters_frozen: bool = True
    development_cv_selection_allowed: bool = False

    @property
    def selected_variant_id(self) -> str:
        return self.selected_variant.variant_id

    @property
    def selected_variant_sha256(self) -> str:
        return self.selected_variant.variant_sha256

    @property
    def selected_parameters_sha256(self) -> str:
        return self.selected_variant.parameters_sha256

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_sensitivity_finalization_v1",
            "finalization_id": self.finalization_id,
            "finalization_sha256": self.finalization_sha256,
            "plan_id": self.plan_id,
            "assessment_id": self.assessment_id,
            "selected_variant_id": self.selected_variant_id,
            "selected_variant_sha256": self.selected_variant_sha256,
            "selected_parameters_sha256": self.selected_parameters_sha256,
            "selected_role": self.selected_variant.role,
            "selection_basis": self.selection_basis,
            "source_data_role": self.source_data_role,
            "freeze_target_role": self.freeze_target_role,
            "trial_counts": self.trial_counts.to_payload(),
            "promotion_blocked": self.promotion_blocked,
            "promotion_block_reasons": list(self.promotion_block_reasons),
            "midpoint_evidence_sha256": self.midpoint_evidence_sha256,
            "development_metrics_inspected": self.development_metrics_inspected,
            "development_cv_parameters_frozen": self.development_cv_parameters_frozen,
            "development_cv_selection_allowed": self.development_cv_selection_allowed,
        }


def finalize_sensitivity_choice(
    plan: SensitivityPlan,
    assessment: SensitivityAssessment,
    rule: SurfaceRule,
    *,
    proposal: CalibrationProposal | None = None,
    midpoint_evidence: VariantEvidence | None = None,
) -> SensitivityFinalization:
    """Freeze baseline or midpoint using validation-OOS evidence only.

    Outer-development metrics are intentionally absent from this interface.
    A non-plateau surface always falls back to the baseline and leaves an
    explicit promotion block for the outer research gate.
    """

    if assessment.plan_id != plan.plan_id:
        raise SensitivityError("assessment does not belong to sensitivity plan")
    if assessment.metric_name != rule.metric_name:
        raise SensitivityError("surface rule differs from assessment metric")
    if assessment.surface_rule_sha256 != _sha256(_surface_rule_payload(rule)):
        raise SensitivityError("surface rule identity differs from assessment")
    if plan.data_role != "validation_oos" or plan.holdout_revealed:
        raise SensitivityError("finalization requires unrevealed validation_oos state")
    baseline = plan.variant("baseline")
    selected = baseline
    selection_basis = "baseline_default"
    promotion_reasons: list[str] = []
    counts = TrialCounts(
        distinct_variant_count=assessment.trial_counts.distinct_variant_count,
        fold_evaluation_count=assessment.trial_counts.fold_evaluation_count,
        selection_count=assessment.trial_counts.selection_count + 1,
    )
    midpoint_evidence_sha256: str | None = None
    bad_surfaces = tuple(
        row
        for row in assessment.surfaces
        if row.shape in {"weak", "needle", "boundary_trend", "unstable"}
    )
    one_sided = tuple(
        row
        for row in assessment.surfaces
        if row.shape == "plateau" and row.plateau_side in {"low", "high"}
    )
    if not assessment.feasibility_passed:
        if proposal is not None or midpoint_evidence is not None:
            raise SensitivityError("infeasible sensitivity evidence cannot authorize midpoint evidence")
        selection_basis = "baseline_fallback_selection_feasibility_failed"
        promotion_reasons.extend(
            f"infeasible_variant:{variant_id}"
            for variant_id in assessment.infeasible_variant_ids
        )
    elif bad_surfaces:
        if proposal is not None or midpoint_evidence is not None:
            raise SensitivityError("bad sensitivity surfaces cannot authorize midpoint evidence")
        selection_basis = "baseline_fallback_bad_surface"
        promotion_reasons.extend(
            f"{row.knob_path}:{row.shape}" for row in bad_surfaces
        )
    elif not assessment.surfaces:
        if proposal is not None or midpoint_evidence is not None:
            raise SensitivityError("baseline-only plan cannot accept midpoint evidence")
        selection_basis = "baseline_frozen_no_safe_numeric_knob"
    elif not one_sided:
        if proposal is not None or midpoint_evidence is not None:
            raise SensitivityError("two-sided plateau does not accept midpoint evidence")
        if any(row.plateau_side == "baseline" for row in assessment.surfaces):
            selection_basis = "baseline_frozen_already_passing"
        else:
            selection_basis = "baseline_frozen_two_sided_plateau"
    elif len(one_sided) > 1:
        if proposal is not None or midpoint_evidence is not None:
            raise SensitivityError("ambiguous one-sided plateaus cannot select a midpoint")
        selection_basis = "baseline_fallback_ambiguous_midpoint"
        promotion_reasons.append("multiple_one_sided_plateaus")
    else:
        if proposal is None or midpoint_evidence is None:
            raise SensitivityError("one-sided plateau requires midpoint validation evidence")
        if proposal.plan_id != plan.plan_id or proposal.assessment_id != assessment.assessment_id:
            raise SensitivityError("midpoint proposal identity does not match plan assessment")
        if midpoint_evidence.variant_id != proposal.variant.variant_id:
            raise SensitivityError("midpoint evidence identity does not match proposal")
        if midpoint_evidence.data_role != "validation_oos":
            raise SensitivityError("midpoint evidence must use validation_oos")
        fold_ids = tuple(row.fold_id for row in midpoint_evidence.folds)
        if fold_ids != assessment.validation_fold_ids:
            raise SensitivityError("midpoint evidence must use the original validation folds")
        midpoint_evidence_sha256 = _sha256(midpoint_evidence.to_payload())
        expected_counts = TrialCounts(
            distinct_variant_count=assessment.trial_counts.distinct_variant_count + 1,
            fold_evaluation_count=assessment.trial_counts.fold_evaluation_count,
            selection_count=assessment.trial_counts.selection_count + 1,
        )
        if proposal.trial_counts_after_registration != expected_counts:
            raise SensitivityError("midpoint proposal trial counts do not reconcile")
        surface = one_sided[0]
        threshold_utility = _utility(rule.pass_threshold, rule)
        aggregate_utility = _utility(midpoint_evidence.aggregate_value, rule)
        baseline_utility = _utility(surface.baseline_value, rule)
        fold_pass_share = sum(
            _utility(row.value, rule) >= threshold_utility
            for row in midpoint_evidence.folds
        ) / len(midpoint_evidence.folds)
        midpoint_valid = (
            midpoint_evidence.feasibility_passed
            and
            aggregate_utility >= threshold_utility
            and aggregate_utility >= baseline_utility - rule.plateau_tolerance
            and fold_pass_share >= rule.fold_consistency_min
        )
        counts = TrialCounts(
            distinct_variant_count=expected_counts.distinct_variant_count,
            fold_evaluation_count=(
                expected_counts.fold_evaluation_count + len(midpoint_evidence.folds)
            ),
            selection_count=expected_counts.selection_count + 1,
        )
        if midpoint_valid:
            selected = proposal.variant
            selection_basis = "midpoint_frozen_after_validation_oos"
        else:
            selection_basis = "baseline_fallback_midpoint_validation_failed"
            promotion_reasons.append(
                "midpoint_validation_failed"
                if midpoint_evidence.feasibility_passed
                else "midpoint_selection_feasibility_failed"
            )
    final_seed = {
        "schema": "axiom_rift_v2_sensitivity_finalization_seed_v1",
        "plan_id": plan.plan_id,
        "assessment_id": assessment.assessment_id,
        "selected_variant_id": selected.variant_id,
        "selected_variant_sha256": selected.variant_sha256,
        "selected_parameters_sha256": selected.parameters_sha256,
        "selection_basis": selection_basis,
        "source_data_role": "validation_oos",
        "freeze_target_role": "development_cv",
        "trial_counts": counts.to_payload(),
        "promotion_blocked": bool(promotion_reasons),
        "promotion_block_reasons": promotion_reasons,
        "midpoint_evidence_sha256": midpoint_evidence_sha256,
        "development_metrics_inspected": False,
    }
    final_sha256 = _sha256(final_seed)
    return SensitivityFinalization(
        finalization_id=f"V2SF{final_sha256[:12].upper()}",
        finalization_sha256=final_sha256,
        plan_id=plan.plan_id,
        assessment_id=assessment.assessment_id,
        selected_variant=selected,
        selection_basis=selection_basis,
        source_data_role="validation_oos",
        freeze_target_role="development_cv",
        trial_counts=counts,
        promotion_blocked=bool(promotion_reasons),
        promotion_block_reasons=tuple(promotion_reasons),
        midpoint_evidence_sha256=midpoint_evidence_sha256,
    )


__all__ = [
    "ALLOWED_TARGETS",
    "CalibrationProposal",
    "FoldFeasibility",
    "FoldMetric",
    "KnobSpec",
    "KnobSurface",
    "MAX_INITIAL_VARIANTS",
    "MAX_KNOBS",
    "MAX_LOCAL_CALIBRATION_EVALUATIONS_PER_OUTER_FOLD",
    "SensitivityAssessment",
    "SensitivityError",
    "SensitivityFinalization",
    "SensitivityPlan",
    "SensitivityVariant",
    "SurfaceRule",
    "TrialCounts",
    "VariantEvidence",
    "assess_sensitivity",
    "build_oat_plan",
    "finalize_sensitivity_choice",
    "propose_local_midpoint",
]
