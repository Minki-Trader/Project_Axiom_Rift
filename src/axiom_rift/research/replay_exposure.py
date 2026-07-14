"""Frozen Project Goal exposure context for registered replay families.

The historical search context belongs to the instant immediately before the
first member of one concurrently registered family.  Later unrelated trials
must not retroactively change that context or make a completed replay
unreadable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from axiom_rift.storage.index import IndexRecord


class ReplayExposureError(ValueError):
    """Raised when a replay family cannot recover one frozen exposure head."""


@dataclass(frozen=True, slots=True)
class FrozenFamilyExposureContext:
    prior_global_exposure_count: int
    family_executable_ids: tuple[str, ...]
    first_family_authority_sequence: int | None


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ReplayExposureError(f"{name} must be non-empty ASCII")
    return value


def derive_frozen_family_exposure_context(
    *,
    trials: Sequence[IndexRecord],
    prior_global_exposure_floor: int,
    study_id: str,
    expected_family_size: int,
    parameter_name: str | None,
    allow_unregistered: bool,
) -> FrozenFamilyExposureContext:
    """Derive the pre-family count from immutable trial authority order.

    Before registration the current trial count is the prospective context.
    After registration the context is frozen at the first family member, so
    trials registered later are deliberately irrelevant.
    """

    _ascii("replay Study id", study_id)
    if parameter_name is not None:
        _ascii("replay exposure parameter", parameter_name)
    if (
        type(prior_global_exposure_floor) is not int
        or prior_global_exposure_floor < 0
        or type(expected_family_size) is not int
        or expected_family_size < 1
        or type(allow_unregistered) is not bool
    ):
        raise ReplayExposureError("replay exposure bounds are invalid")
    values = tuple(trials)
    if any(not isinstance(record, IndexRecord) for record in values):
        raise ReplayExposureError("replay trial projection is not typed")
    sequences = tuple(record.authority_sequence for record in values)
    if any(type(sequence) is not int or sequence < 1 for sequence in sequences):
        raise ReplayExposureError("replay trial authority order is unavailable")
    if len(sequences) != len(set(sequences)):
        raise ReplayExposureError("replay trial authority order is ambiguous")

    family = tuple(
        record for record in values if record.payload.get("study_id") == study_id
    )
    if not family:
        if not allow_unregistered:
            raise ReplayExposureError("registered replay family is absent")
        return FrozenFamilyExposureContext(
            prior_global_exposure_count=(
                prior_global_exposure_floor + len(values)
            ),
            family_executable_ids=(),
            first_family_authority_sequence=None,
        )
    if len(family) != expected_family_size:
        raise ReplayExposureError("registered replay family is incomplete")
    family_ids = tuple(record.record_id for record in family)
    if len(family_ids) != len(set(family_ids)):
        raise ReplayExposureError("registered replay family is duplicated")
    first_sequence = min(
        record.authority_sequence for record in family
        if record.authority_sequence is not None
    )
    frozen_count = prior_global_exposure_floor + sum(
        record.authority_sequence < first_sequence
        for record in values
        if record.authority_sequence is not None
    )
    if parameter_name is not None:
        contexts: set[int] = set()
        for record in family:
            executable = record.payload.get("executable")
            parameters = (
                None
                if not isinstance(executable, Mapping)
                else executable.get("parameters")
            )
            context = (
                None
                if not isinstance(parameters, Mapping)
                else parameters.get(parameter_name)
            )
            if type(context) is not int or context < 0:
                raise ReplayExposureError(
                    "registered replay family exposure context is invalid"
                )
            contexts.add(context)
        if contexts != {frozen_count}:
            raise ReplayExposureError(
                "registered replay family differs from its frozen exposure head"
            )
    return FrozenFamilyExposureContext(
        prior_global_exposure_count=frozen_count,
        family_executable_ids=family_ids,
        first_family_authority_sequence=first_sequence,
    )


__all__ = [
    "FrozenFamilyExposureContext",
    "ReplayExposureError",
    "derive_frozen_family_exposure_context",
]
