from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

import axiom_rift.research.cost_aware_execution_trace as cost_trace_module
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_PROTOCOL_ID,
    CostAwareExecutionProtocolDefinition,
    cost_aware_execution_protocol_definition,
)
from axiom_rift.research.scientific_trace import (
    ATOMIC_TRACE_PROOF_KIND,
    CALCULATION_PROOF_KIND,
    COST_AWARE_EXECUTION_TRACE_PROTOCOL_ID,
    FIXED_HOLD_TRACE_PROTOCOL_IDS,
    PROTOCOL_DEFINITION_TRACE_PROTOCOL_IDS,
    SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
    SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
    SCIENTIFIC_TRACE_PROTOCOL_IDS,
    ScientificTraceError,
    normalized_trace_protocol_definition,
    require_matching_trace_protocol_definitions,
    trace_proof_kinds,
    validate_trace_calculation_pair,
)
from axiom_rift.research.historical_family_stu0070 import (
    STU0070_HISTORICAL_FAMILY,
)


MISSION_ID = "MIS-COST-AWARE-TRACE"
CONTROL_EXECUTABLE_ID = "executable:" + "1" * 64
TARGET_EXECUTABLE_ID = "executable:" + "2" * 64
OTHER_EXECUTABLE_ID = "executable:" + "3" * 64
JOB_ID = "job:" + "4" * 64
JOB_HASH = "5" * 64
TRACE_HASH = "6" * 64
TRACE_OUTPUT_NAME = "scientific/STU-COST/target/evaluation-trace.json"


@pytest.fixture
def definition() -> CostAwareExecutionProtocolDefinition:
    return cost_aware_execution_protocol_definition(
        historical_family=STU0070_HISTORICAL_FAMILY,
        prospective_control_executable_id=CONTROL_EXECUTABLE_ID,
        prospective_target_executable_id=TARGET_EXECUTABLE_ID,
    )


