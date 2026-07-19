"""Additive prospective architecture-family projection for Portfolio axes.

The Portfolio and chassis identities already in the journal are immutable.  A
new scheduler family therefore travels beside a Portfolio snapshot instead of
being inserted into its identity payload.  Older reconstructed v2 chassis do
not contain the Component manifests required by the v4 semantic projection;
their prior projection is retained when available and otherwise callers fall
back to the historical family boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from axiom_rift.research.chassis import (
    ChassisIdentityError,
    prospective_architecture_family_identity_from_chassis,
)


PROJECTION_FIELD = "prospective_architecture_projection"
PROJECTION_SCHEMA = "portfolio_axis_architecture_semantic.v1"


class ProspectiveArchitectureProjectionError(ValueError):
    """Raised when an additive snapshot projection is internally inconsistent."""


def derive_axis_families(snapshot: Any) -> dict[str, str]:
    """Derive every v4 family available from a live typed snapshot.

    A chassis reconstructed only from its immutable v2 payload intentionally
    has no Component context.  Such an axis is omitted so legacy replay can use
    its established fallback without inventing semantic information.
    """

    families: dict[str, str] = {}
    for axis in getattr(snapshot, "axes", ()):
        axis_identity = getattr(axis, "identity", None)
        chassis = getattr(axis, "architecture_chassis", None)
        if not isinstance(axis_identity, str) or chassis is None:
            continue
        try:
            family = prospective_architecture_family_identity_from_chassis(chassis)
        except ChassisIdentityError as exc:
            if "lacks prospective Component manifests" not in str(exc):
                raise ProspectiveArchitectureProjectionError(str(exc)) from exc
            continue
        prior = families.get(axis_identity)
        if prior is not None and prior != family:
            raise ProspectiveArchitectureProjectionError(
                "one Portfolio axis resolves to conflicting semantic families"
            )
        families[axis_identity] = family
    return dict(sorted(families.items()))


def projection_payload(
    *,
    current_axis_identities: set[str],
    derived_families: Mapping[str, str],
    prior_payload: object = None,
) -> dict[str, object]:
    """Build a canonical projection, carrying only still-current legacy rows."""

    merged: dict[str, str] = {}
    if prior_payload is not None:
        if not isinstance(prior_payload, Mapping):
            raise ProspectiveArchitectureProjectionError(
                "prospective architecture projection is malformed"
            )
        if prior_payload.get("schema") != PROJECTION_SCHEMA:
            raise ProspectiveArchitectureProjectionError(
                "prospective architecture projection schema is unsupported"
            )
        prior_families = prior_payload.get("axis_families")
        if not isinstance(prior_families, Mapping):
            raise ProspectiveArchitectureProjectionError(
                "prospective architecture family inventory is malformed"
            )
        for axis_identity, family in prior_families.items():
            if (
                not isinstance(axis_identity, str)
                or not isinstance(family, str)
                or not family.startswith("architecture-family:")
            ):
                raise ProspectiveArchitectureProjectionError(
                    "prospective architecture family row is malformed"
                )
            if axis_identity in current_axis_identities:
                merged[axis_identity] = family

    for axis_identity, family in derived_families.items():
        if axis_identity not in current_axis_identities:
            raise ProspectiveArchitectureProjectionError(
                "prospective architecture family names a non-current axis"
            )
        prior = merged.get(axis_identity)
        if prior is not None and prior != family:
            raise ProspectiveArchitectureProjectionError(
                "Portfolio axis semantic family changed without a new identity"
            )
        merged[axis_identity] = family

    return {
        "axis_families": dict(sorted(merged.items())),
        "schema": PROJECTION_SCHEMA,
    }


def family_for_axis(snapshot_payload: Mapping[str, Any], axis: Mapping[str, Any]) -> str | None:
    """Read one validated v4 family from a durable snapshot projection."""

    raw_projection = snapshot_payload.get(PROJECTION_FIELD)
    if raw_projection is None:
        return None
    normalized = projection_payload(
        current_axis_identities={
            candidate["axis_identity"]
            for candidate in snapshot_payload.get("axes", [])
            if isinstance(candidate, Mapping)
            and isinstance(candidate.get("axis_identity"), str)
        },
        derived_families={},
        prior_payload=raw_projection,
    )
    axis_identity = axis.get("axis_identity")
    if not isinstance(axis_identity, str):
        raise ProspectiveArchitectureProjectionError(
            "Portfolio axis identity is malformed"
        )
    families = normalized["axis_families"]
    assert isinstance(families, dict)
    return families.get(axis_identity)


__all__ = [
    "PROJECTION_FIELD",
    "PROJECTION_SCHEMA",
    "ProspectiveArchitectureProjectionError",
    "derive_axis_families",
    "family_for_axis",
    "projection_payload",
]
