"""Run the Writer-bound P0 drawdown correction replay."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.drawdown_fixed_hold_profile import (  # noqa: E402
    build_drawdown_fixed_hold_profile_design,
)
from axiom_rift.operations.fixed_hold_replay_cli import (  # noqa: E402
    run_fixed_hold_replay_command,
)
from axiom_rift.operations.fixed_hold_replay_profile import (  # noqa: E402
    require_borrowed_production_profile,
)
from axiom_rift.operations.fixed_hold_replay_workflow import (  # noqa: E402
    FixedHoldReplayMissionSpec,
    ReplayAuthorityBoundary,
    ReplayAxisAdmission,
    ReplayInitiativeLifecycle,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.drawdown_state_replay_job import (  # noqa: E402
    CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL,
    drawdown_replay_job_implementation_sha256,
    execute_drawdown_state_replay_job,
    materialize_drawdown_replay_job_implementation,
)
from axiom_rift.research.semantic_question import (  # noqa: E402
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)


MISSION_ID = "MIS-0006"
INITIATIVE_ID = "INI-0025"
STUDY_ID = "STU-0115"
BATCH_DISPLAY_ID = "BAT-0115"
TARGET_OBLIGATION_ID = (
    "historical-replay-obligation:"
    "c537b4ebc7085331cd21e52c26fbc994728c0520d5474473cc246f4e8c85322e"
)
HISTORICAL_FAMILY_AUTHORITY_ID = (
    "historical-family-authority:"
    "d166d3ac4dd728de2c7968021c806908836e6f5bf9a78049e0d033b214fd64ab"
)
EXPECTED_ARCHITECTURE_FAMILY = (
    "architecture-family:"
    "383b1a114d80c3b1d6755424bc012b806ab904d3bd21ed744ceed0bcba0eac3f"
)
PREDECESSOR_STUDY_ID = "STU-0107"
PREDECESSOR_CORE_ID = (
    "semantic-question-core:"
    "f10a3415d7383753894bf019342ca6ca268e1cc9f6e64b21fa8bae160e3ebeea"
)
PREDECESSOR_CLOSE_RECORD_ID = (
    "a85cc4400d667d1294806f6b621df96ed61161e86d3562bd5833b8b56790a5e3"
)
PREDECESSOR_REVISION = 5452
PREDECESSOR_EVENT_ID = (
    "6002ec29ea39a8eb4184edb1d0316d127131988b4079d680575d4796446db444"
)
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"


def mission_spec() -> FixedHoldReplayMissionSpec:
    return FixedHoldReplayMissionSpec(
        axis_admission=ReplayAxisAdmission.REVISE_PROTOCOL,
        initiative_lifecycle=ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE,
        mission_id=MISSION_ID,
        initiative_id=INITIATIVE_ID,
        study_id=STUDY_ID,
        batch_display_id=BATCH_DISPLAY_ID,
        axis_id="axis-stu0048-drawdown-state-replay-bridge",
        bridge_axis_id="axis-stu0048-drawdown-state-replay-bridge",
        operation_prefix="p0-stu0048-completed-bar-replay-v3-",
        decision_prefix="DEC-P0-STU0048-COMPLETED-BAR-V3",
        target_obligation_id=TARGET_OBLIGATION_ID,
        original_study_id="STU-0048",
        job_protocol=JOB_IMPLEMENTATION_PROTOCOL,
        callable_identity=CALLABLE_IDENTITY,
        job_implementation_identity=drawdown_replay_job_implementation_sha256(),
        permit_expiry_utc=PERMIT_EXPIRY_UTC,
        boundary=ReplayAuthorityBoundary(
            sequence=PREDECESSOR_REVISION,
            event_id=PREDECESSOR_EVENT_ID,
        ),
        display_name="STU-0048 completed-bar P0 correction replay family",
    )


def semantic_question_lineage() -> SemanticQuestionLineageProposal:
    return SemanticQuestionLineageProposal(
        predecessor_study_id=PREDECESSOR_STUDY_ID,
        successor_study_id=STUDY_ID,
        predecessor_core_id=PREDECESSOR_CORE_ID,
        successor_core_id=PREDECESSOR_CORE_ID,
        relation=SemanticQuestionRelation.CONTINUATION,
        rationale=(
            "Repeat the same causal question after the point-in-time audit "
            "invalidated the prior replay satisfaction."
        ),
        basis_record_ids=(
            f"study-open:{PREDECESSOR_STUDY_ID}",
            f"study-close:{PREDECESSOR_CLOSE_RECORD_ID}",
        ),
    )


def build_design(writer: StateWriter):
    design = build_drawdown_fixed_hold_profile_design(
        writer,
        spec=mission_spec(),
        historical_family_authority_id=HISTORICAL_FAMILY_AUTHORITY_ID,
        semantic_question_lineage=semantic_question_lineage(),
    )
    if (
        design.controlled_chassis.architecture_family
        != EXPECTED_ARCHITECTURE_FAMILY
    ):
        raise RuntimeError("drawdown corrected architecture family drifted")
    return require_borrowed_production_profile(writer, design)


def main(argv: Sequence[str] | None = None) -> None:
    summary = run_fixed_hold_replay_command(
        repository_root=ROOT,
        design_builder=build_design,
        job_runner=execute_drawdown_state_replay_job,
        job_implementation_materializer=(
            materialize_drawdown_replay_job_implementation
        ),
        study_id=STUDY_ID,
        argv=argv,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
