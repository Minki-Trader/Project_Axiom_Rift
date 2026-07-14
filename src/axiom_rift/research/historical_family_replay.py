"""Declarative historical concurrent-family bindings for prospective replay.

The catalog records immutable historical membership and exact subject controls.
It does not create a prospective Executable, choose a runner, read evidence, or
mutate canonical state.  Each member carries exactly one historical Executable
identity; prospective code must bind that identity through its separately typed
Executable parameter boundary.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
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

STU0048_HISTORICAL_FAMILY = HistoricalFamilySpec(
    original_study_id="STU-0048",
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

STU0051_HISTORICAL_FAMILY = HistoricalFamilySpec(
    original_study_id="STU-0051",
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

STU0032_HISTORICAL_FAMILY = HistoricalFamilySpec(
    original_study_id="STU-0032",
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


P1_HISTORICAL_FAMILY_CATALOG = historical_family_catalog(
    (
        STU0048_HISTORICAL_FAMILY,
        STU0051_HISTORICAL_FAMILY,
        STU0032_HISTORICAL_FAMILY,
    )
)
P1_HISTORICAL_FAMILY_CATALOG_DIGEST = historical_family_catalog_digest(
    P1_HISTORICAL_FAMILY_CATALOG
)


__all__ = [
    "CONTROL_BINDING_SCHEMA",
    "ControlBinding",
    "HISTORICAL_FAMILY_CATALOG_SCHEMA",
    "HISTORICAL_FAMILY_SCHEMA",
    "HISTORICAL_MEMBER_SCHEMA",
    "HistoricalFamilyReplayError",
    "HistoricalFamilySpec",
    "HistoricalMemberSpec",
    "P1_HISTORICAL_FAMILY_CATALOG",
    "P1_HISTORICAL_FAMILY_CATALOG_DIGEST",
    "STU0032_HISTORICAL_FAMILY",
    "STU0048_HISTORICAL_FAMILY",
    "STU0051_HISTORICAL_FAMILY",
    "historical_family_catalog",
    "historical_family_catalog_digest",
    "historical_family_catalog_manifest",
]
