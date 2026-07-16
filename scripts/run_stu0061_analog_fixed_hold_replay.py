from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.fixed_hold_replay_cli import (  # noqa: E402
    run_fixed_hold_replay_command,
)
from axiom_rift.operations.fixed_hold_replay_workflow import (  # noqa: E402
    FixedHoldReplayMember,
    FixedHoldReplayMissionSpec,
    ReplayAxisAdmission,
    ReplayAuthorityBoundary,
    ReplayInitiativeLifecycle,
    build_fixed_hold_replay_design,
)
from axiom_rift.operations.running_job import RunningJobAuthority  # noqa: E402
from axiom_rift.operations.recorded_transition_authority import (  # noqa: E402
    require_same_event_operation_result,
)
from axiom_rift.operations.scientific_history import (  # noqa: E402
    project_frozen_family_exposure_context,
    project_historical_family_end_global_exposure_count,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.analog_fixed_hold_replay import (  # noqa: E402
    ANALOG_FIXED_HOLD_REPLAY_CONTEXT_PARAMETER,
    ANALOG_FIXED_HOLD_REPLAY_ORIGINAL_END_PARAMETER,
    analog_fixed_hold_replay_configurations,
    analog_fixed_hold_replay_controlled_chassis,
    analog_fixed_hold_replay_executable,
)
from axiom_rift.research.analog_fixed_hold_replay_job import (  # noqa: E402
    CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL,
    analog_fixed_hold_replay_job_implementation_sha256,
    build_analog_fixed_hold_replay_job_plan,
    execute_analog_fixed_hold_replay_job,
    materialize_analog_fixed_hold_replay_job_implementation,
)
from axiom_rift.research.fixed_hold_family_trace import (  # noqa: E402
    FIXED_HOLD_REPLAY_CRITERIA,
)
from axiom_rift.research.historical_family_binding import (  # noqa: E402
    HistoricalFamilyAuthority,
    HistoricalFamilySpec,
    historical_family_authority_from_payload,
)
from axiom_rift.research.replay_obligation import (  # noqa: E402
    historical_replay_obligation_from_identity_payload,
)
from axiom_rift.research.replay_exposure import (  # noqa: E402
    FrozenFamilyExposureContext,
)
from axiom_rift.research.trials import TrialAccountant  # noqa: E402
from axiom_rift.storage.index import LocalIndex, LocalIndexView  # noqa: E402


MISSION_ID = "MIS-0006"
AXIS_ID = "axis-stu0061-analog-state-replay-correction-v3"
BRIDGE_AXIS_ID = "axis-stu0017-composite-consensus-replay-bridge"
OPERATION_PREFIX = "p1-stu0061-analog-fixed-hold-replay-v3-"
DECISION_PREFIX = "DEC-P1-STU0061-CORRECTION-V3"
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"
TARGET_OBLIGATION_ID = (
    "historical-replay-obligation:"
    "56799cac8878850c33c0fe59b35ae43425d8ea0f2446f3db1db66c592f63adc8"
)
def require_historical_family_authority(
    index: LocalIndex | LocalIndexView,
) -> HistoricalFamilyAuthority:
    accepted = tuple(
        record
        for record in index.records_by_subject_status(
            f"ReplayObligation:{TARGET_OBLIGATION_ID}",
            "accepted",
        )
        if record.kind == "historical-family-authority"
    )
    if len(accepted) != 1:
        raise RuntimeError(
            "STU-0061 requires one accepted historical family authority"
        )
    record = accepted[0]
    actual = historical_family_authority_from_payload(record.payload)
    initial = index.get(
        "historical-replay-obligation",
        TARGET_OBLIGATION_ID,
    )
    try:
        obligation = historical_replay_obligation_from_identity_payload(
            None if initial is None else initial.payload.get("obligation")
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError("STU-0061 replay obligation is malformed") from exc
    event_kind, result = require_same_event_operation_result(
        index,
        record=record,
        expected_event_kinds=frozenset(
            {"historical_replay_satisfaction_invalidated"}
        ),
    )
    if (
        event_kind != "historical_replay_satisfaction_invalidated"
        or actual.replay_obligation_id != TARGET_OBLIGATION_ID
        or record.record_id != actual.identity
        or record.subject != f"ReplayObligation:{TARGET_OBLIGATION_ID}"
        or record.status != "accepted"
        or record.fingerprint
        != actual.identity.removeprefix("historical-family-authority:")
        or obligation.identity != TARGET_OBLIGATION_ID
        or actual.family.original_study_id != obligation.original_study_id
        or actual.family.target_historical_executable_id
        != obligation.original_executable_id
        or result.get("historical_family_authority_id") != actual.identity
        or result.get("replay_obligation_id") != TARGET_OBLIGATION_ID
    ):
        raise RuntimeError("STU-0061 historical family authority drifted")
    return actual


def _operation_result(
    index: LocalIndex | LocalIndexView,
    operation_id: str,
) -> Mapping[str, object] | None:
    record = index.get("operation", operation_id)
    if record is None:
        return None
    result = record.payload.get("result")
    if record.status != "success" or not isinstance(result, Mapping):
        raise RuntimeError(f"replay operation is malformed: {operation_id}")
    return result


def _next_display_id(
    index: LocalIndex | LocalIndexView,
    *,
    record_kind: str,
    prefix: str,
) -> str:
    ordinals: list[int] = []
    for record in index.records_by_kind_prefix(record_kind, prefix):
        suffix = record.record_id.removeprefix(prefix)
        if record.record_id != prefix + suffix or not suffix.isdigit():
            raise RuntimeError(f"{record_kind} identity is not canonical")
        ordinals.append(int(suffix))
    if not ordinals:
        raise RuntimeError(f"prior {record_kind} identity is unavailable")
    return f"{prefix}{max(ordinals) + 1:04d}"


def _owned_or_next_display_id(
    index: LocalIndex | LocalIndexView,
    *,
    operation_suffix: str,
    result_field: str,
    record_kind: str,
    prefix: str,
) -> str:
    result = _operation_result(
        index,
        OPERATION_PREFIX + operation_suffix,
    )
    if result is None:
        return _next_display_id(
            index,
            record_kind=record_kind,
            prefix=prefix,
        )
    value = result.get(result_field)
    if type(value) is not str or not value.startswith(prefix):
        raise RuntimeError(f"owned {result_field} identity is invalid")
    return value


def derive_replay_boundary(
    writer: StateWriter,
    *,
    index: LocalIndex | LocalIndexView,
    control: Mapping[str, object],
) -> ReplayAuthorityBoundary:
    """Bind the live stable head, or reconstruct the first operation parent."""

    first = index.get("operation", OPERATION_PREFIX + "open-initiative")
    if first is None:
        head = control.get("heads", {}).get("journal", {})
        return ReplayAuthorityBoundary(
            sequence=int(head["sequence"]),
            event_id=str(head["event_id"]),
        )
    if (
        first.status != "success"
        or first.authority_sequence is None
        or first.authority_event_id is None
        or first.authority_offset is None
        or first.authority_sequence < 2
    ):
        raise RuntimeError("replay first-operation authority is incomplete")
    event = writer.journal.read_event_at(
        offset=first.authority_offset,
        expected_sequence=first.authority_sequence,
        expected_event_id=first.authority_event_id,
    )
    previous = event.get("previous_event_id")
    if type(previous) is not str:
        raise RuntimeError("replay predecessor event is unavailable")
    return ReplayAuthorityBoundary(
        sequence=first.authority_sequence - 1,
        event_id=previous,
    )


def derive_replay_display_ids(
    index: LocalIndex | LocalIndexView,
) -> tuple[str, str, str]:
    """Derive natural IDs once and recover the same IDs after partial work."""

    initiative_id = _owned_or_next_display_id(
        index,
        operation_suffix="open-initiative",
        result_field="initiative_id",
        record_kind="initiative-open",
        prefix="INI-",
    )
    study_id = _owned_or_next_display_id(
        index,
        operation_suffix="open-study",
        result_field="study_id",
        record_kind="study-open",
        prefix="STU-",
    )
    batch_result = _operation_result(
        index,
        OPERATION_PREFIX + "open-batch",
    )
    if batch_result is not None:
        batch_id = batch_result.get("batch_id")
        batch_record = (
            None
            if type(batch_id) is not str
            else index.get("batch-open", batch_id)
        )
        batch_display_id = (
            None
            if batch_record is None
            else batch_record.payload.get("display_id")
        )
        if type(batch_display_id) is not str:
            raise RuntimeError("owned Batch display identity is invalid")
    else:
        batch_display_id = "BAT-" + study_id.removeprefix("STU-")
    expected_batch = "BAT-" + study_id.removeprefix("STU-")
    if batch_display_id != expected_batch:
        raise RuntimeError("replay Study and Batch display identities diverged")
    return initiative_id, study_id, batch_display_id


def derive_historical_context(
    index: LocalIndex | LocalIndexView,
    *,
    foundation_root: Path,
    study_id: str,
    historical_family: HistoricalFamilySpec,
) -> tuple[FrozenFamilyExposureContext, int]:
    floor = TrialAccountant.from_foundation(
        foundation_root
    ).prior_global_multiplicity_floor
    prospective = project_frozen_family_exposure_context(
        index,
        prior_global_exposure_floor=floor,
        study_id=study_id,
        batch_id=None,
        expected_family_size=historical_family.family_size,
        parameter_name=ANALOG_FIXED_HOLD_REPLAY_CONTEXT_PARAMETER,
        allow_unregistered=True,
        allow_partial_registered=True,
    )
    original_end = project_historical_family_end_global_exposure_count(
        index,
        prior_global_exposure_floor=floor,
        family=historical_family,
    )
    return prospective, original_end


def mission_spec(
    writer: StateWriter,
    *,
    initiative_id: str,
    study_id: str,
    batch_display_id: str,
    boundary: ReplayAuthorityBoundary,
) -> FixedHoldReplayMissionSpec:
    return FixedHoldReplayMissionSpec(
        axis_admission=ReplayAxisAdmission.ADD_NEW_MECHANISM,
        initiative_lifecycle=(
            ReplayInitiativeLifecycle.OWN_BOUNDED_INITIATIVE
        ),
        mission_id=MISSION_ID,
        initiative_id=initiative_id,
        study_id=study_id,
        batch_display_id=batch_display_id,
        axis_id=AXIS_ID,
        bridge_axis_id=BRIDGE_AXIS_ID,
        operation_prefix=OPERATION_PREFIX,
        decision_prefix=DECISION_PREFIX,
        target_obligation_id=(
            TARGET_OBLIGATION_ID
        ),
        original_study_id="STU-0061",
        job_protocol=JOB_IMPLEMENTATION_PROTOCOL,
        callable_identity=CALLABLE_IDENTITY,
        job_implementation_identity=(
            analog_fixed_hold_replay_job_implementation_sha256()
        ),
        permit_expiry_utc=PERMIT_EXPIRY_UTC,
        boundary=boundary,
        display_name="STU-0061 exact analog-state fixed-hold replay family",
    )


def ordered_members(
    *,
    study_id: str,
    historical_context_count: int,
    original_family_end_global_exposure_count: int,
    historical_family_authority: HistoricalFamilyAuthority,
) -> tuple[FixedHoldReplayMember, ...]:
    values: list[FixedHoldReplayMember] = []
    for ordinal, configuration in enumerate(
        analog_fixed_hold_replay_configurations(
            historical_family_authority.family
        ),
        start=1,
    ):
        executable = analog_fixed_hold_replay_executable(
            configuration,
            historical_family=historical_family_authority.family,
            historical_context_prior_global_exposure_count=(
                historical_context_count
            ),
            original_family_end_global_exposure_count=(
                original_family_end_global_exposure_count
            ),
        )
        values.append(
            FixedHoldReplayMember(
                ordinal=ordinal,
                configuration_id=configuration.configuration_id,
                historical_reference_executable_id=str(
                    configuration.historical_reference_executable_id
                ),
                executable=executable,
                job_plan=build_analog_fixed_hold_replay_job_plan(
                    mission_id=MISSION_ID,
                    study_id=study_id,
                    executable_id=executable.identity,
                    historical_context_prior_global_exposure_count=(
                        historical_context_count
                    ),
                    original_family_end_global_exposure_count=(
                        original_family_end_global_exposure_count
                    ),
                    historical_family=historical_family_authority.family,
                    historical_family_authority_id=(
                        historical_family_authority.identity
                    ),
                    replay_obligation_id=TARGET_OBLIGATION_ID,
                ),
            )
        )
    members = tuple(values)
    if tuple(
        member.historical_reference_executable_id for member in members
    ) != tuple(
        member.historical_reference_executable_id
        for member in historical_family_authority.family.members
    ):
        raise RuntimeError("STU-0061 exact replay order drifted")
    return members


def require_historical_context(
    *,
    context: FrozenFamilyExposureContext,
    historical_context_count: int,
    original_family_end_global_exposure_count: int,
    members: tuple[FixedHoldReplayMember, ...],
) -> None:
    prospective = tuple(member.executable.identity for member in members)
    registered = context.family_executable_ids
    if (
        context.prior_global_exposure_count != historical_context_count
        or historical_context_count
        < original_family_end_global_exposure_count
        or len(registered) > len(prospective)
        or registered != prospective[: len(registered)]
    ):
        raise RuntimeError("STU-0061 historical exposure context drifted")


def build_design(writer: StateWriter):
    authority = RunningJobAuthority(
        writer.root,
        foundation_root=writer.foundation_root,
    )
    with authority.open_stable_index() as (control, index):
        initiative_id, study_id, batch_display_id = derive_replay_display_ids(
            index
        )
        boundary = derive_replay_boundary(
            writer,
            index=index,
            control=control,
        )
        family_authority = require_historical_family_authority(
            index,
        )
        historical_context, original_family_end = derive_historical_context(
            index,
            foundation_root=writer.foundation_root,
            study_id=study_id,
            historical_family=family_authority.family,
        )
    historical_context_count = (
        historical_context.prior_global_exposure_count
    )
    members = ordered_members(
        study_id=study_id,
        historical_context_count=historical_context_count,
        original_family_end_global_exposure_count=original_family_end,
        historical_family_authority=family_authority,
    )
    require_historical_context(
        context=historical_context,
        historical_context_count=historical_context_count,
        original_family_end_global_exposure_count=original_family_end,
        members=members,
    )
    target_id = family_authority.family.target_historical_executable_id
    targets = tuple(
        member
        for member in members
        if member.historical_reference_executable_id == target_id
    )
    if len(targets) != 1:
        raise RuntimeError("STU-0061 replay target is ambiguous")
    criterion_ids = tuple(
        sorted(str(item["criterion_id"]) for item in FIXED_HOLD_REPLAY_CRITERIA)
    )
    return build_fixed_hold_replay_design(
        writer,
        spec=mission_spec(
            writer,
            initiative_id=initiative_id,
            study_id=study_id,
            batch_display_id=batch_display_id,
            boundary=boundary,
        ),
        members=members,
        target_executable_id=targets[0].executable.identity,
        controlled_chassis=analog_fixed_hold_replay_controlled_chassis(
            historical_family=family_authority.family,
            historical_context_prior_global_exposure_count=(
                historical_context_count
            ),
            original_family_end_global_exposure_count=original_family_end,
        ),
        historical_family_manifest=family_authority.family.manifest(),
        historical_family_authority_id=family_authority.identity,
        criterion_ids=criterion_ids,
        causal_question=(
            "Does an exact prospective reconstruction of the four-member "
            "STU-0061 analog-state family preserve causal after-cost evidence "
            "under exact Batch-family selection and paired controls?"
        ),
        mechanism_family=(
            "prospective-stu0061-scoped-analog-fixed-hold-family-replay"
        ),
        why_now=(
            "the prior STU-0106 satisfaction used an invalid E01 family and "
            "the exact locally executable four-member replay is pending"
        ),
        stop_or_reopen_condition=(
            "stop after all four registered members; reopen only under the "
            "typed replay resume condition or new registered material"
        ),
    )


def main(argv: Sequence[str] | None = None) -> None:
    summary = run_fixed_hold_replay_command(
        repository_root=ROOT,
        design_builder=build_design,
        job_runner=execute_analog_fixed_hold_replay_job,
        job_implementation_materializer=(
            materialize_analog_fixed_hold_replay_job_implementation
        ),
        argv=argv,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
