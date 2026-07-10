"""Synthetic-safe callable program dispatch for the future V2 research epoch.

This module is deliberately independent from the existing market-data scout.
It proves callable registration, implementation hashing, complete bundle
identity, and pure sequential dispatch without creating scientific evidence or
mutating active state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import inspect
import json
import re
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from axiom_rift.v2.identity import sha256_payload


PROGRAM_KINDS = (
    "feature",
    "label",
    "model",
    "calibration",
    "selector",
    "trade",
    "sizing",
    "portfolio_risk",
)
PROGRAM_ID_PATTERNS = {
    "feature": re.compile(r"^V2FP[0-9]{4}$"),
    "label": re.compile(r"^V2LP[0-9]{4}$"),
    "model": re.compile(r"^V2MP[0-9]{4}$"),
    "calibration": re.compile(r"^V2CP[0-9]{4}$"),
    "selector": re.compile(r"^V2SEL[0-9]{4}$"),
    "trade": re.compile(r"^V2TP[0-9]{4}$"),
    "sizing": re.compile(r"^V2SZ[0-9]{4}$"),
    "portfolio_risk": re.compile(r"^V2PR[0-9]{4}$"),
}
SCOUT_MODES = frozenset({"s_breadth", "s_depth", "s_synthesis"})
ALLOWED_STAGES = frozenset({"H", "S", "R", "P", "M"})


class ProgramDispatchError(ValueError):
    """Raised when callable or program identity is not deterministic and safe."""


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _ascii_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ProgramDispatchError(f"payload is not canonical ASCII JSON: {exc}") from exc


def callable_sha256(adapter: Callable[..., Any]) -> str:
    """Hash callable source and stable identity without importing from data."""

    if not callable(adapter):
        raise ProgramDispatchError("program adapter must be callable")
    try:
        source = inspect.getsource(adapter).replace("\r\n", "\n")
    except (OSError, TypeError) as exc:
        raise ProgramDispatchError("program adapter source must be inspectable") from exc
    try:
        source_bytes = source.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ProgramDispatchError("program adapter source must be ASCII") from exc
    identity = {
        "module": getattr(adapter, "__module__", ""),
        "qualname": getattr(adapter, "__qualname__", ""),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
    }
    return hashlib.sha256(_ascii_json(identity)).hexdigest()


@runtime_checkable
class ProgramAdapter(Protocol):
    """A pure callable used by the generic synthetic dispatch proof."""

    def __call__(
        self,
        payload: Mapping[str, Any],
        parameters: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ProgramDefinition:
    program_id: str
    kind: str
    implementation_key: str
    implementation_sha256: str
    contract_sha256: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    input_schema: str = "mapping"
    output_schema: str = "mapping"
    causal_requirements: tuple[str, ...] = ()
    portability_status: str = "unproven"
    onnx_requirement: str = "not_assessed"
    mql_requirement: str = "not_assessed"
    fixture_only: bool = False

    def __post_init__(self) -> None:
        pattern = PROGRAM_ID_PATTERNS.get(self.kind)
        if pattern is None or pattern.fullmatch(self.program_id) is None:
            raise ProgramDispatchError(
                f"program id does not match kind: {self.kind}={self.program_id}"
            )
        if not self.implementation_key or not re.fullmatch(
            r"[a-z][a-z0-9_]*", self.implementation_key
        ):
            raise ProgramDispatchError("implementation_key must be a safe identifier")
        for label, value in (
            ("implementation_sha256", self.implementation_sha256),
            ("contract_sha256", self.contract_sha256),
        ):
            if not _is_sha256(value):
                raise ProgramDispatchError(f"{label} must be a lowercase sha256")
        if not isinstance(self.parameters, Mapping):
            raise ProgramDispatchError("program parameters must be a mapping")
        _ascii_json(dict(self.parameters))
        for label, value in (
            ("input_schema", self.input_schema),
            ("output_schema", self.output_schema),
            ("portability_status", self.portability_status),
            ("onnx_requirement", self.onnx_requirement),
            ("mql_requirement", self.mql_requirement),
        ):
            if not isinstance(value, str) or not value:
                raise ProgramDispatchError(f"{label} must be nonempty")
        if not all(isinstance(value, str) and value for value in self.causal_requirements):
            raise ProgramDispatchError("causal requirements must be nonempty strings")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(self, "causal_requirements", tuple(self.causal_requirements))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_program_definition_v2",
            "program_id": self.program_id,
            "kind": self.kind,
            "implementation_key": self.implementation_key,
            "implementation_sha256": self.implementation_sha256,
            "contract_sha256": self.contract_sha256,
            "parameters": dict(self.parameters),
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "causal_requirements": list(self.causal_requirements),
            "portability_status": self.portability_status,
            "onnx_requirement": self.onnx_requirement,
            "mql_requirement": self.mql_requirement,
            "fixture_only": self.fixture_only,
        }

    def executable_payload(self) -> dict[str, Any]:
        """Return semantic executable identity without the assigned program id."""

        payload = self.identity_payload()
        payload.pop("program_id")
        payload["schema"] = "axiom_rift_v2_program_executable_v1"
        return payload

    @property
    def program_sha256(self) -> str:
        return sha256_payload(self.identity_payload())

    @property
    def executable_sha256(self) -> str:
        return sha256_payload(self.executable_payload())


@dataclass(frozen=True)
class JITRegistrationReceipt:
    program_id: str
    implementation_key: str
    implementation_sha256: str
    contract_sha256: str
    fixture_checks_passed: bool
    causality_checks_passed: bool
    interface_checks_passed: bool
    evidence_jobs_launched: bool = False
    claim_ceiling: str = "none"

    def validate_for(self, definition: ProgramDefinition) -> None:
        expected = {
            "program_id": definition.program_id,
            "implementation_key": definition.implementation_key,
            "implementation_sha256": definition.implementation_sha256,
            "contract_sha256": definition.contract_sha256,
        }
        observed = {key: getattr(self, key) for key in expected}
        if observed != expected:
            raise ProgramDispatchError("JIT receipt identity differs from program definition")
        if not (
            self.fixture_checks_passed
            and self.causality_checks_passed
            and self.interface_checks_passed
        ):
            raise ProgramDispatchError("JIT registration requires all cheap checks to pass")
        if self.evidence_jobs_launched:
            raise ProgramDispatchError("JIT harness proof may not launch evidence jobs")
        if self.claim_ceiling != "none":
            raise ProgramDispatchError("JIT registration receipt cannot create a claim")


@dataclass(frozen=True)
class ProgramBundle:
    programs: Mapping[str, ProgramDefinition]
    external_source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if set(self.programs) != set(PROGRAM_KINDS):
            raise ProgramDispatchError("program bundle must contain all eight program kinds")
        normalized: dict[str, ProgramDefinition] = {}
        for kind in PROGRAM_KINDS:
            definition = self.programs[kind]
            if not isinstance(definition, ProgramDefinition) or definition.kind != kind:
                raise ProgramDispatchError(f"program bundle kind mismatch: {kind}")
            if definition.fixture_only:
                raise ProgramDispatchError("fixture-only programs cannot enter an active bundle")
            normalized[kind] = definition
        sources = tuple(dict.fromkeys(self.external_source_ids))
        if not all(isinstance(value, str) and value for value in sources):
            raise ProgramDispatchError("external source ids must be nonempty strings")
        object.__setattr__(self, "programs", MappingProxyType(normalized))
        object.__setattr__(self, "external_source_ids", sources)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_program_bundle_v1",
            "programs": {
                kind: {
                    "program_id": self.programs[kind].program_id,
                    "program_sha256": self.programs[kind].program_sha256,
                }
                for kind in PROGRAM_KINDS
            },
            "external_source_ids": list(self.external_source_ids),
        }

    @property
    def bundle_sha256(self) -> str:
        return sha256_payload(self.identity_payload())


class CallableProgramRegistry:
    """In-memory proof registry; durable mutation remains the writer's job."""

    def __init__(self) -> None:
        self._callables: dict[str, tuple[ProgramAdapter, str]] = {}
        self._programs: dict[str, ProgramDefinition] = {}

    @property
    def program_count(self) -> int:
        return len(self._programs)

    def program_definitions(self) -> tuple[ProgramDefinition, ...]:
        return tuple(self._programs[key] for key in sorted(self._programs))

    def register_callable(
        self,
        implementation_key: str,
        adapter: ProgramAdapter,
        *,
        expected_sha256: str,
    ) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", implementation_key):
            raise ProgramDispatchError("implementation key is not safe")
        if not _is_sha256(expected_sha256):
            raise ProgramDispatchError("expected callable hash is invalid")
        observed = callable_sha256(adapter)
        if observed != expected_sha256:
            raise ProgramDispatchError("callable implementation hash mismatch")
        existing = self._callables.get(implementation_key)
        if existing is not None and existing[1] != observed:
            raise ProgramDispatchError("implementation key is already bound to different code")
        self._callables[implementation_key] = (adapter, observed)
        return observed

    def register_program(
        self,
        definition: ProgramDefinition,
        receipt: JITRegistrationReceipt,
    ) -> ProgramDefinition:
        receipt.validate_for(definition)
        registered = self._callables.get(definition.implementation_key)
        if registered is None:
            raise ProgramDispatchError("program implementation is not in the safe callable catalog")
        if registered[1] != definition.implementation_sha256:
            raise ProgramDispatchError("registered callable hash differs from program definition")
        existing = self._programs.get(definition.program_id)
        if existing is not None:
            if existing.program_sha256 == definition.program_sha256:
                return existing
            raise ProgramDispatchError("program id is already registered with different identity")
        duplicate = next(
            (
                row
                for row in self._programs.values()
                if row.kind == definition.kind
                and row.executable_sha256 == definition.executable_sha256
            ),
            None,
        )
        if duplicate is not None:
            raise ProgramDispatchError("renaming an identical program does not create novelty")
        self._programs[definition.program_id] = definition
        return definition

    def jit_register(
        self,
        definition: ProgramDefinition,
        adapter: ProgramAdapter,
        receipt: JITRegistrationReceipt,
    ) -> ProgramDefinition:
        self.register_callable(
            definition.implementation_key,
            adapter,
            expected_sha256=definition.implementation_sha256,
        )
        return self.register_program(definition, receipt)

    def resolve(self, program_id: str, *, kind: str) -> ProgramDefinition:
        definition = self._programs.get(program_id)
        if definition is None:
            raise ProgramDispatchError(f"program is not registered: {program_id}")
        if definition.kind != kind:
            raise ProgramDispatchError(f"program kind mismatch: {program_id}")
        return definition

    def make_bundle(
        self,
        program_ids: Mapping[str, str],
        *,
        external_source_ids: tuple[str, ...] = (),
    ) -> ProgramBundle:
        if set(program_ids) != set(PROGRAM_KINDS):
            raise ProgramDispatchError("bundle program ids must cover all eight kinds")
        return ProgramBundle(
            {
                kind: self.resolve(program_ids[kind], kind=kind)
                for kind in PROGRAM_KINDS
            },
            external_source_ids=external_source_ids,
        )

    def adapter_for(self, definition: ProgramDefinition) -> ProgramAdapter:
        registered = self._callables.get(definition.implementation_key)
        if registered is None or registered[1] != definition.implementation_sha256:
            raise ProgramDispatchError("callable is absent or its identity changed")
        return registered[0]


