"""Legacy-preserving adapters for the six audited P0 axes.

The historical discovery surfaces omitted daily PnL.  These adapters compose
their existing calculation primitives without editing legacy implementation
files, then compare every replayed non-selection result to the immutable
historical evaluation artifact.  Only observed development material is read.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.research import (
    adjudication as adjudication_module,
    analog_state_discovery as analog_module,
    data as data_module,
    dense_short_synthesis_chassis as synthesis_chassis_module,
    discovery as discovery_module,
    event_label_discovery as event_label_module,
    high_vol_target_reversal_chassis as high_vol_chassis_module,
    high_vol_target_reversal_discovery as high_vol_module,
    positive_direction_sleeve_chassis as positive_chassis_module,
    positive_direction_sleeve_discovery as positive_module,
    p0_replay_inventory as replay_inventory_module,
    regime_direction_router_chassis as regime_chassis_module,
    regime_direction_router_discovery as regime_module,
    selection_inference as selection_module,
    three_way_regime_router_chassis as three_way_chassis_module,
    three_way_regime_router_discovery as three_way_module,
    validation_v2 as validation_v2_module,
    volatility_clock_label_chassis as volatility_chassis_module,
    volatility_clock_label_discovery as volatility_module,
)
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.dense_short_synthesis_chassis import (
    calibrate_synthesis_selector,
    terminal_return_sign_12,
)
from axiom_rift.research.discovery import (
    MICROPOINTS_PER_POINT,
    DiscoveryBoundaryError,
    _evaluate_configuration,
    _fold_payloads,
    _time_ns,
    _validate_engine_environment,
    _validate_fold_payloads,
    _validate_production_data,
    causal_effective_spread,
)
from axiom_rift.research.event_label_discovery import (
    HORIZON as VOLATILITY_CLOCK_HORIZON,
    _raw_features,
    calibrate_selector,
)
from axiom_rift.research.high_vol_target_reversal_chassis import (
    high_vol_target_reversal_configurations,
    simulate_high_vol_target_reversal,
)
from axiom_rift.research.high_vol_target_reversal_discovery import (
    _matrix as high_vol_matrix,
    _threshold as high_vol_threshold,
)
from axiom_rift.research.positive_direction_sleeve_chassis import (
    positive_direction_sleeve_configurations,
    simulate_positive_direction_sleeves,
)
from axiom_rift.research.positive_direction_sleeve_discovery import (
    _matrix as positive_matrix,
    _threshold as positive_threshold,
    target_direction_score,
)
from axiom_rift.research.p0_replay_inventory import load_p0_replay_inventory
from axiom_rift.research.regime_direction_router_chassis import (
    regime_direction_router_configurations,
    simulate_regime_direction_router,
)
from axiom_rift.research.selection_inference import (
    P0_REPLAY_EXECUTABLE_IDS,
)
from axiom_rift.research.three_way_regime_router_chassis import (
    simulate_three_way_regime_router,
    three_way_regime_router_configurations,
)
from axiom_rift.research.volatility_clock_label_chassis import (
    build_labels,
    fit_label_model,
    volatility_clock_label_configurations,
)
from axiom_rift.research.volatility_clock_label_discovery import (
    deterministic_score,
)


P0_AXIS_REPLAY_SCHEMA = "p0_axis_replay.v1"
_VALIDITY_METRICS = (
    "append_invariance_mismatch_count",
    "causality_violation_count",
    "nonfinite_metric_count",
    "prefix_invariance_mismatch_count",
    "unknown_cost_unresolved_signal_count",
)


class ForestReplayError(ValueError):
    """The replay input or historical binding is not exact."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ForestReplayError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ForestReplayError(f"{name} must be a lowercase SHA-256 digest")
    return text


@dataclass(frozen=True, slots=True)
class P0AxisSpec:
    study_id: str
    executable_id: str
    configuration_id: str
    adapter: str
    legacy_evaluation_sha256: str

    def __post_init__(self) -> None:
        _ascii("study_id", self.study_id)
        _ascii("executable_id", self.executable_id)
        _ascii("configuration_id", self.configuration_id)
        if self.adapter not in {
            "analog",
            "high_vol_target_reversal",
            "positive_direction_sleeve",
            "regime_direction_router",
            "three_way_regime_router",
            "volatility_clock_label",
        }:
            raise ForestReplayError("P0 adapter is not registered")
        _digest("legacy_evaluation_sha256", self.legacy_evaluation_sha256)

    def manifest(self) -> dict[str, str]:
        return {
            "adapter": self.adapter,
            "configuration_id": self.configuration_id,
            "executable_id": self.executable_id,
            "legacy_evaluation_sha256": self.legacy_evaluation_sha256,
            "study_id": self.study_id,
        }


