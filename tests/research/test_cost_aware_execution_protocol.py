from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.validation import EvidenceValidationError
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_ALPHA_PPM,
    COST_AWARE_EXECUTION_BASE_SEED,
    COST_AWARE_EXECUTION_BLOCK_LENGTHS,
    COST_AWARE_EXECUTION_BOOTSTRAP_SAMPLES,
    COST_AWARE_EXECUTION_CONTROL_DELTA_METRIC,
    COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID,
    COST_AWARE_EXECUTION_CONTROL_PVALUE_METRIC,
    COST_AWARE_EXECUTION_HISTORICAL_CONTEXT_ADJUSTMENT_AUTHORITY,
    COST_AWARE_EXECUTION_MULTIPLICITY_METHOD,
    COST_AWARE_EXECUTION_MONTE_CARLO_CONFIDENCE_PPM,
    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
    COST_AWARE_EXECUTION_PROTOCOL_DEFINITION_SCHEMA,
    COST_AWARE_EXECUTION_PROTOCOL_ID,
    COST_AWARE_EXECUTION_REPLAY_CLAIMS,
    COST_AWARE_EXECUTION_REPLAY_CRITERIA,
    COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES,
    COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID,
    CostAwareExecutionProtocolDefinition,
    CostAwareExecutionProtocolError,
    build_cost_aware_execution_validation_plan,
    cost_aware_execution_multiplicity_registrations,
    cost_aware_execution_protocol_definition,
    cost_aware_execution_protocol_definition_from_manifest,
    cost_aware_execution_subject_inference_families,
)
from axiom_rift.research.historical_family_stu0070 import (
    STU0070_HISTORICAL_FAMILY,
)
from axiom_rift.research.replay_family_job import ReplayFamilyDefinition
from axiom_rift.research.scientific_trace import (
    ATOMIC_TRACE_PROOF_KIND,
    CALCULATION_PROOF_KIND,
    SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
    SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_VALIDATION_PLAN_V2_SCHEMA,
    build_validation_plan_v2,
    multiplicity_family_registration_hash,
)


SYNTHETIC_CONTROL_EXECUTABLE_ID = "executable:" + "1" * 64
SYNTHETIC_TARGET_EXECUTABLE_ID = "executable:" + "2" * 64
SYNTHETIC_OTHER_EXECUTABLE_ID = "executable:" + "3" * 64


@pytest.fixture
def definition() -> CostAwareExecutionProtocolDefinition:
    return cost_aware_execution_protocol_definition(
        historical_family=STU0070_HISTORICAL_FAMILY,
        prospective_control_executable_id=SYNTHETIC_CONTROL_EXECUTABLE_ID,
        prospective_target_executable_id=SYNTHETIC_TARGET_EXECUTABLE_ID,
    )


def test_definition_wraps_exact_historical_pair_with_explicit_roles(
    definition: CostAwareExecutionProtocolDefinition,
) -> None:
    assert definition.protocol_id == COST_AWARE_EXECUTION_PROTOCOL_ID
    assert definition.historical_family is STU0070_HISTORICAL_FAMILY
    assert definition.historical_family.family_size == 2
    assert definition.prospective_executable_ids == (
        SYNTHETIC_CONTROL_EXECUTABLE_ID,
        SYNTHETIC_TARGET_EXECUTABLE_ID,
    )

    members = definition.member_bindings
    assert tuple(item.historical_ordinal for item in members) == (1, 2)
    assert tuple(item.role for item in members) == ("control", "target")
    assert tuple(item.execution_policy for item in members) == (
        "unconditional_next_open",
        "causal_spread_abstention",
    )
    assert tuple(item.historical_executable_id for item in members) == (
        COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID,
        COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID,
    )
    assert tuple(item.prospective_executable_id for item in members) == (
        SYNTHETIC_CONTROL_EXECUTABLE_ID,
        SYNTHETIC_TARGET_EXECUTABLE_ID,
    )

    manifest = definition.manifest()
    assert manifest["schema"] == COST_AWARE_EXECUTION_PROTOCOL_DEFINITION_SCHEMA
    assert manifest["historical_family"] == STU0070_HISTORICAL_FAMILY.manifest()
    assert len(manifest["members"]) == 2
    assert manifest["prospective_control_executable_id"] == (
        SYNTHETIC_CONTROL_EXECUTABLE_ID
    )
    assert manifest["prospective_target_executable_id"] == (
        SYNTHETIC_TARGET_EXECUTABLE_ID
    )


