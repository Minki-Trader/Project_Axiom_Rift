"""Strict builder for one frozen two-feature, two-sign historical family."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from axiom_rift.research.historical_family_binding import (
    ControlBinding,
    HistoricalFamilyBindingError,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
)


FixedFourRow = tuple[int, str, str, Mapping[str, Any]]


def build_historical_fixed_four_family(
    *,
    original_study_id: str,
    original_batch_id: str,
    target_historical_executable_id: str,
    rows: tuple[FixedFourRow, ...],
) -> HistoricalFamilySpec:
    """Build the exact paired-sign controls for two immutable features."""

    if type(rows) is not tuple or len(rows) != 4:
        raise HistoricalFamilyBindingError(
            "fixed-four historical family requires four rows"
        )
    members = tuple(
        HistoricalMemberSpec(
            ordinal=ordinal,
            configuration_id=configuration_id,
            historical_reference_executable_id=historical_id,
            parameters=dict(parameters),
        )
        for ordinal, configuration_id, historical_id, parameters in rows
    )
    if tuple(member.ordinal for member in members) != (1, 2, 3, 4):
        raise HistoricalFamilyBindingError(
            "fixed-four historical family order is not canonical"
        )
    parameters = tuple(member.parameter_values() for member in members)
    if (
        parameters[0].get("profile") != parameters[1].get("profile")
        or parameters[2].get("profile") != parameters[3].get("profile")
        or parameters[0].get("profile") == parameters[2].get("profile")
        or tuple(item.get("signal_sign") for item in parameters)
        != (1, -1, 1, -1)
        or any(
            {
                key: value
                for key, value in parameters[left].items()
                if key != "signal_sign"
            }
            != {
                key: value
                for key, value in parameters[right].items()
                if key != "signal_sign"
            }
            for left, right in ((0, 1), (2, 3))
        )
    ):
        raise HistoricalFamilyBindingError(
            "fixed-four historical family is not a complete two-by-two surface"
        )
    identities = tuple(
        member.historical_reference_executable_id for member in members
    )
    if target_historical_executable_id not in identities:
        raise HistoricalFamilyBindingError(
            "fixed-four historical family target is not a member"
        )
    controls = (
        ControlBinding(
            subject_historical_executable_id=identities[0],
            opposite_historical_executable_id=identities[1],
            feature_historical_executable_ids=(identities[2],),
        ),
        ControlBinding(
            subject_historical_executable_id=identities[1],
            opposite_historical_executable_id=identities[0],
            feature_historical_executable_ids=(identities[3],),
        ),
        ControlBinding(
            subject_historical_executable_id=identities[2],
            opposite_historical_executable_id=identities[3],
            feature_historical_executable_ids=(identities[0],),
        ),
        ControlBinding(
            subject_historical_executable_id=identities[3],
            opposite_historical_executable_id=identities[2],
            feature_historical_executable_ids=(identities[1],),
        ),
    )
    return HistoricalFamilySpec(
        original_study_id=original_study_id,
        original_batch_id=original_batch_id,
        target_historical_executable_id=target_historical_executable_id,
        members=members,
        controls=controls,
    )


__all__ = ["FixedFourRow", "build_historical_fixed_four_family"]
