from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import (
    ComponentSpec,
    ExecutableSpec,
    canonical_digest,
)
from axiom_rift.operations.replay_job_implementation_preflight import (
    PREFLIGHT_SCHEMA,
    REPLACEMENT_REQUIRED,
    SAME_IDENTITY_REPAIR,
    ReplayJobImplementationPreflightError,
    ReplayJobImplementationPreflightRequest,
    ReplayJobImplementationPreflightResult,
    derive_replay_job_scientific_surface,
    replay_executable_reference_map,
    replay_job_implementation_remediation,
    replay_job_scientific_equivalence_surface,
    replay_job_scientific_surface_hash,
    require_active_replay_job_replacement_binding,
    require_durable_replay_job_implementation_preflight,
    require_replacement_replay_job_scientific_surface,
    require_replacement_replay_study_semantics,
)
from axiom_rift.operations.job_implementation_authority import (
    JobImplementationAuthorityError,
)
from axiom_rift.operations.writer import RecoveryRequired, StateWriter
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
)
from axiom_rift.research.fixed_hold_family_job import (
    build_fixed_hold_family_job_plan,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FixedHoldProtocolDefinition,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.historical_family_binding import (
    ControlBinding,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
)
from axiom_rift.research.implementation_closure import (
    ImplementationClosureError,
)
from axiom_rift.research.portfolio import (
    BatchSpec,
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
)
from axiom_rift.research.scientific_trace import (
    ANALOG_FIXED_HOLD_REPLAY_TRACE_PROTOCOL_ID,
)
from axiom_rift.storage.index import IndexRecord


MISSION_ID = "MIS-9001"
OBLIGATION_ID = "historical-replay-obligation:" + "a" * 64
_CONTEXT_PARAMETER = "historical_context_prior_global_exposure_count"
_ORIGINAL_FAMILY_END_PARAMETER = (
    "original_family_end_global_exposure_count"
)
_CONTEXT_OWNER_PROTOCOL = (
    "portfolio.concurrent_fixed_hold_family_inference.v2"
)
_VOLATILITY_REPLAY_PROTOCOL = (
    "volatility_duration.concurrent_four_config.replay.v1"
)
_ENGINE_RUNTIME = (
    "python3.12.7",
    "numpy2.1.3",
    "pandas2.2.3",
    "scipy1.14.1",
)
_OLD_ENGINE_ROLES = (
    "adapter",
    "catalog",
    "loader",
    "selection",
    "shared",
    "trace_engine",
)
_NEW_ENGINE_ROLES = (
    "adapter",
    "loader",
    "selection",
    "shared",
    "trace_engine",
)
_OLD_PRODUCER_ROLES = (
    "adapter_sha256",
    "catalog_sha256",
    "discovery_sha256",
    "loader_sha256",
    "trace_engine_sha256",
)
_STUDY_AUTHORITY_KEYS = (
    "changed_domains",
    "controlled_chassis",
    "controlled_domains",
    "material_identity",
    "mechanism_family",
    "mission_id",
    "portfolio_action",
    "primary_research_layer",
    "question",
    "replay_obligation_ids",
    "semantic_proposal",
    "semantic_question_core_id",
)


@dataclass(frozen=True)
class _Fixture:
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


def _implementation(name: str, generation: int) -> str:
    digest = sha256(f"{name}:{generation}".encode("ascii")).hexdigest()
    return f"fixture.{name}@sha256:{digest}"


def _components(generation: int) -> tuple[ComponentSpec, ...]:
    label = ComponentSpec(
        display_name="fixture historical label",
        protocol="label.fixture_historical_member.v1",
        implementation=_implementation("label", generation),
        spec={
            "parameter_fields": [
                "configuration_id",
                "historical_reference_executable_id",
                "holding_bars",
            ]
        },
    )
    selector = ComponentSpec(
        display_name="fixture fixed selector",
        protocol="selector.fixture_fixed.v1",
        implementation=_implementation("selector", generation),
        spec={"threshold": 0},
        semantic_dependencies=(label.identity,),
    )
    trade = ComponentSpec(
        display_name="fixture next-open trade",
        protocol="trade.fixture_next_open.v1",
        implementation=_implementation("trade", generation),
        spec={"entry": "next_open"},
        semantic_dependencies=(selector.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="fixture fixed lifecycle",
        protocol="lifecycle.fixture_fixed_hold.v1",
        implementation=_implementation("lifecycle", generation),
        spec={"parameter_fields": ["holding_bars"]},
        semantic_dependencies=(trade.identity,),
    )
    execution = ComponentSpec(
        display_name="fixture exact execution",
        protocol="execution.fixture_exact_cost.v1",
        implementation=_implementation("execution", generation),
        spec={"cost_timing": "completed_period"},
        semantic_dependencies=(lifecycle.identity,),
    )
    return label, selector, trade, lifecycle, execution


def _historical_family() -> HistoricalFamilySpec:
    references = tuple(
        f"executable:{ordinal:064x}" for ordinal in range(1, 5)
    )
    members = tuple(
        HistoricalMemberSpec(
            ordinal=ordinal,
            configuration_id=f"configuration-{ordinal}",
            historical_reference_executable_id=references[ordinal - 1],
            parameters={
                "holding_bars": 2,
                "profile": f"profile-{ordinal}",
            },
        )
        for ordinal in range(1, 5)
    )
    opposite_indices = (1, 0, 3, 2)
    feature_indices = (2, 2, 0, 0)
    controls = tuple(
        ControlBinding(
            subject_historical_executable_id=reference,
            opposite_historical_executable_id=(
                references[opposite_indices[index]]
            ),
            feature_historical_executable_ids=(
                references[feature_indices[index]],
            ),
        )
        for index, reference in enumerate(references)
    )
    return HistoricalFamilySpec(
        original_study_id="STU-8001",
        original_batch_id="batch:" + "b" * 64,
        target_historical_executable_id=references[-1],
        members=members,
        controls=controls,
    )


def _fixture(
    *,
    generation: int,
    context_count: int,
    study_id: str,
    data_contract: str = "data:fixture-observed-v1",
    cost_contract: str = "cost:fixture-exact-v1",
    engine_contract: str = "engine:fixture-semantic-v1",
    holding_override: int | None = None,
    nested_context_override: int | None = None,
    request_protocol: str = "python.source.fixture_fixed_hold.v1",
) -> _Fixture:
    family = _historical_family()
    components = _components(generation)
    executables: list[ExecutableSpec] = []
    for member in family.members:
        parameters = {
            **member.parameter_values(),
            "configuration_id": member.configuration_id,
            "historical_context_prior_global_exposure_count": context_count,
            "historical_reference_executable_id": (
                member.historical_reference_executable_id
            ),
        }
        if holding_override is not None and member.ordinal == 1:
            parameters["holding_bars"] = holding_override
        if nested_context_override is not None:
            parameters["risk_config"] = {
                "historical_context_prior_global_exposure_count": (
                    nested_context_override
                )
            }
        executables.append(
            ExecutableSpec(
                display_name=f"fixture member {member.ordinal}",
                components=components,
                parameters=parameters,
                data_contract=data_contract,
                split_contract="split:fixture-rolling-v1",
                clock_contract="clock:fixture-completed-period-v1",
                cost_contract=cost_contract,
                engine_contract=engine_contract,
            )
        )
    definition = FixedHoldProtocolDefinition(
        family=family,
        prospective_executable_ids=tuple(
            executable.identity for executable in executables
        ),
        protocol_id=ANALOG_FIXED_HOLD_REPLAY_TRACE_PROTOCOL_ID,
        fold_ids=("fold-1",),
        invariance_keys=("profile",),
        allowed_regimes=("all",),
        dataset_sha256="1" * 64,
        material_identity="2" * 64,
        split_artifact_sha256="3" * 64,
        clock_contract="clock:fixture-completed-period-v1",
        cost_contract=cost_contract,
        producer_implementation_identities=(
            (
                "fixture_producer",
                sha256(f"producer:{generation}".encode("ascii")).hexdigest(),
            ),
        ),
        historical_context_id=OBLIGATION_ID,
        historical_prior_global_exposure_count=context_count,
        original_family_end_global_exposure_count=10,
        alpha_ppm=100_000,
        bootstrap_samples=1_000,
        block_lengths=(2,),
        monte_carlo_confidence_ppm=950_000,
        base_seed=7,
    )
    plans = tuple(
        build_fixed_hold_family_job_plan(
            definition=definition,
            artifact_namespace="fixture-replay",
            mission_id=MISSION_ID,
            study_id=study_id,
            executable_id=executable.identity,
        )
        for executable in executables
    )
    artifacts = {
        plan.plan_hash: canonical_bytes(plan.plan) for plan in plans
    }
    request = ReplayJobImplementationPreflightRequest(
        mission_id=MISSION_ID,
        protocol_id=request_protocol,
        callable_identity="fixture.fixed_hold.execute.v1",
        implementation_identity=sha256(
            f"job:{generation}".encode("ascii")
        ).hexdigest(),
        executables=tuple(executables),
        scientific_bindings=tuple(
            plan.scientific_binding() for plan in plans
        ),
        replay_obligation_ids=(OBLIGATION_ID,),
    )
    baseline = ExecutableSpec(
        display_name="fixture comparison anchor",
        components=components,
        parameters={
            "configuration_id": "comparison-anchor",
            "historical_context_prior_global_exposure_count": context_count,
            "historical_reference_executable_id": "none",
            "holding_bars": 2,
            "profile": "comparison-anchor",
            **(
                {}
                if nested_context_override is None
                else {
                    "risk_config": {
                        "historical_context_prior_global_exposure_count": (
                            nested_context_override
                        )
                    }
                }
            ),
        },
        data_contract=data_contract,
        split_contract="split:fixture-rolling-v1",
        clock_contract="clock:fixture-completed-period-v1",
        cost_contract=cost_contract,
        engine_contract=engine_contract,
    )
    chassis = ControlledStudyChassis(
        baseline_executable=baseline,
        changed_domains=(ResearchLayer.TRADE,),
        controlled_domains=(
            ResearchLayer.EXECUTION,
            ResearchLayer.LABEL,
            ResearchLayer.LIFECYCLE,
            ResearchLayer.SELECTOR,
        ),
        architecture=ArchitectureChassisSpec.from_executable(baseline),
    )
    study_payload = {
        "changed_domains": ["trade"],
        "controlled_chassis": chassis.to_identity_payload(),
        "controlled_domains": [
            "execution",
            "label",
            "lifecycle",
            "selector",
        ],
        "material_identity": "2" * 64,
        "mechanism_family": "fixture-fixed-hold-replay",
        "mission_id": MISSION_ID,
        "portfolio_action": "synthesize",
        "primary_research_layer": "trade",
        "question": {
            "causal_question": "Does the exact fixture family survive costs?",
            "changed_variables": ["trade"],
            "controlled_variables": [
                "execution",
                "label",
                "lifecycle",
                "selector",
            ],
            "done_conditions": ["all four members evaluated"],
            "evidence_modes": ["fold", "regime", "session"],
        },
        "replay_obligation_ids": [OBLIGATION_ID],
        "semantic_proposal": {
            "candidate_eligible": False,
            "historical_obligation_id": OBLIGATION_ID,
            "mechanism": "fixture-fixed-hold-replay",
            "original_study_id": "STU-8001",
        },
        "semantic_question_core_id": "semantic-question-core:" + "4" * 64,
    }
    batch_spec = BatchSpec(
        batch_id=f"BAT-{study_id.removeprefix('STU-')}",
        study_id=study_id,
        study_hash="5" * 64,
        display_name="fixture replay family",
        max_trials=4,
        max_compute_seconds=400,
        max_wall_seconds=800,
        stop_rule="stop only after the exact registered family",
        concurrent_family=ConcurrentFamilyManifest(
            evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
            executable_ids=tuple(
                sorted(executable.identity for executable in executables)
            ),
        ),
        acceptance_profile={
            "candidate_authority": "none",
            "exact_original_criteria": [
                "D02-opposite-sign-uncertainty",
                "E01-familywise-selection",
            ],
            "historical_family_authority_id": (
                "historical-family-authority:" + "c" * 64
            ),
            "historical_family_identity": family.identity,
            "replay_obligation_id": OBLIGATION_ID,
        },
        adaptive_basis={
            "causal_complexity": "one exact four-member family",
            "compute_cost": "four bounded Jobs",
            "expected_information_value": "resolve the exact replay",
            "portfolio_opportunity_cost": "other axes remain schedulable",
            "surface_curvature": "fixed family",
            "uncertainty": "one unresolved replay",
        },
    )
    return _Fixture(
        request=request,
        study_payload=study_payload,
        batch_payload={"spec": batch_spec.to_identity_payload()},
        artifacts=artifacts,
    )


def test_scientific_surface_allows_only_implementation_and_context_change() -> None:
    original = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
    )
    replacement = _fixture(
        generation=2,
        context_count=630,
        study_id="STU-9002",
    )

    original_surface = original.surface()
    replacement_surface = replacement.surface()

    assert replay_job_scientific_surface_hash(original_surface) == (
        replay_job_scientific_surface_hash(replacement_surface)
    )
    assert original_surface == replacement_surface
    original_ids = replay_executable_reference_map(
        original.request.executables
    )
    replacement_ids = replay_executable_reference_map(
        replacement.request.executables
    )
    assert set(original_ids) == set(replacement_ids)
    assert set(original_ids.values()).isdisjoint(replacement_ids.values())


@pytest.mark.parametrize(
    ("change", "expected_equal"),
    (
        ({"holding_override": 3}, False),
        ({"data_contract": "data:fixture-observed-v2"}, False),
        ({"cost_contract": "cost:fixture-exact-v2"}, False),
        ({"engine_contract": "engine:fixture-semantic-v2"}, False),
        ({"nested_context_override": 999}, False),
        ({"request_protocol": "python.source.fixture_fixed_hold.v2"}, False),
    ),
)
def test_scientific_surface_detects_research_condition_drift(
    change: dict[str, object],
    expected_equal: bool,
) -> None:
    original = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
    )
    changed = _fixture(
        generation=2,
        context_count=630,
        study_id="STU-9002",
        **change,
    )

    assert (original.surface() == changed.surface()) is expected_equal


