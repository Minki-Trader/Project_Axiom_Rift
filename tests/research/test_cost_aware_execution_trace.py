from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256

import pytest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research import cost_aware_execution_trace as trace_module
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_REPLAY_CRITERIA,
    cost_aware_execution_protocol_definition,
)
from axiom_rift.research.cost_aware_execution_trace import (
    bind_cost_aware_execution_subject_trace,
    build_cost_aware_execution_pair_calculation,
    compute_cost_aware_execution_pair_trace,
    validate_cost_aware_execution_pair_trace,
    validate_cost_aware_execution_subject_trace,
    validate_cost_aware_execution_trace_calculation,
)
from axiom_rift.research.scientific_trace import ScientificTraceError
from axiom_rift.research.historical_family_stu0070 import (
    STU0070_HISTORICAL_FAMILY,
)
from axiom_rift.research.selection_inference import HistoricalSearchContext


_START = datetime(2026, 1, 1)
_DATASET = "a" * 64
_SPLIT = "b" * 64
_MATERIAL = "development-material:synthetic-cost-aware-trace"


def _executable(character: str) -> str:
    return "executable:" + character * 64


def _definition(control: str = "1", target: str = "2"):
    return cost_aware_execution_protocol_definition(
        historical_family=STU0070_HISTORICAL_FAMILY,
        prospective_control_executable_id=_executable(control),
        prospective_target_executable_id=_executable(target),
    )


