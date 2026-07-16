"""One-bar causal quote-timing overlay for fixed residual continuation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.discovery import (
    SimulationResult,
    _time_ns,
    causal_effective_spread,
    completed_bar_execution_spreads,
    discovery_implementation_sha256,
    execution_pnl,
)
from axiom_rift.research.event_direction_meta_chassis import (
    SELECTION_TOTAL_EXPOSURES as PRIOR_SELECTION_TOTAL_EXPOSURES,
)
from axiom_rift.research.market_residual_event_chassis import (
    MarketResidualEventConfiguration,
    market_residual_event_chassis_implementation_sha256,
    market_residual_event_components,
    market_residual_event_configurations,
    market_residual_event_executable,
)


SELECTION_TOTAL_EXPOSURES = PRIOR_SELECTION_TOTAL_EXPOSURES + 1
SPREAD_REFERENCE_BARS = 288
SPREAD_LIMIT_MILLI = 1_000
DEFERRAL_BARS = 1
_FIVE_MINUTES_NS = 300_000_000_000
_PROFILES = ("immediate_control", "causal_one_bar_quote_deferral")
_THIS_FILE = Path(__file__).resolve()


def residual_quote_deferral_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _continuation_configuration() -> MarketResidualEventConfiguration:
    return next(
        configuration
        for configuration in market_residual_event_configurations()
        if configuration.profile == "market_residual_continuation"
    )


@dataclass(frozen=True, slots=True)
class ResidualQuoteDeferralConfiguration:
    profile: str

    def __post_init__(self) -> None:
        if self.profile not in _PROFILES:
            raise ValueError("residual quote-deferral profile is invalid")

    @property
    def configuration_id(self) -> str:
        return self.profile

    @property
    def holding_bars(self) -> int:
        return 6

    @property
    def signal_sign(self) -> int:
        return 1

    @property
    def residual_profile(self) -> str:
        return "fold_train_linear_market_residual"

    @property
    def execution_timing_policy(self) -> str:
        return (
            "immediate_next_open"
            if self.profile == "immediate_control"
            else "causal_prior_median_one_bar_deferral"
        )

    def semantic_parameters(self) -> dict[str, Any]:
        values = dict(_continuation_configuration().semantic_parameters())
        values.update(
            {
                "deferral_bars": (
                    0 if self.profile == "immediate_control" else DEFERRAL_BARS
                ),
                "execution_timing_policy": self.execution_timing_policy,
                "quote_reference_bars": SPREAD_REFERENCE_BARS,
                "spread_limit_milli": SPREAD_LIMIT_MILLI,
            }
        )
        return values


def residual_quote_deferral_configurations() -> tuple[
    ResidualQuoteDeferralConfiguration, ...
]:
    return tuple(ResidualQuoteDeferralConfiguration(profile) for profile in _PROFILES)


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.residual_quote_deferral_chassis.{name}@sha256:"
        f"{residual_quote_deferral_chassis_implementation_sha256()}"
    )


def residual_quote_deferral_baseline() -> ExecutableSpec:
    return market_residual_event_executable(_continuation_configuration())


def _timing_overlay() -> ComponentSpec:
    baseline_portfolio = next(
        component
        for component in market_residual_event_components(_continuation_configuration())
        if component.protocol.startswith("portfolio.")
    )
    return ComponentSpec(
        display_name="causal prior-median one-bar entry timing overlay",
        protocol="execution.causal_one_bar_quote_deferral_overlay.v1",
        implementation=_local("simulate_residual_quote_deferral"),
        spec={
            "decision_quote": "completed_decision_bar_spread_proxy",
            "deferral_bars": DEFERRAL_BARS,
            "deferred_entry_action": "enter_unconditionally_at_next_exact_bar_open",
            "execution_cost_proxies": {
                "entry": "entry_index_minus_1",
                "exit": "exit_index_minus_1",
            },
            "parameter_fields": ["execution_timing_policy"],
            "quote_reference": (
                "gap_reset_strictly_prior_288_completed_bar_median"
            ),
            "reference_unknown_action": "retain_immediate_entry",
            "spread_limit_milli": SPREAD_LIMIT_MILLI,
        },
        semantic_dependencies=(baseline_portfolio.identity,),
    )


def residual_quote_deferral_executable(
    configuration: ResidualQuoteDeferralConfiguration,
) -> ExecutableSpec:
    if configuration.profile == "immediate_control":
        return residual_quote_deferral_baseline()
    baseline = residual_quote_deferral_baseline()
    return ExecutableSpec(
        display_name="market residual continuation causal one-bar quote deferral",
        components=(*market_residual_event_components(_continuation_configuration()), _timing_overlay()),
        parameters=configuration.semantic_parameters(),
        data_contract=baseline.data_contract,
        split_contract=baseline.split_contract,
        clock_contract=(
            "clock:fpmarkets_m5_completed_decision_bar_one_bar_deferral_v1"
        ),
        cost_contract=(
            "cost:fpmarkets_completed_bar_spread_proxy_point_0_01_"
            "causal_zero_repair_one_bar_deferral_half_spread_stress_v1"
        ),
        engine_contract=(
            f"engine:residual_quote_deferral_v1:python{'.'.join(str(v) for v in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"chassis_{residual_quote_deferral_chassis_implementation_sha256()}:"
            f"residual_{market_residual_event_chassis_implementation_sha256()}:"
            f"shared_{discovery_implementation_sha256()}:"
            f"selection_{SELECTION_TOTAL_EXPOSURES}"
        ),
        source_contracts=baseline.source_contracts,
    )


def executable_configuration_map() -> dict[str, ResidualQuoteDeferralConfiguration]:
    return {
        residual_quote_deferral_executable(configuration).identity: configuration
        for configuration in residual_quote_deferral_configurations()
    }


def _spread_reference(spreads: np.ndarray, time_ns: np.ndarray) -> np.ndarray:
    if len(spreads) != len(time_ns):
        raise ValueError("spread reference arrays differ")
    segment = np.zeros(len(time_ns), dtype=np.int64)
    if len(time_ns) > 1:
        segment[1:] = np.cumsum(np.diff(time_ns) != _FIVE_MINUTES_NS)
    values = pd.Series(np.asarray(spreads, dtype=float))
    groups = pd.Series(segment)
    return values.groupby(groups, sort=False).transform(
        lambda part: part.shift(1).rolling(
            SPREAD_REFERENCE_BARS,
            min_periods=24,
        ).median()
    ).to_numpy(float)


def simulate_residual_quote_deferral(
    *,
    frame: pd.DataFrame,
    score: np.ndarray,
    volatility: np.ndarray,
    run: np.ndarray,
    threshold: float,
    configuration: ResidualQuoteDeferralConfiguration,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray | None = None,
) -> SimulationResult:
    if configuration.profile != "causal_one_bar_quote_deferral":
        raise ValueError("quote-deferral simulator requires the subject profile")
    time = pd.to_datetime(frame["time"], errors="raise")
    time_ns = _time_ns(frame)
    opens = pd.to_numeric(frame["open"], errors="raise").to_numpy(dtype=float)
    spreads = (
        causal_effective_spread(
            pd.to_numeric(frame["spread"], errors="raise").to_numpy(dtype=float),
            time_ns,
        )
        if effective_spread is None
        else np.asarray(effective_spread, dtype=float)
    )
    if len(spreads) != len(frame):
        raise ValueError("effective spread length differs from frame")
    reference = _spread_reference(spreads, time_ns)
    candidates = np.flatnonzero(
        ((time >= test_start) & (time <= test_end)).to_numpy()
        & np.isfinite(score)
    )
    records: list[dict[str, Any]] = []
    intents: list[tuple[Any, ...]] = []
    next_decision_index = -1
    unresolved = 0
    gap_excluded = 0
    causality_violations = 0
    for decision_index in candidates:
        if decision_index < next_decision_index or abs(score[decision_index]) < threshold:
            continue
        direction = int(np.sign(score[decision_index])) * configuration.signal_sign
        if direction == 0:
            continue
        scheduled_entry_index = decision_index + 1
        if scheduled_entry_index >= len(frame):
            continue
        decision_spread = spreads[decision_index]
        decision_reference = reference[decision_index]
        defer = bool(
            np.isfinite(decision_spread)
            and np.isfinite(decision_reference)
            and decision_spread * 1000
            > decision_reference * SPREAD_LIMIT_MILLI
        )
        entry_delay_bars = DEFERRAL_BARS if defer else 0
        entry_index = scheduled_entry_index + entry_delay_bars
        exit_index = entry_index + configuration.holding_bars
        if exit_index >= len(frame) or time.iloc[exit_index] > test_end:
            continue
        decision_bar_open_time = time.iloc[decision_index]
        decision_time = decision_bar_open_time + pd.Timedelta(minutes=5)
        scheduled_entry_time = time.iloc[scheduled_entry_index]
        entry_time = time.iloc[entry_index]
        exit_time = time.iloc[exit_index]
        continuous = (
            scheduled_entry_time == decision_time
            and (
                not defer
                or entry_time
                == scheduled_entry_time + pd.Timedelta(minutes=5)
            )
            and run[exit_index]
            >= configuration.holding_bars + 2 + entry_delay_bars
        )
        if not continuous:
            gap_excluded += 1
            intents.append(
                (decision_time, entry_time, exit_time, direction, "gap_excluded")
            )
            continue
        expected_entry_time = decision_time + pd.Timedelta(
            minutes=5 * entry_delay_bars
        )
        if entry_time != expected_entry_time:
            causality_violations += 1
            intents.append(
                (
                    decision_time,
                    entry_time,
                    exit_time,
                    direction,
                    "causality_violation",
                )
            )
            continue
        next_decision_index = exit_index
        execution_spreads = completed_bar_execution_spreads(
            spreads,
            entry_index=entry_index,
            exit_index=exit_index,
        )
        if not execution_spreads.costs_known:
            unresolved += 1
            intents.append(
                (decision_time, entry_time, exit_time, direction, "unknown_cost")
            )
            continue
        native, stress = execution_pnl(
            direction=direction,
            entry_bid=float(opens[entry_index]),
            exit_bid=float(opens[exit_index]),
            entry_spread_points=execution_spreads.entry_spread_points,
            exit_spread_points=execution_spreads.exit_spread_points,
        )
        entry_volatility = float(volatility[decision_index])
        regime = (
            "low"
            if entry_volatility <= regime_cutoffs[0]
            else "high"
            if entry_volatility >= regime_cutoffs[1]
            else "middle"
        )
        records.append(
            {
                "decision_bar_open_time": decision_bar_open_time,
                "decision_time": decision_time,
                "entry_delay_bars": entry_delay_bars,
                "entry_time": entry_time,
                "exit_time": exit_time,
                "direction": direction,
                "pnl": native,
                "stress_pnl": stress,
                "fold_id": fold_id,
                "regime": regime,
            }
        )
        status = (
            "executed_deferred"
            if defer
            else "executed_immediate_reference_unknown"
            if not np.isfinite(decision_reference)
            else "executed_immediate"
        )
        intents.append((decision_time, entry_time, exit_time, direction, status))
    trades = pd.DataFrame.from_records(records)
    if trades.empty:
        trades = pd.DataFrame(
            columns=(
                "decision_bar_open_time",
                "decision_time",
                "entry_delay_bars",
                "entry_time",
                "exit_time",
                "direction",
                "pnl",
                "stress_pnl",
                "fold_id",
                "regime",
            )
        )
    return SimulationResult(
        trades=trades,
        intent_rows=tuple(intents),
        unresolved_cost_signal_count=unresolved,
        gap_excluded_signal_count=gap_excluded,
        causality_violation_count=causality_violations,
    )


__all__ = [
    "DEFERRAL_BARS",
    "ResidualQuoteDeferralConfiguration",
    "SELECTION_TOTAL_EXPOSURES",
    "SPREAD_LIMIT_MILLI",
    "SPREAD_REFERENCE_BARS",
    "executable_configuration_map",
    "residual_quote_deferral_baseline",
    "residual_quote_deferral_chassis_implementation_sha256",
    "residual_quote_deferral_configurations",
    "residual_quote_deferral_executable",
    "simulate_residual_quote_deferral",
]