def test_scientific_surface_rejects_modified_validation_plan() -> None:
    fixture = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
    )
    binding = fixture.request.scientific_binding_values()[0]
    plan_hash = binding["validation_plan_hash"]
    plan = fixture.artifacts[plan_hash]
    changed = plan.replace(
        b'"threshold":0',
        b'"threshold":1',
        1,
    )
    changed_hash = sha256(changed).hexdigest()
    bindings = list(fixture.request.scientific_binding_values())
    bindings[0] = {**bindings[0], "validation_plan_hash": changed_hash}
    request = ReplayJobImplementationPreflightRequest(
        mission_id=fixture.request.mission_id,
        protocol_id=fixture.request.protocol_id,
        callable_identity=fixture.request.callable_identity,
        implementation_identity=fixture.request.implementation_identity,
        executables=fixture.request.executables,
        scientific_bindings=tuple(bindings),
        replay_obligation_ids=fixture.request.replay_obligation_ids,
    )
    artifacts = {**fixture.artifacts, changed_hash: changed}

    with pytest.raises(
        ReplayJobImplementationPreflightError,
        match="differs from the fixed-hold protocol",
    ):
        derive_replay_job_scientific_surface(
            request,
            study_payload=fixture.study_payload,
            batch_payload=fixture.batch_payload,
            artifact_reader=artifacts.__getitem__,
        )


