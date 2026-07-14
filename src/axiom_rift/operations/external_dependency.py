"""Typed external-recovery and blocked-Mission reentry contracts."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from typing import Any, Mapping, Sequence

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest


class ExternalDependencyContractError(ValueError):
    """An external dependency contract is malformed."""


_DEPENDENCY_KINDS = frozenset(
    {
        "broker_service",
        "hardware_service",
        "market_data_service",
        "operating_system_service",
        "vendor_runtime",
    }
)
_RECOVERY_KINDS = frozenset(
    {
        "escalation_probe",
        "external_probe",
        "local_recovery",
        "safe_substitute_search",
    }
)
_REQUIRED_RECOVERY_KINDS = frozenset(
    {"external_probe", "local_recovery", "safe_substitute_search"}
)
_RESUME_ACTION_KINDS = frozenset(
    {"choose_next_initiative_or_terminal", "open_initiative"}
)


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ExternalDependencyContractError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object, *, prefix: str = "") -> str:
    text = _ascii(name, value)
    if prefix and not text.startswith(prefix):
        raise ExternalDependencyContractError(
            f"{name} must use the {prefix} identity prefix"
        )
    digest = text.removeprefix(prefix) if prefix else text
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ExternalDependencyContractError(
            f"{name} must contain a lowercase SHA-256 digest"
        )
    return text


def _exact_keys(name: str, value: Mapping[str, Any], keys: set[str]) -> None:
    if set(value) != keys:
        raise ExternalDependencyContractError(f"{name} schema is not exact")


def _require_ascii_json(name: str, value: object) -> None:
    """Reject mutable/non-JSON or non-ASCII values before canonical freezing."""

    if value is None or type(value) in {bool, int}:
        return
    if type(value) is str:
        _ascii(name, value)
        return
    if type(value) is list:
        for ordinal, child in enumerate(value):
            _require_ascii_json(f"{name}[{ordinal}]", child)
        return
    if type(value) is dict:
        for key, child in value.items():
            _ascii(f"{name} key", key)
            _require_ascii_json(f"{name}.{key}", child)
        return
    raise ExternalDependencyContractError(
        f"{name} must be canonical JSON-safe ASCII data"
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalResumeAction:
    """One exact control action restored after external availability."""

    kind: str
    mission_id: str
    bindings: InitVar[object] = ()
    _binding_documents: tuple[tuple[str, bytes], ...] = field(
        init=False, repr=False
    )
    identity: str = field(init=False)

    def __post_init__(self, bindings: object) -> None:
        kind = _ascii("external resume action kind", self.kind)
        if kind not in _RESUME_ACTION_KINDS:
            raise ExternalDependencyContractError(
                "external resume action is not a supported stable Mission action"
            )
        mission_id = _ascii("external resume Mission id", self.mission_id)
        if type(bindings) is not tuple:
            raise ExternalDependencyContractError(
                "external resume action bindings must be a tuple"
            )
        normalized_documents: list[tuple[str, bytes]] = []
        try:
            pairs = tuple(bindings)
            for pair in pairs:
                if type(pair) is not tuple or len(pair) != 2:
                    raise ExternalDependencyContractError(
                        "external resume action binding must be a name/value pair"
                    )
                name, value = pair
                typed_name = _ascii("external resume binding name", name)
                _require_ascii_json("external resume binding value", value)
                normalized_documents.append(
                    (typed_name, canonical_bytes(value))
                )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ExternalDependencyContractError):
                raise
            raise ExternalDependencyContractError(
                "external resume action binding is not canonical"
            ) from exc
        normalized = tuple(sorted(normalized_documents))
        names = [name for name, _document in normalized]
        if len(names) != len(set(names)) or any(
            name in {"kind", "mission_id"} for name in names
        ):
            raise ExternalDependencyContractError(
                "external resume action bindings are duplicated or reserved"
            )
        values = {
            name: parse_canonical(document) for name, document in normalized
        }
        if kind == "choose_next_initiative_or_terminal":
            allowed = {
                "pending_replay_obligation_ids",
                "required_replay_priority",
            }
            if frozenset(values) not in {frozenset(), frozenset(allowed)}:
                raise ExternalDependencyContractError(
                    "Mission scheduler resume bindings are incomplete or unsupported"
                )
            if values:
                obligation_ids = values["pending_replay_obligation_ids"]
                priority = values["required_replay_priority"]
                if (
                    type(obligation_ids) is not list
                    or not obligation_ids
                    or obligation_ids != sorted(set(obligation_ids))
                    or priority not in {"p0", "p1"}
                ):
                    raise ExternalDependencyContractError(
                        "Mission scheduler replay bindings are not canonical"
                    )
                for obligation_id in obligation_ids:
                    _digest(
                        "Mission scheduler replay obligation",
                        obligation_id,
                        prefix="historical-replay-obligation:",
                    )
        elif set(values) != {"research_intake_id"}:
            raise ExternalDependencyContractError(
                "open_initiative resume requires the exact research intake"
            )
        if kind == "open_initiative":
            _digest(
                "external resume research intake",
                values["research_intake_id"],
                prefix="research-intake:",
            )
        object.__setattr__(self, "_binding_documents", normalized)
        object.__setattr__(
            self,
            "identity",
            "external-resume-action:"
            + canonical_digest(
                domain="external-resume-action",
                payload=self.to_identity_payload(),
            ),
        )

    def to_next_action(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "mission_id": self.mission_id,
            **{
                name: parse_canonical(document)
                for name, document in self._binding_documents
            },
        }

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "bindings": [
                {"name": name, "value": parse_canonical(document)}
                for name, document in self._binding_documents
            ],
            "kind": self.kind,
            "mission_id": self.mission_id,
            "schema": "external_resume_action.v1",
        }

    @classmethod
    def from_next_action(cls, value: Mapping[str, Any]) -> "ExternalResumeAction":
        if not isinstance(value, Mapping):
            raise ExternalDependencyContractError(
                "external resume next action must be a mapping"
            )
        kind = value.get("kind")
        mission_id = value.get("mission_id")
        bindings = tuple(
            (name, child)
            for name, child in value.items()
            if name not in {"kind", "mission_id"}
        )
        return cls(kind=kind, mission_id=mission_id, bindings=bindings)

    @classmethod
    def from_identity_payload(
        cls, value: Mapping[str, Any]
    ) -> "ExternalResumeAction":
        if not isinstance(value, Mapping):
            raise ExternalDependencyContractError(
                "external resume action payload must be a mapping"
            )
        _exact_keys(
            "external resume action",
            value,
            {"bindings", "kind", "mission_id", "schema"},
        )
        if value.get("schema") != "external_resume_action.v1":
            raise ExternalDependencyContractError(
                "external resume action schema is invalid"
            )
        raw_bindings = value.get("bindings")
        if type(raw_bindings) is not list:
            raise ExternalDependencyContractError(
                "external resume action bindings are invalid"
            )
        bindings: list[tuple[str, Any]] = []
        for item in raw_bindings:
            if not isinstance(item, Mapping) or set(item) != {"name", "value"}:
                raise ExternalDependencyContractError(
                    "external resume action binding is malformed"
                )
            bindings.append((item["name"], item["value"]))
        action = cls(
            kind=value["kind"],
            mission_id=value["mission_id"],
            bindings=tuple(bindings),
        )
        if value != action.to_identity_payload():
            raise ExternalDependencyContractError(
                "external resume action payload is not canonical"
            )
        return action


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalResumeCondition:
    """A validator-bound finite external change and its restored action."""

    dependency_id: str
    dependency_kind: str
    blocked_mission_capability: str
    required_external_change: str
    validator_id: str
    validation_plan_hash: str
    resume_action: ExternalResumeAction
    condition_kind: str = "blocked_capability_available"
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _ascii("external dependency id", self.dependency_id)
        if self.dependency_kind not in _DEPENDENCY_KINDS:
            raise ExternalDependencyContractError(
                "external dependency kind is not typed"
            )
        _ascii("blocked Mission capability", self.blocked_mission_capability)
        _ascii("required external change", self.required_external_change)
        _digest("external validator id", self.validator_id, prefix="validator:")
        _digest("external validation plan", self.validation_plan_hash)
        if not isinstance(self.resume_action, ExternalResumeAction):
            raise ExternalDependencyContractError(
                "external resume condition requires a typed action"
            )
        if self.condition_kind != "blocked_capability_available":
            raise ExternalDependencyContractError(
                "external resume condition kind is not typed"
            )
        object.__setattr__(
            self,
            "identity",
            "external-resume-condition:"
            + canonical_digest(
                domain="external-resume-condition",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "blocked_mission_capability": self.blocked_mission_capability,
            "condition_kind": self.condition_kind,
            "dependency_id": self.dependency_id,
            "dependency_kind": self.dependency_kind,
            "required_external_change": self.required_external_change,
            "resume_action": self.resume_action.to_identity_payload(),
            "schema": "external_resume_condition.v1",
            "validation_plan_hash": self.validation_plan_hash,
            "validator_id": self.validator_id,
        }

    @classmethod
    def from_identity_payload(
        cls, value: Mapping[str, Any]
    ) -> "ExternalResumeCondition":
        if not isinstance(value, Mapping):
            raise ExternalDependencyContractError(
                "external resume condition payload must be a mapping"
            )
        _exact_keys(
            "external resume condition",
            value,
            {
                "blocked_mission_capability",
                "condition_kind",
                "dependency_id",
                "dependency_kind",
                "required_external_change",
                "resume_action",
                "schema",
                "validation_plan_hash",
                "validator_id",
            },
        )
        if value.get("schema") != "external_resume_condition.v1":
            raise ExternalDependencyContractError(
                "external resume condition schema is invalid"
            )
        return cls(
            blocked_mission_capability=value["blocked_mission_capability"],
            condition_kind=value["condition_kind"],
            dependency_id=value["dependency_id"],
            dependency_kind=value["dependency_kind"],
            required_external_change=value["required_external_change"],
            resume_action=ExternalResumeAction.from_identity_payload(
                value["resume_action"]
            ),
            validation_plan_hash=value["validation_plan_hash"],
            validator_id=value["validator_id"],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalRecoveryPath:
    recovery_kind: str
    recovery_path_id: str

    def __post_init__(self) -> None:
        if self.recovery_kind not in _RECOVERY_KINDS:
            raise ExternalDependencyContractError(
                "external recovery kind is not typed"
            )
        _ascii("external recovery path id", self.recovery_path_id)

    def to_identity_payload(self) -> dict[str, str]:
        return {
            "recovery_kind": self.recovery_kind,
            "recovery_path_id": self.recovery_path_id,
            "schema": "external_recovery_path.v1",
        }

    @classmethod
    def from_identity_payload(
        cls, value: Mapping[str, Any]
    ) -> "ExternalRecoveryPath":
        if not isinstance(value, Mapping):
            raise ExternalDependencyContractError(
                "external recovery path payload must be a mapping"
            )
        _exact_keys(
            "external recovery path",
            value,
            {"recovery_kind", "recovery_path_id", "schema"},
        )
        if value.get("schema") != "external_recovery_path.v1":
            raise ExternalDependencyContractError(
                "external recovery path schema is invalid"
            )
        return cls(
            recovery_kind=value["recovery_kind"],
            recovery_path_id=value["recovery_path_id"],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalRecoveryPlan:
    boundary_event_id: str
    condition: ExternalResumeCondition
    paths: tuple[ExternalRecoveryPath, ...]
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _digest("external recovery boundary event", self.boundary_event_id)
        if not isinstance(self.condition, ExternalResumeCondition):
            raise ExternalDependencyContractError(
                "external recovery plan requires a typed resume condition"
            )
        if type(self.paths) is not tuple or not self.paths or any(
            not isinstance(item, ExternalRecoveryPath) for item in self.paths
        ):
            raise ExternalDependencyContractError(
                "external recovery plan paths must be a non-empty typed tuple"
            )
        path_ids = [item.recovery_path_id for item in self.paths]
        kinds = {item.recovery_kind for item in self.paths}
        if len(path_ids) != len(set(path_ids)):
            raise ExternalDependencyContractError(
                "external recovery plan paths must be unique"
            )
        if not _REQUIRED_RECOVERY_KINDS.issubset(kinds):
            raise ExternalDependencyContractError(
                "external recovery plan must include probe, local recovery, and substitute search"
            )
        object.__setattr__(
            self,
            "identity",
            "external-recovery-plan:"
            + canonical_digest(
                domain="external-recovery-plan",
                payload=self.to_identity_payload(),
            ),
        )

    def path(self, recovery_path_id: str) -> ExternalRecoveryPath:
        for item in self.paths:
            if item.recovery_path_id == recovery_path_id:
                return item
        raise ExternalDependencyContractError(
            "external recovery path is outside its frozen plan"
        )

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "boundary_event_id": self.boundary_event_id,
            "condition": self.condition.to_identity_payload(),
            "paths": [item.to_identity_payload() for item in self.paths],
            "schema": "external_recovery_plan.v1",
        }

    @classmethod
    def from_identity_payload(
        cls, value: Mapping[str, Any]
    ) -> "ExternalRecoveryPlan":
        if not isinstance(value, Mapping):
            raise ExternalDependencyContractError(
                "external recovery plan payload must be a mapping"
            )
        _exact_keys(
            "external recovery plan",
            value,
            {"boundary_event_id", "condition", "paths", "schema"},
        )
        if value.get("schema") != "external_recovery_plan.v1":
            raise ExternalDependencyContractError(
                "external recovery plan schema is invalid"
            )
        raw_paths = value.get("paths")
        if not isinstance(raw_paths, Sequence) or isinstance(raw_paths, (str, bytes)):
            raise ExternalDependencyContractError(
                "external recovery plan paths are invalid"
            )
        return cls(
            boundary_event_id=value["boundary_event_id"],
            condition=ExternalResumeCondition.from_identity_payload(
                value["condition"]
            ),
            paths=tuple(
                ExternalRecoveryPath.from_identity_payload(item)
                for item in raw_paths
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalChangeEvidence:
    """Durable artifacts offered to the exact blocked-Mission validator."""

    condition_id: str
    result_manifest_output: str
    output_manifest: tuple[tuple[str, str], ...]
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        _digest(
            "external resume condition id",
            self.condition_id,
            prefix="external-resume-condition:",
        )
        result_name = _ascii(
            "external change result output", self.result_manifest_output
        )
        if type(self.output_manifest) is not tuple or len(self.output_manifest) < 2:
            raise ExternalDependencyContractError(
                "external change evidence requires result and measurement artifacts"
            )
        outputs = tuple(
            sorted(
                (
                    _ascii("external change output name", name),
                    _digest("external change output hash", artifact_hash),
                )
                for name, artifact_hash in self.output_manifest
            )
        )
        names = [name for name, _artifact_hash in outputs]
        hashes = [artifact_hash for _name, artifact_hash in outputs]
        if (
            len(names) != len(set(names))
            or len(hashes) != len(set(hashes))
            or result_name not in names
        ):
            raise ExternalDependencyContractError(
                "external change outputs are duplicated or omit the result"
            )
        object.__setattr__(self, "output_manifest", outputs)
        object.__setattr__(
            self,
            "identity",
            "external-change-evidence:"
            + canonical_digest(
                domain="external-change-evidence",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "output_manifest": [
                {"name": name, "sha256": artifact_hash}
                for name, artifact_hash in self.output_manifest
            ],
            "result_manifest_output": self.result_manifest_output,
            "schema": "external_change_evidence_binding.v1",
        }


def external_plan_from_binding(binding: Mapping[str, Any]) -> ExternalRecoveryPlan:
    """Parse and cross-check the exact Job binding for one frozen plan path."""

    if not isinstance(binding, Mapping):
        raise ExternalDependencyContractError(
            "external dependency binding must be a mapping"
        )
    _exact_keys(
        "external dependency binding",
        binding,
        {
            "blocked_mission_capability",
            "dependency_id",
            "dependency_kind",
            "exact_resume_action",
            "recovery_kind",
            "recovery_path_id",
            "recovery_plan",
            "result_manifest_output",
            "required_external_change",
            "validation_plan_hash",
            "validator_id",
        },
    )
    plan = ExternalRecoveryPlan.from_identity_payload(binding["recovery_plan"])
    if binding["recovery_plan"] != plan.to_identity_payload():
        raise ExternalDependencyContractError(
            "external recovery plan payload is not canonical"
        )
    condition = plan.condition
    path = plan.path(binding["recovery_path_id"])
    expected = {
        "blocked_mission_capability": condition.blocked_mission_capability,
        "dependency_id": condition.dependency_id,
        "dependency_kind": condition.dependency_kind,
        "recovery_kind": path.recovery_kind,
        "required_external_change": condition.required_external_change,
        "validation_plan_hash": condition.validation_plan_hash,
        "validator_id": condition.validator_id,
    }
    if any(binding.get(name) != value for name, value in expected.items()):
        raise ExternalDependencyContractError(
            "external dependency binding differs from its frozen recovery plan"
        )
    _ascii("external exact Job resume action", binding["exact_resume_action"])
    _ascii("external result manifest output", binding["result_manifest_output"])
    return plan


__all__ = [
    "ExternalChangeEvidence",
    "ExternalDependencyContractError",
    "ExternalRecoveryPath",
    "ExternalRecoveryPlan",
    "ExternalResumeAction",
    "ExternalResumeCondition",
    "external_plan_from_binding",
]
