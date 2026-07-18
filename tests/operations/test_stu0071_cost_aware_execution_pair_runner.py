from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import nullcontext


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import run_stu0071_cost_aware_execution_pair_replay as runner  # noqa: E402

from axiom_rift.operations import bound_fixed_hold_profile  # noqa: E402
from axiom_rift.operations.fixed_hold_replay_workflow import (  # noqa: E402
    ReplayAxisAdmission,
    ReplayInitiativeLifecycle,
)
from axiom_rift.research.semantic_question import (  # noqa: E402
    SemanticQuestionCore,
    SemanticQuestionRelation,
)


def test_spec_binds_successor_obligation_to_its_older_control_family() -> None:
    spec = runner.mission_spec()
    assert spec.mission_id == "MIS-0006"
    assert spec.initiative_id == "INI-0025"
    assert spec.study_id == "STU-0121"
    assert spec.original_study_id == "STU-0071"
    assert spec.effective_family_origin_study_id == "STU-0070"
    assert spec.axis_admission is ReplayAxisAdmission.ADD_NEW_MECHANISM
    assert (
        spec.initiative_lifecycle
        is ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE
    )
    assert spec.axis_id != spec.bridge_axis_id
    assert spec.boundary.sequence == 5669
    assert spec.boundary.event_id == runner.PREDECESSOR_EVENT_ID
    assert spec.replay_obligation_ids == (runner.TARGET_OBLIGATION_ID,)


def test_common_authority_boundary_uses_explicit_family_origin() -> None:
    spec = runner.mission_spec()
    family = SimpleNamespace(original_study_id="STU-0070")
    authority = SimpleNamespace(
        identity=runner.HISTORICAL_FAMILY_AUTHORITY_ID,
        replay_obligation_id=runner.TARGET_OBLIGATION_ID,
        family=family,
        reconstruction_source_path="source.py",
        reconstruction_source_sha256="a" * 64,
        reconstruction_only_parameter_names=(),
    )
    record = SimpleNamespace(
        record_id=authority.identity,
        status="accepted",
        subject="ReplayObligation:" + runner.TARGET_OBLIGATION_ID,
    )
    index = SimpleNamespace(get=lambda kind, record_id: record)
    writer = SimpleNamespace(
        open_stable_index=lambda: nullcontext(({}, index))
    )
    with (
        patch.object(
            bound_fixed_hold_profile,
            "require_recorded_historical_family_authority",
            return_value=authority,
        ),
        patch.object(
            bound_fixed_hold_profile,
            "historical_family_core_identity",
            return_value="historical-family-core:test",
        ),
    ):
        values = (
            bound_fixed_hold_profile.require_bound_fixed_hold_family_authorities(
                writer,
                spec=spec,
                historical_family_authority_id=authority.identity,
            )
        )
    assert values == (authority,)


def test_build_design_derives_semantic_revision_without_result_transfer() -> None:
    question = {
        "causal_question": "corrected completed-bar policy question",
        "changed_variables": ["execution"],
        "controlled_variables": ["feature", "label"],
    }
    preliminary = SimpleNamespace(question=question)
    final = SimpleNamespace(question=question)
    accepted = object()
    writer = Mock()
    with (
        patch.object(runner, "_profile_design", side_effect=(preliminary, final))
        as profile,
        patch.object(
            runner,
            "require_borrowed_production_profile",
            return_value=accepted,
        ) as require_profile,
    ):
        result = runner.build_design(writer)

    assert result is accepted
    lineage = profile.call_args_list[1].kwargs["lineage"]
    assert lineage.predecessor_study_id == "STU-0071"
    assert lineage.successor_study_id == "STU-0121"
    assert lineage.predecessor_core_id == runner.PREDECESSOR_CORE_ID
    assert lineage.successor_core_id == (
        SemanticQuestionCore.from_question_manifest(question).identity
    )
    assert lineage.relation is SemanticQuestionRelation.SEMANTIC_REVISION
    assert lineage.basis_record_ids == (
        "study-close:" + runner.PREDECESSOR_CLOSE_RECORD_ID,
        "study-open:STU-0071",
    )
    require_profile.assert_called_once_with(writer, final)
