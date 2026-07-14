"""Profile-streamed analog family trace computation.

This module is a prospective implementation successor.  It does not alter the
byte identities used by STU-0106.  The mathematical family, controls, and trace
schema stay fixed, while Executable identities bind the memory-bounded v2 fit
implementation.  A deterministic projection back to the frozen v1 identities
supports exact engineering parity checks without granting scientific credit.
"""

from __future__ import annotations

from copy import deepcopy
import gc
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any, Mapping

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec, canonical_digest
from axiom_rift.research import analog_state_replay as replay_v1
from axiom_rift.research.analog_state_family import (
    P1_STU0061_ANALOG_FAMILY,
    AnalogFamilyConfiguration,
    analog_family_components,
    analog_family_executable,
    analog_family_implementation_sha256,
    calibrate_analog_selector,
)
from axiom_rift.research.analog_state_fit_v2 import (
    analog_fit_v2_implementation_sha256,
    fit_prepared_analog_fold,
    fit_prepared_analog_fold_scoped,
    prepare_analog_frame,
)
from axiom_rift.research.analog_state_trace import (
    ANALOG_FAMILY_TRACE_SCHEMA,
    ANALOG_REPLAY_CONTROLS,
    ANALOG_REPLAY_TRACE_ATTRIBUTION,
    analog_family_execution_contracts,
    analog_family_trace_implementation_identities,
    analog_observation_id,
    analog_original_family_provenance,
    analog_trace_implementation_sha256,
    expected_analog_family_inventory,
    validate_analog_family_trace,
)
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    _evaluate_configuration,
    _fold_payloads,
    _time_ns,
    _validate_engine_environment,
    _validate_fold_payloads,
    _validate_production_data,
    causal_effective_spread,
    discovery_implementation_sha256,
    loader_implementation_sha256,
    simulate_fixed_hold,
)
from axiom_rift.research.scientific_trace import ANALOG_STATE_TRACE_PROTOCOL_ID
from axiom_rift.research.selection_inference import (
    selection_inference_implementation_sha256,
)


_THIS_FILE = Path(__file__).resolve()
ANALOG_SCOPED_QUERY_SCOPE_ID = (
    "train_calibration_union_test_decision_rows_v1"
)


def analog_replay_v2_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def analog_replay_v2_bundle_sha256() -> str:
    """Bind every delegated implementation that can change v2 trace rows."""

    return canonical_digest(
        domain="analog-replay-v2-implementation-bundle",
        payload={
            "analog_family_sha256": analog_family_implementation_sha256(),
            "analog_fit_v2_sha256": analog_fit_v2_implementation_sha256(),
            "analog_replay_v1_helpers_sha256": (
                replay_v1.analog_replay_implementation_sha256()
            ),
            "analog_replay_v2_sha256": analog_replay_v2_implementation_sha256(),
            "analog_trace_sha256": analog_trace_implementation_sha256(),
            "discovery_sha256": discovery_implementation_sha256(),
            "loader_sha256": loader_implementation_sha256(),
            "selection_inference_sha256": (
                selection_inference_implementation_sha256()
            ),
        },
    )


def analog_family_trace_v2_implementation_identities() -> dict[str, str]:
    identities = analog_family_trace_implementation_identities()
    return {
        **identities,
        "analog_replay_sha256": analog_replay_v2_bundle_sha256(),
    }


