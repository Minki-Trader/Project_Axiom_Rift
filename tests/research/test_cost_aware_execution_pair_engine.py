from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from axiom_rift.research.cost_aware_execution_pair import (
    cost_aware_execution_pair_engine_implementation_sha256 as pair_bound_engine_sha256,
    cost_aware_execution_pair_historical_context,
    cost_aware_execution_pair_protocol_definition,
)
from axiom_rift.research.cost_aware_execution_pair_engine import (
    COST_AWARE_EXECUTION_PAIR_PRODUCER_MANIFEST_SCHEMA,
    CostAwareExecutionPairEngineError,
    _PairTraceInputs,
    _build_trace_inputs,
    _candidate_inputs_for_scope,
    _candidate_source_bar_indices,
    _common_candidates,
    _definition_context_boundary,
    _producer_manifest,
    _source_input_sha256,
    _source_observations,
    cost_aware_execution_pair_engine_implementation_sha256,
)
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
    cost_aware_execution_protocol_definition,
)
from axiom_rift.research.cost_aware_execution_trace import (
    ScientificTraceError,
    compute_cost_aware_execution_pair_trace,
    validate_cost_aware_execution_pair_trace,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
)
from axiom_rift.research.historical_family_stu0070 import (
    STU0070_HISTORICAL_FAMILY,
)
from axiom_rift.research.selection_inference import HistoricalSearchContext


def _definition():
    return cost_aware_execution_protocol_definition(
        historical_family=STU0070_HISTORICAL_FAMILY,
        prospective_control_executable_id="executable:" + "1" * 64,
        prospective_target_executable_id="executable:" + "2" * 64,
    )


def _historical_context() -> HistoricalSearchContext:
    return HistoricalSearchContext(
        context_id="historical-context:test-pair-engine",
        prior_global_exposure_count=611,
    )


def _synthetic_model_frame(row_count: int) -> pd.DataFrame:
    rng = np.random.default_rng(917)
    index = np.arange(row_count)
    returns = (
        0.00012 * np.sin(index / 13.0)
        + rng.normal(0.0, 0.00035, row_count)
    )
    opened = np.round(
        np.exp(np.log(10_000.0) + np.cumsum(returns)), 6
    )
    closed = np.round(
        opened * np.exp(rng.normal(0.0, 0.00012, row_count)), 6
    )
    return pd.DataFrame(
        {
            "time": pd.date_range(
                "2024-01-01", periods=row_count, freq="5min"
            ),
            "open": opened,
            "close": closed,
            "spread": np.full(row_count, 2.0),
        }
    )


def _single_fold(frame: pd.DataFrame) -> dict[str, object]:
    return {
        "fold_id": "rw_001",
        "train_is": {
            "start": frame["time"].iloc[0],
            "end": frame["time"].iloc[1599],
        },
        "validation_oos": {
            "start": frame["time"].iloc[1600],
            "end": frame["time"].iloc[1699],
        },
        "test_oos": {
            "start": frame["time"].iloc[1700],
            "end": frame["time"].iloc[2199],
        },
    }


def _small_frame(
    *,
    gap_after: int | None = None,
    row_count: int = 100,
) -> pd.DataFrame:
    base = pd.Timestamp("2025-01-01 00:00:00")
    times = [base + pd.Timedelta(minutes=5 * index) for index in range(row_count)]
    if gap_after is not None:
        for index in range(gap_after + 1, row_count):
            times[index] += pd.Timedelta(minutes=5)
    return pd.DataFrame(
        {
            "time": times,
            "open": np.round(20_000.0 + np.arange(row_count) / 10, 6),
            "close": np.round(20_000.05 + np.arange(row_count) / 10, 6),
            "spread": np.full(row_count, 2.0),
        }
    )


def _candidate_pair(
    frame: pd.DataFrame,
    *,
    decision_index: int,
) -> tuple[dict[str, object], ...]:
    times = pd.DatetimeIndex(frame["time"])
    score = np.zeros(len(frame), dtype=float)
    score[decision_index] = 1.0
    volatility = np.ones(len(frame), dtype=float)
    kwargs = {
        "times": times,
        "score": score,
        "volatility": volatility,
        "threshold": 0.5,
        "regime_cutoffs": (0.5, 1.5),
        "fold_id": "rw_001",
        "test_start": pd.Timestamp("2025-01-01 00:00:00"),
        "test_end": pd.Timestamp("2025-01-30 23:59:59"),
    }
    full = _candidate_inputs_for_scope(**kwargs, scope="full")
    prefix = _candidate_inputs_for_scope(**kwargs, scope="prefix")
    return tuple(dict(item) for item in (*full, *prefix))


