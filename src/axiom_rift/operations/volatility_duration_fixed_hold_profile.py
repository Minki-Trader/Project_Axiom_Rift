"""Writer-owned profile for prospective volatility-duration fixed-hold work."""

from __future__ import annotations

from dataclasses import dataclass

from axiom_rift.operations.fixed_hold_replay_workflow import (
    FixedHoldReplayDesign,
    FixedHoldReplayMember,
    FixedHoldReplayMissionSpec,
    build_fixed_hold_replay_design,
)
from axiom_rift.operations.scientific_history import (
    project_frozen_family_exposure_context,
    project_historical_family_end_global_exposure_count,
)
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_REPLAY_CRITERIA,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyAuthority,
    HistoricalFamilySpec,
    historical_family_authority_from_payload,
)
from axiom_rift.research.semantic_question import (
    SemanticQuestionLineageProposal,
)
from axiom_rift.research.trials import TrialAccountant
from axiom_rift.research.volatility_duration_fixed_hold import (
    volatility_duration_fixed_hold_configurations,
    volatility_duration_fixed_hold_controlled_chassis,
    volatility_duration_fixed_hold_executable,
)
from axiom_rift.research.volatility_duration_fixed_hold_job import (
    build_volatility_duration_fixed_hold_job_plan,
)


VOLATILITY_DURATION_FIXED_HOLD_CAUSAL_QUESTION = (
    "Does the exact Writer-bound four-member volatility state-age family "
    "produce causal after-cost evidence under current completed-period "
    "execution, exact controls, and concurrent-family inference?"
)


@dataclass(frozen=True, slots=True)
class VolatilityDurationFixedHoldExposureContext:
    prior_global_exposure_count: int
    original_family_end_global_exposure_count: int

    def __post_init__(self) -> None:
        if (
            type(self.prior_global_exposure_count) is not int
            or type(self.original_family_end_global_exposure_count) is not int
            or self.original_family_end_global_exposure_count < 0
            or self.prior_global_exposure_count
            < self.original_family_end_global_exposure_count
        ):
            raise ValueError("volatility-duration exposure context is invalid")


def require_volatility_duration_fixed_hold_family_authority(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family_authority_id: str,
) -> HistoricalFamilyAuthority:
    with writer.open_stable_index() as (_control, index):
        record = index.get(
            "historical-family-authority",
            historical_family_authority_id,
        )
    if record is None:
        raise RuntimeError("volatility-duration family authority is absent")
    authority = historical_family_authority_from_payload(record.payload)
    if (
        record.record_id != authority.identity
        or record.status != "accepted"
        or record.subject != f"ReplayObligation:{spec.target_obligation_id}"
        or authority.identity != historical_family_authority_id
        or authority.replay_obligation_id != spec.target_obligation_id
        or authority.family.original_study_id != spec.original_study_id
    ):
        raise RuntimeError("volatility-duration family authority drifted")
    return authority


def project_volatility_duration_fixed_hold_exposure_context(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family: HistoricalFamilySpec,
) -> VolatilityDurationFixedHoldExposureContext:
    """Derive both prospective and original exposure counts from authority."""

    floor = TrialAccountant.from_foundation(
        writer.foundation_root
    ).prior_global_multiplicity_floor
    with writer.open_stable_index() as (_control, index):
        prospective = project_frozen_family_exposure_context(
            index,
            prior_global_exposure_floor=floor,
            study_id=spec.study_id,
            batch_id=None,
            expected_family_size=historical_family.family_size,
            parameter_name=(
                "historical_context_prior_global_exposure_count"
            ),
            allow_unregistered=True,
            allow_partial_registered=True,
        )
        original_end = project_historical_family_end_global_exposure_count(
            index,
            prior_global_exposure_floor=floor,
            family=historical_family,
        )
    return VolatilityDurationFixedHoldExposureContext(
        prior_global_exposure_count=(
            prospective.prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=original_end,
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
    prospective = tuple(member.executable.identity for member in members)
    floor = TrialAccountant.from_foundation(
        writer.foundation_root
    ).prior_global_multiplicity_floor
    with writer.open_stable_index() as (_control, index):
        context = project_frozen_family_exposure_context(
            index,
            prior_global_exposure_floor=floor,
            study_id=spec.study_id,
            batch_id=None,
            expected_family_size=len(members),
            parameter_name=(
                "historical_context_prior_global_exposure_count"
            ),
            allow_unregistered=True,
            allow_partial_registered=True,
        )
    if (
        context.prior_global_exposure_count
        != exposure_context.prior_global_exposure_count
        or (
            context.family_executable_ids
            and context.family_executable_ids
            != prospective[: len(context.family_executable_ids)]
        )
    ):
        raise RuntimeError(
            "volatility-duration prospective exposure context drifted"
        )


def build_volatility_duration_fixed_hold_profile_design(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family_authority_id: str,
    semantic_question_lineage: SemanticQuestionLineageProposal,
) -> FixedHoldReplayDesign:
    family_authority = require_volatility_duration_fixed_hold_family_authority(
        writer,
        spec=spec,
        historical_family_authority_id=historical_family_authority_id,
    )
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
        criterion_ids=criterion_ids,
        causal_question=VOLATILITY_DURATION_FIXED_HOLD_CAUSAL_QUESTION,
        mechanism_family=(
            "prospective-writer-bound-volatility-duration-fixed-hold"
        ),
        why_now=(
            "a prior replay attempt exposed reconstruction-code coupling; "
            "the obligation now requires a clean completed-period implementation"
        ),
        stop_or_reopen_condition=(
            "stop after the exact four-member family; reopen only under a "
            "typed replay resume condition or registered development material"
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
