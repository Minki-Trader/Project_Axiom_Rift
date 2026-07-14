"""Declarative historical concurrent-family bindings for prospective replay.

The catalog records immutable historical membership and exact subject controls.
It does not create a prospective Executable, choose a runner, read evidence, or
mutate canonical state.  Each member carries exactly one historical Executable
identity; prospective code must bind that identity through its separately typed
Executable parameter boundary.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from functools import partial
from importlib import import_module
from typing import Any

from axiom_rift.core.canonical import (
    CanonicalJSONError,
    CanonicalValue,
    canonical_bytes,
    parse_canonical,
)
from axiom_rift.core.identity import canonical_digest


HISTORICAL_MEMBER_SCHEMA = "historical_family_member.v1"
CONTROL_BINDING_SCHEMA = "historical_family_control_binding.v1"
HISTORICAL_FAMILY_SCHEMA = "historical_family_spec.v1"
HISTORICAL_FAMILY_CATALOG_SCHEMA = "historical_family_replay_catalog.v1"


class HistoricalFamilyReplayError(ValueError):
    """A historical family declaration is ambiguous or noncanonical."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise HistoricalFamilyReplayError(f"{name} must be non-empty ASCII")
    return value


def _sha256_identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    expected_prefix = f"{prefix}:"
    digest = text.removeprefix(expected_prefix)
    if (
        text == digest
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise HistoricalFamilyReplayError(
            f"{name} must use {prefix}:<lowercase-sha256>"
        )
    return text


def _study_id(value: object) -> str:
    text = _ascii("original_study_id", value)
    suffix = text.removeprefix("STU-")
    if text == suffix or len(suffix) != 4 or not suffix.isdigit():
        raise HistoricalFamilyReplayError(
            "original_study_id must use STU-<four-digits>"
        )
    return text


def _validate_parameter_strings(value: object, *, path: str) -> None:
    if type(value) is str:
        _ascii(path, value)
        if value.startswith("executable:"):
            raise HistoricalFamilyReplayError(
                "member parameters cannot embed another Executable identity"
            )
        return
    if type(value) is dict:
        for key, item in value.items():
            _ascii(f"{path} key", key)
            if key == "historical_reference_executable_id":
                raise HistoricalFamilyReplayError(
                    "member historical reference has one authoritative field"
                )
            _validate_parameter_strings(item, path=f"{path}.{key}")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _validate_parameter_strings(item, path=f"{path}[{index}]")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalMemberSpec:
    """One original family member with one exact historical identity."""

    ordinal: int
    configuration_id: str
    historical_reference_executable_id: str
    parameters: InitVar[object]
    _parameter_bytes: bytes = field(init=False, repr=False)

    def __post_init__(self, parameters: object) -> None:
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise HistoricalFamilyReplayError(
                "historical member ordinal must be a positive integer"
            )
        _ascii("configuration_id", self.configuration_id)
        _sha256_identity(
            "historical_reference_executable_id",
            self.historical_reference_executable_id,
            "executable",
        )
        if type(parameters) is not dict or not parameters:
            raise HistoricalFamilyReplayError(
                "historical member parameters must be a non-empty object"
            )
        _validate_parameter_strings(parameters, path="parameters")
        try:
            parameter_bytes = canonical_bytes(parameters)
        except CanonicalJSONError as exc:
            raise HistoricalFamilyReplayError(
                "historical member parameters are not canonical"
            ) from exc
        object.__setattr__(self, "_parameter_bytes", parameter_bytes)

    def parameter_values(self) -> dict[str, CanonicalValue]:
        """Return a detached copy of the frozen historical parameters."""

        value = parse_canonical(self._parameter_bytes)
        if not isinstance(value, dict):
            raise RuntimeError("historical member parameters lost object shape")
        return value

    def manifest(self) -> dict[str, object]:
        return {
            "configuration_id": self.configuration_id,
            "historical_reference_executable_id": (
                self.historical_reference_executable_id
            ),
            "ordinal": self.ordinal,
            "parameters": self.parameter_values(),
            "schema": HISTORICAL_MEMBER_SCHEMA,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ControlBinding:
    """Exact opposite and feature controls for one historical subject."""

    subject_historical_executable_id: str
    opposite_historical_executable_id: str
    feature_historical_executable_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        subject = _sha256_identity(
            "subject_historical_executable_id",
            self.subject_historical_executable_id,
            "executable",
        )
        opposite = _sha256_identity(
            "opposite_historical_executable_id",
            self.opposite_historical_executable_id,
            "executable",
        )
        if type(self.feature_historical_executable_ids) is not tuple:
            raise HistoricalFamilyReplayError(
                "feature_historical_executable_ids must be a tuple"
            )
        features = tuple(
            _sha256_identity(
                f"feature_historical_executable_ids[{index}]",
                value,
                "executable",
            )
            for index, value in enumerate(
                self.feature_historical_executable_ids
            )
        )
        if not features:
            raise HistoricalFamilyReplayError(
                "a control binding requires at least one feature control"
            )
        if len(features) != len(set(features)):
            raise HistoricalFamilyReplayError(
                "feature historical controls must be unique"
            )
        features = tuple(sorted(features))
        if subject == opposite or subject in features or opposite in features:
            raise HistoricalFamilyReplayError(
                "subject, opposite, and feature controls must be distinct"
            )
        object.__setattr__(self, "feature_historical_executable_ids", features)

    def manifest(self) -> dict[str, object]:
        return {
            "feature_historical_executable_ids": list(
                self.feature_historical_executable_ids
            ),
            "opposite_historical_executable_id": (
                self.opposite_historical_executable_id
            ),
            "schema": CONTROL_BINDING_SCHEMA,
            "subject_historical_executable_id": (
                self.subject_historical_executable_id
            ),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalFamilySpec:
    """One exact original Batch family and all member-bound controls."""

    original_study_id: str
    original_batch_id: str
    target_historical_executable_id: str
    members: tuple[HistoricalMemberSpec, ...]
    controls: tuple[ControlBinding, ...]
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _study_id(self.original_study_id)
        _sha256_identity("original_batch_id", self.original_batch_id, "batch")
        target = _sha256_identity(
            "target_historical_executable_id",
            self.target_historical_executable_id,
            "executable",
        )
        if (
            type(self.members) is not tuple
            or not self.members
            or any(
                not isinstance(member, HistoricalMemberSpec)
                for member in self.members
            )
        ):
            raise HistoricalFamilyReplayError(
                "historical family members must be a non-empty typed tuple"
            )
        members = tuple(sorted(self.members, key=lambda item: item.ordinal))
        ordinals = tuple(member.ordinal for member in members)
        if ordinals != tuple(range(1, len(members) + 1)):
            raise HistoricalFamilyReplayError(
                "historical family ordinals must be unique and contiguous"
            )
        configurations = tuple(member.configuration_id for member in members)
        references = tuple(
            member.historical_reference_executable_id for member in members
        )
        if len(configurations) != len(set(configurations)):
            raise HistoricalFamilyReplayError(
                "historical family configuration ids must be unique"
            )
        if len(references) != len(set(references)):
            raise HistoricalFamilyReplayError(
                "each historical Executable id must identify exactly one member"
            )
        if references.count(target) != 1:
            raise HistoricalFamilyReplayError(
                "historical family target must identify exactly one member"
            )
        if (
            type(self.controls) is not tuple
            or not self.controls
            or any(
                not isinstance(control, ControlBinding)
                for control in self.controls
            )
        ):
            raise HistoricalFamilyReplayError(
                "historical family controls must be a non-empty typed tuple"
            )
        controls = tuple(
            sorted(
                self.controls,
                key=lambda item: item.subject_historical_executable_id,
            )
        )
        subjects = tuple(
            control.subject_historical_executable_id for control in controls
        )
        if subjects != tuple(sorted(references)):
            raise HistoricalFamilyReplayError(
                "historical family requires one exact control binding per member"
            )
        reference_set = set(references)
        control_by_subject = {
            control.subject_historical_executable_id: control
            for control in controls
        }
        if len(control_by_subject) != len(controls):
            raise HistoricalFamilyReplayError(
                "historical family control subjects must be unique"
            )
        for control in controls:
            control_references = {
                control.opposite_historical_executable_id,
                *control.feature_historical_executable_ids,
            }
            if not control_references.issubset(reference_set):
                raise HistoricalFamilyReplayError(
                    "historical controls must reference exact family members"
                )
            reverse = control_by_subject.get(
                control.opposite_historical_executable_id
            )
            if (
                reverse is None
                or reverse.opposite_historical_executable_id
                != control.subject_historical_executable_id
            ):
                raise HistoricalFamilyReplayError(
                    "historical opposite controls must be reciprocal"
                )
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "controls", controls)
        identity = canonical_digest(
            domain="historical-family-spec", payload=self.manifest()
        )
        object.__setattr__(self, "identity", f"historical-family:{identity}")

    @property
    def family_size(self) -> int:
        return len(self.members)

    def member_for_historical_executable(
        self, historical_executable_id: str
    ) -> HistoricalMemberSpec:
        reference = _sha256_identity(
            "historical_executable_id",
            historical_executable_id,
            "executable",
        )
        matches = tuple(
            member
            for member in self.members
            if member.historical_reference_executable_id == reference
        )
        if len(matches) != 1:
            raise HistoricalFamilyReplayError(
                "historical Executable is not one exact family member"
            )
        return matches[0]

    def control_for_historical_executable(
        self, historical_executable_id: str
    ) -> ControlBinding:
        member = self.member_for_historical_executable(
            historical_executable_id
        )
        matches = tuple(
            control
            for control in self.controls
            if control.subject_historical_executable_id
            == member.historical_reference_executable_id
        )
        if len(matches) != 1:
            raise RuntimeError("validated family lost its exact control binding")
        return matches[0]

    def manifest(self) -> dict[str, object]:
        return {
            "controls": [control.manifest() for control in self.controls],
            "members": [member.manifest() for member in self.members],
            "original_batch_id": self.original_batch_id,
            "original_study_id": self.original_study_id,
            "schema": HISTORICAL_FAMILY_SCHEMA,
            "target_historical_executable_id": (
                self.target_historical_executable_id
            ),
        }


def historical_family_catalog(
    families: tuple[HistoricalFamilySpec, ...],
) -> tuple[HistoricalFamilySpec, ...]:
    """Return a canonical catalog after rejecting cross-family ambiguity."""

    if (
        type(families) is not tuple
        or not families
        or any(not isinstance(family, HistoricalFamilySpec) for family in families)
    ):
        raise HistoricalFamilyReplayError(
            "historical family catalog must be a non-empty typed tuple"
        )
    normalized = tuple(
        sorted(
            families,
            key=lambda item: (
                item.original_study_id,
                item.original_batch_id,
                item.identity,
            ),
        )
    )
    for name, values in (
        (
            "original Study ids",
            tuple(family.original_study_id for family in normalized),
        ),
        (
            "original Batch ids",
            tuple(family.original_batch_id for family in normalized),
        ),
        (
            "family identities",
            tuple(family.identity for family in normalized),
        ),
    ):
        if len(values) != len(set(values)):
            raise HistoricalFamilyReplayError(
                f"historical family catalog {name} must be unique"
            )
    references = tuple(
        member.historical_reference_executable_id
        for family in normalized
        for member in family.members
    )
    if len(references) != len(set(references)):
        raise HistoricalFamilyReplayError(
            "one historical Executable id cannot belong to multiple families"
        )
    return normalized


def historical_family_catalog_manifest(
    families: tuple[HistoricalFamilySpec, ...],
) -> dict[str, object]:
    normalized = historical_family_catalog(families)
    return {
        "families": [family.manifest() for family in normalized],
        "schema": HISTORICAL_FAMILY_CATALOG_SCHEMA,
    }


def historical_family_catalog_digest(
    families: tuple[HistoricalFamilySpec, ...],
) -> str:
    return canonical_digest(
        domain="historical-family-replay-catalog",
        payload=historical_family_catalog_manifest(families),
    )


def _member(
    ordinal: int,
    configuration_id: str,
    historical_reference_executable_id: str,
    **parameters: Any,
) -> HistoricalMemberSpec:
    return HistoricalMemberSpec(
        ordinal=ordinal,
        configuration_id=configuration_id,
        historical_reference_executable_id=(
            historical_reference_executable_id
        ),
        parameters=parameters,
    )


def _control(
    subject: str,
    opposite: str,
    *features: str,
) -> ControlBinding:
    return ControlBinding(
        subject_historical_executable_id=subject,
        opposite_historical_executable_id=opposite,
        feature_historical_executable_ids=tuple(features),
    )


_STU0048_IDS = {
    "depth_positive": (
        "executable:672b5ce2ab8bd5419b49b9b09db271f8d51ba2c1fb14057112ce180306f226ed"
    ),
    "depth_negative": (
        "executable:4b203b0f0eb4e1e12b59f2baafe7e83202b866bc90f0034ad48cf0989bcaa09c"
    ),
    "duration_positive": (
        "executable:4c6b58e03685bcca2037eb0f4731305d94423b00b7adb5ab54f99e147e645ab5"
    ),
    "duration_negative": (
        "executable:032ba71324366292953787e1fa79378274dcb99d9d8dcfe2825738969a6ebf2b"
    ),
}

_build_stu0048_historical_family = partial(
    HistoricalFamilySpec,
    original_batch_id=(
        "batch:ed48b5be86d9c772bcdd1dda59472376386077898f2e23d004a1d7ee90fdbd4b"
    ),
    target_historical_executable_id=_STU0048_IDS["duration_negative"],
    members=(
        _member(
            1,
            "drawdown_depth_288-deterioration-h24",
            _STU0048_IDS["depth_positive"],
            holding_bars=24,
            lookback_bars=288,
            profile="drawdown_depth_288",
            selector_quantile_bp=7_000,
            signal_sign=1,
            unknown_entry_action="cancel_before_open",
        ),
        _member(
            2,
            "drawdown_depth_288-recovery-h24",
            _STU0048_IDS["depth_negative"],
            holding_bars=24,
            lookback_bars=288,
            profile="drawdown_depth_288",
            selector_quantile_bp=7_000,
            signal_sign=-1,
            unknown_entry_action="cancel_before_open",
        ),
        _member(
            3,
            "drawdown_duration_288-deterioration-h24",
            _STU0048_IDS["duration_positive"],
            holding_bars=24,
            lookback_bars=288,
            profile="drawdown_duration_288",
            selector_quantile_bp=7_000,
            signal_sign=1,
            unknown_entry_action="cancel_before_open",
        ),
        _member(
            4,
            "drawdown_duration_288-recovery-h24",
            _STU0048_IDS["duration_negative"],
            holding_bars=24,
            lookback_bars=288,
            profile="drawdown_duration_288",
            selector_quantile_bp=7_000,
            signal_sign=-1,
            unknown_entry_action="cancel_before_open",
        ),
    ),
    controls=(
        _control(
            _STU0048_IDS["depth_positive"],
            _STU0048_IDS["depth_negative"],
            _STU0048_IDS["duration_positive"],
        ),
        _control(
            _STU0048_IDS["depth_negative"],
            _STU0048_IDS["depth_positive"],
            _STU0048_IDS["duration_negative"],
        ),
        _control(
            _STU0048_IDS["duration_positive"],
            _STU0048_IDS["duration_negative"],
            _STU0048_IDS["depth_positive"],
        ),
        _control(
            _STU0048_IDS["duration_negative"],
            _STU0048_IDS["duration_positive"],
            _STU0048_IDS["depth_negative"],
        ),
    ),
)


_STU0051_IDS = {
    "mature_positive": (
        "executable:d07169b4d76bc6a449951b3e2c9fc178f2c52029b80fcaedad200d497848b6f9"
    ),
    "mature_negative": (
        "executable:ff53b8828db4e61c1fbdfaccf84d7d8b3493c2e796e19cd1fddf50bb23e94137"
    ),
    "persistent_positive": (
        "executable:05a4320996e315a57eea1c37c542c1d87b23b003a86167526544ea50e7f27bf2"
    ),
    "persistent_negative": (
        "executable:43bce7d49399848c5fe2a7de0351417a8832b6a004105fafed538743fa2977a9"
    ),
}

_build_stu0051_historical_family = partial(
    HistoricalFamilySpec,
    original_batch_id=(
        "batch:0898237a60c32ed2a3d66d3160a49c041bd2afcd683d48943a14fd8b06e38b7c"
    ),
    target_historical_executable_id=_STU0051_IDS["persistent_negative"],
    members=tuple(
        _member(
            ordinal,
            configuration_id,
            historical_id,
            holding_bars=24,
            profile=profile,
            signal_sign=signal_sign,
            state_window=1_152,
            unknown_entry_action="cancel_before_open",
            volatility_window=96,
        )
        for ordinal, configuration_id, historical_id, profile, signal_sign in (
            (
                1,
                "mature_state_age_24_47-follow-h24",
                _STU0051_IDS["mature_positive"],
                "mature_state_age_24_47",
                1,
            ),
            (
                2,
                "mature_state_age_24_47-reverse-h24",
                _STU0051_IDS["mature_negative"],
                "mature_state_age_24_47",
                -1,
            ),
            (
                3,
                "persistent_state_age_72_143-follow-h24",
                _STU0051_IDS["persistent_positive"],
                "persistent_state_age_72_143",
                1,
            ),
            (
                4,
                "persistent_state_age_72_143-reverse-h24",
                _STU0051_IDS["persistent_negative"],
                "persistent_state_age_72_143",
                -1,
            ),
        )
    ),
    controls=(
        _control(
            _STU0051_IDS["mature_positive"],
            _STU0051_IDS["mature_negative"],
            _STU0051_IDS["persistent_positive"],
        ),
        _control(
            _STU0051_IDS["mature_negative"],
            _STU0051_IDS["mature_positive"],
            _STU0051_IDS["persistent_negative"],
        ),
        _control(
            _STU0051_IDS["persistent_positive"],
            _STU0051_IDS["persistent_negative"],
            _STU0051_IDS["mature_positive"],
        ),
        _control(
            _STU0051_IDS["persistent_negative"],
            _STU0051_IDS["persistent_positive"],
            _STU0051_IDS["mature_negative"],
        ),
    ),
)


_STU0032_IDS = {
    "skew96_h48_positive": (
        "executable:e991bf872002ab5f1deedf4db23c781baf8f4b06716c58be5099eb9d1edaa7d6"
    ),
    "skew96_h96_positive": (
        "executable:f0a4c5ea6caaa4f2e846f5ccb8490e934a53f21ae6e79739fd657c8e78f6f022"
    ),
    "skew96_h48_negative": (
        "executable:6f93cbb23dcd028140b4a7a7600e57cfdb4681dfeaf396c0637bd45dc432a9a6"
    ),
    "skew96_h96_negative": (
        "executable:207c5f73e29da57e73fc5206f81e0cad483d75ae98b0941f660a7ef713bad09c"
    ),
    "skew192_h48_positive": (
        "executable:5dfdc8a11640486d2cc76a9746ba9615483f233b4b73ca752be7c21a2cddf89f"
    ),
    "skew192_h96_positive": (
        "executable:65ab38fd6106defab802d43355fb3cb3ac583c1425f84472abf52d4dd591813b"
    ),
    "skew192_h48_negative": (
        "executable:3894de4c501e35730c300fabc3c01593e8c7664bf7d39bf07fd7b34cde0c8b43"
    ),
    "skew192_h96_negative": (
        "executable:3c35c426ca91dcd11de6fc9e1a74ef8f4678a6ead26d8c91c9dc32fc8beb5f9a"
    ),
    "semivariance_h48_positive": (
        "executable:0f44088c1f7faf80714071e42b069e01d623423dc223a5a59f4cdf42a56df669"
    ),
    "semivariance_h96_positive": (
        "executable:5b8a1956bb784b766619bc27ae8ae2ca88c25d226f4be5a670109e920fd1f194"
    ),
    "semivariance_h48_negative": (
        "executable:cd4e24801f6cee921f7f95d7b986f35cf435f71ec613e05e273a7b73184eb663"
    ),
    "semivariance_h96_negative": (
        "executable:b9d233ce2f311e4979d66c9b8534440c8323252b1c6896f00487e8ffd8336a12"
    ),
}

_STU0032_ROWS = (
    (1, "skew_96-aligned-h48", "skew96_h48_positive", "skew_96", 48, 1),
    (2, "skew_96-aligned-h96", "skew96_h96_positive", "skew_96", 96, 1),
    (3, "skew_96-inverse-h48", "skew96_h48_negative", "skew_96", 48, -1),
    (4, "skew_96-inverse-h96", "skew96_h96_negative", "skew_96", 96, -1),
    (5, "skew_192-aligned-h48", "skew192_h48_positive", "skew_192", 48, 1),
    (6, "skew_192-aligned-h96", "skew192_h96_positive", "skew_192", 96, 1),
    (7, "skew_192-inverse-h48", "skew192_h48_negative", "skew_192", 48, -1),
    (8, "skew_192-inverse-h96", "skew192_h96_negative", "skew_192", 96, -1),
    (
        9,
        "semivariance_96-aligned-h48",
        "semivariance_h48_positive",
        "semivariance_96",
        48,
        1,
    ),
    (
        10,
        "semivariance_96-aligned-h96",
        "semivariance_h96_positive",
        "semivariance_96",
        96,
        1,
    ),
    (
        11,
        "semivariance_96-inverse-h48",
        "semivariance_h48_negative",
        "semivariance_96",
        48,
        -1,
    ),
    (
        12,
        "semivariance_96-inverse-h96",
        "semivariance_h96_negative",
        "semivariance_96",
        96,
        -1,
    ),
)

_STU0032_CONTROL_KEYS = {
    "skew96_h48_positive": (
        "skew96_h48_negative",
        ("semivariance_h48_positive", "skew192_h48_positive"),
    ),
    "skew96_h96_positive": (
        "skew96_h96_negative",
        ("semivariance_h96_positive", "skew192_h96_positive"),
    ),
    "skew96_h48_negative": (
        "skew96_h48_positive",
        ("semivariance_h48_negative", "skew192_h48_negative"),
    ),
    "skew96_h96_negative": (
        "skew96_h96_positive",
        ("semivariance_h96_negative", "skew192_h96_negative"),
    ),
    "skew192_h48_positive": (
        "skew192_h48_negative",
        ("semivariance_h48_positive", "skew96_h48_positive"),
    ),
    "skew192_h96_positive": (
        "skew192_h96_negative",
        ("semivariance_h96_positive", "skew96_h96_positive"),
    ),
    "skew192_h48_negative": (
        "skew192_h48_positive",
        ("semivariance_h48_negative", "skew96_h48_negative"),
    ),
    "skew192_h96_negative": (
        "skew192_h96_positive",
        ("semivariance_h96_negative", "skew96_h96_negative"),
    ),
    "semivariance_h48_positive": (
        "semivariance_h48_negative",
        ("skew192_h48_positive", "skew96_h48_positive"),
    ),
    "semivariance_h96_positive": (
        "semivariance_h96_negative",
        ("skew192_h96_positive", "skew96_h96_positive"),
    ),
    "semivariance_h48_negative": (
        "semivariance_h48_positive",
        ("skew192_h48_negative", "skew96_h48_negative"),
    ),
    "semivariance_h96_negative": (
        "semivariance_h96_positive",
        ("skew192_h96_negative", "skew96_h96_negative"),
    ),
}

_build_stu0032_historical_family = partial(
    HistoricalFamilySpec,
    original_batch_id=(
        "batch:43b527cd0392c0b0c142a160636d58ff4d72baa4adb3661a1ed6902d6414cb9a"
    ),
    target_historical_executable_id=_STU0032_IDS[
        "semivariance_h96_negative"
    ],
    members=tuple(
        _member(
            ordinal,
            configuration_id,
            _STU0032_IDS[key],
            holding_bars=holding_bars,
            profile=profile,
            selector_quantile_bp=9_000,
            signal_sign=signal_sign,
        )
        for ordinal, configuration_id, key, profile, holding_bars, signal_sign
        in _STU0032_ROWS
    ),
    controls=tuple(
        _control(
            _STU0032_IDS[subject_key],
            _STU0032_IDS[opposite_key],
            *(_STU0032_IDS[key] for key in feature_keys),
        )
        for subject_key, (opposite_key, feature_keys) in (
            _STU0032_CONTROL_KEYS.items()
        )
    ),
)


def _three_profile_controls(
    identities: dict[tuple[str, int, int], str],
) -> tuple[ControlBinding, ...]:
    """Build exact sign and profile controls for a 3 x 2 x 2 family."""

    profiles = tuple(sorted({key[0] for key in identities}))
    signs = tuple(sorted({key[1] for key in identities}))
    horizons = tuple(sorted({key[2] for key in identities}))
    if (
        len(profiles) != 3
        or signs != (-1, 1)
        or len(horizons) != 2
        or set(identities)
        != {
            (profile, sign, horizon)
            for profile in profiles
            for sign in signs
            for horizon in horizons
        }
    ):
        raise HistoricalFamilyReplayError(
            "routed family must be one complete 3 x 2 x 2 surface"
        )
    return tuple(
        _control(
            identities[(profile, sign, horizon)],
            identities[(profile, -sign, horizon)],
            *(
                identities[(feature_profile, sign, horizon)]
                for feature_profile in profiles
                if feature_profile != profile
            ),
        )
        for profile in profiles
        for sign in signs
        for horizon in horizons
    )


_STU0016_IDS = {
    ("three_sleeve_router", -1, 12): (
        "executable:fc759b3224803f7fcb02c3ff462952d9d5757f055332d03d5e523b750083bfa2"
    ),
    ("three_sleeve_router", -1, 48): (
        "executable:e2fbd634f77f528e2602869a9185ca9be0839e5043f93fad3168e5234156e26a"
    ),
    ("three_sleeve_router", 1, 12): (
        "executable:b36e424e2e39a835eb0025c9e5401dc3b9ea89d9218e62c47b3256331eb4e678"
    ),
    ("three_sleeve_router", 1, 48): (
        "executable:87a549ee3c11ecfa276f03903e3bf46c63c1cb1f1b3f584841cc2005d67ffa1b"
    ),
    ("volume_reversion_ablation", -1, 12): (
        "executable:3aa139c4dbf40f0249084e62d241280597f370e7e121b4ddac6cda83ffc4ad68"
    ),
    ("volume_reversion_ablation", -1, 48): (
        "executable:bfd622b40f2326258781ea4fff27b7c6b08d5947eb7876d1cea49b64f00334bc"
    ),
    ("volume_reversion_ablation", 1, 12): (
        "executable:f78844b7335bc4463a37645ea4948a164c8cfa74607e274d6d816320354d5ecd"
    ),
    ("volume_reversion_ablation", 1, 48): (
        "executable:a1cf161817284545c00a7636c30481fa21568d7f0b7a8921d73dff0dbbb84c38"
    ),
    ("volume_volatility_ablation", -1, 12): (
        "executable:06ad8508a168bfbf0216e715a01ccffa7e27dfd2cd8fb650431444b70431f975"
    ),
    ("volume_volatility_ablation", -1, 48): (
        "executable:e1ae93800933f1739becd5e67512c20181948941d0b0bac491f40c206ca56f73"
    ),
    ("volume_volatility_ablation", 1, 12): (
        "executable:43d19780f661ee5d05271fec7193f844f9646673eb75f0ae80ecfe5787404b93"
    ),
    ("volume_volatility_ablation", 1, 48): (
        "executable:8de305e766e7048b4291c13c6e442f7b53c30b3659f09d343db504134f9ab5b4"
    ),
}

_STU0016_ROWS = tuple(
    (
        ordinal,
        f"{profile}-{'inverted' if sign == -1 else 'routed'}-h{horizon}",
        profile,
        sign,
        horizon,
    )
    for ordinal, (profile, sign, horizon) in enumerate(
        (
            (profile, sign, horizon)
            for profile in (
                "three_sleeve_router",
                "volume_reversion_ablation",
                "volume_volatility_ablation",
            )
            for sign in (-1, 1)
            for horizon in (12, 48)
        ),
        start=1,
    )
)

_build_stu0016_historical_family = partial(
    HistoricalFamilySpec,
    original_batch_id=(
        "batch:c8c8f757ccfc444360a260aeb905b4254f2a0241ae2ff1e09663eb354bf2f937"
    ),
    target_historical_executable_id=_STU0016_IDS[
        ("volume_volatility_ablation", 1, 48)
    ],
    members=tuple(
        _member(
            ordinal,
            configuration_id,
            _STU0016_IDS[(profile, sign, horizon)],
            holding_bars=horizon,
            profile=profile,
            selector_quantile_bp=9_500,
            signal_sign=sign,
        )
        for ordinal, configuration_id, profile, sign, horizon in _STU0016_ROWS
    ),
    controls=_three_profile_controls(_STU0016_IDS),
)


_STU0017_IDS = {
    ("full_regime_consensus", -1, 24): (
        "executable:6756cf4b4afc9b5e7825eb98ce637ab4b3996e469bf65f93e2cbedcadbdde4ce"
    ),
    ("full_regime_consensus", -1, 48): (
        "executable:1d08147400a254e7f9a54425882fffac16e53cdeeb6267cf411543f9591aa27d"
    ),
    ("full_regime_consensus", 1, 24): (
        "executable:d44b2c56cb72f609e372ade48042bc17d0775bd986759fb0635c9cc597d5d612"
    ),
    ("full_regime_consensus", 1, 48): (
        "executable:f97438d20e3be08799887750daf3b6191619ddf874008083be70fc9a320dbf50"
    ),
    ("volume_primary_all_regimes", -1, 24): (
        "executable:2d9dd7f2165a0157b53bdeaa80265e93fa2f9c16d055f44a75980deba0ea94f9"
    ),
    ("volume_primary_all_regimes", -1, 48): (
        "executable:01084b49554bfe7b81c09a6754919afcd6a9c4ea82e577fcb489249e1a9d983a"
    ),
    ("volume_primary_all_regimes", 1, 24): (
        "executable:de25016fc3c3356c268d281929c50f65774e1f3832ce49daf313d52de1b1e702"
    ),
    ("volume_primary_all_regimes", 1, 48): (
        "executable:563de482fc6f5fc5967a51f4c0338a505901139024736ad00e3c2cb7e6161d99"
    ),
    ("middle_consensus_no_high", -1, 24): (
        "executable:b77b5415e62a6eb58aaff05817a4c0263cb76b473c049976e628e39fe9636e9c"
    ),
    ("middle_consensus_no_high", -1, 48): (
        "executable:415313ffe158c34da4c6a423289c142864d7d5a455e6d1b79b63328d94dc5849"
    ),
    ("middle_consensus_no_high", 1, 24): (
        "executable:ed9db729ee68e448bfa82c50000bda7647bf0c247a1e08f6b2374b76c2a46740"
    ),
    ("middle_consensus_no_high", 1, 48): (
        "executable:7d3a9f18039fd851454d9a8171a2f4c547de14fc464e86f6bafbf3d84e64526a"
    ),
}

_STU0017_ROWS = tuple(
    (
        ordinal,
        f"{profile}-{'inverted' if sign == -1 else 'routed'}-h{horizon}",
        profile,
        sign,
        horizon,
    )
    for ordinal, (profile, sign, horizon) in enumerate(
        (
            (profile, sign, horizon)
            for profile in (
                "full_regime_consensus",
                "volume_primary_all_regimes",
                "middle_consensus_no_high",
            )
            for sign in (-1, 1)
            for horizon in (24, 48)
        ),
        start=1,
    )
)

_build_stu0017_historical_family = partial(
    HistoricalFamilySpec,
    original_batch_id=(
        "batch:7dbabdea68fffba4789a5dd92509610a652a84be95e6ed45fa49f659f37e928e"
    ),
    target_historical_executable_id=_STU0017_IDS[
        ("middle_consensus_no_high", 1, 48)
    ],
    members=tuple(
        _member(
            ordinal,
            configuration_id,
            _STU0017_IDS[(profile, sign, horizon)],
            holding_bars=horizon,
            profile=profile,
            selector_quantile_bp=9_750,
            signal_sign=sign,
        )
        for ordinal, configuration_id, profile, sign, horizon in _STU0017_ROWS
    ),
    controls=_three_profile_controls(_STU0017_IDS),
)


_LAZY_EXPORTS = {
    "ALL_P1_HISTORICAL_FAMILY_CATALOG": (
        "axiom_rift.research.historical_family_catalogs",
        "ALL_P1_HISTORICAL_FAMILY_CATALOG",
    ),
    "ALL_P1_HISTORICAL_FAMILY_CATALOG_DIGEST": (
        "axiom_rift.research.historical_family_catalogs",
        "ALL_P1_HISTORICAL_FAMILY_CATALOG_DIGEST",
    ),
    "P1_HISTORICAL_FAMILY_CATALOG": (
        "axiom_rift.research.historical_family_catalogs",
        "P1_HISTORICAL_FAMILY_CATALOG",
    ),
    "P1_HISTORICAL_FAMILY_CATALOG_DIGEST": (
        "axiom_rift.research.historical_family_catalogs",
        "P1_HISTORICAL_FAMILY_CATALOG_DIGEST",
    ),
    "P1_ROUTED_HISTORICAL_FAMILY_CATALOG": (
        "axiom_rift.research.historical_family_catalogs",
        "P1_ROUTED_HISTORICAL_FAMILY_CATALOG",
    ),
    "P1_ROUTED_HISTORICAL_FAMILY_CATALOG_DIGEST": (
        "axiom_rift.research.historical_family_catalogs",
        "P1_ROUTED_HISTORICAL_FAMILY_CATALOG_DIGEST",
    ),
    "STU0016_HISTORICAL_FAMILY": (
        "axiom_rift.research.historical_family_stu0016",
        "STU0016_HISTORICAL_FAMILY",
    ),
    "STU0017_HISTORICAL_FAMILY": (
        "axiom_rift.research.historical_family_stu0017",
        "STU0017_HISTORICAL_FAMILY",
    ),
    "STU0032_HISTORICAL_FAMILY": (
        "axiom_rift.research.historical_family_stu0032",
        "STU0032_HISTORICAL_FAMILY",
    ),
    "STU0048_HISTORICAL_FAMILY": (
        "axiom_rift.research.historical_family_stu0048",
        "STU0048_HISTORICAL_FAMILY",
    ),
    "STU0051_HISTORICAL_FAMILY": (
        "axiom_rift.research.historical_family_stu0051",
        "STU0051_HISTORICAL_FAMILY",
    ),
}


def __getattr__(name: str) -> object:
    """Load one exact authority binding or the explicit navigation catalog."""

    route = _LAZY_EXPORTS.get(name)
    if route is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = route
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_LAZY_EXPORTS})


