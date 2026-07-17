"""Run the exact engineering reentry for the deferred STU-0051 replay."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import sys


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
    ReplayAuthorityBoundary,
    ReplayAxisAdmission,
    ReplayInitiativeLifecycle,
    materialize_replay_implementation_preflight_request,
)
from axiom_rift.operations.replay_workflow_recovery import (  # noqa: E402
    derive_replay_admission_boundary_identity,
)
from axiom_rift.operations.validation import (  # noqa: E402
    EvidenceValidatorRegistry,
)
from axiom_rift.operations.volatility_duration_fixed_hold_profile import (  # noqa: E402
    build_volatility_duration_fixed_hold_profile_design,
    project_volatility_duration_fixed_hold_exposure_context,
    require_volatility_duration_fixed_hold_family_authority,
    require_volatility_duration_fixed_hold_registration_prefix,
    volatility_duration_fixed_hold_members,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.replay_obligation import (  # noqa: E402
    ReplayResumeEvidence,
)
from axiom_rift.research.semantic_question import (  # noqa: E402
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)
from axiom_rift.research.validation_v2 import (  # noqa: E402
    ScientificAdjudicationValidatorV2,
)
from axiom_rift.research.volatility_duration_fixed_hold_job import (  # noqa: E402
    CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL,
    execute_volatility_duration_fixed_hold_job,
    materialize_volatility_duration_fixed_hold_job_implementation,
    volatility_duration_fixed_hold_job_implementation_sha256,
)


MISSION_ID = "MIS-0006"
INITIATIVE_ID = "INI-0025"
STUDY_ID = "STU-0114"
BATCH_DISPLAY_ID = "BAT-0114"
TARGET_OBLIGATION_ID = (
    "historical-replay-obligation:"
    "a8da0fda7ff53c1951c59bf2bdc4fb8db722cf21c2090dd2e5220c5d2069a904"
)
HISTORICAL_FAMILY_AUTHORITY_ID = (
    "historical-family-authority:"
    "a1996ed0e967f188c6a68fa8ef512996d7754d998f829961e6872107b145bea3"
)
REPLACED_PREFLIGHT_ID = (
    "job-implementation-preflight:"
    "8f99f4bc3c1a044172d49b0364ffb1c3c6d45d4bda82fe4bd95647dde05edae3"
)
DEFERRAL_ID = (
    "historical-replay-deferral:"
    "c53aa79d86aae1a6d161b95bd7975c167eb8595255005b23c488358d069e60ec"
)
RESUME_CONDITION_ID = (
    "historical-replay-resume-condition:"
    "56016b9492eea589abcf23ec6c735b79a7da1c6961e0cd96f25c18122325d71c"
)
DIAGNOSIS_ID = (
    "diagnosis:"
    "3d4d8fa540c01cfbbd4c41bcbfb48e12c1dfea6655c14458534138d7ff90bda1"
)
PREDECESSOR_STUDY_ID = "STU-0113"
PREDECESSOR_CORE_ID = (
    "semantic-question-core:"
    "c37c2ce1bdb5942d70b3380603dacc07733c8cd52bafd43ca0dc9645af20d408"
)
PREDECESSOR_CLOSE_RECORD_ID = (
    "7db4d9545422e36fbb489df753fcc1976c9a17cdaaccdfca8d10281d9b32d136"
)
PREDECESSOR_REVISION = 5410
PREDECESSOR_EVENT_ID = (
    "1131db9825d7741847bda901ab56b4b3df3eb6a7400854819a76672a9be87319"
)
EXPECTED_ARCHITECTURE_FAMILY = (
    "architecture-family:"
    "33b88b0cb30b96538792fe5ef9a091d478eb91fa16b63844380b65ce0031abde"
)
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"
PREPARATION_OPERATION_PREFIX = "p0-stu0051-fixed-hold-reentry-v1-"
OPERATION_PREFIX = PREPARATION_OPERATION_PREFIX + "run-"
REPLACEMENT_PREFLIGHT_OPERATION_ID = (
    PREPARATION_OPERATION_PREFIX + "replacement-preflight"
)
RESUME_OPERATION_ID = PREPARATION_OPERATION_PREFIX + "resume-replay"


def mission_spec(
    *,
    boundary: ReplayAuthorityBoundary | None = None,
) -> FixedHoldReplayMissionSpec:
    return FixedHoldReplayMissionSpec(
        axis_admission=ReplayAxisAdmission.REUSE_EXACT_AXIS,
        initiative_lifecycle=(
            ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE
        ),
        mission_id=MISSION_ID,
        initiative_id=INITIATIVE_ID,
        study_id=STUDY_ID,
        batch_display_id=BATCH_DISPLAY_ID,
        axis_id="axis-stu0051-volatility-duration-replay-bridge",
        bridge_axis_id="axis-stu0051-volatility-duration-replay-bridge",
        operation_prefix=OPERATION_PREFIX,
        decision_prefix="DEC-P0-STU0051-FIXED-HOLD-REENTRY-V1",
        target_obligation_id=TARGET_OBLIGATION_ID,
        original_study_id="STU-0051",
        job_protocol=JOB_IMPLEMENTATION_PROTOCOL,
        callable_identity=CALLABLE_IDENTITY,
        job_implementation_identity=(
            volatility_duration_fixed_hold_job_implementation_sha256()
        ),
        permit_expiry_utc=PERMIT_EXPIRY_UTC,
        boundary=(
            ReplayAuthorityBoundary(
                sequence=PREDECESSOR_REVISION,
                event_id=PREDECESSOR_EVENT_ID,
            )
            if boundary is None
            else boundary
        ),
        display_name="STU-0051 fixed-hold engineering reentry family",
    )


def semantic_question_lineage() -> SemanticQuestionLineageProposal:
    return SemanticQuestionLineageProposal(
        predecessor_study_id=PREDECESSOR_STUDY_ID,
        successor_study_id=STUDY_ID,
        predecessor_core_id=PREDECESSOR_CORE_ID,
        successor_core_id=PREDECESSOR_CORE_ID,
        relation=SemanticQuestionRelation.ENGINEERING_REENTRY,
        rationale=(
            "Rerun the unchanged causal question with the accepted complete "
            "implementation closure after the prior pre-Job engineering gap."
        ),
        basis_record_ids=(
            f"job-implementation-preflight:{REPLACED_PREFLIGHT_ID}",
            f"study-close:{PREDECESSOR_CLOSE_RECORD_ID}",
            f"study-diagnosis:{DIAGNOSIS_ID}",
            f"study-open:{PREDECESSOR_STUDY_ID}",
        ),
    )


def _writer() -> StateWriter:
    return StateWriter(
        ROOT,
        validation_registry=EvidenceValidatorRegistry(
            (ScientificAdjudicationValidatorV2(),)
        ),
    )


def _replacement_members(writer: StateWriter):
    spec = mission_spec()
    authority = require_volatility_duration_fixed_hold_family_authority(
        writer,
        spec=spec,
        historical_family_authority_id=HISTORICAL_FAMILY_AUTHORITY_ID,
    )
    exposure = project_volatility_duration_fixed_hold_exposure_context(
        writer,
        spec=spec,
        historical_family=authority.family,
    )
    members = volatility_duration_fixed_hold_members(
        spec,
        exposure_context=exposure,
        historical_family=authority.family,
        historical_family_authority_id=authority.identity,
    )
    require_volatility_duration_fixed_hold_registration_prefix(
        writer,
        spec=spec,
        members=members,
        exposure_context=exposure,
    )
    return members


def record_replacement_preflight(writer: StateWriter) -> Mapping[str, object]:
    request = materialize_replay_implementation_preflight_request(
        writer,
        spec=mission_spec(),
        members=_replacement_members(writer),
        job_implementation_materializer=(
            materialize_volatility_duration_fixed_hold_job_implementation
        ),
        replacement_for_preflight_id=REPLACED_PREFLIGHT_ID,
    )
    transition = writer.record_replay_job_implementation_preflight(
        request=request,
        operation_id=REPLACEMENT_PREFLIGHT_OPERATION_ID,
    )
    return {
        "mode": "replacement_preflight",
        "request_identity": request.identity,
        **dict(transition.result),
    }


def _accepted_replacement_preflight_id(writer: StateWriter) -> str:
    with writer.open_stable_index() as (_control, index):
        operation = index.get("operation", REPLACEMENT_PREFLIGHT_OPERATION_ID)
        result = (
            None
            if operation is None
            else operation.payload.get("result")
        )
        preflight_id = (
            None
            if not isinstance(result, Mapping)
            else result.get("preflight_id")
        )
        preflight = (
            None
            if not isinstance(preflight_id, str)
            else index.get("job-implementation-preflight", preflight_id)
        )
        stream_head = (
            None
            if preflight is None
            or not isinstance(preflight.event_stream, str)
            else index.event_head(preflight.event_stream)
        )
    if (
        operation is None
        or operation.status != "success"
        or preflight is None
        or preflight.status != "accepted"
        or preflight.payload.get("replacement_for_preflight_id")
        != REPLACED_PREFLIGHT_ID
        or stream_head is None
        or stream_head.record_id != preflight.record_id
    ):
        raise RuntimeError("accepted replacement preflight is absent or stale")
    return preflight.record_id


def resume_replay(writer: StateWriter) -> Mapping[str, object]:
    preflight_id = _accepted_replacement_preflight_id(writer)
    evidence = ReplayResumeEvidence(
        obligation_id=TARGET_OBLIGATION_ID,
        deferral_id=DEFERRAL_ID,
        resume_condition_id=RESUME_CONDITION_ID,
        trigger_record_id=preflight_id,
    )
    transition = writer.resume_historical_replay_obligations(
        resumes=(evidence,),
        operation_id=RESUME_OPERATION_ID,
    )
    return {
        "mode": "resume_replay",
        "resume_evidence_id": evidence.identity,
        **dict(transition.result),
    }


def _admission_spec(writer: StateWriter) -> FixedHoldReplayMissionSpec:
    with writer.open_stable_index() as (control, index):
        sequence, event_id = derive_replay_admission_boundary_identity(
            writer,
            index=index,
            control=control,
            first_operation_id=OPERATION_PREFIX + "replay-decision",
        )
        resume = index.get("operation", RESUME_OPERATION_ID)
        result = None if resume is None else resume.payload.get("result")
    if (
        resume is None
        or resume.status != "success"
        or resume.payload.get("event_kind")
        != "historical_replay_obligations_resumed"
        or not isinstance(result, Mapping)
        or result.get("resumed_replay_obligation_ids")
        != [TARGET_OBLIGATION_ID]
        or result.get("resume_condition_ids") != [RESUME_CONDITION_ID]
        or resume.authority_sequence != sequence
        or resume.authority_event_id != event_id
    ):
        raise RuntimeError(
            "fixed-hold reentry admission is not the exact resume boundary"
        )
    return mission_spec(
        boundary=ReplayAuthorityBoundary(
            sequence=sequence,
            event_id=event_id,
        )
    )


def build_design(writer: StateWriter):
    design = build_volatility_duration_fixed_hold_profile_design(
        writer,
        spec=_admission_spec(writer),
        historical_family_authority_id=HISTORICAL_FAMILY_AUTHORITY_ID,
        semantic_question_lineage=semantic_question_lineage(),
    )
    if (
        design.controlled_chassis.architecture_family
        != EXPECTED_ARCHITECTURE_FAMILY
    ):
        raise RuntimeError("STU-0051 replacement architecture family drifted")
    return require_borrowed_production_profile(writer, design)


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Admit, resume, inspect, or execute the exact STU-0051 "
            "engineering reentry."
        )
    )
    parser.add_argument(
        "--action",
        choices=("preflight", "resume", "plan", "study-close", "diagnose"),
        default="plan",
    )
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--study-close-event-id")
    parser.add_argument("--study-close-revision", type=int)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    arguments = _parse_arguments(argv)
    if arguments.action == "preflight":
        if (
            arguments.recover
            or arguments.study_close_event_id is not None
            or arguments.study_close_revision is not None
        ):
            raise RuntimeError("replacement preflight rejects replay-stage arguments")
        summary = record_replacement_preflight(_writer())
    elif arguments.action == "resume":
        if (
            arguments.recover
            or arguments.study_close_event_id is not None
            or arguments.study_close_revision is not None
        ):
            raise RuntimeError("replacement resume rejects replay-stage arguments")
        summary = resume_replay(_writer())
    else:
        replay_arguments: list[str] = []
        if arguments.action != "plan":
            replay_arguments.extend(("--stage", arguments.action))
        if arguments.recover:
            replay_arguments.append("--recover")
        if arguments.study_close_event_id is not None:
            replay_arguments.extend(
                ("--study-close-event-id", arguments.study_close_event_id)
            )
        if arguments.study_close_revision is not None:
            replay_arguments.extend(
                (
                    "--study-close-revision",
                    str(arguments.study_close_revision),
                )
            )
        summary = run_fixed_hold_replay_command(
            repository_root=ROOT,
            design_builder=build_design,
            job_runner=execute_volatility_duration_fixed_hold_job,
            job_implementation_materializer=(
                materialize_volatility_duration_fixed_hold_job_implementation
            ),
            argv=replay_arguments,
        )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
