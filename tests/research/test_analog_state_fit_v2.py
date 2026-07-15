from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd

from axiom_rift.research import analog_state_fit_v2 as fit_v2_module
from axiom_rift.research.analog_state_family import (
    CURRENT_H48_N15_ANALOG_FAMILY,
    analog_family_components,
    fit_fold_analog_family,
)
from axiom_rift.research.historical_analog_family_stu0061 import (
    STU0061_ANALOG_FAMILY as P1_STU0061_ANALOG_FAMILY,
)
from axiom_rift.research.analog_state_fit_v2 import (
    fit_fold_analog_family_v2,
    fit_prepared_analog_fold,
    fit_prepared_analog_fold_scoped,
    prepare_analog_frame,
)
from axiom_rift.research.analog_state_replay_v2 import (
    ANALOG_SCOPED_QUERY_SCOPE_ID,
    analog_family_components_scoped_v2,
    analog_family_components_v2,
    analog_family_executable_scoped_v2,
    analog_family_executable_v2,
)


def _frame(rows: int = 4_200) -> pd.DataFrame:
    index = np.arange(rows, dtype=float)
    close = (
        15_000.0
        + index * 0.07
        + np.sin(index / 17.0) * 11.0
        + np.cos(index / 53.0) * 7.0
    )
    open_ = close - np.sin(index / 9.0) * 1.5
    span = 2.5 + np.abs(np.cos(index / 13.0))
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=rows, freq="5min"),
            "open": open_,
            "high": np.maximum(open_, close) + span,
            "low": np.minimum(open_, close) - span,
            "close": close,
            "tick_volume": np.full(rows, 100.0),
            "spread": np.full(rows, 12.0),
            "real_volume": np.zeros(rows),
        }
    )


