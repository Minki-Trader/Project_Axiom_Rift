from __future__ import annotations

from copy import deepcopy
from importlib import import_module

import pytest

from axiom_rift.research.historical_family_binding import (
    HISTORICAL_FAMILY_AUTHORITY_SCHEMA,
    ControlBinding,
    HistoricalFamilyAuthority,
    HistoricalFamilyBindingError,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
    historical_family_authority_from_payload,
    historical_family_core_identity,
    historical_family_from_manifest,
)
from axiom_rift.research.historical_study_registry import (
    HISTORICAL_FAMILY_CORE_IDENTITY_BY_MODULE,
)


def _executable(ordinal: int) -> str:
    return f"executable:{ordinal:064x}"


def _family() -> HistoricalFamilySpec:
    members = tuple(
        HistoricalMemberSpec(
            ordinal=ordinal,
            configuration_id=f"configuration-{ordinal}",
            historical_reference_executable_id=_executable(ordinal),
            parameters={
                "holding_bars": 24,
                "legacy_profile": f"profile-{ordinal}",
                "signal_sign": 1 if ordinal in {1, 3} else -1,
                **({"member_specific": ordinal} if ordinal == 1 else {}),
            },
        )
        for ordinal in range(1, 5)
    )
    controls = (
        ControlBinding(
            subject_historical_executable_id=_executable(1),
            opposite_historical_executable_id=_executable(2),
            feature_historical_executable_ids=(_executable(3),),
        ),
        ControlBinding(
            subject_historical_executable_id=_executable(2),
            opposite_historical_executable_id=_executable(1),
            feature_historical_executable_ids=(_executable(4),),
        ),
        ControlBinding(
            subject_historical_executable_id=_executable(3),
            opposite_historical_executable_id=_executable(4),
            feature_historical_executable_ids=(_executable(1),),
        ),
        ControlBinding(
            subject_historical_executable_id=_executable(4),
            opposite_historical_executable_id=_executable(3),
            feature_historical_executable_ids=(_executable(2),),
        ),
    )
    return HistoricalFamilySpec(
        original_study_id="STU-9001",
        original_batch_id="batch:" + "9" * 64,
        target_historical_executable_id=_executable(4),
        members=members,
        controls=controls,
    )


def _authority(
    reconstruction_only_parameter_names: tuple[str, ...],
) -> HistoricalFamilyAuthority:
    return HistoricalFamilyAuthority(
        replay_obligation_id=(
            "historical-replay-obligation:" + "8" * 64
        ),
        family=_family(),
        reconstruction_source_path="records/reconstruction/stu9001.json",
        reconstruction_source_sha256="7" * 64,
        reconstruction_only_parameter_names=(
            reconstruction_only_parameter_names
        ),
    )


def test_typed_family_manifest_round_trips_exact_identity_and_values() -> None:
    family = _family()
    rebuilt = historical_family_from_manifest(family.manifest())

    assert rebuilt is not family
    assert rebuilt.identity == family.identity
    assert rebuilt.manifest() == family.manifest()
    assert tuple(
        member.parameter_values() for member in rebuilt.members
    ) == tuple(member.parameter_values() for member in family.members)
    assert tuple(control.manifest() for control in rebuilt.controls) == tuple(
        control.manifest() for control in family.controls
    )


def test_family_core_identity_is_independent_of_selected_target() -> None:
    primary = _family()
    sibling_target = HistoricalFamilySpec(
        original_study_id=primary.original_study_id,
        original_batch_id=primary.original_batch_id,
        target_historical_executable_id=_executable(1),
        members=primary.members,
        controls=primary.controls,
    )

    assert primary.identity != sibling_target.identity
    assert historical_family_core_identity(primary) == (
        historical_family_core_identity(sibling_target)
    )


def test_family_core_identity_changes_with_exact_membership() -> None:
    primary = _family()
    replacement_reference = _executable(5)
    replacement_members = (
        HistoricalMemberSpec(
            ordinal=1,
            configuration_id="configuration-1",
            historical_reference_executable_id=replacement_reference,
            parameters=primary.members[0].parameter_values(),
        ),
        *primary.members[1:],
    )
    replacement_controls = (
        ControlBinding(
            subject_historical_executable_id=replacement_reference,
            opposite_historical_executable_id=_executable(2),
            feature_historical_executable_ids=(_executable(3),),
        ),
        ControlBinding(
            subject_historical_executable_id=_executable(2),
            opposite_historical_executable_id=replacement_reference,
            feature_historical_executable_ids=(_executable(4),),
        ),
        ControlBinding(
            subject_historical_executable_id=_executable(3),
            opposite_historical_executable_id=_executable(4),
            feature_historical_executable_ids=(replacement_reference,),
        ),
        ControlBinding(
            subject_historical_executable_id=_executable(4),
            opposite_historical_executable_id=_executable(3),
            feature_historical_executable_ids=(_executable(2),),
        ),
    )
    changed_membership = HistoricalFamilySpec(
        original_study_id=primary.original_study_id,
        original_batch_id=primary.original_batch_id,
        target_historical_executable_id=_executable(4),
        members=replacement_members,
        controls=replacement_controls,
    )

    assert historical_family_core_identity(primary) != (
        historical_family_core_identity(changed_membership)
    )