def test_prospective_pair_is_caller_supplied_and_identity_bound() -> None:
    first = cost_aware_execution_protocol_definition(
        historical_family=STU0070_HISTORICAL_FAMILY,
        prospective_control_executable_id=SYNTHETIC_CONTROL_EXECUTABLE_ID,
        prospective_target_executable_id=SYNTHETIC_TARGET_EXECUTABLE_ID,
    )
    repeat = cost_aware_execution_protocol_definition(
        historical_family=STU0070_HISTORICAL_FAMILY,
        prospective_control_executable_id=SYNTHETIC_CONTROL_EXECUTABLE_ID,
        prospective_target_executable_id=SYNTHETIC_TARGET_EXECUTABLE_ID,
    )
    changed = cost_aware_execution_protocol_definition(
        historical_family=STU0070_HISTORICAL_FAMILY,
        prospective_control_executable_id=SYNTHETIC_CONTROL_EXECUTABLE_ID,
        prospective_target_executable_id=SYNTHETIC_OTHER_EXECUTABLE_ID,
    )
    assert first.identity == repeat.identity
    assert first.manifest() == repeat.manifest()
    assert changed.identity != first.identity
    # Prospective member identities remain audit-bound, while the statistical
    # family and contrast identify the immutable historical question.  This
    # prevents context-only exposure changes from perturbing bootstrap seeds.
    assert changed.prospective_family_id == first.prospective_family_id
    assert (
        changed.primary_control_contrast_id
        == first.primary_control_contrast_id
    )
    first_registrations = cost_aware_execution_multiplicity_registrations(
        first,
        first.prospective_control_executable_id,
    )
    changed_registrations = cost_aware_execution_multiplicity_registrations(
        changed,
        changed.prospective_control_executable_id,
    )
    assert first_registrations[0] == changed_registrations[0]
    assert (
        first_registrations[1]["family_registration_hash"]
        != changed_registrations[1]["family_registration_hash"]
    )


@pytest.mark.parametrize(
    ("control_id", "target_id"),
    (
        ("not-an-executable", SYNTHETIC_TARGET_EXECUTABLE_ID),
        (SYNTHETIC_CONTROL_EXECUTABLE_ID, "executable:" + "A" * 64),
        (SYNTHETIC_CONTROL_EXECUTABLE_ID, SYNTHETIC_CONTROL_EXECUTABLE_ID),
    ),
)
def test_definition_rejects_invalid_or_collapsed_prospective_pair(
    control_id: str,
    target_id: str,
) -> None:
    with pytest.raises(CostAwareExecutionProtocolError):
        cost_aware_execution_protocol_definition(
            historical_family=STU0070_HISTORICAL_FAMILY,
            prospective_control_executable_id=control_id,
            prospective_target_executable_id=target_id,
        )


