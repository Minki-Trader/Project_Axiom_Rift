"""Causal cross-sleeve gross-exposure cap over the positive-sleeve frontier.

The registered control is the exact unrestricted executable used by STU-0123.
The subject changes only entry acceptance when another sleeve position would
still be open at the prospective next-bar entry.  A blocked signal does not
consume that sleeve's lifecycle, so later bars can become eligible without
using any counterfactual outcome or future state.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
)
from axiom_rift.research.discovery import (
    SimulationResult,
    _time_ns,
    completed_bar_execution_spreads,
    empty_trade_frame,
    execution_pnl_breakdown,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.sleeve_loss_skip_risk_chassis import (
    INTENT_CALENDAR_POLICY,
    UNRESTRICTED_CONTROL,
    SleeveLossSkipRiskConfiguration,
    simulate_sleeve_loss_skip_risk,
    sleeve_loss_skip_risk_baseline,
)


CAP_ONE_GROSS_POSITION = "max_one_cross_sleeve_gross_position"
STATUS_NORMALIZED_PROTOCOL_REVISION = "status_normalized_v1"
_POLICIES = (UNRESTRICTED_CONTROL, CAP_ONE_GROSS_POSITION)
_FIVE_MINUTES_NS = 5 * 60 * 1_000_000_000
_SLOTS = (
    ("regime_router", 0, 12),
    ("target_direction", 1, 6),
)
_THIS_FILE = Path(__file__).resolve()


def sleeve_exposure_cap_risk_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class SleeveExposureCapRiskConfiguration:
    risk_policy: str

    def __post_init__(self) -> None:
        if self.risk_policy not in _POLICIES:
            raise ValueError("sleeve exposure-cap risk policy is invalid")

    @property
    def configuration_id(self) -> str:
        return self.risk_policy

    def semantic_parameters(self) -> dict[str, Any]:
        baseline = sleeve_loss_skip_risk_baseline().to_identity_payload()
        parameters = baseline.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError("sleeve exposure-cap baseline parameters are invalid")
        return {
            **parameters,
            "gross_exposure_policy": self.risk_policy,
        }


def sleeve_exposure_cap_risk_configurations() -> tuple[
    SleeveExposureCapRiskConfiguration, ...
]:
    return tuple(SleeveExposureCapRiskConfiguration(value) for value in _POLICIES)


def _local(name: str) -> str:
    return (
        "axiom_rift.research.sleeve_exposure_cap_risk_chassis."
        f"{name}@sha256:{sleeve_exposure_cap_risk_chassis_implementation_sha256()}"
    )


def sleeve_exposure_cap_risk_components() -> tuple[ComponentSpec, ...]:
    baseline = sleeve_loss_skip_risk_baseline()
    cap = ComponentSpec(
        display_name="causal one-lot cross-sleeve gross-exposure cap",
        protocol="risk.cross_sleeve_gross_exposure_cap.v1",
        implementation=_local("simulate_sleeve_exposure_cap_risk"),
        spec={
            "blocked_signal_lifecycle": "not_consumed",
            "collision_priority": "regime_router_then_target_direction",
            "counterfactual_blocked_trade_outcome_access": "forbidden",
            "dynamic_sizing": False,
            "maximum_concurrent_gross_lots": 1,
            "parameter_fields": ["gross_exposure_policy"],
            "position_activity_interval": "entry_inclusive_exit_exclusive",
            "state_partition": "fold",
            "state_source": "accepted_positions_with_known_entry_and_exit_clock_only",
        },
        semantic_dependencies=(
            baseline.components[8].identity,
            baseline.components[14].identity,
            baseline.components[16].identity,
            baseline.components[17].identity,
        ),
    )
    return (*baseline.components, cap)


def sleeve_exposure_cap_risk_executable(
    configuration: SleeveExposureCapRiskConfiguration,
) -> ExecutableSpec:
    baseline = sleeve_loss_skip_risk_baseline()
    if configuration.risk_policy == UNRESTRICTED_CONTROL:
        return baseline
    return ExecutableSpec(
        display_name="positive sleeves causal one-lot gross-exposure cap",
        components=sleeve_exposure_cap_risk_components(),
        parameters=configuration.semantic_parameters(),
        data_contract=baseline.data_contract,
        split_contract=baseline.split_contract,
        clock_contract=baseline.clock_contract,
        cost_contract=baseline.cost_contract,
        engine_contract=baseline.engine_contract,
        source_contracts=baseline.source_contracts,
    )


def sleeve_exposure_cap_risk_successor_executable(
    configuration: SleeveExposureCapRiskConfiguration,
) -> ExecutableSpec:
    current = sleeve_exposure_cap_risk_executable(configuration)
    parameters = current.parameter_values()
    if not isinstance(parameters, dict):
        raise ValueError("sleeve exposure-cap successor parameters are invalid")
    return ExecutableSpec(
        display_name="status-normalized " + current.display_name,
        components=current.components,
        parameters={
            **parameters,
            "scientific_protocol_revision": STATUS_NORMALIZED_PROTOCOL_REVISION,
        },
        data_contract=current.data_contract,
        split_contract=current.split_contract,
        clock_contract=current.clock_contract,
        cost_contract=current.cost_contract,
        engine_contract=current.engine_contract,
        source_contracts=current.source_contracts,
    )


def sleeve_exposure_cap_risk_baseline() -> ExecutableSpec:
    return sleeve_loss_skip_risk_baseline()


def sleeve_exposure_cap_risk_controlled_chassis() -> ControlledStudyChassis:
    baseline = sleeve_exposure_cap_risk_baseline()
    return ControlledStudyChassis(
        baseline_executable=baseline,
        changed_domains=(ResearchLayer.RISK,),
        controlled_domains=(
            ResearchLayer.CALIBRATION,
            ResearchLayer.EXECUTION,
            ResearchLayer.FEATURE,
            ResearchLayer.LABEL,
            ResearchLayer.LIFECYCLE,
            ResearchLayer.MODEL,
            ResearchLayer.PORTFOLIO,
            ResearchLayer.REGIME,
            ResearchLayer.SELECTOR,
            ResearchLayer.SYNTHESIS,
            ResearchLayer.TRADE,
        ),
        architecture=ArchitectureChassisSpec.from_executable(baseline),
    )


def sleeve_exposure_cap_risk_successor_controlled_chassis() -> ControlledStudyChassis:
    baseline = sleeve_exposure_cap_risk_successor_executable(
        sleeve_exposure_cap_risk_configurations()[0]
    )
    current = sleeve_exposure_cap_risk_controlled_chassis()
    return ControlledStudyChassis(
        baseline_executable=baseline,
        changed_domains=current.changed_domains,
        controlled_domains=current.controlled_domains,
        architecture=ArchitectureChassisSpec.from_executable(baseline),
    )


def executable_configuration_map() -> dict[str, SleeveExposureCapRiskConfiguration]:
    configurations = sleeve_exposure_cap_risk_configurations()
    return {
        executable.identity: configuration
        for configuration in configurations
        for executable in (
            sleeve_exposure_cap_risk_executable(configuration),
            sleeve_exposure_cap_risk_successor_executable(configuration),
        )
    }


def _simulate_capped(
    *,
    frame: pd.DataFrame,
    score: np.ndarray,
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
    values = np.asarray(score, dtype=float)
    volatility_values = np.asarray(volatility, dtype=float)
    run_values = np.asarray(run)
    if values.shape != (len(frame), 2) or any(
        len(value) != len(frame)
        for value in (spreads, volatility_values, run_values)
    ):
        raise ValueError("sleeve exposure-cap input length differs from frame")
    candidates = np.flatnonzero(
        ((time >= test_start) & (time <= test_end)).to_numpy()
        & np.any(np.isfinite(values), axis=1)
    )
    records: list[dict[str, Any]] = []
    intents: list[tuple[Any, ...]] = []
    next_decision_index = {name: -1 for name, _column, _hold in _SLOTS}
    accepted_exit_indices: list[int] = []
    unresolved = 0
    gap_excluded = 0
    causality_violations = 0
    for decision_index in candidates:
        for slot, column, holding_bars in _SLOTS:
            value = values[decision_index, column]
            if (
                decision_index < next_decision_index[slot]
                or not np.isfinite(value)
                or abs(value) < 1.0
            ):
                continue
            direction = int(np.sign(value))
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
                time_ns[entry_index] - time_ns[decision_index]
                != _FIVE_MINUTES_NS
                or run_values[exit_index] < holding_bars + 2
            ):
                gap_excluded += 1
                intents.append(
                    (
                        slot,
                        decision_time,
                        entry_time,
                        exit_time,
                        direction,
                        "gap_excluded",
                    )
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
            if any(other_exit > entry_index for other_exit in accepted_exit_indices):
                intents.append(
                    (
                        slot,
                        decision_time,
                        entry_time,
                        exit_time,
                        direction,
                        "gross_exposure_cap_blocked",
                    )
                )
                continue
            next_decision_index[slot] = exit_index
            accepted_exit_indices.append(exit_index)
            execution_spreads = completed_bar_execution_spreads(
                spreads,
                entry_index=entry_index,
                exit_index=exit_index,
            )
            if not execution_spreads.costs_known:
                unresolved += 1
                intents.append(
                    (
                        slot,
                        decision_time,
                        entry_time,
                        exit_time,
                        direction,
                        "unknown_cost",
                    )
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
                    "entry_spread_cost": execution_spreads.entry_spread_points * 0.01,
                    "entry_spread_source_bar_index": execution_spreads.entry_proxy_index,
                    "entry_spread_source_bar_open_time": time.iloc[
                        execution_spreads.entry_proxy_index
                    ],
                    "entry_time": entry_time,
                    "exit_bar_index": int(exit_index),
                    "exit_bid": float(opens[exit_index]),
                    "exit_spread_cost": execution_spreads.exit_spread_points * 0.01,
                    "exit_spread_source_bar_index": execution_spreads.exit_proxy_index,
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
                (
                    slot,
                    decision_time,
                    entry_time,
                    exit_time,
                    direction,
                    "executed",
                )
            )
    trades = pd.DataFrame.from_records(records)
    if trades.empty:
        trades = empty_trade_frame().assign(slot=pd.Series(dtype=object))
    else:
        trades = trades.sort_values(
            ["decision_time", "slot"], kind="stable"
        ).reset_index(drop=True)
    return SimulationResult(
        trades=trades,
        intent_rows=tuple(intents),
        unresolved_cost_signal_count=unresolved,
        gap_excluded_signal_count=gap_excluded,
        causality_violation_count=causality_violations,
    )


def simulate_sleeve_exposure_cap_risk(
    *,
    frame: pd.DataFrame,
    score: np.ndarray,
    volatility: np.ndarray,
    run: np.ndarray,
    threshold: float,
    configuration: SleeveExposureCapRiskConfiguration,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    fold_id: str,
    regime_cutoffs: tuple[float, float],
    effective_spread: np.ndarray | None = None,
) -> SimulationResult:
    del threshold
    if effective_spread is None:
        raise ValueError("sleeve exposure-cap requires the frozen effective spread")
    if configuration.risk_policy == UNRESTRICTED_CONTROL:
        return simulate_sleeve_loss_skip_risk(
            frame=frame,
            score=score,
            volatility=volatility,
            run=run,
            threshold=1.0,
            configuration=SleeveLossSkipRiskConfiguration(UNRESTRICTED_CONTROL),
            test_start=test_start,
            test_end=test_end,
            fold_id=fold_id,
            regime_cutoffs=regime_cutoffs,
            effective_spread=effective_spread,
        )
    return _simulate_capped(
        frame=frame,
        score=score,
        volatility=volatility,
        run=run,
        test_start=test_start,
        test_end=test_end,
        fold_id=fold_id,
        regime_cutoffs=regime_cutoffs,
        effective_spread=effective_spread,
    )


__all__ = [
    "CAP_ONE_GROSS_POSITION",
    "STATUS_NORMALIZED_PROTOCOL_REVISION",
    "UNRESTRICTED_CONTROL",
    "SleeveExposureCapRiskConfiguration",
    "executable_configuration_map",
    "simulate_sleeve_exposure_cap_risk",
    "sleeve_exposure_cap_risk_baseline",
    "sleeve_exposure_cap_risk_chassis_implementation_sha256",
    "sleeve_exposure_cap_risk_components",
    "sleeve_exposure_cap_risk_configurations",
    "sleeve_exposure_cap_risk_controlled_chassis",
    "sleeve_exposure_cap_risk_executable",
    "sleeve_exposure_cap_risk_successor_controlled_chassis",
    "sleeve_exposure_cap_risk_successor_executable",
]