@pytest.mark.parametrize(
    "module_filename",
    tuple(sorted(HISTORICAL_FAMILY_CORE_IDENTITY_BY_MODULE)),
)
def test_registered_historical_family_core_matches_frozen_module(
    module_filename: str,
) -> None:
    module = import_module(
        "axiom_rift.research." + module_filename.removesuffix(".py")
    )
    historical_families = tuple(
        value
        for name, value in vars(module).items()
        if name.endswith("_HISTORICAL_FAMILY")
    )
    assert len(historical_families) == 1
    bound_family = historical_family_from_manifest(
        historical_families[0].manifest()
    )

    assert historical_family_core_identity(bound_family) == (
        HISTORICAL_FAMILY_CORE_IDENTITY_BY_MODULE[module_filename]
    )


def test_authority_v2_sorts_declarations_and_round_trips_canonically() -> None:
    authority = _authority(("signal_sign", "legacy_profile"))

    assert HISTORICAL_FAMILY_AUTHORITY_SCHEMA == (
        "historical_family_authority.v2"
    )
    assert authority.reconstruction_only_parameter_names == (
        "legacy_profile",
        "signal_sign",
    )
    payload = authority.to_identity_payload()
    assert payload["reconstruction_only_parameter_names"] == [
        "legacy_profile",
        "signal_sign",
    ]

    rebuilt = historical_family_authority_from_payload(payload)
    assert rebuilt.identity == authority.identity
    assert rebuilt.to_identity_payload() == payload
    assert rebuilt.family.identity == authority.family.identity


@pytest.mark.parametrize(
    ("names", "message"),
    (
        (("legacy_profile", "legacy_profile"), "unique"),
        (("member_specific",), "every member"),
    ),
)
def test_authority_rejects_duplicate_or_non_familywide_declarations(
    names: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(HistoricalFamilyBindingError, match=message):
        _authority(names)


@pytest.mark.parametrize(
    ("attack", "message"),
    (
        ("v1", "malformed"),
        ("missing_field", "malformed"),
        ("family_identity", "not canonical"),
        ("unsorted_names", "not canonical"),
        ("duplicate_names", "unique"),
        ("non_familywide_name", "every member"),
    ),
)
def test_authority_payload_fails_closed_on_legacy_missing_or_tampered_data(
    attack: str,
    message: str,
) -> None:
    payload = deepcopy(
        _authority(("legacy_profile", "signal_sign")).to_identity_payload()
    )
    if attack == "v1":
        payload["schema"] = "historical_family_authority.v1"
    elif attack == "missing_field":
        payload.pop("reconstruction_only_parameter_names")
    elif attack == "family_identity":
        payload["family_identity"] = "historical-family:" + "0" * 64
    elif attack == "unsorted_names":
        payload["reconstruction_only_parameter_names"] = [
            "signal_sign",
            "legacy_profile",
        ]
    elif attack == "duplicate_names":
        payload["reconstruction_only_parameter_names"] = [
            "legacy_profile",
            "legacy_profile",
        ]
    else:
        payload["reconstruction_only_parameter_names"] = [
            "member_specific"
        ]

    with pytest.raises(HistoricalFamilyBindingError, match=message):
        historical_family_authority_from_payload(payload)


def test_authority_identity_binds_reconstruction_only_declarations() -> None:
    profile = _authority(("legacy_profile",))
    signal = _authority(("signal_sign",))
    none = _authority(())

    assert len({profile.identity, signal.identity, none.identity}) == 3
    assert (
        profile.family.identity
        == signal.family.identity
        == none.family.identity
    )
    assert profile.to_identity_payload()[
        "reconstruction_only_parameter_names"
    ] == ["legacy_profile"]
    assert signal.to_identity_payload()[
        "reconstruction_only_parameter_names"
    ] == ["signal_sign"]
