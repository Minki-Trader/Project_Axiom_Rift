"""Operate STU-0124's prospective intent-status engineering Repair."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.core.canonical import canonical_bytes, parse_canonical  # noqa: E402
from axiom_rift.core.identity import ExecutableSpec  # noqa: E402
from axiom_rift.operations.prospective_job_materialization import (  # noqa: E402
    materialize_prospective_job_implementation,
)
from axiom_rift.operations.prospective_pair_status_projection_validation import (  # noqa: E402
    PROJECTION_PROOF_SCHEMA,
    PROJECTION_REPAIR_PROTOCOL,
    PROJECTION_REPAIR_VALIDATOR_ID,
    RUNNING_JOB_SOURCE_SHA256,
    ProspectivePairStatusProjectionRepairValidator,
    projection_verification_manifest,
)
from axiom_rift.operations.repair_candidate import (  # noqa: E402
    build_repair_candidate,
)
from axiom_rift.operations.repair_disposition_materializer import (  # noqa: E402
    materialize_engineering_repair_disposition,
)
from axiom_rift.operations.repair_disposition_validation import (  # noqa: E402
    EngineeringSemanticChangeNecessityValidator,
)
from axiom_rift.operations.repair_observation_authority import (  # noqa: E402
    require_repair_validation_observation_stream,
)
from axiom_rift.operations.repair_validation import (  # noqa: E402
    build_repair_candidate_validation_context,
    build_repair_candidate_validation_receipt,
    build_repair_validation_plan,
    repair_validation_binding,
)
from axiom_rift.operations.repair_semantic_change_authority import (  # noqa: E402
    build_semantic_change_successor_artifact,
)
from axiom_rift.operations.scientific_protocol_repair_inventory import (  # noqa: E402
    SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_PROTOCOL,
    SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_VALIDATOR_ID,
    ScientificProtocolSuccessorRepairInventoryValidator,
    scientific_protocol_successor_inventory,
)
from axiom_rift.operations.validator_rebind_repair_inventory import (  # noqa: E402
    VALIDATOR_REBIND_REPAIR_INVENTORY_PROTOCOL,
    VALIDATOR_REBIND_REPAIR_INVENTORY_VALIDATOR_ID,
    ScientificValidatorRebindRepairInventoryValidator,
    validator_rebind_successor_inventory,
)
from axiom_rift.operations.permits import (  # noqa: E402
    Permit,
    PermitAuthority,
    PermitKeyStore,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.prospective_pair_status_repair_materializer import (  # noqa: E402
    materialize_prospective_pair_status_repair_candidate,
)
from axiom_rift.operations.validation import EvidenceValidatorRegistry  # noqa: E402
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.operations.running_job import RunningJobExecution  # noqa: E402
from axiom_rift.research.sleeve_exposure_cap_risk_runtime import (  # noqa: E402
    CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL,
    sleeve_exposure_cap_risk_runtime_path,
)
from axiom_rift.research.sleeve_exposure_cap_risk_chassis import (  # noqa: E402
    sleeve_exposure_cap_risk_configurations,
    sleeve_exposure_cap_risk_executable,
)
from axiom_rift.research.sleeve_exposure_cap_risk_study import (  # noqa: E402
    build_sleeve_exposure_cap_risk_job_plan,
)
from axiom_rift.research.governance import (  # noqa: E402
    DiagnosisConfidence,
    EvidenceState,
    StudyDiagnosis,
)
from axiom_rift.research.validation_v2 import (  # noqa: E402
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    ScientificAdjudicationValidatorV2,
)


STUDY_ID = "STU-0124"
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"
OPERATION_PREFIX = "goal-audit-stu0124-intent-status-repair-v1-"
PROJECTION_OPERATION_PREFIX = (
    "goal-audit-stu0124-intent-status-projection-repair-v1-"
)
TERMINAL_OPERATION_PREFIX = (
    "goal-audit-stu0124-validator-identity-terminal-v1-"
)
ROOT_CAUSE = (
    "the exposure-cap trace adapter emitted the mechanism-specific "
    "gross_exposure_cap_blocked status instead of the registered generic "
    "risk_policy_skipped status"
)
PROJECTION_ROOT_CAUSE = (
    "the running Job projection recognized only the generic AST and "
    "fixed-hold semantic-equivalence fact schemas and rejected the registered "
    "prospective-pair status-correction facts"
)
TERMINAL_ROOT_CAUSE = (
    "the repaired trace requires a scientific validator identity that differs "
    "from the preregistered STU-0124 validation plan"
)
STUDY_OPERATION_PREFIX = "goal-audit-cross-sleeve-exposure-cap-risk-v1-"


def _registry() -> EvidenceValidatorRegistry:
    validators: list[Any] = [
        ScientificAdjudicationValidatorV2(),
        ProspectivePairStatusProjectionRepairValidator(),
        ScientificProtocolSuccessorRepairInventoryValidator(),
        EngineeringSemanticChangeNecessityValidator(),
        ScientificValidatorRebindRepairInventoryValidator(),
    ]
    try:
        from axiom_rift.operations.prospective_pair_status_repair_equivalence import (
            ProspectivePairStatusCorrectionEquivalenceValidator,
        )
        from axiom_rift.operations.prospective_pair_status_repair_validation import (
            ProspectivePairStatusRepairAttemptValidator,
        )
    except ImportError:
        pass
    else:
        validators.extend(
            (
                ProspectivePairStatusCorrectionEquivalenceValidator(),
                ProspectivePairStatusRepairAttemptValidator(),
            )
        )
    return EvidenceValidatorRegistry(tuple(validators))


def _writer() -> StateWriter:
    writer = StateWriter(ROOT, validation_registry=_registry())
    writer.permit_authority = PermitAuthority(
        PermitKeyStore(ROOT / "local" / "permit.key").load_or_create()
    )
    writer.require_stable_head()
    return writer


def _operation_result(
    writer: StateWriter,
    operation_id: str,
) -> Mapping[str, Any] | None:
    with writer.open_stable_index() as (_control, index):
        operation = index.get("operation", operation_id)
    if operation is None:
        return None
    result = operation.payload.get("result")
    if operation.status != "success" or not isinstance(result, Mapping):
        raise RuntimeError(f"STU-0124 Repair operation is malformed: {operation_id}")
    return result


def _context(writer: StateWriter) -> dict[str, Any]:
    with writer.open_stable_index() as (control, index):
        science = control.get("scientific")
        job = None if not isinstance(science, Mapping) else science.get("active_job")
        repair = (
            None if not isinstance(science, Mapping) else science.get("active_repair")
        )
        if (
            not isinstance(job, Mapping)
            or science.get("active_study") != STUDY_ID
            or job.get("status") not in {"running", "interrupted_repair"}
        ):
            raise RuntimeError("STU-0124 Repair requires its exact active Job")
        declaration = index.get("job-declared", str(job["id"]))
        spec = None if declaration is None else declaration.payload.get("spec")
        if (
            not isinstance(spec, Mapping)
            or spec.get("callable_identity") != CALLABLE_IDENTITY
            or not isinstance(spec.get("implementation_identity"), str)
        ):
            raise RuntimeError("STU-0124 Repair lost its Job declaration")
        open_operation = index.get("operation", OPERATION_PREFIX + "open")
        open_result = (
            None if open_operation is None else open_operation.payload.get("result")
        )
        repair_id = (
            repair.get("id")
            if isinstance(repair, Mapping)
            else (
                open_result.get("repair_id")
                if isinstance(open_result, Mapping)
                else None
            )
        )
        opened = (
            None
            if not isinstance(repair_id, str)
            else index.get("repair-open", repair_id)
        )
    return {
        "control": control,
        "job": dict(job),
        "opened": None if opened is None else dict(opened.payload),
        "repair": None if repair is None else dict(repair),
        "spec": dict(spec),
    }


def open_repair(writer: StateWriter) -> dict[str, Any]:
    context = _context(writer)
    if context["repair"] is not None:
        return {
            "repair_id": context["repair"]["id"],
            "reused": True,
            "revision": context["control"]["revision"],
            "schema": "stu0124_intent_status_repair_open.v1",
        }
    reproduction = writer.evidence.finalize(
        canonical_bytes(
            {
                "exception_message": "prospective pair intent status is invalid",
                "exception_type": "ScientificTraceError",
                "failure_stage": "build_prospective_pair_calculation",
                "job_id": context["job"]["id"],
                "observed_status": "gross_exposure_cap_blocked",
                "registered_status": "risk_policy_skipped",
                "root_cause": ROOT_CAUSE,
                "schema": "stu0124_intent_status_reproduction.v1",
                "scientific_result_computed": False,
                "study_id": STUDY_ID,
            }
        )
    )
    permit_operation = OPERATION_PREFIX + "permit"
    permit_result = _operation_result(writer, permit_operation)
    if permit_result is None:
        permit = writer.issue_permit(
            kind=PermitKind.REPAIR,
            subject_kind=SubjectKind.JOB,
            subject_id=context["job"]["id"],
            input_hash=context["job"]["hash"],
            actions=("open_repair",),
            scope=("job",),
            expires_at_utc=PERMIT_EXPIRY_UTC,
            one_shot=True,
            operation_id=permit_operation,
        )
    else:
        permit_payload = permit_result.get("permit")
        if not isinstance(permit_payload, Mapping):
            raise RuntimeError("STU-0124 Repair permit is absent")
        permit = Permit.from_mapping(permit_payload)
    result = writer.open_repair(
        permit=permit,
        failure={
            "failure_kind": "engineering",
            "interrupted_action": context["spec"]["callable_identity"],
            "minimum_reproduction_evidence": [reproduction.sha256],
            "root_cause": ROOT_CAUSE,
        },
        operation_id=OPERATION_PREFIX + "open",
    )
    control = writer.read_control()
    if control is None:
        raise RuntimeError("STU-0124 Repair lost control state")
    return {
        "repair_id": result.result["repair_id"],
        "reproduction_artifact_hash": reproduction.sha256,
        "reused": result.reused,
        "revision": control["revision"],
        "schema": "stu0124_intent_status_repair_open.v1",
    }


def execute_repair(writer: StateWriter) -> dict[str, Any]:
    context = _context(writer)
    if context["repair"] is None:
        raise RuntimeError("STU-0124 status correction requires its active Repair")
    candidate_hash = materialize_prospective_pair_status_repair_candidate(
        writer,
        explanation=(
            "normalize the mechanism-specific blocked intent to the registered "
            "generic risk-policy skip trace status without changing decisions"
        ),
        source_root=ROOT / "src",
    )
    result = writer.evaluate_repair_candidate(
        candidate_hash=candidate_hash,
        operation_id=OPERATION_PREFIX + "evaluate",
    )
    control = writer.read_control()
    if control is None:
        raise RuntimeError("STU-0124 Repair lost control state")
    return {
        "candidate_hash": candidate_hash,
        "result": dict(result.result),
        "reused": result.reused,
        "revision": control["revision"],
        "schema": "stu0124_intent_status_repair_evaluation.v1",
    }


def open_projection_repair(writer: StateWriter) -> dict[str, Any]:
    context = _context(writer)
    if context["repair"] is not None:
        return {
            "repair_id": context["repair"]["id"],
            "reused": True,
            "revision": context["control"]["revision"],
            "schema": "stu0124_status_projection_repair_open.v1",
        }
    reproduction = writer.evidence.finalize(
        canonical_bytes(
            {
                "exception_message": (
                    "production implementation Repair lacks complete registered "
                    "semantic-equivalence authority"
                ),
                "exception_type": "RunningJobAuthorityIntegrityError",
                "failure_stage": "verify_running_job_execution",
                "job_id": context["job"]["id"],
                "prior_repair_close_record_id": context["job"].get(
                    "required_repair_resume_record_id"
                ),
                "root_cause": PROJECTION_ROOT_CAUSE,
                "schema": "repaired_job_projection_reproduction.v1",
                "scientific_result_computed": False,
                "study_id": STUDY_ID,
            }
        )
    )
    permit_operation = PROJECTION_OPERATION_PREFIX + "permit"
    permit_result = _operation_result(writer, permit_operation)
    if permit_result is None:
        permit = writer.issue_permit(
            kind=PermitKind.REPAIR,
            subject_kind=SubjectKind.JOB,
            subject_id=context["job"]["id"],
            input_hash=context["job"]["hash"],
            actions=("open_repair",),
            scope=("job",),
            expires_at_utc=PERMIT_EXPIRY_UTC,
            one_shot=True,
            operation_id=permit_operation,
        )
    else:
        permit_payload = permit_result.get("permit")
        if not isinstance(permit_payload, Mapping):
            raise RuntimeError("STU-0124 projection Repair permit is absent")
        permit = Permit.from_mapping(permit_payload)
    result = writer.open_repair(
        permit=permit,
        failure={
            "failure_kind": "engineering",
            "interrupted_action": context["spec"]["callable_identity"],
            "minimum_reproduction_evidence": [reproduction.sha256],
            "root_cause": PROJECTION_ROOT_CAUSE,
        },
        operation_id=PROJECTION_OPERATION_PREFIX + "open",
    )
    control = writer.read_control()
    if control is None:
        raise RuntimeError("STU-0124 projection Repair lost control state")
    return {
        "repair_id": result.result["repair_id"],
        "reproduction_artifact_hash": reproduction.sha256,
        "reused": result.reused,
        "revision": control["revision"],
        "schema": "stu0124_status_projection_repair_open.v1",
    }


def execute_projection_repair(writer: StateWriter) -> dict[str, Any]:
    context = _context(writer)
    repair = context["repair"]
    job = context["job"]
    if not isinstance(repair, Mapping):
        raise RuntimeError("STU-0124 projection Repair is not active")
    with writer.open_stable_index() as (control, index):
        science = control["scientific"]
        declaration = index.get("job-declared", str(job["id"]))
        opened = index.get("repair-open", str(repair["id"]))
        if declaration is None or opened is None:
            raise RuntimeError("STU-0124 projection Repair provenance is absent")
        mission_id = declaration.payload.get("mission_id")
        if type(mission_id) is not str:
            raise RuntimeError("STU-0124 projection Repair Mission is absent")
        attempts = []
        attempt_head = index.event_head(f"repair-attempt:{repair['id']}")
        if attempt_head is not None:
            for sequence in range(1, attempt_head.sequence + 1):
                attempt = index.event_record(
                    f"repair-attempt:{repair['id']}", sequence
                )
                if attempt is None:
                    raise RuntimeError("STU-0124 projection attempt stream has a gap")
                attempts.append(attempt)
        observations, observation_head = (
            require_repair_validation_observation_stream(
                index,
                repair_id=str(repair["id"]),
                job_id=str(job["id"]),
                job_hash=str(job["hash"]),
                cause_hash=str(repair["cause_hash"]),
                reproduction_evidence_hashes=opened.payload[
                    "minimum_reproduction_evidence"
                ],
                resume_action=str(repair["resume_action"]),
                mission_id=mission_id,
                expected_scope="production",
                accepted_attempts=attempts,
                evidence=writer.evidence,
            )
        )
    reproduction = opened.payload["minimum_reproduction_evidence"]
    running_job_path = ROOT / "src" / "axiom_rift" / "operations" / "running_job.py"
    source_artifact = writer.evidence.finalize(running_job_path.read_bytes())
    if source_artifact.sha256 != RUNNING_JOB_SOURCE_SHA256:
        raise RuntimeError("STU-0124 projection Repair source drifted")
    proof = writer.evidence.finalize(
        canonical_bytes(
            {
                "changed_dimension": "cause",
                "corrected_fact_schema": (
                    "prospective_pair_status_encoding_correction_facts.v1"
                ),
                "job_hash": job["hash"],
                "job_id": job["id"],
                "repair_id": repair["id"],
                "running_job_source_sha256": RUNNING_JOB_SOURCE_SHA256,
                "schema": PROJECTION_PROOF_SCHEMA,
                "scientific_semantics_changed": False,
            }
        )
    )
    verification = writer.evidence.finalize(
        canonical_bytes(projection_verification_manifest())
    )
    bound_observations = tuple(
        {
            "new_information_evidence_hashes": list(
                item["new_information_evidence_hashes"]
            ),
            "observation_record_id": item["observation_record_id"],
        }
        for item in observations
    )
    observation_information = {
        identity
        for item in bound_observations
        for identity in item["new_information_evidence_hashes"]
    }
    new_evidence = tuple(
        sorted({source_artifact.sha256, proof.sha256, *observation_information})
    )
    explanation = (
        "recognize the registered prospective-pair status-correction facts "
        "during running Job Repair projection replay"
    )
    validation_context = build_repair_candidate_validation_context(
        bound_validation_observations=bound_observations,
        cause_hash=str(repair["cause_hash"]),
        changed_dimension="cause",
        explanation=explanation,
        implementation_proof_hash=None,
        job_hash=str(job["hash"]),
        job_id=str(job["id"]),
        new_basis_hash=source_artifact.sha256,
        new_evidence_hashes=new_evidence,
        previous_basis_hash=str(repair["latest_basis_hash"]),
        prior_attempt_record_id=repair.get("latest_attempt_record_id"),
        prior_validation_observation_head=observation_head,
        repair_axis_id="running-job-projection",
        repair_id=str(repair["id"]),
        reproduction_evidence_hashes=reproduction,
        resume_action=str(repair["resume_action"]),
    )
    artifact_roles = tuple(
        sorted(
            (
                ("projection_proof", proof.sha256),
                ("projection_source", source_artifact.sha256),
                ("validation_result", verification.sha256),
                *(
                    (f"reproduction:{ordinal:04d}", identity)
                    for ordinal, identity in enumerate(reproduction)
                ),
            )
        )
    )
    writer.validation_registry.require_plannable_protocol(
        validator_id=PROJECTION_REPAIR_VALIDATOR_ID,
        domain="engineering",
        protocol=PROJECTION_REPAIR_PROTOCOL,
    )
    binding = repair_validation_binding(
        verification_kind="candidate",
        mission_id=mission_id,
        protocol=PROJECTION_REPAIR_PROTOCOL,
        context=validation_context,
        artifact_roles=artifact_roles,
    )
    plan = writer.evidence.finalize(
        canonical_bytes(
            build_repair_validation_plan(
                validator_id=PROJECTION_REPAIR_VALIDATOR_ID,
                binding=binding,
            )
        )
    )
    receipt = writer.evidence.finalize(
        canonical_bytes(
            build_repair_candidate_validation_receipt(
                validator_id=PROJECTION_REPAIR_VALIDATOR_ID,
                validation_plan_hash=plan.sha256,
                protocol=PROJECTION_REPAIR_PROTOCOL,
                result_artifact_hashes=tuple(
                    sorted(identity for _name, identity in artifact_roles)
                ),
            )
        )
    )
    candidate = writer.evidence.finalize(
        canonical_bytes(
            build_repair_candidate(
                cause_hash=str(repair["cause_hash"]),
                changed_dimension="cause",
                repair_axis_id="running-job-projection",
                explanation=explanation,
                implementation_proof_hash=None,
                job_hash=str(job["hash"]),
                job_id=str(job["id"]),
                new_basis_hash=source_artifact.sha256,
                new_evidence_hashes=new_evidence,
                previous_basis_hash=str(repair["latest_basis_hash"]),
                prior_attempt_record_id=repair.get("latest_attempt_record_id"),
                prior_validation_observation_head=observation_head,
                bound_validation_observations=bound_observations,
                repair_id=str(repair["id"]),
                reproduction_evidence_hashes=tuple(sorted(reproduction)),
                resume_action=str(repair["resume_action"]),
                verification_evidence_hashes=(receipt.sha256,),
            )
        )
    )
    result = writer.evaluate_repair_candidate(
        candidate_hash=candidate.sha256,
        operation_id=PROJECTION_OPERATION_PREFIX + "evaluate",
    )
    control = writer.read_control()
    if control is None:
        raise RuntimeError("STU-0124 projection Repair lost control state")
    return {
        "candidate_hash": candidate.sha256,
        "result": dict(result.result),
        "revision": control["revision"],
        "schema": "stu0124_status_projection_repair_evaluation.v1",
    }


def resume_repaired_job(writer: StateWriter) -> dict[str, Any]:
    context = _context(writer)
    if context["repair"] is not None:
        raise RuntimeError("STU-0124 repaired Job still has an active Repair")
    start = _operation_result(
        writer,
        STUDY_OPERATION_PREFIX + "control-start-job",
    )
    execution_payload = None if start is None else start.get("execution")
    if not isinstance(execution_payload, Mapping):
        raise RuntimeError("STU-0124 control execution authority is absent")
    spec = context["spec"]
    result = writer.resume_repaired_job_execution(
        RunningJobExecution.from_mapping(execution_payload),
        expected_callable_identity=CALLABLE_IDENTITY,
        expected_evidence_subject=spec["evidence_subject"],
        required_input_hashes=tuple(spec["input_hashes"]),
        operation_id=PROJECTION_OPERATION_PREFIX + "resume",
    )
    control = writer.read_control()
    if control is None:
        raise RuntimeError("STU-0124 repaired Job lost control state")
    return {
        "result": dict(result.result),
        "reused": result.reused,
        "revision": control["revision"],
        "schema": "stu0124_repaired_job_resume.v1",
    }


def open_terminal_repair(writer: StateWriter) -> dict[str, Any]:
    context = _context(writer)
    if context["repair"] is not None:
        return {
            "repair_id": context["repair"]["id"],
            "reused": True,
            "revision": context["control"]["revision"],
            "schema": "stu0124_validator_terminal_repair_open.v1",
        }
    frozen_validator = context["spec"].get("scientific_binding", {}).get(
        "validator_id"
    )
    reproduction = writer.evidence.finalize(
        canonical_bytes(
            {
                "current_validator_id": (
                    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
                ),
                "failure_stage": "scientific_protocol_reactivation",
                "frozen_validator_id": frozen_validator,
                "job_id": context["job"]["id"],
                "root_cause": TERMINAL_ROOT_CAUSE,
                "schema": "stu0124_validator_identity_reproduction.v1",
                "scientific_result_computed": False,
                "study_id": STUDY_ID,
            }
        )
    )
    permit_operation = TERMINAL_OPERATION_PREFIX + "permit"
    permit_result = _operation_result(writer, permit_operation)
    if permit_result is None:
        permit = writer.issue_permit(
            kind=PermitKind.REPAIR,
            subject_kind=SubjectKind.JOB,
            subject_id=context["job"]["id"],
            input_hash=context["job"]["hash"],
            actions=("open_repair",),
            scope=("job",),
            expires_at_utc=PERMIT_EXPIRY_UTC,
            one_shot=True,
            operation_id=permit_operation,
        )
    else:
        permit_payload = permit_result.get("permit")
        if not isinstance(permit_payload, Mapping):
            raise RuntimeError("STU-0124 terminal Repair permit is absent")
        permit = Permit.from_mapping(permit_payload)
    result = writer.open_repair(
        permit=permit,
        failure={
            "failure_kind": "engineering",
            "interrupted_action": context["spec"]["callable_identity"],
            "minimum_reproduction_evidence": [reproduction.sha256],
            "root_cause": TERMINAL_ROOT_CAUSE,
        },
        operation_id=TERMINAL_OPERATION_PREFIX + "open",
    )
    control = writer.read_control()
    if control is None:
        raise RuntimeError("STU-0124 terminal Repair lost control state")
    return {
        "repair_id": result.result["repair_id"],
        "reproduction_artifact_hash": reproduction.sha256,
        "revision": control["revision"],
        "schema": "stu0124_validator_terminal_repair_open.v1",
    }


def _successor_spec(
    writer: StateWriter,
    context: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    current = sleeve_exposure_cap_risk_executable(
        sleeve_exposure_cap_risk_configurations()[0]
    )
    parameters = current.parameter_values()
    if not isinstance(parameters, dict):
        raise RuntimeError("STU-0124 successor parameters are invalid")
    proposed = ExecutableSpec(
        display_name="status-normalized exposure-cap protocol control",
        components=current.components,
        parameters={
            **parameters,
            "scientific_protocol_revision": "status_normalized_v1",
        },
        data_contract=current.data_contract,
        split_contract=current.split_contract,
        clock_contract=current.clock_contract,
        cost_contract=current.cost_contract,
        engine_contract=current.engine_contract,
        source_contracts=current.source_contracts,
    )
    implementation = materialize_prospective_job_implementation(
        writer,
        entry_path=sleeve_exposure_cap_risk_runtime_path(),
        callable_identity=CALLABLE_IDENTITY,
        protocol=JOB_IMPLEMENTATION_PROTOCOL,
        source_root=ROOT / "src",
    )
    implementation_manifest = parse_canonical(
        writer.evidence.read_verified(implementation)
    )
    if not isinstance(implementation_manifest, dict):
        raise RuntimeError("STU-0124 successor implementation is invalid")
    successor_plan = writer.evidence.finalize(
        canonical_bytes(
            {
                "executable_id": proposed.identity,
                "predecessor_study_id": STUDY_ID,
                "repair_id": context["repair"]["id"],
                "schema": "stu0125_validator_rebind_successor_plan.v1",
                "study_id": "STU-0125",
                "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
            }
        )
    )
    current_spec = dict(context["spec"])
    current_science = dict(current_spec["scientific_binding"])
    old_plan = current_science["validation_plan_hash"]
    inputs = set(current_spec["input_hashes"])
    inputs.discard(old_plan)
    inputs.update(implementation_manifest["artifact_hashes"])
    inputs.add(successor_plan.sha256)
    outputs = [
        value.replace("STU-0124", "STU-0125").replace(
            current_spec["evidence_subject"]["id"].split(":", 1)[1][:16],
            proposed.identity.split(":", 1)[1][:16],
        )
        for value in current_spec["expected_outputs"]
    ]
    proposed_spec = {
        **current_spec,
        "evidence_subject": {"kind": "Executable", "id": proposed.identity},
        "expected_outputs": outputs,
        "implementation_identity": implementation,
        "input_hashes": sorted(inputs),
        "log_path": "local/jobs/stu-0125/control.log",
        "output_classes": {
            output: current_spec["output_classes"][old]
            for old, output in zip(
                current_spec["expected_outputs"], outputs, strict=True
            )
        },
        "scientific_binding": {
            **current_science,
            "result_manifest_output": current_science[
                "result_manifest_output"
            ].replace("STU-0124", "STU-0125"),
            "validation_plan_hash": successor_plan.sha256,
            "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        },
        "timeout_or_stop_rule": (
            "finish the exact validator-rebound successor control member"
        ),
    }
    return proposed_spec, proposed.to_identity_payload()


def _terminal_authority(
    writer: StateWriter,
    context: Mapping[str, Any],
) -> tuple[str, str]:
    with writer.open_stable_index() as (_control, index):
        subject_id = context["spec"]["evidence_subject"]["id"]
        trial = index.get("trial", subject_id)
    current_executable = None if trial is None else trial.payload.get("executable")
    if not isinstance(current_executable, Mapping):
        raise RuntimeError("STU-0124 current Executable is unavailable")
    proposed_spec, proposed_executable = _successor_spec(writer, context)
    current_spec = dict(context["spec"])
    current_implementation = parse_canonical(
        writer.evidence.read_verified(current_spec["implementation_identity"])
    )
    proposed_implementation = parse_canonical(
        writer.evidence.read_verified(proposed_spec["implementation_identity"])
    )
    if not isinstance(current_implementation, dict) or not isinstance(
        proposed_implementation, dict
    ):
        raise RuntimeError("STU-0124 implementation authority is malformed")
    documents = {
        "current_executable_manifest": dict(current_executable),
        "current_implementation_manifest": current_implementation,
        "current_job_spec": current_spec,
        "proposed_executable_manifest": proposed_executable,
        "proposed_implementation_manifest": proposed_implementation,
        "proposed_job_spec": proposed_spec,
    }
    artifacts = {
        name: writer.evidence.finalize(canonical_bytes(value))
        for name, value in documents.items()
    }
    support_hashes = {
        name: artifact.sha256 for name, artifact in artifacts.items()
    }
    inventory = validator_rebind_successor_inventory(
        current_job_spec=current_spec,
        proposed_job_spec=proposed_spec,
        current_executable_manifest=dict(current_executable),
        proposed_executable_manifest=proposed_executable,
        current_implementation_manifest=current_implementation,
        proposed_implementation_manifest=proposed_implementation,
        support_hashes=support_hashes,
    )
    inventory_artifact = writer.evidence.finalize(canonical_bytes(inventory))
    opened = context.get("opened")
    reproduction = (
        None
        if not isinstance(opened, Mapping)
        else opened.get("minimum_reproduction_evidence")
    )
    if not isinstance(reproduction, list) or len(reproduction) != 1:
        raise RuntimeError("STU-0124 terminal reproduction is absent")
    successor = build_semantic_change_successor_artifact(
        successor_scope="executable",
        job_spec=proposed_spec,
        executable_manifest=proposed_executable,
        implementation_protocol=JOB_IMPLEMENTATION_PROTOCOL,
    )
    successor_artifact = writer.evidence.finalize(canonical_bytes(successor))
    disposition_hash = materialize_engineering_repair_disposition(
        writer,
        inventory_validator_id=VALIDATOR_REBIND_REPAIR_INVENTORY_VALIDATOR_ID,
        inventory_protocol=VALIDATOR_REBIND_REPAIR_INVENTORY_PROTOCOL,
        inventory_result_artifacts={
            **support_hashes,
            "reproduction:0000": reproduction[0],
            "validation_result": inventory_artifact.sha256,
        },
        rationale=(
            "the corrected trace and its current validator identity require "
            "a separately preregistered successor Executable"
        ),
        resume_condition=(
            "complete the typed engineering failure and admit a successor "
            "only from the next Portfolio decision"
        ),
        semantic_change_successor_artifact_hash=successor_artifact.sha256,
    )
    return disposition_hash, successor_artifact.sha256


def _ensure_transition(
    writer: StateWriter,
    suffix: str,
    action: Any,
) -> Mapping[str, Any]:
    operation_id = TERMINAL_OPERATION_PREFIX + suffix
    existing = _operation_result(writer, operation_id)
    if existing is not None:
        return existing
    result = action()
    if not isinstance(result.result, Mapping):
        raise RuntimeError(f"STU-0124 terminal operation is invalid: {suffix}")
    return result.result


def close_terminal_study(writer: StateWriter) -> dict[str, Any]:
    context = _context(writer)
    if context["repair"] is None:
        raise RuntimeError("STU-0124 terminal requires its active Repair")
    disposition_hash, successor_hash = _terminal_authority(writer, context)
    concluded = _ensure_transition(
        writer,
        "conclude",
        lambda: writer.conclude_repair_unrecovered(
            disposition_hash=disposition_hash,
            operation_id=TERMINAL_OPERATION_PREFIX + "conclude",
        ),
    )
    completion = _ensure_transition(
        writer,
        "complete-engineering-failure",
        lambda: writer.complete_job(
            outcome="failed",
            output_manifest={},
            failure={
                "failure_kind": context["opened"]["failure_kind"],
                "interrupted_action": context["opened"]["interrupted_action"],
                "minimum_reproduction_evidence": list(
                    context["opened"]["minimum_reproduction_evidence"]
                ),
                "root_cause": context["opened"]["root_cause"],
                "repair_disposition_hash": concluded["disposition_hash"],
                "resume_action": context["spec"]["resume_action"],
            },
            operation_id=TERMINAL_OPERATION_PREFIX
            + "complete-engineering-failure",
        ),
    )
    completion_id = completion["completion_record_id"]
    _ensure_transition(
        writer,
        "judge",
        lambda: writer.judge_job_evidence(
            completion_record_id=completion_id,
            disposition="stop_batch",
            operation_id=TERMINAL_OPERATION_PREFIX + "judge",
        ),
    )
    _ensure_transition(
        writer,
        "dispose-batch",
        lambda: writer.dispose_batch(
            outcome="engineering_failure",
            operation_id=TERMINAL_OPERATION_PREFIX + "dispose-batch",
        ),
    )
    _ensure_transition(
        writer,
        "close-study",
        lambda: writer.close_study(
            outcome="not_evaluable",
            operation_id=TERMINAL_OPERATION_PREFIX + "close-study",
            kpi_completion_record_id=completion_id,
        ),
    )
    control = writer.read_control()
    if control is None:
        raise RuntimeError("STU-0124 terminal lost control state")
    return {
        "completion_record_id": completion_id,
        "disposition_hash": disposition_hash,
        "next_action": control["next_action"],
        "revision": control["revision"],
        "schema": "stu0124_validator_terminal.v1",
        "successor_artifact_hash": successor_hash,
    }


def diagnose_engineering_gap(writer: StateWriter) -> dict[str, Any]:
    operation_id = TERMINAL_OPERATION_PREFIX + "diagnose"
    result = _operation_result(writer, operation_id)
    if result is None:
        control = writer.read_control()
        if control is None:
            raise RuntimeError("STU-0124 diagnosis lost control state")
        next_action = control.get("next_action")
        if (
            not isinstance(next_action, Mapping)
            or next_action.get("kind") != "diagnose_study"
            or next_action.get("study_id") != STUDY_ID
            or not isinstance(next_action.get("study_close_record_id"), str)
        ):
            raise RuntimeError("STU-0124 diagnosis is not the exact next action")
        result = writer.record_study_diagnosis(
            diagnosis=StudyDiagnosis(
                study_id=STUDY_ID,
                study_close_record_id=next_action["study_close_record_id"],
                evidence_state=EvidenceState.ENGINEERING_GAP,
                confidence=DiagnosisConfidence.HIGH,
                rationale=(
                    "no scientific result was admitted because the registered "
                    "intent-status correction changed the current validator "
                    "identity after STU-0124 preregistration; the typed Repair "
                    "requires a distinct successor protocol"
                ),
                counterfactual=(
                    "a separately preregistered successor bound to the current "
                    "validator identity could answer the unchanged exposure-cap "
                    "question without counting this engineering failure as evidence"
                ),
                reopen_condition=(
                    "continue only from a Portfolio decision through the typed "
                    "successor artifact, or select another higher-information axis"
                ),
            ),
            operation_id=operation_id,
        ).result
    control = writer.read_control()
    if control is None:
        raise RuntimeError("STU-0124 diagnosis lost terminal control state")
    return {
        "next_action": control["next_action"],
        "revision": control["revision"],
        "schema": "stu0124_validator_terminal_diagnosis.v1",
        "study_diagnosis_id": result.get("study_diagnosis_id"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--open-projection", action="store_true")
    parser.add_argument("--execute-projection", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--open-terminal", action="store_true")
    parser.add_argument("--terminal", action="store_true")
    parser.add_argument("--diagnose", action="store_true")
    arguments = parser.parse_args()
    if sum(
        (
            arguments.open,
            arguments.execute,
            arguments.open_projection,
            arguments.execute_projection,
            arguments.resume,
            arguments.open_terminal,
            arguments.terminal,
            arguments.diagnose,
        )
    ) > 1:
        raise SystemExit("choose one STU-0124 Repair action")
    writer = _writer()
    result = (
        open_repair(writer)
        if arguments.open
        else open_projection_repair(writer)
        if arguments.open_projection
        else execute_projection_repair(writer)
        if arguments.execute_projection
        else resume_repaired_job(writer)
        if arguments.resume
        else open_terminal_repair(writer)
        if arguments.open_terminal
        else close_terminal_study(writer)
        if arguments.terminal
        else diagnose_engineering_gap(writer)
        if arguments.diagnose
        else execute_repair(writer)
        if arguments.execute
        else {
            "context": _context(writer),
            "schema": "stu0124_intent_status_repair_plan.v1",
        }
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
