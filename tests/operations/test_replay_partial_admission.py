from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from unittest.mock import patch

import pytest

from axiom_rift.operations.permits import (
    PermitAuthority,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.writer import (
    RecoveryRequired,
    StateWriter,
    TransitionError,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
from tests.operations.test_writer import (
    FIXED_EXPIRY,
    FIXED_NOW,
    OBSERVED_MATERIAL_ID,
    REPO_ROOT,
    batch_spec,
    executable_spec,
    initiative_objective,
    mission_goal,
    study_question,
)


MISSION_ID = "MIS-PARTIAL-REPLAY-ADMISSION"
INITIATIVE_ID = "INI-PARTIAL-REPLAY-ADMISSION"
STUDY_ID = "STU-PARTIAL-REPLAY-ADMISSION"
OBLIGATION_ID = "historical-replay-obligation:" + "a" * 64


@dataclass(frozen=True)
class _WriterBoundary:
    control: dict[str, object]
    journal_head: object
    operation_ids: tuple[str, ...]
    state_files: tuple[tuple[str, bytes], ...]
    journal_files: tuple[tuple[str, bytes], ...]
    trial_delta_total: int
    trial_record_ids: tuple[str, ...]


def _tree_bytes(root: Path) -> tuple[tuple[str, bytes], ...]:
    if not root.exists():
        return ()
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def _boundary(writer: StateWriter) -> _WriterBoundary:
    control = writer.read_control()
    assert control is not None
    with LocalIndex(writer.index_path) as index:
        operations = index.records_by_kind("operation")
        trial_records = (
            *index.records_by_kind("trial"),
            *index.records_by_kind("engineering-evaluation-fixture"),
            *index.records_by_kind("trial-accounting"),
        )
    return _WriterBoundary(
        control=control,
        journal_head=writer.journal.tail()[0],
        operation_ids=tuple(sorted(record.record_id for record in operations)),
        state_files=_tree_bytes(writer.root / "state"),
        journal_files=_tree_bytes(writer.root / "records"),
        trial_delta_total=sum(
            int(record.payload.get("result", {}).get("trial_delta", 0))
            for record in operations
        ),
        trial_record_ids=tuple(
            sorted(record.record_id for record in trial_records)
        ),
    )


def _assert_failed_without_write(
    writer: StateWriter,
    *,
    before: _WriterBoundary,
    operation_id: str,
) -> None:
    after = _boundary(writer)
    assert after == before
    with LocalIndex(writer.index_path) as index:
        assert index.get("operation", operation_id) is None


def _open_batch(tmp_path: Path) -> tuple[StateWriter, object, object]:
    writer = StateWriter(
        tmp_path / "writer",
        permit_authority=PermitAuthority(b"r" * 32),
        clock=lambda: FIXED_NOW,
        engineering_fixture=True,
        foundation_root=REPO_ROOT,
    )
    writer.initialize_ready()
    writer.open_mission(
        mission_id=MISSION_ID,
        goal=mission_goal("partial replay implementation admission"),
        operation_id="partial-admission-open-mission",
    )
    writer.open_initiative(
        initiative_id=INITIATIVE_ID,
        objective=initiative_objective(
            "partial replay implementation admission"
        ),
        operation_id="partial-admission-open-initiative",
    )
    question = study_question("partial replay implementation admission")
    proposal = {
        "mechanism": "legacy partial replay registration boundary"
    }
    study_hash = writer.study_input_hash(
        question=question,
        material_identity=OBSERVED_MATERIAL_ID,
        semantic_proposal=proposal,
    )
    study_permit = writer.issue_permit(
        kind=PermitKind.STUDY,
        subject_kind=SubjectKind.INITIATIVE,
        subject_id=INITIATIVE_ID,
        input_hash=study_hash,
        actions=("open_study",),
        scope=("study",),
        expires_at_utc=FIXED_EXPIRY,
        one_shot=True,
        operation_id="partial-admission-study-permit",
    )
    opened = writer.open_study(
        study_id=STUDY_ID,
        question=question,
        material_identity=OBSERVED_MATERIAL_ID,
        material_display_name="partial replay fixture material",
        semantic_proposal=proposal,
        permit=study_permit,
        operation_id="partial-admission-open-study",
    )
    admitted = executable_spec("partial-replay-admitted")
    unadmitted = executable_spec("partial-replay-unadmitted")
    batch = batch_spec(
        batch_id="BAT-PARTIAL-REPLAY-ADMISSION",
        study_id=STUDY_ID,
        study_hash=opened.result["study_hash"],
        max_trials=2,
    )
    batch_permit = writer.issue_permit(
        kind=PermitKind.BATCH,
        subject_kind=SubjectKind.STUDY,
        subject_id=STUDY_ID,
        input_hash=batch.identity.removeprefix("batch:"),
        actions=("open_batch",),
        scope=("batch",),
        expires_at_utc=FIXED_EXPIRY,
        one_shot=True,
        operation_id="partial-admission-batch-permit",
    )
    writer.open_batch(
        batch_spec=batch,
        permit=batch_permit,
        operation_id="partial-admission-open-batch",
    )
    return writer, admitted, unadmitted


def _replay_study_overlay(
    *,
    admission_id: str | None,
):
    original_get = LocalIndex.get

    def get(index: LocalIndex, kind: str, record_id: str):
        record = original_get(index, kind, record_id)
        if kind != "study-open" or record_id != STUDY_ID or record is None:
            return record
        payload = {
            **record.payload,
            "replay_obligation_ids": [OBLIGATION_ID],
        }
        if admission_id is not None:
            payload["replay_implementation_admission_id"] = admission_id
        return replace(record, payload=payload)

    return patch.object(LocalIndex, "get", new=get)


def _admission(executable: object) -> IndexRecord:
    admission_id = "replay-implementation-admission:" + "b" * 64
    return IndexRecord(
        kind="replay-implementation-admission",
        record_id=admission_id,
        subject=f"Study:{STUDY_ID}",
        status="active",
        fingerprint="b" * 64,
        payload={
            "request": {
                "executable_manifests": [
                    executable.to_identity_payload()  # type: ignore[attr-defined]
                ]
            },
            "source_closure_authority": {
                "schema": "fixture_current_source_authority.v1"
            },
        },
    )


def _progress_patch():
    return patch(
        "axiom_rift.operations.replay_projection.prepare_execution_progress",
        return_value=((OBLIGATION_ID,), []),
    )


def test_legacy_replay_without_admission_fails_before_trial_write(
    tmp_path: Path,
) -> None:
    writer, admitted, _ = _open_batch(tmp_path)
    operation_id = "reject-legacy-replay-without-admission"
    before = _boundary(writer)

    with _replay_study_overlay(admission_id=None), _progress_patch():
        with pytest.raises(
            RecoveryRequired,
            match=(
                "replay trial registration requires a current "
                "implementation admission"
            ),
        ):
            writer.register_trial(
                executable=admitted,
                operation_id=operation_id,
            )

    _assert_failed_without_write(
        writer,
        before=before,
        operation_id=operation_id,
    )


def test_non_replay_trial_registration_is_unchanged(tmp_path: Path) -> None:
    writer, admitted, _ = _open_batch(tmp_path)

    with patch(
        "axiom_rift.operations.replay_projection.prepare_execution_progress",
        return_value=((), []),
    ):
        registered = writer.register_trial(
            executable=admitted,
            operation_id="register-non-replay-control",
        )

    assert registered.result["trial_delta"] == 0
    assert registered.result["cache_hit"] is False
    with LocalIndex(writer.index_path) as index:
        assert (
            index.get("engineering-evaluation-fixture", admitted.identity)
            is not None
        )
        assert index.get("operation", "register-non-replay-control") is not None


@pytest.mark.parametrize(
    ("attack", "error_type", "message"),
    (
        (
            "malformed_admission",
            RecoveryRequired,
            "Study replay implementation admission is malformed",
        ),
        (
            "unadmitted_executable",
            TransitionError,
            "Executable differs from the replay implementation admission",
        ),
        (
            "source_toctou",
            TransitionError,
            "replay implementation source authority changed after Study admission",
        ),
    ),
)
def test_replay_admission_attacks_have_zero_trial_and_state_delta(
    tmp_path: Path,
    attack: str,
    error_type: type[Exception],
    message: str,
) -> None:
    writer, admitted, unadmitted = _open_batch(tmp_path)
    admission = _admission(admitted)
    operation_id = f"reject-partial-replay-{attack}"
    before = _boundary(writer)
    executable = unadmitted if attack == "unadmitted_executable" else admitted

    if attack == "malformed_admission":
        admission_patch = patch.object(
            writer,
            "_study_replay_implementation_admission",
            side_effect=RecoveryRequired(message),
        )
        source_patch = patch.object(
            writer,
            "_require_replay_registration_source_authority",
        )
    else:
        admission_patch = patch.object(
            writer,
            "_study_replay_implementation_admission",
            return_value=admission,
        )
        source_patch = patch.object(
            writer,
            "_require_replay_registration_source_authority",
            side_effect=(
                TransitionError(message)
                if attack == "source_toctou"
                else None
            ),
        )

    with (
        _replay_study_overlay(admission_id=admission.record_id),
        _progress_patch(),
        admission_patch,
        source_patch,
    ):
        with pytest.raises(error_type, match=message):
            writer.register_trial(
                executable=executable,
                operation_id=operation_id,
            )

    _assert_failed_without_write(
        writer,
        before=before,
        operation_id=operation_id,
    )


def test_replay_admission_allows_only_its_exact_executable(
    tmp_path: Path,
) -> None:
    writer, admitted, _ = _open_batch(tmp_path)
    admission = _admission(admitted)

    with (
        _replay_study_overlay(admission_id=admission.record_id),
        _progress_patch(),
        patch.object(
            writer,
            "_study_replay_implementation_admission",
            return_value=admission,
        ),
        patch.object(
            writer,
            "_require_replay_registration_source_authority",
            return_value=None,
        ) as source_recheck,
    ):
        registered = writer.register_trial(
            executable=admitted,
            operation_id="register-exact-admitted-replay-executable",
        )

    assert registered.result["trial_delta"] == 0
    assert registered.result["cache_hit"] is False
    source_recheck.assert_called_once()
    with LocalIndex(writer.index_path) as index:
        trial = index.get(
            "engineering-evaluation-fixture",
            admitted.identity,
        )
        assert trial is not None
        assert trial.payload["replay_obligation_ids"] == [OBLIGATION_ID]
        assert (
            index.get(
                "operation",
                "register-exact-admitted-replay-executable",
            )
            is not None
        )
