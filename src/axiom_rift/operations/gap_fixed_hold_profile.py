"""Writer-owned profile for prospective gap fixed-hold work."""

from __future__ import annotations

from axiom_rift.operations.bound_fixed_hold_profile import (
    BoundFixedHoldExposureContext,
    project_bound_fixed_hold_exposure_context,
    require_bound_fixed_hold_family_authority,
    require_bound_fixed_hold_family_authorities,
    require_bound_fixed_hold_registration_prefix,
)
from axiom_rift.operations.fixed_hold_replay_workflow import (
    FixedHoldReplayDesign,
    FixedHoldReplayMember,
    FixedHoldReplayMissionSpec,
    build_fixed_hold_replay_design,
)
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_REPLAY_CRITERIA,
)
from axiom_rift.research.gap_fixed_hold import (
    gap_fixed_hold_configurations,
    gap_fixed_hold_controlled_chassis,
    gap_fixed_hold_executable,
)
from axiom_rift.research.gap_fixed_hold_job import (
    build_gap_fixed_hold_job_plan,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyAuthority,
    HistoricalFamilySpec,
)
from axiom_rift.research.semantic_question import (
    SemanticQuestionLineageProposal,
)


GAP_EVENT_FIXED_HOLD_CAUSAL_QUESTION = (
    "Does an exact prospective reconstruction of the four-member STU-0046 "
    "gap-event family preserve causal, after-cost evidence under registered "
    "controls and concurrent-family inference?"
)
GAP_PATH_FIXED_HOLD_CAUSAL_QUESTION = (
    "Does an exact prospective reconstruction of the four-member STU-0047 "
    "post-gap-path family preserve causal, after-cost evidence under "
    "registered controls and concurrent-family inference?"
)


GapFixedHoldExposureContext = BoundFixedHoldExposureContext


def _gap_research_intent(
    historical_family: HistoricalFamilySpec,
) -> tuple[str, str, str]:
    if historical_family.original_study_id == "STU-0046":
        return (
            GAP_EVENT_FIXED_HOLD_CAUSAL_QUESTION,
            "prospective-stu0046-gap-event-family-replay",
            (
                "the P1 audit queue requires prospective point-in-time proof "
                "for every member of the unresolved STU-0046 family"
            ),
        )
    if historical_family.original_study_id == "STU-0047":
        return (
            GAP_PATH_FIXED_HOLD_CAUSAL_QUESTION,
            "prospective-stu0047-post-gap-path-family-replay",
            (
                "the P1 audit queue requires prospective point-in-time proof "
                "for every member of the unresolved STU-0047 family"
            ),
        )
    raise RuntimeError("gap fixed-hold Study intent is unregistered")


def require_gap_fixed_hold_family_authority(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family_authority_id: str,
) -> HistoricalFamilyAuthority:
    return require_bound_fixed_hold_family_authority(
        writer,
        spec=spec,
        historical_family_authority_id=historical_family_authority_id,
    )


def project_gap_fixed_hold_exposure_context(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family: HistoricalFamilySpec,
) -> GapFixedHoldExposureContext:
    return project_bound_fixed_hold_exposure_context(
        writer,
        spec=spec,
        historical_family=historical_family,
    )


def gap_fixed_hold_members(
    spec: FixedHoldReplayMissionSpec,
    *,
    exposure_context: GapFixedHoldExposureContext,
    historical_family: HistoricalFamilySpec,
    historical_family_authority_id: str,
) -> tuple[FixedHoldReplayMember, ...]:
    values: list[FixedHoldReplayMember] = []
    for configuration in gap_fixed_hold_configurations(historical_family):
        executable = gap_fixed_hold_executable(
            configuration,
            historical_family=historical_family,
            historical_context_prior_global_exposure_count=(
                exposure_context.prior_global_exposure_count
            ),
            original_family_end_global_exposure_count=(
                exposure_context.original_family_end_global_exposure_count
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
                job_plan=build_gap_fixed_hold_job_plan(
                    mission_id=spec.mission_id,
                    study_id=spec.study_id,
                    executable_id=executable.identity,
                    historical_context_prior_global_exposure_count=(
                        exposure_context.prior_global_exposure_count
                    ),
                    original_family_end_global_exposure_count=(
                        exposure_context.original_family_end_global_exposure_count
                    ),
                    historical_family=historical_family,
                    historical_family_authority_id=(
                        historical_family_authority_id
                    ),
                    replay_obligation_id=spec.target_obligation_id,
                ),
            )
        )
    members = tuple(values)
    if (
        len(members) != historical_family.family_size
        or tuple(
            member.historical_reference_executable_id for member in members
        )
        != tuple(
            member.historical_reference_executable_id
            for member in historical_family.members
        )
    ):
        raise RuntimeError("gap fixed-hold family membership drifted")
    return members


