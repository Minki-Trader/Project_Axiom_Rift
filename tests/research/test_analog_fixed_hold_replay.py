from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

import axiom_rift.operations.validation as validation_module
import axiom_rift.research.replay_coverage as replay_coverage_module
import axiom_rift.research.validation_v2 as validation_v2_module
from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.analog_fixed_hold_replay import (
    analog_fixed_hold_replay_configurations,
    analog_fixed_hold_replay_controlled_chassis,
    analog_fixed_hold_replay_protocol_definition,
    convert_analog_scoped_trace_to_fixed_hold,
)
from axiom_rift.research.analog_fixed_hold_replay_job import (
    RUNTIME_ADAPTER,
    build_analog_fixed_hold_replay_job_plan,
)
from axiom_rift.research.historical_analog_family_stu0061 import (
    STU0061_ANALOG_FAMILY as P1_STU0061_ANALOG_FAMILY,
)
from axiom_rift.research.analog_state_replay_v2 import (
    analog_family_trace_v2_implementation_identities,
    expected_analog_family_inventory_scoped_v2,
)
from axiom_rift.research.analog_state_trace import (
    ANALOG_FAMILY_TRACE_SCHEMA,
    ANALOG_REPLAY_CONTROLS,
    ANALOG_REPLAY_TRACE_ATTRIBUTION,
    analog_family_execution_contracts,
    analog_observation_id,
    analog_original_family_provenance,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    EXPECTED_FOLD_IDS,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_REPLAY_CRITERIA,
    FIXED_HOLD_REPLAY_EVIDENCE_MODES,
    FIXED_HOLD_TRACE_VALIDATOR,
    bind_fixed_hold_family_trace,
    build_fixed_hold_trace_calculation,
    fixed_hold_calculation_parameters,
    fixed_hold_observation_id,
    fixed_hold_subject_inference_families,
    validate_fixed_hold_family_trace,
)
from axiom_rift.research.fixed_hold_replay_runtime import (
    fixed_hold_replay_job_implementation_artifact,
    fixed_hold_replay_job_implementation_sha256,
    fixed_hold_replay_runtime_dependency_paths,
)
from axiom_rift.research.fixed_hold_shared_trace import (
    build_fixed_hold_shared_trace_calculation,
    validate_fixed_hold_shared_trace_pair,
)
from axiom_rift.research.historical_family_stu0061 import (
    STU0061_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
    historical_family_from_manifest,
)
from axiom_rift.research.scientific_trace import (
    ANALOG_FIXED_HOLD_REPLAY_TRACE_PROTOCOL_ID,
    DRAWDOWN_REPLAY_TRACE_PROTOCOL_ID,
    ScientificTraceError,
    validate_trace_calculation_pair,
)


CONTEXT = 622
ORIGINAL_FAMILY_END = 492
EXPECTED_REFERENCES = (
    "executable:80e19339aa1562ab73a1922c1e595163d3d38963c955f46d9c8700b0830af463",
    "executable:050d071fae20cef41beecd5caf356f645ad4c3bcc16749e2fa5179f3a511dac7",
    "executable:4fe8293577a9aa4292bca8e5170b39528b45faeec7c7fe4453851c227869e8df",
    "executable:61a3e085beb97af8ab8251125463bd3106cdebdbac511915b0434f07f14589e8",
)
FAMILY_AUTHORITY_ID = "historical-family-authority:" + "a" * 64
REPLAY_OBLIGATION_ID = "historical-replay-obligation:" + "b" * 64
TYPED_HISTORICAL_FAMILY = historical_family_from_manifest(
    STU0061_HISTORICAL_FAMILY.manifest()
)


def _replay_context() -> HistoricalFamilyReplayContext:
    return HistoricalFamilyReplayContext(
        family_authority_id=FAMILY_AUTHORITY_ID,
        replay_obligation_id=REPLAY_OBLIGATION_ID,
        family=TYPED_HISTORICAL_FAMILY,
        prior_global_exposure_count=CONTEXT,
        original_family_end_global_exposure_count=ORIGINAL_FAMILY_END,
    )


