from __future__ import annotations

from copy import deepcopy

import pytest

from axiom_rift.operations.scientific_multiplicity_authority import (
    ScientificMultiplicityAuthorityError,
    _bind_selection_registration_to_batch,
)
from axiom_rift.research.portfolio import (
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
)
from axiom_rift.storage.index import IndexRecord


FIRST = "executable:" + "f" * 64
SECOND = "executable:" + "1" * 64
BATCH_ID = "batch:" + "2" * 64


def _batch() -> IndexRecord:
    family = ConcurrentFamilyManifest(
        evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
        executable_ids=(FIRST, SECOND),
    )
    return IndexRecord(
        kind="batch-open",
        record_id=BATCH_ID,
        subject="Study:STU-FAMILY-ORDER",
        status="open",
        fingerprint="3" * 64,
        payload={
            "spec": {
                "acceptance_profile": {
                    "concurrent_family": family.to_identity_payload(),
                },
                "max_trials": 2,
            }
        },
    )


def _selection() -> dict[str, object]:
    return {
        "criterion_id": "E01-familywise-selection",
        "family_id": "selection-family:test",
        "family_registration_hash": "4" * 64,
        "family_size": 2,
        "member_id": FIRST,
        "ordered_member_ids": sorted((FIRST, SECOND)),
    }


def test_e01_binds_canonical_membership_not_runner_role_order() -> None:
    result = _bind_selection_registration_to_batch(
        [_selection()],
        batch_record=_batch(),
        expected_batch_id=BATCH_ID,
        executable_id=FIRST,
    )
    assert result is not None
    assert result["ordered_member_ids"] == sorted((FIRST, SECOND))


def test_e01_still_rejects_a_different_member_family() -> None:
    selection = deepcopy(_selection())
    selection["ordered_member_ids"] = [SECOND, "executable:" + "a" * 64]
    with pytest.raises(
        ScientificMultiplicityAuthorityError,
        match="exact Batch family",
    ):
        _bind_selection_registration_to_batch(
            [selection],
            batch_record=_batch(),
            expected_batch_id=BATCH_ID,
            executable_id=FIRST,
        )
