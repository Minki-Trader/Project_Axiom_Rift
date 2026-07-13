"""Rehydrate immutable Portfolio projections from durable identity payloads.

Portfolio mutations retain every prior axis.  Older operator scripts each
carried their own permissive reconstruction helpers, which made a structural
Decision depend on ignored local code.  These helpers provide one strict,
reusable read path.  They reconstruct only identity-bearing objects and verify
that the resulting canonical payload is byte-equivalent to durable authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import ComponentSpec
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ArchitectureRole,
    ArchitectureRoleSpec,
    ChassisIdentityError,
    architecture_component_semantic_surface_identity,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.portfolio import PortfolioAxis


class PortfolioProjectionError(ValueError):
    """Raised when durable Portfolio identity cannot be reconstructed exactly."""


def component_from_identity_payload(value: Mapping[str, Any]) -> ComponentSpec:
    """Rebuild one ComponentSpec and prove exact identity-payload equivalence."""

    try:
        normalized = parse_canonical(canonical_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise PortfolioProjectionError("component payload is not canonical") from exc
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
        raise PortfolioProjectionError("component identity payload is malformed")
    try:
        component = ComponentSpec(
            display_name="rehydrated durable architecture component",
            protocol=normalized["protocol"],
            implementation=normalized["implementation"],
            spec=normalized["spec"],
            semantic_dependencies=tuple(normalized["semantic_dependencies"]),
        )
    except (TypeError, ValueError) as exc:
        raise PortfolioProjectionError("component identity cannot be rebuilt") from exc
    if component.to_identity_payload() != normalized:
        raise PortfolioProjectionError("component identity payload changed on rebuild")
    return component


def component_surface_registry(
    payloads: Iterable[Mapping[str, Any]],
) -> dict[str, ComponentSpec]:
    """Build a deterministic semantic-surface registry from durable payloads.

    Payloads may be component projection records, Executable manifests, trial
    records, Portfolio Decisions, or Study records.  The recursive walk reads
    only canonical ComponentSpec manifests and ignores unrelated values.
    """

    candidates: dict[str, dict[str, ComponentSpec]] = {}

    def register(value: object) -> None:
        if not isinstance(value, Mapping) or value.get("schema") != "component_spec.v1":
            return
        component = component_from_identity_payload(value)
        try:
            surface = architecture_component_semantic_surface_identity(component)
        except ChassisIdentityError:
            return
        candidates.setdefault(surface, {})[component.identity] = component

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            register(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    for payload in payloads:
        if not isinstance(payload, Mapping):
            raise PortfolioProjectionError("projection registry payload is not an object")
        visit(payload)
    return {
        surface: by_identity[sorted(by_identity)[0]]
        for surface, by_identity in sorted(candidates.items())
    }


def architecture_chassis_from_identity_payload(
    value: Mapping[str, Any],
    components_by_surface: Mapping[str, ComponentSpec],
) -> ArchitectureChassisSpec:
    """Rebuild one semantic chassis and verify its exact durable payload."""

    try:
        normalized = parse_canonical(canonical_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise PortfolioProjectionError("architecture payload is not canonical") from exc
    role_names = {role.value for role in ArchitectureRole}
    if (
        not isinstance(normalized, dict)
        or normalized.get("schema") != "architecture_chassis.v2"
        or set(normalized) != {"roles", "schema"}
        or not isinstance(normalized.get("roles"), dict)
        or set(normalized["roles"]) != role_names
    ):
        raise PortfolioProjectionError("architecture chassis payload is malformed")
    roles: dict[str, ArchitectureRoleSpec] = {}
    for role in ArchitectureRole:
        raw = normalized["roles"][role.value]
        if (
            not isinstance(raw, dict)
            or raw.get("schema") != "architecture_role.v3"
            or raw.get("role") != role.value
            or not isinstance(raw.get("component_semantic_surfaces"), list)
            or not isinstance(raw.get("parameter_bindings"), dict)
            or not isinstance(raw.get("boundary_bindings"), dict)
        ):
            raise PortfolioProjectionError("architecture role payload is malformed")
        surfaces = raw["component_semantic_surfaces"]
        try:
            components = tuple(components_by_surface[surface] for surface in surfaces)
        except (KeyError, TypeError) as exc:
            raise PortfolioProjectionError(
                "architecture component surface is absent from durable manifests"
            ) from exc
        try:
            roles[role.value] = ArchitectureRoleSpec(
                role=role,
                components=components,
                parameter_bindings=tuple(raw["parameter_bindings"].items()),
                boundary_bindings=tuple(raw["boundary_bindings"].items()),
            )
        except (TypeError, ValueError, ChassisIdentityError) as exc:
            raise PortfolioProjectionError("architecture role cannot be rebuilt") from exc
    try:
        chassis = ArchitectureChassisSpec(**roles)
    except (TypeError, ValueError, ChassisIdentityError) as exc:
        raise PortfolioProjectionError("architecture chassis cannot be rebuilt") from exc
    if chassis.to_identity_payload() != normalized:
        raise PortfolioProjectionError("architecture payload changed on rebuild")
    return chassis


def portfolio_axis_from_projection(
    value: Mapping[str, Any],
    components_by_surface: Mapping[str, ComponentSpec],
) -> PortfolioAxis:
    """Rebuild one PortfolioAxis without changing its immutable meaning."""

    try:
        normalized = parse_canonical(canonical_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise PortfolioProjectionError("Portfolio axis payload is not canonical") from exc
    expected_fields = {
        "architecture_chassis",
        "architecture_chassis_identity",
        "axis_id",
        "axis_identity",
        "causal_question",
        "changed_domains",
        "controlled_domains",
        "mechanism_family",
        "primary_research_layer",
        "status",
        "stop_or_reopen_condition",
        "system_architecture_family",
        "why_now",
    }
    if not isinstance(normalized, dict) or set(normalized) != expected_fields:
        raise PortfolioProjectionError("Portfolio axis payload fields are malformed")
    architecture_payload = normalized.get("architecture_chassis")
    architecture = (
        None
        if architecture_payload is None
        else architecture_chassis_from_identity_payload(
            architecture_payload,
            components_by_surface,
        )
    )
    try:
        axis = PortfolioAxis(
            axis_id=normalized["axis_id"],
            causal_question=normalized["causal_question"],
            mechanism_family=normalized["mechanism_family"],
            primary_research_layer=ResearchLayer(
                normalized["primary_research_layer"]
            ),
            system_architecture_family=normalized["system_architecture_family"],
            changed_domains=tuple(
                ResearchLayer(item) for item in normalized["changed_domains"]
            ),
            controlled_domains=tuple(
                ResearchLayer(item) for item in normalized["controlled_domains"]
            ),
            why_now=normalized["why_now"],
            stop_or_reopen_condition=normalized["stop_or_reopen_condition"],
            architecture_chassis=architecture,
            status=normalized["status"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PortfolioProjectionError("Portfolio axis cannot be rebuilt") from exc
    expected = {
        **normalized,
        "architecture_chassis": (
            None if architecture is None else architecture.to_identity_payload()
        ),
        "architecture_chassis_identity": (
            None if architecture is None else architecture.identity
        ),
        "axis_identity": axis.identity,
    }
    if expected != normalized or axis.identity != normalized.get("axis_identity"):
        raise PortfolioProjectionError("Portfolio axis identity changed on rebuild")
    return axis


def portfolio_axes_from_projection(
    values: Iterable[Mapping[str, Any]],
    components_by_surface: Mapping[str, ComponentSpec],
) -> tuple[PortfolioAxis, ...]:
    """Rebuild an ordered, unique Portfolio axis set."""

    axes = tuple(
        portfolio_axis_from_projection(value, components_by_surface)
        for value in values
    )
    if len({axis.axis_id for axis in axes}) != len(axes):
        raise PortfolioProjectionError("Portfolio axis ids are not unique")
    return axes


__all__ = [
    "PortfolioProjectionError",
    "architecture_chassis_from_identity_payload",
    "component_from_identity_payload",
    "component_surface_registry",
    "portfolio_axes_from_projection",
    "portfolio_axis_from_projection",
]
