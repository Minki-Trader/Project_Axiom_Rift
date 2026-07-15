from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType
from unittest.mock import patch

import pytest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations import replay_projection as replay_projection_module
from axiom_rift.operations.replay_projection import (
    obligation_heads,
    require_satisfaction_invalidation_record,
)
from axiom_rift.operations.permits import PermitAuthority, PermitKind, SubjectKind
from axiom_rift.operations.running_job import RunningJobAuthority, RunningJobExecution
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.research.fixed_hold_family_trace import (
    fixed_hold_subject_inference_families,
)
from axiom_rift.research.portfolio import (
    BatchSpec,
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
)
from axiom_rift.storage.evidence import EvidenceStore
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
PREDECESSOR_REVISION = 5_333
PREDECESSOR_AUTHORITY_DIGEST = (
    "76358fc4032e756916dc8250c86511e4c6aefcf488940e2a3b47fd3bca07c8a1"
)
EXPECTED_INVALIDATION_MANIFEST_HASH = (
    "bd4fb7dec0854a3ce08468bacc9a89c416aa3b272f9f46d8ac8e29356fdac883"
)
EXPECTED_OBLIGATION_ID = (
    "historical-replay-obligation:"
    "56799cac8878850c33c0fe59b35ae43425d8ea0f2446f3db1db66c592f63adc8"
)
EXPECTED_CONFIGURATION_IDS = (
    "knn_multiscale_state_25-analog-h24",
    "knn_multiscale_state_25-inverse-h24",
    "knn_return_control_25-analog-h24",
    "knn_return_control_25-inverse-h24",
)
EXPECTED_HISTORICAL_EXECUTABLE_IDS = (
    "executable:80e19339aa1562ab73a1922c1e595163d3d38963c955f46d9c8700b0830af463",
    "executable:050d071fae20cef41beecd5caf356f645ad4c3bcc16749e2fa5179f3a511dac7",
    "executable:4fe8293577a9aa4292bca8e5170b39528b45faeec7c7fe4453851c227869e8df",
    "executable:61a3e085beb97af8ab8251125463bd3106cdebdbac511915b0434f07f14589e8",
)
EXPECTED_CURRENT_EXECUTABLE_IDS = (
    "executable:553c767510031ea77d57cbe70d35b9de1314254af1d49c0795aad362976dea5c",
    "executable:b028937f186b1ca33b82f31e2790075b96af7afa8904cb1700dd0a80f0ad7eed",
    "executable:6aa80ec9dab1d48689c1fc10a05e212a876a9c4c613baa411d021739555c45aa",
    "executable:e64047e1c40dc25234e69aedab3de0b36eda2aa813904e527f1a47aa307404ad",
)
EXPECTED_CANONICAL_FAMILY_IDS = tuple(
    sorted(EXPECTED_CURRENT_EXECUTABLE_IDS)
)


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


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _canonical_authority_fingerprints() -> dict[str, tuple[int, str]]:
    journal_root = ROOT / "records" / "journal"
    paths = (
        ROOT / "state" / "control.json",
        *tuple(sorted(path for path in journal_root.rglob("*") if path.is_file())),
        ROOT / "local" / "index.sqlite",
    )
    return {
        path.relative_to(ROOT).as_posix(): (path.stat().st_size, _sha256_file(path))
        for path in paths
    }


