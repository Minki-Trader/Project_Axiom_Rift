"""Pure declarative causal scout engine for V2 development folds."""

from __future__ import annotations

import bisect
import copy
import csv
import hashlib
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from axiom_rift.v2.data.blackouts import BoundaryGap, interval_crosses_non_allow_boundary, load_non_allow_gaps
from axiom_rift.v2.features import (
    FEATURE_NAMES,
    WARMUP_BARS,
    BarArrays,
    FeatureMatrix,
    FeatureContractError,
    bars_from_rows,
    compute_feature_matrix,
    feature_order_sha256,
    feature_program_sha256,
    load_feature_contract,
)
from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.research.autonomy import (
    AutonomyGuardError,
    HypothesisBatch,
    assert_no_scientific_inheritance,
)
from axiom_rift.v2.research.evaluation import (
    Comparison,
    EvaluationProfile,
    FailureEffect,
    MetricObservation,
    MetricRule,
    STANDARD_DIMENSIONS,
    Stage,
    SensitivityState,
    TuningContext,
    TuningRole,
    interpret_kpis,
)
from axiom_rift.v2.research.programs import (
    ProgramRegistryError,
    load_program_registry,
)
from axiom_rift.v2.research.sensitivity import (
    SensitivityAssessment,
    SensitivityError,
    SensitivityPlan,
    SensitivityVariant,
    SurfaceRule,
    VariantEvidence,
    assess_sensitivity,
    build_oat_plan,
    finalize_sensitivity_choice,
    propose_local_midpoint,
)


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class ScoutSpecError(ValueError):
    """Raised when a scout spec exceeds the declarative whitelist."""


@dataclass(frozen=True)
class FoldWindow:
    development_id: str
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    development_start: datetime
    development_end: datetime


@dataclass(frozen=True)
class ScoutSpec:
    goal_id: str
    hypothesis_id: str
    feature_program_id: str
    feature_contract_path: Path
    label_program_id: str
    model_program_id: str
    calibration_program_id: str
    selector_program_id: str
    trade_program_id: str
    alpha: float
    residual_quantile: float
    hold_bars: int
    point_size: float
    maximum_daily_entries: int
    anchors: tuple[str, ...]
    acceptance_profile: dict[str, Any]
    program_registry_path: str
    program_registry_sha256: str
    program_identities: dict[str, dict[str, Any]]
    spec_sha256: str
    hypothesis_schema: str = "axiom_rift_v2_hypothesis_v1"
    sensitivity_plan: dict[str, Any] | None = None
    trial_plan: dict[str, Any] | None = None
    evaluation_profile: EvaluationProfile | None = None
    oat_plan: SensitivityPlan | None = None
    surface_rule: SurfaceRule | None = None
    selection_feasibility: dict[str, Any] | None = None
    executable_programs: dict[str, Any] | None = None
    acceptance_profile_sha256: str | None = None
    split_set_id: str | None = None


@dataclass(frozen=True)
class PreparedFold:
    """Shared causal fold material prepared once for nested selection."""

    window: FoldWindow
    bars: BarArrays
    feature_matrix: FeatureMatrix
    train_indices: np.ndarray
    train_x: np.ndarray
    train_y: np.ndarray
    validation_indices: np.ndarray
    validation_x: np.ndarray
    validation_y: np.ndarray
    development_indices: np.ndarray
    development_x: np.ndarray
    train_bounds: tuple[int, int]
    validation_bounds: tuple[int, int]
    development_bounds: tuple[int, int]
    validation_allowed: np.ndarray
    development_allowed: np.ndarray


@dataclass(frozen=True)
class ModelBundle:
    fold_id: str
    feature_names: tuple[str, ...]
    scaler_mean: tuple[float, ...]
    scaler_scale: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    residual_band: float

    def predict(self, values: np.ndarray) -> np.ndarray:
        mean = np.asarray(self.scaler_mean, dtype=np.float64)
        scale = np.asarray(self.scaler_scale, dtype=np.float64)
        coefficient = np.asarray(self.coefficients, dtype=np.float64)
        return ((np.asarray(values, dtype=np.float64) - mean) / scale) @ coefficient + self.intercept

    def to_payload(self) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "feature_names": list(self.feature_names),
            "scaler_mean": list(self.scaler_mean),
            "scaler_scale": list(self.scaler_scale),
            "coefficients": list(self.coefficients),
            "intercept": self.intercept,
            "residual_band": self.residual_band,
        }


@dataclass(frozen=True)
class LinearFit:
    fold_id: str
    scaler_mean: tuple[float, ...]
    scaler_scale: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    absolute_validation_residuals: tuple[float, ...]

    def bundle(self, residual_quantile: float) -> ModelBundle:
        band = float(
            np.quantile(
                np.asarray(self.absolute_validation_residuals, dtype=np.float64),
                residual_quantile,
            )
        )
        return ModelBundle(
            fold_id=self.fold_id,
            feature_names=FEATURE_NAMES,
            scaler_mean=self.scaler_mean,
            scaler_scale=self.scaler_scale,
            coefficients=self.coefficients,
            intercept=self.intercept,
            residual_band=band,
        )


@dataclass(frozen=True)
class ScoutTrade:
    fold_id: str
    signal_time: str
    entry_time: str
    exit_time: str
    direction: int
    score: float
    residual_band: float
    causal_cost_edge: float
    gross_broker_points: float | None
    spread_cost_broker_points: float | None
    net_broker_points: float | None
    evaluable_after_cost: bool
    exclusion_reason: str | None
    market_day: str
    market_hour: int
    decision_spread_broker_points: float | None = None
    applicable_execution_spread_broker_points: float | None = None
    cost_source: str | None = None
    execution_spread_fallback_used: bool | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "fold_id": self.fold_id,
            "signal_time": self.signal_time,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "direction": self.direction,
            "score": self.score,
            "residual_band": self.residual_band,
            "causal_cost_edge": self.causal_cost_edge,
            "gross_broker_points": self.gross_broker_points,
            "spread_cost_broker_points": self.spread_cost_broker_points,
            "net_broker_points": self.net_broker_points,
            "evaluable_after_cost": self.evaluable_after_cost,
            "exclusion_reason": self.exclusion_reason,
            "market_day": self.market_day,
            "market_hour": self.market_hour,
        }
        if self.decision_spread_broker_points is not None:
            payload.update(
                {
                    "decision_spread_broker_points": (
                        self.decision_spread_broker_points
                    ),
                    "applicable_execution_spread_broker_points": (
                        self.applicable_execution_spread_broker_points
                    ),
                    "cost_source": self.cost_source,
                    "execution_spread_fallback_used": (
                        self.execution_spread_fallback_used
                    ),
                }
            )
        return payload


@dataclass(frozen=True)
class ScoutResult:
    outcome: str
    gate_passed: bool
    metrics: dict[str, Any]
    causal_checks: dict[str, Any]
    models: tuple[ModelBundle, ...]
    trades: tuple[ScoutTrade, ...]
    result_sha256: str
    claim_ceiling: str = "diagnostic_observation"
    economics_claim_allowed: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_scout_result_v1",
            "outcome": self.outcome,
            "gate_passed": self.gate_passed,
            "metrics": self.metrics,
            "causal_checks": self.causal_checks,
            "models": [model.to_payload() for model in self.models],
            "trades": [trade.to_payload() for trade in self.trades],
            "result_sha256": self.result_sha256,
            "claim_ceiling": self.claim_ceiling,
            "economics_claim_allowed": self.economics_claim_allowed,
        }


@dataclass(frozen=True)
class NestedScoutResult:
    outcome: str
    gate_passed: bool
    metrics: dict[str, Any]
    causal_checks: dict[str, Any]
    models: tuple[ModelBundle, ...]
    trades: tuple[ScoutTrade, ...]
    nested_selection: dict[str, Any]
    trial_accounting: dict[str, Any]
    selection_rule_sha256: str
    selected_variant_hashes: dict[str, str]
    selected_configuration_hashes: dict[str, str]
    selected_model_bundle_sha256s: dict[str, str]
    selected_path_hashes: dict[str, str]
    result_sha256: str
    claim_ceiling: str = "diagnostic_observation"
    economics_claim_allowed: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_nested_scout_result_v1",
            "outcome": self.outcome,
            "gate_passed": self.gate_passed,
            "metrics": self.metrics,
            "causal_checks": self.causal_checks,
            "models": [model.to_payload() for model in self.models],
            "trades": [trade.to_payload() for trade in self.trades],
            "nested_selection": self.nested_selection,
            "trial_accounting": self.trial_accounting,
            "selection_rule_sha256": self.selection_rule_sha256,
            "selected_variant_hashes": self.selected_variant_hashes,
            "selected_configuration_hashes": self.selected_configuration_hashes,
            "selected_model_bundle_sha256s": self.selected_model_bundle_sha256s,
            "selected_path_hashes": self.selected_path_hashes,
            "result_sha256": self.result_sha256,
            "claim_ceiling": self.claim_ceiling,
            "economics_claim_allowed": self.economics_claim_allowed,
        }


