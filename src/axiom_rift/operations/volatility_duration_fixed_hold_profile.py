"""Writer-owned profile for prospective volatility-duration fixed-hold work."""

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
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyAuthority,
    HistoricalFamilySpec,
)
from axiom_rift.research.semantic_question import (
    SemanticQuestionLineageProposal,
)
from axiom_rift.research.volatility_duration_fixed_hold import (
    volatility_duration_fixed_hold_configurations,
    volatility_duration_fixed_hold_controlled_chassis,
    volatility_duration_fixed_hold_executable,
)
from axiom_rift.research.volatility_duration_fixed_hold_job import (
    build_volatility_duration_fixed_hold_job_plan,
)


VOLATILITY_DURATION_FIXED_HOLD_CAUSAL_QUESTION = (
    "Does an exact prospective reconstruction of the four-member STU-0051 "
    "volatility state-age family preserve causal, after-cost evidence under "
    "exact controls and concurrent-family inference?"
)


VolatilityDurationFixedHoldExposureContext = BoundFixedHoldExposureContext


def require_volatility_duration_fixed_hold_family_authority(
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


def project_volatility_duration_fixed_hold_exposure_context(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family: HistoricalFamilySpec,
) -> VolatilityDurationFixedHoldExposureContext:
    """Derive both prospective and original exposure counts from authority."""
    return project_bound_fixed_hold_exposure_context(
        writer,
        spec=spec,
        historical_family=historical_family,
    )


def volatility_duration_fixed_hold_members(
    spec: FixedHoldReplayMissionSpec,
    *,
    exposure_context: VolatilityDurationFixedHoldExposureContext,
    historical_family: HistoricalFamilySpec,
    historical_family_authority_id: str,
) -> tuple[FixedHoldReplayMember, ...]:
    values: list[FixedHoldReplayMember] = []
    for configuration in volatility_duration_fixed_hold_configurations(
        historical_family
    ):
        executable = volatility_duration_fixed_hold_executable(
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
                job_plan=build_volatility_duration_fixed_hold_job_plan(
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
        raise RuntimeError("volatility-duration family membership drifted")
    return members


def require_volatility_duration_fixed_hold_registration_prefix(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    members: tuple[FixedHoldReplayMember, ...],
    exposure_context: VolatilityDurationFixedHoldExposureContext,
) -> None:
    require_bound_fixed_hold_registration_prefix(
        writer,
        spec=spec,
        members=members,
        exposure_context=exposure_context,
    )


def build_volatility_duration_fixed_hold_profile_design(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family_authority_id: str,
    semantic_question_lineage: SemanticQuestionLineageProposal,
    additional_historical_family_authority_ids: tuple[str, ...] = (),
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
    exposure = project_volatility_duration_fixed_hold_exposure_context(
        writer,
        spec=spec,
        historical_family=family_authority.family,
    )
    members = volatility_duration_fixed_hold_members(
        spec,
        exposure_context=exposure,
        historical_family=family_authority.family,
        historical_family_authority_id=family_authority.identity,
    )
    require_volatility_duration_fixed_hold_registration_prefix(
        writer,
        spec=spec,
        members=members,
        exposure_context=exposure,
    )
    target_historical_id = (
        family_authority.family.target_historical_executable_id
    )
    targets = tuple(
        member
        for member in members
        if member.historical_reference_executable_id == target_historical_id
    )
    if len(targets) != 1:
        raise RuntimeError("volatility-duration target member is ambiguous")
    criterion_ids = tuple(
        sorted(str(item["criterion_id"]) for item in FIXED_HOLD_REPLAY_CRITERIA)
    )
    return build_fixed_hold_replay_design(
        writer,
        spec=spec,
        members=members,
        target_executable_id=targets[0].executable.identity,
        controlled_chassis=volatility_duration_fixed_hold_controlled_chassis(
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
            sorted(
                authority.identity
                for authority in family_authorities[1:]
            )
        ),
        criterion_ids=criterion_ids,
        causal_question=VOLATILITY_DURATION_FIXED_HOLD_CAUSAL_QUESTION,
        mechanism_family=(
            "prospective-stu0051-volatility-duration-family-replay"
        ),
        why_now=(
            "the P0 correction queue requires a completed-bar replay of the "
            "locally executable family after its prior satisfaction was invalidated"
        ),
        stop_or_reopen_condition=(
            "stop after all four members; reopen only under a typed replay "
            "resume condition or registered development material"
        ),
        semantic_question_lineage=semantic_question_lineage,
    )


__all__ = [
    "VOLATILITY_DURATION_FIXED_HOLD_CAUSAL_QUESTION",
    "VolatilityDurationFixedHoldExposureContext",
    "build_volatility_duration_fixed_hold_profile_design",
    "project_volatility_duration_fixed_hold_exposure_context",
    "require_volatility_duration_fixed_hold_family_authority",
    "require_volatility_duration_fixed_hold_registration_prefix",
    "volatility_duration_fixed_hold_members",
]