def test_scientific_surface_rejects_null_writer_context_parameter() -> None:
    fixture = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
    )
    study_payload = deepcopy(fixture.study_payload)
    study_payload["controlled_chassis"]["baseline_executable"][
        "parameters"
    ]["historical_context_prior_global_exposure_count"] = None

    with pytest.raises(
        ReplayJobImplementationPreflightError,
        match="prospective exposure context is invalid",
    ):
        derive_replay_job_scientific_surface(
            fixture.request,
            study_payload=study_payload,
            batch_payload=fixture.batch_payload,
            artifact_reader=fixture.artifacts.__getitem__,
        )


@pytest.mark.parametrize(
    "attack",
    ("old_schema", "missing_engine", "missing_architecture_engine"),
)
def test_scientific_surface_hash_rejects_incomplete_v2_skeleton(
    attack: str,
) -> None:
    surface = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
    ).surface()
    if attack == "old_schema":
        surface["schema"] = "replay_job_scientific_surface.v1"
    elif attack == "missing_engine":
        del surface["members"][0]["executable"]["engine_contract"]
    elif attack == "missing_architecture_engine":
        del surface["study"]["controlled_chassis"]["architecture"][
            "roles"
        ]["execution"]["boundary_bindings"]["engine_contract"]
    else:
        raise AssertionError(attack)

    with pytest.raises(ReplayJobImplementationPreflightError):
        replay_job_scientific_surface_hash(surface)


