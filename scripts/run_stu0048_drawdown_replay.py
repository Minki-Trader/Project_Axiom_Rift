from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.fixed_hold_replay_workflow import (  # noqa: E402
    FixedHoldReplayMember,
    FixedHoldReplayMissionSpec,
    ReplayAuthorityBoundary,
    ReplayInitiativeLifecycle,
    build_fixed_hold_replay_design,
    read_only_summary,
    require_stable_head,
    run_diagnose_stage,
    run_study_close_stage,
)
from axiom_rift.operations.permits import (  # noqa: E402
    PermitAuthority,
    PermitKeyStore,
)
from axiom_rift.operations.scientific_history import (  # noqa: E402
    project_frozen_family_exposure_context,
)
from axiom_rift.operations.validation import (  # noqa: E402
    EvidenceValidatorRegistry,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.drawdown_state_replay import (  # noqa: E402
    DRAWDOWN_REPLAY_HISTORICAL_CONTEXT_ID,
    drawdown_replay_configurations,
    drawdown_replay_controlled_chassis,
    drawdown_replay_executable,
)
from axiom_rift.research.drawdown_state_replay_job import (  # noqa: E402
    CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL,
    build_drawdown_replay_job_plan,
    drawdown_replay_job_implementation_sha256,
    execute_drawdown_state_replay_job,
    materialize_drawdown_replay_job_implementation,
)
from axiom_rift.research.fixed_hold_family_trace import (  # noqa: E402
    FIXED_HOLD_REPLAY_CRITERIA,
)
from axiom_rift.research.historical_family_replay import (  # noqa: E402
    STU0048_HISTORICAL_FAMILY,
)
from axiom_rift.research.trials import TrialAccountant  # noqa: E402
from axiom_rift.research.validation_v2 import (  # noqa: E402
    ScientificAdjudicationValidatorV2,
)


MISSION_ID = "MIS-0006"
INITIATIVE_ID = "INI-0019"
STUDY_ID = "STU-0107"
BATCH_DISPLAY_ID = "BAT-0107"
HISTORICAL_CONTEXT_COUNT = 578
JOB_PROTOCOL = JOB_IMPLEMENTATION_PROTOCOL
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"
PREDECESSOR_REVISION = 4977
PREDECESSOR_EVENT_ID = (
    "94634825aa9c51533329b86766346d34cb94f1e6b8075feaf86c357a1f50a70d"
)


def mission_spec() -> FixedHoldReplayMissionSpec:
    return FixedHoldReplayMissionSpec(
        initiative_lifecycle=(
            ReplayInitiativeLifecycle.OWN_BOUNDED_INITIATIVE
        ),
        mission_id=MISSION_ID,
        initiative_id=INITIATIVE_ID,
        study_id=STUDY_ID,
        batch_display_id=BATCH_DISPLAY_ID,
        axis_id="axis-stu0048-drawdown-state-replay-bridge",
        bridge_axis_id="axis-cost-aware-execution",
        operation_prefix="p1-stu0048-drawdown-replay-v2-",
        decision_prefix="DEC-P1-STU0048",
        target_obligation_id=DRAWDOWN_REPLAY_HISTORICAL_CONTEXT_ID,
        original_study_id="STU-0048",
        job_protocol=JOB_PROTOCOL,
        callable_identity=CALLABLE_IDENTITY,
        job_implementation_identity=(
            drawdown_replay_job_implementation_sha256()
        ),
        permit_expiry_utc=PERMIT_EXPIRY_UTC,
        boundary=ReplayAuthorityBoundary(
            sequence=PREDECESSOR_REVISION,
            event_id=PREDECESSOR_EVENT_ID,
        ),
        display_name="STU-0048 exact drawdown-state replay family",
    )


def ordered_members() -> tuple[FixedHoldReplayMember, ...]:
    values: list[FixedHoldReplayMember] = []
    for configuration in drawdown_replay_configurations():
        executable = drawdown_replay_executable(
            configuration,
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            ),
        )
        values.append(
            FixedHoldReplayMember(
                ordinal=configuration.ordinal,
                configuration_id=configuration.configuration_id,
                historical_reference_executable_id=(
                    configuration.historical_reference_executable_id
                ),
                executable=executable,
                job_plan=build_drawdown_replay_job_plan(
                    mission_id=MISSION_ID,
                    study_id=STUDY_ID,
                    executable_id=executable.identity,
                    historical_context_prior_global_exposure_count=(
                        HISTORICAL_CONTEXT_COUNT
                    ),
                ),
            )
        )
    members = tuple(values)
    if (
        len(members) != 4
        or tuple(
            member.historical_reference_executable_id for member in members
        )
        != tuple(
            member.historical_reference_executable_id
            for member in STU0048_HISTORICAL_FAMILY.members
        )
    ):
        raise RuntimeError("STU-0048 exact replay family drifted")
    return members