def _copy_canonical_authority(sandbox_root: Path) -> None:
    (sandbox_root / "state").mkdir(parents=True)
    (sandbox_root / "local").mkdir(parents=True)
    (sandbox_root / "records").mkdir(parents=True)
    shutil.copy2(
        ROOT / "state" / "control.json",
        sandbox_root / "state" / "control.json",
    )
    shutil.copy2(
        ROOT / "local" / "index.sqlite",
        sandbox_root / "local" / "index.sqlite",
    )
    shutil.copy2(
        ROOT / "local" / "state.writer.lock",
        sandbox_root / "local" / "state.writer.lock",
    )
    shutil.copytree(
        ROOT / "records" / "journal",
        sandbox_root / "records" / "journal",
    )
    frozen_family = Path(
        "src/axiom_rift/research/historical_family_stu0061.py"
    )
    (sandbox_root / frozen_family).parent.mkdir(parents=True)
    shutil.copy2(ROOT / frozen_family, sandbox_root / frozen_family)


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
            ):
                context = module.derive_historical_context(
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
        assert context.family_executable_ids == tuple(
            member.executable.identity
            for member in members[:registered_count]
        )
        module.require_historical_context(
            context=context,
            historical_context_count=historical_context_count,
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
            members=members,
        )


def test_root_no_argument_runner_fails_closed_at_pre_activation_drift(
    tmp_path: Path,
) -> None:
    control = json.loads((ROOT / "state" / "control.json").read_text("ascii"))
    if (
        control.get("revision") != PREDECESSOR_REVISION
        or control.get("authority", {}).get("manifest_digest")
        != PREDECESSOR_AUTHORITY_DIGEST
    ):
        pytest.skip("canonical authority correction is already active")
    before = _canonical_authority_fingerprints()
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        (sys.executable, str(RUNNER_PATH)),
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "authority or Foundation input content drifted" in result.stderr
    assert "stable-head validation failed; rerun the stage with recovery" in (
        result.stderr
    )
    assert _canonical_authority_fingerprints() == before


def test_typed_correction_sandbox_builds_exact_current_family_read_only(
    tmp_path: Path,
) -> None:
    before = _canonical_authority_fingerprints()
    module = _runner()
    correction = _correction()
    if subprocess.run(
        (
            "git",
            "cat-file",
            "-e",
            f"{correction.PREDECESSOR_COMMIT}:OPERATING_DIRECTION.md",
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
    ).returncode:
        pytest.skip(
            "exact predecessor Git object is absent from the independent "
            "index-tree sandbox"
        )
    assert module.TARGET_OBLIGATION_ID == (
        EXPECTED_OBLIGATION_ID
    )

    sandbox_root = tmp_path / "corrected-repository"
    _copy_canonical_authority(sandbox_root)
    canonical_control = json.loads(
        (ROOT / "state" / "control.json").read_text("ascii")
    )
    authority_paths = correction._authority_paths(canonical_control)
    prospective_digest = correction._manifest_digest(authority_paths)
    canonical_digest = canonical_control["authority"]["manifest_digest"]
    if canonical_digest not in {
        PREDECESSOR_AUTHORITY_DIGEST,
        prospective_digest,
    }:
        pytest.skip("canonical authority is outside the reviewed correction boundary")

    if canonical_digest == PREDECESSOR_AUTHORITY_DIGEST:
        replacements = correction._authority_replacements(authority_paths)
        with correction._predecessor_foundation(authority_paths) as predecessor:
            predecessor_writer = StateWriter(
                sandbox_root,
                engineering_fixture=True,
                foundation_root=predecessor,
            )
            predecessor_writer.migrate_authority(
                replacements=replacements,
                reason=correction.AUTHORITY_REASON,
                operation_id=correction.AUTHORITY_OPERATION_ID,
                allow_active_stable_boundary=True,
            )

    writer = StateWriter(
        sandbox_root,
        engineering_fixture=True,
        foundation_root=ROOT,
    )
    canonical_evidence = EvidenceStore(ROOT / "local" / "evidence")
    sandbox_evidence_root = (sandbox_root / "local" / "evidence").resolve()
    original_read_verified = EvidenceStore.read_verified

    def read_sandbox_or_canonical(
        store: EvidenceStore,
        identity: str,
    ) -> bytes:
        target, _relative = store._target(identity)
        if store._root == sandbox_evidence_root and not target.is_file():
            return original_read_verified(canonical_evidence, identity)
        return original_read_verified(store, identity)

    with patch.object(
        EvidenceStore,
        "read_verified",
        new=read_sandbox_or_canonical,
    ):
        with LocalIndex.open_read_only(writer.index_path) as index:
            matches = tuple(
                (obligation, head)
                for obligation, head in obligation_heads(
                    index,
                    mission_id=module.MISSION_ID,
                )
                if obligation.identity == EXPECTED_OBLIGATION_ID
            )
        assert len(matches) == 1
        _obligation, head = matches[0]
        if head.status == "satisfied":
            plan = writer.plan_historical_replay_satisfaction_invalidation(
                obligation_id=EXPECTED_OBLIGATION_ID
            )
            assert plan["audit_manifest_sha256"] == (
                EXPECTED_INVALIDATION_MANIFEST_HASH
            )
            assert plan["audit_manifest"]["defect"]["code"] == (
                "selection_family_size_mismatch"
            )
            artifact = writer.evidence.finalize(
                canonical_bytes(plan["audit_manifest"])
            )
            assert artifact.sha256 == EXPECTED_INVALIDATION_MANIFEST_HASH
            writer.invalidate_historical_replay_satisfaction(
                obligation_id=EXPECTED_OBLIGATION_ID,
                audit_manifest_hash=artifact.sha256,
                operation_id=correction.INVALIDATION_OPERATION_ID,
                historical_family_authority=(
                    correction._historical_family_authority()
                ),
            )
        elif not (
            head.status == "pending"
            and head.kind
            == "historical-replay-satisfaction-invalidation"
        ):
            pytest.skip("canonical replay correction boundary has advanced")

        with LocalIndex.open_read_only(writer.index_path) as index:
            obligation, pending = next(
                (obligation, head)
                for obligation, head in obligation_heads(
                    index,
                    mission_id=module.MISSION_ID,
                )
                if obligation.identity == EXPECTED_OBLIGATION_ID
            )
            manifest = require_satisfaction_invalidation_record(
                index,
                obligation=obligation,
                record=pending,
            )
        assert pending.status == "pending"
        assert manifest.defect.code.value == "selection_family_size_mismatch"
        assert sha256(canonical_bytes(manifest.to_identity_payload())).hexdigest() == (
            EXPECTED_INVALIDATION_MANIFEST_HASH
        )

        with patch.object(
            replay_projection_module,
            "require_satisfaction",
            side_effect=AssertionError(
                "recorded satisfaction was re-adjudicated by current protocol"
            ),
        ), patch.object(
            replay_projection_module,
            "derive_satisfaction_invalidation_manifest",
            side_effect=AssertionError(
                "stored pending invalidation was re-derived from current protocol"
            ),
        ):
            design = module.build_design(writer)

    assert design.spec.initiative_id == "INI-0024"
    assert design.spec.study_id == "STU-0112"
    assert design.spec.batch_display_id == "BAT-0112"
    assert design.spec.target_obligation_id == EXPECTED_OBLIGATION_ID
    assert tuple(member.ordinal for member in design.members) == (1, 2, 3, 4)
    assert tuple(member.configuration_id for member in design.members) == (
        EXPECTED_CONFIGURATION_IDS
    )
    assert tuple(
        member.historical_reference_executable_id for member in design.members
    ) == EXPECTED_HISTORICAL_EXECUTABLE_IDS
    assert tuple(
        member.executable.identity for member in design.members
    ) == EXPECTED_CURRENT_EXECUTABLE_IDS
    assert design.batch_spec.concurrent_family.executable_ids == (
        EXPECTED_CANONICAL_FAMILY_IDS
    )
    inference_families = fixed_hold_subject_inference_families(
        design.members[0].job_plan.definition,
        design.target_member.executable.identity,
    )
    assert tuple(
        inference_families["selection_family"]["ordered_member_ids"]
    ) == design.batch_spec.concurrent_family.executable_ids
    assert tuple(
        member.executable.to_identity_payload()["parameters"][
            module.ANALOG_FIXED_HOLD_REPLAY_CONTEXT_PARAMETER
        ]
        for member in design.members
    ) == (622, 622, 622, 622)
    assert design.target_member.ordinal == 4
    assert design.target_member.historical_reference_executable_id == (
        EXPECTED_HISTORICAL_EXECUTABLE_IDS[3]
    )
    assert design.target_member.executable.identity == (
        EXPECTED_CURRENT_EXECUTABLE_IDS[3]
    )
    assert design.work_decision.replay_obligation_ids == (
        EXPECTED_OBLIGATION_ID,
    )
    assert design.proposal["historical_obligation_id"] == EXPECTED_OBLIGATION_ID
    assert _canonical_authority_fingerprints() == before