def require_gap_fixed_hold_registration_prefix(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    members: tuple[FixedHoldReplayMember, ...],
    exposure_context: GapFixedHoldExposureContext,
) -> None:
    require_bound_fixed_hold_registration_prefix(
        writer,
        spec=spec,
        members=members,
        exposure_context=exposure_context,
    )


def build_gap_fixed_hold_profile_design(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family_authority_id: str,
    additional_historical_family_authority_ids: tuple[str, ...] = (),
    semantic_question_lineage: SemanticQuestionLineageProposal | None = None,
) -> FixedHoldReplayDesign:
    family_authorities = require_bound_fixed_hold_family_authorities(
        writer,
        spec=spec,
        historical_family_authority_id=historical_family_authority_id,
        additional_historical_family_authority_ids=(
            additional_historical_family_authority_ids
        ),
    )
    family_authority = family_authorities[0]
    causal_question, mechanism_family, why_now = _gap_research_intent(
        family_authority.family
    )
    exposure = project_gap_fixed_hold_exposure_context(
        writer,
        spec=spec,
        historical_family=family_authority.family,
    )
    members = gap_fixed_hold_members(
        spec,
        exposure_context=exposure,
        historical_family=family_authority.family,
        historical_family_authority_id=family_authority.identity,
    )
    require_gap_fixed_hold_registration_prefix(
        writer,
        spec=spec,
        members=members,
        exposure_context=exposure,
    )
    targets = tuple(
        member
        for member in members
        if member.historical_reference_executable_id
        == family_authority.family.target_historical_executable_id
    )
    if len(targets) != 1:
        raise RuntimeError("gap fixed-hold target member is ambiguous")
    criterion_ids = tuple(
        sorted(str(item["criterion_id"]) for item in FIXED_HOLD_REPLAY_CRITERIA)
    )
    return build_fixed_hold_replay_design(
        writer,
        spec=spec,
        members=members,
        target_executable_id=targets[0].executable.identity,
        controlled_chassis=gap_fixed_hold_controlled_chassis(
            historical_family=family_authority.family,
            historical_context_prior_global_exposure_count=(
                exposure.prior_global_exposure_count
            ),
            original_family_end_global_exposure_count=(
                exposure.original_family_end_global_exposure_count
            ),
        ),
        historical_family_manifest=family_authority.family.manifest(),
        historical_family_authority_id=family_authority.identity,
        additional_historical_family_authority_ids=tuple(
            sorted(authority.identity for authority in family_authorities[1:])
        ),
        criterion_ids=criterion_ids,
        causal_question=causal_question,
        mechanism_family=mechanism_family,
        why_now=why_now,
        stop_or_reopen_condition=(
            "stop after all four members; reopen only under a typed replay "
            "resume condition or registered development material"
        ),
        semantic_question_lineage=semantic_question_lineage,
    )


__all__ = [
    "GAP_EVENT_FIXED_HOLD_CAUSAL_QUESTION",
    "GAP_PATH_FIXED_HOLD_CAUSAL_QUESTION",
    "GapFixedHoldExposureContext",
    "build_gap_fixed_hold_profile_design",
    "gap_fixed_hold_members",
    "project_gap_fixed_hold_exposure_context",
    "require_gap_fixed_hold_family_authority",
    "require_gap_fixed_hold_registration_prefix",
]