def test_preflight_remediation_distinguishes_restoration_from_new_identity() -> None:
    repairable = ImplementationClosureError(
        "Job source closure does not match current project source bytes",
        same_identity_repairable=True,
    )
    structural = ImplementationClosureError(
        "prospective Job source imports frozen historical reconstruction"
    )
    manifest = JobImplementationAuthorityError(
        "Job implementation evidence manifest is invalid"
    )

    assert replay_job_implementation_remediation(repairable) == (
        SAME_IDENTITY_REPAIR
    )
    assert replay_job_implementation_remediation(structural) == (
        REPLACEMENT_REQUIRED
    )
    assert replay_job_implementation_remediation(manifest) == (
        REPLACEMENT_REQUIRED
    )


def test_same_identity_repair_cannot_become_a_durable_rejection() -> None:
    fixture = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
    )
    repairable = ReplayJobImplementationPreflightResult(
        request=fixture.request,
        accepted=False,
        reason_code="source_closure_invalid",
        failure_detail=(
            "Job source closure does not match current project source bytes"
        ),
        failure_fingerprint="1" * 64,
        remediation_kind=SAME_IDENTITY_REPAIR,
    )
    replacement = ReplayJobImplementationPreflightResult(
        request=fixture.request,
        accepted=False,
        reason_code="source_closure_invalid",
        failure_detail="prospective source imports frozen reconstruction",
        failure_fingerprint="2" * 64,
        remediation_kind=REPLACEMENT_REQUIRED,
    )

    with pytest.raises(
        ReplayJobImplementationPreflightError,
        match="before a durable replay implementation decision",
    ):
        require_durable_replay_job_implementation_preflight(repairable)
    require_durable_replay_job_implementation_preflight(replacement)


_ADMISSION_AUTHORITY_DIGEST = "d" * 64
_ADMISSION_PROTOCOL_ID = "research-protocol:" + "e" * 64
_ADMISSION_PROTOCOL_EVENT_ID = "1" * 64
_ADMISSION_STUDY_EVENT_ID = "2" * 64


def _admission_protocol_record() -> IndexRecord:
    return IndexRecord(
        kind="research-protocol-activation",
        record_id=_ADMISSION_PROTOCOL_ID,
        subject="ProjectGoal:OPERATING_DIRECTION.md",
        status="active",
        fingerprint="e" * 64,
        payload={"authority_manifest_digest": _ADMISSION_AUTHORITY_DIGEST},
        authority_sequence=10,
        authority_event_id=_ADMISSION_PROTOCOL_EVENT_ID,
        authority_offset=0,
    )


def _admission_records(
    fixture: _Fixture,
    *,
    accepted: IndexRecord | None = None,
    mutate: str | None = None,
) -> tuple[IndexRecord, IndexRecord]:
    study_id = "STU-ADMISSION"
    surface = fixture.surface()
    request = fixture.request.to_identity_payload()
    source_authority = {
        "callable_module_path": "axiom_rift/research/fixture.py",
        "dependency_count": 1,
        "path_inventory_hash": "8" * 64,
        "schema": "job_implementation_source_authority.v1",
        "source_closure_hash": "9" * 64,
    }
    payload = {
        "accepted_replacement_preflight_id": (
            None if accepted is None else accepted.record_id
        ),
        "authority_manifest_digest": _ADMISSION_AUTHORITY_DIGEST,
        "batch_id": "batch:" + "b" * 64,
        "request": request,
        "research_protocol_activation_id": _ADMISSION_PROTOCOL_ID,
        "schema": "replay_implementation_admission.v1",
        "scientific_surface": surface,
        "scientific_surface_hash": replay_job_scientific_surface_hash(
            surface
        ),
        "source_closure_authority": source_authority,
        "study_id": study_id,
    }
    if mutate == "old_surface":
        payload["scientific_surface"] = {
            **surface,
            "schema": "replay_job_scientific_surface.v1",
        }
    elif mutate == "request_extra":
        payload["request"] = {**request, "forged": True}
    elif mutate == "source_schema":
        payload["source_closure_authority"] = {
            **source_authority,
            "schema": "forged.v1",
        }
    elif mutate == "batch_identity":
        payload["batch_id"] = "batch:" + "z" * 64
    elif mutate is not None:
        raise AssertionError(mutate)
    fingerprint = canonical_digest(
        domain="replay-implementation-admission",
        payload=payload,
    )
    admission_id = "replay-implementation-admission:" + fingerprint
    admission = IndexRecord(
        kind="replay-implementation-admission",
        record_id=admission_id,
        subject=f"Study:{study_id}",
        status="active",
        fingerprint=fingerprint,
        payload=payload,
        authority_sequence=20,
        authority_event_id=_ADMISSION_STUDY_EVENT_ID,
        authority_offset=0,
    )
    study = IndexRecord(
        kind="study-open",
        record_id=study_id,
        subject=f"Study:{study_id}",
        status="open",
        fingerprint="a" * 64,
        payload={
            "mission_id": fixture.request.mission_id,
            "replay_implementation_admission_id": admission_id,
            "replay_obligation_ids": list(
                fixture.request.replay_obligation_ids
            ),
        },
        authority_sequence=20,
        authority_event_id=_ADMISSION_STUDY_EVENT_ID,
        authority_offset=0,
    )
    return study, admission


class _AdmissionIndex:
    def __init__(
        self,
        records: tuple[IndexRecord, ...],
        *,
        stream_head_id: str | None = None,
    ) -> None:
        self.records = {
            (record.kind, record.record_id): record for record in records
        }
        self.stream_head_id = stream_head_id

    def get(self, kind: str, record_id: str):
        return self.records.get((kind, record_id))

    def event_head(self, stream: str):
        return (
            None
            if self.stream_head_id is None
            or not stream.startswith(
                "replay-job-implementation-preflight-replacement:"
            )
            else SimpleNamespace(record_id=self.stream_head_id)
        )


