from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyBindingError,
    historical_family_core_identity,
)
from axiom_rift.research.historical_family_stu0046 import (
    STU0046_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0047 import (
    STU0047_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0049 import (
    STU0049_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0050 import (
    STU0050_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_fixed_four_family import (
    build_historical_fixed_four_family,
)
from axiom_rift.research.historical_study_registry import (
    HISTORICAL_FAMILY_CORE_IDENTITY_BY_MODULE,
    HISTORICAL_FAMILY_IDENTITY_BY_MODULE,
    HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256,
)


ROOT = Path(__file__).resolve().parents[2]
FAMILIES = {
    "historical_family_stu0046.py": STU0046_HISTORICAL_FAMILY,
    "historical_family_stu0047.py": STU0047_HISTORICAL_FAMILY,
    "historical_family_stu0049.py": STU0049_HISTORICAL_FAMILY,
    "historical_family_stu0050.py": STU0050_HISTORICAL_FAMILY,
}


@pytest.mark.parametrize(("module_name", "family"), FAMILIES.items())
def test_frozen_fixed_four_family_matches_registry(
    module_name: str,
    family: object,
) -> None:
    source = ROOT / "src/axiom_rift/research" / module_name
    identities = tuple(
        member.historical_reference_executable_id
        for member in family.members
    )

    assert sha256(source.read_bytes()).hexdigest() == (
        HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256[module_name]
    )
    assert family.identity == HISTORICAL_FAMILY_IDENTITY_BY_MODULE[module_name]
    assert historical_family_core_identity(family) == (
        HISTORICAL_FAMILY_CORE_IDENTITY_BY_MODULE[module_name]
    )
    assert tuple(member.ordinal for member in family.members) == (1, 2, 3, 4)
    assert {
        (
            control.subject_historical_executable_id,
            control.opposite_historical_executable_id,
            control.feature_historical_executable_ids,
        )
        for control in family.controls
    } == {
        (identities[0], identities[1], (identities[2],)),
        (identities[1], identities[0], (identities[3],)),
        (identities[2], identities[3], (identities[0],)),
        (identities[3], identities[2], (identities[1],)),
    }


def test_fixed_four_builder_rejects_incomplete_surface() -> None:
    rows = tuple(
        (
            member.ordinal,
            member.configuration_id,
            member.historical_reference_executable_id,
            member.parameter_values(),
        )
        for member in STU0046_HISTORICAL_FAMILY.members[:3]
    )

    with pytest.raises(
        HistoricalFamilyBindingError,
        match="requires four rows",
    ):
        build_historical_fixed_four_family(
            original_study_id="STU-0046",
            original_batch_id=STU0046_HISTORICAL_FAMILY.original_batch_id,
            target_historical_executable_id=(
                STU0046_HISTORICAL_FAMILY.target_historical_executable_id
            ),
            rows=rows,
        )


def test_fixed_four_builder_rejects_wrong_sign_pair() -> None:
    rows = tuple(
        (
            member.ordinal,
            member.configuration_id,
            member.historical_reference_executable_id,
            {
                **member.parameter_values(),
                **({"signal_sign": 1} if member.ordinal == 2 else {}),
            },
        )
        for member in STU0046_HISTORICAL_FAMILY.members
    )

    with pytest.raises(
        HistoricalFamilyBindingError,
        match="complete two-by-two surface",
    ):
        build_historical_fixed_four_family(
            original_study_id="STU-0046",
            original_batch_id=STU0046_HISTORICAL_FAMILY.original_batch_id,
            target_historical_executable_id=(
                STU0046_HISTORICAL_FAMILY.target_historical_executable_id
            ),
            rows=rows,
        )
