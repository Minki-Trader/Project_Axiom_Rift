"""Verify memory-bounded analog fitting against durable STU-0106 evidence.

This is an explicit engineering maintenance check, not a routine scientific
Job gate.  It reads only the registered observed-development prefix and the
exact durable first-member STU-0106 trace.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import sys
from threading import Event, Thread
import time
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from axiom_rift.core.canonical import canonical_bytes, parse_canonical  # noqa: E402
from axiom_rift.operations.running_job import RunningJobAuthority  # noqa: E402
from axiom_rift.research.analog_state_family import (  # noqa: E402
    fit_fold_analog_family,
)
from axiom_rift.research.historical_analog_family_stu0061 import (  # noqa: E402
    STU0061_ANALOG_FAMILY as P1_STU0061_ANALOG_FAMILY,
)
from axiom_rift.research.analog_state_fit_v2 import (  # noqa: E402
    DEFAULT_ANALOG_QUERY_CHUNK_ROWS,
    analog_fit_v2_implementation_sha256,
    fit_prepared_analog_fold,
    fit_prepared_analog_fold_scoped,
    prepare_analog_frame,
)
from axiom_rift.research.analog_state_replay import (  # noqa: E402
    _fold_payloads,
    analog_replay_implementation_sha256,
    compute_analog_family_trace,
)
from axiom_rift.research.analog_state_replay_v2 import (  # noqa: E402
    analog_replay_v2_bundle_sha256,
    compute_analog_family_trace_scoped_v2,
    compute_analog_family_trace_v2,
    trace_scoped_v2_is_exact_v1_decision_parity,
    trace_v2_is_exact_v1_semantic_parity,
)
from axiom_rift.research.analog_state_trace import (  # noqa: E402
    analog_original_family_provenance,
    extract_analog_family_trace_from_subject,
)
from axiom_rift.research.data import load_observed_development  # noqa: E402
from axiom_rift.storage.evidence import EvidenceStore  # noqa: E402


REFERENCE_COMPLETION_RECORD_ID = (
    "6a440e0bb2176ae9cf6dad6a4458077a473d2c87053fbc03633f5c8bb052f791"
)
REFERENCE_TRACE_OUTPUT = (
    "scientific/STU-0106/d2afab54e11ca76e/evaluation-trace.json"
)
REFERENCE_TRACE_SHA256 = (
    "42fb5e3556387e681e0e18ec64a4eec8dd8bd8674ae7b59b6927d4d20e5b1651"
)
V2_TRACE_MAX_ELAPSED_SECONDS = 360.0
V2_TRACE_MAX_PEAK_RSS_BYTES = 1_073_741_824
SCOPED_TRACE_MAX_ELAPSED_SECONDS = 150.0
SCOPED_TRACE_MAX_PEAK_RSS_BYTES = 805_306_368
SCOPED_MAX_QUERY_ROW_RATIO = 0.30
SCOPED_MAX_FIT_TIME_RATIO = 0.60


def _digest_score(values: np.ndarray) -> str:
    """Reproduce the immutable v1 score-vector parity identity."""

    array = np.asarray(values, dtype="<f8").copy()
    array[np.isnan(array)] = np.nan
    material = (
        b"analog-score-vector.v1\0"
        + len(array).to_bytes(8, "big")
        + array.tobytes(order="C")
    )
    return sha256(material).hexdigest()


@dataclass(slots=True)
class _RssSampler:
    peak_bytes: int = 0
    _stop: Event = field(init=False, repr=False)
    _thread: Thread | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self._stop = Event()

    def __enter__(self) -> "_RssSampler":
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("psutil is required for analog memory evidence") from exc
        process = psutil.Process()

        def sample() -> None:
            while not self._stop.wait(0.05):
                self.peak_bytes = max(self.peak_bytes, process.memory_info().rss)
            self.peak_bytes = max(self.peak_bytes, process.memory_info().rss)

        self._thread = Thread(target=sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


def _reference_trace(
    root: Path,
    *,
    foundation_root: Path | None = None,
) -> dict[str, object]:
    root = root.resolve()
    authority = RunningJobAuthority(
        root,
        foundation_root=(
            root if foundation_root is None else foundation_root.resolve()
        ),
    )
    with authority.open_stable_index() as (_control, index):
        completion = index.get(
            "job-completed",
            REFERENCE_COMPLETION_RECORD_ID,
        )
    if completion is None:
        raise RuntimeError("STU-0106 reference completion is absent")
    outputs = completion.payload.get("outputs")
    if (
        not isinstance(outputs, dict)
        or outputs.get(REFERENCE_TRACE_OUTPUT) != REFERENCE_TRACE_SHA256
    ):
        raise RuntimeError("STU-0106 reference completion output drifted")
    content = EvidenceStore(root / "local" / "evidence").read_verified(
        REFERENCE_TRACE_SHA256
    )
    subject = parse_canonical(content)
    if not isinstance(subject, dict):
        raise RuntimeError("STU-0106 reference trace is invalid")
    return extract_analog_family_trace_from_subject(subject)


def verify(
    *,
    root: Path,
    engine: str,
    query_chunk_rows: int,
) -> dict[str, object]:
    reference = _reference_trace(root)
    comparisons = reference.get("invariance_comparisons")
    if not isinstance(comparisons, list) or len(comparisons) != 18:
        raise RuntimeError("STU-0106 reference comparisons are incomplete")
    expected = {
        (str(value["fold_id"]), str(value["profile_id"])): value
        for value in comparisons
        if isinstance(value, dict)
    }
    if len(expected) != 18:
        raise RuntimeError("STU-0106 reference comparison identities drifted")
    data = load_observed_development(root)
    frame = data.frame
    folds = _fold_payloads(data)
    time_index = pd.to_datetime(frame["time"], errors="raise")
    started = time.perf_counter()
    checks = 0
    with _RssSampler() as memory:
        prepared_full = (
            prepare_analog_frame(frame, family=P1_STU0061_ANALOG_FAMILY)
            if engine == "v2"
            else None
        )
        for profile in P1_STU0061_ANALOG_FAMILY.profiles:
            for fold in folds:
                fold_id = str(fold["fold_id"])
                train = fold["train_is"]
                test = fold["test_oos"]
                train_start = pd.Timestamp(train["start"])
                train_end = pd.Timestamp(train["end"])
                prefix_end = int(
                    time_index.searchsorted(pd.Timestamp(test["end"]), side="right")
                )
                prefix_frame = frame.iloc[:prefix_end]
                if engine == "v1":
                    full = fit_fold_analog_family(
                        frame,
                        family=P1_STU0061_ANALOG_FAMILY,
                        profile_id=profile.profile_id,
                        train_start=train_start,
                        train_end=train_end,
                    )
                    prefix = fit_fold_analog_family(
                        prefix_frame,
                        family=P1_STU0061_ANALOG_FAMILY,
                        profile_id=profile.profile_id,
                        train_start=train_start,
                        train_end=train_end,
                    )
                else:
                    if prepared_full is None:
                        raise RuntimeError("v2 full preparation is absent")
                    full = fit_prepared_analog_fold(
                        prepared_full,
                        family=P1_STU0061_ANALOG_FAMILY,
                        profile_id=profile.profile_id,
                        train_start=train_start,
                        train_end=train_end,
                        query_chunk_rows=query_chunk_rows,
                    )
                    prepared_prefix = prepare_analog_frame(
                        prefix_frame,
                        family=P1_STU0061_ANALOG_FAMILY,
                        profile_ids=(profile.profile_id,),
                    )
                    prefix = fit_prepared_analog_fold(
                        prepared_prefix,
                        family=P1_STU0061_ANALOG_FAMILY,
                        profile_id=profile.profile_id,
                        train_start=train_start,
                        train_end=train_end,
                        query_chunk_rows=query_chunk_rows,
                    )
                observed_full = _digest_score(full[0][:prefix_end])
                observed_prefix = _digest_score(prefix[0])
                reference_comparison = expected[(fold_id, profile.profile_id)]
                if (
                    observed_full
                    != reference_comparison["full_score_values_sha256"]
                    or observed_prefix
                    != reference_comparison["prefix_score_values_sha256"]
                ):
                    raise RuntimeError(
                        f"analog parity drift: {fold_id} {profile.profile_id}"
                    )
                checks += 1
    return {
        "checks": checks,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "engine": engine,
        "implementation_sha256": (
            analog_fit_v2_implementation_sha256() if engine == "v2" else None
        ),
        "peak_rss_bytes": memory.peak_bytes,
        "query_chunk_rows": query_chunk_rows if engine == "v2" else None,
        "reference_completion_record_id": REFERENCE_COMPLETION_RECORD_ID,
        "reference_trace_sha256": REFERENCE_TRACE_SHA256,
        "rows": len(frame),
        "schema": "analog_fit_parity_report.v1",
    }


def verify_trace(*, root: Path, engine: str) -> dict[str, object]:
    if engine not in {"v1-trace", "v2-trace", "v2-scoped-trace"}:
        raise ValueError("analog trace verifier engine is invalid")
    reference = _reference_trace(root)
    provenance = analog_original_family_provenance(P1_STU0061_ANALOG_FAMILY)
    started = time.perf_counter()
    with _RssSampler() as memory:
        if engine == "v2-trace":
            trace, metrics = compute_analog_family_trace_v2(
                root,
                family=P1_STU0061_ANALOG_FAMILY,
                original_family_provenance=provenance,
            )
            semantic_trace_exact = trace_v2_is_exact_v1_semantic_parity(
                trace,
                reference,
                family=P1_STU0061_ANALOG_FAMILY,
            )
            implementation_bundle = analog_replay_v2_bundle_sha256()
            parity_mode = "full_vector_exact"
        elif engine == "v2-scoped-trace":
            trace, metrics = compute_analog_family_trace_scoped_v2(
                root,
                family=P1_STU0061_ANALOG_FAMILY,
                original_family_provenance=provenance,
            )
            semantic_trace_exact = trace_scoped_v2_is_exact_v1_decision_parity(
                trace,
                reference,
                family=P1_STU0061_ANALOG_FAMILY,
            )
            implementation_bundle = analog_replay_v2_bundle_sha256()
            parity_mode = "reachable_decisions_exact"
        else:
            trace, metrics = compute_analog_family_trace(root)
            semantic_trace_exact = canonical_bytes(trace) == canonical_bytes(reference)
            implementation_bundle = analog_replay_implementation_sha256()
            parity_mode = "full_vector_exact"
        if not semantic_trace_exact:
            raise RuntimeError(f"analog {engine} complete trace is not exact parity")
    elapsed_seconds = round(time.perf_counter() - started, 3)
    limits = {
        "v2-trace": (
            V2_TRACE_MAX_ELAPSED_SECONDS,
            V2_TRACE_MAX_PEAK_RSS_BYTES,
        ),
        "v2-scoped-trace": (
            SCOPED_TRACE_MAX_ELAPSED_SECONDS,
            SCOPED_TRACE_MAX_PEAK_RSS_BYTES,
        ),
    }.get(engine)
    performance_within_bound = (
        elapsed_seconds <= limits[0]
        and 0 < memory.peak_bytes <= limits[1]
        if limits is not None
        else None
    )
    return {
        "acceptance_max_elapsed_seconds": (
            limits[0] if limits is not None else None
        ),
        "acceptance_max_peak_rss_bytes": (
            limits[1] if limits is not None else None
        ),
        "elapsed_seconds": elapsed_seconds,
        "engine": engine,
        "implementation_bundle_sha256": implementation_bundle,
        "member_count": len(metrics),
        "parity_mode": parity_mode,
        "peak_rss_bytes": memory.peak_bytes,
        "performance_within_bound": performance_within_bound,
        "reference_completion_record_id": REFERENCE_COMPLETION_RECORD_ID,
        "reference_trace_sha256": REFERENCE_TRACE_SHA256,
        "schema": "analog_replay_v2_parity_report.v1",
        "semantic_trace_exact": semantic_trace_exact,
    }


def verify_scoped(*, root: Path, query_chunk_rows: int) -> dict[str, object]:
    """Prove scope reduction without changing any declared-row score."""

    data = load_observed_development(root)
    frame = data.frame
    folds = _fold_payloads(data)
    time_index = pd.to_datetime(frame["time"], errors="raise")
    exact_fit_seconds = 0.0
    scoped_fit_seconds = 0.0
    exact_query_rows = 0
    scoped_query_rows = 0
    comparisons = 0
    with _RssSampler() as memory:
        for profile in P1_STU0061_ANALOG_FAMILY.profiles:
            profile_id = profile.profile_id
            prepared_full = prepare_analog_frame(
                frame,
                family=P1_STU0061_ANALOG_FAMILY,
                profile_ids=(profile_id,),
            )
            for fold in folds:
                train = fold["train_is"]
                test = fold["test_oos"]
                train_start = pd.Timestamp(train["start"])
                train_end = pd.Timestamp(train["end"])
                test_start = pd.Timestamp(test["start"])
                test_end = pd.Timestamp(test["end"])
                prefix_end = int(time_index.searchsorted(test_end, side="right"))
                prefix_frame = frame.iloc[:prefix_end]
                prepared_prefix = prepare_analog_frame(
                    prefix_frame,
                    family=P1_STU0061_ANALOG_FAMILY,
                    profile_ids=(profile_id,),
                )
                for prepared in (prepared_full, prepared_prefix):
                    started = time.perf_counter()
                    exact = fit_prepared_analog_fold(
                        prepared,
                        family=P1_STU0061_ANALOG_FAMILY,
                        profile_id=profile_id,
                        train_start=train_start,
                        train_end=train_end,
                        query_chunk_rows=query_chunk_rows,
                    )
                    exact_fit_seconds += time.perf_counter() - started
                    started = time.perf_counter()
                    scoped = fit_prepared_analog_fold_scoped(
                        prepared,
                        family=P1_STU0061_ANALOG_FAMILY,
                        profile_id=profile_id,
                        train_start=train_start,
                        train_end=train_end,
                        test_start=test_start,
                        test_end=test_end,
                        query_chunk_rows=query_chunk_rows,
                    )
                    scoped_fit_seconds += time.perf_counter() - started
                    valid = np.isfinite(
                        prepared.profile(profile_id).features
                    ).all(axis=1)
                    scope = (
                        (
                            (prepared.time_ns >= int(train_start.value))
                            & (prepared.time_ns <= int(train_end.value))
                        )
                        | (
                            (prepared.time_ns >= int(test_start.value))
                            & (prepared.time_ns <= int(test_end.value))
                        )
                    )
                    declared = valid & scope
                    if not np.array_equal(
                        scoped[0][declared],
                        exact[0][declared],
                        equal_nan=True,
                    ):
                        raise RuntimeError("scoped analog score parity drifted")
                    if not np.isnan(scoped[0][~scope]).all():
                        raise RuntimeError("scoped analog queried undeclared rows")
                    if not (
                        np.array_equal(scoped[1], exact[1], equal_nan=True)
                        and np.array_equal(scoped[2], exact[2])
                    ):
                        raise RuntimeError("scoped analog causal state drifted")
                    exact_query_rows += int(valid.sum())
                    scoped_query_rows += int(declared.sum())
                    comparisons += 1
    query_row_ratio = scoped_query_rows / exact_query_rows
    fit_time_ratio = scoped_fit_seconds / exact_fit_seconds
    performance_within_bound = (
        query_row_ratio <= SCOPED_MAX_QUERY_ROW_RATIO
        and fit_time_ratio <= SCOPED_MAX_FIT_TIME_RATIO
    )
    return {
        "acceptance_max_fit_time_ratio": SCOPED_MAX_FIT_TIME_RATIO,
        "acceptance_max_query_row_ratio": SCOPED_MAX_QUERY_ROW_RATIO,
        "comparisons": comparisons,
        "engine": "v2-scoped",
        "exact_fit_seconds": round(exact_fit_seconds, 3),
        "exact_query_rows": exact_query_rows,
        "fit_time_ratio": round(fit_time_ratio, 6),
        "implementation_bundle_sha256": analog_replay_v2_bundle_sha256(),
        "peak_rss_bytes": memory.peak_bytes,
        "performance_within_bound": performance_within_bound,
        "query_chunk_rows": query_chunk_rows,
        "query_row_ratio": round(query_row_ratio, 6),
        "reference_completion_record_id": REFERENCE_COMPLETION_RECORD_ID,
        "reference_trace_sha256": REFERENCE_TRACE_SHA256,
        "schema": "analog_replay_v2_scoped_parity_report.v1",
        "scoped_fit_seconds": round(scoped_fit_seconds, 3),
        "semantic_scoped_exact": True,
    }


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--engine",
        choices=(
            "v1",
            "v2",
            "v1-trace",
            "v2-trace",
            "v2-scoped",
            "v2-scoped-trace",
        ),
        required=True,
    )
    parser.add_argument(
        "--query-chunk-rows",
        type=int,
        default=DEFAULT_ANALOG_QUERY_CHUNK_ROWS,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    arguments = parse_arguments(argv)
    root = arguments.root.resolve()
    if arguments.engine in {"v1-trace", "v2-trace", "v2-scoped-trace"}:
        result = verify_trace(root=root, engine=arguments.engine)
    elif arguments.engine == "v2-scoped":
        result = verify_scoped(
            root=root,
            query_chunk_rows=arguments.query_chunk_rows,
        )
    else:
        result = verify(
            root=root,
            engine=arguments.engine,
            query_chunk_rows=arguments.query_chunk_rows,
        )
    print(
        json.dumps(
            result,
            sort_keys=True,
        )
    )
    if result.get("performance_within_bound") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
