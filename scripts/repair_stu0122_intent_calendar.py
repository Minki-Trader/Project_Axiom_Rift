"""Operate STU-0122's prospective intent-calendar engineering Repair."""

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
from axiom_rift.operations.prospective_job_materialization import (  # noqa: E402
    materialize_prospective_job_implementation,
)
from axiom_rift.operations.repair_disposition_materializer import (  # noqa: E402
    materialize_engineering_repair_disposition,
)
from axiom_rift.operations.repair_disposition_validation import (  # noqa: E402
    EngineeringSemanticChangeNecessityValidator,
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
from axiom_rift.operations.permits import (  # noqa: E402
    Permit,
    PermitAuthority,
    PermitKeyStore,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.validation import (  # noqa: E402
    EvidenceValidatorRegistry,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.sleeve_loss_skip_risk_runtime import (  # noqa: E402
    CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL,
    sleeve_loss_skip_risk_runtime_path,
)
from axiom_rift.research.sleeve_loss_skip_risk_chassis import (  # noqa: E402
    sleeve_loss_skip_risk_configurations,
    sleeve_loss_skip_risk_executable,
)
from axiom_rift.research.sleeve_loss_skip_risk_study import (  # noqa: E402
    build_sleeve_loss_skip_risk_job_plan,
)
from axiom_rift.research.governance import (  # noqa: E402
    DiagnosisConfidence,
    EvidenceState,
    StudyDiagnosis,
)
from axiom_rift.research.validation_v2 import (  # noqa: E402
    ScientificAdjudicationValidatorV2,
)


STUDY_ID = "STU-0122"
SUCCESSOR_STUDY_ID = "STU-0123"
MISSION_ID = "MIS-0006"
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"
OPERATION_PREFIX = (
    "goal-audit-sleeve-loss-skip-risk-v1-control-repair-1-"
)
ROOT_CAUSE = (
    "the trace adapter emitted gap-excluded intents whose theoretical "
    "decision date was outside the preregistered eligible-day inventory"
)


def _writer() -> StateWriter:
    writer = StateWriter(
        ROOT,
        validation_registry=EvidenceValidatorRegistry(
            (
                ScientificAdjudicationValidatorV2(),
                ScientificProtocolSuccessorRepairInventoryValidator(),
                EngineeringSemanticChangeNecessityValidator(),
            )
        ),
    )
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
        raise RuntimeError(f"STU-0122 Repair operation is malformed: {operation_id}")
    return result


def _context(writer: StateWriter) -> dict[str, Any]:
    with writer.open_stable_index() as (control, index):
        science = control.get("scientific")
        job = None if not isinstance(science, Mapping) else science.get(
            "active_job"
        )
        repair = None if not isinstance(science, Mapping) else science.get(
            "active_repair"
        )
        if (
            not isinstance(job, Mapping)
            or science.get("active_study") != STUDY_ID
            or job.get("status") not in {"running", "interrupted_repair"}
        ):
            raise RuntimeError("STU-0122 Repair requires its exact active Job")
        declaration = index.get("job-declared", str(job["id"]))
        spec = None if declaration is None else declaration.payload.get("spec")
        subject = None if not isinstance(spec, Mapping) else spec.get(
            "evidence_subject"
        )
        if (
            not isinstance(spec, Mapping)
            or not isinstance(subject, Mapping)
            or subject.get("kind") != "Executable"
            or not isinstance(subject.get("id"), str)
            or spec.get("callable_identity") != CALLABLE_IDENTITY
            or not isinstance(spec.get("implementation_identity"), str)
        ):
            raise RuntimeError("STU-0122 Repair lost its Job declaration")
        trial = index.get("trial", str(subject["id"]))
        executable = None if trial is None else trial.payload.get("executable")
        open_operation = index.get("operation", OPERATION_PREFIX + "open")
        open_result = (
            None
            if open_operation is None
            else open_operation.payload.get("result")
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
        if not isinstance(executable, Mapping):
            raise RuntimeError("STU-0122 Repair lost its Executable trial")
    return {
        "control": control,
        "current_executable_manifest": dict(executable),
        "job": dict(job),
        "opened": None if opened is None else dict(opened.payload),
        "repair": None if repair is None else dict(repair),
        "repair_id": repair_id,
        "spec": dict(spec),
    }


def plan_repair(writer: StateWriter) -> dict[str, Any]:
    context = _context(writer)
    return {
        "active_job_id": context["job"]["id"],
        "active_repair_id": (
            None
            if context["repair"] is None
            else context["repair"]["id"]
        ),
        "declared_implementation_identity": context["spec"][
            "implementation_identity"
        ],
        "revision": context["control"]["revision"],
        "schema": "stu0122_intent_calendar_repair_plan.v1",
    }


def open_repair(writer: StateWriter) -> dict[str, Any]:
    context = _context(writer)
    if context["repair"] is not None:
        return {
            "repair_id": context["repair"]["id"],
            "reused": True,
            "revision": context["control"]["revision"],
            "schema": "stu0122_intent_calendar_repair_open.v1",
        }
    reproduction = writer.evidence.finalize(
        canonical_bytes(
            {
                "exception_message": (
                    "prospective pair intent day is not eligible"
                ),
                "exception_type": "ScientificTraceError",
                "failure_stage": "build_prospective_pair_calculation",
                "job_id": context["job"]["id"],
                "protected_protocol_rule": (
                    "every emitted intent decision date belongs to the "
                    "preregistered fold eligible-day inventory"
                ),
                "root_cause": ROOT_CAUSE,
                "schema": "stu0122_intent_calendar_reproduction.v1",
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
            raise RuntimeError("STU-0122 Repair permit is absent")
        permit = Permit.from_mapping(permit_payload)
    opened = writer.open_repair(
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
        raise RuntimeError("STU-0122 Repair lost control state")
    return {
        "repair_id": opened.result["repair_id"],
        "reproduction_artifact_hash": reproduction.sha256,
        "reused": opened.reused,
        "revision": control["revision"],
        "schema": "stu0122_intent_calendar_repair_open.v1",
    }


def _ensure_operation(
    writer: StateWriter,
    suffix: str,
    action: Any,
) -> Mapping[str, Any]:
    operation_id = OPERATION_PREFIX + suffix
    existing = _operation_result(writer, operation_id)
    if existing is not None:
        return existing
    result = action()
    if not isinstance(result.result, Mapping):
        raise RuntimeError(f"STU-0122 operation result is malformed: {suffix}")
    return result.result


def _proposed_job_spec(writer: StateWriter) -> tuple[dict[str, Any], dict[str, Any]]:
    executable = sleeve_loss_skip_risk_executable(
        sleeve_loss_skip_risk_configurations()[0]
    )
    plan = build_sleeve_loss_skip_risk_job_plan(
        repository_root=ROOT,
        mission_id=MISSION_ID,
        study_id=SUCCESSOR_STUDY_ID,
        executable_id=executable.identity,
    )
    plan_artifact = writer.evidence.finalize(canonical_bytes(plan.plan))
    if plan_artifact.sha256 != plan.plan_hash:
        raise RuntimeError("STU-0122 successor validation plan drifted")
    implementation = materialize_prospective_job_implementation(
        writer,
        entry_path=sleeve_loss_skip_risk_runtime_path(),
        callable_identity=CALLABLE_IDENTITY,
        protocol=JOB_IMPLEMENTATION_PROTOCOL,
        source_root=ROOT / "src",
    )
    spec = {
        "budget": {"compute_seconds": 7200, "wall_seconds": 10800},
        "callable_identity": CALLABLE_IDENTITY,
        "evidence_subject": {
            "kind": "Executable",
            "id": executable.identity,
        },
        "expected_outputs": list(plan.expected_outputs()),
        "implementation_identity": implementation,
        "input_hashes": list(plan.job_input_hashes()),
        "log_path": "local/jobs/stu-0123/control.log",
        "output_classes": plan.expected_output_classes(),
        "resume_action": "continue_batch",
        "scientific_binding": plan.scientific_binding(),
        "timeout_or_stop_rule": (
            "finish the exact corrected eligible-day control member"
        ),
        "worker_claims": [],
    }
    return spec, executable.to_identity_payload()


def _materialize_terminal_authority(
    writer: StateWriter,
    context: Mapping[str, Any],
) -> tuple[str, str]:
    proposed_spec, proposed_executable = _proposed_job_spec(writer)
    current_spec = dict(context["spec"])
    current_executable = dict(context["current_executable_manifest"])
    current_implementation = parse_canonical(
        writer.evidence.read_verified(current_spec["implementation_identity"])
    )
    proposed_implementation = parse_canonical(
        writer.evidence.read_verified(proposed_spec["implementation_identity"])
    )
    if not isinstance(current_implementation, dict) or not isinstance(
        proposed_implementation, dict
    ):
        raise RuntimeError("STU-0122 implementation authority is malformed")
    documents = {
        "current_executable_manifest": current_executable,
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
    inventory = scientific_protocol_successor_inventory(
        current_job_spec=current_spec,
        proposed_job_spec=proposed_spec,
        current_executable_manifest=current_executable,
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
        raise RuntimeError("STU-0122 Repair reproduction authority is absent")
    successor = build_semantic_change_successor_artifact(
        successor_scope="executable",
        job_spec=proposed_spec,
        executable_manifest=proposed_executable,
        implementation_protocol=JOB_IMPLEMENTATION_PROTOCOL,
    )
    successor_artifact = writer.evidence.finalize(canonical_bytes(successor))
    disposition_hash = materialize_engineering_repair_disposition(
        writer,
        inventory_validator_id=(
            SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_VALIDATOR_ID
        ),
        inventory_protocol=SCIENTIFIC_PROTOCOL_REPAIR_INVENTORY_PROTOCOL,
        inventory_result_artifacts={
            **support_hashes,
            "reproduction:0000": reproduction[0],
            "validation_result": inventory_artifact.sha256,
        },
        rationale=(
            "the corrected eligible-day trace changes protected Job inputs "
            "and requires a distinct preregistered Executable"
        ),
        resume_condition=(
            "complete the typed engineering failure and admit STU-0123"
        ),
        semantic_change_successor_artifact_hash=successor_artifact.sha256,
    )
    return disposition_hash, successor_artifact.sha256


def conclude_and_close(writer: StateWriter) -> dict[str, Any]:
    conclude_result = _operation_result(writer, OPERATION_PREFIX + "conclude")
    completion = _operation_result(
        writer,
        OPERATION_PREFIX + "complete-engineering-failure",
    )
    context = (
        None
        if conclude_result is not None and completion is not None
        else _context(writer)
    )
    successor_hash: str | None = None
    if conclude_result is None:
        if context is None:
            raise RuntimeError("STU-0122 terminal lost its Repair context")
        if context["repair"] is None:
            raise RuntimeError("STU-0122 terminal requires its active Repair")
        disposition_hash, successor_hash = _materialize_terminal_authority(
            writer, context
        )
        conclude_result = writer.conclude_repair_unrecovered(
            disposition_hash=disposition_hash,
            operation_id=OPERATION_PREFIX + "conclude",
        ).result
    disposition_hash = conclude_result.get("disposition_hash")
    if not isinstance(disposition_hash, str):
        raise RuntimeError("STU-0122 engineering disposition is absent")
    if completion is None:
        if context is None:
            raise RuntimeError("STU-0122 terminal lost its Job context")
        opened = context.get("opened")
        if not isinstance(opened, Mapping):
            raise RuntimeError("STU-0122 Repair cause is absent")
        cause = {
            "failure_kind": opened["failure_kind"],
            "interrupted_action": opened["interrupted_action"],
            "minimum_reproduction_evidence": list(
                opened["minimum_reproduction_evidence"]
            ),
            "root_cause": opened["root_cause"],
            "repair_disposition_hash": disposition_hash,
            "resume_action": context["spec"]["resume_action"],
        }
        completion = _ensure_operation(
            writer,
            "complete-engineering-failure",
            lambda: writer.complete_job(
                outcome="failed",
                output_manifest={},
                failure=cause,
                operation_id=(
                    OPERATION_PREFIX + "complete-engineering-failure"
                ),
            ),
        )
    completion_id = completion.get("completion_record_id")
    if not isinstance(completion_id, str):
        raise RuntimeError("STU-0122 engineering completion is absent")
    _ensure_operation(
        writer,
        "judge-engineering-failure",
        lambda: writer.judge_job_evidence(
            completion_record_id=completion_id,
            disposition="stop_batch",
            operation_id=OPERATION_PREFIX + "judge-engineering-failure",
        ),
    )
    _ensure_operation(
        writer,
        "dispose-engineering-batch",
        lambda: writer.dispose_batch(
            outcome="engineering_failure",
            operation_id=OPERATION_PREFIX + "dispose-engineering-batch",
        ),
    )
    close = _ensure_operation(
        writer,
        "close-not-evaluable-study",
        lambda: writer.close_study(
            outcome="not_evaluable",
            operation_id=OPERATION_PREFIX + "close-not-evaluable-study",
            kpi_completion_record_id=completion_id,
        ),
    )
    control = writer.read_control()
    if control is None:
        raise RuntimeError("STU-0122 terminal lost control state")
    next_action = control.get("next_action")
    journal_head = control.get("heads", {}).get("journal", {})
    close_is_head = (
        isinstance(next_action, Mapping)
        and next_action.get("kind") == "diagnose_study"
        and next_action.get("study_id") == STUDY_ID
        and isinstance(journal_head, Mapping)
    )
    return {
        "completion_record_id": completion_id,
        "disposition_hash": disposition_hash,
        "revision": control["revision"],
        "schema": "stu0122_intent_calendar_terminal.v1",
        "study_close_event_id": (
            journal_head.get("event_id") if close_is_head else None
        ),
        "study_close_record_id": (
            next_action.get("study_close_record_id")
            if close_is_head
            else None
        ),
        "study_close_revision": (
            control["revision"] if close_is_head else None
        ),
        "successor_artifact_hash": successor_hash,
    }


def diagnose_engineering_gap(writer: StateWriter) -> dict[str, Any]:
    operation_id = OPERATION_PREFIX + "diagnose-engineering-gap"
    result = _operation_result(writer, operation_id)
    if result is None:
        control = writer.read_control()
        if control is None:
            raise RuntimeError("STU-0122 diagnosis lost control state")
        next_action = control.get("next_action")
        if (
            not isinstance(next_action, Mapping)
            or next_action.get("kind") != "diagnose_study"
            or next_action.get("study_id") != STUDY_ID
            or not isinstance(next_action.get("study_close_record_id"), str)
        ):
            raise RuntimeError("STU-0122 diagnosis is not the exact next action")
        result = writer.record_study_diagnosis(
            diagnosis=StudyDiagnosis(
                study_id=STUDY_ID,
                study_close_record_id=next_action["study_close_record_id"],
                evidence_state=EvidenceState.ENGINEERING_GAP,
                confidence=DiagnosisConfidence.HIGH,
                rationale=(
                    "no scientific result was admitted because the frozen "
                    "intent calendar rejected out-of-calendar gap rows; the "
                    "typed engineering disposition requires a distinct "
                    "successor protocol"
                ),
                counterfactual=(
                    "the corrected eligible-day-only successor can answer the "
                    "unchanged primary question without counting this "
                    "engineering failure as scientific evidence"
                ),
                reopen_condition=(
                    "continue only through a preregistered successor Study "
                    "bound to the requires_scientific_change disposition and "
                    "the corrected Executable identities"
                ),
            ),
            operation_id=operation_id,
        ).result
    control = writer.read_control()
    if control is None:
        raise RuntimeError("STU-0122 diagnosis lost terminal control state")
    return {
        "next_action": control["next_action"],
        "revision": control["revision"],
        "schema": "stu0122_intent_calendar_diagnosis.v1",
        "study_diagnosis_id": result.get("study_diagnosis_id"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--terminal", action="store_true")
    parser.add_argument("--diagnose", action="store_true")
    arguments = parser.parse_args()
    if sum((arguments.open, arguments.terminal, arguments.diagnose)) > 1:
        raise SystemExit("choose one STU-0122 Repair action")
    writer = _writer()
    result = (
        open_repair(writer)
        if arguments.open
        else conclude_and_close(writer)
        if arguments.terminal
        else diagnose_engineering_gap(writer)
        if arguments.diagnose
        else plan_repair(writer)
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
