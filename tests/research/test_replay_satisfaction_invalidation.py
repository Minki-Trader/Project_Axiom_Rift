from __future__ import annotations

import pytest

from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.replay_satisfaction_invalidation import (
    ReplayMultiplicityBindingDefect,
    ReplayMultiplicityDefectCode,
    ReplaySelectionFamilyObservation,
    SELECTION_CRITERION_ID,
)


EXPECTED_MEMBER_IDS = (
    "executable:" + "3" * 64,
    "executable:" + "1" * 64,
    "executable:" + "2" * 64,
)


def _registration_hash(ordered_member_ids: tuple[str, ...]) -> str:
    return canonical_digest(
        domain="scientific-v2-multiplicity-family",
        payload={
            "alpha_ppm": 100_000,
            "family_id": "family:test",
            "family_size": len(ordered_member_ids),
            "method": "holm",
            "ordered_member_ids": list(ordered_member_ids),
            "schema": "scientific_multiplicity_family_registration.v1",
        },
    )


def _observation(
    executable_id: str,
    *,
    ordered_member_ids: tuple[str, ...],
) -> ReplaySelectionFamilyObservation:
    token = int(executable_id[-1], 16)
    return ReplaySelectionFamilyObservation(
        executable_id=executable_id,
        completion_record_id=f"{token + 4:064x}",
        family_id="family:test",
        family_size=len(ordered_member_ids),
        method="holm",
        alpha_ppm=100_000,
        registered_member_id=executable_id,
        ordered_member_ids=ordered_member_ids,
        family_registration_hash=_registration_hash(ordered_member_ids),
    )


def _defect(
    observed_order: tuple[str, ...],
    *,
    actual_member_set_mismatch: bool = False,
) -> ReplayMultiplicityBindingDefect:
    def member_ids(executable_id: str) -> tuple[str, ...]:
        if not actual_member_set_mismatch:
            return observed_order
        peer = next(item for item in EXPECTED_MEMBER_IDS if item != executable_id)
        return (executable_id, peer, "executable:" + "9" * 64)

    return ReplayMultiplicityBindingDefect(
        code=(
            ReplayMultiplicityDefectCode.SELECTION_FAMILY_MEMBERSHIP_MISMATCH
        ),
        criterion_id=SELECTION_CRITERION_ID,
        batch_open_record_id="batch:" + "a" * 64,
        batch_close_record_id="b" * 64,
        expected_executable_ids=EXPECTED_MEMBER_IDS,
        expected_family_size=len(EXPECTED_MEMBER_IDS),
        observations=tuple(
            _observation(
                executable_id,
                ordered_member_ids=member_ids(executable_id),
            )
            for executable_id in sorted(EXPECTED_MEMBER_IDS)
        ),
    )


def test_same_set_reversed_registration_is_not_a_revocation_defect() -> None:
    reversed_order = tuple(reversed(EXPECTED_MEMBER_IDS))
    with pytest.raises(ValueError, match="membership mismatch is not present"):
        _defect(reversed_order)


def test_actual_member_set_substitution_remains_a_membership_defect() -> None:
    defect = _defect(
        EXPECTED_MEMBER_IDS,
        actual_member_set_mismatch=True,
    )
    assert defect.expected_executable_ids == EXPECTED_MEMBER_IDS
    assert all(
        set(observation.ordered_member_ids) != set(EXPECTED_MEMBER_IDS)
        for observation in defect.observations
    )


def test_exact_batch_order_cannot_be_mislabeled_as_a_membership_defect() -> None:
    with pytest.raises(ValueError, match="membership mismatch is not present"):
        _defect(EXPECTED_MEMBER_IDS)


def test_membership_defect_round_trip_preserves_exact_batch_order() -> None:
    defect = _defect(
        EXPECTED_MEMBER_IDS,
        actual_member_set_mismatch=True,
    )
    rebuilt = ReplayMultiplicityBindingDefect.from_mapping(
        defect.to_identity_payload()
    )
    assert rebuilt == defect
    assert rebuilt.expected_executable_ids == EXPECTED_MEMBER_IDS


def test_registration_hash_binds_member_order() -> None:
    reversed_order = tuple(reversed(EXPECTED_MEMBER_IDS))
    with pytest.raises(ValueError, match="registration hash is invalid"):
        ReplaySelectionFamilyObservation(
            executable_id=EXPECTED_MEMBER_IDS[0],
            completion_record_id="c" * 64,
            family_id="family:test",
            family_size=len(EXPECTED_MEMBER_IDS),
            method="holm",
            alpha_ppm=100_000,
            registered_member_id=EXPECTED_MEMBER_IDS[0],
            ordered_member_ids=reversed_order,
            family_registration_hash=_registration_hash(EXPECTED_MEMBER_IDS),
        )
