from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import run_remaining_p1_fixed_hold_family as runner  # noqa: E402

from axiom_rift.operations.fixed_hold_replay_workflow import (  # noqa: E402
    ReplayAxisAdmission,
    ReplayInitiativeLifecycle,
)


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
        assert spec.axis_id != spec.bridge_axis_id
        assert len(spec.replay_obligation_ids) == 4


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
