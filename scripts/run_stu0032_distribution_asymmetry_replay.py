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
    build_fixed_hold_replay_design,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.distribution_asymmetry_replay import (  # noqa: E402
    DISTRIBUTION_ASYMMETRY_REPLAY_HISTORICAL_CONTEXT_ID,
    distribution_asymmetry_replay_configurations,
    distribution_asymmetry_replay_controlled_chassis,
    distribution_asymmetry_replay_executable,
)
from axiom_rift.research.distribution_asymmetry_replay_job import (  # noqa: E402
    CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL,
    build_distribution_asymmetry_replay_job_plan,
    distribution_asymmetry_replay_job_implementation_sha256,
    execute_distribution_asymmetry_replay_job,
    materialize_distribution_asymmetry_replay_job_implementation,
)
from axiom_rift.research.fixed_hold_family_trace import (  # noqa: E402
    FIXED_HOLD_REPLAY_CRITERIA,
)
from axiom_rift.research.historical_family_replay import (  # noqa: E402
    STU0032_HISTORICAL_FAMILY,
)
from axiom_rift.research.replay_exposure import (  # noqa: E402
    derive_frozen_family_exposure_context,
)
from axiom_rift.research.trials import TrialAccountant  # noqa: E402
from axiom_rift.storage.index import LocalIndex  # noqa: E402


MISSION_ID = "MIS-0006"
INITIATIVE_ID = "INI-0021"
STUDY_ID = "STU-0109"
BATCH_DISPLAY_ID = "BAT-0109"
HISTORICAL_CONTEXT_COUNT = 586
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"
PREDECESSOR_REVISION = 5063
PREDECESSOR_EVENT_ID = (
    "33266c3e29b36765d61109d4f6f262b62e96a6372c58b0788e7afd8ed606a370"
)


def mission_spec() -> FixedHoldReplayMissionSpec:
    return FixedHoldReplayMissionSpec(
        mission_id=MISSION_ID,
        initiative_id=INITIATIVE_ID,
        study_id=STUDY_ID,
        batch_display_id=BATCH_DISPLAY_ID,
        axis_id="axis-stu0032-distribution-asymmetry-replay-bridge",
        bridge_axis_id="axis-stu0051-volatility-duration-replay-bridge",
        operation_prefix="p1-stu0032-distribution-asymmetry-replay-v1-",
        decision_prefix="DEC-P1-STU0032",
        target_obligation_id=(
            DISTRIBUTION_ASYMMETRY_REPLAY_HISTORICAL_CONTEXT_ID
        ),
        original_study_id="STU-0032",
        job_protocol=JOB_IMPLEMENTATION_PROTOCOL,
        callable_identity=CALLABLE_IDENTITY,
        job_implementation_identity=(
            distribution_asymmetry_replay_job_implementation_sha256()
        ),
        permit_expiry_utc=PERMIT_EXPIRY_UTC,
        boundary=ReplayAuthorityBoundary(
            sequence=PREDECESSOR_REVISION,
            event_id=PREDECESSOR_EVENT_ID,
        ),
        display_name="STU-0032 exact distribution-asymmetry replay family",
    )


def ordered_members() -> tuple[FixedHoldReplayMember, ...]:
    values: list[FixedHoldReplayMember] = []
    for configuration in distribution_asymmetry_replay_configurations():
        executable = distribution_asymmetry_replay_executable(
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
                job_plan=build_distribution_asymmetry_replay_job_plan(
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
        len(members) != 12
        or tuple(
            member.historical_reference_executable_id for member in members
        )
        != tuple(
            member.historical_reference_executable_id
            for member in STU0032_HISTORICAL_FAMILY.members
        )
    ):
        raise RuntimeError("STU-0032 exact replay family drifted")
    return members


def require_historical_context(
    writer: StateWriter,
    members: tuple[FixedHoldReplayMember, ...],
) -> None:
    prospective = {member.executable.identity for member in members}
    with LocalIndex(writer.index_path) as index:
        trials = tuple(index.records_by_kind("trial"))
    floor = TrialAccountant.from_foundation(
        writer.foundation_root
    ).prior_global_multiplicity_floor
    context = derive_frozen_family_exposure_context(
        trials=trials,
        prior_global_exposure_floor=floor,
        study_id=STUDY_ID,
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
        raise RuntimeError("STU-0032 historical exposure context drifted")


def build_design(writer: StateWriter):
    members = ordered_members()
    require_historical_context(writer, members)
    target_historical_id = (
        STU0032_HISTORICAL_FAMILY.target_historical_executable_id
    )
    targets = tuple(
        member
        for member in members
        if member.historical_reference_executable_id == target_historical_id
    )
    if len(targets) != 1:
        raise RuntimeError("STU-0032 target member is ambiguous")
    criterion_ids = tuple(
        sorted(str(item["criterion_id"]) for item in FIXED_HOLD_REPLAY_CRITERIA)
    )
    return build_fixed_hold_replay_design(
        writer,
        spec=mission_spec(),
        members=members,
        target_executable_id=targets[0].executable.identity,
        controlled_chassis=distribution_asymmetry_replay_controlled_chassis(
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            )
        ),
        historical_family_manifest=STU0032_HISTORICAL_FAMILY.manifest(),
        criterion_ids=criterion_ids,
        causal_question=(
            "Does an exact prospective reconstruction of the twelve-member "
            "STU-0032 distribution-asymmetry family preserve causal, "
            "after-cost evidence under exact controls and concurrent-family "
            "inference?"
        ),
        mechanism_family=(
            "prospective-stu0032-distribution-asymmetry-family-replay"
        ),
        why_now=(
            "the P1 audit queue identifies STU-0032 as a locally executable "
            "family whose global-history multiplicity and conjunctive verdict "
            "may have hidden claim-level partial evidence"
        ),
        stop_or_reopen_condition=(
            "stop after all twelve members; reopen only under a typed replay "
            "resume condition or registered development material"
        ),
    )


def main(argv: Sequence[str] | None = None) -> None:
    summary = run_fixed_hold_replay_command(
        repository_root=ROOT,
        design_builder=build_design,
        job_runner=execute_distribution_asymmetry_replay_job,
        job_implementation_materializer=(
            materialize_distribution_asymmetry_replay_job_implementation
        ),
        argv=argv,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