P0_AXIS_SPECS = tuple(
    P0AxisSpec(**member) for member in load_p0_replay_inventory()
)


def forest_replay_adapter_dependency_paths() -> tuple[Path, ...]:
    """Return every implementation file that the replay calls directly."""

    modules = (
        data_module,
        discovery_module,
        adjudication_module,
        synthesis_chassis_module,
        event_label_module,
        analog_module,
        volatility_module,
        volatility_chassis_module,
        regime_module,
        regime_chassis_module,
        three_way_module,
        three_way_chassis_module,
        positive_module,
        positive_chassis_module,
        replay_inventory_module,
        high_vol_module,
        high_vol_chassis_module,
        selection_module,
        validation_v2_module,
    )
    return tuple(Path(module.__file__).resolve() for module in modules)


@dataclass(frozen=True, slots=True)
class AxisReplay:
    spec: P0AxisSpec
    evaluation: Mapping[str, Any]
    daily_pnl: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.spec, P0AxisSpec):
            raise ForestReplayError("axis replay requires a P0AxisSpec")
        canonical_bytes(dict(self.evaluation))
        if not self.daily_pnl:
            raise ForestReplayError("axis replay daily PnL is empty")
        dates = tuple(day for day, _ in self.daily_pnl)
        if dates != tuple(sorted(set(dates))):
            raise ForestReplayError("axis replay dates are not sorted and unique")
        if any(type(value) is not int for _, value in self.daily_pnl):
            raise ForestReplayError("axis replay PnL must use integer micropoints")
        metrics = self.evaluation.get("metrics")
        if not isinstance(metrics, Mapping):
            raise ForestReplayError("axis replay metrics are absent")
        if sum(value for _, value in self.daily_pnl) != metrics.get(
            "net_profit_micropoints"
        ):
            raise ForestReplayError("daily PnL does not sum to replay net profit")

    def daily_pnl_mapping(self) -> dict[str, int]:
        return dict(self.daily_pnl)

    def manifest(self) -> dict[str, Any]:
        return {
            "daily_pnl": {
                "date_count": len(self.daily_pnl),
                "first_date": self.daily_pnl[0][0],
                "last_date": self.daily_pnl[-1][0],
                "sum_micropoints": sum(value for _, value in self.daily_pnl),
            },
            "evaluation": dict(self.evaluation),
            "schema": P0_AXIS_REPLAY_SCHEMA,
            "source": self.spec.manifest(),
        }


@dataclass(slots=True)
class _ReplayContext:
    repository_root: Path
    frame: pd.DataFrame
    folds: tuple[dict[str, Any], ...]
    time: pd.Series
    spread: np.ndarray
    features: np.ndarray
    volatility: np.ndarray
    run: np.ndarray
    prefix_frames: dict[str, pd.DataFrame]
    prefix_raw: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]
    prefix_spreads: dict[str, np.ndarray]


@dataclass(slots=True)
class _RouterFold:
    score: np.ndarray
    prefix_score: np.ndarray
    target: np.ndarray
    prefix_target: np.ndarray
    mask: np.ndarray
    prefix_mask: np.ndarray
    threshold: float
    prefix_threshold: float
    cutoffs: tuple[float, float]


def _configuration(configurations: Sequence[Any], configuration_id: str) -> Any:
    found = [
        configuration
        for configuration in configurations
        if configuration.configuration_id == configuration_id
    ]
    if len(found) != 1:
        raise ForestReplayError("legacy configuration is not unique")
    return found[0]


