"""Prospective forest-quality checks for replay-bound Portfolio decisions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from axiom_rift.research.portfolio import PortfolioAction, PortfolioDecision


_STRUCTURAL_ACTIONS = frozenset(
    {
        PortfolioAction.COMPLEMENTARY_SLEEVE,
        PortfolioAction.CONTRAST,
        PortfolioAction.NEW_MECHANISM,
        PortfolioAction.RECOMBINE,
        PortfolioAction.ROTATE,
        PortfolioAction.SYNTHESIZE,
    }
)


class PortfolioDecisionGuardError(ValueError):
    """A replay-bound option set does not contain a genuine forest exit."""


@dataclass(frozen=True, slots=True)
class StructuralAxisSignature:
    """The minimum verified structure needed to compare two option targets."""

    axis_identity: str
    primary_research_layer: str
    semantic_architecture_family: str | None

    def __post_init__(self) -> None:
        for name in ("axis_identity", "primary_research_layer"):
            value = getattr(self, name)
            if type(value) is not str or not value or not value.isascii():
                raise PortfolioDecisionGuardError(
                    f"{name} must be non-empty ASCII"
                )
        family = self.semantic_architecture_family
        if family is not None and (
            type(family) is not str or not family or not family.isascii()
        ):
            raise PortfolioDecisionGuardError(
                "semantic_architecture_family must be ASCII when present"
            )


def require_replay_forest_alternative(
    decision: PortfolioDecision,
    *,
    replay_bound: bool,
    option_signatures: Mapping[str, StructuralAxisSignature | None],
) -> None:
    """Require one unchosen option outside the replay branch's structure.

    This is deliberately not a calendar or consecutive-run quota.  It checks
    the quality of the current choice set: a different primary research layer
    is enough, while a same-layer alternative must prove a different semantic
    architecture family.  Unknown same-layer families fail closed.
    """

    if not isinstance(decision, PortfolioDecision):
        raise TypeError("decision must be a PortfolioDecision")
    if type(replay_bound) is not bool:
        raise TypeError("replay_bound must be bool")
    if not replay_bound:
        return
    if set(option_signatures) != {
        option.option_id for option in decision.options
    }:
        raise PortfolioDecisionGuardError(
            "replay option signatures do not match the exact option set"
        )
    chosen = option_signatures.get(decision.chosen_option_id)
    if chosen is None:
        raise PortfolioDecisionGuardError(
            "replay chosen option lacks a verified structural signature"
        )
    for option in decision.options:
        if (
            option.option_id == decision.chosen_option_id
            or option.action not in _STRUCTURAL_ACTIONS
        ):
            continue
        alternative = option_signatures.get(option.option_id)
        if alternative is None or alternative.axis_identity == chosen.axis_identity:
            continue
        different_layer = (
            alternative.primary_research_layer
            != chosen.primary_research_layer
        )
        different_family = (
            alternative.semantic_architecture_family is not None
            and chosen.semantic_architecture_family is not None
            and alternative.semantic_architecture_family
            != chosen.semantic_architecture_family
        )
        if different_layer or different_family:
            return
    raise PortfolioDecisionGuardError(
        "replay-bound Portfolio decision must retain an unchosen structural "
        "alternative from a different primary layer or semantic architecture"
    )


__all__ = [
    "PortfolioDecisionGuardError",
    "StructuralAxisSignature",
    "require_replay_forest_alternative",
]
