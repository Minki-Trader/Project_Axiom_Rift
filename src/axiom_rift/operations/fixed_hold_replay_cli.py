"""Small command boundary for the reusable fixed-hold replay workflow."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
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
from axiom_rift.operations.validation import EvidenceValidatorRegistry
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.fixed_hold_family_job import FixedHoldFamilyJobPacket
from axiom_rift.research.validation_v2 import ScientificAdjudicationValidatorV2


DesignBuilder = Callable[[StateWriter], FixedHoldReplayDesign]
JobRunner = Callable[..., FixedHoldFamilyJobPacket]
ImplementationMaterializer = Callable[[StateWriter], str]


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
    argv: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Run one explicit stage; omission of ``--stage`` is read-only."""

    arguments = parse_fixed_hold_replay_arguments(argv)
    if arguments.stage is None and arguments.recover:
        raise RuntimeError("read-only plan does not perform recovery")
    root = Path(repository_root).resolve()
    registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
    writer = StateWriter(root, validation_registry=registry)
    require_stable_head(
        writer,
        explicit_recovery=bool(arguments.stage and arguments.recover),
    )
    design = design_builder(writer)
    if arguments.stage is None:
        if (
            arguments.study_close_event_id is not None
            or arguments.study_close_revision is not None
        ):
            raise RuntimeError(
                "Study-close authority arguments require diagnose stage"
            )
        return dict(read_only_summary(writer, design))

    writer.permit_authority = PermitAuthority(
        PermitKeyStore(root / "local" / "permit.key").load_or_create()
    )
    if arguments.stage == "study-close":
        if (
            arguments.study_close_event_id is not None
            or arguments.study_close_revision is not None
        ):
            raise RuntimeError("Study-close stage rejects checkpoint arguments")
        return run_study_close_stage(
            writer,
            design=design,
            repository_root=root,
            job_runner=job_runner,
            job_implementation_materializer=job_implementation_materializer,
            explicit_recovery=arguments.recover,
        )

    if (
        arguments.study_close_event_id is None
        or arguments.study_close_revision is None
    ):
        raise RuntimeError(
            "diagnose stage requires exact Study-close event and revision"
        )
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
