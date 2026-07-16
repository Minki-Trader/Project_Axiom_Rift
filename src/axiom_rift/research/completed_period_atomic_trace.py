"""Canonical completed-period source bindings for atomic fixed-hold traces.

The helper owns the one materialization and validation rule used by analog,
historical-family, and drawdown replay traces.  A completed M5 period is a
historical cost proxy, never a point-in-time quote: next-open entry cost is
bound to ``entry_index - 1`` and exit cost to ``exit_index - 1``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from axiom_rift.research.discovery import (
    completed_bar_execution_spreads,
    execution_pnl_breakdown,
)
from axiom_rift.research.scientific_trace import ScientificTraceError


MICROPOINTS_PER_POINT = 1_000_000
COMPLETED_PERIOD_SPREAD_SEMANTICS = "completed_period_proxy"
_BAR_DURATION = pd.Timedelta(minutes=5)
_VALIDATED_BAR_DURATION = timedelta(minutes=5)
_THIS_FILE = Path(__file__).resolve()

ObservationIdBuilder = Callable[[str, Mapping[str, Any]], str]


def completed_period_atomic_trace_implementation_sha256() -> str:
    """Return the exact shared materializer and validator source identity."""

    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def completed_period_proxy_execution_spec(
    *,
    repair_policy: str,
) -> dict[str, object]:
    """Return the shared Component contract for the implemented proxy path."""

    policy = _ascii("completed-period repair policy", repair_policy)
    return {
        "decision_spread_source": "decision_bar_index",
        "entry_cost_source": (
            "entry_bar_index_minus_1_equals_decision_bar_index"
        ),
        "exit_cost_source": "exit_bar_index_minus_1",
        "information_completion": "source_bar_open_plus_5m",
        "observed_positive_spread": "use_as_is",
        "point": "0.01",
        "spread_semantics": (
            "historical_completed_period_proxy_not_point_in_time_quote"
        ),
        "stress": "half_effective_spread_each_side",
        "unknown_entry_action": "cancel_before_open",
        "zero_spread_repair": policy,
    }


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _integer(name: str, value: object, *, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise ScientificTraceError(f"{name} must be an integer >= {minimum}")
    return value


def _optional_boolean(name: str, value: object) -> bool | None:
    if value is not None and type(value) is not bool:
        raise ScientificTraceError(f"{name} must be boolean or null")
    return value


def _timestamp(name: str, value: object) -> datetime:
    if type(value) is not str or not value or not value.isascii():
        raise ScientificTraceError(f"{name} must be an ASCII timestamp")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ScientificTraceError(f"{name} is not an ISO timestamp") from exc
    return result


def _iso(value: object) -> str:
    return pd.Timestamp(value).isoformat()


def _micropoints(value: object) -> int:
    return int(round(float(value) * MICROPOINTS_PER_POINT))


@dataclass(frozen=True, slots=True, kw_only=True)
class AtomicFixedHoldMember:
    """Typed identity and lifecycle inputs for one trace member."""

    configuration_id: str
    executable_id: str
    historical_reference_executable_id: str
    holding_bars: int

    def __post_init__(self) -> None:
        _ascii("configuration_id", self.configuration_id)
        executable_id = _ascii("executable_id", self.executable_id)
        historical_id = _ascii(
            "historical_reference_executable_id",
            self.historical_reference_executable_id,
        )
        if not executable_id.startswith("executable:"):
            raise ValueError("executable_id must be an Executable identity")
        if not historical_id.startswith("executable:"):
            raise ValueError(
                "historical_reference_executable_id must be an Executable identity"
            )
        if type(self.holding_bars) is not int or self.holding_bars < 1:
            raise ValueError("holding_bars must be a positive integer")


@dataclass(frozen=True, slots=True)
class CompletedPeriodSourceBinding:
    """One decision/entry/exit binding and its causal known mask."""

    decision_index: int
    entry_index: int
    exit_index: int
    decision_source_index: int
    entry_source_index: int
    exit_source_index: int
    decision_source_time: pd.Timestamp
    entry_source_time: pd.Timestamp
    exit_source_time: pd.Timestamp
    decision_information_complete_at: pd.Timestamp
    entry_information_complete_at: pd.Timestamp
    exit_information_complete_at: pd.Timestamp
    decision_known: bool
    entry_known: bool
    exit_known: bool | None

    def fields(self) -> dict[str, object]:
        return {
            "decision_bar_index": self.decision_index,
            "decision_spread_source_bar_index": self.decision_source_index,
            "decision_spread_source_bar_open_time": _iso(
                self.decision_source_time
            ),
            "decision_spread_information_complete_at": _iso(
                self.decision_information_complete_at
            ),
            "decision_spread_known": self.decision_known,
            "entry_bar_index": self.entry_index,
            "entry_spread_source_bar_index": self.entry_source_index,
            "entry_spread_source_bar_open_time": _iso(self.entry_source_time),
            "entry_spread_information_complete_at": _iso(
                self.entry_information_complete_at
            ),
            "entry_spread_known": self.entry_known,
            "exit_bar_index": self.exit_index,
            "exit_spread_source_bar_index": self.exit_source_index,
            "exit_spread_source_bar_open_time": _iso(self.exit_source_time),
            "exit_spread_information_complete_at": _iso(
                self.exit_information_complete_at
            ),
            "exit_spread_known": self.exit_known,
            "spread_semantics": COMPLETED_PERIOD_SPREAD_SEMANTICS,
        }


@dataclass(frozen=True, slots=True)
class CompletedPeriodTraceFrame:
    """Validated frame, source surface, and timestamp lookup for row builders."""

    time: pd.Series
    opens: np.ndarray
    spreads: np.ndarray
    positions: Mapping[int, int]

    @classmethod
    def from_frame(
        cls,
        frame: pd.DataFrame,
        effective_spread: np.ndarray,
    ) -> "CompletedPeriodTraceFrame":
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("atomic trace frame must be a DataFrame")
        time = pd.to_datetime(frame["time"], errors="raise")
        positions = {
            int(value.value): index for index, value in enumerate(time)
        }
        if len(positions) != len(frame):
            raise ValueError("atomic trace frame timestamps are not unique")
        opens = pd.to_numeric(frame["open"], errors="raise").to_numpy(float)
        spreads = np.asarray(effective_spread, dtype=float)
        if spreads.ndim != 1 or len(spreads) != len(frame):
            raise ValueError("atomic trace spread surface differs from frame")
        return cls(
            time=time,
            opens=opens,
            spreads=spreads,
            positions=positions,
        )

    def position(self, value: object) -> int:
        timestamp = pd.Timestamp(value)
        try:
            return int(self.positions[int(timestamp.value)])
        except KeyError as exc:
            raise ValueError("atomic trace timestamp is outside the frame") from exc

    def source_binding(
        self,
        *,
        decision_bar: object,
        entry: object,
        exit_time: object,
        holding_bars: int,
        status: str | None,
    ) -> CompletedPeriodSourceBinding:
        decision_timestamp = pd.Timestamp(decision_bar)
        entry_timestamp = pd.Timestamp(entry)
        exit_timestamp = pd.Timestamp(exit_time)
        decision_index = self.position(decision_timestamp)
        entry_index = self.position(entry_timestamp)
        exit_index = self.position(exit_timestamp)
        if (
            entry_index != decision_index + 1
            or exit_index - entry_index != holding_bars
        ):
            raise RuntimeError("atomic fixed-hold row indices drifted")
        entry_source_index = entry_index - 1
        exit_source_index = exit_index - 1
        entry_known = bool(np.isfinite(self.spreads[entry_source_index]))
        inspect_exit = status is None or status in {"executed", "unknown_cost"}
        exit_known = (
            bool(np.isfinite(self.spreads[exit_source_index]))
            if inspect_exit
            else None
        )
        return CompletedPeriodSourceBinding(
            decision_index=decision_index,
            entry_index=entry_index,
            exit_index=exit_index,
            decision_source_index=decision_index,
            entry_source_index=entry_source_index,
            exit_source_index=exit_source_index,
            decision_source_time=pd.Timestamp(self.time.iloc[decision_index]),
            entry_source_time=pd.Timestamp(self.time.iloc[entry_source_index]),
            exit_source_time=pd.Timestamp(self.time.iloc[exit_source_index]),
            decision_information_complete_at=(
                pd.Timestamp(self.time.iloc[decision_index]) + _BAR_DURATION
            ),
            entry_information_complete_at=(
                pd.Timestamp(self.time.iloc[entry_source_index]) + _BAR_DURATION
            ),
            exit_information_complete_at=(
                pd.Timestamp(self.time.iloc[exit_source_index]) + _BAR_DURATION
            ),
            decision_known=entry_known,
            entry_known=entry_known,
            exit_known=exit_known,
        )


def materialize_fixed_hold_trade_rows(
    *,
    member: AtomicFixedHoldMember,
    simulations: Mapping[tuple[str, str], Any],
    frame: pd.DataFrame,
    effective_spread: np.ndarray,
    observation_id: ObservationIdBuilder,
    include_holding_bars: bool = False,
) -> list[dict[str, object]]:
    """Materialize full-scope executed trades and rederive their PnL."""

    if not isinstance(member, AtomicFixedHoldMember):
        raise TypeError("atomic trace member is not typed")
    if not callable(observation_id):
        raise TypeError("atomic observation id builder is not callable")
    if type(include_holding_bars) is not bool:
        raise TypeError("include_holding_bars must be boolean")
    context = CompletedPeriodTraceFrame.from_frame(frame, effective_spread)
    rows: list[dict[str, object]] = []
    for (fold_id, scope), simulation in simulations.items():
        if scope != "full":
            continue
        for raw in simulation.trades.to_dict(orient="records"):
            decision_bar = pd.Timestamp(raw["decision_bar_open_time"])
            entry = pd.Timestamp(raw["entry_time"])
            exit_time = pd.Timestamp(raw["exit_time"])
            binding = context.source_binding(
                decision_bar=decision_bar,
                entry=entry,
                exit_time=exit_time,
                holding_bars=member.holding_bars,
                status=None,
            )
            execution_spreads = completed_bar_execution_spreads(
                context.spreads,
                entry_index=binding.entry_index,
                exit_index=binding.exit_index,
            )
            if not execution_spreads.costs_known:
                raise RuntimeError(
                    "executed trade has unresolved completed-bar proxy cost"
                )
            if (
                execution_spreads.entry_proxy_index
                != binding.entry_source_index
                or execution_spreads.exit_proxy_index
                != binding.exit_source_index
            ):
                raise RuntimeError("completed-bar proxy source binding drifted")
            recomputed = execution_pnl_breakdown(
                direction=int(raw["direction"]),
                entry_bid=float(context.opens[binding.entry_index]),
                exit_bid=float(context.opens[binding.exit_index]),
                entry_spread_points=execution_spreads.entry_spread_points,
                exit_spread_points=execution_spreads.exit_spread_points,
            )
            observed = (
                float(raw["gross_pnl"]),
                float(raw["native_cost"]),
                float(raw["stress_cost"]),
                float(raw["pnl"]),
                float(raw["stress_pnl"]),
            )
            expected = (
                recomputed.gross_pnl,
                recomputed.native_cost,
                recomputed.stress_cost,
                recomputed.native_net_pnl,
                recomputed.stress_net_pnl,
            )
            if not np.allclose(observed, expected, rtol=0.0, atol=1e-12):
                raise RuntimeError(
                    "trade cost does not match completed-bar spread sources"
                )
            gross = _micropoints(raw["gross_pnl"])
            native_cost = _micropoints(raw["native_cost"])
            stress_cost = _micropoints(raw["stress_cost"])
            row: dict[str, object] = {
                "availability_time": _iso(raw["decision_time"]),
                "configuration_id": member.configuration_id,
                "decision_bar_open_time": _iso(decision_bar),
                "decision_time": _iso(raw["decision_time"]),
                "direction": int(raw["direction"]),
                "entry_time": _iso(entry),
                "executable_id": member.executable_id,
                "exit_time": _iso(exit_time),
                "fold_id": str(fold_id),
                "gross_pnl_micropoints": gross,
                "historical_reference_executable_id": (
                    member.historical_reference_executable_id
                ),
                "native_cost_micropoints": native_cost,
                "native_net_pnl_micropoints": gross - native_cost,
                "observation_id": "pending",
                "regime": str(raw["regime"]),
                "stress_cost_micropoints": stress_cost,
                "stress_net_pnl_micropoints": gross - stress_cost,
                **binding.fields(),
            }
            if include_holding_bars:
                row["holding_bars"] = member.holding_bars
            row["observation_id"] = observation_id("trade", row)
            rows.append(row)
    return rows


def materialize_fixed_hold_intent_rows(
    *,
    member: AtomicFixedHoldMember,
    simulations: Mapping[tuple[str, str], Any],
    frame: pd.DataFrame,
    effective_spread: np.ndarray,
    observation_id: ObservationIdBuilder,
    include_holding_bars: bool = False,
) -> list[dict[str, object]]:
    """Materialize every full and prefix intent with one causal known mask."""

    if not isinstance(member, AtomicFixedHoldMember):
        raise TypeError("atomic trace member is not typed")
    if not callable(observation_id):
        raise TypeError("atomic observation id builder is not callable")
    if type(include_holding_bars) is not bool:
        raise TypeError("include_holding_bars must be boolean")
    context = CompletedPeriodTraceFrame.from_frame(frame, effective_spread)
    rows: list[dict[str, object]] = []
    for (fold_id, scope), simulation in simulations.items():
        for ordinal, raw in enumerate(simulation.intent_rows, start=1):
            decision, entry, exit_time, direction, status = raw
            decision_timestamp = pd.Timestamp(decision)
            entry_timestamp = pd.Timestamp(entry)
            exit_timestamp = pd.Timestamp(exit_time)
            decision_bar = decision_timestamp - _BAR_DURATION
            status_text = str(status)
            binding = context.source_binding(
                decision_bar=decision_bar,
                entry=entry_timestamp,
                exit_time=exit_timestamp,
                holding_bars=member.holding_bars,
                status=status_text,
            )
            row: dict[str, object] = {
                "availability_time": _iso(decision_timestamp),
                "configuration_id": member.configuration_id,
                "decision_bar_open_time": _iso(decision_bar),
                "decision_time": _iso(decision_timestamp),
                "direction": int(direction),
                "entry_time": _iso(entry_timestamp),
                "executable_id": member.executable_id,
                "exit_time": _iso(exit_timestamp),
                "fold_id": str(fold_id),
                "historical_reference_executable_id": (
                    member.historical_reference_executable_id
                ),
                "observation_id": "pending",
                "ordinal": ordinal,
                "scope": str(scope),
                "status": status_text,
                **binding.fields(),
            }
            if include_holding_bars:
                row["holding_bars"] = member.holding_bars
            row["observation_id"] = observation_id("intent", row)
            rows.append(row)
    return rows


def validate_completed_period_fixed_hold_sources(
    row: Mapping[str, Any],
    *,
    holding_bars: int,
    prefix: str,
    intent_status: str | None = None,
) -> tuple[datetime, datetime, datetime]:
    """Validate the canonical source binding shared by all trace schemas."""

    if not isinstance(row, Mapping):
        raise ScientificTraceError(f"{prefix} row is not a mapping")
    if type(holding_bars) is not int or holding_bars < 1:
        raise ScientificTraceError(f"{prefix} holding interval is invalid")
    bar_open = _timestamp(
        f"{prefix} decision_bar_open_time",
        row.get("decision_bar_open_time"),
    )
    availability = _timestamp(
        f"{prefix} availability_time", row.get("availability_time")
    )
    decision = _timestamp(f"{prefix} decision_time", row.get("decision_time"))
    entry = _timestamp(f"{prefix} entry_time", row.get("entry_time"))
    exit_time = _timestamp(f"{prefix} exit_time", row.get("exit_time"))
    if not (
        bar_open + _VALIDATED_BAR_DURATION == availability
        and bar_open <= decision <= entry < exit_time
    ):
        raise ScientificTraceError(f"{prefix} causal clock is invalid")
    decision_index = _integer(
        f"{prefix} decision_bar_index",
        row.get("decision_bar_index"),
        minimum=0,
    )
    entry_index = _integer(
        f"{prefix} entry_bar_index", row.get("entry_bar_index"), minimum=1
    )
    exit_index = _integer(
        f"{prefix} exit_bar_index", row.get("exit_bar_index"), minimum=1
    )
    decision_source_index = _integer(
        f"{prefix} decision_spread_source_bar_index",
        row.get("decision_spread_source_bar_index"),
        minimum=0,
    )
    entry_source_index = _integer(
        f"{prefix} entry_spread_source_bar_index",
        row.get("entry_spread_source_bar_index"),
        minimum=0,
    )
    exit_source_index = _integer(
        f"{prefix} exit_spread_source_bar_index",
        row.get("exit_spread_source_bar_index"),
        minimum=0,
    )
    decision_source_time = _timestamp(
        f"{prefix} decision_spread_source_bar_open_time",
        row.get("decision_spread_source_bar_open_time"),
    )
    entry_source_time = _timestamp(
        f"{prefix} entry_spread_source_bar_open_time",
        row.get("entry_spread_source_bar_open_time"),
    )
    exit_source_time = _timestamp(
        f"{prefix} exit_spread_source_bar_open_time",
        row.get("exit_spread_source_bar_open_time"),
    )
    decision_information_complete_at = _timestamp(
        f"{prefix} decision_spread_information_complete_at",
        row.get("decision_spread_information_complete_at"),
    )
    entry_information_complete_at = _timestamp(
        f"{prefix} entry_spread_information_complete_at",
        row.get("entry_spread_information_complete_at"),
    )
    exit_information_complete_at = _timestamp(
        f"{prefix} exit_spread_information_complete_at",
        row.get("exit_spread_information_complete_at"),
    )
    decision_known = _optional_boolean(
        f"{prefix} decision_spread_known", row.get("decision_spread_known")
    )
    entry_known = _optional_boolean(
        f"{prefix} entry_spread_known", row.get("entry_spread_known")
    )
    exit_known = _optional_boolean(
        f"{prefix} exit_spread_known", row.get("exit_spread_known")
    )
    if row.get("spread_semantics") != COMPLETED_PERIOD_SPREAD_SEMANTICS:
        raise ScientificTraceError(f"{prefix} spread semantics is invalid")
    if entry_index != decision_index + 1:
        raise ScientificTraceError(f"{prefix} decision/entry index is invalid")
    if exit_index - entry_index != holding_bars:
        raise ScientificTraceError(f"{prefix} fixed holding interval is invalid")
    if (
        decision_source_index != decision_index
        or entry_source_index != entry_index - 1
        or entry_source_index != decision_index
        or exit_source_index != exit_index - 1
        or decision_source_time != bar_open
        or entry_source_time != bar_open
        or exit_source_time >= exit_time
        or decision_information_complete_at
        != decision_source_time + _VALIDATED_BAR_DURATION
        or entry_information_complete_at
        != entry_source_time + _VALIDATED_BAR_DURATION
        or exit_information_complete_at
        != exit_source_time + _VALIDATED_BAR_DURATION
        or entry_information_complete_at > entry
        or exit_information_complete_at > exit_time
        or decision_known is not entry_known
    ):
        raise ScientificTraceError(
            f"{prefix} completed-bar spread source is invalid"
        )
    contiguous = (
        decision == availability == entry
        and exit_time
        == entry + _VALIDATED_BAR_DURATION * holding_bars
    )
    if (
        contiguous
        and exit_source_time != exit_time - _VALIDATED_BAR_DURATION
    ):
        raise ScientificTraceError(
            f"{prefix} exit spread source clock is invalid"
        )
    if intent_status is None or intent_status in {
        "entry_cancelled_unknown_cost",
        "executed",
        "unknown_cost",
    }:
        if not contiguous:
            raise ScientificTraceError(
                f"{prefix} executable fixed-hold clock is invalid"
            )
    elif intent_status == "gap_excluded":
        if decision != availability or contiguous:
            raise ScientificTraceError(
                f"{prefix} gap exclusion clock is inconsistent"
            )
    elif intent_status == "causality_violation":
        if decision == availability:
            raise ScientificTraceError(
                f"{prefix} causality violation has no observed violation"
            )
    else:
        raise ScientificTraceError(f"{prefix} intent status is invalid")
    if (
        intent_status != "causality_violation"
        and decision_information_complete_at > decision
    ):
        raise ScientificTraceError(
            f"{prefix} decision spread was unavailable at decision time"
        )
    if intent_status is None or intent_status == "executed":
        if entry_known is not True or exit_known is not True:
            raise ScientificTraceError(
                f"{prefix} executed spread availability is invalid"
            )
    elif intent_status == "entry_cancelled_unknown_cost":
        if entry_known is not False or exit_known is not None:
            raise ScientificTraceError(
                f"{prefix} unknown-entry cancellation source is invalid"
            )
    elif intent_status == "unknown_cost":
        if (
            type(entry_known) is not bool
            or type(exit_known) is not bool
            or (entry_known and exit_known)
        ):
            raise ScientificTraceError(
                f"{prefix} unresolved spread availability is invalid"
            )
    elif exit_known is not None:
        raise ScientificTraceError(
            f"{prefix} excluded path must not inspect exit spread"
        )
    return decision, entry, exit_time


__all__ = [
    "AtomicFixedHoldMember",
    "COMPLETED_PERIOD_SPREAD_SEMANTICS",
    "CompletedPeriodSourceBinding",
    "CompletedPeriodTraceFrame",
    "MICROPOINTS_PER_POINT",
    "completed_period_atomic_trace_implementation_sha256",
    "completed_period_proxy_execution_spec",
    "materialize_fixed_hold_intent_rows",
    "materialize_fixed_hold_trade_rows",
    "validate_completed_period_fixed_hold_sources",
]
