"""Prospective atomic trace producer for the sleeve exposure-cap risk pair."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.dense_short_synthesis_chassis import (
    calibrate_synthesis_selector,
    terminal_return_sign_12,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    _causal_prefix_mismatch_count,
    _fold_payloads,
    _time_ns,
    _validate_engine_environment,
    _validate_fold_payloads,
    _validate_production_data,
    causal_effective_spread,
    discovery_implementation_sha256,
)
from axiom_rift.research.event_label_discovery import _raw_features
from axiom_rift.research.positive_direction_sleeve_chassis import (
    loader_implementation_sha256,
    positive_direction_sleeve_chassis_implementation_sha256,
)
from axiom_rift.research.positive_direction_sleeve_discovery import (
    _matrix,
    _threshold,
    positive_direction_sleeve_discovery_implementation_sha256,
    target_direction_score,
)
from axiom_rift.research.prospective_pair_trace import (
    PROSPECTIVE_PAIR_ELIGIBLE_DAY_SCHEMA,
    PROSPECTIVE_PAIR_INTENT_SCHEMA,
    PROSPECTIVE_PAIR_INVARIANCE_SCHEMA,
    PROSPECTIVE_PAIR_TRADE_SCHEMA,
    PROSPECTIVE_PAIR_TRACE_PROTOCOL_ID,
    ProspectivePairMember,
    ProspectivePairProtocolDefinition,
    ProspectivePairWindow,
    prospective_pair_observation_id,
    prospective_pair_trace_implementation_sha256,
    validate_prospective_pair_scientific_trace,
)
from axiom_rift.research.selection_inference import (
    DEFAULT_ALPHA_PPM,
    DEFAULT_BASE_SEED,
    DEFAULT_BLOCK_LENGTHS,
    DEFAULT_BOOTSTRAP_SAMPLES,
    DEFAULT_MONTE_CARLO_CONFIDENCE_PPM,
    selection_inference_implementation_sha256,
)
from axiom_rift.research.sleeve_exposure_cap_risk_chassis import (
    executable_configuration_map,
    simulate_sleeve_exposure_cap_risk,
    sleeve_exposure_cap_risk_chassis_implementation_sha256,
    sleeve_exposure_cap_risk_configurations,
    sleeve_exposure_cap_risk_executable,
    sleeve_exposure_cap_risk_successor_executable,
)
from axiom_rift.research.volatility_clock_label_chassis import fit_label_model
from axiom_rift.research.volatility_clock_label_discovery import (
    deterministic_score,
)
from axiom_rift.research.scientific_trace import (
    SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
    ScientificTraceError,
)


HISTORICAL_PRIOR_GLOBAL_EXPOSURE_COUNT = 581
HISTORICAL_CONTEXT_ID = "historical-context:pre-exposure-cap-research-581"
SLEEVE_EXPOSURE_CAP_RISK_FAMILY_TRACE_SCHEMA = (
    "sleeve_exposure_cap_risk_family_trace.v1"
)
_THIS_FILE = Path(__file__).resolve()
_MICROPOINTS_PER_POINT = 1_000_000
_FAMILY_TRACE_FIELDS = {
    "adapter_implementation_sha256",
    "attribution",
    "controls",
    "dataset_sha256",
    "eligible_day_observations",
    "family_id",
    "invariance_comparisons",
    "intent_observations",
    "material_identity",
    "ordered_family",
    "protocol_definition",
    "protocol_id",
    "schema",
    "split_artifact_sha256",
    "trade_observations",
    "windows",
}
_EXECUTION_TRACE_FIELDS = {
    "job_hash",
    "job_id",
    "mission_id",
    "subject_executable_id",
}


def sleeve_exposure_cap_risk_trace_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _iso(value: object) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        raise ValueError("sleeve exposure-cap timestamps must be naive")
    return timestamp.to_pydatetime().isoformat()


def _load_foundation(repository_root: str | Path) -> tuple[Any, tuple[dict[str, Any], ...]]:
    _validate_engine_environment()
    data = load_observed_development(Path(repository_root).resolve())
    _validate_production_data(data)
    folds = tuple(_fold_payloads(data))
    _validate_fold_payloads(data.frame, folds)
    return data, folds


def _windows(
    frame: pd.DataFrame, folds: tuple[dict[str, Any], ...]
) -> tuple[ProspectivePairWindow, ...]:
    time = pd.to_datetime(frame["time"], errors="raise")
    values: list[ProspectivePairWindow] = []
    for fold in folds:
        test = fold["test_oos"]
        start = pd.Timestamp(test["start"])
        end = pd.Timestamp(test["end"])
        dates = tuple(
            sorted(
                {
                    value.date().isoformat()
                    for value in time[(time >= start) & (time <= end)]
                }
            )
        )
        values.append(
            ProspectivePairWindow(
                fold_id=str(fold["fold_id"]),
                test_start=_iso(start),
                test_end=_iso(end),
                eligible_dates=dates,
            )
        )
    return tuple(values)


def build_sleeve_exposure_cap_risk_protocol_definition(
    repository_root: str | Path,
    *,
    successor: bool = False,
) -> ProspectivePairProtocolDefinition:
    data, folds = _load_foundation(repository_root)
    configurations = sleeve_exposure_cap_risk_configurations()
    executable_factory = (
        sleeve_exposure_cap_risk_successor_executable
        if successor
        else sleeve_exposure_cap_risk_executable
    )
    members = tuple(
        ProspectivePairMember(
            configuration_id=configuration.configuration_id,
            executable_id=executable_factory(configuration).identity,
            ordinal=index,
        )
        for index, configuration in enumerate(configurations, start=1)
    )
    implementations = tuple(
        sorted(
            {
                "discovery_sha256": discovery_implementation_sha256(),
                "loader_sha256": loader_implementation_sha256(),
                "positive_chassis_sha256": positive_direction_sleeve_chassis_implementation_sha256(),
                "positive_discovery_sha256": positive_direction_sleeve_discovery_implementation_sha256(),
                "prospective_pair_trace_sha256": prospective_pair_trace_implementation_sha256(),
                "selection_inference_sha256": selection_inference_implementation_sha256(),
                "sleeve_exposure_cap_chassis_sha256": sleeve_exposure_cap_risk_chassis_implementation_sha256(),
                "sleeve_exposure_cap_trace_sha256": sleeve_exposure_cap_risk_trace_implementation_sha256(),
            }.items()
        )
    )
    return ProspectivePairProtocolDefinition(
        members=members,
        control_executable_id=members[0].executable_id,
        folds=_windows(data.frame, folds),
        allowed_regimes=("high", "low", "middle"),
        invariance_keys=("decision_append", "feature_prefix"),
        dataset_sha256=DATASET_SHA256,
        material_identity=OBSERVED_MATERIAL_ID,
        split_artifact_sha256=ROLLING_SPLIT_SHA256,
        clock_contract="clock:fpmarkets_m5_bar_open_completed_plus_5m_v5",
        cost_contract=(
            "cost:fpmarkets_completed_bar_spread_proxy_point_0_01_"
            "causal_zero_repair_half_spread_stress_v3"
        ),
        producer_implementation_identities=implementations,
        historical_context_id=HISTORICAL_CONTEXT_ID,
        historical_prior_global_exposure_count=(
            HISTORICAL_PRIOR_GLOBAL_EXPOSURE_COUNT
        ),
        alpha_ppm=DEFAULT_ALPHA_PPM,
        bootstrap_samples=DEFAULT_BOOTSTRAP_SAMPLES,
        block_lengths=DEFAULT_BLOCK_LENGTHS,
        monte_carlo_confidence_ppm=(
            DEFAULT_MONTE_CARLO_CONFIDENCE_PPM
        ),
        base_seed=DEFAULT_BASE_SEED,
        protocol_id=PROSPECTIVE_PAIR_TRACE_PROTOCOL_ID,
    )


def _feature_surfaces(
    *,
    frame: pd.DataFrame,
    folds: tuple[dict[str, Any], ...],
) -> dict[str, object]:
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = causal_effective_spread(
        frame["spread"].to_numpy(float), _time_ns(frame)
    )
    features, volatility, run = _raw_features(frame)
    label = terminal_return_sign_12(frame, run)
    target = target_direction_score(frame, run)
    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_raw: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        end = int(
            time.searchsorted(pd.Timestamp(fold["test_oos"]["end"]), side="right")
        )
        prefix_frame = frame.iloc[:end]
        prefix_frames[fold_id] = prefix_frame
        prefix_raw[fold_id] = _raw_features(prefix_frame)
        prefix_spreads[fold_id] = causal_effective_spread(
            prefix_frame["spread"].to_numpy(float), _time_ns(prefix_frame)
        )
    fold_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    prefix_scores: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    cutoffs: dict[str, tuple[float, float]] = {}
    for fold in folds:
        fold_id = str(fold["fold_id"])
        train_start = pd.Timestamp(fold["train_is"]["start"])
        train_end = pd.Timestamp(fold["train_is"]["end"])
        mask = ((time >= train_start) & (time <= train_end)).to_numpy()
        train = mask & (time.shift(-13) <= train_end).fillna(False).to_numpy()
        model = fit_label_model(features=features, label=label, train_mask=train)
        router_raw = deterministic_score(features, model)
        router_threshold = calibrate_synthesis_selector(router_raw, mask, 7000)
        target_threshold = _threshold(target, mask)
        train_volatility = volatility[train & np.isfinite(volatility)]
        regime_cutoffs = (
            float(np.quantile(train_volatility, 1 / 3, method="higher")),
            float(np.quantile(train_volatility, 2 / 3, method="higher")),
        )
        fold_scores[fold_id] = (
            _matrix(
                router_raw,
                target,
                volatility,
                router_threshold,
                target_threshold,
                regime_cutoffs,
            ),
            volatility,
            run,
        )
        prefix_frame = prefix_frames[fold_id]
        prefix_features, prefix_volatility, prefix_run = prefix_raw[fold_id]
        prefix_time = pd.to_datetime(prefix_frame["time"], errors="raise")
        prefix_mask = (
            (prefix_time >= train_start) & (prefix_time <= train_end)
        ).to_numpy()
        prefix_router = deterministic_score(prefix_features, model)
        prefix_target = target_direction_score(prefix_frame, prefix_run)
        prefix_router_threshold = calibrate_synthesis_selector(
            prefix_router, prefix_mask, 7000
        )
        prefix_target_threshold = _threshold(prefix_target, prefix_mask)
        if (
            router_threshold != prefix_router_threshold
            or target_threshold != prefix_target_threshold
        ):
            raise ValueError("sleeve exposure-cap calibration changed under append")
        prefix_scores[fold_id] = (
            _matrix(
                prefix_router,
                prefix_target,
                prefix_volatility,
                prefix_router_threshold,
                prefix_target_threshold,
                regime_cutoffs,
            ),
            prefix_volatility,
            prefix_run,
        )
        cutoffs[fold_id] = regime_cutoffs
    return {
        "cutoffs": cutoffs,
        "fold_scores": fold_scores,
        "prefix_frames": prefix_frames,
        "prefix_scores": prefix_scores,
        "prefix_spreads": prefix_spreads,
        "spread": spread,
        "time": time,
    }


def _micropoints(value: object) -> int:
    return int(round(float(value) * _MICROPOINTS_PER_POINT))


def _array_bundle_sha256(
    values: tuple[tuple[str, np.ndarray], ...], *, row_count: int
) -> str:
    digest = sha256()
    for name, raw in values:
        array = np.asarray(raw)[:row_count]
        if np.issubdtype(array.dtype, np.floating):
            normalized = np.asarray(array, dtype="<f8").copy()
            normalized[np.isnan(normalized)] = np.nan
        elif np.issubdtype(array.dtype, np.integer):
            normalized = np.asarray(array, dtype="<i8")
        else:
            raise ValueError("sleeve exposure-cap invariance array type is invalid")
        digest.update(name.encode("ascii"))
        digest.update(b"\0")
        digest.update(str(normalized.shape).encode("ascii"))
        digest.update(b"\0")
        digest.update(normalized.tobytes(order="C"))
    return digest.hexdigest()


def _intent_rows_sha256(rows: tuple[tuple[Any, ...], ...]) -> str:
    normalized = [
        [str(slot), _iso(decision), _iso(entry), _iso(exit_time), int(direction), str(status)]
        for slot, decision, entry, exit_time, direction, status in rows
    ]
    return sha256(canonical_bytes(normalized)).hexdigest()


def preregistered_eligible_intent_rows(
    rows: tuple[tuple[Any, ...], ...],
    *,
    eligible_dates: tuple[str, ...],
) -> tuple[tuple[Any, ...], ...]:
    """Remove simulator-only gap rows outside the frozen intent calendar."""

    eligible = frozenset(eligible_dates)
    if not eligible or len(eligible) != len(eligible_dates):
        raise ValueError("sleeve exposure-cap eligible intent calendar is invalid")
    kept: list[tuple[Any, ...]] = []
    for row in rows:
        if len(row) != 6:
            raise ValueError("sleeve exposure-cap intent shape is invalid")
        _slot, decision, entry, _exit_time, _direction, status = row
        if pd.Timestamp(decision).date().isoformat() in eligible:
            kept.append(row)
            continue
        if str(status) != "gap_excluded":
            raise ValueError(
                "sleeve exposure-cap non-gap intent is outside its eligible day"
            )
        if pd.Timestamp(entry).date().isoformat() not in eligible:
            raise ValueError(
                "sleeve exposure-cap excluded gap has no eligible next bar"
            )
    return tuple(kept)


def _trade_observation(
    row: Mapping[str, Any],
    *,
    configuration_id: str,
    executable_id: str,
) -> dict[str, object]:
    decision_time = _iso(row["decision_time"])
    entry_time = _iso(row["entry_time"])
    exit_time = _iso(row["exit_time"])
    direction = int(row["direction"])
    fold_id = str(row["fold_id"])
    slot = str(row["slot"])
    entry_bid = _micropoints(row["entry_bid"])
    exit_bid = _micropoints(row["exit_bid"])
    entry_spread = _micropoints(row["entry_spread_cost"])
    exit_spread = _micropoints(row["exit_spread_cost"])
    if (entry_spread + exit_spread) % 2:
        raise ValueError("sleeve exposure-cap stress cost is not integral")
    gross = direction * (exit_bid - entry_bid)
    native_cost = entry_spread if direction == 1 else exit_spread
    stress_cost = native_cost + (entry_spread + exit_spread) // 2
    native_net = gross - native_cost
    stress_net = gross - stress_cost
    if (
        abs(gross - _micropoints(row["gross_pnl"])) > 1
        or abs(native_cost - _micropoints(row["native_cost"])) > 1
        or abs(stress_cost - _micropoints(row["stress_cost"])) > 1
        or abs(native_net - _micropoints(row["pnl"])) > 1
        or abs(stress_net - _micropoints(row["stress_pnl"])) > 1
    ):
        raise ValueError("sleeve exposure-cap trade rounding is inconsistent")
    return {
        "configuration_id": configuration_id,
        "decision_bar_index": int(row["decision_bar_index"]),
        "decision_bar_open_time": _iso(row["decision_bar_open_time"]),
        "decision_time": decision_time,
        "direction": direction,
        "entry_bar_index": int(row["entry_bar_index"]),
        "entry_bid_micropoints": entry_bid,
        "entry_spread_cost_micropoints": entry_spread,
        "entry_spread_source_bar_index": int(
            row["entry_spread_source_bar_index"]
        ),
        "entry_spread_source_bar_open_time": _iso(
            row["entry_spread_source_bar_open_time"]
        ),
        "entry_time": entry_time,
        "executable_id": executable_id,
        "exit_bar_index": int(row["exit_bar_index"]),
        "exit_bid_micropoints": exit_bid,
        "exit_spread_cost_micropoints": exit_spread,
        "exit_spread_source_bar_index": int(
            row["exit_spread_source_bar_index"]
        ),
        "exit_spread_source_bar_open_time": _iso(
            row["exit_spread_source_bar_open_time"]
        ),
        "exit_time": exit_time,
        "fold_id": fold_id,
        "gross_pnl_micropoints": gross,
        "native_cost_micropoints": native_cost,
        "native_net_pnl_micropoints": native_net,
        "observation_id": prospective_pair_observation_id(
            executable_id=executable_id,
            fold_id=fold_id,
            slot=slot,
            decision_time=decision_time,
            entry_time=entry_time,
            exit_time=exit_time,
            direction=direction,
        ),
        "regime": str(row["regime"]),
        "schema": PROSPECTIVE_PAIR_TRADE_SCHEMA,
        "slot": slot,
        "stress_cost_micropoints": stress_cost,
        "stress_net_pnl_micropoints": stress_net,
    }


def _intent_observation(
    row: tuple[Any, ...],
    *,
    configuration_id: str,
    executable_id: str,
    fold_id: str,
) -> dict[str, object]:
    if len(row) != 6:
        raise ValueError("sleeve exposure-cap intent shape is invalid")
    slot, decision, entry, exit_time, direction, status = row
    decision_iso = _iso(decision)
    entry_iso = _iso(entry)
    exit_iso = _iso(exit_time)
    trace_status = str(status)
    if trace_status == "gross_exposure_cap_blocked":
        trace_status = "risk_policy_skipped"
    return {
        "configuration_id": configuration_id,
        "decision_time": decision_iso,
        "direction": int(direction),
        "entry_time": entry_iso,
        "executable_id": executable_id,
        "exit_time": exit_iso,
        "fold_id": fold_id,
        "observation_id": prospective_pair_observation_id(
            executable_id=executable_id,
            fold_id=fold_id,
            slot=str(slot),
            decision_time=decision_iso,
            entry_time=entry_iso,
            exit_time=exit_iso,
            direction=int(direction),
        ),
        "schema": PROSPECTIVE_PAIR_INTENT_SCHEMA,
        "slot": str(slot),
        "status": trace_status,
    }


def validate_sleeve_exposure_cap_risk_family_trace(
    value: bytes | Mapping[str, Any],
    *,
    definition: ProspectivePairProtocolDefinition,
) -> dict[str, object]:
    try:
        normalized = (
            parse_canonical(value)
            if isinstance(value, bytes)
            else parse_canonical(canonical_bytes(value))
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("sleeve exposure-cap family trace is not canonical") from exc
    if (
        not isinstance(normalized, dict)
        or set(normalized) != _FAMILY_TRACE_FIELDS
        or normalized.get("schema")
        != SLEEVE_EXPOSURE_CAP_RISK_FAMILY_TRACE_SCHEMA
    ):
        raise ValueError("sleeve exposure-cap family trace schema is invalid")
    bound = {
        **normalized,
        "job_hash": "0" * 64,
        "job_id": "job:" + "0" * 64,
        "mission_id": "MIS-FAMILY-TRACE-VALIDATION",
        "schema": SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
        "subject_executable_id": definition.control_executable_id,
    }
    try:
        validate_prospective_pair_scientific_trace(bound, definition)
    except (ScientificTraceError, TypeError, ValueError) as exc:
        raise ValueError("sleeve exposure-cap family trace is invalid") from exc
    canonical_bytes(normalized)
    return normalized


def bind_sleeve_exposure_cap_risk_family_trace(
    value: bytes | Mapping[str, Any],
    *,
    definition: ProspectivePairProtocolDefinition,
    mission_id: str,
    subject_executable_id: str,
    job_id: str,
    job_hash: str,
) -> dict[str, object]:
    family = validate_sleeve_exposure_cap_risk_family_trace(
        value,
        definition=definition,
    )
    bound = {
        **family,
        "job_hash": job_hash,
        "job_id": job_id,
        "mission_id": mission_id,
        "schema": SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
        "subject_executable_id": subject_executable_id,
    }
    try:
        validate_prospective_pair_scientific_trace(bound, definition)
    except (ScientificTraceError, TypeError, ValueError) as exc:
        raise ValueError("sleeve exposure-cap bound trace is invalid") from exc
    canonical_bytes(bound)
    return bound


def extract_sleeve_exposure_cap_risk_family_trace(
    value: Mapping[str, Any],
    *,
    definition: ProspectivePairProtocolDefinition,
) -> dict[str, object]:
    normalized = parse_canonical(canonical_bytes(value))
    if not isinstance(normalized, dict) or set(normalized) != (
        _FAMILY_TRACE_FIELDS | _EXECUTION_TRACE_FIELDS
    ):
        raise ValueError("sleeve exposure-cap bound trace schema is invalid")
    try:
        validate_prospective_pair_scientific_trace(normalized, definition)
    except (ScientificTraceError, TypeError, ValueError) as exc:
        raise ValueError("sleeve exposure-cap bound trace is invalid") from exc
    family = {
        key: item
        for key, item in normalized.items()
        if key not in _EXECUTION_TRACE_FIELDS
    }
    family["schema"] = SLEEVE_EXPOSURE_CAP_RISK_FAMILY_TRACE_SCHEMA
    return validate_sleeve_exposure_cap_risk_family_trace(
        family,
        definition=definition,
    )


def compute_sleeve_exposure_cap_risk_family_trace(
    repository_root: str | Path,
    *,
    definition: ProspectivePairProtocolDefinition,
) -> dict[str, object]:
    configurations = sleeve_exposure_cap_risk_configurations()
    successor = (
        definition.control_executable_id
        == sleeve_exposure_cap_risk_successor_executable(configurations[0]).identity
    )
    current = build_sleeve_exposure_cap_risk_protocol_definition(
        repository_root,
        successor=successor,
    )
    if current.manifest() != definition.manifest():
        raise ValueError("sleeve exposure-cap protocol authority changed")
    data, folds = _load_foundation(repository_root)
    frame = data.frame
    surfaces = _feature_surfaces(frame=frame, folds=folds)
    full_spread = surfaces["spread"]
    trade_observations: list[dict[str, object]] = []
    intent_observations: list[dict[str, object]] = []
    invariance: list[dict[str, object]] = []
    executable_factory = (
        sleeve_exposure_cap_risk_successor_executable
        if successor
        else sleeve_exposure_cap_risk_executable
    )
    for configuration in configurations:
        executable_id = executable_factory(configuration).identity
        for fold in folds:
            fold_id = str(fold["fold_id"])
            test = fold["test_oos"]
            full_score, full_volatility, full_run = surfaces["fold_scores"][fold_id]
            prefix_score, prefix_volatility, prefix_run = surfaces["prefix_scores"][fold_id]
            simulation = simulate_sleeve_exposure_cap_risk(
                frame=frame,
                score=full_score,
                volatility=full_volatility,
                run=full_run,
                threshold=1.0,
                configuration=configuration,
                test_start=pd.Timestamp(test["start"]),
                test_end=pd.Timestamp(test["end"]),
                fold_id=fold_id,
                regime_cutoffs=surfaces["cutoffs"][fold_id],
                effective_spread=full_spread,
            )
            prefix_frame = surfaces["prefix_frames"][fold_id]
            prefix_simulation = simulate_sleeve_exposure_cap_risk(
                frame=prefix_frame,
                score=prefix_score,
                volatility=prefix_volatility,
                run=prefix_run,
                threshold=1.0,
                configuration=configuration,
                test_start=pd.Timestamp(test["start"]),
                test_end=pd.Timestamp(test["end"]),
                fold_id=fold_id,
                regime_cutoffs=surfaces["cutoffs"][fold_id],
                effective_spread=surfaces["prefix_spreads"][fold_id],
            )
            compared = len(prefix_frame)
            prefix_mismatch = _causal_prefix_mismatch_count(
                full_surfaces=(
                    ("score_router", full_score[:, 0]),
                    ("score_target", full_score[:, 1]),
                    ("volatility", full_volatility),
                    ("run", full_run),
                    ("effective_spread", full_spread),
                ),
                prefix_surfaces=(
                    ("score_router", prefix_score[:, 0]),
                    ("score_target", prefix_score[:, 1]),
                    ("volatility", prefix_volatility),
                    ("run", prefix_run),
                    ("effective_spread", surfaces["prefix_spreads"][fold_id]),
                ),
                compared_row_count=compared,
            )
            window = next(
                item for item in definition.folds if item.fold_id == fold_id
            )
            left = preregistered_eligible_intent_rows(
                simulation.intent_rows,
                eligible_dates=window.eligible_dates,
            )
            right = preregistered_eligible_intent_rows(
                prefix_simulation.intent_rows,
                eligible_dates=window.eligible_dates,
            )
            append_mismatch = abs(len(left) - len(right)) + sum(
                left_item != right_item
                for left_item, right_item in zip(left, right, strict=False)
            )
            mismatch_by_key = {
                "decision_append": append_mismatch,
                "feature_prefix": prefix_mismatch,
            }
            hash_by_key = {
                "decision_append": (
                    _intent_rows_sha256(left),
                    _intent_rows_sha256(right),
                ),
                "feature_prefix": (
                    _array_bundle_sha256(
                        (
                            ("score_router", full_score[:, 0]),
                            ("score_target", full_score[:, 1]),
                            ("volatility", full_volatility),
                            ("run", full_run),
                            ("effective_spread", full_spread),
                        ),
                        row_count=compared,
                    ),
                    _array_bundle_sha256(
                        (
                            ("score_router", prefix_score[:, 0]),
                            ("score_target", prefix_score[:, 1]),
                            ("volatility", prefix_volatility),
                            ("run", prefix_run),
                            (
                                "effective_spread",
                                surfaces["prefix_spreads"][fold_id],
                            ),
                        ),
                        row_count=compared,
                    ),
                ),
            }
            for key in definition.invariance_keys:
                invariance.append(
                    {
                        "compared_row_count": compared,
                        "executable_id": executable_id,
                        "fold_id": fold_id,
                        "full_values_sha256": hash_by_key[key][0],
                        "invariance_key": key,
                        "mismatch_count": mismatch_by_key[key],
                        "prefix_values_sha256": hash_by_key[key][1],
                        "schema": PROSPECTIVE_PAIR_INVARIANCE_SCHEMA,
                    }
                )
            for row in simulation.trades.to_dict("records"):
                trade_observations.append(
                    _trade_observation(
                        row,
                        configuration_id=configuration.configuration_id,
                        executable_id=executable_id,
                    )
                )
            for row in left:
                intent_observations.append(
                    _intent_observation(
                        row,
                        configuration_id=configuration.configuration_id,
                        executable_id=executable_id,
                        fold_id=fold_id,
                    )
                )
    trade_observations.sort(
        key=lambda item: (
            item["executable_id"],
            item["fold_id"],
            item["decision_time"],
            item["slot"],
            item["observation_id"],
        )
    )
    intent_observations.sort(
        key=lambda item: (
            item["executable_id"],
            item["fold_id"],
            item["decision_time"],
            item["slot"],
            item["observation_id"],
        )
    )
    eligible = [
        {
            "configuration_id": member.configuration_id,
            "date": day,
            "executable_id": member.executable_id,
            "fold_id": window.fold_id,
            "schema": PROSPECTIVE_PAIR_ELIGIBLE_DAY_SCHEMA,
        }
        for member in definition.members
        for window in definition.folds
        for day in window.eligible_dates
    ]
    trace = {
        "adapter_implementation_sha256": sleeve_exposure_cap_risk_trace_implementation_sha256(),
        "attribution": {
            "definition_identity": definition.identity,
            "implementation_identities": dict(
                definition.producer_implementation_identities
            ),
            "selection_inference_sha256": selection_inference_implementation_sha256(),
            "trace_validator_sha256": prospective_pair_trace_implementation_sha256(),
        },
        "controls": {
            "control_executable_id": definition.control_executable_id
        },
        "dataset_sha256": definition.dataset_sha256,
        "eligible_day_observations": eligible,
        "family_id": definition.family_id,
        "invariance_comparisons": invariance,
        "intent_observations": intent_observations,
        "material_identity": definition.material_identity,
        "ordered_family": list(definition.prospective_executable_ids),
        "protocol_definition": definition.manifest(),
        "protocol_id": definition.protocol_id,
        "schema": SLEEVE_EXPOSURE_CAP_RISK_FAMILY_TRACE_SCHEMA,
        "split_artifact_sha256": definition.split_artifact_sha256,
        "trade_observations": trade_observations,
        "windows": [item.manifest() for item in definition.folds],
    }
    return validate_sleeve_exposure_cap_risk_family_trace(
        trace,
        definition=definition,
    )


def compute_sleeve_exposure_cap_risk_trace(
    repository_root: str | Path,
    *,
    definition: ProspectivePairProtocolDefinition,
    mission_id: str,
    subject_executable_id: str,
    job_id: str,
    job_hash: str,
) -> dict[str, object]:
    family = compute_sleeve_exposure_cap_risk_family_trace(
        repository_root,
        definition=definition,
    )
    return bind_sleeve_exposure_cap_risk_family_trace(
        family,
        definition=definition,
        mission_id=mission_id,
        subject_executable_id=subject_executable_id,
        job_id=job_id,
        job_hash=job_hash,
    )


__all__ = [
    "HISTORICAL_CONTEXT_ID",
    "HISTORICAL_PRIOR_GLOBAL_EXPOSURE_COUNT",
    "SLEEVE_EXPOSURE_CAP_RISK_FAMILY_TRACE_SCHEMA",
    "bind_sleeve_exposure_cap_risk_family_trace",
    "build_sleeve_exposure_cap_risk_protocol_definition",
    "compute_sleeve_exposure_cap_risk_family_trace",
    "compute_sleeve_exposure_cap_risk_trace",
    "extract_sleeve_exposure_cap_risk_family_trace",
    "preregistered_eligible_intent_rows",
    "sleeve_exposure_cap_risk_trace_implementation_sha256",
    "validate_sleeve_exposure_cap_risk_family_trace",
]
