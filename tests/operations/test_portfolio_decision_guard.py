from __future__ import annotations

import pytest

from axiom_rift.operations.portfolio_decision_guard import (
    PortfolioDecisionGuardError,
    StructuralAxisSignature,
    require_replay_forest_alternative,
)
from axiom_rift.research.portfolio import (
    DecisionOption,
    PortfolioAction,
    PortfolioDecision,
)


def _decision() -> PortfolioDecision:
    return PortfolioDecision(
        decision_id="PFD-GUARD",
        chosen_option_id="replay",
        options=(
            DecisionOption(
                option_id="replay",
                action=PortfolioAction.CONTRAST,
                target_id="AX-REPLAY",
                expected_information_value="close exact replay debt",
                opportunity_cost="defers an unrelated branch",
            ),
            DecisionOption(
                option_id="forest",
                action=PortfolioAction.ROTATE,
                target_id="AX-FOREST",
                expected_information_value="test a structural alternative",
                opportunity_cost="defers the replay branch",
                omission_reason="replay has the current priority",
            ),
        ),
        rationale="compare replay against a genuine forest branch",
        commitment_batches=1,
    )


def _signature(
    axis: str,
    *,
    layer: str = "model",
    family: str | None = "architecture-family:" + "a" * 64,
) -> StructuralAxisSignature:
    return StructuralAxisSignature(
        axis_identity="axis:" + axis,
        primary_research_layer=layer,
        semantic_architecture_family=family,
    )


def test_replay_same_layer_and_same_semantic_family_is_rejected() -> None:
    decision = _decision()
    with pytest.raises(PortfolioDecisionGuardError, match="structural alternative"):
        require_replay_forest_alternative(
            decision,
            replay_bound=True,
            option_signatures={
                "replay": _signature("replay"),
                "forest": _signature("forest"),
            },
        )


def test_replay_different_primary_layer_is_a_genuine_alternative() -> None:
    decision = _decision()
    require_replay_forest_alternative(
        decision,
        replay_bound=True,
        option_signatures={
            "replay": _signature("replay"),
            "forest": _signature("forest", layer="execution"),
        },
    )


def test_replay_same_layer_different_semantic_family_is_admitted() -> None:
    decision = _decision()
    require_replay_forest_alternative(
        decision,
        replay_bound=True,
        option_signatures={
            "replay": _signature("replay"),
            "forest": _signature(
                "forest", family="architecture-family:" + "b" * 64
            ),
        },
    )


def test_same_layer_unknown_family_cannot_pretend_to_be_structural() -> None:
    decision = _decision()
    with pytest.raises(PortfolioDecisionGuardError):
        require_replay_forest_alternative(
            decision,
            replay_bound=True,
            option_signatures={
                "replay": _signature("replay"),
                "forest": _signature("forest", family=None),
            },
        )


def test_non_replay_decision_is_not_subject_to_a_rotation_quota() -> None:
    require_replay_forest_alternative(
        _decision(),
        replay_bound=False,
        option_signatures={},
    )


def test_same_axis_with_a_different_label_is_not_a_forest_exit() -> None:
    decision = _decision()
    same = _signature("same", layer="execution")
    with pytest.raises(PortfolioDecisionGuardError):
        require_replay_forest_alternative(
            decision,
            replay_bound=True,
            option_signatures={"replay": same, "forest": same},
        )
