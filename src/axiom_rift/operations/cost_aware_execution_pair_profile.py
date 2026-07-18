"""Writer-bound profile for the prospective STU-0070 execution pair."""

from __future__ import annotations

from axiom_rift.operations.bound_fixed_hold_profile import (
    BoundFixedHoldExposureContext,
    project_bound_fixed_hold_exposure_context,
    require_bound_fixed_hold_family_authorities,
    require_bound_fixed_hold_family_authority,
    require_bound_fixed_hold_registration_prefix,
)
from axiom_rift.operations.fixed_hold_replay_workflow import (
    FixedHoldReplayDesign,
    FixedHoldReplayMember,
    FixedHoldReplayMissionSpec,
    build_fixed_hold_replay_design,
)
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.cost_aware_execution_pair import (
    cost_aware_execution_pair_configurations,
    cost_aware_execution_pair_controlled_chassis,
    cost_aware_execution_pair_executable,
)
from axiom_rift.research.cost_aware_execution_pair_job import (
    build_cost_aware_execution_pair_job_plan,
)
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID,
    COST_AWARE_EXECUTION_HISTORICAL_FAMILY_ID,
    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
    COST_AWARE_EXECUTION_REPLAY_CRITERIA,
    COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyAuthority,
    HistoricalFamilySpec,
)
from axiom_rift.research.semantic_question import (
    SemanticQuestionLineageProposal,
)


COST_AWARE_EXECUTION_PAIR_CAUSAL_QUESTION = (
    "Does the exact prospective STU-0070 two-policy reconstruction show "
    "causal, after-cost benefit from completed-bar spread abstention against "
    "the unconditional next-open control under concurrent-family inference?"
)

_EXACT_HISTORICAL_MEMBER_ORDER = (
    COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID,
    COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID,
)
_EXACT_CRITERION_IDS = (
    "A01-minimum-trades",
    "A02-positive-density",
    "A03-profit-day-concentration",
    "B01-positive-native-cost",
    "B02-fold-profit-factor",
    "B03-slippage-stress",
    "B04-monthly-realized-drawdown-share",
    "C01-feature-prefix-invariance",
    "C02-decision-append-invariance",
    "C03-decision-time-causality",
    "C04-resolved-cost",
    "C05-finite-metrics",
    "D03-primary-control",
    "D04-primary-control-uncertainty",
    "E01-familywise-selection",
    "F01-evaluable-folds",
    "F02-winning-folds",
    "F03-positive-regimes",
)


CostAwareExecutionPairExposureContext = BoundFixedHoldExposureContext


def _require_exact_stu0070_family(
    historical_family: HistoricalFamilySpec,
) -> HistoricalFamilySpec:
    if (
        not isinstance(historical_family, HistoricalFamilySpec)
        or historical_family.identity
        != COST_AWARE_EXECUTION_HISTORICAL_FAMILY_ID
        or historical_family.family_size != 2
        or historical_family.target_historical_executable_id
        != COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID
        or tuple(
            member.historical_reference_executable_id
            for member in historical_family.members
        )
        != _EXACT_HISTORICAL_MEMBER_ORDER
    ):
        raise RuntimeError(
            "cost-aware execution authority is not the exact STU-0070 family"
        )
    return historical_family


def _require_cost_aware_exposure_context(
    exposure_context: CostAwareExecutionPairExposureContext,
) -> CostAwareExecutionPairExposureContext:
    if (
        not isinstance(exposure_context, BoundFixedHoldExposureContext)
        or exposure_context.original_family_end_global_exposure_count
        != COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        or exposure_context.prior_global_exposure_count
        < COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
    ):
        raise RuntimeError(
            "cost-aware execution exposure context does not preserve original "
            "family end 526"
        )
    return exposure_context


def _cost_aware_execution_pair_criterion_ids() -> tuple[str, ...]:
    criteria = COST_AWARE_EXECUTION_REPLAY_CRITERIA
    if type(criteria) is not tuple or len(criteria) != 18:
        raise RuntimeError("cost-aware execution criterion inventory drifted")
    values = tuple(
        sorted(
            item.get("criterion_id")
            for item in criteria
            if type(item) is dict
            and type(item.get("criterion_id")) is str
        )
    )
    if values != _EXACT_CRITERION_IDS or len(set(values)) != 18:
        raise RuntimeError("cost-aware execution criterion inventory drifted")
    return values


def require_cost_aware_execution_pair_family_authority(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family_authority_id: str,
) -> HistoricalFamilyAuthority:
    authority = require_bound_fixed_hold_family_authority(
        writer,
        spec=spec,
        historical_family_authority_id=historical_family_authority_id,
    )
    _require_exact_stu0070_family(authority.family)
    return authority


