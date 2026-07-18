from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import inspect

import pytest

import axiom_rift.operations.replay_job_implementation_preflight as preflight_module
from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import ExecutableSpec
from axiom_rift.operations.replay_job_implementation_preflight import (
    PREFLIGHT_SCHEMA,
    ReplayJobImplementationPreflightError,
    ReplayJobImplementationPreflightRequest,
    derive_replay_job_scientific_surface,
    replay_job_scientific_equivalence_surface,
    replay_job_scientific_surface_hash,
    require_replacement_replay_baseline_semantics,
    require_replacement_replay_study_semantics,
)
from axiom_rift.research.cost_aware_execution_pair import (
    COST_AWARE_EXECUTION_PAIR_CONTEXT_PARAMETER,
    cost_aware_execution_pair_configurations,
    cost_aware_execution_pair_controlled_chassis,
    cost_aware_execution_pair_executable,
)
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_BASE_SEED,
    COST_AWARE_EXECUTION_BLOCK_LENGTHS,
    COST_AWARE_EXECUTION_BOOTSTRAP_SAMPLES,
    COST_AWARE_EXECUTION_MONTE_CARLO_CONFIDENCE_PPM,
    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
    COST_AWARE_EXECUTION_PROTOCOL_ID,
    build_cost_aware_execution_validation_plan,
    cost_aware_execution_protocol_definition,
)
from axiom_rift.research.evidence_proofs import (
    CALCULATION_PROOF_KIND,
    COST_AWARE_EXECUTION_PAIR_TRACE_PROOF_KIND,
)
from axiom_rift.research.historical_family_stu0070 import (
    STU0070_HISTORICAL_FAMILY,
)
from axiom_rift.research.portfolio import (
    BatchSpec,
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
)


MISSION_ID = "MIS-9701"
STUDY_ID = "STU-9701"
OBLIGATION_ID = "historical-replay-obligation:" + "a" * 64
FAMILY_AUTHORITY_ID = "historical-family-authority:" + "b" * 64
ORIGINAL_FAMILY_END = (
    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
)


@dataclass(frozen=True)
class _CostFixture:
    request: ReplayJobImplementationPreflightRequest
    study_payload: dict[str, object]
    batch_payload: dict[str, object]
    artifacts: dict[str, bytes]

    def surface(self) -> dict[str, object]:
        return derive_replay_job_scientific_surface(
            self.request,
            study_payload=self.study_payload,
            batch_payload=self.batch_payload,
            artifact_reader=self.artifacts.__getitem__,
        )


def test_production_preflight_does_not_import_historical_reconstruction() -> None:
    source = inspect.getsource(preflight_module)

    assert "axiom_rift.research.historical_family_stu0070" not in source


def _clone_with_prior(executable: ExecutableSpec, prior: int) -> ExecutableSpec:
    parameters = executable.parameter_values()
    assert isinstance(parameters, dict)
    parameters[COST_AWARE_EXECUTION_PAIR_CONTEXT_PARAMETER] = prior
    return ExecutableSpec(
        display_name=executable.display_name,
        components=executable.components,
        parameters=parameters,
        data_contract=executable.data_contract,
        split_contract=executable.split_contract,
        clock_contract=executable.clock_contract,
        cost_contract=executable.cost_contract,
        engine_contract=executable.engine_contract,
        source_contracts=executable.source_contracts,
    )


