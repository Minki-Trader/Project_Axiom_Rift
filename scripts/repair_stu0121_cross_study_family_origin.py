"""Repair STU-0121's duplicated obligation/family-origin equality check."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.run_stu0071_cost_aware_execution_pair_replay import (  # noqa: E402
    PERMIT_EXPIRY_UTC,
    STUDY_ID,
    build_design,
)
from axiom_rift.core.canonical import canonical_bytes  # noqa: E402
from axiom_rift.operations.fixed_hold_repair_equivalence import (  # noqa: E402
    FixedHoldAuthorityCorrectionEquivalenceValidator,
)
from axiom_rift.operations.fixed_hold_replay_workflow import (  # noqa: E402
    fixed_hold_replay_repair_operation_ids,
    require_stable_head,
)
from axiom_rift.operations.permits import (  # noqa: E402
    Permit,
    PermitAuthority,
    PermitKeyStore,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.running_job import (  # noqa: E402
    effective_running_job_implementation,
)
from axiom_rift.operations.validation import (  # noqa: E402
    EvidenceValidatorRegistry,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.cost_aware_execution_pair_runtime import (  # noqa: E402
    CALLABLE_IDENTITY,
    cost_aware_execution_pair_job_implementation_sha256,
    materialize_cost_aware_execution_pair_job_implementation,
)
from axiom_rift.research.fixed_hold_replay_runtime import (  # noqa: E402
    materialize_running_job_implementation_repair_proof,
)
from axiom_rift.research.validation_v2 import (  # noqa: E402
    ScientificAdjudicationValidatorV2,
)


FAILURE_MESSAGE = (
    "fixed-hold historical family differs from its obligation"
)
ROOT_CAUSES = {
    1: (
        "running Job context duplicated family admission by requiring the "
        "replay obligation origin and the accepted statistical family origin "
        "to match"
    ),
    2: (
        "running Job context compared the Study proposal's obligation origin "
        "with the accepted statistical family origin instead of the replay "
        "obligation origin"
    ),
}
EXPLANATIONS = {
    1: (
        "remove a duplicated cross-study origin equality check without "
        "changing the registered paired-policy scientific protocol"
    ),
    2: (
        "bind the Study proposal origin to the replay obligation while "
        "retaining the separately authenticated statistical family origin"
    ),
}


def _writer() -> StateWriter:
    registry = EvidenceValidatorRegistry(
        (
            ScientificAdjudicationValidatorV2(),
            FixedHoldAuthorityCorrectionEquivalenceValidator(),
        )
    )
    writer = StateWriter(ROOT, validation_registry=registry)
    writer.permit_authority = PermitAuthority(
        PermitKeyStore(ROOT / "local" / "permit.key").load_or_create()
    )
    require_stable_head(writer, explicit_recovery=True)
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
        raise RuntimeError(f"Repair operation is malformed: {operation_id}")
    return result


def _context(writer: StateWriter) -> dict[str, Any]:
    design = build_design(writer)
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
            raise RuntimeError("STU-0121 Repair requires its exact active Job")
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
        ):
            raise RuntimeError("STU-0121 Repair lost its Job declaration")
        member = next(
            (
                item
                for item in design.members
                if item.executable.identity == subject["id"]
            ),
            None,
        )
        if member is None:
            raise RuntimeError("STU-0121 Repair Job is outside its exact pair")
        declared_identity = spec.get("implementation_identity")
        if not isinstance(declared_identity, str):
            raise RuntimeError("STU-0121 declared implementation is absent")
        old_identity, prior_close_record_id = (
            effective_running_job_implementation(
                index,
                job_id=str(job["id"]),
                declared_implementation_identity=declared_identity,
            )
        )
        repair_head = index.event_head(f"job-repair:{job['id']}")
        episode = (
            repair.get("episode")
            if isinstance(repair, Mapping)
            else 1 if repair_head is None else repair_head.sequence + 1
        )
        if (
            type(episode) is not int
            or episode not in ROOT_CAUSES
            or (
                repair is not None
                and repair.get("predecessor_repair_close_record_id")
                != prior_close_record_id
            )
        ):
            raise RuntimeError("STU-0121 Repair episode is not exact")
    new_identity = cost_aware_execution_pair_job_implementation_sha256()
    if (
        not isinstance(old_identity, str)
        or len(old_identity) != 64
        or old_identity == new_identity
    ):
        raise RuntimeError("STU-0121 Repair implementation pair is not changed")
    operation_ids = fixed_hold_replay_repair_operation_ids(
        design.spec,
        member,
        episode=episode,
    )
    return {
        "control": control,
        "design": design,
        "episode": episode,
        "explanation": EXPLANATIONS[episode],
        "job": dict(job),
        "member": member,
        "new_implementation_identity": new_identity,
        "old_implementation_identity": old_identity,
        "operation_ids": operation_ids,
        "repair": None if repair is None else dict(repair),
        "root_cause": ROOT_CAUSES[episode],
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
        "member_ordinal": context["member"].ordinal,
        "repair_episode": context["episode"],
        "new_implementation_identity": context[
            "new_implementation_identity"
        ],
        "old_implementation_identity": context[
            "old_implementation_identity"
        ],
        "operation_ids": context["operation_ids"].by_role(),
        "revision": context["control"]["revision"],
        "schema": "stu0121_cross_study_family_origin_repair_plan.v2",
    }


def apply_repair(writer: StateWriter) -> dict[str, Any]:
    context = _context(writer)
    operation_ids = context["operation_ids"]
    existing_close = _operation_result(writer, operation_ids.close)
    if existing_close is not None:
        return {
            "repair_episode": context["episode"],
            "repair_close_record_id": existing_close[
                "repair_close_record_id"
            ],
            "reused": True,
            "revision": writer.read_control()["revision"],
            "schema": "stu0121_cross_study_family_origin_repair_result.v2",
        }
    reproduction = writer.evidence.finalize(
        canonical_bytes(
            {
                "changed_path": (
                    "axiom_rift/operations/running_job_context.py"
                ),
                "exception_type": "RunningJobAuthorityError",
                "failure_message": FAILURE_MESSAGE,
                "job_id": context["job"]["id"],
                "new_implementation_identity": context[
                    "new_implementation_identity"
                ],
                "old_implementation_identity": context[
                    "old_implementation_identity"
                ],
                "repair_episode": context["episode"],
                "root_cause": context["root_cause"],
                "schema": (
                    "stu0121_cross_study_family_origin_reproduction.v2"
                ),
                "scientific_semantics_changed": False,
                "study_id": STUDY_ID,
            }
        )
    )
    permit_result = _operation_result(writer, operation_ids.permit)
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
            operation_id=operation_ids.permit,
        )
    else:
        permit_payload = permit_result.get("permit")
        if not isinstance(permit_payload, Mapping):
            raise RuntimeError("STU-0121 Repair permit payload is absent")
        permit = Permit.from_mapping(permit_payload)
    open_result = _operation_result(writer, operation_ids.open)
    if open_result is None:
        opened = writer.open_repair(
            permit=permit,
            failure={
                "failure_kind": "engineering",
                "interrupted_action": context["spec"]["callable_identity"],
                "minimum_reproduction_evidence": [reproduction.sha256],
                "root_cause": context["root_cause"],
            },
            operation_id=operation_ids.open,
        )
        repair_id = opened.result["repair_id"]
    else:
        repair_id = open_result.get("repair_id")
        if not isinstance(repair_id, str):
            raise RuntimeError("STU-0121 active Repair identity is absent")
    proof_hash = materialize_running_job_implementation_repair_proof(
        writer,
        callable_identity=CALLABLE_IDENTITY,
        implementation_materializer=(
            materialize_cost_aware_execution_pair_job_implementation
        ),
        explanation=context["explanation"],
        verification_evidence_hashes=(),
    )
    closed = writer.close_repair(
        changed_cause_proof_hash=proof_hash,
        operation_id=operation_ids.close,
    )
    control = writer.read_control()
    if control is None:
        raise RuntimeError("STU-0121 Repair lost control state")
    return {
        "effective_implementation_identity": closed.result[
            "effective_implementation_identity"
        ],
        "repair_episode": context["episode"],
        "repair_close_record_id": closed.result["repair_close_record_id"],
        "repair_id": repair_id,
        "reused": closed.reused,
        "revision": control["revision"],
        "schema": "stu0121_cross_study_family_origin_repair_result.v2",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    writer = _writer()
    result = apply_repair(writer) if arguments.apply else plan_repair(writer)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
