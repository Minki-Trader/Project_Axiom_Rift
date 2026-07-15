"""Canonical Component manifest validation and semantic surface identities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .canonical import CanonicalValue, canonical_bytes, parse_canonical
from .identity import ComponentSpec, canonical_digest


class ComponentManifestError(ValueError):
    """Raised when a Component manifest or semantic surface is invalid."""


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
                raise ComponentManifestError(
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
        raise ComponentManifestError(
            "component domain is outside the prediction-to-position architecture"
        )
    if role is not None and surfaces.architecture_role != role:
        raise ComponentManifestError(
            "architecture component is assigned to the wrong semantic role"
        )
    return surfaces.architecture_role_surface


__all__ = [
    "ARCHITECTURE_ROLE_DOMAINS",
    "COMPONENT_DOMAIN_ALIASES",
    "COMPONENT_RESEARCH_DOMAINS",
    "COMPONENT_SURFACE_ARCHITECTURE_ROLE",
    "COMPONENT_SURFACE_DOMAIN_AWARE",
    "COMPONENT_SURFACE_KINDS",
    "COMPONENT_SURFACE_PROTOCOL_NEUTRAL",
    "ComponentManifestError",
    "ComponentSurfaceIdentities",
    "architecture_component_surface_identity",
    "component_manifest_domain",
    "component_manifest_identity",
    "component_manifest_surfaces",
    "component_spec_from_manifest",
    "validated_component_manifest",
]
