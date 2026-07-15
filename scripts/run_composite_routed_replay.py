from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any


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
from axiom_rift.operations.scientific_history import (  # noqa: E402
    project_frozen_family_exposure_context,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.composite_consensus_replay import (  # noqa: E402
    COMPOSITE_CONSENSUS_REPLAY_HISTORICAL_CONTEXT_ID,
    composite_consensus_replay_configurations,
    composite_consensus_replay_controlled_chassis,
    composite_consensus_replay_executable,
)
from axiom_rift.research.composite_consensus_replay_job import (  # noqa: E402
    CALLABLE_IDENTITY as CONSENSUS_CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL as CONSENSUS_JOB_PROTOCOL,
    build_composite_consensus_replay_job_plan,
    composite_consensus_replay_job_implementation_sha256,
    execute_composite_consensus_replay_job,
    materialize_composite_consensus_replay_job_implementation,
)
from axiom_rift.research.composite_router_replay import (  # noqa: E402
    COMPOSITE_ROUTER_REPLAY_HISTORICAL_CONTEXT_ID,
    composite_router_replay_configurations,
    composite_router_replay_controlled_chassis,
    composite_router_replay_executable,
)
from axiom_rift.research.composite_router_replay_job import (  # noqa: E402
    CALLABLE_IDENTITY as ROUTER_CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL as ROUTER_JOB_PROTOCOL,
    build_composite_router_replay_job_plan,
    composite_router_replay_job_implementation_sha256,
    execute_composite_router_replay_job,
    materialize_composite_router_replay_job_implementation,
)
from axiom_rift.research.fixed_hold_family_trace import (  # noqa: E402
    FIXED_HOLD_REPLAY_CRITERIA,
)
from axiom_rift.research.historical_family_replay import (  # noqa: E402
    STU0016_HISTORICAL_FAMILY,
    STU0017_HISTORICAL_FAMILY,
    HistoricalFamilySpec,
)
from axiom_rift.research.trials import TrialAccountant  # noqa: E402


MISSION_ID = "MIS-0006"
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"
BRIDGE_AXIS_ID = "axis-stu0032-distribution-asymmetry-replay-bridge"


@dataclass(frozen=True, slots=True)
class FamilyRoute:
    name: str
    obligation_id: str
    original_study_id: str
    historical_family: HistoricalFamilySpec
    axis_id: str
    operation_prefix: str
    decision_prefix: str
    display_name: str
    mechanism_family: str
    causal_question: str
    why_now: str
    configurations: Callable[[], tuple[object, ...]]
    executable_builder: Callable[..., Any]
    chassis_builder: Callable[..., Any]
    job_plan_builder: Callable[..., Any]
    job_protocol: str
    callable_identity: str
    implementation_identity_builder: Callable[[], str]
    job_runner: Callable[..., Any]
    implementation_materializer: Callable[[StateWriter], str]


FAMILY_ROUTES = {
    "consensus": FamilyRoute(
        name="consensus",
        obligation_id=COMPOSITE_CONSENSUS_REPLAY_HISTORICAL_CONTEXT_ID,
        original_study_id="STU-0017",
        historical_family=STU0017_HISTORICAL_FAMILY,
        axis_id="axis-stu0017-composite-consensus-replay-bridge",
        operation_prefix="p1-stu0017-composite-consensus-replay-v1-",
        decision_prefix="DEC-P1-STU0017",
        display_name="STU-0017 exact composite-consensus replay family",
        mechanism_family=(
            "prospective-stu0017-composite-consensus-family-replay"
        ),
        causal_question=(
            "Does an exact prospective reconstruction of the twelve-member "
            "STU-0017 composite-consensus family preserve causal, after-cost "
            "evidence under exact controls and concurrent-family inference?"
        ),
        why_now=(
            "the P1 audit queue identifies STU-0017 as an executable routed "
            "family whose global-history multiplicity and conjunctive verdict "
            "may have hidden claim-level partial evidence"
        ),
        configurations=composite_consensus_replay_configurations,
        executable_builder=composite_consensus_replay_executable,
        chassis_builder=composite_consensus_replay_controlled_chassis,
        job_plan_builder=build_composite_consensus_replay_job_plan,
        job_protocol=CONSENSUS_JOB_PROTOCOL,
        callable_identity=CONSENSUS_CALLABLE_IDENTITY,
        implementation_identity_builder=(
            composite_consensus_replay_job_implementation_sha256
        ),
        job_runner=execute_composite_consensus_replay_job,
        implementation_materializer=(
            materialize_composite_consensus_replay_job_implementation
        ),
    ),
    "router": FamilyRoute(
        name="router",
        obligation_id=COMPOSITE_ROUTER_REPLAY_HISTORICAL_CONTEXT_ID,
        original_study_id="STU-0016",
        historical_family=STU0016_HISTORICAL_FAMILY,
        axis_id="axis-stu0016-composite-router-replay-bridge",
        operation_prefix="p1-stu0016-composite-router-replay-v1-",
        decision_prefix="DEC-P1-STU0016",
        display_name="STU-0016 exact composite-router replay family",
        mechanism_family="prospective-stu0016-composite-router-family-replay",
        causal_question=(
            "Does an exact prospective reconstruction of the twelve-member "
            "STU-0016 composite-router family preserve causal, after-cost "
            "evidence under exact controls and concurrent-family inference?"
        ),
        why_now=(
            "the P1 audit queue identifies STU-0016 as an executable routed "
            "family whose global-history multiplicity and conjunctive verdict "
            "may have hidden claim-level partial evidence"
        ),
        configurations=composite_router_replay_configurations,
        executable_builder=composite_router_replay_executable,
        chassis_builder=composite_router_replay_controlled_chassis,
        job_plan_builder=build_composite_router_replay_job_plan,
        job_protocol=ROUTER_JOB_PROTOCOL,
        callable_identity=ROUTER_CALLABLE_IDENTITY,
        implementation_identity_builder=(
            composite_router_replay_job_implementation_sha256
        ),
        job_runner=execute_composite_router_replay_job,
        implementation_materializer=(
            materialize_composite_router_replay_job_implementation
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class RunAuthority:
    family: FamilyRoute
    initiative_id: str
    study_id: str
    batch_display_id: str
    predecessor_revision: int
    predecessor_event_id: str


def parse_arguments(
    argv: Sequence[str] | None,
) -> tuple[RunAuthority, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--family", choices=tuple(FAMILY_ROUTES), required=True)
    parser.add_argument("--initiative-id", required=True)
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--batch-display-id", required=True)
    parser.add_argument("--predecessor-revision", type=int, required=True)
    parser.add_argument("--predecessor-event-id", required=True)
    arguments, remaining = parser.parse_known_args(argv)
    return (
        RunAuthority(
            family=FAMILY_ROUTES[arguments.family],
            initiative_id=arguments.initiative_id,
            study_id=arguments.study_id,
            batch_display_id=arguments.batch_display_id,
            predecessor_revision=arguments.predecessor_revision,
            predecessor_event_id=arguments.predecessor_event_id,
        ),
        remaining,
    )


def historical_context_count(
    writer: StateWriter,
    authority: RunAuthority,
) -> int:
    floor = TrialAccountant.from_foundation(
        writer.foundation_root
    ).prior_global_multiplicity_floor
    with writer.open_stable_index() as (_control, index):
        context = project_frozen_family_exposure_context(
            index,
            prior_global_exposure_floor=floor,
            study_id=authority.study_id,
            batch_id=None,
            expected_family_size=12,
            parameter_name="historical_context_prior_global_exposure_count",
            allow_unregistered=True,
        )
    return context.prior_global_exposure_count


def mission_spec(authority: RunAuthority) -> FixedHoldReplayMissionSpec:
    route = authority.family
    return FixedHoldReplayMissionSpec(
        mission_id=MISSION_ID,
        initiative_id=authority.initiative_id,
        study_id=authority.study_id,
        batch_display_id=authority.batch_display_id,
        axis_id=route.axis_id,
        bridge_axis_id=BRIDGE_AXIS_ID,
        operation_prefix=route.operation_prefix,
        decision_prefix=route.decision_prefix,
        target_obligation_id=route.obligation_id,
        original_study_id=route.original_study_id,
        job_protocol=route.job_protocol,
        callable_identity=route.callable_identity,
        job_implementation_identity=route.implementation_identity_builder(),
        permit_expiry_utc=PERMIT_EXPIRY_UTC,
        boundary=ReplayAuthorityBoundary(
            sequence=authority.predecessor_revision,
            event_id=authority.predecessor_event_id,
        ),
        display_name=route.display_name,
    )


def ordered_members(
    writer: StateWriter,
    authority: RunAuthority,
) -> tuple[FixedHoldReplayMember, ...]:
    route = authority.family
    context = historical_context_count(writer, authority)
    values: list[FixedHoldReplayMember] = []
    for configuration in route.configurations():
        executable = route.executable_builder(
            configuration,
            historical_context_prior_global_exposure_count=context,
        )
        values.append(
            FixedHoldReplayMember(
                ordinal=configuration.ordinal,
                configuration_id=configuration.configuration_id,
                historical_reference_executable_id=(
                    configuration.historical_reference_executable_id
                ),
                executable=executable,
                job_plan=route.job_plan_builder(
                    mission_id=MISSION_ID,
                    study_id=authority.study_id,
                    executable_id=executable.identity,
                    historical_context_prior_global_exposure_count=context,
                ),
            )
        )
    members = tuple(values)
    if (
        tuple(member.ordinal for member in members) != tuple(range(1, 13))
        or tuple(
            member.historical_reference_executable_id for member in members
        )
        != tuple(
            member.historical_reference_executable_id
            for member in route.historical_family.members
        )
    ):
        raise RuntimeError("composite routed exact replay family drifted")
    return members


def build_design(writer: StateWriter, authority: RunAuthority):
    route = authority.family
    context = historical_context_count(writer, authority)
    members = ordered_members(writer, authority)
    targets = tuple(
        member
        for member in members
        if member.historical_reference_executable_id
        == route.historical_family.target_historical_executable_id
    )
    if len(targets) != 1:
        raise RuntimeError("composite routed replay target is ambiguous")
    criterion_ids = tuple(
        sorted(str(item["criterion_id"]) for item in FIXED_HOLD_REPLAY_CRITERIA)
    )
    return build_fixed_hold_replay_design(
        writer,
        spec=mission_spec(authority),
        members=members,
        target_executable_id=targets[0].executable.identity,
        controlled_chassis=route.chassis_builder(
            historical_context_prior_global_exposure_count=context
        ),
        historical_family_manifest=route.historical_family.manifest(),
        criterion_ids=criterion_ids,
        causal_question=route.causal_question,
        mechanism_family=route.mechanism_family,
        why_now=route.why_now,
        stop_or_reopen_condition=(
            "stop after all twelve members; reopen only under a typed replay "
            "resume condition or registered development material"
        ),
    )


def main(argv: Sequence[str] | None = None) -> None:
    authority, remaining = parse_arguments(argv)
    summary = run_fixed_hold_replay_command(
        repository_root=ROOT,
        design_builder=lambda writer: build_design(writer, authority),
        job_runner=authority.family.job_runner,
        job_implementation_materializer=(
            authority.family.implementation_materializer
        ),
        argv=remaining,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