def _bounds(frame: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    return pd.Timestamp(frame.iloc[650]["time"]), pd.Timestamp(
        frame.iloc[3_800]["time"]
    )


def test_v2_fold_fit_is_exactly_equal_to_frozen_v1_semantics() -> None:
    frame = _frame()
    start, end = _bounds(frame)
    for profile in P1_STU0061_ANALOG_FAMILY.profiles:
        expected = fit_fold_analog_family(
            frame,
            family=P1_STU0061_ANALOG_FAMILY,
            profile_id=profile.profile_id,
            train_start=start,
            train_end=end,
        )
        observed = fit_fold_analog_family_v2(
            frame,
            family=P1_STU0061_ANALOG_FAMILY,
            profile_id=profile.profile_id,
            train_start=start,
            train_end=end,
            query_chunk_rows=137,
        )
        for expected_values, observed_values in zip(expected, observed, strict=True):
            np.testing.assert_array_equal(observed_values, expected_values)


def test_preparation_is_shared_across_folds_and_arrays_are_immutable() -> None:
    frame = _frame()
    start, end = _bounds(frame)
    with patch.object(
        fit_v2_module,
        "raw_analog_features",
        wraps=fit_v2_module.raw_analog_features,
    ) as raw_features:
        prepared = prepare_analog_frame(
            frame,
            family=P1_STU0061_ANALOG_FAMILY,
        )
        assert raw_features.call_count == len(P1_STU0061_ANALOG_FAMILY.profiles)
        for profile in P1_STU0061_ANALOG_FAMILY.profiles:
            fit_prepared_analog_fold(
                prepared,
                family=P1_STU0061_ANALOG_FAMILY,
                profile_id=profile.profile_id,
                train_start=start,
                train_end=end,
                query_chunk_rows=211,
            )
            fit_prepared_analog_fold(
                prepared,
                family=P1_STU0061_ANALOG_FAMILY,
                profile_id=profile.profile_id,
                train_start=start + pd.Timedelta(hours=3),
                train_end=end,
                query_chunk_rows=211,
            )
        assert raw_features.call_count == len(P1_STU0061_ANALOG_FAMILY.profiles)
    assert not prepared.time_ns.flags.writeable
    assert not prepared.target.flags.writeable
    assert not prepared.volatility.flags.writeable
    assert all(not profile.features.flags.writeable for profile in prepared.profiles)


def test_kdtree_queries_never_exceed_the_declared_chunk() -> None:
    frame = _frame()
    start, end = _bounds(frame)
    profile_id = P1_STU0061_ANALOG_FAMILY.profiles[0].profile_id
    prepared = prepare_analog_frame(
        frame,
        family=P1_STU0061_ANALOG_FAMILY,
        profile_ids=(profile_id,),
    )
    query_sizes: list[int] = []
    real_tree = fit_v2_module.cKDTree

    class RecordingTree:
        def __init__(self, values: np.ndarray) -> None:
            self._tree = real_tree(values)

        def query(self, values: np.ndarray, **kwargs: object) -> object:
            query_sizes.append(len(values))
            return self._tree.query(values, **kwargs)

    with patch.object(fit_v2_module, "cKDTree", RecordingTree):
        fit_prepared_analog_fold(
            prepared,
            family=P1_STU0061_ANALOG_FAMILY,
            profile_id=profile_id,
            train_start=start,
            train_end=end,
            query_chunk_rows=137,
        )
    assert len(query_sizes) > 1
    assert max(query_sizes) <= 137
    assert sum(query_sizes) == np.isfinite(
        prepared.profile(profile_id).features
    ).all(axis=1).sum()


def test_chunk_size_and_profile_order_fail_closed() -> None:
    frame = _frame()
    start, end = _bounds(frame)
    profile_ids = tuple(
        profile.profile_id for profile in P1_STU0061_ANALOG_FAMILY.profiles
    )
    try:
        prepare_analog_frame(
            frame,
            family=P1_STU0061_ANALOG_FAMILY,
            profile_ids=tuple(reversed(profile_ids)),
        )
    except ValueError as exc:
        assert "sorted and unique" in str(exc)
    else:
        raise AssertionError("unsorted analog profile request was accepted")
    prepared = prepare_analog_frame(
        frame,
        family=P1_STU0061_ANALOG_FAMILY,
        profile_ids=(profile_ids[0],),
    )
    try:
        fit_prepared_analog_fold(
            prepared,
            family=P1_STU0061_ANALOG_FAMILY,
            profile_id=profile_ids[0],
            train_start=start,
            train_end=end,
            query_chunk_rows=P1_STU0061_ANALOG_FAMILY.neighbors,
        )
    except ValueError as exc:
        assert "chunk binding" in str(exc)
    else:
        raise AssertionError("undersized analog query chunk was accepted")


def test_scoped_queries_match_v1_only_on_declared_rows() -> None:
    frame = _frame()
    start, end = _bounds(frame)
    profile_id = P1_STU0061_ANALOG_FAMILY.profiles[0].profile_id
    prepared = prepare_analog_frame(
        frame,
        family=P1_STU0061_ANALOG_FAMILY,
        profile_ids=(profile_id,),
    )
    expected = fit_fold_analog_family(
        frame,
        family=P1_STU0061_ANALOG_FAMILY,
        profile_id=profile_id,
        train_start=start,
        train_end=end,
    )
    test_start = pd.Timestamp(frame.iloc[3_801]["time"])
    test_end = pd.Timestamp(frame.iloc[4_000]["time"])
    query_mask = (
        ((prepared.time_ns >= int(start.value)) & (prepared.time_ns <= int(end.value)))
        | (
            (prepared.time_ns >= int(test_start.value))
            & (prepared.time_ns <= int(test_end.value))
        )
    )
    observed = fit_prepared_analog_fold_scoped(
        prepared,
        family=P1_STU0061_ANALOG_FAMILY,
        profile_id=profile_id,
        train_start=start,
        train_end=end,
        test_start=test_start,
        test_end=test_end,
        query_chunk_rows=137,
    )
    np.testing.assert_array_equal(observed[0][query_mask], expected[0][query_mask])
    assert np.isnan(observed[0][~query_mask]).all()
    np.testing.assert_array_equal(observed[1], expected[1])
    np.testing.assert_array_equal(observed[2], expected[2])


def test_time_validation_and_explicit_family_binding_are_independent() -> None:
    frame = _frame()
    frame.loc[len(frame) - 1, "time"] = pd.NaT
    try:
        prepare_analog_frame(frame, family=P1_STU0061_ANALOG_FAMILY)
    except Exception as exc:
        assert "time is invalid" in str(exc)
    else:
        raise AssertionError("NaT analog time was accepted")
    unrelated = CURRENT_H48_N15_ANALOG_FAMILY.configurations()[0]
    unrelated_executable = analog_family_executable_v2(unrelated)
    replay_executable = analog_family_executable_v2(
        P1_STU0061_ANALOG_FAMILY.configurations()[0]
    )
    assert unrelated_executable.identity != replay_executable.identity
    assert unrelated_executable.parameter_values()["family_id"] == (
        CURRENT_H48_N15_ANALOG_FAMILY.family_id
    )


def test_v2_components_replace_fit_and_synthesis_implementation_code() -> None:
    old = analog_family_components(P1_STU0061_ANALOG_FAMILY)
    new = analog_family_components_v2(P1_STU0061_ANALOG_FAMILY)
    assert len(old) == len(new)
    changed_implementations = [
        index
        for index, (left, right) in enumerate(zip(old, new, strict=True))
        if left.implementation != right.implementation
    ]
    assert changed_implementations == [1, 2, 8]
    for left, right in zip(old, new, strict=True):
        assert left.protocol == right.protocol
        assert left.specification() == right.specification()


def test_scoped_v2_has_a_distinct_protocol_and_executable_identity() -> None:
    full_components = analog_family_components_v2(P1_STU0061_ANALOG_FAMILY)
    scoped_components = analog_family_components_scoped_v2(
        P1_STU0061_ANALOG_FAMILY
    )
    assert len(full_components) == len(scoped_components)
    assert scoped_components[2].protocol == (
        "model.fold_train_knn_analog_family_scoped_query.v2"
    )
    assert scoped_components[2].specification()["query_scope_id"] == (
        ANALOG_SCOPED_QUERY_SCOPE_ID
    )
    assert "query_scope_id" in scoped_components[2].specification()[
        "parameter_fields"
    ]
    configuration = P1_STU0061_ANALOG_FAMILY.configurations()[0]
    full = analog_family_executable_v2(configuration)
    scoped = analog_family_executable_scoped_v2(configuration)
    assert scoped.identity != full.identity
    assert scoped.parameter_values()["query_scope_id"] == (
        ANALOG_SCOPED_QUERY_SCOPE_ID
    )
    assert f"query_scope_{ANALOG_SCOPED_QUERY_SCOPE_ID}" in scoped.engine_contract


def test_scoped_v2_binds_the_explicit_family_without_cross_family_fallback() -> None:
    unrelated = CURRENT_H48_N15_ANALOG_FAMILY.configurations()[0]
    unrelated_executable = analog_family_executable_scoped_v2(unrelated)
    replay_executable = analog_family_executable_scoped_v2(
        P1_STU0061_ANALOG_FAMILY.configurations()[0]
    )
    assert unrelated_executable.identity != replay_executable.identity
    assert unrelated_executable.components == analog_family_components_scoped_v2(
        CURRENT_H48_N15_ANALOG_FAMILY
    )
    assert unrelated_executable.parameter_values()["family_id"] == (
        CURRENT_H48_N15_ANALOG_FAMILY.family_id
    )