def _definition():
    return analog_fixed_hold_replay_protocol_definition(_replay_context())


def _original_family_provenance() -> dict[str, object]:
    return analog_original_family_provenance(
        P1_STU0061_ANALOG_FAMILY,
        context_id=FAMILY_AUTHORITY_ID,
        end_global_exposure_count=ORIGINAL_FAMILY_END,
    )


def test_stu0061_historical_family_preserves_exact_order_and_controls() -> None:
    family = TYPED_HISTORICAL_FAMILY
    assert family.original_study_id == "STU-0061"
    assert family.original_batch_id == (
        "batch:90a31a1906e681d0758a26aec0c21815481c3cfb31c8be5400ef02bff5902123"
    )
    assert tuple(
        member.historical_reference_executable_id for member in family.members
    ) == EXPECTED_REFERENCES
    assert family.target_historical_executable_id == EXPECTED_REFERENCES[-1]
    configurations = analog_fixed_hold_replay_configurations(family)
    assert tuple(
        configuration.configuration_id for configuration in configurations
    ) == tuple(member.configuration_id for member in family.members)

    by_reference = {
        configuration.historical_reference_executable_id: configuration
        for configuration in configurations
    }
    for control in family.controls:
        subject = by_reference[control.subject_historical_executable_id]
        opposite = by_reference[control.opposite_historical_executable_id]
        assert opposite.profile_id == subject.profile_id
        assert opposite.signal_sign == -subject.signal_sign
        assert len(control.feature_historical_executable_ids) == 1
        feature = by_reference[control.feature_historical_executable_ids[0]]
        assert feature.profile_id != subject.profile_id
        assert feature.signal_sign == subject.signal_sign
        reverse = family.control_for_historical_executable(
            opposite.historical_reference_executable_id
        )
        assert (
            reverse.opposite_historical_executable_id
            == subject.historical_reference_executable_id
        )


def test_definition_uses_four_member_e01_and_exact_opposite_d02() -> None:
    definition = _definition()
    assert definition.family == TYPED_HISTORICAL_FAMILY
    assert definition.historical_context_id == FAMILY_AUTHORITY_ID
    assert definition.family.family_size == 4
    assert len(definition.prospective_executable_ids) == 4
    parameters = fixed_hold_calculation_parameters(
        definition,
        FIXED_HOLD_TRACE_VALIDATOR,
    )
    assert parameters["exact_concurrent_family_adjustment_factor"] == 4
    assert definition.protocol_id == ANALOG_FIXED_HOLD_REPLAY_TRACE_PROTOCOL_ID

    historical_to_prospective = dict(
        zip(
            EXPECTED_REFERENCES,
            definition.prospective_executable_ids,
            strict=True,
        )
    )
    for subject_historical in EXPECTED_REFERENCES:
        subject = historical_to_prospective[subject_historical]
        controls = TYPED_HISTORICAL_FAMILY.control_for_historical_executable(
            subject_historical
        )
        families = fixed_hold_subject_inference_families(definition, subject)
        assert set(families["selection_family"]["ordered_member_ids"]) == set(
            definition.prospective_executable_ids
        )
        assert families["paired_control_family"]["member_id"] == (
            "paired-control:opposite:"
            + historical_to_prospective[
                controls.opposite_historical_executable_id
            ]
        )
        assert len(families["paired_control_family"]["feature_member_ids"]) == 1


def _windows() -> tuple[list[dict[str, object]], list[str]]:
    windows: list[dict[str, object]] = []
    dates: list[str] = []
    origin = datetime(2024, 2, 1, 9)
    for index, fold_id in enumerate(EXPECTED_FOLD_IDS):
        test_start = origin + timedelta(days=10 * index)
        eligible = [
            (test_start + timedelta(days=offset)).date().isoformat()
            for offset in range(4)
        ]
        dates.extend(eligible)
        windows.append(
            {
                "eligible_dates": eligible,
                "fold_id": fold_id,
                "test_end": (test_start + timedelta(days=3, hours=14, minutes=55)).isoformat(),
                "test_start": test_start.isoformat(),
                "train_end": (test_start - timedelta(minutes=5)).isoformat(),
                "train_start": (test_start - timedelta(days=5)).isoformat(),
            }
        )
    return windows, dates