def _trace_and_calculation(
    definition: CostAwareExecutionProtocolDefinition,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = definition.manifest()
    trace = {
        "adapter_implementation_sha256": "7" * 64,
        "attribution": {},
        "candidate_observations": [],
        "controls": {},
        "dataset_sha256": "8" * 64,
        "eligible_day_observations": [],
        "family_id": definition.prospective_family_id,
        "historical_context": {
            "adjustment_authority": (
                manifest["inference"][
                    "historical_context_adjustment_authority"
                ]
            ),
            "family_authority_id": "historical-family-authority:" + "a" * 64,
            "historical_context_prior_global_exposure_count": manifest[
                "inference"
            ]["original_family_end_global_exposure_count"],
            "historical_family_identity": definition.historical_family.identity,
            "original_family_end_global_exposure_count": manifest["inference"][
                "original_family_end_global_exposure_count"
            ],
            "replay_obligation_id": "historical-replay-obligation:" + "b" * 64,
            "schema": "cost_aware_execution_historical_context.v1",
        },
        "intent_observations": [],
        "invariance_comparisons": [],
        "job_hash": JOB_HASH,
        "job_id": JOB_ID,
        "material_identity": "material:cost-aware-fixture",
        "mission_id": MISSION_ID,
        "ordered_family": list(definition.prospective_executable_ids),
        "protocol_definition": manifest,
        "protocol_id": COST_AWARE_EXECUTION_TRACE_PROTOCOL_ID,
        "schema": SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
        "source_observations": [],
        "split_artifact_sha256": "9" * 64,
        "subject_executable_id": TARGET_EXECUTABLE_ID,
        "trade_observations": [],
        "windows": [],
    }
    calculation = {
        "evidence_modes": ["causal_contrast"],
        "executable_id": TARGET_EXECUTABLE_ID,
        "job_hash": JOB_HASH,
        "job_id": JOB_ID,
        "metrics": {},
        "mission_id": MISSION_ID,
        "parameters": {},
        "protocol_definition": manifest,
        "protocol_id": COST_AWARE_EXECUTION_TRACE_PROTOCOL_ID,
        "schema": SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
        "statistics": {},
        "trace": {"output_name": TRACE_OUTPUT_NAME, "sha256": TRACE_HASH},
    }
    return trace, calculation


def test_cost_aware_protocol_uses_generic_definition_bound_proof_pair() -> None:
    assert COST_AWARE_EXECUTION_PROTOCOL_ID == (
        COST_AWARE_EXECUTION_TRACE_PROTOCOL_ID
    )
    assert COST_AWARE_EXECUTION_TRACE_PROTOCOL_ID in SCIENTIFIC_TRACE_PROTOCOL_IDS
    assert (
        COST_AWARE_EXECUTION_TRACE_PROTOCOL_ID
        in PROTOCOL_DEFINITION_TRACE_PROTOCOL_IDS
    )
    assert (
        COST_AWARE_EXECUTION_TRACE_PROTOCOL_ID
        not in FIXED_HOLD_TRACE_PROTOCOL_IDS
    )
    assert trace_proof_kinds(
        protocol_id=COST_AWARE_EXECUTION_TRACE_PROTOCOL_ID,
        evidence_mode="cost_and_execution",
    ) == {
        ATOMIC_TRACE_PROOF_KIND: SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
        CALCULATION_PROOF_KIND: SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
    }


def test_cost_aware_definition_dispatch_is_exact_and_closed(
    definition: CostAwareExecutionProtocolDefinition,
) -> None:
    protocol_id, manifest = normalized_trace_protocol_definition(
        definition.manifest()
    )
    assert protocol_id == COST_AWARE_EXECUTION_TRACE_PROTOCOL_ID
    assert manifest == definition.manifest()

    drifted = deepcopy(manifest)
    drifted["protocol_id"] = "cost_aware_execution.unregistered.v1"
    with pytest.raises(
        ScientificTraceError,
        match="definition is not registered",
    ):
        normalized_trace_protocol_definition(drifted)


def test_definition_matcher_rejects_cross_definition_or_protocol(
    definition: CostAwareExecutionProtocolDefinition,
) -> None:
    manifest = definition.manifest()
    assert require_matching_trace_protocol_definitions(
        planned=manifest,
        calculated=deepcopy(manifest),
        calculation_protocol_id=COST_AWARE_EXECUTION_TRACE_PROTOCOL_ID,
    ) == (COST_AWARE_EXECUTION_TRACE_PROTOCOL_ID, manifest)

    other = cost_aware_execution_protocol_definition(
        historical_family=STU0070_HISTORICAL_FAMILY,
        prospective_control_executable_id=CONTROL_EXECUTABLE_ID,
        prospective_target_executable_id=OTHER_EXECUTABLE_ID,
    )
    with pytest.raises(ScientificTraceError, match="definitions differ"):
        require_matching_trace_protocol_definitions(
            planned=manifest,
            calculated=other.manifest(),
            calculation_protocol_id=COST_AWARE_EXECUTION_TRACE_PROTOCOL_ID,
        )
    with pytest.raises(ScientificTraceError, match="definitions differ"):
        require_matching_trace_protocol_definitions(
            planned=manifest,
            calculated=manifest,
            calculation_protocol_id="analog_state.concurrent_four_config.v1",
        )


def test_cost_aware_trace_dispatch_keeps_fixed_hold_fields_separate(
    definition: CostAwareExecutionProtocolDefinition,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace, calculation = _trace_and_calculation(definition)
    calls: list[CostAwareExecutionProtocolDefinition] = []

    def fake_validator(
        *,
        trace: dict[str, Any],
        calculation: dict[str, Any],
        definition: CostAwareExecutionProtocolDefinition,
    ) -> dict[str, dict[str, int | None]]:
        del trace, calculation
        calls.append(definition)
        return {"causal": {"paired_metric": 11}}

    monkeypatch.setattr(
        cost_trace_module,
        "validate_cost_aware_execution_trace_calculation",
        fake_validator,
    )
    assert validate_trace_calculation_pair(
        trace=trace,
        trace_output_name=TRACE_OUTPUT_NAME,
        trace_hash=TRACE_HASH,
        calculation=calculation,
        expected_evidence_modes=("causal_contrast",),
        expected_metric_bindings_by_mode={
            "causal_contrast": (
                {"claim_id": "causal", "metric": "paired_metric", "value": 11},
            )
        },
        mission_id=MISSION_ID,
        executable_id=TARGET_EXECUTABLE_ID,
        job_id=JOB_ID,
        job_hash=JOB_HASH,
    ) == ("causal_contrast",)
    assert calls == [definition]

    missing_source = deepcopy(trace)
    missing_source.pop("source_observations")
    with pytest.raises(ScientificTraceError, match="schema is invalid"):
        validate_trace_calculation_pair(
            trace=missing_source,
            trace_output_name=TRACE_OUTPUT_NAME,
            trace_hash=TRACE_HASH,
            calculation=calculation,
            expected_evidence_modes=("causal_contrast",),
            expected_metric_bindings_by_mode={},
            mission_id=MISSION_ID,
            executable_id=TARGET_EXECUTABLE_ID,
            job_id=JOB_ID,
            job_hash=JOB_HASH,
        )

    fixed_only_field = deepcopy(trace)
    fixed_only_field["semantic_transition_evidence"] = []
    with pytest.raises(ScientificTraceError, match="schema is invalid"):
        validate_trace_calculation_pair(
            trace=fixed_only_field,
            trace_output_name=TRACE_OUTPUT_NAME,
            trace_hash=TRACE_HASH,
            calculation=calculation,
            expected_evidence_modes=("causal_contrast",),
            expected_metric_bindings_by_mode={},
            mission_id=MISSION_ID,
            executable_id=TARGET_EXECUTABLE_ID,
            job_id=JOB_ID,
            job_hash=JOB_HASH,
        )


def test_cost_aware_trace_dispatch_rejects_definition_drift_before_recompute(
    definition: CostAwareExecutionProtocolDefinition,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace, calculation = _trace_and_calculation(definition)
    other = cost_aware_execution_protocol_definition(
        historical_family=STU0070_HISTORICAL_FAMILY,
        prospective_control_executable_id=CONTROL_EXECUTABLE_ID,
        prospective_target_executable_id=OTHER_EXECUTABLE_ID,
    )
    calculation["protocol_definition"] = other.manifest()
    called = False

    def fake_validator(**_kwargs: Any) -> dict[str, dict[str, int | None]]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(
        cost_trace_module,
        "validate_cost_aware_execution_trace_calculation",
        fake_validator,
    )
    with pytest.raises(ScientificTraceError, match="definitions differ"):
        validate_trace_calculation_pair(
            trace=trace,
            trace_output_name=TRACE_OUTPUT_NAME,
            trace_hash=TRACE_HASH,
            calculation=calculation,
            expected_evidence_modes=("causal_contrast",),
            expected_metric_bindings_by_mode={},
            mission_id=MISSION_ID,
            executable_id=TARGET_EXECUTABLE_ID,
            job_id=JOB_ID,
            job_hash=JOB_HASH,
        )
    assert not called
