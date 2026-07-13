"""One fixed USDJPY carry-unwind lifecycle contrast over STU-0092."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

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
    discovery_implementation_sha256,
)
from axiom_rift.research.event_label_discovery import _raw_features
from axiom_rift.research.high_vol_target_reversal_discovery import (
    _matrix,
    _threshold,
)
from axiom_rift.research.positive_direction_sleeve_discovery import (
    target_direction_score,
)
from axiom_rift.research.usdjpy_carry_exit_chassis import (
    CARRY_STATE_BARS,
    SELECTION_TOTAL_EXPOSURES,
    USDJPY_RAW_SHA256,
    executable_configuration_map,
    simulate_usdjpy_carry_exit,
    usdjpy_carry_exit_chassis_implementation_sha256,
    usdjpy_carry_exit_configurations,
    usdjpy_carry_exit_executable,
)
from axiom_rift.research.usdjpy_source import (
    USDJPY_COLUMNS,
    USDJPY_RAW_RELATIVE_PATH,
    usdjpy_source_contract,
)
from axiom_rift.research.volatility_clock_label_chassis import fit_label_model
from axiom_rift.research.volatility_clock_label_discovery import deterministic_score


DEVELOPMENT_END = pd.Timestamp("2026-04-30 23:55:00")
_TIME_FORMAT = "%Y.%m.%d %H:%M:%S"
_FIVE_MINUTES_NS = 300_000_000_000
_THIS_FILE = Path(__file__).resolve()


class USDJPYCarryExitBoundaryError(DiscoveryBoundaryError):
    pass


@dataclass(frozen=True, slots=True)
class USDJPYDevelopment:
    frame: pd.DataFrame
    raw_sha256: str
    prefix_sha256: str
    row_count: int


def usdjpy_carry_exit_discovery_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _record(raw: bytes) -> bytes:
    value = raw[:-1] if raw.endswith(b"\n") else raw
    value = value[:-1] if value.endswith(b"\r") else value
    if not value:
        raise USDJPYCarryExitBoundaryError("USDJPY source contains an empty row")
    return value


def _stamp(row: bytes) -> bytes:
    value, separator, _ = row.partition(b",")
    if not separator or len(value) != 19:
        raise USDJPYCarryExitBoundaryError("USDJPY timestamp field is invalid")
    try:
        parsed = pd.Timestamp(value.decode("ascii"))
    except (UnicodeError, ValueError) as exc:
        raise USDJPYCarryExitBoundaryError("USDJPY timestamp is invalid") from exc
    if parsed.second != 0 or parsed.minute % 5 != 0:
        raise USDJPYCarryExitBoundaryError("USDJPY timestamp is off the M5 grid")
    return value


def load_usdjpy_development(repository_root: str | Path) -> USDJPYDevelopment:
    root = Path(repository_root).resolve()
    path = (root / USDJPY_RAW_RELATIVE_PATH).resolve()
    if root not in path.parents or not path.is_file():
        raise USDJPYCarryExitBoundaryError("USDJPY raw snapshot is absent")
    boundary = DEVELOPMENT_END.strftime(_TIME_FORMAT).encode("ascii")
    expected_header = b",".join(value.encode("ascii") for value in USDJPY_COLUMNS)
    full_hash = sha256()
    prefix_hash = sha256()
    prefix = BytesIO()
    previous: bytes | None = None
    rows = 0
    saw_tail = False
    with path.open("rb") as handle:
        header = handle.readline()
        if _record(header) != expected_header:
            raise USDJPYCarryExitBoundaryError("USDJPY schema differs")
        full_hash.update(header)
        prefix_hash.update(header)
        prefix.write(header)
        for raw in handle:
            full_hash.update(raw)
            stamp = _stamp(_record(raw))
            if previous is not None and stamp <= previous:
                raise USDJPYCarryExitBoundaryError(
                    "USDJPY timestamps are not increasing"
                )
            previous = stamp
            if stamp <= boundary:
                if saw_tail:
                    raise USDJPYCarryExitBoundaryError(
                        "USDJPY development follows its tail"
                    )
                prefix_hash.update(raw)
                prefix.write(raw)
                rows += 1
            else:
                saw_tail = True
    if full_hash.hexdigest() != USDJPY_RAW_SHA256:
        raise USDJPYCarryExitBoundaryError("USDJPY raw SHA256 changed")
    if rows == 0 or not saw_tail:
        raise USDJPYCarryExitBoundaryError("USDJPY boundary is not exposed")
    prefix.seek(0)
    try:
        frame = pd.read_csv(
            prefix,
            usecols=["time", "close"],
            dtype={"time": "string", "close": "float64"},
            engine="c",
        )
    finally:
        prefix.close()
    frame["time"] = pd.to_datetime(
        frame["time"], format=_TIME_FORMAT, errors="raise"
    )
    close = frame["close"].to_numpy(dtype=float)
    if (
        len(frame) != rows
        or frame["time"].duplicated().any()
        or not frame["time"].is_monotonic_increasing
        or frame["time"].iloc[-1] != DEVELOPMENT_END
        or np.any(~np.isfinite(close))
        or np.any(close <= 0)
    ):
        raise USDJPYCarryExitBoundaryError(
            "USDJPY development prefix is invalid"
        )
    return USDJPYDevelopment(
        frame=frame,
        raw_sha256=full_hash.hexdigest(),
        prefix_sha256=prefix_hash.hexdigest(),
        row_count=rows,
    )


def source_carry_return(source_frame: pd.DataFrame) -> pd.Series:
    time = pd.to_datetime(source_frame["time"], errors="raise")
    close = pd.to_numeric(source_frame["close"], errors="raise").to_numpy(float)
    time_ns = time.to_numpy(dtype="datetime64[ns]").astype("int64")
    valid = np.isfinite(close) & (close > 0)
    run = np.zeros(len(source_frame), dtype=np.int32)
    for index in range(len(source_frame)):
        if not valid[index]:
            continue
        run[index] = (
            run[index - 1] + 1
            if index > 0
            and valid[index - 1]
            and time_ns[index] - time_ns[index - 1] == _FIVE_MINUTES_NS
            else 1
        )
    values = np.full(len(source_frame), np.nan)
    eligible = np.flatnonzero(run >= CARRY_STATE_BARS + 1)
    values[eligible] = (
        np.log(close[eligible]) - np.log(close[eligible - CARRY_STATE_BARS])
    )
    return pd.Series(values, index=pd.DatetimeIndex(time), name="carry_return")


def aligned_usdjpy_carry_return(
    target_frame: pd.DataFrame,
    source_frame: pd.DataFrame,
) -> np.ndarray:
    target_time = pd.to_datetime(target_frame["time"], errors="raise")
    state = source_carry_return(source_frame)
    return state.reindex(target_time).to_numpy(dtype=float)


def _matched(results: list[Any], profile: str) -> Any:
    found = [value for value in results if value.configuration.profile == profile]
    if len(found) != 1:
        raise USDJPYCarryExitBoundaryError("USDJPY carry-exit control is not unique")
    return found[0]


def _populate(results: list[Any]) -> None:
    control = _matched(results, "stu0092_fixed_lifecycle_control")
    for subject in results:
        subject.metrics["stu0092_control_delta_net_profit_micropoints"] = (
            subject.metrics["net_profit_micropoints"]
            - control.metrics["net_profit_micropoints"]
        )
        subject.metrics["stu0092_control_pvalue_upper_ppm"] = (
            1_000_000
            if subject is control
            else _paired_control_pvalue(
                subject,
                control,
                role="stu0092_fixed_lifecycle_control",
                total_exposures=SELECTION_TOTAL_EXPOSURES,
            )
        )


def _entry_rows(trades: pd.DataFrame) -> tuple[tuple[Any, ...], ...]:
    if trades.empty:
        return ()
    return tuple(
        tuple(row)
        for row in trades.loc[
            :, ("slot", "decision_time", "entry_time", "direction")
        ].itertuples(index=False, name=None)
    )


def _entry_identity_diagnostics(
    control_trades: pd.DataFrame,
    subject_trades: pd.DataFrame,
    subject_intent_rows: tuple[tuple[Any, ...], ...],
) -> dict[str, int]:
    """Classify only preregistered source-missing target drops as expected."""

    control = Counter(_entry_rows(control_trades))
    subject = Counter(_entry_rows(subject_trades))
    removed = control - subject
    added = subject - control
    no_entry_intents = Counter(
        (row[0], row[1], row[2], row[4])
        for row in subject_intent_rows
        if len(row) == 6
        and row[0] == "target_direction"
        and row[-1] == "source_state_missing_no_entry"
    )
    allowed_removed = removed & no_entry_intents
    unexpected_removed = removed - allowed_removed
    unmatched_intents = no_entry_intents - removed
    unexpected_count = sum(unexpected_removed.values()) + sum(added.values())
    return {
        "control_entry_count": sum(control.values()),
        "subject_entry_count": sum(subject.values()),
        "source_missing_no_entry_intent_count": sum(no_entry_intents.values()),
        "control_source_missing_no_entry_removal_count": sum(
            allowed_removed.values()
        ),
        "unmatched_source_missing_no_entry_intent_count": sum(
            unmatched_intents.values()
        ),
        "unexpected_control_entry_removal_count": sum(
            unexpected_removed.values()
        ),
        "unexpected_subject_entry_addition_count": sum(added.values()),
        "entry_identity_mismatch_count": unexpected_count,
    }


def _held_missing_state_safe_exit_count(trades: pd.DataFrame) -> int:
    if trades.empty or "carry_state_fail_closed" not in trades:
        return 0
    target = trades[trades["slot"] == "target_direction"]
    if target.empty:
        return 0
    return int(target["carry_state_fail_closed"].fillna(False).astype(bool).sum())


def _require_no_unexpected_entry_mismatch(
    diagnostics: Mapping[str, int],
) -> None:
    if diagnostics.get("entry_identity_mismatch_count") != 0:
        raise USDJPYCarryExitBoundaryError(
            "USDJPY lifecycle has an entry change outside preregistered "
            "source-missing no-entry drops: "
            f"removed={diagnostics.get('unexpected_control_entry_removal_count')}, "
            f"added={diagnostics.get('unexpected_subject_entry_addition_count')}"
        )


def compute_registered_usdjpy_carry_exit_surface(
    repository_root: str | Path,
) -> dict[str, Any]:
    _validate_engine_environment()
    root = Path(repository_root).resolve()
    data = load_observed_development(root)
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    source = load_usdjpy_development(root)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = causal_effective_spread(
        frame["spread"].to_numpy(float), _time_ns(frame)
    )
    features, volatility, run = _raw_features(frame)
    label = terminal_return_sign_12(frame, run)
    target = target_direction_score(frame, run)
    carry_return = aligned_usdjpy_carry_return(frame, source.frame)
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
    common: dict[str, tuple[Any, ...]] = {}
    prefix_common: dict[str, tuple[Any, ...]] = {}
    state_counts: list[dict[str, Any]] = []
    for fold in folds:
        fold_id = str(fold["fold_id"])
        train_start = pd.Timestamp(fold["train_is"]["start"])
        train_end = pd.Timestamp(fold["train_is"]["end"])
        mask = ((time >= train_start) & (time <= train_end)).to_numpy()
        train = mask & (time.shift(-13) <= train_end).fillna(False).to_numpy()
        model = fit_label_model(features=features, label=label, train_mask=train)
        router_raw = deterministic_score(features, model)
        router_threshold = calibrate_synthesis_selector(router_raw, mask, 7000)
        values = volatility[train & np.isfinite(volatility)]
        cutoffs = (
            float(np.quantile(values, 1 / 3, method="higher")),
            float(np.quantile(values, 2 / 3, method="higher")),
        )
        common[fold_id] = (
            router_raw,
            target,
            volatility,
            run,
            router_threshold,
            cutoffs,
            mask,
            carry_return,
        )
        prefix = prefix_frames[fold_id]
        raw = prefix_raw[fold_id]
        prefix_time = pd.to_datetime(prefix["time"], errors="raise")
        prefix_mask = (
            (prefix_time >= train_start) & (prefix_time <= train_end)
        ).to_numpy()
        prefix_router = deterministic_score(raw[0], model)
        prefix_target = target_direction_score(prefix, raw[2])
        prefix_router_threshold = calibrate_synthesis_selector(
            prefix_router, prefix_mask, 7000
        )
        if router_threshold != prefix_router_threshold:
            raise USDJPYCarryExitBoundaryError("router threshold drifted")
        prefix_common[fold_id] = (
            prefix_router,
            prefix_target,
            raw[1],
            raw[2],
            prefix_router_threshold,
            prefix_mask,
            carry_return[: len(prefix)],
        )
    results: list[Any] = []
    diagnostics = {
        "control_entry_count": 0,
        "subject_entry_count": 0,
        "source_missing_no_entry_intent_count": 0,
        "control_source_missing_no_entry_removal_count": 0,
        "unmatched_source_missing_no_entry_intent_count": 0,
        "unexpected_control_entry_removal_count": 0,
        "unexpected_subject_entry_addition_count": 0,
        "entry_identity_mismatch_count": 0,
        "held_missing_state_safe_exit_count": 0,
        "target_carry_early_exit_count": 0,
        "target_fixed_exit_count": 0,
    }
    for configuration in usdjpy_carry_exit_configurations():
        fold_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        prefix_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        calibrations: dict[str, tuple[float, tuple[float, float], float]] = {}
        for fold in folds:
            fold_id = str(fold["fold_id"])
            (
                router_raw,
                target_raw,
                fold_volatility,
                fold_run,
                router_threshold,
                cutoffs,
                mask,
                source_values,
            ) = common[fold_id]
            target_threshold = _threshold(
                target_raw, mask, configuration.target_quantile_bp
            )
            matrix = _matrix(
                router_raw,
                target_raw,
                fold_volatility,
                router_threshold,
                target_threshold,
                cutoffs,
            )
            fold_scores[fold_id] = (
                np.column_stack((matrix, source_values)),
                fold_volatility,
                fold_run,
            )
            (
                prefix_router,
                prefix_target,
                prefix_volatility,
                prefix_run,
                prefix_router_threshold,
                prefix_mask,
                prefix_source,
            ) = prefix_common[fold_id]
            prefix_target_threshold = _threshold(
                prefix_target, prefix_mask, configuration.target_quantile_bp
            )
            if target_threshold != prefix_target_threshold:
                raise USDJPYCarryExitBoundaryError("target threshold drifted")
            prefix_matrix = _matrix(
                prefix_router,
                prefix_target,
                prefix_volatility,
                prefix_router_threshold,
                prefix_target_threshold,
                cutoffs,
            )
            prefix_scores[fold_id] = (
                np.column_stack((prefix_matrix, prefix_source)),
                prefix_volatility,
                prefix_run,
            )
            calibrations[fold_id] = (1.0, cutoffs, 1.0)
            if configuration.uses_carry_exit:
                test_start = pd.Timestamp(fold["test_oos"]["start"])
                test_end = pd.Timestamp(fold["test_oos"]["end"])
                test = ((time >= test_start) & (time <= test_end)).to_numpy()
                selected = np.isfinite(target_raw) & (
                    np.abs(target_raw) >= target_threshold
                )
                high = np.isfinite(fold_volatility) & (
                    fold_volatility >= cutoffs[1]
                )
                state_counts.append(
                    {
                        "fold_id": fold_id,
                        "carry_unwind_selected_high_count": int(
                            np.sum(
                                test
                                & selected
                                & high
                                & np.isfinite(source_values)
                                & (source_values < 0)
                            )
                        ),
                        "carry_stable_selected_high_count": int(
                            np.sum(
                                test
                                & selected
                                & high
                                & np.isfinite(source_values)
                                & (source_values >= 0)
                            )
                        ),
                        "missing_selected_high_count": int(
                            np.sum(test & selected & high & ~np.isfinite(source_values))
                        ),
                    }
                )
                control_simulation = simulate_usdjpy_carry_exit(
                    frame=frame,
                    score=fold_scores[fold_id][0],
                    volatility=fold_volatility,
                    run=fold_run,
                    threshold=1.0,
                    configuration=usdjpy_carry_exit_configurations()[0],
                    test_start=test_start,
                    test_end=test_end,
                    fold_id=fold_id,
                    regime_cutoffs=cutoffs,
                    effective_spread=spread,
                )
                subject_simulation = simulate_usdjpy_carry_exit(
                    frame=frame,
                    score=fold_scores[fold_id][0],
                    volatility=fold_volatility,
                    run=fold_run,
                    threshold=1.0,
                    configuration=configuration,
                    test_start=test_start,
                    test_end=test_end,
                    fold_id=fold_id,
                    regime_cutoffs=cutoffs,
                    effective_spread=spread,
                )
                entry_diagnostics = _entry_identity_diagnostics(
                    control_simulation.trades,
                    subject_simulation.trades,
                    subject_simulation.intent_rows,
                )
                for name, count in entry_diagnostics.items():
                    diagnostics[name] += count
                target_trades = subject_simulation.trades[
                    subject_simulation.trades["slot"] == "target_direction"
                ]
                early = (
                    target_trades["carry_early_exit"].fillna(False).astype(bool)
                    if not target_trades.empty
                    else pd.Series(dtype=bool)
                )
                diagnostics["target_carry_early_exit_count"] += int(early.sum())
                diagnostics["target_fixed_exit_count"] += int((~early).sum())
                diagnostics["held_missing_state_safe_exit_count"] += (
                    _held_missing_state_safe_exit_count(subject_simulation.trades)
                )
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
                executable_id=usdjpy_carry_exit_executable(configuration).identity,
                simulation_fn=simulate_usdjpy_carry_exit,
            )
        )
    _require_no_unexpected_entry_mismatch(diagnostics)
    adjusted = _selection_adjusted_pvalues(
        results, total_exposures=SELECTION_TOTAL_EXPOSURES
    )
    for result in results:
        result.metrics["selection_aware_pvalue_ppm"] = adjusted[result.executable_id]
    _populate(results)
    subject = _matched(results, "usdjpy_carry_unwind_exit_subject")
    subject.metrics.update(diagnostics)
    surface = {
        "schema": "usdjpy_carry_exit_surface.v1",
        "dataset_sha256": DATASET_SHA256,
        "material_identity": OBSERVED_MATERIAL_ID,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "source_contract_id": usdjpy_source_contract().source_contract_id,
        "source_raw_sha256": source.raw_sha256,
        "source_development_prefix_sha256": source.prefix_sha256,
        "source_development_row_count": source.row_count,
        "state_counts": state_counts,
        "lifecycle_diagnostics": diagnostics,
        "session_semantics": "broker_clock_fixed_bins_no_dst_or_cash_session_claim",
        "selection_method": _selection_method(SELECTION_TOTAL_EXPOSURES),
        "selection_context": [
            {
                "configuration_id": result.configuration.configuration_id,
                "executable_id": result.executable_id,
                "net_profit_micropoints": result.metrics["net_profit_micropoints"],
                "selection_aware_pvalue_ppm": result.metrics[
                    "selection_aware_pvalue_ppm"
                ],
            }
            for result in results
        ],
        "claim_limits": _claim_limits()
        + [
            "data_source_and_lifecycle_are_the_primary_changed_layers",
            "subject_uses_one_fixed_negative_288_completed_source_bar_state",
            "subject_entry_requires_a_finite_completed_source_state",
            "source_missing_at_entry_drops_only_the_dependent_target_entry",
            "a_dropped_entry_reserves_the_exact_control_six_bar_slot",
            "common_entry_time_direction_and_slot_reservation_are_unchanged",
            "source_missing_or_stale_while_held_safe_exits_at_the_next_exact_open",
            "router_target_roles_selectors_session_risk_execution_and_lot_are_unchanged",
            "no_source_threshold_lookback_direction_session_hold_model_trade_or_lot_grid",
            "one_new_subject_with_exact_registered_STU_0092_control",
        ],
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
        "usdjpy_carry_exit_chassis_implementation_sha256": (
            usdjpy_carry_exit_chassis_implementation_sha256()
        ),
        "usdjpy_carry_exit_discovery_implementation_sha256": (
            usdjpy_carry_exit_discovery_implementation_sha256()
        ),
        "shared_discovery_implementation_sha256": (
            discovery_implementation_sha256()
        ),
    }
    canonical_bytes(surface)
    return surface


def project_usdjpy_carry_exit_evaluation(
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
        or value.get("schema") != "usdjpy_carry_exit_surface.v1"
    ):
        raise USDJPYCarryExitBoundaryError("USDJPY carry-exit surface is invalid")
    expected = executable_configuration_map()
    by_executable = {
        item.get("subject_executable_id"): item for item in value["evaluations"]
    }
    if set(by_executable) != set(expected) or subject_executable_id not in expected:
        raise USDJPYCarryExitBoundaryError("USDJPY carry-exit subjects differ")
    payload = {
        name: job_execution[name]
        for name in ("job_hash", "job_id", "job_permit_id", "start_record_id")
    }
    if job_execution.get("identity") != canonical_digest(
        domain="running-job-execution", payload=payload
    ):
        raise USDJPYCarryExitBoundaryError("USDJPY carry-exit Job is invalid")
    result = {
        **dict(by_executable[subject_executable_id]),
        "claim_limits": value["claim_limits"],
        "job_execution": dict(job_execution),
        "schema": "usdjpy_carry_exit_evaluation.v1",
        "selection_context": value["selection_context"],
        "selection_method": value["selection_method"],
        "session_semantics": value["session_semantics"],
        "surface_artifact_hash": surface_artifact_hash,
        "surface_manifest_hash": surface_manifest_hash,
    }
    canonical_bytes(result)
    return result


__all__ = [
    "DEVELOPMENT_END",
    "USDJPYCarryExitBoundaryError",
    "USDJPYDevelopment",
    "aligned_usdjpy_carry_return",
    "compute_registered_usdjpy_carry_exit_surface",
    "load_usdjpy_development",
    "project_usdjpy_carry_exit_evaluation",
    "source_carry_return",
    "usdjpy_carry_exit_discovery_implementation_sha256",
]
