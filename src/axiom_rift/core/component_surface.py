"""Canonical Component manifest validation and semantic surface identities."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .canonical import CanonicalValue, canonical_bytes, parse_canonical
from .identity import ComponentSpec, canonical_digest


class ComponentManifestError(ValueError):
    """Raised when a Component manifest or semantic surface is invalid."""


class ComponentOutsideArchitectureError(ComponentManifestError):
    """A valid component has no prediction-to-position architecture role."""


COMPONENT_SURFACE_DOMAIN_AWARE = "domain_aware"
COMPONENT_SURFACE_PROTOCOL_NEUTRAL = "protocol_neutral"
COMPONENT_SURFACE_ARCHITECTURE_ROLE = "architecture_role"
COMPONENT_SURFACE_KINDS = frozenset(
    {
        COMPONENT_SURFACE_ARCHITECTURE_ROLE,
        COMPONENT_SURFACE_DOMAIN_AWARE,
        COMPONENT_SURFACE_PROTOCOL_NEUTRAL,
    }
)

COMPONENT_RESEARCH_DOMAINS = frozenset(
    {
        "calibration",
        "data_source",
        "execution",
        "feature",
        "label",
        "lifecycle",
        "model",
        "objective",
        "portfolio",
        "regime",
        "risk",
        "selector",
        "synthesis",
        "trade",
    }
)
COMPONENT_DOMAIN_ALIASES = {"external_source": "data_source"}
ARCHITECTURE_ROLE_DOMAINS: dict[str, frozenset[str]] = {
    "label": frozenset({"label"}),
    "decision": frozenset({"calibration", "model", "selector"}),
    "entry": frozenset({"trade"}),
    "lifecycle": frozenset({"lifecycle"}),
    "execution": frozenset({"execution"}),
    "portfolio": frozenset({"portfolio", "risk", "synthesis"}),
}

_PROTOCOL_VERSION_SUFFIX = re.compile(r"(?:[._-]v(?:ersion)?\d+)$", re.IGNORECASE)
_EMBEDDED_SHA256 = re.compile(r"@sha256:[0-9a-f]{64}", re.IGNORECASE)
_BARE_SHA256 = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", re.IGNORECASE)
_ARCHITECTURE_VOLATILE_FIELD_TOKENS = frozenset(
    {
        "artifact",
        "build",
        "checksum",
        "digest",
        "hash",
        "implementation",
        "seed",
        "sha",
        "sha256",
        "version",
    }
)


@dataclass(frozen=True, slots=True)
class ComponentSurfaceIdentities:
    """Every derived semantic identity for one exact Component manifest."""

    component_id: str
    domain: str
    domain_aware: str
    protocol_neutral: str
    architecture_role: str | None
    architecture_role_surface: str | None

    def bindings(self) -> tuple[tuple[str, str], ...]:
        values = [
            (COMPONENT_SURFACE_DOMAIN_AWARE, self.domain_aware),
            (COMPONENT_SURFACE_PROTOCOL_NEUTRAL, self.protocol_neutral),
        ]
        if self.architecture_role_surface is not None:
            values.append(
                (
                    COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                    self.architecture_role_surface,
                )
            )
        return tuple(sorted(values))

    def identity_for(self, surface_kind: str) -> str:
        if surface_kind == COMPONENT_SURFACE_DOMAIN_AWARE:
            return self.domain_aware
        if surface_kind == COMPONENT_SURFACE_PROTOCOL_NEUTRAL:
            return self.protocol_neutral
        if surface_kind == COMPONENT_SURFACE_ARCHITECTURE_ROLE:
            if self.architecture_role_surface is None:
                raise ComponentOutsideArchitectureError(
                    "component domain is outside the prediction-to-position architecture"
                )
            return self.architecture_role_surface
        raise ComponentManifestError("component surface kind is not supported")


def component_spec_from_manifest(
    value: Mapping[str, object],
    *,
    display_name: str = "rehydrated canonical component",
) -> ComponentSpec:
    """Rebuild one ComponentSpec and prove exact canonical manifest parity."""

    if not isinstance(value, Mapping):
        raise ComponentManifestError("component manifest must be an object")
    try:
        normalized = parse_canonical(canonical_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise ComponentManifestError("component manifest is not canonical") from exc
    if (
        not isinstance(normalized, dict)
        or normalized.get("schema") != "component_spec.v1"
        or set(normalized)
        != {
            "implementation",
            "protocol",
            "schema",
            "semantic_dependencies",
            "spec",
        }
        or not isinstance(normalized.get("semantic_dependencies"), list)
    ):
        raise ComponentManifestError("component manifest schema is invalid")
    try:
        component = ComponentSpec(
            display_name=display_name,
            protocol=normalized["protocol"],
            implementation=normalized["implementation"],
            spec=normalized["spec"],
            semantic_dependencies=tuple(normalized["semantic_dependencies"]),
        )
    except (TypeError, ValueError) as exc:
        raise ComponentManifestError("component manifest fields are invalid") from exc
    if component.to_identity_payload() != normalized:
        raise ComponentManifestError("component manifest is not canonical")
    return component


def validated_component_manifest(
    value: ComponentSpec | Mapping[str, object],
) -> dict[str, CanonicalValue]:
    """Return one detached, exact Component identity payload."""

    component = (
        value
        if isinstance(value, ComponentSpec)
        else component_spec_from_manifest(value)
    )
    return component.to_identity_payload()


def component_manifest_identity(
    value: ComponentSpec | Mapping[str, object],
) -> str:
    manifest = validated_component_manifest(value)
    return _component_identity_from_manifest(manifest)


def _component_identity_from_manifest(
    manifest: Mapping[str, CanonicalValue],
) -> str:
    return "component:" + canonical_digest(domain="component", payload=dict(manifest))


def component_manifest_domain(
    value: ComponentSpec | Mapping[str, object],
) -> str:
    manifest = validated_component_manifest(value)
    return _component_domain_from_manifest(manifest)


def _component_domain_from_manifest(
    manifest: Mapping[str, CanonicalValue],
) -> str:
    protocol = manifest["protocol"]
    if not isinstance(protocol, str):  # ComponentSpec already proves this.
        raise ComponentManifestError("component protocol is invalid")
    prefix = protocol.split(".", 1)[0]
    domain = COMPONENT_DOMAIN_ALIASES.get(prefix, prefix)
    if domain not in COMPONENT_RESEARCH_DOMAINS:
        raise ComponentManifestError(
            f"component protocol domain {prefix!r} is not a ResearchLayer"
        )
    return domain


def component_manifest_surfaces(
    value: ComponentSpec | Mapping[str, object],
) -> ComponentSurfaceIdentities:
    """Derive every semantic surface from one validated Component manifest."""

    manifest = validated_component_manifest(value)
    domain = _component_domain_from_manifest(manifest)
    roles = tuple(
        role
        for role, domains in ARCHITECTURE_ROLE_DOMAINS.items()
        if domain in domains
    )
    if len(roles) > 1:
        raise ComponentManifestError(
            "research domain has ambiguous architecture roles"
        )
    role = roles[0] if roles else None
    domain_aware = "component-surface:" + canonical_digest(
        domain="component-semantic-surface",
        payload={
            "domain": domain,
            "implementation": manifest["implementation"],
            "schema": "component_semantic_surface.v1",
            "semantic_dependencies": manifest["semantic_dependencies"],
            "spec": manifest["spec"],
        },
    )
    protocol_neutral = "component-protocol-neutral:" + canonical_digest(
        domain="component-protocol-neutral-surface",
        payload={
            "implementation": manifest["implementation"],
            "schema": "component_protocol_neutral_surface.v1",
            "semantic_dependencies": manifest["semantic_dependencies"],
            "spec": manifest["spec"],
        },
    )
    architecture_surface = (
        None
        if role is None
        else "architecture-component-surface:"
        + canonical_digest(
            domain="architecture-component-semantic-surface",
            payload={
                "implementation": manifest["implementation"],
                "role": role,
                "schema": "architecture_component_semantic_surface.v1",
                "semantic_dependencies": manifest["semantic_dependencies"],
                "spec": manifest["spec"],
            },
        )
    )
    return ComponentSurfaceIdentities(
        component_id=_component_identity_from_manifest(manifest),
        domain=domain,
        domain_aware=domain_aware,
        protocol_neutral=protocol_neutral,
        architecture_role=role,
        architecture_role_surface=architecture_surface,
    )


def architecture_component_surface_identity(
    value: ComponentSpec | Mapping[str, object],
    *,
    role: str | None = None,
) -> str:
    surfaces = component_manifest_surfaces(value)
    if surfaces.architecture_role_surface is None:
        raise ComponentOutsideArchitectureError(
            "component domain is outside the prediction-to-position architecture"
        )
    if role is not None and surfaces.architecture_role != role:
        raise ComponentManifestError(
            "architecture component is assigned to the wrong semantic role"
        )
    return surfaces.architecture_role_surface


def architecture_protocol_family(protocol: object) -> str:
    """Return a stable protocol stem for prospective architecture grouping.

    Component and Executable identity continue to bind the exact protocol.  This
    coarser stem is used only by the additive semantic architecture-family v4
    surface, where a terminal ``.vN``/``_vN`` suffix is release bookkeeping and
    not a new prediction-to-position topology.
    """

    if type(protocol) is not str or not protocol or not protocol.isascii():
        raise ComponentManifestError("component protocol must be non-empty ASCII")
    return _PROTOCOL_VERSION_SUFFIX.sub("", protocol)


def _architecture_field_is_volatile(name: str) -> bool:
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", name.lower())
        if token
    }
    return bool(tokens.intersection(_ARCHITECTURE_VOLATILE_FIELD_TOKENS))


def _normalize_architecture_text(value: str) -> str:
    normalized = _EMBEDDED_SHA256.sub("@sha256:{digest}", value)
    normalized = _BARE_SHA256.sub("{digest}", normalized)
    return _PROTOCOL_VERSION_SUFFIX.sub("", normalized)


def normalize_architecture_semantic_value(
    value: CanonicalValue,
) -> CanonicalValue:
    """Remove implementation bookkeeping from one architecture semantic value.

    Volatile fields remain bound by Component and Executable identities.  They
    are intentionally absent only from the coarser architecture family, so a
    source hash, RNG seed, build number, or implementation artifact cannot make
    an otherwise unchanged topology appear to be a new research architecture.
    """

    normalized = parse_canonical(canonical_bytes(value))

    def visit(item: CanonicalValue) -> CanonicalValue:
        if isinstance(item, dict):
            return {
                name: visit(child)
                for name, child in item.items()
                if not _architecture_field_is_volatile(name)
            }
        if isinstance(item, list):
            return [visit(child) for child in item]
        if isinstance(item, str):
            return _normalize_architecture_text(item)
        return item

    return visit(normalized)


def architecture_component_family_surface_identity(
    value: ComponentSpec | Mapping[str, object],
    *,
    role: str | None = None,
    semantic_dependencies: tuple[str, ...] | None = None,
) -> str:
    """Return the additive prospective semantic architecture surface.

    Exact implementation bytes and exact dependency identities deliberately do
    not enter this v4 surface.  The caller supplies dependency-domain topology
    after resolving exact Component references in the containing Executable.
    """

    manifest = validated_component_manifest(value)
    domain = _component_domain_from_manifest(manifest)
    roles = tuple(
        candidate
        for candidate, domains in ARCHITECTURE_ROLE_DOMAINS.items()
        if domain in domains
    )
    if len(roles) != 1:
        raise ComponentOutsideArchitectureError(
            "component domain is outside the prediction-to-position architecture"
        )
    derived_role = roles[0]
    if role is not None and role != derived_role:
        raise ComponentManifestError(
            "architecture component is assigned to the wrong semantic role"
        )
    raw_dependencies = (
        tuple(manifest["semantic_dependencies"])
        if semantic_dependencies is None
        else semantic_dependencies
    )
    if any(
        type(dependency) is not str
        or not dependency
        or not dependency.isascii()
        for dependency in raw_dependencies
    ):
        raise ComponentManifestError(
            "architecture semantic dependencies must be non-empty ASCII"
        )
    dependencies = tuple(
        _normalize_architecture_text(dependency)
        for dependency in raw_dependencies
    )
    normalized_spec = normalize_architecture_semantic_value(manifest["spec"])
    return "architecture-family-component-surface:" + canonical_digest(
        domain="architecture-family-component-semantic-surface",
        payload={
            "domain": domain,
            "protocol_family": architecture_protocol_family(manifest["protocol"]),
            "role": derived_role,
            "schema": "architecture_family_component_surface.v4",
            "semantic_dependencies": sorted(dependencies),
            "spec": normalized_spec,
        },
    )


__all__ = [
    "ARCHITECTURE_ROLE_DOMAINS",
    "COMPONENT_DOMAIN_ALIASES",
    "COMPONENT_RESEARCH_DOMAINS",
    "COMPONENT_SURFACE_ARCHITECTURE_ROLE",
    "COMPONENT_SURFACE_DOMAIN_AWARE",
    "COMPONENT_SURFACE_KINDS",
    "COMPONENT_SURFACE_PROTOCOL_NEUTRAL",
    "ComponentManifestError",
    "ComponentOutsideArchitectureError",
    "ComponentSurfaceIdentities",
    "architecture_component_family_surface_identity",
    "architecture_component_surface_identity",
    "architecture_protocol_family",
    "component_manifest_domain",
    "component_manifest_identity",
    "component_manifest_surfaces",
    "component_spec_from_manifest",
    "normalize_architecture_semantic_value",
    "validated_component_manifest",
]
