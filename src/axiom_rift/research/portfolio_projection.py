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
from axiom_rift.core.component_surface import (
    ComponentManifestError,
    component_spec_from_manifest,
)
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ArchitectureRole,
    ArchitectureRoleSpec,
    ChassisIdentityError,
    architecture_component_semantic_surface_identity,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.portfolio import (
    DecisionBasisRecord,
    DecisionLens,
    DecisionLensAssessment,
    DecisionLensPosition,
    DecisionOption,
    PortfolioAction,
    PortfolioAxis,
    PortfolioDecision,
    QuantTeamDecisionReview,
)
from axiom_rift.research.axis_protocol_revision import (
    AxisProtocolRevisionProposal,
)


class PortfolioProjectionError(ValueError):
    """Raised when durable Portfolio identity cannot be reconstructed exactly."""


def component_from_identity_payload(value: Mapping[str, Any]) -> ComponentSpec:
    """Rebuild one ComponentSpec and prove exact identity-payload equivalence."""

    try:
        return component_spec_from_manifest(
            value,
            display_name="rehydrated durable architecture component",
        )
    except ComponentManifestError as exc:
        raise PortfolioProjectionError("component identity cannot be rebuilt") from exc


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


def executable_from_identity_payload(value: Mapping[str, Any]) -> ExecutableSpec:
    """Rebuild one ExecutableSpec and prove exact payload equivalence."""

    try:
        normalized = parse_canonical(canonical_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise PortfolioProjectionError("Executable payload is not canonical") from exc
    expected_fields = {
        "clock_contract",
        "component_identities",
        "component_manifests",
        "cost_contract",
        "data_contract",
        "engine_contract",
        "parameters",
        "schema",
        "source_contracts",
        "split_contract",
    }
    if (
        not isinstance(normalized, dict)
        or normalized.get("schema") != "executable_spec.v1"
        or set(normalized) != expected_fields
        or not isinstance(normalized.get("component_manifests"), list)
        or not isinstance(normalized.get("component_identities"), list)
        or not isinstance(normalized.get("source_contracts"), list)
    ):
        raise PortfolioProjectionError("Executable identity payload is malformed")
    try:
        components = tuple(
            component_from_identity_payload(item)
            for item in normalized["component_manifests"]
        )
        executable = ExecutableSpec(
            display_name="rehydrated durable Portfolio baseline",
            components=components,
            parameters=normalized["parameters"],
            data_contract=normalized["data_contract"],
            split_contract=normalized["split_contract"],
            clock_contract=normalized["clock_contract"],
            cost_contract=normalized["cost_contract"],
            engine_contract=normalized["engine_contract"],
            source_contracts=tuple(normalized["source_contracts"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PortfolioProjectionError("Executable identity cannot be rebuilt") from exc
    if (
        executable.to_identity_payload() != normalized
        or list(executable.component_identities)
        != normalized["component_identities"]
    ):
        raise PortfolioProjectionError("Executable payload changed on rebuild")
    return executable


def portfolio_decision_from_projection(
    value: Mapping[str, Any],
) -> PortfolioDecision:
    """Rebuild a legacy or replay-bound Portfolio Decision exactly."""

    try:
        normalized = parse_canonical(canonical_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise PortfolioProjectionError("Portfolio Decision is not canonical") from exc
    base_fields = {
        "architecture_chassis",
        "architecture_chassis_identity",
        "baseline_executable",
        "baseline_executable_id",
        "chosen_option_id",
        "commitment_batches",
        "decision_id",
        "locks_future_portfolio",
        "options",
        "rationale",
        "recent_positive_lineage_id",
        "schema",
    }
    allowed_fields = (
        base_fields,
        base_fields | {"replay_obligation_ids"},
        base_fields | {"quant_team_review"},
        base_fields | {"quant_team_review", "replay_obligation_ids"},
        base_fields
        | {
            "protocol_revision",
            "protocol_revision_id",
            "replay_obligation_ids",
        },
        base_fields
        | {
            "protocol_revision",
            "protocol_revision_id",
            "quant_team_review",
            "replay_obligation_ids",
        },
    )
    if (
        not isinstance(normalized, dict)
        or set(normalized) not in allowed_fields
        or normalized.get("schema") not in {
            "portfolio_decision.v1",
            "portfolio_decision.v2",
            "portfolio_decision.v3",
            "portfolio_decision.v4",
        }
        or (
            normalized.get("schema") == "portfolio_decision.v3"
            and "quant_team_review" not in normalized
        )
        or (
            normalized.get("schema")
            in {"portfolio_decision.v1", "portfolio_decision.v2"}
            and "quant_team_review" in normalized
        )
        or (
            normalized.get("schema") == "portfolio_decision.v4"
        )
        != ("protocol_revision" in normalized)
        or not isinstance(normalized.get("options"), list)
    ):
        raise PortfolioProjectionError("Portfolio Decision fields are malformed")
    try:
        options = tuple(
            DecisionOption(
                option_id=item["option_id"],
                action=PortfolioAction(item["action"]),
                target_id=item["target_id"],
                expected_information_value=item["expected_information_value"],
                opportunity_cost=item["opportunity_cost"],
                omission_reason=item["omission_reason"],
            )
            for item in normalized["options"]
        )
        baseline_payload = normalized["baseline_executable"]
        baseline = (
            None
            if baseline_payload is None
            else executable_from_identity_payload(baseline_payload)
        )
        review_payload = normalized.get("quant_team_review")
        if review_payload is not None and (
            not isinstance(review_payload, dict)
            or set(review_payload)
            != {
                "assessments",
                "claim_boundary",
                "disagreement_resolution",
                "resolution_basis",
                "schema",
            }
            or review_payload.get("schema")
            != "quant_team_decision_review.v1"
            or not isinstance(review_payload.get("assessments"), list)
        ):
            raise PortfolioProjectionError(
                "quant-team Decision review is malformed"
            )
        if review_payload is not None:
            for item in review_payload["assessments"]:
                if (
                    not isinstance(item, dict)
                    or set(item)
                    != {
                        "basis_records",
                        "finding",
                        "lens",
                        "option_ids",
                        "position",
                    }
                    or not isinstance(item.get("basis_records"), list)
                    or not isinstance(item.get("option_ids"), list)
                    or any(
                        not isinstance(basis, dict)
                        or set(basis) != {"kind", "record_id"}
                        for basis in item.get("basis_records", [])
                    )
                ):
                    raise PortfolioProjectionError(
                        "quant-team lens assessment is malformed"
                    )
        review = (
            None
            if review_payload is None
            else QuantTeamDecisionReview(
                assessments=tuple(
                    DecisionLensAssessment(
                        lens=DecisionLens(item["lens"]),
                        position=DecisionLensPosition(item["position"]),
                        option_ids=tuple(item["option_ids"]),
                        basis_records=tuple(
                            DecisionBasisRecord(
                                kind=basis["kind"],
                                record_id=basis["record_id"],
                            )
                            for basis in item["basis_records"]
                        ),
                        finding=item["finding"],
                    )
                    for item in review_payload["assessments"]
                ),
                claim_boundary=review_payload["claim_boundary"],
                resolution_basis=review_payload["resolution_basis"],
                disagreement_resolution=review_payload[
                    "disagreement_resolution"
                ],
            )
        )
        revision_payload = normalized.get("protocol_revision")
        protocol_revision = (
            None
            if revision_payload is None
            else AxisProtocolRevisionProposal.from_mapping(revision_payload)
        )
        if (
            protocol_revision is not None
            and normalized.get("protocol_revision_id")
            != protocol_revision.identity
        ):
            raise PortfolioProjectionError(
                "axis protocol revision identity drifted"
            )
        decision = PortfolioDecision(
            decision_id=normalized["decision_id"],
            chosen_option_id=normalized["chosen_option_id"],
            options=options,
            rationale=normalized["rationale"],
            commitment_batches=normalized["commitment_batches"],
            quant_team_review=review,
            baseline_executable=baseline,
            replay_obligation_ids=tuple(
                normalized.get("replay_obligation_ids", ())
            ),
            protocol_revision=protocol_revision,
            recent_positive_lineage_id=normalized["recent_positive_lineage_id"],
            locks_future_portfolio=normalized["locks_future_portfolio"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PortfolioProjectionError("Portfolio Decision cannot be rebuilt") from exc
    if (
        decision.to_identity_payload() != normalized
        or (None if baseline is None else baseline.identity)
        != normalized.get("baseline_executable_id")
        or (
            None
            if decision.architecture_chassis is None
            else decision.architecture_chassis.identity
        )
        != normalized.get("architecture_chassis_identity")
        or (
            None
            if decision.architecture_chassis is None
            else decision.architecture_chassis.to_identity_payload()
        )
        != normalized.get("architecture_chassis")
    ):
        raise PortfolioProjectionError(
            "Portfolio Decision identity payload changed on rebuild"
        )
    return decision


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


def architecture_surfaces_from_axis_projection(
    values: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return the exact architecture Component surfaces needed to rehydrate axes."""

    surfaces: set[str] = set()
    for value in values:
        if not isinstance(value, Mapping):
            raise PortfolioProjectionError("Portfolio axis projection is not an object")
        architecture = value.get("architecture_chassis")
        if architecture is None:
            continue
        if (
            not isinstance(architecture, Mapping)
            or architecture.get("schema") != "architecture_chassis.v2"
            or not isinstance(architecture.get("roles"), Mapping)
        ):
            raise PortfolioProjectionError("architecture chassis payload is malformed")
        for role in architecture["roles"].values():
            if not isinstance(role, Mapping) or not isinstance(
                role.get("component_semantic_surfaces"), list
            ):
                raise PortfolioProjectionError("architecture role payload is malformed")
            for surface in role["component_semantic_surfaces"]:
                digest = (
                    ""
                    if not isinstance(surface, str)
                    else surface.removeprefix("architecture-component-surface:")
                )
                if (
                    not isinstance(surface, str)
                    or not surface.startswith("architecture-component-surface:")
                    or len(digest) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in digest
                    )
                ):
                    raise PortfolioProjectionError(
                        "architecture Component surface identity is malformed"
                    )
                surfaces.add(surface)
    return tuple(sorted(surfaces))


__all__ = [
    "PortfolioProjectionError",
    "architecture_chassis_from_identity_payload",
    "architecture_surfaces_from_axis_projection",
    "component_from_identity_payload",
    "component_surface_registry",
    "executable_from_identity_payload",
    "portfolio_axes_from_projection",
    "portfolio_axis_from_projection",
    "portfolio_decision_from_projection",
]
