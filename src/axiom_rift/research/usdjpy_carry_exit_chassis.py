"""USDJPY carry-unwind lifecycle invalidation over the STU-0092 frontier."""

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
    execution_pnl,
    simulate_fixed_hold,
)
from axiom_rift.research.external_observed_development import (
    USDJPY_OBSERVED_DEVELOPMENT_SPEC,
    external_observed_development_loader_implementation_sha256,
)
from axiom_rift.research.high_vol_target_reversal_chassis import (
    high_vol_target_reversal_configurations,
    high_vol_target_reversal_executable,
    simulate_high_vol_target_reversal,
)
from axiom_rift.research.residual_quote_deferral_chassis import (
    SELECTION_TOTAL_EXPOSURES as PRIOR_SELECTION_TOTAL_EXPOSURES,
)
from axiom_rift.research.usdjpy_source import (
    USDJPY_HISTORICAL_SNAPSHOT_SHA256,
    usdjpy_source_contract,
)


SELECTION_TOTAL_EXPOSURES = PRIOR_SELECTION_TOTAL_EXPOSURES + 1
USDJPY_RAW_SHA256 = USDJPY_HISTORICAL_SNAPSHOT_SHA256
CARRY_STATE_BARS = 288
TARGET_HOLDING_BARS = 6
_FIVE_MINUTES_NS = 300_000_000_000
_PROFILES = (
    "stu0092_fixed_lifecycle_control",
    "usdjpy_carry_unwind_exit_subject",
)
_THIS_FILE = Path(__file__).resolve()


def usdjpy_carry_exit_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def frontier_executable() -> ExecutableSpec:
    return high_vol_target_reversal_executable(
        high_vol_target_reversal_configurations()[1]
    )


@dataclass(frozen=True, slots=True)
class USDJPYCarryExitConfiguration:
    profile: str

    def __post_init__(self) -> None:
        if self.profile not in _PROFILES:
            raise ValueError("USDJPY carry-exit profile is invalid")

    @property
    def configuration_id(self) -> str:
        return self.profile

    @property
    def holding_bars(self) -> int:
        return 12

    @property
    def signal_sign(self) -> int:
        return 1

    @property
    def target_quantile_bp(self) -> int:
        return 9000

    @property
    def uses_carry_exit(self) -> bool:
        return self.profile == "usdjpy_carry_unwind_exit_subject"

    def semantic_parameters(self) -> dict[str, Any]:
        values = dict(frontier_executable().parameter_values())
        values.update(
            {
                "target_lifecycle_policy": (
                    "fixed_six_bar_control"
                    if not self.uses_carry_exit
                    else "entry_requires_completed_state_then_exit_next_open_"
                    "after_negative_or_missing_state_and_reserve_slot_to_six_bars"
                ),
                "usdjpy_carry_state_bars": CARRY_STATE_BARS,
                "usdjpy_carry_unwind_sign": "negative",
            }
        )
        return values


def usdjpy_carry_exit_configurations() -> tuple[USDJPYCarryExitConfiguration, ...]:
    return tuple(USDJPYCarryExitConfiguration(profile) for profile in _PROFILES)


def _local(name: str) -> str:
    return (
        f"axiom_rift.research.usdjpy_carry_exit_chassis.{name}@sha256:"
        f"{usdjpy_carry_exit_chassis_implementation_sha256()}"
    )


