"""Shared Writer-bound family and exposure projection for fixed-hold profiles."""

from __future__ import annotations

from dataclasses import dataclass

from axiom_rift.operations.fixed_hold_replay_workflow import (
    FixedHoldReplayMember,
    FixedHoldReplayMissionSpec,
)
from axiom_rift.operations.historical_family_authority_admission import (
    HistoricalFamilyAuthorityAdmissionError,
    require_recorded_historical_family_authority,
)
from axiom_rift.operations.scientific_history import (
    project_frozen_family_exposure_context,
    project_historical_family_end_global_exposure_count,
)
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyAuthority,
    HistoricalFamilySpec,
    historical_family_core_identity,
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
    return require_bound_fixed_hold_family_authorities(
        writer,
        spec=spec,
        historical_family_authority_id=historical_family_authority_id,
    )[0]


def require_bound_fixed_hold_family_authorities(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    historical_family_authority_id: str,
    additional_historical_family_authority_ids: tuple[str, ...] = (),
) -> tuple[HistoricalFamilyAuthority, ...]:
    authority_ids = (
        historical_family_authority_id,
        *additional_historical_family_authority_ids,
    )
    if (
        type(additional_historical_family_authority_ids) is not tuple
        or len(authority_ids) != len(spec.replay_obligation_ids)
        or len(set(authority_ids)) != len(authority_ids)
    ):
        raise RuntimeError(
            "fixed-hold family authorities do not cover selected obligations"
        )
    with writer.open_stable_index() as (_control, index):
        records = tuple(
            index.get("historical-family-authority", authority_id)
            for authority_id in authority_ids
        )
        if any(record is None for record in records):
            raise RuntimeError("fixed-hold historical family authority is absent")
        try:
            authorities = tuple(
                require_recorded_historical_family_authority(index, record)
                for record in records
                if record is not None
            )
        except HistoricalFamilyAuthorityAdmissionError as exc:
            raise RuntimeError(str(exc)) from exc
    primary = authorities[0]
    primary_core = historical_family_core_identity(primary.family)
    for record, authority in zip(records, authorities, strict=True):
        assert record is not None
        if (
            record.record_id != authority.identity
            or record.status != "accepted"
            or record.subject
            != f"ReplayObligation:{authority.replay_obligation_id}"
            or authority.family.original_study_id
            != spec.effective_family_origin_study_id
            or historical_family_core_identity(authority.family)
            != primary_core
            or authority.reconstruction_source_path
            != primary.reconstruction_source_path
            or authority.reconstruction_source_sha256
            != primary.reconstruction_source_sha256
            or authority.reconstruction_only_parameter_names
            != primary.reconstruction_only_parameter_names
        ):
            raise RuntimeError("fixed-hold historical family authority drifted")
    if (
        authorities[0].identity != historical_family_authority_id
        or set(authority.replay_obligation_id for authority in authorities)
        != set(spec.replay_obligation_ids)
        or primary.replay_obligation_id != spec.target_obligation_id
    ):
        raise RuntimeError("fixed-hold historical family coverage drifted")
    return authorities


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
    "require_bound_fixed_hold_family_authorities",
    "require_bound_fixed_hold_registration_prefix",
]
