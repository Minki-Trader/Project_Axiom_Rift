from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256

import pytest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.prospective_pair_trace import (
    PROSPECTIVE_PAIR_ELIGIBLE_DAY_SCHEMA,
    PROSPECTIVE_PAIR_EVIDENCE_MODES,
    PROSPECTIVE_PAIR_INTENT_SCHEMA,
    PROSPECTIVE_PAIR_INVARIANCE_SCHEMA,
    PROSPECTIVE_PAIR_TRACE_PROTOCOL_ID,
    PROSPECTIVE_PAIR_TRADE_SCHEMA,
    ProspectivePairMember,
    ProspectivePairProtocolDefinition,
    ProspectivePairWindow,
    build_prospective_pair_calculation,
    prospective_pair_observation_id,
    prospective_pair_protocol_definition_from_manifest,
)
from axiom_rift.research.scientific_trace import (
    PROTOCOL_DEFINITION_TRACE_PROTOCOL_IDS,
    SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
    SCIENTIFIC_TRACE_PROTOCOL_IDS,
    ScientificTraceError,
    normalized_trace_protocol_definition,
    validate_trace_calculation_pair,
)


MISSION_ID = "MIS-PROSPECTIVE-PAIR"
CONTROL_ID = "executable:" + "1" * 64
SUBJECT_ID = "executable:" + "2" * 64
JOB_ID = "job:" + "3" * 64
JOB_HASH = "4" * 64
OUTPUT_NAME = "scientific/STU-PAIR/subject/atomic-trace.json"


def _definition() -> ProspectivePairProtocolDefinition:
    start = datetime(2026, 1, 1)
    dates = tuple((start + timedelta(days=index)).date().isoformat() for index in range(40))
    return ProspectivePairProtocolDefinition(
        members=(
            ProspectivePairMember("unrestricted_control", CONTROL_ID, 1),
            ProspectivePairMember("registered_policy", SUBJECT_ID, 2),
        ),
        control_executable_id=CONTROL_ID,
        folds=(
            ProspectivePairWindow(
                fold_id="rw_001",
                test_start="2026-01-01T00:00:00",
                test_end="2026-02-09T23:59:00",
                eligible_dates=dates,
            ),
        ),
        allowed_regimes=("high", "low", "middle"),
        invariance_keys=("decision_append", "feature_prefix"),
        dataset_sha256="5" * 64,
        material_identity="material:prospective-pair-fixture",
        split_artifact_sha256="6" * 64,
        clock_contract="clock:completed_bar_fixture",
        cost_contract="cost:fixed_fixture",
        producer_implementation_identities=(("fixture_producer", "7" * 64),),
        historical_context_id="historical-context:fixture",
        historical_prior_global_exposure_count=579,
        alpha_ppm=100_000,
        bootstrap_samples=99,
        block_lengths=(5, 10),
        monte_carlo_confidence_ppm=990_000,
        base_seed=123_456,
    )


def _trade(
    *, executable_id: str, configuration_id: str, day: str, net: int
) -> dict[str, object]:
    decision_time = day + "T09:00:00"
    entry_time = decision_time
    exit_time = day + "T10:00:00"
    observation_id = prospective_pair_observation_id(
        executable_id=executable_id,
        fold_id="rw_001",
        slot="primary",
        decision_time=decision_time,
        entry_time=entry_time,
        exit_time=exit_time,
        direction=1,
    )
    return {
        "configuration_id": configuration_id,
        "decision_bar_index": 10,
        "decision_bar_open_time": day + "T08:55:00",
        "decision_time": decision_time,
        "direction": 1,
        "entry_bar_index": 11,
        "entry_bid_micropoints": 1_000_000,
        "entry_spread_cost_micropoints": 10,
        "entry_spread_source_bar_index": 10,
        "entry_spread_source_bar_open_time": day + "T08:55:00",
        "entry_time": entry_time,
        "executable_id": executable_id,
        "exit_bar_index": 23,
        "exit_bid_micropoints": 1_000_000 + net + 10,
        "exit_spread_cost_micropoints": 10,
        "exit_spread_source_bar_index": 22,
        "exit_spread_source_bar_open_time": day + "T09:55:00",
        "exit_time": exit_time,
        "fold_id": "rw_001",
        "gross_pnl_micropoints": net + 10,
        "native_cost_micropoints": 10,
        "native_net_pnl_micropoints": net,
        "observation_id": observation_id,
        "regime": "middle",
        "schema": PROSPECTIVE_PAIR_TRADE_SCHEMA,
        "slot": "primary",
        "stress_cost_micropoints": 20,
        "stress_net_pnl_micropoints": net - 10,
    }