def _analog_family_components_v2(*, scoped: bool) -> tuple[ComponentSpec, ...]:
    """Build one exact-parity or scope-bound prospective component chain."""

    old_components = analog_family_components(P1_STU0061_ANALOG_FAMILY)
    identity_map: dict[str, str] = {}
    components: list[ComponentSpec] = []
    replacement_count = 0
    fit_name = (
        "fit_prepared_analog_fold_scoped"
        if scoped
        else "fit_prepared_analog_fold"
    )
    replacement = (
        f"axiom_rift.research.analog_state_fit_v2.{fit_name}"
        f"@sha256:{analog_fit_v2_implementation_sha256()}"
    )
    executable_name = (
        "analog_family_executable_scoped_v2"
        if scoped
        else "analog_family_executable_v2"
    )
    synthesis_replacement = (
        f"axiom_rift.research.analog_state_replay_v2.{executable_name}"
        f"@sha256:{analog_replay_v2_implementation_sha256()}"
    )
    for old in old_components:
        implementation = old.implementation
        protocol = old.protocol
        specification = old.specification()
        if "analog_state_family.fit_fold_analog_family@sha256:" in implementation:
            implementation = replacement
            replacement_count += 1
            if scoped and old.protocol == "model.fold_train_knn_analog_family.v1":
                protocol = "model.fold_train_knn_analog_family_scoped_query.v2"
                specification = {
                    **specification,
                    "parameter_fields": [
                        *specification["parameter_fields"],
                        "query_scope_id",
                    ],
                    "query_scope_id": ANALOG_SCOPED_QUERY_SCOPE_ID,
                    "query_scope_derivation": (
                        "registered_train_calibration_and_test_decision_windows"
                    ),
                }
        elif "analog_state_family.analog_family_executable@sha256:" in implementation:
            implementation = synthesis_replacement
            replacement_count += 1
        dependencies = tuple(
            identity_map.get(dependency, dependency)
            for dependency in old.semantic_dependencies
        )
        current = ComponentSpec(
            display_name=old.display_name,
            protocol=protocol,
            implementation=implementation,
            spec=specification,
            semantic_dependencies=dependencies,
        )
        identity_map[old.identity] = current.identity
        components.append(current)
    if len(components) != len(old_components) or replacement_count != 3:
        raise RuntimeError("analog v2 component inventory drifted")
    return tuple(components)


def analog_family_components_v2() -> tuple[ComponentSpec, ...]:
    """Rebind the memory-bounded exact-v1-parity implementation chain."""

    return _analog_family_components_v2(scoped=False)


def analog_family_components_scoped_v2() -> tuple[ComponentSpec, ...]:
    """Bind the prospective train-calibration/test-decision query scope."""

    return _analog_family_components_v2(scoped=True)


def _analog_family_executable_v2(
    configuration: AnalogFamilyConfiguration,
    *,
    scoped: bool,
) -> ExecutableSpec:
    if configuration.family != P1_STU0061_ANALOG_FAMILY:
        raise ValueError("analog replay v2 accepts only the exact P1 family")
    old = analog_family_executable(configuration)
    parameters = old.parameter_values()
    if scoped:
        parameters = {
            **parameters,
            "query_scope_id": ANALOG_SCOPED_QUERY_SCOPE_ID,
        }
    engine_name = "analog_family_scoped_v2" if scoped else "analog_family_v2"
    scope_contract = (
        f":query_scope_{ANALOG_SCOPED_QUERY_SCOPE_ID}" if scoped else ""
    )
    return ExecutableSpec(
        display_name=(
            f"{old.display_name} decision scoped v2"
            if scoped
            else f"{old.display_name} memory bounded v2"
        ),
        components=(
            analog_family_components_scoped_v2()
            if scoped
            else analog_family_components_v2()
        ),
        parameters=parameters,
        data_contract=old.data_contract,
        split_contract=old.split_contract,
        clock_contract=old.clock_contract,
        cost_contract=old.cost_contract,
        engine_contract=(
            f"engine:{engine_name}:"
            f"python{'.'.join(str(value) for value in sys.version_info[:3])}:"
            f"numpy{np.__version__}:pandas{pd.__version__}:scipy{scipy.__version__}:"
            f"fit_{analog_fit_v2_implementation_sha256()}:"
            f"family_{analog_family_implementation_sha256()}:"
            f"loader_{loader_implementation_sha256()}:"
            f"shared_{discovery_implementation_sha256()}:"
            f"selection_{selection_inference_implementation_sha256()}:"
            f"replay_{analog_replay_v2_bundle_sha256()}"
            f"{scope_contract}"
        ),
    )


def analog_family_executable_v2(
    configuration: AnalogFamilyConfiguration,
) -> ExecutableSpec:
    """Build the explicit full-vector v1-parity certification identity."""

    return _analog_family_executable_v2(configuration, scoped=False)


def analog_family_executable_scoped_v2(
    configuration: AnalogFamilyConfiguration,
) -> ExecutableSpec:
    """Build the prospective decision-scoped research identity."""

    return _analog_family_executable_v2(configuration, scoped=True)