def test_replay_criteria_seal_exact_modes_roles_and_metrics(
    definition: CostAwareExecutionProtocolDefinition,
) -> None:
    criteria = definition.criteria
    assert len(criteria) == 18
    assert criteria == tuple(dict(item) for item in COST_AWARE_EXECUTION_REPLAY_CRITERIA)
    assert tuple((item["claim_id"], item["criterion_id"]) for item in criteria) == tuple(
        sorted((item["claim_id"], item["criterion_id"]) for item in criteria)
    )
    assert definition.planned_claims == COST_AWARE_EXECUTION_REPLAY_CLAIMS
    assert definition.evidence_modes == COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES

    by_id = {item["criterion_id"]: item for item in criteria}
    expected_modes = {
        "A01-minimum-trades": "cost_and_execution",
        "A02-positive-density": "cost_and_execution",
        "A03-profit-day-concentration": "cost_and_execution",
        "B01-positive-native-cost": "cost_and_execution",
        "B02-fold-profit-factor": "cost_and_execution",
        "B03-slippage-stress": "sensitivity_or_stress",
        "B04-monthly-realized-drawdown-share": "cost_and_execution",
        "C01-feature-prefix-invariance": "causal_contrast",
        "C02-decision-append-invariance": "causal_contrast",
        "C03-decision-time-causality": "causal_contrast",
        "C04-resolved-cost": "cost_and_execution",
        "C05-finite-metrics": "causal_contrast",
        "D03-primary-control": "causal_contrast",
        "D04-primary-control-uncertainty": "causal_contrast",
        "E01-familywise-selection": "temporal_stability",
        "F01-evaluable-folds": "temporal_stability",
        "F02-winning-folds": "temporal_stability",
        "F03-positive-regimes": "temporal_stability",
    }
    assert {
        criterion_id: item["evidence_mode"] for criterion_id, item in by_id.items()
    } == expected_modes

    validity = {
        "C01-feature-prefix-invariance",
        "C02-decision-append-invariance",
        "C03-decision-time-causality",
        "C04-resolved-cost",
        "C05-finite-metrics",
    }
    multiplicity = {
        "D04-primary-control-uncertainty",
        "E01-familywise-selection",
    }
    risk_diagnostic = {"B04-monthly-realized-drawdown-share"}
    assert {item["criterion_id"] for item in criteria if item["decision_role"] == "validity"} == validity
    assert {item["criterion_id"] for item in criteria if item["decision_role"] == "multiplicity"} == multiplicity
    assert {item["criterion_id"] for item in criteria if item["decision_role"] == "risk_diagnostic"} == risk_diagnostic
    assert all(
        item["decision_role"] == "component"
        for item in criteria
        if item["criterion_id"] not in validity | multiplicity | risk_diagnostic
    )
    assert by_id["D03-primary-control"]["metric"] == (
        COST_AWARE_EXECUTION_CONTROL_DELTA_METRIC
    )
    assert by_id["D04-primary-control-uncertainty"]["metric"] == (
        COST_AWARE_EXECUTION_CONTROL_PVALUE_METRIC
    )
    assert "D01-opposite-sign-control" not in by_id
    assert "D02-opposite-sign-uncertainty" not in by_id


@pytest.mark.parametrize(
    "subject_executable_id",
    (SYNTHETIC_CONTROL_EXECUTABLE_ID, SYNTHETIC_TARGET_EXECUTABLE_ID),
)
def test_subject_inference_families_are_one_contrast_and_two_policies(
    definition: CostAwareExecutionProtocolDefinition,
    subject_executable_id: str,
) -> None:
    d04, e01 = cost_aware_execution_subject_inference_families(
        definition,
        subject_executable_id,
    )
    assert d04["criterion_id"] == "D04-primary-control-uncertainty"
    assert d04["family_size"] == 1
    assert d04["ordered_member_ids"] == [definition.primary_control_contrast_id]
    assert d04["member_id"] == definition.primary_control_contrast_id
    assert d04["inference_role"] == "primary_control_contrast"

    assert e01["criterion_id"] == "E01-familywise-selection"
    assert e01["family_size"] == 2
    assert e01["ordered_member_ids"] == [
        SYNTHETIC_CONTROL_EXECUTABLE_ID,
        SYNTHETIC_TARGET_EXECUTABLE_ID,
    ]
    assert e01["member_id"] == subject_executable_id
    assert e01["inference_role"] == "concurrent_policy_selection"


def test_selection_inference_order_is_canonical_not_role_order() -> None:
    definition = cost_aware_execution_protocol_definition(
        historical_family=STU0070_HISTORICAL_FAMILY,
        prospective_control_executable_id="executable:" + "f" * 64,
        prospective_target_executable_id="executable:" + "0" * 64,
    )
    _, selection = cost_aware_execution_subject_inference_families(
        definition,
        definition.prospective_control_executable_id,
    )
    assert definition.prospective_executable_ids == (
        "executable:" + "f" * 64,
        "executable:" + "0" * 64,
    )
    assert selection["ordered_member_ids"] == [
        "executable:" + "0" * 64,
        "executable:" + "f" * 64,
    ]