def project_cost_aware_execution_pair_exposure_context(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family: HistoricalFamilySpec,
) -> CostAwareExecutionPairExposureContext:
    """Project current prior exposure separately from immutable end 526."""

    family = _require_exact_stu0070_family(historical_family)
    return _require_cost_aware_exposure_context(
        project_bound_fixed_hold_exposure_context(
            writer,
            spec=spec,
            historical_family=family,
        )
    )


def cost_aware_execution_pair_members(
    spec: FixedHoldReplayMissionSpec,
    *,
    exposure_context: CostAwareExecutionPairExposureContext,
    historical_family: HistoricalFamilySpec,
    historical_family_authority_id: str,
) -> tuple[FixedHoldReplayMember, ...]:
    family = _require_exact_stu0070_family(historical_family)
    exposure = _require_cost_aware_exposure_context(exposure_context)
    values: list[FixedHoldReplayMember] = []
    for configuration in cost_aware_execution_pair_configurations(family):
        executable = cost_aware_execution_pair_executable(
            configuration,
            historical_family=family,
            historical_context_prior_global_exposure_count=(
                exposure.prior_global_exposure_count
            ),
            original_family_end_global_exposure_count=(
                exposure.original_family_end_global_exposure_count
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
                job_plan=build_cost_aware_execution_pair_job_plan(
                    mission_id=spec.mission_id,
                    study_id=spec.study_id,
                    executable_id=executable.identity,
                    historical_context_prior_global_exposure_count=(
                        exposure.prior_global_exposure_count
                    ),
                    original_family_end_global_exposure_count=(
                        exposure.original_family_end_global_exposure_count
                    ),
                    historical_family=family,
                    historical_family_authority_id=(
                        historical_family_authority_id
                    ),
                    replay_obligation_id=spec.target_obligation_id,
                ),
            )
        )
    members = tuple(values)
    if (
        len(members) != 2
        or tuple(member.ordinal for member in members) != (1, 2)
        or tuple(
            member.historical_reference_executable_id for member in members
        )
        != _EXACT_HISTORICAL_MEMBER_ORDER
        or sum(
            member.historical_reference_executable_id
            == COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID
            for member in members
        )
        != 1
    ):
        raise RuntimeError("cost-aware execution pair membership drifted")
    return members


def require_cost_aware_execution_pair_registration_prefix(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    members: tuple[FixedHoldReplayMember, ...],
    exposure_context: CostAwareExecutionPairExposureContext,
) -> None:
    _require_cost_aware_exposure_context(exposure_context)
    if (
        len(members) != 2
        or tuple(
            member.historical_reference_executable_id for member in members
        )
        != _EXACT_HISTORICAL_MEMBER_ORDER
    ):
        raise RuntimeError("cost-aware execution registration pair drifted")
    require_bound_fixed_hold_registration_prefix(
        writer,
        spec=spec,
        members=members,
        exposure_context=exposure_context,
    )


def build_cost_aware_execution_pair_profile_design(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family_authority_id: str,
    semantic_question_lineage: SemanticQuestionLineageProposal | None = None,
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
    for authority in family_authorities:
        _require_exact_stu0070_family(authority.family)
    family_authority = family_authorities[0]
    exposure = project_cost_aware_execution_pair_exposure_context(
        writer,
        spec=spec,
        historical_family=family_authority.family,
    )
    members = cost_aware_execution_pair_members(
        spec,
        exposure_context=exposure,
        historical_family=family_authority.family,
        historical_family_authority_id=family_authority.identity,
    )
    require_cost_aware_execution_pair_registration_prefix(
        writer,
        spec=spec,
        members=members,
        exposure_context=exposure,
    )
    targets = tuple(
        member
        for member in members
        if member.historical_reference_executable_id
        == COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID
    )
    if len(targets) != 1:
        raise RuntimeError("cost-aware execution target member is ambiguous")
    return build_fixed_hold_replay_design(
        writer,
        spec=spec,
        members=members,
        target_executable_id=targets[0].executable.identity,
        controlled_chassis=cost_aware_execution_pair_controlled_chassis(
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
        criterion_ids=_cost_aware_execution_pair_criterion_ids(),
        causal_question=COST_AWARE_EXECUTION_PAIR_CAUSAL_QUESTION,
        mechanism_family=(
            "prospective-stu0070-cost-aware-execution-paired-policy-replay"
        ),
        why_now=(
            "the P1 audit queue requires a prospective point-in-time "
            "reconstruction of the unresolved STU-0070 execution family"
        ),
        stop_or_reopen_condition=(
            "stop after both policies; reopen only under a typed replay "
            "resume condition or registered development material"
        ),
        semantic_question_lineage=semantic_question_lineage,
    )


__all__ = [
    "COST_AWARE_EXECUTION_PAIR_CAUSAL_QUESTION",
    "CostAwareExecutionPairExposureContext",
    "build_cost_aware_execution_pair_profile_design",
    "cost_aware_execution_pair_members",
    "project_cost_aware_execution_pair_exposure_context",
    "require_cost_aware_execution_pair_family_authority",
    "require_cost_aware_execution_pair_registration_prefix",
]
