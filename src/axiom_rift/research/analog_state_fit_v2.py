"""Memory-bounded fold fitting for registered analog families.

The historical fitter in :mod:`analog_state_family` is part of already-bound
scientific evidence and therefore remains byte-stable.  This module provides a
new implementation identity with the same mathematical protocol while fixing
two throughput defects observed during the prospective STU-0061 replay:

* raw feature and forward-target construction can be shared across folds; and
* KD-tree queries are evaluated in bounded row chunks instead of allocating
  neighbour matrices for the complete development frame at once.

Callers must establish parity before treating this implementation as an
equivalent replacement for a historical component identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from axiom_rift.research.analog_state_family import (
    AnalogFamilySpec,
    raw_analog_features,
)
from axiom_rift.research.discovery import DiscoveryBoundaryError


DEFAULT_ANALOG_QUERY_CHUNK_ROWS = 50_000
_THIS_FILE = Path(__file__).resolve()


def analog_fit_v2_implementation_sha256() -> str:
    """Return the exact implementation identity for prospective bindings."""

    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _readonly(values: np.ndarray) -> np.ndarray:
    values.setflags(write=False)
    return values


@dataclass(frozen=True, slots=True)
class PreparedAnalogProfile:
    """One immutable profile feature matrix prepared once for many folds."""

    profile_id: str
    feature_protocol: str
    features: np.ndarray

    def __post_init__(self) -> None:
        if (
            type(self.profile_id) is not str
            or not self.profile_id
            or not self.profile_id.isascii()
            or type(self.feature_protocol) is not str
            or not self.feature_protocol
            or not self.feature_protocol.isascii()
            or not isinstance(self.features, np.ndarray)
            or self.features.ndim != 2
            or not self.features.flags.c_contiguous
            or self.features.flags.writeable
        ):
            raise ValueError("prepared analog profile is invalid")


@dataclass(frozen=True, slots=True)
class PreparedAnalogFrame:
    """Immutable shared arrays for fold fits over one exact frame prefix."""

    family_id: str
    horizon: int
    time_ns: np.ndarray
    future_time_ns: np.ndarray
    target: np.ndarray
    volatility: np.ndarray
    consecutive_run: np.ndarray
    profiles: tuple[PreparedAnalogProfile, ...]

    def __post_init__(self) -> None:
        arrays = (
            self.time_ns,
            self.future_time_ns,
            self.target,
            self.volatility,
            self.consecutive_run,
        )
        if (
            type(self.family_id) is not str
            or not self.family_id.isascii()
            or type(self.horizon) is not int
            or self.horizon < 1
            or any(not isinstance(values, np.ndarray) for values in arrays)
            or any(values.ndim != 1 for values in arrays)
            or len({len(values) for values in arrays}) != 1
            or any(values.flags.writeable for values in arrays)
            or type(self.profiles) is not tuple
            or not self.profiles
            or tuple(item.profile_id for item in self.profiles)
            != tuple(sorted({item.profile_id for item in self.profiles}))
            or any(len(item.features) != len(self.time_ns) for item in self.profiles)
        ):
            raise ValueError("prepared analog frame is invalid")

    def profile(self, profile_id: str) -> PreparedAnalogProfile:
        for profile in self.profiles:
            if profile.profile_id == profile_id:
                return profile
        raise KeyError(profile_id)


def _shared_frame_arrays(
    frame: pd.DataFrame,
    *,
    horizon: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    time = pd.to_datetime(frame["time"], errors="raise")
    if time.isna().any() or time.dt.tz is not None:
        raise DiscoveryBoundaryError("analog frame time is invalid")
    time_ns = time.to_numpy(dtype="datetime64[ns]").astype(np.int64, copy=False)
    if len(time_ns) < horizon + 1 or np.any(np.diff(time_ns) <= 0):
        raise DiscoveryBoundaryError("analog frame time is invalid")
    close = frame["close"].to_numpy(float)
    if len(close) != len(time_ns) or not np.isfinite(close).all() or np.any(close <= 0):
        raise DiscoveryBoundaryError("analog frame close is invalid")
    log_close = np.log(close)
    target = np.full(len(close), np.nan)
    target[:-horizon] = log_close[horizon:] - log_close[:-horizon]
    future_time_ns = np.full(len(time_ns), np.iinfo(np.int64).max, dtype=np.int64)
    future_time_ns[:-horizon] = time_ns[horizon:]
    return (
        _readonly(np.ascontiguousarray(time_ns)),
        _readonly(future_time_ns),
        _readonly(target),
    )


def prepare_analog_frame(
    frame: pd.DataFrame,
    *,
    family: AnalogFamilySpec,
    profile_ids: tuple[str, ...] | None = None,
) -> PreparedAnalogFrame:
    """Prepare exact causal features and shared targets once per frame.

    ``profile_ids`` permits streaming callers to prepare one prefix profile at
    a time.  The full-frame path normally omits it and shares preparation
    across every registered family profile.
    """

    if not isinstance(frame, pd.DataFrame) or not isinstance(family, AnalogFamilySpec):
        raise TypeError("analog preparation inputs are invalid")
    requested = (
        tuple(profile.profile_id for profile in family.profiles)
        if profile_ids is None
        else profile_ids
    )
    if (
        type(requested) is not tuple
        or not requested
        or requested != tuple(sorted(set(requested)))
    ):
        raise ValueError("analog profile request must be sorted and unique")
    time_ns, future_time_ns, target = _shared_frame_arrays(
        frame,
        horizon=family.horizon,
    )
    prepared_profiles: list[PreparedAnalogProfile] = []
    shared_volatility: np.ndarray | None = None
    shared_run: np.ndarray | None = None
    for profile_id in requested:
        profile = family.profile(profile_id)
        features, volatility, run = raw_analog_features(
            frame,
            feature_protocol=profile.feature_protocol,
        )
        features = _readonly(np.ascontiguousarray(features, dtype=float))
        volatility = np.ascontiguousarray(volatility, dtype=float)
        run = np.ascontiguousarray(run)
        if shared_volatility is None:
            shared_volatility = _readonly(volatility)
            shared_run = _readonly(run)
        elif not (
            np.array_equal(shared_volatility, volatility, equal_nan=True)
            and np.array_equal(shared_run, run)
        ):
            raise RuntimeError("analog profiles disagree on shared causal state")
        prepared_profiles.append(
            PreparedAnalogProfile(
                profile_id=profile_id,
                feature_protocol=profile.feature_protocol,
                features=features,
            )
        )
    if shared_volatility is None or shared_run is None:
        raise RuntimeError("analog preparation produced no profiles")
    return PreparedAnalogFrame(
        family_id=family.family_id,
        horizon=family.horizon,
        time_ns=time_ns,
        future_time_ns=future_time_ns,
        target=target,
        volatility=shared_volatility,
        consecutive_run=shared_run,
        profiles=tuple(prepared_profiles),
    )


def _fit_prepared_analog_fold(
    prepared: PreparedAnalogFrame,
    *,
    family: AnalogFamilySpec,
    profile_id: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    query_chunk_rows: int = DEFAULT_ANALOG_QUERY_CHUNK_ROWS,
    query_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fit one fold with bounded KD-tree query allocations.

    The neighbour ordering, self-neighbour exclusion, standardization, and
    returned score semantics intentionally match ``fit_fold_analog_family``.
    """

    if not isinstance(prepared, PreparedAnalogFrame) or not isinstance(
        family, AnalogFamilySpec
    ):
        raise TypeError("prepared analog fold inputs are invalid")
    if (
        prepared.family_id != family.family_id
        or prepared.horizon != family.horizon
        or type(query_chunk_rows) is not int
        or query_chunk_rows < family.neighbors + 1
    ):
        raise ValueError("prepared analog family or chunk binding drifted")
    profile = prepared.profile(profile_id)
    if profile.feature_protocol != family.profile(profile_id).feature_protocol:
        raise ValueError("prepared analog profile binding drifted")
    start = pd.Timestamp(train_start)
    end = pd.Timestamp(train_end)
    if start.tzinfo is not None or end.tzinfo is not None or start > end:
        raise ValueError("analog train boundary is invalid")
    start_ns = int(start.value)
    end_ns = int(end.value)
    features = profile.features
    valid = np.isfinite(features).all(axis=1)
    if query_mask is not None:
        if (
            not isinstance(query_mask, np.ndarray)
            or query_mask.dtype != np.bool_
            or query_mask.ndim != 1
            or len(query_mask) != len(features)
        ):
            raise ValueError("analog query mask is invalid")
        valid_queries = valid & query_mask
    else:
        valid_queries = valid
    train = (
        (prepared.time_ns >= start_ns)
        & (prepared.time_ns <= end_ns)
        & np.isfinite(prepared.target)
        & valid
        & (prepared.future_time_ns <= end_ns)
    )
    indices = np.flatnonzero(train)[:: family.library_stride]
    if len(indices) < family.neighbors + 100:
        raise DiscoveryBoundaryError("analog library too small")
    library = features[indices]
    mean = library.mean(axis=0)
    standard = library.std(axis=0, ddof=0)
    standard = np.where(standard > 0, standard, 1.0)
    standardized_library = (library - mean) / standard
    tree = cKDTree(standardized_library)
    score = np.full(len(features), np.nan)
    query_rows = np.flatnonzero(valid_queries)
    for offset in range(0, len(query_rows), query_chunk_rows):
        rows = query_rows[offset : offset + query_chunk_rows]
        query = (features[rows] - mean) / standard
        distances, neighbor_offsets = tree.query(
            query,
            k=family.neighbors + 1,
            workers=1,
        )
        del distances, query
        neighbor_rows = indices[neighbor_offsets]
        del neighbor_offsets
        neighbor_targets = prepared.target[neighbor_rows]
        self_match = neighbor_rows == rows[:, None]
        has_self = self_match.any(axis=1)
        neighbor_targets = np.where(self_match, np.nan, neighbor_targets)
        score[rows] = np.where(
            has_self,
            np.nanmean(neighbor_targets, axis=1),
            neighbor_targets[:, : family.neighbors].mean(axis=1),
        )
    score[prepared.consecutive_run < 193] = np.nan
    return score, prepared.volatility, prepared.consecutive_run