def _index(value: datetime) -> int:
    return int((value - _START).total_seconds() // 300)


def _time(index: int) -> datetime:
    return _START + timedelta(minutes=5 * index)


def _windows() -> list[dict[str, object]]:
    eligible = [
        (datetime(2026, 1, 2) + timedelta(days=offset)).date().isoformat()
        for offset in range(30)
    ]
    return [
        {
            "eligible_dates": eligible,
            "fold_id": "fold-01",
            "test_end": datetime(2026, 2, 2).isoformat(timespec="seconds"),
            "test_start": datetime(2026, 1, 2).isoformat(timespec="seconds"),
        }
    ]


def _candidate_rows(
    decisions: list[int],
    *,
    time_for=_time,
    decision_time_overrides: dict[int, datetime] | None = None,
) -> list[dict[str, object]]:
    overrides = decision_time_overrides or {}
    rows: list[dict[str, object]] = []
    for scope in ("full", "prefix"):
        for ordinal, decision in enumerate(decisions, start=1):
            rows.append(
                {
                    "decision_bar_index": decision,
                    "decision_time": overrides.get(
                        decision, time_for(decision) + timedelta(minutes=5)
                    ).isoformat(timespec="seconds"),
                    "direction": 1,
                    "fold_id": "fold-01",
                    "ordinal": ordinal,
                    "regime": ("low", "middle", "high")[ordinal % 3],
                    "scope": scope,
                }
            )
    return rows


def _bounded_sources(
    decisions: list[int],
    *,
    time_for=_time,
    spread_overrides: dict[int, int] | None = None,
    open_overrides: dict[int, int] | None = None,
) -> list[dict[str, object]]:
    required: set[int] = set()
    for decision in decisions:
        start = max(0, decision - 576)
        required.update(range(max(0, start - 1), decision + 49 + 1))
    spreads = spread_overrides or {}
    opens = open_overrides or {}
    return [
        {
            "bar_index": index,
            "bar_open_time": time_for(index).isoformat(timespec="seconds"),
            "open_micropoints": opens.get(index, 100_000_000 + index * 1_000),
            "raw_spread_millipoints": spreads.get(index, 1_000),
        }
        for index in sorted(required)
    ]


def _context(count: int = 700) -> HistoricalSearchContext:
    return HistoricalSearchContext(
        context_id="historical-family-authority:synthetic-stu0070",
        prior_global_exposure_count=count,
    )


def _compute(
    definition,
    sources: list[dict[str, object]],
    candidates: list[dict[str, object]],
    *,
    context_count: int = 700,
    windows: list[dict[str, object]] | None = None,
):
    return compute_cost_aware_execution_pair_trace(
        definition=definition,
        dataset_sha256=_DATASET,
        split_artifact_sha256=_SPLIT,
        material_identity=_MATERIAL,
        windows=_windows() if windows is None else windows,
        source_observations=sources,
        candidate_observations=candidates,
        historical_context=_context(context_count),
    )


@pytest.fixture(scope="module")
def base_bundle():
    definition = _definition()
    decisions = [
        _index(datetime(2026, 1, 4, 12)),
        _index(datetime(2026, 1, 31, 22)),
    ]
    first, last = decisions
    last_entry = 100_000_000 + (last + 1) * 1_000
    sources = _bounded_sources(
        decisions,
        spread_overrides={first: 2_000},
        open_overrides={last + 49: last_entry - 30_000},
    )
    candidates = _candidate_rows(decisions)
    pair = _compute(definition, sources, candidates)
    subjects = {}
    calculations = {}
    for executable_id in definition.prospective_executable_ids:
        subject = bind_cost_aware_execution_subject_trace(
            pair_trace=pair,
            definition=definition,
            mission_id="MIS-SYNTHETIC",
            executable_id=executable_id,
            job_id="JOB-" + executable_id[-4:],
            job_hash=("c" if executable_id == definition.prospective_control_executable_id else "d")
            * 64,
        )
        trace_hash = sha256(canonical_bytes(subject)).hexdigest()
        calculation = build_cost_aware_execution_pair_calculation(
            trace=subject,
            definition=definition,
            trace_output_name="scientific/cost-aware-trace.json",
            trace_hash=trace_hash,
        )
        subjects[executable_id] = subject
        calculations[executable_id] = calculation
    return {
        "candidates": candidates,
        "calculations": calculations,
        "decisions": decisions,
        "definition": definition,
        "pair": pair,
        "sources": sources,
        "subjects": subjects,
    }


def test_pair_roundtrip_sparse_union_zero_days_and_attribution(base_bundle) -> None:
    definition = base_bundle["definition"]
    pair = base_bundle["pair"]
    assert validate_cost_aware_execution_pair_trace(
        pair, definition=definition
    ) == pair
    assert len(pair["source_observations"]) == len(base_bundle["sources"]) - 2
    assert len(pair["eligible_day_observations"]) == 60
    assert any(
        row["entry_count"] == 0 for row in pair["eligible_day_observations"]
    )

    target_id = definition.prospective_target_executable_id
    target_trades = [
        row for row in pair["trade_observations"] if row["executable_id"] == target_id
    ]
    assert len(target_trades) == 1
    trade = target_trades[0]
    assert trade["decision_time"].startswith("2026-01-31")
    assert trade["exit_time"].startswith("2026-02-01")
    jan31 = next(
        row
        for row in pair["eligible_day_observations"]
        if row["executable_id"] == target_id and row["date"] == "2026-01-31"
    )
    assert jan31["native_net_pnl_micropoints"] == trade[
        "native_net_pnl_micropoints"
    ]
    calculation = base_bundle["calculations"][target_id]
    metrics = validate_cost_aware_execution_trace_calculation(
        trace=base_bundle["subjects"][target_id],
        calculation=calculation,
        definition=definition,
    )
    assert metrics == calculation["metrics"]
    diagnostics = calculation["statistics"]["descriptive_diagnostics"]
    assert diagnostics["activity_and_concentration"][
        "monthly_realized_exit_drawdown_micropoints"
    ] == -trade["native_net_pnl_micropoints"]
    assert metrics["after_cost_fixed_lot_economics"][
        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm"
    ] == 1_000_000_000
    expected_by_claim = {
        claim_id: {
            item["metric"]
            for item in COST_AWARE_EXECUTION_REPLAY_CRITERIA
            if item["claim_id"] == claim_id
        }
        for claim_id in metrics
    }
    assert {
        claim_id: set(values) for claim_id, values in metrics.items()
    } == expected_by_claim
    assert sum(len(values) for values in metrics.values()) == 18
    assert sum(len(values) for values in diagnostics.values()) == 9


def test_strict_prior_gap_reset_no_read_masks_and_independent_occupancy() -> None:
    definition = _definition()
    gap = _index(datetime(2026, 1, 10, 12))

    def time_for(index: int) -> datetime:
        return _time(index) + (timedelta(minutes=30) if index >= gap else timedelta())

    decisions = [gap - 1, gap, gap + 24, gap + 25, gap + 80, gap + 140]
    sources = _bounded_sources(
        decisions,
        time_for=time_for,
        spread_overrides={
            gap: 0,
            gap + 25: 0,
            gap + 26: 9_000,
            gap + 80: 2_000,
        },
    )
    candidates = _candidate_rows(
        decisions,
        time_for=time_for,
        decision_time_overrides={gap + 140: time_for(gap + 140) + timedelta(minutes=10)},
    )
    pair = _compute(definition, sources, candidates)
    target = {
        int(row["ordinal"]): row
        for row in pair["intent_observations"]
        if row["executable_id"] == definition.prospective_target_executable_id
        and row["scope"] == "full"
    }
    control = {
        int(row["ordinal"]): row
        for row in pair["intent_observations"]
        if row["executable_id"] == definition.prospective_control_executable_id
        and row["scope"] == "full"
    }
    assert [target[index]["status"] for index in sorted(target)] == [
        "gap_excluded",
        "entry_cancelled_unknown_gate",
        "entry_cancelled_unknown_gate",
        "executed",
        "spread_abstained",
        "causality_violation",
    ]
    assert sorted(control) == [1, 2, 5, 6]
    assert control[2]["status"] == "unknown_cost"
    assert control[2]["entry_spread_known"] is False
    assert control[2]["exit_spread_known"] is True

    assert target[3]["gate_reference_observation_count"] == 23
    assert target[3]["gate_reference_known"] is False
    assert target[4]["gate_reference_observation_count"] == 24
    assert target[4]["gate_spread_millipoints"] == 1_000
    assert target[4]["gate_reference_millipoints"] == 1_000
    assert target[4]["entry_spread_millipoints"] == 1_000
    assert target[4]["status"] == "executed"

    for ordinal in (1, 6):
        row = target[ordinal]
        assert row["predicate_evaluated"] is False
        assert row["gate_spread_known"] is None
        assert row["entry_spread_known"] is None
        assert row["exit_spread_known"] is None
    assert target[2]["predicate_evaluated"] is True
    assert target[2]["entry_spread_known"] is False
    assert target[2]["exit_spread_known"] is None
    assert target[5]["gate_spread_known"] is True
    assert target[5]["gate_reference_known"] is True
    assert target[5]["exit_spread_known"] is None

    forged = deepcopy(pair)
    row = next(
        item
        for item in forged["intent_observations"]
        if item["executable_id"] == definition.prospective_target_executable_id
        and item["scope"] == "full"
        and item["ordinal"] == 5
    )
    row["exit_spread_known"] = False
    row["observation_id"] = trace_module._observation_id("intent", row)
    with pytest.raises(ScientificTraceError):
        validate_cost_aware_execution_pair_trace(forged, definition=definition)


def test_decision_bar_date_owns_calendar_when_availability_crosses_gap() -> None:
    definition = _definition()
    decision = _index(datetime(2026, 1, 30, 23, 55))

    def time_for(index: int) -> datetime:
        if index <= decision:
            return _time(index)
        return _time(index) + timedelta(days=2)

    sources = _bounded_sources([decision], time_for=time_for)
    candidates = _candidate_rows([decision])
    windows = [
        {
            "eligible_dates": [
                (datetime(2026, 1, 1) + timedelta(days=offset)).date().isoformat()
                for offset in range(30)
            ],
            "fold_id": "fold-01",
            "test_end": datetime(2026, 2, 3).isoformat(timespec="seconds"),
            "test_start": datetime(2026, 1, 1).isoformat(timespec="seconds"),
        }
    ]
    pair = _compute(
        definition,
        sources,
        candidates,
        windows=windows,
    )
    assert {
        row["status"] for row in pair["intent_observations"]
    } == {"gap_excluded"}
    assert all(
        row["decision_bar_open_time"].startswith("2026-01-30")
        and row["decision_time"].startswith("2026-01-31")
        for row in pair["candidate_observations"]
    )


def test_invariance_mismatch_is_scientific_evidence_not_producer_failure(
    base_bundle,
) -> None:
    definition = base_bundle["definition"]
    candidates = deepcopy(base_bundle["candidates"])
    changed = next(
        row
        for row in candidates
        if row["scope"] == "prefix" and row["ordinal"] == 2
    )
    changed["direction"] = -1
    pair = _compute(definition, base_bundle["sources"], candidates)
    proof = pair["invariance_comparisons"][0]
    assert proof["candidate_mismatch_count"] > 0
    assert proof["gate_mismatch_count"] > 0
    assert proof["intent_mismatch_count"] > 0
    subject = bind_cost_aware_execution_subject_trace(
        pair_trace=pair,
        definition=definition,
        mission_id="MIS-SYNTHETIC",
        executable_id=definition.prospective_target_executable_id,
        job_id="JOB-MISMATCH",
        job_hash="e" * 64,
    )
    calculation = build_cost_aware_execution_pair_calculation(
        trace=subject,
        definition=definition,
        trace_output_name="scientific/mismatch-trace.json",
        trace_hash=sha256(canonical_bytes(subject)).hexdigest(),
    )
    causal = calculation["metrics"]["causal_feature_and_execution_validity"]
    assert causal["prefix_invariance_mismatch_count"] > 0
    assert causal["append_invariance_mismatch_count"] > 0
    assert all(
        value is None
        for value in calculation["metrics"]["after_cost_fixed_lot_economics"].values()
    )


def test_exact_d04_e01_and_cross_subject_common_contrast(base_bundle) -> None:
    definition = base_bundle["definition"]
    control_id = definition.prospective_control_executable_id
    target_id = definition.prospective_target_executable_id
    control = base_bundle["calculations"][control_id]
    target = base_bundle["calculations"][target_id]
    assert control["statistics"]["primary_control_family"] == target["statistics"][
        "primary_control_family"
    ]
    assert control["metrics"]["registered_control_contrast"][
        "execution_control_pvalue_upper_ppm"
    ] == target["metrics"]["registered_control_contrast"][
        "execution_control_pvalue_upper_ppm"
    ]
    for calculation in (control, target):
        assessments = calculation["statistics"]["multiplicity_assessments"]
        d04 = assessments["D04-primary-control-uncertainty"]
        e01 = assessments["E01-familywise-selection"]
        assert d04["family_size"] == 1
        assert d04["member_id"] == definition.primary_control_contrast_id
        assert e01["family_size"] == 2
        assert e01["member_id"] == calculation["executable_id"]
        assert d04["method"] == "synchronized_max_moving_block_familywise.v1"
        assert e01["method"] == "synchronized_max_moving_block_familywise.v1"
        assert d04["adjusted_pvalue_ppm"] >= d04["raw_pvalue_ppm"]
        assert e01["adjusted_pvalue_ppm"] >= e01["raw_pvalue_ppm"]


def test_identifier_and_current_history_context_do_not_adjust_pvalues(
    base_bundle,
) -> None:
    original = base_bundle["calculations"][
        base_bundle["definition"].prospective_target_executable_id
    ]
    changed_definition = _definition(control="f", target="0")
    changed_pair = _compute(
        changed_definition,
        base_bundle["sources"],
        base_bundle["candidates"],
        context_count=9_999,
    )
    changed_subject = bind_cost_aware_execution_subject_trace(
        pair_trace=changed_pair,
        definition=changed_definition,
        mission_id="MIS-SYNTHETIC",
        executable_id=changed_definition.prospective_target_executable_id,
        job_id="JOB-RELABEL",
        job_hash="f" * 64,
    )
    changed = build_cost_aware_execution_pair_calculation(
        trace=changed_subject,
        definition=changed_definition,
        trace_output_name="scientific/relabel-trace.json",
        trace_hash=sha256(canonical_bytes(changed_subject)).hexdigest(),
    )
    assert changed["metrics"]["selection_aware_signal_evidence"] == original[
        "metrics"
    ]["selection_aware_signal_evidence"]
    assert changed["metrics"]["registered_control_contrast"][
        "execution_control_pvalue_upper_ppm"
    ] == original["metrics"]["registered_control_contrast"][
        "execution_control_pvalue_upper_ppm"
    ]
    for criterion_id in (
        "D04-primary-control-uncertainty",
        "E01-familywise-selection",
    ):
        changed_assessment = changed["statistics"]["multiplicity_assessments"][
            criterion_id
        ]
        original_assessment = original["statistics"]["multiplicity_assessments"][
            criterion_id
        ]
        assert changed_assessment["raw_pvalue_ppm"] == original_assessment[
            "raw_pvalue_ppm"
        ]
        assert changed_assessment["adjusted_pvalue_ppm"] == original_assessment[
            "adjusted_pvalue_ppm"
        ]
    assert changed["statistics"]["historical_context"][
        "prior_global_exposure_count"
    ] == 9_999


def test_missing_support_zero_day_and_forged_hash_metric_stat_fail_closed(
    base_bundle,
) -> None:
    definition = base_bundle["definition"]
    missing_source = deepcopy(base_bundle["sources"])
    decision = base_bundle["decisions"][0]
    missing_source = [row for row in missing_source if row["bar_index"] != decision - 10]
    with pytest.raises(ScientificTraceError):
        _compute(definition, missing_source, base_bundle["candidates"])

    missing_day = deepcopy(base_bundle["pair"])
    del missing_day["eligible_day_observations"][0]
    with pytest.raises(ScientificTraceError):
        validate_cost_aware_execution_pair_trace(missing_day, definition=definition)

    target_id = definition.prospective_target_executable_id
    forged_subject = deepcopy(base_bundle["subjects"][target_id])
    forged_subject["attribution"]["pair_trace_binding"]["pair_trace_sha256"] = "0" * 64
    with pytest.raises(ScientificTraceError):
        validate_cost_aware_execution_subject_trace(
            forged_subject, definition=definition
        )

    forged_metric = deepcopy(base_bundle["calculations"][target_id])
    forged_metric["metrics"]["causal_feature_and_execution_validity"][
        "causality_violation_count"
    ] += 1
    with pytest.raises(ScientificTraceError):
        validate_cost_aware_execution_trace_calculation(
            trace=base_bundle["subjects"][target_id],
            calculation=forged_metric,
            definition=definition,
        )

    forged_diagnostic = deepcopy(base_bundle["calculations"][target_id])
    forged_diagnostic["statistics"]["descriptive_diagnostics"][
        "causal_feature_and_execution_validity"
    ]["gap_excluded_signal_count"] += 1
    with pytest.raises(ScientificTraceError):
        validate_cost_aware_execution_trace_calculation(
            trace=base_bundle["subjects"][target_id],
            calculation=forged_diagnostic,
            definition=definition,
        )

    forged_stat = deepcopy(base_bundle["calculations"][target_id])
    forged_stat["statistics"]["selection_family"]["plan"]["family_id"] = (
        "family:forged"
    )
    with pytest.raises(ScientificTraceError):
        validate_cost_aware_execution_trace_calculation(
            trace=base_bundle["subjects"][target_id],
            calculation=forged_stat,
            definition=definition,
        )