def _fixture(
    *,
    context_count: int,
    first_member_prior_override: int | None = None,
) -> _CostFixture:
    configurations = cost_aware_execution_pair_configurations(
        STU0070_HISTORICAL_FAMILY
    )
    executables = tuple(
        cost_aware_execution_pair_executable(
            configuration,
            historical_family=STU0070_HISTORICAL_FAMILY,
            historical_context_prior_global_exposure_count=context_count,
            original_family_end_global_exposure_count=ORIGINAL_FAMILY_END,
        )
        for configuration in configurations
    )
    if first_member_prior_override is not None:
        executables = (
            _clone_with_prior(executables[0], first_member_prior_override),
            executables[1],
        )
    definition = cost_aware_execution_protocol_definition(
        historical_family=STU0070_HISTORICAL_FAMILY,
        prospective_control_executable_id=executables[0].identity,
        prospective_target_executable_id=executables[1].identity,
    )
    plans: list[dict[str, object]] = []
    bindings: list[dict[str, object]] = []
    artifacts: dict[str, bytes] = {}
    for ordinal, executable in enumerate(executables, start=1):
        prefix = f"scientific/{STUDY_ID}/job-{ordinal}"
        plan = build_cost_aware_execution_validation_plan(
            definition=definition,
            mission_id=MISSION_ID,
            executable_id=executable.identity,
            output_names={
                "calculation": f"{prefix}/calculation-proof.json",
                "trace": f"{prefix}/evaluation-trace.json",
            },
        )
        plan_bytes = canonical_bytes(plan)
        plan_hash = sha256(plan_bytes).hexdigest()
        artifacts[plan_hash] = plan_bytes
        plans.append(plan)
        bindings.append(
            {
                "evidence_depth": plan["evidence_depth"],
                "evidence_modes": plan["evidence_modes"],
                "planned_claims": plan["planned_claims"],
                "result_manifest_output": f"{prefix}/result.json",
                "validation_plan_hash": plan_hash,
                "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
            }
        )
    request = ReplayJobImplementationPreflightRequest(
        mission_id=MISSION_ID,
        protocol_id="python.source.cost_aware_execution.v1",
        callable_identity="cost_aware_execution.execute.v1",
        implementation_identity=sha256(b"cost-aware-job-v1").hexdigest(),
        executables=executables,
        scientific_bindings=tuple(bindings),
        replay_obligation_ids=(OBLIGATION_ID,),
    )
    chassis = cost_aware_execution_pair_controlled_chassis(
        historical_family=STU0070_HISTORICAL_FAMILY,
        historical_context_prior_global_exposure_count=context_count,
        original_family_end_global_exposure_count=ORIGINAL_FAMILY_END,
    )
    changed_domains = [item.value for item in chassis.changed_domains]
    controlled_domains = [item.value for item in chassis.controlled_domains]
    study_payload = {
        "changed_domains": changed_domains,
        "controlled_chassis": chassis.to_identity_payload(),
        "controlled_domains": controlled_domains,
        "material_identity": "2" * 64,
        "mechanism_family": "cost-aware-execution-paired-policy",
        "mission_id": MISSION_ID,
        "portfolio_action": "synthesize",
        "primary_research_layer": "execution",
        "question": {
            "causal_question": "Does causal spread abstention improve net execution?",
            "changed_variables": changed_domains,
            "controlled_variables": controlled_domains,
            "done_conditions": ["both policies evaluated under one paired trace"],
            "evidence_modes": [
                "causal_contrast",
                "cost_and_execution",
                "sensitivity_or_stress",
                "temporal_stability",
            ],
        },
        "replay_obligation_ids": [OBLIGATION_ID],
        "semantic_proposal": {
            "candidate_eligible": False,
            "historical_obligation_id": OBLIGATION_ID,
            "mechanism": "cost-aware-execution-paired-policy",
            "original_study_id": STU0070_HISTORICAL_FAMILY.original_study_id,
        },
        "semantic_question_core_id": "semantic-question-core:" + "4" * 64,
    }
    batch_spec = BatchSpec(
        batch_id="BAT-9701",
        study_id=STUDY_ID,
        study_hash="5" * 64,
        display_name="cost-aware execution policy pair",
        max_trials=2,
        max_compute_seconds=400,
        max_wall_seconds=800,
        stop_rule="stop only after the exact paired-policy family",
        concurrent_family=ConcurrentFamilyManifest(
            evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
            executable_ids=tuple(sorted(item.identity for item in executables)),
        ),
        acceptance_profile={
            "candidate_authority": "none",
            "exact_original_criteria": [
                "D03-primary-control",
                "D04-primary-control-uncertainty",
                "E01-familywise-selection",
            ],
            "historical_family_authority_id": FAMILY_AUTHORITY_ID,
            "historical_family_identity": STU0070_HISTORICAL_FAMILY.identity,
            "replay_obligation_id": OBLIGATION_ID,
        },
        adaptive_basis={
            "causal_complexity": "one exact paired-policy family",
            "compute_cost": "two bounded Jobs over one shared trace",
            "expected_information_value": "resolve the execution repair",
            "portfolio_opportunity_cost": "other axes remain schedulable",
            "surface_curvature": "fixed paired contrast",
            "uncertainty": "one unresolved replay",
        },
    )
    return _CostFixture(
        request=request,
        study_payload=study_payload,
        batch_payload={"spec": batch_spec.to_identity_payload()},
        artifacts=artifacts,
    )


def _accepted_payload(fixture: _CostFixture) -> dict[str, object]:
    surface = fixture.surface()
    return {
        "callable_identity": fixture.request.callable_identity,
        "executable_ids": list(fixture.request.executable_ids),
        "executable_manifests": [
            item.to_identity_payload() for item in fixture.request.executables
        ],
        "failure_detail": None,
        "failure_fingerprint": None,
        "mission_id": fixture.request.mission_id,
        "outcome": "accepted",
        "protocol_id": fixture.request.protocol_id,
        "reason_code": None,
        "remediation_kind": None,
        "replacement_for_preflight_id": (
            "job-implementation-preflight:" + "c" * 64
        ),
        "replay_obligation_ids": list(fixture.request.replay_obligation_ids),
        "schema": PREFLIGHT_SCHEMA,
        "scientific_surface": surface,
        "scientific_surface_hash": replay_job_scientific_surface_hash(surface),
        "source_closure_authority": {},
    }


