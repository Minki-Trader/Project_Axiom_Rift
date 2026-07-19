"""Typed component-control and prediction-to-position chassis identities."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from axiom_rift.core.canonical import (
    CanonicalValue,
    canonical_bytes,
    parse_canonical,
)
from axiom_rift.core.component_surface import (
    ARCHITECTURE_ROLE_DOMAINS,
    ComponentManifestError,
    ComponentOutsideArchitectureError,
    architecture_component_family_surface_identity as _core_architecture_family_surface,
    architecture_component_surface_identity as _core_architecture_surface,
    component_manifest_domain as _core_component_domain,
    component_manifest_identity as _core_component_identity,
    component_manifest_surfaces,
    normalize_architecture_semantic_value as _normalize_architecture_semantic_value,
)
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec, canonical_digest
from axiom_rift.research.governance import ResearchLayer


class ChassisIdentityError(ValueError):
    """Raised when controlled component or chassis identity is ambiguous."""


class ChassisComponentOutsideArchitectureError(ChassisIdentityError):
    """A valid component is intentionally outside the architecture chassis."""


class ArchitectureRole(str, Enum):
    LABEL = "label"
    DECISION = "decision"
    ENTRY = "entry"
    LIFECYCLE = "lifecycle"
    EXECUTION = "execution"
    PORTFOLIO = "portfolio"


class ComponentParityDimension(str, Enum):
    SEMANTIC_SPEC = "semantic_spec"
    DETERMINISTIC_OUTPUT = "deterministic_output"
    BOUNDARY_BEHAVIOR = "boundary_behavior"


_REQUIRED_PARITY_DIMENSIONS = frozenset(ComponentParityDimension)
_ARCHITECTURE_ROLES = tuple(ArchitectureRole)
_ROLE_DOMAINS: dict[ArchitectureRole, frozenset[ResearchLayer]] = {
    ArchitectureRole(role): frozenset(ResearchLayer(domain) for domain in domains)
    for role, domains in ARCHITECTURE_ROLE_DOMAINS.items()
}

_ENGINE_RUNTIME_CATEGORIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mql5", re.compile(r"^(?:mql5|mqh|ea)(?:[0-9._-]|$)", re.IGNORECASE)),
    (
        "mt5",
        re.compile(r"^(?:mt5(?:build)?|metatrader)(?:[0-9._-]|$)", re.IGNORECASE),
    ),
    ("onnx", re.compile(r"^(?:onnx|onnxruntime)(?:[0-9._-]|$)", re.IGNORECASE)),
    ("python", re.compile(r"^python(?:[0-9._-]|$)", re.IGNORECASE)),
)
_ENGINE_LIBRARY_PREFIXES = (
    "jax",
    "numpy",
    "pandas",
    "scikit",
    "scipy",
    "sklearn",
    "tensorflow",
    "torch",
    "xgboost",
)
_ENGINE_NON_ARCHITECTURAL_PREFIXES = (
    "alpha",
    "artifact",
    "blocks",
    "bonferroni",
    "bootstrap",
    "bundle",
    "chassis",
    "digest",
    "hash",
    "implementation",
    "loader",
    "resample",
    "seed",
    "shared",
    "sha",
    "source_hash",
)


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ChassisIdentityError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ChassisIdentityError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _component_identity(value: object) -> str:
    text = _ascii("component identity", value)
    digest = text.removeprefix("component:")
    if not text.startswith("component:"):
        raise ChassisIdentityError("component identity must use the component namespace")
    _digest("component identity digest", digest)
    return text


def _component_manifest_identity(manifest: Mapping[str, object]) -> str:
    try:
        return _core_component_identity(manifest)
    except ComponentManifestError as exc:
        raise ChassisIdentityError(str(exc)) from exc


def _component_domain_from_manifest(
    manifest: Mapping[str, object],
) -> ResearchLayer:
    try:
        return ResearchLayer(_core_component_domain(manifest))
    except (ComponentManifestError, ValueError) as exc:
        raise ChassisIdentityError(str(exc)) from exc


def component_domain(component: ComponentSpec) -> ResearchLayer:
    if not isinstance(component, ComponentSpec):
        raise ChassisIdentityError("component must be a ComponentSpec")
    return _component_domain_from_manifest(component.to_identity_payload())


def component_semantic_surface_identity(
    component: ComponentSpec | Mapping[str, object],
) -> str:
    """Return the protocol-label-neutral surface used for duplicate guards."""

    manifest = (
        component.to_identity_payload()
        if isinstance(component, ComponentSpec)
        else component
    )
    if not isinstance(manifest, Mapping):
        raise ChassisIdentityError("component semantic surface requires a manifest")
    try:
        return component_manifest_surfaces(manifest).domain_aware
    except ComponentManifestError as exc:
        raise ChassisIdentityError(str(exc)) from exc


def _architecture_role_for_domain(domain: ResearchLayer) -> ArchitectureRole | None:
    matches = tuple(
        role for role, domains in _ROLE_DOMAINS.items() if domain in domains
    )
    if len(matches) > 1:
        raise ChassisIdentityError("research domain has ambiguous architecture roles")
    return matches[0] if matches else None


def _architecture_component_surface_identity(
    component: ComponentSpec | Mapping[str, object],
    *,
    role: ArchitectureRole,
) -> str:
    """Return a surface whose namespace is the prediction-to-position role.

    Model, calibration, and selector are all decision mechanisms. Their protocol
    prefixes therefore cannot split an otherwise identical architecture family.
    """

    manifest = (
        component.to_identity_payload()
        if isinstance(component, ComponentSpec)
        else component
    )
    if not isinstance(manifest, Mapping):
        raise ChassisIdentityError("architecture surface requires a component manifest")
    try:
        return _core_architecture_surface(manifest, role=role.value)
    except ComponentOutsideArchitectureError as exc:
        raise ChassisComponentOutsideArchitectureError(str(exc)) from exc
    except ComponentManifestError as exc:
        raise ChassisIdentityError(str(exc)) from exc


def architecture_component_semantic_surface_identity(
    component: ComponentSpec | Mapping[str, object],
) -> str:
    """Return the protocol-domain-neutral surface for one architecture role."""

    manifest = (
        component.to_identity_payload()
        if isinstance(component, ComponentSpec)
        else component
    )
    if not isinstance(manifest, Mapping):
        raise ChassisIdentityError("architecture surface requires a component manifest")
    try:
        return _core_architecture_surface(manifest)
    except ComponentOutsideArchitectureError as exc:
        raise ChassisComponentOutsideArchitectureError(str(exc)) from exc
    except ComponentManifestError as exc:
        raise ChassisIdentityError(str(exc)) from exc


def _semantic_surface(manifest: Mapping[str, object]) -> bytes:
    return canonical_bytes(
        {
            "implementation": manifest["implementation"],
            "semantic_dependencies": manifest["semantic_dependencies"],
            "spec": manifest["spec"],
        }
    )


def _normalize_component_id(
    component_id: str,
    replacements: Mapping[str, str],
) -> str:
    seen: set[str] = set()
    current = component_id
    while current in replacements:
        if current in seen:
            raise ChassisIdentityError("component equivalence contains a cycle")
        seen.add(current)
        current = replacements[current]
    return current


def _equivalence_replacements(
    equivalences: tuple[ComponentParityEvidence, ...],
) -> dict[str, str]:
    replacements: dict[str, str] = {}
    canonical_ids: set[str] = set()
    for equivalence in equivalences:
        if not isinstance(equivalence, ComponentParityEvidence):
            raise ChassisIdentityError("component equivalence is not typed")
        canonical_id = equivalence.canonical_component.identity
        equivalent_id = equivalence.equivalent_component.identity
        if canonical_id in canonical_ids:
            raise ChassisIdentityError(
                "canonical component has multiple equivalent endpoints"
            )
        if equivalent_id in replacements:
            raise ChassisIdentityError("equivalent component has multiple canonical anchors")
        replacements[equivalent_id] = canonical_id
        canonical_ids.add(canonical_id)
    if canonical_ids.intersection(replacements):
        raise ChassisIdentityError("component equivalence chains are not allowed")
    return replacements


def _manifest_registry(
    manifests: tuple[Mapping[str, object], ...],
) -> dict[str, Mapping[str, object]]:
    registry: dict[str, Mapping[str, object]] = {}
    for manifest in manifests:
        identity = _component_manifest_identity(manifest)
        prior = registry.get(identity)
        if prior is not None and canonical_bytes(prior) != canonical_bytes(manifest):
            raise ChassisIdentityError("component manifest identity collision")
        registry[identity] = manifest
    return registry


def _validate_executable_consumption(
    manifests: tuple[Mapping[str, object], ...],
) -> None:
    """Require every direct component to feed an execution/portfolio terminal.

    Exact ``component:`` dependencies bind one implementation identity. A stable
    ``role:<research-layer>`` dependency is a generic composition socket that
    consumes every current direct component in that layer without baking a Study
    ID or successor component identity into the reusable consumer.
    """

    registry = _manifest_registry(manifests)
    by_domain: dict[ResearchLayer, tuple[str, ...]] = {}
    grouped: dict[ResearchLayer, list[str]] = {}
    for component_id, manifest in registry.items():
        grouped.setdefault(_component_domain_from_manifest(manifest), []).append(
            component_id
        )
    by_domain = {
        domain: tuple(sorted(component_ids))
        for domain, component_ids in grouped.items()
    }
    source_components: dict[str, tuple[str, ...]] = {}
    for component_id in by_domain.get(ResearchLayer.DATA_SOURCE, ()):
        dependencies = registry[component_id].get("semantic_dependencies")
        if not isinstance(dependencies, list):
            raise ChassisIdentityError("component semantic dependencies are malformed")
        for dependency in dependencies:
            if isinstance(dependency, str) and dependency.startswith("source:"):
                source_components.setdefault(dependency, ())
                source_components[dependency] = tuple(
                    sorted((*source_components[dependency], component_id))
                )
    edges: dict[str, set[str]] = {component_id: set() for component_id in registry}
    consumed: set[str] = set()
    for component_id, manifest in registry.items():
        dependencies = manifest.get("semantic_dependencies")
        if not isinstance(dependencies, list):
            raise ChassisIdentityError("component semantic dependencies are malformed")
        for dependency in dependencies:
            if not isinstance(dependency, str) or not dependency.isascii():
                raise ChassisIdentityError(
                    "component semantic dependency is not canonical ASCII"
                )
            targets: tuple[str, ...] = ()
            if dependency.startswith("component:"):
                target = _component_identity(dependency)
                if target not in registry:
                    raise ChassisIdentityError(
                        "component semantic dependency is not bound to a current direct manifest"
                    )
                targets = (target,)
            elif dependency.startswith("role:"):
                try:
                    domain = ResearchLayer(dependency.removeprefix("role:"))
                except ValueError as exc:
                    raise ChassisIdentityError(
                        "component role dependency is not a ResearchLayer"
                    ) from exc
                targets = by_domain.get(domain, ())
                if not targets:
                    raise ChassisIdentityError(
                        "component role dependency has no current direct component"
                    )
            elif dependency.startswith("source:"):
                if (
                    _component_domain_from_manifest(manifest)
                    is ResearchLayer.DATA_SOURCE
                ):
                    continue
                targets = source_components.get(dependency, ())
            else:
                # Other typed external semantic identities remain part of the
                # ComponentSpec surface but do not name an in-Executable node.
                continue
            if component_id in targets:
                raise ChassisIdentityError("component consumption graph has a self-cycle")
            edges[component_id].update(targets)
            consumed.update(targets)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(component_id: str) -> None:
        if component_id in visited:
            return
        if component_id in visiting:
            raise ChassisIdentityError("component consumption graph has a cycle")
        visiting.add(component_id)
        for dependency_id in edges[component_id]:
            visit(dependency_id)
        visiting.remove(component_id)
        visited.add(component_id)

    for component_id in registry:
        visit(component_id)

    terminals = set(registry) - consumed
    if not terminals:
        raise ChassisIdentityError("component consumption graph has no terminal")
    if len(terminals) != 1:
        raise ChassisIdentityError(
            "component consumption graph requires one explicit final terminal"
        )
    allowed_terminal_roles = {
        ArchitectureRole.EXECUTION,
        ArchitectureRole.PORTFOLIO,
    }
    for terminal in terminals:
        role = _architecture_role_for_domain(
            _component_domain_from_manifest(registry[terminal])
        )
        if role not in allowed_terminal_roles:
            raise ChassisIdentityError(
                "component consumption terminal must be execution or portfolio"
            )
    reachable: set[str] = set()

    def collect(component_id: str) -> None:
        if component_id in reachable:
            return
        reachable.add(component_id)
        for dependency_id in edges[component_id]:
            collect(dependency_id)

    for terminal in terminals:
        collect(terminal)
    if reachable != set(registry):
        raise ChassisIdentityError(
            "every direct component must be consumed by the prediction-to-position path"
        )


def executable_semantic_surface_identity(
    executable: ExecutableSpec | Mapping[str, object],
) -> str:
    """Return an ordered Executable identity with protocol labels removed."""

    payload = (
        executable.to_identity_payload()
        if isinstance(executable, ExecutableSpec)
        else executable
    )
    if not isinstance(payload, Mapping) or payload.get("schema") != "executable_spec.v1":
        raise ChassisIdentityError("Executable semantic surface payload is invalid")
    component_ids = payload.get("component_identities")
    manifests = payload.get("component_manifests")
    if (
        not isinstance(component_ids, list)
        or not isinstance(manifests, list)
        or len(component_ids) != len(manifests)
        or not component_ids
    ):
        raise ChassisIdentityError("Executable component manifests are malformed")
    typed_manifests: list[Mapping[str, object]] = []
    for component_id, manifest in zip(component_ids, manifests, strict=True):
        if not isinstance(manifest, Mapping):
            raise ChassisIdentityError("Executable component manifest is malformed")
        if _component_manifest_identity(manifest) != _component_identity(component_id):
            raise ChassisIdentityError(
                "Executable component identity differs from its manifest"
            )
        typed_manifests.append(manifest)
    registry = _manifest_registry(tuple(typed_manifests))
    visiting: set[str] = set()
    surfaces: dict[str, str] = {}

    def surface(component_id: str) -> str:
        prior = surfaces.get(component_id)
        if prior is not None:
            return prior
        if component_id in visiting:
            raise ChassisIdentityError("Executable semantic dependency graph has a cycle")
        manifest = registry.get(component_id)
        if manifest is None:
            raise ChassisIdentityError(
                "Executable semantic dependency is not bound to a direct manifest"
            )
        _component_domain_from_manifest(manifest)
        visiting.add(component_id)
        dependencies = manifest.get("semantic_dependencies")
        if not isinstance(dependencies, list):
            raise ChassisIdentityError("component semantic dependencies are malformed")
        normalized_dependencies: list[str] = []
        for dependency in dependencies:
            if not isinstance(dependency, str) or not dependency.isascii():
                raise ChassisIdentityError(
                    "component semantic dependency is not canonical ASCII"
                )
            normalized_dependencies.append(
                surface(_component_identity(dependency))
                if dependency.startswith("component:")
                else dependency
            )
        normalized_dependencies.sort()
        value = "component-surface:" + canonical_digest(
            domain="component-semantic-surface",
            payload={
                "domain": _component_domain_from_manifest(manifest).value,
                "implementation": manifest["implementation"],
                "schema": "component_semantic_surface.v2",
                "semantic_dependencies": normalized_dependencies,
                "spec": manifest["spec"],
            },
        )
        visiting.remove(component_id)
        surfaces[component_id] = value
        return value

    ordered_surfaces = [surface(_component_identity(value)) for value in component_ids]
    required_fields = (
        "clock_contract",
        "cost_contract",
        "data_contract",
        "engine_contract",
        "parameters",
        "source_contracts",
        "split_contract",
    )
    if any(name not in payload for name in required_fields):
        raise ChassisIdentityError("Executable semantic surface is incomplete")
    return "executable-surface:" + canonical_digest(
        domain="executable-semantic-surface",
        payload={
            "clock_contract": payload["clock_contract"],
            "component_semantic_surfaces": ordered_surfaces,
            "cost_contract": payload["cost_contract"],
            "data_contract": payload["data_contract"],
            "engine_contract": payload["engine_contract"],
            "parameters": payload["parameters"],
            "schema": "executable_semantic_surface.v1",
            "source_contracts": payload["source_contracts"],
            "split_contract": payload["split_contract"],
        },
    )


def _semantic_component_domains(
    *,
    root_ids: tuple[str, ...],
    registry: Mapping[str, Mapping[str, object]],
) -> dict[ResearchLayer, tuple[str, ...]]:
    collected: dict[ResearchLayer, set[str]] = {}
    visited: set[str] = set()

    def visit(component_id: str) -> None:
        if component_id in visited:
            return
        manifest = registry.get(component_id)
        if manifest is None:
            raise ChassisIdentityError(
                "component semantic dependency is not bound to an exact manifest"
            )
        visited.add(component_id)
        domain = _component_domain_from_manifest(manifest)
        collected.setdefault(domain, set()).add(component_id)
        dependencies = manifest.get("semantic_dependencies")
        if not isinstance(dependencies, list):
            raise ChassisIdentityError("component semantic dependencies are malformed")
        for dependency in dependencies:
            if isinstance(dependency, str) and dependency.startswith("component:"):
                visit(_component_identity(dependency))

    for root_id in root_ids:
        visit(root_id)
    return {
        domain: tuple(sorted(component_ids))
        for domain, component_ids in collected.items()
    }


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchitectureRoleSpec:
    role: ArchitectureRole
    components: tuple[ComponentSpec, ...] = field(repr=False)
    parameter_bindings: tuple[tuple[str, CanonicalValue], ...] = ()
    boundary_bindings: tuple[tuple[str, str], ...] = ()
    component_identities: tuple[str, ...] = field(init=False)
    component_semantic_surfaces: tuple[str, ...] = field(init=False)
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.role, ArchitectureRole):
            raise ChassisIdentityError("architecture role is not typed")
        if type(self.components) is not tuple or any(
            not isinstance(value, ComponentSpec) for value in self.components
        ):
            raise ChassisIdentityError("architecture role components are not typed")
        if any(
            component_domain(component) not in _ROLE_DOMAINS[self.role]
            for component in self.components
        ):
            raise ChassisIdentityError(
                "architecture component is assigned to the wrong semantic role"
            )
        component_ids = tuple(sorted(component.identity for component in self.components))
        if len(set(component_ids)) != len(component_ids):
            raise ChassisIdentityError("architecture role components must be unique")
        semantic_surfaces = tuple(
            sorted(
                _architecture_component_surface_identity(component, role=self.role)
                for component in self.components
            )
        )
        if len(set(semantic_surfaces)) != len(semantic_surfaces):
            raise ChassisIdentityError(
                "architecture role cannot contain protocol-only component aliases"
            )
        if not component_ids and self.role is not ArchitectureRole.PORTFOLIO:
            raise ChassisIdentityError(
                "architecture role requires exact component identities"
            )
        if type(self.parameter_bindings) is not tuple:
            raise ChassisIdentityError("architecture parameter bindings must be a tuple")
        parameter_names: set[str] = set()
        parameters: list[tuple[str, CanonicalValue]] = []
        for value in self.parameter_bindings:
            if type(value) is not tuple or len(value) != 2:
                raise ChassisIdentityError("architecture parameter binding is malformed")
            name = _ascii("architecture parameter name", value[0])
            if name in parameter_names:
                raise ChassisIdentityError("architecture parameters must be unique")
            parameter_names.add(name)
            parameters.append((name, parse_canonical(canonical_bytes(value[1]))))
        parameters.sort(key=lambda value: value[0])
        if type(self.boundary_bindings) is not tuple:
            raise ChassisIdentityError("architecture boundary bindings must be a tuple")
        boundaries: list[tuple[str, str]] = []
        boundary_names: set[str] = set()
        for value in self.boundary_bindings:
            if type(value) is not tuple or len(value) != 2:
                raise ChassisIdentityError("architecture boundary binding is malformed")
            name = _ascii("architecture boundary name", value[0])
            binding = _ascii("architecture boundary identity", value[1])
            if name in boundary_names:
                raise ChassisIdentityError("architecture boundaries must be unique")
            boundary_names.add(name)
            boundaries.append((name, binding))
        boundaries.sort(key=lambda value: value[0])
        object.__setattr__(self, "component_identities", component_ids)
        object.__setattr__(
            self, "component_semantic_surfaces", semantic_surfaces
        )
        object.__setattr__(self, "parameter_bindings", tuple(parameters))
        object.__setattr__(self, "boundary_bindings", tuple(boundaries))
        object.__setattr__(
            self,
            "identity",
            "architecture-role:"
            + canonical_digest(
                domain="architecture-role",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "absence": "none" if not self.component_identities else None,
            "boundary_bindings": {
                name: value for name, value in self.boundary_bindings
            },
            "component_semantic_surfaces": list(
                self.component_semantic_surfaces
            ),
            "parameter_bindings": {
                name: value for name, value in self.parameter_bindings
            },
            "role": self.role.value,
            "schema": "architecture_role.v3",
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchitectureChassisSpec:
    label: ArchitectureRoleSpec
    decision: ArchitectureRoleSpec
    entry: ArchitectureRoleSpec
    lifecycle: ArchitectureRoleSpec
    execution: ArchitectureRoleSpec
    portfolio: ArchitectureRoleSpec
    _component_context: tuple[ComponentSpec, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        if any(
            not isinstance(getattr(self, role.value), ArchitectureRoleSpec)
            for role in _ARCHITECTURE_ROLES
        ):
            raise ChassisIdentityError("architecture chassis roles are not typed")
        if type(self._component_context) is not tuple or any(
            not isinstance(component, ComponentSpec)
            for component in self._component_context
        ):
            raise ChassisIdentityError(
                "architecture prospective component context is not typed"
            )
        context_ids = tuple(
            component.identity for component in self._component_context
        )
        if len(set(context_ids)) != len(context_ids):
            raise ChassisIdentityError(
                "architecture prospective component context must be unique"
            )
        role_component_ids = {
            component.identity
            for role in _ARCHITECTURE_ROLES
            for component in getattr(self, role.value).components
        }
        if context_ids and not role_component_ids.issubset(context_ids):
            raise ChassisIdentityError(
                "architecture prospective context omits a role component"
            )
        object.__setattr__(
            self,
            "identity",
            "architecture-family:"
            + canonical_digest(
                domain="architecture-chassis",
                payload=self.to_identity_payload(),
            ),
        )

    @classmethod
    def from_executable(
        cls,
        executable: ExecutableSpec,
    ) -> ArchitectureChassisSpec:
        if not isinstance(executable, ExecutableSpec):
            raise ChassisIdentityError("architecture baseline must be an ExecutableSpec")
        parameters = executable.parameter_values()
        if not isinstance(parameters, dict):
            raise ChassisIdentityError("architecture parameters must be an object")
        roles: dict[str, ArchitectureRoleSpec] = {}
        for role in _ARCHITECTURE_ROLES:
            components = tuple(
                component
                for component in executable.components
                if component_domain(component) in _ROLE_DOMAINS[role]
            )
            parameter_fields: set[str] = set()
            for component in components:
                specification = component.specification()
                if not isinstance(specification, dict):
                    continue
                raw_fields = specification.get("parameter_fields", [])
                if not isinstance(raw_fields, list) or any(
                    type(value) is not str or not value.isascii()
                    for value in raw_fields
                ):
                    raise ChassisIdentityError(
                        "architecture component parameter_fields are malformed"
                    )
                parameter_fields.update(raw_fields)
            missing_parameters = parameter_fields - set(parameters)
            if missing_parameters:
                raise ChassisIdentityError(
                    "architecture component parameter is absent from its Executable"
                )
            boundaries: tuple[tuple[str, str], ...] = ()
            if role is ArchitectureRole.EXECUTION:
                boundaries = (
                    ("clock_contract", executable.clock_contract),
                    ("cost_contract", executable.cost_contract),
                    ("engine_contract", executable.engine_contract),
                )
            roles[role.value] = ArchitectureRoleSpec(
                role=role,
                components=components,
                parameter_bindings=tuple(
                    (name, parameters[name]) for name in sorted(parameter_fields)
                ),
                boundary_bindings=boundaries,
            )
        return cls(**roles, _component_context=executable.components)

    @property
    def component_identities(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    component_id
                    for role in _ARCHITECTURE_ROLES
                    for component_id in getattr(self, role.value).component_identities
                }
            )
        )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "roles": {
                role.value: getattr(self, role.value).to_identity_payload()
                for role in _ARCHITECTURE_ROLES
            },
            "schema": "architecture_chassis.v2",
        }

    def normalized_payload(
        self,
        surface_replacements: Mapping[str, str],
    ) -> dict[str, CanonicalValue]:
        payload = self.to_identity_payload()
        roles = payload["roles"]
        assert isinstance(roles, dict)
        for role_payload in roles.values():
            assert isinstance(role_payload, dict)
            surfaces = role_payload["component_semantic_surfaces"]
            assert isinstance(surfaces, list)
            role_payload["component_semantic_surfaces"] = sorted(
                {
                    surface_replacements.get(surface, surface)
                    for surface in surfaces
                }
            )
        return payload


def _prospective_dependency_category(
    dependency: str,
    *,
    registry: Mapping[str, Mapping[str, object]],
) -> str:
    if dependency.startswith("component:"):
        component_id = _component_identity(dependency)
        manifest = registry.get(component_id)
        if manifest is None:
            raise ChassisIdentityError(
                "architecture dependency is not bound to a direct Component manifest"
            )
        return "research-domain:" + _component_domain_from_manifest(manifest).value
    if dependency.startswith("role:"):
        raw_domain = dependency.removeprefix("role:")
        raw_domain = {"external_source": "data_source"}.get(raw_domain, raw_domain)
        try:
            domain = ResearchLayer(raw_domain)
        except ValueError as exc:
            raise ChassisIdentityError(
                "architecture role dependency is not a ResearchLayer"
            ) from exc
        return "research-domain:" + domain.value
    normalized = _normalize_architecture_semantic_value(dependency)
    if not isinstance(normalized, str) or not normalized:
        raise ChassisIdentityError("architecture dependency category is invalid")
    return normalized


def _engine_token_has_prefix(token: str, prefixes: tuple[str, ...]) -> bool:
    lowered = token.lower()
    return any(
        lowered == prefix
        or lowered.startswith(prefix + "_")
        or lowered.startswith(prefix + "-")
        or lowered.startswith(prefix + "@")
        or (
            prefix in _ENGINE_LIBRARY_PREFIXES
            and lowered.startswith(prefix)
            and len(lowered) > len(prefix)
            and lowered[len(prefix)].isdigit()
        )
        for prefix in prefixes
    )


def _prospective_engine_category(value: str) -> dict[str, CanonicalValue]:
    stable_value = value.split("+", 1)[0]
    parts = stable_value.split(":")
    if len(parts) < 2 or parts[0] != "engine" or not parts[1]:
        raise ChassisIdentityError("architecture engine contract is malformed")
    normalized_family = _normalize_architecture_semantic_value(parts[1])
    if not isinstance(normalized_family, str) or not normalized_family:
        raise ChassisIdentityError("architecture engine family is malformed")
    runtime_categories: set[str] = set()
    semantic_modes: set[str] = set()
    for token in parts[2:]:
        if not token:
            continue
        runtime_category = next(
            (
                category
                for category, pattern in _ENGINE_RUNTIME_CATEGORIES
                if pattern.match(token)
            ),
            None,
        )
        if runtime_category is not None:
            runtime_categories.add(runtime_category)
            continue
        if _engine_token_has_prefix(token, _ENGINE_LIBRARY_PREFIXES):
            continue
        if _engine_token_has_prefix(token, _ENGINE_NON_ARCHITECTURAL_PREFIXES):
            continue
        normalized_token = _normalize_architecture_semantic_value(token)
        if not isinstance(normalized_token, str) or not normalized_token:
            raise ChassisIdentityError("architecture engine mode is malformed")
        semantic_modes.add(normalized_token)
    return {
        "engine_family": normalized_family,
        "runtime_categories": sorted(runtime_categories),
        "schema": "architecture_engine_category.v4",
        "semantic_modes": sorted(semantic_modes),
    }


def _prospective_boundary_category(
    name: str,
    value: str,
) -> CanonicalValue:
    binding = _ascii("architecture boundary identity", value)
    if name == "engine_contract":
        return _prospective_engine_category(binding)
    namespace = name.removesuffix("_contract")
    if not binding.startswith(namespace + ":"):
        raise ChassisIdentityError(
            f"architecture {namespace} contract is malformed"
        )
    normalized = _normalize_architecture_semantic_value(binding)
    if not isinstance(normalized, str) or not normalized:
        raise ChassisIdentityError(
            f"architecture {namespace} category is malformed"
        )
    return normalized


def prospective_architecture_payload_from_chassis(
    chassis: ArchitectureChassisSpec,
) -> dict[str, CanonicalValue]:
    """Return a prospective semantic-family v4 payload from a typed chassis.

    The legacy v2 payload and ``ArchitectureChassisSpec.identity`` remain exact
    and immutable for historical reconstruction.  This additive payload is the
    coarse scheduler/review family: it retains role topology, causal semantics,
    and runtime categories while excluding implementation and experiment
    bookkeeping that remains bound at Component and Executable identity.

    A stored ``architecture_chassis.v2`` payload alone is insufficient because
    it contains surface identities, not the complete Component manifests needed
    to resolve dependency-domain topology.  Only a chassis derived from an exact
    ``ExecutableSpec`` carries that prospective context; a reconstructed v2-only
    chassis fails closed here and keeps its historical identity unchanged.
    """

    if not isinstance(chassis, ArchitectureChassisSpec):
        raise ChassisIdentityError(
            "prospective architecture value must be an ArchitectureChassisSpec"
        )
    if not chassis._component_context:
        raise ChassisIdentityError(
            "stored v2 architecture lacks prospective Component manifests"
        )
    manifests = tuple(
        component.to_identity_payload()
        for component in chassis._component_context
    )
    registry = _manifest_registry(manifests)
    roles: dict[str, CanonicalValue] = {}
    for role in _ARCHITECTURE_ROLES:
        role_spec = getattr(chassis, role.value)
        surfaces: list[str] = []
        for component in role_spec.components:
            manifest = component.to_identity_payload()
            raw_dependencies = manifest.get("semantic_dependencies")
            if not isinstance(raw_dependencies, list):
                raise ChassisIdentityError(
                    "architecture component dependencies are malformed"
                )
            dependencies = tuple(
                _prospective_dependency_category(
                    _ascii("architecture semantic dependency", dependency),
                    registry=registry,
                )
                for dependency in raw_dependencies
            )
            try:
                surfaces.append(
                    _core_architecture_family_surface(
                        manifest,
                        role=role.value,
                        semantic_dependencies=dependencies,
                    )
                )
            except (ComponentManifestError, ComponentOutsideArchitectureError) as exc:
                raise ChassisIdentityError(str(exc)) from exc
        roles[role.value] = {
            "absence": "none" if not surfaces else None,
            "boundary_categories": {
                name: _prospective_boundary_category(name, value)
                for name, value in role_spec.boundary_bindings
            },
            "component_family_surfaces": sorted(surfaces),
            "parameter_fields": sorted(
                name for name, _ in role_spec.parameter_bindings
            ),
            "role": role.value,
            "schema": "architecture_role_semantic.v4",
        }
    return {
        "roles": roles,
        "schema": "architecture_chassis_semantic.v4",
    }


def prospective_architecture_payload(
    executable: ExecutableSpec,
) -> dict[str, CanonicalValue]:
    """Derive a typed chassis, then return its prospective v4 payload."""

    if not isinstance(executable, ExecutableSpec):
        raise ChassisIdentityError(
            "prospective architecture baseline must be an ExecutableSpec"
        )
    return prospective_architecture_payload_from_chassis(
        ArchitectureChassisSpec.from_executable(executable)
    )


def prospective_architecture_family_identity_from_chassis(
    chassis: ArchitectureChassisSpec,
) -> str:
    """Return one additive v4 family from a context-complete chassis."""

    return "architecture-family:" + canonical_digest(
        domain="architecture-chassis-semantic-v4",
        payload=prospective_architecture_payload_from_chassis(chassis),
    )


def prospective_architecture_family_identity(
    executable: ExecutableSpec,
) -> str:
    """Derive a typed chassis, then return its additive v4 family."""

    if not isinstance(executable, ExecutableSpec):
        raise ChassisIdentityError(
            "prospective architecture baseline must be an ExecutableSpec"
        )
    return prospective_architecture_family_identity_from_chassis(
        ArchitectureChassisSpec.from_executable(executable)
    )


def normalize_architecture_payload(
    payload: Mapping[str, object],
    surface_replacements: Mapping[str, str],
) -> dict[str, CanonicalValue]:
    """Normalize one stored architecture through verified parity surfaces."""

    normalized = parse_canonical(canonical_bytes(payload))
    if (
        not isinstance(normalized, dict)
        or normalized.get("schema") != "architecture_chassis.v2"
        or not isinstance(normalized.get("roles"), dict)
        or set(normalized["roles"]) != {role.value for role in _ARCHITECTURE_ROLES}
    ):
        raise ChassisIdentityError("stored architecture chassis payload is invalid")
    roles = normalized["roles"]
    assert isinstance(roles, dict)
    for role in _ARCHITECTURE_ROLES:
        role_payload = roles[role.value]
        if (
            not isinstance(role_payload, dict)
            or role_payload.get("schema") != "architecture_role.v3"
            or role_payload.get("role") != role.value
            or not isinstance(role_payload.get("component_semantic_surfaces"), list)
        ):
            raise ChassisIdentityError("stored architecture role payload is invalid")
        surfaces = role_payload["component_semantic_surfaces"]
        assert isinstance(surfaces, list)
        replaced = [
            surface_replacements.get(_ascii("architecture surface", value), value)
            for value in surfaces
        ]
        if len(set(replaced)) != len(replaced):
            raise ChassisIdentityError(
                "architecture parity collapses multiple composition slots"
            )
        role_payload["component_semantic_surfaces"] = sorted(replaced)
    return normalized


def architecture_family_identity(
    payload: Mapping[str, object],
    *,
    surface_replacements: Mapping[str, str] | None = None,
) -> str:
    normalized = normalize_architecture_payload(
        payload,
        {} if surface_replacements is None else surface_replacements,
    )
    return "architecture-family:" + canonical_digest(
        domain="architecture-chassis",
        payload=normalized,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ComponentParityEvidence:
    canonical_component: ComponentSpec
    equivalent_component: ComponentSpec
    dimensions: tuple[ComponentParityDimension, ...]
    parity_manifest_hash: str
    completion_record_id: str
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_component, ComponentSpec) or not isinstance(
            self.equivalent_component, ComponentSpec
        ):
            raise ChassisIdentityError("component parity endpoints must be ComponentSpec")
        if self.canonical_component.identity == self.equivalent_component.identity:
            raise ChassisIdentityError("component parity requires distinct identities")
        if component_domain(self.canonical_component) != component_domain(
            self.equivalent_component
        ):
            raise ChassisIdentityError("component parity cannot cross research domains")
        canonical_manifest = self.canonical_component.to_identity_payload()
        equivalent_manifest = self.equivalent_component.to_identity_payload()
        if (
            canonical_manifest["protocol"] != equivalent_manifest["protocol"]
            and _semantic_surface(canonical_manifest)
            == _semantic_surface(equivalent_manifest)
        ):
            raise ChassisIdentityError(
                "protocol-only component identity bumps are forbidden"
            )
        if type(self.dimensions) is not tuple or any(
            not isinstance(value, ComponentParityDimension) for value in self.dimensions
        ):
            raise ChassisIdentityError("component parity dimensions are not typed")
        dimensions = tuple(sorted(set(self.dimensions), key=lambda value: value.value))
        if set(dimensions) != _REQUIRED_PARITY_DIMENSIONS:
            raise ChassisIdentityError(
                "component parity must cover spec, deterministic output, and boundaries"
            )
        _digest("parity_manifest_hash", self.parity_manifest_hash)
        _digest("completion_record_id", self.completion_record_id)
        object.__setattr__(self, "dimensions", dimensions)
        object.__setattr__(
            self,
            "identity",
            "component-parity:"
            + canonical_digest(
                domain="component-parity",
                payload=self.to_identity_payload(),
            ),
        )

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "canonical_component_id": self.canonical_component.identity,
            "canonical_component_manifest": self.canonical_component.to_identity_payload(),
            "completion_record_id": self.completion_record_id,
            "dimensions": [dimension.value for dimension in self.dimensions],
            "equivalent_component_id": self.equivalent_component.identity,
            "equivalent_component_manifest": self.equivalent_component.to_identity_payload(),
            "parity_manifest_hash": self.parity_manifest_hash,
            "schema": "component_parity_evidence.v1",
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ControlledStudyChassis:
    baseline_executable: ExecutableSpec
    changed_domains: tuple[ResearchLayer, ...]
    controlled_domains: tuple[ResearchLayer, ...]
    architecture: ArchitectureChassisSpec
    embedded_controlled_domains: tuple[ResearchLayer, ...] = ()
    equivalences: tuple[ComponentParityEvidence, ...] = ()
    identity: str = field(init=False)
    architecture_family: str = field(init=False)
    controlled_chassis_identity: str = field(init=False)
    _controlled_components: tuple[tuple[str, tuple[str, ...]], ...] = field(
        init=False,
        repr=False,
        compare=False,
    )
    _controlled_parameters: tuple[
        tuple[str, tuple[tuple[str, CanonicalValue], ...]], ...
    ] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.baseline_executable, ExecutableSpec):
            raise ChassisIdentityError("controlled chassis baseline is not ExecutableSpec")
        if type(self.controlled_domains) is not tuple or not self.controlled_domains:
            raise ChassisIdentityError("controlled chassis domains must be non-empty")
        if type(self.changed_domains) is not tuple or not self.changed_domains:
            raise ChassisIdentityError("changed chassis domains must be non-empty")
        if any(not isinstance(domain, ResearchLayer) for domain in self.changed_domains):
            raise ChassisIdentityError("changed chassis domains are not typed")
        if any(not isinstance(domain, ResearchLayer) for domain in self.controlled_domains):
            raise ChassisIdentityError("controlled chassis domains are not typed")
        if type(self.embedded_controlled_domains) is not tuple or any(
            not isinstance(domain, ResearchLayer)
            for domain in self.embedded_controlled_domains
        ):
            raise ChassisIdentityError("embedded controlled chassis domains are not typed")
        changed = tuple(sorted(set(self.changed_domains), key=lambda value: value.value))
        domains = tuple(sorted(set(self.controlled_domains), key=lambda value: value.value))
        embedded = tuple(
            sorted(set(self.embedded_controlled_domains), key=lambda value: value.value)
        )
        if len(changed) != len(self.changed_domains):
            raise ChassisIdentityError("changed chassis domains must be unique")
        if len(domains) != len(self.controlled_domains):
            raise ChassisIdentityError("controlled chassis domains must be unique")
        if len(embedded) != len(self.embedded_controlled_domains):
            raise ChassisIdentityError("embedded controlled chassis domains must be unique")
        if set(changed).intersection(domains) or set(changed).intersection(embedded) or set(domains).intersection(embedded):
            raise ChassisIdentityError("changed and controlled chassis domains overlap")
        if not isinstance(self.architecture, ArchitectureChassisSpec):
            raise ChassisIdentityError("controlled chassis architecture is not typed")
        derived_architecture = ArchitectureChassisSpec.from_executable(
            self.baseline_executable
        )
        if (
            self.architecture.identity != derived_architecture.identity
            or self.architecture.to_identity_payload()
            != derived_architecture.to_identity_payload()
        ):
            raise ChassisIdentityError(
                "architecture chassis must be derived from its exact baseline Executable"
            )
        for role in (
            ArchitectureRole.LABEL,
            ArchitectureRole.DECISION,
            ArchitectureRole.ENTRY,
            ArchitectureRole.LIFECYCLE,
            ArchitectureRole.EXECUTION,
        ):
            if not getattr(self.architecture, role.value).component_identities:
                raise ChassisIdentityError(
                    f"Study architecture role {role.value} requires exact component identities"
                )
        if type(self.equivalences) is not tuple:
            raise ChassisIdentityError("component equivalences must be a tuple")
        equivalences = tuple(sorted(self.equivalences, key=lambda value: value.identity))
        if len({value.identity for value in equivalences}) != len(equivalences):
            raise ChassisIdentityError("component equivalences must be unique")
        for equivalence in equivalences:
            if component_domain(equivalence.canonical_component) not in (*domains, *embedded):
                raise ChassisIdentityError(
                    "component equivalence is allowed only for a controlled domain"
                )
        replacements = _equivalence_replacements(equivalences)
        manifests = [
            component.to_identity_payload()
            for component in self.baseline_executable.components
        ]
        for equivalence in equivalences:
            manifests.extend(
                (
                    equivalence.canonical_component.to_identity_payload(),
                    equivalence.equivalent_component.to_identity_payload(),
                )
            )
        registry = _manifest_registry(tuple(manifests))
        by_domain = _semantic_component_domains(
            root_ids=self.baseline_executable.component_identities,
            registry=registry,
        )
        for equivalence in equivalences:
            domain = component_domain(equivalence.canonical_component)
            if equivalence.canonical_component.identity not in by_domain.get(domain, ()):
                raise ChassisIdentityError(
                    "component equivalence canonical endpoint is absent from the baseline"
                )
            if equivalence.equivalent_component.identity in by_domain.get(domain, ()):
                raise ChassisIdentityError(
                    "component equivalence cannot collapse two baseline composition slots"
                )
        undeclared_baseline_domains = set(by_domain) - set(changed) - set(domains) - set(embedded)
        if undeclared_baseline_domains:
            raise ChassisIdentityError(
                "baseline executable has undeclared component domains: "
                + ", ".join(
                    sorted(domain.value for domain in undeclared_baseline_domains)
                )
            )
        controlled: list[tuple[str, tuple[str, ...]]] = []
        controlled_parameters: list[
            tuple[str, tuple[tuple[str, CanonicalValue], ...]]
        ] = []
        baseline_parameters = self.baseline_executable.parameter_values()
        if not isinstance(baseline_parameters, dict):
            raise ChassisIdentityError("baseline parameters must be an object")
        for domain in (*domains, *embedded):
            identities = by_domain.get(domain, ())
            controlled.append(
                (
                    domain.value,
                    tuple(
                        sorted(
                            {
                                _normalize_component_id(identity, replacements)
                                for identity in identities
                            }
                        )
                    ),
                )
            )
            parameter_fields: set[str] = set()
            for identity in identities:
                specification = registry[identity].get("spec")
                if not isinstance(specification, dict):
                    continue
                raw_fields = specification.get("parameter_fields", [])
                if not isinstance(raw_fields, list) or any(
                    type(value) is not str or not value.isascii()
                    for value in raw_fields
                ):
                    raise ChassisIdentityError(
                        "controlled component parameter_fields are malformed"
                    )
                parameter_fields.update(raw_fields)
            if not parameter_fields.issubset(baseline_parameters):
                raise ChassisIdentityError(
                    "controlled component parameter is absent from its baseline"
                )
            controlled_parameters.append(
                (
                    domain.value,
                    tuple(
                        (name, baseline_parameters[name])
                        for name in sorted(parameter_fields)
                    ),
                )
            )
        normalized_baseline_ids = {
            _normalize_component_id(identity, replacements)
            for identities in by_domain.values()
            for identity in identities
        }
        normalized_architecture_ids = {
            _normalize_component_id(identity, replacements)
            for identity in self.architecture.component_identities
        }
        if not normalized_architecture_ids.issubset(normalized_baseline_ids):
            raise ChassisIdentityError(
                "architecture chassis references components outside its baseline"
            )
        surface_replacements: dict[str, str] = {}
        for equivalence in equivalences:
            domain = component_domain(equivalence.canonical_component)
            role = _architecture_role_for_domain(domain)
            if role is None:
                continue
            surface_replacements[
                _architecture_component_surface_identity(
                    equivalence.equivalent_component,
                    role=role,
                )
            ] = _architecture_component_surface_identity(
                equivalence.canonical_component,
                role=role,
            )
        normalized_architecture = self.architecture.normalized_payload(
            surface_replacements
        )
        architecture_family = "architecture-family:" + canonical_digest(
            domain="architecture-chassis",
            payload=normalized_architecture,
        )
        controlled_chassis_identity = "controlled-chassis:" + canonical_digest(
            domain="controlled-component-chassis",
            payload={
                "architecture_family": architecture_family,
                "controlled_components": {
                    domain: list(identities) for domain, identities in controlled
                },
                "controlled_parameter_bindings": {
                    domain: {name: value for name, value in bindings}
                    for domain, bindings in controlled_parameters
                },
                "schema": "controlled_component_chassis.v1",
            },
        )
        object.__setattr__(self, "changed_domains", changed)
        object.__setattr__(self, "controlled_domains", domains)
        object.__setattr__(self, "embedded_controlled_domains", embedded)
        object.__setattr__(self, "equivalences", equivalences)
        object.__setattr__(self, "_controlled_components", tuple(controlled))
        object.__setattr__(
            self, "_controlled_parameters", tuple(controlled_parameters)
        )
        object.__setattr__(self, "architecture_family", architecture_family)
        object.__setattr__(
            self, "controlled_chassis_identity", controlled_chassis_identity
        )
        object.__setattr__(
            self,
            "identity",
            "study-chassis:"
            + canonical_digest(
                domain="controlled-study-chassis",
                payload=self.to_identity_payload(),
            ),
        )

    def controlled_component_identities(self) -> dict[str, tuple[str, ...]]:
        return dict(self._controlled_components)

    def controlled_parameter_bindings(
        self,
    ) -> dict[str, dict[str, CanonicalValue]]:
        return {
            domain: {name: value for name, value in bindings}
            for domain, bindings in self._controlled_parameters
        }

    def to_identity_payload(self) -> dict[str, CanonicalValue]:
        return {
            "architecture": self.architecture.to_identity_payload(),
            "architecture_family": self.architecture_family,
            "baseline_executable": self.baseline_executable.to_identity_payload(),
            "baseline_executable_id": self.baseline_executable.identity,
            "controlled_chassis_identity": self.controlled_chassis_identity,
            "controlled_component_identities": {
                domain: list(identities)
                for domain, identities in self._controlled_components
            },
            "controlled_parameter_bindings": self.controlled_parameter_bindings(),
            "controlled_domains": [domain.value for domain in self.controlled_domains],
            "embedded_controlled_domains": [
                domain.value for domain in self.embedded_controlled_domains
            ],
            "changed_domains": [domain.value for domain in self.changed_domains],
            "equivalences": [
                equivalence.to_identity_payload() for equivalence in self.equivalences
            ],
            "schema": "controlled_study_chassis.v1",
        }


def _control_payload_replacements(payload: Mapping[str, object]) -> dict[str, str]:
    raw = payload.get("equivalences")
    if not isinstance(raw, list):
        raise ChassisIdentityError("controlled chassis equivalences are malformed")
    replacements: dict[str, str] = {}
    canonical_ids: set[str] = set()
    for value in raw:
        if not isinstance(value, dict):
            raise ChassisIdentityError("controlled chassis equivalence is malformed")
        canonical_id = _component_identity(value.get("canonical_component_id"))
        equivalent_id = _component_identity(value.get("equivalent_component_id"))
        if equivalent_id in replacements:
            raise ChassisIdentityError("equivalent component has multiple anchors")
        replacements[equivalent_id] = canonical_id
        canonical_ids.add(canonical_id)
    if canonical_ids.intersection(replacements):
        raise ChassisIdentityError("component equivalence chains are not allowed")
    return replacements


def validate_controlled_executable(
    control_payload: Mapping[str, object],
    executable: ExecutableSpec,
) -> None:
    """Prove that one trial preserves every Study-controlled component domain."""

    if control_payload.get("schema") != "controlled_study_chassis.v1":
        raise ChassisIdentityError("Study controlled chassis payload is invalid")
    if not isinstance(executable, ExecutableSpec):
        raise ChassisIdentityError("controlled trial must be an ExecutableSpec")
    baseline = control_payload.get("baseline_executable")
    equivalences = control_payload.get("equivalences")
    expected = control_payload.get("controlled_component_identities")
    domains = control_payload.get("controlled_domains")
    embedded_domains = control_payload.get("embedded_controlled_domains", [])
    changed_domains = control_payload.get("changed_domains")
    controlled_parameter_bindings = control_payload.get(
        "controlled_parameter_bindings"
    )
    if (
        not isinstance(baseline, dict)
        or not isinstance(baseline.get("component_manifests"), list)
        or not isinstance(equivalences, list)
        or not isinstance(expected, dict)
        or not isinstance(domains, list)
        or not isinstance(embedded_domains, list)
        or not isinstance(changed_domains, list)
        or not isinstance(controlled_parameter_bindings, dict)
    ):
        raise ChassisIdentityError("Study controlled chassis payload is incomplete")
    manifests: list[Mapping[str, object]] = []
    manifests.extend(
        manifest
        for manifest in baseline["component_manifests"]
        if isinstance(manifest, dict)
    )
    if len(manifests) != len(baseline["component_manifests"]):
        raise ChassisIdentityError("baseline component manifests are malformed")
    for equivalence in equivalences:
        if not isinstance(equivalence, dict):
            raise ChassisIdentityError("component equivalence payload is malformed")
        for name in ("canonical_component_manifest", "equivalent_component_manifest"):
            manifest = equivalence.get(name)
            if not isinstance(manifest, dict):
                raise ChassisIdentityError("component equivalence manifest is absent")
            manifests.append(manifest)
    current_manifests = tuple(
        component.to_identity_payload() for component in executable.components
    )
    current_registry = _manifest_registry(current_manifests)
    manifests.extend(current_manifests)
    registry = _manifest_registry(tuple(manifests))
    current_by_domain = _semantic_component_domains(
        root_ids=executable.component_identities,
        registry=current_registry,
    )
    direct_by_domain: dict[ResearchLayer, set[str]] = {}
    for component in executable.components:
        direct_by_domain.setdefault(component_domain(component), set()).add(
            component.identity
        )
    for required_domain in (
        ResearchLayer.FEATURE,
        ResearchLayer.LABEL,
    ):
        if not direct_by_domain.get(required_domain):
            raise ChassisIdentityError(
                f"trial omits an explicit {required_domain.value} component"
            )
    direct_decision_ids = tuple(
        sorted(
            component_id
            for domain in (
                ResearchLayer.MODEL,
                ResearchLayer.CALIBRATION,
                ResearchLayer.SELECTOR,
            )
            for component_id in direct_by_domain.get(domain, ())
        )
    )
    if not direct_decision_ids:
        raise ChassisIdentityError(
            "trial omits an explicit model, calibration, or selector decision component"
        )
    consumed_feature_ids: set[str] = set()
    consumed_label_ids: set[str] = set()
    for decision_id in direct_decision_ids:
        decision_manifest = current_registry[decision_id]
        dependencies = decision_manifest.get("semantic_dependencies")
        if not isinstance(dependencies, list):
            raise ChassisIdentityError("decision semantic dependencies are malformed")
        dependency_domains = _semantic_component_domains(
            root_ids=tuple(
                _component_identity(value)
                for value in dependencies
                if isinstance(value, str) and value.startswith("component:")
            ),
            registry=current_registry,
        )
        consumed_feature_ids.update(
            dependency_domains.get(ResearchLayer.FEATURE, ())
        )
        consumed_label_ids.update(
            dependency_domains.get(ResearchLayer.LABEL, ())
        )
    if (
        consumed_feature_ids != direct_by_domain[ResearchLayer.FEATURE]
        or consumed_label_ids != direct_by_domain[ResearchLayer.LABEL]
    ):
        raise ChassisIdentityError(
            "decision semantic dependencies must exactly bind current direct feature and label components"
        )
    replacements = _control_payload_replacements(control_payload)
    try:
        allowed_domains = {
            *(ResearchLayer(value) for value in domains),
            *(ResearchLayer(value) for value in embedded_domains),
            *(ResearchLayer(value) for value in changed_domains),
        }
    except (TypeError, ValueError) as exc:
        raise ChassisIdentityError("Study component domains are not typed") from exc
    undeclared_current_domains = set(current_by_domain) - allowed_domains
    if undeclared_current_domains:
        raise ChassisIdentityError(
            "trial has undeclared component domains: "
            + ", ".join(
                sorted(domain.value for domain in undeclared_current_domains)
            )
        )

    baseline_parameters = baseline.get("parameters")
    current_parameters = executable.parameter_values()
    if not isinstance(baseline_parameters, dict) or not isinstance(
        current_parameters, dict
    ):
        raise ChassisIdentityError(
            "controlled executable parameters must be canonical objects"
        )
    if executable.data_contract != baseline.get("data_contract"):
        raise ChassisIdentityError("trial changes the controlled data contract")
    if executable.split_contract != baseline.get("split_contract"):
        raise ChassisIdentityError("trial changes the controlled split contract")

    baseline_manifests = tuple(
        manifest
        for manifest in baseline["component_manifests"]
        if isinstance(manifest, dict)
    )
    baseline_direct_by_domain: dict[ResearchLayer, set[str]] = {}
    for manifest in baseline_manifests:
        baseline_direct_by_domain.setdefault(
            _component_domain_from_manifest(manifest), set()
        ).add(component_semantic_surface_identity(manifest))
    current_direct_surfaces: dict[ResearchLayer, set[str]] = {}
    for manifest in current_manifests:
        current_direct_surfaces.setdefault(
            _component_domain_from_manifest(manifest), set()
        ).add(component_semantic_surface_identity(manifest))
    for domain_value in changed_domains:
        try:
            domain = ResearchLayer(domain_value)
        except (TypeError, ValueError) as exc:
            raise ChassisIdentityError("changed domain is not typed") from exc
        baseline_surfaces = baseline_direct_by_domain.get(domain, set())
        current_surfaces = current_direct_surfaces.get(domain, set())
        if (
            domain is not ResearchLayer.DATA_SOURCE
            and (not baseline_surfaces or not current_surfaces)
        ) or (domain is ResearchLayer.DATA_SOURCE and not current_surfaces):
            raise ChassisIdentityError(
                f"changed domain {domain.value} requires direct component manifests"
            )
        parameter_fields: set[str] = set()
        for manifest in (*baseline_manifests, *current_manifests):
            if _component_domain_from_manifest(manifest) != domain:
                continue
            specification = manifest.get("spec")
            raw_fields = (
                []
                if not isinstance(specification, dict)
                else specification.get("parameter_fields", [])
            )
            if not isinstance(raw_fields, list) or any(
                type(field_name) is not str or not field_name.isascii()
                for field_name in raw_fields
            ):
                raise ChassisIdentityError(
                    "changed component parameter_fields are malformed"
                )
            parameter_fields.update(raw_fields)
        if (
            domain is ResearchLayer.FEATURE
            and "score_profile" in baseline_parameters
            and "score_profile" in current_parameters
        ):
            parameter_fields.add("score_profile")
        parameter_changed = any(
            field_name in baseline_parameters
            and field_name in current_parameters
            and baseline_parameters[field_name] != current_parameters[field_name]
            for field_name in parameter_fields
        )
        if current_surfaces == baseline_surfaces and not parameter_changed:
            raise ChassisIdentityError(
                f"trial does not semantically change its declared domain {domain.value}"
            )
    for baseline_manifest in baseline_manifests:
        baseline_domain = _component_domain_from_manifest(baseline_manifest)
        for current_manifest in current_manifests:
            current_domain = _component_domain_from_manifest(current_manifest)
            if (
                current_domain != baseline_domain
                and _semantic_surface(current_manifest)
                == _semantic_surface(baseline_manifest)
            ):
                raise ChassisIdentityError(
                    "protocol-domain-only component relocation is forbidden"
                )
    _validate_executable_consumption(current_manifests)
    controlled_domain_names = set(domains)
    for baseline_manifest in baseline_manifests:
        baseline_id = _component_manifest_identity(baseline_manifest)
        baseline_domain = _component_domain_from_manifest(baseline_manifest)
        if baseline_domain.value not in controlled_domain_names:
            continue
        for current_manifest in current_manifests:
            current_id = _component_manifest_identity(current_manifest)
            if (
                baseline_id != current_id
                and baseline_domain == _component_domain_from_manifest(current_manifest)
                and baseline_manifest["protocol"] != current_manifest["protocol"]
                and _semantic_surface(baseline_manifest)
                == _semantic_surface(current_manifest)
            ):
                raise ChassisIdentityError(
                    "protocol-only controlled component identity bump is forbidden"
                )

    for domain_value in [*domains, *embedded_domains]:
        try:
            domain = ResearchLayer(domain_value)
        except (TypeError, ValueError) as exc:
            raise ChassisIdentityError("controlled domain is not typed") from exc
        expected_ids = expected.get(domain_value)
        if not isinstance(expected_ids, list):
            raise ChassisIdentityError(
                f"controlled domain {domain_value} has malformed baseline components"
            )
        current_ids = current_by_domain.get(domain, ())
        if not expected_ids:
            if current_ids:
                raise ChassisIdentityError(
                    f"trial populates controlled absent domain {domain_value}"
                )
            frozen_bindings = controlled_parameter_bindings.get(domain_value)
            if frozen_bindings != {}:
                raise ChassisIdentityError(
                    f"controlled absent domain {domain_value} has parameter bindings"
                )
            continue
        if not current_ids:
            raise ChassisIdentityError(
                f"trial omits controlled domain {domain_value}; declare exact semantic dependencies"
            )
        normalized_current = Counter(
            _normalize_component_id(identity, replacements) for identity in current_ids
        )
        if normalized_current != Counter(expected_ids):
            raise ChassisIdentityError(
                f"trial changes controlled component identities for {domain_value}"
            )
        controlled_parameter_fields: set[str] = set()
        for component_id in current_ids:
            manifest = registry[component_id]
            specification = manifest.get("spec")
            if not isinstance(specification, dict):
                continue
            parameter_fields = specification.get("parameter_fields", [])
            if not isinstance(parameter_fields, list) or any(
                type(field_name) is not str or not field_name.isascii()
                for field_name in parameter_fields
            ):
                raise ChassisIdentityError(
                    "controlled component parameter_fields are malformed"
                )
            controlled_parameter_fields.update(parameter_fields)
        for field_name in controlled_parameter_fields:
            if (
                field_name not in baseline_parameters
                or field_name not in current_parameters
                or baseline_parameters[field_name] != current_parameters[field_name]
            ):
                raise ChassisIdentityError(
                    f"trial changes controlled parameter {field_name!r}"
                )
        frozen_bindings = controlled_parameter_bindings.get(domain_value)
        if not isinstance(frozen_bindings, dict):
            raise ChassisIdentityError(
                f"controlled domain {domain_value} has no frozen parameter bindings"
            )
        for field_name, frozen_value in frozen_bindings.items():
            if (
                not isinstance(field_name, str)
                or not field_name.isascii()
                or field_name not in baseline_parameters
                or field_name not in current_parameters
                or baseline_parameters[field_name] != frozen_value
                or current_parameters[field_name] != frozen_value
            ):
                raise ChassisIdentityError(
                    f"trial changes frozen controlled parameter {field_name!r}"
                )

    controlled_domain_values = set(domains)
    if ResearchLayer.EXECUTION.value in controlled_domain_values:
        if executable.clock_contract != baseline.get("clock_contract"):
            raise ChassisIdentityError("trial changes the controlled clock contract")
        if executable.cost_contract != baseline.get("cost_contract"):
            raise ChassisIdentityError("trial changes the controlled cost contract")
        if executable.engine_contract != baseline.get("engine_contract"):
            raise ChassisIdentityError("trial changes the controlled engine contract")
    if (
        ResearchLayer.DATA_SOURCE.value in controlled_domain_values
        and list(executable.source_contracts) != baseline.get("source_contracts")
    ):
        raise ChassisIdentityError("trial changes controlled source contracts")


def require_combinable_chassis(
    left: ControlledStudyChassis,
    right: ControlledStudyChassis,
    *,
    shared_domains: tuple[ResearchLayer, ...],
) -> str:
    """Return a combination identity only for exact shared component identities.

    Parity-assisted combination is a Writer boundary because a caller-created
    ``ComponentParityEvidence`` is not authority.
    """

    if not isinstance(left, ControlledStudyChassis) or not isinstance(
        right, ControlledStudyChassis
    ):
        raise ChassisIdentityError("Study chassis comparison requires typed chassis")
    if type(shared_domains) is not tuple or not shared_domains:
        raise ChassisIdentityError("shared chassis domains must be non-empty")
    if any(not isinstance(domain, ResearchLayer) for domain in shared_domains):
        raise ChassisIdentityError("shared chassis domains are not typed")
    if left.architecture_family != right.architecture_family:
        raise ChassisIdentityError(
            "Study results cannot combine different architecture boundary identities"
        )
    left_components = left.controlled_component_identities()
    right_components = right.controlled_component_identities()
    left_parameters = left.controlled_parameter_bindings()
    right_parameters = right.controlled_parameter_bindings()
    comparison: dict[str, list[str]] = {}
    parameter_comparison: dict[str, dict[str, CanonicalValue]] = {}
    for domain in sorted(set(shared_domains), key=lambda value: value.value):
        left_ids = left_components.get(domain.value)
        right_ids = right_components.get(domain.value)
        if left_ids is None or right_ids is None:
            raise ChassisIdentityError(
                f"both Studies must control shared domain {domain.value}"
            )
        normalized_left = set(left_ids)
        normalized_right = set(right_ids)
        if normalized_left != normalized_right:
            raise ChassisIdentityError(
                f"Study results require Writer-verified parity for {domain.value}"
            )
        if left_parameters.get(domain.value) != right_parameters.get(domain.value):
            raise ChassisIdentityError(
                f"Study results change controlled parameters for {domain.value}"
            )
        comparison[domain.value] = sorted(normalized_left)
        parameter_comparison[domain.value] = left_parameters.get(domain.value, {})
    return "chassis-combination:" + canonical_digest(
        domain="study-chassis-combination",
        payload={
            "components": comparison,
            "architecture_family": left.architecture_family,
            "parameter_bindings": parameter_comparison,
            "schema": "study_chassis_combination.v1",
        },
    )


def combine_control_payloads(
    left: Mapping[str, object],
    right: Mapping[str, object],
    *,
    shared_domains: tuple[ResearchLayer, ...],
    verified_equivalences: tuple[Mapping[str, object], ...] = (),
) -> str:
    """Combine stored Study payloads after the Writer verifies every parity edge."""

    if type(shared_domains) is not tuple or not shared_domains or any(
        not isinstance(domain, ResearchLayer) for domain in shared_domains
    ):
        raise ChassisIdentityError("shared chassis domains are not typed")
    for payload in (left, right):
        if payload.get("schema") != "controlled_study_chassis.v1":
            raise ChassisIdentityError("stored Study chassis payload is invalid")
    if type(verified_equivalences) is not tuple or any(
        not isinstance(value, Mapping) for value in verified_equivalences
    ):
        raise ChassisIdentityError("Writer-verified component equivalences are malformed")
    equivalence_payloads: list[Mapping[str, object]] = []
    for payload in (left, right):
        values = payload.get("equivalences")
        if not isinstance(values, list):
            raise ChassisIdentityError("stored component equivalences are malformed")
        for value in values:
            if not isinstance(value, Mapping):
                raise ChassisIdentityError("stored component equivalence is malformed")
            equivalence_payloads.append(value)
    equivalence_payloads.extend(verified_equivalences)

    manifests: dict[str, Mapping[str, object]] = {}
    direct_edges: set[frozenset[str]] = set()
    parents: dict[str, str] = {}

    def find(component_id: str) -> str:
        parent = parents.setdefault(component_id, component_id)
        if parent != component_id:
            parents[component_id] = find(parent)
        return parents[component_id]

    def union(left_id: str, right_id: str) -> None:
        left_root = find(left_id)
        right_root = find(right_id)
        if left_root == right_root:
            return
        low, high = sorted((left_root, right_root))
        parents[high] = low

    for equivalence in equivalence_payloads:
        canonical_id = _component_identity(
            equivalence.get("canonical_component_id")
        )
        equivalent_id = _component_identity(
            equivalence.get("equivalent_component_id")
        )
        if canonical_id == equivalent_id:
            raise ChassisIdentityError("component parity endpoints must be distinct")
        endpoint_manifests: list[tuple[str, Mapping[str, object]]] = []
        for prefix, component_id in (
            ("canonical", canonical_id),
            ("equivalent", equivalent_id),
        ):
            manifest = equivalence.get(f"{prefix}_component_manifest")
            if not isinstance(manifest, Mapping):
                raise ChassisIdentityError("component parity endpoint manifest is absent")
            if _component_manifest_identity(manifest) != component_id:
                raise ChassisIdentityError(
                    "component parity endpoint differs from its manifest"
                )
            prior = manifests.get(component_id)
            if prior is not None and canonical_bytes(prior) != canonical_bytes(manifest):
                raise ChassisIdentityError("component parity endpoint identity collision")
            manifests[component_id] = manifest
            endpoint_manifests.append((component_id, manifest))
        if _component_domain_from_manifest(endpoint_manifests[0][1]) != (
            _component_domain_from_manifest(endpoint_manifests[1][1])
        ):
            raise ChassisIdentityError("component parity cannot cross research domains")
        direct_edges.add(frozenset((canonical_id, equivalent_id)))
        union(canonical_id, equivalent_id)

    surface_owners: dict[str, str] = {}
    for component_id, manifest in manifests.items():
        role = _architecture_role_for_domain(
            _component_domain_from_manifest(manifest)
        )
        if role is None:
            continue
        surface = _architecture_component_surface_identity(manifest, role=role)
        owner = surface_owners.get(surface)
        if owner is None:
            surface_owners[surface] = component_id
        else:
            union(owner, component_id)

    classes: dict[str, list[str]] = {}
    for component_id in parents:
        classes.setdefault(find(component_id), []).append(component_id)
    surface_replacements: dict[str, str] = {}
    for members in classes.values():
        sorted_members = sorted(members)
        class_surface = "architecture-equivalence-class:" + canonical_digest(
            domain="architecture-equivalence-class",
            payload={
                "component_ids": sorted_members,
                "schema": "architecture_equivalence_class.v1",
            },
        )
        for component_id in sorted_members:
            manifest = manifests[component_id]
            role = _architecture_role_for_domain(
                _component_domain_from_manifest(manifest)
            )
            if role is None:
                continue
            surface = _architecture_component_surface_identity(
                manifest,
                role=role,
            )
            prior = surface_replacements.get(surface)
            if prior is not None and prior != class_surface:
                raise ChassisIdentityError(
                    "architecture surface belongs to conflicting parity classes"
                )
            surface_replacements[surface] = class_surface

    architectures: list[dict[str, CanonicalValue]] = []
    for payload in (left, right):
        architecture = payload.get("architecture")
        if not isinstance(architecture, Mapping):
            raise ChassisIdentityError("stored Study architecture is absent")
        architectures.append(
            normalize_architecture_payload(architecture, surface_replacements)
        )
    if architectures[0] != architectures[1]:
        raise ChassisIdentityError(
            "Study results cannot combine different architecture boundary identities"
        )
    architecture_family = "architecture-family:" + canonical_digest(
        domain="architecture-chassis",
        payload=architectures[0],
    )

    def unique_matching(
        left_ids: list[str],
        right_ids: list[str],
    ) -> list[tuple[str, str]]:
        if len(left_ids) != len(right_ids):
            raise ChassisIdentityError(
                "Study results require a bijective controlled composition"
            )
        candidates = {
            left_id: [
                right_id
                for right_id in right_ids
                if left_id == right_id
                or frozenset((left_id, right_id)) in direct_edges
            ]
            for left_id in left_ids
        }
        if any(not values for values in candidates.values()):
            raise ChassisIdentityError(
                "Study results lack direct Writer-verified component parity"
            )
        solutions: list[list[tuple[str, str]]] = []

        def search(
            position: int,
            used: set[str],
            pairs: list[tuple[str, str]],
        ) -> None:
            if len(solutions) > 1:
                return
            if position == len(left_ids):
                solutions.append(list(pairs))
                return
            left_id = left_ids[position]
            for right_id in candidates[left_id]:
                if right_id in used:
                    continue
                used.add(right_id)
                pairs.append((left_id, right_id))
                search(position + 1, used, pairs)
                pairs.pop()
                used.remove(right_id)

        search(0, set(), [])
        if len(solutions) != 1:
            raise ChassisIdentityError(
                "Study results do not have one unique component-parity bijection"
            )
        return solutions[0]

    comparison: dict[str, list[str]] = {}
    parameter_comparison: dict[str, dict[str, CanonicalValue]] = {}
    for domain in sorted(set(shared_domains), key=lambda value: value.value):
        sides: list[list[str]] = []
        for payload in (left, right):
            components = payload.get("controlled_component_identities")
            values = None if not isinstance(components, dict) else components.get(domain.value)
            if not isinstance(values, list) or not values:
                raise ChassisIdentityError(
                    f"both Studies must control shared domain {domain.value}"
                )
            normalized = [_component_identity(value) for value in values]
            if len(set(normalized)) != len(normalized):
                raise ChassisIdentityError(
                    "stored controlled composition contains duplicate identities"
                )
            sides.append(sorted(normalized))
        pairs = unique_matching(sides[0], sides[1])
        comparison[domain.value] = sorted(
            left_id
            if left_id == right_id
            else "component-equivalence:"
            + canonical_digest(
                domain="component-equivalence-pair",
                payload={
                    "component_ids": sorted((left_id, right_id)),
                    "schema": "component_equivalence_pair.v1",
                },
            )
            for left_id, right_id in pairs
        )
        parameter_sides: list[dict[str, CanonicalValue]] = []
        for payload in (left, right):
            bindings = payload.get("controlled_parameter_bindings")
            value = None if not isinstance(bindings, dict) else bindings.get(domain.value)
            if not isinstance(value, dict):
                raise ChassisIdentityError(
                    "stored controlled parameter bindings are malformed"
                )
            parameter_sides.append(value)
        if parameter_sides[0] != parameter_sides[1]:
            raise ChassisIdentityError(
                f"Study results change controlled parameters for {domain.value}"
            )
        parameter_comparison[domain.value] = parameter_sides[0]
    return "chassis-combination:" + canonical_digest(
        domain="study-chassis-combination",
        payload={
            "components": comparison,
            "architecture_family": architecture_family,
            "parameter_bindings": parameter_comparison,
            "schema": "study_chassis_combination.v1",
        },
    )


__all__ = [
    "ArchitectureChassisSpec",
    "ArchitectureRole",
    "ArchitectureRoleSpec",
    "ChassisIdentityError",
    "ChassisComponentOutsideArchitectureError",
    "ComponentParityDimension",
    "ComponentParityEvidence",
    "ControlledStudyChassis",
    "architecture_component_semantic_surface_identity",
    "architecture_family_identity",
    "combine_control_payloads",
    "component_domain",
    "component_semantic_surface_identity",
    "executable_semantic_surface_identity",
    "normalize_architecture_payload",
    "prospective_architecture_family_identity",
    "prospective_architecture_family_identity_from_chassis",
    "prospective_architecture_payload",
    "prospective_architecture_payload_from_chassis",
    "require_combinable_chassis",
    "validate_controlled_executable",
]
