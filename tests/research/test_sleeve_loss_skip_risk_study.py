from __future__ import annotations

from hashlib import sha256

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.validation import (
    EvidenceValidationRequest,
    EvidenceValidatorRegistry,
    ValidationArtifact,
)
from axiom_rift.research.prospective_pair_trace import (
    build_prospective_pair_calculation,
)
from axiom_rift.research.sleeve_loss_skip_risk_study import (
    SleeveLossSkipRiskJobPlan,
    build_measurement,
    build_result,
    build_sleeve_loss_skip_risk_validation_plan,
    output_names,
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