def _source_trace() -> tuple[dict[str, object], tuple[datetime, ...]]:
    inventory = expected_analog_family_inventory_scoped_v2(
        P1_STU0061_ANALOG_FAMILY
    )
    windows, _ = _windows()
    first = inventory[0]
    executed_times = tuple(
        datetime(2024, 2, 1, 9) + timedelta(minutes=5 * index)
        for index in range(26)
    )
    gap_values: list[datetime] = []
    current = datetime(2024, 2, 2, 9)
    for index in range(26):
        gap_values.append(current)
        current += timedelta(minutes=65 if index == 10 else 5)
    frame_times = (*executed_times, *gap_values)

    trade = {
        "availability_time": executed_times[1].isoformat(),
        "configuration_id": first["configuration_id"],
        "decision_bar_index": 0,
        "decision_bar_open_time": executed_times[0].isoformat(),
        "decision_spread_source_bar_index": 0,
        "decision_spread_source_bar_open_time": executed_times[0].isoformat(),
        "decision_spread_information_complete_at": executed_times[1].isoformat(),
        "decision_spread_known": True,
        "decision_time": executed_times[1].isoformat(),
        "direction": 1,
        "entry_bar_index": 1,
        "entry_spread_source_bar_index": 0,
        "entry_spread_source_bar_open_time": executed_times[0].isoformat(),
        "entry_spread_information_complete_at": executed_times[1].isoformat(),
        "entry_spread_known": True,
        "entry_time": executed_times[1].isoformat(),
        "executable_id": first["executable_id"],
        "exit_bar_index": 25,
        "exit_spread_source_bar_index": 24,
        "exit_spread_source_bar_open_time": executed_times[24].isoformat(),
        "exit_spread_information_complete_at": executed_times[25].isoformat(),
        "exit_spread_known": True,
        "exit_time": executed_times[25].isoformat(),
        "fold_id": EXPECTED_FOLD_IDS[0],
        "gross_pnl_micropoints": 1_000,
        "historical_reference_executable_id": first[
            "historical_reference_executable_id"
        ],
        "native_cost_micropoints": 100,
        "native_net_pnl_micropoints": 900,
        "observation_id": "pending",
        "regime": "low",
        "stress_cost_micropoints": 200,
        "stress_net_pnl_micropoints": 800,
        "spread_semantics": "completed_period_proxy",
    }
    trade["observation_id"] = analog_observation_id("trade", trade)

    intents: list[dict[str, object]] = []
    for scope in ("full", "prefix"):
        for ordinal, status, times in (
            (1, "executed", executed_times),
            (2, "gap_excluded", tuple(gap_values)),
        ):
            decision_index = 0 if status == "executed" else 26
            entry_index = decision_index + 1
            exit_index = entry_index + 24
            intent = {
                "availability_time": times[1].isoformat(),
                "configuration_id": first["configuration_id"],
                "decision_bar_index": decision_index,
                "decision_bar_open_time": times[0].isoformat(),
                "decision_spread_source_bar_index": decision_index,
                "decision_spread_source_bar_open_time": times[0].isoformat(),
                "decision_spread_information_complete_at": times[1].isoformat(),
                "decision_spread_known": True,
                "decision_time": times[1].isoformat(),
                "direction": 1,
                "entry_bar_index": entry_index,
                "entry_spread_source_bar_index": decision_index,
                "entry_spread_source_bar_open_time": times[0].isoformat(),
                "entry_spread_information_complete_at": times[1].isoformat(),
                "entry_spread_known": True,
                "entry_time": times[1].isoformat(),
                "executable_id": first["executable_id"],
                "exit_bar_index": exit_index,
                "exit_spread_source_bar_index": exit_index - 1,
                "exit_spread_source_bar_open_time": times[24].isoformat(),
                "exit_spread_information_complete_at": times[25].isoformat(),
                "exit_spread_known": True if status == "executed" else None,
                "exit_time": times[25].isoformat(),
                "fold_id": EXPECTED_FOLD_IDS[0],
                "historical_reference_executable_id": first[
                    "historical_reference_executable_id"
                ],
                "observation_id": "pending",
                "ordinal": ordinal,
                "scope": scope,
                "spread_semantics": "completed_period_proxy",
                "status": status,
            }
            intent["observation_id"] = analog_observation_id("intent", intent)
            intents.append(intent)
    intents.sort(
        key=lambda item: (
            str(item["configuration_id"]),
            str(item["fold_id"]),
            str(item["scope"]),
            int(item["ordinal"]),
            str(item["observation_id"]),
        )
    )

    eligible: list[dict[str, object]] = []
    for member in inventory:
        for window in windows:
            for day in window["eligible_dates"]:
                is_trade_day = (
                    member["configuration_id"] == first["configuration_id"]
                    and window["fold_id"] == EXPECTED_FOLD_IDS[0]
                    and day == "2024-02-01"
                )
                eligible.append(
                    {
                        "configuration_id": member["configuration_id"],
                        "date": day,
                        "entry_count": 1 if is_trade_day else 0,
                        "executable_id": member["executable_id"],
                        "fold_id": window["fold_id"],
                        "native_net_pnl_micropoints": 900 if is_trade_day else 0,
                        "stress_net_pnl_micropoints": 800 if is_trade_day else 0,
                    }
                )
    digest = "1" * 64
    comparisons = [
        {
            "compared_row_count": 100,
            "fold_id": window["fold_id"],
            "full_score_values_sha256": digest,
            "prefix_score_values_sha256": digest,
            "profile_id": profile.profile_id,
        }
        for window in windows
        for profile in P1_STU0061_ANALOG_FAMILY.profiles
    ]
    contracts = analog_family_execution_contracts(P1_STU0061_ANALOG_FAMILY)
    return (
        {
            "attribution": ANALOG_REPLAY_TRACE_ATTRIBUTION,
            "clock_contract": contracts["clock_contract"],
            "controls": ANALOG_REPLAY_CONTROLS,
            "cost_contract": contracts["cost_contract"],
            "dataset_sha256": DATASET_SHA256,
            "eligible_day_observations": eligible,
            "family_id": P1_STU0061_ANALOG_FAMILY.family_id,
            "implementation_identities": (
                analog_family_trace_v2_implementation_identities()
            ),
            "intent_observations": intents,
            "invariance_comparisons": comparisons,
            "material_identity": OBSERVED_MATERIAL_ID,
            "ordered_family": list(inventory),
            "original_family_provenance": _original_family_provenance(),
            "protocol_id": "analog_state.concurrent_four_config.v1",
            "schema": ANALOG_FAMILY_TRACE_SCHEMA,
            "split_artifact_sha256": ROLLING_SPLIT_SHA256,
            "trade_observations": [trade],
            "windows": windows,
        },
        frame_times,
    )


