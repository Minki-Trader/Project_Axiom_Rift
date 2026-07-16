"""Run the fresh P0 completed-bar correction replay for STU-0051."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.fixed_hold_replay_cli import (  # noqa: E402
    run_fixed_hold_replay_command,
)
from axiom_rift.operations.fixed_hold_replay_profile import (  # noqa: E402
    require_borrowed_production_profile,
)
from axiom_rift.operations.fixed_hold_replay_workflow import (  # noqa: E402
    FixedHoldReplayMissionSpec,
    ReplayAxisAdmission,
    ReplayAuthorityBoundary,
    ReplayInitiativeLifecycle,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.semantic_question import (  # noqa: E402
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)
from axiom_rift.research.volatility_duration_replay_job import (  # noqa: E402
    CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL,
    execute_volatility_duration_replay_job,
    materialize_volatility_duration_replay_job_implementation,
    volatility_duration_replay_job_implementation_sha256,
)
from axiom_rift.operations.volatility_duration_replay_profile import (  # noqa: E402
    build_volatility_duration_replay_profile_design,
)


MISSION_ID = "MIS-0006"
INITIATIVE_ID = "INI-0025"
STUDY_ID = "STU-0113"
BATCH_DISPLAY_ID = "BAT-0113"
TARGET_OBLIGATION_ID = (
    "historical-replay-obligation:"
    "a8da0fda7ff53c1951c59bf2bdc4fb8db722cf21c2090dd2e5220c5d2069a904"
)
HISTORICAL_FAMILY_AUTHORITY_ID = (
    "historical-family-authority:"
    "a1996ed0e967f188c6a68fa8ef512996d7754d998f829961e6872107b145bea3"
)
EXPECTED_ARCHITECTURE_FAMILY = (
    "architecture-family:"
    "3486a02996a7b9500bfef8b4fec8ddd5c8c641cf2c506ef81a4f671e9233a48c"
)
PREDECESSOR_STUDY_ID = "STU-0108"
PREDECESSOR_CORE_ID = (
    "semantic-question-core:"
    "c37c2ce1bdb5942d70b3380603dacc07733c8cd52bafd43ca0dc9645af20d408"
)
PREDECESSOR_CLOSE_RECORD_ID = (
    "225ce0ee1d3d504b58553a03171f6d1b4076cdada29e279230bbdbe9cd0d76a8"
)
PREDECESSOR_REVISION = 5394
PREDECESSOR_EVENT_ID = (
    "cf68a2c0a29b78ea6f52a8fce3b859b1dd5068347b1701b7ee0e981cd92c9bbf"
)
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"


def mission_spec() -> FixedHoldReplayMissionSpec:
    return FixedHoldReplayMissionSpec(
        axis_admission=ReplayAxisAdmission.REVISE_PROTOCOL,
        initiative_lifecycle=(
            ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE
        ),
        mission_id=MISSION_ID,
        initiative_id=INITIATIVE_ID,
        study_id=STUDY_ID,
        batch_display_id=BATCH_DISPLAY_ID,
        axis_id="axis-stu0051-volatility-duration-replay-bridge",
        bridge_axis_id="axis-stu0051-volatility-duration-replay-bridge",
        operation_prefix="p0-stu0051-completed-bar-replay-v2-",
        decision_prefix="DEC-P0-STU0051-COMPLETED-BAR-V2",
        target_obligation_id=TARGET_OBLIGATION_ID,
        original_study_id="STU-0051",
        job_protocol=JOB_IMPLEMENTATION_PROTOCOL,
        callable_identity=CALLABLE_IDENTITY,
        job_implementation_identity=(
            volatility_duration_replay_job_implementation_sha256()
        ),
        permit_expiry_utc=PERMIT_EXPIRY_UTC,
        boundary=ReplayAuthorityBoundary(
            sequence=PREDECESSOR_REVISION,
            event_id=PREDECESSOR_EVENT_ID,
        ),
        display_name="STU-0051 completed-bar P0 correction replay family",
    )


def semantic_question_lineage() -> SemanticQuestionLineageProposal:
    return SemanticQuestionLineageProposal(
        predecessor_study_id=PREDECESSOR_STUDY_ID,
        successor_study_id=STUDY_ID,
        predecessor_core_id=PREDECESSOR_CORE_ID,
        successor_core_id=PREDECESSOR_CORE_ID,
        relation=SemanticQuestionRelation.CONTINUATION,
        rationale=(
            "Repeat the same registered causal question after the spread-time "
            "audit invalidated the prior completed-bar implementation evidence."
        ),
        basis_record_ids=(
            f"study-open:{PREDECESSOR_STUDY_ID}",
            f"study-close:{PREDECESSOR_CLOSE_RECORD_ID}",
        ),
    )


def build_design(writer: StateWriter):
    design = build_volatility_duration_replay_profile_design(
        writer,
        spec=mission_spec(),
        historical_family_authority_id=HISTORICAL_FAMILY_AUTHORITY_ID,
        semantic_question_lineage=semantic_question_lineage(),
    )
    if design.controlled_chassis.architecture_family != EXPECTED_ARCHITECTURE_FAMILY:
        raise RuntimeError("STU-0051 corrected architecture family drifted")
    return require_borrowed_production_profile(writer, design)


def main(argv: Sequence[str] | None = None) -> None:
    summary = run_fixed_hold_replay_command(
        repository_root=ROOT,
        design_builder=build_design,
        job_runner=execute_volatility_duration_replay_job,
        job_implementation_materializer=(
            materialize_volatility_duration_replay_job_implementation
        ),
        argv=argv,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