def usdjpy_carry_exit_components() -> tuple[ComponentSpec, ...]:
    frontier = frontier_executable()
    contract = usdjpy_source_contract()
    target_lifecycle = next(
        component
        for component in frontier.components
        if component.protocol == "lifecycle.fixed_hold_no_overlap.v12"
    )
    source = ComponentSpec(
        display_name="exact FPMarkets USDJPY completed M5 spot input",
        protocol="external_source.fpmarkets_usdjpy_m5.v1",
        implementation=_local("simulate_usdjpy_carry_exit"),
        spec={
            "raw_sha256": USDJPY_RAW_SHA256,
            "raw_sha256_role": "acquisition_identity_only",
            "development_prefix_sha256": (
                USDJPY_OBSERVED_DEVELOPMENT_SPEC.prefix_sha256
            ),
            "development_prefix_byte_count": (
                USDJPY_OBSERVED_DEVELOPMENT_SPEC.prefix_byte_count
            ),
            "development_prefix_row_count": (
                USDJPY_OBSERVED_DEVELOPMENT_SPEC.row_count
            ),
            "development_material_identity": (
                USDJPY_OBSERVED_DEVELOPMENT_SPEC.material_identity
            ),
            "development_source_key": "USDJPY",
            "development_loader_implementation_sha256": (
                external_observed_development_loader_implementation_sha256()
            ),
            "source_contract_id": contract.source_contract_id,
            "mapping_identity": contract.mapping_identity,
            "schema_identity": contract.schema_identity,
            "field_identity": contract.field_identity,
            "clock_identity": contract.clock_identity,
            "availability_identity": contract.availability_identity,
            "join": "exact_timestamp_no_fill_no_asof_no_offset_inference",
            "entry_missing_state_action": "no_entry",
            "holding_missing_or_stale_action": "next_exact_open_safe_exit",
        },
        semantic_dependencies=(
            contract.source_contract_id,
            f"external-development-material:{USDJPY_OBSERVED_DEVELOPMENT_SPEC.material_identity}",
        ),
    )
    state = ComponentSpec(
        display_name="completed USDJPY one-FX-day carry state",
        protocol="lifecycle.usdjpy_completed_288bar_carry_state.v2",
        implementation=_local("aligned_usdjpy_carry_return"),
        spec={
            "lookback_completed_source_bars": CARRY_STATE_BARS,
            "carry_unwind": "negative_log_return",
            "carry_stable": "nonnegative_log_return",
            "fit": "none",
            "threshold": "zero_only",
            "gap_action": "reset_and_rewarm_then_fail_closed",
        },
        semantic_dependencies=(source.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="USDJPY carry-unwind target lifecycle invalidation",
        protocol="lifecycle.usdjpy_carry_unwind_target_exit.v2",
        implementation=_local("simulate_usdjpy_carry_exit"),
        spec={
            "parameter_fields": ["target_lifecycle_policy"],
            "dependent_slot": "target_direction",
            "entry_and_direction": "exact_STU_0092_unchanged",
            "scheduled_holding_bars": TARGET_HOLDING_BARS,
            "early_exit": (
                "next_exact_bar_open_after_first_completed_negative_carry_state"
            ),
            "slot_reservation": "retain_original_six_bar_horizon",
            "entry_missing_state": "no_entry",
            "entry_missing_slot_reservation": "retain_original_six_bar_horizon",
            "holding_missing_or_stale_state": (
                "next_exact_bar_open_safe_exit"
            ),
            "router_slot": "unchanged_fixed_twelve_bar",
            "parameter_grid": False,
        },
        semantic_dependencies=(target_lifecycle.identity, state.identity),
    )
    frontier_execution = next(
        component
        for component in frontier.components
        if component.protocol.startswith("execution.")
    )
    engine_binding = ComponentSpec(
        display_name="content-bound USDJPY carry-exit chassis engine",
        protocol="execution.chassis_artifact_binding.v1",
        implementation=_local("simulate_usdjpy_carry_exit"),
        spec={
            "artifact_sha256": usdjpy_carry_exit_chassis_implementation_sha256(),
            "baseline_execution_semantics": "preserved",
            "identity_policy": "any_artifact_byte_change_creates_new_identity",
        },
        semantic_dependencies=(frontier_execution.identity,),
    )
    portfolio = ComponentSpec(
        display_name="fixed frontier with macro lifecycle invalidation",
        protocol="portfolio.usdjpy_carry_exit_frontier.v1",
        implementation=_local("simulate_usdjpy_carry_exit"),
        spec={
            "entry_activity": "unchanged_by_slot_reservation",
            "entry_direction": "unchanged_STU_0092",
            "low_middle_high_roles": "unchanged_STU_0092",
            "session": "unchanged_broker_15_22_target",
            "per_sleeve_lot": 1,
        },
        semantic_dependencies=(
            frontier.components[-1].identity,
            lifecycle.identity,
            engine_binding.identity,
        ),
    )
    return (*frontier.components, source, state, lifecycle, engine_binding, portfolio)


def usdjpy_carry_exit_executable(
    configuration: USDJPYCarryExitConfiguration,
) -> ExecutableSpec:
    if not configuration.uses_carry_exit:
        return frontier_executable()
    baseline = frontier_executable()
    implementation = usdjpy_carry_exit_chassis_implementation_sha256()
    return ExecutableSpec(
        display_name=(
            "registered activity frontier with USDJPY carry-unwind target early exit"
        ),
        components=usdjpy_carry_exit_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=baseline.data_contract,
        split_contract=baseline.split_contract,
        clock_contract=baseline.clock_contract,
        cost_contract=baseline.cost_contract,
        engine_contract=(
            f"{baseline.engine_contract}:"
            f"usdjpy_carry_exit_chassis_sha256_{implementation}:"
            "external_development_material_"
            f"{USDJPY_OBSERVED_DEVELOPMENT_SPEC.material_identity}:"
            "external_development_prefix_"
            f"{USDJPY_OBSERVED_DEVELOPMENT_SPEC.prefix_sha256}:"
            "external_development_loader_"
            f"{external_observed_development_loader_implementation_sha256()}"
        ),
        source_contracts=(usdjpy_source_contract().source_contract_id,),
    )


def executable_configuration_map() -> dict[str, USDJPYCarryExitConfiguration]:
    return {
        usdjpy_carry_exit_executable(configuration).identity: configuration
        for configuration in usdjpy_carry_exit_configurations()
    }


@dataclass(frozen=True, slots=True)
class _FixedSlot:
    holding_bars: int
    signal_sign: int = 1


def _fixed_slot(
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
    name: str,
) -> SimulationResult:
    result = simulate_fixed_hold(
        frame=frame,
        score=score,
        volatility=volatility,
        run=run,
        threshold=1.0,
        configuration=_FixedSlot(holding_bars),
        test_start=test_start,
        test_end=test_end,
        fold_id=fold_id,
        regime_cutoffs=regime_cutoffs,
        effective_spread=effective_spread,
    )
    if not result.trades.empty:
        result.trades = result.trades.assign(
            slot=name,
            carry_early_exit=False,
            carry_trigger_time=pd.NaT,
            carry_exit_reason="not_applicable_router",
            carry_state_fail_closed=False,
            scheduled_exit_time=result.trades["exit_time"],
        )
    result.intent_rows = tuple((name, *row) for row in result.intent_rows)
    return result


def _target_carry_exit_slot(
    *,
    frame: pd.DataFrame,
    score: np.ndarray,
    carry_return: np.ndarray,
    volatility: np.ndarray,
    run: np.ndarray,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray,
) -> SimulationResult:
    time = pd.to_datetime(frame["time"], errors="raise")
    time_ns = _time_ns(frame)
    opens = pd.to_numeric(frame["open"], errors="raise").to_numpy(dtype=float)
    spreads = np.asarray(effective_spread, dtype=float)
    state = np.asarray(carry_return, dtype=float)
    values = np.asarray(score, dtype=float)
    if any(len(item) != len(frame) for item in (spreads, state, values, volatility, run)):
        raise ValueError("USDJPY carry-exit slot input length differs from frame")
    candidates = np.flatnonzero(
        ((time >= test_start) & (time <= test_end)).to_numpy()
        & np.isfinite(values)
    )
    records: list[dict[str, Any]] = []
    intents: list[tuple[Any, ...]] = []
    next_decision_index = -1
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
        scheduled_exit_index = entry_index + TARGET_HOLDING_BARS
        if (
            scheduled_exit_index >= len(frame)
            or time.iloc[scheduled_exit_index] > test_end
        ):
            continue
        decision_bar_open_time = time.iloc[decision_index]
        decision_time = decision_bar_open_time + pd.Timedelta(minutes=5)
        entry_time = time.iloc[entry_index]
        scheduled_exit_time = time.iloc[scheduled_exit_index]
        if (
            time_ns[entry_index] - time_ns[decision_index] != _FIVE_MINUTES_NS
            or run[scheduled_exit_index] < TARGET_HOLDING_BARS + 2
        ):
            gap_excluded += 1
            intents.append(
                (
                    "target_direction",
                    decision_time,
                    entry_time,
                    scheduled_exit_time,
                    direction,
                    "gap_excluded",
                )
            )
            continue
        if decision_time != entry_time:
            causality_violations += 1
            intents.append(
                (
                    "target_direction",
                    decision_time,
                    entry_time,
                    scheduled_exit_time,
                    direction,
                    "causality_violation",
                )
            )
            continue
        if not np.isfinite(state[decision_index]):
            next_decision_index = scheduled_exit_index
            intents.append(
                (
                    "target_direction",
                    decision_time,
                    entry_time,
                    entry_time,
                    direction,
                    "source_state_missing_no_entry",
                )
            )
            continue
        exit_index = scheduled_exit_index
        trigger_index: int | None = None
        trigger_reason: str | None = None
        for state_index in range(entry_index, scheduled_exit_index):
            if not np.isfinite(state[state_index]):
                trigger_index = state_index
                trigger_reason = "missing_or_stale_state_safe_exit"
                exit_index = state_index + 1
                break
            if state[state_index] < 0.0:
                trigger_index = state_index
                trigger_reason = "negative_carry_unwind_exit"
                exit_index = state_index + 1
                break
        exit_time = time.iloc[exit_index]
        carry_early_exit = exit_index < scheduled_exit_index
        carry_state_fail_closed = trigger_reason == "missing_or_stale_state_safe_exit"
        next_decision_index = scheduled_exit_index
        if not (np.isfinite(spreads[entry_index]) and np.isfinite(spreads[exit_index])):
            unresolved += 1
            intents.append(
                (
                    "target_direction",
                    decision_time,
                    entry_time,
                    exit_time,
                    direction,
                    "unknown_cost",
                )
            )
            continue
        native, stress = execution_pnl(
            direction=direction,
            entry_bid=float(opens[entry_index]),
            exit_bid=float(opens[exit_index]),
            entry_spread_points=float(spreads[entry_index]),
            exit_spread_points=float(spreads[exit_index]),
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
                "entry_time": entry_time,
                "exit_time": exit_time,
                "direction": direction,
                "pnl": native,
                "stress_pnl": stress,
                "fold_id": fold_id,
                "regime": regime,
                "slot": "target_direction",
                "carry_early_exit": carry_early_exit,
                "carry_trigger_time": (
                    pd.NaT if trigger_index is None else time.iloc[trigger_index]
                ),
                "carry_exit_reason": (
                    "scheduled_fixed_exit"
                    if trigger_reason is None
                    else trigger_reason
                ),
                "carry_state_fail_closed": carry_state_fail_closed,
                "scheduled_exit_time": scheduled_exit_time,
            }
        )
        intents.append(
            (
                "target_direction",
                decision_time,
                entry_time,
                exit_time,
                direction,
                (
                    "executed_missing_state_safe_exit"
                    if carry_state_fail_closed
                    else "executed_carry_exit"
                    if carry_early_exit
                    else "executed_fixed_exit"
                ),
            )
        )
    trades = pd.DataFrame.from_records(records)
    if trades.empty:
        trades = pd.DataFrame(
            columns=(
                "decision_bar_open_time",
                "decision_time",
                "entry_time",
                "exit_time",
                "direction",
                "pnl",
                "stress_pnl",
                "fold_id",
                "regime",
                "slot",
                "carry_early_exit",
                "carry_trigger_time",
                "carry_exit_reason",
                "carry_state_fail_closed",
                "scheduled_exit_time",
            )
        )
    return SimulationResult(
        trades=trades,
        intent_rows=tuple(intents),
        unresolved_cost_signal_count=unresolved,
        gap_excluded_signal_count=gap_excluded,
        causality_violation_count=causality_violations,
    )


