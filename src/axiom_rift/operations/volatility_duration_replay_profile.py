"""Writer-owned assembly for STU-0051 family replay profiles."""

from __future__ import annotations

from axiom_rift.operations.fixed_hold_replay_workflow import (
    FixedHoldReplayDesign,
    FixedHoldReplayMember,
    FixedHoldReplayMissionSpec,
    build_fixed_hold_replay_design,
)
from axiom_rift.operations.scientific_history import (
    project_frozen_family_exposure_context,
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
from axiom_rift.research.volatility_duration_replay import (
    volatility_duration_replay_configurations,
    volatility_duration_replay_controlled_chassis,
    volatility_duration_replay_executable,
)
from axiom_rift.research.volatility_duration_replay_job import (
    build_volatility_duration_replay_job_plan,
)


STU0051_CAUSAL_QUESTION = (
    "Does an exact prospective reconstruction of the four-member STU-0051 "
    "volatility state-age family preserve causal, after-cost evidence under "
    "exact controls and concurrent-family inference?"
)


def volatility_duration_replay_members(
    spec: FixedHoldReplayMissionSpec,
    *,
    historical_context_count: int,
    historical_family: HistoricalFamilySpec,
    historical_family_authority_id: str,
) -> tuple[FixedHoldReplayMember, ...]:
    """Bind the exact historical family to fresh Study-scoped Job plans."""

    values: list[FixedHoldReplayMember] = []
    for configuration in volatility_duration_replay_configurations(
        historical_family=historical_family
    ):
        executable = volatility_duration_replay_executable(
            configuration,
            historical_context_prior_global_exposure_count=(
                historical_context_count
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
                    mission_id=spec.mission_id,
                    study_id=spec.study_id,
                    executable_id=executable.identity,
                    historical_context_prior_global_exposure_count=(
                        historical_context_count
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
        len(members) != 4
        or tuple(
            member.historical_reference_executable_id for member in members
        )
        != tuple(
            member.historical_reference_executable_id
            for member in historical_family.members
        )
    ):
        raise RuntimeError("STU-0051 exact replay family drifted")
    return members


def require_volatility_duration_family_authority(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family_authority_id: str,
) -> HistoricalFamilyAuthority:
    """Load the exact accepted family through the authenticated index."""

    with writer.open_stable_index() as (_control, index):
        record = index.get(
            "historical-family-authority",
            historical_family_authority_id,
        )
    if record is None:
        raise RuntimeError("STU-0051 historical family authority is absent")
    authority = historical_family_authority_from_payload(record.payload)
    if (
        record.record_id != authority.identity
        or record.status != "accepted"
        or record.subject
        != f"ReplayObligation:{spec.target_obligation_id}"
        or authority.identity != historical_family_authority_id
        or authority.replay_obligation_id != spec.target_obligation_id
        or authority.family.original_study_id != spec.original_study_id
    ):
        raise RuntimeError("STU-0051 historical family authority drifted")
    return authority


def require_volatility_duration_historical_context(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    members: tuple[FixedHoldReplayMember, ...],
    historical_context_count: int,
) -> None:
    """Require the frozen global exposure context without counting this Study."""

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
            parameter_name="historical_context_prior_global_exposure_count",
            allow_unregistered=True,
            allow_partial_registered=True,
        )
    if (
        context.prior_global_exposure_count
        != historical_context_count
        or (
            context.family_executable_ids
            and context.family_executable_ids
            != prospective[: len(context.family_executable_ids)]
        )
    ):
        raise RuntimeError("STU-0051 historical exposure context drifted")


def build_volatility_duration_replay_profile_design(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_context_count: int,
    historical_family_authority_id: str,
    semantic_question_lineage: SemanticQuestionLineageProposal,
) -> FixedHoldReplayDesign:
    """Build one exact STU-0051 replay from explicit production authority."""

    family_authority = require_volatility_duration_family_authority(
        writer,
        spec=spec,
        historical_family_authority_id=historical_family_authority_id,
    )
    members = volatility_duration_replay_members(
        spec,
        historical_context_count=historical_context_count,
        historical_family=family_authority.family,
        historical_family_authority_id=family_authority.identity,
    )
    require_volatility_duration_historical_context(
        writer,
        spec=spec,
        members=members,
        historical_context_count=historical_context_count,
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
        raise RuntimeError("STU-0051 target member is ambiguous")
    criterion_ids = tuple(
        sorted(str(item["criterion_id"]) for item in FIXED_HOLD_REPLAY_CRITERIA)
    )
    return build_fixed_hold_replay_design(
        writer,
        spec=spec,
        members=members,
        target_executable_id=targets[0].executable.identity,
        controlled_chassis=volatility_duration_replay_controlled_chassis(
            historical_context_prior_global_exposure_count=(
                historical_context_count
            )
        ),
        historical_family_manifest=family_authority.family.manifest(),
        historical_family_authority_id=family_authority.identity,
        criterion_ids=criterion_ids,
        causal_question=STU0051_CAUSAL_QUESTION,
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
    "STU0051_CAUSAL_QUESTION",
    "build_volatility_duration_replay_profile_design",
    "require_volatility_duration_family_authority",
    "require_volatility_duration_historical_context",
    "volatility_duration_replay_members",
]