@pytest.mark.parametrize(
    "subject_executable_id",
    (SYNTHETIC_CONTROL_EXECUTABLE_ID, SYNTHETIC_TARGET_EXECUTABLE_ID),
)
def test_multiplicity_registrations_match_scientific_v2_hashes(
    definition: CostAwareExecutionProtocolDefinition,
    subject_executable_id: str,
) -> None:
    registrations = cost_aware_execution_multiplicity_registrations(
        definition,
        subject_executable_id,
    )
    assert tuple(item["criterion_id"] for item in registrations) == (
        "D04-primary-control-uncertainty",
        "E01-familywise-selection",
    )
    assert tuple(item["family_size"] for item in registrations) == (1, 2)
    for registration in registrations:
        assert registration["alpha_ppm"] == COST_AWARE_EXECUTION_ALPHA_PPM
        assert registration["method"] == COST_AWARE_EXECUTION_MULTIPLICITY_METHOD
        assert registration["family_registration_hash"] == (
            multiplicity_family_registration_hash(
                family_id=registration["family_id"],
                alpha_ppm=registration["alpha_ppm"],
                method=registration["method"],
                ordered_member_ids=tuple(registration["ordered_member_ids"]),
            )
        )
    assert registrations[0]["member_id"] == definition.primary_control_contrast_id
    assert registrations[1]["member_id"] == subject_executable_id


@pytest.mark.parametrize(
    "subject_executable_id",
    (SYNTHETIC_OTHER_EXECUTABLE_ID, "not-an-executable"),
)
def test_subject_inference_rejects_implicit_or_external_subjects(
    definition: CostAwareExecutionProtocolDefinition,
    subject_executable_id: str,
) -> None:
    with pytest.raises(CostAwareExecutionProtocolError):
        cost_aware_execution_subject_inference_families(
            definition,
            subject_executable_id,
        )
    with pytest.raises(CostAwareExecutionProtocolError):
        cost_aware_execution_multiplicity_registrations(
            definition,
            subject_executable_id,
        )


def _matching_paths(value: object, needle: object) -> list[tuple[object, ...]]:
    paths: list[tuple[object, ...]] = []

    def visit(item: object, path: tuple[object, ...]) -> None:
        if type(item) is dict:
            for key, child in item.items():
                visit(child, (*path, key))
        elif type(item) is list:
            for index, child in enumerate(item):
                visit(child, (*path, index))
        elif item == needle:
            paths.append(path)

    visit(value, ())
    return paths


@pytest.mark.parametrize(
    "subject_executable_id",
    (SYNTHETIC_CONTROL_EXECUTABLE_ID, SYNTHETIC_TARGET_EXECUTABLE_ID),
)
def test_validation_plan_is_exactly_subject_bound(
    definition: CostAwareExecutionProtocolDefinition,
    subject_executable_id: str,
) -> None:
    output_names = {
        "calculation": "scientific/STU-TEST/calculation-proof.json",
        "trace": "scientific/STU-TEST/evaluation-trace.json",
    }
    plan = build_cost_aware_execution_validation_plan(
        definition=definition,
        mission_id="mission:cost-aware-execution-test",
        executable_id=subject_executable_id,
        output_names=output_names,
    )
    assert plan["schema"] == SCIENTIFIC_VALIDATION_PLAN_V2_SCHEMA
    assert plan["mission_id"] == "mission:cost-aware-execution-test"
    assert plan["executable_id"] == subject_executable_id
    assert plan["evidence_depth"] == "discovery"
    assert plan["candidate_eligible_on_pass"] is False
    assert plan["planned_claims"] == list(COST_AWARE_EXECUTION_REPLAY_CLAIMS)
    assert plan["evidence_modes"] == list(
        COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES
    )
    assert plan["criteria"] == [
        dict(item) for item in COST_AWARE_EXECUTION_REPLAY_CRITERIA
    ]
    assert plan["protocol_definition"] == definition.manifest()
    assert "adjudication_profile" not in plan["protocol_definition"]
    assert plan["adjudication_profile"]["multiplicity"] == list(
        cost_aware_execution_multiplicity_registrations(
            definition,
            subject_executable_id,
        )
    )
    assert plan["adjudication_profile"]["multiplicity"][0]["member_id"] == (
        definition.primary_control_contrast_id
    )
    assert plan["adjudication_profile"]["multiplicity"][1]["member_id"] == (
        subject_executable_id
    )

    requirements = plan["proof_requirements"]
    assert len(requirements) == 8
    by_mode: dict[str, set[tuple[str, str, str]]] = {}
    for item in requirements:
        by_mode.setdefault(item["evidence_mode"], set()).add(
            (
                item["proof_kind"],
                item["artifact_schema"],
                item["output_name"],
            )
        )
    assert set(by_mode) == set(COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES)
    for pairs in by_mode.values():
        assert pairs == {
            (
                ATOMIC_TRACE_PROOF_KIND,
                SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
                output_names["trace"],
            ),
            (
                CALCULATION_PROOF_KIND,
                SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
                output_names["calculation"],
            ),
        }
    assert _matching_paths(
        plan,
        COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
    ) == [
        (
            "protocol_definition",
            "inference",
            "original_family_end_global_exposure_count",
        )
    ]
    canonical_bytes(plan)