def test_writer_admission_projection_authenticates_exact_initial_surface() -> None:
    fixture = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
    )
    study, admission = _admission_records(fixture)
    index = _AdmissionIndex((study, admission))

    with patch(
        "axiom_rift.operations.research_protocol_projection."
        "require_current_research_protocol_activation",
        return_value=_admission_protocol_record(),
    ):
        assert StateWriter._study_replay_implementation_admission(
            index,  # type: ignore[arg-type]
            study_id=study.record_id,
            authority_manifest_digest=_ADMISSION_AUTHORITY_DIGEST,
        ) == admission


@pytest.mark.parametrize(
    "attack",
    ("old_surface", "request_extra", "source_schema", "batch_identity"),
)
def test_writer_admission_projection_rejects_self_hashed_forgery(
    attack: str,
) -> None:
    fixture = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
    )
    study, admission = _admission_records(fixture, mutate=attack)
    index = _AdmissionIndex((study, admission))

    with patch(
        "axiom_rift.operations.research_protocol_projection."
        "require_current_research_protocol_activation",
        return_value=_admission_protocol_record(),
    ), pytest.raises(RecoveryRequired, match="admission is malformed"):
        StateWriter._study_replay_implementation_admission(
            index,  # type: ignore[arg-type]
            study_id=study.record_id,
            authority_manifest_digest=_ADMISSION_AUTHORITY_DIGEST,
        )


def test_writer_admission_projection_rejects_stale_replacement_head() -> None:
    prior_id = "job-implementation-preflight:" + "6" * 64
    fixture = _fixture(
        generation=2,
        context_count=630,
        study_id="STU-9002",
    )
    accepted_payload = _preflight_payload(
        fixture,
        outcome="accepted",
        replacement_for=prior_id,
    )
    accepted_id = "job-implementation-preflight:" + "7" * 64
    accepted = IndexRecord(
        kind="job-implementation-preflight",
        record_id=accepted_id,
        subject=f"Mission:{fixture.request.mission_id}",
        status="accepted",
        fingerprint="7" * 64,
        payload=accepted_payload,
        event_stream=(
            "replay-job-implementation-preflight-replacement:" + prior_id
        ),
        event_sequence=1,
    )
    study, admission = _admission_records(fixture, accepted=accepted)
    index = _AdmissionIndex(
        (study, admission, accepted),
        stream_head_id="job-implementation-preflight:" + "8" * 64,
    )

    with patch(
        "axiom_rift.operations.research_protocol_projection."
        "require_current_research_protocol_activation",
        return_value=_admission_protocol_record(),
    ), pytest.raises(RecoveryRequired, match="admission is malformed"):
        StateWriter._study_replay_implementation_admission(
            index,  # type: ignore[arg-type]
            study_id=study.record_id,
            authority_manifest_digest=_ADMISSION_AUTHORITY_DIGEST,
        )


def _preflight_payload(
    fixture: _Fixture,
    *,
    outcome: str,
    replacement_for: str | None,
) -> dict[str, object]:
    surface = fixture.surface()
    accepted = outcome == "accepted"
    return {
        "callable_identity": fixture.request.callable_identity,
        "executable_ids": list(fixture.request.executable_ids),
        "executable_manifests": [
            executable.to_identity_payload()
            for executable in fixture.request.executables
        ],
        "failure_fingerprint": None if accepted else "6" * 64,
        "implementation_identity": fixture.request.implementation_identity,
        "mission_id": fixture.request.mission_id,
        "outcome": outcome,
        "protocol_id": fixture.request.protocol_id,
        "reason_code": None if accepted else "source_closure_invalid",
        "remediation_kind": None if accepted else REPLACEMENT_REQUIRED,
        "replacement_for_preflight_id": replacement_for,
        "replay_obligation_ids": list(
            fixture.request.replay_obligation_ids
        ),
        "schema": PREFLIGHT_SCHEMA,
        "scientific_surface": surface,
        "scientific_surface_hash": replay_job_scientific_surface_hash(
            surface
        ),
        "source_closure_authority": (
            {"schema": "fixture_source_closure_authority.v1"}
            if accepted
            else None
        ),
    }


def test_replacement_boundary_accepts_exact_science_and_new_implementation() -> None:
    prior_id = "job-implementation-preflight:" + "7" * 64
    original = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
    )
    replacement = _fixture(
        generation=2,
        context_count=630,
        study_id="STU-9002",
    )
    prior_payload = _preflight_payload(
        original,
        outcome="rejected",
        replacement_for=None,
    )
    replacement_payload = _preflight_payload(
        replacement,
        outcome="accepted",
        replacement_for=prior_id,
    )

    require_replacement_replay_job_scientific_surface(
        prior_preflight_id=prior_id,
        prior_payload=prior_payload,
        replacement_payload=replacement_payload,
    )
    active_payload = {
        **replacement_payload,
        "replacement_for_preflight_id": None,
    }
    require_active_replay_job_replacement_binding(
        accepted_payload=replacement_payload,
        active_payload=active_payload,
    )


def test_replacement_boundary_rejects_same_identity_recertification() -> None:
    prior_id = "job-implementation-preflight:" + "6" * 64
    fixture = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
    )
    prior_payload = _preflight_payload(
        fixture,
        outcome="rejected",
        replacement_for=None,
    )
    recertified_payload = _preflight_payload(
        fixture,
        outcome="accepted",
        replacement_for=prior_id,
    )

    with pytest.raises(
        ReplayJobImplementationPreflightError,
        match="reused an old Executable",
    ):
        require_replacement_replay_job_scientific_surface(
            prior_preflight_id=prior_id,
            prior_payload=prior_payload,
            replacement_payload=recertified_payload,
        )