def _build_context(repository_root: str | Path) -> _ReplayContext:
    root = Path(repository_root).resolve()
    _validate_engine_environment()
    data = load_observed_development(root)
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = causal_effective_spread(
        frame["spread"].to_numpy(float), _time_ns(frame)
    )
    features, volatility, run = _raw_features(frame)
    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_raw: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        end = int(
            time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]), side="right")
        )
        prefix = frame.iloc[:end]
        prefix_frames[fold_id] = prefix
        prefix_raw[fold_id] = _raw_features(prefix)
        prefix_spreads[fold_id] = causal_effective_spread(
            prefix["spread"].to_numpy(float), _time_ns(prefix)
        )
    return _ReplayContext(
        repository_root=root,
        frame=frame,
        folds=folds,
        time=time,
        spread=spread,
        features=features,
        volatility=volatility,
        run=run,
        prefix_frames=prefix_frames,
        prefix_raw=prefix_raw,
        prefix_spreads=prefix_spreads,
    )


def _router_folds(context: _ReplayContext) -> dict[str, _RouterFold]:
    labels = terminal_return_sign_12(context.frame, context.run)
    target = target_direction_score(context.frame, context.run)
    result: dict[str, _RouterFold] = {}
    for fold in context.folds:
        fold_id = str(fold["fold_id"])
        start = pd.Timestamp(fold["train_is"]["start"])
        end = pd.Timestamp(fold["train_is"]["end"])
        mask = ((context.time >= start) & (context.time <= end)).to_numpy()
        train = mask & (context.time.shift(-13) <= end).fillna(False).to_numpy()
        model = fit_label_model(
            features=context.features,
            label=labels,
            train_mask=train,
        )
        score = deterministic_score(context.features, model)
        threshold = calibrate_synthesis_selector(score, mask, 7_000)
        values = context.volatility[train & np.isfinite(context.volatility)]
        cutoffs = (
            float(np.quantile(values, 1 / 3, method="higher")),
            float(np.quantile(values, 2 / 3, method="higher")),
        )
        prefix = context.prefix_frames[fold_id]
        prefix_features, _, prefix_run = context.prefix_raw[fold_id]
        prefix_time = pd.to_datetime(prefix["time"], errors="raise")
        prefix_mask = ((prefix_time >= start) & (prefix_time <= end)).to_numpy()
        prefix_score = deterministic_score(prefix_features, model)
        prefix_threshold = calibrate_synthesis_selector(
            prefix_score, prefix_mask, 7_000
        )
        if threshold != prefix_threshold:
            raise DiscoveryBoundaryError("shared router threshold drifted")
        result[fold_id] = _RouterFold(
            score=score,
            prefix_score=prefix_score,
            target=target,
            prefix_target=target_direction_score(prefix, prefix_run),
            mask=mask,
            prefix_mask=prefix_mask,
            threshold=threshold,
            prefix_threshold=prefix_threshold,
            cutoffs=cutoffs,
        )
    return result


def _evaluate_router_axis(
    *,
    context: _ReplayContext,
    router_folds: Mapping[str, _RouterFold],
    spec: P0AxisSpec,
    configuration: Any,
    simulation_fn: Callable[..., Any],
    transform: Callable[
        [_ReplayContext, _RouterFold, str, Any],
        tuple[
            tuple[np.ndarray, np.ndarray, np.ndarray],
            tuple[np.ndarray, np.ndarray, np.ndarray],
            tuple[float, tuple[float, float], float],
        ],
    ],
) -> Any:
    fold_features: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_features: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    calibrations: dict[str, tuple[float, tuple[float, float], float]] = {}
    for fold in context.folds:
        fold_id = str(fold["fold_id"])
        fold_value, prefix_value, calibration = transform(
            context, router_folds[fold_id], fold_id, configuration
        )
        fold_features[fold_id] = fold_value
        prefix_features[fold_id] = prefix_value
        calibrations[fold_id] = calibration
    first = fold_features[str(context.folds[0]["fold_id"])]
    return _evaluate_configuration(
        calibrations=calibrations,
        frame=context.frame,
        features=first,
        fold_features=fold_features,
        folds=context.folds,
        configuration=configuration,
        effective_spread=context.spread,
        prefix_features=prefix_features,
        prefix_spreads=context.prefix_spreads,
        time=context.time,
        executable_id=spec.executable_id,
        simulation_fn=simulation_fn,
    )