def test_scoped_v2_conversion_enforces_exact_fixed_hold_clocks() -> None:
    source, frame_times = _source_trace()
    definition = _definition()
    converted = convert_analog_scoped_trace_to_fixed_hold(
        source,
        definition=definition,
        observed_frame_times=frame_times,
    )
    validated = validate_fixed_hold_family_trace(
        converted,
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
    )
    assert [
        (
            item["full_feature_values_sha256"],
            item["prefix_feature_values_sha256"],
        )
        for item in validated["invariance_comparisons"]
    ] == [
        (
            item["full_score_values_sha256"],
            item["prefix_score_values_sha256"],
        )
        for item in source["invariance_comparisons"]
    ]
    trade = validated["trade_observations"][0]
    assert trade["decision_bar_index"] == 0
    assert trade["entry_bar_index"] == 1
    assert trade["exit_bar_index"] == 25
    assert trade["holding_bars"] == 24
    assert trade["observation_id"] == fixed_hold_observation_id("trade", trade)
    gap = next(
        item
        for item in validated["intent_observations"]
        if item["scope"] == "full" and item["status"] == "gap_excluded"
    )
    assert gap["exit_bar_index"] - gap["entry_bar_index"] == 24
    assert datetime.fromisoformat(str(gap["exit_time"])) != (
        datetime.fromisoformat(str(gap["entry_time"]))
        + timedelta(minutes=120)
    )


