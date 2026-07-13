"""Causal US100-US500 residual-event architecture with fixed short holding."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.us500_market_coherence_chassis import (
    SELECTION_TOTAL_EXPOSURES as PRIOR_TOTAL_EXPOSURES,
    US500_RAW_SHA256,
    frontier_executable,
)
from axiom_rift.research.us500_source import us500_source_contract


SELECTION_TOTAL_EXPOSURES = PRIOR_TOTAL_EXPOSURES + 3
_PROFILES = (
    "target_only_mean_reversion_control",
    "market_residual_mean_reversion",
    "market_residual_continuation",
)
_THIS_FILE = Path(__file__).resolve()


def market_residual_event_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class MarketResidualFit:
    alpha: float
    beta: float
    target_center: float
    target_scale: float
    residual_center: float
    residual_scale: float


@dataclass(frozen=True, slots=True)
class MarketResidualEventConfiguration:
    profile: str

    def __post_init__(self) -> None:
        if self.profile not in _PROFILES:
            raise ValueError("market residual event profile is invalid")

    @property
    def configuration_id(self) -> str:
        return self.profile

    @property
    def holding_bars(self) -> int:
        return 6

    @property
    def signal_sign(self) -> int:
        return 1 if self.profile == "market_residual_continuation" else -1

    @property
    def residual_profile(self) -> str:
        return (
            "target_only_completed_return"
            if self.profile == "target_only_mean_reversion_control"
            else "fold_train_linear_market_residual"
        )

    @property
    def trade_policy(self) -> str:
        if self.profile == "target_only_mean_reversion_control":
            return "mean_reversion"
        return (
            "residual_continuation"
            if self.signal_sign == 1
            else "residual_mean_reversion"
        )

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "beta_fit": (
                "fold_train_ols_with_intercept"
                if self.profile == "target_only_mean_reversion_control"
                else "fold_train_ols_with_intercept_residual_active"
            ),
            "holding_bars": self.holding_bars,
            "lookback_bars": 12,
            "residual_profile": self.residual_profile,
            "risk_policy": "fixed_one_lot_no_stop",
            "selector_quantile_bp": 9000,
            "trade_policy": self.trade_policy,
        }


def market_residual_event_configurations() -> tuple[
    MarketResidualEventConfiguration, ...
]:
    return tuple(MarketResidualEventConfiguration(profile) for profile in _PROFILES)


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.market_residual_event_chassis.{name}@sha256:"
        f"{market_residual_event_chassis_implementation_sha256()}"
    )


def _robust_location_scale(values: np.ndarray) -> tuple[float, float]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if len(finite) < 100:
        raise ValueError("market residual fit requires at least 100 finite observations")
    center = float(np.median(finite))
    scale = float(1.4826 * np.median(np.abs(finite - center)))
    if not np.isfinite(scale) or scale <= 0.0:
        scale = float(np.std(finite))
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("market residual fit scale is degenerate")
    return center, scale


def fit_market_residual(
    target_returns: np.ndarray,
    source_returns: np.ndarray,
    train_mask: np.ndarray,
) -> MarketResidualFit:
    target = np.asarray(target_returns, dtype=float)
    source = np.asarray(source_returns, dtype=float)
    mask = np.asarray(train_mask, dtype=bool)
    if target.shape != source.shape or target.shape != mask.shape:
        raise ValueError("market residual fit arrays differ")
    valid = mask & np.isfinite(target) & np.isfinite(source)
    if int(valid.sum()) < 100:
        raise ValueError("market residual fit has insufficient train observations")
    design = np.column_stack((np.ones(int(valid.sum())), source[valid]))
    alpha, beta = np.linalg.lstsq(design, target[valid], rcond=None)[0]
    residual = target[valid] - float(alpha) - float(beta) * source[valid]
    target_center, target_scale = _robust_location_scale(target[valid])
    residual_center, residual_scale = _robust_location_scale(residual)
    return MarketResidualFit(
        alpha=float(alpha),
        beta=float(beta),
        target_center=target_center,
        target_scale=target_scale,
        residual_center=residual_center,
        residual_scale=residual_scale,
    )


def project_market_residual_score(
    target_returns: np.ndarray,
    source_returns: np.ndarray,
    fit: MarketResidualFit,
    *,
    residual_profile: str,
) -> np.ndarray:
    target = np.asarray(target_returns, dtype=float)
    source = np.asarray(source_returns, dtype=float)
    if target.shape != source.shape:
        raise ValueError("market residual projection arrays differ")
    if residual_profile == "target_only_completed_return":
        score = (target - fit.target_center) / fit.target_scale
    elif residual_profile == "fold_train_linear_market_residual":
        residual = target - fit.alpha - fit.beta * source
        score = (residual - fit.residual_center) / fit.residual_scale
        score[~np.isfinite(source)] = np.nan
    else:
        raise ValueError("market residual projection profile is invalid")
    score[~np.isfinite(target)] = np.nan
    return score


def market_residual_event_components(
    configuration: MarketResidualEventConfiguration | None = None,
) -> tuple[ComponentSpec, ...]:
    contract = us500_source_contract()
    residual_subject = (
        configuration is not None
        and configuration.profile != "target_only_mean_reversion_control"
    )
    source = ComponentSpec(
        display_name="exact completed FPMarkets US500 broad-market source",
        protocol="external_source.fpmarkets_us500_m5.v3",
        implementation=_local("project_market_residual_score"),
        spec={
            "availability": "completed_bar_only",
            "clock_identity": contract.clock_identity,
            "exact_join": "timestamp_inner_no_fill_no_asof",
            "field_identity": contract.field_identity,
            "mapping_identity": contract.mapping_identity,
            "missing_action": "fail_closed",
            "raw_sha256": US500_RAW_SHA256,
            "schema_identity": contract.schema_identity,
            "source_contract_id": contract.source_contract_id,
        },
        semantic_dependencies=(contract.source_contract_id,),
    )
    feature = ComponentSpec(
        display_name="fixed completed-return market residual event score",
        protocol="feature.us100_us500_fold_train_market_residual.v1",
        implementation=_local("project_market_residual_score"),
        spec={
            "lookback_bars": 12,
            "parameter_fields": ["lookback_bars", "residual_profile"],
            "profiles": [
                "target_only_completed_return",
                "fold_train_linear_market_residual",
            ],
            "standardization": "fold_train_median_mad_then_population_std_fallback",
        },
        semantic_dependencies=(source.identity,),
    )
    label = ComponentSpec(
        display_name="fixed six-bar terminal US100 return sign",
        protocol="label.us100_terminal_return_sign_6.v1",
        implementation=_local("fit_market_residual"),
        spec={
            "decision_time": "completed_bar_plus_5m",
            "horizon_bars": 6,
            "target": "future_US100_bid_open_return_sign",
        },
        semantic_dependencies=(feature.identity,),
    )
    model = ComponentSpec(
        display_name="fold-train linear broad-market beta",
        protocol="model.fold_train_us500_beta_ols.v1",
        implementation=_local("fit_market_residual"),
        spec={
            "fit_role": "train_is_only",
            "intercept": True,
            "parameter_fields": ["beta_fit"],
            "solver": "least_squares_no_grid",
        },
        semantic_dependencies=(feature.identity, label.identity),
    )
    selector = ComponentSpec(
        display_name="fold-train top-decile absolute residual event selector",
        protocol="selector.fold_train_abs_quantile.v3",
        implementation=_local("project_market_residual_score"),
        spec={
            "calibration_role": "train_is_only",
            "minimum_train_observations": 1000,
            "parameter_fields": ["selector_quantile_bp"],
            "quantile_basis_points": 9000,
            "quantile_method": "higher",
        },
        semantic_dependencies=(model.identity,),
    )
    trade = ComponentSpec(
        display_name="residual event continuation or mean-reversion entry",
        protocol="trade.market_residual_event_direction.v1",
        implementation=_local("project_market_residual_score"),
        spec={
            "decision_time": "bar_open_plus_5m",
            "entry_time": "next_exact_bar_open",
            "parameter_fields": ["trade_policy"],
            "policies": (
                ["mean_reversion", "continuation"]
                if not residual_subject
                else ["residual_mean_reversion", "residual_continuation"]
            ),
        },
        semantic_dependencies=(selector.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="fixed six-bar nonoverlap residual event lifecycle",
        protocol="lifecycle.fixed_hold_no_overlap.v9",
        implementation=_local("project_market_residual_score"),
        spec={
            "entry_overlap": "reject_while_position_slot_is_occupied",
            "exit_surface": "exact_bar_open_after_6_bars",
            "gap_action": "exclude_path",
            "parameter_fields": ["holding_bars"],
        },
        semantic_dependencies=(trade.identity,),
    )
    risk = ComponentSpec(
        display_name="fixed one-lot residual event risk",
        protocol="risk.fixed_one_lot.v2",
        implementation=_local("project_market_residual_score"),
        spec={
            "dynamic_sizing": False,
            "lot": 1,
            "parameter_fields": ["risk_policy"],
            "stop": None,
        },
        semantic_dependencies=(lifecycle.identity,),
    )
    execution = ComponentSpec(
        display_name="FPMarkets next-open bid execution with native and stress costs",
        protocol="execution.fpmarkets_bid_open_spread.v1",
        implementation=_local("project_market_residual_score"),
        spec={
            "point": "0.01",
            "stress": "half_effective_spread_each_side",
            "unknown_cost_action": "not_evaluable",
        },
        semantic_dependencies=(risk.identity,),
    )
    portfolio = ComponentSpec(
        display_name="single fixed-lot residual event sleeve",
        protocol="portfolio.single_market_residual_event_sleeve.v1",
        implementation=_local("project_market_residual_score"),
        spec={
            "activity_quota": False,
            "maximum_positions": 1,
            **(
                {}
                if not residual_subject
                else {
                    "parameter_fields": ["residual_profile"],
                    "profile_binding": "market_residual_event",
                }
            ),
            "selection_profiles": 3,
        },
        semantic_dependencies=(execution.identity,),
    )
    return (
        source,
        feature,
        label,
        model,
        selector,
        trade,
        lifecycle,
        risk,
        execution,
        portfolio,
    )


def market_residual_event_executable(
    configuration: MarketResidualEventConfiguration,
) -> ExecutableSpec:
    boundary = frontier_executable()
    implementation = market_residual_event_chassis_implementation_sha256()
    return ExecutableSpec(
        display_name=f"market residual event {configuration.profile}",
        components=market_residual_event_components(configuration),
        parameters=configuration.semantic_parameters(),
        data_contract=boundary.data_contract,
        split_contract=boundary.split_contract,
        clock_contract=boundary.clock_contract,
        cost_contract=boundary.cost_contract,
        engine_contract=(
            "engine:market_residual_event_v1:python3.13.9:"
            f"chassis_{implementation}:selection_{SELECTION_TOTAL_EXPOSURES}"
        ),
        source_contracts=(us500_source_contract().source_contract_id,),
    )


def market_residual_event_baseline() -> ExecutableSpec:
    return market_residual_event_executable(market_residual_event_configurations()[0])


__all__ = [
    "MarketResidualEventConfiguration",
    "MarketResidualFit",
    "SELECTION_TOTAL_EXPOSURES",
    "fit_market_residual",
    "market_residual_event_baseline",
    "market_residual_event_chassis_implementation_sha256",
    "market_residual_event_components",
    "market_residual_event_configurations",
    "market_residual_event_executable",
    "project_market_residual_score",
]