def require_historical_context(
    writer: StateWriter,
    members: tuple[FixedHoldReplayMember, ...],
) -> None:
    prospective = {member.executable.identity for member in members}
    floor = TrialAccountant.from_foundation(
        writer.foundation_root
    ).prior_global_multiplicity_floor
    with writer.open_stable_index() as (_control, index):
        context = project_frozen_family_exposure_context(
            index,
            prior_global_exposure_floor=floor,
            study_id=STUDY_ID,
            batch_id=None,
            expected_family_size=len(members),
            parameter_name="historical_context_prior_global_exposure_count",
            allow_unregistered=True,
        )
    if (
        context.prior_global_exposure_count != HISTORICAL_CONTEXT_COUNT
        or (
            context.family_executable_ids
            and set(context.family_executable_ids) != prospective
        )
    ):
        raise RuntimeError("STU-0048 historical exposure context drifted")


def build_design(writer: StateWriter):
    members = ordered_members()
    require_historical_context(writer, members)
    target_historical_id = STU0048_HISTORICAL_FAMILY.target_historical_executable_id
    targets = tuple(
        member
        for member in members
        if member.historical_reference_executable_id == target_historical_id
    )
    if len(targets) != 1:
        raise RuntimeError("STU-0048 target member is ambiguous")
    criterion_ids = tuple(
        sorted(str(item["criterion_id"]) for item in FIXED_HOLD_REPLAY_CRITERIA)
    )
    return build_fixed_hold_replay_design(
        writer,
        spec=mission_spec(),
        members=members,
        target_executable_id=targets[0].executable.identity,
        controlled_chassis=drawdown_replay_controlled_chassis(
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            )
        ),
        historical_family_manifest=STU0048_HISTORICAL_FAMILY.manifest(),
        criterion_ids=criterion_ids,
        causal_question=(
            "Does an exact prospective reconstruction of the four-member "
            "STU-0048 drawdown depth-duration family preserve a causal, "
            "after-cost signal after registered controls and familywise inference?"
        ),
        mechanism_family="prospective-stu0048-drawdown-state-family-replay",
        why_now=(
            "the P1 audit queue identifies STU-0048 as an exact locally executable "
            "family whose legacy verdict collapsed partial scientific evidence"
        ),
        stop_or_reopen_condition=(
            "stop after all four members; reopen only under a typed replay resume "
            "condition or registered development material"
        ),
    )


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or crash-resumably execute the exact STU-0048 replay "
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


def main(argv: Sequence[str] | None = None) -> None:
    arguments = parse_arguments(argv)
    if arguments.stage is None and arguments.recover:
        raise RuntimeError("read-only plan does not perform recovery")
    registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
    writer = StateWriter(ROOT, validation_registry=registry)
    require_stable_head(
        writer,
        explicit_recovery=bool(arguments.stage and arguments.recover),
    )
    design = build_design(writer)
    if arguments.stage is None:
        if (
            arguments.study_close_event_id is not None
            or arguments.study_close_revision is not None
        ):
            raise RuntimeError(
                "Study-close authority arguments require diagnose stage"
            )
        print(json.dumps(read_only_summary(writer, design), sort_keys=True))
        return
    writer.permit_authority = PermitAuthority(
        PermitKeyStore(ROOT / "local" / "permit.key").load_or_create()
    )
    if arguments.stage == "study-close":
        if (
            arguments.study_close_event_id is not None
            or arguments.study_close_revision is not None
        ):
            raise RuntimeError("Study-close stage rejects checkpoint arguments")
        summary = run_study_close_stage(
            writer,
            design=design,
            repository_root=ROOT,
            job_runner=execute_drawdown_state_replay_job,
            job_implementation_materializer=(
                materialize_drawdown_replay_job_implementation
            ),
            explicit_recovery=arguments.recover,
        )
        print(json.dumps(summary, sort_keys=True))
        return
    if (
        arguments.study_close_event_id is None
        or arguments.study_close_revision is None
    ):
        raise RuntimeError(
            "diagnose stage requires exact Study-close event and revision"
        )
    summary = run_diagnose_stage(
        writer,
        design=design,
        study_close_event_id=arguments.study_close_event_id,
        study_close_revision=arguments.study_close_revision,
        explicit_recovery=arguments.recover,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