def test_cost_aware_surface_is_closed_and_context_invariant() -> None:
    original = _fixture(context_count=581)
    later_context = _fixture(context_count=600)

    original_surface = original.surface()
    later_surface = later_context.surface()

    assert original_surface == later_surface
    assert replay_job_scientific_surface_hash(original_surface) == (
        replay_job_scientific_surface_hash(later_surface)
    )
    assert replay_job_scientific_equivalence_surface(original_surface) == (
        replay_job_scientific_equivalence_surface(later_surface)
    )
    for member in original_surface["members"]:
        plan = member["validation_plan"]
        protocol = plan["protocol_definition"]
        assert protocol["protocol_id"] == COST_AWARE_EXECUTION_PROTOCOL_ID
        assert protocol["schema"] == (
            "cost_aware_execution_protocol_scientific_surface.v1"
        )
        assert (
            protocol["original_family_end_global_exposure_count"]
            == ORIGINAL_FAMILY_END
        )
        expected_inference_closure = {
            "base_seed": COST_AWARE_EXECUTION_BASE_SEED,
            "block_lengths": list(COST_AWARE_EXECUTION_BLOCK_LENGTHS),
            "bootstrap_samples": COST_AWARE_EXECUTION_BOOTSTRAP_SAMPLES,
            "monte_carlo_confidence_ppm": (
                COST_AWARE_EXECUTION_MONTE_CARLO_CONFIDENCE_PPM
            ),
        }
        assert {
            key: protocol["inference"][key]
            for key in expected_inference_closure
        } == expected_inference_closure
        assert {
            item["proof_kind"] for item in plan["proof_requirements"]
        } == {
            COST_AWARE_EXECUTION_PAIR_TRACE_PROOF_KIND,
            CALCULATION_PROOF_KIND,
        }
        assert {
            item["criterion_id"]: item["family_size"]
            for item in plan["adjudication_profile"]["multiplicity"]
        } == {
            "D04-primary-control-uncertainty": 1,
            "E01-familywise-selection": 2,
        }


def test_cost_aware_preflight_rejects_reversed_policy_order() -> None:
    fixture = _fixture(context_count=581)
    reversed_request = ReplayJobImplementationPreflightRequest(
        mission_id=fixture.request.mission_id,
        protocol_id=fixture.request.protocol_id,
        callable_identity=fixture.request.callable_identity,
        implementation_identity=fixture.request.implementation_identity,
        executables=tuple(reversed(fixture.request.executables)),
        scientific_bindings=tuple(
            reversed(fixture.request.scientific_binding_values())
        ),
        replay_obligation_ids=fixture.request.replay_obligation_ids,
    )
    with pytest.raises(
        ReplayJobImplementationPreflightError,
        match="differs from the preflight pair",
    ):
        derive_replay_job_scientific_surface(
            reversed_request,
            study_payload=fixture.study_payload,
            batch_payload=fixture.batch_payload,
            artifact_reader=fixture.artifacts.__getitem__,
        )


def test_cost_aware_preflight_rejects_prior_before_original_family_end() -> None:
    fixture = _fixture(
        context_count=581,
        first_member_prior_override=ORIGINAL_FAMILY_END - 1,
    )
    with pytest.raises(
        ReplayJobImplementationPreflightError,
        match="exposure context drifted",
    ):
        fixture.surface()


def test_cost_aware_surface_hash_rejects_role_drift() -> None:
    surface = _fixture(context_count=581).surface()
    surface["members"][0]["validation_plan"]["protocol_definition"][
        "members"
    ][0]["role"] = "target"
    with pytest.raises(
        ReplayJobImplementationPreflightError,
        match="protocol scientific surface drifted",
    ):
        replay_job_scientific_surface_hash(surface)


def test_cost_aware_replacement_boundaries_accept_later_context() -> None:
    accepted_fixture = _fixture(context_count=581)
    later_fixture = _fixture(context_count=600)
    accepted = _accepted_payload(accepted_fixture)
    baseline = later_fixture.study_payload["controlled_chassis"][
        "baseline_executable"
    ]

    assert isinstance(baseline, dict)
    baseline_hash = require_replacement_replay_baseline_semantics(
        accepted_payload=accepted,
        baseline_executable_manifest=baseline,
    )
    study_hash = require_replacement_replay_study_semantics(
        accepted_payload=accepted,
        study_payload=later_fixture.study_payload,
    )
    assert baseline_hash == study_hash


def test_cost_aware_replacement_study_rejects_invalid_context() -> None:
    fixture = _fixture(context_count=581)
    accepted = _accepted_payload(fixture)
    proposed = deepcopy(fixture.study_payload)
    proposed["controlled_chassis"]["baseline_executable"]["parameters"][
        COST_AWARE_EXECUTION_PAIR_CONTEXT_PARAMETER
    ] = ORIGINAL_FAMILY_END - 1

    with pytest.raises(
        ReplayJobImplementationPreflightError,
        match="exposure context drifted",
    ):
        require_replacement_replay_study_semantics(
            accepted_payload=accepted,
            study_payload=proposed,
        )