@dataclass(frozen=True)
class ProgramRunResult:
    stage: str
    mode: str
    bundle_sha256: str
    outputs: Mapping[str, Mapping[str, Any]]
    result_sha256: str
    state_mutated: bool = False
    evidence_claim_created: bool = False


class GenericProgramRunner:
    """Pure sequential adapter runner used only by cheap synthetic proof."""

    def __init__(self, registry: CallableProgramRegistry) -> None:
        self.registry = registry

    def run(
        self,
        bundle: ProgramBundle,
        payload: Mapping[str, Any],
        *,
        stage: str,
        mode: str,
    ) -> ProgramRunResult:
        if stage not in ALLOWED_STAGES:
            raise ProgramDispatchError(f"unsupported stage: {stage}")
        if stage == "S" and mode not in SCOUT_MODES:
            raise ProgramDispatchError("S dispatch requires a registered Scout mode")
        if stage != "S" and mode in SCOUT_MODES:
            raise ProgramDispatchError("Scout modes cannot be used outside S")
        if not isinstance(payload, Mapping):
            raise ProgramDispatchError("runner payload must be a mapping")
        _ascii_json(dict(payload))
        current: Mapping[str, Any] = MappingProxyType(dict(payload))
        outputs: dict[str, Mapping[str, Any]] = {}
        for kind in PROGRAM_KINDS:
            definition = bundle.programs[kind]
            adapter = self.registry.adapter_for(definition)
            context = MappingProxyType(
                {
                    "stage": stage,
                    "mode": mode,
                    "kind": kind,
                    "program_id": definition.program_id,
                    "bundle_sha256": bundle.bundle_sha256,
                }
            )
            observed = adapter(current, definition.parameters, context)
            if not isinstance(observed, Mapping):
                raise ProgramDispatchError(f"{kind} adapter output must be a mapping")
            normalized = dict(observed)
            _ascii_json(normalized)
            outputs[kind] = MappingProxyType(normalized)
            current = outputs[kind]
        result_payload = {
            "schema": "axiom_rift_v2_generic_program_run_v1",
            "stage": stage,
            "mode": mode,
            "bundle_sha256": bundle.bundle_sha256,
            "outputs": {kind: dict(outputs[kind]) for kind in PROGRAM_KINDS},
            "state_mutated": False,
            "evidence_claim_created": False,
        }
        return ProgramRunResult(
            stage=stage,
            mode=mode,
            bundle_sha256=bundle.bundle_sha256,
            outputs=MappingProxyType(outputs),
            result_sha256=sha256_payload(result_payload),
        )


__all__ = [
    "ALLOWED_STAGES",
    "CallableProgramRegistry",
    "GenericProgramRunner",
    "JITRegistrationReceipt",
    "PROGRAM_ID_PATTERNS",
    "PROGRAM_KINDS",
    "ProgramAdapter",
    "ProgramBundle",
    "ProgramDefinition",
    "ProgramDispatchError",
    "ProgramRunResult",
    "SCOUT_MODES",
    "callable_sha256",
]
