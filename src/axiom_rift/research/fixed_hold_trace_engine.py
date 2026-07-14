"""Reusable atomic-trace engine for exact fixed-hold replay families."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import (
    _evaluate_configuration,
    _fold_payloads,
    _time_ns,
    _validate_engine_environment,
    _validate_fold_payloads,
    _validate_production_data,
    simulate_fixed_hold,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_TRACE_VALIDATOR,
    FixedHoldProtocolDefinition,
    build_fixed_hold_family_trace,
    expected_fixed_hold_family_inventory,
    fixed_hold_observation_id,
)


FeatureBuilder = Callable[
    [pd.DataFrame, str],
    tuple[np.ndarray, np.ndarray, np.ndarray],
]
SelectorCalibrator = Callable[[np.ndarray, np.ndarray], float]
SpreadBuilder = Callable[[np.ndarray, np.ndarray], np.ndarray]
RawParityValidator = Callable[[Path, Mapping[str, Any]], None]
_THIS_FILE = Path(__file__).resolve()


def fixed_hold_trace_engine_implementation_sha256() -> str:
    """Return the exact reusable producer implementation identity."""

    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _iso(value: object) -> str:
    return pd.Timestamp(value).isoformat()


def _micropoints(value: object) -> int:
    return int(round(float(value) * 1_000_000))


def _score_digest(values: np.ndarray) -> str:
    array = np.asarray(values, dtype="<f8").copy()
    array[np.isnan(array)] = np.nan
    material = (
        b"fixed-hold-score-vector.v1\0"
        + len(array).to_bytes(8, "big")
        + array.tobytes(order="C")
    )
    return sha256(material).hexdigest()


def _time_position_map(frame: pd.DataFrame) -> dict[int, int]:
    values = _time_ns(frame)
    positions = {int(value): index for index, value in enumerate(values)}
    if len(positions) != len(values):
        raise ValueError("fixed-hold replay time index is not unique")
    return positions


def _configuration_value(configuration: object, name: str) -> object:
    try:
        return getattr(configuration, name)
    except AttributeError as exc:
        raise ValueError(f"fixed-hold configuration lacks {name}") from exc


def _trade_rows(
    *,
    configuration: object,
    executable_id: str,
    simulations: Mapping[tuple[str, str], Any],
    frame: pd.DataFrame,
) -> list[dict[str, object]]:
    positions = _time_position_map(frame)
    configuration_id = str(
        _configuration_value(configuration, "configuration_id")
    )
    historical_id = str(
        _configuration_value(
            configuration,
            "historical_reference_executable_id",
        )
    )
    holding_bars = int(_configuration_value(configuration, "holding_bars"))
    rows: list[dict[str, object]] = []
    for (fold_id, scope), simulation in simulations.items():
        if scope != "full":
            continue
        for raw in simulation.trades.to_dict(orient="records"):
            decision_bar = pd.Timestamp(raw["decision_bar_open_time"])
            entry = pd.Timestamp(raw["entry_time"])
            exit_time = pd.Timestamp(raw["exit_time"])
            decision_index = positions[int(decision_bar.value)]
            entry_index = positions[int(entry.value)]
            exit_index = positions[int(exit_time.value)]
            gross = _micropoints(raw["gross_pnl"])
            native_cost = _micropoints(raw["native_cost"])
            stress_cost = _micropoints(raw["stress_cost"])
            row: dict[str, object] = {
                "availability_time": _iso(raw["decision_time"]),
                "configuration_id": configuration_id,
                "decision_bar_index": decision_index,
                "decision_bar_open_time": _iso(decision_bar),
                "decision_time": _iso(raw["decision_time"]),
                "direction": int(raw["direction"]),
                "entry_bar_index": entry_index,
                "entry_time": _iso(entry),
                "executable_id": executable_id,
                "exit_bar_index": exit_index,
                "exit_time": _iso(exit_time),
                "fold_id": fold_id,
                "gross_pnl_micropoints": gross,
                "historical_reference_executable_id": historical_id,
                "holding_bars": holding_bars,
                "native_cost_micropoints": native_cost,
                "native_net_pnl_micropoints": gross - native_cost,
                "observation_id": "pending",
                "regime": str(raw["regime"]),
                "stress_cost_micropoints": stress_cost,
                "stress_net_pnl_micropoints": gross - stress_cost,
            }
            if not (
                entry_index == decision_index + 1
                and exit_index - entry_index == holding_bars
            ):
                raise RuntimeError("fixed-hold trade indices drifted")
            row["observation_id"] = fixed_hold_observation_id("trade", row)
            rows.append(row)
    return rows


def _intent_rows(
    *,
    configuration: object,
    executable_id: str,
    simulations: Mapping[tuple[str, str], Any],
    frame: pd.DataFrame,
) -> list[dict[str, object]]:
    positions = _time_position_map(frame)
    configuration_id = str(
        _configuration_value(configuration, "configuration_id")
    )
    historical_id = str(
        _configuration_value(
            configuration,
            "historical_reference_executable_id",
        )
    )
    holding_bars = int(_configuration_value(configuration, "holding_bars"))
    rows: list[dict[str, object]] = []
    for (fold_id, scope), simulation in simulations.items():
        for ordinal, raw in enumerate(simulation.intent_rows, start=1):
            decision, entry, exit_time, direction, status = raw
            decision_timestamp = pd.Timestamp(decision)
            entry_timestamp = pd.Timestamp(entry)
            exit_timestamp = pd.Timestamp(exit_time)
            decision_bar_timestamp = decision_timestamp - pd.Timedelta(
                minutes=5
            )
            decision_index = positions[int(decision_bar_timestamp.value)]
            entry_index = positions[int(entry_timestamp.value)]
            exit_index = positions[int(exit_timestamp.value)]
            row: dict[str, object] = {
                "availability_time": _iso(decision_timestamp),
                "configuration_id": configuration_id,
                "decision_bar_index": decision_index,
                "decision_bar_open_time": _iso(decision_bar_timestamp),
                "decision_time": _iso(decision_timestamp),
                "direction": int(direction),
                "entry_bar_index": entry_index,
                "entry_time": _iso(entry_timestamp),
                "executable_id": executable_id,
                "exit_bar_index": exit_index,
                "exit_time": _iso(exit_timestamp),
                "fold_id": fold_id,
                "historical_reference_executable_id": historical_id,
                "holding_bars": holding_bars,
                "observation_id": "pending",
                "ordinal": ordinal,
                "scope": scope,
                "status": str(status),
            }
            if not (
                entry_index == decision_index + 1
                and exit_index - entry_index == holding_bars
            ):
                raise RuntimeError("fixed-hold intent indices drifted")
            row["observation_id"] = fixed_hold_observation_id("intent", row)
            rows.append(row)
    return rows


def compute_fixed_hold_family_trace(
    repository_root: str | Path,
    *,
    definition: FixedHoldProtocolDefinition,
    configurations: tuple[object, ...],
    feature_builder: FeatureBuilder,
    selector_calibrator: SelectorCalibrator,
    spread_builder: SpreadBuilder,
    raw_parity_validator: RawParityValidator | None = None,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    """Evaluate one preregistered family and emit its neutral atomic trace."""

    if not isinstance(definition, FixedHoldProtocolDefinition):
        raise TypeError("fixed-hold definition is not typed")
    if type(configurations) is not tuple or not configurations:
        raise ValueError("fixed-hold configurations are absent")
    for callback in (feature_builder, selector_calibrator, spread_builder):
        if not callable(callback):
            raise TypeError("fixed-hold engine callback is not callable")
    if raw_parity_validator is not None and not callable(raw_parity_validator):
        raise TypeError("fixed-hold parity validator is not callable")

    root = Path(repository_root).resolve()
    inventory = expected_fixed_hold_family_inventory(definition)
    inventory_ids = tuple(str(item["configuration_id"]) for item in inventory)
    configuration_ids = tuple(
        str(_configuration_value(item, "configuration_id"))
        for item in configurations
    )
    historical_ids = tuple(
        str(
            _configuration_value(
                item,
                "historical_reference_executable_id",
            )
        )
        for item in configurations
    )
    if (
        configuration_ids != inventory_ids
        or historical_ids
        != tuple(
            str(item["historical_reference_executable_id"])
            for item in inventory
        )
    ):
        raise ValueError("fixed-hold configuration inventory drifted")
    executable_by_configuration = {
        str(item["configuration_id"]): str(item["executable_id"])
        for item in inventory
    }

    _validate_engine_environment()
    data = load_observed_development(root)
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = spread_builder(
        frame["spread"].to_numpy(float),
        _time_ns(frame),
    )
    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    windows: list[dict[str, object]] = []
    for fold in folds:
        fold_id = str(fold["fold_id"])
        test = fold["test_oos"]
        prefix_end = int(
            time.searchsorted(pd.Timestamp(test["end"]), side="right")
        )
        prefix_frame = frame.iloc[:prefix_end]
        prefix_frames[fold_id] = prefix_frame
        prefix_spreads[fold_id] = spread_builder(
            prefix_frame["spread"].to_numpy(float),
            _time_ns(prefix_frame),
        )
        eligible_dates = tuple(
            sorted(
                pd.DatetimeIndex(
                    time[
                        (time >= pd.Timestamp(test["start"]))
                        & (time <= pd.Timestamp(test["end"]))
                    ]
                )
                .normalize()
                .strftime("%Y-%m-%d")
                .unique()
            )
        )
        windows.append(
            {
                "eligible_dates": list(eligible_dates),
                "fold_id": fold_id,
                "test_end": _iso(test["end"]),
                "test_start": _iso(test["start"]),
                "train_end": _iso(fold["train_is"]["end"]),
                "train_start": _iso(fold["train_is"]["start"]),
            }
        )

    features: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefixes: dict[
        str, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]
    ] = {}
    calibrations: dict[
        str, dict[str, tuple[float, tuple[float, float], float]]
    ] = {}
    comparisons: list[dict[str, object]] = []
    for profile in definition.invariance_keys:
        full = feature_builder(frame, profile)
        features[profile] = full
        prefixes[profile] = {}
        calibrations[profile] = {}
        for fold in folds:
            fold_id = str(fold["fold_id"])
            train = fold["train_is"]
            train_start = pd.Timestamp(train["start"])
            train_end = pd.Timestamp(train["end"])
            train_mask = (
                (time >= train_start) & (time <= train_end)
            ).to_numpy()
            volatility = full[1][train_mask & np.isfinite(full[1])]
            if not len(volatility):
                raise RuntimeError("fixed-hold volatility calibration is empty")
            prefix_frame = prefix_frames[fold_id]
            prefix = feature_builder(prefix_frame, profile)
            prefixes[profile][fold_id] = prefix
            prefix_time = pd.to_datetime(prefix_frame["time"], errors="raise")
            prefix_mask = (
                (prefix_time >= train_start) & (prefix_time <= train_end)
            ).to_numpy()
            calibrations[profile][fold_id] = (
                selector_calibrator(full[0], train_mask),
                (
                    float(np.quantile(volatility, 1 / 3, method="higher")),
                    float(np.quantile(volatility, 2 / 3, method="higher")),
                ),
                selector_calibrator(prefix[0], prefix_mask),
            )
            compared = len(prefix[0])
            comparisons.append(
                {
                    "compared_row_count": compared,
                    "fold_id": fold_id,
                    "full_feature_values_sha256": _score_digest(
                        full[0][:compared]
                    ),
                    "invariance_key": profile,
                    "prefix_feature_values_sha256": _score_digest(prefix[0]),
                }
            )
    comparisons.sort(
        key=lambda item: (
            str(item["fold_id"]),
            str(item["invariance_key"]),
        )
    )

    results: dict[str, Any] = {}
    captures_by_configuration: dict[
        str, dict[tuple[str, str], Any]
    ] = {}
    raw_metrics: dict[str, dict[str, int]] = {}
    for configuration in configurations:
        configuration_id = str(
            _configuration_value(configuration, "configuration_id")
        )
        profile = str(_configuration_value(configuration, "profile"))
        executable_id = executable_by_configuration[configuration_id]
        captures: dict[tuple[str, str], Any] = {}

        def capture_simulation(**kwargs: Any) -> Any:
            simulation = simulate_fixed_hold(**kwargs)
            fold_id = str(kwargs["fold_id"])
            scope = "full" if kwargs["frame"] is frame else "prefix"
            key = (fold_id, scope)
            if key in captures:
                raise RuntimeError("fixed-hold simulation capture duplicated")
            captures[key] = simulation
            return simulation

        result = _evaluate_configuration(
            calibrations=calibrations[profile],
            configuration=configuration,
            effective_spread=spread,
            executable_id=executable_id,
            features=features[profile],
            folds=folds,
            frame=frame,
            prefix_features=prefixes[profile],
            prefix_spreads=prefix_spreads,
            simulation_fn=capture_simulation,
            time=time,
        )
        expected_capture_keys = {
            (str(fold["fold_id"]), scope)
            for fold in folds
            for scope in ("full", "prefix")
        }
        if set(captures) != expected_capture_keys:
            raise RuntimeError("fixed-hold simulation capture is incomplete")
        results[configuration_id] = result
        captures_by_configuration[configuration_id] = captures
        raw_metrics[executable_id] = dict(result.metrics)

    if raw_parity_validator is not None:
        raw_parity_validator(root, results)

    all_trades: list[dict[str, object]] = []
    all_intents: list[dict[str, object]] = []
    for configuration in configurations:
        configuration_id = str(
            _configuration_value(configuration, "configuration_id")
        )
        executable_id = executable_by_configuration[configuration_id]
        captures = captures_by_configuration[configuration_id]
        all_trades.extend(
            _trade_rows(
                configuration=configuration,
                executable_id=executable_id,
                simulations=captures,
                frame=frame,
            )
        )
        all_intents.extend(
            _intent_rows(
                configuration=configuration,
                executable_id=executable_id,
                simulations=captures,
                frame=frame,
            )
        )
    all_trades.sort(
        key=lambda item: (
            str(item["configuration_id"]),
            str(item["fold_id"]),
            str(item["decision_time"]),
            str(item["observation_id"]),
        )
    )
    all_intents.sort(
        key=lambda item: (
            str(item["configuration_id"]),
            str(item["fold_id"]),
            str(item["scope"]),
            int(item["ordinal"]),
            str(item["observation_id"]),
        )
    )
    aggregates: dict[tuple[str, str, str], list[int]] = {}
    for trade in all_trades:
        key = (
            str(trade["configuration_id"]),
            str(trade["fold_id"]),
            str(trade["decision_time"])[:10],
        )
        values = aggregates.setdefault(key, [0, 0, 0])
        values[0] += 1
        values[1] += int(trade["native_net_pnl_micropoints"])
        values[2] += int(trade["stress_net_pnl_micropoints"])
    by_configuration = {
        str(item["configuration_id"]): item for item in inventory
    }
    eligible_rows: list[dict[str, object]] = []
    for configuration_id in sorted(by_configuration):
        member = by_configuration[configuration_id]
        for window in windows:
            for day in window["eligible_dates"]:
                values = aggregates.get(
                    (configuration_id, str(window["fold_id"]), str(day)),
                    [0, 0, 0],
                )
                eligible_rows.append(
                    {
                        "configuration_id": configuration_id,
                        "date": day,
                        "entry_count": values[0],
                        "executable_id": member["executable_id"],
                        "fold_id": window["fold_id"],
                        "native_net_pnl_micropoints": values[1],
                        "stress_net_pnl_micropoints": values[2],
                    }
                )
    neutral = build_fixed_hold_family_trace(
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
        windows=windows,
        invariance_comparisons=comparisons,
        trade_observations=all_trades,
        intent_observations=all_intents,
        eligible_day_observations=eligible_rows,
    )
    return neutral, raw_metrics


__all__ = [
    "FeatureBuilder",
    "RawParityValidator",
    "SelectorCalibrator",
    "SpreadBuilder",
    "compute_fixed_hold_family_trace",
    "fixed_hold_trace_engine_implementation_sha256",
]