def _trace(definition: ProspectivePairProtocolDefinition) -> dict[str, object]:
    trades: list[dict[str, object]] = []
    intents: list[dict[str, object]] = []
    eligible: list[dict[str, object]] = []
    invariance: list[dict[str, object]] = []
    for member in definition.members:
        for index, day in enumerate(definition.folds[0].eligible_dates):
            net = (10 if index % 2 == 0 else -8) + (
                4 if member.executable_id == SUBJECT_ID else 0
            )
            trade = _trade(
                executable_id=member.executable_id,
                configuration_id=member.configuration_id,
                day=day,
                net=net,
            )
            trades.append(trade)
            intents.append(
                {
                    key: trade[key]
                    for key in (
                        "configuration_id",
                        "decision_time",
                        "direction",
                        "entry_time",
                        "executable_id",
                        "exit_time",
                        "fold_id",
                        "observation_id",
                        "slot",
                    )
                }
                | {"schema": PROSPECTIVE_PAIR_INTENT_SCHEMA, "status": "executed"}
            )
            eligible.append(
                {
                    "configuration_id": member.configuration_id,
                    "date": day,
                    "executable_id": member.executable_id,
                    "fold_id": "rw_001",
                    "schema": PROSPECTIVE_PAIR_ELIGIBLE_DAY_SCHEMA,
                }
            )
        for key in definition.invariance_keys:
            invariance.append(
                {
                    "compared_row_count": 40,
                    "executable_id": member.executable_id,
                    "fold_id": "rw_001",
                    "full_values_sha256": "8" * 64,
                    "invariance_key": key,
                    "mismatch_count": 0,
                    "prefix_values_sha256": "8" * 64,
                    "schema": PROSPECTIVE_PAIR_INVARIANCE_SCHEMA,
                }
            )
    return {
        "adapter_implementation_sha256": "7" * 64,
        "attribution": {
            "definition_identity": definition.identity,
            "implementation_identities": dict(
                definition.producer_implementation_identities
            ),
            "selection_inference_sha256": __import__(
                "axiom_rift.research.selection_inference",
                fromlist=["selection_inference_implementation_sha256"],
            ).selection_inference_implementation_sha256(),
            "trace_validator_sha256": __import__(
                "axiom_rift.research.prospective_pair_trace",
                fromlist=["prospective_pair_trace_implementation_sha256"],
            ).prospective_pair_trace_implementation_sha256(),
        },
        "controls": {"control_executable_id": CONTROL_ID},
        "dataset_sha256": definition.dataset_sha256,
        "eligible_day_observations": eligible,
        "family_id": definition.family_id,
        "invariance_comparisons": invariance,
        "intent_observations": intents,
        "job_hash": JOB_HASH,
        "job_id": JOB_ID,
        "material_identity": definition.material_identity,
        "mission_id": MISSION_ID,
        "ordered_family": list(definition.prospective_executable_ids),
        "protocol_definition": definition.manifest(),
        "protocol_id": PROSPECTIVE_PAIR_TRACE_PROTOCOL_ID,
        "schema": SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
        "split_artifact_sha256": definition.split_artifact_sha256,
        "subject_executable_id": SUBJECT_ID,
        "trade_observations": trades,
        "windows": [item.manifest() for item in definition.folds],
    }


def test_prospective_pair_is_registered_and_round_trips_definition() -> None:
    definition = _definition()
    assert PROSPECTIVE_PAIR_TRACE_PROTOCOL_ID in SCIENTIFIC_TRACE_PROTOCOL_IDS
    assert (
        PROSPECTIVE_PAIR_TRACE_PROTOCOL_ID
        in PROTOCOL_DEFINITION_TRACE_PROTOCOL_IDS
    )
    assert prospective_pair_protocol_definition_from_manifest(
        definition.manifest()
    ).manifest() == definition.manifest()
    assert normalized_trace_protocol_definition(definition.manifest()) == (
        PROSPECTIVE_PAIR_TRACE_PROTOCOL_ID,
        definition.manifest(),
    )


def test_dispatch_recomputes_pair_metrics_from_atomic_rows() -> None:
    definition = _definition()
    trace = _trace(definition)
    calculation = build_prospective_pair_calculation(
        trace=trace,
        trace_output_name=OUTPUT_NAME,
        definition=definition,
    )
    trace_hash = sha256(canonical_bytes(trace)).hexdigest()
    subject_net = calculation["metrics"]["after_cost_fixed_lot_economics"][
        "net_profit_micropoints"
    ]
    assert validate_trace_calculation_pair(
        trace=trace,
        trace_output_name=OUTPUT_NAME,
        trace_hash=trace_hash,
        calculation=calculation,
        expected_evidence_modes=PROSPECTIVE_PAIR_EVIDENCE_MODES,
        expected_metric_bindings_by_mode={
            "cost_and_execution": (
                {
                    "claim_id": "after_cost_fixed_lot_economics",
                    "metric": "net_profit_micropoints",
                    "value": subject_net,
                },
            )
        },
        mission_id=MISSION_ID,
        executable_id=SUBJECT_ID,
        job_id=JOB_ID,
        job_hash=JOB_HASH,
    ) == PROSPECTIVE_PAIR_EVIDENCE_MODES


@pytest.mark.parametrize(
    "mutation",
    ("cost", "eligible", "definition", "future_source", "invariance"),
)
def test_pair_proof_rejects_atomic_or_authority_tampering(mutation: str) -> None:
    definition = _definition()
    trace = _trace(definition)
    calculation = build_prospective_pair_calculation(
        trace=trace,
        trace_output_name=OUTPUT_NAME,
        definition=definition,
    )
    tampered = deepcopy(trace)
    if mutation == "cost":
        tampered["trade_observations"][0]["native_net_pnl_micropoints"] += 1
    elif mutation == "eligible":
        tampered["eligible_day_observations"].pop()
    elif mutation == "definition":
        tampered["protocol_definition"]["historical_context"][
            "prior_global_exposure_count"
        ] += 1
    elif mutation == "future_source":
        tampered["trade_observations"][0][
            "entry_spread_source_bar_open_time"
        ] = tampered["trade_observations"][0]["entry_time"]
    else:
        tampered["invariance_comparisons"][0][
            "prefix_values_sha256"
        ] = "9" * 64
    with pytest.raises(ScientificTraceError):
        validate_trace_calculation_pair(
            trace=tampered,
            trace_output_name=OUTPUT_NAME,
            trace_hash=sha256(canonical_bytes(tampered)).hexdigest(),
            calculation=calculation,
            expected_evidence_modes=PROSPECTIVE_PAIR_EVIDENCE_MODES,
            expected_metric_bindings_by_mode={},
            mission_id=MISSION_ID,
            executable_id=SUBJECT_ID,
            job_id=JOB_ID,
            job_hash=JOB_HASH,
        )
