"""Typed audit authority for revoking one invalid replay satisfaction.

The original satisfaction and every scientific record remain immutable.  The
legacy v1 manifest records an exact E01 family defect.  The additive v2
manifest can also bind completion-scoped scientific-validity heads, so an
otherwise well-formed replay cannot preserve authority from invalid evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.identity import canonical_digest


AUDIT_MANIFEST_SCHEMA = "replay_satisfaction_invalidation_audit_manifest.v1"
AUDIT_MANIFEST_V2_SCHEMA = "replay_satisfaction_invalidation_audit_manifest.v2"
SELECTION_CRITERION_ID = "E01-familywise-selection"
COMPLETION_VALIDITY_DEFECT_KIND = "completion_validity"
MULTIPLICITY_DEFECT_KIND = "multiplicity_binding"


class ReplayMultiplicityDefectCode(str, Enum):
    """Narrow replay defects that may revoke satisfaction authority."""

    SELECTION_FAMILY_SIZE_MISMATCH = "selection_family_size_mismatch"
    SELECTION_FAMILY_DISAGREEMENT = "selection_family_disagreement"
    SELECTION_FAMILY_MEMBERSHIP_MISMATCH = (
        "selection_family_membership_mismatch"
    )


class ReplayCompletionValidityDefectCode(str, Enum):
    """Completion defects that revoke family-wide satisfaction authority."""

    EVIDENCE_COMPLETION_VALIDITY_INVALID = (
        "evidence_completion_validity_invalid"
    )


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _identity(name: str, value: object, *, prefix: str) -> str:
    text = _ascii(name, value)
    if not text.startswith(prefix):
        raise ValueError(f"{name} must use the {prefix!r} namespace")
    _digest(f"{name} digest", text.removeprefix(prefix))
    return text


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplaySelectionFamilyObservation:
    """One member's exact recorded E01 family binding."""

    executable_id: str
    completion_record_id: str
    family_id: str
    family_size: int
    method: str
    alpha_ppm: int
    registered_member_id: str
    ordered_member_ids: tuple[str, ...]
    family_registration_hash: str

    def __post_init__(self) -> None:
        _identity(
            "selection observation Executable",
            self.executable_id,
            prefix="executable:",
        )
        _digest("selection observation completion", self.completion_record_id)
        _ascii("selection observation family id", self.family_id)
        if type(self.family_size) is not int or self.family_size < 1:
            raise ValueError("selection observation family size must be positive")
        _ascii("selection observation method", self.method)
        if (
            type(self.alpha_ppm) is not int
            or not 1 <= self.alpha_ppm <= 1_000_000
        ):
            raise ValueError("selection observation alpha must be within ppm bounds")
        registered_member_id = _ascii(
            "selection observation registered member",
            self.registered_member_id,
        )
        members = tuple(self.ordered_member_ids)
        if (
            not members
            or len(members) != self.family_size
            or len(set(members)) != len(members)
            or any(
                _ascii(
                    "selection observation registered member",
                    item,
                )
                != item
                for item in members
            )
            or registered_member_id not in members
        ):
            raise ValueError(
                "selection observation registration membership is malformed"
            )
        registration_hash = _digest(
            "selection observation family registration hash",
            self.family_registration_hash,
        )
        expected_hash = canonical_digest(
            domain="scientific-v2-multiplicity-family",
            payload={
                "alpha_ppm": self.alpha_ppm,
                "family_id": self.family_id,
                "family_size": self.family_size,
                "method": self.method,
                "ordered_member_ids": list(members),
                "schema": "scientific_multiplicity_family_registration.v1",
            },
        )
        if registration_hash != expected_hash:
            raise ValueError(
                "selection observation family registration hash is invalid"
            )
        object.__setattr__(self, "ordered_member_ids", members)

    def to_identity_payload(self) -> dict[str, object]:
        return {
            "alpha_ppm": self.alpha_ppm,
            "completion_record_id": self.completion_record_id,
            "executable_id": self.executable_id,
            "family_id": self.family_id,
            "family_registration_hash": self.family_registration_hash,
            "family_size": self.family_size,
            "method": self.method,
            "ordered_member_ids": list(self.ordered_member_ids),
            "registered_member_id": self.registered_member_id,
        }

    @classmethod
    def from_mapping(cls, value: object) -> ReplaySelectionFamilyObservation:
        fields = {
            "alpha_ppm",
            "completion_record_id",
            "executable_id",
            "family_id",
            "family_registration_hash",
            "family_size",
            "method",
            "ordered_member_ids",
            "registered_member_id",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != fields
            or not isinstance(value.get("ordered_member_ids"), list)
        ):
            raise ValueError("selection family observation is malformed")
        return cls(
            executable_id=value["executable_id"],  # type: ignore[arg-type]
            completion_record_id=value["completion_record_id"],  # type: ignore[arg-type]
            family_id=value["family_id"],  # type: ignore[arg-type]
            family_size=value["family_size"],  # type: ignore[arg-type]
            method=value["method"],  # type: ignore[arg-type]
            alpha_ppm=value["alpha_ppm"],  # type: ignore[arg-type]
            registered_member_id=value["registered_member_id"],  # type: ignore[arg-type]
            ordered_member_ids=tuple(
                value["ordered_member_ids"]  # type: ignore[arg-type]
            ),
            family_registration_hash=value[
                "family_registration_hash"
            ],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayMultiplicityBindingDefect:
    """Exact E01 mismatch derived by revalidating durable Batch evidence."""

    code: ReplayMultiplicityDefectCode
    criterion_id: str
    batch_open_record_id: str
    batch_close_record_id: str
    expected_executable_ids: tuple[str, ...]
    expected_family_size: int
    observations: tuple[ReplaySelectionFamilyObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.code, ReplayMultiplicityDefectCode):
            raise TypeError("multiplicity defect code is invalid")
        if self.criterion_id != SELECTION_CRITERION_ID:
            raise ValueError("only E01 selection-family defects are revocable")
        _identity(
            "multiplicity Batch open",
            self.batch_open_record_id,
            prefix="batch:",
        )
        _digest("multiplicity Batch close", self.batch_close_record_id)
        expected = tuple(self.expected_executable_ids)
        if (
            not expected
            or len(expected) != len(set(expected))
            or any(
                _identity(
                    "multiplicity family Executable",
                    item,
                    prefix="executable:",
                )
                != item
                for item in expected
            )
            or type(self.expected_family_size) is not int
            or self.expected_family_size != len(expected)
        ):
            raise ValueError("expected Batch family is malformed")
        observations = tuple(self.observations)
        if (
            len(observations) != len(expected)
            or tuple(item.executable_id for item in observations)
            != tuple(sorted(expected))
            or len({item.completion_record_id for item in observations})
            != len(observations)
        ):
            raise ValueError("selection observations do not exactly cover the Batch")
        # Prospective execution still requires exact Batch order, but a later
        # audit may revoke immutable satisfaction only for a changed member
        # set (or one of the other typed defects).  Reordering the same set is
        # protocol drift, not evidence that the historical family omitted or
        # substituted a scientific trial.
        expected_member_set = set(expected)
        family_bindings = {
            (item.family_id, item.family_size, item.method, item.alpha_ppm)
            for item in observations
        }
        if self.code is ReplayMultiplicityDefectCode.SELECTION_FAMILY_SIZE_MISMATCH:
            if all(
                item.family_size == self.expected_family_size
                for item in observations
            ):
                raise ValueError("selection family size mismatch is not present")
        elif self.code is ReplayMultiplicityDefectCode.SELECTION_FAMILY_DISAGREEMENT:
            if (
                any(
                    item.family_size != self.expected_family_size
                    for item in observations
                )
                or len(family_bindings) <= 1
            ):
                raise ValueError("selection family disagreement is not present")
        elif (
            any(
                item.family_size != self.expected_family_size
                for item in observations
            )
            or len(family_bindings) != 1
            or any(
                item.registered_member_id != item.executable_id
                or any(
                    _identity(
                        "selection membership registered Executable",
                        member_id,
                        prefix="executable:",
                    )
                    != member_id
                    for member_id in item.ordered_member_ids
                )
                for item in observations
            )
            or not any(
                set(item.ordered_member_ids) != expected_member_set
                for item in observations
            )
        ):
            raise ValueError("selection family membership mismatch is not present")
        object.__setattr__(self, "expected_executable_ids", expected)
        object.__setattr__(self, "observations", observations)

    def to_identity_payload(self) -> dict[str, object]:
        return {
            "batch_close_record_id": self.batch_close_record_id,
            "batch_open_record_id": self.batch_open_record_id,
            "code": self.code.value,
            "criterion_id": self.criterion_id,
            "expected_executable_ids": list(self.expected_executable_ids),
            "expected_family_size": self.expected_family_size,
            "observations": [item.to_identity_payload() for item in self.observations],
        }

    @classmethod
    def from_mapping(cls, value: object) -> ReplayMultiplicityBindingDefect:
        fields = {
            "batch_close_record_id",
            "batch_open_record_id",
            "code",
            "criterion_id",
            "expected_executable_ids",
            "expected_family_size",
            "observations",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("replay multiplicity defect is malformed")
        executable_ids = value["expected_executable_ids"]
        observations = value["observations"]
        if not isinstance(executable_ids, list) or not isinstance(observations, list):
            raise ValueError("replay multiplicity defect inventory is malformed")
        return cls(
            code=ReplayMultiplicityDefectCode(value["code"]),
            criterion_id=value["criterion_id"],  # type: ignore[arg-type]
            batch_open_record_id=value["batch_open_record_id"],  # type: ignore[arg-type]
            batch_close_record_id=value["batch_close_record_id"],  # type: ignore[arg-type]
            expected_executable_ids=tuple(executable_ids),  # type: ignore[arg-type]
            expected_family_size=value["expected_family_size"],  # type: ignore[arg-type]
            observations=tuple(
                ReplaySelectionFamilyObservation.from_mapping(item)
                for item in observations
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplaySatisfactionInvalidationAuditManifest:
    """Canonical audit manifest derived only from durable replay authority."""

    governing_mission_id: str
    obligation_id: str
    satisfaction_record_id: str
    satisfaction_event_sequence: int
    portfolio_decision_id: str
    replay_study_id: str
    replay_executable_id: str
    replay_study_close_record_id: str
    study_diagnosis_id: str
    completion_record_ids: tuple[str, ...]
    defect: ReplayMultiplicityBindingDefect

    def __post_init__(self) -> None:
        _ascii("replay invalidation Mission", self.governing_mission_id)
        _identity(
            "replay invalidation obligation",
            self.obligation_id,
            prefix="historical-replay-obligation:",
        )
        _identity(
            "replay invalidation satisfaction",
            self.satisfaction_record_id,
            prefix="historical-replay-satisfaction:",
        )
        if type(self.satisfaction_event_sequence) is not int or self.satisfaction_event_sequence < 2:
            raise ValueError("satisfaction event sequence must follow obligation creation")
        _identity("replay invalidation Decision", self.portfolio_decision_id, prefix="decision:")
        _ascii("replay invalidation Study", self.replay_study_id)
        _identity("replay invalidation Executable", self.replay_executable_id, prefix="executable:")
        _digest("replay invalidation Study close", self.replay_study_close_record_id)
        _identity("replay invalidation diagnosis", self.study_diagnosis_id, prefix="diagnosis:")
        completions = tuple(sorted(self.completion_record_ids))
        if (
            not completions
            or len(completions) != len(set(completions))
            or any(_digest("replay invalidation completion", item) != item for item in completions)
            or set(completions)
            != {item.completion_record_id for item in self.defect.observations}
        ):
            raise ValueError("replay invalidation completion inventory is not exact")
        if self.replay_executable_id not in self.defect.expected_executable_ids:
            raise ValueError("replay invalidation target is outside the Batch family")
        object.__setattr__(self, "completion_record_ids", completions)

    @property
    def identity(self) -> str:
        return "historical-replay-satisfaction-invalidation:" + canonical_digest(
            domain="historical-replay-satisfaction-invalidation",
            payload=self.to_identity_payload(),
        )

    def to_identity_payload(self) -> dict[str, object]:
        return {
            "completion_record_ids": list(self.completion_record_ids),
            "defect": self.defect.to_identity_payload(),
            "governing_mission_id": self.governing_mission_id,
            "obligation_id": self.obligation_id,
            "portfolio_decision_id": self.portfolio_decision_id,
            "replay_executable_id": self.replay_executable_id,
            "replay_study_close_record_id": self.replay_study_close_record_id,
            "replay_study_id": self.replay_study_id,
            "satisfaction_event_sequence": self.satisfaction_event_sequence,
            "satisfaction_record_id": self.satisfaction_record_id,
            "schema": AUDIT_MANIFEST_SCHEMA,
            "study_diagnosis_id": self.study_diagnosis_id,
        }

    @classmethod
    def from_mapping(
        cls,
        value: object,
    ) -> ReplaySatisfactionInvalidationAuditManifest:
        fields = {
            "completion_record_ids",
            "defect",
            "governing_mission_id",
            "obligation_id",
            "portfolio_decision_id",
            "replay_executable_id",
            "replay_study_close_record_id",
            "replay_study_id",
            "satisfaction_event_sequence",
            "satisfaction_record_id",
            "schema",
            "study_diagnosis_id",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != fields
            or value.get("schema") != AUDIT_MANIFEST_SCHEMA
            or not isinstance(value.get("completion_record_ids"), list)
        ):
            raise ValueError("replay satisfaction invalidation manifest is malformed")
        return cls(
            governing_mission_id=value["governing_mission_id"],  # type: ignore[arg-type]
            obligation_id=value["obligation_id"],  # type: ignore[arg-type]
            satisfaction_record_id=value["satisfaction_record_id"],  # type: ignore[arg-type]
            satisfaction_event_sequence=value["satisfaction_event_sequence"],  # type: ignore[arg-type]
            portfolio_decision_id=value["portfolio_decision_id"],  # type: ignore[arg-type]
            replay_study_id=value["replay_study_id"],  # type: ignore[arg-type]
            replay_executable_id=value["replay_executable_id"],  # type: ignore[arg-type]
            replay_study_close_record_id=value["replay_study_close_record_id"],  # type: ignore[arg-type]
            study_diagnosis_id=value["study_diagnosis_id"],  # type: ignore[arg-type]
            completion_record_ids=tuple(value["completion_record_ids"]),  # type: ignore[arg-type]
            defect=ReplayMultiplicityBindingDefect.from_mapping(value["defect"]),
        )

    @classmethod
    def from_bytes(
        cls,
        document: bytes,
    ) -> ReplaySatisfactionInvalidationAuditManifest:
        return cls.from_mapping(parse_canonical(document))


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayCompletionValidityObservation:
    """One current completion-validity head used by a replay satisfaction."""

    completion_record_id: str
    executable_id: str
    invalidation_record_id: str
    reason: str
    affected_criterion_ids: tuple[str, ...]
    validity_stream_sequence: int
    authority_event_id: str
    authority_sequence: int
    authority_offset: int

    def __post_init__(self) -> None:
        _digest("completion validity completion", self.completion_record_id)
        _identity(
            "completion validity Executable",
            self.executable_id,
            prefix="executable:",
        )
        _identity(
            "completion validity invalidation",
            self.invalidation_record_id,
            prefix="historical-scientific-validity-invalidation:",
        )
        _ascii("completion validity reason", self.reason)
        criteria = tuple(sorted(self.affected_criterion_ids))
        if (
            not criteria
            or len(criteria) != len(set(criteria))
            or any(_ascii("completion validity criterion", item) != item for item in criteria)
        ):
            raise ValueError("completion validity criteria must be unique ASCII")
        if (
            type(self.validity_stream_sequence) is not int
            or self.validity_stream_sequence < 1
        ):
            raise ValueError("completion validity stream sequence must be positive")
        _digest("completion validity authority event", self.authority_event_id)
        if type(self.authority_sequence) is not int or self.authority_sequence < 1:
            raise ValueError("completion validity authority sequence must be positive")
        if type(self.authority_offset) is not int or self.authority_offset < 0:
            raise ValueError("completion validity authority offset must be nonnegative")
        object.__setattr__(self, "affected_criterion_ids", criteria)

    def to_identity_payload(self) -> dict[str, object]:
        return {
            "affected_criterion_ids": list(self.affected_criterion_ids),
            "authority_event_id": self.authority_event_id,
            "authority_offset": self.authority_offset,
            "authority_sequence": self.authority_sequence,
            "completion_record_id": self.completion_record_id,
            "executable_id": self.executable_id,
            "invalidation_record_id": self.invalidation_record_id,
            "reason": self.reason,
            "validity_stream_sequence": self.validity_stream_sequence,
        }

    @classmethod
    def from_mapping(cls, value: object) -> ReplayCompletionValidityObservation:
        fields = {
            "affected_criterion_ids",
            "authority_event_id",
            "authority_offset",
            "authority_sequence",
            "completion_record_id",
            "executable_id",
            "invalidation_record_id",
            "reason",
            "validity_stream_sequence",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != fields
            or not isinstance(value.get("affected_criterion_ids"), list)
        ):
            raise ValueError("completion validity observation is malformed")
        return cls(
            completion_record_id=value["completion_record_id"],  # type: ignore[arg-type]
            executable_id=value["executable_id"],  # type: ignore[arg-type]
            invalidation_record_id=value["invalidation_record_id"],  # type: ignore[arg-type]
            reason=value["reason"],  # type: ignore[arg-type]
            affected_criterion_ids=tuple(value["affected_criterion_ids"]),  # type: ignore[arg-type]
            validity_stream_sequence=value["validity_stream_sequence"],  # type: ignore[arg-type]
            authority_event_id=value["authority_event_id"],  # type: ignore[arg-type]
            authority_sequence=value["authority_sequence"],  # type: ignore[arg-type]
            authority_offset=value["authority_offset"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayCompletionValidityDefect:
    """Exact invalid completion heads in one satisfaction evidence family."""

    code: ReplayCompletionValidityDefectCode
    observations: tuple[ReplayCompletionValidityObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.code, ReplayCompletionValidityDefectCode):
            raise TypeError("completion validity defect code is invalid")
        observations = tuple(
            sorted(self.observations, key=lambda item: item.completion_record_id)
        )
        if (
            not observations
            or any(
                not isinstance(item, ReplayCompletionValidityObservation)
                for item in observations
            )
            or len({item.completion_record_id for item in observations})
            != len(observations)
            or len({item.invalidation_record_id for item in observations})
            != len(observations)
        ):
            raise ValueError("completion validity observations are not exact")
        object.__setattr__(self, "observations", observations)

    def to_identity_payload(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "observations": [
                item.to_identity_payload() for item in self.observations
            ],
        }

    @classmethod
    def from_mapping(cls, value: object) -> ReplayCompletionValidityDefect:
        if (
            not isinstance(value, Mapping)
            or set(value) != {"code", "observations"}
            or not isinstance(value.get("observations"), list)
        ):
            raise ValueError("replay completion validity defect is malformed")
        return cls(
            code=ReplayCompletionValidityDefectCode(value["code"]),
            observations=tuple(
                ReplayCompletionValidityObservation.from_mapping(item)
                for item in value["observations"]
            ),
        )


ReplaySatisfactionDefect = (
    ReplayMultiplicityBindingDefect | ReplayCompletionValidityDefect
)


def _defect_kind(defect: ReplaySatisfactionDefect) -> str:
    if isinstance(defect, ReplayMultiplicityBindingDefect):
        return MULTIPLICITY_DEFECT_KIND
    if isinstance(defect, ReplayCompletionValidityDefect):
        return COMPLETION_VALIDITY_DEFECT_KIND
    raise TypeError("replay satisfaction defect is unsupported")


def _defect_payload(defect: ReplaySatisfactionDefect) -> dict[str, object]:
    return {
        "kind": _defect_kind(defect),
        "value": defect.to_identity_payload(),
    }


def _defect_from_mapping(value: object) -> ReplaySatisfactionDefect:
    if not isinstance(value, Mapping) or set(value) != {"kind", "value"}:
        raise ValueError("replay satisfaction defect wrapper is malformed")
    if value["kind"] == MULTIPLICITY_DEFECT_KIND:
        return ReplayMultiplicityBindingDefect.from_mapping(value["value"])
    if value["kind"] == COMPLETION_VALIDITY_DEFECT_KIND:
        return ReplayCompletionValidityDefect.from_mapping(value["value"])
    raise ValueError("replay satisfaction defect kind is unsupported")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplaySatisfactionInvalidationAuditManifestV2:
    """Additive manifest supporting a sorted union of exact defect classes."""

    governing_mission_id: str
    obligation_id: str
    satisfaction_record_id: str
    satisfaction_event_sequence: int
    portfolio_decision_id: str
    replay_study_id: str
    replay_executable_id: str
    replay_study_close_record_id: str
    study_diagnosis_id: str
    completion_record_ids: tuple[str, ...]
    defects: tuple[ReplaySatisfactionDefect, ...]

    def __post_init__(self) -> None:
        _ascii("replay invalidation Mission", self.governing_mission_id)
        _identity(
            "replay invalidation obligation",
            self.obligation_id,
            prefix="historical-replay-obligation:",
        )
        _identity(
            "replay invalidation satisfaction",
            self.satisfaction_record_id,
            prefix="historical-replay-satisfaction:",
        )
        if (
            type(self.satisfaction_event_sequence) is not int
            or self.satisfaction_event_sequence < 2
        ):
            raise ValueError(
                "satisfaction event sequence must follow obligation creation"
            )
        _identity(
            "replay invalidation Decision",
            self.portfolio_decision_id,
            prefix="decision:",
        )
        _ascii("replay invalidation Study", self.replay_study_id)
        _identity(
            "replay invalidation Executable",
            self.replay_executable_id,
            prefix="executable:",
        )
        _digest(
            "replay invalidation Study close",
            self.replay_study_close_record_id,
        )
        _identity(
            "replay invalidation diagnosis",
            self.study_diagnosis_id,
            prefix="diagnosis:",
        )
        completions = tuple(sorted(self.completion_record_ids))
        if (
            not completions
            or len(completions) != len(set(completions))
            or any(
                _digest("replay invalidation completion", item) != item
                for item in completions
            )
        ):
            raise ValueError("replay invalidation completion inventory is not exact")
        defects = tuple(sorted(self.defects, key=_defect_kind))
        if (
            not defects
            or any(
                not isinstance(
                    item,
                    (
                        ReplayMultiplicityBindingDefect,
                        ReplayCompletionValidityDefect,
                    ),
                )
                for item in defects
            )
            or len({_defect_kind(item) for item in defects}) != len(defects)
        ):
            raise ValueError("replay satisfaction defects must be a typed union")
        completion_set = set(completions)
        for defect in defects:
            observed_ids = {
                item.completion_record_id for item in defect.observations
            }
            if not observed_ids.issubset(completion_set):
                raise ValueError("replay defect is outside satisfaction evidence")
            if isinstance(defect, ReplayMultiplicityBindingDefect):
                if (
                    observed_ids != completion_set
                    or self.replay_executable_id
                    not in defect.expected_executable_ids
                ):
                    raise ValueError(
                        "multiplicity defect does not cover the exact replay family"
                    )
        object.__setattr__(self, "completion_record_ids", completions)
        object.__setattr__(self, "defects", defects)

    @property
    def identity(self) -> str:
        return "historical-replay-satisfaction-invalidation:" + canonical_digest(
            domain="historical-replay-satisfaction-invalidation-v2",
            payload=self.to_identity_payload(),
        )

    def to_identity_payload(self) -> dict[str, object]:
        return {
            "completion_record_ids": list(self.completion_record_ids),
            "defects": [_defect_payload(item) for item in self.defects],
            "governing_mission_id": self.governing_mission_id,
            "obligation_id": self.obligation_id,
            "portfolio_decision_id": self.portfolio_decision_id,
            "replay_executable_id": self.replay_executable_id,
            "replay_study_close_record_id": self.replay_study_close_record_id,
            "replay_study_id": self.replay_study_id,
            "satisfaction_event_sequence": self.satisfaction_event_sequence,
            "satisfaction_record_id": self.satisfaction_record_id,
            "schema": AUDIT_MANIFEST_V2_SCHEMA,
            "study_diagnosis_id": self.study_diagnosis_id,
        }

    @classmethod
    def from_mapping(
        cls,
        value: object,
    ) -> ReplaySatisfactionInvalidationAuditManifestV2:
        fields = {
            "completion_record_ids",
            "defects",
            "governing_mission_id",
            "obligation_id",
            "portfolio_decision_id",
            "replay_executable_id",
            "replay_study_close_record_id",
            "replay_study_id",
            "satisfaction_event_sequence",
            "satisfaction_record_id",
            "schema",
            "study_diagnosis_id",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != fields
            or value.get("schema") != AUDIT_MANIFEST_V2_SCHEMA
            or not isinstance(value.get("completion_record_ids"), list)
            or not isinstance(value.get("defects"), list)
        ):
            raise ValueError(
                "replay satisfaction invalidation v2 manifest is malformed"
            )
        return cls(
            governing_mission_id=value["governing_mission_id"],  # type: ignore[arg-type]
            obligation_id=value["obligation_id"],  # type: ignore[arg-type]
            satisfaction_record_id=value["satisfaction_record_id"],  # type: ignore[arg-type]
            satisfaction_event_sequence=value["satisfaction_event_sequence"],  # type: ignore[arg-type]
            portfolio_decision_id=value["portfolio_decision_id"],  # type: ignore[arg-type]
            replay_study_id=value["replay_study_id"],  # type: ignore[arg-type]
            replay_executable_id=value["replay_executable_id"],  # type: ignore[arg-type]
            replay_study_close_record_id=value["replay_study_close_record_id"],  # type: ignore[arg-type]
            study_diagnosis_id=value["study_diagnosis_id"],  # type: ignore[arg-type]
            completion_record_ids=tuple(value["completion_record_ids"]),  # type: ignore[arg-type]
            defects=tuple(_defect_from_mapping(item) for item in value["defects"]),  # type: ignore[arg-type]
        )

    @classmethod
    def from_bytes(
        cls,
        document: bytes,
    ) -> ReplaySatisfactionInvalidationAuditManifestV2:
        return cls.from_mapping(parse_canonical(document))


ReplaySatisfactionInvalidationManifest = (
    ReplaySatisfactionInvalidationAuditManifest
    | ReplaySatisfactionInvalidationAuditManifestV2
)


def replay_satisfaction_invalidation_manifest_from_mapping(
    value: object,
) -> ReplaySatisfactionInvalidationManifest:
    if not isinstance(value, Mapping):
        raise ValueError("replay satisfaction invalidation manifest is malformed")
    if value.get("schema") == AUDIT_MANIFEST_SCHEMA:
        return ReplaySatisfactionInvalidationAuditManifest.from_mapping(value)
    if value.get("schema") == AUDIT_MANIFEST_V2_SCHEMA:
        return ReplaySatisfactionInvalidationAuditManifestV2.from_mapping(value)
    raise ValueError("replay satisfaction invalidation schema is unsupported")


def replay_satisfaction_invalidation_manifest_from_bytes(
    document: bytes,
) -> ReplaySatisfactionInvalidationManifest:
    return replay_satisfaction_invalidation_manifest_from_mapping(
        parse_canonical(document)
    )


__all__ = [
    "AUDIT_MANIFEST_SCHEMA",
    "AUDIT_MANIFEST_V2_SCHEMA",
    "COMPLETION_VALIDITY_DEFECT_KIND",
    "MULTIPLICITY_DEFECT_KIND",
    "ReplayCompletionValidityDefect",
    "ReplayCompletionValidityDefectCode",
    "ReplayCompletionValidityObservation",
    "ReplayMultiplicityBindingDefect",
    "ReplayMultiplicityDefectCode",
    "ReplaySatisfactionInvalidationAuditManifest",
    "ReplaySatisfactionInvalidationAuditManifestV2",
    "ReplaySatisfactionInvalidationManifest",
    "ReplaySelectionFamilyObservation",
    "SELECTION_CRITERION_ID",
    "replay_satisfaction_invalidation_manifest_from_bytes",
    "replay_satisfaction_invalidation_manifest_from_mapping",
]
