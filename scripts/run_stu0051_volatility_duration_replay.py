from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.fixed_hold_replay_cli import (  # noqa: E402
    run_fixed_hold_replay_command,
)
from axiom_rift.operations.fixed_hold_replay_workflow import (  # noqa: E402
    FixedHoldReplayMember,
    FixedHoldReplayMissionSpec,
    ReplayAuthorityBoundary,
    ReplayInitiativeLifecycle,
    build_fixed_hold_replay_design,
)
from axiom_rift.operations.scientific_history import (  # noqa: E402
    project_frozen_family_exposure_context,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.fixed_hold_family_trace import (  # noqa: E402
    FIXED_HOLD_REPLAY_CRITERIA,
)
from axiom_rift.research.historical_family_replay import (  # noqa: E402
    STU0051_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_binding import (  # noqa: E402
    historical_family_from_manifest,
)
from axiom_rift.research.trials import TrialAccountant  # noqa: E402
from axiom_rift.research.volatility_duration_replay import (  # noqa: E402
    VOLATILITY_DURATION_REPLAY_HISTORICAL_CONTEXT_ID,
    volatility_duration_replay_configurations,
    volatility_duration_replay_controlled_chassis,
    volatility_duration_replay_executable,
)
from axiom_rift.research.volatility_duration_replay_job import (  # noqa: E402
    CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL,
    build_volatility_duration_replay_job_plan,
    execute_volatility_duration_replay_job,
    materialize_volatility_duration_replay_job_implementation,
    volatility_duration_replay_job_implementation_sha256,
)


MISSION_ID = "MIS-0006"
INITIATIVE_ID = "INI-0020"
STUDY_ID = "STU-0108"
BATCH_DISPLAY_ID = "BAT-0108"
HISTORICAL_CONTEXT_COUNT = 582
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"
PREDECESSOR_REVISION = 5020
PREDECESSOR_EVENT_ID = (
    "61da2fdb1930956b0acc9886042af09ca98eb70301e5394cfdaa922b58964fc2"
)
HISTORICAL_FAMILY_AUTHORITY_ID = (
    "historical-family-authority:"
    "a1996ed0e967f188c6a68fa8ef512996d7754d998f829961e6872107b145bea3"
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
        axis_id="axis-stu0051-volatility-duration-replay-bridge",
        bridge_axis_id="axis-stu0048-drawdown-state-replay-bridge",
        operation_prefix="p1-stu0051-volatility-duration-replay-v1-",
        decision_prefix="DEC-P1-STU0051",
        target_obligation_id=VOLATILITY_DURATION_REPLAY_HISTORICAL_CONTEXT_ID,
        original_study_id="STU-0051",
        job_protocol=JOB_IMPLEMENTATION_PROTOCOL,
        callable_identity=CALLABLE_IDENTITY,
        job_implementation_identity=(
            volatility_duration_replay_job_implementation_sha256()
        ),
        permit_expiry_utc=PERMIT_EXPIRY_UTC,
        boundary=ReplayAuthorityBoundary(
            sequence=PREDECESSOR_REVISION,
            event_id=PREDECESSOR_EVENT_ID,
        ),
        display_name="STU-0051 exact volatility-duration replay family",
    )


def ordered_members() -> tuple[FixedHoldReplayMember, ...]:
    historical_family = historical_family_from_manifest(
        STU0051_HISTORICAL_FAMILY.manifest()
    )
    values: list[FixedHoldReplayMember] = []
    for configuration in volatility_duration_replay_configurations():
        executable = volatility_duration_replay_executable(
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
                job_plan=build_volatility_duration_replay_job_plan(
                    mission_id=MISSION_ID,
                    study_id=STUDY_ID,
                    executable_id=executable.identity,
                    historical_context_prior_global_exposure_count=(
                        HISTORICAL_CONTEXT_COUNT
                    ),
                    historical_family=historical_family,
                    historical_family_authority_id=(
                        HISTORICAL_FAMILY_AUTHORITY_ID
                    ),
                    replay_obligation_id=(
                        VOLATILITY_DURATION_REPLAY_HISTORICAL_CONTEXT_ID
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
            for member in STU0051_HISTORICAL_FAMILY.members
        )
    ):
        raise RuntimeError("STU-0051 exact replay family drifted")
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
        raise RuntimeError("STU-0051 historical exposure context drifted")


def build_design(writer: StateWriter):
    members = ordered_members()
    require_historical_context(writer, members)
    target_historical_id = (
        STU0051_HISTORICAL_FAMILY.target_historical_executable_id
    )
    targets = tuple(
        member
        for member in members
        if member.historical_reference_executable_id == target_historical_id
    )
    if len(targets) != 1:
        raise RuntimeError("STU-0051 target member is ambiguous")
    criterion_ids = tuple(
        sorted(str(item["criterion_id"]) for item in FIXED_HOLD_REPLAY_CRITERIA)
    )
    return build_fixed_hold_replay_design(
        writer,
        spec=mission_spec(),
        members=members,
        target_executable_id=targets[0].executable.identity,
        controlled_chassis=volatility_duration_replay_controlled_chassis(
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            )
        ),
        historical_family_manifest=STU0051_HISTORICAL_FAMILY.manifest(),
        historical_family_authority_id=HISTORICAL_FAMILY_AUTHORITY_ID,
        criterion_ids=criterion_ids,
        causal_question=(
            "Does an exact prospective reconstruction of the four-member "
            "STU-0051 volatility state-age family preserve causal, after-cost "
            "evidence under exact controls and concurrent-family inference?"
        ),
        mechanism_family=(
            "prospective-stu0051-volatility-duration-family-replay"
        ),
        why_now=(
            "the P1 audit queue identifies STU-0051 as a locally executable "
            "family whose legacy verdict collapsed claim-level partial evidence"
        ),
        stop_or_reopen_condition=(
            "stop after all four members; reopen only under a typed replay "
            "resume condition or registered development material"
        ),
    )


def main(argv: Sequence[str] | None = None) -> None:
    summary = run_fixed_hold_replay_command(
        repository_root=ROOT,
        design_builder=build_design,
        job_runner=execute_volatility_duration_replay_job,
        job_implementation_materializer=(
            materialize_volatility_duration_replay_job_implementation
        ),
        argv=argv,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