def _load_evaluation_profile(acceptance: Mapping[str, Any]) -> EvaluationProfile:
    profile_id = acceptance.get("profile_id")
    rules_payload = acceptance.get("resolved_rules")
    profile_sha256 = acceptance.get("profile_sha256")
    dimension_order = acceptance.get(
        "dimension_order",
        list(STANDARD_DIMENSIONS),
    )
    if acceptance.get("frozen_before_results") is not True:
        raise ScoutSpecError("acceptance profile was not frozen before results")
    if not isinstance(profile_id, str) or not profile_id:
        raise ScoutSpecError("hypothesis v2 acceptance profile_id is missing")
    if not isinstance(rules_payload, list) or not rules_payload:
        raise ScoutSpecError("hypothesis v2 requires nonempty resolved metric rules")
    if not isinstance(dimension_order, list) or not all(
        isinstance(value, str) and value for value in dimension_order
    ):
        raise ScoutSpecError("hypothesis v2 dimension_order is invalid")
    hash_payload = {
        "profile_id": profile_id,
        "resolved_rules": rules_payload,
        "dimension_order": dimension_order,
    }
    if profile_sha256 != sha256_payload(hash_payload):
        raise ScoutSpecError("hypothesis v2 acceptance profile hash mismatch")
    common_keys = {
        "name",
        "dimension",
        "comparison",
        "stages",
        "required_stages",
        "failure_effect",
        "tuning_role",
    }
    comparison_keys = {
        "minimum": {"pass_at", "fail_below"},
        "maximum": {"pass_at", "fail_above"},
        "range": {"pass_min", "pass_max", "fail_below", "fail_above"},
        "equal": {"expected"},
    }
    rules: list[MetricRule] = []
    for row in rules_payload:
        if not isinstance(row, Mapping):
            raise ScoutSpecError("resolved metric rule must be a mapping")
        comparison = row.get("comparison")
        if comparison not in comparison_keys:
            raise ScoutSpecError(f"unsupported resolved comparison: {comparison}")
        unknown = set(row) - common_keys - comparison_keys[str(comparison)]
        if unknown:
            raise ScoutSpecError(
                "resolved metric rule contains unknown keys: " + ", ".join(sorted(unknown))
            )
        stages = row.get("stages")
        required_stages = row.get("required_stages", stages)
        if not isinstance(stages, list) or not isinstance(required_stages, list):
            raise ScoutSpecError("resolved metric rule stages must be lists")
        try:
            effect = FailureEffect(str(row.get("failure_effect", "reject")))
            tuning_role = TuningRole(str(row.get("tuning_role", "none")))
            common = {
                "name": str(row["name"]),
                "dimension": str(row["dimension"]),
                "stages": tuple(stages),
                "required_stages": tuple(required_stages),
                "failure_effect": effect,
                "tuning_role": tuning_role,
            }
            if comparison == "minimum":
                rule = MetricRule.minimum(
                    **common,
                    pass_at=float(row["pass_at"]),
                    fail_below=None if row.get("fail_below") is None else float(row["fail_below"]),
                )
            elif comparison == "maximum":
                rule = MetricRule.maximum(
                    **common,
                    pass_at=float(row["pass_at"]),
                    fail_above=None if row.get("fail_above") is None else float(row["fail_above"]),
                )
            elif comparison == "range":
                rule = MetricRule.range(
                    **common,
                    pass_min=float(row["pass_min"]),
                    pass_max=float(row["pass_max"]),
                    fail_below=None if row.get("fail_below") is None else float(row["fail_below"]),
                    fail_above=None if row.get("fail_above") is None else float(row["fail_above"]),
                )
            else:
                rule = MetricRule.equal(**common, expected=row["expected"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ScoutSpecError(f"invalid resolved metric rule: {exc}") from exc
        rules.append(rule)
    return EvaluationProfile(
        profile_id=profile_id,
        rules=tuple(rules),
        dimension_order=tuple(dimension_order),
    )


def load_evaluation_profile(acceptance: Mapping[str, Any]) -> EvaluationProfile:
    """Load one frozen profile for execution and independent receipt replay."""

    return _load_evaluation_profile(acceptance)


def _require_mandatory_s_rules(profile: EvaluationProfile) -> None:
    rules = {rule.name: rule for rule in profile.rules}
    required = {
        "causal_checks_all_pass": ("integrity", Comparison.EQUAL, FailureEffect.REPAIR),
        "evaluable_trade_count": (
            "inferential_density",
            Comparison.MINIMUM,
            FailureEffect.REJECT,
        ),
        "unknown_cost_observation_count": (
            {"economics", "integrity"},
            Comparison.MAXIMUM,
            FailureEffect.EVIDENCE_GAP,
        ),
        "net_broker_points": ("economics", Comparison.MINIMUM, FailureEffect.REJECT),
        "positive_net_fold_count": ("stability", Comparison.MINIMUM, FailureEffect.REJECT),
    }
    missing = sorted(set(required) - set(rules))
    if missing:
        raise ScoutSpecError("mandatory S rules are missing: " + ", ".join(missing))
    for name, (dimension, comparison, effect) in required.items():
        rule = rules[name]
        allowed_dimensions = dimension if isinstance(dimension, set) else {dimension}
        if (
            rule.dimension not in allowed_dimensions
            or rule.comparison is not comparison
            or rule.failure_effect is not effect
            or Stage.S not in rule.required_stages
        ):
            raise ScoutSpecError(f"mandatory S rule semantics differ: {name}")
        if comparison is Comparison.MINIMUM and rule.hard_min is not None:
            raise ScoutSpecError(f"mandatory S minimum cannot have a warning band: {name}")
        if comparison is Comparison.MAXIMUM and rule.hard_max is not None:
            raise ScoutSpecError(f"mandatory S maximum cannot have a warning band: {name}")
    causal = rules["causal_checks_all_pass"]
    if causal.expected is not True:
        raise ScoutSpecError("causal_checks_all_pass must require true")
    density = rules["evaluable_trade_count"]
    positive_folds = rules["positive_net_fold_count"]
    if density.pass_min is None or density.pass_min <= 0 or not density.pass_min.is_integer():
        raise ScoutSpecError("evaluable_trade_count threshold must be a positive integer")
    if (
        positive_folds.pass_min is None
        or positive_folds.pass_min <= 0
        or not positive_folds.pass_min.is_integer()
    ):
        raise ScoutSpecError("positive_net_fold_count threshold must be a positive integer")
    unknown_cost = rules["unknown_cost_observation_count"]
    if unknown_cost.pass_max != 0.0:
        raise ScoutSpecError("unknown_cost_observation_count maximum must be zero")


def _configuration_sha256(
    *,
    executable_programs: Mapping[str, Any],
    parameters: Mapping[str, Any],
) -> str:
    effective_programs = copy.deepcopy(dict(executable_programs))
    for program_name, parameter_group, parameter_name in (
        ("model_program", "model", "alpha"),
        ("calibration_program", "calibration", "quantile"),
    ):
        group = parameters.get(parameter_group)
        program = effective_programs.get(program_name)
        if isinstance(group, Mapping) and parameter_name in group:
            if not isinstance(program, Mapping):
                raise ScoutSpecError(
                    f"{program_name} must be a mapping for configuration identity"
                )
            effective_programs[program_name] = {
                **dict(program),
                parameter_name: group[parameter_name],
            }
    return sha256_payload(
        {
            "schema": "axiom_rift_v2_executable_configuration_v1",
            "executable_programs": effective_programs,
            "variant_parameters": dict(parameters),
        }
    )


def _history_sha256(configuration_hashes: list[str]) -> str:
    return sha256_payload(sorted(configuration_hashes))


def _validate_scientific_bundle_hypothesis(
    *,
    payload: Mapping[str, Any],
    project_root: Path | None,
    hypothesis_batch: HypothesisBatch,
    evaluation_profile: EvaluationProfile,
    sensitivity: Mapping[str, Any],
    trials: Mapping[str, Any],
    programs: Mapping[str, Any],
    data: Mapping[str, Any],
    evidence_budget: Mapping[str, Any],
) -> dict[str, Any]:
    if project_root is None:
        raise ScoutSpecError("scientific bundle validation requires the project root")
    descriptor = payload.get("program_registry")
    if not isinstance(descriptor, Mapping) or set(descriptor) != {"path", "sha256"}:
        raise ScoutSpecError("scientific hypothesis program registry binding is incomplete")
    registry_path = descriptor.get("path")
    registry_sha256 = descriptor.get("sha256")
    if not isinstance(registry_path, str) or not isinstance(registry_sha256, str):
        raise ScoutSpecError("scientific hypothesis program registry binding is invalid")
    try:
        from axiom_rift.v2.research.scientific_programs import (
            BUNDLE_ROLE_NAMES,
            bind_compression_release_runtime,
            build_scientific_bundle_batch,
            load_scientific_program_registry,
        )
        from axiom_rift.v2.research.compression_release import (
            COMPRESSION_RELEASE_EXECUTABLE_SHA256,
        )
        from axiom_rift.v2.research.scientific_scout import (
            SCIENTIFIC_SELECTION_RULE_SHA256,
        )

        registry = load_scientific_program_registry(project_root, Path(registry_path))
        bundle_batch = build_scientific_bundle_batch(registry, programs)
        release_configuration_hashes = bind_compression_release_runtime(
            registry, bundle_batch
        )
    except (ImportError, ValueError) as exc:
        raise ScoutSpecError(f"scientific program bundle is invalid: {exc}") from exc
    if registry.registry_sha256 != registry_sha256:
        raise ScoutSpecError("scientific program registry hash differs from the H binding")
    if tuple(bundle_batch.bundles) != tuple(BUNDLE_ROLE_NAMES):
        raise ScoutSpecError("compression-release H requires all five registered bundle roles")
    trade_implementation_keys = {
        bundle.programs["trade"].implementation_key
        for bundle in bundle_batch.bundles.values()
    }
    selector_implementation_keys = {
        bundle.programs["selector"].implementation_key
        for bundle in bundle_batch.bundles.values()
    }
    if len(trade_implementation_keys) != 1 or len(selector_implementation_keys) != 1:
        raise ScoutSpecError(
            "compression-release H may not mix selector or trade implementations"
        )
    trade_implementation_key = next(iter(trade_implementation_keys))
    selector_implementation_key = next(iter(selector_implementation_keys))
    causal_spread_floor = (
        trade_implementation_key == "fixed_6bar_causal_spread_floor_v1"
    )
    bundle_hashes = dict(bundle_batch.bundle_role_hashes)
    if dict(hypothesis_batch.bundle_roles) != bundle_hashes:
        raise ScoutSpecError("autonomy batch differs from the registered scientific bundles")
    if (
        programs.get("runtime_sha256") != registry.runtime_sha256
        or programs.get("runtime_executable_sha256")
        != COMPRESSION_RELEASE_EXECUTABLE_SHA256
        or programs.get("release_configuration_hashes")
        != dict(release_configuration_hashes)
        or programs.get("selection_rule_sha256")
        != SCIENTIFIC_SELECTION_RULE_SHA256
    ):
        raise ScoutSpecError(
            "compression-release runtime identity differs from executable programs"
        )
    if hypothesis_batch.scout_mode != "s_breadth":
        raise ScoutSpecError("compression-release H autonomy route is invalid")
    if causal_spread_floor:
        if (
            hypothesis_batch.hypothesis_type != "coupled_mechanism"
            or hypothesis_batch.dominant_axis != "axis_trade"
            or set(hypothesis_batch.coupled_program_kinds)
            != {"selector", "trade"}
            or selector_implementation_key
            != "chronological_compression_cost_gated_selector_v1"
        ):
            raise ScoutSpecError(
                "causal-spread-floor H autonomy coupling is invalid"
            )
    elif (
        trade_implementation_key != "fixed_6bar_observed_spread_v1"
        or selector_implementation_key
        != "chronological_compression_selector_v1"
        or hypothesis_batch.hypothesis_type != "structural_batch"
        or hypothesis_batch.dominant_axis != "axis_selector"
        or hypothesis_batch.coupled_program_kinds
    ):
        raise ScoutSpecError("compression-release H autonomy route is invalid")
    knobs = tuple(hypothesis_batch.numeric_knobs)
    if len(knobs) != 1 or (
        knobs[0].path,
        float(knobs[0].low),
        float(knobs[0].baseline),
        float(knobs[0].high),
    ) != ("selector.compression_ratio_max", 2.0, 2.5, 3.0):
        raise ScoutSpecError("compression-release H numeric surface is invalid")
    if hypothesis_batch.local_calibration_rounds != 0:
        raise ScoutSpecError("compression-release H does not preregister local calibration")
    expected_policy = {
        "selector": {
            "compression_ratio_max": {
                "type": "float",
                "low": 2.0,
                "baseline": 2.5,
                "high": 3.0,
            }
        }
    }
    if (
        sensitivity.get("enabled") is not True
        or sensitivity.get("disabled_reason") not in {None, ""}
        or sensitivity.get("data_role") != "validation_oos"
        or sensitivity.get("development_variant_selection_allowed") is not False
        or sensitivity.get("holdout_revealed") is not False
        or sensitivity.get("candidate_frozen") is not False
        or sensitivity.get("policy") != expected_policy
        or sensitivity.get("local_calibration_rounds_max") != 0
    ):
        raise ScoutSpecError("compression-release H sensitivity policy is invalid")
    feasibility = sensitivity.get("selection_feasibility")
    expected_feasibility = {
        "causal_checks_required": True,
        "unknown_cost_observation_count_max": 0,
        "evaluable_trade_count_min_per_fold": 20,
    }
    if feasibility != expected_feasibility:
        raise ScoutSpecError("compression-release H selection feasibility is invalid")
    surface_payload = sensitivity.get("surface_rule")
    if not isinstance(surface_payload, Mapping):
        raise ScoutSpecError("compression-release H surface rule is missing")
    try:
        surface_rule = SurfaceRule(
            metric_name=str(surface_payload["metric_name"]),
            higher_is_better=surface_payload["higher_is_better"],
            pass_threshold=float(surface_payload["pass_threshold"]),
            plateau_tolerance=float(surface_payload["plateau_tolerance"]),
            fold_consistency_min=float(surface_payload.get("fold_consistency_min", 0.67)),
            viability_threshold=(
                None
                if surface_payload.get("viability_threshold") is None
                else float(surface_payload["viability_threshold"])
            ),
        )
    except (KeyError, TypeError, ValueError, SensitivityError) as exc:
        raise ScoutSpecError(f"compression-release H surface rule is invalid: {exc}") from exc
    if not (
        surface_rule.metric_name == "net_broker_points"
        and surface_rule.higher_is_better is True
        and surface_rule.pass_threshold == 0.01
        and surface_rule.effective_viability_threshold == 0.0
        and surface_rule.plateau_tolerance == 100.0
        and surface_rule.fold_consistency_min == 0.67
    ):
        raise ScoutSpecError("compression-release H surface thresholds differ from preregistration")
    surface_metric = next(
        (rule for rule in evaluation_profile.rules if rule.name == "net_broker_points"),
        None,
    )
    if surface_metric is None or Stage.S not in surface_metric.applicable_stages:
        raise ScoutSpecError("compression-release surface metric is not an S rule")
    profile_rules = {rule.name: rule for rule in evaluation_profile.rules}
    if (
        profile_rules["evaluable_trade_count"].pass_min != 60.0
        or profile_rules["unknown_cost_observation_count"].pass_max != 0.0
        or profile_rules["net_broker_points"].pass_min != 0.01
        or profile_rules["positive_net_fold_count"].pass_min != 2.0
        or profile_rules["causal_checks_all_pass"].expected is not True
    ):
        raise ScoutSpecError(
            "compression-release acceptance thresholds differ from the hard S profile"
        )
    if causal_spread_floor:
        shadow_count = profile_rules.get("shadow_evaluable_trade_count")
        shadow_net = profile_rules.get("shadow_net_broker_points")
        shadow_folds = profile_rules.get("shadow_positive_net_fold_count")
        if (
            shadow_count is None
            or shadow_count.dimension != "inferential_density"
            or shadow_count.comparison is not Comparison.MINIMUM
            or shadow_count.pass_min != 60.0
            or shadow_count.failure_effect is not FailureEffect.EVIDENCE_GAP
            or shadow_net is None
            or shadow_net.dimension != "economics"
            or shadow_net.comparison is not Comparison.MINIMUM
            or shadow_net.pass_min != 0.01
            or shadow_net.failure_effect is not FailureEffect.REJECT
            or shadow_folds is None
            or shadow_folds.dimension != "stability"
            or shadow_folds.comparison is not Comparison.MINIMUM
            or shadow_folds.pass_min != 2.0
            or shadow_folds.failure_effect is not FailureEffect.REJECT
        ):
            raise ScoutSpecError(
                "causal-spread-floor H requires the strict observed-cost shadow"
            )
    elif set(profile_rules) != {
        "causal_checks_all_pass",
        "evaluable_trade_count",
        "unknown_cost_observation_count",
        "net_broker_points",
        "positive_net_fold_count",
    }:
        raise ScoutSpecError(
            "legacy compression-release H acceptance profile has drifted"
        )
    try:
        data_config = yaml.safe_load(
            (project_root / "configs/v2/data.yaml").read_text(encoding="ascii")
        )
        split_config = yaml.safe_load(
            (project_root / "configs/v2/splits.yaml").read_text(encoding="ascii")
        )
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ScoutSpecError(f"scientific data binding is unreadable: {exc}") from exc
    if not isinstance(data_config, Mapping) or not isinstance(split_config, Mapping):
        raise ScoutSpecError("scientific data configs must be mappings")
    processed = data_config.get("processed")
    boundary = data_config.get("boundary_source")
    split_source = split_config.get("source")
    lineage = data_config.get("lineage_requirements")
    if not all(
        isinstance(row, Mapping)
        for row in (processed, boundary, split_source, lineage)
    ):
        raise ScoutSpecError("scientific data config bindings are incomplete")
    expected_data = {
        "dataset_id": data_config.get("dataset_id"),
        "split_set_id": split_config.get("split_set_id"),
        "material_ids": sorted(
            [
                str(split_config.get("dataset_material_id")),
                str(lineage.get("split_set_material_id")),
                str(lineage.get("boundary_mask_material_id")),
                str(lineage.get("symbol_snapshot_material_id")),
            ]
        ),
        "dataset": {
            "material_id": split_config.get("dataset_material_id"),
            "path": processed.get("path"),
            "sha256": processed.get("sha256"),
        },
        "split_source": {
            "material_id": lineage.get("split_set_material_id"),
            "path": split_source.get("path"),
            "sha256": split_source.get("sha256"),
        },
        "boundary_source": {
            "material_id": lineage.get("boundary_mask_material_id"),
            "path": boundary.get("path"),
            "sha256": boundary.get("sha256"),
            "non_allow_boundary_count": boundary.get(
                "non_allow_boundary_count"
            ),
        },
        "symbol_material_id": lineage.get("symbol_snapshot_material_id"),
        "scout_anchor_ids": ["V2D002", "V2D005", "V2D008"],
        "tail_access": "forbidden",
        "forward_holdout_access": "forbidden",
        "real_volume_used": False,
        "external_source_ids": [],
    }
    if causal_spread_floor:
        cost_quality = data_config.get("cost_quality")
        active_fallback = (
            cost_quality.get("active_causal_fallback")
            if isinstance(cost_quality, Mapping)
            else None
        )
        expected_fallback = {
            "policy_id": "V2CF0001",
            "program_id": "V2TP1002",
            "selector_program_ids": [
                "V2SEL2001",
                "V2SEL2002",
                "V2SEL2003",
                "V2SEL2004",
                "V2SEL2005",
            ],
            "implementation_key": "fixed_6bar_causal_spread_floor_v1",
            "decision_zero_action": "reject_signal_admission",
            "positive_execution_rule": "max_decision_and_execution_spread",
            "execution_zero_action": "positive_decision_spread_floor",
            "negative_or_nonfinite_action": "data_integrity_failure",
            "true_cost_upper_bound_claim": False,
            "after_cost_metric_state": "causal_policy_evaluable",
            "after_cost_metric_state_is_observed_cost": False,
            "observed_execution_shadow_required_before_R": True,
            "policy_parameter_count": 0,
            "external_source_ids": [],
        }
        if (
            not isinstance(cost_quality, Mapping)
            or cost_quality.get("causal_fallback_allowed_only_when_preregistered")
            is not True
            or active_fallback != expected_fallback
        ):
            raise ScoutSpecError(
                "causal-spread-floor H data policy is not active and exact"
            )
        expected_data["causal_cost_policy"] = expected_fallback
    if dict(data) != expected_data:
        raise ScoutSpecError("compression-release H data binding is invalid")
    for descriptor in (
        expected_data["dataset"],
        expected_data["split_source"],
        expected_data["boundary_source"],
    ):
        source_path = project_root / str(descriptor["path"])
        if (
            not source_path.is_file()
            or hashlib.sha256(source_path.read_bytes()).hexdigest()
            != descriptor["sha256"]
        ):
            raise ScoutSpecError(
                f"compression-release H data file hash differs: {descriptor['path']}"
            )
    if trials.get("frozen_before_results") is not True:
        raise ScoutSpecError("compression-release trial plan was not frozen")
    family_id = trials.get("family_id")
    if not isinstance(family_id, str) or family_id != hypothesis_batch.family_id:
        raise ScoutSpecError("compression-release trial family differs from autonomy")
    exact_caps = {
        "unique_variant_cap": 5,
        "validation_evaluation_cell_cap": 15,
        "local_calibration_new_evaluations_per_outer_fold_max": 0,
        "development_paths_per_fold_max": 1,
    }
    if any(trials.get(field) != value for field, value in exact_caps.items()):
        raise ScoutSpecError("compression-release trial caps are invalid")
    for prefix in ("family", "global"):
        hashes = trials.get(f"{prefix}_configuration_hashes_before")
        count = trials.get(f"{prefix}_trials_before")
        history_hash = trials.get(f"{prefix}_history_sha256_before")
        if (
            not isinstance(hashes, list)
            or hashes != sorted(set(hashes))
            or not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes)
            or count != len(hashes)
            or history_hash != sha256_payload(hashes)
        ):
            raise ScoutSpecError(f"compression-release {prefix} trial history is invalid")
    timeout_seconds = evidence_budget.get("job_timeout_seconds")
    expected_evidence_budget = {
        "scout_jobs_max": 1,
        "configuration_trials_max": 5,
        "validation_evaluation_cells_max": 15,
        "development_paths_per_fold_max": 1,
        "mt5_runs_max": 0,
        "holdout_reveals_max": 0,
        "job_timeout_seconds": timeout_seconds,
    }
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 30 < timeout_seconds <= 3600
        or dict(evidence_budget) != expected_evidence_budget
    ):
        raise ScoutSpecError("compression-release evidence budget is invalid")
    return {
        "evaluation_profile": evaluation_profile,
        "sensitivity_plan": None,
        "surface_rule": surface_rule,
        "trial_plan": dict(trials),
        "selection_feasibility": dict(expected_feasibility),
        "initial_configuration_hashes": sorted(bundle_hashes.values()),
        "hypothesis_batch": hypothesis_batch,
        "scientific_program_registry": registry,
        "scientific_bundle_batch": bundle_batch,
        "release_configuration_hashes": dict(release_configuration_hashes),
        "runtime_sha256": registry.runtime_sha256,
        "runtime_executable_sha256": COMPRESSION_RELEASE_EXECUTABLE_SHA256,
        "selection_rule_sha256": SCIENTIFIC_SELECTION_RULE_SHA256,
        "trade_implementation_key": trade_implementation_key,
    }