def _windows() -> tuple[dict[str, object], ...]:
    dates = pd.date_range("2025-01-01", periods=30, freq="D")
    return (
        {
            "eligible_dates": [item.date().isoformat() for item in dates],
            "fold_id": "rw_001",
            "test_end": "2025-01-30T23:59:59",
            "test_start": "2025-01-01T00:00:00",
        },
    )


def _trace(
    frame: pd.DataFrame,
    candidates: tuple[dict[str, object], ...],
) -> dict[str, object]:
    indices = _candidate_source_bar_indices(
        candidates, source_row_count=len(frame)
    )
    return compute_cost_aware_execution_pair_trace(
        definition=_definition(),
        dataset_sha256="a" * 64,
        split_artifact_sha256="b" * 64,
        material_identity="material:test-pair-engine",
        windows=_windows(),
        source_observations=_source_observations(
            frame, bar_indices=indices
        ),
        candidate_observations=candidates,
        historical_context=_historical_context(),
    )


class CostAwareExecutionPairEngineTests(unittest.TestCase):
    def test_engine_never_imports_retired_cost_discovery(self) -> None:
        source = Path(
            "src/axiom_rift/research/cost_aware_execution_pair_engine.py"
        ).read_text(encoding="ascii")
        self.assertNotIn("cost_aware_execution_discovery", source)
        digest = cost_aware_execution_pair_engine_implementation_sha256()
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, pair_bound_engine_sha256())

    def test_definition_boundary_rebuilds_current_engine_bound_pair(self) -> None:
        replay = HistoricalFamilyReplayContext(
            family_authority_id=(
                "historical-family-authority:"
                "3ddff77adc305d07d2ee536994527f8bd40dc12e9ea8ef9615797e95fd256e29"
            ),
            replay_obligation_id=(
                "historical-replay-obligation:"
                "ab4d0fcd6d5f88756fbed17f32dbf2831217a7c158d043b7f85f3c69b149b63e"
            ),
            family=STU0070_HISTORICAL_FAMILY,
            prior_global_exposure_count=581,
            original_family_end_global_exposure_count=(
                COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
            ),
        )
        definition = cost_aware_execution_pair_protocol_definition(replay)
        historical = cost_aware_execution_pair_historical_context(replay)
        self.assertEqual(
            _definition_context_boundary(definition, historical),
            COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
        )
        with self.assertRaises(CostAwareExecutionPairEngineError):
            _definition_context_boundary(
                definition,
                HistoricalSearchContext(
                    context_id=historical.context_id,
                    prior_global_exposure_count=582,
                ),
            )

    def test_exact_model_candidates_are_append_and_prefix_identical(self) -> None:
        appended = _synthetic_model_frame(2400)
        fold = _single_fold(appended)
        prefix = _build_trace_inputs(appended.iloc[:2200].copy(), (fold,))
        full = _build_trace_inputs(appended, (fold,))

        self.assertGreater(len(full.candidate_observations), 0)
        self.assertEqual(
            prefix.candidate_observations,
            full.candidate_observations,
        )
        self.assertEqual(
            prefix.fold_provenance[0]["candidate_common_sha256"],
            full.fold_provenance[0]["candidate_common_sha256"],
        )
        by_scope = {
            scope: tuple(
                row
                for row in full.candidate_observations
                if row["scope"] == scope
            )
            for scope in ("full", "prefix")
        }
        self.assertEqual(
            _common_candidates(by_scope["full"]),
            _common_candidates(by_scope["prefix"]),
        )

    def test_sparse_source_union_is_candidate_bounded(self) -> None:
        candidates = (
            {
                "decision_bar_index": 10_000,
                "decision_time": "2025-01-01T00:00:00",
                "direction": 1,
                "fold_id": "rw_001",
                "ordinal": 1,
                "regime": "middle",
                "scope": "full",
            },
            {
                "decision_bar_index": 9_000_000,
                "decision_time": "2025-01-01T00:00:00",
                "direction": 1,
                "fold_id": "rw_009",
                "ordinal": 1,
                "regime": "middle",
                "scope": "full",
            },
        )
        indices = _candidate_source_bar_indices(
            candidates, source_row_count=10_000_000
        )
        self.assertLess(len(indices), 1_300)
        self.assertLess(indices.nbytes, 11_000)
        self.assertEqual(indices[0], 10_000 - 576 - 1)
        self.assertEqual(indices[-1], 9_000_000 + 49)

    def test_trace_accepts_sparse_global_support_and_shrinks_predecessor(
        self,
    ) -> None:
        frame = _small_frame(row_count=800)
        candidates = _candidate_pair(frame, decision_index=700)
        supplied = _candidate_source_bar_indices(
            candidates, source_row_count=len(frame)
        )
        self.assertEqual(int(supplied[0]), 700 - 576 - 1)
        trace = _trace(frame, candidates)
        self.assertEqual(
            trace["candidate_observations"][0]["context_start_reason"],
            "rolling_truncation",
        )
        self.assertEqual(
            trace["source_observations"][0]["bar_index"],
            700 - 576,
        )

    def test_source_hash_detects_value_tamper_and_rejects_index_tamper(
        self,
    ) -> None:
        source = _source_observations(_small_frame())
        rows = [dict(item) for item in source]
        expected = _source_input_sha256(rows)
        rows[0]["open_micropoints"] += 1
        self.assertNotEqual(expected, _source_input_sha256(rows))
        rows[0]["bar_index"] = 1
        with self.assertRaises(CostAwareExecutionPairEngineError):
            _source_input_sha256(rows)

    def test_materialized_trace_rejects_source_tamper(self) -> None:
        frame = _small_frame()
        trace = _trace(frame, _candidate_pair(frame, decision_index=30))
        tampered = deepcopy(trace)
        tampered["source_observations"][0]["open_micropoints"] += 1
        with self.assertRaises(ScientificTraceError):
            validate_cost_aware_execution_pair_trace(
                tampered, definition=_definition()
            )

    def test_gap_candidate_is_not_filtered_before_trace(self) -> None:
        frame = _small_frame(gap_after=10)
        candidates = _candidate_pair(frame, decision_index=10)
        self.assertEqual(len(candidates), 2)
        trace = _trace(frame, candidates)
        self.assertEqual(
            {row["status"] for row in trace["intent_observations"]},
            {"gap_excluded"},
        )

    def test_causality_violation_is_not_hidden_by_candidate_producer(
        self,
    ) -> None:
        frame = _small_frame()
        candidates = [
            dict(item) for item in _candidate_pair(frame, decision_index=10)
        ]
        for candidate in candidates:
            candidate["decision_time"] = "2025-01-01T01:00:00"
        trace = _trace(frame, tuple(candidates))
        self.assertEqual(
            {row["status"] for row in trace["intent_observations"]},
            {"causality_violation"},
        )

    def test_producer_manifest_freezes_minimum_24_spread_reference(
        self,
    ) -> None:
        frame = _small_frame()
        source = _source_observations(
            frame, bar_indices=np.arange(60, dtype=np.int64)
        )
        inputs = _PairTraceInputs(
            windows=_windows(),
            source_observations=source,
            candidate_observations=_candidate_pair(
                frame, decision_index=10
            ),
            fold_provenance=(),
            feature_provenance={"schema": "test_feature_provenance.v1"},
        )
        manifest = _producer_manifest(
            definition=_definition(),
            historical_context=_historical_context(),
            original_family_end_global_exposure_count=(
                COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
            ),
            inputs=inputs,
            trace={"schema": "test_neutral_trace.v1"},
        )
        self.assertEqual(
            manifest["schema"],
            COST_AWARE_EXECUTION_PAIR_PRODUCER_MANIFEST_SCHEMA,
        )
        self.assertEqual(
            manifest["trace_input_contract"][
                "spread_reference_min_observations"
            ],
            24,
        )
        self.assertEqual(
            manifest["historical_context"]["current"][
                "prior_global_exposure_count"
            ],
            611,
        )
        self.assertEqual(
            manifest["historical_context"][
                "original_family_end_global_exposure_count"
            ],
            COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
        )


if __name__ == "__main__":
    unittest.main()
