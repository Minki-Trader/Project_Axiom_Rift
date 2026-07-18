"""Atomic paired-policy trace for the corrected cost-aware replay.

The producer is deliberately pure.  A Job-owned engine supplies an observed
development prefix, one exact fold calendar, and the common full/prefix
candidate stream.  This module shrinks the source frame to the causal support
needed by those candidates, simulates both policies with independent occupancy,
and immediately validates every derived row.  The recomputer opens only the
trace and performs deterministic exact-family inference.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from hashlib import sha256
from math import ceil
from pathlib import Path
from typing import Any

import numpy as np

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_CONTROL_DELTA_METRIC,
    COST_AWARE_EXECUTION_CONTROL_PVALUE_METRIC,
    COST_AWARE_EXECUTION_PROTOCOL_ID,
    COST_AWARE_EXECUTION_REPLAY_CLAIMS,
    COST_AWARE_EXECUTION_REPLAY_CRITERIA,
    COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES,
    CostAwareExecutionProtocolDefinition,
    cost_aware_execution_multiplicity_registrations,
    cost_aware_execution_protocol_definition_from_manifest,
    cost_aware_execution_subject_inference_families,
)
from axiom_rift.research.scientific_study import claim_metrics
from axiom_rift.research.scientific_trace import (
    SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
    SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
    ScientificTraceError,
)
from axiom_rift.research.selection_inference import (
    HistoricalSearchContext,
    SelectionFamilyPlan,
    SelectionHypothesis,
    infer_concurrent_selection_family,
    selection_inference_implementation_sha256,
)


COST_AWARE_EXECUTION_PAIR_TRACE_SCHEMA = (
    "cost_aware_execution_pair_trace.v1"
)
COST_AWARE_EXECUTION_SOURCE_OBSERVATION_SCHEMA = (
    "cost_aware_execution_source_observation.v1"
)
COST_AWARE_EXECUTION_CANDIDATE_OBSERVATION_SCHEMA = (
    "cost_aware_execution_candidate_observation.v1"
)
COST_AWARE_EXECUTION_INTENT_OBSERVATION_SCHEMA = (
    "cost_aware_execution_intent_observation.v1"
)
COST_AWARE_EXECUTION_TRADE_OBSERVATION_SCHEMA = (
    "cost_aware_execution_trade_observation.v1"
)
COST_AWARE_EXECUTION_ELIGIBLE_DAY_SCHEMA = (
    "cost_aware_execution_eligible_day.v1"
)
COST_AWARE_EXECUTION_INVARIANCE_SCHEMA = (
    "cost_aware_execution_invariance.v1"
)

_BAR_DURATION = timedelta(minutes=5)
_HOLDING_BARS = 48
_SPREAD_REFERENCE_BARS = 288
_SPREAD_REFERENCE_MIN_PERIODS = 24
_SPREAD_LIMIT_MILLI = 1_200
_SOURCE_HISTORY_BARS = 2 * _SPREAD_REFERENCE_BARS
_SPREAD_SEMANTICS = "completed_period_proxy"
_ALLOWED_SCOPES = frozenset({"full", "prefix"})
_ALLOWED_REGIMES = frozenset({"low", "middle", "high"})
_ALLOWED_STATUSES = frozenset(
    {
        "causality_violation",
        "entry_cancelled_unknown_gate",
        "executed",
        "gap_excluded",
        "spread_abstained",
        "unknown_cost",
    }
)

_WINDOW_FIELDS = {"eligible_dates", "fold_id", "test_end", "test_start"}
_SOURCE_INPUT_FIELDS = {
    "bar_index",
    "bar_open_time",
    "open_micropoints",
    "raw_spread_millipoints",
}
_SOURCE_FIELDS = _SOURCE_INPUT_FIELDS | {
    "information_complete_at",
    "observation_id",
    "schema",
}
_CANDIDATE_INPUT_FIELDS = {
    "decision_bar_index",
    "decision_time",
    "direction",
    "fold_id",
    "ordinal",
    "regime",
    "scope",
}
_CANDIDATE_FIELDS = {
    "availability_time",
    "candidate_stream_id",
    "context_start_bar_index",
    "context_start_reason",
    "decision_bar_index",
    "decision_bar_open_time",
    "decision_time",
    "direction",
    "entry_bar_index",
    "entry_time",
    "exit_bar_index",
    "exit_time",
    "fold_id",
    "holding_bars",
    "observation_id",
    "ordinal",
    "regime",
    "schema",
    "scope",
    "segment_predecessor_bar_index",
}
_INTENT_FIELDS = {
    "availability_time",
    "candidate_stream_id",
    "configuration_id",
    "decision_bar_index",
    "decision_bar_open_time",
    "decision_spread_information_complete_at",
    "decision_spread_source_bar_index",
    "decision_spread_source_bar_open_time",
    "decision_time",
    "direction",
    "entry_bar_index",
    "entry_spread_information_complete_at",
    "entry_spread_known",
    "entry_spread_millipoints",
    "entry_spread_source_bar_index",
    "entry_spread_source_bar_open_time",
    "entry_time",
    "executable_id",
    "exit_bar_index",
    "exit_spread_information_complete_at",
    "exit_spread_known",
    "exit_spread_millipoints",
    "exit_spread_source_bar_index",
    "exit_spread_source_bar_open_time",
    "exit_time",
    "fold_id",
    "gate_reference_known",
    "gate_reference_millipoints",
    "gate_reference_observation_count",
    "gate_spread_known",
    "gate_spread_millipoints",
    "historical_reference_executable_id",
    "holding_bars",
    "observation_id",
    "ordinal",
    "policy",
    "predicate_evaluated",
    "regime",
    "schema",
    "scope",
    "spread_semantics",
    "status",
}
_TRADE_FIELDS = {
    "availability_time",
    "candidate_stream_id",
    "configuration_id",
    "decision_bar_index",
    "decision_bar_open_time",
    "decision_time",
    "direction",
    "entry_bar_index",
    "entry_spread_millipoints",
    "entry_spread_source_bar_index",
    "entry_time",
    "executable_id",
    "exit_bar_index",
    "exit_spread_millipoints",
    "exit_spread_source_bar_index",
    "exit_time",
    "fold_id",
    "gross_pnl_micropoints",
    "historical_reference_executable_id",
    "holding_bars",
    "intent_observation_id",
    "native_cost_micropoints",
    "native_net_pnl_micropoints",
    "observation_id",
    "policy",
    "regime",
    "schema",
    "spread_semantics",
    "stress_cost_micropoints",
    "stress_net_pnl_micropoints",
}
_ELIGIBLE_DAY_FIELDS = {
    "configuration_id",
    "date",
    "entry_count",
    "executable_id",
    "fold_id",
    "native_net_pnl_micropoints",
    "schema",
    "stress_net_pnl_micropoints",
}
_INVARIANCE_FIELDS = {
    "candidate_mismatch_count",
    "candidate_full_sha256",
    "full_candidate_count",
    "candidate_prefix_sha256",
    "fold_id",
    "gate_mismatch_count",
    "gate_full_sha256",
    "gate_prefix_sha256",
    "intent_mismatch_count",
    "intent_full_sha256",
    "intent_prefix_sha256",
    "mismatch_count",
    "prefix_candidate_count",
    "schema",
}
_PAIR_TRACE_FIELDS = {
    "attribution",
    "candidate_observations",
    "controls",
    "dataset_sha256",
    "eligible_day_observations",
    "family_id",
    "historical_context",
    "implementation_identities",
    "intent_observations",
    "invariance_comparisons",
    "material_identity",
    "ordered_family",
    "protocol_definition",
    "protocol_id",
    "schema",
    "source_observations",
    "split_artifact_sha256",
    "trade_observations",
    "windows",
}
_SUBJECT_TRACE_FIELDS = {
    "adapter_implementation_sha256",
    "attribution",
    "candidate_observations",
    "controls",
    "dataset_sha256",
    "eligible_day_observations",
    "family_id",
    "historical_context",
    "intent_observations",
    "invariance_comparisons",
    "job_hash",
    "job_id",
    "material_identity",
    "mission_id",
    "ordered_family",
    "protocol_definition",
    "protocol_id",
    "schema",
    "source_observations",
    "split_artifact_sha256",
    "subject_executable_id",
    "trade_observations",
    "windows",
}
_CALCULATION_FIELDS = {
    "evidence_modes",
    "executable_id",
    "job_hash",
    "job_id",
    "metrics",
    "mission_id",
    "parameters",
    "protocol_definition",
    "protocol_id",
    "schema",
    "statistics",
    "trace",
}

_DESCRIPTIVE_DIAGNOSTIC_METRICS = {
    "activity_and_concentration": (
        "daily_entries_max_milli",
        "daily_entries_median_milli",
        "daily_entries_p10_milli",
        "daily_entries_p90_milli",
        "eligible_day_count",
        "monthly_realized_exit_drawdown_micropoints",
        "zero_entry_day_rate_ppm",
    ),
    "causal_feature_and_execution_validity": (
        "gap_excluded_signal_count",
    ),
    "temporal_and_regime_stability": (
        "positive_regime_count",
    ),
}


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ScientificTraceError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise ScientificTraceError(f"{name} must be a lowercase SHA-256")
    return text


def _executable_id(name: str, value: object) -> str:
    text = _ascii(name, value)
    digest = text.removeprefix("executable:")
    if digest == text:
        raise ScientificTraceError(f"{name} must be executable:<sha256>")
    _digest(name, digest)
    return text


def _integer(name: str, value: object, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ScientificTraceError(f"{name} must be an integer")
    return value


def _mapping(name: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ScientificTraceError(f"{name} must be an object")
    return value


def _sequence(name: str, value: object) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ScientificTraceError(f"{name} must be an array")
    return value


def _timestamp(name: str, value: object) -> datetime:
    text = _ascii(name, value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ScientificTraceError(f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is not None:
        raise ScientificTraceError(f"{name} must use the frozen naive broker clock")
    return parsed


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _strict_date(name: str, value: object) -> str:
    text = _ascii(name, value)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ScientificTraceError(f"{name} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != text:
        raise ScientificTraceError(f"{name} must be canonical YYYY-MM-DD")
    return text


def _canonical_clone(name: str, value: object) -> dict[str, Any]:
    try:
        normalized = parse_canonical(canonical_bytes(value))
    except (TypeError, ValueError) as exc:
        raise ScientificTraceError(f"{name} is not canonical") from exc
    if type(normalized) is not dict:
        raise ScientificTraceError(f"{name} must be an object")
    return normalized


def cost_aware_execution_trace_implementation_sha256() -> str:
    """Return the exact source identity sealed by the Job executable."""

    return sha256(Path(__file__).resolve().read_bytes()).hexdigest()


def _observation_id(kind: str, value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "observation_id"}
    return "observation:" + canonical_digest(
        domain=f"cost-aware-execution-{kind}-observation",
        payload=payload,
    )


def _static_attribution() -> dict[str, object]:
    return {
        "candidate_stream": "common_before_policy_with_independent_occupancy",
        "drawdown_attribution": "exit_order_within_exit_month",
        "eligible_calendar": "exact_test_dates_with_explicit_zero_entry_days",
        "native_pnl_attribution": "decision_day",
        "spread_reference": "strict_prior_gap_reset_288_min24",
        "stress_pnl_attribution": "decision_day",
    }


def _static_controls(
    definition: CostAwareExecutionProtocolDefinition,
) -> dict[str, object]:
    manifest = definition.manifest()
    return {
        "binding": manifest["primary_control"],
        "control_policy": "unconditional_next_open",
        "primary_control_family_scope": "one_subject_control_contrast",
        "selection_family_scope": "exact_two_policy_concurrent_family",
        "target_policy": "causal_spread_abstention",
    }


def _implementation_identities() -> dict[str, str]:
    return {
        "cost_aware_execution_trace_sha256": (
            cost_aware_execution_trace_implementation_sha256()
        ),
        "selection_inference_sha256": (
            selection_inference_implementation_sha256()
        ),
    }


def _normalize_historical_context(
    value: HistoricalSearchContext | Mapping[str, Any],
    *,
    definition: CostAwareExecutionProtocolDefinition,
) -> dict[str, object]:
    current = value.manifest() if isinstance(value, HistoricalSearchContext) else dict(value)
    try:
        normalized_current = HistoricalSearchContext(
            context_id=current["context_id"],
            prior_global_exposure_count=current["prior_global_exposure_count"],
        ).manifest()
    except (KeyError, TypeError, ValueError) as exc:
        raise ScientificTraceError("current historical search context is invalid") from exc
    if current != normalized_current:
        raise ScientificTraceError("historical search context contains extra authority")
    inference = _mapping(
        "cost-aware definition inference",
        definition.manifest().get("inference"),
    )
    _integer(
        "original family end global exposure count",
        inference.get("original_family_end_global_exposure_count"),
        minimum=0,
    )
    return normalized_current


def _normalize_windows(
    windows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    fold_ids: set[str] = set()
    all_dates: set[str] = set()
    for raw in _sequence("cost-aware windows", windows):
        row = _mapping("cost-aware window", raw)
        if set(row) != _WINDOW_FIELDS:
            raise ScientificTraceError("cost-aware window schema is invalid")
        fold_id = _ascii("window fold_id", row.get("fold_id"))
        if fold_id in fold_ids:
            raise ScientificTraceError("cost-aware fold_id is duplicated")
        fold_ids.add(fold_id)
        start = _timestamp("window test_start", row.get("test_start"))
        end = _timestamp("window test_end", row.get("test_end"))
        if start >= end:
            raise ScientificTraceError("cost-aware test window is reversed")
        eligible = tuple(
            _strict_date("window eligible date", item)
            for item in _sequence("window eligible_dates", row.get("eligible_dates"))
        )
        if not eligible or eligible != tuple(sorted(set(eligible))):
            raise ScientificTraceError(
                "cost-aware eligible dates must be sorted and unique"
            )
        if any(item in all_dates for item in eligible):
            raise ScientificTraceError(
                "cost-aware fold calendars must be disjoint"
            )
        all_dates.update(eligible)
        if eligible[0] < start.date().isoformat() or eligible[-1] > end.date().isoformat():
            raise ScientificTraceError(
                "cost-aware eligible date lies outside its test window"
            )
        rows.append(
            {
                "eligible_dates": list(eligible),
                "fold_id": fold_id,
                "test_end": _iso(end),
                "test_start": _iso(start),
            }
        )
    if len(all_dates) < 30:
        raise ScientificTraceError(
            "cost-aware selection inference requires at least 30 eligible dates"
        )
    result = tuple(sorted(rows, key=lambda item: str(item["fold_id"])))
    canonical_bytes(list(result))
    return result


def _normalize_source_input(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, object], ...]:
    normalized: list[dict[str, object]] = []
    prior_index = -1
    seen: set[int] = set()
    for raw in _sequence("cost-aware source input", rows):
        row = _mapping("cost-aware source row", raw)
        if set(row) != _SOURCE_INPUT_FIELDS:
            raise ScientificTraceError("cost-aware source input schema is invalid")
        index = _integer("source bar_index", row.get("bar_index"), minimum=0)
        if index in seen or index <= prior_index:
            raise ScientificTraceError(
                "cost-aware source input must be sorted and global-index unique"
            )
        seen.add(index)
        prior_index = index
        bar_open = _timestamp("source bar_open_time", row.get("bar_open_time"))
        opened = _integer(
            "source open_micropoints", row.get("open_micropoints"), minimum=1
        )
        spread = _integer(
            "source raw_spread_millipoints",
            row.get("raw_spread_millipoints"),
            minimum=0,
        )
        normalized.append(
            {
                "bar_index": index,
                "bar_open_time": _iso(bar_open),
                "open_micropoints": opened,
                "raw_spread_millipoints": spread,
            }
        )
    if not normalized:
        raise ScientificTraceError("cost-aware source input is empty")
    return tuple(normalized)


def _candidate_stream_id(value: Mapping[str, Any]) -> str:
    payload = {
        key: value[key]
        for key in (
            "decision_bar_index",
            "decision_time",
            "direction",
            "fold_id",
            "ordinal",
            "regime",
        )
    }
    return "candidate:" + canonical_digest(
        domain="cost-aware-execution-common-candidate",
        payload=payload,
    )


def _normalize_candidate_input(
    rows: Sequence[Mapping[str, Any]],
    *,
    windows: Sequence[Mapping[str, Any]],
    source_by_index: Mapping[int, Mapping[str, Any]],
) -> tuple[dict[str, object], ...]:
    window_by_fold = {str(item["fold_id"]): item for item in windows}
    window_runtime = {
        fold_id: (
            _timestamp("window test_start", window["test_start"]),
            _timestamp("window test_end", window["test_end"]),
            frozenset(str(item) for item in window["eligible_dates"]),
        )
        for fold_id, window in window_by_fold.items()
    }
    source_indices = tuple(sorted(source_by_index))
    source_times = {
        index: _timestamp(
            "candidate source time",
            source_by_index[index]["bar_open_time"],
        )
        for index in source_indices
    }
    source_context_by_decision: dict[
        int,
        tuple[int, int, int, datetime, datetime, datetime, int, int | None, str],
    ] = {}
    normalized: list[dict[str, object]] = []
    for raw in _sequence("cost-aware candidate input", rows):
        row = _mapping("cost-aware candidate row", raw)
        if set(row) != _CANDIDATE_INPUT_FIELDS:
            raise ScientificTraceError("cost-aware candidate input schema is invalid")
        fold_id = _ascii("candidate fold_id", row.get("fold_id"))
        if fold_id not in window_by_fold:
            raise ScientificTraceError("candidate belongs to an unknown fold")
        scope = _ascii("candidate scope", row.get("scope"))
        if scope not in _ALLOWED_SCOPES:
            raise ScientificTraceError("candidate scope must be full or prefix")
        ordinal = _integer("candidate ordinal", row.get("ordinal"), minimum=1)
        decision_index = _integer(
            "candidate decision_bar_index",
            row.get("decision_bar_index"),
            minimum=0,
        )
        decision_time = _timestamp("candidate decision_time", row.get("decision_time"))
        direction = _integer("candidate direction", row.get("direction"))
        if direction not in {-1, 1}:
            raise ScientificTraceError("candidate direction must be -1 or 1")
        regime = _ascii("candidate regime", row.get("regime"))
        if regime not in _ALLOWED_REGIMES:
            raise ScientificTraceError("candidate regime is invalid")
        source_context = source_context_by_decision.get(decision_index)
        if source_context is None:
            entry_index = decision_index + 1
            exit_index = entry_index + _HOLDING_BARS
            rolling_floor = max(0, decision_index - _SOURCE_HISTORY_BARS)
            support_start = max(0, rolling_floor - 1)
            left = bisect_left(source_indices, support_start)
            right = bisect_right(source_indices, exit_index)
            if right - left != exit_index - support_start + 1:
                raise ScientificTraceError(
                    "candidate-bounded source support is incomplete"
                )
            decision_bar = source_times[decision_index]
            entry_time = source_times[entry_index]
            exit_time = source_times[exit_index]
            context_start = rolling_floor
            predecessor: int | None = None
            if rolling_floor > 0:
                previous = source_times[rolling_floor - 1]
                first = source_times[rolling_floor]
                if first - previous != _BAR_DURATION:
                    predecessor = rolling_floor - 1
            prior = source_times[rolling_floor]
            for index in range(rolling_floor + 1, decision_index + 1):
                current = source_times[index]
                if current - prior != _BAR_DURATION:
                    context_start = index
                    predecessor = index - 1
                prior = current
            if context_start == 0:
                reason = "dataset_start"
                predecessor = None
            elif predecessor is not None:
                reason = "segment_start"
            else:
                reason = "rolling_truncation"
            source_context = (
                entry_index,
                exit_index,
                rolling_floor,
                decision_bar,
                entry_time,
                exit_time,
                context_start,
                predecessor,
                reason,
            )
            source_context_by_decision[decision_index] = source_context
        (
            entry_index,
            exit_index,
            rolling_floor,
            decision_bar,
            entry_time,
            exit_time,
            context_start,
            predecessor,
            reason,
        ) = source_context
        window_start, window_end, eligible_dates = window_runtime[fold_id]
        if not (
            window_start <= decision_bar
            and exit_time <= window_end
            and decision_bar.date().isoformat() in eligible_dates
        ):
            raise ScientificTraceError("candidate lies outside its exact fold calendar")
        candidate: dict[str, object] = {
            "availability_time": _iso(decision_bar + _BAR_DURATION),
            "candidate_stream_id": "pending",
            "context_start_bar_index": context_start,
            "context_start_reason": reason,
            "decision_bar_index": decision_index,
            "decision_bar_open_time": _iso(decision_bar),
            "decision_time": _iso(decision_time),
            "direction": direction,
            "entry_bar_index": entry_index,
            "entry_time": _iso(entry_time),
            "exit_bar_index": exit_index,
            "exit_time": _iso(exit_time),
            "fold_id": fold_id,
            "holding_bars": _HOLDING_BARS,
            "observation_id": "pending",
            "ordinal": ordinal,
            "regime": regime,
            "schema": COST_AWARE_EXECUTION_CANDIDATE_OBSERVATION_SCHEMA,
            "scope": scope,
            "segment_predecessor_bar_index": predecessor,
        }
        candidate["candidate_stream_id"] = _candidate_stream_id(candidate)
        candidate["observation_id"] = _observation_id("candidate", candidate)
        normalized.append(candidate)
    result = tuple(
        sorted(
            normalized,
            key=lambda item: (
                str(item["fold_id"]),
                str(item["scope"]),
                int(item["ordinal"]),
            ),
        )
    )
    seen: set[tuple[str, str, int]] = set()
    for item in result:
        key = (str(item["fold_id"]), str(item["scope"]), int(item["ordinal"]))
        if key in seen:
            raise ScientificTraceError("candidate ordinal is duplicated")
        seen.add(key)
    for fold_id in window_by_fold:
        for scope in sorted(_ALLOWED_SCOPES):
            scoped = tuple(
                item
                for item in result
                if item["fold_id"] == fold_id and item["scope"] == scope
            )
            ordinals = tuple(int(item["ordinal"]) for item in scoped)
            if ordinals != tuple(range(1, len(ordinals) + 1)):
                raise ScientificTraceError("candidate ordinals must be contiguous")
            indices = tuple(int(item["decision_bar_index"]) for item in scoped)
            if any(right <= left for left, right in zip(indices, indices[1:])):
                raise ScientificTraceError(
                    "candidate decision indices must be strictly increasing"
                )
    return result


def _materialize_source_union(
    source_by_index: Mapping[int, Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, object], ...]:
    required: set[int] = set()
    for candidate in candidates:
        start = int(candidate["context_start_bar_index"])
        end = int(candidate["exit_bar_index"])
        required.update(range(start, end + 1))
        predecessor = candidate["segment_predecessor_bar_index"]
        if predecessor is not None:
            required.add(int(predecessor))
    rows: list[dict[str, object]] = []
    for index in sorted(required):
        raw = source_by_index[index]
        opened = _timestamp("source union bar_open_time", raw["bar_open_time"])
        row: dict[str, object] = {
            **dict(raw),
            "information_complete_at": _iso(opened + _BAR_DURATION),
            "observation_id": "pending",
            "schema": COST_AWARE_EXECUTION_SOURCE_OBSERVATION_SCHEMA,
        }
        row["observation_id"] = _observation_id("source", row)
        rows.append(row)
    return tuple(rows)


def _median(values: Sequence[int]) -> int:
    if not values:
        raise RuntimeError("median requires at least one value")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    total = ordered[middle - 1] + ordered[middle]
    if total % 2:
        raise ScientificTraceError(
            "spread median is not exactly representable in millipoints"
        )
    return total // 2


def _derived_spreads(
    candidate: Mapping[str, Any],
    source_by_index: Mapping[int, Mapping[str, Any]],
) -> tuple[dict[int, int | None], int | None, int]:
    start = int(candidate["context_start_bar_index"])
    decision = int(candidate["decision_bar_index"])
    exit_index = int(candidate["exit_bar_index"])
    for index in range(start, exit_index + 1):
        if index not in source_by_index:
            raise ScientificTraceError("candidate causal source interval is incomplete")
    effective: dict[int, int | None] = {}
    segment_start = start
    prior_time: datetime | None = None
    for index in range(start, exit_index + 1):
        row = source_by_index[index]
        opened = _timestamp("derived spread source time", row["bar_open_time"])
        if prior_time is not None and opened - prior_time != _BAR_DURATION:
            segment_start = index
        raw = _integer(
            "derived raw spread",
            row["raw_spread_millipoints"],
            minimum=0,
        )
        if raw > 0:
            effective[index] = raw
        else:
            prior_positive = [
                int(source_by_index[prior]["raw_spread_millipoints"])
                for prior in range(max(segment_start, index - _SPREAD_REFERENCE_BARS), index)
                if int(source_by_index[prior]["raw_spread_millipoints"]) > 0
            ]
            effective[index] = (
                _median(prior_positive)
                if len(prior_positive) >= _SPREAD_REFERENCE_MIN_PERIODS
                else None
            )
        prior_time = opened
    reference_values = [
        effective[index]
        for index in range(max(segment_start, decision - _SPREAD_REFERENCE_BARS), decision)
        if effective[index] is not None
    ]
    reference = (
        _median([int(value) for value in reference_values])
        if len(reference_values) >= _SPREAD_REFERENCE_MIN_PERIODS
        else None
    )
    return effective, reference, len(reference_values)


def _derived_spreads_cache_key(
    candidate: Mapping[str, Any],
) -> tuple[str, int, int, int]:
    return (
        str(candidate["candidate_stream_id"]),
        int(candidate["context_start_bar_index"]),
        int(candidate["decision_bar_index"]),
        int(candidate["exit_bar_index"]),
    )


def _cached_derived_spreads(
    candidate: Mapping[str, Any],
    source_by_index: Mapping[int, Mapping[str, Any]],
    cache: dict[
        tuple[str, int, int, int],
        tuple[dict[int, int | None], int | None, int],
    ],
) -> tuple[dict[int, int | None], int | None, int]:
    key = _derived_spreads_cache_key(candidate)
    cached = cache.get(key)
    if cached is None:
        cached = _derived_spreads(candidate, source_by_index)
        cache[key] = cached
    return cached


def _member_inventory(
    definition: CostAwareExecutionProtocolDefinition,
) -> tuple[dict[str, object], ...]:
    return tuple(item.manifest() for item in definition.member_bindings)


def _path_is_contiguous(
    candidate: Mapping[str, Any],
    source_by_index: Mapping[int, Mapping[str, Any]],
) -> bool:
    start = int(candidate["decision_bar_index"])
    end = int(candidate["exit_bar_index"])
    prior = _timestamp("path source time", source_by_index[start]["bar_open_time"])
    for index in range(start + 1, end + 1):
        current = _timestamp(
            "path source time", source_by_index[index]["bar_open_time"]
        )
        if current - prior != _BAR_DURATION:
            return False
        prior = current
    return True


def _intent_row(
    *,
    member: Mapping[str, Any],
    candidate: Mapping[str, Any],
    source_by_index: Mapping[int, Mapping[str, Any]],
    status: str,
    predicate_evaluated: bool,
    effective: Mapping[int, int | None] | None,
    reference: int | None,
    reference_count: int | None,
) -> dict[str, object]:
    if status not in _ALLOWED_STATUSES:
        raise RuntimeError("cost-aware execution status drifted")
    decision_index = int(candidate["decision_bar_index"])
    exit_source_index = int(candidate["exit_bar_index"]) - 1
    decision_source = source_by_index[decision_index]
    exit_source = source_by_index[exit_source_index]
    entry_value = None if effective is None else effective[decision_index]
    exit_value = None if effective is None else effective[exit_source_index]

    gate_known: bool | None = None
    gate_reference_known: bool | None = None
    gate_value: int | None = None
    gate_reference_value: int | None = None
    gate_count: int | None = None
    entry_known: bool | None = None
    entry_spread: int | None = None
    exit_known: bool | None = None
    exit_spread: int | None = None

    if predicate_evaluated:
        gate_known = entry_value is not None
        gate_reference_known = reference is not None
        gate_value = None if entry_value is None else int(entry_value)
        gate_reference_value = None if reference is None else int(reference)
        gate_count = int(reference_count) if reference_count is not None else 0
        entry_known = gate_known
        entry_spread = gate_value

    if status in {"executed", "unknown_cost"}:
        if not predicate_evaluated:
            entry_known = entry_value is not None
            entry_spread = None if entry_value is None else int(entry_value)
        exit_known = exit_value is not None
        exit_spread = None if exit_value is None else int(exit_value)

    row: dict[str, object] = {
        "availability_time": candidate["availability_time"],
        "candidate_stream_id": candidate["candidate_stream_id"],
        "configuration_id": member["configuration_id"],
        "decision_bar_index": decision_index,
        "decision_bar_open_time": candidate["decision_bar_open_time"],
        "decision_spread_information_complete_at": decision_source[
            "information_complete_at"
        ],
        "decision_spread_source_bar_index": decision_index,
        "decision_spread_source_bar_open_time": decision_source[
            "bar_open_time"
        ],
        "decision_time": candidate["decision_time"],
        "direction": candidate["direction"],
        "entry_bar_index": candidate["entry_bar_index"],
        "entry_spread_information_complete_at": decision_source[
            "information_complete_at"
        ],
        "entry_spread_known": entry_known,
        "entry_spread_millipoints": entry_spread,
        "entry_spread_source_bar_index": decision_index,
        "entry_spread_source_bar_open_time": decision_source["bar_open_time"],
        "entry_time": candidate["entry_time"],
        "executable_id": member["prospective_executable_id"],
        "exit_bar_index": candidate["exit_bar_index"],
        "exit_spread_information_complete_at": exit_source[
            "information_complete_at"
        ],
        "exit_spread_known": exit_known,
        "exit_spread_millipoints": exit_spread,
        "exit_spread_source_bar_index": exit_source_index,
        "exit_spread_source_bar_open_time": exit_source["bar_open_time"],
        "exit_time": candidate["exit_time"],
        "fold_id": candidate["fold_id"],
        "gate_reference_known": gate_reference_known,
        "gate_reference_millipoints": gate_reference_value,
        "gate_reference_observation_count": gate_count,
        "gate_spread_known": gate_known,
        "gate_spread_millipoints": gate_value,
        "historical_reference_executable_id": member[
            "historical_executable_id"
        ],
        "holding_bars": _HOLDING_BARS,
        "observation_id": "pending",
        "ordinal": candidate["ordinal"],
        "policy": member["execution_policy"],
        "predicate_evaluated": predicate_evaluated,
        "regime": candidate["regime"],
        "schema": COST_AWARE_EXECUTION_INTENT_OBSERVATION_SCHEMA,
        "scope": candidate["scope"],
        "spread_semantics": _SPREAD_SEMANTICS,
        "status": status,
    }
    row["observation_id"] = _observation_id("intent", row)
    return row


def _simulate_pair_intents(
    *,
    definition: CostAwareExecutionProtocolDefinition,
    candidates: Sequence[Mapping[str, Any]],
    source_by_index: Mapping[int, Mapping[str, Any]],
    derived_spread_cache: dict[
        tuple[str, int, int, int],
        tuple[dict[int, int | None], int | None, int],
    ] | None = None,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    spread_cache = {} if derived_spread_cache is None else derived_spread_cache
    causal_inputs: dict[
        tuple[str, int, int, int],
        tuple[
            str,
            dict[int, int | None] | None,
            int | None,
            int | None,
        ],
    ] = {}
    for member in _member_inventory(definition):
        policy = str(member["execution_policy"])
        if policy not in {"unconditional_next_open", "causal_spread_abstention"}:
            raise ScientificTraceError("cost-aware execution policy is invalid")
        for fold_id in sorted({str(item["fold_id"]) for item in candidates}):
            for scope in sorted(_ALLOWED_SCOPES):
                next_decision_index = -1
                selected = sorted(
                    (
                        item
                        for item in candidates
                        if item["fold_id"] == fold_id and item["scope"] == scope
                    ),
                    key=lambda item: int(item["ordinal"]),
                )
                for candidate in selected:
                    decision_index = int(candidate["decision_bar_index"])
                    if decision_index < next_decision_index:
                        continue
                    predicate_evaluated = False
                    causal_key = _derived_spreads_cache_key(candidate)
                    cached = causal_inputs.get(causal_key)
                    if cached is None:
                        if not _path_is_contiguous(candidate, source_by_index):
                            cached = ("gap_excluded", None, None, None)
                        elif _timestamp(
                            "candidate decision_time", candidate["decision_time"]
                        ) != _timestamp(
                            "candidate entry_time", candidate["entry_time"]
                        ):
                            cached = ("causality_violation", None, None, None)
                        else:
                            effective, reference, reference_count = (
                                _cached_derived_spreads(
                                    candidate,
                                    source_by_index,
                                    spread_cache,
                                )
                            )
                            cached = (
                                "ready",
                                effective,
                                reference,
                                reference_count,
                            )
                        causal_inputs[causal_key] = cached
                    causal_status, effective, reference, reference_count = cached
                    if causal_status != "ready":
                        status = causal_status
                    else:
                        if effective is None:
                            raise RuntimeError(
                                "ready causal input lacks derived spreads"
                            )
                        entry_value = effective[decision_index]
                        if policy == "causal_spread_abstention":
                            predicate_evaluated = True
                            if entry_value is None or reference is None:
                                status = "entry_cancelled_unknown_gate"
                            elif (
                                int(entry_value) * 1_000
                                > int(reference) * _SPREAD_LIMIT_MILLI
                            ):
                                status = "spread_abstained"
                            else:
                                next_decision_index = int(candidate["exit_bar_index"])
                                exit_value = effective[
                                    int(candidate["exit_bar_index"]) - 1
                                ]
                                status = (
                                    "executed"
                                    if entry_value is not None and exit_value is not None
                                    else "unknown_cost"
                                )
                        else:
                            next_decision_index = int(candidate["exit_bar_index"])
                            exit_value = effective[
                                int(candidate["exit_bar_index"]) - 1
                            ]
                            status = (
                                "executed"
                                if entry_value is not None and exit_value is not None
                                else "unknown_cost"
                            )
                    rows.append(
                        _intent_row(
                            member=member,
                            candidate=candidate,
                            source_by_index=source_by_index,
                            status=status,
                            predicate_evaluated=predicate_evaluated,
                            effective=effective,
                            reference=reference,
                            reference_count=reference_count,
                        )
                    )
    result = tuple(
        sorted(
            rows,
            key=lambda item: (
                str(item["configuration_id"]),
                str(item["fold_id"]),
                str(item["scope"]),
                int(item["ordinal"]),
            ),
        )
    )
    return result


def _trade_row(
    intent: Mapping[str, Any],
    source_by_index: Mapping[int, Mapping[str, Any]],
) -> dict[str, object]:
    entry_index = int(intent["entry_bar_index"])
    exit_index = int(intent["exit_bar_index"])
    direction = int(intent["direction"])
    entry_open = int(source_by_index[entry_index]["open_micropoints"])
    exit_open = int(source_by_index[exit_index]["open_micropoints"])
    entry_spread = int(intent["entry_spread_millipoints"])
    exit_spread = int(intent["exit_spread_millipoints"])
    gross = direction * (exit_open - entry_open)
    native_cost = (
        entry_spread * 10 if direction == 1 else exit_spread * 10
    )
    stress_cost = native_cost + (entry_spread + exit_spread) * 5
    row: dict[str, object] = {
        "availability_time": intent["availability_time"],
        "candidate_stream_id": intent["candidate_stream_id"],
        "configuration_id": intent["configuration_id"],
        "decision_bar_index": intent["decision_bar_index"],
        "decision_bar_open_time": intent["decision_bar_open_time"],
        "decision_time": intent["decision_time"],
        "direction": direction,
        "entry_bar_index": entry_index,
        "entry_spread_millipoints": entry_spread,
        "entry_spread_source_bar_index": intent[
            "entry_spread_source_bar_index"
        ],
        "entry_time": intent["entry_time"],
        "executable_id": intent["executable_id"],
        "exit_bar_index": exit_index,
        "exit_spread_millipoints": exit_spread,
        "exit_spread_source_bar_index": intent["exit_spread_source_bar_index"],
        "exit_time": intent["exit_time"],
        "fold_id": intent["fold_id"],
        "gross_pnl_micropoints": gross,
        "historical_reference_executable_id": intent[
            "historical_reference_executable_id"
        ],
        "holding_bars": _HOLDING_BARS,
        "intent_observation_id": intent["observation_id"],
        "native_cost_micropoints": native_cost,
        "native_net_pnl_micropoints": gross - native_cost,
        "observation_id": "pending",
        "policy": intent["policy"],
        "regime": intent["regime"],
        "schema": COST_AWARE_EXECUTION_TRADE_OBSERVATION_SCHEMA,
        "spread_semantics": _SPREAD_SEMANTICS,
        "stress_cost_micropoints": stress_cost,
        "stress_net_pnl_micropoints": gross - stress_cost,
    }
    row["observation_id"] = _observation_id("trade", row)
    return row


def _materialize_trades(
    intents: Sequence[Mapping[str, Any]],
    source_by_index: Mapping[int, Mapping[str, Any]],
) -> tuple[dict[str, object], ...]:
    rows = tuple(
        _trade_row(item, source_by_index)
        for item in intents
        if item["scope"] == "full" and item["status"] == "executed"
    )
    result = tuple(
        sorted(
            rows,
            key=lambda item: (
                str(item["configuration_id"]),
                str(item["fold_id"]),
                str(item["decision_time"]),
                str(item["observation_id"]),
            ),
        )
    )
    canonical_bytes(list(result))
    return result


def _materialize_eligible_days(
    *,
    definition: CostAwareExecutionProtocolDefinition,
    windows: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for member in _member_inventory(definition):
        executable_id = str(member["prospective_executable_id"])
        configuration_id = str(member["configuration_id"])
        for window in windows:
            fold_id = str(window["fold_id"])
            for day in window["eligible_dates"]:
                selected = [
                    trade
                    for trade in trades
                    if trade["executable_id"] == executable_id
                    and trade["fold_id"] == fold_id
                    and str(trade["decision_time"])[:10] == day
                ]
                rows.append(
                    {
                        "configuration_id": configuration_id,
                        "date": day,
                        "entry_count": len(selected),
                        "executable_id": executable_id,
                        "fold_id": fold_id,
                        "native_net_pnl_micropoints": sum(
                            int(item["native_net_pnl_micropoints"])
                            for item in selected
                        ),
                        "schema": COST_AWARE_EXECUTION_ELIGIBLE_DAY_SCHEMA,
                        "stress_net_pnl_micropoints": sum(
                            int(item["stress_net_pnl_micropoints"])
                            for item in selected
                        ),
                    }
                )
    result = tuple(
        sorted(
            rows,
            key=lambda item: (
                str(item["executable_id"]),
                str(item["fold_id"]),
                str(item["date"]),
            ),
        )
    )
    canonical_bytes(list(result))
    return result


def _comparison_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    return sha256(canonical_bytes(list(rows))).hexdigest()


def _sequence_mismatch_count(left: Sequence[object], right: Sequence[object]) -> int:
    return abs(len(left) - len(right)) + sum(
        first != second for first, second in zip(left, right)
    )


def _materialize_invariance(
    *,
    candidates: Sequence[Mapping[str, Any]],
    intents: Sequence[Mapping[str, Any]],
    source_by_index: Mapping[int, Mapping[str, Any]],
    derived_spread_cache: dict[
        tuple[str, int, int, int],
        tuple[dict[int, int | None], int | None, int],
    ] | None = None,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    spread_cache = {} if derived_spread_cache is None else derived_spread_cache
    fold_ids = sorted({str(item["fold_id"]) for item in candidates})
    for fold_id in fold_ids:
        candidate_payload: dict[str, list[dict[str, object]]] = {}
        gate_payload: dict[str, list[dict[str, object]]] = {}
        intent_payload: dict[str, list[dict[str, object]]] = {}
        for scope in sorted(_ALLOWED_SCOPES):
            scoped_candidates = sorted(
                (
                    item
                    for item in candidates
                    if item["fold_id"] == fold_id and item["scope"] == scope
                ),
                key=lambda item: int(item["ordinal"]),
            )
            candidate_payload[scope] = [
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"observation_id", "scope"}
                }
                for item in scoped_candidates
            ]
            gate_payload[scope] = []
            for item in scoped_candidates:
                effective, reference, count = _cached_derived_spreads(
                    item,
                    source_by_index,
                    spread_cache,
                )
                gate_payload[scope].append(
                    {
                        "candidate_stream_id": item["candidate_stream_id"],
                        "effective_spread_millipoints": effective[
                            int(item["decision_bar_index"])
                        ],
                        "reference_millipoints": reference,
                        "reference_observation_count": count,
                    }
                )
            scoped_intents = sorted(
                (
                    item
                    for item in intents
                    if item["fold_id"] == fold_id and item["scope"] == scope
                ),
                key=lambda item: (
                    str(item["configuration_id"]), int(item["ordinal"])
                ),
            )
            intent_payload[scope] = [
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"observation_id", "scope"}
                }
                for item in scoped_intents
            ]
        candidate_hashes = {
            scope: _comparison_hash(candidate_payload[scope])
            for scope in _ALLOWED_SCOPES
        }
        gate_hashes = {
            scope: _comparison_hash(gate_payload[scope])
            for scope in _ALLOWED_SCOPES
        }
        intent_hashes = {
            scope: _comparison_hash(intent_payload[scope])
            for scope in _ALLOWED_SCOPES
        }
        candidate_mismatches = _sequence_mismatch_count(
            candidate_payload["full"], candidate_payload["prefix"]
        )
        gate_mismatches = _sequence_mismatch_count(
            gate_payload["full"], gate_payload["prefix"]
        )
        intent_mismatches = _sequence_mismatch_count(
            intent_payload["full"], intent_payload["prefix"]
        )
        mismatch_count = (
            candidate_mismatches + gate_mismatches + intent_mismatches
        )
        rows.append(
            {
                "candidate_mismatch_count": candidate_mismatches,
                "candidate_full_sha256": candidate_hashes["full"],
                "full_candidate_count": len(candidate_payload["full"]),
                "candidate_prefix_sha256": candidate_hashes["prefix"],
                "fold_id": fold_id,
                "gate_mismatch_count": gate_mismatches,
                "gate_full_sha256": gate_hashes["full"],
                "gate_prefix_sha256": gate_hashes["prefix"],
                "intent_mismatch_count": intent_mismatches,
                "intent_full_sha256": intent_hashes["full"],
                "intent_prefix_sha256": intent_hashes["prefix"],
                "mismatch_count": mismatch_count,
                "prefix_candidate_count": len(candidate_payload["prefix"]),
                "schema": COST_AWARE_EXECUTION_INVARIANCE_SCHEMA,
            }
        )
    return tuple(rows)


def _validate_materialized_sources(
    rows: object,
) -> tuple[dict[str, object], ...]:
    normalized: list[dict[str, object]] = []
    prior_index = -1
    seen: set[int] = set()
    for raw in _sequence("cost-aware source observations", rows):
        row = _mapping("cost-aware source observation", raw)
        if set(row) != _SOURCE_FIELDS:
            raise ScientificTraceError("cost-aware source observation schema is invalid")
        if row.get("schema") != COST_AWARE_EXECUTION_SOURCE_OBSERVATION_SCHEMA:
            raise ScientificTraceError("cost-aware source observation version drifted")
        index = _integer("source observation bar_index", row.get("bar_index"), minimum=0)
        if index in seen or index <= prior_index:
            raise ScientificTraceError("source observations must be sorted and unique")
        seen.add(index)
        prior_index = index
        opened = _timestamp("source observation bar_open_time", row.get("bar_open_time"))
        if _timestamp(
            "source observation information_complete_at",
            row.get("information_complete_at"),
        ) != opened + _BAR_DURATION:
            raise ScientificTraceError("source information-complete clock is invalid")
        _integer("source observation open", row.get("open_micropoints"), minimum=1)
        _integer(
            "source observation spread",
            row.get("raw_spread_millipoints"),
            minimum=0,
        )
        if row.get("observation_id") != _observation_id("source", row):
            raise ScientificTraceError("source observation identity is forged")
        normalized.append(dict(row))
    if not normalized:
        raise ScientificTraceError("cost-aware source observations are empty")
    return tuple(normalized)


def _validate_materialized_candidates(
    rows: object,
    *,
    windows: Sequence[Mapping[str, Any]],
    source_by_index: Mapping[int, Mapping[str, Any]],
) -> tuple[dict[str, object], ...]:
    window_by_fold = {str(item["fold_id"]): item for item in windows}
    window_runtime = {
        fold_id: (
            _timestamp("candidate window start", window["test_start"]),
            _timestamp("candidate window end", window["test_end"]),
            frozenset(str(item) for item in window["eligible_dates"]),
        )
        for fold_id, window in window_by_fold.items()
    }
    source_indices = tuple(sorted(source_by_index))
    source_times = {
        index: _timestamp(
            "candidate materialized source time",
            source_by_index[index]["bar_open_time"],
        )
        for index in source_indices
    }
    validated_context_paths: set[tuple[int, int]] = set()
    normalized: list[dict[str, object]] = []
    prior_key: tuple[str, str, int] | None = None
    seen_keys: set[tuple[str, str, int]] = set()
    for raw in _sequence("cost-aware candidate observations", rows):
        row = _mapping("cost-aware candidate observation", raw)
        if set(row) != _CANDIDATE_FIELDS:
            raise ScientificTraceError("cost-aware candidate observation schema is invalid")
        if row.get("schema") != COST_AWARE_EXECUTION_CANDIDATE_OBSERVATION_SCHEMA:
            raise ScientificTraceError("cost-aware candidate observation version drifted")
        fold_id = _ascii("candidate observation fold_id", row.get("fold_id"))
        scope = _ascii("candidate observation scope", row.get("scope"))
        ordinal = _integer("candidate observation ordinal", row.get("ordinal"), minimum=1)
        key = (fold_id, scope, ordinal)
        if fold_id not in window_by_fold or scope not in _ALLOWED_SCOPES:
            raise ScientificTraceError("candidate fold or scope is invalid")
        if key in seen_keys or (prior_key is not None and key <= prior_key):
            raise ScientificTraceError("candidate observations must be sorted and unique")
        seen_keys.add(key)
        prior_key = key
        decision = _integer(
            "candidate observation decision index",
            row.get("decision_bar_index"),
            minimum=0,
        )
        entry = _integer(
            "candidate observation entry index", row.get("entry_bar_index"), minimum=1
        )
        exit_index = _integer(
            "candidate observation exit index", row.get("exit_bar_index"), minimum=1
        )
        start = _integer(
            "candidate observation context start",
            row.get("context_start_bar_index"),
            minimum=0,
        )
        if entry != decision + 1 or exit_index != entry + _HOLDING_BARS:
            raise ScientificTraceError("candidate fixed-hold indices are invalid")
        if row.get("holding_bars") != _HOLDING_BARS:
            raise ScientificTraceError("candidate holding interval drifted")
        left = bisect_left(source_indices, start)
        right = bisect_right(source_indices, exit_index)
        if right - left != exit_index - start + 1:
            raise ScientificTraceError("candidate source support is incomplete")
        source_decision = source_by_index[decision]
        source_entry = source_by_index[entry]
        source_exit = source_by_index[exit_index]
        if (
            row.get("decision_bar_open_time") != source_decision["bar_open_time"]
            or row.get("availability_time")
            != source_decision["information_complete_at"]
            or row.get("entry_time") != source_entry["bar_open_time"]
            or row.get("exit_time") != source_exit["bar_open_time"]
        ):
            raise ScientificTraceError("candidate source clock is invalid")
        _timestamp("candidate observation decision_time", row.get("decision_time"))
        if row.get("direction") not in {-1, 1} or row.get("regime") not in _ALLOWED_REGIMES:
            raise ScientificTraceError("candidate direction or regime is invalid")
        reason = row.get("context_start_reason")
        predecessor = row.get("segment_predecessor_bar_index")
        rolling_floor = max(0, decision - _SOURCE_HISTORY_BARS)
        if reason == "dataset_start":
            if start != 0 or predecessor is not None or rolling_floor != 0:
                raise ScientificTraceError("dataset-start source context is invalid")
        elif reason == "rolling_truncation":
            if start != rolling_floor or start == 0 or predecessor is not None:
                raise ScientificTraceError("rolling source context is invalid")
        elif reason == "segment_start":
            if type(predecessor) is not int or predecessor != start - 1 or start < rolling_floor:
                raise ScientificTraceError("segment-start source context is invalid")
            if predecessor not in source_by_index:
                raise ScientificTraceError("segment predecessor evidence is absent")
            previous_time = source_times[predecessor]
            start_time = source_times[start]
            if start_time - previous_time == _BAR_DURATION:
                raise ScientificTraceError("segment reset has no timestamp gap")
        else:
            raise ScientificTraceError("candidate context-start reason is invalid")
        context_path = (start, decision)
        if context_path not in validated_context_paths:
            prior_time = source_times[start]
            for index in range(start + 1, decision + 1):
                current = source_times[index]
                if current - prior_time != _BAR_DURATION:
                    raise ScientificTraceError(
                        "candidate gate history crosses a gap"
                    )
                prior_time = current
            validated_context_paths.add(context_path)
        if row.get("candidate_stream_id") != _candidate_stream_id(row):
            raise ScientificTraceError("candidate stream identity is forged")
        if row.get("observation_id") != _observation_id("candidate", row):
            raise ScientificTraceError("candidate observation identity is forged")
        window_start, window_end, eligible_dates = window_runtime[fold_id]
        if not (
            window_start <= source_times[decision]
            and source_times[exit_index] <= window_end
            and str(row["decision_bar_open_time"])[:10] in eligible_dates
        ):
            raise ScientificTraceError("candidate lies outside its exact fold calendar")
        normalized.append(dict(row))
    for fold_id in window_by_fold:
        for scope in sorted(_ALLOWED_SCOPES):
            scoped = tuple(
                row
                for row in normalized
                if row["fold_id"] == fold_id and row["scope"] == scope
            )
            ordinals = tuple(int(row["ordinal"]) for row in scoped)
            if ordinals != tuple(range(1, len(ordinals) + 1)):
                raise ScientificTraceError("candidate ordinals are not contiguous")
            indices = tuple(int(row["decision_bar_index"]) for row in scoped)
            if any(right <= left for left, right in zip(indices, indices[1:])):
                raise ScientificTraceError(
                    "candidate decision indices must be strictly increasing"
                )
    if not normalized:
        raise ScientificTraceError("cost-aware candidate stream is empty")
    return tuple(normalized)


def compute_cost_aware_execution_pair_trace(
    *,
    definition: CostAwareExecutionProtocolDefinition,
    dataset_sha256: str,
    split_artifact_sha256: str,
    material_identity: str,
    windows: Sequence[Mapping[str, Any]],
    source_observations: Sequence[Mapping[str, Any]],
    candidate_observations: Sequence[Mapping[str, Any]],
    historical_context: HistoricalSearchContext | Mapping[str, Any],
) -> dict[str, object]:
    """Build and immediately validate one Job-neutral two-policy trace."""

    if not isinstance(definition, CostAwareExecutionProtocolDefinition):
        raise ScientificTraceError("cost-aware trace definition is not typed")
    normalized_windows = _normalize_windows(windows)
    source_input = _normalize_source_input(source_observations)
    source_input_by_index = {
        int(item["bar_index"]): item for item in source_input
    }
    candidates = _normalize_candidate_input(
        candidate_observations,
        windows=normalized_windows,
        source_by_index=source_input_by_index,
    )
    source_rows = _materialize_source_union(source_input_by_index, candidates)
    source_by_index = {int(item["bar_index"]): item for item in source_rows}
    derived_spread_cache: dict[
        tuple[str, int, int, int],
        tuple[dict[int, int | None], int | None, int],
    ] = {}
    intents = _simulate_pair_intents(
        definition=definition,
        candidates=candidates,
        source_by_index=source_by_index,
        derived_spread_cache=derived_spread_cache,
    )
    trades = _materialize_trades(intents, source_by_index)
    eligible_days = _materialize_eligible_days(
        definition=definition,
        windows=normalized_windows,
        trades=trades,
    )
    invariance = _materialize_invariance(
        candidates=candidates,
        intents=intents,
        source_by_index=source_by_index,
        derived_spread_cache=derived_spread_cache,
    )
    value = {
        "attribution": _static_attribution(),
        "candidate_observations": [dict(item) for item in candidates],
        "controls": _static_controls(definition),
        "dataset_sha256": _digest("cost-aware dataset_sha256", dataset_sha256),
        "eligible_day_observations": [dict(item) for item in eligible_days],
        "family_id": definition.prospective_family_id,
        "historical_context": _normalize_historical_context(
            historical_context, definition=definition
        ),
        "implementation_identities": _implementation_identities(),
        "intent_observations": [dict(item) for item in intents],
        "invariance_comparisons": [dict(item) for item in invariance],
        "material_identity": _ascii(
            "cost-aware material_identity", material_identity
        ),
        "ordered_family": [dict(item) for item in _member_inventory(definition)],
        "protocol_definition": definition.manifest(),
        "protocol_id": definition.protocol_id,
        "schema": COST_AWARE_EXECUTION_PAIR_TRACE_SCHEMA,
        "source_observations": [dict(item) for item in source_rows],
        "split_artifact_sha256": _digest(
            "cost-aware split_artifact_sha256", split_artifact_sha256
        ),
        "trade_observations": [dict(item) for item in trades],
        "windows": [dict(item) for item in normalized_windows],
    }
    return validate_cost_aware_execution_pair_trace(value, definition=definition)


def validate_cost_aware_execution_pair_trace(
    trace: Mapping[str, Any],
    *,
    definition: CostAwareExecutionProtocolDefinition,
) -> dict[str, object]:
    """Recompute every neutral pair row and reject any extra authority."""

    if not isinstance(definition, CostAwareExecutionProtocolDefinition):
        raise ScientificTraceError("cost-aware trace definition is not typed")
    normalized = _canonical_clone("cost-aware pair trace", trace)
    if set(normalized) != _PAIR_TRACE_FIELDS:
        raise ScientificTraceError("cost-aware pair trace schema is invalid")
    if (
        normalized.get("schema") != COST_AWARE_EXECUTION_PAIR_TRACE_SCHEMA
        or normalized.get("protocol_id") != COST_AWARE_EXECUTION_PROTOCOL_ID
        or normalized.get("family_id") != definition.prospective_family_id
        or normalized.get("protocol_definition") != definition.manifest()
        or normalized.get("ordered_family")
        != [dict(item) for item in _member_inventory(definition)]
        or normalized.get("controls") != _static_controls(definition)
        or normalized.get("attribution") != _static_attribution()
        or normalized.get("implementation_identities")
        != _implementation_identities()
    ):
        raise ScientificTraceError("cost-aware pair trace authority drifted")
    _digest("cost-aware pair dataset_sha256", normalized.get("dataset_sha256"))
    _digest(
        "cost-aware pair split_artifact_sha256",
        normalized.get("split_artifact_sha256"),
    )
    _ascii("cost-aware pair material_identity", normalized.get("material_identity"))
    current_context = _mapping(
        "cost-aware historical current context",
        normalized.get("historical_context"),
    )
    expected_context = _normalize_historical_context(
        current_context,
        definition=definition,
    )
    if normalized.get("historical_context") != expected_context:
        raise ScientificTraceError("cost-aware historical context drifted")
    windows = _normalize_windows(normalized.get("windows"))
    if list(windows) != normalized.get("windows"):
        raise ScientificTraceError("cost-aware windows are not canonical")
    sources = _validate_materialized_sources(normalized.get("source_observations"))
    source_by_index = {int(item["bar_index"]): item for item in sources}
    candidates = _validate_materialized_candidates(
        normalized.get("candidate_observations"),
        windows=windows,
        source_by_index=source_by_index,
    )
    required_sources: set[int] = set()
    for candidate in candidates:
        required_sources.update(
            range(
                int(candidate["context_start_bar_index"]),
                int(candidate["exit_bar_index"]) + 1,
            )
        )
        predecessor = candidate["segment_predecessor_bar_index"]
        if predecessor is not None:
            required_sources.add(int(predecessor))
    if set(source_by_index) != required_sources:
        raise ScientificTraceError("cost-aware source union is not minimal and exact")
    derived_spread_cache: dict[
        tuple[str, int, int, int],
        tuple[dict[int, int | None], int | None, int],
    ] = {}
    expected_intents = _simulate_pair_intents(
        definition=definition,
        candidates=candidates,
        source_by_index=source_by_index,
        derived_spread_cache=derived_spread_cache,
    )
    if normalized.get("intent_observations") != list(expected_intents):
        raise ScientificTraceError("cost-aware intent rows drifted from atomic sources")
    expected_trades = _materialize_trades(expected_intents, source_by_index)
    if normalized.get("trade_observations") != list(expected_trades):
        raise ScientificTraceError("cost-aware trades drifted from executed intents")
    expected_days = _materialize_eligible_days(
        definition=definition,
        windows=windows,
        trades=expected_trades,
    )
    if normalized.get("eligible_day_observations") != list(expected_days):
        raise ScientificTraceError(
            "cost-aware eligible-day rows are incomplete or forged"
        )
    expected_invariance = _materialize_invariance(
        candidates=candidates,
        intents=expected_intents,
        source_by_index=source_by_index,
        derived_spread_cache=derived_spread_cache,
    )
    if normalized.get("invariance_comparisons") != list(expected_invariance):
        raise ScientificTraceError("cost-aware invariance proof drifted")
    return normalized


def _pair_trace_sha256(trace: Mapping[str, Any]) -> str:
    return sha256(canonical_bytes(trace)).hexdigest()


def bind_cost_aware_execution_subject_trace(
    *,
    pair_trace: Mapping[str, Any],
    definition: CostAwareExecutionProtocolDefinition,
    mission_id: str,
    executable_id: str,
    job_id: str,
    job_hash: str,
) -> dict[str, object]:
    """Bind reusable pair bytes to one exact member Job."""

    pair = validate_cost_aware_execution_pair_trace(
        pair_trace, definition=definition
    )
    subject = _executable_id("cost-aware subject executable_id", executable_id)
    if subject not in definition.prospective_executable_ids:
        raise ScientificTraceError("cost-aware subject is outside the exact pair")
    binding = {
        "definition_identity": definition.identity,
        "implementation_identities": pair["implementation_identities"],
        "pair_trace_sha256": _pair_trace_sha256(pair),
        "schema": COST_AWARE_EXECUTION_PAIR_TRACE_SCHEMA,
    }
    copied = _PAIR_TRACE_FIELDS - {
        "attribution",
        "implementation_identities",
        "schema",
    }
    value = {
        **{name: pair[name] for name in copied},
        "adapter_implementation_sha256": (
            cost_aware_execution_trace_implementation_sha256()
        ),
        "attribution": {
            "pair_trace_binding": binding,
            "protocol_attribution": pair["attribution"],
        },
        "job_hash": _digest("cost-aware subject job_hash", job_hash),
        "job_id": _ascii("cost-aware subject job_id", job_id),
        "mission_id": _ascii("cost-aware subject mission_id", mission_id),
        "schema": SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
        "subject_executable_id": subject,
    }
    subject_trace, _ = _open_subject_trace(value, definition=definition)
    return subject_trace


def _open_subject_trace(
    trace: Mapping[str, Any],
    *,
    definition: CostAwareExecutionProtocolDefinition,
) -> tuple[dict[str, object], dict[str, object]]:
    normalized = _canonical_clone("cost-aware subject trace", trace)
    if set(normalized) != _SUBJECT_TRACE_FIELDS:
        raise ScientificTraceError("cost-aware subject trace schema is invalid")
    if (
        normalized.get("schema") != SCIENTIFIC_EVALUATION_TRACE_SCHEMA
        or normalized.get("protocol_id") != definition.protocol_id
        or normalized.get("protocol_definition") != definition.manifest()
        or normalized.get("adapter_implementation_sha256")
        != cost_aware_execution_trace_implementation_sha256()
    ):
        raise ScientificTraceError("cost-aware subject trace binding drifted")
    _ascii("cost-aware subject mission_id", normalized.get("mission_id"))
    _ascii("cost-aware subject job_id", normalized.get("job_id"))
    _digest("cost-aware subject job_hash", normalized.get("job_hash"))
    subject = _executable_id(
        "cost-aware subject executable_id",
        normalized.get("subject_executable_id"),
    )
    if subject not in definition.prospective_executable_ids:
        raise ScientificTraceError("cost-aware subject is outside the exact pair")
    attribution = _mapping(
        "cost-aware subject attribution", normalized.get("attribution")
    )
    if set(attribution) != {"pair_trace_binding", "protocol_attribution"}:
        raise ScientificTraceError("cost-aware subject attribution is invalid")
    binding = _mapping(
        "cost-aware pair trace binding", attribution.get("pair_trace_binding")
    )
    if set(binding) != {
        "definition_identity",
        "implementation_identities",
        "pair_trace_sha256",
        "schema",
    }:
        raise ScientificTraceError("cost-aware pair trace binding is invalid")
    copied = _PAIR_TRACE_FIELDS - {
        "attribution",
        "implementation_identities",
        "schema",
    }
    pair = {
        **{name: normalized[name] for name in copied},
        "attribution": attribution["protocol_attribution"],
        "implementation_identities": binding["implementation_identities"],
        "schema": binding["schema"],
    }
    pair = validate_cost_aware_execution_pair_trace(
        pair, definition=definition
    )
    if (
        binding.get("definition_identity") != definition.identity
        or binding.get("pair_trace_sha256") != _pair_trace_sha256(pair)
    ):
        raise ScientificTraceError("cost-aware neutral pair hash is forged")
    return normalized, pair


def validate_cost_aware_execution_subject_trace(
    trace: Mapping[str, Any],
    *,
    definition: CostAwareExecutionProtocolDefinition,
) -> dict[str, object]:
    return _open_subject_trace(trace, definition=definition)[0]


def extract_cost_aware_execution_pair_trace(
    trace: Mapping[str, Any],
    *,
    definition: CostAwareExecutionProtocolDefinition,
) -> dict[str, object]:
    return _open_subject_trace(trace, definition=definition)[1]


def _calculation_parameters(
    definition: CostAwareExecutionProtocolDefinition,
) -> dict[str, object]:
    inference = _mapping(
        "cost-aware protocol inference",
        definition.manifest().get("inference"),
    )
    block_lengths = tuple(
        _integer("cost-aware inference block length", item, minimum=1)
        for item in _sequence(
            "cost-aware inference block lengths", inference.get("block_lengths")
        )
    )
    if block_lengths != tuple(sorted(set(block_lengths))):
        raise ScientificTraceError("cost-aware inference block lengths drifted")
    value = {
        "alpha_ppm": _integer(
            "cost-aware inference alpha_ppm", inference.get("alpha_ppm"), minimum=1
        ),
        "base_seed": _integer(
            "cost-aware inference base_seed", inference.get("base_seed"), minimum=0
        ),
        "block_lengths": list(block_lengths),
        "bootstrap_samples": _integer(
            "cost-aware inference bootstrap_samples",
            inference.get("bootstrap_samples"),
            minimum=99,
        ),
        "definition_identity": definition.identity,
        "exact_primary_control_family_size": _integer(
            "cost-aware primary-control family size",
            inference.get("primary_control_contrast_family_size"),
            minimum=1,
        ),
        "exact_selection_family_size": _integer(
            "cost-aware selection family size",
            inference.get("selection_family_size"),
            minimum=1,
        ),
        "historical_context_adjustment_authority": inference.get(
            "historical_context_adjustment_authority"
        ),
        "holding_bars": _HOLDING_BARS,
        "monte_carlo_confidence_ppm": _integer(
            "cost-aware inference monte_carlo_confidence_ppm",
            inference.get("monte_carlo_confidence_ppm"),
            minimum=1,
        ),
        "original_family_end_global_exposure_count": _integer(
            "cost-aware original family end exposure count",
            inference.get("original_family_end_global_exposure_count"),
            minimum=0,
        ),
        "spread_limit_milli": _SPREAD_LIMIT_MILLI,
        "spread_reference_bars": _SPREAD_REFERENCE_BARS,
        "spread_reference_min_periods": _SPREAD_REFERENCE_MIN_PERIODS,
        "trace_implementation_sha256": (
            cost_aware_execution_trace_implementation_sha256()
        ),
    }
    if (
        value["exact_primary_control_family_size"] != 1
        or value["exact_selection_family_size"] != 2
        or value["historical_context_adjustment_authority"]
        != "context_only_never_adjustment_factor"
    ):
        raise ScientificTraceError("cost-aware inference boundary drifted")
    canonical_bytes(value)
    return value


def _selection_plan(
    *,
    family_id: str,
    hypothesis_ids: Sequence[str],
    registration_ids: Mapping[str, str],
    parameters: Mapping[str, Any],
) -> SelectionFamilyPlan:
    ordered = tuple(sorted(hypothesis_ids))
    return SelectionFamilyPlan(
        family_id=family_id,
        stage="discovery",
        hypotheses=tuple(
            SelectionHypothesis(
                hypothesis_id=hypothesis_id,
                registration_id=registration_ids[hypothesis_id],
            )
            for hypothesis_id in ordered
        ),
        alpha_ppm=int(parameters["alpha_ppm"]),
        bootstrap_samples=int(parameters["bootstrap_samples"]),
        block_lengths=tuple(int(item) for item in parameters["block_lengths"]),
        monte_carlo_confidence_ppm=int(
            parameters["monte_carlo_confidence_ppm"]
        ),
        base_seed=int(parameters["base_seed"]),
    )


def _profit_factor(values: Sequence[int]) -> int:
    gain = sum(value for value in values if value > 0)
    loss = -sum(value for value in values if value < 0)
    if loss <= 0:
        return 1_000_000 if gain > 0 else 0
    return min(1_000_000, int(round(1_000 * gain / loss)))


def _monthly_drawdown(
    trades: Sequence[Mapping[str, Any]],
) -> tuple[int, int]:
    by_month: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for trade in sorted(
        trades,
        key=lambda item: (str(item["exit_time"]), str(item["observation_id"])),
    ):
        by_month[str(trade["exit_time"])[:7]].append(trade)
    worst = 0
    worst_share = 0
    for values in by_month.values():
        equity = 0
        peak = 0
        drawdown = 0
        gross_profit = 0
        for trade in values:
            pnl = int(trade["native_net_pnl_micropoints"])
            equity += pnl
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
            gross_profit += max(0, pnl)
        share = (
            0
            if drawdown <= 0
            else 1_000_000_000
            if gross_profit <= 0
            else min(1_000_000_000, ceil(1_000_000 * drawdown / gross_profit))
        )
        worst = max(worst, drawdown)
        worst_share = max(worst_share, share)
    return worst, worst_share


def _flat_subject_metrics(
    *,
    subject_id: str,
    pair: Mapping[str, Any],
    definition: CostAwareExecutionProtocolDefinition,
    selection_pvalue: int,
    control_pvalue: int,
) -> tuple[dict[str, int], bool]:
    trades = [
        item
        for item in pair["trade_observations"]
        if item["executable_id"] == subject_id
    ]
    daily_rows = [
        item
        for item in pair["eligible_day_observations"]
        if item["executable_id"] == subject_id
    ]
    if not daily_rows:
        raise ScientificTraceError("cost-aware subject has no eligible-day rows")
    daily_values = [int(item["native_net_pnl_micropoints"]) for item in daily_rows]
    daily_entries = np.asarray(
        [int(item["entry_count"]) for item in daily_rows], dtype=np.int64
    )
    positive_days = sorted((value for value in daily_values if value > 0), reverse=True)
    gross_positive = sum(positive_days)
    top5_share = (
        0
        if gross_positive <= 0
        else min(
            1_000_000,
            int(round(1_000_000 * sum(positive_days[:5]) / gross_positive)),
        )
    )
    fold_ids = tuple(str(item["fold_id"]) for item in pair["windows"])
    fold_values = {
        fold_id: [
            int(item["native_net_pnl_micropoints"])
            for item in trades
            if item["fold_id"] == fold_id
        ]
        for fold_id in fold_ids
    }
    fold_profit_factors = sorted(_profit_factor(values) for values in fold_values.values())
    regime_values: dict[str, dict[str, list[int]]] = {
        regime: {fold_id: [] for fold_id in fold_ids}
        for regime in sorted(_ALLOWED_REGIMES)
    }
    for trade in trades:
        regime_values[str(trade["regime"])][str(trade["fold_id"])].append(
            int(trade["native_net_pnl_micropoints"])
        )
    positive_regimes = 0
    supported_regimes = 0
    for by_fold in regime_values.values():
        total = sum(sum(values) for values in by_fold.values())
        trade_count = sum(len(values) for values in by_fold.values())
        evaluable_folds = sum(bool(values) for values in by_fold.values())
        winning_folds = sum(
            sum(values) > 0 for values in by_fold.values() if values
        )
        positive_regimes += total > 0
        supported_regimes += (
            total > 0
            and trade_count >= 30
            and evaluable_folds >= 5
            and winning_folds >= 3
            and 2 * winning_folds > evaluable_folds
        )
    realized_drawdown, realized_drawdown_share = _monthly_drawdown(trades)
    full_intents = [
        item
        for item in pair["intent_observations"]
        if item["executable_id"] == subject_id and item["scope"] == "full"
    ]
    unknown_cost = sum(item["status"] == "unknown_cost" for item in full_intents)
    gap_excluded = sum(item["status"] == "gap_excluded" for item in full_intents)
    causality = sum(
        item["status"] == "causality_violation" for item in full_intents
    )
    prefix_mismatches = sum(
        int(item["candidate_mismatch_count"])
        + int(item["gate_mismatch_count"])
        for item in pair["invariance_comparisons"]
    )
    append_mismatches = sum(
        int(item["intent_mismatch_count"])
        for item in pair["invariance_comparisons"]
    )
    control_id = definition.prospective_control_executable_id
    subject_net = sum(daily_values)
    control_net = sum(
        int(item["native_net_pnl_micropoints"])
        for item in pair["eligible_day_observations"]
        if item["executable_id"] == control_id
    )
    flat = {
        "append_invariance_mismatch_count": append_mismatches,
        "causality_violation_count": causality,
        "daily_entries_max_milli": int(daily_entries.max(initial=0)) * 1_000,
        "daily_entries_median_milli": int(
            round(1_000 * float(np.median(daily_entries)))
        ),
        "daily_entries_p10_milli": int(
            round(
                1_000
                * float(np.quantile(daily_entries, 0.10, method="lower"))
            )
        ),
        "daily_entries_p90_milli": int(
            round(
                1_000
                * float(np.quantile(daily_entries, 0.90, method="higher"))
            )
        ),
        "eligible_day_count": len(daily_rows),
        "entries_per_day_milli": int(
            round(1_000 * len(trades) / len(daily_rows))
        ),
        "evaluable_folds": sum(bool(values) for values in fold_values.values()),
        "execution_control_delta_net_profit_micropoints": (
            subject_net - control_net
        ),
        "execution_control_pvalue_upper_ppm": control_pvalue,
        "gap_excluded_signal_count": gap_excluded,
        "median_fold_profit_factor_milli": fold_profit_factors[
            len(fold_profit_factors) // 2
        ],
        "monthly_realized_exit_drawdown_micropoints": realized_drawdown,
        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": (
            realized_drawdown_share
        ),
        "net_profit_micropoints": subject_net,
        "nonfinite_metric_count": 0,
        "positive_regime_count": int(positive_regimes),
        "prefix_invariance_mismatch_count": prefix_mismatches,
        "selection_aware_pvalue_ppm": selection_pvalue,
        "stress_net_profit_micropoints": sum(
            int(item["stress_net_pnl_micropoints"]) for item in trades
        ),
        "supported_positive_regime_count": int(supported_regimes),
        "top5_profit_day_share_ppm": top5_share,
        "trade_count": len(trades),
        "unknown_cost_unresolved_signal_count": unknown_cost,
        "winning_fold_count": sum(
            sum(values) > 0 for values in fold_values.values() if values
        ),
        "zero_entry_day_rate_ppm": int(
            round(1_000_000 * int((daily_entries == 0).sum()) / len(daily_entries))
        ),
    }
    evaluable = all(
        flat[name] == 0
        for name in (
            "append_invariance_mismatch_count",
            "causality_violation_count",
            "nonfinite_metric_count",
            "prefix_invariance_mismatch_count",
            "unknown_cost_unresolved_signal_count",
        )
    )
    return flat, evaluable


def _derive_metrics_and_statistics(
    *,
    trace: Mapping[str, Any],
    definition: CostAwareExecutionProtocolDefinition,
    parameters: Mapping[str, Any],
) -> tuple[dict[str, dict[str, int | None]], dict[str, object]]:
    if dict(parameters) != _calculation_parameters(definition):
        raise ScientificTraceError("cost-aware calculation parameters drifted")
    subject_trace, pair = _open_subject_trace(trace, definition=definition)
    subject_id = str(subject_trace["subject_executable_id"])
    daily: dict[str, dict[str, int]] = {
        executable_id: {}
        for executable_id in definition.prospective_executable_ids
    }
    for row in pair["eligible_day_observations"]:
        daily[str(row["executable_id"])][str(row["date"])] = int(
            row["native_net_pnl_micropoints"]
        )
    if any(tuple(values) != tuple(next(iter(daily.values()))) for values in daily.values()):
        raise ScientificTraceError("cost-aware family calendars differ")
    current_context = _mapping(
        "cost-aware current historical context", pair["historical_context"]
    )
    historical_context = HistoricalSearchContext(
        context_id=str(current_context["context_id"]),
        prior_global_exposure_count=int(
            current_context["prior_global_exposure_count"]
        ),
    )
    families = cost_aware_execution_subject_inference_families(
        definition, subject_id
    )
    family_by_criterion = {str(item["criterion_id"]): item for item in families}
    selection_family = family_by_criterion["E01-familywise-selection"]
    control_family = family_by_criterion["D04-primary-control-uncertainty"]
    family_registration_ids = {
        item.prospective_executable_id: (
            "historical-reference:" + item.historical_executable_id
        )
        for item in definition.member_bindings
    }
    selection_result = infer_concurrent_selection_family(
        plan=_selection_plan(
            family_id=str(selection_family["family_id"]),
            hypothesis_ids=definition.prospective_executable_ids,
            registration_ids=family_registration_ids,
            parameters=parameters,
        ),
        daily_pnl_by_hypothesis=daily,
        historical_context=historical_context,
    )
    control_id = definition.prospective_control_executable_id
    target_id = definition.prospective_target_executable_id
    contrast_id = str(control_family["member_id"])
    contrast_daily = {
        day: daily[target_id][day] - daily[control_id][day]
        for day in daily[target_id]
    }
    control_result = infer_concurrent_selection_family(
        plan=_selection_plan(
            family_id=str(control_family["family_id"]),
            hypothesis_ids=(contrast_id,),
            registration_ids={
                contrast_id: "protocol-contrast:" + definition.identity
            },
            parameters=parameters,
        ),
        daily_pnl_by_hypothesis={contrast_id: contrast_daily},
        historical_context=historical_context,
    )
    subject_selection = selection_result.hypothesis(subject_id)
    subject_control = control_result.hypothesis(contrast_id)
    flat, evaluable = _flat_subject_metrics(
        subject_id=subject_id,
        pair=pair,
        definition=definition,
        selection_pvalue=(
            subject_selection.synchronized_max_monte_carlo_upper_pvalue_ppm
        ),
        control_pvalue=(
            subject_control.synchronized_max_monte_carlo_upper_pvalue_ppm
        ),
    )
    all_claim_metrics = claim_metrics(
        {"evaluable": evaluable, "metrics": flat},
        control_delta_metric=COST_AWARE_EXECUTION_CONTROL_DELTA_METRIC,
        control_pvalue_metric=COST_AWARE_EXECUTION_CONTROL_PVALUE_METRIC,
        include_opposite_sign=False,
    )
    if set(all_claim_metrics) != set(COST_AWARE_EXECUTION_REPLAY_CLAIMS):
        raise RuntimeError("cost-aware claim metric inventory drifted")
    criterion_metrics_by_claim: dict[str, tuple[str, ...]] = {
        claim_id: tuple(
            str(item["metric"])
            for item in COST_AWARE_EXECUTION_REPLAY_CRITERIA
            if item["claim_id"] == claim_id
        )
        for claim_id in COST_AWARE_EXECUTION_REPLAY_CLAIMS
    }
    metrics: dict[str, dict[str, int | None]] = {}
    descriptive_diagnostics: dict[str, dict[str, int | None]] = {}
    for claim_id in COST_AWARE_EXECUTION_REPLAY_CLAIMS:
        claim_values = all_claim_metrics[claim_id]
        criterion_names = criterion_metrics_by_claim[claim_id]
        diagnostic_names = _DESCRIPTIVE_DIAGNOSTIC_METRICS.get(claim_id, ())
        if (
            len(set(criterion_names)) != len(criterion_names)
            or set(claim_values) != set(criterion_names) | set(diagnostic_names)
        ):
            raise RuntimeError(
                "cost-aware measurement/diagnostic metric boundary drifted"
            )
        metrics[claim_id] = {
            name: claim_values[name] for name in criterion_names
        }
        if diagnostic_names:
            descriptive_diagnostics[claim_id] = {
                name: claim_values[name] for name in diagnostic_names
            }
    if sum(len(values) for values in metrics.values()) != len(
        COST_AWARE_EXECUTION_REPLAY_CRITERIA
    ):
        raise RuntimeError("cost-aware exact criterion projection drifted")
    registrations = {
        str(item["criterion_id"]): item
        for item in cost_aware_execution_multiplicity_registrations(
            definition, subject_id
        )
    }

    def multiplicity_result(
        criterion_id: str,
        result: Any,
    ) -> dict[str, object]:
        registration = registrations[criterion_id]
        row = {
            **dict(registration),
            "adjusted_pvalue_ppm": (
                result.synchronized_max_monte_carlo_upper_pvalue_ppm
            ),
            "raw_pvalue_ppm": result.raw_monte_carlo_upper_pvalue_ppm,
        }
        if (
            row["method"] != "synchronized_max_moving_block_familywise.v1"
            or row["adjusted_pvalue_ppm"] < row["raw_pvalue_ppm"]
        ):
            raise ScientificTraceError(
                "cost-aware synchronized-max multiplicity result drifted"
            )
        return row

    statistics = {
        "descriptive_diagnostics": descriptive_diagnostics,
        "exposure_semantics": {
            "current_prior_global_exposure_count": (
                historical_context.prior_global_exposure_count
            ),
            "historical_context_adjustment_authority": (
                historical_context.manifest()["adjustment_authority"]
            ),
            "original_family_end_global_exposure_count": parameters[
                "original_family_end_global_exposure_count"
            ],
            "primary_control_family_size": control_result.plan.family_size,
            "selection_family_size": selection_result.plan.family_size,
        },
        "historical_context": historical_context.manifest(),
        "multiplicity_assessments": {
            "D04-primary-control-uncertainty": multiplicity_result(
                "D04-primary-control-uncertainty",
                subject_control,
            ),
            "E01-familywise-selection": multiplicity_result(
                "E01-familywise-selection",
                subject_selection,
            ),
        },
        "primary_control_family": control_result.statistical_manifest(),
        "selection_family": selection_result.statistical_manifest(),
        "subject_controls": {
            "contrast_id": contrast_id,
            "primary_control_executable_id": control_id,
            "subject_executable_id": subject_id,
        },
    }
    if (
        control_result.plan.family_size != 1
        or selection_result.plan.family_size != 2
        or tuple(selection_result.plan.hypothesis_ids)
        != tuple(sorted(definition.prospective_executable_ids))
    ):
        raise ScientificTraceError("cost-aware exact inference family drifted")
    canonical_bytes(metrics)
    canonical_bytes(statistics)
    return metrics, statistics


def build_cost_aware_execution_pair_calculation(
    *,
    trace: Mapping[str, Any],
    definition: CostAwareExecutionProtocolDefinition,
    trace_output_name: str,
    trace_hash: str,
) -> dict[str, object]:
    """Recompute one subject from reusable pair bytes and bind its trace hash."""

    subject, _ = _open_subject_trace(trace, definition=definition)
    expected_hash = sha256(canonical_bytes(subject)).hexdigest()
    if _digest("cost-aware trace hash", trace_hash) != expected_hash:
        raise ScientificTraceError("cost-aware trace hash differs from opened bytes")
    parameters = _calculation_parameters(definition)
    metrics, statistics = _derive_metrics_and_statistics(
        trace=subject,
        definition=definition,
        parameters=parameters,
    )
    value = {
        "evidence_modes": list(COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES),
        "executable_id": subject["subject_executable_id"],
        "job_hash": subject["job_hash"],
        "job_id": subject["job_id"],
        "metrics": metrics,
        "mission_id": subject["mission_id"],
        "parameters": parameters,
        "protocol_definition": definition.manifest(),
        "protocol_id": definition.protocol_id,
        "schema": SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
        "statistics": statistics,
        "trace": {
            "output_name": _ascii(
                "cost-aware trace output_name", trace_output_name
            ),
            "sha256": expected_hash,
        },
    }
    canonical_bytes(value)
    return value


def validate_cost_aware_execution_trace_calculation(
    *,
    trace: Mapping[str, Any],
    calculation: Mapping[str, Any],
    definition: CostAwareExecutionProtocolDefinition,
) -> dict[str, dict[str, int | None]]:
    """Return only metrics independently recomputed from the atomic pair trace."""

    if not isinstance(calculation, Mapping) or set(calculation) != _CALCULATION_FIELDS:
        raise ScientificTraceError("cost-aware calculation proof schema is invalid")
    if (
        calculation.get("schema") != SCIENTIFIC_CALCULATION_PROOF_SCHEMA
        or calculation.get("protocol_id") != definition.protocol_id
    ):
        raise ScientificTraceError("cost-aware calculation protocol drifted")
    parsed_definition = cost_aware_execution_protocol_definition_from_manifest(
        calculation.get("protocol_definition")
    )
    if parsed_definition.manifest() != definition.manifest():
        raise ScientificTraceError("cost-aware calculation definition drifted")
    subject, _ = _open_subject_trace(trace, definition=definition)
    if any(
        calculation.get(name) != subject.get(trace_name)
        for name, trace_name in (
            ("executable_id", "subject_executable_id"),
            ("job_hash", "job_hash"),
            ("job_id", "job_id"),
            ("mission_id", "mission_id"),
        )
    ):
        raise ScientificTraceError("cost-aware calculation belongs to another Job")
    if tuple(calculation.get("evidence_modes", ())) != (
        COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES
    ):
        raise ScientificTraceError("cost-aware calculation evidence modes drifted")
    trace_reference = _mapping(
        "cost-aware calculation trace reference", calculation.get("trace")
    )
    if set(trace_reference) != {"output_name", "sha256"}:
        raise ScientificTraceError("cost-aware calculation trace reference is invalid")
    _ascii("cost-aware trace output_name", trace_reference.get("output_name"))
    if trace_reference.get("sha256") != sha256(canonical_bytes(subject)).hexdigest():
        raise ScientificTraceError("cost-aware calculation trace hash is forged")
    parameters = _mapping(
        "cost-aware calculation parameters", calculation.get("parameters")
    )
    expected_metrics, expected_statistics = _derive_metrics_and_statistics(
        trace=subject,
        definition=definition,
        parameters=parameters,
    )
    if calculation.get("metrics") != expected_metrics:
        raise ScientificTraceError("cost-aware metrics drifted from atomic rows")
    if calculation.get("statistics") != expected_statistics:
        raise ScientificTraceError("cost-aware deterministic inference proof drifted")
    return expected_metrics


__all__ = [
    "COST_AWARE_EXECUTION_CANDIDATE_OBSERVATION_SCHEMA",
    "COST_AWARE_EXECUTION_ELIGIBLE_DAY_SCHEMA",
    "COST_AWARE_EXECUTION_INTENT_OBSERVATION_SCHEMA",
    "COST_AWARE_EXECUTION_INVARIANCE_SCHEMA",
    "COST_AWARE_EXECUTION_PAIR_TRACE_SCHEMA",
    "COST_AWARE_EXECUTION_SOURCE_OBSERVATION_SCHEMA",
    "COST_AWARE_EXECUTION_TRADE_OBSERVATION_SCHEMA",
    "bind_cost_aware_execution_subject_trace",
    "build_cost_aware_execution_pair_calculation",
    "compute_cost_aware_execution_pair_trace",
    "cost_aware_execution_trace_implementation_sha256",
    "extract_cost_aware_execution_pair_trace",
    "validate_cost_aware_execution_pair_trace",
    "validate_cost_aware_execution_subject_trace",
    "validate_cost_aware_execution_trace_calculation",
]
