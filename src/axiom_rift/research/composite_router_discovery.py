


"""Causal fold-trained residual-sleeve router for US100 M5 discovery.

The module owns one immutable twelve-Executable surface.  It reuses the
already-proved trade, lifecycle, cost, fold, and data-boundary primitives from
``research.discovery`` while binding those exact dependency bytes and this
module's feature/statistical bytes into every Executable identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import ceil, sqrt
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import scipy
from scipy.stats import beta

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec, canonical_digest
from axiom_rift.research import data as data_module
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    _causal_prefix_mismatch_count,
    DiscoveryBoundaryError,
    _consecutive_run,
    _daily_series,
    _fold_payloads,
    _micropoints,
    _monthly_realized_exit_drawdown,
    _profit_factor,
    _time_ns,
    _validate_engine_environment,
    _validate_fold_payloads,
    _validate_production_data,
    causal_effective_spread,
    discovery_implementation_sha256,
    simulate_fixed_hold,
)
from axiom_rift.research.volatility_discovery import (
    compute_volatility_transition_score,
    volatility_implementation_sha256,
)
from axiom_rift.research.volume_price_discovery import (
    compute_volume_price_pressure_score,
    volume_price_implementation_sha256,
)
from axiom_rift.research.reversion_discovery import (
    compute_overextension_score,
    reversion_implementation_sha256,
)


SELECTOR_QUANTILE_BP = 9_500
SELECTION_BOOTSTRAP_SAMPLES = 41_999
SELECTION_BLOCK_LENGTHS = (5, 10, 20)
SELECTION_TOTAL_EXPOSURES = 210
SELECTION_SEED = 612_337_279
SELECTION_MONTE_CARLO_CONFIDENCE_PPM = 990_000

_PROFILE_ROUTES: dict[str, dict[str, str]] = {
    "three_sleeve_router": {
        "low": "volume",
        "middle": "reversion",
        "high": "volatility",
    },
    "volume_reversion_ablation": {
        "low": "volume",
        "middle": "reversion",
        "high": "no_trade",
    },
    "volume_volatility_ablation": {
        "low": "volume",
        "middle": "no_trade",
        "high": "volatility",
    },
}
_COMPOSITE_ROUTER_FILE = Path(__file__).resolve()


class CompositeRouterBoundaryError(DiscoveryBoundaryError):
    """Raised before unregistered composite-routing semantics enter evaluation."""


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def composite_router_implementation_sha256() -> str:
    return _file_sha256(_COMPOSITE_ROUTER_FILE)


def trend_dependency_sha256() -> str:
    return discovery_implementation_sha256()


def loader_implementation_sha256() -> str:
    return _file_sha256(Path(data_module.__file__).resolve())


def volatility_dependency_sha256() -> str:
    return volatility_implementation_sha256()


def volume_price_dependency_sha256() -> str:
    return volume_price_implementation_sha256()


def reversion_dependency_sha256() -> str:
    return reversion_implementation_sha256()


@dataclass(frozen=True, slots=True)
class CompositeRouterConfiguration:
    profile: str
    route_sign: int
    holding_bars: int

    def __post_init__(self) -> None:
        if self.profile not in _PROFILE_ROUTES:
            raise ValueError("composite router profile is not registered")
        if self.route_sign not in {-1, 1}:
            raise ValueError("route_sign must be -1 or 1")
        if self.holding_bars not in {12, 48}:
            raise ValueError("holding_bars is not registered")

    @property
    def signal_sign(self) -> int:
        """Adapter required by the proven fixed-hold simulator."""

        return self.route_sign

    @property
    def routes(self) -> dict[str, str]:
        return dict(_PROFILE_ROUTES[self.profile])

    @property
    def rewarm_bars(self) -> int:
        return 145

    @property
    def configuration_id(self) -> str:
        sign = "inverted" if self.route_sign == -1 else "routed"
        return f"{self.profile}-{sign}-h{self.holding_bars}"

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            "direction_policy": "route_sign_times_selected_sleeve_score_sign",
            "holding_bars": self.holding_bars,
            "route_sign": self.route_sign,
            "routes": self.routes,
            "selected_entry_rule": "absolute_normalized_score_at_least_one",
            "sleeve_selector_quantile_bp": SELECTOR_QUANTILE_BP,
            "threshold_quantile_bp": SELECTOR_QUANTILE_BP,
        }


def composite_router_configurations() -> tuple[CompositeRouterConfiguration, ...]:
    return tuple(
        CompositeRouterConfiguration(profile, route_sign, holding_bars)
        for profile in (
            "three_sleeve_router",
            "volume_reversion_ablation",
            "volume_volatility_ablation",
        )
        for route_sign in (-1, 1)
        for holding_bars in (12, 48)
    )


def _local_implementation(function_name: str) -> str:
    return (
        f"axiom_rift.research.composite_router_discovery.{function_name}@sha256:"
        f"{composite_router_implementation_sha256()}"
    )


def _dependency_implementation(function_name: str) -> str:
    return (
        f"axiom_rift.research.discovery.{function_name}@sha256:"
        f"{trend_dependency_sha256()}"
    )




def composite_router_components() -> tuple[ComponentSpec, ...]:
    return (
        ComponentSpec(
            display_name="completed-bar volume-price body pressure sleeve",
            protocol="feature.completed_bar_volume_body_pressure_12_96.v1",
            implementation=(
                "axiom_rift.research.volume_price_discovery."
                "compute_volume_price_pressure_score@sha256:"
                f"{volume_price_dependency_sha256()}"
            ),
            spec={
                "direction": "follow_body_pressure_sign",
                "profile": "body_pressure_12_96",
                "role": "low_realized_volatility_sleeve",
            },
        ),
        ComponentSpec(
            display_name="completed-bar slow96 overextension continuation sleeve",
            protocol="feature.completed_bar_slow96_overextension_continuation.v1",
            implementation=(
                "axiom_rift.research.reversion_discovery."
                "compute_overextension_score@sha256:"
                f"{reversion_dependency_sha256()}"
            ),
            spec={
                "direction": "continuation_of_overextension_sign",
                "profile": "slow_96",
                "role": "middle_realized_volatility_sleeve",
            },
        ),
        ComponentSpec(
            display_name="completed-bar rv24-120 volatility breakout sleeve",
            protocol="feature.completed_bar_rv24_120_breakout.v1",
            implementation=(
                "axiom_rift.research.volatility_discovery."
                "compute_volatility_transition_score@sha256:"
                f"{volatility_dependency_sha256()}"
            ),
            spec={
                "direction": "breakout_transition_sign",
                "profile": "rv_ratio_24_120",
                "role": "high_realized_volatility_sleeve",
            },
        ),
        ComponentSpec(
            display_name="fold-train volatility-tertile normalized sleeve router",
            protocol="synthesis.fold_train_tertile_residual_router.v1",
            implementation=_local_implementation("route_composite_score"),
            spec={
                "entry_rule": "selected_sleeve_absolute_normalized_score_at_least_one",
                "evidence_execution": "new_raw_data_load_no_prior_result_cache",
                "profiles": {
                    name: dict(routes) for name, routes in _PROFILE_ROUTES.items()
                },
                "regime_cutoffs": "fold_train_realized_volatility_tertiles",
                "sleeve_normalization": "fold_train_absolute_95th_percentile",
                "test_action": "freeze_cutoffs_and_three_sleeve_thresholds",
            },
        ),
        ComponentSpec(
            display_name="completed-bar next-open routed or inverted entry",
            protocol="trade.completed_bar_next_open_composite_router.v1",
            implementation=_dependency_implementation("simulate_fixed_hold"),
            spec={
                "decision_time": "bar_open_plus_5m",
                "entry_time": "decision_time_at_next_exact_bar_open",
                "direction": "route_sign_times_selected_sleeve_score_sign",
                "parameter_fields": ["route_sign"],
            },
        ),
        ComponentSpec(
            display_name="fixed-hold nonoverlap lifecycle",
            protocol="lifecycle.fixed_hold_no_overlap.v2",
            implementation=_dependency_implementation("simulate_fixed_hold"),
            spec={
                "entry_overlap": "reject_while_position_slot_is_occupied",
                "exit_surface": "exact_bar_open_after_holding_bars",
                "gap_action": "exclude_path",
                "unknown_cost_action": "reserve_slot_and_mark_not_evaluable",
                "parameter_fields": ["holding_bars"],
            },
        ),
        ComponentSpec(
            display_name="FPMarkets bid-bar spread execution",
            protocol="execution.fpmarkets_bid_bar_spread.v2",
            implementation=_dependency_implementation("execution_pnl"),
            spec={
                "bar_quote_basis": "bid_ohlc_with_spread_points",
                "point": "0.01",
                "zero_spread": "lag1_positive_median_window288_min24_gap_reset",
                "stress": "half_effective_spread_each_side",
            },
        ),
        ComponentSpec(
            display_name="fixed one-lot single-sleeve risk",
            protocol="risk.fixed_one_lot.v1",
            implementation=_dependency_implementation("simulate_fixed_hold"),
            spec={"dynamic_sizing": False, "lot": 1, "positions_per_sleeve": 1},
        ),
    )


def composite_router_executable(configuration: CompositeRouterConfiguration) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=f"composite residual router {configuration.configuration_id}",
        components=composite_router_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=(
            f"split:{ROLLING_SPLIT_SHA256}:rolling_windows_9_observed_development"
        ),
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v2",
        cost_contract=(
            "cost:bid_bar_spread_point_0_01_zero_lag1_positive_median_"
            "window288_min24_gap_reset_half_spread_stress_v2"
        ),
        engine_contract=(
            "engine:composite_router_discovery_v1:python3_13_9:numpy2_3_4:"
            "pandas2_3_3:scipy1_16_3:"
            f"composite_router_sha256_{composite_router_implementation_sha256()}:"
            f"trend_dependency_sha256_{trend_dependency_sha256()}:"
            f"loader_sha256_{loader_implementation_sha256()}:"
            f"volume_price_dependency_sha256_{volume_price_dependency_sha256()}:"
            f"reversion_dependency_sha256_{reversion_dependency_sha256()}:"
            f"volatility_dependency_sha256_{volatility_dependency_sha256()}:"
            f"selector_{SELECTOR_QUANTILE_BP}_higher:regime_higher:"
            f"bootstrap_{SELECTION_BOOTSTRAP_SAMPLES}:blocks_5_10_20:"
            f"mc_upper_{SELECTION_MONTE_CARLO_CONFIDENCE_PPM}:"
            f"bonferroni_{SELECTION_TOTAL_EXPOSURES}:seed_{SELECTION_SEED}"
        ),
    )


def composite_router_executable_configuration_map() -> dict[str, CompositeRouterConfiguration]:
    return {
        composite_router_executable(configuration).identity: configuration
        for configuration in composite_router_configurations()
    }


def executable_configuration_map() -> dict[str, CompositeRouterConfiguration]:
    return composite_router_executable_configuration_map()


@dataclass(slots=True)
class _RouterFeatures:
    volume: np.ndarray
    reversion: np.ndarray
    volatility_sleeve: np.ndarray
    realized_volatility: np.ndarray
    run: np.ndarray


def compute_composite_sleeve_scores(frame: pd.DataFrame) -> _RouterFeatures:
    """Compute three independent completed-bar sleeve scores from raw data."""

    volume, volume_regime, volume_run = compute_volume_price_pressure_score(
        frame, "body_pressure_12_96"
    )
    reversion, reversion_regime, reversion_run = compute_overextension_score(
        frame, 96
    )
    volatility_sleeve, volatility_regime, volatility_run = (
        compute_volatility_transition_score(frame, "rv_ratio_24_120")
    )
    if not (
        np.array_equal(volume_run, reversion_run)
        and np.array_equal(volume_run, volatility_run)
    ):
        raise CompositeRouterBoundaryError("sleeve gap runs differ")
    reversion_regime = reversion_regime.copy()
    reversion_regime[reversion_run < 49] = np.nan
    for name, candidate in (
        ("volume", volume_regime),
        ("reversion", reversion_regime),
    ):
        if not np.allclose(
            candidate,
            volatility_regime,
            rtol=0.0,
            atol=0.0,
            equal_nan=True,
        ):
            raise CompositeRouterBoundaryError(
                f"{name} realized-volatility surface differs"
            )
    return _RouterFeatures(
        volume=volume,
        reversion=reversion,
        volatility_sleeve=volatility_sleeve,
        realized_volatility=volatility_regime,
        run=volatility_run,
    )


def calibrate_router(
    features: _RouterFeatures,
    train_mask: np.ndarray,
) -> tuple[tuple[float, float], dict[str, float]]:
    """Freeze train-only regime cutoffs and one abs-95 threshold per sleeve."""

    eligible = (
        train_mask
        & np.isfinite(features.realized_volatility)
        & (features.run >= 145)
    )
    train_volatility = features.realized_volatility[eligible]
    if len(train_volatility) < 1000:
        raise CompositeRouterBoundaryError("router regime calibration is too small")
    cutoffs = (
        float(np.quantile(train_volatility, 1 / 3, method="higher")),
        float(np.quantile(train_volatility, 2 / 3, method="higher")),
    )
    thresholds = {
        "volume": calibrate_selector(features.volume, train_mask),
        "reversion": calibrate_selector(features.reversion, train_mask),
        "volatility": calibrate_selector(features.volatility_sleeve, train_mask),
    }
    if any(not np.isfinite(value) or value <= 0 for value in thresholds.values()):
        raise CompositeRouterBoundaryError("router sleeve threshold is not positive")
    return cutoffs, thresholds


def route_composite_score(
    features: _RouterFeatures,
    *,
    profile: str,
    volatility_cutoffs: tuple[float, float],
    sleeve_thresholds: Mapping[str, float],
) -> np.ndarray:
    """Select one normalized sleeve by frozen realized-volatility regime."""

    if profile not in _PROFILE_ROUTES:
        raise ValueError("composite router profile is not registered")
    if set(sleeve_thresholds) != {"volume", "reversion", "volatility"}:
        raise ValueError("router sleeve thresholds are incomplete")
    low, high = volatility_cutoffs
    if not (np.isfinite(low) and np.isfinite(high) and low <= high):
        raise ValueError("router volatility cutoffs are invalid")
    normalized = {
        "volume": features.volume / float(sleeve_thresholds["volume"]),
        "reversion": features.reversion / float(sleeve_thresholds["reversion"]),
        "volatility": (
            features.volatility_sleeve / float(sleeve_thresholds["volatility"])
        ),
    }
    realized = features.realized_volatility
    regimes = {
        "low": np.isfinite(realized) & (realized <= low),
        "middle": np.isfinite(realized) & (realized > low) & (realized < high),
        "high": np.isfinite(realized) & (realized >= high),
    }
    routed = np.full(len(realized), np.nan)
    for regime, sleeve in _PROFILE_ROUTES[profile].items():
        if sleeve == "no_trade":
            continue
        candidate = normalized[sleeve]
        selected = (
            regimes[regime]
            & np.isfinite(candidate)
            & (np.abs(candidate) >= 1.0)
        )
        routed[selected] = candidate[selected]
    routed[features.run < 145] = np.nan
    return routed





def calibrate_selector(score: np.ndarray, train_mask: np.ndarray) -> float:
    values = np.abs(score[train_mask & np.isfinite(score)])
    if len(values) < 1000:
        raise ValueError("selector calibration has fewer than 1000 observations")
    return float(
        np.quantile(values, SELECTOR_QUANTILE_BP / 10_000, method="higher")
    )


@dataclass(slots=True)
class _ConfigurationResult:
    configuration: CompositeRouterConfiguration
    executable_id: str
    metrics: dict[str, int]
    fold_metrics: list[dict[str, int | str]]
    regime_metrics: list[dict[str, int | str]]
    session_metrics: list[dict[str, int | str]]
    direction_metrics: list[dict[str, int | str]]
    daily_pnl: pd.Series


def _evaluate_configuration(
    *,
    frame: pd.DataFrame,
    folds: Sequence[Mapping[str, Any]],
    configuration: CompositeRouterConfiguration,
    effective_spread: np.ndarray,
    features: _RouterFeatures | None = None,
    prefix_features_by_end: Mapping[int, _RouterFeatures] | None = None,
) -> _ConfigurationResult:
    features = (
        compute_composite_sleeve_scores(frame) if features is None else features
    )
    volatility = features.realized_volatility
    run = features.run
    time = pd.to_datetime(frame["time"], errors="raise")
    simulations: list[Any] = []
    fold_metrics: list[dict[str, int | str]] = []
    eligible_parts: list[pd.DatetimeIndex] = []
    append_mismatches = 0
    prefix_mismatches = 0
    for fold in folds:
        train = fold["train_is"]
        test = fold["test_oos"]
        train_mask = (
            (time >= pd.Timestamp(train["start"]))
            & (time <= pd.Timestamp(train["end"]))
        ).to_numpy()
        cutoffs, sleeve_thresholds = calibrate_router(features, train_mask)
        routed_score = route_composite_score(
            features,
            profile=configuration.profile,
            volatility_cutoffs=cutoffs,
            sleeve_thresholds=sleeve_thresholds,
        )
        simulation = simulate_fixed_hold(
            frame=frame,
            score=routed_score,
            volatility=volatility,
            run=run,
            threshold=1.0,
            configuration=configuration,  # type: ignore[arg-type]
            test_start=pd.Timestamp(test["start"]),
            test_end=pd.Timestamp(test["end"]),
            fold_id=str(fold["fold_id"]),
            regime_cutoffs=cutoffs,
            effective_spread=effective_spread,
        )
        simulations.append(simulation)
        pnl = simulation.trades["pnl"].to_numpy(dtype=float)
        fold_metrics.append(
            {
                "fold_id": str(fold["fold_id"]),
                "net_profit_micropoints": _micropoints(float(pnl.sum())),
                "profit_factor_milli": _profit_factor(pnl),
                "stress_net_profit_micropoints": _micropoints(
                    float(simulation.trades["stress_pnl"].sum())
                ),
                "trade_count": int(len(simulation.trades)),
                "unresolved_cost_signal_count": simulation.unresolved_cost_signal_count,
            }
        )
        eligible_parts.append(
            pd.DatetimeIndex(
                time[
                    (time >= pd.Timestamp(test["start"]))
                    & (time <= pd.Timestamp(test["end"]))
                ]
            ).normalize().unique()
        )
        prefix_end = int(time.searchsorted(pd.Timestamp(test["end"]), side="right"))
        prefix_frame = frame.iloc[:prefix_end]
        prefix_features = (
            prefix_features_by_end[prefix_end]
            if prefix_features_by_end is not None
            and prefix_end in prefix_features_by_end
            else compute_composite_sleeve_scores(prefix_frame)
        )
        prefix_routed_score = route_composite_score(
            prefix_features,
            profile=configuration.profile,
            volatility_cutoffs=cutoffs,
            sleeve_thresholds=sleeve_thresholds,
        )
        prefix_spread = causal_effective_spread(
            pd.to_numeric(prefix_frame["spread"], errors="raise").to_numpy(dtype=float),
            _time_ns(prefix_frame),
        )
        prefix_mismatches += _causal_prefix_mismatch_count(
            full_surfaces=(
                ("volume", features.volume),
                ("reversion", features.reversion),
                ("volatility_sleeve", features.volatility_sleeve),
                ("realized_volatility", features.realized_volatility),
                ("run", features.run),
                ("routed_score", routed_score),
                ("effective_spread", effective_spread),
            ),
            prefix_surfaces=(
                ("volume", prefix_features.volume),
                ("reversion", prefix_features.reversion),
                ("volatility_sleeve", prefix_features.volatility_sleeve),
                (
                    "realized_volatility",
                    prefix_features.realized_volatility,
                ),
                ("run", prefix_features.run),
                ("routed_score", prefix_routed_score),
                ("effective_spread", prefix_spread),
            ),
            compared_row_count=prefix_end,
        )
        prefix_simulation = simulate_fixed_hold(
            frame=prefix_frame,
            score=prefix_routed_score,
            volatility=prefix_features.realized_volatility,
            run=prefix_features.run,
            threshold=1.0,
            configuration=configuration,  # type: ignore[arg-type]
            test_start=pd.Timestamp(test["start"]),
            test_end=pd.Timestamp(test["end"]),
            fold_id=str(fold["fold_id"]),
            regime_cutoffs=cutoffs,
            effective_spread=prefix_spread,
        )
        left, right = simulation.intent_rows, prefix_simulation.intent_rows
        append_mismatches += abs(len(left) - len(right)) + sum(
            one != two for one, two in zip(left, right, strict=False)
        )

    trades = pd.concat([item.trades for item in simulations], ignore_index=True)
    eligible_days = pd.DatetimeIndex(
        sorted(set().union(*(set(value) for value in eligible_parts)))
    )
    daily_pnl = _daily_series(trades, eligible_days, "pnl")
    daily_entries = (
        pd.Series(0, index=eligible_days, dtype=int)
        if trades.empty
        else trades.assign(
            day=pd.to_datetime(trades["decision_time"]).dt.normalize()
        ).groupby("day", sort=True).size().reindex(eligible_days, fill_value=0).astype(int)
    )
    net = float(trades["pnl"].sum()) if not trades.empty else 0.0
    stress = float(trades["stress_pnl"].sum()) if not trades.empty else 0.0
    drawdown, drawdown_share = _monthly_realized_exit_drawdown(trades)
    positive_daily = daily_pnl[daily_pnl > 0].sort_values(ascending=False)
    gross_positive = float(positive_daily.sum())
    top5_share = (
        0
        if gross_positive <= 0
        else min(1_000_000, int(round(1_000_000 * positive_daily.head(5).sum() / gross_positive)))
    )
    regime_metrics: list[dict[str, int | str]] = []
    for regime in ("low", "middle", "high"):
        selected = trades[trades["regime"] == regime]
        by_fold = (
            selected.groupby("fold_id", sort=True)["pnl"].sum()
            if not selected.empty
            else pd.Series(dtype=float)
        )
        regime_metrics.append(
            {
                "evaluable_fold_count": int(len(by_fold)),
                "regime": regime,
                "net_profit_micropoints": _micropoints(float(selected["pnl"].sum())),
                "trade_count": int(len(selected)),
                "winning_fold_count": int((by_fold > 0).sum()),
            }
        )
    hours = (
        pd.to_datetime(trades["entry_time"]).dt.hour
        if not trades.empty
        else pd.Series(dtype=int)
    )
    labels = (
        pd.Series(
            np.select(
                [hours.between(1, 7), hours.between(8, 14), hours.between(15, 22)],
                ["broker_01_07", "broker_08_14", "broker_15_22"],
                default="broker_23_00",
            ),
            index=trades.index,
        )
        if not trades.empty
        else pd.Series(dtype=object)
    )
    session_metrics: list[dict[str, int | str]] = []
    for session in ("broker_01_07", "broker_08_14", "broker_15_22", "broker_23_00"):
        selected = trades[labels == session] if not trades.empty else trades
        session_metrics.append(
            {
                "session": session,
                "net_profit_micropoints": _micropoints(float(selected["pnl"].sum())),
                "trade_count": int(len(selected)),
            }
        )
    direction_metrics: list[dict[str, int | str]] = []
    for direction, name in ((1, "long"), (-1, "short")):
        selected = trades[trades["direction"] == direction]
        direction_metrics.append(
            {
                "direction": name,
                "net_profit_micropoints": _micropoints(float(selected["pnl"].sum())),
                "trade_count": int(len(selected)),
            }
        )
    fold_pf = sorted(int(item["profit_factor_milli"]) for item in fold_metrics)
    unresolved = sum(item.unresolved_cost_signal_count for item in simulations)
    metrics = {
        "append_invariance_mismatch_count": append_mismatches,
        "causality_violation_count": sum(item.causality_violation_count for item in simulations),
        "daily_entries_max_milli": 0 if daily_entries.empty else int(daily_entries.max()) * 1000,
        "daily_entries_median_milli": 0 if daily_entries.empty else int(round(1000 * float(daily_entries.median()))),
        "daily_entries_p10_milli": 0 if daily_entries.empty else int(round(1000 * float(np.quantile(daily_entries, 0.10, method="lower")))),
        "daily_entries_p90_milli": 0 if daily_entries.empty else int(round(1000 * float(np.quantile(daily_entries, 0.90, method="higher")))),
        "eligible_day_count": int(len(eligible_days)),
        "entries_per_day_milli": 0 if not len(eligible_days) else int(round(1000 * len(trades) / len(eligible_days))),
        "evaluable_folds": sum(int(item["trade_count"]) > 0 for item in fold_metrics),
        "gap_excluded_signal_count": sum(item.gap_excluded_signal_count for item in simulations),
        "median_fold_profit_factor_milli": fold_pf[len(fold_pf) // 2] if fold_pf else 0,
        "monthly_realized_exit_drawdown_micropoints": _micropoints(drawdown),
        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": drawdown_share,
        "net_profit_micropoints": _micropoints(net),
        "nonfinite_metric_count": 0,
        "positive_regime_count": sum(int(item["net_profit_micropoints"]) > 0 for item in regime_metrics),
        "prefix_invariance_mismatch_count": prefix_mismatches,
        "selection_aware_pvalue_ppm": 1_000_000,
        "stress_net_profit_micropoints": _micropoints(stress),
        "supported_positive_regime_count": sum(
            int(item["net_profit_micropoints"]) > 0
            and int(item["trade_count"]) >= 30
            and int(item["evaluable_fold_count"]) >= 5
            and int(item["winning_fold_count"]) >= 3
            and 2 * int(item["winning_fold_count"]) > int(item["evaluable_fold_count"])
            for item in regime_metrics
        ),
        "top5_profit_day_share_ppm": top5_share,
        "trade_count": int(len(trades)),
        "unknown_cost_unresolved_signal_count": unresolved,
        "winning_fold_count": sum(int(item["net_profit_micropoints"]) > 0 for item in fold_metrics),
        "zero_entry_day_rate_ppm": 0 if daily_entries.empty else int(round(1_000_000 * int((daily_entries == 0).sum()) / len(daily_entries))),
    }
    return _ConfigurationResult(
        configuration,
        composite_router_executable(configuration).identity,
        metrics,
        fold_metrics,
        regime_metrics,
        session_metrics,
        direction_metrics,
        daily_pnl,
    )


def _overlapping_block_sums(values: np.ndarray, length: int) -> np.ndarray:
    cumulative = np.concatenate(([0.0], np.cumsum(values, dtype=float)))
    return cumulative[length:] - cumulative[:-length]


def _adjusted_bootstrap_upper_pvalue(values: np.ndarray, *, seed_label: str) -> int:
    sample = np.asarray(values, dtype=float)
    if len(sample) < 30 or np.any(~np.isfinite(sample)):
        raise CompositeRouterBoundaryError("bootstrap series is invalid or too short")
    standard = float(sample.std(ddof=1))
    if standard <= 0 or float(sample.mean()) <= 0:
        return 1_000_000
    observed = float(sample.mean() * sqrt(len(sample)) / standard)
    centered = sample - sample.mean()
    squares = centered * centered
    worst = 0.0
    for length in SELECTION_BLOCK_LENGTHS:
        seed = sha256(f"{SELECTION_SEED}:{seed_label}:{length}".encode("ascii")).digest()
        rng = np.random.default_rng(int.from_bytes(seed[:8], "big"))
        full_count, remainder = divmod(len(centered), length)
        sums = _overlapping_block_sums(centered, length)
        square_sums = _overlapping_block_sums(squares, length)
        partial_sums = None if remainder == 0 else _overlapping_block_sums(centered, remainder)
        partial_squares = None if remainder == 0 else _overlapping_block_sums(squares, remainder)
        exceedances = generated = 0
        while generated < SELECTION_BOOTSTRAP_SAMPLES:
            count = min(256, SELECTION_BOOTSTRAP_SAMPLES - generated)
            starts = rng.integers(0, len(sums), size=(count, full_count))
            draw_sum = sums[starts].sum(axis=1)
            draw_square = square_sums[starts].sum(axis=1)
            if partial_sums is not None and partial_squares is not None:
                partial_starts = rng.integers(0, len(partial_sums), size=count)
                draw_sum += partial_sums[partial_starts]
                draw_square += partial_squares[partial_starts]
            variance = np.maximum(0.0, (draw_square - draw_sum * draw_sum / len(centered)) / (len(centered) - 1))
            statistics = np.divide(
                draw_sum / len(centered) * sqrt(len(centered)),
                np.sqrt(variance),
                out=np.zeros(count),
                where=variance > 0,
            )
            exceedances += int((statistics >= observed).sum())
            generated += count
        point = (1 + exceedances) / (SELECTION_BOOTSTRAP_SAMPLES + 1)
        upper = 1.0 if exceedances >= SELECTION_BOOTSTRAP_SAMPLES else float(
            beta.ppf(
                SELECTION_MONTE_CARLO_CONFIDENCE_PPM / 1_000_000,
                exceedances + 1,
                SELECTION_BOOTSTRAP_SAMPLES - exceedances,
            )
        )
        worst = max(worst, min(1.0, max(point, upper) * SELECTION_TOTAL_EXPOSURES))
    return min(1_000_000, int(ceil(1_000_000 * worst)))


def _matched_result(
    results: Sequence[_ConfigurationResult],
    *,
    profile: str,
    signal_sign: int,
    holding_bars: int,
) -> _ConfigurationResult:
    matches = [
        item for item in results
        if item.configuration.profile == profile
        and item.configuration.signal_sign == signal_sign
        and item.configuration.holding_bars == holding_bars
    ]
    if len(matches) != 1:
        raise CompositeRouterBoundaryError("registered control match is not unique")
    return matches[0]


def _paired_pvalue(subject: _ConfigurationResult, control: _ConfigurationResult, role: str) -> int:
    if not subject.daily_pnl.index.equals(control.daily_pnl.index):
        raise CompositeRouterBoundaryError("paired controls have different eligible days")
    return _adjusted_bootstrap_upper_pvalue(
        subject.daily_pnl.to_numpy(dtype=float) - control.daily_pnl.to_numpy(dtype=float),
        seed_label=f"control:{role}:{subject.executable_id}:{control.executable_id}",
    )


def _populate_pvalues_and_controls(results: Sequence[_ConfigurationResult]) -> None:
    for subject in results:
        subject.metrics["selection_aware_pvalue_ppm"] = _adjusted_bootstrap_upper_pvalue(
            subject.daily_pnl.to_numpy(dtype=float),
            seed_label=f"selection:{subject.executable_id}",
        )
        opposite = _matched_result(
            results,
            profile=subject.configuration.profile,
            signal_sign=-subject.configuration.signal_sign,
            holding_bars=subject.configuration.holding_bars,
        )
        profile_controls = [
            _matched_result(
                results,
                profile=profile,
                signal_sign=subject.configuration.signal_sign,
                holding_bars=subject.configuration.holding_bars,
            )
            for profile in _PROFILE_ROUTES
            if profile != subject.configuration.profile
        ]
        subject.metrics["opposite_sign_worst_delta_net_profit_micropoints"] = (
            subject.metrics["net_profit_micropoints"] - opposite.metrics["net_profit_micropoints"]
        )
        subject.metrics["opposite_sign_pvalue_upper_ppm"] = _paired_pvalue(subject, opposite, "opposite_sign")
        subject.metrics["feature_control_worst_delta_net_profit_micropoints"] = min(
            subject.metrics["net_profit_micropoints"] - item.metrics["net_profit_micropoints"]
            for item in profile_controls
        )
        subject.metrics["feature_control_worst_pvalue_upper_ppm"] = max(
            _paired_pvalue(subject, item, "profile") for item in profile_controls
        )
        if any(type(value) is not int for value in subject.metrics.values()):
            raise CompositeRouterBoundaryError("scientific metrics are not fixed-point integers")


def _selection_method() -> dict[str, Any]:
    return {
        "bootstrap_samples": SELECTION_BOOTSTRAP_SAMPLES,
        "block_days": list(SELECTION_BLOCK_LENGTHS),
        "method": "centered_non_circular_moving_block_studentized_one_sided_then_bonferroni",
        "monte_carlo_upper_confidence_ppm": SELECTION_MONTE_CARLO_CONFIDENCE_PPM,
        "multiple_block_rule": "maximum_adjusted_pvalue",
        "paired_control_rule": "same_eligible_decision_day_intersection_union_worst_control",
        "seed": SELECTION_SEED,
        "seed_derivation": "sha256_base_seed_label_block_length_first_u64",
        "total_exposures": SELECTION_TOTAL_EXPOSURES,
    }


def _claim_limits() -> list[str]:
    return [
        "discovery_only",
        "daily_pnl_is_attributed_to_decision_day",
        "monthly_drawdown_is_exit_realized_not_mark_to_market",
        "monthly_drawdown_share_gate_is_for_sparse_composite_router_surfaces_only",
        "router_has_no_broker_session_cash_session_or_runtime_authority_claim",
        "shared_in_memory_feature_arrays_are_not_prior_result_cache_reuse",
        "regime_support_requires_30_trades_5_folds_3_winning_folds",
        "regime_support_requires_strict_majority_winning_evaluable_folds",
        "session_bins_are_broker_clock_descriptions_only",
        "controls_are_registered_executables_in_the_same_batch",
    ]


def _compute_registered_composite_router_surface(repository_root: str | Path) -> dict[str, Any]:
    if not isinstance(repository_root, (str, Path)):
        raise CompositeRouterBoundaryError("composite_router surface requires a repository path")
    _validate_engine_environment()
    data = load_observed_development(Path(repository_root).resolve())
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    effective_spread = causal_effective_spread(
        pd.to_numeric(data.frame["spread"], errors="raise").to_numpy(dtype=float),
        _time_ns(data.frame),
    )
    features = compute_composite_sleeve_scores(data.frame)
    frame_time = pd.to_datetime(data.frame["time"], errors="raise")
    prefix_features_by_end: dict[int, _RouterFeatures] = {}
    for fold in folds:
        prefix_end = int(
            frame_time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]), side="right")
        )
        prefix_features_by_end[prefix_end] = compute_composite_sleeve_scores(
            data.frame.iloc[:prefix_end]
        )
    results = [
        _evaluate_configuration(
            frame=data.frame,
            folds=folds,
            configuration=configuration,
            effective_spread=effective_spread,
            features=features,
            prefix_features_by_end=prefix_features_by_end,
        )
        for configuration in composite_router_configurations()
    ]
    _populate_pvalues_and_controls(results)
    surface: dict[str, Any] = {
        "claim_limits": _claim_limits(),
        "dataset_sha256": DATASET_SHA256,
        "discovery_implementation_sha256": composite_router_implementation_sha256(),
        "engine_environment": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "python": ".".join(str(value) for value in sys.version_info[:3]),
            "scipy": scipy.__version__,
        },
        "evaluations": [
            {
                "direction_metrics": item.direction_metrics,
                "evaluable": all(
                    item.metrics[name] == 0
                    for name in (
                        "unknown_cost_unresolved_signal_count",
                        "causality_violation_count",
                        "nonfinite_metric_count",
                        "prefix_invariance_mismatch_count",
                        "append_invariance_mismatch_count",
                    )
                ),
                "fold_metrics": item.fold_metrics,
                "metrics": dict(sorted(item.metrics.items())),
                "regime_metrics": item.regime_metrics,
                "session_metrics": item.session_metrics,
                "subject_configuration_id": item.configuration.configuration_id,
                "subject_executable_id": item.executable_id,
            }
            for item in results
        ],
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "reversion_dependency_sha256": reversion_dependency_sha256(),
        "schema": "composite_router_surface.v1",
        "selection_context": [
            {
                "configuration_id": item.configuration.configuration_id,
                "executable_id": item.executable_id,
                "net_profit_micropoints": item.metrics["net_profit_micropoints"],
                "selection_aware_pvalue_ppm": item.metrics["selection_aware_pvalue_ppm"],
            }
            for item in results
        ],
        "selection_method": _selection_method(),
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "trend_dependency_sha256": trend_dependency_sha256(),
        "volatility_dependency_sha256": volatility_dependency_sha256(),
        "volume_price_dependency_sha256": volume_price_dependency_sha256(),
    }
    canonical_bytes(surface)
    return surface


def project_composite_router_evaluation(
    surface: Mapping[str, Any],
    *,
    job_execution: Mapping[str, str],
    subject_executable_id: str,
    surface_artifact_hash: str,
    surface_manifest_hash: str,
) -> dict[str, Any]:
    for name, digest in (
        ("surface artifact", surface_artifact_hash),
        ("surface manifest", surface_manifest_hash),
    ):
        if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise CompositeRouterBoundaryError(f"{name} hash is invalid")
    if not isinstance(job_execution, Mapping) or set(job_execution) != {
        "identity", "job_hash", "job_id", "job_permit_id", "start_record_id"
    }:
        raise CompositeRouterBoundaryError("Job execution binding is invalid")
    payload = {name: job_execution[name] for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")}
    if job_execution["identity"] != canonical_digest(domain="running-job-execution", payload=payload):
        raise CompositeRouterBoundaryError("Job execution identity is invalid")
    value = dict(surface)
    if sha256(canonical_bytes(value)).hexdigest() != surface_artifact_hash:
        raise CompositeRouterBoundaryError("surface bytes differ from their artifact hash")
    expected_fields = {
        "claim_limits", "dataset_sha256", "discovery_implementation_sha256",
        "engine_environment", "evaluations", "loader_implementation_sha256",
        "material_identity", "reversion_dependency_sha256", "schema",
        "selection_context", "selection_method",
        "session_semantics", "split_artifact_sha256", "trend_dependency_sha256",
        "volatility_dependency_sha256",
        "volume_price_dependency_sha256",
    }
    if set(value) != expected_fields or value.get("schema") != "composite_router_surface.v1":
        raise CompositeRouterBoundaryError("composite_router surface schema is invalid")
    expected = composite_router_executable_configuration_map()
    evaluations = value.get("evaluations")
    if not isinstance(evaluations, list) or len(evaluations) != len(expected):
        raise CompositeRouterBoundaryError("composite_router surface evaluation count is invalid")
    by_identity = {item.get("subject_executable_id"): item for item in evaluations if isinstance(item, Mapping)}
    if len(by_identity) != len(evaluations) or set(by_identity) != set(expected) or subject_executable_id not in expected:
        raise CompositeRouterBoundaryError("composite_router surface subjects differ from registration")
    for identity, configuration in expected.items():
        if by_identity[identity].get("subject_configuration_id") != configuration.configuration_id:
            raise CompositeRouterBoundaryError("composite_router surface configuration binding differs")
    evaluation = {
        **dict(by_identity[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "composite_router_evaluation.v1",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(evaluation)
    return evaluation


__all__ = [
    "DATASET_SHA256", "OBSERVED_MATERIAL_ID", "ROLLING_SPLIT_SHA256",
    "CompositeRouterBoundaryError", "CompositeRouterConfiguration", "SELECTOR_QUANTILE_BP",
    "SELECTION_BLOCK_LENGTHS", "SELECTION_BOOTSTRAP_SAMPLES",
    "SELECTION_MONTE_CARLO_CONFIDENCE_PPM", "SELECTION_SEED",
    "SELECTION_TOTAL_EXPOSURES", "_compute_registered_composite_router_surface",
    "calibrate_router", "calibrate_selector", "compute_composite_sleeve_scores",
    "executable_configuration_map",
    "loader_implementation_sha256", "project_composite_router_evaluation",
    "composite_router_components", "composite_router_configurations", "composite_router_executable",
    "composite_router_executable_configuration_map", "composite_router_implementation_sha256",
    "reversion_dependency_sha256", "trend_dependency_sha256",
    "volatility_dependency_sha256", "volume_price_dependency_sha256",
    "route_composite_score",
]
