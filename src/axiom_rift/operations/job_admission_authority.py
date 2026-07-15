"""Exact production work-boundary admission for Job declarations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from axiom_rift.operations.external_dependency import ExternalRecoveryPlan
from axiom_rift.storage.index import IndexRecord, LocalIndex


class JobAdmissionAuthorityError(RuntimeError):
    """A Job declaration is outside every exact authorized work boundary."""


RecordBuilder = Callable[..., IndexRecord]
DecisionLoader = Callable[[LocalIndex, str], IndexRecord | None]


def _parity_at_accepted_decision(
    next_action: object,
    parity_binding: object,
) -> bool:
    return bool(
        isinstance(next_action, dict)
        and next_action.get("kind") == "execute_portfolio_decision"
        and isinstance(parity_binding, dict)
        and parity_binding.get("portfolio_decision_id")
        == next_action.get("decision_id")
        and parity_binding.get("portfolio_snapshot_id")
        == next_action.get("portfolio_snapshot_id")
        and parity_binding.get("portfolio_axis_identity")
        == next_action.get("target_axis_identity")
        and parity_binding.get("architecture_chassis_identity")
        == next_action.get("architecture_chassis_identity")
    )


def _candidate_gap_retry_allowed(
    *,
    active_executable: object,
    next_action: object,
    spec: Mapping[str, Any],
) -> bool:
    if not (
        isinstance(active_executable, str)
        and isinstance(next_action, dict)
        and next_action.get("kind") == "resolve_candidate_engineering_gap"
        and next_action.get("executable_id") == active_executable
        and next_action.get("successor_scope") is None
        and spec["evidence_subject"]
        == {"kind": "Executable", "id": active_executable}
    ):
        return False
    work_context = next_action.get("work_context")
    target_id = next_action.get("target_id")
    return bool(
        (
            work_context == "runtime"
            and isinstance(spec.get("runtime_binding"), dict)
            and spec["runtime_binding"].get("evidence_depth") == target_id
        )
        or (
            work_context == "source"
            and isinstance(spec.get("source_binding"), dict)
            and spec["source_binding"].get("source_contract_id") == target_id
        )
        or (
            work_context == "pre_reveal_holdout"
            and isinstance(spec.get("scientific_binding"), dict)
            and isinstance(spec.get("holdout_binding"), dict)
            and spec["holdout_binding"].get("holdout_id") == target_id
        )
    )


def _external_admission(
    *,
    current: Mapping[str, Any],
    science: Mapping[str, Any],
    next_action: object,
    external_binding: object,
    external_plan: ExternalRecoveryPlan | None,
    index: LocalIndex,
    record_builder: RecordBuilder,
) -> tuple[bool, tuple[IndexRecord, ...]]:
    if external_plan is None or not isinstance(external_binding, dict):
        return False, ()
    mission_id = science["active_mission"]
    if external_plan.condition.resume_action.mission_id != mission_id:
        raise JobAdmissionAuthorityError(
            "external recovery plan is bound to another Mission"
        )
    if any(
        science.get(name) is not None
        for name in (
            "active_batch",
            "active_executable",
            "active_holdout_evaluation",
            "active_initiative",
            "active_lineage",
            "active_release",
            "active_repair",
            "active_study",
        )
    ):
        raise JobAdmissionAuthorityError(
            "external recovery Job requires disposed subordinate work"
        )
    plan_record = index.get("external-recovery-plan", external_plan.identity)
    path = external_plan.path(external_binding["recovery_path_id"])
    first_path = external_plan.paths[0]
    unconsumed_first_plan = bool(
        plan_record is not None
        and plan_record.subject == f"Mission:{mission_id}"
        and plan_record.payload == external_plan.to_identity_payload()
        and index.event_head(f"external-recovery:{external_plan.identity}") is None
    )
    first_boundary = bool(
        (plan_record is None or unconsumed_first_plan)
        and path == first_path
        and (
            unconsumed_first_plan
            or external_plan.boundary_event_id
            == current.get("heads", {}).get("journal", {}).get("event_id")
        )
        and next_action
        == external_plan.condition.resume_action.to_next_action()
    )
    continuation_boundary = bool(
        plan_record is not None
        and plan_record.subject == f"Mission:{mission_id}"
        and plan_record.payload == external_plan.to_identity_payload()
        and isinstance(next_action, dict)
        and next_action.get("kind") == "declare_external_dependency_job"
        and next_action.get("recovery_plan_id") == external_plan.identity
        and next_action.get("recovery_path_id") == path.recovery_path_id
        and isinstance(next_action.get("prior_completion_record_ids"), list)
    )
    if not first_boundary or plan_record is not None:
        return first_boundary or continuation_boundary, ()
    return True, (
        record_builder(
            kind="external-recovery-plan",
            record_id=external_plan.identity,
            subject=f"Mission:{mission_id}",
            status="active",
            fingerprint=external_plan.identity.removeprefix(
                "external-recovery-plan:"
            ),
            payload=external_plan.to_identity_payload(),
        ),
    )


def _require_parity_baseline(
    *,
    active_batch: object,
    science: Mapping[str, Any],
    spec: Mapping[str, Any],
    parity_binding: Mapping[str, Any],
    index: LocalIndex,
    active_decision_loader: DecisionLoader,
) -> None:
    if active_batch is not None or science.get("active_study") is not None:
        raise JobAdmissionAuthorityError(
            "pre-Study component parity requires no active Study or Batch"
        )
    decision = active_decision_loader(
        index,
        parity_binding["portfolio_decision_id"],
    )
    baseline = None if decision is None else decision.payload.get(
        "baseline_executable"
    )
    canonical_id = parity_binding["canonical_component_id"]
    if (
        decision is None
        or not isinstance(baseline, dict)
        or canonical_id not in baseline.get("component_identities", [])
        or spec["evidence_subject"]
        != {"kind": "Mission", "id": science["active_mission"]}
    ):
        raise JobAdmissionAuthorityError(
            "component parity canonical endpoint is outside the accepted baseline"
        )


def require_job_admission(
    *,
    engineering_fixture: bool,
    current: Mapping[str, Any],
    science: Mapping[str, Any],
    spec: Mapping[str, Any],
    external_binding: object,
    external_plan: ExternalRecoveryPlan | None,
    index: LocalIndex,
    record_builder: RecordBuilder,
    active_decision_loader: DecisionLoader,
) -> tuple[IndexRecord, ...]:
    """Authorize one declaration and return any first external-plan record."""

    if engineering_fixture:
        return ()
    next_action = current.get("next_action")
    active_batch = science.get("active_batch")
    parity_binding = spec.get("component_parity_binding")
    parity_allowed = _parity_at_accepted_decision(
        next_action,
        parity_binding,
    )
    if isinstance(parity_binding, dict) and not parity_allowed:
        raise JobAdmissionAuthorityError(
            "component parity Job must bind the exact accepted Portfolio Decision"
        )
    batch_allowed = isinstance(active_batch, dict) and next_action == {
        "kind": "declare_job",
        "batch_id": active_batch["id"],
    }
    active_executable = science.get("active_executable")
    candidate_allowed = bool(
        isinstance(active_executable, str)
        and isinstance(next_action, dict)
        and next_action.get("kind") == "plan_candidate_bound_evidence"
        and spec["evidence_subject"]
        == {"kind": "Executable", "id": active_executable}
        and (
            isinstance(spec.get("runtime_binding"), dict)
            or (
                isinstance(spec.get("scientific_binding"), dict)
                and isinstance(spec.get("holdout_binding"), dict)
            )
        )
    )
    source_study_allowed = bool(
        isinstance(science.get("active_study"), str)
        and active_batch is None
        and isinstance(spec.get("source_binding"), dict)
        and next_action
        == {"kind": "freeze_batch", "study_id": science["active_study"]}
        and spec["evidence_subject"]
        == {"kind": "Study", "id": science["active_study"]}
    )
    source_candidate_allowed = bool(
        isinstance(active_executable, str)
        and isinstance(spec.get("source_binding"), dict)
        and next_action
        == {
            "kind": "plan_candidate_bound_evidence",
            "executable_id": active_executable,
        }
        and spec["evidence_subject"]
        == {"kind": "Executable", "id": active_executable}
    )
    gap_retry_allowed = _candidate_gap_retry_allowed(
        active_executable=active_executable,
        next_action=next_action,
        spec=spec,
    )
    external_allowed, records = _external_admission(
        current=current,
        science=science,
        next_action=next_action,
        external_binding=external_binding,
        external_plan=external_plan,
        index=index,
        record_builder=record_builder,
    )
    if not any(
        (
            batch_allowed,
            candidate_allowed,
            external_allowed,
            parity_allowed,
            gap_retry_allowed,
            source_candidate_allowed,
            source_study_allowed,
        )
    ):
        raise JobAdmissionAuthorityError(
            "Job declaration cannot preempt research direction and is outside every exact authorized work boundary"
        )
    if parity_allowed:
        assert isinstance(parity_binding, dict)
        _require_parity_baseline(
            active_batch=active_batch,
            science=science,
            spec=spec,
            parity_binding=parity_binding,
            index=index,
            active_decision_loader=active_decision_loader,
        )
    return records


__all__ = ["JobAdmissionAuthorityError", "require_job_admission"]
