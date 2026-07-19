"""Fail-closed validation for prospective engineering-gap successor work."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from axiom_rift.operations.repair_semantic_change_authority import (
    RepairSemanticChangeAuthorityError,
    normalize_semantic_change_successor_artifact,
)
from axiom_rift.research.portfolio_projection import (
    PortfolioProjectionError,
    executable_from_identity_payload,
)
from axiom_rift.research.prospective_engineering_reentry import (
    ProspectiveEngineeringReentry,
)
from axiom_rift.research.semantic_question import SemanticQuestionCore
from axiom_rift.storage.index import LocalIndex, LocalIndexView


PROSPECTIVE_ENGINEERING_REENTRY_VALIDATION_SCHEMA = (
    "prospective_engineering_reentry_validation.v1"
)


class ProspectiveEngineeringReentryValidationError(ValueError):
    """Raised when durable predecessor and successor authority do not join."""


def _references(value: object) -> set[tuple[str, str]]:
    if not isinstance(value, list):
        raise ProspectiveEngineeringReentryValidationError(
            "engineering reentry diagnosis basis is malformed"
        )
    result: set[tuple[str, str]] = set()
    for item in value:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"kind", "record_id"}
            or type(item.get("kind")) is not str
            or type(item.get("record_id")) is not str
        ):
            raise ProspectiveEngineeringReentryValidationError(
                "engineering reentry diagnosis basis is malformed"
            )
        result.add((item["kind"], item["record_id"]))
    return result


def _successor_hash_from_disposition(
    payload: Mapping[str, Any],
) -> str:
    validation = payload.get("disposition_validation")
    semantic = (
        None
        if not isinstance(validation, Mapping)
        else validation.get("semantic_change_validation")
    )
    registered = (
        None
        if not isinstance(semantic, Mapping)
        else semantic.get("validation")
    )
    facts = (
        None
        if not isinstance(registered, Mapping)
        else registered.get("facts")
    )
    binding = (
        None if not isinstance(facts, Mapping) else facts.get("binding")
    )
    context = (
        None
        if not isinstance(binding, Mapping)
        else binding.get("context")
    )
    successor_hash = (
        None
        if not isinstance(context, Mapping)
        else context.get("proposed_successor_artifact_sha256")
    )
    artifacts = (
        None
        if not isinstance(registered, Mapping)
        else registered.get("result_artifact_hashes")
    )
    if (
        not isinstance(semantic, Mapping)
        or semantic.get("schema")
        != "engineering_semantic_change_necessity_validation.v2"
        or not isinstance(registered, Mapping)
        or registered.get("schema")
        != "engineering_repair_registered_validation.v2"
        or registered.get("verdict") != "passed"
        or registered.get("verification_kind") != "semantic_change"
        or type(successor_hash) is not str
        or type(artifacts) is not list
        or successor_hash not in artifacts
    ):
        raise ProspectiveEngineeringReentryValidationError(
            "engineering disposition lacks its validated successor artifact"
        )
    return successor_hash


def require_prospective_engineering_reentry(
    index: LocalIndex | LocalIndexView,
    *,
    artifact_reader: Callable[[str], bytes],
    plan: ProspectiveEngineeringReentry,
    mission_id: str,
    portfolio_snapshot_id: str,
    portfolio_action: str,
    target_axis: Mapping[str, Any],
    baseline_executable_id: str,
) -> dict[str, Any]:
    """Validate one exact non-credit successor selection from durable records."""

    if (
        not isinstance(plan, ProspectiveEngineeringReentry)
        or plan.mission_id != mission_id
        or plan.portfolio_snapshot_id != portfolio_snapshot_id
        or plan.portfolio_action != portfolio_action
        or plan.target_axis_id != target_axis.get("axis_id")
        or plan.target_axis_identity != target_axis.get("axis_identity")
        or plan.successor_baseline_executable_id != baseline_executable_id
    ):
        raise ProspectiveEngineeringReentryValidationError(
            "engineering reentry selection differs from its typed plan"
        )
    diagnosis = index.get("study-diagnosis", plan.study_diagnosis_id)
    study = index.get("study-open", plan.predecessor_study_id)
    close = index.get("study-close", plan.study_close_record_id)
    completion = index.get("job-completed", plan.completion_record_id)
    disposition = index.get("repair-close", plan.disposition_record_id)
    if disposition is None:
        disposition = index.get(
            "engineering-failure-disposition",
            plan.disposition_record_id,
        )
    if (
        diagnosis is None
        or diagnosis.status != "engineering_gap"
        or diagnosis.subject != f"Study:{plan.predecessor_study_id}"
        or diagnosis.payload.get("mission_id") != mission_id
        or diagnosis.payload.get("portfolio_snapshot_id")
        != portfolio_snapshot_id
        or diagnosis.payload.get("portfolio_axis_id")
        != plan.target_axis_id
        or diagnosis.payload.get("portfolio_axis_identity")
        != plan.target_axis_identity
        or diagnosis.payload.get("study_close_record_id")
        != plan.study_close_record_id
        or study is None
        or study.subject != f"Study:{plan.predecessor_study_id}"
        or study.payload.get("mission_id") != mission_id
        or close is None
        or close.subject != f"Study:{plan.predecessor_study_id}"
        or close.status not in {"evidence_gap", "not_evaluable"}
        or completion is None
        or completion.payload.get("scientific") is not None
        or not isinstance(completion.payload.get("failure"), Mapping)
        or completion.payload["failure"].get("failure_kind")
        not in {"engineering", "not_evaluable"}
        or completion.payload.get("engineering_disposition_record_id")
        != plan.disposition_record_id
        or disposition is None
        or disposition.subject
        != f"Job:{completion.payload.get('job_id')}"
        or disposition.payload.get("disposition_hash")
        != plan.disposition_hash
        or not isinstance(disposition.payload.get("disposition"), Mapping)
        or disposition.payload["disposition"].get("disposition")
        != "requires_scientific_change"
        or disposition.payload["disposition"].get("job_id")
        != completion.payload.get("job_id")
    ):
        raise ProspectiveEngineeringReentryValidationError(
            "engineering reentry predecessor authority is absent or stale"
        )
    diagnosis_basis = _references(diagnosis.payload.get("evidence_basis"))
    required_diagnosis_basis = {
        ("job-completed", plan.completion_record_id),
        ("study-close", plan.study_close_record_id),
    }
    if not required_diagnosis_basis.issubset(diagnosis_basis):
        raise ProspectiveEngineeringReentryValidationError(
            "engineering reentry diagnosis omits its exact gap evidence"
        )
    lineage = plan.semantic_question_lineage
    try:
        predecessor_core = SemanticQuestionCore.from_question_manifest(
            study.payload.get("question", {})
        )
    except (TypeError, ValueError) as exc:
        raise ProspectiveEngineeringReentryValidationError(
            "engineering reentry predecessor question is malformed"
        ) from exc
    required_lineage_basis = {
        f"job-completed:{plan.completion_record_id}",
        f"study-close:{plan.study_close_record_id}",
        f"study-diagnosis:{plan.study_diagnosis_id}",
        f"study-open:{plan.predecessor_study_id}",
    }
    if (
        lineage.predecessor_core_id != predecessor_core.identity
        or not required_lineage_basis.issubset(lineage.basis_record_ids)
        or index.get("study-open", plan.successor_study_id) is not None
    ):
        raise ProspectiveEngineeringReentryValidationError(
            "engineering reentry lineage does not bind the exact predecessor"
        )
    successor_hash = _successor_hash_from_disposition(disposition.payload)
    if successor_hash != plan.successor_artifact_hash:
        raise ProspectiveEngineeringReentryValidationError(
            "engineering reentry selected another successor artifact"
        )
    try:
        successor = normalize_semantic_change_successor_artifact(
            artifact_reader(successor_hash)
        )
        successor_executable = executable_from_identity_payload(
            successor["executable_manifest"]
        )
    except (
        OSError,
        RepairSemanticChangeAuthorityError,
        PortfolioProjectionError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        raise ProspectiveEngineeringReentryValidationError(
            "engineering reentry successor artifact is invalid"
        ) from exc
    job_spec = successor["job_spec"]
    subject = job_spec.get("evidence_subject")
    expected_outputs = job_spec.get("expected_outputs")
    output_prefix = f"scientific/{plan.successor_study_id}/"
    predecessor_executable_ids = {
        record.record_id
        for record in index.records_by_kind("trial")
        if record.payload.get("study_id") == plan.predecessor_study_id
    }
    if (
        successor.get("successor_scope") != "executable"
        or not isinstance(subject, Mapping)
        or subject.get("kind") != "Executable"
        or subject.get("id") != successor_executable.identity
        or successor_executable.identity
        != plan.successor_baseline_executable_id
        or successor_executable.identity in predecessor_executable_ids
        or type(expected_outputs) is not list
        or not expected_outputs
        or any(
            type(path) is not str or not path.startswith(output_prefix)
            for path in expected_outputs
        )
    ):
        raise ProspectiveEngineeringReentryValidationError(
            "engineering reentry successor does not bind a distinct Study protocol"
        )
    review_basis = tuple(
        sorted(
            {
                ("job-completed", plan.completion_record_id),
                (disposition.kind, plan.disposition_record_id),
                ("study-close", plan.study_close_record_id),
                ("study-diagnosis", plan.study_diagnosis_id),
            }
        )
    )
    return {
        "engineering_reentry_id": plan.identity,
        "portfolio_action": plan.portfolio_action,
        "required_review_basis": [
            {"kind": kind, "record_id": record_id}
            for kind, record_id in review_basis
        ],
        "schema": PROSPECTIVE_ENGINEERING_REENTRY_VALIDATION_SCHEMA,
        "scientific_claim_delta": 0,
        "scientific_failure_delta": 0,
        "scientific_trial_delta": 0,
        "semantic_question_lineage_id": lineage.identity,
        "successor_artifact_hash": successor_hash,
        "successor_baseline_executable_id": successor_executable.identity,
        "successor_study_id": plan.successor_study_id,
    }


__all__ = [
    "PROSPECTIVE_ENGINEERING_REENTRY_VALIDATION_SCHEMA",
    "ProspectiveEngineeringReentryValidationError",
    "require_prospective_engineering_reentry",
]