def test_conversion_rejects_an_unobserved_exit_row() -> None:
    source, frame_times = _source_trace()
    definition = _definition()
    missing_exit = tuple(
        value for value in frame_times if value != frame_times[25]
    )
    with pytest.raises(ValueError, match="trade exit is absent"):
        convert_analog_scoped_trace_to_fixed_hold(
            source,
            definition=definition,
            observed_frame_times=missing_exit,
        )


@pytest.mark.parametrize(
    ("attack", "message"),
    (("missing", "schema"), ("tampered", "provenance")),
)
def test_conversion_rejects_unbound_original_family_provenance(
    attack: str,
    message: str,
) -> None:
    source, frame_times = _source_trace()
    attacked = deepcopy(source)
    if attack == "missing":
        attacked.pop("original_family_provenance")
    else:
        attacked["original_family_provenance"] = {
            **attacked["original_family_provenance"],
            "context_id": "historical-family-authority:" + "c" * 64,
        }
    with pytest.raises(ValueError, match=message):
        convert_analog_scoped_trace_to_fixed_hold(
            attacked,
            definition=_definition(),
            observed_frame_times=frame_times,
        )


def test_controlled_chassis_and_runtime_closure_are_prospective() -> None:
    chassis = analog_fixed_hold_replay_controlled_chassis(
        historical_family=TYPED_HISTORICAL_FAMILY,
        historical_context_prior_global_exposure_count=CONTEXT,
        original_family_end_global_exposure_count=ORIGINAL_FAMILY_END,
    )
    assert chassis.baseline_executable.identity.startswith("executable:")
    paths = fixed_hold_replay_runtime_dependency_paths(RUNTIME_ADAPTER)
    assert Path(__file__).resolve() not in paths
    assert all(path.name != "writer.py" for path in paths)
    assert any(path.name == "analog_fixed_hold_replay.py" for path in paths)
    assert any(path.name == "analog_state_replay_v2.py" for path in paths)
    path_set = set(paths)
    path_names = {path.name for path in paths}
    assert {
        "adjudication.py",
        "fixed_hold_family_job.py",
        "reproducible_cache.py",
        "validation.py",
        "validation_v2.py",
    }.issubset(path_names)
    assert {
        "historical_analog_family_stu0061.py",
        "historical_family_replay.py",
        "historical_family_stu0061.py",
        "historical_family_stu0017.py",
        "historical_family_stu0032.py",
        "p0_replay_inventory.py",
        "p0_selection_inference.py",
    }.isdisjoint(path_names)
    assert Path(validation_module.__file__).resolve() in path_set
    assert Path(replay_coverage_module.__file__).resolve() in path_set


def test_runtime_implementation_binds_validator_dependency_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency = next(
        path
        for path in validation_v2_module.SCIENTIFIC_VALIDATION_V2_DEPENDENCIES
        if path.name == "adjudication.py"
    ).resolve()
    baseline_artifact = fixed_hold_replay_job_implementation_artifact(
        RUNTIME_ADAPTER
    )
    baseline_identity = fixed_hold_replay_job_implementation_sha256(
        RUNTIME_ADAPTER
    )
    original_read_bytes = Path.read_bytes

    def perturbed_read_bytes(path: Path) -> bytes:
        content = original_read_bytes(path)
        if path.resolve() == dependency:
            return content + b"\n# dependency perturbation"
        return content

    monkeypatch.setattr(Path, "read_bytes", perturbed_read_bytes)
    changed_artifact = fixed_hold_replay_job_implementation_artifact(
        RUNTIME_ADAPTER
    )
    changed_identity = fixed_hold_replay_job_implementation_sha256(
        RUNTIME_ADAPTER
    )
    assert sha256(changed_artifact).hexdigest() != sha256(
        baseline_artifact
    ).hexdigest()
    assert changed_identity != baseline_identity


