"""Repair, generic-engine, and runtime-engine authority at Job completion."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.operations.runtime_completion import (
    RuntimeSuccessAuthorityError,
    require_runtime_success_authority,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


class JobCompletionEntryAuthorityError(RuntimeError):
    """Job completion lacks its exact engine-entry authority."""


class JobCompletionEntryIntegrityError(RuntimeError):
    """Projected Repair or engine-entry history is internally invalid."""


EffectiveImplementationResolver = Callable[..., tuple[str, str]]
RuntimeSourceResolver = Callable[..., IndexRecord]


def require_repair_resume_entry(
    *,
    index: LocalIndex,
    job: Mapping[str, Any],
    job_id: str,
    declared_spec: Mapping[str, Any],
    current_execution: RunningJobExecution,
    effective_implementation_resolver: EffectiveImplementationResolver,
) -> None:
    """Require the exact post-Repair implementation and engine re-entry."""

    repair_resume_record_id = job.get("last_repair_resume_record_id")
    repair_head = index.event_head(f"job-repair:{job_id}")
    latest_repair = (
        None
        if repair_head is None
        else index.get(repair_head.record_kind, repair_head.record_id)
    )
    if repair_head is None:
        if repair_resume_record_id is not None:
            raise JobCompletionEntryIntegrityError(
                "Job resume projection exists without Repair history"
            )
        return
    if latest_repair is None or latest_repair.kind != "repair-close":
        raise JobCompletionEntryIntegrityError(
            "Job Repair head is invalid at completion"
        )
    if latest_repair.status == "unrecovered":
        return
    if latest_repair.status != "repaired":
        raise JobCompletionEntryIntegrityError(
            "Job Repair terminal is invalid at completion"
        )
    effective_implementation, repair_close_id = (
        effective_implementation_resolver(
            index,
            job_id=job_id,
            declared_implementation_identity=declared_spec[
                "implementation_identity"
            ],
        )
    )
    repair_resume = (
        None
        if not isinstance(repair_resume_record_id, str)
        else index.get("job-resumed", repair_resume_record_id)
    )
    if (
        repair_close_id != latest_repair.record_id
        or repair_resume is None
        or repair_resume.status != "validated"
        or repair_resume.subject != f"Job:{job_id}"
        or repair_resume.fingerprint != job["hash"]
        or repair_resume.payload.get("execution")
        != current_execution.payload()
        or repair_resume.payload.get("repair_close_record_id")
        != repair_close_id
        or repair_resume.payload.get("effective_implementation_identity")
        != effective_implementation
        or repair_resume.payload.get("callable_identity")
        != declared_spec["callable_identity"]
    ):
        raise JobCompletionEntryAuthorityError(
            "Job completion lacks its exact post-Repair engine re-entry"
        )


def _require_generic_engine_entry(
    *,
    index: LocalIndex,
    job: Mapping[str, Any],
    job_id: str,
    start_record: IndexRecord,
    job_permit_id: str,
    current_execution: RunningJobExecution,
) -> None:
    if start_record.payload.get("runtime") is not None:
        raise JobCompletionEntryAuthorityError(
            "generic Job cannot produce runtime evidence"
        )
    engine_entry_id = job.get("engine_entry_record_id")
    engine_entry = (
        None
        if not isinstance(engine_entry_id, str)
        else index.get("job-engine-entry", engine_entry_id)
    )
    consumed = index.event_record(f"permit:{job_permit_id}", 2)
    if (
        engine_entry is None
        or engine_entry.status != "validated"
        or engine_entry.subject != f"Job:{job_id}"
        or engine_entry.fingerprint != job["hash"]
        or consumed is None
        or engine_entry.payload
        != {
            "execution": current_execution.payload(),
            "permit_consumption_record_id": consumed.record_id,
        }
        or engine_entry.authority_event_id != start_record.authority_event_id
        or engine_entry.authority_sequence != start_record.authority_sequence
    ):
        raise JobCompletionEntryAuthorityError(
            "Job completion lacks its exact engine-entry attestation"
        )


def _require_runtime_source_ineligibility(
    *,
    index: LocalIndex,
    job: Mapping[str, Any],
    job_id: str,
    failure_manifest: Mapping[str, Any],
    provenance: Mapping[str, Any],
    direction: object,
    runtime_source_resolver: RuntimeSourceResolver,
) -> None:
    source_id = failure_manifest["source_contract_id"]
    source_state_id = failure_manifest["source_state_record_id"]
    candidate_head = index.event_head(
        f"candidate:{provenance.get('executable_id', '')}"
    )
    candidate = (
        None
        if candidate_head is None
        else index.get(candidate_head.record_kind, candidate_head.record_id)
    )
    source_head = index.event_head(f"source:{source_id}")
    source_state = index.get("source-state", source_state_id)
    if (
        candidate is None
        or candidate.record_id != provenance.get("candidate_id")
        or source_id
        not in candidate.payload.get("executable", {}).get(
            "source_contracts", []
        )
        or source_head is None
        or source_head.record_id != source_state_id
        or source_state is None
        or source_state.subject != f"Source:{source_id}"
    ):
        raise JobCompletionEntryAuthorityError(
            "runtime source ineligibility lacks its exact current source head"
        )
    if source_state.status == "runtime_eligible":
        if (
            isinstance(direction, Mapping)
            and direction.get("kind")
            == "complete_runtime_source_ineligibility"
        ):
            raise JobCompletionEntryAuthorityError(
                "runtime drift completion does not bind a suspended source"
            )
        try:
            runtime_source_resolver(
                index,
                source_id,
                freshness_required=False,
            )
        except JobCompletionEntryAuthorityError as exc:
            raise JobCompletionEntryAuthorityError(
                "runtime source ineligibility is not a typed stale source"
            ) from exc
        try:
            runtime_source_resolver(
                index,
                source_id,
                freshness_required=True,
            )
        except JobCompletionEntryAuthorityError:
            return
        raise JobCompletionEntryAuthorityError(
            "runtime source remains eligible at Job completion"
        )
    if source_state.status != "suspended":
        raise JobCompletionEntryAuthorityError(
            "runtime source ineligibility is neither stale nor suspended"
        )
    observation_id = source_state.payload.get(
        "runtime_source_drift_observation_id"
    )
    observation = (
        None
        if not isinstance(observation_id, str)
        else index.get("runtime-source-drift-observation", observation_id)
    )
    if (
        not isinstance(direction, Mapping)
        or set(direction)
        != {
            "job_id",
            "kind",
            "observation_id",
            "source_contract_id",
            "source_state_record_id",
        }
        or direction.get("kind") != "complete_runtime_source_ineligibility"
        or direction.get("job_id") != job_id
        or direction.get("source_contract_id") != source_id
        or direction.get("source_state_record_id") != source_state_id
        or direction.get("observation_id") != observation_id
        or observation is None
        or observation.status != "fail_closed"
        or observation.subject != f"Job:{job_id}"
        or observation.fingerprint != job["hash"]
        or observation.payload.get("source_contract_id") != source_id
        or observation.payload.get("prior_source_state_record_id")
        == source_state_id
        or observation.payload.get("artifact_hash")
        not in failure_manifest["minimum_reproduction_evidence"]
    ):
        raise JobCompletionEntryAuthorityError(
            "runtime source drift completion lacks its exact typed observation"
        )


def require_completion_engine_entry(
    *,
    control: Mapping[str, Any],
    index: LocalIndex,
    job: Mapping[str, Any],
    job_id: str,
    declaration: IndexRecord,
    start_record: IndexRecord,
    start_record_id: str,
    job_permit_id: str,
    current_execution: RunningJobExecution,
    runtime_binding: object,
    outcome: str,
    failure_manifest: Mapping[str, Any] | None,
    engineering_disposition: Mapping[str, Any] | None,
    direction: object,
    engineering_fixture: bool,
    runtime_source_resolver: RuntimeSourceResolver,
) -> dict[str, Any] | None:
    """Verify exact generic/runtime entry and return bound runtime provenance."""

    if runtime_binding is None:
        _require_generic_engine_entry(
            index=index,
            job=job,
            job_id=job_id,
            start_record=start_record,
            job_permit_id=job_permit_id,
            current_execution=current_execution,
        )
        return None
    provenance = start_record.payload.get("runtime")
    if not isinstance(provenance, dict):
        raise JobCompletionEntryAuthorityError(
            "runtime Job start lacks RuntimePermit provenance"
        )
    source_ineligibility_failure = bool(
        failure_manifest is not None
        and failure_manifest["failure_kind"]
        == "runtime_source_ineligibility"
    )
    runtime_entry_id = job.get("runtime_entry_record_id")
    runtime_entry = (
        None
        if not isinstance(runtime_entry_id, str)
        else index.get("runtime-engine-entry", runtime_entry_id)
    )
    if (
        runtime_entry is None
        and not source_ineligibility_failure
        and engineering_disposition is None
    ):
        raise JobCompletionEntryAuthorityError(
            "runtime Job completion lacks its exact engine-entry attestation"
        )
    if runtime_entry is not None:
        if (
            runtime_entry.status != "validated"
            or runtime_entry.subject != f"Job:{job_id}"
            or runtime_entry.fingerprint != job["hash"]
            or runtime_entry.payload.get("job_start_record_id")
            != start_record_id
            or runtime_entry.payload.get("runtime_permit_id")
            != provenance.get("runtime_permit_id")
            or runtime_entry.payload.get("candidate_id")
            != provenance.get("candidate_id")
            or runtime_entry.payload.get("source_receipt_ids")
            != sorted(provenance.get("source_receipt_ids", []))
        ):
            raise JobCompletionEntryAuthorityError(
                "runtime Job completion lacks its exact engine-entry attestation"
            )
        if outcome == "success":
            try:
                require_runtime_success_authority(
                    control=control,
                    index=index,
                    job=job,
                    declaration=declaration,
                    start_record=start_record,
                    runtime_entry=runtime_entry,
                    runtime_binding=runtime_binding,
                    provenance=provenance,
                    engineering_fixture=engineering_fixture,
                    require_runtime_source=runtime_source_resolver,
                )
            except RuntimeSuccessAuthorityError as exc:
                raise JobCompletionEntryAuthorityError(str(exc)) from exc
        provenance = {
            **provenance,
            "runtime_entry_record_id": runtime_entry_id,
        }
    if source_ineligibility_failure:
        assert failure_manifest is not None
        _require_runtime_source_ineligibility(
            index=index,
            job=job,
            job_id=job_id,
            failure_manifest=failure_manifest,
            provenance=provenance,
            direction=direction,
            runtime_source_resolver=runtime_source_resolver,
        )
    return provenance


__all__ = [
    "JobCompletionEntryAuthorityError",
    "JobCompletionEntryIntegrityError",
    "require_completion_engine_entry",
    "require_repair_resume_entry",
]