def expected_analog_family_inventory_v2() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "configuration_id": configuration.configuration_id,
            "executable_id": analog_family_executable_v2(configuration).identity,
            "historical_reference_executable_id": (
                configuration.historical_reference_executable_id
            ),
            "ordinal": ordinal,
            "profile_id": configuration.profile_id,
            "signal_sign": configuration.signal_sign,
        }
        for ordinal, configuration in enumerate(
            P1_STU0061_ANALOG_FAMILY.configurations(),
            start=1,
        )
    )


def expected_analog_family_inventory_scoped_v2() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "configuration_id": configuration.configuration_id,
            "executable_id": analog_family_executable_scoped_v2(
                configuration
            ).identity,
            "historical_reference_executable_id": (
                configuration.historical_reference_executable_id
            ),
            "ordinal": ordinal,
            "profile_id": configuration.profile_id,
            "signal_sign": configuration.signal_sign,
        }
        for ordinal, configuration in enumerate(
            P1_STU0061_ANALOG_FAMILY.configurations(),
            start=1,
        )
    )


def _v2_to_v1_executable_ids(*, scoped: bool = False) -> dict[str, str]:
    executable_builder = (
        analog_family_executable_scoped_v2
        if scoped
        else analog_family_executable_v2
    )
    return {
        executable_builder(configuration).identity: (
            analog_family_executable(configuration).identity
        )
        for configuration in P1_STU0061_ANALOG_FAMILY.configurations()
    }


def _project_analog_v2_trace_to_v1(
    trace: Mapping[str, object],
    *,
    scoped: bool = False,
) -> dict[str, object]:
    """Create a non-authoritative exact parity projection to frozen v1 IDs."""

    projected = deepcopy(dict(trace))
    mapping = _v2_to_v1_executable_ids(scoped=scoped)
    projected["implementation_identities"] = (
        analog_family_trace_implementation_identities()
    )
    for member in projected["ordered_family"]:
        member["executable_id"] = mapping[str(member["executable_id"])]
    for collection_name, observation_kind in (
        ("trade_observations", "trade"),
        ("intent_observations", "intent"),
    ):
        rows = projected[collection_name]
        for row in rows:
            row["executable_id"] = mapping[str(row["executable_id"])]
            row["observation_id"] = "pending"
            row["observation_id"] = analog_observation_id(observation_kind, row)
        rows.sort(
            key=(
                (lambda item: (
                    str(item["configuration_id"]),
                    str(item["fold_id"]),
                    str(item["decision_time"]),
                    str(item["observation_id"]),
                ))
                if observation_kind == "trade"
                else (lambda item: (
                    str(item["configuration_id"]),
                    str(item["fold_id"]),
                    str(item["scope"]),
                    int(item["ordinal"]),
                    str(item["observation_id"]),
                ))
            )
        )
    for row in projected["eligible_day_observations"]:
        row["executable_id"] = mapping[str(row["executable_id"])]
    return validate_analog_family_trace(projected)


def validate_analog_family_trace_v2(
    trace: Mapping[str, object],
) -> dict[str, object]:
    if trace.get("implementation_identities") != (
        analog_family_trace_v2_implementation_identities()
    ):
        raise ValueError("analog v2 implementation identities drifted")
    if tuple(trace.get("ordered_family", ())) != expected_analog_family_inventory_v2():
        raise ValueError("analog v2 family inventory drifted")
    _project_analog_v2_trace_to_v1(trace)
    normalized = parse_canonical(canonical_bytes(trace))
    if not isinstance(normalized, dict):
        raise RuntimeError("analog v2 trace normalization failed")
    return normalized


def validate_analog_family_trace_scoped_v2(
    trace: Mapping[str, object],
) -> dict[str, object]:
    if trace.get("implementation_identities") != (
        analog_family_trace_v2_implementation_identities()
    ):
        raise ValueError("analog scoped v2 implementation identities drifted")
    if tuple(trace.get("ordered_family", ())) != (
        expected_analog_family_inventory_scoped_v2()
    ):
        raise ValueError("analog scoped v2 family inventory drifted")
    _project_analog_v2_trace_to_v1(trace, scoped=True)
    normalized = parse_canonical(canonical_bytes(trace))
    if not isinstance(normalized, dict):
        raise RuntimeError("analog scoped v2 trace normalization failed")
    return normalized


