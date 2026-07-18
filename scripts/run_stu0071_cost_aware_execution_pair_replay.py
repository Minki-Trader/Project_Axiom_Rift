"""Run the corrected prospective pair for the STU-0071 replay duty.

The obligation targets the STU-0071 repaired subject, while its exact
statistical control family originates in STU-0070.  The runner therefore binds
lineage to STU-0071 and family multiplicity to the Writer-recorded STU-0070
authority without importing the historical reconstruction module.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.cost_aware_execution_pair_profile import (  # noqa: E402
    build_cost_aware_execution_pair_profile_design,
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
from axiom_rift.research.cost_aware_execution_pair_runtime import (  # noqa: E402
    CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL,
    cost_aware_execution_pair_job_implementation_sha256,
    execute_cost_aware_execution_pair_job,
    materialize_cost_aware_execution_pair_job_implementation,
)
from axiom_rift.research.semantic_question import (  # noqa: E402
    SemanticQuestionCore,
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)


MISSION_ID = "MIS-0006"
INITIATIVE_ID = "INI-0025"
STUDY_ID = "STU-0121"
BATCH_DISPLAY_ID = "BAT-0121"
TARGET_OBLIGATION_ID = (
    "historical-replay-obligation:"
    "ab4d0fcd6d5f88756fbed17f32dbf2831217a7c158d043b7f85f3c69b149b63e"
)
HISTORICAL_FAMILY_AUTHORITY_ID = (
    "historical-family-authority:"
    "3ddff77adc305d07d2ee536994527f8bd40dc12e9ea8ef9615797e95fd256e29"
)
PREDECESSOR_STUDY_ID = "STU-0071"
FAMILY_ORIGIN_STUDY_ID = "STU-0070"
PREDECESSOR_CORE_ID = (
    "semantic-question-core:"
    "b61a78b5ee580a82d6261cd3ca0ae8b32f29861920ddeb639ba83dd26aacceba"
)
PREDECESSOR_CLOSE_RECORD_ID = (
    "4482cfcebcd3677a8f6bc4fc0cba22fd923593cfc711067c5ca1f3789099c15a"
)
PREDECESSOR_REVISION = 5669
PREDECESSOR_EVENT_ID = (
    "e6ceeb3608c417f8836843605302c0b982609e5f3942383b4a7544618fccb41f"
)
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"


def mission_spec() -> FixedHoldReplayMissionSpec:
    return FixedHoldReplayMissionSpec(
        axis_admission=ReplayAxisAdmission.ADD_NEW_MECHANISM,
        initiative_lifecycle=(
            ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE
        ),
        mission_id=MISSION_ID,
        initiative_id=INITIATIVE_ID,
        study_id=STUDY_ID,
        batch_display_id=BATCH_DISPLAY_ID,
        axis_id="axis-stu0071-cost-aware-execution-replay-bridge",
        bridge_axis_id="axis-stu0047-post-gap-path-replay-bridge",
        operation_prefix="p1-stu0071-cost-aware-execution-pair-replay-v1-",
        decision_prefix="DEC-P1-STU0071-COST-AWARE-PAIR",
        target_obligation_id=TARGET_OBLIGATION_ID,
        original_study_id=PREDECESSOR_STUDY_ID,
        family_origin_study_id=FAMILY_ORIGIN_STUDY_ID,
        job_protocol=JOB_IMPLEMENTATION_PROTOCOL,
        callable_identity=CALLABLE_IDENTITY,
        job_implementation_identity=(
            cost_aware_execution_pair_job_implementation_sha256()
        ),
        permit_expiry_utc=PERMIT_EXPIRY_UTC,
        boundary=ReplayAuthorityBoundary(
            sequence=PREDECESSOR_REVISION,
            event_id=PREDECESSOR_EVENT_ID,
        ),
        display_name=(
            "STU-0071 corrected completed-bar cost-aware execution pair replay"
        ),
    )


def _profile_design(
    writer: StateWriter,
    *,
    lineage: SemanticQuestionLineageProposal | None,
):
    return build_cost_aware_execution_pair_profile_design(
        writer,
        spec=mission_spec(),
        historical_family_authority_id=HISTORICAL_FAMILY_AUTHORITY_ID,
        semantic_question_lineage=lineage,
    )


def build_design(writer: StateWriter):
    preliminary = _profile_design(writer, lineage=None)
    successor_core_id = SemanticQuestionCore.from_question_manifest(
        preliminary.question
    ).identity
    relation = (
        SemanticQuestionRelation.CONTINUATION
        if successor_core_id == PREDECESSOR_CORE_ID
        else SemanticQuestionRelation.SEMANTIC_REVISION
    )
    lineage = SemanticQuestionLineageProposal(
        predecessor_study_id=PREDECESSOR_STUDY_ID,
        successor_study_id=STUDY_ID,
        predecessor_core_id=PREDECESSOR_CORE_ID,
        successor_core_id=successor_core_id,
        relation=relation,
        rationale=(
            "Replace the audit-invalid entry-time decision-input claim with "
            "one prospective completed-bar policy pair; preserve the original "
            "family only as control and multiplicity authority and transfer no "
            "historical result."
        ),
        basis_record_ids=(
            f"study-open:{PREDECESSOR_STUDY_ID}",
            f"study-close:{PREDECESSOR_CLOSE_RECORD_ID}",
        ),
    )
    design = _profile_design(writer, lineage=lineage)
    return require_borrowed_production_profile(writer, design)


def main(argv: Sequence[str] | None = None) -> None:
    summary = run_fixed_hold_replay_command(
        repository_root=ROOT,
        design_builder=build_design,
        job_runner=execute_cost_aware_execution_pair_job,
        job_implementation_materializer=(
            materialize_cost_aware_execution_pair_job_implementation
        ),
        operation_prefix=mission_spec().operation_prefix,
        study_id=STUDY_ID,
        argv=argv,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
