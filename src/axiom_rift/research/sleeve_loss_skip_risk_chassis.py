"""Causal same-sleeve one-entry skip after a realized loss.

The policy is evaluated inside each sleeve's sequential signal loop.  It does
not post-filter a completed trade list: skipping an entry immediately frees
the slot, so the next bar can become eligible.  Only an accepted trade whose
exit is already realized can arm the one-entry skip state.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.discovery import (
    SimulationResult,
    _time_ns,
    causal_effective_spread,
    completed_bar_execution_spreads,
    completed_bar_spread_proxy_indices,
    empty_trade_frame,
    execution_pnl_breakdown,
)
from axiom_rift.research.positive_direction_sleeve_chassis import (
    PositiveDirectionSleeveConfiguration,
    positive_direction_sleeve_components,
    positive_direction_sleeve_executable,
)


UNRESTRICTED_CONTROL = "unrestricted_dual_positive_control"
SKIP_NEXT_AFTER_LOSS = "skip_next_same_sleeve_after_loss"
_POLICIES = (UNRESTRICTED_CONTROL, SKIP_NEXT_AFTER_LOSS)
_FIVE_MINUTES_NS = 5 * 60 * 1_000_000_000
_THIS_FILE = Path(__file__).resolve()


def sleeve_loss_skip_risk_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class SleeveLossSkipRiskConfiguration:
    risk_policy: str

    def __post_init__(self) -> None:
        if self.risk_policy not in _POLICIES:
            raise ValueError("sleeve loss-skip risk policy is invalid")

    @property
    def configuration_id(self) -> str:
        return self.risk_policy

    def semantic_parameters(self) -> dict[str, Any]:
        return {
            **PositiveDirectionSleeveConfiguration(
                "dual_positive_direction_slots"
            ).semantic_parameters(),
            "base_portfolio_profile": "dual_positive_direction_slots",
            "holding_bars_by_slot": {
                "regime_router": 12,
                "target_direction": 6,
            },
            "loss_definition": "accepted_native_net_pnl_below_zero",
            "risk_policy": self.risk_policy,
            "skip_count_per_trigger": 1,
            "state_partition": "fold_and_sleeve",
            "state_reset": "after_one_skipped_eligible_entry_or_fold_end",
            "state_source": "prior_accepted_same_sleeve_realized_exit_only",
        }


def sleeve_loss_skip_risk_configurations() -> tuple[
    SleeveLossSkipRiskConfiguration, ...
]:
    return tuple(SleeveLossSkipRiskConfiguration(value) for value in _POLICIES)


def _local(name: str) -> str:
    return (
        "axiom_rift.research.sleeve_loss_skip_risk_chassis."
        f"{name}@sha256:{sleeve_loss_skip_risk_chassis_implementation_sha256()}"
    )


def sleeve_loss_skip_risk_components() -> tuple[ComponentSpec, ...]:
    base = positive_direction_sleeve_components()
    policy = ComponentSpec(
        display_name="same-sleeve realized-loss one-entry skip risk",
        protocol="risk.same_sleeve_skip_next_after_realized_loss.v1",
        implementation=_local("simulate_sleeve_loss_skip_risk"),
        spec={
            "counterfactual_skipped_trade_outcome_access": "forbidden",
            "dynamic_sizing": False,
            "loss_definition": "accepted_native_net_pnl_below_zero",
            "parameter_fields": ["risk_policy"],
            "skip_count_per_trigger": 1,
            "state_partition": "fold_and_sleeve",
            "state_reset": "one_skipped_eligible_entry",
            "state_source": "prior_accepted_same_sleeve_realized_exit_only",
        },
        semantic_dependencies=(base[9].identity, base[15].identity),
    )
    portfolio = ComponentSpec(
        display_name="dual positive sleeves with causal loss skip overlay",
        protocol="portfolio.positive_direction_loss_skip_overlay.v1",
        implementation=_local("simulate_sleeve_loss_skip_risk"),
        spec={
            "base_portfolio_profile": "dual_positive_direction_slots",
            "parameter_fields": ["risk_policy"],
            "per_sleeve_lot": 1,
            "slots": ["regime_router", "target_direction"],
        },
        semantic_dependencies=(base[-1].identity, policy.identity),
    )
    return (*base, policy, portfolio)


def sleeve_loss_skip_risk_executable(
    configuration: SleeveLossSkipRiskConfiguration,
) -> ExecutableSpec:
    base = positive_direction_sleeve_executable(
        PositiveDirectionSleeveConfiguration("dual_positive_direction_slots")
    )
    if configuration.risk_policy == UNRESTRICTED_CONTROL:
        return base
    return ExecutableSpec(
        display_name="positive sleeves skip next same-sleeve entry after loss",
        components=sleeve_loss_skip_risk_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=base.data_contract,
        split_contract=base.split_contract,
        clock_contract=base.clock_contract,
        cost_contract=base.cost_contract,
        engine_contract=base.engine_contract,
    )


def sleeve_loss_skip_risk_baseline() -> ExecutableSpec:
    return sleeve_loss_skip_risk_executable(sleeve_loss_skip_risk_configurations()[0])


def executable_configuration_map() -> dict[str, SleeveLossSkipRiskConfiguration]:
    return {
        sleeve_loss_skip_risk_executable(value).identity: value
        for value in sleeve_loss_skip_risk_configurations()
    }


def _simulate_slot(
    *,
    frame: pd.DataFrame,
    score: np.ndarray,
    volatility: np.ndarray,
    run: np.ndarray,
    holding_bars: int,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray,
    slot: str,
    skip_after_loss: bool,
) -> SimulationResult:
    time = pd.to_datetime(frame["time"], errors="raise")
    time_ns = _time_ns(frame)
    opens = pd.to_numeric(frame["open"], errors="raise").to_numpy(dtype=float)
    spreads = np.asarray(effective_spread, dtype=float)
    values = np.asarray(score, dtype=float)
    volatility_values = np.asarray(volatility, dtype=float)
    run_values = np.asarray(run)
    if any(len(value) != len(frame) for value in (spreads, values, volatility_values, run_values)):
        raise ValueError("sleeve loss-skip input length differs from frame")
    candidates = np.flatnonzero(
        ((time >= test_start) & (time <= test_end)).to_numpy()
        & np.isfinite(values)
    )
    records: list[dict[str, Any]] = []
    intents: list[tuple[Any, ...]] = []
    next_decision_index = -1
    skip_next_eligible = False
    unresolved = 0
    gap_excluded = 0
    causality_violations = 0
    for decision_index in candidates:
        if decision_index < next_decision_index or abs(values[decision_index]) < 1.0:
            continue
        direction = int(np.sign(values[decision_index]))
        if direction == 0:
            continue
        entry_index = decision_index + 1
        exit_index = entry_index + holding_bars
        if exit_index >= len(frame) or time.iloc[exit_index] > test_end:
            continue
        decision_bar_open_time = time.iloc[decision_index]
        decision_time = decision_bar_open_time + pd.Timedelta(minutes=5)
        entry_time = time.iloc[entry_index]
        exit_time = time.iloc[exit_index]
        if (
            time_ns[entry_index] - time_ns[decision_index] != _FIVE_MINUTES_NS
            or run_values[exit_index] < holding_bars + 2
        ):
            gap_excluded += 1
            intents.append(
                (slot, decision_time, entry_time, exit_time, direction, "gap_excluded")
            )
            continue
        if decision_time != entry_time:
            causality_violations += 1
            intents.append(
                (
                    slot,
                    decision_time,
                    entry_time,
                    exit_time,
                    direction,
                    "causality_violation",
                )
            )
            continue
        if skip_after_loss and skip_next_eligible:
            intents.append(
                (
                    slot,
                    decision_time,
                    entry_time,
                    exit_time,
                    direction,
                    "risk_policy_skipped",
                )
            )
            skip_next_eligible = False
            continue
        entry_proxy_index = completed_bar_spread_proxy_indices(
            int(entry_index), spread_count=len(spreads)
        )
        assert isinstance(entry_proxy_index, int)
        next_decision_index = exit_index
        execution_spreads = completed_bar_execution_spreads(
            spreads, entry_index=entry_index, exit_index=exit_index
        )
        if not execution_spreads.costs_known:
            unresolved += 1
            intents.append(
                (slot, decision_time, entry_time, exit_time, direction, "unknown_cost")
            )
            continue
        pnl = execution_pnl_breakdown(
            direction=direction,
            entry_bid=float(opens[entry_index]),
            exit_bid=float(opens[exit_index]),
            entry_spread_points=execution_spreads.entry_spread_points,
            exit_spread_points=execution_spreads.exit_spread_points,
        )
        regime = (
            "low"
            if volatility_values[decision_index] <= regime_cutoffs[0]
            else "high"
            if volatility_values[decision_index] >= regime_cutoffs[1]
            else "middle"
        )
        records.append(
            {
                "decision_bar_index": int(decision_index),
                "decision_bar_open_time": decision_bar_open_time,
                "decision_time": decision_time,
                "entry_bar_index": int(entry_index),
                "entry_bid": float(opens[entry_index]),
                "entry_spread_cost": (
                    execution_spreads.entry_spread_points * 0.01
                ),
                "entry_spread_source_bar_index": (
                    execution_spreads.entry_proxy_index
                ),
                "entry_spread_source_bar_open_time": time.iloc[
                    execution_spreads.entry_proxy_index
                ],
                "entry_time": entry_time,
                "exit_bar_index": int(exit_index),
                "exit_bid": float(opens[exit_index]),
                "exit_spread_cost": (
                    execution_spreads.exit_spread_points * 0.01
                ),
                "exit_spread_source_bar_index": (
                    execution_spreads.exit_proxy_index
                ),
                "exit_spread_source_bar_open_time": time.iloc[
                    execution_spreads.exit_proxy_index
                ],
                "exit_time": exit_time,
                "direction": direction,
                "gross_pnl": pnl.gross_pnl,
                "native_cost": pnl.native_cost,
                "stress_cost": pnl.stress_cost,
                "pnl": pnl.native_net_pnl,
                "stress_pnl": pnl.stress_net_pnl,
                "fold_id": fold_id,
                "regime": regime,
                "slot": slot,
            }
        )
        intents.append(
            (slot, decision_time, entry_time, exit_time, direction, "executed")
        )
        if skip_after_loss and pnl.native_net_pnl < 0:
            skip_next_eligible = True
    trades = pd.DataFrame.from_records(records)
    if trades.empty:
        trades = empty_trade_frame().assign(slot=pd.Series(dtype=object))
    return SimulationResult(
        trades=trades,
        intent_rows=tuple(intents),
        unresolved_cost_signal_count=unresolved,
        gap_excluded_signal_count=gap_excluded,
        causality_violation_count=causality_violations,
    )


def simulate_sleeve_loss_skip_risk(
    *,
    frame: pd.DataFrame,
    score: np.ndarray,
    volatility: np.ndarray,
    run: np.ndarray,
    threshold: float,
    configuration: SleeveLossSkipRiskConfiguration,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray | None = None,
) -> SimulationResult:
    del threshold
    values = np.asarray(score, dtype=float)
    if values.ndim != 2 or values.shape != (len(frame), 2):
        raise ValueError("sleeve loss-skip score matrix is invalid")
    spreads = (
        causal_effective_spread(
            frame["spread"].to_numpy(float), _time_ns(frame)
        )
        if effective_spread is None
        else np.asarray(effective_spread, dtype=float)
    )
    skip = configuration.risk_policy == SKIP_NEXT_AFTER_LOSS
    slots = (
        _simulate_slot(
            frame=frame,
            score=values[:, 0],
            volatility=volatility,
            run=run,
            holding_bars=12,
            test_start=test_start,
            test_end=test_end,
            fold_id=fold_id,
            regime_cutoffs=regime_cutoffs,
            effective_spread=spreads,
            slot="regime_router",
            skip_after_loss=skip,
        ),
        _simulate_slot(
            frame=frame,
            score=values[:, 1],
            volatility=volatility,
            run=run,
            holding_bars=6,
            test_start=test_start,
            test_end=test_end,
            fold_id=fold_id,
            regime_cutoffs=regime_cutoffs,
            effective_spread=spreads,
            slot="target_direction",
            skip_after_loss=skip,
        ),
    )
    trades = (
        pd.concat([item.trades for item in slots], ignore_index=True)
        .sort_values(["decision_time", "slot"], kind="stable")
        .reset_index(drop=True)
    )
    return SimulationResult(
        trades=trades,
        intent_rows=tuple(row for item in slots for row in item.intent_rows),
        unresolved_cost_signal_count=sum(
            item.unresolved_cost_signal_count for item in slots
        ),
        gap_excluded_signal_count=sum(item.gap_excluded_signal_count for item in slots),
        causality_violation_count=sum(item.causality_violation_count for item in slots),
    )


__all__ = [
    "SKIP_NEXT_AFTER_LOSS",
    "UNRESTRICTED_CONTROL",
    "SleeveLossSkipRiskConfiguration",
    "executable_configuration_map",
    "simulate_sleeve_loss_skip_risk",
    "sleeve_loss_skip_risk_baseline",
    "sleeve_loss_skip_risk_chassis_implementation_sha256",
    "sleeve_loss_skip_risk_components",
    "sleeve_loss_skip_risk_configurations",
    "sleeve_loss_skip_risk_executable",
]
