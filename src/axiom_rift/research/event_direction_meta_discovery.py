"""Registered event-level direction meta-policy discovery surface."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import sklearn
from sklearn.tree import DecisionTreeClassifier

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.dense_short_synthesis_chassis import (
    calibrate_synthesis_selector,
    terminal_return_sign_12,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    DiscoveryBoundaryError,
    SimulationResult,
    _claim_limits,
    _evaluate_configuration,
    _fold_payloads,
    _paired_control_pvalue,
    _selection_adjusted_pvalues,
    _selection_method,
    _time_ns,
    _validate_engine_environment,
    _validate_fold_payloads,
    _validate_production_data,
    causal_effective_spread,
    execution_pnl,
)
from axiom_rift.research.event_direction_meta_chassis import (
    MODEL_MAX_DEPTH,
    MODEL_MIN_SAMPLES_LEAF,
    MODEL_RANDOM_SEED,
    SELECTION_TOTAL_EXPOSURES,
    EventDirectionMetaConfiguration,
    apply_event_direction_actions,
    event_direction_meta_chassis_implementation_sha256,
    event_direction_meta_configurations,
    event_direction_meta_executable,
    executable_configuration_map,
    simulate_event_direction_meta_policy,
)
from axiom_rift.research.event_label_discovery import _raw_features
from axiom_rift.research.positive_direction_sleeve_discovery import (
    target_direction_score,
)
from axiom_rift.research.session_dense_positive_sleeve_chassis import (
    loader_implementation_sha256,
)
from axiom_rift.research.volatility_clock_label_chassis import fit_label_model
from axiom_rift.research.volatility_clock_label_discovery import deterministic_score


EVENT_STATE_FEATURE_NAMES = (
    "normalized_return_12",
    "normalized_return_48",
    "normalized_return_192",
    "path_efficiency_48",
    "volatility_ratio_48_192",
    "path_state_available",
    "router_score",
    "router_score_available",
    "target_score",
    "target_score_available",
    "volatility_tercile",
    "volatility_state_available",
    "slot_identity",
)
_THIS_FILE = Path(__file__).resolve()


def event_direction_meta_discovery_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _threshold(score: np.ndarray, mask: np.ndarray, quantile_bp: int) -> float:
    values = np.abs(score[mask & np.isfinite(score)])
    if len(values) < 1000:
        raise DiscoveryBoundaryError("event direction target selector is too small")
    return float(np.quantile(values, quantile_bp / 10000.0, method="higher"))


def _baseline_matrix(
    router_raw: np.ndarray,
    target_raw: np.ndarray,
    volatility: np.ndarray,
    router_threshold: float,
    target_threshold: float,
    cutoffs: tuple[float, float],
) -> np.ndarray:
    router = np.zeros(len(router_raw))
    selected = np.isfinite(router_raw) & (router_raw > 0)
    high = np.isfinite(volatility) & (volatility >= cutoffs[1])
    router[selected & high] = np.abs(router_raw[selected & high]) / router_threshold
    router[selected & ~high] = -np.abs(router_raw[selected & ~high]) / router_threshold
    target = np.divide(
        target_raw,
        target_threshold,
        out=np.full(len(target_raw), np.nan),
        where=np.isfinite(target_raw),
    )
    target[high] *= -1.0
    return np.column_stack((router, target))


def event_state_matrix(
    raw_features: np.ndarray,
    baseline_score: np.ndarray,
    volatility: np.ndarray,
    cutoffs: tuple[float, float],
    *,
    slot_index: int,
) -> np.ndarray:
    raw = np.asarray(raw_features, dtype=float)
    score = np.asarray(baseline_score, dtype=float)
    vol = np.asarray(volatility, dtype=float)
    if raw.shape != (len(score), 5) or score.ndim != 2 or score.shape[1] != 2:
        raise ValueError("event direction state inputs are invalid")
    if vol.shape != (len(score),) or slot_index not in (0, 1):
        raise ValueError("event direction state slot is invalid")
    raw_available = np.isfinite(raw).all(axis=1)
    raw_values = np.where(np.isfinite(raw), raw, 0.0)
    router_available = np.isfinite(score[:, 0])
    target_available = np.isfinite(score[:, 1])
    volatility_available = np.isfinite(vol)
    regime = np.zeros(len(score), dtype=float)
    regime[volatility_available & (vol <= cutoffs[0])] = -1.0
    regime[volatility_available & (vol >= cutoffs[1])] = 1.0
    values = np.column_stack(
        (
            raw_values,
            raw_available.astype(float),
            np.where(router_available, score[:, 0], 0.0),
            router_available.astype(float),
            np.where(target_available, score[:, 1], 0.0),
            target_available.astype(float),
            regime,
            volatility_available.astype(float),
            np.full(len(score), -1.0 if slot_index == 0 else 1.0),
        )
    )
    if values.shape[1] != len(EVENT_STATE_FEATURE_NAMES) or not np.isfinite(values).all():
        raise ValueError("event direction state encoding is not finite")
    return values


def _decision_indices(time: pd.Series, trades: pd.DataFrame) -> np.ndarray:
    values = pd.to_datetime(trades["decision_bar_open_time"], errors="raise")
    indices = time.searchsorted(values, side="left")
    if (
        len(indices) != len(values)
        or np.any(indices >= len(time))
        or not np.array_equal(time.iloc[indices].to_numpy(), values.to_numpy())
    ):
        raise DiscoveryBoundaryError("event direction training times do not align")
    return np.asarray(indices, dtype=np.int64)


def fit_event_direction_model(
    *,
    frame: pd.DataFrame,
    raw_features: np.ndarray,
    baseline_score: np.ndarray,
    volatility: np.ndarray,
    cutoffs: tuple[float, float],
    effective_spread: np.ndarray,
    training_simulation: SimulationResult,
) -> tuple[DecisionTreeClassifier, dict[str, int | str | list[str]]]:
    if sklearn.__version__ != "1.8.0":
        raise DiscoveryBoundaryError("event direction sklearn environment differs")
    trades = training_simulation.trades
    if len(trades) < 1000 or "slot" not in trades:
        raise DiscoveryBoundaryError("event direction training events are too small")
    time = pd.to_datetime(frame["time"], errors="raise")
    opens = pd.to_numeric(frame["open"], errors="raise").to_numpy(dtype=float)
    spread = np.asarray(effective_spread, dtype=float)
    indices = _decision_indices(time, trades)
    states = (
        event_state_matrix(
            raw_features,
            baseline_score,
            volatility,
            cutoffs,
            slot_index=0,
        ),
        event_state_matrix(
            raw_features,
            baseline_score,
            volatility,
            cutoffs,
            slot_index=1,
        ),
    )
    rows: list[np.ndarray] = []
    labels: list[int] = []
    for row_number, (_, trade) in enumerate(trades.iterrows()):
        slot = str(trade["slot"])
        slot_index = 0 if slot == "regime_router" else 1 if slot == "target_direction" else -1
        if slot_index < 0:
            raise DiscoveryBoundaryError("event direction training slot is unknown")
        decision_index = int(indices[row_number])
        holding_bars = 12 if slot_index == 0 else 6
        entry_index = decision_index + 1
        exit_index = entry_index + holding_bars
        follow_direction = int(trade["direction"])
        if exit_index >= len(frame) or follow_direction not in (-1, 1):
            raise DiscoveryBoundaryError("event direction training lifecycle differs")
        reverse_native, _ = execution_pnl(
            direction=-follow_direction,
            entry_bid=float(opens[entry_index]),
            exit_bid=float(opens[exit_index]),
            entry_spread_points=float(spread[entry_index]),
            exit_spread_points=float(spread[exit_index]),
        )
        follow_native = float(trade["pnl"])
        labels.append(1 if follow_native >= reverse_native else -1)
        rows.append(states[slot_index][decision_index])
    x = np.vstack(rows)
    y = np.asarray(labels, dtype=np.int8)
    model = DecisionTreeClassifier(
        criterion="log_loss",
        max_depth=MODEL_MAX_DEPTH,
        min_samples_leaf=MODEL_MIN_SAMPLES_LEAF,
        random_state=MODEL_RANDOM_SEED,
    )
    model.fit(x, y)
    used_indices = sorted(
        {int(index) for index in model.tree_.feature if int(index) >= 0}
    )
    diagnostics: dict[str, int | str | list[str]] = {
        "class_follow_count": int((y == 1).sum()),
        "class_reverse_count": int((y == -1).sum()),
        "criterion": "log_loss",
        "feature_count": int(x.shape[1]),
        "leaf_count": int(model.get_n_leaves()),
        "max_depth_observed": int(model.get_depth()),
        "train_event_count": int(len(y)),
        "used_features": [EVENT_STATE_FEATURE_NAMES[index] for index in used_indices],
    }
    return model, diagnostics


def _predict_actions(
    model: DecisionTreeClassifier,
    raw_features: np.ndarray,
    baseline_score: np.ndarray,
    volatility: np.ndarray,
    cutoffs: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray]:
    actions: list[np.ndarray] = []
    for slot_index in (0, 1):
        state = event_state_matrix(
            raw_features,
            baseline_score,
            volatility,
            cutoffs,
            slot_index=slot_index,
        )
        action = np.asarray(model.predict(state), dtype=np.int8)
        if action.shape != (len(baseline_score),) or not np.isin(action, (-1, 1)).all():
            raise DiscoveryBoundaryError("event direction model abstained")
        actions.append(action)
    return actions[0], actions[1]


def _mismatch_count(left: Sequence[tuple[Any, ...]], right: Sequence[tuple[Any, ...]]) -> int:
    return abs(len(left) - len(right)) + sum(
        left_item != right_item
        for left_item, right_item in zip(left, right, strict=False)
    )


def _intent_schedule(simulation: SimulationResult) -> tuple[tuple[Any, ...], ...]:
    values: list[tuple[Any, ...]] = []
    for row in simulation.intent_rows:
        if len(row) != 6:
            raise DiscoveryBoundaryError("event direction intent schema differs")
        values.append((row[0], row[1], row[2], row[3], row[5]))
    return tuple(values)


def _trade_schedule(simulation: SimulationResult) -> tuple[tuple[Any, ...], ...]:
    if simulation.trades.empty:
        return ()
    return tuple(
        tuple(row)
        for row in simulation.trades.loc[
            :, ("decision_time", "entry_time", "exit_time", "slot")
        ].itertuples(index=False, name=None)
    )


def _matched(results: list[Any], profile: str) -> Any:
    found = [result for result in results if result.configuration.profile == profile]
    if len(found) != 1:
        raise DiscoveryBoundaryError("event direction control is not unique")
    return found[0]


def _populate_control_metrics(results: list[Any]) -> None:
    control = _matched(results, "stu0092_fixed_direction_control")
    for result in results:
        result.metrics["stu0092_control_delta_net_profit_micropoints"] = (
            result.metrics["net_profit_micropoints"]
            - control.metrics["net_profit_micropoints"]
        )
        result.metrics["stu0092_control_pvalue_upper_ppm"] = (
            1_000_000
            if result is control
            else _paired_control_pvalue(
                result,
                control,
                role="exact_stu0092_control",
                total_exposures=SELECTION_TOTAL_EXPOSURES,
            )
        )


def compute_registered_event_direction_meta_surface(
    repository_root: str | Path,
) -> dict[str, Any]:
    _validate_engine_environment()
    if sklearn.__version__ != "1.8.0":
        raise DiscoveryBoundaryError("event direction sklearn environment differs")
    data = load_observed_development(Path(repository_root).resolve())
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = causal_effective_spread(
        frame["spread"].to_numpy(float), _time_ns(frame)
    )
    raw_features, volatility, run = _raw_features(frame)
    router_label = terminal_return_sign_12(frame, run)
    target_raw = target_direction_score(frame, run)

    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_raw: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        prefix_end = int(
            time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]), side="right")
        )
        prefix = frame.iloc[:prefix_end]
        prefix_frames[fold_id] = prefix
        prefix_raw[fold_id] = _raw_features(prefix)
        prefix_spreads[fold_id] = causal_effective_spread(
            prefix["spread"].to_numpy(float), _time_ns(prefix)
        )

    control_fold_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    subject_fold_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    control_prefix_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    subject_prefix_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    calibrations: dict[str, tuple[float, tuple[float, float], float]] = {}
    model_diagnostics: list[dict[str, Any]] = []

    for fold in folds:
        fold_id = str(fold["fold_id"])
        train_start = pd.Timestamp(fold["train_is"]["start"])
        train_end = pd.Timestamp(fold["train_is"]["end"])
        selector_mask = ((time >= train_start) & (time <= train_end)).to_numpy()
        train_mask = selector_mask & (
            time.shift(-13) <= train_end
        ).fillna(False).to_numpy()
        router_model = fit_label_model(
            features=raw_features,
            label=router_label,
            train_mask=train_mask,
        )
        router_raw = deterministic_score(raw_features, router_model)
        router_threshold = calibrate_synthesis_selector(
            router_raw, selector_mask, 7000
        )
        target_threshold = _threshold(target_raw, selector_mask, 9000)
        values = volatility[train_mask & np.isfinite(volatility)]
        cutoffs = (
            float(np.quantile(values, 1 / 3, method="higher")),
            float(np.quantile(values, 2 / 3, method="higher")),
        )
        baseline = _baseline_matrix(
            router_raw,
            target_raw,
            volatility,
            router_threshold,
            target_threshold,
            cutoffs,
        )
        training_simulation = simulate_event_direction_meta_policy(
            frame=frame,
            score=baseline,
            volatility=volatility,
            run=run,
            threshold=1.0,
            configuration=event_direction_meta_configurations()[0],
            test_start=train_start,
            test_end=train_end,
            fold_id=f"{fold_id}_train",
            regime_cutoffs=cutoffs,
            effective_spread=spread,
        )
        event_model, diagnostics = fit_event_direction_model(
            frame=frame,
            raw_features=raw_features,
            baseline_score=baseline,
            volatility=volatility,
            cutoffs=cutoffs,
            effective_spread=spread,
            training_simulation=training_simulation,
        )
        router_actions, target_actions = _predict_actions(
            event_model, raw_features, baseline, volatility, cutoffs
        )
        subject = apply_event_direction_actions(
            baseline, router_actions, target_actions
        )

        prefix = prefix_frames[fold_id]
        prefix_features, prefix_volatility, prefix_run = prefix_raw[fold_id]
        prefix_time = pd.to_datetime(prefix["time"], errors="raise")
        prefix_selector_mask = (
            (prefix_time >= train_start) & (prefix_time <= train_end)
        ).to_numpy()
        prefix_router_raw = deterministic_score(prefix_features, router_model)
        prefix_target_raw = target_direction_score(prefix, prefix_run)
        prefix_router_threshold = calibrate_synthesis_selector(
            prefix_router_raw, prefix_selector_mask, 7000
        )
        prefix_target_threshold = _threshold(
            prefix_target_raw, prefix_selector_mask, 9000
        )
        if (
            router_threshold != prefix_router_threshold
            or target_threshold != prefix_target_threshold
        ):
            raise DiscoveryBoundaryError("event direction baseline threshold drifted")
        prefix_baseline = _baseline_matrix(
            prefix_router_raw,
            prefix_target_raw,
            prefix_volatility,
            prefix_router_threshold,
            prefix_target_threshold,
            cutoffs,
        )
        prefix_router_actions, prefix_target_actions = _predict_actions(
            event_model,
            prefix_features,
            prefix_baseline,
            prefix_volatility,
            cutoffs,
        )
        prefix_subject = apply_event_direction_actions(
            prefix_baseline, prefix_router_actions, prefix_target_actions
        )

        control_fold_scores[fold_id] = (baseline, volatility, run)
        subject_fold_scores[fold_id] = (subject, volatility, run)
        control_prefix_scores[fold_id] = (
            prefix_baseline,
            prefix_volatility,
            prefix_run,
        )
        subject_prefix_scores[fold_id] = (
            prefix_subject,
            prefix_volatility,
            prefix_run,
        )
        calibrations[fold_id] = (1.0, cutoffs, 1.0)
        model_diagnostics.append({"fold_id": fold_id, **diagnostics})

    configurations = event_direction_meta_configurations()
    score_sets = (control_fold_scores, subject_fold_scores)
    prefix_sets = (control_prefix_scores, subject_prefix_scores)
    results: list[Any] = []
    for configuration, fold_scores, prefix_scores in zip(
        configurations, score_sets, prefix_sets, strict=True
    ):
        first = fold_scores[str(folds[0]["fold_id"])]
        results.append(
            _evaluate_configuration(
                calibrations=calibrations,
                frame=frame,
                features=first,
                fold_features=fold_scores,
                folds=folds,
                configuration=configuration,
                effective_spread=spread,
                prefix_features=prefix_scores,
                prefix_spreads=prefix_spreads,
                time=time,
                executable_id=event_direction_meta_executable(configuration).identity,
                simulation_fn=simulate_event_direction_meta_policy,
            )
        )

    control_result, subject_result = results
    intent_mismatches = 0
    trade_mismatches = 0
    event_count_delta_abs = 0
    slot_hold_mismatches = 0
    follow_count = 0
    reverse_count = 0
    fold_policy: list[dict[str, int | str]] = []
    for fold in folds:
        fold_id = str(fold["fold_id"])
        test_start = pd.Timestamp(fold["test_oos"]["start"])
        test_end = pd.Timestamp(fold["test_oos"]["end"])
        cutoffs = calibrations[fold_id][1]
        control_simulation = simulate_event_direction_meta_policy(
            frame=frame,
            score=control_fold_scores[fold_id][0],
            volatility=volatility,
            run=run,
            threshold=1.0,
            configuration=configurations[0],
            test_start=test_start,
            test_end=test_end,
            fold_id=fold_id,
            regime_cutoffs=cutoffs,
            effective_spread=spread,
        )
        subject_simulation = simulate_event_direction_meta_policy(
            frame=frame,
            score=subject_fold_scores[fold_id][0],
            volatility=volatility,
            run=run,
            threshold=1.0,
            configuration=configurations[1],
            test_start=test_start,
            test_end=test_end,
            fold_id=fold_id,
            regime_cutoffs=cutoffs,
            effective_spread=spread,
        )
        intent_mismatches += _mismatch_count(
            _intent_schedule(control_simulation),
            _intent_schedule(subject_simulation),
        )
        control_schedule = _trade_schedule(control_simulation)
        subject_schedule = _trade_schedule(subject_simulation)
        trade_mismatches += _mismatch_count(control_schedule, subject_schedule)
        event_count_delta_abs += abs(
            len(control_simulation.trades) - len(subject_simulation.trades)
        )
        fold_follow = 0
        fold_reverse = 0
        if control_schedule == subject_schedule:
            control_directions = control_simulation.trades["direction"].to_numpy(int)
            subject_directions = subject_simulation.trades["direction"].to_numpy(int)
            fold_follow = int((control_directions == subject_directions).sum())
            fold_reverse = int((control_directions == -subject_directions).sum())
            if fold_follow + fold_reverse != len(control_directions):
                raise DiscoveryBoundaryError("event direction action is not binary")
        follow_count += fold_follow
        reverse_count += fold_reverse
        for _, trade in subject_simulation.trades.iterrows():
            expected = pd.Timedelta(
                minutes=60 if trade["slot"] == "regime_router" else 30
            )
            slot_hold_mismatches += int(
                pd.Timestamp(trade["exit_time"])
                - pd.Timestamp(trade["entry_time"])
                != expected
            )
        fold_policy.append(
            {
                "fold_id": fold_id,
                "follow_event_count": fold_follow,
                "reverse_event_count": fold_reverse,
                "trade_count": int(len(subject_simulation.trades)),
            }
        )

    invariant_metrics = {
        "direction_action_missing_count": 0,
        "event_count_delta_abs": event_count_delta_abs,
        "event_schedule_mismatch_count": intent_mismatches,
        "executed_event_schedule_mismatch_count": trade_mismatches,
        "slot_hold_mismatch_count": slot_hold_mismatches,
    }
    control_result.metrics.update(
        {
            "baseline_trade_count": control_result.metrics["trade_count"],
            "direction_action_missing_count": 0,
            "event_count_delta_abs": 0,
            "event_direction_follow_count": control_result.metrics["trade_count"],
            "event_direction_reversal_count": 0,
            "event_direction_reversal_rate_ppm": 0,
            "event_schedule_mismatch_count": 0,
            "executed_event_schedule_mismatch_count": 0,
            "slot_hold_mismatch_count": 0,
        }
    )
    subject_result.metrics.update(
        {
            **invariant_metrics,
            "baseline_trade_count": control_result.metrics["trade_count"],
            "event_direction_follow_count": follow_count,
            "event_direction_reversal_count": reverse_count,
            "event_direction_reversal_rate_ppm": (
                0
                if follow_count + reverse_count == 0
                else int(
                    round(
                        1_000_000 * reverse_count / (follow_count + reverse_count)
                    )
                )
            ),
        }
    )
    adjusted = _selection_adjusted_pvalues(
        results, total_exposures=SELECTION_TOTAL_EXPOSURES
    )
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = adjusted[result.executable_id]
    _populate_control_metrics(results)

    surface = {
        "claim_limits": _claim_limits()
        + [
            "label_model_trade_and_synthesis_are_the_only_changed_layers",
            "control_reuses_the_exact_STU_0092_executable",
            "subject_uses_one_fixed_depth_three_tree_without_a_grid",
            "model_fits_only_executed_fold_train_events_and_slot_horizon_labels",
            "every_event_receives_follow_or_reverse_and_never_abstains",
            "event_timestamps_slot_lot_execution_and_holds_are_invariant",
            "selectors_cutoffs_session_and_underlying_sleeves_are_unchanged",
            "development_only_no_confirmation_holdout_or_live_authority",
            "two_executable_surface_one_new_trial",
        ],
        "dataset_sha256": DATASET_SHA256,
        "evaluations": [
            {
                "direction_metrics": result.direction_metrics,
                "evaluable": all(
                    result.metrics[name] == 0
                    for name in (
                        "unknown_cost_unresolved_signal_count",
                        "causality_violation_count",
                        "nonfinite_metric_count",
                        "prefix_invariance_mismatch_count",
                        "append_invariance_mismatch_count",
                    )
                ),
                "fold_metrics": result.fold_metrics,
                "metrics": dict(sorted(result.metrics.items())),
                "regime_metrics": result.regime_metrics,
                "session_metrics": result.session_metrics,
                "subject_configuration_id": result.configuration.configuration_id,
                "subject_executable_id": result.executable_id,
            }
            for result in results
        ],
        "event_direction_meta_chassis_implementation_sha256": (
            event_direction_meta_chassis_implementation_sha256()
        ),
        "event_direction_meta_discovery_implementation_sha256": (
            event_direction_meta_discovery_implementation_sha256()
        ),
        "event_state_feature_names": list(EVENT_STATE_FEATURE_NAMES),
        "fold_event_policy": fold_policy,
        "loader_implementation_sha256": loader_implementation_sha256(),
        "material_identity": OBSERVED_MATERIAL_ID,
        "model_diagnostics": model_diagnostics,
        "schema": "event_direction_meta_surface.v1",
        "selection_context": [
            {
                "configuration_id": result.configuration.configuration_id,
                "executable_id": result.executable_id,
                "net_profit_micropoints": result.metrics[
                    "net_profit_micropoints"
                ],
                "selection_aware_pvalue_ppm": result.metrics[
                    "selection_aware_pvalue_ppm"
                ],
            }
            for result in results
        ],
        "selection_method": _selection_method(SELECTION_TOTAL_EXPOSURES),
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "sklearn_version": sklearn.__version__,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
    }
    canonical_bytes(surface)
    return surface


def project_event_direction_meta_evaluation(
    surface: Mapping[str, Any],
    *,
    job_execution: Mapping[str, str],
    subject_executable_id: str,
    surface_artifact_hash: str,
    surface_manifest_hash: str,
) -> dict[str, Any]:
    value = dict(surface)
    if (
        sha256(canonical_bytes(value)).hexdigest() != surface_artifact_hash
        or value.get("schema") != "event_direction_meta_surface.v1"
    ):
        raise DiscoveryBoundaryError("event direction meta surface is invalid")
    expected = executable_configuration_map()
    by_executable = {
        item.get("subject_executable_id"): item for item in value["evaluations"]
    }
    if set(by_executable) != set(expected) or subject_executable_id not in expected:
        raise DiscoveryBoundaryError("event direction meta subjects differ")
    payload = {
        name: job_execution[name]
        for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")
    }
    if job_execution.get("identity") != canonical_digest(
        domain="running-job-execution", payload=payload
    ):
        raise DiscoveryBoundaryError("event direction meta Job is invalid")
    result = {
        **dict(by_executable[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "event_direction_meta_evaluation.v1",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(result)
    return result


__all__ = [
    "EVENT_STATE_FEATURE_NAMES",
    "compute_registered_event_direction_meta_surface",
    "event_direction_meta_discovery_implementation_sha256",
    "event_state_matrix",
    "fit_event_direction_model",
    "project_event_direction_meta_evaluation",
]
