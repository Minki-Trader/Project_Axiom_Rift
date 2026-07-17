"""Data-only historical family binding admitted by a running Job.

This module deliberately contains no historical Study, Batch, or Executable
identity.  Reconstruction code may materialize a manifest from historical
records, but prospective code can receive a family only by parsing the exact
manifest authenticated by its Study and replay obligation.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from typing import Any, Protocol, runtime_checkable

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
HISTORICAL_FAMILY_CORE_SCHEMA = "historical_family_core.v1"
HISTORICAL_FAMILY_AUTHORITY_SCHEMA = "historical_family_authority.v2"


class HistoricalFamilyBindingError(ValueError):
    """A Writer-bound historical family manifest is invalid or ambiguous."""


@runtime_checkable
class HistoricalFamilyLike(Protocol):
    """Read-only shape shared with frozen reconstruction family objects."""

    original_study_id: str
    original_batch_id: str
    target_historical_executable_id: str
    members: tuple[Any, ...]
    controls: tuple[Any, ...]
    identity: str

    @property
    def family_size(self) -> int: ...

    def manifest(self) -> dict[str, object]: ...


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise HistoricalFamilyBindingError(f"{name} must be non-empty ASCII")
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
        raise HistoricalFamilyBindingError(
            f"{name} must use {prefix}:<lowercase-sha256>"
        )
    return text


def _study_id(value: object) -> str:
    text = _ascii("original_study_id", value)
    suffix = text.removeprefix("STU-")
    if text == suffix or len(suffix) != 4 or not suffix.isdigit():
        raise HistoricalFamilyBindingError(
            "original_study_id must use STU-<four-digits>"
        )
    return text


def _validate_parameter_strings(value: object, *, path: str) -> None:
    if type(value) is str:
        _ascii(path, value)
        if value.startswith("executable:"):
            raise HistoricalFamilyBindingError(
                "member parameters cannot embed another Executable identity"
            )
        return
    if type(value) is dict:
        for key, item in value.items():
            _ascii(f"{path} key", key)
            if key == "historical_reference_executable_id":
                raise HistoricalFamilyBindingError(
                    "member historical reference has one authoritative field"
                )
            _validate_parameter_strings(item, path=f"{path}.{key}")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _validate_parameter_strings(item, path=f"{path}[{index}]")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalMemberSpec:
    """One exact historical family member detached from reconstruction code."""

    ordinal: int
    configuration_id: str
    historical_reference_executable_id: str
    parameters: InitVar[object]
    _parameter_bytes: bytes = field(init=False, repr=False)

    def __post_init__(self, parameters: object) -> None:
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise HistoricalFamilyBindingError(
                "historical member ordinal must be a positive integer"
            )
        _ascii("configuration_id", self.configuration_id)
        _sha256_identity(
            "historical_reference_executable_id",
            self.historical_reference_executable_id,
            "executable",
        )
        if type(parameters) is not dict or not parameters:
            raise HistoricalFamilyBindingError(
                "historical member parameters must be a non-empty object"
            )
        _validate_parameter_strings(parameters, path="parameters")
        try:
            parameter_bytes = canonical_bytes(parameters)
        except CanonicalJSONError as exc:
            raise HistoricalFamilyBindingError(
                "historical member parameters are not canonical"
            ) from exc
        object.__setattr__(self, "_parameter_bytes", parameter_bytes)

    def parameter_values(self) -> dict[str, CanonicalValue]:
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
            raise HistoricalFamilyBindingError(
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
            raise HistoricalFamilyBindingError(
                "a control binding requires at least one feature control"
            )
        if len(features) != len(set(features)):
            raise HistoricalFamilyBindingError(
                "feature historical controls must be unique"
            )
        features = tuple(sorted(features))
        if subject == opposite or subject in features or opposite in features:
            raise HistoricalFamilyBindingError(
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


def historical_family_core_identity(family: HistoricalFamilySpec) -> str:
    """Identify immutable family membership independently of one target."""

    if not isinstance(family, HistoricalFamilySpec):
        raise HistoricalFamilyBindingError(
            "historical family core requires a typed family"
        )
    return "historical-family-core:" + canonical_digest(
        domain="historical-family-core",
        payload={
            "controls": [
                control.manifest() for control in family.controls
            ],
            "members": [member.manifest() for member in family.members],
            "original_batch_id": family.original_batch_id,
            "original_study_id": family.original_study_id,
            "schema": HISTORICAL_FAMILY_CORE_SCHEMA,
        },
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalFamilySpec:
    """One validated data-only family supplied by authenticated state."""

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
            raise HistoricalFamilyBindingError(
                "historical family members must be a non-empty typed tuple"
            )
        members = tuple(sorted(self.members, key=lambda item: item.ordinal))
        ordinals = tuple(member.ordinal for member in members)
        if ordinals != tuple(range(1, len(members) + 1)):
            raise HistoricalFamilyBindingError(
                "historical family ordinals must be unique and contiguous"
            )
        configurations = tuple(member.configuration_id for member in members)
        references = tuple(
            member.historical_reference_executable_id for member in members
        )
        if len(configurations) != len(set(configurations)):
            raise HistoricalFamilyBindingError(
                "historical family configuration ids must be unique"
            )
        if len(references) != len(set(references)):
            raise HistoricalFamilyBindingError(
                "each historical Executable id must identify exactly one member"
            )
        if references.count(target) != 1:
            raise HistoricalFamilyBindingError(
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
            raise HistoricalFamilyBindingError(
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
            raise HistoricalFamilyBindingError(
                "historical family requires one exact control binding per member"
            )
        reference_set = set(references)
        control_by_subject = {
            control.subject_historical_executable_id: control
            for control in controls
        }
        if len(control_by_subject) != len(controls):
            raise HistoricalFamilyBindingError(
                "historical family control subjects must be unique"
            )
        for control in controls:
            control_references = {
                control.opposite_historical_executable_id,
                *control.feature_historical_executable_ids,
            }
            if not control_references.issubset(reference_set):
                raise HistoricalFamilyBindingError(
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
                raise HistoricalFamilyBindingError(
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
            raise HistoricalFamilyBindingError(
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


def historical_family_from_manifest(value: object) -> HistoricalFamilySpec:
    """Parse exact canonical data without importing reconstruction modules."""

    if type(value) is not dict:
        raise HistoricalFamilyBindingError(
            "historical family manifest must be an object"
        )
    if set(value) != {
        "controls",
        "members",
        "original_batch_id",
        "original_study_id",
        "schema",
        "target_historical_executable_id",
    } or value.get("schema") != HISTORICAL_FAMILY_SCHEMA:
        raise HistoricalFamilyBindingError(
            "historical family manifest schema or fields are invalid"
        )
    raw_members = value.get("members")
    raw_controls = value.get("controls")
    if type(raw_members) is not list or type(raw_controls) is not list:
        raise HistoricalFamilyBindingError(
            "historical family manifest members or controls are invalid"
        )
    members: list[HistoricalMemberSpec] = []
    for raw_member in raw_members:
        if (
            type(raw_member) is not dict
            or set(raw_member)
            != {
                "configuration_id",
                "historical_reference_executable_id",
                "ordinal",
                "parameters",
                "schema",
            }
            or raw_member.get("schema") != HISTORICAL_MEMBER_SCHEMA
        ):
            raise HistoricalFamilyBindingError(
                "historical family member manifest is invalid"
            )
        members.append(
            HistoricalMemberSpec(
                ordinal=raw_member["ordinal"],
                configuration_id=raw_member["configuration_id"],
                historical_reference_executable_id=(
                    raw_member["historical_reference_executable_id"]
                ),
                parameters=raw_member["parameters"],
            )
        )
    controls: list[ControlBinding] = []
    for raw_control in raw_controls:
        if (
            type(raw_control) is not dict
            or set(raw_control)
            != {
                "feature_historical_executable_ids",
                "opposite_historical_executable_id",
                "schema",
                "subject_historical_executable_id",
            }
            or raw_control.get("schema") != CONTROL_BINDING_SCHEMA
            or type(raw_control.get("feature_historical_executable_ids"))
            is not list
        ):
            raise HistoricalFamilyBindingError(
                "historical family control manifest is invalid"
            )
        controls.append(
            ControlBinding(
                subject_historical_executable_id=(
                    raw_control["subject_historical_executable_id"]
                ),
                opposite_historical_executable_id=(
                    raw_control["opposite_historical_executable_id"]
                ),
                feature_historical_executable_ids=tuple(
                    raw_control["feature_historical_executable_ids"]
                ),
            )
        )
    family = HistoricalFamilySpec(
        original_study_id=value["original_study_id"],
        original_batch_id=value["original_batch_id"],
        target_historical_executable_id=(
            value["target_historical_executable_id"]
        ),
        members=tuple(members),
        controls=tuple(controls),
    )
    try:
        input_bytes = canonical_bytes(value)
    except CanonicalJSONError as exc:
        raise HistoricalFamilyBindingError(
            "historical family manifest is not canonical"
        ) from exc
    if canonical_bytes(family.manifest()) != input_bytes:
        raise HistoricalFamilyBindingError(
            "historical family manifest is not canonical"
        )
    return family


def historical_reference_executable_id_from_manifest(
    executable_payload: object,
) -> str | None:
    """Read the sole component-declared historical reference from an Executable."""

    if not isinstance(executable_payload, dict):
        raise HistoricalFamilyBindingError(
            "replay Executable manifest must be an object"
        )
    parameters = executable_payload.get("parameters")
    manifests = executable_payload.get("component_manifests")
    if not isinstance(parameters, dict) or not isinstance(manifests, list):
        return None
    reference = parameters.get("historical_reference_executable_id")
    declarations = tuple(
        item
        for item in manifests
        if isinstance(item, dict)
        and isinstance(item.get("spec"), dict)
        and "historical_reference_executable_id"
        in item["spec"].get("parameter_fields", [])
    )
    if reference is None and not declarations:
        return None
    try:
        normalized = _sha256_identity(
            "historical_reference_executable_id",
            reference,
            "executable",
        )
    except HistoricalFamilyBindingError as exc:
        raise HistoricalFamilyBindingError(
            "replay Executable historical reference is invalid"
        ) from exc
    if len(declarations) != 1:
        raise HistoricalFamilyBindingError(
            "replay Executable historical reference is not one typed component field"
        )
    return normalized


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalFamilyAuthority:
    """One content-addressed audit migration binding for prospective replay."""

    replay_obligation_id: str
    family: HistoricalFamilySpec
    reconstruction_source_path: str
    reconstruction_source_sha256: str
    reconstruction_only_parameter_names: tuple[str, ...] = ()
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _sha256_identity(
            "replay_obligation_id",
            self.replay_obligation_id,
            "historical-replay-obligation",
        )
        if not isinstance(self.family, HistoricalFamilySpec):
            raise HistoricalFamilyBindingError(
                "historical family authority requires a typed family"
            )
        source_path = _ascii(
            "reconstruction_source_path", self.reconstruction_source_path
        )
        if (
            source_path.startswith("/")
            or ":" in source_path
            or "\\" in source_path
            or any(part in {"", ".", ".."} for part in source_path.split("/"))
        ):
            raise HistoricalFamilyBindingError(
                "reconstruction source path must be canonical and relative"
            )
        source_sha256 = _ascii(
            "reconstruction_source_sha256", self.reconstruction_source_sha256
        )
        if len(source_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in source_sha256
        ):
            raise HistoricalFamilyBindingError(
                "reconstruction source SHA-256 is invalid"
            )
        names = self.reconstruction_only_parameter_names
        if type(names) is not tuple:
            raise HistoricalFamilyBindingError(
                "reconstruction-only parameter names must be a tuple"
            )
        normalized_names = tuple(
            sorted(
                _ascii(
                    f"reconstruction_only_parameter_names[{ordinal}]",
                    name,
                )
                for ordinal, name in enumerate(names)
            )
        )
        if len(normalized_names) != len(set(normalized_names)):
            raise HistoricalFamilyBindingError(
                "reconstruction-only parameter names must be unique"
            )
        if any(
            any(
                name not in member.parameter_values()
                for member in self.family.members
            )
            for name in normalized_names
        ):
            raise HistoricalFamilyBindingError(
                "reconstruction-only parameters must exist on every member"
            )
        object.__setattr__(
            self,
            "reconstruction_only_parameter_names",
            normalized_names,
        )
        digest = canonical_digest(
            domain="historical-family-authority",
            payload=self.to_identity_payload(),
        )
        object.__setattr__(
            self,
            "identity",
            f"historical-family-authority:{digest}",
        )

    def to_identity_payload(self) -> dict[str, object]:
        return {
            "family": self.family.manifest(),
            "family_identity": self.family.identity,
            "reconstruction_source": {
                "path": self.reconstruction_source_path,
                "sha256": self.reconstruction_source_sha256,
            },
            "reconstruction_only_parameter_names": list(
                self.reconstruction_only_parameter_names
            ),
            "replay_obligation_id": self.replay_obligation_id,
            "schema": HISTORICAL_FAMILY_AUTHORITY_SCHEMA,
        }


def historical_family_authority_from_payload(
    value: object,
) -> HistoricalFamilyAuthority:
    """Rebuild and byte-check one durable family authority record payload."""

    if (
        type(value) is not dict
        or set(value)
        != {
            "family",
            "family_identity",
            "reconstruction_only_parameter_names",
            "reconstruction_source",
            "replay_obligation_id",
            "schema",
        }
        or value.get("schema") != HISTORICAL_FAMILY_AUTHORITY_SCHEMA
    ):
        raise HistoricalFamilyBindingError(
            "historical family authority payload is malformed"
        )
    source = value.get("reconstruction_source")
    if type(source) is not dict or set(source) != {"path", "sha256"}:
        raise HistoricalFamilyBindingError(
            "historical family reconstruction source is malformed"
        )
    authority = HistoricalFamilyAuthority(
        replay_obligation_id=value["replay_obligation_id"],
        family=historical_family_from_manifest(value["family"]),
        reconstruction_source_path=source["path"],
        reconstruction_source_sha256=source["sha256"],
        reconstruction_only_parameter_names=tuple(
            value["reconstruction_only_parameter_names"]
        )
        if isinstance(value["reconstruction_only_parameter_names"], list)
        else (),
    )
    if (
        value.get("family_identity") != authority.family.identity
        or canonical_bytes(authority.to_identity_payload())
        != canonical_bytes(value)
    ):
        raise HistoricalFamilyBindingError(
            "historical family authority payload is not canonical"
        )
    return authority


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalFamilyReplayContext:
    """Small immutable input used to construct one prospective definition."""

    family_authority_id: str
    replay_obligation_id: str
    family: HistoricalFamilySpec
    prior_global_exposure_count: int
    original_family_end_global_exposure_count: int

    def __post_init__(self) -> None:
        _sha256_identity(
            "family_authority_id",
            self.family_authority_id,
            "historical-family-authority",
        )
        _sha256_identity(
            "replay_obligation_id",
            self.replay_obligation_id,
            "historical-replay-obligation",
        )
        if not isinstance(self.family, HistoricalFamilySpec):
            raise HistoricalFamilyBindingError(
                "replay context family must be Writer-bound typed data"
            )
        if (
            type(self.prior_global_exposure_count) is not int
            or self.prior_global_exposure_count < 0
        ):
            raise HistoricalFamilyBindingError(
                "replay context prior exposure count must be non-negative"
            )
        if (
            type(self.original_family_end_global_exposure_count) is not int
            or self.original_family_end_global_exposure_count
            < self.family.family_size
            or self.original_family_end_global_exposure_count
            > self.prior_global_exposure_count
        ):
            raise HistoricalFamilyBindingError(
                "replay context original family end exposure is invalid"
            )


__all__ = [
    "CONTROL_BINDING_SCHEMA",
    "ControlBinding",
    "HISTORICAL_FAMILY_SCHEMA",
    "HISTORICAL_FAMILY_CORE_SCHEMA",
    "HISTORICAL_FAMILY_AUTHORITY_SCHEMA",
    "HISTORICAL_MEMBER_SCHEMA",
    "HistoricalFamilyBindingError",
    "HistoricalFamilyLike",
    "HistoricalFamilyReplayContext",
    "HistoricalFamilyAuthority",
    "HistoricalFamilySpec",
    "HistoricalMemberSpec",
    "historical_family_authority_from_payload",
    "historical_family_core_identity",
    "historical_family_from_manifest",
    "historical_reference_executable_id_from_manifest",
]
