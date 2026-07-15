"""Pure control and record projection after one Job completion is validated.

StateWriter retains all mutation, validation, evidence derivation, commit, and
filesystem cleanup authority.  This module only derives the exact downstream
action, holdout projection, and immutable supplemental records from an already
constructed completion record and its declaration.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.storage.index import IndexRecord, LocalIndex


class JobCompletionProjectionError(RuntimeError):
    """A completed Job has no valid typed downstream projection."""


class JobCompletionProjectionIntegrityError(JobCompletionProjectionError):
    """Durable completion context required for recovery is unavailable."""


RecordBuilder = Callable[..., IndexRecord]


@dataclass(frozen=True, slots=True)
class JobCompletionProjection:
    """Pure post-completion changes for StateWriter to commit atomically."""

    next_action: Mapping[str, Any]
    active_holdout_evaluation: Mapping[str, Any] | None
    supplemental_records: tuple[IndexRecord, ...]


def _copy(value: Mapping[str, Any]) -> dict[str, Any]:
    copied = parse_canonical(canonical_bytes(dict(value)))
    assert isinstance(copied, dict)
    return dict(copied)


def _require_ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise JobCompletionProjectionError(f"{name} must be non-empty ASCII")
    return value


def _require_digest(name: str, value: object) -> str:
    text = _require_ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise JobCompletionProjectionError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


def _candidate_engineering_gap_action(
    *,
    completion: IndexRecord,
    candidate_context: object,
    engineering_disposition: object,
    work_context: str,
    target_id: str,
) -> dict[str, Any]:
    if (
        not isinstance(candidate_context, Mapping)
        or not isinstance(candidate_context.get("executable_id"), str)
        or not isinstance(engineering_disposition, Mapping)
    ):
        raise JobCompletionProjectionIntegrityError(
            "candidate engineering gap lost its exact context"
        )
    return {
        "completion_record_id": completion.record_id,
        "disposition": engineering_disposition["disposition"],
        "executable_id": candidate_context["executable_id"],
        "job_id": completion.payload["job_id"],
        "kind": "resolve_candidate_engineering_gap",
        "resume_condition": engineering_disposition["resume_condition"],
        "successor_scope": engineering_disposition["successor_scope"],
        "target_id": target_id,
        "work_context": work_context,
    }


def _holdout_operational_gap_record(
    *,
    completion: IndexRecord,
    holdout_binding: Mapping[str, Any],
    record_builder: RecordBuilder,
) -> IndexRecord:
    failure_manifest = completion.payload["failure"]
    gap_payload = {
        "completion_record_id": completion.record_id,
        "engineering_disposition_hash": failure_manifest[
            "repair_disposition_hash"
        ],
        "holdout_id": holdout_binding["holdout_id"],
        "job_id": completion.payload["job_id"],
        "scientific_failure_delta": 0,
        "scientific_trial_delta": 0,
        "sealed_holdout_preserved": True,
    }
    gap_id = canonical_digest(
        domain="holdout-evaluation-operational-gap",
        payload=gap_payload,
    )
    return record_builder(
        kind="holdout-evaluation-operational-gap",
        record_id=gap_id,
        subject=f"Holdout:{holdout_binding['holdout_id']}",
        status="pre_reveal_engineering_gap",
        fingerprint=holdout_binding["holdout_id"].removeprefix("holdout:"),
        payload=gap_payload,
    )


def _project_completion_route(
    *,
    declaration: IndexRecord,
    completion: IndexRecord,
    active_holdout: Mapping[str, Any] | None,
    pre_reveal_holdout_engineering_gap: bool,
    engineering_fixture: bool,
    record_builder: RecordBuilder,
) -> tuple[dict[str, Any], dict[str, Any] | None, tuple[IndexRecord, ...]]:
    declared_spec = declaration.payload.get("spec")
    if not isinstance(declared_spec, Mapping):
        raise JobCompletionProjectionIntegrityError(
            "current Job spec is unavailable during completion projection"
        )
    job_id = completion.payload["job_id"]
    scientific_manifest = completion.payload.get("scientific")
    engineering_disposition = completion.payload.get("engineering_disposition")
    failure_manifest = completion.payload.get("failure")
    holdout_binding = declared_spec.get("holdout_binding")
    source_binding = declared_spec.get("source_binding")
    external_binding = declared_spec.get("external_dependency_binding")
    component_parity_binding = declared_spec.get("component_parity_binding")
    runtime_binding = declared_spec.get("runtime_binding")
    candidate_context = declaration.payload.get("candidate_execution_context")
    return_next_action = declaration.payload.get("return_next_action")
    projected_holdout = (
        None if active_holdout is None else _copy(active_holdout)
    )
    exact_judgement = {
        "completion_record_id": completion.record_id,
        "job_id": job_id,
        "kind": "judge_job_evidence",
    }
    supplemental_records: list[IndexRecord] = []

    if holdout_binding is not None:
        if pre_reveal_holdout_engineering_gap:
            if (
                scientific_manifest is not None
                or engineering_disposition is None
                or not isinstance(candidate_context, Mapping)
                or not isinstance(candidate_context.get("executable_id"), str)
            ):
                raise JobCompletionProjectionError(
                    "pre-reveal holdout gap lacks exact engineering provenance"
                )
            supplemental_records.append(
                _holdout_operational_gap_record(
                    completion=completion,
                    holdout_binding=holdout_binding,
                    record_builder=record_builder,
                )
            )
            next_action = _candidate_engineering_gap_action(
                completion=completion,
                candidate_context=candidate_context,
                engineering_disposition=engineering_disposition,
                work_context="pre_reveal_holdout",
                target_id=holdout_binding["holdout_id"],
            )
        elif scientific_manifest is not None:
            assert isinstance(projected_holdout, dict)
            projected_holdout["status"] = (
                "evaluation_completed_pending_disposition"
            )
            next_action = {
                "completion_record_id": completion.record_id,
                "holdout_id": projected_holdout["holdout_id"],
                "job_id": job_id,
                "kind": "record_holdout_evaluation",
            }
        elif engineering_disposition is not None:
            assert isinstance(projected_holdout, dict)
            projected_holdout["status"] = "engineering_gap_pending_disposition"
            next_action = {
                "completion_record_id": completion.record_id,
                "holdout_id": projected_holdout["holdout_id"],
                "job_id": job_id,
                "kind": "dispose_revealed_holdout_engineering_gap",
            }
        else:
            raise JobCompletionProjectionError(
                "revealed holdout completion lacks scientific evidence or a typed engineering gap"
            )
        if isinstance(projected_holdout, dict):
            projected_holdout["completion_record_id"] = completion.record_id
    elif isinstance(source_binding, Mapping) and completion.status == "success":
        source_resume_action = (
            exact_judgement
            if declaration.payload.get("batch_id") is not None
            else return_next_action
        )
        if not isinstance(source_resume_action, Mapping):
            raise JobCompletionProjectionIntegrityError(
                "source Job lost its exact return action"
            )
        next_action = {
            "completion_record_id": completion.record_id,
            "job_id": job_id,
            "kind": "record_source_eligibility",
            "resume_next_action": _copy(source_resume_action),
            "source_contract_id": source_binding["source_contract_id"],
        }
    elif (
        isinstance(source_binding, Mapping)
        and declaration.payload.get("batch_id") is None
        and not isinstance(candidate_context, Mapping)
    ):
        if not isinstance(return_next_action, Mapping):
            raise JobCompletionProjectionIntegrityError(
                "failed source Job lost its exact return action"
            )
        next_action = _copy(return_next_action)
    elif (
        isinstance(source_binding, Mapping)
        and isinstance(candidate_context, Mapping)
        and engineering_disposition is not None
    ):
        next_action = _candidate_engineering_gap_action(
            completion=completion,
            candidate_context=candidate_context,
            engineering_disposition=engineering_disposition,
            work_context="source",
            target_id=source_binding["source_contract_id"],
        )
    elif isinstance(external_binding, Mapping):
        next_action = {
            "completion_record_id": completion.record_id,
            "job_id": job_id,
            "kind": "judge_external_dependency_evidence",
        }
    elif declaration.payload.get("batch_id") is not None or isinstance(
        component_parity_binding,
        Mapping,
    ):
        next_action = exact_judgement
    elif isinstance(candidate_context, Mapping):
        executable_id = candidate_context.get("executable_id")
        if not isinstance(executable_id, str):
            raise JobCompletionProjectionIntegrityError(
                "candidate Job completion context is malformed"
            )
        if engineering_disposition is not None:
            if not isinstance(runtime_binding, Mapping):
                raise JobCompletionProjectionError(
                    "candidate engineering gap has no typed work context"
                )
            next_action = _candidate_engineering_gap_action(
                completion=completion,
                candidate_context=candidate_context,
                engineering_disposition=engineering_disposition,
                work_context="runtime",
                target_id=runtime_binding["evidence_depth"],
            )
        else:
            next_action = {
                "executable_id": executable_id,
                "kind": "plan_candidate_bound_evidence",
            }
    elif engineering_fixture and isinstance(return_next_action, Mapping):
        next_action = _copy(return_next_action)
    else:
        raise JobCompletionProjectionError(
            "Job completion has no typed operational consumer"
        )
    return next_action, projected_holdout, tuple(supplemental_records)


def _job_success_cache_record(
    *,
    declaration: IndexRecord,
    completion: IndexRecord,
    record_builder: RecordBuilder,
) -> IndexRecord:
    declared_spec = declaration.payload["spec"]
    success_fingerprint = _require_digest(
        "Job success fingerprint",
        declaration.payload.get("success_fingerprint"),
    )
    candidate_context = declaration.payload.get("candidate_execution_context")
    return record_builder(
        kind="job-success-cache",
        record_id=success_fingerprint,
        subject=f"Mission:{declaration.payload['mission_id']}",
        status="reusable",
        fingerprint=completion.fingerprint,
        payload={
            "completion_record_id": completion.record_id,
            "expected_outputs": list(declared_spec["expected_outputs"]),
            "job_id": completion.payload["job_id"],
            "mission_id": declaration.payload["mission_id"],
            "output_classes": dict(declared_spec["output_classes"]),
            "candidate_execution_context": candidate_context,
            "implementation_source_authority": (
                {
                    "authority": declaration.payload.get(
                        "source_closure_authority"
                    ),
                    "schema": "job_implementation_source_binding.v1",
                }
                if "source_closure_authority" in declaration.payload
                else None
            ),
            "external_observed_development_binding": declaration.payload.get(
                "external_observed_development_binding"
            ),
            **(
                {
                    "observed_development_binding": declaration.payload[
                        "observed_development_binding"
                    ]
                }
                if "observed_development_binding" in declaration.payload
                else {}
            ),
        },
    )


def _external_dependency_attempt_record(
    *,
    index: LocalIndex,
    declaration: IndexRecord,
    completion: IndexRecord,
    external_binding: Mapping[str, Any],
    record_builder: RecordBuilder,
) -> IndexRecord:
    dependency_id = external_binding["dependency_id"]
    dependency_head = index.event_head(f"external-dependency:{dependency_id}")
    attempt_sequence = 1 if dependency_head is None else dependency_head.sequence + 1
    attempt_id = canonical_digest(
        domain="external-dependency-attempt",
        payload={
            "completion_record_id": completion.record_id,
            "dependency_id": dependency_id,
            "recovery_path_id": external_binding["recovery_path_id"],
        },
    )
    external_manifest = completion.payload.get("external")
    return record_builder(
        kind="external-dependency-attempt",
        record_id=attempt_id,
        subject=f"Mission:{declaration.payload['mission_id']}",
        status=(
            "available"
            if completion.status == "success"
            else (
                "external_unavailable"
                if external_manifest is not None
                and external_manifest["verdict"] == "failed"
                else (
                    "external_unresolved"
                    if external_manifest is not None
                    and external_manifest["verdict"] == "not_evaluable"
                    else "local_failure"
                )
            )
        ),
        fingerprint=dependency_id,
        payload={
            "completion_record_id": completion.record_id,
            "external": external_manifest,
            **external_binding,
        },
        event_stream=f"external-dependency:{dependency_id}",
        event_sequence=attempt_sequence,
    )


def project_job_completion(
    *,
    index: LocalIndex,
    declaration: IndexRecord,
    completion: IndexRecord,
    active_holdout: Mapping[str, Any] | None,
    pre_reveal_holdout_engineering_gap: bool,
    engineering_fixture: bool,
    record_builder: RecordBuilder,
) -> JobCompletionProjection:
    """Derive one exact downstream projection without mutating its inputs."""

    next_action, projected_holdout, route_records = _project_completion_route(
        declaration=declaration,
        completion=completion,
        active_holdout=active_holdout,
        pre_reveal_holdout_engineering_gap=(
            pre_reveal_holdout_engineering_gap
        ),
        engineering_fixture=engineering_fixture,
        record_builder=record_builder,
    )
    records = list(route_records)
    if completion.status == "success":
        records.append(
            _job_success_cache_record(
                declaration=declaration,
                completion=completion,
                record_builder=record_builder,
            )
        )
    declared_spec = declaration.payload["spec"]
    external_binding = declared_spec.get("external_dependency_binding")
    if isinstance(external_binding, dict):
        records.append(
            _external_dependency_attempt_record(
                index=index,
                declaration=declaration,
                completion=completion,
                external_binding=external_binding,
                record_builder=record_builder,
            )
        )
    return JobCompletionProjection(
        next_action=next_action,
        active_holdout_evaluation=projected_holdout,
        supplemental_records=tuple(records),
    )


__all__ = [
    "JobCompletionProjection",
    "JobCompletionProjectionError",
    "JobCompletionProjectionIntegrityError",
    "project_job_completion",
]