@pytest.mark.parametrize(
    "attack",
    (
        "same_executables",
        "stale_pointer",
        "protocol_drift",
        "callable_drift",
        "surface_hash_forgery",
        "parameter_drift",
    ),
)
def test_replacement_boundary_rejects_identity_and_science_attacks(
    attack: str,
) -> None:
    prior_id = "job-implementation-preflight:" + "7" * 64
    original = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
    )
    replacement = _fixture(
        generation=2,
        context_count=630,
        study_id="STU-9002",
    )
    prior_payload = _preflight_payload(
        original,
        outcome="rejected",
        replacement_for=None,
    )
    replacement_payload = _preflight_payload(
        replacement,
        outcome="accepted",
        replacement_for=prior_id,
    )
    if attack == "same_executables":
        replacement_payload["executable_ids"] = prior_payload[
            "executable_ids"
        ]
        replacement_payload["executable_manifests"] = prior_payload[
            "executable_manifests"
        ]
    elif attack == "stale_pointer":
        replacement_payload["replacement_for_preflight_id"] = (
            "job-implementation-preflight:" + "8" * 64
        )
    elif attack == "protocol_drift":
        replacement_payload["protocol_id"] = "python.source.changed.v1"
    elif attack == "callable_drift":
        replacement_payload["callable_identity"] = "fixture.changed.execute.v1"
    elif attack == "surface_hash_forgery":
        replacement_payload["scientific_surface_hash"] = "9" * 64
    elif attack == "parameter_drift":
        drift = _fixture(
            generation=2,
            context_count=630,
            study_id="STU-9002",
            holding_override=3,
        )
        drift_surface = drift.surface()
        replacement_payload["scientific_surface"] = drift_surface
        replacement_payload["scientific_surface_hash"] = (
            replay_job_scientific_surface_hash(drift_surface)
        )
        replacement_payload["executable_ids"] = list(
            drift.request.executable_ids
        )
        replacement_payload["executable_manifests"] = [
            executable.to_identity_payload()
            for executable in drift.request.executables
        ]
    else:
        raise AssertionError(attack)

    with pytest.raises(
        ReplayJobImplementationPreflightError,
        match=(
            "changed its scientific surface|reused an old Executable"
        ),
    ):
        require_replacement_replay_job_scientific_surface(
            prior_preflight_id=prior_id,
            prior_payload=prior_payload,
            replacement_payload=replacement_payload,
        )


def _engine_contract(
    tag: str,
    *,
    roles: tuple[str, ...],
    runtime: tuple[str, ...] = _ENGINE_RUNTIME,
) -> str:
    role_bindings = tuple(
        f"{role}_{sha256(f'{tag}:{role}'.encode('ascii')).hexdigest()}"
        for role in roles
    )
    return ":".join(("engine", tag, *runtime, *role_bindings))


def _bind_payload_surface(
    payload: dict[str, object],
    surface: dict[str, object],
) -> None:
    payload["callable_identity"] = surface["callable_identity"]
    payload["protocol_id"] = surface["protocol_id"]
    payload["scientific_surface"] = surface
    payload["scientific_surface_hash"] = (
        replay_job_scientific_surface_hash(surface)
    )


def _strict_context_surface(
    fixture: _Fixture,
    *,
    context_count: int,
    context_subject: str,
    producer_roles: tuple[str, ...] = _OLD_PRODUCER_ROLES,
) -> dict[str, object]:
    surface = fixture.surface()
    chassis = surface["study"]["controlled_chassis"]
    executables = [
        member["executable"] for member in surface["members"]
    ] + [chassis["baseline_executable"]]
    for executable in executables:
        owner = executable["components"][1]
        owner["protocol"] = _CONTEXT_OWNER_PROTOCOL
        owner["spec"] = {
            "historical_context_adjustment_authority": (
                "context_only_never_adjustment_factor"
            ),
            "parameter_fields": [
                _CONTEXT_PARAMETER,
                _ORIGINAL_FAMILY_END_PARAMETER,
            ],
            "selection_family_scope": (
                "exact_registered_concurrent_family"
            ),
        }
        executable["parameters"][_CONTEXT_PARAMETER] = context_count
        executable["parameters"][_ORIGINAL_FAMILY_END_PARAMETER] = 10

    roles = chassis["architecture"]["roles"]
    roles["decision"]["absence"] = "none"
    roles["decision"]["component_ordinals"] = []
    roles["portfolio"]["absence"] = None
    roles["portfolio"]["component_ordinals"] = [2]
    roles["portfolio"]["parameter_bindings"] = {
        _CONTEXT_PARAMETER: context_count,
        _ORIGINAL_FAMILY_END_PARAMETER: 10,
    }
    chassis["controlled_parameter_bindings"]["portfolio"] = {
        _CONTEXT_PARAMETER: context_count,
        _ORIGINAL_FAMILY_END_PARAMETER: 10,
    }
    for member in surface["members"]:
        definition = member["validation_plan"]["protocol_definition"]
        definition["historical_context_id"] = context_subject
        definition["producer_implementation_roles"] = list(producer_roles)
        definition["protocol_id"] = _VOLATILITY_REPLAY_PROTOCOL
    return surface


def _strict_context_replacement_payloads() -> tuple[
    str,
    dict[str, object],
    dict[str, object],
]:
    prior_id = "job-implementation-preflight:" + "7" * 64
    original = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
    )
    replacement = _fixture(
        generation=2,
        context_count=630,
        study_id="STU-9002",
    )
    prior_payload = _preflight_payload(
        original,
        outcome="rejected",
        replacement_for=None,
    )
    replacement_payload = _preflight_payload(
        replacement,
        outcome="accepted",
        replacement_for=prior_id,
    )
    prior_surface = _strict_context_surface(
        original,
        context_count=626,
        context_subject=OBLIGATION_ID,
    )
    family_authority_id = replacement_payload["scientific_surface"][
        "batch"
    ]["acceptance_profile"]["historical_family_authority_id"]
    replacement_surface = _strict_context_surface(
        replacement,
        context_count=630,
        context_subject=family_authority_id,
    )
    _bind_payload_surface(prior_payload, prior_surface)
    _bind_payload_surface(replacement_payload, replacement_surface)
    return prior_id, prior_payload, replacement_payload


