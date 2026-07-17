from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from axiom_rift.core.identity import (
    ComponentSpec,
    ExecutableSpec,
    canonical_digest,
)
from axiom_rift.operations.replay_projection import (
    initial_obligation_record,
    prepare_execution_progress,
    require_study_execution_complete,
)
from axiom_rift.operations.replay_study_admission import (
    ReplayRegistrationState,
    ReplayStudyAdmissionError,
    inspect_replay_study_registration,
)
from axiom_rift.research.portfolio import (
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
)
from axiom_rift.research.replay_obligation import (
    HistoricalReplayObligation,
    derive_historical_replay_obligation,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
from tests.operations.test_replay_partial_admission import (
    MISSION_ID,
    STUDY_ID,
    _open_batch,
)


DECISION_ID = "decision:" + "d" * 64
MATERIAL_IDENTITY = "material:" + "e" * 64
CONTROL_REFERENCE_ID = "executable:" + "c" * 64


def _historical_executable_payload(token: int) -> dict[str, object]:
    return {
        "schema": "replay_member_lineage_history.v1",
        "token": token,
    }


def _adjudication_payload(token: int) -> dict[str, object]:
    executable = _historical_executable_payload(token)
    return {
        "adjudication": {
            "candidate_eligible": False,
            "claims": [{"claim_id": f"claim-{token}"}],
            "criteria": [{"criterion_id": f"criterion-{token}"}],
        },
        "audit_artifact_hash": f"{token + 10:064x}",
        "completion_record_id": f"{token + 20:064x}",
        "disposition": "replay_required",
        "executable_id": "executable:"
        + canonical_digest(domain="executable", payload=executable),
        "measurement_artifact_hash": f"{token + 30:064x}",
        "reason_codes": ["missing_exact_uncertainty"],
        "replay_priority": "p1",
        "schema": "historical_scientific_adjudication.v2",
        "study_close_record_id": f"{token + 40:064x}",
        "study_id": f"STU-HIST-{token:04d}",
        "validation_plan_hash": f"{token + 50:064x}",
    }


def _obligations(count: int) -> tuple[HistoricalReplayObligation, ...]:
    return tuple(
        derive_historical_replay_obligation(
            governing_mission_id=MISSION_ID,
            historical_adjudication_id=(
                f"historical-adjudication:{token:064x}"
            ),
            adjudication_payload=_adjudication_payload(token),
        )
        for token in range(1, count + 1)
    )


def _adjudication_records(
    obligations: tuple[HistoricalReplayObligation, ...],
) -> tuple[IndexRecord, ...]:
    return tuple(
        IndexRecord(
            kind="historical-scientific-adjudication",
            record_id=obligation.historical_adjudication_id,
            subject=f"Study:{obligation.original_study_id}",
            status="replay_required",
            fingerprint=f"{token:064x}",
            payload=_adjudication_payload(token),
        )
        for token, obligation in enumerate(obligations, start=1)
    )


def _replay_manifest(reference: str, token: int) -> dict[str, object]:
    return {
        "component_manifests": [
            {
                "schema": "replay_member_lineage_component.v1",
                "spec": {
                    "parameter_fields": [
                        "historical_reference_executable_id"
                    ],
                    "token": token,
                },
            }
        ],
        "parameters": {
            "historical_reference_executable_id": reference,
            "token": token,
        },
        "schema": "replay_member_lineage_executable.v1",
    }


def _control_manifest() -> dict[str, object]:
    return {
        "component_manifests": [
            {
                "schema": "replay_member_lineage_component.v1",
                "spec": {
                    "parameter_fields": [
                        "historical_reference_executable_id"
                    ],
                    "role": "nonselected_control",
                },
            }
        ],
        "parameters": {
            "historical_reference_executable_id": CONTROL_REFERENCE_ID,
            "role": "nonselected_control",
        },
        "schema": "replay_member_lineage_control.v1",
    }


def _executable_id(manifest: dict[str, object]) -> str:
    return "executable:" + canonical_digest(
        domain="executable",
        payload=manifest,
    )


def _trial_authority_records(
    *,
    batch_id: str,
    executable_id: str,
    executable_manifest: dict[str, object],
    ordinal: int,
    replay_obligation_ids: tuple[str, ...] | None,
) -> tuple[IndexRecord, IndexRecord, IndexRecord, IndexRecord]:
    authority_sequence = 100 + ordinal
    event_id = f"{authority_sequence:064x}"
    operation_id = f"register-member-lineage-{ordinal}"
    result = {
        "cache_hit": False,
        "global_multiplicity": ordinal,
        "trial_delta": 1,
    }
    payload: dict[str, object] = {
        "engineering_fixture": False,
        "executable": executable_manifest,
        "material_identity": MATERIAL_IDENTITY,
        "mission_id": MISSION_ID,
        "portfolio_axis_id": None,
        "portfolio_axis_identity": None,
        "portfolio_decision_id": DECISION_ID,
        "portfolio_snapshot_id": None,
        "scheduler_eligible": False,
        "scientific_eligible": True,
        "study_id": STUDY_ID,
        "trial_delta": 1,
    }
    if replay_obligation_ids is not None:
        payload["replay_obligation_ids"] = list(replay_obligation_ids)
    trial = IndexRecord(
        kind="trial",
        record_id=executable_id,
        subject=f"Batch:{batch_id}",
        status="evaluated",
        fingerprint=executable_id.removeprefix("executable:"),
        payload=payload,
        event_stream=f"batch-trials:{batch_id}",
        event_sequence=ordinal,
        authority_sequence=authority_sequence,
        authority_event_id=event_id,
        authority_offset=0,
    )
    accounting_id = canonical_digest(
        domain="material-trial",
        payload={
            "material_identity": MATERIAL_IDENTITY,
            "executable_id": executable_id,
        },
    )
    accounting = IndexRecord(
        kind="trial-accounting",
        record_id=accounting_id,
        subject=f"Material:{MATERIAL_IDENTITY}",
        status="counted",
        fingerprint=executable_id.removeprefix("executable:"),
        payload={
            "executable_id": executable_id,
            "global_multiplicity": ordinal,
            "study_id": STUDY_ID,
        },
        event_stream=f"material-trial:{MATERIAL_IDENTITY}",
        event_sequence=ordinal,
        authority_sequence=authority_sequence,
        authority_event_id=event_id,
        authority_offset=0,
    )
    operation = IndexRecord(
        kind="operation",
        record_id=operation_id,
        subject=f"Executable:{executable_id}",
        status="success",
        fingerprint=canonical_digest(
            domain="replay-member-lineage-operation",
            payload={"ordinal": ordinal},
        ),
        payload={"event_kind": "trial_registered", "result": result},
        authority_sequence=authority_sequence,
        authority_event_id=event_id,
        authority_offset=0,
    )
    journal = IndexRecord(
        kind="journal-event",
        record_id=event_id,
        subject="Control:fixture",
        status="trial_registered",
        fingerprint=event_id,
        payload={"operation_id": operation_id},
        event_stream="control",
        event_sequence=authority_sequence,
        authority_sequence=authority_sequence,
        authority_event_id=event_id,
        authority_offset=0,
    )
    return trial, accounting, operation, journal


def _registration_fixture(
    tmp_path: Path,
    *,
    obligation_count: int,
    legacy_full_study_lineage: bool,
) -> tuple[
    LocalIndex,
    IndexRecord,
    IndexRecord,
    tuple[HistoricalReplayObligation, ...],
]:
    obligations = _obligations(obligation_count)
    manifests = tuple(
        _replay_manifest(obligation.original_executable_id, token)
        for token, obligation in enumerate(obligations, start=1)
    ) + (_control_manifest(),)
    ordered_members = tuple(
        sorted(
            ((_executable_id(manifest), manifest) for manifest in manifests),
            key=lambda item: item[0],
        )
    )
    family = ConcurrentFamilyManifest(
        evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
        executable_ids=tuple(item[0] for item in ordered_members),
    )
    obligation_ids = tuple(sorted(item.identity for item in obligations))
    study = IndexRecord(
        kind="study-open",
        record_id=STUDY_ID,
        subject=f"Mission:{MISSION_ID}",
        status="open",
        fingerprint="a" * 64,
        payload={
            "material_identity": MATERIAL_IDENTITY,
            "mission_id": MISSION_ID,
            "portfolio_axis_id": None,
            "portfolio_axis_identity": None,
            "portfolio_decision_id": DECISION_ID,
            "portfolio_snapshot_id": None,
            "prior_global_multiplicity": 0,
            "prior_material_trial_count": 0,
            "replay_obligation_ids": list(obligation_ids),
        },
    )
    batch_id = "batch:" + "b" * 64
    batch = IndexRecord(
        kind="batch-open",
        record_id=batch_id,
        subject=f"Study:{STUDY_ID}",
        status="open",
        fingerprint="b" * 64,
        payload={
            "spec": {
                "acceptance_profile": {
                    "concurrent_family": family.to_identity_payload(),
                },
                "max_trials": family.family_size,
            }
        },
    )
    index = LocalIndex(tmp_path / "member-lineage.sqlite")
    index.put_many(
        (
            *_adjudication_records(obligations),
            *(initial_obligation_record(item) for item in obligations),
            study,
            batch,
        )
    )
    for ordinal, (executable_id, manifest) in enumerate(
        ordered_members,
        start=1,
    ):
        matched, progress = prepare_execution_progress(
            index,
            study_record=study,
            batch_record=batch,
            executable_id=executable_id,
            executable_payload=manifest,
        )
        index.put_many(progress)
        lineage = (
            obligation_ids
            if legacy_full_study_lineage
            else matched if matched else None
        )
        index.put_many(
            _trial_authority_records(
                batch_id=batch_id,
                executable_id=executable_id,
                executable_manifest=manifest,
                ordinal=ordinal,
                replay_obligation_ids=lineage,
            )
        )
    return index, study, batch, obligations


def _typed_replay_executable(reference: str) -> ExecutableSpec:
    component = ComponentSpec(
        display_name="typed replay member fixture component",
        protocol="feature.engineering_fixture.v1",
        implementation="fixture.component",
        spec={
            "parameter_fields": ["historical_reference_executable_id"],
            "tag": "typed-replay-member",
        },
    )
    return ExecutableSpec(
        display_name="typed replay member fixture executable",
        components=(component,),
        parameters={
            "historical_reference_executable_id": reference,
            "tag": "typed-replay-member",
        },
        data_contract="data:engineering_fixture",
        split_contract="split:engineering_fixture",
        clock_contract="clock:completed_bar_fixture",
        cost_contract="cost:engineering_fixture",
        engine_contract="engine:engineering_fixture",
    )


def test_writer_records_only_exact_member_lineage_and_omits_control(
    tmp_path: Path,
) -> None:
    writer, _, _ = _open_batch(tmp_path)
    obligations = _obligations(2)
    selected = _typed_replay_executable(
        obligations[0].original_executable_id
    )
    control = _typed_replay_executable(CONTROL_REFERENCE_ID)
    admission = IndexRecord(
        kind="replay-implementation-admission",
        record_id="replay-implementation-admission:" + "f" * 64,
        subject=f"Study:{STUDY_ID}",
        status="active",
        fingerprint="f" * 64,
        payload={
            "request": {
                "executable_manifests": [
                    selected.to_identity_payload(),
                    control.to_identity_payload(),
                ]
            },
            "source_closure_authority": {
                "schema": "fixture_current_source_authority.v1"
            },
        },
    )
    obligation_ids = tuple(sorted(item.identity for item in obligations))
    projection = LocalIndex(tmp_path / "writer-member-lineage.sqlite")
    projection.put_many(
        (
            *_adjudication_records(obligations),
            *(initial_obligation_record(item) for item in obligations),
        )
    )
    original_get = LocalIndex.get

    def replay_study_get(
        index: LocalIndex,
        kind: str,
        record_id: str,
    ) -> IndexRecord | None:
        record = original_get(index, kind, record_id)
        if kind != "study-open" or record_id != STUDY_ID or record is None:
            return record
        return replace(
            record,
            payload={
                **record.payload,
                "mission_id": MISSION_ID,
                "portfolio_decision_id": DECISION_ID,
                "replay_obligation_ids": list(obligation_ids),
            },
        )

    real_prepare_execution_progress = prepare_execution_progress

    def projected_progress(
        _index: LocalIndex,
        **kwargs: object,
    ) -> tuple[tuple[str, ...], list[IndexRecord]]:
        return real_prepare_execution_progress(
            projection,
            **kwargs,  # type: ignore[arg-type]
        )

    try:
        with (
            patch.object(LocalIndex, "get", new=replay_study_get),
            patch.object(
                writer,
                "_study_replay_implementation_admission",
                return_value=admission,
            ),
            patch.object(
                writer,
                "_require_replay_registration_source_authority",
                return_value=None,
            ),
            patch(
                "axiom_rift.operations.replay_projection."
                "prepare_execution_progress",
                side_effect=projected_progress,
            ),
        ):
            writer.register_trial(
                executable=selected,
                operation_id="register-plural-replay-selected-member",
            )
            writer.register_trial(
                executable=control,
                operation_id="register-plural-replay-control-member",
            )
    finally:
        projection.close()

    with LocalIndex(writer.index_path) as index:
        selected_trial = index.get(
            "engineering-evaluation-fixture",
            selected.identity,
        )
        control_trial = index.get(
            "engineering-evaluation-fixture",
            control.identity,
        )
    assert selected_trial is not None
    assert selected_trial.payload["replay_obligation_ids"] == [
        obligations[0].identity
    ]
    assert control_trial is not None
    assert "replay_obligation_ids" not in control_trial.payload


def test_exact_plural_member_lineage_is_usable_and_execution_complete(
    tmp_path: Path,
) -> None:
    index, study, batch, obligations = _registration_fixture(
        tmp_path,
        obligation_count=2,
        legacy_full_study_lineage=False,
    )
    try:
        inspection = inspect_replay_study_registration(
            index,
            study_record=study,
            batch_record=batch,
        ).require_usable()
        assert inspection.state is ReplayRegistrationState.COMPLETE
        assert inspection.legacy_lineage_projection is False
        assert require_study_execution_complete(
            index,
            mission_id=MISSION_ID,
            study=study,
        ) == tuple(sorted(item.identity for item in obligations))
    finally:
        index.close()


def test_ambiguous_legacy_plural_full_study_lineage_is_rejected(
    tmp_path: Path,
) -> None:
    index, study, batch, _ = _registration_fixture(
        tmp_path,
        obligation_count=2,
        legacy_full_study_lineage=True,
    )
    try:
        inspection = inspect_replay_study_registration(
            index,
            study_record=study,
            batch_record=batch,
        )
        assert inspection.state is ReplayRegistrationState.COMPLETE
        assert inspection.legacy_lineage_projection is True
        with pytest.raises(
            ReplayStudyAdmissionError,
            match="replay trial stream is not the exact frozen family prefix",
        ):
            inspection.require_usable()
    finally:
        index.close()


def test_legacy_singleton_full_study_lineage_remains_usable(
    tmp_path: Path,
) -> None:
    index, study, batch, obligations = _registration_fixture(
        tmp_path,
        obligation_count=1,
        legacy_full_study_lineage=True,
    )
    try:
        inspection = inspect_replay_study_registration(
            index,
            study_record=study,
            batch_record=batch,
        ).require_usable()
        assert inspection.state is ReplayRegistrationState.COMPLETE
        assert inspection.legacy_lineage_projection is False
        assert require_study_execution_complete(
            index,
            mission_id=MISSION_ID,
            study=study,
        ) == (obligations[0].identity,)
    finally:
        index.close()
