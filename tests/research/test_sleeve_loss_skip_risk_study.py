from __future__ import annotations

from hashlib import sha256

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.prospective_job_materialization import (
    prospective_job_dependency_paths,
    prospective_job_implementation_artifact,
    prospective_job_implementation_sha256,
    prospective_job_source_closure_artifact,
)
from axiom_rift.operations.validation import (
    EvidenceValidationRequest,
    EvidenceValidatorRegistry,
    ValidationArtifact,
)
from axiom_rift.research.prospective_pair_trace import (
    build_prospective_pair_calculation,
)
from axiom_rift.research.sleeve_loss_skip_risk_runtime import (
    CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL,
    sleeve_loss_skip_risk_runtime_path,
)
from axiom_rift.research.sleeve_loss_skip_risk_study import (
    SleeveLossSkipRiskJobPlan,
    build_measurement,
    build_result,
    build_sleeve_loss_skip_risk_job_plan,
    build_sleeve_loss_skip_risk_validation_plan,
    output_names,
    sleeve_loss_skip_risk_multiplicity_registrations,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    ScientificAdjudicationValidatorV2,
)
from tests.research.test_prospective_pair_trace import (
    JOB_HASH,
    JOB_ID,
    MISSION_ID,
    SUBJECT_ID,
    _definition,
    _trace,
)


def test_job_implementation_closes_current_callable_source() -> None:
    entry_path = sleeve_loss_skip_risk_runtime_path()
    source_root = entry_path.parents[2]
    paths = prospective_job_dependency_paths(entry_path)
    assert paths
    assert entry_path in paths
    assert any(path.name == "sleeve_loss_skip_risk_study.py" for path in paths)
    assert not any(
        path.name == "prospective_job_materialization.py" for path in paths
    )
    closure = parse_canonical(
        prospective_job_source_closure_artifact(
            callable_identity=CALLABLE_IDENTITY,
            dependency_paths=paths,
            source_root=source_root,
        )
    )
    assert closure["schema"] == "job_implementation_source_closure.v1"
    assert any(
        row["path"].endswith("sleeve_loss_skip_risk_runtime.py")
        for row in closure["dependencies"]
    )
    manifest = prospective_job_implementation_artifact(
        callable_identity=CALLABLE_IDENTITY,
        protocol=JOB_IMPLEMENTATION_PROTOCOL,
        dependency_paths=paths,
        source_root=source_root,
    )
    assert sha256(manifest).hexdigest() == prospective_job_implementation_sha256(
        entry_path=entry_path,
        callable_identity=CALLABLE_IDENTITY,
        protocol=JOB_IMPLEMENTATION_PROTOCOL,
        source_root=source_root,
    )


def test_selection_registration_uses_canonical_family_order() -> None:
    definition = _definition()
    subject_id = definition.prospective_executable_ids[0]
    registrations = sleeve_loss_skip_risk_multiplicity_registrations(
        definition=definition,
        subject_executable_id=subject_id,
    )
    selection = next(
        item
        for item in registrations
        if item["criterion_id"] == "E01-familywise-selection"
    )
    assert selection["ordered_member_ids"] == sorted(
        definition.prospective_executable_ids
    )


def test_job_plan_accepts_one_verified_family_definition(monkeypatch) -> None:
    definition = _definition()
    calls = 0

    def current_definition(_repository_root):
        nonlocal calls
        calls += 1
        return definition

    monkeypatch.setattr(
        "axiom_rift.research.sleeve_loss_skip_risk_study."
        "build_sleeve_loss_skip_risk_protocol_definition",
        current_definition,
    )
    plan = build_sleeve_loss_skip_risk_job_plan(
        repository_root=".",
        mission_id=MISSION_ID,
        study_id="STU-PROSPECTIVE-PAIR",
        executable_id=definition.prospective_executable_ids[0],
        definition=definition,
    )

    assert calls == 0
    assert plan.definition == definition


def test_prospective_pair_plan_and_atomic_proofs_validate_end_to_end(
    tmp_path,
) -> None:
    definition = _definition()
    names = output_names(SUBJECT_ID, study_id="STU-PROSPECTIVE-PAIR")
    plan = build_sleeve_loss_skip_risk_validation_plan(
        definition=definition,
        mission_id=MISSION_ID,
        executable_id=SUBJECT_ID,
        names=names,
    )
    scoped = SleeveLossSkipRiskJobPlan(
        mission_id=MISSION_ID,
        study_id="STU-PROSPECTIVE-PAIR",
        executable_id=SUBJECT_ID,
        definition=definition,
        output_name_items=tuple(sorted(names.items())),
        plan=plan,
    )
    trace = _trace(definition)
    trace_content = canonical_bytes(trace)
    trace_hash = sha256(trace_content).hexdigest()
    calculation = build_prospective_pair_calculation(
        trace=trace,
        trace_output_name=names["trace"],
        definition=definition,
    )
    calculation_content = canonical_bytes(calculation)
    calculation_hash = sha256(calculation_content).hexdigest()
    measurement = build_measurement(
        scoped_plan=scoped,
        job_id=JOB_ID,
        job_hash=JOB_HASH,
        calculation=calculation,
        trace_sha256=trace_hash,
        calculation_sha256=calculation_hash,
    )
    measurement_content = canonical_bytes(measurement)
    result = build_result(
        scoped_plan=scoped,
        job_id=JOB_ID,
        job_hash=JOB_HASH,
        measurement_sha256=sha256(measurement_content).hexdigest(),
    )
    payloads = {
        names["calculation"]: calculation_content,
        names["measurement"]: measurement_content,
        names["plan"]: canonical_bytes(plan),
        names["result"]: canonical_bytes(result),
        names["trace"]: trace_content,
    }
    artifacts = []
    for index, (output_name, content) in enumerate(payloads.items()):
        path = tmp_path / f"artifact-{index}.json"
        path.write_bytes(content)
        artifacts.append(
            ValidationArtifact(
                output_name=output_name,
                sha256=sha256(content).hexdigest(),
                _source=path,
            )
        )
    request = EvidenceValidationRequest(
        domain="scientific",
        validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        validation_plan_hash=scoped.plan_hash,
        job_id=JOB_ID,
        job_hash=JOB_HASH,
        mission_id=MISSION_ID,
        evidence_subject={"kind": "Executable", "id": SUBJECT_ID},
        binding=scoped.scientific_binding(),
        result_manifest=result,
        artifacts=tuple(artifacts),
    )
    registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
    validated = registry.validate(request)[0]
    assert validated.scientific_eligible is True
    assert validated.facts["executed_evidence_modes"] == list(
        plan["evidence_modes"]
    )
    assert scoped.validated_recomputed_criterion_ids(validated.facts) == tuple(
        sorted(item["criterion_id"] for item in plan["criteria"])
    )