def test_replacement_equivalence_accepts_recognized_old_and_new_engines(
) -> None:
    prior_id = "job-implementation-preflight:" + "7" * 64
    original = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
        engine_contract=_engine_contract(
            "stu0051_volatility_duration_replay_v1",
            roles=_OLD_ENGINE_ROLES,
        ),
    )
    replacement = _fixture(
        generation=2,
        context_count=630,
        study_id="STU-9002",
        engine_contract=_engine_contract(
            "volatility_duration_fixed_hold_v1",
            roles=_NEW_ENGINE_ROLES,
        ),
    )

    require_replacement_replay_job_scientific_surface(
        prior_preflight_id=prior_id,
        prior_payload=_preflight_payload(
            original,
            outcome="rejected",
            replacement_for=None,
        ),
        replacement_payload=_preflight_payload(
            replacement,
            outcome="accepted",
            replacement_for=prior_id,
        ),
    )


@pytest.mark.parametrize(
    "attack",
    (
        "runtime_drift",
        "unknown_tag",
        "missing_role",
        "extra_role",
        "duplicate_role",
        "renamed_role",
    ),
)
def test_replacement_equivalence_rejects_engine_profile_attacks(
    attack: str,
) -> None:
    prior_id = "job-implementation-preflight:" + "7" * 64
    original_engine = _engine_contract(
        "stu0051_volatility_duration_replay_v1",
        roles=_OLD_ENGINE_ROLES,
    )
    runtime = list(_ENGINE_RUNTIME)
    roles = list(_NEW_ENGINE_ROLES)
    tag = "volatility_duration_fixed_hold_v1"
    if attack == "runtime_drift":
        runtime[0] = "python3.13.0"
    elif attack == "unknown_tag":
        tag = "volatility_duration_fixed_hold_unregistered_v1"
    elif attack == "missing_role":
        roles.remove("selection")
    elif attack == "extra_role":
        roles.append("catalog")
    elif attack == "duplicate_role":
        roles.append("adapter")
    elif attack == "renamed_role":
        roles[roles.index("selection")] = "selector"
    else:
        raise AssertionError(attack)
    replacement_engine = _engine_contract(
        tag,
        roles=tuple(roles),
        runtime=tuple(runtime),
    )
    original = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
        engine_contract=original_engine,
    )
    replacement = _fixture(
        generation=2,
        context_count=630,
        study_id="STU-9002",
        engine_contract=replacement_engine,
    )

    with pytest.raises(
        ReplayJobImplementationPreflightError,
        match="changed its scientific surface",
    ):
        require_replacement_replay_job_scientific_surface(
            prior_preflight_id=prior_id,
            prior_payload=_preflight_payload(
                original,
                outcome="rejected",
                replacement_for=None,
            ),
            replacement_payload=_preflight_payload(
                replacement,
                outcome="accepted",
                replacement_for=prior_id,
            ),
        )


def test_replacement_equivalence_rejects_producer_role_drift() -> None:
    prior_id, prior_payload, replacement_payload = (
        _strict_context_replacement_payloads()
    )
    replacement_surface = deepcopy(
        replacement_payload["scientific_surface"]
    )
    for member in replacement_surface["members"]:
        roles = member["validation_plan"]["protocol_definition"][
            "producer_implementation_roles"
        ]
        roles[roles.index("catalog_sha256")] = "catalog_reader_sha256"
    _bind_payload_surface(replacement_payload, replacement_surface)

    with pytest.raises(
        ReplayJobImplementationPreflightError,
        match="changed its scientific surface",
    ):
        require_replacement_replay_job_scientific_surface(
            prior_preflight_id=prior_id,
            prior_payload=prior_payload,
            replacement_payload=replacement_payload,
        )


def test_replacement_equivalence_accepts_obligation_and_family_context_alias(
) -> None:
    prior_id, prior_payload, replacement_payload = (
        _strict_context_replacement_payloads()
    )

    assert replay_job_scientific_equivalence_surface(
        prior_payload["scientific_surface"]
    ) == replay_job_scientific_equivalence_surface(
        replacement_payload["scientific_surface"]
    )
    require_replacement_replay_job_scientific_surface(
        prior_preflight_id=prior_id,
        prior_payload=prior_payload,
        replacement_payload=replacement_payload,
    )


