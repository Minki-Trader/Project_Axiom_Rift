"""Shared Writer-bound family and exposure projection for fixed-hold profiles."""

from __future__ import annotations

from dataclasses import dataclass

from axiom_rift.operations.fixed_hold_replay_workflow import (
    FixedHoldReplayMember,
    FixedHoldReplayMissionSpec,
)
from axiom_rift.operations.scientific_history import (
    project_frozen_family_exposure_context,
    project_historical_family_end_global_exposure_count,
)
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyAuthority,
    HistoricalFamilySpec,
    historical_family_authority_from_payload,
)
from axiom_rift.research.trials import TrialAccountant


@dataclass(frozen=True, slots=True)
class BoundFixedHoldExposureContext:
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
            raise ValueError("Writer-bound fixed-hold exposure context is invalid")


def require_bound_fixed_hold_family_authority(
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
        raise RuntimeError("fixed-hold historical family authority is absent")
    authority = historical_family_authority_from_payload(record.payload)
    if (
        record.record_id != authority.identity
        or record.status != "accepted"
        or record.subject != f"ReplayObligation:{spec.target_obligation_id}"
        or authority.identity != historical_family_authority_id
        or authority.replay_obligation_id != spec.target_obligation_id
        or authority.family.original_study_id != spec.original_study_id
    ):
        raise RuntimeError("fixed-hold historical family authority drifted")
    return authority


def project_bound_fixed_hold_exposure_context(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family: HistoricalFamilySpec,
) -> BoundFixedHoldExposureContext:
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
    return BoundFixedHoldExposureContext(
        prior_global_exposure_count=prospective.prior_global_exposure_count,
        original_family_end_global_exposure_count=original_end,
    )


def require_bound_fixed_hold_registration_prefix(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    members: tuple[FixedHoldReplayMember, ...],
    exposure_context: BoundFixedHoldExposureContext,
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
        raise RuntimeError("fixed-hold prospective exposure context drifted")


__all__ = [
    "BoundFixedHoldExposureContext",
    "project_bound_fixed_hold_exposure_context",
    "require_bound_fixed_hold_family_authority",
    "require_bound_fixed_hold_registration_prefix",
]