def test_validation_plan_rejects_external_subject_and_ambiguous_outputs(
    definition: CostAwareExecutionProtocolDefinition,
) -> None:
    outputs = {
        "calculation": "scientific/STU-TEST/calculation-proof.json",
        "trace": "scientific/STU-TEST/evaluation-trace.json",
    }
    with pytest.raises(CostAwareExecutionProtocolError):
        build_cost_aware_execution_validation_plan(
            definition=definition,
            mission_id="mission:cost-aware-execution-test",
            executable_id=SYNTHETIC_OTHER_EXECUTABLE_ID,
            output_names=outputs,
        )
    with pytest.raises(CostAwareExecutionProtocolError):
        build_cost_aware_execution_validation_plan(
            definition=definition,
            mission_id="mission:cost-aware-execution-test",
            executable_id=SYNTHETIC_TARGET_EXECUTABLE_ID,
            output_names={"trace": "scientific/STU-TEST/trace.json"},
        )
    with pytest.raises(CostAwareExecutionProtocolError):
        build_cost_aware_execution_validation_plan(
            definition=definition,
            mission_id="mission:cost-aware-execution-test",
            executable_id=SYNTHETIC_TARGET_EXECUTABLE_ID,
            output_names={
                "calculation": "scientific/STU-TEST/same.json",
                "trace": "scientific/STU-TEST/same.json",
            },
        )


def _rebuild_validation_plan(plan: dict[str, Any]) -> dict[str, object]:
    return build_validation_plan_v2(
        mission_id=plan["mission_id"],
        executable_id=plan["executable_id"],
        evidence_depth=plan["evidence_depth"],
        planned_claims=tuple(plan["planned_claims"]),
        evidence_modes=tuple(plan["evidence_modes"]),
        criteria=tuple(plan["criteria"]),
        adjudication_profile=plan["adjudication_profile"],
        proof_requirements=tuple(plan["proof_requirements"]),
        candidate_eligible_on_pass=plan["candidate_eligible_on_pass"],
        protocol_definition=plan["protocol_definition"],
    )


def test_central_plan_boundary_rejects_protocol_binding_drift(
    definition: CostAwareExecutionProtocolDefinition,
) -> None:
    plan = build_cost_aware_execution_validation_plan(
        definition=definition,
        mission_id="mission:cost-aware-execution-test",
        executable_id=SYNTHETIC_TARGET_EXECUTABLE_ID,
        output_names={
            "calculation": "scientific/STU-TEST/calculation-proof.json",
            "trace": "scientific/STU-TEST/evaluation-trace.json",
        },
    )
    variants: list[dict[str, Any]] = []

    outside_subject = deepcopy(plan)
    outside_subject["executable_id"] = SYNTHETIC_OTHER_EXECUTABLE_ID
    variants.append(outside_subject)

    wrong_registered_subject = deepcopy(plan)
    wrong_registered_subject["adjudication_profile"]["multiplicity"][1][
        "member_id"
    ] = SYNTHETIC_CONTROL_EXECUTABLE_ID
    variants.append(wrong_registered_subject)

    altered_criterion = deepcopy(plan)
    altered_criterion["criteria"][0]["evidence_mode"] = "causal_contrast"
    variants.append(altered_criterion)

    confirmation = deepcopy(plan)
    confirmation["evidence_depth"] = "confirmation"
    variants.append(confirmation)

    promotion_drift = deepcopy(plan)
    promotion_drift["adjudication_profile"]["promotion_criterion_ids"] = [
        "A01-minimum-trades"
    ]
    variants.append(promotion_drift)

    for tampered in variants:
        with pytest.raises(EvidenceValidationError):
            _rebuild_validation_plan(tampered)


