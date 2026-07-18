"""Small command boundary for the reusable fixed-hold replay workflow."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from axiom_rift.operations.fixed_hold_replay_workflow import (
    FixedHoldReplayDesign,
    read_only_summary,
    require_stable_head,
    run_diagnose_stage,
    run_study_close_stage,
)
from axiom_rift.operations.permits import PermitAuthority, PermitKeyStore
from axiom_rift.operations.replay_workflow_recovery import (
    replay_operation_namespace_study_id,
)
from axiom_rift.operations.validation import EvidenceValidatorRegistry
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.fixed_hold_family_job import FixedHoldFamilyJobPacket
from axiom_rift.research.validation_v2 import ScientificAdjudicationValidatorV2


DesignBuilder = Callable[[StateWriter], FixedHoldReplayDesign]
JobRunner = Callable[..., FixedHoldFamilyJobPacket]
ImplementationMaterializer = Callable[[StateWriter], str]


def _completed_study_handoff(
    writer: StateWriter,
    *,
    study_id: str | None,
) -> dict[str, Any] | None:
    """Return the canonical handoff for an already closed replay runner.

    A historical runner is a compatibility surface after its Study closes.  A
    later Portfolio action can legitimately change the current axis meaning,
    so rebuilding the old design at that boundary is both unnecessary and
    misleading.  The immutable Study KPI is the cheap keyed close witness.
    """

    if study_id is None:
        return None
    if type(study_id) is not str or not study_id or not study_id.isascii():
        raise ValueError("fixed-hold replay Study ID must be non-empty ASCII")
    with writer.open_stable_index() as (control, index):
        kpi = index.get("study-kpi", study_id)
        if kpi is None:
            return None
        next_action = control.get("next_action")
        scientific = control.get("scientific")
        diagnosis_id = (
            next_action.get("study_diagnosis_id")
            if isinstance(next_action, Mapping)
            else None
        )
        diagnosis = (
            index.get("study-diagnosis", diagnosis_id)
            if isinstance(diagnosis_id, str)
            else None
        )
    if (
        kpi.record_id != study_id
        or kpi.subject != f"Study:{study_id}"
        or not isinstance(kpi.payload, Mapping)
        or kpi.payload.get("study_id") != study_id
        or not isinstance(next_action, Mapping)
        or not isinstance(scientific, Mapping)
        or scientific.get("active_study") == study_id
    ):
        raise RuntimeError("closed replay Study handoff is malformed")
    pending_diagnosis = (
        next_action.get("kind") == "diagnose_study"
        and next_action.get("study_id") == study_id
    )
    diagnosis_resolution_in_progress = (
        next_action.get("kind")
        == "resolve_historical_replay_obligations"
        and next_action.get("study_id") == study_id
        and isinstance(next_action.get("study_diagnosis_id"), str)
        and isinstance(next_action.get("resume_next_action"), Mapping)
    )
    diagnosis_completed_handoff = (
        next_action.get("kind") == "portfolio_decision"
        and isinstance(diagnosis_id, str)
        and diagnosis is not None
        and diagnosis.subject == f"Study:{study_id}"
        and diagnosis.payload.get("study_id") == study_id
    )
    return {
        "completion_record_id": kpi.payload.get("completion_record_id"),
        "mode": (
            "study_close_pending_diagnosis"
            if pending_diagnosis
            else "diagnosis_resolution_in_progress"
            if diagnosis_resolution_in_progress
            else "diagnosis_completed_handoff"
            if diagnosis_completed_handoff
            else "completed_study_handoff"
        ),
        "next_action": dict(next_action),
        "schema": "fixed_hold_replay_read_only_handoff.v1",
        "state_revision": control.get("revision"),
        "study_id": study_id,
        "study_outcome": kpi.payload.get("outcome"),
    }


def _operation_namespace_handoff(
    writer: StateWriter,
    *,
    operation_prefix: str,
    requested_study_id: str | None,
) -> dict[str, Any] | None:
    """Expose an old one-shot runner instead of rebuilding it as new work."""

    if requested_study_id is None:
        return None
    with writer.open_stable_index() as (control, index):
        owner_study_id = replay_operation_namespace_study_id(
            index,
            operation_prefix,
        )
        if owner_study_id is None or owner_study_id == requested_study_id:
            return None
        owner_kpi = index.get("study-kpi", owner_study_id)
        next_action = control.get("next_action")
        if not isinstance(next_action, Mapping):
            raise RuntimeError(
                "replay operation namespace handoff lost its next action"
            )
    return {
        "mode": (
            "completed_operation_namespace_handoff"
            if owner_kpi is not None
            else "in_progress_operation_namespace_handoff"
        ),
        "next_action": dict(next_action),
        "operation_prefix": operation_prefix,
        "owner_study_id": owner_study_id,
        "requested_study_id": requested_study_id,
        "schema": "fixed_hold_replay_operation_namespace_handoff.v1",
        "state_revision": control.get("revision"),
        "study_outcome": (
            None if owner_kpi is None else owner_kpi.payload.get("outcome")
        ),
    }


def parse_fixed_hold_replay_arguments(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or crash-resumably execute an exact fixed-hold replay "
            "and its post-checkpoint diagnosis."
        )
    )
    parser.add_argument(
        "--stage",
        choices=("study-close", "diagnose"),
        help="omit for a read-only plan",
    )
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--study-close-event-id")
    parser.add_argument("--study-close-revision", type=int)
    return parser.parse_args(argv)


def run_fixed_hold_replay_command(
    *,
    repository_root: str | Path,
    design_builder: DesignBuilder,
    job_runner: JobRunner,
    job_implementation_materializer: ImplementationMaterializer,
    operation_prefix: str,
    study_id: str | None = None,
    argv: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Run one explicit stage; omission of ``--stage`` is read-only."""

    arguments = parse_fixed_hold_replay_arguments(argv)
    if arguments.stage is None:
        if arguments.recover:
            raise RuntimeError("read-only plan does not perform recovery")
        if (
            arguments.study_close_event_id is not None
            or arguments.study_close_revision is not None
        ):
            raise RuntimeError(
                "Study-close authority arguments require diagnose stage"
            )
    elif arguments.stage == "study-close":
        if (
            arguments.study_close_event_id is not None
            or arguments.study_close_revision is not None
        ):
            raise RuntimeError("Study-close stage rejects checkpoint arguments")
    elif (
        arguments.study_close_event_id is None
        or arguments.study_close_revision is None
    ):
        raise RuntimeError(
            "diagnose stage requires exact Study-close event and revision"
        )
    root = Path(repository_root).resolve()
    registry = EvidenceValidatorRegistry(
        (
            (ScientificAdjudicationValidatorV2(),)
            if arguments.stage == "study-close"
            else ()
        )
    )
    writer = StateWriter(root, validation_registry=registry)
    require_stable_head(
        writer,
        explicit_recovery=bool(arguments.stage and arguments.recover),
    )
    handoff = _completed_study_handoff(writer, study_id=study_id)
    if handoff is not None:
        if arguments.stage is None:
            return handoff
        if arguments.stage == "study-close":
            raise RuntimeError(
                "closed replay Study rejects another execution stage"
            )
        if handoff.get("mode") not in {
            "study_close_pending_diagnosis",
            "diagnosis_resolution_in_progress",
            "diagnosis_completed_handoff",
        }:
            raise RuntimeError("closed replay Study has no pending diagnosis")
    namespace_handoff = (
        None
        if handoff is not None
        else _operation_namespace_handoff(
            writer,
            operation_prefix=operation_prefix,
            requested_study_id=study_id,
        )
    )
    if namespace_handoff is not None:
        if arguments.stage is None:
            return namespace_handoff
        raise RuntimeError(
            "replay operation namespace belongs to Study:"
            + str(namespace_handoff["owner_study_id"])
        )
    design = design_builder(writer)
    if arguments.stage is None:
        return dict(read_only_summary(writer, design))

    if arguments.stage == "study-close":
        writer.permit_authority = PermitAuthority(
            PermitKeyStore(root / "local" / "permit.key").load_or_create()
        )
        return run_study_close_stage(
            writer,
            design=design,
            repository_root=root,
            job_runner=job_runner,
            job_implementation_materializer=job_implementation_materializer,
            explicit_recovery=arguments.recover,
        )

    assert arguments.study_close_event_id is not None
    assert arguments.study_close_revision is not None
    return run_diagnose_stage(
        writer,
        design=design,
        study_close_event_id=arguments.study_close_event_id,
        study_close_revision=arguments.study_close_revision,
        explicit_recovery=arguments.recover,
    )


__all__ = [
    "DesignBuilder",
    "ImplementationMaterializer",
    "JobRunner",
    "parse_fixed_hold_replay_arguments",
    "run_fixed_hold_replay_command",
]
