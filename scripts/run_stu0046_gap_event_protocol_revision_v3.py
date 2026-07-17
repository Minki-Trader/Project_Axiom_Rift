"""Run the diagnosed STU-0046 same-question protocol revision."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.run_remaining_p1_fixed_hold_family import (  # noqa: E402
    FAMILY_ROUTES,
    INITIATIVE_ID,
    MISSION_ID,
    PERMIT_EXPIRY_UTC,
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
from axiom_rift.operations.gap_fixed_hold_profile import (  # noqa: E402
    build_gap_event_fixed_hold_v3_profile_design,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.gap_event_fixed_hold_v3_job import (  # noqa: E402
    CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL,
    execute_gap_event_fixed_hold_v3_job,
    gap_event_fixed_hold_v3_job_implementation_sha256,
    materialize_gap_event_fixed_hold_v3_job_implementation,
)
from axiom_rift.research.semantic_question import (  # noqa: E402
    SemanticQuestionCore,
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)


STUDY_ID = "STU-0117"
BATCH_DISPLAY_ID = "BAT-0117"
PREDECESSOR_STUDY_ID = "STU-0116"
PREDECESSOR_CORE_ID = (
    "semantic-question-core:"
    "eba0c28df7cb13e5a6d3f7642c91c08cc62231eb19df4c362bd273a3188ee3f6"
)
PREDECESSOR_CLOSE_ID = (
    "a6c2c0337d4048aa0327b4a2840368d10d498223ac4108f606500ae2cb81671d"
)
PREDECESSOR_DIAGNOSIS_ID = (
    "diagnosis:81d551801014e8b3a3278cefb9bab929195e61c687d20b85a4a87c9d9e3f53e6"
)
OPERATION_PREFIX = "p1-stu0046-gap-event-replay-v3-"
DECISION_PREFIX = "DEC-P1-STU0046-GAP-EVENT-V3"


def parse_arguments(
    argv: Sequence[str] | None,
) -> tuple[int, str, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--batch-display-id", required=True)
    parser.add_argument("--predecessor-revision", type=int, required=True)
    parser.add_argument("--predecessor-event-id", required=True)
    arguments, remaining = parser.parse_known_args(argv)
    if (
        arguments.study_id != STUDY_ID
        or arguments.batch_display_id != BATCH_DISPLAY_ID
    ):
        raise RuntimeError("STU-0046 v3 requires its exact natural Study boundary")
    return (
        arguments.predecessor_revision,
        arguments.predecessor_event_id,
        remaining,
    )


def mission_spec(
    *,
    predecessor_revision: int,
    predecessor_event_id: str,
) -> FixedHoldReplayMissionSpec:
    route = FAMILY_ROUTES["stu0046"]
    return FixedHoldReplayMissionSpec(
        axis_admission=ReplayAxisAdmission.REVISE_PROTOCOL,
        initiative_lifecycle=ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE,
        mission_id=MISSION_ID,
        initiative_id=INITIATIVE_ID,
        study_id=STUDY_ID,
        batch_display_id=BATCH_DISPLAY_ID,
        axis_id=route.axis_id,
        bridge_axis_id=route.axis_id,
        operation_prefix=OPERATION_PREFIX,
        decision_prefix=DECISION_PREFIX,
        target_obligation_id=route.primary_obligation_id,
        additional_obligation_ids=route.additional_obligation_ids,
        original_study_id=route.original_study_id,
        job_protocol=JOB_IMPLEMENTATION_PROTOCOL,
        callable_identity=CALLABLE_IDENTITY,
        job_implementation_identity=(
            gap_event_fixed_hold_v3_job_implementation_sha256()
        ),
        permit_expiry_utc=PERMIT_EXPIRY_UTC,
        boundary=ReplayAuthorityBoundary(
            sequence=predecessor_revision,
            event_id=predecessor_event_id,
        ),
        display_name=(
            "STU-0046 feasible-floor prospective gap-event replay family"
        ),
    )


def _profile_design(
    writer: StateWriter,
    *,
    spec: FixedHoldReplayMissionSpec,
    lineage: SemanticQuestionLineageProposal | None,
):
    route = FAMILY_ROUTES["stu0046"]
    return build_gap_event_fixed_hold_v3_profile_design(
        writer,
        spec=spec,
        historical_family_authority_id=route.primary_family_authority_id,
        additional_historical_family_authority_ids=(
            route.additional_family_authority_ids
        ),
        semantic_question_lineage=lineage,
    )


def build_design(
    writer: StateWriter,
    *,
    predecessor_revision: int,
    predecessor_event_id: str,
):
    spec = mission_spec(
        predecessor_revision=predecessor_revision,
        predecessor_event_id=predecessor_event_id,
    )
    lineage = SemanticQuestionLineageProposal(
        predecessor_study_id=PREDECESSOR_STUDY_ID,
        successor_study_id=STUDY_ID,
        predecessor_core_id=PREDECESSOR_CORE_ID,
        successor_core_id=PREDECESSOR_CORE_ID,
        relation=SemanticQuestionRelation.CONTINUATION,
        rationale=(
            "Retain the exact diagnosed question under a distinct prospective "
            "protocol whose train-only event floor is feasible before any new "
            "scientific outcome is observed; inherit no predecessor evidence."
        ),
        basis_record_ids=tuple(
            sorted(
                (
                    f"study-open:{PREDECESSOR_STUDY_ID}",
                    f"study-close:{PREDECESSOR_CLOSE_ID}",
                    f"study-diagnosis:{PREDECESSOR_DIAGNOSIS_ID}",
                )
            )
        ),
    )
    design = _profile_design(writer, spec=spec, lineage=lineage)
    successor_core_id = SemanticQuestionCore.from_question_manifest(
        design.question
    ).identity
    if successor_core_id != PREDECESSOR_CORE_ID:
        raise RuntimeError("STU-0046 v3 changed the diagnosed scientific question")
    return require_borrowed_production_profile(writer, design)


def main(argv: Sequence[str] | None = None) -> None:
    predecessor_revision, predecessor_event_id, remaining = parse_arguments(argv)
    summary = run_fixed_hold_replay_command(
        repository_root=ROOT,
        design_builder=lambda writer: build_design(
            writer,
            predecessor_revision=predecessor_revision,
            predecessor_event_id=predecessor_event_id,
        ),
        job_runner=execute_gap_event_fixed_hold_v3_job,
        job_implementation_materializer=(
            materialize_gap_event_fixed_hold_v3_job_implementation
        ),
        study_id=STUDY_ID,
        argv=remaining,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