def _fit_prepared_for_scope(
    prepared: Any,
    *,
    profile_id: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    scoped: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if scoped:
        return fit_prepared_analog_fold_scoped(
            prepared,
            family=P1_STU0061_ANALOG_FAMILY,
            profile_id=profile_id,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
        )
    return fit_prepared_analog_fold(
        prepared,
        family=P1_STU0061_ANALOG_FAMILY,
        profile_id=profile_id,
        train_start=train_start,
        train_end=train_end,
    )


def _compute_analog_family_trace_v2(
    repository_root: str | Path,
    *,
    scoped: bool,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    """Compute the exact family with one profile and one query protocol at a time."""

    _validate_engine_environment()
    data = load_observed_development(Path(repository_root).resolve())
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = causal_effective_spread(frame["spread"].to_numpy(float), _time_ns(frame))
    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    windows: list[dict[str, object]] = []
    for fold in folds:
        fold_id = str(fold["fold_id"])
        test = fold["test_oos"]
        prefix_end = int(time.searchsorted(pd.Timestamp(test["end"]), side="right"))
        prefix_frames[fold_id] = frame.iloc[:prefix_end]
        prefix_spreads[fold_id] = causal_effective_spread(
            prefix_frames[fold_id]["spread"].to_numpy(float),
            _time_ns(prefix_frames[fold_id]),
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
                "test_end": replay_v1._iso(test["end"]),
                "test_start": replay_v1._iso(test["start"]),
                "train_end": replay_v1._iso(fold["train_is"]["end"]),
                "train_start": replay_v1._iso(fold["train_is"]["start"]),
            }
        )
    comparisons_by_key: dict[tuple[str, str], dict[str, object]] = {}
    all_trades: list[dict[str, object]] = []
    all_intents: list[dict[str, object]] = []
    raw_metrics: dict[str, dict[str, int]] = {}
    for profile in P1_STU0061_ANALOG_FAMILY.profiles:
        profile_id = profile.profile_id
        full_prepared = prepare_analog_frame(
            frame,
            family=P1_STU0061_ANALOG_FAMILY,
            profile_ids=(profile_id,),
        )
        feature_sets: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        prefix_sets: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        calibrations: dict[str, tuple[float, tuple[float, float], float]] = {}
        for fold in folds:
            fold_id = str(fold["fold_id"])
            train = fold["train_is"]
            test = fold["test_oos"]
            start = pd.Timestamp(train["start"])
            end = pd.Timestamp(train["end"])
            test_start = pd.Timestamp(test["start"])
            test_end = pd.Timestamp(test["end"])
            full = _fit_prepared_for_scope(
                full_prepared,
                profile_id=profile_id,
                train_start=start,
                train_end=end,
                test_start=test_start,
                test_end=test_end,
                scoped=scoped,
            )
            prefix_frame = prefix_frames[fold_id]
            prefix_prepared = prepare_analog_frame(
                prefix_frame,
                family=P1_STU0061_ANALOG_FAMILY,
                profile_ids=(profile_id,),
            )
            prefix = _fit_prepared_for_scope(
                prefix_prepared,
                profile_id=profile_id,
                train_start=start,
                train_end=end,
                test_start=test_start,
                test_end=test_end,
                scoped=scoped,
            )
            feature_sets[fold_id] = full
            prefix_sets[fold_id] = prefix
            train_mask = ((time >= start) & (time <= end)).to_numpy()
            prefix_time = pd.to_datetime(prefix_frame["time"], errors="raise")
            prefix_train_mask = (
                (prefix_time >= start) & (prefix_time <= end)
            ).to_numpy()
            volatility = full[1][train_mask & np.isfinite(full[1])]
            calibrations[fold_id] = (
                calibrate_analog_selector(
                    full[0],
                    train_mask,
                    selector_quantile_bp=P1_STU0061_ANALOG_FAMILY.selector_quantile_bp,
                ),
                (
                    float(np.quantile(volatility, 1 / 3, method="higher")),
                    float(np.quantile(volatility, 2 / 3, method="higher")),
                ),
                calibrate_analog_selector(
                    prefix[0],
                    prefix_train_mask,
                    selector_quantile_bp=P1_STU0061_ANALOG_FAMILY.selector_quantile_bp,
                ),
            )
            compared = len(prefix[0])
            comparisons_by_key[(fold_id, profile_id)] = {
                "compared_row_count": compared,
                "fold_id": fold_id,
                "full_score_values_sha256": replay_v1._digest_score(
                    full[0][:compared]
                ),
                "prefix_score_values_sha256": replay_v1._digest_score(prefix[0]),
                "profile_id": profile_id,
            }
            del prefix_prepared
        for configuration in P1_STU0061_ANALOG_FAMILY.configurations():
            if configuration.profile_id != profile_id:
                continue
            subject = (
                analog_family_executable_scoped_v2(configuration).identity
                if scoped
                else analog_family_executable_v2(configuration).identity
            )
            captures: dict[tuple[str, str], Any] = {}

            def capture_simulation(**kwargs: Any) -> Any:
                result = simulate_fixed_hold(**kwargs)
                fold_id = str(kwargs["fold_id"])
                scope = "full" if kwargs["frame"] is frame else "prefix"
                key = (fold_id, scope)
                if key in captures:
                    raise RuntimeError("analog v2 simulation capture is not unique")
                captures[key] = result
                return result

            result = _evaluate_configuration(
                calibrations=calibrations,
                frame=frame,
                features=feature_sets[str(folds[0]["fold_id"])],
                fold_features=feature_sets,
                folds=folds,
                configuration=configuration,
                effective_spread=spread,
                prefix_features=prefix_sets,
                prefix_spreads=prefix_spreads,
                time=time,
                executable_id=subject,
                simulation_fn=capture_simulation,
            )
            expected_capture_keys = {
                (str(fold["fold_id"]), scope)
                for fold in folds
                for scope in ("full", "prefix")
            }
            if set(captures) != expected_capture_keys:
                raise RuntimeError("analog v2 simulation trace capture is incomplete")
            raw_metrics[subject] = dict(result.metrics)
            all_trades.extend(
                replay_v1._trade_rows(
                    configuration=configuration,
                    executable_id=subject,
                    simulations=captures,
                )
            )
            all_intents.extend(
                replay_v1._intent_rows(
                    configuration=configuration,
                    executable_id=subject,
                    simulations=captures,
                )
            )
        del (
            full_prepared,
            feature_sets,
            prefix_sets,
            calibrations,
            full,
            prefix,
            prefix_frame,
            prefix_time,
            prefix_train_mask,
            train_mask,
            volatility,
            captures,
            result,
        )
        gc.collect()
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
    trade_aggregates: dict[tuple[str, str, str], list[int]] = {}
    for trade in all_trades:
        key = (
            str(trade["configuration_id"]),
            str(trade["fold_id"]),
            str(trade["decision_time"])[:10],
        )
        values = trade_aggregates.setdefault(key, [0, 0, 0])
        values[0] += 1
        values[1] += int(trade["native_net_pnl_micropoints"])
        values[2] += int(trade["stress_net_pnl_micropoints"])
    inventory = (
        expected_analog_family_inventory_scoped_v2()
        if scoped
        else expected_analog_family_inventory_v2()
    )
    members = {str(item["configuration_id"]): item for item in inventory}
    eligible_rows: list[dict[str, object]] = []
    for configuration_id in sorted(members):
        member = members[configuration_id]
        for window in windows:
            for day in window["eligible_dates"]:
                values = trade_aggregates.get(
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
    comparisons = [
        comparisons_by_key[(str(window["fold_id"]), profile.profile_id)]
        for window in windows
        for profile in P1_STU0061_ANALOG_FAMILY.profiles
    ]
    contracts = analog_family_execution_contracts()
    trace: dict[str, object] = {
        "attribution": ANALOG_REPLAY_TRACE_ATTRIBUTION,
        "clock_contract": contracts["clock_contract"],
        "controls": ANALOG_REPLAY_CONTROLS,
        "cost_contract": contracts["cost_contract"],
        "dataset_sha256": DATASET_SHA256,
        "eligible_day_observations": eligible_rows,
        "family_id": P1_STU0061_ANALOG_FAMILY.family_id,
        "implementation_identities": (
            analog_family_trace_v2_implementation_identities()
        ),
        "intent_observations": all_intents,
        "invariance_comparisons": comparisons,
        "material_identity": OBSERVED_MATERIAL_ID,
        "ordered_family": list(inventory),
        "original_family_provenance": analog_original_family_provenance(),
        "protocol_id": ANALOG_STATE_TRACE_PROTOCOL_ID,
        "schema": ANALOG_FAMILY_TRACE_SCHEMA,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "trade_observations": all_trades,
        "windows": windows,
    }
    normalized = (
        validate_analog_family_trace_scoped_v2(trace)
        if scoped
        else validate_analog_family_trace_v2(trace)
    )
    parity_metrics = {
        analog_family_executable(configuration).identity: raw_metrics[
            (
                analog_family_executable_scoped_v2(configuration).identity
                if scoped
                else analog_family_executable_v2(configuration).identity
            )
        ]
        for configuration in P1_STU0061_ANALOG_FAMILY.configurations()
    }
    replay_v1.assert_frozen_stu0061_raw_metric_parity(parity_metrics)
    return normalized, raw_metrics


def compute_analog_family_trace_v2(
    repository_root: str | Path,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    """Compute the full-vector v1 parity trace with bounded allocations."""

    return _compute_analog_family_trace_v2(repository_root, scoped=False)


def compute_analog_family_trace_scoped_v2(
    repository_root: str | Path,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    """Compute the prospective decision-scoped family trace."""

    return _compute_analog_family_trace_v2(repository_root, scoped=True)


def trace_v2_is_exact_v1_semantic_parity(
    trace: Mapping[str, object],
    frozen_v1_trace: Mapping[str, object],
) -> bool:
    projected = _project_analog_v2_trace_to_v1(trace)
    validated_frozen = validate_analog_family_trace(frozen_v1_trace)
    return canonical_bytes(projected) == canonical_bytes(validated_frozen)


def trace_scoped_v2_is_exact_v1_decision_parity(
    trace: Mapping[str, object],
    frozen_v1_trace: Mapping[str, object],
) -> bool:
    """Compare all reachable decisions while allowing scope-specific score hashes."""

    projected = _project_analog_v2_trace_to_v1(trace, scoped=True)
    validated_frozen = validate_analog_family_trace(frozen_v1_trace)
    scoped_comparisons = projected.pop("invariance_comparisons")
    frozen_comparisons = validated_frozen.pop("invariance_comparisons")
    if not isinstance(scoped_comparisons, list) or not isinstance(
        frozen_comparisons,
        list,
    ):
        return False
    if len(scoped_comparisons) != len(frozen_comparisons):
        return False
    for scoped_row, frozen_row in zip(
        scoped_comparisons,
        frozen_comparisons,
        strict=True,
    ):
        if not isinstance(scoped_row, dict) or not isinstance(frozen_row, dict):
            return False
        identity_fields = ("compared_row_count", "fold_id", "profile_id")
        if any(scoped_row.get(name) != frozen_row.get(name) for name in identity_fields):
            return False
        if scoped_row.get("full_score_values_sha256") != scoped_row.get(
            "prefix_score_values_sha256"
        ):
            return False
    return canonical_bytes(projected) == canonical_bytes(validated_frozen)


__all__ = [
    "ANALOG_SCOPED_QUERY_SCOPE_ID",
    "analog_family_components_scoped_v2",
    "analog_family_components_v2",
    "analog_family_executable_scoped_v2",
    "analog_family_executable_v2",
    "analog_family_trace_v2_implementation_identities",
    "analog_replay_v2_bundle_sha256",
    "analog_replay_v2_implementation_sha256",
    "compute_analog_family_trace_scoped_v2",
    "compute_analog_family_trace_v2",
    "expected_analog_family_inventory_scoped_v2",
    "expected_analog_family_inventory_v2",
    "trace_scoped_v2_is_exact_v1_decision_parity",
    "trace_v2_is_exact_v1_semantic_parity",
    "validate_analog_family_trace_scoped_v2",
    "validate_analog_family_trace_v2",
]