@pytest.mark.parametrize(
    "attack",
    (
        "unrelated_authority",
        "unrelated_component",
        "unrelated_role",
        "unrelated_group",
        "nested_context",
        "original_family_end_drift",
    ),
)
def test_replacement_equivalence_rejects_context_exclusion_attacks(
    attack: str,
) -> None:
    prior_id, prior_payload, replacement_payload = (
        _strict_context_replacement_payloads()
    )
    replacement_surface = deepcopy(
        replacement_payload["scientific_surface"]
    )
    chassis = replacement_surface["study"]["controlled_chassis"]
    if attack == "unrelated_authority":
        for member in replacement_surface["members"]:
            member["validation_plan"]["protocol_definition"][
                "historical_context_id"
            ] = "historical-family-authority:" + "d" * 64
    elif attack == "unrelated_component":
        replacement_surface["members"][0]["executable"]["components"][0][
            "spec"
        ]["parameter_fields"].append(_CONTEXT_PARAMETER)
    elif attack == "unrelated_role":
        chassis["architecture"]["roles"]["label"][
            "parameter_bindings"
        ][_CONTEXT_PARAMETER] = 630
    elif attack == "unrelated_group":
        chassis["controlled_parameter_bindings"]["label"][
            _CONTEXT_PARAMETER
        ] = 630
    elif attack == "nested_context":
        replacement_surface["members"][0]["executable"]["parameters"][
            "risk_config"
        ] = {_CONTEXT_PARAMETER: 630}
    elif attack == "original_family_end_drift":
        for member in replacement_surface["members"]:
            member["validation_plan"]["protocol_definition"][
                _ORIGINAL_FAMILY_END_PARAMETER
            ] = 11
            member["executable"]["parameters"][
                _ORIGINAL_FAMILY_END_PARAMETER
            ] = 11
        chassis["baseline_executable"]["parameters"][
            _ORIGINAL_FAMILY_END_PARAMETER
        ] = 11
        chassis["controlled_parameter_bindings"]["portfolio"][
            _ORIGINAL_FAMILY_END_PARAMETER
        ] = 11
        chassis["architecture"]["roles"]["portfolio"][
            "parameter_bindings"
        ][_ORIGINAL_FAMILY_END_PARAMETER] = 11
    else:
        raise AssertionError(attack)
    _bind_payload_surface(replacement_payload, replacement_surface)

    with pytest.raises(
        ReplayJobImplementationPreflightError,
        match=(
            "changed its scientific surface|historical context|"
            "exposure context|original family exposure"
        ),
    ):
        require_replacement_replay_job_scientific_surface(
            prior_preflight_id=prior_id,
            prior_payload=prior_payload,
            replacement_payload=replacement_payload,
        )


@pytest.mark.parametrize(
    ("field", "replacement_value"),
    (
        ("callable_identity", "fixture.fixed_hold.execute.v2"),
        ("protocol_id", "python.source.fixture_fixed_hold.v2"),
    ),
)
def test_replacement_equivalence_accepts_job_technical_identity_change(
    field: str,
    replacement_value: str,
) -> None:
    prior_id = "job-implementation-preflight:" + "7" * 64
    original = _fixture(
        generation=1,
        context_count=626,
        study_id="STU-9001",
    )
    replacement = _fixture(
        generation=2,
        context_count=630,
        study_id="STU-9002",
    )
    prior_payload = _preflight_payload(
        original,
        outcome="rejected",
        replacement_for=None,
    )
    replacement_payload = _preflight_payload(
        replacement,
        outcome="accepted",
        replacement_for=prior_id,
    )
    replacement_surface = deepcopy(
        replacement_payload["scientific_surface"]
    )
    replacement_surface[field] = replacement_value
    _bind_payload_surface(replacement_payload, replacement_surface)

    require_replacement_replay_job_scientific_surface(
        prior_preflight_id=prior_id,
        prior_payload=prior_payload,
        replacement_payload=replacement_payload,
    )


def _tamper_study_key(
    study_payload: dict[str, object],
    key: str,
) -> None:
    if key == "changed_domains":
        study_payload[key] = ["label"]
    elif key == "controlled_chassis":
        chassis = study_payload[key]
        chassis["baseline_executable"]["engine_contract"] = (
            "engine:fixture-semantic-v2"
        )
        chassis["architecture"]["roles"]["execution"][
            "boundary_bindings"
        ]["engine_contract"] = "engine:fixture-semantic-v2"
    elif key == "controlled_domains":
        study_payload[key] = ["execution", "label", "lifecycle"]
    elif key == "material_identity":
        study_payload[key] = "7" * 64
    elif key == "mechanism_family":
        study_payload[key] = "fixture-fixed-hold-replay-tampered"
    elif key == "mission_id":
        study_payload[key] = "MIS-9002"
    elif key == "portfolio_action":
        study_payload[key] = "explore"
    elif key == "primary_research_layer":
        study_payload[key] = "label"
    elif key == "question":
        study_payload[key]["causal_question"] = "A different question?"
    elif key == "replay_obligation_ids":
        study_payload[key] = [
            "historical-replay-obligation:" + "e" * 64
        ]
    elif key == "semantic_proposal":
        study_payload[key]["mechanism"] = "different-mechanism"
    elif key == "semantic_question_core_id":
        study_payload[key] = "semantic-question-core:" + "f" * 64
    else:
        raise AssertionError(key)


def test_replacement_study_semantics_accepts_exact_authority_payload() -> None:
    fixture = _fixture(
        generation=2,
        context_count=630,
        study_id="STU-9002",
    )
    accepted_payload = _preflight_payload(
        fixture,
        outcome="accepted",
        replacement_for="job-implementation-preflight:" + "7" * 64,
    )

    assert tuple(fixture.study_payload) == _STUDY_AUTHORITY_KEYS
    require_replacement_replay_study_semantics(
        accepted_payload=accepted_payload,
        study_payload=fixture.study_payload,
    )


@pytest.mark.parametrize("key", _STUDY_AUTHORITY_KEYS)
def test_replacement_study_semantics_rejects_each_authority_key_tamper(
    key: str,
) -> None:
    fixture = _fixture(
        generation=2,
        context_count=630,
        study_id="STU-9002",
    )
    accepted_payload = _preflight_payload(
        fixture,
        outcome="accepted",
        replacement_for="job-implementation-preflight:" + "7" * 64,
    )
    study_payload = deepcopy(fixture.study_payload)
    _tamper_study_key(study_payload, key)

    with pytest.raises(
        ReplayJobImplementationPreflightError,
        match=(
            "differs from its accepted authority|"
            "changed its scientific semantics"
        ),
    ):
        require_replacement_replay_study_semantics(
            accepted_payload=accepted_payload,
            study_payload=study_payload,
        )