def _raw_router_transform(
    context: _ReplayContext,
    value: _RouterFold,
    fold_id: str,
    configuration: Any,
) -> tuple[
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[float, tuple[float, float], float],
]:
    selector_quantile = getattr(configuration, "selector_quantile_bp", 7_000)
    if selector_quantile != 7_000:
        raise ForestReplayError("router selector differs from shared replay")
    prefix_volatility = context.prefix_raw[fold_id][1]
    prefix_run = context.prefix_raw[fold_id][2]
    return (
        (value.score, context.volatility, context.run),
        (value.prefix_score, prefix_volatility, prefix_run),
        (value.threshold, value.cutoffs, value.prefix_threshold),
    )


def _positive_transform(
    context: _ReplayContext,
    value: _RouterFold,
    fold_id: str,
    configuration: Any,
) -> tuple[
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[float, tuple[float, float], float],
]:
    del configuration
    threshold = positive_threshold(value.target, value.mask)
    prefix_threshold = positive_threshold(value.prefix_target, value.prefix_mask)
    if threshold != prefix_threshold:
        raise DiscoveryBoundaryError("positive direction threshold drifted")
    prefix_volatility = context.prefix_raw[fold_id][1]
    prefix_run = context.prefix_raw[fold_id][2]
    return (
        (
            positive_matrix(
                value.score,
                value.target,
                context.volatility,
                value.threshold,
                threshold,
                value.cutoffs,
            ),
            context.volatility,
            context.run,
        ),
        (
            positive_matrix(
                value.prefix_score,
                value.prefix_target,
                prefix_volatility,
                value.prefix_threshold,
                prefix_threshold,
                value.cutoffs,
            ),
            prefix_volatility,
            prefix_run,
        ),
        (1.0, value.cutoffs, 1.0),
    )


def _high_vol_transform(
    context: _ReplayContext,
    value: _RouterFold,
    fold_id: str,
    configuration: Any,
) -> tuple[
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[np.ndarray, np.ndarray, np.ndarray],
    tuple[float, tuple[float, float], float],
]:
    quantile = configuration.target_quantile_bp
    threshold = high_vol_threshold(value.target, value.mask, quantile)
    prefix_threshold = high_vol_threshold(
        value.prefix_target, value.prefix_mask, quantile
    )
    if threshold != prefix_threshold:
        raise DiscoveryBoundaryError("high volatility target threshold drifted")
    prefix_volatility = context.prefix_raw[fold_id][1]
    prefix_run = context.prefix_raw[fold_id][2]
    return (
        (
            high_vol_matrix(
                value.score,
                value.target,
                context.volatility,
                value.threshold,
                threshold,
                value.cutoffs,
            ),
            context.volatility,
            context.run,
        ),
        (
            high_vol_matrix(
                value.prefix_score,
                value.prefix_target,
                prefix_volatility,
                value.prefix_threshold,
                prefix_threshold,
                value.cutoffs,
            ),
            prefix_volatility,
            prefix_run,
        ),
        (1.0, value.cutoffs, 1.0),
    )


def _evaluate_volatility_clock(context: _ReplayContext, spec: P0AxisSpec) -> Any:
    configuration = _configuration(
        volatility_clock_label_configurations(), spec.configuration_id
    )
    labels = build_labels(context.frame, context.volatility, context.run)
    fold_features: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_features: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    calibrations: dict[str, tuple[float, tuple[float, float], float]] = {}
    for fold in context.folds:
        fold_id = str(fold["fold_id"])
        start = pd.Timestamp(fold["train_is"]["start"])
        end = pd.Timestamp(fold["train_is"]["end"])
        selector_mask = (
            (context.time >= start) & (context.time <= end)
        ).to_numpy()
        train_mask = selector_mask & (
            context.time.shift(-(VOLATILITY_CLOCK_HORIZON + 1)) <= end
        ).fillna(False).to_numpy()
        model = fit_label_model(
            features=context.features,
            label=labels[configuration.profile],
            train_mask=train_mask,
        )
        score = deterministic_score(context.features, model)
        fold_features[fold_id] = (score, context.volatility, context.run)
        prefix_raw = context.prefix_raw[fold_id]
        prefix_score = deterministic_score(prefix_raw[0], model)
        prefix_features[fold_id] = (
            prefix_score,
            prefix_raw[1],
            prefix_raw[2],
        )
        prefix_time = pd.to_datetime(
            context.prefix_frames[fold_id]["time"], errors="raise"
        )
        prefix_train = ((prefix_time >= start) & (prefix_time <= end)).to_numpy()
        values = context.volatility[
            train_mask & np.isfinite(context.volatility)
        ]
        cutoffs = (
            float(np.quantile(values, 1 / 3, method="higher")),
            float(np.quantile(values, 2 / 3, method="higher")),
        )
        calibrations[fold_id] = (
            calibrate_selector(score, selector_mask),
            cutoffs,
            calibrate_selector(prefix_score, prefix_train),
        )
    first = fold_features[str(context.folds[0]["fold_id"])]
    return _evaluate_configuration(
        calibrations=calibrations,
        frame=context.frame,
        features=first,
        fold_features=fold_features,
        folds=context.folds,
        configuration=configuration,
        effective_spread=context.spread,
        prefix_features=prefix_features,
        prefix_spreads=context.prefix_spreads,
        time=context.time,
        executable_id=spec.executable_id,
    )


