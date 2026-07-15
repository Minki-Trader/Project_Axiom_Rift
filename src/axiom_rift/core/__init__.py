"""Small reusable primitives for the Axiom operating kernel."""

from .canonical import (
    CanonicalJSONError,
    CanonicalValue,
    canonical_bytes,
    canonical_text,
    parse_canonical,
)
from .component_surface import (
    COMPONENT_SURFACE_ARCHITECTURE_ROLE,
    COMPONENT_SURFACE_DOMAIN_AWARE,
    COMPONENT_SURFACE_KINDS,
    COMPONENT_SURFACE_PROTOCOL_NEUTRAL,
    ComponentManifestError,
    ComponentSurfaceIdentities,
    architecture_component_surface_identity,
    component_manifest_domain,
    component_manifest_identity,
    component_manifest_surfaces,
    component_spec_from_manifest,
    validated_component_manifest,
)
from .identity import ComponentSpec, ExecutableSpec, canonical_digest

__all__ = [
    "CanonicalJSONError",
    "CanonicalValue",
    "COMPONENT_SURFACE_ARCHITECTURE_ROLE",
    "COMPONENT_SURFACE_DOMAIN_AWARE",
    "COMPONENT_SURFACE_KINDS",
    "COMPONENT_SURFACE_PROTOCOL_NEUTRAL",
    "ComponentManifestError",
    "ComponentSpec",
    "ComponentSurfaceIdentities",
    "ExecutableSpec",
    "canonical_bytes",
    "canonical_digest",
    "canonical_text",
    "architecture_component_surface_identity",
    "component_manifest_domain",
    "component_manifest_identity",
    "component_manifest_surfaces",
    "component_spec_from_manifest",
    "parse_canonical",
    "validated_component_manifest",
]
