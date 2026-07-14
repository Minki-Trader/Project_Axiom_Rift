"""Shared atomic-trace engine for fold-trained routed sleeve families.

This engine owns the common computation that historical composite-router and
composite-consensus modules duplicated.  Family adapters supply only their
feature, calibration, and routing functions; the engine computes each shared
surface once, captures every full and prefix simulation, verifies historical
raw parity, and emits the registered fixed-hold atomic trace.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import (
    _daily_series,
    _fold_payloads,
    _micropoints,
    _monthly_realized_exit_drawdown,
    _profit_factor,
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
)
from axiom_rift.research.fixed_hold_trace_engine import (
    _configuration_value,
    _intent_rows,
    _score_digest,
    _trade_rows,
)


FeatureBuilder = Callable[[pd.DataFrame], Any]
RouterCalibrator = Callable[
    [Any, np.ndarray],
    tuple[tuple[float, float], Mapping[str, float]],
]
ScoreRouter = Callable[..., np.ndarray]
SpreadBuilder = Callable[[np.ndarray, np.ndarray], np.ndarray]
RawParityValidator = Callable[[Path, Mapping[str, Any]], None]
_THIS_FILE = Path(__file__).resolve()


def routed_sleeve_trace_engine_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _iso(value: object) -> str:
    return pd.Timestamp(value).isoformat()


def _feature_arrays(features: object) -> tuple[np.ndarray, ...]:
    try:
        values = tuple(
            np.asarray(getattr(features, name), dtype=float)
            for name in (
                "volume",
                "reversion",
                "volatility_sleeve",
                "realized_volatility",
                "run",
            )
        )
    except AttributeError as exc:
        raise ValueError("routed sleeve feature surface is incomplete") from exc
    if len({len(value) for value in values}) != 1:
        raise ValueError("routed sleeve feature lengths differ")
    return values


@dataclass(slots=True)
class RoutedSleeveResult:
    configuration: object
    executable_id: str
    metrics: dict[str, int]
    fold_metrics: list[dict[str, int | str]]
    regime_metrics: list[dict[str, int | str]]
    session_metrics: list[dict[str, int | str]]
    direction_metrics: list[dict[str, int | str]]
    daily_pnl: pd.Series


def _raw_result(
    *,
    configuration: object,
    executable_id: str,
    folds: Sequence[Mapping[str, Any]],
    time: pd.Series,
    simulations: Mapping[tuple[str, str], Any],
    prefix_invariance_mismatch_count: int,
) -> RoutedSleeveResult:
    full = [simulations[(str(fold["fold_id"]), "full")] for fold in folds]
    fold_metrics: list[dict[str, int | str]] = []
    eligible_parts: list[pd.DatetimeIndex] = []
    append_mismatches = 0
    for fold, simulation in zip(folds, full, strict=True):
        fold_id = str(fold["fold_id"])
        pnl = simulation.trades["pnl"].to_numpy(dtype=float)
        fold_metrics.append(
            {
                "fold_id": fold_id,
                "net_profit_micropoints": _micropoints(float(pnl.sum())),
                "profit_factor_milli": _profit_factor(pnl),
                "stress_net_profit_micropoints": _micropoints(
                    float(simulation.trades["stress_pnl"].sum())
                ),
                "trade_count": int(len(simulation.trades)),
                "unresolved_cost_signal_count": (
                    simulation.unresolved_cost_signal_count
                ),
            }
        )
        test = fold["test_oos"]
        eligible_parts.append(
            pd.DatetimeIndex(
                time[
                    (time >= pd.Timestamp(test["start"]))
                    & (time <= pd.Timestamp(test["end"]))
                ]
            )
            .normalize()
            .unique()
        )
        prefix = simulations[(fold_id, "prefix")]
        left = simulation.intent_rows
        right = prefix.intent_rows
        append_mismatches += abs(len(left) - len(right)) + sum(
            one != two for one, two in zip(left, right, strict=False)
        )

    trades = pd.concat([item.trades for item in full], ignore_index=True)
    eligible_days = pd.DatetimeIndex(
        sorted(set().union(*(set(value) for value in eligible_parts)))
    )
    daily_pnl = _daily_series(trades, eligible_days, "pnl")
    daily_entries = (
        pd.Series(0, index=eligible_days, dtype=int)
        if trades.empty
        else trades.assign(
            day=pd.to_datetime(trades["decision_time"]).dt.normalize()
        )
        .groupby("day", sort=True)
        .size()
        .reindex(eligible_days, fill_value=0)
        .astype(int)
    )
    net = float(trades["pnl"].sum()) if not trades.empty else 0.0
    stress = float(trades["stress_pnl"].sum()) if not trades.empty else 0.0
    drawdown, drawdown_share = _monthly_realized_exit_drawdown(trades)
    positive_daily = daily_pnl[daily_pnl > 0].sort_values(ascending=False)
    gross_positive = float(positive_daily.sum())
    top5_share = (
        0
        if gross_positive <= 0
        else min(
            1_000_000,
            int(
                round(
                    1_000_000
                    * float(positive_daily.head(5).sum())
                    / gross_positive
                )
            ),
        )
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
                "net_profit_micropoints": _micropoints(
                    float(selected["pnl"].sum())
                ),
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
                [
                    hours.between(1, 7),
                    hours.between(8, 14),
                    hours.between(15, 22),
                ],
                ["broker_01_07", "broker_08_14", "broker_15_22"],
                default="broker_23_00",
            ),
            index=trades.index,
        )
        if not trades.empty
        else pd.Series(dtype=object)
    )
    session_metrics: list[dict[str, int | str]] = []
    for session in (
        "broker_01_07",
        "broker_08_14",
        "broker_15_22",
        "broker_23_00",
    ):
        selected = trades[labels == session] if not trades.empty else trades
        session_metrics.append(
            {
                "session": session,
                "net_profit_micropoints": _micropoints(
                    float(selected["pnl"].sum())
                ),
                "trade_count": int(len(selected)),
            }
        )

    direction_metrics: list[dict[str, int | str]] = []
    for direction, name in ((1, "long"), (-1, "short")):
        selected = trades[trades["direction"] == direction]
        direction_metrics.append(
            {
                "direction": name,
                "net_profit_micropoints": _micropoints(
                    float(selected["pnl"].sum())
                ),
                "trade_count": int(len(selected)),
            }
        )

    fold_pf = sorted(int(item["profit_factor_milli"]) for item in fold_metrics)
    unresolved = sum(item.unresolved_cost_signal_count for item in full)
    metrics = {
        "append_invariance_mismatch_count": append_mismatches,
        "causality_violation_count": sum(
            item.causality_violation_count for item in full
        ),
        "daily_entries_max_milli": (
            0 if daily_entries.empty else int(daily_entries.max()) * 1000
        ),
        "daily_entries_median_milli": (
            0
            if daily_entries.empty
            else int(round(1000 * float(daily_entries.median())))
        ),
        "daily_entries_p10_milli": (
            0
            if daily_entries.empty
            else int(
                round(
                    1000
                    * float(np.quantile(daily_entries, 0.10, method="lower"))
                )
            )
        ),
        "daily_entries_p90_milli": (
            0
            if daily_entries.empty
            else int(
                round(
                    1000
                    * float(np.quantile(daily_entries, 0.90, method="higher"))
                )
            )
        ),
        "eligible_day_count": int(len(eligible_days)),
        "entries_per_day_milli": (
            0
            if not len(eligible_days)
            else int(round(1000 * len(trades) / len(eligible_days)))
        ),
        "evaluable_folds": sum(
            int(item["trade_count"]) > 0 for item in fold_metrics
        ),
        "gap_excluded_signal_count": sum(
            item.gap_excluded_signal_count for item in full
        ),
        "median_fold_profit_factor_milli": (
            fold_pf[len(fold_pf) // 2] if fold_pf else 0
        ),
        "monthly_realized_exit_drawdown_micropoints": _micropoints(drawdown),
        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": (
            drawdown_share
        ),
        "net_profit_micropoints": _micropoints(net),
        "nonfinite_metric_count": 0,
        "positive_regime_count": sum(
            int(item["net_profit_micropoints"]) > 0
            for item in regime_metrics
        ),
        "prefix_invariance_mismatch_count": (
            prefix_invariance_mismatch_count
        ),
        "selection_aware_pvalue_ppm": 1_000_000,
        "stress_net_profit_micropoints": _micropoints(stress),
        "supported_positive_regime_count": sum(
            int(item["net_profit_micropoints"]) > 0
            and int(item["trade_count"]) >= 30
            and int(item["evaluable_fold_count"]) >= 5
            and int(item["winning_fold_count"]) >= 3
            and 2 * int(item["winning_fold_count"])
            > int(item["evaluable_fold_count"])
            for item in regime_metrics
        ),
        "top5_profit_day_share_ppm": top5_share,
        "trade_count": int(len(trades)),
        "unknown_cost_unresolved_signal_count": unresolved,
        "winning_fold_count": sum(
            int(item["net_profit_micropoints"]) > 0
            for item in fold_metrics
        ),
        "zero_entry_day_rate_ppm": (
            0
            if daily_entries.empty
            else int(
                round(
                    1_000_000
                    * int((daily_entries == 0).sum())
                    / len(daily_entries)
                )
            )
        ),
    }
    return RoutedSleeveResult(
        configuration=configuration,
        executable_id=executable_id,
        metrics=metrics,
        fold_metrics=fold_metrics,
        regime_metrics=regime_metrics,
        session_metrics=session_metrics,
        direction_metrics=direction_metrics,
        daily_pnl=daily_pnl,
    )


def compute_routed_sleeve_family_trace(
    repository_root: str | Path,
    *,
    definition: FixedHoldProtocolDefinition,
    configurations: tuple[object, ...],
    feature_builder: FeatureBuilder,
    router_calibrator: RouterCalibrator,
    score_router: ScoreRouter,
    spread_builder: SpreadBuilder,
    raw_parity_validator: RawParityValidator | None = None,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    """Compute one exact routed family without duplicated per-member features."""

    if not isinstance(definition, FixedHoldProtocolDefinition):
        raise TypeError("routed sleeve definition is not typed")
    if type(configurations) is not tuple or not configurations:
        raise ValueError("routed sleeve configurations are absent")
    for callback in (
        feature_builder,
        router_calibrator,
        score_router,
        spread_builder,
    ):
        if not callable(callback):
            raise TypeError("routed sleeve callback is not callable")
    if raw_parity_validator is not None and not callable(raw_parity_validator):
        raise TypeError("routed sleeve parity validator is not callable")

    root = Path(repository_root).resolve()
    inventory = expected_fixed_hold_family_inventory(definition)
    configuration_ids = tuple(
        str(_configuration_value(value, "configuration_id"))
        for value in configurations
    )
    historical_ids = tuple(
        str(_configuration_value(value, "historical_reference_executable_id"))
        for value in configurations
    )
    if configuration_ids != tuple(
        str(value["configuration_id"]) for value in inventory
    ) or historical_ids != tuple(
        str(value["historical_reference_executable_id"])
        for value in inventory
    ):
        raise ValueError("routed sleeve configuration inventory drifted")
    executable_by_configuration = {
        str(value["configuration_id"]): str(value["executable_id"])
        for value in inventory
    }

    _validate_engine_environment()
    data = load_observed_development(root)
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    features = feature_builder(frame)
    if len(_feature_arrays(features)[0]) != len(frame):
        raise ValueError("routed sleeve feature row count drifted")
    spread = spread_builder(frame["spread"].to_numpy(float), _time_ns(frame))

    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_features: dict[str, Any] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    windows: list[dict[str, object]] = []
    calibrations: dict[str, tuple[tuple[float, float], Mapping[str, float]]] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        train = fold["train_is"]
        test = fold["test_oos"]
        train_mask = (
            (time >= pd.Timestamp(train["start"]))
            & (time <= pd.Timestamp(train["end"]))
        ).to_numpy()
        calibrations[fold_id] = router_calibrator(features, train_mask)
        prefix_end = int(
            time.searchsorted(pd.Timestamp(test["end"]), side="right")
        )
        prefix_frame = frame.iloc[:prefix_end]
        prefix_frames[fold_id] = prefix_frame
        prefix_features[fold_id] = feature_builder(prefix_frame)
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
                "train_end": _iso(train["end"]),
                "train_start": _iso(train["start"]),
            }
        )

    routed: dict[tuple[str, str, str], np.ndarray] = {}
    mismatch_by_profile: dict[str, int] = {}
    comparisons: list[dict[str, object]] = []
    full_arrays = _feature_arrays(features)
    for profile in definition.invariance_keys:
        mismatches = 0
        for fold in folds:
            fold_id = str(fold["fold_id"])
            cutoffs, thresholds = calibrations[fold_id]
            full_score = score_router(
                features,
                profile=profile,
                volatility_cutoffs=cutoffs,
                sleeve_thresholds=thresholds,
            )
            prefix_score = score_router(
                prefix_features[fold_id],
                profile=profile,
                volatility_cutoffs=cutoffs,
                sleeve_thresholds=thresholds,
            )
            routed[(profile, fold_id, "full")] = full_score
            routed[(profile, fold_id, "prefix")] = prefix_score
            compared = len(prefix_score)
            for prefix_value, full_value in zip(
                _feature_arrays(prefix_features[fold_id])[:-1],
                full_arrays[:-1],
                strict=True,
            ):
                mismatches += int(
                    (~np.isclose(
                        prefix_value,
                        full_value[:compared],
                        rtol=0.0,
                        atol=0.0,
                        equal_nan=True,
                    )).sum()
                )
            mismatches += int(
                (~np.isclose(
                    prefix_score,
                    full_score[:compared],
                    rtol=0.0,
                    atol=0.0,
                    equal_nan=True,
                )).sum()
            )
            comparisons.append(
                {
                    "compared_row_count": compared,
                    "fold_id": fold_id,
                    "full_feature_values_sha256": _score_digest(
                        full_score[:compared]
                    ),
                    "invariance_key": profile,
                    "prefix_feature_values_sha256": _score_digest(
                        prefix_score
                    ),
                }
            )
        mismatch_by_profile[profile] = mismatches
    comparisons.sort(
        key=lambda value: (str(value["fold_id"]), str(value["invariance_key"]))
    )

    results: dict[str, RoutedSleeveResult] = {}
    captures_by_configuration: dict[str, dict[tuple[str, str], Any]] = {}
    raw_metrics: dict[str, dict[str, int]] = {}
    for configuration in configurations:
        configuration_id = str(
            _configuration_value(configuration, "configuration_id")
        )
        profile = str(_configuration_value(configuration, "profile"))
        executable_id = executable_by_configuration[configuration_id]
        captures: dict[tuple[str, str], Any] = {}
        for fold in folds:
            fold_id = str(fold["fold_id"])
            test = fold["test_oos"]
            cutoffs, _ = calibrations[fold_id]
            captures[(fold_id, "full")] = simulate_fixed_hold(
                frame=frame,
                score=routed[(profile, fold_id, "full")],
                volatility=full_arrays[3],
                run=full_arrays[4],
                threshold=1.0,
                configuration=configuration,
                test_start=pd.Timestamp(test["start"]),
                test_end=pd.Timestamp(test["end"]),
                fold_id=fold_id,
                regime_cutoffs=cutoffs,
                effective_spread=spread,
            )
            prefix_arrays = _feature_arrays(prefix_features[fold_id])
            captures[(fold_id, "prefix")] = simulate_fixed_hold(
                frame=prefix_frames[fold_id],
                score=routed[(profile, fold_id, "prefix")],
                volatility=prefix_arrays[3],
                run=prefix_arrays[4],
                threshold=1.0,
                configuration=configuration,
                test_start=pd.Timestamp(test["start"]),
                test_end=pd.Timestamp(test["end"]),
                fold_id=fold_id,
                regime_cutoffs=cutoffs,
                effective_spread=prefix_spreads[fold_id],
            )
        result = _raw_result(
            configuration=configuration,
            executable_id=executable_id,
            folds=folds,
            time=time,
            simulations=captures,
            prefix_invariance_mismatch_count=mismatch_by_profile[profile],
        )
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
        key=lambda value: (
            str(value["configuration_id"]),
            str(value["fold_id"]),
            str(value["decision_time"]),
            str(value["observation_id"]),
        )
    )
    all_intents.sort(
        key=lambda value: (
            str(value["configuration_id"]),
            str(value["fold_id"]),
            str(value["scope"]),
            int(value["ordinal"]),
            str(value["observation_id"]),
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
        str(value["configuration_id"]): value for value in inventory
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
    "RouterCalibrator",
    "RoutedSleeveResult",
    "ScoreRouter",
    "SpreadBuilder",
    "compute_routed_sleeve_family_trace",
    "routed_sleeve_trace_engine_implementation_sha256",
]