def _evaluate_analog(context: _ReplayContext, spec: P0AxisSpec) -> Any:
    configuration = _configuration(
        analog_module.analog_configurations(), spec.configuration_id
    )
    fold_features: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_features: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    calibrations: dict[str, tuple[float, tuple[float, float], float]] = {}
    for fold in context.folds:
        fold_id = str(fold["fold_id"])
        start = pd.Timestamp(fold["train_is"]["start"])
        end = pd.Timestamp(fold["train_is"]["end"])
        value = analog_module.fit_fold_analog(
            context.frame, configuration.profile, start, end
        )
        prefix = analog_module.fit_fold_analog(
            context.prefix_frames[fold_id], configuration.profile, start, end
        )
        fold_features[fold_id] = value
        prefix_features[fold_id] = prefix
        mask = ((context.time >= start) & (context.time <= end)).to_numpy()
        prefix_time = pd.to_datetime(
            context.prefix_frames[fold_id]["time"], errors="raise"
        )
        prefix_mask = ((prefix_time >= start) & (prefix_time <= end)).to_numpy()
        volatility_values = value[1][mask & np.isfinite(value[1])]
        cutoffs = (
            float(np.quantile(volatility_values, 1 / 3, method="higher")),
            float(np.quantile(volatility_values, 2 / 3, method="higher")),
        )
        calibrations[fold_id] = (
            analog_module.calibrate_selector(value[0], mask),
            cutoffs,
            analog_module.calibrate_selector(prefix[0], prefix_mask),
        )
    first = fold_features[str(context.folds[0]["fold_id"])]
    return _evaluate_configuration(
        calibrations=calibrations,
        frame=context.frame,
        features=first,
        fold_features=fold_features,
        folds=context.folds,
        configuration=configuration,
        effective_spread=context.spread,
        prefix_features=prefix_features,
        prefix_spreads=context.prefix_spreads,
        time=context.time,
        executable_id=spec.executable_id,
    )


def _read_legacy_evaluation(root: Path, spec: P0AxisSpec) -> dict[str, Any]:
    path = (
        root
        / "local"
        / "evidence"
        / "sha256"
        / spec.legacy_evaluation_sha256[:2]
        / spec.legacy_evaluation_sha256
    )
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ForestReplayError("legacy evaluation artifact is absent") from exc
    if sha256(content).hexdigest() != spec.legacy_evaluation_sha256:
        raise ForestReplayError("legacy evaluation artifact hash differs")
    try:
        value = parse_canonical(content)
    except (TypeError, ValueError) as exc:
        raise ForestReplayError("legacy evaluation artifact is not canonical") from exc
    if (
        not isinstance(value, dict)
        or value.get("subject_executable_id") != spec.executable_id
        or value.get("subject_configuration_id") != spec.configuration_id
    ):
        raise ForestReplayError("legacy evaluation belongs to another axis")
    return value