def test_four_jobs_share_one_exact_family_cache_producer() -> None:
    definition = _definition()
    plans = tuple(
        build_analog_fixed_hold_replay_job_plan(
            mission_id="MIS-0006",
            study_id="STU-0112",
            executable_id=executable_id,
            historical_context_prior_global_exposure_count=CONTEXT,
            original_family_end_global_exposure_count=ORIGINAL_FAMILY_END,
            historical_family=TYPED_HISTORICAL_FAMILY,
            historical_family_authority_id=FAMILY_AUTHORITY_ID,
            replay_obligation_id=REPLAY_OBLIGATION_ID,
        )
        for executable_id in definition.prospective_executable_ids
    )
    assert [plan.produces_family_cache for plan in plans] == [
        True,
        False,
        False,
        False,
    ]
    assert len({plan.definition.identity for plan in plans}) == 1
    assert len({plan.cache_output_name for plan in plans}) == 1
    producer = plans[0]
    assert all(
        plan.producer_executable_id == producer.executable_id
        for plan in plans[1:]
    )


def test_central_dispatcher_recomputes_the_new_protocol() -> None:
    source, frame_times = _source_trace()
    definition = _definition()
    neutral = convert_analog_scoped_trace_to_fixed_hold(
        source,
        definition=definition,
        observed_frame_times=frame_times,
    )
    target = definition.prospective_executable_ids[0]
    subject = bind_fixed_hold_family_trace(
        family_trace=neutral,
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
        mission_id="MIS-0006",
        executable_id=target,
        job_id="job:stu0061-dispatch-test",
        job_hash="2" * 64,
    )
    trace_hash = sha256(canonical_bytes(subject)).hexdigest()
    calculation = build_fixed_hold_trace_calculation(
        trace=subject,
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
        trace_output_name="scientific/stu0061/evaluation-trace.json",
        trace_hash=trace_hash,
    )
    by_mode: dict[str, list[dict[str, object]]] = {
        mode: [] for mode in FIXED_HOLD_REPLAY_EVIDENCE_MODES
    }
    metrics = calculation["metrics"]
    for criterion in FIXED_HOLD_REPLAY_CRITERIA:
        claim_id = str(criterion["claim_id"])
        metric = str(criterion["metric"])
        by_mode[str(criterion["evidence_mode"])].append(
            {
                "claim_id": claim_id,
                "metric": metric,
                "value": metrics[claim_id][metric],
            }
        )
    assert validate_trace_calculation_pair(
        trace=subject,
        trace_output_name="scientific/stu0061/evaluation-trace.json",
        trace_hash=trace_hash,
        calculation=calculation,
        expected_evidence_modes=FIXED_HOLD_REPLAY_EVIDENCE_MODES,
        expected_metric_bindings_by_mode={
            mode: tuple(values) for mode, values in by_mode.items()
        },
        mission_id="MIS-0006",
        executable_id=target,
        job_id="job:stu0061-dispatch-test",
        job_hash="2" * 64,
    ) == FIXED_HOLD_REPLAY_EVIDENCE_MODES