__all__ = [
    "CONTROL_BINDING_SCHEMA",
    "ControlBinding",
    "HISTORICAL_FAMILY_CATALOG_SCHEMA",
    "HISTORICAL_FAMILY_SCHEMA",
    "HISTORICAL_MEMBER_SCHEMA",
    "HistoricalFamilyReplayError",
    "HistoricalFamilySpec",
    "HistoricalMemberSpec",
    "ALL_P1_HISTORICAL_FAMILY_CATALOG",
    "ALL_P1_HISTORICAL_FAMILY_CATALOG_DIGEST",
    "P1_HISTORICAL_FAMILY_CATALOG",
    "P1_HISTORICAL_FAMILY_CATALOG_DIGEST",
    "P1_ROUTED_HISTORICAL_FAMILY_CATALOG",
    "P1_ROUTED_HISTORICAL_FAMILY_CATALOG_DIGEST",
    "STU0016_HISTORICAL_FAMILY",
    "STU0017_HISTORICAL_FAMILY",
    "STU0032_HISTORICAL_FAMILY",
    "STU0048_HISTORICAL_FAMILY",
    "STU0051_HISTORICAL_FAMILY",
    "historical_family_catalog",
    "historical_family_catalog_digest",
    "historical_family_catalog_manifest",
]