def fit_prepared_analog_fold(
    prepared: PreparedAnalogFrame,
    *,
    family: AnalogFamilySpec,
    profile_id: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    query_chunk_rows: int = DEFAULT_ANALOG_QUERY_CHUNK_ROWS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Exact full-vector parity path for explicit certification work."""

    return _fit_prepared_analog_fold(
        prepared,
        family=family,
        profile_id=profile_id,
        train_start=train_start,
        train_end=train_end,
        query_chunk_rows=query_chunk_rows,
        query_mask=None,
    )


def fit_prepared_analog_fold_scoped(
    prepared: PreparedAnalogFrame,
    *,
    family: AnalogFamilySpec,
    profile_id: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    query_chunk_rows: int = DEFAULT_ANALOG_QUERY_CHUNK_ROWS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Query only train-calibration and reachable test-decision rows.

    This is a distinct prospective protocol.  The caller cannot supply an
    arbitrary mask: the exact train and test windows derive the only permitted
    query scope from the registered split.
    """

    start = pd.Timestamp(train_start)
    end = pd.Timestamp(train_end)
    decision_start = pd.Timestamp(test_start)
    decision_end = pd.Timestamp(test_end)
    boundaries = (start, end, decision_start, decision_end)
    if (
        any(value.tzinfo is not None for value in boundaries)
        or not start <= end < decision_start <= decision_end
    ):
        raise ValueError("analog scoped query boundary is invalid")
    query_mask = (
        ((prepared.time_ns >= int(start.value)) & (prepared.time_ns <= int(end.value)))
        | (
            (prepared.time_ns >= int(decision_start.value))
            & (prepared.time_ns <= int(decision_end.value))
        )
    )
    return _fit_prepared_analog_fold(
        prepared,
        family=family,
        profile_id=profile_id,
        train_start=start,
        train_end=end,
        query_chunk_rows=query_chunk_rows,
        query_mask=query_mask,
    )


def fit_fold_analog_family_v2(
    frame: pd.DataFrame,
    *,
    family: AnalogFamilySpec,
    profile_id: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    query_chunk_rows: int = DEFAULT_ANALOG_QUERY_CHUNK_ROWS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compatibility entry point for one fold over an unprepared frame."""

    prepared = prepare_analog_frame(
        frame,
        family=family,
        profile_ids=(profile_id,),
    )
    return fit_prepared_analog_fold(
        prepared,
        family=family,
        profile_id=profile_id,
        train_start=train_start,
        train_end=train_end,
        query_chunk_rows=query_chunk_rows,
    )


def fit_fold_analog_family_scoped_v2(
    frame: pd.DataFrame,
    *,
    family: AnalogFamilySpec,
    profile_id: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    query_chunk_rows: int = DEFAULT_ANALOG_QUERY_CHUNK_ROWS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Unprepared-frame entry point for the prospective scoped protocol."""

    prepared = prepare_analog_frame(
        frame,
        family=family,
        profile_ids=(profile_id,),
    )
    return fit_prepared_analog_fold_scoped(
        prepared,
        family=family,
        profile_id=profile_id,
        train_start=train_start,
        train_end=train_end,
        test_start=test_start,
        test_end=test_end,
        query_chunk_rows=query_chunk_rows,
    )


__all__ = [
    "DEFAULT_ANALOG_QUERY_CHUNK_ROWS",
    "PreparedAnalogFrame",
    "PreparedAnalogProfile",
    "analog_fit_v2_implementation_sha256",
    "fit_fold_analog_family_v2",
    "fit_fold_analog_family_scoped_v2",
    "fit_prepared_analog_fold",
    "fit_prepared_analog_fold_scoped",
    "prepare_analog_frame",
]
