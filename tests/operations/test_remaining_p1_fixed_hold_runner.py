from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import run_remaining_p1_fixed_hold_family as runner  # noqa: E402

from axiom_rift.operations.fixed_hold_replay_workflow import (  # noqa: E402
    FixedHoldReplayMissionSpec,
    ReplayAxisAdmission,
    ReplayAuthorityBoundary,
    ReplayInitiativeLifecycle,
    _require_new_axis_diagnosis_compatibility,
)
from axiom_rift.research.governance import ResearchLayer  # noqa: E402
from axiom_rift.research.portfolio import PortfolioAction  # noqa: E402


def _authority(name: str, ordinal: int) -> runner.RunAuthority:
    return runner.RunAuthority(
        route=runner.FAMILY_ROUTES[name],
        study_id=f"STU-{ordinal:04d}",
        batch_display_id=f"BAT-{ordinal:04d}",
        predecessor_revision=5_492,
        predecessor_event_id="a" * 64,
    )


def test_routes_cover_four_disjoint_exact_families() -> None:
    assert set(runner.FAMILY_ROUTES) == {
        "stu0046",
        "stu0047",
        "stu0049",
        "stu0050",
    }
    obligations = []
    axes = []
    for route in runner.FAMILY_ROUTES.values():
        obligations.extend(
            (route.primary_obligation_id, *route.additional_obligation_ids)
        )
        axes.append(route.axis_id)
        assert len(route.additional_family_authority_ids) == 3
    assert len(obligations) == len(set(obligations)) == 16
    assert len(axes) == len(set(axes)) == 4


def test_every_route_borrows_one_active_initiative_and_adds_a_mechanism() -> None:
    for ordinal, name in enumerate(sorted(runner.FAMILY_ROUTES), start=116):
        spec = runner.mission_spec(_authority(name, ordinal))
        assert spec.mission_id == "MIS-0006"
        assert spec.initiative_id == "INI-0025"
        assert (
            spec.initiative_lifecycle
            is ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE
        )
        assert spec.axis_admission is ReplayAxisAdmission.ADD_NEW_MECHANISM
        assert spec.new_axis_action is PortfolioAction.CONTRAST
        assert spec.axis_id != spec.bridge_axis_id
        assert len(spec.replay_obligation_ids) == 4


def test_new_axis_action_is_typed_separately_from_structural_admission() -> None:
    route = runner.FAMILY_ROUTES["stu0046"]
    values = dict(
        mission_id="MIS-0006",
        initiative_id="INI-0025",
        study_id="STU-0116",
        batch_display_id="BAT-0116",
        axis_id=route.axis_id,
        bridge_axis_id=route.bridge_axis_id,
        operation_prefix=route.operation_prefix,
        decision_prefix=route.decision_prefix,
        target_obligation_id=route.primary_obligation_id,
        original_study_id=route.original_study_id,
        job_protocol=route.job_protocol,
        callable_identity=route.callable_identity,
        job_implementation_identity=route.implementation_identity_builder(),
        permit_expiry_utc=runner.PERMIT_EXPIRY_UTC,
        boundary=ReplayAuthorityBoundary(sequence=5_492, event_id="c" * 64),
        display_name=route.display_name,
        initiative_lifecycle=(
            ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE
        ),
        axis_admission=ReplayAxisAdmission.ADD_NEW_MECHANISM,
    )
    defaulted = FixedHoldReplayMissionSpec(**values)
    assert defaulted.new_axis_action is None
    assert defaulted.resolved_new_axis_action is PortfolioAction.NEW_MECHANISM
    try:
        FixedHoldReplayMissionSpec(
            **values,
            new_axis_action=PortfolioAction.PRESERVE,
        )
    except ValueError as exc:
        assert "diversifying Portfolio action" in str(exc)
    else:
        raise AssertionError("non-diversifying new-axis action was accepted")


def test_diagnosis_compatibility_is_proved_before_first_mutation() -> None:
    diagnosis_id = "diagnosis:" + "d" * 64
    diagnosis = SimpleNamespace(
        payload={
            "allowed_actions": ["contrast"],
            "allowed_research_layers": ["synthesis"],
            "portfolio_axis_id": "axis-source",
            "system_architecture_family": "architecture-family:source",
        }
    )
    index = SimpleNamespace(get=lambda kind, record_id: diagnosis)
    control = {"next_action": {"study_diagnosis_id": diagnosis_id}}
    target = SimpleNamespace(
        axis_id="axis-target",
        primary_research_layer=ResearchLayer.SYNTHESIS,
        system_architecture_family="architecture-family:target",
    )
    projected = {
        "axis-source": {
            "primary_research_layer": "synthesis",
        }
    }
    with pytest.raises(RuntimeError, match="cannot structurally exit"):
        _require_new_axis_diagnosis_compatibility(
            control=control,
            index=index,
            action=PortfolioAction.NEW_MECHANISM,
            target_axis=target,
            projected_axes=projected,
        )
    _require_new_axis_diagnosis_compatibility(
        control=control,
        index=index,
        action=PortfolioAction.CONTRAST,
        target_axis=target,
        projected_axes=projected,
    )


def test_cli_authority_is_explicit_and_preserves_remaining_stage_arguments() -> None:
    authority, remaining = runner.parse_arguments(
        (
            "--family",
            "stu0046",
            "--study-id",
            "STU-0116",
            "--batch-display-id",
            "BAT-0116",
            "--predecessor-revision",
            "5492",
            "--predecessor-event-id",
            "b" * 64,
            "--stage",
            "study-close",
        )
    )
    assert authority.route.name == "stu0046"
    assert authority.study_id == "STU-0116"
    assert authority.predecessor_revision == 5_492
    assert remaining == ["--stage", "study-close"]