def simulate_usdjpy_carry_exit(
    *,
    frame: pd.DataFrame,
    score: np.ndarray,
    volatility: np.ndarray,
    run: np.ndarray,
    threshold: float,
    configuration: USDJPYCarryExitConfiguration,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray | None = None,
) -> SimulationResult:
    del threshold
    values = np.asarray(score, dtype=float)
    if values.ndim != 2 or values.shape != (len(frame), 3):
        raise ValueError("USDJPY carry-exit score matrix is invalid")
    if not configuration.uses_carry_exit:
        return simulate_high_vol_target_reversal(
            frame=frame,
            score=values[:, :2],
            volatility=volatility,
            run=run,
            threshold=1.0,
            configuration=high_vol_target_reversal_configurations()[1],
            test_start=test_start,
            test_end=test_end,
            fold_id=fold_id,
            regime_cutoffs=regime_cutoffs,
            effective_spread=effective_spread,
        )
    routed = values[:, :2].copy()
    high = np.isfinite(volatility) & (
        np.asarray(volatility, dtype=float) >= regime_cutoffs[1]
    )
    routed[high, 1] *= -1.0
    spreads = np.asarray(effective_spread, dtype=float)
    router = _fixed_slot(
        frame=frame,
        score=routed[:, 0],
        volatility=volatility,
        run=run,
        holding_bars=12,
        test_start=test_start,
        test_end=test_end,
        fold_id=fold_id,
        regime_cutoffs=regime_cutoffs,
        effective_spread=spreads,
        name="regime_router",
    )
    target = routed[:, 1].copy()
    entry_hours = (
        pd.to_datetime(frame["time"], errors="raise")
        + pd.Timedelta(minutes=5)
    ).dt.hour
    target[~entry_hours.isin(range(15, 23)).to_numpy()] = np.nan
    macro = _target_carry_exit_slot(
        frame=frame,
        score=target,
        carry_return=values[:, 2],
        volatility=volatility,
        run=run,
        test_start=test_start,
        test_end=test_end,
        fold_id=fold_id,
        regime_cutoffs=regime_cutoffs,
        effective_spread=spreads,
    )
    if router.trades.empty:
        trades = macro.trades.copy()
    elif macro.trades.empty:
        trades = router.trades.copy()
    else:
        trades = pd.concat((router.trades, macro.trades), ignore_index=True)
    trades = trades.sort_values(
        ["decision_time", "slot"], kind="stable"
    ).reset_index(drop=True)
    return SimulationResult(
        trades=trades,
        intent_rows=(*router.intent_rows, *macro.intent_rows),
        unresolved_cost_signal_count=(
            router.unresolved_cost_signal_count + macro.unresolved_cost_signal_count
        ),
        gap_excluded_signal_count=(
            router.gap_excluded_signal_count + macro.gap_excluded_signal_count
        ),
        causality_violation_count=(
            router.causality_violation_count + macro.causality_violation_count
        ),
    )


__all__ = [
    "CARRY_STATE_BARS",
    "SELECTION_TOTAL_EXPOSURES",
    "TARGET_HOLDING_BARS",
    "USDJPYCarryExitConfiguration",
    "USDJPY_RAW_SHA256",
    "_target_carry_exit_slot",
    "executable_configuration_map",
    "frontier_executable",
    "simulate_usdjpy_carry_exit",
    "usdjpy_carry_exit_chassis_implementation_sha256",
    "usdjpy_carry_exit_components",
    "usdjpy_carry_exit_configurations",
    "usdjpy_carry_exit_executable",
]