def test_dispatcher_rejects_missing_tampered_and_cross_protocol_definitions(
) -> None:
    source, frame_times = _source_trace()
    definition = _definition()
    neutral = convert_analog_scoped_trace_to_fixed_hold(
        source,
        definition=definition,
        observed_frame_times=frame_times,
    )
    target = definition.prospective_executable_ids[0]
    subject = bind_fixed_hold_family_trace(
        family_trace=neutral,
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
        mission_id="MIS-0006",
        executable_id=target,
        job_id="job:stu0061-definition-attack-test",
        job_hash="4" * 64,
    )
    trace_hash = sha256(canonical_bytes(subject)).hexdigest()
    calculation = build_fixed_hold_trace_calculation(
        trace=subject,
        definition=definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
        trace_output_name="scientific/stu0061/definition-attack-trace.json",
        trace_hash=trace_hash,
    )
    by_mode: dict[str, list[dict[str, object]]] = {
        mode: [] for mode in FIXED_HOLD_REPLAY_EVIDENCE_MODES
    }
    for criterion in FIXED_HOLD_REPLAY_CRITERIA:
        claim_id = str(criterion["claim_id"])
        metric = str(criterion["metric"])
        by_mode[str(criterion["evidence_mode"])].append(
            {
                "claim_id": claim_id,
                "metric": metric,
                "value": calculation["metrics"][claim_id][metric],
            }
        )

    def validate(attacked: dict[str, object]) -> None:
        validate_trace_calculation_pair(
            trace=subject,
            trace_output_name=(
                "scientific/stu0061/definition-attack-trace.json"
            ),
            trace_hash=trace_hash,
            calculation=attacked,
            expected_evidence_modes=FIXED_HOLD_REPLAY_EVIDENCE_MODES,
            expected_metric_bindings_by_mode={
                mode: tuple(values) for mode, values in by_mode.items()
            },
            mission_id="MIS-0006",
            executable_id=target,
            job_id="job:stu0061-definition-attack-test",
            job_hash="4" * 64,
        )

    missing = deepcopy(calculation)
    missing.pop("protocol_definition")
    with pytest.raises(ScientificTraceError, match="schema"):
        validate(missing)

    tampered = deepcopy(calculation)
    tampered["protocol_definition"]["historical_family"][
        "target_historical_executable_id"
    ] = EXPECTED_REFERENCES[0]
    with pytest.raises(ScientificTraceError, match="definition"):
        validate(tampered)

    cross_protocol = deepcopy(calculation)
    cross_protocol["protocol_definition"] = replace(
        definition,
        protocol_id=DRAWDOWN_REPLAY_TRACE_PROTOCOL_ID,
    ).manifest()
    with pytest.raises(ScientificTraceError, match="differs from trace"):
        validate(cross_protocol)


def test_shared_trace_dispatcher_recomputes_the_new_protocol() -> None:
    source, frame_times = _source_trace()
    definition = _definition()
    neutral = convert_analog_scoped_trace_to_fixed_hold(
        source,
        definition=definition,
        observed_frame_times=frame_times,
    )
    target = definition.prospective_executable_ids[0]
    trace_output = "local/cache/stu0061/shared-family-trace.json"
    trace_hash = sha256(canonical_bytes(neutral)).hexdigest()
    calculation = build_fixed_hold_shared_trace_calculation(
        trace=neutral,
        definition=definition,
        mission_id="MIS-0006",
        executable_id=target,
        job_id="job:stu0061-shared-dispatch-test",
        job_hash="3" * 64,
        trace_output_name=trace_output,
        trace_hash=trace_hash,
    )
    by_mode: dict[str, list[dict[str, object]]] = {
        mode: [] for mode in FIXED_HOLD_REPLAY_EVIDENCE_MODES
    }
    metrics = calculation["metrics"]
    for criterion in FIXED_HOLD_REPLAY_CRITERIA:
        claim_id = str(criterion["claim_id"])
        metric = str(criterion["metric"])
        by_mode[str(criterion["evidence_mode"])].append(
            {
                "claim_id": claim_id,
                "metric": metric,
                "value": metrics[claim_id][metric],
            }
        )
    assert validate_fixed_hold_shared_trace_pair(
        trace=neutral,
        trace_output_name=trace_output,
        trace_hash=trace_hash,
        calculation=calculation,
        expected_evidence_modes=FIXED_HOLD_REPLAY_EVIDENCE_MODES,
        expected_metric_bindings_by_mode={
            mode: tuple(values) for mode, values in by_mode.items()
        },
        mission_id="MIS-0006",
        executable_id=target,
        job_id="job:stu0061-shared-dispatch-test",
        job_hash="3" * 64,
    ) == FIXED_HOLD_REPLAY_EVIDENCE_MODES
