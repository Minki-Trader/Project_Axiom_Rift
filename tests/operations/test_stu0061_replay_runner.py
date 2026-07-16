from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.permits import PermitAuthority, PermitKind, SubjectKind
from axiom_rift.operations.running_job import RunningJobAuthority, RunningJobExecution
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.research.fixed_hold_family_trace import (
    fixed_hold_subject_inference_families,
    fixed_hold_trace_implementation_sha256,
)
from axiom_rift.research.portfolio import (
    BatchSpec,
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
from tests.operations.test_writer import (
    FIXED_EXPIRY,
    FIXED_NOW,
    OBSERVED_MATERIAL_ID,
    executable_spec,
    initiative_objective,
    job_spec,
    mission_goal,
    study_question,
)


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "scripts" / "run_stu0061_analog_fixed_hold_replay.py"
CORRECTION_PATH = ROOT / "scripts" / "apply_exhaustive_audit_replay_correction.py"


def _runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "run_stu0061_analog_fixed_hold_replay_test",
        RUNNER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _correction() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "apply_exhaustive_audit_replay_correction_test",
        CORRECTION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(kind: str, record_id: str) -> IndexRecord:
    return IndexRecord(
        kind=kind,
        record_id=record_id,
        subject=f"Test:{record_id}",
        status="open",
        fingerprint="1" * 64,
        payload={},
    )


class _Journal:
    def read_event_at(
        self,
        *,
        offset: int,
        expected_sequence: int,
        expected_event_id: str,
    ) -> dict[str, object]:
        assert offset == 900
        assert expected_sequence == 78
        assert expected_event_id == "8" * 64
        return {"previous_event_id": "7" * 64}


class _Writer:
    def __init__(self, index_path: Path) -> None:
        self.index_path = index_path
        self.journal = _Journal()

    def read_control(self) -> dict[str, object]:
        return {
            "heads": {
                "journal": {
                    "event_id": "6" * 64,
                    "sequence": 77,
                }
            }
        }


def test_real_writer_requires_full_vectorized_family_before_first_job(
    tmp_path: Path,
) -> None:
    writer = StateWriter(
        tmp_path / "writer",
        permit_authority=PermitAuthority(b"r" * 32),
        clock=lambda: FIXED_NOW,
        engineering_fixture=True,
        foundation_root=ROOT,
    )
    writer.initialize_ready()
    writer.open_mission(
        mission_id="MIS-FIXED-HOLD-REGRESSION",
        goal=mission_goal("fixed-hold vectorized family"),
        operation_id="fixed-hold-open-mission",
    )
    initiative_id = "INI-FIXED-HOLD-REGRESSION"
    writer.open_initiative(
        initiative_id=initiative_id,
        objective=initiative_objective("fixed-hold vectorized family"),
        operation_id="fixed-hold-open-initiative",
    )

    study_id = "STU-FIXED-HOLD-REGRESSION"
    question = study_question("fixed-hold vectorized family")
    proposal = {"mechanism": "exact family registration before engine entry"}
    study_hash = writer.study_input_hash(
        question=question,
        material_identity=OBSERVED_MATERIAL_ID,
        semantic_proposal=proposal,
    )
    study_permit = writer.issue_permit(
        kind=PermitKind.STUDY,
        subject_kind=SubjectKind.INITIATIVE,
        subject_id=initiative_id,
        input_hash=study_hash,
        actions=("open_study",),
        scope=("study",),
        expires_at_utc=FIXED_EXPIRY,
        one_shot=True,
        operation_id="fixed-hold-permit-study",
    )
    opened_study = writer.open_study(
        study_id=study_id,
        question=question,
        material_identity=OBSERVED_MATERIAL_ID,
        material_display_name="fixed-hold vectorized family fixture",
        semantic_proposal=proposal,
        permit=study_permit,
        operation_id="fixed-hold-open-study",
    )

    members = tuple(
        executable_spec(f"fixed-hold-member-{ordinal:02d}")
        for ordinal in range(1, 5)
    )
    family = ConcurrentFamilyManifest(
        evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
        executable_ids=tuple(member.identity for member in members),
    )
    batch = BatchSpec(
        batch_id="BAT-FIXED-HOLD-REGRESSION",
        study_id=study_id,
        study_hash=opened_study.result["study_hash"],
        display_name="fixed-hold vectorized family regression",
        max_trials=len(members),
        max_compute_seconds=120,
        max_wall_seconds=120,
        stop_rule="stop after the exact vectorized family",
        concurrent_family=family,
        acceptance_profile={"causality": "required", "unknown_cost": "reject"},
        adaptive_basis={
            "uncertainty": "fixture",
            "causal_complexity": "fixture",
            "surface_curvature": "fixture",
            "compute_cost": "bounded",
            "expected_information_value": "positive",
            "portfolio_opportunity_cost": "declared",
        },
    )
    batch_permit = writer.issue_permit(
        kind=PermitKind.BATCH,
        subject_kind=SubjectKind.STUDY,
        subject_id=study_id,
        input_hash=batch.identity.removeprefix("batch:"),
        actions=("open_batch",),
        scope=("batch",),
        expires_at_utc=FIXED_EXPIRY,
        one_shot=True,
        operation_id="fixed-hold-permit-batch",
    )
    writer.open_batch(
        batch_spec=batch,
        permit=batch_permit,
        operation_id="fixed-hold-open-batch",
    )

    writer.register_trial(
        executable=members[0],
        operation_id="fixed-hold-register-member-01",
    )
    member01_subject = {"kind": "Executable", "id": members[0].identity}
    with pytest.raises(TransitionError, match=r"3 missing"):
        writer.declare_job(
            spec=job_spec(writer, member01_subject),
            operation_id="fixed-hold-reject-partial-family-job",
        )
    assert writer.read_control()["scientific"]["active_job"] is None

    for ordinal, member in enumerate(members[1:], start=2):
        writer.register_trial(
            executable=member,
            operation_id=f"fixed-hold-register-member-{ordinal:02d}",
        )
    declared = writer.declare_job(
        spec=job_spec(writer, member01_subject),
        operation_id="fixed-hold-declare-member-01-job",
    )
    job_permit = writer.issue_permit(
        kind=PermitKind.JOB,
        subject_kind=SubjectKind.JOB,
        subject_id=declared.result["job_id"],
        input_hash=declared.result["job_hash"],
        actions=("start_job",),
        scope=("job",),
        expires_at_utc=FIXED_EXPIRY,
        one_shot=True,
        operation_id="fixed-hold-permit-member-01-job",
    )
    started = writer.start_job(
        permit=job_permit,
        operation_id="fixed-hold-start-member-01-job",
    )
    execution = RunningJobExecution.from_mapping(started.result["execution"])
    context = RunningJobAuthority(
        writer.root,
        foundation_root=ROOT,
    ).verify_running_job_execution(
        execution,
        expected_callable_identity="fixture.callable",
        expected_evidence_subject=member01_subject,
    )

    assert context["spec"]["evidence_subject"] == member01_subject
    assert context["batch_id"] == batch.identity
    assert writer.read_control()["scientific"]["active_job"]["status"] == "running"
    with LocalIndex(writer.index_path) as index:
        head = index.event_head(f"batch-trials:{batch.identity}")
        assert head is not None and head.sequence == len(members)
        assert tuple(
            index.event_record(f"batch-trials:{batch.identity}", ordinal).record_id
            for ordinal in range(1, len(members) + 1)
        ) == tuple(member.identity for member in members)


def test_runner_derives_natural_ids_and_current_boundary(tmp_path: Path) -> None:
    module = _runner()
    index_path = tmp_path / "index.sqlite"
    with LocalIndex(index_path) as index:
        index.put_many(
            (
                _record("initiative-open", "INI-0022"),
                _record("initiative-open", "INI-0023"),
                _record("study-open", "STU-0110"),
                _record("study-open", "STU-0111"),
            )
        )
    writer = _Writer(index_path)
    with LocalIndex(index_path) as index:
        assert module.derive_replay_display_ids(index) == (
            "INI-0024",
            "STU-0112",
            "BAT-0112",
        )
        boundary = module.derive_replay_boundary(
            writer,
            index=index,
            control=writer.read_control(),
        )
    assert boundary.sequence == 77
    assert boundary.event_id == "6" * 64


def test_runner_recovers_predecessor_from_first_operation(tmp_path: Path) -> None:
    module = _runner()
    index_path = tmp_path / "index.sqlite"
    with LocalIndex(index_path) as index:
        index.put_many(
            (
                _record("initiative-open", "INI-0023"),
                _record("study-open", "STU-0111"),
                IndexRecord(
                    kind="operation",
                    record_id=module.OPERATION_PREFIX + "open-initiative",
                    subject="Test:operation",
                    status="success",
                    fingerprint="2" * 64,
                    payload={
                        "event_kind": "initiative_opened",
                        "result": {"initiative_id": "INI-0024"},
                    },
                    authority_sequence=78,
                    authority_event_id="8" * 64,
                    authority_offset=900,
                ),
            )
        )
    writer = _Writer(index_path)
    with LocalIndex(index_path) as index:
        boundary = module.derive_replay_boundary(
            writer,
            index=index,
            control=writer.read_control(),
        )
    assert boundary.sequence == 77
    assert boundary.event_id == "7" * 64


def test_runner_contains_no_frozen_future_state_boundary() -> None:
    source = RUNNER_PATH.read_text(encoding="ascii")
    assert "PREDECESSOR_REVISION" not in source
    assert "PREDECESSOR_EVENT_ID" not in source
    assert 'INITIATIVE_ID = "INI-0024"' not in source
    assert 'STUDY_ID = "STU-0112"' not in source
    assert 'records_by_kind("trial")' not in source
    assert "historical_family_stu0061" not in source
    assert "reviewed_historical_family_authority" not in source
    assert "open_stable_index" in source


def test_frozen_family_separates_recorded_and_current_trace_lineage() -> None:
    module = _runner()
    correction = _correction()
    obligation_id = (
        "historical-replay-obligation:"
        "56799cac8878850c33c0fe59b35ae43425d8ea0f2446f3db1db66c592f63adc8"
    )
    expected_configuration_ids = (
        "knn_multiscale_state_25-analog-h24",
        "knn_multiscale_state_25-inverse-h24",
        "knn_return_control_25-analog-h24",
        "knn_return_control_25-inverse-h24",
    )
    expected_historical_ids = (
        "executable:80e19339aa1562ab73a1922c1e595163d3d38963c955f46d9c8700b0830af463",
        "executable:050d071fae20cef41beecd5caf356f645ad4c3bcc16749e2fa5179f3a511dac7",
        "executable:4fe8293577a9aa4292bca8e5170b39528b45faeec7c7fe4453851c227869e8df",
        "executable:61a3e085beb97af8ab8251125463bd3106cdebdbac511915b0434f07f14589e8",
    )
    recorded_stu0112_ids = (
        "executable:553c767510031ea77d57cbe70d35b9de1314254af1d49c0795aad362976dea5c",
        "executable:b028937f186b1ca33b82f31e2790075b96af7afa8904cb1700dd0a80f0ad7eed",
        "executable:6aa80ec9dab1d48689c1fc10a05e212a876a9c4c613baa411d021739555c45aa",
        "executable:e64047e1c40dc25234e69aedab3de0b36eda2aa813904e527f1a47aa307404ad",
    )
    current_prospective_ids = (
        "executable:803e572b7fed0ad39bff7f5c84d146507c9ed3c12ec80ee638e26a77c833559a",
        "executable:39f08e4ba558d34c902d2995fc87a75c13779fd82d7e6c9daf3971fd8d758abd",
        "executable:07bc05c86c65cb20157bd5dc1c04349e45dfda18eca6c0700ce158bc8724c8e8",
        "executable:519b156bcc67fa67e0939f73a8cbe4748240d69404e859b4c080b31713711f61",
    )
    current_trace_sha256 = (
        "84dea5ecff142bc348f802e252d294b160db0bc197199ce2b96295bd9594e8ec"
    )
    family_authority = correction._historical_family_authority()
    members = module.ordered_members(
        study_id="STU-0112",
        historical_context_count=622,
        original_family_end_global_exposure_count=492,
        historical_family_authority=family_authority,
    )

    assert module.TARGET_OBLIGATION_ID == obligation_id
    assert tuple(member.ordinal for member in members) == (1, 2, 3, 4)
    assert tuple(member.configuration_id for member in members) == (
        expected_configuration_ids
    )
    assert tuple(
        member.historical_reference_executable_id for member in members
    ) == expected_historical_ids
    assert tuple(member.executable.identity for member in members) == (
        current_prospective_ids
    )
    assert tuple(
        sorted(member.executable.identity for member in members)
    ) == tuple(sorted(current_prospective_ids))
    assert tuple(
        member.executable.to_identity_payload()["parameters"][
            module.ANALOG_FIXED_HOLD_REPLAY_CONTEXT_PARAMETER
        ]
        for member in members
    ) == (622, 622, 622, 622)
    assert tuple(
        member.executable.to_identity_payload()["parameters"][
            module.ANALOG_FIXED_HOLD_REPLAY_ORIGINAL_END_PARAMETER
        ]
        for member in members
    ) == (492, 492, 492, 492)
    targets = tuple(
        member
        for member in members
        if member.historical_reference_executable_id
        == family_authority.family.target_historical_executable_id
    )
    assert len(targets) == 1
    assert targets[0].ordinal == 4
    assert targets[0].executable.identity == current_prospective_ids[3]
    assert fixed_hold_trace_implementation_sha256() == current_trace_sha256
    assert set(current_prospective_ids).isdisjoint(recorded_stu0112_ids)
    for member in members:
        current_payload = member.executable.to_identity_payload()
        current_engine = str(current_payload["engine_contract"])
        current_token = f"fixed_hold_trace_{current_trace_sha256}"
        assert current_engine.count(current_token) == 1
        assert current_engine.split(":")[-1] == current_token
    for member in members:
        inference_families = fixed_hold_subject_inference_families(
            member.job_plan.definition,
            targets[0].executable.identity,
        )
        assert tuple(
            inference_families["selection_family"]["ordered_member_ids"]
        ) == tuple(sorted(current_prospective_ids))


def test_runner_recovers_one_to_three_registered_family_members(
    tmp_path: Path,
) -> None:
    module = _runner()
    correction = _correction()
    family_authority = correction._historical_family_authority()
    study_id = "STU-0112"
    study_hash = "8" * 64
    batch_spec = {"study_hash": study_hash, "study_id": study_id}
    batch_digest = canonical_digest(
        domain="batch-spec",
        payload=batch_spec,
    )
    batch_id = f"batch:{batch_digest}"
    historical_context_count = 622
    members = module.ordered_members(
        study_id=study_id,
        historical_context_count=historical_context_count,
        original_family_end_global_exposure_count=492,
        historical_family_authority=family_authority,
    )
    prior_count = historical_context_count - 18
    prior = tuple(
        IndexRecord(
            kind="trial",
            record_id=f"executable:{ordinal:064x}",
            subject="Batch:prior",
            status="evaluated",
            fingerprint=f"{ordinal:064x}",
            payload={"study_id": "STU-PRIOR"},
            authority_sequence=ordinal,
            authority_event_id=f"{ordinal:064x}",
            authority_offset=ordinal,
        )
        for ordinal in range(1, prior_count + 1)
    )
    study = IndexRecord(
        kind="study-open",
        record_id=study_id,
        subject=f"Study:{study_id}",
        status="open",
        fingerprint=study_hash,
        payload={"spec": {"study_id": study_id}},
    )
    batch = IndexRecord(
        kind="batch-open",
        record_id=batch_id,
        subject=f"Study:{study_id}",
        status="open",
        fingerprint=batch_digest,
        payload={"batch_hash": batch_digest, "spec": batch_spec},
        event_stream=f"study-batches:{study_id}",
        event_sequence=1,
    )
    family = tuple(
        IndexRecord(
            kind="trial",
            record_id=member.executable.identity,
            subject=f"Batch:{batch_id}",
            status="evaluated",
            fingerprint=member.executable.identity.removeprefix("executable:"),
            payload={
                "executable": member.executable.to_identity_payload(),
                "study_id": study_id,
            },
            event_stream=f"batch-trials:{batch_id}",
            event_sequence=member.ordinal,
            authority_sequence=999 + member.ordinal,
            authority_event_id=f"{999 + member.ordinal:064x}",
            authority_offset=999 + member.ordinal,
        )
        for member in members
    )

    for registered_count in (1, 2, 3):
        path = tmp_path / f"partial-{registered_count}.sqlite"
        with LocalIndex(path) as index:
            index.rebuild(
                (study, batch, *prior, *family[:registered_count])
            )
            with patch.object(
                index,
                "records_by_kind",
                side_effect=AssertionError("global trial scan"),
            ), patch.object(
                module,
                "project_historical_family_end_global_exposure_count",
                return_value=492,
            ):
                context, original_end = module.derive_historical_context(
                    index.read_only(),
                    foundation_root=ROOT,
                    study_id=study_id,
                    historical_family=family_authority.family,
                )
            with pytest.raises(ValueError, match="family is incomplete"):
                module.project_frozen_family_exposure_context(
                    index.read_only(),
                    prior_global_exposure_floor=18,
                    study_id=study_id,
                    batch_id=batch_id,
                    expected_family_size=4,
                    parameter_name=(
                        module.ANALOG_FIXED_HOLD_REPLAY_CONTEXT_PARAMETER
                    ),
                    allow_unregistered=False,
                )
        assert context.prior_global_exposure_count == historical_context_count
        assert original_end == 492
        assert context.family_executable_ids == tuple(
            member.executable.identity
            for member in members[:registered_count]
        )
        module.require_historical_context(
            context=context,
            historical_context_count=historical_context_count,
            original_family_end_global_exposure_count=original_end,
            members=members,
        )

    wrong_prefix = type(context)(
        prior_global_exposure_count=historical_context_count,
        family_executable_ids=(members[1].executable.identity,),
        first_family_authority_sequence=1_000,
    )
    with pytest.raises(RuntimeError, match="historical exposure context drifted"):
        module.require_historical_context(
            context=wrong_prefix,
            historical_context_count=historical_context_count,
            original_family_end_global_exposure_count=492,
            members=members,
        )
