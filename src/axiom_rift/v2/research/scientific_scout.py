"""Pure compression-release Scout evaluation for the active V2 epoch.

The module reads in-memory bars and returns deterministic payloads.  It does
not write receipts, artifacts, registries, or control state.  Five frozen
release configurations are inspected on ``validation_oos``; only the three
continuation roles can be selected, and exactly one frozen path per surviving
fold is subsequently inspected on ``development_cv``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import math
import re
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence

import numpy as np

from axiom_rift.v2.data.splits import SCOUT_ANCHORS, assert_split_access
from axiom_rift.v2.data.blackouts import BoundaryGap, interval_crosses_non_allow_boundary
from axiom_rift.v2.features import BarArrays
from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.research.evaluation import (
    EvaluationProfile,
    MetricObservation,
    interpret_kpis,
)
from axiom_rift.v2.research.scout import (
    TIME_FORMAT,
    FoldWindow,
    ScoutTrade,
    _market_parts,
    _role_indices,
)
from axiom_rift.v2.research.specs import IndexBoundary


BUNDLE_ROLES = (
    "continuation_low",
    "continuation_base",
    "continuation_high",
    "failed_break_reversal",
    "compression_ablation",
)
DIRECTIONAL_BUNDLE_ROLES = (
    "short_reversal_low",
    "short_reversal_base",
    "short_reversal_high",
    "long_reversal_control",
    "short_continuation_control",
)
CONTINUATION_ROLES = BUNDLE_ROLES[:3]
FALSIFIER_ROLES = BUNDLE_ROLES[3:]
PREFERRED_CONTINUATION_ORDER = (
    "continuation_base",
    "continuation_low",
    "continuation_high",
)
SCIENTIFIC_SELECTION_RULE_PAYLOAD = {
    "schema": "axiom_rift_v2_compression_release_selection_rule_v1",
    "selection_source_data_role": "validation_oos",
    "development_variant_selection": False,
    "utility_metric": "total_fixed_lot_net_broker_points",
    "continuation_roles": list(CONTINUATION_ROLES),
    "control_roles": list(FALSIFIER_ROLES),
    "all_roles_must_be_evaluable": True,
    "preferred_continuation_order": list(PREFERRED_CONTINUATION_ORDER),
    "plateau_tolerance_broker_points": 100.0,
    "ablation_noninferiority_rejects_compression": True,
    "competing_reversal_dominance_rejects_continuation": True,
}
SCIENTIFIC_SELECTION_RULE_SHA256 = sha256_payload(
    SCIENTIFIC_SELECTION_RULE_PAYLOAD
)
DIRECTIONAL_SELECTION_RULE_PAYLOAD = {
    "schema": "axiom_rift_v2_directional_reversal_selection_rule_v1",
    "selection_source_data_role": "validation_oos",
    "development_variant_selection": False,
    "utility_metric": "strict_observed_shadow_total_fixed_lot_net_broker_points",
    "primary_roles": list(DIRECTIONAL_BUNDLE_ROLES[:3]),
    "control_roles": list(DIRECTIONAL_BUNDLE_ROLES[3:]),
    "required_feasible_roles": [
        "short_reversal_base",
        "long_reversal_control",
        "short_continuation_control",
    ],
    "preferred_primary_order": [
        "short_reversal_base",
        "short_reversal_low",
        "short_reversal_high",
    ],
    "plateau_tolerance_broker_points": 100.0,
    "long_reversal_noninferiority_rejects_short_asymmetry": True,
    "short_continuation_noninferiority_rejects_reversal": True,
}
DIRECTIONAL_SELECTION_RULE_SHA256 = sha256_payload(
    DIRECTIONAL_SELECTION_RULE_PAYLOAD
)


def selection_layout_for_hash(selection_rule_sha256: str) -> Mapping[str, Any]:
    """Return one immutable role layout without widening runtime dispatch."""

    if selection_rule_sha256 == SCIENTIFIC_SELECTION_RULE_SHA256:
        return MappingProxyType(
            {
                "roles": BUNDLE_ROLES,
                "primary_roles": CONTINUATION_ROLES,
                "control_roles": FALSIFIER_ROLES,
                "required_feasible_roles": BUNDLE_ROLES,
                "preferred_order": PREFERRED_CONTINUATION_ORDER,
                "utility_metric": "net_broker_points",
                "reversal_roles": ("failed_break_reversal",),
                "layout": "compression_release",
            }
        )
    if selection_rule_sha256 == DIRECTIONAL_SELECTION_RULE_SHA256:
        return MappingProxyType(
            {
                "roles": DIRECTIONAL_BUNDLE_ROLES,
                "primary_roles": DIRECTIONAL_BUNDLE_ROLES[:3],
                "control_roles": DIRECTIONAL_BUNDLE_ROLES[3:],
                "required_feasible_roles": (
                    "short_reversal_base",
                    "long_reversal_control",
                    "short_continuation_control",
                ),
                "preferred_order": (
                    "short_reversal_base",
                    "short_reversal_low",
                    "short_reversal_high",
                ),
                "utility_metric": "shadow_net_broker_points",
                "reversal_roles": DIRECTIONAL_BUNDLE_ROLES[:4],
                "layout": "directional_reversal",
            }
        )
    raise ScientificScoutError("scientific Scout selection rule is not registered")
ANCHORS = tuple(sorted(SCOUT_ANCHORS))
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
LEGACY_TRADE_IMPLEMENTATION_KEY = "fixed_6bar_observed_spread_v1"
CAUSAL_SPREAD_FLOOR_IMPLEMENTATION_KEY = (
    "fixed_6bar_causal_spread_floor_v1"
)
TRADE_IMPLEMENTATION_KEYS = frozenset(
    {
        LEGACY_TRADE_IMPLEMENTATION_KEY,
        CAUSAL_SPREAD_FLOOR_IMPLEMENTATION_KEY,
    }
)


class ScientificScoutError(ValueError):
    """Raised when the read-only Scout surface is incomplete or non-causal."""


class EventConfigurationLike(Protocol):
    role: str

    @property
    def identity_sha256(self) -> str: ...


class CompressionEvaluationLike(Protocol):
    configuration_sha256: str
    executable_sha256: str
    directions: Sequence[int]
    scores: Sequence[float]
    valid_mask: Sequence[bool]


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None


def trial_history_sha256(configuration_hashes: Sequence[str]) -> str:
    """Hash the complete, de-duplicated executable configuration history."""

    normalized = sorted(set(configuration_hashes))
    if not all(_is_sha256(value) for value in normalized):
        raise ScientificScoutError("trial history contains an invalid configuration hash")
    return sha256_payload(normalized)


EMPTY_TRIAL_HISTORY_SHA256 = trial_history_sha256(())


@dataclass(frozen=True)
class ScientificScoutSpec:
    goal_id: str
    hypothesis_id: str
    family_id: str
    bundle_role_hashes: Mapping[str, str]
    release_configuration_hashes: Mapping[str, str]
    evaluation_profile: EvaluationProfile
    runtime_sha256: str
    runtime_executable_sha256: str
    selection_rule_sha256: str
    trade_implementation_key: str = LEGACY_TRADE_IMPLEMENTATION_KEY
    family_configuration_hashes_before: tuple[str, ...] = ()
    family_history_sha256_before: str = EMPTY_TRIAL_HISTORY_SHA256
    global_configuration_hashes_before: tuple[str, ...] = ()
    global_history_sha256_before: str = EMPTY_TRIAL_HISTORY_SHA256
    anchors: tuple[str, ...] = ANCHORS
    hold_bars: int = 6
    point_size: float = 0.01
    maximum_daily_entries: int = 10
    minimum_validation_trades_per_fold: int = 20
    plateau_tolerance_broker_points: float = 100.0
    sizing_mode: str = "fixed_lot"
    program_registry_path: str = ""
    program_registry_sha256: str = ""
    program_identities: Mapping[str, Any] = field(default_factory=dict)
    spec_sha256: str = ""
    acceptance_profile: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if re.fullmatch(r"V2G[0-9]{4}", self.goal_id) is None:
            raise ScientificScoutError("goal_id is invalid")
        if re.fullmatch(r"V2H[0-9]{4}", self.hypothesis_id) is None:
            raise ScientificScoutError("hypothesis_id is invalid")
        if not self.family_id or not self.family_id.isascii():
            raise ScientificScoutError("family_id must be nonempty ASCII")
        if tuple(self.anchors) != ANCHORS:
            raise ScientificScoutError("Scout anchors must be V2D002, V2D005, and V2D008")
        fixed = (
            self.hold_bars == 6
            and self.point_size == 0.01
            and self.maximum_daily_entries == 10
            and self.minimum_validation_trades_per_fold == 20
            and self.plateau_tolerance_broker_points == 100.0
            and self.sizing_mode == "fixed_lot"
        )
        if not fixed:
            raise ScientificScoutError("compression Scout fixed parameters differ from preregistration")
        layout = selection_layout_for_hash(self.selection_rule_sha256)
        role_names = tuple(layout["roles"])
        roles = dict(self.bundle_role_hashes)
        if set(roles) != set(role_names) or not all(_is_sha256(value) for value in roles.values()):
            raise ScientificScoutError("bundle_role_hashes must cover one registered five-role layout")
        if len(set(roles.values())) != len(role_names):
            raise ScientificScoutError("each Scout role requires a distinct executable bundle hash")
        release_hashes = dict(self.release_configuration_hashes)
        if (
            set(release_hashes) != set(role_names)
            or not all(_is_sha256(value) for value in release_hashes.values())
            or len(set(release_hashes.values())) != len(role_names)
        ):
            raise ScientificScoutError(
                "release_configuration_hashes must cover the registered runtime roles"
            )
        if not isinstance(self.evaluation_profile, EvaluationProfile):
            raise ScientificScoutError("scientific Scout evaluation profile is invalid")
        if (
            not _is_sha256(self.runtime_sha256)
            or not _is_sha256(self.runtime_executable_sha256)
            or self.selection_rule_sha256 not in {
                SCIENTIFIC_SELECTION_RULE_SHA256,
                DIRECTIONAL_SELECTION_RULE_SHA256,
            }
        ):
            raise ScientificScoutError("scientific Scout runtime binding is invalid")
        if self.trade_implementation_key not in TRADE_IMPLEMENTATION_KEYS:
            raise ScientificScoutError(
                "scientific Scout trade implementation is invalid"
            )
        if self.program_registry_path:
            if (
                "\\" in self.program_registry_path
                or not _is_sha256(self.program_registry_sha256)
                or not _is_sha256(self.spec_sha256)
                or not self.program_identities
            ):
                raise ScientificScoutError("scientific Scout program binding is incomplete")
        family_before = tuple(sorted(set(self.family_configuration_hashes_before)))
        global_before = tuple(sorted(set(self.global_configuration_hashes_before)))
        if trial_history_sha256(family_before) != self.family_history_sha256_before:
            raise ScientificScoutError("family trial history hash mismatch")
        if trial_history_sha256(global_before) != self.global_history_sha256_before:
            raise ScientificScoutError("global trial history hash mismatch")
        object.__setattr__(self, "anchors", tuple(self.anchors))
        object.__setattr__(self, "bundle_role_hashes", MappingProxyType(roles))
        object.__setattr__(
            self,
            "release_configuration_hashes",
            MappingProxyType(release_hashes),
        )
        object.__setattr__(self, "family_configuration_hashes_before", family_before)
        object.__setattr__(self, "global_configuration_hashes_before", global_before)
        object.__setattr__(self, "program_identities", MappingProxyType(dict(self.program_identities)))
        object.__setattr__(self, "acceptance_profile", MappingProxyType(dict(self.acceptance_profile)))

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_scientific_scout_spec_v1",
            "goal_id": self.goal_id,
            "hypothesis_id": self.hypothesis_id,
            "family_id": self.family_id,
            "bundle_role_hashes": dict(self.bundle_role_hashes),
            "release_configuration_hashes": dict(self.release_configuration_hashes),
            "evaluation_profile_id": self.evaluation_profile.profile_id,
            "runtime_sha256": self.runtime_sha256,
            "runtime_executable_sha256": self.runtime_executable_sha256,
            "selection_rule_sha256": self.selection_rule_sha256,
            "trade_implementation_key": self.trade_implementation_key,
            "family_configuration_hashes_before": list(self.family_configuration_hashes_before),
            "family_history_sha256_before": self.family_history_sha256_before,
            "global_configuration_hashes_before": list(self.global_configuration_hashes_before),
            "global_history_sha256_before": self.global_history_sha256_before,
            "anchors": list(self.anchors),
            "hold_bars": self.hold_bars,
            "point_size": self.point_size,
            "maximum_daily_entries": self.maximum_daily_entries,
            "minimum_validation_trades_per_fold": self.minimum_validation_trades_per_fold,
            "plateau_tolerance_broker_points": self.plateau_tolerance_broker_points,
            "sizing_mode": self.sizing_mode,
            "program_registry_path": self.program_registry_path,
            "program_registry_sha256": self.program_registry_sha256,
            "program_identities": dict(self.program_identities),
            "spec_sha256": self.spec_sha256,
            "acceptance_profile": dict(self.acceptance_profile),
        }


@dataclass(frozen=True)
class ScientificFold:
    window: FoldWindow
    bars: BarArrays
    non_allow_gaps: tuple[BoundaryGap, ...] = ()

    def __post_init__(self) -> None:
        if self.window.development_id not in SCOUT_ANCHORS:
            raise ScientificScoutError("fold is not a preregistered Scout anchor")
        if not (
            self.window.train_end < self.window.validation_start
            and self.window.validation_end < self.window.development_start
        ):
            raise ScientificScoutError("fold roles must remain chronologically isolated")
        size = len(self.bars)
        if size < 1 or any(len(getattr(self.bars, name)) != size for name in (
            "open", "high", "low", "close", "tick_volume", "spread"
        )):
            raise ScientificScoutError("bar arrays have inconsistent lengths")
        if any(left >= right for left, right in zip(self.bars.time, self.bars.time[1:])):
            raise ScientificScoutError("bar times must be strictly chronological")
        numeric = np.column_stack((
            self.bars.open, self.bars.high, self.bars.low, self.bars.close,
            self.bars.tick_volume, self.bars.spread,
        ))
        if not np.isfinite(numeric).all() or np.any(self.bars.spread < 0.0):
            raise ScientificScoutError("bar values must be finite and spreads nonnegative")
        object.__setattr__(self, "non_allow_gaps", tuple(self.non_allow_gaps))


@dataclass(frozen=True)
class RoleEvaluation:
    fold_id: str
    data_role: str
    configuration_role: str
    configuration_sha256: str
    metrics: Mapping[str, Any]
    causal_checks: Mapping[str, bool]
    trades: tuple[ScoutTrade, ...]
    evaluation_sha256: str

    @property
    def feasible(self) -> bool:
        return bool(self.metrics["selection_feasible"])

    @property
    def utility(self) -> float | None:
        value = self.metrics["net_broker_points"]
        return None if value is None else float(value)

    def to_payload(self) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "data_role": self.data_role,
            "configuration_role": self.configuration_role,
            "configuration_sha256": self.configuration_sha256,
            "metrics": dict(self.metrics),
            "causal_checks": dict(self.causal_checks),
            "trades": [trade.to_payload() for trade in self.trades],
            "evaluation_sha256": self.evaluation_sha256,
        }


@dataclass(frozen=True)
class FoldSelection:
    fold_id: str
    selected_role: str | None
    selected_configuration_sha256: str | None
    selection_basis: str
    plateau_roles: tuple[str, ...]
    falsifier_triggered: bool
    validation_contrasts: Mapping[str, Any]
    selection_sha256: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "selected_role": self.selected_role,
            "selected_configuration_sha256": self.selected_configuration_sha256,
            "selection_basis": self.selection_basis,
            "plateau_roles": list(self.plateau_roles),
            "falsifier_triggered": self.falsifier_triggered,
            "validation_contrasts": dict(self.validation_contrasts),
            "selection_sha256": self.selection_sha256,
        }


@dataclass(frozen=True)
class ScientificScoutResult:
    outcome: str
    gate_passed: bool
    metrics: Mapping[str, Any]
    causal_checks: Mapping[str, Any]
    validation_evaluations: tuple[RoleEvaluation, ...]
    selections: tuple[FoldSelection, ...]
    development_evaluations: tuple[RoleEvaluation, ...]
    selected_path_hashes: Mapping[str, str]
    trial_accounting: Mapping[str, Any]
    result_sha256: str
    claim_ceiling: str = "diagnostic_observation"
    mt5_executed: bool = False
    economics_claim_allowed: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_scientific_scout_result_v1",
            "outcome": self.outcome,
            "gate_passed": self.gate_passed,
            "metrics": dict(self.metrics),
            "causal_checks": dict(self.causal_checks),
            "validation_evaluations": [row.to_payload() for row in self.validation_evaluations],
            "selections": [row.to_payload() for row in self.selections],
            "development_evaluations": [row.to_payload() for row in self.development_evaluations],
            "selected_path_hashes": dict(self.selected_path_hashes),
            "trial_accounting": dict(self.trial_accounting),
            "result_sha256": self.result_sha256,
            "claim_ceiling": self.claim_ceiling,
            "mt5_executed": self.mt5_executed,
            "economics_claim_allowed": self.economics_claim_allowed,
        }


def scientific_kpi_observations(
    metrics: Mapping[str, Any],
    *,
    causal_checks_passed: bool,
    trade_implementation_key: str,
) -> dict[str, Any]:
    """Build the exact registered S observations used by producer and receipt audit."""

    unknown = metrics.get("unknown_cost_observation_count")
    observations: dict[str, Any] = {
        "causal_checks_all_pass": causal_checks_passed,
        "evaluable_trade_count": metrics.get("evaluable_trade_count"),
        "unknown_cost_observation_count": unknown,
        "net_broker_points": (
            metrics.get("net_broker_points")
            if unknown == 0
            else MetricObservation.not_evaluable("unknown_cost_observations")
        ),
        "positive_net_fold_count": metrics.get("positive_net_fold_count"),
    }
    if trade_implementation_key == CAUSAL_SPREAD_FLOOR_IMPLEMENTATION_KEY:
        observations.update(
            {
                "shadow_evaluable_trade_count": metrics.get(
                    "shadow_evaluable_trade_count"
                ),
                "shadow_net_broker_points": metrics.get(
                    "shadow_net_broker_points"
                ),
                "shadow_positive_net_fold_count": metrics.get(
                    "shadow_positive_net_fold_count"
                ),
            }
        )
    return observations


def _slice_bars(bars: BarArrays, end: int) -> BarArrays:
    return BarArrays(
        time=bars.time[:end], open=bars.open[:end], high=bars.high[:end],
        low=bars.low[:end], close=bars.close[:end],
        tick_volume=bars.tick_volume[:end], spread=bars.spread[:end],
    )


def _signal_arrays(evaluation: CompressionEvaluationLike, size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    directions = np.asarray(evaluation.directions, dtype=np.int8)
    scores = np.asarray(evaluation.scores, dtype=np.float64)
    valid = np.asarray(evaluation.valid_mask, dtype=bool)
    if directions.shape != (size,) or scores.shape != (size,) or valid.shape != (size,):
        raise ScientificScoutError("compression evaluation arrays must match the bar count")
    if not set(np.unique(directions)).issubset({-1, 0, 1}):
        raise ScientificScoutError("compression directions must be -1, 0, or 1")
    selected = valid & (directions != 0)
    if not np.isfinite(scores[selected]).all():
        raise ScientificScoutError("selected compression scores must be finite")
    if np.any((directions != 0) & ~valid):
        raise ScientificScoutError("invalid compression observations may not emit directions")
    return directions, scores, valid


def _validate_runtime_evaluation(
    evaluation: CompressionEvaluationLike,
    *,
    role: str,
    spec: ScientificScoutSpec,
) -> None:
    if evaluation.configuration_sha256 != spec.release_configuration_hashes[role]:
        raise ScientificScoutError(
            f"runtime configuration identity differs from preregistration: {role}"
        )
    if evaluation.executable_sha256 != spec.runtime_executable_sha256:
        raise ScientificScoutError("runtime executable identity differs from preregistration")


def evaluate_signal_role(
    *, fold_id: str, bars: BarArrays, boundary: IndexBoundary,
    configuration_role: str, configuration_sha256: str,
    evaluation: CompressionEvaluationLike, spec: ScientificScoutSpec,
    prefix_invariant: bool = True,
    non_allow_gaps: tuple[BoundaryGap, ...] = (),
) -> RoleEvaluation:
    """Evaluate precomputed causal signals inside one isolated split role."""

    if boundary.role not in {"validation_oos", "development_cv"}:
        raise ScientificScoutError("unsupported Scout data role")
    layout = selection_layout_for_hash(spec.selection_rule_sha256)
    if configuration_role not in layout["roles"] or not _is_sha256(configuration_sha256):
        raise ScientificScoutError("configuration identity is invalid")
    boundary.validate(len(bars))
    directions, scores, _valid = _signal_arrays(evaluation, len(bars))
    causal_floor = (
        spec.trade_implementation_key
        == CAUSAL_SPREAD_FLOOR_IMPLEMENTATION_KEY
    )
    spread_values = np.asarray(bars.spread, dtype=np.float64)
    if causal_floor and (
        spread_values.shape != (len(bars),)
        or not np.isfinite(spread_values).all()
        or np.any(spread_values < 0.0)
    ):
        raise ScientificScoutError(
            "causal spread-floor inputs must be finite and nonnegative"
        )
    last_decision = boundary.end - 1 - spec.hold_bars
    daily_entries: dict[str, int] = defaultdict(int)
    occupied_until = -1
    trades: list[ScoutTrade] = []
    zero_decision_rejections = 0
    execution_spread_fallbacks = 0
    observed_execution_costs = 0
    zero_decision_by_hour: dict[int, int] = defaultdict(int)
    zero_decision_by_direction: dict[str, int] = defaultdict(int)
    fallback_by_hour: dict[int, int] = defaultdict(int)
    fallback_by_direction: dict[str, int] = defaultdict(int)
    lifecycle_inside = True
    boundary_crossings_excluded = True
    observed_features = getattr(evaluation, "features", None)
    for decision_index in range(boundary.start, max(boundary.start, last_decision)):
        direction = int(directions[decision_index])
        if direction == 0:
            continue
        market_day, market_hour = _market_parts(bars.time[decision_index])
        decision_spread = float(bars.spread[decision_index])
        if causal_floor and decision_spread == 0.0:
            zero_decision_rejections += 1
            zero_decision_by_hour[market_hour] += 1
            zero_decision_by_direction[
                "long" if direction > 0 else "short"
            ] += 1
            continue
        if decision_index < occupied_until:
            continue
        if daily_entries[market_day] >= spec.maximum_daily_entries:
            continue
        entry_index = decision_index + 1
        exit_index = entry_index + spec.hold_bars
        if exit_index >= boundary.end:
            lifecycle_inside = False
            continue
        dependency_bars = (
            26 if configuration_role in layout["reversal_roles"] else 25
        )
        lookback_index = max(0, decision_index - dependency_bars)
        if non_allow_gaps and interval_crosses_non_allow_boundary(
            bars.time[lookback_index], bars.time[exit_index], non_allow_gaps
        ):
            continue
        atr = None
        if observed_features is not None and decision_index < len(observed_features):
            atr = getattr(observed_features[decision_index], "atr_24", None)
        causal_cost = (
            float(decision_spread * spec.point_size / float(atr))
            if decision_spread > 0.0 and atr is not None and float(atr) > 0.0
            else 0.0
        )
        if decision_spread <= 0.0:
            gross = (
                direction
                * (float(bars.open[exit_index]) - float(bars.open[entry_index]))
                / spec.point_size
            )
            daily_entries[market_day] += 1
            occupied_until = exit_index
            trades.append(ScoutTrade(
                fold_id=fold_id,
                signal_time=bars.time[decision_index].strftime(TIME_FORMAT),
                entry_time=bars.time[entry_index].strftime(TIME_FORMAT),
                exit_time=bars.time[exit_index].strftime(TIME_FORMAT),
                direction=direction,
                score=float(scores[decision_index]),
                residual_band=0.0,
                causal_cost_edge=0.0,
                gross_broker_points=gross,
                spread_cost_broker_points=None,
                net_broker_points=None,
                evaluable_after_cost=False,
                exclusion_reason="unknown_decision_spread",
                market_day=market_day,
                market_hour=market_hour,
            ))
            continue
        if atr is not None and abs(float(scores[decision_index])) <= causal_cost:
            continue
        gross = (
            direction
            * (float(bars.open[exit_index]) - float(bars.open[entry_index]))
            / spec.point_size
        )
        daily_entries[market_day] += 1
        occupied_until = exit_index
        spread_index = entry_index if direction > 0 else exit_index
        required_spread = float(bars.spread[spread_index])
        execution_observed = required_spread > 0.0
        if causal_floor:
            effective_spread = (
                max(decision_spread, required_spread)
                if execution_observed
                else decision_spread
            )
            evaluable = True
            net = gross - effective_spread
            fallback_used = not execution_observed
            if fallback_used:
                execution_spread_fallbacks += 1
                fallback_by_hour[market_hour] += 1
                fallback_by_direction[
                    "long" if direction > 0 else "short"
                ] += 1
            else:
                observed_execution_costs += 1
            cost_source = (
                "decision_spread_floor"
                if fallback_used
                else "max_decision_and_execution_spread"
            )
        else:
            effective_spread = required_spread
            evaluable = execution_observed
            net = gross - required_spread if evaluable else None
            fallback_used = None
            cost_source = None
        trades.append(ScoutTrade(
            fold_id=fold_id,
            signal_time=bars.time[decision_index].strftime(TIME_FORMAT),
            entry_time=bars.time[entry_index].strftime(TIME_FORMAT),
            exit_time=bars.time[exit_index].strftime(TIME_FORMAT),
            direction=direction,
            score=float(scores[decision_index]),
            residual_band=0.0,
            causal_cost_edge=causal_cost,
            gross_broker_points=gross,
            spread_cost_broker_points=(
                effective_spread if evaluable else None
            ),
            net_broker_points=net,
            evaluable_after_cost=evaluable,
            exclusion_reason=None if evaluable else "unknown_required_spread",
            market_day=market_day,
            market_hour=market_hour,
            decision_spread_broker_points=(
                decision_spread if causal_floor else None
            ),
            applicable_execution_spread_broker_points=(
                required_spread if causal_floor else None
            ),
            cost_source=cost_source,
            execution_spread_fallback_used=fallback_used,
        ))
    unknown = sum(not trade.evaluable_after_cost for trade in trades)
    evaluable = [trade for trade in trades if trade.evaluable_after_cost]
    net_values = [float(trade.net_broker_points) for trade in evaluable if trade.net_broker_points is not None]
    shadow_evaluable = [
        trade
        for trade in evaluable
        if trade.execution_spread_fallback_used is False
    ]
    shadow_net_values = [
        float(trade.net_broker_points)
        for trade in shadow_evaluable
        if trade.net_broker_points is not None
    ]
    eligible_days = sorted({_market_parts(value)[0] for value in bars.time[boundary.start:boundary.end]})
    daily_counts = [daily_entries.get(day, 0) for day in eligible_days]
    gains = sum(value for value in net_values if value > 0.0)
    losses = -sum(value for value in net_values if value < 0.0)
    after_cost_evaluable = unknown == 0
    causal_checks = {
        "completed_bar_signal": True,
        "train_fit_hashed_no_op": True,
        "next_open_entry": True,
        "trade_lifecycle_inside_role": lifecycle_inside,
        "non_allow_boundaries_excluded": boundary_crossings_excluded,
        "sequential_no_future_ranking": True,
        "daily_cap_respected": max(daily_counts, default=0) <= spec.maximum_daily_entries,
        "prefix_invariance": bool(prefix_invariant),
        "development_variant_selection": False,
    }
    if (
        spec.trade_implementation_key
        == CAUSAL_SPREAD_FLOOR_IMPLEMENTATION_KEY
    ):
        causal_checks.update(
            {
                "zero_decision_rejected_before_admission": all(
                    trade.decision_spread_broker_points is not None
                    and trade.decision_spread_broker_points > 0.0
                    for trade in trades
                ),
                "future_execution_spread_not_signal_gate": True,
                "all_admitted_costs_positive": all(
                    trade.spread_cost_broker_points is not None
                    and trade.spread_cost_broker_points > 0.0
                    for trade in trades
                ),
                "observed_execution_cost_not_undercharged": all(
                    trade.execution_spread_fallback_used is True
                    or (
                        trade.spread_cost_broker_points is not None
                        and trade.decision_spread_broker_points is not None
                        and trade.applicable_execution_spread_broker_points
                        is not None
                        and trade.spread_cost_broker_points
                        >= trade.decision_spread_broker_points
                        and trade.spread_cost_broker_points
                        >= trade.applicable_execution_spread_broker_points
                    )
                    for trade in trades
                ),
                "decision_floor_is_not_true_cost_upper_bound": True,
            }
        )
    causal_passed = all(value for key, value in causal_checks.items() if key != "development_variant_selection") and not causal_checks["development_variant_selection"]
    feasible = (
        boundary.role == "validation_oos"
        and causal_passed and unknown == 0
        and len(evaluable) >= spec.minimum_validation_trades_per_fold
        and (
            spec.trade_implementation_key
            != CAUSAL_SPREAD_FLOOR_IMPLEMENTATION_KEY
            or len(shadow_evaluable) >= spec.minimum_validation_trades_per_fold
        )
    )
    metrics: dict[str, Any] = {
        "entry_count": len(trades),
        "evaluable_trade_count": len(evaluable),
        "unknown_cost_observation_count": unknown,
        "eligible_day_count": len(eligible_days),
        "entries_per_eligible_day": len(trades) / len(eligible_days) if eligible_days else 0.0,
        "maximum_daily_entries": max(daily_counts, default=0),
        "gross_broker_points": sum(
            float(trade.gross_broker_points)
            for trade in trades
            if trade.gross_broker_points is not None
        ),
        "spread_cost_broker_points": sum(float(trade.spread_cost_broker_points) for trade in evaluable),
        "net_broker_points": sum(net_values) if after_cost_evaluable else None,
        "profit_factor": gains / losses if after_cost_evaluable and losses > 0.0 else None,
        "expectancy_broker_points": float(np.mean(net_values)) if after_cost_evaluable and net_values else None,
        "after_cost_metric_state": (
            "causal_policy_evaluable"
            if causal_floor and after_cost_evaluable
            else "observed"
            if after_cost_evaluable
            else "not_evaluable"
        ),
        "selection_feasible": feasible,
        "sizing_mode": "fixed_lot",
    }
    if (
        spec.trade_implementation_key
        == CAUSAL_SPREAD_FLOOR_IMPLEMENTATION_KEY
    ):
        metrics.update(
            {
                "zero_decision_spread_rejection_count": (
                    zero_decision_rejections
                ),
                "execution_spread_fallback_count": (
                    execution_spread_fallbacks
                ),
                "observed_execution_cost_trade_count": (
                    observed_execution_costs
                ),
                "shadow_evaluable_trade_count": len(shadow_evaluable),
                "shadow_net_broker_points": sum(shadow_net_values),
                "cost_policy_diagnostics": {
                    "zero_decision_rejections_by_market_hour": {
                        str(key): value
                        for key, value in sorted(zero_decision_by_hour.items())
                    },
                    "zero_decision_rejections_by_direction": dict(
                        sorted(zero_decision_by_direction.items())
                    ),
                    "execution_spread_fallbacks_by_market_hour": {
                        str(key): value
                        for key, value in sorted(fallback_by_hour.items())
                    },
                    "execution_spread_fallbacks_by_direction": dict(
                        sorted(fallback_by_direction.items())
                    ),
                },
            }
        )
    body = {
        "fold_id": fold_id, "data_role": boundary.role,
        "configuration_role": configuration_role,
        "configuration_sha256": configuration_sha256,
        "metrics": metrics, "causal_checks": causal_checks,
        "trades": [trade.to_payload() for trade in trades],
    }
    return RoleEvaluation(
        fold_id=fold_id, data_role=boundary.role,
        configuration_role=configuration_role,
        configuration_sha256=configuration_sha256,
        metrics=MappingProxyType(metrics),
        causal_checks=MappingProxyType(causal_checks),
        trades=tuple(trades), evaluation_sha256=sha256_payload(body),
    )


def _select_directional_reversal_path(
    fold_id: str,
    evaluations: Mapping[str, RoleEvaluation],
    spec: ScientificScoutSpec,
) -> FoldSelection:
    layout = selection_layout_for_hash(spec.selection_rule_sha256)
    roles = tuple(layout["roles"])
    primary_roles = tuple(layout["primary_roles"])
    control_roles = tuple(layout["control_roles"])
    required_roles = set(layout["required_feasible_roles"])
    preferred = tuple(layout["preferred_order"])
    if set(evaluations) != set(roles):
        raise ScientificScoutError(
            "directional selection requires all five registered roles"
        )
    if any(
        row.data_role != "validation_oos" or row.fold_id != fold_id
        for row in evaluations.values()
    ):
        raise ScientificScoutError(
            "selection may inspect validation_oos from one fold only"
        )
    feasible = {
        role: float(row.metrics["shadow_net_broker_points"])
        for role, row in evaluations.items()
        if row.feasible
        and isinstance(row.metrics.get("shadow_net_broker_points"), (int, float))
        and not isinstance(row.metrics.get("shadow_net_broker_points"), bool)
        and math.isfinite(float(row.metrics["shadow_net_broker_points"]))
    }
    primary = {role: feasible[role] for role in primary_roles if role in feasible}
    required_feasible = required_roles.issubset(feasible)
    selected_role: str | None = None
    plateau: tuple[str, ...] = ()
    basis = "required_directional_role_not_evaluable"
    if required_feasible and primary:
        best = max(primary.values())
        plateau = tuple(
            role
            for role in preferred
            if role in primary
            and primary[role] >= best - spec.plateau_tolerance_broker_points
        )
        selected_role = plateau[0]
        basis = (
            "base_preferred_validation_shadow_plateau"
            if selected_role == "short_reversal_base"
            else "best_feasible_validation_shadow_plateau"
        )
    elif required_feasible:
        basis = "no_feasible_short_reversal"
    selected_utility = primary.get(selected_role) if selected_role else None
    long_control = feasible.get("long_reversal_control")
    continuation_control = feasible.get("short_continuation_control")
    long_falsifies = bool(
        selected_utility is not None
        and long_control is not None
        and long_control
        >= selected_utility - spec.plateau_tolerance_broker_points
    )
    continuation_falsifies = bool(
        selected_utility is not None
        and continuation_control is not None
        and continuation_control
        >= selected_utility - spec.plateau_tolerance_broker_points
    )
    contrasts = {
        "short_reversal_shadow_net_broker_points": {
            role: primary.get(role) for role in primary_roles
        },
        "long_reversal_control_shadow_net_broker_points": long_control,
        "short_continuation_control_shadow_net_broker_points": (
            continuation_control
        ),
        "long_control_minus_selected": (
            None
            if selected_utility is None or long_control is None
            else long_control - selected_utility
        ),
        "continuation_control_minus_selected": (
            None
            if selected_utility is None or continuation_control is None
            else continuation_control - selected_utility
        ),
        "long_reversal_control_falsifies": long_falsifies,
        "short_continuation_control_falsifies": continuation_falsifies,
        "controls_selection_eligible": False,
        "required_roles_evaluable": required_feasible,
        "all_roles_evaluable": set(feasible) == set(roles),
        "unevaluable_roles": sorted(set(roles) - set(feasible)),
        "selection_source_role": "validation_oos",
        "selection_utility": "strict_observed_shadow_net_broker_points",
    }
    body = {
        "fold_id": fold_id,
        "selected_role": selected_role,
        "selected_configuration_sha256": (
            evaluations[selected_role].configuration_sha256
            if selected_role
            else None
        ),
        "selection_basis": basis,
        "plateau_roles": list(plateau),
        "falsifier_triggered": long_falsifies or continuation_falsifies,
        "validation_contrasts": contrasts,
    }
    return FoldSelection(
        fold_id=fold_id,
        selected_role=selected_role,
        selected_configuration_sha256=body["selected_configuration_sha256"],
        selection_basis=basis,
        plateau_roles=plateau,
        falsifier_triggered=long_falsifies or continuation_falsifies,
        validation_contrasts=MappingProxyType(contrasts),
        selection_sha256=sha256_payload(body),
    )


def select_continuation_path(
    fold_id: str, evaluations: Mapping[str, RoleEvaluation], spec: ScientificScoutSpec,
) -> FoldSelection:
    if spec.selection_rule_sha256 == DIRECTIONAL_SELECTION_RULE_SHA256:
        return _select_directional_reversal_path(fold_id, evaluations, spec)
    if set(evaluations) != set(BUNDLE_ROLES):
        raise ScientificScoutError("selection requires all five validation roles")
    if any(row.data_role != "validation_oos" or row.fold_id != fold_id for row in evaluations.values()):
        raise ScientificScoutError("selection may inspect validation_oos from one fold only")
    feasible = {
        role: row.utility for role, row in evaluations.items()
        if row.feasible and row.utility is not None
    }
    continuation = {role: feasible[role] for role in CONTINUATION_ROLES if role in feasible}
    selected_role: str | None = None
    plateau: tuple[str, ...] = ()
    basis = "no_feasible_continuation"
    all_roles_evaluable = set(feasible) == set(BUNDLE_ROLES)
    if not all_roles_evaluable:
        basis = "validation_role_not_evaluable"
    if all_roles_evaluable and continuation:
        best = max(continuation.values())
        plateau = tuple(role for role in PREFERRED_CONTINUATION_ORDER if role in continuation and continuation[role] >= best - spec.plateau_tolerance_broker_points)
        selected_role = plateau[0]
        basis = "base_preferred_validation_plateau" if selected_role == "continuation_base" else "best_feasible_validation_plateau"
    selected_utility = continuation.get(selected_role) if selected_role else None
    reversal = feasible.get("failed_break_reversal")
    ablation = feasible.get("compression_ablation")
    reversal_falsifies = bool(selected_utility is not None and reversal is not None and reversal > selected_utility + spec.plateau_tolerance_broker_points)
    ablation_falsifies = bool(selected_utility is not None and ablation is not None and ablation >= selected_utility - spec.plateau_tolerance_broker_points)
    contrasts = {
        "continuation_net_broker_points": {role: continuation.get(role) for role in CONTINUATION_ROLES},
        "reversal_net_broker_points": reversal,
        "ablation_net_broker_points": ablation,
        "reversal_minus_selected": None if selected_utility is None or reversal is None else reversal - selected_utility,
        "ablation_minus_selected": None if selected_utility is None or ablation is None else ablation - selected_utility,
        "reversal_falsifies": reversal_falsifies,
        "ablation_falsifies": ablation_falsifies,
        "falsifiers_selection_eligible": False,
        "all_roles_evaluable": all_roles_evaluable,
        "unevaluable_roles": sorted(set(BUNDLE_ROLES) - set(feasible)),
        "selection_source_role": "validation_oos",
    }
    body = {
        "fold_id": fold_id,
        "selected_role": selected_role,
        "selected_configuration_sha256": evaluations[selected_role].configuration_sha256 if selected_role else None,
        "selection_basis": basis,
        "plateau_roles": list(plateau),
        "falsifier_triggered": reversal_falsifies or ablation_falsifies,
        "validation_contrasts": contrasts,
    }
    return FoldSelection(
        fold_id=fold_id, selected_role=selected_role,
        selected_configuration_sha256=body["selected_configuration_sha256"],
        selection_basis=basis, plateau_roles=plateau,
        falsifier_triggered=reversal_falsifies or ablation_falsifies,
        validation_contrasts=MappingProxyType(contrasts),
        selection_sha256=sha256_payload(body),
    )


def _default_release_surface(
    selection_rule_sha256: str,
) -> tuple[
    Sequence[EventConfigurationLike],
    Callable[[BarArrays, EventConfigurationLike], CompressionEvaluationLike],
]:
    if selection_rule_sha256 == DIRECTIONAL_SELECTION_RULE_SHA256:
        from axiom_rift.v2.research.directional_reversal import (
            DIRECTIONAL_EVENT_CONFIGURATIONS,
            evaluate_directional_configuration,
        )

        return DIRECTIONAL_EVENT_CONFIGURATIONS, evaluate_directional_configuration
    from axiom_rift.v2.research.compression_release import EVENT_CONFIGURATIONS, evaluate_configuration
    return EVENT_CONFIGURATIONS, evaluate_configuration


def _config_identity(configuration: EventConfigurationLike) -> str:
    value = configuration.identity_sha256
    value = value() if callable(value) else value
    if not _is_sha256(value):
        raise ScientificScoutError("release configuration identity is invalid")
    return str(value)


def run_scientific_scout(
    spec: ScientificScoutSpec,
    folds: Sequence[ScientificFold],
    *,
    configurations: Sequence[EventConfigurationLike] | None = None,
    evaluator: Callable[[BarArrays, EventConfigurationLike], CompressionEvaluationLike] | None = None,
) -> ScientificScoutResult:
    """Run the bounded validation-selection-development path without I/O."""

    if configurations is None or evaluator is None:
        default_configs, default_evaluator = _default_release_surface(
            spec.selection_rule_sha256
        )
        configurations = default_configs if configurations is None else configurations
        evaluator = default_evaluator if evaluator is None else evaluator
    layout = selection_layout_for_hash(spec.selection_rule_sha256)
    role_names = tuple(layout["roles"])
    by_role = {configuration.role: configuration for configuration in configurations}
    if set(by_role) != set(role_names) or len(configurations) != len(role_names):
        raise ScientificScoutError("release surface must expose exactly five immutable roles")
    ordered_folds = tuple(sorted(folds, key=lambda row: row.window.development_id))
    if tuple(row.window.development_id for row in ordered_folds) != spec.anchors:
        raise ScientificScoutError("Scout inputs must contain the three anchors exactly once")
    validations: list[RoleEvaluation] = []
    selections: list[FoldSelection] = []
    developments: list[RoleEvaluation] = []
    path_hashes: dict[str, str] = {}
    for fold in ordered_folds:
        fold_id = fold.window.development_id
        assert_split_access("S", fold_id, "validation_oos")
        validation_start, validation_end = _role_indices(fold.bars.time, fold.window.validation_start, fold.window.validation_end)
        validation_bars = _slice_bars(fold.bars, validation_end)
        rows: dict[str, RoleEvaluation] = {}
        full_observations: dict[str, CompressionEvaluationLike] = {}
        for role in role_names:
            observed = evaluator(validation_bars, by_role[role])
            full_observed = evaluator(fold.bars, by_role[role])
            _validate_runtime_evaluation(observed, role=role, spec=spec)
            _validate_runtime_evaluation(full_observed, role=role, spec=spec)
            full_observations[role] = full_observed
            prefix_directions, prefix_scores, prefix_valid = _signal_arrays(
                observed, len(validation_bars)
            )
            full_directions, full_scores, full_valid = _signal_arrays(
                full_observed, len(fold.bars)
            )
            prefix_invariant = bool(
                np.array_equal(prefix_directions, full_directions[:validation_end])
                and np.array_equal(prefix_valid, full_valid[:validation_end])
                and np.array_equal(prefix_scores, full_scores[:validation_end])
            )
            rows[role] = evaluate_signal_role(
                fold_id=fold_id, bars=validation_bars,
                boundary=IndexBoundary("validation_oos", validation_start, validation_end),
                configuration_role=role,
                configuration_sha256=spec.bundle_role_hashes[role],
                evaluation=observed, spec=spec,
                prefix_invariant=prefix_invariant,
                non_allow_gaps=fold.non_allow_gaps,
            )
            validations.append(rows[role])
        selection = select_continuation_path(fold_id, rows, spec)
        selections.append(selection)
        if selection.selected_role is None or selection.falsifier_triggered:
            continue
        assert_split_access("S", fold_id, "development_cv")
        development_start, development_end = _role_indices(fold.bars.time, fold.window.development_start, fold.window.development_end)
        development_bars = _slice_bars(fold.bars, development_end)
        observed = evaluator(development_bars, by_role[selection.selected_role])
        _validate_runtime_evaluation(
            observed, role=selection.selected_role, spec=spec
        )
        development_directions, development_scores, development_valid = _signal_arrays(
            observed, len(development_bars)
        )
        full_directions, full_scores, full_valid = _signal_arrays(
            full_observations[selection.selected_role], len(fold.bars)
        )
        development_prefix_invariant = bool(
            np.array_equal(
                development_directions, full_directions[:development_end]
            )
            and np.array_equal(development_valid, full_valid[:development_end])
            and np.array_equal(development_scores, full_scores[:development_end])
        )
        development = evaluate_signal_role(
            fold_id=fold_id, bars=development_bars,
            boundary=IndexBoundary("development_cv", development_start, development_end),
            configuration_role=selection.selected_role,
            configuration_sha256=selection.selected_configuration_sha256 or "",
            evaluation=observed, spec=spec,
            prefix_invariant=development_prefix_invariant,
            non_allow_gaps=fold.non_allow_gaps,
        )
        developments.append(development)
        path_hashes[fold_id] = sha256_payload({
            "schema": "axiom_rift_v2_frozen_scientific_path_v1",
            "fold_id": fold_id,
            "selection_sha256": selection.selection_sha256,
            "selection_rule_sha256": spec.selection_rule_sha256,
            "configuration_role": selection.selected_role,
            "bundle_sha256": selection.selected_configuration_sha256,
            "release_configuration_sha256": _config_identity(by_role[selection.selected_role]),
            "source_data_role": "validation_oos",
            "evaluation_target_role": "development_cv",
        })
    new_hashes = tuple(
        sorted(spec.bundle_role_hashes[role] for role in role_names)
    )
    family_after = tuple(sorted(set(spec.family_configuration_hashes_before) | set(new_hashes)))
    global_after = tuple(sorted(set(spec.global_configuration_hashes_before) | set(new_hashes)))
    accounting = {
        "family_id": spec.family_id,
        "configuration_trials": len(new_hashes),
        "job_unique_configuration_count": len(new_hashes),
        "new_family_configuration_trials": len(
            set(new_hashes) - set(spec.family_configuration_hashes_before)
        ),
        "validation_evaluation_cells": len(validations),
        "local_calibration_trials": 0,
        "inner_selection_events": len(selections),
        "development_selected_paths": len(developments),
        "development_variant_selection": False,
        "family_trials_before": len(spec.family_configuration_hashes_before),
        "family_trials_cumulative": len(family_after),
        "global_trials_before": len(spec.global_configuration_hashes_before),
        "global_trials_cumulative": len(global_after),
        "configuration_hashes": list(new_hashes),
        "family_configuration_hashes_before": list(spec.family_configuration_hashes_before),
        "family_history_sha256_before": spec.family_history_sha256_before,
        "family_configuration_hashes_after": list(family_after),
        "family_history_sha256_after": trial_history_sha256(family_after),
        "global_configuration_hashes_before": list(spec.global_configuration_hashes_before),
        "global_history_sha256_before": spec.global_history_sha256_before,
        "global_configuration_hashes_after": list(global_after),
        "global_history_sha256_after": trial_history_sha256(global_after),
        "holdout_reveals": 0,
        "trial_accounting_complete": True,
    }
    all_development_trades = tuple(trade for row in developments for trade in row.trades)
    validation_unknown = sum(
        int(row.metrics["unknown_cost_observation_count"]) for row in validations
    )
    development_unknown = sum(
        int(row.metrics["unknown_cost_observation_count"]) for row in developments
    )
    unknown = validation_unknown + development_unknown
    net = None if unknown else sum(float(row.metrics["net_broker_points"] or 0.0) for row in developments)
    positive_net_fold_count = sum(
        row.metrics["net_broker_points"] is not None
        and float(row.metrics["net_broker_points"]) > 0.0
        for row in developments
    )
    evaluable_trade_count = sum(
        int(row.metrics["evaluable_trade_count"]) for row in developments
    )
    causal_floor = (
        spec.trade_implementation_key
        == CAUSAL_SPREAD_FLOOR_IMPLEMENTATION_KEY
    )
    shadow_evaluable_trade_count = (
        sum(
            int(row.metrics["shadow_evaluable_trade_count"])
            for row in developments
        )
        if causal_floor
        else 0
    )
    shadow_net = (
        sum(
            float(row.metrics["shadow_net_broker_points"])
            for row in developments
        )
        if causal_floor
        else None
    )
    shadow_positive_net_fold_count = (
        sum(
            float(row.metrics["shadow_net_broker_points"]) > 0.0
            for row in developments
        )
        if causal_floor
        else 0
    )
    metrics = {
        "per_fold": [dict(row.metrics) for row in developments],
        "entry_count": len(all_development_trades),
        "evaluable_trade_count": evaluable_trade_count,
        "unknown_cost_observation_count": unknown,
        "validation_unknown_cost_observation_count": validation_unknown,
        "development_unknown_cost_observation_count": development_unknown,
        "net_broker_points": net,
        "positive_net_fold_count": positive_net_fold_count,
        "after_cost_metric_state": (
            "causal_policy_evaluable"
            if causal_floor and unknown == 0
            else "observed"
            if unknown == 0
            else "not_evaluable"
        ),
        "sizing_mode": "fixed_lot",
    }
    if causal_floor:
        metrics.update(
            {
                "shadow_evaluable_trade_count": (
                    shadow_evaluable_trade_count
                ),
                "shadow_net_broker_points": shadow_net,
                "shadow_positive_net_fold_count": (
                    shadow_positive_net_fold_count
                ),
                "validation_zero_decision_spread_rejection_count": sum(
                    int(row.metrics["zero_decision_spread_rejection_count"])
                    for row in validations
                ),
                "development_zero_decision_spread_rejection_count": sum(
                    int(row.metrics["zero_decision_spread_rejection_count"])
                    for row in developments
                ),
                "validation_execution_spread_fallback_count": sum(
                    int(row.metrics["execution_spread_fallback_count"])
                    for row in validations
                ),
                "development_execution_spread_fallback_count": sum(
                    int(row.metrics["execution_spread_fallback_count"])
                    for row in developments
                ),
            }
        )
    validation_passed = len(selections) == 3 and all(row.selected_role and not row.falsifier_triggered for row in selections)
    causal_passed = all(all(value for key, value in row.causal_checks.items() if key != "development_variant_selection") for row in (*validations, *developments))
    observations = scientific_kpi_observations(
        metrics,
        causal_checks_passed=causal_passed,
        trade_implementation_key=spec.trade_implementation_key,
    )
    kpi_evaluation = interpret_kpis(
        "S", observations, spec.evaluation_profile
    )
    metrics["kpi_evaluation"] = kpi_evaluation.to_payload()
    hard_profile_passed = kpi_evaluation.route == "route_to_R"
    gate_passed = (
        validation_passed
        and len(developments) == 3
        and causal_passed
        and unknown == 0
        and hard_profile_passed
    )
    if kpi_evaluation.route == "repair_required":
        outcome = "repair_required"
    elif kpi_evaluation.route == "evidence_gap":
        outcome = "evidence_gap"
    elif gate_passed:
        outcome = "route_to_R"
    else:
        outcome = "scientific_reject"
    causal = {
        "all_validation_selection_source_only": True,
        "development_paths_frozen_before_evaluation": True,
        "development_variant_selection": False,
        "one_development_path_per_fold": len(developments) <= len(spec.anchors),
        "all_role_checks_passed": causal_passed,
        "hard_profile_passed": hard_profile_passed,
        "kpi_route": kpi_evaluation.route,
    }
    body = {
        "outcome": outcome, "gate_passed": gate_passed,
        "metrics": metrics, "causal_checks": causal,
        "validation_evaluations": [row.to_payload() for row in validations],
        "selections": [row.to_payload() for row in selections],
        "development_evaluations": [row.to_payload() for row in developments],
        "selected_path_hashes": path_hashes,
        "trial_accounting": accounting,
        "claim_ceiling": "diagnostic_observation",
        "mt5_executed": False, "economics_claim_allowed": False,
    }
    return ScientificScoutResult(
        outcome=outcome, gate_passed=gate_passed,
        metrics=MappingProxyType(metrics), causal_checks=MappingProxyType(causal),
        validation_evaluations=tuple(validations), selections=tuple(selections),
        development_evaluations=tuple(developments),
        selected_path_hashes=MappingProxyType(path_hashes),
        trial_accounting=MappingProxyType(accounting),
        result_sha256=sha256_payload(body),
    )


__all__ = [
    "ANCHORS", "BUNDLE_ROLES", "CONTINUATION_ROLES", "FALSIFIER_ROLES",
    "CAUSAL_SPREAD_FLOOR_IMPLEMENTATION_KEY",
    "DIRECTIONAL_BUNDLE_ROLES", "DIRECTIONAL_SELECTION_RULE_PAYLOAD",
    "DIRECTIONAL_SELECTION_RULE_SHA256",
    "LEGACY_TRADE_IMPLEMENTATION_KEY",
    "SCIENTIFIC_SELECTION_RULE_PAYLOAD", "SCIENTIFIC_SELECTION_RULE_SHA256",
    "FoldSelection", "RoleEvaluation", "ScientificFold", "ScientificScoutError",
    "ScientificScoutResult", "ScientificScoutSpec", "evaluate_signal_role",
    "run_scientific_scout", "select_continuation_path",
    "selection_layout_for_hash", "trial_history_sha256",
]