def validate_hypothesis_v2_payload(
    payload: Mapping[str, Any],
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Validate result-independent V2 H policy before any ledger commit."""

    if not isinstance(payload, Mapping) or payload.get("schema") != "axiom_rift_v2_hypothesis_v2":
        raise ScoutSpecError("active hypothesis must use axiom_rift_v2_hypothesis_v2")
    required_sections = {
        "autonomy_batch",
        "executable_programs",
        "data",
        "falsification",
        "acceptance_profile",
        "sensitivity_plan",
        "trial_plan",
        "routing",
        "evidence_budget",
    }
    missing = sorted(required_sections - set(payload))
    if missing:
        raise ScoutSpecError("hypothesis v2 is missing sections: " + ", ".join(missing))
    if payload.get("status") != "preregistered" or payload.get("v1_evidence_inherited") is not False:
        raise ScoutSpecError("hypothesis v2 must be fresh and preregistered")
    if payload.get("scientific_origin") != "v2_current":
        raise ScoutSpecError("hypothesis v2 scientific origin is invalid")
    try:
        assert_no_scientific_inheritance(payload)
        hypothesis_batch = HypothesisBatch.from_payload(payload["autonomy_batch"])
    except (AutonomyGuardError, KeyError, TypeError) as exc:
        raise ScoutSpecError(f"hypothesis v2 autonomy batch is invalid: {exc}") from exc
    hypothesis_id = payload.get("hypothesis_id")
    if not isinstance(hypothesis_id, str) or re.fullmatch(r"V2H[0-9]{4}", hypothesis_id) is None:
        raise ScoutSpecError("hypothesis v2 identity is invalid")
    if hypothesis_batch.hypothesis_id != hypothesis_id:
        raise ScoutSpecError("autonomy batch hypothesis identity differs")
    if payload.get("scientific_epoch_id") != hypothesis_batch.scientific_epoch_id:
        raise ScoutSpecError("outer scientific epoch differs from autonomy batch")
    acceptance = payload.get("acceptance_profile")
    sensitivity = payload.get("sensitivity_plan")
    trials = payload.get("trial_plan")
    programs = payload.get("executable_programs")
    data = payload.get("data")
    falsification = payload.get("falsification")
    routing = payload.get("routing")
    evidence_budget = payload.get("evidence_budget")
    if not all(isinstance(row, Mapping) for row in (acceptance, sensitivity, trials, programs, data)):
        raise ScoutSpecError("hypothesis v2 declarative sections must be mappings")
    if not all(isinstance(row, Mapping) for row in (falsification, routing, evidence_budget)):
        raise ScoutSpecError("hypothesis v2 decision and budget sections must be mappings")
    for field in (
        "scientific_reject_conditions",
        "repair_conditions",
        "scale_miss_conditions",
    ):
        conditions = falsification.get(field)
        if not isinstance(conditions, list) or not conditions or not all(
            isinstance(value, str) and value for value in conditions
        ):
            raise ScoutSpecError(f"hypothesis v2 falsification is incomplete: {field}")
    expected_routing = {
        "broken_execution": "repair_same_scope",
        "scientific_reject": "record_negative_memory_then_rotate",
        "scientific_survive": "advance_by_stage_gate",
        "holdout_informed_redesign": "forbidden",
    }
    if dict(routing) != expected_routing:
        raise ScoutSpecError("hypothesis v2 routing policy is incomplete")
    evaluation_profile = _load_evaluation_profile(acceptance)
    _require_mandatory_s_rules(evaluation_profile)
    if programs.get("schema") == "axiom_rift_v2_scientific_bundle_batch_spec_v1":
        return _validate_scientific_bundle_hypothesis(
            payload=payload,
            project_root=project_root,
            hypothesis_batch=hypothesis_batch,
            evaluation_profile=evaluation_profile,
            sensitivity=sensitivity,
            trials=trials,
            programs=programs,
            data=data,
            evidence_budget=evidence_budget,
        )
    required_program_sections = {
        "feature_program",
        "label_program",
        "model_program",
        "calibration_program",
        "selector_program",
        "trade_program",
    }
    if set(programs) != required_program_sections or not all(
        isinstance(programs.get(name), Mapping) for name in required_program_sections
    ):
        raise ScoutSpecError("hypothesis v2 executable program surface is incomplete")
    if any(
        not isinstance(programs[name].get("id"), str) or not programs[name].get("id")
        for name in required_program_sections
    ):
        raise ScoutSpecError("hypothesis v2 executable program identity is missing")
    try:
        horizon = int(programs["label_program"]["horizon_bars_after_entry"])
        hold_bars = int(programs["trade_program"]["hold_bars"])
        daily_cap = int(programs["selector_program"]["daily_entry_safety_cap"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ScoutSpecError(f"hypothesis v2 executable program parameters are invalid: {exc}") from exc
    if horizon <= 0 or horizon != hold_bars or daily_cap <= 0:
        raise ScoutSpecError("hypothesis v2 label, trade, or selector semantics are invalid")
    if sensitivity.get("data_role") != "validation_oos":
        raise ScoutSpecError("hypothesis v2 sensitivity must use validation_oos only")
    if sensitivity.get("development_variant_selection_allowed") is not False:
        raise ScoutSpecError("hypothesis v2 must forbid development variant selection")
    if sensitivity.get("holdout_revealed") is not False or sensitivity.get("candidate_frozen") is not False:
        raise ScoutSpecError("hypothesis v2 sensitivity cannot start after freeze or holdout")
    policy = sensitivity.get("policy")
    surface_payload = sensitivity.get("surface_rule")
    feasibility = sensitivity.get("selection_feasibility")
    enabled = sensitivity.get("enabled")
    disabled_reason = sensitivity.get("disabled_reason")
    model = programs.get("model_program") if isinstance(programs, Mapping) else None
    calibration = programs.get("calibration_program") if isinstance(programs, Mapping) else None
    if not all(isinstance(row, Mapping) for row in (policy, surface_payload, feasibility)):
        raise ScoutSpecError("hypothesis v2 sensitivity policy or surface rule is missing")
    if set(feasibility) != {
        "causal_checks_required",
        "unknown_cost_observation_count_max",
        "evaluable_trade_count_min_per_fold",
    }:
        raise ScoutSpecError("selection_feasibility fields are incomplete")
    minimum_per_fold = feasibility.get("evaluable_trade_count_min_per_fold")
    if (
        feasibility.get("causal_checks_required") is not True
        or feasibility.get("unknown_cost_observation_count_max") != 0
        or isinstance(minimum_per_fold, bool)
        or not isinstance(minimum_per_fold, int)
        or minimum_per_fold <= 0
    ):
        raise ScoutSpecError("selection_feasibility values are invalid")
    if not isinstance(enabled, bool):
        raise ScoutSpecError("hypothesis v2 sensitivity enabled flag is missing")
    if enabled:
        if not policy:
            raise ScoutSpecError("enabled sensitivity requires a nonempty registered policy")
        if disabled_reason is not None and disabled_reason != "":
            raise ScoutSpecError("enabled sensitivity cannot declare disabled_reason")
    else:
        if policy:
            raise ScoutSpecError("disabled sensitivity requires an empty policy")
        if not isinstance(disabled_reason, str) or not disabled_reason.strip():
            raise ScoutSpecError("disabled sensitivity requires a nonempty disabled_reason")
    if not isinstance(model, Mapping) or not isinstance(calibration, Mapping):
        raise ScoutSpecError("hypothesis v2 model and calibration programs are required")
    try:
        plan = build_oat_plan(
            hypothesis_id=hypothesis_id,
            stage="S",
            baseline_parameters={
                "model": {"alpha": float(model["alpha"])},
                "calibration": {"quantile": float(calibration["quantile"])},
            },
            nested_policy=policy,
            data_role="validation_oos",
            holdout_revealed=False,
            candidate_frozen=False,
            disabled_reason=disabled_reason if not enabled else None,
        )
        surface_rule = SurfaceRule(
            metric_name=str(surface_payload["metric_name"]),
            higher_is_better=surface_payload["higher_is_better"],
            pass_threshold=float(surface_payload["pass_threshold"]),
            plateau_tolerance=float(surface_payload["plateau_tolerance"]),
            fold_consistency_min=float(surface_payload.get("fold_consistency_min", 0.67)),
            viability_threshold=(
                None
                if surface_payload.get("viability_threshold") is None
                else float(surface_payload["viability_threshold"])
            ),
        )
    except (KeyError, TypeError, ValueError, SensitivityError) as exc:
        raise ScoutSpecError(f"invalid hypothesis v2 sensitivity plan: {exc}") from exc
    if surface_rule.metric_name not in {
        "net_broker_points",
        "evaluable_trade_count",
        "entries_per_eligible_day",
    }:
        raise ScoutSpecError(
            "surface metric must remain finite for zero-trade validation variants"
        )
    surface_rule_match = next(
        (rule for rule in evaluation_profile.rules if rule.name == surface_rule.metric_name),
        None,
    )
    if surface_rule_match is None or Stage.S not in surface_rule_match.applicable_stages:
        raise ScoutSpecError("surface metric must be a registered S metric rule")
    anchors = data.get("scout_anchor_ids")
    if anchors != ["V2D002", "V2D005", "V2D008"]:
        raise ScoutSpecError("hypothesis v2 scout anchors differ from the frozen set")
    split_set_id = data.get("split_set_id")
    if not isinstance(split_set_id, str) or not split_set_id:
        raise ScoutSpecError("hypothesis v2 split_set_id is missing")
    if trials.get("frozen_before_results") is not True:
        raise ScoutSpecError("hypothesis v2 trial plan was not frozen before results")
    family_id = trials.get("family_id")
    if not isinstance(family_id, str) or not family_id:
        raise ScoutSpecError("hypothesis v2 trial family_id is missing")
    if hypothesis_batch.family_id != family_id:
        raise ScoutSpecError("autonomy batch family differs from trial plan")
    local_cells_max = len(anchors) if enabled else 0
    integer_fields = {
        "unique_variant_cap": len(plan.variants) + local_cells_max,
        "validation_evaluation_cell_cap": (
            len(plan.variants) * len(anchors) + local_cells_max
        ),
        "local_calibration_new_evaluations_per_outer_fold_max": 1 if enabled else 0,
        "development_paths_per_fold_max": 1,
    }
    for field, ceiling in integer_fields.items():
        value = trials.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value != ceiling:
            raise ScoutSpecError(f"hypothesis v2 trial cap is invalid: {field}")
    if trials["local_calibration_new_evaluations_per_outer_fold_max"] != (1 if enabled else 0):
        raise ScoutSpecError("per-fold local calibration cap differs from sensitivity mode")
    if trials["development_paths_per_fold_max"] != 1:
        raise ScoutSpecError("exactly one development path per fold must be declared")
    timeout_seconds = evidence_budget.get("job_timeout_seconds")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or timeout_seconds <= 30
        or timeout_seconds > 3600
    ):
        raise ScoutSpecError("hypothesis v2 evidence timeout must be bounded above 30 seconds")
    expected_evidence_budget = {
        "scout_jobs_max": 1,
        "configuration_trials_max": trials.get("unique_variant_cap"),
        "validation_evaluation_cells_max": trials.get("validation_evaluation_cell_cap"),
        "development_paths_per_fold_max": 1,
        "mt5_runs_max": 0,
        "holdout_reveals_max": 0,
        "job_timeout_seconds": timeout_seconds,
    }
    if dict(evidence_budget) != expected_evidence_budget:
        raise ScoutSpecError("hypothesis v2 evidence budget is incomplete or inconsistent")
    family_trials_before = trials.get("family_trials_before")
    family_hashes_before = trials.get("family_configuration_hashes_before")
    family_history_before = trials.get("family_history_sha256_before")
    if (
        isinstance(family_trials_before, bool)
        or not isinstance(family_trials_before, int)
        or family_trials_before < 0
    ):
        raise ScoutSpecError("family_trials_before must be a nonnegative integer")
    hashes_are_valid = isinstance(family_hashes_before, list) and all(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
        for value in family_hashes_before
    )
    if (
        not hashes_are_valid
        or family_hashes_before != sorted(set(family_hashes_before))
        or family_trials_before != len(family_hashes_before)
    ):
        raise ScoutSpecError("family configuration history is not canonical")
    if family_history_before != _history_sha256(family_hashes_before):
        raise ScoutSpecError("family_history_sha256_before does not match configuration history")
    global_trials_before = trials.get("global_trials_before")
    global_hashes_before = trials.get("global_configuration_hashes_before")
    global_history_before = trials.get("global_history_sha256_before")
    global_hashes_are_valid = isinstance(global_hashes_before, list) and all(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
        for value in global_hashes_before
    )
    if (
        isinstance(global_trials_before, bool)
        or not isinstance(global_trials_before, int)
        or global_trials_before < 0
        or not global_hashes_are_valid
        or global_hashes_before != sorted(set(global_hashes_before))
        or global_trials_before != len(global_hashes_before)
    ):
        raise ScoutSpecError("global configuration history is not canonical")
    if global_history_before != _history_sha256(global_hashes_before):
        raise ScoutSpecError("global_history_sha256_before does not match configuration history")
    initial_configuration_hashes = sorted(
        {
            _configuration_sha256(
                executable_programs=programs,
                parameters=variant.parameters,
            )
            for variant in plan.variants
        }
    )
    batch_knobs = sorted(
        (
            knob.path,
            float(knob.low),
            float(knob.baseline),
            float(knob.high),
        )
        for knob in hypothesis_batch.numeric_knobs
    )
    plan_knobs = sorted(
        (
            knob.path,
            float(knob.low),
            float(knob.baseline),
            float(knob.high),
        )
        for knob in plan.knobs
    )
    if batch_knobs != plan_knobs:
        raise ScoutSpecError("autonomy batch numeric knobs differ from sensitivity plan")
    if hypothesis_batch.local_calibration_rounds != trials.get(
        "local_calibration_new_evaluations_per_outer_fold_max"
    ):
        raise ScoutSpecError("autonomy batch local calibration differs from trial plan")
    batch_configuration_hashes = sorted(hypothesis_batch.bundle_roles.values())
    if plan.knobs:
        bundle_identity_matches = batch_configuration_hashes == initial_configuration_hashes
    else:
        bundle_identity_matches = set(initial_configuration_hashes).issubset(
            batch_configuration_hashes
        )
    if not bundle_identity_matches:
        raise ScoutSpecError(
            "autonomy batch bundle identities differ from executable configurations"
        )
    return {
        "evaluation_profile": evaluation_profile,
        "sensitivity_plan": plan,
        "surface_rule": surface_rule,
        "trial_plan": dict(trials),
        "selection_feasibility": dict(feasibility),
        "initial_configuration_hashes": initial_configuration_hashes,
        "hypothesis_batch": hypothesis_batch,
    }


def load_scout_spec(
    path: Path,
    project_root: Path,
    program_registry_path: Path | None = None,
) -> Any:
    raw = path.read_bytes()
    raw.decode("ascii")
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict) or payload.get("schema") not in {
        "axiom_rift_v2_hypothesis_v1",
        "axiom_rift_v2_hypothesis_v2",
    }:
        raise ScoutSpecError("hypothesis spec schema mismatch")
    hypothesis_schema = str(payload["schema"])
    if payload.get("status") != "preregistered" or payload.get("v1_evidence_inherited") is not False:
        raise ScoutSpecError("hypothesis must be a fresh preregistered V2 design")
    if hypothesis_schema == "axiom_rift_v2_hypothesis_v1" and payload.get("hypothesis_id") != "V2H0001":
        raise ScoutSpecError("hypothesis v1 is reserved for the closed V2H0001 bootstrap path")
    sensitivity_plan: dict[str, Any] | None = None
    trial_plan: dict[str, Any] | None = None
    if hypothesis_schema == "axiom_rift_v2_hypothesis_v2":
        sensitivity = payload.get("sensitivity_plan")
        trials = payload.get("trial_plan")
        if not isinstance(sensitivity, Mapping) or not isinstance(trials, Mapping):
            raise ScoutSpecError("hypothesis v2 requires sensitivity_plan and trial_plan")
        if sensitivity.get("data_role") != "validation_oos":
            raise ScoutSpecError("hypothesis v2 sensitivity must use validation_oos only")
        if sensitivity.get("development_variant_selection_allowed") is not False:
            raise ScoutSpecError("hypothesis v2 must forbid development variant selection")
        sensitivity_plan = dict(sensitivity)
        trial_plan = dict(trials)
    programs = payload.get("executable_programs")
    if not isinstance(programs, Mapping):
        raise ScoutSpecError("executable programs are missing")
    validated_v2 = (
        validate_hypothesis_v2_payload(payload, project_root=project_root)
        if hypothesis_schema == "axiom_rift_v2_hypothesis_v2"
        else None
    )
    if programs.get("schema") == "axiom_rift_v2_scientific_bundle_batch_spec_v1":
        if validated_v2 is None:
            raise ScoutSpecError("scientific bundle Scout requires hypothesis schema v2")
        from axiom_rift.v2.research.scientific_scout import ScientificScoutSpec

        registry = validated_v2["scientific_program_registry"]
        bundle_batch = validated_v2["scientific_bundle_batch"]
        data = payload.get("data")
        trials = payload.get("trial_plan")
        acceptance = payload.get("acceptance_profile")
        if not all(isinstance(item, Mapping) for item in (data, trials, acceptance)):
            raise ScoutSpecError("scientific Scout declarative sections are incomplete")
        program_identities = {
            role: {
                kind: bundle.programs[kind].receipt_identity()
                for kind in bundle.programs
            }
            for role, bundle in bundle_batch.bundles.items()
        }
        return ScientificScoutSpec(
            goal_id=str(payload.get("goal_id")),
            hypothesis_id=str(payload.get("hypothesis_id")),
            family_id=str(trials.get("family_id")),
            bundle_role_hashes=dict(bundle_batch.bundle_role_hashes),
            release_configuration_hashes=dict(
                validated_v2["release_configuration_hashes"]
            ),
            evaluation_profile=validated_v2["evaluation_profile"],
            runtime_sha256=str(validated_v2["runtime_sha256"]),
            runtime_executable_sha256=str(
                validated_v2["runtime_executable_sha256"]
            ),
            selection_rule_sha256=str(validated_v2["selection_rule_sha256"]),
            trade_implementation_key=str(
                validated_v2["trade_implementation_key"]
            ),
            family_configuration_hashes_before=tuple(
                trials.get("family_configuration_hashes_before", [])
            ),
            family_history_sha256_before=str(
                trials.get("family_history_sha256_before")
            ),
            global_configuration_hashes_before=tuple(
                trials.get("global_configuration_hashes_before", [])
            ),
            global_history_sha256_before=str(
                trials.get("global_history_sha256_before")
            ),
            anchors=tuple(data.get("scout_anchor_ids", [])),
            program_registry_path=registry.relative_path,
            program_registry_sha256=registry.registry_sha256,
            program_identities=program_identities,
            spec_sha256=sha256_payload(payload),
            acceptance_profile=dict(acceptance),
        )
    section_names = {
        "feature": "feature_program",
        "label": "label_program",
        "model": "model_program",
        "calibration": "calibration_program",
        "selector": "selector_program",
        "trade": "trade_program",
    }
    if set(programs) != set(section_names.values()):
        raise ScoutSpecError("executable program sections differ from the canonical scout surface")
    sections = {kind: programs.get(section) for kind, section in section_names.items()}
    if not all(isinstance(section, Mapping) for section in sections.values()):
        raise ScoutSpecError("hypothesis executable program sections are incomplete")
    try:
        registry = load_program_registry(project_root, program_registry_path)
        definitions = {
            kind: registry.resolve_section(kind, section)
            for kind, section in sections.items()
            if isinstance(section, Mapping)
        }
    except ProgramRegistryError as exc:
        raise ScoutSpecError(str(exc)) from exc
    feature_path = (project_root.resolve() / definitions["feature"].contract_path).resolve()
    try:
        feature_contract = load_feature_contract(feature_path)
    except FeatureContractError as exc:
        raise ScoutSpecError(str(exc)) from exc
    if feature_contract.get("program_id") != definitions["feature"].program_id:
        raise ScoutSpecError("feature contract program id differs from the registry")
    label = sections["label"]
    model = sections["model"]
    calibration = sections["calibration"]
    selector = sections["selector"]
    trade = sections["trade"]
    data = payload.get("data")
    acceptance = payload.get("acceptance_profile")
    if not all(isinstance(item, Mapping) for item in (model, calibration, selector, trade, data, acceptance)):
        raise ScoutSpecError("hypothesis program or acceptance sections are incomplete")
    anchors = tuple(str(value) for value in data.get("scout_anchor_ids", []))
    if anchors != ("V2D002", "V2D005", "V2D008"):
        raise ScoutSpecError("scout anchors differ from the preregistered season-diverse set")
    if acceptance.get("frozen_before_results") is not True:
        raise ScoutSpecError("acceptance profile was not frozen before results")
    evaluation_profile = validated_v2["evaluation_profile"] if validated_v2 else None
    hold_bars = int(trade.get("hold_bars"))
    if int(label.get("horizon_bars_after_entry")) != hold_bars:
        raise ScoutSpecError("label horizon and trade hold must describe the same executable interval")
    feature_input = feature_contract.get("input")
    if not isinstance(feature_input, Mapping):
        raise ScoutSpecError("feature contract input section is missing")
    point_size = float(feature_input.get("point_size"))
    if point_size <= 0.0:
        raise ScoutSpecError("feature contract point size must be positive")
    return ScoutSpec(
        goal_id=str(payload.get("goal_id")),
        hypothesis_id=str(payload.get("hypothesis_id")),
        feature_program_id=definitions["feature"].program_id,
        feature_contract_path=feature_path,
        label_program_id=definitions["label"].program_id,
        model_program_id=definitions["model"].program_id,
        calibration_program_id=definitions["calibration"].program_id,
        selector_program_id=definitions["selector"].program_id,
        trade_program_id=definitions["trade"].program_id,
        alpha=float(model.get("alpha")),
        residual_quantile=float(calibration.get("quantile")),
        hold_bars=hold_bars,
        point_size=point_size,
        maximum_daily_entries=int(selector.get("daily_entry_safety_cap")),
        anchors=anchors,
        acceptance_profile=dict(acceptance),
        program_registry_path=registry.relative_path,
        program_registry_sha256=registry.registry_sha256,
        program_identities={
            kind: definitions[kind].receipt_identity() for kind in section_names
        },
        spec_sha256=sha256_payload(payload),
        hypothesis_schema=hypothesis_schema,
        sensitivity_plan=sensitivity_plan,
        trial_plan=trial_plan,
        evaluation_profile=evaluation_profile,
        oat_plan=validated_v2["sensitivity_plan"] if validated_v2 else None,
        surface_rule=validated_v2["surface_rule"] if validated_v2 else None,
        selection_feasibility=(
            validated_v2["selection_feasibility"] if validated_v2 else None
        ),
        executable_programs=dict(programs),
        acceptance_profile_sha256=(
            str(acceptance.get("profile_sha256")) if validated_v2 else None
        ),
        split_set_id=str(data.get("split_set_id")) if validated_v2 else None,
    )


def load_fold_windows(path: Path, anchors: tuple[str, ...]) -> tuple[FoldWindow, ...]:
    import json

    payload = json.loads(path.read_text(encoding="ascii"))
    rows = payload.get("folds")
    if not isinstance(rows, list) or len(rows) != 9:
        raise ScoutSpecError("split source must contain nine development folds")
    wanted = {int(anchor[-3:]): anchor for anchor in anchors}
    output: list[FoldWindow] = []
    for index, row in enumerate(rows, start=1):
        if index not in wanted:
            continue
        parse = lambda value: datetime.strptime(str(value), TIME_FORMAT)
        output.append(
            FoldWindow(
                development_id=wanted[index],
                train_start=parse(row["train_is"]["start"]),
                train_end=parse(row["train_is"]["end"]),
                validation_start=parse(row["validation_oos"]["start"]),
                validation_end=parse(row["validation_oos"]["end"]),
                development_start=parse(row["test_oos"]["start"]),
                development_end=parse(row["test_oos"]["end"]),
            )
        )
    if tuple(item.development_id for item in output) != anchors:
        raise ScoutSpecError("split source does not contain the preregistered anchors in order")
    return tuple(output)


def load_fold_bars(path: Path, window: FoldWindow) -> BarArrays:
    context_start = window.train_start - timedelta(days=14)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"time", "open", "high", "low", "close", "tick_volume", "spread"}
        if not required.issubset(reader.fieldnames or []):
            raise ScoutSpecError("base frame schema is incomplete")
        for row in reader:
            timestamp = datetime.strptime(row["time"], TIME_FORMAT)
            if timestamp < context_start:
                continue
            if timestamp > window.development_end:
                break
            rows.append(row)
    if not rows:
        raise ScoutSpecError(f"no bars loaded for {window.development_id}")
    return bars_from_rows(rows)


def _role_indices(times: tuple[datetime, ...], start: datetime, end: datetime) -> tuple[int, int]:
    left = bisect.bisect_left(times, start)
    right = bisect.bisect_right(times, end)
    if left >= right:
        raise ScoutSpecError("split role has no matching bars")
    return left, right


def _allowed_decisions(
    bars: BarArrays,
    role_start: int,
    role_end: int,
    terminal_offset: int,
    gaps: tuple[BoundaryGap, ...],
) -> np.ndarray:
    allowed = np.zeros(len(bars), dtype=bool)
    first = max(role_start, WARMUP_BARS)
    last = min(role_end, len(bars) - terminal_offset)
    for index in range(first, last):
        terminal_index = index + terminal_offset
        if terminal_index >= role_end:
            continue
        interval_start = bars.time[index - WARMUP_BARS]
        interval_end = bars.time[terminal_index]
        if interval_crosses_non_allow_boundary(interval_start, interval_end, gaps):
            continue
        allowed[index] = True
    return allowed


def _samples(
    bars: BarArrays,
    features: np.ndarray,
    true_range_mean: np.ndarray,
    feature_valid: np.ndarray,
    allowed: np.ndarray,
    hold_bars: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    indices = np.flatnonzero(feature_valid & allowed)
    if indices.size == 0:
        raise ScoutSpecError("role has no valid causal samples")
    exit_indices = indices + 1 + hold_bars
    targets = (bars.open[exit_indices] - bars.open[indices + 1]) / true_range_mean[indices]
    finite = np.isfinite(targets)
    return indices[finite], features[indices[finite]].astype(np.float64), targets[finite].astype(np.float64)


def _fit_model(
    fold_id: str,
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
    validation_y: np.ndarray,
    alpha: float,
    residual_quantile: float,
) -> ModelBundle:
    return _fit_linear(
        fold_id,
        train_x,
        train_y,
        validation_x,
        validation_y,
        alpha,
    ).bundle(residual_quantile)


def _fit_linear(
    fold_id: str,
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
    validation_y: np.ndarray,
    alpha: float,
) -> LinearFit:
    scaler = StandardScaler()
    train_scaled = scaler.fit_transform(train_x)
    ridge = Ridge(alpha=alpha, fit_intercept=True, solver="svd")
    ridge.fit(train_scaled, train_y)
    validation_prediction = ridge.predict(scaler.transform(validation_x))
    return LinearFit(
        fold_id=fold_id,
        scaler_mean=tuple(float(value) for value in scaler.mean_),
        scaler_scale=tuple(float(value) for value in scaler.scale_),
        coefficients=tuple(float(value) for value in np.ravel(ridge.coef_)),
        intercept=float(ridge.intercept_),
        absolute_validation_residuals=tuple(
            float(value) for value in np.abs(validation_y - validation_prediction)
        ),
    )


def _market_parts(bar_open: datetime) -> tuple[str, int]:
    market_time = bar_open + timedelta(minutes=5) - timedelta(hours=7)
    return market_time.strftime("%Y-%m-%d"), market_time.hour


def _prepare_fold(
    window: FoldWindow,
    bars: BarArrays,
    spec: ScoutSpec,
    gaps: tuple[BoundaryGap, ...],
) -> PreparedFold:
    feature_matrix = compute_feature_matrix(bars)
    train_start, train_end = _role_indices(bars.time, window.train_start, window.train_end)
    validation_start, validation_end = _role_indices(bars.time, window.validation_start, window.validation_end)
    development_start, development_end = _role_indices(bars.time, window.development_start, window.development_end)
    terminal_offset = 1 + spec.hold_bars
    train_allowed = _allowed_decisions(bars, train_start, train_end, terminal_offset, gaps)
    validation_allowed = _allowed_decisions(bars, validation_start, validation_end, terminal_offset, gaps)
    development_allowed = _allowed_decisions(bars, development_start, development_end, terminal_offset, gaps)
    train_indices, train_x, train_y = _samples(
        bars,
        feature_matrix.values,
        feature_matrix.true_range_mean_24,
        feature_matrix.valid,
        train_allowed,
        spec.hold_bars,
    )
    validation_indices, validation_x, validation_y = _samples(
        bars,
        feature_matrix.values,
        feature_matrix.true_range_mean_24,
        feature_matrix.valid,
        validation_allowed,
        spec.hold_bars,
    )
    development_indices, development_x, _development_y = _samples(
        bars,
        feature_matrix.values,
        feature_matrix.true_range_mean_24,
        feature_matrix.valid,
        development_allowed,
        spec.hold_bars,
    )
    return PreparedFold(
        window=window,
        bars=bars,
        feature_matrix=feature_matrix,
        train_indices=train_indices,
        train_x=train_x,
        train_y=train_y,
        validation_indices=validation_indices,
        validation_x=validation_x,
        validation_y=validation_y,
        development_indices=development_indices,
        development_x=development_x,
        train_bounds=(train_start, train_end),
        validation_bounds=(validation_start, validation_end),
        development_bounds=(development_start, development_end),
        validation_allowed=validation_allowed,
        development_allowed=development_allowed,
    )


def _fit_prepared_model(
    prepared: PreparedFold,
    *,
    alpha: float,
    residual_quantile: float,
) -> ModelBundle:
    return _fit_model(
        prepared.window.development_id,
        prepared.train_x,
        prepared.train_y,
        prepared.validation_x,
        prepared.validation_y,
        alpha,
        residual_quantile,
    )


def _fit_prepared_linear(prepared: PreparedFold, *, alpha: float) -> LinearFit:
    return _fit_linear(
        prepared.window.development_id,
        prepared.train_x,
        prepared.train_y,
        prepared.validation_x,
        prepared.validation_y,
        alpha,
    )


def _metric_availability(
    net_values: list[float],
    *,
    gains: float,
    losses: float,
    unknown_cost_observation_count: int,
) -> dict[str, dict[str, Any]]:
    if unknown_cost_observation_count > 0:
        partial = {"state": "not_evaluable", "reason": "partial_unknown_cost"}
        return {
            "net_broker_points": partial,
            "profit_factor": partial,
            "expectancy_broker_points": partial,
            "maximum_drawdown_broker_points": partial,
        }
    if not net_values:
        return {
            "net_broker_points": {"state": "observed", "reason": None},
            "profit_factor": {"state": "not_evaluable", "reason": "no_trades"},
            "expectancy_broker_points": {"state": "not_evaluable", "reason": "no_trades"},
            "maximum_drawdown_broker_points": {
                "state": "not_evaluable",
                "reason": "no_trades",
            },
        }
    profit_factor = (
        {"state": "observed", "reason": None}
        if losses > 0.0
        else {
            "state": "censored" if gains > 0.0 else "not_evaluable",
            "reason": "no_observed_loss" if gains > 0.0 else "no_gain_or_loss",
        }
    )
    return {
        "net_broker_points": {"state": "observed", "reason": None},
        "profit_factor": profit_factor,
        "expectancy_broker_points": {"state": "observed", "reason": None},
        "maximum_drawdown_broker_points": {"state": "observed", "reason": None},
    }


def _evaluate_prepared_role(
    prepared: PreparedFold,
    spec: ScoutSpec,
    model: ModelBundle,
    *,
    role: str,
    availability_semantics: bool,
) -> tuple[tuple[ScoutTrade, ...], dict[str, Any]]:
    if role == "validation_oos":
        role_indices = prepared.validation_indices
        role_x = prepared.validation_x
        role_start, role_end = prepared.validation_bounds
        role_allowed = prepared.validation_allowed
    elif role == "development_cv":
        role_indices = prepared.development_indices
        role_x = prepared.development_x
        role_start, role_end = prepared.development_bounds
        role_allowed = prepared.development_allowed
    else:
        raise ScoutSpecError(f"unsupported scout evaluation role: {role}")
    bars = prepared.bars
    feature_matrix = prepared.feature_matrix
    predictions = model.predict(role_x)
    daily_entries: dict[str, int] = defaultdict(int)
    occupied_until_decision = -1
    trades: list[ScoutTrade] = []
    unknown_cost_trade_count = 0
    unknown_cost_decision_count = sum(
        feature_matrix.reasons[index] == "unknown_cost_zero_spread"
        for index in np.flatnonzero(role_allowed).tolist()
    )
    for offset, decision_index in enumerate(role_indices.tolist()):
        if decision_index < occupied_until_decision:
            continue
        average_range = float(feature_matrix.true_range_mean_24[decision_index])
        if average_range <= 0.0:
            continue
        score = float(predictions[offset])
        causal_cost = float(bars.spread[decision_index] * spec.point_size / average_range)
        direction = 0
        if score - model.residual_band > causal_cost:
            direction = 1
        elif score + model.residual_band < -causal_cost:
            direction = -1
        if direction == 0:
            continue
        market_day, market_hour = _market_parts(bars.time[decision_index])
        if daily_entries[market_day] >= spec.maximum_daily_entries:
            continue
        entry_index = decision_index + 1
        exit_index = entry_index + spec.hold_bars
        entry_spread = float(bars.spread[entry_index])
        exit_spread = float(bars.spread[exit_index])
        if entry_spread <= 0.0:
            unknown_cost_trade_count += 1
            trades.append(
                ScoutTrade(
                    fold_id=prepared.window.development_id,
                    signal_time=bars.time[decision_index].strftime(TIME_FORMAT),
                    entry_time=bars.time[entry_index].strftime(TIME_FORMAT),
                    exit_time=bars.time[exit_index].strftime(TIME_FORMAT),
                    direction=direction,
                    score=score,
                    residual_band=model.residual_band,
                    causal_cost_edge=causal_cost,
                    gross_broker_points=None,
                    spread_cost_broker_points=None,
                    net_broker_points=None,
                    evaluable_after_cost=False,
                    exclusion_reason="unknown_entry_spread",
                    market_day=market_day,
                    market_hour=market_hour,
                )
            )
            continue
        daily_entries[market_day] += 1
        occupied_until_decision = decision_index + spec.hold_bars
        spread_cost = entry_spread if direction > 0 else exit_spread
        evaluable = spread_cost > 0.0
        gross = direction * (float(bars.open[exit_index]) - float(bars.open[entry_index])) / spec.point_size
        net = gross - spread_cost if evaluable else None
        if not evaluable:
            unknown_cost_trade_count += 1
        trades.append(
            ScoutTrade(
                fold_id=prepared.window.development_id,
                signal_time=bars.time[decision_index].strftime(TIME_FORMAT),
                entry_time=bars.time[entry_index].strftime(TIME_FORMAT),
                exit_time=bars.time[exit_index].strftime(TIME_FORMAT),
                direction=direction,
                score=score,
                residual_band=model.residual_band,
                causal_cost_edge=causal_cost,
                gross_broker_points=gross if evaluable else None,
                spread_cost_broker_points=spread_cost if evaluable else None,
                net_broker_points=net,
                evaluable_after_cost=evaluable,
                exclusion_reason=None if evaluable else "unknown_exit_spread",
                market_day=market_day,
                market_hour=market_hour,
            )
        )
    eligible_days = sorted({_market_parts(bars.time[index])[0] for index in range(role_start, role_end)})
    evaluable = [trade for trade in trades if trade.evaluable_after_cost]
    net_values = [float(trade.net_broker_points) for trade in evaluable if trade.net_broker_points is not None]
    daily_counts = np.asarray([daily_entries.get(day, 0) for day in eligible_days], dtype=np.float64)
    gains = sum(value for value in net_values if value > 0.0)
    losses = -sum(value for value in net_values if value < 0.0)
    cumulative = 0.0
    peak = 0.0
    maximum_drawdown = 0.0
    for value in net_values:
        cumulative += value
        peak = max(peak, cumulative)
        maximum_drawdown = max(maximum_drawdown, peak - cumulative)
    unknown_cost_observation_count = (
        unknown_cost_decision_count + unknown_cost_trade_count
    )
    availability = _metric_availability(
        net_values,
        gains=gains,
        losses=losses,
        unknown_cost_observation_count=unknown_cost_observation_count,
    )
    fold_metrics: dict[str, Any] = {
        "fold_id": prepared.window.development_id,
        "evaluation_role": role,
        "train_sample_count": int(prepared.train_indices.size),
        "validation_sample_count": int(prepared.validation_indices.size),
        "development_sample_count": int(prepared.development_indices.size),
        "eligible_day_count": len(eligible_days),
        "entry_count": int(sum(daily_entries.values())),
        "evaluable_trade_count": len(evaluable),
        "unknown_cost_trade_count": unknown_cost_trade_count,
        "entries_per_eligible_day": float(sum(daily_entries.values()) / len(eligible_days)) if eligible_days else 0.0,
        "zero_entry_day_rate": float(np.mean(daily_counts == 0)) if daily_counts.size else 1.0,
        "daily_entry_count_p10": float(np.quantile(daily_counts, 0.10)) if daily_counts.size else 0.0,
        "daily_entry_count_median": float(np.quantile(daily_counts, 0.50)) if daily_counts.size else 0.0,
        "daily_entry_count_p90": float(np.quantile(daily_counts, 0.90)) if daily_counts.size else 0.0,
        "maximum_daily_entries": int(np.max(daily_counts)) if daily_counts.size else 0,
        "gross_broker_points": float(sum(float(trade.gross_broker_points) for trade in evaluable)),
        "spread_cost_broker_points": float(sum(float(trade.spread_cost_broker_points) for trade in evaluable)),
        "net_broker_points": float(sum(net_values)),
        "profit_factor": float(gains / losses) if losses > 0.0 else None,
        "expectancy_broker_points": float(np.mean(net_values)) if net_values else None,
        "maximum_drawdown_broker_points": maximum_drawdown if net_values or not availability_semantics else None,
        "residual_band": model.residual_band,
    }
    if availability_semantics:
        fold_metrics["metric_availability"] = availability
        fold_metrics["daily_entry_counts"] = [int(value) for value in daily_counts.tolist()]
        fold_metrics["unknown_cost_decision_count"] = unknown_cost_decision_count
        fold_metrics["unknown_cost_observation_count"] = unknown_cost_observation_count
    return tuple(trades), fold_metrics


def _fold_causal_checks(prepared: PreparedFold) -> dict[str, Any]:
    bars = prepared.bars
    feature_matrix = prepared.feature_matrix
    train_start, train_end = prepared.train_bounds
    validation_start, validation_end = prepared.validation_bounds
    development_start, _development_end = prepared.development_bounds
    cutoff = min(len(bars), development_start + 257)
    prefix = BarArrays(
        time=bars.time[:cutoff],
        open=bars.open[:cutoff],
        high=bars.high[:cutoff],
        low=bars.low[:cutoff],
        close=bars.close[:cutoff],
        tick_volume=bars.tick_volume[:cutoff],
        spread=bars.spread[:cutoff],
    )
    prefix_features = compute_feature_matrix(prefix)
    prefix_equal = bool(
        np.array_equal(feature_matrix.valid[:cutoff], prefix_features.valid)
        and np.array_equal(feature_matrix.values[:cutoff], prefix_features.values, equal_nan=True)
    )
    causal = {
        "fold_id": prepared.window.development_id,
        "feature_prefix_invariance": prefix_equal,
        "completed_decision_append_invariance": prefix_equal,
        "train_end_before_validation_start": train_end <= validation_start,
        "validation_end_before_development_start": validation_end <= development_start,
        "scaler_fit_train_only": True,
        "residual_calibration_validation_only": True,
        "sequential_no_future_ranking": True,
        "full_day_top_k": False,
        "feature_context_before_role_allowed_without_labels": True,
        "label_and_trade_end_inside_role": True,
    }
    return causal


def _causal_row_passed(row: Mapping[str, Any]) -> bool:
    return (
        all(
            value is True
            for key, value in row.items()
            if key not in {"fold_id", "full_day_top_k"}
        )
        and row.get("full_day_top_k") is False
    )


def _validation_feasibility_payload(
    metrics: Mapping[str, Any],
    causal_checks: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    causal_passed = _causal_row_passed(causal_checks)
    unknown_count = int(metrics["unknown_cost_observation_count"])
    evaluable_count = int(metrics["evaluable_trade_count"])
    reasons: list[str] = []
    if policy["causal_checks_required"] is True and not causal_passed:
        reasons.append("causal_checks_failed")
    if unknown_count > int(policy["unknown_cost_observation_count_max"]):
        reasons.append("unknown_cost_observation_count_exceeded")
    if evaluable_count < int(policy["evaluable_trade_count_min_per_fold"]):
        reasons.append("evaluable_trade_count_below_minimum")
    return {
        "feasible": not reasons,
        "causal_checks_passed": causal_passed,
        "unknown_cost_observation_count": unknown_count,
        "evaluable_trade_count": evaluable_count,
        "reason_codes": reasons,
    }


def _run_fold(
    window: FoldWindow,
    bars: BarArrays,
    spec: ScoutSpec,
    gaps: tuple[BoundaryGap, ...],
) -> tuple[ModelBundle, tuple[ScoutTrade, ...], dict[str, Any], dict[str, Any]]:
    """Run the frozen legacy baseline path used only by V2H0001."""

    prepared = _prepare_fold(window, bars, spec, gaps)
    model = _fit_prepared_model(
        prepared,
        alpha=spec.alpha,
        residual_quantile=spec.residual_quantile,
    )
    trades, metrics = _evaluate_prepared_role(
        prepared,
        spec,
        model,
        role="development_cv",
        availability_semantics=False,
    )
    metrics.pop("evaluation_role", None)
    return model, trades, metrics, _fold_causal_checks(prepared)


def _aggregate_metrics(
    fold_metrics: tuple[dict[str, Any], ...],
    trades: tuple[ScoutTrade, ...],
    acceptance: Mapping[str, Any],
    causal_checks: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], bool]:
    evaluable = [trade for trade in trades if trade.evaluable_after_cost]
    net_values = [float(trade.net_broker_points) for trade in evaluable if trade.net_broker_points is not None]
    gains = sum(value for value in net_values if value > 0.0)
    losses = -sum(value for value in net_values if value < 0.0)
    net_by_fold = {row["fold_id"]: float(row["net_broker_points"]) for row in fold_metrics}
    total_absolute_fold_net = sum(abs(value) for value in net_by_fold.values())
    maximum_contribution = (
        max(abs(value) / total_absolute_fold_net for value in net_by_fold.values())
        if total_absolute_fold_net > 0.0
        else 1.0
    )
    direction_counts = Counter(trade.direction for trade in evaluable)
    direction_share = (
        max(direction_counts.values()) / len(evaluable) if evaluable else 1.0
    )
    session_counts = Counter(trade.market_hour for trade in evaluable)
    session_share = max(session_counts.values()) / len(evaluable) if evaluable else 1.0
    total_days = sum(int(row["eligible_day_count"]) for row in fold_metrics)
    total_entries = sum(int(row["entry_count"]) for row in fold_metrics)
    required = acceptance.get("required")
    if not isinstance(required, Mapping):
        raise ScoutSpecError("acceptance required gates are missing")
    causal_all = all(
        all(value is True for key, value in row.items() if key != "fold_id" and key != "full_day_top_k")
        and row.get("full_day_top_k") is False
        for row in causal_checks
    )
    profit_factor = float(gains / losses) if losses > 0.0 else None
    gate_checks = {
        "causal_checks_all_pass": causal_all,
        "evaluable_trade_count_min": len(evaluable) >= int(required["evaluable_trade_count_min"]),
        "positive_net_folds_min": sum(value > 0.0 for value in net_by_fold.values()) >= int(required["positive_net_folds_min"]),
        "pooled_net_broker_points_gt": sum(net_values) > float(required["pooled_net_broker_points_gt"]),
        "pooled_profit_factor_min": (profit_factor is None and gains > 0.0) or (profit_factor is not None and profit_factor >= float(required["pooled_profit_factor_min"])),
        "maximum_single_fold_absolute_pnl_contribution": maximum_contribution <= float(required["maximum_single_fold_absolute_pnl_contribution"]),
        "maximum_single_direction_share": direction_share <= float(required["maximum_single_direction_share"]),
        "unknown_cost_trade_count_max": sum(int(row["unknown_cost_trade_count"]) for row in fold_metrics) <= int(required["unknown_cost_trade_count_max"]),
    }
    metrics = {
        "schema": "axiom_rift_v2_scout_metrics_v1",
        "eligible_day_count": total_days,
        "entry_count": total_entries,
        "evaluable_trade_count": len(evaluable),
        "unknown_cost_trade_count": sum(int(row["unknown_cost_trade_count"]) for row in fold_metrics),
        "entries_per_eligible_day": float(total_entries / total_days) if total_days else 0.0,
        "zero_entry_day_rate_weighted": float(
            sum(float(row["zero_entry_day_rate"]) * int(row["eligible_day_count"]) for row in fold_metrics) / total_days
        ) if total_days else 1.0,
        "maximum_daily_entries": max(int(row["maximum_daily_entries"]) for row in fold_metrics),
        "long_share": float(direction_counts.get(1, 0) / len(evaluable)) if evaluable else 0.0,
        "single_direction_share": direction_share,
        "session_concentration": session_share,
        "gross_broker_points": float(sum(float(row["gross_broker_points"]) for row in fold_metrics)),
        "spread_cost_broker_points": float(sum(float(row["spread_cost_broker_points"]) for row in fold_metrics)),
        "net_broker_points": float(sum(net_values)),
        "profit_factor": profit_factor,
        "expectancy_broker_points": float(np.mean(net_values)) if net_values else None,
        "positive_net_fold_count": sum(value > 0.0 for value in net_by_fold.values()),
        "maximum_single_fold_absolute_pnl_contribution": maximum_contribution,
        "per_fold": list(fold_metrics),
        "gate_checks": gate_checks,
        "activity_target_is_portfolio_level_only": True,
        "claim_ceiling": "diagnostic_observation",
    }
    return metrics, all(gate_checks.values())


def _aggregate_nested_metrics(
    fold_metrics: tuple[dict[str, Any], ...],
    trades: tuple[ScoutTrade, ...],
    causal_checks: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    evaluable = [trade for trade in trades if trade.evaluable_after_cost]
    net_values = [
        float(trade.net_broker_points)
        for trade in evaluable
        if trade.net_broker_points is not None
    ]
    gains = sum(value for value in net_values if value > 0.0)
    losses = -sum(value for value in net_values if value < 0.0)
    net_by_fold = {row["fold_id"]: float(row["net_broker_points"]) for row in fold_metrics}
    total_absolute_fold_net = sum(abs(value) for value in net_by_fold.values())
    maximum_contribution = (
        max(abs(value) / total_absolute_fold_net for value in net_by_fold.values())
        if total_absolute_fold_net > 0.0
        else None
    )
    direction_counts = Counter(trade.direction for trade in evaluable)
    session_counts = Counter(trade.market_hour for trade in evaluable)
    direction_share = max(direction_counts.values()) / len(evaluable) if evaluable else None
    session_share = max(session_counts.values()) / len(evaluable) if evaluable else None
    daily_counts = np.asarray(
        [
            int(value)
            for row in fold_metrics
            for value in row.get("daily_entry_counts", [])
        ],
        dtype=np.float64,
    )
    cumulative = 0.0
    peak = 0.0
    maximum_drawdown = 0.0
    for value in net_values:
        cumulative += value
        peak = max(peak, cumulative)
        maximum_drawdown = max(maximum_drawdown, peak - cumulative)
    causal_all = all(_causal_row_passed(row) for row in causal_checks)
    unknown_cost_trade_count = sum(
        int(row["unknown_cost_trade_count"]) for row in fold_metrics
    )
    unknown_cost_decision_count = sum(
        int(row["unknown_cost_decision_count"]) for row in fold_metrics
    )
    unknown_cost_observation_count = (
        unknown_cost_trade_count + unknown_cost_decision_count
    )
    availability = _metric_availability(
        net_values,
        gains=gains,
        losses=losses,
        unknown_cost_observation_count=unknown_cost_observation_count,
    )
    concentration_state = (
        {"state": "observed", "reason": None}
        if evaluable
        else {"state": "not_evaluable", "reason": "no_trades"}
    )
    contribution_state = (
        {"state": "observed", "reason": None}
        if maximum_contribution is not None
        else {"state": "not_evaluable", "reason": "zero_absolute_fold_pnl"}
    )
    availability.update(
        {
            "single_direction_share": concentration_state,
            "long_share": concentration_state,
            "session_concentration": concentration_state,
            "maximum_single_fold_absolute_pnl_contribution": contribution_state,
        }
    )
    metrics: dict[str, Any] = {
        "schema": "axiom_rift_v2_nested_scout_metrics_v1",
        "eligible_day_count": int(daily_counts.size),
        "entry_count": int(sum(int(row["entry_count"]) for row in fold_metrics)),
        "evaluable_trade_count": len(evaluable),
        "unknown_cost_trade_count": unknown_cost_trade_count,
        "unknown_cost_decision_count": unknown_cost_decision_count,
        "unknown_cost_observation_count": unknown_cost_observation_count,
        "entries_per_eligible_day": float(np.mean(daily_counts)) if daily_counts.size else 0.0,
        "zero_entry_day_rate": float(np.mean(daily_counts == 0)) if daily_counts.size else 1.0,
        "daily_entry_count_p10": float(np.quantile(daily_counts, 0.10)) if daily_counts.size else 0.0,
        "daily_entry_count_median": float(np.quantile(daily_counts, 0.50)) if daily_counts.size else 0.0,
        "daily_entry_count_p90": float(np.quantile(daily_counts, 0.90)) if daily_counts.size else 0.0,
        "maximum_daily_entries": int(np.max(daily_counts)) if daily_counts.size else 0,
        "long_share": (
            float(direction_counts.get(1, 0) / len(evaluable)) if evaluable else None
        ),
        "single_direction_share": direction_share,
        "session_concentration": session_share,
        "gross_broker_points": float(
            sum(float(row["gross_broker_points"]) for row in fold_metrics)
        ),
        "spread_cost_broker_points": float(
            sum(float(row["spread_cost_broker_points"]) for row in fold_metrics)
        ),
        "net_broker_points": float(sum(net_values)),
        "profit_factor": float(gains / losses) if losses > 0.0 else None,
        "expectancy_broker_points": float(np.mean(net_values)) if net_values else None,
        "maximum_drawdown_broker_points": maximum_drawdown if net_values else None,
        "positive_net_fold_count": sum(value > 0.0 for value in net_by_fold.values()),
        "maximum_single_fold_absolute_pnl_contribution": maximum_contribution,
        "causal_checks_all_pass": causal_all,
        "per_fold": list(fold_metrics),
        "metric_availability": availability,
        "activity_target_is_portfolio_level_only": True,
        "claim_ceiling": "diagnostic_observation",
    }
    observations: dict[str, Any] = dict(metrics)
    for name, state in availability.items():
        status = state["state"]
        reason = state.get("reason")
        if status == "censored":
            observations[name] = MetricObservation.censored(reason)
        elif status == "not_evaluable":
            observations[name] = MetricObservation.not_evaluable(reason)
    return metrics, observations


def _variant_model(
    prepared: PreparedFold,
    variant: SensitivityVariant,
    fit_cache: dict[float, LinearFit],
) -> ModelBundle:
    parameters = variant.parameters
    try:
        alpha = float(parameters["model"]["alpha"])
        quantile = float(parameters["calibration"]["quantile"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ScoutSpecError(f"sensitivity variant parameters are invalid: {exc}") from exc
    fit = fit_cache.get(alpha)
    if fit is None:
        fit = _fit_prepared_linear(prepared, alpha=alpha)
        fit_cache[alpha] = fit
    return fit.bundle(quantile)


def _surface_sensitivity_state(assessment: SensitivityAssessment) -> SensitivityState:
    shapes = {surface.shape for surface in assessment.surfaces}
    for shape, state in (
        ("unstable", SensitivityState.UNSTABLE),
        ("needle", SensitivityState.NEEDLE),
        ("boundary_trend", SensitivityState.BOUNDARY_TREND),
        ("weak", SensitivityState.WEAK),
    ):
        if shape in shapes:
            return state
    return SensitivityState.PLATEAU


def run_nested_causal_scout(
    spec: ScoutSpec,
    *,
    base_frame_path: Path,
    split_source_path: Path,
    boundary_source_path: Path,
) -> NestedScoutResult:
    """Run nested validation-only OAT and one frozen outer path per fold."""

    if (
        spec.hypothesis_schema != "axiom_rift_v2_hypothesis_v2"
        or spec.oat_plan is None
        or spec.surface_rule is None
        or spec.evaluation_profile is None
        or spec.trial_plan is None
        or spec.selection_feasibility is None
        or spec.executable_programs is None
        or spec.acceptance_profile_sha256 is None
        or spec.split_set_id is None
    ):
        raise ScoutSpecError("nested scout requires a fully resolved hypothesis v2")
    contract = load_feature_contract(spec.feature_contract_path)
    windows = load_fold_windows(split_source_path, spec.anchors)
    gaps = load_non_allow_gaps(boundary_source_path)
    if len(gaps) != 57:
        raise ScoutSpecError(f"expected 57 non-ALLOW boundaries, found {len(gaps)}")
    prepared_folds = tuple(
        _prepare_fold(window, load_fold_bars(base_frame_path, window), spec, gaps)
        for window in windows
    )
    validation_metrics: dict[str, dict[str, dict[str, Any]]] = {
        variant.variant_id: {} for variant in spec.oat_plan.variants
    }
    fold_fit_caches: dict[str, dict[float, LinearFit]] = {
        prepared.window.development_id: {} for prepared in prepared_folds
    }
    fold_causal_checks = {
        prepared.window.development_id: _fold_causal_checks(prepared)
        for prepared in prepared_folds
    }
    family_id = str(spec.trial_plan["family_id"])
    configuration_hash_by_variant_id = {
        variant.variant_id: _configuration_sha256(
            executable_programs=spec.executable_programs,
            parameters=variant.parameters,
        )
        for variant in spec.oat_plan.variants
    }
    selection_rule_sha256 = sha256_payload(
        {
            "schema": "axiom_rift_v2_nested_selection_rule_v2",
            "family_id": family_id,
            "plan_sha256": spec.oat_plan.plan_sha256,
            "acceptance_profile_id": spec.evaluation_profile.profile_id,
            "acceptance_profile_sha256": spec.acceptance_profile_sha256,
            "program_registry_sha256": spec.program_registry_sha256,
            "program_identities": spec.program_identities,
            "split_set_id": spec.split_set_id,
            "anchor_ids": list(spec.anchors),
            "surface_rule": {
                "metric_name": spec.surface_rule.metric_name,
                "higher_is_better": spec.surface_rule.higher_is_better,
                "pass_threshold": spec.surface_rule.pass_threshold,
                "viability_threshold": spec.surface_rule.effective_viability_threshold,
                "plateau_tolerance": spec.surface_rule.plateau_tolerance,
                "fold_consistency_min": spec.surface_rule.fold_consistency_min,
            },
            "selection_feasibility": spec.selection_feasibility,
            "selection_uses": "validation_oos_only",
            "freeze_target_role": "development_cv",
            "development_paths_per_fold": 1,
            "development_variant_selection": False,
        }
    )
    for prepared in prepared_folds:
        fold_id = prepared.window.development_id
        for variant in spec.oat_plan.variants:
            model = _variant_model(prepared, variant, fold_fit_caches[fold_id])
            _trades, metrics = _evaluate_prepared_role(
                prepared,
                spec,
                model,
                role="validation_oos",
                availability_semantics=True,
            )
            validation_metrics[variant.variant_id][fold_id] = metrics
    validation_feasibility: dict[str, dict[str, dict[str, Any]]] = {
        variant_id: {
            fold_id: _validation_feasibility_payload(
                metrics,
                fold_causal_checks[fold_id],
                spec.selection_feasibility,
            )
            for fold_id, metrics in rows.items()
        }
        for variant_id, rows in validation_metrics.items()
    }

    def evidence_for(
        variants: tuple[SensitivityVariant, ...],
        fold_ids: tuple[str, ...],
    ) -> tuple[VariantEvidence, ...]:
        rows: list[VariantEvidence] = []
        metric_name = spec.surface_rule.metric_name
        for variant in variants:
            fold_values = {
                fold_id: float(validation_metrics[variant.variant_id][fold_id][metric_name])
                for fold_id in fold_ids
            }
            aggregate = float(sum(fold_values.values()))
            if metric_name == "entries_per_eligible_day":
                total_days = sum(
                    int(validation_metrics[variant.variant_id][fold_id]["eligible_day_count"])
                    for fold_id in fold_ids
                )
                total_entries = sum(
                    int(validation_metrics[variant.variant_id][fold_id]["entry_count"])
                    for fold_id in fold_ids
                )
                aggregate = float(total_entries / total_days) if total_days else 0.0
            rows.append(
                VariantEvidence.from_mapping(
                    variant.variant_id,
                    aggregate,
                    fold_values,
                    {
                        fold_id: validation_feasibility[variant.variant_id][fold_id]
                        for fold_id in fold_ids
                    },
                    data_role="validation_oos",
                )
            )
        return tuple(rows)

    selected_models: list[ModelBundle] = []
    development_trades: list[ScoutTrade] = []
    development_metrics: list[dict[str, Any]] = []
    causal_rows: list[dict[str, Any]] = []
    finalizations: list[dict[str, Any]] = []
    promotion_block_reasons: list[str] = []
    selected_variant_hashes: dict[str, str] = {}
    selected_configuration_hashes: dict[str, str] = {}
    selected_model_bundle_sha256s: dict[str, str] = {}
    selected_path_hashes: dict[str, str] = {}
    local_configuration_hashes: set[str] = set()
    local_cell_count = 0
    for prepared in prepared_folds:
        fold_id = prepared.window.development_id
        fold_evidence = evidence_for(spec.oat_plan.variants, (fold_id,))
        fold_assessment = assess_sensitivity(
            spec.oat_plan,
            fold_evidence,
            spec.surface_rule,
        )
        proposal = None
        midpoint_evidence = None
        eligible = tuple(
            surface for surface in fold_assessment.surfaces if surface.local_midpoint_eligible
        )
        other_surfaces = tuple(
            surface for surface in fold_assessment.surfaces if not surface.local_midpoint_eligible
        )
        if len(eligible) == 1 and all(
            surface.shape == "plateau" and surface.plateau_side in {"both", "baseline"}
            for surface in other_surfaces
        ):
            proposal = propose_local_midpoint(spec.oat_plan, fold_assessment)
            midpoint_model = _variant_model(
                prepared,
                proposal.variant,
                fold_fit_caches[fold_id],
            )
            _midpoint_trades, midpoint_metrics = _evaluate_prepared_role(
                prepared,
                spec,
                midpoint_model,
                role="validation_oos",
                availability_semantics=True,
            )
            metric_value = float(midpoint_metrics[spec.surface_rule.metric_name])
            midpoint_feasibility = _validation_feasibility_payload(
                midpoint_metrics,
                fold_causal_checks[fold_id],
                spec.selection_feasibility,
            )
            midpoint_evidence = VariantEvidence.from_mapping(
                proposal.variant.variant_id,
                metric_value,
                {fold_id: metric_value},
                {fold_id: midpoint_feasibility},
                data_role="validation_oos",
            )
            validation_metrics[proposal.variant.variant_id] = {fold_id: midpoint_metrics}
            validation_feasibility[proposal.variant.variant_id] = {
                fold_id: midpoint_feasibility
            }
            configuration_sha256 = _configuration_sha256(
                executable_programs=spec.executable_programs,
                parameters=proposal.variant.parameters,
            )
            configuration_hash_by_variant_id[proposal.variant.variant_id] = (
                configuration_sha256
            )
            local_configuration_hashes.add(configuration_sha256)
            local_cell_count += 1
        finalization = finalize_sensitivity_choice(
            spec.oat_plan,
            fold_assessment,
            spec.surface_rule,
            proposal=proposal,
            midpoint_evidence=midpoint_evidence,
        )
        selected = finalization.selected_variant
        selected_model = _variant_model(
            prepared,
            selected,
            fold_fit_caches[fold_id],
        )
        fold_trades, fold_metrics = _evaluate_prepared_role(
            prepared,
            spec,
            selected_model,
            role="development_cv",
            availability_semantics=True,
        )
        fold_metrics["selected_variant_id"] = selected.variant_id
        fold_metrics["selected_variant_sha256"] = selected.variant_sha256
        fold_metrics["selection_finalization_sha256"] = finalization.finalization_sha256
        selected_configuration_sha256 = configuration_hash_by_variant_id[selected.variant_id]
        selected_model_bundle_sha256 = sha256_payload(selected_model.to_payload())
        selected_path_sha256 = sha256_payload(
            {
                "schema": "axiom_rift_v2_selected_path_v1",
                "configuration_sha256": selected_configuration_sha256,
                "fold_id": fold_id,
                "split_set_id": spec.split_set_id,
                "selection_source_role": "validation_oos",
                "evaluation_target_role": "development_cv",
                "selection_rule_sha256": selection_rule_sha256,
                "selected_model_bundle_sha256": selected_model_bundle_sha256,
            }
        )
        fold_metrics["selected_configuration_sha256"] = selected_configuration_sha256
        fold_metrics["selected_model_bundle_sha256"] = selected_model_bundle_sha256
        fold_metrics["selected_path_sha256"] = selected_path_sha256
        selected_models.append(selected_model)
        development_trades.extend(fold_trades)
        development_metrics.append(fold_metrics)
        causal_rows.append(fold_causal_checks[fold_id])
        finalizations.append(finalization.to_payload())
        promotion_block_reasons.extend(
            f"{fold_id}:{reason}" for reason in finalization.promotion_block_reasons
        )
        selected_variant_hashes[fold_id] = selected.variant_sha256
        selected_configuration_hashes[fold_id] = selected_configuration_sha256
        selected_model_bundle_sha256s[fold_id] = selected_model_bundle_sha256
        selected_path_hashes[fold_id] = selected_path_sha256

    all_fold_ids = tuple(prepared.window.development_id for prepared in prepared_folds)
    global_evidence = evidence_for(spec.oat_plan.variants, all_fold_ids)
    global_assessment = assess_sensitivity(
        spec.oat_plan,
        global_evidence,
        spec.surface_rule,
    )
    sensitivity_state = _surface_sensitivity_state(global_assessment)
    if promotion_block_reasons and sensitivity_state is SensitivityState.PLATEAU:
        sensitivity_state = SensitivityState.UNSTABLE
    metrics, observations = _aggregate_nested_metrics(
        tuple(development_metrics),
        tuple(development_trades),
        tuple(causal_rows),
    )
    kpi_evaluation = interpret_kpis(
        "S",
        observations,
        spec.evaluation_profile,
        tuning=TuningContext(
            sensitivity_state=sensitivity_state,
            sensitivity_budget_remaining=0,
            calibration_budget_remaining=0,
        ),
    )
    metrics["kpi_evaluation"] = kpi_evaluation.to_payload()
    metrics["sensitivity_assessment"] = global_assessment.to_payload()
    configuration_hashes = sorted(set(configuration_hash_by_variant_id.values()))
    job_unique_configuration_count = len(configuration_hashes)
    validation_cells = len(spec.oat_plan.variants) * len(prepared_folds) + local_cell_count
    family_hashes_before = list(spec.trial_plan["family_configuration_hashes_before"])
    global_hashes_before = list(spec.trial_plan["global_configuration_hashes_before"])
    family_hashes_after = sorted(set(family_hashes_before) | set(configuration_hashes))
    global_hashes_after = sorted(set(global_hashes_before) | set(configuration_hashes))
    trial_accounting = {
        "schema": "axiom_rift_v2_nested_trial_accounting_v1",
        "family_id": family_id,
        "configuration_hashes": configuration_hashes,
        "configuration_trials": job_unique_configuration_count,
        "job_unique_configuration_count": job_unique_configuration_count,
        "new_family_configuration_trials": len(
            set(configuration_hashes) - set(family_hashes_before)
        ),
        "validation_evaluation_cells": validation_cells,
        "local_calibration_trials": len(local_configuration_hashes),
        "inner_selection_events": len(prepared_folds) if spec.oat_plan.knobs else 0,
        "development_selected_paths": len(prepared_folds),
        "family_trials_before": int(spec.trial_plan["family_trials_before"]),
        "family_configuration_hashes_before": family_hashes_before,
        "family_history_sha256_before": spec.trial_plan["family_history_sha256_before"],
        "family_configuration_hashes_after": family_hashes_after,
        "family_history_sha256_after": _history_sha256(family_hashes_after),
        "family_trials_cumulative": len(family_hashes_after),
        "global_trials_before": int(spec.trial_plan["global_trials_before"]),
        "global_configuration_hashes_before": global_hashes_before,
        "global_history_sha256_before": spec.trial_plan["global_history_sha256_before"],
        "global_configuration_hashes_after": global_hashes_after,
        "global_history_sha256_after": _history_sha256(global_hashes_after),
        "global_trials_cumulative": len(global_hashes_after),
        "holdout_reveals": 0,
        "development_variant_selection": False,
    }
    if job_unique_configuration_count > int(spec.trial_plan["unique_variant_cap"]):
        raise ScoutSpecError("nested scout exceeded preregistered unique variant cap")
    if validation_cells > int(spec.trial_plan["validation_evaluation_cell_cap"]):
        raise ScoutSpecError("nested scout exceeded preregistered evaluation-cell cap")
    causal_payload = {
        "schema": "axiom_rift_v2_nested_causal_checks_v1",
        "all_pass": bool(metrics["causal_checks_all_pass"]),
        "validation_only_selection": True,
        "development_paths_per_fold": 1,
        "development_variant_selection": False,
        "folds": causal_rows,
    }
    nested_selection = {
        "schema": "axiom_rift_v2_nested_selection_v1",
        "plan": spec.oat_plan.to_payload(),
        "global_validation_assessment": global_assessment.to_payload(),
        "validation_surface": {
            "metric_name": spec.surface_rule.metric_name,
            "variants": {
                variant_id: {
                    "configuration_sha256": configuration_hash_by_variant_id[variant_id],
                    "folds": {
                        fold_id: {
                            "metrics": rows[fold_id],
                            "feasibility": validation_feasibility[variant_id][fold_id],
                        }
                        for fold_id in sorted(rows)
                    },
                }
                for variant_id, rows in sorted(validation_metrics.items())
            },
        },
        "fold_finalizations": finalizations,
        "selection_rule_sha256": selection_rule_sha256,
        "source_data_role": "validation_oos",
        "freeze_target_role": "development_cv",
        "development_paths_per_fold": 1,
        "development_variant_selection": False,
        "promotion_blocked": bool(promotion_block_reasons),
        "promotion_block_reasons": sorted(set(promotion_block_reasons)),
        "selected_variant_hashes": selected_variant_hashes,
        "selected_configuration_hashes": selected_configuration_hashes,
        "selected_model_bundle_sha256s": selected_model_bundle_sha256s,
        "selected_path_hashes": selected_path_hashes,
    }
    outcome = kpi_evaluation.route
    gate_passed = outcome == "route_to_R"
    metrics["feature_order_sha256"] = feature_order_sha256()
    metrics["feature_program_sha256"] = feature_program_sha256(contract)
    body = {
        "outcome": outcome,
        "gate_passed": gate_passed,
        "metrics": metrics,
        "causal_checks": causal_payload,
        "models": [model.to_payload() for model in selected_models],
        "trades": [trade.to_payload() for trade in development_trades],
        "nested_selection": nested_selection,
        "trial_accounting": trial_accounting,
        "selection_rule_sha256": selection_rule_sha256,
        "selected_variant_hashes": selected_variant_hashes,
        "selected_configuration_hashes": selected_configuration_hashes,
        "selected_model_bundle_sha256s": selected_model_bundle_sha256s,
        "selected_path_hashes": selected_path_hashes,
        "claim_ceiling": "diagnostic_observation",
        "economics_claim_allowed": False,
    }
    result_sha256 = sha256_payload(body)
    return NestedScoutResult(
        outcome=outcome,
        gate_passed=gate_passed,
        metrics=metrics,
        causal_checks=causal_payload,
        models=tuple(selected_models),
        trades=tuple(development_trades),
        nested_selection=nested_selection,
        trial_accounting=trial_accounting,
        selection_rule_sha256=selection_rule_sha256,
        selected_variant_hashes=selected_variant_hashes,
        selected_configuration_hashes=selected_configuration_hashes,
        selected_model_bundle_sha256s=selected_model_bundle_sha256s,
        selected_path_hashes=selected_path_hashes,
        result_sha256=result_sha256,
    )


def run_causal_scout(
    spec: ScoutSpec,
    *,
    base_frame_path: Path,
    split_source_path: Path,
    boundary_source_path: Path,
) -> ScoutResult:
    started = time.monotonic()
    contract = load_feature_contract(spec.feature_contract_path)
    windows = load_fold_windows(split_source_path, spec.anchors)
    gaps = load_non_allow_gaps(boundary_source_path)
    if len(gaps) != 57:
        raise ScoutSpecError(f"expected 57 non-ALLOW boundaries, found {len(gaps)}")
    models: list[ModelBundle] = []
    trades: list[ScoutTrade] = []
    fold_metrics: list[dict[str, Any]] = []
    causal_rows: list[dict[str, Any]] = []
    for window in windows:
        bars = load_fold_bars(base_frame_path, window)
        model, fold_trades, metrics, causal = _run_fold(window, bars, spec, gaps)
        models.append(model)
        trades.extend(fold_trades)
        fold_metrics.append(metrics)
        causal_rows.append(causal)
    metrics, gate_passed = _aggregate_metrics(
        tuple(fold_metrics), tuple(trades), spec.acceptance_profile, tuple(causal_rows)
    )
    metrics["elapsed_seconds"] = time.monotonic() - started
    metrics["feature_order_sha256"] = feature_order_sha256()
    metrics["feature_program_sha256"] = feature_program_sha256(contract)
    causal_payload = {
        "schema": "axiom_rift_v2_causal_checks_v1",
        "all_pass": all(metrics["gate_checks"][key] for key in ("causal_checks_all_pass",)),
        "folds": causal_rows,
    }
    body = {
        "outcome": "route_to_R" if gate_passed else "scout_rejected",
        "gate_passed": gate_passed,
        "metrics": metrics,
        "causal_checks": causal_payload,
        "models": [model.to_payload() for model in models],
        "trades": [trade.to_payload() for trade in trades],
        "claim_ceiling": "diagnostic_observation",
        "economics_claim_allowed": False,
    }
    result_sha256 = sha256_payload(body)
    return ScoutResult(
        outcome=body["outcome"],
        gate_passed=gate_passed,
        metrics=metrics,
        causal_checks=causal_payload,
        models=tuple(models),
        trades=tuple(trades),
        result_sha256=result_sha256,
    )