def _axis_replay(
    *, root: Path, spec: P0AxisSpec, configuration_result: Any
) -> AxisReplay:
    evaluable = all(
        configuration_result.metrics[name] == 0 for name in _VALIDITY_METRICS
    )
    evaluation = {
        "direction_metrics": configuration_result.direction_metrics,
        "evaluable": evaluable,
        "fold_metrics": configuration_result.fold_metrics,
        "metrics": dict(sorted(configuration_result.metrics.items())),
        "regime_metrics": configuration_result.regime_metrics,
        "session_metrics": configuration_result.session_metrics,
        "subject_configuration_id": spec.configuration_id,
        "subject_executable_id": spec.executable_id,
    }
    legacy = _read_legacy_evaluation(root, spec)
    for name in (
        "direction_metrics",
        "evaluable",
        "fold_metrics",
        "regime_metrics",
        "session_metrics",
        "subject_configuration_id",
        "subject_executable_id",
    ):
        if legacy.get(name) != evaluation[name]:
            raise ForestReplayError(
                f"replayed {spec.study_id} {name} differs from legacy evidence"
            )
    legacy_metrics = legacy.get("metrics")
    if not isinstance(legacy_metrics, Mapping):
        raise ForestReplayError("legacy evaluation metrics are absent")
    expected_metrics = {
        name: legacy_metrics.get(name) for name in evaluation["metrics"]
    }
    if expected_metrics != evaluation["metrics"]:
        raise ForestReplayError(
            f"replayed {spec.study_id} metrics differ from legacy evidence"
        )
    daily_pnl = tuple(
        (
            timestamp.date().isoformat(),
            int(round(float(value) * MICROPOINTS_PER_POINT)),
        )
        for timestamp, value in configuration_result.daily_pnl.items()
    )
    return AxisReplay(spec=spec, evaluation=evaluation, daily_pnl=daily_pnl)


def replay_p0_axes(repository_root: str | Path) -> tuple[AxisReplay, ...]:
    """Recompute and legacy-bind the six exact P0 development axes."""

    context = _build_context(repository_root)
    router_folds = _router_folds(context)
    results: dict[str, Any] = {}
    by_adapter = {spec.adapter: spec for spec in P0_AXIS_SPECS}

    analog_spec = by_adapter["analog"]
    results[analog_spec.executable_id] = _evaluate_analog(context, analog_spec)

    volatility_spec = by_adapter["volatility_clock_label"]
    results[volatility_spec.executable_id] = _evaluate_volatility_clock(
        context, volatility_spec
    )

    regime_spec = by_adapter["regime_direction_router"]
    regime_configuration = _configuration(
        regime_direction_router_configurations(),
        regime_spec.configuration_id,
    )
    results[regime_spec.executable_id] = _evaluate_router_axis(
        context=context,
        router_folds=router_folds,
        spec=regime_spec,
        configuration=regime_configuration,
        simulation_fn=simulate_regime_direction_router,
        transform=_raw_router_transform,
    )

    three_way_spec = by_adapter["three_way_regime_router"]
    three_way_configuration = _configuration(
        three_way_regime_router_configurations(),
        three_way_spec.configuration_id,
    )
    results[three_way_spec.executable_id] = _evaluate_router_axis(
        context=context,
        router_folds=router_folds,
        spec=three_way_spec,
        configuration=three_way_configuration,
        simulation_fn=simulate_three_way_regime_router,
        transform=_raw_router_transform,
    )

    positive_spec = by_adapter["positive_direction_sleeve"]
    positive_configuration = _configuration(
        positive_direction_sleeve_configurations(),
        positive_spec.configuration_id,
    )
    results[positive_spec.executable_id] = _evaluate_router_axis(
        context=context,
        router_folds=router_folds,
        spec=positive_spec,
        configuration=positive_configuration,
        simulation_fn=simulate_positive_direction_sleeves,
        transform=_positive_transform,
    )

    high_vol_spec = by_adapter["high_vol_target_reversal"]
    high_vol_configuration = _configuration(
        high_vol_target_reversal_configurations(),
        high_vol_spec.configuration_id,
    )
    results[high_vol_spec.executable_id] = _evaluate_router_axis(
        context=context,
        router_folds=router_folds,
        spec=high_vol_spec,
        configuration=high_vol_configuration,
        simulation_fn=simulate_high_vol_target_reversal,
        transform=_high_vol_transform,
    )

    specs_by_id = {spec.executable_id: spec for spec in P0_AXIS_SPECS}
    return tuple(
        _axis_replay(
            root=context.repository_root,
            spec=specs_by_id[executable_id],
            configuration_result=results[executable_id],
        )
        for executable_id in P0_REPLAY_EXECUTABLE_IDS
    )



__all__ = [
    "AxisReplay",
    "ForestReplayError",
    "P0_AXIS_REPLAY_SCHEMA",
    "P0_AXIS_SPECS",
    "P0AxisSpec",
    "forest_replay_adapter_dependency_paths",
    "replay_p0_axes",
]