def test_original_family_end_530_is_context_only_and_never_an_adjustment_factor(
    definition: CostAwareExecutionProtocolDefinition,
) -> None:
    manifest = definition.manifest()
    inference = manifest["inference"]
    assert inference["original_family_end_global_exposure_count"] == (
        COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
    )
    assert inference["historical_context_adjustment_authority"] == (
        COST_AWARE_EXECUTION_HISTORICAL_CONTEXT_ADJUSTMENT_AUTHORITY
    )
    assert inference["base_seed"] == COST_AWARE_EXECUTION_BASE_SEED
    assert inference["block_lengths"] == list(
        COST_AWARE_EXECUTION_BLOCK_LENGTHS
    )
    assert inference["bootstrap_samples"] == (
        COST_AWARE_EXECUTION_BOOTSTRAP_SAMPLES
    )
    assert inference["monte_carlo_confidence_ppm"] == (
        COST_AWARE_EXECUTION_MONTE_CARLO_CONFIDENCE_PPM
    )
    assert "historical_prior_global_exposure_count" not in inference
    assert inference["primary_control_contrast_family_size"] == 1
    assert inference["selection_family_size"] == 2
    assert _matching_paths(
        manifest,
        COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
    ) == [
        ("inference", "original_family_end_global_exposure_count")
    ]
    registrations = cost_aware_execution_multiplicity_registrations(
        definition,
        SYNTHETIC_TARGET_EXECUTABLE_ID,
    )
    assert all(item["family_size"] in {1, 2} for item in registrations)
    assert all(
        COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        not in item.values()
        for item in registrations
    )
    assert all(
        "historical" not in key
        for item in registrations
        for key in item
    )


def test_manifest_round_trip_is_canonical_and_identity_stable(
    definition: CostAwareExecutionProtocolDefinition,
) -> None:
    manifest = definition.manifest()
    normalized = parse_canonical(canonical_bytes(manifest))
    parsed = cost_aware_execution_protocol_definition_from_manifest(normalized)
    assert parsed == definition
    assert parsed.identity == definition.identity
    assert parsed.manifest() == manifest
    assert isinstance(parsed, ReplayFamilyDefinition)
    assert parsed.family == STU0070_HISTORICAL_FAMILY


def test_parser_rejects_any_authority_drift(
    definition: CostAwareExecutionProtocolDefinition,
) -> None:
    mutations: list[tuple[tuple[object, ...], Any]] = [
        (("protocol_id",), "cost_aware_execution.paired_policy.invalid.v1"),
        (("prospective_family_id",), "family:" + "0" * 64),
        (("inference", "selection_family_size"), 530),
        (("inference", "base_seed"), 0),
        (("inference", "block_lengths"), [5, 10]),
        (("inference", "bootstrap_samples"), 1),
        (("inference", "monte_carlo_confidence_ppm"), 950_000),
        (("inference", "primary_control_contrast_family_size"), 2),
        (
            ("inference", "historical_context_adjustment_authority"),
            "bonferroni_global_history",
        ),
        (("members", 0, "role"), "target"),
        (("criteria", 0, "evidence_mode"), "extreme_or_boundary"),
        (
            ("historical_family", "original_study_id"),
            "STU-9999",
        ),
    ]
    for path, replacement in mutations:
        tampered = deepcopy(definition.manifest())
        target: Any = tampered
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = replacement
        with pytest.raises(CostAwareExecutionProtocolError):
            cost_aware_execution_protocol_definition_from_manifest(tampered)

    extra = deepcopy(definition.manifest())
    extra["ambient_callback"] = "run"
    with pytest.raises(CostAwareExecutionProtocolError):
        cost_aware_execution_protocol_definition_from_manifest(extra)


def test_manifest_is_data_only_without_ambient_execution_authority(
    definition: CostAwareExecutionProtocolDefinition,
) -> None:
    manifest = definition.manifest()
    forbidden_key_fragments = (
        "callback",
        "callable",
        "implementation",
        "module",
        "producer",
    )
    forbidden_value_fragments = ("@sha256:", "axiom_rift.", ".py")

    def visit(value: object) -> None:
        if type(value) is dict:
            for key, item in value.items():
                assert not any(fragment in key for fragment in forbidden_key_fragments)
                visit(item)
        elif type(value) is list:
            for item in value:
                visit(item)
        elif type(value) is str:
            assert value.isascii()
            assert not any(fragment in value for fragment in forbidden_value_fragments)
        else:
            assert type(value) in {int, bool}

    visit(manifest)
    canonical_bytes(manifest)
