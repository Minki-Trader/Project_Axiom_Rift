"""Stable component and executable identity primitives."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from hashlib import sha256

from .canonical import CanonicalValue, canonical_bytes, parse_canonical


CANONICAL_IDENTITY_PREFIX = b"axiom-rift\x00identity\x00sha256\x00v1\x00"
_COMPONENT_SCHEMA = "component_spec.v1"
_EXECUTABLE_SCHEMA = "executable_spec.v1"


def _ascii_text(name: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be str")
    if not value:
        raise ValueError(f"{name} must not be empty")
    if not value.isascii():
        raise ValueError(f"{name} must be ASCII")
    return value


def _ascii_tuple(
    name: str,
    values: object,
    *,
    allow_empty: bool,
    ordered: bool,
) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{name} must be tuple[str, ...]")
    normalized = tuple(
        _ascii_text(f"{name}[{index}]", value)
        for index, value in enumerate(values)
    )
    if not allow_empty and not normalized:
        raise ValueError(f"{name} must not be empty")
    if not ordered:
        if len(set(normalized)) != len(normalized):
            raise ValueError(f"{name} must not contain duplicates")
        normalized = tuple(sorted(normalized))
    return normalized


def canonical_identity_bytes(*, domain: str, payload: object) -> bytes:
    """Return the deterministic domain-framed bytes used by identities."""

    domain_bytes = _ascii_text("domain", domain).encode("ascii")
    if len(domain_bytes) > 0xFFFFFFFF:
        raise ValueError("domain is too long")
    return (
        CANONICAL_IDENTITY_PREFIX
        + len(domain_bytes).to_bytes(4, "big")
        + domain_bytes
        + canonical_bytes(payload)
    )


def parse_canonical_identity_bytes(
    document: bytes,
) -> tuple[str, CanonicalValue]:
    """Parse one exact identity frame and reject every noncanonical byte."""

    if type(document) is not bytes:
        raise TypeError("identity document must be bytes")
    length_offset = len(CANONICAL_IDENTITY_PREFIX)
    domain_offset = length_offset + 4
    if not document.startswith(CANONICAL_IDENTITY_PREFIX):
        raise ValueError("identity document prefix is invalid")
    if len(document) < domain_offset:
        raise ValueError("identity document is truncated before domain length")
    domain_length = int.from_bytes(
        document[length_offset:domain_offset], "big"
    )
    payload_offset = domain_offset + domain_length
    if len(document) <= payload_offset:
        raise ValueError("identity document domain or payload is truncated")
    try:
        domain = document[domain_offset:payload_offset].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("identity document domain must be ASCII") from exc
    _ascii_text("domain", domain)
    payload = parse_canonical(document[payload_offset:])
    if canonical_identity_bytes(domain=domain, payload=payload) != document:
        raise ValueError("identity document is not canonical")
    return domain, payload


def canonical_digest(*, domain: str, payload: object) -> str:
    """Return a domain-separated SHA-256 digest of a canonical payload."""

    return sha256(
        canonical_identity_bytes(domain=domain, payload=payload)
    ).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class ComponentSpec:
    """A component identity scoped only to its own semantic surface."""

    display_name: str = field(compare=False)
    protocol: str = field(compare=False)
    implementation: str = field(compare=False)
    spec: InitVar[object]
    semantic_dependencies: tuple[str, ...] = field(default=(), compare=False)
    _spec_bytes: bytes = field(init=False, repr=False, compare=False)
    identity: str = field(init=False)

    def __post_init__(self, spec: object) -> None:
        _ascii_text("display_name", self.display_name)
        _ascii_text("protocol", self.protocol)
        _ascii_text("implementation", self.implementation)
        dependencies = _ascii_tuple(
            "semantic_dependencies",
            self.semantic_dependencies,
            allow_empty=True,
            ordered=False,
        )
        spec_bytes = canonical_bytes(spec)
        object.__setattr__(self, "semantic_dependencies", dependencies)
        object.__setattr__(self, "_spec_bytes", spec_bytes)
        digest = canonical_digest(domain="component", payload=self.to_identity_payload())
        object.__setattr__(self, "identity", f"component:{digest}")

    @property
    def component_id(self) -> str:
        return self.identity

    def specification(self) -> CanonicalValue:
        """Return a detached copy of the frozen semantic specification."""

        return parse_canonical(self._spec_bytes)

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "implementation": self.implementation,
            "protocol": self.protocol,
            "schema": _COMPONENT_SCHEMA,
            "semantic_dependencies": list(self.semantic_dependencies),
            "spec": self.specification(),
        }

    def renamed(self, display_name: str) -> ComponentSpec:
        return ComponentSpec(
            display_name=display_name,
            protocol=self.protocol,
            implementation=self.implementation,
            spec=self.specification(),
            semantic_dependencies=self.semantic_dependencies,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutableSpec:
    """An immutable identity for one exact executable scientific path."""

    display_name: str = field(compare=False)
    components: tuple[ComponentSpec, ...] = field(compare=False, repr=False)
    component_identities: tuple[str, ...] = field(init=False, compare=False)
    parameters: InitVar[object]
    data_contract: str = field(compare=False)
    split_contract: str = field(compare=False)
    clock_contract: str = field(compare=False)
    cost_contract: str = field(compare=False)
    engine_contract: str = field(compare=False)
    source_contracts: tuple[str, ...] = field(default=(), compare=False)
    _parameter_bytes: bytes = field(init=False, repr=False, compare=False)
    identity: str = field(init=False)

    def __post_init__(self, parameters: object) -> None:
        _ascii_text("display_name", self.display_name)
        if (
            type(self.components) is not tuple
            or not self.components
            or any(not isinstance(component, ComponentSpec) for component in self.components)
        ):
            raise ValueError("components must be a non-empty tuple of ComponentSpec")
        composition = tuple(component.identity for component in self.components)
        if len(set(composition)) != len(composition):
            raise ValueError("Executable components must be unique")
        _ascii_text("data_contract", self.data_contract)
        _ascii_text("split_contract", self.split_contract)
        _ascii_text("clock_contract", self.clock_contract)
        _ascii_text("cost_contract", self.cost_contract)
        _ascii_text("engine_contract", self.engine_contract)
        sources = _ascii_tuple(
            "source_contracts",
            self.source_contracts,
            allow_empty=True,
            ordered=False,
        )
        declared_source_dependencies = {
            dependency
            for component in self.components
            for dependency in component.semantic_dependencies
            if dependency.startswith("source:")
        }
        if declared_source_dependencies != set(sources):
            raise ValueError(
                "source_contracts must exactly match component source dependencies"
            )
        for source in sources:
            digest = source.removeprefix("source:")
            if (
                not source.startswith("source:")
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError("source_contracts must contain SourceContract identities")
        parameter_bytes = canonical_bytes(parameters)
        object.__setattr__(self, "component_identities", composition)
        object.__setattr__(self, "source_contracts", sources)
        object.__setattr__(self, "_parameter_bytes", parameter_bytes)
        digest = canonical_digest(domain="executable", payload=self.to_identity_payload())
        object.__setattr__(self, "identity", f"executable:{digest}")

    @property
    def executable_id(self) -> str:
        return self.identity

    def parameter_values(self) -> CanonicalValue:
        """Return a detached copy of the frozen parameter payload."""

        return parse_canonical(self._parameter_bytes)

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "clock_contract": self.clock_contract,
            "component_identities": list(self.component_identities),
            "component_manifests": [
                component.to_identity_payload() for component in self.components
            ],
            "cost_contract": self.cost_contract,
            "data_contract": self.data_contract,
            "engine_contract": self.engine_contract,
            "parameters": self.parameter_values(),
            "schema": _EXECUTABLE_SCHEMA,
            "source_contracts": list(self.source_contracts),
            "split_contract": self.split_contract,
        }

    def renamed(self, display_name: str) -> ExecutableSpec:
        return ExecutableSpec(
            display_name=display_name,
            components=self.components,
            parameters=self.parameter_values(),
            data_contract=self.data_contract,
            split_contract=self.split_contract,
            clock_contract=self.clock_contract,
            cost_contract=self.cost_contract,
            engine_contract=self.engine_contract,
            source_contracts=self.source_contracts,
        )
