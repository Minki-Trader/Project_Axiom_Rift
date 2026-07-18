"""Observed-development producer for a corrected historical pair trace.

The producer reconstructs the registered event-label signal independently of
the retired cost-aware discovery runner.  It emits one common pre-policy
candidate stream in both full and test-prefix scopes, then delegates policy
occupancy, causal cost repair, spread gating, and trade materialization to the
neutral pair trace core.

The returned producer manifest is reproducibility evidence only.  It carries
no scientific decision authority and never writes operational state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.cost_aware_execution_pair import (
    COST_AWARE_EXECUTION_PAIR_HOLDING_BARS,
    COST_AWARE_EXECUTION_PAIR_SELECTOR_QUANTILE_BP,
    COST_AWARE_EXECUTION_PAIR_SPREAD_LIMIT_MILLI,
    COST_AWARE_EXECUTION_PAIR_SPREAD_REFERENCE_BARS,
    COST_AWARE_EXECUTION_PAIR_SPREAD_REFERENCE_MIN_OBSERVATIONS,
    cost_aware_execution_pair_executable_map,
    cost_aware_execution_pair_producer_implementation_identities,
)
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_HISTORICAL_CONTEXT_ADJUSTMENT_AUTHORITY,
    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
    CostAwareExecutionProtocolDefinition,
)
from axiom_rift.research.cost_aware_execution_trace import (
    compute_cost_aware_execution_pair_trace_snapshot,
)
from axiom_rift.research.cost_aware_execution_trace_snapshot import (
    CostAwareExecutionPairTraceSnapshot,
)
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    _fold_payloads,
    _validate_engine_environment,
    _validate_fold_payloads,
    _validate_production_data,
)
from axiom_rift.research.event_label_discovery import (
    HORIZON,
    _fit_model,
    _labels,
    _raw_features,
    _score,
    calibrate_selector,
)
from axiom_rift.research.selection_inference import HistoricalSearchContext


COST_AWARE_EXECUTION_PAIR_PRODUCER_MANIFEST_SCHEMA = (
    "cost_aware_execution_pair_trace_producer.v1"
)
_SOURCE_HASH_SCHEMA = "cost_aware_execution_source_input_columnar_sha256.v1"
_ARRAY_HASH_SCHEMA = "numpy_float64_little_endian_sha256.v1"
_FIVE_MINUTES = pd.Timedelta(minutes=5)
_SCALING_TOLERANCE = 1e-4
_SOURCE_FIELDS = {
    "bar_index",
    "bar_open_time",
    "open_micropoints",
    "raw_spread_millipoints",
}
_THIS_FILE = Path(__file__).resolve()


class CostAwareExecutionPairEngineError(ValueError):
    """The prospective pair producer boundary is invalid."""


def cost_aware_execution_pair_engine_implementation_sha256() -> str:
    """Return the exact source identity bound by the pair Executables."""

    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _iso(value: pd.Timestamp) -> str:
    return value.to_pydatetime().isoformat(timespec="seconds")


def _canonical_sha256(value: object) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _array_sha256(value: np.ndarray) -> str:
    array = np.asarray(value, dtype=np.float64)
    if np.isinf(array).any():
        raise CostAwareExecutionPairEngineError(
            "producer provenance array contains infinity"
        )
    normalized = np.array(array, dtype="<f8", order="C", copy=True)
    normalized[np.isnan(normalized)] = np.nan
    digest = sha256()
    digest.update(
        canonical_bytes(
            {
                "dtype": "float64_little_endian",
                "schema": _ARRAY_HASH_SCHEMA,
                "shape": [int(item) for item in normalized.shape],
            }
        )
    )
    digest.update(normalized.tobytes(order="C"))
    return digest.hexdigest()


def _timestamps(frame: pd.DataFrame) -> pd.DatetimeIndex:
    if "time" not in frame:
        raise CostAwareExecutionPairEngineError("source time column is missing")
    try:
        values = pd.DatetimeIndex(pd.to_datetime(frame["time"], errors="raise"))
    except (TypeError, ValueError) as exc:
        raise CostAwareExecutionPairEngineError(
            "source time column is invalid"
        ) from exc
    if values.tz is not None or values.hasnans:
        raise CostAwareExecutionPairEngineError(
            "source must use finite naive broker timestamps"
        )
    time_ns = values.asi8
    if (
        len(values) == 0
        or (len(values) > 1 and np.any(np.diff(time_ns) <= 0))
        or np.any(time_ns % 1_000_000_000 != 0)
    ):
        raise CostAwareExecutionPairEngineError(
            "source timestamps must be strictly increasing whole seconds"
        )
    return values


def _numeric_column(
    frame: pd.DataFrame,
    name: str,
    *,
    positive: bool,
) -> np.ndarray:
    if name not in frame:
        raise CostAwareExecutionPairEngineError(f"source {name} column is missing")
    try:
        values = pd.to_numeric(frame[name], errors="raise").to_numpy(float)
    except (TypeError, ValueError) as exc:
        raise CostAwareExecutionPairEngineError(
            f"source {name} column is invalid"
        ) from exc
    if not np.isfinite(values).all() or (
        np.any(values <= 0) if positive else np.any(values < 0)
    ):
        qualifier = "positive" if positive else "non-negative"
        raise CostAwareExecutionPairEngineError(
            f"source {name} values must be finite and {qualifier}"
        )
    return values


def _scaled_integer(
    values: np.ndarray,
    *,
    scale: int,
    name: str,
) -> np.ndarray:
    scaled = np.asarray(values, dtype=np.float64) * scale
    rounded = np.rint(scaled)
    if (
        np.any(np.abs(scaled - rounded) > _SCALING_TOLERANCE)
        or np.any(np.abs(rounded) > np.iinfo(np.int64).max)
    ):
        raise CostAwareExecutionPairEngineError(
            f"source {name} is not exactly representable at the registered scale"
        )
    return rounded.astype(np.int64)


class _SourceObservationSequence(Sequence[Mapping[str, object]]):
    """Compact immutable view over an ordered global-index source union."""

    __slots__ = ("_bar_index", "_open", "_spread", "_time_ns")

    def __init__(
        self,
        *,
        bar_index: np.ndarray,
        time_ns: np.ndarray,
        open_micropoints: np.ndarray,
        raw_spread_millipoints: np.ndarray,
    ) -> None:
        count = len(time_ns)
        if (
            len(bar_index) != count
            or len(open_micropoints) != count
            or len(raw_spread_millipoints) != count
        ):
            raise CostAwareExecutionPairEngineError(
                "source observation columns differ in length"
            )
        self._bar_index = np.array(bar_index, dtype=np.int64, copy=True)
        self._time_ns = np.array(time_ns, dtype=np.int64, copy=True)
        self._open = np.array(open_micropoints, dtype=np.int64, copy=True)
        self._spread = np.array(
            raw_spread_millipoints, dtype=np.int64, copy=True
        )
        if (
            count == 0
            or np.any(self._bar_index < 0)
            or (count > 1 and np.any(np.diff(self._bar_index) <= 0))
            or (count > 1 and np.any(np.diff(self._time_ns) <= 0))
        ):
            raise CostAwareExecutionPairEngineError(
                "source union indices and timestamps must be strictly increasing"
            )
        self._bar_index.flags.writeable = False
        self._time_ns.flags.writeable = False
        self._open.flags.writeable = False
        self._spread.flags.writeable = False

    def __len__(self) -> int:
        return len(self._time_ns)

    def __getitem__(
        self, index: int | slice
    ) -> Mapping[str, object] | tuple[Mapping[str, object], ...]:
        if isinstance(index, slice):
            return tuple(self[item] for item in range(*index.indices(len(self))))
        if type(index) is not int:
            raise TypeError("source observation index must be an integer")
        normalized = index + len(self) if index < 0 else index
        if normalized < 0 or normalized >= len(self):
            raise IndexError(index)
        return {
            "bar_index": int(self._bar_index[normalized]),
            "bar_open_time": _iso(pd.Timestamp(int(self._time_ns[normalized]))),
            "open_micropoints": int(self._open[normalized]),
            "raw_spread_millipoints": int(self._spread[normalized]),
        }

    def source_input_sha256(self) -> str:
        return _source_columns_sha256(
            bar_index=self._bar_index,
            time_ns=self._time_ns,
            open_micropoints=self._open,
            raw_spread_millipoints=self._spread,
        )


def _source_columns(
    frame: pd.DataFrame,
) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
    times = _timestamps(frame)
    opened = _numeric_column(frame, "open", positive=True)
    spread = _numeric_column(frame, "spread", positive=False)
    return (
        times,
        _scaled_integer(opened, scale=1_000_000, name="open"),
        _scaled_integer(spread, scale=1_000, name="spread"),
    )


def _source_observations(
    frame: pd.DataFrame,
    *,
    bar_indices: np.ndarray | None = None,
) -> _SourceObservationSequence:
    times, opened, spread = _source_columns(frame)
    indices = (
        np.arange(len(frame), dtype=np.int64)
        if bar_indices is None
        else np.asarray(bar_indices, dtype=np.int64)
    )
    if len(indices) == 0 or np.any(indices < 0) or np.any(indices >= len(frame)):
        raise CostAwareExecutionPairEngineError(
            "source union bar indices are outside the observed frame"
        )
    return _SourceObservationSequence(
        bar_index=indices,
        time_ns=times.asi8[indices],
        open_micropoints=opened[indices],
        raw_spread_millipoints=spread[indices],
    )


def _source_columns_sha256(
    *,
    bar_index: np.ndarray,
    time_ns: np.ndarray,
    open_micropoints: np.ndarray,
    raw_spread_millipoints: np.ndarray,
) -> str:
    count = len(time_ns)
    if (
        len(bar_index) != count
        or len(open_micropoints) != count
        or len(raw_spread_millipoints) != count
    ):
        raise CostAwareExecutionPairEngineError(
            "source hash columns differ in length"
        )
    digest = sha256()
    digest.update(
        canonical_bytes(
            {
                "fields": sorted(_SOURCE_FIELDS),
                "row_count": count,
                "schema": _SOURCE_HASH_SCHEMA,
            }
        )
    )
    for values in (
        bar_index,
        time_ns,
        open_micropoints,
        raw_spread_millipoints,
    ):
        digest.update(np.asarray(values, dtype="<i8").tobytes(order="C"))
    return digest.hexdigest()


def _source_input_sha256(rows: Sequence[Mapping[str, object]]) -> str:
    if isinstance(rows, _SourceObservationSequence):
        return rows.source_input_sha256()
    time_ns: list[int] = []
    opened: list[int] = []
    spreads: list[int] = []
    indices: list[int] = []
    for raw in rows:
        if type(raw) is not dict or set(raw) != _SOURCE_FIELDS:
            raise CostAwareExecutionPairEngineError(
                "source hash row schema is invalid"
            )
        bar_index = raw["bar_index"]
        if (
            type(bar_index) is not int
            or bar_index < 0
            or (indices and bar_index <= indices[-1])
        ):
            raise CostAwareExecutionPairEngineError(
                "source hash requires strictly increasing global bar indices"
            )
        try:
            timestamp = pd.Timestamp(raw["bar_open_time"])
        except (TypeError, ValueError) as exc:
            raise CostAwareExecutionPairEngineError(
                "source hash timestamp is invalid"
            ) from exc
        open_value = raw["open_micropoints"]
        spread_value = raw["raw_spread_millipoints"]
        if (
            timestamp.tzinfo is not None
            or type(open_value) is not int
            or open_value < 1
            or type(spread_value) is not int
            or spread_value < 0
        ):
            raise CostAwareExecutionPairEngineError(
                "source hash row value is invalid"
            )
        time_ns.append(int(timestamp.value))
        indices.append(bar_index)
        opened.append(open_value)
        spreads.append(spread_value)
    return _source_columns_sha256(
        bar_index=np.asarray(indices, dtype=np.int64),
        time_ns=np.asarray(time_ns, dtype=np.int64),
        open_micropoints=np.asarray(opened, dtype=np.int64),
        raw_spread_millipoints=np.asarray(spreads, dtype=np.int64),
    )


def _fold_window(
    fold: Mapping[str, Any], role: str
) -> tuple[pd.Timestamp, pd.Timestamp]:
    try:
        window = fold[role]
        if not isinstance(window, Mapping):
            raise TypeError
        start = pd.Timestamp(window["start"])
        end = pd.Timestamp(window["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CostAwareExecutionPairEngineError(
            f"fold {role} window is invalid"
        ) from exc
    if start.tzinfo is not None or end.tzinfo is not None or start > end:
        raise CostAwareExecutionPairEngineError(
            f"fold {role} window is invalid"
        )
    return start, end


def _window_inputs(
    times: pd.DatetimeIndex,
    folds: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    for fold in folds:
        fold_id = str(fold.get("fold_id", ""))
        if not fold_id or not fold_id.isascii():
            raise CostAwareExecutionPairEngineError("fold identity is invalid")
        start, end = _fold_window(fold, "test_oos")
        selected = times[(times >= start) & (times <= end)]
        eligible = tuple(
            item.date().isoformat()
            for item in sorted(pd.DatetimeIndex(selected.normalize().unique()))
        )
        if not eligible:
            raise CostAwareExecutionPairEngineError(
                "fold test window contains no source observations"
            )
        result.append(
            {
                "eligible_dates": list(eligible),
                "fold_id": fold_id,
                "test_end": _iso(end),
                "test_start": _iso(start),
            }
        )
    canonical_bytes(result)
    return tuple(result)


def _candidate_inputs_for_scope(
    *,
    times: pd.DatetimeIndex,
    score: np.ndarray,
    volatility: np.ndarray,
    threshold: float,
    regime_cutoffs: tuple[float, float],
    fold_id: str,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    scope: str,
) -> tuple[dict[str, object], ...]:
    """Emit all selected common candidates before policy occupancy or gates."""

    score = np.asarray(score, dtype=float)
    volatility = np.asarray(volatility, dtype=float)
    if (
        scope not in {"full", "prefix"}
        or len(score) != len(times)
        or len(volatility) != len(times)
        or not np.isfinite(threshold)
        or threshold < 0
        or len(regime_cutoffs) != 2
        or not np.isfinite(regime_cutoffs).all()
        or regime_cutoffs[0] > regime_cutoffs[1]
    ):
        raise CostAwareExecutionPairEngineError(
            "candidate producer inputs are invalid"
        )
    eligible = np.flatnonzero(
        np.asarray((times >= test_start) & (times <= test_end), dtype=bool)
        & np.isfinite(score)
    )
    rows: list[dict[str, object]] = []
    for decision_index in eligible:
        if abs(float(score[decision_index])) < threshold:
            continue
        direction = int(np.sign(score[decision_index]))
        if direction == 0:
            continue
        entry_index = int(decision_index) + 1
        exit_index = entry_index + COST_AWARE_EXECUTION_PAIR_HOLDING_BARS
        if exit_index >= len(times) or times[exit_index] > test_end:
            continue
        decision_volatility = float(volatility[decision_index])
        if not np.isfinite(decision_volatility):
            raise CostAwareExecutionPairEngineError(
                "selected candidate volatility is not finite"
            )
        regime = (
            "low"
            if decision_volatility <= regime_cutoffs[0]
            else "high"
            if decision_volatility >= regime_cutoffs[1]
            else "middle"
        )
        rows.append(
            {
                "decision_bar_index": int(decision_index),
                "decision_time": _iso(times[decision_index] + _FIVE_MINUTES),
                "direction": direction,
                "fold_id": fold_id,
                "ordinal": len(rows) + 1,
                "regime": regime,
                "scope": scope,
            }
        )
    canonical_bytes(rows)
    return tuple(rows)


def _common_candidates(
    rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {name: value for name, value in row.items() if name != "scope"}
        for row in rows
    )


def _candidate_source_bar_indices(
    candidates: Sequence[Mapping[str, object]],
    *,
    source_row_count: int,
) -> np.ndarray:
    """Return the merged 576-lookback, predecessor, and fixed-path union."""

    if type(source_row_count) is not int or source_row_count < 1:
        raise CostAwareExecutionPairEngineError(
            "source row count must be a positive integer"
        )
    intervals: set[tuple[int, int]] = set()
    history = 2 * COST_AWARE_EXECUTION_PAIR_SPREAD_REFERENCE_BARS
    for candidate in candidates:
        decision = candidate.get("decision_bar_index")
        if type(decision) is not int or decision < 0:
            raise CostAwareExecutionPairEngineError(
                "candidate source union decision index is invalid"
            )
        exit_index = decision + 1 + COST_AWARE_EXECUTION_PAIR_HOLDING_BARS
        if exit_index >= source_row_count:
            raise CostAwareExecutionPairEngineError(
                "candidate source union path exceeds the observed frame"
            )
        context_start = max(0, decision - history)
        predecessor_start = context_start - 1 if context_start > 0 else 0
        intervals.add((predecessor_start, exit_index))
    if not intervals:
        raise CostAwareExecutionPairEngineError(
            "candidate source union requires at least one candidate"
        )
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + 1:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return np.concatenate(
        [
            np.arange(start, end + 1, dtype=np.int64)
            for start, end in merged
        ]
    )


def _model_manifest(
    model: tuple[np.ndarray, np.ndarray, np.ndarray, float]
) -> dict[str, object]:
    mean, std, beta, intercept = model
    values = tuple(np.asarray(item, dtype=float) for item in (mean, std, beta))
    if any(not np.isfinite(item).all() for item in values) or not np.isfinite(
        intercept
    ):
        raise CostAwareExecutionPairEngineError("fold model is not finite")
    payload = {
        "coefficient_hex": [float(item).hex() for item in values[2]],
        "feature_mean_hex": [float(item).hex() for item in values[0]],
        "feature_population_std_hex": [
            float(item).hex() for item in values[1]
        ],
        "intercept_hex": float(intercept).hex(),
        "ridge_penalty_hex": float(1.0).hex(),
    }
    return {**payload, "model_sha256": _canonical_sha256(payload)}


@dataclass(frozen=True, slots=True)
class _PairTraceInputs:
    windows: tuple[dict[str, object], ...]
    source_observations: Sequence[Mapping[str, object]]
    candidate_observations: tuple[dict[str, object], ...]
    fold_provenance: tuple[dict[str, object], ...]
    feature_provenance: dict[str, object]


def _build_trace_inputs(
    frame: pd.DataFrame,
    folds: Sequence[Mapping[str, Any]],
) -> _PairTraceInputs:
    """Reproduce the exact registered signal and its append proof inputs."""

    times, open_micropoints, raw_spread_millipoints = _source_columns(frame)
    _numeric_column(frame, "close", positive=True)
    windows = _window_inputs(times, folds)

    full_features, full_volatility, full_run = _raw_features(frame)
    label = _labels(frame, full_volatility, full_run)[
        "first_passage_label_48"
    ]
    future_time = pd.Series(times).shift(-(HORIZON + 1))
    candidates: list[dict[str, object]] = []
    provenance: list[dict[str, object]] = []

    for fold in folds:
        fold_id = str(fold["fold_id"])
        train_start, train_end = _fold_window(fold, "train_is")
        test_start, test_end = _fold_window(fold, "test_oos")
        prefix_end = int(times.searchsorted(test_end, side="right"))
        prefix_frame = frame.iloc[:prefix_end]
        prefix_times = times[:prefix_end]
        prefix_features, prefix_volatility, prefix_run = _raw_features(
            prefix_frame
        )
        if not (
            np.array_equal(
                full_features[:prefix_end], prefix_features, equal_nan=True
            )
            and np.array_equal(
                full_volatility[:prefix_end],
                prefix_volatility,
                equal_nan=True,
            )
            and np.array_equal(full_run[:prefix_end], prefix_run)
        ):
            raise CostAwareExecutionPairEngineError(
                "past-only feature append invariance failed"
            )

        selector_mask = np.asarray(
            (times >= train_start) & (times <= train_end), dtype=bool
        )
        train_mask = selector_mask & np.asarray(
            (future_time <= train_end).fillna(False), dtype=bool
        )
        model = _fit_model(
            features=full_features,
            label=label,
            train_mask=train_mask,
        )
        full_score = _score(full_features, model)
        prefix_score = _score(prefix_features, model)
        if not np.array_equal(
            full_score[:prefix_end], prefix_score, equal_nan=True
        ):
            raise CostAwareExecutionPairEngineError(
                "fold score append invariance failed"
            )
        prefix_selector_mask = np.asarray(
            (prefix_times >= train_start) & (prefix_times <= train_end),
            dtype=bool,
        )
        full_threshold = calibrate_selector(full_score, selector_mask)
        prefix_threshold = calibrate_selector(
            prefix_score, prefix_selector_mask
        )
        if full_threshold.hex() != prefix_threshold.hex():
            raise CostAwareExecutionPairEngineError(
                "selector append invariance failed"
            )
        volatility_values = full_volatility[
            train_mask & np.isfinite(full_volatility)
        ]
        if len(volatility_values) == 0:
            raise CostAwareExecutionPairEngineError(
                "fold volatility calibration set is empty"
            )
        cutoffs = (
            float(
                np.quantile(volatility_values, 1 / 3, method="higher")
            ),
            float(
                np.quantile(volatility_values, 2 / 3, method="higher")
            ),
        )
        full_candidates = _candidate_inputs_for_scope(
            times=times,
            score=full_score,
            volatility=full_volatility,
            threshold=full_threshold,
            regime_cutoffs=cutoffs,
            fold_id=fold_id,
            test_start=test_start,
            test_end=test_end,
            scope="full",
        )
        prefix_candidates = _candidate_inputs_for_scope(
            times=prefix_times,
            score=prefix_score,
            volatility=prefix_volatility,
            threshold=prefix_threshold,
            regime_cutoffs=cutoffs,
            fold_id=fold_id,
            test_start=test_start,
            test_end=test_end,
            scope="prefix",
        )
        common = _common_candidates(full_candidates)
        if common != _common_candidates(prefix_candidates):
            raise CostAwareExecutionPairEngineError(
                "full and prefix common candidates differ"
            )
        candidates.extend(dict(item) for item in full_candidates)
        candidates.extend(dict(item) for item in prefix_candidates)
        provenance.append(
            {
                "candidate_common_sha256": _canonical_sha256(list(common)),
                "candidate_count": len(common),
                "fold_id": fold_id,
                "full_score_sha256": _array_sha256(full_score),
                "full_threshold_hex": full_threshold.hex(),
                "model": _model_manifest(model),
                "prefix_end_bar_index_exclusive": prefix_end,
                "prefix_feature_sha256": _array_sha256(prefix_features),
                "prefix_score_sha256": _array_sha256(prefix_score),
                "prefix_threshold_hex": prefix_threshold.hex(),
                "regime_cutoff_hex": [item.hex() for item in cutoffs],
                "test_end": _iso(test_end),
                "test_start": _iso(test_start),
                "train_end": _iso(train_end),
                "train_start": _iso(train_start),
            }
        )

    if not candidates:
        raise CostAwareExecutionPairEngineError(
            "registered signal produced no common candidates"
        )
    ordered_candidates = tuple(
        sorted(
            candidates,
            key=lambda item: (
                str(item["fold_id"]),
                str(item["scope"]),
                int(item["ordinal"]),
            ),
        )
    )
    canonical_bytes(list(ordered_candidates))
    feature_provenance = {
        "feature_matrix_sha256": _array_sha256(full_features),
        "feature_protocol": "fixed_multiscale_return_path.v1",
        "first_passage_label_sha256": _array_sha256(label),
        "label_profile": "first_passage_label_48",
        "selector_quantile_bp": COST_AWARE_EXECUTION_PAIR_SELECTOR_QUANTILE_BP,
        "volatility_sha256": _array_sha256(full_volatility),
    }
    canonical_bytes(feature_provenance)
    source_indices = _candidate_source_bar_indices(
        ordered_candidates,
        source_row_count=len(frame),
    )
    source = _SourceObservationSequence(
        bar_index=source_indices,
        time_ns=times.asi8[source_indices],
        open_micropoints=open_micropoints[source_indices],
        raw_spread_millipoints=raw_spread_millipoints[source_indices],
    )
    return _PairTraceInputs(
        windows=windows,
        source_observations=source,
        candidate_observations=ordered_candidates,
        fold_provenance=tuple(provenance),
        feature_provenance=feature_provenance,
    )


def _definition_context_boundary(
    definition: CostAwareExecutionProtocolDefinition,
    historical_context: HistoricalSearchContext,
) -> int:
    if not isinstance(definition, CostAwareExecutionProtocolDefinition):
        raise TypeError("cost-aware pair definition is not typed")
    if not isinstance(historical_context, HistoricalSearchContext):
        raise TypeError("cost-aware historical context is not typed")
    manifest = definition.manifest()
    inference = manifest.get("inference")
    if not isinstance(inference, Mapping):
        raise CostAwareExecutionPairEngineError(
            "protocol inference boundary is missing"
        )
    original_end = inference.get(
        "original_family_end_global_exposure_count"
    )
    if (
        original_end
        != COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        or inference.get("historical_context_adjustment_authority")
        != COST_AWARE_EXECUTION_HISTORICAL_CONTEXT_ADJUSTMENT_AUTHORITY
        or historical_context.prior_global_exposure_count < original_end
    ):
        raise CostAwareExecutionPairEngineError(
            "historical context and original family end are not separated"
        )
    expected = cost_aware_execution_pair_executable_map(
        historical_family=definition.historical_family,
        historical_context_prior_global_exposure_count=(
            historical_context.prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=original_end,
    )
    by_policy = {
        configuration.execution_policy: executable_id
        for executable_id, configuration in expected.items()
    }
    expected_order = (
        by_policy["unconditional_next_open"],
        by_policy["causal_spread_abstention"],
    )
    if definition.prospective_executable_ids != expected_order:
        raise CostAwareExecutionPairEngineError(
            "protocol members do not match the corrected pair Executables"
        )
    return original_end


@dataclass(frozen=True, slots=True)
class CostAwareExecutionPairTraceProduction:
    """One neutral trace plus its non-authoritative producer provenance."""

    trace: CostAwareExecutionPairTraceSnapshot
    producer_manifest: dict[str, object]


def _producer_manifest(
    *,
    definition: CostAwareExecutionProtocolDefinition,
    historical_context: HistoricalSearchContext,
    original_family_end_global_exposure_count: int,
    inputs: _PairTraceInputs,
    trace: Mapping[str, object] | CostAwareExecutionPairTraceSnapshot,
) -> dict[str, object]:
    identities = cost_aware_execution_pair_producer_implementation_identities()
    identities = {
        **identities,
        "pair_engine_sha256": (
            cost_aware_execution_pair_engine_implementation_sha256()
        ),
    }
    manifest = {
        "candidate_input_count": len(inputs.candidate_observations),
        "candidate_input_sha256": _canonical_sha256(
            list(inputs.candidate_observations)
        ),
        "dataset_sha256": DATASET_SHA256,
        "engine_environment": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "python": ".".join(str(item) for item in sys.version_info[:3]),
            "scipy": scipy.__version__,
        },
        "feature_provenance": dict(inputs.feature_provenance),
        "fold_provenance": [dict(item) for item in inputs.fold_provenance],
        "historical_context": {
            "current": historical_context.manifest(),
            "original_family_end_global_exposure_count": (
                original_family_end_global_exposure_count
            ),
            "separation": "current_context_distinct_from_original_family_end",
        },
        "implementation_identities": dict(sorted(identities.items())),
        "material_identity": OBSERVED_MATERIAL_ID,
        "producer_role": (
            "reproducibility_only_never_scientific_decision_authority"
        ),
        "prospective_family_id": definition.prospective_family_id,
        "protocol_definition_id": definition.identity,
        "protocol_id": definition.protocol_id,
        "schema": COST_AWARE_EXECUTION_PAIR_PRODUCER_MANIFEST_SCHEMA,
        "source_input_count": len(inputs.source_observations),
        "source_input_hash_schema": _SOURCE_HASH_SCHEMA,
        "source_input_sha256": _source_input_sha256(
            inputs.source_observations
        ),
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "trace_input_contract": {
            "candidate_stage": "common_pre_policy_before_occupancy_and_gates",
            "holding_bars": COST_AWARE_EXECUTION_PAIR_HOLDING_BARS,
            "source_context_history_bars": (
                2 * COST_AWARE_EXECUTION_PAIR_SPREAD_REFERENCE_BARS
            ),
            "source_union": (
                "candidate_context_predecessor_through_fixed_hold_exit"
            ),
            "spread_limit_milli": (
                COST_AWARE_EXECUTION_PAIR_SPREAD_LIMIT_MILLI
            ),
            "spread_reference_bars": (
                COST_AWARE_EXECUTION_PAIR_SPREAD_REFERENCE_BARS
            ),
            "spread_reference_min_observations": (
                COST_AWARE_EXECUTION_PAIR_SPREAD_REFERENCE_MIN_OBSERVATIONS
            ),
        },
        "trace_sha256": (
            trace.sha256
            if isinstance(trace, CostAwareExecutionPairTraceSnapshot)
            else _canonical_sha256(dict(trace))
        ),
        "window_input_count": len(inputs.windows),
        "window_input_sha256": _canonical_sha256(list(inputs.windows)),
    }
    canonical_bytes(manifest)
    return manifest


def produce_cost_aware_execution_pair_trace(
    repository_root: str | Path,
    *,
    definition: CostAwareExecutionProtocolDefinition,
    historical_context: HistoricalSearchContext,
) -> CostAwareExecutionPairTraceProduction:
    """Produce the corrected pair's Job-neutral observed-development trace."""

    original_end = _definition_context_boundary(
        definition, historical_context
    )
    _validate_engine_environment()
    data = load_observed_development(Path(repository_root).resolve())
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    inputs = _build_trace_inputs(data.frame, folds)
    trace = compute_cost_aware_execution_pair_trace_snapshot(
        definition=definition,
        dataset_sha256=DATASET_SHA256,
        split_artifact_sha256=ROLLING_SPLIT_SHA256,
        material_identity=OBSERVED_MATERIAL_ID,
        windows=inputs.windows,
        source_observations=inputs.source_observations,
        candidate_observations=inputs.candidate_observations,
        historical_context=historical_context,
    )
    manifest = _producer_manifest(
        definition=definition,
        historical_context=historical_context,
        original_family_end_global_exposure_count=original_end,
        inputs=inputs,
        trace=trace,
    )
    return CostAwareExecutionPairTraceProduction(
        trace=trace,
        producer_manifest=manifest,
    )


__all__ = [
    "COST_AWARE_EXECUTION_PAIR_PRODUCER_MANIFEST_SCHEMA",
    "CostAwareExecutionPairEngineError",
    "CostAwareExecutionPairTraceProduction",
    "cost_aware_execution_pair_engine_implementation_sha256",
    "produce_cost_aware_execution_pair_trace",
]
